"""📷 Telecamera Astronomica: Moon detection, offsets, alarm and the tab (simulator), in Italian and English."""
import json
import os

import numpy as np
import pytest

from emelab import moontrack as mt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_detect_full_and_partial_moon():
    s = mt.SimSource(phase=1.0)
    f = s.frame_at(0.0)
    d = mt.detect(f)
    assert d and abs(d["r"] - 145) < 4
    yy, xx = np.nonzero(f > 100)
    assert abs(d["cx"] - xx.mean()) < 2 and abs(d["cy"] - yy.mean()) < 2
    d2 = mt.detect(mt.SimSource(phase=0.4).frame_at(0.0))
    assert d2 and abs(d2["r"] - 145) < 6                  # diameter from the longest side at any phase


def test_no_moon_in_a_dark_or_flat_frame():
    assert mt.detect(np.full((480, 640), 10, np.uint8)) is None
    rng = np.random.default_rng(1)
    assert mt.detect(rng.normal(20, 3, (480, 640)).clip(0, 255).astype(np.uint8)) is None


def test_scale_offset_and_loss():
    sc = mt.deg_per_px(3.75, 1, 120.0)                  # ASI120MM Mini + 30F4
    assert abs(sc * 3600 - 6.45) < 0.02
    o = mt.offset({"cx": 110.0, "cy": 90.0}, (100.0, 100.0), 0.01)
    assert o["az_deg"] == pytest.approx(0.1) and o["el_deg"] == pytest.approx(0.1)
    o = mt.offset({"cx": 110.0, "cy": 90.0}, (100.0, 100.0), 0.01, flip_x=True, flip_y=True)
    assert o["az_deg"] == pytest.approx(-0.1) and o["el_deg"] == pytest.approx(-0.1)
    assert mt.pointing_loss_db(0.25, 1.0) == pytest.approx(0.75)


def test_alarm_needs_hold_time_and_clears():
    a = mt.Alarm()
    assert not a.update(0.0, 0.2, 0.1, 3) and not a.active
    assert a.update(3.1, 0.2, 0.1, 3) and a.active and a.reason == "out"
    assert not a.update(3.5, 0.3, 0.1, 3)                # beeps only once
    a.update(4.0, 0.05, 0.1, 3)
    assert not a.active
    a.update(5.0, None, 0.1, 0)
    assert a.active and a.reason == "lost"


def test_missing_library_is_explained(monkeypatch):
    monkeypatch.setattr(mt, "dll_candidates", lambda p="": [])
    monkeypatch.setattr(mt, "_LIB", {"path": None, "error": None})
    monkeypatch.setattr("ctypes.util.find_library", lambda n: None)
    cams, err = mt.list_cameras()
    assert cams == [] and err


def test_overlay_and_beep():
    f = mt.SimSource().frame_at(5.0)
    im = mt.overlay(f, mt.detect(f), (320, 240), 30, 50, True)
    assert im.size == (640, 480)
    assert mt.beep_wav()[:4] == b"RIFF"


@pytest.mark.parametrize("lang", ["it", "en"])
def test_tab_with_simulator(tmp_path, monkeypatch, lang):
    pytest.importorskip("erfa")
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", lang)
    (tmp_path / "settings.json").write_text(json.dumps({"tabs": ["camera"], "cam_enabled": True, "cam_source": "sim",
                                                        "language": lang}))
    mt.stop()
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
    at.run()
    import time
    time.sleep(0.6)                                      # first simulated frame
    at.run()
    try:
        assert not at.exception, [e.value for e in at.exception]
        texts = [str(e.value) for k in ("subheader", "caption", "markdown", "success", "warning", "error", "info")
                 for e in getattr(at, k)] + [m.label for m in at.metric]
        if lang == "en":
            assert any("Astronomical camera" in t for t in texts)
            assert any("Offset" == t for t in texts), texts
            from tests.test_language_consistency import ITALIAN_MARKERS
            labels = texts + [w.label for k in ("number_input", "checkbox", "selectbox", "radio", "button", "toggle")
                              for w in getattr(at, k)]
            bad = [(t[:100], m) for t in labels for m in ITALIAN_MARKERS if m in t]
            assert not bad, bad
        else:
            assert any("Scostamento" == t for t in texts), texts
    finally:
        mt.stop()


def test_camera_tab_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
    at.run()
    assert not any("Telecamera" in t.label for t in at.tabs)
    assert mt.current() is None


def test_ref_point_is_inverse_of_offset():
    for fx, fy in ((False, False), (True, False), (False, True), (True, True)):
        ref = mt.ref_point(640, 480, 0.12, -0.07, 0.004, fx, fy)
        o = mt.offset({"cx": ref[0], "cy": ref[1]}, (319.5, 239.5), 0.004, fx, fy)
        assert o["az_deg"] == pytest.approx(0.12) and o["el_deg"] == pytest.approx(-0.07)


def test_suggested_threshold_from_beam():
    assert mt.suggested_tol(0.704, 1.0) == pytest.approx(0.14)      # 24GHz, 1.2 m
    assert mt.suggested_tol(1.632, 1.0) == pytest.approx(0.33)      # 10GHz, 1.2 m
    assert 2 * mt.pointing_loss_db(mt.suggested_tol(0.7, 1.0), 0.7) <= 1.0
    assert mt.suggested_tol(0.0) == 0.0


def test_sun_peak_fits_and_heatmap_files():
    xs = np.linspace(-1, 1, 9)
    A, E = np.meshgrid(xs, xs)
    Z = 20 - 12 * (((A - 0.13) / 0.7) ** 2 + ((E + 0.06) / 0.7) ** 2)
    pk = mt.fit_peak_2d(A.ravel(), E.ravel(), Z.ravel())
    assert pk[0] == pytest.approx(0.13, abs=0.005) and pk[1] == pytest.approx(-0.06, abs=0.005)
    assert mt.fit_peak_1d(xs, 20 - 12 * ((xs - 0.1) / 0.7) ** 2) == pytest.approx(0.1, abs=0.005)
    lst = "Az;El;SN\n" + "\n".join(f"{a:.3f};{e:.3f};{z:.2f}" for a, e, z in zip(A.ravel(), E.ravel(), Z.ravel()))
    mat = ";" + ";".join(f"{a:.3f}" for a in xs) + "\n" + "\n".join(
        f"{e:.3f};" + ";".join(f"{z:.2f}" for z in row) for e, row in zip(xs, Z))
    for text in (lst, mat):
        h = mt.parse_heatmap(text)
        assert len(h["db"]) == 81
        p = mt.fit_peak_2d(h["az"], h["el"], h["db"])
        assert p[0] == pytest.approx(0.13, abs=0.01) and p[1] == pytest.approx(-0.06, abs=0.01)


def test_alignment_band_and_rf_centre():
    assert mt.best_alignment_band({10.368: 1.63, 24.048: 0.70, 47.088: 0.36}) == 24.048
    assert mt.best_alignment_band({47.088: 0.36, 76.032: 0.22}) == 47.088
    # Sun 0.20° right of the image centre while the dish is 0.05° left of the noise peak → beam at 0.15°
    assert mt.rf_from_sun((0.20, -0.10), (0.05, 0.02)) == pytest.approx((0.15, -0.12))


@pytest.mark.parametrize("step", [0, 1, 2, 3])
def test_sun_wizard_steps_in_english(tmp_path, monkeypatch, step):
    pytest.importorskip("erfa")
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"tabs": ["camera"], "cam_enabled": True, "cam_source": "sim",
                                                        "language": "en"}))
    mt.stop()
    from emelab import ui_sunalign
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, "emelab_main.py"), default_timeout=120)
    at.session_state["sa_step"] = ui_sunalign.STEPS[step]
    at.session_state["sa_open"] = True
    at.run()
    try:
        assert not at.exception, [e.value for e in at.exception]
        from tests.test_language_consistency import ITALIAN_MARKERS
        texts = [str(e.value) for k in ("caption", "markdown", "success", "warning", "error", "info")
                 for e in getattr(at, k)] + [w.label for k in ("button", "radio") for w in getattr(at, k)]
        bad = [(t[:100], m) for t in texts for m in ITALIAN_MARKERS if m in t]
        assert not bad, bad
    finally:
        mt.stop()
