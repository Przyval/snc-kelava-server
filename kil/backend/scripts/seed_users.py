#!/usr/bin/env python3
"""
Seed Enterprise Users from Legacy p_user Table
================================================
Creates enterprise_users records linked to existing p_user records.
Also creates a default admin account for initial access.

Usage:
    python kil/backend/scripts/seed_users.py
    python kil/backend/scripts/seed_users.py --admin-only   # Just create admin
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import bcrypt
from dotenv import load_dotenv

load_dotenv()

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_admin():
    """Create the default admin account."""
    admin_email = "admin@sanocare.work"
    admin_pw = "SanoCare2026!"

    existing = execute_kelava_query_single(
        "SELECT id FROM enterprise_users WHERE email = %s", (admin_email,)
    )

    if existing:
        print(f"  Admin account already exists (id={existing['id']})")
        return existing["id"]

    pw_hash = hash_password(admin_pw)
    result = execute_kelava_query_single(
        """
        INSERT INTO enterprise_users (email, password_hash, full_name, role)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (admin_email, pw_hash, "System Administrator", "admin"),
    )

    admin_id = result["id"]
    print(f"  Created admin: {admin_email} / {admin_pw}  (id={admin_id})")
    print(f"  *** CHANGE THIS PASSWORD IMMEDIATELY ***")
    return admin_id


def seed_from_p_user():
    """
    Sync p_user records into enterprise_users.
    Maps roles: Sales → technician, outlet_manager → supervisor,
    manager → supervisor, Administrator → admin, dev → admin
    """
    role_map = {
        "Sales": "technician",
        "outlet_manager": "supervisor",
        "manager.": "supervisor",
        "manager": "supervisor",
        "Administrator": "admin",
        "dev": "admin",
    }

    # Get all active p_user records with their roles
    p_users = execute_kelava_query("""
        SELECT DISTINCT ON (pu.id)
            pu.id, pu.email, pu.fullname, pu.username,
            pr.role_name as role_name
        FROM p_user pu
        LEFT JOIN p_user_role pur ON pur.user_id = pu.id
        LEFT JOIN p_role pr ON pr.id = pur.role_id
        WHERE COALESCE(pu.is_deleted, false) = false
        ORDER BY pu.id, pr.role_name
    """)

    created = 0
    skipped = 0
    errors = 0

    for pu in p_users:
        email = (pu.get("email") or "").strip()
        if not email:
            # Generate email from username
            username = (pu.get("username") or f"user{pu['id']}").strip()
            email = f"{username}@sanocare.work"

        # Check if already exists
        existing = execute_kelava_query_single(
            "SELECT id FROM enterprise_users WHERE email = %s OR p_user_id = %s",
            (email, pu["id"]),
        )

        if existing:
            skipped += 1
            continue

        role_name = (pu.get("role_name") or "Sales").strip()
        enterprise_role = role_map.get(role_name, "viewer")
        full_name = (pu.get("fullname") or email.split("@")[0]).strip()

        # Default password: SanoCare + last 4 of p_user_id
        default_pw = f"SanoCare{str(pu['id']).zfill(4)[-4:]}"
        pw_hash = hash_password(default_pw)

        try:
            execute_kelava_query(
                """
                INSERT INTO enterprise_users
                    (p_user_id, email, password_hash, full_name, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (pu["id"], email, pw_hash, full_name, enterprise_role),
            )
            created += 1
            print(f"  + {email} ({enterprise_role}) <- p_user.id={pu['id']}")
        except Exception as e:
            errors += 1
            print(f"  ! Error for p_user {pu['id']}: {e}")

    return created, skipped, errors


def main():
    admin_only = "--admin-only" in sys.argv

    print("=" * 60)
    print("Enterprise User Seeding")
    print("=" * 60)

    print("\n1. Creating admin account...")
    create_admin()

    if not admin_only:
        print("\n2. Syncing p_user records...")
        created, skipped, errors = seed_from_p_user()
        print(f"\n   Created: {created}")
        print(f"   Skipped (already exist): {skipped}")
        print(f"   Errors: {errors}")

    # Summary
    total = execute_kelava_query_single("SELECT COUNT(*) as cnt FROM enterprise_users")
    by_role = execute_kelava_query(
        "SELECT role, COUNT(*) as cnt FROM enterprise_users GROUP BY role ORDER BY cnt DESC"
    )

    print(f"\n{'=' * 60}")
    print(f"Total enterprise users: {total['cnt']}")
    for r in by_role:
        print(f"  {r['role']}: {r['cnt']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
