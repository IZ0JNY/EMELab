# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🧪 Q65 Lab tab: the experimental decoder next to WSJT-X, laid out like WSJT-X (waterfall, sync curve, Band
Activity) with the EMELab look. EMELab only listens: WSJT-X is never changed from here."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

import streamlit as _st

from emelab import i18n, q65lab, stations, wsjtx_ini
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state
ASSUMED_COLOR = "#e8590c"
REFRESH_S = 2.0
PROFILES = {"auto": "Automatico (dallo spread previsto)", "wsjtx": "Metrica di WSJT-X, media lineare",
            "wide": "Spread largo (campana, smussatura 300%)"}


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


def _html(h: str):
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)


def _t(s: str) -> str:
    return html.escape(i18n.tr(s))


_CSS = """<style>
.qx-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:0 0 2px}
.qx-title{font-size:21px;font-weight:700;letter-spacing:.2px}
.qx-sub{font-size:12.5px;opacity:.7}
.qx-strip{display:flex;flex-wrap:wrap;gap:5px;font-size:12.5px;margin:4px 0 2px}
.qx-strip span{padding:2px 9px;border-radius:7px;background:rgba(127,127,127,.06);border:1px solid rgba(127,127,127,.32)}
.qx-strip b{margin-left:5px;font-family:ui-monospace,Consolas,monospace}.qx-strip i{opacity:.65;font-style:normal}
.qx-strip .ok{border-color:#2ea04399;background:rgba(46,160,67,.08)}
.qx-strip .warn{border-color:#d29922;background:rgba(210,153,34,.12)}
.qx-strip .bad{border-color:#f85149;background:rgba(248,81,73,.12)}
.qx-strip .lab{border-color:#7c3aed88;background:rgba(124,58,237,.08)}
.qx-strip .assumed b{color:#e8590c}
.qx-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:2px 0 8px}
.qx-card{border:1px solid rgba(127,127,127,.28);border-radius:10px;padding:6px 10px;background:rgba(127,127,127,.03)}
.qx-card i{display:block;font-style:normal;font-size:11px;opacity:.7}
.qx-card b{font-size:22px;font-family:ui-monospace,Consolas,monospace}
.qx-card.lab b{color:#7c3aed}.qx-card.only b{color:#1a7f37}
.qx-sec{font-weight:650;font-size:15px;margin:0 0 4px}
.qx-wrap{max-height:520px;overflow-y:auto;border:1px solid rgba(127,127,127,.25);border-radius:10px}
table.qx{width:100%;border-collapse:collapse;font-family:ui-monospace,Consolas,monospace;font-size:13px}
table.qx th{position:sticky;top:0;background:#f6f7f9;font-weight:600;font-size:11.5px;text-align:left;padding:4px 6px;
 border-bottom:1px solid rgba(127,127,127,.3);font-family:inherit}
table.qx td{padding:3px 6px;border-bottom:1px solid rgba(127,127,127,.12);white-space:nowrap}
table.qx td.n{text-align:right}
table.qx tr.per td{background:rgba(127,127,127,.08);font-size:11.5px;color:#555;padding:2px 6px;font-family:inherit}
table.qx tr.me td{background:#ffe3e3}
table.qx tr.cq td{background:#e6f6e9}
table.qx tr.only td:first-child{box-shadow:inset 4px 0 0 #1a7f37}
table.qx tr.miss td{opacity:.55}
.qx-tag{display:inline-block;font-size:10.5px;font-weight:700;padding:0 6px;border-radius:5px;margin-left:3px;
 border:1px solid transparent;font-family:system-ui,sans-serif}
.qx-tag.lab{background:#ede9fe;color:#5b21b6;border-color:#c4b5fd}
.qx-tag.ref{background:#e0f2fe;color:#075985;border-color:#7dd3fc}
.qx-tag.wsjtx{background:#f1f5f9;color:#334155;border-color:#cbd5e1}
.qx-tag.new{background:#dcfce7;color:#14532d;border-color:#86efac}
.qx-legend{font-size:11.5px;opacity:.75;margin-top:5px}
.qx-wf img{border-radius:8px}
</style>"""


# ------------------------------------------------------------------ engine and parameters
@_st.cache_resource
def engine() -> q65lab.Engine:
    return q65lab.Engine()


def _svc():
    try:
        from emelab import ui
        return ui._wsjtx_service()
    except Exception:
        return None


def _wsjtx_live(svc) -> bool:
    return bool(svc and svc.running and svc.last_seen
                and (datetime.now(timezone.utc) - svc.last_seen).total_seconds() < 90)


def _params_fn(eng: q65lab.Engine):
    def fn():
        from emelab import db as edb
        svc = _svc()
        status = svc.status if _wsjtx_live(svc) else {}
        if status:
            eng.note_status(status)
        sets = openems_local.load_settings()
        p = q65lab.params_from(status, wsjtx_ini.read(wsjtx_ini.find(sets.get("wsjtx_file") or None)),
                               edb.DB().station())
        if not status:                                     # WSJT-X silent: the values set in this tab
            man = sets.get("q65lab_manual", {})
            p.update({k: man[k] for k in ("submode", "rx_hz", "ftol", "tr") if man.get(k)})
            p["manual"] = True
        return p
    return fn


def _wsjtx_decodes(period: q65lab.Period) -> list[dict]:
    """What WSJT-X itself decoded in that period (UDP Decode messages), for the comparison."""
    svc = _svc()
    if not svc:
        return []
    t0, t1 = period.utc - timedelta(seconds=1), period.utc + timedelta(seconds=period.tr - 1)
    return [{"message": d["message"], "snr": d["snr"], "dt": d["dt"], "freq": float(d["df"]), "q": None, "nused": None}
            for d in list(svc.recent) if d.get("utc") and t0 <= d["utc"] <= t1]


# ------------------------------------------------------------------ page
def tab(D=None):
    _html(_CSS)
    eng = engine()
    eng.params_fn = _params_fn(eng)
    sets = openems_local.load_settings()
    eng.mode = sets.get("q65lab_profile", "auto") if sets.get("q65lab_profile") in PROFILES else "auto"
    _header(eng, sets)
    if not eng.exe:
        st.warning("Il decoder sperimentale (q65lab.exe) non è installato: arriva con l'installer di EMELab. Puoi "
                   "indicarne il percorso in ⚙️ Audio e decoder.")
    _frag(REFRESH_S)(_live)(eng)
    _saved_files(eng, sets)
    _settings(eng, sets)
    _about()


def _header(eng: q65lab.Engine, sets: dict):
    c = st.columns([4.6, 1.25, 1.1, 1.15, 2.2], vertical_alignment="center")
    c[0].markdown("<div class='qx-head'><span class='qx-title'>🧪 Q65 Lab</span><span class='qx-sub'>"
                  + _t("decoder sperimentale accanto a WSJT-X · stesso audio, due decodifiche, nessuna modifica a WSJT-X")
                  + "</span></div>", unsafe_allow_html=True)
    if eng.running:
        if c[1].button("⏹ Ferma ascolto", key="qx_stop", width="stretch"):
            eng.stop()
            openems_local.save_settings(q65lab_on=False)
            st.rerun()
    else:
        if c[1].button("▶️ Ascolta", key="qx_start", type="primary", width="stretch", disabled=not eng.exe,
                       help="prende l'audio dalla stessa scheda di WSJT-X (IC-9700 USB Audio CODEC) e decodifica ogni periodo"):
            _start(eng, sets)
    if c[2].button("🧹 Clear Avg", key="qx_clear", width="stretch", disabled=not eng.running,
                   help="azzera le medie dei due decoder (come «Clear Avg» di WSJT-X)"):
        eng.clear_avg()
        st.toast(i18n.tr("Medie azzerate"), icon="🧹")
    with c[3].popover("🌊 Waterfall", width="stretch"):
        _wf_controls(sets)
    prof = c[4].selectbox("Profilo Q65 Lab", list(PROFILES), format_func=lambda k: i18n.tr(PROFILES[k]),
                          index=list(PROFILES).index(eng.mode), key="qx_profile", label_visibility="collapsed",
                          help="Automatico: metrica di WSJT-X fino a 80 Hz di spread, campana e smussatura 2× fino a "
                               "200 Hz, 3× oltre. Sempre media lineare.")
    if prof != sets.get("q65lab_profile", "auto"):
        openems_local.save_settings(q65lab_profile=prof)
        eng.mode = prof
    if sets.get("q65lab_on") and not eng.running and eng.exe and not S.get("qx_autostart_tried"):
        S["qx_autostart_tried"] = True                  # it was listening when EMELab was closed: starts again
        _start(eng, sets, quiet=True)


PALETTE_NAMES = {"wsjtx": "Come WSJT-X", "blue": "Blu", "gray": "Grigio", "warm": "Caldo"}
WF_KEYS = ("auto", "start", "span", "navg", "gain", "zero", "palette", "flatten", "use_ref", "spectrum")


def _wf_saved(sets: dict) -> dict:
    """The waterfall choices: saved in EMELab, else those of the WSJT-X Wide Graph (read from WSJT-X.ini), automatic."""
    v = sets.get("q65lab_wf")
    if isinstance(v, dict) and v:
        return {"auto": True, **{k: v[k] for k in WF_KEYS if k in v}}
    return {"auto": True, **q65lab.ini_widegraph(wsjtx_ini.find(sets.get("wsjtx_file") or None))}


def _wf_controls(sets: dict):
    """The controls of the WSJT-X Wide Graph; in «Automatico» Q65 Lab chooses the view and the levels itself."""
    v = {**q65lab.WfView().__dict__, **_wf_saved(sets)}
    ref = q65lab.refspec_path(wsjtx_ini.find(sets.get("wsjtx_file") or None))
    new = {"auto": st.toggle("Automatico", value=bool(v["auto"]), key="qx_wf_auto",
                             help="zoom da Rx − F Tol alla larghezza del sottomodo + F Tol, livelli dal rumore, "
                                  "spettro di riferimento di WSJT-X se c'è")}
    c = st.columns(2)
    new["start"] = c[0].number_input("Inizio (Hz)", 0, 4500, int(v["start"]), 50, key="qx_wf_start", disabled=new["auto"])
    new["span"] = c[1].number_input("Larghezza (Hz)", 200, 5000, int(v["span"]), 100, key="qx_wf_span", disabled=new["auto"])
    new["navg"] = st.slider("N Avg (velocità)", 1, 20, int(v["navg"]), key="qx_wf_navg",
                            help="una riga ogni N × 0,2 s, come in WSJT-X: più alto = più lento e più pulito")
    c = st.columns(2)
    new["gain"] = c[0].slider("Guadagno", -50, 50, int(v["gain"]), key="qx_wf_gain")
    new["zero"] = c[1].slider("Zero", -50, 50, int(v["zero"]), key="qx_wf_zero")
    new["palette"] = st.selectbox("Palette", list(PALETTE_NAMES), format_func=lambda k: i18n.tr(PALETTE_NAMES[k]),
                                  index=list(PALETTE_NAMES).index(v["palette"]) if v["palette"] in PALETTE_NAMES else 0,
                                  key="qx_wf_palette")
    c = st.columns([1, 1.25, 1.1])
    new["flatten"] = c[0].checkbox("Flatten", value=bool(v["flatten"]), key="qx_wf_flatten", disabled=new["auto"])
    new["use_ref"] = c[1].checkbox("Ref Spec", value=bool(v["use_ref"]) and ref is not None, key="qx_wf_ref",
                                   disabled=new["auto"] or ref is None,
                                   help="refspec.dat di WSJT-X (Tools → Measure reference spectrum), letto senza modificarlo"
                                   if ref else "refspec.dat di WSJT-X non trovato")
    new["spectrum"] = c[2].checkbox("Spettro", value=bool(v["spectrum"]) or new["auto"], key="qx_wf_spec",
                                    disabled=new["auto"],
                                    help="spettro cumulativo del periodo sotto il waterfall")
    if st.button("↩️ Come la Wide Graph di WSJT-X", key="qx_wf_reset", width="stretch"):
        openems_local.save_settings(q65lab_wf={})
        for k in list(S.keys()):
            if str(k).startswith("qx_wf_"):
                del S[k]
        st.rerun()
    if any(new[k] != v.get(k) for k in new):
        openems_local.save_settings(q65lab_wf=new)


def _wf_view(eng: q65lab.Engine, sets: dict, p: dict) -> tuple[q65lab.WfView, bool]:
    """The view to draw now (adapted to the situation in «Automatico») and whether the reference spectrum is used."""
    v = _wf_saved(sets)
    base = q65lab.WfView(**{k: v[k] for k in WF_KEYS if k != "auto" and k in v})
    path = q65lab.refspec_path(wsjtx_ini.find(sets.get("wsjtx_file") or None))
    if path:
        stamp = (str(path), path.stat().st_mtime)
        if S.get("qx_ref_stamp") != stamp:
            eng.waterfall.ref = q65lab.read_refspec(path)
            S["qx_ref_stamp"] = stamp
    else:
        eng.waterfall.ref = None
    if v.get("auto", True):
        view = q65lab.auto_view(p, base)
        view.flatten = True
        view.use_ref = eng.waterfall.ref is not None
        view.spectrum = True
    else:
        view = base
    eng.waterfall.step = view.step()
    return view, bool(v.get("auto", True))


def _start(eng: q65lab.Engine, sets: dict, quiet: bool = False):
    devs = q65lab.input_devices()
    ini_a = q65lab.ini_audio(wsjtx_ini.find(sets.get("wsjtx_file") or None))
    want = sets.get("q65lab_device") or ini_a.get("device")
    dev = next((d for d in devs if d["name"] == want and d["api"] == sets.get("q65lab_api")), None) \
        or q65lab.pick_device(devs, want)
    if dev is None:
        if not quiet:
            st.error(i18n.tr("Scheda audio dell'IC-9700 non trovata (USB Audio CODEC). Collega la radio o scegli la "
                             "scheda in ⚙️ Audio e decoder."))
        return
    ch = sets.get("q65lab_channel") or ini_a.get("channel") or "Mono"
    try:
        eng.start(q65lab.Capture(dev["index"], ch, rate=48000 if dev["rate"] >= 44100 else dev["rate"]))
        openems_local.save_settings(q65lab_on=True)
        S["qx_dev_label"] = f"{dev['name']} · {dev['api']}"
        st.rerun()
    except Exception as e:
        if not quiet:
            st.error(i18n.tr("Non riesco ad aprire la scheda audio") + f": {e}")


def _strip(items) -> str:
    cells = "".join(f"<span class='{state}'><i>{_t(lbl)}</i><b>{html.escape(i18n.tr(str(val)))}</b></span>" for lbl, val, state in items)
    return f"<div class='qx-strip'>{cells}</div>"


def _live(eng: q65lab.Engine):
    p = eng.current_params()
    k = eng.knobs_for(p.get("spread_hz"))
    now = time.time()
    tr = p["tr"]
    left = tr - (now % tr)
    src = eng.source
    lvl = getattr(src, "level_db", None) if src else None
    if eng.running:
        lvl_state = "ok" if lvl is not None and -45 < lvl < -6 else "warn"
        audio = (S.get("qx_dev_label") or "IC-9700 · USB Audio CODEC", lvl_state)
    else:
        audio = ("fermo", "none")
    items = [("Audio", audio[0], audio[1])]
    if eng.running and lvl is not None:
        items.append(("Livello", f"{lvl:.0f} dBFS", lvl_state))
    items += [("Modo", f"Q65-{tr}{p['submode']}", "ok" if p.get("mode_ok", True) else "warn"),
              ("Banda", stations.band_label(p.get("band")) if p.get("band") else "—", "none"),
              ("Rx", f"{p['rx_hz']} Hz", "none"), ("F Tol", f"{p['ftol']} Hz", "none"),
              ("DX", (p.get("dx_call") or "—") + (f" {p['dx_grid']}" if p.get("dx_grid") else ""),
               "ok" if p.get("dx_call") else "warn")]
    if p.get("manual"):
        items.append(("WSJT-X", "non collegato: valori di questa scheda", "warn"))
    sp = p.get("spread_hz")
    items.append(("Spread previsto", f"{sp:.0f} Hz" if sp else "—", "none" if sp else "assumed"))
    items.append(("Profilo Q65 Lab", k.label(), "lab"))
    if eng.running:
        items.append(("Decodifica tra", f"{int(left)//60:d}:{int(left)%60:02d}" + (" · ⏳" if eng.busy else ""), "none"))
    _html(_strip(items))
    periods = list(eng.periods)
    done = [x for x in periods if not x.skipped]
    n_lab = sum(len(x.lab.get("decodes", [])) for x in done)
    n_ref = sum(len(x.ref.get("decodes", [])) for x in done)
    rows_all = [(x, q65lab.merge(x.lab.get("decodes", []), x.ref.get("decodes", []), _wsjtx_decodes(x))) for x in done]
    n_only = sum(1 for _, rows in rows_all for r in rows if r["only_lab"])
    _html("<div class='qx-cards'>"
          f"<div class='qx-card'><i>{_t('Periodi decodificati')}</i><b>{len(done)}</b></div>"
          f"<div class='qx-card lab'><i>{_t('Decodifiche Q65 Lab')}</i><b>{n_lab}</b></div>"
          f"<div class='qx-card'><i>{_t('Decodifiche come WSJT-X')}</i><b>{n_ref}</b></div>"
          f"<div class='qx-card only'><i>{_t('Solo Q65 Lab')}</i><b>{n_only}</b></div></div>")
    left_c, right_c = st.columns([2.15, 1.35])
    with left_c.container(border=True):
        _html(f"<div class='qx-sec'>🌊 {_t('Waterfall')}</div>")
        marks = [(x.utc.timestamp(), x.utc.strftime("%H:%M:%S")) for x in periods[-12:]]
        view, auto = _wf_view(eng, openems_local.load_settings(), p)
        img = eng.waterfall.image(p["rx_hz"], p["ftol"], width=1100, height=340, marks=marks, dark=True, view=view,
                                  spec_rows=int(p["tr"] / max(view.step(), 0.2)), spread_hz=p.get("spread_hz"))
        st.image(img, width="stretch")
        tr_ = eng.waterfall.trace
        note = (f"{i18n.tr('automatico')} {view.start}–{view.start + view.span} Hz" if auto else
                f"{view.start}–{view.start + view.span} Hz") + (" · Ref Spec" if view.use_ref else "")
        if tr_:
            note += " · " + i18n.tr("possibile traccia a") + f" {tr_[0]:.0f} Hz, +{tr_[1]:.1f} dB " + i18n.tr("sul rumore")
        st.caption("🌊 " + note)
        last = next((x for x in reversed(done) if x.lab.get("red")), None)
        if last:
            st.plotly_chart(_sync_fig(last, p), width="stretch", key="qx_sync", config={"displayModeBar": False})
        elif not eng.running:
            st.caption("Premi ▶️ Ascolta: il waterfall parte subito, la prima decodifica arriva alla fine del primo "
                       "periodo intero.")
    with right_c.container(border=True):
        _html(f"<div class='qx-sec'>📋 {_t('Attività in banda')}</div>")
        _html(_table(rows_all[::-1], p.get("my_call", ""), skipped=[x for x in periods if x.skipped][-3:]))
        _html("<div class='qx-legend'>" + " ".join([
            f"<span class='qx-tag lab'>LAB</span> {_t('Q65 Lab')}",
            f"<span class='qx-tag ref'>REF</span> {_t('come WSJT-X, stesso audio')}",
            f"<span class='qx-tag wsjtx'>WSJT-X</span> {_t('decodificato da WSJT-X')}",
            f"<span class='qx-tag new'>★</span> {_t('solo Q65 Lab')}"]) + "</div>")
    if eng.errors:
        st.caption("⚠️ " + " · ".join(list(eng.errors)[-3:]))


def _table(rows_all, mycall: str, skipped=(), dated: bool = False, limit: int = 40) -> str:
    mycall = (mycall or "").upper()
    head = ("<tr><th>UTC</th><th>dB</th><th>DT</th><th>Freq</th><th>" + _t("Messaggio") + "</th><th></th></tr>")
    body = []
    for x, rows in rows_all[:limit]:
        navg = x.lab.get("navg") or (0, 0)
        ms = x.lab.get("ms")
        when = f"{x.utc:%d/%m/%Y %H:%M:%S}" if dated else f"{x.utc:%H:%M:%S}"
        if dated and x.params.get("submode"):
            when += f" · Q65-{x.params.get('tr', 60)}{x.params['submode']} · Rx {x.params.get('rx_hz')}"
        info = f"{when} · {x.knobs.label()}" + (f" · media {max(navg)}" if max(navg) > 1 else "") \
            + (f" · {ms / 1000:.1f} s" if ms else "")
        body.append(f"<tr class='per'><td colspan='6'>{html.escape(i18n.tr(info))}</td></tr>")
        if not rows:
            body.append(f"<tr class='miss'><td colspan='6'>{_t('nessuna decodifica')}</td></tr>")
        for r in rows:
            msg = r["message"]
            words = msg.split()
            cls = []
            if mycall and mycall in words:
                cls.append("me")
            elif words[:1] == ["CQ"]:
                cls.append("cq")
            if r["only_lab"]:
                cls.append("only")
            if not r["lab"]:
                cls.append("miss")
            tags = "".join(f"<span class='qx-tag {t}'>{lab}</span>" for t, lab in
                           (("lab", "LAB"), ("ref", "REF"), ("wsjtx", "WSJT-X")) if r[t])
            if r["only_lab"]:
                tags += "<span class='qx-tag new'>★</span>"
            q = f"q{r['q']}" + (str(r["nused"]) if r.get("nused") and r["nused"] > 1 else "") if r.get("q") is not None else ""
            body.append(f"<tr class='{' '.join(cls)}'><td>{x.utc:%H%M}</td><td class='n'>{r['snr'] if r['snr'] is not None else ''}</td>"
                        f"<td class='n'>{(r['dt'] or 0):.1f}</td><td class='n'>{(r['freq'] or 0):.0f}</td>"
                        f"<td>{html.escape(msg)} <span style='opacity:.6'>{q}</span></td><td>{tags}</td></tr>")
    for x in skipped:
        body.append(f"<tr class='per'><td colspan='6'>{x.utc:%H:%M:%S} · {_t('trasmissione: periodo non decodificato')}</td></tr>")
    if not body:
        body.append(f"<tr class='miss'><td colspan='6'>{_t('Le decodifiche appaiono qui alla fine di ogni periodo.')}</td></tr>")
    return f"<div class='qx-wrap'><table class='qx'>{head}{''.join(body)}</table></div>"


def _sync_fig(period: q65lab.Period, p: dict):
    import plotly.graph_objects as go
    red = period.lab["red"]
    f, avg, cur = red["f"], red["avg"], red["cur"]
    step = max(1, len(f) // 900)
    fig = go.Figure()
    rx, tol = p["rx_hz"], p["ftol"]
    fig.add_vrect(x0=rx - tol, x1=rx + tol, fillcolor="rgba(46,160,67,.08)", line_width=0)
    fig.add_vline(x=rx, line_color="#2ea043", line_width=2)
    fig.add_trace(go.Scatter(x=f[::step], y=cur[::step], name=i18n.tr("questo periodo"), line=dict(color="#f08c00", width=1.6)))
    if (avg != 0).any():
        fig.add_trace(go.Scatter(x=f[::step], y=avg[::step], name=i18n.tr("media"), line=dict(color="#e03131", width=1.6)))
    for d in period.lab.get("decodes", []):
        fig.add_vline(x=d["freq"], line_color="#7c3aed", line_dash="dot", line_width=1)
    fig.update_layout(height=150, margin=dict(l=4, r=4, t=22, b=4), showlegend=True,
                      legend=dict(orientation="h", y=1.25, x=0, font=dict(size=11)),
                      title=dict(text=i18n.tr("Curva di sincronismo") + f" · {period.utc:%H:%M}", font=dict(size=12), x=0.5),
                      xaxis=dict(range=[200, 3000], showgrid=False, tickfont=dict(size=10)),
                      yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


# ------------------------------------------------------------------ saved WSJT-X periods
def _alltxt_path(sets: dict):
    try:
        from emelab import alltxt
        ini = wsjtx_ini.find(sets.get("wsjtx_file") or None)
        cand = (ini.parent / "ALL.TXT") if ini else None
        return cand if cand and cand.is_file() else alltxt.find_default()
    except Exception:
        return None


def _file_label(path) -> str:
    from pathlib import Path
    t = q65lab.file_time(path)
    return f"{t:%d/%m/%Y %H:%M:%S} · {Path(path).name}" if t.year > 1 else Path(path).name


def _saved_files(eng: q65lab.Engine, sets: dict):
    from pathlib import Path
    with st.expander("📂 Periodi salvati da WSJT-X: decodificali con Q65 Lab"):
        ini = wsjtx_ini.find(sets.get("wsjtx_file") or None)
        folder = q65lab.save_dir(ini)
        own = eng.folder / "rx"
        st.caption("Scegli i .wav salvati da WSJT-X (Save → Save all) o quelli registrati da Q65 Lab mentre ascolta: "
                   "EMELab li legge senza modificarli, li mette in ordine di giorno e ora e li decodifica con i due "
                   "decoder, medie comprese. Con ALL.TXT confronta anche quello che ha decodificato WSJT-X.")
        sel = [Path(x) for x in S.get("qx_sel", [])]
        c = st.columns([1.3, 1.3, 1.1, 3.3], vertical_alignment="center")
        start_dir = folder if folder and any(folder.glob("*.wav")) else own
        if c[0].button("📂 Seleziona wav", key="qx_pickwav", type="primary", width="stretch",
                       help="apre la finestra di Windows nella cartella «save» di WSJT-X: puoi sceglierne più di uno"):
            got = q65lab.pick_wav_files(start_dir)
            if got is None:
                S["qx_nodialog"] = True
            elif got:
                sel = sorted({*sel, *got}, key=lambda f: (q65lab.file_time(f), str(f)))
                S["qx_sel"] = [str(x) for x in sel]
        own_files = sorted(own.glob("*.wav")) if own.is_dir() else []
        if c[1].button("🎙️ Registrati da Q65 Lab", key="qx_own", width="stretch", disabled=not own_files,
                       help="gli ultimi periodi ascoltati da Q65 Lab (cartella q65lab/rx)"):
            sel = sorted({*sel, *own_files}, key=lambda f: (q65lab.file_time(f), str(f)))
            S["qx_sel"] = [str(x) for x in sel]
        if c[2].button("🗑️ Svuota", key="qx_selclear", width="stretch", disabled=not sel):
            sel = []
            S["qx_sel"] = []
        n_saved = len(list(folder.glob("*.wav"))) if folder else 0
        c[3].caption(i18n.tr("Cartella") + f": {folder or '—'} · {n_saved} " + i18n.tr("file")
                     + ("" if n_saved else " · " + i18n.tr("in WSJT-X attiva Save → Save all per registrare i periodi")))
        up = None
        if S.get("qx_nodialog"):
            up = st.file_uploader("…oppure carica dei .wav", type=["wav"], accept_multiple_files=True, key="qx_up")
        if sel:
            sel = sorted(sel, key=lambda f: (q65lab.file_time(f), str(f)))
            keep = st.multiselect("File da decodificare (in ordine di giorno e ora)", [str(x) for x in sel],
                                  default=[str(x) for x in sel], format_func=_file_label, key="qx_selbox")
            if len(keep) != len(sel):
                S["qx_sel"] = keep
                sel = [Path(x) for x in keep]
        p = eng.current_params()
        rows_all = q65lab.read_alltxt(_alltxt_path(sets))
        c = st.columns([1.5, 1.2, 1, 1, 2.3], vertical_alignment="bottom")
        auto = c[0].toggle("Automatico da ALL.TXT", value=bool(rows_all), key="qx_f_auto", disabled=not rows_all,
                           help="per ogni file prende da ALL.TXT il modo, la frequenza Rx e il DX che WSJT-X aveva a "
                                "quell'ora; le medie ripartono quando cambiano")
        modes = [f"Q65-{t}{x}" for t in (60, 30, 120, 15, 300) for x in "ABCDE"]
        cur = f"Q65-{p['tr']}{p['submode']}"
        sub = c[1].selectbox("Modo", modes, index=modes.index(cur) if cur in modes else 3, key="qx_f_mode", disabled=auto)
        rx = c[2].number_input("Rx (Hz)", 200, 4000, int(p["rx_hz"]), 10, key="qx_f_rx", disabled=auto)
        tol = c[3].number_input("F Tol (Hz)", 10, 1000, int(p["ftol"]), 10, key="qx_f_tol")
        dx = c[4].text_input("DX Call e locator (per q3)", f"{p.get('dx_call', '')} {p.get('dx_grid', '')}".strip(),
                             key="qx_f_dx", disabled=auto)
        go_ = st.button("🧪 Decodifica con Q65 Lab e come WSJT-X", key="qx_f_go", disabled=not (sel or up) or not eng.exe)
        if go_:
            paths = list(sel)
            if up:
                tmp = q65lab.work_dir() / "upload"
                tmp.mkdir(exist_ok=True)
                for u in up:
                    (tmp / u.name).write_bytes(u.getvalue())
                    paths.append(tmp / u.name)
            dxw = dx.split()
            pp = p | {"tr": int(sub[4:-1]), "submode": sub[-1], "rx_hz": int(rx), "ftol": int(tol),
                      "dx_call": dxw[0].upper() if dxw else "", "dx_grid": dxw[1].upper() if len(dxw) > 1 else ""}
            bar = st.progress(0.0)
            try:
                S["qx_files_res"] = q65lab.decode_files(paths, pp, eng.exe, eng.knobs_for(pp.get("spread_hz")),
                                                        progress=lambda i, n: bar.progress(i / n),
                                                        alltxt_rows=rows_all, auto=auto)
            except Exception as e:
                st.error(f"q65lab: {e}")
        res = S.get("qx_files_res")
        if res:
            n_lab = sum(len(r["lab"]["decodes"]) for r in res)
            n_ref = sum(len(r["ref"]["decodes"]) for r in res)
            n_wj = sum(1 for r in res for x in r["rows"] if x.get("wsjtx"))
            only = sum(1 for r in res for x in r["rows"] if x["only_lab"])
            lost = sum(1 for r in res for x in r["rows"] if x["only_ref"])
            _html("<div class='qx-cards'>"
                  f"<div class='qx-card'><i>{_t('File')}</i><b>{len(res)}</b></div>"
                  f"<div class='qx-card lab'><i>{_t('Decodifiche Q65 Lab')}</i><b>{n_lab}</b></div>"
                  f"<div class='qx-card'><i>{_t('Decodifiche come WSJT-X')} / {_t('WSJT-X')}</i><b>{n_ref} / {n_wj}</b></div>"
                  f"<div class='qx-card only'><i>{_t('Solo Q65 Lab')} / {_t('solo WSJT-X')}</i><b>{only} / {lost}</b></div></div>")
            fake = [(q65lab.Period(r["utc"], r.get("params", {}).get("tr", 60), None, r.get("params", {}),
                                   r.get("knobs") or q65lab.lab_knobs(None), None, lab=r["lab"], ref=r["ref"]), r["rows"])
                    for r in res]
            tcol, _ = st.columns([1.7, 1])
            with tcol:
                _html(_table(fake, p.get("my_call", ""), dated=True, limit=300))     # in order of day and time


# ------------------------------------------------------------------ settings
def _settings(eng: q65lab.Engine, sets: dict):
    with st.expander("⚙️ Audio e decoder"):
        ini_path = wsjtx_ini.find(sets.get("wsjtx_file") or None)
        ini_a = q65lab.ini_audio(ini_path)
        devs = q65lab.input_devices()
        st.caption(i18n.tr("Scheda audio di WSJT-X (WSJT-X.ini)") + f": {ini_a.get('device') or '—'}"
                   + (f" · {ini_a['channel']}" if ini_a.get("channel") else "")
                   + " · " + i18n.tr("radio") + ": IC-9700 USB")
        if devs:
            labels = [f"{d['name']} · {d['api']}" for d in devs]
            auto = q65lab.pick_device(devs, sets.get("q65lab_device") or ini_a.get("device"))
            cur = next((i for i, d in enumerate(devs) if d["name"] == sets.get("q65lab_device")
                        and d["api"] == sets.get("q65lab_api")), devs.index(auto) if auto in devs else 0)
            c = st.columns([3, 1])
            i = c[0].selectbox("Scheda audio di ricezione", range(len(devs)), index=cur, format_func=lambda j: labels[j],
                               key="qx_dev", help="la stessa di WSJT-X: Windows la condivide fra i due programmi")
            chs = ["Mono", "Left", "Right", "Both"]
            ch = c[1].selectbox("Canale", chs, index=chs.index(sets.get("q65lab_channel") or ini_a.get("channel") or "Mono")
                                if (sets.get("q65lab_channel") or ini_a.get("channel") or "Mono") in chs else 0, key="qx_ch")
            if devs[i]["name"] != sets.get("q65lab_device") or devs[i]["api"] != sets.get("q65lab_api") \
                    or ch != sets.get("q65lab_channel"):
                if st.button("💾 Usa questa scheda", key="qx_dev_save"):
                    openems_local.save_settings(q65lab_device=devs[i]["name"], q65lab_api=devs[i]["api"], q65lab_channel=ch)
                    st.rerun()
        else:
            st.info("Nessuna scheda audio di ingresso trovata (serve il pacchetto sounddevice, incluso nell'installer).")
        st.markdown("**" + i18n.tr("Valori usati quando WSJT-X non manda il suo stato") + "**")
        man = sets.get("q65lab_manual", {})
        c = st.columns(4)
        sub = c[0].selectbox("Sottomodo", list("ABCDE"), index="ABCDE".index(man.get("submode", "D")), key="qx_m_sub")
        trp = c[1].selectbox("T/R (s)", [30, 60, 120], index=[30, 60, 120].index(man.get("tr", 60)), key="qx_m_tr")
        rx = c[2].number_input("Rx (Hz) ", 200, 4000, int(man.get("rx_hz", 1000)), 10, key="qx_m_rx")
        tol = c[3].number_input("F Tol (Hz) ", 10, 1000, int(man.get("ftol", 100)), 10, key="qx_m_tol")
        new = {"submode": sub, "tr": trp, "rx_hz": int(rx), "ftol": int(tol)}
        if new != man:
            openems_local.save_settings(q65lab_manual=new)
        st.caption(i18n.tr("Decoder") + f": {eng.exe or i18n.tr('non trovato')} · " + i18n.tr("periodi registrati in")
                   + f" {eng.folder / 'rx'}")


def _about():
    with st.expander("ℹ️ Che cosa cambia Q65 Lab"):
        st.markdown(i18n.tr(
            "Q65 Lab usa il decoder Q65 di WSJT-X v3.0.2 (K1JT e WSJT Development Group, licenza GPLv3) con tre "
            "regolazioni, scelte in base allo spread di librazione previsto sul percorso verso il DX:\n\n"
            "- **modello di spread a campana** invece che Lorentziano, più simile alla Luna a 24 GHz;\n"
            "- **smussatura dello spettro** 2× o 3× più larga quando lo spread supera 80 o 200 Hz;\n"
            "- **media lineare** su tutti i periodi invece di quella esponenziale di 4 periodi.\n\n"
            "Nelle simulazioni dello studio: circa +1 dB a 24 GHz con 250 Hz di spread, nulla a 10 GHz, +0,5 dB con "
            "medie di 12-16 periodi. La colonna REF è il decoder di WSJT-X sullo stesso audio: è il confronto onesto. "
            "Q65 Lab non è WSJT-X e non è approvato dai suoi autori; i sorgenti sono nella cartella q65lab "
            "dell'installazione."))
