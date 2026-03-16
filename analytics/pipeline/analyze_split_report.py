import os
import sys
from datetime import datetime

# Add current directory to path to allow imports
sys.path.append(os.getcwd())

try:
    from kil.db.kelava_db import execute_kelava_query
except ImportError as e:
    print(f"Error importing kil.db.kelava_db: {e}")
    sys.exit(1)


def run_segmented_analysis():
    print("# 📊 SEGMENTED CUSTOMER ACTIVITY REPORT")
    print(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    query = """
    WITH customer_service_types AS (
        SELECT 
            c.id,
            c.name,
            CASE 
                WHEN EXISTS (SELECT 1 FROM t_road_plan rp WHERE rp.id_customer = c.id AND rp.type = 'spv_tc') 
                THEN 'Termite Control' 
                ELSE 'Laporan Pelayanan' 
            END as service_category
        FROM m_customer c
    ),
    last_visits AS (
        SELECT 
            c.id,
            MAX(v.realization_date) as last_visit_date,
            CURRENT_DATE - MAX(v.realization_date)::date as days_ago
        FROM m_customer c
        LEFT JOIN t_road_plan rp ON rp.id_customer = c.id
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        GROUP BY c.id
    ),
    categorized_data AS (
        SELECT 
            cs.service_category,
            CASE 
                WHEN lv.last_visit_date IS NULL THEN 'Never Visited'
                WHEN lv.days_ago <= 60 THEN 'Active'
                WHEN lv.days_ago <= 180 THEN 'Inactive'
                WHEN lv.days_ago <= 365 THEN 'Dormant'
                ELSE 'Lost'
            END as status_category
        FROM customer_service_types cs
        JOIN last_visits lv ON cs.id = lv.id
    )
    SELECT 
        service_category,
        status_category,
        COUNT(*) as customer_count
    FROM categorized_data
    GROUP BY 1, 2
    ORDER BY 1, 
        CASE status_category
            WHEN 'Active' THEN 1
            WHEN 'Inactive' THEN 2
            WHEN 'Dormant' THEN 3
            WHEN 'Lost' THEN 4
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

    # Process results into a nested dict
    data = {}
    for row in results:
        svc = row["service_category"]
        stat = row["status_category"]
        count = row["customer_count"]
        if svc not in data:
            data[svc] = {}
        data[svc][stat] = count

    status_order = ["Active", "Inactive", "Dormant", "Lost", "Never Visited"]
    status_definitions = {
        "Active": "≤ 60 hari",
        "Inactive": "2-6 bulan",
        "Dormant": "6-12 bulan",
        "Lost": "> 1 tahun",
        "Never Visited": "-",
    }

    for service in sorted(data.keys()):
        print(f"## 🛠️ Kategori: {service}")
        total = sum(data[service].values())
        print(f"**Total Klien:** {total}")

        print("\n| Status | Definisi | Jumlah | % |")
        print("|---|---|---|---|")

        for status in status_order:
            count = data[service].get(status, 0)
            pct = (count / total * 100) if total > 0 else 0
            print(f"| {status} | {status_definitions[status]} | {count} | {pct:.1f}% |")
        print("\n")


if __name__ == "__main__":
    run_segmented_analysis()
