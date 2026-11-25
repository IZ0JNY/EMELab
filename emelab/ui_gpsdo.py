# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🛰️ GPSDO tab: your GPSDO and its live state, the reminder before operating, the catalogue of GPSDOs with the
phase noise multiplied up to the EME bands, the user's corrections and the phase-noise estimate from a WAV."""
from __future__ import annotations

import html

import streamlit as _st

from emelab import gpsdo, i18n, stations
from emelab import settings as openems_local

st = i18n.wrap(_st)
ASSUMED_COLOR = "#e8590c"
VERDICT = {"ok": "✅ adeguato", "marginal": "⚠️ al limite", "poor": "❌ troppo rumoroso"}


def _mine(models, sets):
    names = [gpsdo.model_key(m) for m in models]
    cur = sets.get("gpsdo_model") or "Leo Bodnar mini GPS Reference Clock"
    return names, (names.index(cur) if cur in names else 0)


def _status_box(sets):
    st.markdown("#### " + i18n.tr("📡 Stato del GPSDO"))
    c = st.columns([2, 2, 2])
    use = c[0].checkbox("Uso un GPSDO (promemoria prima di operare)", bool(sets.get("gpsdo_use", True)), key="gp_use")
    if use != bool(sets.get("gpsdo_use", True)):
        openems_local.save_settings(gpsdo_use=use)
    if c[1].button("✅ GPSDO acceso e agganciato", key="gp_ok"):
        gpsdo.confirm()
        st.success("Confermato per le prossime 12 ore.")
    if sets.get("gpsdo_ok_utc"):
        c[2].caption(i18n.tr("Ultima conferma") + f": {sets['gpsdo_ok_utc'].replace('T', ' ').replace('Z', ' UTC')}")
    c = st.columns([2, 3])
    if c[0].button("🛰️ Leggi lo stato dal GPSDO Leo Bodnar (USB)", key="gp_read",
                   help="mini GPS Reference Clock o GPS Disciplined Clock: GPS signal, PLL lock e numero di perdite di segnale. "
                        "Chiudi prima il programma di configurazione del costruttore."):
        _st.session_state["gp_state"] = gpsdo.read_leo_bodnar()
    r = _st.session_state.get("gp_state")
    if r:
        if r.get("error"):
            c[1].warning(i18n.tr("Lettura non riuscita") + f": {i18n.tr(r['error'])}")
        else:
            ok = r["gps_ok"] and r["pll_ok"]
            (c[1].success if ok else c[1].error)(
                f"{r['model']} · GPS signal {'OK' if r['gps_ok'] else 'NO'} · PLL lock {'OK' if r['pll_ok'] else 'NO'} · "
                + i18n.tr("perdite di segnale") + f" {r['loss_count']} · {r['utc']} UTC")
            if ok:
                gpsdo.confirm()
            with st.expander(i18n.tr("Dati grezzi dal GPSDO")):
                st.code(r.get("raw", ""))
    with st.expander(i18n.tr("Altri GPSDO: porta seriale con NMEA (LBE-142x, Thunderbolt con convertitore…)")):
        ports = gpsdo.serial_ports()
        c = st.columns([3, 1, 1])
        port = c[0].selectbox("Porta", [p for p, _ in ports] or ["—"], key="gp_port",
                              format_func=lambda p: next((f"{p} · {d}" for pp, d in ports if pp == p), p))
        baud = c[1].selectbox("Baud", [9600, 4800, 19200, 38400, 115200], key="gp_baud")
        if c[2].button("📥 Leggi", key="gp_nmea", disabled=not ports):
            _st.session_state["gp_nmea"] = gpsdo.read_serial(port, 3.0, int(baud))
        n = _st.session_state.get("gp_nmea")
        if n:
            if n.get("error"):
                st.warning(i18n.tr("Lettura non riuscita") + f": {i18n.tr(n['error'])}")
            elif not n.get("sentences"):
                st.warning("Nessuna frase NMEA ricevuta: controlla porta e velocità.")
            else:
                st.info(f"Fix GPS: {'sì' if n.get('fix') else 'no'} · " + i18n.tr("satelliti usati") + f" {n.get('sats_used') or '—'} · "
                        + i18n.tr("visibili") + f" {n.get('sats_seen') or '—'} · UTC {n.get('utc') or '—'}")


def _band_table(m, sets):
    from emelab import dx
    rows = []
    for band in ("10G", "24G", "47G"):
        mode = dx.band_mode(band, sets)
        r = gpsdo.band_report(m, band, mode)
        if r.get("ok") is None:
            continue
        row = {"Banda": stations.band_label(band), "Modo": f"Q65-{mode}", "Moltiplicazione (dB)": round(r["add_db"], 1)}
        for f in (10, 100, 1_000, 10_000):
            row[f"{f if f < 1000 else str(f // 1000) + 'k'} Hz (dBc/Hz)"] = round(r["at"][f], 0)
        row.update({"Fase rms oltre ½ tono (°)": round(r["rms_deg_out"], 1), "Perdita stimata (dB)": round(r["loss_db"], 2),
                    "Giudizio": i18n.tr(VERDICT[r["ok"]])})
        rows.append(row)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    return rows


def _catalogue(models, sets):
    st.markdown("#### " + i18n.tr("📚 Catalogo GPSDO e rumore di fase"))
    st.caption("Rumore di fase alle uscite di riferimento (di solito 10 MHz) dai datasheet o da misure pubblicate. "
               "Nelle bande EME il rumore del riferimento si moltiplica per N = f/f_ref: +60 dB a 10GHz, +68 dB a 24GHz, "
               "+74 dB a 47GHz. Le celle vuote non sono pubblicate: inseriscile dal datasheet o da una tua misura.")
    rows = []
    for m in models:
        pn = m.get("pn") or {}
        row = {"Modello": m["name"], "Costruttore": m.get("maker", ""), "Tipo": m.get("kind", ""),
               "f ref (MHz)": m.get("f_ref_mhz")}
        for f in gpsdo.OFFSETS:
            row[f"{f if f < 1000 else str(f // 1000) + 'k'} Hz"] = pn.get(f)
        row.update({"Uscite": m.get("outputs", ""), "Interfaccia": m.get("interface", ""),
                    "Stato": "✅ " + i18n.tr("verificato da te") if m.get("verified") else "", "Fonte": m.get("source", "")})
        rows.append(row)
    st.dataframe(rows, hide_index=True, width="stretch")


def _editor(m):
    key = gpsdo.model_key(m)
    with st.expander(i18n.tr("✏️ Correggi a mano") + f": {key}"):
        if m.get("origin") == "catalog":
            st.caption("⚠️ Valori del catalogo: salvandoli dopo averli controllati sul datasheet diventano ✅ verificati da te.")
        up = st.file_uploader("Datasheet PDF (cerco il rumore di fase nel testo)", type=["pdf"], key=f"gp_pdf_{key}")
        found = {}
        if up is not None:
            try:
                found = gpsdo.read_pn_text(stations.pdf_text(up.getvalue()))
                st.info(i18n.tr("Trovati nel PDF") + ": " + (", ".join(f"{k} Hz {v:.0f}" for k, v in sorted(found.items())) or "—"))
            except Exception as e:
                st.warning(f"PDF: {e}")
        pn = {**(m.get("pn") or {}), **found}
        c = st.columns(len(gpsdo.OFFSETS))
        vals = {}
        for i, f in enumerate(gpsdo.OFFSETS):
            v = c[i].text_input(f"{f if f < 1000 else str(f // 1000) + 'k'} Hz (dBc/Hz)", "" if pn.get(f) is None else f"{pn[f]:g}",
                                key=f"gp_pn_{key}_{f}_{len(found)}")
            vals[f] = v
        c = st.columns(3)
        fref = c[0].number_input("f ref (MHz)", 0.001, 2000.0, float(m.get("f_ref_mhz") or 10.0), key=f"gp_fref_{key}")
        src = c[1].text_input("Fonte o link al datasheet", m.get("source", ""), key=f"gp_src_{key}")
        c2 = st.columns(3)
        if c2[0].button("💾 Salva i valori (verificati da te)", key=f"gp_save_{key}"):
            gpsdo.save_model({**{k: v for k, v in m.items() if k not in ("catalog", "origin", "verified")},
                              "pn": vals, "f_ref_mhz": fref, "source": src})
            st.success("Valori salvati e segnati come verificati da te (solo su questo PC)")
            _st.rerun()
        if m.get("origin") == "edited" and c2[1].button("↩️ Ripristina i valori del catalogo", key=f"gp_rev_{key}"):
            gpsdo.revert_model(key)
            _st.rerun()
        if m.get("origin") == "mine" and c2[1].button("🗑️ Elimina", key=f"gp_del_{key}"):
            gpsdo.revert_model(key)
            _st.rerun()


def _add_model():
    with st.expander("➕ Aggiungi un GPSDO"):
        c = st.columns(3)
        name = c[0].text_input("Modello", key="gp_new_name")
        maker = c[1].text_input("Costruttore", key="gp_new_maker")
        fref = c[2].number_input("f ref (MHz)", 0.001, 2000.0, 10.0, key="gp_new_fref")
        if st.button("➕ Aggiungi", key="gp_new_add", disabled=not name.strip()):
            gpsdo.save_model({"name": name.strip(), "maker": maker.strip(), "kind": "GPSDO", "f_ref_mhz": fref, "pn": {}})
            _st.rerun()


def _wav_box(m):
    st.markdown("#### " + i18n.tr("🎙️ Stima del rumore di fase da una registrazione"))
    st.caption("EMELab non può misurare da solo il rumore di fase del GPSDO: serve un analizzatore di spettro o di rumore "
               "di fase. Può però stimarlo da un WAV con una portante non modulata e pulita (un beacon, la portante del "
               "tuo transverter, un generatore agganciato allo stesso GPSDO), per esempio salvato da WSJT-X con "
               "«Save all» o dall'SDR. Il risultato comprende tutta la catena (GPSDO, moltiplicazioni, LO del ricevitore, "
               "propagazione): se è vicino alla stima del catalogo, il GPSDO non è il limite.")
    up = st.file_uploader("WAV (PCM 16 bit, mono)", type=["wav"], key="gp_wav")
    if up is None:
        return
    try:
        r = gpsdo.measure_wav(up.getvalue())
    except Exception as e:
        st.error(f"WAV: {e}")
        return
    st.markdown(i18n.tr("Portante a") + f" **{r['f_carrier_hz']:.1f} Hz** · " + i18n.tr("risoluzione") + f" {r['resolution_hz']:.2f} Hz · "
                f"{r['seconds']:.0f} s · " + i18n.tr("fondo del rumore") + f" {r['floor_dbc_hz']:.0f} dBc/Hz")
    band = st.selectbox("Banda della registrazione", ["10G", "24G", "47G"], key="gp_wav_band", format_func=stations.band_label)
    exp = None
    if m.get("pn") and m.get("f_ref_mhz"):
        add = gpsdo.multiply_db(float(m["f_ref_mhz"]), gpsdo.BAND_MHZ[band])
        exp = {f: gpsdo.interp_pn(m["pn"], f) + add for f in r["pn"]}
    st.dataframe([{"Offset (Hz)": f, "Misurato (dBc/Hz)": round(v, 1),
                   "Atteso dal GPSDO (dBc/Hz)": round(exp[f], 1) if exp else None,
                   "Note": i18n.tr("al fondo del rumore") if v < r["floor_dbc_hz"] + 3 else ""} for f, v in sorted(r["pn"].items())],
                 hide_index=True, width="stretch")


def tab(D=None):
    st.subheader("GPSDO: riferimento di frequenza")
    sets = openems_local.load_settings()
    models = gpsdo.models(sets)
    _status_box(sets)
    names, idx = _mine(models, sets)
    st.markdown("#### " + i18n.tr("🔎 Il tuo GPSDO nelle bande EME"))
    pick = st.selectbox("Il tuo GPSDO", names, index=idx, key="gp_model")
    if pick != sets.get("gpsdo_model"):
        openems_local.save_settings(gpsdo_model=pick)
    m = models[names.index(pick)]
    st.caption(" · ".join(x for x in (m.get("outputs"), m.get("level"), m.get("stability"), m.get("interface"), m.get("power")) if x)
               + (f"  \n{i18n.tr('Fonte')}: {m['source']}" if m.get("source") else ""))
    used = m
    if not m.get("pn"):
        ref = [x for x in models if x.get("pn") and x.get("maker") == m.get("maker") and x.get("kind") == "GPSDO"]
        ref.sort(key=lambda x: "Disciplined Clock" not in x["name"])     # the mini's closest relative first
        if ref:
            alt = st.selectbox("Il costruttore non pubblica il rumore di fase di questo modello: stima con", [gpsdo.model_key(x) for x in ref],
                               key="gp_alt")
            used = next(x for x in ref if gpsdo.model_key(x) == alt)
            st.markdown(f"<span style='color:{ASSUMED_COLOR}'>{html.escape(i18n.tr('Valori presunti: stessa famiglia, non misurati sul tuo GPSDO'))}</span>",
                        unsafe_allow_html=True)
    if _band_table(used, sets):
        st.caption("Perdita stimata: energia che il rumore di fase sposta oltre metà della spaziatura dei toni Q65 "
                   "(60D: 13,3 Hz; 60E: 26,7 Hz), integrata fino a 100 kHz, come 4,34·σ² dB. La fase rms entro ½ tono "
                   "allarga solo la riga, come lo spread Doppler della Luna. Vale dentro la banda del PLL del tuo LO; "
                   "fuori conta il VCO del transverter.")
    _wav_box(used)
    _catalogue(models, sets)
    _editor(m)
    _add_model()
