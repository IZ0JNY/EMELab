# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📻 WSJT-X tab: the Echo mode measurements of WSJT-X (all_echo.txt) compared with the own echo EMELab expects for
the configuration, and saved, if you want, as echo measurements of the diary."""
from __future__ import annotations

import streamlit as _st

import math

from emelab import analysis, echo, i18n, wsjtx_ini
from emelab import db as edb
from emelab import settings as openems_local

st = i18n.wrap(_st)


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, float) and math.isnan(o):
        return None
    return o.isoformat() if hasattr(o, "isoformat") else o


def _best_setup(D, stn, sets: list[dict], run: dict):
    """The configuration whose expected spread at the time of the run is closest to the Width WSJT-X used."""
    best, err = sets[0], None
    for s in sets:
        try:
            sp = analysis.snapshot(stn, s, run["mid"])["spread_hz"]
        except Exception:
            continue
        e = abs(sp - run["width_hz"])
        if err is None or e < err:
            best, err = s, e
    return best


def render(D):
    st.markdown("#### " + i18n.tr("🔁 Modo Echo di WSJT-X"))
    st.caption("Dalla versione 2.6 il modo Echo integra la potenza su tutto lo spread: il suo S/N vale anche per le eco "
               "molto allargate da 10 GHz in su (DL3WDG). Il segnale deve stare a 1500 Hz ±10 Hz: Doppler «Own Echo» o "
               "CFOM. EMELab legge all_echo.txt accanto a WSJT-X.ini e confronta ogni misura con l'eco che calcola per la "
               "tua configurazione. Le prime eco possono uscire troppo forti per i picchi di librazione: conta il valore "
               "finale, quando SNR e dBerr sono stabili.")
    sets_l = openems_local.load_settings()
    path = echo.find(wsjtx_ini.find(sets_l.get("wsjtx_file") or None))
    up = None if path else st.file_uploader("all_echo.txt di WSJT-X", type=["txt"], key="echo_up")
    if path:
        runs = echo.read(path)
        st.caption(i18n.tr("File") + f": {path}")
    elif up is not None:
        runs = [echo.summary(r) for r in reversed(echo.runs(echo.parse(up.getvalue().decode("utf-8", "replace"))))]
    else:
        st.info("all_echo.txt non trovato: si crea quando usi il modo Echo di WSJT-X. Puoi anche caricarlo qui.")
        return
    if not runs:
        st.info("Nessuna misura Echo nel file.")
        return
    stn, sets = D.station(), D.setups()
    if not sets or not stn.get("lat"):
        st.info("Servono stazione e configurazione per il confronto con il calcolo.")
        return
    saved = {m["utc"] for m in D.measurements(kind="echo")}
    rows, calc_of = [], []
    for r in runs[:20]:
        setup = _best_setup(D, stn, sets, r)
        c = analysis.snapshot(stn, setup, r["mid"])
        e = c.get("echo") or {}
        exp = e.get("snr_1hz_db")
        calc_of.append((setup, c))
        rows.append({"UTC": f"{r['start']:%Y-%m-%d %H:%M}", "Cicli": r["cycles"],
                     "SNR (dB/2500 Hz)": round(r["snr_db"], 1) if r["echo"] else None,
                     "dBerr": r["dberr_db"], "SNR 1 Hz (dB)": round(r["snr_1hz_db"], 1) if r["echo"] else None,
                     "Atteso EMELab 1 Hz (dB)": round(exp, 1) if exp is not None else None,
                     "Differenza (dB)": round(r["snr_1hz_db"] - exp, 1) if r["echo"] and exp is not None else None,
                     "Width WSJT-X (Hz)": round(r["width_hz"]), "Spread EMELab (Hz)": round(c.get("spread_hz") or 0),
                     "Configurazione": setup["name"],
                     "Stato": ("✅" if r["settled"] else "⏳") if r["echo"] else "❌",
                     "Nel diario": "✓" if edb.iso_utc(r["mid"]) in saved else ""})
    _st.dataframe([{i18n.tr(k): v for k, v in x.items()} for x in rows], hide_index=True, width="stretch")
    st.caption("✅ valore stabile (almeno 5 cicli con eco, dBerr ≤ 1 dB) · ⏳ servono altri cicli · ❌ nessuna eco trovata. "
               "SNR 1 Hz = SNR in 2500 Hz + 34,0 dB. Una differenza negativa vuol dire eco più deboli del calcolo: "
               "potenza, puntamento, perdite o Tsys da controllare. La configurazione è quella con lo spread più vicino "
               "alla Width usata da WSJT-X. Nel modo Monitor (segnale di un'altra stazione) il confronto non vale.")
    first = next((i for i, r in enumerate(runs[:20]) if r["echo"]), 0)
    pick = st.selectbox("Misura da registrare nel diario", range(len(rows)), index=first, key="echo_pick",
                        format_func=lambda i: f"{rows[i]['UTC']} UTC · {rows[i]['Cicli']} " + i18n.tr("cicli"))
    r, (setup, c) = runs[pick], calc_of[pick]
    if not r["echo"]:
        st.caption("In questa misura WSJT-X non ha trovato l'eco: non c'è niente da registrare.")
    elif st.button("💾 Registra come misura d'eco", key="echo_save"):
        D.add(utc=r["mid"], setup_id=setup["id"], band_ghz=setup["band_ghz"], kind="echo", snr_db=round(r["snr_1hz_db"], 2),
              notes=i18n.tr("Modo Echo di WSJT-X") + f": {r['cycles']} " + i18n.tr("cicli") + f", SNR {r['snr_db']:.1f} dB/2500 Hz, "
              f"dBerr {r['dberr_db']}, Width {r['width_hz']:.0f} Hz", wx_source="WSJT-X Echo",
              calc=_clean(c), extra={"wsjtx_echo": _clean(r)})
        st.success("Misura registrata.")
        _st.rerun()
