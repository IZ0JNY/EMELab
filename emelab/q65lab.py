# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""🧪 Q65 Lab: an experimental Q65 decoder listening next to WSJT-X.

EMELab takes the receive audio from the same sound card as WSJT-X (the IC-9700 «USB Audio CODEC» by default, or the
«SoundInName» of WSJT-X.ini), cuts it into T/R periods on the PC clock and decodes each period twice with q65lab
(decoder/q65lab: the Q65 decoder of WSJT-X v3.0.2, GPLv3):

  · «come WSJT-X»  the WSJT-X decoder exactly, on the same audio: the reference;
  · «Q65 Lab»      the same decoder with the metric matched to the expected spread: Gaussian fading model and wider
                   spectral smoothing when the libration spread is wide (24 GHz and up), linear averages.

Study of Nov 2026 (simulations): about +1 dB at 24 GHz Q65-60E with a Moon-like spread of 250 Hz, nothing at 10 GHz,
+0.5 dB with averages of 12-16 periods. Saved WSJT-X periods (File → Save all) can be decoded the same way.
EMELab never changes WSJT-X: the parameters (mode, Rx frequency, F Tol, DX call and grid) are read from its UDP status
and from WSJT-X.ini.
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

FS = 12000                                   # sample rate of the decoder (WSJT-X)
SUBMODES = "ABCDE"
TR_OK = (15, 30, 60, 120, 300)
KEEP_PERIODS = 120                           # recorded periods kept on disk for «decodifica di nuovo»


# ------------------------------------------------------------------ the decoder program
def find_decoder() -> Path | None:
    """q65lab(.exe): EMELAB_Q65LAB, next to the app (installer: <EMELab>\\q65lab), build/q65lab of a source tree, PATH."""
    exe = "q65lab.exe" if os.name == "nt" else "q65lab"
    here = Path(__file__).resolve().parent
    cands = [Path(os.environ["EMELAB_Q65LAB"])] if os.environ.get("EMELAB_Q65LAB") else []
    cands += [here.parent.parent / "q65lab" / exe, here.parent / "q65lab" / exe, here.parent / "build" / "q65lab" / exe]
    w = shutil.which(exe)
    if w:
        cands.append(Path(w))
    return next((c for c in cands if c.is_file()), None)


def work_dir() -> Path:
    from emelab import settings
    p = settings.config_dir() / "q65lab"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class Knobs:
    fade: int = 1             # 1 Lorentzian (WSJT-X), 0 Gaussian
    smo: int = 100            # spectral smoothing, % of WSJT-X
    ntc: int = 4              # averaging time constant (4 = WSJT-X; large = linear average)

    def label(self) -> str:
        return (("Lorentziano" if self.fade else "campana") + f" · smussatura {self.smo}%"
                + (" · media lineare" if self.ntc > 100 else f" · media {self.ntc} periodi"))


WSJTX_KNOBS = Knobs()
LINEAR = 100000


def lab_knobs(spread_hz: float | None) -> Knobs:
    """The Q65 Lab profile for the expected libration spread (Hz at the band): below 80 Hz the WSJT-X metric (it is
    already right there), from 80 Hz a Gaussian model and 2× smoothing, from 200 Hz 3× smoothing. Always linear
    averages."""
    if spread_hz is None or spread_hz < 80:
        return Knobs(1, 100, LINEAR)
    return Knobs(0, 200 if spread_hz < 200 else 300, LINEAR)


class Decoder:
    """One q65lab process, kept alive between periods (the averages live in it)."""

    def __init__(self, exe: Path | str, cwd: Path | str, knobs: Knobs = WSJTX_KNOBS):
        self.exe, self.cwd = str(exe), Path(cwd)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.knobs = None
        self.p = None
        self._lock = threading.RLock()
        self.set_knobs(knobs)

    def _start(self):
        # below normal priority: WSJT-X always gets the CPU first, Q65 Lab never slows it down
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        self.p = subprocess.Popen([self.exe], cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1, creationflags=flags)
        if not flags and hasattr(os, "setpriority"):
            try:
                os.setpriority(os.PRIO_PROCESS, self.p.pid, 10)
            except OSError:
                pass
        if self.knobs:
            k, self.knobs = self.knobs, None
            self.set_knobs(k)

    def _cmd(self, line: str) -> list[str]:
        """Sends one command; returns the lines up to and including the final «E …»."""
        if self.p is None or self.p.poll() is not None:
            self._start()
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        out = []
        while True:
            r = self.p.stdout.readline()
            if not r:
                raise RuntimeError("q65lab si è chiuso")
            r = r.rstrip("\n")
            out.append(r)
            if r.startswith("E"):
                return out

    def set_knobs(self, k: Knobs):
        with self._lock:
            if k == self.knobs:
                return
            if self.p is None:
                self.knobs = k
                self._start()
                return
            for key, v in (("FADE", k.fade), ("SMO", k.smo), ("NTC", k.ntc)):
                self._cmd(f"SET {key} {v}")
            self.knobs = k

    def clear(self):
        with self._lock:
            self._cmd("CLEAR")

    def decode(self, wav: Path | str, utc: datetime, tr: int, submode: str, rx_hz: int, ftol: int, depth: int = 3,
               mycall: str = "", dxcall: str = "", dxgrid: str = "", max_drift: int = 0, eme_delay: bool = True) -> dict:
        """{"decodes": [{"utc", "snr", "dt", "freq", "q", "nused", "message"}], "navg": (even, odd), "ms", "red"}."""
        hhmm = utc.strftime("%H%M") if tr >= 60 else utc.strftime("%H%M%S")
        args = ['"' + str(Path(wav).resolve()) + '"', hhmm, str(tr), submode, str(int(rx_hz)), str(int(ftol)), str(int(depth)),
                _tok(mycall), _tok(dxcall), _tok(dxgrid[:4] if dxgrid else ""), str(int(max_drift)),
                "1" if eme_delay else "0", "0"]
        with self._lock:
            lines = self._cmd("DECODE " + " ".join(args))
        return parse_output(lines, utc) | {"red": read_red(self.cwd / "q65lab_red.dat")}

    def close(self):
        try:
            if self.p and self.p.poll() is None:
                self.p.stdin.write("QUIT\n")
                self.p.stdin.flush()
                self.p.wait(3)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def _tok(s: str) -> str:
    s = (s or "").strip().upper()
    return s if s and " " not in s else "-"


def parse_output(lines: list[str], utc: datetime | None = None) -> dict:
    out = {"decodes": [], "navg": (0, 0), "ms": None, "error": None}
    for r in lines:
        if r.startswith("D "):
            p = r.split(None, 7)
            if len(p) < 8:
                continue
            out["decodes"].append({"utc": utc, "snr": int(p[2]), "dt": float(p[3]), "freq": float(p[4]),
                                   "q": int(p[5]), "nused": int(p[6]), "message": p[7].strip()})
        elif r.startswith("E ERR"):
            out["error"] = r[6:].strip()
        elif r.startswith("E "):
            p = r.split()
            if len(p) == 4 and all(x.lstrip("-").isdigit() for x in p[1:]):
                out["navg"], out["ms"] = (int(p[1]), int(p[2])), int(p[3])
    return out


def read_red(path: Path) -> dict | None:
    """Sync curves of the last decode: {"f": Hz, "avg": red (average), "cur": orange (this period)}."""
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            a = np.loadtxt(path, max_rows=4000)
    except Exception:
        return None
    if a.ndim != 2 or a.shape[0] < 3 or a.shape[1] < 3:
        return None
    return {"f": a[1:, 0], "avg": a[1:, 1], "cur": a[1:, 2]}


# ------------------------------------------------------------------ audio files
def write_wav(path: Path | str, x: np.ndarray, fs: int = FS):
    """16-bit mono PCM; x as float (±1 full scale) or int16."""
    x = np.asarray(x)
    if x.dtype != np.int16:
        x = np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(x.tobytes())


def read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    """(float samples ±1, sample rate); the first channel of a stereo file."""
    with wave.open(str(path), "rb") as w:
        n, ch, sw, fs = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("serve un .wav a 16 bit")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return (x.reshape(-1, ch)[:, 0] if ch > 1 else x), fs


def to_12k(x: np.ndarray, fs: int) -> np.ndarray:
    if fs == FS:
        return np.asarray(x, dtype=np.float32)
    from math import gcd
    from scipy.signal import resample_poly
    g = gcd(int(fs), FS)
    return resample_poly(x, FS // g, int(fs) // g).astype(np.float32)


def ensure_12k(path: Path, out_dir: Path) -> Path:
    """The file itself if already 12 kHz mono 16 bit (WSJT-X's own), otherwise a converted copy."""
    with wave.open(str(path), "rb") as w:
        if w.getframerate() == FS and w.getnchannels() == 1 and w.getsampwidth() == 2:
            return path
    x, fs = read_wav(path)
    out = out_dir / (path.stem + "_12k.wav")
    write_wav(out, to_12k(x, fs))
    return out


def saved_time(name: str) -> datetime | None:
    """UTC of a WSJT-X saved period from its name (YYMMDD_HHMM.wav or YYMMDD_HHMMSS.wav)."""
    stem = Path(name).stem
    for n, fmt in ((13, "%y%m%d_%H%M%S"), (11, "%y%m%d_%H%M")):
        if len(stem) < n or (n == 11 and len(stem) > 11 and stem[11].isdigit()):
            continue
        try:
            return datetime.strptime(stem[:n], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def save_dir(ini_path: Path | str | None = None) -> Path | None:
    """WSJT-X's «save» folder, next to WSJT-X.ini (File → Open save directory)."""
    try:
        from emelab import wsjtx_ini
        p = Path(ini_path) if ini_path else wsjtx_ini.find()
    except Exception:
        p = None
    if not p:
        return None
    d = (p if p.is_dir() else p.parent) / "save"
    return d if d.is_dir() else None


def saved_files(folder: Path | str | None, limit: int = 400) -> list[dict]:
    """Newest first: {"path", "name", "utc", "bytes"}."""
    if not folder:
        return []
    try:
        fs = [p for p in Path(folder).glob("*.wav") if p.is_file()]
    except OSError:
        return []
    out = [{"path": p, "name": p.name, "utc": saved_time(p.name), "bytes": p.stat().st_size} for p in fs]
    out.sort(key=lambda r: (r["utc"] or datetime.min.replace(tzinfo=timezone.utc), r["name"]), reverse=True)
    return out[:limit]


def pick_wav_files(initial_dir: Path | str | None = None) -> list[Path] | None:
    """The Windows «Open» dialog (several .wav at once), opened in initial_dir; [] when cancelled, None when no
    dialog can be shown on this PC (then the page offers an upload box)."""
    init = str(initial_dir or Path.home()).replace("'", "''")
    if os.name == "nt":
        ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Add-Type -AssemblyName System.Windows.Forms; "
              "$f=New-Object System.Windows.Forms.Form -Property @{TopMost=$true}; "
              "$d=New-Object System.Windows.Forms.OpenFileDialog; $d.Filter='WAV (*.wav)|*.wav'; $d.Multiselect=$true; "
              f"$d.Title='Q65 Lab'; $d.InitialDirectory='{init}'; "
              "if($d.ShowDialog($f) -eq 'OK'){ $d.FileNames }")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, timeout=600,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            return None
        return [Path(x) for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip().lower().endswith(".wav")]
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        fs = filedialog.askopenfilenames(initialdir=str(initial_dir or Path.home()), filetypes=[("WAV", "*.wav")])
        root.destroy()
        return [Path(x) for x in fs]
    except Exception:
        return None


def file_time(path: Path | str) -> datetime:
    """UTC of a period file: from the WSJT-X name, else the file time minus nothing (start unknown)."""
    p = Path(path)
    t = saved_time(p.name)
    if t:
        return t
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc)


def read_alltxt(path: Path | str | None) -> list[dict]:
    """Q65 lines of WSJT-X's ALL.TXT (Rx decodes and own Tx): utc, rxtx, mode ('Q65-60E'), snr_db, dt_s, df_hz,
    message, band. [] if missing."""
    if not path:
        return []
    try:
        from emelab import alltxt
        rows = []
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if "Q65" in line:
                r = alltxt.parse_line(line)
                if r and str(r.get("mode", "")).startswith("Q65"):
                    rows.append(r)
        return rows
    except Exception:
        return []


def wsjtx_decodes_at(rows: list[dict], utc: datetime, tr: int) -> list[dict]:
    """What WSJT-X itself decoded in the period starting at utc (from ALL.TXT), in the shape of merge()."""
    t1 = utc + timedelta(seconds=tr)
    return [{"message": r["message"], "snr": r["snr_db"], "dt": r["dt_s"], "freq": float(r["df_hz"]), "q": None,
             "nused": None} for r in rows if r["rxtx"] == "Rx" and utc <= r["utc"] < t1]


def guess_params(rows: list[dict], utc: datetime, window_min: float = 30) -> dict:
    """Mode, Rx frequency and DX of a saved period from the nearest ALL.TXT lines (within window_min): what WSJT-X was
    doing at that time. {} when nothing is near."""
    near = [r for r in rows if abs((r["utc"] - utc).total_seconds()) <= window_min * 60]
    if not near:
        return {}
    r = min(near, key=lambda r: abs((r["utc"] - utc).total_seconds()))
    out = {}
    m = str(r["mode"])[4:]                                   # '60E'
    if m[:-1].isdigit() and m[-1:] in SUBMODES and int(m[:-1]) in TR_OK:
        out["tr"], out["submode"] = int(m[:-1]), m[-1]
    tx = [x for x in near if x["rxtx"] == "Tx"]
    if tx:                                                   # Rx = Tx frequency in Q65 EME practice
        out["rx_hz"] = min(tx, key=lambda x: abs((x["utc"] - utc).total_seconds()))["df_hz"]
        w = min(tx, key=lambda x: abs((x["utc"] - utc).total_seconds()))["message"].split()
        if len(w) >= 2 and w[0] not in ("CQ", "QRZ"):
            out["dx_call"] = w[0]
    elif r["rxtx"] == "Rx":
        out["rx_hz"] = r["df_hz"]
    return out


# ------------------------------------------------------------------ sound card
DEFAULT_DEVICE_HINT = "USB Audio CODEC"     # IC-9700 (and IC-705/7300/7610) built-in codec


def ini_audio(ini_path: Path | str | None = None) -> dict:
    """{"device": SoundInName, "channel": Mono/Left/Right/Both} of WSJT-X.ini ({} if not found)."""
    try:
        from emelab import wsjtx_ini
        p = Path(ini_path) if ini_path else wsjtx_ini.find()
        if not p or not p.is_file():
            return {}
        conf = wsjtx_ini.parse(p.read_text(encoding="utf-8", errors="replace")).get("Configuration", {})
    except Exception:
        return {}
    return {k: v for k, v in (("device", (conf.get("SoundInName") or "").strip()),
                              ("channel", (conf.get("AudioInputChannel") or "").strip())) if v}


def input_devices() -> list[dict]:
    """[{"index", "name", "api", "rate"}] of the capture devices (empty without sounddevice/PortAudio)."""
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        return [{"index": i, "name": d["name"], "api": apis[d["hostapi"]]["name"], "rate": int(d["default_samplerate"])}
                for i, d in enumerate(sd.query_devices()) if d.get("max_input_channels", 0) > 0]
    except Exception:
        return []


def pick_device(devs: list[dict], wanted: str | None = None) -> dict | None:
    """The device WSJT-X uses (same name, or the name cut to 31 characters as MME does), else the IC-9700 codec;
    MME first (it shares the card with WSJT-X and resamples)."""
    def score(d):
        n, w = d["name"].lower(), (wanted or "").lower()
        s = 0
        if w and (n == w or n.startswith(w[:31]) or w.startswith(n)):
            s += 100
        elif w and w in n:
            s += 80
        if DEFAULT_DEVICE_HINT.lower() in n:
            s += 40
        s += {"MME": 3, "Windows WASAPI": 2, "Windows DirectSound": 1}.get(d["api"], 0)
        return s
    if not devs:
        return None
    best = max(devs, key=score)
    return best if score(best) >= 40 else None


def same_card(devs: list[dict], name: str) -> list[dict]:
    """The entries of one sound card in the other Windows audio systems (MME cuts names to 31 characters), in the
    order to try them when one gives only silence: MME, WASAPI, DirectSound (never WDM-KS, which is exclusive)."""
    key = (name or "").lower()[:31].strip()
    order = {"MME": 0, "Windows WASAPI": 1, "Windows DirectSound": 2}
    out = [d for d in devs if d["api"] in order and key and d["name"].lower()[:31].strip() == key]
    return sorted(out, key=lambda d: order[d["api"]])


SILENCE_DBFS = -85.0                          # below this the card gives zeros: blocked, muted or the wrong entry
BAND_GHZ = {"10G": 10.368, "24G": 24.048, "47G": 47.088, "76G": 76.032, "122G": 122.25, "134G": 134.928}


class Capture:
    """Sound card → mono float samples with their UTC time (sounddevice/PortAudio, shared with WSJT-X)."""

    def __init__(self, device: int | None, channel: str = "Mono", rate: int = 48000, seconds: float = 330.0):
        self.device, self.channel, self.rate = device, channel or "Mono", int(rate)
        self.buf = np.zeros(int(seconds * self.rate), dtype=np.float32)
        self.n = 0                   # samples received in all
        self.t0 = None               # UTC (s, epoch) of sample 0
        self.level_db = None
        self.error = None
        self.stream = None
        self._lock = threading.Lock()

    def start(self):
        import sounddevice as sd
        ch = 2 if self.channel in ("Left", "Right", "Both") else 1

        def cb(indata, frames, tinfo, status):
            x = indata[:, 1] if self.channel == "Right" else (indata.mean(axis=1) if self.channel == "Both" else indata[:, 0])
            now = time.time()
            with self._lock:
                if self.t0 is None:
                    self.t0 = now - frames / self.rate - (self.stream.latency if self.stream else 0.0)
                i = self.n % len(self.buf)
                k = min(frames, len(self.buf) - i)
                self.buf[i:i + k] = x[:k]
                if k < frames:
                    self.buf[:frames - k] = x[k:]
                self.n += frames
                rms = float(np.sqrt(np.mean(np.square(x)))) if frames else 0.0
                self.level_db = 20 * np.log10(max(rms, 1e-6))
        try:
            self.stream = sd.InputStream(device=self.device, channels=ch, samplerate=self.rate, dtype="float32",
                                         blocksize=int(self.rate * 0.1), callback=cb)
            self.stream.start()
        except Exception as e:
            self.error = str(e)
            raise
        return self

    def stop(self):
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None

    def take(self, t_start: float, seconds: float) -> np.ndarray | None:
        """Samples from UTC t_start (epoch s) for «seconds», resampled to 12 kHz; None if not (or no longer) there."""
        with self._lock:
            if self.t0 is None:
                return None
            i0 = int(round((t_start - self.t0) * self.rate))
            n = int(seconds * self.rate)
            if i0 + n > self.n or self.n - i0 > len(self.buf):
                return None
            lo = max(i0, 0)
            idx = np.arange(lo, i0 + n) % len(self.buf)
            x = np.concatenate([np.zeros(lo - i0, np.float32), self.buf[idx]])
        return to_12k(x, self.rate)

    def latest(self, seconds: float) -> np.ndarray | None:
        with self._lock:
            n = int(seconds * self.rate)
            if self.n < n:
                return None
            idx = np.arange(self.n - n, self.n) % len(self.buf)
            x = self.buf[idx].copy()
        return to_12k(x, self.rate)


class FileSource(Capture):
    """.wav files played as if they came from the sound card: file i is the period that starts i T/R periods after
    the current one began (demo and tests)."""

    def __init__(self, files: list[Path | str], tr: int = 60):
        super().__init__(None, "Mono", FS, seconds=330.0)
        self.files, self.tr = [Path(f) for f in files], tr
        self._stop = threading.Event()

    def start(self):
        chunks = []
        for f in self.files:
            x = read_wav(f)[0][:self.tr * FS]
            chunks.append(np.pad(x, (0, self.tr * FS - len(x))))
        data = np.concatenate(chunks) if chunks else np.zeros(self.tr * FS, np.float32)
        now = time.time()
        self.t0 = now - (now % self.tr)

        def push(k, m):
            chunk = data[np.arange(k, k + m) % len(data)]
            with self._lock:
                i = self.n % len(self.buf)
                j = min(m, len(self.buf) - i)
                self.buf[i:i + j] = chunk[:j]
                if j < m:
                    self.buf[:m - j] = chunk[j:]
                self.n += m
                self.level_db = 20 * np.log10(max(float(np.sqrt(np.mean(chunk ** 2))), 1e-6))

        def run():
            while not self._stop.is_set():
                target = int((time.time() - self.t0) * FS)
                while self.n < target:
                    push(self.n, min(target - self.n, FS // 10))
                time.sleep(0.1)
        threading.Thread(target=run, name="q65lab-file", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()


# ------------------------------------------------------------------ waterfall
WF_DF = FS / 8192                              # 1.465 Hz: the bin of the WSJT-X Wide Graph


@dataclass
class WfView:
    """How the waterfall is shown, as the controls of the WSJT-X Wide Graph."""
    start: int = 200               # Hz at the left edge («Start»)
    span: int = 2800               # Hz shown («Bins/Pixel» × width)
    navg: int = 5                  # «N Avg»: one row every navg × 0.2 s (5 = one per second)
    gain: int = 0                  # contrast −50…50
    zero: int = 0                  # brightness −50…50
    palette: str = "wsjtx"         # see PALETTES
    flatten: bool = True           # «Flatten»: removes the shape of the receiver passband
    use_ref: bool = False          # «Ref Spec»: divides by the reference spectrum of WSJT-X (refspec.dat)
    spectrum: bool = True          # cumulative spectrum of the period under the waterfall («Cumulative»)

    def step(self) -> float:
        return max(0.2, 0.2 * int(self.navg or 5))


PALETTES = {   # name → colour stops (position, r, g, b)
    "wsjtx": [[0.00, 0.03, 0.05, 0.12], [0.35, 0.05, 0.20, 0.55], [0.60, 0.10, 0.65, 0.85],
              [0.82, 0.98, 0.85, 0.20], [1.00, 1.00, 1.00, 1.00]],
    "blue": [[0.00, 0.00, 0.02, 0.10], [0.50, 0.05, 0.25, 0.70], [0.85, 0.45, 0.80, 1.00], [1.00, 1.00, 1.00, 1.00]],
    "gray": [[0.00, 0.04, 0.04, 0.05], [1.00, 1.00, 1.00, 1.00]],
    "warm": [[0.00, 0.02, 0.01, 0.05], [0.35, 0.40, 0.05, 0.40], [0.65, 0.90, 0.30, 0.10],
             [0.88, 1.00, 0.80, 0.25], [1.00, 1.00, 1.00, 0.90]],
}
INI_PALETTES = {"default": "wsjtx", "blue1": "blue", "blue2": "blue", "blue3": "blue", "gray1": "gray",
                "gray2": "gray", "fldigi": "warm", "linrad": "warm", "cutesdr": "blue"}


def ini_widegraph(ini_path: Path | str | None = None) -> dict:
    """WfView fields from the [WideGraph] section of WSJT-X.ini (read only; {} if not found)."""
    try:
        from emelab import wsjtx_ini
        p = Path(ini_path) if ini_path else wsjtx_ini.find()
        if not p or not p.is_file():
            return {}
        wg = wsjtx_ini.parse(p.read_text(encoding="utf-8", errors="replace")).get("WideGraph", {})
    except Exception:
        return {}
    num = lambda k, d: int(float(wg[k])) if str(wg.get(k, "")).strip().lstrip("-").replace(".", "", 1).isdigit() else d
    yes = lambda k, d: str(wg[k]).strip().lower() == "true" if k in wg else d
    out = {}
    if "StartFreq" in wg:
        out["start"] = max(0, min(4500, num("StartFreq", 200)))
    if "BinsPerPixel" in wg or "PlotWidth" in wg:
        out["span"] = int(max(200, min(5000 - out.get("start", 0), num("BinsPerPixel", 2) * num("PlotWidth", 1000) * WF_DF)))
    if "WaterfallAvg" in wg:
        out["navg"] = max(1, min(50, num("WaterfallAvg", 5)))
    if "WaterfallPalette" in wg:
        out["palette"] = INI_PALETTES.get(str(wg["WaterfallPalette"]).strip().lower(), "wsjtx")
    if "Flatten" in wg:
        out["flatten"] = yes("Flatten", True)
    if "UseRef" in wg:
        out["use_ref"] = yes("UseRef", False)
    if "Cumulative" in wg:
        out["spectrum"] = yes("Cumulative", True)
    return out


def refspec_path(ini_path: Path | str | None = None) -> Path | None:
    """refspec.dat of WSJT-X (Tools → Measure reference spectrum), next to WSJT-X.ini."""
    try:
        from emelab import wsjtx_ini
        p = Path(ini_path) if ini_path else wsjtx_ini.find()
    except Exception:
        return None
    r = p.parent / "refspec.dat" if p else None
    return r if r and r.is_file() else None


def read_refspec(path: Path | str | None) -> tuple[np.ndarray, np.ndarray] | None:
    """(Hz, dB relative to 1000–2000 Hz) of refspec.dat: a header line, then «freq s ref fil filter» per bin."""
    if not path:
        return None
    f, db = [], []
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            v = line.split()
            if len(v) == 5 and "." in v[0]:
                try:
                    f.append(float(v[0]))
                    db.append(float(v[2]))
                except ValueError:
                    pass
    except OSError:
        return None
    if len(f) <= 100:
        return None
    db = np.array(db)
    k = 41                                     # only the passband shape: the bin-to-bin ripple would draw stripes
    db = np.convolve(np.pad(db, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    return np.array(f), db


NSPS = {15: 1800, 30: 3600, 60: 7200, 120: 16000, 300: 41472}       # samples per Q65 symbol at 12 kHz


def q65_bandwidth(tr: int, submode: str) -> float:
    """Hz occupied by a Q65 signal: 65 tones (sync + 64 data) above the Rx frequency."""
    n = SUBMODES.index(submode) if submode in SUBMODES else 3
    return 65 * FS / NSPS.get(int(tr or 60), 7200) * 2 ** n


def auto_view(p: dict, base: WfView | None = None) -> WfView:
    """The view adapted to the situation: from Rx − F Tol to the top tone of the submode + F Tol (+ the expected
    spread), so that the whole signal and nothing else fills the waterfall; the other choices stay those of «base»."""
    base = base or WfView()
    rx, ftol = float(p.get("rx_hz") or 1000), float(p.get("ftol") or 100)
    bw = q65_bandwidth(p.get("tr", 60), p.get("submode", "D"))
    spread = float(p.get("spread_hz") or 0)
    lo, hi = rx - ftol - spread / 2, rx + bw + ftol + spread / 2
    m = max(50.0, 0.08 * (hi - lo))
    lo, hi = max(0.0, lo - m), min(5000.0, hi + m)
    if hi - lo < 300:
        c = (hi + lo) / 2
        lo, hi = max(0.0, c - 150), min(5000.0, c + 150)
    return WfView(**{**base.__dict__, "start": int(lo // 10 * 10), "span": int(np.ceil((hi - lo) / 10) * 10)})


class Waterfall:
    """Rows of the spectrum 0–5000 Hz (WSJT-X «Wide Graph»), newest last, one row per «step» seconds; the WfView
    chooses the part shown and how."""

    def __init__(self, f_lo: float = 0.0, f_hi: float = 5000.0, nfft: int = 8192, step: float = 1.0, rows: int = 600):
        self.f_lo, self.f_hi, self.nfft, self.step = f_lo, f_hi, nfft, step
        f = np.fft.rfftfreq(nfft, 1 / FS)
        self.sel = (f >= f_lo) & (f <= f_hi)
        self.freqs = f[self.sel]
        self.rows = deque(maxlen=rows)
        self.times = deque(maxlen=rows)
        self.win = np.hanning(nfft).astype(np.float32)
        self.ref = None                                  # (Hz, dB) of refspec.dat
        self.trace = None                                # (Hz, dB over the noise) of a likely signal in Rx ± F Tol

    def add(self, x12k: np.ndarray, t: float):
        """One row from the last samples: average of 4 overlapping FFTs (Welch), smoothed over 3 bins, so that weak
        traces stand out of the speckle as in WSJT-X («Avg»)."""
        if x12k is None or len(x12k) < self.nfft:
            return
        x = np.asarray(x12k, dtype=np.float32)
        hop = max(1, min(self.nfft // 2, (len(x) - self.nfft) // 3)) if len(x) > self.nfft else 0
        segs = [x[len(x) - self.nfft - k * hop: len(x) - k * hop] for k in range(4 if hop else 1)]
        s = np.mean([np.abs(np.fft.rfft(g * self.win)) ** 2 for g in segs], axis=0)
        s = np.convolve(s, np.ones(3) / 3, mode="same")
        db = 10 * np.log10(s[self.sel] + 1e-12)
        self.rows.append(db.astype(np.float32))
        self.times.append(t)

    def _levels(self, view: WfView):
        """Rows of the view (newest first), with Ref Spec, row levelling and Flatten applied; and their Hz."""
        lo = max(self.f_lo, float(view.start))
        hi = min(self.f_hi, lo + max(100.0, float(view.span)))
        cols = (self.freqs >= lo) & (self.freqs <= hi)
        z = np.array(self.rows)[::-1][:, cols]
        f = self.freqs[cols]
        if view.use_ref and self.ref is not None:
            # only the passband shape: never lift by more than 12 dB where the radio filter has cut (noise would light up)
            z = z - np.maximum(np.interp(f, self.ref[0], self.ref[1]), -12.0)[None, :]
        z = z - np.median(z, axis=1, keepdims=True)                 # same level on every row
        if view.flatten and z.shape[1] > 80:
            base = np.percentile(z, 25, axis=0)                      # the passband shape, smoothed over ~60 bins
            k = 61                                                   # so that a narrow trace stays
            base = np.convolve(np.pad(base, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
            z = z - base[None, :]
        return z, f, lo, hi

    def image(self, rx_hz: float | None = None, ftol: float | None = None, width: int = 1100, height: int = 420,
              marks: list[tuple[float, str]] | None = None, dark: bool = True, view: WfView | None = None,
              spec_rows: int = 60, spread_hz: float | None = None):
        """RGB numpy image: frequency axis, waterfall with the newest row at the top as in WSJT-X, Rx frequency
        (green) and F Tol band, a line at each T/R period with its UTC; below, the cumulative spectrum of the last
        «spec_rows» rows."""
        from PIL import Image, ImageDraw
        view = view or WfView()
        h_axis = 22
        h_spec = int(height * 0.27) if view.spectrum else 0
        h_wf = height - h_axis - h_spec
        bg = (14, 17, 23) if dark else (250, 250, 250)
        img = Image.new("RGB", (width, height), bg)
        lo, hi = max(self.f_lo, float(view.start)), min(self.f_hi, float(view.start) + max(100.0, float(view.span)))
        spec = None
        if self.rows:
            z, f, lo, hi = self._levels(view)
            spec = z[:max(1, min(len(z), spec_rows))].mean(axis=0)
            if len(z) >= 3:                                              # a light 3-row blend against speckle
                z = np.vstack([z[:1], (z[:-2] + 2 * z[1:-1] + z[2:]) / 4, z[-1:]])
            a, b = np.percentile(z, 55), np.percentile(z, 99.9) + 1.0
            a -= (b - a) * view.zero / 100.0                             # «Zero»: brighter background
            b = a + (b - a) * 10 ** (-view.gain / 50.0)                  # «Gain»: more contrast
            u = np.clip((z - a) / max(b - a, 1e-3), 0, 1) ** 1.4         # calm background, traces bright
            rgb = (_cmap(u, view.palette) * 255).astype(np.uint8)
            wf = Image.fromarray(rgb).resize((width, h_wf), Image.NEAREST if len(z) < 50 else Image.BOX)
            img.paste(wf, (0, h_axis))
        d = ImageDraw.Draw(img)
        fx = lambda fr: int((fr - lo) / max(hi - lo, 1) * (width - 1))
        axis = (200, 205, 215) if dark else (40, 40, 40)
        span = hi - lo
        major = 500 if span > 1800 else 200 if span > 700 else 100
        minor = major // 5
        for fr in range(int(np.ceil(lo / minor) * minor), int(hi) + 1, minor):
            x = fx(fr)
            if fr % major == 0:
                d.line([(x, h_axis - 6), (x, h_axis)], fill=axis)
                d.text((max(0, min(width - 30, x - 14)), 3), f"{fr}", fill=axis)
            else:
                d.line([(x, h_axis - 3), (x, h_axis)], fill=axis)
        if rx_hz:
            if ftol:
                d.rectangle([fx(rx_hz - ftol), 0, fx(rx_hz + ftol), h_axis - 1], outline=(46, 160, 67))
            d.line([(fx(rx_hz), 0), (fx(rx_hz), h_axis - 1)], fill=(46, 200, 80), width=3)
        if self.rows and marks:
            n = len(self.rows)
            ts = list(self.times)
            for t_mark, text in marks:
                k = next((i for i in range(n - 1, -1, -1) if ts[i] <= t_mark), None)
                if k is None:
                    continue
                y = h_axis + int((n - 1 - k) / max(n, 1) * h_wf)
                d.line([(0, y), (width, y)], fill=(255, 255, 255) if dark else (0, 0, 0))
                d.text((4, y + 2), text, fill=(255, 255, 255) if dark else (0, 0, 0))
        if h_spec:
            y0 = h_axis + h_wf
            d.rectangle([0, y0, width, height], fill=(10, 12, 16) if dark else (240, 240, 240))
            grid = (40, 46, 58) if dark else (210, 210, 210)
            for fr in range(int(np.ceil(lo / major) * major), int(hi) + 1, major):
                d.line([(fx(fr), y0), (fx(fr), height)], fill=grid)
            if rx_hz and ftol:
                d.rectangle([fx(rx_hz - ftol), y0, fx(rx_hz + ftol), height - 1], fill=(18, 40, 26) if dark else (225, 245, 230))
                d.line([(fx(rx_hz), y0), (fx(rx_hz), height)], fill=(46, 160, 67))
            if rx_hz and spread_hz:                                      # where the sync tone is expected
                a_, b_ = fx(rx_hz - spread_hz / 2), fx(rx_hz + spread_hz / 2)
                d.rectangle([a_, y0 + 1, max(a_ + 1, b_), y0 + 5], fill=(46, 160, 67))
            self.trace = None
            if spec is not None and len(spec) > 10 and rx_hz and ftol:
                self.trace = find_trace(spec, f, rx_hz, ftol, spread_hz)
            if spec is not None and len(spec) > 10:
                k = int(max(9, min(61, (spread_hz or 20) / 2 / WF_DF))) | 1      # ~half the expected spread
                sm = np.convolve(np.pad(spec, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
                edges = np.linspace(0, len(sm), width + 1).astype(int)
                col = np.array([sm[edges[i]:max(edges[i] + 1, edges[i + 1])].mean() for i in range(width)])
                s_lo, s_hi = np.percentile(col, 2), np.max(col)
                s_hi = max(s_hi, s_lo + 3.0)                             # at least 3 dB tall: noise stays flat
                ys = y0 + 6 + (1 - (col - s_lo) / (s_hi - s_lo)) * (h_spec - 12)
                d.line(list(zip(range(width), np.clip(ys, y0 + 2, height - 2).tolist())), fill=(245, 197, 66), width=2)
            if self.trace:
                tx = fx(self.trace[0])
                d.polygon([(tx - 6, y0 + 3), (tx + 6, y0 + 3), (tx, y0 + 12)], fill=(255, 120, 60))
                d.text((min(width - 70, tx + 8), y0 + 3), f"+{self.trace[1]:.1f} dB", fill=(255, 160, 110))
            d.text((6, y0 + 3), "AVG", fill=axis)
        return np.asarray(img)


def find_trace(spec: np.ndarray, f: np.ndarray, rx_hz: float, ftol: float, spread_hz: float | None = None):
    """A likely EME signal in the cumulative spectrum: the strongest bump in Rx ± F Tol, smoothed over the expected
    spread (the sync tone is that wide), clearly above the noise of the rest of the view. (Hz, dB) or None."""
    df = float(np.median(np.diff(f))) if len(f) > 1 else WF_DF
    k = int(max(3, min(301, (spread_hz or 20) / df))) | 1
    sm = np.convolve(np.pad(spec, k // 2, mode="edge"), np.ones(k) / k, mode="valid")
    inside = (f >= rx_hz - ftol) & (f <= rx_hz + ftol)
    if inside.sum() < 3 or (~inside).sum() < 3 * k:
        return None
    out = sm[~inside]
    noise = np.median(out)
    sigma = 1.4826 * np.median(np.abs(out - noise)) + 1e-6
    i = int(np.argmax(np.where(inside, sm, -np.inf)))
    excess = float(sm[i] - noise)
    return (float(f[i]), excess) if excess > max(0.3, 4 * sigma) else None


def _cmap(u: np.ndarray, palette: str = "wsjtx") -> np.ndarray:
    """Colour of each level 0…1 with one of the PALETTES (default: dark blue → cyan → yellow → white, readable weak
    traces as with the WSJT-X default palette)."""
    stops = np.array(PALETTES.get(palette, PALETTES["wsjtx"]))
    out = np.empty(u.shape + (3,), dtype=np.float32)
    for c in range(3):
        out[..., c] = np.interp(u, stops[:, 0], stops[:, c + 1])
    return out


# ------------------------------------------------------------------ the engine
@dataclass
class Period:
    utc: datetime
    tr: int
    wav: Path
    params: dict
    knobs: Knobs
    spread_hz: float | None
    lab: dict = field(default_factory=dict)
    ref: dict = field(default_factory=dict)
    skipped: str | None = None


def merge(lab: list[dict], ref: list[dict], wsjtx: list[dict] | None = None) -> list[dict]:
    """One row per message: who decoded it (Q65 Lab, «come WSJT-X» on the same audio, WSJT-X itself) and the
    best values; «only_lab» when Q65 Lab is the only one."""
    rows: dict[str, dict] = {}
    for src, ds in (("lab", lab), ("ref", ref), ("wsjtx", wsjtx or [])):
        for d in ds:
            m = " ".join(str(d.get("message", "")).split())
            if not m:
                continue
            r = rows.setdefault(m, {"message": m, "snr": d.get("snr"), "dt": d.get("dt"), "freq": d.get("freq"),
                                    "q": d.get("q"), "nused": d.get("nused"), "lab": False, "ref": False, "wsjtx": False})
            r[src] = True
            if src == "lab":
                r.update(snr=d.get("snr"), dt=d.get("dt"), freq=d.get("freq"), q=d.get("q"), nused=d.get("nused"))
    out = list(rows.values())
    for r in out:
        r["only_lab"] = r["lab"] and not r["ref"] and not r["wsjtx"]
        r["only_ref"] = not r["lab"] and (r["ref"] or r["wsjtx"])
    return sorted(out, key=lambda r: (r["freq"] or 0))


class Engine:
    """Listens, cuts the T/R periods, decodes each one with the two profiles. One per EMELab (see ui_q65lab)."""

    def __init__(self, exe: Path | str | None = None, folder: Path | None = None):
        self.exe = Path(exe) if exe else find_decoder()
        self.folder = folder or work_dir()
        (self.folder / "rx").mkdir(parents=True, exist_ok=True)
        self.source: Capture | None = None
        self.periods = deque(maxlen=200)       # newest last
        self.waterfall = Waterfall()
        self.errors = deque(maxlen=20)
        self.params_fn = None                  # () → dict of the current parameters (see current_params)
        self.mode = "auto"                     # auto | wsjtx | wide  (Q65 Lab profile)
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._dec_lab = self._dec_ref = None
        self._tx_seen: set[int] = set()        # periods (epoch // tr) in which WSJT-X was transmitting
        self._last_dx = None
        self.busy = False
        self.started = None

    # ------------------------------------------------ control
    @property
    def running(self) -> bool:
        return self.source is not None and not self._stop.is_set()

    def start(self, source: Capture):
        self.stop()
        self._stop = threading.Event()
        self.source = source.start()
        self.started = time.time()
        for fn, name in ((self._scheduler, "q65lab-periods"), (self._worker, "q65lab-decode"),
                         (self._wf_loop, "q65lab-waterfall")):
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def stop(self):
        self._stop.set()
        if self.source:
            self.source.stop()
        self.source = None
        self._threads = []

    def decoders(self):
        if not self.exe:
            raise FileNotFoundError("q65lab non trovato")
        if self._dec_lab is None:
            self._dec_lab = Decoder(self.exe, self.folder / "lab")
            self._dec_ref = Decoder(self.exe, self.folder / "ref", WSJTX_KNOBS)
        return self._dec_lab, self._dec_ref

    def clear_avg(self):
        for d in (self._dec_lab, self._dec_ref):
            if d:
                try:
                    d.clear()
                except Exception as e:
                    self.errors.append(f"clear: {e}")

    def note_status(self, status: dict):
        """WSJT-X Status: remembers the periods in which it transmits (they are not decoded)."""
        if status.get("transmitting"):
            tr = int(status.get("tr_period") or 60) or 60
            self._tx_seen.add(int(time.time() // tr))

    # ------------------------------------------------ threads
    def _wf_loop(self):
        while not self._stop.wait(self.waterfall.step):
            try:
                x = self.source.latest(self.waterfall.nfft * 2.5 / FS) if self.source else None
                self.waterfall.add(x, time.time())
            except Exception as e:
                self.errors.append(f"waterfall: {e}")

    def _scheduler(self):
        last = None
        while not self._stop.wait(0.25):
            p = self.current_params()
            tr = p["tr"]
            now = time.time()
            k = int(now // tr)
            if last is None:
                last = k                               # the period under way is incomplete: start with the next one
                continue
            if k == last or now - k * tr < 0.5:        # 0.5 s of margin for the sound card buffers
                continue
            prev = last
            last = k
            t0 = prev * tr
            utc = datetime.fromtimestamp(t0, timezone.utc)
            if prev in self._tx_seen:
                self.periods.append(Period(utc, tr, Path(), p, WSJTX_KNOBS, p.get("spread_hz"), skipped="tx"))
                continue
            x = self.source.take(t0, tr) if self.source else None
            if x is None:
                continue
            wav = self.folder / "rx" / utc.strftime("%y%m%d_%H%M%S.wav")
            write_wav(wav, x)
            self._prune()
            self._q.put((utc, tr, wav, p))

    def _prune(self):
        try:
            fs = sorted((self.folder / "rx").glob("*.wav"))
            for f in fs[:-KEEP_PERIODS]:
                f.unlink(missing_ok=True)
        except OSError:
            pass

    def _worker(self):
        while not self._stop.is_set():
            try:
                utc, tr, wav, p = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.periods.append(self.decode_period(utc, tr, wav, p))
            except Exception as e:
                self.errors.append(f"{utc:%H:%M}: {e}")

    # ------------------------------------------------ decoding
    def knobs_for(self, spread_hz: float | None) -> Knobs:
        if self.mode == "wsjtx":
            return Knobs(1, 100, LINEAR)
        if self.mode == "wide":
            return Knobs(0, 300, LINEAR)
        return lab_knobs(spread_hz)

    def decode_period(self, utc: datetime, tr: int, wav: Path, p: dict) -> Period:
        lab, ref = self.decoders()
        dx = (p.get("dx_call") or "").upper()
        key = (dx, p.get("band"), p.get("submode"), tr, int(p.get("rx_hz") or 0) // 50)
        if key != self._last_dx and self._last_dx is not None:
            self.clear_avg()                            # another station, band, mode or Rx: the averages start again
        self._last_dx = key
        k = self.knobs_for(p.get("spread_hz"))
        lab.set_knobs(k)
        kw = dict(utc=utc, tr=tr, submode=p["submode"], rx_hz=p["rx_hz"], ftol=p["ftol"], depth=p["depth"],
                  mycall=p.get("my_call", ""), dxcall=dx, dxgrid=p.get("dx_grid", ""), max_drift=p.get("max_drift", 0),
                  eme_delay=p.get("eme_delay", True))
        self.busy = True
        try:
            r_lab = lab.decode(wav, **kw)
            r_ref = ref.decode(wav, **kw)
        finally:
            self.busy = False
        return Period(utc, tr, wav, p, k, p.get("spread_hz"), lab=r_lab, ref=r_ref)

    def current_params(self) -> dict:
        p = DEFAULT_PARAMS.copy()
        if self.params_fn:
            try:
                p.update({k: v for k, v in (self.params_fn() or {}).items() if v not in (None, "")})
            except Exception as e:
                self.errors.append(f"parametri: {e}")
        if p["tr"] not in TR_OK:
            p["tr"] = 60
        if p["submode"] not in SUBMODES:
            p["submode"] = "D"
        return p


DEFAULT_PARAMS = {"tr": 60, "submode": "D", "rx_hz": 1000, "ftol": 100, "depth": 3 | 16, "my_call": "", "dx_call": "",
                  "dx_grid": "", "max_drift": 0, "eme_delay": True, "spread_hz": None, "band": None}


def params_from(status: dict | None, ini: dict | None, station: dict | None = None, now: datetime | None = None,
                dx_locator: str | None = None) -> dict:
    """Decoding parameters from the WSJT-X UDP status and WSJT-X.ini (EMELab reads, never writes), with the expected
    libration spread on the path to the DX (own echo when there is no DX locator)."""
    s, ini = status or {}, ini or {}
    p = {}
    mode = (s.get("mode") or "").upper()
    sub = (s.get("submode") or "").strip().upper()
    if sub and sub[0] in SUBMODES:
        p["submode"] = sub[0]
    if s.get("tr_period"):
        p["tr"] = int(s["tr_period"])
    if s.get("rx_df"):
        p["rx_hz"] = int(s["rx_df"])
    if s.get("freq_tolerance") and s["freq_tolerance"] < 10000:
        p["ftol"] = int(s["freq_tolerance"])
    p["my_call"] = s.get("de_call") or (station or {}).get("callsign") or ""
    p["dx_call"] = s.get("dx_call") or ""
    p["dx_grid"] = s.get("dx_grid") or ""
    depth = {"Fast": 1, "Normal": 2, "Deep": 3}.get(ini.get("depth") or "Deep", 3)
    if ini.get("averaging") is not False:
        depth |= 16
    if ini.get("auto_clear_avg"):
        depth |= 128
    p["depth"] = depth
    if ini.get("max_drift") is not None:
        p["max_drift"] = int(ini["max_drift"])
    if ini.get("decode52") is not None:
        p["eme_delay"] = bool(ini["decode52"])
    p["mode_ok"] = mode.startswith("Q65") or not mode
    hz = s.get("dial_hz")
    if hz:
        from emelab import stations
        p["band"] = stations.band_of(hz / 1e6)
        p["spread_hz"] = expected_spread(hz / 1e9, station, dx_locator or p["dx_grid"], now)
    return p


def expected_spread(f_ghz: float, station: dict | None, dx_locator: str | None, now: datetime | None = None) -> float | None:
    """Libration spread (Hz, limb to limb) at f_ghz on the path station → Moon → DX (own echo without a DX locator)."""
    st = station or {}
    try:
        from emelab import astro
        if st.get("lat") is not None and st.get("lon") is not None:
            a = (float(st["lat"]), float(st["lon"]))
        elif st.get("locator"):
            a = astro.locator_to_latlon(st["locator"])
        else:
            return None
        b = astro.locator_to_latlon(dx_locator) if dx_locator and len(dx_locator) >= 4 else a
        m = astro.mutual(now or datetime.now(timezone.utc), a, b, float(st.get("height_m") or 0.0))
        return float(m["spread_hz_per_ghz"]) * f_ghz
    except Exception:
        return None


def decode_files(files: list[Path], params: dict, exe: Path | None = None, knobs: Knobs | None = None,
                 folder: Path | None = None, progress=None, alltxt_rows: list[dict] | None = None,
                 auto: bool = False) -> list[dict]:
    """Saved periods decoded in time order with both profiles (fresh averages): one dict per file
    {"name", "utc", "params", "lab", "ref", "rows"}; with ALL.TXT, the decodes of WSJT-X itself are compared too and,
    with «auto», each file gets the mode, Rx and DX WSJT-X had at that time (averages restart when they change)."""
    exe = exe or find_decoder()
    if not exe:
        raise FileNotFoundError("q65lab non trovato")
    files = [f for f in files if Path(f).is_file()]          # skip the ones deleted meanwhile (Q65 Lab keeps its last)
    if not files:
        return []
    folder = folder or (work_dir() / "files")
    lab = Decoder(exe, folder / "lab", knobs or lab_knobs(params.get("spread_hz")))
    ref = Decoder(exe, folder / "ref", WSJTX_KNOBS)
    out = []
    try:
        files = sorted(files, key=lambda f: (file_time(f), str(f)))
        last = None
        for i, f in enumerate(files):
            f = Path(f)
            utc = file_time(f)
            pp = params | (guess_params(alltxt_rows or [], utc) if auto else {})
            key = (pp["tr"], pp["submode"], pp["rx_hz"], pp.get("dx_call", ""))
            if last is not None and key != last:
                lab.clear()
                ref.clear()
            last = key
            w = ensure_12k(f, folder)
            kw = dict(utc=utc, tr=pp["tr"], submode=pp["submode"], rx_hz=pp["rx_hz"], ftol=pp["ftol"],
                      depth=pp["depth"], mycall=pp.get("my_call", ""), dxcall=pp.get("dx_call", ""),
                      dxgrid=pp.get("dx_grid", ""), max_drift=pp.get("max_drift", 0),
                      eme_delay=pp.get("eme_delay", True))
            a, b = lab.decode(w, **kw), ref.decode(w, **kw)
            wj = wsjtx_decodes_at(alltxt_rows, utc, pp["tr"]) if alltxt_rows else None
            out.append({"name": f.name, "utc": utc, "params": pp, "knobs": lab.knobs, "lab": a, "ref": b,
                        "rows": merge(a["decodes"], b["decodes"], wj)})
            if progress:
                progress(i + 1, len(files))
    finally:
        lab.close()
        ref.close()
    return out

