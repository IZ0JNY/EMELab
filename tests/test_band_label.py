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
