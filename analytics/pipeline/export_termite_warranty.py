import csv
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


def export_termite_warranty():
    print("Generating Termite Warranty Expiry List (3 Years)...")

    query = """
    WITH termite_customers AS (
        -- Get customers who have at least one spv_tc visit
        SELECT DISTINCT id_customer
        FROM t_road_plan
        WHERE type = 'spv_tc'
    ),
    treatment_dates AS (
        -- Find first and last treatment for these customers
        SELECT 
            rp.id_customer,
            MIN(v.realization_date) as first_treatment,
            MAX(v.realization_date) as last_treatment,
            COUNT(v.id) as total_visits
        FROM t_road_plan rp
        JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_customer IN (SELECT id_customer FROM termite_customers)
        GROUP BY rp.id_customer
    )
    SELECT 
        c.code,
        c.name,
        c.contact_person_name,
        c.contact_person_phone,
        c.phone1,
        td.first_treatment,
        td.last_treatment,
        td.total_visits,
        (td.first_treatment + INTERVAL '3 years')::date as warranty_expiry_date,
        CURRENT_DATE - (td.first_treatment + INTERVAL '3 years')::date as days_expired
    FROM treatment_dates td
    JOIN m_customer c ON c.id = td.id_customer
    WHERE (td.first_treatment + INTERVAL '3 years') < CURRENT_DATE
    ORDER BY warranty_expiry_date ASC
    """

    try:
        results = execute_kelava_query(query)
    except Exception as e:
        print(f"Error executing query: {e}")
        return

    if not results:
        print("No expired termite warranties found.")
        return

    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"termite_expired_warranty_{timestamp}.csv"

    headers = [
        "code",
        "name",
        "contact_person",
        "phone",
        "first_treatment",
        "last_treatment",
        "total_visits",
        "warranty_expiry_date",
        "days_expired",
    ]

    print(f"Writing {len(results)} records to {filename}...")

    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        for row in results:
            phone = row["contact_person_phone"] or row["phone1"] or ""
            clean_row = {
                "code": row["code"],
                "name": row["name"],
                "contact_person": row["contact_person_name"] or "-",
                "phone": phone,
                "first_treatment": str(row["first_treatment"]),
                "last_treatment": str(row["last_treatment"]),
                "total_visits": row["total_visits"],
                "warranty_expiry_date": str(row["warranty_expiry_date"]),
                "days_expired": row["days_expired"],
            }
            writer.writerow(clean_row)

    print(f"Export completed successfully: {filename}")
    return filename


if __name__ == "__main__":
    export_termite_warranty()
