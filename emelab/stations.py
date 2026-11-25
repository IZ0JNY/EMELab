# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EME station database, built on this PC from:

* WSJT-X CALL3.TXT  — callsign, locator (and the "EME" flag) of the stations in WSJT-X's own list;
* WSJT-X ALL.TXT    — every message decoded: who was really heard, on which band, with which SNR and when;
* the EME Directory of Henk PA0PLY (https://www.pa0ply.nl/eme-directory/) — one PDF per band with callsign,
  locator, name, antenna and power (downloaded by the user; e-mail addresses are not kept).

Name, address and QSL data can be added from QRZ.com (user's own account) for QSL labels. Nothing is uploaded."""
from __future__ import annotations

import re
from datetime import datetime, timezone

LOC = r"[A-R]{2}\d{2}(?:[A-X]{2}(?:\d{2})?)?"
LOC_RX = re.compile(rf"^{LOC}$", re.I)
CALL_RX = re.compile(r"^(?=.*\d)[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}(?:/[A-Z0-9]{1,4})?$", re.I)
BANDS_MHZ = {"10G": (10000, 10500), "24G": (24000, 24250), "47G": (47000, 47200), "76G": (75500, 81000),
             "122G": (122250, 123000), "134G": (134000, 141000)}


def band_of(freq_mhz: float | None) -> str | None:
    if freq_mhz is None:
        return None
    for b, (lo, hi) in BANDS_MHZ.items():
        if lo <= freq_mhz <= hi:
            return b
    return None


def band_label(band) -> str:
    """Band as shown to the user: «10GHz», «24GHz», «122GHz»… from the internal key ("10G") or a frequency in GHz
    (10.368). The internal keys and the ADIF bands stay as they are; only what is displayed changes."""
    if band is None or band == "":
        return ""
    if isinstance(band, (int, float)):
        return f"{int(band)}GHz"
    b = str(band)
    return f"{b[:-1]}GHz" if b.endswith("G") and b[:-1].isdigit() else b


def band_sort_key(label: str):
    """Order band labels by frequency («10GHz» before «24GHz» before «122GHz»), anything else after."""
    m = re.match(r"^(\d+(?:\.\d+)?)", str(label or ""))
    return (0, float(m.group(1))) if m else (1, str(label))


# ------------------------------------------------------------------ WSJT-X CALL3.TXT
def parse_call3(text: str) -> list[dict]:
    """CALL3.TXT lines: CALL,GRID[,EME][,previous call][,date] ; '//' lines are comments."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        f = [x.strip() for x in line.split(",")]
        if len(f) < 2 or not CALL_RX.match(f[0]) or not LOC_RX.match(f[1]):
            continue
        out.append({"call": f[0].upper(), "locator": f[1][:6].upper() if len(f[1]) >= 6 else f[1].upper(),
                    "eme": any(x.upper() == "EME" for x in f[2:]), "source": "CALL3"})
    return out


def eme_only(rows: list[dict], known_eme: set[str]) -> list[dict]:
    """CALL3.TXT holds every station WSJT-X knows (tens of thousands): keep only those marked EME, or already known
    as EME stations (EME Directory, heard on 10 GHz and up, in the log)."""
    return [r for r in rows if r.get("eme") or r["call"] in known_eme]


# ------------------------------------------------------------------ WSJT-X ALL.TXT
_ALL_NEW = re.compile(r"^(\d{6})_(\d{6})\s+([\d.]+)\s+(Rx|Tx)\s+(\S+)\s+(-?\d+)\s+(-?[\d.]+)\s+(-?\d+)\s+(.*)$")
_ALL_OLD = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([\d.]+)\s+(Rx|Tx)\s+(\S+)\s+(-?\d+)\s+(-?[\d.]+)\s+(-?\d+)\s+(.*)$")


def parse_all(text: str) -> list[dict]:
    """Decodes (Rx) of WSJT-X ALL.TXT: UTC time, dial frequency (MHz), mode, SNR, DT, DF and the message; the
    calls and the locator are taken from the message ('CQ K1JT FN20', 'IZ0JNY K1JT FN20', 'IZ0JNY K1JT -15')."""
    out = []
    for line in text.splitlines():
        m = _ALL_NEW.match(line.strip()) or _ALL_OLD.match(line.strip())
        if not m:
            continue
        d, t, f, rxtx, mode, snr, dt, df, msg = m.groups()
        if rxtx != "Rx":
            continue
        try:
            ts = (datetime.strptime(d + t, "%y%m%d%H%M%S") if "-" not in d else
                  datetime.strptime(d + " " + t, "%Y-%m-%d %H:%M:%S")).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        w = msg.split()
        if not w:
            continue
        call = grid = None
        if w[0] == "CQ":
            rest = w[1:]
            if rest and not CALL_RX.match(rest[0]) and len(rest) > 1:      # CQ DX K1JT FN20 / CQ EME …
                rest = rest[1:]
            call = rest[0] if rest else None
            grid = rest[1] if len(rest) > 1 and LOC_RX.match(rest[1]) else None
        elif len(w) >= 2:
            call = w[1]
            grid = w[2] if len(w) > 2 and LOC_RX.match(w[2]) and w[2].upper() != "RR73" else None
        if not call or not CALL_RX.match(call.strip("<>")):
            continue
        fmhz = float(f) * (1000 if float(f) < 1000 else 1)
        out.append({"utc": ts, "call": call.strip("<>").upper(), "locator": grid.upper() if grid else None,
                    "freq_mhz": fmhz, "band": band_of(fmhz), "mode": mode, "snr_db": int(snr), "dt_s": float(dt),
                    "df_hz": int(df), "message": msg})
    return out


def eme_decodes(decodes: list[dict], known_eme: set[str] = frozenset()) -> list[dict]:
    """Only the decodes on the EME bands of EMELab (10 GHz and up), or of stations already known as EME (for a
    WSJT-X that shows the transverter IF instead of the real frequency): HF/VHF FT8 traffic in ALL.TXT stays out."""
    return [d for d in decodes if d.get("band") or d["call"] in known_eme]


def heard_summary(decodes: list[dict]) -> dict[str, dict]:
    """Per callsign: locator, bands, first/last time heard, number of decodes, best and median SNR."""
    import statistics
    by = {}
    for d in decodes:
        s = by.setdefault(d["call"], {"call": d["call"], "locator": None, "bands": set(), "first": d["utc"], "last": d["utc"],
                                      "n": 0, "snrs": [], "modes": set()})
        s["n"] += 1
        s["snrs"].append(d["snr_db"])
        s["first"] = min(s["first"], d["utc"])
        s["last"] = max(s["last"], d["utc"])
        if d["band"]:
            s["bands"].add(d["band"])
        s["modes"].add(d["mode"])
        if d["locator"] and len(d["locator"]) >= 4:
            s["locator"] = d["locator"]
    for s in by.values():
        s["snr_best"] = max(s["snrs"])
        s["snr_median"] = statistics.median(s["snrs"])
        del s["snrs"]
    return by


# ------------------------------------------------------------------ PA0PLY EME Directory (PDF per band)
_LOC_IN = re.compile(r"([A-R]{2}\d{2}[A-X]{2})")
_ANT = re.compile(r"(\d+(?:[.,]\d+)?\s*m\s*dish(?:\s*OS)?|\d+\s*x\s*\S+|[\w.,]+\s*(?:yagi|horn|array)s?)", re.I)


def parse_pa0ply(text: str, band: str) -> list[dict]:
    """Rows of one band of the EME Directory: callsign, locator, first name, antenna, power (W), web site.
    Works with columns separated by spaces or glued together by the PDF text extraction."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("eme stations", "call")):
            continue
        m = _LOC_IN.search(line)
        if not m or m.start() < 3:
            continue
        call = line[:m.start()].strip()
        if not CALL_RX.match(call):
            continue
        rest = line[m.end():]
        a = _ANT.search(rest)
        name = (rest[:a.start()] if a else rest.split("  ")[0]).strip()
        ant = a.group(1).strip() if a else ""
        after = rest[a.end():] if a else ""
        pw = re.match(r"\s*(\d+(?:[.,]\d+)?)", after)
        web = re.search(r"(https?://\S+|www\.\S+)", after)
        out.append({"call": call.upper(), "locator": m.group(1).upper(), "name": name, "antenna": ant,
                    "power_w": float(pw.group(1).replace(",", ".")) if pw else None, "web": web.group(1) if web else None,
                    "band": band, "source": "PA0PLY"})
    return out


PA0PLY_PAGE = "https://www.pa0ply.nl/eme-directory/"


def pa0ply_pdf_links(page_html: str) -> dict[str, str]:
    """Band → PDF link found on the EME Directory page (the file names change at every update)."""
    out = {}
    for u in re.findall(r'href=["\']([^"\']+\.pdf)["\']', page_html, re.I):
        n = u.rsplit("/", 1)[-1].lower()
        for key, b in (("10368", "10G"), ("10g", "10G"), ("24048", "24G"), ("24g", "24G"), ("47g", "47G"), ("76g", "76G")):
            if n.startswith(key):
                out[b] = u
    return out


def pdf_text(data: bytes) -> str:
    import io
    from pypdf import PdfReader
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in PdfReader(io.BytesIO(data)).pages)
