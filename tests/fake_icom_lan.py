# SPDX-License-Identifier: GPL-3.0-or-later
"""A pretend IC-9700 on the network (localhost UDP) for the tests of emelab/icom_lan.py."""
from __future__ import annotations

import select
import socket
import struct
import threading
import time

from emelab import icom
from emelab.icom_lan import header, passcode

RADIO_ID = 0x1D2E3F40


class FakeRadio:
    def __init__(self, user="ivan", password="segreto", freq_hz=144_048_101, busy=False):
        self.user, self.password, self.busy = user, password, busy
        self.freq_hz = freq_hz
        self.ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ctrl.bind(("127.0.0.1", 0))
        self.civ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.civ.bind(("127.0.0.1", 0))
        self.port, self.civ_port = self.ctrl.getsockname()[1], self.civ.getsockname()[1]
        self.peer = {}           # sock → (addr, client id)
        self.seq = {}
        self.received: list[bytes] = []      # CI-V frames from the client
        self.ping_answers = 0
        self.scope_out = False
        self.token_magics: list[int] = []
        self.closed = []
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def stop(self):
        self._stop.set()
        self.t.join(1)
        self.ctrl.close(), self.civ.close()

    def _hdr(self, sock, length, ptype=0, seq=None):
        if seq is None:
            seq = self.seq.get(sock, 1)
            self.seq[sock] = seq + 1
        return header(length, ptype, seq, RADIO_ID, self.peer[sock][1])

    def _send(self, sock, d):
        sock.sendto(d, self.peer[sock][0])

    def _civ_reply(self, body: bytes) -> bytes | None:
        a = icom.DEFAULT_ADDR
        table = {b"\x25\x00": b"\x25\x00" + icom.int_to_bcd(self.freq_hz, 5),
                 b"\x25\x01": b"\x25\x01" + icom.int_to_bcd(432_065_000, 5),
                 b"\x26\x00": b"\x26\x00\x01\x01\x01", b"\x26\x01": b"\x26\x01\x03\x00\x02",
                 b"\x14\x01": b"\x14\x01\x01\x28", b"\x16\x22": b"\x16\x22\x00", b"\x16\x40": b"\x16\x40\x01",
                 b"\x0f": b"\x0f\x01", b"\x16\x12": b"\x16\x12\x03"}
        for k, v in table.items():
            if body == k:
                return icom.frame(v[0], None, v[1:], to=icom.CTRL_ADDR, frm=a)
        if body[:2] == b"\x27\x11":
            self.scope_out = bool(body[2])
            return icom.frame(icom.OK, None, b"", to=icom.CTRL_ADDR, frm=a)
        return icom.frame(icom.NG, None, b"", to=icom.CTRL_ADDR, frm=a)

    def _civ_out(self, data: bytes):
        n = len(data)
        self._send(self.civ, self._hdr(self.civ, 0x15 + n) + bytes([0xC1, n, 0, 0, 1]) + data)

    def scope_sweep(self, centre=144_050_000, half_span=25_000):
        a = icom.DEFAULT_ADDR
        head = b"\x27\x00\x00\x01\x11" + b"\x00" + icom.int_to_bcd(centre, 5) + icom.int_to_bcd(half_span, 5) + b"\x00"
        self._civ_out(icom.frame(head[0], None, head[1:], to=icom.CTRL_ADDR, frm=a))
        for k in range(2, 12):
            wave = bytes((20 + (i * 7 + k) % 30 + (120 if k == 6 and 20 <= i < 24 else 0)) for i in range(50))
            body = b"\x27\x00\x00" + icom.int_to_bcd(k, 1) + b"\x11" + wave
            self._civ_out(icom.frame(body[0], None, body[1:], to=icom.CTRL_ADDR, frm=a))

    def _run(self):
        last_ping = 0
        while not self._stop.is_set():
            r, _, _ = select.select([self.ctrl, self.civ], [], [], 0.02)
            for sock in r:
                try:
                    d, addr = sock.recvfrom(1500)
                except OSError:
                    continue
                self._handle(sock, d, addr)
            if self.scope_out and self.civ in self.peer:
                self.scope_sweep()
            if time.monotonic() - last_ping > 0.1:
                last_ping = time.monotonic()
                for sock in list(self.peer):
                    self._send(sock, self._hdr(sock, 0x15, 7, 9) + bytes([0, 0x57, 0x2B, 0x12, 0x00]))

    def _handle(self, sock, d, addr):
        ptype = struct.unpack("<H", d[4:6])[0]
        if len(d) == 16 and ptype == 3:
            self.peer[sock] = (addr, struct.unpack(">I", d[8:12])[0])
            self._send(sock, self._hdr(sock, 0x10, 4, 0))
            return
        if sock not in self.peer:
            return
        if len(d) == 16 and ptype == 6:
            self._send(sock, self._hdr(sock, 0x10, 6, 1))
        elif len(d) == 16 and ptype == 5:
            self.closed.append(sock)
        elif len(d) == 21 and ptype == 7:
            if d[16] == 1:
                self.ping_answers += 1
            else:
                self._send(sock, self._hdr(sock, 0x15, 7, struct.unpack("<H", d[6:8])[0]) + b"\x01" + d[17:21])
        elif sock is self.ctrl and len(d) == 0x80:
            ok = d[64:80] == passcode(self.user) and d[80:96] == passcode(self.password)
            p = bytearray(96)
            p[:16] = self._hdr(sock, 0x60)
            p[26:32] = b"TOKEN1"
            if not ok:
                p[48:52] = b"\xff\xff\xff\xfe"
            self._send(sock, bytes(p))
        elif sock is self.ctrl and len(d) == 0x40:
            self.token_magics.append(d[21])
            p = bytearray(64)
            p[:16] = self._hdr(sock, 0x40)
            p[16:22] = bytes([0, 0, 0, 0x30, 0x02, d[21]])
            self._send(sock, bytes(p))
            if d[21] == 0x05 and self.token_magics.count(0x05) == 1:
                c = bytearray(168)
                c[:16] = self._hdr(sock, 168)
                c[16:20] = b"\0\0\0\x98"
                c[66:82] = b"GUID-0123456789A"
                c[82:89] = b"IC-9700"
                c[148] = icom.DEFAULT_ADDR
                self._send(sock, bytes(c))
        elif sock is self.ctrl and len(d) == 0x90:
            if self.busy:
                return
            p = bytearray(144)
            p[:16] = self._hdr(sock, 0x90)
            p[26:32] = b"TOKEN2"
            p[64:71] = b"IC-9700"
            p[96] = 1
            self._send(sock, bytes(p))
        elif sock is self.civ and len(d) > 21 and d[16] == 0xC1:
            for to, frm, body in icom.split_frames(d[21:])[0]:
                self.received.append(body)
                rep = self._civ_reply(body)
                if rep:
                    self._civ_out(rep)
