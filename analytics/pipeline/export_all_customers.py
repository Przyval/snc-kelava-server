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
    print("Make sure you are running this script from the root of the project.")
    sys.exit(1)


def export_customers():
    print("Fetching customer data...")

    query = """
    SELECT 
        c.id, 
        c.code, 
        c.name, 
        c.address, 
        c.phone1, 
        c.phone2, 
        c.email,
        c.credit_limit, 
        c.payment_term,
        
        -- Priority/Action from View
        pa.priority, 
        pa.owner, 
        pa.service_frequency, 
        pa.expected_cycle_days,
        pa.has_active_contract, 
        pa.value_monthly, 
        pa.days_since_last_visit,
        pa.account_status, 
        pa.suggested_action, 
        pa.reason, 
        pa.rfm_segment as business_signal,
        
        -- Contract Info (Latest Active)
        k.no_kontrak, 
        k.start_date as contract_start_date, 
        k.end_date as contract_end_date,
        
        -- Visit Info (Last Visit)
        lv.last_visit_date,
        lv.days_ago_visits
        
    FROM m_customer c
    LEFT JOIN v_customer_priority_action pa ON pa.customer_id = c.id
    LEFT JOIN LATERAL (
        SELECT no_kontrak, start_date, end_date
        FROM m_customer_kontrak 
        WHERE id_customer = c.id AND is_active ILIKE 'active'
        ORDER BY end_date DESC LIMIT 1
    ) k ON true
    LEFT JOIN LATERAL (
        SELECT MAX(realization_date) as last_visit_date,
               CURRENT_DATE - MAX(realization_date)::date as days_ago_visits
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.id_customer = c.id
    ) lv ON true
    ORDER BY c.name ASC
    """

    try:
        results = execute_kelava_query(query)
    except Exception as e:
        print(f"Error executing query: {e}")
        return

    if not results:
        print("No customers found.")
        return

    # Determine headers from the first row keys
    headers = list(results[0].keys()) if results else []

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"all_customers_export_{timestamp}.csv"

    print(f"Writing {len(results)} records to {filename}...")

    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        for row in results:
            # Convert any non-string objects to string for CSV safety (dates, etc)
            clean_row = {}
            for k, v in row.items():
                if v is None:
                    clean_row[k] = ""
                else:
                    clean_row[k] = str(v)
            writer.writerow(clean_row)

    print(f"Export completed successfully: {filename}")
    return filename


if __name__ == "__main__":
    export_customers()
