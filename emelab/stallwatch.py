# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Diagnostics: when a full run of the page lasts more than LIMIT_S seconds (the page stops answering clicks),
the stacks of all threads are written once to stderr, which the desktop app saves in server.log."""
from __future__ import annotations

import faulthandler
import sys
import threading
import time
from datetime import datetime, timezone

LIMIT_S = 30.0
_RUN = {"start": None, "dumped": False}
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


def run_started():
    with _LOCK:
        _RUN.update(start=time.monotonic(), dumped=False)
    _ensure_thread()


def run_finished():
    with _LOCK:
        _RUN["start"] = None


def stalled_for(now: float | None = None) -> float | None:
    """Seconds the current run has lasted, or None if no run is in progress."""
    with _LOCK:
        t = _RUN["start"]
    return None if t is None else (now if now is not None else time.monotonic()) - t


def _loop():
    while True:
        time.sleep(5)
        s = stalled_for()
        if s is not None and s > LIMIT_S and not _RUN["dumped"]:
            _RUN["dumped"] = True
            try:
                print(f"\n=== EMELab: page run stuck for {s:.0f} s at {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC: "
                      "stacks of all threads ===", file=sys.stderr, flush=True)
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
                sys.stderr.flush()
            except Exception:
                pass


def _ensure_thread():
    global _THREAD
    if _THREAD is None or not _THREAD.is_alive():
        _THREAD = threading.Thread(target=_loop, name="emelab-stallwatch", daemon=True)
        _THREAD.start()
