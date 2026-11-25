"""WSJT-X ALL.TXT read directly: only 10 GHz and up, followed live, statistics per band, station and session."""
from datetime import datetime, timezone

from emelab import alltxt, db as edb

SAMPLE = """\
251120_183000    14.074 Rx FT8    -10  0.1 1234 CQ DL1ABC JO62
251120_200000 10368.100 Tx Q65      0  0.0 1000 CQ IZ0XXX JN61
251120_200100 10368.100 Rx Q65    -21  2.6 1012 IZ0XXX OK1KIR JO70   q3
251120_200300 10368.100 Rx Q65    -19  2.7 1010 IZ0XXX OK1KIR R-20   q3
251120_200500 10368.100 Rx Q65    -18  2.6 1008 IZ0XXX OK1KIR RR73
251120_200600 10368.100 Rx Q65    -24  2.4 1100 CQ PA0PLY JO32   a2
251120_200700 10368.100 Tx Q65      0  0.0 1000 OK1KIR IZ0XXX 73
251121_201000 24048.100 Rx Q65    -15  2.8  700 CQ OK1KIR JO70
251121_201200 24048.100 Rx Q65    -16  2.9  690 CQ OK1KIR JO70
"""


def test_parse_keeps_only_10ghz_and_up():
    rows = alltxt.parse_eme(SAMPLE.splitlines())
    assert all(r["band"] in ("10G", "24G") for r in rows)
    assert len(rows) == 8
    r = rows[1]
    assert (r["rxtx"], r["call"], r["locator"], r["snr_db"], r["dt_s"], r["df_hz"]) == ("Rx", "OK1KIR", "JO70", -21, 2.6, 1012)
    assert r["message"] == "IZ0XXX OK1KIR JO70"            # Q65 «q3» mark removed
    assert rows[4]["call"] == "PA0PLY" and rows[4]["message"] == "CQ PA0PLY JO32"
    assert rows[0]["rxtx"] == "Tx" and rows[0]["call"] is None
    assert rows[5]["call"] == "OK1KIR"                      # who I was calling


def test_tail_reads_only_complete_new_lines(tmp_path):
    p = tmp_path / "ALL.TXT"
    p.write_text(SAMPLE[:SAMPLE.index("251120_200300")])
    t = alltxt.LineTail(p, 0)
    assert len(t.read_new()) == 3
    with open(p, "a") as f:
        f.write("251120_200300 10368.100 Rx Q65    -19  2.7 1010 IZ0XXX OK1KIR R-20")   # no newline yet
    assert t.read_new() == []
    with open(p, "a") as f:
        f.write("\n")
    assert len(t.read_new()) == 1
    assert t.behind == 0


def test_store_is_idempotent_and_fills_heard(tmp_path):
    D = edb.DB(tmp_path / "e.sqlite")
    D.upsert_station("OK1KIR", locator="JO70EB", eme=1, data={"directory": {"10G": {}}})
    rows = alltxt.parse_eme(SAMPLE.splitlines())
    r1 = alltxt.store(D, rows)
    r2 = alltxt.store(D, rows)
    assert (r1["new_rx"], r2["new_rx"]) == (6, 0)
    h = D.station_of("OK1KIR")["data"]["heard"]
    assert h["n"] == 5 and h["snr_best"] == -15 and h["bands"] == ["10G", "24G"]
    assert D.station_of("OK1KIR")["locator"] == "JO70EB"    # 4-character grid never replaces a 6-character locator
    assert len(D.tx_lines()) == 2
    D.remove_station_source("heard")
    assert D.eme_decodes() == [] and D.tx_lines() == []


def test_summary_sessions_heard_not_worked(tmp_path):
    D = edb.DB(tmp_path / "e.sqlite")
    alltxt.store(D, alltxt.parse_eme(SAMPLE.splitlines()))
    qsos = [{"call": "OK1KIR", "band": "10G", "utc": "2025-11-20T20:07:00Z"}]
    s = alltxt.summarize(D.eme_decodes(), D.tx_lines(), qsos, "IZ0XXX", lambda *a: -1234.0)
    assert s["n_rx"] == 6 and s["n_tx"] == 2
    assert [x["band"] for x in s["sessions"]] == ["10G", "24G"]
    s10 = s["sessions"][0]
    assert s10["n_rx"] == 4 and s10["n_tx"] == 2 and s10["worked"] == ["OK1KIR"] and s10["snr_best"] == -18
    kir10 = next(x for x in s["stations"] if (x["call"], x["band"]) == ("OK1KIR", "10G"))
    assert kir10["worked"] and kir10["to_me"] == 3 and kir10["df_min"] == 1008 and kir10["df_max"] == 1012
    assert kir10["df_drift"] is not None and kir10["df_drift"] < 0
    assert kir10["doppler_hz"] == -1234.0
    hnw = {(x["call"], x["band"]) for x in s["heard_not_worked"]}
    assert hnw == {("PA0PLY", "10G"), ("OK1KIR", "24G")}
    assert s["bands"]["10G"]["stations"] == 2 and s["by_hour"]["10G"][20] == 4


def test_find_default_next_to_wsjtx_log(tmp_path, monkeypatch):
    d = tmp_path / "WSJT-X"
    d.mkdir()
    (d / "ALL.TXT").write_text("")
    monkeypatch.setattr(alltxt.wsjtx_logfile, "default_paths", lambda: [d / "wsjtx_log.adi"])
    assert alltxt.find_default() == d / "ALL.TXT"
    assert alltxt.clean_path(f'"{d}"') == str(d / "ALL.TXT")


def test_service_follows_alltxt(tmp_path):
    from emelab import wsjtx_service
    p = tmp_path / "ALL.TXT"
    p.write_text(SAMPLE)
    svc = wsjtx_service.Service(lambda: edb.DB(tmp_path / "e.sqlite"), lambda: "JN61")
    svc.all_tail = alltxt.LineTail(p, 0)
    svc.poll_alltxt()
    assert svc.all_read["rx"] == 6 and svc.all_recent[0]["call"] == "OK1KIR"
    assert svc.all_recent[0]["utc"] == datetime(2025, 11, 21, 20, 12, tzinfo=timezone.utc)


def test_app_shows_alltxt_live_and_stats_in_english(tmp_path, monkeypatch):
    """ALL.TXT followed from the settings at start, live panes and statistics rendered; in English no Italian left."""
    import os
    import time

    import pytest
    pytest.importorskip("erfa")
    from streamlit.testing.v1 import AppTest

    from emelab import i18n, settings
    from tests.test_language_consistency import ITALIAN_MARKERS, _visible_texts
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "en")
    p = tmp_path / "ALL.TXT"
    p.write_text(SAMPLE)
    D = edb.DB()
    D.save_station(callsign="IZ0XXX", locator="JN61", lat=41.5, lon=13.0, height_m=100.0)
    alltxt.store(D, alltxt.parse_eme(SAMPLE.splitlines()))
    settings.save_settings(wsjtx_all_on=True, wsjtx_all=str(p), wsjtx_all_pos={"path": str(p), "offset": 0})
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=120)
        at.run()
        time.sleep(1.5)                     # the background reader has the file by now
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        texts = _visible_texts(at)
        md = " ".join(t for k, t in texts)
        assert "Band Activity" in md and "OK1KIR" in md
        assert any(k == "subheader" and "Heard in WSJT-X ALL.TXT" in t for k, t in texts)
        bad = [(k, t[:120], m) for k, t in texts for m in ITALIAN_MARKERS if m in t]
        assert not bad, bad
    finally:
        i18n.set_lang("it")
        from emelab import ui
        ui._wsjtx_service().stop_alltxt()
