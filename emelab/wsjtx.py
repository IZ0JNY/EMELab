# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Link with WSJT-X through its UDP «network server» protocol (Settings → Reporting → UDP Server).

WSJT-X sends, as Qt QDataStream big-endian datagrams with magic 0xadbccbda and schema 2: Heartbeat, Status (dial
frequency, mode, submode, DX call/grid, transmitting…), Decode (time, SNR, DT, DF, message), QSOLogged and
LoggedADIF (when you press OK in «Log QSO») and Close. A server may send back Replay, HighlightCallsign (colour a
callsign in the Band Activity window), Configure (mode, submode, T/R period, frequency tolerance, DX call and grid)
and Location.

Protocol: WSJT-X Network/NetworkMessage.hpp by Joe Taylor K1JT, Bill Somerville G4WJS and the WSJT Development
Group (field order cross-checked with the wsjtx-go library by Chris Keller KØSWE). To share the stream with
other programs (JTAlert, GridTracker…) set WSJT-X to a multicast address such as 224.0.0.1 and let EMELab join it.
"""
from __future__ import annotations

import socket
import struct
import threading
from datetime import datetime, timedelta, timezone

MAGIC = 0xADBCCBDA
SCHEMA = 2
NULL = 0xFFFFFFFF
TYPES = {0: "heartbeat", 1: "status", 2: "decode", 3: "clear", 5: "qso_logged", 6: "close", 10: "wspr_decode",
         12: "logged_adif"}


class _R:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def _take(self, n):
        if self.i + n > len(self.b):
            raise ValueError("short datagram")
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def u8(self):
        return self._take(1)[0]

    def b_(self):
        return self.u8() != 0

    def u32(self):
        return struct.unpack(">I", self._take(4))[0]

    def i32(self):
        return struct.unpack(">i", self._take(4))[0]

    def u64(self):
        return struct.unpack(">Q", self._take(8))[0]

    def f64(self):
        return struct.unpack(">d", self._take(8))[0]

    def s(self):
        n = self.u32()
        return "" if n == NULL else self._take(n).decode("utf-8", "replace")

    def qdatetime(self):
        jd = self.u64()
        ms = self.u32()
        spec = self.u8()
        off = self.i32() if spec == 2 else 0
        t = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=jd - 2440588, milliseconds=ms)
        if spec == 2:
            t -= timedelta(seconds=off)
        return t                      # spec 0 (local time) is taken as UTC: WSJT-X sends UTC


def parse(data: bytes) -> dict | None:
    """One datagram → {"type": …, fields…}; None if it is not WSJT-X or a type EMELab does not use."""
    r = _R(data)
    try:
        if r.u32() != MAGIC:
            return None
        r.u32()                                   # schema
        t = r.u32()
        kind = TYPES.get(t)
        if kind is None:
            return None
        m = {"type": kind, "id": r.s()}
        if kind == "heartbeat":
            m.update(max_schema=r.u32(), version=r.s(), revision=r.s())
        elif kind == "status":
            m.update(dial_hz=r.u64(), mode=r.s(), dx_call=r.s(), report=r.s(), tx_mode=r.s(), tx_enabled=r.b_(),
                     transmitting=r.b_(), decoding=r.b_(), rx_df=r.u32(), tx_df=r.u32(), de_call=r.s(), de_grid=r.s(),
                     dx_grid=r.s(), tx_watchdog=r.b_(), submode=r.s(), fast_mode=r.b_(), special_mode=r.u8(),
                     freq_tolerance=r.u32(), tr_period=r.u32(), config_name=r.s())
            try:
                m["tx_message"] = r.s()
            except ValueError:
                pass
        elif kind == "decode":
            m.update(new=r.b_(), ms_since_midnight=r.u32(), snr=r.i32(), dt=r.f64(), df=r.u32(), mode=r.s(),
                     message=r.s(), low_confidence=r.b_(), off_air=r.b_())
        elif kind == "qso_logged":
            m.update(time_off=r.qdatetime(), dx_call=r.s(), dx_grid=r.s(), tx_freq_hz=r.u64(), mode=r.s(),
                     report_sent=r.s(), report_rcvd=r.s(), tx_power=r.s(), comments=r.s(), name=r.s(),
                     time_on=r.qdatetime(), operator=r.s(), my_call=r.s(), my_grid=r.s(), exch_sent=r.s(),
                     exch_rcvd=r.s())
            try:
                m["prop_mode"] = r.s()
            except ValueError:
                pass
        elif kind == "logged_adif":
            m.update(adif=r.s())
        return m
    except ValueError:
        return None


# ------------------------------------------------------------------ messages to WSJT-X
class _W:
    def __init__(self, t: int):
        self.b = bytearray(struct.pack(">III", MAGIC, SCHEMA, t))

    def s(self, v: str):
        e = (v or "").encode("utf-8")
        self.b += struct.pack(">I", NULL if not e else len(e)) + e
        return self

    def u32(self, v):
        self.b += struct.pack(">I", int(v))
        return self

    def b_(self, v):
        self.b += bytes([1 if v else 0])
        return self

    def color(self, rgb: str | None):
        """QColor: spec (0 invalid, 1 RGB), alpha, r, g, b, pad — 16-bit values."""
        if not rgb:
            self.b += struct.pack(">bHHHHH", 0, 0, 0, 0, 0, 0)
        else:
            r, g, b = (int(rgb.lstrip("#")[i:i + 2], 16) * 257 for i in (0, 2, 4))
            self.b += struct.pack(">bHHHHH", 1, 0xFFFF, r, g, b, 0)
        return self


def replay(client_id: str) -> bytes:
    return bytes(_W(7).s(client_id).b)


def highlight(client_id: str, call: str, bg: str | None, fg: str | None = "#000000", last_only: bool = False) -> bytes:
    """Colour a callsign in WSJT-X's Band Activity window (bg None = remove the highlight)."""
    return bytes(_W(13).s(client_id).s(call).color(bg).color(fg if bg else None).b_(last_only).b)


def configure(client_id: str, mode: str = "Q65", submode: str = "", tr_period: int = 0, freq_tol: int = 0,
              dx_call: str = "", dx_grid: str = "", generate: bool = False) -> bytes:
    """Set mode/submode/T-R period/tolerance/DX in WSJT-X (empty or 0 = leave unchanged)."""
    w = _W(15).s(client_id).s(mode).u32(freq_tol or NULL).s(submode).b_(False).u32(tr_period or NULL).u32(NULL)
    return bytes(w.s(dx_call).s(dx_grid).b_(generate).b)


# ------------------------------------------------------------------ listener
class Listener:
    """Background UDP listener (default 127.0.0.1:2237, or a multicast group shared with other programs).
    Calls on_message(msg, addr) for every parsed datagram; remembers the last client address to answer it."""

    def __init__(self, on_message, host: str = "127.0.0.1", port: int = 2237, multicast: str | None = None):
        self.on_message, self.host, self.port, self.multicast = on_message, host, port, multicast
        self.sock = None
        self.clients: dict[str, tuple] = {}
        self._stop = threading.Event()

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.multicast:
            s.bind(("", self.port))
            mreq = struct.pack("4s4s", socket.inet_aton(self.multicast), socket.inet_aton("0.0.0.0"))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        else:
            s.bind((self.host, self.port))
        s.settimeout(1.0)
        self.sock = s
        threading.Thread(target=self._run, name="wsjtx-udp", daemon=True).start()
        return self

    def _run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            m = parse(data)
            if m:
                self.clients[m["id"]] = addr
                try:
                    self.on_message(m, addr)
                except Exception:
                    pass

    def send(self, client_id: str, payload: bytes) -> bool:
        addr = self.clients.get(client_id)
        if not addr or self.sock is None:
            return False
        self.sock.sendto(payload, addr)
        return True

    def stop(self):
        self._stop.set()
        if self.sock:
            self.sock.close()
