# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EME Assistant ↔ WSJT-X, live: keeps the decodes, logs the QSOs you accept in WSJT-X with every condition of that moment,
and can colour callsigns and set the Q65 submode in WSJT-X. Runs in the background of the EME Assistant server."""
from __future__ import annotations

import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone

from . import logbook, stations, wsjtx

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
        if not self.auto_log:
            return
        f_mhz = m["tx_freq_hz"] / 1e6 if m.get("tx_freq_hz") else None
        band = stations.band_of(f_mhz) or self._band()
        mode = m.get("mode") or ""
        sub = self.status.get("submode") if mode.upper().startswith("Q65") else None
        q = {"utc": m["time_on"], "call": m["dx_call"].upper(), "band": band, "freq_mhz": f_mhz, "mode": mode,
             "submode": sub, "rst_sent": m.get("report_sent"), "rst_rcvd": m.get("report_rcvd"),
             "locator": (m.get("dx_grid") or "").upper() or None, "my_locator": (m.get("my_grid") or "").upper() or None,
             "name": m.get("name") or None, "tx_pwr": m.get("tx_power") or None,
             "comment": " ".join(x for x in (m.get("comments"), "logged by WSJT-X → EME Assistant") if x)}
        wx = None
        if self.wx_fn:
            try:
                wx = self.wx_fn(q["utc"])
            except Exception as e:
                self.errors.append(f"meteo: {e}")
        q["calc"] = logbook.enrich(q, q["my_locator"] or self.my_locator_fn() or "", 0.0, wx)
        if wx:
            q.update(t_c=wx.get("t_c"), rh=wx.get("rh"), p_hpa=wx.get("p_hpa"), wx_source=wx.get("wx_source"))
        qid = self.db().add_qso(**q)
        self.logged.appendleft({**q, "id": qid, "duplicate": qid is None})

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
