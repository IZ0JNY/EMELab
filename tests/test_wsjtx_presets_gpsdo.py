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


def test_presets_47_76_editable(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import dx, wsjtx_check as wc
    assert {"47G", "76G"} <= set(wc.EDITABLE_BANDS)
    for b in ("47G", "76G"):
        p = wc.preset(b)
        assert p["assumed"] and not p["saved"] and p["mode"] == "60E" and p["tx_df"] == 700
    wc.save_preset("47G", mode="30C", tx_df=1200, rx_df=1200, f_tol=100, doppler="Full", split="Fake It",
                   max_drift=10, tx_first=False, auto_seq=False, config="EME 47")
    p = wc.preset("47G")
    assert (p["mode"], p["tr"], p["submode"], p["tx_df"], p["f_tol"], p["doppler"], p["split"], p["config"]) == \
        ("30C", 30, "C", 1200, 100, "Full", "Fake It", "EME 47")
    assert p["saved"] and not p["assumed"] and dx.band_mode("47G") == "60E"   # 30C has no threshold: Signal tab untouched
    st = {"dial_hz": 47_088_100_000, "mode": "Q65", "submode": "C", "tr_period": 30, "tx_df": 1200, "rx_df": 1200,
          "freq_tolerance": 100, "config_name": "EME 47"}
    assert wc.check(st) == []
    assert wc.check({**st, "submode": "E", "tr_period": 60})[0]["fix"] == "30C"
    wc.save_preset("76G", mode="120E")
    assert wc.preset("76G")["mode"] == "120E" and dx.band_mode("76G") == "120E"
    wc.save_preset("47G", mode="60E")                     # back to a threshold mode: the stored 30C goes away
    assert wc.preset("47G")["mode"] == "60E"
    wc.reset_preset("47G")
    assert wc.preset("47G")["assumed"] and wc.preset("47G")["tx_df"] == 700


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
    s.on_message(st, None)                       # Ivan: never sent by itself, only flagged (Rx goes only with «Applica il preset»)
    assert sent == [] and any(p["code"] == "rx_df" for p in s.problems)


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
    assert gpsdo.parse_lb_status(bytes([0, 0x84, 0xb5, 0x62]))["error"]          # a UBX data chunk, not a status
    # status report and feature (configuration) report read from a mini GPS Reference Clock (fw 1.17) set to 10 MHz
    s = gpsdo.parse_lb_status(bytes.fromhex("00 04 00 62 05 01 02 00 06 01 0f 38"))
    assert s["gps_ok"] and s["pll_ok"] and s["loss_count"] == 4
    cfg = gpsdo.parse_lb_config(bytes.fromhex("00 03 03 40 7d 01 00 00 00 06 69 18 00 01 79 00 00 79 00 00 00 09 14 00"))
    assert cfg["f_ref_hz"] == 97600 and cfg["n2_ls"] == 6250 and cfg["nc1_ls"] == 122 and cfg["drive_ma"] == 32
    assert cfg["bw"] == 9 and abs(cfg["f_out_hz"] - 10e6) < 1e-6
    # UBX-NAV-PVT: 3D fix, 13 satellites, split across HID chunks with junk around it
    p = bytearray(92)
    p[4:12] = bytes([0xea, 0x07, 11, 25, 17, 3, 7, 0x37])
    p[20], p[21], p[23] = 3, 0x03, 13
    p[24:28] = (132748499).to_bytes(4, "little", signed=True)
    p[28:32] = (415259678).to_bytes(4, "little", signed=True)
    body = bytes([0x01, 0x07, 92, 0]) + bytes(p)
    a = c = 0
    for x in body:
        a = (a + x) & 0xFF
        c = (c + a) & 0xFF
    frame = b"\xb5\x62" + body + bytes([a, c])
    pvt = gpsdo.parse_ubx_pvt(b"\xff\x00\xb5\x62\x01" + frame + b"\xb5\x62\x01\x07\x5c")
    assert pvt["sats_used"] == 13 and pvt["fix"] == "3D" and pvt["fix_ok"] and abs(pvt["lat"] - 41.5259678) < 1e-6
    assert pvt["gps_utc"] == "2026-11-25 17:03:07"
    assert gpsdo.parse_ubx_pvt(frame[:-1] + b"\x00") is None                      # bad checksum
    assert gpsdo._lb_cfg_msg(1, 7, 10)[:9] == bytes([0, 8, 6, 1, 8, 0, 1, 7, 10]) and len(gpsdo._lb_cfg_msg(1, 7, 0)) == 61

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


INI = r"""[General]
RxFreq_old=700
[MultiSettings]
CurrentName=EME mm-wave
Test\Astro\DopplerMethod=1
Test\Configuration\SplitMode=@Variant(\0\0\0\x7f\0\0\0\x1eTransceiverFactory::SplitMode\0\0\0\0\x13split_mode_emulate\0)
[Configuration]
SplitMode=@Variant(\0\0\0\x7f\0\0\0\x1eTransceiverFactory::SplitMode\0\0\0\0\xfsplit_mode_rig\0)
[Astro]
DopplerTracking=true
DopplerMethod=2
[MainWindow]
TxFirst=true
[Common]
AutoSeq=true
MaxDrift=0
"""


def test_wsjtx_ini(tmp_path, monkeypatch):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from emelab import wsjtx_check, wsjtx_ini
    f = tmp_path / "WSJT-X.ini"
    f.write_text(INI)
    r = wsjtx_ini.read(f)
    assert (r["config"], r["doppler"], r["split"], r["tx_first"], r["auto_seq"], r["max_drift"]) == \
        ("EME mm-wave", "CFOM", "Rig", True, True, 0)
    assert wsjtx_ini.find(tmp_path / "wsjtx_log.adi") == f
    assert wsjtx_ini.differences(r, wsjtx_check.preset("10G")) == []
    f.write_text(INI.replace("DopplerTracking=true", "DopplerTracking=false").replace("TxFirst=true", "TxFirst=false"))
    d = {x["code"] for x in wsjtx_ini.differences(wsjtx_ini.read(f), wsjtx_check.preset("10G"))}
    assert d == {"ini_doppler", "ini_tx_first"}
