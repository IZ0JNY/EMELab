"""📟 Radio tab: CI-V frames and BCD (5 and 6 bytes), a simulated IC-9700, rigctld, the display and the commands."""
import socket
import threading

from emelab import icom, ui_radio


def test_bcd_frequencies_5_and_6_bytes():
    assert icom.bcd_to_int(bytes([0x00, 0x40, 0x17, 0x44, 0x01])) == 144_174_000
    assert icom.freq_bytes(144_174_000) == bytes([0x00, 0x40, 0x17, 0x44, 0x01])
    hz = 10_368_100_000                                  # SQ6EMM firmware: transverter RF, 6 bytes
    b = icom.freq_bytes(hz)
    assert len(b) == 6 and icom.bcd_to_int(b) == hz
    assert icom.bcd_to_int(icom.freq_bytes(24_048_160_000)) == 24_048_160_000
    assert icom.bcd_to_int(bytes([0x02, 0x55]), little=False) == 255


def test_split_frames_skips_echo_and_partial():
    f = icom.frame(0x03)
    ans = bytes([0xFE, 0xFE, 0xE0, 0xA2, 0x03]) + icom.freq_bytes(432_065_000) + bytes([0xFD])
    frames, rest = icom.split_frames(f + ans + b"\xFE\xFE\xE0")
    assert frames[0] == (0xA2, 0xE0, bytes([0x03]))
    assert frames[1][2][0] == 0x03 and icom.bcd_to_int(frames[1][2][1:]) == 432_065_000
    assert rest == b"\xFE\xFE\xE0"


def test_meter_scales():
    assert icom.s_units(0) == "S0" and icom.s_units(120) == "S9" and icom.s_units(241) == "S9+60dB"
    assert icom.swr(0) == 1.0 and icom.swr(80) == 2.0
    assert icom.po_percent(213) == 100
    assert icom.mode_label("USB", True) == "USB-D" and icom.mode_label("CW", True) == "CW"


class FakeRadio:
    """A simulated IC-9700 on the serial line: echoes the command (CI-V USB Echo Back) and answers."""

    def __init__(self):
        self.out = b""
        self.freq = {0: 10_368_100_000, 1: 24_048_160_000}
        self.sets = []

    def reset_input_buffer(self):
        pass

    def close(self):
        pass

    def write(self, req):
        self.out += req                                   # echo
        body = req[4:-1]
        cmd, rest = body[0], body[1:]
        ans = None
        if cmd == 0x25:
            ans = bytes([0x25, rest[0]]) + icom.freq_bytes(self.freq[rest[0]])
        elif cmd == 0x26:
            ans = bytes([0x26, rest[0], 0x01, 0x01, 0x01])
        elif cmd == 0x15 and rest[:1] == b"\x02":
            ans = bytes([0x15, 0x02, 0x01, 0x20])
        elif cmd == 0x16 and rest[:1] == b"\x02":
            ans = bytes([0x16, 0x02, 0x01])
        elif cmd == 0x14 and rest[:1] == b"\x0a" and len(rest) == 1:
            ans = bytes([0x14, 0x0A, 0x01, 0x28])
        elif cmd == 0x1C:
            ans = bytes([0x1C, 0x00, 0x00])
        elif cmd in (0x05, 0x06) or (cmd == 0x14 and len(rest) == 3):
            self.sets.append(body)
            ans = bytes([0xFB])
        else:
            ans = bytes([0xFA])
        self.out += bytes([0xFE, 0xFE, 0xE0, 0xA2]) + ans + bytes([0xFD])

    def read(self, n):
        b, self.out = self.out[:n], self.out[n:]
        return b


def _serial_with(radio, monkeypatch):
    def enter(self):
        self.ser = radio
        return self
    monkeypatch.setattr(icom.CivSerial, "__enter__", enter)


def test_read_state_from_simulated_radio(monkeypatch):
    r = FakeRadio()
    _serial_with(r, monkeypatch)
    st = icom.read({"radio_source": "serial", "radio_port": "COM9"})
    assert st["source"] == "serial" and "error" not in st
    assert st["sel"]["freq_hz"] == 10_368_100_000 and st["unsel"]["freq_hz"] == 24_048_160_000
    assert st["sel"]["mode"] == "USB" and st["sel"]["data"] and st["sel"]["filter"] == "FIL1"
    assert st["s_meter"] == "S9" and st["preamp"] is True and st["power_pct"] == 50 and st["tx"] is False
    ok, _ = icom.write({"radio_source": "serial", "radio_port": "COM9"}, "power_pct", 20)
    assert ok and r.sets[-1] == bytes([0x14, 0x0A, 0x00, 0x51])
    ok, _ = icom.write({"radio_source": "serial", "radio_port": "COM9"}, "freq_hz", 10_368_200_000)
    assert ok and icom.bcd_to_int(r.sets[-1][1:]) == 10_368_200_000


def test_busy_port_falls_back_to_wsjtx(monkeypatch):
    def enter(self):
        raise PermissionError("Accesso negato")
    monkeypatch.setattr(icom.CivSerial, "__enter__", enter)
    st = icom.read({"radio_source": "serial", "radio_port": "COM3"},
                   {"dial_hz": 24_048_000_000, "mode": "Q65", "submode": "E", "transmitting": True})
    assert st["source"] == "wsjtx" and "WSJT-X" in st["error"]
    assert st["sel"]["freq_hz"] == 24_048_000_000 and st["tx"] is True


def test_wsjtx_only_never_writes():
    ok, _ = icom.write({"radio_source": "wsjtx"}, "power_pct", 10)
    assert not ok


def test_rigctld_client():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    answers = {"get_freq": "Frequency: 10368100000", "get_mode": "Mode: PKTUSB\nPassband: 3000",
               "get_ptt": "PTT: 0", "get_level STRENGTH": "STRENGTH: -6", "get_level RFPOWER": "RFPOWER: 0.5",
               "get_func NB": "Func Status: 1", "get_vfo": "VFO: Main"}

    def serve():
        c, _ = srv.accept()
        f = c.makefile("rwb")
        for line in f:
            cmd = line.decode().strip()[2:]
            a = answers.get(cmd)
            f.write(((cmd + ":\n" + a + "\nRPRT 0\n") if a else "RPRT -11\n").encode())
            f.flush()
    threading.Thread(target=serve, daemon=True).start()
    st = icom.read({"radio_source": "rigctld", "radio_host": "127.0.0.1", "radio_rport": srv.getsockname()[1]})
    assert st.get("source") == "rigctld", st
    assert st["sel"]["freq_hz"] == 10_368_100_000 and st["sel"]["mode"] == "USB" and st["sel"]["data"]
    assert st["power_pct"] == 50 and st["nb"] is True and st["s_meter"] == "S8" and st["main_sub"] == "MAIN"


def test_display_html():
    st = {"source": "serial", "main_sub": "MAIN", "tx": True, "preamp": True, "agc": "MID",
          "sel": {"freq_hz": 10_368_100_000, "mode": "USB", "data": True, "filter": "FIL1"},
          "unsel": {"freq_hz": 24_048_160_000, "mode": "USB", "data": True}, "po_pct": 50, "swr": 1.2}
    h = ui_radio.render_display(st)
    assert "10368.100<small>.00" in h and "24048.160<small>.00" in h
    assert "USB-D" in h and ">TX<" in h and "10GHz" in h
    assert ui_radio.fmt_freq(None) == ("----.---", ".--")
    rows = ui_radio.settings_rows(st)
    assert any(n == "Frequenza selezionata" and v == "10.368.100.000 Hz" for _, n, v in rows)
