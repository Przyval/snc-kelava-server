import csv
import os
import sys

# Add current directory to path to allow imports
sys.path.append(os.getcwd())

try:
    from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
except ImportError as e:
    print(f"Error importing kil.db.kelava_db: {e}")
    sys.exit(1)


def format_currency(value):
    if not value:
        return "Rp 0"
    try:
        return f"Rp {int(float(value)):,}".replace(",", ".")
    except:
        return str(value)


def check_contract_data():
    print("Checking Contract Size / Value Data...")

    # 1. Check schemas
    print("\n[Audit] 1. Checking table columns...")
    schema_check = execute_kelava_query("""
        SELECT table_name, column_name 
        FROM information_schema.columns 
        WHERE table_name IN ('m_customer_kontrak', 'v_customer_priority_action')
          AND column_name ILIKE '%val%' OR column_name ILIKE '%amount%' OR column_name ILIKE '%nilai%' OR column_name ILIKE '%price%'
    """)
    for row in schema_check:
        print(f"  - {row['table_name']}.{row['column_name']}")

    # 2. Check Data Population in View
    print(
        "\n[Audit] 2. Checking 'v_customer_priority_action.value_monthly' population..."
    )
    view_stats = execute_kelava_query_single("""
        SELECT 
            COUNT(*) as total_rows,
            COUNT(value_monthly) as non_null_values,
            COUNT(*) FILTER (WHERE value_monthly > 0) as positive_values,
            MAX(value_monthly) as max_val,
            AVG(value_monthly) as avg_val
        FROM v_customer_priority_action
    """)
    print(f"  - Total Rows: {view_stats['total_rows']}")
    print(f"  - Non-Null Values: {view_stats['non_null_values']}")
    print(f"  - Positive Values (>0): {view_stats['positive_values']}")
    print(f"  - Max Value: {format_currency(view_stats['max_val'])}")

    # 3. Check Data Population in Raw Contract Table
    print("\n[Audit] 3. Checking 'm_customer_kontrak.nilai_kontrak' (if exists)...")
    # We try to select it, if it fails we catch it
    try:
        contract_stats = execute_kelava_query_single("""
            SELECT 
                COUNT(*) as total_contracts,
                COUNT(nilai_kontrak) as non_null_values,
                MAX(nilai_kontrak) as max_val
            FROM m_customer_kontrak
        """)
        print(f"  - Total Contracts: {contract_stats['total_contracts']}")
        print(f"  - Non-Null Values: {contract_stats['non_null_values']}")
        print(f"  - Max Value: {format_currency(contract_stats['max_val'])}")
    except Exception as e:
        print(f"  - Error querying m_customer_kontrak: {e}")

    # 4. Sample Data
    print("\n[Audit] 4. Customer Samples with Value...")
    samples = execute_kelava_query("""
        SELECT 
            c.name,
            pa.value_monthly
        FROM m_customer c
        JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE pa.value_monthly > 0
        ORDER BY pa.value_monthly DESC
        LIMIT 5
    """)
    if not samples:
        print("  - No samples found with value > 0")
    else:
        for row in samples:
            print(f"  - {row['name']}: {format_currency(row['value_monthly'])}")


if __name__ == "__main__":
    check_contract_data()
