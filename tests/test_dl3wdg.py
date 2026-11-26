"""Advice from DL3WDG's «Using WSJT-X for Microwave EME» (EME 2022): 60D/60E note, WSJT-X.ini decoding options,
«no decode» checklist and the Echo mode file all_echo.txt."""
from datetime import timedelta

import pytest

from emelab import dx, echo, wsjtx_ini

ECHO = """\
261027_203030  20.5083  64.07   43664   249.7  -0.3     1     0    -53  -17.7     1.5    0
261027_203036  20.5100  64.32   43652   249.7  -0.3     2     0    -22  -20.1     1.3    0
261027_203042  20.5117  64.56   43641   249.7  -0.3     3     0    -22  -20.2     1.0    0
261027_203048  20.5133  64.69   43629   249.7  -0.3     4     0    -22  -21.3     0.9    0
261027_203054  20.5150  64.35   43617   249.8  -0.3     5     0    -37  -22.1     0.8    0
261027_203100  20.5167  64.26   43606   249.9  -0.3     6     1    -38  -21.3     0.7    0
261027_203106  20.5183  64.13   43594   249.9  -0.3     7     2    -22  -20.5     0.7    0
261027_203418  20.5717  65.99   43225   251.0  -0.3     8     0    52  -99.0     0.4    0
261027_203421  20.5725  65.98   43219   250.9  -0.3     9     0    99  -99.0     0.3    0
garbage line
"""


def test_mode_hint_60e_beats_60d_above_70hz():
    assert dx.mode_hint("60D", 40) is None
    h = dx.mode_hint("60D", 250)
    assert h["mode"] == "60E" and 0.5 < h["gain_db"] < 2.0
    assert dx.mode_hint("60E", 250) is None
    assert dx.mode_hint("120E", 250) is None


def test_echo_runs_and_summary():
    rows = echo.parse(ECHO)
    assert len(rows) == 9 and rows[0]["width_hz"] == 249.7 and rows[0]["snr_db"] == -17.7
    runs = echo.runs(rows)
    assert [len(r) for r in runs] == [7, 2]                  # the pause of more than a minute starts a new run
    s = echo.summary(runs[0])
    assert s["echo"] and s["cycles"] == 7
    assert s["snr_db"] == pytest.approx(sum([-20.2, -21.3, -22.1, -21.3, -20.5]) / 5)
    assert s["snr_1hz_db"] == pytest.approx(s["snr_db"] + 33.98, abs=0.01)
    assert s["settled"]
    none = echo.summary(runs[1])
    assert not none["echo"] and none["snr_db"] is None and not none["settled"]
    assert runs[1][0]["utc"] - runs[0][-1]["utc"] > timedelta(seconds=60)


def test_echo_read_and_find(tmp_path):
    (tmp_path / "WSJT-X.ini").write_text("[General]\n")
    (tmp_path / "all_echo.txt").write_text(ECHO)
    assert echo.find(tmp_path / "WSJT-X.ini") == tmp_path / "all_echo.txt"
    out = echo.read(tmp_path / "all_echo.txt")
    assert len(out) == 2 and not out[0]["echo"] and out[1]["echo"]          # newest first
    assert echo.read(tmp_path / "missing.txt") == []


INI = """[Configuration]
MyGrid=JN61
VHFUHF=true
Decode52=false
SingleDecode=false
[Astro]
DopplerTracking=true
DopplerMethod=2
[Common]
NDepth=2
AutoClearAvg=false
MaxDrift=0
[WideGraph]
Flatten=false
UseRef=true
"""


def test_ini_extras_and_advice(tmp_path):
    p = tmp_path / "WSJT-X.ini"
    p.write_text(INI)
    r = wsjtx_ini.read(p)
    assert r["depth"] == "Normal" and r["averaging"] is False and r["single_decode"] is False
    assert r["decode52"] is False and r["vhf"] is True and r["my_grid"] == "JN61" and r["use_ref"] and r["flatten"] is False
    codes = {a["code"] for a in wsjtx_ini.advice(r, {"dx_call": "", "dx_grid": ""})}
    assert codes == {"avg", "depth", "single", "decode52", "grid6", "refspec", "dxcall"}
    p.write_text(INI.replace("NDepth=2", "NDepth=19").replace("AutoClearAvg=false", "AutoClearAvg=true")
                 .replace("MyGrid=JN61", "MyGrid=JN61PM").replace("Decode52=false", "Decode52=true")
                 .replace("SingleDecode=false", "SingleDecode=true").replace("Flatten=false", "Flatten=true"))
    r = wsjtx_ini.read(p)
    assert r["depth"] == "Deep" and r["averaging"] and r["auto_clear_avg"]
    assert wsjtx_ini.advice(r, {"dx_call": "UN6PD", "dx_grid": "MN69JM"}) == []
    assert wsjtx_ini.advice({}) == []


def test_no_decode_rows():
    pytest.importorskip("streamlit")
    from emelab import ui_wsjtx_panel as p
    rows = p.no_decode_rows({"mode": "Q65", "submode": "E", "tr_period": 60, "freq_tolerance": 200},
                            {"depth": "Fast", "doppler": "CFOM", "max_drift": 0},
                            {"ntp": {"offset_s": 0.9, "server": "x"}, "bkt": {"running": True}}, {"gpsdo_use": False})
    by = {r["Causa possibile"].split(" (")[0]: r for r in rows}
    assert "Q65-60E" in by["Sottomodo diverso da quello del corrispondente"]["Causa possibile"]
    assert by["Orologio del PC sbagliato o corretto a metà periodo"]["Stato"] == p.BAD
    assert by["Decodifica Fast o Normal"]["Stato"] == p.BAD
    assert by["Doppler tracking spento o diverso dal corrispondente"]["Stato"] == p.OK
    assert by["Segnale che deriva o instabile"]["Stato"] == p.OK


def test_refspec_due(tmp_path):
    from datetime import datetime, timezone
    from emelab import refspec
    (tmp_path / "WSJT-X.ini").write_text("[General]\n")
    assert refspec.find(tmp_path / "WSJT-X.ini") is None
    (tmp_path / "refspec.dat").write_text("x")
    f = refspec.find(tmp_path / "WSJT-X.ini")
    m = refspec.measured_utc(f)
    assert f and m
    before, after = m - timedelta(hours=1), m + timedelta(hours=1)
    assert not refspec.due(m, None)                       # WSJT-X not heard yet: no session
    assert not refspec.due(m, before)                     # measured after the session started
    assert refspec.due(m, after)                          # older than the session
    assert refspec.due(None, after)
    assert not refspec.due(m, after, (after + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert refspec.due(m, after, (after - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
