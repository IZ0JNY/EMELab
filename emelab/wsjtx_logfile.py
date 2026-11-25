# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""WSJT-X log file (wsjtx_log.adi): EMELab follows it like «tail -f» and picks up every QSO WSJT-X appends.

WSJT-X writes one ADIF record to wsjtx_log.adi each time you press OK in «Log QSO». The file is read only from the
position reached last time (kept in the EMELab settings), so a QSO is never read twice and nothing is needed on the
WSJT-X side: no UDP port, no conflict with JTAlert, GridTracker or other loggers. A record still being written (no
<EOR> yet) waits for the next look; a file that got shorter (deleted, new log) is read again from the start."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import logbook

EOR = re.compile(rb"<eor>", re.I)


def _bases() -> list[Path]:
    home = Path.home()
    if sys.platform.startswith("win"):
        out = [Path(os.environ["LOCALAPPDATA"])] if os.environ.get("LOCALAPPDATA") else []
        out.append(home / "AppData" / "Local")
        if os.environ.get("USERPROFILE"):
            out.append(Path(os.environ["USERPROFILE"]) / "AppData" / "Local")
    elif sys.platform == "darwin":
        out = [home / "Library" / "Application Support"]
    else:
        out = [Path(os.environ["XDG_DATA_HOME"])] if os.environ.get("XDG_DATA_HOME") else []
        out.append(home / ".local" / "share")
    seen, uniq = set(), []
    for b in out:
        k = str(b).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    return uniq


def default_paths() -> list[Path]:
    """Where WSJT-X keeps wsjtx_log.adi (File → Open log directory): main instance first, then --rig-name instances
    («WSJT-X - IC9700») and WSJT-X Improved / JTDX, which use the same file name."""
    out = []
    for b in _bases():
        out.append(b / "WSJT-X" / "wsjtx_log.adi")
        for pat in ("WSJT-X*", "JTDX*"):
            try:
                out += sorted(p / "wsjtx_log.adi" for p in b.glob(pat) if p.is_dir() and p.name != "WSJT-X")
            except OSError:
                pass
    return out


def find_default() -> Path | None:
    """The wsjtx_log.adi that exists; with more than one, the one written most recently."""
    found = [p for p in default_paths() if p.is_file()]
    if not found:
        return None
    try:
        return max(found, key=lambda p: p.stat().st_mtime)
    except OSError:
        return found[0]


def clean_path(text: str) -> str:
    """The path as typed or pasted: without the quotes Windows adds with «Copy as path»; a folder (the one WSJT-X
    opens with File → Open log directory) becomes the wsjtx_log.adi inside it; %LOCALAPPDATA% and ~ are expanded."""
    p = (text or "").strip().strip('"').strip("'").strip()
    if not p:
        return ""
    p = os.path.expanduser(os.path.expandvars(p))
    if Path(p).is_dir():
        p = str(Path(p) / "wsjtx_log.adi")
    return p


class LogTail:
    """Reads the complete ADIF records appended to a file since the last call."""

    def __init__(self, path, offset: int | None = None):
        self.path = Path(path)
        self.offset = offset            # None: start from the end (only the QSOs logged from now on)

    def read_new(self) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if self.offset is None:
            self.offset = size
            return []
        if size < self.offset:          # file replaced or emptied: read it again from the start
            self.offset = 0
        if size == self.offset:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read(size - self.offset)
        last = None
        for last in EOR.finditer(chunk):
            pass
        if last is None:                # record still being written
            return []
        done = chunk[:last.end()]
        self.offset += len(done)
        return logbook.parse_adif(done.decode("utf-8", "replace"))
