def render_daily_digest(day, platform, account_id, totals, winners, losers, fatigue_watch, objections=None):
    objections = objections or {}
    lines = []
    lines.append(f"{day} | {platform.upper()} | {account_id}")
    lines.append("")
    lines.append(f"Spend: ₹{totals['spend']:.0f} | Revenue: ₹{totals['revenue']:.0f} | ROAS: {totals['roas']:.2f}")
    lines.append(f"CTR: {totals['ctr']:.2f}% | Conversions: {int(totals['conversions'])} | CPC: ₹{totals['cpc']:.2f}")
    lines.append("")

    lines.append("Top Winners (by ROAS):")
    for w in winners:
        lines.append(f"- {w['entity_level']} {w['entity_id']} | spend ₹{w['spend']:.0f} | roas {w['roas']:.2f} | ctr {w['ctr']:.2f}%")

    lines.append("")
    lines.append("Top Losers (by ROAS):")
    for l in losers:
        lines.append(f"- {l['entity_level']} {l['entity_id']} | spend ₹{l['spend']:.0f} | roas {l['roas']:.2f} | ctr {l['ctr']:.2f}%")

    if fatigue_watch:
        lines.append("")
        lines.append("Fatigue Watchlist:")
        for f in fatigue_watch[:8]:
            lines.append(f"- {f['entity_level']} {f['entity_id']} | fatigue {f['fatigue_score']:.2f} | ctr_ratio {f['fatigue_ctr_ratio']:.2f}")

    if objections:
        lines.append("")
        lines.append("Objections:")
        for k, v in objections.items():
            lines.append(f"- {k}: {v}")

    return "\n".join(lines)