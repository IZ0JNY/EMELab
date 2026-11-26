"""Y factor from the Continuum CSV of SDR Console (read only)."""
import os
from datetime import date, datetime, timedelta, timezone

from emelab import sdrconsole

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(HERE, "data", "sdrconsole_continuum.csv")   # start of IZ0JNY's export, 26-11-2026 (24 GHz, cold sky)

HEADER = ("# SDR Console version 3.4 build 4138 : Continuum Mode\r\n#\r\n# Created   : 26/11/2026 {created}\r\n"
          "# Interval  : 50 ms\r\n# Level     : dBm\r\n# Date      : UTC\r\n#\r\n\"Time\",\"Level\",\"Frequency\",\"Bandwidth\"\r\n")


def _synthetic(cold=-79.0, hot=-67.0, start="11:59:50", created="13:01:00"):
    """20 s of cold sky, then 20 s on the Sun, 50 ms apart, small noise."""
    h, m, s = map(int, start.split(":"))
    t0 = h * 3600 + m * 60 + s
    rows = []
    for i in range(800):
        sec = t0 + i * 0.05
        lvl = (cold if i < 400 else hot) + (0.1 if i % 2 else -0.1)
        hh, rem = divmod(sec, 3600)
        mm, ss = divmod(rem, 60)
        rows.append(f"{int(hh) % 24:02d}:{int(mm):02d}:{ss:06.3f},{lvl:.2f},,24048116.-776,1300\r\n")
    return HEADER.format(created=created) + "".join(rows) + "# End\r\n"


def test_real_export_is_read():
    r = sdrconsole.read(REAL)
    assert r["unit"] == "dBm" and "Continuum" in r["meta"]["program"]
    t, lvl, fmhz, bw = r["samples"][0]
    assert t == datetime(2026, 11, 26, 8, 54, 6, 800000, tzinfo=timezone.utc)
    assert lvl == -79.04 and abs(fmhz - 24048.116776) < 1e-6 and bw == 1300.0
    assert all(-80 < s[1] < -78 for s in r["samples"])


def test_y_from_cold_sky_then_sun():
    r = sdrconsole.parse(_synthetic())
    w = sdrconsole.auto_windows(r["samples"])
    assert w["cold"][1] < datetime(2026, 11, 26, 12, 0, 10, tzinfo=timezone.utc) <= w["hot"][0]
    y = sdrconsole.y_from(r["samples"], w["cold"], w["hot"])
    assert abs(y["y_db"] - 12.0) < 0.01 and y["y_err"] < 0.02
    assert y["cold"]["n"] > 150 and y["hot"]["n"] > 80


def test_date_and_midnight():
    # Created is local time (UTC+1): 00:30 local on the 27th is still the 26th in UTC
    r = sdrconsole.parse(_synthetic(start="23:30:00", created="00:31:00").replace("26/11/2026", "27/11/2026"))
    assert r["samples"][0][0].date() == date(2026, 11, 26)
    # a recording across midnight UTC
    r = sdrconsole.parse(_synthetic(start="23:59:50", created="01:01:00").replace("26/11/2026", "27/11/2026"))
    assert r["samples"][0][0].date() == date(2026, 11, 26) and r["samples"][-1][0].date() == date(2026, 11, 27)
    assert all(b[0] > a[0] for a, b in zip(r["samples"], r["samples"][1:]))


def test_latest_csv(tmp_path):
    assert sdrconsole.latest_csv(tmp_path) is None
    a, b = tmp_path / "a.csv", tmp_path / "B.CSV"
    a.write_text("x"); b.write_text("y")
    os.utime(a, (1, 1))
    assert sdrconsole.latest_csv(tmp_path) == b
    assert sdrconsole.latest_csv(tmp_path / "nope") is None


def test_new_measurement_uses_the_csv(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("erfa")
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from emelab import autofill, i18n, settings
    from tests.test_language_consistency import ROOT, _demo_station
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    monkeypatch.setattr(autofill, "read_weather", lambda *a, **k: {"tried": []})
    _demo_station(tmp_path)
    folder = tmp_path / "SDR Console"
    folder.mkdir()
    (folder / "SDR.CSV").write_text(_synthetic())
    settings.save_settings(dd_port=1, em_autofill=False, sdrc_dir=str(folder))
    try:
        at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
        at.session_state["main_tab"] = "➕ Nuova misura"
        at.session_state["em_n_kind"] = "sun"
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        at.button(key="em_sdrc_latest").click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert at.session_state["em_sdrc"]["name"] == "SDR.CSV"
        at.button(key="em_sdrc_use").click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert abs(at.session_state["em_n_y"] - 12.0) < 0.01
        assert at.session_state["em_n_time"].hour == 12 and at.session_state["em_y_hot"]["source"] == "SDR Console"
        at.button(key="em_n_save").click().run()
        from emelab import db as edb
        m = edb.DB().measurements()[-1]
        assert abs(m["y_db"] - 12.0) < 0.01 and m["extra"]["y_capture"]["sdr_console"]["file"] == "SDR.CSV"
        assert m["utc"].startswith("2026-11-26T12:00")
    finally:
        i18n.set_lang("it")
