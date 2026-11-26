# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🔴 Live: everything needed while operating, on one page.

Four quadrants (Moon from the camera with the offset and the rotor corrections · DriverDish · watchdogs ·
Moon and clock) and, underneath, one compact strip with the QSO parameters read from WSJT-X (sked, Tx and Rx
frequency, mode, F Tol, Split, 1st/2nd, Doppler), BktTimeSync with the PC clock and DT, and the GPSDO lock."""
from __future__ import annotations

import html
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone

import streamlit as _st

from emelab import i18n, moontrack as mt, stations, timesync, ui_camera, wsjtx_check
from emelab import settings as openems_local

st = i18n.wrap(_st)
S = _st.session_state
GPSDO_EVERY_S = 20
CAM_MAX_H = 300
DT_WARN_S, DT_BAD_S = 0.5, 1.0


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


# ------------------------------------------------------------------ data sources (all read-only)
def _svc():
    try:
        from emelab import ui
        return ui._wsjtx_service()
    except Exception:
        return None


def _wsjtx_live(svc) -> bool:
    return bool(svc and svc.running and svc.last_seen
                and (datetime.now(timezone.utc) - svc.last_seen).total_seconds() < 90)


def dd_status():
    """(status dict or None, error or None) from DriverDish's telnet reader of the Tracking tab."""
    sets = openems_local.load_settings()
    if not sets.get("dd_live"):
        return None, "off"
    try:
        from emelab import ui_tracking
        mon = ui_tracking._monitor(sets.get("dd_host", "127.0.0.1"), int(sets.get("dd_port", 9999)))
        return (mon.last if mon.connected else None), mon.error
    except Exception as e:
        return None, str(e)


_GPSDO = {"last": None, "t": 0.0, "busy": False, "loss": None, "loss_utc": None}


def note_loss(prev: int | None, prev_utc, reading: dict | None, now: datetime | None = None):
    """(loss counter, UTC of the last lock loss): the Leo Bodnar counts its lock losses, so a loss that came and
    went between two reads still shows as a counter that moved."""
    n = (reading or {}).get("loss_count")
    if not isinstance(n, int):
        return prev, prev_utc
    if prev is not None and n != prev:
        return n, now or datetime.now(timezone.utc)
    return n, prev_utc


def gpsdo_state() -> dict | None:
    """Leo Bodnar lock state, read in the background once a minute (a read takes a few seconds)."""
    sets = openems_local.load_settings()
    if not sets.get("gpsdo_use", True):
        return None
    if not _GPSDO["busy"] and time.time() - _GPSDO["t"] > GPSDO_EVERY_S:
        _GPSDO["busy"] = True

        def run():
            try:
                from emelab import gpsdo
                r = gpsdo.read_leo_bodnar(seconds=2.5, satellites=False)
                _GPSDO["loss"], _GPSDO["loss_utc"] = note_loss(_GPSDO["loss"], _GPSDO["loss_utc"], r)
                _GPSDO["last"] = {**r, "loss_utc": _GPSDO["loss_utc"]} if isinstance(r, dict) else r
            except Exception as e:
                _GPSDO["last"] = {"error": str(e)}
            finally:
                _GPSDO["t"], _GPSDO["busy"] = time.time(), False
        threading.Thread(target=run, daemon=True, name="emelab-live-gpsdo").start()
    return _GPSDO["last"]


def dt_median(svc, minutes: float = 10.0) -> tuple[float | None, int]:
    """Median DT of the decodes of the last minutes (WSJT-X UDP), and how many."""
    if not svc:
        return None, 0
    now = datetime.now(timezone.utc)
    dts = [d["dt"] for d in list(svc.recent)[:200] if d.get("dt") is not None and now - d["utc"] <= timedelta(minutes=minutes)]
    return (statistics.median(dts) if dts else None), len(dts)


# ------------------------------------------------------------------ bottom strip
def _mhz(hz) -> str:
    return f"{hz / 1e6:,.6f}".replace(",", " ") if hz else "—"


def strip_items(status: dict | None, ini: dict | None, bkt: dict | None, ntp: dict | None, dt: float | None,
                n_dt: int, gp: dict | None) -> list[tuple[str, str, str]]:
    """[(label, value, state ok/warn/bad/none)] of the bottom strip (pure function, tested without Streamlit)."""
    s, ini = status or {}, ini or {}
    nul = wsjtx_check.NULL
    num = lambda k: None if s.get(k) in (None, nul) else int(s[k])
    dial, txdf, rxdf, ftol, tr = s.get("dial_hz"), num("tx_df"), num("rx_df"), num("freq_tolerance"), num("tr_period")
    mode = (s.get("mode") or "").strip()
    sub = (s.get("submode") or "").strip().upper()
    out = [("Sked", f"{_mhz(dial)} MHz" if dial else "—", "none"),
           ("TX", f"{_mhz(dial + txdf)} MHz" if dial and txdf is not None else "—", "none"),
           ("RX", f"{_mhz(dial + rxdf)} MHz" if dial and rxdf is not None else "—", "none"),
           ("Modo", (f"Q65-{tr or ''}{sub}" if mode.upper().startswith("Q65") else mode) or "—", "none"),
           ("F Tol", f"{ftol} Hz" if ftol is not None else "—", "none")]
    sp = ini.get("split")
    out.append(("Split", sp or "—", "none" if sp is None else ("ok" if sp != "None" else "warn")))
    tf = ini.get("tx_first")
    out.append(("Tx", "—" if tf is None else ("1st" if tf else "2nd"), "none"))
    dop = ini.get("doppler")
    out.append(("Doppler", "—" if dop is None else ("OFF" if dop == "None" else dop),
                "none" if dop is None else ("bad" if dop == "None" else "ok")))
    if bkt and bkt.get("running") is not None:
        out.append(("BktTimeSync", "OK" if bkt["running"] else "NO", "ok" if bkt["running"] else "bad"))
    else:
        out.append(("BktTimeSync", "—", "none"))
    if ntp and ntp.get("offset_s") is not None:
        v = timesync.verdict(ntp["offset_s"])
        out.append(("NTP", f"{ntp['offset_s']:+.2f} s", v or "none"))
    if dt is None:
        out.append(("DT", "—", "none"))
    else:
        out.append(("DT", f"{dt:+.1f} s ({n_dt})", "ok" if abs(dt) <= DT_WARN_S else "warn" if abs(dt) <= DT_BAD_S else "bad"))
    if not gp:
        out.append(("GPSDO", "—", "none"))
    elif gp.get("error"):
        out.append(("GPSDO", "?", "warn"))
    else:
        ok = gp.get("gps_ok") and gp.get("pll_ok")
        out.append(("GPSDO", ("GPS ✓ · PLL lock ✓" if ok else f"GPS {'✓' if gp.get('gps_ok') else '✗'} · PLL {'✓' if gp.get('pll_ok') else '✗'}"),
                    "ok" if ok else "bad"))
    return out


_CSS = """<style>
.lv{display:flex;flex-wrap:wrap;gap:4px;font-size:12.5px}
.lv span{padding:2px 8px;border-radius:6px;background:rgba(127,127,127,.07);border:1px solid rgba(127,127,127,.35)}
.lv b{margin-left:4px;font-family:ui-monospace,Consolas,monospace}.lv i{opacity:.65;font-style:normal}
.lv .ok{border-color:#2ea04399;background:rgba(46,160,67,.08)}.lv .warn{border-color:#d29922;background:rgba(210,153,34,.12)}
.lv .bad{border-color:#f85149;background:rgba(248,81,73,.12)}
</style>"""


_KV_CSS = """<style>.kv{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:3px 12px;margin:2px 0 4px}
.kv div{line-height:1.12;min-width:0}.kv i{display:block;font-style:normal;font-size:11px;opacity:.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kv b{font-size:16px;font-family:ui-monospace,Consolas,monospace;font-weight:600;white-space:nowrap}</style>"""


def kv(pairs) -> None:
    """Compact grid of label/value pairs (st.metric truncates the longer values)."""
    cells = "".join("<div></div>" if p is None else f"<div><i>{html.escape(i18n.tr(p[0]))}</i><b>{html.escape(str(p[1]))}</b></div>"
                    for p in pairs)
    h = _KV_CSS + f"<div class='kv'>{cells}</div>"
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)


def strip_html(items) -> str:
    cells = "".join(f"<span class='{state}'><i>{html.escape(i18n.tr(lbl))}</i><b>{html.escape(str(val))}</b></span>"
                    for lbl, val, state in items)
    return _CSS + f"<div class='lv'>{cells}</div>"


# ------------------------------------------------------------------ page
def tab(D):
    """Sized to fit a full-HD screen (1920×1080, sidebar open) without scrolling: three columns."""
    sets = openems_local.load_settings()
    cfg = ui_camera.cfg_from_settings(D, sets)
    _html(_PAGE_CSS)
    left, right = st.container(key="lvgrid").columns([2.15, 1.25])
    with left:     # camera + corrections · DriverDish, watchdog, strip; underneath, the wide clock + frequency box
        q = st.container(key="lvin").columns([1.15, 1])
        with q[0].container(border=True):
            _camera_quadrant(D, sets, cfg)
        with q[1].container(border=True):
            _driverdish_quadrant(sets)
        with q[1].container(border=True):
            _watchdog_quadrant()
        with q[1].container(border=True):
            _bottom_strip()
        with st.container(border=True):
            _clock_quadrant()
    with right:    # the two stations · WSJT-X checks
        with st.container(border=True):
            _moon_quadrant(D)
        with st.container(border=True):
            _frag(2)(_wsjtx_checks_live)()


_PAGE_CSS = """<style>
.block-container{padding-top:3.9rem !important;padding-bottom:.3rem !important}
[data-testid='stVerticalBlockBorderWrapper']{padding:.55rem .75rem !important}
.st-key-lvgrid>div>[data-testid=stHorizontalBlock]>[data-testid=stColumn]>[data-testid=stVerticalBlock]>[data-testid=stLayoutWrapper]:last-child,
.st-key-lvin [data-testid=stColumn]>[data-testid=stVerticalBlock]>[data-testid=stLayoutWrapper]:last-child{flex-grow:1}
.st-key-lvgrid>div>[data-testid=stHorizontalBlock]>[data-testid=stColumn]>[data-testid=stVerticalBlock]>[data-testid=stLayoutWrapper]:last-child>div,
.st-key-lvin [data-testid=stColumn]>[data-testid=stVerticalBlock]>[data-testid=stLayoutWrapper]:last-child>div{height:100%}
.badge{padding:3px 10px;border-radius:6px;font-weight:600;font-size:14px;margin:2px 0;border:1px solid rgba(127,127,127,.35)}
.badge.ok{background:rgba(46,160,67,.10);border-color:#2ea043;color:#1a7f37}
.badge.warn{background:rgba(210,153,34,.12);border-color:#d29922;color:#9a6700}
.badge.bad{background:rgba(248,81,73,.12);border-color:#f85149;color:#cf222e}.badge.none{background:rgba(127,127,127,.07)}
</style>"""


def _html(h: str):
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)


def badge(text: str, state: str = "none"):
    """One-line coloured status (instead of the tall st.success / st.error boxes)."""
    _html(f"<div class='badge {state}'>{html.escape(i18n.tr(text))}</div>")


def dd_target_is_sun(d: dict | None) -> bool:
    """DriverDish is following the Sun (its «status» target)."""
    return str((d or {}).get("target", "")).strip().lower() in ("sun", "sole")


def _cam_toggled():
    on = bool(S.get("lv_cam_on"))
    openems_local.save_settings(cam_enabled=on)
    if not on:
        mt.stop()


def _camera_quadrant(D, sets, cfg):
    sun = dd_target_is_sun(dd_status()[0])
    t = st.columns([3, 1.2], vertical_alignment="center")
    t[0].markdown("**" + i18n.tr("☀️ Sole dalla telecamera" if sun else "📷 Luna dalla telecamera") + "**")
    S["lv_cam_on"] = bool(sets.get("cam_enabled"))          # follows the setting, also when changed in the camera tab
    t[1].toggle("Accesa", key="lv_cam_on", on_change=_cam_toggled,
                help="Accende o spegne la telecamera (come nella scheda 📷 Telecamera Astronomica); spenta, resta libera per ASICap")
    if sun:
        badge("Filtro solare sul cercatore prima di inquadrare il Sole: senza filtro il sensore si danneggia", "bad")
    if not sets.get("cam_enabled"):
        st.info("Telecamera spenta: accendila con l'interruttore qui sopra.")
        return
    if ui_camera.start_from_settings(sets) is None:
        st.warning("Telecamera non disponibile: controlla la scheda 📷 Telecamera Astronomica.")
        return
    _frag(float(sets.get("cam_refresh_s", 1.0)))(_camera_live)(cfg)


def _camera_live(cfg):
    from emelab import watchdog
    kind = openems_local.load_settings().get("cam_source", "asi")
    if kind in watchdog.CAM_NOT_REAL:
        badge(i18n.tr(watchdog.CAM_NOT_REAL[kind]), "warn")
    m = ui_camera.measure(cfg)
    if not m or m.get("frame") is None:
        st.info("In attesa del primo fotogramma dalla telecamera…")
        return
    off, alarm = m["off"], m["alarm"]
    img = mt.overlay(m["frame"], m["det"], m["ref"], m["tol"] / m["scale"], cfg["grid"] / m["scale"], alarm.active,
                     max_w=640, grid_deg=cfg["grid"])
    ih, iw = img.shape[:2] if hasattr(img, "shape") else (img.size[1], img.size[0])
    st.image(img, width=int(min(560, CAM_MAX_H * iw / ih)))        # at most CAM_MAX_H px high: the page fits the screen
    if alarm.active:
        badge("🚨 FUORI TRACKING" if alarm.reason == "out" else "🚨 LUNA PERSA: non è più nell'immagine", "bad")
    elif off and off["total_deg"] > m["tol"]:
        badge("⚠️ Fuori tolleranza", "warn")
    elif off:
        badge("✅ In tracking", "ok")
    else:
        badge("Luna non trovata nell'immagine", "warn")
    kv(([("Scostamento", f"{off['total_deg']:.3f}°"), ("Az", f"{off['az_deg']:+.3f}°"), ("El", f"{off['el_deg']:+.3f}°")]
        if off else []) + [("Soglia", f"{m['tol']:.3f}°")])
    ui_camera.alarm_feedback(m, cfg)
    corrections(off, "live")


def corrections(off: dict | None, prefix: str = "live"):
    """«Applica queste correzioni»: the camera offset sent to DriverDish as offset changes (emelab/rotor.py, with its
    limits). Off until enabled; manual only."""
    from emelab import rotor
    sets = openems_local.load_settings()
    on = st.toggle("🛠️ Correzioni al rotore (DriverDish)", bool(sets.get("rotor_enabled", False)), key=f"{prefix}_rot_on",
                   help="EMELab cambia solo gli offset di DriverDish (ao/eo), al massimo 0,25° per volta e sempre "
                        "entro ±0,5°: DriverDish continua a inseguire la Luna")
    if on != bool(sets.get("rotor_enabled", False)):
        openems_local.save_settings(rotor_enabled=on)
        rotor.reset_totals()
    if not on:
        return
    d, err = dd_status()
    host, port = sets.get("dd_host", "127.0.0.1"), int(sets.get("dd_port", 9999))
    if err == "off":
        st.warning("Accendi «🔴 Leggi in tempo reale» nella scheda 🎯 Tracking: senza lo stato di DriverDish non mando correzioni.")
        return
    p = rotor.plan(off["az_deg"], off["el_deg"], (d or {}).get("dish_el") or 0.0) if off else None
    if p and d:
        new_az, new_el = (d.get("off_az") or 0) + p["az"], (d.get("off_el") or 0) + p["el"]
        st.markdown(i18n.tr("Correzione proposta") + f": **Az {p['az']:+.3f}°** · **El {p['el']:+.3f}°** → "
                    + i18n.tr("offset di DriverDish") + f" Az {new_az:+.3f}° · El {new_el:+.3f}° (" + i18n.tr("limite") + " ±0,5°)")
        if abs(p["az_full"]) > rotor.MAX_STEP_DEG or abs(p["el_full"]) > rotor.MAX_STEP_DEG:
            st.caption("Scostamento grande: mando al massimo 0,25° per volta, ripremi dopo qualche secondo.")
    why = rotor.preflight(d)
    c = st.columns([3, 2])
    if c[0].button("✅ Applica queste correzioni", key=f"{prefix}_apply", type="primary", width="stretch",
                   disabled=bool(why) or not p):
        r = rotor.apply(p["az"], p["el"], d, host, port)
        (st.success if r["ok"] else st.error)((i18n.tr("Inviato a DriverDish") + ": " + " · ".join(r["sent"])) if r["ok"]
                                             else i18n.tr(r["error"]))
    if c[1].button("⏹️ STOP correzioni", key=f"{prefix}_stop", width="stretch"):
        rotor.stop()
        st.rerun()
    if why:
        st.caption("⏸️ " + i18n.tr(why))
    with st.expander(i18n.tr("Spostamenti a mano e registro")):
        c = st.columns(5)
        step = c[0].selectbox("Passo (°)", rotor.STEPS, index=1, key=f"{prefix}_step")
        for i, (lbl, ax, sg) in enumerate((("⬅️ Az−", "az", -1), ("➡️ Az+", "az", 1), ("⬆️ El+", "el", 1), ("⬇️ El−", "el", -1))):
            if c[i + 1].button(lbl, key=f"{prefix}_mv{i}", disabled=bool(why), width="stretch"):
                r = rotor.apply(sg * step if ax == "az" else 0.0, sg * step if ax == "el" else 0.0, d, host, port, reason="passo")
                (st.success if r["ok"] else st.error)(" · ".join(r["sent"]) if r["ok"] else i18n.tr(r["error"]))
        log = rotor.totals()["log"]
        if log:
            st.dataframe([{"UTC": e["utc"], "Tipo": e["reason"], "Comandi": " ".join(e["cmds"])} for e in reversed(log)],
                         hide_index=True, width="stretch")


def _driverdish_quadrant(sets):
    _frag(2)(_driverdish_live)()


def _driverdish_live():
    st.markdown("**" + i18n.tr("🛰️ DriverDish") + "**")
    d, err = dd_status()
    if err == "off":
        st.info("Lettura di DriverDish spenta: accendi «🔴 Leggi in tempo reale» nella scheda 🎯 Tracking.")
        return
    if not d:
        from emelab import watchdog
        st.warning(i18n.tr("DriverDish non risponde") + (f": {err}" if err else "")
                   + (" · " + i18n.tr(watchdog.TELNET_HINT) if watchdog.refused(err) else ""))
        return
    tracking = d.get("tracking")
    badge(f"{d.get('target', '—')} · " + ("TRACKING ON" if tracking else "TRACKING OFF")
          + (" · " + i18n.tr("in movimento") if d.get("moving") else ""), "ok" if tracking else "bad")
    f = lambda k, sg="": f"{d[k]:{sg}.3f}°" if isinstance(d.get(k), (int, float)) else "—"
    kv([("Antenna Az", f("dish_az")), ("Antenna El", f("dish_el")), ("Errore Az", f("err_az", "+")),
        ("Errore El", f("err_el", "+")), ("Offset Az", f("off_az", "+")), ("Offset El", f("off_el", "+"))])
    st.caption(i18n.tr("Obiettivo") + f" Az {d.get('target_az', float('nan')):.3f}° El {d.get('target_el', float('nan')):.3f}°"
               + (f" · {d['utc']:%H:%M:%S} UTC" if isinstance(d.get("utc"), datetime) else ""))


def watchdog_items(D=None) -> list[dict]:
    """Current state of the watchdogs (emelab/watchdog.py), from the readers already running (all read-only)."""
    from emelab import ui_wsjtx_panel, watchdog
    sets = openems_local.load_settings()
    svc = _svc()
    d, err = dd_status()
    mon_since = None
    try:
        if sets.get("dd_live"):
            from emelab import ui_tracking
            mon_since = ui_tracking._monitor(sets.get("dd_host", "127.0.0.1"), int(sets.get("dd_port", 9999))).error_since
    except Exception:
        pass
    clock = ui_wsjtx_panel.clock_state()
    live = _wsjtx_live(svc)
    dt, n = dt_median(svc) if live else (None, 0)
    probs = [p.get("msg", "") for p in (getattr(svc, "problems", None) or []) if not p.get("soft")] if live else []
    cam_on = bool(sets.get("cam_enabled"))
    src = mt.current() if cam_on else None
    age = (time.time() - src.latest()[1]) if src and src.latest()[0] is not None else None
    gp_on = bool(sets.get("gpsdo_use", True) and sets.get("gpsdo_ok_utc"))      # a GPSDO that has been seen working
    return watchdog.checks(gpsdo=gpsdo_state() if gp_on else None, gpsdo_on=gp_on,
                           dd=d, dd_err=None if err == "off" else err, dd_on=bool(sets.get("dd_live")), dd_err_since=mon_since,
                           wsjtx_on=bool(svc and svc.running), wsjtx_last=getattr(svc, "last_seen", None), wsjtx_problems=probs,
                           bkt=clock.get("bkt") if svc and svc.running else None, ntp=clock.get("ntp"), dt=dt if n >= 3 else None,
                           cam_on=cam_on, cam_age_s=age, cam_error=getattr(src, "error", None) if src else None,
                           cam_kind=sets.get("cam_source", "asi"))


_ICON = {"ok": "🟢", "warn": "🟡", "bad": "🔴"}


def _watchdog_quadrant():
    _frag(5)(_watchdog_live)()


def _watchdog_live():
    st.markdown("**" + i18n.tr("🐕 Watchdog") + "**")
    items = watchdog_items()
    if not items:
        st.info("Nessun controllo attivo: accendi GPSDO, DriverDish, WSJT-X o la telecamera nelle loro schede.")
        return
    rows = "".join(f"<div class='wd {i['state']}'><span>{_ICON[i['state']]}</span><b>{html.escape(i18n.tr(i['name']))}</b>"
                   f"<i>{html.escape(i18n.tr(i['msg']))}</i></div>" for i in items)
    h = ("<style>.wd{display:flex;gap:10px;align-items:baseline;padding:2px 8px;border-radius:6px;margin:2px 0;"
         "font-size:14px}.wd b{min-width:110px}.wd i{font-style:normal;opacity:.85}.wd.bad{background:#3a141622;"
         "border:1px solid #f85149}.wd.warn{border:1px solid #d29922}.wd.ok{border:1px solid #2ea04366}</style>" + rows)
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
    st.caption(i18n.tr("Controllo ogni 5 s; GPSDO letto ogni 20 s.") + f" {datetime.now(timezone.utc):%H:%M:%S} UTC")


def watchdog_sidebar(D):
    """Runs from the sidebar on every page (any tab open): camera alarm and «🚨 Watchdog» toasts."""
    _frag(5)(_watchdog_bg)(D)


def _watchdog_bg(D):
    from emelab import watchdog
    sets = openems_local.load_settings()
    if sets.get("cam_enabled") and mt.current() is not None:     # only a camera already open: never opened from here
        cfg = ui_camera.cfg_from_settings(D, sets)
        ui_camera.alarm_feedback(ui_camera.measure(cfg), cfg)       # the out-of-tracking alarm with any tab open
    items = watchdog_items(D)
    prev = S.setdefault("wd_prev", {})
    for i in watchdog.newly_bad(items, prev):
        _st.toast(watchdog.TOAST_PREFIX + i18n.tr(i["msg"]), icon="🚨")
    bad = [i for i in items if i["state"] == "bad"]
    if bad:
        st.error("🚨 " + " · ".join(i18n.tr(i["name"]) for i in bad))


def _moon_quadrant(D):
    _frag(2)(_moon_live)(D)


def dx_of(svc, D) -> tuple[str, str]:
    """(call, locator) of the station being worked: WSJT-X DX Call / DX Grid, the locator from the stations database
    when WSJT-X has none."""
    s = (svc.status or {}) if _wsjtx_live(svc) else {}
    call = (s.get("dx_call") or "").strip().upper()
    grid = (s.get("dx_grid") or "").strip()
    if call and len(grid) < 4:
        try:
            grid = ((D.station_of(call) or {}).get("locator") or grid)
        except Exception:
            pass
    return call, grid


_WX: dict = {}
WX_EVERY_S = 900


def weather_at(lat: float, lon: float) -> dict | None:
    """Open-Meteo now at a place, fetched in the background and kept 15 minutes (never blocks the page)."""
    key = (round(lat, 2), round(lon, 2))
    e = _WX.get(key)
    if (e is None or time.time() - e["t"] > WX_EVERY_S) and not (e or {}).get("busy"):
        _WX[key] = {**(e or {"wx": None}), "busy": True, "t": (e or {}).get("t", 0.0)}

        def run():
            try:
                from emelab import weather
                wx = weather.open_meteo(lat, lon, datetime.now(timezone.utc))
            except Exception:
                wx = (_WX.get(key) or {}).get("wx")
            _WX[key] = {"wx": wx, "t": time.time(), "busy": False}
        threading.Thread(target=run, daemon=True, name="emelab-live-wx").start()
    return (_WX.get(key) or {}).get("wx")


def station_view(now: datetime, me: tuple, other: tuple | None, f_ghz: float, h_me: float = 0.0,
                 h_other: float = 0.0, pol_me: str | None = None, pol_other: str | None = None) -> dict:
    """What one station sees now: Moon Az/El, distance, own echo Doppler and spread, polarisation angle and Dpol
    towards the other station, mutual spread/Doppler/libration and the Earth–Moon–Earth path (pure: no Streamlit)."""
    from emelab import astro, dx
    sk = astro.sky(now, me[0], me[1], h_me)
    own = astro.mutual(now, me, me, h_me, h_me)
    v = {"az": sk.moon.az, "el": sk.moon.el, "dist_km": sk.moon.dist_km, "sun_moon": sk.sun_moon_deg,
         "dop_echo_hz": sk.doppler_hz_per_ghz * f_ghz * 1e0, "spread_echo_hz": sk.spread_hz_per_ghz * f_ghz,
         "lib_echo": own["libration_deg_per_min"], "pol": dx.pol_angle(me[0], sk.moon.az, sk.moon.el)}
    if other:
        so = astro.sky(now, other[0], other[1], h_other)
        mu = astro.mutual(now, me, other, h_me, h_other)
        p_o = dx.pol_angle(other[0], so.moon.az, so.moon.el)
        dpol = dx.spatial_pol_offset(v["pol"], p_o)
        pm, po = pol_me or dx.default_pol(*me), pol_other or dx.default_pol(*other)
        mis = dx.pol_mismatch_deg(dpol, pm, po)
        path = sk.moon.dist_km + so.moon.dist_km
        v.update(dpol=dpol, pol_loss_db=dx.pol_loss_db(mis), pols=f"{pm}/{po}", spread_mutual_hz=mu["spread_hz_per_ghz"] * f_ghz,
                 dop_path_hz=mu["doppler_hz_per_ghz"] * f_ghz, lib_mutual=mu["libration_deg_per_min"],
                 path_km=path, delay_s=path / 299792.458, other_el=so.moon.el)
    return v


def _moon_live(D):
    from emelab import astro, tz
    now = datetime.now(timezone.utc)
    stn = D.station() or {}
    svc = _svc()
    hz = ((svc.status or {}).get("dial_hz") if _wsjtx_live(svc) else None)
    f_ghz = hz / 1e9 if hz else float(openems_local.load_settings().get("cam_band_ghz", 24.048))
    call, grid = dx_of(svc, D)
    if not stn.get("lat"):
        st.info("Inserisci il locator nella scheda 🏠 Stazione per vedere la Luna.")
        return
    me = (stn["lat"], stn["lon"])
    other = None
    if len(grid) >= 4:
        try:
            other = astro.locator_to_latlon(grid)
        except Exception:
            other = None
    v = station_view(now, me, other, f_ghz, stn.get("height_m") or 0.0)
    band = stations.band_label(f_ghz)
    _panel(f"{stn.get('callsign') or '—'} · {stn.get('locator') or ''}", "#1f6feb",
           v, me, now, band, towards=call or "DX")
    if other:
        vo = station_view(now, other, me, f_ghz)
        _panel(f"{call or '—'} · {grid[:6]}", "#e8590c", vo, other, now, band,
               towards=stn.get("callsign") or i18n.tr("me"))
        _heading(f"{stn.get('callsign') or '—'} ↔ {call or '—'}", "#8b949e")
        kv(common_pairs(v))
        st.caption(i18n.tr("Percorso Terra–Luna–Terra") + f" {v['path_km']:,.0f} km · " + i18n.tr("ritardo")
                   + f" {v['delay_s']:.3f} s · " + i18n.tr("polarizzazioni") + f" {v['pols']}")
    else:
        st.caption("Il riquadro del DX compare quando WSJT-X ha un DX Call con il locator (o il locator è nel "
                   "database delle stazioni).")


def weather_pairs(wx: dict) -> list[tuple[str, str]]:
    """Temperature, humidity and whether it rains (pure)."""
    f = lambda k, fmt: format(wx[k], fmt) if isinstance(wx.get(k), (int, float)) else "—"
    rain = wx.get("rain_mmh")
    wet = isinstance(rain, (int, float)) and rain >= 0.1
    return [("Temperatura", f"{f('t_c', '.0f')} °C"), ("Umidità", f"{f('rh', '.0f')} %"),
            ("Pioggia", "—" if rain is None else (i18n.tr("sì") + f" · {rain:.1f} mm/h" if wet else i18n.tr("no")))]


def _clock_quadrant():
    _frag(1)(_clock_live)()


def _clock_live():
    now = datetime.now(timezone.utc)
    svc = _svc()
    stt = (svc.status or {}) if _wsjtx_live(svc) else {}
    hz = stt.get("dial_hz")
    mode = next((v for k, v, _ in strip_items(stt, None, None, None, None, 0, None) if k == "Modo"), "—")
    mono = "font-family:ui-monospace,Consolas,monospace;font-weight:700"
    _html("<div style='display:grid;grid-template-columns:1fr 1.25fr;align-items:center;text-align:center;height:100%'>"
          f"<div><span style='{mono};font-size:44px;line-height:1.0'>{now:%H:%M:%S}</span>"
          f"<span style='font-size:18px;opacity:.75'> UTC</span>"
          f"<div style='font-size:17px;opacity:.75'>{html.escape(_date_it(now))}</div></div>"
          f"<div style='border-left:1px solid rgba(127,127,127,.35)'>"
          f"<span style='{mono};font-size:44px;line-height:1.0;white-space:nowrap'>{_mhz(hz)[:-3] if hz else '—'}</span>"
          f"<span style='font-size:18px;opacity:.75'> MHz</span>"
          f"<div style='{mono};font-size:22px;color:#1f6feb'>{html.escape(mode)}</div></div></div>")


def _date_it(d: datetime) -> str:
    if i18n.get_lang() == "en":
        return f"{d:%a %d %b %Y}"
    days = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
    months = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
    return f"{days[d.weekday()]} {d.day} {months[d.month - 1]} {d.year}"


def panel_pairs(v: dict, local: str, towards: str, wx: dict | None) -> list:
    """The same fields in the same places for both stations (pure): 3 per row, None = empty cell."""
    g = lambda k, fmt: format(v[k], fmt) if isinstance(v.get(k), (int, float)) else "—"
    w = weather_pairs(wx) if wx else [("Temperatura", "—"), ("Umidità", "—"), ("Pioggia", "—")]
    return [("Ora locale", local), ("Luna Az", g("az", ".1f") + "°"), ("Luna El", g("el", ".1f") + "°"),
            ("Distanza Luna", g("dist_km", ",.0f") + " km"), ("Sole–Luna", g("sun_moon", ".0f") + "°"),
            (i18n.tr("Dpol verso") + f" {towards}", g("dpol", "+.0f") + "°"),
            *w]


def common_pairs(v: dict) -> list:
    """What both stations share (pure): polarisation loss, mutual spread and libration."""
    g = lambda k, fmt: format(v[k], fmt) if isinstance(v.get(k), (int, float)) else "—"
    return [("Perdita di polarizzazione", g("pol_loss_db", ".1f") + " dB"), ("Spread reciproco", g("spread_mutual_hz", ".0f") + " Hz"),
            ("Librazione reciproca", g("lib_mutual", ".3f") + "°/min")]


def _heading(title: str, color: str):
    _html(f"<div style='border-left:6px solid {color};padding:2px 10px;margin:4px 0 2px;font-size:16px;font-weight:700'>"
          f"{html.escape(title)}</div>")


def _panel(title, color, v, ll, now, band, towards="DX"):
    from emelab import tz
    loc, zone, _ = tz.local_time(ll[0], ll[1], now)
    _heading(title, color)
    pairs = panel_pairs(v, f"{loc:%H:%M} ({zone.split('/')[-1]})", towards, weather_at(*ll))
    kv(pairs)


def _wsjtx_checks_live():
    """The same control check as the 📻 WSJT-X tab (preset of the band vs WSJT-X now), without its buttons."""
    from emelab import ui_wsjtx_panel
    st.markdown("**" + i18n.tr("📻 Controllo di WSJT-X") + "**")
    svc = _svc()
    if not _wsjtx_live(svc):
        st.info("WSJT-X non collegato: attiva l'ascolto UDP nella scheda 📻 WSJT-X.")
        return
    band = ui_wsjtx_panel._band(svc)
    if not band:
        st.caption("WSJT-X non è su una banda EME (10 GHz e oltre).")
        return
    rows = ui_wsjtx_panel.check_rows(svc, openems_local.load_settings(), band)
    ini = ui_wsjtx_panel.ini_state(openems_local.load_settings())
    st.caption(stations.band_label(band) + " · " + i18n.tr("✅ come il preset · ⚠️ diverso dal preset · ❔ WSJT-X non lo manda: confermalo tu")
               + (" · " + i18n.tr("(WSJT-X.ini) = dal file salvato alle") + f" {ini['saved']:%H:%M} UTC; "
                  + i18n.tr("WSJT-X lo riscrive quando chiudi la finestra Astro o WSJT-X") if ini.get("saved") else ""))
    cells = "".join(f"<span class='{'bad' if r['Stato'] == ui_wsjtx_panel.BAD else 'ok' if r['Stato'] == ui_wsjtx_panel.OK else ''}'>"
                    f"<i>{html.escape(i18n.tr(r['Parametro']))}</i><b>{html.escape(str(r['WSJT-X adesso']))}</b> {r['Stato']}</span>"
                    for r in rows)
    h = _CSS + f"<div class='lv'>{cells}</div>"
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)


def _bottom_strip():
    _frag(2)(_bottom_live)()


def _bottom_live():
    from emelab import ui_wsjtx_panel
    svc = _svc()
    sets = openems_local.load_settings()
    live = _wsjtx_live(svc)
    clock = ui_wsjtx_panel.clock_state()
    dt, n = dt_median(svc) if live else (None, 0)
    items = strip_items(svc.status if live else None, ui_wsjtx_panel.ini_state(sets), clock.get("bkt"), clock.get("ntp"),
                        dt, n, gpsdo_state())
    h = strip_html(items)
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)
    if not live:
        st.caption("WSJT-X non collegato: Sked, TX, RX, modo e F Tol arrivano via UDP; Split, 1st/2nd e Doppler da WSJT-X.ini.")
