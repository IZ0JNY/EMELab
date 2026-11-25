# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Are the WSJT-X settings right for EME on this band? Checked on every UDP Status message.

What the Status message shows, and what EMELab can do about it:
- mode, submode and T/R period (Q65-60D at 10 GHz, Q65-60E from 24 GHz up, or your choice per band): corrected by
  EMELab with the Configure message, if WSJT-X has «Accept UDP requests» ticked; otherwise only a warning;
- dial frequency outside the bands from 10 GHz up, callsign and locator different from the EMELab station,
  TX watchdog: only a warning (the UDP protocol cannot change them).
Doppler tracking, Prop Mode, audio and rig settings are not in the Status message: EMELab cannot see them."""
from __future__ import annotations

from . import dx, stations

NULL = 0xFFFFFFFF
Q65_STANDARD = {"10G": "60D", "24G": "60E", "47G": "60E", "76G": "60E", "122G": "60E", "134G": "60E"}


def expected_mode(band: str) -> str:
    """Q65 submode for the band ('60D'): the user's choice when EMELab has one (dx.band_mode), else the standard."""
    fn = getattr(dx, "band_mode", None)
    if fn:
        try:
            return fn(band)
        except Exception:
            pass
    return Q65_STANDARD.get(band, "60E")


def check(status: dict, station: dict | None = None) -> list[dict]:
    """Problems in the WSJT-X Status: [{"code", "msg", "fix"}], fix = the Q65 code to send ('60D') or None."""
    out = []
    hz = status.get("dial_hz")
    band = stations.band_of(hz / 1e6) if hz else None
    if hz and band is None:
        out.append({"code": "band", "msg": "WSJT-X non è su una banda EME da 10 GHz in su", "detail": f"{hz / 1e6:,.3f} MHz",
                    "fix": None})
    if band:
        want = expected_mode(band)
        mode = (status.get("mode") or "").strip()
        sub = (status.get("submode") or "").strip().upper()
        tr = status.get("tr_period")
        tr = None if tr in (None, 0, NULL) else int(tr)
        have = f"{mode}" + (f"-{tr or ''}{sub}" if mode.upper().startswith("Q65") else (f" {sub}" if sub else ""))
        if not mode.upper().startswith("Q65") or sub != want[-1] or (tr is not None and tr != int(want[:-1])):
            out.append({"code": "mode", "msg": "Modo diverso da quello della banda", "detail": f"{have} → Q65-{want} ({band})",
                        "fix": want})
    stn = station or {}
    my_call = (stn.get("callsign") or "").upper().strip()
    de_call = (status.get("de_call") or "").upper().strip()
    if my_call and de_call and de_call.split("/")[0] != my_call.split("/")[0]:
        out.append({"code": "call", "msg": "Nominativo in WSJT-X diverso da quello della stazione", "detail": f"{de_call} ≠ {my_call}",
                    "fix": None})
    my_loc = (stn.get("locator") or "").upper().strip()
    de_grid = (status.get("de_grid") or "").upper().strip()
    if my_loc and de_grid and de_grid[:4] != my_loc[:4]:
        out.append({"code": "grid", "msg": "Locator in WSJT-X diverso da quello della stazione", "detail": f"{de_grid} ≠ {my_loc}",
                    "fix": None})
    if status.get("tx_watchdog"):
        out.append({"code": "watchdog", "msg": "Il TX watchdog di WSJT-X ha fermato la trasmissione", "detail": "",
                    "fix": None})
    return out
