# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Order of the main tabs, chosen in the Assistant («Schede da mostrare e ordine») and saved in settings.json."""
from __future__ import annotations


def merge(default: list[str], saved: list[str] | None) -> list[str]:
    """Saved order for the tabs that still exist; a tab added in a newer version goes right after the tab that
    precedes it in the default order (or first, if it has no predecessor)."""
    out = [k for k in dict.fromkeys(saved or []) if k in default]
    if not out:
        return list(default)
    for i, k in enumerate(default):
        if k in out:
            continue
        prev = next((p for p in reversed(default[:i]) if p in out), None)
        out.insert(out.index(prev) + 1 if prev else 0, k)
    return out


def move(order: list[str], key: str, delta: int) -> list[str]:
    """Moves «key» delta places (negative = earlier); stays inside the list."""
    out = list(order)
    if key not in out:
        return out
    i = out.index(key)
    j = max(0, min(len(out) - 1, i + delta))
    out.insert(j, out.pop(i))
    return out
