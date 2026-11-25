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
        return {"call": g("call") or call.upper(), "name": name, "address": addr, "qth": g("addr2"), "country": g("country"),
                "locator": g("grid"), "lat": g("lat"), "lon": g("lon"), "qsl_via": g("qslmgr"),
                "lotw": g("lotw"), "eqsl": g("eqsl"), "mqsl": g("mqsl")}
