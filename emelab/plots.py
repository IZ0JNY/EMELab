# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Charts and fits of any parameter of the logged QSOs and measurements.

Every QSO and measurement is flattened into one row of numbers (its own fields plus every condition EMELab
computed: Moon position at both ends, distances, Doppler, spread, atmosphere, weather…). Any two columns can be
plotted against each other and fitted with:

* linear and polynomial least squares (with R², RMSE and the equation),
* LOESS (local linear regression with tricube weights, span chosen by the user) for trends without a formula,
* medians per class of X (robust, with the interquartile range) — good for small, noisy samples like QSO reports.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np

LABELS = {
    "rst_sent_db": "Rapporto inviato (dB)", "rst_rcvd_db": "Rapporto ricevuto (dB)", "snr_db": "SNR misurato (dB)",
    "y_db": "Fattore Y (dB)", "moon_el": "Elevazione Luna (°)", "moon_az": "Azimut Luna (°)", "dx_moon_el": "Elevazione Luna DX (°)",
    "dx_moon_az": "Azimut Luna DX (°)", "moon_dist_km": "Distanza Luna (km)", "path_loss_vs_perigee_db": "Perdita rispetto al perigeo (dB)",
    "mutual_spread_hz": "Mutual spread (Hz)", "mutual_doppler_hz": "Doppler mutuo (Hz)", "own_spread_hz": "Spread eco proprie (Hz)",
    "own_doppler_hz": "Doppler eco proprie (Hz)", "libration_deg_min": "Librazione (°/min)", "sun_moon_deg": "Angolo Sole–Luna (°)",
    "moon_phase_deg": "Fase lunare (°)", "moon_illum": "Illuminazione Luna", "moon_dec": "Declinazione Luna (°)",
    "atm_db": "Attenuazione atmosferica (dB)", "t_sky": "Temperatura cielo (K)", "ground_km": "Distanza a terra (km)",
    "eme_path_km": "Percorso EME (km)", "eme_delay_s": "Ritardo EME (s)", "t_c": "Temperatura (°C)", "rh": "Umidità (%)",
    "p_hpa": "Pressione (hPa)", "hour": "Ora UTC", "month": "Mese", "doy": "Giorno dell'anno", "date": "Data",
    "freq_mhz": "Frequenza (MHz)", "dx_atm_db_std": "Attenuazione DX (dB)", "sublunar_lat": "Latitudine sublunare (°)",
}
FITS = {"none": "Nessuna", "linear": "Lineare", "poly2": "Polinomiale di 2° grado", "poly3": "Polinomiale di 3° grado",
        "loess": "LOESS (tendenza locale)", "bins": "Mediane per classi"}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(str(v).replace("+", "").replace(",", ".")) if not isinstance(v, (int, float)) else float(v)
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def _utc(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _mode(q: dict) -> str:
    from .logbook import mode_label
    return mode_label(q)[0]


def rows_from_qsos(qsos: list[dict]) -> list[dict]:
    out = []
    for q in qsos:
        r = {"call": q.get("call"), "band": q.get("band"), "mode": _mode(q), "locator": q.get("locator")}
        t = _utc(q.get("utc"))
        if t:
            r.update(utc=t, date=t.timestamp() / 86400.0, hour=t.hour + t.minute / 60, month=t.month, doy=t.timetuple().tm_yday)
        for k in ("freq_mhz", "t_c", "rh", "p_hpa"):
            r[k] = _num(q.get(k))
        r["rst_sent_db"], r["rst_rcvd_db"] = _num(q.get("rst_sent")), _num(q.get("rst_rcvd"))
        for k, v in (q.get("calc") or {}).items():
            x = _num(v)
            if x is not None:
                r[k] = x
        out.append(r)
    return out


def rows_from_measurements(ms: list[dict]) -> list[dict]:
    out = []
    for m in ms:
        r = {"kind": m.get("kind"), "band": f"{m.get('band_ghz'):g} GHz" if m.get("band_ghz") else None}
        t = _utc(m.get("utc"))
        if t:
            r.update(utc=t, date=t.timestamp() / 86400.0, hour=t.hour + t.minute / 60, month=t.month, doy=t.timetuple().tm_yday)
        for k in ("y_db", "snr_db", "value", "t_c", "rh", "p_hpa", "wind_ms", "cloud_pct", "az_off", "el_off"):
            r[k] = _num(m.get(k))
        calc = m.get("calc") or {}
        for part in ("sun", "moon"):
            for k, v in (calc.get(part) or {}).items():
                x = _num(v)
                if x is not None:
                    r[f"{part}_{k}"] = x
        for k, v in calc.items():
            x = _num(v) if not isinstance(v, dict) else None
            if x is not None:
                r[k] = x
        out.append(r)
    return out


def numeric_columns(rows: list[dict]) -> list[str]:
    keys = {}
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                keys[k] = keys.get(k, 0) + 1
    return sorted((k for k, n in keys.items() if n >= 2), key=lambda k: (k not in LABELS, LABELS.get(k, k)))


def label(k: str) -> str:
    return LABELS.get(k, k)


# ------------------------------------------------------------------ fits
def loess(x: np.ndarray, y: np.ndarray, xs: np.ndarray, span: float = 0.5) -> np.ndarray:
    """Local linear regression with tricube weights over the nearest span·n points."""
    n = len(x)
    k = max(3, int(math.ceil(span * n)))
    out = np.empty_like(xs, dtype=float)
    for i, x0 in enumerate(xs):
        d = np.abs(x - x0)
        h = np.partition(d, min(k, n) - 1)[min(k, n) - 1] or 1e-12
        w = np.clip(1 - (d / h) ** 3, 0, None) ** 3
        sw = w.sum()
        if sw <= 0:
            out[i] = np.nan
            continue
        mx, my = (w * x).sum() / sw, (w * y).sum() / sw
        vx = (w * (x - mx) ** 2).sum()
        b = (w * (x - mx) * (y - my)).sum() / vx if vx > 0 else 0.0
        out[i] = my + b * (x0 - mx)
    return out


def fit(x, y, kind: str = "linear", span: float = 0.5, n_bins: int = 8) -> dict:
    """Curve for the chart and the statistics of the fit (equation, R², RMSE, residuals)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    res = {"kind": kind, "n": int(len(x))}
    if len(x) < 3 or kind == "none":
        return res
    xs = np.linspace(x.min(), x.max(), 200)
    if kind in ("linear", "poly2", "poly3"):
        deg = {"linear": 1, "poly2": 2, "poly3": 3}[kind]
        if len(x) <= deg:
            return res
        c = np.polyfit(x, y, deg)
        yhat = np.polyval(c, x)
        res.update(xs=xs, ys=np.polyval(c, xs), coef=c.tolist(), equation=equation(c))
        if deg == 1:
            n = len(x)
            s = math.sqrt(((y - yhat) ** 2).sum() / max(n - 2, 1))
            sxx = ((x - x.mean()) ** 2).sum()
            res["slope_err"] = s / math.sqrt(sxx) if sxx > 0 else float("nan")
            res["r"] = float(np.corrcoef(x, y)[0, 1]) if n > 2 else float("nan")
    elif kind == "loess":
        res.update(xs=xs, ys=loess(x, y, xs, span))
        yhat = loess(x, y, x, span)
    elif kind == "bins":
        edges = np.unique(np.quantile(x, np.linspace(0, 1, n_bins + 1)))
        idx = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, len(edges) - 2)
        bx, by, lo, hi, cnt = [], [], [], [], []
        for b in range(len(edges) - 1):
            m = idx == b
            if m.sum() == 0:
                continue
            bx.append(float(np.median(x[m]))); by.append(float(np.median(y[m])))
            lo.append(float(np.percentile(y[m], 25))); hi.append(float(np.percentile(y[m], 75))); cnt.append(int(m.sum()))
        res.update(xs=np.array(bx), ys=np.array(by), lo=np.array(lo), hi=np.array(hi), counts=cnt)
        yhat = np.interp(x, bx, by)
    else:
        raise ValueError(kind)
    resid = y - yhat
    sst = ((y - y.mean()) ** 2).sum()
    res.update(residuals=resid, x=x, rmse=float(math.sqrt((resid ** 2).mean())),
               r2=float(1 - (resid ** 2).sum() / sst) if sst > 0 else float("nan"))
    return res


def equation(c) -> str:
    deg = len(c) - 1
    terms = []
    for i, a in enumerate(c):
        p = deg - i
        t = f"{a:+.4g}"
        terms.append(t + ("·x" if p == 1 else f"·x^{p}" if p > 1 else ""))
    return "y = " + " ".join(terms).lstrip("+")


def correlations(rows: list[dict], target: str, cols: list[str] | None = None, min_n: int = 8) -> list[tuple[str, float, int]]:
    """Which parameters go with the target (Spearman rank correlation, strongest first)."""
    cols = cols or numeric_columns(rows)
    out = []
    for c in cols:
        if c == target:
            continue
        pairs = [(r[c], r[target]) for r in rows if isinstance(r.get(c), (int, float)) and isinstance(r.get(target), (int, float))]
        if len(pairs) < min_n:
            continue
        a, b = np.array(pairs, float).T
        if a.std() == 0 or b.std() == 0:
            continue
        ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
        out.append((c, float(np.corrcoef(ra, rb)[0, 1]), len(pairs)))
    return sorted(out, key=lambda t: -abs(t[1]))
