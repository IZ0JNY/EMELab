# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab — EME measurements and planning at 10, 24 and 47 GHz (separate program, companion of FeedLab).

Run with  streamlit run emelab_main.py.  Dish and feed come from a FeedLab project file (.feedlab.json); everything else
is EMELab's own."""
from __future__ import annotations

import streamlit as _st

import emelab
from emelab import i18n, ui
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = st.session_state
if "lang" not in S:
    S.lang = i18n.default_lang()
i18n.set_lang(S.lang)
st.set_page_config(page_title="EMELab — misure e pianificazione EME", page_icon="🌕", layout="wide")


def _set_lang():
    i18n.set_lang(S.lang)
    try:
        openems_local.save_settings(language=S.lang)
    except Exception:
        pass


D = ui._db()
with st.sidebar:
    st.title("🌕 EMELab")
    st.subheader("Misure e pianificazione EME a 10, 24 e 47 GHz")
    st.caption("Software progettato da Ivan IZ0JNY · parabola e feed dai progetti FeedLab")
    stn = D.station()
    if stn.get("callsign") or stn.get("locator"):
        st.markdown(f"**{stn.get('callsign') or ''}** {stn.get('locator') or ''}")
    st.metric("Misure registrate", len(D.measurements()))
    st.divider()
    st.caption(f"Versione {emelab.__version__} · © Ivan De Cesaris IZ0JNY")
    st.selectbox("Lingua / Language", list(i18n.LANGS), key="lang", format_func=lambda k: i18n.LANGS[k], on_change=_set_lang)
    st.caption("Tutti i dati restano su questo PC. Orari in UTC.")

st.header("🌕 EMELab — stazione EME, misure e pianificazione")
t = st.tabs(["🏠 Stazione", "🛰️ Configurazioni", "➕ Nuova misura", "📒 Diario", "📊 Analisi", "🗓️ Pianificatore",
             "📖 Guida alle misure"])
with t[0]:
    ui._station(D)
with t[1]:
    ui._setups(D)
with t[2]:
    ui._new(D)
with t[3]:
    ui._log(D)
with t[4]:
    ui._analysis(D)
with t[5]:
    ui._planner(D)
with t[6]:
    ui._guide()
