# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""📷 Astronomical camera: live Moon image from a ZWO ASI USB camera, Moon centre detection and tracking alarm.

The camera is only read (video mode, through ZWO's own ASICamera2 library and the `zwoasi` binding): EMELab never
moves anything. Without the library or the camera EMELab says why and offers the simulator, so the tab never breaks.
Only one program at a time can open an ASI camera: close ASICap (or SharpCap, FireCapture…) before starting here."""
from __future__ import annotations

import glob
import io
import math
import os
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

DLL = "ASICamera2.dll" if os.name == "nt" else "libASICamera2.so"
MOON_DIAM_DEG = 0.518                    # mean apparent diameter, used when the optics are unknown
# Ivan's camera and lens: ZWO ASI120MM Mini (3.75 µm) + ZWO 30F4 mini guide scope (f = 120 mm)
DEFAULT_PIXEL_UM = 3.75
DEFAULT_FOCAL_MM = 120.0


# ------------------------------------------------------------------ ZWO library
def dll_candidates(user_path: str = "") -> list[str]:
    """Where ASICamera2.dll may be: the path chosen by the user, ZWO_ASI_LIB, EMELab's own folder, the folders of
    ASICap / ASIStudio / SharpCap / FireCapture / N.I.N.A. (they all ship the 64-bit library)."""
    out = []
    for p in (user_path, os.environ.get("ZWO_ASI_LIB", "")):
        if p:
            out.append(str(Path(p) / DLL) if Path(p).is_dir() else p)
    here = Path(__file__).resolve().parent
    out += [str(here / DLL), str(here.parent / DLL), str(here.parent.parent / DLL)]
    if os.name == "nt":
        roots = [os.environ.get(k, "") for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA")]
        for r in filter(None, dict.fromkeys(roots)):
            for pat in ("*ASI*", "*ZWO*", "SharpCap*", "FireCapture*", "N.I.N.A*", "Programs\\*ASI*"):
                for d in glob.glob(os.path.join(r, pat)):
                    out += glob.glob(os.path.join(d, DLL)) + glob.glob(os.path.join(d, "*", DLL)) \
                        + glob.glob(os.path.join(d, "*", "x64", DLL))
    return [p for p in dict.fromkeys(out) if p and os.path.isfile(p)]


_LIB = {"path": None, "error": None}


def load_library(user_path: str = "") -> dict:
    """Load the ZWO library once. Returns {"ok", "path", "error"} (error in Italian, for the interface)."""
    if _LIB["path"]:
        return {"ok": True, "path": _LIB["path"], "error": None}
    try:
        import zwoasi as asi
    except Exception:
        return {"ok": False, "path": None, "error": "manca il pacchetto Python «zwoasi»"}
    tried = dll_candidates(user_path)
    if not tried:
        from ctypes.util import find_library
        lib = find_library("ASICamera2")
        tried = [lib] if lib else []
    if not tried:
        return {"ok": False, "path": None,
                "error": "libreria ZWO ASICamera2.dll non trovata (installa ASICap o ASIStudio, o indica dove si trova)"}
    last = ""
    for p in tried:
        try:
            asi.init(p)
            _LIB.update(path=p, error=None)
            return {"ok": True, "path": p, "error": None}
        except Exception as e:                       # e.g. a 32-bit DLL in a 64-bit Python
            last = f"{p}: {e}"
    _LIB["error"] = last
    return {"ok": False, "path": None, "error": "libreria ZWO trovata ma non caricabile" + f" ({last})"}


def list_cameras(user_path: str = "") -> tuple[list[dict], str | None]:
    """[{index, name, width, height, pixel_um, color, usb3}], error."""
    r = load_library(user_path)
    if not r["ok"]:
        return [], r["error"]
    import zwoasi as asi
    try:
        cams = []
        for i in range(asi.get_num_cameras()):
            p = asi._get_camera_property(i)
            cams.append({"index": i, "name": p["Name"], "width": p["MaxWidth"], "height": p["MaxHeight"],
                         "pixel_um": p["PixelSize"], "color": bool(p["IsColorCam"]), "usb3": bool(p["IsUSB3Camera"])})
        return cams, (None if cams else "nessuna telecamera ZWO collegata (controlla il cavo USB e chiudi ASICap)")
    except Exception as e:
        return [], f"errore della libreria ZWO: {e}"


# ------------------------------------------------------------------ frame sources
class _Source:
    """A camera running in its own thread; `latest()` gives the newest frame without waiting."""
    kind = "base"

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._t = 0.0
        self._stop = threading.Event()
        self.error = None
        self.info = {}
        self.history = deque(maxlen=3600)            # (time, dx_deg, dy_deg, found)
        self._th = threading.Thread(target=self._run, daemon=True, name=f"emelab-cam-{self.kind}")

    def start(self):
        self._th.start()
        return self

    def stop(self):
        self._stop.set()

    def latest(self):
        with self._lock:
            return self._frame, self._t

    def _put(self, frame):
        with self._lock:
            self._frame, self._t = frame, time.time()

    def set_controls(self, exposure_ms: float, gain: int, auto: bool):
        pass

    def _run(self):
        raise NotImplementedError


class AsiSource(_Source):
    kind = "asi"

    def __init__(self, index: int, exposure_ms: float = 5.0, gain: int = 0, binning: int = 1, auto: bool = False):
        super().__init__()
        self.index, self.binning = index, binning
        self._ctl = (exposure_ms, gain, auto)
        self._ctl_dirty = threading.Event()

    def set_controls(self, exposure_ms: float, gain: int, auto: bool):
        if (exposure_ms, gain, auto) != self._ctl:
            self._ctl = (exposure_ms, gain, auto)
            self._ctl_dirty.set()

    def _apply(self, cam, asi):
        exp, gain, auto = self._ctl
        cam.set_control_value(asi.ASI_GAIN, int(gain), auto=bool(auto))
        cam.set_control_value(asi.ASI_EXPOSURE, int(exp * 1000), auto=bool(auto))
        if auto:
            try:
                cam.set_control_value(asi.ASI_AUTO_MAX_EXP, 100)          # ms: the Moon is bright, keep the rate up
                cam.set_control_value(asi.ASI_AUTO_TARGET_BRIGHTNESS, 60)
            except Exception:
                pass

    def _run(self):
        import zwoasi as asi
        cam = None
        try:
            cam = asi.Camera(self.index)
            p = cam.get_camera_property()
            fmt = asi.ASI_IMG_Y8 if asi.ASI_IMG_Y8 in p["SupportedVideoFormat"] else asi.ASI_IMG_RAW8
            b = self.binning if self.binning in p["SupportedBins"] else 1
            cam.set_roi(bins=b, image_type=fmt)
            try:
                cam.set_control_value(asi.ASI_BANDWIDTHOVERLOAD,
                                      cam.get_controls()["BandWidth"]["MinValue"])   # steady frames on USB 2
            except Exception:
                pass
            self._apply(cam, asi)
            self.info = {"name": p["Name"], "pixel_um": p["PixelSize"], "bin": b, "color": bool(p["IsColorCam"]),
                         "width": p["MaxWidth"] // b, "height": p["MaxHeight"] // b}
            cam.start_video_capture()
            while not self._stop.is_set():
                if self._ctl_dirty.is_set():
                    self._ctl_dirty.clear()
                    self._apply(cam, asi)
                exp = self._ctl[0] if not self._ctl[2] else 100
                try:
                    img = cam.capture_video_frame(timeout=int(2 * exp + 500))
                    self._put(np.array(img, copy=True))
                    self.error = None
                except Exception as e:                # a missed frame (timeout): keep trying
                    self.error = str(e)
                    time.sleep(0.2)
        except Exception as e:
            self.error = f"impossibile aprire la telecamera: {e}"
        finally:
            if cam is not None:
                try:
                    cam.stop_video_capture()
                except Exception:
                    pass
                try:
                    cam.close()
                except Exception:
                    pass


class SimSource(_Source):
    """Synthetic Moon (ASI120MM Mini + 30F4 size, ~290 px across) that drifts slowly: to try the tab without camera."""
    kind = "sim"

    def __init__(self, width: int = 640, height: int = 480, phase: float = 0.8, drift_px_s: float = 1.5):
        super().__init__()
        self.w, self.h, self.phase, self.drift = width, height, phase, drift_px_s
        self.info = {"name": "Simulatore", "pixel_um": DEFAULT_PIXEL_UM * 2, "bin": 1, "color": False,
                     "width": width, "height": height}

    def frame_at(self, t: float) -> np.ndarray:
        r = 145 * self.w / 1280 * 2
        cx = self.w / 2 + 40 * math.sin(t / 25) + self.drift * (t % 120) - self.drift * 60
        cy = self.h / 2 + 25 * math.sin(t / 37)
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        disk = d2 <= r * r
        # terminator: ellipse cutting the disc (phase 1 = full Moon)
        k = 2 * self.phase - 1
        lit = disk & ((xx - cx) >= -k * np.sqrt(np.clip(r * r - (yy - cy) ** 2, 0, None)))
        img = np.random.default_rng(int(t * 10)).normal(12, 3, (self.h, self.w))
        img[lit] = 190 + 25 * np.sin(xx[lit] / 9) * np.cos(yy[lit] / 13)
        return np.clip(img, 0, 255).astype(np.uint8)

    def _run(self):
        t0 = time.time()
        while not self._stop.is_set():
            self._put(self.frame_at(time.time() - t0))
            time.sleep(0.25)


class StillSource(_Source):
    """One picture loaded from a file (to try the detection on a real Moon image)."""
    kind = "still"

    def __init__(self, data: bytes):
        super().__init__()
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("L")
        self.info = {"name": "Immagine", "pixel_um": DEFAULT_PIXEL_UM, "bin": 1, "color": False,
                     "width": im.width, "height": im.height}
        self._put(np.asarray(im))

    def start(self):
        return self

    def _run(self):
        pass


# one camera for the whole program (Streamlit reruns the script; the thread must survive)
_CUR: dict = {"src": None, "key": None}
_CUR_LOCK = threading.Lock()


def current():
    return _CUR["src"]


def ensure(key: tuple, factory):
    """Start the source described by `key` (stopping another one); the same key keeps the running source."""
    with _CUR_LOCK:
        if _CUR["key"] == key and _CUR["src"] is not None:
            return _CUR["src"]
        if _CUR["src"] is not None:
            _CUR["src"].stop()
            time.sleep(0.3)                          # let the old thread close the camera before reopening it
        _CUR["src"] = factory().start()
        _CUR["key"] = key
        return _CUR["src"]


def stop():
    with _CUR_LOCK:
        if _CUR["src"] is not None:
            _CUR["src"].stop()
        _CUR.update(src=None, key=None)


# ------------------------------------------------------------------ detection
def _gray(frame: np.ndarray) -> np.ndarray:
    a = np.asarray(frame)
    if a.ndim == 3:
        a = a[..., :3].mean(axis=2)
    a = a.astype(np.float32)
    if a.max() > 255:                                # RAW16
        a = a * (255.0 / max(float(a.max()), 1.0))
    return a


def _otsu(a: np.ndarray) -> float:
    h, edges = np.histogram(a, bins=256, range=(0, 256))
    p = h / max(h.sum(), 1)
    w = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        s = (mu[-1] * w - mu) ** 2 / (w * (1 - w))
    return float(np.nanargmax(s))


def detect(frame: np.ndarray, min_contrast: float = 40.0) -> dict | None:
    """Moon in the frame: {cx, cy (pixels of the frame), r (radius in pixels), area, threshold} or None.

    Bright-blob detection: Otsu threshold, the largest bright region (hot pixels, lights and thin clouds are left out),
    its centroid. The radius comes from the longest side of the region, which is the Moon's diameter at any phase.
    With a partial Moon the centroid sits on the lit side: «use the current position as centre» takes that into account."""
    a = _gray(frame)
    h, w = a.shape
    step = max(1, int(max(h, w) // 480))             # work on ≤ ~480 px: fast at any resolution
    s = a[::step, ::step]
    lo, hi = float(np.percentile(s, 5)), float(np.percentile(s, 99.9))
    if hi - lo < min_contrast:
        return None
    thr = max(_otsu(s), lo + 0.3 * (hi - lo))
    mask = s > thr
    if not mask.any():
        return None
    try:
        from scipy import ndimage
        lab, n = ndimage.label(mask)
        if n > 1:
            sizes = ndimage.sum(mask, lab, range(1, n + 1))
            mask = lab == (int(np.argmax(sizes)) + 1)
    except Exception:
        pass
    area = int(mask.sum())
    if area < 20 or area > 0.8 * mask.size:
        return None
    ys, xs = np.nonzero(mask)
    cx, cy = (xs.mean() + 0.5) * step - 0.5, (ys.mean() + 0.5) * step - 0.5
    r = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) * step / 2
    return {"cx": float(cx), "cy": float(cy), "r": float(r), "area": area * step * step, "threshold": thr,
            "width": w, "height": h}


def deg_per_px(pixel_um: float, binning: int, focal_mm: float) -> float:
    """Plate scale from the optics: pixel size × binning / focal length."""
    return math.degrees(pixel_um * binning * 1e-3 / focal_mm) if focal_mm > 0 and pixel_um > 0 else 0.0


def deg_per_px_from_moon(r_px: float, moon_diam_deg: float = MOON_DIAM_DEG) -> float:
    return moon_diam_deg / (2 * r_px) if r_px > 0 else 0.0


def offset(det: dict, ref: tuple[float, float], scale: float, flip_x: bool = False, flip_y: bool = False) -> dict:
    """Offset of the Moon from the reference point. Positive az: the Moon is to the right (antenna must turn right,
    azimuth up); positive el: the Moon is higher (antenna must go up). Assumes the camera is mounted upright;
    the flips cover a mirrored or upside-down camera."""
    dx = det["cx"] - ref[0]
    dy = ref[1] - det["cy"]                          # image rows grow downwards
    if flip_x:
        dx = -dx
    if flip_y:
        dy = -dy
    return {"dx_px": dx, "dy_px": dy, "az_deg": dx * scale, "el_deg": dy * scale,
            "total_deg": math.hypot(dx, dy) * scale, "total_px": math.hypot(dx, dy)}


def pointing_loss_db(off_deg: float, hpbw_deg: float) -> float:
    """Loss of a Gaussian beam pointed off_deg away: 12 (θ/θ₃dB)² dB, one way (twice for the echo)."""
    return 12.0 * (off_deg / hpbw_deg) ** 2 if hpbw_deg > 0 else 0.0


class Alarm:
    """Out of tracking only after `hold_s` seconds over tolerance (no alarms from a single noisy frame);
    the Moon lost from the image for `hold_s` seconds also raises it."""

    def __init__(self):
        self.since = None
        self.active = False
        self.reason = ""

    def update(self, now: float, total_deg: float | None, tol_deg: float, hold_s: float) -> bool:
        """Returns True only when the alarm starts (to beep once)."""
        bad = total_deg is None or total_deg > tol_deg
        if not bad:
            self.since, self.active, self.reason = None, False, ""
            return False
        if self.since is None:
            self.since = now
        self.reason = "lost" if total_deg is None else "out"
        if not self.active and now - self.since >= hold_s:
            self.active = True
            return True
        return False


# ------------------------------------------------------------------ drawing
GRID_COLOR = (80, 200, 255)
OK_COLOR, BAD_COLOR = (60, 220, 90), (255, 60, 60)


def overlay(frame: np.ndarray, det: dict | None, ref: tuple[float, float], tol_px: float, grid_px: float,
            alarm: bool, max_w: int = 960, stretch: bool = True):
    """The frame with the grid, the reference centre, the tolerance circle and the detected Moon; a PIL image."""
    from PIL import Image, ImageDraw
    a = _gray(frame)
    if stretch:
        lo, hi = np.percentile(a[::4, ::4], (1, 99.8))
        a = (a - lo) * (255.0 / max(hi - lo, 1.0))
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGB")
    k = min(1.0, max_w / im.width)
    if k < 1:
        im = im.resize((int(im.width * k), int(im.height * k)))
    d = ImageDraw.Draw(im)
    W, H = im.size
    rx, ry = ref[0] * k, ref[1] * k
    g = grid_px * k
    if g >= 8:
        i = 1
        while rx - i * g > 0 or rx + i * g < W or ry - i * g > 0 or ry + i * g < H:
            for x in (rx - i * g, rx + i * g):
                d.line([(x, 0), (x, H)], fill=GRID_COLOR, width=1)
            for y in (ry - i * g, ry + i * g):
                d.line([(0, y), (W, y)], fill=GRID_COLOR, width=1)
            i += 1
    d.line([(rx, 0), (rx, H)], fill=GRID_COLOR, width=2)
    d.line([(0, ry), (W, ry)], fill=GRID_COLOR, width=2)
    col = BAD_COLOR if alarm else OK_COLOR
    t = tol_px * k
    d.ellipse([rx - t, ry - t, rx + t, ry + t], outline=col, width=3)
    if det:
        cx, cy, r = det["cx"] * k, det["cy"] * k, det["r"] * k
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 200, 0), width=2)
        d.line([(cx - 12, cy), (cx + 12, cy)], fill=(255, 200, 0), width=3)
        d.line([(cx, cy - 12), (cx, cy + 12)], fill=(255, 200, 0), width=3)
        d.line([(rx, ry), (cx, cy)], fill=col, width=2)
    if alarm:
        d.rectangle([0, 0, W - 1, H - 1], outline=BAD_COLOR, width=8)
    return im


def beep_wav(freq: float = 1000.0, seconds: float = 0.6, rate: int = 16000) -> bytes:
    """Three short beeps as a WAV file (alarm sound for st.audio)."""
    import wave
    t = np.arange(int(seconds * rate)) / rate
    env = ((t * 5) % 1 < 0.6).astype(float)
    y = (0.6 * env * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(y.tobytes())
    return buf.getvalue()
