# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Sun and Moon as seen from the station, from ERFA (the IAU SOFA routines): Moon by eraMoon98 (a few
arc-seconds), Sun by eraEpv00. Topocentric (parallax included, ~1° for the Moon), geometric elevation plus
radio refraction (ITU-R P.834). All times are UTC (UT1 ≈ UTC: < 0.9 s, < 0.004°)."""
from __future__ import annotations

import re

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

AU_KM = 149597870.7
R_MOON_KM = 1737.4
R_SUN_KM = 695700.0
C_KM_S = 299792.458
MOON_ROT = 2 * math.pi / (27.321661 * 86400)      # synchronous rotation (rad/s)


def utc(dt: datetime) -> datetime:
    """Naive datetimes are taken as UTC; aware ones are converted to UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _jd(dt: datetime):
    """(UTC→) TT and UT1≈UTC two-part Julian dates for ERFA."""
    import erfa
    d = utc(dt)
    u1, u2 = erfa.dtf2d("UTC", d.year, d.month, d.day, d.hour, d.minute, d.second + d.microsecond * 1e-6)
    a1, a2 = erfa.utctai(u1, u2)
    t1, t2 = erfa.taitt(a1, a2)
    return (float(t1), float(t2)), (float(u1), float(u2))


def _gcrs_to_itrs(tt, ut):
    import erfa
    return erfa.c2t06a(tt[0], tt[1], ut[0], ut[1], 0.0, 0.0)


def _observer_itrs(lat: float, lon: float, h_m: float) -> np.ndarray:
    import erfa
    return np.asarray(erfa.gd2gc(1, math.radians(lon), math.radians(lat), h_m)) / 1000.0   # km


def _enu(lat: float, lon: float) -> np.ndarray:
    la, lo = math.radians(lat), math.radians(lon)
    e = np.array([-math.sin(lo), math.cos(lo), 0.0])
    n = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)])
    u = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    return np.vstack([e, n, u])


def _geo_vectors(dt: datetime):
    """Geocentric GCRS position of Moon and Sun (km) and the GCRS→ITRS matrix."""
    import erfa
    tt, ut = _jd(dt)
    moon = np.asarray(erfa.moon98(tt[0], tt[1])['p']) * AU_KM
    pvh, _ = erfa.epv00(tt[0], tt[1])
    sun = -np.asarray(pvh['p']) * AU_KM
    return moon, sun, np.asarray(_gcrs_to_itrs(tt, ut))


def radio_refraction_deg(el_deg: float, h_km: float = 0.0) -> float:
    """Ray bending for the standard atmosphere, ITU-R P.834 (approximation valid from about −1° up)."""
    th = max(el_deg, -0.9)
    return 1.0 / (1.314 + 0.6437 * th + 0.02869 * th ** 2 + h_km * (0.2305 + 0.09428 * th + 0.01096 * th ** 2)
                  + 0.008583 * h_km ** 2)


@dataclass
class Body:
    az: float            # degrees from north, clockwise
    el: float            # geometric elevation (degrees)
    el_radio: float      # elevation with radio refraction
    dist_km: float       # topocentric distance
    ra: float            # geocentric right ascension (deg)
    dec: float           # geocentric declination (deg)
    diam_deg: float      # apparent diameter


def _body(vec_gcrs, R, lat, lon, h_m, m, enu, radius_km):
    obs = _observer_itrs(lat, lon, h_m)
    v = m @ vec_gcrs - obs                                  # topocentric, ITRS
    loc = enu @ v
    d = float(np.linalg.norm(loc))
    el = math.degrees(math.asin(loc[2] / d))
    az = math.degrees(math.atan2(loc[0], loc[1])) % 360.0
    ra = math.degrees(math.atan2(vec_gcrs[1], vec_gcrs[0])) % 360.0
    dec = math.degrees(math.asin(vec_gcrs[2] / np.linalg.norm(vec_gcrs)))
    return Body(az, el, el + (radio_refraction_deg(el, h_m / 1000) if el > -1 else 0.0), d, ra, dec,
                math.degrees(2 * math.asin(min(1.0, radius_km / d))))


@dataclass
class Sky:
    t: datetime
    moon: Body
    sun: Body
    sun_moon_deg: float          # angle between Sun and Moon seen from the station
    moon_phase_deg: float        # Sun–Moon–Earth angle (0 = full Moon, 180 = new Moon)
    moon_illum: float            # illuminated fraction
    doppler_hz_per_ghz: float    # own-echo Doppler at 1 GHz (scales with frequency)
    spread_hz_per_ghz: float     # libration spreading of the echo at 1 GHz (limb to limb)


def _topo_moon_vec(dt, lat, lon, h_m):
    moon, sun, m = _geo_vectors(dt)
    return m @ moon - _observer_itrs(lat, lon, h_m), moon, sun, m


def sky(dt: datetime, lat: float, lon: float, h_m: float = 0.0) -> Sky:
    """Sun and Moon for the station at time dt (UTC)."""
    dt = utc(dt)
    moon, sun, m = _geo_vectors(dt)
    enu = _enu(lat, lon)
    mb = _body(moon, R_MOON_KM, lat, lon, h_m, m, enu, R_MOON_KM)
    sb = _body(sun, R_SUN_KM, lat, lon, h_m, m, enu, R_SUN_KM)
    obs = _observer_itrs(lat, lon, h_m)
    vm = m @ moon - obs
    vs = m @ sun - obs
    sep = math.degrees(math.acos(np.clip(vm @ vs / np.linalg.norm(vm) / np.linalg.norm(vs), -1, 1)))
    # phase angle at the Moon between Sun and Earth
    a = sun - moon
    b = -moon
    ph = math.degrees(math.acos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))
    illum = (1 + math.cos(math.radians(ph))) / 2
    dop, spr = _doppler_spread(dt, lat, lon, h_m)
    return Sky(dt, mb, sb, sep, ph, illum, dop, spr)


def _doppler_spread(dt, lat, lon, h_m, step_s: float = 30.0):
    """Own-echo Doppler and libration spreading per GHz of carrier.

    In an inertial frame the observer→Moon direction turns with angular velocity w = u × du/dt; the Moon
    itself turns with its synchronous rotation about its axis (≈ ecliptic pole). The echo spread comes from
    the apparent rotation (Moon rotation − line-of-sight rotation) perpendicular to the line of sight:
    two-way limb-to-limb spread = 4·a·|Ω⊥|/λ."""
    import erfa
    pts = []
    for s in (-step_s, 0.0, step_s):
        t = dt + timedelta(seconds=s)
        moon, _, m = _geo_vectors(t)
        obs_gcrs = m.T @ _observer_itrs(lat, lon, h_m)           # station in GCRS (inertial)
        pts.append(moon - obs_gcrs)
    r0, r1, r2 = (np.asarray(p) for p in pts)
    rng = [np.linalg.norm(p) for p in (r0, r1, r2)]
    vr = (rng[2] - rng[0]) / (2 * step_s)                        # km/s, + receding
    dop = -2 * vr / C_KM_S * 1e9                                 # Hz per GHz
    u0, u1, u2 = r0 / rng[0], r1 / rng[1], r2 / rng[2]
    w_los = np.cross(u1, (u2 - u0) / (2 * step_s))               # rad/s, inertial
    tt, _ = _jd(dt)
    eps = erfa.obl06(tt[0], tt[1])
    pole = np.array([0.0, -math.sin(eps), math.cos(eps)])        # ecliptic north pole in GCRS (Moon axis ≈ 1.5°)
    omega = MOON_ROT * pole - w_los
    omega_perp = omega - (omega @ u1) * u1
    spread = 4 * R_MOON_KM * np.linalg.norm(omega_perp) / C_KM_S * 1e9   # Hz per GHz
    return float(dop), float(spread)


def moon_geocentric_km(dt: datetime) -> float:
    """Distance Earth centre – Moon centre (km): perigee/apogee are defined on this one."""
    moon, _, _ = _geo_vectors(utc(dt))
    return float(np.linalg.norm(moon))


def track(start: datetime, hours: float, step_min: float, lat: float, lon: float, h_m: float = 0.0):
    """Sky every step_min minutes from start (UTC) for the given hours."""
    n = int(hours * 60 / step_min) + 1
    return [sky(utc(start) + timedelta(minutes=i * step_min), lat, lon, h_m) for i in range(n)]


# ------------------------------------------------------------------ Maidenhead locator
def locator_to_latlon(loc: str) -> tuple[float, float]:
    """Centre of a Maidenhead locator (4, 6 or 8 characters)."""
    s = loc.strip().upper()
    if len(s) < 4 or len(s) % 2:
        raise ValueError("locator")
    lon = (ord(s[0]) - 65) * 20 - 180
    lat = (ord(s[1]) - 65) * 10 - 90
    lon += int(s[2]) * 2
    lat += int(s[3])
    dlon, dlat = 2.0, 1.0
    if len(s) >= 6:
        dlon, dlat = 2 / 24, 1 / 24
        lon += (ord(s[4]) - 65) * dlon
        lat += (ord(s[5]) - 65) * dlat
    if len(s) >= 8:
        dlon, dlat = dlon / 10, dlat / 10
        lon += int(s[6]) * dlon
        lat += int(s[7]) * dlat
    return lat + dlat / 2, lon + dlon / 2


def latlon_to_locator(lat: float, lon: float, n: int = 6) -> str:
    """Maidenhead locator of 4, 6, 8 or 10 characters (10: about 20 m × 20 m in Italy)."""
    lon = min(max(lon, -180.0), 179.9999999) + 180
    lat = min(max(lat, -90.0), 89.9999999) + 90
    s = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    lon %= 20
    lat %= 10
    s += str(int(lon // 2)) + str(int(lat // 1))
    lon, lat = lon % 2, lat % 1
    if n >= 6:
        lon, lat = lon * 12, lat * 24
        s += chr(97 + int(lon)) + chr(97 + int(lat))
        lon, lat = lon % 1, lat % 1
    if n >= 8:
        lon, lat = lon * 10, lat * 10
        s += str(int(lon)) + str(int(lat))
        lon, lat = lon % 1, lat % 1
    if n >= 10:
        lon, lat = lon * 24, lat * 24
        s += chr(97 + int(lon)) + chr(97 + int(lat))
    return s


def parse_coords(text: str) -> tuple[float, float] | None:
    """Latitude and longitude from what Google Maps gives: «41.12345, 12.34567» (right click on the map), a link
    with «@41.1,12.3,15z», «q=41.1,12.3», «!3d41.1!4d12.3», or degrees-minutes-seconds «41°07'24.4"N 12°20'44.4"E»."""
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", t)
    if not m:
        m = re.search(r"[@=/](-?\d{1,2}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)", t)
    if not m:
        m = re.fullmatch(r"\(?\s*(-?\d{1,2}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*\)?", t)
        if m and "," in m.group(1) + m.group(2) and ";" not in t:
            m = None if t.count(",") != 1 or " " not in t else m
    if m:
        lat, lon = (float(x.replace(",", ".")) for x in m.groups())
    else:
        d = re.findall(r"(\d{1,3})°\s*(\d{1,2})?['′]?\s*(\d{1,2}(?:[.,]\d+)?)?[\"″]?\s*([NSEWO])", t.upper())
        if len(d) != 2:
            return None
        v = []
        for deg, mi, se, h in d:
            x = float(deg) + float(mi or 0) / 60 + float((se or "0").replace(",", ".")) / 3600
            v.append((-x if h in "SWO" else x, h))
        lat = next((x for x, h in v if h in "NS"), None)
        lon = next((x for x, h in v if h in "EWO"), None)
        if lat is None or lon is None:
            return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


# ------------------------------------------------------------------ two stations: mutual Doppler and spread
def _apparent_rotation(dt: datetime, lat: float, lon: float, h_m: float, step_s: float = 30.0):
    """Unit vector station→Moon, range rate (km/s) and the Moon's apparent rotation seen from the station
    (synchronous rotation minus the turning of the line of sight), all in GCRS."""
    import erfa
    pts = []
    for s in (-step_s, 0.0, step_s):
        t = dt + timedelta(seconds=s)
        moon, _, m = _geo_vectors(t)
        pts.append(moon - m.T @ _observer_itrs(lat, lon, h_m))
    r0, r1, r2 = (np.asarray(p) for p in pts)
    rng = [np.linalg.norm(p) for p in (r0, r1, r2)]
    u0, u1, u2 = r0 / rng[0], r1 / rng[1], r2 / rng[2]
    w_los = np.cross(u1, (u2 - u0) / (2 * step_s))
    tt, _ = _jd(dt)
    eps = erfa.obl06(tt[0], tt[1])
    pole = np.array([0.0, -math.sin(eps), math.cos(eps)])
    return u1, (rng[2] - rng[0]) / (2 * step_s), MOON_ROT * pole - w_los


def mutual(dt: datetime, a: tuple[float, float], b: tuple[float, float], h_a: float = 0.0, h_b: float = 0.0) -> dict:
    """Path A → Moon → B: Doppler of the echo centre and libration spreading, per GHz of carrier.

    A point r of the Moon's disc shifts the frequency by (1/λ)·[(Ω_A×r)·û_A + (Ω_B×r)·û_B]; with û_A ≈ û_B ≈ û the
    spread over the disc (radius a) is 2a·|(Ω_A + Ω_B)⊥|/λ. For A = B it is the own-echo spread 4a·|Ω⊥|/λ."""
    dt = utc(dt)
    ua, vra, oa = _apparent_rotation(dt, a[0], a[1], h_a)
    ub, vrb, ob = _apparent_rotation(dt, b[0], b[1], h_b)
    u = (ua + ub) / np.linalg.norm(ua + ub)
    om = oa + ob
    om_perp = om - (om @ u) * u
    spread = 2 * R_MOON_KM * np.linalg.norm(om_perp) / C_KM_S * 1e9
    dop = -(vra + vrb) / C_KM_S * 1e9
    rate = math.degrees(np.linalg.norm(om_perp) / 2) * 60          # mean apparent libration rate, °/min
    return {"doppler_hz_per_ghz": float(dop), "spread_hz_per_ghz": float(spread), "libration_deg_per_min": float(rate)}
