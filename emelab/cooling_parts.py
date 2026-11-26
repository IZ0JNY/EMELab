# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Catalogue of cooling parts for the amplifier: heat sinks, fans, water cold plates, pumps, thermal pastes and pads.

Same rules as the device catalogue: catalogue values are typical (⚠️ to confirm on the current datasheet); what the
user types or reads from a datasheet PDF goes into a local library (settings.json, this PC only) marked ✅ verified,
which overrides the catalogue entry with the same part and maker and can be reverted to it.

Fields (all optional except part, maker, cat):
- dissipatore: r_nat_kw (natural convection, at dt_ref_k), r_fan_kw (fan-cooled with its own fan), w_mm, h_mm,
  l_mm (along the fins / air), mass_kg
- ventola: flow_m3h (free air), p_max_pa (static pressure), size_mm
- piastra: r_kw at flow_lmin, dp_kpa at the same flow, mass_kg
- pompa: h_max_m (max head), q_max_lmin (max flow)
- tim (paste, pad, foil): k_wmk, t_um (bond line or pad thickness), rc_m2kw (two contact interfaces), insulating
"""
from __future__ import annotations

import math
import re

CATS = {"dissipatore": "🧱 Dissipatori", "ventola": "🌀 Ventole", "piastra": "💧 Piastre ad acqua",
        "pompa": "⛽ Pompe", "radiatore": "🌬️ Radiatori", "chiller": "❄️ Chiller", "tim": "🧴 Paste e pad termici"}

# typical values: confirm them on the datasheet of the exact version you buy (length, fan voltage…)
CATALOG = [
    # heat sinks: profiles for natural convection (R at ΔT 75 K, datasheet convention) and tunnel heat sinks with fan
    dict(cat="dissipatore", part="SK 47 · 100 mm", maker="Fischer Elektronik", r_nat_kw=1.0, w_mm=112, h_mm=40, l_mm=100,
         mass_kg=0.45, notes="profilo alettato per convezione naturale"),
    dict(cat="dissipatore", part="SK 89 · 150 mm", maker="Fischer Elektronik", r_nat_kw=0.55, w_mm=165, h_mm=38, l_mm=150,
         mass_kg=1.0, notes="profilo largo, base spessa"),
    dict(cat="dissipatore", part="SK 92 · 200 mm", maker="Fischer Elektronik", r_nat_kw=0.38, w_mm=200, h_mm=40, l_mm=200,
         mass_kg=1.8, notes="per SSPA da 50–100 W dissipati"),
    dict(cat="dissipatore", part="LA 6 · 150 mm 12 V", maker="Fischer Elektronik", r_fan_kw=0.20, w_mm=60, h_mm=60, l_mm=150,
         mass_kg=0.55, notes="dissipatore a tunnel con ventola compresa"),
    dict(cat="dissipatore", part="LAM 4 · 100 mm 12 V", maker="Fischer Elektronik", r_fan_kw=0.30, w_mm=40, h_mm=40, l_mm=100,
         mass_kg=0.25, notes="tunnel piccolo con ventola, per MMIC da 10–30 W dissipati"),
    dict(cat="dissipatore", part="LAM 5 D · 150 mm 24 V", maker="Fischer Elektronik", r_fan_kw=0.12, w_mm=50, h_mm=100, l_mm=150,
         mass_kg=0.9, notes="tunnel doppio con ventola"),
    dict(cat="dissipatore", part="Dissipatore CPU a torre (generico)", maker="—", r_fan_kw=0.18, w_mm=125, h_mm=150, l_mm=50,
         mass_kg=0.7, notes="heat pipe con ventola 120 mm: base piccola, buono per un solo MMIC"),
    # fans (free-air flow and static pressure from the maker)
    dict(cat="ventola", part="NF-A8 PWM", maker="Noctua", flow_m3h=55.7, p_max_pa=21.6, size_mm=80),
    dict(cat="ventola", part="NF-A12x25 PWM", maker="Noctua", flow_m3h=102.1, p_max_pa=23.0, size_mm=120),
    dict(cat="ventola", part="NF-A14 PWM", maker="Noctua", flow_m3h=140.2, p_max_pa=20.0, size_mm=140),
    dict(cat="ventola", part="AFB1212SH", maker="Delta Electronics", flow_m3h=175.0, p_max_pa=80.0, size_mm=120,
         notes="industriale, rumorosa, molta pressione: buona su alette fitte"),
    dict(cat="ventola", part="Ventola 80 mm 12 V (generica)", maker="—", flow_m3h=40.0, p_max_pa=25.0, size_mm=80),
    # water cold plates: R from plate to inlet coolant for one small heat source, pressure drop at the same flow
    dict(cat="piastra", part="CP10G01 (rame, 4 passaggi)", maker="Boyd (Lytron)", r_kw=0.03, flow_lmin=3.8, dp_kpa=14.0,
         mass_kg=0.45, notes="tubo di rame in piastra di alluminio, 15 cm"),
    dict(cat="piastra", part="Waterblock CPU in rame (generico)", maker="—", r_kw=0.04, flow_lmin=4.0, dp_kpa=12.0, mass_kg=0.25,
         notes="microcanali, base 40×40 mm: ottimo per un MMIC"),
    dict(cat="piastra", part="Piastra alluminio con 2 tubi (generica)", maker="—", r_kw=0.08, flow_lmin=2.0, dp_kpa=4.0,
         mass_kg=0.3),
    # pumps: head (m of water) at zero flow and flow at zero head
    dict(cat="pompa", part="D5 (Vario, velocità 5)", maker="Xylem / Laing", h_max_m=3.9, q_max_lmin=25.0),
    dict(cat="pompa", part="DDC-1T", maker="Xylem / Laing", h_max_m=4.5, q_max_lmin=7.0),
    dict(cat="pompa", part="Pompa da kit AIO PC (generica)", maker="—", h_max_m=1.5, q_max_lmin=4.0),
    dict(cat="pompa", part="DC40 12 V (pompa solare)", maker="—", h_max_m=5.0, q_max_lmin=8.0),
    # radiators: pressure drop at a flow, and the coolant-to-air resistance with its fans
    dict(cat="radiatore", part="Radiatore 240 mm rame (2 ventole)", maker="—", r_kw=0.04, flow_lmin=2.0, dp_kpa=3.0),
    dict(cat="radiatore", part="Radiatore 120 mm alluminio (1 ventola)", maker="—", r_kw=0.10, flow_lmin=2.0, dp_kpa=2.0),
    # chillers with their own pump (common ones for laser tubes, often sold on AliExpress): a passive one is a
    # radiator with fan (W per °C above the air), a compressor or Peltier one keeps the set point up to its capacity
    dict(cat="chiller", part="CW-3000", maker="VEVOR", kind="passivo", r_kw=0.02, h_max_m=10.0, q_max_lmin=10.0,
         tank_l=9.0, source="manuale CW-3000 (50 W/°C, pompa 10 m e 10 L/min, serbatoio 9 L)",
         notes="il chiller di IZ0JNY (versione normale, non PRO): radiatore con ventola e serbatoio da 9 L, niente "
               "compressore, non scende sotto l'aria"),
    dict(cat="chiller", part="CW-3000", maker="S&A Teyu (e cloni)", kind="passivo", r_kw=0.02, h_max_m=10.0, q_max_lmin=10.0,
         notes="nessun compressore: 50 W/°C, il liquido resta sopra l'aria"),
    dict(cat="chiller", part="CW-5000", maker="S&A Teyu (e cloni)", kind="compressore", cap_w=750.0, h_max_m=10.0,
         q_max_lmin=10.0, t_set_min_c=5.0, notes="a compressore, set point 5–35 °C"),
    dict(cat="chiller", part="CW-5200", maker="S&A Teyu (e cloni)", kind="compressore", cap_w=1400.0, h_max_m=12.0,
         q_max_lmin=13.0, t_set_min_c=5.0),
    dict(cat="chiller", part="Mini chiller Peltier (generico)", maker="—", kind="compressore", cap_w=70.0, h_max_m=2.0,
         q_max_lmin=4.0, t_set_min_c=15.0, notes="cella di Peltier: poca potenza, bene solo per MMIC piccoli"),
    # thermal interface materials: conductivity, typical bond line / pad thickness
    dict(cat="tim", part="MX-4", maker="Arctic", k_wmk=8.5, t_um=30, rc_m2kw=4e-6, insulating=True),
    dict(cat="tim", part="Kryonaut", maker="Thermal Grizzly", k_wmk=12.5, t_um=30, rc_m2kw=4e-6, insulating=True),
    dict(cat="tim", part="NT-H2", maker="Noctua", k_wmk=8.0, t_um=30, rc_m2kw=4e-6, insulating=True,
         notes="conducibilità non dichiarata dal produttore: valore presunto"),
    dict(cat="tim", part="Pasta al silicone bianca (generica)", maker="—", k_wmk=0.8, t_um=50, rc_m2kw=6e-6, insulating=True),
    dict(cat="tim", part="Conductonaut (metallo liquido)", maker="Thermal Grizzly", k_wmk=73.0, t_um=20, rc_m2kw=2e-6,
         insulating=False, notes="conduce corrente e corrode l'alluminio: solo rame o nichel"),
    dict(cat="tim", part="Carbonaut (pad di grafite 0.2 mm)", maker="Thermal Grizzly", k_wmk=62.5, t_um=200, rc_m2kw=1e-5,
         insulating=False, notes="riutilizzabile, conduce corrente"),
    dict(cat="tim", part="Foglio di indio 0.1 mm", maker="Indium Corporation", k_wmk=86.0, t_um=100, rc_m2kw=5e-6,
         insulating=False, notes="serve pressione di montaggio; classico per GaN su flangia"),
    dict(cat="tim", part="Tflex 700 (0.5 mm)", maker="Laird", k_wmk=5.0, t_um=500, rc_m2kw=1e-5, insulating=True),
    dict(cat="tim", part="Gap Pad 1500 (0.5 mm)", maker="Bergquist (Henkel)", k_wmk=1.5, t_um=508, rc_m2kw=1e-5, insulating=True),
    dict(cat="tim", part="Sil-Pad 400 (isolante 0.18 mm)", maker="Bergquist (Henkel)", k_wmk=0.9, t_um=180, rc_m2kw=1e-5,
         insulating=True, notes="isola elettricamente il case dal dissipatore"),
]
NUM_FIELDS = {
    "dissipatore": [("r_nat_kw", "R naturale (K/W)"), ("r_fan_kw", "R con ventola (K/W)"), ("w_mm", "Larghezza (mm)"),
                    ("h_mm", "Altezza (mm)"), ("l_mm", "Lunghezza (mm)"), ("mass_kg", "Massa (kg)")],
    "ventola": [("flow_m3h", "Portata (m³/h)"), ("p_max_pa", "Pressione statica (Pa)"), ("size_mm", "Lato (mm)")],
    "piastra": [("r_kw", "R piastra (K/W)"), ("flow_lmin", "alla portata (L/min)"), ("dp_kpa", "Perdita di carico (kPa)"),
                ("mass_kg", "Massa (kg)")],
    "pompa": [("h_max_m", "Prevalenza massima (m)"), ("q_max_lmin", "Portata massima (L/min)")],
    "radiatore": [("r_kw", "R liquido–aria (K/W)"), ("flow_lmin", "alla portata (L/min)"), ("dp_kpa", "Perdita di carico (kPa)")],
    "chiller": [("cap_w", "Potenza frigorifera (W)"), ("r_kw", "R liquido–aria se passivo (K/W)"),
                ("h_max_m", "Prevalenza massima (m)"), ("q_max_lmin", "Portata massima (L/min)")],
    "tim": [("k_wmk", "Conducibilità (W/m·K)"), ("t_um", "Spessore (µm)")],
}
RHO_G = 9.81 * 995.0                                          # Pa per metre of water


def _key(p: dict) -> tuple[str, str, str]:
    return p["cat"], p["part"].strip().lower(), (p.get("maker") or "—").strip().lower()


def parts(cat: str, library: list[dict] | None = None) -> list[dict]:
    """Catalogue + local library for one category; a library entry with the same part and maker replaces the
    catalogue one (origin «edited», catalogue values kept under «catalog»), the others are «mine»."""
    lib = {_key(p): p for p in (library or []) if p.get("cat") == cat}
    out = []
    for c in CATALOG:
        if c["cat"] != cat:
            continue
        k = _key(c)
        if k in lib:
            out.append({**c, **lib.pop(k), "origin": "edited", "catalog": dict(c), "verified": 1})
        else:
            out.append({**c, "origin": "catalog", "check": True})
    out += [{**p, "origin": "mine", "verified": 1} for p in lib.values()]
    return out


def save(library: list[dict], entry: dict) -> list[dict]:
    """Library with this entry added or replaced (same category, part and maker)."""
    e = {k: v for k, v in entry.items() if k not in ("origin", "catalog", "check")}
    e["verified"] = 1
    return [p for p in library if _key(p) != _key(e)] + [e]


def revert(library: list[dict], entry: dict) -> list[dict]:
    return [p for p in library if _key(p) != _key(entry)]


# ------------------------------------------------------------------ thermal interface
def r_tim(k_wmk: float, t_um: float, area_mm2: float, rc_m2kw: float = 5e-6) -> float:
    """Case-to-sink resistance of a paste, pad or foil: bulk t/(k·A) plus the two contact interfaces."""
    a = max(area_mm2, 0.1) * 1e-6
    return (t_um * 1e-6) / (max(k_wmk, 1e-3) * a) + rc_m2kw / a


# ------------------------------------------------------------------ heat sink from its datasheet
FAN_FACTOR = [(0.0, 1.0), (1.0, 0.55), (2.0, 0.40), (3.0, 0.33), (4.0, 0.28), (6.0, 0.22), (10.0, 0.17)]


def _interp(pts, x):
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def sink_r_natural(hs: dict, dt_k: float, dt_ref_k: float = 75.0) -> float:
    """Natural-convection R of a catalogue profile at the actual temperature rise (h ∝ ΔT^¼, so R ∝ ΔT^−¼)."""
    return hs["r_nat_kw"] * (dt_ref_k / max(dt_k, 2.0)) ** 0.25


def sink_r_fan(hs: dict, flow_m3h: float | None, through: float) -> tuple[float, float]:
    """R of a catalogue heat sink with air blowing along it, and the air speed in m/s. A tunnel heat sink with its own
    fan has r_fan_kw; a profile uses its natural R times the usual «R vs air speed» factor of profile datasheets."""
    area = max((hs.get("w_mm") or 100) * (hs.get("h_mm") or 40), 1.0) * 1e-6
    u = (flow_m3h or 0.0) * through / 3600 / area
    if hs.get("r_fan_kw") and not hs.get("r_nat_kw"):
        return hs["r_fan_kw"], u
    return hs["r_nat_kw"] * _interp(FAN_FACTOR, u), u


def sink_mass(hs: dict) -> float:
    if hs.get("mass_kg"):
        return hs["mass_kg"]
    v = (hs.get("w_mm") or 100) * (hs.get("h_mm") or 40) * (hs.get("l_mm") or 100) * 1e-9
    return 0.35 * v * 2700                                   # a finned profile is about 35 % metal


# ------------------------------------------------------------------ water loop: pump against the loop
def loop_point(pump: dict, parts_dp: list[tuple[float, float]], extra_k: float = 0.0) -> dict:
    """Operating point of a pump on a loop. Pump: Δp = p_max·(1 − (Q/Q_max)²). Every loop part has Δp ∝ Q²
    (turbulent), given as (Δp kPa at flow L/min). Returns the flow and the pressure drop of each part."""
    p_max = pump["h_max_m"] * RHO_G / 1000                 # kPa
    qm = pump["q_max_lmin"]
    k = extra_k + sum(dp / max(q, 1e-3) ** 2 for dp, q in parts_dp)      # kPa/(L/min)²
    q = math.sqrt(p_max / (p_max / qm ** 2 + k)) if k > 0 else qm
    return {"flow_lmin": q, "dp_pump_kpa": k * q ** 2, "p_max_kpa": p_max,
            "dp_parts_kpa": [dp / max(qq, 1e-3) ** 2 * q ** 2 for dp, qq in parts_dp]}


def coolant_inlet(source: dict, p_avg_w: float, t_air_c: float, t_set_c: float | None = None) -> dict:
    """Coolant temperature going into the cold plate. Radiator or passive chiller: air + P·R. Compressor or
    Peltier chiller: its set point while the average heat stays under its capacity; above, it can no longer hold it
    and the excess warms the coolant (assumed 0.05 K/W of extra radiator)."""
    if source.get("kind") == "compressore":
        t0 = max(t_set_c if t_set_c is not None else 25.0, source.get("t_set_min_c") or 5.0)
        over = max(p_avg_w - (source.get("cap_w") or 0.0), 0.0)
        return {"t_in_c": t0 + over * 0.05, "over_w": over, "load": p_avg_w / max(source.get("cap_w") or 1e-9, 1e-9)}
    return {"t_in_c": t_air_c + p_avg_w * (source.get("r_kw") or 0.05), "over_w": 0.0, "load": None}


TUBE_DP = {"corti (≤ 1 m, 10 mm)": (1.0, 2.0), "medi (2–3 m, 10 mm)": (3.0, 2.0), "lunghi (5 m, 8 mm)": (12.0, 2.0)}


# ------------------------------------------------------------------ datasheet PDF reader
_N = r"(\d+(?:[.,]\d+)?)"
PATTERNS = {
    "dissipatore": {"r_nat_kw": rf"(?:R\s*th|thermal\s+resistance|resistenza\s+termica|Wärmewiderstand)[^\n\d]{{0,50}}{_N}\s*(?:K|°C)\s*/\s*W",
                    "l_mm": rf"(?:length|lunghezza|Länge)[^\n\d]{{0,20}}{_N}\s*mm",
                    "w_mm": rf"(?:width|larghezza|Breite)[^\n\d]{{0,20}}{_N}\s*mm",
                    "h_mm": rf"(?:height|altezza|Höhe)[^\n\d]{{0,20}}{_N}\s*mm"},
    "ventola": {"flow_m3h": rf"{_N}\s*m\s*[³3]\s*/\s*h", "flow_cfm": rf"{_N}\s*CFM",
                "p_max_pa": rf"{_N}\s*Pa\b", "p_max_mmh2o": rf"{_N}\s*mm\s*H\s*2?\s*O"},
    "piastra": {"r_kw": rf"(?:thermal\s+resistance|R\s*th|resistenza)[^\n\d]{{0,50}}{_N}\s*(?:K|°C)\s*/\s*W",
                "flow_lmin": rf"{_N}\s*(?:l|L)\s*/\s*min", "flow_gpm": rf"{_N}\s*gpm",
                "dp_kpa": rf"{_N}\s*kPa", "dp_psi": rf"{_N}\s*psi"},
    "pompa": {"h_max_m": rf"(?:head|prevalenza|Förderhöhe)[^\n\d]{{0,30}}{_N}\s*m\b",
              "q_max_lmin": rf"{_N}\s*(?:l|L)\s*/\s*min", "q_max_lh": rf"{_N}\s*(?:l|L)\s*/\s*h"},
    "chiller": {"cap_w": rf"(?:cooling\s+capacity|potenza\s+frigorifera|capacit[àa])[^\n\d]{{0,30}}{_N}\s*W",
                "h_max_m": rf"(?:lift|head|prevalenza)[^\n\d]{{0,30}}{_N}\s*m\b",
                "q_max_lmin": rf"{_N}\s*(?:l|L)\s*/\s*min"},
    "radiatore": {"dp_kpa": rf"{_N}\s*kPa", "flow_lmin": rf"{_N}\s*(?:l|L)\s*/\s*min"},
    "tim": {"k_wmk": rf"{_N}\s*W\s*/\s*\(?\s*m\s*[·.\-*]?\s*K\s*\)?", "t_um": rf"{_N}\s*(?:µm|um|μm)", "t_mm": rf"(?:thickness|spessore)[^\n\d]{{0,20}}{_N}\s*mm"},
}
_CONV = {"flow_cfm": ("flow_m3h", 1.699), "p_max_mmh2o": ("p_max_pa", 9.807), "flow_gpm": ("flow_lmin", 3.785),
         "dp_psi": ("dp_kpa", 6.895), "q_max_lh": ("q_max_lmin", 1 / 60), "t_mm": ("t_um", 1000.0)}


def read_datasheet(text: str, cat: str) -> dict:
    """Values found in the text of a cooling-part datasheet; units converted (CFM, gpm, psi, mm H₂O, L/h, mm);
    the line each one comes from is in out["_lines"] so the user can check it."""
    t = re.sub(r"[ \t]+", " ", text)
    out, lines = {}, {}
    for k, rx in PATTERNS.get(cat, {}).items():
        m = re.search(rx, t, re.I)
        if not m:
            continue
        v = float(m.group(1).replace(",", "."))
        dst, f = _CONV.get(k, (k, 1.0))
        if dst in out:
            continue
        out[dst] = round(v * f, 4)
        a, b = t.rfind("\n", 0, m.start()) + 1, t.find("\n", m.end())
        lines[dst] = t[a:b if b >= 0 else len(t)].strip()[:160]
    if lines:
        out["_lines"] = lines
    return out
