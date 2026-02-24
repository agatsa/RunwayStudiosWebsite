from datetime import timedelta
from services.ingestion_service.storage.postgres import get_conn

WINDOWS = [6, 24, 72]

def run_action_outcomes():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # recent actions that do not yet have outcomes computed for all windows
            cur.execute("""
              SELECT action_id, ts, platform, account_id, entity_level, entity_id
              FROM action_log
              WHERE ts >= NOW() - INTERVAL '10 days'
              ORDER BY ts DESC
              LIMIT 200
            """)
            actions = cur.fetchall()

        for (action_id, ts, platform, account_id, level, eid) in actions:
            for w in WINDOWS:
                with conn.cursor() as cur:
                    cur.execute("""
                      SELECT 1 FROM action_outcome WHERE action_id=%s AND window_hours=%s
                    """, (action_id, w))
                    if cur.fetchone():
                        continue

                # baseline = 24h before action time (or last day)
                # after = window_hours after action time
                with get_conn() as conn2:
                    with conn2.cursor() as cur:
                        cur.execute("""
                          SELECT
                            COALESCE(AVG(roas),0), COALESCE(AVG(ctr),0), COALESCE(SUM(spend),0)
                          FROM kpi_hourly
                          WHERE platform=%s AND account_id=%s AND entity_level=%s AND entity_id=%s
                            AND hour_ts >= (%s - INTERVAL '24 hours')
                            AND hour_ts < %s
                        """, (platform, account_id, level, eid, ts, ts))
                        b_roas, b_ctr, b_spend = cur.fetchone()

                        cur.execute("""
                          SELECT
                            COALESCE(AVG(roas),0), COALESCE(AVG(ctr),0), COALESCE(SUM(spend),0)
                          FROM kpi_hourly
                          WHERE platform=%s AND account_id=%s AND entity_level=%s AND entity_id=%s
                            AND hour_ts >= %s
                            AND hour_ts < (%s + (%s || ' hours')::interval)
                        """, (platform, account_id, level, eid, ts, ts, w))
                        a_roas, a_ctr, a_spend = cur.fetchone()

                        d_roas = float(a_roas or 0) - float(b_roas or 0)
                        d_ctr  = float(a_ctr or 0) - float(b_ctr or 0)
                        d_spend = float(a_spend or 0) - float(b_spend or 0)

                        cur.execute("""
                          INSERT INTO action_outcome(action_id, window_hours, delta_roas, delta_ctr, delta_spend, notes)
                          VALUES (%s,%s,%s,%s,%s,%s)
                          ON CONFLICT (action_id, window_hours) DO NOTHING
                        """, (action_id, w, d_roas, d_ctr, d_spend, "auto-computed"))

        print("[Layer2] action_outcomes computed")

if __name__ == "__main__":
    run_action_outcomes()