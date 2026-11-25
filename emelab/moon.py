# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""The Moon right now, for the 🌙 Moon tab: position, rise/transit/set, phase, optical libration, declination trend,
next perigee/apogee and new/full Moon, sky behind the Moon and the degradation against the ideal case, per band.

Positions come from astro (ERFA eraMoon98, topocentric, radio refraction ITU-R P.834). Optical libration: Meeus,
Astronomical Algorithms ch. 53 (geocentric; the physical libration, < 0.04°, is left out). Galactic coordinates:
IAU 1958 pole (RA 192.85948°, Dec +27.12825°, l of the NCP 122.93192°)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

from . import analysis, astro, atmos, link, sky

PERIGEE_KM = 356400.0               # a close perigee (geocentric): the reference of «dB from perigee»
R_EARTH_KM = 6371.0
SYNODIC_DAYS = 29.530589
INCL_MOON_EQ = 1.54242              # inclination of the lunar equator on the ecliptic (deg)
BANDS = (("10G", 10.3682), ("24G", 24.0482), ("47G", 47.0882))
STD_WX = {"t_c": 15.0, "rh": 60.0, "p_hpa": 1013.25}
TYPICAL_SETUP = {"nf_db": 1.0, "line_loss_db": 0.3, "spill": 0.9, "ground_frac": 0.25}   # when no setup exists
PHASE_NAMES = ["🌑 Luna nuova", "🌒 Falce crescente", "🌓 Primo quarto", "🌔 Gibbosa crescente", "🌕 Luna piena",
               "🌖 Gibbosa calante", "🌗 Ultimo quarto", "🌘 Falce calante"]


# ------------------------------------------------------------------ fast position (no Doppler)
def azel(dt: datetime, lat: float, lon: float, h_m: float = 0.0) -> tuple[float, float, float, float]:
    """Azimuth, geometric elevation, elevation with radio refraction and topocentric distance (km) of the Moon."""
    moon, _, m = astro._geo_vectors(astro.utc(dt))
    loc = astro._enu(lat, lon) @ (m @ moon - astro._observer_itrs(lat, lon, h_m))
    d = float(np.linalg.norm(loc))
    el = math.degrees(math.asin(loc[2] / d))
    az = math.degrees(math.atan2(loc[0], loc[1])) % 360.0
    # refraction kept continuous below the horizon too (astro.sky drops it under −1°), so that the rise/set crossings
    # of the radio elevation 0° are smooth
    return az, el, el + astro.radio_refraction_deg(el, h_m / 1000), d


def _ecliptic(dt: datetime):
    """Ecliptic longitude and latitude of date (deg) of Moon and Sun, geocentric, and T (Julian centuries TT)."""
    import erfa
    tt, _ = astro._jd(dt)
    moon, sun, _ = astro._geo_vectors(dt)
    r = np.asarray(erfa.ecm06(tt[0], tt[1]))
    out = []
    for v in (moon, sun):
        e = r @ v
        out.append((math.degrees(math.atan2(e[1], e[0])) % 360.0, math.degrees(math.asin(e[2] / np.linalg.norm(e)))))
    T = ((tt[0] - 2451545.0) + tt[1]) / 36525.0
    return out[0], out[1], T


def elongation(dt: datetime) -> float:
    """Moon − Sun ecliptic longitude (0 = new Moon, 90 = first quarter, 180 = full, 270 = last quarter)."""
    (lm, _), (ls, _), _ = _ecliptic(astro.utc(dt))
    return (lm - ls) % 360.0


def libration(dt: datetime) -> tuple[float, float]:
    """Geocentric optical libration in longitude and latitude (deg), Meeus ch. 53: + longitude = the east limb
    (Mare Crisium side) turned towards us, + latitude = the north pole region visible."""
    (lam, beta), _, T = _ecliptic(astro.utc(dt))
    F = 93.2720950 + 483202.0175233 * T - 0.0036539 * T ** 2 - T ** 3 / 3526000 + T ** 4 / 863310000
    Om = 125.0445479 - 1934.1362891 * T + 0.0020754 * T ** 2 + T ** 3 / 467441 - T ** 4 / 60616000
    I, W, b = math.radians(INCL_MOON_EQ), math.radians(lam - Om), math.radians(beta)
    A = math.degrees(math.atan2(math.sin(W) * math.cos(b) * math.cos(I) - math.sin(b) * math.sin(I),
                                math.cos(W) * math.cos(b)))
    l_ = (A - F + 180.0) % 360.0 - 180.0
    b_ = math.degrees(math.asin(-math.sin(W) * math.cos(b) * math.sin(I) - math.sin(b) * math.cos(I)))
    return l_, b_


def phase(dt: datetime, illum: float) -> dict:
    e = elongation(dt)
    return {"elongation": e, "waxing": e < 180.0, "age_days": e / 360.0 * SYNODIC_DAYS, "illum": illum,
            "name": PHASE_NAMES[int(((e + 22.5) % 360) // 45)]}


def galactic(ra_deg: float, dec_deg: float) -> tuple[float, float]:
    """Galactic longitude and latitude (deg) from J2000 right ascension and declination."""
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    ra_p, dec_p, l_ncp = math.radians(192.85948), math.radians(27.12825), math.radians(122.93192)
    sb = math.sin(dec) * math.sin(dec_p) + math.cos(dec) * math.cos(dec_p) * math.cos(ra - ra_p)
    b = math.asin(max(-1.0, min(1.0, sb)))
    y = math.cos(dec) * math.sin(ra - ra_p)
    x = math.sin(dec) * math.cos(dec_p) - math.cos(dec) * math.sin(dec_p) * math.cos(ra - ra_p)
    return math.degrees(l_ncp - math.atan2(y, x)) % 360.0, math.degrees(b)


def galactic_background_k(f_ghz: float, b_deg: float) -> float:
    """Rough galactic synchrotron brightness behind the Moon at f (K): about 20 K at 408 MHz far from the plane and
    up to ~250 K on it (Haslam), scaled with f^-2.6. Above 10 GHz it is well below 0.1 K: shown only to say so."""
    t408 = 20.0 + 230.0 * math.exp(-abs(b_deg) / 4.0)
    return t408 * (f_ghz / 0.408) ** -2.6


# ------------------------------------------------------------------ events
def _refine_cross(f, a: datetime, b: datetime, fa: float, tol_s: float = 20.0) -> datetime:
    while (b - a).total_seconds() > tol_s:
        mid = a + (b - a) / 2
        fm = f(mid)
        if (fm >= 0) == (fa >= 0):
            a, fa = mid, fm
        else:
            b = mid
    return a + (b - a) / 2


def day_events(day_start_utc: datetime, lat: float, lon: float, h_m: float = 0.0, horizon: list[dict] | None = None,
               hours: float = 24.0, step_min: float = 10.0) -> dict:
    """Moon rises, upper transits (time, elevation) and sets (radio elevation 0°) in [day_start, day_start + hours), the
    AZ/EL track for the sky plot and, with a horizon profile, when the Moon comes out from and goes behind the obstacles."""
    from . import wizard
    t0 = astro.utc(day_start_utc)
    n = int(hours * 60 / step_min) + 1
    ts = [t0 + timedelta(minutes=i * step_min) for i in range(n)]
    pts = [azel(t, lat, lon, h_m) for t in ts]
    out = {"track": [(t, p[0], p[2]) for t, p in zip(ts, pts)], "rises": [], "sets": [], "transits": [],
           "free_from": [], "free_to": []}

    def elf(t):
        return azel(t, lat, lon, h_m)[2]

    for i in range(1, n):
        a, b = pts[i - 1][2], pts[i][2]
        if a < 0 <= b:
            out["rises"].append(_refine_cross(elf, ts[i - 1], ts[i], a))
        elif a >= 0 > b:
            out["sets"].append(_refine_cross(elf, ts[i - 1], ts[i], a))
    for k in range(1, n - 1):                             # upper culminations: golden-section search around each maximum
        if not (pts[k - 1][2] < pts[k][2] >= pts[k + 1][2]):
            continue
        lo, hi = ts[k - 1], ts[k + 1]
        for _ in range(14):
            m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
            if elf(m1) < elf(m2):
                lo = m1
            else:
                hi = m2
        tt = lo + (hi - lo) / 2
        out["transits"].append((tt, elf(tt)))
    if horizon:
        def free(t):
            az, _, el, _ = azel(t, lat, lon, h_m)
            return el - wizard.el_min(horizon, az)
        fv = [p[2] - wizard.el_min(horizon, p[0]) for p in pts]
        for i in range(1, n):
            if fv[i - 1] < 0 <= fv[i]:
                out["free_from"].append(_refine_cross(free, ts[i - 1], ts[i], fv[i - 1]))
            elif fv[i - 1] >= 0 > fv[i]:
                out["free_to"].append(_refine_cross(free, ts[i - 1], ts[i], fv[i - 1]))
    return out


def declination_series(start: datetime, days: float = 30.0, step_h: float = 3.0) -> list[tuple[datetime, float]]:
    """Geocentric declination of the Moon every step_h hours."""
    t0 = astro.utc(start)
    out = []
    for i in range(int(days * 24 / step_h) + 1):
        t = t0 + timedelta(hours=i * step_h)
        moon, _, _ = astro._geo_vectors(t)
        out.append((t, math.degrees(math.asin(moon[2] / np.linalg.norm(moon)))))
    return out


def declination_extremes(series: list[tuple[datetime, float]]) -> list[tuple[datetime, float, str]]:
    """Northern («max») and southern («min») declination extremes in the series, refined with a parabola."""
    out = []
    for i in range(1, len(series) - 1):
        a, b, c = series[i - 1][1], series[i][1], series[i + 1][1]
        kind = "max" if b > a and b >= c else "min" if b < a and b <= c else None
        if kind:
            den = a - 2 * b + c
            x = 0.5 * (a - c) / den if den else 0.0
            step = series[i + 1][0] - series[i][0]
            out.append((series[i][0] + step * x, b - 0.25 * (a - c) * x, kind))
    return out


def next_phases(start: datetime, days: float = 32.0) -> list[tuple[datetime, str]]:
    """Next new («new»), first quarter, full («full») and last quarter Moons."""
    t0 = astro.utc(start)
    targets = {0.0: "new", 90.0: "first", 180.0: "full", 270.0: "last"}
    step = timedelta(hours=6)
    out = []
    t, e = t0, elongation(t0)
    while t < t0 + timedelta(days=days):
        t2 = t + step
        e2 = elongation(t2)
        for tg, name in targets.items():
            d1, d2 = (e - tg + 180) % 360 - 180, (e2 - tg + 180) % 360 - 180
            if d1 < 0 <= d2:
                f = lambda x, tg=tg: (elongation(x) - tg + 180) % 360 - 180
                out.append((_refine_cross(f, t, t2, d1, 60.0), name))
        t, e = t2, e2
    return out


# ------------------------------------------------------------------ per band
def band_now(f_ghz: float, el_radio: float, dist_km: float, geo_km: float, signed_phase_deg: float, wx: dict,
             setup: dict, sky_s) -> dict:
    """Doppler, spread, path loss, sky and Moon temperatures and the degradation against the ideal case (Moon at
    perigee and at the zenith, same weather and receiver) for one band."""
    z = atmos.zenith_attenuation(f_ghz, wx["t_c"], wx["rh"], wx["p_hpa"])["total"]
    up = el_radio > 0
    a = atmos.slant_attenuation(z, max(el_radio, 0.5)) if up else float("nan")
    t_sky = atmos.sky_temperature(a, wx["t_c"]) if up else float("nan")
    t_sky_zen = atmos.sky_temperature(z, wx["t_c"])
    ts = analysis.tsys_cold(setup, t_sky)["sys"] if up else float("nan")
    ts0 = analysis.tsys_cold(setup, t_sky_zen)["sys"]
    d_dist = 40 * math.log10(dist_km / (PERIGEE_KM - R_EARTH_KM))
    d_atm_extra = 2 * (a - z) if up else float("nan")
    d_noise = 10 * math.log10(ts / ts0) if up else float("nan")
    return {"f_ghz": f_ghz, "doppler_hz": sky_s.doppler_hz_per_ghz * f_ghz, "spread_hz": sky_s.spread_hz_per_ghz * f_ghz,
            "path_loss_db": link.path_loss_db(f_ghz, dist_km), "perigee_db": 40 * math.log10(geo_km / PERIGEE_KM),
            "a_slant_db": a, "a_zen_db": z, "t_sky": t_sky, "t_moon": sky.moon_tb(f_ghz, signed_phase_deg),
            "tsys": ts, "two_way_atm_db": 2 * a if up else float("nan"),
            "dgrd": {"dist": d_dist, "atm": d_atm_extra, "noise": d_noise,
                     "total": d_dist + d_atm_extra + d_noise if up else float("nan")}}


def now(dt: datetime, lat: float, lon: float, h_m: float = 0.0, wx: dict | None = None,
        setups: dict | None = None) -> dict:
    """Everything the Moon tab shows for the instant dt (UTC). setups: band key → setup dict (missing bands use a
    typical receiver, reported in «assumed»)."""
    dt = astro.utc(dt)
    s = astro.sky(dt, lat, lon, h_m)
    geo = astro.moon_geocentric_km(dt)
    ph = phase(dt, s.moon_illum)
    signed = -s.moon_phase_deg if ph["waxing"] else s.moon_phase_deg
    wx_assumed = not wx
    wx = {**STD_WX, **{k: v for k, v in (wx or {}).items() if v is not None}}
    lib_l, lib_b = libration(dt)
    rate = astro.mutual(dt, (lat, lon), (lat, lon), h_m, h_m)["libration_deg_per_min"]
    gl, gb = galactic(s.moon.ra, s.moon.dec)
    m1 = astro._geo_vectors(dt + timedelta(hours=1))[0]
    dec1 = math.degrees(math.asin(m1[2] / np.linalg.norm(m1)))
    s1 = astro._doppler_spread(dt + timedelta(seconds=60), lat, lon, h_m)
    bands = {}
    for key, f in BANDS:
        su = (setups or {}).get(key)
        b = band_now(f, s.moon.el_radio, s.moon.dist_km, geo, signed, wx, su or TYPICAL_SETUP, s)
        b["setup_assumed"] = su is None
        b["doppler_rate_hz_min"] = (s1[0] - s.doppler_hz_per_ghz) * f
        bands[key] = b
    return {"utc": dt, "sky": s, "az": s.moon.az, "el": s.moon.el, "el_radio": s.moon.el_radio,
            "dist_km": s.moon.dist_km, "geo_km": geo, "diam_deg": s.moon.diam_deg, "ra": s.moon.ra, "dec": s.moon.dec,
            "dec_rate_deg_h": dec1 - s.moon.dec, "sun_moon_deg": s.sun_moon_deg, "sun_el": s.sun.el, "sun_az": s.sun.az,
            "phase": ph, "phase_signed_deg": signed, "libration_lon": lib_l, "libration_lat": lib_b,
            "libration_rate_deg_min": rate, "gal_l": gl, "gal_b": gb,
            "t_gal_10g": galactic_background_k(10.368, gb), "wx": wx, "wx_assumed": wx_assumed, "bands": bands}


def ra_hms(ra_deg: float) -> str:
    h = (ra_deg % 360) / 15.0
    hh, mm = int(h), int((h % 1) * 60)
    ss = ((h * 60) % 1) * 60
    return f"{hh:02d}h {mm:02d}m {ss:04.1f}s"


def dec_dms(dec_deg: float) -> str:
    s = "+" if dec_deg >= 0 else "−"
    d = abs(dec_deg)
    return f"{s}{int(d):02d}° {int((d % 1) * 60):02d}′ {((d * 60) % 1) * 60:02.0f}″"
