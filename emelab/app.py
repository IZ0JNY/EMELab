# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab — EME planning, measurements, analysis and log from 10 to 134 GHz (companion of FeedLab).
Run with  streamlit run emelab_main.py.  Same look as FeedLab: sidebar with title, author, language, Credits."""
from __future__ import annotations

import os

import streamlit as _st

import emelab
from emelab import coach, i18n, nav, tab_order, ui, ui_camera, ui_gpsdo, ui_live, ui_horizon, ui_moon, ui_nanoham, ui_q65lab, ui_radio, ui_skydome, ui_wsjtx_panel
from emelab import settings as openems_local
from emelab import charts, stallwatch, wsqueue

charts.install()                             # wheel zoom on every Plotly chart, kept across refreshes
wsqueue.lift()                               # Streamlit drops sessions whose send queue passes 500 messages

stallwatch.run_started()                     # writes the thread stacks to server.log if this run gets stuck

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


@_st.dialog("📚 Bibliografia", width="large")
def _biblio_dialog():
    from emelab import credits
    credits.render_bibliography(st)


D = ui._db()
ui._wsjtx_autostart()                # keeps listening to WSJT-X in the background if it was switched on
if "update_info" not in S:                         # new version on GitHub: checked once per launch (as in FeedLab)
    from emelab import updates as _updates
    S["update_info"] = _updates.check(emelab.__version__, i18n.get_lang())
    if S["update_info"]:
        _upd = S["update_info"]

        @_st.dialog(i18n.tr("🆕 Nuova versione disponibile"), width="large")
        def _update_popup():
            st.markdown(i18n.tr("**EMELab {new}** è disponibile (stai usando la {cur}).").format(
                new=_upd["version"], cur=emelab.__version__))
            st.markdown(f"**{i18n.tr('Cosa c’è di nuovo')}**")
            _st.markdown(_upd["notes"] or i18n.tr("Vedi le note di rilascio su GitHub."))   # already in the right language
            st.link_button("⬇️ Scarica la nuova versione", _upd["url"])

        _update_popup()
        S["_update_dialog"] = True                 # one dialog per run: the alarm pop-ups wait for the next run
elif "coach_seen" not in S:                        # invitations to measure, once per launch
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
    _counters = (c[0].empty(), c[1].empty())      # filled again after the tabs: an import must show at once


def _show_counters():
    _counters[0].metric("Misure", len(D.measurements()))
    _counters[1].metric("QSO", len(D.qsos()))


_show_counters()
with st.sidebar:
    st.divider()
    st.caption(f"Versione {emelab.__version__} · © Ivan De Cesaris IZ0JNY")
    st.selectbox("Lingua / Language", list(i18n.LANGS), key="lang", format_func=lambda k: i18n.LANGS[k],
                 on_change=_set_lang)       # chosen in the installer; here for the portable version
    if os.environ.get("EMELAB_DESKTOP") == "browser":
        if st.button("⏻ Chiudi EMELab", help="ferma il programma"):
            st.write("EMELab chiuso: puoi chiudere questa scheda del browser.")
            os._exit(0)
    if st.button("ℹ️ Credits", key="credits_btn", help="Autore, versione e tutte le fonti"):
        _credits_dialog()
    if st.button("📚 Bibliografia", key="biblio_btn", help="i libri su cui si basano i calcoli"):
        _biblio_dialog()
    if st.button("🔄 Controlla aggiornamenti", key="upd_btn", help="chiede a GitHub se c'è una versione più nuova"):
        from emelab import updates as _updates
        _u = _updates.check(emelab.__version__, i18n.get_lang())
        if _u:
            st.markdown(i18n.tr("**EMELab {new}** è disponibile (stai usando la {cur}).").format(
                new=_u["version"], cur=emelab.__version__))
            st.link_button("⬇️ Scarica la nuova versione", _u["url"])
        elif _updates.LAST_ERROR:
            st.warning(i18n.tr("Impossibile contattare GitHub ({e}). Controlla la connessione o scarica da {url}").format(
                e=_updates.LAST_ERROR, url=_updates.RELEASES_URL))
        else:
            st.success("Hai già l'ultima versione.")
    st.link_button("🐞 Segnala un problema", "https://github.com/IZ0JNY/EMELab/issues")
    st.caption("Tutti i dati restano su questo PC. Orari in UTC.")

TABS = [  # key, label, function — "wizard" and "station" are always shown
    ("wizard", "🧭 Assistente", ui._wizard), ("station", "🏠 Stazione", None), ("live", "🔴 Live", ui_live.tab), ("moon", "🌙 Luna", ui_moon.tab), ("horizon", "🏔️ Orizzonte", ui_horizon.tab), ("skydome", "🌌 Volta celeste", ui_skydome.tab), ("setups", "🛰️ Configurazioni", ui._setups),
    ("planner", "🗓️ Pianificatore", ui._planner_tab), ("log", "📡 Log QSO", ui._logbook_tab), ("wsjtx", "📻 WSJT-X", ui._wsjtx_tab), ("radio", "📟 Radio", ui_radio.tab), ("q65lab", "🧪 Q65 Lab", ui_q65lab.tab), ("gpsdo", "🛰️ GPSDO", ui_gpsdo.tab), ("nanoham", ":material/developer_board: nanoHam", ui_nanoham.tab), ("stations", "👥 Stazioni EME", ui._stations_tab),
    ("new", "➕ Nuova misura", ui._new), ("diary", "📒 Diario misure", ui._log), ("analysis", "📊 Analisi", ui._analysis),
    ("charts", "📈 Grafici", ui._charts_tab), ("stats", "📉 Statistiche QSO", ui._qso_stats_tab),
    ("pointing", "🎯 Tracking", ui._pointing_tab), ("camera", "📷 Telecamera Astronomica", ui_camera.tab), ("lna", "▷ LNA", ui._lna_tab), ("power", "⚡ RF Power", ui._power_tab),
     ("design", "🔧 Laboratorio", ui._design_tab), ("prints", "🖨️ Stampa PDF", ui._prints_tab),
    ("database", "🗄️ Database", ui._database_tab), ("guide", "📖 Guida alle misure", None)]
# 0.1.10: a new EMELab shows only these tabs, in this order (after 🧭 Assistente); the others are switched on in
# «Schede da mostrare e ordine» (Assistant). 🏠 Stazione is always shown.
DEFAULT_ON = ["live", "station", "moon", "log", "planner"]
DEFAULT_ORDER = DEFAULT_ON + [k for k, _, _ in TABS[1:] if k not in DEFAULT_ON]
_saved = openems_local.load_settings().get("tabs")
if "tabs_on" not in S and _saved is not None and not openems_local.load_settings().get("tabs_defaults_0110"):
    _saved = [k for k in DEFAULT_ON if k != "station"]               # once: the new defaults also on PCs already set up
    openems_local.save_settings(tabs=_saved, tabs_order=DEFAULT_ORDER, tabs_defaults_0110=True,
                                tabs_gpsdo_offered=True, tabs_moon_offered=True, tabs_q65lab_offered=True,
                                tabs_nanoham_offered=True, tabs_radio_offered=True, tabs_horizon_offered=True,
                                tabs_skydome_offered=True)
if "tabs_on" not in S:
    if _saved is not None and ({"sspa", "twt"} & set(_saved)):       # 0.1.1 had SSPA and TWT as two tabs
        _saved = [k for k in _saved if k not in ("sspa", "twt")] + ["power"]
    if _saved is not None and "signal" in _saved:                    # 0.1.8: «Segnale e stazioni» is inside the Planner
        _saved = [k for k in _saved if k != "signal"] + ([] if "planner" in _saved else ["planner"])
    if _saved is not None and "gpsdo" not in _saved and not openems_local.load_settings().get("tabs_gpsdo_offered"):
        _saved = list(_saved) + ["gpsdo"]                             # 0.1.6: new GPSDO tab shown once by default
        openems_local.save_settings(tabs=_saved, tabs_gpsdo_offered=True)
    if _saved is not None and "moon" not in _saved and not openems_local.load_settings().get("tabs_moon_offered"):
        _saved = list(_saved) + ["moon"]                              # new Moon tab shown once by default
        openems_local.save_settings(tabs=_saved, tabs_moon_offered=True)
    if _saved is not None and "q65lab" not in _saved and not openems_local.load_settings().get("tabs_q65lab_offered"):
        _saved = list(_saved) + ["q65lab"]                            # 0.1.17: new Q65 Lab tab shown once (Ivan asked for it)
        openems_local.save_settings(tabs=_saved, tabs_q65lab_offered=True)
    if _saved is not None and "nanoham" not in _saved and not openems_local.load_settings().get("tabs_nanoham_offered"):
        _saved = list(_saved) + ["nanoham"]                           # 0.1.20: new nanoHam tab shown once (Ivan asked for it)
        openems_local.save_settings(tabs=_saved, tabs_nanoham_offered=True)
    if _saved is not None and "radio" not in _saved and not openems_local.load_settings().get("tabs_radio_offered"):
        _saved = list(_saved) + ["radio"]                             # 0.1.20: new Radio tab shown once (Ivan asked for it)
        openems_local.save_settings(tabs=_saved, tabs_radio_offered=True)
    for _k in ("horizon", "skydome"):                                 # 0.1.23: new tabs shown once (Ivan asked for them)
        if _saved is not None and _k not in _saved and not openems_local.load_settings().get(f"tabs_{_k}_offered"):
            _saved = list(_saved) + [_k]
            openems_local.save_settings(tabs=_saved, **{f"tabs_{_k}_offered": True})
    if _saved is None and os.environ.get("EMELAB_TABS") == "all":     # tests: every tab on a fresh PC
        _saved = [k for k, _, _ in TABS[2:]]
    S["tabs_on"] = [k for k, _, _ in TABS[2:] if (_saved is None and k in DEFAULT_ON) or (_saved and k in _saved)]


if "tabs_order" not in S:
    S["tabs_order"] = tab_order.merge(DEFAULT_ORDER, openems_local.load_settings().get("tabs_order"))


def _save_tabs():
    try:
        openems_local.save_settings(tabs=S["tabs_on"], tabs_order=S["tabs_order"], tabs_defaults_0110=True,
                                    tabs_gpsdo_offered=True, tabs_moon_offered=True,
                                    tabs_q65lab_offered=True, tabs_nanoham_offered=True,
                                    tabs_radio_offered=True, tabs_horizon_offered=True,
                                    tabs_skydome_offered=True)  # a choice: no more offers
    except Exception:
        pass


def _toggle_tab(k):
    on = [x for x in S["tabs_on"] if x != k]
    S["tabs_on"] = on + [k] if S.get(f"tabvis_{k}") else on
    _save_tabs()


def _move_tab(k, delta):
    S["tabs_order"] = tab_order.move(S["tabs_order"], k, delta)
    _save_tabs()


def _reset_tab_order():
    S["tabs_order"] = list(DEFAULT_ORDER)
    _save_tabs()


# The main tab bar goes onto more rows (two with the usual tabs) instead of scrolling sideways. Rows are a little lower
# (30 px instead of 40) and the gap under the bar smaller, so 🔴 Live still fits a 1920×1030 screen without scrolling.
_TABS_CSS = """<style>
.st-key-main_tab>div>[role=tablist],.st-key-main_tab>div>[data-baseweb=tab-list]{flex-wrap:wrap !important;overflow:visible !important}
.st-key-main_tab>div>[role=tablist]{row-gap:0 !important}
.st-key-main_tab>div>[role=tablist]>[role=tab],.st-key-main_tab>div>[data-baseweb=tab-list]>[role=tab]{flex:0 0 auto;height:30px !important}
.st-key-main_tab>div>[data-testid=stTabPanel]{padding-top:6px !important}
</style>"""


def _tabs_settings():
    """In the Assistant: which tabs to show and in which order (🧭 Assistente stays first, 🏠 Stazione always shown).
    Ivan: ticking or moving a tab must not reload the page, so the list is a fragment (only it reruns) and the tab bar
    changes with «Aggiorna la barra delle schede» (or at the next click anywhere else)."""
    with st.expander("⚙️ Schede da mostrare e ordine", expanded=S.pop("_tabs_keep_open", False)):
        _frag_tabs_list()


def _tabs_list():
    st.caption("Spunta le schede che usi e spostale con ⬆️ ⬇️, anche più di una: la pagina resta ferma e la scelta "
               "resta salvata su questo PC. 🧭 Assistente resta sempre la prima.")
    labels = {k: l for k, l, _ in TABS}
    order = S["tabs_order"]
    for i, k in enumerate(order):
        S[f"tabvis_{k}"] = k == "station" or k in S["tabs_on"]
        c = st.columns([8, 1, 1], vertical_alignment="center")
        c[0].checkbox(labels[k], key=f"tabvis_{k}", on_change=_toggle_tab, args=(k,), disabled=k == "station",
                      help="sempre visibile" if k == "station" else None)
        c[1].button("⬆️", key=f"tabup_{k}", on_click=_move_tab, args=(k, -1), disabled=i == 0, help="sposta prima")
        c[2].button("⬇️", key=f"tabdn_{k}", on_click=_move_tab, args=(k, 1), disabled=i == len(order) - 1,
                    help="sposta dopo")
    c = st.columns(2)
    c[0].button("↩️ Ordine originale", key="tab_order_reset", on_click=_reset_tab_order,
                help="rimette le schede nell'ordine di EMELab (la scelta di quelle visibili resta)")
    pending = (list(S["tabs_on"]), list(S["tabs_order"])) != S.get("_tabs_shown")
    if c[1].button("✅ Aggiorna la barra delle schede", key="tab_bar_apply", type="primary" if pending else "secondary",
                   disabled=not pending, help="mostra in alto le schede scelte"):
        S["_tabs_keep_open"] = True           # the list stays open after the reload
        st.rerun()


_frag_tabs_list = getattr(_st, "fragment", lambda f: f)(_tabs_list)

if not openems_local.load_settings().get("cam_enabled"):
    from emelab import moontrack as _mt
    _mt.stop()                                # camera switched off: released for ASICap and the others
if "nanoham" in S["tabs_on"]:
    ui_nanoham.ensure_running()               # the nanoHam boards are read (and logged) with any tab open
with st.sidebar:
    ui_live.watchdog_sidebar(D)               # watchdogs and camera alarm with any tab open
nav.register({k: l for k, l, _ in TABS})          # a click on an alert opens Live (or the alert's tab)
ui._wsjtx_banner()                   # WSJT-X settings that do not fit the band
if not S.pop("_update_dialog", False):
    ui_wsjtx_panel.popup(ui._wsjtx_service())   # pop-up when a QSO parameter is off (closed twice: never again)
    from emelab import ui_tracking as _ui_tracking
    _ui_tracking.popup()                         # alarm when DriverDish (EA3HMJ) stops working (read-only check)
_by_key = {t[0]: t for t in TABS}
shown = [TABS[0]] + [_by_key[k] for k in S["tabs_order"] if k == "station" or k in S["tabs_on"]]
S["_tabs_shown"] = (list(S["tabs_on"]), list(S["tabs_order"]))   # what the tab bar shows (the chooser compares)
with _st.sidebar:                                    # in the sidebar: no empty gap above the tab bar
    _st.markdown(_TABS_CSS, unsafe_allow_html=True)   # Ivan: the tab bar wraps onto two rows instead of scrolling
try:      # with a key the active tab can be switched from the code (e.g. «Chi posso collegare» → Pianificatore)
    tabs = st.tabs([l for _, l, _ in shown], key="main_tab", on_change="rerun")
except TypeError:                                   # Streamlit without state on tabs
    tabs = st.tabs([l for _, l, _ in shown])
for tab, (k, _, fn) in zip(tabs, shown):
    with tab:
        if k == "station":
            ui._station(D)
            st.divider()
            st.subheader("🧪 Cosa misurare o provare adesso")
            for sgg in coach.suggestions(D)[:8]:
                st.markdown("- " + i18n.tr(sgg["text"]))
        elif k == "wizard":
            _tabs_settings()
            fn(D)
        elif k == "guide":
            ui._guide()
        elif k == "new":
            fn(D, getattr(tab, "open", None))   # True/False when Streamlit tracks the active tab, None otherwise
        else:
            fn(D)

nav.toast_hook()
_show_counters()                            # QSO/measurements added or deleted in this run (ADIF import, WSJT-X…)
stallwatch.run_finished()
