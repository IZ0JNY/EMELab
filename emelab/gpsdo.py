# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""GPSDO (GPS-disciplined reference oscillator): catalogue, phase noise multiplied up to the EME bands, the reminder
before operating, the live state read from the GPSDO's serial port (NMEA) and a phase-noise estimate from a WAV.

Phase noise. A transverter LO locked to a 10 MHz reference carries, inside the PLL loop bandwidth, the reference
phase noise raised by 20·log10(N) with N = f_LO / f_ref (+60.3 dB at 10 GHz, +67.6 dB at 24 GHz, +73.5 dB at 47 GHz).
EMELab integrates that noise from half the Q65 tone spacing of the band (energy beyond it falls outside the tone)
up to 100 kHz and turns the rms phase σ into a loss of 4.34·σ² dB: an estimate from the datasheet, not a
measurement. Below half the tone spacing the noise only widens the line, like the EME Doppler spread.

Rule of the catalogue (as catalog.py): a number is written only when it comes from a datasheet, a distributor page
quoting the maker or a published measurement (field «source»); missing values stay None. The user's own
corrections are saved in the settings («gpsdo_overrides»), shown as ✅ verified, and can be removed."""
from __future__ import annotations

import io
import math
import wave
from datetime import datetime, timedelta, timezone

import numpy as np

OFFSETS = (1, 10, 100, 1_000, 10_000, 100_000)            # Hz, the phase-noise columns
BAND_MHZ = {"10G": 10_368.1, "24G": 24_048.1, "47G": 47_088.1, "76G": 76_032.1, "122G": 122_250.1, "134G": 134_928.1}
Q65_BAUD_60 = 1.0 / 0.6                                     # Hz: tone spacing of Q65-60A
Q65_SPACING = {"A": 1, "B": 2, "C": 4, "D": 8, "E": 16}     # × baud

S_LBE = "https://www.leobodnar.com"
MODELS = [
    dict(name="mini GPS Reference Clock", maker="Leo Bodnar", kind="GPSDO", outputs="1 × SMA, 400 Hz–810 MHz (PLL Si53xx)",
         level="CMOS 3.3 V, corrente d'uscita 8–32 mA", f_ref_mhz=10.0, pn=None,
         stability="stessa famiglia del GPS Disciplined Clock valutato da Riley (2016)",
         interface="USB HID: configurazione e stato (GPS signal, PLL lock, perdite di segnale) leggibili da EMELab",
         power="USB 5 V", source="leobodnar.com, prodotto 301; programma «mini GPS Clock Configuration» 1.15. "
                                 "Rumore di fase non pubblicato in cifre: inseriscilo se lo misuri", url=S_LBE),
    dict(name="LBE-1421", maker="Leo Bodnar", kind="GPSDO", outputs="2 × SMA: Out1 1 Hz–800 MHz (o 1 PPS/NMEA), Out2 1 Hz–1.4 GHz",
         level="CMOS 3.3 V, 50 Ω, +11 dBm a 10 MHz (bassa potenza −2 dBm)", f_ref_mhz=10.0,
         pn={1: -72, 10: -101, 100: -128, 1_000: -147, 10_000: -156, 100_000: -159}, stability="1×10⁻¹² tipica (agganciato)",
         interface="USB-C: configurazione da PC Windows, NMEA su porta seriale virtuale", power="USB-C 5 V, 250 mA",
         source="sdr-kits.net/LBE-1421-GPS-Clock e batronix.com (valori tipici del costruttore)", url=S_LBE),
    dict(name="LBE-1420", maker="Leo Bodnar", kind="GPSDO", outputs="1 × SMA, 1 Hz–1.4 GHz (datasheet; il distributore dice 1.1 GHz garantiti)",
         level="CMOS 3.3 V, 50 Ω, +11 dBm sotto 400 MHz (bassa potenza +6 dBm)", f_ref_mhz=10.0,
         pn={1: -70, 10: -100, 100: -125, 1_000: -145, 10_000: -150, 100_000: -153}, stability="1×10⁻¹² a 1000 s",
         interface="USB-C: NMEA su porta seriale virtuale, configurazione da PC", power="USB-C 5 V, 250 mA",
         source="LBE-1420 Datasheet v1.1 (leobodnar.com); rumore di fase tipico da sdr-kits.net/LBE-1420-GPS-Clock", url=S_LBE),
    dict(name="LBE-1423", maker="Leo Bodnar", kind="GPSDO", outputs="1 PPS + uscita differenziale ± 1 Hz–1.4 GHz",
         level="CMOS 3.3 V, 50 Ω, +11 dBm sotto 400 MHz", f_ref_mhz=10.0, pn=None, stability="1×10⁻¹² a 1000 s",
         interface="USB-C: NMEA su porta seriale virtuale", power="USB-C 5 V, 250 mA",
         source="LBE-1423 Datasheet V1.0 (2025): rumore di fase non riportato in cifre", url=S_LBE),
    dict(name="LBE-1425", maker="Leo Bodnar", kind="GPSDO", outputs="2 × SMA, 1 Hz–1.4 GHz", level="CMOS 3.3 V, 50 Ω, +11 dBm",
         f_ref_mhz=10.0, pn=None, stability="oscillatore migliorato; invecchiamento senza GPS 0.2 ppb/giorno",
         interface="USB-C: NMEA su porta seriale virtuale", power="USB-C 5 V, 0.4 A",
         source="LBE-1425 Datasheet V1.0 (2025): rumore di fase non riportato in cifre", url=S_LBE),
    dict(name="GPS Disciplined Clock (doppia uscita, 2016)", maker="Leo Bodnar", kind="GPSDO",
         outputs="2 × CMOS, 450 Hz–800 MHz", level="da +7.7 a +13.3 dBm", f_ref_mhz=12.0,
         pn={1: -65, 100: -120, 1_000: -133, 10_000: -137, 100_000: -140}, stability="ADEV circa 1×10⁻¹⁰ a 1 s (misura Riley)",
         interface="USB: solo configurazione, LED di aggancio", power="USB o 5–15 V",
         source="W.J. Riley 2016, «Informal Evaluation of a Leo Bodnar GPS Frequency Reference»: 100 Hz–100 kHz "
                "specifica del costruttore a ~12 MHz, 1 Hz misurato da Riley (circa −65 dBc/Hz)", url=S_LBE),
    dict(name="LBE-1610 (OCXO, senza GPS)", maker="Leo Bodnar", kind="OCXO", outputs="2 × SMA, solo 10 MHz",
         level="CMOS 3.3 V, 50 Ω, +11 dBm", f_ref_mhz=10.0,
         pn={1: -115, 10: -145, 100: -162, 1_000: -167, 10_000: -170, 100_000: -170}, stability="calibrazione via USB",
         interface="USB-C, porta seriale virtuale per la calibrazione", power="rete 110/240 V",
         source="LBE-1610 Datasheet V1.0 (2025): riferimento a basso rumore da agganciare a un GPSDO", url=S_LBE),
    dict(name="Thunderbolt", maker="Trimble", kind="GPSDO", outputs="10 MHz sinusoidale + 1 PPS", level="+12.5 ± 2.5 dBm",
         f_ref_mhz=10.0, pn={10: -120, 100: -135, 1_000: -135, 10_000: -145, 100_000: -145},
         stability="1.16×10⁻¹² (media su un giorno)", interface="RS-232 (DB-9), protocollo TSIP 9600 8N1",
         power="24 V (19–34 V), 10 W a regime", source="Trimble datasheet TID10999F (2001)", url="https://www.trimble.com"),
    dict(name="GPSDO per USRP (OCXO)", maker="Ettus Research", kind="GPSDO", outputs="10 MHz + 1 PPS",
         level="", f_ref_mhz=10.0, pn={1: -75, 10: -110, 100: -132, 1_000: -142, 10_000: -145},
         stability="ADEV 1×10⁻¹¹ a 1 s", interface="RS-232: NMEA e SCPI", power="3.3/5 V, 0.7 W",
         source="kb.ettus.com/GPSDO (10 kHz: «< −145»)", url="https://kb.ettus.com/GPSDO"),
    dict(name="GPSDO per USRP (TCXO)", maker="Ettus Research", kind="GPSDO", outputs="10 MHz + 1 PPS", level="", f_ref_mhz=10.0,
         pn={1: -65, 10: -102, 100: -132, 10_000: -152}, stability="ADEV 1×10⁻¹¹ a 1 s", interface="RS-232: NMEA e SCPI",
         power="3.3 V, 0.5 W", source="kb.ettus.com/GPSDO (10 kHz: «< −152»)", url="https://kb.ettus.com/GPSDO"),
]
EDITABLE = ["f_ref_mhz", "outputs", "level", "stability", "interface", "power", "source"]


# ------------------------------------------------------------------ catalogue + the user's corrections
def models(settings: dict | None = None) -> list[dict]:
    """Catalogue with the user's corrections applied (verified=True) and the user's own models."""
    if settings is None:
        from . import settings as _s
        settings = _s.load_settings()
    over = settings.get("gpsdo_overrides") or {}
    out = []
    for m in MODELS:
        key = model_key(m)
        if key in over:
            mine = over[key]
            out.append({**m, **mine, "pn": _pn(mine.get("pn", m.get("pn"))), "verified": True, "origin": "edited", "catalog": m})
        else:
            out.append({**m, "verified": False, "origin": "catalog"})
    known = {model_key(m) for m in MODELS}
    for key, mine in over.items():
        if key not in known:
            out.append({"kind": "GPSDO", **mine, "pn": _pn(mine.get("pn")), "verified": True, "origin": "mine"})
    return out


def model_key(m: dict) -> str:
    return f"{(m.get('maker') or '').strip()} {(m.get('name') or '').strip()}".strip()


def _pn(pn) -> dict | None:
    if not pn:
        return None
    out = {}
    for k, v in pn.items():
        try:
            if v is not None and str(v).strip() != "":
                out[int(float(k))] = float(v)
        except (TypeError, ValueError):
            pass
    return out or None


def save_model(m: dict) -> dict:
    """Store a corrected or new model (keys of the catalogue; pn as {offset Hz: dBc/Hz})."""
    from . import settings as _s
    sets = _s.load_settings()
    over = dict(sets.get("gpsdo_overrides") or {})
    keep = {k: m.get(k) for k in ("name", "maker", "kind", "outputs", "level", "f_ref_mhz", "stability", "interface", "power",
                                  "source", "url", "datasheet") if m.get(k) not in (None, "")}
    keep["pn"] = {str(k): v for k, v in (_pn(m.get("pn")) or {}).items()}
    keep["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    over[model_key(m)] = keep
    return _s.save_settings(gpsdo_overrides=over)


def revert_model(key: str) -> bool:
    from . import settings as _s
    over = dict(_s.load_settings().get("gpsdo_overrides") or {})
    if key not in over:
        return False
    del over[key]
    _s.save_settings(gpsdo_overrides=over)
    return True


# ------------------------------------------------------------------ phase noise
def interp_pn(pn: dict, f: float) -> float | None:
    """dBc/Hz at offset f, straight lines on a log-frequency axis between the given points; below the first point
    the first slope continues (at least −20 dB/decade, at most −40), above the last the curve stays flat."""
    pts = sorted((k, v) for k, v in (_pn(pn) or {}).items())
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0][1]
    lx = [math.log10(k) for k, _ in pts]
    x = math.log10(max(f, 1e-3))
    if x <= lx[0]:
        slope = (pts[1][1] - pts[0][1]) / (lx[1] - lx[0])
        slope = min(max(slope, -40.0), -20.0)
        return pts[0][1] + slope * (x - lx[0])
    if x >= lx[-1]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        if lx[i] <= x <= lx[i + 1]:
            return pts[i][1] + (pts[i + 1][1] - pts[i][1]) * (x - lx[i]) / (lx[i + 1] - lx[i])
    return None


def multiply_db(f_ref_mhz: float, f_rf_mhz: float) -> float:
    return 20.0 * math.log10(f_rf_mhz / f_ref_mhz)


def integrated_rad2(pn: dict, f1: float, f2: float, add_db: float = 0.0, n: int = 400) -> float:
    """σ² (rad²) of the phase noise between f1 and f2 (both sidebands: 2·∫L(f)df), raised by add_db."""
    f = np.logspace(math.log10(f1), math.log10(f2), n)
    L = np.array([interp_pn(pn, x) for x in f]) + add_db
    y = 10 ** (L / 10.0)
    return float(2.0 * np.sum((y[1:] + y[:-1]) / 2.0 * np.diff(f)))


def tone_spacing_hz(mode: str) -> float:
    """'60E' → 26.7 Hz (Q65 tone spacing = baud × 1, 2, 4, 8, 16 for A…E; baud = 1/0.6 s at T/R 60 s)."""
    period, sub = int(mode[:-1]), mode[-1].upper()
    return Q65_BAUD_60 * 60.0 / period * Q65_SPACING.get(sub, 16)


def band_report(m: dict, band: str, mode: str, f2: float = 100_000.0) -> dict:
    """Phase noise of the model at the band's LO: dBc/Hz at the standard offsets, rms phase, estimated Q65 loss."""
    pn = _pn(m.get("pn"))
    f_rf = BAND_MHZ.get(band)
    if not pn or not f_rf or not m.get("f_ref_mhz"):
        return {"band": band, "ok": None}
    add = multiply_db(float(m["f_ref_mhz"]), f_rf)
    half = tone_spacing_hz(mode) / 2.0
    s_out = integrated_rad2(pn, half, f2, add)
    s_in = integrated_rad2(pn, 1.0, half, add)
    loss = 10.0 * math.log10(math.e) * s_out
    verdict = "ok" if loss < 0.5 else ("marginal" if loss < 2.0 else "poor")
    return {"band": band, "mode": mode, "add_db": add, "half_tone_hz": half,
            "at": {f: interp_pn(pn, f) + add for f in OFFSETS},
            "rms_deg_out": math.degrees(math.sqrt(s_out)), "rms_deg_in": math.degrees(math.sqrt(s_in)),
            "loss_db": loss, "ok": verdict}


# ------------------------------------------------------------------ reminder before operating
def reminder_due(settings: dict, now: datetime | None = None, hours: float = 12.0) -> bool:
    """True when the user uses a GPSDO and has not confirmed it locked in the last `hours`."""
    if not settings.get("gpsdo_use", True):
        return False
    now = now or datetime.now(timezone.utc)
    t = settings.get("gpsdo_ok_utc")
    if not t:
        return True
    try:
        last = datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - last > timedelta(hours=hours)


def confirm(now: datetime | None = None) -> dict:
    from . import settings as _s
    now = now or datetime.now(timezone.utc)
    return _s.save_settings(gpsdo_ok_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"))


# ------------------------------------------------------------------ live state from the serial port (NMEA)
def _nmea_ok(line: str) -> bool:
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, cs = line[1:].partition("*")
    x = 0
    for ch in body:
        x ^= ord(ch)
    try:
        return x == int(cs[:2], 16)
    except ValueError:
        return False


def parse_nmea(lines) -> dict:
    """GGA/RMC/GSV/GSA sentences → {"fix": bool, "quality", "sats_used", "sats_seen", "utc", "lat", "lon", "sentences"}."""
    st = {"fix": None, "quality": None, "sats_used": None, "sats_seen": None, "utc": None, "lat": None, "lon": None,
          "sentences": 0}
    for raw in lines:
        line = (raw.decode("ascii", "replace") if isinstance(raw, bytes) else str(raw)).strip()
        if not _nmea_ok(line):
            continue
        st["sentences"] += 1
        f = line[1:line.index("*")].split(",")
        typ = f[0][-3:]
        try:
            if typ == "GGA" and len(f) > 7:
                q = int(f[6] or 0)
                st["quality"], st["fix"] = q, q > 0
                st["sats_used"] = int(f[7]) if f[7] else st["sats_used"]
                st["utc"] = f[1][:6] or st["utc"]
                if f[2] and f[4]:
                    st["lat"] = (int(f[2][:2]) + float(f[2][2:]) / 60) * (-1 if f[3] == "S" else 1)
                    st["lon"] = (int(f[4][:3]) + float(f[4][3:]) / 60) * (-1 if f[5] == "W" else 1)
            elif typ == "RMC" and len(f) > 2:
                if st["fix"] is None:
                    st["fix"] = f[2] == "A"
                st["utc"] = st["utc"] or f[1][:6]
            elif typ == "GSV" and len(f) > 3 and f[3]:
                st["sats_seen"] = max(st["sats_seen"] or 0, int(f[3]))
            elif typ == "GSA" and len(f) > 2 and st["fix"] is None:
                st["fix"] = f[2] in ("2", "3")
        except (ValueError, IndexError):
            continue
    return st


def serial_ports() -> list[tuple[str, str]]:
    """[(port, description)] of this PC (needs pyserial; empty without it)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description or "") for p in list_ports.comports()]


def read_serial(port: str, seconds: float = 3.0, baud: int = 9600) -> dict:
    """Listen to the GPSDO's NMEA for a few seconds and return parse_nmea() of it (plus "error" on failure)."""
    try:
        import serial
    except ImportError:
        return {"error": "pyserial non installato"}
    lines = []
    try:
        with serial.Serial(port, baud, timeout=0.5) as s:
            end = datetime.now() + timedelta(seconds=seconds)
            while datetime.now() < end:
                ln = s.readline()
                if ln:
                    lines.append(ln)
    except Exception as e:
        return {"error": str(e)}
    out = parse_nmea(lines)
    out["port"] = port
    return out


# ------------------------------------------------------------------ live state of a Leo Bodnar clock over USB (HID)
LB_VID = 0x1DD2
LB_PIDS = {0x2211: "mini GPS Reference Clock", 0x2210: "GPS Disciplined Clock (doppia uscita)"}


def parse_lb_status(buf) -> dict:
    """Feature report of a Leo Bodnar mini/dual GPS clock → {"gps_ok", "pll_ok", "loss_count"}.
    Layout read from the maker's «mini GPS Clock Configuration» program (v1.15): byte 1 = signal loss count,
    byte 2 bit 0 = no GPS signal, bit 1 = no PLL lock (report id 0 in byte 0)."""
    b = bytes(buf or b"")
    if len(b) < 3:
        return {"error": "risposta troppo corta"}
    return {"gps_ok": not (b[2] & 0x01), "pll_ok": not (b[2] & 0x02), "loss_count": b[1], "raw": b[:16].hex(" ")}


def read_leo_bodnar() -> dict:
    """Read lock state from the Leo Bodnar clock on USB (needs the «hidapi» package; Windows needs no driver).
    Close the maker's configuration program first: it may keep the device busy."""
    try:
        import hid
    except ImportError:
        return {"error": "pacchetto hidapi non installato"}
    found = [d for d in hid.enumerate(LB_VID) if d.get("product_id") in LB_PIDS]
    if not found:
        return {"error": "nessun GPSDO Leo Bodnar (mini o doppia uscita) trovato sulle porte USB"}
    d0 = found[0]
    dev = hid.device()
    try:
        dev.open_path(d0["path"])
        buf = b""
        for n in (60, 61, 64, 9):
            try:
                buf = bytes(dev.get_feature_report(0, n))
            except (OSError, ValueError):
                continue
            if len(buf) >= 3:
                break
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            dev.close()
        except Exception:
            pass
    out = parse_lb_status(buf)
    out.update(model=LB_PIDS[d0["product_id"]], serial=d0.get("serial_number") or "",
               utc=datetime.now(timezone.utc).strftime("%H:%M:%S"))
    return out


# ------------------------------------------------------------------ phase noise estimate from a WAV
def measure_wav(data: bytes, offsets=(10, 30, 100, 300, 1_000, 3_000), seg_s: float = 4.0) -> dict:
    """Phase-noise estimate (dBc/Hz) of an unmodulated carrier in a WAV recording (WSJT-X «Save all», SDR audio…).

    The result is the noise of the whole chain: GPSDO × multiplication, the receiver's own LO, the far end's signal
    and the path. With a clean carrier (a beacon, your own transverter's LO leakage, a signal generator locked to the
    same GPSDO) it shows how close-in noise compares to the catalogue estimate; limits: half the sample rate and the
    noise floor of the recording."""
    with wave.open(io.BytesIO(data)) as w:
        fs, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("serve un WAV PCM a 16 bit")
    x = np.frombuffer(raw, dtype="<i2").astype(float)
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    nper = int(2 ** math.floor(math.log2(max(256, min(len(x), fs * seg_s)))))
    if len(x) < nper:
        raise ValueError("registrazione troppo corta")
    k_ = np.arange(nper) / nper                         # 4-term Blackman-Harris: sidelobes −92 dB, low leakage close in
    win = 0.35875 - 0.48829 * np.cos(2 * np.pi * k_) + 0.14128 * np.cos(4 * np.pi * k_) - 0.01168 * np.cos(6 * np.pi * k_)
    step = nper // 2
    psd = np.zeros(nper // 2 + 1)
    k = 0
    for i in range(0, len(x) - nper + 1, step):
        seg = x[i:i + nper]
        psd += np.abs(np.fft.rfft((seg - seg.mean()) * win)) ** 2
        k += 1
    psd /= k * fs * np.sum(win ** 2)                     # one-sided density (units²/Hz) up to a factor 2
    df = fs / nper
    f = np.arange(len(psd)) * df
    i0 = int(np.argmax(psd[int(50 / df):])) + int(50 / df)          # ignore DC / hum below 50 Hz
    w_bins = 6
    carrier = float(np.sum(psd[max(0, i0 - w_bins):i0 + w_bins + 1]) * df)
    fc = f[i0]
    out = {}
    for off in offsets:
        vals = []
        for sgn in (-1, 1):
            lo, hi = fc + sgn * off * 0.9, fc + sgn * off * 1.1
            a, b = sorted((lo, hi))
            sel = (f >= a) & (f <= b)
            if a > 0 and b < fs / 2 and sel.any():
                vals.append(float(np.median(psd[sel])))
        if vals and off > (w_bins + 1) * df:
            out[off] = 10 * math.log10(np.mean(vals) / carrier)
    floor = 10 * math.log10(float(np.median(psd[1:])) / carrier)
    return {"fs": fs, "f_carrier_hz": float(fc), "resolution_hz": df, "pn": out, "floor_dbc_hz": floor,
            "seconds": len(x) / fs}


# ------------------------------------------------------------------ phase noise from datasheet text
_PN_RE = None


def read_pn_text(text: str) -> dict:
    """Phase-noise points found in a datasheet's text: '10 Hz -100 dBc/Hz', '1kHz: −145', '100Hz offset -125 dBc'…"""
    import re
    global _PN_RE
    if _PN_RE is None:
        _PN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k|K|M)?\s*Hz[^\d\-−–\n]{0,25}([\-−–]\s?\d{2,3}(?:[.,]\d)?)\s*(?:dBc)?", re.I)
    out = {}
    for m in _PN_RE.finditer(text or ""):
        f = float(m.group(1).replace(",", ".")) * {"k": 1e3, "K": 1e3, "M": 1e6}.get(m.group(2) or "", 1)
        v = float(m.group(3).replace("−", "-").replace("–", "-").replace(" ", "").replace(",", "."))
        if f in OFFSETS and -180 <= v <= -40 and int(f) not in out:
            out[int(f)] = v
    return out
