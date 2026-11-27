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
