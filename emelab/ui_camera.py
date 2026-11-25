# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📷 Astronomical camera tab: live Moon from a ZWO ASI camera, grid with the centre, the Moon's offset in degrees
and an alarm (banner, notice on every tab, beep) when the antenna goes out of tracking. Off until switched on."""
from __future__ import annotations

import time

import streamlit as _st

from emelab import i18n, moontrack as mt
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state


def _set(**kw):
    try:
        openems_local.save_settings(**kw)
    except Exception:
        pass


def _hpbw_default(D) -> float:
    try:
        from emelab import analysis
        hp = [analysis.hpbw_of(s) for s in D.setups() if s.get("D_m")]
        return round(min(hp), 3) if hp else 0.0
    except Exception:
        return 0.0


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
    hp0 = _hpbw_default(D)
    hpbw = _widget(c[2].number_input, "Fascio a −3 dB della parabola (°)", "cam_hpbw", hp0 or 0.5, "cam_hpbw",
                   0.01, 10.0, step=0.01, format="%.3f", help="dalla tua configurazione più stretta; serve per la perdita di puntamento")
    tol = _widget(c[3].number_input, "Tolleranza (°)", "cam_tol", round((hp0 or 0.4) / 4, 3), "cam_tol_deg",
                  0.005, 5.0, step=0.01, format="%.3f",
                  help="consigliata: 1/4 del fascio a −3 dB, cioè circa 0,75 dB di perdita in ciascun verso")
    c = st.columns(4)
    hold = _widget(c[0].number_input, "Allarme dopo (s) fuori tolleranza", "cam_hold", 3.0, "cam_hold_s", 0.0, 60.0, step=1.0)
    grid = _widget(c[1].number_input, "Passo della griglia (°)", "cam_grid", 0.1, "cam_grid_deg", 0.01, 2.0, step=0.05)
    refresh = _widget(c[2].selectbox, "Aggiorna ogni (s)", "cam_refresh", 1.0, "cam_refresh_s", [0.5, 1.0, 2.0, 5.0])
    beep = _widget(c[3].checkbox, "🔔 Suono d'allarme", "cam_beep", True, "cam_beep")
    c = st.columns(4)
    flip_x = _widget(c[0].checkbox, "Immagine specchiata (destra/sinistra)", "cam_fx", False, "cam_flip_x")
    flip_y = _widget(c[1].checkbox, "Immagine capovolta (su/giù)", "cam_fy", False, "cam_flip_y")
    if c[2].button("🎯 Usa la posizione attuale della Luna come centro", key="cam_setref",
                   help="la telecamera non è mai perfettamente allineata al fascio radio: punta al massimo del rumore "
                        "della Luna (o del Sole) e premi qui"):
        fr, _ = src.latest()
        det = mt.detect(fr) if fr is not None else None
        if det:
            _set(cam_ref=[det["cx"] / det["width"], det["cy"] / det["height"]])
            st.success("Centro salvato: ora la croce è sulla Luna.")
        else:
            st.warning("Luna non trovata nell'immagine: centro non cambiato.")
    if c[3].button("↩️ Centro dell'immagine", key="cam_resetref"):
        _set(cam_ref=None)

    cfg = dict(tol=tol, hold=hold, grid=grid, hpbw=hpbw, flip_x=flip_x, flip_y=flip_y, beep=beep,
               scale_mode=scale_mode, focal=focal, ref=openems_local.load_settings().get("cam_ref"))
    frag = getattr(_st, "fragment", None)
    live = frag(run_every=refresh)(_live) if frag else _live
    live(cfg)
    st.caption("Az + = la Luna è a destra del centro: gira la parabola verso destra (azimut che cresce); El + = la Luna è "
               "più in alto: alza la parabola. Vale con la telecamera dritta; altrimenti usa specchiata/capovolta. "
               "Con la Luna non piena il centro trovato è quello della parte illuminata: per questo conviene "
               "fissare il centro con il pulsante 🎯 quando sei sul massimo del segnale.")


def _live(cfg):
    src = mt.current()
    if src is None:
        return
    frame, t = src.latest()
    if frame is None:
        if src.error:
            st.error(i18n.tr(src.error) if src.error.startswith("impossibile") else src.error)
        else:
            st.info("In attesa del primo fotogramma dalla telecamera…")
        return
    h, w = frame.shape[:2]
    ref = (cfg["ref"][0] * w, cfg["ref"][1] * h) if cfg["ref"] else ((w - 1) / 2, (h - 1) / 2)
    det = mt.detect(frame)
    if cfg["scale_mode"] == "moon" and det:
        scale = mt.deg_per_px_from_moon(det["r"])
    else:
        info = src.info or {}
        scale = mt.deg_per_px(info.get("pixel_um") or mt.DEFAULT_PIXEL_UM, info.get("bin") or 1, cfg["focal"])
    scale = scale or mt.deg_per_px(mt.DEFAULT_PIXEL_UM, 1, mt.DEFAULT_FOCAL_MM)
    off = mt.offset(det, ref, scale, cfg["flip_x"], cfg["flip_y"]) if det else None
    now = time.time()
    alarm = getattr(src, "alarm", None) or mt.Alarm()
    src.alarm = alarm
    started = alarm.update(now, off["total_deg"] if off else None, cfg["tol"], cfg["hold"])
    src.history.append((now, off["az_deg"] if off else None, off["el_deg"] if off else None))

    img = mt.overlay(frame, det, ref, cfg["tol"] / scale, cfg["grid"] / scale, alarm.active)
    c = st.columns([3, 1])
    c[0].image(img, width="stretch")
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
    if started:
        _st.toast(i18n.tr("🚨 Telecamera: fuori tracking! Controlla il puntamento della parabola."), icon="🚨")
        if cfg["beep"]:
            try:
                _st.audio(mt.beep_wav(), format="audio/wav", autoplay=True)
            except TypeError:
                pass
    hist = [(x, a, e) for x, a, e in src.history if now - x <= 600 and a is not None]
    if len(hist) > 2:
        import pandas as pd
        df = pd.DataFrame({"s": [x - now for x, _, _ in hist], "Az (°)": [a for _, a, _ in hist],
                           "El (°)": [e for _, _, e in hist]}).set_index("s")
        st.caption("Scostamento negli ultimi 10 minuti (secondi fa)")
        st.line_chart(df, height=180)
