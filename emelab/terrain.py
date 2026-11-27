# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🏔️ Automatic horizon from the terrain: the elevation of the skyline seen from a station, computed from a digital
elevation model with the Earth's curvature and standard radio refraction (k = 4/3).

Terrain: the Copernicus DEM (ESA / Airbus) of the AWS Open Data registry, GLO-30 (≈30 m) near the station and GLO-90
farther away, read with HTTP range requests (only the 1024×1024 blocks needed); if Copernicus is not reachable, the
free «Terrarium» tiles (Mapzen, SRTM 1″ over Europe). Downloaded once into the EMELab folder (terrain/), then
everything works without internet. Mountain names from OpenStreetMap (natural=peak). Idea from YAEC by IC8TEM.

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


# ------------------------------------------------------------------ Copernicus DEM (GLO-30 / GLO-90)
COP_URL = {30: "https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif",
           90: "https://copernicus-dem-90m.s3.amazonaws.com/{n}/{n}.tif"}
COP_SOURCE = ("Copernicus DEM GLO-30 (≈30 m) vicino e GLO-90 (≈90 m) lontano, ESA / Airbus, AWS Open Data. "
              "© DLR e.V. 2010-2014 e © Airbus Defence and Space GmbH 2014-2018, fornito nell'ambito del "
              "programma COPERNICUS dall'Unione Europea e dall'ESA")
COP_RINGS = ((15.0, 30), (60.0, 90))        # GLO-30 out to 15 km, GLO-90 beyond


def cop_name(lat_i: int, lon_i: int, res: int) -> str:
    ns = f"N{lat_i:02d}" if lat_i >= 0 else f"S{-lat_i:02d}"
    ew = f"E{lon_i:03d}" if lon_i >= 0 else f"W{-lon_i:03d}"
    return f"Copernicus_DSM_COG_{10 if res == 30 else 30}_{ns}_00_{ew}_00_DEM"


def _http_range(url: str, start: int, end: int) -> bytes:
    import urllib.error
    import urllib.request
    from .net import _contexts
    err = None
    for _, ctx in _contexts():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EMELab)",
                                                       "Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                return r.read()
        except urllib.error.HTTPError as e:            # 403/404: no file there (sea): no point in other contexts
            raise FileNotFoundError(url) from e
        except Exception as e:
            err = e
    raise err


def parse_tiff_header(buf: bytes) -> dict:
    """The tags of the first IFD of a little-endian classic TIFF (Copernicus COG): size, tiling, compression,
    predictor and where the tile offsets/byte counts are (as (count, type, value-or-offset))."""
    import struct
    if buf[:4] != b"II*\x00":
        raise ValueError("not a little-endian classic TIFF")
    ifd = struct.unpack_from("<I", buf, 4)[0]
    n = struct.unpack_from("<H", buf, ifd)[0]
    tags = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from("<HHII", buf, ifd + 2 + 12 * i)
        if cnt == 1 and typ == 3:
            val = struct.unpack_from("<H", buf, ifd + 2 + 12 * i + 8)[0]
        tags[tag] = (cnt, typ, val)
    g = lambda t, d=None: tags[t][2] if t in tags else d                       # noqa: E731
    return {"width": g(256), "height": g(257), "tw": g(322), "th": g(323), "compression": g(259, 1),
            "predictor": g(317, 1), "bits": g(258), "offsets": tags[324], "counts": tags[325]}


def _array_at(buf_get, entry) -> list[int]:
    import struct
    cnt, typ, val = entry
    size = 4 if typ == 4 else 8 if typ == 16 else 2
    if cnt * size <= 4:
        return [val]
    raw = buf_get(val, val + cnt * size - 1)
    fmt = {4: "I", 16: "Q", 3: "H"}[typ]
    return list(struct.unpack(f"<{cnt}{fmt}", raw))


def decode_tile(raw: bytes, tw: int, th: int, compression: int, predictor: int) -> np.ndarray:
    """Float32 heights of one internal tile: DEFLATE (8 or 32946) and the floating-point predictor (3)."""
    import zlib
    data = zlib.decompress(raw) if compression in (8, 32946) else raw
    if predictor == 3:                     # byte planes (most significant first), each row differenced
        b = np.frombuffer(data, dtype=np.uint8).reshape(th, 4 * tw)
        b = np.cumsum(b, axis=1, dtype=np.uint8)
        planes = b.reshape(th, 4, tw)
        le = np.stack([planes[:, 3], planes[:, 2], planes[:, 1], planes[:, 0]], axis=-1)
        return np.ascontiguousarray(le).view("<f4").reshape(th, tw)
    a = np.frombuffer(data, dtype="<f4").reshape(th, tw)
    if predictor == 2:
        a = np.cumsum(a, axis=1)
    return a


class CopFile:
    """One 1°×1° Copernicus COG read by HTTP ranges: only the internal tiles that are needed, cached on disk."""

    def __init__(self, lat_i: int, lon_i: int, res: int):
        self.lat_i, self.lon_i, self.res = lat_i, lon_i, res
        self.name = cop_name(lat_i, lon_i, res)
        self.url = COP_URL[res].format(n=self.name)
        self.dir = _cache_dir() / f"cop{res}" / self.name
        self.missing = False
        hdr_file = self.dir / "header.json"
        try:
            if hdr_file.exists():
                self.h = json.loads(hdr_file.read_text(encoding="utf-8"))
            else:
                head = _http_range(self.url, 0, 65535)
                h = parse_tiff_header(head)
                get = lambda a, b: head[a:b + 1] if b < len(head) else _http_range(self.url, a, b)   # noqa: E731
                h["offsets"], h["counts"] = _array_at(get, h["offsets"]), _array_at(get, h["counts"])
                self.dir.mkdir(parents=True, exist_ok=True)
                hdr_file.write_text(json.dumps(h), encoding="utf-8")
                self.h = h
        except FileNotFoundError:          # no tile: open sea
            self.missing = True

    def tile(self, ti: int, tj: int) -> np.ndarray:
        h = self.h
        f = self.dir / f"t{tj}_{ti}.bin"
        k = tj * ((h["width"] + h["tw"] - 1) // h["tw"]) + ti
        if f.exists():
            raw = f.read_bytes()
        else:
            o, c = h["offsets"][k], h["counts"][k]
            raw = _http_range(self.url, o, o + c - 1) if c else b""
            f.write_bytes(raw)
        if not raw:
            return np.zeros((h["th"], h["tw"]), dtype=np.float32)
        return decode_tile(raw, h["tw"], h["th"], h["compression"], h["predictor"])


class CopGrid:
    """Heights on a regular lat/lon grid around a point (Copernicus pixel spacing), with bilinear sampling.
    Pixel (row r, col c) of a file is the point (lat_i + 1 − r/H, lon_i + c/W)."""

    def __init__(self, lat: float, lon: float, radius_km: float, res: int):
        import math as _m
        step = (1 / 3600 if res == 30 else 3 / 3600)
        dlat = radius_km / 111.2
        dlon = radius_km / (111.2 * max(0.05, _m.cos(_m.radians(lat))))
        self.lat1, self.lon0 = lat + dlat, lon - dlon
        self.dy = step
        self.dx = step                                         # refined per file below (wider pixels north of 50°)
        self.ny = int(2 * dlat / step) + 2
        files = {}
        self.tiles = 0
        # grid in the step of the first file's longitude spacing
        f0 = CopFile(_m.floor(lat), _m.floor(lon), res)
        if not f0.missing:
            self.dx = 1.0 / f0.h["width"]
        self.nx = int(2 * dlon / self.dx) + 2
        self.h = np.zeros((self.ny, self.nx), dtype=np.float32)
        lats = self.lat1 - np.arange(self.ny) * self.dy
        lons = self.lon0 + np.arange(self.nx) * self.dx
        for la_i in range(_m.floor(lats.min()), _m.floor(lats.max()) + 1):
            for lo_i in range(_m.floor(lons.min()), _m.floor(lons.max()) + 1):
                cf = f0 if (la_i, lo_i) == (f0.lat_i, f0.lon_i) else CopFile(la_i, lo_i, res)
                files[(la_i, lo_i)] = cf
                if cf.missing:
                    continue
                H, W, tw, th = cf.h["height"], cf.h["width"], cf.h["tw"], cf.h["th"]
                ry = np.where((lats > la_i) & (lats <= la_i + 1))[0]
                cx = np.where((lons >= lo_i) & (lons < lo_i + 1))[0]
                if not len(ry) or not len(cx):
                    continue
                r_f = np.clip(np.round((la_i + 1 - lats[ry]) * H).astype(int), 0, H - 1)
                c_f = np.clip(np.round((lons[cx] - lo_i) * W).astype(int), 0, W - 1)
                for tj in range(r_f.min() // th, r_f.max() // th + 1):
                    for ti in range(c_f.min() // tw, c_f.max() // tw + 1):
                        t = cf.tile(ti, tj)
                        self.tiles += 1
                        sr = (r_f // th) == tj
                        sc = (c_f // tw) == ti
                        if sr.any() and sc.any():
                            self.h[np.ix_(ry[sr], cx[sc])] = t[np.ix_(r_f[sr] - tj * th, c_f[sc] - ti * tw)]

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        y = np.clip((self.lat1 - lat) / self.dy, 0, self.ny - 1.001)
        x = np.clip((lon - self.lon0) / self.dx, 0, self.nx - 1.001)
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
    rings, mos, source = [], [], SOURCE
    if fetch is None:                        # Copernicus DEM (the tests pass their own Terrarium tiles)
        try:
            for r, res in COP_RINGS:
                rings.append((min(r, max_km), res))
                mos.append(CopGrid(lat, lon, min(r, max_km) * 1.02 + 0.2, res))
                if r >= max_km:
                    break
            source = COP_SOURCE
        except Exception:                    # Copernicus not reachable: the Terrarium tiles (SRTM)
            rings, mos = [], []
    if not mos:
        for r, z in RINGS:                   # only the rings needed to reach max_km
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
            "obs_h_m": np.round(h[rows, k], 0).tolist(), "tiles": sum(m.tiles for m in mos), "source": source}


def _hz_file(lat, lon, antenna_agl_m, max_km) -> Path:
    return _cache_dir() / f"hzc_{lat:.5f}_{lon:.5f}_{antenna_agl_m:.1f}_{max_km:.0f}.json"   # c: Copernicus


def is_cached(lat: float, lon: float, antenna_agl_m: float = 3.0, max_km: float = 60.0) -> bool:
    return _hz_file(lat, lon, antenna_agl_m, max_km).exists()


def cached_horizon(lat: float, lon: float, antenna_agl_m: float = 3.0, max_km: float = 60.0, fetch=None) -> dict:
    """horizon() saved next to the tiles, so that it is computed once per place and antenna height."""
    f = _hz_file(lat, lon, antenna_agl_m, max_km)
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


# --- Mountain names: the peaks of OpenStreetMap (natural=peak), the same data PeakVisor and most peak apps start from.
# PeakVisor has no public API; the Overpass API of OSM is free. Downloaded once per place, then offline.
OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                 "https://overpass.private.coffee/api/interpreter")
PEAKS_SOURCE = "© OpenStreetMap contributors (ODbL), natural=peak via Overpass API"


def _ele(tag) -> float | None:
    try:
        return float(str(tag).replace(",", ".").split()[0].rstrip("m"))
    except Exception:
        return None


def parse_peaks(data: dict) -> list[dict]:
    """Overpass JSON → [{"name", "lat", "lon", "ele"}] (peaks without a name or a height are left out)."""
    out = []
    for e in data.get("elements", []):
        t = e.get("tags") or {}
        name = t.get("name") or t.get("name:it") or t.get("name:en")
        ele = _ele(t.get("ele")) if t.get("ele") is not None else None
        if name and ele is not None and "lat" in e:
            out.append({"name": name, "lat": float(e["lat"]), "lon": float(e["lon"]), "ele": ele})
    return out


def fetch_peaks(lat: float, lon: float, radius_km: float = 60.0) -> list[dict]:
    """Named peaks within radius_km, cached in terrain/peaks_*.json (the first time needs internet)."""
    f = _cache_dir() / f"peaks_{lat:.3f}_{lon:.3f}_{radius_km:.0f}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    import urllib.parse
    import urllib.request
    from .net import _contexts
    q = f'[out:json][timeout:60];node["natural"~"^(peak|volcano)$"](around:{radius_km * 1000:.0f},{lat:.5f},{lon:.5f});out;'
    body = urllib.parse.urlencode({"data": q}).encode()
    err = None
    for url in OVERPASS_URLS:
        for _, ctx in _contexts():
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": "EMELab (EME station tool)"})
                with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                    peaks = parse_peaks(json.loads(r.read().decode("utf-8")))
                f.write_text(json.dumps(peaks), encoding="utf-8")
                return peaks
            except Exception as e:
                err = e
    raise err or RuntimeError("Overpass")


def bearing_km(lat: float, lon: float, lat2: float, lon2: float) -> tuple[float, float]:
    """Initial azimuth (deg) and great-circle distance (km) from (lat, lon) to (lat2, lon2)."""
    p1, p2, dl = math.radians(lat), math.radians(lat2), math.radians(lon2 - lon)
    az = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                 math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return az, 2 * R_EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def visible_peaks(hz: dict, peaks: list[dict], tol_deg: float = 0.35, min_sep_deg: float = 4.0,
                  max_n: int = 30) -> list[dict]:
    """The peaks that are on the skyline (not hidden behind nearer terrain), the highest first, at least
    min_sep_deg apart in azimuth so that the labels do not overlap."""
    cand = []
    for p in peaks:
        az, d = bearing_km(hz["lat"], hz["lon"], p["lat"], p["lon"])
        if not 0.3 <= d <= hz.get("max_km", 60.0):
            continue
        el = float(elevation_angle(p["ele"], hz["antenna_m"], d))
        if el >= el_at(hz, az) - tol_deg:
            cand.append({**p, "az": round(az, 1), "el": round(el, 2), "dist_km": round(d, 1)})
    cand.sort(key=lambda c: -c["el"])
    out = []
    for c in cand:
        if all(min(abs(c["az"] - o["az"]), 360 - abs(c["az"] - o["az"])) >= min_sep_deg for o in out):
            out.append(c)
        if len(out) >= max_n:
            break
    return sorted(out, key=lambda c: c["az"])
