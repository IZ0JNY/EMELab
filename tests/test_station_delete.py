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
