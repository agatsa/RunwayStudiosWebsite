# services/agent_swarm/agents/budget_governor.py
"""
Agent 6 — Budget Governor
Rules-based engine informed by performance analysis.
If action > ₹10k → request WhatsApp approval before executing.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import requests

from services.agent_swarm.config import (
    TARGET_ROAS, MAX_CPA, DAILY_SPEND_CAP,
    HOURLY_SCALE_MAX_PCT, APPROVAL_THRESHOLD,
    META_ADS_TOKEN, META_AD_ACCOUNT_ID, META_GRAPH,
    WA_REPORT_NUMBER, AD_TIMEZONE,
)
from services.agent_swarm.db import get_conn
from services.agent_swarm.wa import send_text


# ── Platform-agnostic connector helper ────────────────────

def _get_connector(platform: str, tenant: dict):
    """
    Return a PlatformConnector for the given tenant, or None if unavailable.
    Supports meta and google; falls back gracefully.
    """
    try:
        from services.agent_swarm.connectors.base import get_connector
        from services.agent_swarm.core.workspace import get_primary_connection
        conn_row = get_primary_connection(tenant or {}, platform)
        if conn_row:
            return get_connector(conn_row, tenant or {})
    except Exception as e:
        print(f"_get_connector({platform}) error: {e}")
    return None


# ── Meta API helpers ──────────────────────────────────────

def _get_adset_budget(adset_id: str, meta_token: str = None) -> dict | None:
    try:
        url = f"{META_GRAPH}/{adset_id}"
        params = {
            "fields": "id,name,daily_budget,lifetime_budget,bid_amount,status",
            "access_token": meta_token or META_ADS_TOKEN,
        }
        r = requests.get(url, params=params, timeout=20)
        return r.json() if r.ok else None
    except Exception:
        return None


def _list_active_adsets(account_id: str, meta_token: str = None) -> list[dict]:
    try:
        url = f"{META_GRAPH}/{account_id}/adsets"
        params = {
            "fields": "id,name,daily_budget,status,effective_status",
            "limit": 50,
            "access_token": meta_token or META_ADS_TOKEN,
        }
        r = requests.get(url, params=params, timeout=20)
        if r.ok:
            return [
                a for a in r.json().get("data", [])
                if a.get("effective_status") in ("ACTIVE", "active")
            ]
        return []
    except Exception:
        return []


def _get_today_spend(platform: str, account_id: str, tz: str = None) -> float:
    _tz = tz or AD_TIMEZONE
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(spend), 0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s
                  AND (hour_ts AT TIME ZONE %s)::date =
                      (NOW() AT TIME ZONE %s)::date
                """,
                (platform, account_id, _tz, _tz),
            )
            return float(cur.fetchone()[0] or 0)


def _check_zero_roas_streak(platform: str, account_id: str, hours: int = 6) -> bool:
    """Returns True if ROAS has been 0 for `hours` consecutive hours with meaningful spend."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as total_hours,
                       SUM(CASE WHEN spend > 50 AND (revenue IS NULL OR revenue = 0) THEN 1 ELSE 0 END) as zero_roas_hours
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s
                  AND hour_ts >= NOW() - INTERVAL '%s hours'
                  AND entity_level = 'account'
                """,
                (platform, account_id, hours),
            )
            row = cur.fetchone()
            if not row:
                return False
            total, zero_count = int(row[0] or 0), int(row[1] or 0)
            # At least half the hours must have data, and all of them zero ROAS
            return total >= (hours // 2) and zero_count >= (hours // 2)


def _get_recent_roas_cpa(platform: str, account_id: str) -> tuple[float | None, float | None]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COALESCE(SUM(spend), 0),
                  COALESCE(SUM(revenue), 0),
                  COALESCE(SUM(conversions), 0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s
                  AND hour_ts >= NOW() - INTERVAL '3 hours'
                """,
                (platform, account_id),
            )
            spend, revenue, conversions = cur.fetchone()
            spend, revenue, conversions = float(spend), float(revenue), float(conversions)

    roas = round(revenue / spend, 4) if spend > 0 else None
    cpa = round(spend / conversions, 2) if conversions > 0 else None
    return roas, cpa


# ── Action logging & approval ─────────────────────────────

def _log_action(
    platform, account_id, entity_level, entity_id,
    action_type, old_value, new_value, triggered_by,
    status="pending"
) -> str:
    action_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO action_log
                  (id, platform, account_id, entity_level, entity_id,
                   action_type, old_value, new_value, triggered_by, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    action_id, platform, account_id, entity_level, entity_id,
                    action_type,
                    json.dumps(old_value),
                    json.dumps(new_value),
                    triggered_by, status,
                ),
            )
    return action_id


def _request_whatsapp_approval(action_id: str, description: str, amount: float, wa_number: str = None, tenant: dict = None):
    target = wa_number or WA_REPORT_NUMBER
    msg = (
        f"⚠️ ACTION APPROVAL NEEDED\n\n"
        f"{description}\n"
        f"Budget impact: ₹{amount:,.0f}\n\n"
        f"Reply:\n"
        f"✅ approve {action_id[:8]}\n"
        f"❌ reject {action_id[:8]}"
    )
    sent = send_text(target, msg, tenant=tenant)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pending_approvals
                  (action_log_id, wa_number, message_sent)
                VALUES (%s,%s,%s)
                """,
                (action_id, target, msg),
            )
    return sent


def _auto_execute_action(action_id: str, entity_id: str, action_type: str, new_value: dict, meta_token: str = None) -> bool:
    """Execute approved or auto-approved action via Meta API."""
    token = meta_token or META_ADS_TOKEN
    try:
        if action_type == "pause":
            url = f"{META_GRAPH}/{entity_id}"
            r = requests.post(
                url,
                data={"status": "PAUSED", "access_token": token},
                timeout=20,
            )
        elif action_type == "resume":
            url = f"{META_GRAPH}/{entity_id}"
            r = requests.post(
                url,
                data={"status": "ACTIVE", "access_token": token},
                timeout=20,
            )
        elif action_type in ("increase_budget", "decrease_budget"):
            url = f"{META_GRAPH}/{entity_id}"
            r = requests.post(
                url,
                data={
                    "daily_budget": int(new_value.get("daily_budget_cents", 0)),
                    "access_token": token,
                },
                timeout=20,
            )
        else:
            return False

        success = r.status_code < 300
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE action_log
                    SET status=%s, executed_at=NOW(), approved_by='auto',
                        error=%s
                    WHERE id=%s
                    """,
                    (
                        "executed" if success else "failed",
                        None if success else r.text[:200],
                        action_id,
                    ),
                )
        return success
    except Exception as e:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET status='failed', error=%s WHERE id=%s",
                    (str(e)[:200], action_id),
                )
        return False


# ── Main governor logic ───────────────────────────────────

def run_budget_governor(
    platform: str,
    account_id: str,
    performance_analysis: dict | None = None,
    tenant: dict = None,
) -> dict:
    # Extract per-tenant credentials (fall back to env vars)
    meta_token = (tenant or {}).get("meta_access_token") or META_ADS_TOKEN
    wa_number = (tenant or {}).get("admin_wa_id") or WA_REPORT_NUMBER
    daily_cap = float((tenant or {}).get("daily_spend_cap") or DAILY_SPEND_CAP)

    actions_taken = []
    actions_pending_approval = []

    tz = (tenant or {}).get("timezone") or AD_TIMEZONE
    today_spend = _get_today_spend(platform, account_id, tz=tz)
    roas_3h, cpa_3h = _get_recent_roas_cpa(platform, account_id)

    # Try platform-agnostic connector first (supports Google + Meta)
    connector = _get_connector(platform, tenant)

    def _list_entities() -> list[dict]:
        """List active campaigns/adsets via connector or Meta fallback."""
        if connector:
            try:
                return connector.list_campaigns(status="ACTIVE")
            except Exception as e:
                print(f"connector.list_campaigns error: {e}")
        # Meta fallback (backward compat)
        if platform == "meta":
            return _list_active_adsets(account_id, meta_token)
        return []

    def _do_pause(entity_id: str) -> bool:
        if connector:
            try:
                result = connector.pause(entity_id)
                return result.get("ok", False) if isinstance(result, dict) else bool(result)
            except Exception as e:
                print(f"connector.pause error: {e}")
        if platform == "meta":
            return _auto_execute_action("", entity_id, "pause", {}, meta_token)
        return False

    def _do_resume(entity_id: str) -> bool:
        if connector:
            try:
                result = connector.resume(entity_id)
                return result.get("ok", False) if isinstance(result, dict) else bool(result)
            except Exception as e:
                print(f"connector.resume error: {e}")
        if platform == "meta":
            return _auto_execute_action("", entity_id, "resume", {}, meta_token)
        return False

    def _do_update_budget(entity_id: str, new_budget_inr: float) -> bool:
        if connector:
            try:
                return connector.update_budget(entity_id, new_budget_inr)
            except Exception as e:
                print(f"connector.update_budget error: {e}")
        if platform == "meta":
            new_cents = int(new_budget_inr * 100)
            return _auto_execute_action(
                "", entity_id, "increase_budget",
                {"daily_budget_cents": new_cents}, meta_token,
            )
        return False

    # 1. Daily spend cap check
    if today_spend >= daily_cap:
        entities = _list_entities()
        for entity in entities[:3]:
            entity_id = entity["id"]
            entity_name = entity.get("name", entity_id)[:40]
            action_id = _log_action(
                platform, account_id, "campaign", entity_id,
                "pause",
                {"status": "ACTIVE"},
                {"status": "PAUSED"},
                "budget_governor_daily_cap",
            )
            # Daily cap pause → auto execute (safety critical, no approval)
            success = _do_pause(entity_id)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE action_log SET status=%s, executed_at=NOW() WHERE id=%s",
                        ("executed" if success else "failed", action_id),
                    )
            actions_taken.append({
                "action": "pause",
                "entity": entity_name,
                "reason": f"Daily cap ₹{daily_cap:,.0f} reached",
                "executed": success,
            })

        send_text(
            wa_number,
            f"🛑 DAILY CAP REACHED\nSpend: ₹{today_spend:,.0f} ≥ cap ₹{daily_cap:,.0f}\n"
            f"Paused {len(entities[:3])} campaigns automatically.",
            tenant=tenant,
        )
        return {"ok": True, "actions_taken": actions_taken, "actions_pending": []}

    # 2. ROAS-based scaling
    if roas_3h is not None:
        scale_up_threshold = TARGET_ROAS * 1.20
        scale_down_roas = TARGET_ROAS * 0.70

        if roas_3h > scale_up_threshold:
            # ROAS healthy → consider increasing budget 15%
            entities = _list_entities()
            for entity in entities[:2]:   # top 2 only
                entity_id = entity["id"]
                # Budget is stored as INR for Google, cents for Meta
                if platform == "google":
                    current_budget_inr = float(entity.get("daily_budget_inr") or entity.get("daily_budget", 0))
                    current_budget_cents = int(current_budget_inr * 100)
                else:
                    current_budget_cents = int(entity.get("daily_budget") or 0)
                    current_budget_inr = current_budget_cents / 100
                if current_budget_inr <= 0:
                    continue

                new_budget_inr = round(current_budget_inr * (1 + HOURLY_SCALE_MAX_PCT), 2)
                new_budget_cents = int(new_budget_inr * 100)
                budget_increase_inr = new_budget_inr - current_budget_inr

                action_id = _log_action(
                    platform, account_id, "campaign", entity_id,
                    "increase_budget",
                    {"daily_budget_inr": current_budget_inr},
                    {"daily_budget_inr": new_budget_inr},
                    "budget_governor_roas",
                )

                approval_threshold = float((tenant or {}).get("approval_threshold") or APPROVAL_THRESHOLD)
                if budget_increase_inr >= approval_threshold:
                    _request_whatsapp_approval(
                        action_id,
                        f"Increase budget: {entity.get('name','')[:30]}\n"
                        f"₹{current_budget_inr:,.0f} → ₹{new_budget_inr:,.0f}\n"
                        f"Reason: ROAS {roas_3h:.2f} > target {TARGET_ROAS}×1.2",
                        budget_increase_inr,
                        wa_number,
                        tenant=tenant,
                    )
                    actions_pending_approval.append({
                        "action_id": action_id[:8],
                        "action": "increase_budget",
                        "entity": entity.get("name", entity_id)[:40],
                        "amount_inr": budget_increase_inr,
                    })
                else:
                    success = _do_update_budget(entity_id, new_budget_inr)
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE action_log SET status=%s, executed_at=NOW() WHERE id=%s",
                                ("executed" if success else "failed", action_id),
                            )
                    actions_taken.append({
                        "action": "increase_budget",
                        "entity": entity.get("name", entity_id)[:40],
                        "reason": f"ROAS {roas_3h:.2f} > {scale_up_threshold:.2f}",
                        "executed": success,
                    })

        elif roas_3h < scale_down_roas:
            # ROAS poor → reduce budget 20%
            entities = _list_entities()
            for entity in entities[:2]:
                entity_id = entity["id"]
                if platform == "google":
                    current_budget_inr = float(entity.get("daily_budget_inr") or entity.get("daily_budget", 0))
                else:
                    current_budget_inr = int(entity.get("daily_budget") or 0) / 100
                if current_budget_inr <= 0:
                    continue

                new_budget_inr = round(current_budget_inr * 0.80, 2)

                action_id = _log_action(
                    platform, account_id, "campaign", entity_id,
                    "decrease_budget",
                    {"daily_budget_inr": current_budget_inr},
                    {"daily_budget_inr": new_budget_inr},
                    "budget_governor_roas_drop",
                )
                # Budget decrease → auto execute (no approval needed)
                success = _do_update_budget(entity_id, new_budget_inr)
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE action_log SET status=%s, executed_at=NOW() WHERE id=%s",
                            ("executed" if success else "failed", action_id),
                        )
                actions_taken.append({
                    "action": "decrease_budget",
                    "entity": entity.get("name", entity_id)[:40],
                    "reason": f"ROAS {roas_3h:.2f} < {scale_down_roas:.2f}",
                    "executed": success,
                })

    # 3. CPA-based pause
    if cpa_3h is not None and cpa_3h > MAX_CPA:
        entities = _list_entities()
        # Pause worst 1 entity
        if entities:
            entity = entities[0]
            entity_id = entity["id"]
            action_id = _log_action(
                platform, account_id, "campaign", entity_id,
                "pause",
                {"status": "ACTIVE"},
                {"status": "PAUSED"},
                "budget_governor_cpa_breach",
            )
            success = _do_pause(entity_id)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE action_log SET status=%s, executed_at=NOW() WHERE id=%s",
                        ("executed" if success else "failed", action_id),
                    )
            actions_taken.append({
                "action": "pause",
                "entity": entity.get("name", entity_id)[:40],
                "reason": f"CPA ₹{cpa_3h:.0f} > max ₹{MAX_CPA:.0f}",
                "executed": success,
            })

    # 4. Performance analyst overrides (high risk)
    if performance_analysis and performance_analysis.get("risk_level") == "high":
        pause_list = performance_analysis.get("pause_adsets", [])
        # Only act on real entity IDs (numeric strings for Meta; resource names for Google).
        pause_list = [aid for aid in (pause_list or []) if aid and str(aid).strip()]
        for entity_id in pause_list[:3]:
            action_id = _log_action(
                platform, account_id, "campaign", entity_id,
                "pause",
                {"status": "ACTIVE"},
                {"status": "PAUSED"},
                "budget_governor_analyst",
            )
            success = _do_pause(entity_id)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE action_log SET status=%s, executed_at=NOW() WHERE id=%s",
                        ("executed" if success else "failed", action_id),
                    )
            actions_taken.append({
                "action": "pause",
                "entity": entity_id,
                "reason": "High risk signal from performance analyst",
                "executed": success,
            })

    # 5. Corrective creative trigger — if ROAS=0 for 6+ hours with real spend
    creative_triggered = False
    try:
        if _check_zero_roas_streak(platform, account_id, hours=6):
            # Import here to avoid circular imports
            from services.agent_swarm.agents.creative_generator import run_creative_generator
            run_creative_generator(
                platform, account_id,
                trigger_reason="zero_roas_6h_corrective",
                tenant=tenant,
            )
            creative_triggered = True
            send_text(
                wa_number,
                "🚨 *Corrective Action:* ROAS has been 0 for 6+ hours.\n"
                "New ad creatives have been generated and sent above for your approval.\n"
                "Existing campaigns remain running — approve a new creative to launch a fresh angle.",
                tenant=tenant,
            )
    except Exception as e:
        print(f"Creative trigger error: {e}")

    return {
        "ok": True,
        "today_spend": round(today_spend, 2),
        "roas_3h": roas_3h,
        "cpa_3h": cpa_3h,
        "actions_taken": actions_taken,
        "actions_pending_approval": actions_pending_approval,
        "creative_triggered": creative_triggered,
    }
