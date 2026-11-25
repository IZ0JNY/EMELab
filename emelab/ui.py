# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""The tabs of EMELab (emelab/app.py): station, setups (dish and feed from a FeedLab project file), new measurement with Sun/Moon positions and weather (UTC), log, expected vs measured,
pointing model, Moon planner and measurement guide. All data stay in a local SQLite file (settings folder);
the personal weather-station address is saved only in the local settings."""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import plotly.graph_objects as go
import streamlit as _st

from emelab import analysis, astro, atmos, bridge, db as edb, i18n, planner, weather
from emelab import settings as openems_local   # same interface: load_settings / save_settings

st = i18n.wrap(_st)
BANDS = {"10.368 GHz": 10.368, "24.048 GHz": 24.048, "47.088 GHz": 47.088}


def _db():
    """A fresh connection at every run (Streamlit reruns on other threads; opening SQLite costs ~1 ms)."""
    return edb.DB()


def _fmt(v, f="{:.2f}"):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f.format(v)


# ------------------------------------------------------------------ station and setups
def _station(D):
    stn = D.station()
    st.subheader("Stazione")
    c = st.columns(4)
    call = c[0].text_input("Nominativo", stn.get("callsign") or "", key="em_call")
    loc = c[1].text_input("Locator", stn.get("locator") or "", key="em_loc", help="es. JN61fs: calcola latitudine e longitudine")
    lat0, lon0 = stn.get("lat"), stn.get("lon")
    if loc and len(loc.strip()) >= 4 and (lat0 is None or loc.strip().upper() != (stn.get("locator") or "").upper()):
        try:
            lat0, lon0 = astro.locator_to_latlon(loc)
        except Exception:
            pass
    lat = c[2].number_input("Latitudine (°, nord +)", -90.0, 90.0, float(lat0 or 0.0), 0.0001, format="%.4f", key="em_lat")
    lon = c[3].number_input("Longitudine (°, est +)", -180.0, 180.0, float(lon0 or 0.0), 0.0001, format="%.4f", key="em_lon")
    c = st.columns(4)
    h = c[0].number_input("Quota (m s.l.m.)", -100.0, 5000.0, float(stn.get("height_m") or 0.0), 1.0, key="em_h")
    sets = openems_local.load_settings()
    url = c[1].text_input("Stazione meteo personale (facoltativa)", sets.get("emelab_wx_url", ""), key="em_wxurl",
                          help="indirizzo del tuo sito Meteotemplate / Cumulus / Weather Display, oppure del file dati. "
                               "Resta salvato solo su questo PC")
    flux = c[2].number_input("Flusso solare a 15.4 GHz (SFU)", 300.0, 3000.0, float(sets.get("emelab_flux", 550.0)), 10.0,
                             key="em_flux", help="valore del giorno dagli osservatori RSTN (San Vito, Learmonth, Sagamore "
                                                 "Hill, Palehua) pubblicato da NOAA SWPC; serve per il rumore solare atteso")
    if c[3].button("💾 Salva stazione", key="em_save_st"):
        D.save_station(callsign=call.strip().upper(), locator=loc.strip(), lat=lat, lon=lon, height_m=h)
        openems_local.save_settings(emelab_wx_url=url.strip(), emelab_flux=flux)
        st.success("Stazione salvata (solo su questo PC).")
    st.caption("Tutti i dati di EMELab (stazione, configurazioni, misure, indirizzo della stazione meteo) restano in un file sul "
               "tuo PC e non vengono mai inviati: il meteo da internet riceve solo coordinate e ora.")


def _setups(D):
    st.subheader("Configurazioni per banda")
    st.caption("Una configurazione per ogni banda: parabola, feed, perdite, preamplificatore/transverter e potenza. Il pulsante "
               "«Carica file di progetto FeedLab» prende parabola, feed e risultati (guadagno, efficienza, spillover, taper) "
               "dal file salvato da FeedLab, senza ricalcolarli.")
    c = st.columns(4)
    band_l = c[0].selectbox("Banda", list(BANDS), key="em_setup_band")
    band = BANDS[band_l]
    name = c[1].text_input("Nome della configurazione", f"{band_l} — 2.4 m", key="em_setup_name")
    nf = c[2].number_input("NF preamplificatore / transverter (dB)", 0.2, 10.0, 1.5 if band < 30 else 3.0, 0.1, key="em_nf")
    line = c[3].number_input("Perdite feed → LNA (dB)", 0.0, 5.0, 0.2, 0.05, key="em_line",
                             help="relè, guida, adattatori tra il feed e l'ingresso del preamplificatore")
    c = st.columns(4)
    txw = c[0].number_input("Potenza TX al feed (W)", 0.0, 2000.0, 20.0, 1.0, key="em_txw")
    rms = c[1].number_input("Superficie della parabola, errore RMS (mm)", 0.0, 3.0, 0.3, 0.05, key="em_rms",
                            help="perdita di Ruze: a 47 GHz 0.3 mm RMS costano circa 1.2 dB")
    hp = c[2].number_input("Larghezza del fascio misurata (°, 0 = calcolata)", 0.0, 5.0, 0.0, 0.01, key="em_hpbw",
                           help="dal transito del sole: durata a −3 dB × 0.25°/min × cos(dec)")
    extra = {"nf_db": nf, "line_loss_db": line, "tx_w": txw, "rms_mm": rms, "hpbw_deg": hp or None}
    b = st.columns(3)
    up = b[0].file_uploader("📂 Carica file di progetto FeedLab", type=["json"], key="em_proj_up",
                            help="il file .feedlab.json salvato da FeedLab (scheda 📦 Output di progetto): parabola, feed e "
                                 "risultati già calcolati per la sua banda")
    proj = None
    if up is not None:
        try:
            proj = bridge.load_project(up.getvalue())
        except Exception as e:
            st.error(i18n.tr("File non valido") + f": {e}")
    elif b[0].button("📥 Ultimo progetto aperto in FeedLab", key="em_last_fl",
                     help="il progetto che FeedLab tiene aggiornato su questo PC"):
        proj = bridge.latest_feedlab_project()
        if proj is None:
            st.warning("Nessun progetto da FeedLab: apri FeedLab e completa banda, parabola, feed e materiale.")
    if proj is not None:
        st.caption(i18n.tr("Progetto FeedLab") + ": " + bridge.describe(proj))
        if st.button("💾 Salva configurazione dal progetto", key="em_proj_save", type="primary"):
            band_p = float(proj["inputs"]["f_ghz"])
            D.save_setup(name if abs(band_p - band) < 0.5 else f"{band_p:.4f} GHz — {proj['inputs'].get('feed_name', '')}",
                         band_p, bridge.setup_from_project(proj, extra))
            st.success("Configurazione salvata dal progetto FeedLab.")
    with b[1].popover("✍️ Inserisci a mano"):
        Dm = st.number_input("Diametro della parabola (m)", 0.3, 20.0, 2.4, 0.05, key="em_m_D")
        eta = st.number_input("Efficienza d'apertura (%)", 20.0, 90.0, 60.0, 1.0, key="em_m_eta")
        et = st.number_input("Taper al bordo (dB)", 5.0, 25.0, 12.0, 0.5, key="em_m_et")
        if st.button("💾 Salva configurazione", key="em_m_save"):
            lam = 299.792458 / band
            g = 10 * math.log10(eta / 100 * (math.pi * Dm * 1000 / lam) ** 2)
            D.save_setup(name, band, {"band_ghz": band, "D_m": Dm, "eta_ap": eta / 100, "gain_dbi": g, "edge_taper_db": et,
                                      "spill": 0.9, "ground_frac": 0.25, "source": "manuale", **extra})
            st.success("Configurazione salvata.")
    rows = D.setups()
    if rows:
        st.dataframe([{"ID": r["id"], "Nome": r["name"], "Banda (GHz)": r["band_ghz"], "Parabola (m)": r.get("D_m"),
                       "Guadagno (dBi)": round(r.get("gain_dbi", 0), 2), "Efficienza (%)": round(100 * r.get("eta_ap", 0), 1),
                       "Taper (dB)": round(r.get("edge_taper_db", 0), 1), "NF (dB)": r.get("nf_db"),
                       "Perdite (dB)": r.get("line_loss_db"), "TX (W)": r.get("tx_w"), "Origine": r.get("source")}
                      for r in rows], hide_index=True, width="stretch")
        dl = st.selectbox("Elimina configurazione", [None] + [r["id"] for r in rows], key="em_del_setup",
                          format_func=lambda i: "—" if i is None else next(r["name"] for r in rows if r["id"] == i))
        if dl and st.button("🗑️ Elimina", key="em_del_setup_btn"):
            D.delete_setup(dl)
            st.rerun()


# ------------------------------------------------------------------ new measurement
def _wx_fetch(src, stn, dt):
    url = openems_local.load_settings().get("emelab_wx_url", "")
    try:
        if src == "station":
            if not url:
                st.warning("Inserisci l'indirizzo della tua stazione meteo nella sezione Stazione.")
                return
            w = weather.station_now(url)
        else:
            w = weather.open_meteo(stn["lat"], stn["lon"], dt)
        for k in ("t_c", "rh", "p_hpa", "wind_ms", "rain_mmh", "cloud_pct"):
            if w.get(k) is not None:
                _st.session_state[f"em_wx_{k}"] = float(w[k])
        _st.session_state["em_wx_src"] = w.get("wx_source")
        _st.session_state["em_wx_utc"] = w.get("wx_utc")
    except Exception as e:
        st.error(i18n.tr("Meteo non disponibile") + f": {e}")


def _new(D):
    stn = D.station()
    sets = D.setups()
    if not stn.get("lat") and not stn.get("lon"):
        st.info("Inserisci e salva prima la stazione (posizione) nella sezione Stazione e configurazioni.")
        return
    if not sets:
        st.info("Crea prima una configurazione per la banda (sezione Stazione e configurazioni).")
        return
    now = datetime.now(timezone.utc)
    c = st.columns(4)
    sid = c[0].selectbox("Configurazione", [s["id"] for s in sets], key="em_n_setup",
                         format_func=lambda i: next(s["name"] for s in sets if s["id"] == i))
    setup = next(s for s in sets if s["id"] == sid)
    d0 = c[1].date_input("Data (UTC)", now.date(), key="em_n_date")
    t0 = c[2].time_input("Ora (UTC)", now.time().replace(second=0, microsecond=0), key="em_n_time", step=60)
    if "em_n_kind" not in _st.session_state:          # by night the Moon is the natural default
        _now = astro.sky(now, stn["lat"], stn["lon"], stn.get("height_m") or 0.0)
        _st.session_state["em_n_kind"] = "sun" if _now.sun.el > 3 else "moon" if _now.moon.el > 3 else "cold_sky"
    kind = c[3].selectbox("Tipo di misura", list(edb.KINDS), key="em_n_kind", format_func=lambda k: edb.KINDS[k])
    dt = datetime.combine(d0, t0).replace(tzinfo=timezone.utc)
    st.caption(f"⏱️ {edb.iso_utc(dt)} UTC")
    c = st.columns(4)
    y = c[0].number_input("Y misurato (dB)", -5.0, 40.0, None, 0.05, key="em_n_y",
                          help="sole/luna/terra: rapporto tra rumore sulla sorgente e cielo freddo")
    snr = c[1].number_input("SNR (dB)", -40.0, 60.0, None, 0.1, key="em_n_snr", help="eco o segnale: SNR letto dal programma")
    val = c[2].number_input("Altro valore", value=None, key="em_n_val", help="es. livello in dBm, spostamento del feed in mm")
    unit = c[3].text_input("Unità", "", key="em_n_unit")
    c = st.columns(5)
    azr = c[0].number_input("AZ letto (°)", 0.0, 360.0, None, 0.01, key="em_n_azr")
    elr = c[1].number_input("EL letto (°)", -5.0, 95.0, None, 0.01, key="em_n_elr")
    azo = c[2].number_input("Correzione AZ al picco (°)", -10.0, 10.0, None, 0.005, key="em_n_azo",
                            help="correzione che hai dovuto dare rispetto alla posizione calcolata per avere il massimo")
    elo = c[3].number_input("Correzione EL al picco (°)", -10.0, 10.0, None, 0.005, key="em_n_elo")
    partner = c[4].text_input("Stazione corrispondente", "", key="em_n_partner", help="nominativo e locator, per eco/QSO")
    st.markdown("**Meteo al momento della misura**")
    b = st.columns(3)
    if b[0].button("🌡️ Dalla mia stazione", key="em_wx_st"):
        _wx_fetch("station", stn, dt)
    if b[1].button("🌍 Da Open-Meteo", key="em_wx_om"):
        _wx_fetch("om", stn, dt)
    b[2].caption((i18n.tr("Fonte") + f": {_st.session_state.get('em_wx_src') or i18n.tr('manuale')} · "
                  f"{_st.session_state.get('em_wx_utc') or '—'} UTC"))
    c = st.columns(6)
    t_c = c[0].number_input("Temperatura (°C)", -40.0, 50.0, None, 0.1, key="em_wx_t_c")
    rh = c[1].number_input("Umidità (%)", 0.0, 100.0, None, 1.0, key="em_wx_rh")
    p = c[2].number_input("Pressione (hPa)", 800.0, 1100.0, None, 0.1, key="em_wx_p_hpa")
    wind = c[3].number_input("Vento (m/s)", 0.0, 60.0, None, 0.1, key="em_wx_wind_ms")
    rain = c[4].number_input("Pioggia (mm/h)", 0.0, 200.0, None, 0.1, key="em_wx_rain_mmh")
    cloud = c[5].number_input("Nuvole (%)", 0.0, 100.0, None, 1.0, key="em_wx_cloud_pct")
    notes = st.text_area("Note", "", key="em_n_notes", height=70)
    wx = {"t_c": t_c, "rh": rh, "p_hpa": p}
    calc = analysis.snapshot(stn, setup, dt, wx, openems_local.load_settings().get("emelab_flux"))
    _show_snapshot(calc, kind)
    if st.button("💾 Registra misura", type="primary", key="em_n_save"):
        D.add(utc=dt, setup_id=sid, band_ghz=setup["band_ghz"], kind=kind, y_db=y, snr_db=snr, value=val, unit=unit or None,
              az_read=azr, el_read=elr, az_off=azo, el_off=elo, partner=partner or None, notes=notes or None,
              t_c=t_c, rh=rh, p_hpa=p, wind_ms=wind, rain_mmh=rain, cloud_pct=cloud,
              wx_utc=_st.session_state.get("em_wx_utc"), wx_source=_st.session_state.get("em_wx_src") or "manuale",
              calc=_clean(calc))
        st.success("Misura registrata.")


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


def _show_snapshot(c, kind):
    s, m = c["sun"], c["moon"]
    cols = st.columns(4)
    cols[0].metric("Sole AZ / EL", f"{s['az']:.2f}° / {s['el']:.2f}°")
    cols[1].metric("Luna AZ / EL", f"{m['az']:.2f}° / {m['el']:.2f}°")
    cols[2].metric("Distanza Luna", f"{m['dist_km']:.0f} km")
    cols[3].metric("Angolo Sole–Luna", f"{c['sun_moon_deg']:.1f}°")
    cols = st.columns(4)
    cols[0].metric("Attenuazione allo zenit", f"{c['a_zen_db']:.2f} dB", help=f"O₂ {c['a_zen_o2']:.2f} + H₂O {c['a_zen_h2o']:.2f} dB, "
                   f"vapore {c['rho']:.1f} g/m³")
    src = s if kind == "sun" else m
    if src["el"] < 0:
        st.warning(("Il Sole" if kind == "sun" else "La Luna") + " " + i18n.tr("è sotto l'orizzonte in questo momento") +
                   f" (EL {src['el']:.1f}°).")
    cols[1].metric("Attenuazione sul percorso", _fmt(src["a_slant_db"], "{:.2f} dB"))
    cols[2].metric("Temperatura di cielo", _fmt(src["t_sky"], "{:.0f} K"))
    cols[3].metric("Tsys (cielo freddo)", _fmt(src["tsys"], "{:.0f} K"))
    cols = st.columns(4)
    cols[0].metric("Y sole atteso", _fmt(s["y_db"], "{:.2f} dB"))
    cols[1].metric("Y luna atteso", _fmt(m["y_db"], "{:.2f} dB"))
    cols[2].metric("Fascio a −3 dB", f"{c['hpbw_deg']:.3f}°")
    e = c.get("echo")
    cols[3].metric("Eco attesa (SNR in 1 Hz)", _fmt(e["snr_1hz_db"], "{:.1f} dB") if e else "—",
                   help=(i18n.tr("nella banda di allargamento") + f" {e['spread_hz']:.0f} Hz: {e['snr_spread_db']:.1f} dB · "
                         + i18n.tr("perdita di tratta") + f" {e['path_loss_db']:.2f} dB · " + i18n.tr("fascio più stretto della Luna")
                         + f" {e['beam_moon_db']:.1f} dB") if e else None)
    st.caption(i18n.tr("Doppler eco") + f" {c['doppler_hz']:+.0f} Hz · " + i18n.tr("allargamento") + f" {c['spread_hz']:.0f} Hz · "
               + i18n.tr("fase lunare") + f" {c['moon_phase_deg']:+.0f}° ({100 * c['moon_illum']:.0f} %)")


# ------------------------------------------------------------------ log
def _log(D):
    sets = {s["id"]: s for s in D.setups()}
    c = st.columns(2)
    fb = c[0].selectbox("Banda", [None] + list(BANDS), key="em_l_band", format_func=lambda b: i18n.tr("tutte") if b is None else b)
    fk = c[1].selectbox("Tipo", [None] + list(edb.KINDS), key="em_l_kind",
                        format_func=lambda k: i18n.tr("tutti") if k is None else edb.KINDS[k])
    rows = D.measurements(BANDS.get(fb) if fb else None, fk)
    if not rows:
        st.info("Nessuna misura registrata.")
    else:
        tab = []
        for r in rows:
            ev = analysis.evaluate_measurement(r, sets[r["setup_id"]]) if r.get("setup_id") in sets else {}
            c = r.get("calc") or {}
            src = c.get("moon" if r["kind"] in ("moon", "echo", "qso") else "sun") or {}
            tab.append({"ID": r["id"], "UTC": r["utc"].replace("T", " ").replace("Z", ""), "GHz": r["band_ghz"], "Tipo": edb.KINDS.get(r["kind"], r["kind"]),
                        "Y (dB)": r["y_db"], "Y atteso": _r(ev.get("y_expected")), "ΔY": _r(ev.get("y_delta")),
                        "G/T misurato": _r(ev.get("gt_measured")), "ΔG/T": _r(ev.get("gt_delta")), "SNR": r["snr_db"],
                        "SNR atteso": _r(ev.get("snr_expected")), "EL": _r(src.get("el")), "AZ": _r(src.get("az")),
                        "°C": r["t_c"], "UR %": r["rh"], "hPa": r["p_hpa"], "Meteo": r["wx_source"], "Note": r["notes"]})
        import pandas as pd
        tr = i18n.tr                                   # pandas tables are not translated by the streamlit proxy
        df = pd.DataFrame([{tr(k): (tr(v) if k in ("Tipo", "Meteo") and isinstance(v, str) else v) for k, v in row.items()}
                           for row in tab])
        st.dataframe(df, hide_index=True, width="stretch")
        c = st.columns(3)
        dl = c[0].selectbox("Elimina misura (ID)", [None] + [r["id"] for r in rows], key="em_del_m",
                            format_func=lambda i: "—" if i is None else str(i))
        if dl and c[0].button("🗑️ Elimina", key="em_del_m_btn"):
            D.delete(dl)
            st.rerun()
        c[1].download_button("⬇️ Esporta CSV", D.export_csv(), file_name="emelab_misure.csv", mime="text/csv")
    up = st.file_uploader("Importa CSV", type=["csv"], key="em_imp")
    if up is not None and st.button("📥 Importa", key="em_imp_btn"):
        n = D.import_csv(up.getvalue().decode("utf-8"))
        st.success(i18n.tr("Misure importate") + f": {n}")


def _r(v, n=2):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, n)


# ------------------------------------------------------------------ analysis
def _analysis(D):
    sets = D.setups()
    if not sets:
        st.info("Nessuna configurazione.")
        return
    sid = st.selectbox("Configurazione", [s["id"] for s in sets], key="em_a_setup",
                       format_func=lambda i: next(s["name"] for s in sets if s["id"] == i))
    setup = next(s for s in sets if s["id"] == sid)
    rows = [r for r in D.measurements() if r.get("setup_id") == sid]
    for t in analysis.advice(rows, setup):
        st.markdown("- " + i18n.tr(t))
    with st.expander("📊 Dove guadagnare dB con questa configurazione", expanded=not rows):
        st.caption("Quanto cambiano G/T (ricezione) e SNR delle eco con miglioramenti realistici, a 30° di elevazione e "
                   "UR 60 %, con lo stesso modello usato per i valori attesi.")
        st.dataframe([{"Miglioramento": i18n.tr(r["label"]), "ΔG/T (dB)": round(r["d_gt"], 2), "ΔEco (dB)": round(r["d_echo"], 2)}
                      for r in sorted(analysis.improvements(setup), key=lambda r: -abs(r["d_echo"]))],
                     hide_index=True, width="stretch")
    ev = [(r, analysis.evaluate_measurement(r, setup)) for r in rows]
    sun = [(r, e) for r, e in ev if "gt_delta" in e]
    if sun:
        c = st.columns(2)
        fig = go.Figure(go.Scatter(x=[r["calc"]["sun"]["el"] for r, _ in sun], y=[e["gt_delta"] for _, e in sun],
                                   mode="markers", marker=dict(size=9, color=[r.get("rh") for r, _ in sun],
                                   colorscale="Viridis", showscale=True, colorbar=dict(title="UR %"))))
        fig.add_hline(y=0, line_dash="dot")
        fig.update_layout(title="G/T misurato − atteso vs elevazione del sole", xaxis_title="Elevazione (°)",
                          yaxis_title="ΔG/T (dB)", height=360, margin=dict(l=10, r=10, t=40, b=10))
        c[0].plotly_chart(fig, width="stretch")
        fig = go.Figure(go.Scatter(x=[r["utc"] for r, _ in sun], y=[e["gt_measured"] for _, e in sun], mode="markers",
                                   name="misurato"))
        fig.add_trace(go.Scatter(x=[r["utc"] for r, _ in sun], y=[e["gt_expected"] for _, e in sun], mode="lines",
                                 name="atteso", line=dict(dash="dot")))
        fig.update_layout(title="G/T dal sole nel tempo", yaxis_title="G/T (dB/K)", height=360,
                          margin=dict(l=10, r=10, t=40, b=10))
        c[1].plotly_chart(fig, width="stretch")
    ff = analysis.focus_fit(rows)
    if ff:
        fig = go.Figure(go.Scatter(x=ff["x"], y=ff["y"], mode="markers", name="misurato"))
        xs = np.linspace(min(ff["x"]), max(ff["x"]), 60)
        a, b, c0 = ff["coef"]
        fig.add_trace(go.Scatter(x=xs, y=a * xs ** 2 + b * xs + c0, mode="lines", name="curva interpolata"))
        fig.update_layout(title="Messa a fuoco: Y in funzione dello spostamento del feed", xaxis_title="Spostamento (mm)",
                          yaxis_title="Y (dB)", height=340, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
        if ff["best_mm"] is not None:
            st.success(i18n.tr("Fuoco migliore a") + f" {ff['best_mm']:+.1f} mm " + i18n.tr("dalla posizione di partenza") +
                       f" ({ff['gain_db']:+.2f} dB " + i18n.tr("di Y in più") + ").")
    pm = [r for r in rows if r.get("az_off") is not None and r.get("el_off") is not None and r["kind"] in ("sun", "moon")]
    if pm:
        fig = go.Figure(go.Scatter(x=[r["az_off"] for r in pm], y=[r["el_off"] for r in pm], mode="markers",
                                   text=[r["utc"] for r in pm], marker=dict(size=9, color=[r["calc"][r["kind"]]["el"] for r in pm],
                                   colorscale="Plasma", showscale=True, colorbar=dict(title="EL"))))
        hp = analysis.hpbw_of(setup)
        fig.add_shape(type="circle", x0=-hp / 2, x1=hp / 2, y0=-hp / 2, y1=hp / 2, line=dict(dash="dot"))
        fig.update_layout(title="Correzioni di puntamento al picco (cerchio = fascio a −3 dB)", xaxis_title="Correzione AZ (°)",
                          yaxis_title="Correzione EL (°)", height=380, margin=dict(l=10, r=10, t=40, b=10))
        fig.update_yaxes(scaleanchor="x")
        st.plotly_chart(fig, width="stretch")


# ------------------------------------------------------------------ planner
def _planner(D):
    stn = D.station()
    sets = D.setups()
    if not sets or (not stn.get("lat") and not stn.get("lon")):
        st.info("Servono stazione e configurazione.")
        return
    c = st.columns(5)
    sid = c[0].selectbox("Configurazione", [s["id"] for s in sets], key="em_p_setup",
                         format_func=lambda i: next(s["name"] for s in sets if s["id"] == i))
    setup = next(s for s in sets if s["id"] == sid)
    days = c[1].number_input("Giorni", 1, 60, 14, key="em_p_days")
    min_el = c[2].number_input("Elevazione minima (°)", 0.0, 60.0, 10.0, 1.0, key="em_p_minel",
                               help="sotto i 10–15° a 24/47 GHz l'atmosfera e il rumore di terra pesano molto")
    ploc = c[3].text_input("Locator della stazione corrispondente", "", key="em_p_ploc",
                           help="facoltativo: mostra solo le finestre in cui la Luna è visibile da entrambi")
    use_fc = c[4].checkbox("Usa le previsioni meteo", False, key="em_p_fc",
                           help="umidità prevista da Open-Meteo (16 giorni): a 24 GHz cambia l'attenuazione")
    if st.button("🗓️ Calcola", type="primary", key="em_p_go"):
        partner = None
        if ploc.strip():
            try:
                partner = astro.locator_to_latlon(ploc)
            except Exception:
                st.warning("Locator non valido.")
        series = None
        if use_fc:
            try:
                series = weather.open_meteo_series(stn["lat"], stn["lon"], datetime.now(timezone.utc), min(int(days), 16))
            except Exception as e:
                st.warning(i18n.tr("Previsioni non disponibili") + f": {e}")
        with st.spinner("Calcolo delle finestre…"):
            smp = planner.windows(stn, setup, datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0),
                                  int(days), 15, min_el, partner, series)
        _st.session_state["em_plan"] = (smp, planner.daily(smp))
    if _st.session_state.get("em_plan"):
        smp, rows = _st.session_state["em_plan"]
        if not rows:
            st.info("Nessuna finestra nel periodo con questi limiti.")
            return
        st.dataframe([{"Inizio (UTC)": r["start"].strftime("%Y-%m-%d %H:%M"), "Fine (UTC)": r["end"].strftime("%Y-%m-%d %H:%M"),
                       "Ore": round(r["hours"], 1), "Momento migliore (UTC)": r["best_utc"].strftime("%Y-%m-%d %H:%M"),
                       "EL max (°)": round(r["best_el"], 1), "Distanza (km)": round(r["dist_km"]),
                       "Eco SNR 1 Hz (dB)": _r(r["snr_1hz"], 1), "Eco SNR nell'allargamento (dB)": _r(r["snr_spread"], 1),
                       "Allargamento (Hz)": round(r["spread_hz"]), "Attenuazione (dB)": round(r["a_slant_db"], 2),
                       "Sole–Luna min (°)": round(r["sun_moon_deg"], 1)} for r in rows], hide_index=True, width="stretch")
        fig = go.Figure(go.Scatter(x=[s["utc"] for s in smp], y=[s["snr_1hz"] for s in smp], mode="markers",
                                   marker=dict(size=4, color=[s["el"] for s in smp], colorscale="Viridis", showscale=True,
                                               colorbar=dict(title="EL"))))
        fig.update_layout(title="SNR atteso delle eco (1 Hz) nelle finestre", yaxis_title="dB", height=360,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
    with st.expander("🌡️ Mesi più favorevoli (clima dell'ultimo anno nel tuo luogo)"):
        st.caption("Medie mensili di temperatura e umidità dall'archivio Open-Meteo: vapore acqueo, attenuazione, "
                   "temperatura di cielo a 30° e quanto perdi rispetto al mese migliore (G/T e eco).")
        if st.button("Calcola dal clima", key="em_p_clim"):
            try:
                _st.session_state["em_clim"] = planner.monthly_climate(stn["lat"], stn["lon"], setup)
            except Exception as e:
                st.warning(i18n.tr("Archivio meteo non disponibile") + f": {e}")
        cl = _st.session_state.get("em_clim")
        if cl:
            st.dataframe([{"Mese": i18n.tr(planner.MONTHS_IT[r["month"] - 1]), "°C": round(r["t_c"], 1), "UR %": round(r["rh"]),
                           "Vapore (g/m³)": round(r["rho"], 1), "Attenuazione zenit (dB)": round(r["a_zen_db"], 2),
                           "Cielo a 30° (K)": round(r["t_sky"]), "ΔG/T (dB)": round(r["d_gt_db"], 2),
                           "ΔEco (dB)": round(r["d_echo_db"], 2)} for r in cl], hide_index=True, width="stretch")
    with st.expander("📅 Perigei e apogei dei prossimi mesi"):
        if st.button("Calcola perigei", key="em_p_peri"):
            pts = planner.perigees(datetime.now(timezone.utc), 200)
            st.dataframe([{"UTC": t.strftime("%Y-%m-%d %H:%M"), "Tipo": k, "Distanza (km)": round(d),
                           "Eco rispetto al perigeo (dB)": round(-40 * math.log10(d / min(x[1] for x in pts)), 2)}
                          for t, d, k in pts], hide_index=True, width="stretch")
        st.caption("Al perigeo le eco sono fino a 2.2 dB più forti che all'apogeo (la perdita di tratta va con R⁴).")


# ------------------------------------------------------------------ guide
def _guide():
    from pathlib import Path
    lang = i18n.get_lang()
    p = Path(__file__).resolve().parent / f"guida_misure_{'it' if lang == 'it' else 'en'}.md"
    if p.exists():
        _st.markdown(p.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ world map (plotly, offline coastlines)
def world_fig(paths: list[tuple], points: list[tuple] = (), sublunar: tuple | None = None, height: int = 420):
    """paths: [(lat_a, lon_a, lat_b, lon_b, colour, label)], points: [(lat, lon, text, colour)]."""
    import json
    from pathlib import Path
    from emelab import report
    fig = go.Figure()
    p = Path(__file__).resolve().parent / "data" / "ne_110m_land.json"
    if p.exists():
        xs, ys = [], []
        for poly in json.loads(p.read_text())["polygons"]:
            xs += [c[0] for c in poly] + [None]
            ys += [c[1] for c in poly] + [None]
        fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", fillcolor="#e8e4d8", line=dict(color="#9a9484", width=0.6),
                                 hoverinfo="skip", showlegend=False))
    for la, lo, lb, lob, col, lab in paths:
        lat, lon = report.great_circle_points((la, lo), (lb, lob))
        fig.add_trace(go.Scatter(x=lon, y=lat, mode="lines", line=dict(color=col, width=2), name=lab, hoverinfo="name"))
    for la, lo, txt, col in points:
        fig.add_trace(go.Scatter(x=[lo], y=[la], mode="markers+text", text=[txt], textposition="top center",
                                 marker=dict(size=8, color=col), showlegend=False))
    if sublunar:
        fig.add_trace(go.Scatter(x=[sublunar[1]], y=[sublunar[0]], mode="markers+text", text=["🌕"],
                                 marker=dict(size=14, color="#f4efd8", line=dict(color="#555", width=1)),
                                 name=i18n.tr("punto sub-lunare")))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor="#dfeaf3",
                      xaxis=dict(range=[-180, 180], showgrid=True, gridcolor="#c9d6e2", zeroline=False, title=""),
                      yaxis=dict(range=[-90, 90], showgrid=True, gridcolor="#c9d6e2", zeroline=False, scaleanchor="x", title=""),
                      legend=dict(orientation="h"))
    return fig


# ------------------------------------------------------------------ EME stations
def _stations_tab(D):
    from emelab import stations as stn
    st.subheader("Stazioni EME")
    st.caption("Database delle stazioni costruito sul tuo PC da: CALL3.TXT e ALL.TXT di WSJT-X, EME Directory di PA0PLY e, "
               "se vuoi, QRZ.com. Le email non vengono salvate; i dati restano su questo PC.")
    c = st.columns(3)
    up3 = c[0].file_uploader("CALL3.TXT di WSJT-X", type=["txt"], key="st_call3")
    upa = c[1].file_uploader("ALL.TXT di WSJT-X", type=["txt"], key="st_all",
                             help="il registro di tutte le decodifiche: chi hai davvero ascoltato, su quale banda, con quale SNR")
    with c[2]:
        st.markdown("**EME Directory (PA0PLY)**")
        if st.button("🔄 Scarica e aggiorna", key="st_pa0ply",
                     help="scarica dal sito di Henk PA0PLY i PDF delle bande 10, 24, 47 e 76 GHz e li legge"):
            _pa0ply_update(D)
        upp = st.file_uploader("…oppure carica i PDF", type=["pdf"], accept_multiple_files=True, key="st_pa0ply_up")
    if up3 is not None and st.button("📥 Importa CALL3.TXT", key="st_call3_go"):
        rows = stn.parse_call3(up3.getvalue().decode("utf-8", "replace"))
        for r in rows:
            D.upsert_station(r["call"], locator=r["locator"], eme=1 if r["eme"] else None, data={"call3": True})
        D.commit()
        st.success(i18n.tr("Stazioni importate") + f": {len(rows)}")
    if upa is not None and st.button("📥 Importa ALL.TXT", key="st_all_go"):
        dec = stn.parse_all(upa.getvalue().decode("utf-8", "replace"))
        summ = stn.heard_summary(dec)
        for call, s in summ.items():
            old = (D.station_of(call) or {}).get("data", {}).get("heard", {})
            heard = {"n": old.get("n", 0) + s["n"], "first": min(str(s["first"]), old.get("first", "9999")),
                     "last": max(str(s["last"]), old.get("last", "")), "snr_best": max(s["snr_best"], old.get("snr_best", -99)),
                     "snr_median": s["snr_median"], "bands": sorted(set(old.get("bands", [])) | s["bands"]),
                     "modes": sorted(set(old.get("modes", [])) | s["modes"])}
            D.upsert_station(call, locator=s["locator"], eme=1, data={"heard": heard})
        D.commit()
        st.success(i18n.tr("Decodifiche lette") + f": {len(dec)} · " + i18n.tr("stazioni") + f": {len(summ)}")
    if upp and st.button("📥 Importa i PDF", key="st_pa0ply_go"):
        _pa0ply_import(D, [(f.name, f.getvalue()) for f in upp])
    rows = D.stations()
    if rows:
        import pandas as pd
        tab = []
        for r in rows:
            d = r.get("data", {})
            h = d.get("heard", {})
            dirb = d.get("directory", {})
            tab.append({"Nominativo": r["call"], "Locator": r.get("locator"), "Nome": r.get("name"), "QTH": r.get("qth"),
                        "Bande (directory)": ", ".join(sorted(dirb)), "Stazione": "; ".join(f"{b}: {v.get('antenna', '')} {v.get('power_w') or ''} W"
                                                                                  for b, v in sorted(dirb.items())),
                        "Sentito": h.get("n"), "Ultima volta": (h.get("last") or "")[:16], "SNR migliore": h.get("snr_best"),
                        "Bande sentite": ", ".join(h.get("bands", []))})
        df = pd.DataFrame(tab)
        df.columns = [i18n.tr(c) for c in df.columns]
        st.dataframe(df, hide_index=True, width="stretch")
        _qrz_box(D, [r["call"] for r in rows])


def _pa0ply_update(D):
    from emelab import stations as stn, weather
    try:
        page = weather._get(stn.PA0PLY_PAGE, 20).decode("utf-8", "replace")
        links = stn.pa0ply_pdf_links(page)
        files = [(u.rsplit("/", 1)[-1], weather._get(u, 60)) for u in links.values()]
        _pa0ply_import(D, files)
    except Exception as e:
        st.error(i18n.tr("EME Directory non raggiungibile") + f": {e}")


def _pa0ply_import(D, files):
    from emelab import stations as stn
    n = 0
    for name, data in files:
        nl = name.lower()
        band = "10G" if nl.startswith(("10368", "10g")) else "24G" if nl.startswith(("24048", "24g")) else \
            "47G" if nl.startswith("47") else "76G" if nl.startswith("76") else None
        if band is None:
            continue
        for r in stn.parse_pa0ply(stn.pdf_text(data), band):
            old = (D.station_of(r["call"]) or {}).get("data", {}).get("directory", {})
            old[band] = {"antenna": r["antenna"], "power_w": r["power_w"], "web": r["web"]}
            D.upsert_station(r["call"], locator=r["locator"], name=r["name"] or None, eme=1, data={"directory": old})
            n += 1
    D.commit()
    st.success(i18n.tr("Righe della EME Directory importate") + f": {n}")


def _qrz_box(D, calls):
    sets = openems_local.load_settings()
    with st.expander("🔎 QRZ.com: nome, indirizzo e QTH per le etichette QSL"):
        st.caption("Usa il tuo account QRZ.com (servizio XML; per l'indirizzo completo serve l'abbonamento XML Logbook Data). "
                   "Utente e password restano salvati solo su questo PC.")
        c = st.columns(3)
        user = c[0].text_input("Utente QRZ.com", sets.get("qrz_user", ""), key="qrz_user")
        pw = c[1].text_input("Password QRZ.com", sets.get("qrz_pw", ""), type="password", key="qrz_pw")
        if c[2].button("💾 Salva accesso", key="qrz_save"):
            openems_local.save_settings(qrz_user=user, qrz_pw=pw)
            st.success("Salvato su questo PC.")
        pick = st.multiselect("Nominativi da cercare", calls, key="qrz_pick")
        if pick and st.button("🔎 Cerca su QRZ.com", key="qrz_go"):
            from emelab import qrz
            try:
                q = qrz.QRZ(user, pw)
                for call in pick:
                    r = q.lookup(call)
                    D.upsert_station(call, name=r.get("name"), address=r.get("address"), qth=r.get("qth"),
                                     country=r.get("country"), locator=r.get("locator"),
                                     data={"qrz": {k: r.get(k) for k in ("qsl_via", "lotw", "eqsl", "lat", "lon")}})
                D.commit()
                st.success(i18n.tr("Aggiornati da QRZ.com") + f": {len(pick)}")
            except Exception as e:
                st.error(f"QRZ.com: {e}")


# ------------------------------------------------------------------ logbook
def _logbook_tab(D):
    from emelab import logbook as lb
    stn = D.station()
    if not stn.get("lat") and not stn.get("lon"):
        st.info("Inserisci e salva prima la stazione (posizione) nella scheda Stazione.")
        return
    my_loc = stn.get("locator") or astro.latlon_to_locator(stn["lat"], stn["lon"])
    with st.expander("➕ Nuovo QSO", expanded=True):
        now = datetime.now(timezone.utc)
        c = st.columns(4)
        d0 = c[0].date_input("Data (UTC)", now.date(), key="q_date")
        t0 = c[1].time_input("Ora (UTC)", now.time().replace(second=0, microsecond=0), key="q_time", step=60)
        call = c[2].text_input("Nominativo", "", key="q_call").strip().upper()
        known = D.station_of(call) if call else None
        loc = c[3].text_input("Locator", (known or {}).get("locator") or "", key=f"q_loc_{call}")
        c = st.columns(5)
        band = c[0].selectbox("Banda", list(lb.BAND_F), key="q_band")
        freq = c[1].number_input("Frequenza (MHz)", 1000.0, 300000.0, lb.BAND_F[band] * 1000, 0.001, format="%.3f", key=f"q_f_{band}")
        mode = c[2].selectbox("Modo", ["Q65", "JT65", "JT4", "CW", "SSB", "FST4", "Altro"], key="q_mode")
        sub = c[3].text_input("Sottomodo", "60D" if mode == "Q65" else "", key=f"q_sub_{mode}")
        pwr = c[4].text_input("Potenza TX (W)", "", key="q_pwr")
        c = st.columns(4)
        rs = c[0].text_input("Rapporto inviato", "", key="q_rs")
        rr = c[1].text_input("Rapporto ricevuto", "", key="q_rr")
        sets = D.setups()
        sid = c[2].selectbox("Configurazione", [None] + [s["id"] for s in sets], key="q_setup",
                             format_func=lambda i: "—" if i is None else next(s["name"] for s in sets if s["id"] == i))
        name = c[3].text_input("Nome", (known or {}).get("name") or "", key=f"q_name_{call}")
        comment = st.text_input("Note", "", key="q_comment")
        dt = datetime.combine(d0, t0).replace(tzinfo=timezone.utc)
        if call and loc:
            calc = lb.conditions(dt, (stn["lat"], stn["lon"]), lb.latlon(loc), freq / 1000, None, stn.get("height_m") or 0)
            cc = st.columns(5)
            cc[0].metric("Distanza a terra", f"{calc.get('ground_km', 0):.0f} km")
            cc[1].metric("Percorso EME", f"{calc.get('eme_path_km', 0):,.0f} km".replace(",", "."),
                         help=i18n.tr("stazione → Luna → stazione in quel momento") + f"; {calc.get('eme_delay_s', 0):.3f} s")
            cc[2].metric("Luna EL (tu / DX)", f"{calc['moon_el']:.1f}° / {calc.get('dx_moon_el', float('nan')):.1f}°")
            cc[3].metric("Spread mutuo", f"{calc.get('mutual_spread_hz', 0):.0f} Hz")
            cc[4].metric("Doppler mutuo", f"{calc.get('mutual_doppler_hz', 0):+.0f} Hz")
            st.plotly_chart(world_fig([(stn["lat"], stn["lon"], *lb.latlon(loc), "#d62728", f"{my_loc} – {call}")],
                                      [(stn["lat"], stn["lon"], my_loc, "#1f77b4"), (*lb.latlon(loc), call, "#d62728")],
                                      (calc["sublunar_lat"], calc["sublunar_lon"]), 360), width="stretch")
        if st.button("💾 Registra QSO", type="primary", key="q_save", disabled=not (call and loc)):
            q = {"utc": dt, "call": call, "band": band, "freq_mhz": freq, "mode": mode, "submode": sub or None,
                 "rst_sent": rs or None, "rst_rcvd": rr or None, "locator": loc.upper(), "my_locator": my_loc,
                 "name": name or None, "tx_pwr": pwr or None, "setup_id": sid, "comment": comment or None}
            q["calc"] = lb.enrich(q, my_loc, stn.get("height_m") or 0)
            D.add_qso(**q)
            if name or loc:
                D.upsert_station(call, locator=loc.upper(), name=name or None, eme=1)
                D.commit()
            st.success("QSO registrato.")
    with st.expander("📥 Importa ADIF (i tuoi QSO già fatti)"):
        ups = st.file_uploader("File ADIF (.adi, .adif)", type=["adi", "adif", "txt"], accept_multiple_files=True, key="q_adif")
        only_eme = st.checkbox("Solo i QSO EME e delle bande da 10 GHz in su", True, key="q_adif_eme")
        if ups and st.button("📥 Importa", key="q_adif_go"):
            n = dup = 0
            bar = st.progress(0.0)
            recs = [r for f in ups for r in lb.parse_adif(f.getvalue().decode("utf-8", "replace"))]
            for k, r in enumerate(recs):
                q = lb.from_adif_record(r)
                if q is None or (only_eme and (q["band"] not in lb.BAND_F or (q.get("prop_mode") or "EME").upper() != "EME")):
                    continue
                q.pop("prop_mode", None)
                q["my_locator"] = q.get("my_locator") or my_loc
                q["calc"] = lb.enrich(q, my_loc, stn.get("height_m") or 0)
                if D.add_qso(**q):
                    n += 1
                else:
                    dup += 1
                bar.progress((k + 1) / max(len(recs), 1))
            st.success(i18n.tr("QSO importati") + f": {n}" + (f" · " + i18n.tr("già presenti") + f": {dup}" if dup else ""))
    qs = D.qsos()
    if not qs:
        st.info("Nessun QSO nel log.")
        return
    import pandas as pd
    df = pd.DataFrame([{"ID": q["id"], "Data UTC": q["utc"].strftime("%Y-%m-%d %H:%M"), "Nominativo": q["call"],
                        "Banda": q.get("band"), "Modo": " ".join(x for x in (q.get("mode"), q.get("submode")) if x),
                        "Inviato": q.get("rst_sent"), "Ricevuto": q.get("rst_rcvd"), "Locator": q.get("locator"),
                        "Distanza (km)": _r(q["calc"].get("ground_km"), 0), "Percorso EME (km)": _r(q["calc"].get("eme_path_km"), 0),
                        "EL Luna": _r(q["calc"].get("moon_el"), 1), "EL DX": _r(q["calc"].get("dx_moon_el"), 1),
                        "Spread (Hz)": _r(q["calc"].get("mutual_spread_hz"), 0), "Note": q.get("comment")} for q in qs])
    df.columns = [i18n.tr(c) for c in df.columns]
    st.dataframe(df, hide_index=True, width="stretch")
    cols = {"10G": "#1f77b4", "24G": "#d62728", "47G": "#2ca02c", "76G": "#9467bd", "122G": "#8c564b", "134G": "#e377c2"}
    paths = [(*lb.latlon(q["my_locator"] or my_loc), *lb.latlon(q["locator"]), cols.get(q.get("band"), "#555"),
              f"{q['call']} {q.get('band') or ''}") for q in qs if q.get("locator") and lb.latlon(q["locator"])]
    st.plotly_chart(world_fig(paths[-300:], height=460), width="stretch")
    c = st.columns(3)
    c[0].download_button("⬇️ Esporta ADIF", lb.to_adif(qs, stn.get("callsign") or ""), file_name="emelab_log.adi",
                         mime="text/plain")
    dl = c[1].selectbox("Elimina QSO (ID)", [None] + [q["id"] for q in qs], key="q_del",
                        format_func=lambda i: "—" if i is None else str(i))
    if dl and c[1].button("🗑️ Elimina", key="q_del_go"):
        D.delete_qso(dl)
        st.rerun()


def _qso_stats_tab(D):
    from emelab import logbook as lb
    qs = D.qsos()
    if not qs:
        st.info("Nessun QSO nel log.")
        return
    s = lb.statistics(qs)
    c = st.columns(4)
    c[0].metric("QSO", s["n"])
    c[1].metric("Bande", ", ".join(f"{b}: {n}" for b, n in sorted(s["by_band"].items())))
    if "moon_el" in s:
        c[2].metric("EL Luna mediana", f"{s['moon_el']['median']:.0f}°")
    if "mutual_spread_hz" in s:
        c[3].metric("Spread mutuo mediano", f"{s['mutual_spread_hz']['median']:.0f} Hz")
    cc = st.columns(2)
    fig = go.Figure(go.Bar(x=list(range(24)), y=s["by_hour"]))
    fig.update_layout(title="QSO per ora UTC", height=300, margin=dict(l=10, r=10, t=40, b=10))
    cc[0].plotly_chart(fig, width="stretch")
    fig = go.Figure(go.Bar(x=[i18n.tr(m) for m in planner.MONTHS_IT], y=s["by_month"]))
    fig.update_layout(title="QSO per mese", height=300, margin=dict(l=10, r=10, t=40, b=10))
    cc[1].plotly_chart(fig, width="stretch")
    cc = st.columns(2)
    for col, k, title in ((cc[0], "moon_el", "Elevazione della Luna ai QSO (°)"), (cc[1], "mutual_spread_hz", "Spread mutuo ai QSO (Hz)")):
        v = [q["calc"].get(k) for q in qs if q.get("calc") and q["calc"].get(k) is not None]
        if v:
            fig = go.Figure(go.Histogram(x=v, nbinsx=20))
            fig.update_layout(title=title, height=300, margin=dict(l=10, r=10, t=40, b=10))
            col.plotly_chart(fig, width="stretch")


# ------------------------------------------------------------------ prints and database
def _prints_tab(D):
    from emelab import report
    stn = D.station()
    who = f"{stn.get('callsign') or ''} {stn.get('locator') or ''}".strip()
    st.subheader("Stampa in PDF")
    c = st.columns(3)
    if c[0].button("📒 Diario delle misure", key="pr_diary"):
        sets = {s["id"]: s for s in D.setups()}
        rows = D.measurements()
        for r in rows:
            ev = analysis.evaluate_measurement(r, sets[r["setup_id"]]) if r.get("setup_id") in sets else {}
            r["_y_exp"], r["_y_delta"] = ev.get("y_expected"), ev.get("y_delta")
            src = (r.get("calc") or {}).get("sun" if r["kind"] == "sun" else "moon") or {}
            r["_el"] = src.get("el")
        adv = []
        for s in sets.values():
            adv += [f"{s['name']}: {a}" for a in analysis.advice([r for r in rows if r.get("setup_id") == s["id"]], s)]
        _st.session_state["pr_pdf"] = ("diario_misure.pdf", report.diary_pdf(rows, who, adv))
    if c[1].button("📡 Log dei QSO con mappa", key="pr_log"):
        _st.session_state["pr_pdf"] = ("log_qso.pdf", report.log_pdf(D.qsos(), who))
    with c[2]:
        qs = D.qsos()
        pick = st.multiselect("QSO per le etichette QSL", [q["id"] for q in qs], key="pr_qsl_pick",
                              format_func=lambda i: next(f"{q['call']} {q['utc']:%Y-%m-%d} {q.get('band') or ''}" for q in qs if q["id"] == i))
        if st.button("🏷️ Etichette QSL", key="pr_qsl", disabled=not pick):
            sel = []
            for q in qs:
                if q["id"] in pick:
                    s = D.station_of(q["call"]) or {}
                    sel.append({**q, "name": q.get("name") or s.get("name"), "address": s.get("address")})
            _st.session_state["pr_pdf"] = ("etichette_qsl.pdf", report.qsl_labels_pdf(sel, stn.get("callsign") or "",
                                                                                     stn.get("locator") or ""))
    if _st.session_state.get("pr_pdf"):
        name, data = _st.session_state["pr_pdf"]
        st.download_button(f"⬇️ {name}", data, file_name=name, mime="application/pdf", type="primary")


def _database_tab(D):
    st.subheader("Database")
    st.caption(i18n.tr("Tutti i dati di EMELab sono in un unico file SQLite su questo PC") + f": `{D.path}`. " +
               i18n.tr("Puoi aprirlo anche con un programma come «DB Browser for SQLite»."))
    import pandas as pd
    tabs = {"measurements": "Misure", "qsos": "QSO", "stations": "Stazioni EME", "setups": "Configurazioni", "station": "Stazione"}
    t = st.selectbox("Tabella", list(tabs), format_func=lambda k: tabs[k], key="db_table")
    df = pd.read_sql_query(f"SELECT * FROM {t}", D.con)
    st.caption(i18n.tr("Righe") + f": {len(df)}")
    st.dataframe(df, hide_index=True, width="stretch")
    st.download_button("⬇️ Esporta CSV", df.to_csv(index=False), file_name=f"emelab_{t}.csv", mime="text/csv")


def _credits_tab():
    from emelab import credits
    credits.render(st)


# ------------------------------------------------------------------ chain design
_RX_DEFAULT = [{"Stadio": "Relè + guida", "Tipo": "passivo", "Guadagno (dB)": -0.3, "NF (dB)": 0.3},
               {"Stadio": "LNA", "Tipo": "attivo", "Guadagno (dB)": 20.0, "NF (dB)": 1.5},
               {"Stadio": "Cavo", "Tipo": "passivo", "Guadagno (dB)": -3.0, "NF (dB)": 3.0},
               {"Stadio": "Transverter", "Tipo": "attivo", "Guadagno (dB)": 15.0, "NF (dB)": 8.0}]
_TX_DEFAULT = [{"Stadio": "Driver", "Tipo": "attivo", "Guadagno (dB)": 20.0, "Psat (dBm)": 33.0, "P1dB (dBm)": 31.0, "V": 6.0, "A": 0.8},
               {"Stadio": "SSPA", "Tipo": "attivo", "Guadagno (dB)": 15.0, "Psat (dBm)": 43.0, "P1dB (dBm)": 41.0, "V": 24.0, "A": 4.0},
               {"Stadio": "Guida + relè", "Tipo": "passivo", "Guadagno (dB)": -0.5, "Psat (dBm)": None, "P1dB (dBm)": None, "V": None, "A": None}]


def _design_tab(D):
    import pandas as pd
    from emelab import chain, parts
    st.subheader("Progettazione della catena")
    st.caption("Ricezione: cifra di rumore e Tsys con la formula di Friis e il contributo di ogni stadio. Trasmissione: "
               "potenza al feed con la compressione degli amplificatori (modello di Rapp), consumo e calore.")
    c = st.columns(2)
    with c[0]:
        st.markdown("**Ricezione (dal feed al transverter)**")
        rx = st.data_editor(pd.DataFrame(_st.session_state.get("rx_tab", _RX_DEFAULT)), num_rows="dynamic", key="rx_ed",
                            hide_index=True, width="stretch")
        t_ant = st.number_input("Temperatura d'antenna (K)", 3.0, 500.0, 40.0, 1.0, key="ch_tant",
                                help="dal progetto FeedLab o dalla misura; cielo freddo + spillover")
        stages = [chain.passive(r["Stadio"], -float(r["Guadagno (dB)"])) if r["Tipo"] == "passivo" else
                  {"name": r["Stadio"], "gain_db": float(r["Guadagno (dB)"]), "nf_db": float(r["NF (dB)"])}
                  for r in rx.to_dict("records") if r.get("Stadio") and r.get("Guadagno (dB)") is not None]
        if stages:
            res = chain.rx_chain(stages, t_ant)
            m = st.columns(3)
            m[0].metric("NF del sistema", f"{res['nf_db']:.2f} dB")
            m[1].metric("Tsys", f"{res['tsys_K']:.0f} K")
            m[2].metric("Guadagno", f"{res['gain_db']:.1f} dB")
            fig = go.Figure(go.Bar(x=[s["name"] for s in res["stages"]], y=[s["added_K"] for s in res["stages"]],
                                   text=[f"{s['share_pct']:.0f} %" for s in res["stages"]], textposition="outside"))
            fig.update_layout(title="Kelvin aggiunti da ogni stadio (riferiti al feed)", height=300,
                              margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, width="stretch")
    with c[1]:
        st.markdown("**Trasmissione (dal transverter al feed)**")
        tx = st.data_editor(pd.DataFrame(_st.session_state.get("tx_tab", _TX_DEFAULT)), num_rows="dynamic", key="tx_ed",
                            hide_index=True, width="stretch")
        pin = st.number_input("Potenza in ingresso (dBm)", -30.0, 40.0, 10.0, 0.5, key="ch_pin")
        st_tx = []
        for r in tx.to_dict("records"):
            if not r.get("Stadio") or r.get("Guadagno (dB)") is None:
                continue
            if r["Tipo"] == "passivo":
                st_tx.append(chain.passive(r["Stadio"], -float(r["Guadagno (dB)"])))
            else:
                f = lambda k: None if r.get(k) is None or pd.isna(r.get(k)) else float(r[k])
                st_tx.append({"name": r["Stadio"], "gain_db": float(r["Guadagno (dB)"]), "psat_dbm": f("Psat (dBm)"),
                              "p1db_dbm": f("P1dB (dBm)"), "vdc": f("V"), "idc_a": f("A")})
        if st_tx:
            res = chain.tx_chain(pin, st_tx)
            m = st.columns(3)
            m[0].metric("Potenza al feed", f"{res['p_out_w']:.1f} W", help=f"{res['p_out_dbm']:.2f} dBm")
            m[1].metric("Consumo DC", f"{res['dc_w']:.0f} W")
            m[2].metric("Calore da dissipare", f"{res['heat_w']:.0f} W")
            st.dataframe(pd.DataFrame([{i18n.tr("Stadio"): s["name"], i18n.tr("Ingresso (dBm)"): round(s["p_in_dbm"], 2),
                                        i18n.tr("Uscita (dBm)"): round(s["p_out_dbm"], 2),
                                        i18n.tr("Margine dal P1dB (dB)"): None if s["p1db_margin_db"] is None else round(s["p1db_margin_db"], 1)}
                                       for s in res["stages"]]), hide_index=True, width="stretch")
    st.divider()
    st.subheader("Libreria dei componenti")
    st.caption("Componenti con i valori dei datasheet dei produttori (inseriti da te o trovati nel catalogo Mouser) e il "
               "link al datasheet. EMELab non inventa i valori: controlla sempre il datasheet alla tua frequenza.")
    rows = parts.all_parts(D)
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns=["id"]), hide_index=True, width="stretch")
    with st.expander("➕ Aggiungi un componente dal datasheet"):
        c = st.columns(4)
        p_part = c[0].text_input("Sigla", key="pt_part")
        p_maker = c[1].text_input("Produttore", key="pt_maker")
        p_type = c[2].selectbox("Tipo", list(parts.TYPES), format_func=lambda k: parts.TYPES[k], key="pt_type")
        p_ds = c[3].text_input("Link al datasheet", key="pt_ds")
        c = st.columns(8)
        vals = {k: c[i].number_input(lab, value=None, key=f"pt_{k}") for i, (k, lab) in enumerate(
            [("f_lo_ghz", "Da GHz"), ("f_hi_ghz", "A GHz"), ("gain_db", "Guadagno dB"), ("nf_db", "NF dB"),
             ("p1db_dbm", "P1dB dBm"), ("psat_dbm", "Psat dBm"), ("vdc", "V"), ("idc_a", "A")])}
        if st.button("💾 Salva componente", key="pt_save", disabled=not (p_part and p_maker)):
            parts.save(D, part=p_part, maker=p_maker, type=p_type, datasheet=p_ds or None, **vals)
            st.rerun()
    with st.expander("🔎 Cerca nel catalogo Mouser (chiave API personale)"):
        sets = openems_local.load_settings()
        c = st.columns(3)
        key = c[0].text_input("Chiave API Mouser (Search API)", sets.get("mouser_key", ""), type="password", key="ms_key",
                              help="gratuita su mouser.com (API Hub); resta salvata solo su questo PC")
        if c[0].button("💾 Salva chiave", key="ms_save"):
            openems_local.save_settings(mouser_key=key)
        kw = c[1].text_input("Cerca (es. «LNA 24 GHz», «GaN amplifier 10 GHz»)", key="ms_kw")
        if c[2].button("🔎 Cerca", key="ms_go", disabled=not (key and kw)):
            try:
                _st.session_state["ms_res"] = parts.mouser_search(key, kw)
            except Exception as e:
                st.error(f"Mouser: {e}")
        if _st.session_state.get("ms_res"):
            st.dataframe(pd.DataFrame(_st.session_state["ms_res"]), hide_index=True, width="stretch",
                         column_config={"datasheet": st.column_config.LinkColumn("Datasheet"),
                                        "mouser": st.column_config.LinkColumn("Mouser")})
            st.caption("Apri il datasheet, leggi i valori alla tua frequenza e aggiungi il componente alla libreria.")
