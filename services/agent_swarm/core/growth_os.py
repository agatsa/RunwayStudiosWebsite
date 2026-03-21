"""
services/agent_swarm/core/growth_os.py

Growth OS — Unified Cross-Platform Action Plan Engine.

Reads from all intelligence sources (YouTube competitor intel, Meta, Google,
GA4, auction insights, search trends, comments) and synthesises a prioritised
12-15 action plan via Claude Sonnet.

DB pattern: callers pass a live psycopg2 conn.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import anthropic

from services.agent_swarm.config import ANTHROPIC_API_KEY

CLAUDE_SONNET = "claude-sonnet-4-6"

# ── Data gathering ─────────────────────────────────────────────────────────────

def gather_intelligence(workspace_id: str, conn) -> dict:
    """Query all intelligence sources for this workspace. Returns empty keys
    gracefully when no data is present."""

    result: dict[str, Any] = {
        "yt_topic_clusters": [],
        "yt_breakout_recipe": None,
        "yt_channel_profiles": [],
        "yt_ai_features_summary": {},
        "own_top_videos": [],
        "yt_growth_recipe": None,
        "meta_kpi": {},
        "google_kpi": {},
        "auction_insights": [],
        "search_terms": [],
        "comment_intel": {},
    }

    try:
        with conn.cursor() as cur:

            # ── YT topic clusters (workspace-wide, all channels) ─────────────
            cur.execute(
                """
                SELECT topic_name, avg_velocity, hit_rate, shelf_life,
                       cluster_size, trs_score, subthemes
                FROM yt_topic_clusters
                WHERE workspace_id = %s
                ORDER BY trs_score DESC, avg_velocity DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["yt_topic_clusters"] = [
                {
                    "topic_name": r[0],
                    "avg_velocity": float(r[1] or 0),
                    "hit_rate": float(r[2] or 0),
                    "shelf_life": r[3],
                    "cluster_size": r[4],
                    "trs_score": r[5],
                    "subthemes": r[6] if isinstance(r[6], list) else [],
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[growth_os] yt_topic_clusters query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── YT breakout recipe ───────────────────────────────────────────
            cur.execute(
                """
                SELECT playbook_text, top_features, p90_threshold, breakout_count
                FROM yt_breakout_recipe
                WHERE workspace_id = %s
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if row:
                result["yt_breakout_recipe"] = {
                    "playbook_text": row[0],
                    "top_features": row[1] or {},
                    "p90_threshold": float(row[2] or 0),
                    "breakout_count": row[3],
                }
    except Exception as e:
        print(f"[growth_os] yt_breakout_recipe query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── YT channel profiles (competitor cadence data) ────────────────
            cur.execute(
                """
                SELECT channel_id, cadence_pattern, median_gap_days, breakout_rate,
                       hit_rate, risk_profile, median_velocity
                FROM yt_channel_profiles
                WHERE workspace_id = %s
                ORDER BY breakout_rate DESC
                LIMIT 5
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["yt_channel_profiles"] = [
                {
                    "channel_id": r[0],
                    "cadence_pattern": r[1],
                    "median_gap_days": float(r[2] or 0),
                    "breakout_rate": float(r[3] or 0),
                    "hit_rate": float(r[4] or 0),
                    "risk_profile": r[5],
                    "median_velocity": float(r[6] or 0),
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[growth_os] yt_channel_profiles query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── YT AI features aggregate ────────────────────────────────────
            cur.execute(
                """
                SELECT format_label, COUNT(*) as cnt,
                       AVG(curiosity_score) as avg_curiosity,
                       AVG(specificity_score) as avg_specificity
                FROM yt_ai_features
                WHERE workspace_id = %s AND format_label IS NOT NULL
                GROUP BY format_label
                ORDER BY cnt DESC
                LIMIT 5
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["yt_ai_features_summary"]["top_formats"] = [
                {
                    "format_label": r[0],
                    "count": r[1],
                    "avg_curiosity": float(r[2] or 0),
                    "avg_specificity": float(r[3] or 0),
                }
                for r in rows
            ]

            cur.execute(
                """
                SELECT thumb_emotion, COUNT(*) as cnt
                FROM yt_ai_features
                WHERE workspace_id = %s AND thumb_emotion IS NOT NULL
                GROUP BY thumb_emotion
                ORDER BY cnt DESC
                LIMIT 3
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["yt_ai_features_summary"]["top_thumb_emotions"] = [
                {"emotion": r[0], "count": r[1]} for r in rows
            ]
    except Exception as e:
        print(f"[growth_os] yt_ai_features query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── Own top videos ───────────────────────────────────────────────
            cur.execute(
                """
                SELECT title, views, likes, comments, velocity, format_label, is_short
                FROM yt_own_channel_snapshot
                WHERE workspace_id = %s
                ORDER BY views DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["own_top_videos"] = [
                {
                    "title": r[0],
                    "views": r[1],
                    "likes": r[2],
                    "comments": r[3],
                    "velocity": float(r[4] or 0),
                    "format_label": r[5],
                    "is_short": r[6],
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[growth_os] own_top_videos query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── YT growth recipe ─────────────────────────────────────────────
            cur.execute(
                """
                SELECT plan_15d, plan_30d, thumbnail_brief, hooks_library,
                       emerging_topics, own_velocity_percentile, content_gaps
                FROM yt_growth_recipe
                WHERE workspace_id = %s
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if row:
                result["yt_growth_recipe"] = {
                    "plan_15d": row[0],
                    "plan_30d": row[1],
                    "thumbnail_brief": row[2],
                    "hooks_library": row[3],
                    "emerging_topics": row[4],
                    "own_velocity_percentile": float(row[5] or 0),
                    "content_gaps": row[6] or [],
                }
    except Exception as e:
        print(f"[growth_os] yt_growth_recipe query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── Meta KPI (last 30d) ──────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    SUM(spend)          AS total_spend,
                    SUM(revenue)        AS total_revenue,
                    AVG(roas)           AS avg_roas,
                    AVG(ctr)            AS avg_ctr,
                    AVG(cpc)            AS avg_cpc,
                    SUM(impressions)    AS total_impressions,
                    SUM(clicks)         AS total_clicks,
                    SUM(conversions)    AS total_conversions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND platform = 'meta'
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '30 days'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                result["meta_kpi"] = {
                    "total_spend": float(row[0] or 0),
                    "total_revenue": float(row[1] or 0),
                    "avg_roas": float(row[2] or 0),
                    "avg_ctr": float(row[3] or 0),
                    "avg_cpc": float(row[4] or 0),
                    "total_impressions": int(row[5] or 0),
                    "total_clicks": int(row[6] or 0),
                    "total_conversions": int(row[7] or 0),
                }
    except Exception as e:
        print(f"[growth_os] meta_kpi query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── Google KPI (last 30d) ────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    SUM(spend)          AS total_spend,
                    AVG(roas)           AS avg_roas,
                    AVG(ctr)            AS avg_ctr,
                    SUM(impressions)    AS total_impressions,
                    SUM(clicks)         AS total_clicks,
                    SUM(conversions)    AS total_conversions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND platform IN ('google', 'google_ads')
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '30 days'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                result["google_kpi"] = {
                    "total_spend": float(row[0] or 0),
                    "avg_roas": float(row[1] or 0),
                    "avg_ctr": float(row[2] or 0),
                    "total_impressions": int(row[3] or 0),
                    "total_clicks": int(row[4] or 0),
                    "total_conversions": int(row[5] or 0),
                }
    except Exception as e:
        print(f"[growth_os] google_kpi query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── Auction insights (top 5 competitors) ────────────────────────
            cur.execute(
                """
                SELECT competitor_domain, AVG(impression_share) AS avg_is,
                       AVG(overlap_rate) AS avg_overlap,
                       AVG(position_above_rate) AS avg_position_above
                FROM google_auction_insights
                WHERE workspace_id = %s
                GROUP BY competitor_domain
                ORDER BY avg_is DESC
                LIMIT 5
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["auction_insights"] = [
                {
                    "domain": r[0],
                    "impression_share": float(r[1] or 0),
                    "overlap_rate": float(r[2] or 0),
                    "position_above_rate": float(r[3] or 0),
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[growth_os] auction_insights query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── Top search terms ─────────────────────────────────────────────
            cur.execute(
                """
                SELECT entity_name, SUM(clicks) AS total_clicks,
                       AVG(ctr) AS avg_ctr, SUM(conversions) AS total_conv
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'search_term'
                  AND hour_ts >= NOW() - INTERVAL '30 days'
                  AND entity_name IS NOT NULL
                GROUP BY entity_name
                ORDER BY total_clicks DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            result["search_terms"] = [
                {
                    "term": r[0],
                    "clicks": int(r[1] or 0),
                    "ctr": float(r[2] or 0),
                    "conversions": float(r[3] or 0),
                }
                for r in rows
            ]
    except Exception as e:
        print(f"[growth_os] search_terms query failed: {e}")

    try:
        with conn.cursor() as cur:
            # ── Comment intel (pain + winning terms from raw_json) ───────────
            cur.execute(
                """
                SELECT raw_json
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'comment_intel'
                ORDER BY hour_ts DESC
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                result["comment_intel"] = row[0] if isinstance(row[0], dict) else {}
    except Exception as e:
        print(f"[growth_os] comment_intel query failed: {e}")

    return result


# ── Claude prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are the Growth OS engine for an AI ad agency SaaS platform.
Your job is to synthesise cross-platform intelligence into a prioritised
action plan for the brand.

Rules:
1. Return ONLY a valid JSON object — no markdown, no prose, no code fences.
2. The JSON object must have exactly two keys: "relevant_modules" and "actions".
3. Generate exactly 12–15 action objects in the "actions" array.
4. Each action MUST have all required fields (see schema below).
5. Base every "rationale" on specific data from the intelligence provided.
6. Use the EXACT impact/effort values: "high", "medium", "low".
7. Use the EXACT platform values: "youtube", "meta", "google", "all".
8. Use the EXACT action_type values: "new_creative", "create_campaign",
   "keyword_addition", "review".
9. If a STRATEGIC DIRECTIVE is provided, ALL actions must serve that directive.
   Weight your action selection, channels, and priorities accordingly.
10. "relevant_modules" must be a JSON array of strings from this list ONLY:
    ["youtube", "meta", "google_ads", "marketplace", "app_growth", "seo",
     "email", "competitor_intel", "campaign_planner", "products",
     "organic_posts", "search_trends"]
    Include only modules that are actually relevant to this workspace's data
    and strategy. A new workspace with no data should get: ["youtube", "seo"].

Schema:
{
  "relevant_modules": ["module1", "module2", ...],
  "actions": [
    {
      "id": "<uuid4 string>",
      "platform": "youtube|meta|google|all",
      "action_type": "new_creative|create_campaign|keyword_addition|review",
      "title": "<short imperative title, ≤10 words>",
      "rationale": "<1-2 sentences citing specific data>",
      "source": "yt_competitor_intel|meta_performance|google_ads|search_trends|comment_intel|all",
      "source_detail": "<e.g. Topic cluster: ECG Home · hit_rate 89%>",
      "impact": "high|medium|low",
      "effort": "low|medium|high",
      "creative_brief": "<Hook: ...\\nBody: ...\\nCTA: ...\\nVisual: ...>",
      "setup_guide": "<Step 1: ...\\nStep 2: ...\\nStep 3: ...>",
      "action_data": {}
    }
  ]
}

For "creative_brief": Write a concise creative brief for each action. Format:
Hook: <attention-grabbing opening line or ad hook>
Body: <core message / value proposition>
CTA: <call to action text>
Visual: <visual direction — what to show on screen/image>

For "setup_guide": Write step-by-step implementation instructions.
Step 1: <first concrete action>
Step 2: <second action>
Step 3: <third action>
(Add more steps if needed)
"""


def _build_prompt(intel: dict, directive: str = None, strategy_mode: str = None) -> str:
    lines = []

    # ── Strategic Directive block (user-defined focus) ──────────────────────────
    if directive and directive.strip():
        mode_label = {
            "scale": "🚀 SCALE MODE",
            "efficiency": "⚡ EFFICIENCY MODE",
            "launch": "🆕 PRODUCT LAUNCH MODE",
            "seasonal": "📅 SEASONAL PUSH MODE",
            "custom": "🎯 CUSTOM DIRECTIVE",
        }.get(strategy_mode or "", "🎯 STRATEGIC DIRECTIVE")

        lines.append(f"=== {mode_label} — HIGHEST PRIORITY ===")
        lines.append(directive.strip())
        lines.append(
            "\nCRITICAL: Every action you generate MUST directly serve this directive. "
            "Heavily weight channels, action types, and priorities toward fulfilling this goal. "
            "Ignore data signals that conflict with this directive.\n"
        )

    # Detect new/empty workspace — all intelligence sources are empty
    all_empty = not any([
        intel.get("meta_performance"),
        intel.get("google_ads"),
        intel.get("yt_channel_stats"),
        intel.get("yt_competitor_intel"),
        intel.get("search_trends"),
        intel.get("comment_intel"),
    ])
    if all_empty:
        lines.append(
            "=== NEW WORKSPACE CONTEXT ===\n"
            "This brand has JUST signed up and has no connected ad accounts or data yet. "
            "Your job is to generate a SETUP ROADMAP — concrete first steps to get value fast. "
            "Focus actions on: (1) what to connect first, (2) what data to upload, "
            "(3) what early wins to chase in week 1. "
            "Use the competitor context (if any) to make recommendations specific to their niche. "
            "Every action should help them get started, not optimise existing campaigns.\n"
        )

    lines.append("Here is the cross-platform intelligence for this brand:\n")

    # YT topics
    if intel.get("yt_topic_clusters"):
        lines.append("=== YouTube Competitor Topic Clusters ===")
        for t in intel["yt_topic_clusters"][:5]:
            lines.append(
                f"• {t['topic_name']}: hit_rate={t['hit_rate']:.0f}%, "
                f"avg_velocity={t['avg_velocity']:.0f} views/day, "
                f"shelf_life={t['shelf_life'] or 'unknown'}, "
                f"trs_score={t['trs_score']}"
            )

    # Breakout recipe
    if intel.get("yt_breakout_recipe"):
        br = intel["yt_breakout_recipe"]
        lines.append("\n=== YouTube Breakout Recipe (ML model) ===")
        lines.append(f"P90 velocity threshold: {br['p90_threshold']:.0f} views/day")
        lines.append(f"Top features: {json.dumps(br['top_features'])}")
        if br.get("playbook_text"):
            lines.append(f"Playbook summary: {br['playbook_text'][:400]}")

    # Channel cadence
    if intel.get("yt_channel_profiles"):
        lines.append("\n=== Competitor Upload Cadence ===")
        for cp in intel["yt_channel_profiles"][:3]:
            lines.append(
                f"• {cp['cadence_pattern'] or 'unknown'}: "
                f"every {cp['median_gap_days']:.0f}d, "
                f"breakout_rate={cp['breakout_rate']:.0f}%"
            )

    # AI format summary
    top_formats = (intel.get("yt_ai_features_summary") or {}).get("top_formats", [])
    if top_formats:
        lines.append("\n=== Top Competitor Video Formats ===")
        for f in top_formats[:3]:
            lines.append(
                f"• {f['format_label']}: {f['count']} videos, "
                f"curiosity={f['avg_curiosity']:.1f}/10, "
                f"specificity={f['avg_specificity']:.1f}/10"
            )

    # Own top videos
    if intel.get("own_top_videos"):
        lines.append("\n=== Own Top Videos ===")
        for v in intel["own_top_videos"][:5]:
            lines.append(
                f"• \"{v['title'][:60]}\": {v['views']:,} views, "
                f"velocity={v['velocity']:.0f}/day, format={v['format_label'] or 'unknown'}"
            )

    # Growth recipe highlights
    if intel.get("yt_growth_recipe"):
        gr = intel["yt_growth_recipe"]
        lines.append("\n=== Own Channel Growth Recipe ===")
        lines.append(
            f"Own velocity percentile vs competitors: {gr['own_velocity_percentile']:.0f}th"
        )
        if gr.get("emerging_topics"):
            lines.append(f"Emerging topics: {gr['emerging_topics'][:300]}")
        if gr.get("hooks_library"):
            lines.append(f"Winning hooks: {gr['hooks_library'][:300]}")

    # Meta KPI
    if intel.get("meta_kpi"):
        mk = intel["meta_kpi"]
        lines.append("\n=== Meta Ads (last 30 days) ===")
        lines.append(
            f"Spend: ₹{mk['total_spend']:,.0f}, Revenue: ₹{mk['total_revenue']:,.0f}, "
            f"ROAS: {mk['avg_roas']:.2f}, CTR: {mk['avg_ctr']:.2f}%, "
            f"CPC: ₹{mk['avg_cpc']:.0f}"
        )

    # Google KPI
    if intel.get("google_kpi"):
        gk = intel["google_kpi"]
        lines.append("\n=== Google Ads (last 30 days) ===")
        lines.append(
            f"Spend: ₹{gk['total_spend']:,.0f}, ROAS: {gk['avg_roas']:.2f}, "
            f"CTR: {gk['avg_ctr']:.2f}%, Conversions: {gk['total_conversions']}"
        )

    # Auction insights
    if intel.get("auction_insights"):
        lines.append("\n=== Google Auction Insights (Top Competitors) ===")
        for ai in intel["auction_insights"][:3]:
            lines.append(
                f"• {ai['domain']}: impression_share={ai['impression_share']:.0f}%, "
                f"overlap_rate={ai['overlap_rate']:.0f}%, "
                f"position_above_rate={ai['position_above_rate']:.0f}%"
            )

    # Search terms
    if intel.get("search_terms"):
        lines.append("\n=== Top Search Terms ===")
        for st in intel["search_terms"][:8]:
            lines.append(
                f"• \"{st['term']}\": {st['clicks']} clicks, "
                f"CTR={st['ctr']:.1f}%, conv={st['conversions']:.0f}"
            )

    # Comment intel
    if intel.get("comment_intel"):
        ci = intel["comment_intel"]
        if ci.get("pain_terms"):
            lines.append(f"\n=== Customer Pain Points (from comments) ===")
            lines.append(", ".join(ci["pain_terms"][:10]))
        if ci.get("winning_terms"):
            lines.append(f"=== Winning Messages ===")
            lines.append(", ".join(ci["winning_terms"][:10]))

    closing = (
        "\nNow generate 12-15 cross-platform growth actions as a JSON array. "
        "Prioritise high-confidence, high-data-backed actions. "
        "Balance YouTube content (new_creative/review), Meta campaigns "
        "(create_campaign), and Google keywords (keyword_addition). "
        "Make each action specific and immediately actionable."
    )
    if directive and directive.strip():
        closing += (
            f" Remember: the Strategic Directive is '{directive.strip()[:100]}' — "
            "ensure every action contributes to this goal."
        )
    lines.append(closing)

    return "\n".join(lines)


# ── Plan generation ────────────────────────────────────────────────────────────

def generate_action_plan(workspace_id: str, conn, directive: str = None, strategy_mode: str = None) -> dict:
    """Gather intelligence, call Claude, upsert plan into DB, return plan dict.

    directive:      Optional free-text strategic focus from the user.
    strategy_mode:  One of scale|efficiency|launch|seasonal|custom (used for UI labelling).
    """

    intel = gather_intelligence(workspace_id, conn)

    # Determine which sources have data
    sources_used = {
        "yt_competitor_intel": bool(intel.get("yt_topic_clusters")),
        "yt_breakout_recipe": bool(intel.get("yt_breakout_recipe")),
        "yt_own_channel": bool(intel.get("own_top_videos")),
        "yt_growth_recipe": bool(intel.get("yt_growth_recipe")),
        "meta_performance": bool(intel.get("meta_kpi")),
        "google_ads": bool(intel.get("google_kpi")),
        "competitor_auction": bool(intel.get("auction_insights")),
        "search_trends": bool(intel.get("search_terms")),
        "comment_intel": bool(intel.get("comment_intel")),
    }

    # Always call Claude — _build_prompt handles the new-workspace case with
    # a "NEW WORKSPACE CONTEXT" block that tells Claude to generate a setup roadmap
    relevant_modules = []
    actions = []
    prompt = _build_prompt(intel, directive=directive, strategy_mode=strategy_mode)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        msg = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip potential markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        # Extract JSON object — find first { ... } block
        start = raw.find("{")
        if start == -1:
            start = raw.find("[")
        if start != -1:
            raw = raw[start:]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            actions = parsed
            relevant_modules = []
        else:
            actions = parsed.get("actions", [])
            relevant_modules = parsed.get("relevant_modules", [])
    except Exception as e:
        print(f"[growth_os] Claude call failed: {e}")
        print(f"[growth_os] raw response (first 500 chars): {raw[:500] if 'raw' in dir() else 'N/A'}")
        actions = []
        relevant_modules = []

    # Ensure each action has a uuid id
    for a in actions:
        if not a.get("id"):
            a["id"] = str(uuid.uuid4())

    # Upsert into growth_os_plans
    plan_id = str(uuid.uuid4())
    plan_json = {"actions": actions, "relevant_modules": relevant_modules}
    generated_at = datetime.now(timezone.utc).isoformat()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO growth_os_plans
                    (id, workspace_id, plan_json, sources_used, directive, strategy_mode)
                VALUES (%s::uuid, %s::uuid, %s::jsonb, %s::jsonb, %s, %s)
                """,
                (
                    plan_id, workspace_id,
                    json.dumps(plan_json), json.dumps(sources_used),
                    (directive or "").strip(),
                    strategy_mode or "",
                ),
            )
        conn.commit()
    except Exception as e:
        print(f"[growth_os] DB upsert failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return {
        "plan_id": plan_id,
        "generated_at": generated_at,
        "actions": actions,
        "sources_used": sources_used,
        "directive": (directive or "").strip(),
        "strategy_mode": strategy_mode or "",
        "relevant_modules": relevant_modules,
    }


# ── Send to approvals ──────────────────────────────────────────────────────────

def send_action_to_approvals(workspace_id: str, action: dict, conn) -> str:
    """Insert a Growth OS action into action_log as a pending approval.

    Returns the new action_log id (str).
    """
    platform = action.get("platform", "all")
    action_type = action.get("action_type", "review")
    title = action.get("title", "Growth OS action")

    # Build the new_value JSONB payload stored in action_log
    new_value = {
        "growth_os_action_id": action.get("id"),
        "title": title,
        "rationale": action.get("rationale", ""),
        "source": action.get("source", ""),
        "source_detail": action.get("source_detail", ""),
        "impact": action.get("impact", "medium"),
        "effort": action.get("effort", "medium"),
        "description": f"{title}\n\n{action.get('rationale', '')}",
        **(action.get("action_data") or {}),
    }

    action_log_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO action_log
                    (workspace_id, platform, account_id, entity_level, entity_id,
                     action_type, new_value, triggered_by, status)
                VALUES (%s, %s, 'growth_os', 'growth_os', 'growth_os',
                        %s, %s::jsonb, 'growth_os', 'pending')
                RETURNING id
                """,
                (workspace_id, platform, action_type, json.dumps(new_value)),
            )
            row = cur.fetchone()
            action_log_id = str(row[0]) if row else None
        conn.commit()
    except Exception as e:
        print(f"[growth_os] send_action_to_approvals failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return action_log_id or ""
