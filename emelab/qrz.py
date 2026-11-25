# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""QRZ.com XML Logbook Data service (https://xmldata.qrz.com): name, address, QTH, country, locator of a callsign,
for QSL labels and the station database. The user's own QRZ account is used; username and password are saved only
in EMELab's local settings and sent only to xmldata.qrz.com. Full addresses need a QRZ XML subscription."""
from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

URL = "https://xmldata.qrz.com/xml/current/"
AGENT = "EMELab"


def _get(params: dict, timeout: float = 15.0) -> ET.Element:
    from .net import _contexts
    err = None
    for _, ctx in _contexts():
        try:
            with urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(params), timeout=timeout, context=ctx) as r:
                return ET.fromstring(r.read())
        except Exception as e:
            err = e
    raise err


def _strip(root: ET.Element) -> ET.Element:
    for el in root.iter():                       # drop the XML namespace
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


class QRZ:
    def __init__(self, user: str, password: str):
        self.user, self.password, self.key = user, password, None

    def login(self) -> str:
        root = _strip(_get({"username": self.user, "password": self.password, "agent": AGENT}))
        s = root.find("Session")
        if s is None or s.findtext("Key") is None:
            raise RuntimeError((s.findtext("Error") if s is not None else None) or "QRZ: accesso non riuscito")
        self.key = s.findtext("Key")
        return self.key

    def lookup(self, call: str) -> dict:
        if not self.key:
            self.login()
        root = _strip(_get({"s": self.key, "callsign": call.upper()}))
        s = root.find("Session")
        if s is not None and s.findtext("Error") and "Session" in (s.findtext("Error") or ""):
            self.login()
            root = _strip(_get({"s": self.key, "callsign": call.upper()}))
        c = root.find("Callsign")
        if c is None:
            raise RuntimeError((s.findtext("Error") if s is not None else None) or f"{call}: non trovato")
        g = lambda k: (c.findtext(k) or "").strip() or None
        name = " ".join(x for x in (g("fname"), g("name")) if x) or None
        addr = ", ".join(x for x in (g("addr1"), " ".join(y for y in (g("zip"), g("addr2")) if y), g("state")) if x) or None
        return {"call": g("call") or call.upper(), "name": name, "fname": g("fname"), "lname": g("name"), "address": addr, "qth": g("addr2"), "country": g("country"),
                "locator": g("grid"), "lat": g("lat"), "lon": g("lon"), "qsl_via": g("qslmgr"),
                "lotw": g("lotw"), "eqsl": g("eqsl"), "mqsl": g("mqsl")}


def qso_people(D, calls) -> dict[str, dict]:
    """QTH, first name and last name of each callsign of the QSO log, from the EME stations database (filled by
    QRZ.com): {call: {"qth", "fname", "lname"}}; empty strings where it is not known yet."""
    out = {}
    for call in calls:
        s = D.station_of(call) or {}
        q = (s.get("data") or {}).get("qrz") or {}
        out[call] = {"qth": s.get("qth") or "", "fname": q.get("fname") or "", "lname": q.get("lname") or ""}
    return out


def missing(D, calls) -> list[str]:
    """Callsigns never looked up on QRZ.com with the first/last name split (only these are asked again)."""
    out = []
    for call in dict.fromkeys(calls):
        q = ((D.station_of(call) or {}).get("data") or {}).get("qrz") or {}
        if "fname" not in q:
            out.append(call)
    return out


def store(D, r: dict, locator: bool = True):
    """Save one QRZ.com answer in the EME stations database."""
    D.upsert_station(r["call"], name=r.get("name"), address=r.get("address"), qth=r.get("qth"),
                     country=r.get("country"), locator=r.get("locator") if locator else None,
                     data={"qrz": {k: r.get(k) for k in ("qsl_via", "lotw", "eqsl", "lat", "lon", "fname", "lname")}})
