"""Bands shown as «10GHz», QSO IDs from 1 after emptying the log, wsjtx_log.adi path as pasted."""
import os
from datetime import datetime, timezone


def test_band_label():
    from emelab.stations import band_label, band_sort_key
    assert band_label("10G") == "10GHz"
    assert band_label("134G") == "134GHz"
    assert band_label(10.368) == "10GHz"
    assert band_label(122.25) == "122GHz"
    assert band_label(None) == "" and band_label("?") == "?"
    assert sorted(["122GHz", "24GHz", "10GHz"], key=band_sort_key) == ["10GHz", "24GHz", "122GHz"]


def test_qso_ids_restart_after_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import db as edb
    D = edb.DB()
    for i in range(3):
        D.add_qso(utc=datetime(2025, 1, 1, i, tzinfo=timezone.utc), call=f"K{i}XX", band="10G")
    D.clear_qsos()
    D.add_qso(utc=datetime(2025, 1, 2, tzinfo=timezone.utc), call="K1XX", band="10G")
    assert [q["id"] for q in D.qsos()] == [1]
    D.delete_qso(1)
    D.add_qso(utc=datetime(2025, 1, 3, tzinfo=timezone.utc), call="K2XX", band="10G")
    assert [q["id"] for q in D.qsos()] == [1]


def test_wsjtx_log_path_cleaning(tmp_path):
    from emelab.wsjtx_logfile import clean_path
    f = tmp_path / "wsjtx_log.adi"
    f.write_text("")
    assert clean_path(f'"{f}"') == str(f)                 # Windows «Copy as path» adds quotes
    assert clean_path(str(tmp_path)) == str(f)            # the folder of File → Open log directory
    assert clean_path("  ") == ""


def test_live_locators_and_short_checks(tmp_path):
    """Locators always in capitals (JN61PM); the Live WSJT-X chips are short."""
    from emelab import db, ui_live
    D = db.DB(tmp_path / "t.sqlite")
    D.save_station(callsign="IZ0JNY", locator="jn61pm")
    assert D.station()["locator"] == "JN61PM"
    D.upsert_station("ik3ghy", locator="jn65dm")
    assert D.station_of("IK3GHY")["locator"] == "JN65DM"
    assert ui_live.short_check({"Parametro": "Doppler tracking (finestra Astro)",
                                "WSJT-X adesso": "CFOM (Constant Frequency On Moon) (WSJT-X.ini)"}) == ("Doppler", "CFOM")
    assert ui_live.short_check({"Parametro": "Split Operation", "WSJT-X adesso": "Rig (WSJT-X.ini)"}) == ("Split", "Rig")


def test_db_waits_for_another_writer(tmp_path):
    """Two connections (UI and WSJT-X listener): the second writer waits instead of «database is locked»."""
    import threading, time
    from emelab import db
    a, b = db.DB(tmp_path / "t.sqlite"), db.DB(tmp_path / "t.sqlite")
    a.upsert_station("IK3GHY", locator="JN65DM")          # write transaction left open, as during a QRZ.com lookup
    threading.Timer(1.0, a.commit).start()
    t0 = time.time()
    b.save_station(callsign="IZ0JNY", locator="JN61PM")
    assert time.time() - t0 < 10 and b.station()["locator"] == "JN61PM"
    assert b.station_of("IK3GHY")["locator"] == "JN65DM"


def test_qrz_not_found_is_not_asked_again(tmp_path):
    from emelab import db, qrz
    D = db.DB(tmp_path / "t.sqlite")
    assert qrz.missing(D, ["W1XYZ", "IK3GHY"]) == ["W1XYZ", "IK3GHY"]
    qrz.mark_not_found(D, "W1XYZ")
    qrz.store(D, {"call": "IK3GHY", "fname": "Mario", "lname": "Rossi", "qth": "Venezia"})
    D.commit()
    assert qrz.missing(D, ["W1XYZ", "IK3GHY"]) == []
