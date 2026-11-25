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
    st.caption("EME Assistant legge i file e lo stato di DriverDish (José EA3HMJ, EA3HMJ Tracking Software Suite): scansioni a "
               "deriva, mappa delle correzioni in azimut, posizione e offset dell'antenna. Il comando dell'antenna resta a "
               "DriverDish: EME Assistant non la muove.")
    t1, t2, t3 = st.tabs(["☀️ Scansione a deriva (DriftScan)", "🧭 Correzioni (corrections.txt)", "🔌 Stato dell'antenna"])
    with t1:
        _driftscan(D, hp_expected)
    with t2:
        _corrections(D)
    with t3:
        _status()


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


def _status():
    sets = openems_local.load_settings()
    c = st.columns(3)
    host = c[0].text_input("Indirizzo del PC con DriverDish", sets.get("dd_host", "127.0.0.1"), key="ea_host")
    port = c[1].number_input("Porta telnet", 1, 65535, int(sets.get("dd_port", 9999)), key="ea_port")
    if c[2].button("🔌 Leggi lo stato", key="ea_read"):
        openems_local.save_settings(dd_host=host.strip(), dd_port=int(port))
        try:
            r = ea3hmj.driverdish_query(["az", "el", "ao", "eo", "astro", "traking", "moving", "status"], host.strip(), int(port))
            _st.session_state["ea_status"] = r
        except OSError as e:
            st.error(i18n.tr("DriverDish non raggiungibile: attiva il server telnet in DriverDish (Setup)") + f" — {e}")
    r = _st.session_state.get("ea_status")
    if r:
        m = st.columns(4)
        m[0].metric("AZ antenna", r.get("az") or "—")
        m[1].metric("EL antenna", r.get("el") or "—")
        m[2].metric("Offset AZ / EL", f"{r.get('ao') or '—'} / {r.get('eo') or '—'}")
        m[3].metric("Inseguimento", r.get("traking") or "—")
        with st.expander("Risposta completa di «status»"):
            st.text(r.get("status") or "")
    st.caption("Solo lettura. In DriverDish: Setup → abilita il server telnet (porta 9999).")
