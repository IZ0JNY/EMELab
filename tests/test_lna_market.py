"""💡 LNA suggestions: the market survey file, the comparison with the user's LNA, and the tabs in both languages."""
import os
from datetime import date

import pytest

from emelab import lna_market


def test_survey_file_is_complete_and_sourced():
    sv = lna_market.load()
    assert sv["date"] and sv["parts"] and sv["pa_parts"] and sv["makers"]
    for p in sv["parts"] + sv["pa_parts"]:
        assert p["part"] and p["maker"]
        assert p.get("source", "").startswith("http"), p["part"]          # every part has its page
    makers = {m["maker"] for m in sv["makers"]}
    assert {"Qorvo", "MACOM"} <= makers and any("YiFeng" in m for m in makers)
    for band in (10.368, 24.048, 47.088, 76.032):
        assert len([p for p in sv["parts"] if lna_market.in_band(p, band)]) >= 3, band
    assert any(p["part"] == "YPA47-4653C1" and lna_market.in_band(p, 47.088) for p in sv["pa_parts"])


def test_compare_with_my_lna():
    sv = {"parts": [{"part": "A", "maker": "x", "f_lo_ghz": 8, "f_hi_ghz": 12, "nf_db": 0.5},
                    {"part": "B", "maker": "x", "f_lo_ghz": 8, "f_hi_ghz": 12, "nf_db": 1.5},
                    {"part": "C", "maker": "x", "f_lo_ghz": 8, "f_hi_ghz": 12, "nf_db": None},
                    {"part": "D", "maker": "x", "f_lo_ghz": 20, "f_hi_ghz": 30, "nf_db": 0.5}]}
    setup = {"band_ghz": 10.368, "nf_db": 0.9, "line_loss_db": 0.2, "spill": 0.9}
    rows = lna_market.compare(sv, 10.368, setup)
    assert [r["part"] for r in rows] == ["A", "B", "C"]                 # best NF first, unknown last, other band out
    assert rows[0]["d_gt_db"] > 0 > rows[1]["d_gt_db"] and rows[2]["d_gt_db"] is None
    assert lna_market.compare(sv, 10.368, None)[0]["d_gt_db"] is None


def test_age_and_ideas():
    assert lna_market.age_days({"date": "2026-11-01"}, date(2026, 11, 26)) == 25
    assert lna_market.age_days({"date": None}) is None
    for band in (10.368, 24.048, 47.088, 76.032, 122.25, 134.928):
        assert lna_market.ideas(band)


@pytest.mark.parametrize("lang", ["it", "en"])
def test_tabs_show_suggestions(tmp_path, monkeypatch, lang):
    pytest.importorskip("erfa")
    from emelab import astro, db as edb, i18n, parts
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", lang)
    monkeypatch.setenv("EMELAB_TABS", "all")
    D = edb.DB()
    lat, lon = astro.locator_to_latlon("JN45FA")
    D.save_station(callsign="IZ0XXX", locator="JN45FA", lat=lat, lon=lon, height_m=100.0)
    D.save_setup("10 GHz demo", 10.368, {"band_ghz": 10.368, "D_m": 1.2, "eta_ap": 0.6, "gain_dbi": 40, "tx_w": 20,
                                         "nf_db": 0.9, "line_loss_db": 0.2, "spill": 0.9, "edge_taper_db": 12})
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    try:
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        head = "💡 Suggerimenti: nuovi chip e nuovi design" if lang == "it" else "💡 Suggestions: new chips and new designs"
        assert head in [h.value for h in at.subheader]
        col = "ΔG/T se sostituisce il tuo (dB)" if lang == "it" else "ΔG/T if it replaces yours (dB)"
        assert any(col in df.value.columns for df in at.dataframe)
        at.button(key="lm_add").click().run()
        assert not at.exception
        assert any(r["origin"] in ("mine", "edited") for r in parts.devices(edb.DB(), 10.368, "LNA"))
        at.selectbox(key="lm_band").set_value(76.032).run()
        assert not at.exception
    finally:
        i18n.set_lang("it")
