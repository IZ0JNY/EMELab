"""⚡ Automatic filling of a Sun / Moon measurement: DriverDish (read only), weather, WSJT-X, with fallbacks."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from emelab import autofill

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
STN = {"lat": 41.9, "lon": 12.5, "height_m": 50.0}
STATUS = {"target": "Sun", "target_az": 180.20, "target_el": 30.10, "dish_az": 180.25, "dish_el": 30.08,
          "err_az": 0.05, "err_el": -0.02, "off_az": -0.24, "off_el": 0.10, "tracking": True, "moving": False}


def test_driverdish_fields_and_pointing_error():
    r = autofill.from_driverdish(STATUS, {"az": 180.0, "el": 30.0, "el_radio": 30.02})
    assert r["fields"] == {"az_read": 180.25, "el_read": 30.08, "az_off": -0.24, "el_off": 0.1, "kind": "sun"}
    x = r["extra"]
    assert x["target"] == "Sun" and x["tracking"] is True
    assert abs(x["err_deg"] - 0.0476) < 0.002
    assert x["dish_minus_calc_az"] == 0.25 and x["dish_minus_calc_el"] == 0.06
    # AZ difference across north
    r = autofill.from_driverdish(dict(STATUS, dish_az=0.1), {"az": 359.9, "el": 30.0})
    assert abs(r["extra"]["dish_minus_calc_az"] - 0.2) < 1e-9
    assert autofill.target_kind("Moon") == "moon" and autofill.target_kind("LUNA") == "moon"
    assert autofill.target_kind("Cas A") is None and autofill.target_kind(None) is None


def test_driverdish_monitor_is_used_when_fresh_otherwise_telnet(monkeypatch):
    mon = SimpleNamespace(last=dict(STATUS, raw="…", utc=NOW - timedelta(seconds=3)))
    r = autofill.read_driverdish("127.0.0.1", 9999, mon, NOW)
    assert r["via"] == "monitor" and "raw" not in r["status"] and r["status"]["dish_az"] == 180.25
    asked = []

    def fake(cmds, host, port, timeout):
        asked.append(cmds)
        return {"status": "Target: Moon\r\nDish Pos AZ: 100.0 EL:20.0\r\nTRACKING ON"}
    monkeypatch.setattr(autofill.ea3hmj, "driverdish_query", fake)
    old = SimpleNamespace(last=dict(STATUS, utc=NOW - timedelta(minutes=5)))
    r = autofill.read_driverdish("127.0.0.1", 9999, old, NOW)
    assert r["via"] == "telnet" and r["status"]["target"] == "Moon" and r["status"]["dish_el"] == 20.0
    assert asked == [["status"]]                       # only the read-only command


def test_wsjtx_frequency_and_matching_setup():
    st = {"dial_hz": 24_048_100_000, "mode": "Q65", "submode": "E"}
    w = autofill.from_wsjtx(st, NOW - timedelta(seconds=10), NOW)
    assert w["band"] == "24G" and w["band_label"] == "24GHz" and abs(w["freq_mhz"] - 24048.1) < 1e-6
    assert autofill.from_wsjtx(st, NOW - timedelta(minutes=5), NOW) is None       # WSJT-X not talking any more
    assert autofill.from_wsjtx({}, NOW, NOW) is None
    sets = [{"id": 1, "band_ghz": 10.368}, {"id": 2, "band_ghz": 24.048}]
    assert autofill.setup_for_band(sets, 24048.1, 1) == 2
    assert autofill.setup_for_band(sets, 24048.1, 2) == 2
    assert autofill.setup_for_band(sets, 47088.0, 1) == 1                        # no setup for that band
    assert autofill.setup_for_band(sets, None, 1) == 1


def test_weather_station_first_then_open_meteo():
    now = datetime.now(timezone.utc)
    stn_fn = lambda url: {"t_c": 5.0, "rh": 80.0, "p_hpa": 1010.0, "wx_source": "stazione"}
    om_fn = lambda lat, lon, dt: {"t_c": 7.0, "rh": 70.0, "p_hpa": 1012.0, "cloud_pct": 40.0, "wx_source": "Open-Meteo"}
    assert autofill.read_weather(1, 2, now, "http://x", stn_fn, om_fn)["wx_source"] == "stazione"

    def bad(url):
        raise OSError("timeout")
    w = autofill.read_weather(1, 2, now, "http://x", bad, om_fn)
    assert w["wx_source"] == "Open-Meteo" and w["tried"] == [("station", "timeout")]
    # an old measurement never uses the station (it only knows the present)
    assert autofill.read_weather(1, 2, now - timedelta(days=1), "http://x", stn_fn, om_fn)["wx_source"] == "Open-Meteo"

    def om_bad(*a):
        raise OSError("offline")
    w = autofill.read_weather(1, 2, now, "", None, om_bad)
    assert w["tried"] == [("Open-Meteo", "offline")] and "t_c" not in w


def test_collect_every_source_and_fallbacks():
    dd = lambda: {"status": STATUS, "utc": "2026-11-25T12:00:00Z", "via": "telnet"}
    wx = lambda: {"t_c": 7.04, "rh": 70.0, "p_hpa": 1012.0, "cloud_pct": 40.0, "rain_mmh": 0.0,
                  "wx_source": "Open-Meteo", "wx_utc": "2026-11-25T12:00:00Z"}
    r = autofill.collect(STN, {}, NOW, dd_reader=dd, wx_reader=wx,
                         wsjtx_status={"dial_hz": 10_368_100_000, "mode": "Q65", "submode": "D"},
                         wsjtx_seen=NOW - timedelta(seconds=5), now=NOW)
    f, x = r["fields"], r["extra"]
    assert f["wx_t_c"] == 7.04 and f["wx_cloud_pct"] == 40.0 and f["wx_source"] == "Open-Meteo"
    assert x["driverdish"]["dish_az"] == 180.25 and x["wsjtx"]["band"] == "10G" and "gpsdo" not in x
    assert all(ok for _, ok, _ in r["report"])

    def down():
        raise ConnectionRefusedError("connection refused")
    r = autofill.collect(STN, {}, NOW, dd_reader=down, wx_reader=lambda: {"tried": [("Open-Meteo", "x")]},
                         now=NOW)
    assert "driverdish" not in r["extra"] and not r["fields"]
    rep = {s: ok for s, ok, _ in r["report"]}
    assert rep == {"DriverDish": False, "meteo": False, "WSJT-X": False}


def test_saved_with_the_measurement(tmp_path):
    from emelab import db as edb
    D = edb.DB(tmp_path / "m.sqlite")
    r = autofill.collect(STN, {}, NOW, dd_reader=lambda: {"status": STATUS, "utc": "x", "via": "monitor"},
                         wx_reader=lambda: {}, now=NOW)
    D.add(utc=NOW, setup_id=1, band_ghz=10.368, kind="sun", y_db=12.0, az_read=180.25, el_read=30.08, extra=r["extra"])
    m = D.measurements()[0]
    assert m["extra"]["driverdish"]["target"] == "Sun" and m["extra"]["auto_utc"] == "2026-11-25T12:00:00Z"
    assert autofill.age_s(m["extra"]["auto_utc"], NOW + timedelta(minutes=2)) == 120


def test_new_measurement_tab_fills_itself_from_driverdish(tmp_path, monkeypatch):
    """The «➕ New measurement» tab, opened with a (fake) DriverDish on telnet, fills AZ/EL, offsets, kind and weather;
    only read-only commands reach DriverDish and the reading is saved with the measurement."""
    import os
    import pytest
    pytest.importorskip("erfa")
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from emelab import ea3hmj, i18n, settings
    from tests.test_driverdish_live import _fake_driverdish
    from tests.test_language_consistency import ROOT, _demo_station
    received = []
    srv = _fake_driverdish(received)
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    monkeypatch.setattr(autofill, "read_weather", lambda *a, **k: {"t_c": 3.5, "rh": 91.0, "p_hpa": 1004.0,
                                                                   "cloud_pct": 100.0, "rain_mmh": 0.4,
                                                                   "wx_source": "Open-Meteo", "wx_utc": "2026-11-25T12:00:00Z"})
    _demo_station(tmp_path)
    settings.save_settings(dd_host="127.0.0.1", dd_port=srv.getsockname()[1], dd_live=False)
    try:
        at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        assert "em_af" not in at.session_state                        # nothing read while another tab is open
        at.session_state["main_tab"] = "➕ Nuova misura"               # the user opens the tab
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        ss = at.session_state
        assert ss["em_af"]["extra"]["driverdish"]["target"] == "Moon"
        assert ss["em_n_azr"] == 141.095 and ss["em_n_elr"] == 36.367 and ss["em_n_azo"] == -0.24
        assert ss["em_n_kind"] == "moon" and ss["em_wx_t_c"] == 3.5 and ss["em_wx_cloud_pct"] == 100.0
        assert at.number_input(key="em_n_azr").value == 141.095          # shown in the form, still editable
        at.number_input(key="em_n_azr").set_value(141.2)
        # Y in two clicks: cold sky, then the Moon
        at.number_input(key="em_y_level").set_value(-62.40)
        at.button(key="em_y_cold_btn").click().run()
        at.number_input(key="em_y_level").set_value(-61.65)
        at.button(key="em_y_hot_btn").click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert at.session_state["em_n_y"] == 0.75 and at.number_input(key="em_n_y").value == 0.75
        at.button(key="em_n_save").click().run()
        assert not at.exception, [e.value for e in at.exception]
        from emelab import db as edb
        m = edb.DB().measurements()[-1]
        assert m["az_read"] == 141.2 and m["extra"]["driverdish"]["dish_az"] == 141.095
        assert m["extra"]["weather"]["wx_source"] == "Open-Meteo" and m["t_c"] == 3.5
        assert m["y_db"] == 0.75 and m["extra"]["y_capture"]["cold"]["db"] == -62.4
        assert m["extra"]["y_capture"]["hot"]["kind"] == "moon"
    finally:
        i18n.set_lang("it")
        srv.close()
    assert received and set(received) <= set(ea3hmj.READ_COMMANDS) | {"exit"}


def test_y_delta():
    assert autofill.y_delta(-62.4, -50.15) == 12.25
    assert autofill.y_delta(None, 3.0) is None
