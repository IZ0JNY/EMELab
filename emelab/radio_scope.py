# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Spectrum scope and waterfall of the 📟 Radio tab, from the IC-9700's receive audio (USB Audio CODEC).

The audio card is shared with WSJT-X (as in Q65 Lab), so the scope works while WSJT-X keeps the CAT port: it shows the
receiver's passband (0–3 kHz above the dial frequency in USB), the part that matters for EME. The radio's own RF scope
(CI-V command 27h) needs the CI-V stream on the USB port, which WSJT-X and rigctld hold."""
from __future__ import annotations

import base64
import io
import threading
import time

import numpy as np

F_MAX = 3000.0          # Hz shown (USB passband)
POINTS = 300            # spectrum points across the scope
WF_ROWS = 90            # waterfall history (rows)
ROW_S = 0.5             # one waterfall row every 0.5 s
REF_DB = -100.0         # bottom of the 60 dB scale before the noise floor is known

_lock = threading.Lock()
_SCOPE: "AudioScope | None" = None


def spectrum(x: np.ndarray, fs: int = 12000, f_max: float = F_MAX, points: int = POINTS) -> np.ndarray:
    """Power spectrum in dB of the samples, averaged into «points» bins from 0 to f_max."""
    if x is None or len(x) < 256:
        return np.full(points, np.nan)
    n = 1 << int(np.floor(np.log2(len(x))))
    x = x[-n:] * np.hanning(n)
    p = np.abs(np.fft.rfft(x)) ** 2 / n
    f = np.fft.rfftfreq(n, 1 / fs)
    edges = np.linspace(0, f_max, points + 1)
    idx = np.clip(np.searchsorted(f, edges), 0, len(p) - 1)
    out = np.array([p[a:max(b, a + 1)].mean() for a, b in zip(idx[:-1], idx[1:])])
    return 10 * np.log10(np.maximum(out, 1e-14))


class AudioScope:
    """Keeps the capture running and builds one waterfall row every ROW_S seconds."""

    def __init__(self, device: int | None, channel: str = "Mono", rate: int = 48000):
        from emelab import q65lab
        self.cap = q65lab.Capture(device, channel, rate, seconds=20.0)
        self.rows: list[np.ndarray] = []
        self.last = None
        self.device = device
        self.error = None
        self._t = 0.0

    def start(self):
        try:
            self.cap.start()
        except Exception as e:
            self.error = str(e)
        return self

    def stop(self):
        self.cap.stop()

    def update(self) -> None:
        now = time.time()
        n_new = int((now - self._t) / ROW_S) if self._t else 1
        if n_new <= 0:
            return
        n_new = min(n_new, 8)
        for k in range(n_new, 0, -1):
            x = self.cap.latest(ROW_S * k)
            if x is None:
                return
            row = spectrum(x[: int(12000 * ROW_S)])
            self.rows.append(row)
        self.rows = self.rows[-WF_ROWS:]
        self.last = self.rows[-1]
        self._t = now

    def frame(self) -> dict:
        self.update()
        return {"spec": self.last, "rows": list(self.rows), "f0": 0.0, "f1": F_MAX, "label": "AUDIO",
                "error": self.error or self.cap.error, "level_db": self.cap.level_db}


def get(device: int | None, channel: str = "Mono", rate: int = 48000) -> AudioScope:
    """The running scope for this device (started on first use, restarted if the device changes)."""
    global _SCOPE
    with _lock:
        if _SCOPE is None or _SCOPE.device != device:
            if _SCOPE is not None:
                _SCOPE.stop()
            _SCOPE = AudioScope(device, channel, rate).start()
        return _SCOPE


def stop():
    global _SCOPE
    with _lock:
        if _SCOPE is not None:
            _SCOPE.stop()
        _SCOPE = None


# ------------------------------------------------------------------ drawing
def scale(rows: list[np.ndarray], span_db: float = 50.0) -> tuple[float, float]:
    """(bottom, top) in dB: the noise floor one tenth above the bottom, as the radio's auto scale."""
    vals = np.concatenate([r[np.isfinite(r)] for r in rows]) if rows else np.array([])
    if not len(vals):
        return REF_DB, REF_DB + span_db
    floor = float(np.percentile(vals, 30))
    lo = floor - span_db * 0.1
    return lo, lo + span_db


def waterfall_png(rows: list[np.ndarray], lo: float, hi: float, height: int = WF_ROWS) -> str:
    """Base64 PNG of the waterfall (newest row on top), blue → cyan → yellow as on the radio."""
    from PIL import Image
    w = len(rows[0]) if rows else 300
    img = np.zeros((height, w), dtype=np.float32)
    for i, r in enumerate(reversed(rows[-height:])):
        img[i] = np.nan_to_num((r - lo) / (hi - lo), nan=0.0)
    u = np.clip(img, 0, 1)
    stops = np.array([[0.0, 0, 0, 70], [0.3, 10, 20, 150], [0.55, 40, 90, 255], [0.75, 120, 230, 255], [1.0, 255, 255, 255]])
    rgb = np.stack([np.interp(u, stops[:, 0], stops[:, c]) for c in (1, 2, 3)], axis=-1).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def spectrum_svg(spec: np.ndarray | None, lo: float, hi: float, w: int = 600, h: int = 100) -> str:
    """SVG path of the spectrum trace (filled), coordinates in a w×h box."""
    if spec is None or not np.isfinite(spec).any():
        return ""
    y = np.clip((np.nan_to_num(spec, nan=lo) - lo) / (hi - lo), 0, 1)
    xs = np.linspace(0, w, len(y))
    pts = " ".join(f"{x:.1f},{h - v * h:.1f}" for x, v in zip(xs, y))
    return f'<polyline points="{pts}" fill="none" stroke="#5cf06a" stroke-width="1.2"/>'


def demo_rows(seed: int = 1, n: int = WF_ROWS, traces: tuple = ((1000.0, 8.0, 14.0), (1650.0, 3.0, 9.0))) -> list[np.ndarray]:
    """Noise with a few EME-like traces (frequency Hz, width Hz, dB above noise): previews and tests."""
    rng = np.random.default_rng(seed)
    f = np.linspace(0, F_MAX, POINTS)
    rows = []
    for i in range(n):
        r = -112 + rng.normal(0, 1.6, POINTS) - 6 * np.exp(-(f / 180) ** 2) - 6 * np.exp(-((F_MAX - f) / 220) ** 2)
        for f0, bw, snr in traces:
            r = r + snr * np.exp(-((f - f0 - 3 * np.sin(i / 9)) / max(bw, 5)) ** 2) * (0.7 + 0.3 * rng.random())
        rows.append(r)
    return rows


def spectrum_png(spec: np.ndarray | None, lo: float, hi: float, w: int = 600, h: int = 110) -> str:
    """Base64 PNG of the spectrum: grid and green trace on black, as on the radio's scope."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(50, w, 100):
        d.line([(x, 0), (x, h)], fill=(58, 66, 80))
    for y in range(0, h, h // 5):
        d.line([(0, y), (w, y)], fill=(58, 66, 80))
    if spec is not None and np.isfinite(spec).any():
        y = np.clip((np.nan_to_num(spec, nan=lo) - lo) / (hi - lo), 0, 1)
        xs = np.linspace(0, w - 1, len(y))
        d.line([(float(x), float((h - 1) * (1 - v))) for x, v in zip(xs, y)], fill=(92, 240, 106), width=1)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()
