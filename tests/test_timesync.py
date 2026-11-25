"""PC clock check: BktTimeSync process detection, SNTP offset maths, verdict and pop-up alerts (read-only)."""
import struct


def _ntp(t: float) -> bytes:
    sec = int(t) + 2_208_988_800
    return struct.pack(">II", sec, int((t - int(t)) * 2 ** 32))


def test_find_process():
    from emelab import timesync as ts
    assert ts.find_process(["System", "svchost.exe", "BktTimeSync.exe", "wsjtx.exe"]) == "BktTimeSync.exe"
    assert ts.find_process(["bkttimesync.exe"]) == "bkttimesync.exe"
    assert ts.find_process(["BktTimeSyncGPS.exe", "wsjtx.exe"]) is None
    assert ts.find_process([]) is None


def test_offset_from_packet_and_verdict():
    from emelab import timesync as ts
    t1, t4 = 1000.0, 1000.1                       # 100 ms round trip, server 0.3 s ahead of the PC
    pkt = bytes([0x24, 2]) + b"\0" * 30 + _ntp(1000.35) + _ntp(1000.35)
    r = ts.offset_from_packet(pkt, t1, t4)
    assert abs(r["offset_s"] - 0.3) < 1e-6 and abs(r["delay_s"] - 0.1) < 1e-6 and r["stratum"] == 2
    bad = bytes([0x24, 0]) + b"\0" * 46
    try:
        ts.offset_from_packet(bad, t1, t4)
        assert False
    except ValueError:
        pass
    assert [ts.verdict(x) for x in (0.1, -0.5, 0.7, -1.4, None)] == ["ok", "ok", "warn", "bad", None]


def test_ntp_offset_unreachable():
    from emelab import timesync as ts
    r = ts.ntp_offset("invalid.invalid", timeout=0.5)
    assert r["error"] and r["server"] == "invalid.invalid"


def test_clock_alerts():
    from emelab import ui_wsjtx_panel as p
    ok = {"bkt": {"running": True, "process": "BktTimeSync.exe"},
          "ntp": {"offset_s": 0.109, "delay_s": 0.02, "stratum": 2, "server": "pool.ntp.org"}}
    assert p.clock_alerts(ok) == []
    off = {"bkt": {"running": False, "process": None}, "ntp": {**ok["ntp"], "offset_s": -0.8}}
    assert [a["key"] for a in p.clock_alerts(off)] == ["bktsync", "clock"]
    assert p.clock_alerts({"bkt": {"running": None, "process": None}, "ntp": {"error": "x", "server": "s"}}) == []
