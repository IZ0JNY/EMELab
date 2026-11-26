# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Automatic filling of a Sun / Moon measurement («➕ Nuova misura»).

At the moment of the measurement EMELab gathers, from what is reachable on the station PC:
  • DriverDish (EA3HMJ, telnet «status», read only): dish AZ/EL, target and its position, pointing error, offsets;
  • the weather: the personal station first, Open-Meteo as fallback (temperature, humidity, pressure, wind, rain,
    clouds);
  • WSJT-X (UDP status): dial frequency, band, mode;
  • the ephemeris of Sun and Moon come from analysis.snapshot (distance, Sun–Moon angle, sky temperature) and are
    saved with the measurement as always.
Every source is optional: when one does not answer, the others still fill their fields, and the report says why.
Nothing here ever sends a command that moves the dish (ea3hmj.READ_COMMANDS). All the values stay editable in the
form; what was read is saved in the measurement's «extra» field with its source and UTC time."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import ea3hmj, stations

DD_FRESH_S = 15          # a reading of the live DriverDish monitor older than this is not used
WSJTX_FRESH_S = 90       # WSJT-X sends a status at least every 15 s while it runs

TARGETS = {"sun": "sun", "sole": "sun", "moon": "moon", "luna": "moon"}


def target_kind(target: str | None) -> str | None:
    """DriverDish target name → measurement kind ("sun", "moon") or None."""
    t = (target or "").strip().lower()
    return next((k for name, k in TARGETS.items() if t.startswith(name)), None)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ DriverDish
def from_driverdish(status: dict, calc_src: dict | None = None) -> dict:
    """Fields of the form and the stored details from a parsed DriverDish «status».

    calc_src: EMELab's own position of the measured source ({"az", "el", "el_radio"}), to store dish − computed."""
    f, x = {}, {}
    if status.get("dish_az") is not None:
        f["az_read"], f["el_read"] = round(status["dish_az"] % 360.0, 3), round(status["dish_el"], 3)
    if status.get("off_az") is not None:
        f["az_off"], f["el_off"] = round(status["off_az"], 3), round(status["off_el"], 3)
    for k in ("target", "target_az", "target_el", "dish_az", "dish_el", "err_az", "err_el", "off_az", "off_el",
              "tracking", "moving"):
        if status.get(k) is not None:
            x[k] = status[k]
    if None not in (status.get("target_az"), status.get("dish_az")):
        x["err_deg"] = round(ea3hmj.angle_between(status["target_az"], status["target_el"],
                                                  status["dish_az"], status["dish_el"]), 4)
    elif None not in (status.get("err_az"), status.get("err_el")):
        x["err_deg"] = round(ea3hmj.angle_between(0.0, 0.0, status["err_az"], status["err_el"]), 4)
    if calc_src and status.get("dish_az") is not None:
        el_c = calc_src.get("el_radio", calc_src.get("el"))
        daz = (status["dish_az"] - calc_src["az"] + 180.0) % 360.0 - 180.0
        x["dish_minus_calc_az"], x["dish_minus_calc_el"] = round(daz, 3), round(status["dish_el"] - el_c, 3)
    k = target_kind(status.get("target"))
    if k:
        f["kind"] = k
    return {"fields": f, "extra": x}


def read_driverdish(host: str, port: int, monitor=None, now: datetime | None = None, timeout: float = 2.5) -> dict:
    """Status from the live monitor of the Tracking tab when it is fresh, otherwise one read-only «status»."""
    now = now or datetime.now(timezone.utc)
    last = getattr(monitor, "last", None) if monitor is not None else None
    if last and last.get("utc") and (now - last["utc"]).total_seconds() <= DD_FRESH_S:
        st = {k: v for k, v in last.items() if k not in ("raw", "utc")}
        return {"status": st, "utc": _iso(last["utc"]), "via": "monitor"}
    ans = ea3hmj.driverdish_query(["status"], host, int(port), timeout)
    st = ea3hmj.parse_status(ans.get("status", ""))
    if not st:
        raise OSError("DriverDish non ha risposto a «status»")
    return {"status": st, "utc": _iso(now), "via": "telnet"}


# ------------------------------------------------------------------ WSJT-X
def from_wsjtx(status: dict | None, last_seen: datetime | None, now: datetime | None = None) -> dict | None:
    """Dial frequency, band and mode from the last WSJT-X status, if WSJT-X is talking to EMELab now."""
    now = now or datetime.now(timezone.utc)
    if not status or not status.get("dial_hz") or not last_seen or (now - last_seen).total_seconds() > WSJTX_FRESH_S:
        return None
    mhz = status["dial_hz"] / 1e6
    band = stations.band_of(mhz)
    mode = " ".join(str(v) for v in (status.get("mode"), status.get("submode")) if v)
    out = {"freq_mhz": round(mhz, 6), "band": band, "band_label": stations.band_label(band) if band else None,
           "mode": mode or None, "utc": _iso(last_seen)}
    if status.get("tx_df") is not None:
        out["tx_df_hz"] = status["tx_df"]
    if status.get("rx_df") is not None:
        out["rx_df_hz"] = status["rx_df"]
    return out


def setup_for_band(setups: list[dict], freq_mhz: float | None, current_id=None):
    """Id of the configuration whose band contains the WSJT-X frequency (the current one when it already fits)."""
    if not freq_mhz:
        return current_id
    b = stations.band_of(freq_mhz)
    fit = [s["id"] for s in setups if stations.band_of(float(s["band_ghz"]) * 1000.0) == b]
    if not fit or current_id in fit:
        return current_id
    return fit[0]


# ------------------------------------------------------------------ weather
def read_weather(lat: float, lon: float, dt: datetime, station_url: str = "", station_fn=None, open_meteo_fn=None) -> dict:
    """Personal station first (only for a measurement within 30 min of now: it gives the present), Open-Meteo after.
    Returns the weather dict of emelab.weather plus "tried": [(source, error)…] for the sources that failed."""
    from . import weather
    station_fn = station_fn or (lambda u: weather.station_now(u, timeout=5.0))        # short: the form is waiting
    open_meteo_fn = open_meteo_fn or (lambda la, lo, t: weather.open_meteo(la, lo, t, timeout=6.0))
    tried = []
    if station_url and abs((datetime.now(timezone.utc) - dt).total_seconds()) <= 1800:
        try:
            w = station_fn(station_url)
            if any(w.get(k) is not None for k in ("t_c", "rh", "p_hpa")):
                return dict(w, tried=tried)
            tried.append(("station", "nessun dato"))
        except Exception as e:
            tried.append(("station", str(e) or e.__class__.__name__))
    try:
        return dict(open_meteo_fn(lat, lon, dt), tried=tried)
    except Exception as e:
        tried.append(("Open-Meteo", str(e) or e.__class__.__name__))
    return {"tried": tried}


WX_KEYS = ("t_c", "rh", "p_hpa", "wind_ms", "rain_mmh", "cloud_pct")


# ------------------------------------------------------------------ everything together
def collect(stn: dict, settings: dict, dt: datetime, *, dd_monitor=None, wsjtx_status=None, wsjtx_seen=None,
            dd_reader=None, wx_reader=None, now: datetime | None = None) -> dict:
    """Read every source in parallel (each one with a short timeout) and return
        {"utc": capture time, "fields": values for the form, "extra": what is saved with the measurement,
         "report": [(source, ok, text)…]}.
    The readers can be replaced (tests); by default they are the real ones."""
    now = now or datetime.now(timezone.utc)
    host = (settings.get("dd_host") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(settings.get("dd_port") or 9999)
    dd_reader = dd_reader or (lambda: read_driverdish(host, port, dd_monitor, now))
    wx_reader = wx_reader or (lambda: read_weather(stn["lat"], stn["lon"], dt, settings.get("emelab_wx_url", "")))
    fields: dict = {}
    extra: dict = {"auto_utc": _iso(now)}
    report: list = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_dd = ex.submit(dd_reader)
        f_wx = ex.submit(wx_reader)
        # DriverDish
        try:
            r = f_dd.result(timeout=8)
            extra["driverdish"] = dict(r["status"], utc=r["utc"], via=r["via"])
            report.append(("DriverDish", True, r["via"]))
        except Exception as e:
            report.append(("DriverDish", False, str(e) or e.__class__.__name__))
        # weather
        try:
            w = f_wx.result(timeout=15)
        except Exception as e:
            w = {"tried": [("meteo", str(e) or e.__class__.__name__)]}
        if any(w.get(k) is not None for k in WX_KEYS):
            for k in WX_KEYS:
                if w.get(k) is not None:
                    fields["wx_" + k] = round(float(w[k]), 2)
            fields["wx_source"], fields["wx_utc"] = w.get("wx_source"), w.get("wx_utc")
            extra["weather"] = {k: w.get(k) for k in WX_KEYS + ("dew_c", "gust_ms", "iwv_kg_m2", "wx_source", "wx_utc",
                                                                 "station_file") if w.get(k) is not None}
            report.append(("meteo", True, w.get("wx_source") or ""))
        else:
            report.append(("meteo", False, "; ".join(f"{s}: {e}" for s, e in w.get("tried", [])) or "nessun dato"))
    # WSJT-X (already in memory, no waiting)
    wj = from_wsjtx(wsjtx_status, wsjtx_seen, now)
    if wj:
        extra["wsjtx"] = wj
        report.append(("WSJT-X", True, f"{wj['freq_mhz']:.3f} MHz"))
    else:
        report.append(("WSJT-X", False, "non collegato"))
    return {"utc": _iso(now), "fields": fields, "extra": extra, "report": report}


def driverdish_fields(extra: dict, calc: dict | None, kind: str | None) -> dict:
    """Form values from the stored DriverDish reading, with dish − computed for the source being measured."""
    st = extra.get("driverdish")
    if not st:
        return {"fields": {}, "extra": {}}
    k = target_kind(st.get("target")) or kind
    src = (calc or {}).get(k) if k in ("sun", "moon") else None
    return from_driverdish(st, src)


def age_s(capture_utc: str | None, dt: datetime) -> float | None:
    """Seconds between the automatic reading and the time of the measurement in the form."""
    if not capture_utc:
        return None
    t = datetime.fromisoformat(capture_utc.replace("Z", "+00:00"))
    return abs((dt - t).total_seconds())



# ------------------------------------------------------------------ Y factor by two clicks
HOT_KINDS = {"sun": "Sole", "moon": "Luna", "ground": "Terra"}       # what the «hot» click can be
HOT_SHORT = {"sun": "SN", "moon": "MN", "ground": "GND"}


def y_delta(cold_db: float | None, hot_db: float | None) -> float | None:
    """Y in dB from two levels in dB (RMS of the receiver on cold sky and on the source)."""
    if cold_db is None or hot_db is None:
        return None
    return round(float(hot_db) - float(cold_db), 3)


def capture(level_db: float, utc: datetime, az=None, el=None, source: str = "manuale") -> dict:
    return {"db": float(level_db), "utc": _iso(utc), "az": az, "el": el, "source": source}
