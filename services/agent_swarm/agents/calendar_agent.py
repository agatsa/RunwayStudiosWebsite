# services/agent_swarm/agents/calendar_agent.py
"""
Agent 5 — Occasion / Calendar Agent
Returns upcoming Indian festivals, salary days, health awareness days
for the next 14 days. Injects into creative_director context.
"""
from datetime import date, timedelta


# Static Indian festival calendar 2026 (extend yearly)
FESTIVALS_2026 = {
    date(2026, 1, 14): ("Makar Sankranti / Lohri", "harvest", "high"),
    date(2026, 1, 26): ("Republic Day", "national", "medium"),
    date(2026, 2, 14): ("Valentine's Day", "gifting", "high"),
    date(2026, 3, 6):  ("Maha Shivratri", "religious", "medium"),
    date(2026, 3, 20): ("Holi", "festival", "high"),
    date(2026, 3, 30): ("Ram Navami", "religious", "medium"),
    date(2026, 4, 6):  ("Ugadi / Gudi Padwa", "new_year", "high"),
    date(2026, 4, 14): ("Baisakhi / Tamil New Year", "harvest", "high"),
    date(2026, 4, 18): ("Good Friday", "religious", "low"),
    date(2026, 4, 20): ("Easter", "religious", "low"),
    date(2026, 5, 9):  ("Mother's Day", "gifting", "high"),
    date(2026, 5, 14): ("Eid al-Adha (approx)", "religious", "high"),
    date(2026, 6, 5):  ("World Environment Day", "awareness", "medium"),
    date(2026, 6, 21): ("International Yoga Day", "health", "high"),
    date(2026, 6, 22): ("Father's Day", "gifting", "high"),
    date(2026, 7, 4):  ("Guru Purnima", "spiritual", "medium"),
    date(2026, 8, 15): ("Independence Day", "national", "high"),
    date(2026, 8, 27): ("Onam (approx)", "harvest", "medium"),
    date(2026, 9, 5):  ("Teachers' Day", "appreciation", "medium"),
    date(2026, 9, 10): ("Ganesh Chaturthi (approx)", "festival", "high"),
    date(2026, 10, 2): ("Gandhi Jayanti / Navratri start", "national", "medium"),
    date(2026, 10, 20): ("Dussehra (approx)", "festival", "high"),
    date(2026, 10, 31): ("Diwali (approx)", "festival", "very_high"),
    date(2026, 11, 1):  ("Diwali Day 2", "festival", "very_high"),
    date(2026, 11, 2):  ("Bhai Dooj", "festival", "high"),
    date(2026, 11, 14): ("Children's Day", "awareness", "medium"),
    date(2026, 12, 25): ("Christmas", "gifting", "high"),
    date(2026, 12, 31): ("New Year's Eve", "celebration", "high"),
}

# Health awareness days (always useful for health/wellness brands)
HEALTH_DAYS_2026 = {
    date(2026, 2, 4):  "World Cancer Day",
    date(2026, 3, 8):  "International Women's Day",
    date(2026, 3, 24): "World TB Day",
    date(2026, 4, 7):  "World Health Day",
    date(2026, 5, 31): "World No Tobacco Day",
    date(2026, 6, 5):  "World Environment Day",
    date(2026, 9, 10): "World Suicide Prevention Day",
    date(2026, 10, 10): "World Mental Health Day",
    date(2026, 11, 14): "World Diabetes Day",
}


def _salary_days_near(today: date, horizon_days: int = 14) -> list[dict]:
    """Indian salary cycle: 1st and 7th of each month."""
    result = []
    for delta in range(horizon_days + 1):
        d = today + timedelta(days=delta)
        if d.day in (1, 2, 7, 8):
            result.append({
                "date": str(d),
                "occasion": "Salary Day window" if d.day in (1, 2) else "Post-salary spend window",
                "category": "salary",
                "importance": "high",
                "days_away": delta,
            })
    return result


def get_upcoming_occasions(horizon_days: int = 14) -> dict:
    today = date.today()
    horizon_end = today + timedelta(days=horizon_days)

    occasions = []

    # Festivals
    for d, (name, category, importance) in FESTIVALS_2026.items():
        if today <= d <= horizon_end:
            occasions.append({
                "date": str(d),
                "occasion": name,
                "category": category,
                "importance": importance,
                "days_away": (d - today).days,
            })

    # Health days
    for d, name in HEALTH_DAYS_2026.items():
        if today <= d <= horizon_end:
            occasions.append({
                "date": str(d),
                "occasion": name,
                "category": "health_awareness",
                "importance": "medium",
                "days_away": (d - today).days,
            })

    # Salary days
    occasions.extend(_salary_days_near(today, horizon_days))

    # Weekend peaks
    for delta in range(horizon_days + 1):
        d = today + timedelta(days=delta)
        if d.weekday() == 5:   # Saturday
            occasions.append({
                "date": str(d),
                "occasion": "Weekend peak (Sat-Sun)",
                "category": "weekend",
                "importance": "medium",
                "days_away": delta,
            })

    occasions.sort(key=lambda x: x["days_away"])

    # Top 3 high-priority
    top = [o for o in occasions if o["importance"] in ("high", "very_high")][:3]

    return {
        "today": str(today),
        "horizon_days": horizon_days,
        "upcoming_occasions": occasions,
        "top_priority": top,
        "creative_context": _build_creative_context(top, occasions),
    }


def _build_creative_context(top: list[dict], all_occasions: list[dict]) -> str:
    if not top and not all_occasions:
        return "No major occasions in the next 14 days. Focus on evergreen performance creatives."

    lines = []
    if top:
        lines.append("🗓 UPCOMING HIGH-PRIORITY OCCASIONS:")
        for o in top:
            lines.append(f"  • {o['occasion']} ({o['date']}, {o['days_away']} days away) — {o['category']}")
    else:
        lines.append("No very high priority occasions upcoming.")

    if all_occasions:
        lines.append(f"\nTotal occasions in window: {len(all_occasions)}")

    lines.append("\nCreative angle suggestions:")
    for o in top[:2]:
        cat = o["category"]
        if cat == "gifting":
            lines.append(f"  → {o['occasion']}: Gift angle, bundling, emotional messaging")
        elif cat == "festival":
            lines.append(f"  → {o['occasion']}: Festive offer, limited time, celebration")
        elif cat == "salary":
            lines.append(f"  → {o['occasion']}: EMI offer, value messaging, 'treat yourself'")
        elif cat == "health_awareness":
            lines.append(f"  → {o['occasion']}: Educational angle, awareness, product benefit")
        elif cat == "national":
            lines.append(f"  → {o['occasion']}: Pride angle, Made in India, national themes")
        else:
            lines.append(f"  → {o['occasion']}: Seasonal relevance, timely offer")

    return "\n".join(lines)
