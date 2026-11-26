# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Dish and power per band from the HB9Q EME logger (https://logger.hb9q.ch/).

Every registered user of the logger lists the equipment per band in the profile, for example
``10xxx MHz - 1.8M offset dish - 60W``. The user reads those profiles with his own login and saves them in a CSV file
(columns ``call, band, antenna, power_w, hb9q``); EMELab compares the file with the EME stations table and, only for
the rows the user ticks, writes the values as corrections by hand (✏️), which can be taken away again.
Only the bands from 10 GHz up that EMELab follows are kept: 10, 24, 47 and 76 GHz."""
from __future__ import annotations

import csv
import io
import re

from emelab.stations import band_of

BANDS = ("10G", "24G", "47G", "76G")
CSV_COLUMNS = ("call", "band", "antenna", "power_w", "hb9q")

_FREQ = re.compile(r"^\s*(\d+)\s*([xX]*)\s*(?:MHz)?\s*$")
_POWER = re.compile(r"(\d*[.,]?\d+)\s*([km]?)W(?:atts?|att|t)?\b", re.I)
_DISH = re.compile(r"(\d+(?:[.,]\d+)?)\s*(cm|m(?:t|tr|eters?|etres?)?)(?:\b|(?=PF))", re.I)
_RX_ONLY = re.compile(r"rx\s*only|only\s*rx|rx\s*test|no\s*tx", re.I)
_EMAIL = re.compile(r"\S+@\S+")


def band_of_text(freq: str) -> str | None:
    """«10xxx», «10368», «24048 MHz», «76032» → internal band key ("10G"…), None for the bands below 10 GHz."""
    m = _FREQ.match(freq or "")
    if not m:
        return None
    b = band_of(float(m.group(1) + "0" * len(m.group(2))))      # «10xxx» = 10000 MHz
    return b if b in BANDS else None


def power_w(text: str) -> float | None:
    """The transmitter power written in the profile («60W», «1.2KW», «LNA 0,5dB, 32W»), in watts."""
    t = (text or "").strip()
    m = _POWER.search(t)
    if m:
        w = float(m.group(1).replace(",", ".")) * {"k": 1000, "m": 0.001}.get(m.group(2).lower(), 1)
    elif re.fullmatch(r"\d+(?:[.,]\d+)?", t):        # just a number: watts
        w = float(t.replace(",", "."))
    else:
        return None
    return w or None                                  # «0W», «RX only»: no transmitter


def antenna(text: str) -> str:
    """The antenna in the same style as the EME Directory: «1.8m dish», «2.4m dish OS» (offset); anything else as written."""
    t = (text or "").strip()
    d = None
    m = _DISH.search(t)
    if m:
        d = float(m.group(1).replace(",", "."))
        if m.group(2).lower() == "cm" and d >= 20:      # «0.91cm» is a typo for metres
            d /= 100
    else:                                   # «1.8 pf dish», «240 PF», «Laminas 160 offset»: no unit
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\S+\s+)?(?:dish|disk|offset|pf|prime|cassegrain)", t, re.I)
        if m:
            d = float(m.group(1).replace(",", "."))
            d = d / 100 if d >= 30 else d
    if d is not None and 0.2 <= d <= 40:
        return f"{d:g}m dish" + (" OS" if re.search(r"off\s*-?\s*set|offest|\bOS\b|o/s|\bOF\b", t, re.I) else "")
    return t[:40]


def parse_equipment(text: str) -> dict[str, dict]:
    """The «Equipment» lines of a profile → {band: {"antenna", "power_w", "hb9q"}}, only 10/24/47/76 GHz."""
    out = {}
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(" - ")]
        if len(parts) < 2:
            continue
        b = band_of_text(parts[0])
        if not b or b in out:
            continue
        rest = _EMAIL.sub("", " - ".join(parts[1:])).strip()
        out[b] = {"antenna": antenna(parts[1]), "power_w": None if _RX_ONLY.search(rest) else power_w(parts[-1]) or power_w(rest),
                 "hb9q": rest}
    return out


def to_csv(profiles: dict[str, str]) -> str:
    """{call: profile text} → the CSV file EMELab imports."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for call in sorted(profiles):
        for b, v in sorted(parse_equipment(profiles[call]).items(), key=lambda x: BANDS.index(x[0])):
            w.writerow([call.upper(), b, v["antenna"], "" if v["power_w"] is None else f"{v['power_w']:g}", v["hb9q"]])
    return buf.getvalue()


def parse_csv(text: str) -> list[dict]:
    """The CSV file → rows {call, band, antenna, power_w, hb9q}; bands also as «10GHz», only 10/24/47/76 GHz."""
    rows = []
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        call = (r.get("call") or "").strip().upper()
        b = (r.get("band") or "").strip().upper().replace("GHZ", "G")
        if not call or b not in BANDS:
            continue
        try:
            pw = float((r.get("power_w") or "").replace(",", ".")) or None
        except ValueError:
            pw = None
        rows.append({"call": call, "band": b, "antenna": (r.get("antenna") or "").strip(), "power_w": pw,
                     "hb9q": (r.get("hb9q") or "").strip()})
    return rows


def _dish_m(ant: str) -> float | None:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)m\b", ant or "")
    return float(m.group(1)) if m else None


def compare(rows: list[dict], current: dict[str, dict]) -> list[dict]:
    """HB9Q rows against what EMELab knows ({call: {band: {"antenna", "power_w"}}}, the directory with the corrections).
    Each row gets "state": "uguale" (same), "nuovo" (band missing here), "manca" (antenna or power missing here) or
    "diverso" (dish differs by more than 0.1 m, or power by more than 15 %)."""
    out = []
    for r in rows:
        cur = (current.get(r["call"]) or {}).get(r["band"]) or {}
        ca, cp = (cur.get("antenna") or "").strip(), cur.get("power_w")
        if not cur:
            state = "nuovo"
        else:
            dh, dc = _dish_m(r["antenna"]), _dish_m(ca)
            ant_diff = (dh is not None and dc is not None and abs(dh - dc) > 0.1)
            pw_diff = bool(r["power_w"] and cp and abs(r["power_w"] - cp) > 0.15 * max(r["power_w"], cp))
            missing = (r["antenna"] and not ca) or (r["power_w"] and not cp)
            state = "diverso" if (ant_diff or pw_diff) else "manca" if missing else "uguale"
        out.append({**r, "state": state, "cur_antenna": ca, "cur_power_w": cp, "known": r["call"] in current})
    return out


def merged(r: dict) -> dict:
    """The correction written for one ticked row: HB9Q's values, keeping ours where HB9Q says nothing."""
    return {"antenna": r["antenna"] or r.get("cur_antenna") or "", "power_w": r["power_w"] or r.get("cur_power_w")}
