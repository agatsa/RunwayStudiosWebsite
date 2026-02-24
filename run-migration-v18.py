"""Run DB migration v18 — YouTube Channel Intelligence tables."""
import psycopg2
from pathlib import Path

conn = psycopg2.connect(
    host="34.93.56.252", port=5432,
    dbname="wa_agency", user="postgres", password="job314",
    connect_timeout=10,
)
sql = Path(__file__).parent / "infra" / "db_v18_youtube.sql"
print("Running migration v18 (YouTube)...")
with conn:
    with conn.cursor() as cur:
        cur.execute(sql.read_text())
conn.close()
print("Migration v18 complete.")
