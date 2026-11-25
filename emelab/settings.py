# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EME Assistant's own settings folder (Windows: %APPDATA%\\EMELab, Linux: ~/.config/EMELab, or EMELAB_CONFIG):
settings.json and the measurement database. Nothing here is ever uploaded."""
from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    p = Path(os.environ.get("EMELAB_CONFIG", Path(base or Path.home()) / "EMELab"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_settings() -> dict:
    try:
        return json.loads((config_dir() / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(**kw) -> dict:
    s = {**load_settings(), **kw}
    (config_dir() / "settings.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s
