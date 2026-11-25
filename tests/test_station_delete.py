"""Imported station data can be taken away again: per source (CALL3, ALL.TXT, EME Directory per band, QRZ.com),
single stations or the whole database; the app tab renders the delete box and the table has no "None" cells."""
import os


def _db(tmp_path):
    from emelab import db as edb
    D = edb.DB(tmp_path / "t.sqlite")
    D.upsert_station("OK1KIR", locator="JO70EB", eme=1, data={"call3": True})
    D.upsert_station("PA0PLY", locator="JO32LR", name="Henk", eme=1,
                     data={"directory": {"10G": {"antenna": "3m dish", "power_w": 50, "name": "Henk"},
                                         "24G": {"antenna": "1.8m dish", "power_w": 20, "name": "Henk"}}})
    D.upsert_station("DF3GJ", locator="JO31", name="Jan", eme=1,
                     data={"directory": {"24G": {"antenna": "2m dish", "power_w": 10, "name": "Jan"}}, "heard": {"n": 3}})
    D.upsert_station("IZ0AAA", name="Mario Rossi", qth="Roma", address="Via X", data={"qrz": {"lotw": "Y"}, "call3": True})
    D.commit()
    D.log_station_import("directory:24G", "24048.pdf", 2)
    D.log_station_import("call3", "CALL3.TXT", 2)
    return D


def test_source_counts(tmp_path):
    D = _db(tmp_path)
    assert D.station_source_counts() == {"call3": 2, "directory:10G": 1, "directory:24G": 2, "heard": 1, "qrz": 1}


def test_remove_directory_band(tmp_path):
    D = _db(tmp_path)
    ch, de = D.remove_station_source("directory:24G")
    assert (ch, de) == (2, 0)
    assert list(D.station_of("PA0PLY")["data"]["directory"]) == ["10G"]
    jan = D.station_of("DF3GJ")
    assert "directory" not in jan["data"] and jan["name"] is None and jan["data"]["heard"]
    assert [r["source"] for r in D.station_imports()] == ["call3"]
    ch, de = D.remove_station_source("directory:10G")
    assert de == 1 and D.station_of("PA0PLY") is None


def test_remove_qrz_and_call3(tmp_path):
    D = _db(tmp_path)
    D.remove_station_source("qrz")
    s = D.station_of("IZ0AAA")
    assert s["name"] is None and s["qth"] is None and s["address"] is None and "qrz" not in s["data"]
    D.remove_station_source("call3")
    assert D.station_of("IZ0AAA") is None and D.station_of("OK1KIR") is None
    assert D.station_of("DF3GJ")


def test_delete_single_and_clear(tmp_path):
    D = _db(tmp_path)
    assert D.delete_stations(["ok1kir"]) == 1 and D.station_of("OK1KIR") is None
    assert D.clear_stations() == 3
    assert D.stations() == [] and D.station_imports() == []


def test_stations_tab_delete_box(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    from emelab import db as edb
    D = _db(tmp_path)
    D.con.close()
    D = edb.DB()                                   # the app's own database in the fresh settings folder
    D.upsert_station("DF3GJ", locator="JO31", name="Jan", eme=1, data={"directory": {"24G": {"antenna": "2m dish"}}})
    D.commit()
    D.log_station_import("directory:24G", "24048.pdf", 1)
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Cancella i dati importati" in e.label for e in at.expander)
    tables = [df.value for df in at.dataframe]
    st_tab = next(t for t in tables if "Nominativo" in t.columns)
    assert "None" not in st_tab.astype(str).values
    at.button(key="st_del_src_directory:24G").click().run()
    at.button(key="st_del_src_yes").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert edb.DB().stations() == []
    from emelab import i18n
    i18n.set_lang("it")


def test_manual_corrections_survive_imports_and_can_be_removed(tmp_path):
    D = _db(tmp_path)
    D.set_station_manual("DF3GJ", {"locator": "JO31AB", "name": "Jan B.", "qth": "Bonn"},
                         {"24G": {"antenna": "3m dish", "power_w": 40}, "47G": {"antenna": "1.2m dish", "power_w": 5}})
    s = D.station_of("DF3GJ")
    assert (s["locator"], s["name"], s["qth"]) == ("JO31AB", "Jan B.", "Bonn")
    dirb = D.directory_of(s["data"])
    assert dirb["24G"]["power_w"] == 40 and dirb["47G"]["antenna"] == "1.2m dish"
    # a new import of the directory does not overwrite the correction, but is kept underneath
    D.upsert_station("DF3GJ", locator="JO31CD", name="Jan", data={"directory": {"24G": {"antenna": "2m dish", "power_w": 12}}})
    D.commit()
    s = D.station_of("DF3GJ")
    assert (s["locator"], s["name"]) == ("JO31AB", "Jan B.") and D.directory_of(s["data"])["24G"]["power_w"] == 40
    assert "manual" in D.station_source_counts()
    # one field back to the import, then everything
    D.set_station_manual("DF3GJ", {"name": ""})
    assert D.station_of("DF3GJ")["name"] == "Jan"
    D.remove_station_source("manual")
    s = D.station_of("DF3GJ")
    assert (s["locator"], s["qth"]) == ("JO31CD", None) and D.directory_of(s["data"])["24G"]["power_w"] == 12
    assert "47G" not in D.directory_of(s["data"])


def test_manual_only_station_and_other_source_removed(tmp_path):
    D = _db(tmp_path)
    D.set_station_manual("OH2DG", {"locator": "KP20LG"})
    assert D.station_of("OH2DG")["locator"] == "KP20LG"
    D.set_station_manual("PA0PLY", {"name": "Henk P."})
    D.remove_station_source("directory:10G")
    assert D.station_of("PA0PLY")["name"] == "Henk P."
    D.set_station_manual("OH2DG", {"locator": ""})
    assert D.station_of("OH2DG") is None


def test_table_edit_saves_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    from emelab import db as edb
    D = edb.DB()
    D.upsert_station("DF3GJ", locator="JO31", name="Jan", eme=1, data={"directory": {"24G": {"antenna": "2m dish"}}})
    D.commit()
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    at.selectbox(key="st_ed_call").select("DF3GJ").run()
    at.text_input(key="st_ed_qth_DF3GJ").input("Bonn").run()
    at.number_input(key="st_ed_pw_DF3GJ_24G").set_value(30.0).run()
    at.button(key="st_ed_save_DF3GJ").click().run()
    assert not at.exception, [e.value for e in at.exception]
    s = edb.DB().station_of("DF3GJ")
    assert s["qth"] == "Bonn" and s["name"] == "Jan" and s["data"]["manual"]["bands"]["24G"]["power_w"] == 30
    from emelab import i18n
    i18n.set_lang("it")


def test_save_station_edits_from_table(tmp_path):
    import pandas as pd
    from emelab import ui
    D = _db(tmp_path)
    cols = ["Nominativo", "Locator", "Nome", "QTH"]
    df = pd.DataFrame([{"Nominativo": "DF3GJ", "Locator": "JO31", "Nome": "Jan", "QTH": ""},
                       {"Nominativo": "OK1KIR", "Locator": "JO70EB", "Nome": "", "QTH": ""}])
    ed = df.copy()
    ed.loc[0, "QTH"] = "Bonn"
    ed.loc[1, "Locator"] = "XX"
    msgs = ui._save_station_edits(D, df, ed, cols)
    assert D.station_of("DF3GJ")["qth"] == "Bonn" and D.station_of("OK1KIR")["locator"] == "JO70EB"
    assert [k for k, _ in msgs] == ["success", "error"]


def _app(tmp_path, monkeypatch, n_stations=2):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    from emelab import db as edb
    D = edb.DB()
    for i in range(n_stations):
        D.upsert_station(f"K{i}AA", locator="FN20", data={"call3": True})
    D.commit()
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at, edb


def test_quick_clear_button_asks_then_empties(tmp_path, monkeypatch):
    at, edb = _app(tmp_path, monkeypatch)
    at.button(key="st_quick_clear").click().run()
    assert edb.DB().stations()                       # nothing deleted before the OK
    at.button(key="st_quick_clear_no").click().run()
    assert len(edb.DB().stations()) == 2
    at.button(key="st_quick_clear").click().run()
    at.button(key="st_quick_clear_yes").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert edb.DB().stations() == []
    assert any("svuotato" in s.value for s in at.success)
    from emelab import i18n
    i18n.set_lang("it")


def test_big_import_asks_for_ok(tmp_path):
    import streamlit as st
    from emelab import db as edb, ui
    D = edb.DB(tmp_path / "t.sqlite")
    rows = [{"call": f"K{i}AB", "locator": "FN20", "eme": False} for i in range(301)]
    st.session_state.clear()
    ui._import_or_ask(D, "call3", (rows, "CALL3.TXT"), {r["call"] for r in rows})
    assert D.stations() == [] and st.session_state["st_import_pending"]["n"] == 301
    ui._import_apply(D, "call3", st.session_state.pop("st_import_pending")["payload"])
    assert len(D.stations()) == 301
    few = rows[:300]
    D.clear_stations()
    ui._import_or_ask(D, "call3", (few, "CALL3.TXT"), {r["call"] for r in few})
    assert len(D.stations()) == 300 and "st_import_pending" not in st.session_state


def test_call3_and_all_keep_only_eme():
    from emelab import stations as stn
    rows = stn.parse_call3("1A0C,JN61FV\n2E0AAG,IO82VE\nOK1KIR,JO70EB,EME\nDF3GJ,JO31\n")
    assert [r["call"] for r in stn.eme_only(rows, {"DF3GJ"})] == ["DF3GJ"]      # the EME mark alone is not enough
    dec = [{"call": "K1JT", "band": "10G"}, {"call": "EA1XX", "band": None}, {"call": "PA0PLY", "band": None}]
    assert [d["call"] for d in stn.eme_decodes(dec, {"PA0PLY"})] == ["K1JT", "PA0PLY"]


def test_big_table_is_limited_and_searchable(tmp_path, monkeypatch):
    at, edb = _app(tmp_path, monkeypatch, n_stations=520)
    assert any("Mostro le prime" in c.value for c in at.caption)
    at.text_input(key="st_find").input("K51").run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any("Mostro le prime" in c.value for c in at.caption)
    from emelab import i18n
    i18n.set_lang("it")


def test_eme_10g_calls(tmp_path):
    from datetime import datetime, timezone
    from emelab import db as edb
    D = edb.DB(tmp_path / "t.sqlite")
    D.upsert_station("PA0PLY", data={"directory": {"10G": {"antenna": "3m dish"}}})
    D.upsert_station("K1JT", data={"heard": {"n": 2, "bands": ["10G"]}})
    D.upsert_station("EA1XX", data={"heard": {"n": 2, "bands": []}})       # heard live, band unknown
    D.upsert_station("2E0AAG", data={"call3": True})
    D.commit()
    D.add_qso(utc=datetime(2026, 1, 1, tzinfo=timezone.utc), call="OK1KIR", band="24G")
    D.add_qso(utc=datetime(2026, 1, 1, tzinfo=timezone.utc), call="G4ABC", band="2m")
    assert D.eme_10g_calls() == {"PA0PLY", "K1JT", "OK1KIR"}


def test_real_call3_keeps_only_known_eme_10g():
    """Head of a real WSJT-X CALL3.TXT (133 087 lines, none marked EME, no band information)."""
    from emelab import stations as stn
    text = ("// Version: 2024-08-14_14:10Z\n1A0C,JN61FV,,,\n2E0AAG,IO82VE,,,\n3B8DU,LG89,,,\n3B8EME,LG89QT,,,\n"
            "9A5AA,JN75XT,,,\nDF3GJ,JO31,,,\n")
    rows = stn.parse_call3(text)
    assert len(rows) == 6
    assert [r["call"] for r in stn.eme_only(rows, {"3B8DU", "9A5AA", "OH2DG"})] == ["3B8DU", "9A5AA"]


def test_call3_does_not_spoil_a_precise_locator(tmp_path):
    from emelab import db as edb, ui
    D = edb.DB(tmp_path / "t.sqlite")
    D.upsert_station("3B8DU", locator="LG89SQ", data={"directory": {"10G": {"antenna": "3m dish"}}})
    D.upsert_station("9A5AA", locator="JN75", data={"directory": {"10G": {"antenna": "2.4m dish"}}})
    D.commit()
    ui._import_apply(D, "call3", ([{"call": "3B8DU", "locator": "LG89", "eme": False},
                                   {"call": "9A5AA", "locator": "JN75XT", "eme": False}], "CALL3.TXT"))
    assert D.station_of("3B8DU")["locator"] == "LG89SQ" and D.station_of("9A5AA")["locator"] == "JN75XT"
