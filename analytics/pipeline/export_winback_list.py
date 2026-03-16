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


def export_winback_list():
    print("Generating Winback List (Lost > 1 Year)...")

    query = """
    WITH last_visits AS (
        SELECT 
            c.id,
            c.code,
            c.name,
            c.address,
            c.phone1,
            c.phone2,
            c.email,
            MAX(v.realization_date) as last_visit_date,
            CURRENT_DATE - MAX(v.realization_date)::date as days_since_last_visit,
            COUNT(v.id) as total_historical_visits
        FROM m_customer c
        JOIN t_road_plan rp ON rp.id_customer = c.id
        JOIN t_visit v ON v.id_road_plan = rp.id
        GROUP BY c.id, c.code, c.name, c.address, c.phone1, c.phone2, c.email
    )
    SELECT 
        *
    FROM last_visits
    WHERE days_since_last_visit > 365
    ORDER BY last_visit_date DESC
    """

    try:
        results = execute_kelava_query(query)
    except Exception as e:
        print(f"Error executing query: {e}")
        return

    if not results:
        print("No lost customers found.")
        return

    # Use a fixed filename for easier finding
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"winback_list_lost_customers_{timestamp}.csv"

    headers = [
        "code",
        "name",
        "days_since_last_visit",
        "last_visit_date",
        "total_historical_visits",
        "phone1",
        "phone2",
        "address",
        "email",
    ]

    print(f"Writing {len(results)} records to {filename}...")

    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        for row in results:
            clean_row = {
                "code": row["code"],
                "name": row["name"],
                "days_since_last_visit": row["days_since_last_visit"],
                "last_visit_date": str(row["last_visit_date"]),
                "total_historical_visits": row["total_historical_visits"],
                "phone1": row["phone1"] or "",
                "phone2": row["phone2"] or "",
                "address": row["address"] or "",
                "email": row["email"] or "",
            }
            writer.writerow(clean_row)

    print(f"Export completed successfully: {filename}")


if __name__ == "__main__":
    export_winback_list()
