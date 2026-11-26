# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Cooled LNA: how the noise of a HEMT/pHEMT LNA changes with its physical temperature (Peltier cell, dry ice,
liquid nitrogen, cryocooler) or what a dedicated cryogenic LNA gives, and the effect on the station.

Model (Pospieszalski 1989, drain and gate noise of a HEMT): most of the noise temperature scales with the
physical temperature of the transistor, a small part does not (hot electrons in the channel, the input
match, the noise of the next stages). Referred to the datasheet value Te_ref at T_ref:

    Te(T) = Te_ref · [a + (1 − a) · T / T_ref]

a ≈ 0.10 fits room-temperature GaAs pHEMT amateur LNAs cooled to cryogenic temperature (cryogenic LNAs
measured both warm and cold give 0.05–0.15, InP lower than GaAs); it is an assumption the user can change.
Peltier cells only reach some tens of kelvin below the ambient: one stage ΔT_max ≈ 65–70 K with no load,
in practice 25–40 K with the LNA heat and a small box, two stages ≈ 50–60 K."""
from __future__ import annotations

import math

T0 = 290.0
ZERO_C = 273.15
A_NONTHERMAL = 0.10            # presunto: part of Te that does not scale with the physical temperature
T_REF_C = 25.0                 # presunto: datasheet NF is given at +25 °C

# method → (label, physical temperature in °C or None = relative to ambient, delta to ambient in K)
METHODS = {
    "ambient": ("Temperatura ambiente (nessun raffreddamento)", None, 0.0),
    "peltier1": ("Cella di Peltier, 1 stadio", None, -30.0),
    "peltier2": ("Cella di Peltier, 2 stadi", None, -50.0),
    "dryice": ("Ghiaccio secco (−78 °C)", -78.5, None),
    "ln2": ("Azoto liquido (77 K)", 77.0 - ZERO_C, None),
    "cryo": ("Criocooler a ciclo chiuso (20 K)", 20.0 - ZERO_C, None),
    "custom": ("Temperatura a scelta", None, None),
}
PELTIER_MAX_DT = {"peltier1": 45.0, "peltier2": 70.0}    # deepest reachable below ambient (K), with the LNA heat


def te_of_nf(nf_db: float) -> float:
    return T0 * (10 ** (nf_db / 10) - 1)


def nf_of_te(te_k: float) -> float:
    return 10 * math.log10(1 + max(te_k, 0.0) / T0)


def cooled_te(te_ref_k: float, t_phys_k: float, t_ref_k: float = T_REF_C + ZERO_C, a: float = A_NONTHERMAL) -> float:
    """Noise temperature (K) of the LNA at physical temperature t_phys_k, from its value te_ref_k at t_ref_k."""
    a = min(max(a, 0.0), 1.0)
    return te_ref_k * (a + (1 - a) * max(t_phys_k, 0.0) / t_ref_k)


def physical_temp_c(method: str, t_amb_c: float, custom_c: float | None = None) -> tuple[float, bool]:
    """Physical temperature of the LNA (°C) for a cooling method, and True when the asked one is not reachable
    (a Peltier cell asked below its limit: the limit is used)."""
    _, fixed, delta = METHODS[method]
    if method == "custom":
        t = float(custom_c if custom_c is not None else t_amb_c)
        return max(t, -ZERO_C + 4.0), False
    if fixed is not None:
        return fixed, False
    t = t_amb_c + (delta or 0.0)
    if method in PELTIER_MAX_DT and custom_c is not None:          # the user asked a Peltier temperature
        lim = t_amb_c - PELTIER_MAX_DT[method]
        if custom_c < lim:
            return lim, True
        return min(custom_c, t_amb_c), False
    return t, False


def dew_point_c(t_c: float, rh_pct: float) -> float:
    """Dew point (°C), Magnus formula (Alduchov & Eskridge 1996)."""
    b, c = 17.625, 243.04
    g = math.log(max(rh_pct, 1.0) / 100) + b * t_c / (c + t_c)
    return c * g / (b - g)


def cooled_stage(nf_db: float, t_phys_c: float, t_ref_c: float = T_REF_C, a: float = A_NONTHERMAL) -> dict:
    """NF and Te of an LNA (datasheet NF at t_ref_c) when it works at t_phys_c."""
    te0 = te_of_nf(nf_db)
    te = cooled_te(te0, t_phys_c + ZERO_C, t_ref_c + ZERO_C, a)
    return {"te_ref_K": te0, "te_K": te, "nf_db": nf_of_te(te), "d_te_K": te - te0}


def setup_cooled(setup: dict, te_lna_k: float, cool_line: bool = False, t_phys_c: float = 25.0) -> dict:
    """A copy of a setup with the LNA at te_lna_k (nf_db of the setup is taken as the LNA's) and, if cool_line,
    the feed → LNA loss at the same physical temperature (LNA and input in the same cold box or dewar)."""
    s = dict(setup)
    s["nf_db"] = nf_of_te(te_lna_k)
    if cool_line:
        s["line_t_phys"] = t_phys_c + ZERO_C
    return s
