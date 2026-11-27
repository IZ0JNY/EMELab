# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🏔️ Horizon tab: the skyline computed from the terrain around the station and around the DX, the Moon path over
it, the minutes of Moon lost behind the mountains, the common windows with both terrains, and a button to use the
terrain as the free horizon of the whole program (Planner, «Chi posso collegare», Moon tab)."""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as _st

from emelab import astro, i18n, terrain, wizard
from emelab import settings as openems_local

st = i18n.wrap(_st)
ASSUMED_COLOR = "#e8590c"
TERRAIN_COLOR = "#8d6e63"


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _hm(t):
    return "—" if t is None else f"{t.astimezone(_local_tz()):%d/%m %H:%M}"


def _compute(lat, lon, agl, max_km):
    try:
        return terrain.cached_horizon(round(lat, 5), round(lon, 5), float(agl), float(max_km)), None
    except Exception as e:                                      # no internet the first time
        return None, str(e)


def _track(lat, lon, h, hours=24.0, step=5.0):
    t0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    t0 -= timedelta(minutes=t0.minute % int(step))               # on the 5 minutes: the hour marks fall on the track
    return [(s.t, s.moon.az, s.moon.el_radio) for s in astro.track(t0, hours, step, lat, lon, h)]


def _plot(hz, track, manual, title, dx_hz=None, height=380):
    fig = go.Figure()
    az, el = hz["az"] + [360.0], hz["el"] + [hz["el"][0]]
    fig.add_trace(go.Scatter(x=az, y=el, fill="tozeroy", mode="lines", line=dict(color=TERRAIN_COLOR, width=1),
                             fillcolor="rgba(141,110,99,0.55)", name=i18n.tr("Terreno"),
                             customdata=[[d, h] for d, h in zip(hz["dist_km"] + [hz["dist_km"][0]],
                                                                 hz["obs_h_m"] + [hz["obs_h_m"][0]])],
                             hovertemplate="AZ %{x:.0f}° · EL %{y:.1f}° · %{customdata[0]:.1f} km · "
                                           "%{customdata[1]:.0f} m<extra></extra>"))
    if manual:
        a = list(range(0, 361))
        fig.add_trace(go.Scatter(x=a, y=[min(wizard.el_min(manual, x), 45) for x in a], mode="lines",
                                 line=dict(color="#555", dash="dash", width=1.5),
                                 name=i18n.tr("Orizzonte libero salvato")))
    segs, cur = [], []
    for p in track:
        if p[2] >= -1:
            cur.append(p)
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    tz = _local_tz()
    for i, s in enumerate(segs):
        fig.add_trace(go.Scatter(x=[p[1] for p in s], y=[p[2] for p in s], mode="lines", name=i18n.tr("Luna, prossime 24 ore"),
                                 line=dict(color="#9e9e9e", width=2), legendgroup="m", showlegend=i == 0,
                                 text=[f"{p[0].astimezone(tz):%H:%M}" for p in s],
                                 hovertemplate="%{text} · AZ %{x:.0f}° · EL %{y:.1f}°<extra></extra>"))
        hours = [p for p in s if p[0].minute == 0]
        fig.add_trace(go.Scatter(x=[p[1] for p in hours], y=[p[2] for p in hours], mode="markers+text",
                                 marker=dict(size=5, color="#757575"), text=[f"{p[0].astimezone(tz):%H}" for p in hours],
                                 textposition="top center", textfont=dict(size=10), showlegend=False, hoverinfo="skip"))
    if track and track[0][2] > -1:
        fig.add_trace(go.Scatter(x=[track[0][1]], y=[track[0][2]], mode="markers+text", text=["🌙"],
                                 textposition="top center", marker=dict(size=14, color="#f5f0d0", line=dict(color="#555", width=1)),
                                 name=i18n.tr("Luna adesso")))
    ymax = max(20.0, max(hz["el"]) + 6, max((p[2] for p in track), default=0) + 2 if track else 0)
    fig.update_layout(title=title, height=height, margin=dict(l=10, r=10, t=40, b=10),
                      xaxis=dict(range=[0, 360], tickvals=list(range(0, 361, 45)),
                                 ticktext=["N", "NE", "E", "SE", "S", "SO", "O", "NO", "N"], title="Azimut"),
                      yaxis=dict(range=[min(0.0, min(hz["el"]) - 1), min(ymax, 90)], title="Elevazione (°)"),
                      legend=dict(orientation="h", y=-0.25))
    return i18n.translate_plotly(fig)


def _windows(trA, hzA, manual, trB, hzB, step_min):
    """Common windows: Moon over both terrains (and over your saved free horizon), and without terrain (EL > 0)."""
    out, cur, base = [], None, 0
    for (t, a1, e1), (_, a2, e2) in zip(trA, trB):
        both_up = e1 > 0 and e2 > 0
        base += step_min if both_up else 0
        ok = both_up and e1 >= terrain.el_at(hzA, a1) and e2 >= terrain.el_at(hzB, a2) and \
            (not manual or e1 >= wizard.el_min(manual, a1))
        if ok and cur is None:
            cur = {"start": t, "end": t, "my_el": e1, "dx_el": e2}
        elif ok:
            cur.update(end=t, my_el=max(cur["my_el"], e1), dx_el=max(cur["dx_el"], e2))
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return out, base


def tab(D):
    stn = D.station()
    if not stn.get("lat"):
        st.info("Inserisci nominativo e locator nella scheda Stazione: l'orizzonte parte dalla tua posizione.")
        return
    S = _st.session_state
    lat, lon, h = float(stn["lat"]), float(stn["lon"]), float(stn.get("height_m") or 0.0)
    cfg = openems_local.load_settings()
    st.markdown("### 🏔️ Orizzonte dal terreno")
    st.caption("Lo skyline delle montagne e delle colline intorno a te, calcolato dal modello del terreno (SRTM, ≈30 m) "
               "con la curvatura terrestre e la rifrazione radio standard (k = 4/3). Case, alberi e il tuo tetto non ci "
               "sono: quelli restano da aggiungere a mano nell'orizzonte libero. Le tessere del terreno si scaricano una "
               "volta sola (circa 3 MB) e restano nella cartella di EMELab.")
    c = st.columns([1, 1, 2])
    agl = c[0].number_input("Altezza della parabola dal suolo (m)", 0.0, 100.0, float(cfg.get("terrain_agl_m", 3.0)), 0.5,
                            key="hz_agl", help="il centro della parabola, sopra il terreno sotto di te")
    max_km = c[1].selectbox("Fino a (km)", [15, 30, 60], index=2, key="hz_km",
                            help="oltre i 60 km anche una montagna di 2000 m resta sotto 1°")
    loc = (stn.get("locator") or "").upper()
    c[2].markdown(f"**{html.escape(stn.get('callsign') or '')} {html.escape(loc)}** · {lat:.5f}, {lon:.5f}" +
                  ("" if len(loc) >= 8 else f"<br><span style='color:{ASSUMED_COLOR}'>" +
                   i18n.tr("Per gli ostacoli vicini serve la posizione precisa: lat/lon dal GPS o un locator di 8–10 caratteri.") +
                   "</span>"), unsafe_allow_html=True)
    if agl != cfg.get("terrain_agl_m", 3.0):
        openems_local.save_settings(terrain_agl_m=agl)
    with st.spinner(i18n.tr("Calcolo dell'orizzonte dal terreno…")):
        hz, err = _compute(lat, lon, agl, max_km)
    if hz is None:
        st.error(i18n.tr("Non riesco a scaricare il terreno (serve internet solo la prima volta)") + f": {err}")
        return
    manual = cfg.get("horizon") or None
    track = _track(lat, lon, h)
    bl = terrain.moon_blocked(track, hz)
    i_max = max(range(len(hz["el"])), key=lambda i: hz["el"][i])
    m = st.columns(4)
    m[0].metric("Ostacolo più alto", f"{hz['el'][i_max]:.1f}°",
                f"AZ {hz['az'][i_max]:.0f}° · {hz['dist_km'][i_max]:.1f} km · {hz['obs_h_m'][i_max]:.0f} m", delta_color="off")
    m[1].metric("Quota del terreno qui", f"{hz['ground_m']:.0f} m",
                (i18n.tr("stazione") + f" {h:.0f} m") if h else None, delta_color="off")
    m[2].metric("Luna sopra 0° (24 h)", f"{bl['minutes_up'] / 60:.1f} h")
    nxt = bl["passes"][0] if bl["passes"] else None
    m[3].metric("Persa dietro le montagne", f"{bl['minutes_blocked']:.0f} min",
                (i18n.tr("questo passaggio: libera") + f" {_hm(nxt['clear_from'])} → {_hm(nxt['clear_to'])}")
                if nxt and nxt["clear_from"] else None, delta_color="off")
    if bl["passes"]:
        st.dataframe([{"Sorge": _hm(p["rise"]) if p["rise"] > track[0][0] else i18n.tr("già alta"), "Esce dalle montagne": (_hm(p["clear_from"]) if p["clear_from"] != track[0][0] else i18n.tr("già fuori")),
                       "Entra dietro le montagne": _hm(p["clear_to"]), "Tramonta": _hm(p["set"]),
                       "Minuti persi": int(p["minutes_blocked"])} for p in bl["passes"]], hide_index=True, width="stretch")
    st.plotly_chart(_plot(hz, track, manual, i18n.tr("Il tuo orizzonte e la Luna (ore locali)")), width="stretch", key="hz_me")

    with st.expander("⛰️ Gli ostacoli principali, settore per settore"):
        rows = []
        for s0 in range(0, 360, 30):
            idx = [i for i, a in enumerate(hz["az"]) if s0 <= a < s0 + 30]
            i = max(idx, key=lambda k: hz["el"][k])
            rows.append({"Settore": f"{s0:03d}–{s0 + 30:03d}°", "Azimut (°)": round(hz["az"][i]),
                         "Elevazione (°)": hz["el"][i], "Distanza (km)": hz["dist_km"][i], "Quota (m)": int(hz["obs_h_m"][i]),
                         "Locator": astro.latlon_to_locator(hz["obs_lat"][i], hz["obs_lon"][i], 8)})
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(i18n.tr("Terreno") + ": " + terrain.SOURCE + ". " + i18n.tr("Idea da YAEC di IC8TEM."))

    with st.expander("💾 Usa il terreno come orizzonte libero di EMELab"):
        st.caption("L'orizzonte libero lo usano il Pianificatore, «Chi posso collegare», la scheda Luna e l'Assistente. "
                   "«Unisci» tiene il più alto fra il terreno e quello che hai messo a mano (case, alberi).")
        c = st.columns(3)
        width = c[0].selectbox("Settori di", [1, 2, 5, 10], index=2, format_func=lambda x: f"{x}°", key="hz_w")
        floor = c[1].number_input("Elevazione minima della parabola (°)", 0.0, 30.0, 0.0, 0.5, key="hz_floor",
                                  help="se la tua montatura non scende sotto un certo angolo")
        margin = c[2].number_input("Margine sopra il terreno (°)", 0.0, 5.0, 0.5, 0.1, key="hz_margin",
                                   help="mezzo fascio a 10 GHz con 2,4 m è circa 0,4°: sotto, metà del fascio tocca il terreno")
        sec = terrain.to_sectors(hz, width, floor, margin)
        merged = terrain.merge_with(sec, manual)
        b = st.columns(2)
        if b[0].button(f"🏔️ Sostituisci con il terreno ({len(sec)} settori)", key="hz_use"):
            openems_local.save_settings(horizon=sec, horizon_source="terrain")
            st.success("Orizzonte libero salvato dal terreno.")
        if b[1].button(f"🔗 Unisci con il mio ({len(merged)} settori)", key="hz_merge", disabled=not manual):
            openems_local.save_settings(horizon=merged, horizon_source="terrain+manual")
            st.success("Orizzonte libero salvato: il più alto fra terreno e il tuo.")

    st.markdown("#### 🤝 L'orizzonte del DX e le finestre comuni")
    c = st.columns([2, 1])
    q = c[0].text_input("Nominativo o locator del DX", key="hz_dx", max_chars=12,
                        help="un nominativo delle Stazioni EME (con locator di almeno 6 caratteri) o un locator").strip().upper()
    dx_agl = c[1].number_input("Antenna DX dal suolo (m)", 0.0, 100.0, 5.0, 0.5, key="hz_dx_agl", help="presunto")
    rec = D.station_of(q) if q else None
    loc_dx = (rec.get("locator") or "").upper() if rec else (q if q[:2].isalpha() and q[2:4].isdigit() else "")
    pick = q if rec else ""
    if q and not loc_dx:
        st.warning(i18n.tr("Nominativo senza locator nelle Stazioni EME") + f": {q}")
        return
    if not loc_dx:
        st.caption("Scegli una stazione: vedrai il suo orizzonte e le finestre comuni con i due terreni.")
        return
    if len(loc_dx) < 6:
        st.warning("Serve un locator di almeno 6 caratteri.")
        return
    try:
        dlat, dlon = astro.locator_to_latlon(loc_dx)
    except Exception:
        st.warning("Locator non valido.")
        return
    with st.spinner(i18n.tr("Calcolo dell'orizzonte del DX…")):
        hzd, err = _compute(dlat, dlon, dx_agl, max_km)
    if hzd is None:
        st.error(i18n.tr("Non riesco a scaricare il terreno del DX") + f": {err}")
        return
    trd = _track(dlat, dlon, hzd["ground_m"])
    st.markdown(f"<span style='color:{ASSUMED_COLOR}'>" + i18n.tr("Posizione del DX dal centro del locator") +
                f" {html.escape(loc_dx)}" + (" (" + i18n.tr("±2 km: gli ostacoli vicini sono approssimati") + ")" if len(loc_dx) < 8 else "") +
                "</span>", unsafe_allow_html=True)
    st.plotly_chart(_plot(hzd, trd, None, f"{pick or loc_dx}: " + i18n.tr("orizzonte e Luna (ore locali tue)")),
                    width="stretch", key="hz_dx_plot")
    win, base = _windows(track, hz, manual, trd, hzd, 5.0)
    tot = sum((w["end"] - w["start"]).total_seconds() / 60 + 5 for w in win)
    st.metric("Finestra comune nelle prossime 24 ore", f"{tot / 60:.1f} h",
              f"{(tot - base):+.0f} min " + i18n.tr("rispetto a «Luna sopra 0° per tutti e due»"), delta_color="off")
    if win:
        st.dataframe([{"Inizio": _hm(w["start"]), "Fine": _hm(w["end"] + timedelta(minutes=5)),
                       "Durata (min)": int((w["end"] - w["start"]).total_seconds() / 60 + 5),
                       "EL max tua (°)": round(w["my_el"], 1), "EL max DX (°)": round(w["dx_el"], 1)} for w in win],
                     hide_index=True, width="stretch")
    else:
        st.info("Nelle prossime 24 ore la Luna non è mai sopra i due orizzonti insieme.")
