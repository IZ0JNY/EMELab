# SPDX-License-Identifier: GPL-3.0-or-later
"""🔌 nanoHam tab: protocol, channels, alarms, link state per board, settings and the tab in both languages."""
import csv
import os
import time

from emelab import nanoham as link


def test_parse_line():
    assert link.parse_line(b"CH1,7.532\n") == (1, 7.532)
    assert link.parse_line("CH4,0.000\r\n") == (4, 0.0)
    assert link.parse_line("CH12,-1.5") == (12, -1.5)
    for bad in ("", "CH1", "CH,1.0", "CH1;2.0", "Modulo 0x48 trovato", "CH1=7.5", "CH1,abc", "CH1,nan"):
        assert link.parse_line(bad) is None


class _Quiet:
    def readline(self):
        time.sleep(0.05)
        return b""

    def close(self):
        pass


def _rd():
    return link.Reader("TEST", opener=lambda p, b: _Quiet())


def test_port_error_status():
    r = link.Reader("COM_NONE", opener=lambda p, b: (_ for _ in ()).throw(OSError("no port")))
    time.sleep(0.1)
    r.stop()
    assert r.status() == "ERRORE" and "no port" in r.error


def test_reader_latest_and_stale():
    r = _rd()
    r.stop()
    t = 1000.0
    assert r.feed("CH1,5.000", t)
    assert not r.feed("garbage", t)
    assert r.raw(1, t + 0.5) == 5.0
    assert r.raw(1, t + 1.5) is None                  # no data for > 1 s → NO DATA
    assert r.lines_ok == 1 and r.lines_bad == 1
    assert r.status(t + 0.5) == "LINK"


def test_scale_and_alarms():
    c = link.Channel(2, "V Master", "V", scale=10.0, offset=0.5, decimals=2, alarm_min=10, alarm_max=30)
    assert c.value(1.2) == 12.5
    assert link.alarm_of(c, 12.5) is None
    assert "> 30.00" in link.alarm_of(c, 31)
    assert "< 10.00" in link.alarm_of(c, 9)
    assert link.alarm_of(c, None) == "NO DATA"
    c.alarm_nodata = False
    assert link.alarm_of(c, None) is None


def test_logic_channel():
    c = link.Channel(7, "PTT", kind="logic", on_text="TX", off_text="RX", alarm_state="ON")
    assert c.value(0.9) == 1.0 and c.value(0.1) == 0.0
    assert c.fmt(1.0) == "TX" and c.fmt(0.0) == "RX"
    assert link.alarm_of(c, 1.0) == "TX"
    assert link.alarm_of(c, 0.0) is None
    c.alarm_state = ""
    assert link.alarm_of(c, 1.0) is None


def test_three_default_boards_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import ui_nanoham
    d = ui_nanoham.load_cfg()
    assert [b.name for b in d["boards"]] == ["10GHz", "24GHz", "47GHz"]
    assert all(b.enabled and not b.configured for b in d["boards"])          # nothing opened until a port is chosen
    assert [c.name for c in d["boards"][0].channels][:4] == ["V Helix", "V Master", "V Slave", "V Aux"]
    d["boards"][0].channels[1].alarm_max = 15.0
    d["boards"][1].port = "COM9"
    d["boards"][1].enabled = False                                           # no reader opened on a missing port
    ui_nanoham.save_cfg(d)
    e = ui_nanoham.load_cfg()
    assert e["boards"][0].channels[1].alarm_max == 15.0
    assert e["boards"][1].port == "COM9"


def test_link_state():
    b = link.Board(name="24GHz")
    assert link.link_state(b, None) == "NO PORTA"
    b.port = "COM5"
    r = _rd()
    r.stop()
    r.feed("CH1,5.0", 100.0)
    assert link.link_state(b, r, 100.5) == "LINK"
    assert link.link_state(b, r, 102.0) == "NO DATA"
    b.enabled = False
    assert link.link_state(b, r, 100.5) == "SPENTA"


def test_channels_from_rows():
    from emelab import ui_nanoham
    rows = [{"n": 2, "name": "V 48 TWT", "kind": "analog", "unit": "V", "scale": 10.0, "alarm_max": None,
             "alarm_min": float("nan"), "enabled": True},
            {"n": 2, "name": "dup"}, {"n": None, "name": "no CH"},
            {"n": 7, "name": "PTT", "kind": "logic", "on_text": "TX", "off_text": "RX", "alarm_state": "—", "enabled": True},
            {"n": 5, "name": "T box", "unit": "°C", "alarm_max": "60,5", "alarm_min": "", "enabled": True}]
    ch = ui_nanoham.channels_from_rows(rows)
    assert [c.n for c in ch] == [2, 5, 7]
    assert ch[1].alarm_max == 60.5 and ch[1].alarm_min is None and ch[2].alarm_state == ""
    assert ch[0].name == "V 48 TWT" and ch[0].scale == 10.0 and ch[0].alarm_min is None
    assert ch[2].logic and ch[2].fmt(1.0) == "TX"


def _tab_app():
    from emelab import ui_nanoham
    ui_nanoham.tab()


def test_tab_renders_with_demo_board(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    from emelab import settings
    settings.save_settings(nanoham={"boards": [{"name": "10GHz", "port": "DEMO"}, {"name": "24GHz"},
                                               {"name": "47GHz", "enabled": False}]})
    at = AppTest.from_function(_tab_app, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    md = " ".join(m.value for m in at.markdown)
    assert "10GHz" in md and "24GHz" in md and "47GHz" in md
    assert "NO PORTA" in md and "SPENTA" in md
    link.stop_reader("DEMO")


def test_tab_in_english(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    from emelab import i18n
    i18n.set_lang("en")
    try:
        at = AppTest.from_function(_tab_app, default_timeout=60)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        texts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [t.label for t in at.tabs] \
            + [i.value for i in at.info] + [e.label for e in at.expander] + [b.label for b in at.button]
        it = [t for t in texts for w in (" della ", " delle ", "Nessun", "scheda", "Misure", "porta", " è ", "Fibra",
                                          "Configurazione", "Stato", "Sola lettura") if w in t]
        assert not it, it
    finally:
        i18n.set_lang("it")


def test_csv_log(tmp_path):
    r = _rd()
    r.stop()
    now = time.time()
    r.feed("CH1,7.000", now)
    r.feed("CH2,25.000", now)
    b = link.Board(name="10GHz")
    b.channels[1].alarm_max = 24.0
    log = link.CsvLog(tmp_path)
    p = log.write(b, r, 1.0, now)
    assert log.write(b, r, 1.0, now + 0.2) is None          # too soon
    rows = list(csv.reader(open(p, encoding="utf-8"), delimiter=";"))
    assert rows[0][:3] == ["UTC", "V Helix (kV)", "V Master (V)"]
    assert rows[1][1:3] == ["7.000", "25.000"]
    assert "V Master" in rows[1][-1] and "V Slave: NO DATA" in rows[1][-1]


def test_demo_reader():
    r = link.Reader(link.DEMO_PORT)
    time.sleep(0.5)
    r.stop()
    assert r.status() == "LINK"
    assert 6.5 < r.raw(1) < 7.5
    assert r.raw(8) == 0.0
