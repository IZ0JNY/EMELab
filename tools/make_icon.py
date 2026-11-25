# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Draw EMELab's icon — a full Moon with its maria and, in front of it, a dish (drawn like FeedLab's) pointing at
it — and write docs/emelab.ico (PNG-compressed ICO, 16…256 px) and docs/emelab_256.png.  python tools/make_icon.py
Every size is drawn at 1024 px and reduced, so the small ones stay smooth."""
import io
import struct
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, Polygon  # noqa: E402
from PIL import Image  # noqa: E402

MARIA = [(-0.36, 0.30, 0.30, 0.22, 15), (0.05, 0.43, 0.20, 0.16, 0), (0.27, 0.12, 0.24, 0.19, -10),
         (0.63, 0.30, 0.13, 0.11, 0), (0.48, -0.22, 0.12, 0.20, 20), (-0.62, -0.05, 0.24, 0.44, 10),
         (-0.15, -0.38, 0.21, 0.13, 0), (0.10, -0.05, 0.09, 0.07, 0)]


def _render(detail: bool) -> Image.Image:
    S = 1024
    fig = plt.figure(figsize=(1, 1), dpi=S)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_alpha(0)
    box = FancyBboxPatch((0.03, 0.03), 0.94, 0.94, boxstyle="round,pad=0,rounding_size=0.19", fc="none", ec="none")
    ax.add_patch(box)
    yy = np.linspace(1, 0, 256)[:, None] * np.ones((1, 4))
    sky = ax.imshow(yy, extent=(0, 1, 0, 1), cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
        "s", ["#1d2f63", "#0a1130"]), vmin=0, vmax=1, interpolation="bicubic", zorder=0)
    sky.set_clip_path(box)
    if detail:
        rng = np.random.default_rng(7)
        for _ in range(14):
            x, y = rng.uniform(0.08, 0.92, 2)
            if (x - 0.62) ** 2 + (y - 0.64) ** 2 > 0.36 ** 2 and y > 0.30:
                ax.add_patch(Circle((x, y), rng.uniform(0.003, 0.007), fc="#dfe6ff", ec="none", alpha=0.9, zorder=1))
    cx, cy, R = 0.615, 0.635, 0.275                              # the Moon
    for k, a in ((1.22, 0.06), (1.12, 0.10), (1.05, 0.16)):      # soft glow
        ax.add_patch(Circle((cx, cy), R * k, fc="#fff4d6", ec="none", alpha=a, zorder=2))
    disc = Circle((cx, cy), R, fc="none", ec="none", zorder=3); ax.add_patch(disc)
    g = np.linspace(-1, 1, 400)
    X, Y = np.meshgrid(g, g[::-1])
    mu = np.sqrt(np.clip(1 - X ** 2 - Y ** 2, 0, 1))
    shade = 0.80 + 0.20 * mu ** 0.5 - 0.06 * (X + Y)            # limb darkening, lit from upper left
    base = np.dstack([0.97 * shade, 0.94 * shade, 0.84 * shade, np.ones_like(shade)])
    im = ax.imshow(np.clip(base, 0, 1), extent=(cx - R, cx + R, cy - R, cy + R), interpolation="bicubic", zorder=3)
    im.set_clip_path(disc)
    for x, y, w, h, a in MARIA:
        e = Ellipse((cx + x * R, cy + y * R), 2 * w * R, 2 * h * R, angle=a, fc="#8f8a76", ec="none", alpha=0.55, zorder=4)
        ax.add_patch(e); e.set_clip_path(disc)
    if detail:
        for x, y, r in ((-0.12, -0.78, 0.055), (0.35, 0.62, 0.04), (-0.55, 0.55, 0.035), (0.70, -0.45, 0.04)):
            c = Circle((cx + x * R, cy + y * R), r * R, fc="#fbf7e8", ec="#a7a08a", lw=0.12, zorder=5)
            ax.add_patch(c); c.set_clip_path(disc)
    # the dish, seen in profile like FeedLab's, its axis toward the Moon
    C = np.array([0.335, 0.355])
    u = np.array([cx, cy]) - C; u /= np.linalg.norm(u)
    v = np.array([-u[1], u[0]])
    h, d, t = 0.25, 0.095, 0.05
    f = h ** 2 / (4 * d)
    s = np.linspace(-1, 1, 120)
    front = C[None] + (d * s ** 2)[:, None] * u + (h * s)[:, None] * v
    back = C[None] + (d * s ** 2 - t * (1 - 0.55 * s ** 2))[:, None] * u + (h * s)[:, None] * v
    F = C + f * u
    lw = 1.0                                                     # points: 1 pt = 14 px at 1024 px
    ax.plot([C[0] - 0.04 * u[0], 0.30], [C[1] - 0.04 * u[1], 0.12], color="#55657f", lw=3.2,
            solid_capstyle="butt", zorder=6)
    ax.add_patch(Polygon([[0.18, 0.085], [0.42, 0.085], [0.39, 0.125], [0.21, 0.125]], closed=True, fc="#55657f",
                         ec="none", zorder=6))
    ax.add_patch(Polygon(np.vstack([front, back[::-1]]), closed=True, fc="#e9eef5", ec="#b8c4d6", lw=0.3, zorder=7))
    inner = C[None] + (d * s ** 2 + 0.004)[:, None] * u + (h * s * 0.98)[:, None] * v
    ax.plot(inner[:, 0], inner[:, 1], color="#ffffff", lw=0.45, alpha=0.9, zorder=8)
    for e in (front[0], front[-1]):
        ax.plot([e[0], F[0]], [e[1], F[1]], color="#8c9bb3", lw=0.75, solid_capstyle="round", zorder=8)
    w1, w2 = 0.045, 0.022                                        # feed horn, mouth toward the dish
    p0, p1 = F - 0.03 * u, F + 0.05 * u
    ax.add_patch(Polygon([p0 + w1 * v, p0 - w1 * v, p1 - w2 * v, p1 + w2 * v], closed=True, fc="#f2a900", ec="#c98700",
                         lw=0.2, zorder=9))
    if detail:                                                   # the signal going up to the Moon
        ang0 = np.arctan2(u[1], u[0])
        for k, rr in enumerate((0.075, 0.12, 0.165)):
            a = np.linspace(ang0 - 0.55, ang0 + 0.55, 40)
            ax.plot(p1[0] + rr * np.cos(a), p1[1] + rr * np.sin(a), color="#ffc94a", lw=0.8, alpha=0.85 - 0.22 * k,
                    solid_capstyle="round", zorder=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=S, transparent=True)
    plt.close(fig)
    return Image.open(buf).convert("RGBA")


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    full, simple = _render(True), _render(False)
    pngs = []
    for s in sizes:
        im = (full if s >= 48 else simple).resize((s, s), Image.LANCZOS)
        b = io.BytesIO(); im.save(b, format="PNG"); pngs.append(b.getvalue())
    head = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, p in zip(sizes, pngs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(p), off + len(data))
        data += p
    docs = Path(__file__).resolve().parents[1] / "docs"
    (docs / "emelab.ico").write_bytes(head + entries + data)
    (docs / "emelab_256.png").write_bytes(pngs[-1])
    return pngs


if __name__ == "__main__":
    main()
