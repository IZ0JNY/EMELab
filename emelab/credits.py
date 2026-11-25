# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Author, sources and acknowledgements of EME Assistant."""
from __future__ import annotations

AUTHOR = "Ivan De Cesaris, IZ0JNY"
REPO = "https://github.com/IZ0JNY/EMELab"

SOURCES = [
    ("Doug McArthur VK3UM (SK)", "EMECalc, EME Planner, Libration Calculator, Atmosphere, «Sun noise and measurements»: "
     "il riferimento per calcolo, pianificazione e librazione EME", "https://www.vk5dj.com/doug.html"),
    ("John Drew VK5DJ", "custodisce i programmi di VK3UM; routine di calcolo Duffett-Smith/Meeus del Planner",
     "https://www.vk5dj.com/doug.html"),
    ("Gerald Ihninger OE2IGL e Joachim Köppen DF3GJ", "EME Link Budget & Analysis Tool (1–300 GHz): equazione radar, Beam "
     "Width Factor, modello termico della Luna, riflettività lunare, Sole, atmosfera, soglie Q65, puntamento",
     "https://wettersat.bplaced.net/EME/EME.html"),
    ("Charlie Suckling G3WDG", "librazione e spread in EME, DUBUS 3/2010", ""),
    ("J.V. Evans", "Radar Studies of the Moon, J. Res. NBS 69D (1965): riflettività lunare",
     "https://nvlpubs.nist.gov/nistpubs/jres/69D/jresv69Dn12p1637_A1b.pdf"),
    ("Charlie Suckling G3WDG / DL3WDG", "soglie di decodifica Q65 (60D, 60E, 120E) in funzione del mutual spread, "
     "dalle curve usate nel calcolatore di OE2IGL/DF3GJ", ""),
    ("Costantino IC8TEM", "YAEC – Yet Another EME Calc: idee per il rischio di polarizzazione (Dpol), l'orizzonte libero e "
     "gli ostacoli, la pianificazione dei giorni migliori, la prova della stazione su Sole, Luna e terreno e il controllo dei "
     "calcoli passo passo", "https://github.com/ic8tem/YAEC"),
    ("Joe Taylor K1JT", "WSJT-X lib/astro.f90: sfasamento spaziale della polarizzazione (Dpol)", "https://wsjt.sourceforge.io/"),
    ("José EA3HMJ", "EA3HMJ Tracking Software Suite (DriverDish, DishController, Astroserver, SNserver): file DriftScan e "
     "corrections.txt, server telnet e server delle effemeridi letti da EME Assistant", "https://github.com/EA3HMJ-Tracking-Software-Suite"),
    ("Joachim Köppen DF3GJ", "deconvoluzione delle scansioni a deriva di Sole e Luna (Lunar Drift Scans)",
     "https://portia.astrophysik.uni-kiel.de/~koeppen/JS/LunarDriftScans.html"),
    ("Carsten Groen OZ9AAR", "SimpleCalc, SkyScanner, WSJT Log Viewer e il calcolatore online del rumore solare: idee per il "
     "flusso RSTN del giorno con controllo dei brillamenti GOES e per l'analisi delle decodifiche", "https://moonbounce.dk/"),
    ("A.A.M. Saleh", "modello AM/AM e AM/PM dei tubi a onda progressiva, IEEE Trans. Commun. COM-29 (1981)", ""),
    ("C. Rapp", "modello di compressione degli amplificatori a stato solido (1991)", ""),
    ("432 and Above EME News (EME.RADIO)", "notizie e risultati delle stazioni EME, campagne a 47 e 76 GHz", "https://eme.radio/"),
    ("Henk PA0PLY", "EME Directory: stazioni EME per banda", "https://www.pa0ply.nl/eme-directory/"),
    ("Joe Taylor K1JT e il gruppo WSJT-X", "WSJT-X, CALL3.TXT, ALL.TXT, modi Q65/JT65", "https://wsjt.sourceforge.io/"),
    ("Ivan De Cesaris IZ0JNY", "scansione del Sole: disco solare ⊗ fascio gaussiano (modello erf, fattori G per banda)", ""),
    ("Paul Wade W1GHZ", "Online Microwave Antenna Book: rumore solare, fascio e taper", "https://www.w1ghz.org/antbook/contents.htm"),
    ("J.W.M. Baars", "The Paraboloidal Reflector Antenna in Radio Astronomy and Communication; correzione per sorgenti estese (1973)", ""),
    ("ITU-R", "P.676 (gas), P.618 (rumore), P.834 (rifrazione), P.840 (nubi), S.733 (G/T con radiosorgenti)",
     "https://www.itu.int/rec/R-REC-P/en"),
    ("IAU SOFA / ERFA", "posizioni di Sole e Luna (pyerfa)", "https://github.com/liberfa/erfa"),
    ("NOAA SWPC / USAF RSTN", "flusso solare a 15.4 GHz", "https://services.swpc.noaa.gov/text/solar_radio_flux.txt"),
    ("Open-Meteo", "meteo attuale, previsto e archivio", "https://open-meteo.com/"),
    ("Natural Earth", "coste del mondo (pubblico dominio)", "https://www.naturalearthdata.com/"),
    ("QRZ.com", "servizio XML per nominativi e indirizzi QSL (con l'account dell'utente)", "https://www.qrz.com/"),
]

BIBLIOGRAPHY = [   # (author, title, details) — the books behind the calculations, shown apart from the credits
    ("Constantine A. Balanis", "Antenna Theory: Analysis and Design", "Wiley — guadagno, efficienza d'apertura, "
     "diagrammi, polarizzazione, riflettori"),
    ("Miroslav Kasal OK2AQ", "Weak Radio Signals from Space", "ricezione di segnali deboli: rumore, temperatura "
     "d'antenna, G/T, EME"),
]


def render_bibliography(st):
    for who, title, what in BIBLIOGRAPHY:
        st.markdown(f"- {who}, ***{title}***" + (f" — {what}" if what else ""))


def render(st):
    from . import __version__
    st.markdown(f"**EME Assistant {__version__}** — {AUTHOR} · GPL-3.0-or-later · [{REPO}]({REPO})")
    st.markdown("**Fonti e ringraziamenti**")
    for who, what, url in SOURCES:
        st.markdown(f"- **{who}** — {what}" + (f" — [{url}]({url})" if url else ""))
