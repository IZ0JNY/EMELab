"""Language consistency: in Italian only Italian, in English only English.

The catalogue has unique, non-empty keys; the app rendered in English (fresh settings folder with a small
invented station: locator, one setup per band, two QSOs) shows no Italian words, and the same app still works in Italian."""
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("erfa")

MY_LOC = "JN45FA"                         # invented example station
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITALIAN_MARKERS = [" della ", " delle ", " degli ", " con il ", " per il ", "Nessun", "misura", "Stazione ", "parabola",
                   "configurazione", "Salva", "Carica", "Calcola", " è ", "più", " sono ", " questo ", " nella ",
                   "Inserisci", "Importa", "Registra", "Potenza", "Guadagno", "Perdit", "Elevazione", "Banda",
                   "Nominativo", "Frequenza", "Pioggia", "Vento", "Luna ", "Sole "]


def test_catalogue_keys_unique_and_not_empty():
    from emelab.i18n_catalog import ENTRIES
    keys = [e[0] for e in ENTRIES]
    assert all(isinstance(k, str) and k.strip() for k in keys)
    assert all(isinstance(e[1], str) and e[1].strip() for e in ENTRIES)
    dup = sorted({k for k in keys if keys.count(k) > 1})
    assert not dup, dup


def _demo_station(cfg):
    from emelab import astro, db as edb, logbook as lb
    D = edb.DB()
    lat, lon = astro.locator_to_latlon(MY_LOC)
    D.save_station(callsign="IZ0XXX", locator=MY_LOC, lat=lat, lon=lon, height_m=100.0)
    for band in (10.368, 24.048):
        D.save_setup(f"{band:g} GHz demo", band, {"band_ghz": band, "D_m": 1.2, "eta_ap": 0.6, "gain_dbi": 40, "tx_w": 20,
                                                 "nf_db": 0.7, "line_loss_db": 0.2, "spill": 0.9, "edge_taper_db": 12})
    for call, loc, t in (("OK1KIR", "JO70EB", datetime(2026, 2, 25, 20, 0, tzinfo=timezone.utc)),
                         ("PA0PLY", "JO32LR", datetime(2026, 6, 16, 3, 0, tzinfo=timezone.utc))):
        q = {"utc": t, "call": call, "band": "24G", "freq_mhz": 24048.2, "mode": "Q65", "submode": "60D",
             "rst_sent": "-18", "rst_rcvd": "-20", "locator": loc, "my_locator": MY_LOC}
        q["calc"] = lb.enrich(q, MY_LOC, 100.0)
        D.add_qso(**q)


def _visible_texts(at):
    out = []
    for kind in ("title", "header", "subheader", "caption", "markdown", "info", "warning", "success", "error"):
        out += [(kind, str(e.value)) for e in getattr(at, kind)]
    out += [("button", b.label) for b in at.button]
    out += [("tab", t.label) for t in at.tabs]
    out += [("metric", m.label) for m in at.metric]
    out += [("expander", e.label) for e in at.expander]
    for kind in ("selectbox", "radio", "number_input", "text_input", "checkbox", "multiselect"):
        out += [(kind, w.label) for w in getattr(at, kind)]
    return out


def _run(tmp_path, monkeypatch, lang):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", lang)
    _demo_station(tmp_path)
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


@pytest.fixture
def restore_lang():
    from emelab import i18n
    yield
    i18n.set_lang("it")


def test_english_shows_only_english(tmp_path, monkeypatch, restore_lang):
    at = _run(tmp_path, monkeypatch, "en")
    from emelab import i18n
    assert i18n.get_lang() == "en"
    texts = _visible_texts(at)
    assert any("Station" in t for _, t in texts)
    bad = [(k, t[:120], m) for k, t in texts for m in ITALIAN_MARKERS if m in t]
    assert not bad, bad


def test_italian_still_works(tmp_path, monkeypatch, restore_lang):
    at = _run(tmp_path, monkeypatch, "it")
    texts = [t for _, t in _visible_texts(at)]
    assert any("Stazione" in t for t in texts)
    assert any("Laboratorio di misure e pianificazione EME" in t for t in texts)
