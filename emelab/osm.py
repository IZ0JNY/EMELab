# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Interactive OpenStreetMap map for the Station tab (Streamlit component in emelab/osm_map, Leaflet bundled).

The page itself is local, but the map tiles come from tile.openstreetmap.org, so the tile server sees which area
is shown. A click on the map returns {"lat", "lon", "zoom", "t"} (t = click time, to process each click once)."""
from __future__ import annotations

from pathlib import Path

_component = None


def _comp():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("emelab_osm_map", path=str(Path(__file__).resolve().parent / "osm_map"))
    return _component


def station_map(lat: float, lon: float, has_pos: bool, stations=(), height: int = 460, me_label: str = "",
                hint: str = "", key: str = "em_osm", on_change=None):
    """Draw the map; returns the last click {"lat", "lon", "zoom", "t"} or None."""
    return _comp()(lat=float(lat), lon=float(lon), has_pos=bool(has_pos), zoom=13, height=int(height),
                   stations=[[float(a), float(b), str(c)] for a, b, c in stations], me_label=me_label, hint=hint,
                   key=key, default=None, on_change=on_change)
