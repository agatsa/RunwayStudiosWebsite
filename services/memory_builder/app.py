# services/memory_builder/app.py
"""
Unified Layer-2 runner.

Supports:
- MODE=daily_close | weekly | monthly | outcomes
- Auto-discovers platform/account from daily_kpis
- Backfills:
    MODE=daily_close with START_DAY / END_DAY (inclusive)
    MODE=weekly with WEEK_START (YYYY-MM-DD) optional
    MODE=monthly with MONTH (YYYY-MM) optional
- Safe defaults:
    daily_close runs for yesterday
    weekly runs for last completed week
    monthly runs for last completed month
    outcomes runs for recent actions

Env:
  DATABASE_URL                 (required; same as ingestion_service)
  MODE                         (optional; default daily_close)
  DAY                          (optional; YYYY-MM-DD) shortcut for single-day daily_close
  START_DAY, END_DAY           (optional; YYYY-MM-DD) inclusive range for daily_close
  WEEK_START                   (optional; YYYY-MM-DD) for weekly memory
  MONTH                        (optional; YYYY-MM) for monthly memory
  MIN_SPEND_WINLOSE            (optional; default 500) for daily winners/losers selection
  WEEKLY_MIN_SPEND             (optional; default 3000) for weekly winners
"""

import os

import json
import psycopg2.extras

from datetime import date, datetime, timedelta
from typing import Iterator, Optional, Tuple

from services.ingestion_service.storage.postgres import get_conn

# Import your Layer 2 jobs
from services.memory_builder.daily_close import (
    _discover_entity_levels,  # already defined in your daily_close patch
    _fetch_daily_rows,
    _fetch_7d_baselines,
    _upsert_mem_entity_daily,
    _build_digest,
)
from services.memory_builder.weekly_memory import week_start as _week_start_fn
from services.memory_builder.monthly_memory import run_monthly_memory
from services.memory_builder.action_outcomes import run_action_outcomes

from services.memory_builder.build_daily_kpis import main as run_build_daily_kpis


# -----------------------------
# Helpers
# -----------------------------

def _parse_date(s: str) -> date:
    return date.fromisoformat(s)

def _parse_month(s: str) -> Tuple[int, int]:
    y, m = s.split("-")
    return int(y), int(m)

def _daterange(start: date, end: date) -> Iterator[date]:
    # inclusive
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)

def _default_yesterday() -> date:
    return date.today() - timedelta(days=1)

def _discover_combos_for_day(conn, day: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT platform, account_id
            FROM daily_kpis
            WHERE day = %s
            """,
            (day,),
        )
        return cur.fetchall()  # list[(platform, account_id)]

def _discover_combos_for_range(conn, start: date, end: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT platform, account_id
            FROM daily_kpis
            WHERE day >= %s AND day <= %s
            """,
            (start, end),
        )
        return cur.fetchall()

def _discover_combos_for_week(conn, ws: date, we_exclusive: date):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT platform, account_id
            FROM daily_kpis
            WHERE day >= %s AND day < %s
            """,
            (ws, we_exclusive),
        )
        return cur.fetchall()

def _month_range(d: date):
    ms = date(d.year, d.month, 1)
    if d.month == 12:
        me = date(d.year + 1, 1, 1)
    else:
        me = date(d.year, d.month + 1, 1)
    return ms, me


# -----------------------------
# MODE: daily_close
# -----------------------------

def run_daily_close_for_day(day: date):
    """
    Layer 2 daily close:
    - For each (platform, account_id) present that day:
        - compute fatigue memory for all discovered entity levels (except account)
        - create/store daily digest (mem_daily_digest)
    """
    with get_conn() as conn:
        combos = _discover_combos_for_day(conn, day)

        if not combos:
            print(f"[Layer2] daily_close: no daily_kpis rows for {day}")
            return

        for (platform, account_id) in combos:
            # compute fatigue per level (auto-discover)
            levels = _discover_entity_levels(conn, day, platform, account_id)

            for level in levels:
                rows = _fetch_daily_rows(conn, day, platform, account_id, entity_level_filter=level)
                baselines = _fetch_7d_baselines(conn, day, platform, account_id, level)
                _upsert_mem_entity_daily(conn, rows, baselines)

            # build + store digest
            text, js = _build_digest(conn, day, platform, account_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mem_daily_digest(platform, account_id, day, digest_text, json_summary)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (platform, account_id, day)
                    DO UPDATE SET digest_text=EXCLUDED.digest_text, json_summary=EXCLUDED.json_summary;
                    """,
                    (platform, account_id, day, text, psycopg2.extras.Json(js)),
                )

        print(f"[Layer2] daily_close complete for {day} (combos={len(combos)})")


def run_daily_close():
    # Priority: DAY (single day) > START_DAY/END_DAY (range) > default yesterday
    day_env = os.getenv("DAY")
    start_env = os.getenv("START_DAY")
    end_env = os.getenv("END_DAY")

    if day_env:
        run_daily_close_for_day(_parse_date(day_env))
        return

    if start_env and end_env:
        start = _parse_date(start_env)
        end = _parse_date(end_env)
        for d in _daterange(start, end):
            run_daily_close_for_day(d)
        return

    # default: yesterday
    run_daily_close_for_day(_default_yesterday())


# -----------------------------
# MODE: weekly
# -----------------------------

def run_weekly_memory_unified():
    """
    Weekly digest for each platform/account.
    Default: last completed week if run on Monday morning,
             otherwise uses current week-to-date minus 1 day start anchor.
    Override with WEEK_START=YYYY-MM-DD.
    """
    ws_env = os.getenv("WEEK_START")
    today = date.today()

    if ws_env:
        ws = _parse_date(ws_env)
    else:
        # If today is Monday, weekly run typically wants last week
        # Else choose week containing yesterday (completed partial)
        anchor = today - timedelta(days=1)
        ws = _week_start_fn(anchor)

    we = ws + timedelta(days=7)

    # Build digest in the same style as your weekly_memory.py module
    # We reuse your existing weekly_memory.py runner (which auto chooses),
    # but this unified function guarantees the ws is controlled if provided.
    with get_conn() as conn:
        combos = _discover_combos_for_week(conn, ws, we)

        for (platform, account_id) in combos:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                           CASE WHEN COALESCE(SUM(spend),0)>0 THEN COALESCE(SUM(revenue),0)/SUM(spend) ELSE 0 END roas
                    FROM daily_kpis
                    WHERE platform=%s AND account_id=%s AND day >= %s AND day < %s
                    """,
                    (platform, account_id, ws, we),
                )
                spend, revenue, roas = cur.fetchone()

                min_spend = float(os.getenv("WEEKLY_MIN_SPEND", "3000"))
                cur.execute(
                    """
                    SELECT entity_id, SUM(spend) spend, AVG(roas) roas, AVG(ctr) ctr
                    FROM daily_kpis
                    WHERE platform=%s AND account_id=%s AND entity_level='ad'
                      AND day >= %s AND day < %s
                    GROUP BY entity_id
                    HAVING SUM(spend) >= %s
                    ORDER BY AVG(roas) DESC
                    LIMIT 5
                    """,
                    (platform, account_id, ws, we, min_spend),
                )
                winners = [
                    {"ad_id": r[0], "spend": float(r[1] or 0), "roas": float(r[2] or 0), "ctr": float(r[3] or 0)}
                    for r in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT entity_id, COUNT(*) fatigue_days, AVG(fatigue_score) avg_fatigue
                    FROM mem_entity_daily
                    WHERE platform=%s AND account_id=%s AND entity_level='ad'
                      AND day >= %s AND day < %s AND fatigue_flag=true
                    GROUP BY entity_id
                    ORDER BY AVG(fatigue_score) DESC
                    LIMIT 10
                    """,
                    (platform, account_id, ws, we),
                )
                fatigue = [
                    {"ad_id": r[0], "fatigue_days": int(r[1] or 0), "avg_fatigue": float(r[2] or 0)}
                    for r in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT objection_type, SUM(count)
                    FROM fact_objections_daily
                    WHERE platform=%s AND account_id=%s AND day >= %s AND day < %s
                    GROUP BY objection_type
                    ORDER BY SUM(count) DESC
                    """,
                    (platform, account_id, ws, we),
                )
                objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

            text = "\n".join(
                [
                    f"Week {ws} → {we - timedelta(days=1)} | {platform.upper()} | {account_id}",
                    "",
                    f"Spend ₹{float(spend or 0):.0f} | Revenue ₹{float(revenue or 0):.0f} | ROAS {float(roas or 0):.2f}",
                    "",
                    "Top Winners:",
                    *([f"- ad {w['ad_id']} | spend ₹{w['spend']:.0f} | roas {w['roas']:.2f} | ctr {w['ctr']:.2f}%"
                       for w in winners] if winners else ["- none"]),
                    "",
                    "Fatigue Watchlist:",
                    *([f"- ad {f['ad_id']} | fatigue_days {f['fatigue_days']} | avg_fatigue {f['avg_fatigue']:.2f}"
                       for f in fatigue] if fatigue else ["- none"]),
                    "",
                    "Objections:",
                    *([f"- {k}: {v}" for k, v in objections.items()] if objections else ["- none"]),
                ]
            )

            js = {
                "totals": {"spend": float(spend or 0), "revenue": float(revenue or 0), "roas": float(roas or 0)},
                "winners": winners,
                "fatigue": fatigue,
                "objections": objections,
                "week_start": str(ws),
                "week_end": str(we),
            }

            with get_conn() as conn2:
                with conn2.cursor() as cur2:
                  cur2.execute(
                        """
                        INSERT INTO mem_weekly_digest(platform, account_id, week_start, digest_text, json_summary)
                        VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (platform, account_id, week_start)
                        DO UPDATE SET digest_text=EXCLUDED.digest_text, json_summary=EXCLUDED.json_summary;
                        """,
                        (platform, account_id, ws, text, psycopg2.extras.Json(js)),
                    )

        print(f"[Layer2] weekly_memory complete week_start={ws} (combos={len(combos)})")


# -----------------------------
# MODE: monthly
# -----------------------------

def run_monthly_memory_unified():
    """
    Default: last completed month.
    Override: MONTH=YYYY-MM
    """
    month_env = os.getenv("MONTH")
    if month_env:
        # monthly_memory.py already supports month_str
        run_monthly_memory(month_env)
        return
    run_monthly_memory(None)


# -----------------------------
# MODE: outcomes
# -----------------------------

def run_outcomes_unified():
    run_action_outcomes()


# -----------------------------
# main
# -----------------------------

def main():
    mode = (os.getenv("MODE") or "daily_close").strip().lower()

    if mode == "daily_close":
        run_daily_close()
    elif mode == "weekly":
        run_weekly_memory_unified()
    elif mode == "monthly":
        run_monthly_memory_unified()
    elif mode == "outcomes":
        run_outcomes_unified()
    elif mode == "build_daily_kpis":
        run_build_daily_kpis()
    else:
        raise RuntimeError(f"Unknown MODE={mode}. Use daily_close|weekly|monthly|outcomes")

if __name__ == "__main__":
    main()