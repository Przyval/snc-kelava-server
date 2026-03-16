#!/usr/bin/env python3
"""
Backfill KPI Monthly Archive
==============================
Computes historical monthly KPI metrics for all technicians and stores in kpi_monthly_archive.
Designed to run once for historical data, then monthly via cron for current month.

Usage:
    python -m kil.backend.scripts.backfill_kpi_archive [--since 2021-01]
    python -m kil.backend.scripts.backfill_kpi_archive --current-month
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kil" / "backend"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single


def compute_grade(visits_per_day: float, completion_rate: float) -> str:
    """Grade calculation: 40% visit volume (scaled to 4/day), 60% completion rate."""
    score = (visits_per_day / 4 * 40) + (completion_rate / 100 * 60)
    if score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    elif score >= 50:
        return "C"
    return "D"


def backfill(since: str = "2021-01", current_month_only: bool = False):
    """
    Backfill KPI monthly archive from t_road_plan + t_visit.
    """
    if current_month_only:
        where_clause = "DATE_TRUNC('month', rp.visit_date::date) = DATE_TRUNC('month', CURRENT_DATE)"
        # 3 CTEs use where_clause, no params needed
        params = None
        print("Computing current month only...")
    else:
        where_clause = "rp.visit_date::date >= %s"
        since_date = f"{since}-01"
        # 3 CTEs use where_clause, each needs the param
        params = (since_date, since_date, since_date)
        print(f"Backfilling from {since}...")

    # Get all technician-month combinations from road plans
    rows = execute_kelava_query(
        f"""
        WITH monthly_plan AS (
            SELECT
                rp.id_user as technician_id,
                DATE_TRUNC('month', rp.visit_date::date) as month,
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as total_completed,
                COUNT(DISTINCT rp.visit_date::date) as active_days
            FROM t_road_plan rp
            WHERE {where_clause}
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY rp.id_user, DATE_TRUNC('month', rp.visit_date::date)
        ),
        monthly_visit AS (
            SELECT
                rp.id_user as technician_id,
                DATE_TRUNC('month', v.realization_date) as month,
                COUNT(v.id) as total_visits,
                ROUND(AVG(
                    CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
                    END
                )::numeric, 1) as avg_duration_min
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE {where_clause}
            GROUP BY rp.id_user, DATE_TRUNC('month', v.realization_date)
        ),
        daily_first_checkin AS (
            SELECT
                rp.id_user as technician_id,
                DATE_TRUNC('month', v.realization_date) as month,
                v.realization_date,
                MIN(v.check_in)::time as first_checkin
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE {where_clause}
              AND v.check_in IS NOT NULL
            GROUP BY rp.id_user, DATE_TRUNC('month', v.realization_date), v.realization_date
        ),
        monthly_punctuality AS (
            SELECT
                technician_id,
                month,
                COUNT(*) as total_work_days,
                COUNT(*) FILTER (WHERE first_checkin <= '08:30:00'::time) as on_time_days
            FROM daily_first_checkin
            GROUP BY technician_id, month
        )
        SELECT
            mp.technician_id,
            TO_CHAR(mp.month, 'YYYY-MM') as year_month,
            mp.total_planned,
            mp.total_completed,
            COALESCE(mv.total_visits, 0) as total_visits,
            mp.active_days,
            CASE WHEN mp.active_days > 0
                THEN ROUND(COALESCE(mv.total_visits, 0)::numeric / mp.active_days, 1)
                ELSE 0
            END as visits_per_day,
            CASE WHEN mp.total_planned > 0
                THEN ROUND(mp.total_completed::numeric / mp.total_planned * 100, 1)
                ELSE 0
            END as completion_rate,
            COALESCE(mv.avg_duration_min, 0) as avg_duration_min,
            CASE WHEN mpt.total_work_days > 0
                THEN ROUND(COALESCE(mpt.on_time_days, 0)::numeric / mpt.total_work_days * 100, 1)
                ELSE 0
            END as on_time_rate
        FROM monthly_plan mp
        LEFT JOIN monthly_visit mv ON mv.technician_id = mp.technician_id AND mv.month = mp.month
        LEFT JOIN monthly_punctuality mpt ON mpt.technician_id = mp.technician_id AND mpt.month = mp.month
        ORDER BY mp.technician_id, mp.month
        """,
        params if params else None,
    )

    print(f"Found {len(rows)} technician-month records to process")

    inserted = 0
    updated = 0
    for row in rows:
        vpd = float(row["visits_per_day"])
        cr = float(row["completion_rate"])
        grade = compute_grade(vpd, cr)

        result = execute_kelava_query_single(
            """
            INSERT INTO kpi_monthly_archive
                (technician_id, year_month, total_planned, total_completed,
                 total_visits, active_days, visits_per_day, completion_rate,
                 avg_duration_min, on_time_rate, grade)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (technician_id, year_month)
            DO UPDATE SET
                total_planned = EXCLUDED.total_planned,
                total_completed = EXCLUDED.total_completed,
                total_visits = EXCLUDED.total_visits,
                active_days = EXCLUDED.active_days,
                visits_per_day = EXCLUDED.visits_per_day,
                completion_rate = EXCLUDED.completion_rate,
                avg_duration_min = EXCLUDED.avg_duration_min,
                on_time_rate = EXCLUDED.on_time_rate,
                grade = EXCLUDED.grade,
                computed_at = NOW()
            RETURNING (xmax = 0) as is_insert
            """,
            (
                row["technician_id"],
                row["year_month"],
                row["total_planned"],
                row["total_completed"],
                row["total_visits"],
                row["active_days"],
                row["visits_per_day"],
                row["completion_rate"],
                row["avg_duration_min"],
                row["on_time_rate"],
                grade,
            ),
        )

        if result and result.get("is_insert"):
            inserted += 1
        else:
            updated += 1

    print(f"Done: {inserted} inserted, {updated} updated")


def main():
    parser = argparse.ArgumentParser(description="Backfill KPI monthly archive")
    parser.add_argument("--since", default="2021-01", help="Start year-month (e.g., 2021-01)")
    parser.add_argument("--current-month", action="store_true", help="Only compute current month")
    args = parser.parse_args()

    backfill(since=args.since, current_month_only=args.current_month)


if __name__ == "__main__":
    main()
