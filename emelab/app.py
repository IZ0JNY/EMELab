# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab — EME planning, measurements, analysis and log from 10 to 134 GHz (companion of FeedLab).
Run with  streamlit run emelab_main.py.  Same look as FeedLab: sidebar with title, author, language, Credits."""
from __future__ import annotations

import streamlit as _st

import emelab
from emelab import coach, i18n, ui
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = st.session_state
if "lang" not in S:
    S.lang = i18n.default_lang()
i18n.set_lang(S.lang)
st.set_page_config(page_title="EMELab — Laboratorio di misure e pianificazione EME", page_icon="🌕", layout="wide")


def _set_lang():
    i18n.set_lang(S.lang)
    try:
        openems_local.save_settings(language=S.lang)
    except Exception:
        pass


@_st.dialog("ℹ️ Credits", width="large")
def _credits_dialog():
    from emelab import credits
    credits.render(st)


D = ui._db()
if "coach_seen" not in S:                          # invitations to measure, once per launch
    S["coach_seen"] = True
    try:
        _sug = coach.suggestions(D)
        if _sug:
            _st.toast(i18n.tr(_sug[0]["text"]), icon="🧪", duration=12)
    except Exception:
        pass

with st.sidebar:
    st.title("🌕 EMELab")
    st.subheader("Laboratorio di misure e pianificazione EME")
    st.caption("10–134 GHz · Software progettato da Ivan IZ0JNY")
    stn = D.station()
    if stn.get("callsign") or stn.get("locator"):
        st.markdown(f"**{i18n.tr('Stazione')}:** {stn.get('callsign') or ''} · {stn.get('locator') or ''}")
    c = st.columns(2)
    c[0].metric("Misure", len(D.measurements()))
    c[1].metric("QSO", len(D.qsos()))
    st.divider()
    st.caption(f"Versione {emelab.__version__} · © Ivan De Cesaris IZ0JNY")
    st.selectbox("Lingua / Language", list(i18n.LANGS), key="lang", format_func=lambda k: i18n.LANGS[k], on_change=_set_lang)
    if st.button("ℹ️ Credits", key="credits_btn", help="Autore, versione e tutte le fonti"):
        _credits_dialog()
    st.link_button("🐞 Segnala un problema", "https://github.com/IZ0JNY/EMELab/issues")
    st.caption("Tutti i dati restano su questo PC. Orari in UTC.")

TABS = [  # key, label, function — "wizard" and "station" are always shown
    ("wizard", "🧭 Assistente", ui._wizard), ("station", "🏠 Stazione", None), ("setups", "🛰️ Configurazioni", ui._setups), ("signal", "📶 Segnale e stazioni", ui._signal_tab),
    ("planner", "🗓️ Pianificatore", ui._planner), ("log", "📡 Log QSO", ui._logbook_tab), ("stations", "👥 Stazioni EME", ui._stations_tab),
    ("new", "➕ Nuova misura", ui._new), ("diary", "📒 Diario misure", ui._log), ("analysis", "📊 Analisi", ui._analysis),
    ("charts", "📈 Grafici", ui._charts_tab), ("stats", "📉 Statistiche QSO", ui._qso_stats_tab),
    ("pointing", "🎯 Puntamento", ui._pointing_tab), ("lna", "🔊 LNA", ui._lna_tab), ("sspa", "🔥 SSPA", ui._sspa_tab),
    ("twt", "💡 TWT", ui._twt_tab), ("design", "🔧 Progettazione", ui._design_tab), ("prints", "🖨️ Stampa PDF", ui._prints_tab),
    ("database", "🗄️ Database", ui._database_tab), ("guide", "📖 Guida alle misure", None)]
_saved = openems_local.load_settings().get("tabs")
if "tabs_on" not in S:
    S["tabs_on"] = [k for k, _, _ in TABS[2:] if _saved is None or k in _saved]


def _save_tabs():
    try:
        openems_local.save_settings(tabs=S["tabs_on"])
    except Exception:
        pass


with st.sidebar:
    with st.expander("⚙️ Schede da mostrare"):
        st.multiselect("Schede", [k for k, _, _ in TABS[2:]], key="tabs_on", on_change=_save_tabs,
                       format_func=lambda k: next(l for kk, l, _ in TABS if kk == k),
                       help="scegli le parti di EMELab che usi: la scelta resta salvata su questo PC")
shown = [t for t in TABS if t[0] in ("wizard", "station") or t[0] in S["tabs_on"]]
tabs = st.tabs([l for _, l, _ in shown])
for tab, (k, _, fn) in zip(tabs, shown):
    with tab:
        if k == "station":
            ui._station(D)
            st.divider()
            st.subheader("🧪 Cosa misurare o provare adesso")
            for sgg in coach.suggestions(D)[:8]:
                st.markdown("- " + i18n.tr(sgg["text"]))
        elif k == "guide":
            ui._guide()
        else:
            fn(D)
