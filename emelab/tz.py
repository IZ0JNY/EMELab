# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Local time of a station from its position: the real time zone (timezonefinder + tzdata, offline) or, without
them, solar time rounded to the hour (then marked as assumed)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache


@lru_cache(maxsize=1)
def _finder():
    try:
        from timezonefinder import TimezoneFinder
        return TimezoneFinder()
    except Exception:
        return None


@lru_cache(maxsize=512)
def zone_name(lat: float, lon: float) -> str | None:
    f = _finder()
    if f is None:
        return None
    try:
        return f.timezone_at(lat=lat, lng=lon) or f.certain_timezone_at(lat=lat, lng=lon)
    except Exception:
        return None


def local_time(lat: float, lon: float, utc: datetime) -> tuple[datetime, str, bool]:
    """(local time, zone label, assumed). The label is the IANA zone (e.g. Europe/Prague) or "UTC±h"."""
    utc = utc if utc.tzinfo else utc.replace(tzinfo=timezone.utc)
    name = zone_name(round(lat, 3), round(lon, 3))
    if name:
        try:
            from zoneinfo import ZoneInfo
            return utc.astimezone(ZoneInfo(name)), name, False
        except Exception:
            pass
    h = round(lon / 15)
    return utc.astimezone(timezone(timedelta(hours=h))), f"UTC{h:+d}", True
