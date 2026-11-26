# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Echo mode of WSJT-X (2.6 and later): the measurements it writes to all_echo.txt, next to WSJT-X.ini.

Since WSJT-X 2.6 the Echo mode integrates the echo power over the whole spread, so its S/N is right also for the
widely spread echoes of 10 GHz and up (DL3WDG, «Using WSJT-X for Microwave EME», EME 2022). One line per echo cycle:

    261027_203030  20.5083  64.07   43664   249.7  -0.3     1     0    -53  -17.7     1.5    0

date_time (YYMMDD_HHMMSS UTC), UTC in hours, Level (audio level, dB), Doppler (Hz), Width (Hz, from Astro),
Dgrd (dB, from Astro), N (cycles averaged), Q (quality 0–10), DF (Hz from 1500 Hz), SNR (dB in 2500 Hz; −99 = no
echo found), dBerr (estimated error of SNR), and a last column that EMELab ignores.

A run starts again when N goes back or after a pause; its result is the average of the last cycles, once SNR and
dBerr have settled (the first echoes can be too strong because of libration peaks). Read-only: EMELab never writes
the file nor tells WSJT-X to transmit."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

NO_ECHO = -99.0
BW_REF_HZ = 2500.0                     # WSJT-X S/N reference bandwidth
TAIL = 5                               # cycles averaged for the result of a run
GAP_S = 60.0                           # a pause longer than this starts a new run


def find(ini_path: str | Path | None = None) -> Path | None:
    """all_echo.txt in the WSJT-X folder (the one of WSJT-X.ini / wsjtx_log.adi)."""
    try:
        from . import wsjtx_ini
        p = Path(ini_path) if ini_path else wsjtx_ini.find()
    except Exception:
        return None
    if not p:
        return None
    f = (p if p.is_dir() else p.parent) / "all_echo.txt"
    return f if f.is_file() else None


def parse(text: str) -> list[dict]:
    """One dict per echo cycle; lines that do not look like Echo output are skipped."""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) < 11 or "_" not in f[0]:
            continue
        try:
            t = datetime.strptime(f[0], "%y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
            out.append({"utc": t, "level": float(f[2]), "doppler_hz": float(f[3]), "width_hz": float(f[4]),
                        "dgrd_db": float(f[5]), "n": int(f[6]), "q": int(f[7]), "df_hz": float(f[8]),
                        "snr_db": float(f[9]), "dberr_db": float(f[10])})
        except ValueError:
            continue
    return out


def runs(rows: list[dict], gap_s: float = GAP_S) -> list[list[dict]]:
    """Consecutive cycles of one measurement: a new run when N does not grow or after a pause."""
    out, cur = [], []
    for r in rows:
        if cur and (r["n"] <= cur[-1]["n"] or (r["utc"] - cur[-1]["utc"]).total_seconds() > gap_s):
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def to_1hz(snr_2500_db: float) -> float:
    """S/N in 2500 Hz (WSJT-X) → S/N in 1 Hz (EMELab's own-echo figure)."""
    return snr_2500_db + 10 * math.log10(BW_REF_HZ)


def summary(run: list[dict], tail: int = TAIL) -> dict:
    """Result of one run: start, end, cycles, mean Width/Doppler, and S/N as the mean of the last `tail` cycles with
    an echo (None when WSJT-X never found one)."""
    good = [r for r in run if r["snr_db"] > NO_ECHO + 1]
    last = good[-tail:]
    snr = sum(r["snr_db"] for r in last) / len(last) if last else None
    mid = run[len(run) // 2]["utc"]
    return {"start": run[0]["utc"], "end": run[-1]["utc"], "mid": mid, "cycles": run[-1]["n"] - run[0]["n"] + 1,
            "width_hz": sum(r["width_hz"] for r in run) / len(run),
            "doppler_hz": sum(r["doppler_hz"] for r in run) / len(run), "dgrd_db": run[-1]["dgrd_db"],
            "snr_db": snr, "snr_1hz_db": to_1hz(snr) if snr is not None else None,
            "dberr_db": last[-1]["dberr_db"] if last else None, "q": max(r["q"] for r in run),
            "settled": bool(last) and len(last) >= tail and last[-1]["dberr_db"] <= 1.0,
            "echo": snr is not None}


def read(path: str | Path) -> list[dict]:
    """Summaries of every run in the file, newest first ([] when the file cannot be read)."""
    try:
        rows = parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    return [summary(r) for r in reversed(runs(rows))]
