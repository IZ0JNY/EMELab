"""Quick hardware check of the ZWO ASI camera for the 📷 Telecamera Astronomica tab (read-only capture).

    python tools/asi_check.py [percorso\\ASICamera2.dll]

Finds the ZWO library, lists the cameras, grabs a few video frames (5 ms, gain 0, bin 2), detects the Moon (or the
brightest object) and saves asi_check.png with the grid next to this script's working folder."""
import os
import sys
import time
from pathlib import Path

# the embedded Python of EMELab ignores PYTHONPATH (._pth file): put this repository first, plus EMELAB_EXTRA_PATH
sys.path[:0] = [str(Path(__file__).resolve().parents[1])] + [p for p in os.environ.get("EMELAB_EXTRA_PATH", "").split(os.pathsep) if p]
from emelab import moontrack as mt

dll = sys.argv[1] if len(sys.argv) > 1 else ""
print("candidates:", mt.dll_candidates(dll))
print("library:", mt.load_library(dll))
cams, err = mt.list_cameras(dll)
print("cameras:", cams, err or "")
if not cams:
    sys.exit(1)
src = mt.AsiSource(cams[0]["index"], exposure_ms=float(sys.argv[2]) if len(sys.argv) > 2 else 5.0, gain=0, binning=2).start()
t0 = time.time()
n, last = 0, 0.0
while time.time() - t0 < 6:
    f, t = src.latest()
    if f is not None and t != last:
        n, last = n + 1, t
    time.sleep(0.05)
f, _ = src.latest()
src.stop()
print("info:", src.info, "frames in 6 s:", n, "error:", src.error)
if f is None:
    sys.exit(2)
print("frame:", f.shape, f.dtype, "min/mean/max", int(f.min()), round(float(f.mean()), 1), int(f.max()))
det = mt.detect(f)
print("detection:", det)
h, w = f.shape[:2]
scale = mt.deg_per_px(src.info["pixel_um"], src.info["bin"], mt.DEFAULT_FOCAL_MM)
mt.overlay(f, det, ((w - 1) / 2, (h - 1) / 2), 0.1 / scale, 0.1 / scale, False).save("asi_check.png")
print("saved asi_check.png; scale", round(scale * 3600, 2), "arcsec/px")
