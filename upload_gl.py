"""
GL Upload Script
----------------
Usage:
    python upload_gl.py GL_012024.csv          # load a single file
    python upload_gl.py GL_*2024.csv           # load a full year (shell glob)
    python upload_gl.py --list                 # show what's already loaded
    python upload_gl.py --delete 012024        # remove a month from the DB

The database file (gl.db) is created automatically on first run.
Re-uploading the same month is safe — existing rows are replaced.
"""

import sqlite3
import csv
import os
import sys
import glob
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "gl.db")

# Map CSV column names → DB column names (snake_case, no spaces/special chars)
COLUMN_MAP = {
    "Customer":           "customer",
    "Vendor":             "vendor",
    "Amount":             "amount",
    "Data Type":          "data_type",
    "Scenario":           "scenario",
    "Posting Date":       "posting_date",
    "Account ID":         "account_id",
    "Account Name":       "account_name",
    "DR_KPI":             "dr_kpi",
    "Report_Field":       "report_field",
    "Entity":             "entity",
    "Reporting Year":     "reporting_year",
    "Account Full":       "account_full",
    "Intercompany":       "intercompany",
    "Valid Line?":        "valid_line",
    "Posting Amount":     "posting_amount",
    "Posting Currency":   "posting_currency",
    "Reporting Currency": "reporting_currency",
    "Currency EOP rate":  "currency_eop_rate",
    "Currency AVG rate":  "currency_avg_rate",
    "Reporting Month":    "reporting_month",
    "Description":        "description",
    "DR_ACC_Sign":        "dr_acc_sign",
    "Department":         "department",
    "Account Group L2":   "account_group_l2",
    "Account Group L1":   "account_group_l1",
    "Account Group L0":   "account_group_l0",
    "Location":           "location",
    "Debit":              "debit",
    "Credit":             "credit",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS gl_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file         TEXT NOT NULL,
    loaded_at           TEXT NOT NULL,
    customer            TEXT,
    vendor              TEXT,
    amount              REAL,
    data_type           TEXT,
    scenario            TEXT,
    posting_date        TEXT,
    account_id          INTEGER,
    account_name        TEXT,
    dr_kpi              TEXT,
    report_field        TEXT,
    entity              TEXT,
    reporting_year      INTEGER,
    account_full        TEXT,
    intercompany        TEXT,
    valid_line          TEXT,
    posting_amount      REAL,
    posting_currency    TEXT,
    reporting_currency  TEXT,
    currency_eop_rate   REAL,
    currency_avg_rate   REAL,
    reporting_month     TEXT,
    description         TEXT,
    dr_acc_sign         INTEGER,
    department          TEXT,
    account_group_l2    TEXT,
    account_group_l1    TEXT,
    account_group_l0    TEXT,
    location            TEXT,
    debit               REAL,
    credit              REAL
);

CREATE INDEX IF NOT EXISTS idx_posting_date   ON gl_transactions(posting_date);
CREATE INDEX IF NOT EXISTS idx_account_id     ON gl_transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_entity         ON gl_transactions(entity);
CREATE INDEX IF NOT EXISTS idx_location       ON gl_transactions(location);
CREATE INDEX IF NOT EXISTS idx_scenario       ON gl_transactions(scenario);
CREATE INDEX IF NOT EXISTS idx_source_file    ON gl_transactions(source_file);
CREATE INDEX IF NOT EXISTS idx_account_group0 ON gl_transactions(account_group_l0);
CREATE INDEX IF NOT EXISTS idx_account_group1 ON gl_transactions(account_group_l1);
"""

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    for stmt in CREATE_TABLE_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()

def coerce(value, col):
    """Convert empty strings to None; cast numeric columns."""
    if value == "" or value is None:
        return None
    if col in ("amount", "posting_amount", "currency_eop_rate",
               "currency_avg_rate", "debit", "credit"):
        try:
            return float(value)
        except ValueError:
            return None
    if col in ("account_id", "reporting_year", "dr_acc_sign"):
        try:
            return int(float(value))
        except ValueError:
            return None
    return value

def load_file(conn, filepath):
    filename = os.path.basename(filepath)

    if not os.path.exists(filepath):
        print(f"  ERROR: file not found — {filepath}")
        return

    # Delete any existing rows for this source file (idempotent re-upload)
    deleted = conn.execute(
        "DELETE FROM gl_transactions WHERE source_file = ?", (filename,)
    ).rowcount
    if deleted:
        print(f"  Removed {deleted} existing rows for {filename}")

    loaded_at = datetime.now(timezone.utc).isoformat()

    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows_inserted = 0
        for row in reader:
            db_row = {"source_file": filename, "loaded_at": loaded_at}
            for csv_col, db_col in COLUMN_MAP.items():
                db_row[db_col] = coerce(row.get(csv_col, ""), db_col)

            placeholders = ", ".join(f":{k}" for k in db_row)
            columns = ", ".join(db_row.keys())
            conn.execute(
                f"INSERT INTO gl_transactions ({columns}) VALUES ({placeholders})",
                db_row,
            )
            rows_inserted += 1

    conn.commit()
    print(f"  Loaded {rows_inserted} rows  << {filename}")

def list_loaded(conn):
    rows = conn.execute("""
        SELECT source_file, COUNT(*) as rows, MAX(loaded_at) as last_loaded
        FROM gl_transactions
        GROUP BY source_file
        ORDER BY source_file
    """).fetchall()
    if not rows:
        print("Database is empty — no files loaded yet.")
        return
    print(f"\n{'File':<20} {'Rows':>6}  {'Loaded At (UTC)'}")
    print("-" * 60)
    for r in rows:
        print(f"{r['source_file']:<20} {r['rows']:>6}  {r['last_loaded']}")
    total = sum(r["rows"] for r in rows)
    print("-" * 60)
    print(f"{'TOTAL':<20} {total:>6}\n")

def delete_month(conn, mmyyyy):
    filename = f"GL_{mmyyyy}.csv"
    deleted = conn.execute(
        "DELETE FROM gl_transactions WHERE source_file = ?", (filename,)
    ).rowcount
    conn.commit()
    print(f"Deleted {deleted} rows for {filename}")

def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    conn = get_connection()
    init_db(conn)

    if args[0] == "--list":
        list_loaded(conn)

    elif args[0] == "--delete":
        if len(args) < 2:
            print("Usage: python upload_gl.py --delete MMYYYY")
            sys.exit(1)
        delete_month(conn, args[1])

    else:
        # Expand any glob patterns (needed on Windows where shell doesn't expand)
        files = []
        for pattern in args:
            matched = glob.glob(pattern)
            files.extend(matched if matched else [pattern])

        if not files:
            print("No matching files found.")
            sys.exit(1)

        files = sorted(files)
        print(f"\nLoading {len(files)} file(s) into {DB_PATH}\n")
        for filepath in files:
            load_file(conn, filepath)
        print("\nDone.")
        list_loaded(conn)

    conn.close()

if __name__ == "__main__":
    main()
