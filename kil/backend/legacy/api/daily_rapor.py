"""
Daily KPI Rapor Auto-Generation
==================================
Automatically calculates daily KPI scores per technician.
Integrates: completion rate, punctuality, photo compliance,
complaint count, GPS drift, and chemical logging.

Meeting: "Setiap hari ada rapor otomatis... langsung ke HP"
"""

import json
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

daily_rapor_bp = Blueprint("daily_rapor", __name__, url_prefix="/rapor")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return

    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS daily_kpi_rapor (
            id                  BIGSERIAL PRIMARY KEY,
            technician_id       INTEGER NOT NULL,
            rapor_date          DATE NOT NULL,
            planned_visits      INTEGER DEFAULT 0,
            completed_visits    INTEGER DEFAULT 0,
            completion_pct      NUMERIC(5,1) DEFAULT 0,
            on_time_visits      INTEGER DEFAULT 0,
            punctuality_pct     NUMERIC(5,1) DEFAULT 0,
            photo_compliant     INTEGER DEFAULT 0,
            photo_pct           NUMERIC(5,1) DEFAULT 0,
            avg_duration_min    NUMERIC(6,1),
            complaint_count     INTEGER DEFAULT 0,
            drift_alert_count   INTEGER DEFAULT 0,
            chemical_logged     INTEGER DEFAULT 0,
            units_scanned       INTEGER DEFAULT 0,
            overall_score       NUMERIC(5,1) DEFAULT 0,
            grade               VARCHAR(2),
            detail_json         TEXT,
            wa_sent             BOOLEAN DEFAULT false,
            wa_sent_at          TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(technician_id, rapor_date)
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_rapor_tech_date
        ON daily_kpi_rapor (technician_id, rapor_date DESC)
    """)

    _TABLE_ENSURED = True


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _calc_grade(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    return "E"


# ── Generate Daily Rapor ──────────────────────────────────────


@daily_rapor_bp.route("/generate", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def generate_rapor():
    """
    Generate daily KPI rapor for all technicians on a given date.

    Body: {
        date: "YYYY-MM-DD" (default: yesterday),
        technician_id?: int (generate for specific tech only)
    }

    KPI Weights:
    - Completion rate: 40%
    - Punctuality: 20%
    - Photo compliance: 15%
    - No complaints: 15% (100% if 0 complaints, -10 per complaint)
    - Chemical logging: 5%
    - No GPS drift: 5%
    """
    _ensure_tables()
    data = request.json or {}
    target_date = data.get("date", (date.today() - timedelta(days=1)).isoformat())
    tech_filter = data.get("technician_id")

    # Get all technicians with planned visits on target date
    where = "rp.visit_date::date = %s AND COALESCE(rp.is_cancel, false) = false"
    params = [target_date]
    if tech_filter:
        where += " AND rp.id_user = %s"
        params.append(int(tech_filter))

    techs = execute_kelava_query(
        f"""
        SELECT
            rp.id_user AS technician_id,
            u.fullname AS tech_name,
            COUNT(DISTINCT rp.id) AS planned,
            COUNT(DISTINCT CASE WHEN rp.status = 'Selesai' THEN rp.id END) AS completed,
            COUNT(DISTINCT CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                  AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 BETWEEN 5 AND 480
                  THEN rp.id END) AS valid_duration,
            ROUND(AVG(CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                  THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 END)::numeric, 1) AS avg_duration
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE {where}
        GROUP BY rp.id_user, u.fullname
        """,
        tuple(params),
    )

    generated = 0
    skipped = 0
    rapors = []

    for t in techs:
        tid = t["technician_id"]
        planned = t["planned"] or 0
        completed = t["completed"] or 0

        if planned == 0:
            continue

        # 1. Completion rate
        completion_pct = round(completed / planned * 100, 1) if planned > 0 else 0

        # 2. Photo compliance (from foto_cache or t_road_plan_foto)
        try:
            photo_stats = execute_kelava_query_single(
                """
                SELECT COUNT(DISTINCT rp.id) AS with_photos
                FROM t_road_plan rp
                JOIN t_road_plan_foto rpf ON rpf.id_road_plan = rp.id
                WHERE rp.id_user = %s AND rp.visit_date::date = %s
                  AND COALESCE(rp.is_cancel, false) = false
                """,
                (tid, target_date),
            )
            photo_compliant = photo_stats["with_photos"] if photo_stats else 0
        except Exception:
            photo_compliant = 0
        photo_pct = round(photo_compliant / planned * 100, 1) if planned > 0 else 0

        # 3. Punctuality (check-in time vs scheduled — approximate)
        try:
            punct = execute_kelava_query_single(
                """
                SELECT COUNT(*) FILTER (WHERE v.check_in::time <= '09:00:00') AS on_time
                FROM t_visit v
                JOIN t_road_plan rp ON rp.id = v.id_road_plan
                WHERE rp.id_user = %s AND rp.visit_date::date = %s AND v.check_in IS NOT NULL
                """,
                (tid, target_date),
            )
            on_time = punct["on_time"] if punct else 0
        except Exception:
            on_time = 0
        punct_pct = round(on_time / planned * 100, 1) if planned > 0 else 0

        # 4. Complaints on this date
        try:
            compl = execute_kelava_query_single(
                """
                SELECT COUNT(*) AS cnt FROM complaint_tickets
                WHERE assigned_to = %s AND created_at::date = %s
                """,
                (tid, target_date),
            )
            complaint_count = compl["cnt"] if compl else 0
        except Exception:
            complaint_count = 0

        # 5. GPS drift alerts
        try:
            drift = execute_kelava_query_single(
                """
                SELECT COUNT(*) AS cnt FROM drift_alerts
                WHERE technician_id = %s AND created_at::date = %s
                """,
                (tid, target_date),
            )
            drift_count = drift["cnt"] if drift else 0
        except Exception:
            drift_count = 0

        # 6. Chemical logging
        try:
            chem = execute_kelava_query_single(
                """
                SELECT COUNT(*) AS cnt FROM chemical_usage_logs
                WHERE technician_id = %s AND applied_at::date = %s
                """,
                (tid, target_date),
            )
            chem_count = chem["cnt"] if chem else 0
        except Exception:
            chem_count = 0

        # 7. Unit scans
        try:
            scans = execute_kelava_query_single(
                """
                SELECT COUNT(*) AS cnt FROM unit_scan_logs
                WHERE technician_id = %s AND scan_time::date = %s
                """,
                (tid, target_date),
            )
            scan_count = scans["cnt"] if scans else 0
        except Exception:
            scan_count = 0

        # Calculate overall score (weighted)
        complaint_score = max(0, 100 - complaint_count * 10)
        drift_score = 100 if drift_count == 0 else max(0, 100 - drift_count * 20)
        chem_score = min(100, chem_count / max(1, completed) * 100) if completed > 0 else 0

        overall = round(
            completion_pct * 0.40 +
            punct_pct * 0.20 +
            photo_pct * 0.15 +
            complaint_score * 0.15 +
            chem_score * 0.05 +
            drift_score * 0.05,
            1,
        )
        grade = _calc_grade(overall)

        detail = {
            "tech_name": t["tech_name"],
            "avg_duration_min": float(t["avg_duration"] or 0),
            "complaint_score": complaint_score,
            "drift_score": drift_score,
            "chem_score": chem_score,
        }

        # Upsert rapor
        try:
            execute_kelava_query(
                """
                INSERT INTO daily_kpi_rapor
                    (technician_id, rapor_date, planned_visits, completed_visits, completion_pct,
                     on_time_visits, punctuality_pct, photo_compliant, photo_pct, avg_duration_min,
                     complaint_count, drift_alert_count, chemical_logged, units_scanned,
                     overall_score, grade, detail_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (technician_id, rapor_date) DO UPDATE SET
                    planned_visits = EXCLUDED.planned_visits,
                    completed_visits = EXCLUDED.completed_visits,
                    completion_pct = EXCLUDED.completion_pct,
                    on_time_visits = EXCLUDED.on_time_visits,
                    punctuality_pct = EXCLUDED.punctuality_pct,
                    photo_compliant = EXCLUDED.photo_compliant,
                    photo_pct = EXCLUDED.photo_pct,
                    avg_duration_min = EXCLUDED.avg_duration_min,
                    complaint_count = EXCLUDED.complaint_count,
                    drift_alert_count = EXCLUDED.drift_alert_count,
                    chemical_logged = EXCLUDED.chemical_logged,
                    units_scanned = EXCLUDED.units_scanned,
                    overall_score = EXCLUDED.overall_score,
                    grade = EXCLUDED.grade,
                    detail_json = EXCLUDED.detail_json
                """,
                (
                    tid, target_date, planned, completed, completion_pct,
                    on_time, punct_pct, photo_compliant, photo_pct,
                    t["avg_duration"], complaint_count, drift_count,
                    chem_count, scan_count, overall, grade,
                    json.dumps(detail, default=str),
                ),
            )
            generated += 1
        except Exception:
            skipped += 1

        rapors.append({
            "technician_id": tid,
            "tech_name": t["tech_name"],
            "overall_score": overall,
            "grade": grade,
            "completion_pct": completion_pct,
            "punctuality_pct": punct_pct,
            "photo_pct": photo_pct,
        })

    # Sort by score descending
    rapors.sort(key=lambda x: x["overall_score"], reverse=True)

    return jsonify({
        "date": target_date,
        "generated": generated,
        "skipped": skipped,
        "rapors": rapors,
    })


# ── Get Rapor for Tech ────────────────────────────────────────


@daily_rapor_bp.route("/technician/<int:tech_id>", methods=["GET"])
@require_auth
def tech_rapor(tech_id: int):
    """Get rapor history for a technician."""
    _ensure_tables()
    days = int(request.args.get("days", 30))

    rows = execute_kelava_query(
        """
        SELECT * FROM daily_kpi_rapor
        WHERE technician_id = %s AND rapor_date >= CURRENT_DATE - %s
        ORDER BY rapor_date DESC
        """,
        (tech_id, days),
    )

    # Calculate averages
    if rows:
        avg_score = round(sum(float(r["overall_score"] or 0) for r in rows) / len(rows), 1)
    else:
        avg_score = 0

    return jsonify({
        "technician_id": tech_id,
        "rapors": [_fmt(r) for r in rows],
        "average_score": avg_score,
        "total_days": len(rows),
    })


# ── Leaderboard ───────────────────────────────────────────────


@daily_rapor_bp.route("/leaderboard", methods=["GET"])
@require_auth
def leaderboard():
    """KPI leaderboard for a date range."""
    _ensure_tables()
    days = int(request.args.get("days", 30))

    rows = execute_kelava_query(
        """
        SELECT
            dr.technician_id,
            u.fullname AS tech_name,
            COUNT(*) AS days_active,
            ROUND(AVG(dr.overall_score)::numeric, 1) AS avg_score,
            ROUND(AVG(dr.completion_pct)::numeric, 1) AS avg_completion,
            ROUND(AVG(dr.punctuality_pct)::numeric, 1) AS avg_punctuality,
            ROUND(AVG(dr.photo_pct)::numeric, 1) AS avg_photo,
            SUM(dr.complaint_count) AS total_complaints,
            SUM(dr.drift_alert_count) AS total_drift_alerts,
            MODE() WITHIN GROUP (ORDER BY dr.grade) AS most_common_grade
        FROM daily_kpi_rapor dr
        JOIN p_user u ON u.id = dr.technician_id
        WHERE dr.rapor_date >= CURRENT_DATE - %s
        GROUP BY dr.technician_id, u.fullname
        ORDER BY avg_score DESC
        """,
        (days,),
    )

    # Add rank
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    return jsonify({
        "leaderboard": [_fmt(r) for r in rows],
        "period_days": days,
        "generated_at": datetime.now().isoformat(),
    })


# ── Monthly Summary ───────────────────────────────────────────


@daily_rapor_bp.route("/monthly/<int:tech_id>", methods=["GET"])
@require_auth
def monthly_summary(tech_id: int):
    """Monthly aggregated KPI for a technician."""
    _ensure_tables()
    months = int(request.args.get("months", 6))

    rows = execute_kelava_query(
        """
        SELECT
            TO_CHAR(rapor_date, 'YYYY-MM') AS month,
            COUNT(*) AS days_active,
            ROUND(AVG(overall_score)::numeric, 1) AS avg_score,
            ROUND(AVG(completion_pct)::numeric, 1) AS avg_completion,
            ROUND(AVG(punctuality_pct)::numeric, 1) AS avg_punctuality,
            ROUND(AVG(photo_pct)::numeric, 1) AS avg_photo,
            SUM(complaint_count) AS total_complaints,
            SUM(completed_visits) AS total_completed,
            SUM(planned_visits) AS total_planned
        FROM daily_kpi_rapor
        WHERE technician_id = %s
          AND rapor_date >= CURRENT_DATE - INTERVAL '%s months'
        GROUP BY TO_CHAR(rapor_date, 'YYYY-MM')
        ORDER BY month DESC
        """,
        (tech_id, months),
    )

    return jsonify({
        "technician_id": tech_id,
        "monthly": [_fmt(r) for r in rows],
    })
