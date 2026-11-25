# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""WSJT-X ALL.TXT in the interface: the file followed live (📻 WSJT-X tab, with a «Band Activity / Rx Frequency»
view laid out like WSJT-X) and the statistics of every decode at 10 GHz and up (📉 Statistiche QSO tab)."""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as _st

from emelab import alltxt, i18n, logbook as lb, stations as stn
from emelab import settings as openems_local

st = i18n.wrap(_st)


def _bl(b):
    return stn.band_label(b)


def save_pos(path, offset):
    openems_local.save_settings(wsjtx_all_pos={"path": path, "offset": int(offset)})


def autostart(svc, sets):
    """Follow ALL.TXT again at EMELab start if it was switched on, from where it stopped."""
    if sets.get("wsjtx_all_on") and not svc.alltxt_running and sets.get("wsjtx_all"):
        pos = sets.get("wsjtx_all_pos") or {}
        svc.on_all_pos = save_pos
        svc.start_alltxt(sets["wsjtx_all"], pos.get("offset") if pos.get("path") == sets["wsjtx_all"] else None)


# ------------------------------------------------------------------ 📻 WSJT-X tab
def file_box(D, svc, sets):
    st.markdown("#### " + i18n.tr("📄 ALL.TXT di WSJT-X: tutte le decodifiche"))
    st.caption("WSJT-X scrive in ALL.TXT ogni messaggio decodificato e ogni tua trasmissione, con SNR, DT e offset audio. "
               "EMELab lo segue come wsjtx_log.adi: legge solo le righe nuove e tiene solo quelle da 10 GHz in su "
               "(il traffico FT8 delle altre bande viene saltato). Il file è nella stessa cartella di wsjtx_log.adi.")
    found = alltxt.find_default()
    if not (_st.session_state.get("wj_all") or "").strip():
        _st.session_state["wj_all"] = sets.get("wsjtx_all") or (str(found) if found else "")
    c = st.columns([4, 2])
    path = c[0].text_input("Percorso di ALL.TXT", key="wj_all",
                           help="il file o la cartella che WSJT-X apre con File → Open log directory")
    clean = alltxt.clean_path(path)
    ok = bool(clean) and Path(clean).is_file()
    if not svc.alltxt_running:
        past = st.checkbox("Leggi anche tutto lo storico già presente in ALL.TXT (i doppioni vengono saltati)", True,
                           key="wj_all_past")
        if c[1].button("▶️ Segui ALL.TXT in tempo reale", type="primary", key="wj_all_on", disabled=not ok):
            openems_local.save_settings(wsjtx_all_on=True, wsjtx_all=clean, wsjtx_all_pos={})
            svc.on_all_pos = save_pos
            svc.start_alltxt(clean, 0 if past else None)
            st.rerun()
        if path.strip() and not ok:
            st.warning("File non trovato: controlla il percorso (in WSJT-X: File → Open log directory).")
        elif not path.strip():
            st.warning("Non ho trovato ALL.TXT nelle cartelle di WSJT-X di questo PC: incolla qui sopra il percorso "
                       "della cartella che WSJT-X apre con File → Open log directory.")
        return
    if c[1].button("⏹️ Smetti di seguire ALL.TXT", key="wj_all_off"):
        svc.stop_alltxt()
        openems_local.save_settings(wsjtx_all_on=False)
        st.rerun()
    if c[1].button("🔁 Rileggi ALL.TXT da capo", key="wj_all_again",
                   help="legge di nuovo tutto il file: le righe già nel database vengono saltate"):
        svc.start_alltxt(str(svc.all_tail.path), 0)
        st.rerun()
    band_activity(D, svc)


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


@_frag(5)
def band_activity(D, svc):
    """Live view laid out like the two panes of WSJT-X: Band Activity (every decode) and Rx Frequency (my
    transmissions and the messages to or from me), refreshed every 5 seconds."""
    tail = svc.all_tail
    if tail is None:
        return
    behind = tail.behind
    rd = svc.all_read
    st.markdown(i18n.tr("Seguo") + f" `{tail.path}` · " + i18n.tr("righe da 10 GHz in su lette") +
                f": Rx {rd['rx']} · Tx {rd['tx']}" +
                (" · " + i18n.tr("ultima riga") + f" {svc.all_seen:%H:%M:%S} UTC" if svc.all_seen else ""))
    if behind > 0:
        st.info(i18n.tr("Sto leggendo lo storico di ALL.TXT") + f": {behind / 1e6:,.1f} MB " + i18n.tr("ancora da leggere") + "…")
    recent = list(svc.all_recent)[:120]
    if not recent:
        st.caption("Ancora nessuna riga da 10 GHz in su: appena WSJT-X decodifica qualcosa compare qui.")
        return
    my = ((D.station() or {}).get("callsign") or "").upper()
    now = datetime.now(timezone.utc)
    last_h = [r for r in recent if r["rxtx"] == "Rx" and now - r["utc"] < timedelta(hours=1)]
    if last_h:
        c = st.columns(4)
        c[0].metric("Stazioni nell'ultima ora", len({r["call"] for r in last_h if r["call"]}))
        c[1].metric("SNR migliore (1 h)", f"{max(r['snr_db'] for r in last_h)} dB")
        c[2].metric("DT medio (1 h)", f"{sum(r['dt_s'] for r in last_h) / len(last_h):.1f} s")
        c[3].metric("Banda", _bl(last_h[0]["band"]))
    left = [r for r in recent if r["rxtx"] == "Rx"][:40]
    right = [r for r in recent if r["rxtx"] == "Tx" or (my and my in r["message"].upper().split())][:40]
    c = st.columns(2)
    c[0].markdown(f"**{i18n.tr('Band Activity')}**")
    c[0].markdown(_pane(left, my), unsafe_allow_html=True)
    c[1].markdown(f"**{i18n.tr('Rx Frequency')}**")
    c[1].markdown(_pane(right, my), unsafe_allow_html=True)
    st.caption("Come in WSJT-X: verde = CQ, rosso = messaggi con il tuo nominativo, giallo = le tue trasmissioni. "
               "Ultime righe in alto. Si aggiorna da solo ogni 5 secondi.")


def _pane(rows, my) -> str:
    """One WSJT-X pane: «UTC  dB   DT Freq    Message», monospace, same colours as WSJT-X."""
    head = "UTC    dB   DT Freq   Message"
    lines = []
    for r in rows:
        msg = r["message"]
        if r["rxtx"] == "Tx":
            bg, text = "#ffff66", f"{r['utc']:%H%M%S}  Tx      {r['df_hz']:>4}  {msg}"
        else:
            words = msg.upper().split()
            bg = "#ff8080" if my and my in words else "#66ff66" if words[:1] == ["CQ"] else "transparent"
            text = f"{r['utc']:%H%M%S} {r['snr_db']:>3} {r['dt_s']:>4.1f} {r['df_hz']:>4}  {msg}"
        lines.append(f'<div style="background:{bg};white-space:pre">{html.escape(text)}</div>')
    body = "".join(lines) or '<div style="color:#888">—</div>'
    return ('<div style="font-family:Consolas,\'Courier New\',monospace;font-size:13px;background:#ffffff;color:#000;'
            'border:1px solid #999;height:330px;overflow-y:auto;padding:2px 4px">'
            f'<div style="background:#ddd;white-space:pre;font-weight:bold">{head}</div>{body}</div>')


# ------------------------------------------------------------------ 📉 statistics
def _doppler_fn(D):
    from emelab import astro
    me = D.station() or {}
    if not me.get("lat"):
        return None
    cache = {}

    def f(call, grid, band, t):
        loc = grid or ((D.station_of(call) or {}).get("locator"))
        if not loc or band not in lb.BAND_F:
            return None
        key = (loc, band, t.replace(minute=0, second=0))
        if key not in cache:
            m = astro.mutual(t, (me["lat"], me["lon"]), astro.locator_to_latlon(loc), me.get("height_m") or 0.0)
            cache[key] = m["doppler_hz_per_ghz"] * lb.BAND_F[band]
        return cache[key]
    return f


def _v(x, fmt="{:.0f}"):
    return "" if x is None else fmt.format(x)


def stats_section(D):
    st.divider()
    st.subheader("📡 Ascolti da ALL.TXT di WSJT-X")
    rx_all, tx_all = D.eme_decodes(), D.tx_lines()
    if not rx_all and not tx_all:
        st.info("Nessuna decodifica da 10 GHz in su: nella scheda 📻 WSJT-X premi «▶️ Segui ALL.TXT in tempo reale» "
                "e EMELab legge tutto lo storico del file.")
        return
    bands = sorted({r["band"] for r in rx_all} | {r["band"] for r in tx_all}, key=alltxt._band_order)
    on = st.multiselect("Bande", bands, default=bands, format_func=_bl, key="at_bands")
    rx = [r for r in rx_all if r["band"] in on]
    tx = [r for r in tx_all if r["band"] in on]
    me = D.station() or {}
    s = alltxt.summarize(rx, tx, D.qsos(), me.get("callsign"), _doppler_fn(D))
    c = st.columns(5)
    c[0].metric("Decodifiche", s["n_rx"])
    c[1].metric("Stazioni sentite", len({x["call"] for x in s["stations"]}))
    c[2].metric("Sessioni", len(s["sessions"]))
    c[3].metric("Ore di attività", f"{sum(b['hours'] for b in s['bands'].values()):.1f}")
    c[4].metric("Sentite ma non collegate", len(s["heard_not_worked"]))

    st.markdown("**" + i18n.tr("Per banda") + "**")
    st.dataframe([{"Banda": _bl(b), "Decodifiche": v["n_rx"], "Trasmissioni": v["n_tx"], "Stazioni": v["stations"],
                   "SNR migliore (dB)": _v(v["snr_best"]), "SNR medio (dB)": _v(v["snr_mean"], "{:.1f}"),
                   "DT medio (s)": _v(v["dt_mean"], "{:.2f}"), "Sessioni": v["sessions"],
                   "Ore": f"{v['hours']:.1f}", "Prima decodifica": _v(v["first"], "{:%Y-%m-%d}"),
                   "Ultima decodifica": _v(v["last"], "{:%Y-%m-%d}")} for b, v in s["bands"].items()],
                 hide_index=True, width="stretch")
    _charts(s, rx)

    st.markdown("**" + i18n.tr("Per stazione") + "**")
    st.caption("DF = offset audio della decodifica. «Deriva DF» è la pendenza mediana del DF dentro una sessione: "
               "vicino a 0 Hz/min se il Doppler è corretto (CFOM o Doppler tracking in WSJT-X). «Doppler previsto» è "
               "lo spostamento atteso dalla Luna all'ultimo ascolto, calcolato dai due locator.")
    st.dataframe([_station_row(x) for x in s["stations"]], hide_index=True, width="stretch")

    if s["heard_not_worked"]:
        st.markdown("**" + i18n.tr("Sentite ma non collegate") + "**")
        st.caption("Stazioni decodificate su una banda dove non hai ancora un QSO con loro nel Log QSO.")
        st.dataframe([{"Nominativo": x["call"], "Banda": _bl(x["band"]), "Locator": x["locator"] or "",
                       "Decodifiche": x["n"], "SNR migliore (dB)": _v(x["snr_best"]), "Ultima volta": f"{x['last']:%Y-%m-%d %H:%M}",
                       "CQ": x["cq"], "Chiamate a me": x["to_me"]}
                      for x in sorted(s["heard_not_worked"], key=lambda x: (-(x["snr_best"] or -99)))],
                     hide_index=True, width="stretch")

    st.markdown("**" + i18n.tr("Sessioni di attività") + "**")
    st.caption(i18n.tr("Una sessione finisce dopo") + f" {alltxt.SESSION_GAP_MIN} " +
               i18n.tr("minuti senza ricezioni né trasmissioni sulla banda."))
    st.dataframe([{"Inizio (UTC)": f"{x['start']:%Y-%m-%d %H:%M}", "Fine (UTC)": f"{x['end']:%H:%M}", "Durata (min)": x["minutes"],
                   "Banda": _bl(x["band"]), "Rx": x["n_rx"], "Tx": x["n_tx"], "SNR migliore (dB)": _v(x["snr_best"]),
                   "Stazioni sentite": ", ".join(x["calls"]), "QSO nel log": ", ".join(x["worked"])}
                  for x in reversed(s["sessions"][-300:])], hide_index=True, width="stretch")


def _station_row(x):
    return {"Nominativo": x["call"], "Banda": _bl(x["band"]), "Locator": x["locator"] or "", "Decodifiche": x["n"],
            "Sessioni": x["sessions"], "Prima volta": f"{x['first']:%Y-%m-%d}", "Ultima volta": f"{x['last']:%Y-%m-%d %H:%M}",
            "SNR migliore (dB)": _v(x["snr_best"]), "SNR medio (dB)": _v(x["snr_mean"], "{:.1f}"),
            "SNR peggiore (dB)": _v(x["snr_worst"]),
            "DT medio (s)": _v(x["dt_mean"], "{:.2f}"),
            "DT min…max (s)": "" if x["dt_min"] is None else f"{x['dt_min']:.1f}…{x['dt_max']:.1f}",
            "DF medio (Hz)": _v(x["df_mean"]),
            "DF min…max (Hz)": "" if x["df_min"] is None else f"{x['df_min']}…{x['df_max']}",
            "Deriva DF (Hz/min)": _v(x["df_drift"], "{:+.1f}"), "Doppler previsto (Hz)": _v(x["doppler_hz"], "{:+,.0f}"),
            "Chiamate a me": x["to_me"], "Già collegata": "✅" if x["worked"] else ""}


def _charts(s, rx):
    c = st.columns(2)
    fig = go.Figure()
    for b, hours in s["by_hour"].items():
        fig.add_bar(x=list(range(24)), y=hours, name=_bl(b), marker_color=lb.BAND_COLORS.get(b, "#777"))
    fig.update_layout(barmode="stack", title="Decodifiche per ora UTC", xaxis_title="ora UTC", yaxis_title="decodifiche",
                      height=320, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="")
    c[0].plotly_chart(fig, width="stretch", key="at_hours")
    fig = go.Figure()
    for b in s["bands"]:
        v = [r["snr"] for r in rx if r["band"] == b and r["snr"] is not None]
        if v:
            fig.add_histogram(x=v, name=_bl(b), marker_color=lb.BAND_COLORS.get(b, "#777"), xbins=dict(size=1))
    fig.update_layout(barmode="stack", title="Distribuzione dell'SNR", xaxis_title="SNR (dB)", yaxis_title="decodifiche",
                      height=320, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="")
    c[1].plotly_chart(fig, width="stretch", key="at_snr")
