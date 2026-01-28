#!/usr/bin/env python3
import os
import json
import mysql.connector
from mysql.connector import errorcode

# Load environment variables
SRC_HOST = os.getenv("SRC_HOST")
SRC_PORT = int(os.getenv("SRC_PORT", 3306))
SRC_USER = os.getenv("SRC_USER")
SRC_PASSWORD = os.getenv("SRC_PASSWORD")
SRC_DB = os.getenv("SRC_DB")

TGT_HOST = os.getenv("TGT_HOST")
TGT_PORT = int(os.getenv("TGT_PORT", 3306))
TGT_USER = os.getenv("TGT_USER")
TGT_PASSWORD = os.getenv("TGT_PASSWORD")
TGT_DB = os.getenv("TGT_DB")

APPLIED_FILE = "applied_columns.json"

# Load applied changes from previous runs
if os.path.exists(APPLIED_FILE):
    with open(APPLIED_FILE, "r") as f:
        applied = json.load(f)
else:
    applied = {}

def save_applied():
    with open(APPLIED_FILE, "w") as f:
        json.dump(applied, f, indent=2)

def get_columns(conn, db_name):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(f"""
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{db_name}';
    """)
    columns = {}
    for row in cursor.fetchall():
        table = row['TABLE_NAME']
        col = row['COLUMN_NAME']
        columns.setdefault(table, {})[col] = row
    cursor.close()
    return columns

def get_tables(conn, db_name):
    cursor = conn.cursor()
    cursor.execute(f"SHOW TABLES FROM {db_name}")
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return set(tables)

def format_default(default):
    """Return proper SQL default, handling NULL and CURRENT_TIMESTAMP correctly."""
    if default is None:
        return None
    default = str(default)
    if default.upper() in ("NULL", "CURRENT_TIMESTAMP()", "CURRENT_TIMESTAMP"):
        return default
    return f"'{default}'"

def apply_sql(cursor, sql):
    print(f"Executing: {sql}")
    try:
        cursor.execute(sql)
    except mysql.connector.Error as e:
        print(f"ERROR executing SQL: {e}")

def compare_and_sync(src_cols, tgt_cols, tgt_conn, src_tables, tgt_tables):
    tgt_cursor = tgt_conn.cursor()

    # Step 1: Check for missing tables
    for table in src_tables:
        if table not in tgt_tables:
            key = f"TABLE::{table}"
            if applied.get(key):
                continue
            cmd = input(f"Table '{table}' is missing in target. Create it LIKE source? [y/N]: ").strip().lower()
            if cmd == "y":
                sql = f"CREATE TABLE {TGT_DB}.{table} LIKE {SRC_DB}.{table}"
                apply_sql(tgt_cursor, sql)
                applied[key] = True
                save_applied()

    # Step 2: Compare columns
    for table, src_table_cols in src_cols.items():
        tgt_table_cols = tgt_cols.get(table, {})
        print(f"\n=== Table: {table} ===")
        for col_name, src_col in src_table_cols.items():
            key = f"{table}.{col_name}"
            if applied.get(key):
                continue  # Already applied/ignored

            tgt_col = tgt_table_cols.get(col_name)
            if not tgt_col:
                cmd = input(f"Column '{col_name}' is missing in target. Add? [y/N]: ").strip().lower()
                if cmd == "y":
                    default = format_default(src_col['COLUMN_DEFAULT'])
                    null_str = "NULL" if src_col['IS_NULLABLE'] == "YES" else "NOT NULL"
                    sql = f"ALTER TABLE {table} ADD COLUMN {col_name} {src_col['COLUMN_TYPE']} {null_str}"
                    if default is not None:
                        sql += f" DEFAULT {default}"
                    apply_sql(tgt_cursor, sql)
                    applied[key] = True
                    save_applied()
                continue

            # Compare type, nullability, default
            diffs = []
            if src_col['COLUMN_TYPE'] != tgt_col['COLUMN_TYPE']:
                diffs.append(f"Type: {tgt_col['COLUMN_TYPE']} -> {src_col['COLUMN_TYPE']}")
            if src_col['IS_NULLABLE'] != tgt_col['IS_NULLABLE']:
                diffs.append(f"Nullable: {tgt_col['IS_NULLABLE']} -> {src_col['IS_NULLABLE']}")
            if (src_col['COLUMN_DEFAULT'] or "").upper() != (tgt_col['COLUMN_DEFAULT'] or "").upper():
                diffs.append(f"Default: {tgt_col['COLUMN_DEFAULT']} -> {src_col['COLUMN_DEFAULT']}")

            if diffs:
                print(f"Column '{col_name}' differs: {', '.join(diffs)}")
                cmd = input(f"Apply changes to '{col_name}'? [y/N]: ").strip().lower()
                if cmd == "y":
                    default = format_default(src_col['COLUMN_DEFAULT'])
                    null_str = "NULL" if src_col['IS_NULLABLE'] == "YES" else "NOT NULL"
                    sql = f"ALTER TABLE {table} MODIFY COLUMN {col_name} {src_col['COLUMN_TYPE']} {null_str}"
                    if default is not None:
                        sql += f" DEFAULT {default}"
                    apply_sql(tgt_cursor, sql)
                    applied[key] = True
                    save_applied()
    tgt_cursor.close()

def main():
    try:
        src_conn = mysql.connector.connect(
            host=SRC_HOST, port=SRC_PORT, user=SRC_USER, password=SRC_PASSWORD, database=SRC_DB
        )
        tgt_conn = mysql.connector.connect(
            host=TGT_HOST, port=TGT_PORT, user=TGT_USER, password=TGT_PASSWORD, database=TGT_DB
        )
    except mysql.connector.Error as err:
        print("Error connecting:", err)
        return

    print(f"Fetching tables and columns from source: {SRC_DB}")
    src_tables = get_tables(src_conn, SRC_DB)
    src_cols = get_columns(src_conn, SRC_DB)

    print(f"Fetching tables and columns from target: {TGT_DB}")
    tgt_tables = get_tables(tgt_conn, TGT_DB)
    tgt_cols = get_columns(tgt_conn, TGT_DB)

    compare_and_sync(src_cols, tgt_cols, tgt_conn, src_tables, tgt_tables)

    tgt_conn.commit()
    src_conn.close()
    tgt_conn.close()
    print("\nDone.")

if __name__ == "__main__":
    main()

