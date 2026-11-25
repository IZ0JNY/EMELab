# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EME Assistant invites you to measure and to try: the measurements that teach the station model the most right now,
missing or old calibrations, opportunities (Sun high today, perigee, dry days, active stations), and what to try
after a QSO. Each suggestion has a priority (higher first) and a short reason."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import astro, db as edb, planner


def _age_days(rows, kind, band=None):
    ts = [edb.parse_utc(r["utc"]) for r in rows if r["kind"] == kind and (band is None or abs((r.get("band_ghz") or 0) - band) < 1)]
    return (datetime.now(timezone.utc) - max(ts)).days if ts else None


def _sun_today(stn, now):
    """Highest Sun elevation in the next 24 h (time and elevation)."""
    best = None
    for k in range(0, 24 * 6):
        t = now + timedelta(minutes=10 * k)
        s = astro.sky(t, stn["lat"], stn["lon"], stn.get("height_m") or 0.0)
        if best is None or s.sun.el > best[1]:
            best = (t, s.sun.el, s.sun.az)
    return best


def suggestions(D: edb.DB, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    stn = D.station()
    out = []

    def add(prio, text, why=""):
        out.append({"priority": prio, "text": text, "why": why})

    if not (stn.get("lat") or stn.get("lon")):
        return [{"priority": 100, "text": "Inserisci la posizione della stazione (scheda Stazione): serve a tutto il resto.", "why": ""}]
    setups = D.setups()
    if not setups:
        add(95, "Crea una configurazione per ogni banda caricando un file di progetto FeedLab.")
    rows = D.measurements()
    for s in setups:
        b = s["band_ghz"]
        tag = f"{b:.3f} GHz"
        sun = [r for r in rows if r["kind"] == "sun" and r.get("setup_id") == s["id"]]
        if len(sun) < 3:
            add(80, f"{tag}: registra almeno 3 misure di rumore solare (oggi ne hai {len(sun)}): servono per la prima "
                    "stima dell'efficienza e del G/T reali.")
        else:
            els = sorted((r.get("calc") or {}).get("sun", {}).get("el") or 0 for r in sun)
            if els and els[-1] - els[0] < 15:
                add(60, f"{tag}: le misure di Sole sono tutte tra {els[0]:.0f}° e {els[-1]:.0f}° di elevazione: misura "
                        "anche più in alto e più in basso per separare atmosfera, rumore di terra e stazione.")
        if _age_days(rows, "focus") is None:
            add(55, f"{tag}: non hai ancora una curva di messa a fuoco del feed (spostamento assiale a passi di λ/4).")
        if not [r for r in rows if r["kind"] == "ground" and r.get("setup_id") == s["id"]]:
            add(45, f"{tag}: misura il rapporto terra/cielo: controlla preamplificatore e spillover in un minuto.")
        age = _age_days([r for r in rows if r.get("setup_id") == s["id"]], "sun")
        if age is not None and age > 30:
            add(40, f"{tag}: l'ultima misura di Sole è di {age} giorni fa: ripetila per vedere se la stazione è cambiata.")
    pts = [((r.get("calc") or {}).get(r["kind"]) or {}).get("az") for r in rows
           if r.get("az_off") is not None and r["kind"] in ("sun", "moon")]
    pts = [p for p in pts if p is not None]
    if len(pts) < 6:
        add(70, f"Puntamento: servono almeno 6 misure di correzione al picco su Sole e Luna (ne hai {len(pts)}), a "
                "elevazioni e azimut diversi, per calcolare il modello di puntamento.")
    else:
        for lo in range(0, 360, 90):
            if not any(lo <= p < lo + 90 for p in pts):
                add(50, f"Puntamento: nessuna misura con azimut tra {lo}° e {lo + 90}°: aggiungine qualcuna su Sole o Luna.")
    t, el, az = _sun_today(stn, now)
    if el > 10:
        add(65, f"Il Sole culmina a {el:.0f}° di elevazione alle {t:%H:%M} UTC (AZ {az:.0f}°): buon momento per una misura "
                "di rumore solare e una scansione (larghezza del fascio, correzione di puntamento).")
    try:
        per = [p for p in planner.perigees(now, 20) if p[2] == "perigeo"]
        if per:
            d = (per[0][0] - now).days
            if 0 <= d <= 5:
                add(60, (f"Perigeo oggi ({per[0][0]:%H:%M} UTC)" if d == 0 else f"Perigeo tra {d} giorni ({per[0][0]:%Y-%m-%d})") + ": eco fino a 2 dB più forti, buon periodo per prove "
                        "di eco e QSO a 24 e 47 GHz.")
    except Exception:
        pass
    qs = D.qsos()
    if not qs:
        add(35, "Importa il tuo log ADIF: dai QSO già fatti EME Assistant ricava le condizioni che funzionano per te.")
    st_heard = [s for s in D.stations() if (s.get("data") or {}).get("heard")]
    if not st_heard:
        add(30, "Importa ALL.TXT di WSJT-X: EME Assistant saprà quali stazioni hai davvero ascoltato e quando.")
    return sorted(out, key=lambda x: -x["priority"])
