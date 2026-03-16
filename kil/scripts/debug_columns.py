#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import psycopg
from dotenv import load_dotenv

load_dotenv()

conn = psycopg.connect(
    host=os.environ.get("KELAVA_HOST"),
    port=os.environ.get("KELAVA_PORT"),
    dbname=os.environ.get("KELAVA_DB"),
    user=os.environ.get("KELAVA_USER"),
    password=os.environ.get("KELAVA_PASSWORD"),
)
cursor = conn.cursor()

for table in ["t_road_plan", "t_road_plan_foto"]:
    print(f"--- {table} ---")
    cursor.execute(
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'"
    )
    for row in cursor.fetchall():
        print(row[0])
