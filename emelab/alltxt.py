# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""WSJT-X ALL.TXT: every line WSJT-X decoded (Rx) or sent (Tx), read directly from the file and followed live.

ALL.TXT lives in the same folder as wsjtx_log.adi (File → Open log directory). EMELab reads it like «tail -f»: only
the lines appended since the last look (the position is kept in the EMELab settings), so nothing is read twice and
nothing is needed on the WSJT-X side. Only the lines on the EME bands of EMELab (10 GHz and up) are kept: the HF/VHF
FT8 traffic that usually fills ALL.TXT is skipped at once, before any parsing.

Kept lines go to the EMELab database (decodes, own transmissions); the statistics are computed from there: per band,
per station, per operating session, heard but not worked, SNR, DT and the audio offset (DF) with its drift, compared
with the Doppler expected from the Moon."""
from __future__ import annotations

import re
import statistics as _stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import stations, wsjtx_logfile

NAME = "ALL.TXT"
SESSION_GAP_MIN = 45          # more than this without Rx or Tx on a band: a new operating session begins
MIN_EME_MHZ = 10000.0         # 10 GHz

_NEW = re.compile(r"^(\d{6})_(\d{6})\s+([\d.]+)\s+(Rx|Tx)\s+(\S+)\s+(-?\d+)\s+(-?[\d.]+)\s+(-?\d+)\s+(.*)$")
_OLD = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([\d.]+)\s+(Rx|Tx)\s+(\S+)\s+(-?\d+)\s+(-?[\d.]+)\s+(-?\d+)\s+(.*)$")
# what WSJT-X appends after a Q65 message: decode depth / averaging («q3», «a2») and the «?» «*» marks
_TAIL = re.compile(r"(?:\s+(?:[aq]\d{1,2}|\*|\?|\^))+\s*$")


# ------------------------------------------------------------------ where the file is
def default_paths() -> list[Path]:
    """ALL.TXT next to every wsjtx_log.adi EMELab knows about (main WSJT-X first, then --rig-name instances, JTDX)."""
    return [p.with_name(NAME) for p in wsjtx_logfile.default_paths()]


def find_default() -> Path | None:
    found = [p for p in default_paths() if p.is_file()]
    if not found:
        return None
    try:
        return max(found, key=lambda p: p.stat().st_mtime)
    except OSError:
        return found[0]


def clean_path(text: str) -> str:
    """As typed or pasted: quotes removed, a folder becomes the ALL.TXT inside it, %LOCALAPPDATA% and ~ expanded."""
    p = (text or "").strip().strip('"').strip("'").strip()
    if not p:
        return ""
    import os
    p = os.path.expanduser(os.path.expandvars(p))
    if Path(p).is_dir():
        p = str(Path(p) / NAME)
    return p


# ------------------------------------------------------------------ one line
def _freq_mhz(line: str) -> float | None:
    """Dial frequency of a line without the full parse (the fast filter): second field, or third in the old format."""
    f = line.split(None, 3)
    try:
        x = float(f[2] if len(f) > 2 and "-" in f[0] else f[1])
    except (IndexError, ValueError):
        return None
    return x                                    # ALL.TXT always writes the dial frequency in MHz


def parse_line(line: str) -> dict | None:
    """One ALL.TXT line → {utc, rxtx, freq_mhz, band, mode, snr_db, dt_s, df_hz, message, call, locator}.
    For Rx «call» is who transmitted; for Tx it is who I was calling (None for my CQ)."""
    s = line.strip()
    m = _NEW.match(s) or _OLD.match(s)
    if not m:
        return None
    d, t, f, rxtx, mode, snr, dt, df, msg = m.groups()
    try:
        ts = (datetime.strptime(d + t, "%y%m%d%H%M%S") if "-" not in d else
              datetime.strptime(d + " " + t, "%Y-%m-%d %H:%M:%S")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    msg = _TAIL.sub("", msg).strip()
    fmhz = float(f)
    w = msg.replace("<", "").replace(">", "").split()
    call = grid = None
    if rxtx == "Rx":
        if w and w[0] in ("CQ", "QRZ", "DE"):
            rest = w[1:]
            if len(rest) > 1 and not stations.CALL_RX.match(rest[0]):        # CQ EME K1JT FN20
                rest = rest[1:]
            call = rest[0] if rest else None
            grid = rest[1] if len(rest) > 1 else None
        elif len(w) >= 2:
            call = w[1]
            grid = w[2] if len(w) > 2 else None
    else:
        call = None if (w and w[0] == "CQ") else (w[0] if w else None)
    if call and not stations.CALL_RX.match(call):
        call = None
    if grid and (not stations.LOC_RX.match(grid) or grid.upper() == "RR73"):
        grid = None
    return {"utc": ts, "rxtx": rxtx, "freq_mhz": fmhz, "band": stations.band_of(fmhz), "mode": mode,
            "snr_db": int(snr), "dt_s": float(dt), "df_hz": int(df), "message": msg,
            "call": call.upper() if call else None, "locator": grid.upper() if grid else None}


def parse_eme(lines) -> list[dict]:
    """Only the lines on the EMELab bands (10 GHz and up); the rest is dropped before the regular expression."""
    out = []
    for line in lines:
        f = _freq_mhz(line)
        if f is None or f < MIN_EME_MHZ:
            continue
        d = parse_line(line)
        if d and d["band"]:
            out.append(d)
    return out


# ------------------------------------------------------------------ following the file
class LineTail:
    """Complete lines appended to a text file since the last call (a line still being written waits)."""

    def __init__(self, path, offset: int | None = None):
        self.path = Path(path)
        self.offset = offset            # None: start from the end (only what WSJT-X writes from now on)

    def size(self) -> int | None:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def read_new(self, max_bytes: int = 8 << 20) -> list[str]:
        size = self.size()
        if size is None:
            return []
        if self.offset is None:
            self.offset = size
            return []
        if size < self.offset:          # file emptied or replaced (WSJT-X: «Erase ALL.TXT»)
            self.offset = 0
        if size == self.offset:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            chunk = f.read(min(size - self.offset, max_bytes))
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        done = chunk[:end + 1]
        self.offset += len(done)
        return done.decode("utf-8", "replace").splitlines()

    @property
    def behind(self) -> int:
        """Bytes still to read (a long history being read for the first time)."""
        size = self.size()
        return max(0, size - self.offset) if size is not None and self.offset is not None else 0


# ------------------------------------------------------------------ into the database
def store(D, rows: list[dict], source: str = NAME) -> dict:
    """Decodes and own transmissions into the database (duplicates skipped); the «heard» summary of every station
    involved is rebuilt from all the decodes in the database, so reading the same file twice changes nothing."""
    rx = [r for r in rows if r["rxtx"] == "Rx"]
    tx = [r for r in rows if r["rxtx"] == "Tx"]
    new_rx = D.add_decodes([{"utc": r["utc"], "call": r["call"], "grid": r["locator"], "snr": r["snr_db"], "dt": r["dt_s"],
                             "df": r["df_hz"], "mode": r["mode"], "message": r["message"], "band": r["band"],
                             "dial_mhz": r["freq_mhz"], "client": source} for r in rx])
    new_tx = D.add_tx_lines([{"utc": r["utc"], "call": r["call"], "mode": r["mode"], "message": r["message"],
                              "band": r["band"], "dial_mhz": r["freq_mhz"], "df": r["df_hz"]} for r in tx])
    calls = sorted({r["call"] for r in rx if r["call"]})
    if calls:
        refresh_heard(D, calls)
    return {"rx": len(rx), "tx": len(tx), "new_rx": new_rx, "new_tx": new_tx, "calls": calls}


def refresh_heard(D, calls):
    """Rebuild data.heard of the stations (Stazioni EME: Sentito, SNR migliore, Bande sentite…) from the decodes."""
    by = {}
    for r in D.eme_decodes(calls=list(calls)):
        by.setdefault(r["call"], []).append(r)
    for call, rs in by.items():
        snrs = [r["snr"] for r in rs if r["snr"] is not None]
        dts = [r["dt"] for r in rs if r["dt"] is not None]
        grid = next((r["grid"] for r in sorted(rs, key=lambda r: r["utc"], reverse=True)
                     if r["grid"] and len(r["grid"]) >= 4), None)
        heard = {"n": len(rs), "first": min(r["utc"] for r in rs), "last": max(r["utc"] for r in rs),
                 "snr_best": max(snrs) if snrs else None, "snr_median": _stat.median(snrs) if snrs else None,
                 "snr_mean": round(_stat.fmean(snrs), 1) if snrs else None,
                 "dt_mean": round(_stat.fmean(dts), 2) if dts else None,
                 "bands": sorted({r["band"] for r in rs if r["band"]}, key=_band_order),
                 "modes": sorted({r["mode"] for r in rs if r["mode"]})}
        have = ((D.station_of(call) or {}).get("locator") or "")
        D.upsert_station(call, locator=grid if grid and len(grid) > len(have) else None, eme=1,   # never less precise
                         data={"heard": heard})
    D.commit()


def _band_order(b):
    order = list(stations.BANDS_MHZ)
    return (order.index(b) if b in order else len(order), str(b))


# ------------------------------------------------------------------ statistics
def _t(x) -> datetime:
    if isinstance(x, datetime):
        return x
    return datetime.strptime(str(x).replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _slope_hz_per_min(pts) -> float | None:
    """Least-squares DF drift (Hz/min) of one station in one session; None with fewer than 3 decodes or < 3 min."""
    if len(pts) < 3:
        return None
    t0 = pts[0][0]
    xs = [(t - t0).total_seconds() / 60 for t, _ in pts]
    if xs[-1] - xs[0] < 3:
        return None
    ys = [y for _, y in pts]
    mx, my = _stat.fmean(xs), _stat.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else None


def sessions(rx: list[dict], tx: list[dict], gap_min: float = SESSION_GAP_MIN) -> list[dict]:
    """Operating sessions per band: Rx and Tx lines with no pause longer than gap_min minutes."""
    ev = sorted([(_t(r["utc"]), r["band"], "rx", r) for r in rx] + [(_t(r["utc"]), r["band"], "tx", r) for r in tx],
                key=lambda e: e[0])
    open_, out = {}, []
    for t, b, kind, r in ev:
        s = open_.get(b)
        if s is None or (t - s["end"]).total_seconds() > gap_min * 60:
            s = {"band": b, "start": t, "end": t, "rx": [], "tx": []}
            open_[b] = s
            out.append(s)
        s["end"] = t
        s[kind].append(r)
    for s in out:
        snrs = [r["snr"] for r in s["rx"] if r.get("snr") is not None]
        s["calls"] = sorted({r["call"] for r in s["rx"] if r.get("call")})
        s["n_rx"], s["n_tx"] = len(s["rx"]), len(s["tx"])
        s["snr_best"] = max(snrs) if snrs else None
        s["minutes"] = round((s["end"] - s["start"]).total_seconds() / 60) + 1
    return out


def summarize(rx: list[dict], tx: list[dict], qsos: list[dict] = (), my_call: str | None = None,
              doppler_fn=None) -> dict:
    """All the statistics of the decodes (database rows: utc, call, grid, snr, dt, df, mode, message, band).

    qsos: the EMELab log, for «worked» and «heard but not worked»; doppler_fn(call, grid, band, utc) → expected
    Doppler in Hz (or None), compared with the measured DF."""
    my = (my_call or "").upper()
    worked = {(q["call"].upper(), q.get("band")) for q in qsos if q.get("call")}
    ses = sessions(rx, tx)
    out = {"n_rx": len(rx), "n_tx": len(tx), "sessions": ses, "bands": {}, "stations": [], "by_hour": {}}
    # per band
    for b in sorted({r["band"] for r in rx} | {r["band"] for r in tx}, key=_band_order):
        rb = [r for r in rx if r["band"] == b]
        snrs = [r["snr"] for r in rb if r["snr"] is not None]
        dts = [r["dt"] for r in rb if r["dt"] is not None]
        sb = [s for s in ses if s["band"] == b]
        out["bands"][b] = {"n_rx": len(rb), "n_tx": sum(1 for r in tx if r["band"] == b),
                           "stations": len({r["call"] for r in rb if r["call"]}),
                           "snr_best": max(snrs) if snrs else None, "snr_mean": _stat.fmean(snrs) if snrs else None,
                           "dt_mean": _stat.fmean(dts) if dts else None, "sessions": len(sb),
                           "hours": sum(s["minutes"] for s in sb) / 60,
                           "first": min((_t(r["utc"]) for r in rb), default=None),
                           "last": max((_t(r["utc"]) for r in rb), default=None)}
        hours = [0] * 24
        for r in rb:
            hours[_t(r["utc"]).hour] += 1
        out["by_hour"][b] = hours
    # per station and band
    by = {}
    for r in rx:
        if r["call"]:
            by.setdefault((r["call"], r["band"]), []).append(r)
    for (call, b), rs in sorted(by.items(), key=lambda kv: (_band_order(kv[0][1]), -len(kv[1]), kv[0][0])):
        rs = sorted(rs, key=lambda r: _t(r["utc"]))
        snrs = [r["snr"] for r in rs if r["snr"] is not None]
        dts = [r["dt"] for r in rs if r["dt"] is not None]
        dfs = [r["df"] for r in rs if r["df"] is not None]
        grid = next((r["grid"] for r in reversed(rs) if r.get("grid")), None)
        drifts = []
        for s in ses:
            if s["band"] == b:
                pts = [(_t(r["utc"]), r["df"]) for r in s["rx"] if r.get("call") == call and r.get("df") is not None]
                k = _slope_hz_per_min(pts)
                if k is not None:
                    drifts.append(k)
        n_ses = sum(1 for s in ses if s["band"] == b and call in s["calls"])
        dop = None
        if doppler_fn is not None:
            try:
                dop = doppler_fn(call, grid, b, _t(rs[-1]["utc"]))
            except Exception:
                dop = None
        out["stations"].append({
            "call": call, "band": b, "locator": grid, "n": len(rs), "first": _t(rs[0]["utc"]), "last": _t(rs[-1]["utc"]),
            "snr_best": max(snrs) if snrs else None, "snr_mean": _stat.fmean(snrs) if snrs else None,
            "snr_median": _stat.median(snrs) if snrs else None, "snr_worst": min(snrs) if snrs else None,
            "dt_mean": _stat.fmean(dts) if dts else None, "dt_min": min(dts) if dts else None,
            "dt_max": max(dts) if dts else None, "df_mean": _stat.fmean(dfs) if dfs else None,
            "df_min": min(dfs) if dfs else None, "df_max": max(dfs) if dfs else None,
            "df_drift": _stat.median(drifts) if drifts else None, "doppler_hz": dop, "sessions": n_ses,
            "to_me": sum(1 for r in rs if my and (r.get("message") or "").upper().split()[:1] == [my]),
            "cq": sum(1 for r in rs if (r.get("message") or "").upper().startswith("CQ")),
            "worked": (call, b) in worked})
    out["heard_not_worked"] = [s for s in out["stations"] if not s["worked"]]
    for s in ses:
        s["worked"] = sorted(q["call"] for q in qsos if q.get("band") == s["band"] and q.get("utc") is not None
                             and s["start"] - timedelta(minutes=5) <= _t(q["utc"]) <= s["end"] + timedelta(minutes=5))
    return out
