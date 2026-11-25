# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Signal expected from another station and the chance of a QSO.

Bistatic radar equation A → Moon → B with the actual distances of the Moon from both stations, the part of the
Moon both beams illuminate, the atmosphere at both ends and the noise of the receiving station pointed at the Moon:

    P_rx = P_tx·G_tx·G_rx·σ·λ² / ((4π)³ R_A² R_B²) · BWF · L_atm,A · L_atm,B ,   σ = 0.065·π·a²
    SNR(2500 Hz) = P_rx / (k·T_sys·2500 Hz)                                  (the WSJT-X reporting bandwidth)

Decoding thresholds of Q65 against the mutual libration spread are the fits by Charlie Suckling G3WDG (used in the
EME calculator of OE2IGL/DF3GJ). Unknown data of the other station (receiver, efficiency) are typical values for the
band: they are shown as assumptions, and the offset learned from the logged QSOs corrects the whole model."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta

import numpy as np

from . import astro, atmos, link, sky

K_B = 1.380649e-23
BW_WSJT = 2500.0
BAND_GHZ = {"10G": 10.3682, "24G": 24.0482, "47G": 47.0882, "76G": 76.0322, "122G": 122.2502, "134G": 134.9282}
# typical receive system at 30° elevation without the Moon (LNA + feed loss + sky + spillover), K
TSYS_TYPICAL = {"10G": 75.0, "24G": 160.0, "47G": 420.0, "76G": 750.0, "122G": 1500.0, "134G": 1600.0}
POWER_TYPICAL = {"10G": 30.0, "24G": 15.0, "47G": 5.0, "76G": 2.0, "122G": 0.5, "134G": 0.5}
ETA = {"offset": 0.65, "prime": 0.55}
SIGMA_LOGISTIC_DB = 2.0          # spread of the success probability around the threshold (model + QSB)


def antenna_m(text: str | None) -> tuple[float | None, str]:
    """Dish diameter (m) and kind from texts like '2.4m dish OS', '120 cm', '3,7m dish'."""
    if not text:
        return None, "prime"
    t = text.lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(cm|m)\b", t)
    if not m:
        return None, "prime"
    d = float(m.group(1)) / (100 if m.group(2) == "cm" else 1)
    return d, "offset" if re.search(r"\bos\b|offset", t) else "prime"


def gain_dbi(f_ghz: float, D_m: float, eta: float) -> float:
    lam = sky.C / (f_ghz * 1e9)
    return 10 * math.log10(eta * (math.pi * D_m / lam) ** 2)


def station(band: str, D_m: float, power_w: float | None = None, kind: str = "prime", tsys_K: float | None = None,
            eta: float | None = None, line_loss_db: float = 0.0, assumed: tuple = ()) -> dict:
    eta = eta or ETA.get(kind, 0.55)
    f = BAND_GHZ[band]
    return {"band": band, "D_m": D_m, "kind": kind, "eta": eta, "gain_dbi": gain_dbi(f, D_m, eta),
            "hpbw_deg": sky.hpbw_deg(f, D_m, 12.0), "power_w": power_w if power_w else POWER_TYPICAL[band],
            "tsys_K": tsys_K or TSYS_TYPICAL[band], "line_loss_db": line_loss_db,
            "assumed": tuple(assumed) + (() if power_w else ("potenza",)) + (() if tsys_K else ("Tsys",)) +
            (() if eta else ("efficienza",))}


def from_directory(entry: dict, band: str) -> dict | None:
    """Station model from a row of the EME Directory (antenna text and power)."""
    D, kind = antenna_m(entry.get("antenna"))
    if not D:
        return None
    return station(band, D, entry.get("power_w"), kind)


def q65_threshold_db(mode: str, spread_hz: float) -> float:
    """Q65 decoding threshold (dB in 2500 Hz) vs mutual libration spread — G3WDG fits (OE2IGL calculator)."""
    x = min(max(spread_hz, 0.0), 1300.0)
    if mode == "60D":
        x = min(x, 550.0)
        return 5.6139e-8 * x ** 3 - 6.4781e-5 * x ** 2 + 3.7718e-2 * x - 28.285
    if mode == "60E":
        return -3.6013e-12 * x ** 4 + 1.5565e-8 * x ** 3 - 2.4829e-5 * x ** 2 + 0.022733 * x - 27.483
    if mode == "120E":
        x = min(x, 550.0)
        return 3e-8 * x ** 3 - 0.00005 * x ** 2 + 0.0387 * x - 30.751
    raise ValueError(mode)


def best_mode(spread_hz: float) -> tuple[str, float]:
    return min(((m, q65_threshold_db(m, spread_hz)) for m in ("60D", "60E", "120E")), key=lambda x: x[1])


def moon_temp_in_beam(f_ghz: float, D_m: float, eta: float, hpbw: float, moon_diam_deg: float, tb: float = 220.0) -> float:
    return sky.antenna_temp_disk(tb, moon_diam_deg, f_ghz, D_m, eta, hpbw)


def snr_2500(tx: dict, rx: dict, f_ghz: float, r_tx_km: float, r_rx_km: float, moon_diam_deg: float,
             atm_tx_db: float, atm_rx_db: float, t_sky_rx: float = 0.0) -> dict:
    """SNR (dB in 2500 Hz) at the receiver of rx for a signal sent by tx."""
    lam = sky.C / (f_ghz * 1e9)
    sigma = link.REFLECTIVITY * math.pi * link.R_MOON_M ** 2
    pl = 10 * math.log10((4 * math.pi) ** 3 * (r_tx_km * 1e3) ** 2 * (r_rx_km * 1e3) ** 2 / (sigma * lam ** 2))
    bwf = 10 * math.log10(link.beam_moon_factor(moon_diam_deg, tx["hpbw_deg"], hpbw_rx=rx["hpbw_deg"]))
    p = (10 * math.log10(tx["power_w"]) - tx.get("line_loss_db", 0.0) + tx["gain_dbi"] + rx["gain_dbi"] - pl + bwf
         - atm_tx_db - atm_rx_db)
    t_moon = moon_temp_in_beam(f_ghz, rx["D_m"], rx["eta"], rx["hpbw_deg"], moon_diam_deg) * 10 ** (-atm_rx_db / 10)
    tsys = rx["tsys_K"] + t_sky_rx + t_moon
    n = 10 * math.log10(K_B * tsys * BW_WSJT)
    return {"p_rx_dbw": p, "path_loss_db": pl, "bwf_db": bwf, "tsys_K": tsys, "t_moon_K": t_moon, "snr_db": p - n}


def pol_angle(lat_deg: float, az_deg: float, el_deg: float) -> float:
    """Position angle (°) of a horizontally polarised antenna's E field as seen on the sky (parallactic form,
    as in WSJT-X lib/astro.f90 by K1JT)."""
    la, az, el = (math.radians(v) for v in (lat_deg, az_deg, el_deg))
    xx = math.sin(la) * math.cos(el) - math.cos(la) * math.cos(az) * math.sin(el)
    yy = math.cos(la) * math.sin(az)
    return math.degrees(math.atan2(yy, xx))


def spatial_pol_offset(p_a: float, p_b: float) -> float:
    """Spatial polarisation offset Dpol between two stations, −90…+90° (linear polarisation, no Faraday:
    negligible at 10 GHz and above)."""
    d = (p_b - p_a + 720.0) % 180.0
    return d - 180.0 if d > 90.0 else d


def pol_loss_db(dpol_deg: float) -> float:
    """Loss between two linearly polarised antennas rotated by Dpol (cross-polar floor about −30 dB)."""
    return -10 * math.log10(max(math.cos(math.radians(dpol_deg)) ** 2, 1e-3))


def link_at(t: datetime, a: dict, a_loc: tuple, b: dict, b_loc: tuple, band: str, wx_a: dict | None = None,
            wx_b: dict | None = None, h_a: float = 0.0, h_b: float = 0.0, linear: bool = True) -> dict | None:
    """Both directions at time t: a hears b and b hears a, with margins over the best Q65 mode."""
    f = BAND_GHZ[band]
    sa = astro.sky(t, a_loc[0], a_loc[1], h_a)
    sb = astro.sky(t, b_loc[0], b_loc[1], h_b)
    if sa.moon.el < 0 or sb.moon.el < 0:
        return None

    def atm(s, wx):
        wx = wx or {}
        z = atmos.zenith_attenuation(f, wx.get("t_c", 15.0) if wx.get("t_c") is not None else 15.0,
                                     wx.get("rh", 60.0) if wx.get("rh") is not None else 60.0,
                                     wx.get("p_hpa") or 1013.25)["total"]
        a_db = atmos.slant_attenuation(z, max(s.moon.el_radio, 0.5))
        return a_db, atmos.sky_temperature(a_db, wx.get("t_c") if wx.get("t_c") is not None else 15.0)
    aa, tska = atm(sa, wx_a)
    ab, tskb = atm(sb, wx_b)
    mut = astro.mutual(t, a_loc, b_loc, h_a, h_b)
    spread = mut["spread_hz_per_ghz"] * f
    mode, thr = best_mode(spread)
    diam = (sa.moon.diam_deg + sb.moon.diam_deg) / 2
    hear_b = snr_2500(b, a, f, sb.moon.dist_km, sa.moon.dist_km, diam, ab, aa, tska)     # at a
    hear_a = snr_2500(a, b, f, sa.moon.dist_km, sb.moon.dist_km, diam, aa, ab, tskb)     # at b
    dpol = spatial_pol_offset(pol_angle(a_loc[0], sa.moon.az, sa.moon.el), pol_angle(b_loc[0], sb.moon.az, sb.moon.el))
    lpol = pol_loss_db(dpol) if linear else 0.0
    hear_b["snr_db"] -= lpol
    hear_a["snr_db"] -= lpol
    return {"utc": t, "el_a": sa.moon.el, "el_b": sb.moon.el, "spread_hz": spread,
            "doppler_hz": mut["doppler_hz_per_ghz"] * f, "mode": mode, "threshold_db": thr,
            "dpol_deg": dpol, "pol_loss_db": lpol,
            "snr_a_hears_b": hear_b["snr_db"], "snr_b_hears_a": hear_a["snr_db"],
            "margin_db": min(hear_b["snr_db"], hear_a["snr_db"]) - thr, "detail": (hear_b, hear_a)}


def probability(margin_db: float, offset_db: float = 0.0, sigma_db: float = SIGMA_LOGISTIC_DB) -> float:
    return 1 / (1 + math.exp(-(margin_db + offset_db) / sigma_db))


# ------------------------------------------------------------------ fast Moon elevation for many stations
def moon_elevations(times: list[datetime], locs: np.ndarray) -> np.ndarray:
    """Topocentric Moon elevation (°, geometric) for every time × station; locs: N×2 (lat, lon)."""
    la, lo = np.radians(locs[:, 0]), np.radians(locs[:, 1])
    import erfa
    obs = np.array([erfa.gd2gc(1, l2, l1, 0.0) for l1, l2 in zip(la, lo)]) / 1000.0
    up = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=1)
    out = np.empty((len(times), len(locs)))
    for i, t in enumerate(times):
        moon, _, m = astro._geo_vectors(astro.utc(t))
        v = (m @ moon)[None, :] - obs
        out[i] = np.degrees(np.arcsin(np.sum(v * up, axis=1) / np.linalg.norm(v, axis=1)))
    return out


def rank(me: dict, my_loc: tuple, others: list[dict], band: str, start: datetime, hours: float = 48.0,
         step_min: float = 30.0, min_el: float = 10.0, offset_db: float = 0.0, my_ok=None) -> list[dict]:
    """For every station (dicts with call, loc (lat, lon), model), the best common window in the period and
    the estimated QSO probability there, best first."""
    times = [astro.utc(start) + timedelta(minutes=step_min * i) for i in range(int(hours * 60 / step_min) + 1)]
    others = [o for o in others if o.get("loc") and o.get("model")]
    if not others:
        return []
    el = moon_elevations(times, np.array([my_loc] + [o["loc"] for o in others], float))
    out = []
    for j, o in enumerate(others, start=1):
        common = np.minimum(el[:, 0], el[:, j])
        ok = common >= min_el
        if my_ok is not None:                      # the user's free horizon (Moon not behind obstacles)
            ok &= np.asarray(my_ok(times), bool)
        if not ok.any():
            out.append({**o, "best": None, "hours_common": 0.0, "probability": 0.0})
            continue
        i = int(np.argmax(np.where(ok, common, -99)))
        r = link_at(times[i], me, my_loc, o["model"], o["loc"], band)
        out.append({**o, "best": r, "hours_common": float(ok.sum() * step_min / 60),
                    "probability": probability(r["margin_db"], offset_db) if r else 0.0})
    return sorted(out, key=lambda x: (-x["probability"], -(x["best"] or {}).get("margin_db", -99)))


def learn_offset(pairs: list[tuple[float, float]]) -> dict:
    """Offset between reported and predicted SNR from logged QSOs (robust: median, with its spread)."""
    if not pairs:
        return {"n": 0, "offset_db": 0.0, "mad_db": None}
    d = np.array([r - p for r, p in pairs])
    med = float(np.median(d))
    return {"n": len(d), "offset_db": med, "mad_db": float(1.4826 * np.median(np.abs(d - med)))}
