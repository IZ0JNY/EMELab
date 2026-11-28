# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Closing the alert pop-ups (⚠️ WSJT-X, 🚨 DriverDish) so that they stay closed.

Two things made «Chiudi» look broken (Ivan, 0.1.25):

1. Streamlit runs a click inside a dialog only after the page run in progress has finished. With many tabs
   that run can take several seconds, so the pop-up stayed on screen, Ivan clicked again, and the second
   click landed on the next pop-up (or counted the alert as closed twice: never again). hook() puts a small
   script in the page: «Chiudi» and «Ho visto» close the dialog at once in the window, as its ✕ does, and
   the dialog's on_dismiss callback records the closing on the next run.
2. An alert closed while the problem lasts came back as soon as the problem disappeared for a single
   reading (WSJT-X silent for a moment, DriverDish missing one «status»). prune() forgets a closed alert
   only when its problem has been gone for GRACE_S seconds."""
from __future__ import annotations

import time

GRACE_S = 120.0
CLOSE_KEYS = ("wjp_close", "ea_alarm_ok")       # st.button keys of the «Chiudi» buttons in the pop-ups


def prune(closed: set, present, gone_since: dict, now: float | None = None, grace: float = GRACE_S) -> set:
    """Forget the closed alerts whose problem has been gone for `grace` seconds (closed is changed in place).

    gone_since keeps, for each closed alert that is not present now, when it was first seen gone."""
    now = time.time() if now is None else now
    present = set(present)
    for k in list(closed):
        if k in present:
            gone_since.pop(k, None)
        elif now - gone_since.setdefault(k, now) >= grace:
            closed.discard(k)
            gone_since.pop(k, None)
    for k in list(gone_since):
        if k not in closed:
            gone_since.pop(k, None)
    return closed


JS = """<script>
const w = window.parent, doc = w.document;   // the page itself (st.html) or the frame's parent
const SEL = %s;
if (!w.emeDialogClose) {
  w.emeDialogClose = true;
  doc.addEventListener('click', ev => {
    const b = ev.target.closest && ev.target.closest(SEL);
    if (!b) return;
    const d = b.closest('[role="dialog"]');
    const x = d && d.querySelector('button[aria-label="Close"]');
    if (!x) return;                       // no ✕ found: the click goes to Streamlit as before
    ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
    x.click();                            // closes now; on_dismiss records it on the next run
  }, true);
}
</script>"""


def hook():
    """Script that makes «Chiudi» close the pop-ups at once (installed once in the page, cheap at every run)."""
    import json

    import streamlit as _st
    sel = ", ".join(f".st-key-{k} button" for k in CLOSE_KEYS)
    js = JS % json.dumps(sel)
    try:                                             # Streamlit ≥ 1.5x: runs in the page itself, no frame, no gap
        _st.html(js, unsafe_allow_javascript=True)
        return
    except TypeError:
        pass
    if hasattr(_st, "iframe"):                       # Streamlit ≥ 1.52
        _st.iframe(js, height=1)
    else:
        import streamlit.components.v1 as components
        components.html(js, height=0)
