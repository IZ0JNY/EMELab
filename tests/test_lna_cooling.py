"""❄️ Cooled LNA: the temperature model, the Peltier limit, the dew point and the 🔊 LNA tab in both languages."""
import os

import pytest

from emelab import analysis, cooling


def test_te_scales_with_physical_temperature():
    te0 = cooling.te_of_nf(0.9)                                    # ≈ 67 K at +25 °C
    assert cooling.cooled_stage(0.9, 25.0)["te_K"] == pytest.approx(te0)
    peltier = cooling.cooled_stage(0.9, -5.0)
    assert 0.80 < peltier["nf_db"] < 0.85                          # a Peltier cell: some hundredths of a dB
    ln2 = cooling.cooled_stage(0.9, 77 - cooling.ZERO_C)
    assert 0.28 < ln2["nf_db"] < 0.36                              # liquid nitrogen: about a third of Te
    floor = cooling.cooled_te(te0, 0.0)
    assert floor == pytest.approx(cooling.A_NONTHERMAL * te0)      # the part that does not scale stays


def test_cryogenic_lna_datasheet_ratio():
    """LNF cryogenic LNAs: ~4–8 K at 5 K from some tens of kelvin warm — the model with a = 7 % gives that order."""
    assert 3.0 < cooling.cooled_te(55.0, 5.0, 296.0, 0.07) < 6.0


def test_peltier_limit_and_methods():
    t, lim = cooling.physical_temp_c("peltier1", 20.0, -60.0)
    assert lim and t == pytest.approx(20.0 - cooling.PELTIER_MAX_DT["peltier1"])
    t, lim = cooling.physical_temp_c("peltier1", 20.0, -5.0)
    assert not lim and t == -5.0
    assert cooling.physical_temp_c("ln2", 20.0)[0] == pytest.approx(-196.15)
    assert cooling.physical_temp_c("ambient", 12.0)[0] == 12.0


def test_dew_point():
    assert cooling.dew_point_c(20.0, 100.0) == pytest.approx(20.0, abs=0.05)
    assert cooling.dew_point_c(20.0, 50.0) == pytest.approx(9.3, abs=0.2)


def test_cooled_setup_lowers_tsys_and_cold_line():
    s = {"band_ghz": 24.048, "D_m": 1.2, "nf_db": 1.0, "line_loss_db": 0.3, "spill": 0.9}
    warm = analysis.tsys_cold(s, 20.0)["sys"]
    te = cooling.cooled_stage(1.0, 77 - cooling.ZERO_C)["te_K"]
    cold = analysis.tsys_cold(cooling.setup_cooled(s, te), 20.0)["sys"]
    colder = analysis.tsys_cold(cooling.setup_cooled(s, te, True, 77 - cooling.ZERO_C), 20.0)["sys"]
    assert colder < cold < warm
    assert analysis.tsys_cold(dict(s), 20.0)["sys"] == pytest.approx(warm)      # setups without the key unchanged


def test_cryogenic_devices_in_catalogue():
    from emelab import catalog
    cryo = [d for d in catalog.DEVICES if d.get("cryo_k")]
    assert any(catalog.in_band(d, 10.368) for d in cryo) and any(catalog.in_band(d, 24.048) for d in cryo)


@pytest.mark.parametrize("lang", ["it", "en"])
def test_lna_tab_cooling_box(tmp_path, monkeypatch, lang):
    pytest.importorskip("erfa")
    from emelab import astro, db as edb, i18n
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", lang)
    monkeypatch.setenv("EMELAB_TABS", "all")
    D = edb.DB()
    lat, lon = astro.locator_to_latlon("JN45FA")
    D.save_station(callsign="IZ0XXX", locator="JN45FA", lat=lat, lon=lon, height_m=100.0)
    for band in (10.368, 24.048):
        D.save_setup(f"{band:g} GHz demo", band, {"band_ghz": band, "D_m": 1.2, "eta_ap": 0.6, "gain_dbi": 46, "tx_w": 20,
                                                 "nf_db": 0.9, "line_loss_db": 0.2, "spill": 0.9, "edge_taper_db": 12})
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    try:
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        head = "❄️ LNA raffreddato o criogenico" if lang == "it" else "❄️ Cooled or cryogenic LNA"
        assert head in [h.value for h in at.subheader]
        tables = [df.value for df in at.dataframe]
        band_col = "Banda" if lang == "it" else "Band"
        per_band = [t for t in tables if band_col in t.columns and ("Rumore solare (dB)" in t.columns or "Sun noise (dB)" in t.columns)]
        assert per_band and len(per_band[0]) == 2
        at.selectbox(key="lc_meth").set_value("ln2").run()
        assert not at.exception
        at.radio(key="lc_what").set_value(at.radio(key="lc_what").options[1]).run()
        assert not at.exception
    finally:
        i18n.set_lang("it")
