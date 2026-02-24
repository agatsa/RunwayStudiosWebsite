# services/agent_swarm/reporter/whatsapp_hourly.py
"""
Layer 5 — Hourly WhatsApp Reporter
Claude summarizes performance data + agent outputs → sends to WA.
"""
import json
import zoneinfo
from datetime import datetime, timedelta, timezone

import anthropic

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, WA_REPORT_NUMBER,
)
from services.agent_swarm.db import get_conn
from services.agent_swarm.wa import send_text

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _fetch_report_data(platform: str, account_id: str) -> dict:
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)
    t1h = now_utc - timedelta(hours=1)
    t24h = now_utc - timedelta(hours=24)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Last 24h rolling window (more reliable than IST calendar day,
            # especially for early-morning reports before much data has come in)
            cur.execute(
                """
                SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                       COALESCE(SUM(conversions),0), COALESCE(SUM(clicks),0),
                       COALESCE(SUM(impressions),0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t24h),
            )
            r = cur.fetchone()
            spend_today = float(r[0] or 0)
            revenue_today = float(r[1] or 0)
            conv_today = int(r[2] or 0)
            clicks_today = int(r[3] or 0)
            imp_today = int(r[4] or 0)

            roas_today = round(revenue_today / spend_today, 2) if spend_today > 0 else 0
            cac_today = round(spend_today / conv_today, 0) if conv_today > 0 else 0

            # Last 1h
            cur.execute(
                """
                SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t1h),
            )
            r1 = cur.fetchone()
            spend_1h = float(r1[0] or 0)
            roas_1h = round(float(r1[1] or 0) / spend_1h, 2) if spend_1h > 0 else 0

            # Recent alerts (last 2h, unresolved)
            cur.execute(
                """
                SELECT alert_type, severity, summary
                FROM alerts
                WHERE platform=%s AND account_id=%s
                  AND ts >= NOW() - INTERVAL '2 hours'
                  AND resolved=false
                ORDER BY ts DESC LIMIT 5
                """,
                (platform, account_id),
            )
            alerts = [
                {"type": r[0], "severity": r[1], "summary": r[2]}
                for r in cur.fetchall()
            ]

            # Recent actions taken (last 2h)
            cur.execute(
                """
                SELECT action_type, entity_id, status, triggered_by
                FROM action_log
                WHERE platform=%s AND account_id=%s
                  AND ts >= NOW() - INTERVAL '2 hours'
                ORDER BY ts DESC LIMIT 5
                """,
                (platform, account_id),
            )
            actions = [
                {"type": r[0], "entity": r[1][:20] if r[1] else "", "status": r[2], "by": r[3]}
                for r in cur.fetchall()
            ]

            # Top objections today
            cur.execute(
                """
                SELECT objection_type, SUM(count)
                FROM fact_objections_daily
                WHERE platform=%s AND account_id=%s AND day = CURRENT_DATE
                GROUP BY objection_type ORDER BY SUM(count) DESC LIMIT 3
                """,
                (platform, account_id),
            )
            objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

            # Latest landing page score
            cur.execute(
                """
                SELECT overall_score, issues
                FROM landing_page_audits
                ORDER BY ts DESC LIMIT 1
                """,
            )
            lp_row = cur.fetchone()
            lp_score = float(lp_row[0] or 0) if lp_row else None
            lp_issues = json.loads(lp_row[1] or "[]") if lp_row else []

            # Pending approvals
            cur.execute(
                """
                SELECT COUNT(*) FROM pending_approvals WHERE status='pending'
                """,
            )
            pending_approvals = int(cur.fetchone()[0] or 0)

            # Comment stats — global aggregates (last 24h)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE first_seen_at >= NOW() - INTERVAL '24 hours'),
                    COUNT(*) FILTER (WHERE status='auto_replied'
                        AND replied_at >= NOW() - INTERVAL '24 hours'),
                    COUNT(*) FILTER (WHERE status='pending')
                FROM comment_replies
                WHERE platform=%s AND account_id=%s
                """,
                (platform, account_id),
            )
            _cr = cur.fetchone() or (0, 0, 0)
            comment_new_24h = int(_cr[0] or 0)
            comment_auto_replied = int(_cr[1] or 0)
            comment_pending = int(_cr[2] or 0)
            # Top objection type in last 24h
            cur.execute(
                """
                SELECT objection_type
                FROM comment_replies
                WHERE platform=%s AND account_id=%s
                  AND first_seen_at >= NOW() - INTERVAL '24 hours'
                GROUP BY objection_type
                ORDER BY COUNT(*) DESC
                LIMIT 1
                """,
                (platform, account_id),
            )
            _top = cur.fetchone()
            comment_top_type = _top[0] if _top else None

    return {
        "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M IST"),
        "last_24h": {
            "spend": spend_today,
            "revenue": revenue_today,
            "roas": roas_today,
            "conversions": conv_today,
            "clicks": clicks_today,
            "impressions": imp_today,
            "cac": cac_today,
        },
        "last_1h": {"spend": spend_1h, "roas": roas_1h},
        "alerts": alerts,
        "actions": actions,
        "objections": objections,
        "landing_page": {"score": lp_score, "top_issues": lp_issues[:2]},
        "pending_approvals": pending_approvals,
        "comments": {
            "new_24h": comment_new_24h,
            "auto_replied_24h": comment_auto_replied,
            "pending_review": comment_pending,
            "top_type": comment_top_type,
        },
    }


def generate_and_send_report(platform: str, account_id: str, admin_wa_id: str = None) -> dict:
    data = _fetch_report_data(platform, account_id)

    ist_time = data["timestamp_ist"]  # e.g. "2026-02-19 14:05 IST"
    ist_hhmm = ist_time.split(" ")[1]   # e.g. "14:05"
    next_hour = f"{(int(ist_hhmm.split(':')[0]) + 1) % 24:02d}:00"

    prompt = f"""You are an AI marketing analyst for an Indian D2C brand.
Write a concise WhatsApp hourly performance report.

DATA:
{json.dumps(data, indent=2, default=str)}

RULES:
- Max 300 words total
- Use emojis sparingly but effectively
- Indian currency format: ₹12,430
- Be direct, no fluff
- Highlight the single most important issue
- All metrics shown are for the LAST 24 HOURS (rolling window), label them as such
- Show IST time: {ist_hhmm} IST
- Next check time: {next_hour} IST

FORMAT (follow exactly):
📊 {ist_hhmm} IST | Last 24h Snapshot

Spend: ₹X | ROAS: X.X | Sales: ₹X
Conversions: X | CAC: ₹X | Last 1h: ₹X

[If issues exist]
⚠️ Top Issue:
[1-2 sentences on what's happening and why]

[If actions were taken]
✅ Actions Taken:
[bullet list of actions]

[If comments data in last 24h]
💬 Comments (24h): X new | X auto-replied | X pending review
Top: [top_type if available]
[If pending_review > 0: "Reply 'auto reply <id>' to auto-send AI reply"]

[If landing page data]
🔗 Landing Page: X/10
[top issue if score < 7]

[If pending approvals]
⏳ [N] approval(s) pending - reply 'approve/reject [id]'

Next check: {next_hour} IST"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    message = response.content[0].text.strip()
    target_number = admin_wa_id or WA_REPORT_NUMBER
    sent = send_text(target_number, message)

    return {
        "ok": True,
        "sent": sent,
        "message": message,
        "data_snapshot": data,
    }
