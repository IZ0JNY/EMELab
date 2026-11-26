def test_evaluate_measurement_without_expected_y():
    """A stored snapshot with no expected Y (e.g. Moon below the horizon) must not crash the measurement log."""
    from emelab import analysis
    ev = analysis.evaluate_measurement({"kind": "moon", "y_db": 0.75, "calc": {"moon": {"y_db": None}}}, {})
    assert ev["y_expected"] is None and ev["y_delta"] is None


def test_moon_tb_stored_with_measurement_snapshot():
    """A Moon measurement carries the Moon brightness temperature at that moment, with its model terms."""
    from datetime import datetime, timezone
    from emelab import analysis, sky
    stn = {"lat": 41.9, "lon": 12.5, "height_m": 50}
    setup = {"band_ghz": 24.048, "D_m": 1.5, "eta_ap": 0.6, "gain_dbi": 49.0, "nf_db": 1.0}
    c = analysis.snapshot(stn, setup, datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc))
    m = c["moon"]
    assert m["tb"] == sky.moon_tb(24.048, c["moon_phase_deg"])
    assert m["tb_min"] <= m["tb"] <= m["tb_max"]
    assert m["tb_model_band"] == 24 and m["tb_source"]


def test_moon_tb_peaks_after_full_moon_and_swing_grows_with_frequency():
    from emelab import sky
    for f in (10.368, 24.048, 47.088):
        d = sky.moon_tb_detail(f, 0.0)
        assert sky.moon_tb(f, d["lag_deg"]) == d["tb_max"]
    assert sky.moon_tb_detail(47.088, 0)["t1"] > sky.moon_tb_detail(24.048, 0)["t1"] > sky.moon_tb_detail(10.368, 0)["t1"]
    assert 190 < sky.moon_tb(10.368, 45) < 240
