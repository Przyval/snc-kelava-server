import os
import sys
from datetime import datetime

# Add current directory to path to allow imports
sys.path.append(os.getcwd())

try:
    from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
except ImportError as e:
    print(f"Error importing kil.db.kelava_db: {e}")
    sys.exit(1)


def format_contact(name, phone, phone1):
    parts = []
    if name:
        parts.append(name)

    phones = []
    if phone:
        phones.append(phone)
    if phone1 and phone1 != phone:
        phones.append(phone1)

    if phones:
        parts.append(f"({', '.join(phones)})")

    return " ".join(parts) if parts else "-"


def generate_report():
    print("# 📊 MASTER CUSTOMER HEALTH REPORT (With Contacts)")
    print(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    # 1. OVERALL SEGMENTATION
    # -----------------------
    seg_query = """
    WITH last_visits AS (
        SELECT 
            c.id,
            CURRENT_DATE - MAX(v.realization_date)::date as days_ago
        FROM m_customer c
        LEFT JOIN t_road_plan rp ON rp.id_customer = c.id
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        GROUP BY c.id
    )
    SELECT 
        CASE 
            WHEN days_ago IS NULL THEN 'Never Visited'
            WHEN days_ago <= 60 THEN 'Active'
            WHEN days_ago <= 180 THEN 'Inactive'
            WHEN days_ago <= 365 THEN 'Dormant'
            ELSE 'Lost'
        END as status,
        COUNT(*) as count
    FROM last_visits
    GROUP BY 1
    ORDER BY count DESC
    """
    segments = execute_kelava_query(seg_query)
    total_customers = sum(s["count"] for s in segments)

    print("## 1. Executive Summary")
    print(f"**Total Customers:** {total_customers}")
    print("\n| Status | Definition | Count | % |")
    print("|---|---|---|---|")

    status_order = ["Active", "Inactive", "Dormant", "Lost", "Never Visited"]
    seg_map = {s["status"]: s["count"] for s in segments}

    for status in status_order:
        count = seg_map.get(status, 0)
        pct = (count / total_customers * 100) if total_customers else 0
        def_text = ""
        if status == "Active":
            def_text = "< 60 days"
        elif status == "Inactive":
            def_text = "2-6 months"
        elif status == "Dormant":
            def_text = "6-12 months"
        elif status == "Lost":
            def_text = "> 1 year"

        print(f"| **{status}** | {def_text} | {count} | {pct:.1f}% |")

    # 2. TOP ACTIVE CLIENTS (By Frequency/Value)
    # -----------------------
    print("\n## 2. Top 10 Active Clients (Most Frequent)")
    print("> Klien paling sering dikunjungi & memiliki kontak person.")
    print("\n| Customer | Contact Person | Last Visit | Visits |")
    print("|---|---|---|---|")

    top_active_query = """
    SELECT 
        c.name,
        c.contact_person_name,
        c.contact_person_phone,
        c.phone1,
        MAX(v.realization_date) as last_visit,
        COUNT(v.id) as total_visits
    FROM m_customer c
    JOIN t_road_plan rp ON rp.id_customer = c.id
    JOIN t_visit v ON v.id_road_plan = rp.id
    WHERE v.realization_date >= CURRENT_DATE - INTERVAL '60 days'
    GROUP BY c.id, c.name, c.contact_person_name, c.contact_person_phone, c.phone1
    ORDER BY total_visits DESC
    LIMIT 10
    """
    top_active = execute_kelava_query(top_active_query)
    for row in top_active:
        contact = format_contact(
            row["contact_person_name"], row["contact_person_phone"], row["phone1"]
        )
        print(
            f"| {row['name']} | {contact} | {row['last_visit']} | {row['total_visits']} |"
        )

    # 3. WINBACK OPPORTUNITIES
    # -----------------------
    print("\n## 3. Top Winback Opportunities (Lost > 1 Year)")
    print(
        "> Klien 'Lost' dengan histori kunjungan tinggi. Hubungi CP ini untuk rawat ulang."
    )
    print("\n| Customer | Contact Person | Last Visit | Total Hist. Visits |")
    print("|---|---|---|---|")

    winback_query = """
    SELECT 
        c.name,
        c.contact_person_name,
        c.contact_person_phone,
        c.phone1,
        MAX(v.realization_date) as last_visit,
        COUNT(v.id) as total_visits
    FROM m_customer c
    JOIN t_road_plan rp ON rp.id_customer = c.id
    JOIN t_visit v ON v.id_road_plan = rp.id
    GROUP BY c.id, c.name, c.contact_person_name, c.contact_person_phone, c.phone1
    HAVING (CURRENT_DATE - MAX(v.realization_date)::date) > 365
    ORDER BY total_visits DESC
    LIMIT 15
    """
    winback = execute_kelava_query(winback_query)
    for row in winback:
        contact = format_contact(
            row["contact_person_name"], row["contact_person_phone"], row["phone1"]
        )
        print(
            f"| {row['name']} | {contact} | {row['last_visit']} | {row['total_visits']} |"
        )


if __name__ == "__main__":
    generate_report()
