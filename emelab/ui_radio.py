# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📻 Radio tab: the Icom IC-9700 on USB (CI-V), its display redrawn as on the radio (MAIN and SUB readouts, status
icons, S/Po meter, multi-function meter) and every setting read from the radio. Read-only by default: the commands
send something to the radio only when «Comandi verso la radio» is switched on and a button is pressed."""
from __future__ import annotations

import html
import time
from datetime import datetime, timezone

import streamlit as _st

from emelab import i18n, icom, stations
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state
ASSUMED = "#e8590c"
REFRESH_S = 2
SOURCES = {"wsjtx": "Solo WSJT-X (nessun CAT, sempre senza conflitti)",
           "rigctld": "rigctld condiviso con WSJT-X (Hamlib NET rigctl)",
           "serial": "CI-V diretto su porta COM (WSJT-X chiuso o presa REMOTE)"}


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


def _wsjtx_status():
    try:
        from emelab import ui
        svc = ui._wsjtx_service()
        return svc.status if svc and svc.last_seen else None
    except Exception:
        return None


# ------------------------------------------------------------------ the display
def fmt_freq(hz: int | None) -> tuple[str, str]:
    """«10368.100» and «.000» as on the Icom readout (MHz.kHz, then the Hz digits smaller)."""
    if not hz:
        return "----.---", ".---"
    mhz, rest = divmod(int(hz), 1_000_000)
    khz, hz_ = divmod(rest, 1000)
    return f"{mhz}.{khz:03d}", f".{hz_:03d}"


def _band(hz):
    if not hz:
        return ""
    b = stations.band_of(hz / 1e6)
    if b:
        return stations.band_label(b)
    return f"{hz / 1e6:.0f}MHz" if hz < 1e9 else f"{hz / 1e9:.1f}GHz"


def _icon(label, on, warn=False):
    cls = "on warn" if (on and warn) else ("on" if on else "off")
    return f'<span class="ic {cls}">{html.escape(label)}</span>'


def _bar(frac, n=30, hot_from=None, color="#f5f5f5"):
    k = max(0, min(n, round((frac or 0) * n)))
    cells = []
    for i in range(n):
        c = (("#ff4d4d" if hot_from is not None and i >= hot_from else color) if i < k else "#2b3440")
        cells.append(f'<i style="background:{c}"></i>')
    return '<span class="bar">' + "".join(cells) + "</span>"


def _s_frac(state):
    raw = state.get("s_raw")
    if raw is not None:
        return raw / 241
    m = state.get("s_meter") or ""
    if m.startswith("S9+"):
        return (120 + int(m[3:].rstrip("dB") or 0) / 60 * 121) / 241
    if m.startswith("S") and m[1:].isdigit():
        return int(m[1:]) / 9 * 120 / 241
    return 0


def render_display(state: dict, now: datetime | None = None) -> str:
    """HTML of the IC-9700 display (480×272 proportions, drawn at 2× on screen)."""
    now = now or datetime.now(timezone.utc)
    sel, uns = state.get("sel") or {}, state.get("unsel") or {}
    tx = bool(state.get("tx"))
    ms = state.get("main_sub") or "MAIN"
    main, sub = (sel, uns) if ms == "MAIN" else (uns, sel)
    wsjtx_only = state.get("source") == "wsjtx"

    def readout(v, big, name, active):
        f1, f2 = fmt_freq(v.get("freq_hz"))
        mode = icom.mode_label(v.get("mode"), v.get("data"))
        mode_style = f' style="color:{ASSUMED}"' if wsjtx_only else ""
        dig = (f'<span class="dig" style="color:{ASSUMED}">{html.escape(v["digital"])}</span>'
               if v.get("digital") else "")
        txb = '<span class="txb">TX</span>' if (tx and active) else ""
        ifx = ""
        if v.get("if_hz"):
            i1, i2 = fmt_freq(v["if_hz"])
            ifx = f'<span class="ifq">IF {i1}{i2}</span>'
        return (f'<div class="ro {"big" if big else "small"} {"act" if active else ""}">'
                f'<div class="left"><span class="vfo">{name}</span><span class="mode"{mode_style}>{html.escape(mode)}</span>'
                f'<span class="fil">{html.escape(v.get("filter") or "")}</span>{dig}</div>'
                f'<div class="freq">{f1}<small>{f2}</small></div>'
                f'<div class="right">{txb}<span class="band">{_band(v.get("freq_hz"))}</span>{ifx}</div></div>')

    icons = "".join([
        _icon("P.AMP", state.get("preamp")), _icon("ATT", state.get("att") not in (None, "OFF")),
        _icon("AGC-" + state["agc"][0] if state.get("agc") else "AGC", state.get("agc") is not None),
        _icon("NB", state.get("nb")), _icon("NR", state.get("nr")), _icon("AN", state.get("anf")),
        _icon("MN", state.get("mnf")), _icon("COMP", state.get("comp")), _icon("VOX", state.get("vox")),
        _icon("BK-IN", state.get("bkin") not in (None, "OFF")), _icon("MONI", state.get("monitor")),
        _icon("DUAL", state.get("dualwatch")), _icon("SAT", state.get("satmode")),
        _icon("SPLIT", state.get("split") == "SPLIT"),
        _icon("RIT " + (f"{state.get('rit_hz', 0):+d}" if state.get("rit_on") else ""), state.get("rit_on")),
        _icon("🔒", state.get("lock"), warn=True)])
    if tx:
        po = (state.get("po_pct") or 0) / 100
        meter = (f'<div class="mrow"><b>Po</b>{_bar(po / 1.2, hot_from=25)}'
                 f'<span class="sc">0 · 25 · 50 · 100%</span><em>{state.get("po_pct", "—")}%</em></div>')
    else:
        meter = (f'<div class="mrow"><b>S</b>{_bar(_s_frac(state), hot_from=15)}'
                 f'<span class="sc">1 · 3 · 5 · 7 · 9 · +20 · +40 · +60</span><em>{state.get("s_meter", "—")}</em></div>')

    def mf(name, val, frac, unit="", assumed=False):
        col = f' style="color:{ASSUMED}"' if assumed else ""
        v = "—" if val is None else f"{val}{unit}"
        return f'<div class="mf"><b>{name}</b>{_bar(frac, 14, color="#7fd3ff")}<em{col}>{v}</em></div>'

    multi = "".join([
        mf("Po", state.get("po_pct"), (state.get("po_pct") or 0) / 120, "%"),
        mf("SWR", state.get("swr"), ((state.get("swr") or 1) - 1) / 5),
        mf("ALC", state.get("alc_pct"), (state.get("alc_pct") or 0) / 100, "%"),
        mf("COMP", state.get("comp_raw"), (state.get("comp_raw") or 0) / 241),
        mf("Vd", state.get("vd_v"), (state.get("vd_v") or 0) / 16, "V"),
        mf("Id", state.get("id_a"), (state.get("id_a") or 0) / 20, "A", assumed=True)])
    levels = " ".join(f'<span><b>{k}</b> {"—" if state.get(v) is None else state.get(v)}</span>'
                      for k, v in (("AF", "af_pct"), ("RF", "rf_pct"), ("SQL", "sql_pct"), ("RF PWR", "power_pct"),
                                   ("MIC", "mic_pct"), ("NR", "nr_level")))
    src = {"serial": "CI-V USB", "rigctld": "rigctld", "wsjtx": "WSJT-X"}.get(state.get("source"), "—")
    css = """
<style>
.ic97box{container-type:inline-size;width:100%}
.ic97{width:auto;background:#0a0d12;border:1.46cqw solid #1d1f22;border-radius:1.04cqw;
 box-shadow:0 0.42cqw 1.46cqw rgba(0,0,0,.35);font-family:"Arial Narrow","Roboto Condensed",Arial,sans-serif;
 color:#f2f2f2;position:relative;overflow:hidden;box-sizing:content-box}
.ic97 .top{display:flex;gap:0.42cqw;align-items:center;height:3.12cqw;padding:0.31cqw 0.83cqw;background:#151a22;border-bottom:1px solid #2a3340}
.ic97 .ic{font-size:1.35cqw;padding:1px 0.52cqw;border-radius:0.31cqw;letter-spacing:.3px}
.ic97 .ic.off{color:#3d4654;border:1px solid #232a34}
.ic97 .ic.on{color:#0a0d12;background:#d8e4ee;border:1px solid #d8e4ee;font-weight:700}
.ic97 .ic.warn{background:#ffb000;border-color:#ffb000}
.ic97 .clk{margin-left:auto;font-size:1.88cqw;color:#d8e4ee}
.ic97 .ro{display:flex;align-items:center;padding:0 1.25cqw;border-bottom:1px solid #1c232d}
.ic97 .ro.big{height:15.62cqw}.ic97 .ro.small{height:9.58cqw}
.ic97 .ro.act .vfo{background:#1f6fd1;color:#fff}
.ic97 .left{width:15.62cqw;display:flex;flex-direction:column;gap:0.42cqw}
.ic97 .vfo{font-size:1.46cqw;color:#9fb3c8;border:1px solid #33465c;border-radius:0.31cqw;padding:0 0.62cqw;width:max-content}
.ic97 .mode{font-size:2.71cqw;font-weight:700;color:#ffffff}
.ic97 .small .mode{font-size:2.08cqw}
.ic97 .fil,.ic97 .dig{font-size:1.46cqw;color:#9fb3c8}
.ic97 .freq{flex:1;text-align:right;font-weight:700;letter-spacing:1px;font-variant-numeric:tabular-nums;line-height:1}
.ic97 .big .freq{font-size:10.21cqw}.ic97 .small .freq{font-size:6.04cqw;color:#cfd8e2}
.ic97 .freq small{font-size:.55em;margin-left:2px}
.ic97 .right{width:13cqw;display:flex;flex-direction:column;align-items:flex-end;gap:0.62cqw}
.ic97 .band{font-size:1.67cqw;color:#7fd3ff}
.ic97 .ifq{font-size:1.35cqw;color:#9fb3c8;white-space:nowrap}
.ic97 .txb{background:#e02424;color:#fff;font-weight:700;font-size:2.08cqw;padding:0 1.04cqw;border-radius:0.31cqw}
.ic97 .meter{padding:0.83cqw 1.25cqw 2px 1.25cqw}
.ic97 .mrow{display:flex;align-items:center;gap:0.83cqw;font-size:1.56cqw}
.ic97 .mrow b{width:2.71cqw;color:#9fb3c8}
.ic97 .bar{display:inline-flex;gap:2px}.ic97 .bar i{display:inline-block;width:1.25cqw;height:1.46cqw}
.ic97 .mrow .bar i{width:1.46cqw;height:1.88cqw}
.ic97 .sc{color:#6d7f93;font-size:1.35cqw;margin-left:0.62cqw}
.ic97 .mrow em,.ic97 .mf em{font-style:normal;margin-left:auto;color:#fff;min-width:7.29cqw;text-align:right}
.ic97 .multi{display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.42cqw 1.88cqw;padding:0.62cqw 1.25cqw 1.04cqw;font-size:1.46cqw}
.ic97 .mf{display:flex;align-items:center;gap:0.62cqw}.ic97 .mf b{width:4.17cqw;color:#9fb3c8}
.ic97 .mf .bar i{width:0.94cqw;height:1.15cqw}
.ic97 .lv{height:3.12cqw;display:flex;gap:1.88cqw;align-items:center;
 padding:0 1.25cqw;background:#151a22;border-top:1px solid #2a3340;font-size:1.46cqw;color:#cfd8e2}
.ic97 .lv b{color:#9fb3c8;font-weight:400}
.ic97 .lv .src{margin-left:auto;color:#6d7f93}
.ic97-name{text-align:center;font:600 1.25cqw Arial,sans-serif;letter-spacing:0.31cqw;color:#888;margin-top:0.42cqw}
</style>"""
    return (css + '<div class="ic97box"><div class="ic97">'
            f'<div class="top">{icons}<span class="clk">{now:%H:%M} UTC</span></div>'
            + readout(main, ms == "MAIN", "MAIN", ms == "MAIN")
            + readout(sub, ms == "SUB", "SUB", ms == "SUB")
            + f'<div class="meter">{meter}</div><div class="multi">{multi}</div>'
            f'<div class="lv">{levels}<span class="src">{html.escape(src)}</span></div>'
            '</div><div class="ic97-name">IC-9700 · EMELab</div></div>')


# ------------------------------------------------------------------ settings table
def _trv(v):
    if not v.get("if_hz"):
        return "n.d."
    return (f"{v['trv']}" + (f" ({v['trv_model']})" if v.get("trv_model") else "") + " · IF "
            + "{:,.0f} Hz".format(v["if_hz"]).replace(",", "."))


def _yn(v):
    return "n.d." if v is None else ("ON" if v is True else ("OFF" if v is False else str(v)))


def settings_rows(state: dict) -> list[tuple[str, str, str]]:
    """(group, name, value) of every setting read."""
    sel, uns = state.get("sel") or {}, state.get("unsel") or {}

    def fq(v):
        return "n.d." if not v.get("freq_hz") else "{:,.0f} Hz".format(v["freq_hz"]).replace(",", ".")
    rows = [("MAIN/SUB", "Ricevitore selezionato", state.get("main_sub") or "n.d."),
            ("MAIN/SUB", "Frequenza selezionata", fq(sel)),
            ("MAIN/SUB", "Modo selezionato", (icom.mode_label(sel.get("mode"), sel.get("data")) if sel.get("mode") else "n.d.")
             + (f" · {sel['filter']}" if sel.get("filter") else "")),
            ("MAIN/SUB", "Frequenza non selezionata", fq(uns)),
            ("MAIN/SUB", "Modo non selezionato", (icom.mode_label(uns.get("mode"), uns.get("data")) if uns.get("mode") else "n.d.")
             + (f" · {uns['filter']}" if uns.get("filter") else "")),
            ("MAIN/SUB", "Transverter sul selezionato", _trv(sel)),
            ("MAIN/SUB", "Transverter sul non selezionato", _trv(uns)),
            ("MAIN/SUB", "Dualwatch", _yn(state.get("dualwatch"))),
            ("MAIN/SUB", "Modo satellite", _yn(state.get("satmode"))),
            ("MAIN/SUB", "Split / Duplex", state.get("split") or "n.d."),
            ("RX", "Preamplificatore (P.AMP)", _yn(state.get("preamp"))),
            ("RX", "Attenuatore", state.get("att") or "n.d."),
            ("RX", "AGC", state.get("agc") or "n.d."),
            ("RX", "Noise blanker", _yn(state.get("nb")) + (f" · {state['nb_level']}%" if state.get("nb_level") is not None else "")),
            ("RX", "Noise reduction", _yn(state.get("nr")) + (f" · {state['nr_level']}" if state.get("nr_level") is not None else "")),
            ("RX", "Notch automatico / manuale", f"{_yn(state.get('anf'))} / {_yn(state.get('mnf'))}"),
            ("RX", "RIT", _yn(state.get("rit_on")) + (f" · {state['rit_hz']:+d} Hz" if state.get("rit_hz") is not None else "")),
            ("RX", "AF / RF gain / Squelch", " / ".join("n.d." if state.get(k) is None else f"{state[k]}%"
                                                    for k in ("af_pct", "rf_pct", "sql_pct"))),
            ("RX", "S-meter", state.get("s_meter") or "n.d."),
            ("TX", "Stato", "TX" if state.get("tx") else "RX"),
            ("TX", "Potenza RF", "n.d." if state.get("power_pct") is None else f"{state['power_pct']}%"),
            ("TX", "Mic gain", "n.d." if state.get("mic_pct") is None else f"{state['mic_pct']}%"),
            ("TX", "Compressore", _yn(state.get("comp")) + (f" · {state['comp_level']}" if state.get("comp_level") is not None else "")),
            ("TX", "VOX", _yn(state.get("vox")) + (f" · {state['vox_pct']}%" if state.get("vox_pct") is not None else "")),
            ("TX", "Break-in / velocità CW", f"{state.get('bkin') or 'n.d.'} / "
             + ("n.d." if state.get("key_wpm") is None else f"{state['key_wpm']} WPM")),
            ("TX", "Po / SWR / ALC", f"{state.get('po_pct', 'n.d.')}% / {state.get('swr', 'n.d.')} / {state.get('alc_pct', 'n.d.')}%"),
            ("Alimentazione", "Vd / Id", f"{state.get('vd_v', 'n.d.')} V / {state.get('id_a', 'n.d.')} A"),
            ("Varie", "Blocco manopola (LOCK)", _yn(state.get("lock"))),
            ("Varie", "Monitor", _yn(state.get("monitor")))]
    return rows


# ------------------------------------------------------------------ the tab
def _connection(sets):
    with st.expander("🔌 Collegamento con l'IC-9700", expanded=not sets.get("radio_source")):
        st.caption("WSJT-X tiene aperta la porta USB della radio e Windows la dà a un solo programma alla volta. "
                   "Scegli come EMELab legge la radio:")
        cur = sets.get("radio_source", "wsjtx")
        src = st.radio("Sorgente", list(SOURCES), index=list(SOURCES).index(cur) if cur in SOURCES else 0,
                       format_func=lambda k: i18n.tr(SOURCES[k]), key="rad_src", horizontal=True)
        c = st.columns(4)
        if src == "serial":
            try:
                from emelab import gpsdo
                ports = [p for p, _ in gpsdo.serial_ports()]
            except Exception:
                ports = []
            port = c[0].selectbox("Porta COM", ports or [sets.get("radio_port") or "COM3"], key="rad_port")
            baud = c[1].selectbox("Velocità", [115200, 57600, 38400, 19200, 9600],
                                  index=[115200, 57600, 38400, 19200, 9600].index(int(sets.get("radio_baud", 115200))),
                                  key="rad_baud")
            addr = c[2].text_input("Indirizzo CI-V", f"{int(sets.get('radio_addr', icom.DEFAULT_ADDR)):02X}h",
                                   key="rad_addr")
            new = dict(radio_port=port, radio_baud=int(baud),
                       radio_addr=int(addr.rstrip("hH") or "A2", 16) if addr.rstrip("hH") else icom.DEFAULT_ADDR)
            st.caption("Con WSJT-X aperto la porta USB è occupata: usa la presa REMOTE con un cavo CI-V "
                       "(menu SET › Connectors › CI-V › CI-V USB Port = Link to [REMOTE]) oppure rigctld.")
        elif src == "rigctld":
            try:
                from emelab import gpsdo
                ports = [p for p, _ in gpsdo.serial_ports()]
            except Exception:
                ports = []
            cur_port = sets.get("radio_port") or "COM3"
            port = c[0].selectbox("Porta COM della radio", list(dict.fromkeys(ports + [cur_port])),
                                  index=list(dict.fromkeys(ports + [cur_port])).index(cur_port), key="rad_rport_com")
            bauds = [115200, 57600, 38400, 19200, 9600]
            baud = c[1].selectbox("Velocità", bauds, index=bauds.index(int(sets.get("radio_baud", 115200))),
                                  key="rad_rbaud")
            host = c[2].text_input("Host", sets.get("radio_host", "127.0.0.1"), key="rad_host")
            rport = c[3].number_input("Porta TCP", 1, 65535, int(sets.get("radio_rport", 4532)), key="rad_rport")
            new = dict(radio_port=port, radio_baud=int(baud), radio_host=host, radio_rport=int(rport))
            st.markdown(i18n.tr("rigctld fa da centralino: apre lui la porta della radio e la condivide con WSJT-X e "
                                "EMELab. Va avviato con WSJT-X chiuso (o con il CAT di WSJT-X già su rigctld)."))
            exe = icom.find_rigctld([sets.get("wsjtx_bin_dir") or ""])
            alive = icom.rigctld_alive(host, int(rport))
            c = st.columns([2, 5])
            if c[0].button("▶️ Avvia rigctld", key="rad_rig_start", disabled=alive or not exe,
                           help="avvia rigctld-wsjtx.exe della cartella di WSJT-X per l'IC-9700"):
                ok, msg = icom.start_rigctld(exe, port, int(baud), int(rport))
                S["rad_rig_msg"] = (ok, i18n.tr(msg))
                alive = icom.rigctld_alive(host, int(rport))
            if alive:
                c[1].success(i18n.tr("rigctld in ascolto su") + f" {host}:{int(rport)}")
            elif not exe:
                c[1].warning("rigctld-wsjtx.exe non trovato: è nella cartella bin di WSJT-X.")
            else:
                c[1].info(i18n.tr("rigctld non è avviato") + f" · {exe}")
            if S.get("rad_rig_msg") and not alive:
                (st.success if S["rad_rig_msg"][0] else st.error)(S["rad_rig_msg"][1])
            st.code(icom.rigctld_command(exe.rsplit("\\", 1)[0] if exe and "\\" in exe else r"C:\WSJT\wsjtx\bin",
                                         port, int(baud), int(rport)))
            st.caption("Poi in WSJT-X › Settings › Radio scegli «Hamlib NET rigctl», server 127.0.0.1:4532. "
                       "Questo lo fai tu: EMELab non cambia le impostazioni di WSJT-X.")
        else:
            new = {}
            st.caption("Frequenza, modo e TX/RX arrivano dai messaggi UDP di WSJT-X: nessun conflitto, ma le altre "
                       "impostazioni della radio non si vedono.")
        new["radio_source"] = src
        if any(sets.get(k) != v for k, v in new.items()):
            openems_local.save_settings(**new)
            sets.update(new)


def _transverters(sets):
    """Transverters with the IF on the radio (e.g. 10368 − 144 MHz): the radio shows 144, EMELab shows 10368."""
    trvs = sets.get("radio_trvs") or icom.DEFAULT_TRANSVERTERS
    with st.expander("🔁 Transverter (offset IF → RF)"):
        st.caption("Per ogni transverter la frequenza RF e la IF sull'IC-9700: EMELab somma l'offset (RF − IF) alla "
                   "frequenza letta dalla radio quando questa è nella banda IF (IF … IF + 2 MHz). Con il firmware "
                   "SQ6EMM, che passa già la RF via CI-V, l'offset non viene applicato.")
        import pandas as pd
        models = [""] + [icom.catalog_label(c) for c in icom.TRANSVERTER_CATALOG]
        df = pd.DataFrame([{"on": bool(x.get("on", True)), "name": x["name"], "model": x.get("model") or "",
                            "rf_mhz": float(x["rf_mhz"]), "if_mhz": float(x["if_mhz"])} for x in trvs])
        df["lo_mhz"] = df["rf_mhz"] - df["if_mhz"]
        ed = st.data_editor(df, key="rad_trv_ed", num_rows="dynamic", hide_index=True, column_config={
            "on": _st.column_config.CheckboxColumn(i18n.tr("Attivo"), width="small"),
            "name": _st.column_config.TextColumn(i18n.tr("Nome")),
            "model": _st.column_config.SelectboxColumn(i18n.tr("Modello"), options=models),
            "rf_mhz": _st.column_config.NumberColumn("RF MHz", format="%.3f"),
            "if_mhz": _st.column_config.NumberColumn("IF MHz", format="%.3f"),
            "lo_mhz": _st.column_config.NumberColumn(i18n.tr("Offset MHz"), format="%.3f", disabled=True)})
        new = [{"on": bool(r["on"]), "name": str(r["name"]).strip(), "model": str(r.get("model") or ""),
                "rf_mhz": float(r["rf_mhz"]),
                "if_mhz": float(r["if_mhz"])} for r in ed.to_dict("records")
               if str(r.get("name") or "").strip() and r.get("rf_mhz") == r.get("rf_mhz") and r.get("if_mhz") == r.get("if_mhz")]
        names = ["auto", "OFF"] + [x["name"] for x in new]
        lab = {"auto": i18n.tr("auto (banda da WSJT-X)"), "OFF": i18n.tr("nessuno (mostra la IF)")}
        c = st.columns(2)
        cur_m, cur_s = sets.get("radio_trv_main", "auto"), sets.get("radio_trv_sub", "auto")
        m = c[0].selectbox("Transverter su MAIN", names, index=names.index(cur_m) if cur_m in names else 0,
                           format_func=lambda k: lab.get(k, k), key="rad_trv_main")
        s_ = c[1].selectbox("Transverter su SUB", names, index=names.index(cur_s) if cur_s in names else 0,
                            format_func=lambda k: lab.get(k, k), key="rad_trv_sub")
        _catalog_table()
        st.caption("«auto» sceglie il transverter dalla frequenza di WSJT-X (se WSJT-X ha il suo offset transverter); "
                   "con più transverter sulla stessa IF e WSJT-X spento serve sceglierlo qui.")
        if new != trvs or m != cur_m or s_ != cur_s:
            openems_local.save_settings(radio_trvs=new, radio_trv_main=m, radio_trv_sub=s_)
            sets.update(radio_trvs=new, radio_trv_main=m, radio_trv_sub=s_)
            S.pop("rad_state", None)


def _catalog_table():
    """Transverters on the market: the Kuhne values come from the maker's pages, the others are assumed (orange)."""
    st.markdown("**" + i18n.tr("Transverter in commercio") + "**")
    head = ["Modello", "Banda", "RF", "IF", "LO", "Pout", "NF", "Pilotaggio IF", "Uscita RF"]
    h = ('<table style="width:100%;border-collapse:collapse;font-size:13px"><tr>'
         + "".join(f'<th style="text-align:left;padding:2px 6px;border-bottom:1px solid #ccc">{html.escape(i18n.tr(x))}</th>'
                   for x in head) + "</tr>")
    for c in icom.TRANSVERTER_CATALOG:
        col = "" if c.get("verified") else f"color:{ASSUMED};"
        name = html.escape(icom.catalog_label(c))
        if c.get("url"):
            name = f'<a href="{html.escape(c["url"])}" target="_blank">{name}</a>'
        name += " ✅" if c.get("verified") else ""
        cells = [name, c["band"], c["rf_range"], c["if_range"], i18n.tr(c.get("lo") or "—"),
                 "—" if c.get("pout_w") is None else f"{c['pout_w'] * 1000:.0f} mW" if c["pout_w"] < 1 else f"{c['pout_w']:g} W",
                 "—" if c.get("nf_db") is None else f"{c['nf_db']:g} dB", c.get("drive") or "—",
                 i18n.tr(c.get("rf_conn") or "—")]
        h += "<tr>" + "".join(f'<td style="padding:1px 6px;{col}">{x if i == 0 else html.escape(str(x))}</td>'
                              for i, x in enumerate(cells)) + "</tr>"
    h += "</table>"
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
    st.caption("✅ dati dalla pagina del costruttore; in arancione i modelli con i soli valori presunti (banda e IF usuali).")


def _read(sets):
    """At most one reading per REFRESH_S, shared by the display and the table in the same run."""
    last = S.get("rad_state")
    if last and time.time() - last.get("read_utc", 0) < REFRESH_S - 0.2:
        return last
    w = _wsjtx_status()
    st_ = icom.read(sets, w)
    S["rad_state"] = icom.apply_transverters(st_, sets.get("radio_trvs") or icom.DEFAULT_TRANSVERTERS,
                                             sets.get("radio_trv_main", "auto"), sets.get("radio_trv_sub", "auto"),
                                             (w or {}).get("dial_hz"))
    return S["rad_state"]


def _commands(sets, state):
    with st.expander("🎛️ Comandi verso la radio"):
        st.caption("Spento di default: EMELab manda qualcosa alla radio solo con questo interruttore acceso e "
                   "solo quando premi un pulsante «Invia». L'interruttore si spegne alla chiusura di EMELab.")
        on = st.toggle("Comandi verso la radio attivi", key="rad_cmd_on")
        disabled = not on or sets.get("radio_source", "wsjtx") == "wsjtx"
        if on and disabled:
            st.warning("Con la sola lettura da WSJT-X non si possono inviare comandi: scegli rigctld o CI-V diretto.")
        if on and state.get("tx"):
            st.warning("La radio è in trasmissione.")
        sel = state.get("sel") or {}
        c = st.columns([3, 1, 2, 1, 3, 1])
        f = c[0].number_input("Frequenza (Hz)", 0, 200_000_000_000, int(sel.get("freq_hz") or 0), 10, key="rad_set_f",
                              disabled=disabled)
        if c[1].button("Invia", key="rad_go_f", disabled=disabled,
                       help="una frequenza RF del transverter viene inviata alla radio come IF"):
            _send(sets, "freq_hz", icom.rf_to_if(int(f), sets.get("radio_trvs") or icom.DEFAULT_TRANSVERTERS))
        modes = ["USB", "LSB", "CW", "CW-R", "FM", "AM", "RTTY"]
        m = c[2].selectbox("Modo", modes, index=modes.index(sel["mode"]) if sel.get("mode") in modes else 0,
                           key="rad_set_m", disabled=disabled)
        if c[3].button("Invia", key="rad_go_m", disabled=disabled):
            _send(sets, "mode", m)
        p = c[4].slider("Potenza RF %", 0, 100, int(state.get("power_pct") or 0), key="rad_set_p", disabled=disabled)
        if c[5].button("Invia", key="rad_go_p", disabled=disabled):
            _send(sets, "power_pct", p)
        c = st.columns(8)
        for i, (key, label) in enumerate((("preamp", "P.AMP"), ("att", "ATT"), ("nb", "NB"), ("nr", "NR"),
                                          ("anf", "AN"), ("comp", "COMP"), ("vox", "VOX"), ("dualwatch", "DUAL"))):
            cur = state.get(key)
            cur = cur not in (None, "OFF", False)
            if c[i].button(f"{label} → {'OFF' if cur else 'ON'}", key=f"rad_tg_{key}", disabled=disabled):
                _send(sets, key, not cur)
        c = st.columns(4)
        agc = c[0].selectbox("AGC", ["FAST", "MID", "SLOW"], key="rad_set_agc", disabled=disabled)
        if c[1].button("Invia", key="rad_go_agc", disabled=disabled):
            _send(sets, "agc", agc)
        if S.get("rad_msg"):
            (st.success if S["rad_msg"][0] else st.error)(S["rad_msg"][1])


def _send(sets, key, value):
    ok, msg = icom.write(sets, key, value)
    S["rad_msg"] = (ok, f"{key} = {value}: {i18n.tr(msg)}")
    S.pop("rad_state", None)            # read again at once


def tab(D=None):
    sets = openems_local.load_settings()
    st.subheader("📟 Radio · Icom IC-9700")
    _connection(sets)
    _transverters(sets)
    live = st.toggle("Aggiornamento automatico", value=True, key="rad_live",
                     help=f"legge la radio ogni {REFRESH_S} secondi")

    @_frag(REFRESH_S if live else None)
    def _panel():
        state = _read(openems_local.load_settings())
        left, right = st.columns([5, 3])
        with left:
            h = render_display(state)
            st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
            if state.get("error"):
                st.warning(i18n.tr("Lettura dalla radio non riuscita") + f": {i18n.tr(state['error'])}. "
                           + i18n.tr("Mostro quello che dice WSJT-X."))
            elif not state.get("sel"):
                st.info("Nessun dato: WSJT-X non trasmette lo stato e il CAT non è configurato.")
            st.caption(i18n.tr("In alto le funzioni della radio: riquadro chiaro = ON, grigio scuro = OFF o non letto. "
                               "Nella tabella «n.d.» = non disponibile: la radio (o rigctld) non dà quel valore."))
            st.caption(i18n.tr("In arancione i valori presunti (modo da WSJT-X, scala di Id).")
                       + " " + i18n.tr("Con il firmware SQ6EMM la radio mostra e passa via CI-V la frequenza RF del transverter."))
        with right:
            rows = settings_rows(state)
            h = '<table style="width:100%;border-collapse:collapse;font-size:13px;line-height:1.25">'
            last = None
            for g, n, v in rows:
                if g != last:
                    h += (f'<tr><td colspan="2" style="padding:4px 4px 1px;font-weight:700;border-bottom:1px solid '
                          f'#ccc">{html.escape(i18n.tr(g))}</td></tr>')
                    last = g
                col = f"color:{ASSUMED};" if n == "Vd / Id" else ""
                h += (f'<tr><td style="padding:0 4px;color:#555">{html.escape(i18n.tr(n))}</td>'
                      f'<td style="padding:0 4px;text-align:right;{col}">{html.escape(str(v))}</td></tr>')
            h += "</table>"
            st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
        return state

    state = _panel() or S.get("rad_state") or {}
    _commands(sets, state)
