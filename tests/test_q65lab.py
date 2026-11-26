"""🧪 Q65 Lab: decoder protocol, profiles, parameters from WSJT-X, files, engine (with the decoder if it is built)."""
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from emelab import q65lab

DATA = Path(__file__).parent / "data"
WAV15 = DATA / "q65lab_15A_IZ0JNY_OK1KIR.wav"            # q65sim "IZ0JNY OK1KIR JO70" A 1000 Hz, 15 s, -12 dB
EXE = q65lab.find_decoder()
needs_exe = pytest.mark.skipif(EXE is None, reason="q65lab non compilato su questo PC")


def test_parse_output():
    utc = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
    r = q65lab.parse_output(["D 1800  -24  2.48    700.0  3   1 IZ0JNY OK1KIR JO70", "E      3     0    1519"], utc)
    assert r["decodes"] == [{"utc": utc, "snr": -24, "dt": 2.48, "freq": 700.0, "q": 3, "nused": 1,
                             "message": "IZ0JNY OK1KIR JO70"}]
    assert r["navg"] == (3, 0) and r["ms"] == 1519 and r["error"] is None
    assert q65lab.parse_output(["E ERR cannot read wav"])["error"] == "cannot read wav"


def test_lab_profile_follows_the_spread():
    assert q65lab.lab_knobs(20) == q65lab.Knobs(1, 100, q65lab.LINEAR)         # 10 GHz: the WSJT-X metric
    assert q65lab.lab_knobs(150) == q65lab.Knobs(0, 200, q65lab.LINEAR)        # 24 GHz
    assert q65lab.lab_knobs(320) == q65lab.Knobs(0, 300, q65lab.LINEAR)        # 24 GHz high libration, 47 GHz
    assert q65lab.lab_knobs(None).fade == 1
    assert q65lab.WSJTX_KNOBS == q65lab.Knobs(1, 100, 4)


def test_params_from_wsjtx_status_and_ini():
    status = {"mode": "Q65", "submode": "E", "tr_period": 60, "rx_df": 700, "freq_tolerance": 200,
              "de_call": "IZ0JNY", "dx_call": "OK1KIR", "dx_grid": "JO70", "dial_hz": 24048100000}
    ini = {"depth": "Deep", "averaging": True, "auto_clear_avg": True, "max_drift": 0, "decode52": True}
    stn = {"callsign": "IZ0JNY", "locator": "JN61FW", "lat": 41.9, "lon": 12.5, "height_m": 50}
    p = q65lab.params_from(status, ini, stn, datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc))
    assert (p["submode"], p["tr"], p["rx_hz"], p["ftol"], p["dx_call"], p["band"]) == ("E", 60, 700, 200, "OK1KIR", "24G")
    assert p["depth"] == 3 | 16 | 128 and p["eme_delay"] is True and p["max_drift"] == 0
    assert 1 < p["spread_hz"] < 1000                    # mutual libration spread at 24 GHz


def test_merge_marks_who_decoded():
    lab = [{"message": "IZ0JNY OK1KIR JO70", "snr": -25, "dt": 2.5, "freq": 700.0, "q": 3, "nused": 1},
           {"message": "CQ DL7YC JO62", "snr": -27, "dt": 2.4, "freq": 820.0, "q": 0, "nused": 2}]
    ref = [{"message": "IZ0JNY  OK1KIR JO70", "snr": -25, "dt": 2.5, "freq": 700.0, "q": 3, "nused": 1}]
    rows = q65lab.merge(lab, ref)
    assert [r["message"] for r in rows] == ["IZ0JNY OK1KIR JO70", "CQ DL7YC JO62"]
    assert rows[0]["lab"] and rows[0]["ref"] and not rows[0]["only_lab"]
    assert rows[1]["only_lab"]


def test_wav_roundtrip_and_resampling(tmp_path):
    x = 0.1 * np.sin(2 * np.pi * 1000 * np.arange(48000) / 48000)
    q65lab.write_wav(tmp_path / "a.wav", q65lab.to_12k(x, 48000))
    y, fs = q65lab.read_wav(tmp_path / "a.wav")
    assert fs == 12000 and len(y) == 12000
    assert abs(np.argmax(np.abs(np.fft.rfft(y))) - 1000) <= 1


def test_saved_file_names():
    assert q65lab.saved_time("261126_1803.wav") == datetime(2026, 11, 26, 18, 3, tzinfo=timezone.utc)
    assert q65lab.saved_time("261126_180330.wav") == datetime(2026, 11, 26, 18, 3, 30, tzinfo=timezone.utc)
    assert q65lab.saved_time("echo.wav") is None


def test_ini_audio_and_device_choice(tmp_path):
    ini = tmp_path / "WSJT-X.ini"
    ini.write_text("[Configuration]\nSoundInName=Microfono (USB Audio CODEC)\nAudioInputChannel=Left\n", encoding="utf-8")
    assert q65lab.ini_audio(ini) == {"device": "Microfono (USB Audio CODEC)", "channel": "Left"}
    devs = [{"index": 0, "name": "Microfono (Realtek(R) Audio)", "api": "MME", "rate": 44100},
            {"index": 1, "name": "Microfono (USB Audio CODEC)", "api": "Windows WASAPI", "rate": 48000},
            {"index": 2, "name": "Microfono (USB Audio CODEC)", "api": "MME", "rate": 48000}]
    assert q65lab.pick_device(devs, "Microfono (USB Audio CODEC)")["index"] == 2
    assert q65lab.pick_device(devs, None)["index"] == 2                     # IC-9700 codec by default
    assert q65lab.pick_device(devs[:1], None) is None


def test_waterfall_image():
    wf = q65lab.Waterfall(rows=50)
    t = np.arange(8192) / 12000
    for i in range(30):
        wf.add(0.01 * np.random.default_rng(i).standard_normal(8192) + 0.05 * np.sin(2 * np.pi * 1500 * t), i)
    img = wf.image(rx_hz=1500, ftol=100, width=600, height=200, marks=[(10, "18:01")])
    assert img.shape == (200, 600, 3)
    col = int((1500 - 200) / 2800 * 599)
    assert img[60:, col - 2:col + 3].mean() > img[60:, 50:60].mean()          # the tone is the bright line


@needs_exe
def test_decoder_decodes_the_simulated_period(tmp_path):
    d = q65lab.Decoder(EXE, tmp_path)
    try:
        r = d.decode(WAV15, datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc), 15, "A", 1000, 50, 3,
                     "IZ0JNY", "OK1KIR", "JO70", eme_delay=False)
    finally:
        d.close()
    assert [x["message"] for x in r["decodes"]] == ["IZ0JNY OK1KIR JO70"]
    assert abs(r["decodes"][0]["freq"] - 1000) < 5 and r["red"] is not None


@needs_exe
def test_decode_files_both_profiles(tmp_path):
    p = q65lab.DEFAULT_PARAMS | {"tr": 15, "submode": "A", "rx_hz": 1000, "ftol": 50, "eme_delay": False}
    out = q65lab.decode_files([WAV15], p, EXE, folder=tmp_path)
    assert out[0]["rows"][0]["lab"] and out[0]["rows"][0]["ref"]


@needs_exe
def test_engine_listens_and_decodes_each_period(tmp_path):
    eng = q65lab.Engine(EXE, tmp_path)
    eng.params_fn = lambda: {"tr": 15, "submode": "A", "rx_hz": 1000, "ftol": 50, "eme_delay": False}
    eng.start(q65lab.FileSource([WAV15], tr=15))
    try:
        t_end = time.time() + 40
        while time.time() < t_end and not any(p.lab.get("decodes") for p in eng.periods):
            time.sleep(0.5)
    finally:
        eng.stop()
    got = [d["message"] for p in eng.periods for d in p.lab.get("decodes", [])]
    assert "IZ0JNY OK1KIR JO70" in got, (list(eng.errors), [(p.utc, p.lab, p.skipped) for p in eng.periods])
    assert len(eng.waterfall.rows) >= 1


def test_widegraph_from_ini_and_refspec(tmp_path):
    ini = tmp_path / "WSJT-X.ini"
    ini.write_text("[WideGraph]\nStartFreq=100\nBinsPerPixel=2\nPlotWidth=1000\nWaterfallAvg=3\nWaterfallPalette=Gray1\n"
                   "Flatten=false\nUseRef=true\nCumulative=true\n", encoding="utf-8")
    assert q65lab.ini_widegraph(ini) == {"start": 100, "span": 2929, "navg": 3, "palette": "gray", "flatten": False,
                                         "use_ref": True, "spectrum": True}
    ref = tmp_path / "refspec.dat"
    ref.write_text("  400 2600    5   0.1E+01  -0.1E+00   0.3E-01   0.1E+00   0.6E+00\n"
                   + "".join(f"{i * 1.736:10.3f}   0.100E+04  {-(i % 7):10.6f}   0.264E-05 -111.577217\n" for i in range(1, 400)),
                   encoding="utf-8")
    assert q65lab.refspec_path(ini) == ref
    f, db = q65lab.read_refspec(ref)
    assert len(f) == 399 and abs(f[0] - 1.736) < 1e-6 and -6 < db[200] < 0


def test_auto_view_covers_the_whole_signal():
    v = q65lab.auto_view({"rx_hz": 700, "ftol": 200, "tr": 60, "submode": "E", "spread_hz": 260})
    assert v.start <= 700 - 200 and v.start + v.span >= 700 + q65lab.q65_bandwidth(60, "E") + 200
    v = q65lab.auto_view({"rx_hz": 1000, "ftol": 50, "tr": 60, "submode": "D"})
    assert 800 <= v.start <= 950 and 1950 <= v.start + v.span <= 2200
    assert abs(q65lab.q65_bandwidth(60, "E") - 65 * 12000 / 7200 * 16) < 1e-9


def test_find_trace_in_the_spectrum():
    f = np.arange(0, 3000, q65lab.WF_DF)
    spec = np.random.default_rng(1).normal(0, 0.3, len(f))
    assert q65lab.find_trace(spec, f, 700, 100, 50) is None
    spec[(f > 690) & (f < 740)] += 3
    hz, db = q65lab.find_trace(spec, f, 700, 100, 50)
    assert 690 < hz < 740 and db > 2


def test_files_with_alltxt():
    rows = [{"utc": datetime(2026, 9, 26, 18, 50, 0, tzinfo=timezone.utc), "rxtx": "Rx", "mode": "Q65-60D", "snr_db": -17,
             "dt_s": 2.5, "df_hz": 1277, "message": "CQ IZ2DJP JN55", "band": "10G"},
            {"utc": datetime(2026, 9, 26, 18, 51, 6, tzinfo=timezone.utc), "rxtx": "Tx", "mode": "Q65-60D", "snr_db": 0,
             "dt_s": 0.0, "df_hz": 1200, "message": "IZ2DJP IZ0JNY JN61", "band": "10G"}]
    t = datetime(2026, 9, 26, 18, 50, tzinfo=timezone.utc)
    assert q65lab.guess_params(rows, t) == {"tr": 60, "submode": "D", "rx_hz": 1200, "dx_call": "IZ2DJP"}
    assert q65lab.guess_params(rows, datetime(2026, 9, 27, tzinfo=timezone.utc)) == {}
    assert [d["message"] for d in q65lab.wsjtx_decodes_at(rows, t, 60)] == ["CQ IZ2DJP JN55"]
    assert q65lab.file_time("260926_1850.wav") == t


def test_same_card_entries_and_missing_files(tmp_path):
    devs = [{"index": 0, "name": "Microphone (USB Audio CODEC )", "api": "MME", "rate": 44100},
            {"index": 1, "name": "Microphone (USB Audio CODEC )", "api": "Windows WDM-KS", "rate": 48000},
            {"index": 2, "name": "Microphone (USB Audio CODEC )", "api": "Windows DirectSound", "rate": 48000},
            {"index": 3, "name": "Microphone (USB Audio CODEC )", "api": "Windows WASAPI", "rate": 48000},
            {"index": 4, "name": "Microfono (Realtek)", "api": "MME", "rate": 44100}]
    assert [d["index"] for d in q65lab.same_card(devs, "Microphone (USB Audio CODEC )")] == [0, 3, 2]
    out = q65lab.decode_files([tmp_path / "gone.wav"], q65lab.DEFAULT_PARAMS, exe=EXE or tmp_path / "x", folder=tmp_path)
    assert out == []
