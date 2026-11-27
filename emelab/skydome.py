# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🌌 Sky dome: where the noisy bodies are when the dish points at the Moon or at the Sun.

Bodies: Sun, Moon, the planets that are bright at microwaves (Venus, Mars, Jupiter, Saturn) and the strong radio
sources (Cas A, Cyg A, Tau A, Ori A, Vir A, Sgr A). For each one: its antenna temperature with the dish on axis
(S·Ae/2k for a point source, or the disk formula) and what reaches the receiver when the dish points elsewhere,
through the main lobe (Gaussian) or the sidelobes (ITU-R S.465 envelope 32 − 25 log θ dBi). Idea from YAEC by IC8TEM
(Sky view); code written for EMELab.

At 10 GHz and above the only body that really adds noise near the Moon is the Sun: radio sources and planets give
well under 1 K to a 2–3 m dish, the galactic background is below 0.1 K, and the sky noise comes from the atmosphere
(highest at low elevation, and at 24 GHz next to the water-vapour line)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

from . import astro

K_B = 1.380649e-23
C = 299792458.0
AU_KM = 149597870.7

# Strong radio sources, J2000. flux(f_ghz) in Jy. Baars et al. 1977 (A&A 61, 99) fits with the secular decrease of
# Cas A (−0.6 %/year at cm wavelengths, epoch 1980) and Tau A (−0.2 %/year); Ori A and Sgr A indicative.
def _baars(a, b, c=0.0):
    return lambda f: 10 ** (a + b * math.log10(f * 1000) + c * math.log10(f * 1000) ** 2)


SOURCES = [
    {"name": "Cas A", "ra": 350.866, "dec": 58.812, "diam_deg": 0.08, "kind": "supernova remnant",
     "flux": lambda f, y: _baars(5.745, -0.770)(f) * (1 - 0.006) ** (y - 1980)},
    {"name": "Tau A (Crab)", "ra": 83.633, "dec": 22.0145, "diam_deg": 0.07, "kind": "supernova remnant",
     "flux": lambda f, y: _baars(3.915, -0.299)(f) * (1 - 0.002) ** (y - 1980)},
    {"name": "Cyg A", "ra": 299.868, "dec": 40.734, "diam_deg": 0.04, "kind": "radio galaxy",
     "flux": lambda f, y: _baars(4.695, 0.085, -0.178)(f)},
    {"name": "Ori A", "ra": 83.82, "dec": -5.39, "diam_deg": 0.06, "kind": "HII region (thermal)",
     "flux": lambda f, y: 400.0 * (f / 10.0) ** -0.1},
    {"name": "Vir A (M87)", "ra": 187.706, "dec": 12.391, "diam_deg": 0.03, "kind": "radio galaxy",
     "flux": lambda f, y: _baars(5.023, -0.856)(f)},
    {"name": "Sgr A", "ra": 266.417, "dec": -29.008, "diam_deg": 0.3, "kind": "galactic centre",
     "flux": lambda f, y: 300.0 * (f / 10.0) ** -0.6},
]

# planets: erfa.plan94 number, radius (km), disk brightness temperature (K) at 10 / 24 / 47 GHz (indicative,
# de Pater 1990; Venus from the cm-wave spectrum, Jupiter thermal without the synchrotron belts)
PLANETS = [
    {"name": "Venere", "n": 2, "r_km": 6052.0, "tb": {10: 650.0, 24: 500.0, 47: 450.0}},
    {"name": "Marte", "n": 4, "r_km": 3390.0, "tb": {10: 200.0, 24: 200.0, 47: 200.0}},
    {"name": "Giove", "n": 5, "r_km": 71492.0, "tb": {10: 180.0, 24: 150.0, 47: 160.0}},
    {"name": "Saturno", "n": 6, "r_km": 60268.0, "tb": {10: 150.0, 24: 140.0, 47: 140.0}},
]
QUIET_SUN_SFU_15G4 = 600.0          # typical 15.4 GHz flux of the quiet Sun near solar maximum (assumed)


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def radec_vec(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])


def _frame(dt: datetime, lat: float, lon: float, h_m: float):
    """GCRS→ITRS matrix, ENU matrix, observer (km), geocentric Moon and Sun (km) and the TT date."""
    moon, sun, m = astro._geo_vectors(dt)
    return m, astro._enu(lat, lon), astro._observer_itrs(lat, lon, h_m), moon, sun, astro._jd(dt)[0]


def _azel(enu, v_itrs):
    loc = enu @ v_itrs
    d = float(np.linalg.norm(loc))
    el = math.degrees(math.asin(loc[2] / d))
    return math.degrees(math.atan2(loc[0], loc[1])) % 360.0, el


def _sep(u, v) -> float:
    return math.degrees(math.acos(float(np.clip(_unit(u) @ _unit(v), -1, 1))))


def bodies(dt: datetime, lat: float, lon: float, h_m: float = 0.0, f_ghz: float = 10.368) -> list[dict]:
    """Every body for the station at dt: az, el (radio), apparent diameter, direction (ITRS unit vector), flux/Tb."""
    import erfa
    dt = astro.utc(dt)
    m, enu, obs, moon, sun, tt = _frame(dt, lat, lon, h_m)
    out = []
    for name, vec, r_km in (("Luna", moon, astro.R_MOON_KM), ("Sole", sun, astro.R_SUN_KM)):
        v = m @ vec - obs
        az, el = _azel(enu, v)
        d = float(np.linalg.norm(v))
        out.append({"name": name, "kind": "moon" if name == "Luna" else "sun", "az": az, "el": el,
                    "el_radio": el + (astro.radio_refraction_deg(el, h_m / 1000) if el > -1 else 0.0),
                    "diam_deg": math.degrees(2 * math.asin(min(1.0, r_km / d))), "u": _unit(v), "dist_km": d})
    pvh, _ = erfa.epv00(tt[0], tt[1])
    earth = np.asarray(pvh["p"])
    band = min((10, 24, 47), key=lambda b: abs(b - f_ghz))
    for p in PLANETS:
        pv = erfa.plan94(tt[0], tt[1], p["n"])
        g = (np.asarray(pv["p"]) - earth) * AU_KM
        v = m @ g - obs
        az, el = _azel(enu, v)
        d = float(np.linalg.norm(v))
        out.append({"name": p["name"], "kind": "planet", "az": az, "el": el, "el_radio": el, "u": _unit(v),
                    "diam_deg": math.degrees(2 * p["r_km"] / d), "tb": p["tb"][band], "dist_km": d})
    year = dt.year + (dt.timetuple().tm_yday - 1) / 365.25
    for s in SOURCES:
        v = m @ radec_vec(s["ra"], s["dec"])
        az, el = _azel(enu, v)
        out.append({"name": s["name"], "kind": "source", "az": az, "el": el,
                    "el_radio": el + (astro.radio_refraction_deg(el, h_m / 1000) if el > -1 else 0.0),
                    "u": _unit(v), "diam_deg": s["diam_deg"], "flux_jy": s["flux"](f_ghz, year), "what": s["kind"]})
    return out


# ------------------------------------------------------------------ antenna response
def rel_gain_db(theta_deg: float, hpbw_deg: float, gmax_dbi: float) -> float:
    """Gain towards theta relative to the peak (dB): Gaussian main lobe, then the ITU-R S.465 sidelobe envelope
    (32 − 25 log θ dBi, never below −10 dBi) once that is higher. An envelope: real sidelobes are mostly lower."""
    main = -12.0 * (theta_deg / hpbw_deg) ** 2
    if theta_deg < 1.2 * hpbw_deg:
        return main
    env = max(-10.0, 32.0 - 25.0 * math.log10(max(theta_deg, 1e-3))) - gmax_dbi
    return max(main, min(env, -14.0))                     # first sidelobe at least 14 dB under the peak


def t_on_axis(body: dict, f_ghz: float, D_m: float, eta_ap: float, hpbw: float, sun_sfu: float | None = None,
              moon_tb: float | None = None) -> float:
    """Antenna temperature (K) with the dish pointed at the body."""
    from . import sky
    ae = eta_ap * math.pi * D_m ** 2 / 4
    if body["kind"] == "source":                       # S·Ae/2k, reduced when the source is wider than the beam
        return body["flux_jy"] * 1e-26 * ae / (2 * K_B) * hpbw ** 2 / (hpbw ** 2 + body["diam_deg"] ** 2)
    if body["kind"] == "sun":
        tb = sky.sun_tb_from_flux(sun_sfu or QUIET_SUN_SFU_15G4, f_ghz, body["diam_deg"])
    elif body["kind"] == "moon":
        tb = moon_tb if moon_tb is not None else 220.0
    else:
        tb = body["tb"]
    return sky.antenna_temp_disk(tb, body["diam_deg"], f_ghz, D_m, eta_ap, hpbw)


def gmax_dbi(f_ghz: float, D_m: float, eta_ap: float) -> float:
    lam = C / (f_ghz * 1e9)
    return 10 * math.log10(eta_ap * (math.pi * D_m / lam) ** 2)


def noise_when_pointing(target: str, dt: datetime, lat: float, lon: float, h_m: float, f_ghz: float, D_m: float,
                        eta_ap: float, edge_taper_db: float = 12.0, sun_sfu: float | None = None,
                        moon_tb: float | None = None, bl: list[dict] | None = None) -> dict:
    """With the dish on target ("Luna" or "Sole"): every other body with its distance from the beam axis and the
    noise it adds (K), largest first."""
    from . import sky
    bl = bl or bodies(dt, lat, lon, h_m, f_ghz)
    hp = sky.hpbw_deg(f_ghz, D_m, edge_taper_db)
    g = gmax_dbi(f_ghz, D_m, eta_ap)
    tgt = next(b for b in bl if b["name"] == target)
    rows = []
    for b in bl:
        if b is tgt:
            continue
        th = _sep(tgt["u"], b["u"])
        t0 = t_on_axis(b, f_ghz, D_m, eta_ap, hp, sun_sfu, moon_tb)
        rel = rel_gain_db(th, hp, g)
        hidden = b["el"] < -1                              # behind the Earth: it adds nothing
        rows.append({"name": b["name"], "kind": b["kind"], "sep_deg": th, "sep_hpbw": th / hp, "t_on_axis_k": t0,
                     "rel_db": rel, "dt_k": 0.0 if hidden else t0 * 10 ** (rel / 10), "el": b["el"], "az": b["az"],
                     "hidden": hidden})
    rows.sort(key=lambda r: -r["dt_k"])
    return {"target": tgt, "hpbw": hp, "gmax_dbi": g, "rows": rows}


# ------------------------------------------------------------------ the coming days
def close_approaches(start: datetime, days: float, lat: float, lon: float, h_m: float, f_ghz: float, D_m: float,
                     eta_ap: float, edge_taper_db: float = 12.0, step_min: float = 30.0, min_dt_k: float = 0.5,
                     near_deg: float = 2.0, target: str = "Luna", sun_sfu: float | None = None) -> list[dict]:
    """Moments in the next days when, with the dish on target above the horizon, another body adds at least
    min_dt_k kelvin or passes within near_deg of the beam axis: one row per body and pass (its worst moment)."""
    n = int(days * 24 * 60 / step_min)
    best: dict[str, dict] = {}
    out = []
    for i in range(n + 1):
        t = astro.utc(start) + timedelta(minutes=i * step_min)
        bl = bodies(t, lat, lon, h_m, f_ghz)
        tgt = next(b for b in bl if b["name"] == target)
        res = noise_when_pointing(target, t, lat, lon, h_m, f_ghz, D_m, eta_ap, edge_taper_db, sun_sfu, bl=bl)
        for r in res["rows"]:
            hit = tgt["el"] > 0 and (r["dt_k"] >= min_dt_k or r["sep_deg"] <= near_deg)
            cur = best.get(r["name"])
            if hit:
                if cur is None or r["dt_k"] > cur["dt_k"] or (r["dt_k"] == cur["dt_k"] and r["sep_deg"] < cur["sep_deg"]):
                    best[r["name"]] = {**r, "t": t, "target_el": tgt["el"], "start": cur["start"] if cur else t}
            elif cur is not None:
                out.append({**cur, "end": t})
                best.pop(r["name"])
    out += [{**c, "end": None} for c in best.values()]
    out.sort(key=lambda r: r["t"])
    return out


def galactic_plane(n: int = 181) -> list[tuple[float, float]]:
    """(RA, Dec) of the galactic equator, J2000 (inverse of moon.galactic)."""
    ra_p, dec_p, l_ncp = math.radians(192.85948), math.radians(27.12825), math.radians(122.93192)
    out = []
    for i in range(n):
        lg, b = math.radians(i * 360 / (n - 1)), 0.0
        sd = math.sin(b) * math.sin(dec_p) + math.cos(b) * math.cos(dec_p) * math.cos(l_ncp - lg)
        dec = math.asin(sd)
        y = math.cos(b) * math.sin(l_ncp - lg)
        x = math.sin(b) * math.cos(dec_p) - math.cos(b) * math.sin(dec_p) * math.cos(l_ncp - lg)
        out.append(((math.degrees(math.atan2(y, x)) + math.degrees(ra_p)) % 360.0, math.degrees(dec)))
    return out


def ecliptic(dt: datetime, n: int = 181) -> list[tuple[float, float]]:
    import erfa
    tt = astro._jd(astro.utc(dt))[0]
    eps = erfa.obl06(tt[0], tt[1])
    out = []
    for i in range(n):
        lam = math.radians(i * 360 / (n - 1))
        ra = math.atan2(math.sin(lam) * math.cos(eps), math.cos(lam))
        dec = math.asin(math.sin(eps) * math.sin(lam))
        out.append((math.degrees(ra) % 360, math.degrees(dec)))
    return out


def radec_to_azel(points: list[tuple[float, float]], dt: datetime, lat: float, lon: float) -> list[tuple[float, float]]:
    """Fixed directions (J2000 RA/Dec, precession ignored: < 0.4° in 2026) to azimuth/elevation now."""
    m, enu, *_ = _frame(astro.utc(dt), lat, lon, 0.0)
    return [_azel(enu, m @ radec_vec(r, d)) for r, d in points]
