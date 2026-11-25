# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab printouts (PDF, A4, same layout as FeedLab's reports): measurement diary, QSO log, QSO statistics with
maps, and QSL labels (3 × 8 on A4)."""
from __future__ import annotations

import io
import math
from datetime import datetime

import numpy as np

from .stations import band_label

A4 = (8.27, 11.69)


def _tr(s):
    from . import i18n
    return i18n.tr(s)


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _header(fig, title, station=""):
    from . import __version__
    fig.text(0.06, 0.965, "EMELab — " + _tr(title), fontsize=13, weight="bold")
    if station:
        fig.text(0.06, 0.945, station, fontsize=8, color="0.3")
    fig.text(0.06, 0.02, f"EMELab {__version__} · {datetime.utcnow():%Y-%m-%d %H:%M} UTC · © Ivan De Cesaris IZ0JNY",
             fontsize=6.5, color="0.45")


def _table_pages(pdf, title, station, head, rows, widths, per=40, fs=6.5):
    plt = _plt()
    for k in range(0, max(len(rows), 1), per):
        fig = plt.figure(figsize=A4, dpi=100)
        _header(fig, title, station)
        ax = fig.add_axes([0.04, 0.05, 0.92, 0.87]); ax.axis("off")
        chunk = rows[k:k + per] or [["—"] * len(head)]
        t = ax.table(cellText=chunk, colLabels=[_tr(h) for h in head], colWidths=widths, loc="upper left", cellLoc="left")
        t.auto_set_font_size(False); t.set_fontsize(fs); t.scale(1, 1.2)
        for (r, c), cell in t.get_celld().items():
            cell.set_edgecolor("0.85")
            if r == 0:
                cell.set_facecolor("#2e5c8a"); cell.set_text_props(color="white", weight="bold")
        pdf.savefig(fig); plt.close(fig)


def _fmt(v, n=1):
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else (f"{v:.{n}f}" if isinstance(v, float) else str(v))


def _mode(q: dict) -> str:
    from .logbook import mode_label
    label, assumed = mode_label(q)
    return label + (" (presunto)" if assumed else "")


def log_pdf(qsos: list[dict], station: str = "") -> bytes:
    from matplotlib.backends.backend_pdf import PdfPages
    buf = io.BytesIO()
    head = ["Data UTC", "Nominativo", "Banda", "Modo", "Inv.", "Ric.", "Locator", "km", "Percorso EME (km)",
            "EL Luna", "EL DX", "Spread (Hz)"]
    rows = []
    for q in qsos:
        c = q.get("calc") or {}
        rows.append([q["utc"].strftime("%Y-%m-%d %H:%M"), q["call"], band_label(q.get("band")), _mode(q),
                     q.get("rst_sent") or "", q.get("rst_rcvd") or "", q.get("locator") or "", _fmt(c.get("ground_km"), 0),
                     _fmt(c.get("eme_path_km"), 0), _fmt(c.get("moon_el")), _fmt(c.get("dx_moon_el")), _fmt(c.get("mutual_spread_hz"), 0)])
    with PdfPages(buf) as pdf:
        _table_pages(pdf, "Log dei QSO EME", station, head, rows,
                     [0.13, 0.10, 0.06, 0.06, 0.05, 0.05, 0.08, 0.07, 0.11, 0.07, 0.07, 0.08])
        _map_page(pdf, qsos, station)
    return buf.getvalue()


def _map_page(pdf, qsos, station):
    """World map (equirectangular, coastlines from Natural Earth when available) with every QSO path."""
    plt = _plt()
    from . import logbook
    fig = plt.figure(figsize=A4, dpi=100)
    _header(fig, "Mappa dei QSO", station)
    ax = fig.add_axes([0.06, 0.40, 0.88, 0.50])
    world_outline(ax)
    cols = logbook.BAND_COLORS
    for q in qsos:
        my, dx = logbook.latlon(q.get("my_locator")), logbook.latlon(q.get("locator"))
        if my and dx:
            lat, lon = great_circle_points(my, dx)
            ax.plot(lon, lat, color=cols.get(q.get("band"), "0.4"), lw=0.8, alpha=0.8)
            ax.plot(dx[1], dx[0], "o", ms=3, color=cols.get(q.get("band"), "0.4"))
    for b, c in cols.items():
        ax.plot([], [], color=c, label=band_label(b))
    ax.legend(fontsize=7, loc="lower left")
    ax.set_xlim(-180, 180); ax.set_ylim(-90, 90); ax.set_aspect("equal")
    ax.set_xlabel("°E"); ax.set_ylabel("°N")
    pdf.savefig(fig); plt.close(fig)


def great_circle_points(a, b, n=80):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    p1 = np.array([math.cos(la1) * math.cos(lo1), math.cos(la1) * math.sin(lo1), math.sin(la1)])
    p2 = np.array([math.cos(la2) * math.cos(lo2), math.cos(la2) * math.sin(lo2), math.sin(la2)])
    w = math.acos(float(np.clip(p1 @ p2, -1, 1)))
    if w < 1e-9:
        return np.array([a[0]]), np.array([a[1]])
    t = np.linspace(0, 1, n)
    pts = (np.sin((1 - t) * w)[:, None] * p1 + np.sin(t * w)[:, None] * p2) / math.sin(w)
    lat = np.degrees(np.arcsin(pts[:, 2]))
    lon = np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))
    jump = np.where(np.abs(np.diff(lon)) > 180)[0]          # break the line at the date line
    for j in jump[::-1]:
        lat = np.insert(lat, j + 1, np.nan); lon = np.insert(lon, j + 1, np.nan)
    return lat, lon


def world_outline(ax):
    """Coastlines: Natural Earth 110 m (public domain) shipped in emelab/data when present, else a graticule only."""
    from pathlib import Path
    import json
    p = Path(__file__).resolve().parent / "data" / "ne_110m_land.json"
    if p.exists():
        for poly in json.loads(p.read_text())["polygons"]:
            xy = np.array(poly)
            ax.fill(xy[:, 0], xy[:, 1], color="#e8e4d8", ec="#9a9484", lw=0.4)
    ax.set_facecolor("#dfeaf3")
    ax.grid(alpha=0.3)


def diary_pdf(rows: list[dict], station: str = "", advice: list[str] | None = None) -> bytes:
    from matplotlib.backends.backend_pdf import PdfPages
    from . import db as edb
    plt = _plt()
    buf = io.BytesIO()
    head = ["Data UTC", "Banda", "Tipo", "Y (dB)", "Y atteso", "ΔY", "SNR", "EL", "°C", "UR %", "Note"]
    tab = []
    for r in rows:
        tab.append([r["utc"].replace("T", " ").replace("Z", "")[:16], band_label(r.get("band_ghz")), _tr(edb.KINDS.get(r["kind"], r["kind"]))[:28],
                    _fmt(r.get("y_db"), 2), _fmt(r.get("_y_exp"), 2), _fmt(r.get("_y_delta"), 2), _fmt(r.get("snr_db")),
                    _fmt(r.get("_el")), _fmt(r.get("t_c")), _fmt(r.get("rh"), 0), (r.get("notes") or "")[:30]])
    with PdfPages(buf) as pdf:
        if advice:
            fig = plt.figure(figsize=A4, dpi=100)
            _header(fig, "Diario delle misure — conclusioni", station)
            import textwrap
            y = 0.90
            for a in advice:
                for line in textwrap.wrap("• " + _tr(a), 100):
                    fig.text(0.06, y, line, fontsize=9); y -= 0.022
                y -= 0.01
            pdf.savefig(fig); plt.close(fig)
        _table_pages(pdf, "Diario delle misure", station, head, tab, [0.12, 0.06, 0.20, 0.06, 0.07, 0.05, 0.05, 0.05, 0.05, 0.05, 0.24])
    return buf.getvalue()


def qsl_labels_pdf(qsos: list[dict], my_call: str, my_locator: str = "", cols: int = 3, rows: int = 8) -> bytes:
    """QSL labels, 3 × 8 per A4 sheet (70 × 37 mm): 'To Radio' call and name/address (from QRZ when known), then
    date, time UTC, band, mode, report and 'EME'."""
    plt = _plt()
    from matplotlib.backends.backend_pdf import PdfPages
    buf = io.BytesIO()
    per = cols * rows
    with PdfPages(buf) as pdf:
        for k in range(0, len(qsos), per):
            fig = plt.figure(figsize=A4, dpi=100)
            for n, q in enumerate(qsos[k:k + per]):
                cx, cy = n % cols, n // cols
                x0, y0 = 0.01 + cx * (0.98 / cols), 0.995 - (cy + 1) * (0.99 / rows)
                w, h = 0.98 / cols, 0.99 / rows
                fig.text(x0 + 0.02, y0 + h - 0.025, f"To Radio {q['call']}", fontsize=10, weight="bold")
                if q.get("name"):
                    fig.text(x0 + 0.02, y0 + h - 0.045, q["name"][:40], fontsize=7)
                if q.get("address"):
                    fig.text(x0 + 0.02, y0 + h - 0.060, q["address"][:48], fontsize=6)
                fig.text(x0 + 0.02, y0 + 0.040, f"{q['utc']:%Y-%m-%d}  {q['utc']:%H:%M} UTC  {band_label(q.get('band'))}  "
                         f"{q.get('mode') or ''}  {_tr('rapporto')} {q.get('rst_sent') or ''}", fontsize=6.5)
                fig.text(x0 + 0.02, y0 + 0.020, f"EME · {my_call} {my_locator} · {_tr('Grazie per il QSO')}", fontsize=6.5, color="0.3")
            pdf.savefig(fig); plt.close(fig)
    return buf.getvalue()
