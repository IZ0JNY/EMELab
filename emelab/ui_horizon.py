# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🏔️ Horizon tab: the skyline computed from the terrain around the station and around the DX, the Moon path over
it, the minutes of Moon lost behind the mountains, the common windows with both terrains, and a button to use the
terrain as the free horizon of the whole program (Planner, «Chi posso collegare», Moon tab)."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as _st

from emelab import astro, i18n, terrain, wizard
from emelab import settings as openems_local

st = i18n.wrap(_st)
ASSUMED_COLOR = "#e8590c"
TERRAIN_COLOR = "#8d6e63"


def _compass():
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"] if i18n.get_lang() == "en" else \
        ["N", "NE", "E", "SE", "S", "SO", "O", "NO", "N"]


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _hm(t):
    return "—" if t is None else f"{t.astimezone(_local_tz()):%d/%m %H:%M}"


def _compute(lat, lon, agl, max_km):
    try:
        return terrain.cached_horizon(round(lat, 5), round(lon, 5), float(agl), float(max_km)), None
    except Exception as e:                                      # no internet the first time
        return None, str(e)


def _track(lat, lon, h, hours=24.0, step=5.0, body="moon"):
    t0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    t0 -= timedelta(minutes=t0.minute % int(step))               # on the 5 minutes: the hour marks fall on the track
    return [(s.t, getattr(s, body).az, getattr(s, body).el_radio) for s in astro.track(t0, hours, step, lat, lon, h)]


_PEAKS_FAILED: dict = {}          # place → time of the last failed download (retry after 10 minutes, not at every rerun)


def _peaks(hz):
    key = (round(hz["lat"], 3), round(hz["lon"], 3), hz.get("max_km", 60.0))
    if time.time() - _PEAKS_FAILED.get(key, 0) < 600:
        return None
    try:
        return terrain.visible_peaks(hz, terrain.fetch_peaks(*key))
    except Exception:                                           # no internet the first time: the profile without names
        _PEAKS_FAILED[key] = time.time()
        return None


def _mix(c1, c2, k):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * k):02x}" for x, y in zip(a, b))


# height of the obstacle (m) → colour: meadows, woods, bare slopes, rock; snow on the highest peaks
ZONES = ((400, "#7a9a55"), (1000, "#4f7a3a"), (1600, "#7c6a4c"), (2200, "#8e8780"), (9999, "#9a9690"))
HAZE = "#b4c3d4"                    # far away the mountains turn pale blue (aerial perspective)
SNOW_M = 2000.0


def _terrain_colors(hz):
    """One colour per azimuth for the skyline: by the height of the obstacle, paler with distance; and the snow cap
    (degrees) on peaks above SNOW_M in winter-ish style."""
    cols, snow = [], []
    for e, h, d in zip(hz["el"], hz["obs_h_m"], hz["dist_km"]):
        c = next(col for top, col in ZONES if h < top)
        cols.append(_mix(c, HAZE, min(0.65, (d / max(hz.get("max_km", 60.0), 1.0)) * 0.9)))
        snow.append(round(min(max(e, 0) * 0.25, 0.08 * (h - SNOW_M) / 100), 2) if h > SNOW_M and e > 0 else 0.0)
    return cols, snow


def _draw_track(fig, track, group, name, color, mark_color, icon, now_color, now_name):
    """A body over the horizon: its path (above −1°), the local hours on it and where it is now."""
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
        fig.add_trace(go.Scatter(x=[p[1] for p in s], y=[p[2] for p in s], mode="lines", name=name,
                                 line=dict(color=color, width=2), legendgroup=group, showlegend=i == 0,
                                 text=[f"{p[0].astimezone(tz):%H:%M}" for p in s],
                                 hovertemplate=f"{icon} " + "%{text} · AZ %{x:.0f}° · EL %{y:.1f}°<extra></extra>"))
        hours = [p for p in s if p[0].minute == 0]
        fig.add_trace(go.Scatter(x=[p[1] for p in hours], y=[p[2] for p in hours], mode="markers+text",
                                 marker=dict(size=5, color=mark_color), text=[f"{p[0].astimezone(tz):%H}" for p in hours],
                                 textposition="top center", textfont=dict(size=10, color=mark_color), showlegend=False,
                                 hoverinfo="skip"))
    if track and track[0][2] > -1:
        fig.add_trace(go.Scatter(x=[track[0][1]], y=[track[0][2]], mode="markers+text", text=[icon],
                                 textposition="top center", marker=dict(size=14, color=now_color, line=dict(color="#555", width=1)),
                                 name=now_name))


def _plot(hz, track, manual, title, dx_hz=None, height=380, peaks=None, sun_track=None):
    fig = go.Figure()
    az, el = hz["az"] + [360.0], hz["el"] + [hz["el"][0]]
    cols, snow = _terrain_colors(hz)
    a0 = hz["az"]
    fig.add_trace(go.Bar(x=a0, y=hz["el"], width=1.02, marker=dict(color=cols, line=dict(width=0)), showlegend=False,
                         hoverinfo="skip", offset=0))
    for k, a in ((0.66, 0.10), (0.33, 0.12)):                  # darker towards the valley floor: some depth
        fig.add_trace(go.Bar(x=a0, y=[max(e, 0) * k for e in hz["el"]], width=1.02, offset=0, showlegend=False,
                             marker=dict(color=f"rgba(30,40,20,{a})", line=dict(width=0)), hoverinfo="skip"))
    if any(snow):
        fig.add_trace(go.Bar(x=a0, y=snow, base=[e - s for e, s in zip(hz["el"], snow)], width=1.02, offset=0,
                             marker=dict(color="rgba(250,250,252,0.95)", line=dict(width=0)), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=az, y=el, mode="lines", line=dict(color="#4a3b2f", width=1.2),
                             name=i18n.tr("Terreno"),
                             customdata=[[d, h] for d, h in zip(hz["dist_km"] + [hz["dist_km"][0]],
                                                                 hz["obs_h_m"] + [hz["obs_h_m"][0]])],
                             hovertemplate="AZ %{x:.0f}° · EL %{y:.1f}° · %{customdata[0]:.1f} km · "
                                           "%{customdata[1]:.0f} m<extra></extra>"))
    if manual:
        a = list(range(0, 361))
        fig.add_trace(go.Scatter(x=a, y=[min(wizard.el_min(manual, x), 45) for x in a], mode="lines",
                                 line=dict(color="#555", dash="dash", width=1.5),
                                 name=i18n.tr("Orizzonte libero salvato")))
    _draw_track(fig, track, "m", i18n.tr("Luna, prossime 24 ore"), "#9e9e9e", "#757575", "🌙", "#f5f0d0", i18n.tr("Luna adesso"))
    if sun_track:
        _draw_track(fig, sun_track, "s", i18n.tr("Sole, prossime 24 ore"), "#f4a300", "#e08e00", "☀️", "#ffc107",
                    i18n.tr("Sole adesso"))
    if peaks:
        fig.add_trace(go.Scatter(x=[p["az"] for p in peaks], y=[p["el"] for p in peaks], mode="markers",
                                 marker=dict(symbol="triangle-up", size=7, color="#4e342e"), name=i18n.tr("Cime (OpenStreetMap)"),
                                 customdata=[[p["name"], p["ele"], p["dist_km"]] for p in peaks],
                                 hovertemplate="%{customdata[0]} · %{customdata[1]:.0f} m · %{customdata[2]:.1f} km · "
                                               "AZ %{x:.0f}° · EL %{y:.1f}°<extra></extra>"))
        for p in peaks:
            fig.add_annotation(x=p["az"], y=p["el"], text=html.escape(p["name"]), showarrow=False, textangle=-60,
                               xanchor="left", yanchor="bottom", xshift=-2, yshift=4, font=dict(size=9, color="#4e342e"))
    ymax = max(20.0, max(hz["el"]) + (12 if peaks else 6), max((p[2] for p in track + (sun_track or [])), default=0) + 2 if track else 0)
    fig.update_layout(title=title, height=height, margin=dict(l=10, r=10, t=40, b=10), bargap=0, barmode="overlay",
                      xaxis=dict(range=[0, 360], tickvals=list(range(0, 361, 15)),
                                 ticktext=[f"{a}°" for a in range(0, 361, 15)], title="Azimut (°)",
                                 showgrid=True, gridcolor="rgba(0,0,0,0.12)", tickfont=dict(size=10)),
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
    lat, lon, h = float(stn["lat"]), float(stn["lon"]), float(stn.get("height_m") or 0.0)
    cfg = openems_local.load_settings()
    st.markdown("### 🏔️ Orizzonte dal terreno")
    st.caption("Lo skyline delle montagne e delle colline intorno a te, calcolato dal modello del terreno Copernicus "
               "(≈30 m vicino, ≈90 m lontano) con la curvatura terrestre e la rifrazione radio standard (k = 4/3), con i "
               "nomi delle cime di OpenStreetMap. Case, alberi e il tuo tetto non ci sono: quelli restano da aggiungere a "
               "mano nell'orizzonte libero. Il terreno si scarica una volta sola (circa 30 MB) e resta nella cartella di EMELab.")
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
    S = _st.session_state
    if not terrain.is_cached(round(lat, 5), round(lon, 5), float(agl), float(max_km)) and not S.get("hz_go"):
        st.button("🏔️ Scarica il terreno e calcola l'orizzonte", key="hz_go_btn", type="primary",
                  on_click=lambda: S.__setitem__("hz_go", True))
        return
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
    peaks = _peaks(hz)
    sun = _track(lat, lon, h, body="sun")
    st.plotly_chart(_plot(hz, track, manual, i18n.tr("Il tuo orizzonte, la Luna e il Sole (ore locali)"), peaks=peaks,
                          sun_track=sun),
                    width="stretch", key="hz_me")
    sp = next((p for p in terrain.moon_blocked(sun, hz)["passes"] if p["clear_from"]), None)
    if sp:
        head = i18n.tr("Sole: già sopra le montagne") if sp["clear_from"] == sun[0][0] else \
            i18n.tr("Sole: esce dalle montagne") + f" {_hm(sp['clear_from'])}"
        st.caption("☀️ " + head + ", " +
                   i18n.tr("entra dietro le montagne") + f" {_hm(sp['clear_to'])} · " +
                   i18n.tr("minuti persi") + f" {sp['minutes_blocked']:.0f}")
    if peaks is None:
        st.caption("Nomi delle montagne non disponibili: servono internet la prima volta (OpenStreetMap).")

    with st.expander("⛰️ Gli ostacoli principali, settore per settore"):
        rows = []
        for s0 in range(0, 360, 30):
            idx = [i for i, a in enumerate(hz["az"]) if s0 <= a < s0 + 30]
            i = max(idx, key=lambda k: hz["el"][k])
            rows.append({"Settore": f"{s0:03d}–{s0 + 30:03d}°", "Azimut (°)": round(hz["az"][i]),
                         "Elevazione (°)": hz["el"][i], "Distanza (km)": hz["dist_km"][i], "Quota (m)": int(hz["obs_h_m"][i]),
                         "Locator": astro.latlon_to_locator(hz["obs_lat"][i], hz["obs_lon"][i], 8)})
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(i18n.tr("Terreno") + ": " + i18n.tr(hz.get("source") or terrain.SOURCE) + ". " + i18n.tr("Cime") + ": " +
                   terrain.PEAKS_SOURCE + ". " + i18n.tr("Idea da YAEC di IC8TEM."))

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
    st.plotly_chart(_plot(hzd, trd, None, f"{pick or loc_dx}: " + i18n.tr("orizzonte e Luna (ore locali tue)"),
                          peaks=_peaks(hzd)),
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
