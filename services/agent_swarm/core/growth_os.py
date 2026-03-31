"""
services/agent_swarm/core/growth_os.py

Growth OS v2 — World-Class Growth Strategy Engine.

Persistent background job architecture:
- Job runs entirely on backend, survives frontend navigation
- Logs each step to growth_os_jobs table in real time
- Gathers intelligence from ALL sources, auto-triggers missing analyses
- Generates 7-dimension 90-day strategy via Claude Opus
"""

import json
import uuid
import time
from datetime import datetime, timezone
from typing import Any

import anthropic

from services.agent_swarm.config import ANTHROPIC_API_KEY

CLAUDE_OPUS = "claude-opus-4-6"

# ── Logging helper ──────────────────────────────────────────────────────────────

def _log(job_id: str, msg: str, phase: str = "intel", type_: str = "info", source: str = None):
    """Append a single log entry to growth_os_jobs.logs (JSONB array)."""
    from services.agent_swarm.db import get_conn
    entry: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "type": type_,
        "msg": msg,
    }
    if source:
        entry["source"] = source
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE growth_os_jobs SET logs = logs || %s::jsonb WHERE id = %s::uuid",
                    (json.dumps([entry]), job_id),
                )
    except Exception as e:
        print(f"[growth_os] _log failed: {e}")


def _is_cancelled(job_id: str) -> bool:
    """Return True if the job has been force-cancelled via the DB flag."""
    from services.agent_swarm.db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM growth_os_jobs WHERE id=%s::uuid", (job_id,))
                row = cur.fetchone()
                return row is not None and row[0] == "cancelled"
    except Exception:
        return False


def _set_job_status(job_id: str, status: str, plan_json: dict = None, credits_charged: int = None):
    """Update job status and optionally save plan."""
    from services.agent_swarm.db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if plan_json is not None and credits_charged is not None:
                    cur.execute(
                        """UPDATE growth_os_jobs
                              SET status=%s, plan_json=%s::jsonb, credits_charged=%s,
                                  completed_at=NOW()
                            WHERE id=%s::uuid""",
                        (status, json.dumps(plan_json), credits_charged, job_id),
                    )
                elif plan_json is not None:
                    cur.execute(
                        """UPDATE growth_os_jobs
                              SET status=%s, plan_json=%s::jsonb, completed_at=NOW()
                            WHERE id=%s::uuid""",
                        (status, json.dumps(plan_json), job_id),
                    )
                else:
                    cur.execute(
                        "UPDATE growth_os_jobs SET status=%s WHERE id=%s::uuid",
                        (status, job_id),
                    )
    except Exception as e:
        print(f"[growth_os] _set_job_status failed: {e}")


# ── Intelligence gathering with logging ────────────────────────────────────────

def _check_meta(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking Meta Ads performance...", source="meta")
    try:
        with conn.cursor() as cur:
            # Use 365-day window so Excel-uploaded historical data is always included.
            # Live API data lands with current timestamps so 365d captures both.
            cur.execute(
                """
                SELECT
                    SUM(spend) AS total_spend,
                    SUM(revenue) AS total_revenue,
                    AVG(CASE WHEN spend > 0 THEN revenue/spend ELSE NULL END) AS avg_roas,
                    AVG(CASE WHEN impressions > 0 THEN clicks/impressions*100 ELSE NULL END) AS avg_ctr,
                    AVG(CASE WHEN clicks > 0 THEN spend/clicks ELSE NULL END) AS avg_cpc,
                    SUM(impressions) AS total_impressions,
                    SUM(clicks) AS total_clicks,
                    SUM(conversions) AS total_conversions,
                    COUNT(DISTINCT entity_name) AS campaign_count
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND platform = 'meta'
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        # Accept data even if spend=0 — Excel files sometimes have only clicks/impressions
        has_data = row and row[8] and int(row[8]) > 0  # campaign_count > 0
        if has_data:
            data = {
                "total_spend": float(row[0] or 0),
                "total_revenue": float(row[1] or 0),
                "avg_roas": float(row[2] or 0),
                "avg_ctr": float(row[3] or 0),
                "avg_cpc": float(row[4] or 0),
                "total_impressions": int(row[5] or 0),
                "total_clicks": int(row[6] or 0),
                "total_conversions": int(row[7] or 0),
            }
            # Also fetch individual campaign names + performance
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT entity_name,
                              ROUND(SUM(COALESCE(spend,0))::numeric,0) AS spend,
                              ROUND(SUM(COALESCE(conversions,0))::numeric,0) AS convs,
                              ROUND(SUM(COALESCE(clicks,0))::numeric,0) AS clicks,
                              ROUND(CASE WHEN SUM(COALESCE(spend,0))>0
                                    THEN SUM(COALESCE(revenue,0))/SUM(COALESCE(spend,0))
                                    ELSE 0 END::numeric,2) AS roas
                       FROM kpi_hourly
                       WHERE workspace_id=%s AND platform='meta' AND entity_level='campaign'
                         AND hour_ts >= NOW() - INTERVAL '365 days'
                       GROUP BY entity_name ORDER BY spend DESC LIMIT 10""",
                    (workspace_id,),
                )
                campaigns = [
                    {"name": r[0], "spend": float(r[1] or 0), "conversions": int(r[2] or 0),
                     "clicks": int(r[3] or 0), "roas": float(r[4] or 0)}
                    for r in cur.fetchall() if r[0]
                ]
            data["campaigns"] = campaigns
            _log(job_id,
                 f"✓ Meta Ads — ₹{data['total_spend']:,.0f} spend · {data['avg_roas']:.2f}× ROAS · CTR {data['avg_ctr']:.2f}% · {len(campaigns)} campaigns",
                 type_="found", source="meta")
            return data
        else:
            _log(job_id, "~ Meta Ads — no data (not connected or no campaigns)", type_="missing", source="meta")
            return {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, f"~ Meta Ads — error reading data: {e}", type_="missing", source="meta")
        return {}


def _check_google(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking Google Ads performance...", source="google")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    SUM(spend) AS total_spend,
                    SUM(revenue) AS total_revenue,
                    AVG(CASE WHEN spend > 0 THEN revenue/spend ELSE NULL END) AS avg_roas,
                    AVG(CASE WHEN impressions > 0 THEN clicks/impressions*100 ELSE NULL END) AS avg_ctr,
                    SUM(clicks) AS total_clicks,
                    SUM(conversions) AS total_conversions,
                    COUNT(DISTINCT entity_name) AS campaign_count
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND platform = 'google'
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        has_data = row and row[6] and int(row[6]) > 0
        if has_data:
            data = {
                "total_spend": float(row[0] or 0),
                "total_revenue": float(row[1] or 0),
                "avg_roas": float(row[2] or 0),
                "avg_ctr": float(row[3] or 0),
                "total_clicks": int(row[4] or 0),
                "total_conversions": int(row[5] or 0),
            }
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT entity_name,
                              ROUND(SUM(COALESCE(spend,0))::numeric,0) AS spend,
                              ROUND(SUM(COALESCE(conversions,0))::numeric,0) AS convs,
                              ROUND(SUM(COALESCE(clicks,0))::numeric,0) AS clicks,
                              ROUND(CASE WHEN SUM(COALESCE(spend,0))>0
                                    THEN SUM(COALESCE(revenue,0))/SUM(COALESCE(spend,0))
                                    ELSE 0 END::numeric,2) AS roas
                       FROM kpi_hourly
                       WHERE workspace_id=%s AND platform='google' AND entity_level='campaign'
                         AND hour_ts >= NOW() - INTERVAL '365 days'
                       GROUP BY entity_name ORDER BY spend DESC LIMIT 10""",
                    (workspace_id,),
                )
                campaigns = [
                    {"name": r[0], "spend": float(r[1] or 0), "conversions": int(r[2] or 0),
                     "clicks": int(r[3] or 0), "roas": float(r[4] or 0)}
                    for r in cur.fetchall() if r[0]
                ]
            data["campaigns"] = campaigns
            _log(job_id,
                 f"✓ Google Ads — ₹{data['total_spend']:,.0f} spend · {data['avg_roas']:.2f}× ROAS · {data['total_conversions']} conversions · {len(campaigns)} campaigns",
                 type_="found", source="google")
            return data
        else:
            _log(job_id, "~ Google Ads — no data (connect Google or upload CSV reports)", type_="missing", source="google")
            return {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, f"~ Google Ads — error reading data: {e}", type_="missing", source="google")
        return {}


def _check_youtube(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking YouTube channel data...", source="youtube")
    try:
        # platform_connections.account_id stores the channel_id for YouTube
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT account_id
                FROM platform_connections
                WHERE workspace_id = %s AND platform = 'youtube' AND account_id IS NOT NULL
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        if not row:
            _log(job_id, "~ YouTube — channel not connected", type_="missing", source="youtube")
            return {}

        channel_id = row[0]

        # Aggregate video stats
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(view_count), 0)
                FROM youtube_videos
                WHERE workspace_id = %s
                """,
                (workspace_id,),
            )
            agg = cur.fetchone()
        video_count = int(agg[0] or 0) if agg else 0
        total_views = int(agg[1] or 0) if agg else 0

        # Top videos
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, view_count, like_count, comment_count,
                       COALESCE(avg_view_duration_pct, 0), COALESCE(is_short, false)
                FROM youtube_videos
                WHERE workspace_id = %s
                ORDER BY view_count DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            top_videos = cur.fetchall()

        data = {
            "channel_id": channel_id,
            "subscriber_count": 0,  # not stored locally; shown as N/A
            "total_views": total_views,
            "video_count": video_count,
            "top_videos": [
                {
                    "title": v[0],
                    "views": int(v[1] or 0),
                    "likes": int(v[2] or 0),
                    "comments": int(v[3] or 0),
                    "retention_pct": float(v[4] or 0),
                    "is_short": v[5],
                }
                for v in top_videos
            ],
        }
        top_title = top_videos[0][0][:50] if top_videos else "unknown"
        _log(job_id,
             f"✓ YouTube — {video_count} videos · {total_views:,} total views · top: \"{top_title}\"",
             type_="found", source="youtube")
        return data
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, f"~ YouTube — not connected", type_="missing", source="youtube")
        return {}


def _check_yt_competitor_intel(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking YouTube competitor intelligence...", source="yt_intel")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, channels_analyzed, created_at
                FROM yt_analysis_jobs
                WHERE workspace_id = %s AND status = 'completed'
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            job = cur.fetchone()
        if not job:
            _log(job_id, "~ YouTube Intel — no analysis completed yet", type_="missing", source="yt_intel")
            return {}

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT topic_name, avg_velocity, hit_rate, trs_score
                FROM yt_topic_clusters WHERE workspace_id = %s
                ORDER BY trs_score DESC LIMIT 8
                """,
                (workspace_id,),
            )
            clusters = cur.fetchall()

            cur.execute(
                """
                SELECT playbook_text, top_features, p90_threshold
                FROM yt_breakout_recipe WHERE workspace_id = %s LIMIT 1
                """,
                (workspace_id,),
            )
            recipe = cur.fetchone()

            cur.execute(
                """
                SELECT plan_15d, plan_30d, thumbnail_brief, hooks_library, emerging_topics
                FROM yt_growth_recipe WHERE workspace_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            growth = cur.fetchone()

        data = {
            "topic_clusters": [
                {"topic": r[0], "velocity": float(r[1] or 0), "hit_rate": float(r[2] or 0), "trs": float(r[3] or 0)}
                for r in clusters
            ],
            "breakout_recipe": {
                "playbook": recipe[0][:500] if recipe and recipe[0] else None,
                "top_features": recipe[1] if recipe else {},
                "p90_threshold": float(recipe[2] or 0) if recipe else 0,
            } if recipe else None,
            "growth_plan": {
                "plan_15d": growth[0][:400] if growth and growth[0] else None,
                "plan_30d": growth[1][:400] if growth and growth[1] else None,
                "hooks_library": growth[3][:400] if growth and growth[3] else None,
                "emerging_topics": growth[4][:300] if growth and growth[4] else None,
            } if growth else None,
        }

        channel_count = int(job[2] or 0)
        top_topic = clusters[0][0] if clusters else "unknown"
        _log(job_id,
             f"✓ YouTube Intel — {channel_count} competitors · top topic: \"{top_topic}\" · hit_rate {clusters[0][2]:.0f}%",
             type_="found", source="yt_intel")
        return data
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ YouTube Intel — no analysis completed yet", type_="missing", source="yt_intel")
        return {}


def _check_brand_intel(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking brand & competitor intelligence...", source="brand_intel")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, brand_url, completed_at
                FROM brand_intel_jobs
                WHERE workspace_id = %s AND status = 'completed'
                ORDER BY completed_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            job_row = cur.fetchone()
        if not job_row:
            _log(job_id, "~ Competitor Intel — no analysis completed yet", type_="missing", source="brand_intel")
            return {}

        bi_job_id = str(job_row[0])
        brand_url = job_row[1] or ""

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competitor_name, competitor_url, confidence_pct,
                       brand_dna, meta_ads, pricing_intel, review_intel, tech_stack
                FROM brand_competitor_profiles
                WHERE job_id = %s::uuid AND confirmed = TRUE
                ORDER BY confidence_pct DESC
                """,
                (bi_job_id,),
            )
            profiles = cur.fetchall()

            cur.execute(
                """
                SELECT competitive_gaps, ad_angle_opportunities, recipe_text
                FROM brand_growth_recipe
                WHERE workspace_id = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            recipe = cur.fetchone()

        data = {
            "brand_url": brand_url,
            "competitors": [
                {
                    "name": p[0],
                    "url": p[1],
                    "confidence_pct": float(p[2] or 0),
                    "tagline": (p[3] or {}).get("tagline"),
                    "uvp": (p[3] or {}).get("uvp"),
                    "icp": (p[3] or {}).get("icp"),
                    "positioning": (p[3] or {}).get("positioning"),
                    "ad_count": (p[4] or {}).get("summary", {}).get("ad_count", 0),
                    "top_themes": (p[4] or {}).get("summary", {}).get("top_message_themes", [])[:3],
                    "pricing_tiers": (p[5] or {}).get("tiers", [])[:3],
                    "pain_points": (p[6] or {}).get("pain_points", [])[:4],
                    "wins": (p[6] or {}).get("wins", [])[:3],
                    "tech_stack": (p[7] or [])[:5],
                }
                for p in profiles
            ],
            "competitive_gaps": recipe[0] if recipe else [],
            "ad_angles": recipe[1] if recipe else [],
            "recipe_text": recipe[2][:600] if recipe and recipe[2] else None,
        }

        comp_names = [c["name"] for c in data["competitors"][:3]]
        _log(job_id,
             f"✓ Competitor Intel — {len(data['competitors'])} competitors: {', '.join(comp_names)}",
             type_="found", source="brand_intel")
        return data
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Competitor Intel — run Brand Intel first from the sidebar", type_="missing", source="brand_intel")
        return {}


def _check_lp_audit(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking landing page audit data...", source="lp_audit")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT audit_json, brand_url, created_at
                FROM lp_audits
                WHERE workspace_id = %s AND status = 'completed'
                ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            _log(job_id, "~ Landing Page Audit — not run yet", type_="missing", source="lp_audit")
            return {}

        audit = row[0] if isinstance(row[0], dict) else {}
        brand = audit.get("brand", {})
        competitors = audit.get("competitors", [])

        data = {
            "brand_url": row[1] or "",
            "brand_grade": brand.get("grade", ""),
            "brand_score": brand.get("score", 0),
            "brand_issues": brand.get("issues", [])[:5],
            "brand_recommendations": brand.get("recommendations", [])[:4],
            "conversion_winner": audit.get("conversion_winner"),
            "competitors": [
                {"name": c.get("name"), "grade": c.get("grade"), "score": c.get("score")}
                for c in competitors[:3]
            ],
        }
        _log(job_id,
             f"✓ Landing Pages — your page: {data['brand_grade']} ({data['brand_score']}/100) · {len(data['brand_issues'])} issues found",
             type_="found", source="lp_audit")
        return data
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Landing Page Audit — not yet run", type_="missing", source="lp_audit")
        return {}


def _check_shopify(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking Shopify store data...", source="shopify")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shop_domain, access_token FROM shopify_connections WHERE workspace_id=%s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
        if not row:
            _log(job_id, "~ Shopify — not connected", type_="missing", source="shopify")
            return {}

        import requests as _req
        from datetime import timedelta
        shop_domain, access_token = row
        headers = {"X-Shopify-Access-Token": access_token}
        since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")

        resp = _req.get(
            f"https://{shop_domain}/admin/api/2024-01/orders.json"
            f"?status=any&financial_status=paid&limit=250&created_at_min={since}"
            "&fields=id,total_price,line_items",
            headers=headers, timeout=15,
        )

        prod_resp = _req.get(
            f"https://{shop_domain}/admin/api/2024-01/products.json?limit=50&fields=id,title,variants,tags",
            headers=headers, timeout=10,
        )

        data = {}
        if resp.ok:
            orders = resp.json().get("orders", [])
            if orders:
                total_rev = sum(float(o.get("total_price", 0)) for o in orders)
                order_count = len(orders)
                data.update({
                    "total_revenue_30d": round(total_rev, 2),
                    "order_count_30d": order_count,
                    "aov": round(total_rev / order_count, 2) if order_count else 0,
                })

        if prod_resp.ok:
            products = prod_resp.json().get("products", [])
            data["products"] = [
                {
                    "title": p["title"],
                    "price": float(p["variants"][0]["price"]) if p.get("variants") else 0,
                    "tags": p.get("tags", "").split(", ")[:5],
                }
                for p in products[:10]
            ]

        if data:
            rev = data.get("total_revenue_30d", 0)
            orders_n = data.get("order_count_30d", 0)
            _log(job_id,
                 f"✓ Shopify — ₹{rev:,.0f} revenue (30d) · {orders_n} orders · {len(data.get('products', []))} products",
                 type_="found", source="shopify")
        else:
            _log(job_id, "~ Shopify — connected but no data", type_="missing", source="shopify")

        return data
    except Exception as e:
        _log(job_id, f"~ Shopify — error: {e}", type_="missing", source="shopify")
        return {}


def _check_email(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking email marketing data...", source="email")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS campaign_count,
                       AVG(COALESCE((stats_json->>'open_rate')::float, 0)) AS avg_open_rate,
                       AVG(COALESCE((stats_json->>'click_rate')::float, 0)) AS avg_click_rate
                FROM email_campaigns
                WHERE workspace_id = %s AND status = 'sent'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                SELECT COUNT(DISTINCT email) FROM email_contacts
                WHERE workspace_id = %s AND unsubscribed = FALSE
                """,
                (workspace_id,),
            )
            contact_row = cur.fetchone()

        campaign_count = int(row[0] or 0) if row else 0
        avg_open = float(row[1] or 0) if row else 0
        avg_click = float(row[2] or 0) if row else 0
        contacts = int(contact_row[0] or 0) if contact_row else 0

        if campaign_count > 0 or contacts > 0:
            data = {
                "campaign_count": campaign_count,
                "avg_open_rate": avg_open,
                "avg_click_rate": avg_click,
                "contact_count": contacts,
            }
            _log(job_id,
                 f"✓ Email — {contacts:,} contacts · {campaign_count} campaigns · {avg_open:.0f}% open rate",
                 type_="found", source="email")
            return data
        else:
            _log(job_id, "~ Email — no campaigns or contacts yet", type_="missing", source="email")
            return {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Email — not connected", type_="missing", source="email")
        return {}


def _check_search_trends(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking search trends data...", source="search_trends")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_name, SUM(clicks) AS total_clicks, AVG(ctr) AS avg_ctr
                FROM kpi_hourly
                WHERE workspace_id = %s AND entity_level = 'search_term'
                  AND hour_ts >= NOW() - INTERVAL '30 days' AND entity_name IS NOT NULL
                GROUP BY entity_name ORDER BY total_clicks DESC LIMIT 15
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

        if rows:
            data = {
                "top_terms": [
                    {"term": r[0], "clicks": int(r[1] or 0), "ctr": float(r[2] or 0)}
                    for r in rows
                ]
            }
            top_term = rows[0][0]
            _log(job_id,
                 f"✓ Search Terms — {len(rows)} keywords · top: \"{top_term}\" ({int(rows[0][1])} clicks)",
                 type_="found", source="search_trends")
            return data
        else:
            # Try Google Trends via pytrends for brand keywords
            try:
                from services.agent_swarm.connectors.google_trends import get_trends_for_workspace
                trends = get_trends_for_workspace(workspace_id, conn)
                if trends and trends.get("seasonality_summary"):
                    _log(job_id, f"✓ Google Trends — {trends.get('seasonality_summary', '')[:80]}", type_="found", source="search_trends")
                    return {"google_trends": trends}
            except Exception:
                pass
            _log(job_id, "~ Search Trends — no keyword data available", type_="missing", source="search_trends")
            return {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Search Trends — no keyword data available", type_="missing", source="search_trends")
        return {}


def _check_organic(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking organic social performance...", source="organic")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS post_count,
                       AVG(COALESCE((raw_json->>'impressions')::float, 0)) AS avg_impressions,
                       AVG(COALESCE((raw_json->>'engagement_rate')::float, 0)) AS avg_engagement,
                       MAX(COALESCE((raw_json->>'impressions')::float, 0)) AS best_impressions
                FROM kpi_hourly
                WHERE workspace_id = %s AND entity_level = 'organic_post'
                  AND hour_ts >= NOW() - INTERVAL '30 days'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

        if row and int(row[0] or 0) > 0:
            data = {
                "post_count": int(row[0] or 0),
                "avg_impressions": float(row[1] or 0),
                "avg_engagement_rate": float(row[2] or 0),
                "best_post_impressions": float(row[3] or 0),
            }
            _log(job_id,
                 f"✓ Organic Social — {data['post_count']} posts · {data['avg_engagement_rate']:.1f}% avg engagement",
                 type_="found", source="organic")
            return data
        else:
            _log(job_id, "~ Organic Social — no post data", type_="missing", source="organic")
            return {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Organic Social — no post data", type_="missing", source="organic")
        return {}


def _check_comments(job_id: str, workspace_id: str, conn) -> dict:
    _log(job_id, "Checking comments & reviews intelligence...", source="comments")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT raw_json FROM kpi_hourly
                WHERE workspace_id = %s AND entity_level = 'comment_intel'
                ORDER BY hour_ts DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        if row and row[0]:
            ci = row[0] if isinstance(row[0], dict) else {}
            pain = ci.get("pain_terms", [])[:6]
            wins = ci.get("winning_terms", [])[:6]
            if pain or wins:
                _log(job_id,
                     f"✓ Comments — pain points: {', '.join(pain[:3])} · wins: {', '.join(wins[:3])}",
                     type_="found", source="comments")
                return ci
        _log(job_id, "~ Comments — not yet analysed", type_="missing", source="comments")
        return {}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Comments — not yet analysed", type_="missing", source="comments")
        return {}


def _check_auction(job_id: str, workspace_id: str, conn) -> dict:
    """Google Auction insights — competitive visibility data."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competitor_domain, AVG(impression_share) AS avg_is,
                       AVG(overlap_rate) AS avg_overlap
                FROM google_auction_insights WHERE workspace_id = %s
                GROUP BY competitor_domain ORDER BY avg_is DESC LIMIT 5
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
        if rows:
            return [
                {"domain": r[0], "impression_share": float(r[1] or 0), "overlap": float(r[2] or 0)}
                for r in rows
            ]
        return []
    except Exception:
        return []


def _check_reddit_voc(job_id: str, workspace_id: str, conn) -> dict:
    """Read competitive Reddit VoC sweep stored during onboarding."""
    _log(job_id, "Checking Reddit Voice of Customer data...", source="reddit_voc")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT reddit_voc FROM onboard_jobs
                WHERE workspace_id = %s AND status = 'complete'
                  AND reddit_voc IS NOT NULL
                ORDER BY updated_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            _log(job_id, "~ Reddit VoC — no sweep data yet (runs during onboarding)", type_="missing", source="reddit_voc")
            return {}

        voc = row[0] if isinstance(row[0], dict) else {}
        synthesis = voc.get("synthesis", {})
        total_posts = voc.get("total_posts", 0)
        queries_run = voc.get("queries_run", 0)
        pain_points = synthesis.get("top_pain_points", [])
        win_opp = synthesis.get("win_opportunity", "")

        if not synthesis and not total_posts:
            _log(job_id, "~ Reddit VoC — sweep ran but returned no posts", type_="missing", source="reddit_voc")
            return {}

        _log(job_id,
             f"✓ Reddit VoC — {total_posts} posts across {queries_run} queries · {len(pain_points)} pain points · sentiment: {synthesis.get('category_sentiment', 'unknown')}",
             type_="found", source="reddit_voc")
        return voc
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log(job_id, "~ Reddit VoC — error reading data", type_="missing", source="reddit_voc")
        return {}


def _run_voc_sweep(job_id: str, workspace_id: str, brand_url: str, competitor_names: list) -> dict:
    """
    Run Reddit competitive VoC sweep inline.
    Called by Growth OS when reddit_voc is missing — permanent auto-fix for all users.
    Returns enriched voc dict (same format as onboard_chain stores).
    Saves result back to onboard_jobs so future strategy runs skip this step.
    """
    import asyncio
    import httpx
    from urllib.parse import urlparse

    _log(job_id, f"⚡ Running Reddit VoC sweep — {brand_url} + {len(competitor_names)} competitors...",
         type_="auto_trigger", source="reddit_voc")

    try:
        # Build own brand query from domain name
        _domain = urlparse(brand_url).netloc.replace("www.", "").split(".")[0]
        _brand_q = _domain.strip().capitalize() if _domain else "brand"

        _search_targets = [("own", _brand_q)] + [("competitor", name) for name in competitor_names[:4]]

        async def _sweep():
            results = {}
            async with httpx.AsyncClient(
                timeout=12,
                headers={"User-Agent": "runway-studios-aria/1.0"},
                follow_redirects=True,
            ) as cli:
                for idx, (kind, query) in enumerate(_search_targets):
                    if idx > 0:
                        await asyncio.sleep(1.5)
                    try:
                        r = await cli.get(
                            "https://www.reddit.com/search.json",
                            params={"q": query, "sort": "relevance", "limit": 20, "type": "link"},
                        )
                        posts = []
                        if r.status_code == 200:
                            for child in r.json().get("data", {}).get("children", []):
                                p = child.get("data", {})
                                posts.append({
                                    "title": p.get("title", ""),
                                    "subreddit": p.get("subreddit_name_prefixed", ""),
                                    "score": p.get("score", 0),
                                    "url": f"https://reddit.com{p.get('permalink', '')}",
                                    "text_preview": (p.get("selftext") or "")[:300].strip(),
                                    "num_comments": p.get("num_comments", 0),
                                })
                        results[query] = {"kind": kind, "posts": posts}
                    except Exception:
                        results[query] = {"kind": kind, "posts": []}
            return results

        raw = asyncio.run(_sweep())

        own_posts = raw.get(_brand_q, {}).get("posts", [])
        comp_posts = {k: v["posts"] for k, v in raw.items() if v.get("kind") == "competitor"}
        total_posts = sum(len(v["posts"]) for v in raw.values())

        _log(job_id, f"   ↳ {total_posts} posts fetched across {len(_search_targets)} queries", source="reddit_voc")

        # Claude Haiku synthesis
        synthesis = {}
        if total_posts > 0:
            try:
                import anthropic as _anth
                from services.agent_swarm.config import ANTHROPIC_API_KEY
                _HAIKU = "claude-haiku-4-5-20251001"

                digest = []
                if own_posts:
                    digest.append(f"=== Reddit posts about {_brand_q} (our brand) ===")
                    for p in own_posts[:8]:
                        digest.append(f"[{p['subreddit']}] {p['title']} | {p['text_preview'][:150]}")
                for cname, cposts in comp_posts.items():
                    if cposts:
                        digest.append(f"\n=== Reddit posts about {cname} (competitor) ===")
                        for p in cposts[:8]:
                            digest.append(f"[{p['subreddit']}] {p['title']} | {p['text_preview'][:150]}")

                resp = _anth.Anthropic(api_key=ANTHROPIC_API_KEY).messages.create(
                    model=_HAIKU,
                    max_tokens=800,
                    system="You are a market research analyst. Return ONLY valid JSON, no markdown.",
                    messages=[{"role": "user", "content": (
                        "Analyse these Reddit posts and return a JSON synthesis.\n\n"
                        + "\n".join(digest[:60])
                        + '\n\nReturn JSON with exactly these keys:\n'
                        '{"top_pain_points":["pain 1","pain 2","pain 3","pain 4","pain 5"],'
                        '"unmet_desires":["desire 1","desire 2","desire 3"],'
                        '"competitor_weaknesses":{"CompetitorName":["weakness 1","weakness 2"]},'
                        '"our_brand_sentiment":"positive|neutral|negative|not_mentioned",'
                        '"category_sentiment":"positive|neutral|negative",'
                        '"win_opportunity":"One sentence: what gap exists that our brand can own"}'
                    )}],
                )
                syn_raw = resp.content[0].text.strip()
                if syn_raw.startswith("```"):
                    syn_raw = syn_raw.split("```", 2)[1]
                    if syn_raw.startswith("json"):
                        syn_raw = syn_raw[4:]
                    syn_raw = syn_raw.rsplit("```", 1)[0]
                synthesis = json.loads(syn_raw.strip())
                _log(job_id,
                     f"   ↳ VoC synthesis: {len(synthesis.get('top_pain_points', []))} pain points · win: {synthesis.get('win_opportunity', '')[:60]}",
                     source="reddit_voc")
            except Exception as e:
                _log(job_id, f"   ↳ VoC synthesis partial: {e}", type_="warning", source="reddit_voc")

        voc_data = {
            "own_posts": own_posts[:15],
            "competitor_posts": {k: v[:10] for k, v in comp_posts.items()},
            "synthesis": synthesis,
            "queries_run": len(_search_targets),
            "total_posts": total_posts,
        }

        # Persist back to onboard_jobs so future Growth OS runs skip the sweep
        try:
            from services.agent_swarm.db import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE onboard_jobs SET reddit_voc=%s::jsonb, updated_at=NOW()
                           WHERE workspace_id=%s AND id=(
                               SELECT id FROM onboard_jobs WHERE workspace_id=%s
                               ORDER BY updated_at DESC LIMIT 1
                           )""",
                        (json.dumps(voc_data), workspace_id, workspace_id),
                    )
                conn.commit()
        except Exception:
            pass  # persist failure is non-fatal — data is used in-memory this run

        return voc_data

    except Exception as e:
        _log(job_id, f"   ↳ Reddit VoC sweep failed: {e}", type_="warning", source="reddit_voc")
        return {}


def _check_workspace(job_id: str, workspace_id: str, conn) -> dict:
    """Get workspace profile (name, type, budget, brand URL)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, workspace_type, monthly_budget, brand_url, store_url
                FROM workspaces WHERE id = %s::uuid
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
        if row:
            return {
                "name": row[0] or "Unknown Brand",
                "type": row[1] or "d2c",
                "monthly_budget": float(row[2] or 0),
                "brand_url": row[3] or row[4] or "",
            }
        return {"name": "Unknown Brand", "type": "d2c", "monthly_budget": 0, "brand_url": ""}
    except Exception:
        return {"name": "Unknown Brand", "type": "d2c", "monthly_budget": 0, "brand_url": ""}


def _check_products_catalog(job_id: str, workspace_id: str, conn) -> list:
    """Fetch products from the central catalog (CSV uploads, Shopify sync, manual)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT name, description, price, product_url, category
                   FROM products
                   WHERE workspace_id = %s::uuid
                   ORDER BY updated_at DESC LIMIT 10""",
                (workspace_id,),
            )
            rows = cur.fetchall()
        if rows:
            products = [
                {
                    "name": r[0] or "",
                    "description": (r[1] or "")[:200],
                    "price": float(r[2]) if r[2] else 0,
                    "url": r[3] or "",
                    "category": r[4] or "",
                }
                for r in rows
            ]
            _log(job_id, f"✓ Product Catalog — {len(products)} products found", type_="found", source="products")
            return products
        _log(job_id, "~ Product Catalog — no products uploaded yet", type_="missing", source="products")
        return []
    except Exception as e:
        return []


# ── Strategy prompt builder ────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the world's most effective growth strategist — embodying the thinking of:
- David Ogilvy (advertising mastery, positioning that sells, copywriting precision)
- Alex Hormozi (irresistible offer creation, value stack, conversion obsession)
- Neil Patel (SEO, content marketing, traffic compounding)
- Chet Holmes (dream 100, education-based selling, systematic pipeline)
- Russell Brunson (funnel strategy, value ladders, community monetisation)
- Rory Sutherland (behavioural economics, perceived value, reframing)

You have access to real intelligence data for this brand. You must produce an exhaustive, concrete, date-bound 90-day growth strategy.

RULES — NON-NEGOTIABLE:
1. Every KPI target must include a number (not "improve CTR" but "target CTR 3.2% from current 1.9% — a 68% lift")
2. Every action must have a specific next step someone can execute tomorrow morning
3. Timeline must be realistic — do not compress 3 months of work into week 1
4. Cover ALL 7 dimensions: Paid Acquisition, Organic Content, Product & Offer, Landing Pages, Email/SMS/WhatsApp, Competitive Positioning, Brand & PR
5. For product: compare user's products vs competitor features, recommend ONE strategic addition that enhances (not replaces) their core product
6. For Email/SMS/WhatsApp: write ACTUAL subject lines, message templates with copy — not abstract plans
7. For landing pages: cite specific findings from audit data if available
8. For competitive: cite specific competitor gaps and name the competitors
9. Every rationale must cite the specific data point that justifies the action
10. Strategy must be achievable by a lean team — flag which actions need agency/tools
11. The user's strategic directive overrides everything — all actions must serve it

Return ONLY valid JSON with this exact structure — no markdown, no preamble:
{
  "strategy_summary": {
    "headline": "30-word strategy headline capturing the core thesis",
    "key_insight": "The single most important thing the data reveals",
    "primary_opportunity": "The biggest untapped opportunity right now",
    "90_day_revenue_target": "Conservative revenue/growth estimate with reasoning",
    "biggest_risk": "What could undermine this strategy and how to mitigate"
  },
  "actions": [
    {
      "id": "<uuid4>",
      "period": "Week 1|Week 2|Month 2|Month 3",
      "dimension": "paid|organic|product|landing_page|crm|competitive|brand",
      "channel": "meta|google|youtube|email|sms|whatsapp|seo|organic_social|shopify|all",
      "priority": "P0|P1|P2",
      "title": "Short imperative title — max 10 words",
      "rationale": "1-2 sentences citing specific data from the intelligence provided",
      "exact_next_step": "Specific action to take tomorrow morning — no vagueness",
      "kpi_target": "Specific measurable target with number and current baseline",
      "effort_days": 1,
      "budget_recommendation": "₹X/day or null if no budget needed",
      "creative_brief": "Hook: ...\\nBody: ...\\nCTA: ...\\nVisual: ...",
      "copy_template": "Actual WhatsApp/Email/SMS message template with [PLACEHOLDERS] or null",
      "setup_guide": "Step 1: ...\\nStep 2: ...\\nStep 3: ...",
      "source": "Which intelligence source justifies this action"
    }
  ],
  "product_brief": {
    "hero_feature_recommendation": "Specific feature to add based on competitor analysis",
    "rationale": "Why this feature — cite which competitors have it, what customer pain it solves",
    "positioning_angle": "Exact angle to use in ads and landing pages for this feature",
    "pricing_suggestion": "Price point recommendation with reasoning",
    "implementation_steps": "Step 1: ...\\nStep 2: ...\\nStep 3: ..."
  },
  "crm_sequences": [
    {
      "name": "Sequence name",
      "channel": "email|whatsapp|sms",
      "trigger": "What triggers this sequence",
      "messages": [
        {
          "day": 0,
          "subject": "Subject line (for email)",
          "body": "Full message body with [BRAND_NAME] [FIRST_NAME] placeholders",
          "cta": "Call to action text",
          "goal": "What this message achieves"
        }
      ]
    }
  ],
  "intelligence_coverage": {
    "sources_used": ["list of sources that had data"],
    "sources_missing": ["list of sources with no data"],
    "coverage_pct": 75
  },
  "honest_assessment": {
    "headline": "One brutal-truth sentence about the brand's current growth state",
    "what_is_working": ["Specific thing working with data evidence", "Another thing"],
    "what_is_broken": ["Specific blocker with data evidence", "Specific issue"],
    "real_30d_target": "What is realistically achievable in 30 days — USE ONLY real numbers from the data. State ₹ revenue or % growth with the assumption behind it.",
    "real_90d_target": "90-day realistic target with assumptions. If no data, say what data is needed."
  },
  "asymmetric_moves": [
    {
      "rank": 1,
      "title": "5-8 word move title",
      "why_asymmetric": "Why this has 10x impact vs effort — cite data",
      "data_basis": "The specific data point that proves this move",
      "timeline": "Days 1-7",
      "revenue_or_growth_potential": "Specific estimate: ₹X/month additional revenue OR X% subscriber growth"
    }
  ],
  "sprint_calendar": {
    "week_1": {
      "theme": "Week 1 theme — 5 words",
      "days": [
        {"days": "1-2", "task": "Specific task", "why_first": "Why this is first", "outcome": "What you will have by end of day 2"}
      ]
    },
    "week_2": {"theme": "...", "days": [{"days": "8-10", "task": "...", "why_first": "...", "outcome": "..."}]},
    "week_3": {"theme": "...", "days": [{"days": "15-17", "task": "...", "why_first": "...", "outcome": "..."}]},
    "week_4": {"theme": "...", "days": [{"days": "22-24", "task": "...", "why_first": "...", "outcome": "..."}]}
  },
  "channel_rankings": [
    {
      "rank": 1,
      "channel_or_format": "Channel name (brands) or content format (creators)",
      "estimated_cac_or_cpm": "₹X estimated CAC or ₹Y CPM — based on data or category benchmark",
      "speed": "Fast",
      "priority": "DO FIRST",
      "reason": "One sentence why this rank based on data"
    }
  ],
  "financial_model": {
    "current_state": "Current monthly revenue or views/subscribers — based on data only",
    "month_1_target": "₹X — state exact assumption e.g. if ROAS stays at 2.8 and daily spend increases to ₹8K",
    "month_3_target": "₹X — state key assumption",
    "month_12_target": "₹X — state key assumption and what must be true",
    "biggest_lever": "The single action with highest revenue/growth impact and why",
    "break_even_point": "At what monthly spend or output level does this become self-sustaining"
  },
  "not_to_do": [
    {
      "dont": "Do not [specific action]",
      "because": "Data-backed reason — cite specific number from intel"
    }
  ],
  "weekly_kpis": [
    {
      "metric": "Metric name",
      "current_value": "X from real data or no data yet",
      "week_4_target": "Y",
      "red_flag": "Below Z — means stop or change course",
      "how_to_measure": "Where exactly to check this metric"
    }
  ]
}

Generate 20-30 actions total, spread across all 7 dimensions and all 4 time periods.
For CRM sequences: generate at least 3 (Welcome, Cart Abandon/Follow-up, Win-back).
Each email in a sequence should have a FULL body — at least 3-4 paragraphs of real copy.

CRITICAL RULES FOR NEW SECTIONS:
- honest_assessment: Use ONLY real numbers from data provided. If spending ₹X at ROAS Y that equals ₹Z revenue — say that. No invented numbers.
- asymmetric_moves: Generate EXACTLY 3 moves, ranked by impact/effort ratio. Each must cite a specific data point.
- sprint_calendar: Each week must have 2-4 specific day-ranges with concrete tasks derived from the intel data — not generic advice. For creators: this is a content calendar. For brands: this is an execution calendar.
- channel_rankings: Include ALL relevant channels (6-10 entries). For brands: rank by CAC/conversion speed. For creators: rank content formats by views/effort ratio from real video data.
- financial_model: Use ONLY real numbers from connected data. If Meta ROAS and spend data exists, project revenue as spend × ROAS scenarios. If YouTube data exists, project as views × CPM benchmarks. NEVER invent — always state basis. Use ₹ currency.
- not_to_do: 3-5 items. Each grounded in specific data from intel. Be direct and opinionated.
- weekly_kpis: 5-7 metrics. Use real current values from data where available. Red flag thresholds should be specific numbers.
"""


def _build_strategy_prompt(intel: dict, directive: str = None, strategy_mode: str = None) -> str:
    lines = []

    # Strategic directive — highest priority
    if directive and directive.strip():
        mode_label = {
            "scale": "🚀 SCALE MODE — Maximise revenue at all costs",
            "efficiency": "⚡ EFFICIENCY MODE — Cut waste, improve ROAS",
            "launch": "🆕 PRODUCT LAUNCH MODE — Drive maximum awareness and first purchases",
            "seasonal": "📅 SEASONAL PUSH MODE — Capitalise on seasonal demand",
            "custom": "🎯 CUSTOM DIRECTIVE",
        }.get(strategy_mode or "", "🎯 STRATEGIC DIRECTIVE")

        lines.append(f"=== {mode_label} — THIS OVERRIDES EVERYTHING ===")
        lines.append(directive.strip())
        lines.append("\nEvery single action in this strategy MUST serve this directive. Weight all channels, timing, and budget toward this goal.\n")

    ws = intel.get("workspace", {})
    ws_type = ws.get("type", "d2c")
    is_creator = ws_type in ("creator", "media")

    lines.append(f"=== BRAND PROFILE ===")
    lines.append(f"Brand: {ws.get('name', 'Unknown')}")
    lines.append(f"Type: {ws_type}")
    lines.append(f"Monthly Budget: ₹{ws.get('monthly_budget', 0):,.0f}")
    if ws.get("brand_url"):
        lines.append(f"Website: {ws['brand_url']}")

    # Workspace-type context — tells Claude how to frame the new sections
    if is_creator:
        lines.append("\n=== STRATEGY TYPE: YOUTUBE CREATOR / MEDIA ===")
        lines.append("This is a creator workspace. Adapt ALL new sections as follows:")
        lines.append("• channel_rankings = content FORMAT rankings (Shorts/Tutorial/Review/Vlog/Podcast etc) by avg views, CTR, and effort")
        lines.append("• financial_model = subscriber/views growth + monetisation: AdSense CPM × monthly views + sponsorship ₹ value at subscriber milestones")
        lines.append("• actions focus on: content calendar, thumbnail A/B test, collab outreach, SEO title formulas, Shorts funnel to long-form")
        lines.append("• sprint_calendar = week-by-week content publishing plan with specific video titles/topics/formats based on competitor intel")
        lines.append("• not_to_do = creator-specific pitfalls grounded in the YouTube data provided")
        lines.append("• financial_model targets = monthly AdSense ₹ + sponsorship ₹ at target subscriber/view milestones from real data")
    else:
        lines.append("\n=== STRATEGY TYPE: BRAND / D2C / SAAS / AGENCY ===")
        lines.append("This is a brand running paid advertising + owned channels. Strategy focuses on:")
        lines.append("• channel_rankings = advertising + owned channels ranked by CAC, conversion speed, and ROI")
        lines.append("• financial_model = monthly revenue = ad_spend × ROAS + organic/email channels — project from real spend/ROAS data")
        lines.append("• sprint_calendar = week-by-week brand execution: campaign launches, LP fixes, email sequences, creative testing")
        lines.append("• financial_model: use real ROAS and spend numbers to project — state assumptions clearly")

    # Product Catalog — inject before ad data so ARIA knows what's being sold
    products_catalog = intel.get("products_catalog", [])
    # Also merge Shopify products if no catalog products exist
    if not products_catalog:
        shopify_products = intel.get("shopify", {}).get("products", [])
        if shopify_products:
            products_catalog = [{"name": p["title"], "price": p["price"], "description": "", "url": "", "category": ""} for p in shopify_products]
    if products_catalog:
        lines.append("\n=== PRODUCTS BEING SOLD ===")
        lines.append("IMPORTANT: These are the ACTUAL products this brand sells. Base ALL strategy, copy, and channel recommendations on these products — not on any assumed category.")
        for p in products_catalog[:8]:
            price_str = f" | ₹{p['price']:,.0f}" if p.get("price") else ""
            desc_str = f" — {p['description'][:120]}" if p.get("description") else ""
            cat_str = f" [{p['category']}]" if p.get("category") else ""
            lines.append(f"  • {p['name']}{cat_str}{price_str}{desc_str}")
    else:
        lines.append("\n=== PRODUCTS: No catalog uploaded — infer from brand name and website ===")

    # Meta Ads
    meta = intel.get("meta", {})
    if meta:
        lines.append("\n=== META ADS (Historical) ===")
        lines.append(f"Spend: ₹{meta.get('total_spend', 0):,.0f}")
        lines.append(f"Revenue: ₹{meta.get('total_revenue', 0):,.0f}")
        lines.append(f"ROAS: {meta.get('avg_roas', 0):.2f}× (target 2.5×)")
        lines.append(f"CTR: {meta.get('avg_ctr', 0):.2f}% (industry avg 1.0%)")
        lines.append(f"CPC: ₹{meta.get('avg_cpc', 0):.0f}")
        lines.append(f"Conversions: {meta.get('total_conversions', 0):,}")
        for c in meta.get("campaigns", [])[:8]:
            roas_str = f" | ROAS {c['roas']:.2f}x" if c['roas'] > 0 else ""
            lines.append(f"  Campaign: {c['name']} — Spend ₹{c['spend']:,.0f} | Clicks {c['clicks']}{roas_str}")
    else:
        lines.append("\n=== META ADS: Not connected — exclude from paid strategy ===")

    # Google Ads
    google = intel.get("google", {})
    if google:
        lines.append("\n=== GOOGLE ADS (Historical) ===")
        lines.append(f"Spend: ₹{google.get('total_spend', 0):,.0f}")
        lines.append(f"ROAS: {google.get('avg_roas', 0):.2f}×")
        lines.append(f"CTR: {google.get('avg_ctr', 0):.2f}%")
        lines.append(f"Conversions: {google.get('total_conversions', 0)}")
        for c in google.get("campaigns", [])[:8]:
            roas_str = f" | ROAS {c['roas']:.2f}x" if c['roas'] > 0 else ""
            lines.append(f"  Campaign: {c['name']} — Spend ₹{c['spend']:,.0f} | Clicks {c['clicks']}{roas_str}")

    # YouTube Channel
    yt = intel.get("youtube", {})
    if yt:
        lines.append("\n=== YOUTUBE CHANNEL ===")
        lines.append(f"Subscribers: {yt.get('subscriber_count', 0):,}")
        lines.append(f"Total Views: {yt.get('total_views', 0):,}")
        lines.append(f"Videos: {yt.get('video_count', 0)}")
        top = yt.get("top_videos", [])
        if top:
            lines.append("Top Videos:")
            for v in top[:5]:
                lines.append(f"  • \"{v['title'][:60]}\" — {v['views']:,} views, {v['retention_pct']:.0f}% retention {'[SHORT]' if v.get('is_short') else ''}")

    # YouTube Competitor Intel
    yt_intel = intel.get("yt_intel", {})
    if yt_intel:
        clusters = yt_intel.get("topic_clusters", [])
        if clusters:
            lines.append("\n=== YOUTUBE COMPETITOR TOPIC INTELLIGENCE ===")
            for c in clusters[:6]:
                lines.append(f"  • {c['topic']}: hit_rate={c['hit_rate']:.0f}%, velocity={c['velocity']:.0f}/day, TRS={c['trs']:.1f}")
        recipe = yt_intel.get("breakout_recipe")
        if recipe and recipe.get("playbook"):
            lines.append(f"\nBreakout Playbook: {recipe['playbook'][:300]}")
        growth = yt_intel.get("growth_plan")
        if growth:
            if growth.get("hooks_library"):
                lines.append(f"\nWinning Hooks Library: {growth['hooks_library'][:300]}")
            if growth.get("emerging_topics"):
                lines.append(f"Emerging Topics: {growth['emerging_topics'][:200]}")

    # Brand & Competitor Intel
    brand = intel.get("brand_intel", {})
    if brand:
        lines.append("\n=== BRAND & COMPETITOR INTELLIGENCE ===")
        for c in brand.get("competitors", [])[:4]:
            lines.append(f"\nCompetitor: {c['name']} ({c['url']})")
            if c.get("positioning"):
                lines.append(f"  Positioning: {c['positioning'][:120]}")
            if c.get("uvp"):
                lines.append(f"  UVP: {c['uvp'][:100]}")
            if c.get("ad_count", 0) > 0:
                lines.append(f"  Active Meta Ads: {c['ad_count']} | Themes: {', '.join(c.get('top_themes', []))}")
            pricing = c.get("pricing_tiers", [])
            if pricing:
                pricing_str = ", ".join([p.get("name", "") + " " + str(p.get("price", "")) for p in pricing[:3]])
                lines.append(f"  Pricing: {pricing_str}")
            if c.get("pain_points"):
                lines.append(f"  Customer Pain Points: {'; '.join(c['pain_points'][:3])}")
            if c.get("tech_stack"):
                lines.append(f"  Tech Stack: {', '.join(c['tech_stack'][:5])}")

        gaps = brand.get("competitive_gaps", [])
        if gaps:
            lines.append("\nCompetitive Gaps (exploit these):")
            for g in gaps[:5]:
                if isinstance(g, dict):
                    lines.append(f"  • [{g.get('priority', '').upper()}] {g.get('gap', '')} → {g.get('opportunity', '')}")

        angles = brand.get("ad_angles", [])
        if angles:
            lines.append("\nWinning Ad Angles to Test:")
            for a in angles[:3]:
                if isinstance(a, dict):
                    lines.append(f"  • {a.get('angle', '')}: \"{a.get('headline', '')}\"")

    # Landing Page Audit
    lp = intel.get("lp_audit", {})
    if lp:
        lines.append(f"\n=== LANDING PAGE AUDIT ===")
        lines.append(f"Your Page: Grade {lp.get('brand_grade', '?')} ({lp.get('brand_score', 0)}/100)")
        issues = lp.get("brand_issues", [])
        if issues:
            lines.append(f"Issues: {'; '.join(issues[:5])}")
        recs = lp.get("brand_recommendations", [])
        if recs:
            lines.append(f"AI Recommendations: {'; '.join(recs[:4])}")
        if lp.get("conversion_winner"):
            lines.append(f"Conversion Winner: {lp['conversion_winner']}")
        for comp in lp.get("competitors", [])[:2]:
            lines.append(f"Competitor '{comp.get('name', '')}': Grade {comp.get('grade', '?')} ({comp.get('score', 0)}/100)")

    # Shopify
    shopify = intel.get("shopify", {})
    if shopify:
        lines.append("\n=== SHOPIFY STORE DATA ===")
        lines.append(f"Revenue (30d): ₹{shopify.get('total_revenue_30d', 0):,.0f}")
        lines.append(f"Orders (30d): {shopify.get('order_count_30d', 0)}")
        lines.append(f"Average Order Value: ₹{shopify.get('aov', 0):,.0f}")
        products = shopify.get("products", [])
        if products:
            lines.append("Products:")
            for p in products[:6]:
                lines.append(f"  • {p['title']}: ₹{p['price']:,.0f}")

    # Email
    email = intel.get("email", {})
    if email:
        lines.append("\n=== EMAIL MARKETING ===")
        lines.append(f"Contacts: {email.get('contact_count', 0):,}")
        lines.append(f"Campaigns sent: {email.get('campaign_count', 0)}")
        lines.append(f"Avg open rate: {email.get('avg_open_rate', 0):.1f}% (industry avg 21%)")
        lines.append(f"Avg click rate: {email.get('avg_click_rate', 0):.1f}%")

    # Search terms
    search = intel.get("search_trends", {})
    if search.get("top_terms"):
        lines.append("\n=== TOP SEARCH TERMS ===")
        for t in search["top_terms"][:10]:
            lines.append(f"  • \"{t['term']}\": {t['clicks']} clicks, CTR {t['ctr']:.1f}%")

    # Organic social
    organic = intel.get("organic", {})
    if organic:
        lines.append("\n=== ORGANIC SOCIAL ===")
        lines.append(f"Posts (30d): {organic.get('post_count', 0)}")
        lines.append(f"Avg engagement rate: {organic.get('avg_engagement_rate', 0):.1f}%")

    # Comments
    comments = intel.get("comments", {})
    if comments:
        pain = comments.get("pain_terms", [])
        wins = comments.get("winning_terms", [])
        if pain or wins:
            lines.append("\n=== CUSTOMER SENTIMENT (from comments) ===")
            if pain:
                lines.append(f"Pain points: {', '.join(pain[:8])}")
            if wins:
                lines.append(f"Love: {', '.join(wins[:8])}")

    # Reddit VoC — competitive sweep
    reddit_voc = intel.get("reddit_voc", {})
    if reddit_voc:
        synthesis = reddit_voc.get("synthesis", {})
        pain_points = synthesis.get("top_pain_points", [])
        unmet = synthesis.get("unmet_desires", [])
        comp_weaknesses = synthesis.get("competitor_weaknesses", {})
        win_opp = synthesis.get("win_opportunity", "")
        total_posts = reddit_voc.get("total_posts", 0)
        queries_run = reddit_voc.get("queries_run", 0)

        if pain_points or unmet or comp_weaknesses:
            lines.append(f"\n=== REDDIT VOICE OF CUSTOMER (Competitive Sweep — {total_posts} posts, {queries_run} brands) ===")
            lines.append("IMPORTANT: These are real customer pain points from Reddit across this product category — not assumptions.")
            if pain_points:
                lines.append(f"Top Pain Points (whole category): {'; '.join(pain_points[:5])}")
            if unmet:
                lines.append(f"Unmet Customer Desires: {'; '.join(unmet[:3])}")
            if synthesis.get("our_brand_sentiment"):
                lines.append(f"Our Brand Sentiment on Reddit: {synthesis['our_brand_sentiment']}")
            if synthesis.get("category_sentiment"):
                lines.append(f"Category Sentiment: {synthesis['category_sentiment']}")
            for comp_name, weaknesses in list(comp_weaknesses.items())[:4]:
                if weaknesses:
                    lines.append(f"  {comp_name} weaknesses (from Reddit): {'; '.join(weaknesses[:3])}")
            if win_opp:
                lines.append(f"Win Opportunity: {win_opp}")
            lines.append("→ Use these pain points to write ad copy, landing page headlines, and email subject lines that resonate.")
            lines.append("→ For each competitor weakness, recommend a specific action that makes us the obvious alternative.")

    # Auction insights
    auction = intel.get("auction_insights", [])
    if auction:
        lines.append("\n=== GOOGLE AUCTION INSIGHTS ===")
        for a in auction[:5]:
            lines.append(f"  • {a['domain']}: {a['impression_share']:.0f}% impression share, {a['overlap']:.0f}% overlap")

    return "\n".join(lines)


# ── Main job runner ────────────────────────────────────────────────────────────

def run_full_strategy_job(
    job_id: str,
    workspace_id: str,
    directive: str = None,
    brand_url: str = None,
    strategy_mode: str = None,
    auto_trigger_analyses: bool = True,
    credits_base: int = 10,
):
    """
    Full strategy generation. Runs entirely on backend.
    Logs to growth_os_jobs table in real time.
    """
    from services.agent_swarm.db import get_conn

    total_credits = credits_base

    try:
        _set_job_status(job_id, "running")
        _log(job_id, "═══════════════════════════════════════", "start", "separator")
        _log(job_id, "  ARIA Growth OS — World-Class Strategy Engine", "start", "header")
        _log(job_id, "═══════════════════════════════════════", "start", "separator")
        _log(job_id, "Phase 1: Intelligence Sweep — gathering all data sources", "intel", "phase")
        _log(job_id, "─────────────────────────────────────────────────────────", "intel", "divider")

        with get_conn() as conn:
            workspace = _check_workspace(job_id, workspace_id, conn)
            products_catalog = _check_products_catalog(job_id, workspace_id, conn)
            meta = _check_meta(job_id, workspace_id, conn)
            google = _check_google(job_id, workspace_id, conn)
            youtube = _check_youtube(job_id, workspace_id, conn)
            yt_intel = _check_yt_competitor_intel(job_id, workspace_id, conn)
            brand_intel = _check_brand_intel(job_id, workspace_id, conn)
            lp_audit = _check_lp_audit(job_id, workspace_id, conn)
            shopify = _check_shopify(job_id, workspace_id, conn)
            email = _check_email(job_id, workspace_id, conn)
            search_trends = _check_search_trends(job_id, workspace_id, conn)
            organic = _check_organic(job_id, workspace_id, conn)
            comments = _check_comments(job_id, workspace_id, conn)
            auction_insights = _check_auction(job_id, workspace_id, conn)
            reddit_voc = _check_reddit_voc(job_id, workspace_id, conn)

        # Count what's available
        sources_found = []
        sources_missing = []
        intel_map = {
            "meta": meta, "google": google, "youtube": youtube,
            "yt_intel": yt_intel, "brand_intel": brand_intel, "lp_audit": lp_audit,
            "shopify": shopify, "email": email, "search_trends": search_trends,
            "organic": organic, "comments": comments, "reddit_voc": reddit_voc,
        }
        for k, v in intel_map.items():
            if v:
                sources_found.append(k)
            else:
                sources_missing.append(k)

        _log(job_id, "─────────────────────────────────────────────────────────", "intel", "divider")
        _log(job_id,
             f"Intelligence complete — {len(sources_found)}/{len(intel_map)} sources active",
             "intel", "summary")

        # ── Cancellation checkpoint after intel sweep ──────────────────────────
        if _is_cancelled(job_id):
            _log(job_id, "⛔ Job cancelled by user.", "cancelled", "cancelled")
            return

        # Auto-trigger missing critical analyses
        # Use explicitly-passed brand_url if provided, otherwise fall back to workspace setting
        if brand_url:
            workspace["brand_url"] = brand_url
        if auto_trigger_analyses and workspace.get("brand_url"):
            brand_url = workspace["brand_url"]

            if not brand_intel and brand_url:
                _log(job_id, "", "intel", "divider")
                _log(job_id,
                     f"⚡ Auto-triggering Competitor Intelligence for {brand_url} (+20 credits)...",
                     "trigger", "auto_trigger", source="brand_intel")
                total_credits += 20
                try:
                    _trigger_brand_intel(job_id, workspace_id, brand_url)
                    # Wait for it to run (max 3 mins), checking for cancellation each tick
                    for _ in range(36):
                        if _is_cancelled(job_id):
                            _log(job_id, "⛔ Job cancelled by user.", "cancelled", "cancelled")
                            return
                        time.sleep(5)
                        with get_conn() as conn:
                            brand_intel = _check_brand_intel_silent(workspace_id, conn)
                        if brand_intel:
                            intel_map["brand_intel"] = brand_intel
                            sources_found.append("brand_intel")
                            if "brand_intel" in sources_missing:
                                sources_missing.remove("brand_intel")
                            break
                        _log(job_id, "   ↳ Competitor analysis in progress...", "trigger", "progress")
                except Exception as e:
                    _log(job_id, f"   ↳ Could not auto-trigger competitor intel: {e}", "trigger", "warning")

            if not lp_audit and brand_url:
                if _is_cancelled(job_id):
                    _log(job_id, "⛔ Job cancelled by user.", "cancelled", "cancelled")
                    return
                _log(job_id,
                     f"⚡ Auto-triggering Landing Page Audit for {brand_url} (+5 credits)...",
                     "trigger", "auto_trigger", source="lp_audit")
                total_credits += 5
                try:
                    _trigger_lp_audit(job_id, workspace_id, brand_url)
                    for _ in range(18):
                        if _is_cancelled(job_id):
                            _log(job_id, "⛔ Job cancelled by user.", "cancelled", "cancelled")
                            return
                        time.sleep(5)
                        with get_conn() as conn:
                            lp_audit = _check_lp_audit_silent(workspace_id, conn)
                        if lp_audit:
                            intel_map["lp_audit"] = lp_audit
                            sources_found.append("lp_audit")
                            if "lp_audit" in sources_missing:
                                sources_missing.remove("lp_audit")
                            break
                        _log(job_id, "   ↳ LP audit in progress...", "trigger", "progress")
                except Exception as e:
                    _log(job_id, f"   ↳ Could not auto-trigger LP audit: {e}", "trigger", "warning")

            # Auto-run Reddit VoC sweep when missing (permanent fix — works for all users)
            if not reddit_voc and brand_url:
                if _is_cancelled(job_id):
                    _log(job_id, "⛔ Job cancelled by user.", "cancelled", "cancelled")
                    return
                # Get competitor names from brand_intel (may have just been freshly gathered above)
                _comp_names = [c["name"] for c in intel_map.get("brand_intel", {}).get("competitors", [])[:4] if c.get("name")]
                reddit_voc = _run_voc_sweep(job_id, workspace_id, brand_url, _comp_names)
                if reddit_voc:
                    intel_map["reddit_voc"] = reddit_voc
                    sources_found.append("reddit_voc")
                    if "reddit_voc" in sources_missing:
                        sources_missing.remove("reddit_voc")

        # ── Cancellation checkpoint before strategy generation ─────────────────
        if _is_cancelled(job_id):
            _log(job_id, "⛔ Job cancelled by user.", "cancelled", "cancelled")
            return

        # Build intel dict for prompt
        intel = {
            "workspace": workspace,
            "products_catalog": products_catalog,
            **intel_map,
            "auction_insights": auction_insights,
        }

        _log(job_id, "", "strategy", "divider")
        _log(job_id, "Phase 2: Strategy Generation — Claude Opus thinking...", "strategy", "phase")
        _log(job_id, "─────────────────────────────────────────────────────────", "strategy", "divider")
        _log(job_id, "Analysing paid acquisition opportunities...", "strategy", "thinking")
        time.sleep(1)
        _log(job_id, "Analysing organic content strategy...", "strategy", "thinking")
        time.sleep(1)
        _log(job_id, "Analysing product & offer gaps...", "strategy", "thinking")
        time.sleep(1)
        _log(job_id, "Analysing landing page optimisation...", "strategy", "thinking")
        time.sleep(1)
        _log(job_id, "Building email/SMS/WhatsApp sequences with real copy...", "strategy", "thinking")
        time.sleep(1)
        _log(job_id, "Synthesising competitive positioning strategy...", "strategy", "thinking")
        time.sleep(1)
        _log(job_id, "Generating 90-day brand strategy...", "strategy", "thinking")

        prompt = _build_strategy_prompt(intel, directive=directive, strategy_mode=strategy_mode)

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # Use streaming — required for large outputs (>10 min generation time at 32K tokens)
        raw = ""
        with client.messages.stream(
            model=CLAUDE_OPUS,
            max_tokens=32768,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                raw += chunk
        raw = raw.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        # Attempt to recover truncated JSON (hit max_tokens mid-output)
        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            # Truncated: close all open arrays/objects and retry
            recovered = raw
            open_brackets = recovered.count("{") - recovered.count("}")
            open_arrays = recovered.count("[") - recovered.count("]")
            # Close any open string (heuristic: count unescaped quotes)
            # Strip trailing incomplete value up to the last comma or colon
            for ch in [",", ":"]:
                last = recovered.rfind(ch)
                if last > len(recovered) - 200:
                    recovered = recovered[:last]
            recovered = recovered.rstrip().rstrip(",")
            # Close open arrays/objects
            open_arrays = recovered.count("[") - recovered.count("]")
            open_brackets = recovered.count("{") - recovered.count("}")
            recovered += "]" * max(open_arrays, 0) + "}" * max(open_brackets, 0)
            plan = json.loads(recovered)
            _log(job_id, "⚠️ Strategy JSON was truncated — recovered partial plan", "strategy", "warning")

        # Assign UUIDs if missing
        for action in plan.get("actions", []):
            if not action.get("id"):
                action["id"] = str(uuid.uuid4())

        # Add coverage metadata
        plan["intelligence_coverage"] = {
            "sources_used": sources_found,
            "sources_missing": sources_missing,
            "coverage_pct": round(len(sources_found) / max(len(intel_map), 1) * 100),
        }

        action_count = len(plan.get("actions", []))
        crm_count = len(plan.get("crm_sequences", []))

        _log(job_id, "─────────────────────────────────────────────────────────", "strategy", "divider")
        _log(job_id,
             f"✅ Strategy complete — {action_count} actions · {crm_count} CRM sequences · 7 dimensions · 90-day timeline",
             "strategy", "done")

        # Save to growth_os_plans (legacy table) for backward compat
        with get_conn() as conn:
            with conn.cursor() as cur:
                plan_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO growth_os_plans
                           (id, workspace_id, plan_json, generated_at, strategy_mode, directive, sources_used)
                       VALUES (%s::uuid, %s::uuid, %s::jsonb, NOW(), %s, %s, %s::jsonb)""",
                    (
                        plan_id,
                        workspace_id,
                        json.dumps(plan),
                        strategy_mode or "custom",
                        directive or "",
                        json.dumps({"sources_used": sources_found, "sources_missing": sources_missing}),
                    ),
                )

        plan["plan_id"] = plan_id
        _set_job_status(job_id, "completed", plan_json=plan, credits_charged=total_credits)

    except json.JSONDecodeError as e:
        _log(job_id, f"❌ Failed to parse Claude response: {e}", "error", "error")
        _set_job_status(job_id, "failed")
    except Exception as e:
        import traceback
        _log(job_id, f"❌ Error: {str(e)}", "error", "error")
        print(f"[growth_os] run_full_strategy_job error: {traceback.format_exc()}")
        _set_job_status(job_id, "failed")


def _trigger_brand_intel(job_id: str, workspace_id: str, brand_url: str):
    """Brand intel requires user confirmation between phases — cannot auto-complete.
    Raise an exception so the caller skips the auto-trigger gracefully."""
    raise RuntimeError(
        "Brand Intel requires competitor confirmation in the dashboard — run it manually from the sidebar."
    )


def _trigger_lp_audit(job_id: str, workspace_id: str, brand_url: str):
    """Start LP audit in background."""
    import threading
    from services.agent_swarm.connectors.lp_auditor import run_full_audit
    from services.agent_swarm.db import get_conn
    import asyncio

    audit_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO lp_audits (id, workspace_id, brand_url, status)
                   VALUES (%s::uuid, %s::uuid, %s, 'running')""",
                (audit_id, workspace_id, brand_url),
            )

    def _run():
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(run_full_audit(brand_url, [], "Brand"))
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE lp_audits SET status='completed', audit_json=%s::jsonb, updated_at=NOW() WHERE id=%s::uuid",
                        (json.dumps(result), audit_id),
                    )
        except Exception as e:
            print(f"[growth_os] auto lp audit failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
    _log(job_id, f"   ↳ Scoring your landing page...", "trigger", "progress")


def _check_brand_intel_silent(workspace_id: str, conn) -> dict:
    """Check brand intel without logging."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM brand_intel_jobs WHERE workspace_id=%s AND status='completed' ORDER BY completed_at DESC LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
        if row:
            # Re-use the logging version but we don't have a job_id here — return minimal
            return {"available": True}
        return {}
    except Exception:
        return {}


def _check_lp_audit_silent(workspace_id: str, conn) -> dict:
    """Check LP audit without logging."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT audit_json FROM lp_audits WHERE workspace_id=%s AND status='completed' ORDER BY created_at DESC LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else {}
    except Exception:
        return {}


# ── Legacy compatibility (existing /growth-os/generate still works) ─────────────

def generate_action_plan(workspace_id: str, conn, directive: str = None, strategy_mode: str = None):
    """Legacy function — creates a v2 job and runs it synchronously."""
    job_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO growth_os_jobs (id, workspace_id, directive, strategy_mode, status)
               VALUES (%s::uuid, %s::uuid, %s, %s, 'pending')""",
            (job_id, workspace_id, directive or "", strategy_mode or ""),
        )
    run_full_strategy_job(job_id, workspace_id, directive=directive, strategy_mode=strategy_mode)
