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
    c = st.columns([5.2, 1.25, 1.1, 2.2], vertical_alignment="center")
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
    prof = c[3].selectbox("Profilo Q65 Lab", list(PROFILES), format_func=lambda k: i18n.tr(PROFILES[k]),
                          index=list(PROFILES).index(eng.mode), key="qx_profile", label_visibility="collapsed",
                          help="Automatico: metrica di WSJT-X fino a 80 Hz di spread, campana e smussatura 2× fino a "
                               "200 Hz, 3× oltre. Sempre media lineare.")
    if prof != sets.get("q65lab_profile", "auto"):
        openems_local.save_settings(q65lab_profile=prof)
        eng.mode = prof
    if sets.get("q65lab_on") and not eng.running and eng.exe and not S.get("qx_autostart_tried"):
        S["qx_autostart_tried"] = True                  # it was listening when EMELab was closed: starts again
        _start(eng, sets, quiet=True)


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
        img = eng.waterfall.image(p["rx_hz"], p["ftol"], width=1100, height=330, marks=marks, dark=True)
        st.image(img, width="stretch")
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


def _table(rows_all, mycall: str, skipped=()) -> str:
    mycall = (mycall or "").upper()
    head = ("<tr><th>UTC</th><th>dB</th><th>DT</th><th>Freq</th><th>" + _t("Messaggio") + "</th><th></th></tr>")
    body = []
    for x, rows in rows_all[:40]:
        navg = x.lab.get("navg") or (0, 0)
        ms = x.lab.get("ms")
        info = f"{x.utc:%H:%M:%S} · {x.knobs.label()}" + (f" · media {max(navg)}" if max(navg) > 1 else "") \
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
def _saved_files(eng: q65lab.Engine, sets: dict):
    with st.expander("📂 Periodi salvati da WSJT-X: decodificali con Q65 Lab"):
        folder = q65lab.save_dir(wsjtx_ini.find(sets.get("wsjtx_file") or None))
        st.caption("WSJT-X salva ogni periodo con Save → Save all (o Save decoded) nella cartella «save» accanto a "
                   "WSJT-X.ini. EMELab li legge senza modificarli e li decodifica in ordine con i due decoder, medie "
                   "comprese: è il confronto più onesto, sullo stesso audio.")
        files = q65lab.saved_files(folder)
        up = st.file_uploader("…oppure carica dei .wav", type=["wav"], accept_multiple_files=True, key="qx_up")
        if folder:
            st.caption(i18n.tr("Cartella") + f": {folder} · {len(files)} " + i18n.tr("file"))
        elif not up:
            st.info("Cartella «save» di WSJT-X non trovata: attiva Save → Save all in WSJT-X, oppure carica i file qui.")
        names = [f["name"] for f in files]
        pick = st.multiselect("File da decodificare", names, default=names[:min(10, len(names))], key="qx_pick",
                              help="i più recenti per primi; vengono decodificati in ordine di tempo")
        p = eng.current_params()
        c = st.columns([1.2, 1, 1, 2.5], vertical_alignment="bottom")
        modes = [f"Q65-{t}{x}" for t in (60, 30, 120) for x in "ABCDE"]
        cur = f"Q65-{p['tr']}{p['submode']}"
        sub = c[0].selectbox("Modo", modes, index=modes.index(cur) if cur in modes else 3, key="qx_f_mode")
        rx = c[1].number_input("Rx (Hz)", 200, 4000, int(p["rx_hz"]), 10, key="qx_f_rx")
        tol = c[2].number_input("F Tol (Hz)", 10, 1000, int(p["ftol"]), 10, key="qx_f_tol")
        dx = c[3].text_input("DX Call e locator (per q3)", f"{p.get('dx_call', '')} {p.get('dx_grid', '')}".strip(), key="qx_f_dx")
        go_ = st.button("🧪 Decodifica con Q65 Lab e come WSJT-X", key="qx_f_go", disabled=not (pick or up) or not eng.exe)
        if go_:
            paths = [f["path"] for f in files if f["name"] in pick]
            if up:
                tmp = q65lab.work_dir() / "upload"
                tmp.mkdir(exist_ok=True)
                for u in up:
                    (tmp / u.name).write_bytes(u.getvalue())
                    paths.append(tmp / u.name)
            tr = int(sub[4:-1])
            dxw = dx.split()
            pp = p | {"tr": tr, "submode": sub[-1], "rx_hz": int(rx), "ftol": int(tol),
                      "dx_call": dxw[0].upper() if dxw else "", "dx_grid": dxw[1].upper() if len(dxw) > 1 else ""}
            bar = st.progress(0.0)
            try:
                S["qx_files_res"] = q65lab.decode_files(paths, pp, eng.exe, eng.knobs_for(pp.get("spread_hz")),
                                                        progress=lambda i, n: bar.progress(i / n))
            except Exception as e:
                st.error(f"q65lab: {e}")
        res = S.get("qx_files_res")
        if res:
            n_lab = sum(len(r["lab"]["decodes"]) for r in res)
            n_ref = sum(len(r["ref"]["decodes"]) for r in res)
            only = sum(1 for r in res for x in r["rows"] if x["only_lab"])
            lost = sum(1 for r in res for x in r["rows"] if x["only_ref"])
            _html("<div class='qx-cards'>"
                  f"<div class='qx-card'><i>{_t('File')}</i><b>{len(res)}</b></div>"
                  f"<div class='qx-card lab'><i>{_t('Decodifiche Q65 Lab')}</i><b>{n_lab}</b></div>"
                  f"<div class='qx-card'><i>{_t('Decodifiche come WSJT-X')}</i><b>{n_ref}</b></div>"
                  f"<div class='qx-card only'><i>{_t('Solo Q65 Lab')} / {_t('solo WSJT-X')}</i><b>{only} / {lost}</b></div></div>")
            fake = [(q65lab.Period(r["utc"], 60, None, {}, q65lab.lab_knobs(None), None, lab=r["lab"], ref=r["ref"]), r["rows"])
                    for r in res]
            _html(_table(fake[::-1], p.get("my_call", "")))


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
