# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EME logbook: QSOs with every condition of the moment (both stations), ADIF import/export, statistics.

For each QSO EMELab stores date/time UTC, call, band/frequency, mode, reports, locators, power, setup and comment,
and computes for both stations: Moon azimuth/elevation, distance, path loss vs perigee, Doppler and mutual libration
spread, Sun–Moon angle, lunar phase, atmospheric attenuation and sky temperature (with the weather when known).
Imported ADIF QSOs get the same parameters, recomputed from their date, time and locators."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import astro, atmos, stations

ADIF_BANDS = {"3cm": "10G", "1.25cm": "24G", "6mm": "47G", "4mm": "76G", "2.5mm": "122G", "2mm": "134G"}
BAND_ADIF = {v: k for k, v in ADIF_BANDS.items()}
BAND_F = {"10G": 10.3682, "24G": 24.0482, "47G": 47.0882, "76G": 76.0322, "122G": 122.2502, "134G": 134.9282}
BAND_COLORS = {"10G": "#1f77b4", "24G": "#ff7f0e", "47G": "#d62728", "76G": "#f2c200", "122G": "#8c564b",
               "134G": "#2ca02c"}         # same colours everywhere: maps, statistics, PDF
PERIGEE_KM = 356400.0


# ------------------------------------------------------------------ ADIF
def parse_adif(text: str) -> list[dict]:
    """ADIF records → list of {FIELD: value} (field names upper case)."""
    body = re.split(r"<eoh>", text, flags=re.I)[-1] if re.search(r"<eoh>", text, re.I) else text
    out, rec = [], {}
    i = 0
    rx = re.compile(r"<([A-Za-z0-9_]+)(?::(\d+)(?::[A-Za-z])?)?>")
    while True:
        m = rx.search(body, i)
        if not m:
            break
        name = m.group(1).upper()
        if name == "EOR":
            if rec:
                out.append(rec)
            rec = {}
            i = m.end()
            continue
        n = int(m.group(2) or 0)
        rec[name] = body[m.end():m.end() + n]
        i = m.end() + n
    if rec:
        out.append(rec)
    return out


def _f(tag, val):
    v = "" if val is None else str(val)
    return f"<{tag}:{len(v.encode('utf-8'))}>{v} " if v != "" else ""


def to_adif(qsos: list[dict], my_call: str = "", program: str = "EMELab") -> str:
    """ADIF 3 export (PROP_MODE EME), with the EME conditions in the comment fields."""
    head = f"EMELab ADIF export\n{_f('ADIF_VER', '3.1.4')}{_f('PROGRAMID', program)}<EOH>\n"
    lines = []
    for q in qsos:
        t = q["utc"] if isinstance(q["utc"], datetime) else datetime.strptime(q["utc"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        rec = (_f("CALL", q["call"]) + _f("QSO_DATE", t.strftime("%Y%m%d")) + _f("TIME_ON", t.strftime("%H%M%S")) +
               _f("BAND", BAND_ADIF.get(q.get("band"), q.get("band"))) + _f("FREQ", f"{q['freq_mhz']:.6f}" if q.get("freq_mhz") else None) +
               _f("MODE", q.get("mode")) + _f("SUBMODE", q.get("submode")) + _f("RST_SENT", q.get("rst_sent")) +
               _f("RST_RCVD", q.get("rst_rcvd")) + _f("GRIDSQUARE", q.get("locator")) + _f("MY_GRIDSQUARE", q.get("my_locator")) +
               _f("STATION_CALLSIGN", my_call or None) + _f("NAME", q.get("name")) + _f("QTH", q.get("qth")) +
               _f("TX_PWR", q.get("tx_pwr")) + _f("PROP_MODE", "EME") + _f("COMMENT", q.get("comment")) +
               _f("QSL_SENT", q.get("qsl_sent")) + _f("QSL_RCVD", q.get("qsl_rcvd")))
        lines.append(rec + "<EOR>")
    return head + "\n".join(lines) + "\n"


def from_adif_record(r: dict) -> dict | None:
    """One ADIF record → QSO dict (None without call, date or time)."""
    if not (r.get("CALL") and r.get("QSO_DATE") and r.get("TIME_ON")):
        return None
    tm = r["TIME_ON"].ljust(6, "0")[:6]
    t = datetime.strptime(r["QSO_DATE"] + tm, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    f = None
    if r.get("FREQ"):
        try:
            f = float(r["FREQ"])                  # ADIF FREQ is in MHz
        except ValueError:
            f = None
    band = stations.band_of(f) or ADIF_BANDS.get((r.get("BAND") or "").lower())
    return {"utc": t, "call": r["CALL"].upper(), "band": band, "freq_mhz": f, "mode": r.get("MODE"),
            "submode": r.get("SUBMODE"), "rst_sent": r.get("RST_SENT"), "rst_rcvd": r.get("RST_RCVD"),
            "locator": (r.get("GRIDSQUARE") or "").upper() or None, "my_locator": (r.get("MY_GRIDSQUARE") or "").upper() or None,
            "name": r.get("NAME"), "qth": r.get("QTH"), "tx_pwr": r.get("TX_PWR"), "comment": r.get("COMMENT") or r.get("NOTES"),
            "qsl_sent": r.get("QSL_SENT"), "qsl_rcvd": r.get("QSL_RCVD"), "prop_mode": r.get("PROP_MODE"), "adif": r}


EME_DIGI = ("Q65", "JT65", "JT4", "QRA64")


def eme_verdict(q: dict, eme_calls=(), strict: bool = False) -> str | None:
    """None if the QSO is to be kept as EME at 10 GHz and up, otherwise the reason it is left out.
    PROP_MODE=EME is always kept; another PROP_MODE (tropo, rain scatter…) never. Without PROP_MODE it is kept only
    when it is with a known EME station or in an EME digital mode (Q65, JT65, JT4, QRA64), unless strict."""
    if q.get("band") not in BAND_F:
        return "sotto i 10 GHz"
    pm = (q.get("prop_mode") or "").upper()
    if pm == "EME":
        return None
    if pm:
        return "propagazione " + pm
    if strict:
        return "senza PROP_MODE=EME"
    digi = " ".join(x for x in (q.get("mode"), q.get("submode")) if x).upper()
    if q.get("call") in eme_calls or any(m in digi for m in EME_DIGI):
        return None
    return "non EME"


def wsjtx_mode(q: dict) -> dict:
    """WSJT-X writes Q65 in ADIF as MODE=MFSK, SUBMODE=Q65: bring it back to mode Q65 as in the rest of EMELab."""
    if (q.get("mode") or "").upper() == "MFSK" and (q.get("submode") or "").upper() in EME_DIGI:
        q["mode"], q["submode"] = q["submode"].upper(), None
    return q


# ------------------------------------------------------------------ conditions of a QSO
def conditions(utc: datetime, my_loc: tuple[float, float], dx_loc: tuple[float, float] | None, f_ghz: float,
               wx: dict | None = None, my_h: float = 0.0) -> dict:
    """Everything about the path at that moment, for both stations."""
    s = astro.sky(utc, my_loc[0], my_loc[1], my_h)
    out = {"f_ghz": f_ghz, "moon_az": s.moon.az, "moon_el": s.moon.el, "moon_dist_km": s.moon.dist_km,
           "moon_dec": s.moon.dec, "sun_moon_deg": s.sun_moon_deg, "moon_phase_deg": s.moon_phase_deg,
           "moon_illum": s.moon_illum, "own_doppler_hz": s.doppler_hz_per_ghz * f_ghz,
           "own_spread_hz": s.spread_hz_per_ghz * f_ghz,
           "path_loss_vs_perigee_db": 40 * __import__("math").log10(astro.moon_geocentric_km(utc) / PERIGEE_KM)}
    wx = wx or {}
    t_c = wx.get("t_c") if wx.get("t_c") is not None else 15.0
    rh = wx.get("rh") if wx.get("rh") is not None else 60.0
    z = atmos.zenith_attenuation(f_ghz, t_c, rh, wx.get("p_hpa") or 1013.25)["total"]
    if s.moon.el > -1:
        a = atmos.slant_attenuation(z, max(s.moon.el_radio, 0.5))
        out.update(atm_db=a, t_sky=atmos.sky_temperature(a, t_c))
    out["sublunar_lat"], out["sublunar_lon"] = sublunar_point(utc)
    if dx_loc:
        d = astro.sky(utc, dx_loc[0], dx_loc[1], 0.0)
        out["ground_km"] = great_circle_km(my_loc, dx_loc)
        out["eme_path_km"] = s.moon.dist_km + d.moon.dist_km              # A → Moon → B at that moment
        out["eme_delay_s"] = out["eme_path_km"] / astro.C_KM_S
        m = astro.mutual(utc, my_loc, dx_loc, my_h, 0.0)
        out.update(dx_moon_az=d.moon.az, dx_moon_el=d.moon.el, mutual_doppler_hz=m["doppler_hz_per_ghz"] * f_ghz,
                   mutual_spread_hz=m["spread_hz_per_ghz"] * f_ghz, libration_deg_min=m["libration_deg_per_min"],
                   dx_atm_db_std=atmos.slant_attenuation(atmos.zenith_attenuation(f_ghz, 15.0, 60.0)["total"],
                                                         max(d.moon.el_radio, 0.5)) if d.moon.el > -1 else None)
    return out


def great_circle_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def sublunar_point(utc: datetime) -> tuple[float, float]:
    """Where the Moon is at the zenith (geocentric latitude/longitude of the Moon)."""
    import math
    import numpy as np
    moon, _, m = astro._geo_vectors(astro.utc(utc))
    v = m @ moon
    return math.degrees(math.asin(v[2] / np.linalg.norm(v))), math.degrees(math.atan2(v[1], v[0]))


def latlon(loc: str | None) -> tuple[float, float] | None:
    try:
        return astro.locator_to_latlon(loc) if loc and len(loc) >= 4 else None
    except Exception:
        return None


def enrich(q: dict, my_locator: str, my_h: float = 0.0, wx: dict | None = None) -> dict:
    my = latlon(q.get("my_locator") or my_locator)
    if my is None:
        return {}
    f = (q.get("freq_mhz") or 0) / 1000 or BAND_F.get(q.get("band") or "", 10.3682)
    return conditions(q["utc"], my, latlon(q.get("locator")), f, wx, my_h)


def fill_locators(D, my_locator: str, my_h: float = 0.0) -> int:
    """QSOs without a locator (common in ADIF files of other loggers): take it from the EME stations database and
    recompute distance, EME path, Moon elevations and spread. Returns how many QSOs were completed."""
    n = 0
    known = {}
    for q in D.qsos():
        if q.get("locator"):
            continue
        if q["call"] not in known:
            s = D.station_of(q["call"])
            known[q["call"]] = (s or {}).get("locator") if s and latlon((s or {}).get("locator")) else None
        loc = known[q["call"]]
        if not loc:
            continue
        q["locator"] = loc
        D.update_qso(q["id"], locator=loc, calc=enrich(q, my_locator, my_h))
        n += 1
    return n


# ------------------------------------------------------------------ statistics
def statistics(qsos: list[dict]) -> dict:
    """Distributions of the conditions over the logged QSOs: what the successful ones had in common."""
    import numpy as np
    rows = [q for q in qsos if q.get("calc")]
    out = {"n": len(qsos), "n_with_conditions": len(rows)}
    def arr(k):
        return np.array([q["calc"].get(k) for q in rows if q["calc"].get(k) is not None], float)
    for k in ("moon_el", "dx_moon_el", "mutual_spread_hz", "path_loss_vs_perigee_db", "sun_moon_deg", "atm_db", "moon_dec"):
        a = arr(k) if rows else np.array([])
        if a.size:
            out[k] = {"median": float(np.median(a)), "p10": float(np.percentile(a, 10)), "p90": float(np.percentile(a, 90))}
    out["by_band"] = {}
    for q in qsos:
        out["by_band"][q.get("band") or "?"] = out["by_band"].get(q.get("band") or "?", 0) + 1
    out["by_hour"] = [0] * 24
    out["by_month"] = [0] * 12
    for q in qsos:
        t = q["utc"] if isinstance(q["utc"], datetime) else datetime.strptime(q["utc"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        out["by_hour"][t.hour] += 1
        out["by_month"][t.month - 1] += 1
    return out


# ------------------------------------------------------------------ how the mode of a QSO is shown
Q65_PERIODS = (15, 30, 60, 120, 300)
Q65_SUBMODES = tuple(f"{p}{x}" for p in Q65_PERIODS for x in "ABCDE")
_Q65_CODE = re.compile(r"(?<![\w.])(15|30|60|120|300)\s*([A-E])(?![A-Za-z0-9])")


def q65_submode(q: dict) -> tuple[str | None, bool]:
    """Q65 submode of a QSO as «60D»: from the submode field, the notes or the raw ADIF record; otherwise the band's
    submode (EMELab's choice for the band, by default 60D at 10 GHz and 60E from 24 GHz up), flagged as assumed.
    (None, False) when the QSO is not Q65."""
    mode, sub = (q.get("mode") or "").upper().strip(), (q.get("submode") or "").upper().strip()
    if "Q65" not in (mode, sub) and not mode.startswith("Q65") and not sub.startswith("Q65"):
        return None, False
    texts = [sub.replace("Q65", ""), mode.replace("Q65", ""), str(q.get("comment") or "").upper()]
    texts += [str(v).upper() for k, v in (q.get("adif") or {}).items()
              if k.upper() in ("COMMENT", "NOTES", "SUBMODE") or k.upper().startswith("APP_")]
    for t in texts:
        m = _Q65_CODE.search(t)
        if m:
            return m.group(1) + m.group(2), False
    s = sub.replace("Q65", "").replace("-", "").strip()
    from . import dx
    std = dx.band_mode(q.get("band") or "")
    if len(s) == 1 and s in "ABCDE":            # WSJT-X UDP gives the tone-spacing letter, not the T/R period
        return f"{std[:-1]}{s}", True
    return std, True


def mode_label(q: dict) -> tuple[str, bool]:
    """Mode as shown in EMELab: «Q65-60D» for Q65 (never «MFSK Q65»), otherwise mode and submode as logged.
    The flag is True when the Q65 submode is assumed."""
    sub, assumed = q65_submode(q)
    if sub:
        return f"Q65-{sub}", assumed
    mode, s = q.get("mode") or "", q.get("submode") or ""
    if mode.upper() == "MFSK" and s:
        return s, False
    return " ".join(x for x in (mode, s) if x), False
