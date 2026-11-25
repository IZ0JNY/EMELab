# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab ↔ WSJT-X, live: keeps the decodes, logs the QSOs you accept in WSJT-X with every condition of that moment,
and can colour callsigns and set the Q65 submode in WSJT-X. Runs in the background of the EMELab server.

A QSO logged in WSJT-X reaches EMELab in two independent ways, used together or alone: the UDP «QSO Logged» message
and the record WSJT-X appends to wsjtx_log.adi (see wsjtx_logfile). Both go through log_qso(): only EME QSOs at
10 GHz and up are kept (logbook.eme_verdict), and the same QSO arriving twice, or already imported from an ADIF file,
is recognised (same call and band within ±10 minutes) and logged once."""
from __future__ import annotations

import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

from . import logbook, stations, wsjtx, wsjtx_check, wsjtx_logfile

CALL = re.compile(r"^(?=.*\d)[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}(?:/[A-Z0-9]{1,4})?$")
GRID = re.compile(r"^[A-R]{2}\d{2}$")


def sender_of(message: str) -> tuple[str | None, str | None]:
    """Callsign that transmitted a standard message, and its grid if present:
    'CQ DL7YC JO62' → DL7YC/JO62, 'IZ0JNY OK1DFC JN79' → OK1DFC/JN79, 'IZ0JNY OK1DFC -18' → OK1DFC."""
    t = [x for x in message.upper().replace("<", "").replace(">", "").split() if x]
    if not t:
        return None, None
    if t[0] in ("CQ", "QRZ", "DE") and len(t) >= 2:
        i = 1 + (1 if len(t) > 2 and not CALL.match(t[1]) and CALL.match(t[2]) else 0)     # CQ EU DL7YC …
    else:
        i = 1
    call = t[i] if i < len(t) and CALL.match(t[i]) else None
    grid = next((x for x in t[i + 1:i + 2] if GRID.match(x) and x != "RR73"), None) if call else None
    return call, grid


class Service:
    def __init__(self, db_factory, my_locator_fn, wx_fn=None):
        self.db_factory, self.my_locator_fn, self.wx_fn = db_factory, my_locator_fn, wx_fn
        self.listener: wsjtx.Listener | None = None
        self.status: dict = {}
        self.client: str | None = None
        self.last_seen: datetime | None = None
        self.recent = deque(maxlen=300)
        self.logged = deque(maxlen=50)
        self.errors = deque(maxlen=20)
        self.auto_log = True
        self.eme_only = True            # keep only EME QSOs at 10 GHz and up
        self.strict_eme = False         # … and only those with PROP_MODE=EME
        self.tail: wsjtx_logfile.LogTail | None = None
        self.on_tail_pos = None         # callback(path, offset) to remember where the file was read up to
        self.file_seen: datetime | None = None
        self.auto_fix = True            # correct mode/submode/T-R in WSJT-X when they do not match the band
        self.problems: list[dict] = []  # what is wrong in the WSJT-X settings now (wsjtx_check)
        self.fixes = deque(maxlen=20)   # corrections sent to WSJT-X
        self._fix_try: dict = {}        # Q65 code → (attempts, last time)
        self._file_stop = threading.Event()
        self._db = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- control
    def start(self, host="127.0.0.1", port=2237, multicast=None):
        self.stop()
        self.listener = wsjtx.Listener(self.on_message, host, port, multicast).start()
        return self

    def stop(self):
        if self.listener:
            self.listener.stop()
        self.listener = None

    def start_file(self, path, offset: int | None = None, interval: float = 3.0):
        """Follow wsjtx_log.adi in the background (offset None: only the QSOs logged from now on)."""
        self.stop_file()
        self.tail = wsjtx_logfile.LogTail(path, offset)
        self._file_stop = threading.Event()
        stop = self._file_stop

        def run():
            while not stop.is_set():
                self.poll_file()
                stop.wait(interval)
        threading.Thread(target=run, name="wsjtx-adi", daemon=True).start()
        return self

    def stop_file(self):
        self._file_stop.set()
        self.tail = None

    @property
    def file_running(self) -> bool:
        return self.tail is not None

    def poll_file(self) -> int:
        """Read what WSJT-X appended to its log file; returns how many records were read."""
        tail = self.tail
        if tail is None:
            return 0
        try:
            before = tail.offset
            recs = tail.read_new()
        except Exception as e:
            self.errors.append(f"wsjtx_log.adi: {e}")
            return 0
        with self._lock:
            for r in recs:
                try:
                    q = logbook.from_adif_record(r)
                    if q:
                        self.log_qso(logbook.wsjtx_mode(q), "wsjtx_log.adi")
                except Exception as e:
                    self.errors.append(f"wsjtx_log.adi: {e}")
            if recs:
                self.file_seen = datetime.now(timezone.utc)
        if tail.offset != before and self.on_tail_pos:
            try:
                self.on_tail_pos(str(tail.path), tail.offset)
            except Exception:
                pass
        return len(recs)

    @property
    def running(self) -> bool:
        return self.listener is not None

    def db(self):
        if self._db is None:
            self._db = self.db_factory()
        return self._db

    # ---------------------------------------------------------------- incoming
    def on_message(self, m: dict, addr):
        with self._lock:
            self.client = m["id"]
            self.last_seen = datetime.now(timezone.utc)
            try:
                getattr(self, "_on_" + m["type"], lambda m: None)(m)
            except Exception as e:                          # never kill the listener
                self.errors.append(f"{m['type']}: {e}")

    def _on_status(self, m):
        self.status = m
        try:
            stn = self.db().station()
        except Exception:
            stn = {}
        probs = wsjtx_check.check(m, stn)
        want = next((p["fix"] for p in probs if p.get("fix")), None)
        if want is None:
            self._fix_try = {}
        elif self.auto_fix and not m.get("transmitting"):
            n, last = self._fix_try.get(want, (0, None))
            now = datetime.now(timezone.utc)
            if n < 3 and (last is None or (now - last).total_seconds() > 15):
                if self.set_q65(want):
                    self._fix_try = {want: (n + 1, now)}
                    self.fixes.appendleft({"utc": now, "to": f"Q65-{want}", "from": f"{m.get('mode')} {m.get('submode')}"})
            elif n >= 3:
                probs.append({"code": "udp_requests", "msg": "WSJT-X non accetta le correzioni: in Settings → Reporting "
                              "spunta «Accept UDP requests»", "detail": "", "fix": None})
        self.problems = probs

    def _band(self):
        hz = self.status.get("dial_hz")
        return stations.band_of(hz / 1e6) if hz else None

    def _on_decode(self, m):
        now = datetime.now(timezone.utc)
        t = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(milliseconds=m["ms_since_midnight"])
        if t > now + timedelta(minutes=5):                 # decode of yesterday, received after midnight
            t -= timedelta(days=1)
        call, grid = sender_of(m["message"])
        d = {"utc": t, "call": call, "grid": grid, "snr": m["snr"], "dt": m["dt"], "df": m["df"], "mode": m["mode"],
             "message": m["message"].strip(), "band": self._band(),
             "dial_mhz": (self.status.get("dial_hz") or 0) / 1e6 or None, "client": m["id"]}
        self.recent.appendleft(d)
        self.db().add_decode(**d)
        if call:
            data = (self.db().station_of(call) or {}).get("data", {})
            heard = data.get("heard", {})
            band = d["band"]
            heard = {**heard, "n": heard.get("n", 0) + 1, "last": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "snr_best": max(heard.get("snr_best", -99), m["snr"]),
                     "bands": sorted(set(heard.get("bands", [])) | ({band} if band else set()))}
            self.db().upsert_station(call, locator=grid if grid and len(grid) >= 4 else None, eme=1, data={"heard": heard})
            self.db().commit()

    def _on_qso_logged(self, m):
        f_mhz = m["tx_freq_hz"] / 1e6 if m.get("tx_freq_hz") else None
        band = stations.band_of(f_mhz) or self._band()
        mode = m.get("mode") or ""
        q = {"utc": m["time_on"], "call": m["dx_call"].upper(), "band": band, "freq_mhz": f_mhz, "mode": mode,
             "rst_sent": m.get("report_sent"), "rst_rcvd": m.get("report_rcvd"),
             "locator": (m.get("dx_grid") or "").upper() or None, "my_locator": (m.get("my_grid") or "").upper() or None,
             "name": m.get("name") or None, "tx_pwr": m.get("tx_power") or None, "comment": m.get("comments") or None,
             "prop_mode": m.get("prop_mode") or None}
        self.log_qso(q, "UDP")

    def log_qso(self, q: dict, source: str) -> int | None:
        """One QSO from WSJT-X (UDP or log file) → the EMELab log, with the conditions of that moment.
        Returns the new id, None when left out (not EME) or already in the log."""
        if not self.auto_log:
            return None
        q = dict(q)
        q.pop("adif", None)
        prop = q.pop("prop_mode", None)
        if (q.get("mode") or "").upper().startswith("Q65") and not q.get("submode"):
            q["submode"] = self.status.get("submode") or None
        entry = {**q, "source": source, "id": None, "duplicate": False, "skipped": None}
        db = self.db()
        if self.eme_only:
            eme_calls = {q["call"]} if (db.station_of(q["call"]) or {}).get("eme") else set()
            why = logbook.eme_verdict({**q, "prop_mode": prop}, eme_calls, self.strict_eme)
            if why:
                self.logged.appendleft({**entry, "skipped": why})
                return None
        if db.qso_near(q["call"], q.get("band"), q["utc"]):
            self.logged.appendleft({**entry, "duplicate": True})
            return None
        q["comment"] = " ".join(x for x in (q.get("comment"), "logged by WSJT-X → EMELab") if x)
        wx = None
        if self.wx_fn:
            try:
                wx = self.wx_fn(q["utc"])
            except Exception as e:
                self.errors.append(f"meteo: {e}")
        q["calc"] = logbook.enrich(q, q.get("my_locator") or self.my_locator_fn() or "", 0.0, wx)
        if wx:
            q.update(t_c=wx.get("t_c"), rh=wx.get("rh"), p_hpa=wx.get("p_hpa"), wx_source=wx.get("wx_source"))
        qid = db.add_qso(**q)
        if qid and q.get("locator"):
            db.upsert_station(q["call"], locator=q["locator"], eme=1)
            db.commit()
        self.logged.appendleft({**q, "source": source, "id": qid, "duplicate": qid is None, "skipped": None})
        return qid

    # ---------------------------------------------------------------- outgoing
    def highlight(self, call: str, bg: str | None, fg: str | None = "#000000") -> bool:
        return bool(self.listener and self.client and self.listener.send(self.client, wsjtx.highlight(self.client, call, bg, fg)))

    def set_q65(self, submode_code: str) -> bool:
        """'60D' → Q65, submode D, T/R 60 s (and the same for 30/120/300 s and A–E)."""
        period, sub = int(submode_code[:-1]), submode_code[-1]
        return bool(self.listener and self.client and
                    self.listener.send(self.client, wsjtx.configure(self.client, "Q65", sub, period)))

    def replay(self) -> bool:
        return bool(self.listener and self.client and self.listener.send(self.client, wsjtx.replay(self.client)))
