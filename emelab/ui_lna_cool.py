# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""❄️ Cooled LNA, in the 🔊 LNA tab: the LNA cooled by a Peltier cell, dry ice, liquid nitrogen or a cryocooler,
or a dedicated cryogenic LNA, and what changes for every band: NF, Tsys, G/T, Sun and Moon noise, own echo."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as _st

from emelab import analysis, astro, chain, cooling, i18n, parts
from emelab import settings as openems_local

st = i18n.wrap(_st)
ASSUMED_COLOR = "#e8590c"


def _bl(band) -> str:
    from emelab.stations import band_label
    return band_label(band)


def _orange(txt: str) -> str:
    return f"<span style='color:{ASSUMED_COLOR}'>{txt}</span>"


def _best_times(stn: dict, now: datetime):
    """Highest Sun and highest Moon in the next 24 h (the noise and echo values are given there)."""
    tr = astro.track(now, 24, 30, stn["lat"], stn["lon"], stn.get("height_m") or 0.0)
    return max(tr, key=lambda s: s.sun.el).t, max(tr, key=lambda s: s.moon.el).t


def _band_rows(D, stn, t_phys_c: float, a: float, t_ref_c: float, cool_line: bool, cryo: dict | None) -> list[dict]:
    """Per configuration: warm and cooled values with the Sun and the Moon at their highest in the next 24 h."""
    sets = D.setups()
    if not sets or stn.get("lat") is None:
        return []
    now = datetime.now(timezone.utc)
    t_sun, t_moon = _best_times(stn, now)
    flux = openems_local.load_settings().get("emelab_flux")
    rows = []
    for s in sets:
        nf = float(s.get("nf_db") or 1.5)
        if cryo and cryo.get("band") is not None and abs(float(cryo["band"]) - float(s["band_ghz"])) > 1:
            continue
        if cryo:
            te_c = cooling.te_of_nf(cryo["nf_db"])
        else:
            te_c = cooling.cooled_stage(nf, t_phys_c, t_ref_c, a)["te_K"]
        sc = cooling.setup_cooled(s, te_c, cool_line, t_phys_c)
        out = {}
        for tag, ss in (("w", s), ("c", sc)):
            cs = analysis.snapshot(stn, ss, t_sun, None, flux)
            cm = analysis.snapshot(stn, ss, t_moon, None, flux)
            out[tag] = {"sun_y": cs["sun"]["y_db"], "moon_y": cm["moon"]["y_db"], "tsys": cm["moon"]["tsys"],
                        "gt": cs["gt_expected"], "echo": (cm.get("echo") or {}).get("snr_1hz_db")}
        w, c = out["w"], out["c"]

        def f(v, n=1):
            return "" if v is None or v != v else f"{v:.{n}f}"

        def d(x, y, n=2):
            return "" if x is None or y is None or x != x or y != y else f"{y - x:+.{n}f}"
        rows.append({"Banda": _bl(s["band_ghz"]), "Configurazione": s["name"],
                     "NF LNA (dB)": f"{nf:.2f} → {cooling.nf_of_te(te_c):.2f}",
                     "Te LNA (K)": f"{cooling.te_of_nf(nf):.0f} → {te_c:.0f}",
                     "Tsys verso la Luna (K)": f"{f(w['tsys'], 0)} → {f(c['tsys'], 0)}",
                     "ΔG/T (dB)": d(-10 * math.log10(w["tsys"]), -10 * math.log10(c["tsys"])) if w["tsys"] == w["tsys"] else "",
                     "Rumore solare (dB)": f"{f(w['sun_y'])} → {f(c['sun_y'])}",
                     "Rumore lunare (dB)": f"{f(w['moon_y'], 2)} → {f(c['moon_y'], 2)}",
                     "Eco propria (dB in 1 Hz)": f"{f(w['echo'])} → {f(c['echo'])}" if w["echo"] is not None else "",
                     "Δ eco (dB)": d(w["echo"], c["echo"])})
    return rows, t_sun, t_moon


def box(D, nf1: float, g1: float, nf2: float, l_pre: float, t_ant: float, tphys: float, gain: float, band: float | None):
    st.divider()
    st.subheader("❄️ LNA raffreddato o criogenico")
    st.caption("Il rumore di un LNA a HEMT/pHEMT scende quasi in proporzione alla sua temperatura fisica (modello di "
               "Pospieszalski): una cella di Peltier toglie qualche decimo di dB, l'azoto liquido o un criocooler molto di "
               "più. Qui scegli come raffreddi e vedi cosa cambia per ogni banda: NF, Tsys, G/T, rumore di Sole e Luna, eco.")
    ss = _st.session_state
    c = st.columns([2, 1, 1, 1])
    what = c[0].radio("Cosa vuoi provare", ["Raffreddare il mio LNA", "Un LNA criogenico dal catalogo"], key="lc_what",
                      horizontal=True)
    t_amb = c[1].number_input("Temperatura ambiente (°C)", -30.0, 45.0, 15.0, 1.0, key="lc_tamb",
                              help="dove sta l'LNA: al fuoco della parabola")
    rh = c[2].number_input("Umidità (%)", 5.0, 100.0, 70.0, 1.0, key="lc_rh")
    cool_line = c[3].checkbox("Raffredda anche le perdite prima dell'LNA", False, key="lc_line",
                              help="relè, guida e transizioni nello stesso contenitore freddo (dewar) dell'LNA")
    cryo = None
    assumed = []
    if what == "Raffreddare il mio LNA":
        c = st.columns([2, 1, 1, 1])
        meth = c[0].selectbox("Raffreddamento", list(cooling.METHODS), index=1, key="lc_meth",
                              format_func=lambda k: cooling.METHODS[k][0])
        want = None
        if meth in cooling.PELTIER_MAX_DT:
            lim = t_amb - cooling.PELTIER_MAX_DT[meth]
            want = c[1].number_input("Temperatura raggiunta dall'LNA (°C)", -80.0, 45.0,
                                     max(t_amb + cooling.METHODS[meth][2], lim), 1.0, key=f"lc_tp_{meth}",
                                     help=i18n.tr("con il calore dell'LNA e un contenitore piccolo; limite") + f" {lim:.0f} °C")
            assumed.append(i18n.tr("ΔT della cella di Peltier"))
        elif meth == "custom":
            want = c[1].number_input("Temperatura dell'LNA (°C)", -269.0, 45.0, -40.0, 1.0, key="lc_tc")
        t_c, warn = cooling.physical_temp_c(meth, t_amb, want)
        a = c[2].number_input("Parte del rumore che non scende (%)", 0.0, 50.0, cooling.A_NONTHERMAL * 100, 1.0,
                              key="lc_a", help="elettroni caldi nel canale, adattamento d'ingresso: 5–15 % nei LNA "
                                               "criogenici misurati caldi e freddi") / 100
        t_ref = c[3].number_input("Temperatura della NF di datasheet (°C)", -40.0, 60.0, cooling.T_REF_C, 1.0, key="lc_tref")
        if abs(a - cooling.A_NONTHERMAL) < 1e-9:
            assumed.append(i18n.tr("parte del rumore che non scende") + " 10 %")
        if t_ref == cooling.T_REF_C:
            assumed.append(i18n.tr("NF di datasheet a") + " +25 °C")
        if warn:
            st.warning(i18n.tr("Con la cella di Peltier si scende al massimo di circa") +
                       f" {cooling.PELTIER_MAX_DT[meth]:.0f} K " + i18n.tr("sotto l'ambiente: uso") + f" {t_c:.0f} °C.")
        r = cooling.cooled_stage(nf1, t_c, t_ref, a)
        nf_c, te_c = r["nf_db"], r["te_K"]
    else:
        rows = [d for d in parts.devices(D, band or 10.368, "LNA") if d.get("cryo_k")]
        if not rows:
            st.info("Nessun LNA criogenico in catalogo per questa banda: aggiungilo nella libreria con NF e temperatura.")
            return
        c = st.columns([2, 1, 1])
        i = c[0].selectbox("LNA criogenico", range(len(rows)), key="lc_dev",
                           format_func=lambda j: f"{rows[j]['part']} · {rows[j]['maker']}" + (" ✅" if rows[j].get("verified") else ""))
        dev = rows[i]
        t_c = float(dev["cryo_k"]) - cooling.ZERO_C
        nf_c = float(dev.get("nf_db") or 0.1)
        te_c = cooling.te_of_nf(nf_c)
        a, t_ref = cooling.A_NONTHERMAL, cooling.T_REF_C
        c[1].metric("Rumore", f"{te_c:.1f} K", f"NF {nf_c:.2f} dB", delta_color="off", delta_arrow="off")
        c[2].metric("Temperatura fisica", f"{dev['cryo_k']:.0f} K", delta_color="off")
        st.caption(i18n.tr(dev.get("notes") or "") + (" · " + i18n.tr("Fonte") + f": {dev.get('source')}" if dev.get("source") else ""))
        if dev.get("check"):
            assumed.append(i18n.tr("dati da confermare sul datasheet alla frequenza di lavoro"))
        cryo = {"nf_db": nf_c, "band": band}
    # this tab's chain, warm and cold
    t_line = (t_c + cooling.ZERO_C) if cool_line else tphys

    def tsys(nf_lna, tl):
        return chain.rx_chain([chain.passive("a", l_pre, tl), {"name": "b", "gain_db": g1, "nf_db": nf_lna},
                               {"name": "c", "gain_db": 10.0, "nf_db": nf2}], t_ant)["tsys_K"]
    t_w, t_k = tsys(nf1, tphys), tsys(nf_c, t_line)
    m = st.columns(5)
    m[0].metric("Temperatura dell'LNA", f"{t_c:.0f} °C", f"{t_c + cooling.ZERO_C:.0f} K", delta_color="off", delta_arrow="off")
    m[1].metric("NF LNA", f"{nf_c:.2f} dB", f"{nf_c - nf1:+.2f} dB", delta_color="inverse")
    m[2].metric("Te LNA", f"{te_c:.0f} K", f"{te_c - cooling.te_of_nf(nf1):+.0f} K", delta_color="inverse")
    m[3].metric("Tsys", f"{t_k:.0f} K", f"{t_k - t_w:+.0f} K", delta_color="inverse")
    m[4].metric("G/T e eco propria", f"{10 * math.log10(t_w / t_k):+.2f} dB", delta_color="off",
                help=i18n.tr("in ricezione l'eco guadagna quanto il G/T: stessa potenza, meno rumore"))
    if t_c < t_amb:
        dp = cooling.dew_point_c(t_amb, rh)
        if t_c <= dp:
            st.warning(i18n.tr("L'LNA è sotto il punto di rugiada") + f" ({dp:.0f} °C): " + i18n.tr(
                "condensa e ghiaccio sull'ingresso e sui connettori. Serve un contenitore stagno con essiccante o "
                "flusso di azoto secco, e una finestra in guida a bassa perdita."))
    if assumed:
        st.markdown(_orange(i18n.tr("presunto")) + ": " + ", ".join(_orange(x) for x in assumed),
                    unsafe_allow_html=True)
    # NF against the physical temperature
    import numpy as _np
    tk = _np.linspace(10, 330, 81)
    te0 = cooling.te_of_nf(nf1)
    fig = go.Figure(go.Scatter(x=tk - cooling.ZERO_C,
                               y=[cooling.nf_of_te(cooling.cooled_te(te0, x, t_ref + cooling.ZERO_C, a)) for x in tk],
                               name="NF del mio LNA"))
    for lab, tc in (("Peltier", t_amb - 30), ("ghiaccio secco", -78.5), ("azoto liquido", 77 - cooling.ZERO_C),
                    ("criocooler", 20 - cooling.ZERO_C)):
        fig.add_vline(x=tc, line_dash="dot", line_color="#888", annotation_text=lab, annotation_position="top")
    fig.add_trace(go.Scatter(x=[t_c], y=[nf_c], mode="markers", marker=dict(size=11, color="#1c7ed6"), name="scelta"))
    fig.update_layout(title="NF dell'LNA contro la sua temperatura fisica", xaxis_title="°C", yaxis_title="dB",
                      height=300, margin=dict(l=10, r=10, t=60, b=10), showlegend=False)
    st.plotly_chart(fig, width="stretch")
    # every band
    st.markdown("**" + i18n.tr("Effetto su ogni banda") + "**")
    stn = D.station()
    try:
        res = _band_rows(D, stn, t_c, a, t_ref, cool_line, cryo)
    except Exception as e:                                  # missing station data: the tab must still work
        res = []
        st.caption(i18n.tr("Calcolo per banda non disponibile") + f": {e}")
    if not res or not res[0]:
        st.info("Salva la stazione e almeno una configurazione per vedere l'effetto su ogni banda.")
    else:
        rows, t_sun, t_moon = res
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(i18n.tr("Valori con il Sole e la Luna al punto più alto delle prossime 24 ore") +
                   f" (☀️ {t_sun:%d/%m %H:%M}, 🌙 {t_moon:%d/%m %H:%M} UTC). " + i18n.tr(
                       "La NF della configurazione è presa come quella dell'LNA (stadi dopo trascurabili con guadagno ≥ 25 dB). "
                       "Il rumore solare e lunare cresce perché a parità di sorgente il rumore del sistema è più basso."))
    with st.expander("📚 Esperienze e riferimenti"):
        st.markdown("\n".join("- " + i18n.tr(x) for x in [
            "RW3BP (2016, banda 76 GHz): LNA OMMIC CGY2190UH raffreddato ad azoto liquido; Tsys 100 K, LNA circa 90 K "
            "(NF 1.2 dB), rumore solare 12.5 dB a 20° di elevazione, più di 10 dB meglio del ricevitore del 2013 "
            "(432 and Above EME News, novembre 2016).",
            "LNA criogenici commerciali (Low Noise Factory, Narda-MITEQ): 4–8 K di rumore a 4–20 K fisici; i pHEMT "
            "migliorano fino a circa 77 K, InP e mHEMT fino a 4 K.",
            "Cella di Peltier: il lato caldo va dissipato (dissipatore e ventola) e alimentato a parte; ogni 10 °C in "
            "meno valgono circa −0.02/−0.03 dB di NF su un LNA da 0.8–1 dB.",
            "Sotto il punto di rugiada l'acqua condensa: contenitore stagno, essiccante o azoto secco, finestra in "
            "guida (PTFE o mylar) tra il feed e la parte fredda.",
            "Il guadagno di un HEMT freddo cresce di qualche dB: controlla che i polarizzatori restino stabili e che "
            "il transverter dopo non vada in compressione."]))
