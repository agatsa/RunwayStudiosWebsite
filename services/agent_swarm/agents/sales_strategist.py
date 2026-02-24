# services/agent_swarm/agents/sales_strategist.py
"""
Sales Strategist — Orchestrator of the Sales Intelligence Layer

Every 6 hours:
  1. Run fb_analyst   → deep breakdown, relevance, frequency
  2. Run competitor_monitor → FB Ad Library + competitor LP intel
  3. Run lp_analyst   → enhanced LP audit (mobile speed, promise gap, offer)
  4. Pull performance context from DB (KPIs, objections, weekly digest)
  5. Feed ALL to Claude Opus → diagnosis + prioritised action plan
  6. Save strategy + actions to DB
  7. Auto-execute safe actions (pause fatigue ads, scale winners < 15%)
  8. Send approval-tier actions to WhatsApp one-by-one
  9. Send full strategy report

Action tiers:
  auto      → execute immediately, no human needed
  approval  → WhatsApp approve/reject before executing
  strategic → report-only, human decision
"""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    META_ADS_TOKEN, META_GRAPH,
    PRODUCT_CONTEXT, LANDING_PAGE_URL,
    WA_REPORT_NUMBER,
)
from services.agent_swarm.db import get_conn
from services.agent_swarm.wa import send_text
from services.agent_swarm.agents.fb_analyst import run_fb_deep_analysis
from services.agent_swarm.agents.competitor_monitor import run_competitor_monitor
from services.agent_swarm.agents.lp_analyst import run_lp_analyst

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


# ── Playwright LP Audit from lp_audit_cache ─────────────────

def _fetch_lp_playwright_audit(tenant_id: str) -> dict:
    """
    Read the most recent Playwright-based LP audit pushed from the
    LP Auditor web tool. Returns empty dict if none saved yet.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT site_url, score, grade, mobile_load_ms, desktop_load_ms,
                           ctas_above_fold, price_visible, page_height_px,
                           issues, competitor_summary, audited_at
                    FROM lp_audit_cache
                    WHERE tenant_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
        if not row:
            return {}
        age_hours = None
        try:
            from datetime import timezone as _tz
            audited = row[10]
            if audited:
                age_hours = round(
                    (datetime.now(timezone.utc) - audited.replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1
                )
        except Exception:
            pass
        return {
            "site_url": row[0],
            "score": int(row[1] or 0),
            "grade": row[2] or "D",
            "mobile_load_ms": row[3],
            "desktop_load_ms": row[4],
            "ctas_above_fold": int(row[5] or 0),
            "price_visible": bool(row[6]),
            "page_height_px": int(row[7] or 0),
            "issues": row[8] or [],
            "competitor_summary": row[9] or [],
            "age_hours": age_hours,
        }
    except Exception as e:
        print(f"sales_strategist: _fetch_lp_playwright_audit failed: {e}")
        return {}


# ── Campaign + adset data from Meta API ─────────────────────

def _fetch_campaign_insights(account_id: str, meta_token: str) -> list[dict]:
    """
    Fetch 7-day campaign-level performance from Meta API.
    Returns list sorted by spend desc.
    """
    try:
        import json as _json
        r = requests.get(
            f"{META_GRAPH}/{account_id}/insights",
            params={
                "level": "campaign",
                "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions,action_values",
                "date_preset": "last_7d",
                "filtering": _json.dumps([
                    {"field": "spend", "operator": "GREATER_THAN", "value": "0"}
                ]),
                "limit": 20,
                "access_token": meta_token,
            },
            timeout=30,
        )
        if not r.ok:
            print(f"sales_strategist: campaign insights API {r.status_code}: {r.text[:150]}")
            return []
        rows = r.json().get("data", [])
        purchase_types = {
            "purchase", "offsite_conversion.fb_pixel_purchase",
            "omni_purchase", "web_in_store_purchase",
        }
        result = []
        for row in rows:
            spend = float(row.get("spend", 0) or 0)
            purchases = sum(
                float(a.get("value", 0)) for a in (row.get("actions") or [])
                if a.get("action_type") in purchase_types
            )
            revenue = sum(
                float(a.get("value", 0)) for a in (row.get("action_values") or [])
                if a.get("action_type") in purchase_types
            )
            result.append({
                "campaign_id": row.get("campaign_id", ""),
                "campaign_name": (row.get("campaign_name") or "")[:60],
                "spend_7d": round(spend, 2),
                "revenue_7d": round(revenue, 2),
                "conversions_7d": round(purchases, 1),
                "clicks_7d": int(row.get("clicks", 0) or 0),
                "impressions_7d": int(row.get("impressions", 0) or 0),
                "roas": round(revenue / spend, 2) if spend > 0 else 0,
                "cpa": round(spend / purchases, 2) if purchases > 0 else None,
                "ctr": round(int(row.get("clicks", 0) or 0) / int(row.get("impressions", 1) or 1) * 100, 3),
            })
        result.sort(key=lambda x: x["spend_7d"], reverse=True)
        return result
    except Exception as e:
        print(f"sales_strategist: _fetch_campaign_insights failed: {e}")
        return []


def _fetch_adset_budgets(account_id: str, meta_token: str) -> list[dict]:
    """
    Fetch all active adsets with their current daily budgets.
    Budgets returned in INR (Meta stores in paise = 1/100 INR).
    """
    try:
        import json as _json
        r = requests.get(
            f"{META_GRAPH}/{account_id}/adsets",
            params={
                "fields": "id,name,campaign_id,daily_budget,lifetime_budget,status,effective_status,bid_strategy",
                "filtering": _json.dumps([
                    {"field": "effective_status", "operator": "IN",
                     "value": ["ACTIVE", "CAMPAIGN_PAUSED", "PAUSED"]}
                ]),
                "limit": 50,
                "access_token": meta_token,
            },
            timeout=30,
        )
        if not r.ok:
            print(f"sales_strategist: adset budgets API {r.status_code}: {r.text[:150]}")
            return []
        rows = r.json().get("data", [])
        result = []
        for row in rows:
            daily_paise = int(row.get("daily_budget", 0) or 0)
            lifetime_paise = int(row.get("lifetime_budget", 0) or 0)
            result.append({
                "adset_id": row.get("id", ""),
                "adset_name": (row.get("name") or "")[:60],
                "campaign_id": row.get("campaign_id", ""),
                "daily_budget_inr": daily_paise / 100 if daily_paise else None,
                "lifetime_budget_inr": lifetime_paise / 100 if lifetime_paise else None,
                "status": row.get("effective_status", row.get("status", "")),
                "bid_strategy": row.get("bid_strategy", ""),
            })
        result.sort(key=lambda x: (x["daily_budget_inr"] or 0), reverse=True)
        return result
    except Exception as e:
        print(f"sales_strategist: _fetch_adset_budgets failed: {e}")
        return []


# ── Funnel drop-off from Meta API ───────────────────────────

def _fetch_funnel_events(account_id: str, meta_token: str) -> dict:
    """
    Fetch 7-day account-level funnel events:
    ViewContent → AddToCart → InitiateCheckout → Purchase
    Returns counts + drop-off % at each step.
    """
    try:
        r = requests.get(
            f"{META_GRAPH}/{account_id}/insights",
            params={
                "level": "account",
                "fields": "actions",
                "date_preset": "last_7d",
                "access_token": meta_token,
            },
            timeout=30,
        )
        if not r.ok:
            print(f"sales_strategist: funnel events API {r.status_code}: {r.text[:150]}")
            return {}
        data = r.json().get("data", [])
        if not data:
            return {}

        funnel_keys = {
            "view_content":       "view_content",
            "add_to_cart":        "add_to_cart",
            "initiate_checkout":  "initiate_checkout",
            "purchase":           "purchase",
            "offsite_conversion.fb_pixel_view_content":      "view_content",
            "offsite_conversion.fb_pixel_add_to_cart":       "add_to_cart",
            "offsite_conversion.fb_pixel_initiate_checkout": "initiate_checkout",
            "offsite_conversion.fb_pixel_purchase":          "purchase",
        }
        counts = {"view_content": 0, "add_to_cart": 0, "initiate_checkout": 0, "purchase": 0}
        for row in data:
            for a in (row.get("actions") or []):
                mapped = funnel_keys.get(a.get("action_type", ""))
                if mapped:
                    counts[mapped] += float(a.get("value", 0) or 0)

        vc  = int(counts["view_content"])
        atc = int(counts["add_to_cart"])
        ic  = int(counts["initiate_checkout"])
        pur = int(counts["purchase"])

        def pct(num, denom):
            return round(num / denom * 100, 1) if denom > 0 else 0

        result = {
            "view_content":      vc,
            "add_to_cart":       atc,
            "initiate_checkout": ic,
            "purchase":          pur,
            "lp_to_cart_pct":        pct(atc, vc),
            "cart_to_checkout_pct":  pct(ic, atc),
            "checkout_to_purchase_pct": pct(pur, ic),
            "overall_cvr_pct":       pct(pur, vc),
        }
        # Identify primary bottleneck
        if vc == 0:
            result["bottleneck"] = "NO_LANDING — ViewContent not firing or zero LP visits tracked"
        elif atc == 0:
            result["bottleneck"] = f"LP_TO_CART — {vc} people saw LP, 0 added to cart (LP is killing intent)"
        elif ic == 0:
            result["bottleneck"] = f"CART_TO_CHECKOUT — {atc} added to cart, 0 initiated checkout (cart/price barrier)"
        elif pur == 0:
            result["bottleneck"] = f"CHECKOUT_ABANDONMENT — {ic} reached checkout, 0 purchased (payment/trust barrier)"
        else:
            result["bottleneck"] = f"PARTIAL_CONVERSION — {pct(pur, vc)}% overall CVR"

        print(f"sales_strategist: funnel — VC={vc}, ATC={atc}, IC={ic}, PUR={pur} | {result['bottleneck']}")
        return result
    except Exception as e:
        print(f"sales_strategist: _fetch_funnel_events failed: {e}")
        return {}


# ── Placement performance from Meta API ─────────────────────

def _fetch_placement_performance(account_id: str, meta_token: str) -> list[dict]:
    """
    Fetch 7-day spend/clicks/CTR broken down by publisher_platform.
    Flags Audience Network if CTR > 5% (bot/accidental click signal).
    """
    try:
        r = requests.get(
            f"{META_GRAPH}/{account_id}/insights",
            params={
                "level": "account",
                "fields": "spend,clicks,impressions,actions",
                "breakdowns": "publisher_platform",
                "date_preset": "last_7d",
                "access_token": meta_token,
            },
            timeout=30,
        )
        if not r.ok:
            print(f"sales_strategist: placement perf API {r.status_code}: {r.text[:150]}")
            return []
        rows = r.json().get("data", [])
        result = []
        purchase_types = {"purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase"}
        for row in rows:
            spend   = float(row.get("spend", 0) or 0)
            clicks  = int(row.get("clicks", 0) or 0)
            imp     = int(row.get("impressions", 0) or 0)
            conv    = sum(float(a.get("value", 0)) for a in (row.get("actions") or [])
                         if a.get("action_type") in purchase_types)
            ctr     = round(clicks / imp * 100, 2) if imp > 0 else 0
            platform = row.get("publisher_platform", "unknown")
            flagged = platform == "audience_network" and ctr > 5.0
            result.append({
                "platform":   platform,
                "spend":      round(spend, 2),
                "clicks":     clicks,
                "impressions": imp,
                "ctr_pct":    ctr,
                "conversions": int(conv),
                "cpa":        round(spend / conv, 2) if conv > 0 else None,
                "flagged_junk": flagged,
                "flag_reason": "CTR >5% on Audience Network = bot/accidental clicks" if flagged else "",
            })
        result.sort(key=lambda x: x["spend"], reverse=True)
        return result
    except Exception as e:
        print(f"sales_strategist: _fetch_placement_performance failed: {e}")
        return []


# ── Performance context from DB ─────────────────────────────

def _fetch_perf_context(platform: str, account_id: str) -> dict:
    """Pull 7-day KPIs, objections, LP audit, and weekly digest from DB."""
    now = datetime.now(timezone.utc)
    t7d = now - timedelta(days=7)
    ctx: dict = {}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # 7-day aggregated KPIs
                cur.execute(
                    """
                    SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                           COALESCE(SUM(conversions),0), COALESCE(SUM(clicks),0),
                           COALESCE(SUM(impressions),0)
                    FROM kpi_hourly
                    WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                    """,
                    (platform, account_id, t7d),
                )
                r = cur.fetchone()
                spend, rev, conv, clicks, imp = [float(x or 0) for x in r]
                ctx["last_7d"] = {
                    "spend": round(spend, 2),
                    "revenue": round(rev, 2),
                    "roas": round(rev / spend, 2) if spend > 0 else 0,
                    "conversions": int(conv),
                    "clicks": int(clicks),
                    "impressions": int(imp),
                    "ctr": round(clicks / imp, 4) if imp > 0 else 0,
                    "cpa": round(spend / conv, 2) if conv > 0 else None,
                }

                # Top objections
                cur.execute(
                    """
                    SELECT objection_type, SUM(count) as cnt
                    FROM fact_objections_daily
                    WHERE platform=%s AND account_id=%s
                      AND day >= CURRENT_DATE - INTERVAL '7 days'
                    GROUP BY objection_type ORDER BY cnt DESC LIMIT 5
                    """,
                    (platform, account_id),
                )
                ctx["top_objections"] = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

                # Latest LP audit
                cur.execute(
                    """
                    SELECT clarity_score, trust_score, friction_score, overall_score,
                           issues, recommendations
                    FROM landing_page_audits ORDER BY ts DESC LIMIT 1
                    """
                )
                lp = cur.fetchone()
                ctx["lp_audit"] = {
                    "clarity": float(lp[0] or 0), "trust": float(lp[1] or 0),
                    "friction": float(lp[2] or 0), "overall": float(lp[3] or 0),
                    "issues": lp[4], "recommendations": lp[5],
                } if lp else {}

                # Weekly digest
                cur.execute(
                    """
                    SELECT digest_text FROM mem_weekly_digest
                    WHERE platform=%s AND account_id=%s
                    ORDER BY week_start DESC LIMIT 1
                    """,
                    (platform, account_id),
                )
                row = cur.fetchone()
                ctx["weekly_digest"] = row[0][:600] if row else "No weekly digest yet."

                # 7-day comment analytics
                try:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE status='auto_replied') AS auto_replied,
                            COUNT(*) FILTER (WHERE status='pending') AS unanswered,
                            COUNT(*) FILTER (WHERE status='replied') AS human_replied
                        FROM comment_replies
                        WHERE platform=%s AND account_id=%s
                          AND first_seen_at >= NOW() - INTERVAL '7 days'
                        """,
                        (platform, account_id),
                    )
                    cr = cur.fetchone() or (0, 0, 0, 0)

                    cur.execute(
                        """
                        SELECT objection_type, COUNT(*) AS cnt
                        FROM comment_replies
                        WHERE platform=%s AND account_id=%s
                          AND first_seen_at >= NOW() - INTERVAL '7 days'
                        GROUP BY objection_type
                        ORDER BY cnt DESC
                        LIMIT 7
                        """,
                        (platform, account_id),
                    )
                    breakdown = {r[0]: int(r[1]) for r in cur.fetchall()}

                    cur.execute(
                        """
                        SELECT
                            cr.ad_id,
                            e.name AS ad_name,
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE cr.status='pending') AS pending,
                            COUNT(*) FILTER (WHERE cr.status='auto_replied') AS auto_replied,
                            COUNT(*) FILTER (WHERE cr.objection_type IN ('scam','trust')) AS negative
                        FROM comment_replies cr
                        LEFT JOIN entities_snapshot e
                            ON e.entity_id = cr.ad_id
                           AND e.entity_level = 'ad'
                           AND e.platform = cr.platform
                        WHERE cr.platform=%s AND cr.account_id=%s
                          AND cr.first_seen_at >= NOW() - INTERVAL '7 days'
                        GROUP BY cr.ad_id, e.name
                        ORDER BY total DESC
                        LIMIT 10
                        """,
                        (platform, account_id),
                    )
                    by_ad = [
                        {
                            "ad_id": (r[0] or "")[:15],
                            "ad_name": r[1] or "Unknown Ad",
                            "total": int(r[2] or 0),
                            "pending": int(r[3] or 0),
                            "auto_replied": int(r[4] or 0),
                            "negative_count": int(r[5] or 0),
                        }
                        for r in cur.fetchall()
                    ]

                    cur.execute(
                        """
                        SELECT objection_type, comment_text, commenter_name
                        FROM comment_replies
                        WHERE platform=%s AND account_id=%s
                          AND first_seen_at >= NOW() - INTERVAL '7 days'
                          AND comment_text IS NOT NULL AND comment_text != ''
                        ORDER BY first_seen_at DESC
                        LIMIT 30
                        """,
                        (platform, account_id),
                    )
                    comment_examples: dict = {}
                    for row in cur.fetchall():
                        t = row[0] or "other"
                        if t not in comment_examples:
                            comment_examples[t] = []
                        if len(comment_examples[t]) < 3:
                            comment_examples[t].append(
                                f"{row[2] or 'User'}: \"{(row[1] or '')[:70]}\""
                            )

                    ctx["comment_stats"] = {
                        "total_7d": int(cr[0] or 0),
                        "auto_replied": int(cr[1] or 0),
                        "unanswered": int(cr[2] or 0),
                        "human_replied": int(cr[3] or 0),
                        "unanswered_rate_pct": round(
                            int(cr[2] or 0) / int(cr[0] or 1) * 100, 1
                        ),
                        "breakdown_by_type": breakdown,
                        "by_ad": by_ad,
                        "examples_by_type": comment_examples,
                    }
                except Exception as e:
                    print(f"sales_strategist: comment stats failed: {e}")
                    ctx["comment_stats"] = {}

    except Exception as e:
        print(f"sales_strategist: perf context failed: {e}")
        ctx.setdefault("last_7d", {})
        ctx.setdefault("top_objections", {})
        ctx.setdefault("lp_audit", {})
        ctx.setdefault("weekly_digest", "")

    return ctx


# ── Claude Opus strategy generation ────────────────────────

def _generate_strategy(
    perf_ctx: dict,
    fb_data: dict,
    competitor_data: dict,
    lp_data: dict,
    tenant: dict,
    campaign_insights: list = None,
    adset_budgets: list = None,
    lp_playwright: dict = None,
    funnel_events: dict = None,
    placement_perf: list = None,
) -> dict:
    """
    Feed all data to Claude Opus — most powerful model — to get a complete
    diagnosis + prioritised action plan + competitive insights + forecast.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    product_ctx = (tenant or {}).get("product_context") or PRODUCT_CONTEXT

    # Prepare compact but complete data blobs
    fb_summary = fb_data.get("summary", "No FB deep data.")
    fb_age = json.dumps(fb_data.get("breakdowns", {}).get("age_gender", [])[:8], indent=2)
    fb_placement = json.dumps(fb_data.get("breakdowns", {}).get("placement", [])[:6], indent=2)
    fb_device = json.dumps(fb_data.get("breakdowns", {}).get("device", [])[:4], indent=2)
    fb_relevance = json.dumps(fb_data.get("relevance_diagnostics", [])[:8], indent=2)
    fb_frequency = json.dumps(fb_data.get("frequency", [])[:8], indent=2)

    comp_summary = competitor_data.get("summary", "No competitor data.")
    comp_top = json.dumps(competitor_data.get("top_competitors", [])[:4], indent=2)
    comp_gaps = json.dumps(competitor_data.get("opportunity_gaps", []), indent=2)
    gap_analysis = competitor_data.get("gap_analysis", {})
    where_we_lag = json.dumps(gap_analysis.get("where_we_lag", []), indent=2)
    top_priority_fix = gap_analysis.get("top_priority_fix", "")
    winning_angles = json.dumps(gap_analysis.get("winning_ad_angles", []), indent=2)

    lp_scores = json.dumps(lp_data.get("scores", {}))
    lp_promise = lp_data.get("promise_gap", "")
    lp_offer = lp_data.get("offer_analysis", "")
    lp_fixes = json.dumps(lp_data.get("critical_fixes", [])[:5])

    # Playwright LP audit — real browser data, most authoritative LP signal
    lp_pw = lp_playwright or {}
    lp_pw_score = lp_pw.get("score", None)
    lp_pw_section = ""
    if lp_pw:
        comp_scores = ""
        for c in (lp_pw.get("competitor_summary") or [])[:4]:
            comp_scores += f"\n  - {c.get('name','?')}: {c.get('score','?')}/100, load={c.get('load_ms','?')}ms, CTAs above fold={c.get('ctas_above_fold','?')}"
        age_note = f" (audited {lp_pw.get('age_hours','?')}h ago)" if lp_pw.get("age_hours") else ""
        lp_pw_section = f"""
=== REAL BROWSER LP AUDIT (Playwright{age_note}) ===
URL: {lp_pw.get('site_url', 'N/A')}
Funnel Score: {lp_pw_score}/100  Grade: {lp_pw.get('grade','?')}

Mobile load time: {lp_pw.get('mobile_load_ms','?')}ms  (target <3000ms — {'PASS' if (lp_pw.get('mobile_load_ms') or 9999) < 3000 else 'FAIL'})
Desktop load time: {lp_pw.get('desktop_load_ms','?')}ms
CTAs visible above fold (mobile): {lp_pw.get('ctas_above_fold', 0)}  ({'GOOD' if lp_pw.get('ctas_above_fold',0) >= 1 else 'CRITICAL — no buy button above fold'})
Price visible above fold: {'YES' if lp_pw.get('price_visible') else 'NO — users dont know cost before scrolling'}
Page height: {lp_pw.get('page_height_px','?')}px ({(lp_pw.get('page_height_px') or 0)//844} screens to scroll)

Issues found by browser audit:
{chr(10).join(f'  - {i}' for i in (lp_pw.get('issues') or []))}

Competitor LP scores vs ours:{comp_scores if comp_scores else ' No competitor data yet'}

INTERPRETATION:
{"CRITICAL: LP score is below 50. This landing page is likely the PRIMARY reason for low conversion. Even with perfect ads, poor LP will waste spend. Budget increases NOT recommended until LP is fixed." if (lp_pw_score or 100) < 50 else ""}
{"WARNING: LP score 50-70. LP has significant issues that are hurting conversion. Fix LP in parallel with ad optimisation." if 50 <= (lp_pw_score or 100) < 70 else ""}
{"LP score is healthy (70+). Conversion issues are more likely ad-side (targeting, creative, offer)." if (lp_pw_score or 100) >= 70 else ""}
"""
    else:
        lp_pw_section = "\n=== REAL BROWSER LP AUDIT ===\nNot yet available — run LP Auditor tool and click 'Save to Bot'\n"

    # Build campaign + adset sections
    camp_insights_str = json.dumps(campaign_insights or [], indent=2)
    adset_budgets_str = json.dumps(adset_budgets or [], indent=2)

    # Funnel drop-off section
    fn = funnel_events or {}
    if fn:
        vc  = fn.get("view_content", 0)
        atc = fn.get("add_to_cart", 0)
        ic  = fn.get("initiate_checkout", 0)
        pur = fn.get("purchase", 0)
        funnel_section = f"""
=== FUNNEL DROP-OFF ANALYSIS (7 days, Meta Pixel) ===
ViewContent (landed on LP):   {vc:,}
AddToCart (intent signal):    {atc:,}  ({fn.get('lp_to_cart_pct', 0)}% of viewers)
InitiateCheckout:             {ic:,}  ({fn.get('cart_to_checkout_pct', 0)}% of cart adds)
Purchase:                     {pur:,}  ({fn.get('checkout_to_purchase_pct', 0)}% of checkouts)
Overall CVR:                  {fn.get('overall_cvr_pct', 0)}%

PRIMARY BOTTLENECK: {fn.get('bottleneck', 'Unknown')}
"""
    else:
        funnel_section = "\n=== FUNNEL DROP-OFF ANALYSIS ===\nNot available — pixel events not returned by API.\n"

    # Placement performance section
    pl = placement_perf or []
    an_flagged = [p for p in pl if p.get("flagged_junk")]
    if pl:
        pl_rows = ""
        for p in pl:
            flag = " ⚠️ JUNK TRAFFIC" if p.get("flagged_junk") else ""
            pl_rows += (f"\n  {p['platform']:20s} | spend=₹{p['spend']:,.0f} | "
                        f"clicks={p['clicks']:,} | CTR={p['ctr_pct']}%{flag}")
        placement_section = f"""
=== PLACEMENT PERFORMANCE (7 days) ==={pl_rows}

{"⚠️ AUDIENCE NETWORK FLAG: CTR > 5% detected. This is a bot/accidental-click signal. Recommend exclude_placement action for all active adsets." if an_flagged else "Audience Network CTR within normal range."}
"""
    else:
        placement_section = "\n=== PLACEMENT PERFORMANCE ===\nNot available.\n"

    # Comment intelligence — examples and per-ad breakdown
    comment_stats = perf_ctx.get("comment_stats", {})
    comment_examples = comment_stats.get("examples_by_type", {})
    comment_by_ad = comment_stats.get("by_ad", [])
    comment_examples_str = ""
    for ctype, examples in comment_examples.items():
        comment_examples_str += f"\n  [{ctype.upper()}]: " + " | ".join(examples[:2])

    prompt = f"""You are the world's best Facebook Ads strategist for Indian D2C brands.
Your mission: diagnose WHY this business is at its current performance level and provide
a precise, data-backed, immediately executable action plan to grow sales.

You think like a data scientist + elite performance marketer. Be specific. Use the actual numbers.
Do NOT give generic advice — every recommendation must be traceable to a specific data point.

=== PRODUCT ===
{product_ctx[:600]}

=== 7-DAY AGGREGATE PERFORMANCE ===
{json.dumps(perf_ctx.get('last_7d', {}), indent=2)}

=== PER-CAMPAIGN 7-DAY PERFORMANCE (from Meta API) ===
{camp_insights_str}

=== ACTIVE ADSETS WITH CURRENT BUDGETS ===
{adset_budgets_str}
{funnel_section}
{placement_section}
=== COMMENT INTELLIGENCE DEEP DIVE (7 days) ===
Global stats: {json.dumps({k: v for k, v in comment_stats.items() if k not in ('by_ad', 'examples_by_type')}, indent=2)}

By ad (which ads attract most objections):
{json.dumps(comment_by_ad, indent=2)}

Real customer comment examples by type:{comment_examples_str}

Key insight: unanswered comments = missed conversion opportunities. High price/trust/scam = creative messaging gap.

=== TOP CUSTOMER OBJECTIONS (fact_objections_daily, 7d) ===
{json.dumps(perf_ctx.get('top_objections', {}), indent=2)}

=== LANDING PAGE DEEP AUDIT ===
Scores: {lp_scores}
Promise gap: {lp_promise}
Offer analysis: {lp_offer}
Critical fixes: {lp_fixes}
{lp_pw_section}
=== FACEBOOK DEEP ANALYSIS ===
{fb_summary}

Age/Gender (top segments by spend):
{fb_age}

Placement breakdown:
{fb_placement}

Device breakdown:
{fb_device}

Ad Relevance Diagnostics:
{fb_relevance}

Frequency/Audience Saturation:
{fb_frequency}

=== COMPETITOR INTELLIGENCE ===
{comp_summary}

Top competitors:
{comp_top}

Where WE are lagging vs competitors (RIGHT NOW based on current metrics):
{where_we_lag}

Competitor winning ad angles we should test:
{winning_angles}

Top priority fix identified:
{top_priority_fix}

Opportunity gaps competitors are missing:
{comp_gaps}

=== HISTORICAL CONTEXT ===
{perf_ctx.get('weekly_digest', '')}

=== YOUR TASK ===
Think step-by-step:
1. What is the PRIMARY root cause of current performance? (be specific, cite data)
2. What quick wins can be executed TODAY?
3. What strategic changes will compound over 2-4 weeks?
4. For EVERY campaign: diagnose its health, recommend budget increase/decrease/pause with exact numbers.

BUDGET DECISION RULES (per campaign/adset):
- ROAS ≥ target × 1.5 AND frequency < 2.5 → recommend increase 20-30%
- ROAS ≥ target AND frequency < 3 → recommend increase 10-15%
- ROAS 0.8×–1×  target → maintain, watch
- ROAS < 0.8× target OR quality_ranking BELOW_AVERAGE on 2+ metrics → recommend decrease 20-30% or pause
- LP OVERRIDE: If Playwright LP audit score < 50 → cap ALL budget increases at +10% max regardless of ROAS. Mark fix_lp as priority 1 action. Poor LP = ads waste spend on non-converting traffic.
- AUDIENCE NETWORK OVERRIDE: If Audience Network CTR > 5% → recommend exclude_placement (tier=approval, NOT auto) for all active adsets. Include adset_ids list in data. Junk traffic inflates click counts and wastes budget.
- FUNNEL BOTTLENECK: Identify the exact funnel step where drop-off occurs. If ViewContent=0 → pixel/LP issue. If AddToCart=0 → LP intent issue. If InitiateCheckout=0 → cart/price barrier. If Purchase=0 but IC>0 → payment/trust barrier. Each bottleneck maps to a specific fix action.
- All budget recommendations require "approval" tier (not auto, not strategic — human must confirm each)

ACTION TIERS (use exactly these):
- "auto": safe to execute without human approval
  → pause ads: only if quality_ranking=BELOW_AVERAGE on 2+ metrics AND spend wasted
- "approval": valuable but needs human sign-off
  → ALL budget increases or decreases (scale_budget)
  → new creatives, audience changes, offer tests
- "strategic": human must decide (LP changes, restructure, offer overhaul)

VALID action_types: pause_ad, scale_budget, new_creative, new_audience, fix_lp, test_offer, restructure, exclude_placement

For exclude_placement: data must include "adset_ids" (list of all active adset IDs to patch) and "platform_to_exclude" = "audience_network".

For pause_ad: include exact ad_id and ad_name from relevance diagnostics above.
For scale_budget: include exact adset_id, adset_name, current_daily_budget_inr, new_daily_budget_inr, scale_pct.
For new_creative: write complete specific creative brief (angle, hook idea, key message, format).

Return ONLY valid JSON — no markdown, no explanation:
{{
  "diagnosis": {{
    "primary_root_cause": "Specific 2-3 sentence diagnosis citing actual data points",
    "confidence": "high|medium|low",
    "evidence": ["data point 1 with numbers", "data point 2 with numbers"],
    "severity": "critical|high|medium|low"
  }},
  "campaign_analysis": [
    {{
      "campaign_id": "meta campaign id",
      "campaign_name": "name",
      "spend_7d": 0,
      "roas": 0,
      "conversions_7d": 0,
      "adset_id": "best matching adset_id from adset_budgets list",
      "adset_name": "name",
      "current_daily_budget_inr": 0,
      "recommendation": "increase_budget|decrease_budget|pause|maintain",
      "proposed_daily_budget_inr": 0,
      "change_pct": 0,
      "diagnosis": "1-2 sentence diagnosis for this specific campaign citing its data",
      "rationale": "Why this budget decision, citing ROAS vs target, frequency, relevance score"
    }}
  ],
  "action_plan": [
    {{
      "tier": "auto|approval|strategic",
      "priority": 1,
      "action_type": "pause_ad|scale_budget|new_creative|new_audience|fix_lp|test_offer|restructure",
      "title": "Short title max 60 chars",
      "description": "What to do + exactly why, citing specific data (2-3 sentences)",
      "data": {{
        "ad_id": "only for pause_ad",
        "ad_name": "only for pause_ad",
        "adset_id": "only for scale_budget",
        "adset_name": "only for scale_budget",
        "current_daily_budget_inr": 0,
        "new_daily_budget_inr": 0,
        "scale_pct": 0,
        "creative_brief": "only for new_creative — full brief",
        "angle": "only for new_creative",
        "audience_spec": "only for new_audience",
        "fix_detail": "only for fix_lp or test_offer"
      }},
      "estimated_revenue_impact": "specific projection e.g. +₹X/week or +X% ROAS"
    }}
  ],
  "comment_intelligence_summary": "2-3 sentences on what comments reveal about customer mindset and creative gaps",
  "competitive_insights": "3-4 sentences on what competitors are doing and our advantages",
  "forecast": "If top 3 actions done within 7 days: [specific ROAS/revenue projection]",
  "whatsapp_summary": "5-7 lines, emojis OK, max 600 chars — key diagnosis + top 3 actions + budget decisions + forecast"
}}"""

    try:
        resp = client.messages.create(
            model="claude-opus-4-6",  # Most capable — strategy generation warrants Opus
            max_tokens=8096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip code fences if present
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if m:
                raw = m.group(1).strip()
        # Try full JSON first
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            candidate = m.group()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Response may be truncated — repair by closing open braces/brackets
                open_braces = candidate.count("{") - candidate.count("}")
                open_brackets = candidate.count("[") - candidate.count("]")
                repaired = candidate.rstrip().rstrip(",")
                repaired += "]" * max(0, open_brackets)
                repaired += "}" * max(0, open_braces)
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError as inner_e:
                    print(f"sales_strategist: JSON repair failed: {inner_e}")
        return json.loads(raw)
    except Exception as e:
        print(f"sales_strategist: strategy generation failed: {e}")
        import traceback; traceback.print_exc()
        return {
            "diagnosis": {"primary_root_cause": "Strategy generation failed — check logs.", "confidence": "low", "evidence": [], "severity": "low"},
            "action_plan": [],
            "competitive_insights": "",
            "forecast": "",
            "whatsapp_summary": "⚠️ Strategy analysis failed. Check agent-swarm logs.",
        }


# ── Auto-execute safe actions ───────────────────────────────

def _execute_auto_action(action: dict, meta_token: str) -> tuple[bool, str]:
    """Execute a tier='auto' action immediately via Meta API."""
    action_type = action.get("action_type", "")
    data = action.get("data", {})

    if action_type == "pause_ad":
        ad_id = data.get("ad_id")
        if not ad_id:
            return False, "No ad_id in action data"
        try:
            r = requests.post(
                f"{META_GRAPH}/{ad_id}",
                data={"status": "PAUSED", "access_token": meta_token},
                timeout=20,
            )
            if r.ok and not r.json().get("error"):
                return True, f"Paused ad {ad_id} ({data.get('ad_name', '')})"
            return False, f"Meta API: {r.text[:150]}"
        except Exception as e:
            return False, str(e)

    elif action_type == "scale_budget":
        adset_id = data.get("adset_id")
        new_budget_inr = data.get("new_daily_budget_inr")
        if not adset_id or not new_budget_inr:
            return False, "Missing adset_id or new_daily_budget_inr"
        # Safety cap: never scale more than 20% via auto-execution
        scale_pct = float(data.get("scale_pct", 0))
        if scale_pct > 20:
            return False, f"Auto-execution cap exceeded: {scale_pct}% > 20%"
        new_budget_paise = int(float(new_budget_inr) * 100)  # Meta uses currency subunits
        try:
            r = requests.post(
                f"{META_GRAPH}/{adset_id}",
                data={"daily_budget": new_budget_paise, "access_token": meta_token},
                timeout=20,
            )
            if r.ok and not r.json().get("error"):
                return True, f"Scaled {data.get('adset_name', adset_id)} to ₹{new_budget_inr}/day"
            return False, f"Meta API: {r.text[:150]}"
        except Exception as e:
            return False, str(e)

    elif action_type == "exclude_placement":
        # Same logic as approval tier — reuse by calling approved-action handler
        # Build a minimal tenant dict for the call
        data = action.get("data", {})
        adset_ids = data.get("adset_ids", [])
        platform  = data.get("platform_to_exclude", "audience_network")
        if not adset_ids:
            return False, "No adset_ids provided for exclude_placement"
        results_list = []
        for adset_id in adset_ids:
            try:
                r = requests.get(
                    f"{META_GRAPH}/{adset_id}",
                    params={"fields": "targeting", "access_token": meta_token},
                    timeout=20,
                )
                targeting = r.json().get("targeting", {})
                platforms = targeting.get("publisher_platforms",
                    ["facebook", "instagram", "audience_network", "messenger"])
                if platform not in platforms:
                    results_list.append(f"{adset_id}: already excluded")
                    continue
                platforms = [p for p in platforms if p != platform]
                targeting["publisher_platforms"] = platforms
                targeting.pop("audience_network_positions", None)
                r2 = requests.post(
                    f"{META_GRAPH}/{adset_id}",
                    data={"targeting": json.dumps(targeting), "access_token": meta_token},
                    timeout=20,
                )
                if r2.ok and not r2.json().get("error"):
                    results_list.append(f"{adset_id}: ok")
                else:
                    results_list.append(f"{adset_id}: failed — {r2.text[:80]}")
            except Exception as e:
                results_list.append(f"{adset_id}: error — {str(e)[:60]}")
        success = sum(1 for x in results_list if "ok" in x or "already" in x)
        return success > 0, f"Excluded {platform} from {success}/{len(adset_ids)} adsets"

    return False, f"No auto-executor for action_type '{action_type}'"


def _execute_approved_action(
    action: dict,
    tenant: dict,
    platform: str,
    account_id: str,
) -> tuple[bool, str]:
    """Execute an approval-tier action that the user just approved."""
    action_type = action.get("action_type", "")
    data = action.get("data", {})

    if action_type == "new_creative":
        brief = data.get("creative_brief") or action.get("description", "")
        angle = data.get("angle", "")
        trigger = f"STRATEGY: {action.get('title', '')}. {brief}"
        try:
            from services.agent_swarm.agents.creative_generator import run_creative_generator
            result = run_creative_generator(
                platform, account_id,
                trigger_reason=trigger,
                tenant=tenant,
            )
            n = result.get("concepts_generated", 0)
            return result.get("ok", False), f"Generated {n} creative concept(s)"
        except Exception as e:
            return False, str(e)

    elif action_type == "pause_ad":
        meta_token = (tenant or {}).get("meta_access_token") or META_ADS_TOKEN
        return _execute_auto_action(action, meta_token)

    elif action_type == "scale_budget":
        # User explicitly approved — execute without the 20% auto-execution cap
        meta_token = (tenant or {}).get("meta_access_token") or META_ADS_TOKEN
        adset_id = data.get("adset_id")
        new_budget_inr = data.get("new_daily_budget_inr")
        if not adset_id or not new_budget_inr:
            return False, "Missing adset_id or new_daily_budget_inr in action data"
        new_budget_paise = int(float(new_budget_inr) * 100)
        try:
            r = requests.post(
                f"{META_GRAPH}/{adset_id}",
                data={"daily_budget": new_budget_paise, "access_token": meta_token},
                timeout=20,
            )
            if r.ok and not r.json().get("error"):
                curr = data.get("current_daily_budget_inr", "?")
                pct = data.get("scale_pct", 0)
                return True, f"Budget updated: ₹{curr} → ₹{new_budget_inr}/day ({float(pct):+.0f}%)"
            return False, f"Meta API error: {r.text[:150]}"
        except Exception as e:
            return False, str(e)

    elif action_type == "exclude_placement":
        meta_token = (tenant or {}).get("meta_access_token") or META_ADS_TOKEN
        adset_ids = data.get("adset_ids", [])
        platform  = data.get("platform_to_exclude", "audience_network")
        if not adset_ids:
            return False, "No adset_ids provided for exclude_placement"
        results = []
        for adset_id in adset_ids:
            try:
                # Fetch current targeting
                r = requests.get(
                    f"{META_GRAPH}/{adset_id}",
                    params={"fields": "targeting", "access_token": meta_token},
                    timeout=20,
                )
                targeting = r.json().get("targeting", {})
                platforms = targeting.get("publisher_platforms",
                    ["facebook", "instagram", "audience_network", "messenger"])
                if platform not in platforms:
                    results.append(f"{adset_id}: already excluded")
                    continue
                platforms = [p for p in platforms if p != platform]
                targeting["publisher_platforms"] = platforms
                targeting.pop("audience_network_positions", None)
                r2 = requests.post(
                    f"{META_GRAPH}/{adset_id}",
                    data={"targeting": json.dumps(targeting), "access_token": meta_token},
                    timeout=20,
                )
                if r2.ok and not r2.json().get("error"):
                    results.append(f"{adset_id}: excluded {platform}")
                else:
                    results.append(f"{adset_id}: failed — {r2.text[:80]}")
            except Exception as e:
                results.append(f"{adset_id}: error — {str(e)[:60]}")
        success_count = sum(1 for r in results if "excluded" in r)
        return success_count > 0, f"Excluded {platform} from {success_count}/{len(adset_ids)} adsets"

    # For fix_lp, new_audience, restructure, test_offer — log as noted
    return True, "Recommendation noted and logged"


# ── DB persistence ──────────────────────────────────────────

def _save_strategy(
    tenant_id: str, platform: str, account_id: str,
    strategy: dict,
    fb_data: dict, competitor_data: dict, lp_data: dict,
) -> str:
    """Insert strategy into DB, return strategy UUID."""
    strategy_id = str(uuid.uuid4())
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                diag = strategy.get("diagnosis", {})
                cur.execute(
                    """
                    INSERT INTO sales_strategies
                      (id, tenant_id, platform, account_id,
                       diagnosis, competitive_insights, forecast, whatsapp_summary,
                       raw_fb_data, raw_competitor, raw_lp_data)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        strategy_id, tenant_id, platform, account_id,
                        json.dumps(diag),
                        strategy.get("competitive_insights", ""),
                        strategy.get("forecast", ""),
                        strategy.get("whatsapp_summary", ""),
                        json.dumps(fb_data),
                        json.dumps(competitor_data),
                        json.dumps(lp_data),
                    ),
                )
    except Exception as e:
        print(f"sales_strategist: save_strategy failed: {e}")
    return strategy_id


def _save_actions(
    strategy_id: str,
    tenant_id: str,
    action_plan: list,
) -> list[dict]:
    """Insert action items, return list with generated UUIDs."""
    saved = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for i, action in enumerate(action_plan):
                    action_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO strategy_actions
                          (id, strategy_id, tenant_id, tier, priority,
                           action_type, title, description, data)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            action_id, strategy_id, tenant_id,
                            action.get("tier", "strategic"),
                            action.get("priority", i + 1),
                            action.get("action_type", ""),
                            action.get("title", "")[:200],
                            action.get("description", ""),
                            json.dumps(action.get("data", {})),
                        ),
                    )
                    saved.append({**action, "id": action_id})
    except Exception as e:
        print(f"sales_strategist: save_actions failed: {e}")
    return saved


def _mark_action_status(action_id: str, status: str, result_msg: str = "") -> None:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE strategy_actions
                    SET status=%s, execute_result=%s, updated_at=NOW()
                    WHERE id=%s
                    """,
                    (status, result_msg[:500], action_id),
                )
    except Exception as e:
        print(f"sales_strategist: mark_action_status failed: {e}")


# ── WhatsApp delivery ───────────────────────────────────────

def _send_strategy_report(strategy: dict, actions: list[dict], wa_num: str, tenant: dict = None, lp_playwright: dict = None) -> None:
    """Send the full strategy report to WhatsApp in chunks."""
    diag = strategy.get("diagnosis", {})

    # Message 1: Summary + diagnosis
    summary = strategy.get("whatsapp_summary", "")
    root_cause = diag.get("primary_root_cause", "")
    evidence = "\n".join(f"  • {e}" for e in diag.get("evidence", []))
    severity = diag.get("severity", "").upper()

    msg1 = (
        f"🧠 *SALES INTELLIGENCE REPORT*\n"
        f"_{datetime.now().strftime('%d %b %Y, %I:%M %p')}_\n\n"
        f"📊 *SUMMARY*\n{summary}\n\n"
        f"🔍 *ROOT CAUSE* [{severity}]\n{root_cause}\n"
    )
    if evidence:
        msg1 += f"\nEvidence:\n{evidence}"
    send_text(wa_num, msg1, tenant)

    # Message 2: Campaign breakdown (per-campaign diagnosis + budget recommendations)
    campaign_analysis = strategy.get("campaign_analysis", [])
    if campaign_analysis:
        lines = [f"📊 *CAMPAIGN BREAKDOWN ({len(campaign_analysis)} campaigns, 7 days)*\n"]
        for i, c in enumerate(campaign_analysis[:6], 1):
            name = (c.get("campaign_name") or "Campaign")[:35]
            spend = c.get("spend_7d", 0)
            roas = c.get("roas", 0)
            conv = c.get("conversions_7d", 0)
            curr_budget = c.get("current_daily_budget_inr")
            proposed = c.get("proposed_daily_budget_inr")
            rec = c.get("recommendation", "maintain").replace("_", " ").upper()
            change_pct = c.get("change_pct", 0)
            rationale = (c.get("rationale") or c.get("diagnosis") or "")[:100]

            # Budget change line
            if curr_budget and proposed and abs(float(proposed) - float(curr_budget)) > 1:
                direction = "↑" if float(proposed) > float(curr_budget) else "↓"
                budget_line = f"Budget: ₹{curr_budget:,.0f}/day {direction} ₹{proposed:,.0f}/day ({change_pct:+.0f}%)"
            elif curr_budget:
                budget_line = f"Budget: ₹{curr_budget:,.0f}/day ({rec})"
            else:
                budget_line = f"Recommendation: {rec}"

            lines.append(
                f"*{i}. {name}*\n"
                f"Spend: ₹{spend:,.0f} | ROAS: {roas}x | Conv: {conv:.0f}\n"
                f"{budget_line}\n"
                f"_{rationale}_\n"
            )

        # Add comment-intelligence summary
        ci_summary = strategy.get("comment_intelligence_summary", "")
        if ci_summary:
            lines.append(f"\n💬 *Comment Intel:*\n_{ci_summary}_")

        send_text(wa_num, "\n".join(lines), tenant)

    # Message 3: Auto-executed actions
    auto_actions = [a for a in actions if a.get("tier") == "auto"]
    if auto_actions:
        lines = ["⚡ *AUTO-EXECUTED NOW*"]
        for a in auto_actions:
            status = a.get("_exec_status", "pending")
            icon = "✅" if status == "executed" else "❌"
            lines.append(f"{icon} {a.get('title', '')} — {a.get('_exec_result', '')}")
        send_text(wa_num, "\n".join(lines), tenant)

    # Message 4: Approval-needed actions — numbered for easy approval
    approval_actions = [a for a in actions if a.get("tier") == "approval"]
    if approval_actions:
        lines = [f"⏳ *{len(approval_actions)} ACTION(S) NEED YOUR APPROVAL*\n"]
        for a in approval_actions:
            num = a.get("priority", "?")
            data = a.get("data", {}) or {}
            # For scale_budget: show current → proposed budget clearly
            budget_detail = ""
            if a.get("action_type") == "scale_budget":
                curr = data.get("current_daily_budget_inr")
                proposed_b = data.get("new_daily_budget_inr")
                scale_pct = data.get("scale_pct", 0)
                adset = data.get("adset_name", "")
                if curr and proposed_b:
                    direction = "↑" if float(scale_pct or 0) > 0 else "↓"
                    budget_detail = (
                        f"\n💰 ₹{curr:,.0f} → ₹{proposed_b:,.0f}/day "
                        f"({float(scale_pct):+.0f}%)"
                    )
                    if adset:
                        budget_detail += f"\n   {adset}"

            lines.append(
                f"*#{num} — {a.get('title', '')}*\n"
                f"_{a.get('description', '')[:150]}_"
                f"{budget_detail}\n"
                f"✅ approve {num}   ❌ reject {num}\n"
            )
        lines.append("_To approve multiple: approve 5 6 7 8_\n_To approve all: approve all_")
        send_text(wa_num, "\n".join(lines), tenant)

    # Message 5: Strategic recommendations
    strategic_actions = [a for a in actions if a.get("tier") == "strategic"]
    if strategic_actions:
        lines = ["📋 *STRATEGIC RECOMMENDATIONS*"]
        for i, a in enumerate(strategic_actions, 1):
            lines.append(f"\n{i}. *{a.get('title', '')}*\n{a.get('description', '')[:200]}")
        send_text(wa_num, "\n".join(lines), tenant)

    # Message 6: LP health (real browser audit)
    lp_pw = lp_playwright or {}
    if lp_pw:
        score = lp_pw.get("score", 0)
        grade = lp_pw.get("grade", "?")
        mobile_ms = lp_pw.get("mobile_load_ms", "?")
        ctas = lp_pw.get("ctas_above_fold", 0)
        price_vis = "YES" if lp_pw.get("price_visible") else "NO"
        age_h = lp_pw.get("age_hours")
        age_note = f" (audited {age_h}h ago)" if age_h else ""
        issues = lp_pw.get("issues") or []
        issue_lines = "\n".join(f"  • {i}" for i in issues[:5])

        if score < 50:
            health_icon = "🔴"
            health_label = "CRITICAL — LP is hurting conversion"
        elif score < 70:
            health_icon = "🟡"
            health_label = "WARNING — LP needs fixes"
        else:
            health_icon = "🟢"
            health_label = "Healthy"

        lp_msg = (
            f"🖥️ *LANDING PAGE HEALTH{age_note}*\n"
            f"{health_icon} Score: {score}/100 (Grade {grade}) — {health_label}\n"
            f"Mobile load: {mobile_ms}ms | CTAs above fold: {ctas} | Price visible: {price_vis}\n"
        )
        if issue_lines:
            lp_msg += f"\nTop issues:\n{issue_lines}"
        if score < 50:
            lp_msg += "\n\n⚠️ *Budget increases capped at +10% until LP is fixed.*"
        send_text(wa_num, lp_msg.strip(), tenant)

    # Message 7: Competitive insights + forecast
    comp = strategy.get("competitive_insights", "")
    forecast = strategy.get("forecast", "")
    if comp or forecast:
        msg7 = ""
        if comp:
            msg7 += f"🕵️ *COMPETITOR INTEL*\n{comp}\n\n"
        if forecast:
            msg7 += f"📈 *FORECAST*\n{forecast}"
        send_text(wa_num, msg7.strip(), tenant)


def _send_approval_action(action: dict, wa_num: str, tenant: dict = None) -> None:
    """Send a single approval-needed action as a WhatsApp message."""
    short_id = action["id"][:8]
    data = action.get("data", {}) or {}

    # For scale_budget: clearly show current → proposed
    budget_detail = ""
    if action.get("action_type") == "scale_budget":
        curr = data.get("current_daily_budget_inr")
        proposed = data.get("new_daily_budget_inr")
        scale_pct = data.get("scale_pct", 0)
        adset = data.get("adset_name", "")
        if curr and proposed:
            direction = "increase" if float(scale_pct or 0) > 0 else "decrease"
            budget_detail = (
                f"\n\n💰 Budget {direction}: ₹{curr:,.0f}/day → ₹{proposed:,.0f}/day "
                f"({float(scale_pct):+.0f}%)"
            )
            if adset:
                budget_detail += f"\nAdset: _{adset}_"

    msg = (
        f"⚠️ *STRATEGY ACTION — APPROVAL NEEDED*\n\n"
        f"*{action.get('title', '')}*\n\n"
        f"{action.get('description', '')}"
        f"{budget_detail}\n\n"
        f"Estimated impact: {action.get('estimated_revenue_impact', 'unknown')}\n\n"
        f"✅ `approve strategy {short_id}`\n"
        f"❌ `reject strategy {short_id}`"
    )
    send_text(wa_num, msg, tenant)


# ── Public: handle approval/rejection from WhatsApp ────────

def handle_strategy_approval(
    action_id_short: str,
    approved: bool,
    tenant: dict,
    platform: str,
    account_id: str,
) -> dict:
    """
    Called from main.py when user replies 'approve strategy XXXXXXXX'
    or 'reject strategy XXXXXXXX'.
    """
    wa_num = (tenant or {}).get("admin_wa_id") or WA_REPORT_NUMBER
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID

    # Find the action by short ID
    action_row = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, action_type, title, description, data, status
                    FROM strategy_actions
                    WHERE tenant_id=%s AND LEFT(id::TEXT, 8)=%s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (tenant_id, action_id_short[:8]),
                )
                row = cur.fetchone()
        if row:
            action_row = {
                "id": str(row[0]), "action_type": row[1],
                "title": row[2], "description": row[3],
                "data": row[4] or {}, "status": row[5],
            }
    except Exception as e:
        print(f"handle_strategy_approval: DB lookup failed: {e}")
        return {"ok": False, "error": str(e)}

    if not action_row:
        send_text(wa_num, f"⚠️ Strategy action `{action_id_short}` not found.", tenant)
        return {"ok": False, "error": "Action not found"}

    if action_row["status"] not in ("pending",):
        send_text(wa_num, f"Action `{action_id_short}` is already {action_row['status']}.", tenant)
        return {"ok": False, "error": f"Already {action_row['status']}"}

    if not approved:
        _mark_action_status(action_row["id"], "rejected", "User rejected")
        send_text(wa_num, f"❌ Action rejected: *{action_row['title']}*", tenant)
        return {"ok": True, "status": "rejected"}

    # Execute the approved action
    _mark_action_status(action_row["id"], "approved")
    success, result_msg = _execute_approved_action(action_row, tenant, platform, account_id)
    final_status = "executed" if success else "failed"
    _mark_action_status(action_row["id"], final_status, result_msg)

    icon = "✅" if success else "⚠️"
    send_text(
        wa_num,
        f"{icon} *{action_row['title']}*\n{result_msg}",
        tenant,
    )
    return {"ok": True, "status": final_status, "result": result_msg}


def handle_strategy_approval_by_numbers(
    numbers: list[int],
    approved: bool,
    tenant: dict,
    platform: str,
    account_id: str,
) -> dict:
    """
    Approve/reject strategy actions by their priority numbers (e.g. approve 5 6 7).
    Looks up the latest strategy for the tenant and finds actions with matching priorities.
    """
    wa_num = (tenant or {}).get("admin_wa_id") or WA_REPORT_NUMBER
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID

    # Fetch matching pending approval actions from latest strategy
    rows = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sa.id, sa.priority
                    FROM strategy_actions sa
                    JOIN sales_strategies ss ON ss.id = sa.strategy_id
                    WHERE sa.tenant_id = %s
                      AND sa.tier = 'approval'
                      AND sa.status = 'pending'
                      AND sa.priority = ANY(%s)
                    ORDER BY ss.created_at DESC, sa.priority ASC
                    """,
                    (tenant_id, numbers),
                )
                rows = [(str(r[0]), r[1]) for r in cur.fetchall()]
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not rows:
        send_text(wa_num, f"⚠️ No pending approval actions found for #{', #'.join(str(n) for n in numbers)}.", tenant)
        return {"ok": False, "error": "Actions not found"}

    results = []
    for action_id, priority in rows:
        res = handle_strategy_approval(
            action_id[:8], approved, tenant, platform, account_id
        )
        results.append({"priority": priority, **res})

    return {"ok": True, "processed": len(results), "results": results}


# ── Main entry point ────────────────────────────────────────

def run_sales_strategy(
    platform: str,
    account_id: str,
    tenant: dict = None,
) -> dict:
    """
    Full sales intelligence pipeline. Designed to run every 6 hours.
    Returns strategy dict with action summary.
    """
    meta_token = (tenant or {}).get("meta_access_token") or META_ADS_TOKEN
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID
    wa_num = (tenant or {}).get("admin_wa_id") or WA_REPORT_NUMBER

    print(f"sales_strategist: starting for tenant={tenant_id}, account={account_id}")
    send_text(wa_num, "🧠 *Sales Intelligence Analysis starting...*\n_Pulling deep Facebook data, competitor intel, and LP audit. Report in ~2 minutes._", tenant)

    # ── Step 1: Pull performance context first (needed by competitor monitor) ─
    perf_ctx: dict = {}
    try:
        perf_ctx = _fetch_perf_context(platform, account_id)
    except Exception as e:
        print(f"sales_strategist: perf context failed: {e}")

    # ── Step 2: Run all three intelligence agents ─────────────
    fb_data: dict = {"ok": False, "breakdowns": {}, "relevance_diagnostics": [], "frequency": [], "summary": ""}
    try:
        print("sales_strategist: running FB deep analysis...")
        fb_data = run_fb_deep_analysis(platform, account_id, tenant)
    except Exception as e:
        print(f"sales_strategist: fb_analyst failed: {e}")

    competitor_data: dict = {"ok": False, "top_competitors": [], "opportunity_gaps": [], "summary": "", "gap_analysis": {}}
    try:
        print("sales_strategist: running competitor monitor...")
        competitor_data = run_competitor_monitor(tenant, current_performance=perf_ctx)
    except Exception as e:
        print(f"sales_strategist: competitor_monitor failed: {e}")

    lp_data: dict = {"ok": False, "scores": {}, "critical_fixes": []}
    try:
        print("sales_strategist: running LP analyst...")
        comp_summary = competitor_data.get("summary", "")
        lp_data = run_lp_analyst(tenant=tenant, competitor_summary=comp_summary)
    except Exception as e:
        print(f"sales_strategist: lp_analyst failed: {e}")

    # ── Step 2b: Fetch LP Playwright audit from DB ────────────
    lp_playwright: dict = {}
    try:
        print("sales_strategist: fetching LP playwright audit...")
        lp_playwright = _fetch_lp_playwright_audit(tenant_id)
        if lp_playwright:
            age = lp_playwright.get("age_hours", "?")
            score = lp_playwright.get("score", "?")
            print(f"sales_strategist: LP playwright audit — score={score}/100, age={age}h")
        else:
            print("sales_strategist: no LP playwright audit in DB yet — run LP Auditor tool first")
    except Exception as e:
        print(f"sales_strategist: LP playwright audit fetch failed: {e}")

    # ── Step 3: Fetch campaign insights, adset budgets, funnel + placement ──
    meta_acct = account_id if account_id.startswith("act_") else f"act_{account_id}"
    campaign_insights: list = []
    adset_budgets: list = []
    funnel_events: dict = {}
    placement_perf: list = []
    try:
        print("sales_strategist: fetching campaign insights...")
        campaign_insights = _fetch_campaign_insights(meta_acct, meta_token)
        print(f"sales_strategist: {len(campaign_insights)} campaigns")
    except Exception as e:
        print(f"sales_strategist: campaign insights failed: {e}")
    try:
        print("sales_strategist: fetching adset budgets...")
        adset_budgets = _fetch_adset_budgets(meta_acct, meta_token)
        print(f"sales_strategist: {len(adset_budgets)} adsets")
    except Exception as e:
        print(f"sales_strategist: adset budgets failed: {e}")
    try:
        print("sales_strategist: fetching funnel events...")
        funnel_events = _fetch_funnel_events(meta_acct, meta_token)
    except Exception as e:
        print(f"sales_strategist: funnel events failed: {e}")
    try:
        print("sales_strategist: fetching placement performance...")
        placement_perf = _fetch_placement_performance(meta_acct, meta_token)
    except Exception as e:
        print(f"sales_strategist: placement perf failed: {e}")

    # ── Step 4: Generate strategy with Claude Opus ────────────
    print("sales_strategist: generating strategy with Claude Opus...")
    strategy = _generate_strategy(
        perf_ctx, fb_data, competitor_data, lp_data, tenant,
        campaign_insights=campaign_insights,
        adset_budgets=adset_budgets,
        lp_playwright=lp_playwright,
        funnel_events=funnel_events,
        placement_perf=placement_perf,
    )

    # ── Step 5: Save strategy + actions ──────────────────────
    action_plan = strategy.get("action_plan", [])
    strategy_id = _save_strategy(tenant_id, platform, account_id, strategy, fb_data, competitor_data, lp_data)
    saved_actions = _save_actions(strategy_id, tenant_id, action_plan)

    # ── Step 6: Execute auto-tier actions ─────────────────────
    auto_results = []
    for action in saved_actions:
        if action.get("tier") != "auto":
            continue
        success, result_msg = _execute_auto_action(action, meta_token)
        status = "executed" if success else "failed"
        _mark_action_status(action["id"], status, result_msg)
        action["_exec_status"] = status
        action["_exec_result"] = result_msg
        auto_results.append({"action": action.get("title"), "success": success, "result": result_msg})
        print(f"sales_strategist: auto-action '{action.get('title')}' → {status}: {result_msg}")

    # ── Step 7: Send strategy report to WhatsApp ─────────────
    try:
        _send_strategy_report(strategy, saved_actions, wa_num, tenant, lp_playwright=lp_playwright)
    except Exception as e:
        print(f"sales_strategist: WA report failed: {e}")

    # ── Step 8: Update strategy status ───────────────────────
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sales_strategies SET status='delivered' WHERE id=%s",
                    (strategy_id,),
                )
    except Exception as e:
        print(f"sales_strategist: status update failed: {e}")

    n_auto = len([a for a in saved_actions if a.get("tier") == "auto"])
    n_approval = len([a for a in saved_actions if a.get("tier") == "approval"])
    n_strategic = len([a for a in saved_actions if a.get("tier") == "strategic"])

    print(f"sales_strategist: done. {n_auto} auto, {n_approval} approval, {n_strategic} strategic")

    return {
        "ok": True,
        "strategy_id": strategy_id,
        "diagnosis_severity": strategy.get("diagnosis", {}).get("severity", ""),
        "actions": {
            "auto_executed": n_auto,
            "awaiting_approval": n_approval,
            "strategic": n_strategic,
        },
        "auto_results": auto_results,
    }
