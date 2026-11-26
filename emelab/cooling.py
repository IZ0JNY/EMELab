# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Cooling of a power device: passive finned heat sink, the same sink with a fan, water-cooled cold plate.

Each method gives a sink-to-coolant thermal resistance R (K/W) and a heat capacity C (J/K). The junction follows
the transmit period within milliseconds, the sink with the time constant τ = R·C: with EME T/R periods of 60 s a
big passive sink (τ ≈ 10 min) sees the average power, a cold plate (τ ≈ seconds) the full power of every
transmission. The periodic steady state of a first-order system driven by a square wave gives the sink peak:

    ΔT_peak = P·R·(1 − e^(−t_on/τ)) / (1 − e^(−T/τ))      (t_on = duty·T, T = TX + RX period)

Heat-transfer correlations (plate-fin sink, isothermal base):
- natural convection, vertical fins: Bar-Cohen & Rohsenow (1984) plus radiation from the envelope;
- forced air through the fin channels: Teertstra, Yovanovich & Culham (1999), developing laminar flow;
- the air (or water) warms along the sink: R = 1 / (ṁ·cp·(1 − e^(−G/(ṁ·cp)))) (effectiveness, NTU);
- cold plate: R given at a reference flow by its maker, convective part scaled as flow^−0.8.

Lifetime: Arrhenius, MTTF(Tj) = MTTF_ref · exp(Ea/k · (1/Tj − 1/T_ref)), the model behind every «MTTF vs channel
temperature» chart in GaN and GaAs datasheets."""
from __future__ import annotations

import math

K_B = 8.617333e-5                     # eV/K
SIGMA = 5.670374e-8                   # W/(m²·K⁴)
K_AL = 200.0                          # W/(m·K), aluminium alloy 6063
RHO_AL, CP_AL = 2700.0, 900.0
CP_CU = 385.0
# air at about 45 °C
AIR = {"rho": 1.11, "cp": 1007.0, "k": 0.0275, "nu": 1.75e-5, "pr": 0.71}
COOLANTS = {"acqua": {"rho": 995.0, "cp": 4180.0, "h_factor": 1.0},
            "acqua + glicole 30 %": {"rho": 1040.0, "cp": 3700.0, "h_factor": 0.75}}

# Arrhenius activation energy (eV) and a reference MTTF (h) at a reference channel temperature (°C): typical of
# GaN-on-SiC and GaAs pHEMT foundry reliability reports. Assumed: read the «MTTF vs Tch» chart of your device.
LIFE = {"GaN": {"ea_ev": 1.7, "mttf_h": 1e7, "t_ref_c": 200.0},
        "GaAs": {"ea_ev": 1.5, "mttf_h": 1e7, "t_ref_c": 150.0},
        "SiGe": {"ea_ev": 1.0, "mttf_h": 1e7, "t_ref_c": 150.0},
        "LDMOS / MOSFET": {"ea_ev": 1.0, "mttf_h": 1e7, "t_ref_c": 175.0}}
TECH_ALIAS = {"LDMOS": "LDMOS / MOSFET", "MOSFET": "LDMOS / MOSFET", "Si": "LDMOS / MOSFET"}
TJ_MAX = {"GaN": 225.0, "GaAs": 150.0, "SiGe": 150.0, "LDMOS / MOSFET": 200.0}
RJC_TYP = {"GaN": 1.5, "GaAs": 4.0, "SiGe": 10.0, "LDMOS / MOSFET": 0.5}      # K/W, typical power device (assumed)

# default plate-fin sink (assumed): 15 × 20 cm base, 8 mm thick, 15 fins 40 × 2 mm
SINK = {"w_cm": 15.0, "l_cm": 20.0, "base_mm": 8.0, "fin_h_mm": 40.0, "n_fins": 15, "fin_t_mm": 2.0, "emiss": 0.85}


def _sink_geom(s: dict) -> dict:
    w, l = s["w_cm"] / 100, s["l_cm"] / 100
    tb, hf, tf, n = s["base_mm"] / 1000, s["fin_h_mm"] / 1000, s["fin_t_mm"] / 1000, max(int(s["n_fins"]), 2)
    gap = max((w - n * tf) / (n - 1), 1e-4)
    vol = w * l * tb + n * tf * hf * l
    return {"w": w, "l": l, "tb": tb, "hf": hf, "tf": tf, "n": n, "gap": gap,
            "a_fin": 2 * n * hf * l, "a_base": (n - 1) * gap * l, "a_flow": (n - 1) * gap * hf,
            "a_env": w * l + 2 * (hf + tb) * l + 2 * w * (hf + tb),
            "c_jk": vol * RHO_AL * CP_AL, "mass_kg": vol * RHO_AL}


def _fin_eff(h: float, g: dict) -> float:
    m = math.sqrt(2 * h / (K_AL * g["tf"]))
    x = m * g["hf"]
    return math.tanh(x) / x if x > 1e-9 else 1.0


def _g_conv(h: float, g: dict) -> float:
    return h * (_fin_eff(h, g) * g["a_fin"] + g["a_base"])


def h_natural(g: dict, dt_k: float, t_amb_c: float) -> float:
    """Natural convection in vertical parallel-plate channels (Bar-Cohen & Rohsenow), W/(m²·K)."""
    dt = max(dt_k, 0.5)
    t_film = t_amb_c + 273.15 + dt / 2
    alpha = AIR["nu"] / AIR["pr"]
    ra_s = 9.81 / t_film * dt * g["gap"] ** 3 / (AIR["nu"] * alpha)
    el = max(ra_s * g["gap"] / g["l"], 1e-6)
    nu = (576 / el ** 2 + 2.873 / math.sqrt(el)) ** -0.5
    return nu * AIR["k"] / g["gap"]


def h_forced(g: dict, u_ms: float) -> float:
    """Forced air in the fin channels, developing laminar flow (Teertstra et al.), W/(m²·K)."""
    re_s = max(u_ms, 1e-6) * g["gap"] / AIR["nu"]
    rs = re_s * g["gap"] / g["l"]
    pr = AIR["pr"]
    nu = ((rs * pr / 2) ** -3 + (0.664 * math.sqrt(rs) * pr ** (1 / 3) * math.sqrt(1 + 3.65 / math.sqrt(rs))) ** -3) ** (-1 / 3)
    return nu * AIR["k"] / g["gap"]


def _ntu_r(g_wk: float, mcp: float) -> float:
    return 1 / (mcp * (1 - math.exp(-g_wk / mcp)))


def _r_from_datasheet(sink: dict, method: str, p_avg_w: float, flow_m3h=None, through=0.5) -> dict:
    """Heat sink picked from the catalogue: R from its datasheet instead of the geometry."""
    from emelab import cooling_parts as cp
    m = cp.sink_mass(sink)
    out = {"c_jk": m * CP_AL, "mass_kg": m, "datasheet": True}
    if method == "passivo":
        if not sink.get("r_nat_kw"):                       # tunnel heat sink without its fan: assumed ×3
            r = sink["r_fan_kw"] * 3
        else:
            dt = 30.0
            for _ in range(30):
                r = cp.sink_r_natural(sink, dt)
                dt = 0.5 * dt + 0.5 * max(p_avg_w, 1e-6) * r
        return {**out, "r_kw": r}
    r, u = cp.sink_r_fan(sink, flow_m3h, through)
    q = max((flow_m3h or 0) * through, 1e-3) / 3600
    return {**out, "r_kw": r, "u_ms": u, "air_rise_k_per_w": 1 / (AIR["rho"] * AIR["cp"] * q)}


def r_passive(sink: dict, p_avg_w: float, t_amb_c: float) -> dict:
    """Passive sink: natural convection + radiation; h depends on the temperature rise, so iterate."""
    if sink.get("r_nat_kw") or sink.get("r_fan_kw"):
        return _r_from_datasheet(sink, "passivo", p_avg_w)
    g = _sink_geom(sink)
    dt = 30.0
    for _ in range(40):
        h = h_natural(g, dt, t_amb_c)
        ts, ta = t_amb_c + 273.15 + dt, t_amb_c + 273.15
        h_rad = sink.get("emiss", 0.85) * SIGMA * (ts ** 2 + ta ** 2) * (ts + ta)
        gt = _g_conv(h, g) + h_rad * g["a_env"]
        new = max(p_avg_w, 1e-6) / gt
        if abs(new - dt) < 0.01:
            break
        dt = 0.5 * dt + 0.5 * new
    return {"r_kw": 1 / gt, "c_jk": g["c_jk"], "h": h, "h_rad": h_rad, "mass_kg": g["mass_kg"], "geom": g}


def r_forced(sink: dict, flow_m3h: float, through: float = 0.5) -> dict:
    """The same sink with a fan: free-air flow × the fraction that really goes through the fins."""
    if sink.get("r_nat_kw") or sink.get("r_fan_kw"):
        return _r_from_datasheet(sink, "ventilato", 0.0, flow_m3h, through)
    g = _sink_geom(sink)
    q = max(flow_m3h * through, 1e-3) / 3600
    u = q / g["a_flow"]
    h = h_forced(g, u)
    gc = _g_conv(h, g)
    mcp = AIR["rho"] * AIR["cp"] * q
    return {"r_kw": _ntu_r(gc, mcp), "c_jk": g["c_jk"], "h": h, "u_ms": u, "mass_kg": g["mass_kg"],
            "air_rise_k_per_w": 1 / mcp, "geom": g}


def r_water(flow_lmin: float, r_ref_kw: float = 0.04, flow_ref_lmin: float = 2.0, coolant: str = "acqua",
            mass_kg: float = 0.25) -> dict:
    """Water cold plate: R (plate to inlet coolant) from the maker at a reference flow; the convective part
    scales as flow^−0.8 (turbulent) and the coolant warming is added with the NTU relation."""
    c = COOLANTS.get(coolant, COOLANTS["acqua"])
    w = COOLANTS["acqua"]
    mcp_ref = w["rho"] * w["cp"] * flow_ref_lmin / 60000
    # the datasheet R includes the warming of water at the reference flow: take it apart
    g_ref = -mcp_ref * math.log(max(1 - 1 / (r_ref_kw * mcp_ref), 1e-9)) if r_ref_kw * mcp_ref > 1 else 1 / r_ref_kw
    g = g_ref * c["h_factor"] * (max(flow_lmin, 0.01) / flow_ref_lmin) ** 0.8
    mcp = c["rho"] * c["cp"] * max(flow_lmin, 0.01) / 60000
    cap = mass_kg * CP_CU + 0.05 * c["rho"] / 1000 * c["cp"]     # copper plate + ~50 cm³ of coolant inside
    return {"r_kw": _ntu_r(g, mcp), "c_jk": cap, "rise_k_per_w": 1 / mcp, "mass_kg": mass_kg}


def peak_factor(tau_s: float, duty: float, period_s: float) -> float:
    """Sink peak rise / (P·R) for a square wave (TX duty·T, then RX) in periodic steady state."""
    if duty >= 1:
        return 1.0
    if tau_s <= 0:
        return 1.0
    t_on = duty * period_s
    return (1 - math.exp(-t_on / tau_s)) / (1 - math.exp(-period_s / tau_s))


def solve(method: str, p_diss_w: float, n_dev: int, rth_jc: float, rth_cs: float, t_ref_c: float, duty: float,
          period_s: float, **kw) -> dict:
    """Junction temperature at the end of a transmission for one cooling method.

    t_ref_c is the air temperature (passive, fan) or the coolant inlet temperature (water). The sink carries
    n_dev devices, each dissipating p_diss_w; every junction adds its own P·(R_jc + R_cs)."""
    p_tot = p_diss_w * max(int(n_dev), 1)
    if method == "passivo":
        r = r_passive(kw["sink"], p_tot * duty, t_ref_c)
    elif method == "ventilato":
        r = r_forced(kw["sink"], kw["flow_m3h"], kw.get("through", 0.5))
    else:
        r = r_water(kw["flow_lmin"], kw.get("r_ref_kw", 0.04), kw.get("flow_ref_lmin", 2.0), kw.get("coolant", "acqua"),
                    kw.get("mass_kg", 0.25))
    tau = r["r_kw"] * r["c_jk"]
    f = peak_factor(tau, duty, period_s)
    t_sink = t_ref_c + p_tot * r["r_kw"] * f
    t_case = t_sink + p_diss_w * rth_cs
    tj = t_case + p_diss_w * rth_jc
    t_off = (1 - min(duty, 1.0)) * period_s
    sink_swing = (t_sink - t_ref_c) * (1 - math.exp(-t_off / tau)) if tau > 0 and duty < 1 else 0.0
    return {**r, "tau_s": tau, "peak_factor": f, "t_sink_c": t_sink, "t_case_c": t_case, "tj_c": tj,
            "t_sink_avg_c": t_ref_c + p_tot * r["r_kw"] * duty,
            "tj_swing_k": (p_diss_w * (rth_jc + rth_cs) + sink_swing) if duty < 1 else 0.0}


def _bisect(fn, lo: float, hi: float, it: int = 60) -> float:
    for _ in range(it):
        mid = (lo + hi) / 2
        if fn(mid):
            lo = mid
        else:
            hi = mid
    return lo


def max_p_diss(method: str, tj_target_c: float, duty: float, **args) -> float:
    """Largest dissipation per device that keeps the junction at or below the target."""
    def ok(p):
        return solve(method, p, duty=duty, **args)["tj_c"] <= tj_target_c
    if not ok(1e-3):
        return 0.0
    hi = 1.0
    while ok(hi) and hi < 1e5:
        hi *= 2
    return _bisect(ok, 0.0, hi)


def max_duty(method: str, p_diss_w: float, tj_target_c: float, **args) -> float | None:
    """Largest transmit fraction at this power (1 = continuous allowed; None = not even a single short TX)."""
    def ok(d):
        return solve(method, p_diss_w, duty=d, **args)["tj_c"] <= tj_target_c
    if ok(1.0):
        return 1.0
    if not ok(1e-4):
        return None
    return _bisect(ok, 0.0, 1.0, 40)


def p_out_from_diss(p_diss_w: float, pae_pct: float) -> float:
    e = min(max(pae_pct / 100, 1e-3), 0.999)
    return p_diss_w * e / (1 - e)


def mttf_h(tj_c: float, ea_ev: float, mttf_ref_h: float, t_ref_c: float) -> float:
    """Arrhenius: median time to failure at junction temperature tj_c."""
    return mttf_ref_h * math.exp(ea_ev / K_B * (1 / (tj_c + 273.15) - 1 / (t_ref_c + 273.15)))


def life_factor(tj_hot_c: float, tj_cool_c: float, ea_ev: float) -> float:
    """How many times longer the device lives at tj_cool_c than at tj_hot_c."""
    return math.exp(ea_ev / K_B * (1 / (tj_cool_c + 273.15) - 1 / (tj_hot_c + 273.15)))


def schedule(kind: str, tr_s: float, cq_tx: int = 10, qso_tx: int = 6, minutes: float = 30.0,
             cool_min: float = 10.0) -> list[tuple[float, bool]]:
    """Transmit/receive sequence as (duration s, transmitting). «ciclo»: TX/RX alternated for `minutes`;
    «qso»: cq_tx calls (TX, RX, TX…), then qso_tx transmissions of the QSO, then cool_min minutes of listening."""
    if kind == "qso":
        n = max(int(cq_tx), 0) + max(int(qso_tx), 1)
        seq = [(tr_s, True), (tr_s, False)] * n
        return seq + [(cool_min * 60, False)]
    n = max(int(round(minutes * 60 / (2 * tr_s))), 1)
    return [(tr_s, True), (tr_s, False)] * n


def simulate(method: str, p_diss_w: float, n_dev: int, rth_jc: float, rth_cs: float, t_ref_c: float,
             seq: list[tuple[float, bool]], dt_s: float = 1.0, **kw) -> dict:
    """Junction and sink temperature against time from a cold start (sink at the reference temperature).

    Sink: one thermal RC node, exact exponential step for piecewise-constant power. Junction: follows the sink
    within milliseconds, T_j = T_sink + P·(R_jc + R_cs) while transmitting."""
    duty = sum(d for d, tx in seq if tx) / max(sum(d for d, _ in seq), 1e-9)
    base = solve(method, p_diss_w, n_dev, rth_jc, rth_cs, t_ref_c, max(duty, 1e-3), 120.0, **kw)
    r, tau = base["r_kw"], max(base["tau_s"], 1e-6)
    p_tot = p_diss_w * max(int(n_dev), 1)
    a = math.exp(-dt_s / tau)
    t, ts = 0.0, t_ref_c
    out_t, out_j, out_s = [0.0], [t_ref_c], [t_ref_c]
    for dur, tx in seq:
        steps = max(int(round(dur / dt_s)), 1)
        p = p_tot if tx else 0.0
        for _ in range(steps):
            ts = t_ref_c + (ts - t_ref_c) * a + p * r * (1 - a)
            t += dt_s
            out_t.append(t)
            out_s.append(ts)
            out_j.append(ts + (p_diss_w * (rth_jc + rth_cs) if tx else 0.0))
    return {"t_s": out_t, "tj_c": out_j, "t_sink_c": out_s, "tj_max_c": max(out_j), "tau_s": tau, "r_kw": r}


def device_thermal(dev: dict | None) -> dict:
    """Thermal data of the device chosen in the amplifier: technology, R_jc, Tj max and PAE, from its fields or
    from the «rth_jc=…, tj_max=…, pae_pct=…» the datasheet reader writes in the notes. Missing → None."""
    import re
    dev = dev or {}
    tech = TECH_ALIAS.get(dev.get("tech") or "", dev.get("tech"))
    out = {"tech": tech if tech in LIFE else None, "rth_jc": None, "tj_max": None, "pae_pct": None}
    for k in ("rth_jc", "tj_max", "pae_pct"):
        v = dev.get(k)
        if v is None:
            m = re.search(rf"\b{k}\s*=\s*([0-9.]+)", dev.get("notes") or "")
            v = float(m.group(1)) if m else None
        out[k] = float(v) if v is not None else None
    return out
