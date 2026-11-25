import struct

from emelab import wsjtx


def _hdr(t):
    return struct.pack(">III", wsjtx.MAGIC, 2, t)


def _s(v):
    e = v.encode()
    return struct.pack(">I", len(e)) + e


def test_decode_message():
    pkt = (_hdr(2) + _s("WSJT-X") + b"\x01" + struct.pack(">Ii", 40_320_000, -18) + struct.pack(">d", 2.6)
           + struct.pack(">I", 711) + _s("~") + _s("CQ DL7YC JO62") + b"\x00\x00")
    m = wsjtx.parse(pkt)
    assert m["type"] == "decode" and m["snr"] == -18 and m["message"] == "CQ DL7YC JO62" and abs(m["dt"] - 2.6) < 1e-9
    assert m["ms_since_midnight"] // 60000 == 672           # 11:12 UTC


def test_qso_logged_datetime():
    jd = 2461000                       # QDate julian day
    dt = struct.pack(">QIB", jd, 3_600_000, 1)
    pkt = (_hdr(5) + _s("WSJT-X") + dt + _s("OK1KIR") + _s("JN79DW") + struct.pack(">Q", 24_048_200_000) + _s("Q65")
           + _s("-18") + _s("-16") + _s("15") + _s("") + _s("Vlada") + dt + _s("") + _s("IZ0JNY") + _s("JN61")
           + _s("") + _s("") + _s("EME"))
    m = wsjtx.parse(pkt)
    assert m["type"] == "qso_logged" and m["dx_call"] == "OK1KIR" and m["time_on"].hour == 1 and m["prop_mode"] == "EME"


def test_not_wsjtx_and_encoders():
    assert wsjtx.parse(b"hello world, not wsjt-x") is None
    h = wsjtx.highlight("WSJT-X", "OK1DFC", "#ffcc00")
    assert h[:4] == struct.pack(">I", wsjtx.MAGIC) and struct.unpack(">I", h[8:12])[0] == 13
    c = wsjtx.configure("WSJT-X", "Q65", "D", 60)
    assert struct.unpack(">I", c[8:12])[0] == 15


def test_sender_of_messages():
    from emelab.wsjtx_service import sender_of
    assert sender_of("CQ DL7YC JO62") == ("DL7YC", "JO62")
    assert sender_of("IZ0JNY OK1DFC JN79") == ("OK1DFC", "JN79")
    assert sender_of("IZ0JNY OK1DFC -18") == ("OK1DFC", None)
    assert sender_of("CQ EU OZ1LPR JO44") == ("OZ1LPR", "JO44")
    assert sender_of("OK1DFC IZ0JNY RR73")[0] == "IZ0JNY"


def test_service_logs_qso_and_decodes(tmp_path):
    from datetime import datetime, timezone
    from emelab import db as edb
    from emelab.wsjtx_service import Service
    D = edb.DB(tmp_path / "t.sqlite")
    s = Service(lambda: D, lambda: "JN61PM")
    s.on_message({"type": "status", "id": "WSJT-X", "dial_hz": 24_048_000_000, "submode": "D"}, None)
    s.on_message({"type": "decode", "id": "WSJT-X", "new": True, "ms_since_midnight": 3_600_000, "snr": -17, "dt": 2.5,
                  "df": 700, "mode": "~", "message": "CQ OK1KIR JN79", "low_confidence": False, "off_air": False}, None)
    assert D.decodes()[0]["call"] == "OK1KIR" and D.decodes()[0]["band"] == "24G"
    t = datetime(2026, 2, 25, 17, 2, tzinfo=timezone.utc)
    s.on_message({"type": "qso_logged", "id": "WSJT-X", "time_off": t, "time_on": t, "dx_call": "OK1KIR", "dx_grid": "JN79DW",
                  "tx_freq_hz": 24_048_200_000, "mode": "Q65", "report_sent": "-17", "report_rcvd": "-14", "tx_power": "15",
                  "comments": "", "name": "", "operator": "", "my_call": "IZ0JNY", "my_grid": "JN61PM",
                  "exch_sent": "", "exch_rcvd": ""}, None)
    q = D.qsos()[0]
    assert q["call"] == "OK1KIR" and q["band"] == "24G" and q["submode"] == "D" and q["calc"].get("moon_el") is not None
    assert not s.errors
