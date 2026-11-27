# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📻 Radio tab: the Icom IC-9700 on USB (CI-V), its display redrawn as on the radio (MAIN and SUB readouts, status
icons, S/Po meter, multi-function meter) and every setting read from the radio. Read-only by default: the commands
send something to the radio only when «Comandi verso la radio» is switched on and a button is pressed."""
from __future__ import annotations

import html
import re
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


def _icons(state) -> list[str]:
    """The function icons the radio shows on its top line: only the ones that are on (unknown = not shown)."""
    on = [("P.AMP", state.get("preamp") is True), ("ATT", state.get("att") not in (None, "OFF")),
          ("NB", state.get("nb") is True), ("NR", state.get("nr") is True), ("AN", state.get("anf") is True),
          ("NOTCH", state.get("mnf") is True), ("COMP", state.get("comp") is True), ("VOX", state.get("vox") is True),
          ("BK-IN", state.get("bkin") not in (None, "OFF")), ("MONI", state.get("monitor") is True),
          ("DUAL", state.get("dualwatch") is True), ("SAT", state.get("satmode") is True),
          ("SPLIT", state.get("split") == "SPLIT"),
          (f"RIT {state.get('rit_hz', 0):+d}", state.get("rit_on") is True), ("LOCK", state.get("lock") is True)]
    return [k for k, v in on if v]


_CSS = """
<style>
.ic97box{container-type:inline-size;width:100%}
.ic97{background:#000;border:14px solid #1b1c1e;border-radius:10px;color:#fff;overflow:hidden;
 font-family:"Arial Narrow","Roboto Condensed","Liberation Sans Narrow",Arial,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.35)}
.ic97 .top{display:flex;align-items:center;gap:8px;height:34px;padding:4px 10px 0}
.ic97 .tx{background:#d01818;color:#fff;font-weight:700;font-size:20px;padding:0 8px;border:2px solid #ff6b6b}
.ic97 .tx.off{visibility:hidden}
.ic97 .fn{font-size:15px;color:#fff;border:1px solid #9aa4b0;padding:0 5px;border-radius:2px}
.ic97 .clk{margin-left:auto;font-size:24px}
.ic97 .pbt{font-size:15px;color:#000;background:#c9ced4;padding:0 6px;border-radius:2px}
.ic97 .vfo{display:grid;grid-template-columns:260px 1fr 130px;align-items:end;padding:2px 10px 6px}
.ic97 .boxes{display:flex;gap:8px}
.ic97 .mode{background:linear-gradient(#3d7fd6,#1d55a8);border:1px solid #8bb8f0;font-size:26px;padding:4px 0;width:130px;
 text-align:center;border-radius:2px}
.ic97 .fil{background:#22262b;border:1px solid #9aa4b0;font-size:26px;padding:4px 0;width:110px;text-align:center;border-radius:2px}
.ic97 .meter{margin-top:6px;font-size:12px;color:#c9ced4}
.ic97 .meter .sc{display:flex;justify-content:space-between;width:250px;color:#e0e0e0}
.ic97 .meter .sc b{color:#ff4d4d;font-weight:400}
.ic97 .meter .bar{position:relative;height:6px;width:250px;background:#20242a;margin-top:2px}
.ic97 .meter .bar i{position:absolute;left:0;top:0;bottom:0;background:#fff}
.ic97 .meter .lab{font-size:12px;color:#c9ced4;margin-top:1px}
.ic97 .fq{text-align:right;line-height:1}
.ic97 .agc{font-size:16px;color:#e8e8e8;text-align:right;padding-right:6px}
.ic97 .big{font-size:78px;font-weight:700;letter-spacing:1px;font-variant-numeric:tabular-nums}
.ic97 .big small{font-size:50px}
.ic97 .st{display:flex;justify-content:flex-end;gap:6px;margin-top:4px}
.ic97 .ch{font-size:14px;padding:1px 6px;border:1px solid #59626d;color:#9aa4b0;border-radius:2px}
.ic97 .ch.on{background:#e8eef4;color:#000;border-color:#e8eef4;font-weight:700}
.ic97 .ch.on2{color:#fff;border-color:#9aa4b0}
.ic97 .ch.nd{opacity:.5}
.ic97 .txf{text-align:right;font-size:15px;color:#ffb3b3;margin-top:3px;font-variant-numeric:tabular-nums}
.ic97 .side{text-align:right;font-size:18px;line-height:1.25;padding-bottom:10px}
.ic97 .side .ifq{font-size:13px;white-space:nowrap;color:#c9ced4}
.ic97 .side .band{color:#7fd3ff}
.ic97 .sh{display:flex;align-items:center;gap:8px;background:#1e2430;height:26px;padding:0 8px;font-size:15px}
.ic97 .sh .main{background:#c3171b;padding:0 6px;font-weight:700}
.ic97 .sh .ttl{margin:0 auto;letter-spacing:1px}
.ic97 .sh .ctr{background:#2a64c8;padding:0 6px}
.ic97 .sh .grid{color:#e0e0e0}
.ic97 .edge{display:flex;justify-content:space-between;font-size:13px;color:#e0e0e0;padding:2px 8px 0}
.ic97 .spec{display:block;width:100%;height:110px;background:#000}
.ic97 .wf{display:block;width:100%;height:110px;image-rendering:pixelated;background:#000038}
.ic97 .ax{display:flex;justify-content:space-around;font-size:13px;color:#e0e0e0;padding:2px 0}
.ic97 .keys{display:grid;grid-template-columns:repeat(6,1fr);gap:4px;padding:4px 6px 6px}
.ic97 .keys span{background:linear-gradient(#3a3f46,#22262b);border:1px solid #6b737d;text-align:center;font-size:16px;
 padding:3px 0;border-radius:2px;white-space:nowrap}
.ic97 .keys b{font-weight:400;color:#c9ced4;margin-right:4px}
.ic97 .noscope{display:flex;align-items:center;justify-content:center;height:240px;color:#8a929c;font-size:16px;
 background:#04070d;text-align:center;padding:0 30px}
.ic97-name{text-align:center;font:600 12px Arial,sans-serif;letter-spacing:3px;color:#888;margin-top:4px}
</style>"""


def _css():
    return re.sub(r"(?<![\d.])(\d+(?:\.\d+)?)px", lambda m: m.group(0) if m.group(1) in ("1", "2")
                  else f"{float(m.group(1)) / 9.6:.2f}cqw", _CSS)


def render_display(state: dict, now: datetime | None = None, scope: dict | None = None) -> str:
    """HTML of the IC-9700 screen as on the radio: MAIN only (TX, function icons, clock; mode and filter, AGC,
    S/SWR meter, frequency to the Hz, VFO; spectrum scope and waterfall; soft keys with the levels)."""
    from emelab import radio_scope
    now = now or datetime.now(timezone.utc)
    sel, uns = state.get("sel") or {}, state.get("unsel") or {}
    v = sel if (state.get("main_sub") or "MAIN") == "MAIN" else uns
    tx = bool(state.get("tx"))
    wsjtx_only = state.get("source") == "wsjtx"
    f1, f2 = fmt_freq(v.get("freq_hz"))
    mode = icom.mode_label(v.get("mode"), v.get("data"))
    mode_st = f' style="color:{ASSUMED}"' if wsjtx_only else ""
    fil = v.get("filter") or ("FIL" if not v.get("width_hz") else f"{v['width_hz'] / 1000:g}k")
    icons = "".join(f'<span class="fn">{html.escape(k)}</span>' for k in _icons(state))
    if tx:
        frac = (state.get("po_pct") or 0) / 120
        scale_ = '<span>0</span><span>25</span><span>50</span><span>100</span><b>%</b>'
        lab = "Po/SWR " + (f"{state['swr']:g}" if state.get("swr") is not None else "")
    else:
        frac = _s_frac(state)
        scale_ = ('<span>1</span><span>3</span><span>5</span><span>7</span><span>9</span>'
                  '<b>+20</b><b>+40</b><b>+60dB</b>')
        lab = "S/SWR " + (state.get("s_meter") or "")
    agc = ("AGC-" + state["agc"][0]) if state.get("agc") else ""
    ifq = ""
    if v.get("if_hz"):
        i1, i2 = fmt_freq(v["if_hz"])
        ifq = f'<div class="ifq">IF {i1}{i2}</div>'
    def chip(k, val):
        cls = "nd" if val is None else ("on" if val else "")
        return f'<span class="ch {cls}">{k} {"n.d." if val is None else ("ON" if val else "OFF")}</span>'
    split = None if state.get("split") is None else state.get("split") == "SPLIT"
    status = (chip("NB", state.get("nb")) + chip("NR", state.get("nr")) + chip("SPLIT", split)
              + f'<span class="ch on2">{html.escape(fil)}</span>')
    tx_hz = (uns if v is sel else sel).get("freq_hz") if split else v.get("freq_hz")
    txline = ""
    if tx_hz:
        t1, t2 = fmt_freq(tx_hz)
        txline = f"TX {t1}{t2}"
        if state.get("doppler_hz") is not None:
            txline += f" · Doppler {state['doppler_hz']:+,.0f} Hz".replace(",", ".")
    head = (f'<div class="top"><span class="tx {"" if tx else "off"}">TX</span>{icons}'
            f'<span class="clk">{now:%H:%M}</span><span class="pbt">UTC</span></div>'
            f'<div class="vfo"><div><div class="boxes"><span class="mode"{mode_st}>{html.escape(mode)}</span>'
            f'<span class="fil">{html.escape(fil)}</span></div>'
            f'<div class="meter"><div class="sc">{scale_}</div><div class="bar"><i style="width:{max(0, min(1, frac)) * 100:.0f}%"></i></div>'
            f'<div class="lab">{html.escape(lab)}</div></div></div>'
            f'<div class="fq"><div class="agc">{agc}</div><div class="big">{f1}<small>{f2}</small></div>'
            f'<div class="st">{status}</div><div class="txf">{txline}</div></div>'
            f'<div class="side">VFO A'
            f'<div class="band">{_band(v.get("freq_hz"))}</div>{ifq}</div></div>')
    sc = scope or {}
    rows = sc.get("rows") or []
    if rows:
        lo, hi = radio_scope.scale(rows)
        dial = v.get("freq_hz")
        ax = "".join(f"<span>{(dial + k) / 1e6:.4f}</span>" if dial else f"<span>+{k}</span>"
                     for k in (250, 750, 1250, 1750, 2250, 2750))
        edge_l = fmt_freq(dial)[0] if dial else "0"
        edge_r = fmt_freq(dial + 3000)[0] + fmt_freq(dial + 3000)[1] if dial else "+3 kHz"
        scope_html = (f'<div class="sh"><span class="main">MAIN</span><span class="ttl">SPECTRUM SCOPE</span>'
                      f'<span class="ctr">{html.escape(sc.get("label") or "AUDIO")}</span>'
                      f'<span class="grid">Grid 500Hz/10dB</span></div>'
                      f'<div class="edge"><span>{edge_l}{fmt_freq(dial)[1] if dial else ""}</span><span>{edge_r}</span></div>'
                      f'<img class="spec" src="data:image/png;base64,{radio_scope.spectrum_png(sc.get("spec"), lo, hi)}"/>'
                      f'<img class="wf" src="data:image/png;base64,{radio_scope.waterfall_png(rows, lo, hi)}"/>'
                      f'<div class="ax">{ax}</div>')
    else:
        msg = sc.get("error") or i18n.tr("Spectrum scope spento: accendilo sopra il display.")
        scope_html = (f'<div class="sh"><span class="main">MAIN</span><span class="ttl">SPECTRUM SCOPE</span>'
                      f'<span class="ctr">AUDIO</span></div><div class="noscope">{html.escape(i18n.tr(msg))}</div>')

    def key(k, val, unit="%"):
        return f'<span><b>{k}</b>{"n.d." if val is None else str(val) + unit}</span>'
    keys = ('<div class="keys">' + key("AF", state.get("af_pct")) + key("RF", state.get("rf_pct"))
            + key("SQL", state.get("sql_pct")) + key("PWR", state.get("power_pct")) + key("MIC", state.get("mic_pct"))
            + f'<span><b>CAT</b>{html.escape({"serial": "CI-V", "rigctld": "rigctld", "wsjtx": "WSJT-X"}.get(state.get("source"), "—"))}</span>'
            + '</div>')
    return (_css() + '<div class="ic97box"><div class="ic97">' + head + scope_html + keys
            + '</div><div class="ic97-name">IC-9700 · EMELab</div></div>')


# ------------------------------------------------------------------ control panel around the display (original design)
_PANEL_CSS = """
<style>
.rp{display:grid;grid-template-columns:200px 1fr 300px;gap:14px;padding:14px;border-radius:16px;
 background:linear-gradient(160deg,#2b2f35 0%,#17191d 55%,#0f1114 100%);box-shadow:0 10px 30px rgba(0,0,0,.35),
 inset 0 1px 0 rgba(255,255,255,.08);font-family:"Roboto Condensed","Arial Narrow",Arial,sans-serif;color:#dfe5ec}
.rp h4{margin:0 0 6px;font-size:11px;letter-spacing:2px;color:#8d98a5;font-weight:600;text-transform:uppercase}
.rp .card{background:linear-gradient(#202328,#181a1e);border:1px solid #2e333a;border-radius:10px;padding:10px;margin-bottom:12px;
 box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}
.rp .knobs{display:flex;flex-direction:column;gap:9px}
.rp .sl{display:grid;grid-template-columns:1fr auto;font-size:11px;color:#9aa6b2;row-gap:4px}
.rp .sl b{color:#fff;font-weight:600;font-size:12px}
.rp .sl .trk{grid-column:1/3;position:relative;height:6px;border-radius:3px;background:#0d0f12;box-shadow:inset 0 1px 2px #000}
.rp .sl .trk i{position:absolute;left:0;top:0;bottom:0;border-radius:3px;opacity:.85}
.rp .sl .trk u{position:absolute;top:-5px;width:22px;height:16px;margin-left:-11px;border-radius:4px;
 background:linear-gradient(#e7ebef,#9aa3ad);box-shadow:0 1px 3px rgba(0,0,0,.7);text-decoration:none}
.rp .sl.nd{opacity:.5}
.rp .knob{display:flex;flex-direction:column;align-items:center;gap:4px;font-size:11px;color:#9aa6b2}
.rp .dial{width:64px;height:64px;border-radius:50%;position:relative;
 background:conic-gradient(from 225deg,var(--c) calc(var(--v)*0.75turn),#2b3038 0 0.75turn,transparent 0);}
.rp .dial::before{content:"";position:absolute;inset:6px;border-radius:50%;
 background:radial-gradient(circle at 35% 30%,#4a5059,#1b1e22 70%);box-shadow:0 2px 6px rgba(0,0,0,.6)}
.rp .dial::after{content:"";position:absolute;left:50%;top:50%;width:3px;height:22px;margin-left:-1.5px;background:#e9eef3;
 border-radius:2px;transform-origin:50% 0;transform:rotate(calc(var(--v)*270deg + 45deg)) ;box-shadow:0 0 4px rgba(255,255,255,.4)}
.rp .dial.nd{background:conic-gradient(from 225deg,#2b3038 0.75turn,transparent 0)}
.rp .dial.nd::after{display:none}
.rp .knob b{font-size:15px;color:#fff;font-weight:600}
.rp .keys{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.rp .bands{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
.rp .bands span{text-align:center;padding:7px 0;border-radius:6px;font-size:13px;background:linear-gradient(#3a3f47,#25292f);
 border:1px solid #4a515a;color:#c4ccd5;box-shadow:0 2px 0 #0b0c0e}
.rp .bands span.on{background:linear-gradient(#3d7fd6,#1d55a8);border-color:#8bb8f0;color:#fff;box-shadow:0 0 10px rgba(61,127,214,.5)}
.rp .key{display:flex;align-items:center;gap:6px;background:linear-gradient(#3a3f47,#25292f);border:1px solid #4a515a;
 border-radius:6px;padding:5px 7px;font-size:12px;color:#e6ebf0;box-shadow:0 2px 0 #0b0c0e}
.rp .led{width:4px;height:14px;border-radius:2px;background:#2a2f35;box-shadow:inset 0 1px 2px #000}
.rp .key.on .led{background:#38c6ff;box-shadow:0 0 6px #38c6ff}
.rp .key.nd{opacity:.45}
.rp .center{min-width:0}
.rp .modes{display:flex;gap:6px;margin-top:10px}
.rp .modes span{flex:1;text-align:center;padding:6px 0;border-radius:6px;font-size:13px;background:linear-gradient(#34383f,#202328);
 border:1px solid #454c55;color:#c4ccd5}
.rp .modes span.on{background:linear-gradient(#3d7fd6,#1d55a8);border-color:#8bb8f0;color:#fff;box-shadow:0 0 10px rgba(61,127,214,.5)}
.rp .txrx{display:flex;gap:8px;margin-bottom:12px}
.rp .txrx span{flex:1;text-align:center;font-weight:700;font-size:18px;padding:8px 0;border-radius:8px;letter-spacing:2px;
 background:#202328;border:1px solid #2e333a;color:#4b535c}
.rp .txrx .rx.on{background:linear-gradient(#1f6b37,#124222);color:#d9ffe5;border-color:#3cff7a;box-shadow:0 0 12px rgba(60,255,122,.35)}
.rp .txrx .tx.on{background:linear-gradient(#a3171b,#5e0b0d);color:#fff;border-color:#ff6b6b;box-shadow:0 0 14px rgba(255,80,80,.5)}
.rp .m{display:grid;grid-template-columns:44px 1fr 64px;align-items:center;gap:6px;font-size:12px;margin:5px 0}
.rp .m .tr{height:9px;border-radius:5px;background:#2a2f36;overflow:hidden}
.rp .m .tr i{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#38c6ff,#3cff7a 60%,#ffd23c 80%,#ff4d4d)}
.rp .m em{font-style:normal;text-align:right;color:#fff}
.rp .m em.as{color:#ff9a4d}
.rp .kv{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:12px}
.rp .kv span{color:#8d98a5}.rp .kv b{color:#fff;font-weight:500;text-align:right}
.rp .src{display:flex;align-items:center;gap:8px;font-size:12px}
.rp .src .dot{width:10px;height:10px;border-radius:50%;background:#3cff7a;box-shadow:0 0 8px #3cff7a}
.rp .src .dot.warn{background:#ffb000;box-shadow:0 0 8px #ffb000}
</style>"""


def _knob(label, val, color="#38c6ff"):
    """A horizontal slider with its value (n.d. when the radio did not give it)."""
    if val is None:
        return (f'<div class="sl nd"><span>{html.escape(label)}</span><b>n.d.</b>'
                f'<div class="trk"></div></div>')
    v = max(0.0, min(1.0, float(val) / 100))
    return (f'<div class="sl"><span>{html.escape(label)}</span><b>{int(round(float(val)))}%</b>'
            f'<div class="trk"><i style="width:{v * 100:.0f}%;background:{color}"></i>'
            f'<u style="left:{v * 100:.0f}%"></u></div></div>')


def _key(label, val):
    cls = "nd" if val is None else ("on" if val else "")
    return f'<span class="key {cls}"><span class="led"></span>{html.escape(label)}</span>'


def _meter(name, val, frac, unit="", assumed=False):
    shown = "n.d." if val is None else f"{val}{unit}"
    w = 0 if val is None else max(0.0, min(1.0, frac)) * 100
    return (f'<div class="m"><span>{name}</span><span class="tr"><i style="width:{w:.0f}%"></i></span>'
            f'<em class="{"as" if assumed and val is not None else ""}">{shown}</em></div>')


def render_panel(state: dict, scope: dict | None = None, now: datetime | None = None) -> str:
    """The whole Radio panel: knobs and function keys on the left, the IC-9700 screen in the middle, TX/RX, meters,
    transverter and connection on the right. Drawn by EMELab; values the radio did not give show «n.d.»."""
    sel, uns = state.get("sel") or {}, state.get("unsel") or {}
    v = sel if (state.get("main_sub") or "MAIN") == "MAIN" else uns
    att = state.get("att")
    keys = "".join([
        _key("P.AMP", state.get("preamp")), _key("ATT", None if att is None else att != "OFF"),
        _key("NB", state.get("nb")), _key("NR", state.get("nr")), _key("AN", state.get("anf")),
        _key("NOTCH", state.get("mnf")), _key("COMP", state.get("comp")), _key("VOX", state.get("vox")),
        _key("DUAL", state.get("dualwatch")), _key("SAT", state.get("satmode")),
        _key("SPLIT", None if state.get("split") is None else state.get("split") == "SPLIT"),
        _key("LOCK", state.get("lock"))])
    left = ('<div><div class="card"><h4>' + html.escape(i18n.tr("Livelli")) + '</h4><div class="knobs">'
            + _knob("AF", state.get("af_pct")) + _knob("RF", state.get("rf_pct"), "#3cff7a")
            + _knob("SQL", state.get("sql_pct"), "#ffd23c") + _knob("RF PWR", state.get("power_pct"), "#ff6b6b")
            + '</div></div><div class="card"><h4>' + html.escape(i18n.tr("Funzioni")) + '</h4><div class="keys">'
            + keys + '</div></div></div>')
    mode = v.get("mode")
    modes = "".join(f'<span class="{"on" if mode == m else ""}">{m}</span>' for m in ("USB", "LSB", "CW", "FM", "AM", "DV"))
    center = ('<div class="center">' + render_display(state, now=now, scope=scope)
              + f'<div class="modes">{modes}</div></div>')
    tx = bool(state.get("tx"))
    swr_v = state.get("swr")
    meters = (_meter("S", state.get("s_meter"), _s_frac(state)) + _meter("Po", state.get("po_pct"), (state.get("po_pct") or 0) / 100, "%")
              + _meter("SWR", swr_v, ((swr_v or 1) - 1) / 2) + _meter("ALC", state.get("alc_pct"), (state.get("alc_pct") or 0) / 100, "%")
              + _meter("Vd", state.get("vd_v"), (state.get("vd_v") or 0) / 16, " V")
              + _meter("Id", state.get("id_a"), (state.get("id_a") or 0) / 20, " A", assumed=True))
    trv = ""
    if v.get("if_hz"):
        f1, f2 = fmt_freq(v["if_hz"])
        trv = (f'<div class="card"><h4>Transverter</h4><div class="kv"><span>{html.escape(i18n.tr("Modello"))}</span>'
               f'<b>{html.escape(v.get("trv_model") or v.get("trv") or "")}</b><span>IF</span><b>{f1}{f2}</b>'
               f'<span>LO</span><b>{(v["freq_hz"] - v["if_hz"]) / 1e6:,.3f} MHz</b></div></div>').replace(",", ".")
    src = {"serial": "CI-V USB", "rigctld": "rigctld · Hamlib", "wsjtx": "WSJT-X (UDP)", "lan": "LAN · Ethernet"}.get(
        state.get("source"), "—")
    warn = bool(state.get("error"))
    from emelab import icom as _icom
    trvs = openems_local.load_settings().get("radio_trvs") or _icom.DEFAULT_TRANSVERTERS
    cur_band = _band(v.get("freq_hz"))
    bands = "".join(f'<span class="{"on" if x["name"] == cur_band or _band(x["rf_mhz"] * 1e6) == cur_band else ""}">'
                    f'{html.escape(x["name"])}</span>' for x in trvs if x.get("on", True))
    right = (f'<div><div class="txrx"><span class="rx {"" if tx else "on"}">RX</span><span class="tx {"on" if tx else ""}">TX</span></div>'
             f'<div class="card"><h4>Band</h4><div class="bands">{bands}</div></div>'
             f'<div class="card"><h4>Meter</h4>{meters}</div>{trv}'
             f'<div class="card"><h4>{html.escape(i18n.tr("Collegamento"))}</h4><div class="src"><span class="dot {"warn" if warn else ""}">'
             f'</span>{html.escape(src)}</div></div></div>')
    return _PANEL_CSS + f'<div class="rp">{left}{center}{right}</div>'


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


def _own_doppler(state, sets):
    """Own-echo Doppler (Hz) at the RF frequency shown, from the Moon position for this station; None if unknown."""
    try:
        from emelab import astro, db as edb
        me = edb.DB().station() or {}
        if not me.get("lat"):
            return None
        hz = (state.get("sel") or {}).get("freq_hz")
        if not hz:
            return None
        trvs = sets.get("radio_trvs") or icom.DEFAULT_TRANSVERTERS
        rf = icom.apply_transverters({"source": state.get("source"), "main_sub": "MAIN", "sel": {"freq_hz": hz}}, trvs,
                                     sets.get("radio_trv_main", "auto"), "OFF",
                                     ((_wsjtx_status() or {}).get("dial_hz")))["sel"]["freq_hz"]
        s = astro.sky(datetime.now(timezone.utc), me["lat"], me["lon"], me.get("height_m") or 0.0)
        return s.doppler_hz_per_ghz * rf / 1e9
    except Exception:
        return None


def _read(sets):
    """At most one reading per REFRESH_S, shared by the display and the table in the same run."""
    last = S.get("rad_state")
    if last and time.time() - last.get("read_utc", 0) < REFRESH_S - 0.2:
        return last
    w = _wsjtx_status()
    st_ = icom.read(sets, w)
    st_["doppler_hz"] = _own_doppler(st_, sets)
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


def _scope_frame():
    dev = S.get("rad_scope_dev")
    if not dev:
        return {"error": "Spectrum scope spento o scheda audio non trovata."} if S.get("rad_scope") else None
    from emelab import radio_scope
    try:
        return radio_scope.get(dev["index"], "Mono", dev.get("rate") or 48000).frame()
    except Exception as e:
        return {"error": str(e)}


def tab(D=None):
    sets = openems_local.load_settings()
    st.subheader("📟 Radio · Icom IC-9700")
    _connection(sets)
    _transverters(sets)
    c = st.columns([2, 2, 4])
    live = c[0].toggle("Aggiornamento automatico", value=True, key="rad_live",
                       help=f"legge la radio ogni {REFRESH_S} secondi")
    scope_on = c[1].toggle("Spectrum scope e waterfall", value=bool(sets.get("radio_scope", True)), key="rad_scope",
                           help="dall'audio di ricezione dell'IC-9700 (USB Audio CODEC), condiviso con WSJT-X")
    if scope_on != bool(sets.get("radio_scope", True)):
        openems_local.save_settings(radio_scope=scope_on)
    if scope_on:
        from emelab import q65lab
        devs = q65lab.input_devices()
        best = q65lab.pick_device(devs, q65lab.ini_audio().get("device"))
        if best:
            c[2].caption(i18n.tr("Audio dello scope") + f": {best['name']} · {best['api']}")
        else:
            c[2].caption("Scheda audio dell'IC-9700 non trovata (USB Audio CODEC).")
        S["rad_scope_dev"] = best
    else:
        from emelab import radio_scope
        radio_scope.stop()
        S["rad_scope_dev"] = None

    @_frag(REFRESH_S if live else None)
    def _panel():
        state = _read(openems_local.load_settings())
        h = render_panel(state, scope=_scope_frame())
        st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
        if state.get("error"):
            st.warning(i18n.tr("Lettura dalla radio non riuscita") + f": {i18n.tr(state['error'])}. "
                       + i18n.tr("Mostro quello che dice WSJT-X."))
        elif not state.get("sel"):
            st.info("Nessun dato: WSJT-X non trasmette lo stato e il CAT non è configurato.")
        st.caption(i18n.tr("In alto compaiono solo le funzioni accese (NB, NR, P.AMP…), come sulla radio. "
                           "Nella tabella «n.d.» = non disponibile: la radio (o rigctld) non dà quel valore. "
                           "Lo scope mostra la banda passante audio (0–3 kHz sopra la frequenza).")
                   + " " + i18n.tr("In arancione i valori presunti (modo da WSJT-X, scala di Id)."))
        with st.expander("📋 Tutte le impostazioni lette"):
            rows = settings_rows(state)
            h = '<table style="width:100%;border-collapse:collapse;font-size:13px;line-height:1.3">'
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
