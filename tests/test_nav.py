from emelab import nav

LABELS = {"wizard": "🧭 Assistente", "camera": "📷 Telecamera Astronomica", "pointing": "🎯 Tracking",
          "wsjtx": "📻 WSJT-X", "gpsdo": "🛰️ GPSDO"}


def test_live_missing_falls_back_to_alert_tab():
    assert nav.target("camera", LABELS, ["wizard"]) == "camera"
    assert nav.target("driverdish", LABELS, ["wizard"]) == "pointing"
    assert nav.target("clock", LABELS, ["wizard"]) == "wsjtx"


def test_live_first_when_shown():
    lab = {**LABELS, "live": "🔴 Live"}
    assert nav.target("camera", lab, ["wizard", "live"]) == "live"
    assert nav.target("gpsdo", lab, ["wizard"]) == "gpsdo"          # Live hidden: the alert's own tab


def test_wsjtx_popup_kind():
    from emelab.ui_wsjtx_panel import _kind
    assert _kind([{"key": "gpsdo"}]) == "gpsdo"
    assert _kind([{"key": "bktsync"}, {"key": "clock"}]) == "clock"
    assert _kind([{"key": "gpsdo"}, {"key": "mode@24GHz"}]) == "wsjtx"


def test_watchdog_opens_only_live():
    assert nav.target("watchdog", LABELS, ["wizard"]) is None
    assert nav.target("watchdog", {**LABELS, "live": "🔴 Live"}, ["live"]) == "live"
