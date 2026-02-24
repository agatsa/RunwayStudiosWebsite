# services/ingestion_service/utils/timewindows.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

@dataclass
class SyncWindow:
    start: datetime
    end: datetime

def floor_to_hour(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)

def compute_window(
    last_success_end: datetime | None,
    overlap_hours: int = 2,
    max_window_hours: int = 6,
    freshness_lag_minutes: int = 15,
) -> SyncWindow:
    """
    Window strategy:
    - end = floor_to_hour(now - freshness_lag)
    - start = max(last_success_end - overlap, end - max_window)
    - overlap ensures delayed attribution is corrected
    """
    now = datetime.now(timezone.utc)
    end = floor_to_hour(now - timedelta(minutes=freshness_lag_minutes))

    max_start = end - timedelta(hours=max_window_hours)
    if last_success_end is None:
        start = max_start
    else:
        start = max(last_success_end - timedelta(hours=overlap_hours), max_start)

    if start >= end:
        start = end - timedelta(hours=1)

    return SyncWindow(start=start, end=end)