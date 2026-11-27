# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""nanoHam tab (printed circuit board icon): the measurements of the setups (voltages, currents, temperatures, PTT and other logic states) sent
by the nanoHam reading boards over the optical fiber, one board per setup (10GHz, 24GHz, 47GHz), with the state of
each fiber link. Read-only: EMELab only listens to the COM ports.

Sub-tabs: 🔴 Misure (link state, values, bars, alarms), 📈 Grafici (last minutes, one graph per unit and board),
⚙️ Configurazione (port, baud, channel names, units, divider ratios, thresholds), 📒 Log (CSV per board and day).
Settings in EMELab's settings.json under «nanoham»."""
from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as _st

from emelab import i18n, nanoham as nh
from emelab import settings as openems_local
from emelab.logbook import BAND_COLORS

st = i18n.wrap(_st)
S = _st.session_state
OK, WARN, BAD, OFF = "#2f9e44", "#f08c00", "#e03131", "#868e96"
ASSUMED_COLOR = "#e8590c"                 # as everywhere in EMELab: values that are not real measurements
GRAPH_MIN = [1, 5, 15, 30, 60]
LINK_COLOR = {"LINK": OK, "NO DATA": WARN, "ERRORE": BAD, "NO PORTA": OFF, "SPENTA": OFF}
LINK_TEXT = {"LINK": "dati in arrivo dalla fibra",
             "NO DATA": "porta aperta ma nessun dato da più di 1 s: controlla fibra, moduli TEL0153 e scheda",
             "ERRORE": "porta COM non aperta",
             "NO PORTA": "scegli la porta COM in ⚙️ Configurazione",
             "SPENTA": "scheda spenta in ⚙️ Configurazione"}
BAUDS = [115200, 57600, 38400, 19200, 9600]


def _frag(run_every):
    f = getattr(_st, "fragment", None)
    return f(run_every=run_every) if f else (lambda fn: fn)


def default_log_dir() -> str:
    return str(openems_local.config_dir() / "nanoham")


def load_cfg(sets: dict | None = None) -> dict:
    sets = openems_local.load_settings() if sets is None else sets
    d = dict(sets.get("nanoham") or {})
    d["boards"] = nh.load_boards(d)
    d.setdefault("log_on", False)
    d.setdefault("log_dir", default_log_dir())
    d.setdefault("log_every_s", 1.0)
    d.setdefault("graph_min", 5)
    return d


def save_cfg(cfg: dict):
    out = {**cfg, "boards": [b.to_dict() for b in cfg["boards"]]}
    openems_local.save_settings(nanoham=out)
    apply(cfg)


def apply(cfg: dict):
    """Readers for the enabled boards with a port, none for the others; the CSV log follows the settings."""
    want = {b.port for b in cfg["boards"] if b.enabled and b.configured}
    for p in nh.active_ports():
        if p not in want:
            nh.stop_reader(p)
    for b in cfg["boards"]:
        if b.enabled and b.configured:
            nh.reader(b.port, b.baud)
    if cfg.get("log_on") or nh._LOGGER is not None:
        nh.logger().configure(cfg["boards"], cfg["log_dir"] if cfg.get("log_on") else None, cfg["log_every_s"])


def ensure_running(sets: dict | None = None):
    """Called by app.py at every run while the tab is on: the boards keep being read (and logged) with any tab open."""
    try:
        apply(load_cfg(sets))
    except Exception:
        pass


def _rd(b: nh.Board):
    return nh.reader(b.port, b.baud) if b.enabled and b.configured else None


def _band_color(name: str) -> str:
    key = name.replace(" ", "").upper().replace("GHZ", "G")
    return BAND_COLORS.get(key, "#868e96")


# ---------------------------------------------------------------- 🔴 Misure
def _link_box(b: nh.Board, now: float) -> str:
    rd = _rd(b)
    stt = nh.link_state(b, rd, now)
    color = LINK_COLOR.get(stt, BAD)
    info = i18n.tr(LINK_TEXT.get(stt, ""))
    if rd is not None and stt == "ERRORE" and rd.error:
        info += f": {rd.error} · " + i18n.tr("riprovo ogni 2 s")
    elif rd is not None and stt == "LINK":
        info = f"{rd.lines_per_s(now):.0f} " + i18n.tr("righe/s") + f" · {rd.lines_ok} ok · {rd.lines_bad} " + i18n.tr("scartate")
    demo = (f"<div style='color:{ASSUMED_COLOR};font-size:0.8rem;font-weight:600'>⚠️ "
            + html.escape(i18n.tr("DEMO: dati simulati, non sono misure vere")) + "</div>") if b.demo and b.enabled else ""
    port = html.escape(b.port or "—") + (f" · {b.baud} baud" if b.configured else "")
    return (f"<div style='border:2px solid {color};border-left:8px solid {_band_color(b.name)};border-radius:10px;"
            f"padding:8px 12px;margin-bottom:8px'>"
            f"<div style='font-size:1.15rem;font-weight:700'>{html.escape(b.name)} "
            f"<span style='color:{color};font-size:1rem'>● {html.escape(i18n.tr(stt))}</span></div>"
            f"<div style='font-size:0.8rem;opacity:.75'>{i18n.tr('Fibra ottica')} · {port}</div>"
            f"<div style='font-size:0.8rem;opacity:.85'>{html.escape(info)}</div>{demo}</div>")


def _tile(c: nh.Channel, v, alarm, demo: bool) -> str:
    color = OFF if v is None else (BAD if alarm else (ASSUMED_COLOR if demo else OK))
    head = f"<div style='font-size:0.8rem;opacity:.8;white-space:nowrap;overflow:hidden'>CH{c.n} · {html.escape(c.name)}</div>"
    box = f"<div style='border:2px solid {color};border-radius:10px;padding:6px 10px;margin-bottom:6px'>"
    if c.logic:
        lit = v is not None and v >= 0.5
        bg = color if lit else "transparent"
        note = ("🚨 " + alarm) if alarm else (
            i18n.tr("allarme se") + " " + (c.on_text if c.alarm_state == "ON" else c.off_text) if c.alarm_state
            else i18n.tr("nessun allarme"))
        return (box + head
                + f"<div style='display:inline-block;margin:4px 0;padding:2px 14px;border-radius:14px;font-size:1.4rem;"
                  f"font-weight:700;border:2px solid {color};background:{bg};color:{'#fff' if lit else color}'>"
                  f"{html.escape(c.fmt(v))}</div>"
                + f"<div style='font-size:0.75rem;color:{BAD if alarm else 'inherit'};opacity:.85'>{html.escape(note)}</div></div>")
    pct = 0 if v is None or not c.full_scale else max(0.0, min(100.0, 100 * v / c.full_scale))
    lim = " · ".join(x for x in ((f"min {c.fmt(c.alarm_min)}" if c.alarm_min is not None else ""),
                                 (f"max {c.fmt(c.alarm_max)}" if c.alarm_max is not None else "")) if x)
    note = ("🚨 " + alarm) if alarm else (lim or i18n.tr("nessuna soglia"))
    return (box + head
            + f"<div style='font-size:1.8rem;font-weight:700;color:{color};font-variant-numeric:tabular-nums'>"
              f"{c.fmt(v)} <span style='font-size:1rem'>{html.escape(c.unit)}</span></div>"
            + f"<div style='background:#8883;border-radius:4px;height:6px'><div style='width:{pct:.1f}%;height:6px;"
              f"border-radius:4px;background:{color}'></div></div>"
            + f"<div style='font-size:0.75rem;margin-top:3px;color:{BAD if alarm else 'inherit'};opacity:.85'>"
              f"{html.escape(note)}</div></div>")


def _measures(cfg: dict):
    @_frag(0.5)
    def _live():
        now = time.time()
        boards = cfg["boards"]
        st.markdown("#### " + i18n.tr("🔗 Stato dei link in fibra"))
        cols = st.columns(max(1, len(boards)))
        for col, b in zip(cols, boards):
            col.markdown(_link_box(b, now), unsafe_allow_html=True)
        active = S.setdefault("nh_alarms_on", {})
        for b in boards:
            rd = _rd(b)
            if rd is None:
                continue
            chans = [c for c in b.channels if c.enabled]
            st.markdown(f"<div style='border-bottom:3px solid {_band_color(b.name)};font-weight:700;margin:6px 0'>"
                        f"{html.escape(b.name)}</div>", unsafe_allow_html=True)
            per_row = 8
            for i in range(0, len(chans), per_row):
                row = chans[i:i + per_row]
                for col, c in zip(st.columns(per_row), row):
                    r = rd.raw(c.n, now)
                    v = None if r is None else c.value(r)
                    a = nh.alarm_of(c, v)
                    key = f"{b.name}|{c.n}"
                    if a and not active.get(key) and not b.demo:
                        _st.toast(f"🚨 nanoHam {b.name} · {c.name}: {a}", icon="🚨")
                    active[key] = bool(a)
                    col.markdown(_tile(c, v, a, b.demo), unsafe_allow_html=True)
        if not any(b.enabled and b.configured for b in boards):
            st.info("Nessuna scheda nanoHam collegata: scegli la porta COM di ogni setup in ⚙️ Configurazione "
                    "(«DEMO» simula una scheda per provare).")

    _live()


# ---------------------------------------------------------------- 📈 Grafici
def _figure(b: nh.Board, unit: str, chans: list, minutes: int, now: float):
    import plotly.graph_objects as go
    rd = _rd(b)
    fig = go.Figure()
    for c in chans:
        pts = rd.series(c.n, minutes * 60, now) if rd else []
        fig.add_trace(go.Scatter(x=[datetime.fromtimestamp(t, timezone.utc) for t, _ in pts],
                                 y=[c.value(v) for _, v in pts], mode="lines", line_shape="hv" if c.logic else "linear",
                                 name=c.name + ("" if c.logic else f" ({c.unit})")))
    logic = unit == "stati"
    fig.update_layout(height=220 if logic else 280, margin=dict(l=10, r=10, t=36, b=10),
                      title=f"{b.name} · {i18n.tr('stati (0/1)') if logic else unit}", uirevision=f"{b.name}|{unit}",
                      legend=dict(orientation="h", y=-0.25),
                      yaxis=dict(range=[-0.1, 1.1], tickvals=[0, 1]) if logic else {})
    return fig


def _graphs(cfg: dict):
    c = st.columns([2, 5])
    m = c[0].select_slider("Ultimi minuti", GRAPH_MIN,
                           value=cfg["graph_min"] if cfg["graph_min"] in GRAPH_MIN else 5, key="nh_graph_min")
    if m != cfg["graph_min"]:
        cfg["graph_min"] = m
        save_cfg(cfg)

    @_frag(2.0)
    def _plots():
        now = time.time()
        shown = False
        for b in cfg["boards"]:
            if _rd(b) is None:
                continue
            groups: dict[str, list] = {}
            for ch in b.channels:
                if ch.enabled:
                    groups.setdefault("stati" if ch.logic else ch.unit, []).append(ch)
            cols = st.columns(max(1, len(groups)))
            for col, (u, chans) in zip(cols, groups.items()):
                col.plotly_chart(_figure(b, u, chans, m, now), key=f"nh_g_{b.name}_{u}", width="stretch")
                shown = True
        if not shown:
            st.info("Nessun grafico: nessuna scheda nanoHam collegata.")

    _plots()


# ---------------------------------------------------------------- ⚙️ Configurazione
CH_COLS = {"n": "CH", "name": "Nome", "kind": "Tipo", "unit": "Unità", "scale": "Rapporto (partitore)", "offset": "Offset",
           "decimals": "Decimali", "full_scale": "Fondo scala", "alarm_min": "Allarme sotto", "alarm_max": "Allarme sopra",
           "alarm_nodata": "Allarme NO DATA", "on_text": "Testo ON", "off_text": "Testo OFF",
           "alarm_state": "Allarme se (logico)", "enabled": "Attivo"}


def channels_from_rows(rows) -> list[nh.Channel]:
    """Rows of the channel table → channels (duplicates and rows without CH dropped, empty cells = default)."""
    chans, seen = [], set()
    for r in rows:
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if n in seen:
            continue
        seen.add(n)
        d = nh.Channel(n)
        for k in CH_COLS:
            x = r.get(k)
            if k == "n" or x is None or x != x or x == "" and k not in ("on_text", "off_text", "alarm_state", "unit"):
                continue
            cur = getattr(d, k)
            if k in ("alarm_min", "alarm_max"):
                try:
                    setattr(d, k, float(str(x).replace(",", ".")))
                except ValueError:
                    pass                                             # not a number: threshold off
            elif k == "alarm_state":
                d.alarm_state = x if x in ("ON", "OFF") else ""
            elif isinstance(cur, bool):
                setattr(d, k, bool(x))
            else:
                setattr(d, k, type(cur)(x))
        d.name = d.name or f"CH{d.n}"
        chans.append(d)
    return sorted(chans, key=lambda c: c.n)


def _board_editor(cfg: dict, i: int, b: nh.Board):
    ports = nh.serial_ports()
    names = ["", nh.DEMO_PORT] + [p for p, _ in ports]
    if b.port not in names:
        names.append(b.port)
    desc = dict(ports)
    with st.expander(f":material/developer_board: {b.name} · {b.port or i18n.tr('porta da scegliere')}"):
        c = st.columns([3, 3, 2, 1])
        name = c[0].text_input("Nome (banda del setup)", b.name, key=f"nh_name_{i}")
        port = c[1].selectbox("Porta COM", names, index=names.index(b.port), key=f"nh_port_{i}",
                              format_func=lambda p: i18n.tr("— nessuna —") if not p else (
                                  i18n.tr("DEMO · scheda simulata") if p == nh.DEMO_PORT
                                  else (f"{p} · {desc[p]}" if desc.get(p) else p)),
                              help="la porta del cavo USB-TTL collegato al modulo in fibra (TEL0153) di questo setup")
        baud = c[2].selectbox("Baud", BAUDS, index=BAUDS.index(b.baud) if b.baud in BAUDS else 0, key=f"nh_baud_{i}")
        en = c[3].checkbox("Accesa", b.enabled, key=f"nh_en_{i}")
        st.caption("Valore mostrato = valore ricevuto × rapporto + offset (rapporto = partitore, es. 10 per 1:10). "
                   "Lascia vuote le soglie che non usi. Tipo «logic»: ricevuto ≥ 0.5 = ON, con i tuoi testi "
                   "(es. PTT / RX) e l'allarme nello stato che scegli. Aggiungi una riga per un canale in più (CH11…).")
        import pandas as pd
        rows = pd.DataFrame([{k: getattr(ch, k) for k in CH_COLS} for ch in b.channels], columns=list(CH_COLS))
        for k in ("alarm_min", "alarm_max"):                         # unused threshold: blank cell, not «None»
            rows[k] = [("" if x is None or x != x else f"{x:g}") for x in rows[k]]
        rows["alarm_state"] = [x or "—" for x in rows["alarm_state"]]
        ed = st.data_editor(rows, key=f"nh_ch_{i}", num_rows="dynamic", hide_index=True, width="stretch",
                            column_config={k: _st.column_config.Column(i18n.tr(v)) for k, v in CH_COLS.items()} | {
                                "n": _st.column_config.NumberColumn("CH", min_value=1, max_value=99, step=1, required=True),
                                "decimals": _st.column_config.NumberColumn(i18n.tr("Decimali"), min_value=0, max_value=6, step=1),
                                "scale": _st.column_config.NumberColumn(i18n.tr("Rapporto (partitore)"), format="%.4f"),
                                "alarm_nodata": _st.column_config.CheckboxColumn(i18n.tr("Allarme NO DATA")),
                                "alarm_min": _st.column_config.TextColumn(i18n.tr("Allarme sotto")),
                                "alarm_max": _st.column_config.TextColumn(i18n.tr("Allarme sopra")),
                                "kind": _st.column_config.SelectboxColumn(i18n.tr("Tipo"), options=["analog", "logic"],
                                                                          required=True),
                                "alarm_state": _st.column_config.SelectboxColumn(i18n.tr("Allarme se (logico)"),
                                                                                 options=["—", "ON", "OFF"]),
                                "enabled": _st.column_config.CheckboxColumn(i18n.tr("Attivo"))})
        c = st.columns([1, 1, 1, 3])
        if c[0].button("💾 Salva", key=f"nh_save_{i}", type="primary"):
            name = name.strip() or b.name
            if any(x.name == name and j != i for j, x in enumerate(cfg["boards"])):
                st.error("C'è già una scheda con questo nome.")
                return
            if port and port != nh.DEMO_PORT and any(x.port == port and x.enabled and j != i
                                                     for j, x in enumerate(cfg["boards"])):
                st.error("Questa porta è già usata da un'altra scheda.")
                return
            cfg["boards"][i] = nh.Board(name=name, port=port, baud=int(baud), enabled=en,
                                        channels=channels_from_rows(ed.to_dict("records") if hasattr(ed, "to_dict") else ed) or nh.nanoham_channels())
            save_cfg(cfg)
            st.rerun()
        if c[1].button("↩️ Canali nanoHam", key=f"nh_reset_{i}", help="rimette gli 8 canali predefiniti della nanoHam"):
            b.channels = nh.nanoham_channels()
            save_cfg(cfg)
            st.rerun()
        if c[2].button("🗑️ Elimina", key=f"nh_del_{i}", disabled=len(cfg["boards"]) == 1):
            cfg["boards"].pop(i)
            save_cfg(cfg)
            st.rerun()


def _config(cfg: dict):
    st.caption("Una nanoHam per setup (10GHz, 24GHz, 47GHz), ognuna sulla sua porta COM: nanoHam → TEL0153 → fibra → "
               "TEL0153 → cavo USB-TTL 3,3 V → PC. Protocollo: righe «CH<n>,<valore>» a 115200 baud, come la reading "
               "board. EMELab legge soltanto, non manda nulla alle schede. Chiudi NanoHam PC se usa la stessa porta.")
    for i, b in enumerate(list(cfg["boards"])):
        _board_editor(cfg, i, b)
    if st.button("➕ Aggiungi una scheda", key="nh_add"):
        used = {b.name for b in cfg["boards"]}
        name = next(n for n in list(nh.BANDS) + ["76GHz", "122GHz", "134GHz"] + [f"nanoHam {k}" for k in range(2, 99)]
                    if n not in used)
        cfg["boards"].append(nh.Board(name=name))
        save_cfg(cfg)
        st.rerun()


# ---------------------------------------------------------------- 📒 Log
def _log_page(cfg: dict):
    st.caption("Un file CSV per scheda e per giorno (UTC), separatore «;», valori già scalati, con gli allarmi attivi. "
               "Si apre con Excel o LibreOffice. Continua a registrare con qualsiasi scheda di EMELab aperta.")
    c = st.columns([1, 4, 1])
    on = c[0].toggle("Registra", bool(cfg["log_on"]), key="nh_log_on")
    folder = c[1].text_input("Cartella", cfg["log_dir"], key="nh_log_dir")
    every = c[2].number_input("Ogni (s)", 0.1, 3600.0, float(cfg["log_every_s"]), 0.5, key="nh_log_every")
    if (on, folder, every) != (cfg["log_on"], cfg["log_dir"], cfg["log_every_s"]):
        cfg.update(log_on=on, log_dir=folder, log_every_s=every)
        save_cfg(cfg)
    lg = nh._LOGGER
    if lg and lg.error:
        st.error(i18n.tr("Errore di scrittura") + f": {lg.error}")
    elif on and lg and lg.last_path:
        st.success(i18n.tr("Sto scrivendo in") + f" {lg.last_path}")
    log = nh.CsvLog(folder)
    for b in cfg["boards"]:
        p = log.path(b)
        if Path(p).exists():
            st.download_button(f"⬇️ {p.name}", p.read_bytes(), p.name, "text/csv", key=f"nh_dl_{b.name}")


def tab(D=None):
    cfg = load_cfg()
    apply(cfg)
    st.caption("Le misure dei setup dalle schede nanoHam in fibra ottica: tensioni, correnti, temperature, PTT e altri "
               "stati logici. Sola lettura.")
    sub = st.tabs(["🔴 Misure", "📈 Grafici", "⚙️ Configurazione", "📒 Log"])
    with sub[0]:
        _measures(cfg)
    with sub[1]:
        _graphs(cfg)
    with sub[2]:
        _config(cfg)
    with sub[3]:
        _log_page(cfg)
