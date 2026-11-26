from datetime import datetime, timedelta, timezone

from emelab import ui_live, watchdog

NOW = datetime(2026, 11, 26, 9, 40, tzinfo=timezone.utc)


def test_note_loss_marks_a_counter_that_moved():
    n, t = ui_live.note_loss(None, None, {"loss_count": 4}, NOW)
    assert (n, t) == (4, None)                                  # first read: nothing to compare with
    assert ui_live.note_loss(4, None, {"loss_count": 4}, NOW) == (4, None)
    assert ui_live.note_loss(4, None, {"loss_count": 5}, NOW) == (5, NOW)
    assert ui_live.note_loss(5, NOW, {"error": "x"}, NOW) == (5, NOW)


def test_gpsdo_recent_loss_is_a_warning_then_ok():
    g = {"gps_ok": True, "pll_ok": True, "loss_utc": NOW - timedelta(minutes=2)}
    st = {i["key"]: i["state"] for i in watchdog.checks(now=NOW, gpsdo=g, gpsdo_on=True)}
    assert st["gpsdo"] == "warn"
    g["loss_utc"] = NOW - timedelta(minutes=11)
    st = {i["key"]: i["state"] for i in watchdog.checks(now=NOW, gpsdo=g, gpsdo_on=True)}
    assert st["gpsdo"] == "ok"


def test_driverdish_refused_tells_where_to_switch_telnet_on():
    err = "[WinError 10061] No connection could be made because the target machine actively refused it"
    item = watchdog.checks(now=NOW, dd=None, dd_err=err, dd_on=True)[0]
    assert item["state"] == "bad" and watchdog.TELNET_HINT in item["msg"]
    item = watchdog.checks(now=NOW, dd=None, dd_err="timed out", dd_on=True)[0]
    assert watchdog.TELNET_HINT not in item["msg"]


def test_camera_simulator_is_flagged_not_ok():
    item = watchdog.checks(now=NOW, cam_on=True, cam_age_s=0.5, cam_kind="sim")[0]
    assert item["state"] == "warn" and "simulatore" in item["msg"]
    assert watchdog.checks(now=NOW, cam_on=True, cam_age_s=0.5)[0]["state"] == "ok"


def test_dd_target_sun():
    assert ui_live.dd_target_is_sun({"target": "Sun"}) and not ui_live.dd_target_is_sun({"target": "Moon"})
    assert not ui_live.dd_target_is_sun(None)


def test_gpsdo_without_fix_is_bad_even_if_lock_bit_is_on():
    g = {"gps_ok": True, "pll_ok": True, "pvt": {"fix_type": 0, "fix_ok": False, "sats_used": 0}}
    item = watchdog.checks(now=NOW, gpsdo=g, gpsdo_on=True)[0]
    assert item["state"] == "bad" and "senza fix" in item["msg"]
    g["pvt"] = {"fix_type": 3, "fix_ok": True, "sats_used": 9}
    assert watchdog.checks(now=NOW, gpsdo=g, gpsdo_on=True)[0]["state"] == "ok"


def test_clock_state_reads_in_background(monkeypatch):
    import time
    from emelab import timesync, ui_wsjtx_panel as p
    calls = []
    monkeypatch.setattr(timesync, "bkt_running", lambda: calls.append(1) or {"running": len(calls) == 1, "process": "x"})
    monkeypatch.setattr(p, "_CLOCK", {"bkt": None, "t_proc": 0.0, "ntp": None, "t_ntp": 0.0, "busy": False})
    assert p.clock_state()["bkt"]["running"] is True            # first call reads at once
    p._CLOCK["t_proc"] -= p.PROC_EVERY_S + 1                     # 5 s later: BktTimeSync closed
    p.clock_state()
    for _ in range(50):
        if not p._CLOCK["busy"]:
            break
        time.sleep(0.02)
    assert p.clock_state()["bkt"]["running"] is False
