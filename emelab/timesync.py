# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""PC clock check for WSJT-X: is BktTimeSync (IZ2BKT) running, and how far is the PC clock from an NTP server.

Q65/JT decoding needs the PC clock within a few tenths of a second (WSJT-X DT): beyond ±0.5 s decodes start to
suffer, beyond ±1 s they drop. EMELab only looks: it lists the running processes and sends one SNTP query
(UDP 123). It never changes the system time nor BktTimeSync's settings."""
from __future__ import annotations

import os
import re
import socket
import struct
import subprocess
import time

NTP_SERVER = "pool.ntp.org"
WARN_S = 0.5                     # |offset| above this: warning
BAD_S = 1.0                      # |offset| above this: decodes drop
PROCESS_RE = re.compile(r"bkt\s*_?time\s*_?sync(?!\s*_?gps)", re.I)     # BktTimeSync.exe, not the BktTimeSyncGPS box
_NTP_EPOCH = 2_208_988_800       # 1900-01-01 → 1970-01-01


def find_process(names: list[str]) -> str | None:
    """The first process name that looks like BktTimeSync, or None."""
    return next((n for n in names if PROCESS_RE.search(n)), None)


def process_names() -> list[str] | None:
    """Names of the running processes (Windows: tasklist), None where it cannot be read."""
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None
    return [ln.split('","')[0].strip('"') for ln in r.stdout.splitlines() if ln.startswith('"')]


def bkt_running() -> dict:
    """{"running": True/False/None, "process": name or None}; None = cannot be checked (not Windows)."""
    names = process_names()
    if names is None:
        return {"running": None, "process": None}
    p = find_process(names)
    return {"running": p is not None, "process": p}


def _ts(b: bytes) -> float:
    sec, frac = struct.unpack(">II", b)
    return sec - _NTP_EPOCH + frac / 2 ** 32


def offset_from_packet(data: bytes, t1: float, t4: float) -> dict:
    """SNTP reply → {"offset_s", "delay_s", "stratum"}; offset > 0 means the PC clock is behind."""
    if len(data) < 48:
        raise ValueError("risposta NTP troppo corta")
    stratum = data[1]
    t2, t3 = _ts(data[32:40]), _ts(data[40:48])
    if stratum == 0 or t3 <= 0:
        raise ValueError("server NTP non sincronizzato")
    return {"offset_s": ((t2 - t1) + (t3 - t4)) / 2, "delay_s": (t4 - t1) - (t3 - t2), "stratum": stratum}


def ntp_offset(server: str = NTP_SERVER, timeout: float = 2.0) -> dict:
    """One SNTP query: {"offset_s", "delay_s", "stratum", "server"} or {"error", "server"}."""
    pkt = b"\x23" + 47 * b"\0"               # LI 0, version 4, mode 3 (client)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            t1 = time.time()
            s.sendto(pkt, (server, 123))
            data, _ = s.recvfrom(512)
            t4 = time.time()
        return {**offset_from_packet(data, t1, t4), "server": server}
    except socket.timeout:
        return {"error": "nessuna risposta dal server NTP", "server": server}
    except Exception as e:                   # DNS, network, bad packet
        return {"error": str(e) or e.__class__.__name__, "server": server}


def verdict(offset_s: float | None) -> str | None:
    """ok / warn / bad from the offset."""
    if offset_s is None:
        return None
    a = abs(offset_s)
    return "ok" if a <= WARN_S else "warn" if a <= BAD_S else "bad"
