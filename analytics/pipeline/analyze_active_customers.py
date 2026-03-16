import os
import sys

# Add current directory to path to allow imports
sys.path.append(os.getcwd())

try:
    from kil.db.kelava_db import execute_kelava_query
except ImportError as e:
    print(f"Error importing kil.db.kelava_db: {e}")
    sys.exit(1)


def analyze_active_customers():
    print("Analyzing customer activity (Threshold: 60 days)...")

    query = """
    WITH last_visits AS (
        SELECT 
            c.id,
            c.name,
            MAX(v.realization_date) as last_visit_date,
            CURRENT_DATE - MAX(v.realization_date)::date as days_since_last_visit
        FROM m_customer c
        LEFT JOIN t_road_plan rp ON rp.id_customer = c.id
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        GROUP BY c.id, c.name
    ),
    categorized AS (
        SELECT 
            CASE 
                WHEN last_visit_date IS NULL THEN 'Never Visited'
                WHEN days_since_last_visit <= 60 THEN 'Active (< 60 days)'
                WHEN days_since_last_visit <= 180 THEN 'Inactive (2-6 months)'
                WHEN days_since_last_visit <= 365 THEN 'Dormant (6-12 months)'
                ELSE 'Lost (> 1 year)'
            END as status_category,
            name
        FROM last_visits
    )
    SELECT 
        status_category,
        COUNT(*) as customer_count
    FROM categorized
    GROUP BY status_category
    ORDER BY 
        CASE status_category
            WHEN 'Active (< 60 days)' THEN 1
            WHEN 'Inactive (2-6 months)' THEN 2
            WHEN 'Dormant (6-12 months)' THEN 3
            WHEN 'Lost (> 1 year)' THEN 4
            ELSE 5
        END;
    """

    try:
        results = execute_kelava_query(query)
    except Exception as e:
        print(f"Error executing query: {e}")
        return

    if not results:
        print("No data returned.")
        return

    print("\n--- Summary: Active vs Inactive/Lost ---")
    total_customers = sum(row["customer_count"] for row in results)

    active_total = 0
    inactive_total = 0

    # Store results in map for easy access
    counts = {row["status_category"]: row["customer_count"] for row in results}

    # Define order for display
    categories = [
        "Active (< 60 days)",
        "Inactive (2-6 months)",
        "Dormant (6-12 months)",
        "Lost (> 1 year)",
        "Never Visited",
    ]

    print(f"{'Category':<25} | {'Count':<10} | {'Percentage':<10}")
    print("-" * 50)

    for cat in categories:
        count = counts.get(cat, 0)
        if count > 0:
            pct = (count / total_customers) * 100
            print(f"{cat:<25} | {count:<10} | {pct:.1f}%")

            if cat == "Active (< 60 days)":
                active_total += count
            else:
                inactive_total += count

    print("-" * 50)
    print(f"{'TOTAL':<25} | {total_customers:<10} | 100%")
    print("\n")

    active_pct = (active_total / total_customers * 100) if total_customers > 0 else 0
    inactive_pct = (
        (inactive_total / total_customers * 100) if total_customers > 0 else 0
    )

    print(
        f"✅ AKTIF (Visited <= 60 days): {active_total} customers ({active_pct:.1f}%)"
    )
    print(
        f"⚠️ TIDAK AKTIF / HILANG:     {inactive_total} customers ({inactive_pct:.1f}%)"
    )


if __name__ == "__main__":
    analyze_active_customers()
