# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🌙 Moon tab: the Moon seen from the station right now, refreshed every 30 seconds. Position, distance and path loss,
own-echo Doppler and spread per band, libration, phase, RA/Dec and declination trend, rise/transit/set (local time and
UTC), sky behind the Moon, degradation against the ideal case, next perigee/apogee, sky plot with the free horizon."""
from __future__ import annotations

import functools
import html
import math
from datetime import datetime, timedelta, timezone

import plotly.graph_objects as go
import streamlit as _st

from emelab import i18n, logbook as lb, moon, planner
from emelab import settings as openems_local
from emelab.stations import band_label

st = i18n.wrap(_st)
ASSUMED_COLOR = "#e8590c"
REFRESH_S = 30
PHASE_EVENT = {"new": "🌑 Luna nuova", "first": "🌓 Primo quarto", "full": "🌕 Luna piena", "last": "🌗 Ultimo quarto"}


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _t(t: datetime | None, day: bool = False) -> str:
    """«18:42 (17:42 UTC)», local time of this PC first."""
    if t is None:
        return "—"
    lt = t.astimezone(_local_tz())
    f = "%d/%m %H:%M" if day else "%H:%M"
    if lt.utcoffset() == timedelta(0):
        return f"{lt:{f}} UTC"
    return f"{lt:{f}} ({t.astimezone(timezone.utc):%H:%M} UTC)"


def _tz_name() -> str:
    return datetime.now().astimezone().tzname() or "locale"


def _horizon():
    """The free-horizon profile saved by the user (🧭 Assistant), or None if never saved."""
    try:
        hz = openems_local.load_settings().get("horizon")
    except Exception:
        hz = None
    return [dict(r) for r in hz] if hz else None


def _setups_by_band(D) -> dict:
    out = {}
    for s in D.setups():
        f = float(s.get("band_ghz") or 0)
        for key, fb in moon.BANDS:
            if abs(f - fb) < 1.5 and key not in out and s.get("D_m"):
                out[key] = s
    return out


def _weather_now():
    """Current hour of the Open-Meteo forecast the 🧭 Assistant already downloaded (None: standard atmosphere)."""
    fc = _st.session_state.get("wz_fc") or []
    h = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    w = next((x for x in fc if x.get("utc") == h), None)
    if w and w.get("t_c") is not None and w.get("rh") is not None:
        return {"t_c": w["t_c"], "rh": w["rh"], "p_hpa": w.get("p_hpa")}
    return None


@functools.lru_cache(maxsize=8)
def _day(day_start_iso: str, lat: float, lon: float, h: float, hz_key: tuple):
    hz = [{"az_da": a, "az_a": b, "el_min": e} for a, b, e in hz_key] or None
    return moon.day_events(datetime.fromisoformat(day_start_iso), lat, lon, h, hz, hours=48.0, step_min=10.0)


@functools.lru_cache(maxsize=4)
def _month(hour_iso: str):
    t = datetime.fromisoformat(hour_iso)
    dec = moon.declination_series(t - timedelta(days=3), 33.0, 3.0)
    per = [p for p in planner.perigees(t, 40) if p[0] > t][:2]
    return dec, moon.declination_extremes(dec), per, moon.next_phases(t, 32.0)


def _sky_plot(track, now_d, hz):
    """Polar sky plot: centre = zenith, rim = horizon; Moon track of the day, Moon and Sun now, obstacles in brown."""
    fig = go.Figure()
    if hz:
        from emelab import wizard
        az = list(range(0, 361, 2))
        em = [min(wizard.el_min(hz, a), 90.0) for a in az]
        fig.add_trace(go.Barpolar(r=em, base=[90 - e for e in em], theta=az, width=2, marker_color="#8d6e63",
                                  marker_line_width=0, opacity=0.55, name=i18n.tr("Ostacoli (orizzonte libero)"),
                                  hoverinfo="skip"))
    segs, cur = [], []
    for p in track:                              # one line per pass: nothing drawn across the hidden part
        if p[2] >= -2:
            cur.append(p)
        elif cur:
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    tz = _local_tz()
    for i, up in enumerate(segs):
        fig.add_trace(go.Scatterpolar(r=[90 - e for _, _, e in up], theta=[a for _, a, _ in up], mode="lines+markers",
                                      marker=dict(size=4), line=dict(color="#9e9e9e"), name=i18n.tr("Luna oggi"),
                                      legendgroup="track", showlegend=i == 0,
                                      text=[f"{t.astimezone(tz):%H:%M}" for t, _, _ in up],
                                      hovertemplate="%{text} · AZ %{theta:.0f}° · EL %{customdata:.1f}°<extra></extra>",
                                      customdata=[e for _, _, e in up]))
    if now_d["el_radio"] > -2:
        fig.add_trace(go.Scatterpolar(r=[90 - now_d["el_radio"]], theta=[now_d["az"]], mode="markers+text",
                                      marker=dict(size=18, color="#f5f0d0", line=dict(color="#555", width=1)),
                                      text=["🌙"], textposition="top center", name=i18n.tr("Luna adesso")))
    if now_d["sun_el"] > -2:
        fig.add_trace(go.Scatterpolar(r=[90 - now_d["sun_el"]], theta=[now_d["sun_az"]], mode="markers",
                                      marker=dict(size=16, color="#ffb300"), name=i18n.tr("Sole adesso")))
    fig.update_layout(polar=dict(angularaxis=dict(direction="clockwise", rotation=90, tickvals=[0, 90, 180, 270],
                                                  ticktext=["N", "E", "S", "W" if i18n.get_lang() == "en" else "O"]),
                                 radialaxis=dict(range=[0, 92], tickvals=[0, 30, 60, 90], ticktext=["90°", "60°", "30°", "0°"])),
                      height=420, margin=dict(l=30, r=30, t=30, b=30), legend=dict(orientation="h", y=-0.08))
    return fig


def _dec_plot(dec, ext, t_now):
    fig = go.Figure(go.Scatter(x=[t for t, _ in dec], y=[d for _, d in dec], mode="lines", line=dict(color="#9e9e9e"),
                               name=i18n.tr("Declinazione")))
    fig.add_vline(x=t_now, line_dash="dot", line_color="#e8590c")
    for t, d, k in ext:
        fig.add_annotation(x=t, y=d, text=f"{d:+.1f}°", showarrow=False, yshift=10 if k == "max" else -10)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), yaxis_title=i18n.tr("Declinazione (°)"),
                      showlegend=False)
    return fig


def _band_header(key: str) -> str:
    return (f"<span style='color:{lb.BAND_COLORS.get(key, '#777')};font-weight:700;font-size:1.15em'>■ "
            f"{html.escape(band_label(key))}</span>")


def _fmt(v, f):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f.format(v)


def tab(D):
    stn = D.station()
    if not stn.get("lat"):
        st.info("Inserisci nominativo e locator nella scheda Stazione: la scheda Luna parte dalla tua posizione.")
        return
    _live(D, stn)


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


@_frag(REFRESH_S)
def _live(D, stn):
    lat, lon, h = float(stn["lat"]), float(stn["lon"]), float(stn.get("height_m") or 0.0)
    t = datetime.now(timezone.utc).replace(microsecond=0)
    wx = _weather_now()
    sets = _setups_by_band(D)
    n = moon.now(t, lat, lon, h, wx, sets)
    hz = _horizon()
    tz = _local_tz()
    lt = t.astimezone(tz)
    st.markdown(f"### 🌙 {i18n.tr('La Luna adesso')} · {lt:%H:%M:%S} {_tz_name()}" +
                (f" ({t:%H:%M:%S} UTC)" if lt.utcoffset() != timedelta(0) else ""))
    st.caption(i18n.tr("Vista da") + f" {stn.get('callsign') or ''} {stn.get('locator') or ''} · " +
               i18n.tr("si aggiorna da sola ogni 30 secondi"))
    if n["el_radio"] < 0:
        st.warning(i18n.tr("La Luna è sotto l'orizzonte") + f" (EL {n['el']:.1f}°).")

    ph = n["phase"]
    c = st.columns(4)
    c[0].metric("Azimut", f"{n['az']:.2f}°", help="dal nord in senso orario, topocentrico (parallasse inclusa)")
    c[1].metric("Elevazione", f"{n['el_radio']:.2f}°",
                help=i18n.tr("con la rifrazione radio (ITU-R P.834); geometrica") + f" {n['el']:.2f}°")
    c[2].metric("Distanza", f"{n['dist_km']:,.0f} km",
                help=i18n.tr("dalla tua stazione; dal centro della Terra") + f" {n['geo_km']:,.0f} km, "
                + f"{n['bands']['10G']['perigee_db']:+.2f} dB " + i18n.tr("rispetto al perigeo") + " (356 400 km)")
    c[3].metric("Angolo Sole–Luna", f"{n['sun_moon_deg']:.1f}°",
                help="sotto 10–15° il Sole entra nel fascio o nei lobi laterali e alza il rumore")
    c = st.columns(4)
    c[0].metric("Fase", ph["name"], help=i18n.tr("illuminata al") + f" {100 * ph['illum']:.0f} %, " +
                i18n.tr("elongazione") + f" {ph['elongation']:.0f}°")
    c[1].metric("Età della Luna", f"{ph['age_days']:.1f} " + i18n.tr("giorni"),
                help="giorni dalla Luna nuova (stima dall'elongazione)")
    c[2].metric("Ascensione retta", moon.ra_hms(n["ra"]), help="geocentrica, J2000")
    c[3].metric("Declinazione", moon.dec_dms(n["dec"]), delta=f"{n['dec_rate_deg_h'] * 24:+.1f}°/" + i18n.tr("giorno"),
                delta_color="off", help="geocentrica, J2000. Declinazione alta (nord) = Luna alta e a lungo sopra l'orizzonte in Europa")
    c = st.columns(4)
    c[0].metric("Diametro apparente", f"{n['diam_deg'] * 60:.2f}′")
    c[1].metric("Librazione (long.)", f"{n['libration_lon']:+.2f}°",
                help="librazione ottica geocentrica (Meeus): + = bordo est verso di noi")
    c[2].metric("Librazione (lat.)", f"{n['libration_lat']:+.2f}°", help="+ = si vede la zona del polo nord lunare")
    c[3].metric("Velocità di librazione", f"{n['libration_rate_deg_min'] * 60:.2f}°/h",
                help="rotazione apparente della Luna vista da te: è lei che allarga le eco (spread)")

    st.markdown("#### " + i18n.tr("📡 Per banda (eco proprie)"))
    cols = st.columns(len(moon.BANDS))
    for col, (key, f) in zip(cols, moon.BANDS):
        b = n["bands"][key]
        with col:
            st.markdown(_band_header(key), unsafe_allow_html=True)
            st.metric("Doppler eco", f"{b['doppler_hz']:+,.0f} Hz", delta=f"{b['doppler_rate_hz_min']:+.1f} Hz/min",
                      delta_color="off", help="spostamento della tua eco (andata e ritorno) e quanto cambia al minuto")
            cc = st.columns(2)
            cc[0].metric("Spread", f"{b['spread_hz']:.0f} Hz",
                         help="allargamento delle eco da bordo a bordo per la librazione")
            cc[1].metric("Perdita di tratta", f"{b['path_loss_db']:.2f} dB",
                         help=i18n.tr("perdita isotropa di andata e ritorno via Luna") + f"; {b['perigee_db']:+.2f} dB " +
                         i18n.tr("rispetto al perigeo"))
            cc = st.columns(2)
            cc[0].metric("Cielo verso la Luna", _fmt(b["t_sky"], "{:.0f} K"),
                         help=i18n.tr("atmosfera alla tua elevazione più fondo cosmico; attenuazione") +
                         f" {_fmt(b['a_slant_db'], '{:.2f}')} dB " + i18n.tr("per tratta") + ". " +
                         i18n.tr("Fondo galattico dietro la Luna") + f" ≈ {n['t_gal_10g']:.2f} K " + i18n.tr("a 10 GHz") +
                         f" (b = {n['gal_b']:+.0f}°): " + i18n.tr("trascurabile da 10 GHz in su"))
            cc[1].metric("Luna (Tb)", f"{b['t_moon']:.0f} K",
                         help="emissione termica della Luna nel fascio: cambia con la fase e con la banda")
            dg = b["dgrd"]
            st.metric("Degradazione", _fmt(dg["total"], "{:.1f} dB"),
                         help=i18n.tr("rispetto al caso ideale: Luna al perigeo e allo zenit, stesso meteo e ricevitore.") +
                         " " + i18n.tr("Distanza") + f" {dg['dist']:+.2f} dB · " + i18n.tr("atmosfera (andata e ritorno)") +
                         f" {_fmt(dg['atm'], '{:+.2f}')} dB · " + i18n.tr("rumore di cielo") + f" {_fmt(dg['noise'], '{:+.2f}')} dB")
            if b["setup_assumed"]:
                st.markdown(f"<span style='color:{ASSUMED_COLOR};font-size:0.85em'>" +
                            html.escape(i18n.tr("ricevitore presunto (NF 1 dB): nessuna configurazione per questa banda")) +
                            "</span>", unsafe_allow_html=True)
    if n["wx_assumed"]:
        st.markdown(f"<span style='color:{ASSUMED_COLOR}'>" + html.escape(
            i18n.tr("Meteo presunto: atmosfera standard (15 °C, umidità 60 %). Apri l'Assistente per usare le previsioni di oggi.")) +
            "</span>", unsafe_allow_html=True)
    else:
        w = n["wx"]
        st.caption(i18n.tr("Meteo da te adesso") + f": {w['t_c']:.0f} °C, " + i18n.tr("umidità") + f" {w['rh']:.0f} % (Open-Meteo)")

    # ---------------------------------------------------------------- today and the next days
    lt = t.astimezone(tz)
    day0 = lt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    hz_key = tuple((float(r["az_da"]), float(r["az_a"]), float(r["el_min"])) for r in (hz or []))
    ev = _day(day0.isoformat(), round(lat, 5), round(lon, 5), round(h, 1), hz_key)
    dec, ext, per, phases = _month(t.replace(minute=0, second=0).isoformat())
    c = st.columns([3, 2])
    with c[0]:
        st.markdown("#### " + i18n.tr("🕒 Oggi") + f" ({lt:%d/%m}, " + i18n.tr("ora locale") + f" {_tz_name()})")
        day1 = day0 + timedelta(days=1)

        def pick(ts):
            """Today's event, or the next one (with its date) when the Moon does not do it today."""
            x = next((x for x in ts if day0 <= (x[0] if isinstance(x, tuple) else x) < day1), None)
            if x is None:
                x = next((x for x in ts if (x[0] if isinstance(x, tuple) else x) >= t), None)
                return x, True
            return x, False

        (r, rd), (tr_, td), (s_, sd) = pick(ev["rises"]), pick(ev["transits"]), pick(ev["sets"])
        far = datetime.max.replace(tzinfo=timezone.utc)
        rows = sorted([(r or far, "🌅 " + i18n.tr("Sorge"), _t(r, rd)),
                       (tr_[0] if tr_ else far, "⬆️ " + i18n.tr("Culmina"),
                        (_t(tr_[0], td) + f" · EL {tr_[1]:.1f}°") if tr_ else "—"),
                       (s_ or far, "🌇 " + i18n.tr("Tramonta"), _t(s_, sd))], key=lambda x: x[0])
        rows = [(a, b) for _, a, b in rows]
        if hz:
            rows.append(("🏔️ " + i18n.tr("Esce dagli ostacoli"),
                         ", ".join(_t(x) for x in ev["free_from"] if day0 <= x < day1) or "—"))
            rows.append(("🏔️ " + i18n.tr("Entra dietro gli ostacoli"),
                         ", ".join(_t(x) for x in ev["free_to"] if day0 <= x < day1) or "—"))
        st.markdown("\n".join(f"- **{a}:** {b}" for a, b in rows))
        st.caption("Sorge e tramonta con il centro della Luna a 0° di elevazione radio (rifrazione inclusa).")
        st.markdown("#### " + i18n.tr("📅 Prossimi eventi"))
        evs = [(p[0], ("🔻 " + i18n.tr("Perigeo") if p[2] == "perigeo" else "🔺 " + i18n.tr("Apogeo")) + f" · {p[1]:,.0f} km · "
                + f"{40 * math.log10(p[1] / moon.PERIGEE_KM):+.1f} dB") for p in per]
        evs += [(tt, i18n.tr(PHASE_EVENT[k])) for tt, k in phases]
        evs += [(tt, ("⤴️ " + i18n.tr("Declinazione massima") if k == "max" else "⤵️ " + i18n.tr("Declinazione minima"))
                 + f" {d:+.1f}°") for tt, d, k in ext if tt > t]
        evs.sort(key=lambda x: x[0])
        st.markdown("\n".join(f"- **{_t(tt, day=True)}** — {txt}" for tt, txt in evs[:8]))
    with c[1]:
        st.markdown("#### " + i18n.tr("🔭 Cielo di oggi"))
        st.plotly_chart(_sky_plot([p for p in ev["track"] if day0 <= p[0] <= day1], n, hz), width="stretch", key="moon_sky")
        if not hz:
            st.caption("Nessun orizzonte libero salvato: puoi disegnarlo nell'Assistente (🏔️) e qui vedrai gli ostacoli.")
    st.markdown("#### " + i18n.tr("📈 Andamento della declinazione"))
    st.plotly_chart(_dec_plot(dec, ext, t), width="stretch", key="moon_dec")
    st.caption("Con la declinazione alta la Luna resta più ore sopra l'orizzonte e sale di più; vicino al perigeo "
               "l'eco è più forte (fino a 2.2 dB rispetto all'apogeo).")
    _map_box(t, lat, lon, h, n)


def _map_fig(img, info):
    n = info["size"]
    fig = go.Figure(go.Image(z=img, hoverinfo="skip"))
    feats = info["features"]
    if feats:
        fig.add_trace(go.Scatter(x=[f["x"] for f in feats], y=[f["y"] for f in feats], mode="markers+text",
                                 text=[f["name"] for f in feats], textposition="top center",
                                 textfont=dict(size=11, color=["#ffe08a" if f["lit"] else "#9fb3c8" for f in feats]),
                                 marker=dict(size=4, color=["#ffe08a" if f["lit"] else "#9fb3c8" for f in feats]),
                                 customdata=[(f["lat"], f["lon"]) for f in feats],
                                 hovertemplate="%{text}<br>lat %{customdata[0]:.1f}° · lon %{customdata[1]:.1f}°<extra></extra>",
                                 name=i18n.tr("Mari e crateri")))
    xs, ys = info["sub_obs_px"]
    fig.add_trace(go.Scatter(x=[xs], y=[ys], mode="markers", marker=dict(symbol="cross-thin", size=14,
                             line=dict(color="#e8590c", width=2)), name=i18n.tr("Centro visto da te (librazione)"),
                             hovertemplate=i18n.tr("Centro visto da te (librazione)") + "<extra></extra>"))
    xp, yp, vis = info["north"]
    if vis:
        fig.add_trace(go.Scatter(x=[xp], y=[yp], mode="markers+text", text=["N"], textposition="top center",
                                 textfont=dict(color="#e8590c", size=14), marker=dict(size=7, color="#e8590c"),
                                 name=i18n.tr("Polo nord lunare"), hovertemplate=i18n.tr("Polo nord lunare") + "<extra></extra>"))
    fig.update_xaxes(visible=False, range=[0, n])
    fig.update_yaxes(visible=False, range=[n, 0], scaleanchor="x")
    fig.update_layout(height=640, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor="#000", paper_bgcolor="#000",
                      legend=dict(orientation="h", y=-0.02, font=dict(color="#ddd")))
    return fig


def _map_box(t, lat, lon, h, n):
    from emelab import moon_map
    st.markdown("#### " + i18n.tr("🗺️ Mappa della Luna"))
    c = st.columns([2, 2, 3])
    up = c[0].radio("In alto", ["zenith", "north"], horizontal=True, key="moon_map_up",
                    format_func=lambda k: {"zenith": "Zenit (come la vedi)", "north": "Nord celeste"}[k],
                    help="Zenit: la Luna orientata come la vedi dalla stazione in questo momento. Nord celeste: come "
                         "nelle carte del cielo e nei telescopi senza diagonale (est a sinistra).")
    names = c[1].checkbox("Nomi di mari e crateri", True, key="moon_map_names")
    img, info = moon_map.render(t, lat, lon, h, 560, up)
    if not names:
        info = {**info, "features": []}
    st.plotly_chart(_map_fig(img, info), width="stretch", key="moon_map")
    ob, ss = info["sub_obs"], info["sub_sun"]
    st.caption(i18n.tr("Fase") + f" {i18n.tr(n['phase']['name'])}, " + i18n.tr("illuminata al") +
               f" {100 * n['phase']['illum']:.0f} % · " + i18n.tr("centro visto da te") +
               f": lat {ob[0]:+.1f}°, lon {ob[1]:+.1f}° · " + i18n.tr("Sole allo zenit su") +
               f" lat {ss[0]:+.1f}°, lon {ss[1]:+.1f}° · " + i18n.tr("in giallo i punti illuminati, in azzurro quelli al buio"))
    st.caption("Mappa della superficie: texture di Celestia ricavata dalle immagini LRO e dal «CGI Moon Kit» della NASA "
               "(pubblico dominio). Il lato in ombra è schiarito un po' per riconoscere i mari.")
