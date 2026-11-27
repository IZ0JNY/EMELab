"""🏔️ Orizzonte (terrain horizon) and 🌌 Volta celeste (sky dome): computations without internet."""
import io
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

pytest.importorskip("erfa")
PIL = pytest.importorskip("PIL")


def _png(h):
    """A Terrarium tile with height h (m) everywhere."""
    from PIL import Image
    v = h + 32768
    r, g, b = int(v // 256), int(v % 256), int((v - int(v)) * 256)
    im = Image.new("RGB", (256, 256), (r, g, b))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_terrarium_decode():
    from emelab import terrain
    assert terrain._decode(_png(724.0))[10, 10] == pytest.approx(724.0, abs=0.01)


def test_elevation_angle_curvature_and_refraction():
    from emelab import terrain
    # a 1000 m peak 20 km away seen from 100 m: atan((900 − d²/2kR)/d)
    d = 20.0
    drop = (d * 1000) ** 2 / (2 * 4 / 3 * 6371e3)
    assert float(terrain.elevation_angle(1000, 100, d)) == pytest.approx(math.degrees(math.atan((900 - drop) / 20000)), abs=1e-6)
    assert float(terrain.elevation_angle(100, 100, 50)) < 0          # flat ground drops below the horizon


def test_flat_terrain_horizon(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import terrain
    hz = terrain.horizon(41.5, 13.3, 3.0, max_km=15, fetch=lambda u: _png(100.0))
    assert hz["ground_m"] == pytest.approx(100.0, abs=0.1) and hz["antenna_m"] == pytest.approx(103.0, abs=0.1)
    assert len(hz["az"]) == 360 and max(hz["el"]) < 0.01
    assert all(5 < d < 10 for d in hz["dist_km"])     # from 3 m the flat Earth's skyline is at √(2kR·3) ≈ 7 km


def test_sectors_merge_and_moon_passes():
    from emelab import terrain, wizard
    hz = {"az": list(range(360)), "el": [10.0 if 30 <= a < 60 else 2.0 for a in range(360)]}
    sec = terrain.to_sectors(hz, 5, floor_deg=0.0, margin_deg=0.5)
    assert wizard.el_min(sec, 45) == pytest.approx(10.5) and wizard.el_min(sec, 200) == pytest.approx(2.5)
    assert len(sec) == 3                                                  # 0–30, 30–60, 60–360 merged
    manual = [{"az_da": 0.0, "az_a": 180.0, "el_min": 0.0}, {"az_da": 180.0, "az_a": 190.0, "el_min": 20.0},
              {"az_da": 190.0, "az_a": 360.0, "el_min": 0.0}]
    m = terrain.merge_with(sec, manual)
    assert wizard.el_min(m, 185) == pytest.approx(20.0) and wizard.el_min(m, 45) == pytest.approx(10.5)
    t0 = datetime(2026, 12, 1, tzinfo=timezone.utc)
    track = [(t0 + timedelta(minutes=10 * i), 30 + i, [-1, 1, 5, 12, 15, 8, 1, -2][i]) for i in range(8)]
    p = terrain.moon_passes(track, hz)
    assert len(p) == 1 and p[0]["minutes_up"] == 60 and p[0]["clear_from"] == track[3][0]
    assert p[0]["minutes_blocked"] == 40                                  # 1°, 5°, 8°, 1° behind the 10° ridge
    assert terrain.el_at(hz, 359.5) == pytest.approx(2.0)


def test_skydome_bodies_and_black_holes():
    from emelab import skydome
    t = datetime(2026, 11, 27, 21, 30, tzinfo=timezone.utc)
    bl = skydome.bodies(t, 41.526, 13.275, 140, 10.368)
    names = {b["name"] for b in bl}
    assert {"Luna", "Sole", "Giove", "Cas A", "Sgr A*", "Cyg X-1", "M87 (Vir A)"} <= names
    assert sum(1 for b in bl if b.get("bh")) == 8
    cas = next(b for b in bl if b["name"] == "Cas A")
    assert 250 < cas["flux_jy"] < 450                                     # Cas A at 10 GHz in 2026, with the fading
    for b in bl:
        assert 0 <= b["az"] < 360 and -90 <= b["el"] <= 90


def test_sun_noise_falls_with_distance():
    from emelab import skydome
    hp, g = 0.82, 46.5
    assert skydome.rel_gain_db(0.0, hp, g) == 0
    assert skydome.rel_gain_db(hp / 2, hp, g) == pytest.approx(-3.0)
    assert skydome.rel_gain_db(2, hp, g) > skydome.rel_gain_db(5, hp, g) > skydome.rel_gain_db(30, hp, g)
    assert skydome.rel_gain_db(5, hp, g) <= -14


def test_hidden_bodies_add_nothing_and_close_approaches():
    from emelab import skydome
    t = datetime(2026, 11, 27, 21, 30, tzinfo=timezone.utc)
    r = skydome.noise_when_pointing("Luna", t, 41.526, 13.275, 140, 10.368, 2.4, 0.65)
    sun = next(x for x in r["rows"] if x["name"] == "Sole")
    assert sun["hidden"] and sun["dt_k"] == 0                            # night: the Sun is below the horizon
    ev = skydome.close_approaches(t, 15, 41.526, 13.275, 140, 10.368, 2.4, 0.65, step_min=60)
    assert any(e["name"] == "Sole" for e in ev)                          # new Moon on 9/12 is within 15 days
    gp = skydome.galactic_plane(7)
    from emelab import moon
    for ra, dec in gp:
        assert abs(moon.galactic(ra, dec)[1]) < 1e-6


def test_copernicus_tile_floating_point_predictor():
    """A float32 tile encoded as TIFF predictor 3 (byte planes, rows differenced) + DEFLATE comes back intact."""
    import zlib
    from emelab import terrain
    a = (np.arange(4 * 6, dtype="<f4").reshape(4, 6) * 37.25 + 120.5).astype("<f4")
    be = a.view(np.uint8).reshape(4, 6, 4)[..., ::-1]                  # big-endian bytes of every value
    planes = np.transpose(be, (0, 2, 1)).reshape(4, 24)                # byte planes, most significant first
    diff = np.concatenate([planes[:, :1], np.diff(planes.astype(np.int16), axis=1).astype(np.uint8)], axis=1)
    out = terrain.decode_tile(zlib.compress(diff.astype(np.uint8).tobytes()), 6, 4, 8, 3)
    assert np.array_equal(out, a)
    assert terrain.cop_name(41, 13, 30) == "Copernicus_DSM_COG_10_N41_00_E013_00_DEM"
    assert terrain.cop_name(-1, -2, 90) == "Copernicus_DSM_COG_30_S01_00_W002_00_DEM"


def test_peaks_on_the_skyline():
    """Named OSM peaks: only those on the skyline, not hidden behind nearer terrain, spaced in azimuth."""
    from emelab import terrain
    lat, lon = 41.5, 13.0
    hz = {"lat": lat, "lon": lon, "antenna_m": 200.0, "max_km": 60.0,
          "az": [float(a) for a in range(360)], "el": [0.0] * 360}
    hz["el"][90] = 5.0                                                  # a near ridge to the east hides what is behind
    def at(az, d, ele, name):
        la, lo = terrain.destination(lat, lon, np.array([az]), np.array([d]))
        return {"type": "node", "lat": float(la[0]), "lon": float(lo[0]), "tags": {"natural": "peak", "name": name, "ele": ele}}
    data = {"elements": [at(0, 10, "1200", "Monte Nord"), at(2, 12, "900 m", "Cima Vicina"),
                         at(90, 20, "800", "Dietro la cresta"), at(180, 15, "1000", "Monte Sud"),
                         {"type": "node", "lat": 41.6, "lon": 13.0, "tags": {"name": "Senza quota"}},
                         {"type": "node", "lat": 41.6, "lon": 13.0, "tags": {"ele": "500"}}]}
    peaks = terrain.parse_peaks(data)
    assert [p["name"] for p in peaks] == ["Monte Nord", "Cima Vicina", "Dietro la cresta", "Monte Sud"]
    assert peaks[1]["ele"] == 900.0
    vis = terrain.visible_peaks(hz, peaks)
    names = [p["name"] for p in vis]
    assert names == ["Monte Nord", "Monte Sud"]                         # 2° from Monte Nord, lower: label dropped
    assert vis[0]["az"] == pytest.approx(0.0, abs=0.2) and vis[0]["dist_km"] == pytest.approx(10.0, abs=0.1)
    az, d = terrain.bearing_km(lat, lon, peaks[3]["lat"], peaks[3]["lon"])
    assert az == pytest.approx(180.0, abs=0.01) and d == pytest.approx(15.0, abs=0.01)


def test_dish_pointing_by_az_el_and_daylight():
    from emelab import skydome, ui_skydome
    t = datetime(2026, 11, 28, 11, 30, tzinfo=timezone.utc)
    lat, lon = 41.5, 13.0
    bl = skydome.bodies(t, lat, lon, 100.0, 10.368)
    sun = next(b for b in bl if b["name"] == "Sole")
    r = skydome.noise_when_pointing("Luna", t, lat, lon, 100.0, 10.368, 2.4, 0.65, bl=bl,
                                    az_el=(sun["az"] + 0.3, sun["el"]))
    assert r["target"]["name"] == "Parabola"
    top = max(r["rows"], key=lambda x: x["dt_k"])
    assert top["name"] == "Sole" and top["dt_k"] > 50                  # 0.3° from the Sun: the Sun dominates
    r2 = skydome.noise_when_pointing("Luna", t, lat, lon, 100.0, 10.368, 2.4, 0.65, bl=bl,
                                     az_el=(sun["az"], sun["el"]), exclude="Sole")
    assert all(x["name"] != "Sole" for x in r2["rows"])                # the tracked body is not in the list
    assert ui_skydome.daylight(-30) == 0 and ui_skydome.daylight(10) == 1 and 0 < ui_skydome.daylight(-6) < 1
    assert ui_skydome._tracked_name("Moon", bl) == "Luna" and ui_skydome._tracked_name("SUN", bl) == "Sole"
    assert ui_skydome._tracked_name("", bl) is None
