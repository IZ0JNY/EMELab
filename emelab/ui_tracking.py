# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Pointing tab: link with the EA3HMJ Tracking Software Suite (DriverDish): drift scans and autocorrection files,
read-only status of the dish from DriverDish's telnet server, and the ephemeris of its Astroserver."""
from __future__ import annotations

import math
from datetime import timezone

import numpy as np
import plotly.graph_objects as go
import streamlit as _st

from emelab import astro, ea3hmj, i18n, sunscan
from emelab import settings as openems_local

st = i18n.wrap(_st)


def tracking_box(D, hp_expected: float | None = None):
    st.divider()
    st.subheader("📡 Sistema di inseguimento EA3HMJ (DriverDish)")
    st.caption("EMELab legge i file e lo stato di DriverDish (José EA3HMJ, EA3HMJ Tracking Software Suite): scansioni a "
               "deriva, mappa delle correzioni in azimut, posizione e offset dell'antenna. Il comando dell'antenna resta a "
               "DriverDish: EMELab non la muove.")
    t3, t1, t2 = st.tabs(["🔌 Stato dell'antenna", "☀️ Scansione a deriva (DriftScan)", "🧭 Correzioni (corrections.txt)"])
    with t1:
        _driftscan(D, hp_expected)
    with t2:
        _corrections(D)
    with t3:
        _status(D, hp_expected)


def _driftscan(D, hp_expected):
    up = st.file_uploader("File driftScan_….csv di DriverDish", type=["csv", "txt"], key="ea_drift")
    if up is None:
        st.caption("In DriverDish: menu DriftScan → Start Drift Scan; il file si trova nella cartella tracking.")
        return
    d = ea3hmj.parse_driftscan(up.getvalue().decode("utf-8", "replace"))
    if len(d["t"]) < 10:
        st.error("Il file non contiene abbastanza punti.")
        return
    stn = D.station()
    t0 = d["t"][0]
    secs = np.array([(t - t0).total_seconds() for t in d["t"]])
    sn = np.array(d["sn_db"])
    tgt = (d.get("target") or "Sun").lower()
    mid = d["t"][len(d["t"]) // 2]
    s = astro.sky(mid, stn.get("lat") or 0.0, stn.get("lon") or 0.0, stn.get("height_m") or 0.0)
    body = s.moon if tgt.startswith("moon") else s.sun
    x = sunscan.drift_angle(secs - secs[int(np.argmax(sn))], body.dec)
    p_lin = 10 ** (sn / 10)
    diam = body.diam_deg * (sunscan.SUN_RADIO_DIAM_FACTOR if hasattr(sunscan, "SUN_RADIO_DIAM_FACTOR") and not tgt.startswith("moon") else 1.0)
    fit = sunscan.fit_scan(x, p_lin, sun_diam=diam)
    f = d.get("freq_ghz")
    Dm = d.get("diameter_m")
    hp_th = (sunscan.hpbw_deg(f, Dm) if f and Dm else hp_expected)
    m = st.columns(4)
    m[0].metric("HPBW misurata", f"{fit['hpbw_deg']:.3f}°",
                f"{fit['hpbw_deg'] - hp_th:+.3f}° " + i18n.tr("rispetto al calcolo") if hp_th else None, delta_color="off")
    m[1].metric("Fattore Y", f"{fit['y_db']:.2f} dB")
    m[2].metric("Diametro del disco", f"{diam:.4f}°")
    m[3].metric("k = HPBW·D/λ", f"{fit['hpbw_deg'] * Dm / (0.299792458 / f):.1f}°" if f and Dm else "—")
    xs = np.linspace(x.min(), x.max(), 400)
    mod = sunscan.scan_disc(xs - fit["offset_deg"], fit["hpbw_deg"], diam)
    fig = go.Figure(go.Scatter(x=x, y=sn, mode="markers", marker=dict(size=4), name="misura DriverDish"))
    fig.add_trace(go.Scatter(x=xs, y=10 * np.log10(np.maximum(fit["baseline"] + fit["amplitude"] * mod / mod.max(), 1e-12)),
                             name="modello disco ⊗ fascio"))
    fig.update_layout(title=f"DriftScan {d.get('target', '')} {f or ''} GHz · {Dm or ''} m", xaxis_title=i18n.tr("angolo dal centro (°)"),
                      yaxis_title="SN (dB)", height=340, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("Adattamento dell'intera curva (disco ⊗ fascio gaussiano, modello IZ0JNY) invece dei soli punti 15–85 %: "
               "lo stesso risultato della deconvoluzione di J. Köppen DF3GJ, ma con tutti i punti della scansione.")


def _corrections(D):
    up = st.file_uploader("corrections.txt di DriverDish (Autocorrection)", type=["txt", "csv"], key="ea_corr")
    if up is None:
        st.caption("In DriverDish: AutoCorr → Auto Run; alla fine il programma scrive corrections.txt.")
        return
    c = ea3hmj.parse_corrections(up.getvalue().decode("utf-8", "replace"))
    pts = c["points"]
    if len(pts) < 3:
        st.error("Il file non contiene abbastanza punti.")
        return
    az = np.array([p[0] for p in pts])
    off = np.array([p[1] for p in pts])
    tgt = st.radio("Misurate su", ["Sole", "Luna"], horizontal=True, key="ea_corr_tgt")
    stn = D.station()
    el = None
    try:
        from datetime import datetime, timedelta
        day = datetime.strptime(c["date"].replace("/", "-"), "%d-%m-%Y").replace(tzinfo=timezone.utc) if c.get("date") else None
    except ValueError:
        day = None
    if day and stn.get("lat"):
        track = [astro.sky(day + timedelta(minutes=10 * i), stn["lat"], stn["lon"], stn.get("height_m") or 0.0) for i in range(144)]
        tb = [(b.az, b.el) for s in track for b in [(s.moon if tgt == "Luna" else s.sun)] if b.el > 0]
        if tb:
            taz, tel = np.array([p[0] for p in tb]), np.array([p[1] for p in tb])
            o = np.argsort(taz)
            el = np.interp(az, taz[o], tel[o])
    m = st.columns(4)
    m[0].metric("Punti", len(pts))
    m[1].metric("Correzione media", f"{off.mean():+.3f}°")
    m[2].metric("Escursione", f"{off.max() - off.min():.3f}°")
    m[3].metric("Data", c.get("date") or "—")
    fig = go.Figure(go.Scatter(x=az, y=off, mode="lines+markers", name="correzione AZ"))
    if el is not None:
        fig.add_trace(go.Scatter(x=az, y=el, name="EL del bersaglio", yaxis="y2", line=dict(dash="dot")))
        A = np.vstack([np.ones_like(el), np.tan(np.radians(el))]).T
        cross = off * np.cos(np.radians(el))
        coef, *_ = np.linalg.lstsq(A, cross, rcond=None)
        res = cross - A @ coef
        st.markdown(i18n.tr("Scomposizione (errore AZ·cos EL)") + f": zero AZ **{coef[0]:+.3f}°**, " + i18n.tr("inclinazione dell'asse") +
                    f" **{coef[1]:+.3f}°** · " + i18n.tr("residuo") + f" {res.std():.3f}°")
    fig.update_layout(title="Mappa delle correzioni in azimut", xaxis_title="AZ (°)", yaxis_title=i18n.tr("correzione (°)"),
                      yaxis2=dict(overlaying="y", side="right", title="EL (°)"), height=320, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption("Se la correzione cambia molto con l'elevazione, il supporto non è in bolla (termine in tan EL): metterlo in "
               "bolla toglie la causa invece di correggerla.")


@_st.cache_resource(show_spinner=False)
def _monitor(host: str, port: int) -> ea3hmj.DriverDishMonitor:
    return ea3hmj.DriverDishMonitor(host, port)


def _status(D, hp):
    sets = openems_local.load_settings()
    c = st.columns([3, 1.4, 2.2])
    host = c[0].text_input("Indirizzo del PC con DriverDish", sets.get("dd_host", "127.0.0.1"), key="ea_host",
                           help="127.0.0.1 se DriverDish gira su questo PC, altrimenti l'IP che DriverDish mostra in Setup → Local IP")
    port = c[1].number_input("Porta telnet", 1, 65535, int(sets.get("dd_port", 9999)), key="ea_port")
    live = c[2].toggle("🔴 Leggi in tempo reale", bool(sets.get("dd_live", False)), key="ea_live",
                       help="EMELab chiede «status» a DriverDish ogni 2 secondi, in sottofondo")
    host = host.strip() or "127.0.0.1"
    if (host, int(port), live) != (sets.get("dd_host"), sets.get("dd_port"), sets.get("dd_live")):
        openems_local.save_settings(dd_host=host, dd_port=int(port), dd_live=bool(live))
    if not live:
        _st.session_state["ea_problems"] = []
        old = _st.session_state.pop("ea_mon_key", None)
        if old:
            _monitor(*old).stop()
            _monitor.clear()
        st.caption("Solo lettura: EMELab non manda mai comandi che muovono la parabola. In DriverDish: Setup → "
                   "Telnet server, porta 9999, spunta «Run».")
        return
    key = (host, int(port))
    if _st.session_state.get("ea_mon_key") not in (None, key):
        _monitor(*_st.session_state["ea_mon_key"]).stop()
        _monitor.clear()
    _st.session_state["ea_mon_key"] = key
    mon = _monitor(*key)
    if not mon.alive:
        _monitor.clear()
        mon = _monitor(*key)
    alarm = st.checkbox("🚨 Pop-up di allarme se DriverDish non funziona", bool(sets.get("dd_alarm", True)), key="ea_alarm",
                        help="DriverDish che non risponde, dati fermi, antenna ferma durante l'inseguimento, errore oltre HPBW/2, "
                             "effemeridi della Luna diverse da quelle di EMELab")
    if alarm != sets.get("dd_alarm", True):
        openems_local.save_settings(dd_alarm=bool(alarm))
    _st.session_state["ea_alarm_on"] = alarm
    _live_status(D, mon, hp)
    st.caption("Solo lettura: EMELab chiede a DriverDish soltanto «status» e «moving», mai comandi che muovono la "
               "parabola. La posizione della Luna è calcolata da EMELab per la tua stazione (con rifrazione radio).")


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


def _fmt(v, nd=3, unit="°"):
    return "—" if v is None else f"{v:.{nd}f}{unit}"


_ICON = {True: "✅", False: "❌", None: "➖"}


def _health_box(D, mon, hp, now):
    stn = D.station() or {}
    moon = None
    if stn.get("lat") is not None and stn.get("lon") is not None:
        moon = astro.sky(now, stn["lat"], stn["lon"], stn.get("height_m") or 0.0).moon
    checks = ea3hmj.health(mon.last, mon.error, list(mon.history), now, hp,
                           (moon.az, moon.el_radio) if moon is not None else None)
    probs = [c for c in checks if c["ok"] is False]
    S = _st.session_state
    S["ea_problems"] = probs
    with st.expander(("🚨 " if probs else "🩺 ") + i18n.tr("Controllo di DriverDish") +
                     (f": {len(probs)} " + i18n.tr("problemi") if probs else ": " + i18n.tr("tutto a posto")), expanded=bool(probs)):
        st.markdown("\n".join(f"- {_ICON[c['ok']]} {i18n.tr(c['label'])}" + (f" · {c['detail']}" if c["detail"] else "")
                               for c in checks))
    keys = sorted(c["key"] for c in probs)
    acked = S.setdefault("ea_acked", set())
    from emelab import dismiss
    dismiss.prune(acked, keys, S.setdefault("ea_gone", {}))   # alarms again only if gone for 2 minutes and back
    if S.get("ea_alarm_on", True) and set(keys) - acked and keys != S.get("ea_alert_keys"):
        S["ea_alert_keys"] = keys
        _st.rerun(scope="app")                       # full run: app.py opens the pop-up
    S["ea_alert_keys"] = keys
    return moon


@_frag(2)
def _live_status(D, mon, hp):
    from datetime import datetime
    now = datetime.now(timezone.utc)
    moon = _health_box(D, mon, hp, now)
    r = mon.last
    if r is None:
        if mon.error:
            st.warning(i18n.tr("DriverDish non raggiungibile: attiva il server telnet in DriverDish (Setup)") +
                       f" — {mon.host}:{mon.port} · {mon.error}")
        else:
            st.info(i18n.tr("Mi collego a DriverDish") + f" ({mon.host}:{mon.port})…")
        return
    age = (now - r["utc"]).total_seconds()
    if mon.error:
        st.warning(i18n.tr("Collegamento con DriverDish perso: mostro l'ultima lettura") + f" ({age:.0f} s) · {mon.error}")
    elif age > 10:
        st.warning(i18n.tr("DriverDish non risponde da") + f" {age:.0f} s")
    trk = r.get("tracking")
    mv = r.get("moving")
    state = ("🟢 " + i18n.tr("Inseguimento attivo") if trk else "⚪ " + i18n.tr("Inseguimento spento") if trk is False else "—")
    if mv:
        state += " · " + i18n.tr("in movimento")
    m = st.columns(4)
    m[0].metric("Bersaglio di DriverDish", r.get("target") or "—")
    m[1].metric("Stato", state)
    m[2].metric("Antenna AZ / EL", f"{_fmt(r.get('dish_az'))} / {_fmt(r.get('dish_el'))}")
    m[3].metric("Bersaglio AZ / EL", f"{_fmt(r.get('target_az'))} / {_fmt(r.get('target_el'))}")
    m = st.columns(4)
    m[0].metric("Errore AZ / EL (DriverDish)", f"{_fmt(r.get('err_az'))} / {_fmt(r.get('err_el'))}")
    m[1].metric("Offset AZ / EL", f"{_fmt(r.get('off_az'))} / {_fmt(r.get('off_el'))}")
    stn = D.station() or {}
    if moon is not None:
        m[2].metric("Luna calcolata da EMELab AZ / EL", f"{moon.az:.3f}° / {moon.el_radio:.3f}°")
    else:
        m[2].metric("Luna calcolata da EMELab AZ / EL", "—", help=i18n.tr("inserisci la posizione nella scheda Stazione"))
    err_moon = None
    if moon is not None and r.get("dish_az") is not None and r.get("dish_el") is not None:
        err_moon = ea3hmj.angle_between(r["dish_az"], r["dish_el"], moon.az, moon.el_radio)
        frac = f"{err_moon / hp:.2f} HPBW" if hp else None
        m[3].metric("Antenna ↔ Luna", f"{err_moon:.3f}°", frac, delta_color="off")
    if hp and err_moon is not None:
        loss = ea3hmj.pointing_loss_db(err_moon, hp)
        if moon.el_radio < 0:
            st.info(i18n.tr("La Luna è sotto l'orizzonte") + f" (EL {moon.el_radio:.1f}°).")
        elif err_moon <= hp / 10:
            st.success(i18n.tr("Puntata sulla Luna: errore entro HPBW/10") + f" ({err_moon:.3f}° ≤ {hp / 10:.3f}°, "
                       + i18n.tr("perdita") + f" {loss:.2f} dB, " + i18n.tr("eco proprie") + f" {2 * loss:.2f} dB)")
        elif err_moon <= hp / 2:
            st.warning(i18n.tr("Antenna vicino alla Luna ma oltre HPBW/10") + f": {err_moon:.3f}° (HPBW {hp:.3f}°, "
                       + i18n.tr("perdita") + f" {loss:.2f} dB, " + i18n.tr("eco proprie") + f" {2 * loss:.2f} dB)")
        else:
            st.error(i18n.tr("Antenna fuori dal fascio rispetto alla Luna") + f": {err_moon:.2f}° (HPBW {hp:.3f}°)")
    if moon is not None and (r.get("target") or "").strip().lower().startswith(("moon", "luna")) \
            and r.get("target_az") is not None and r.get("target_el") is not None:
        d = ea3hmj.angle_between(r["target_az"], r["target_el"], moon.az, moon.el_radio)
        st.caption(i18n.tr("Effemeridi: bersaglio di DriverDish e Luna di EMELab differiscono di") + f" {d:.3f}° "
                   f"(ΔAZ {((r['target_az'] - moon.az + 180) % 360) - 180:+.3f}°, ΔEL {r['target_el'] - moon.el_radio:+.3f}°)")
    hist = [(t, h) for t, h in mon.history if (now - t).total_seconds() < 1800]
    if len(hist) > 2:
        ts = [t for t, _ in hist]
        fig = go.Figure()
        e_dd = [math.hypot((h.get("err_az") or 0.0) * math.cos(math.radians(h.get("dish_el") or 0.0)), h.get("err_el") or 0.0)
                if h.get("err_az") is not None else None for _, h in hist]
        fig.add_trace(go.Scatter(x=ts, y=e_dd, name=i18n.tr("errore verso il bersaglio (DriverDish)")))
        if stn.get("lat") is not None:
            e_m = []
            for t, h in hist[::max(1, len(hist) // 120)]:
                if h.get("dish_az") is None:
                    continue
                mb = astro.sky(t, stn["lat"], stn["lon"], stn.get("height_m") or 0.0).moon
                e_m.append((t, ea3hmj.angle_between(h["dish_az"], h["dish_el"], mb.az, mb.el_radio)))
            if e_m:
                fig.add_trace(go.Scatter(x=[a for a, _ in e_m], y=[b for _, b in e_m], name=i18n.tr("antenna ↔ Luna")))
        if hp:
            fig.add_hline(y=hp / 10, line_dash="dot", annotation_text="HPBW/10")
            fig.add_hline(y=hp / 2, line_dash="dash", annotation_text="HPBW/2")
        fig.update_layout(title="Errore di puntamento negli ultimi 30 minuti", yaxis_title="°", height=300,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch", key="ea_live_plot")
    with st.expander("Risposta completa di «status»"):
        st.text(r.get("raw") or "")
    st.caption(i18n.tr("Ultima lettura da DriverDish") + f": {r['utc']:%H:%M:%S} UTC ({age:.0f} s)")


# ------------------------------------------------------------------ alarm pop-up (opened by app.py on a full run)
def _alarm_body(items):
    for a in items:
        st.error(i18n.tr(a["label"]) + " — " + i18n.tr("non va") + (f" ({a['detail']})" if a.get("detail") else ""))
    st.caption("EMELab legge soltanto: controlla DriverDish e la parabola. L'allarme torna se il problema sparisce e "
               "poi si ripresenta; si spegne nella scheda 🎯 Tracking.")
    from emelab import nav
    c = st.columns(2)
    if c[0].button("Ho visto", type="primary", key="ea_alarm_ok"):
        _ack()
        _st.rerun()
    if nav.button("driverdish", key="ea_alarm_go", on_click=_ack, container=c[1]):
        _st.rerun()


def _ack():
    S = _st.session_state
    S.setdefault("ea_acked", set()).update(c["key"] for c in S.get("ea_problems") or [])


try:
    _alarm = _st.dialog("🚨 DriverDish", width="large", on_dismiss=_ack)(_alarm_body)
except TypeError:                                   # older Streamlit: no on_dismiss
    _alarm = _st.dialog("🚨 DriverDish", width="large")(_alarm_body)


def popup():
    S = _st.session_state
    if not S.get("ea_alarm_on", True) or not S.get("ea_mon_key"):
        return
    if S.get("wj_alert_keys"):                      # the WSJT-X pop-up is open: one dialog at a time
        return
    probs = S.get("ea_problems") or []
    items = [c for c in probs if c["key"] not in S.get("ea_acked", set())]
    if items:
        _alarm(items)
