"""
Run DB migration v14 — LP Builder tables.
Usage: py -3 run-migration-v14.py
"""
import os, sys
from pathlib import Path

# Load .env
env_file = Path(__file__).parent / "services" / "agent_swarm" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DB_URL = os.getenv("DB_URL", "")
if not DB_URL:
    print("ERROR: DB_URL not set in environment or .env")
    sys.exit(1)

import psycopg2

sql = Path(__file__).parent / "infra" / "db_additions_v14.sql"
ddl = sql.read_text()

print(f"Running migration v14 against DB...")
with psycopg2.connect(DB_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
print("Migration v14 complete.")
