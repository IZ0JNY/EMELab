# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Picture of the Moon as seen from the station right now: phase (terminator from the Sun direction), libration (which
part of the limb is turned towards us) and orientation in the sky (zenith up, or celestial north up).

Orientation of the Moon: IAU/WGCCRE 2009 rotation model (pole RA/Dec and prime meridian W with the E1…E13 terms,
Archinal et al. 2011), in the ICRF = GCRS of astro. Brightness: Lommel–Seeliger law μ0/(μ0 + μ), which keeps the full
Moon evenly bright to the limb as it really looks, plus a faint earthshine on the night side.
Surface map: emelab/data/moon_albedo_2k.jpg, simple cylindrical (longitude −180…180, centre 0°), from the Celestia
texture derived from the LRO map and the NASA SVS «CGI Moon Kit» (NASA, public domain; Celestia content GPL-2.0+)."""
from __future__ import annotations

import functools
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from . import astro

MAP_FILE = Path(__file__).resolve().parent / "data" / "moon_albedo_2k.jpg"
EARTHSHINE = 0.12

# Main features (name, selenographic latitude, longitude east +) — IAU Gazetteer of Planetary Nomenclature
FEATURES = [
    ("Mare Imbrium", 32.8, -15.6), ("Mare Serenitatis", 28.0, 17.5), ("Mare Tranquillitatis", 8.5, 31.4),
    ("Mare Crisium", 17.0, 59.1), ("Mare Fecunditatis", -7.8, 51.3), ("Mare Nectaris", -15.2, 35.5),
    ("Mare Nubium", -21.3, -16.6), ("Mare Humorum", -24.4, -38.6), ("Mare Frigoris", 56.0, 1.4),
    ("Oceanus Procellarum", 18.4, -57.4), ("Mare Smythii", 1.3, 87.5), ("Mare Orientale", -19.4, -92.8),
    ("Tycho", -43.3, -11.4), ("Copernicus", 9.6, -20.1), ("Kepler", 8.1, -38.0), ("Aristarchus", 23.7, -47.4),
    ("Plato", 51.6, -9.4), ("Clavius", -58.4, -14.4), ("Grimaldi", -5.2, -68.6), ("Langrenus", -8.9, 61.1),
    ("Apollo 11", 0.67, 23.47),
]


@functools.lru_cache(maxsize=1)
def _albedo() -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(MAP_FILE).convert("L"), dtype=np.float32) / 255.0


def _unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])


def body_axes(dt: datetime) -> np.ndarray:
    """Rows: Moon body-fixed x (towards 0° longitude), y (90° E), z (north pole), as GCRS unit vectors (IAU 2009)."""
    tt, _ = astro._jd(astro.utc(dt))
    d = (tt[0] - 2451545.0) + tt[1]
    T = d / 36525.0
    E = [0.0] + [math.radians(a) for a in (
        125.045 - 0.0529921 * d, 250.089 - 0.1059842 * d, 260.008 + 13.0120009 * d, 176.625 + 13.3407154 * d,
        357.529 + 0.9856003 * d, 311.589 + 26.4057084 * d, 134.963 + 13.0649930 * d, 276.617 + 0.3287146 * d,
        34.226 + 1.7484877 * d, 15.134 - 0.1589763 * d, 119.743 + 0.0036096 * d, 239.961 + 0.1643573 * d,
        25.053 + 12.9590088 * d)]
    s, c = math.sin, math.cos
    a0 = (269.9949 + 0.0031 * T - 3.8787 * s(E[1]) - 0.1204 * s(E[2]) + 0.0700 * s(E[3]) - 0.0172 * s(E[4])
          + 0.0072 * s(E[6]) - 0.0052 * s(E[10]) + 0.0043 * s(E[13]))
    d0 = (66.5392 + 0.0130 * T + 1.5419 * c(E[1]) + 0.0239 * c(E[2]) - 0.0278 * c(E[3]) + 0.0068 * c(E[4])
          - 0.0029 * c(E[6]) + 0.0009 * c(E[7]) + 0.0008 * c(E[10]) - 0.0009 * c(E[13]))
    W = (38.3213 + 13.17635815 * d - 1.4e-12 * d ** 2 + 3.5610 * s(E[1]) + 0.1208 * s(E[2]) - 0.0642 * s(E[3])
         + 0.0158 * s(E[4]) + 0.0252 * s(E[5]) - 0.0066 * s(E[6]) - 0.0047 * s(E[7]) - 0.0046 * s(E[8])
         + 0.0028 * s(E[9]) + 0.0052 * s(E[10]) + 0.0040 * s(E[11]) + 0.0019 * s(E[12]) - 0.0044 * s(E[13]))
    z = _unit(a0, d0)
    node = np.cross([0.0, 0.0, 1.0], z)
    node /= np.linalg.norm(node)
    w = math.radians(W % 360.0)
    x = math.cos(w) * node + math.sin(w) * np.cross(z, node)
    return np.vstack([x, np.cross(z, x), z])


def geometry(dt: datetime, lat: float, lon: float, h_m: float = 0.0, up: str = "zenith") -> dict:
    """Viewing geometry: towards-observer vector v, screen right/up axes, Sun direction from the Moon, body axes,
    sub-observer and sub-solar selenographic points (deg)."""
    dt = astro.utc(dt)
    moon, sun, m = astro._geo_vectors(dt)
    obs = m.T @ astro._observer_itrs(lat, lon, h_m)
    v = obs - moon
    v /= np.linalg.norm(v)
    ref = m.T @ astro._enu(lat, lon)[2] if up == "zenith" else np.array([0.0, 0.0, 1.0])
    upv = ref - (ref @ v) * v
    upv /= np.linalg.norm(upv)
    right = np.cross(upv, v)
    s = sun - moon
    s /= np.linalg.norm(s)
    B = body_axes(dt)

    def selen(p):
        q = B @ p
        return math.degrees(math.asin(max(-1.0, min(1.0, q[2])))), math.degrees(math.atan2(q[1], q[0]))

    return {"v": v, "right": right, "up": upv, "sun": s, "axes": B, "sub_obs": selen(v), "sub_sun": selen(s)}


def render(dt: datetime, lat: float, lon: float, h_m: float = 0.0, size: int = 520, up: str = "zenith") -> tuple:
    """RGB image (size × size, uint8) of the Moon now, and the screen positions (x, y in pixels, origin top left) of
    the features on the visible face, of the lunar north pole and of the sub-observer point."""
    g = geometry(dt, lat, lon, h_m, up)
    alb = _albedo()
    H, W = alb.shape
    n = size
    c = (np.arange(n) + 0.5) / n * 2 - 1
    sx, sy = np.meshgrid(c * 1.04, -c * 1.04)               # a small margin around the disc
    r2 = sx ** 2 + sy ** 2
    inside = r2 < 1.0
    sz = np.sqrt(np.clip(1 - r2, 0, 1))
    P = (sx[..., None] * g["right"] + sy[..., None] * g["up"] + sz[..., None] * g["v"])     # GCRS unit vectors
    q = P @ g["axes"].T
    la = np.degrees(np.arcsin(np.clip(q[..., 2], -1, 1)))
    lo = np.degrees(np.arctan2(q[..., 1], q[..., 0]))
    col = np.clip(((lo + 180) / 360 * W).astype(int), 0, W - 1)
    row = np.clip(((90 - la) / 180 * H).astype(int), 0, H - 1)
    a = alb[row, col]
    mu0 = P @ g["sun"]
    mu = sz
    lit = np.where(mu0 > 0, 2 * mu0 / (mu0 + mu + 1e-6), 0.0)
    lit = np.clip(lit, 0, 1.3) / 1.3
    soft = np.clip((mu0 + 0.015) / 0.03, 0, 1)            # soft terminator (a few degrees)
    lum = a * (EARTHSHINE + (1 - EARTHSHINE) * np.maximum(lit, 0) * soft)
    lum = np.clip(lum, 0, 1) ** (1 / 1.1)
    img = np.zeros((n, n, 3), dtype=np.float32)
    tint = np.array([1.0, 0.985, 0.95])
    img[inside] = lum[inside][:, None] * tint
    img = (img * 255).astype(np.uint8)

    def to_px(p):
        x, y = p @ g["right"], p @ g["up"]
        return (x / 1.04 + 1) / 2 * n, (1 - y / 1.04) / 2 * n, p @ g["v"]

    marks = []
    for name, flat, flon in FEATURES:
        p = g["axes"].T @ np.array([math.cos(math.radians(flat)) * math.cos(math.radians(flon)),
                                    math.cos(math.radians(flat)) * math.sin(math.radians(flon)),
                                    math.sin(math.radians(flat))])
        x, y, z = to_px(p)
        if z > 0.15:
            lit_here = float(p @ g["sun"]) > 0
            marks.append({"name": name, "x": x, "y": y, "lit": lit_here, "lat": flat, "lon": flon})
    xp, yp, zp = to_px(g["axes"][2])
    sub = g["axes"].T @ np.array([math.cos(math.radians(g["sub_obs"][0])) * math.cos(math.radians(g["sub_obs"][1])),
                                  math.cos(math.radians(g["sub_obs"][0])) * math.sin(math.radians(g["sub_obs"][1])),
                                  math.sin(math.radians(g["sub_obs"][0]))])
    xs, ys, _ = to_px(sub)
    return img, {"features": marks, "north": (xp, yp, zp > 0), "sub_obs_px": (xs, ys), "sub_obs": g["sub_obs"],
                 "sub_sun": g["sub_sun"], "size": n}
