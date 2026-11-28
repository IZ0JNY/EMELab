# SPDX-License-Identifier: GPL-3.0-or-later
"""Closing the alert pop-ups: a closed alert comes back only after its problem has been gone for a while."""
from emelab import dismiss


def test_closed_alert_stays_closed_while_problem_flickers():
    closed, gone = {"a", "b"}, {}
    dismiss.prune(closed, {"a", "b"}, gone, now=0)
    dismiss.prune(closed, {"b"}, gone, now=10)          # «a» missing for one reading
    assert closed == {"a", "b"} and "a" in gone
    dismiss.prune(closed, {"a", "b"}, gone, now=20)     # back again: still closed, no pop-up
    assert closed == {"a", "b"} and gone == {}


def test_closed_alert_forgotten_after_grace():
    closed, gone = {"a"}, {}
    dismiss.prune(closed, set(), gone, now=0, grace=120)
    dismiss.prune(closed, set(), gone, now=119, grace=120)
    assert closed == {"a"}
    dismiss.prune(closed, set(), gone, now=120, grace=120)
    assert closed == set() and gone == {}


def test_hook_selector_names_the_close_buttons():
    assert "wjp_close" in dismiss.CLOSE_KEYS and "ea_alarm_ok" in dismiss.CLOSE_KEYS
    assert 'aria-label="Close"' in dismiss.JS


def test_one_closing_counts_once(monkeypatch, tmp_path):
    """«Chiudi» (closes through the ✕) and on_dismiss may both report the same closing: count it once."""
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import settings, ui_wsjtx_panel as w
    w.S.pop("wj_popup_done", None)
    w._closed(["gpsdo", "clock"])
    w._closed(["gpsdo", "clock"])
    assert settings.load_settings()["wsjtx_popup_closed"] == {"gpsdo": 1, "clock": 1}
    w.S["wj_popup_done"] = set()                     # problem gone and back: a new closing counts again
    w._closed(["gpsdo"])
    assert settings.load_settings()["wsjtx_popup_closed"]["gpsdo"] == 2
