# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🏔️ Automatic horizon from the terrain: the elevation of the skyline seen from a station, computed from a digital
elevation model with the Earth's curvature and standard radio refraction (k = 4/3).

Terrain: the free «Terrarium» elevation tiles of the AWS Open Data registry (Mapzen / Linux Foundation), which are
SRTM 1″ (≈30 m) over Europe, with ETOPO1, GMTED and national models where SRTM has no data. Tiles are downloaded once
into the EMELab folder (terrain/), then everything works without internet. Idea from YAEC by IC8TEM (SRTM1 horizon).

Only the ground is in the model: houses, trees and the station's own building are not, so they still go in the
free horizon by hand (🧭 Assistente)."""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
SOURCE = ("Terrarium tiles, AWS Open Data «Terrain Tiles» (Mapzen): SRTM 1″ in Europe, plus ETOPO1, GMTED2010, "
          "national DEMs")
R_EARTH_KM = 6371.0
K_RADIO = 4 / 3                     # standard radio refraction: effective Earth radius 4/3 R
# (max distance km, zoom): fine tiles near the station, coarse far away. z13 ≈ 14 m/px, z11 ≈ 57 m/px, z9 ≈ 230 m/px
# at 41° N; at 60 km a 230 m pixel subtends 0.2°, below the 10 GHz beamwidth of a 2.4 m dish.
RINGS = ((3.0, 13), (15.0, 11), (60.0, 9))


def _cache_dir() -> Path:
    from .settings import config_dir
    p = config_dir() / "terrain"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Web-Mercator tile coordinates (fractional) of a point."""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(max(-85.05, min(85.05, lat)))
    y = (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n
    return x, y


def _decode(png: bytes) -> np.ndarray:
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def tile(z: int, x: int, y: int, fetch=None) -> np.ndarray:
    """256×256 heights (m) of one tile, from the local cache or downloaded once."""
    f = _cache_dir() / f"{z}" / f"{x}_{y}.png"
    if f.exists() and f.stat().st_size > 0:
        return _decode(f.read_bytes())
    if fetch is None:
        from .weather import _get
        fetch = lambda u: _get(u, 30)                                       # noqa: E731
    data = fetch(TILE_URL.format(z=z, x=x, y=y))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return _decode(data)


class Mosaic:
    """The tiles of one zoom level around a point, glued into one array, with bilinear sampling."""

    def __init__(self, lat: float, lon: float, radius_km: float, z: int, fetch=None):
        self.z = z
        dlat = radius_km / 111.2
        dlon = radius_km / (111.2 * max(0.05, math.cos(math.radians(lat))))
        x0, y0 = _tile_xy(lat + dlat, lon - dlon, z)
        x1, y1 = _tile_xy(lat - dlat, lon + dlon, z)
        self.tx0, self.ty0 = int(x0), int(y0)
        nx, ny = int(x1) - self.tx0 + 1, int(y1) - self.ty0 + 1
        self.h = np.zeros((ny * 256, nx * 256))
        for j in range(ny):
            for i in range(nx):
                self.h[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = tile(z, self.tx0 + i, self.ty0 + j, fetch)
        self.tiles = nx * ny

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        n = 2 ** self.z
        x = ((lon + 180.0) / 360.0 * n - self.tx0) * 256 - 0.5
        la = np.radians(np.clip(lat, -85.05, 85.05))
        y = ((1 - np.log(np.tan(la) + 1 / np.cos(la)) / math.pi) / 2 * n - self.ty0) * 256 - 0.5
        x = np.clip(x, 0, self.h.shape[1] - 1.001)
        y = np.clip(y, 0, self.h.shape[0] - 1.001)
        i, j = x.astype(int), y.astype(int)
        fx, fy = x - i, y - j
        h = self.h
        return ((h[j, i] * (1 - fx) + h[j, i + 1] * fx) * (1 - fy) +
                (h[j + 1, i] * (1 - fx) + h[j + 1, i + 1] * fx) * fy)


def destination(lat: float, lon: float, az_deg: np.ndarray, d_km: np.ndarray):
    """Points at distance d along azimuth az from (lat, lon), on the sphere."""
    p1, l1 = math.radians(lat), math.radians(lon)
    th = np.radians(az_deg)
    dr = d_km / R_EARTH_KM
    p2 = np.arcsin(math.sin(p1) * np.cos(dr) + math.cos(p1) * np.sin(dr) * np.cos(th))
    l2 = l1 + np.arctan2(np.sin(th) * np.sin(dr) * math.cos(p1), np.cos(dr) - math.sin(p1) * np.sin(p2))
    return np.degrees(p2), (np.degrees(l2) + 540) % 360 - 180


def distances_km(min_km: float = 0.06, max_km: float = 60.0) -> np.ndarray:
    """Sample distances: every ~15 m near the station, growing to ~1 % of the distance far away."""
    out, d = [], min_km
    while d <= max_km:
        out.append(d)
        d += max(0.015, d * 0.01)
    return np.asarray(out)


def elevation_angle(h_target_m, h_obs_m: float, d_km, k: float = K_RADIO):
    """Elevation (deg) of a terrain point seen from the antenna, with Earth curvature and refraction."""
    d_m = np.asarray(d_km) * 1000.0
    drop = d_m ** 2 / (2 * k * R_EARTH_KM * 1000.0)
    return np.degrees(np.arctan2(np.asarray(h_target_m) - h_obs_m - drop, d_m))


def horizon(lat: float, lon: float, antenna_agl_m: float = 3.0, max_km: float = 60.0, az_step: float = 1.0,
            fetch=None) -> dict:
    """Skyline seen from an antenna antenna_agl_m above the ground at (lat, lon).

    Returns {"ground_m", "antenna_m", "az": [...], "el": [...], "dist_km": [...], "lat": [...], "lon": [...],
    "h_m": [...], "tiles": n}: for each azimuth the highest terrain elevation angle and where that obstacle is."""
    rings = []
    for r, z in RINGS:                       # only the rings needed to reach max_km
        rings.append((min(r, max_km), z))
        if r >= max_km:
            break
    mos = [Mosaic(lat, lon, r * 1.02 + 0.2, z, fetch) for r, z in rings]
    ground = float(mos[0].sample(np.array([lat]), np.array([lon]))[0])
    h_obs = ground + antenna_agl_m
    d = distances_km(max_km=max_km)
    az = np.arange(0.0, 360.0, az_step)
    A, Dd = np.meshgrid(az, d, indexing="ij")
    plat, plon = destination(lat, lon, A, Dd)
    h = np.empty_like(Dd)
    lo = 0.0
    for (r, _), m in zip(rings, mos):
        sel = (Dd > lo) & (Dd <= r) if lo else (Dd <= r)
        if sel.any():
            h[sel] = m.sample(plat[sel], plon[sel])
        lo = r
    el = elevation_angle(h, h_obs, Dd)
    k = np.argmax(el, axis=1)
    rows = np.arange(len(az))
    return {"lat": lat, "lon": lon, "ground_m": round(ground, 1), "antenna_m": round(h_obs, 1),
            "antenna_agl_m": antenna_agl_m, "max_km": max_km,
            "az": az.tolist(), "el": np.round(el[rows, k], 2).tolist(), "dist_km": np.round(Dd[rows, k], 2).tolist(),
            "obs_lat": np.round(plat[rows, k], 5).tolist(), "obs_lon": np.round(plon[rows, k], 5).tolist(),
            "obs_h_m": np.round(h[rows, k], 0).tolist(), "tiles": sum(m.tiles for m in mos), "source": SOURCE}


def cached_horizon(lat: float, lon: float, antenna_agl_m: float = 3.0, max_km: float = 60.0, fetch=None) -> dict:
    """horizon() saved next to the tiles, so that it is computed once per place and antenna height."""
    key = f"hz_{lat:.5f}_{lon:.5f}_{antenna_agl_m:.1f}_{max_km:.0f}.json"
    f = _cache_dir() / key
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    r = horizon(lat, lon, antenna_agl_m, max_km, fetch=fetch)
    f.write_text(json.dumps(r), encoding="utf-8")
    return r


def el_at(hz: dict, az: float) -> float:
    """Terrain horizon elevation towards az (linear between the computed azimuths)."""
    a = np.asarray(hz["az"])
    e = np.asarray(hz["el"])
    return float(np.interp(az % 360.0, np.append(a, 360.0), np.append(e, e[0])))


def to_sectors(hz: dict, width_deg: float = 5.0, floor_deg: float = 0.0, margin_deg: float = 0.0) -> list[dict]:
    """Terrain horizon as free-horizon sectors (🧭 Assistente format): in each sector the highest terrain angle,
    plus a margin, never below floor_deg. Adjacent sectors with the same value are merged."""
    a = np.asarray(hz["az"])
    e = np.asarray(hz["el"])
    out = []
    for s in np.arange(0.0, 360.0, width_deg):
        sel = (a >= s) & (a < s + width_deg)
        v = max(floor_deg, math.ceil((float(e[sel].max()) + margin_deg) * 10) / 10) if sel.any() else floor_deg
        if out and out[-1]["el_min"] == v:
            out[-1]["az_a"] = float(s + width_deg)
        else:
            out.append({"az_da": float(s), "az_a": float(s + width_deg), "el_min": v})
    return out


def merge_with(sectors: list[dict], manual: list[dict] | None, step: float = 1.0) -> list[dict]:
    """The higher of the terrain sectors and the hand-made free horizon, degree by degree, as sectors again."""
    from . import wizard
    if not manual:
        return sectors
    az = np.arange(0.0, 360.0, step)
    el = [max(wizard.el_min(sectors, a + step / 2), wizard.el_min(manual, a + step / 2)) for a in az]
    return to_sectors({"az": az.tolist(), "el": el}, step)


def moon_passes(track: list[tuple], hz: dict) -> list[dict]:
    """track: [(t, az, el_radio)] every step. One row per pass above 0°: rise, set, when the Moon is clear of the
    terrain and the minutes lost behind it."""
    if len(track) < 2:
        return []
    step = (track[1][0] - track[0][0]).total_seconds() / 60
    out, cur = [], None
    for t, az, el in track:
        if el > 0:
            if cur is None:
                cur = {"rise": t, "set": t, "clear_from": None, "clear_to": None, "minutes_up": 0.0, "minutes_blocked": 0.0}
            cur["set"] = t
            cur["minutes_up"] += step
            if el >= el_at(hz, az):
                cur["clear_from"] = cur["clear_from"] or t
                cur["clear_to"] = t
            else:
                cur["minutes_blocked"] += step
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def moon_blocked(track: list[tuple], hz: dict) -> dict:
    """Totals over the track: minutes with the Moon above 0° and minutes behind the terrain."""
    ps = moon_passes(track, hz)
    return {"minutes_up": sum(p["minutes_up"] for p in ps), "minutes_blocked": sum(p["minutes_blocked"] for p in ps),
            "passes": ps}
