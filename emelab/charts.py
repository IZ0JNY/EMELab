# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""One place for how every Plotly chart in EMELab behaves.

install() wraps Streamlit's plotly_chart once, so every chart (st.plotly_chart, col.plotly_chart, ...)
gets mouse-wheel zoom (double click resets the view) and keeps the user's zoom when the page refreshes.
A chart can still pass its own config= or uirevision: those win over the defaults here.
Streamlit's built-in charts (st.line_chart ...) already zoom with the wheel."""
from __future__ import annotations

import functools
import types

CONFIG = {"scrollZoom": True, "doubleClick": "reset+autosize", "displaylogo": False}


def defaults(fig, config=None, key=None):
    """Return the config to use and set a stable uirevision on fig (when it has none)."""
    cfg = dict(CONFIG)
    cfg.update(config or {})
    lay = getattr(fig, "layout", None)
    if lay is not None:
        try:
            if lay.uirevision is None:      # same chart, same title -> keep zoom; new title (e.g. other band) -> reset
                lay.uirevision = f"{key or ''}|{lay.title.text or ''}"
        except Exception:
            pass
    return cfg


def install():
    from streamlit.delta_generator import DeltaGenerator
    orig = DeltaGenerator.plotly_chart
    if getattr(orig, "_emelab_zoom", False):
        return

    @functools.wraps(orig)
    def plotly_chart(self, figure_or_data, *args, config=None, **kw):
        return orig(self, figure_or_data, *args, config=defaults(figure_or_data, config, kw.get("key")), **kw)

    plotly_chart._emelab_zoom = True
    DeltaGenerator.plotly_chart = plotly_chart
    import streamlit                        # st.plotly_chart was bound to the main area at import time
    main = getattr(streamlit, "_main", None)
    if main is not None:
        streamlit.plotly_chart = types.MethodType(plotly_chart, main)
