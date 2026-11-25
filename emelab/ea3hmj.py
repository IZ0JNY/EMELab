# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Link with the EA3HMJ Tracking Software Suite (José EA3HMJ: DriverDish, DishController, Astroserver,
JPLastroserver, Astronomyserver, SNserver — https://github.com/EA3HMJ-Tracking-Software-Suite).

The ephemeris servers of the suite answer on TCP (telnet-like text): port 8888 planets/probes/fixed stations, 8889
satellites, 8890 noise sources. After connecting the client sends its user name (the callsign used for the station
kernel), then a target name; the answer is one line
    <target>,date,azimuth,elevation,distance,relative velocity,delay,frequency with doppler,frequency,drift
(Astroserver v1.6 manual, EA3HMJ). `<target>?Ddate` asks for another instant, `?P[n]` for n samples.

EMELab only READS from the servers here (the same positions DriverDish uses to point the dish), so the scans and the
measurements in EMELab use exactly the dish's own ephemerides. Commanding the dish is left to DriverDish."""
from __future__ import annotations

import socket
from datetime import datetime

PORTS = {"pianeti": 8888, "satelliti": 8889, "radiosorgenti": 8890}


def parse_line(line: str) -> dict | None:
    f = [x.strip() for x in line.strip().split(",")]
    if len(f) < 4:
        return None
    try:
        out = {"target": f[0], "date": f[1], "az": float(f[2]), "el": float(f[3])}
    except ValueError:
        return None
    for i, k in enumerate(("dist_km", "rel_vel_km_s", "delay_s", "freq_doppler_mhz", "freq_mhz", "drift_hz_s"), start=4):
        try:
            out[k] = float(f[i]) if i < len(f) and f[i] else None
        except ValueError:
            out[k] = None
    return out


def query(target: str, user: str, host: str = "127.0.0.1", port: int = 8888, when: datetime | None = None,
          timeout: float = 5.0) -> dict | None:
    """Position of target (e.g. MOON, SUN) for the server's user `user`, now or at `when` (UTC)."""
    cmd = target.upper() + (f"?D{when.strftime('%Y-%m-%dT%H:%M:%S')}" if when else "")
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        f = s.makefile("rwb", buffering=0)
        _read_available(s)                                   # banner / prompt
        f.write((user.strip() + "\r\n").encode())
        _read_available(s)
        f.write((cmd + "\r\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        for line in buf.decode("utf-8", "replace").splitlines():
            if line.upper().startswith(target.upper() + ","):
                return parse_line(line)
    return None


def _read_available(s, wait: float = 0.4) -> bytes:
    s.settimeout(wait)
    data = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    except (socket.timeout, OSError):
        pass
    finally:
        s.settimeout(5.0)
    return data


# ------------------------------------------------------------------ DriverDish files
def parse_driftscan(text: str) -> dict:
    """DriverDish DriftScan CSV (driftScan_<target>_<diam>_<freq>-<time>.csv):
        ;Diameter;Frequency;Astro ID;Astro name
        ;1.2;47.0;10;Sun
        ;date time;elevation;azimuth;SN
        2025-11-15 12:33:39, -40.87, 195.400, 28.402
    → {"diameter_m", "freq_ghz", "target", "t": [datetime], "el": [...], "az": [...], "sn_db": [...]}"""
    from datetime import timezone
    meta, t, el, az, sn = {}, [], [], [], []
    head = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(";"):
            head.append([x.strip() for x in line.strip(";").split(";")])
            continue
        f = [x.strip() for x in line.replace(";", ",").split(",")]
        if len(f) < 4:
            continue
        try:
            ts = datetime.strptime(f[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            t.append(ts); el.append(float(f[1])); az.append(float(f[2])); sn.append(float(f[3]))
        except ValueError:
            continue
    for i, h in enumerate(head[:-1]):
        if h and h[0].lower().startswith("diameter") and i + 1 < len(head):
            v = head[i + 1]
            try:
                meta = {"diameter_m": float(v[0]), "freq_ghz": float(v[1]), "target": v[3] if len(v) > 3 else ""}
            except (ValueError, IndexError):
                pass
    return {**meta, "t": t, "el": el, "az": az, "sn_db": sn}


def parse_corrections(text: str) -> dict:
    """DriverDish Autocorrection corrections.txt: ';date', ';Azimuth Offset', then «azimuth offset» pairs."""
    date, pts = None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(";"):
            s = line.strip(";").strip()
            if date is None and any(ch.isdigit() for ch in s):
                date = s
            continue
        f = line.replace(",", " ").split()
        try:
            pts.append((float(f[0]), float(f[1])))
        except (ValueError, IndexError):
            continue
    return {"date": date, "points": pts}


# ------------------------------------------------------------------ DriverDish telnet server (read-only use)
def driverdish_query(commands: list[str], host: str = "127.0.0.1", port: int = 9999, timeout: float = 4.0) -> dict:
    """Ask DriverDish's telnet server (enable it in DriverDish → Setup) for read-only values: az, el, ao, eo, astro,
    moving, traking, status. Returns {command: answer text}."""
    out = {}
    with socket.create_connection((host, port), timeout=timeout) as s:
        _read_available(s)
        for c in commands:
            s.sendall((c + "\r\n").encode())
            out[c] = _read_available(s, 0.6).decode("utf-8", "replace").strip()
        try:
            s.sendall(b"exit\r\n")
        except OSError:
            pass
    return out
