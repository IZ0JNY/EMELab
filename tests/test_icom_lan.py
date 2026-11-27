# SPDX-License-Identifier: GPL-3.0-or-later
import time

import pytest

from emelab import icom, icom_lan
from tests.fake_icom_lan import FakeRadio


@pytest.fixture
def radio():
    r = FakeRadio()
    yield r
    r.stop()


def _session(r, **kw):
    return icom_lan.IcomLan("127.0.0.1", kw.get("user", r.user), kw.get("password", r.password), r.port,
                            civ_port=r.civ_port).connect()


def test_passcode_known_value():
    # first letters go through Icom's table (kappanhang/wfview): "a" at position 0 → 0x38
    assert icom_lan.passcode("a")[0] == 0x38
    assert len(icom_lan.passcode("x" * 30)) == 16
    assert icom_lan.passcode("")[0] == 0


def test_packets_have_the_right_size():
    assert len(icom_lan.login_packet(1, 2, 0, b"ab", "u", "p")) == 0x80
    assert len(icom_lan.token_packet(1, 2, 0, 5, b"tokenx")) == 0x40
    assert len(icom_lan.conninfo_packet(1, 2, 0, b"tokenx", b"g" * 16, "IC-9700", "u")) == 0x90
    p = icom_lan.civ_packet(1, 2, 7, b"\xfe\xfe\xa2\xe0\x03\xfd")
    assert icom_lan.civ_payload(p) == b"\xfe\xfe\xa2\xe0\x03\xfd"


def test_login_read_and_close(radio):
    s = _session(radio)
    try:
        assert s.radio_name == "IC-9700"
        st = s.read_state()
        assert st["source"] == "lan"
        assert st["sel"]["freq_hz"] == 144_048_101
        assert st["sel"]["mode"] == "USB" and st["sel"]["data"] is True
        assert st["unsel"]["freq_hz"] == 432_065_000
        assert st["nb"] is False and st["nr"] is True and st["split"] == "SPLIT"
        assert st["agc"] == "SLOW"
        time.sleep(0.4)
        assert radio.token_magics[:2] == [0x02, 0x05]
    finally:
        s.close()
    time.sleep(0.1)
    assert radio.civ in radio.closed and radio.ctrl in radio.closed
    assert 0x01 in radio.token_magics                      # token released


def test_wrong_password(radio):
    with pytest.raises(icom_lan.LanError, match="password"):
        _session(radio, password="sbagliata")


def test_busy_radio():
    r = FakeRadio(busy=True)
    try:
        with pytest.raises(icom_lan.LanError, match="altro programma"):
            _session(r)
    finally:
        r.stop()


def test_scope_from_the_radio(radio):
    s = _session(radio)
    try:
        assert s.set_scope(True)
        end = time.time() + 3
        while time.time() < end and not s.scope.rows:
            time.sleep(0.05)
        f = s.scope.frame()
        assert f["f_lo_hz"] == 144_025_000 and f["f_hi_hz"] == 144_075_000
        assert len(f["spec"]) == 500 and f["rows"]
        assert f["label"] == "CENTER ±25k"
        assert s.set_scope(False) and not radio.scope_out
    finally:
        s.close()


def test_read_through_icom_read(radio, monkeypatch):
    sets = {"radio_source": "lan", "radio_lan_host": "127.0.0.1", "radio_lan_user": radio.user,
            "radio_lan_password": radio.password, "radio_lan_port": radio.port}
    monkeypatch.setattr(icom_lan, "CIV_PORT", radio.civ_port)
    monkeypatch.setattr(icom, "_lan", lambda s: icom_lan.get(s["radio_lan_host"], s["radio_lan_user"],
                                                              s["radio_lan_password"], s["radio_lan_port"],
                                                              civ_port=radio.civ_port))
    try:
        st = icom.read(sets)
        assert st["source"] == "lan" and st["sel"]["freq_hz"] == 144_048_101
        ok, msg = icom.write(sets, "nb", True)      # the fake radio answers NG
        assert not ok
    finally:
        icom_lan.stop()


def test_missing_settings_falls_back_to_wsjtx():
    st = icom.read({"radio_source": "lan"}, {"dial_hz": 144_048_000, "mode": "Q65"})
    assert "non impostati" in st["error"]


def test_scope_header_six_bytes():
    rest = b"\x01" + icom.int_to_bcd(10_368_000_000, 6) + icom.int_to_bcd(10_368_200_000, 6) + b"\x00"
    info, data = icom_lan.parse_scope_header(rest, 11)
    assert info["mode"] == "FIX" and info["f_lo_hz"] == 10_368_000_000 and info["span_hz"] == 200_000
    assert data == b""
