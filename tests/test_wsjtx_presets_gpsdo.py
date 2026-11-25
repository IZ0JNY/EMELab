"""WSJT-X band presets and control check, Configure with Rx DF, GPSDO catalogue / phase noise / HID / NMEA / WAV."""
import io
import math
import struct
import wave

import numpy as np


def test_presets_and_check(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import wsjtx_check as wc
    p10, p24 = wc.preset("10G"), wc.preset("24G")
    assert (p10["mode"], p10["tx_df"], p10["rx_df"], p10["doppler"]) == ("60D", 1000, 1000, "CFOM")
    assert (p24["mode"], p24["tx_df"], p24["rx_df"], p24["f_tol"], p24["config"]) == ("60E", 700, 700, 200, "EME mm-wave")
    assert wc.preset("47G")["assumed"] and not p24["assumed"]
    st = {"dial_hz": 24_048_121_634, "mode": "Q65", "submode": "E", "tr_period": 60, "tx_df": 700, "rx_df": 700,
          "freq_tolerance": 200, "config_name": "EME mm-wave"}
    assert wc.check(st) == []
    p = {x["code"]: x for x in wc.check({**st, "tx_df": 1000, "rx_df": 1500, "freq_tolerance": 100, "config_name": "Default"})}
    assert set(p) == {"tx_df", "rx_df", "ftol", "config"}
    assert p["ftol"]["cfg"] == {"freq_tol": 200} and p["rx_df"]["soft"] and not p["tx_df"].get("soft")
    wc.save_preset("24G", mode="60D", tx_df=800)
    assert wc.preset("24G")["mode"] == "60D" and wc.preset("24G")["tx_df"] == 800 and wc.preset("24G")["saved"]


def test_configure_rx_df_and_service_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import db as edb, wsjtx
    from emelab.wsjtx_service import Service
    b = wsjtx.configure("WSJT-X", "Q65", "E", 60, 200, rx_df=700)
    assert struct.unpack(">I", b[-13:-9])[0] == 700                       # Rx DF, then empty DX call, DX grid, generate
    D = edb.DB(tmp_path / "t.sqlite")
    s = Service(lambda: D, lambda: "JN61PM")
    sent = []
    s.set_q65 = lambda code, **kw: sent.append((code, kw)) or True
    st = {"type": "status", "id": "WSJT-X", "dial_hz": 10_368_100_000, "mode": "Q65", "submode": "D", "tr_period": 60,
          "tx_df": 1000, "rx_df": 1300, "freq_tolerance": 200}
    s.on_message(st, None)                       # first status of the band: Rx goes to the preset
    assert sent == [(None, {"rx_df": 1000})]
    s.on_message(st, None)                       # same band: the moved Rx is only noted
    assert len(sent) == 1 and any(p["code"] == "rx_df" for p in s.problems)


def test_gpsdo_catalogue_and_phase_noise(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import gpsdo
    ms = gpsdo.models()
    lbe = next(m for m in ms if m["name"] == "LBE-1421")
    assert lbe["pn"][1000] == -147 and not lbe["verified"]
    r = gpsdo.band_report(lbe, "24G", "60E")
    assert abs(r["add_db"] - 20 * math.log10(24048.1 / 10)) < 1e-9 and r["ok"] == "ok"
    assert abs(gpsdo.tone_spacing_hz("60D") - 13.333) < 0.01
    assert gpsdo.band_report(next(m for m in ms if m["name"].startswith("mini")), "24G", "60E")["ok"] is None
    gpsdo.save_model({**lbe, "pn": {"1000": "-150", "10": ""}})
    lbe2 = next(m for m in gpsdo.models() if m["name"] == "LBE-1421")
    assert lbe2["verified"] and lbe2["pn"] == {1000: -150.0}
    assert gpsdo.revert_model(gpsdo.model_key(lbe)) and not next(m for m in gpsdo.models() if m["name"] == "LBE-1421")["verified"]
    assert gpsdo.read_pn_text("1 Hz -72 dBc/Hz 10 Hz -101 100Hz −128 1 kHz -147") == {1: -72, 10: -101, 100: -128, 1000: -147}


def test_gpsdo_reminder_hid_nmea():
    from datetime import datetime, timezone
    from emelab import gpsdo
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
    assert gpsdo.reminder_due({}, now)
    assert not gpsdo.reminder_due({"gpsdo_ok_utc": "2026-11-25T16:00:00Z"}, now)
    assert gpsdo.reminder_due({"gpsdo_ok_utc": "2026-11-25T06:00:00Z"}, now)
    assert not gpsdo.reminder_due({"gpsdo_use": False}, now)
    s = gpsdo.parse_lb_status(bytes([0, 3, 0]) + bytes(57))
    assert s["gps_ok"] and s["pll_ok"] and s["loss_count"] == 3
    s = gpsdo.parse_lb_status(bytes([0, 0, 2]))
    assert s["gps_ok"] and not s["pll_ok"]

    def ck(b):
        x = 0
        for c in b:
            x ^= ord(c)
        return f"${b}*{x:02X}"
    st = gpsdo.parse_nmea([ck("GPGGA,161910,4131.558,N,01316.491,E,1,09,0.9,201.2,M,,M,,"), ck("GPGSV,3,1,12,01,40,083,46"),
                           "$GPGGA,bad*00"])
    assert st["fix"] and st["sats_used"] == 9 and st["sats_seen"] == 12 and abs(st["lat"] - 41.526) < 0.001 and st["sentences"] == 2


def test_measure_wav_carrier():
    from emelab import gpsdo
    fs, n = 12000, 12000 * 20
    t = np.arange(n) / fs
    rng = np.random.default_rng(1)
    x = 8000 * np.sin(2 * np.pi * 1000 * t) + 3 * rng.standard_normal(n)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(fs)
        w.writeframes(x.astype("<i2").tobytes())
    r = gpsdo.measure_wav(buf.getvalue())
    assert abs(r["f_carrier_hz"] - 1000) < 1
    # white noise: σ²=9 over 6 kHz → 1.5e-3 /Hz; carrier 3.2e7 → about −103 dBc/Hz
    assert all(-110 < v < -96 for v in r["pn"].values()), r["pn"]


def test_panel_html(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import ui_wsjtx_panel as up, wsjtx_check as wc
    st = {"dial_hz": 24_048_121_634, "mode": "Q65", "submode": "E", "tr_period": 60, "tx_df": 700, "rx_df": 650,
          "freq_tolerance": 200, "config_name": "EME mm-wave", "dx_call": "UN6PD", "dx_grid": "MN69JM"}
    h = up.panel_html(st, wc.preset("24G"), {}, "24G")
    assert "24 048,121634" in h and "UN6PD" in h and "btn on'>60E" in h and "⚠️" in h and "❔" in h
