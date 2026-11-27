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
    assert "10368.100<small>.000" in h and "24048.160<small>.000" in h
    assert "USB-D" in h and ">TX<" in h and "10GHz" in h
    assert ui_radio.fmt_freq(None) == ("----.---", ".---")
    assert ui_radio.fmt_freq(24_048_101_102) == ("24048.101", ".102")
    rows = ui_radio.settings_rows(st)
    assert any(n == "Frequenza selezionata" and v == "10.368.100.000 Hz" for _, n, v in rows)


def test_find_rigctld_in_wsjtx_bin(tmp_path):
    (tmp_path / "rigctld-wsjtx.exe").write_bytes(b"")
    assert icom.find_rigctld([str(tmp_path)]).endswith("rigctld-wsjtx.exe")
    assert icom.rigctld_command(str(tmp_path), "COM4") .endswith("-m 3081 -r COM4 -s 115200 -t 4532")
    assert not icom.rigctld_alive("127.0.0.1", 1)


def test_transverter_offsets_if_144():
    trvs = icom.DEFAULT_TRANSVERTERS
    assert icom.lo_hz(trvs[0]) == 10_224_000_000
    st = {"source": "rigctld", "main_sub": "MAIN", "sel": {"freq_hz": 144_100_000}, "unsel": {"freq_hz": 144_160_000}}
    out = icom.apply_transverters(st, trvs, "10GHz", "24GHz")
    assert out["sel"]["freq_hz"] == 10_368_100_000 and out["sel"]["if_hz"] == 144_100_000
    assert out["unsel"]["freq_hz"] == 24_048_160_000 and out["unsel"]["trv"] == "24GHz"
    # auto: the band from WSJT-X's dial (WSJT-X with its own transverter offset)
    out = icom.apply_transverters(st, trvs, "auto", "OFF", wsjtx_hz=47_088_100_000)
    assert out["sel"]["freq_hz"] == 47_088_100_000 and out["unsel"]["freq_hz"] == 144_160_000
    # auto without a hint and three transverters on 144: nothing is guessed
    assert icom.apply_transverters(st, trvs, "auto", "auto")["sel"]["freq_hz"] == 144_100_000
    # SQ6EMM firmware already gives RF: left alone; outside the IF band: left alone
    st2 = {"source": "serial", "sel": {"freq_hz": 10_368_100_000}, "unsel": {"freq_hz": 432_100_000}}
    out = icom.apply_transverters(st2, trvs, "10GHz", "10GHz")
    assert out["sel"]["freq_hz"] == 10_368_100_000 and out["unsel"]["freq_hz"] == 432_100_000
    assert icom.rf_to_if(24_048_200_000, trvs) == 144_200_000 and icom.rf_to_if(432_000_000, trvs) == 432_000_000


def test_transverter_catalog_kuhne():
    by = {c["model"]: c for c in icom.TRANSVERTER_CATALOG}
    for m, rf in (("MKU 10 G5", 10368), ("MKU 24 G3", 24048), ("MKU 47 G2", 47088)):
        assert by[m]["verified"] and by[m]["rf_mhz"] == rf and by[m]["if_mhz"] == 144
    assert [t["model"] for t in icom.DEFAULT_TRANSVERTERS] == ["Kuhne MKU 10 G5", "Kuhne MKU 24 G3", "Kuhne MKU 47 G2"]
    assert all(t["model"] in [icom.catalog_label(c) for c in icom.TRANSVERTER_CATALOG] for t in icom.DEFAULT_TRANSVERTERS)


def test_rigctld_bare_values_as_hamlib_sends_them():
    """Hamlib's extended answers: the command echoed («get_func: NB»), then the value, often without a label.
    A function that is off must read OFF, not ON (first test on the IC-9700, 2026-11-27)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    answers = {"get_freq": "get_freq:\nFrequency: 144101102", "get_mode": "get_mode:\nMode: USB\nPassband: 3000",
               "get_ptt": "get_ptt:\nPTT: 0", "get_level RFPOWER": "get_level: RFPOWER\n0.250000",
               "get_level AF": "get_level: AF\n0.400000", "get_func NB": "get_func: NB\n0",
               "get_func NR": "get_func: NR\n0", "get_func VOX": "get_func: VOX\n1", "get_vfo": "get_vfo:\nVFO: Main",
               "get_func SATMODE": "get_func: SATMODE\n0"}

    def serve():
        c, _ = srv.accept()
        f = c.makefile("rwb")
        for line in f:
            cmd = line.decode().strip()[2:]
            a = answers.get(cmd)
            f.write(((a + "\nRPRT 0\n") if a else f"{cmd.split()[0]}:\nRPRT -11\n").encode())
            f.flush()
    threading.Thread(target=serve, daemon=True).start()
    st = icom.read({"radio_source": "rigctld", "radio_host": "127.0.0.1", "radio_rport": srv.getsockname()[1]})
    assert st.get("source") == "rigctld", st
    assert st["sel"]["freq_hz"] == 144_101_102 and st["main_sub"] == "MAIN"
    assert st["power_pct"] == 25 and st["af_pct"] == 40
    assert st["nb"] is False and st["nr"] is False and st["vox"] is True and st["satmode"] is False
    assert "comp" not in st and "dualwatch" not in st          # not answered: unknown, not ON
    rows = dict((n, v) for _, n, v in ui_radio.settings_rows(st))
    assert rows["Noise blanker"].startswith("OFF") and rows["Compressore"].startswith("n.d.")
