# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📷 Astronomical camera tab: live Moon from a ZWO ASI camera, grid with the centre, the Moon's offset in degrees
and an alarm (banner, notice on every tab, beep) when the antenna goes out of tracking. Off until switched on."""
from __future__ import annotations

import time

import streamlit as _st

from emelab import i18n, stations, moontrack as mt
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state


def _set(**kw):
    try:
        openems_local.save_settings(**kw)
    except Exception:
        pass


BANDS_GHZ = [10.368, 24.048, 47.088, 76.032, 122.25, 134.928]


def _wsjtx_mhz():
    """Dial frequency of WSJT-X (MHz) when EMELab is listening to it and it is on an EME band, else None."""
    try:
        from emelab import stations, ui
        svc = ui._wsjtx_service()
        hz = (svc.status or {}).get("dial_hz") if svc.running else None
        return hz / 1e6 if hz and stations.band_of(hz / 1e6) else None
    except Exception:
        return None


def beam(D, manual_ghz: float, hpbw_override: float = 0.0) -> dict:
    """Operating frequency (WSJT-X, else the band chosen by hand), the setup of that band and its −3 dB beamwidth."""
    from emelab import analysis
    mhz = _wsjtx_mhz()
    src = "wsjtx" if mhz else "manual"
    f_ghz = mhz / 1000 if mhz else float(manual_ghz)
    setup, hp = None, 0.0
    try:
        sets = [x for x in D.setups(f_ghz) if x.get("D_m")]
        if sets:
            setup = sets[0]
            hp = analysis.hpbw_of(setup)
    except Exception:
        pass
    if hpbw_override:
        hp = hpbw_override
    return {"f_ghz": f_ghz, "mhz": mhz, "source": src, "setup": setup, "hpbw": hp}


def _widget(fn, label, key, default, save_key, *a, **kw):
    """A widget whose value is remembered in settings.json."""
    sets = S["_cam_sets"]
    if key not in S:
        S[key] = sets.get(save_key, default)
    v = fn(label, *a, key=key, **kw)
    if sets.get(save_key, default) != v:
        sets[save_key] = v
        _set(**{save_key: v})
    return v


def tab(D):
    st.subheader("📷 Telecamera Astronomica")
    st.caption("Immagine dal vivo della Luna da una telecamera ZWO ASI in USB (es. ASI120MM Mini con cercatore 30F4), "
               "montata sulla parabola: una griglia mostra il centro e EMELab avvisa quando la Luna esce dalla tolleranza, "
               "cioè quando vai fuori tracking. La telecamera viene solo letta: EMELab non muove nulla.")
    S["_cam_sets"] = sets = openems_local.load_settings()
    on = st.toggle("Abilita la telecamera", bool(sets.get("cam_enabled", False)), key="cam_on",
                   help="spenta, EMELab non apre la telecamera e la lascia libera per ASICap o altri programmi")
    if on != bool(sets.get("cam_enabled", False)):
        _set(cam_enabled=on)
        sets["cam_enabled"] = on
    if not on:
        mt.stop()
        st.info("Telecamera spenta. Accendila con l'interruttore qui sopra quando ti serve il controllo del tracking.")
        return

    src_kind = _widget(st.radio, "Sorgente", "cam_src", "asi", "cam_source", ["asi", "sim", "still"], horizontal=True,
                       format_func={"asi": "Telecamera ZWO ASI", "sim": "Simulatore (prova senza telecamera)",
                                    "still": "Immagine da file"}.get)
    c = st.columns(4)
    exp = _widget(c[0].number_input, "Esposizione (ms)", "cam_exp", 5.0, "cam_exposure_ms", 0.032, 2000.0, step=1.0,
                  help="la Luna è luminosa: con il 30F4 bastano pochi millisecondi e guadagno basso")
    gain = _widget(c[1].number_input, "Guadagno", "cam_gain", 0, "cam_gain", 0, 600, step=5)
    auto = _widget(c[2].checkbox, "Esposizione automatica", "cam_auto", False, "cam_auto")
    binning = _widget(c[3].selectbox, "Binning", "cam_bin", 2, "cam_bin", [1, 2],
                      help="2×2: immagine più piccola e più veloce, precisione ancora molto migliore del fascio")

    src = None
    if src_kind == "asi":
        with st.expander("🔌 Libreria ZWO e telecamera", expanded=not mt.load_library(sets.get("cam_dll", ""))["ok"]):
            dll = _widget(st.text_input, "Percorso di ASICamera2.dll (vuoto = cerco da solo)", "cam_dll", "", "cam_dll",
                          help="ASICap, ASIStudio, SharpCap e FireCapture la installano nella loro cartella")
            lib = mt.load_library(dll)
            if lib["ok"]:
                st.caption(i18n.tr("Libreria ZWO") + f": `{lib['path']}`")
            else:
                st.warning(i18n.tr(lib["error"]))
                st.markdown(i18n.tr("Installa l'ASI Camera Driver e ASICap da") + " https://www.zwoastro.com/software/ "
                            + i18n.tr("oppure usa il simulatore per provare la scheda."))
        cams, err = mt.list_cameras(sets.get("cam_dll", ""))
        if err:
            st.error(i18n.tr(err))
            if st.button("🔄 Cerca di nuovo la telecamera", key="cam_rescan"):
                st.rerun()
            return
        names = [f"{x['name']} ({x['width']}×{x['height']}, {x['pixel_um']:g} µm)" for x in cams]
        i = st.selectbox("Telecamera", range(len(cams)), format_func=lambda j: names[j], key="cam_idx")
        cam = cams[i]
        src = mt.ensure(("asi", cam["index"], binning), lambda: mt.AsiSource(cam["index"], exp, gain, binning, auto))
        src.set_controls(exp, gain, auto)
    elif src_kind == "sim":
        src = mt.ensure(("sim",), mt.SimSource)
    else:
        up = st.file_uploader("Foto della Luna (PNG, JPG, FITS esclusi)", type=["png", "jpg", "jpeg", "bmp", "tif", "tiff"],
                              key="cam_file")
        if up is None:
            mt.stop()
            st.caption("Carica una foto della Luna fatta con la telecamera per provare il riconoscimento del centro.")
            return
        src = mt.ensure(("still", up.name, up.size), lambda: mt.StillSource(up.getvalue()))

    st.markdown("#### " + i18n.tr("🎯 Centro, scala e tolleranza"))
    c = st.columns(4)
    scale_mode = _widget(c[0].radio, "Scala dell'immagine", "cam_scale", "optics", "cam_scale_mode", ["optics", "moon"],
                         format_func={"optics": "Dall'ottica (pixel e focale)", "moon": "Dal diametro della Luna"}.get,
                         help="dal diametro della Luna (0,52°) serve la Luna intera nell'immagine")
    focal = _widget(c[1].number_input, "Focale dell'obiettivo (mm)", "cam_focal", mt.DEFAULT_FOCAL_MM, "cam_focal_mm",
                    1.0, 5000.0, step=10.0, help="ZWO 30F4: 120 mm")
    st.markdown("#### " + i18n.tr("🚨 Soglia d'allarme"))
    bands = sorted({round(float(x["band_ghz"]), 3) for x in D.setups()} | set(BANDS_GHZ))
    c = st.columns(4)
    tol_mode = _widget(c[0].radio, "Soglia", "cam_tolmode", "auto", "cam_tol_mode", ["auto", "fixed"],
                       format_func={"auto": "Suggerita dalla frequenza di lavoro", "fixed": "Scelta da me"}.get,
                       help="suggerita: dal fascio a −3 dB della parabola alla frequenza letta da WSJT-X, aggiornata da "
                            "sola quando cambi banda")
    max_loss = _widget(c[1].number_input, "Perdita massima sull'eco (dB)", "cam_maxloss", 1.0, "cam_max_echo_loss_db",
                       0.1, 6.0, step=0.1, format="%.1f",
                       help="perdita di puntamento accettata andata e ritorno: la soglia suggerita è "
                            "HPBW·√(dB/24) (1 dB ≈ 1/5 del fascio)")
    if "cam_tol_set" in S:                           # from «💡 Parti dalla soglia suggerita», before the widget is drawn
        S["cam_tol"], S["cam_tolmode"] = S.pop("cam_tol_set"), "fixed"
    tol_fixed = _widget(c[2].number_input, "Soglia scelta da me (°)", "cam_tol", 0.05, "cam_tol_deg",
                        0.005, 5.0, step=0.005, format="%.3f",
                        help="parti dalla suggerita e alza o abbassa di 0,005° alla volta (es. 0,01° · 0,05° · 0,1°)")
    man_ghz = _widget(c[3].selectbox, "Banda quando WSJT-X non è collegato", "cam_band", 24.048, "cam_band_ghz", bands,
                      format_func=lambda g: stations.band_label(g))
    hp_over = _widget(st.number_input, "Fascio a −3 dB (°, 0 = calcolato dalla configurazione della banda)", "cam_hpbw0",
                      0.0, "cam_hpbw_override", 0.0, 10.0, step=0.01, format="%.3f")
    bm = beam(D, man_ghz, hp_over)
    _beam_info(bm, max_loss, tol_mode, tol_fixed)
    sug = mt.suggested_tol(bm["hpbw"], max_loss)
    if sug and st.button("💡 Parti dalla soglia suggerita e poi regolala a mano", key="cam_tol_sug",
                         help="copia la soglia suggerita nella «Soglia scelta da me»: poi la alzi o abbassi come vuoi"):
        S["cam_tol_set"] = sug
        _set(cam_tol_deg=sug, cam_tol_mode="fixed")
        st.rerun()
    c = st.columns(4)
    hold = _widget(c[0].number_input, "Allarme dopo (s) fuori tolleranza", "cam_hold", 3.0, "cam_hold_s", 0.0, 60.0, step=1.0)
    grid = _widget(c[1].selectbox, "Passo della griglia (°)", "cam_grid", 0.1, "cam_grid_deg", [0.05, 0.1, 0.2, 0.25, 0.5],
                   help="0,1° con linee sottili ogni 0,05°: con ASI120MM Mini e 30F4 un decimo di grado sono ~28 pixel "
                        "(binning 2×2), 0,05° sono ~14 pixel")
    refresh = _widget(c[2].selectbox, "Aggiorna ogni (s)", "cam_refresh", 1.0, "cam_refresh_s", [0.5, 1.0, 2.0, 5.0])
    beep = _widget(c[3].checkbox, "🔔 Suono d'allarme", "cam_beep", True, "cam_beep")
    c = st.columns(4)
    flip_x = _widget(c[0].checkbox, "Immagine specchiata (destra/sinistra)", "cam_fx", False, "cam_flip_x")
    flip_y = _widget(c[1].checkbox, "Immagine capovolta (su/giù)", "cam_fy", False, "cam_flip_y")
    st.markdown("#### " + i18n.tr("📡 Allineamento telecamera ↔ fascio radio"))
    st.caption("La croce azzurra è il centro radio: dove punta davvero la parabola. All'inizio è il centro dell'immagine; "
               "dopo l'allineamento con il rumore del Sole (o della Luna) scrivi qui lo scostamento misurato, "
               "oppure punta al massimo del segnale e premi 🎯.")
    if "cam_rf_set" in S:                            # value from the 🎯 button, before the widgets are drawn
        S["cam_rfaz"], S["cam_rfel"] = S.pop("cam_rf_set")
    c = st.columns(4)
    rf_az = _widget(c[0].number_input, "Centro radio: Az rispetto alla telecamera (°)", "cam_rfaz", 0.0, "cam_rf_az_deg",
                    -3.0, 3.0, step=0.01, format="%.3f")
    rf_el = _widget(c[1].number_input, "Centro radio: El rispetto alla telecamera (°)", "cam_rfel", 0.0, "cam_rf_el_deg",
                    -3.0, 3.0, step=0.01, format="%.3f")
    cfg = dict(tol_mode=tol_mode, tol_fixed=tol_fixed, max_loss=max_loss, man_ghz=man_ghz, hp_over=hp_over, D=D,
               hold=hold, grid=grid, flip_x=flip_x, flip_y=flip_y, beep=beep,
               scale_mode=scale_mode, focal=focal, rf=(rf_az, rf_el))
    if c[2].button("🎯 Usa la posizione attuale della Luna come centro", key="cam_setref",
                   help="la telecamera non è mai perfettamente allineata al fascio radio: punta al massimo del rumore "
                        "della Luna (o del Sole) e premi qui"):
        fr, _ = src.latest()
        det = mt.detect(fr) if fr is not None else None
        if det:
            h, w = fr.shape[:2]
            o = mt.offset(det, ((w - 1) / 2, (h - 1) / 2), _scale(src, det, cfg), flip_x, flip_y)
            S["cam_rf_set"] = (round(o["az_deg"], 3), round(o["el_deg"], 3))
            _set(cam_rf_az_deg=S["cam_rf_set"][0], cam_rf_el_deg=S["cam_rf_set"][1])
            st.rerun()
        else:
            st.warning("Luna non trovata nell'immagine: centro non cambiato.")
    if c[3].button("↩️ Centro dell'immagine", key="cam_resetref"):
        S["cam_rf_set"] = (0.0, 0.0)
        _set(cam_rf_az_deg=0.0, cam_rf_el_deg=0.0)
        st.rerun()

    def sun_in_camera():
        fr, _ = src.latest()
        det = mt.detect(fr) if fr is not None else None
        if not det:
            return None
        h, w = fr.shape[:2]
        o = mt.offset(det, ((w - 1) / 2, (h - 1) / 2), _scale(src, None, {**cfg, "scale_mode": "optics"}), flip_x, flip_y)
        return o["az_deg"], o["el_deg"]

    def save_rf(az, el):
        S["cam_rf_set"] = (az, el)
        _set(cam_rf_az_deg=az, cam_rf_el_deg=el)
        st.rerun()

    from emelab import ui_sunalign
    ui_sunalign.wizard(D, sun_in_camera, save_rf)

    frag = getattr(_st, "fragment", None)
    live = frag(run_every=refresh)(_live) if frag else _live
    live(cfg)
    st.caption("Az + = la Luna è a destra del centro: gira la parabola verso destra (azimut che cresce); El + = la Luna è "
               "più in alto: alza la parabola. Vale con la telecamera dritta; altrimenti usa specchiata/capovolta. "
               "Con la Luna non piena il centro trovato è quello della parte illuminata: per questo conviene "
               "fissare il centro con il pulsante 🎯 quando sei sul massimo del segnale.")


def _tol(bm, max_loss, tol_mode, tol_fixed) -> float:
    sug = mt.suggested_tol(bm["hpbw"], max_loss)
    return sug if tol_mode == "auto" and sug else tol_fixed


def _beam_info(bm, max_loss, tol_mode, tol_fixed):
    """Where the frequency comes from, the beamwidth, the suggested threshold and the loss at common thresholds."""
    where = (i18n.tr("📻 WSJT-X") + f": {bm['mhz']:.3f} MHz" if bm["source"] == "wsjtx"
             else i18n.tr("Banda scelta a mano (WSJT-X non collegato)"))
    if not bm["hpbw"]:
        st.warning(i18n.tr("Nessuna configurazione con il diametro della parabola per") + f" {stations.band_label(bm['f_ghz'])}: "
                   + i18n.tr("inseriscila in 🛰️ Configurazioni o scrivi il fascio a −3 dB qui sopra. Uso la soglia scelta da me."))
        return
    sug = mt.suggested_tol(bm["hpbw"], max_loss)
    stp = bm.get("setup") or {}
    st.info(f"{where} → {stations.band_label(bm['f_ghz'])}" + (f" · {stp.get('name')} (⌀ {stp.get('D_m'):g} m)" if stp else "")
            + " · " + i18n.tr("fascio a −3 dB") + f" **{bm['hpbw']:.3f}°** · " + i18n.tr("soglia suggerita") + f" **{sug:.3f}°** "
            + f"({i18n.tr('perdita eco')} ≤ {max_loss:.1f} dB) · " + i18n.tr("in uso") + f": **{_tol(bm, max_loss, tol_mode, tol_fixed):.3f}°**")
    rows = [{"Soglia (°)": f"{t:g}", "Frazione del fascio": f"1/{bm['hpbw'] / t:.0f}" if t < bm["hpbw"] else f"{t / bm['hpbw']:.1f}×",
             "Perdita andata (dB)": round(mt.pointing_loss_db(t, bm["hpbw"]), 2),
             "Perdita eco (dB)": round(2 * mt.pointing_loss_db(t, bm["hpbw"]), 2)} for t in mt.TOL_CHOICES]
    with st.expander(i18n.tr("Quanto perdo con ogni soglia a") + f" {stations.band_label(bm['f_ghz'])}"):
        st.dataframe(rows, hide_index=True, width="stretch")


def _scale(src, det, cfg) -> float:
    """Degrees per pixel of the frame: from the optics, or from the Moon's diameter."""
    sc = 0.0
    if cfg["scale_mode"] == "moon" and det:
        sc = mt.deg_per_px_from_moon(det["r"])
    if not sc:
        info = src.info or {}
        sc = mt.deg_per_px(info.get("pixel_um") or mt.DEFAULT_PIXEL_UM, info.get("bin") or 1, cfg["focal"])
    return sc or mt.deg_per_px(mt.DEFAULT_PIXEL_UM, 1, mt.DEFAULT_FOCAL_MM)


def cfg_from_settings(D, sets: dict | None = None) -> dict:
    """The camera settings saved by this tab, for other tabs (🔴 Live) that show the camera without its widgets."""
    s = sets if sets is not None else openems_local.load_settings()
    return dict(tol_mode=s.get("cam_tol_mode", "auto"), tol_fixed=s.get("cam_tol_deg", 0.05),
                max_loss=s.get("cam_max_echo_loss_db", 1.0), man_ghz=s.get("cam_band_ghz", 24.048),
                hp_over=s.get("cam_hpbw_override", 0.0), D=D, hold=s.get("cam_hold_s", 3.0), grid=s.get("cam_grid_deg", 0.1),
                flip_x=s.get("cam_flip_x", False), flip_y=s.get("cam_flip_y", False), beep=s.get("cam_beep", True),
                scale_mode=s.get("cam_scale_mode", "optics"), focal=s.get("cam_focal_mm", mt.DEFAULT_FOCAL_MM),
                rf=(s.get("cam_rf_az_deg", 0.0), s.get("cam_rf_el_deg", 0.0)))


def start_from_settings(sets: dict | None = None):
    """Start (or keep) the camera chosen in this tab, without drawing it: for 🔴 Live. Returns the source or None."""
    s = sets if sets is not None else openems_local.load_settings()
    if not s.get("cam_enabled"):
        return None
    kind = s.get("cam_source", "asi")
    if kind == "sim":
        return mt.ensure(("sim",), mt.SimSource)
    if kind == "asi":
        cur = mt.current()
        if cur is not None and cur.kind == "asi":
            return cur
        cams, err = mt.list_cameras(s.get("cam_dll", ""))
        if err or not cams:
            return None
        b = int(s.get("cam_bin", 2))
        exp, gain, auto = float(s.get("cam_exposure_ms", 5.0)), int(s.get("cam_gain", 0)), bool(s.get("cam_auto", False))
        return mt.ensure(("asi", cams[0]["index"], b), lambda: mt.AsiSource(cams[0]["index"], exp, gain, b, auto))
    return mt.current()


def measure(cfg) -> dict | None:
    """Moon offset on the newest frame: {frame, t, det, off, scale, ref, tol, hpbw, alarm, started}. The same frame is
    measured once even when two tabs show it (one alarm, one history)."""
    src = mt.current()
    if src is None:
        return None
    frame, t = src.latest()
    if frame is None:
        return {"frame": None, "error": src.error}
    last = getattr(src, "last_meas", None)
    if last and last["t"] == t and last["cfg_key"] == _cfg_key(cfg):
        return {**last, "started": False}
    bm = beam(cfg["D"], cfg["man_ghz"], cfg["hp_over"])          # follows WSJT-X when you change band
    tol = _tol(bm, cfg["max_loss"], cfg["tol_mode"], cfg["tol_fixed"])
    h, w = frame.shape[:2]
    det = mt.detect(frame)
    scale = _scale(src, det, cfg)
    ref = mt.ref_point(w, h, cfg["rf"][0], cfg["rf"][1], scale, cfg["flip_x"], cfg["flip_y"])
    off = mt.offset(det, ref, scale, cfg["flip_x"], cfg["flip_y"]) if det else None
    now = time.time()
    alarm = getattr(src, "alarm", None) or mt.Alarm()
    src.alarm = alarm
    started = alarm.update(now, off["total_deg"] if off else None, tol, cfg["hold"])
    src.history.append((now, off["az_deg"] if off else None, off["el_deg"] if off else None))
    m = {"frame": frame, "t": t, "now": now, "det": det, "off": off, "scale": scale, "ref": ref, "tol": tol,
         "hpbw": bm["hpbw"], "beam": bm, "alarm": alarm, "started": started, "w": w, "h": h, "src": src,
         "cfg_key": _cfg_key(cfg)}
    src.last_meas = m
    return m


def _cfg_key(cfg) -> tuple:
    return tuple((k, v) for k, v in sorted(cfg.items()) if k != "D")


def alarm_feedback(m, cfg):
    """Toast and beep when the alarm starts."""
    if m and m.get("started"):
        _st.toast(i18n.tr("🚨 Telecamera: fuori tracking! Controlla il puntamento della parabola.") + " "
                  + i18n.tr("(clicca per aprire la scheda)"), icon="🚨")
        if cfg["beep"]:
            try:
                _st.audio(mt.beep_wav(), format="audio/wav", autoplay=True)
            except TypeError:
                pass


def _live(cfg):
    m = measure(cfg)
    if m is None:
        return
    if m["frame"] is None:
        if m.get("error"):
            st.error(i18n.tr(m["error"]) if m["error"].startswith("impossibile") else m["error"])
        else:
            st.info("In attesa del primo fotogramma dalla telecamera…")
        return
    frame, t, det, off, scale, ref, alarm, src = (m[k] for k in ("frame", "t", "det", "off", "scale", "ref", "alarm", "src"))
    w, h, now = m["w"], m["h"], m["now"]
    cfg = {**cfg, "tol": m["tol"], "hpbw": m["hpbw"]}
    img = mt.overlay(frame, det, ref, cfg["tol"] / scale, cfg["grid"] / scale, alarm.active, grid_deg=cfg["grid"])
    c = st.columns([3, 1])
    c[0].image(img, width="stretch")
    c[0].caption("✚ " + i18n.tr("azzurro: centro radio") + " · ✖ " + i18n.tr("giallo: centro della Luna") + " · "
                 + i18n.tr("cerchio: tolleranza") + f" {cfg['tol']:.3f}° · " + i18n.tr("griglia") + f" {cfg['grid']:g}°")
    with c[1]:
        if alarm.active:
            st.error("🚨 FUORI TRACKING" if alarm.reason == "out" else "🚨 LUNA PERSA: non è più nell'immagine")
        elif off and off["total_deg"] > cfg["tol"]:
            st.warning("⚠️ Fuori tolleranza")
        elif off:
            st.success("✅ In tracking")
        else:
            st.warning("Luna non trovata nell'immagine")
        if off:
            st.metric("Scostamento", f"{off['total_deg']:.3f}°")
            st.metric("Az", f"{off['az_deg']:+.3f}°")
            st.metric("El", f"{off['el_deg']:+.3f}°")
            if cfg["hpbw"]:
                st.metric("Perdita di puntamento (eco)", f"{2 * mt.pointing_loss_db(off['total_deg'], cfg['hpbw']):.2f} dB")
        st.caption(f"{(src.info or {}).get('name', '')} · {w}×{h} · {scale * 3600:.1f}\"/px · "
                   + i18n.tr("fotogramma di") + f" {max(0.0, now - t):.1f} s " + i18n.tr("fa"))
    alarm_feedback(m, cfg)
    from emelab import ui_live
    ui_live.corrections(off, "cam")
    hist = [(x, a, e) for x, a, e in src.history if now - x <= 600 and a is not None]
    if len(hist) > 2:
        import pandas as pd
        df = pd.DataFrame({"s": [x - now for x, _, _ in hist], "Az (°)": [a for _, a, _ in hist],
                           "El (°)": [e for _, _, e in hist]}).set_index("s")
        st.caption("Scostamento negli ultimi 10 minuti (secondi fa)")
        st.line_chart(df, height=180)
