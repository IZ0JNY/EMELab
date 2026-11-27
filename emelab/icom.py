# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Icom IC-9700 over CI-V: read the radio's state (frequencies, modes, meters, receiver and transmitter settings)
for the 📻 Radio tab, and — only when the user presses a button with the commands switched on — change a setting.

Four ways to reach the radio, because WSJT-X normally holds the radio's USB serial port (Windows opens a COM
port for one program at a time):

* ``serial``  — CI-V straight on a COM port (the IC-9700 USB port when WSJT-X is closed, or the REMOTE jack with a
  CI-V cable, «CI-V USB Port = Link to [REMOTE]»). Every setting can be read.
* ``rigctld`` — Hamlib's rigctld, a small server that owns the port and lets several programs share it (WSJT-X
  ships it as rigctld-wsjtx.exe; WSJT-X then uses «Hamlib NET rigctl» on 127.0.0.1:4532). The usual settings.
* ``lan``     — Ethernet (Icom network protocol, emelab/icom_lan.py): every setting and the radio's RF scope while
  WSJT-X keeps the USB port. One network client at a time.
* ``wsjtx``   — no CAT at all: frequency, mode and TX state from WSJT-X's UDP messages. Always works, few fields.

Frequencies above 1.4 GHz use the 6-byte BCD format of the SQ6EMM custom firmware (transverter RF on the display
and on CI-V, as on the IC-905); 5-byte frames (stock firmware) are read the same way."""
from __future__ import annotations

import socket
import time

DEFAULT_ADDR = 0xA2        # IC-9700 default CI-V address
CTRL_ADDR = 0xE0           # controller (PC)
PREAMBLE, EOM, OK, NG = 0xFE, 0xFD, 0xFB, 0xFA
HAMLIB_IC9700 = 3081       # Hamlib rig model of the IC-9700

MODES = {0x00: "LSB", 0x01: "USB", 0x02: "AM", 0x03: "CW", 0x04: "RTTY", 0x05: "FM", 0x07: "CW-R",
         0x08: "RTTY-R", 0x17: "DV", 0x22: "DD"}
MODE_CODES = {v: k for k, v in MODES.items()}
AGC = {1: "FAST", 2: "MID", 3: "SLOW"}
ATT = {0x00: "OFF", 0x10: "10dB"}


# ------------------------------------------------------------------ BCD and frames
def bcd_to_int(b: bytes, little: bool = True) -> int:
    """Icom BCD: two digits per byte; frequencies little-endian (lowest digits first), levels big-endian."""
    seq = b if not little else bytes(reversed(b))
    n = 0
    for x in seq:
        n = n * 100 + (x >> 4) * 10 + (x & 0x0F)
    return n


def int_to_bcd(n: int, nbytes: int, little: bool = True) -> bytes:
    out = []
    for _ in range(nbytes):
        n, r = divmod(n, 100)
        out.append(((r // 10) << 4) | (r % 10))
    return bytes(out if little else reversed(out))


def freq_bytes(hz: int) -> bytes:
    """5 bytes up to 9.99 GHz on the stock radio; 6 bytes above 1.4 GHz (custom firmware, as the IC-905)."""
    return int_to_bcd(int(hz), 6 if hz >= 1_400_000_000 else 5)


def frame(cmd: int, sub: int | None = None, data: bytes = b"", to: int = DEFAULT_ADDR, frm: int = CTRL_ADDR) -> bytes:
    body = bytes([cmd]) + (bytes([sub]) if sub is not None else b"") + bytes(data)
    return bytes([PREAMBLE, PREAMBLE, to, frm]) + body + bytes([EOM])


def split_frames(buf: bytes) -> tuple[list[tuple[int, int, bytes]], bytes]:
    """[(to, from, body)] of the complete frames in buf, and the bytes left over (an incomplete frame)."""
    out, i = [], 0
    while True:
        s = buf.find(bytes([PREAMBLE, PREAMBLE]), i)
        if s < 0:
            return out, b""
        e = buf.find(bytes([EOM]), s + 2)
        if e < 0:
            return out, buf[s:]
        f = buf[s + 2:e].lstrip(bytes([PREAMBLE]))
        if len(f) >= 3:
            out.append((f[0], f[1], bytes(f[2:])))
        i = e + 1


# ------------------------------------------------------------------ meter scales (IC-9700 CI-V reference guide)
def _interp(x: float, pts: list[tuple[float, float]]) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def s_units(raw: int) -> str:
    """0 = S0, 120 = S9, 241 = S9+60 dB."""
    if raw <= 120:
        return f"S{round(raw / 120 * 9)}"
    return f"S9+{round((raw - 120) / 121 * 60)}dB"


def swr(raw: int) -> float:
    return round(_interp(raw, [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (240, 6.0)]), 2)


def po_percent(raw: int) -> float:
    return int(round(_interp(raw, [(0, 0), (143, 50), (213, 100), (255, 120)])))


def vd_volts(raw: int) -> float:
    return round(_interp(raw, [(0, 0), (13, 10), (241, 16)]), 1)


def id_amps(raw: int) -> float:             # the IC-9700 guide's Id scale is assumed (shown in orange)
    return round(_interp(raw, [(0, 0), (121, 10), (241, 20)]), 1)


# ------------------------------------------------------------------ what we read, field by field
# key: (cmd, sub, decoder). decoder gets the data bytes after cmd/sub.
def _lvl(d: bytes) -> int:
    return bcd_to_int(d[-2:], little=False) if len(d) >= 2 else 0


def _pct(d: bytes) -> int:
    return round(_lvl(d) / 255 * 100)


def _onoff(d: bytes) -> bool:
    return bool(d and d[-1])


QUERIES = {
    "af_pct": (0x14, 0x01, _pct), "rf_pct": (0x14, 0x02, _pct), "sql_pct": (0x14, 0x03, _pct),
    "nr_level": (0x14, 0x06, lambda d: round(_lvl(d) / 255 * 15)), "power_pct": (0x14, 0x0A, _pct),
    "mic_pct": (0x14, 0x0B, _pct), "key_wpm": (0x14, 0x0C, lambda d: round(6 + _lvl(d) / 255 * 42)),
    "comp_level": (0x14, 0x0E, lambda d: round(_lvl(d) / 255 * 10)),
    "nb_level": (0x14, 0x12, _pct), "vox_pct": (0x14, 0x16, _pct),
    "s_raw": (0x15, 0x02, _lvl), "po_raw": (0x15, 0x11, _lvl), "swr_raw": (0x15, 0x12, _lvl),
    "alc_raw": (0x15, 0x13, _lvl), "comp_raw": (0x15, 0x14, _lvl), "vd_raw": (0x15, 0x15, _lvl),
    "id_raw": (0x15, 0x16, _lvl), "busy": (0x15, 0x01, _onoff),
    "preamp": (0x16, 0x02, _onoff), "agc": (0x16, 0x12, lambda d: AGC.get(d[-1], "?") if d else "?"),
    "nb": (0x16, 0x22, _onoff), "nr": (0x16, 0x40, _onoff), "anf": (0x16, 0x41, _onoff),
    "comp": (0x16, 0x44, _onoff), "monitor": (0x16, 0x45, _onoff), "vox": (0x16, 0x46, _onoff),
    "bkin": (0x16, 0x47, lambda d: {0: "OFF", 1: "SEMI", 2: "FULL"}.get(d[-1], "?") if d else "?"),
    "mnf": (0x16, 0x48, _onoff), "lock": (0x16, 0x50, _onoff),
    "dualwatch": (0x16, 0x59, _onoff), "satmode": (0x16, 0x5A, _onoff),
    "att": (0x11, None, lambda d: ATT.get(d[-1], f"{d[-1]:02X}") if d else "?"),
    "tx": (0x1C, 0x00, _onoff),
    "split": (0x0F, None, lambda d: {0: "OFF", 1: "SPLIT", 0x10: "SIMPLEX", 0x11: "DUP-", 0x12: "DUP+"}
              .get(d[-1], "?") if d else "?"),
    "rit_on": (0x21, 0x01, _onoff),
    "rit_hz": (0x21, 0x00, lambda d: (-1 if len(d) >= 3 and d[2] else 1) * bcd_to_int(d[:2]) if d else 0),
    "data_mode": (0x1A, 0x06, lambda d: bool(d and d[0])),
    "main_sub": (0x07, 0xD2, lambda d: "SUB" if d and d[-1] else "MAIN"),
}


def _decode_vfo(d: bytes) -> dict:
    """0x25 (frequency) / 0x26 (mode, data, filter) answers: first byte is 00 selected / 01 unselected."""
    return {"freq_hz": bcd_to_int(d[1:])} if d else {}


def _decode_mode(d: bytes) -> dict:
    if len(d) < 2:
        return {}
    out = {"mode": MODES.get(d[1], f"0x{d[1]:02X}")}
    if len(d) >= 3:
        out["data"] = bool(d[2])
    if len(d) >= 4:
        out["filter"] = f"FIL{d[3]}"
    return out


def mode_label(mode: str | None, data: bool | None) -> str:
    """«USB-D» as on the radio's display."""
    if not mode:
        return "—"
    return mode + ("-D" if data and mode in ("LSB", "USB", "AM", "FM") else "")


def derive(state: dict) -> dict:
    """Readable values from the raw meters (S units, W%, SWR, V, A)."""
    s = dict(state)
    if s.get("s_raw") is not None:
        s["s_meter"] = s_units(s["s_raw"])
    if s.get("po_raw") is not None:
        s["po_pct"] = po_percent(s["po_raw"])
    if s.get("swr_raw") is not None:
        s["swr"] = swr(s["swr_raw"])
    if s.get("vd_raw") is not None:
        s["vd_v"] = vd_volts(s["vd_raw"])
    if s.get("id_raw") is not None:
        s["id_a"] = id_amps(s["id_raw"])
    if s.get("alc_raw") is not None:
        s["alc_pct"] = round(s["alc_raw"] / 120 * 100)
    return s


# ------------------------------------------------------------------ transports
def read_civ(query, source: str) -> dict:
    """Every setting of QUERIES through query(cmd, sub) (a COM port or the LAN CI-V stream)."""
    st: dict = {"source": source}
    for vfo, key in ((0x00, "sel"), (0x01, "unsel")):
        f = query(0x25, vfo)
        if f:
            st[key] = _decode_vfo(bytes([vfo]) + f)
            m = query(0x26, vfo)
            if m:
                st[key].update(_decode_mode(bytes([vfo]) + m))
    if "sel" not in st:                        # older firmware: 0x03 / 0x04 on the selected receiver only
        f = query(0x03)
        if f is None:
            raise IOError("la radio non risponde (indirizzo CI-V, velocità o «CI-V USB Echo Back»?)")
        st["sel"] = {"freq_hz": bcd_to_int(f)}
        m = query(0x04)
        if m:
            st["sel"]["mode"] = MODES.get(m[0], "?")
            st["sel"]["filter"] = f"FIL{m[1]}" if len(m) > 1 else None
    for key, (cmd, sub, dec) in QUERIES.items():
        d = query(cmd, sub)
        if d:
            try:
                st[key] = dec(d)
            except Exception:
                pass
    return derive(st)


class CivSerial:
    """CI-V on a COM port. Opened for one reading and closed again, so another program can use the port in between."""

    def __init__(self, port: str, baud: int = 115200, addr: int = DEFAULT_ADDR, timeout: float = 0.25):
        self.port, self.baud, self.addr, self.timeout = port, int(baud), int(addr), timeout
        self.ser = None

    def __enter__(self):
        import serial                  # pyserial
        self.ser = serial.Serial(self.port, self.baud, timeout=0.05, write_timeout=0.5)
        self.ser.reset_input_buffer()
        return self

    def __exit__(self, *a):
        try:
            self.ser.close()
        finally:
            self.ser = None

    def query(self, cmd: int, sub: int | None = None, data: bytes = b"") -> bytes | None:
        """The radio's answer (bytes after cmd/sub), b"" for OK, None for NG or no answer."""
        req = frame(cmd, sub, data, self.addr)
        self.ser.write(req)
        buf, end = b"", time.monotonic() + self.timeout
        while time.monotonic() < end:
            buf += self.ser.read(64)
            frames, rest = split_frames(buf)
            for to, frm, body in frames:
                if frm != self.addr or to not in (CTRL_ADDR, 0x00):
                    continue                   # our own echo or another device
                if body == bytes([OK]):
                    return b""
                if body == bytes([NG]):
                    return None
                head = bytes([cmd]) + (bytes([sub]) if sub is not None else b"")
                if body.startswith(head) and to == CTRL_ADDR:
                    return body[len(head):]
            buf = rest
        return None

    def read_state(self) -> dict:
        return read_civ(self.query, "serial")

    def send(self, cmd: int, sub: int | None, data: bytes = b"") -> bool:
        return self.query(cmd, sub, data) == b""


class Rigctld:
    """Hamlib rigctld (shared with WSJT-X): the extended protocol, one command per line."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4532, timeout: float = 1.5):
        self.host, self.port, self.timeout = host, int(port), timeout
        self.sock = None
        self._buf = b""

    def __enter__(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)
        return self

    def __exit__(self, *a):
        try:
            self.sock.close()
        finally:
            self.sock = None

    def cmd(self, line: str) -> list[str] | None:
        """Lines of the answer to «+\\line» (without the RPRT line); None if Hamlib returned an error."""
        self.sock.sendall(("+\\" + line + "\n").encode())
        name = line.split()[0]
        out = []
        while True:
            while b"\n" not in self._buf:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise IOError("rigctld ha chiuso la connessione")
                self._buf += chunk
            ln, self._buf = self._buf.split(b"\n", 1)
            t = ln.decode(errors="replace").strip()
            if t.startswith("RPRT"):
                return out if t.split()[-1] == "0" else None
            if not t or t.startswith(name + ":"):            # the command echoed: «get_level: RFPOWER»
                continue
            # values come as «Frequency: 144100000» or bare («0.500000» after get_level, «0» after get_func)
            out.append(t.split(":", 1)[1].strip() if ":" in t else t)

    def _num(self, line: str):
        r = self.cmd(line)
        try:
            return float(r[-1]) if r else None
        except ValueError:
            return None                      # not a number: unknown, never «ON»

    def read_state(self) -> dict:
        st: dict = {"source": "rigctld"}
        f = self._num("get_freq")
        if f is None:
            raise IOError("rigctld non legge la frequenza")
        m = self.cmd("get_mode") or []
        mode = m[0] if m else None
        st["sel"] = {"freq_hz": int(f), "mode": (mode or "").replace("PKT", "") or None,
                     "data": bool(mode and mode.startswith("PKT")), "width_hz": int(float(m[1])) if len(m) > 1 else None}
        info = self.cmd("get_vfo_info Sub") or []
        if info:
            try:
                st["unsel"] = {"freq_hz": int(float(info[0])), "mode": info[1].replace("PKT", ""),
                               "data": info[1].startswith("PKT")}
            except (ValueError, IndexError):
                pass
        st["tx"] = bool(self._num("get_ptt"))
        lv = {"STRENGTH": "s_db", "RFPOWER": "power_pct", "AF": "af_pct", "RF": "rf_pct", "SQL": "sql_pct",
              "MICGAIN": "mic_pct", "COMP": "comp_level", "VOXGAIN": "vox_pct", "KEYSPD": "key_wpm",
              "PREAMP": "preamp_db", "ATT": "att_db", "AGC": "agc_n", "SWR": "swr", "RFPOWER_METER": "po_frac",
              "ALC": "alc_frac", "VD_METER": "vd_v", "ID_METER": "id_a", "NR": "nr_frac"}
        for lev, key in lv.items():
            v = self._num("get_level " + lev)
            if isinstance(v, float):
                st[key] = v
        for k in ("power_pct", "af_pct", "rf_pct", "sql_pct", "mic_pct", "vox_pct"):
            if k in st:
                st[k] = round(st[k] * 100)
        if "po_frac" in st:
            st["po_pct"] = round(st.pop("po_frac") * 100)
        if "alc_frac" in st:
            st["alc_pct"] = round(st.pop("alc_frac") * 100)
        if "s_db" in st:                                   # Hamlib: dB relative to S9
            db = st["s_db"]
            st["s_meter"] = f"S9+{round(db)}dB" if db > 0 else f"S{max(0, round(9 + db / 6))}"
        if "preamp_db" in st:
            st["preamp"] = st["preamp_db"] > 0
        if "att_db" in st:
            st["att"] = f"{int(st['att_db'])}dB" if st["att_db"] else "OFF"
        if "agc_n" in st:
            st["agc"] = {2: "FAST", 3: "SLOW", 5: "MID", 6: "AUTO"}.get(int(st["agc_n"]), str(int(st["agc_n"])))
        for fn, key in {"NB": "nb", "NR": "nr", "ANF": "anf", "MN": "mnf", "COMP": "comp", "VOX": "vox",
                        "LOCK": "lock", "MON": "monitor", "SATMODE": "satmode", "DUAL_WATCH": "dualwatch",
                        "RIT": "rit_on"}.items():
            v = self._num("get_func " + fn)
            if v is not None:
                st[key] = bool(v)
        sp = self.cmd("get_split_vfo")
        if sp:
            st["split"] = "SPLIT" if sp[0] == "1" else "OFF"
        rit = self._num("get_rit")
        if isinstance(rit, float):
            st["rit_hz"] = int(rit)
        vfo = self.cmd("get_vfo")
        if vfo:
            st["main_sub"] = "SUB" if "sub" in vfo[0].lower() or vfo[0] == "VFOB" else "MAIN"
        return st

    def send_line(self, line: str) -> bool:
        return self.cmd(line) is not None


def from_wsjtx(status: dict | None) -> dict:
    """What WSJT-X tells over UDP: dial frequency, mode, TX state. No CAT needed."""
    if not status or not status.get("dial_hz"):
        return {}
    mode = status.get("mode") or ""
    return {"source": "wsjtx", "sel": {"freq_hz": int(status["dial_hz"]), "mode": "USB", "data": True,
                                       "digital": mode + (("-" + status["submode"]) if status.get("submode") else "")},
            "tx": bool(status.get("transmitting"))}


# ------------------------------------------------------------------ reading with the chosen source
def _lan(sets: dict):
    """The open network session with the radio (IP, network user and password from the tab's settings)."""
    from emelab import icom_lan
    if not sets.get("radio_lan_host") or not sets.get("radio_lan_user"):
        raise IOError("indirizzo IP o utente di rete della radio non impostati")
    return icom_lan.get(sets["radio_lan_host"], sets["radio_lan_user"], sets.get("radio_lan_password") or "",
                        int(sets.get("radio_lan_port") or 50001))


def read(sets: dict, wsjtx_status: dict | None = None) -> dict:
    """The radio state with the source chosen in the tab; on failure the WSJT-X data and the error."""
    src = sets.get("radio_source", "wsjtx")
    err = None
    try:
        if src == "serial" and sets.get("radio_port"):
            with CivSerial(sets["radio_port"], sets.get("radio_baud", 115200),
                           int(sets.get("radio_addr", DEFAULT_ADDR))) as r:
                st = r.read_state()
        elif src == "rigctld":
            with Rigctld(sets.get("radio_host", "127.0.0.1"), sets.get("radio_rport", 4532)) as r:
                st = r.read_state()
        elif src == "lan":
            st = _lan(sets).read_state()
        else:
            st = None
        if st:
            st["read_utc"] = time.time()
            return st
    except ImportError:
        err = "pyserial non installato"
    except Exception as e:
        msg = str(e)
        if "denied" in msg.lower() or "negato" in msg.lower() or "PermissionError" in repr(e):
            msg = "porta occupata (probabilmente da WSJT-X): usa rigctld o chiudi WSJT-X"
        err = msg
    st = from_wsjtx(wsjtx_status)
    st["read_utc"] = time.time()
    if err:
        st["error"] = err
    return st


# ------------------------------------------------------------------ commands (only from a button, commands on)
def _level(pct: float) -> bytes:
    return int_to_bcd(round(max(0.0, min(100.0, pct)) / 100 * 255), 2, little=False)


SETTERS = {   # key → (CI-V builder, rigctld line builder)
    "freq_hz": (lambda v: (0x05, None, freq_bytes(int(v))), lambda v: f"set_freq {int(v)}"),
    "mode": (lambda v: (0x06, None, bytes([MODE_CODES[v]])), lambda v: f"set_mode {v} 0"),
    "power_pct": (lambda v: (0x14, 0x0A, _level(v)), lambda v: f"set_level RFPOWER {v / 100:.3f}"),
    "af_pct": (lambda v: (0x14, 0x01, _level(v)), lambda v: f"set_level AF {v / 100:.3f}"),
    "rf_pct": (lambda v: (0x14, 0x02, _level(v)), lambda v: f"set_level RF {v / 100:.3f}"),
    "sql_pct": (lambda v: (0x14, 0x03, _level(v)), lambda v: f"set_level SQL {v / 100:.3f}"),
    "preamp": (lambda v: (0x16, 0x02, bytes([int(bool(v))])), lambda v: f"set_level PREAMP {10 if v else 0}"),
    "att": (lambda v: (0x11, None, bytes([0x10 if v else 0x00])), lambda v: f"set_level ATT {10 if v else 0}"),
    "agc": (lambda v: (0x16, 0x12, bytes([{"FAST": 1, "MID": 2, "SLOW": 3}[v]])),
            lambda v: "set_level AGC " + str({"FAST": 2, "MID": 5, "SLOW": 3}[v])),
    "nb": (lambda v: (0x16, 0x22, bytes([int(bool(v))])), lambda v: f"set_func NB {int(bool(v))}"),
    "nr": (lambda v: (0x16, 0x40, bytes([int(bool(v))])), lambda v: f"set_func NR {int(bool(v))}"),
    "anf": (lambda v: (0x16, 0x41, bytes([int(bool(v))])), lambda v: f"set_func ANF {int(bool(v))}"),
    "comp": (lambda v: (0x16, 0x44, bytes([int(bool(v))])), lambda v: f"set_func COMP {int(bool(v))}"),
    "vox": (lambda v: (0x16, 0x46, bytes([int(bool(v))])), lambda v: f"set_func VOX {int(bool(v))}"),
    "dualwatch": (lambda v: (0x16, 0x59, bytes([int(bool(v))])), lambda v: f"set_func DUAL_WATCH {int(bool(v))}"),
}


def write(sets: dict, key: str, value) -> tuple[bool, str]:
    """Sends one setting to the radio. Never called by EMELab on its own: only by a button in the Radio tab, with
    «Comandi verso la radio» switched on. (ok, message)."""
    if key not in SETTERS:
        return False, f"impostazione sconosciuta: {key}"
    civ, rig = SETTERS[key]
    src = sets.get("radio_source", "wsjtx")
    try:
        if src == "serial" and sets.get("radio_port"):
            with CivSerial(sets["radio_port"], sets.get("radio_baud", 115200),
                           int(sets.get("radio_addr", DEFAULT_ADDR))) as r:
                ok = r.send(*civ(value))
        elif src == "rigctld":
            with Rigctld(sets.get("radio_host", "127.0.0.1"), sets.get("radio_rport", 4532)) as r:
                ok = r.send_line(rig(value))
        elif src == "lan":
            ok = _lan(sets).send(*civ(value))
        else:
            return False, "con la sola lettura da WSJT-X non si possono inviare comandi"
    except Exception as e:
        return False, str(e)
    return ok, "inviato" if ok else "la radio ha rifiutato il comando"


def rigctld_command(wsjtx_dir: str, port: str, baud: int = 115200, tcp: int = 4532) -> str:
    """Command line to start rigctld-wsjtx (shipped with WSJT-X) for the IC-9700, to share the port."""
    exe = (wsjtx_dir.rstrip("\\/") + "\\rigctld-wsjtx.exe") if wsjtx_dir else "rigctld-wsjtx.exe"
    return f'"{exe}" -m {HAMLIB_IC9700} -r {port} -s {int(baud)} -t {int(tcp)}'


RIGCTLD_DIRS = [r"C:\WSJT\wsjtx\bin", r"C:\Program Files\wsjtx\bin", r"C:\Program Files (x86)\wsjtx\bin",
                r"C:\WSJT\wsjtx-improved\bin"]


def find_rigctld(extra_dirs: list[str] | None = None) -> str | None:
    """Path of rigctld-wsjtx.exe (shipped with WSJT-X), or of a Hamlib rigctld on the PATH."""
    import os
    import shutil
    for d in (extra_dirs or []) + RIGCTLD_DIRS:
        p = os.path.join(d, "rigctld-wsjtx.exe")
        if d and os.path.isfile(p):
            return p
    return shutil.which("rigctld-wsjtx") or shutil.which("rigctld")


def rigctld_alive(host: str = "127.0.0.1", port: int = 4532) -> bool:
    try:
        with socket.create_connection((host, int(port)), 0.5):
            return True
    except OSError:
        return False


_RIGCTLD_PROC = None


def start_rigctld(exe: str, port: str, baud: int = 115200, tcp: int = 4532):
    """Starts rigctld for the IC-9700 (only from the «Avvia rigctld» button). (ok, message)."""
    global _RIGCTLD_PROC
    import subprocess
    import sys
    if rigctld_alive("127.0.0.1", tcp):
        return True, "rigctld è già in ascolto"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        _RIGCTLD_PROC = subprocess.Popen([exe, "-m", str(HAMLIB_IC9700), "-r", port, "-s", str(int(baud)),
                                          "-t", str(int(tcp))], creationflags=flags,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception as e:
        return False, str(e)
    for _ in range(20):
        if rigctld_alive("127.0.0.1", tcp):
            return True, "rigctld avviato"
        if _RIGCTLD_PROC.poll() is not None:
            err = (_RIGCTLD_PROC.stderr.read() or b"").decode(errors="replace").strip()[-300:]
            return False, "rigctld si è chiuso: " + (err or "porta COM occupata da WSJT-X? Chiudi prima WSJT-X")
        time.sleep(0.25)
    return False, "rigctld non risponde"


# ------------------------------------------------------------------ transverters (IF on the radio, RF in EMELab)
# Commercial transverters. verified=True: values from the maker's product page (Kuhne shop, read 2026-11-27);
# verified=False: only band and usual IF, shown in orange as assumed.
KUHNE = "https://shop.kuhne-electronic.com/kuhne/en/shop/konverter-transverte/transverter/"
TRANSVERTER_CATALOG = [
    {"maker": "Kuhne electronic", "model": "MKU 10 G5", "band": "10GHz", "rf_range": "10000–10500 MHz",
     "if_range": "28–440 MHz", "rf_mhz": 10368.0, "if_mhz": 144.0, "lo": "PLL interno (ref. 10 MHz esterna)",
     "pout_w": 0.2, "nf_db": 1.3, "drive": "0.5–5 W", "rf_conn": "SMA (RX/TX separati)",
     "supply": "13.8 V, 580 mA", "verified": True,
     "url": "https://shop.kuhne-electronic.de/funk/en/shop/konverter-transverte/transverter/MKU+10+G5+3+cm+Transverter/?card=2018"},
    {"maker": "Kuhne electronic", "model": "MKU 24 G3", "band": "24GHz", "rf_range": "24048–24050 MHz",
     "if_range": "144–146 MHz", "rf_mhz": 24048.0, "if_mhz": 144.0, "lo": "LO esterno 11952 MHz (×2 = 23904)",
     "pout_w": 2.0, "nf_db": 3.5, "drive": "0.5–5 W", "rf_conn": "SMA", "supply": "13.8 V, 2 A in TX",
     "verified": True, "url": KUHNE + "MKU+24+G3+Transverter/?card=1757"},
    {"maker": "Kuhne electronic", "model": "MKU 47 G2", "band": "47GHz", "rf_range": "47088–47090 MHz",
     "if_range": "144–146 MHz", "rf_mhz": 47088.0, "if_mhz": 144.0, "lo": "LO esterno 11736 MHz (×4 = 46944)",
     "pout_w": 0.03, "nf_db": 6.0, "drive": "1–5 W", "rf_conn": "guida WR-19 (UG383/U)", "supply": "13.8 V, 400 mA in TX",
     "verified": True, "url": KUHNE + "MKU+47+G2+Transverter/?card=1611"},
    {"maker": "Down East Microwave", "model": "DEM 10368-144", "band": "10GHz", "rf_range": "10368 MHz",
     "if_range": "144 MHz", "rf_mhz": 10368.0, "if_mhz": 144.0, "lo": "10224 MHz", "verified": False, "url": ""},
    {"maker": "SG Lab", "model": "Transverter 10 GHz", "band": "10GHz", "rf_range": "10368 MHz",
     "if_range": "144 / 432 MHz", "rf_mhz": 10368.0, "if_mhz": 144.0, "lo": "10224 MHz", "verified": False, "url": ""},
]
DEFAULT_TRANSVERTERS = [{"name": "10GHz", "model": "Kuhne MKU 10 G5", "rf_mhz": 10368.0, "if_mhz": 144.0, "on": True},
                        {"name": "24GHz", "model": "Kuhne MKU 24 G3", "rf_mhz": 24048.0, "if_mhz": 144.0, "on": True},
                        {"name": "47GHz", "model": "Kuhne MKU 47 G2", "rf_mhz": 47088.0, "if_mhz": 144.0, "on": True}]


def catalog_label(c: dict) -> str:
    return f"{c['maker'].split()[0]} {c['model']}"
IF_SPAN_MHZ = 2.0          # a transverter's IF band: if_mhz … if_mhz + 2 MHz (144–146)


def lo_hz(trv: dict) -> int:
    """Local-oscillator offset added to the IF: 10368 − 144 MHz = 10224 MHz."""
    return round((float(trv["rf_mhz"]) - float(trv["if_mhz"])) * 1e6)


def pick_transverter(trvs: list[dict], choice: str | None, if_hz: int | None, wsjtx_hz: int | None = None):
    """The transverter to apply to a receiver: the one chosen by name, or with «auto» the one whose RF band holds
    WSJT-X's dial frequency (when WSJT-X has its own transverter offset); only if the radio is inside its IF band."""
    if not if_hz or if_hz >= 1_400_000_000:          # already RF (SQ6EMM firmware) or nothing read
        return None
    fit = [t for t in trvs if t.get("on", True)
           and float(t["if_mhz"]) * 1e6 <= if_hz <= (float(t["if_mhz"]) + IF_SPAN_MHZ) * 1e6]
    if not fit or not choice or choice == "OFF":
        return None
    if choice == "auto":
        if wsjtx_hz and wsjtx_hz >= 1_000_000_000:
            near = min(fit, key=lambda t: abs(float(t["rf_mhz"]) * 1e6 - wsjtx_hz))
            if abs(float(near["rf_mhz"]) * 1e6 - wsjtx_hz) < 50e6:
                return near
        return fit[0] if len(fit) == 1 else None
    return next((t for t in fit if t["name"] == choice), None)


def apply_transverters(state: dict, trvs: list[dict], main: str | None = "auto", sub: str | None = "auto",
                       wsjtx_hz: int | None = None) -> dict:
    """Adds the RF frequency to the MAIN and SUB readouts: freq_hz becomes RF, if_hz keeps what the radio shows."""
    s = dict(state)
    ms = s.get("main_sub") or "MAIN"
    for key, rx in (("sel", ms), ("unsel", "SUB" if ms == "MAIN" else "MAIN")):
        v = s.get(key)
        if not v or not v.get("freq_hz") or s.get("source") == "wsjtx":
            continue
        t = pick_transverter(trvs, main if rx == "MAIN" else sub, v["freq_hz"], wsjtx_hz)
        if t:
            s[key] = dict(v, if_hz=v["freq_hz"], freq_hz=v["freq_hz"] + lo_hz(t), trv=t["name"],
                          trv_model=t.get("model") or "")
    return s


def rf_to_if(hz: int, trvs: list[dict]) -> int:
    """For a frequency command: an RF frequency typed in EMELab becomes the IF to send to the radio."""
    for t in trvs:
        if t.get("on", True) and abs(hz - float(t["rf_mhz"]) * 1e6) < 50e6:
            return int(hz - lo_hz(t))
    return int(hz)
