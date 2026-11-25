"""Planner: the other station is chosen by callsign from the EME stations database (corrections by hand included)
and its locator comes from there; an unknown callsign takes a locator by hand, which can be added to the database."""
import os

import pytest

pytest.importorskip("erfa")


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    from emelab import astro, db as edb
    D = edb.DB()
    lat, lon = astro.locator_to_latlon("JN61PM")
    D.save_station(callsign="IZ0XXX", locator="JN61PM", lat=lat, lon=lon, height_m=100.0)
    D.save_setup("24 demo", 24.048, {"band_ghz": 24.048, "D_m": 1.2, "eta_ap": 0.6, "gain_dbi": 46, "tx_w": 20,
                                     "nf_db": 0.7, "line_loss_db": 0.2, "spill": 0.9, "edge_taper_db": 12})
    D.upsert_station("OK1KIR", locator="JO70EB", eme=1, data={"call3": True})
    D.upsert_station("DF3GJ", locator="JO31", eme=1, data={"call3": True})
    D.commit()
    D.set_station_manual("DF3GJ", {"locator": "JO31AB"})      # the correction by hand wins
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_partner_by_callsign(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    sb = at.selectbox(key="em_p_pcall")
    assert "OK1KIR · JO70EB" in sb.options and "DF3GJ · JO31AB" in sb.options
    sb.set_value("DF3GJ").run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("JO31AB" in c.value and "✏️" in c.value for c in at.caption)
    at.button(key="em_p_go").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["em_plan_dx"] == ("DF3GJ", "JO31AB")
    assert any("DF3GJ · JO31AB" in c.value for c in at.caption)


def test_unknown_callsign_locator_by_hand_and_added(tmp_path, monkeypatch):
    at = _app(tmp_path, monkeypatch)
    at.selectbox(key="em_p_pcall").set_value("➕").run()
    at.text_input(key="em_p_newcall").input("oh2dg").run()
    at.text_input(key="em_p_ploc_OH2DG").input("kp20lg").run()
    assert not at.exception, [e.value for e in at.exception]
    at.button(key="em_p_addst_OH2DG").click().run()
    assert not at.exception, [e.value for e in at.exception]
    from emelab import db as edb
    assert edb.DB().station_of("OH2DG")["locator"] == "KP20LG"
    assert at.selectbox(key="em_p_pcall").value == "OH2DG"
    assert any("KP20LG" in c.value for c in at.caption)
    from emelab import i18n
    i18n.set_lang("it")
