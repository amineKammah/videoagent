import sqlite3
import csv
from pathlib import Path
from contextlib import contextmanager

REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = REPO_ROOT / "videoagent.db"
CSV_PATH = REPO_ROOT / "assets" / "test_customers.csv"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not CSV_PATH.exists():
        print(f"Warning: {CSV_PATH} not found. Skipping database initialization.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create table based on CSV header
    # For simplicity, we'll treat most fields as TEXT, except explicit IDs
    
    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'")
    if cursor.fetchone():
        # Table exists, for this "test" setup we might want to skip or reload?
        # Let's assume if it exists we don't reload to avoid duplicates or wiping user data
        # unless we want to force reload. For now, let's just return if it exists.
        conn.close()
        return

    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        if not fields:
            return

        # Build CREATE TABLE statement
        # We manually set id as INTEGER PRIMARY KEY and others as TEXT
        columns_def = []
        for field in fields:
            if field == 'id':
                columns_def.append(f"{field} INTEGER PRIMARY KEY")
            elif field == 'brand_id':
                columns_def.append(f"{field} INTEGER")
            else:
                columns_def.append(f"{field} TEXT")
        
        create_query = f"CREATE TABLE customers ({', '.join(columns_def)})"
        cursor.execute(create_query)

        # Insert data
        insert_query = f"INSERT INTO customers ({', '.join(fields)}) VALUES ({', '.join(['?' for _ in fields])})"
        
        rows_to_insert = []
        for row in reader:
            rows_to_insert.append([row[field] for field in fields])
        
        cursor.executemany(insert_query, rows_to_insert)
        conn.commit()
        print(f"Initialized database with {len(rows_to_insert)} customers.")

    conn.close()

def get_all_customers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
