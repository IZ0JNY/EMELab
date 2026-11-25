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
