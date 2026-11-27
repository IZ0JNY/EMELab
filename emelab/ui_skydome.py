# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🌌 Sky dome tab: the sky seen from the station (azimuth across, elevation up) coloured by the sky noise of the
atmosphere at the chosen band, with Sun, Moon, planets, strong radio sources, galactic plane and ecliptic; when the
dish points at the Moon or at the Sun, which bodies are near the beam and how many kelvin they add; the passes of
the coming 30 days."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import plotly.graph_objects as go
import streamlit as _st

from emelab import atmos, i18n, moon, skydome, sky, wizard
from emelab import settings as openems_local
from emelab.stations import band_label

st = i18n.wrap(_st)
ASSUMED_COLOR = "#e8590c"
MARK = {"moon": ("#f5f0d0", 18), "sun": ("#ffb300", 18), "planet": ("#26a69a", 9), "source": ("#ab47bc", 9)}
ICON = {"Luna": "🌙", "Sole": "☀️"}


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _setup(D, f):
    for s in D.setups():
        if abs(float(s.get("band_ghz") or 0) - f) < 1.5 and s.get("D_m"):
            return s, False
    return {"D_m": 2.4, "eta_ap": 0.65, "edge_taper_db": 12.0}, True


def _weather():
    fc = _st.session_state.get("wz_fc") or []
    h = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    w = next((x for x in fc if x.get("utc") == h), None)
    if w and w.get("t_c") is not None and w.get("rh") is not None:
        return {"t_c": w["t_c"], "rh": w["rh"], "p_hpa": w.get("p_hpa") or 1013.25}, False
    return dict(moon.STD_WX), True


def _t_atm(f, wx, el):
    z = atmos.zenith_attenuation(f, wx["t_c"], wx["rh"], wx["p_hpa"])["total"]
    return atmos.sky_temperature(atmos.slant_attenuation(z, max(el, 0.5)), wx["t_c"])


def _dome(bl, f, wx, tracks, hz, tgt, hp, gal, ecl):
    fig = go.Figure()
    els = np.arange(0, 91, 1.0)
    tsky = [[_t_atm(f, wx, e)] * 2 for e in els]
    fig.add_trace(go.Heatmap(x=[0.0, 360.0], y=els, z=tsky, colorscale="Turbo", zmin=0, zmax=max(60, tsky[0][0]),
                             colorbar=dict(title="T cielo (K)", len=0.8), opacity=0.55, hoverinfo="skip"))
    if hz:
        a = list(range(0, 361))
        fig.add_trace(go.Scatter(x=a, y=[min(wizard.el_min(hz, x), 90) for x in a], fill="tozeroy", mode="lines",
                                 line=dict(color="#6d4c41", width=1), fillcolor="rgba(109,76,65,0.75)",
                                 name=i18n.tr("Orizzonte libero"), hoverinfo="skip"))
    for pts, name, col, dash in ((gal, i18n.tr("Piano galattico"), "white", "dot"),
                                 (ecl, i18n.tr("Eclittica"), "#fff59d", "dash")):
        xs, ys = [], []
        for a, e in pts:
            if e < 0:
                xs.append(None)
                ys.append(None)
                continue
            if xs and xs[-1] is not None and abs(a - xs[-1]) > 180:
                xs.append(None)
                ys.append(None)
            xs.append(a)
            ys.append(e)
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=col, dash=dash, width=1.5), name=name,
                                 hoverinfo="skip"))
    tz = _local_tz()
    for name, tr in tracks.items():
        xs, ys, tx = [], [], []
        for t, a, e in tr:
            if e < 0 or (xs and xs[-1] is not None and abs(a - xs[-1]) > 180):
                xs.append(None)
                ys.append(None)
                tx.append("")
                if e < 0:
                    continue
            xs.append(a)
            ys.append(e)
            tx.append(f"{t.astimezone(tz):%H:%M}")
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", text=tx, name=f"{ICON[name]} " + i18n.tr("prossime 24 ore"),
                                 line=dict(color="#bdbdbd" if name == "Luna" else "#ffca28", width=1.5),
                                 hovertemplate="%{text} · AZ %{x:.0f}° · EL %{y:.1f}°<extra></extra>"))
    up = [b for b in bl if b["el"] > -1]
    for kind in ("source", "planet", "sun", "moon"):
        bs = [b for b in up if b["kind"] == kind]
        if not bs:
            continue
        col, size = MARK[kind]
        fig.add_trace(go.Scatter(x=[b["az"] for b in bs], y=[b["el"] for b in bs], mode="markers+text",
                                 text=[ICON.get(b["name"], "") + " " + i18n.tr(b["name"]) for b in bs],
                                 textposition="top center", textfont=dict(color="white", size=11),
                                 marker=dict(color=col, size=size, line=dict(color="#333", width=1)),
                                 name={"source": i18n.tr("Radiosorgenti"), "planet": i18n.tr("Pianeti"),
                                       "sun": i18n.tr("Sole"), "moon": i18n.tr("Luna")}[kind],
                                 hovertemplate="%{text} · AZ %{x:.1f}° · EL %{y:.1f}°<extra></extra>"))
    fig.update_layout(height=470, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="#0b1a33",
                      xaxis=dict(range=[0, 360], tickvals=list(range(0, 361, 45)),
                                 ticktext=["N", "NE", "E", "SE", "S", "SO", "O", "NO", "N"], title="Azimut",
                                 showgrid=False),
                      yaxis=dict(range=[0, 90], title="Elevazione (°)", showgrid=False),
                      legend=dict(orientation="h", y=-0.2))
    return i18n.translate_plotly(fig)


def _zoom(res, bl, span):
    """Around the beam axis: offsets in cross-elevation and elevation, circles at 1, 3 and 10 beamwidths."""
    tgt, hp = res["target"], res["hpbw"]
    fig = go.Figure()
    th = np.linspace(0, 2 * math.pi, 120)
    for k, lab in ((0.5, "HPBW"), (1.5, "3 HPBW"), (5.0, "10 HPBW")):
        r = k * hp
        if r < span * 1.2:
            fig.add_trace(go.Scatter(x=r * np.cos(th), y=r * np.sin(th), mode="lines", name=lab,
                                     line=dict(color="#90caf9", dash="dot" if k > 0.5 else "solid", width=1),
                                     hoverinfo="skip"))
    xs, ys, txt, cols, sizes = [], [], [], [], []
    for b in bl:
        dx = ((b["az"] - tgt["az"] + 180) % 360 - 180) * math.cos(math.radians(tgt["el"]))
        dy = b["el"] - tgt["el"]
        if abs(dx) <= span and abs(dy) <= span:
            xs.append(dx)
            ys.append(dy)
            txt.append(ICON.get(b["name"], "") + " " + i18n.tr(b["name"]))
            cols.append(MARK[b["kind"]][0])
            sizes.append(max(8, min(60, b["diam_deg"] / span * 400)) if b["kind"] in ("sun", "moon") else 9)
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", text=txt, textposition="top center",
                             marker=dict(color=cols, size=sizes, line=dict(color="#333", width=1)), showlegend=False,
                             hovertemplate="%{text}: %{x:+.2f}°, %{y:+.2f}°<extra></extra>"))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="#0b1a33",
                      title=i18n.tr("Intorno al puntamento") + f" (±{span:.0f}°)",
                      xaxis=dict(range=[-span, span], title="ΔAZ·cos EL (°)", zeroline=False, showgrid=False),
                      yaxis=dict(range=[-span, span], title="ΔEL (°)", scaleanchor="x", zeroline=False, showgrid=False),
                      legend=dict(orientation="h", y=-0.2))
    return i18n.translate_plotly(fig)


def tab(D):
    stn = D.station()
    if not stn.get("lat"):
        st.info("Inserisci nominativo e locator nella scheda Stazione: la volta celeste parte dalla tua posizione.")
        return
    lat, lon, h = float(stn["lat"]), float(stn["lon"]), float(stn.get("height_m") or 0.0)
    st.markdown("### 🌌 Volta celeste")
    st.caption("Il cielo visto dalla tua stazione: azimut in orizzontale, elevazione in verticale. I colori sono il "
               "rumore del cielo dovuto all'atmosfera alla banda scelta (alle microonde è quasi tutto lì, più forte "
               "in basso). Sopra: Sole, Luna, i pianeti e le radiosorgenti più forti. Sotto: chi è vicino al fascio "
               "quando punti la Luna o il Sole, e quanti kelvin aggiunge.")
    c = st.columns([1, 1, 2])
    bands = {k: f for k, f in moon.BANDS}
    bk = c[0].radio("Banda", list(bands), format_func=band_label, horizontal=True, key="sd_band")
    f = bands[bk]
    target = c[1].radio("Punto verso", ["Luna", "Sole"], horizontal=True, key="sd_tgt",
                        format_func=lambda k: f"{ICON[k]} " + i18n.tr(k))
    hours = c[2].slider("Fra quante ore", 0, 48, 0, key="sd_h", help="0 = adesso")
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=hours)
    su, su_assumed = _setup(D, f)
    wx, wx_assumed = _weather()
    sfu = _st.session_state.get("em_flux")
    D_m, eta, taper = float(su["D_m"]), float(su.get("eta_ap") or 0.65), float(su.get("edge_taper_db") or 12.0)
    tsys = su.get("feedlab_tsys")
    info = [f"⌀ {D_m:.2f} m · η {eta * 100:.0f} %", f"{t.astimezone(_local_tz()):%d/%m %H:%M}"]
    assumed = []
    if su_assumed:
        assumed.append(i18n.tr("parabola 2,4 m η 65 % (nessuna configurazione per questa banda)"))
    if wx_assumed:
        assumed.append(i18n.tr("atmosfera standard 15 °C, 60 %"))
    if not sfu:
        assumed.append(i18n.tr("Sole") + f" {skydome.QUIET_SUN_SFU_15G4:.0f} SFU " + i18n.tr("a 15,4 GHz"))
    if not tsys:
        assumed.append("Tsys 80 K")
    st.markdown(" · ".join(info) + ("" if not assumed else f" · <span style='color:{ASSUMED_COLOR}'>" +
                                    i18n.tr("presunto") + ": " + ", ".join(assumed) + "</span>"), unsafe_allow_html=True)
    tsys = float(tsys or 80.0)

    bl = skydome.bodies(t, lat, lon, h, f)
    res = skydome.noise_when_pointing(target, t, lat, lon, h, f, D_m, eta, taper, sfu, bl=bl)
    tg = res["target"]
    from emelab import astro
    trk = astro.track(t, 24.0, 10.0, lat, lon, h)
    tracks = {"Luna": [(s.t, s.moon.az, s.moon.el) for s in trk], "Sole": [(s.t, s.sun.az, s.sun.el) for s in trk]}
    gal = skydome.radec_to_azel(skydome.galactic_plane(), t, lat, lon)
    ecl = skydome.radec_to_azel(skydome.ecliptic(t), t, lat, lon)
    hz = openems_local.load_settings().get("horizon") or None
    st.plotly_chart(_dome(bl, f, wx, tracks, hz, tg, res["hpbw"], gal, ecl), width="stretch", key="sd_dome")

    tot = sum(r["dt_k"] for r in res["rows"])
    t_atm = _t_atm(f, wx, tg["el"])
    m = st.columns(4)
    m[0].metric(f"{ICON[target]} " + i18n.tr(target), f"AZ {tg['az']:.1f}° · EL {tg['el']:.1f}°")
    m[1].metric("Fascio a −3 dB", f"{res['hpbw']:.2f}°", f"G {res['gmax_dbi']:.1f} dBi", delta_color="off")
    m[2].metric("Rumore dagli altri corpi", f"{tot:.2f} K", f"{10 * math.log10((tsys + tot) / tsys):+.2f} dB " +
                i18n.tr("su Tsys"), delta_color="inverse" if tot > 1 else "off")
    m[3].metric("Cielo (atmosfera) a quella EL", f"{t_atm:.0f} K", delta_color="off")
    if tg["el"] < 0:
        st.warning(i18n.tr(target) + " " + i18n.tr("è sotto l'orizzonte in quel momento") + f" (EL {tg['el']:.1f}°).")
    worst = res["rows"][0] if res["rows"] else None
    if worst and worst["dt_k"] >= 1:
        st.warning(f"{ICON.get(worst['name'], '')} {i18n.tr(worst['name'])} " + i18n.tr("a") +
                   f" {worst['sep_deg']:.1f}° " + i18n.tr("dal fascio aggiunge") + f" {worst['dt_k']:.1f} K.")
    else:
        st.success(i18n.tr("Nessun corpo rumoroso vicino al fascio: meno di 1 K in tutto."))

    c = st.columns([1, 1])
    span = max(5.0, min(20.0, 12 * res["hpbw"]))
    c[0].plotly_chart(_zoom(res, bl, span), width="stretch", key="sd_zoom")
    rows = [{"Corpo": f"{ICON.get(r['name'], '')} {i18n.tr(r['name'])}", "Distanza (°)": round(r["sep_deg"], 1),
             "In fasci": round(r["sep_hpbw"], 1), "T se puntato (K)": round(r["t_on_axis_k"], 2),
             "Attenuazione (dB)": round(r["rel_db"], 1), "Aggiunge (K)": round(r["dt_k"], 3),
             "EL (°)": round(r["el"], 1)} for r in res["rows"] if not r["hidden"]]
    c[1].dataframe(rows, hide_index=True, width="stretch", height=360)
    st.caption("«T se puntato»: temperatura d'antenna con la parabola puntata proprio su quel corpo. «Attenuazione»: "
               "lobo principale gaussiano, poi l'inviluppo dei lobi laterali ITU-R S.465 (32 − 25 log θ dBi): è un "
               "limite alto, i lobi veri sono quasi sempre più bassi. Alle microonde solo il Sole conta davvero: "
               "radiosorgenti e pianeti danno meno di 1 K a una parabola di 2–3 m.")

    st.markdown("#### 📅 " + i18n.tr("Prossimi 30 giorni") + f": {ICON[target]} " + i18n.tr(target) + " " +
                i18n.tr("vicino a corpi rumorosi"))
    ev = _approaches(t.replace(minute=0).isoformat(), lat, lon, h, f, D_m, eta, taper, target, sfu)
    if not ev:
        st.info("Nessun passaggio vicino con il bersaglio sopra l'orizzonte.")
    else:
        tz = _local_tz()
        st.dataframe([{"Quando": f"{e['t'].astimezone(tz):%d/%m %H:%M}", "Corpo": f"{ICON.get(e['name'], '')} {i18n.tr(e['name'])}",
                       "Distanza min (°)": round(e["sep_deg"], 2), "Aggiunge (K)": round(e["dt_k"], 2),
                       "EL bersaglio (°)": round(e["target_el"], 1)} for e in ev], hide_index=True, width="stretch")
    st.caption(i18n.tr("Sorgenti") + ": Baars et al. 1977 (Cas A, Tau A, Cyg A, Vir A, con il calo secolare); Ori A e "
               "Sgr A indicativi; pianeti de Pater 1990. " + i18n.tr("Idea da YAEC di IC8TEM."))


@_st.cache_data(ttl=3600, show_spinner=False)
def _approaches(t_iso, lat, lon, h, f, D_m, eta, taper, target, sfu):
    return skydome.close_approaches(datetime.fromisoformat(t_iso), 30, lat, lon, h, f, D_m, eta, taper,
                                    step_min=30.0, min_dt_k=0.5, near_deg=2.0, target=target, sun_sfu=sfu)
