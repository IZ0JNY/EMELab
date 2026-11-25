"""DriverDish telnet server (EA3HMJ): read-only live status in the Tracking tab."""
import socket
import threading
import time

import pytest

from emelab import ea3hmj

STATUS = ("Target:       Moon\r\nTarget Pos AZ:141.341, EL:36.386\r\nDish Pos AZ: 141.095, EL:36.367\r\n"
          "Curr Err AZ: 0.006, EL:0.019\r\nOffset A-Z : -0.240, EL: 0.000\r\nTRACKING ON\r\n")


def test_parse_status_manual_example():
    r = ea3hmj.parse_status("DriverDishServer (c) ea3hmj 2.022\r\nstatus\r\n" + STATUS)
    assert r == {"target": "Moon", "target_az": 141.341, "target_el": 36.386, "dish_az": 141.095, "dish_el": 36.367,
                 "err_az": 0.006, "err_el": 0.019, "off_az": -0.24, "off_el": 0.0, "tracking": True}
    assert ea3hmj.parse_status("TRACKING OFF\r\n")["tracking"] is False
    assert ea3hmj.parse_status("garbage") == {}


def test_yes_no_and_geometry():
    assert ea3hmj.parse_yes_no("moving\r\nTrue") is True
    assert ea3hmj.parse_yes_no("Not moving") is False
    assert ea3hmj.parse_yes_no("") is None
    assert abs(ea3hmj.angle_between(10, 0, 11, 0) - 1.0) < 1e-9
    assert abs(ea3hmj.angle_between(0, 89, 180, 89) - 2.0) < 1e-9
    assert abs(ea3hmj.pointing_loss_db(0.1, 1.0) - 0.12) < 1e-9


def test_commands_that_move_the_dish_are_refused():
    for bad in ("az+5", "el-2", "traking on", "traking off", "stop", "ao+0.1", "exit; az+1"):
        with pytest.raises(ValueError):
            ea3hmj.driverdish_query([bad], port=1)       # refused before any connection


def _fake_driverdish(received):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0)); srv.listen(2)

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            f = c.makefile("rb")
            c.sendall(b"DriverDishServer (c) ea3hmj 2.022\r\n'help' to list options\r\n")
            for line in f:
                cmd = line.decode().strip()
                received.append(cmd)
                if cmd == "status":
                    c.sendall(STATUS.encode())
                elif cmd == "moving":
                    c.sendall(b"False\r\n")
                elif cmd == "exit":
                    break
            c.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv


def test_monitor_reads_status_and_sends_only_read_commands():
    received = []
    srv = _fake_driverdish(received)
    mon = ea3hmj.DriverDishMonitor("127.0.0.1", srv.getsockname()[1], period=0.2)
    try:
        t0 = time.monotonic()
        while (mon.last is None or len(mon.history) < 2) and time.monotonic() - t0 < 10:
            time.sleep(0.05)
        assert mon.last and mon.last["dish_az"] == 141.095 and mon.last["tracking"] is True
        assert mon.last["moving"] is False and mon.connected and mon.error is None
    finally:
        mon.stop(); srv.close()
    assert received and set(received) <= set(ea3hmj.READ_COMMANDS)


def test_monitor_reports_unreachable_driverdish():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    mon = ea3hmj.DriverDishMonitor("127.0.0.1", port)
    try:
        t0 = time.monotonic()
        while mon.error is None and time.monotonic() - t0 < 5:
            time.sleep(0.05)
        assert mon.error and mon.last is None and not mon.connected
    finally:
        mon.stop()


def test_parse_status_real_driverdish_344():
    # DriverDish.App 3.4.4268 on IZ0JNY's EME PC, 25-11-2026 (no comma between AZ and EL, «Offset AZ:»)
    raw = ("DriverDishServer (c) ea3hmj 2.022\r\n'help' to list options\r\n\r\nTarget:       Sun\r\n"
           "Target Pos AZ:257.608   EL:-17.172\r\nDish Pos AZ:  124.663   EL:86.411\r\n"
           "Curr Err AZ:  133.115   EL:-103.582\r\nOffset AZ:    0.170     EL:0.000\r\nTRACKING OFF\r\n")
    assert ea3hmj.parse_status(raw) == {"target": "Sun", "target_az": 257.608, "target_el": -17.172, "dish_az": 124.663,
                                        "dish_el": 86.411, "err_az": 133.115, "err_el": -103.582, "off_az": 0.17,
                                        "off_el": 0.0, "tracking": False}


def test_tracking_tab_live_in_english(tmp_path, monkeypatch):
    pytest.importorskip("erfa")
    pytest.importorskip("streamlit")
    import os
    from streamlit.testing.v1 import AppTest
    from emelab import i18n
    from tests.test_language_consistency import ITALIAN_MARKERS, ROOT, _demo_station, _visible_texts
    received = []
    srv = _fake_driverdish(received)
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "en")
    _demo_station(tmp_path)
    from emelab import settings
    settings.save_settings(dd_host="127.0.0.1", dd_port=srv.getsockname()[1], dd_live=True)
    try:
        at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
        at.run()
        time.sleep(1.5)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        texts = _visible_texts(at)
        labels = [t for k, t in texts if k == "metric"]
        assert "Dish ↔ Moon" in labels and "DriverDish target" in labels
        live = [(k, t) for k, t in texts if "DriverDish" in t or "Moon" in t]
        bad = [(k, t[:120], m) for k, t in live for m in ITALIAN_MARKERS if m in t]
        assert not bad, bad
    finally:
        i18n.set_lang("it")
        srv.close()
    assert set(received) <= set(ea3hmj.READ_COMMANDS)
