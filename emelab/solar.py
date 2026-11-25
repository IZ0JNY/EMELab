# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Solar flux of the day from the USAF RSTN observatories (San Vito, Learmonth, Sagamore Hill, Palehua, Kaena
Point) published by NOAA SWPC, and the GOES X-ray flux to tell whether the Sun is quiet enough for a sun-noise
calibration (a flare changes the microwave flux within minutes).

Idea from the online sun-noise calculator of Carsten Groen OZ9AAR (moonbounce.dk); code written for EME Assistant.
Interpolation between two RSTN frequencies is a power law in log–log (the "traditional" method)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

RSTN_URL = "https://services.swpc.noaa.gov/json/solar-radio-flux.json"
XRAY_URL = "https://services.swpc.noaa.gov/json/goes/primary/xrays-1-day.json"
LON = {"San Vito": 17.7, "Learmonth": 114.1, "Sagamore Hill": -70.8, "Palehua": -158.1, "Kaena Point": -158.3}


def _get(url):
    from .weather import _get as get
    return json.loads(get(url, 20))


def rstn(data: list | None = None) -> list[dict]:
    """Observations: [{utc, site, flux: {MHz: SFU}, quality: {MHz: text}}], newest first."""
    data = data if data is not None else _get(RSTN_URL)
    out = []
    for o in data:
        try:
            t = datetime.fromisoformat(o["time_tag"].replace("Z", "")).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        fl, q = {}, {}
        for d in o.get("details", []):
            if d.get("flux") is not None:
                fl[int(d["frequency"])] = float(d["flux"])
                q[int(d["frequency"])] = d.get("observed_quality", "")
        out.append({"utc": t, "site": o.get("common_name", ""), "flux": fl, "quality": q})
    return sorted(out, key=lambda o: o["utc"], reverse=True)


def best_15g4(obs: list[dict], lon: float | None = None, max_age_h: float = 36.0) -> dict | None:
    """The 15.4 GHz value to use: good quality, recent, from the observatory closest in longitude (the same
    part of the day, i.e. the Sun as you see it), else the newest good one."""
    now = max((o["utc"] for o in obs), default=datetime.now(timezone.utc))
    good = [o for o in obs if 15400 in o["flux"] and o["quality"].get(15400, "").lower().startswith("good")
            and now - o["utc"] <= timedelta(hours=max_age_h)]
    if not good:
        return None
    if lon is not None:
        good.sort(key=lambda o: (abs(((LON.get(o["site"], 0) - lon) + 180) % 360 - 180), -o["utc"].timestamp()))
    o = good[0]
    return {"sfu": o["flux"][15400], "site": o["site"], "utc": o["utc"], "spectrum": o["flux"]}


def interp(spectrum: dict[int, float], f_ghz: float) -> float | None:
    """Flux at f from the two bracketing RSTN frequencies (power law; extrapolated beyond the last two)."""
    pts = sorted((f / 1000, s) for f, s in spectrum.items() if s and s > 0)
    if len(pts) < 2:
        return None
    lo = max((p for p in pts if p[0] <= f_ghz), default=pts[0], key=lambda p: p[0])
    hi = min((p for p in pts if p[0] > f_ghz), default=None, key=lambda p: p[0])
    if hi is None:
        lo, hi = pts[-2], pts[-1]
    if lo == hi:
        lo, hi = pts[0], pts[1]
    a = math.log(hi[1] / lo[1]) / math.log(hi[0] / lo[0])
    return lo[1] * (f_ghz / lo[0]) ** a


def xray_class(w_m2: float) -> str:
    for c, th in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7), ("A", 1e-8)):
        if w_m2 >= th:
            return f"{c}{w_m2 / th:.1f}"
    return "A0"


def xray_status(data: list | None = None, hours: float = 12.0) -> dict:
    """GOES long band (0.1–0.8 nm): current class, maximum of the last hours and whether to calibrate now."""
    data = data if data is not None else _get(XRAY_URL)
    pts = [(datetime.fromisoformat(d["time_tag"].replace("Z", "")).replace(tzinfo=timezone.utc), d["flux"])
           for d in data if d.get("energy") == "0.1-0.8nm" and d.get("flux")]
    if not pts:
        return {"ok": None}
    pts.sort()
    t_end = pts[-1][0]
    mx = max(f for t, f in pts if t_end - t <= timedelta(hours=hours))
    cur = pts[-1][1]
    ok = mx < 1e-5 and cur < 1e-6            # no M/X flare in the window, quiet now (below C)
    return {"ok": ok, "now": xray_class(cur), "max": xray_class(mx), "utc": t_end,
            "advice": "Sole tranquillo: buon momento per misurare il rumore solare." if ok else
            ("Brillamento recente o in corso: il flusso a microonde può variare, rimanda la calibrazione." if mx >= 1e-5
             else "Attività di classe C: misura, ma annota il valore e ripeti più tardi.")}
