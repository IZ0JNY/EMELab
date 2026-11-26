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
    dxs = at.session_state["em_plan_dx"]
    assert (dxs["call"], dxs["locator"]) == ("DF3GJ", "JO31AB")
    assert any("DF3GJ · JO31AB" in c.value for c in at.caption)
    labels = [m.label for m in at.metric]
    assert any("Ora locale da DF3GJ" in x for x in labels) and "Probabilità di QSO adesso" in labels
    tab = next(d.value for d in at.dataframe if "Migliore" in getattr(d.value, "columns", []))
    assert {"Ora locale DX", "Luna da te AZ/EL (°)", "Luna dal DX AZ/EL (°)", "Migliore"} <= set(tab.columns)
    assert (tab["Migliore"] == "✅").any()
    # the «Segnale» sub-tab: the day every 30 minutes with the Moon from both stations and the local times
    day = [d.value for d in at.dataframe if "UTC" in getattr(d.value, "columns", []) and "Ora locale DX" in d.value.columns]
    assert day and {"Luna da te AZ/EL (°)", "Luna dal DX AZ/EL (°)", "Probabilità QSO"} <= set(day[0].columns)


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


def test_qso_chances_and_horizon():
    from datetime import datetime, timezone
    from emelab import astro, dx, planner
    stn = {"lat": 41.6, "lon": 13.0, "height_m": 100.0}
    setup = {"band_ghz": 24.048, "D_m": 2.4, "eta_ap": 0.6, "gain_dbi": 52, "tx_w": 18, "nf_db": 0.7,
             "line_loss_db": 0.2, "spill": 0.9, "edge_taper_db": 12}
    t0 = datetime(2026, 11, 25, tzinfo=timezone.utc)
    dxl = astro.locator_to_latlon("JO70EB")
    smp = planner.windows(stn, setup, t0, 2, 15, 10.0, dxl)
    rows = planner.daily(smp)
    me = dx.station("24G", 2.4, 18, "offset")
    planner.qso_chances(rows, me, (stn["lat"], stn["lon"]), dx.station("24G", 4.5, 30), dxl, "24G", "60E")
    q = rows[0]["qso"]
    assert 0 <= q["probability"] <= 1 and rows[0]["start"] <= q["utc"] <= rows[0]["end"]
    assert q["el_me"] >= 10 and q["el_dx"] >= 10 and 0 <= q["az_me"] < 360
    # a wall towards the south-east hides part of every pass: no sample behind it
    wall = [{"az_da": 0, "az_a": 120, "el_min": 5}, {"az_da": 120, "az_a": 200, "el_min": 80},
            {"az_da": 200, "az_a": 360, "el_min": 5}]
    smp2 = planner.windows(stn, setup, t0, 2, 15, 10.0, horizon=wall)
    assert smp2 and all(not (120 <= s["az"] <= 200) or s["el"] >= 80 for s in smp2)
    assert len(smp2) < len(planner.windows(stn, setup, t0, 2, 15, 10.0))


def test_best_rows_and_local_time():
    from datetime import datetime, timezone
    from emelab import tz, ui
    rows = [{"sun_moon_deg": 90, "snr_spread": -1.0}, {"sun_moon_deg": 90, "snr_spread": -1.8},
            {"sun_moon_deg": 5, "snr_spread": 3.0}, {"sun_moon_deg": 90, "snr_spread": -4.0}]
    assert ui.planner_best_rows(rows, 10.0) == [True, True, False, False]
    lt, name, assumed = tz.local_time(50.0, 14.4, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
    if assumed:                     # without timezonefinder: solar time rounded to the hour, UTC+1 at 14.4° E
        assert (lt.hour, name) == (13, "UTC+1")
    else:                           # real zone: Prague is on summer time (CEST, UTC+2) in July
        assert (lt.hour, name) == (14, "Europe/Prague")


def test_local_time_without_timezonefinder(monkeypatch):
    from datetime import datetime, timezone
    from emelab import tz
    monkeypatch.setattr(tz, "zone_name", lambda lat, lon: None)
    lt, name, assumed = tz.local_time(41.6, -73.9, datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert assumed and name == "UTC-5" and lt.hour == 7


def test_click_in_who_can_i_work_opens_planner(monkeypatch):
    from emelab import ui
    rk = [{"call": "OK1KIR"}, {"call": "DF3GJ"}]
    # the callback works on streamlit's session state: call it with a plain dict standing in
    fake = {"sg_rank_sel_0": {"selection": {"rows": [], "cells": [[1, "Nominativo"]]}}, "tabs_on": ["signal"]}
    monkeypatch.setattr(ui, "_st", type("S", (), {"session_state": fake}))
    ui._open_in_planner_cb("sg_rank_sel_0", rk, {"id": 7}, 12.0)
    assert fake["em_p_pcall"] == "DF3GJ" and fake["em_p_setup"] == 7 and fake["em_p_minel"] == 12.0
    assert fake["em_p_auto"] and fake["main_tab"] == "🗓️ Pianificatore" and "planner" in fake["tabs_on"]
    assert fake["sg_rank_sel_n"] == 1 and fake["pl_sub"] == "🗓️ Finestre"
