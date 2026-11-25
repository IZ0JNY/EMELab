"""QSOs from WSJT-X logged by themselves: wsjtx_log.adi followed like «tail -f», UDP «QSO Logged», the EME ≥10 GHz
filter, and the same QSO from two sources (or already imported from ADIF) logged once."""
from datetime import datetime, timezone

import pytest

pytest.importorskip("erfa")


def rec(call="OK1KIR", t="170200", band="1.25cm", freq="24048.200", mode="MFSK", sub="Q65", prop=None):
    f = lambda k, v: f"<{k}:{len(v)}>{v} " if v else ""
    return (f("CALL", call) + f("GRIDSQUARE", "JN79DW") + f("MODE", mode) + f("SUBMODE", sub) + f("RST_SENT", "-17") +
            f("RST_RCVD", "-14") + f("QSO_DATE", "20260225") + f("TIME_ON", t) + f("BAND", band) + f("FREQ", freq) +
            f("PROP_MODE", prop) + f("MY_GRIDSQUARE", "JN61PM") + "<EOR>\n")


def test_eme_verdict():
    from emelab import logbook as lb
    q = {"call": "OK1KIR", "band": "24G", "mode": "Q65"}
    assert lb.eme_verdict(q) is None
    assert lb.eme_verdict({**q, "prop_mode": "EME"}, strict=True) is None
    assert lb.eme_verdict(q, strict=True) == "senza PROP_MODE=EME"
    assert lb.eme_verdict({**q, "prop_mode": "RS"}) == "propagazione RS"
    assert lb.eme_verdict({**q, "band": None}) == "sotto i 10 GHz"
    assert lb.eme_verdict({**q, "mode": "CW"}) == "non EME"
    assert lb.eme_verdict({**q, "mode": "CW"}, {"OK1KIR"}) is None
    assert lb.wsjtx_mode({"mode": "MFSK", "submode": "Q65"}) == {"mode": "Q65", "submode": None}


def test_log_tail_reads_only_appended_complete_records(tmp_path):
    from emelab.wsjtx_logfile import LogTail
    p = tmp_path / "wsjtx_log.adi"
    p.write_text("WSJT-X ADIF Export<eoh>\n" + rec(call="DL7YC"))
    t = LogTail(p)                                  # from the end: the old QSO is not read
    assert t.read_new() == []
    with open(p, "a") as f:
        f.write(rec()[:40])                          # WSJT-X still writing
    assert t.read_new() == []
    with open(p, "a") as f:
        f.write(rec()[40:])
    r = t.read_new()
    assert [x["CALL"] for x in r] == ["OK1KIR"] and t.read_new() == []
    p.write_text(rec(call="PA0PLY"))                 # new, shorter file: read from the start
    assert [x["CALL"] for x in t.read_new()] == ["PA0PLY"]
    assert [x["CALL"] for x in LogTail(p, 0).read_new()] == ["PA0PLY"]


def test_service_file_and_udp_same_qso_once_and_filter(tmp_path):
    from emelab import db as edb
    from emelab.wsjtx_service import Service
    D = edb.DB(tmp_path / "t.sqlite")
    s = Service(lambda: D, lambda: "JN61PM")
    s.status = {"submode": "D"}
    p = tmp_path / "wsjtx_log.adi"
    p.write_text("<eoh>\n")
    s.tail = __import__("emelab.wsjtx_logfile", fromlist=["LogTail"]).LogTail(p)
    seen = []
    s.on_tail_pos = lambda path, off: seen.append(off)
    s.poll_file()
    # UDP first (seconds 30), then the same QSO in the file (seconds 00): logged once
    t = datetime(2026, 2, 25, 17, 2, 30, tzinfo=timezone.utc)
    s.on_message({"type": "qso_logged", "id": "WSJT-X", "time_off": t, "time_on": t, "dx_call": "OK1KIR", "dx_grid": "JN79DW",
                  "tx_freq_hz": 24_048_200_000, "mode": "Q65", "report_sent": "-17", "report_rcvd": "-14", "tx_power": "",
                  "comments": "", "name": "", "operator": "", "my_call": "IZ0JNY", "my_grid": "JN61PM",
                  "exch_sent": "", "exch_rcvd": "", "prop_mode": ""}, None)
    with open(p, "a") as f:
        f.write(rec(t="170200"))
        f.write(rec(call="DL7YC", t="180000", prop="RS"))                     # rain scatter: out
        f.write(rec(call="PA0PLY", t="190000", band="2m", freq="144.120", sub="Q65", prop="EME"))   # below 10 GHz: out
        f.write(rec(call="OH2DG", t="200000", band="3cm", freq="10368.100", mode="MFSK", sub="Q65"))
    assert s.poll_file() == 4 and seen
    qs = {q["call"]: q for q in D.qsos()}
    assert set(qs) == {"OK1KIR", "OH2DG"}
    assert qs["OH2DG"]["mode"] == "Q65" and qs["OH2DG"]["submode"] == "D" and qs["OH2DG"]["band"] == "10G"
    st = {q["call"]: (q["duplicate"], q["skipped"]) for q in reversed(s.logged)}      # newest wins
    assert st["OK1KIR"] == (True, None) and st["DL7YC"][1] == "propagazione RS" and st["PA0PLY"][1] == "sotto i 10 GHz"
    s.strict_eme = True
    with open(p, "a") as f:
        f.write(rec(call="SP6JLW", t="210000"))
    s.poll_file()
    assert "SP6JLW" not in {q["call"] for q in D.qsos()}
    assert not s.errors


def test_qso_near_catches_adif_without_seconds(tmp_path):
    from emelab import db as edb
    D = edb.DB(tmp_path / "t.sqlite")
    D.add_qso(utc=datetime(2026, 2, 25, 17, 2, tzinfo=timezone.utc), call="OK1KIR", band="24G")
    assert D.qso_near("ok1kir", "24G", datetime(2026, 2, 25, 17, 8, 41, tzinfo=timezone.utc))
    assert not D.qso_near("OK1KIR", "10G", datetime(2026, 2, 25, 17, 8, tzinfo=timezone.utc))
    assert not D.qso_near("OK1KIR", "24G", datetime(2026, 2, 25, 18, 0, tzinfo=timezone.utc))


def test_settings_check_and_auto_fix(tmp_path):
    from emelab import db as edb, wsjtx_check
    from emelab.wsjtx_service import Service
    stn = {"callsign": "IZ0JNY", "locator": "JN61PM"}
    ok = {"dial_hz": 10_368_100_000, "mode": "Q65", "submode": "D", "tr_period": 60, "de_call": "IZ0JNY", "de_grid": "JN61"}
    assert wsjtx_check.check(ok, stn) == []
    p = wsjtx_check.check({**ok, "dial_hz": 24_048_100_000}, stn)          # 24 GHz wants 60E
    assert [x["code"] for x in p] == ["mode"] and p[0]["fix"] == "60E"
    p = wsjtx_check.check({**ok, "mode": "FT8", "submode": "", "dial_hz": 144_174_000, "de_grid": "JN45",
                           "tx_watchdog": True}, stn)
    assert {x["code"] for x in p} == {"band", "grid", "watchdog"}
    assert wsjtx_check.check({**ok, "tr_period": 0xFFFFFFFF}, stn) == []    # T/R not reported: submode only

    D = edb.DB(tmp_path / "t.sqlite")
    D.save_station(callsign="IZ0JNY", locator="JN61PM", lat=41.6, lon=13.3, height_m=0)
    s = Service(lambda: D, lambda: "JN61PM")
    sent = []
    s.set_q65 = lambda code: sent.append(code) or True
    s.on_message({"type": "status", "id": "WSJT-X", **ok, "submode": "E"}, None)
    assert sent == ["60D"] and s.problems and s.fixes
    s.on_message({"type": "status", "id": "WSJT-X", **ok, "submode": "E", "transmitting": True}, None)
    assert sent == ["60D"]                                                  # never while transmitting / too soon
    s._fix_try = {"60D": (3, None)}
    s.on_message({"type": "status", "id": "WSJT-X", **ok, "submode": "E"}, None)
    assert any(x["code"] == "udp_requests" for x in s.problems)
    s.on_message({"type": "status", "id": "WSJT-X", **ok}, None)
    assert s.problems == [] and not s.errors
