# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Icom network protocol (IC-9700 «Network Control»): the CI-V stream over Ethernet, without the USB port.

WSJT-X keeps the USB port (CAT and audio) and EMELab reads the radio over the LAN at the same time: every setting
of the 📟 Radio tab and the radio's own spectrum scope (CI-V 27h waveform data), which the USB port cannot give
while WSJT-X holds it.

The radio accepts one network client at a time (RS-BA1, wfview, kappanhang or EMELab). The protocol is Icom's
UDP protocol as documented by the open-source projects wfview and kappanhang (MIT):

* control port (50001): handshake (are you there / I am here / are you ready), login with the network user and
  password (obfuscated by Icom's fixed table), token renewal every minute, connection request for the streams;
* CI-V port (50002): CI-V frames inside UDP packets (0xC1 header); the stream is opened with 0xC0 … 05;
* on both: tracked packets with a sequence number (the radio may ask them again), idle packets, and pings
  that the radio sends ten times a second and that must be answered, or the radio drops the session.

Nothing here sends a setting to the radio: read() only asks (CI-V queries). The scope data output (27 11 01) is
switched on only when the user ticks «Scope RF dalla radio», and switched off again when the session closes."""
from __future__ import annotations

import atexit
import os
import select
import socket
import struct
import threading
import time

import numpy as np

from emelab import icom

CONTROL_PORT, CIV_PORT, AUDIO_PORT = 50001, 50002, 50003
PING_S = 3.0           # our pings (the radio sends its own every 100 ms)
IDLE_S = 1.0           # idle packets
TOKEN_S = 60.0         # token renewal
LOST_S = 6.0           # nothing from the radio for this long → session lost
RETRY_S = 10.0         # wait before logging in again after a failure
SCOPE_ROW_S = 0.5      # one waterfall row every 0.5 s
SCOPE_ROWS = 90
SCOPE_AMP_MAX = 160    # waveform amplitude 0…160 (IC-9700 CI-V reference)

_TABLE = bytes([0x47, 0x5d, 0x4c, 0x42, 0x66, 0x20, 0x23, 0x46, 0x4e, 0x57, 0x45, 0x3d, 0x67, 0x76, 0x60, 0x41,
                0x62, 0x39, 0x59, 0x2d, 0x68, 0x7e, 0x7c, 0x65, 0x7d, 0x49, 0x29, 0x72, 0x73, 0x78, 0x21, 0x6e,
                0x5a, 0x5e, 0x4a, 0x3e, 0x71, 0x2c, 0x2a, 0x54, 0x3c, 0x3a, 0x63, 0x4f, 0x43, 0x75, 0x27, 0x79,
                0x5b, 0x35, 0x70, 0x48, 0x6b, 0x56, 0x6f, 0x34, 0x32, 0x6c, 0x30, 0x61, 0x6d, 0x7b, 0x2f, 0x4b,
                0x64, 0x38, 0x2b, 0x2e, 0x50, 0x40, 0x3f, 0x55, 0x33, 0x37, 0x25, 0x77, 0x24, 0x26, 0x74, 0x6a,
                0x28, 0x53, 0x4d, 0x69, 0x22, 0x5c, 0x44, 0x31, 0x36, 0x58, 0x3b, 0x7a, 0x51, 0x5f, 0x52])


def passcode(s: str) -> bytes:
    """User name and password as the radio wants them: 16 bytes, each character through Icom's table."""
    out = bytearray(16)
    for i, ch in enumerate(s.encode("ascii", "replace")[:16]):
        p = ch + i
        if p > 126:
            p = 32 + p % 127
        out[i] = _TABLE[p - 32] if 32 <= p <= 126 else 0
    return bytes(out)


def header(length: int, ptype: int, seq: int, my_id: int, radio_id: int) -> bytes:
    return struct.pack("<IHH", length, ptype, seq & 0xFFFF) + struct.pack(">II", my_id, radio_id)


def _cstr(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


class LanError(IOError):
    pass


class _Stream:
    """One UDP stream (control or CI-V): handshake, tracked sequence numbers, idle packets, pings."""

    def __init__(self, host: str, port: int, name: str, timeout: float = 1.0):
        self.name = name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.connect((host, port))
        self.sock.settimeout(timeout)
        ip, lport = self.sock.getsockname()
        self.my_id = (int.from_bytes(socket.inet_aton(ip), "big") << 16 | lport) & 0xFFFFFFFF
        self.radio_id = 0
        self.seq = 1                 # tracked packets
        self.sent: dict[int, bytes] = {}
        self.ping_seq = 0
        self.ping_inner = 0x8304
        self.last_rx = time.monotonic()
        self.last_ping = self.last_idle = 0.0
        self.lock = threading.Lock()

    # --- low level
    def send(self, d: bytes) -> None:
        try:
            self.sock.send(d)
        except OSError:
            pass

    def hdr(self, length: int, ptype: int = 0, seq: int = 0) -> bytes:
        return header(length, ptype, seq, self.my_id, self.radio_id)

    def tracked(self, d: bytes) -> None:
        with self.lock:
            d = d[:6] + struct.pack("<H", self.seq) + d[8:]
            self.sent[self.seq] = d
            self.sent.pop((self.seq - 200) & 0xFFFF, None)
            self.seq = (self.seq + 1) & 0xFFFF
            self.send(d)

    def recv(self, timeout: float) -> bytes | None:
        self.sock.settimeout(timeout)
        try:
            r = self.sock.recv(1500)
        except (socket.timeout, OSError):
            return None
        self.last_rx = time.monotonic()
        return r

    def expect(self, length: int, start: bytes, timeout: float = 1.5) -> bytes:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r = self.recv(max(0.01, end - time.monotonic()))
            if r is None:
                continue
            if self.handle_common(r):
                continue
            if len(r) == length and r[:len(start)] == start:
                return r
        raise LanError(f"{self.name}: la radio non risponde")

    # --- handshake and keep-alive
    def start(self) -> None:
        p3 = self.hdr(0x10, 0x03, 0)
        self.send(p3), self.send(p3)
        r = self.expect(16, bytes([0x10, 0, 0, 0, 0x04, 0]))
        self.radio_id = struct.unpack(">I", r[8:12])[0]
        p6 = self.hdr(0x10, 0x06, 1)
        self.send(p6), self.send(p6)
        self.expect(16, bytes([0x10, 0, 0, 0, 0x06, 0]))

    def ping(self) -> None:
        inner = self.ping_inner
        self.ping_inner = (self.ping_inner + 1) & 0xFFFF
        self.send(self.hdr(0x15, 0x07, self.ping_seq) + bytes([0, os.urandom(1)[0], inner & 0xFF, inner >> 8, 0x06]))
        self.ping_seq = (self.ping_seq + 1) & 0xFFFF

    def idle(self) -> None:
        self.tracked(self.hdr(0x10, 0x00, 0))

    def tick(self, now: float) -> None:
        if now - self.last_ping >= PING_S:
            self.last_ping = now
            self.ping()
        if now - self.last_idle >= IDLE_S:
            self.last_idle = now
            self.idle()

    def handle_common(self, r: bytes) -> bool:
        """Pings, retransmit requests and idles. True when the packet needs nothing else."""
        if len(r) == 21 and r[1:6] == bytes([0, 0, 0, 0x07, 0]):
            if r[16] == 0x00:            # the radio's ping: answer it
                self.send(self.hdr(0x15, 0x07, struct.unpack("<H", r[6:8])[0]) + b"\x01" + r[17:21])
            return True
        if len(r) >= 16 and r[4:6] == b"\x01\x00":
            seqs = [struct.unpack("<H", r[6:8])[0]] if len(r) == 16 else []
            for k in range(16, len(r) - 3, 4):
                a, b = struct.unpack("<HH", r[k:k + 4])
                seqs += [(a + i) & 0xFFFF for i in range(((b - a) & 0xFFFF) + 1)][:20]
            for s in seqs:
                self.send(self.sent.get(s) or self.hdr(0x10, 0x00, s))
            return True
        return len(r) == 16 and r[4:6] == b"\x00\x00"

    def close(self) -> None:
        try:
            p = self.hdr(0x10, 0x05, 0)
            self.send(p), self.send(p)
        finally:
            self.sock.close()


# ------------------------------------------------------------------ packets of the control stream
def login_packet(my_id, radio_id, inner, auth_start: bytes, user: str, password: str) -> bytes:
    p = bytearray(0x80)
    p[:16] = header(0x80, 0, 0, my_id, radio_id)
    p[16:28] = bytes([0, 0, 0, 0x70, 0x01, 0, 0, inner & 0xFF, inner >> 8 & 0xFF, 0]) + auth_start[:2]
    p[64:80], p[80:96] = passcode(user), passcode(password)
    p[96:104] = b"icom-pc\0"
    return bytes(p)


def token_packet(my_id, radio_id, inner, magic: int, token: bytes) -> bytes:
    p = bytearray(0x40)
    p[:16] = header(0x40, 0, 0, my_id, radio_id)
    p[16:26] = bytes([0, 0, 0, 0x30, 0x01, magic, 0, inner & 0xFF, inner >> 8 & 0xFF, 0])
    p[26:32] = token[:6]
    return bytes(p)


def conninfo_packet(my_id, radio_id, inner, token: bytes, guid: bytes, radio_name: str, user: str,
                    rx_audio: bool = False) -> bytes:
    """Asks the radio to open the CI-V stream. Receive audio off by default (WSJT-X uses the USB audio)."""
    p = bytearray(0x90)
    p[:16] = header(0x90, 0, 0, my_id, radio_id)
    p[16:26] = bytes([0, 0, 0, 0x80, 0x01, 0x03, 0, inner & 0xFF, inner >> 8 & 0xFF, 0])
    p[26:32] = token[:6]
    p[32:48] = guid[:16].ljust(16, b"\0")
    p[64:96] = radio_name.encode("ascii", "replace")[:31].ljust(32, b"\0")
    p[96:112] = passcode(user)
    p[112:116] = bytes([1 if rx_audio else 0, 0, 0x04, 0x04])
    p[116:136] = struct.pack(">IIIII", 8000, 8000, CIV_PORT, AUDIO_PORT, 100)
    p[136] = 0x01
    return bytes(p)


def civ_packet(my_id, radio_id, civ_seq: int, data: bytes) -> bytes:
    n = len(data)
    return header(0x15 + n, 0, 0, my_id, radio_id) + bytes([0xC1, n, 0, civ_seq >> 8 & 0xFF, civ_seq & 0xFF]) + data


def civ_open_packet(my_id, radio_id, civ_seq: int, open_: bool = True) -> bytes:
    return header(0x16, 0, 0, my_id, radio_id) + bytes([0xC0, 0x01, 0, civ_seq >> 8 & 0xFF, civ_seq & 0xFF,
                                                         0x05 if open_ else 0x00])


def civ_payload(r: bytes) -> bytes | None:
    """CI-V bytes carried by a packet of the CI-V stream, None for other packets."""
    if len(r) > 21 and r[4:6] == b"\0\0" and r[16] == 0xC1 and r[17] == len(r) - 21:
        return r[21:]
    return None


# ------------------------------------------------------------------ spectrum scope (CI-V 27 00)
def parse_scope_header(rest: bytes, seq_max: int) -> tuple[dict, bytes]:
    """First part of a waveform sweep: scope mode, edges (Hz), out of range; then the waveform bytes, if any."""
    n = 6 if seq_max > 1 and len(rest) == 14 else 5      # 6-byte frequencies of the SQ6EMM firmware
    mode = rest[0] if rest else 0
    f1 = icom.bcd_to_int(rest[1:1 + n])
    f2 = icom.bcd_to_int(rest[1 + n:1 + 2 * n])
    oor = bool(rest[1 + 2 * n]) if len(rest) > 1 + 2 * n else False
    if mode in (0, 2):        # centre (or scroll-C): centre frequency and ± span
        lo, hi = f1 - f2, f1 + f2
    else:                     # fixed (or scroll-F): lower and upper edge
        lo, hi = f1, f2
    info = {"mode": {0: "CENTER", 1: "FIX", 2: "SCROLL-C", 3: "SCROLL-F"}.get(mode, "?"),
            "f_lo_hz": lo, "f_hi_hz": hi, "span_hz": hi - lo, "out_of_range": oor}
    return info, rest[2 + 2 * n:]


class Scope:
    """Puts together the waveform sweeps that the radio sends in several CI-V frames (or one on the LAN)."""

    def __init__(self):
        self.info: dict = {}
        self.buf = bytearray()
        self.spec: np.ndarray | None = None
        self.rows: list[np.ndarray] = []
        self.last_row = 0.0
        self.sweeps = 0

    def feed(self, body: bytes, now: float | None = None) -> bool:
        """body = CI-V body from 27 00 on. True when a sweep is complete."""
        if len(body) < 5 or body[0] != 0x27 or body[1] != 0x00 or body[2] != 0x00:   # MAIN only
            return False
        seq, seq_max = icom.bcd_to_int(body[3:4]), icom.bcd_to_int(body[4:5])
        rest = body[5:]
        if seq == 1:
            self.info, data = parse_scope_header(rest, seq_max)
            self.buf = bytearray(data)
        elif self.info:
            self.buf += rest
        if seq != seq_max or not self.info:
            return False
        if not self.buf:
            return False
        self.spec = np.frombuffer(bytes(self.buf), dtype=np.uint8).astype(float)
        self.sweeps += 1
        now = time.time() if now is None else now
        if now - self.last_row >= SCOPE_ROW_S:
            self.rows = (self.rows + [self.spec])[-SCOPE_ROWS:]
            self.last_row = now
        return True

    def frame(self) -> dict:
        i = self.info
        label = (f"{i.get('mode', '')} ±{i['span_hz'] / 2000:g}k" if i.get("mode") in ("CENTER", "SCROLL-C")
                 else f"{i.get('mode', '')} {i.get('span_hz', 0) / 1000:g}k") if i else "RF"
        return {"spec": self.spec, "rows": list(self.rows), "f_lo_hz": i.get("f_lo_hz"), "f_hi_hz": i.get("f_hi_hz"),
                "label": label, "range": (0.0, float(SCOPE_AMP_MAX)), "rf": True,
                "out_of_range": i.get("out_of_range"), "error": None if self.rows else "in attesa dei dati dello scope"}


# ------------------------------------------------------------------ the session
class IcomLan:
    """Logged-in session with the radio: a background thread keeps it alive and collects the CI-V frames."""

    def __init__(self, host: str, user: str, password: str, port: int = CONTROL_PORT, addr: int = icom.DEFAULT_ADDR,
                 timeout: float = 0.35, civ_port: int = CIV_PORT):
        self.host, self.user, self.password, self.port = host, user, password, int(port)
        self.civ_port = int(civ_port)
        self.addr, self.timeout = int(addr), timeout
        self.ctrl: _Stream | None = None
        self.civ: _Stream | None = None
        self.radio_name = ""
        self.inner = 0
        self.token = b"\0" * 6
        self.civ_seq = 0
        self.error: str | None = None
        self.alive = False
        self.scope = Scope()
        self.scope_on = False
        self.unsolicited: dict = {}
        self._replies: list[tuple[int, int, bytes]] = []
        self._cv = threading.Condition()
        self._qlock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rxbuf = b""

    # --- connection
    def connect(self) -> "IcomLan":
        try:
            self._login()
        except Exception:
            self._shutdown()
            raise
        self.alive = True
        self._thread = threading.Thread(target=self._loop, name="icom-lan", daemon=True)
        self._thread.start()
        return self

    def _next_inner(self) -> int:
        v = self.inner
        self.inner = (self.inner + 1) & 0xFFFF
        return v

    def _login(self) -> None:
        c = self.ctrl = _Stream(self.host, self.port, "controllo")
        c.start()
        c.tracked(login_packet(c.my_id, c.radio_id, self._next_inner(), os.urandom(2), self.user, self.password))
        r = c.expect(96, bytes([0x60, 0, 0, 0, 0, 0]), 2.0)
        if r[48:52] == b"\xff\xff\xff\xfe":
            raise LanError("utente o password di rete sbagliati (menu SET › Network › Network User1)")
        self.token = r[26:32]
        c.tracked(token_packet(c.my_id, c.radio_id, self._next_inner(), 0x02, self.token))
        c.tracked(token_packet(c.my_id, c.radio_id, self._next_inner(), 0x05, self.token))
        guid, token_ok, sent_ci, end = None, False, False, time.monotonic() + 5.0
        rx_audio = False
        while time.monotonic() < end:
            r = c.recv(0.1)
            now = time.monotonic()
            c.tick(now)
            if r is None or c.handle_common(r):
                continue
            n = len(r)
            if n == 64 and r[:6] == bytes([0x40, 0, 0, 0, 0, 0]) and r[21] == 0x05:
                token_ok = True
            elif n >= 168 and r[4:6] == b"\0\0" and struct.unpack("<I", r[:4])[0] == n:   # radio capabilities
                guid = r[66:82]
                self.radio_name = _cstr(r[82:114]) or "IC-9700"
                if n > 148 and r[148]:
                    self.addr = r[148]
            elif n == 80 and r[:6] == bytes([0x50, 0, 0, 0, 0, 0]):
                if r[48:51] == b"\xff\xff\xff":
                    raise LanError("la radio ha rifiutato il collegamento (riprova o spegni e riaccendi la radio)")
            elif n == 144 and r[:6] == bytes([0x90, 0, 0, 0, 0, 0]) and r[96] == 1:   # streams granted
                c.radio_id, c.my_id = struct.unpack(">II", r[8:16])
                self.token = r[26:32]
                break
            if token_ok and guid is not None and not sent_ci:
                c.tracked(conninfo_packet(c.my_id, c.radio_id, self._next_inner(), self.token, guid,
                                          self.radio_name, self.user, rx_audio))
                sent_ci, end = True, time.monotonic() + 4.0
        else:
            if not token_ok:
                raise LanError("login accettato ma la radio non conferma il collegamento")
            raise LanError("la radio non apre lo stream CI-V: forse un altro programma (RS-BA1, wfview) "
                           "è già collegato in rete")
        s = self.civ = _Stream(self.host, self.civ_port, "CI-V")
        s.start()
        s.tracked(civ_open_packet(s.my_id, s.radio_id, self._civ_next(), True))
        self.ctrl.last_token = time.monotonic()

    def _civ_next(self) -> int:
        v = self.civ_seq
        self.civ_seq = (self.civ_seq + 1) & 0xFFFF
        return v

    def _loop(self) -> None:
        c, s = self.ctrl, self.civ
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([c.sock, s.sock], [], [], 0.05)
            except (OSError, ValueError):
                break
            for sock in ready:
                st = c if sock is c.sock else s
                r = st.recv(0)
                if r is None or st.handle_common(r):
                    continue
                if st is s:
                    d = civ_payload(r)
                    if d:
                        self._on_civ(d)
                elif len(r) == 80 and r[:6] == bytes([0x50, 0, 0, 0, 0, 0]) and r[48:51] == b"\xff\xff\xff":
                    self.error, self.alive = "la radio ha chiuso la sessione di rete", False
            now = time.monotonic()
            c.tick(now)
            s.tick(now)
            if now - getattr(c, "last_token", now) >= TOKEN_S:
                c.last_token = now
                c.tracked(token_packet(c.my_id, c.radio_id, self._next_inner(), 0x05, self.token))
            if now - min(c.last_rx, s.last_rx) > LOST_S:
                self.error, self.alive = "la radio non risponde più in rete", False
                break
        self.alive = False

    def _on_civ(self, data: bytes) -> None:
        frames, self._rxbuf = icom.split_frames(self._rxbuf + data)
        for to, frm, body in frames:
            if frm != self.addr:
                continue                                  # our own frames echoed back
            if body[:2] == b"\x27\x00":
                self.scope.feed(body)
                continue
            if to == 0x00:                                # transceive: the radio announces a change
                if body[:1] == b"\x00" and len(body) >= 6:
                    self.unsolicited["freq_hz"] = icom.bcd_to_int(body[1:])
                continue
            with self._cv:
                self._replies.append((to, frm, body))
                self._replies = self._replies[-50:]
                self._cv.notify_all()

    # --- CI-V
    def send_civ(self, data: bytes) -> None:
        s = self.civ
        s.tracked(civ_packet(s.my_id, s.radio_id, self._civ_next(), data))

    def query(self, cmd: int, sub: int | None = None, data: bytes = b"") -> bytes | None:
        """The radio's answer (bytes after cmd/sub), b"" for OK, None for NG or no answer."""
        if not self.alive:
            raise LanError(self.error or "sessione di rete chiusa")
        head = bytes([cmd]) + (bytes([sub]) if sub is not None else b"")
        with self._qlock:
            with self._cv:
                self._replies.clear()
            self.send_civ(icom.frame(cmd, sub, data, self.addr))
            end = time.monotonic() + self.timeout
            with self._cv:
                while True:
                    for to, frm, body in self._replies:
                        if body == bytes([icom.OK]):
                            return b""
                        if body == bytes([icom.NG]):
                            return None
                        if body.startswith(head):
                            return body[len(head):]
                    left = end - time.monotonic()
                    if left <= 0:
                        return None
                    self._cv.wait(left)

    def read_state(self) -> dict:
        st = icom.read_civ(self.query, "lan")
        st["radio_name"] = self.radio_name
        return st

    def send(self, cmd: int, sub: int | None, data: bytes = b"") -> bool:
        return self.query(cmd, sub, data) == b""

    def set_scope(self, on: bool) -> bool:
        """Scope waveform data output (27 11) on or off. Only from the tab's switch."""
        ok = self.send(0x27, 0x11, bytes([1 if on else 0]))
        self.scope_on = bool(on and ok)
        if not on:
            self.scope = Scope()
        return ok

    # --- closing
    def _shutdown(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(1.0)
        c, s = self.ctrl, self.civ
        try:
            if s:
                s.tracked(civ_open_packet(s.my_id, s.radio_id, self._civ_next(), False))
            if c:
                c.tracked(token_packet(c.my_id, c.radio_id, self._next_inner(), 0x01, self.token))
        except Exception:
            pass
        for x in (s, c):
            if x:
                try:
                    x.close()
                except Exception:
                    pass
        self.ctrl = self.civ = None
        self.alive = False

    def close(self) -> None:
        if self.alive and self.scope_on:
            try:
                self.set_scope(False)
            except Exception:
                pass
        self._shutdown()


# ------------------------------------------------------------------ one session per EMELab
_lock = threading.Lock()
_SESSION: IcomLan | None = None
_LAST_FAIL: tuple[tuple, float, str] | None = None


def get(host: str, user: str, password: str, port: int = CONTROL_PORT, civ_port: int = CIV_PORT) -> IcomLan:
    """The open session (logged in on first use, again after a loss, at most once every RETRY_S seconds)."""
    global _SESSION, _LAST_FAIL
    key = (host, user, password, int(port), int(civ_port))
    with _lock:
        s = _SESSION
        if s is not None and (s.host, s.user, s.password, s.port, s.civ_port) == key and s.alive:
            return s
        if s is not None:
            s.close()
            _SESSION = None
        if _LAST_FAIL and _LAST_FAIL[0] == key and time.monotonic() - _LAST_FAIL[1] < RETRY_S:
            raise LanError(_LAST_FAIL[2])
        try:
            _SESSION = IcomLan(host, user, password, port, civ_port=civ_port).connect()
        except Exception as e:
            msg = str(e) or e.__class__.__name__
            _LAST_FAIL = (key, time.monotonic(), msg)
            raise LanError(msg) from e
        _LAST_FAIL = None
        return _SESSION


def current() -> IcomLan | None:
    return _SESSION if _SESSION is not None and _SESSION.alive else None


def stop() -> None:
    global _SESSION
    with _lock:
        if _SESSION is not None:
            _SESSION.close()
        _SESSION = None


atexit.register(stop)
