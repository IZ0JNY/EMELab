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
# DriverDish 3.x → Setup → Telnet server (port 9999, «Run»). Commands from the DriverDish.App Ethernet Utils manual
# (EA3HMJ, 10-03-2026). EMELab sends ONLY the read commands below: the others ("az+5", "traking on", "stop", …)
# move the dish or change its state and are refused here, whatever the caller asks.
READ_COMMANDS = ("status", "az", "el", "ao", "eo", "eq", "astro", "moving", "traking", "help")

_NUM = r"(-?\d+(?:[.,]\d+)?)"
_STATUS_ROWS = {                      # label in «status» → key prefix
    "target pos": "target", "dish pos": "dish", "curr err": "err", "offset": "off",
}


def _num(x: str) -> float:
    return float(x.replace(",", "."))


def _check_read_only(cmd: str) -> str:
    c = cmd.strip().lower()
    if c not in READ_COMMANDS:
        raise ValueError(f"DriverDish command not allowed (EMELab is read-only): {cmd!r}")
    return c


def parse_status(text: str) -> dict:
    """Answer of DriverDish's «status» command, e.g.
        Target:       Sun
        Target Pos AZ:141.341, EL:36.386
        Dish Pos AZ: 141.095, EL:36.367
        Curr Err AZ: 0.006, EL:0.019
        Offset A-Z : -0.240, EL: 0.000
        TRACKING ON
    → {"target": "Sun", "target_az": 141.341, "target_el": 36.386, "dish_az": …, "err_az": …, "off_az": …,
       "tracking": True}. Missing rows are simply absent; unknown rows are ignored."""
    import re
    out: dict = {}
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip(">").strip()
        if not line:
            continue
        low = line.lower()
        m = re.match(r"tra(?:c)?king\s*:?\s*(on|off)\b", low)
        if m:
            out["tracking"] = m.group(1) == "on"
            continue
        m = re.match(r"target\s*:\s*(.+)$", line, re.I)
        if m and "pos" not in low:
            out["target"] = m.group(1).strip()
            continue
        for label, key in _STATUS_ROWS.items():
            if low.replace("  ", " ").startswith(label):
                m = re.search(r"A-?Z\s*:\s*" + _NUM + r"\s*[,;]?\s*EL\s*:\s*" + _NUM, line, re.I)
                if m:
                    out[key + "_az"] = _num(m.group(1))
                    out[key + "_el"] = _num(m.group(2))
                break
    return out


def parse_yes_no(text: str) -> bool | None:
    """Answer of «moving» / «traking»: True, False or None when it can't be told (the echo of the command and the
    prompt are ignored)."""
    import re
    words = [w for w in re.findall(r"[a-zá-ú0-9]+", (text or "").lower()) if w not in ("moving", "traking", "tracking", "is", "dish")]
    if any(w in ("no", "not", "false", "off", "0", "stop", "stopped") for w in words):
        return False
    if any(w in ("yes", "true", "on", "1", "si", "sí") for w in words):
        return True
    return None


def driverdish_query(commands: list[str], host: str = "127.0.0.1", port: int = 9999, timeout: float = 4.0) -> dict:
    """Ask DriverDish's telnet server (enable it in DriverDish → Setup) for read-only values: az, el, ao, eo, astro,
    moving, traking, status. Returns {command: answer text}. Any other command raises ValueError before connecting."""
    cmds = [_check_read_only(c) for c in commands]
    out = {}
    with socket.create_connection((host, port), timeout=timeout) as s:
        _read_available(s)
        for c in cmds:
            s.sendall((c + "\r\n").encode())
            out[c] = _read_available(s, 0.6).decode("utf-8", "replace").strip()
        try:
            s.sendall(b"exit\r\n")
        except OSError:
            pass
    return out


def angle_between(az1: float, el1: float, az2: float, el2: float) -> float:
    """Great-circle angle (degrees) between two (AZ, EL) directions."""
    import math
    a1, e1, a2, e2 = map(math.radians, (az1, el1, az2, el2))
    c = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def pointing_loss_db(err_deg: float, hpbw_deg: float) -> float:
    """One-way loss of a Gaussian beam pointed err_deg off (−12·(θ/HPBW)² dB, as positive dB)."""
    return 12.0 * (err_deg / hpbw_deg) ** 2 if hpbw_deg > 0 else float("nan")


class DriverDishMonitor:
    """Background reader of DriverDish's telnet server: keeps one connection open and asks «status» (and
    «moving») every `period` seconds, reconnecting by itself. Never sends anything but READ_COMMANDS.
    The page only looks at .last / .error / .history, so a slow or absent DriverDish never blocks EMELab."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9999, period: float = 2.0, keep: int = 900):
        import collections
        import threading
        self.host, self.port, self.period = host, int(port), float(period)
        self.last: dict | None = None          # last parsed status + "utc", "moving", "raw"
        self.error: str | None = None
        self.error_since = None
        self.connected = False
        self.history = collections.deque(maxlen=keep)   # (utc, status dict)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="DriverDishMonitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def _ask(self, s, cmd: str) -> str:
        s.sendall((_check_read_only(cmd) + "\r\n").encode())
        return _read_until_quiet(s, quiet=0.25, total=2.0).decode("utf-8", "replace")

    def _run(self):
        from datetime import timezone
        backoff = 1.0
        while not self._stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=4.0) as s:
                    _read_until_quiet(s, quiet=0.3, total=1.5)          # banner
                    self.connected, backoff = True, 1.0
                    while not self._stop.is_set():
                        raw = self._ask(s, "status")
                        st = parse_status(raw)
                        if not st:
                            raise OSError("DriverDish answered «status» with nothing readable")
                        st["moving"] = parse_yes_no(self._ask(s, "moving"))
                        st["raw"] = raw.strip()
                        st["utc"] = datetime.now(timezone.utc)
                        self.last, self.error, self.error_since = st, None, None
                        self.history.append((st["utc"], {k: v for k, v in st.items() if k != "raw"}))
                        self._stop.wait(self.period)
            except (OSError, ValueError) as e:
                self.connected = False
                if self.error_since is None:
                    self.error_since = datetime.now(timezone.utc)
                self.error = str(e) or e.__class__.__name__
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 15.0)


def _read_until_quiet(s, quiet: float = 0.25, total: float = 2.0) -> bytes:
    """Read until nothing arrives for `quiet` seconds (or `total` seconds have passed)."""
    import time
    end = time.monotonic() + total
    data = b""
    s.settimeout(quiet)
    try:
        while time.monotonic() < end:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                if data:
                    break
                continue
            if not chunk:
                raise OSError("DriverDish closed the connection")
            data += chunk
    finally:
        s.settimeout(4.0)
    return data
