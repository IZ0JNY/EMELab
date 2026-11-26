# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""💡 LNA suggestions in the 🔊 LNA tab: the dated market survey of LNA chips per band, compared with the LNA of the
configuration, design ideas, and one click to copy a part into the user's library."""
from __future__ import annotations

import streamlit as _st

from emelab import i18n, lna_market, parts

st = i18n.wrap(_st)
BANDS = [10.368, 24.048, 47.088, 76.032, 122.25, 134.928]


def _bl(band) -> str:
    from emelab.stations import band_label
    return band_label(band)


def _n(v, fmt="{:g}"):
    return "" if v is None else fmt.format(v)


def _fmt(f: str | None) -> str:
    """format of a part: the Italian base word translated, the details in brackets as read on the page"""
    if not f:
        return ""
    base, _, rest = f.partition(" (")
    return i18n.tr(base) + (f" ({rest}" if rest else "")


def box(D, setup: dict | None):
    st.divider()
    st.subheader("💡 Suggerimenti: nuovi chip e nuovi design")
    sv = lna_market.load()
    age = lna_market.age_days(sv)
    st.caption(i18n.tr("Ricerca di mercato degli LNA (MMIC in die e in package, pHEMT discreti, moduli) dei produttori "
                       "più noti, confrontata con l'LNA della tua configurazione. I numeri sono quelli letti sulle pagine "
                       "del produttore o del distributore: le celle vuote vanno lette sul datasheet.") +
               (f" {i18n.tr('Ricerca del')} {sv['date']}." if sv.get("date") else ""))
    if age is not None and age > lna_market.OLD_DAYS:
        st.info(i18n.tr("La ricerca ha") + f" {age} " + i18n.tr("giorni: la prossima ricerca mensile la aggiornerà."))
    c = st.columns([1, 3])
    b0 = float(setup["band_ghz"]) if setup else 10.368
    band = c[0].selectbox("Banda", BANDS, index=min(range(len(BANDS)), key=lambda i: abs(BANDS[i] - b0)), key="lm_band",
                          format_func=_bl)
    mine = setup if setup and abs(float(setup["band_ghz"]) - band) < 1 else \
        next((s for s in D.setups() if abs(float(s["band_ghz"]) - band) < 1), None)
    if mine and mine.get("nf_db") is not None:
        c[1].markdown(i18n.tr("Il tuo LNA a") + f" {_bl(band)}: **NF {float(mine['nf_db']):.2f} dB** "
                      f"({i18n.tr('configurazione')} «{mine['name']}»)")
    else:
        c[1].caption("Nessuna configurazione per questa banda: il confronto con il tuo LNA non è disponibile.")
    rows = lna_market.compare(sv, band, mine)
    if not rows:
        st.info("La ricerca non ha trovato LNA per questa banda: guarda le idee di progetto qui sotto.")
    else:
        st.dataframe([{"Sigla": p["part"], "Produttore": p["maker"], "Da GHz": _n(p.get("f_lo_ghz")),
                       "A GHz": _n(p.get("f_hi_ghz")), "NF (dB)": _n(p.get("nf_db")), "Guadagno (dB)": _n(p.get("gain_db")),
                       "Formato": _fmt(p.get("format")), "Tecnologia": p.get("tech") or "",
                       "Stato": i18n.tr(p.get("status") or ""),
                       "ΔG/T se sostituisce il tuo (dB)": _n(p.get("d_gt_db"), "{:+.2f}"),
                       "Nota": p.get("note") or "", "Fonte": p.get("source") or ""} for p in rows],
                     hide_index=True, width="stretch",
                     column_config={"Fonte": _st.column_config.LinkColumn(i18n.tr("Fonte"), display_text="🔗")})
        st.caption("ΔG/T con cielo freddo e le stesse perdite prima dell'LNA; positivo = meglio del tuo. La NF di un chip "
                   "nudo non comprende le perdite del montaggio (connettori, transizioni, bond): conta quella misurata.")
        c = st.columns([3, 1])
        i = c[0].selectbox("Copia nella mia libreria", range(len(rows)), key="lm_pick",
                           format_func=lambda j: f"{rows[j]['part']} · {rows[j]['maker']}")
        if c[1].button("➕ Nella libreria", key="lm_add"):
            p = rows[i]
            parts.save(D, part=p["part"], maker=p["maker"], type="lna", f_lo_ghz=p.get("f_lo_ghz"),
                       f_hi_ghz=p.get("f_hi_ghz"), gain_db=p.get("gain_db"), nf_db=p.get("nf_db"), tech=p.get("tech"),
                       datasheet=p.get("source"), notes=i18n.tr("dalla ricerca di mercato del") + f" {sv.get('date')}")
            st.success(i18n.tr("Aggiunto alla libreria: lo trovi nel Catalogo dispositivi qui sotto."))
    with st.expander(i18n.tr("🛠️ Idee di progetto per") + f" {_bl(band)}", expanded=False):
        st.markdown("\n".join("- " + i18n.tr(x) for x in lna_market.ideas(band)))
    disc = [p for p in sv.get("parts", []) if p.get("f_lo_ghz") is None and p.get("f_hi_ghz") is None]
    if disc and band < 30:
        with st.expander(i18n.tr("🔬 Transistor discreti per il primo stadio") + f" ({len(disc)})"):
            st.dataframe([{"Sigla": p["part"], "Produttore": p["maker"], "NF (dB)": _n(p.get("nf_db")),
                           "Guadagno (dB)": _n(p.get("gain_db")), "Stato": i18n.tr(p.get("status") or ""),
                           "Nota": p.get("note") or "", "Fonte": p.get("source") or ""} for p in disc],
                         hide_index=True, width="stretch",
                         column_config={"Fonte": _st.column_config.LinkColumn(i18n.tr("Fonte"), display_text="🔗")})
            st.caption("NF e guadagno alla frequenza di prova del datasheet (in nota): a 10 e 24 GHz vanno adattati per il minimo rumore.")
    if sv.get("makers"):
        with st.expander("🏭 Produttori"):
            st.markdown("\n".join(f"- **{m['maker']}**: {i18n.tr(m.get('note') or '')}" +
                                  (f" — {m['url']}" if m.get("url") else "") for m in sv["makers"]))


def pa_box(band: float):
    """⚡ RF Power: power amplifier chips of the market survey for the band, strongest first."""
    sv = lna_market.load()
    rows = sorted([p for p in sv.get("pa_parts", []) if lna_market.in_band(p, band)],
                  key=lambda p: -(p.get("psat_dbm") or -99))
    with st.expander(i18n.tr("💡 Chip di potenza dalla ricerca di mercato") + f" ({_bl(band)}, {len(rows)})"):
        if not rows:
            st.caption("Nessun chip di potenza per questa banda nella ricerca di mercato.")
            return
        st.dataframe([{"Sigla": p["part"], "Produttore": p["maker"], "Da GHz": _n(p.get("f_lo_ghz")),
                       "A GHz": _n(p.get("f_hi_ghz")), "Psat (dBm)": _n(p.get("psat_dbm")),
                       "Psat (W)": _n(None if p.get("psat_dbm") is None else round(10 ** ((p["psat_dbm"] - 30) / 10), 1)),
                       "Guadagno (dB)": _n(p.get("gain_db")), "Formato": _fmt(p.get("format")),
                       "Tecnologia": p.get("tech") or "", "Stato": i18n.tr(p.get("status") or ""),
                       "Fonte": p.get("source") or ""} for p in rows],
                     hide_index=True, width="stretch",
                     column_config={"Fonte": _st.column_config.LinkColumn(i18n.tr("Fonte"), display_text="🔗")})
        st.caption(i18n.tr("Ricerca del") + f" {sv.get('date')}. " + i18n.tr(
            "Per usarne uno: aggiungilo nel Catalogo dispositivi qui sotto con i dati del datasheet."))
