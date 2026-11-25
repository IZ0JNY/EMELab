# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Weather at the time of a measurement, always with its UTC timestamp and its source.

Sources: Open-Meteo (free, no account: forecast API for the last days and the next 16, archive API for older
dates) and an optional personal station. The station address is typed by the user in EMELab and saved only in
the local settings of this computer: it is never written in the program or sent anywhere else.
Supported station formats: Meteotemplate (live JSON), Cumulus realtime.txt, Weather Display clientraw.txt and
a plain JSON with the usual names."""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HOURLY = ["temperature_2m", "relative_humidity_2m", "surface_pressure", "dew_point_2m", "cloud_cover",
          "precipitation", "wind_speed_10m", "wind_gusts_10m", "total_column_integrated_water_vapour"]


def _get(url: str, timeout: float = 10.0) -> bytes:
    return _get_final(url, timeout)[0]


def _get_final(url: str, timeout: float = 10.0) -> tuple[bytes, str]:
    """Body and final address after redirects."""
    from .net import _contexts
    err = None
    for _, ctx in _contexts():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; EMELab)"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read(), r.geturl()
        except Exception as e:                    # try the next TLS context
            err = e
            if url.startswith("http://"):
                break
    raise err


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def open_meteo(lat: float, lon: float, dt: datetime, timeout: float = 10.0) -> dict:
    """Hourly model values interpolated to dt (UTC)."""
    dt = _utc(dt)
    old = dt < datetime.now(timezone.utc) - timedelta(days=60)
    base = "https://archive-api.open-meteo.com/v1/archive" if old else "https://api.open-meteo.com/v1/forecast"
    day = dt.date()
    q = {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "hourly": ",".join(HOURLY), "timezone": "UTC",
         "wind_speed_unit": "ms", "start_date": str(day - timedelta(days=0)), "end_date": str(day + timedelta(days=1))}
    js = json.loads(_get(base + "?" + urllib.parse.urlencode(q), timeout))
    if js.get("error"):
        raise RuntimeError(js.get("reason", "Open-Meteo"))
    h = js["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
    i = max(0, min(len(times) - 2, int((dt - times[0]).total_seconds() // 3600)))
    w = (dt - times[i]).total_seconds() / 3600.0

    def val(k):
        a, b = (h.get(k) or [None] * len(times))[i], (h.get(k) or [None] * len(times))[i + 1]
        if a is None or b is None:
            return a if b is None else b
        return a + (b - a) * w
    return {"t_c": val("temperature_2m"), "rh": val("relative_humidity_2m"), "p_hpa": val("surface_pressure"),
            "dew_c": val("dew_point_2m"), "cloud_pct": val("cloud_cover"), "rain_mmh": val("precipitation"),
            "wind_ms": val("wind_speed_10m"), "gust_ms": val("wind_gusts_10m"),
            "iwv_kg_m2": val("total_column_integrated_water_vapour"),
            "wx_utc": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "wx_source": "Open-Meteo"}


def open_meteo_series(lat: float, lon: float, start: datetime, days: int, timeout: float = 10.0) -> list[dict]:
    """Hourly forecast (or recent past) for the planner: humidity at 24 GHz matters a lot."""
    start = _utc(start)
    q = {"latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}", "hourly": ",".join(HOURLY[:4] + ["cloud_cover",
         "precipitation", "precipitation_probability", "wind_speed_10m", "wind_gusts_10m"]), "timezone": "UTC",
         "wind_speed_unit": "ms", "start_date": str(start.date()),
         "end_date": str((start + timedelta(days=max(min(days, 16) - 1, 0))).date())}   # the forecast covers 16 days
    js = json.loads(_get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q), timeout))
    h = js["hourly"]
    g = lambda k, i: (h.get(k) or [None] * len(h["time"]))[i]
    return [{"utc": datetime.fromisoformat(t).replace(tzinfo=timezone.utc), "t_c": h["temperature_2m"][i],
             "rh": h["relative_humidity_2m"][i], "p_hpa": h["surface_pressure"][i],
             "cloud_pct": h["cloud_cover"][i], "rain_mmh": h["precipitation"][i], "rain_prob": g("precipitation_probability", i),
             "wind_ms": g("wind_speed_10m", i), "gust_ms": g("wind_gusts_10m", i)} for i, t in enumerate(h["time"])]


# ------------------------------------------------------------------ personal station
def _num(x):
    try:
        v = float(str(x).replace(",", "."))
        return None if math.isnan(v) else v
    except Exception:
        return None


def parse_station(text: str) -> dict:
    """Current values from a station file. Returns °C, %, hPa, m/s, mm/h and the station time (UTC) if present."""
    s = text.strip()
    out = {}
    if s.startswith("{"):
        js = json.loads(s)
        js = {str(k).lower(): v for k, v in js.items()}
        pick = lambda *ks: next((_num(js[k]) for k in ks if k in js and _num(js[k]) is not None), None)
        out = {"t_c": pick("t", "temp", "temperature", "outtemp"), "rh": pick("h", "hum", "humidity", "outhumidity"),
               "p_hpa": pick("p", "press", "pressure", "barometer"), "dew_c": pick("d", "dew", "dewpoint"),
               "rain_mmh": pick("rr", "rrate", "rainrate", "rain_rate")}
        w = pick("w", "wind", "windspeed", "wind_speed")       # Meteotemplate: km/h
        if w is not None:
            out["wind_ms"] = w / 3.6 if "w" in js or "wind" in js else w
        ts = pick("u", "time", "timestamp", "unix", "datetime")
        if ts and ts > 1e9:
            out["station_utc"] = datetime.fromtimestamp(ts, timezone.utc)
        out["format"] = "json"
    elif s.startswith("12345"):                               # Weather Display clientraw.txt
        f = s.split()
        out = {"wind_ms": _num(f[1]) * 0.514444 if _num(f[1]) is not None else None, "t_c": _num(f[4]),
               "rh": _num(f[5]), "p_hpa": _num(f[6]), "rain_mmh": _num(f[10]), "dew_c": _num(f[72]) if len(f) > 72 else None,
               "format": "clientraw"}
    else:                                                     # Cumulus realtime.txt: date time temp hum dew wspeed …
        f = s.split()
        if len(f) > 10:
            out = {"t_c": _num(f[2]), "rh": _num(f[3]), "dew_c": _num(f[4]), "p_hpa": _num(f[10]),
                   "rain_mmh": _num(f[8]), "format": "cumulus"}
    return {k: v for k, v in out.items() if v is not None}


# file names written by the usual station programs, in order of preference
STATION_FILES = ["meteotemplateLive.txt", "realtime.txt", "clientraw.txt", "realtimegauges.txt",
                 "customclientraw.txt"]
# folders where these programs are often installed under the home page of the site
STATION_DIRS = ["", "template/", "meteotemplate/", "meteo/", "weather/", "wd/", "cumulus/", "data/", "live/"]
_FILE_RE = None


def _page_candidates(page_url: str, html: str) -> list[str]:
    """Data files and frames referenced by the home page (links, scripts, iframes), as absolute URLs."""
    import re
    global _FILE_RE
    if _FILE_RE is None:
        names = "|".join(re.escape(n) for n in STATION_FILES)
        _FILE_RE = re.compile(r"""["'(=\s]([^"'()<>\s]*?(?:%s))(?:\?[^"'()<>\s]*)?["')\s&]""" % names, re.I)
    found, frames = [], []
    for m in _FILE_RE.finditer(html):
        found.append(urllib.parse.urljoin(page_url, m.group(1)))
    for m in re.finditer(r"""<i?frame[^>]+src\s*=\s*["']([^"']+)["']""", html, re.I):
        frames.append(urllib.parse.urljoin(page_url, m.group(1)))
    return list(dict.fromkeys(found)), list(dict.fromkeys(frames))


def _folder(u: str) -> str:
    p = urllib.parse.urlsplit(u)
    path = p.path if p.path.endswith("/") else p.path.rsplit("/", 1)[0] + "/"
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, "", ""))


def _read(u: str, timeout: float) -> dict:
    d = parse_station(_get(u, timeout).decode("utf-8", "replace"))
    if d.get("t_c") is None and d.get("rh") is None:
        raise RuntimeError("nessun valore di temperatura o umidità")
    return d


def station_now(url: str, timeout: float = 8.0) -> dict:
    """Read the personal station.

    A direct link to a data file is read as it is. For the address of a web site: the usual files next to the
    home page, then the files the home page itself links (also inside frames), then the usual install folders;
    http and https are both tried. The URL that worked is returned in "station_file"."""
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    tried, seen = [], set()

    def attempt(u):
        if u in seen:
            return None
        seen.add(u)
        try:
            d = _read(u, timeout)
        except Exception as e:
            tried.append(f"{u}: {e}")
            return None
        now = datetime.now(timezone.utc)
        t = d.pop("station_utc", now)
        d.update(wx_utc=t.strftime("%Y-%m-%dT%H:%M:%SZ"), wx_source="stazione personale", station_file=u)
        return d

    path = urllib.parse.urlsplit(url).path
    if path.lower().endswith((".txt", ".json", ".php", ".xml")) and not path.lower().endswith(("index.php",)):
        d = attempt(url)
        if d:
            return d
        raise RuntimeError("; ".join(tried))

    root = _folder(url if url.endswith("/") or "." in path.rsplit("/", 1)[-1] else url + "/")
    other = root.replace("http://", "https://", 1) if root.startswith("http://") else root.replace("https://", "http://", 1)
    # 1) the usual files next to the home page
    for name in STATION_FILES[:3]:
        d = attempt(root + name)
        if d:
            return d
    # 2) what the home page links (after redirects), also one level of frames; https if http does not answer
    bases = [root]
    for page in ([url, other] if other != root else [url]):
        try:
            body, page = _get_final(page, timeout)
            html = body.decode("utf-8", "replace")
        except Exception as e:
            tried.append(f"{page}: {e}")
            if page == url:
                bases = [other]
            continue
        files, frames = _page_candidates(page, html)
        for f in frames[:5]:
            try:
                ff, _ = _page_candidates(f, _get(f, timeout).decode("utf-8", "replace"))
                files += ff + [_folder(f) + n for n in STATION_FILES[:3]]
            except Exception as e:
                tried.append(f"{f}: {e}")
        for u in files:
            d = attempt(u)
            if d:
                return d
        bases = [_folder(page)]
        break
    # 3) the usual install folders
    for base in bases:
        for sub in STATION_DIRS:
            for name in STATION_FILES[:3]:
                d = attempt(base + sub + name)
                if d:
                    return d
    nf = sum("404" in t for t in tried)
    head = (f"nessun file dati trovato ({nf} indirizzi provati danno 404). Apri il sito nel browser e incolla qui "
            "l'indirizzo diretto del file dati (es. .../clientraw.txt, .../realtime.txt, .../meteotemplateLive.txt)")
    raise RuntimeError(head + " — " + "; ".join(tried[:6]))
