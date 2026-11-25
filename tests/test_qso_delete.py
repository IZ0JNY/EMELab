"""QSO log: an ADIF import can be taken back, the whole log can be emptied, missing locators are taken from the
EME stations database, and the table shows no "None" cells."""
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("erfa")


def _q(call, h, loc=None):
    return {"utc": datetime(2026, 1, 23, h, 0, tzinfo=timezone.utc), "call": call, "band": "10G", "freq_mhz": 10368.1,
            "mode": "MFSK", "submode": "Q65", "locator": loc, "my_locator": "JN61PM"}


def test_import_delete_and_clear(tmp_path):
    from emelab import db as edb
    D = edb.DB(tmp_path / "t.sqlite")
    D.add_qso(**_q("OK1KIR", 1, "JO70EB"))                 # typed by hand: not part of any import
    id0 = D.max_qso_id()
    D.add_qso(**_q("IK3GHY", 2))
    D.add_qso(**_q("LZ4OC", 3))
    assert D.log_qso_import("EME.adi", id0) == 2
    assert D.log_qso_import("empty.adi", D.max_qso_id()) == 0
    imp = D.qso_imports()
    assert [(r["label"], r["n"]) for r in imp] == [("EME.adi", 2)]
    assert D.delete_qso_import(imp[0]["id"]) == 2
    assert [q["call"] for q in D.qsos()] == ["OK1KIR"] and D.qso_imports() == []
    assert D.clear_qsos() == 1 and D.qsos() == []


def test_fill_locators_from_stations(tmp_path):
    from emelab import db as edb, logbook as lb
    D = edb.DB(tmp_path / "t.sqlite")
    D.add_qso(**_q("IK3GHY", 2))
    D.add_qso(**_q("NOBODY1", 3))
    D.upsert_station("IK3GHY", locator="JN55VF", data={"call3": True})
    D.commit()
    assert lb.fill_locators(D, "JN61PM") == 1
    q = {x["call"]: x for x in D.qsos()}
    assert q["IK3GHY"]["locator"] == "JN55VF" and q["IK3GHY"]["calc"]["ground_km"] > 100
    assert q["NOBODY1"]["locator"] is None


def test_logbook_tab_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    from emelab import astro, db as edb
    D = edb.DB()
    lat, lon = astro.locator_to_latlon("JN61PM")
    D.save_station(callsign="IZ0XXX", locator="JN61PM", lat=lat, lon=lon, height_m=100.0)
    id0 = D.max_qso_id()
    D.add_qso(**_q("IK3GHY", 2))
    D.log_qso_import("EME.adi", id0)
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    log = next(df.value for df in at.dataframe if "Percorso EME (km)" in df.value.columns)
    assert "None" not in log.astype(str).values
    assert at.button(key="q_clear_go").disabled
    at.checkbox(key="q_clear_ok").check().run()
    at.button(key="q_clear_go").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert edb.DB().qsos() == []
    from emelab import i18n
    i18n.set_lang("it")
