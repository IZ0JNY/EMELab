# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Guided start of EMELab: today's sky and weather, the user's free horizon, Moon windows with their quality and
the forecast, who to work in a window, and the text of a sked proposal."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import astro, atmos

PERIGEE_KM = 356400.0
DAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
             "novembre", "dicembre"]


# ------------------------------------------------------------------ free horizon
def default_horizon(min_el: float = 10.0) -> list[dict]:
    return [{"az_da": 0.0, "az_a": 360.0, "el_min": min_el}]


def el_min(horizon: list[dict], az: float) -> float:
    """Lowest usable elevation towards azimuth az (obstacles, trees, houses); outside every sector: not usable."""
    best = None
    for s in horizon or []:
        a0, a1 = float(s["az_da"]) % 360, float(s["az_a"]) % 360 or 360.0
        inside = a0 <= az <= a1 if a0 < a1 else (az >= a0 or az <= a1)
        if inside:
            best = float(s["el_min"]) if best is None else min(best, float(s["el_min"]))
    return 90.0 if best is None else best


def visible(horizon, az, el) -> bool:
    return el >= el_min(horizon, az)


# ------------------------------------------------------------------ today
DAYS_SHORT_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
DAYS_SHORT_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def short_it(t: datetime, with_time: bool = True) -> str:
    from . import i18n
    days = DAYS_SHORT_IT if i18n.get_lang() == "it" else DAYS_SHORT_EN
    return f"{days[t.weekday()]} {t:%d/%m}" + (f" {t:%H:%M}" if with_time else "")


def date_it(t: datetime) -> str:
    return f"{DAYS_IT[t.weekday()]} {t.day} {MONTHS_IT[t.month - 1]} {t.year}"


def moon_windows(lat: float, lon: float, h_m: float, horizon: list[dict], start: datetime, days: int = 7,
                 step_min: int = 10, bands_ghz: tuple = (10.3682, 24.0482, 47.0882)) -> list[dict]:
    """Periods with the Moon above the free horizon: start, end, culmination, distance (and dB from perigee),
    own-echo spread at each band, Sun–Moon angle."""
    out, cur = [], None
    t = astro.utc(start).replace(second=0, microsecond=0)
    for i in range(int(days * 1440 / step_min) + 1):
        ti = t + timedelta(minutes=i * step_min)
        s = astro.sky(ti, lat, lon, h_m)
        ok = visible(horizon, s.moon.az, s.moon.el)
        if ok:
            if cur is None:
                cur = {"start": ti, "samples": []}
            cur["samples"].append((ti, s))
        elif cur is not None:
            out.append(_close(cur, bands_ghz))
            cur = None
    if cur is not None:
        out.append(_close(cur, bands_ghz))
    return out


def _close(cur, bands):
    sm = cur["samples"]
    tb, sb = max(sm, key=lambda x: x[1].moon.el)
    geo = astro.moon_geocentric_km(tb)
    spreads = {f: (min(s.spread_hz_per_ghz for _, s in sm) * f, max(s.spread_hz_per_ghz for _, s in sm) * f) for f in bands}
    return {"start": sm[0][0], "end": sm[-1][0], "hours": (sm[-1][0] - sm[0][0]).total_seconds() / 3600 + 1 / 6,
            "best_utc": tb, "best_el": sb.moon.el, "best_az": sb.moon.az, "dist_km": geo,
            "perigee_db": -40 * math.log10(geo / PERIGEE_KM), "spread": spreads,
            "sun_moon_min": min(s.sun_moon_deg for _, s in sm), "phase_deg": sb.moon_phase_deg}


def window_score(w: dict, f_ghz: float, wx: dict | None = None) -> tuple[int, str]:
    """0–100: Moon height, distance, spread (narrow is better for weak signals), Sun far from the Moon, weather."""
    sc = 40.0 + min(w["best_el"], 60) / 60 * 30            # height above the horizon (atmosphere, ground noise)
    sc += 10 + w["perigee_db"] * 8                            # +10 at perigee, about −8 at apogee
    lo, hi = w["spread"].get(f_ghz, (0, 0))
    sc -= 10 * min(max(((lo + hi) / 2 - 4 * f_ghz) / (15 * f_ghz), 0), 1)   # wide spread hurts weak signals
    if w["sun_moon_min"] < 5:
        sc -= 25
    elif w["sun_moon_min"] < 15:
        sc -= 10
    if wx:
        sc -= {"❌": 30, "⚠️": 12}.get(wx.get("label", "")[:2].strip(), 0)
    sc = max(0, min(100, sc))
    return int(round(sc)), "ottime" if sc >= 75 else "buone" if sc >= 55 else "discrete" if sc >= 35 else "scarse"


def window_weather(series: list[dict] | None, w: dict, f_ghz: float) -> dict | None:
    """Forecast during the window at the station: worst rain probability and gusts, mean humidity, attenuation."""
    if not series:
        return None
    pts = [x for x in series if w["start"] - timedelta(minutes=59) <= x["utc"] <= w["end"]]
    if not pts:
        return None
    pp = max((x.get("rain_prob") or 0) for x in pts)
    gust = max((x.get("gust_ms") or 0) for x in pts)
    rain = sum((x.get("rain_mmh") or 0) for x in pts)
    rh = sum(x["rh"] for x in pts) / len(pts)
    t_c = sum(x["t_c"] for x in pts) / len(pts)
    cloud = sum((x.get("cloud_pct") or 0) for x in pts) / len(pts)
    z = atmos.zenith_attenuation(f_ghz, t_c, rh, pts[0]["p_hpa"])["total"]
    a = atmos.slant_attenuation(z, max(w["best_el"], 0.5))
    lab = "❌ sconsigliato" if pp >= 60 or rain >= 1 or gust >= 15 else ("⚠️ incerto" if pp >= 30 or gust >= 10 else "✅ buono")
    return {"label": lab, "rain_prob": pp, "gust_ms": gust, "rh": rh, "t_c": t_c, "cloud": cloud, "atm_db": a}


def sky_now_text(lat, lon, h_m, horizon, bands=(10.3682, 24.0482, 47.0882)) -> dict:
    now = datetime.now(timezone.utc)
    s = astro.sky(now, lat, lon, h_m)
    geo = astro.moon_geocentric_km(now)
    return {"now": now, "moon_az": s.moon.az, "moon_el": s.moon.el, "visible": visible(horizon, s.moon.az, s.moon.el),
            "dist_km": geo, "perigee_db": -40 * math.log10(geo / PERIGEE_KM), "illum": s.moon_illum,
            "sun_el": s.sun.el, "sun_az": s.sun.az, "sun_moon": s.sun_moon_deg,
            "spread": {f: s.spread_hz_per_ghz * f for f in bands}, "doppler": {f: s.doppler_hz_per_ghz * f for f in bands}}


# ------------------------------------------------------------------ sked proposal
MODES_FREQ = {"10G": "10368.200", "24G": "24048.200", "47G": "47088.200", "76G": "76032.200"}


def sked_text(lang: str, my_call: str, my_loc: str, dx_call: str, dx_name: str | None, band: str, t0: datetime,
              t1: datetime, mode: str, my_first: bool, snr_me: float, snr_dx: float) -> str:
    qrg = MODES_FREQ.get(band, "")
    if lang == "it":
        hi = f"Ciao {dx_name}," if dx_name else "Ciao,"
        return (f"{hi}\nsono {my_call} ({my_loc}). Ti propongo uno sked EME a {band.replace('G', ' GHz')} il "
                f"{t0:%d/%m/%Y} dalle {t0:%H:%M} alle {t1:%H:%M} UTC, quando la Luna è visibile da entrambi.\n"
                f"QRG {qrg} MHz, Q65-{mode}; io trasmetto nel periodo {'pari (primo)' if my_first else 'dispari (secondo)'}.\n"
                f"Secondo il mio calcolo dovremmo riceverci intorno a {snr_me:.0f} dB (io) e {snr_dx:.0f} dB (tu).\n"
                f"Se ti va bene confermami, altrimenti proponimi un altro orario.\n73 de {my_call}")
    hi = f"Hi {dx_name}," if dx_name else "Hi,"
    return (f"{hi}\nthis is {my_call} ({my_loc}). I would like to propose an EME sked on {band.replace('G', ' GHz')} on "
            f"{t0:%Y-%m-%d} from {t0:%H:%M} to {t1:%H:%M} UTC, when the Moon is up at both ends.\n"
            f"QRG {qrg} MHz, Q65-{mode}; I transmit {'first (even)' if my_first else 'second (odd)'} period.\n"
            f"My estimate is about {snr_me:.0f} dB at my end and {snr_dx:.0f} dB at yours.\n"
            f"Please confirm or suggest another time.\n73 de {my_call}")
