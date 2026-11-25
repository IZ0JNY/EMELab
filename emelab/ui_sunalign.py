# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🧭 Guided camera ↔ radio-beam alignment on the Sun (inside the 📷 Telecamera Astronomica tab).

1. preparation and the best band for it; 2. the noise maximum, from a DriverDish heatmap/scan file or from readings
typed by hand; 3. the Sun in the camera → the radio centre (cyan cross); 4. done.
EMELab never moves the dish: the scans are made by DriverDish (or by hand), EMELab only reads and computes."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as _st

from emelab import i18n, stations, moontrack as mt
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state
STEPS = ["1 · Preparazione", "2 · Massimo del rumore solare", "3 · Il Sole nella telecamera", "4 · Fatto"]


def _beams(D) -> dict:
    from emelab import analysis
    out = {}
    for s in D.setups():
        if s.get("D_m"):
            try:
                out[round(float(s["band_ghz"]), 3)] = analysis.hpbw_of(s)
            except Exception:
                pass
    return out


def _dd_status():
    """Last DriverDish status if the Tracking tab's reader is running (read-only), else None."""
    try:
        from emelab import ui_tracking
        sets = openems_local.load_settings()
        if not sets.get("dd_live"):                  # reader switched off in the Tracking tab: do not start one here
            return None
        mon = ui_tracking._monitor(sets.get("dd_host", "127.0.0.1"), int(sets.get("dd_port", 9999)))
        return mon.last if mon and mon.connected else None
    except Exception:
        return None


def wizard(D, sun_in_camera, save_rf):
    """sun_in_camera() → (az, el) offset of the bright disc from the image centre, or None;
    save_rf(az, el) stores the radio centre."""
    with st.expander("🧭 Procedura guidata: allinea la telecamera al fascio radio con il Sole",
                     expanded=S.get("sa_open", False)):
        S["sa_open"] = True
        if "sa_step_set" in S:                       # after a capture: straight to «Fatto»
            S["sa_step"] = S.pop("sa_step_set")
        step = st.radio("Passo", STEPS, horizontal=True, key="sa_step", label_visibility="collapsed")
        i = STEPS.index(step)
        [_prep, _peak, _camera, _done][i](D, sun_in_camera, save_rf)


def _prep(D, *_):
    beams = _beams(D)
    best = mt.best_alignment_band(beams)
    if best:
        st.success(i18n.tr("Banda consigliata per l'allineamento") + f": **{stations.band_label(best)}** "
                   + i18n.tr("(fascio a −3 dB") + f" {beams[best]:.2f}°). "
                   + i18n.tr("È il fascio più stretto ancora più largo del Sole (0,53°): il massimo del rumore è netto e "
                             "rotondo. Con un fascio più stretto del Sole la cima diventa piatta e il centro si trova peggio."))
        rows = [{"Banda": stations.band_label(f), "Fascio a −3 dB (°)": round(h, 3),
                 "Fascio / Sole": round(h / 0.53, 2)} for f, h in sorted(beams.items())]
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("Inserisci almeno una configurazione con il diametro della parabola in 🛰️ Configurazioni: "
                "così ti consiglio la banda migliore per l'allineamento.")
    st.error("☀️ **Filtro solare sul cercatore 30F4 prima di inquadrare il Sole** (pellicola solare tipo AstroSolar "
             "davanti all'obiettivo). Senza filtro il Sole può danneggiare il sensore della telecamera. Senza filtro usa "
             "il metodo alternativo del passo 3 (prima il Sole solo in radio, poi la Luna in telecamera).")
    st.markdown(i18n.tr("Prima di cominciare") + ":\n\n"
                + "\n".join("- " + i18n.tr(x) for x in (
                    "DriverDish insegue il Sole (TRACKING ON).",
                    "Il ricevitore misura il rumore solare (SN di DriverDish o il tuo misuratore).",
                    "Telecamera abilitata: esposizione al minimo (0,03–1 ms) e guadagno 0 con il filtro solare.",
                    "EMELab non muove la parabola: le scansioni le fai con DriverDish (heatmap o drift scan) o a mano.")))
    dd = _dd_status()
    if dd:
        st.caption(i18n.tr("DriverDish ora") + f": {dd.get('target', '—')} · Az {dd.get('dish_az', 0):.3f}° El {dd.get('dish_el', 0):.3f}° · "
                   + "Offset Az " + f"{dd.get('off_az', 0):+.3f}° El {dd.get('off_el', 0):+.3f}° · "
                   + ("TRACKING ON" if dd.get("tracking") else "TRACKING OFF"))


def _peak(D, *_):
    st.markdown("Trova di quanto il massimo del rumore solare è spostato dal centro della scansione (dove DriverDish "
                "punta il Sole).")
    how = st.radio("Metodo", ["file", "hand"], horizontal=True, key="sa_how",
                   format_func={"file": "Heatmap o scansione di DriverDish (file)", "hand": "Letture a mano"}.get)
    az = el = db = None
    if how == "file":
        up = st.file_uploader("File della heatmap / scansione (CSV o testo)", type=["csv", "txt", "dat"], key="sa_file",
                              help="colonne Az, El e SN (dB), oppure una matrice con gli offset Az in alto e gli offset El a "
                                   "sinistra. Mandami un file di DriverDish se il formato non viene riconosciuto.")
        if up is not None:
            h = mt.parse_heatmap(up.getvalue().decode("utf-8", "replace"))
            az, el, db = h["az"], h["el"], h["db"]
            if not db:
                st.warning("Nel file non ho trovato offset Az, El e rumore in dB.")
    else:
        import pandas as pd
        st.caption("Scrivi il rumore (dB) letto con la parabola spostata degli offset indicati rispetto al Sole: una croce "
                   "(solo Az, poi solo El) o una griglia. Bastano 5 punti; meglio 9 o più.")
        ka, ke, kd = (i18n.tr(k) for k in ("Offset Az (°)", "Offset El (°)", "Rumore (dB)"))   # headers in the language
        sk = "sa_rows_" + i18n.get_lang()
        base = S.get(sk) or [{ka: a, ke: e, kd: None} for a, e in ((-0.4, 0), (-0.2, 0), (0, 0), (0.2, 0), (0.4, 0),
                                                                   (0, -0.4), (0, -0.2), (0, 0.2), (0, 0.4))]
        ed = _st.data_editor(pd.DataFrame(base, columns=[ka, ke, kd]), num_rows="dynamic", hide_index=True,
                             key="sa_editor_" + i18n.get_lang(), width="stretch")
        S[sk] = ed.to_dict("records")
        rows = [r for r in S[sk] if all(isinstance(r.get(k), (int, float)) and r.get(k) == r.get(k) for k in (ka, ke, kd))]
        az, el, db = [r[ka] for r in rows], [r[ke] for r in rows], [r[kd] for r in rows]
    if not db or len(db) < 3:
        return
    pk = _fit(az, el, db)
    if pk is None:
        st.warning("Punti insufficienti per trovare il massimo: servono almeno 3 letture lungo Az e 3 lungo El.")
        return
    S["sa_peak"] = pk
    st.success(i18n.tr("Massimo del rumore solare") + f": Az **{pk[0]:+.3f}°**, El **{pk[1]:+.3f}°** "
               + i18n.tr("rispetto al centro della scansione") + f" ({max(db):.1f} dB).")
    st.markdown(i18n.tr("Per portare la parabola sul massimo aggiungi in DriverDish") + f" Az {pk[0]:+.3f}° · El {pk[1]:+.3f}° "
                + i18n.tr("agli offset attuali (EMELab non la muove), oppure lasciala dov'è: al passo 3 ne tengo conto io."))
    _plot(az, el, db, pk)


def _fit(az, el, db):
    """2D maximum, or the two 1D maxima of a cross scan."""
    import numpy as np
    a, e, d = (np.asarray(v, float) for v in (az, el, db))
    on_az, on_el = np.isclose(e, 0), np.isclose(a, 0)
    if len(set(a.tolist())) >= 3 and len(set(e.tolist())) >= 3 and (on_az.sum() + on_el.sum() - 1) < len(d):
        p = mt.fit_peak_2d(a, e, d)
        if p:
            return p
    pa = mt.fit_peak_1d(a[on_az], d[on_az]) if on_az.sum() >= 3 else None
    pe = mt.fit_peak_1d(e[on_el], d[on_el]) if on_el.sum() >= 3 else None
    if pa is None and pe is None:
        return None
    return (pa or 0.0, pe or 0.0)


def _plot(az, el, db, pk):
    try:
        import plotly.graph_objects as go
        fig = go.Figure(go.Scatter(x=az, y=el, mode="markers", marker=dict(size=14, color=db, colorscale="Inferno",
                                                                          showscale=True, colorbar=dict(title="dB")),
                                   text=[f"{v:.1f} dB" for v in db], name="SN"))
        fig.add_trace(go.Scatter(x=[pk[0]], y=[pk[1]], mode="markers", name="max",
                                 marker=dict(symbol="x", size=18, color="#00e5ff", line=dict(width=2))))
        fig.update_layout(height=360, xaxis_title="Offset Az (°)", yaxis_title="Offset El (°)",
                          yaxis_scaleanchor="x", margin=dict(l=40, r=10, t=10, b=40))
        st.plotly_chart(fig, width="stretch")
    except Exception:
        pass


def _camera(D, sun_in_camera, save_rf):
    pk = S.get("sa_peak") or (0.0, 0.0)
    pos = sun_in_camera()
    if pos:
        st.info(i18n.tr("Sole nella telecamera") + f": Az {pos[0]:+.3f}°, El {pos[1]:+.3f}° "
                + i18n.tr("dal centro dell'immagine") + " · " + i18n.tr("massimo del passo 2") + f": Az {pk[0]:+.3f}°, El {pk[1]:+.3f}°")
    else:
        st.warning("Nessun disco luminoso nella telecamera: controlla filtro, esposizione e che il Sole sia inquadrato.")
    c = st.columns(2)
    if c[0].button("📸 La parabola è al centro della scansione: registra (tengo conto del massimo)", key="sa_cap_scan",
                   disabled=not pos):
        _save(save_rf, mt.rf_from_sun(pos, pk))
    if c[1].button("📸 La parabola è già sul massimo del rumore: registra", key="sa_cap_peak", disabled=not pos):
        _save(save_rf, mt.rf_from_sun(pos))
    st.markdown("**" + i18n.tr("Senza filtro solare") + "**: " + i18n.tr(
        "porta la parabola sul massimo del rumore solare in DriverDish (passo 2), lascia quegli offset, passa alla Luna "
        "e premi 🎯 «Usa la posizione attuale della Luna come centro» quando la Luna è inquadrata."))


def _save(save_rf, rf):
    openems_local.save_settings(cam_rf_aligned_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    S["sa_step_set"] = STEPS[3]
    save_rf(round(rf[0], 3), round(rf[1], 3))


def _done(D, *_):
    sets = openems_local.load_settings()
    st.success(i18n.tr("Centro radio salvato") + f": Az {sets.get('cam_rf_az_deg', 0):+.3f}°, El {sets.get('cam_rf_el_deg', 0):+.3f}° "
               + i18n.tr("rispetto al centro della telecamera") + (f" · {sets['cam_rf_aligned_utc'].replace('T', ' ')} UTC"
                                                                    if sets.get("cam_rf_aligned_utc") else ""))
    st.markdown(i18n.tr("La croce azzurra ora è il centro del fascio radio. Ripeti l'allineamento se smonti la "
                        "telecamera o cambi illuminatore; i valori restano modificabili a mano qui sopra."))
