# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Watchdogs of the things that must work while operating (asked by Ivan IZ0JNY): GPSDO locked, DriverDish answering
and tracking, WSJT-X sending its status, BktTimeSync with the PC clock and DT in range, camera giving frames.

`checks()` is a pure function of the states read elsewhere (read-only); a check is skipped (None) when that part is
not in use. The page runs it every few seconds from the sidebar, so the alarms appear whatever tab is open, and
raises a toast «🚨 Watchdog: …» when a check turns bad."""
from __future__ import annotations

from datetime import datetime, timezone

DD_GRACE_S = 10.0
GPSDO_LOSS_WARN_S = 600.0
WSJTX_SILENT_S = 40.0                # WSJT-X sends a heartbeat every 15 s
CAM_STALE_S = 5.0
DT_WARN_S, DT_BAD_S = 0.5, 1.0
TOAST_PREFIX = "🚨 Watchdog: "
CAM_NOT_REAL = {"sim": "simulatore: la telecamera vera non è in uso",
                "still": "immagine da file: la telecamera vera non è in uso"}
TELNET_HINT = "in DriverDish accendi Setup → Telnet server, porta 9999, «Run»"


def no_fix(pvt: dict | None) -> bool:
    """The GPS receiver of the GPSDO has no 3D fix (UBX-NAV-PVT). The Leo Bodnar «GPS lock» bit stays on for a long
    time after the antenna is lost (holdover), so the fix is the reliable sign."""
    if not pvt:
        return False
    return not pvt.get("fix_ok") or (pvt.get("fix_type") or 0) < 3 or (pvt.get("sats_used") or 0) < 4


def refused(err: str | None) -> bool:
    """Connection refused: DriverDish (or its telnet server) is not listening."""
    e = (err or "").lower()
    return "10061" in e or "refused" in e or "errno 111" in e


def checks(*, now: datetime | None = None, gpsdo: dict | None = None, gpsdo_on: bool = False,
           dd: dict | None = None, dd_err: str | None = None, dd_on: bool = False, dd_err_since: datetime | None = None,
           wsjtx_on: bool = False, wsjtx_last: datetime | None = None, wsjtx_problems: list | None = None,
           bkt: dict | None = None, ntp: dict | None = None, dt: float | None = None,
           cam_on: bool = False, cam_age_s: float | None = None, cam_error: str | None = None,
           cam_kind: str = "asi") -> list[dict]:
    """[{"key", "name", "state": ok/warn/bad, "msg"}] for the parts in use."""
    now = now or datetime.now(timezone.utc)
    out = []

    def add(key, name, state, msg):
        out.append({"key": key, "name": name, "state": state, "msg": msg})

    if gpsdo_on:
        if gpsdo is None:
            add("gpsdo", "GPSDO", "warn", "lettura in corso")
        elif gpsdo.get("error"):
            add("gpsdo", "GPSDO", "bad", "GPSDO non letto: " + gpsdo["error"])
        elif no_fix(gpsdo.get("pvt")):
            add("gpsdo", "GPSDO", "bad", f"GPS senza fix ({gpsdo['pvt'].get('sats_used', 0)} satelliti): antenna staccata o "
                                          "cielo coperto, il GPSDO va in holdover")
        elif not (gpsdo.get("gps_ok") and gpsdo.get("pll_ok")):
            add("gpsdo", "GPSDO", "bad", f"GPSDO non agganciato (GPS {'OK' if gpsdo.get('gps_ok') else 'NO'}, "
                                          f"PLL {'OK' if gpsdo.get('pll_ok') else 'NO'})")
        elif gpsdo.get("loss_utc") and (now - gpsdo["loss_utc"]).total_seconds() < GPSDO_LOSS_WARN_S:
            add("gpsdo", "GPSDO", "warn", "aggancio perso e ritrovato negli ultimi 10 minuti")
        else:
            add("gpsdo", "GPSDO", "ok", "GPS e PLL agganciati")
    if dd_on:
        if not dd:
            late = dd_err_since is None or (now - dd_err_since).total_seconds() >= DD_GRACE_S
            add("driverdish", "DriverDish", "bad" if late else "warn", "DriverDish non risponde" + (f": {dd_err}" if dd_err else "")
                + (" · " + TELNET_HINT if refused(dd_err) else ""))
        elif dd.get("tracking") is False:
            add("driverdish", "DriverDish", "bad", "DriverDish non insegue (TRACKING OFF)")
        else:
            add("driverdish", "DriverDish", "ok", f"TRACKING ON · {dd.get('target', '')}".strip(" ·"))
    if wsjtx_on:
        age = (now - wsjtx_last).total_seconds() if wsjtx_last else None
        if age is None or age > WSJTX_SILENT_S:
            add("wsjtx", "WSJT-X", "bad", "WSJT-X non manda lo stato via UDP" + (f" da {age:.0f} s" if age else ""))
        elif wsjtx_problems:
            add("wsjtx", "WSJT-X", "warn", "WSJT-X diverso dal preset: " + ", ".join(wsjtx_problems[:3]))
        else:
            add("wsjtx", "WSJT-X", "ok", "stato ricevuto, come il preset")
    if bkt and bkt.get("running") is not None:
        if not bkt["running"]:
            add("bkt", "BktTimeSync", "bad", "BktTimeSync non è in esecuzione")
        else:
            off = (ntp or {}).get("offset_s")
            if off is not None and abs(off) > DT_BAD_S:
                add("bkt", "BktTimeSync", "bad", f"orologio del PC fuori di {off:+.2f} s")
            elif off is not None and abs(off) > DT_WARN_S:
                add("bkt", "BktTimeSync", "warn", f"orologio del PC fuori di {off:+.2f} s")
            else:
                add("bkt", "BktTimeSync", "ok", "in esecuzione" + (f", orologio {off:+.2f} s" if off is not None else ""))
    if dt is not None:
        st = "ok" if abs(dt) <= DT_WARN_S else "warn" if abs(dt) <= DT_BAD_S else "bad"
        add("dt", "DT", st, f"DT medio {dt:+.1f} s")
    if cam_on:
        if cam_kind in CAM_NOT_REAL:
            add("camera", "Telecamera", "warn", CAM_NOT_REAL[cam_kind])
        elif cam_error and (cam_age_s is None or cam_age_s > CAM_STALE_S):
            add("camera", "Telecamera", "bad", "telecamera: " + cam_error)
        elif cam_age_s is None:
            add("camera", "Telecamera", "warn", "in attesa del primo fotogramma")
        elif cam_age_s > CAM_STALE_S:
            add("camera", "Telecamera", "bad", f"nessun fotogramma da {cam_age_s:.0f} s")
        else:
            add("camera", "Telecamera", "ok", "fotogrammi regolari")
    return out


def newly_bad(items: list[dict], prev: dict) -> list[dict]:
    """Checks that turned bad since the previous run (prev = {key: state}, updated in place)."""
    out = [i for i in items if i["state"] == "bad" and prev.get(i["key"]) != "bad"]
    prev.clear()
    prev.update({i["key"]: i["state"] for i in items})
    return out
