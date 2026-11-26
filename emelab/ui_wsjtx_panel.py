# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📻 WSJT-X tab, live part: a panel laid out like the WSJT-X main window with the values read over UDP (refreshed
every 2 seconds), the control check of the QSO parameters against the band preset, the preset editor and the
warning pop-up (a warning closed twice for the same parameter and band never comes back; «🔔 Riattiva i popup»
brings all of them back).

What WSJT-X sends in its Status message: dial frequency, mode, submode, T/R period, Tx and Rx audio frequency,
F Tol, configuration name, DX call/grid, Tx enabled, transmitting, decoding, TX watchdog. Not sent: Doppler tracking
(CFOM), Split Operation, «Tx even/1st», Max Drift, Auto Seq: these are read from WSJT-X.ini (wsjtx_ini); without
the file the panel asks for a confirmation, valid 12 hours. EMELab only listens and reads files: WSJT-X is not slowed
down (it sends Status anyway; Configure goes out only to correct a value, at most 3 times, never while transmitting)."""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

import streamlit as _st

import os
import time

from emelab import gpsdo, i18n, stations, timesync, wsjtx_check, wsjtx_ini
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state
CONFIRM_HOURS = 12.0
OK, BAD, ASK = "✅", "⚠️", "❔"
PROC_EVERY_S, NTP_EVERY_S = 5, 600            # BktTimeSync process check / NTP offset measurement
_CLOCK = {"bkt": None, "t_proc": 0.0, "ntp": None, "t_ntp": 0.0, "busy": False}


def _clock_poll():
    """Background read (tasklist takes up to a second on Windows): the page never waits for it."""
    try:
        now = time.monotonic()
        if now - _CLOCK["t_proc"] >= PROC_EVERY_S or _CLOCK["bkt"] is None:
            _CLOCK["bkt"], _CLOCK["t_proc"] = timesync.bkt_running(), time.monotonic()
        if os.name == "nt" and (_CLOCK["ntp"] is None or now - _CLOCK["t_ntp"] >= NTP_EVERY_S):
            _CLOCK["ntp"], _CLOCK["t_ntp"] = timesync.ntp_offset(), time.monotonic()
    finally:
        _CLOCK["busy"] = False


# ------------------------------------------------------------------ PC clock (BktTimeSync)
def clock_state(measure: bool = False) -> dict:
    """{"bkt": bkt_running(), "ntp": ntp_offset() or None}: process checked every 5 s, NTP every 10 minutes on
    Windows (elsewhere only on request), both in the background. Read-only: EMELab never changes the clock nor
    BktTimeSync."""
    import threading
    if measure:
        _CLOCK["bkt"], _CLOCK["t_proc"] = timesync.bkt_running(), time.monotonic()
        _CLOCK["ntp"], _CLOCK["t_ntp"] = timesync.ntp_offset(), time.monotonic()
    elif _CLOCK["bkt"] is None:                     # first call: read once now, so the page starts with real values
        _CLOCK["busy"] = True
        _clock_poll()
    elif not _CLOCK["busy"] and time.monotonic() - _CLOCK["t_proc"] >= PROC_EVERY_S:
        _CLOCK["busy"] = True
        threading.Thread(target=_clock_poll, daemon=True, name="emelab-clock").start()
    return {"bkt": _CLOCK["bkt"] or {"running": None, "process": None}, "ntp": _CLOCK["ntp"]}


def clock_alerts(state: dict) -> list[dict]:
    """Pop-up alerts: BktTimeSync not running, PC clock off by more than 0.5 s."""
    out = []
    if state["bkt"].get("running") is False:
        out.append({"key": "bktsync", "msg": "BktTimeSync non è in esecuzione",
                    "detail": i18n.tr("avvialo per tenere l'orologio del PC allineato (DT di WSJT-X)"), "action": None})
    ntp = state.get("ntp") or {}
    if timesync.verdict(ntp.get("offset_s")) in ("warn", "bad"):
        out.append({"key": "clock", "msg": "Orologio del PC fuori di più di 0,5 s",
                    "detail": f"{ntp['offset_s']:+.2f} s " + i18n.tr("rispetto a") + f" {ntp['server']}", "action": None})
    return out


def _clock_box():
    st.markdown("#### " + i18n.tr("🕒 Orologio del PC (BktTimeSync)"))
    c = st.columns([3, 3, 1])
    measure = c[2].button("🔄 Misura", key="ts_measure", help="Una richiesta SNTP al server NTP (UDP 123). EMELab "
                          "non cambia l'ora del PC né le impostazioni di BktTimeSync.")
    stt = clock_state(measure)
    bkt, ntp = stt["bkt"], stt["ntp"]
    if bkt.get("running"):
        c[0].success(i18n.tr("BktTimeSync in esecuzione") + f" ({bkt['process']})")
    elif bkt.get("running") is False:
        c[0].error("BktTimeSync non è in esecuzione: avvialo (anche ridotto nella barra di sistema).")
    else:
        c[0].info("Controllo del processo BktTimeSync disponibile solo su Windows.")
    if not ntp:
        c[1].info("Premi «🔄 Misura» per confrontare l'orologio del PC con il server NTP.")
    elif ntp.get("error"):
        c[1].warning(i18n.tr("Server NTP non raggiungibile") + f" ({ntp['server']}): {i18n.tr(ntp['error'])}")
    else:
        v = timesync.verdict(ntp["offset_s"])
        txt = (i18n.tr("Scarto dell'orologio del PC") + f" {ntp['offset_s']:+.3f} s " + i18n.tr("rispetto a")
               + f" {ntp['server']} (stratum {ntp['stratum']}, " + i18n.tr("ritardo") + f" {ntp['delay_s'] * 1000:.0f} ms)")
        {"ok": c[1].success, "warn": c[1].warning, "bad": c[1].error}[v](txt)
    st.caption("Q65 e gli altri modi di WSJT-X vogliono l'orologio del PC entro pochi decimi di secondo (colonna DT): "
               "oltre ±0,5 s le decodifiche peggiorano, oltre ±1 s si perdono. EMELab controlla soltanto: non tocca "
               "l'ora di sistema né BktTimeSync.")


# ------------------------------------------------------------------ state
def _live(svc) -> bool:
    return bool(svc.running and svc.last_seen and (datetime.now(timezone.utc) - svc.last_seen).total_seconds() < 90)


def _band(svc):
    hz = (svc.status or {}).get("dial_hz")
    return stations.band_of(hz / 1e6) if hz else None


def confirmed(sets: dict, what: str, band: str | None, now: datetime | None = None) -> bool:
    """A manual check (doppler, tx_first, …) confirmed for the band in the last 12 hours."""
    t = ((sets.get("wsjtx_confirm") or {}).get(f"{what}@{band}"))
    if not t:
        return False
    try:
        last = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now or datetime.now(timezone.utc)) - last <= timedelta(hours=CONFIRM_HOURS)


def confirm(what: str, band: str | None):
    sets = openems_local.load_settings()
    c = dict(sets.get("wsjtx_confirm") or {})
    c[f"{what}@{band}"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    openems_local.save_settings(wsjtx_confirm=c)


def ini_state(sets: dict) -> dict:
    """WSJT-X.ini values, re-read only when the file changes."""
    try:
        path = wsjtx_ini.find(sets.get("wsjtx_file") or None)
        if not path:
            return {}
        mt = path.stat().st_mtime
        c = S.get("wj_ini_cache")
        if c and c[0] == str(path) and c[1] == mt:
            return c[2]
        r = wsjtx_ini.read(path)
        S["wj_ini_cache"] = (str(path), mt, r)
        return r
    except Exception:
        return {}


def alerts(svc, sets: dict) -> list[dict]:
    """What is off now: [{"key", "msg", "detail", "action"}] (action: preset / doppler / gpsdo / None)."""
    if not _live(svc):
        return []
    band = _band(svc)
    out = []
    for p in svc.problems:
        act = "preset" if (p.get("fix") or p.get("cfg")) else None
        out.append({"key": f"{p['code']}@{band}", "msg": p["msg"], "detail": p.get("detail", ""), "action": act})
    if band:
        pre = wsjtx_check.preset(band, sets)
        ini = ini_state(sets)
        for d in wsjtx_ini.differences(ini, pre):
            out.append({"key": f"{d['code']}@{band}", "msg": d["msg"], "detail": d["detail"], "action": None})
        if ini.get("doppler") is None and pre.get("doppler") and pre["doppler"] != "None" and not confirmed(sets, "doppler", band):
            out.append({"key": f"doppler@{band}", "msg": "Doppler tracking da confermare",
                        "detail": wsjtx_check.DOPPLER.get(pre["doppler"], pre["doppler"]) + " " +
                        i18n.tr("nella finestra Astro di WSJT-X"), "action": "doppler"})
        if gpsdo.reminder_due(sets):
            out.append({"key": "gpsdo", "msg": "GPSDO: controlla che sia acceso e agganciato",
                        "detail": "GPS signal OK · PLL lock OK", "action": "gpsdo"})
        out += clock_alerts(clock_state())
    return out


def to_show(svc, sets: dict) -> list[dict]:
    """Alerts for the pop-up: not closed twice, and not already closed while the problem lasts."""
    al = alerts(svc, sets)
    closed = sets.get("wsjtx_popup_closed") or {}
    keys = {a["key"] for a in al}
    done = S.setdefault("wj_popup_done", set())
    done &= keys                                   # a problem that went away and comes back shows again
    return [a for a in al if int(closed.get(a["key"], 0)) < 2 and a["key"] not in done]


def _closed(keys):
    sets = openems_local.load_settings()
    closed = dict(sets.get("wsjtx_popup_closed") or {})
    for k in keys:
        closed[k] = int(closed.get(k, 0)) + 1
    openems_local.save_settings(wsjtx_popup_closed=closed)
    S.setdefault("wj_popup_done", set()).update(keys)


# ------------------------------------------------------------------ pop-up
def _dialog_body(svc, items):
    band = _band(svc)
    for k, a in enumerate(items):
        c = st.columns([4, 2])
        c[0].warning(i18n.tr(a["msg"]) + (f": {a['detail']}" if a.get("detail") else ""))
        if a["action"] == "preset" and band and c[1].button("⚙️ Applica il preset", key=f"wjp_fix_{k}"):
            c[1].success("Inviato a WSJT-X.") if svc.apply_preset(band) else c[1].error("WSJT-X non raggiungibile.")
        elif a["action"] == "doppler" and c[1].button("✅ Attivo in WSJT-X", key=f"wjp_dop_{k}"):
            confirm("doppler", band)
            S.setdefault("wj_popup_done", set()).add(a["key"])
            S.setdefault("wj_conf_now", set()).add(a["key"])
        elif a["action"] == "gpsdo" and c[1].button("✅ GPSDO agganciato", key=f"wjp_gps_{k}"):
            gpsdo.confirm()
            S.setdefault("wj_popup_done", set()).add(a["key"])
            S.setdefault("wj_conf_now", set()).add(a["key"])
    st.caption("Puoi cambiare i parametri in WSJT-X mentre operi: EMELab avvisa soltanto. Un avviso chiuso due volte "
               "non riappare più (si riattiva nella scheda 📻 WSJT-X).")
    c = st.columns(2)
    if c[0].button("Chiudi", type="primary", key="wjp_close"):
        _closed([a["key"] for a in items if a["key"] not in S.get("wj_conf_now", set())])
        S["wj_conf_now"] = set()
        _st.rerun()
    from emelab import nav
    if nav.button(_kind(items), key="wjp_go", container=c[1],
                  on_click=lambda: S.setdefault("wj_popup_done", set()).update(a["key"] for a in items)):
        _st.rerun()                                 # seen: back only if the problem goes away and returns


def _kind(items) -> str:
    """Alert kind for the «➡️ Apri» button: GPSDO, PC clock or the WSJT-X settings."""
    keys = [a["key"] for a in items]
    if any(not k.startswith(("gpsdo", "clock", "bktsync")) for k in keys):
        return "wsjtx"
    return "gpsdo" if any(k.startswith("gpsdo") for k in keys) else "clock"


def _on_dismiss():
    _closed([k for k in (S.get("wj_popup_keys") or []) if k not in S.get("wj_conf_now", set())])
    S["wj_conf_now"] = set()


try:
    _dialog = _st.dialog("⚠️ WSJT-X", width="large", on_dismiss=_on_dismiss)(_dialog_body)
except TypeError:                                   # older Streamlit: no on_dismiss
    _dialog = _st.dialog("⚠️ WSJT-X", width="large")(_dialog_body)


def popup(svc):
    """Open the pop-up when something is off (called on every full run of the app)."""
    try:
        items = to_show(svc, openems_local.load_settings())
    except Exception:
        return
    S["wj_alert_keys"] = sorted(a["key"] for a in items)
    if items:
        S["wj_popup_keys"] = [a["key"] for a in items]
        _dialog(svc, items)


# ------------------------------------------------------------------ the WSJT-X-like panel
_CSS = """<style>
.wjx{font-family:Segoe UI,Arial,sans-serif;font-size:13px;background:#f0f0f0;color:#000;border:1px solid #aaa;border-radius:4px;
     padding:8px;max-width:980px}
.wjx .row{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;margin-bottom:6px}
.wjx .freq{background:#000;color:#ffeb3b;font:600 26px Consolas,monospace;padding:6px 14px;min-width:240px;text-align:center}
.wjx .clock{background:#000;color:#ffeb3b;font:600 16px Consolas,monospace;padding:6px 10px;text-align:center}
.wjx .btn{display:inline-block;border:1px solid #999;background:#e1e1e1;padding:2px 8px;margin:1px;border-radius:2px;min-width:34px;
     text-align:center}
.wjx .on{background:#00e000;border-color:#008000}
.wjx .cell{border:1px solid #bbb;background:#fff;padding:3px 7px;border-radius:2px}
.wjx .lbl{color:#333;margin-right:4px}
.wjx .bad{background:#ffe0b2;border-color:#e8590c}
.wjx .ask{background:#fff8e1;border-color:#bfa100}
.wjx .bar{display:flex;gap:6px;flex-wrap:wrap}
.wjx .rx{background:#00e000;padding:2px 10px}.wjx .tx{background:#ff4040;color:#fff;padding:2px 10px}
.wjx .grp{border:1px solid #bbb;padding:5px;border-radius:3px;background:#f7f7f7}
</style>"""


def _cell(label, value, mark=""):
    cls = {"⚠️": "cell bad", "❔": "cell ask"}.get(mark, "cell")
    return (f"<span class='{cls}'><span class='lbl'>{html.escape(i18n.tr(label))}</span>"
            f"<b>{html.escape(str(value))}</b> {mark}</span>")


def _ini_cell(label, key, want, ini, sets, band, fmt=lambda v: v):
    """A setting not sent over UDP: from WSJT-X.ini when available (✅/⚠️), else the preset value to confirm (❔)."""
    if want is None:
        return _cell(label, "—")
    have = (ini or {}).get(key)
    if have is not None:
        return _cell(label, fmt(have), OK if str(have) == str(want.get(key)) else BAD)
    conf_key = "doppler" if key == "doppler" else "manual"
    return _cell(label, fmt(want.get(key, "—")), OK if confirmed(sets, conf_key, band) else ASK)


def panel_html(status: dict, pre: dict | None, sets: dict, band: str | None, ini: dict | None = None) -> str:
    """HTML of the WSJT-X-like panel (pure function: tested without Streamlit)."""
    s = status or {}
    nul = wsjtx_check.NULL
    num = lambda k: None if s.get(k) in (None, nul) else int(s[k])
    mode = (s.get("mode") or "").strip()
    sub = (s.get("submode") or "").strip().upper()
    tr = num("tr_period")
    tx, rx, ftol = num("tx_df"), num("rx_df"), num("freq_tolerance")

    def mk(ok):
        return "" if pre is None else (OK if ok else BAD)
    want = pre or {}
    modes = "".join(f"<span class='btn{' on' if mode.upper() == m.upper() else ''}'>{m}</span>"
                    for m in ("FT8", "FT4", "MSK", "Q65", "JT65", "Echo"))
    subs = "".join(f"<span class='btn{' on' if mode.upper().startswith('Q65') and tr == int(c[:-1]) and sub == c[-1] else ''}'>{c}</span>"
                   for c in ("15A", "15C", "30B", "60C", "60D", "60E", "120E"))
    hz = s.get("dial_hz")
    f = f"{hz / 1e6:,.6f}".replace(",", " ").replace(".", ",", 1) if hz else "—"
    now = datetime.now(timezone.utc)
    rows = [
        "<div class='row'>"
        f"<div class='freq'>{f}<div style='font-size:12px;color:#ccc'>{html.escape(stations.band_label(band) if band else '—')}</div></div>"
        f"<div class='clock'>{now:%Y %b %d}<br>{now:%H:%M:%S}</div>"
        f"<div class='grp'>{_cell('DX Call', s.get('dx_call') or '—')}<br>{_cell('DX Grid', s.get('dx_grid') or '—')}</div>"
        "</div>",
        f"<div class='row'><div class='grp'>{modes}</div><div class='grp'>{subs}</div></div>",
        "<div class='row'>"
        + _cell("Modo", f"Q65-{tr or ''}{sub}" if mode.upper().startswith("Q65") else (mode or "—"),
                mk(mode.upper().startswith("Q65") and sub == want.get("submode") and (tr is None or tr == want.get("tr"))))
        + (f" <span class='lbl'>→ Q65-{want['mode']}</span>" if pre else "")
        + _cell("Tx", f"{tx} Hz" if tx is not None else "—", mk(tx is not None and abs(tx - int(want.get("tx_df", 0))) <= 5))
        + _cell("Rx", f"{rx} Hz" if rx is not None else "—", mk(rx is not None and abs(rx - int(want.get("rx_df", 0))) <= 5))
        + _cell("F Tol", f"{ftol} Hz" if ftol is not None else "—",
                "" if ftol is None else mk(ftol == int(want.get("f_tol") or ftol)))
        + _cell("T/R", f"{tr} s" if tr else "—", "" if not tr else mk(tr == want.get("tr")))
        + "</div>",
        "<div class='row'>"
        + _ini_cell("Doppler", "doppler", pre, ini, sets, band, lambda v: wsjtx_check.DOPPLER.get(v, v).split(" (")[0])
        + _ini_cell("Split", "split", pre, ini, sets, band)
        + _ini_cell("Tx even/1st", "tx_first", pre, ini, sets, band, lambda v: "sì" if v else "no")
        + _ini_cell("Max Drift", "max_drift", pre, ini, sets, band)
        + _ini_cell("Auto Seq", "auto_seq", pre, ini, sets, band, lambda v: "sì" if v else "no")
        + "</div>",
        "<div class='row bar'>"
        + (f"<span class='tx'>{html.escape(i18n.tr('Trasmissione'))}</span>" if s.get("transmitting")
           else f"<span class='rx'>{html.escape(i18n.tr('Ricezione'))}</span>")
        + _cell("Config", s.get("config_name") or "—",
                "" if not (pre and s.get("config_name")) else mk(str(s["config_name"]).strip().casefold() == str(want.get("config", "")).strip().casefold()))
        + _cell("Tx abilitato", "sì" if s.get("tx_enabled") else "no")
        + (_cell("TX watchdog", "!", BAD) if s.get("tx_watchdog") else "")
        + (_cell("Tx", s.get("tx_message"), "") if s.get("tx_message") else "")
        + "</div>",
    ]
    return _CSS + "<div class='wjx'>" + "".join(rows) + "</div>"


def _live_fragment(svc):
    sets = openems_local.load_settings()
    band = _band(svc)
    pre = wsjtx_check.preset(band, sets) if band else None
    if not _live(svc):
        st.info("Il pannello si riempie appena WSJT-X manda il primo messaggio di stato via UDP.")
        return
    age = (datetime.now(timezone.utc) - svc.last_seen).total_seconds()
    ini = ini_state(sets)
    h = panel_html(svc.status, pre, sets, band, ini)
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
    st.caption(i18n.tr("Valori letti da WSJT-X in tempo reale") + f" ({svc.client or 'WSJT-X'}, {age:.0f} s) · "
               + i18n.tr("✅ come il preset · ⚠️ diverso dal preset · ❔ WSJT-X non lo manda: confermalo tu")
               + (" · " + i18n.tr("Doppler, Split, Tx even/1st, Max Drift e Auto Seq da WSJT-X.ini salvato alle")
                  + f" {ini['saved']:%H:%M} UTC" if ini.get("saved") else ""))
    keys = sorted(a["key"] for a in to_show(svc, sets))
    if keys and keys != S.get("wj_alert_keys"):    # a new problem: rerun the whole page to open the pop-up
        S["wj_alert_keys"] = keys
        _st.rerun(scope="app")


try:
    _live_fragment = _st.fragment(run_every=2)(_live_fragment)
except Exception:                                   # Streamlit without fragments: plain function
    pass


# ------------------------------------------------------------------ control check + preset editor
def check_rows(svc, sets, band) -> list[dict]:
    """Rows of the control check: Parametro, Preset, WSJT-X adesso, Stato (✅/⚠️/❔). Also used by 🔴 Live."""
    pre = wsjtx_check.preset(band, sets)
    s = svc.status or {}
    probs = {p["code"]: p for p in svc.problems}
    nul = wsjtx_check.NULL

    def v(k):
        return None if s.get(k) in (None, nul) else s.get(k)
    rows = [("Modo", f"Q65-{pre['mode']}", f"{s.get('mode', '')} {s.get('submode', '')}".strip() or "—", "mode"),
            ("Tx", f"{pre['tx_df']} Hz", f"{v('tx_df')} Hz" if v("tx_df") is not None else "—", "tx_df"),
            ("Rx", f"{pre['rx_df']} Hz", f"{v('rx_df')} Hz" if v("rx_df") is not None else "—", "rx_df"),
            ("F Tol", f"{pre['f_tol']} Hz", f"{v('freq_tolerance')} Hz" if v("freq_tolerance") is not None else "—", "ftol"),
            ("Configurazione", pre.get("config") or "—", s.get("config_name") or "—", "config")]
    out = [{"Parametro": a, "Preset": b, "WSJT-X adesso": c,
            "Stato": BAD if code in probs else (OK if c != "—" else ASK)} for a, b, c, code in rows]
    ini = ini_state(sets)
    yn = {True: "sì", False: "no"}
    for key, label in wsjtx_check.MANUAL:
        want = pre.get(key)
        have = ini.get(key)
        show = (lambda v: wsjtx_check.DOPPLER.get(v, v)) if key == "doppler" else (lambda v: yn.get(v, v))
        conf = "doppler" if key == "doppler" else "manual"
        out.append({"Parametro": label.replace("«", "").replace("»", ""), "Preset": show(want),
                    "WSJT-X adesso": f"{show(have)} (WSJT-X.ini)" if have is not None else i18n.tr("non inviato via UDP"),
                    "Stato": (OK if str(have) == str(want) else BAD) if have is not None else (OK if confirmed(sets, conf, band) else ASK)})
    return out


def _check_table(svc, sets, band):
    pre = wsjtx_check.preset(band, sets)
    out = check_rows(svc, sets, band)
    st.dataframe(out, hide_index=True, width="stretch")
    if pre.get("assumed"):
        st.markdown(f"<span style='color:#e8590c'>{html.escape(i18n.tr('Valori presunti: copiati dai 24GHz, controllali e salvali'))}</span>",
                    unsafe_allow_html=True)
    c = st.columns(3)
    if c[0].button("⚙️ Applica il preset in WSJT-X", key="wj_apply", help="modo, sottomodo, T/R, F Tol e Rx (Tx va messo a mano)"):
        st.success("Inviato a WSJT-X.") if svc.apply_preset(band) else st.error("WSJT-X non raggiungibile.")
    if c[1].button("✅ Doppler tracking attivo", key="wj_dop_ok"):
        confirm("doppler", band)
        _st.rerun()
    if c[2].button("✅ Split, Tx even/1st, Max Drift, Auto Seq a posto", key="wj_man_ok"):
        confirm("manual", band)
        _st.rerun()


def _advice_box(svc, sets):
    """DL3WDG's advice for microwave EME that WSJT-X does not follow now: only notes, never a pop-up."""
    st.markdown("#### " + i18n.tr("📘 Consigli di DL3WDG per l'EME a microonde"))
    ini = ini_state(sets)
    if not ini:
        st.caption("WSJT-X.ini non trovato: i consigli compaiono quando EMELab trova il file accanto a wsjtx_log.adi.")
        return
    items = wsjtx_ini.advice(ini, svc.status if _live(svc) else None)
    if not items:
        st.success("Media, decodifica, Single decode, EME delay, locator e DX: tutto come consiglia DL3WDG.")
    for a in items:
        st.info(i18n.tr(a["msg"]) + ": " + i18n.tr(a["detail"]))
    st.caption("Dalla guida «Using WSJT-X for Microwave EME (Q65 and Echo mode)» di Charlie Suckling DL3WDG (EME 2022). "
               "Sono solo consigli: EMELab non cambia WSJT-X.")


def no_decode_rows(status: dict, ini: dict, clock: dict, sets: dict) -> list[dict]:
    """«I see the signal but there is no decode»: the causes listed by DL3WDG, each with its state where EMELab can
    tell (✅ fine, ⚠️ likely, ❔ check it yourself) and what to do."""
    s = status or {}
    mode = f"Q65-{s.get('tr_period') or ''}{(s.get('submode') or '').strip()}" if (s.get("mode") or "").upper().startswith("Q65") else (s.get("mode") or "—")
    rows = []

    def add(state, cause, todo, value=""):
        rows.append({"Stato": state, "Causa possibile": i18n.tr(cause) + (f" ({value})" if value else ""),
                     "Cosa fare": i18n.tr(todo)})
    add(ASK, "Sottomodo diverso da quello del corrispondente", "chiedigli che sottomodo usa: deve essere identico", mode)
    ntp = (clock or {}).get("ntp") or {}
    v = timesync.verdict(ntp.get("offset_s"))
    bkt = ((clock or {}).get("bkt") or {}).get("running")
    state = BAD if (v in ("warn", "bad") or bkt is False) else OK if v == "ok" else ASK
    add(state, "Orologio del PC sbagliato o corretto a metà periodo",
        "BktTimeSync acceso e scarto entro ±0,5 s; una correzione dell'ora durante il periodo rovina la decodifica",
        f"{ntp['offset_s']:+.2f} s" if ntp.get("offset_s") is not None else "")
    gps_due = gpsdo.reminder_due(sets)
    drift = ini.get("max_drift")
    add(ASK if gps_due else OK, "Segnale che deriva o instabile",
        "rig agganciato al GPSDO e Max Drift 0; se il segnale deriva e non decodifica, prova Max Drift diverso da 0",
        f"Max Drift {drift}" if drift is not None else "")
    depth = ini.get("depth")
    add(OK if depth == "Deep" else BAD if depth else ASK, "Decodifica Fast o Normal",
        "metti Deep, oppure fai doppio clic sul tono di sync nella cascata (o premi Decode): rifà la decodifica in Deep",
        depth or "")
    ftol = s.get("freq_tolerance")
    add(ASK, "Segnale fuori dalla barra verde (F Tol)",
        "il segnale deve stare dentro la barra verde attorno a Rx; se non sai dov'è allarga F Tol (decodifica più lenta)",
        f"F Tol {ftol} Hz" if ftol not in (None, wsjtx_check.NULL) else "")
    dop = ini.get("doppler")
    add((OK if dop == "CFOM" else BAD) if dop else ASK, "Doppler tracking spento o diverso dal corrispondente",
        "CFOM da entrambe le parti è il caso più semplice: il Doppler si aggiorna di continuo",
        wsjtx_check.DOPPLER.get(dop, dop) if dop else "")
    add(ASK, "Ha iniziato a trasmettere tardi o ha cambiato messaggio durante il periodo", "aspetta il periodo successivo")
    add(ASK, "Salto di Doppler grande (es. 20 Hz) a metà periodo", "succede senza CAT continuo: aspetta il periodo successivo")
    add(ASK, "Audio interrotto", "chiudi e riapri WSJT-X")
    return rows


def _no_decode_box(svc, sets):
    with st.expander("🤔 " + i18n.tr("Vedo il segnale in cascata ma non decodifica: perché?")):
        rows = no_decode_rows(svc.status if _live(svc) else {}, ini_state(sets), clock_state(), sets)
        _st.dataframe([{i18n.tr(k): v for k, v in r.items()} for r in rows], hide_index=True, width="stretch")
        st.caption("Le cause elencate da DL3WDG; spesso sono più di una insieme. ✅ a posto · ⚠️ probabile · ❔ controlla tu.")


def _preset_editor(band):
    """Every field of the band preset, editable and saved in the settings (only compared with WSJT-X, never written
    into WSJT-X.ini)."""
    pre = wsjtx_check.preset(band)
    if pre.get("assumed"):
        st.markdown(f"<span style='color:#e8590c'>{html.escape(i18n.tr('Valori presunti: copiati dai 24GHz. Controllali, correggili e salva il preset.'))}</span>",
                    unsafe_allow_html=True)
    elif pre.get("saved"):
        st.caption(i18n.tr("Preset salvato da te."))
    modes = list(wsjtx_check.Q65_PRESET_MODES)
    c = st.columns(4)
    mode = c[0].selectbox("Modo Q65 (sottomodo e T/R)", modes, index=modes.index(pre["mode"]) if pre["mode"] in modes else modes.index("60E"),
                          key=f"wjp_mode_{band}", format_func=lambda k: f"Q65-{k}",
                          help=i18n.tr("Il numero è il periodo T/R in secondi, la lettera il sottomodo. Soglie e margini EMELab li calcola per 60D, 60E e 120E."))
    tx = c[1].number_input("Tx (Hz)", 200, 4000, int(pre["tx_df"]), 10, key=f"wjp_tx_{band}")
    rx = c[2].number_input("Rx (Hz)", 200, 4000, int(pre["rx_df"]), 10, key=f"wjp_rx_{band}")
    ftol = c[3].number_input("F Tol (Hz)", 10, 1000, int(pre["f_tol"]), 10, key=f"wjp_ftol_{band}")
    c = st.columns(4)
    cfg = c[0].text_input("Configurazione", pre.get("config") or "", key=f"wjp_cfg_{band}")
    dop = c[1].selectbox("Doppler tracking", list(wsjtx_check.DOPPLER), index=list(wsjtx_check.DOPPLER).index(pre.get("doppler", "CFOM"))
                         if pre.get("doppler") in wsjtx_check.DOPPLER else 0, format_func=lambda k: wsjtx_check.DOPPLER[k],
                         key=f"wjp_dop_{band}")
    drift = c[2].number_input("Max Drift", 0, 100, int(pre.get("max_drift") or 0), 1, key=f"wjp_drift_{band}")
    split = c[2].selectbox("Split Operation", list(wsjtx_check.SPLIT), index=list(wsjtx_check.SPLIT).index(pre.get("split", "Rig"))
                           if pre.get("split") in wsjtx_check.SPLIT else 0, key=f"wjp_split_{band}")
    c3 = c[3].columns(2)
    txf = c3[0].checkbox("Tx even/1st", bool(pre.get("tx_first")), key=f"wjp_txf_{band}")
    aseq = c3[1].checkbox("Auto Seq", bool(pre.get("auto_seq")), key=f"wjp_aseq_{band}")
    c = st.columns([1, 1, 2])
    if c[0].button("💾 Salva il preset della banda", key=f"wjp_save_{band}"):
        wsjtx_check.save_preset(band, mode=mode, tx_df=int(tx), rx_df=int(rx), f_tol=int(ftol), config=cfg.strip(),
                                doppler=dop, max_drift=int(drift), tx_first=txf, auto_seq=aseq, split=split)
        st.success("Preset salvato.")
        _st.rerun()
    if pre.get("saved") and c[1].button("↩️ Torna ai valori iniziali", key=f"wjp_reset_{band}"):
        wsjtx_check.reset_preset(band)
        for k in ("mode", "tx", "rx", "ftol", "cfg", "dop", "drift", "split", "txf", "aseq"):
            S.pop(f"wjp_{k}_{band}", None)
        _st.rerun()


def _preset_editors(band):
    """One tab per band (10, 24, 47, 76 GHz; the band WSJT-X is on comes first)."""
    st.markdown("#### " + i18n.tr("✏️ Preset di WSJT-X per banda"))
    st.caption(i18n.tr("Scrivi i valori che usi su ogni banda e salvali: EMELab li usa solo per il controllo qui sopra e "
                       "non modifica mai WSJT-X.ini."))
    bands = ([band] if band else []) + [b for b in wsjtx_check.EDITABLE_BANDS if b != band]
    for b, tab in zip(bands, st.tabs([stations.band_label(b) for b in bands])):
        with tab:
            _preset_editor(b)


def render(svc, sets):
    """Live panel, control check, preset editor, automatic corrections and pop-up settings."""
    st.markdown("#### " + i18n.tr("🖥️ WSJT-X in tempo reale"))
    _live_fragment(svc)
    _clock_box()
    band = _band(svc)
    st.markdown("#### " + i18n.tr("✅ Controllo dei parametri per il QSO"))
    st.caption("EMELab confronta i valori di WSJT-X con il preset della banda (10GHz: Q65-60D, Tx e Rx 1000 Hz, CFOM; "
               "24GHz: Q65-60E, Tx e Rx 700 Hz; 47 e 76GHz: presunti come i 24GHz; Split «Rig»; tutti modificabili "
               "qui sotto). EMELab cambia WSJT-X solo quando premi «⚙️ Applica il preset» (serve "
               "«Accept UDP requests» in WSJT-X); altrimenti legge e segnala soltanto; Tx lo "
               "segnala soltanto; Doppler tracking, Split, Tx even/1st, Max Drift e Auto Seq non passano via UDP: li "
               "legge da WSJT-X.ini (che WSJT-X salva quando cambi un'impostazione). EMELab ascolta e legge file: "
               "non rallenta WSJT-X.")
    if band and _live(svc):
        _check_table(svc, sets, band)
    else:
        st.info("Il controllo parte quando WSJT-X è collegato e su una banda da 10 GHz in su.")
    _advice_box(svc, sets)
    _no_decode_box(svc, sets)
    _preset_editors(band)
    if svc.fixes:
        f = svc.fixes[0]
        st.caption(i18n.tr("Ultima correzione inviata") + f": {f['utc']:%H:%M:%S} UTC, {f['from']} → {f['to']}")
    closed = {k: v for k, v in (sets.get("wsjtx_popup_closed") or {}).items() if int(v) >= 2}
    if closed:
        c = st.columns([4, 1])
        c[0].caption(i18n.tr("Avvisi che non compaiono più (chiusi due volte)") + ": " + ", ".join(sorted(closed)))
        if c[1].button("🔔 Riattiva i popup", key="wj_popup_reset"):
            openems_local.save_settings(wsjtx_popup_closed={})
            S["wj_popup_done"] = set()
            _st.rerun()
