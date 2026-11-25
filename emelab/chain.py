# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Station chain design: receive (Friis noise figure and system temperature, contribution of every stage) and
transmit (power at the feed, compression margin, DC power and heat). A stage is a dict:
{"name", "gain_db" (negative for a loss), "nf_db" (for a passive loss = its loss at 290 K), "p1db_dbm", "psat_dbm",
 "vdc", "idc_a", "part", "datasheet"}."""
from __future__ import annotations

import math

T0 = 290.0


def db2lin(x):
    return 10 ** (x / 10)


def lin2db(x):
    return 10 * math.log10(x)


def passive(name: str, loss_db: float, t_phys: float = 290.0) -> dict:
    """A cable, waveguide, relay or adapter: gain = −loss, noise temperature (L−1)·T_phys."""
    te = (db2lin(loss_db) - 1) * t_phys
    return {"name": name, "gain_db": -loss_db, "nf_db": lin2db(1 + te / T0), "passive": True}


def rx_chain(stages: list[dict], t_ant: float = 40.0) -> dict:
    """Cascade (Friis): total gain, noise figure, equivalent noise temperature at the feed, Tsys with the antenna,
    and how many kelvin each stage adds referred to the feed."""
    g_cum = 1.0
    te_tot = 0.0
    contrib = []
    for s in stages:
        te = (db2lin(s["nf_db"]) - 1) * T0
        add = te / g_cum
        contrib.append({"name": s["name"], "te_K": te, "added_K": add})
        te_tot += add
        g_cum *= db2lin(s["gain_db"])
    tsys = t_ant + te_tot
    for c in contrib:
        c["share_pct"] = 100 * c["added_K"] / te_tot if te_tot > 0 else 0.0
    return {"gain_db": lin2db(g_cum), "te_K": te_tot, "nf_db": lin2db(1 + te_tot / T0), "tsys_K": tsys, "stages": contrib}


def rapp_dbm(p_lin_dbm: float, psat_dbm: float, s: float = 2.0) -> float:
    """Rapp model of a solid-state amplifier: P_out = P_lin / (1 + (P_lin/P_sat)^s)^(1/s) (power form, smoothness s;
    s ≈ 2 typical of GaAs/GaN SSPAs, large s → hard limiter)."""
    pl, ps = 10 ** (p_lin_dbm / 10), 10 ** (psat_dbm / 10)
    return 10 * math.log10(pl / (1 + (pl / ps) ** s) ** (1 / s))


def tx_chain(p_in_dbm: float, stages: list[dict]) -> dict:
    """Power through the chain (Rapp compression per active stage, margin to P1dB reported), DC power and heat."""
    p = p_in_dbm
    rows = []
    pdc = 0.0
    for s in stages:
        lin = p + s["gain_db"]
        if not s.get("passive") and s.get("psat_dbm") is not None:
            out = rapp_dbm(lin, s["psat_dbm"], s.get("rapp_s", 2.0))
        else:
            out = lin
        margin = (s["p1db_dbm"] - out) if s.get("p1db_dbm") is not None else None
        dc = (s.get("vdc") or 0) * (s.get("idc_a") or 0)
        pdc += dc
        rows.append({"name": s["name"], "p_in_dbm": p, "p_out_dbm": out, "p1db_margin_db": margin, "dc_w": dc})
        p = out
    p_w = 10 ** ((p - 30) / 10)
    return {"p_out_dbm": p, "p_out_w": p_w, "dc_w": pdc, "heat_w": max(pdc - p_w, 0.0), "stages": rows}


def what_if_echo_db(d_tx_db: float = 0.0, d_gt_db: float = 0.0) -> float:
    """Own-echo SNR change: transmit power change + G/T change (the antenna gain counts in both)."""
    return d_tx_db + d_gt_db


# ------------------------------------------------------------------ travelling-wave tube (Saleh model)
SALEH = {"aa": 2.1587, "ba": 1.1517, "ap": 4.0033, "bp": 9.1040}      # Saleh 1981, typical TWT


def saleh(p_in_dbm: float, psat_dbm: float, g0_db: float, k: dict = SALEH) -> tuple[float, float]:
    """TWT output power (dBm) and AM/PM phase shift (°) for an input power, scaled so that the peak of the
    AM/AM curve is P_sat and the small-signal gain is G0 (Saleh, IEEE Trans. Commun. 1981)."""
    aa, ba, ap, bp = k["aa"], k["ba"], k["ap"], k["bp"]
    a_max = aa / (2 * math.sqrt(ba))
    psat = 10 ** (psat_dbm / 10)
    p_ref = aa ** 2 * psat / (a_max ** 2 * 10 ** (g0_db / 10))       # input power that maps to r = 1
    r = math.sqrt(10 ** (p_in_dbm / 10) / p_ref)
    a = aa * r / (1 + ba * r ** 2)
    phi = ap * r ** 2 / (1 + bp * r ** 2)
    return 10 * math.log10(max(a ** 2 * psat / a_max ** 2, 1e-30)), math.degrees(phi)


def saleh_drive_for_sat(psat_dbm: float, g0_db: float, k: dict = SALEH) -> float:
    """Input power (dBm) that saturates the tube (peak of the AM/AM curve)."""
    a_max = k["aa"] / (2 * math.sqrt(k["ba"]))
    p_ref = k["aa"] ** 2 * 10 ** (psat_dbm / 10) / (a_max ** 2 * 10 ** (g0_db / 10))
    return 10 * math.log10(p_ref / k["ba"])


# ------------------------------------------------------------------ SSPA helpers
def combine(p_one_dbm: float, n: int, combiner_loss_db: float = 0.3, phase_err_deg: float = 0.0) -> float:
    """N equal amplifiers combined: 10·log N, minus the combiner loss and the amplitude/phase imbalance loss."""
    eff = (1 + (n - 1) * math.cos(math.radians(phase_err_deg)) ** 2) / n if n > 1 else 1.0
    return p_one_dbm + 10 * math.log10(n * eff) - (combiner_loss_db if n > 1 else 0.0)


def heatsink_rth(p_diss_w: float, t_amb_c: float = 35.0, t_base_max_c: float = 70.0, duty: float = 0.5) -> float:
    """Thermal resistance (K/W) the heat sink must not exceed for the given dissipation and duty cycle
    (Q65 = 50 %: TX one period, RX the next — the sink averages over minutes)."""
    p = max(p_diss_w * duty, 1e-9)
    return (t_base_max_c - t_amb_c) / p


# ------------------------------------------------------------------ pointing
def pointing_budget(hpbw_deg: float, terms_deg: dict[str, float]) -> dict:
    """Root-sum-square of independent pointing errors and the loss it causes on a Gaussian beam, one way
    (−12·(θ/HPBW)² dB) and two way (own echoes and sun noise see it twice in TX + RX)."""
    rss = math.sqrt(sum(v ** 2 for v in terms_deg.values()))
    one = -12 * (rss / hpbw_deg) ** 2
    return {"rss_deg": rss, "loss_one_way_db": one, "loss_echo_db": 2 * one, "fraction_hpbw": rss / hpbw_deg,
            "terms": {k: (v, -12 * (v / hpbw_deg) ** 2) for k, v in terms_deg.items()}}


def encoder_step_deg(bits: int) -> float:
    return 360.0 / 2 ** bits
