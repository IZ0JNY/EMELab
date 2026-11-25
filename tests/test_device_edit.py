"""Devices corrected by hand or from a datasheet PDF: the user's values replace the catalogue ones, are marked as
verified, can be undone; own devices can be added and deleted; the datasheet reader takes the typical value."""
import os
import sqlite3

import pytest

from emelab import catalog, parts


class _D:                                    # the part of emelab.db.DB that parts.py uses
    def __init__(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row


def _row(rows, part):
    return next(r for r in rows if r["part"] == part)


def test_catalogue_device_corrected_and_reverted():
    D = _D()
    r = _row(parts.devices(D, 10.368, "LNA"), "XLNA-mk2 10 GHz")
    assert r["origin"] == "catalog" and r.get("gain_db") is None and not r["verified"]
    parts.save(D, part="XLNA-mk2 10 GHz", maker="DU3T", type="lna", f_lo_ghz=10.0, f_hi_ghz=10.5, gain_db=30.0,
               nf_db=0.45, notes="misurato", verified=1)
    r = _row(parts.devices(D, 10.368, "LNA"), "XLNA-mk2 10 GHz")
    assert r["origin"] == "edited" and r["verified"] and not r["check"]
    assert (r["gain_db"], r["nf_db"], r["notes"]) == (30.0, 0.45, "misurato")
    assert r["catalog"].get("gain_db") is None                   # the catalogue values stay available
    assert sum(x["part"] == "XLNA-mk2 10 GHz" for x in parts.devices(D, 10.368, "LNA")) == 1
    hmc = _row(parts.devices(D, 10.368, "LNA"), "HMC565")
    assert hmc["check"] and hmc["origin"] == "catalog"
    assert parts.revert(D, "xlna-MK2 10 ghz", " DU3T ")      # case and spaces do not matter
    r = _row(parts.devices(D, 10.368, "LNA"), "XLNA-mk2 10 GHz")
    assert r["origin"] == "catalog" and r.get("gain_db") is None


def test_power_presets_editable():
    D = _D()
    parts.save(D, part="QPA1010", maker="Qorvo", type="pa", f_lo_ghz=7.9, f_hi_ghz=11.0, psat_dbm=42.0, verified=1)
    parts.save(D, part="RW1136", maker="Siemens", type="twt", f_lo_ghz=24.0, f_hi_ghz=24.25, psat_dbm=43.0, verified=1)
    q = _row(parts.devices(D, 10.368, "PA"), "QPA1010")
    t = _row(parts.devices(D, 24.048, "TWT"), "RW1136")
    assert (q["psat_dbm"], q["origin"], q["check"]) == (42.0, "edited", False)
    assert (t["psat_dbm"], t["origin"], t["type"]) == (43.0, "edited", "TWT")
    assert not any(r["part"] == "RW1136" for r in parts.devices(D, 24.048, "PA"))


def test_own_device_and_old_database():
    D = _D()
    D.con.executescript("""CREATE TABLE parts (id INTEGER PRIMARY KEY AUTOINCREMENT, part TEXT, maker TEXT, type TEXT,
        f_lo_ghz REAL, f_hi_ghz REAL, gain_db REAL, nf_db REAL, p1db_dbm REAL, psat_dbm REAL, vdc REAL, idc_a REAL,
        datasheet TEXT, notes TEXT, UNIQUE(part, maker));
        INSERT INTO parts (part, maker, type, f_lo_ghz, f_hi_ghz, nf_db) VALUES ('MyLNA', 'me', 'lna', 10.3, 10.5, 0.6);""")
    rows = parts.devices(D, 10.368, "LNA")                   # columns added to an older library
    mine = _row(rows, "MyLNA")
    assert mine["origin"] == "mine" and mine["nf_db"] == 0.6
    assert not any(r["part"] == "MyLNA" for r in parts.devices(D, 24.048, "LNA"))
    parts.delete(D, mine["id"])
    assert not any(r["part"] == "MyLNA" for r in parts.devices(D, 10.368, "LNA"))


def test_datasheet_typical_values():
    f = catalog.read_datasheet("Frequency Range 6 - 20 GHz\nGain 18 21 dB\nNoise Figure 1.8 2.2 2.6 dB\n"
                               "Noise Figure 9 dB\nSaturated Output Power (Psat) 17 dBm\nSupply Current (Idd) 53 75 mA")
    assert (f["f_lo"], f["f_hi"], f["gain_db"], f["nf_db"], f["psat_dbm"]) == (6.0, 20.0, 21.0, 2.2, 17.0)
    assert abs(f["idc_a"] - 0.053) < 1e-12
    assert f["_lines"]["gain_db"] == "Gain 18 21 dB"
    assert catalog.read_datasheet("Gain 21 dB")["gain_db"] == 21.0


def _box_app():
    from emelab import db as edb, i18n, ui
    i18n.set_lang("it")
    ui._catalog_box(edb.DB(), ("LNA", "SW"), "ln")


def test_catalog_box_edit_and_revert(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_box_app, default_timeout=60)
    at.run()
    assert not at.exception
    cells = at.dataframe[0].value
    assert "None" not in cells.astype(str).values
    i = next(j for j, o in enumerate(at.selectbox(key="ln_cs").options) if o.startswith("XLNA-mk2"))
    at.selectbox(key="ln_cs").set_value(i).run()
    assert any(e.label.startswith("✏️") and "XLNA-mk2" in e.label for e in at.expander)
    gain = next(w for w in at.number_input if w.label == "Guadagno (dB)")
    gain.set_value(31.5).run()
    next(b for b in at.button if b.label.startswith("💾 Salva i valori")).click().run()
    assert not at.exception
    tab = at.dataframe[0].value
    row = tab[tab["Sigla"] == "XLNA-mk2 10 GHz"].iloc[0]
    assert row["Guadagno (dB)"] == "31.5" and row["Verificato"] == "✅"
    assert any("verificati da te" in s.value for s in at.success)
    next(b for b in at.button if b.label.startswith("↩️")).click().run()
    tab = at.dataframe[0].value
    row = tab[tab["Sigla"] == "XLNA-mk2 10 GHz"].iloc[0]
    assert row["Guadagno (dB)"] == "" and row["Verificato"] == ""
