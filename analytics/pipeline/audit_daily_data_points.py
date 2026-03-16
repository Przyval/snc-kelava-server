import json
import os
import sys

# Add current directory to path to allow imports
sys.path.append(os.getcwd())

try:
    from kil.db.kelava_db import execute_kelava_query
except ImportError as e:
    print(f"Error importing kil.db.kelava_db: {e}")
    sys.exit(1)


def audit_data_points():
    print("# AUDIT DATA POINT HARIAN (Direct DB Inspection)\n")

    # 1. CORE VISIT DATA (t_visit)
    print("## 1. DATA KUNJUNGAN (t_visit)")
    print("Mencatat aktivitas teknisi di lokasi. Data points:")

    columns_visit = execute_kelava_query("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 't_visit'
        ORDER BY ordinal_position
    """)
    for col in columns_visit:
        print(f"- {col['column_name']} ({col['data_type']})")

    # Inspect JSON metadata keys if any
    print("\n--- Deep Dive: Meta & Additional Data (JSON Content) ---")
    meta_sample = execute_kelava_query("""
        SELECT additional_data, meta_distance
        FROM t_visit 
        WHERE additional_data IS NOT NULL LIMIT 1
    """)
    if meta_sample:
        row = meta_sample[0]
        if row["additional_data"]:
            print(
                "Keys in 'additional_data':",
                list(row["additional_data"].keys())
                if isinstance(row["additional_data"], dict)
                else row["additional_data"],
            )
        if row["meta_distance"]:
            print(
                "Keys in 'meta_distance':",
                list(row["meta_distance"].keys())
                if isinstance(row["meta_distance"], dict)
                else row["meta_distance"],
            )

    # 2. EVIDENCE / PHOTOS (t_road_plan_foto)
    print("\n## 2. BUKTI FOTO (t_road_plan_foto)")
    columns_foto = execute_kelava_query("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 't_road_plan_foto'
    """)
    for col in columns_foto:
        print(f"- {col['column_name']} ({col['data_type']})")

    # 3. FORM DATA / FINDINGS (t_visit_data)
    print("\n## 3. LAPORAN & TEMUAN (t_visit_data)")
    print("Data form digital yang diisi teknisi.")
    columns_vd = execute_kelava_query("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 't_visit_data'
    """)
    for col in columns_vd:
        print(f"- {col['column_name']} ({col['data_type']})")

    # 4. PRODUCT USAGE (t_visit_product)
    print("\n## 4. PENGGUNAAN BAHAN/KIMIA (t_visit_product)")
    columns_vp = execute_kelava_query("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 't_visit_product'
    """)
    for col in columns_vp:
        print(f"- {col['column_name']} ({col['data_type']})")


if __name__ == "__main__":
    audit_data_points()
