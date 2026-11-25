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
CREATE INDEX IF NOT EXISTS d_call ON decodes(call);
CREATE TABLE IF NOT EXISTS tx_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL, call TEXT, mode TEXT,
    message TEXT, band TEXT, dial_mhz REAL, df INTEGER, UNIQUE(utc, message));
CREATE TABLE IF NOT EXISTS setup_history (id INTEGER PRIMARY KEY AUTOINCREMENT, band TEXT NOT NULL, from_utc TEXT NOT NULL,
    dish_m REAL, dish_kind TEXT, eta REAL, power_w REAL, nf_db REAL, line_loss_db REAL, pol TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS station_imports (id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL, source TEXT NOT NULL,
    label TEXT, n INTEGER);
CREATE TABLE IF NOT EXISTS qso_imports (id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL, label TEXT,
    ids TEXT);
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
        for k, v in (data.get("manual") or {}).items():       # corrections made by hand win over every import
            if k in self.MANUAL_FIELDS:
                if kw.get(k) not in (None, ""):
                    data.setdefault("orig", {})[k] = kw[k]
                row[k] = v
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

    # where the station data came from, and how to take it away again ------------------
    # data keys written by each source: "call3" (CALL3.TXT), "heard" (ALL.TXT and live WSJT-X decodes),
    # "directory" {band: …} (EME Directory PA0PLY), "qrz" (QRZ.com, which also fills name/address/QTH/country).
    QRZ_FIELDS = ("address", "qth", "country", "email")

    @staticmethod
    def _station_sources(data: dict) -> list[str]:
        out = []
        if data.get("call3"):
            out.append("call3")
        if data.get("heard"):
            out.append("heard")
        out += [f"directory:{b}" for b in sorted(data.get("directory") or {})]
        if data.get("qrz"):
            out.append("qrz")
        if data.get("manual"):
            out.append("manual")
        return out

    # corrections made by hand ------------------------------------------------------
    # data["manual"] = {"locator"/"name"/"qth": value, "bands": {band: {"antenna", "power_w"}}}; data["orig"] keeps the
    # imported value of a corrected field, so that taking the correction away gives it back.
    MANUAL_FIELDS = ("locator", "name", "qth")

    @staticmethod
    def directory_of(data: dict) -> dict:
        """Station per band: the EME Directory, with the bands corrected by hand on top."""
        out = {b: dict(v) for b, v in (data.get("directory") or {}).items()}
        for b, v in ((data.get("manual") or {}).get("bands") or {}).items():
            out[b] = {**out.get(b, {}), **v}
        return out

    def set_station_manual(self, call: str, fields: dict | None = None, bands: dict | None = None):
        """Correct fields by hand. A blank value takes the correction away (the imported value comes back);
        bands: {band: {"antenna": …, "power_w": …}} or {band: None} to take that band's correction away."""
        call = call.upper()
        cur = self.station_of(call) or {"call": call, "data": {}}
        data = cur["data"]
        man, orig = dict(data.get("manual") or {}), dict(data.get("orig") or {})
        row = {k: cur.get(k) for k in self.MANUAL_FIELDS}
        for k, v in (fields or {}).items():
            if k not in self.MANUAL_FIELDS:
                continue
            v = (v or "").strip() or None
            if v is None:
                if k in man:
                    man.pop(k)
                    row[k] = orig.pop(k, None)
                continue
            if k not in man:
                orig[k] = cur.get(k)
            man[k] = v
            row[k] = v
        mb = dict(man.get("bands") or {})
        for b, v in (bands or {}).items():
            if v:
                mb[b] = {"antenna": (v.get("antenna") or "").strip(), "power_w": v.get("power_w")}
            else:
                mb.pop(b, None)
        if mb:
            man["bands"] = mb
        else:
            man.pop("bands", None)
        for k, v in (("manual", man), ("orig", orig)):
            if v:
                data[k] = v
            else:
                data.pop(k, None)
        if cur.get("updated_utc") is None and not man:
            return
        self.con.execute("INSERT OR REPLACE INTO stations (call, locator, name, qth, address, country, email, eme, data, "
                         "updated_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         [call, row["locator"], row["name"], row["qth"], cur.get("address"), cur.get("country"),
                          cur.get("email"), cur.get("eme"), json.dumps(data, default=str),
                          iso_utc(datetime.now(timezone.utc))])
        if not self._station_sources(data):
            self.con.execute("DELETE FROM stations WHERE call = ?", (call,))
        self.con.commit()

    def eme_10g_calls(self) -> set[str]:
        """Stations with evidence of EME from 10 GHz up: a band in the EME Directory (or corrected by hand), heard on
        10 GHz and up (ALL.TXT, live WSJT-X), or a QSO in the log on 10 GHz and up."""
        out = set()
        for s in self.stations():
            d = s["data"]
            if self.directory_of(d) or (d.get("heard") or {}).get("bands"):
                out.add(s["call"])
        bands = ("10G", "24G", "47G", "76G", "122G", "134G")
        out |= {r[0] for r in self.con.execute(
            f"SELECT DISTINCT call FROM qsos WHERE band IN ({','.join('?' * len(bands))})", bands)}
        return out

    def log_station_import(self, source: str, label: str, n: int):
        self.con.execute("INSERT INTO station_imports (utc, source, label, n) VALUES (?,?,?,?)",
                         (iso_utc(datetime.now(timezone.utc)), source, label, int(n)))
        self.con.commit()

    def station_imports(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM station_imports ORDER BY utc DESC, id DESC")]

    def station_source_counts(self) -> dict[str, int]:
        """Source key ("call3", "heard", "directory:10G", "qrz") → number of stations holding data from it."""
        out: dict[str, int] = {}
        for s in self.stations():
            for k in self._station_sources(s["data"]):
                out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))

    def remove_station_source(self, source: str) -> tuple[int, int]:
        """Take away everything a source brought; a station left with no source at all is deleted.
        Returns (stations changed, stations deleted)."""
        band = source.split(":", 1)[1] if source.startswith("directory:") else None
        changed = deleted = 0
        for s in self.stations():
            data = s["data"]
            if source not in self._station_sources(data):
                continue
            if source == "manual":
                orig = data.pop("orig", {})
                for k in data.pop("manual", {}):
                    if k in self.MANUAL_FIELDS:
                        s[k] = orig.get(k)
            elif band:
                dirb = dict(data.get("directory") or {})
                dirb.pop(band, None)
                if dirb:
                    data["directory"] = dirb
                else:
                    data.pop("directory", None)
            else:
                data.pop(source, None)
            if not self._station_sources(data):
                self.con.execute("DELETE FROM stations WHERE call = ?", (s["call"],))
                deleted += 1
                continue
            row = {k: s.get(k) for k in ("locator", "name", "qth", "address", "country", "email", "eme")}
            if source == "qrz":
                for k in self.QRZ_FIELDS:
                    row[k] = None
                row["name"] = next((v.get("name") for v in (data.get("directory") or {}).values() if v.get("name")), None)
            elif band and not data.get("qrz") and not data.get("directory"):
                row["name"] = None                                   # the name came only from the directory
            for k, v in (data.get("manual") or {}).items():          # a correction by hand stays
                if k in self.MANUAL_FIELDS:
                    if row[k] != s.get(k):                           # the imported value under it changed
                        data.setdefault("orig", {})[k] = row[k]
                    row[k] = v
            self.con.execute("UPDATE stations SET locator=?, name=?, qth=?, address=?, country=?, email=?, eme=?, data=?, "
                             "updated_utc=? WHERE call=?",
                             [row["locator"], row["name"], row["qth"], row["address"], row["country"], row["email"],
                              row["eme"], json.dumps(data, default=str), iso_utc(datetime.now(timezone.utc)), s["call"]])
            changed += 1
        if source == "heard":                       # the decodes and Tx lines the heard summaries came from
            self.con.execute("DELETE FROM decodes")
            self.con.execute("DELETE FROM tx_lines")
        self.con.execute("DELETE FROM station_imports WHERE source = ?", (source,))
        self.con.commit()
        return changed, deleted

    def delete_stations(self, calls: list[str]) -> int:
        n = 0
        for c in calls:
            n += self.con.execute("DELETE FROM stations WHERE call = ?", (c.upper(),)).rowcount
        self.con.commit()
        return n

    def clear_stations(self) -> int:
        n = self.con.execute("DELETE FROM stations").rowcount
        self.con.execute("DELETE FROM station_imports")
        self.con.commit()
        return n

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

    def qso_near(self, call: str, band: str | None, utc: datetime, minutes: float = 10) -> dict | None:
        """A QSO already in the log with the same call and band within ± minutes (the same QSO from another source:
        WSJT-X over UDP, its log file, an ADIF export of another logger with or without the seconds)."""
        from datetime import timedelta
        a, b = iso_utc(utc - timedelta(minutes=minutes)), iso_utc(utc + timedelta(minutes=minutes))
        r = self.con.execute("SELECT id, utc FROM qsos WHERE call = ? AND IFNULL(band, '') = IFNULL(?, '') AND utc BETWEEN ? AND ? "
                             "LIMIT 1", (call.upper(), band, a, b)).fetchone()
        return dict(r) if r else None

    def update_qso(self, qid: int, **q):
        for k in ("calc", "adif"):
            if isinstance(q.get(k), dict):
                q[k] = json.dumps(q[k], default=str)
        keys = [k for k in q if k in QSO_COLS and k != "id"]
        self.con.execute(f"UPDATE qsos SET {','.join(k + '=?' for k in keys)} WHERE id=?", [q[k] for k in keys] + [qid])
        self.con.commit()

    def delete_qso(self, qid: int):
        self.con.execute("DELETE FROM qsos WHERE id=?", (qid,))
        self._reset_qso_ids_if_empty()
        self.con.commit()

    def _reset_qso_ids_if_empty(self):
        """An empty log starts again from ID 1 (AUTOINCREMENT would otherwise go on from the last ID ever used)."""
        if not self.con.execute("SELECT 1 FROM qsos LIMIT 1").fetchone():
            self.con.execute("DELETE FROM qso_imports")
            for t in ("qsos", "qso_imports"):
                self.con.execute("DELETE FROM sqlite_sequence WHERE name = ?", (t,))

    # ADIF imports: which QSOs came from which file(s), so that an import can be taken back ------------
    def max_qso_id(self) -> int:
        return int(self.con.execute("SELECT IFNULL(MAX(id), 0) FROM qsos").fetchone()[0])

    def log_qso_import(self, label: str, since_id: int) -> int:
        """Record the QSOs added after `since_id` (by an import just finished) under `label`; returns how many."""
        ids = [r[0] for r in self.con.execute("SELECT id FROM qsos WHERE id > ? ORDER BY id", (since_id,))]
        if ids:
            self.con.execute("INSERT INTO qso_imports (utc, label, ids) VALUES (?,?,?)",
                             (iso_utc(datetime.now(timezone.utc)), label, json.dumps(ids)))
            self.con.commit()
        return len(ids)

    def qso_imports(self) -> list[dict]:
        """Every import, newest first, with how many of its QSOs are still in the log."""
        have = {r[0] for r in self.con.execute("SELECT id FROM qsos")}
        out = []
        for r in self.con.execute("SELECT * FROM qso_imports ORDER BY utc DESC, id DESC"):
            d = dict(r)
            d["ids"] = json.loads(d["ids"] or "[]")
            d["n"] = sum(1 for i in d["ids"] if i in have)
            out.append(d)
        return out

    def delete_qso_import(self, imp_id: int) -> int:
        r = self.con.execute("SELECT ids FROM qso_imports WHERE id = ?", (imp_id,)).fetchone()
        n = 0
        for qid in json.loads(r["ids"] or "[]") if r else []:
            n += self.con.execute("DELETE FROM qsos WHERE id = ?", (qid,)).rowcount
        self.con.execute("DELETE FROM qso_imports WHERE id = ?", (imp_id,))
        self._reset_qso_ids_if_empty()
        self.con.commit()
        return n

    def clear_qsos(self) -> int:
        n = self.con.execute("DELETE FROM qsos").rowcount
        self._reset_qso_ids_if_empty()
        self.con.commit()
        return n

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

    def add_decodes(self, rows: list[dict]) -> int:
        """Many decodes at once (ALL.TXT); duplicates skipped. Returns how many were new."""
        keys = ["utc", "call", "grid", "snr", "dt", "df", "mode", "message", "band", "dial_mhz", "client"]
        before = self.con.total_changes
        self.con.executemany(f"INSERT OR IGNORE INTO decodes ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                             [[iso_utc(d[k]) if k == "utc" and isinstance(d[k], datetime) else d.get(k) for k in keys]
                              for d in rows])
        self.con.commit()
        return self.con.total_changes - before

    def add_tx_lines(self, rows: list[dict]) -> int:
        """Own transmissions read from ALL.TXT (Tx lines): when and on which band I was on the air."""
        keys = ["utc", "call", "mode", "message", "band", "dial_mhz", "df"]
        before = self.con.total_changes
        self.con.executemany(f"INSERT OR IGNORE INTO tx_lines ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                             [[iso_utc(d[k]) if k == "utc" and isinstance(d[k], datetime) else d.get(k) for k in keys]
                              for d in rows])
        self.con.commit()
        return self.con.total_changes - before

    def eme_decodes(self, calls: list[str] | None = None, bands: list[str] | None = None,
                    since: str | None = None) -> list[dict]:
        """All the decodes on the EME bands (10 GHz and up: band set), oldest first."""
        q, a = "SELECT * FROM decodes WHERE band IS NOT NULL AND band != ''", []
        if calls:
            q += f" AND call IN ({','.join('?' * len(calls))})"
            a += [c.upper() for c in calls]
        if bands:
            q += f" AND band IN ({','.join('?' * len(bands))})"
            a += list(bands)
        if since:
            q += " AND utc >= ?"
            a.append(since)
        return [dict(r) for r in self.con.execute(q + " ORDER BY utc", a)]

    def tx_lines(self, bands: list[str] | None = None, since: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM tx_lines WHERE band IS NOT NULL", []
        if bands:
            q += f" AND band IN ({','.join('?' * len(bands))})"
            a += list(bands)
        if since:
            q += " AND utc >= ?"
            a.append(since)
        return [dict(r) for r in self.con.execute(q + " ORDER BY utc", a)]

    def clear_alltxt(self) -> int:
        """Forget what was read from ALL.TXT (decodes and Tx lines), to read the file again from the start."""
        n = self.con.execute("DELETE FROM decodes WHERE client = 'ALL.TXT'").rowcount
        n += self.con.execute("DELETE FROM tx_lines").rowcount
        self.con.commit()
        return n

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
