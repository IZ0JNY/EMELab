# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Local EMELab database (SQLite) in the user settings folder: station, setups per band and measurements.

Nothing here is ever uploaded: the file stays on this computer (export/import as CSV). Every time is stored
as ISO 8601 UTC ("2026-11-24T22:15:00Z")."""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

KINDS = {
    "sun": "Rumore solare (Y sole / cielo freddo)",
    "moon": "Rumore lunare (Y luna / cielo freddo)",
    "cold_sky": "Cielo freddo (riferimento)",
    "ground": "Terra / orizzonte (Y terra / cielo freddo)",
    "echo": "Eco proprie (SNR)",
    "beacon": "Beacon / segnale di un'altra stazione",
    "qso": "QSO / tentativo",
    "focus": "Messa a fuoco (spostamento del feed)",
    "other": "Altro",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS station (id INTEGER PRIMARY KEY CHECK (id = 1), callsign TEXT, locator TEXT,
    lat REAL, lon REAL, height_m REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS setups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, band_ghz REAL, created_utc TEXT,
    data TEXT);
CREATE TABLE IF NOT EXISTS measurements (id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL, setup_id INTEGER,
    band_ghz REAL, kind TEXT, y_db REAL, snr_db REAL, value REAL, unit TEXT, az_read REAL, el_read REAL,
    az_off REAL, el_off REAL, partner TEXT, notes TEXT,
    t_c REAL, rh REAL, p_hpa REAL, wind_ms REAL, rain_mmh REAL, cloud_pct REAL, wx_utc TEXT, wx_source TEXT,
    calc TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS m_utc ON measurements(utc);
CREATE TABLE IF NOT EXISTS stations (call TEXT PRIMARY KEY, locator TEXT, name TEXT, qth TEXT, address TEXT,
    country TEXT, email TEXT, eme INTEGER, data TEXT, updated_utc TEXT);
CREATE TABLE IF NOT EXISTS qsos (id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL, call TEXT NOT NULL, band TEXT,
    freq_mhz REAL, mode TEXT, submode TEXT, rst_sent TEXT, rst_rcvd TEXT, locator TEXT, my_locator TEXT, name TEXT,
    qth TEXT, tx_pwr TEXT, setup_id INTEGER, comment TEXT, qsl_sent TEXT, qsl_rcvd TEXT, t_c REAL, rh REAL,
    p_hpa REAL, wx_source TEXT, calc TEXT, adif TEXT, UNIQUE(utc, call, band));
CREATE INDEX IF NOT EXISTS q_utc ON qsos(utc);
CREATE TABLE IF NOT EXISTS decodes (id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL, call TEXT, grid TEXT,
    snr INTEGER, dt REAL, df INTEGER, mode TEXT, message TEXT, band TEXT, dial_mhz REAL, client TEXT,
    UNIQUE(utc, message, df));
CREATE INDEX IF NOT EXISTS d_utc ON decodes(utc);
CREATE TABLE IF NOT EXISTS setup_history (id INTEGER PRIMARY KEY AUTOINCREMENT, band TEXT NOT NULL, from_utc TEXT NOT NULL,
    dish_m REAL, dish_kind TEXT, eta REAL, power_w REAL, nf_db REAL, line_loss_db REAL, pol TEXT, notes TEXT);
"""
QSO_COLS = ["id", "utc", "call", "band", "freq_mhz", "mode", "submode", "rst_sent", "rst_rcvd", "locator", "my_locator",
            "name", "qth", "tx_pwr", "setup_id", "comment", "qsl_sent", "qsl_rcvd", "t_c", "rh", "p_hpa", "wx_source",
            "calc", "adif"]

COLS = ["id", "utc", "setup_id", "band_ghz", "kind", "y_db", "snr_db", "value", "unit", "az_read", "el_read", "az_off",
        "el_off", "partner", "notes", "t_c", "rh", "p_hpa", "wind_ms", "rain_mmh", "cloud_pct", "wx_utc", "wx_source",
        "calc", "extra"]


def iso_utc(dt: datetime) -> str:
    d = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def default_path() -> Path:
    from .settings import config_dir
    return config_dir() / "emelab.sqlite"


class DB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)   # Streamlit reruns on other threads
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    # station ---------------------------------------------------------------
    def station(self) -> dict:
        r = self.con.execute("SELECT * FROM station WHERE id = 1").fetchone()
        return dict(r) if r else {}

    def save_station(self, **kw):
        cur = {**self.station(), **kw, "id": 1}
        keys = ["id", "callsign", "locator", "lat", "lon", "height_m", "notes"]
        self.con.execute(f"INSERT OR REPLACE INTO station ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                         [cur.get(k) for k in keys])
        self.con.commit()

    # setups ----------------------------------------------------------------
    def setups(self, band: float | None = None) -> list[dict]:
        q = "SELECT * FROM setups" + (" WHERE abs(band_ghz - ?) < 1" if band else "") + " ORDER BY band_ghz, id"
        rows = self.con.execute(q, (band,) if band else ()).fetchall()
        return [{**dict(r), **json.loads(r["data"] or "{}")} for r in rows]

    def save_setup(self, name: str, band_ghz: float, data: dict, setup_id: int | None = None) -> int:
        js = json.dumps(data)
        if setup_id:
            self.con.execute("UPDATE setups SET name=?, band_ghz=?, data=? WHERE id=?", (name, band_ghz, js, setup_id))
        else:
            cur = self.con.execute("INSERT INTO setups (name, band_ghz, created_utc, data) VALUES (?,?,?,?)",
                                   (name, band_ghz, iso_utc(datetime.now(timezone.utc)), js))
            setup_id = cur.lastrowid
        self.con.commit()
        return int(setup_id)

    def delete_setup(self, setup_id: int):
        self.con.execute("DELETE FROM setups WHERE id=?", (setup_id,))
        self.con.commit()

    # measurements ------------------------------------------------------------
    def add(self, **m) -> int:
        m = dict(m)
        if isinstance(m.get("utc"), datetime):
            m["utc"] = iso_utc(m["utc"])
        for k in ("calc", "extra"):
            if isinstance(m.get(k), dict):
                m[k] = json.dumps(m[k])
        keys = [k for k in COLS if k != "id" and k in m]
        cur = self.con.execute(f"INSERT INTO measurements ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                               [m[k] for k in keys])
        self.con.commit()
        return int(cur.lastrowid)

    def update(self, mid: int, **m):
        for k in ("calc", "extra"):
            if isinstance(m.get(k), dict):
                m[k] = json.dumps(m[k])
        keys = [k for k in m if k in COLS and k != "id"]
        self.con.execute(f"UPDATE measurements SET {','.join(k + '=?' for k in keys)} WHERE id=?",
                         [m[k] for k in keys] + [mid])
        self.con.commit()

    def delete(self, mid: int):
        self.con.execute("DELETE FROM measurements WHERE id=?", (mid,))
        self.con.commit()

    def measurements(self, band: float | None = None, kind: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM measurements WHERE 1=1", []
        if band:
            q += " AND abs(band_ghz - ?) < 1"
            a.append(band)
        if kind:
            q += " AND kind = ?"
            a.append(kind)
        rows = self.con.execute(q + " ORDER BY utc", a).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("calc", "extra"):
                d[k] = json.loads(d[k]) if d.get(k) else {}
            out.append(d)
        return out

    # stations --------------------------------------------------------------------
    def upsert_station(self, call: str, **kw):
        """Merge what a source knows about a station (data: bands, antenna, power, heard… as JSON)."""
        call = call.upper()
        cur = self.station_of(call) or {"call": call, "data": {}}
        data = {**cur.get("data", {}), **(kw.pop("data", None) or {})}
        row = {**{k: v for k, v in cur.items() if k != "data"}, **{k: v for k, v in kw.items() if v not in (None, "")}}
        row.update(call=call, data=json.dumps(data, default=str), updated_utc=iso_utc(datetime.now(timezone.utc)))
        keys = ["call", "locator", "name", "qth", "address", "country", "email", "eme", "data", "updated_utc"]
        self.con.execute(f"INSERT OR REPLACE INTO stations ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                         [row.get(k) for k in keys])

    def commit(self):
        self.con.commit()

    def station_of(self, call: str) -> dict | None:
        r = self.con.execute("SELECT * FROM stations WHERE call = ?", (call.upper(),)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["data"] = json.loads(d["data"] or "{}")
        return d

    def stations(self) -> list[dict]:
        out = []
        for r in self.con.execute("SELECT * FROM stations ORDER BY call"):
            d = dict(r)
            d["data"] = json.loads(d["data"] or "{}")
            out.append(d)
        return out

    # QSOs -----------------------------------------------------------------------
    def add_qso(self, **q) -> int | None:
        q = dict(q)
        if isinstance(q.get("utc"), datetime):
            q["utc"] = iso_utc(q["utc"])
        for k in ("calc", "adif"):
            if isinstance(q.get(k), dict):
                q[k] = json.dumps(q[k], default=str)
        keys = [k for k in QSO_COLS if k != "id" and k in q]
        cur = self.con.execute(f"INSERT OR IGNORE INTO qsos ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                               [q[k] for k in keys])
        self.con.commit()
        return int(cur.lastrowid) if cur.rowcount else None

    def update_qso(self, qid: int, **q):
        for k in ("calc", "adif"):
            if isinstance(q.get(k), dict):
                q[k] = json.dumps(q[k], default=str)
        keys = [k for k in q if k in QSO_COLS and k != "id"]
        self.con.execute(f"UPDATE qsos SET {','.join(k + '=?' for k in keys)} WHERE id=?", [q[k] for k in keys] + [qid])
        self.con.commit()

    def delete_qso(self, qid: int):
        self.con.execute("DELETE FROM qsos WHERE id=?", (qid,))
        self.con.commit()

    def qsos(self, band: str | None = None, call: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM qsos WHERE 1=1", []
        if band:
            q += " AND band = ?"
            a.append(band)
        if call:
            q += " AND call = ?"
            a.append(call.upper())
        out = []
        for r in self.con.execute(q + " ORDER BY utc", a):
            d = dict(r)
            for k in ("calc", "adif"):
                d[k] = json.loads(d[k]) if d.get(k) else {}
            d["utc"] = parse_utc(d["utc"])
            out.append(d)
        return out

    # CSV ----------------------------------------------------------------------
    # decodes received live from WSJT-X ---------------------------------------
    def add_decode(self, **d) -> bool:
        keys = ["utc", "call", "grid", "snr", "dt", "df", "mode", "message", "band", "dial_mhz", "client"]
        if isinstance(d.get("utc"), datetime):
            d["utc"] = iso_utc(d["utc"])
        cur = self.con.execute(f"INSERT OR IGNORE INTO decodes ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                               [d.get(k) for k in keys])
        self.con.commit()
        return bool(cur.rowcount)

    def decodes(self, since: str | None = None, call: str | None = None, limit: int = 500) -> list[dict]:
        q, a = "SELECT * FROM decodes WHERE 1=1", []
        if since:
            q += " AND utc >= ?"
            a.append(since)
        if call:
            q += " AND call = ?"
            a.append(call.upper())
        return [dict(r) for r in self.con.execute(q + " ORDER BY utc DESC LIMIT ?", a + [limit])]

    # station history (what was used on each band, from which date) -----------------
    HIST_COLS = ["band", "from_utc", "dish_m", "dish_kind", "eta", "power_w", "nf_db", "line_loss_db", "pol", "notes"]

    def history(self, band: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM setup_history", []
        if band:
            q += " WHERE band = ?"
            a.append(band)
        return [dict(r) for r in self.con.execute(q + " ORDER BY band, from_utc", a)]

    def save_history(self, band: str, rows: list[dict]):
        """Replace the history of one band with these periods (each valid from its date to the next one)."""
        self.con.execute("DELETE FROM setup_history WHERE band = ?", (band,))
        for r in rows:
            r = {**r, "band": band}
            if isinstance(r.get("from_utc"), datetime):
                r["from_utc"] = iso_utc(r["from_utc"])
            keys = [k for k in self.HIST_COLS if r.get(k) not in (None, "")]
            self.con.execute(f"INSERT INTO setup_history ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                             [r[k] for k in keys])
        self.con.commit()

    def setup_at(self, band: str, t: datetime) -> dict | None:
        """The station period in force on band at time t (latest period that started before t)."""
        t = iso_utc(t) if isinstance(t, datetime) else str(t)
        r = self.con.execute("SELECT * FROM setup_history WHERE band = ? AND from_utc <= ? ORDER BY from_utc DESC LIMIT 1",
                             (band, t)).fetchone()
        return dict(r) if r else None

    def export_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(COLS)
        for r in self.con.execute("SELECT * FROM measurements ORDER BY utc"):
            w.writerow([r[k] for k in COLS])
        return buf.getvalue()

    def import_csv(self, text: str) -> int:
        n = 0
        for row in csv.DictReader(io.StringIO(text)):
            m = {k: (row.get(k) if row.get(k) not in ("", None) else None) for k in COLS if k != "id"}
            if not m.get("utc"):
                continue
            for k in ("band_ghz", "y_db", "snr_db", "value", "az_read", "el_read", "az_off", "el_off", "t_c", "rh",
                      "p_hpa", "wind_ms", "rain_mmh", "cloud_pct"):
                if m.get(k) is not None:
                    m[k] = float(m[k])
            self.add(**m)
            n += 1
        return n
