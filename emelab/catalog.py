# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Catalogue of devices used by microwave EME stations at 10, 24 and 47 GHz (power amplifiers, LNAs, waveguide
switches, transverters, tubes) and the tools to complete it from the manufacturers' datasheets.

Rule: a number is written here only when it comes from a datasheet or from the station page that uses the
device; everything else is left empty (None) and EMELab asks the user to read it from the datasheet. Entries
marked check=True carry typical values to be confirmed on the current datasheet at the actual frequency.
The user's own devices are added to the local parts library (parts.py) and stay on this PC."""
from __future__ import annotations

import re
import urllib.parse

TYPES = {"PA": "Amplificatore di potenza (SSPA / MMIC)", "TWT": "Tubo a onda progressiva", "LNA": "LNA",
         "SW": "Commutatore in guida / relè coassiale", "TRV": "Transverter"}
TJ_MAX = {"GaN": 225.0, "GaAs": 150.0, "SiGe": 150.0, "LDMOS": 200.0}    # typical absolute maximum (°C)

DEVICES = [
    # LNA ------------------------------------------------------------------------------------------------------
    dict(part="CGY2260UH/C1", maker="MACOM", type="LNA", f_lo=25.0, f_hi=43.0, gain_db=25.0, nf_db=1.8, tech="GaAs",
         notes="MMIC a 3 stadi, 1.68 × 3.0 mm; NF < 1.8 dB in banda. Usato a 47 GHz (fuori banda nominale) nel DFH47.",
         source="datasheet MACOM / pagina 47 GHz IZ0JNY", check=False),
    dict(part="DFH47GHz", maker="EA5DOM · EB3FRN · EA3HMJ", type="LNA", f_lo=47.0, f_hi=47.2, gain_db=None, nf_db=None,
         tech="GaAs", notes="LNA su CGY2260UH/C1, supporto in alluminio dorato, wire-bonding. Misura NF e guadagno a 47 GHz.",
         source="pagina 47 GHz IZ0JNY", check=False),
    dict(part="LNA 24 GHz WR-42", maker="DU3T", type="LNA", f_lo=24.0, f_hi=24.25, nf_db=1.3, tech="GaAs",
         notes="ingresso in guida WR-42, montaggio al fuoco", source="pagina 24 GHz IZ0JNY", check=False),
    dict(part="XLNA-mk2 10 GHz", maker="DU3T", type="LNA", f_lo=10.0, f_hi=10.5, tech="GaAs",
         notes="alimentazione 9 V da regolatore lineare", source="pagina 10 GHz IZ0JNY", check=False),
    dict(part="HMC751", maker="Analog Devices", type="LNA", f_lo=17.0, f_hi=27.0, gain_db=25.0, nf_db=2.2, tech="GaAs",
         notes="MMIC LNA 17–27 GHz", source="datasheet", check=True),
    dict(part="HMC1040", maker="Analog Devices", type="LNA", f_lo=24.0, f_hi=43.5, gain_db=23.0, nf_db=2.2, tech="GaAs",
         notes="MMIC LNA 24–43.5 GHz", source="datasheet", check=True),
    dict(part="HMC565", maker="Analog Devices", type="LNA", f_lo=6.0, f_hi=20.0, gain_db=21.0, nf_db=2.5, tech="GaAs",
         notes="MMIC LNA 6–20 GHz (secondo stadio a 10 GHz)", source="datasheet", check=True),
    # cryogenic LNA (noise temperature with the amplifier at about 5 K; cryo_k = physical temperature) ------------
    dict(part="LNF-LNC6_20SC", maker="Low Noise Factory", type="LNA", f_lo=6.0, f_hi=20.0, gain_db=32.0, nf_db=0.06,
         tech="InP", cryo_k=5.0, notes="LNA criogenico 6–20 GHz: 3.8 K di rumore raffreddato (dati misurati a 296 K e a 5 K)",
         source="datasheet LNF 2023-03-03", check=True),
    dict(part="LNF-LNC23_42B", maker="Low Noise Factory", type="LNA", f_lo=23.0, f_hi=42.0, gain_db=27.0, nf_db=0.12,
         tech="InP", cryo_k=5.0, notes="LNA criogenico 23–42 GHz: 8.2 K di rumore raffreddato (dati misurati a 296 K e a 5 K)",
         source="datasheet LNF 2023-03-01", check=True),
    dict(part="CLNA-30-0800-1200-5P-ND", maker="Narda-MITEQ", type="LNA", f_lo=8.0, f_hi=12.0, gain_db=30.0, nf_db=0.12,
         tech="InP", cryo_k=4.0, notes="LNA criogenico 8–12 GHz, 8 K tipici (mHEMT/InP fino a 4 K)",
         source="nardamiteq.com, LNA criogenici", check=True),
    # power ----------------------------------------------------------------------------------------------------
    dict(part="QPA1010", maker="Qorvo", type="PA", f_lo=7.9, f_hi=11.0, psat_dbm=41.8, tech="GaN",
         notes="MMIC GaN su SiC, circa 15 W in banda X; usato a 10 GHz da IZ0JNY", source="datasheet Qorvo", check=True),
    dict(part="QPA1022", maker="Qorvo", type="PA", f_lo=8.5, f_hi=11.0, psat_dbm=36.0, tech="GaN",
         notes="MMIC GaN su SiC, circa 4 W in banda X", source="datasheet", check=True),
    dict(part="SSPA 10 GHz 7 W", maker="IK3GHY (autocostruito)", type="PA", f_lo=10.3, f_hi=10.5, psat_dbm=38.5,
         notes="6 W al feed nel setup 10 GHz di IZ0JNY", source="pagina 10 GHz IZ0JNY", check=False),
    dict(part="RW1136", maker="Siemens", type="TWT", f_lo=24.0, f_hi=24.25, psat_dbm=42.6, vdc=48.0, tech="TWT",
         notes="TWT modificato per 24 GHz; 18.2 W misurati al feed con twist WR-42 diretto (14 W con guida flessibile)",
         source="pagina nuovo setup 24 GHz IZ0JNY", check=False),
    dict(part="SSPA 47 GHz 50 W", maker="OK1DFC (autocostruito)", type="PA", f_lo=47.0, f_hi=47.2, psat_dbm=47.0, tech="GaN",
         notes="raffreddato a liquido, efficienza circa 33 %; 45 W misurati in aprile 2026", source="432 and Above EME News 04/2026",
         check=False),
    # switches -------------------------------------------------------------------------------------------------
    dict(part="45512H-1002", maker="Hughes", type="SW", f_lo=None, f_hi=None,
         notes="commutatore in guida per onde millimetriche (scheda di controllo IZ0JNY)", source="pagina IZ0JNY", check=True),
    dict(part="Commutatore WR-42", maker="DU3T", type="SW", f_lo=18.0, f_hi=26.5, notes="usato a 24 GHz con il TWT",
         source="pagina 24 GHz IZ0JNY", check=False),
    dict(part="Commutatore WR-75", maker="—", type="SW", f_lo=10.0, f_hi=15.0, notes="nel setup 10 GHz su piastra unica",
         source="pagina 10 GHz IZ0JNY", check=False),
    # transverters ---------------------------------------------------------------------------------------------
    dict(part="10G5", maker="Kuhne electronic", type="TRV", f_lo=10.368, f_hi=10.45, source="pagina 10 GHz IZ0JNY", check=True),
    dict(part="47G2", maker="Kuhne electronic", type="TRV", f_lo=47.0, f_hi=47.2, source="pagina 47 GHz IZ0JNY", check=True),
]


def in_band(d: dict, f_ghz: float, margin: float = 0.5) -> bool:
    """a device with no frequency range is shown on every band"""
    lo, hi = d.get("f_lo"), d.get("f_hi")
    if lo is None and hi is None:
        return True
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    return lo - margin <= f_ghz <= hi + margin


def for_band(f_ghz: float, kind: str | None = None) -> list[dict]:
    return [d for d in DEVICES if (not kind or d["type"] == kind) and in_band(d, f_ghz)]


def search_links(part: str, maker: str = "") -> dict[str, str]:
    q = urllib.parse.quote_plus
    p = part.strip()
    return {"Datasheet (web)": f"https://duckduckgo.com/?q={q(f'{maker} {p} datasheet pdf'.strip())}",
            "Octopart": f"https://octopart.com/search?q={q(p)}",
            "Mouser": f"https://www.mouser.com/c/?q={q(p)}",
            "Digi-Key": f"https://www.digikey.com/en/products/result?keywords={q(p)}"}


# ------------------------------------------------------------------ reading a datasheet PDF
_NUM = r"(-?\d+(?:[.,]\d+)?)"
PATTERNS = {
    "gain_db": rf"(?:small[- ]signal\s+)?gain[^\n\d-]{{0,40}}{_NUM}\s*dB(?!m)",
    "nf_db": rf"noise\s+figure[^\n\d]{{0,40}}{_NUM}\s*dB",
    "p1db_dbm": rf"(?:P1dB|output\s+power\s+(?:for|at)\s+1\s*dB\s+compression)[^\n\d-]{{0,40}}{_NUM}\s*dBm",
    "psat_dbm": rf"(?:Psat|saturated\s+output\s+power)[^\n\d-]{{0,40}}{_NUM}\s*dBm",
    "vdc": rf"(?:Vdd|Vd|drain\s+(?:supply\s+)?voltage)[^\n\d-]{{0,30}}{_NUM}\s*V\b",
    "idc_a": rf"(?:Idd|Idq|drain\s+current)[^\n\d-]{{0,30}}{_NUM}\s*(mA|A)\b",
    "rth_jc": rf"(?:thermal\s+resistance|R\s*th|θ\s*JC|R\s*θ\s*JC)[^\n\d]{{0,50}}{_NUM}\s*°?\s*C\s*/\s*W",
    "tj_max": rf"(?:junction|channel)\s+temperature[^\n\d]{{0,40}}{_NUM}\s*°?\s*C",
    "pae_pct": rf"(?:PAE|power[- ]added\s+efficiency)[^\n\d]{{0,40}}{_NUM}\s*%",
    "f_range": r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*GHz",
}


_NUMS = rf"((?:-?\d+(?:[.,]\d+)?\s+){{0,2}}-?\d+(?:[.,]\d+)?)"     # 1 to 3 numbers: a value or min / typ / max columns


_MAX_COLUMN = ("nf_db", "idc_a", "rth_jc")     # with two columns these are "typ max", the others "min typ"


def _typ(nums: str, k: str) -> float:
    v = [float(x.replace(",", ".")) for x in nums.split()]
    if len(v) == 3:
        return v[1]
    return v[0] if len(v) == 1 or k in _MAX_COLUMN else v[1]


def read_datasheet(text: str) -> dict:
    """Candidate values found in a datasheet's text, for the user to confirm.

    A value written alone ("Gain 21 dB") is taken as it is; in a table row with min / typ / max columns
    ("Noise Figure 1.8 2.2 2.6 dB") the middle (typical) one is taken when there are three numbers; with two, the
    first for noise figure, current and thermal resistance ("typ max"), the second for the others ("min typ"). The PDF line each value comes from is returned in out["_lines"], so the user can check it."""
    t = re.sub(r"[ \t]+", " ", text)
    out, lines = {}, {}
    for k, rx in PATTERNS.items():
        if k != "f_range":
            rx = rx.replace(_NUM, _NUMS, 1)
        m = re.search(rx, t, re.I)
        if not m:
            continue
        a, b = t.rfind("\n", 0, m.start()) + 1, t.find("\n", m.end())
        lines[k] = t[a:b if b >= 0 else len(t)].strip()[:160]
        if k == "f_range":
            out["f_lo"], out["f_hi"] = float(m.group(1)), float(m.group(2))
        elif k == "idc_a":
            v = _typ(m.group(1), k)
            out[k] = v / 1000 if m.group(2) == "mA" else v
        else:
            out[k] = _typ(m.group(1), k)
    if lines:
        out["_lines"] = lines
    return out


# ------------------------------------------------------------------ heat sink
H_CONV = {"naturale": 7.0, "ventola": 35.0, "ventola forte": 70.0}       # W/(m²·K), effective, finned aluminium


def heatsink(p_out_w: float, pae_pct: float, rth_jc: float, rth_cs: float = 0.2, t_amb_c: float = 35.0,
             tj_target_c: float = 150.0, duty: float = 0.5, p_dc_w: float | None = None) -> dict:
    """Heat-sink sizing for one power device.

    P_diss = P_DC − P_out (P_DC from the PAE if not given). The junction follows the transmit period within
    milliseconds, the heat sink averages over minutes: T_sink = T_amb + duty·P_diss·R_sa and
    T_j = T_sink + P_diss·(R_jc + R_cs). The largest R_sa that keeps T_j ≤ target is the heat sink to buy; the
    finned area is estimated for natural convection and with a fan (effective h, fin efficiency included)."""
    p_dc = p_dc_w if p_dc_w else p_out_w / max(pae_pct / 100, 1e-3)
    pd = max(p_dc - p_out_w, 0.0)
    margin = tj_target_c - t_amb_c - pd * (rth_jc + rth_cs)
    rsa = margin / (duty * pd) if pd > 0 else float("inf")
    area = {k: (1 / (h * rsa) if rsa > 0 and rsa != float("inf") else float("nan")) for k, h in H_CONV.items()}
    return {"p_dc_w": p_dc, "p_diss_w": pd, "rsa_max": rsa, "ok": rsa > 0, "area_m2": area,
            "tj_continuous_c": t_amb_c + pd * (rth_jc + rth_cs + (rsa if rsa > 0 else 0)),
            "t_sink_c": t_amb_c + duty * pd * (rsa if rsa > 0 else 0)}
