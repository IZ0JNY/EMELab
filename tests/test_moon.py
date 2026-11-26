"""🌙 Moon tab: phases, libration, declination extremes, rise/transit/set and per-band values."""
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("erfa")

from emelab import astro, moon

ROME = (41.9, 12.5)


def test_full_and_new_moon_times():
    """Full Moon 24 Nov 2026 14:53 UTC, new Moon 9 Dec 2026 00:51 UTC (published ephemerides): within 15 minutes."""
    ph = moon.next_phases(datetime(2026, 11, 20, tzinfo=timezone.utc), 20)
    full = next(t for t, k in ph if k == "full")
    new = next(t for t, k in ph if k == "new")
    assert abs((full - datetime(2026, 11, 24, 14, 53, tzinfo=timezone.utc)).total_seconds()) < 900
    assert abs((new - datetime(2026, 12, 9, 0, 51, tzinfo=timezone.utc)).total_seconds()) < 900


def test_libration_stays_in_its_range():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    vals = [moon.libration(t0 + timedelta(days=d)) for d in range(0, 60, 2)]
    assert all(abs(l) < 8.2 and abs(b) < 7.0 for l, b in vals)
    assert max(abs(l) for l, _ in vals) > 4 and max(abs(b) for _, b in vals) > 5


def test_declination_extremes_two_weeks_apart():
    ext = moon.declination_extremes(moon.declination_series(datetime(2026, 11, 1, tzinfo=timezone.utc), 30))
    kinds = [k for _, _, k in ext]
    assert "max" in kinds and "min" in kinds
    gap = (ext[1][0] - ext[0][0]).total_seconds() / 86400
    assert ext[0][2] != ext[1][2] and 12 < gap < 15.5


def test_rise_transit_set_are_consistent():
    ev = moon.day_events(datetime(2026, 11, 25, tzinfo=timezone.utc), *ROME, 50.0, hours=48)
    assert ev["rises"] and ev["sets"] and ev["transits"]
    for t in ev["rises"] + ev["sets"]:
        assert abs(moon.azel(t, *ROME, 50.0)[2]) < 0.1
    t, el = ev["transits"][0]
    assert el > max(moon.azel(t + timedelta(minutes=m), *ROME, 50.0)[2] for m in (-20, 20))


def test_now_per_band_scales_with_frequency():
    n = moon.now(datetime(2026, 11, 25, 22, tzinfo=timezone.utc), *ROME, 50.0)
    b10, b24 = n["bands"]["10G"], n["bands"]["24G"]
    assert b24["doppler_hz"] / b10["doppler_hz"] == pytest.approx(24.0482 / 10.3682, rel=1e-6)
    assert b10["setup_assumed"] and n["wx_assumed"]
    assert b10["dgrd"]["total"] >= 0 and b24["dgrd"]["total"] > b10["dgrd"]["total"]
    assert n["t_gal_10g"] < 0.5


def test_moon_map_matches_libration_and_phase():
    """The rendered view agrees with the optical libration (Meeus) within 1°, and the full Moon is lit, the new Moon dark."""
    from emelab import moon_map
    for t in (datetime(2026, 11, 24, 15, tzinfo=timezone.utc), datetime(2026, 12, 9, 1, tzinfo=timezone.utc)):
        g = moon_map.geometry(t, 0.0, 0.0, 0.0)
        l_, b_ = moon.libration(t)
        assert abs(g["sub_obs"][0] - b_) < 1.0 and abs(g["sub_obs"][1] - l_) < 1.0
    full, _ = moon_map.render(datetime(2026, 11, 24, 15, tzinfo=timezone.utc), *ROME, 50.0, 120)
    new, info = moon_map.render(datetime(2026, 12, 9, 1, tzinfo=timezone.utc), *ROME, 50.0, 120)
    assert full.shape == (120, 120, 3) and full.mean() > 2.5 * new.mean()
    assert any(f["name"] == "Tycho" for f in info["features"])
