# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Receiver level for the Y factor from SDR Console (sdr-radio.com) in Continuum mode.

SDR Console has no live data output for the level, but its Signal History / Continuum display exports a CSV:

    # SDR Console version 3.4 build 4138 : Continuum Mode
    # Created   : 26/11/2026 09:56:22          ← local time of the PC
    # Interval  : 50 ms
    # Level     : dBm
    # Date      : UTC
    …
    "Time","Level","Frequency","Bandwidth"
    08:54:06.800,-79.04,,24048116.-776,1300    ← time UTC, level dBm, (empty), frequency kHz, bandwidth kHz

(the rows carry one more field than the header, and the frequency is written as «24048116.-776»: both are read as
they are). EMELab only reads the file. With the cold sky and the source (Sun, Moon, ground) in the same recording,
Y = level on the source − level on cold sky, both as averages over a time window."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _num(x: str) -> float | None:
    x = (x or "").strip().strip('"')
    if not x:
        return None
    x = x.replace(".-", ".")                     # «24048116.-776» as exported by build 4138
    try:
        return float(x)
    except ValueError:
        return None


def _created(meta: dict) -> datetime | None:
    v = meta.get("created")
    for fmt in ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt)
        except (TypeError, ValueError):
            continue
    return None


def parse(text: str, day: date | None = None) -> dict:
    """{"meta": {...header in lower case...}, "samples": [(utc datetime, level, freq_mhz, bw_khz)…], "unit": "dBm"}.

    The rows only carry the time of day: the date comes from «Created» (local time of the PC, so it can be the day
    after the UTC date near midnight), or from `day`. A time going backwards means midnight was passed."""
    meta, rows = {}, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*([^:]+?)\s*:\s*(.*)$", line)
            if "sdr console" in line.lower():
                meta.setdefault("program", line.lstrip("# ").strip())
            elif m:
                meta[m.group(1).strip().lower()] = m.group(2).strip()
            continue
        f = line.split(",")
        m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$", f[0].strip().strip('"'))
        if not m:
            continue                                  # header row «"Time","Level",…»
        lvl = _num(f[1]) if len(f) > 1 else None
        if lvl is None:
            continue
        nums = [_num(x) for x in f[2:]]
        nums = [v for v in nums if v is not None]
        freq_khz = nums[0] if nums else None
        bw = nums[1] if len(nums) > 1 else None
        sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        rows.append((sec, lvl, freq_khz / 1000.0 if freq_khz else None, bw))
    if day is None:
        cr = _created(meta)
        if cr is not None:
            day = cr.date()
            if rows and rows[0][0] - (cr.hour * 3600 + cr.minute * 60 + cr.second) > 12 * 3600:
                day -= timedelta(days=1)            # Created is local time and already past midnight
        else:
            day = datetime.now(timezone.utc).date()
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    out, add, prev = [], 0.0, None
    for sec, lvl, fmhz, bw in rows:
        if prev is not None and sec < prev - 3600:
            add += 86400.0
        prev = sec
        out.append((base + timedelta(seconds=sec + add), lvl, fmhz, bw))
    return {"meta": meta, "samples": out, "unit": meta.get("level", "dB")}


def read(path: str | Path) -> dict:
    p = Path(path)
    r = parse(p.read_text(encoding="utf-8", errors="replace"))
    r["file"] = str(p)
    return r


def latest_csv(folder: str | Path) -> Path | None:
    """Newest .csv in the folder SDR Console exports to (None when there is none)."""
    d = Path(folder)
    if not d.is_dir():
        return None
    files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() == ".csv"]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def stats(samples, t0: datetime, t1: datetime) -> dict | None:
    """Mean (in dB, as SDR Console shows it), spread and number of samples between t0 and t1."""
    v = [s[1] for s in samples if t0 <= s[0] <= t1]
    if not v:
        return None
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
    return {"db": round(m, 3), "sd": round(sd, 3), "n": len(v), "from": t0, "to": t1,
            "sem": round(sd / math.sqrt(len(v)), 4)}


def smooth(samples, seconds: float = 1.0) -> list[tuple[datetime, float]]:
    """Averages over consecutive blocks of `seconds` (for the plot and the automatic windows)."""
    out, block, t_start = [], [], None
    for t, lvl, *_ in samples:
        if t_start is None:
            t_start = t
        if (t - t_start).total_seconds() >= seconds and block:
            out.append((t_start + (t - t_start) / 2, sum(block) / len(block)))
            block, t_start = [], t
        block.append(lvl)
    if block:
        out.append((t_start, sum(block) / len(block)))
    return out


def auto_windows(samples, cold_s: float = 10.0, hot_s: float = 5.0) -> dict | None:
    """Suggested windows: the quietest `cold_s` seconds (lowest mean) and `hot_s` seconds around the highest level.
    Both stay adjustable in the page."""
    if len(samples) < 4:
        return None
    t = [s[0] for s in samples]
    v = [s[1] for s in samples]
    span = (t[-1] - t[0]).total_seconds()
    cold_s, hot_s = min(cold_s, span / 2 or 1), min(hot_s, span / 2 or 1)

    def best(width, sign):
        j, acc, best_v, best_i = 0, 0.0, None, (0, 0)
        for i in range(len(v)):
            acc += v[i]
            while (t[i] - t[j]).total_seconds() > width:
                acc -= v[j]
                j += 1
            if (t[i] - t[j]).total_seconds() >= width * 0.9:
                m = acc / (i - j + 1)
                if best_v is None or sign * m > sign * best_v:
                    best_v, best_i = m, (j, i)
        return (t[best_i[0]], t[best_i[1]]) if best_v is not None else (t[0], t[-1])
    return {"cold": best(cold_s, -1), "hot": best(hot_s, +1)}


def y_from(samples, cold: tuple, hot: tuple) -> dict:
    """Y (dB) = mean level in the hot window − mean level in the cold window, with its statistical uncertainty."""
    c, h = stats(samples, *cold), stats(samples, *hot)
    if not c or not h:
        return {"cold": c, "hot": h, "y_db": None}
    y = round(h["db"] - c["db"], 3)
    return {"cold": c, "hot": h, "y_db": y, "y_err": round(math.hypot(c["sem"], h["sem"]), 3),
            "noise_sd": max(c["sd"], h["sd"])}
