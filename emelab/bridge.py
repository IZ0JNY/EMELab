# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""FeedLab project files (.feedlab.json) in EME Assistant: dish, feed and the results FeedLab already computed (gain,
G/T, efficiency, spillover, edge taper, Tsys). EME Assistant never recomputes them. One project per band."""
from __future__ import annotations

import json
import os
from pathlib import Path

FORMAT = "FeedLab project"


def load_project(data: str | bytes) -> dict:
    p = json.loads(data)
    if p.get("format") != FORMAT:
        raise ValueError("non è un file di progetto FeedLab")
    if not (p.get("results") or {}).get("gain_dbi"):
        raise ValueError("il progetto non contiene i risultati calcolati da FeedLab")
    return p


def feedlab_auto_path() -> Path:
    """Where FeedLab keeps the open design on this PC."""
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(os.environ.get("FEEDLAB_CONFIG", Path(base or Path.home()) / "FeedLab")) / "feedlab_project.json"


def latest_feedlab_project() -> dict | None:
    try:
        return load_project(feedlab_auto_path().read_text(encoding="utf-8"))
    except Exception:
        return None


def describe(p: dict) -> str:
    i = p["inputs"]
    d = i["dish"]
    return (f"{i.get('feed_name', i.get('feed_kind'))} · {i['f_ghz']:.4f} GHz · "
            f"{'offset' if d['kind'] == 'offset' else 'prime focus'} D {d['D_mm']:.0f} mm f/D {d['fD']:.3f} · "
            f"{i.get('material', '')}")


def setup_from_project(p: dict, extra: dict) -> dict:
    """Setup for EME Assistant from the results stored in the project (nothing is recomputed)."""
    i, r = p["inputs"], p["results"]
    d = i["dish"]
    return {"band_ghz": float(i["f_ghz"]), "D_m": d["D_mm"] / 1000, "eta_ap": r["eta"], "gain_dbi": r["gain_dbi"],
            "edge_taper_db": r["edge_taper_db"], "spill": r["spill"], "ground_frac": 0.25 if d["kind"] == "offset" else 0.5,
            "feed": i.get("feed_name") or i.get("feed_kind"), "dish": f"{d['kind']} D {d['D_mm']:.0f} mm f/D {d['fD']:.3f}",
            "material": i.get("material"), "pc_mm": r.get("phase_center_mm"), "feedlab_gt": r.get("g_over_t"),
            "feedlab_tsys": (r.get("tsys") or {}).get("sys"), "source": "FeedLab", "project_created_utc": p.get("created_utc"),
            **extra}
