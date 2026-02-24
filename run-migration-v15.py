"""Run DB migration v15 — sales_strategies, strategy_actions, lp_audit_cache, LP Builder tables."""
import psycopg2
from pathlib import Path

conn = psycopg2.connect(
    host="34.93.56.252", port=5432,
    dbname="wa_agency", user="postgres", password="job314",
    connect_timeout=10,
)
sql = Path(__file__).parent / "infra" / "db_additions_v15.sql"
print("Running migration v15...")
with conn:
    with conn.cursor() as cur:
        cur.execute(sql.read_text())
conn.close()
print("Migration v15 complete.")
