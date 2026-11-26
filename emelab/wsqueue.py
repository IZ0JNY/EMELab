# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Keep the browser session alive when a page run sends many elements at once.

Streamlit 1.67 (Starlette server) queues at most 500 messages per browser. When a long run fills the
queue faster than the window reads it, Streamlit drops the session on the server but leaves the socket
open: the page stays on screen, yet every click (tab checkboxes, «Chiudi» buttons) is silently thrown
away. EMELab has about twenty tabs, so a full run can pass 500 messages on a slow PC.

lift() removes the cap: for browsers that connect later (module constant) and for the queues of the
sessions already connected. It is cheap and safe to call at every run; on another Streamlit it does
nothing."""
from __future__ import annotations


def _active_clients() -> list:
    try:
        from streamlit.runtime import Runtime
        mgr = Runtime.instance()._session_mgr
        return [s.client for s in mgr.list_active_sessions()]
    except Exception:
        return []


def lift_queue(q) -> bool:
    """Make an asyncio.Queue unbounded; True if it was bounded."""
    if getattr(q, "_maxsize", 0) > 0:
        q._maxsize = 0
        return True
    return False


def lift() -> int:
    """Remove the send-queue cap; returns how many existing queues were changed."""
    try:
        from streamlit.web.server.starlette import starlette_websocket as ws
        ws.WEBSOCKET_MAX_SEND_QUEUE_SIZE = 0          # asyncio.Queue(maxsize=0) = no limit
    except Exception:
        return 0
    n = 0
    for c in _active_clients():
        q = getattr(c, "_send_queue", None)
        if q is not None and lift_queue(q):
            n += 1
    return n
