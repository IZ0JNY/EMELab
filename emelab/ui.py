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
def _bl(band) -> str:
    """Band as shown everywhere: «10GHz», «24GHz»… (internal keys "10G" and ADIF bands stay unchanged)."""
    from emelab.stations import band_label
    return band_label(band)


def _bsk(label):
    from emelab.stations import band_sort_key
    return band_sort_key(label)


def _bands_text(bands) -> str:
    """«10GHz, 24GHz» from band keys, in frequency order."""
    return ", ".join(sorted((_bl(b) for b in bands), key=_bsk))


BANDS = {"10GHz": 10.368, "24GHz": 24.048, "47GHz": 47.088}


def _db():
    """A fresh connection at every run (Streamlit reruns on other threads; opening SQLite costs ~1 ms)."""
    return edb.DB()


def _fmt(v, f="{:.2f}"):
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f.format(v)


# ------------------------------------------------------------------ station and setups
def _noaa_cb(lon):
    from emelab import solar
    try:
        b = solar.best_15g4(solar.rstn(), lon)
        if not b:
            _st.session_state["em_noaa_msg"] = ("warn", i18n.tr("Nessun valore a 15.4 GHz di buona qualità nelle ultime 36 ore."))
            return
        _st.session_state["em_flux"] = float(b["sfu"])
        x = solar.xray_status()
        msg = (f"{b['sfu']:.0f} SFU · {b['site']} {b['utc']:%Y-%m-%d %H:%M} UTC · GOES {x.get('now', '?')} "
               f"(max 12 h {x.get('max', '?')}) — " + i18n.tr(x.get("advice", "")))
        _st.session_state["em_noaa_msg"] = ("ok" if x.get("ok") else "warn", msg)
    except Exception as e:
        _st.session_state["em_noaa_msg"] = ("err", i18n.tr("NOAA non raggiungibile") + f": {e}")


def _loc_cb():
    """locator typed → latitude and longitude follow (centre of the square)"""
    try:
        _st.session_state["em_lat"], _st.session_state["em_lon"] = astro.locator_to_latlon(_st.session_state.get("em_loc", ""))
        _st.session_state["em_pos_msg"] = None
    except Exception:
        pass


def _latlon_cb():
    """latitude or longitude changed by hand → locator follows"""
    _st.session_state["em_loc"] = astro.latlon_to_locator(_st.session_state["em_lat"], _st.session_state["em_lon"], 6)


def _set_position(lat, lon, source):
    """position chosen on the map or pasted from Google Maps → latitude, longitude, locator and ground height"""
    ss = _st.session_state
    ss["em_lat"], ss["em_lon"] = round(lat, 6), round(lon, 6)
    ss["em_loc"] = astro.latlon_to_locator(lat, lon, 6)
    msg = i18n.tr(source) + f": {lat:.6f}, {lon:.6f} → {astro.latlon_to_locator(lat, lon, 10)}"
    try:
        h = weather.elevation(lat, lon)
        ss["em_h"] = float(round(h))
        ss["em_pos_msg"] = ("ok", msg + " · " + i18n.tr("quota del terreno") + f" {h:.0f} m (Open-Meteo)")
    except Exception:
        ss["em_pos_msg"] = ("warn", msg + " · " + i18n.tr("quota non trovata (serve internet): scrivila a mano"))


def _height_cb(lat, lon):
    try:
        h = weather.elevation(lat, lon)
        _st.session_state["em_h"] = float(round(h))
        _st.session_state["em_h_msg"] = ("ok", i18n.tr("quota del terreno") + f" {h:.0f} m (Open-Meteo)")
    except Exception as e:
        _st.session_state["em_h_msg"] = ("warn", i18n.tr("quota non trovata (serve internet): scrivila a mano") + f" — {str(e)[:120]}")


def _gmaps_cb():
    p = astro.parse_coords(_st.session_state.get("em_gmaps", ""))
    if p is None:
        _st.session_state["em_pos_msg"] = ("err", i18n.tr("Coordinate non riconosciute: in Google Maps fai clic destro sul "
                                                          "punto e poi clic sui numeri in alto per copiarli."))
        return
    _st.session_state["em_gmaps"] = ""
    _set_position(p[0], p[1], "Posizione presa da Google Maps")


def _osm_cb():
    v = _st.session_state.get("em_osm")
    if not isinstance(v, dict) or v.get("t") == _st.session_state.get("em_osm_t"):
        return
    _st.session_state["em_osm_t"] = v.get("t")
    try:
        _set_position(float(v["lat"]), float(v["lon"]), "Posizione presa dalla mappa")
    except (KeyError, TypeError, ValueError):
        pass


def _wx_test_cb():
    from emelab import weather
    url = (_st.session_state.get("em_wxurl") or "").strip()
    if not url:
        _st.session_state["em_wx_msg"] = ("warn", i18n.tr("Scrivi prima l'indirizzo della stazione meteo."))
        return
    try:
        d = weather.station_now(url)
        parts = [f"{d['t_c']:.1f} °C" if d.get("t_c") is not None else None,
                 f"{d['rh']:.0f} %" if d.get("rh") is not None else None,
                 f"{d['p_hpa']:.1f} hPa" if d.get("p_hpa") is not None else None]
        _st.session_state["em_wx_msg"] = ("ok", i18n.tr("Stazione meteo letta") + ": " + " · ".join(x for x in parts if x) +
                                          f" ({d.get('wx_utc', '')})" +
                                          (f" — file: {d['station_file']}"
                                           if d.get("station_file") and d["station_file"] != url else ""))
    except Exception as e:
        _st.session_state["em_wx_msg"] = ("err", i18n.tr("Stazione meteo non letta") + f": {str(e)[:300]}")


def _osm_map(D, lat, lon):
    """OpenStreetMap / terrain / satellite map (locator grid optional) with the station and the EME stations of the directory; a click sets the position"""
    from emelab import osm
    pts = []
    try:
        for x in D.stations():
            if x.get("locator") and x.get("eme"):
                try:
                    pts.append((*astro.locator_to_latlon(x["locator"]), x.get("call") or ""))
                except Exception:
                    pass
    except Exception:
        pass
    osm.station_map(lat, lon, bool(lat or lon), pts[-400:], height=480,
                    me_label=_st.session_state.get("em_call") or i18n.tr("la mia stazione"),
                    hint=i18n.tr("Clic sulla tua parabola per scegliere la posizione"),
                    layer_labels={"map": i18n.tr("Mappa"), "terrain": i18n.tr("Terreno"), "satellite": i18n.tr("Satellite"),
                                  "grid": i18n.tr("Griglia del locator")},
                    key="em_osm", on_change=_osm_cb)
    st.caption("Clic sul punto della parabola: latitudine, longitudine, locator e quota si aggiornano. In alto a destra "
               "scegli Mappa (OpenStreetMap), Terreno (OpenTopoMap) o Satellite (Esri World Imagery) e, se vuoi, la griglia "
               "del locator. Rotellina per lo zoom, trascina per spostare.")


def _station(D):
    stn = D.station()
    st.subheader("Stazione")
    ss = _st.session_state
    if "em_lat" not in ss:                       # first draw: from the database, or from the locator
        lat0, lon0 = stn.get("lat"), stn.get("lon")
        if (lat0 is None or (not lat0 and not lon0)) and stn.get("locator"):
            try:
                lat0, lon0 = astro.locator_to_latlon(stn["locator"])
            except Exception:
                pass
        ss["em_lat"], ss["em_lon"] = float(lat0 or 0.0), float(lon0 or 0.0)
    ss.setdefault("em_loc", stn.get("locator") or "")
    left, right = st.columns([1, 1])
    with left:
        c = st.columns(2)
        call = c[0].text_input("Nominativo", stn.get("callsign") or "", key="em_call")
        loc = c[1].text_input("Locator", key="em_loc", on_change=_loc_cb,
                              help="es. JN61fs: latitudine e longitudine vanno al centro del quadrato. Per la posizione esatta "
                                   "fai clic sulla mappa o usa Google Maps")
        c = st.columns(2)
        lat = c[0].number_input("Latitudine (°, nord +)", -90.0, 90.0, step=0.0001, format="%.6f", key="em_lat",
                                on_change=_latlon_cb)
        lon = c[1].number_input("Longitudine (°, est +)", -180.0, 180.0, step=0.0001, format="%.6f", key="em_lon",
                                on_change=_latlon_cb)
        st.markdown(i18n.tr("Locator preciso") + f": **{astro.latlon_to_locator(lat, lon, 10)}**" +
                    f" · {astro.latlon_to_locator(lat, lon, 6)}")
        with st.container(border=True):
            st.markdown("**" + i18n.tr("📍 Posizione da Google Maps") + "**")
            g = st.columns([1, 2])
            g[0].link_button("🗺️ Apri Google Maps", f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},17z/data=!3m1!1e3"
                             if (lat or lon) else "https://www.google.com/maps")
            g[1].text_input("Incolla qui le coordinate o il link", key="em_gmaps", on_change=_gmaps_cb,
                            placeholder="41.64581, 12.62503", label_visibility="collapsed")
            st.caption("In Google Maps fai clic destro sulla tua parabola: le coordinate compaiono in alto nel menu, un clic "
                       "le copia. Incollale qui e premi Invio: latitudine, longitudine e locator si aggiornano. Va bene anche "
                       "il link della pagina.")
            if ss.get("em_pos_msg"):
                kind, msg = ss["em_pos_msg"]
                (st.success if kind == "ok" else st.warning if kind == "warn" else st.error)(msg)
    with right:
        _osm_map(D, lat, lon)
    c = st.columns(4)
    ss.setdefault("em_h", float(stn.get("height_m") or 0.0))
    if not ss["em_h"] and (lat or lon) and not ss.get("em_h_auto"):
        ss["em_h_auto"] = True                   # height still 0 with a known position: ask once per session
        try:
            ss["em_h"] = float(round(weather.elevation(lat, lon)))
        except Exception:
            pass
    h = c[0].number_input("Quota (m s.l.m.)", -100.0, 5000.0, step=1.0, key="em_h",
                          help="si riempie da sola dopo un clic sulla mappa o le coordinate di Google Maps (quota del terreno "
                               "da Open-Meteo, modello Copernicus a 90 m): correggila se serve")
    c[0].button("⛰️ Quota dal punto", key="em_h_get", on_click=_height_cb, args=(lat, lon), disabled=not (lat or lon),
                help="chiede a Open-Meteo la quota del terreno nel punto di latitudine e longitudine qui sopra")
    if ss.get("em_h_msg"):
        kind, msg = ss["em_h_msg"]
        (c[0].success if kind == "ok" else c[0].warning)(msg)
    sets = openems_local.load_settings()
    url = c[1].text_input("Stazione meteo personale (facoltativa)", sets.get("emelab_wx_url", ""), key="em_wxurl",
                          help="indirizzo del tuo sito Meteotemplate / Cumulus / Weather Display, oppure del file dati. "
                               "Resta salvato solo su questo PC")
    c[1].button("🌡️ Prova la stazione meteo", key="em_wxtest", on_click=_wx_test_cb,
                help="legge adesso temperatura, umidità e pressione dall'indirizzo scritto sopra")
    flux = c[2].number_input("Flusso solare a 15.4 GHz (SFU)", 300.0, 3000.0, float(sets.get("emelab_flux", 550.0)), 10.0,
                             key="em_flux", help="valore del giorno dagli osservatori RSTN (San Vito, Learmonth, Sagamore "
                                                 "Hill, Palehua) pubblicato da NOAA SWPC; serve per il rumore solare atteso")
    c[2].button("📡 Prendi da NOAA", key="em_noaa", on_click=_noaa_cb, args=(lon,),
                help="valore di oggi a 15.4 GHz dall'osservatorio RSTN più vicino in longitudine (San Vito per l'Europa) "
                     "e stato dei brillamenti GOES")
    if _st.session_state.get("em_noaa_msg"):
        kind, msg = _st.session_state["em_noaa_msg"]
        (st.success if kind == "ok" else st.warning if kind == "warn" else st.error)(msg)
    if _st.session_state.get("em_wx_msg"):
        kind, msg = _st.session_state["em_wx_msg"]
        (st.success if kind == "ok" else st.warning if kind == "warn" else st.error)(msg)
    if c[3].button("💾 Salva stazione", key="em_save_st"):
        D.save_station(callsign=call.strip().upper(), locator=loc.strip(), lat=lat, lon=lon, height_m=h)
        openems_local.save_settings(emelab_wx_url=url.strip(), emelab_flux=flux)
        st.success("Stazione salvata (solo su questo PC).")
    _horizon_editor("stn_hz")
    st.caption("Tutti i dati di EMELab (stazione, configurazioni, misure, indirizzo della stazione meteo) restano in un file sul "
               "tuo PC e non vengono mai inviati. Escono solo le richieste a internet: il meteo riceve coordinate e ora, la "
               "mappa scarica le immagini da OpenStreetMap, OpenTopoMap o Esri (che vedono la zona mostrata), la quota riceve solo il punto "
               "della stazione (Open-Meteo). Senza internet la mappa resta vuota: scrivi coordinate e quota a mano.")


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
        st.dataframe([{"ID": r["id"], "Nome": r["name"], "Banda": _bl(r["band_ghz"]), "Parabola (m)": r.get("D_m"),
                       "Guadagno (dBi)": round(r.get("gain_dbi", 0), 2), "Efficienza (%)": round(100 * r.get("eta_ap", 0), 1),
                       "Taper (dB)": round(r.get("edge_taper_db", 0), 1), "NF (dB)": r.get("nf_db"),
                       "Perdite (dB)": r.get("line_loss_db"), "TX (W)": r.get("tx_w"), "Origine": r.get("source")}
                      for r in rows], hide_index=True, width="stretch")
        dl = st.selectbox("Elimina configurazione", [None] + [r["id"] for r in rows], key="em_del_setup",
                          format_func=lambda i: "—" if i is None else next(r["name"] for r in rows if r["id"] == i))
        if dl and st.button("🗑️ Elimina", key="em_del_setup_btn"):
            D.delete_setup(dl)
            st.rerun()
    _history_editor(D)


def _lang_key() -> str:
    """Suffix for the keys of editable tables, whose headers change with the language."""
    return "" if i18n.get_lang() == "it" else "_" + i18n.get_lang()


def _editor_rows(rows):
    """An editable table shown in the current language (headers and words); _editor_back reads it back in Italian."""
    import pandas as pd
    if i18n.get_lang() == "it":
        return pd.DataFrame(rows)
    return pd.DataFrame([{i18n.tr(k): (i18n.tr(v) if isinstance(v, str) else v) for k, v in r.items()} for r in rows])


def _blank_cols(df):
    """Number columns with empty cells become text columns: the editor shows a blank there, never "None".
    Returns the table and the column_config that keeps those columns editable; _num reads them back."""
    import pandas as pd
    cfg = {}
    for c in df.columns:
        v = df[c]
        if v.isna().any() and not v.dropna().map(lambda x: isinstance(x, str)).any():
            df[c] = v.map(lambda x: "" if x is None or pd.isna(x) else f"{x:g}").astype(object)
            cfg[c] = _st.column_config.TextColumn(c, alignment="right")
    return df, cfg


def _num(v):
    """A number typed in an editable table (float, text or empty) → float, or None when empty or not a number."""
    try:
        f = float(str(v).replace(",", ".")) if v is not None and str(v).strip() not in ("", "None", "nan") else None
    except ValueError:
        return None
    return None if f is None or f != f else f


def _editor_back(ed, cols):
    if i18n.get_lang() == "it":
        return ed.to_dict("records")
    names = {i18n.tr(c): c for c in cols}
    kinds = {i18n.tr(k): k for k in ("passivo", "attivo")}
    return [{names.get(k, k): (kinds.get(v, v) if names.get(k) == "Tipo" else v) for k, v in r.items()}
            for r in ed.to_dict("records")]


def _history_editor(D):
    import pandas as pd
    from emelab import dx
    st.divider()
    st.subheader("📜 Storico della stazione")
    st.caption("Quale parabola, potenza e ricevitore hai usato su ogni banda e da quando. EMELab usa il periodo giusto per "
               "ogni QSO quando confronta i rapporti con la teoria e impara la correzione della tua stazione periodo per "
               "periodo. Ogni riga vale dalla sua data fino alla riga successiva.")
    band = st.selectbox("Banda", list(dx.BAND_GHZ), key="hist_band", format_func=_bl)
    rows = D.history(band)
    df = pd.DataFrame([{"Dal (data)": (r["from_utc"] or "")[:10], "Parabola (m)": r.get("dish_m"),
                        "Tipo": "offset" if r.get("dish_kind") == "offset" else "fuoco primario",
                        "Efficienza (%)": round(100 * r["eta"], 1) if r.get("eta") else None, "Potenza al feed (W)": r.get("power_w"),
                        "NF ricevitore (dB)": r.get("nf_db"), "Perdite prima dell'LNA (dB)": r.get("line_loss_db"),
                        "Polarizzazione": r.get("pol") or "V", "Note": r.get("notes") or ""} for r in rows]
                      or [{"Dal (data)": "", "Parabola (m)": None, "Tipo": "offset", "Efficienza (%)": None,
                           "Potenza al feed (W)": None, "NF ricevitore (dB)": None, "Perdite prima dell'LNA (dB)": None,
                           "Polarizzazione": "V", "Note": ""}])
    names = {c: i18n.tr(c) for c in df.columns}              # headers in the current language, read back in Italian
    prime = i18n.tr("fuoco primario")
    if i18n.get_lang() != "it":
        df = df.rename(columns=names).replace({names["Tipo"]: {"fuoco primario": prime}})
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key=f"hist_ed_{band}" + _lang_key(),
                        column_config={names["Dal (data)"]: st.column_config.TextColumn(help=i18n.tr("AAAA-MM-GG (UTC)")),
                                       names["Tipo"]: st.column_config.SelectboxColumn(options=["offset", prime]),
                                       names["Polarizzazione"]: st.column_config.SelectboxColumn(options=["V", "H", "HV"])})
    if i18n.get_lang() != "it":
        ed = ed.rename(columns={v: k for k, v in names.items()})
    if st.button("💾 Salva lo storico della banda", key="hist_save"):
        out, bad = [], []
        for r in ed.to_dict("records"):
            d = str(r.get("Dal (data)") or "").strip()
            if not d:
                continue
            try:
                t = datetime.fromisoformat(d[:10]).replace(tzinfo=timezone.utc)
            except ValueError:
                bad.append(d)
                continue
            num = lambda k: None if r.get(k) is None or (isinstance(r.get(k), float) and r.get(k) != r.get(k)) else float(r[k])
            out.append({"from_utc": t, "dish_m": num("Parabola (m)"), "dish_kind": "offset" if r.get("Tipo") == "offset" else "prime",
                        "eta": (num("Efficienza (%)") or 0) / 100 or None, "power_w": num("Potenza al feed (W)"),
                        "nf_db": num("NF ricevitore (dB)"), "line_loss_db": num("Perdite prima dell'LNA (dB)"),
                        "pol": r.get("Polarizzazione") or None, "notes": r.get("Note") or None})
        if bad:
            st.error(i18n.tr("Date non valide (usa AAAA-MM-GG)") + ": " + ", ".join(bad))
        else:
            D.save_history(band, out)
            _st.session_state.pop("em_off_key", None)
            st.success("Storico salvato.")


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
            tab.append({"ID": r["id"], "UTC": r["utc"].replace("T", " ").replace("Z", ""), "Banda": _bl(r["band_ghz"]), "Tipo": edb.KINDS.get(r["kind"], r["kind"]),
                        "Y (dB)": r["y_db"], "Y atteso": _r(ev.get("y_expected")), "ΔY": _r(ev.get("y_delta")),
                        "G/T misurato": _r(ev.get("gt_measured")), "ΔG/T": _r(ev.get("gt_delta")), "SNR": r["snr_db"],
                        "SNR atteso": _r(ev.get("snr_expected")), "EL": _r(src.get("el")), "AZ": _r(src.get("az")),
                        "°C": r["t_c"], "UR %": r["rh"], "hPa": r["p_hpa"], "Meteo": r["wx_source"], "Note": r["notes"] or ""})
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
        c[1].download_button("⬇️ Esporta CSV", D.export_csv(), mime="text/csv",
                             file_name="emelab_misure.csv" if i18n.get_lang() == "it" else "emelab_measurements.csv")
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
def _planner_tab(D):
    """One Planner: configuration, Q65 mode, other station and weather chosen once at the top; below, the signal
    of the day (default), the Moon windows of the next days and who you can work."""
    from emelab import dx
    st.subheader("Pianificatore")
    st.caption("Equazione radar bistatica con la distanza reale della Luna da entrambe le stazioni, la parte di Luna "
               "illuminata da entrambi i fasci, l'atmosfera ai due capi e il rumore di chi riceve puntato sulla Luna. "
               "Soglie Q65 di G3WDG contro il mutual spread. Dati delle altre stazioni dalla EME Directory; dove mancano, "
               "valori tipici della banda (indicati come ipotesi). EMELab corregge il modello con i rapporti dei tuoi QSO.")
    stn = D.station()
    sets = D.setups()
    if not sets or not stn.get("lat"):
        st.info("Servono stazione e configurazione.")
        return
    c = st.columns([3, 2, 3, 2])
    sid = c[0].selectbox("Configurazione", [s["id"] for s in sets], key="em_p_setup",
                         format_func=lambda i: next(f"{s['name']} ({_bl(s['band_ghz'])})" for s in sets if s["id"] == i))
    setup = next(s for s in sets if s["id"] == sid)
    band = _band_of_setup(setup)
    sets_l = openems_local.load_settings()
    std = dx.Q65_STANDARD.get(band, "60E")
    cur = dx.band_mode(band, sets_l)
    q65 = c[1].selectbox(f"Modo Q65 su {_bl(band)}", list(dx.Q65_MODES), index=list(dx.Q65_MODES).index(cur),
                         key=f"sg_q65_{band}",
                         format_func=lambda k: f"Q65-{k}" + (" (" + i18n.tr("standard della banda") + ")" if k == std else ""),
                         help="Soglie e margini sono calcolati per questo sottomodo. Di solito 60D a 10 GHz e 60E da 24 GHz in "
                              "su. La scelta viene ricordata per la banda.")
    if q65 != cur:
        openems_local.save_settings(q65_modes={**(sets_l.get("q65_modes") or {}), band: q65})
    with c[2]:
        pcall, ploc = _planner_partner(D)
    use_fc = c[3].checkbox("Usa le previsioni meteo", True, key="em_p_fc",
                           help="previsioni Open-Meteo (16 giorni) da te e, dal suo locator, dalla stazione corrispondente: "
                                "umidità e pioggia cambiano l'attenuazione a 10/24 GHz, il vento il puntamento")
    dxs = None
    if ploc and stn_loc_ok(ploc):
        dxs = {"call": pcall, "locator": ploc.upper(), "loc": astro.locator_to_latlon(ploc)}
    sub = ["📶 Segnale", "🗓️ Finestre", "🏆 Chi posso collegare"]
    try:
        tabs = st.tabs(sub, key="pl_sub", on_change="rerun", default=i18n.tr(sub[0]))
    except TypeError:
        tabs = st.tabs(sub)
    with tabs[0]:
        _signal_view(D, stn, setup, band, q65, dxs, use_fc)
    with tabs[1]:
        _planner(D, stn, setup, pcall, ploc, use_fc)
    with tabs[2]:
        _rank_view(D, stn, setup, band, q65)


def stn_loc_ok(loc: str) -> bool:
    from emelab import stations as stns
    return bool(stns.LOC_RX.match((loc or "").strip()))


def _planner(D, stn, setup, pcall, ploc, use_fc):
    """The Moon windows of the next days, with the other station chosen at the top."""
    c = st.columns(3)
    days = c[0].number_input("Giorni", 1, 60, 14, key="em_p_days")
    min_el = c[1].number_input("Elevazione minima (°)", 0.0, 60.0, 10.0, 1.0, key="em_p_minel",
                               help="sotto i 10–15° a 24/47 GHz l'atmosfera e il rumore di terra pesano molto")
    run_now = c[2].button("🗓️ Calcola", type="primary", key="em_p_go")
    if _st.session_state.pop("em_p_auto", False):        # opened from «Chi posso collegare»: compute straight away
        run_now = True
    if run_now:
        partner = None
        if ploc.strip():
            try:
                partner = astro.locator_to_latlon(ploc)
            except Exception:
                st.warning("Locator non valido.")
        _st.session_state["em_plan_dx"] = ({"call": pcall, "locator": ploc.strip().upper(), "loc": partner}
                                           if partner else None)
        series = None
        if use_fc:
            try:
                series = weather.open_meteo_series(stn["lat"], stn["lon"], datetime.now(timezone.utc), min(int(days), 16))
            except Exception as e:
                st.warning(i18n.tr("Previsioni non disponibili") + f": {e}")
        series_dx = None
        if use_fc and partner:
            try:
                series_dx = weather.open_meteo_series(partner[0], partner[1], datetime.now(timezone.utc), min(int(days), 16))
            except Exception as e:
                st.warning(i18n.tr("Previsioni non disponibili") + f": {e}")
        with st.spinner("Calcolo delle finestre…"):
            smp = planner.windows(stn, setup, datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0),
                                  int(days), 15, min_el, partner, series, horizon=_my_horizon())
        rows = planner.daily(smp)
        if partner and rows:
            with st.spinner("Probabilità di QSO…"):
                _planner_qso(D, stn, setup, rows, _st.session_state["em_plan_dx"])
        if series or series_dx:
            for r in rows:
                r["wx"] = planner.weather_quality(float(setup["band_ghz"]), r, series, series_dx, partner)
        _st.session_state["em_plan"] = (smp, rows)
    if _st.session_state.get("em_plan"):
        smp, rows = _st.session_state["em_plan"]
        if not rows:
            st.info("Nessuna finestra nel periodo con questi limiti.")
            return
        dx_shown = _st.session_state.get("em_plan_dx")
        if dx_shown:
            st.caption(i18n.tr("Finestre con la Luna visibile da te e da") + " **"
                       + " · ".join(x for x in (dx_shown["call"], dx_shown["locator"]) if x) + "**")
            _planner_now(D, stn, setup, dx_shown)
        best = planner_best_rows(rows, SUN_MOON_WARN_DEG)
        st.caption("👆 " + i18n.tr("Clicca una riga per vedere quel passaggio ogni 30 minuti."))
        pick = _planner_table([{"Migliore": "✅" if b else "", "Inizio (UTC)": r["start"].strftime("%Y-%m-%d %H:%M"), "Fine (UTC)": r["end"].strftime("%Y-%m-%d %H:%M"),
                       "Ore": round(r["hours"], 1), **_qso_cols(r, dx_shown), "Momento migliore (UTC)": r["best_utc"].strftime("%Y-%m-%d %H:%M"),
                       "EL max (°)": round(r["best_el"], 1), "Distanza (km)": round(r["dist_km"]),
                       "Eco SNR 1 Hz (dB)": _r(r["snr_1hz"], 1), "Eco SNR nell'allargamento (dB)": _r(r["snr_spread"], 1),
                       "Allargamento (Hz)": round(r["spread_hz"]), "Attenuazione (dB)": round(r["a_slant_db"], 2),
                       "Sole–Luna min (°)": f"{r['sun_moon_deg']:.1f}" + (" ⚠️" if r["sun_moon_deg"] < SUN_MOON_WARN_DEG else ""),
                       **({"Meteo": i18n.tr(r["wx"]["label"]), "Pioggia da te (%)": r["wx"].get("pp_me"),
                           "Pioggia DX (%)": r["wx"].get("pp_dx"), "Raffiche da te (m/s)": r["wx"].get("gust_me"),
                           "Atmosfera totale (dB)": r["wx"].get("atm_total_db")} if r.get("wx") else {})}
                      for r, b in zip(rows, best)], [r["sun_moon_deg"] < SUN_MOON_WARN_DEG for r in rows], best)
        if pick is not None:
            _planner_detail(D, stn, setup, smp, rows[pick], dx_shown)
        if dx_shown and any("qso" in r for r in rows):
            st.caption("Probabilità di QSO in Q65, nei due sensi, nel momento migliore del passaggio (stesso modello di "
                       "«Chi posso collegare», con la correzione appresa dai tuoi QSO). «Momento migliore (UTC)» resta "
                       "quello delle tue eco.")
            if dx_shown.get("assumed"):
                st.markdown(f"<span style='color:{ASSUMED_COLOR}'>" + i18n.tr("presunto") + "</span>: "
                            + ", ".join(i18n.tr(a) for a in dx_shown["assumed"]), unsafe_allow_html=True)
        if any(r.get("wx") for r in rows):
            st.caption("Meteo: ✅ buone, ⚠️ discrete, ❌ sconsigliate — probabilità di pioggia, raffiche di vento (puntamento) "
                       "e attenuazione atmosferica ai due capi all'ora migliore, dalle previsioni Open-Meteo.")
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


SUN_MOON_WARN_DEG = 10.0      # below this the Sun is in or near the beam: much more noise, echoes and QSOs suffer

PLANNER_HELP = {
    "Migliore": "✅ e riga verde = i passaggi più favorevoli: con una stazione scelta quelli con il margine di QSO più "
                "alto (entro 1 dB dal migliore), altrimenti quelli con le tue eco più forti nell'allargamento (entro 1 dB "
                "dal migliore). Mai con il Sole a meno di 10° dalla Luna o con il meteo sconsigliato.",
    "Inizio (UTC)": "quando la Luna sale sopra l'elevazione minima e il tuo orizzonte libero (e, se hai scelto una "
                    "stazione, sopra il suo orizzonte)",
    "Fine (UTC)": "quando la Luna scende sotto l'elevazione minima o dietro i tuoi ostacoli",
    "Probabilità QSO": "probabilità stimata di completare un QSO in Q65 con la stazione scelta, nel suo momento migliore "
                       "del passaggio: stesso modello di «Chi posso collegare», corretto con i rapporti dei tuoi QSO",
    "Momento migliore QSO (UTC)": "l'istante del passaggio con il margine più alto sulla soglia Q65, nei due sensi",
    "Ora locale DX": "che ore sono dalla stazione corrispondente nel momento migliore del QSO (fuso orario dal locator; "
                     "con * è l'ora solare, presunta)",
    "Luna da te AZ/EL (°)": "dove punti tu nel momento migliore del QSO: azimut / elevazione della Luna",
    "Luna dal DX AZ/EL (°)": "dove punta la stazione corrispondente nel momento migliore del QSO: azimut / elevazione",
    "Momento migliore (UTC)": "l'istante del passaggio con le tue eco più forti (Sole lontano dalla Luna)",
    "EL max (°)": "elevazione più alta della Luna nel passaggio, vista da te",
    "Eco SNR 1 Hz (dB)": "rapporto segnale/rumore atteso delle tue eco in 1 Hz di banda, nel momento migliore",
    "Eco SNR nell'allargamento (dB)": "SNR delle eco su tutta la larghezza dell'allargamento Doppler (libration spread)",
    "Allargamento (Hz)": "quanto la Luna allarga in frequenza le tue eco (libration spread) nel momento migliore",
    "Attenuazione (dB)": "attenuazione dell'atmosfera (vapore e ossigeno) lungo il percorso verso la Luna nel momento "
                         "migliore, per un solo attraversamento",
    "Sole–Luna min (°)": "distanza angolare più piccola tra Sole e Luna durante il passaggio. Se il Sole è vicino alla Luna "
                         "entra nel fascio dell'antenna o nei lobi laterali e il rumore sale molto: sotto i 10° ⚠️ eco e "
                         "QSO peggiorano, sotto 2–3° (circa la Luna nuova) sono quasi impossibili",
}


def _planner_help() -> dict:
    """The (?) tooltips on the planner table's columns (keys as shown, i.e. translated)."""
    return {i18n.tr(k): _st.column_config.Column(help=i18n.tr(v)) for k, v in PLANNER_HELP.items()}


def planner_best_rows(rows: list[dict], sun_min: float, within_db: float = 1.0) -> list[bool]:
    """The most favourable passes: with another station the highest QSO margin, otherwise your strongest echoes in
    the spreading; every pass within within_db of the best one counts, but never with the Sun too close to the Moon
    or with the weather advised against."""
    def score(r):
        if "qso" in r:
            return (r["qso"] or {}).get("margin_db")
        return r["snr_spread"] if r.get("snr_spread") is not None else (-r["a_slant_db"] if r.get("a_slant_db") is not None else None)
    ok = [r["sun_moon_deg"] >= sun_min and "sconsigliate" not in ((r.get("wx") or {}).get("label") or "") and score(r) is not None
          for r in rows]
    top = max((score(r) for r, k in zip(rows, ok) if k), default=None)
    return [bool(k and top is not None and score(r) >= top - within_db) for r, k in zip(rows, ok)]


def _planner_detail(D, stn, setup, smp, row, dxs, step_min: int = 30):
    """One pass every step_min minutes: where the Moon is from both stations, the local times, echoes, spread,
    Sun–Moon distance and, with another station, the QSO probability and the signals both ways."""
    from emelab import dx, tz
    st.markdown("#### 🔎 " + i18n.tr("Passaggio") + f" {row['start']:%Y-%m-%d %H:%M} → {row['end']:%H:%M} UTC · "
                + i18n.tr("ogni 30 minuti"))
    pts = [s for s in smp if row["start"] <= s["utc"] <= row["end"]
           and ((s["utc"] - row["start"]).total_seconds() / 60) % step_min == 0]
    ctx = _planner_link_ctx(D, stn, setup) if dxs else None
    model = _planner_dx_model(D, ctx[0], dxs["call"], dxs["locator"])[0] if dxs else None
    out, close = [], []
    for s in pts:
        lt_me = tz.local_time(stn["lat"], stn["lon"], s["utc"])
        d = {"UTC": s["utc"].strftime("%H:%M"), "Ora locale (te)": lt_me[0].strftime("%H:%M") + ("*" if lt_me[2] else ""),
             "Luna da te AZ/EL (°)": f"{s['az']:.0f} / {s['el']:.0f}"}
        if dxs:
            band, me, my_loc, offset, mode = ctx
            mb = planner.moon_both(s["utc"], my_loc, dxs["loc"], stn.get("height_m") or 0.0)
            lt = tz.local_time(dxs["loc"][0], dxs["loc"][1], s["utc"])
            k = dx.link_at(s["utc"], me, my_loc, model, dxs["loc"], band, h_a=stn.get("height_m") or 0.0, mode=mode)
            d.update({"Ora locale DX": lt[0].strftime("%H:%M") + ("*" if lt[2] else ""),
                      "Luna dal DX AZ/EL (°)": f"{mb['az_dx']:.0f} / {mb['el_dx']:.0f}",
                      "Probabilità QSO": f"{100 * dx.probability(k['margin_db'], offset):.0f} %" if k else "–",
                      "Lo ricevi a (dB)": round(k["snr_a_hears_b"] + offset, 1) if k else None,
                      "Ti riceve a (dB)": round(k["snr_b_hears_a"], 1) if k else None,
                      "Margine (dB)": round(k["margin_db"] + offset, 1) if k else None})
        d.update({"Eco SNR 1 Hz (dB)": _r(s["snr_1hz"], 1), "Allargamento (Hz)": round(s["spread_hz"]),
                  "Attenuazione (dB)": round(s["a_slant_db"], 2), "Sole–Luna (°)": round(s["sun_moon_deg"], 1)})
        out.append(d)
        close.append(s["sun_moon_deg"] < SUN_MOON_WARN_DEG)
    if not out:
        st.info("Nessun punto in questo passaggio.")
        return
    import pandas as pd
    df = pd.DataFrame(out)
    df.columns = [i18n.tr(c) for c in df.columns]
    bg = pd.DataFrame("", index=df.index, columns=df.columns)
    key = "Margine (dB)" if dxs else "Eco SNR 1 Hz (dB)"
    vals = [o.get(key) for o in out]
    top = max((v for v, c in zip(vals, close) if v is not None and not c), default=None)
    for i, (v, c) in enumerate(zip(vals, close)):
        if top is not None and v is not None and not c and v >= top - 1.0:
            bg.iloc[i, :] = BEST_ROW_CSS
        if c:
            bg.iloc[i, df.columns.get_loc(i18n.tr("Sole–Luna (°)"))] = SUN_MOON_WARN_CSS
    _st.dataframe(df.style.apply(lambda _: bg, axis=None).format(lambda v: f"{v:g}" if isinstance(v, float) else v),
                  hide_index=True, width="stretch", column_config={
                      i18n.tr("Ora locale (te)"): _st.column_config.Column(help=i18n.tr("la tua ora locale (fuso orario dal locator)")),
                      **_planner_help()})
    st.caption("Righe verdi: i momenti migliori del passaggio (entro 1 dB dal margine di QSO più alto, o dalle eco più "
               "forti se non hai scelto una stazione). Solo i momenti con la Luna sopra il tuo orizzonte libero.")


def _planner_table(data: list[dict], sun_close: list[bool], best: list[bool]):
    """The planner table: (?) on every column header, and the Sun–Moon cell coloured where the Sun is too close
    to the Moon, with the warning shown when the mouse is over that cell."""
    import pandas as pd
    df = pd.DataFrame(data)
    col = "Sole–Luna min (°)"
    df.columns = [i18n.tr(c) for c in df.columns]
    tcol = i18n.tr(col)
    tip = i18n.tr("Sole troppo vicino alla Luna: il Sole entra nel fascio o nei lobi laterali e il rumore sale molto, "
                  "eco e QSO peggiorano. Meglio un altro passaggio.")
    bg = pd.DataFrame("", index=df.index, columns=df.columns)
    for i, b in enumerate(best):
        if b:
            bg.iloc[i, :] = BEST_ROW_CSS
    for i, close in enumerate(sun_close):
        if close:
            bg.iloc[i, df.columns.get_loc(tcol)] = SUN_MOON_WARN_CSS
    sty = df.style.apply(lambda _: bg, axis=None).format(lambda v: f"{v:g}" if isinstance(v, float) else v)
    ev = _st.dataframe(sty, hide_index=True, width="stretch", column_config=_planner_help(), key="em_p_table",
                       on_select="rerun", selection_mode=["single-row", "single-cell"])
    if any(sun_close):
        st.warning("⚠️ " + tip)
    sel = getattr(ev, "selection", None) or {}
    rows = list(sel.get("rows") or []) + [c[0] if isinstance(c, (list, tuple)) else c.get("row")
                                          for c in sel.get("cells") or []]
    rows = [i for i in rows if isinstance(i, int) and 0 <= i < len(data)]
    return rows[0] if rows else None


BEST_ROW_CSS = "background-color: rgba(46, 160, 67, 0.22)"
SUN_MOON_WARN_CSS = "background-color: rgba(229, 57, 53, 0.30); font-weight: 600"


def _my_horizon() -> list[dict] | None:
    """Your free horizon (saved in the Assistant or Station tab), or None when it was never set."""
    return openems_local.load_settings().get("horizon") or None


def _my_moon_ok(stn):
    """For dx.rank: is the Moon above your free horizon at each time (always True without a saved horizon)."""
    from emelab import wizard
    hz = _my_horizon()
    if not hz:
        return None
    return lambda times: [wizard.visible(hz, s.moon.az, s.moon.el) for s in
                          (astro.sky(t, stn["lat"], stn["lon"], stn.get("height_m") or 0.0) for t in times)]


PLANNER_TAB_LABEL = "🗓️ Pianificatore"


def _open_in_planner_kw(rk, setup, min_el) -> dict:
    """st.dataframe arguments that make a click on a row (or on one of its cells) of «Chi posso collegare» open the
    Planner with that station, the same configuration and minimum elevation, computed straight away."""
    n = _st.session_state.get("sg_rank_sel_n", 0)
    key = f"sg_rank_sel_{n}"
    return {"key": key, "on_select": lambda: _open_in_planner_cb(key, rk, setup, min_el),
            "selection_mode": ["single-row", "single-cell"]}


def _open_in_planner_cb(key, rk, setup, min_el):
    S = _st.session_state
    sel = (S.get(key) or {}).get("selection") or {}
    rows = list(sel.get("rows") or []) + [c[0] if isinstance(c, (list, tuple)) else c.get("row") for c in sel.get("cells") or []]
    rows = [i for i in rows if isinstance(i, int) and 0 <= i < len(rk)]
    if not rows:
        return
    r = rk[rows[0]]
    S["sg_rank_sel_n"] = S.get("sg_rank_sel_n", 0) + 1          # a fresh table next time: the click does not stick
    S["em_p_setup"] = setup["id"]
    S["em_p_minel"] = float(min_el)
    S["em_p_pcall"] = r["call"]
    S["em_p_auto"] = True
    if "planner" not in (S.get("tabs_on") or []):
        S["tabs_on"] = list(S.get("tabs_on") or []) + ["planner"]
    S["main_tab"] = i18n.tr(PLANNER_TAB_LABEL)
    S["pl_sub"] = i18n.tr("🗓️ Finestre")


def _planner_dx_model(D, band, call, loc):
    """The other station's model on this band: from the EME Directory (corrections by hand included) or, when it is
    not there, a typical 2.4 m dish with the band's typical power and receiver (assumed)."""
    from emelab import dx
    m = next((x for x in _dx_models(D, band) if x["call"] == call), None)
    if m:
        return m["model"], list(m["model"].get("assumed") or ())
    mod = dx.station(band, 2.4, None, "prime", assumed=("antenna 2.4 m",))
    return mod, list(mod["assumed"])


def _planner_link_ctx(D, stn, setup):
    from emelab import dx
    band = _band_of_setup(setup)
    me = _my_model(setup, band)
    my_loc = (stn["lat"], stn["lon"])
    off = _learned_offset(D, band, me, my_loc, _dx_models(D, band))
    return band, me, my_loc, (off["offset_db"] if off["n"] >= 5 else 0.0), dx.band_mode(band, openems_local.load_settings())


def _planner_qso(D, stn, setup, rows, dxs):
    band, me, my_loc, offset, mode = _planner_link_ctx(D, stn, setup)
    model, assumed = _planner_dx_model(D, band, dxs["call"], dxs["locator"])
    dxs["assumed"] = assumed
    planner.qso_chances(rows, me, my_loc, model, dxs["loc"], band, mode, offset, h_me=stn.get("height_m") or 0.0)


def _qso_cols(r, dxs) -> dict:
    """Planner table columns with the other station: QSO probability, its best moment, the time there and the Moon."""
    from emelab import tz
    if not dxs or "qso" not in r:
        return {}
    q = r["qso"]
    if not q:
        return {"Probabilità QSO": "–", "Momento migliore QSO (UTC)": "", "Ora locale DX": "",
                "Luna da te AZ/EL (°)": "", "Luna dal DX AZ/EL (°)": ""}
    lt, zn, ass = tz.local_time(dxs["loc"][0], dxs["loc"][1], q["utc"])
    return {"Probabilità QSO": f"{100 * q['probability']:.0f} %", "Momento migliore QSO (UTC)": q["utc"].strftime("%Y-%m-%d %H:%M"),
            "Ora locale DX": lt.strftime("%H:%M") + ("*" if ass else ""),
            "Luna da te AZ/EL (°)": f"{q['az_me']:.0f} / {q['el_me']:.0f}",
            "Luna dal DX AZ/EL (°)": f"{q['az_dx']:.0f} / {q['el_dx']:.0f}"}


def _planner_now(D, stn, setup, dxs):
    """Right now with the other station: time there, Moon from both, QSO probability if the Moon is up for both."""
    from emelab import dx, tz
    now = datetime.now(timezone.utc)
    band, me, my_loc, offset, mode = _planner_link_ctx(D, stn, setup)
    mb = planner.moon_both(now, my_loc, dxs["loc"], stn.get("height_m") or 0.0)
    lt, zn, ass = tz.local_time(dxs["loc"][0], dxs["loc"][1], now)
    model, _ = _planner_dx_model(D, band, dxs["call"], dxs["locator"])
    from emelab import wizard
    hz = _my_horizon()
    hidden = bool(hz) and not wizard.visible(hz, mb["az_me"], mb["el_me"])
    k = None if hidden else dx.link_at(now, me, my_loc, model, dxs["loc"], band, h_a=stn.get("height_m") or 0.0, mode=mode)
    m = st.columns(4)
    m[0].metric(i18n.tr("Ora locale da") + f" {dxs['call'] or dxs['locator']}", lt.strftime("%H:%M"),
                zn + (" · " + i18n.tr("presunto") if ass else ""), delta_color="off", delta_arrow="off")
    m[1].metric("Luna da te adesso (AZ/EL)", f"{mb['az_me']:.0f}° / {mb['el_me']:.0f}°")
    m[2].metric("Luna dal DX adesso (AZ/EL)", f"{mb['az_dx']:.0f}° / {mb['el_dx']:.0f}°")
    m[3].metric("Probabilità di QSO adesso", f"{100 * dx.probability(k['margin_db'], offset):.0f} %" if k else "–",
                None if k else i18n.tr("Luna dietro i tuoi ostacoli" if hidden else "Luna non visibile da entrambi"),
                delta_color="off", delta_arrow="off")


_DX_NONE, _DX_NEW = "", "\u2795"


def _planner_partner(D) -> tuple[str, str]:
    """The other station of the planner, chosen by callsign from the EME stations database (corrections by hand
    included); its locator comes from there. A callsign that is not there yet, or has no locator, takes a locator
    typed by hand, which can be kept in the database. Returns (callsign, locator), both "" when none is chosen."""
    from emelab import stations as stn
    rows = D.stations()
    loc_of = {r["call"]: (r.get("locator") or "").upper() for r in rows}
    man = {r["call"] for r in rows if "locator" in ((r.get("data") or {}).get("manual") or {})}

    def label(c):
        if c == _DX_NONE:
            return "— nessuna —"
        if c == _DX_NEW:
            return "➕ Altro nominativo o solo locator"
        return f"{c} · {loc_of[c]}" if loc_of.get(c) else f"{c} · ?"

    if "em_p_pcall_next" in _st.session_state:      # a station just added: pick it (before the widget exists)
        _st.session_state["em_p_pcall"] = _st.session_state.pop("em_p_pcall_next")
    call = st.selectbox("Stazione corrispondente", [_DX_NONE] + list(loc_of) + [_DX_NEW], key="em_p_pcall",
                        format_func=label,
                        help="scrivi il nominativo per cercarlo nelle Stazioni EME: il locator viene da lì. "
                             "Facoltativo: mostra solo le finestre in cui la Luna è visibile da entrambi")
    if call == _DX_NONE:
        return "", ""
    if call != _DX_NEW and loc_of.get(call):
        st.caption("📍 " + i18n.tr("Locator") + f": **{loc_of[call]}**" + (" ✏️" if call in man else ""))
        return call, loc_of[call]
    if call == _DX_NEW:
        call = st.text_input("Nominativo", "", key="em_p_newcall", placeholder="es. OK1KIR").strip().upper()
        if call in loc_of and loc_of[call]:
            st.caption("📍 " + i18n.tr("Locator") + f": **{loc_of[call]}**" + (" ✏️" if call in man else ""))
            return call, loc_of[call]
    loc = st.text_input("Locator", "", key=f"em_p_ploc_{call}", placeholder="es. JO70EB",
                        help="locator della stazione corrispondente (4 o 6 caratteri)").strip().upper()
    if call and loc and stn.LOC_RX.match(loc):
        if st.button("➕ Aggiungi alle Stazioni EME", key=f"em_p_addst_{call}",
                     help="salva nominativo e locator nel database come correzione a mano (✏️)"):
            D.set_station_manual(call, {"locator": loc})
            _st.session_state["em_p_pcall_next"] = call
            st.rerun()
    return call, loc


# ------------------------------------------------------------------ guide
def _guide():
    from pathlib import Path
    lang = i18n.get_lang()
    p = Path(__file__).resolve().parent / f"guida_misure_{'it' if lang == 'it' else 'en'}.md"
    if p.exists():
        _st.markdown(p.read_text(encoding="utf-8"))
    from emelab import credits
    st.divider()
    st.subheader("📚 Bibliografia")
    credits.render_bibliography(st)


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
        allrows = stn.parse_call3(up3.getvalue().decode("utf-8", "replace"))
        rows = stn.eme_only(allrows, D.eme_10g_calls())
        st.info(i18n.tr("Righe in CALL3.TXT") + f": {len(allrows)} · " + i18n.tr("stazioni EME da 10 GHz in su tenute")
                + f": {len(rows)}")
        if not rows:
            st.warning("CALL3.TXT non dice chi fa EME: completa solo il locator delle stazioni EME già note. "
                       "Importa prima la EME Directory (o ALL.TXT, o il log QSO), poi CALL3.TXT.")
        _import_or_ask(D, "call3", (rows, up3.name), {r["call"] for r in rows})
    if upa is not None and st.button("📥 Importa ALL.TXT", key="st_all_go"):
        from emelab import alltxt
        lines = upa.getvalue().decode("utf-8", "replace").splitlines()
        rows = alltxt.parse_eme(lines)              # only 10 GHz and up, Rx and Tx
        st.info(i18n.tr("Righe in ALL.TXT") + f": {len(lines)} · " + i18n.tr("righe da 10 GHz in su tenute") + f": {len(rows)}")
        _import_or_ask(D, "heard", (rows, upa.name), {r["call"] for r in rows if r["rxtx"] == "Rx" and r["call"]})
    if upp and st.button("📥 Importa i PDF", key="st_pa0ply_go"):
        _pa0ply_import(D, [(f.name, f.getvalue()) for f in upp])
    _import_confirm(D)
    _stations_quick_clear(D)
    rows = D.stations()
    if rows:
        import pandas as pd
        tab = []
        shown = rows
        if len(rows) > TABLE_MAX:
            q = st.text_input("🔎 Cerca nominativo o locator", "", key="st_find").strip().upper()
            if q:
                shown = [r for r in rows if q in r["call"] or q in (r.get("locator") or "").upper()]
            if len(shown) > TABLE_MAX:
                st.caption(i18n.tr("Mostro le prime") + f" {TABLE_MAX} " + i18n.tr("stazioni su") + f" {len(shown)}" + ". " +
                           i18n.tr("Scrivi un nominativo per trovare le altre."))
                shown = shown[:TABLE_MAX]
        for r in shown:
            d = r.get("data", {})
            h = d.get("heard", {})
            dirb = D.directory_of(d)
            tab.append({"Nominativo": r["call"], "Locator": r.get("locator") or "", "Nome": r.get("name") or "",
                        "QTH": r.get("qth") or "", "Bande (directory)": _bands_text(dirb),
                        "Stazione": _station_text(dirb), "✏️": "✏️" if d.get("manual") else "",
                        "Sentito": _blank(h.get("n")), "Ultima volta": (h.get("last") or "")[:16],
                        "SNR migliore": _blank(h.get("snr_best")), "SNR medio": _blank(h.get("snr_mean")),
                        "Bande sentite": _bands_text(h.get("bands", []))})
        df = pd.DataFrame(tab)
        cols = list(df.columns)
        df.columns = [i18n.tr(c) for c in cols]
        st.caption("Puoi correggere a mano Locator, Nome e QTH direttamente nella tabella, poi premi «Salva le correzioni». "
                   "Le correzioni a mano (✏️) restano anche quando importi di nuovo i file.")
        editable = {i18n.tr(c) for c in ("Locator", "Nome", "QTH")}
        ed = st.data_editor(df, hide_index=True, width="stretch", key="st_table" + _lang_key(),
                            disabled=[c for c in df.columns if c not in editable])
        if st.button("💾 Salva le correzioni", key="st_table_save"):
            st.session_state["st_flash"] = _save_station_edits(D, df, ed, cols)
            st.session_state.pop("st_table" + _lang_key(), None)      # the edits are in the database now
            st.rerun()
        for kind, msg in st.session_state.pop("st_flash", None) or []:
            getattr(st, kind)(msg)
        _station_edit_box(D, rows)
        _qrz_box(D, [r["call"] for r in rows])
    if rows or D.station_imports():
        _stations_manage(D, [r["call"] for r in rows])


TABLE_MAX = 500                # rows shown at once in the EME stations table (it stays fast with any database)


def _station_text(dirb: dict) -> str:
    out = []
    for b, v in sorted(dirb.items()):
        pw = v.get("power_w")
        out.append(f"{b}: " + " ".join(x for x in ((v.get("antenna") or "").strip(), f"{pw:g} W" if pw else "") if x))
    return "; ".join(out)


def _save_station_edits(D, df, ed, cols):
    """Write back the Locator/Nome/QTH cells changed in the table as corrections by hand."""
    from emelab import stations as stn
    names = dict(zip(df.columns, cols))
    n, bad = 0, []
    for (_, a), (_, b) in zip(df.iterrows(), ed.iterrows()):
        ch = {}
        for c in df.columns:
            k = {"Locator": "locator", "Nome": "name", "QTH": "qth"}.get(names[c])
            if k and str(a[c] or "").strip() != str(b[c] if b[c] is not None else "").strip():
                ch[k] = str(b[c] if b[c] is not None else "").strip()
        if not ch:
            continue
        if ch.get("locator"):
            ch["locator"] = ch["locator"].upper()
            if not stn.LOC_RX.match(ch["locator"]):
                bad.append(f"{a.iloc[0]}: {ch['locator']}")
                continue
        D.set_station_manual(str(a.iloc[0]), ch)
        n += 1
    out = [("success", i18n.tr("Stazioni corrette a mano") + f": {n}")]
    if bad:
        out.append(("error", i18n.tr("Locator non valido") + ": " + ", ".join(bad)))
    return out


def _station_edit_box(D, rows):
    from emelab import dx, stations as stn
    with st.expander("✏️ Correggi a mano una stazione (anche antenna e potenza per banda)"):
        calls = [r["call"] for r in rows]
        call = st.selectbox("Nominativo", [""] + calls, key="st_ed_call", format_func=lambda c: c or "—")
        new = st.text_input("…oppure un nominativo nuovo", "", key="st_ed_new").strip().upper()
        call = new or call
        if not call:
            return
        r = D.station_of(call) or {"call": call, "data": {}}
        man = r["data"].get("manual") or {}
        dirb = D.directory_of(r["data"])
        c = st.columns(3)
        loc = c[0].text_input("Locator", r.get("locator") or "", key=f"st_ed_loc_{call}")
        name = c[1].text_input("Nome", r.get("name") or "", key=f"st_ed_name_{call}")
        qth = c[2].text_input("QTH", r.get("qth") or "", key=f"st_ed_qth_{call}")
        bands = {}
        for b in dx.BAND_GHZ:
            v = dirb.get(b) or {}
            c = st.columns([1, 3, 2])
            c[0].markdown(f"**{_bl(b)}**" + (" ✏️" if b in (man.get("bands") or {}) else ""))
            ant = c[1].text_input("Antenna", v.get("antenna") or "", key=f"st_ed_ant_{call}_{b}",
                                  placeholder="es. 3m dish", label_visibility="collapsed" if b != list(dx.BAND_GHZ)[0] else "visible")
            pw = c[2].number_input("Potenza (W)", 0.0, 100000.0, float(v.get("power_w") or 0), 1.0, key=f"st_ed_pw_{call}_{b}",
                                   label_visibility="collapsed" if b != list(dx.BAND_GHZ)[0] else "visible")
            if ant.strip() != (v.get("antenna") or "").strip() or pw != float(v.get("power_w") or 0):
                bands[b] = {"antenna": ant, "power_w": pw or None} if (ant.strip() or pw) else None
        c = st.columns(2)
        if c[0].button("💾 Salva la stazione", key=f"st_ed_save_{call}"):
            if loc and not stn.LOC_RX.match(loc.strip()):
                st.error(i18n.tr("Locator non valido") + f": {loc}")
            else:
                f = {k: v for k, v in (("locator", loc.strip().upper()), ("name", name), ("qth", qth))
                     if (v or "") != (r.get(k) or "")}
                D.set_station_manual(call, {k: v or "" for k, v in f.items()}, bands)
                st.success(i18n.tr("Salvato") + f": {call}")
                st.rerun()
        if man and c[1].button("↩️ Togli le correzioni a mano", key=f"st_ed_undo_{call}"):
            D.set_station_manual(call, {k: "" for k in D.MANUAL_FIELDS}, {b: None for b in man.get("bands") or {}})
            st.success(i18n.tr("Tornati i dati importati") + f": {call}")
            st.rerun()


def _blank(v):
    """Empty cell instead of "None" in the tables."""
    return "" if v is None else str(v)


def _source_label(key: str) -> str:
    if key.startswith("directory:"):
        return i18n.tr("EME Directory (PA0PLY)") + " · " + key.split(":", 1)[1]
    return {"call3": i18n.tr("CALL3.TXT di WSJT-X"), "heard": i18n.tr("Ascolti (ALL.TXT e WSJT-X in diretta)"),
            "qrz": "QRZ.com", "manual": i18n.tr("Correzioni a mano")}.get(key, key)


def _stations_manage(D, calls):
    with st.expander("🗑️ Cancella i dati importati"):
        imp = D.station_imports()
        if imp:
            import pandas as pd
            st.markdown("**" + i18n.tr("File importati") + "**")
            df = pd.DataFrame([{"Data (UTC)": r["utc"][:16].replace("T", " "), "Fonte": _source_label(r["source"]),
                                "File": r.get("label") or "", "Stazioni": _blank(r.get("n"))} for r in imp])
            df.columns = [i18n.tr(c) for c in df.columns]
            st.dataframe(df, hide_index=True, width="stretch")
        counts = D.station_source_counts()
        if counts:
            st.markdown("**" + i18n.tr("Cancella per fonte") + "**")
            st.caption("Toglie dal database tutto quello che è arrivato da quella fonte. Le stazioni che non hanno "
                       "dati da altre fonti vengono eliminate.")
            for key, n in counts.items():
                c = st.columns([3, 1])
                c[0].markdown(f"{_source_label(key)} — {n} " + i18n.tr("stazioni"))
                if c[1].button("🗑️ Cancella", key=f"st_del_src_{key}"):
                    st.session_state["st_del_pending"] = key
            key = st.session_state.get("st_del_pending")
            if key in counts:
                st.warning(i18n.tr("Cancellare i dati di") + f" {_source_label(key)} ({counts[key]} " +
                           i18n.tr("stazioni") + ")?")
                c = st.columns(2)
                if c[0].button("✅ Sì, cancella", key="st_del_src_yes"):
                    ch, de = D.remove_station_source(key)
                    st.session_state.pop("st_del_pending", None)
                    st.success(i18n.tr("Stazioni aggiornate") + f": {ch} · " + i18n.tr("stazioni eliminate") + f": {de}")
                    st.rerun()
                if c[1].button("Annulla", key="st_del_src_no"):
                    st.session_state.pop("st_del_pending", None)
                    st.rerun()
        if calls:
            st.markdown("**" + i18n.tr("Cancella singole stazioni") + "**")
            pick = st.multiselect("Stazioni da cancellare", calls, key="st_del_calls")
            if pick and st.button("🗑️ Cancella le stazioni scelte", key="st_del_calls_go"):
                n = D.delete_stations(pick)
                st.session_state.pop("st_del_calls", None)
                st.success(i18n.tr("stazioni eliminate") + f": {n}")
                st.rerun()
            st.markdown("**" + i18n.tr("Svuota tutto il database delle stazioni") + "**")
            sure = st.checkbox("Confermo: cancella tutte le stazioni e l'elenco dei file importati", key="st_clear_ok")
            if st.button("🗑️ Svuota il database delle stazioni", key="st_clear_go", disabled=not sure):
                n = D.clear_stations()
                st.session_state.pop("st_clear_ok", None)
                st.success(i18n.tr("stazioni eliminate") + f": {n}")
                st.rerun()


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
    parsed = []
    for name, data in files:
        nl = name.lower()
        band = "10G" if nl.startswith(("10368", "10g")) else "24G" if nl.startswith(("24048", "24g")) else \
            "47G" if nl.startswith("47") else "76G" if nl.startswith("76") else None
        if band is not None:
            parsed.append((name, band, stn.parse_pa0ply(stn.pdf_text(data), band)))
    _import_or_ask(D, "directory", parsed, {r["call"] for _, _, rows in parsed for r in rows})


IMPORT_ASK_OVER = 300          # above this many stations in one import EMELab asks before going on


def _import_or_ask(D, kind, payload, calls: set):
    """Import at once, or — with more than IMPORT_ASK_OVER stations — keep it waiting for an OK."""
    if len(calls) > IMPORT_ASK_OVER:
        have = {r["call"] for r in D.stations()}
        st.session_state["st_import_pending"] = {"kind": kind, "payload": payload, "n": len(calls),
                                                 "new": len(calls - have)}
    else:
        st.session_state.pop("st_import_pending", None)
        _import_apply(D, kind, payload)


def _import_confirm(D):
    p = st.session_state.get("st_import_pending")
    if not p:
        return
    st.warning(i18n.tr("Questa importazione contiene") + f" {p['n']} " + i18n.tr("stazioni") + f" ({p['new']} " +
               i18n.tr("nuove") + "), " + i18n.tr("più di") + f" {IMPORT_ASK_OVER}. " + i18n.tr("Continuo?"))
    c = st.columns(2)
    if c[0].button("✅ OK, continua l'importazione", key="st_import_yes"):
        st.session_state.pop("st_import_pending", None)
        _import_apply(D, p["kind"], p["payload"])
    if c[1].button("✖️ Annulla l'importazione", key="st_import_no"):
        st.session_state.pop("st_import_pending", None)
        st.rerun()


def _import_apply(D, kind, payload):
    if kind == "call3":
        rows, name = payload
        for r in rows:
            old = (D.station_of(r["call"]) or {}).get("locator") or ""
            loc = r["locator"] if len(r["locator"]) > len(old) else None      # never a less precise locator
            D.upsert_station(r["call"], locator=loc, eme=1, data={"call3": True})
        D.commit()
        D.log_station_import("call3", name, len(rows))
        st.success(i18n.tr("Stazioni importate") + f": {len(rows)}")
    elif kind == "heard":
        from emelab import alltxt
        rows, name = payload
        res = alltxt.store(D, rows)                 # into the decodes; «heard» rebuilt from them (no double counts)
        D.log_station_import("heard", name, len(res["calls"]))
        st.success(i18n.tr("Decodifiche lette") + f": {res['rx']} ({res['new_rx']} " + i18n.tr("nuove") + ") · " +
                   i18n.tr("stazioni") + f": {len(res['calls'])}")
    elif kind == "directory":
        n = 0
        for name, band, rows in payload:
            for r in rows:
                old = (D.station_of(r["call"]) or {}).get("data", {}).get("directory", {})
                old[band] = {"antenna": r["antenna"], "power_w": r["power_w"], "web": r["web"], "name": r["name"] or None}
                D.upsert_station(r["call"], locator=r["locator"], name=r["name"] or None, eme=1, data={"directory": old})
            n += len(rows)
            D.commit()
            D.log_station_import(f"directory:{band}", name, len(rows))
        st.success(i18n.tr("Righe della EME Directory importate") + f": {n}")


def _stations_quick_clear(D):
    """Empty the station database and start again: right under the import buttons, so it is easy to find."""
    n = len(D.stations())
    if not n:                                    # just emptied: the message, then nothing else to show
        for kind, msg in st.session_state.pop("st_flash", None) or []:
            getattr(st, kind)(msg)
        if not D.station_imports():
            return
    c = st.columns([3, 2])
    c[0].markdown(f"**{n}** " + i18n.tr("stazioni nel database") + " · " +
                  i18n.tr("per cancellare solo una fonte o singole stazioni apri «🗑️ Cancella i dati importati» in fondo alla pagina"))
    if c[1].button("🗑️ Svuota tutto e re-importa", key="st_quick_clear"):
        st.session_state["st_quick_clear_ask"] = True
    if st.session_state.get("st_quick_clear_ask"):
        st.warning(i18n.tr("Cancellare tutte le") + f" {n} " + i18n.tr("stazioni e l'elenco dei file importati? "
                                                                       "Poi potrai importare di nuovo i file da capo."))
        c = st.columns(2)
        if c[0].button("✅ Sì, svuota", key="st_quick_clear_yes"):
            D.clear_stations()
            st.session_state.pop("st_quick_clear_ask", None)
            st.session_state.pop("st_table" + _lang_key(), None)
            st.session_state["st_flash"] = [("success", i18n.tr("Database delle stazioni svuotato: ora puoi re-importare i file."))]
            st.rerun()
        if c[1].button("Annulla", key="st_quick_clear_no"):
            st.session_state.pop("st_quick_clear_ask", None)
            st.rerun()


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
                    qrz.store(D, {**q.lookup(call), "call": call})
                D.commit()
                D.log_station_import("qrz", ", ".join(pick)[:200], len(pick))
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
    svc = _wsjtx_autostart()
    auto_on = svc.auto_log and (svc.running or svc.file_running)
    if auto_on:
        how = " + ".join(x for x in ("UDP" if svc.running else "", "wsjtx_log.adi" if svc.file_running else "") if x)
        last = next((q for q in svc.logged if q.get("id")), None)
        st.success(i18n.tr("I QSO confermati in WSJT-X entrano nel log da soli") + f" ({how})"
                   + (" · " + i18n.tr("ultimo") + f": {last['call']} {last['utc']:%Y-%m-%d %H:%M}" if last else ""))
    else:
        st.info("Per registrare i QSO da soli, collega WSJT-X nella scheda 📻 WSJT-X (file di log o UDP). "
                "Il modulo qui sotto resta per i QSO fatti con altri programmi o in CW/SSB.")
    with st.expander("➕ Nuovo QSO", expanded=not auto_on):
        now = datetime.now(timezone.utc)
        c = st.columns(4)
        d0 = c[0].date_input("Data (UTC)", now.date(), key="q_date")
        t0 = c[1].time_input("Ora (UTC)", now.time().replace(second=0, microsecond=0), key="q_time", step=60)
        call = c[2].text_input("Nominativo", "", key="q_call").strip().upper()
        known = D.station_of(call) if call else None
        loc = c[3].text_input("Locator", (known or {}).get("locator") or "", key=f"q_loc_{call}")
        c = st.columns(5)
        band = c[0].selectbox("Banda", list(lb.BAND_F), key="q_band", format_func=_bl)
        freq = c[1].number_input("Frequenza (MHz)", 1000.0, 300000.0, lb.BAND_F[band] * 1000, 0.001, format="%.3f", key=f"q_f_{band}")
        mode = c[2].selectbox("Modo", ["Q65", "JT65", "JT4", "CW", "SSB", "FST4", "Altro"], key="q_mode")
        if mode == "Q65":
            from emelab import dx
            std = dx.band_mode(band)
            sub = c[3].selectbox("Sottomodo", list(lb.Q65_SUBMODES), index=lb.Q65_SUBMODES.index(std), key=f"q_sub_q65_{band}",
                                 format_func=lambda k: f"Q65-{k}", help="Periodo T/R (15–300 s) e spaziatura dei toni (A–E)")
        else:
            sub = c[3].text_input("Sottomodo", "", key=f"q_sub_{mode}")
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
            id0 = D.max_qso_id()
            n = dup = skipped = 0
            bar = st.progress(0.0)
            recs = [r for f in ups for r in lb.parse_adif(f.getvalue().decode("utf-8", "replace"))]
            eme_calls = {x["call"] for x in D.stations() if x.get("eme")}
            for k, r in enumerate(recs):
                q = lb.from_adif_record(r)
                if q is None:
                    continue
                q = lb.wsjtx_mode(q)
                # PROP_MODE EME, or (no PROP_MODE) an EME station / an EME digital mode; tropo, rain scatter… are left out
                if only_eme and lb.eme_verdict(q, eme_calls):
                    skipped += 1
                    continue
                q.pop("prop_mode", None)
                if D.qso_near(q["call"], q.get("band"), q["utc"]):       # already logged (from WSJT-X or another file)
                    dup += 1
                    continue
                q["my_locator"] = q.get("my_locator") or my_loc
                q["calc"] = lb.enrich(q, my_loc, stn.get("height_m") or 0)
                if D.add_qso(**q):
                    n += 1
                else:
                    dup += 1
                bar.progress((k + 1) / max(len(recs), 1))
            st.success(i18n.tr("QSO importati") + f": {n}" + (f" · " + i18n.tr("già presenti") + f": {dup}" if dup else "")
                       + (f" · " + i18n.tr("non EME o sotto i 10 GHz, lasciati fuori") + f": {skipped}" if skipped else ""))
            D.log_qso_import(", ".join(f.name for f in ups), id0)
    lb.fill_locators(D, my_loc, stn.get("height_m") or 0)
    lb.fill_moon_az(D, my_loc, stn.get("height_m") or 0)
    qs = D.qsos()
    if not qs:
        st.info("Nessun QSO nel log.")
        return
    from emelab import qrz
    _qso_qrz_fill(D, [q["call"] for q in qs])
    ppl = qrz.qso_people(D, {q["call"] for q in qs})
    import pandas as pd
    df = pd.DataFrame([{"ID": q["id"], "Data UTC": q["utc"].strftime("%Y-%m-%d %H:%M"), "Nominativo": q["call"],
                        "Banda": _bl(q.get("band")), "Modo": lb.mode_label(q)[0],
                        "Inviato": q.get("rst_sent") or "", "Ricevuto": q.get("rst_rcvd") or "", "Locator": q.get("locator") or "",
                        "QTH": ppl[q["call"]]["qth"], "Nome": ppl[q["call"]]["fname"], "Cognome": ppl[q["call"]]["lname"],
                        "Distanza (km)": _blank(_r(q["calc"].get("ground_km"), 0)),
                        "Percorso EME (km)": _blank(_r(q["calc"].get("eme_path_km"), 0)),
                        "AZ Luna": _blank(_r(q["calc"].get("moon_az"), 1)), "EL Luna": _blank(_r(q["calc"].get("moon_el"), 1)),
                        "AZ DX": _blank(_r(q["calc"].get("dx_moon_az"), 1)), "EL DX": _blank(_r(q["calc"].get("dx_moon_el"), 1)),
                        "Spread (Hz)": _blank(_r(q["calc"].get("mutual_spread_hz"), 0)), "Note": q.get("comment") or ""}
                       for q in qs])
    raw_cols = list(df.columns)
    df.columns = [i18n.tr(c) for c in df.columns]
    assumed = [lb.mode_label(q)[1] for q in qs]
    mcol = i18n.tr("Modo")
    sty = df.style.format(precision=1, na_rep="").apply(
        lambda col: [f"color: {ASSUMED_COLOR}" if a else "" for a in assumed], subset=[mcol])
    st.dataframe(sty, hide_index=True, width="stretch", key="q_log_table",
                 column_config=_col_config("log_qso", list(df.columns), raw_cols))
    _col_widths_editor("log_qso", raw_cols)
    if any(assumed):
        st.markdown(f"<span style='color:{ASSUMED_COLOR}'>Q65-60D</span> = " + i18n.tr(
            "sottomodo presunto: non è scritto nel log (WSJT-X non lo mette nell'ADIF), è il modo standard della banda "
            "(60D a 10 GHz, 60E da 24 GHz in su) o quello scelto nel Pianificatore."), unsafe_allow_html=True)
    cols = lb.BAND_COLORS
    paths = [(*lb.latlon(q["my_locator"] or my_loc), *lb.latlon(q["locator"]), cols.get(q.get("band"), "#555"),
              f"{q['call']} {_bl(q.get('band'))}") for q in qs if q.get("locator") and lb.latlon(q["locator"])]
    st.plotly_chart(world_fig(paths[-300:], height=460), width="stretch")
    c = st.columns(3)
    c[0].download_button("⬇️ Esporta ADIF", lb.to_adif(qs, stn.get("callsign") or ""), file_name="emelab_log.adi",
                         mime="text/plain")
    dl = c[1].selectbox("Elimina QSO (ID)", [None] + [q["id"] for q in qs], key="q_del",
                        format_func=lambda i: "—" if i is None else str(i))
    if dl and c[1].button("🗑️ Elimina", key="q_del_go"):
        D.delete_qso(dl)
        st.rerun()
    _qsos_manage(D, len(qs))


def _qso_qrz_fill(D, calls):
    """QTH, first and last name of the QSO partners from QRZ.com: only the callsigns not looked up yet, on request."""
    from emelab import qrz
    todo = qrz.missing(D, calls)
    sets = openems_local.load_settings()
    user, pw = sets.get("qrz_user", ""), sets.get("qrz_pw", "")
    with st.expander("🔎 QTH, nome e cognome da QRZ.com" + (f" ({len(todo)} " + i18n.tr("da cercare") + ")" if todo else "")):
        if not (user and pw):
            st.caption("Salva prima utente e password di QRZ.com nella scheda Stazioni EME (riquadro «🔎 QRZ.com»).")
            return
        st.caption("Cerca su QRZ.com solo i nominativi del log non ancora cercati; i dati restano nel database delle "
                   "stazioni EME. Nome, cognome e QTH arrivano anche senza abbonamento XML di QRZ.com.")
        c = st.columns(2)
        go = c[0].button("🔎 Cerca i mancanti su QRZ.com", key="q_qrz_go", disabled=not todo)
        again = c[1].button("🔄 Aggiorna tutti da QRZ.com", key="q_qrz_all")
        if not (go or again):
            return
        pick = todo if go else list(dict.fromkeys(calls))
        q, ok, bad = qrz.QRZ(user, pw), 0, []
        bar = st.progress(0.0)
        for k, call in enumerate(pick):
            try:
                qrz.store(D, {**q.lookup(call), "call": call}, locator=False)
                ok += 1
            except Exception as e:
                if not q.key:                                    # login refused: no point trying the others
                    st.error(f"QRZ.com: {e}")
                    break
                bad.append(call)
            bar.progress((k + 1) / len(pick))
        D.commit()
        if ok:
            D.log_station_import("qrz", ", ".join(pick)[:200], ok)
            st.success(i18n.tr("Aggiornati da QRZ.com") + f": {ok}")
        if bad:
            st.warning(i18n.tr("Non trovati su QRZ.com") + ": " + ", ".join(bad))


def _qsos_manage(D, n_qsos):
    with st.expander("🗑️ Cancella i QSO importati o svuota il log"):
        imp = [r for r in D.qso_imports() if r["n"]]
        if imp:
            st.markdown("**" + i18n.tr("File ADIF importati") + "**")
            for r in imp:
                c = st.columns([3, 1])
                c[0].markdown(f"{r['utc'][:16].replace('T', ' ')} UTC · {r.get('label') or ''} — {r['n']} QSO")
                if c[1].button("🗑️ Cancella", key=f"q_imp_del_{r['id']}"):
                    st.session_state["q_imp_pending"] = r["id"]
            pend = next((r for r in imp if r["id"] == st.session_state.get("q_imp_pending")), None)
            if pend:
                st.warning(i18n.tr("Cancellare i QSO importati da") + f" {pend.get('label') or ''} ({pend['n']} QSO)?")
                c = st.columns(2)
                if c[0].button("✅ Sì, cancella", key="q_imp_yes"):
                    D.delete_qso_import(pend["id"])
                    st.session_state.pop("q_imp_pending", None)
                    st.rerun()
                if c[1].button("Annulla", key="q_imp_no"):
                    st.session_state.pop("q_imp_pending", None)
                    st.rerun()
        st.markdown("**" + i18n.tr("Svuota tutto il log") + "**")
        st.caption("Cancella tutti i QSO del log, così puoi importare di nuovo i file ADIF da capo. "
                   "Le Stazioni EME e le misure restano.")
        sure = st.checkbox(i18n.tr("Confermo: cancella tutti i QSO") + f" ({n_qsos})", key="q_clear_ok")
        if st.button("🗑️ Svuota il log QSO", key="q_clear_go", disabled=not sure):
            D.clear_qsos()
            st.session_state.pop("q_clear_ok", None)
            st.rerun()


def _saved_widths(table: str) -> dict:
    return ((openems_local.load_settings().get("col_widths") or {}).get(table) or {})


def _col_config(table: str, shown: list, raw: list) -> dict:
    """Column widths the user chose for this table (saved on this PC): {shown name: Column(width=px)}."""
    w = _saved_widths(table)
    return {s: _st.column_config.Column(width=int(w[r])) for s, r in zip(shown, raw) if w.get(r)}


def _col_widths_save(table: str, raw: list):
    allw = openems_local.load_settings().get("col_widths") or {}
    allw[table] = {r: int(_st.session_state.get(f"cw_{table}_{r}") or 0) for r in raw
                   if _st.session_state.get(f"cw_{table}_{r}")}
    openems_local.save_settings(col_widths=allw)


def _col_widths_reset(table: str, raw: list):
    allw = openems_local.load_settings().get("col_widths") or {}
    allw.pop(table, None)
    openems_local.save_settings(col_widths=allw)
    for r in raw:
        _st.session_state[f"cw_{table}_{r}"] = 0


def _col_widths_editor(table: str, raw: list):
    """Widths of the table columns in pixels, remembered on this PC: the table opens the same way every time."""
    w = _saved_widths(table)
    with st.popover("↔️ Larghezza delle colonne"):
        st.caption("Larghezza in pixel di ogni colonna, ricordata su questo PC. 0 = automatica.")
        c = st.columns(4)
        for i, r in enumerate(raw):
            k = f"cw_{table}_{r}"
            if k not in _st.session_state:
                _st.session_state[k] = int(w.get(r) or 0)
            c[i % 4].number_input(r, 0, 1000, step=10, key=k, on_change=_col_widths_save, args=(table, raw))
        st.button("↩️ Larghezze automatiche", key=f"cw_{table}_reset", on_click=_col_widths_reset, args=(table, raw))


def _qso_band_filter(qs, lb):
    """One switch per band found in the log (10 GHz, 24 GHz, 47 GHz…): the statistics follow the bands left on."""
    order = list(lb.BAND_F)
    count = {}
    for q in qs:
        count[q.get("band") or "?"] = count.get(q.get("band") or "?", 0) + 1
    bands = sorted(count, key=lambda b: (order.index(b) if b in order else len(order), b))
    if len(bands) < 2:
        return qs
    st.caption("Bande da includere")
    st.markdown("<style>" + "".join(
        f".st-key-qs_band_{b} label[data-selected='true'] > span + div {{background-color: {lb.BAND_COLORS[b]} !important;}}"
        for b in bands if b in lb.BAND_COLORS) + "</style>", unsafe_allow_html=True)
    c = st.columns(6)
    on = set()
    for i, b in enumerate(bands):
        name = _bl(b)
        if c[i % len(c)].toggle(f"{name} ({count[b]})", value=True, key=f"qs_band_{b}"):
            on.add(b)
    return [q for q in qs if (q.get("band") or "?") in on]


def _qso_stats_tab(D):
    from emelab import ui_alltxt
    _qso_stats_log(D)
    ui_alltxt.stats_section(D)          # every decode of ALL.TXT at 10 GHz and up


def _qso_stats_log(D):
    from emelab import logbook as lb
    qs = D.qsos()
    if not qs:
        st.info("Nessun QSO nel log.")
        return
    qs = _qso_band_filter(qs, lb)
    if not qs:
        st.info("Nessuna banda selezionata.")
        return
    s = lb.statistics(qs)
    c = st.columns(4)
    c[0].metric("QSO", s["n"])
    c[1].metric("Bande", ", ".join(f"{_bl(b)}: {n}" for b, n in sorted(s["by_band"].items(), key=lambda x: _bsk(_bl(x[0])))))
    if "moon_el" in s:
        c[2].metric("EL Luna mediana", f"{s['moon_el']['median']:.0f}°")
    if "mutual_spread_hz" in s:
        c[3].metric("Spread mutuo mediano", f"{s['mutual_spread_hz']['median']:.0f} Hz")
    _qso_stats_charts(qs, lb)


def _qso_stats_charts(qs, lb):
    """Hour, month, Moon elevation and spread: one coloured piece per band, stacked from 10 GHz upwards."""
    order = list(lb.BAND_F)
    bands = sorted({q.get("band") or "?" for q in qs}, key=lambda b: (order.index(b) if b in order else len(order), b))
    many = len(bands) > 1

    def name(b):
        return f"{b[:-1]} GHz" if b.endswith("G") and b[:-1].isdigit() else b

    def layout(fig, title):
        fig.update_layout(title=title, height=300, margin=dict(l=10, r=10, t=40, b=10), barmode="stack",
                          showlegend=many, legend=dict(orientation="h", y=1.12, x=1, xanchor="right", traceorder="normal"))
        return fig

    def of(b):
        return [q for q in qs if (q.get("band") or "?") == b]

    def utc(q):
        t = q["utc"]
        return t if isinstance(t, datetime) else datetime.strptime(t.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")

    months = [i18n.tr(m) for m in planner.MONTHS_IT]
    cc = st.columns(2)
    fig, fig2 = go.Figure(), go.Figure()
    for b in bands:
        h, m = [0] * 24, [0] * 12
        for q in of(b):
            t = utc(q)
            h[t.hour] += 1
            m[t.month - 1] += 1
        color = lb.BAND_COLORS.get(b, "#777")
        fig.add_bar(x=list(range(24)), y=h, name=name(b), marker_color=color)
        fig2.add_bar(x=months, y=m, name=name(b), marker_color=color)
    cc[0].plotly_chart(layout(fig, "QSO per ora UTC"), width="stretch")
    cc[1].plotly_chart(layout(fig2, "QSO per mese"), width="stretch")
    cc = st.columns(2)
    for col, k, title in ((cc[0], "moon_el", "Elevazione della Luna ai QSO (°)"), (cc[1], "mutual_spread_hz", "Spread mutuo ai QSO (Hz)")):
        val = {b: [q["calc"].get(k) for q in of(b) if q.get("calc") and q["calc"].get(k) is not None] for b in bands}
        allv = [x for v in val.values() for x in v]
        if not allv:
            continue
        lo, hi = min(allv), max(allv)
        size = (hi - lo) / 20 or 1                       # same 20 bins for every band, so the pieces stack
        fig = go.Figure()
        for b in bands:
            if val[b]:
                fig.add_histogram(x=val[b], name=name(b), marker_color=lb.BAND_COLORS.get(b, "#777"),
                                  xbins=dict(start=lo, end=hi + size * 1e-6, size=size))
        col.plotly_chart(layout(fig, title), width="stretch")


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
                              format_func=lambda i: next(f"{q['call']} {q['utc']:%Y-%m-%d} {_bl(q.get('band'))}" for q in qs if q["id"] == i))
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
        if i18n.get_lang() != "it":
            name = {"diario_misure.pdf": "measurement_log.pdf", "log_qso.pdf": "qso_log.pdf",
                    "etichette_qsl.pdf": "qsl_labels.pdf"}.get(name, name)
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
        rx_df, rx_cfg = _blank_cols(_editor_rows(_st.session_state.get("rx_tab", _RX_DEFAULT)))
        rx = st.data_editor(rx_df, num_rows="dynamic", column_config=rx_cfg,
                            key="rx_ed" + _lang_key(), hide_index=True, width="stretch")
        t_ant = st.number_input("Temperatura d'antenna (K)", 3.0, 500.0, 40.0, 1.0, key="ch_tant",
                                help="dal progetto FeedLab o dalla misura; cielo freddo + spillover")
        stages = [chain.passive(r["Stadio"], -_num(r["Guadagno (dB)"])) if r["Tipo"] == "passivo" else
                  {"name": r["Stadio"], "gain_db": _num(r["Guadagno (dB)"]), "nf_db": _num(r.get("NF (dB)")) or 0.0}
                  for r in _editor_back(rx, _RX_DEFAULT[0]) if r.get("Stadio") and _num(r.get("Guadagno (dB)")) is not None]
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
        tx_df, tx_cfg = _blank_cols(_editor_rows(_st.session_state.get("tx_tab", _TX_DEFAULT)))
        tx = st.data_editor(tx_df, num_rows="dynamic", column_config=tx_cfg,
                            key="tx_ed" + _lang_key(), hide_index=True, width="stretch")
        pin = st.number_input("Potenza in ingresso (dBm)", -30.0, 40.0, 10.0, 0.5, key="ch_pin")
        st_tx = []
        for r in _editor_back(tx, _TX_DEFAULT[0]):
            if not r.get("Stadio") or _num(r.get("Guadagno (dB)")) is None:
                continue
            if r["Tipo"] == "passivo":
                st_tx.append(chain.passive(r["Stadio"], -_num(r["Guadagno (dB)"])))
            else:
                f = lambda k: _num(r.get(k))
                st_tx.append({"name": r["Stadio"], "gain_db": _num(r["Guadagno (dB)"]), "psat_dbm": f("Psat (dBm)"),
                              "p1db_dbm": f("P1dB (dBm)"), "vdc": f("V"), "idc_a": f("A")})
        if st_tx:
            res = chain.tx_chain(pin, st_tx)
            m = st.columns(3)
            m[0].metric("Potenza al feed", f"{res['p_out_w']:.1f} W", help=f"{res['p_out_dbm']:.2f} dBm")
            m[1].metric("Consumo DC", f"{res['dc_w']:.0f} W")
            m[2].metric("Calore da dissipare", f"{res['heat_w']:.0f} W")
            st.dataframe(pd.DataFrame([{i18n.tr("Stadio"): s["name"], i18n.tr("Ingresso (dBm)"): round(s["p_in_dbm"], 2),
                                        i18n.tr("Uscita (dBm)"): round(s["p_out_dbm"], 2),
                                        i18n.tr("Margine dal P1dB (dB)"): "" if s["p1db_margin_db"] is None else f"{s['p1db_margin_db']:.1f}"}
                                       for s in res["stages"]]), hide_index=True, width="stretch",
                         column_config={i18n.tr("Margine dal P1dB (dB)"): _st.column_config.TextColumn(alignment="right")})
    st.divider()
    st.subheader("Libreria dei componenti")
    st.caption("Componenti con i valori dei datasheet dei produttori (inseriti da te o trovati nel catalogo Mouser) e il "
               "link al datasheet. EMELab non inventa i valori: controlla sempre il datasheet alla tua frequenza.")
    rows = parts.all_parts(D)
    if rows:
        lib = pd.DataFrame(rows).drop(columns=["id", "verified"], errors="ignore")
        st.dataframe(lib.astype(object).where(lib.notna(), ""), hide_index=True, width="stretch")
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


# ------------------------------------------------------------------ charts and fits
def _charts_tab(D):
    import pandas as pd
    from emelab import plots
    st.subheader("Grafici e interpolazioni")
    st.caption("Qualsiasi parametro dei QSO o delle misure contro qualsiasi altro, con interpolazione: retta, polinomio, "
               "LOESS (tendenza locale) o mediane per classi. Le condizioni di ogni QSO (Luna, spread, Doppler, atmosfera, "
               "meteo) sono quelle calcolate da EMELab.")
    src = st.radio("Dati", ["QSO", "Misure"], horizontal=True, key="pl_src")
    rows = plots.rows_from_qsos(D.qsos()) if src == "QSO" else plots.rows_from_measurements(D.measurements())
    if not rows:
        st.info("Ancora nessun dato: registra o importa QSO e misure.")
        return
    cats = sorted({r.get("band") for r in rows if r.get("band")}, key=_bsk)
    c = st.columns(4)
    sel_b = c[0].multiselect("Bande", cats, cats, key="pl_bands")
    rows = [r for r in rows if not cats or r.get("band") in sel_b]
    if src == "QSO":
        calls = sorted({r["call"] for r in rows if r.get("call")})
        sel_c = c[1].multiselect("Nominativi (vuoto = tutti)", calls, [], key="pl_calls")
        if sel_c:
            rows = [r for r in rows if r.get("call") in sel_c]
    dates = [r["utc"] for r in rows if r.get("utc")]
    if dates:
        d0, d1 = min(dates).date(), max(dates).date()
        rng = c[2].date_input("Periodo", (d0, d1), min_value=d0, max_value=d1, key="pl_dates")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            rows = [r for r in rows if r.get("utc") and rng[0] <= r["utc"].date() <= rng[1]]
    kind = c[3].selectbox("Tipo di grafico", ["Dispersione", "Serie nel tempo", "Istogramma", "Correlazioni"], key="pl_kind")
    cols = plots.numeric_columns(rows)
    if not cols:
        st.info("Nessun parametro numerico nel periodo scelto.")
        return
    fmt = lambda k: i18n.tr(plots.label(k))
    yd = "rst_sent_db" if "rst_sent_db" in cols else ("y_db" if "y_db" in cols else cols[0])
    xd = "moon_el" if "moon_el" in cols else cols[0]
    group = "band" if src == "QSO" else "kind"
    if kind == "Correlazioni":
        tgt = st.selectbox("Parametro da spiegare", cols, index=cols.index(yd), format_func=fmt, key="pl_tgt")
        cr = plots.correlations(rows, tgt)
        if not cr:
            st.info("Servono almeno 8 valori per parametro.")
            return
        st.caption("Correlazione di rango di Spearman: +1 crescono insieme, −1 uno cresce e l'altro cala, 0 nessun legame. "
                   "Indica dove guardare, non la causa.")
        top = cr[:20]
        fig = go.Figure(go.Bar(x=[v for _, v, _ in top][::-1], y=[fmt(k) for k, _, _ in top][::-1], orientation="h",
                               marker_color=["#2e7d32" if v > 0 else "#c62828" for _, v, _ in top][::-1],
                               text=[f"{v:+.2f} (n={n})" for _, v, n in top][::-1], textposition="auto"))
        fig.update_layout(title=i18n.tr("Cosa va insieme a") + f" «{fmt(tgt)}»", height=120 + 26 * len(top),
                          margin=dict(l=10, r=10, t=40, b=10), xaxis_range=[-1, 1])
        st.plotly_chart(fig, width="stretch")
        return
    c = st.columns(4)
    ycol = c[0].selectbox("Asse Y", cols, index=cols.index(yd), format_func=fmt, key="pl_y")
    if kind == "Dispersione":
        xcol = c[1].selectbox("Asse X", cols, index=cols.index(xd), format_func=fmt, key="pl_x")
    else:
        xcol = "date"
    fk = c[2].selectbox("Interpolazione", list(plots.FITS), format_func=lambda k: plots.FITS[k], index=1 if kind != "Istogramma" else 0,
                        key="pl_fit", disabled=kind == "Istogramma")
    span = c[3].slider("Ampiezza LOESS", 0.2, 1.0, 0.5, 0.05, key="pl_span", disabled=fk != "loess",
                       help="frazione dei punti usata per ogni stima locale: più alta = curva più liscia")
    pts = [r for r in rows if isinstance(r.get(ycol), (int, float)) and (kind == "Istogramma" or isinstance(r.get(xcol), (int, float)))]
    if not pts:
        st.info("Nessun valore per questi parametri.")
        return
    fig = go.Figure()
    if kind == "Istogramma":
        for g in sorted({str(r.get(group)) for r in pts}):
            fig.add_trace(go.Histogram(x=[r[ycol] for r in pts if str(r.get(group)) == g], name=g, opacity=0.75))
        fig.update_layout(barmode="overlay", xaxis_title=fmt(ycol), yaxis_title=i18n.tr("Numero"))
        vals = np.array([r[ycol] for r in pts])
        st.caption(i18n.tr("Mediana") + f" {np.median(vals):.2f} · " + i18n.tr("media") + f" {vals.mean():.2f} · σ {vals.std():.2f} · n {len(vals)}")
    else:
        xv = lambda r: (r["utc"] if xcol == "date" else r[xcol])
        for g in sorted({str(r.get(group)) for r in pts}):
            sub = [r for r in pts if str(r.get(group)) == g]
            fig.add_trace(go.Scatter(x=[xv(r) for r in sub], y=[r[ycol] for r in sub], mode="markers", name=g,
                                     text=[f"{r.get('call') or r.get('kind') or ''} {r['utc']:%Y-%m-%d %H:%M}" if r.get("utc") else ""
                                           for r in sub], hovertemplate="%{text}<br>x=%{x}<br>y=%{y}<extra></extra>",
                                     marker=dict(size=8, opacity=0.8)))
        if fk != "none":
            x = np.array([r[xcol] for r in pts], float)
            y = np.array([r[ycol] for r in pts], float)
            f = plots.fit(x, y, fk, span)
            if "xs" in f:
                xs = f["xs"]
                xs_plot = pd.to_datetime(xs * 86400, unit="s") if xcol == "date" else xs
                if fk == "bins":
                    fig.add_trace(go.Scatter(x=xs_plot, y=f["ys"], mode="lines+markers", name=i18n.tr("Mediana per classe"),
                                             line=dict(color="black", width=3),
                                             error_y=dict(type="data", symmetric=False, array=f["hi"] - f["ys"], arrayminus=f["ys"] - f["lo"])))
                else:
                    fig.add_trace(go.Scatter(x=xs_plot, y=f["ys"], mode="lines", name=i18n.tr(plots.FITS[fk]),
                                             line=dict(color="black", width=3)))
                m = st.columns(4)
                m[0].metric("Punti", f["n"])
                m[1].metric("R²", f"{f['r2']:.3f}" if math.isfinite(f.get("r2", float("nan"))) else "–")
                m[2].metric("Scarto quadratico medio", f"{f['rmse']:.2f}")
                if f.get("equation"):
                    per = " (" + i18n.tr("x in giorni") + ")" if xcol == "date" else ""
                    m[3].metric("Pendenza", f"{f['coef'][-2]:+.3g}" + (f" ± {f['slope_err']:.2g}" if f.get("slope_err") else ""),
                                help=i18n.tr("variazione di Y per unità di X") + per)
                    st.caption(f["equation"] + per)
                with st.expander("Residui (misura − interpolazione)"):
                    rf = go.Figure(go.Scatter(x=pd.to_datetime(f["x"] * 86400, unit="s") if xcol == "date" else f["x"],
                                              y=f["residuals"], mode="markers"))
                    rf.add_hline(y=0, line_color="gray")
                    rf.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), xaxis_title=fmt(xcol), yaxis_title="Δ")
                    st.plotly_chart(rf, width="stretch")
        fig.update_layout(xaxis_title=fmt(xcol) if xcol != "date" else "UTC", yaxis_title=fmt(ycol))
    fig.update_layout(height=460, margin=dict(l=10, r=10, t=30, b=10), legend_title_text="")
    st.plotly_chart(fig, width="stretch")
    df = pd.DataFrame([{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()} for r in pts])
    st.download_button("⬇️ Dati del grafico (CSV)", df.to_csv(index=False).encode(), key="pl_csv",
                       file_name="emelab_grafico.csv" if i18n.get_lang() == "it" else "emelab_chart.csv")


# ------------------------------------------------------------------ chain sections
def _setup_pick(D, key):
    sets = D.setups()
    if not sets:
        return None
    sid = st.selectbox("Configurazione", [s["id"] for s in sets], key=key,
                       format_func=lambda i: next(f"{s['name']} ({_bl(s['band_ghz'])})" for s in sets if s["id"] == i))
    return next(s for s in sets if s["id"] == sid)


def _pointing_tab(D):
    from emelab import chain, sunscan
    st.subheader("Tracking")
    st.caption("Bilancio degli errori di puntamento: ogni causa indipendente si somma in quadratura (RSS). La perdita su un "
               "fascio gaussiano è −12·(θ/HPBW)² dB in una direzione; le eco proprie e il rumore solare la vedono due volte.")
    s = _setup_pick(D, "pt_setup")
    c = st.columns(3)
    f = c[0].number_input("Frequenza (GHz)", 10.0, 140.0, float(s["band_ghz"]) if s else 24.048, key="pt_f")
    Dm = c[1].number_input("Diametro parabola (m)", 0.3, 10.0, float(s["D_m"]) if s else 1.2, 0.1, key="pt_D")
    taper = c[2].number_input("Taper al bordo (dB)", 0.0, 25.0, float((s or {}).get("edge_taper_db") or 12.0), key="pt_tp")
    hp = sunscan.hpbw_deg(f, Dm, sunscan.k_from_taper(taper))
    st.markdown(f"**HPBW {hp:.3f}°** · " + i18n.tr("diametro apparente della Luna") + " ≈ 0.49–0.56° · " +
                i18n.tr("obiettivo: errore totale sotto") + f" **{hp / 10:.3f}°** (HPBW/10 → −0.12 dB)")
    c = st.columns(5)
    bits = c[0].number_input("Bit dell'encoder", 8, 24, 18, key="pt_bits")
    back = c[1].number_input("Gioco meccanico (°)", 0.0, 1.0, 0.02, 0.005, format="%.3f", key="pt_back")
    model = c[2].number_input("Residuo del modello di puntamento (°)", 0.0, 1.0, 0.03, 0.005, format="%.3f", key="pt_mod",
                              help="dalla scheda Analisi: RMS dopo la correzione con le misure di sole")
    wind = c[3].number_input("Flessione con il vento (°)", 0.0, 1.0, 0.02, 0.005, format="%.3f", key="pt_wind")
    track = c[4].number_input("Passo di inseguimento (°)", 0.0, 1.0, 0.02, 0.005, format="%.3f", key="pt_trk",
                              help="di quanto si sposta la Luna prima che il rotore corregga (metà del passo come errore medio)")
    b = chain.pointing_budget(hp, {"Encoder (½ passo)": chain.encoder_step_deg(int(bits)) / 2, "Gioco": back,
                                   "Modello": model, "Vento": wind, "Inseguimento (½ passo)": track / 2})
    m = st.columns(4)
    m[0].metric("Errore totale (RSS)", f"{b['rss_deg']:.3f}°", f"{b['fraction_hpbw']:.2f} HPBW", delta_color="off")
    m[1].metric("Perdita in una direzione", f"{b['loss_one_way_db']:.2f} dB")
    m[2].metric("Perdita sulle eco proprie", f"{b['loss_echo_db']:.2f} dB")
    m[3].metric("Moto della Luna", "≈ 0.25°/min", help=i18n.tr("in cielo la Luna si sposta di circa 15° all'ora"))
    st.dataframe([{"Causa": k, "Errore (°)": round(v, 4), "Perdita da sola (dB)": round(l, 3)} for k, (v, l) in b["terms"].items()],
                 hide_index=True, width="stretch")
    import numpy as _np
    th = _np.linspace(0, hp, 60)
    fig = go.Figure(go.Scatter(x=th, y=-12 * (th / hp) ** 2, name="una direzione"))
    fig.add_trace(go.Scatter(x=th, y=-24 * (th / hp) ** 2, name="eco proprie"))
    fig.add_vline(x=b["rss_deg"], line_dash="dot")
    fig.update_layout(title="Perdita contro errore di puntamento", xaxis_title="°", yaxis_title="dB", height=320,
                      margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    _sunscan_box(D, s, f, Dm, hp)
    _pointing_model_box(D, hp)
    from emelab import ui_tracking
    ui_tracking.tracking_box(D, hp)
    with st.expander("💡 Strategie per puntare meglio"):
        st.markdown("\n".join("- " + i18n.tr(x) for x in [
            "Misura il sole in molti punti di azimut ed elevazione: il modello di puntamento (zero AZ/EL, inclinazione dell'asse, flessione) si stima solo con dati ben distribuiti.",
            "Fai scansioni a croce o a 5 punti sul sole: l'offset del massimo è l'errore di puntamento in quel punto.",
            "A 24 e 47 GHz controlla il fuoco prima del puntamento: un feed fuori fuoco sposta e allarga il fascio.",
            "Usa la rifrazione radio, non quella ottica: sotto i 10° di elevazione la differenza supera il decimo di grado.",
            "Insegui con passi piccoli (meno di HPBW/10) e con il gioco sempre recuperato nello stesso verso.",
            "Con vento forte la flessione cresce con il quadrato della velocità: pianifica le prove nelle ore calme (vedi Pianificatore).",
            "Verifica sulla Luna: il massimo del rumore lunare deve coincidere con la posizione calcolata."]))


def _lna_tab(D):
    from emelab import chain
    st.subheader("LNA e ricezione")
    st.caption("Ogni decimo di dB perso prima dell'LNA aggiunge circa 7 K: le perdite tra feed e LNA contano quanto la NF. "
               "Qui vedi quanto pesa ogni elemento e quanto G/T guadagni migliorandolo.")
    s = _setup_pick(D, "ln_setup")
    c = st.columns(4)
    gain = c[0].number_input("Guadagno antenna (dBi)", 20.0, 80.0, float((s or {}).get("gain_dbi") or 46.0), 0.1, key="ln_g")
    t_ant = c[1].number_input("Temperatura d'antenna (K)", 3.0, 400.0, 40.0, 1.0, key="ln_ta",
                              help="cielo + spillover verso terra, verso il cielo freddo")
    tphys = c[2].number_input("Temperatura fisica delle perdite (K)", 200.0, 340.0, 290.0, 1.0, key="ln_tp")
    c = st.columns(4)
    l_pre = c[0].number_input("Perdita prima dell'LNA (dB)", 0.0, 3.0, float((s or {}).get("line_loss_db") or 0.2), 0.05, key="ln_lp",
                              help="relè, guida, transizioni, finestra")
    nf1 = c[1].number_input("NF LNA (dB)", 0.1, 10.0, float((s or {}).get("nf_db") or 1.3), 0.05, key="ln_nf")
    g1 = c[2].number_input("Guadagno LNA (dB)", 5.0, 50.0, 25.0, 0.5, key="ln_g1")
    nf2 = c[3].number_input("NF dello stadio dopo (transverter, cavo…) (dB)", 0.5, 20.0, 8.0, 0.5, key="ln_nf2")
    stages = [chain.passive("Perdite prima dell'LNA", l_pre, tphys), {"name": "LNA", "gain_db": g1, "nf_db": nf1},
              {"name": "Stadio successivo", "gain_db": 10.0, "nf_db": nf2}]
    r = chain.rx_chain(stages, t_ant)
    gt = gain - 10 * math.log10(r["tsys_K"])
    m = st.columns(4)
    m[0].metric("NF del sistema", f"{r['nf_db']:.2f} dB")
    m[1].metric("Tsys", f"{r['tsys_K']:.0f} K")
    m[2].metric("G/T", f"{gt:.2f} dB/K")
    m[3].metric("Contributo dell'LNA", f"{r['stages'][1]['share_pct']:.0f} %")

    def gt_with(**kw):
        p = dict(l_pre=l_pre, nf1=nf1, g1=g1, nf2=nf2)
        p.update(kw)
        rr = chain.rx_chain([chain.passive("a", p["l_pre"], tphys), {"name": "b", "gain_db": p["g1"], "nf_db": p["nf1"]},
                             {"name": "c", "gain_db": 10.0, "nf_db": p["nf2"]}], t_ant)
        return gain - 10 * math.log10(rr["tsys_K"])
    st.dataframe([{"Miglioramento": i18n.tr(n), "ΔG/T (dB)": round(gt_with(**kw) - gt, 2)} for n, kw in [
        ("Perdita prima dell'LNA −0.1 dB", {"l_pre": max(l_pre - 0.1, 0)}),
        ("LNA direttamente sul feed (perdita 0.05 dB)", {"l_pre": 0.05}),
        ("NF LNA −0.3 dB", {"nf1": max(nf1 - 0.3, 0.1)}),
        ("Guadagno LNA +10 dB", {"g1": g1 + 10}),
        ("Secondo LNA (stadio dopo con NF 2 dB)", {"nf2": 2.0})]], hide_index=True, width="stretch")
    st.caption("Confronta la NF del datasheet con quella che risulta dal rumore solare (scheda Analisi): la differenza "
               "racconta le perdite nascoste e il fuoco.")
    st.divider()
    _catalog_box(D, ("LNA", "SW"), "ln")


POWER_BANDS = [10.368, 24.048, 47.088, 76.032, 122.25, 134.928]


def _power_devices() -> dict:
    """per band: {"kind": "PA"/"TWT"/"", "part": name, "maker": maker} — saved only on this PC"""
    return dict(openems_local.load_settings().get("power_devices") or {})


def _power_rows(D, band, kind):
    """catalogue devices with the user's corrections, then the user's own devices (same list as the catalogue box)"""
    from emelab import parts
    return parts.devices(D, band, kind)


def _power_apply(dev, kind):
    """the chosen device fills the numbers of its tab (they stay editable)"""
    ss = _st.session_state
    if not dev:
        return
    if kind == "PA":
        if dev.get("psat_dbm"):
            ss["sp_psat"] = float(dev["psat_dbm"])
        if dev.get("gain_db"):
            ss["sp_g"] = float(dev["gain_db"])
    elif kind == "TWT" and dev.get("psat_dbm"):
        ss["tw_ps"] = round(10 ** ((float(dev["psat_dbm"]) - 30) / 10), 1)


def _power_save_cb(D, band):
    ss = _st.session_state
    kind = ss.get("pw_kind")
    kind = {"SSPA": "PA", "TWT": "TWT"}.get(kind, "")
    rows = _power_rows(D, band, kind) if kind else []
    i = ss.get(f"pw_dev_{kind}")
    if not isinstance(i, int) or i >= len(rows):      # the selector was not on screen: saved device, else the first one
        old = _power_devices().get(f"{band:g}", {})
        i = next((j for j, r in enumerate(rows) if r["part"] == old.get("part")), 0)
    dev = rows[i] if rows else None
    allp = _power_devices()
    allp[f"{band:g}"] = {"kind": kind, "part": dev["part"] if dev else "", "maker": dev["maker"] if dev else ""}
    openems_local.save_settings(power_devices=allp)
    _power_apply(dev, kind)


def _power_tab(D):
    """Power amplifier of each band: the user says whether it is an SSPA or a TWT and which device; only that model shows."""
    st.subheader("⚡ Amplificatore di potenza per banda")
    st.caption("Per ogni banda scegli se usi un SSPA (stato solido) o un TWT e quale dispositivo: i suoi dati dal catalogo "
               "riempiono il calcolo qui sotto. La scelta resta salvata su questo PC.")
    allp = _power_devices()
    ss = _st.session_state
    c = st.columns([1, 1, 2])
    band = c[0].selectbox("Banda", POWER_BANDS, key="pw_band", format_func=_bl)
    cur = allp.get(f"{band:g}", {})
    if ss.get("pw_band_prev") != band:                   # new band: show what was saved for it
        ss["pw_band_prev"] = band
        ss["pw_kind"] = {"PA": "SSPA", "TWT": "TWT"}.get(cur.get("kind"), "SSPA" if band < 20 else "TWT" if band < 30 else "SSPA")
        for k in ("PA", "TWT"):
            rows = _power_rows(D, band, k)
            idx = next((i for i, r in enumerate(rows) if r["part"] == cur.get("part")), 0)
            ss[f"pw_dev_{k}"] = idx
            if cur.get("kind") == k and rows:
                _power_apply(rows[idx], k)
    kind_l = c[1].radio("Tipo di amplificatore", ["SSPA", "TWT"], key="pw_kind", horizontal=True,
                        on_change=_power_save_cb, args=(D, band))
    kind = "PA" if kind_l == "SSPA" else "TWT"
    rows = _power_rows(D, band, kind)
    if rows:
        if ss.get(f"pw_dev_{kind}", 0) >= len(rows):
            ss[f"pw_dev_{kind}"] = 0
        i = c[2].selectbox("Il tuo dispositivo", range(len(rows)), key=f"pw_dev_{kind}",
                           format_func=lambda i: f"{rows[i]['part']} — {i18n.tr(rows[i]['maker'])}" +
                                                 (" ⚠️" if rows[i].get("check") else " ✅" if rows[i].get("verified") else ""),
                           on_change=_power_save_cb, args=(D, band))
        dev = rows[i]
        if ("sp_psat" if kind == "PA" else "tw_ps") not in ss:     # numbers not on screen yet: from the device
            _power_apply(dev, kind)
        info = [f"Psat {dev['psat_dbm']:.1f} dBm ({10 ** ((dev['psat_dbm'] - 30) / 10):.1f} W)" if dev.get("psat_dbm") else None,
                f"{i18n.tr('guadagno')} {dev['gain_db']:.0f} dB" if dev.get("gain_db") else None,
                i18n.tr(dev.get("notes")) if dev.get("notes") else None,
                i18n.tr("fonte") + ": " + i18n.tr(dev.get("source")) if dev.get("source") else None]
        st.info(" · ".join(x for x in info if x) + ("  \n⚠️ " + i18n.tr("valori tipici da confermare sul datasheet") if dev.get("check") else
                                                    "  \n✅ " + i18n.tr("valori verificati da te") if dev.get("verified") else "") +
                "  \n" + i18n.tr("Per correggerli: «✏️ Correggi a mano» nel Catalogo dispositivi in fondo alla pagina."))
        if not cur or cur.get("part") != dev["part"] or cur.get("kind") != kind:
            if st.button("💾 Usa questo dispositivo su questa banda", key="pw_save", type="primary"):
                _power_save_cb(D, band)
                st.rerun()
    else:
        c[2].info("Nessun dispositivo in catalogo per questa banda: aggiungilo a mano o dal datasheet nel catalogo qui sotto.")
    done = {k: v for k, v in _power_devices().items() if v.get("kind")}
    if done:
        st.markdown(i18n.tr("La tua stazione") + ": " + " · ".join(
            f"**{_bl(float(b))}** {'SSPA' if v['kind'] == 'PA' else 'TWT'} {v.get('part') or ''}" for b, v in
            sorted(done.items(), key=lambda x: float(x[0]))))
    st.divider()
    if kind == "PA":
        _sspa_tab(D)
    else:
        _twt_tab(D)


def _sspa_tab(D):
    import numpy as _np
    from emelab import chain
    st.subheader("SSPA")
    st.caption("Amplificatori a stato solido: compressione con il modello di Rapp, combinazione di più moduli, perdite fino "
               "al feed, consumo e dissipatore. In Q65 si trasmette un periodo sì e uno no (50 %).")
    c = st.columns(4)
    _st.session_state.setdefault("sp_psat", 43.0)          # set by the device chosen in ⚡ RF Power
    psat = c[0].number_input("Psat di un modulo (dBm)", 10.0, 60.0, step=0.5, key="sp_psat")
    _st.session_state.setdefault("sp_g", 30.0)          # set by the device chosen in ⚡ RF Power
    g = c[1].number_input("Guadagno (dB)", 5.0, 60.0, step=0.5, key="sp_g")
    s_r = c[2].number_input("Morbidezza di Rapp s", 0.5, 10.0, 2.0, 0.5, key="sp_s", help="2 tipico GaAs/GaN; alto = limitatore netto")
    pin = c[3].number_input("Potenza di pilotaggio (dBm)", -20.0, 40.0, 10.0, 0.5, key="sp_pin")
    c = st.columns(4)
    n = c[0].number_input("Moduli combinati", 1, 16, 1, key="sp_n")
    lc = c[1].number_input("Perdita del combinatore (dB)", 0.0, 3.0, 0.3, 0.05, key="sp_lc", disabled=n == 1)
    lout = c[2].number_input("Perdita fino al feed (dB)", 0.0, 6.0, 0.5, 0.05, key="sp_lo", help="guida, relè, isolatore")
    eff = c[3].number_input("Efficienza (PAE, %)", 5.0, 70.0, 25.0, 1.0, key="sp_eff")
    one = chain.rapp_dbm(pin + g, psat, s_r)
    tot = chain.combine(one, int(n), lc) - lout
    pw = 10 ** ((tot - 30) / 10)
    pdc = int(n) * 10 ** ((one - 30) / 10) / (eff / 100)
    heat = pdc - 10 ** ((chain.combine(one, int(n), lc) - 30) / 10)
    m = st.columns(4)
    m[0].metric("Potenza al feed", f"{pw:.1f} W", f"{tot:.1f} dBm", delta_color="off")
    m[1].metric("Compressione", f"{(pin + g) - one:.1f} dB")
    m[2].metric("Consumo DC", f"{pdc:.0f} W")
    m[3].metric("Dissipatore", f"≤ {chain.heatsink_rth(heat):.2f} K/W",
                help=i18n.tr("resistenza termica massima per restare sotto 70 °C con 35 °C d'aria e il 50 % di trasmissione"))
    x = _np.linspace(pin - 25, pin + 10, 80)
    y = [chain.rapp_dbm(v + g, psat, s_r) for v in x]
    fig = go.Figure(go.Scatter(x=x, y=y, name="Rapp"))
    fig.add_trace(go.Scatter(x=x, y=x + g, name="lineare", line=dict(dash="dot")))
    fig.add_vline(x=pin, line_dash="dot")
    fig.update_layout(title="Uscita di un modulo contro pilotaggio", xaxis_title="Pin (dBm)", yaxis_title="Pout (dBm)",
                      height=320, margin=dict(l=10, r=10, t=40, b=10), yaxis_range=[min(y) - 3, psat + 3])
    st.plotly_chart(fig, width="stretch")
    st.caption("Lavora 1–2 dB sotto la saturazione: Q65 è a inviluppo costante, ma un margine protegge i transistor e "
               "riduce il calore.")
    st.divider()
    dev = _catalog_box(D, ("PA",), "sp")
    _heatsink_box(dev, 10 ** ((tot + lout - 30) / 10) / max(int(n), 1), eff, "sp")


def _twt_tab(D):
    import numpy as _np
    from emelab import chain
    st.subheader("TWT")
    st.caption("Tubo a onda progressiva: caratteristica AM/AM e AM/PM con il modello di Saleh, alimentazioni, efficienza e "
               "perdite fino al feed. Il tubo va pilotato vicino alla saturazione, non oltre: oltre il picco la potenza cala.")
    c = st.columns(4)
    _st.session_state.setdefault("tw_ps", 20.0)          # set by the device chosen in ⚡ RF Power
    psat = c[0].number_input("Potenza di saturazione (W)", 1.0, 500.0, step=1.0, key="tw_ps")
    g0 = c[1].number_input("Guadagno di piccolo segnale (dB)", 20.0, 60.0, 35.0, 0.5, key="tw_g")
    pin = c[2].number_input("Pilotaggio (dBm)", -20.0, 30.0, 10.0, 0.5, key="tw_pin")
    lout = c[3].number_input("Perdita fino al feed (dB)", 0.0, 6.0, 0.4, 0.05, key="tw_lo")
    c = st.columns(4)
    vh = c[0].number_input("Tensione d'elica (V)", 0.0, 20000.0, 4000.0, 50.0, key="tw_vh")
    ih = c[1].number_input("Corrente di catodo (mA)", 0.0, 2000.0, 60.0, 1.0, key="tw_ih")
    pf = c[2].number_input("Filamento (W)", 0.0, 50.0, 6.0, 0.5, key="tw_pf")
    pa = c[3].number_input("Ausiliari (ventole, controllo) (W)", 0.0, 500.0, 20.0, 1.0, key="tw_pa")
    ps_dbm = 10 * math.log10(psat * 1000)
    out, ph = chain.saleh(pin, ps_dbm, g0)
    at_feed = out - lout
    pdc = vh * ih / 1000 * 0.6 + pf + pa            # collector depression returns ~40 % (typical single-stage)
    m = st.columns(4)
    m[0].metric("Potenza al feed", f"{10 ** ((at_feed - 30) / 10):.1f} W", f"{at_feed:.1f} dBm", delta_color="off")
    m[1].metric("Pilotaggio per la saturazione", f"{chain.saleh_drive_for_sat(ps_dbm, g0):.1f} dBm")
    m[2].metric("Spostamento di fase AM/PM", f"{ph:.1f}°")
    m[3].metric("Consumo stimato", f"{pdc:.0f} W", help=i18n.tr("con collettore depresso che recupera circa il 40 % della potenza del fascio"))
    x = _np.linspace(pin - 25, chain.saleh_drive_for_sat(ps_dbm, g0) + 8, 90)
    y = [chain.saleh(v, ps_dbm, g0) for v in x]
    fig = go.Figure(go.Scatter(x=x, y=[a for a, _ in y], name="AM/AM"))
    fig.add_trace(go.Scatter(x=x, y=[p for _, p in y], name="AM/PM (°)", yaxis="y2"))
    fig.add_vline(x=pin, line_dash="dot")
    fig.update_layout(title="Caratteristica del tubo (Saleh)", xaxis_title="Pin (dBm)", yaxis_title="Pout (dBm)",
                      yaxis2=dict(overlaying="y", side="right", title="°"), height=340, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    _catalog_box(D, ("TWT",), "tw")
    with st.expander("🔧 Buone pratiche con i TWT"):
        st.markdown("\n".join("- " + i18n.tr(x) for x in [
            "Scalda il filamento per il tempo indicato dal costruttore prima di dare l'alta tensione.",
            "Il relè o lo switch d'antenna deve commutare prima della trasmissione: sequencer con ritardi adeguati.",
            "Non superare la saturazione: oltre il picco la potenza cala e la corrente d'elica cresce.",
            "Controlla la corrente d'elica: se aumenta, il fascio non è ben focalizzato o il carico è disadattato.",
            "Annota le ore di catodo nel diario: l'emissione cala con l'uso e la potenza di saturazione con lei."]))


# ------------------------------------------------------------------ signal of a station, who can I work
def _my_model(setup: dict, band: str) -> dict:
    from emelab import dx
    tsys = analysis.tsys_cold(setup, 0.0)["sys"]
    m = dx.station(band, float(setup["D_m"]), float(setup.get("tx_w") or 0) or None, "offset",
                   tsys_K=tsys, eta=float(setup.get("eta_ap") or 0.6), line_loss_db=0.0)
    m["pol"] = setup.get("pol") or openems_local.load_settings().get("my_pol")
    return m


def _band_of_setup(setup):
    from emelab import dx
    return min(dx.BAND_GHZ, key=lambda b: abs(dx.BAND_GHZ[b] - float(setup["band_ghz"])))


def _dx_models(D, band):
    from emelab import dx
    out = []
    for r in D.stations():
        e = D.directory_of(r.get("data", {})).get(band)
        if not e or not r.get("locator"):
            continue
        m = dx.from_directory(e, band)
        try:
            loc = astro.locator_to_latlon(r["locator"])
        except Exception:
            continue
        if m:
            m["pol"] = (r.get("data", {}).get("pol") or {}).get(band)
            out.append({"call": r["call"], "locator": r["locator"], "loc": loc, "model": m, "antenna": e.get("antenna"),
                        "power_w": e.get("power_w"), "heard": (r.get("data", {}).get("heard") or {}).get("n")})
    return out


def _model_at(D, band, t, me_now):
    """Your station as it was at time t on this band (station history), or the current configuration."""
    from emelab import dx
    h = D.setup_at(band, t)
    if not h or not h.get("dish_m"):
        return me_now, None
    m = dx.station(band, float(h["dish_m"]), h.get("power_w") or me_now.get("power_w"), h.get("dish_kind") or "offset",
                   tsys_K=None, eta=h.get("eta") or None)
    if h.get("nf_db") is not None:
        tsys_setup = {"nf_db": h["nf_db"], "line_loss_db": h.get("line_loss_db") or 0.0, "spill": 0.9}
        m["tsys_K"] = analysis.tsys_cold(tsys_setup, 0.0)["sys"]
    else:
        m["tsys_K"] = me_now["tsys_K"]
    m["pol"] = h.get("pol") or me_now.get("pol")
    return m, h["from_utc"][:10]


def _learned_offset(D, band, me, my_loc, models):
    """Median of (reported − predicted) on the QSOs of this band, each QSO with the station of its period (station
    history): what EMELab has learned about your station, overall and period by period."""
    from emelab import dx
    key = ("em_offset", band, len(D.qsos(band=band)), len(D.history(band)))
    if _st.session_state.get("em_off_key") == key:
        return _st.session_state["em_off"]
    by = {m["call"]: m for m in models}
    pairs, per = [], {}
    for q in D.qsos(band=band)[-200:]:
        m = by.get(q["call"])
        v = _num_rst(q.get("rst_sent"))
        if not m or v is None:
            continue
        t = edb.parse_utc(q["utc"]) if isinstance(q["utc"], str) else q["utc"]
        mine, epoch = _model_at(D, band, t, me)
        r = dx.link_at(t, mine, my_loc, m["model"], m["loc"], band)
        if r:
            pairs.append((v, r["snr_a_hears_b"]))
            per.setdefault(epoch or "configurazione attuale", []).append((v, r["snr_a_hears_b"]))
    res = dx.learn_offset(pairs)
    res["epochs"] = {k: dx.learn_offset(v) for k, v in sorted(per.items())}
    _st.session_state["em_off_key"], _st.session_state["em_off"] = key, res
    return res


ASSUMED_COLOR = "#e8590c"        # assumed values (e.g. a Q65 submode the log does not say): orange


def _num_rst(v):
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _model_header(D, stn, setup, band):
    """Your station in the model and what EMELab learned from your QSOs (shared by the sub-tabs)."""
    me = _my_model(setup, band)
    my_loc = (stn["lat"], stn["lon"])
    models = _dx_models(D, band)
    off = _learned_offset(D, band, me, my_loc, models)
    return me, my_loc, models, off


def _rank_view(D, stn, s, band, q65):
    from emelab import dx
    me, my_loc, models, off = _model_header(D, stn, s, band)
    if not models:
        st.info("Importa la EME Directory (scheda Stazioni EME) per avere antenna e potenza delle altre stazioni.")
        return
    m = st.columns(4)
    m[0].metric("La tua stazione", f"{me['D_m']:.2f} m · {me['power_w']:.0f} W")
    m[1].metric("Tsys senza Luna", f"{me['tsys_K']:.0f} K")
    m[2].metric("Correzione appresa dai QSO", f"{off['offset_db']:+.1f} dB" if off["n"] else "–",
                f"n={off['n']}" + (f", ±{off['mad_db']:.1f} dB" if off.get("mad_db") else ""), delta_color="off")
    m[3].metric("Stazioni con dati", len(models))
    if len(off.get("epochs", {})) > 1 or (off.get("epochs") and "configurazione attuale" not in off["epochs"]):
        with st.expander("📜 Correzione per periodo (storico della stazione)"):
            st.dataframe([{"Dal": i18n.tr(k), "QSO": v["n"], "Misura − teoria (dB)": round(v["offset_db"], 1),
                           "Dispersione (dB)": round(v["mad_db"], 1) if v.get("mad_db") is not None else None}
                          for k, v in off["epochs"].items()], hide_index=True, width="stretch")
            st.caption("Quanto i rapporti che hai dato (come ricevevi l'altra stazione) si scostano dal modello in ogni "
                       "periodo: un valore molto negativo indica perdite, puntamento o Tsys peggiori del previsto.")
    c = st.columns(3)
    hours = c[0].number_input("Prossime ore", 6, 336, 48, 6, key="sg_h")
    min_el = c[1].number_input("Elevazione minima (°)", 0.0, 60.0, 10.0, 1.0, key="sg_el")
    if c[2].button("🏆 Calcola la classifica", type="primary", key="sg_go"):
        with st.spinner("Calcolo delle finestre comuni…"):
            _st.session_state["sg_rank"] = dx.rank(me, my_loc, models, band, datetime.now(timezone.utc), float(hours),
                                                   30.0, float(min_el), off["offset_db"] if off["n"] >= 5 else 0.0,
                                                   mode=q65, my_ok=_my_moon_ok(stn))
            _st.session_state["sg_rank_key"] = (band, q65)
    rk = _st.session_state.get("sg_rank") if _st.session_state.get("sg_rank_key") == (band, q65) else None
    if rk:
        st.dataframe([{"Nominativo": r["call"], "Locator": r["locator"], "Antenna": r.get("antenna"), "Potenza (W)": r.get("power_w"),
                       "Probabilità": f"{100 * r['probability']:.0f} %",
                       "Momento migliore (UTC)": r["best"]["utc"].strftime("%Y-%m-%d %H:%M") if r["best"] else "–",
                       "Ore in comune": round(r["hours_common"], 1),
                       "Lo ricevi a (dB)": round(r["best"]["snr_a_hears_b"] + (off["offset_db"] if off["n"] >= 5 else 0), 1) if r["best"] else None,
                       "Ti riceve a (dB)": round(r["best"]["snr_b_hears_a"], 1) if r["best"] else None,
                       "Modo": r["best"]["mode"] if r["best"] else "", "Spread (Hz)": round(r["best"]["spread_hz"]) if r["best"] else None,
                       "Dpol (°)": round(r["best"]["dpol_deg"]) if r["best"] else None,
                       "Margine (dB)": round(r["best"]["margin_db"], 1) if r["best"] else None,
                       "Sentito (ALL.TXT)": str(r["heard"]) if r.get("heard") else "",
                       "Nota": ("⚠️ " + i18n.tr("spread oltre la tolleranza")) if r["best"] and not r["best"]["spread_ok"] else ""}
                      for r in rk], hide_index=True, width="stretch",
                     **_open_in_planner_kw(rk, s, float(min_el)))
        st.caption("👆 " + i18n.tr("Clicca una riga o un nominativo: diventa la stazione in alto e si aprono le sue finestre."))
        if any(r["best"] and not r["best"]["spread_ok"] for r in rk):
            st.warning(f"Per alcune stazioni il mutual spread supera quello che Q65-{q65} tollera "
                       f"({dx.Q65_SPREAD_MAX[q65]:.0f} Hz): la soglia è estrapolata e il margine penalizzato.")
        st.caption("Probabilità stimata dal margine sulla soglia Q65 (±2 dB di incertezza tra modello e QSB). "
                   "«Sentito» = quante decodifiche hai di quella stazione nel tuo ALL.TXT.")


def _wx_day(lat, lon, d0):
    """Open-Meteo hourly forecast for one UTC day at a place, {hour datetime: values}; kept for the session."""
    key = ("pl_wx", round(lat, 2), round(lon, 2), str(d0))
    S = _st.session_state
    if key not in S:
        t0 = datetime.combine(d0, time(0, 0), tzinfo=timezone.utc)
        try:
            S[key] = {w["utc"]: w for w in weather.open_meteo_series(lat, lon, t0, 1)}
        except Exception as e:                     # remembered: no new wait at every click while offline
            S[key] = e
    if isinstance(S[key], Exception):
        raise S[key]
    return S[key]


def _wx_cell(w) -> str:
    if not w:
        return ""
    parts = [f"{w['t_c']:.0f}°C" if w.get("t_c") is not None else "", f"{w['rh']:.0f}%" if w.get("rh") is not None else ""]
    if w.get("rain_prob") is not None:
        parts.append(f"☔{w['rain_prob']:.0f}%")
    if w.get("rain_mmh"):
        parts.append(f"{w['rain_mmh']:.1f} mm/h")
    if w.get("gust_ms") is not None:
        parts.append(f"💨{w['gust_ms']:.0f} m/s")
    return " ".join(p for p in parts if p)


def _signal_view(D, stn, setup, band, q65, dxs, use_fc):
    """The signal of one day with the station chosen at the top: SNR both ways, threshold, where the Moon is from
    both stations, local times and the weather at both ends (Open-Meteo, from the locators)."""
    from emelab import dx, tz, wizard
    if not dxs:
        st.info("Scegli la stazione corrispondente in alto (nominativo o locator) per vedere il segnale.")
        return
    me, my_loc, models, off = _model_header(D, stn, setup, band)
    offset = off["offset_db"] if off["n"] >= 5 else 0.0
    call = dxs["call"]
    model, assumed = _planner_dx_model(D, band, call, dxs["locator"])
    k = call or dxs["locator"]
    c = st.columns(3)
    d0 = c[0].date_input("Giorno (UTC)", datetime.now(timezone.utc).date(), key="sg_day")
    pw = c[1].number_input("Sua potenza (W)", 0.1, 2000.0, float(model["power_w"]), key=f"sg_pw_{k}_{band}")
    dd = c[2].number_input("Sua parabola (m)", 0.3, 20.0, float(model["D_m"]), 0.1, key=f"sg_dd_{k}_{band}")
    POLS = {"V": "Verticale", "H": "Orizzontale", "HV": "Commutabile H/V"}
    c = st.columns(2)
    my_def = me.get("pol") or dx.default_pol(*my_loc)
    my_pol = c[0].selectbox("La tua polarizzazione", list(POLS), index=list(POLS).index(my_def), key="sg_mypol",
                            format_func=lambda k: POLS[k], help="lineare: in Europa e nel resto del mondo di solito "
                            "verticale, in Nord America orizzontale")
    dx_def = model.get("pol") or dx.default_pol(*dxs["loc"])
    dx_pol = c[1].selectbox("Sua polarizzazione", list(POLS), index=list(POLS).index(dx_def), key=f"sg_dxpol_{k}",
                            format_func=lambda k: POLS[k])
    if (my_pol != my_def or dx_pol != dx_def) and call:
        if c[0].button("💾 Ricorda le polarizzazioni", key="sg_polsave"):
            openems_local.save_settings(my_pol=my_pol)
            data = (D.station_of(call) or {}).get("data", {})
            D.upsert_station(call, data={"pol": {**(data.get("pol") or {}), band: dx_pol}})
            D.commit()
    me = dict(me, pol=my_pol)
    other = dx.station(band, dd, pw if pw != float(model["power_w"]) or "potenza" not in assumed else None,
                       model.get("kind", "prime"), assumed=tuple(a for a in assumed if a not in ("potenza", "Tsys", "efficienza")))
    other["pol"] = dx_pol
    wx_me = wx_dx = {}
    if use_fc and 0 <= (d0 - datetime.now(timezone.utc).date()).days < 16:
        try:
            wx_me = _wx_day(my_loc[0], my_loc[1], d0)
            wx_dx = _wx_day(dxs["loc"][0], dxs["loc"][1], d0)
        except Exception as e:
            st.warning(i18n.tr("Previsioni non disponibili") + f": {e}")
    elif use_fc:
        st.caption("Previsioni meteo solo per i prossimi 16 giorni: per questo giorno valori tipici.")
    hz = _my_horizon()
    h_me = stn.get("height_m") or 0.0
    rows, table = [], []
    t0 = datetime.combine(d0, time(0, 0), tzinfo=timezone.utc)
    for i in range(0, 24 * 4):
        t = t0 + timedelta(minutes=15 * i)
        hr = t.replace(minute=0)
        mb = planner.moon_both(t, my_loc, dxs["loc"], h_me)
        if hz and not wizard.visible(hz, mb["az_me"], mb["el_me"]):
            continue                                   # Moon behind your obstacles
        r = dx.link_at(t, me, my_loc, other, dxs["loc"], band, wx_a=wx_me.get(hr), wx_b=wx_dx.get(hr), h_a=h_me, mode=q65)
        if not r:
            continue
        rows.append(r)
        if t.minute % 30 == 0:
            lt_me, lt_dx = tz.local_time(*my_loc, t), tz.local_time(*dxs["loc"], t)
            row = {"UTC": t.strftime("%H:%M"), "Ora locale (te)": lt_me[0].strftime("%H:%M") + ("*" if lt_me[2] else ""),
                   "Ora locale DX": lt_dx[0].strftime("%H:%M") + ("*" if lt_dx[2] else ""),
                   "Luna da te AZ/EL (°)": f"{mb['az_me']:.0f} / {mb['el_me']:.0f}",
                   "Luna dal DX AZ/EL (°)": f"{mb['az_dx']:.0f} / {mb['el_dx']:.0f}",
                   "Probabilità QSO": f"{100 * dx.probability(r['margin_db'], offset):.0f} %",
                   "Lo ricevi a (dB)": round(r["snr_a_hears_b"] + offset, 1), "Ti riceve a (dB)": round(r["snr_b_hears_a"], 1),
                   "Margine (dB)": round(r["margin_db"] + offset, 1), "Spread (Hz)": round(r["spread_hz"]),
                   "Dpol (°)": round(r["dpol_deg"])}
            if wx_me or wx_dx:
                row.update({"Meteo da te": _wx_cell(wx_me.get(hr)), "Meteo DX": _wx_cell(wx_dx.get(hr))})
            table.append(row)
    if not rows:
        st.info("La Luna non è visibile da entrambi in quel giorno.")
        return
    xs, gap = [], []                     # a break in the lines where the Moon is not visible from both
    for i, r in enumerate(rows):
        if i and (r["utc"] - rows[i - 1]["utc"]).total_seconds() > 16 * 60:
            xs.append(r["utc"] - timedelta(minutes=1))
            gap.append(True)
        xs.append(r["utc"])
        gap.append(False)
    it = iter(rows)
    pts = [None if g else next(it) for g in gap]
    yv = lambda f: [None if p is None else f(p) for p in pts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=yv(lambda r: r["snr_a_hears_b"] + offset), name="lo ricevi"))
    fig.add_trace(go.Scatter(x=xs, y=yv(lambda r: r["snr_b_hears_a"]), name="ti riceve"))
    fig.add_trace(go.Scatter(x=xs, y=yv(lambda r: r["threshold_db"]), name=f"soglia Q65-{q65}", line=dict(dash="dot")))
    fig.update_layout(title=f"{k} — " + i18n.tr("SNR atteso in 2500 Hz"), yaxis_title="dB", height=360,
                      margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    b = max(rows, key=lambda r: r["margin_db"])
    hb = b["detail"][0]
    st.markdown(f"{i18n.tr('Momento migliore')}: **{b['utc']:%H:%M} UTC** · EL {b['el_a']:.0f}° / {b['el_b']:.0f}° · "
                f"spread {b['spread_hz']:.0f} Hz · **Q65-{b['mode']}** · Dpol {b['dpol_deg']:+.0f}° ({b['pol_a']}/{b['pol_b']}: " +
                i18n.tr("perdita di polarizzazione") + f" {b['pol_loss_db']:.1f} dB) · " + i18n.tr("perdita di tratta") +
                f" {hb['path_loss_db']:.1f} dB · " + i18n.tr("fasci sulla Luna") + f" {hb['bwf_db']:.1f} dB · Tsys {hb['tsys_K']:.0f} K")
    if not b["spread_ok"]:
        st.warning(f"Il mutual spread ({b['spread_hz']:.0f} Hz) supera quello che Q65-{q65} tollera "
                   f"({dx.Q65_SPREAD_MAX[q65]:.0f} Hz): la soglia è estrapolata e il margine penalizzato.")
    if other["assumed"]:
        st.markdown(f"<span style='color:{ASSUMED_COLOR}'>" + i18n.tr("presunto") + "</span>: "
                    + ", ".join(i18n.tr(a) for a in other["assumed"]), unsafe_allow_html=True)
    if table:
        import pandas as pd
        st.markdown("#### 🔎 " + i18n.tr("La giornata ogni 30 minuti"))
        df = pd.DataFrame(table)
        df.columns = [i18n.tr(c) for c in df.columns]
        bg = pd.DataFrame("", index=df.index, columns=df.columns)
        top = max(t["Margine (dB)"] for t in table)
        for i, t in enumerate(table):
            if t["Margine (dB)"] >= top - 1.0:
                bg.iloc[i, :] = BEST_ROW_CSS
        _st.dataframe(df.style.apply(lambda _: bg, axis=None).format(lambda v: f"{v:g}" if isinstance(v, float) else v),
                      hide_index=True, width="stretch", column_config={
                          i18n.tr("Ora locale (te)"): _st.column_config.Column(help=i18n.tr("la tua ora locale (fuso orario dal locator)")),
                          i18n.tr("Meteo da te"): _st.column_config.Column(help=i18n.tr(WX_HELP)),
                          i18n.tr("Meteo DX"): _st.column_config.Column(help=i18n.tr(WX_HELP)),
                          **_planner_help()})
        st.caption("Solo i momenti con la Luna sopra il tuo orizzonte libero e visibile dalla stazione corrispondente. "
                   "Righe verdi: entro 1 dB dal margine migliore della giornata. Il meteo (Open-Meteo, dal locator) entra "
                   "nel calcolo: umidità e pressione cambiano l'attenuazione e il rumore di cielo ai due capi.")


WX_HELP = ("previsione Open-Meteo per quell'ora: temperatura, umidità relativa, probabilità di pioggia (☔), pioggia "
           "in mm/h, raffiche di vento (💨). Per la stazione corrispondente dalle coordinate del suo locator")


# ------------------------------------------------------------------ device catalogue and heat sink
def _num_cell(v) -> str:
    """number for a table cell: empty instead of None / NaN"""
    return "" if v is None or v != v else f"{v:g}"


CAT_BANDS = [10.368, 24.048, 47.088, 76.032, 122.25, 134.928]
_EDIT_FIELDS = [("f_lo", "Da GHz"), ("f_hi", "A GHz"), ("gain_db", "Guadagno (dB)"), ("nf_db", "NF (dB)"),
                ("p1db_dbm", "P1dB (dBm)"), ("psat_dbm", "Psat (dBm)"), ("vdc", "Tensione (V)"), ("idc_a", "Corrente (A)")]
_PDF_LABEL = {"f_range": "Da/A GHz", "gain_db": "Guadagno", "nf_db": "NF", "p1db_dbm": "P1dB", "psat_dbm": "Psat",
              "vdc": "Tensione", "idc_a": "Corrente", "rth_jc": "R giunzione–case", "tj_max": "Tj max", "pae_pct": "PAE"}


def _catalog_box(D, kinds, key):
    """Devices for the band from EMELab's catalogue (with the user's corrections) and the user's library; every
    device can be corrected by hand or from its datasheet PDF, and the correction can be undone."""
    import pandas as pd
    from emelab import catalog, parts
    ss = _st.session_state
    st.subheader("📚 Catalogo dispositivi")
    for kind_msg, msg in ss.pop(f"{key}_flash", None) or []:
        getattr(st, kind_msg)(msg)
    c = st.columns(3)
    band = c[0].selectbox("Banda", CAT_BANDS, key=f"{key}_cb", format_func=_bl)
    kind_lbl = {k: catalog.TYPES[k] for k in kinds}
    kind = c[1].selectbox("Tipo", list(kinds), format_func=lambda k: kind_lbl[k], key=f"{key}_ck")
    rows = parts.devices(D, band, kind)
    if rows:
        def source(r):
            if r["origin"] == "catalog":
                return i18n.tr(r.get("source"))
            who = i18n.tr("corretto da te") if r["origin"] == "edited" else i18n.tr("la tua libreria")
            return f"{who}: {r.get('source') or ''}".rstrip(": ")
        tab = pd.DataFrame([{"Sigla": r["part"], "Produttore": i18n.tr(r["maker"]), "Da GHz": _num_cell(r.get("f_lo")),
                             "A GHz": _num_cell(r.get("f_hi")), "Guadagno (dB)": _num_cell(r.get("gain_db")),
                             "NF (dB)": _num_cell(r.get("nf_db")), "Psat (dBm)": _num_cell(r.get("psat_dbm")),
                             "Note": i18n.tr(r.get("notes")) if r.get("notes") else "", "Fonte": source(r),
                             "Verificato": "✅" if r.get("verified") else "⚠️" if r.get("check") else ""} for r in rows])
        tab.columns = [i18n.tr(x) for x in tab.columns]
        st.dataframe(tab, hide_index=True, width="stretch")
        st.caption("⚠️ = valori tipici da confermare sul datasheet attuale alla tua frequenza. ✅ = valori inseriti o "
                   "corretti da te (restano su questo PC). Le celle vuote vanno lette dal datasheet: EMELab non inventa i numeri.")
    else:
        st.info("Nessun dispositivo per questa banda: aggiungilo a mano o dal datasheet qui sotto.")
    NEW = len(rows)
    pick = ss.pop(f"{key}_pick", None)                    # device just saved: select it
    if pick:
        ss[f"{key}_cs"] = next((i for i, r in enumerate(rows) if (r["part"], r["maker"]) == pick), NEW)
    if not isinstance(ss.get(f"{key}_cs"), int) or ss[f"{key}_cs"] > NEW:
        ss[f"{key}_cs"] = 0
    i = c[2].selectbox("Il tuo dispositivo", range(NEW + 1), key=f"{key}_cs",
                       format_func=lambda i: "➕ " + i18n.tr("Nuovo dispositivo") if i == NEW else
                       f"{rows[i]['part']} — {rows[i]['maker']}" + (" ✅" if rows[i].get("verified") else ""))
    sel = rows[i] if i < NEW else None
    if sel:
        links = catalog.search_links(sel["part"], sel["maker"] if sel["maker"] != "—" else "")
        lc = st.columns(len(links))
        for col, (k, u) in zip(lc, links.items()):
            col.link_button("🔎 " + k, u)
    title = (("✏️ " + i18n.tr("Correggi a mano i valori di") + f" {sel['part']} " + i18n.tr("o caricane il datasheet (PDF)"))
             if sel else "➕ " + i18n.tr("Nuovo dispositivo: inserisci i valori a mano o caricane il datasheet (PDF)"))
    with st.expander(title, expanded=sel is None):
        _device_editor(D, key, kind, sel)
    return sel


def _device_editor(D, key, kind, sel):
    """Form to correct a device (or add a new one): values typed by hand or read from its datasheet PDF, saved in the
    user's library as verified; a corrected catalogue device can go back to the catalogue values."""
    from emelab import catalog, parts
    ss = _st.session_state
    up = st.file_uploader("📄 Datasheet PDF (facoltativo): EMELab legge i valori e li mette nei campi qui sotto",
                          type=["pdf"], key=f"{key}_ds_{sel['part'] if sel else 'new'}")
    found = {}
    if up is not None:
        from emelab import stations as stn
        try:
            found = catalog.read_datasheet(stn.pdf_text(up.getvalue()))
        except Exception as e:
            st.error(f"PDF: {e}")
        lines = found.pop("_lines", {})
        if lines:
            st.caption(i18n.tr("Valori trovati nel PDF (controllali: prendo il valore tipico della riga)") + ":  \n" +
                       "  \n".join(f"**{i18n.tr(_PDF_LABEL.get(k, k))}** ← «{v}»" for k, v in lines.items()))
        elif not found:
            st.warning("Nel PDF non ho trovato valori leggibili (forse è una scansione): inseriscili a mano qui sotto.")
    base = sel or {}
    stamp = f"{key}_{abs(hash((base.get('part'), base.get('maker'), base.get('origin'), base.get('updated'), up.file_id if up else '')))}"
    c = st.columns([2, 2, 3])
    fixed = bool(sel) and sel["origin"] != "mine"        # a catalogue device keeps its name: that is how it is matched
    part = c[0].text_input("Sigla", base.get("part") or (up.name.rsplit(".", 1)[0] if up else ""), key=f"{stamp}_p",
                           disabled=fixed)
    maker = c[1].text_input("Produttore", base.get("maker") or "", key=f"{stamp}_m", disabled=fixed)
    src = c[2].text_input("Fonte o link al datasheet", base.get("source") if sel and sel["origin"] != "catalog" else
                          (up.name if up else ""), key=f"{stamp}_s")
    vals = {}
    cc = st.columns(len(_EDIT_FIELDS))
    for col, (k, lab) in zip(cc, _EDIT_FIELDS):
        v = found.get(k, base.get(k))
        vals[k] = col.number_input(lab, value=None if v is None else float(v), key=f"{stamp}_{k}", format="%g")
    extra = {k: found[k] for k in ("rth_jc", "tj_max", "pae_pct") if k in found}
    notes0 = base.get("notes") or ""
    if extra:
        notes0 = "; ".join(x for x in [notes0, ", ".join(f"{k}={v:g}" for k, v in extra.items())] if x)
    notes = st.text_area("Note", notes0, key=f"{stamp}_n", height=68)
    if sel and sel["origin"] == "catalog" and sel.get("check"):
        st.caption("⚠️ Valori tipici del catalogo: salvandoli dopo averli controllati sul datasheet diventano ✅ verificati da te.")
    if sel and sel["origin"] == "edited":
        cat = sel.get("catalog") or {}
        st.caption(i18n.tr("Valori del catalogo EMELab") + ": " + " · ".join(
            f"{i18n.tr(lab)} {_num_cell(cat.get(k)) or '—'}" for k, lab in _EDIT_FIELDS))
    b = st.columns(3)
    if b[0].button("💾 Salva i valori (verificati da te)", key=f"{stamp}_save", type="primary",
                   disabled=not (part or "").strip()):
        part_s, maker_s = (sel["part"], sel["maker"]) if fixed else (part.strip(), maker.strip() or "—")
        if sel and sel["origin"] == "mine" and (part_s, maker_s) != (sel["part"], sel["maker"]):
            parts.delete(D, sel["id"])                    # renamed own device: replace the old row
        ltype = (parts.find(D, sel["part"], sel["maker"]) or {}).get("type") if sel and sel["origin"] == "mine" else None
        parts.save(D, part=part_s, maker=maker_s, type=ltype or parts.KIND_TO_TYPE[kind], datasheet=src.strip() or None,
                   notes=notes.strip() or None, tech=base.get("tech"), verified=1,
                   **{lk: vals[ck] for lk, ck in parts.NUM_FIELDS})
        ss[f"{key}_pick"] = (part_s, maker_s)
        ss[f"{key}_flash"] = [("success", i18n.tr("Valori salvati e segnati come verificati da te (solo su questo PC)") +
                               f": {part_s}")]
        st.rerun()
    if sel and sel["origin"] == "edited" and b[1].button("↩️ Ripristina i valori del catalogo", key=f"{stamp}_rev"):
        parts.revert(D, sel["part"], sel["maker"])
        ss[f"{key}_pick"] = (sel["part"], sel["maker"])
        ss[f"{key}_flash"] = [("info", i18n.tr("Ripristinati i valori del catalogo EMELab") + f": {sel['part']}")]
        st.rerun()
    if sel and sel["origin"] == "mine" and b[1].button("🗑️ Elimina dalla tua libreria", key=f"{stamp}_del"):
        parts.delete(D, sel["id"])
        ss[f"{key}_flash"] = [("info", i18n.tr("Eliminato dalla tua libreria") + f": {sel['part']}")]
        st.rerun()


def _heatsink_box(dev, p_out_w, pae_default, key):
    from emelab import catalog
    st.subheader("🌡️ Dissipatore del dispositivo di potenza")
    st.caption("La giunzione segue il periodo di trasmissione in millisecondi, il dissipatore fa la media su minuti: "
               "con Q65 (50 % in trasmissione) il dissipatore vede metà potenza, la giunzione la vede tutta. "
               "Resistenza termica giunzione–case dal datasheet del dispositivo.")
    tech = (dev or {}).get("tech") or "GaN"
    c = st.columns(4)
    pw = c[0].number_input("Potenza d'uscita del dispositivo (W)", 0.1, 500.0, float(round(p_out_w, 1)), 0.5, key=f"{key}_hp")
    pae = c[1].number_input("Efficienza (PAE, %)", 5.0, 80.0, float(pae_default), 1.0, key=f"{key}_he")
    rjc = c[2].number_input("R giunzione–case (K/W)", 0.05, 50.0, 1.5, 0.05, key=f"{key}_hj",
                            help="«thermal resistance, channel to case» nel datasheet")
    rcs = c[3].number_input("R case–dissipatore (K/W)", 0.0, 5.0, 0.2, 0.05, key=f"{key}_hc",
                            help="pasta termica o indio: 0.1–0.3 K/W; con isolante di più")
    c = st.columns(4)
    tamb = c[0].number_input("Temperatura dell'aria (°C)", -20.0, 60.0, 35.0, 1.0, key=f"{key}_ha",
                             help="al fuoco d'estate, al sole, la scatola si scalda: meglio abbondare")
    tjmax = catalog.TJ_MAX.get(tech, 175.0)
    tjt = c[1].number_input("Temperatura di giunzione obiettivo (°C)", 60.0, 250.0, min(150.0, tjmax - 25), 5.0, key=f"{key}_ht",
                            help=i18n.tr("massimo assoluto tipico") + f" {tech}: {tjmax:.0f} °C; " +
                                 i18n.tr("ogni 10 °C in meno raddoppia circa la vita del dispositivo"))
    duty = c[2].number_input("Frazione in trasmissione", 0.05, 1.0, 0.5, 0.05, key=f"{key}_hd",
                             help="Q65: 0.5; prove e beacon continui: 1")
    h = catalog.heatsink(pw, pae, rjc, rcs, tamb, tjt, duty)
    m = st.columns(4)
    m[0].metric("Potenza dissipata", f"{h['p_diss_w']:.0f} W", f"DC {h['p_dc_w']:.0f} W", delta_color="off")
    if not h["ok"]:
        m[1].metric("Dissipatore", "impossibile")
        st.error("Anche con un dissipatore ideale la giunzione supera l'obiettivo: riduci la potenza, migliora il contatto "
                 "termico (R case–dissipatore) o usa un dispositivo con resistenza termica più bassa.")
        return
    m[1].metric("R dissipatore–aria massima", f"{h['rsa_max']:.2f} K/W")
    m[2].metric("Temperatura del dissipatore", f"{h['t_sink_c']:.0f} °C")
    m[3].metric("Giunzione in trasmissione continua", f"{h['tj_continuous_c']:.0f} °C",
                help=i18n.tr("se trasmetti senza pause (prove, beacon) con lo stesso dissipatore"))
    st.dataframe([{"Raffreddamento": i18n.tr(k), "Superficie alettata (cm²)": round(a * 1e4) if a == a else None,
                   "Ordine di grandezza": i18n.tr("piastra alettata") + f" ≈ {math.sqrt(a * 1e4 / 6):.0f} × {math.sqrt(a * 1e4 / 6):.0f} cm"
                   if a == a else ""} for k, a in h["area_m2"].items()], hide_index=True, width="stretch")
    st.caption("Superficie stimata con un coefficiente di scambio efficace (alette comprese): naturale ≈ 7, ventola ≈ 35, "
               "ventola forte ≈ 70 W/(m²·K). Per la scelta finale usa la curva K/W del produttore del dissipatore.")


# ------------------------------------------------------------------ guided start
def _horizon_editor(key="wz_hz"):
    import pandas as pd
    from emelab import wizard
    hz = openems_local.load_settings().get("horizon") or wizard.default_horizon(10.0)
    with st.expander("🏔️ Il tuo orizzonte libero (dove vedi la Luna senza ostacoli)"):
        st.caption("Settori di azimut con l'elevazione minima libera da case, alberi, colline. Fuori dai settori la Luna "
                   "si considera nascosta. Lo usano anche il Pianificatore e «Chi posso collegare». Resta salvato solo su questo PC.")
        ed = st.data_editor(pd.DataFrame(hz), num_rows="dynamic", hide_index=True, key=key, width="stretch",
                            column_config={"az_da": st.column_config.NumberColumn(i18n.tr("Azimut da (°)"), min_value=0, max_value=360),
                                           "az_a": st.column_config.NumberColumn(i18n.tr("Azimut a (°)"), min_value=0, max_value=360),
                                           "el_min": st.column_config.NumberColumn(i18n.tr("Elevazione minima (°)"), min_value=0, max_value=90)})
        rows = [r for r in ed.to_dict("records") if None not in (r.get("az_da"), r.get("az_a"), r.get("el_min"))
                and not any(isinstance(v, float) and v != v for v in r.values())]
        if st.button("💾 Salva orizzonte", key=key + "_save"):
            openems_local.save_settings(horizon=rows)
            st.success("Orizzonte salvato.")
        import numpy as _np
        az = _np.arange(0, 361, 2)
        fig = go.Figure(go.Barpolar(r=[wizard.el_min(rows, a) for a in az], theta=az, marker_color="#8d6e63", opacity=0.7))
        fig.update_layout(polar=dict(angularaxis=dict(direction="clockwise", rotation=90), radialaxis=dict(range=[0, 40])),
                          height=300, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, width="stretch", key=key + "_plot")
    return rows or hz


def _wizard(D):
    from emelab import coach, dx, weather, wizard
    S = _st.session_state
    stn = D.station()
    if not stn.get("lat"):
        st.info("Benvenuto in EMELab! Per cominciare inserisci nominativo e locator nella scheda Stazione.")
        return
    hz = _horizon_editor()
    now = wizard.sky_now_text(stn["lat"], stn["lon"], stn.get("height_m") or 0.0, hz)
    st.markdown(f"### 🧭 {i18n.tr('Oggi è')} {i18n.tr(wizard.date_it(now['now']))}, " + i18n.tr("sono le") +
                f" {now['now']:%H:%M} UTC")
    if "wz_fc" not in S:
        try:
            S["wz_fc"] = weather.open_meteo_series(stn["lat"], stn["lon"], now["now"], 16)
        except Exception as e:
            S["wz_fc"] = []
            S["wz_fc_err"] = str(e)
    fc = S["wz_fc"]
    nowh = now["now"].replace(minute=0, second=0, microsecond=0)
    cur = next((x for x in fc if x["utc"] == nowh), None)
    nxt = [x for x in fc if nowh <= x["utc"] <= nowh + timedelta(hours=24)]
    c = st.columns(2)
    with c[0]:
        if cur:
            st.markdown(f"**{i18n.tr('Meteo da te adesso')}:** {cur['t_c']:.0f} °C, " + i18n.tr("umidità") + f" {cur['rh']:.0f} %, " +
                        i18n.tr("nuvole") + f" {cur['cloud_pct']:.0f} %, " + i18n.tr("vento") + f" {cur.get('wind_ms') or 0:.0f} m/s")
            if nxt:
                st.markdown(f"**{i18n.tr('Prossime 24 ore')}:** " + i18n.tr("pioggia fino al") +
                            f" {max((x.get('rain_prob') or 0) for x in nxt):.0f} %, " + i18n.tr("raffiche fino a") +
                            f" {max((x.get('gust_ms') or 0) for x in nxt):.0f} m/s, " + i18n.tr("umidità") +
                            f" {min(x['rh'] for x in nxt):.0f}–{max(x['rh'] for x in nxt):.0f} %")
        else:
            st.caption(i18n.tr("Previsioni meteo non disponibili") + (f": {S.get('wz_fc_err')}" if S.get("wz_fc_err") else ""))
    with c[1]:
        vis = i18n.tr("visibile dal tuo orizzonte") if now["visible"] else i18n.tr("non visibile adesso")
        st.markdown(f"**{i18n.tr('Luna')}:** AZ {now['moon_az']:.0f}° EL {now['moon_el']:.0f}° — {vis}; " +
                    f"{now['dist_km']:,.0f} km ({now['perigee_db']:+.1f} dB " + i18n.tr("rispetto al perigeo") + "), " +
                    i18n.tr("illuminata al") + f" {100 * now['illum']:.0f} %")
        st.markdown(f"**{i18n.tr('Spread delle eco proprie')}:** " +
                    " · ".join(f"{f:.0f} GHz {v:.0f} Hz" for f, v in now["spread"].items()) +
                    f" · **{i18n.tr('Sole–Luna')}** {now['sun_moon']:.0f}°")
    st.divider()
    goals = {"plan": "📡 Pianificare un QSO", "chain": "🔧 Migliorare la catena (LNA, SSPA, TWT)",
             "setup": "🎯 Migliorare il setup (puntamento, fuoco, misure)", "analyse": "📊 Capire i miei risultati"}
    goal = st.radio("Cosa vuoi fare oggi?", list(goals), format_func=lambda k: goals[k], horizontal=True, key="wz_goal",
                    index=None)
    if goal == "plan":
        _wz_plan(D, stn, hz, fc)
    elif goal == "chain":
        st.markdown("\n".join("- " + i18n.tr(s["text"]) for s in coach.suggestions(D) if s.get("area") in (None, "chain"))[:3000]
                    or i18n.tr("Nessun suggerimento al momento."))
        st.info("Apri le schede 🔊 LNA, 🔥 SSPA e 💡 TWT: per ogni stadio vedi quanto pesa e quanto guadagni migliorandolo. "
                "Nel 🗓️ Pianificatore («Chi posso collegare») la «correzione appresa dai QSO» ti dice quanto la tua stazione rende "
                "rispetto alla teoria: se ricevi peggio di come ti ricevono, il margine è in ricezione (LNA, perdite, Tsys).")
    elif goal == "setup":
        for sgg in coach.suggestions(D)[:8]:
            st.markdown("- " + i18n.tr(sgg["text"]))
        st.info("Nella scheda 🎯 Tracking trovi il bilancio degli errori e le strategie; in ➕ Nuova misura registri sole, "
                "Luna, terra e fuoco; in 📊 Analisi EMELab stima G/T, efficienza, NF e il modello di puntamento.")
    elif goal == "analyse":
        st.info("Nella scheda 📈 Grafici puoi mettere in relazione i rapporti dei QSO con elevazione, spread, distanza, "
                "umidità…; «Correlazioni» ti mostra cosa va insieme ai tuoi risultati. In 📉 Statistiche QSO trovi le "
                "distribuzioni e la mappa.")


def _wz_plan(D, stn, hz, fc):
    from emelab import dx, wizard
    S = _st.session_state
    sets = D.setups()
    if not sets:
        st.info("Crea prima una configurazione (scheda Configurazioni) per la banda che vuoi usare.")
        return
    c = st.columns(3)
    sid = c[0].selectbox("Con quale configurazione?", [s["id"] for s in sets], key="wz_setup",
                         format_func=lambda i: next(f"{s['name']} ({_bl(s['band_ghz'])})" for s in sets if s["id"] == i))
    setup = next(s for s in sets if s["id"] == sid)
    days = c[1].slider("Quanti giorni guardare avanti?", 1, 16, 7, key="wz_days",
                       help="le previsioni meteo arrivano a 16 giorni")
    band = _band_of_setup(setup)
    f = float(setup["band_ghz"])
    if c[2].button("🌙 Cerca le finestre di Luna", type="primary", key="wz_go"):
        with st.spinner("Calcolo delle finestre…"):
            ws = wizard.moon_windows(stn["lat"], stn["lon"], stn.get("height_m") or 0.0, hz, datetime.now(timezone.utc), int(days))
            for w in ws:
                w["wx"] = wizard.window_weather(fc, w, f)
                w["score"], w["quality"] = wizard.window_score(w, f, w["wx"])
        S["wz_windows"] = ws
        S.pop("wz_rank", None)
    ws = S.get("wz_windows")
    if not ws:
        return
    st.markdown("#### " + i18n.tr("Le tue finestre di Luna"))
    st.dataframe([{"Dal (UTC)": wizard.short_it(w["start"]), "Al (UTC)": w["end"].strftime("%d/%m %H:%M"),
                   "Ore": round(w["hours"], 1), "Culmine": f"{w['best_utc']:%H:%M} EL {w['best_el']:.0f}°",
                   "Distanza (km)": f"{w['dist_km']:,.0f}", "Rispetto al perigeo (dB)": round(w["perigee_db"], 2),
                   "Spread (Hz)": "{:.0f}–{:.0f}".format(*w["spread"].get(f, w["spread"][min(w["spread"], key=lambda k: abs(k - f))])),
                   "Sole–Luna min (°)": round(w["sun_moon_min"]),
                   "Meteo": i18n.tr(w["wx"]["label"]) if w.get("wx") else "—",
                   "Pioggia (%)": w["wx"]["rain_prob"] if w.get("wx") else "—",
                   "Raffiche (m/s)": round(w["wx"]["gust_ms"]) if w.get("wx") else "—",
                   "Umidità (%)": round(w["wx"]["rh"]) if w.get("wx") else "—",
                   "Condizioni": f"{w['score']} · {i18n.tr(w['quality'])}"} for w in ws], hide_index=True, width="stretch")
    best = max(range(len(ws)), key=lambda i: ws[i]["score"])
    st.caption(i18n.tr("La finestra migliore è") + f" {ws[best]['start']:%d/%m} " + i18n.tr("dalle") + f" {ws[best]['start']:%H:%M} " +
               i18n.tr("alle") + f" {ws[best]['end']:%H:%M} UTC. " +
               i18n.tr("Il punteggio tiene conto di altezza della Luna, distanza, spread, distanza dal Sole e meteo."))
    wi = st.selectbox("Quale finestra vuoi usare?", range(len(ws)), index=best, key="wz_wi",
                      format_func=lambda i: f"{wizard.short_it(ws[i]['start'])} → {ws[i]['end']:%H:%M} UTC · {ws[i]['score']}")
    w = ws[wi]
    models = _dx_models(D, band)
    if not models:
        st.info("Importa la EME Directory (scheda Stazioni EME) per sapere chi è attivo e con quale stazione.")
        return
    me = _my_model(setup, band)
    off = _learned_offset(D, band, me, (stn["lat"], stn["lon"]), models)
    if st.button("👥 Con chi posso fare QSO in questa finestra?", key="wz_rank_go"):
        hours = (w["end"] - w["start"]).total_seconds() / 3600
        ok = lambda times: [wizard.visible(hz, *(lambda s: (s.moon.az, s.moon.el))(astro.sky(t, stn["lat"], stn["lon"], stn.get("height_m") or 0)))
                            for t in times]
        with st.spinner("Calcolo per ogni stazione…"):
            S["wz_rank"] = dx.rank(me, (stn["lat"], stn["lon"]), models, band, w["start"], hours, 20.0, 5.0,
                                   off["offset_db"] if off["n"] >= 5 else 0.0, my_ok=ok)
    rk = [r for r in (S.get("wz_rank") or []) if r.get("best")]
    if not rk:
        return
    worked = {q["call"] for q in D.qsos(band=band)}
    st.markdown("#### " + i18n.tr("Chi puoi collegare"))
    st.dataframe([{"Nominativo": r["call"], "Già collegato": "✓" if r["call"] in worked else "",
                   "Probabilità tecnica": f"{min(100 * r['probability'], 99):.0f} %",
                   "Momento migliore (UTC)": f"{r['best']['utc']:%d/%m %H:%M}", "Ore in comune": round(r["hours_common"], 1),
                   "Lo ricevi a (dB)": round(r["best"]["snr_a_hears_b"] + (off["offset_db"] if off["n"] >= 5 else 0), 1),
                   "Ti riceve a (dB)": round(r["best"]["snr_b_hears_a"], 1), "Modo": "Q65-" + r["best"]["mode"] + ("" if r["best"]["spread_ok"] else " ⚠️"),
                   "Mutual spread (Hz)": round(r["best"]["spread_hz"]),
                   "Polarizzazioni": f"{r['best']['pol_a']}/{r['best']['pol_b']}", "Dpol (°)": round(r["best"]["dpol_deg"]),
                   "Perdita di polarizzazione (dB)": round(r["best"]["pol_loss_db"], 1),
                   "Margine (dB)": round(r["best"]["margin_db"], 1),
                   "Stazione": f"{r.get('antenna') or ''} {r.get('power_w') or ''} W"} for r in rk[:40]], hide_index=True, width="stretch")
    st.caption("Probabilità tecnica: margine del segnale atteso sulla soglia Q65 (con la correzione appresa dai tuoi QSO e "
               "±2 dB di incertezza). Non sa se l'altra stazione è attiva: per questo conviene uno sked.")
    new = [r for r in rk if r["call"] not in worked and r["probability"] >= 0.5]
    if new:
        st.success(i18n.tr("Stazioni nuove per te con buone probabilità") + ": " + ", ".join(r["call"] for r in new[:12]))
    st.markdown("#### " + i18n.tr("Proponi uno sked"))
    pick = st.selectbox("Stazione", [r["call"] for r in rk], key="wz_pick")
    r = next(x for x in rk if x["call"] == pick)
    info = D.station_of(pick) or {}
    web = ((info.get("data", {}).get("directory") or {}).get(band) or {}).get("web")
    c = st.columns(3)
    c[0].link_button("🔎 QRZ.com", f"https://www.qrz.com/db/{pick}")
    if web:
        c[1].link_button("🌐 " + i18n.tr("Sito della stazione"), web if web.startswith("http") else "https://" + web)
    lang = c[2].radio("Lingua del messaggio", ["en", "it"], index=1 if pick.startswith("I") else 0, horizontal=True,
                      format_func=lambda k: {"en": "English", "it": "Italiano"}[k], key="wz_lang")
    t0 = r["best"]["utc"] - timedelta(minutes=30)
    t1 = r["best"]["utc"] + timedelta(minutes=30)
    st.code(wizard.sked_text(lang, stn.get("callsign") or "", stn.get("locator") or "", pick, info.get("name"), band, t0, t1,
                             r["best"]["mode"], (stn.get("callsign") or "") < pick, r["best"]["snr_a_hears_b"], r["best"]["snr_b_hears_a"]),
            language=None)
    st.caption("Copia il testo e mandalo come preferisci (email, chat EME, HB9Q logger). EMELab non conserva le email: "
               "l'indirizzo lo trovi su QRZ.com o sul sito della stazione.")


# ------------------------------------------------------------------ WSJT-X live
@_st.cache_resource
def _wsjtx_service():
    from emelab import wsjtx_service

    def wx(t):
        stn = edb.DB().station()
        if not stn.get("lat"):
            return None
        return weather.open_meteo(stn["lat"], stn["lon"], t)
    return wsjtx_service.Service(edb.DB, lambda: edb.DB().station().get("locator"), wx)


def _wsjtx_autostart():
    sets = openems_local.load_settings()
    svc = _wsjtx_service()
    svc.auto_log = bool(sets.get("wsjtx_autolog", True))
    svc.eme_only = bool(sets.get("wsjtx_eme_only", True))
    svc.strict_eme = bool(sets.get("wsjtx_strict_eme", False))
    svc.auto_fix = bool(sets.get("wsjtx_autofix", True))
    if sets.get("wsjtx_on") and not svc.running:
        try:
            svc.start(sets.get("wsjtx_host", "127.0.0.1"), int(sets.get("wsjtx_port", 2237)), sets.get("wsjtx_mcast") or None)
        except OSError as e:
            svc.errors.append(f"avvio: {e}")
    if sets.get("wsjtx_file_on") and not svc.file_running and sets.get("wsjtx_file"):
        pos = sets.get("wsjtx_file_pos") or {}
        svc.on_tail_pos = _wsjtx_save_pos
        svc.start_file(sets["wsjtx_file"], pos.get("offset") if pos.get("path") == sets["wsjtx_file"] else None)
    from emelab import ui_alltxt
    ui_alltxt.autostart(svc, sets)
    return svc


def _wsjtx_live_problems(svc):
    """What is wrong in WSJT-X now (only while it is talking to EMELab)."""
    if not (svc.running and svc.last_seen and svc.problems):
        return []
    return svc.problems if (datetime.now(timezone.utc) - svc.last_seen).total_seconds() < 90 else []


def _wsjtx_banner():
    """Warning on every page when the WSJT-X settings do not fit the band."""
    probs = [p for p in _wsjtx_live_problems(_wsjtx_service()) if not p.get("soft")]
    if probs:
        st.warning(i18n.tr("⚠️ Impostazioni di WSJT-X da controllare") + ": " +
                   " · ".join(i18n.tr(p["msg"]) + (f" ({p['detail']})" if p.get("detail") else "") for p in probs)
                   + " — " + i18n.tr("dettagli nella scheda 📻 WSJT-X"))
        from emelab import nav
        nav.button("wsjtx", key="wj_banner_go")


def _wsjtx_save_pos(path, offset):
    openems_local.save_settings(wsjtx_file_pos={"path": path, "offset": int(offset)})


def _wsjtx_file_box(svc, sets):
    from emelab import wsjtx_logfile
    st.markdown("#### " + i18n.tr("📄 File di log di WSJT-X (wsjtx_log.adi)"))
    st.caption("Il modo più semplice: ogni volta che premi OK in «Log QSO», WSJT-X aggiunge il QSO a wsjtx_log.adi ed "
               "EMELab lo legge entro pochi secondi. Non serve nessuna porta UDP, quindi non disturba JTAlert, GridTracker "
               "o altri logger. Il file è nella cartella che WSJT-X apre con File → Open log directory.")
    found = wsjtx_logfile.find_default()
    if not (_st.session_state.get("wj_file") or "").strip():          # empty box: fill it with the file found on this PC
        _st.session_state["wj_file"] = sets.get("wsjtx_file") or (str(found) if found else "")
    c = st.columns([4, 2])
    path = c[0].text_input("Percorso di wsjtx_log.adi", key="wj_file",
                           help="incolla il percorso del file o della cartella che WSJT-X apre con File → Open log directory")
    from pathlib import Path
    clean = wsjtx_logfile.clean_path(path)
    ok = bool(clean) and Path(clean).is_file()
    if not svc.file_running:
        st.caption("Con il pulsante «Importa automaticamente i nuovi QSO da WSJT-X» EMELab resta in ascolto del file: "
                   "ogni QSO che registri in WSJT-X entra da solo nel Log QSO di EMELab, senza importare l'ADIF a mano. "
                   "La scelta viene ricordata e riparte all'avvio di EMELab.")
        past = st.checkbox("Importa anche i QSO già presenti nel file (i doppioni vengono saltati)", False, key="wj_file_past")
        if c[1].button("▶️ Importa automaticamente i nuovi QSO da WSJT-X", type="primary", key="wj_file_on", disabled=not ok):
            p = clean
            openems_local.save_settings(wsjtx_file_on=True, wsjtx_file=p, wsjtx_file_pos={})
            svc.on_tail_pos = _wsjtx_save_pos
            svc.start_file(p, 0 if past else None)
            st.rerun()
        if path.strip() and not ok:
            st.warning("File non trovato: controlla il percorso (in WSJT-X: File → Open log directory).")
        elif not path.strip():
            st.warning(i18n.tr("Non ho trovato wsjtx_log.adi nelle cartelle di WSJT-X di questo PC. In WSJT-X apri "
                               "File → Open log directory, copia il percorso della cartella e incollalo qui sopra.")
                       + "  \n" + i18n.tr("Cercato in") + ": " + ", ".join(f"`{p.parent}`" for p in wsjtx_logfile.default_paths()[:3]))
    else:
        if c[1].button("⏹️ Smetti di importare da WSJT-X", key="wj_file_off"):
            svc.stop_file()
            openems_local.save_settings(wsjtx_file_on=False)
            st.rerun()
        st.markdown(i18n.tr("Importo automaticamente i nuovi QSO da") + f" `{svc.tail.path}`" + (" · " + i18n.tr("ultimo QSO letto") +
                    f" {svc.file_seen:%H:%M:%S} UTC" if svc.file_seen else ""))


def _wsjtx_logged_table(svc):
    if not svc.logged:
        return
    from emelab import logbook as lb
    st.markdown("#### " + i18n.tr("QSO registrati da WSJT-X"))

    def state(q):
        if q.get("skipped"):
            why = q["skipped"]
            why = i18n.tr("propagazione") + why[12:] if why.startswith("propagazione ") else i18n.tr(why)
            return i18n.tr("lasciato fuori") + ": " + why
        return i18n.tr("già nel log") if q["duplicate"] else i18n.tr("registrato")
    st.dataframe([{"UTC": q["utc"].strftime("%Y-%m-%d %H:%M"), "Nominativo": q["call"], "Banda": _bl(q.get("band")),
                   "Modo": lb.mode_label(q)[0],
                   "Inviato": q.get("rst_sent") or "", "Ricevuto": q.get("rst_rcvd") or "", "Locator": q.get("locator") or "",
                   "Luna EL (°)": round((q.get("calc") or {}).get("moon_el", float("nan")), 1),
                   "Fonte": q.get("source"), "Stato": state(q)} for q in svc.logged],
                 hide_index=True, width="stretch")


def _wsjtx_tab(D):
    from emelab import dx
    st.subheader("Collegamento con WSJT-X")
    st.caption("In WSJT-X: Settings → Reporting → «UDP Server» = 127.0.0.1, porta 2237, e spunta «Accept UDP requests». "
               "EMELab riceve le decodifiche, registra nel Log QSO ogni QSO che confermi in WSJT-X (con tutte le condizioni "
               "di quel momento) e può colorare i nominativi e impostare il sottomodo Q65. Se usi anche JTAlert o "
               "GridTracker, metti in WSJT-X un indirizzo multicast (per esempio 224.0.0.1) e lo stesso qui.")
    sets = openems_local.load_settings()
    svc = _wsjtx_autostart()
    c = st.columns(3)
    auto = c[0].checkbox("Registra i QSO nel log", bool(sets.get("wsjtx_autolog", True)), key="wj_auto")
    eme_only = c[1].checkbox("Solo i QSO EME e delle bande da 10 GHz in su", bool(sets.get("wsjtx_eme_only", True)), key="wj_eme")
    strict = c[2].checkbox("Solo con Prop Mode = EME", bool(sets.get("wsjtx_strict_eme", False)), key="wj_strict",
                           disabled=not eme_only,
                           help=i18n.tr("Senza questa spunta, un QSO senza Prop Mode entra se è in Q65, JT65, JT4 o QRA64 "
                                        "oppure con una stazione EME nota. Un Prop Mode diverso da EME (tropo, rain scatter…) "
                                        "resta sempre fuori. In WSJT-X il Prop Mode si sceglie nella finestra «Log QSO» e "
                                        "viene ricordato."))
    if (auto, eme_only, strict) != (svc.auto_log, svc.eme_only, svc.strict_eme):
        svc.auto_log, svc.eme_only, svc.strict_eme = auto, eme_only, strict
        openems_local.save_settings(wsjtx_autolog=auto, wsjtx_eme_only=eme_only, wsjtx_strict_eme=strict)
    _wsjtx_file_box(svc, sets)
    from emelab import ui_alltxt
    ui_alltxt.file_box(D, svc, sets)
    _wsjtx_logged_table(svc)
    st.markdown("#### " + i18n.tr("📡 UDP (decodifiche, colori, sottomodo Q65)"))
    c = st.columns(4)
    host = c[0].text_input("Indirizzo", sets.get("wsjtx_host", "127.0.0.1"), key="wj_host")
    port = c[1].number_input("Porta UDP", 1024, 65535, int(sets.get("wsjtx_port", 2237)), key="wj_port")
    mcast = c[2].text_input("Gruppo multicast (facoltativo)", sets.get("wsjtx_mcast", ""), key="wj_mcast")
    if not svc.running:
        if c[3].button("▶️ Collega", type="primary", key="wj_start"):
            try:
                svc.start(host.strip(), int(port), mcast.strip() or None)
                openems_local.save_settings(wsjtx_on=True, wsjtx_host=host.strip(), wsjtx_port=int(port),
                                            wsjtx_mcast=mcast.strip(), wsjtx_autolog=auto)
                st.rerun()
            except OSError as e:
                st.error(i18n.tr("Porta non disponibile (forse un altro programma la usa)") + f": {e}")
    elif c[3].button("⏹️ Scollega", key="wj_stop"):
        svc.stop()
        openems_local.save_settings(wsjtx_on=False)
        st.rerun()
    if not svc.running:
        st.info("Non collegato.")
        if svc.errors:
            with st.expander("⚠️ Messaggi"):
                for e in list(svc.errors)[-10:]:
                    st.text(e)
        from emelab import ui_wsjtx_panel
        ui_wsjtx_panel._preset_editors(None)        # presets can be written also with WSJT-X closed
        return
    s = svc.status
    if not svc.last_seen:
        st.warning("In ascolto: nessun messaggio da WSJT-X finora. Controlla le impostazioni di Reporting in WSJT-X.")
    else:
        age = (datetime.now(timezone.utc) - svc.last_seen).total_seconds()
        st.markdown(f"**{svc.client or 'WSJT-X'}** · " + i18n.tr("ultimo messaggio") + f" {age:.0f} s · "
                    + (f"**{s['dial_hz'] / 1e6:,.3f} MHz** · " if s.get("dial_hz") else "")
                    + f"**{s.get('mode', '')} {s.get('submode', '')}** · DX **{s.get('dx_call') or '—'}** {s.get('dx_grid') or ''} · "
                    + ("🔴 TX" if s.get("transmitting") else "🟢 RX"))
    st.button("🔄 Aggiorna", key="wj_refresh")
    from emelab import ui_wsjtx_panel
    ui_wsjtx_panel.render(svc, sets)
    stn = D.station()
    band = None
    if s.get("dial_hz"):
        from emelab import stations as _stns
        band = _stns.band_of(s["dial_hz"] / 1e6)
    # recommended Q65 submode for the DX in WSJT-X
    if band and s.get("dx_call") and stn.get("lat"):
        dxs = D.station_of(s["dx_call"])
        grid = s.get("dx_grid") or (dxs or {}).get("locator")
        if grid:
            try:
                L = astro.locator_to_latlon(grid)
                mut = astro.mutual(datetime.now(timezone.utc), (stn["lat"], stn["lon"]), L)
                spread = mut["spread_hz_per_ghz"] * dx.BAND_GHZ.get(band, 10.368)
                mode = dx.band_mode(band)
                thr = dx.q65_threshold_db(mode, spread)
                c = st.columns([3, 1])
                c[0].info(i18n.tr("Con") + f" {s['dx_call']}: mutual spread {spread:.0f} Hz · " + i18n.tr("modo della banda") +
                          f" **Q65-{mode}** (" + i18n.tr("soglia") + f" {thr:.1f} dB)" +
                          ("" if dx.spread_ok(mode, spread) else " ⚠️ " + i18n.tr("spread oltre la tolleranza")))
                if c[1].button(f"⚙️ Imposta Q65-{mode} in WSJT-X", key="wj_setmode"):
                    st.success("Inviato a WSJT-X.") if svc.set_q65(mode) else st.error("WSJT-X non raggiungibile.")
            except Exception:
                pass
    rec = list(svc.recent)[:60]
    if rec:
        st.markdown("#### " + i18n.tr("Ultime decodifiche"))
        worked = {q["call"] for q in D.qsos(band=band)} if band else set()
        st.dataframe([{"UTC": r["utc"].strftime("%H:%M"), "Nominativo": r["call"], "Locator": r["grid"], "SNR (dB)": r["snr"],
                       "DT (s)": round(r["dt"], 1), "DF (Hz)": r["df"], "Messaggio": r["message"],
                       "Già collegato": "✓" if r["call"] in worked else ""} for r in rec], hide_index=True, width="stretch")
        if st.button("🎨 Colora in WSJT-X: verde chi ti manca, grigio chi hai già collegato", key="wj_hl"):
            n = 0
            for call in {r["call"] for r in rec if r["call"]}:
                n += svc.highlight(call, "#c8e6c9" if call not in worked else "#e0e0e0")
            st.success(i18n.tr("Nominativi colorati") + f": {n}")
    if svc.errors:
        with st.expander("⚠️ Messaggi"):
            for e in list(svc.errors)[-10:]:
                st.text(e)



def _sunscan_box(D, setup, f, Dm, hp_expected):
    import io
    import numpy as _np
    import pandas as pd
    from emelab import sunscan
    st.divider()
    st.subheader("☀️ Scansione del Sole")
    st.caption("Incolla o carica le letture di una scansione: a croce (in AZ e in EL attraverso il Sole) oppure a deriva "
               "(antenna ferma, il Sole passa). EMELab adatta il modello disco solare ⊗ fascio gaussiano (IZ0JNY) e ti dà "
               "la larghezza del fascio vera, l'errore di puntamento in quel punto e il fattore Y. L'errore si salva nel "
               "diario e alimenta il modello di puntamento.")
    c = st.columns(4)
    kind = c[0].radio("Scansione", ["AZ (in croce)", "EL (in croce)", "Deriva (antenna ferma)"], key="ss_kind")
    unit = c[1].radio("Livelli in", ["dB", "lineare"], key="ss_unit", horizontal=True)
    t_meas = c[2].text_input("Ora della misura (UTC, AAAA-MM-GG HH:MM)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), key="ss_t")
    up = c[3].file_uploader("CSV (due colonne)", type=["csv", "txt"], key="ss_csv",
                            help="prima colonna: angolo rispetto al Sole calcolato (°) — oppure secondi per la deriva; "
                                 "seconda colonna: livello")
    txt = st.text_area("…oppure incolla qui le coppie «angolo  livello» (una per riga)", key="ss_txt", height=120,
                       placeholder="-1.0  0.2\n-0.5  3.1\n0.0  6.0\n0.5  3.4\n1.0  0.3")
    raw = up.getvalue().decode("utf-8", "replace") if up is not None else txt
    pts = []
    for line in (raw or "").splitlines():
        v = [x for x in line.replace(";", " ").replace(",", " ").replace("\t", " ").split() if x]
        try:
            if len(v) >= 2:
                pts.append((float(v[0]), float(v[1])))
        except ValueError:
            continue
    if len(pts) < 7:
        st.info("Servono almeno 7 punti, da una parte all'altra del Sole.")
        return
    try:
        t = datetime.strptime(t_meas.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        st.error("Ora non valida.")
        return
    stn = D.station()
    x = _np.array([p[0] for p in pts])
    y = _np.array([p[1] for p in pts])
    if kind.startswith("Deriva"):
        sun = astro.sky(t, stn.get("lat") or 0.0, stn.get("lon") or 0.0, stn.get("height_m") or 0.0).sun
        x = sunscan.drift_angle(x - x[_np.argmax(y)], sun.dec)
    p_lin = 10 ** (y / 10) if unit == "dB" else y
    fit = sunscan.fit_scan(x, p_lin)
    m = st.columns(4)
    m[0].metric("HPBW misurata", f"{fit['hpbw_deg']:.3f}°", f"{fit['hpbw_deg'] - hp_expected:+.3f}° " + i18n.tr("rispetto al calcolo"),
                delta_color="off")
    m[1].metric("Errore di puntamento", f"{fit['offset_deg']:+.3f}°", f"{abs(fit['offset_deg']) / fit['hpbw_deg']:.2f} HPBW",
                delta_color="off")
    m[2].metric("Fattore Y del Sole", f"{fit['y_db']:.2f} dB")
    m[3].metric("k = HPBW·D/λ", f"{fit['hpbw_deg'] * Dm / (0.299792458 / f):.1f}°",
                help=i18n.tr("circa 58° con illuminazione uniforme, 66° con 10 dB di taper, 70° con 15 dB"))
    xs = _np.linspace(x.min(), x.max(), 300)
    mod = sunscan.scan_disc(xs - fit["offset_deg"], fit["hpbw_deg"])
    fig = go.Figure(go.Scatter(x=x, y=p_lin, mode="markers", name="misura"))
    fig.add_trace(go.Scatter(x=xs, y=fit["baseline"] + fit["amplitude"] * mod / mod.max(), name="modello disco ⊗ fascio"))
    fig.add_vline(x=fit["offset_deg"], line_dash="dot")
    fig.update_layout(title="Scansione del Sole e modello", xaxis_title="°", yaxis_title=i18n.tr("livello (lineare)"), height=320,
                      margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    if fit["rms"] > 0.1 * fit["amplitude"]:
        st.warning("Il modello si adatta male (vento, QRM o scansione non centrata): ripeti la misura.")
    if setup and not kind.startswith("Deriva") and st.button("💾 Salva l'errore nel diario (per il modello di puntamento)", key="ss_save"):
        calc = analysis.snapshot(stn, setup, t, None, openems_local.load_settings().get("emelab_flux"))
        az = fit["offset_deg"] if kind.startswith("AZ") else None
        el = fit["offset_deg"] if kind.startswith("EL") else None
        D.add(utc=t, setup_id=setup["id"], band_ghz=float(setup["band_ghz"]), kind="sun", y_db=fit["y_db"],
              az_off=az, el_off=el, notes=i18n.tr("scansione del Sole") + f" ({i18n.tr(kind)}), HPBW {fit['hpbw_deg']:.3f}°",
              calc=_clean(calc))
        st.success("Salvato nel diario misure.")


def _pointing_model_box(D, hp):
    import numpy as _np
    st.divider()
    st.subheader("📐 Modello di puntamento")
    pm = analysis.pointing_model(D.measurements())
    if not pm:
        st.info("Servono almeno 3 misure di Sole o Luna con l'errore in AZ e in EL (dalle scansioni qui sopra o dalla scheda "
                "Nuova misura), meglio se a elevazioni diverse.")
        return
    m = st.columns(4)
    m[0].metric("Zero AZ (encoder)", f"{pm['az_zero']:+.3f}°")
    m[1].metric("Inclinazione dell'asse", f"{pm['az_tilt']:+.3f}°", help=i18n.tr("termine in tan(EL): il supporto non è in bolla"))
    m[2].metric("Zero EL", f"{pm['el_zero']:+.3f}°")
    m[3].metric("Flessione (cos EL)", f"{pm['el_sag']:+.3f}°", help=i18n.tr("il peso del feed fa scendere il fascio più in basso"))
    rms = math.hypot(pm["rms_az"], pm["rms_el"])
    ok = rms <= hp / 10
    (st.success if ok else st.warning)(
        i18n.tr("Residuo dopo la correzione") + f" {rms:.3f}° ({rms / hp:.2f} HPBW) — " +
        (i18n.tr("ottimo: sotto HPBW/10") if ok else i18n.tr("sopra HPBW/10: aggiungi misure a elevazioni diverse e controlla gioco e vento")))
    st.caption(f"{pm['n']} " + i18n.tr("misure. Correzioni da impostare nel controllo del rotore: AZ −(zero AZ)/cos(EL) − inclinazione·tan(EL), "
                                       "EL −(zero EL) − flessione·cos(EL)."))
    el = _np.linspace(5, 85, 50)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=el, y=pm["az_zero"] + pm["az_tilt"] * _np.tan(_np.radians(el)), name="errore AZ·cos(EL)"))
    fig.add_trace(go.Scatter(x=el, y=pm["el_zero"] + pm["el_sag"] * _np.cos(_np.radians(el)), name="errore EL"))
    fig.update_layout(title="Errore previsto contro elevazione", xaxis_title="EL (°)", yaxis_title="°", height=300,
                      margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
