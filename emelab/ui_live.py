# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🔴 Live: everything needed while operating, on one page.

Four quadrants (Moon from the camera with the offset and the rotor corrections · DriverDish · WSJT-X decodes ·
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
GPSDO_EVERY_S = 60
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


_GPSDO = {"last": None, "t": 0.0, "busy": False}


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
                _GPSDO["last"] = gpsdo.read_leo_bodnar(seconds=2.5, satellites=False)
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
.lv{display:flex;flex-wrap:wrap;gap:6px;font-family:ui-monospace,Consolas,monospace;font-size:14px}
.lv span{padding:4px 8px;border-radius:6px;background:#1e2633;color:#e6edf3;border:1px solid #334}
.lv b{margin-left:4px}.lv .ok{border-color:#2ea043;background:#12261a}.lv .warn{border-color:#d29922;background:#2a2210}
.lv .bad{border-color:#f85149;background:#3a1416}.lv i{color:#9aa7b4;font-style:normal}
</style>"""


_KV_CSS = """<style>.kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px 14px;margin:4px 0 8px}
.kv div{line-height:1.15}.kv i{display:block;font-style:normal;font-size:12px;opacity:.7}
.kv b{font-size:20px;font-family:ui-monospace,Consolas,monospace;font-weight:600}</style>"""


def kv(pairs) -> None:
    """Compact grid of label/value pairs (st.metric truncates the longer values)."""
    cells = "".join(f"<div><i>{html.escape(i18n.tr(k))}</i><b>{html.escape(str(v))}</b></div>" for k, v in pairs)
    h = _KV_CSS + f"<div class='kv'>{cells}</div>"
    st.html(h) if hasattr(_st, "html") else _st.markdown(h, unsafe_allow_html=True)


def strip_html(items) -> str:
    cells = "".join(f"<span class='{state}'><i>{html.escape(i18n.tr(lbl))}</i><b>{html.escape(str(val))}</b></span>"
                    for lbl, val, state in items)
    return _CSS + f"<div class='lv'>{cells}</div>"


# ------------------------------------------------------------------ page
def tab(D):
    st.subheader("🔴 Live")
    sets = openems_local.load_settings()
    cfg = ui_camera.cfg_from_settings(D, sets)
    q = st.columns(2)
    with q[0].container(border=True):
        _camera_quadrant(D, sets, cfg)
    with q[1].container(border=True):
        _driverdish_quadrant(sets)
    q = st.columns(2)
    with q[0].container(border=True):
        _decodes_quadrant()
    with q[1].container(border=True):
        _moon_quadrant(D)
    with st.container(border=True):
        _bottom_strip()


def _camera_quadrant(D, sets, cfg):
    st.markdown("**" + i18n.tr("📷 Luna dalla telecamera") + "**")
    if not sets.get("cam_enabled"):
        st.info("Telecamera spenta: accendila nella scheda 📷 Telecamera Astronomica.")
        return
    if ui_camera.start_from_settings(sets) is None:
        st.warning("Telecamera non disponibile: controlla la scheda 📷 Telecamera Astronomica.")
        return
    _frag(float(sets.get("cam_refresh_s", 1.0)))(_camera_live)(cfg)


def _camera_live(cfg):
    m = ui_camera.measure(cfg)
    if not m or m.get("frame") is None:
        st.info("In attesa del primo fotogramma dalla telecamera…")
        return
    off, alarm = m["off"], m["alarm"]
    img = mt.overlay(m["frame"], m["det"], m["ref"], m["tol"] / m["scale"], cfg["grid"] / m["scale"], alarm.active,
                     max_w=640, grid_deg=cfg["grid"])
    st.image(img, width="stretch")
    if alarm.active:
        st.error("🚨 FUORI TRACKING" if alarm.reason == "out" else "🚨 LUNA PERSA: non è più nell'immagine")
    elif off and off["total_deg"] > m["tol"]:
        st.warning("⚠️ Fuori tolleranza")
    elif off:
        st.success("✅ In tracking")
    else:
        st.warning("Luna non trovata nell'immagine")
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
        st.warning(i18n.tr("DriverDish non risponde") + (f": {err}" if err else ""))
        return
    tracking = d.get("tracking")
    (st.success if tracking else st.error)(f"{d.get('target', '—')} · " + ("TRACKING ON" if tracking else "TRACKING OFF")
                                           + (" · " + i18n.tr("in movimento") if d.get("moving") else ""))
    f = lambda k, sg="": f"{d[k]:{sg}.3f}°" if isinstance(d.get(k), (int, float)) else "—"
    kv([("Antenna Az", f("dish_az")), ("Antenna El", f("dish_el")), ("Errore Az", f("err_az", "+")),
        ("Errore El", f("err_el", "+")), ("Offset Az", f("off_az", "+")), ("Offset El", f("off_el", "+"))])
    st.caption(i18n.tr("Obiettivo") + f" Az {d.get('target_az', float('nan')):.3f}° El {d.get('target_el', float('nan')):.3f}°"
               + (f" · {d['utc']:%H:%M:%S} UTC" if isinstance(d.get("utc"), datetime) else ""))


def _decodes_quadrant():
    _frag(2)(_decodes_live)()


def _decodes_live():
    st.markdown("**" + i18n.tr("📻 WSJT-X: ultime decodifiche") + "**")
    svc = _svc()
    if not _wsjtx_live(svc):
        st.info("WSJT-X non collegato: attiva l'ascolto UDP nella scheda 📻 WSJT-X.")
        return
    rows = [{"UTC": f"{d['utc']:%H:%M}", "dB": d["snr"], "DT": round(d["dt"], 1), "DF": d["df"], "Messaggio": d["message"]}
            for d in list(svc.recent)[:8]]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch", height=300)
    else:
        st.caption("Ancora nessuna decodifica.")


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


def _moon_live(D):
    from emelab import astro, moon
    st.markdown("**" + i18n.tr("🌕 Luna, stazione collegata e orologio") + "**")
    now = datetime.now(timezone.utc)
    stn = D.station() or {}
    svc = _svc()
    hz = ((svc.status or {}).get("dial_hz") if _wsjtx_live(svc) else None)
    f_ghz = hz / 1e9 if hz else float(openems_local.load_settings().get("cam_band_ghz", 24.048))
    call, grid = dx_of(svc, D)
    kv([("UTC", f"{now:%H:%M:%S}"), ("Frequenza WSJT-X", f"{hz / 1e6:,.3f} MHz".replace(",", " ") if hz else "—"),
        ("DX", (call or "—") + (f" {grid[:6]}" if grid else ""))])
    if not stn.get("lat"):
        st.info("Inserisci il locator nella scheda 🏠 Stazione per vedere la Luna.")
        return
    h = stn.get("height_m") or 0.0
    sk = astro.sky(now, stn["lat"], stn["lon"], h)
    lib_l, lib_b = moon.libration(now)
    kv([("Luna Az", f"{sk.moon.az:.2f}°"), ("Luna El", f"{sk.moon.el:.2f}°"),
        (i18n.tr("Doppler eco") + f" {stations.band_label(f_ghz)}", f"{sk.doppler_hz_per_ghz * f_ghz / 1000:+.2f} kHz"),
        ("Librazione lon / lat", f"{lib_l:+.2f}° / {lib_b:+.2f}°")])
    dx_ll = None
    if len(grid) >= 4:
        try:
            dx_ll = astro.locator_to_latlon(grid)
        except Exception:
            dx_ll = None
    if dx_ll:
        mu = astro.mutual(now, (stn["lat"], stn["lon"]), dx_ll, h, 0.0)
        dsk = astro.sky(now, dx_ll[0], dx_ll[1], 0.0)
        kv([("Spread reciproco", f"{mu['spread_hz_per_ghz'] * f_ghz:.0f} Hz"),
            (i18n.tr("Doppler verso") + f" {call or 'DX'}", f"{mu['doppler_hz_per_ghz'] * f_ghz / 1000:+.2f} kHz"),
            (i18n.tr("Luna da") + f" {call or 'DX'}", f"El {dsk.moon.el:.1f}° Az {dsk.moon.az:.1f}°")])
        st.caption(i18n.tr("Librazione reciproca") + f" {mu['libration_deg_per_min']:.3f}°/min · "
                   + i18n.tr("spread proprio") + f" {sk.spread_hz_per_ghz * f_ghz:.0f} Hz · " + i18n.tr("Distanza")
                   + f" {sk.moon.dist_km:,.0f} km · RA {moon.ra_hms(sk.moon.ra)} Dec {moon.dec_dms(sk.moon.dec)}")
    else:
        st.caption(i18n.tr("spread proprio") + f" {sk.spread_hz_per_ghz * f_ghz:.0f} Hz · " + i18n.tr("Distanza")
                   + f" {sk.moon.dist_km:,.0f} km · RA {moon.ra_hms(sk.moon.ra)} Dec {moon.dec_dms(sk.moon.dec)} · "
                   + i18n.tr("lo spread reciproco compare quando WSJT-X ha un DX Call con il locator"))


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
