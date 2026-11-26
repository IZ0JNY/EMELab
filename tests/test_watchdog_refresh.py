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
