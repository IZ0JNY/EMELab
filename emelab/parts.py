# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Component library (LNA, SSPA, driver, mixer/transverter, waveguide, relay…) kept in EMELab's database with the
values read from the manufacturers' datasheets, and an optional search in the Mouser catalogue through its official
API with the user's own key (saved only on this PC). Values are never invented: each part carries its datasheet link.

A library entry with the same part number and maker as a device of EMELab's catalogue (catalog.py) is the user's
correction of that device: `devices()` shows it in place of the catalogue values, marked as verified by the user,
and `revert()` deletes it so the catalogue values come back."""
from __future__ import annotations

import json
import urllib.request

TYPES = {"lna": "LNA", "pa": "SSPA / PA", "twt": "TWT", "driver": "Driver", "mixer": "Mixer / transverter", "passive": "Guida, cavo, relè",
         "other": "Altro"}
SCHEMA = """CREATE TABLE IF NOT EXISTS parts (id INTEGER PRIMARY KEY AUTOINCREMENT, part TEXT, maker TEXT, type TEXT,
    f_lo_ghz REAL, f_hi_ghz REAL, gain_db REAL, nf_db REAL, p1db_dbm REAL, psat_dbm REAL, vdc REAL, idc_a REAL,
    datasheet TEXT, notes TEXT, UNIQUE(part, maker));"""
COLS = ["part", "maker", "type", "f_lo_ghz", "f_hi_ghz", "gain_db", "nf_db", "p1db_dbm", "psat_dbm", "vdc", "idc_a",
        "datasheet", "notes", "tech", "verified", "updated"]
_ADDED = {"tech": "TEXT", "verified": "INTEGER", "updated": "TEXT"}        # columns added after the first release
# catalogue type (catalog.TYPES) -> library type; a TWT saved before "twt" existed is a "pa"
KIND_TO_TYPE = {"PA": "pa", "LNA": "lna", "SW": "passive", "TWT": "twt", "TRV": "mixer"}
KIND_LIB_TYPES = {"PA": ("pa",), "LNA": ("lna",), "SW": ("passive",), "TWT": ("twt", "pa"), "TRV": ("mixer",)}
# editable numbers of a device: library column, catalogue key
NUM_FIELDS = [("f_lo_ghz", "f_lo"), ("f_hi_ghz", "f_hi"), ("gain_db", "gain_db"), ("nf_db", "nf_db"),
              ("p1db_dbm", "p1db_dbm"), ("psat_dbm", "psat_dbm"), ("vdc", "vdc"), ("idc_a", "idc_a")]


def ensure(D):
    D.con.executescript(SCHEMA)
    have = {r[1] for r in D.con.execute("PRAGMA table_info(parts)")}
    for col, typ in _ADDED.items():
        if col not in have:
            D.con.execute(f"ALTER TABLE parts ADD COLUMN {col} {typ}")
    D.con.commit()


def _key(part, maker) -> tuple[str, str]:
    return (str(part or "").strip().casefold(), str(maker or "").strip().casefold())


def save(D, **p):
    ensure(D)
    from datetime import datetime, timezone
    p.setdefault("updated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    keys = [k for k in COLS if k in p]
    D.con.execute(f"INSERT OR REPLACE INTO parts ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})", [p[k] for k in keys])
    D.con.commit()


def all_parts(D, f_ghz: float | None = None, kind: str | None = None) -> list[dict]:
    ensure(D)
    q, a = "SELECT * FROM parts WHERE 1=1", []
    if f_ghz:
        q += " AND (f_lo_ghz IS NULL OR f_lo_ghz <= ?) AND (f_hi_ghz IS NULL OR f_hi_ghz >= ?)"
        a += [f_ghz, f_ghz]
    if kind:
        q += " AND type = ?"
        a.append(kind)
    return [dict(r) for r in D.con.execute(q + " ORDER BY type, part", a)]


def delete(D, pid: int):
    D.con.execute("DELETE FROM parts WHERE id=?", (pid,))
    D.con.commit()


def find(D, part: str, maker: str) -> dict | None:
    """the library entry with this part number and maker (case and spaces ignored)"""
    ensure(D)
    k = _key(part, maker)
    return next((dict(r) for r in D.con.execute("SELECT * FROM parts") if _key(r["part"], r["maker"]) == k), None)


def revert(D, part: str, maker: str) -> bool:
    """delete the user's correction of a catalogue device (or the user's own device): True if something was deleted"""
    r = find(D, part, maker)
    if r:
        delete(D, r["id"])
    return bool(r)


def devices(D, band: float, kind: str) -> list[dict]:
    """Devices of one type for a band: EMELab's catalogue with the user's corrections applied, then the user's own
    devices. Each row has the catalogue keys (part, maker, f_lo, f_hi, gain_db, nf_db, psat_dbm, …) and
    origin = "catalog" | "edited" (catalogue device corrected by the user) | "mine" (the user's own device);
    edited and own devices carry verified=True and check=False."""
    from . import catalog
    ensure(D)
    lib = {_key(r["part"], r["maker"]): dict(r) for r in D.con.execute("SELECT * FROM parts")}
    cat_keys = {_key(d["part"], d["maker"]) for d in catalog.DEVICES}
    rows = []
    for d in catalog.DEVICES:
        if d["type"] != kind:
            continue
        mine = lib.get(_key(d["part"], d["maker"]))
        if mine is None:
            if catalog.in_band(d, band):
                rows.append(dict(d, origin="catalog", verified=False))
            continue
        r = dict(d, **{ck: mine.get(lk) for lk, ck in NUM_FIELDS})
        r.update(notes=mine.get("notes"), source=mine.get("datasheet") or d.get("source"), tech=mine.get("tech") or d.get("tech"),
                 check=False, origin="edited", verified=True, updated=mine.get("updated"), catalog=dict(d), id=mine["id"])
        if catalog.in_band(r, band):
            rows.append(r)
    for k, p in lib.items():
        if k in cat_keys or p.get("type") not in KIND_LIB_TYPES.get(kind, ()):
            continue
        r = {ck: p.get(lk) for lk, ck in NUM_FIELDS}
        r.update(part=p["part"], maker=p["maker"], type=kind, notes=p.get("notes"), source=p.get("datasheet"), tech=p.get("tech"),
                 check=False, origin="mine", verified=True, updated=p.get("updated"), id=p["id"])
        if catalog.in_band(r, band, margin=0.0):
            rows.append(r)
    return rows


def mouser_search(api_key: str, keyword: str, records: int = 25, timeout: float = 20.0) -> list[dict]:
    """Mouser Search API v1 (keyword): manufacturer, part number, description, datasheet link, availability, price."""
    from .net import _contexts
    body = json.dumps({"SearchByKeywordRequest": {"keyword": keyword, "records": records, "startingRecord": 0}}).encode()
    url = f"https://api.mouser.com/api/v1/search/keyword?apiKey={api_key}"
    err = None
    for _, ctx in _contexts():
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                js = json.loads(r.read())
            break
        except Exception as e:
            err = e
    else:
        raise err
    if js.get("Errors"):
        raise RuntimeError("; ".join(e.get("Message", "") for e in js["Errors"]))
    out = []
    for p in (js.get("SearchResults") or {}).get("Parts", []):
        pb = p.get("PriceBreaks") or []
        out.append({"maker": p.get("Manufacturer"), "part": p.get("ManufacturerPartNumber"), "description": p.get("Description"),
                    "datasheet": p.get("DataSheetUrl"), "availability": p.get("Availability"),
                    "price": f"{pb[0].get('Price')} ({pb[0].get('Quantity')} pz)" if pb else None, "mouser": p.get("ProductDetailUrl")})
    return out
