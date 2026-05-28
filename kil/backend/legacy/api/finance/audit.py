"""
Audit & Compliance Blueprint
==============================
Document Management, Approval Queue, SoD Enforcement,
Month-End Close Checklist, Audit Packages.
"""

import os
import uuid
from datetime import date

from flask import Blueprint, request

from .core import (
    err, fin_execute, fin_execute_returning, fin_query,
    ok, require_finance_role, row_to_dict, rows_to_list,
)
from kil.backend.core.security import require_auth

audit_fin_bp = Blueprint("finance_audit", __name__, url_prefix="/api/v1/finance/audit")

UPLOAD_DIR = os.environ.get("FINANCE_DOCS_DIR", "/tmp/finance_docs")


# ── Document Management ───────────────────────────────────────

@audit_fin_bp.get("/documents")
@require_auth
@require_finance_role
def list_documents():
    doc_type = request.args.get("doc_type")
    ref_id   = request.args.get("reference_id", type=int)

    conditions, params = ["is_deleted = FALSE"], []
    if doc_type:
        conditions.append("doc_type = %s"); params.append(doc_type)
    if ref_id:
        conditions.append("reference_id = %s"); params.append(ref_id)

    rows = fin_query(
        f"SELECT * FROM fin_documents WHERE {' AND '.join(conditions)} ORDER BY uploaded_at DESC LIMIT 100",
        params, many=True,
    )
    return ok(rows_to_list(rows))


@audit_fin_bp.post("/documents")
@require_auth
@require_finance_role
def upload_document():
    """
    Accepts multipart/form-data with fields:
      doc_type, reference_id, description
    + file in 'file' field.
    Falls back to JSON body (url/path reference) for linking existing files.
    """
    user = request.environ.get("user_email", "system")

    if request.files.get("file"):
        f         = request.files["file"]
        ext       = os.path.splitext(f.filename)[1]
        stored_fn = f"{uuid.uuid4().hex}{ext}"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        storage_path = os.path.join(UPLOAD_DIR, stored_fn)
        f.save(storage_path)
        size     = os.path.getsize(storage_path)
        mime     = f.content_type
        orig     = f.filename
        doc_type = request.form.get("doc_type", "OTHER")
        ref_id   = int(request.form.get("reference_id", 0))
        desc     = request.form.get("description")
    else:
        d = request.get_json() or {}
        if not d.get("storage_path") or not d.get("doc_type") or not d.get("reference_id"):
            return err("doc_type, reference_id, and storage_path required")
        storage_path = d["storage_path"]
        doc_type     = d["doc_type"]
        ref_id       = d["reference_id"]
        orig         = d.get("original_name", os.path.basename(storage_path))
        stored_fn    = orig
        size         = d.get("file_size")
        mime         = d.get("mime_type")
        desc         = d.get("description")

    row = fin_execute_returning(
        """
        INSERT INTO fin_documents
            (doc_type, reference_id, filename, original_name,
             file_size, mime_type, storage_path, description, uploaded_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        [doc_type, ref_id, stored_fn, orig, size, mime, storage_path, desc, user],
    )
    return ok({"id": row["id"]}, "Document uploaded", 201)


@audit_fin_bp.delete("/documents/<int:doc_id>")
@require_auth
@require_finance_role
def delete_document(doc_id: int):
    user = request.environ.get("user_email", "system")
    fin_execute(
        "UPDATE fin_documents SET is_deleted=TRUE, deleted_at=NOW(), deleted_by=%s WHERE id=%s",
        [user, doc_id],
    )
    return ok({}, "Document deleted")


# ── Approval Queue (SoD-compliant) ────────────────────────────

@audit_fin_bp.get("/approvals")
@require_auth
@require_finance_role
def list_approvals():
    status = request.args.get("status", "PENDING")
    module = request.args.get("module")

    conditions = ["status = %s"]
    params: list = [status]
    if module:
        conditions.append("module = %s"); params.append(module)

    rows = fin_query(
        f"""
        SELECT *,
               EXTRACT(EPOCH FROM (NOW() - submitted_at))/3600 AS hours_pending
        FROM   fin_approval_queue
        WHERE  {' AND '.join(conditions)}
        ORDER  BY submitted_at
        """,
        params, many=True,
    )
    return ok(rows_to_list(rows))


@audit_fin_bp.post("/approvals")
@require_auth
@require_finance_role
def submit_for_approval():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["module", "record_id"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    row = fin_execute_returning(
        """
        INSERT INTO fin_approval_queue
            (module, record_id, record_ref, description, amount,
             submitted_by, required_role)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        [d["module"], d["record_id"], d.get("record_ref"),
         d.get("description"), d.get("amount"), user,
         d.get("required_role", "finance_manager")],
    )
    return ok({"id": row["id"]}, "Submitted for approval", 201)


@audit_fin_bp.post("/approvals/<int:approval_id>/review")
@require_auth
@require_finance_role
def review_approval(approval_id: int):
    d      = request.get_json()
    user   = request.environ.get("user_email", "system")
    action = d.get("action")  # APPROVED | REJECTED
    if action not in ("APPROVED", "REJECTED"):
        return err("action must be APPROVED or REJECTED")

    # SoD check: cannot approve own submission
    aq = fin_query("SELECT submitted_by, status FROM fin_approval_queue WHERE id=%s", [approval_id])
    if not aq:
        return err("Approval not found", 404)
    if aq["status"] != "PENDING":
        return err("Not pending")
    if aq["submitted_by"] == user:
        fin_execute(
            """INSERT INTO fin_sod_violations
               (user_email, attempted_action, record_module, record_id, violation_rule, ip_address)
               VALUES (%s,'SELF_APPROVE',%s,%s,'Cannot approve own submission',%s)""",
            [user, "APPROVAL", approval_id, request.remote_addr],
        )
        return err("SoD violation: cannot approve your own submission", 403)

    fin_execute(
        """UPDATE fin_approval_queue
           SET status=%s, reviewed_by=%s, reviewed_at=NOW(), review_notes=%s
           WHERE id=%s""",
        [action, user, d.get("notes"), approval_id],
    )
    return ok({"action": action}, f"Approval {action.lower()}")


# ── Month-End Close Checklist ─────────────────────────────────

@audit_fin_bp.get("/close-checklist")
@require_auth
@require_finance_role
def close_checklist():
    period_id = request.args.get("period_id", type=int)

    if not period_id:
        period = fin_query("SELECT id FROM fin_fiscal_periods WHERE status='OPEN' ORDER BY year, period LIMIT 1")
        if not period:
            return err("No open period found")
        period_id = period["id"]

    rows = fin_query(
        """
        SELECT ci.*,
               fp.year || '-' || LPAD(fp.period::text,2,'0') AS period_label
        FROM fin_close_checklist_instances ci
        JOIN fin_fiscal_periods fp ON fp.id = ci.period_id
        WHERE ci.period_id = %s
        ORDER BY ci.sequence_no
        """,
        [period_id], many=True,
    )
    done_count  = sum(1 for r in rows if r["status"] == "DONE")
    total_count = len(rows)
    pct_done    = round(done_count / max(total_count, 1) * 100)

    return ok({
        "items": rows_to_list(rows),
        "done": done_count,
        "total": total_count,
        "pct_done": pct_done,
        "period_id": period_id,
    })


@audit_fin_bp.post("/close-checklist/<int:item_id>/complete")
@require_auth
@require_finance_role
def complete_checklist_item(item_id: int):
    d    = request.get_json() or {}
    user = request.environ.get("user_email", "system")
    fin_execute(
        """UPDATE fin_close_checklist_instances
           SET status='DONE', completed_by=%s, completed_at=NOW(), notes=%s
           WHERE id=%s""",
        [user, d.get("notes"), item_id],
    )
    return ok({}, "Checklist item completed")


@audit_fin_bp.post("/close-checklist/<int:item_id>/skip")
@require_auth
@require_finance_role
def skip_checklist_item(item_id: int):
    d    = request.get_json() or {}
    user = request.environ.get("user_email", "system")
    fin_execute(
        """UPDATE fin_close_checklist_instances
           SET status='SKIPPED', completed_by=%s, completed_at=NOW(), notes=%s
           WHERE id=%s""",
        [user, d.get("notes"), item_id],
    )
    return ok({}, "Checklist item skipped")


# ── SoD Violations ────────────────────────────────────────────

@audit_fin_bp.get("/sod-violations")
@require_auth
@require_finance_role
def sod_violations():
    rows = fin_query(
        "SELECT * FROM fin_sod_violations ORDER BY blocked_at DESC LIMIT 100",
        many=True,
    )
    summary = fin_query("SELECT * FROM v_fin_sod_summary LIMIT 20", many=True)
    return ok({"violations": rows_to_list(rows), "summary": rows_to_list(summary)})


# ── Compliance Dashboard ──────────────────────────────────────

@audit_fin_bp.get("/compliance-dashboard")
@require_auth
@require_finance_role
def compliance_dashboard():
    dashboard = fin_query("SELECT * FROM v_fin_compliance_dashboard", many=True)
    pending_approvals = fin_query("SELECT * FROM v_fin_pending_approvals LIMIT 20", many=True)
    return ok({
        "metrics": rows_to_list(dashboard),
        "pending_approvals": rows_to_list(pending_approvals),
    })


# ── Audit Packages ────────────────────────────────────────────

@audit_fin_bp.get("/packages")
@require_auth
@require_finance_role
def list_audit_packages():
    rows = fin_query(
        "SELECT * FROM fin_audit_packages ORDER BY created_at DESC",
        many=True,
    )
    return ok(rows_to_list(rows))


@audit_fin_bp.post("/packages")
@require_auth
@require_finance_role
def create_audit_package():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["period_year", "period_type", "period_from", "period_to"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    # Auto-compute totals from GL
    period_from = d["period_from"]
    period_to   = d["period_to"]

    totals = fin_query(
        """
        SELECT
            SUM(CASE WHEN fa.account_type='ASSET'   THEN gl.debit - gl.credit ELSE 0 END) AS total_assets,
            SUM(CASE WHEN fa.account_type='REVENUE' THEN gl.credit - gl.debit ELSE 0 END) AS total_revenue
        FROM fin_gl_lines gl
        JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status='POSTED'
        JOIN fin_accounts fa ON fa.code = gl.account_code
        WHERE je.entry_date BETWEEN %s AND %s
        """,
        [period_from, period_to],
    )

    # Auto-generate package number
    count = fin_query("SELECT COUNT(*)+1 AS n FROM fin_audit_packages")
    pkg_no = f"AP-{d['period_year']}-{count['n']:03d}"

    row = fin_execute_returning(
        """
        INSERT INTO fin_audit_packages
            (package_no, period_year, period_type, period_from, period_to,
             total_assets, total_revenue, auditor_name, notes, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, package_no
        """,
        [pkg_no, d["period_year"], d["period_type"],
         period_from, period_to,
         float(totals["total_assets"] or 0) if totals else 0,
         float(totals["total_revenue"] or 0) if totals else 0,
         d.get("auditor_name"), d.get("notes"), user],
    )
    return ok(row_to_dict(row), "Audit package created", 201)


# ── Field Change Audit Trail ──────────────────────────────────

@audit_fin_bp.get("/field-changes")
@require_auth
@require_finance_role
def field_changes():
    table = request.args.get("table")
    ref   = request.args.get("record_id", type=int)

    conditions, params = [], []
    if table:
        conditions.append("table_name = %s"); params.append(table)
    if ref:
        conditions.append("record_id = %s"); params.append(ref)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"SELECT * FROM fin_field_changes {where} ORDER BY changed_at DESC LIMIT 200",
        params, many=True,
    )
    return ok(rows_to_list(rows))
