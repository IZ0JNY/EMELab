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

tabs = st.tabs(["🏠 Stazione", "🛰️ Configurazioni", "🔧 Progettazione", "➕ Nuova misura", "📒 Diario misure",
                "📡 Log QSO", "👥 Stazioni EME", "📊 Analisi", "📈 Statistiche QSO", "🗓️ Pianificatore",
                "🖨️ Stampa PDF", "🗄️ Database", "📖 Guida alle misure"])
with tabs[0]:
    ui._station(D)
    st.divider()
    st.subheader("🧪 Cosa misurare o provare adesso")
    for sgg in coach.suggestions(D)[:8]:
        st.markdown("- " + i18n.tr(sgg["text"]))
with tabs[1]:
    ui._setups(D)
with tabs[2]:
    ui._design_tab(D)
with tabs[3]:
    ui._new(D)
with tabs[4]:
    ui._log(D)
with tabs[5]:
    ui._logbook_tab(D)
with tabs[6]:
    ui._stations_tab(D)
with tabs[7]:
    ui._analysis(D)
with tabs[8]:
    ui._qso_stats_tab(D)
with tabs[9]:
    ui._planner(D)
with tabs[10]:
    ui._prints_tab(D)
with tabs[11]:
    ui._database_tab(D)
with tabs[12]:
    ui._guide()
