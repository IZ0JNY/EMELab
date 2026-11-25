from datetime import datetime, timezone

import numpy as np

from emelab import catalog, chain, dx, plots, solar, wizard


def test_q65_thresholds_and_best_mode():
    assert abs(dx.q65_threshold_db("60D", 0) + 28.285) < 1e-6
    m, thr = dx.best_mode(300)
    assert m in ("60D", "60E", "120E") and -32 < thr < -20


def test_band_mode_is_the_operating_standard_not_the_lowest_threshold():
    assert dx.band_mode("10G", {}) == "60D"
    assert dx.band_mode("24G", {}) == "60E"
    assert dx.band_mode("47G", {}) == "60E"
    assert dx.band_mode("24G", {"q65_modes": {"24G": "120E"}}) == "120E"
    assert dx.band_mode("24G", {"q65_modes": {"24G": "bogus"}}) == "60E"
    assert dx.best_mode(260)[0] == "120E"          # lowest threshold, but not what is used on the air


def test_q65_threshold_penalised_beyond_spread_tolerance():
    assert dx.spread_ok("60D", 500) and not dx.spread_ok("60D", 700)
    at, beyond = dx.q65_threshold_db("60D", 550), dx.q65_threshold_db("60D", 800)
    assert beyond > at + 1.0                        # keeps rising instead of staying flat


def test_link_uses_the_band_mode():
    a = dx.station("24G", 2.4, 20)
    t = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    for h in range(0, 24):
        r = dx.link_at(t.replace(hour=h), a, (42.0, 13.0), a, (52.0, 5.0), "24G", mode="60E")
        if r:
            assert r["mode"] == "60E"
            assert abs(r["threshold_db"] - dx.q65_threshold_db("60E", r["spread_hz"])) < 1e-9
            break


def test_bistatic_link_symmetric_for_equal_stations():
    a = dx.station("10G", 2.4, 50)
    t = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    r = dx.link_at(t, a, (52.0, 5.0), a, (52.1, 5.2), "10G")
    if r:
        assert abs(r["snr_a_hears_b"] - r["snr_b_hears_a"]) < 0.3


def test_antenna_parser():
    assert dx.antenna_m("2.4m dish OS") == (2.4, "offset")
    assert dx.antenna_m("120 cm")[0] == 1.2


def test_learn_offset():
    o = dx.learn_offset([(-15, -13), (-18, -16), (-12, -10)])
    assert o["n"] == 3 and abs(o["offset_db"] + 2) < 1e-9


def test_fits():
    x = np.linspace(0, 10, 50)
    y = 1 + 2 * x
    f = plots.fit(x, y, "linear")
    assert abs(f["coef"][0] - 2) < 1e-9 and f["r2"] > 0.999
    assert plots.fit(x, y, "loess")["rmse"] < 1e-6
    assert len(plots.fit(x, y, "bins")["xs"]) >= 4


def test_saleh_saturates_at_psat():
    p = chain.saleh_drive_for_sat(43, 35)
    out, _ = chain.saleh(p, 43, 35)
    assert abs(out - 43) < 1e-6 and chain.saleh(p + 6, 43, 35)[0] < 43


def test_heatsink():
    h = catalog.heatsink(20, 25, 1.5, 0.2, 35, 150, 0.5)
    assert h["p_diss_w"] == 60 and h["ok"] and 0.3 < h["rsa_max"] < 0.6


def test_datasheet_reader():
    v = catalog.read_datasheet("Frequency 17 - 27 GHz Gain 25 dB Noise Figure 2.2 dB Vdd 3 V Idd 75 mA")
    assert v["f_lo"] == 17 and v["nf_db"] == 2.2 and abs(v["idc_a"] - 0.075) < 1e-9


def test_solar_interp_power_law():
    assert abs(solar.interp({8800: 200, 15400: 500}, 15.4) - 500) < 1e-6
    assert solar.xray_class(2.3e-5).startswith("M2.3")


def test_horizon_and_windows():
    hz = [{"az_da": 90, "az_a": 270, "el_min": 10}]
    assert wizard.el_min(hz, 180) == 10 and wizard.el_min(hz, 0) == 90
    ws = wizard.moon_windows(41.5, 13.3, 0, wizard.default_horizon(10), datetime(2026, 11, 25, tzinfo=timezone.utc), 2, 20)
    assert ws and all(w["best_el"] >= 10 for w in ws)
    assert "IZ0JNY" in wizard.sked_text("en", "IZ0JNY", "JN61", "OK1KIR", None, "24G", ws[0]["start"], ws[0]["end"], "60D",
                                        True, -15, -16)


def test_station_history(tmp_path):
    from emelab import db as edb
    D = edb.DB(tmp_path / "t.sqlite")
    D.save_history("10G", [{"from_utc": datetime(2024, 7, 1, tzinfo=timezone.utc), "dish_m": 1.0, "power_w": 20},
                           {"from_utc": datetime(2025, 6, 20, tzinfo=timezone.utc), "dish_m": 1.2, "power_w": 20},
                           {"from_utc": datetime(2026, 9, 1, tzinfo=timezone.utc), "dish_m": 2.4, "power_w": 6}])
    assert D.setup_at("10G", datetime(2025, 1, 1, tzinfo=timezone.utc))["dish_m"] == 1.0
    assert D.setup_at("10G", datetime(2026, 1, 1, tzinfo=timezone.utc))["dish_m"] == 1.2
    assert D.setup_at("10G", datetime(2026, 11, 1, tzinfo=timezone.utc))["power_w"] == 6
    assert D.setup_at("10G", datetime(2024, 1, 1, tzinfo=timezone.utc)) is None
    assert D.setup_at("24G", datetime(2026, 1, 1, tzinfo=timezone.utc)) is None


def test_q65_mode_label_from_adif():
    from emelab import logbook as lb
    assert lb.mode_label({"mode": "MFSK", "submode": "Q65", "band": "10G"}, ) == ("Q65-60D", True)
    assert lb.mode_label({"mode": "MFSK", "submode": "Q65", "band": "24G"}) == ("Q65-60E", True)
    assert lb.mode_label({"mode": "MFSK", "submode": "Q65", "band": "24G", "comment": "Q65-120A sked"}) == ("Q65-120A", False)
    assert lb.mode_label({"mode": "Q65", "submode": "60D", "band": "24G"}) == ("Q65-60D", False)
    assert lb.mode_label({"mode": "MFSK", "submode": "Q65", "band": "24G", "comment": "OH60A"})[1]   # a call, not a mode
    assert lb.mode_label({"mode": "MFSK", "submode": "FST4", "band": "10G"}) == ("FST4", False)
    assert lb.mode_label({"mode": "CW", "band": "10G"}) == ("CW", False)
    assert "60D" in lb.Q65_SUBMODES and "300E" in lb.Q65_SUBMODES and len(lb.Q65_SUBMODES) == 25
