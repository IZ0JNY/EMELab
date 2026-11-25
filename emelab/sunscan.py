# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Sun scan: the Sun's disc convolved with a Gaussian antenna beam (idea and erf model: Ivan De Cesaris IZ0JNY,
"Sun disk ⊗ antenna beam (Gaussian)", 2026).

* HPBW ≈ k·λ/D (k = 70° by default), σ = HPBW / (2√(2 ln 2)), Gaussian beam B(θ) = exp(−θ²/2σ²).
* 1D strip model (IZ0JNY): P(θ) = ∫_{θ−R}^{θ+R} B(φ) dφ = σ√(π/2)·[erf((θ+R)/(√2σ)) − erf((θ−R)/(√2σ))].
* 2D disc model: a scan across a uniform disc weights each strip by its chord, P(θ) = ∫_{−R}^{R} 2√(R²−x²)·B(θ−x) dx.
* Pointing loss: energy collected in a window of half-width Δ centred at the offset µ, compared with the centred
  window, times an empirical band factor G (IZ0JNY: 1.05 at 10 GHz, 1.2 at 24 GHz, 1.5 at 47 GHz).
* Fit of a measured drift scan → true HPBW (the Sun's size removed) and pointing offset."""
from __future__ import annotations

import math

import numpy as np

C = 299792458.0
SUN_DIAM_DEG = 0.53
G_BAND = {10: 1.05, 24: 1.2, 47: 1.5}


def hpbw_deg(f_ghz: float, D_m: float, k_deg: float = 70.0) -> float:
    return k_deg * (C / (f_ghz * 1e9)) / D_m


def k_from_taper(edge_taper_db: float) -> float:
    """Beamwidth constant k (degrees) of HPBW = k·λ/D for a given edge taper: (1.02 + 0.0135·taper) rad;
    ≈ 58.4° for uniform illumination, ≈ 66° at 10 dB, ≈ 69° at 13.5 dB, ≈ 70° at 15 dB (W1GHZ: beamwidth depends
    on the taper)."""
    return math.degrees(1.02 + 0.0135 * edge_taper_db)


def baars_width(hpbw: float, sun_diam: float = SUN_DIAM_DEG) -> float:
    """Width of the scan of a uniform disc with a Gaussian beam (Baars 1973 approximation):
    θ_scan² ≈ θ_beam² + (ln 2 / 2)·θ_disc². Error of the scan width (EMELab check against the 2D disc model): −1.6 % at
    θ_beam = θ_disc, −3 % at 0.8, −5.5 % at 0.66 (24 GHz, 2.4 m), −10 % at 0.5, −20 % at 0.3 (47 GHz, 2.4 m).
    Use fit_scan() (full 2D model) whenever the beam is narrower than the Sun."""
    return math.sqrt(hpbw ** 2 + math.log(2) / 2 * sun_diam ** 2)


def beam_from_scan_width(width: float, sun_diam: float = SUN_DIAM_DEG) -> float:
    """Inverse of baars_width: true HPBW from the measured −3 dB width of a Sun scan."""
    return math.sqrt(max(width ** 2 - math.log(2) / 2 * sun_diam ** 2, 1e-12))


def sigma_of(hpbw: float) -> float:
    return hpbw / (2 * math.sqrt(2 * math.log(2)))


def scan_strip(theta, hpbw: float, sun_diam: float = SUN_DIAM_DEG):
    """IZ0JNY erf model (1D strip of width 2R)."""
    from scipy.special import erf
    s, R = sigma_of(hpbw), sun_diam / 2
    th = np.asarray(theta, float)
    return s * math.sqrt(math.pi / 2) * (erf((th + R) / (math.sqrt(2) * s)) - erf((th - R) / (math.sqrt(2) * s)))


def scan_disc(theta, hpbw: float, sun_diam: float = SUN_DIAM_DEG, n: int = 401):
    """2D uniform disc scanned through its centre (chord-weighted strips)."""
    s, R = sigma_of(hpbw), sun_diam / 2
    x = np.linspace(-R, R, n)
    w = 2 * np.sqrt(np.maximum(R * R - x * x, 0.0))
    th = np.atleast_1d(np.asarray(theta, float))
    return np.trapezoid(w[None, :] * np.exp(-((th[:, None] - x[None, :]) ** 2) / (2 * s * s)), x, axis=1)


def pointing_loss_db(mu: float, delta: float, hpbw: float, f_ghz: float | None = None, model: str = "disc",
                     sun_diam: float = SUN_DIAM_DEG) -> float:
    """Loss (dB, ≤ 0) of the energy in a window [µ−Δ, µ+Δ] compared with the centred one (× band factor G)."""
    f = scan_disc if model == "disc" else scan_strip
    t1 = np.linspace(mu - delta, mu + delta, 201)
    t0 = np.linspace(-delta, delta, 201)
    e1 = np.trapezoid(f(t1, hpbw, sun_diam), t1)
    e0 = np.trapezoid(f(t0, hpbw, sun_diam), t0)
    g = 1.0
    if f_ghz:
        g = G_BAND[min(G_BAND, key=lambda b: abs(b - f_ghz))]
    return 10 * math.log10(e1 / e0) * g


def fit_scan(theta_deg, power_lin, sun_diam: float = SUN_DIAM_DEG, model: str = "disc") -> dict:
    """Fit a measured scan (angle in degrees on the sky, linear power above the cold-sky baseline or including it)
    with baseline + amplitude × model(θ − θ0): returns the beam HPBW, the pointing offset θ0 and the measured −3 dB width."""
    from scipy.optimize import least_squares
    th = np.asarray(theta_deg, float)
    p = np.asarray(power_lin, float)
    f = scan_disc if model == "disc" else scan_strip
    i0 = int(np.argmax(p))
    base0, amp0 = float(np.percentile(p, 5)), float(p.max() - np.percentile(p, 5))
    half = th[p - base0 > amp0 / 2]
    w0 = float(half.max() - half.min()) if half.size > 1 else 0.5

    def res(x):
        b, a, t0, hp = x
        m = f(th - t0, max(hp, 1e-3), sun_diam)
        return b + a * m / m.max() - p if m.max() > 0 else p * 0 + 1e3

    r = least_squares(res, [base0, amp0, float(th[i0]), max(w0 * 0.8, 0.05)],
                      bounds=([-np.inf, 0, th.min(), 0.01], [np.inf, np.inf, th.max(), 20]))
    b, a, t0, hp = r.x
    return {"hpbw_deg": float(hp), "offset_deg": float(t0), "measured_width_deg": w0, "baseline": float(b),
            "amplitude": float(a), "y_db": float(10 * math.log10((a + b) / b)) if b > 0 else float("nan"),
            "rms": float(np.sqrt(np.mean(r.fun ** 2)))}


def drift_angle(t_s, dec_deg: float):
    """Sky angle (°) swept by a drift scan in t seconds: 15″/s × cos(δ) = 0.25°/min × cos(δ)."""
    return np.asarray(t_s, float) * (0.25 / 60) * math.cos(math.radians(dec_deg))
