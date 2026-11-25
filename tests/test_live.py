"""🔴 Live tab, rotor corrections through DriverDish offsets (limits) and watchdogs."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from emelab import rotor, watchdog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DD = {"target": "Moon", "tracking": True, "moving": False, "dish_el": 30.0, "off_az": 0.17, "off_el": 0.0}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    rotor._state.update(last_t=0.0, added_az=0.0, added_el=0.0, log=[])
    return tmp_path


def test_only_offset_commands_within_step():
    assert rotor.command("az", 0.0123) == "ao+0.012" and rotor.command("el", -0.05) == "eo-0.050"
    for bad in ("az+1.000", "el-0.100", "tracking on", "stop", "ao + 0.010", "ao+0.300", "ao+1"):
        with pytest.raises(ValueError):
            rotor.check_command(bad)
    assert rotor.check_command("eo-0.250") == "eo-0.250"


def test_plan_converts_azimuth_and_clips():
    p = rotor.plan(0.05, -0.02, 60.0)
    assert p["az"] == pytest.approx(0.1) and p["el"] == pytest.approx(-0.02)
    assert rotor.plan(1.0, 1.0, 0.0)["az"] == rotor.MAX_STEP_DEG
    assert rotor.az_axis_from_sky(0.01, 89.0) == pytest.approx(0.01 / 0.17364817766693041)


def test_apply_needs_enable_tracking_and_respects_limit(cfg):
    sent = []
    send = lambda cmds, h, p: sent.extend(cmds) or ["ok"] * len(cmds)
    r = rotor.apply(0.01, 0.0, DD, send=send)
    assert not r["ok"] and "spente" in r["error"] and not sent
    (cfg / "settings.json").write_text(json.dumps({"rotor_enabled": True}))
    assert "TRACKING" in rotor.apply(0.01, 0, {**DD, "tracking": False}, send=send)["error"]
    assert "muovendo" in rotor.apply(0.01, 0, {**DD, "moving": True}, send=send)["error"]
    r = rotor.apply(0.40, 0.0, DD, send=send)               # 0.17 + 0.25 (clipped step) = 0.42: allowed
    assert r["ok"] and sent == ["ao+0.250"]
    rotor._state["last_t"] = 0.0
    r = rotor.apply(0.2, 0.0, {**DD, "off_az": 0.42}, send=send)     # would go to 0.62 > 0.5
    assert not r["ok"] and "0,5" not in r["error"] and "+0.620" in r["error"] and sent == ["ao+0.250"]
    r = rotor.apply(0.0, -0.01, {**DD, "off_az": 0.42}, send=send)   # too soon after the last command? no: last_t not set
    assert r["ok"] and sent[-1] == "eo-0.010"
    assert "attendi" in rotor.apply(0.0, -0.01, DD, send=send)["error"]
    assert (cfg / "rotor_log.csv").read_text().count("\n") == 3      # header + 2 commands


def test_stop_switches_corrections_off(cfg):
    (cfg / "settings.json").write_text(json.dumps({"rotor_enabled": True}))
    rotor.stop()
    assert not rotor.enabled()


def test_watchdog_checks():
    now = datetime(2026, 11, 25, 21, 0, tzinfo=timezone.utc)
    items = watchdog.checks(now=now, gpsdo={"gps_ok": True, "pll_ok": False}, gpsdo_on=True,
                            dd=None, dd_err="timed out", dd_on=True, dd_err_since=now - timedelta(seconds=30),
                            wsjtx_on=True, wsjtx_last=now - timedelta(seconds=200),
                            bkt={"running": True}, ntp={"offset_s": 0.7}, dt=1.4, cam_on=True, cam_age_s=12.0)
    st = {i["key"]: i["state"] for i in items}
    assert st == {"gpsdo": "bad", "driverdish": "bad", "wsjtx": "bad", "bkt": "warn", "dt": "bad", "camera": "bad"}
    assert watchdog.checks(now=now) == []                   # nothing in use: nothing checked
    prev = {}
    assert len(watchdog.newly_bad(items, prev)) == 5
    assert watchdog.newly_bad(items, prev) == []            # one toast per change


def test_strip_items():
    from emelab import ui_live
    items = ui_live.strip_items({"dial_hz": 24048100000, "mode": "Q65", "submode": "E", "tr_period": 60, "tx_df": 700,
                                 "rx_df": 700, "freq_tolerance": 200},
                                {"split": "Rig", "tx_first": False, "doppler": "CFOM"}, {"running": True},
                                {"offset_s": 0.02}, 0.3, 9, {"gps_ok": True, "pll_ok": True})
    d = {k: (v, s) for k, v, s in items}
    assert d["Sked"][0] == "24 048.100000 MHz" and d["TX"][0] == "24 048.100700 MHz"
    assert d["Modo"][0] == "Q65-60E" and d["Tx"][0] == "2nd" and d["Doppler"] == ("CFOM", "ok")
    assert d["GPSDO"][1] == "ok" and d["DT"][1] == "ok"


@pytest.mark.parametrize("lang", ["it", "en"])
def test_live_tab_renders(tmp_path, monkeypatch, lang):
    pytest.importorskip("erfa")
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"tabs": ["live"], "cam_enabled": True, "cam_source": "sim",
                                                        "language": lang, "rotor_enabled": True}))
    from emelab import moontrack as mt
    mt.stop()
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
    at.run()
    import time
    time.sleep(0.6)
    at.run()
    try:
        assert not at.exception, [e.value for e in at.exception]
        if lang == "en":
            from tests.test_language_consistency import ITALIAN_MARKERS
            texts = [str(e.value) for k in ("caption", "markdown", "success", "warning", "error", "info")
                     for e in getattr(at, k)] + [w.label for k in ("button", "toggle") for w in getattr(at, k)]
            bad = [(t[:100], m) for t in texts for m in ITALIAN_MARKERS if m in t]
            assert not bad, bad
            assert any("Rotor corrections" in t.label for t in at.toggle)
    finally:
        mt.stop()
