# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""💡 LNA suggestions: a dated market survey of LNA chips (MMIC dies, packaged MMICs, discrete pHEMTs, modules) from
the well-known makers for the EME bands 10–134 GHz (data/lna_market.json, refreshed by a new research run) and
design ideas per band, each part compared with the LNA of the user's configuration for that band.

Rule as in catalog.py: a number is written in the survey only when it was read on the maker's or a distributor's
page (source URL kept); everything else stays empty."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import analysis

PATH = Path(__file__).parent / "data" / "lna_market.json"
OLD_DAYS = 120                      # after this the survey is shown as old

# design ideas per band (keys as stations.band_label of the band)
IDEAS = {
    10: ["LNA direttamente sul feed (o sul relè in guida WR-90): ogni 0.1 dB di perdita prima dell'LNA vale circa 7 K.",
         "Primo stadio con pHEMT discreto a bassissimo rumore (NF 0.3–0.5 dB) adattato per il minimo rumore, poi un MMIC "
         "per il guadagno: è lo schema dei migliori LNA amatoriali a 10 GHz.",
         "Ingresso in guida con transizione guida–microstriscia a sonda: evita il connettore SMA prima del primo stadio.",
         "Un filtro dopo il primo stadio (non prima) protegge dal TX e dai radar in banda X senza peggiorare la NF."],
    24: ["Ingresso in guida WR-42 con sonda direttamente sul primo stadio: a 24 GHz un SMA e 5 cm di cavo costano 0.3–0.5 dB.",
         "MMIC in die su supporto dorato con wire-bonding corti: il package QFN aggiunge perdita e induttanza a 24 GHz.",
         "Due stadi in cascata con guadagno ≥ 25 dB, così il transverter non pesa sulla NF.",
         "Una cella di Peltier sul primo stadio vale qualche centesimo di dB (vedi ❄️ qui sopra): utile solo dopo aver tolto le perdite."],
    47: ["MMIC in die (ad es. la famiglia 25–43 GHz usata fuori banda o i 37–50 GHz) su supporto dorato, ingresso in guida WR-22.",
         "Wire-bonding il più corto possibile e doppio bond sull'ingresso: a 47 GHz 0.3 mm di filo sono già un'induttanza.",
         "Il rumore del sistema conta più del G/T teorico: un LNA vicino al feed vale più di una parabola più grande."],
    76: ["Modulo in guida WR-12 con MMIC W-band in die: a 76 GHz ogni transizione costa decimi di dB.",
         "Il raffreddamento conta: RW3BP ha raffreddato ad azoto liquido un CGY2190UH arrivando a un LNA di circa 90 K "
         "(432 and Above EME News, novembre 2016).",
         "Controlla la stabilità fuori banda: i MMIC W-band hanno guadagno anche a 40–60 GHz."],
    122: ["Sopra i 100 GHz gli LNA sono MMIC InP o mHEMT in modulo WR-8/WR-6; spesso conviene un mixer a basso rumore "
          "direttamente al feed.",
          "Verifica la NF a 122 GHz, non nella banda nominale: molti moduli D-band peggiorano ai bordi."],
    134: ["A 134 GHz si lavora con moduli WR-6 (D-band) InP o con un mixer subarmonico al feed.",
          "Il vapore acqueo pesa più dell'LNA: Tsys d'inverno e con aria secca (vedi Pianificatore)."],
}


def load(path: Path | None = None) -> dict:
    try:
        return json.loads((path or PATH).read_text(encoding="utf-8"))
    except Exception:
        return {"date": None, "makers": [], "parts": []}


def age_days(survey: dict, today: date | None = None) -> int | None:
    try:
        return ((today or date.today()) - date.fromisoformat(survey["date"])).days
    except Exception:
        return None


def in_band(p: dict, f_ghz: float, margin: float = 0.5) -> bool:
    lo, hi = p.get("f_lo_ghz"), p.get("f_hi_ghz")
    if lo is None and hi is None:
        return False
    lo = hi if lo is None else lo
    hi = lo if hi is None else hi
    return lo - margin <= f_ghz <= hi + margin


def ideas(f_ghz: float) -> list[str]:
    return IDEAS[min(IDEAS, key=lambda b: abs(b - f_ghz))]


def compare(survey: dict, f_ghz: float, setup: dict | None, t_sky: float = 15.0) -> list[dict]:
    """Parts of the survey for a band, best NF first, with the G/T change if the part replaced the LNA of the
    configuration (its NF taken as the LNA's; feed → LNA loss and antenna unchanged)."""
    rows = [dict(p) for p in survey.get("parts", []) if in_band(p, f_ghz)]
    ts0 = analysis.tsys_cold(setup, t_sky)["sys"] if setup else None
    for p in rows:
        p["d_gt_db"] = None
        if setup and p.get("nf_db") is not None:
            ts = analysis.tsys_cold(dict(setup, nf_db=float(p["nf_db"])), t_sky)["sys"]
            import math
            p["d_gt_db"] = 10 * math.log10(ts0 / ts)
    rows.sort(key=lambda p: (p.get("nf_db") is None, p.get("nf_db") or 0))
    return rows
