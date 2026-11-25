# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Component library (LNA, SSPA, driver, mixer/transverter, waveguide, relay…) kept in EME Assistant's database with the
values read from the manufacturers' datasheets, and an optional search in the Mouser catalogue through its official
API with the user's own key (saved only on this PC). Values are never invented: each part carries its datasheet link."""
from __future__ import annotations

import json
import urllib.request

TYPES = {"lna": "LNA", "pa": "SSPA / PA", "driver": "Driver", "mixer": "Mixer / transverter", "passive": "Guida, cavo, relè",
         "other": "Altro"}
SCHEMA = """CREATE TABLE IF NOT EXISTS parts (id INTEGER PRIMARY KEY AUTOINCREMENT, part TEXT, maker TEXT, type TEXT,
    f_lo_ghz REAL, f_hi_ghz REAL, gain_db REAL, nf_db REAL, p1db_dbm REAL, psat_dbm REAL, vdc REAL, idc_a REAL,
    datasheet TEXT, notes TEXT, UNIQUE(part, maker));"""
COLS = ["part", "maker", "type", "f_lo_ghz", "f_hi_ghz", "gain_db", "nf_db", "p1db_dbm", "psat_dbm", "vdc", "idc_a",
        "datasheet", "notes"]


def ensure(D):
    D.con.executescript(SCHEMA)


def save(D, **p):
    ensure(D)
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
