# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Rotor corrections from the camera, through DriverDish's offsets (the ONLY place where EMELab moves the dish).

Asked by Ivan IZ0JNY (25-11-2026) for the 📷 camera and 🔴 Live tabs. DriverDish keeps tracking the Moon; EMELab
only adds small amounts to its offsets with the telnet commands «ao+xx», «ao-xx», «eo+xx», «eo-xx» (DriverDishServer
2.022 help: «[ao][eo]+xx = Add +xx degrees to offset»). Absolute moves («az+xx», «el-xx»), «tracking on/off» and
«stop» are never sent from here.

Safeguards (all checked before every command, whatever the caller asks):
* off unless enabled in the settings (``rotor_enabled``); manual only («Applica queste correzioni»), no automatic loop;
* at most MAX_STEP_DEG per command, and the resulting DriverDish offset must stay within ±OFFSET_LIMIT_DEG
  (Ivan's limit, AZ and EL, read from DriverDish's «status» just before sending);
* at least MIN_INTERVAL_S between two commands;
* DriverDish must answer, be in TRACKING ON and not already moving;
* every command is written to rotor_log.csv in EMELab's settings folder.

The camera measures offsets on the sky (cross-elevation); the azimuth offset of the dish is that divided by
cos(elevation)."""
from __future__ import annotations

import math
import re
import socket
import threading
import time
from datetime import datetime, timezone

from emelab import ea3hmj
from emelab import settings as openems_local

MAX_STEP_DEG = 0.25              # per press of «Applica queste correzioni»
OFFSET_LIMIT_DEG = 0.5           # Ivan: DriverDish offsets must stay within −0.5° … +0.5° on AZ and EL
MIN_INTERVAL_S = 3.0
MIN_STEP_DEG = 0.001
STEPS = (0.005, 0.01, 0.02, 0.05)

_CMD_RX = re.compile(r"^(ao|eo)([+-])(\d+\.\d{3})$")
_lock = threading.Lock()
_state = {"last_t": 0.0, "added_az": 0.0, "added_el": 0.0, "log": []}


def command(axis: str, delta_deg: float) -> str:
    """'az' → «ao±x.xxx», 'el' → «eo±x.xxx» (offset change in degrees of the dish axis)."""
    key = {"az": "ao", "el": "eo"}[axis]
    return f"{key}{'+' if delta_deg >= 0 else '-'}{abs(delta_deg):.3f}"


def check_command(cmd: str) -> str:
    """Only offset additions within the step limit go out; anything else raises ValueError."""
    m = _CMD_RX.match(cmd.strip())
    if not m:
        raise ValueError(f"comando non permesso: {cmd!r}")
    if float(m.group(3)) > MAX_STEP_DEG + 1e-9:
        raise ValueError(f"passo oltre {MAX_STEP_DEG}°: {cmd!r}")
    return cmd.strip()


def az_axis_from_sky(cross_el_deg: float, el_deg: float) -> float:
    """Azimuth-axis change that moves the beam by cross_el_deg on the sky at elevation el_deg (capped at 80°)."""
    return cross_el_deg / math.cos(math.radians(min(abs(el_deg), 80.0)))


def plan(off_az_sky: float, off_el: float, el_deg: float) -> dict:
    """Offset changes to bring the radio centre onto the Moon: the camera says the Moon is off_az_sky to the right
    and off_el higher → add those (azimuth converted to the axis), each clipped to MAX_STEP_DEG."""
    daz = az_axis_from_sky(off_az_sky, el_deg)
    clip = lambda v: max(-MAX_STEP_DEG, min(MAX_STEP_DEG, v))
    return {"az": round(clip(daz), 3), "el": round(clip(off_el), 3), "az_full": daz, "el_full": off_el}


def enabled() -> bool:
    return bool(openems_local.load_settings().get("rotor_enabled", False))


def reset_totals():
    with _lock:
        _state.update(added_az=0.0, added_el=0.0)


def stop():
    """⏹️ STOP: corrections off at once (DriverDish keeps tracking as it is)."""
    openems_local.save_settings(rotor_enabled=False)
    reset_totals()


def totals() -> dict:
    return {"az": _state["added_az"], "el": _state["added_el"], "last_t": _state["last_t"], "log": list(_state["log"][-20:])}


def preflight(status: dict | None, now: float | None = None) -> str | None:
    """Why a correction cannot go out now (Italian, for the interface), or None."""
    now = time.time() if now is None else now
    if not enabled():
        return "correzioni al rotore spente"
    if not status:
        return "DriverDish non risponde"
    if status.get("tracking") is not True:
        return "DriverDish non è in TRACKING ON"
    if status.get("moving"):
        return "il rotore si sta già muovendo"
    if now - _state["last_t"] < MIN_INTERVAL_S:
        return f"attendi {MIN_INTERVAL_S - (now - _state['last_t']):.0f} s fra una correzione e l'altra"
    return None


def apply(daz: float, d_el: float, status: dict | None, host: str = "127.0.0.1", port: int = 9999,
          reason: str = "manuale", send=None) -> dict:
    """Send the offset changes (axis degrees). Returns {"ok", "sent": [...], "error"}. `send` replaces the telnet
    connection in tests."""
    with _lock:
        why = preflight(status)
        if why:
            return {"ok": False, "sent": [], "error": why}
        cmds = []
        for axis, d, key in (("az", daz, "added_az"), ("el", d_el, "added_el")):
            d = max(-MAX_STEP_DEG, min(MAX_STEP_DEG, round(d, 3)))
            if abs(d) < MIN_STEP_DEG:
                continue
            cur = status.get("off_" + axis)
            if cur is None:
                return {"ok": False, "sent": [], "error": f"offset {axis.upper()} di DriverDish non letto"}
            if abs(cur + d) > OFFSET_LIMIT_DEG + 1e-9:
                return {"ok": False, "sent": [], "error": f"l'offset {axis.upper()} di DriverDish andrebbe a {cur + d:+.3f}°, "
                                                            f"oltre ±{OFFSET_LIMIT_DEG}°: controlla puntamento e allineamento "
                                                            "della telecamera"}
            cmds.append((axis, d, key, check_command(command(axis, d))))
        if not cmds:
            return {"ok": True, "sent": [], "error": None}
        try:
            answers = (send or _send)([c[3] for c in cmds], host, port)
        except OSError as e:
            return {"ok": False, "sent": [], "error": f"DriverDish non raggiungibile: {e}"}
        now = time.time()
        _state["last_t"] = now
        for axis, d, key, cmd in cmds:
            _state[key] += d
        entry = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "reason": reason,
                 "cmds": [c[3] for c in cmds], "answers": answers,
                 "off_before": (status.get("off_az"), status.get("off_el"))}
        _state["log"].append(entry)
        _log(entry)
        return {"ok": True, "sent": [c[3] for c in cmds], "error": None}


def _send(cmds: list[str], host: str, port: int) -> list[str]:
    out = []
    with socket.create_connection((host, port), timeout=4.0) as s:
        ea3hmj._read_until_quiet(s, quiet=0.3, total=1.5)           # banner
        for c in cmds:
            s.sendall((check_command(c) + "\r\n").encode())
            out.append(ea3hmj._read_until_quiet(s, quiet=0.25, total=2.0).decode("utf-8", "replace").strip())
        try:
            s.sendall(b"exit\r\n")
        except OSError:
            pass
    return out


def _log(entry: dict):
    try:
        p = openems_local.config_dir() / "rotor_log.csv"
        new = not p.exists()
        with p.open("a", encoding="utf-8") as f:
            if new:
                f.write("utc;reason;commands;answers;offset_before_az;offset_before_el\n")
            f.write(f"{entry['utc']};{entry['reason']};{' '.join(entry['cmds'])};{' | '.join(entry['answers'])};"
                    f"{entry['off_before'][0]};{entry['off_before'][1]}\n")
    except OSError:
        pass
