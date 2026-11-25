# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""WSJT-X settings that the UDP protocol does not carry, read (only read) from WSJT-X.ini, next to wsjtx_log.adi.

The top-level sections hold the configuration in use («[MultiSettings] CurrentName»); the other configurations sit
under «[MultiSettings] <name>\\…» and are ignored. WSJT-X writes the file when a setting changes or when it closes,
so a change made a moment ago may not be there yet: the panel shows the time the file was saved.

- [Astro] DopplerTracking, DopplerMethod: 0 none, 1 full Doppler to DX grid, 2 constant frequency on Moon (CFOM),
  3 own echo, 4 on DX echo, 5 call DX (order of the Astro window radio buttons in WSJT-X);
- [Configuration] SplitMode: split_mode_none / split_mode_rig / split_mode_emulate («Fake It»);
- [MainWindow] TxFirst, [Common] AutoSeq, MaxDrift."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

DOPPLER_METHODS = {0: "None", 1: "Full", 2: "CFOM", 3: "OwnEcho", 4: "OnDxEcho", 5: "CallDx"}
SPLIT = {"split_mode_none": "None", "split_mode_rig": "Rig", "split_mode_emulate": "Fake It"}


def find(log_path: str | Path | None = None) -> Path | None:
    """WSJT-X.ini in the folder of wsjtx_log.adi (the given one, or the one found on this PC)."""
    cands = []
    if log_path:
        p = Path(str(log_path))
        cands.append((p if p.is_dir() else p.parent) / "WSJT-X.ini")
    try:
        from . import wsjtx_logfile
        f = wsjtx_logfile.find_default()
        if f:
            cands.append(f.parent / "WSJT-X.ini")
        cands += [p.parent / "WSJT-X.ini" for p in wsjtx_logfile.default_paths()]
    except Exception:
        pass
    return next((c for c in cands if c.is_file()), None)


def parse(text: str) -> dict:
    """{section: {key: raw value}} of the top-level sections (keys with «\\» belong to other configurations)."""
    out, sec = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            out.setdefault(sec, {})
        elif sec and "=" in line:
            k, v = line.split("=", 1)
            if "\\" not in k:
                out[sec][k] = v
    return out


def _bool(v):
    return None if v is None else v.strip().lower() == "true"


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def read(path: str | Path | None = None) -> dict:
    """{"config", "doppler_tracking", "doppler" ('CFOM'…; 'None' when tracking is off), "split" ('Rig'…), "tx_first",
    "auto_seq", "max_drift", "saved" (UTC datetime), "path"}; {} when the file is not found or unreadable."""
    p = Path(path) if path else find()
    if not p or not p.is_file():
        return {}
    try:
        ini = parse(p.read_text(encoding="utf-8", errors="replace"))
        saved = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
    except OSError:
        return {}
    astro, conf = ini.get("Astro", {}), ini.get("Configuration", {})
    track = _bool(astro.get("DopplerTracking"))
    method = DOPPLER_METHODS.get(_int(astro.get("DopplerMethod")))
    split = next((name for key, name in SPLIT.items() if key in (conf.get("SplitMode") or "")), None)
    return {"config": ini.get("MultiSettings", {}).get("CurrentName"), "doppler_tracking": track,
            "doppler": ("None" if track is False else method), "split": split,
            "tx_first": _bool(ini.get("MainWindow", {}).get("TxFirst")), "auto_seq": _bool(ini.get("Common", {}).get("AutoSeq")),
            "max_drift": _int(ini.get("Common", {}).get("MaxDrift")), "saved": saved, "path": str(p)}


def differences(ini: dict, preset: dict) -> list[dict]:
    """Settings of WSJT-X.ini that differ from the band preset: [{"code", "msg", "detail"}]."""
    if not ini:
        return []
    out = []
    names = {"doppler": "Doppler tracking", "split": "Split Operation", "tx_first": "Tx even/1st", "auto_seq": "Auto Seq",
             "max_drift": "Max Drift"}
    for k, label in names.items():
        want, have = preset.get(k), ini.get(k)
        if want is None or have is None or str(want) == str(have):
            continue
        show = {True: "sì", False: "no"}
        out.append({"code": f"ini_{k}", "msg": f"{label} diverso dal preset della banda",
                    "detail": f"{show.get(have, have)} → {show.get(want, want)} (WSJT-X.ini)"})
    return out
