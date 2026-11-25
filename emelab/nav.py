# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""From an alert to its tab: a click on an alert (toast, pop-up, banner) opens the «Live» tab, or the tab of the
alert when Live is not there or hidden. app.py registers the tabs with register(); goto() switches the active tab."""
from __future__ import annotations

import json

import streamlit as _st

from emelab import i18n

LIVE = "live"
# alert kind → tabs to open, first that exists; "live" only when shown, the others are switched on if hidden
TARGETS = {
    "camera": [LIVE, "camera"],
    "driverdish": [LIVE, "pointing"],
    "wsjtx": [LIVE, "wsjtx"],
    "gpsdo": [LIVE, "gpsdo", "wsjtx"],
    "clock": [LIVE, "wsjtx"],
    "watchdog": [LIVE],                     # the watchdog checks everything: only the Live tab sums it up
}
# toasts that become clickable: start of the (Italian) text → alert kind
TOASTS = {"🚨 Telecamera: fuori tracking! Controlla il puntamento della parabola.": "camera",
          "🚨 Watchdog:": "watchdog"}


# tab icons: Material Symbols drawn in a neutral grey instead of the coloured or black emoji of the labels
ICONS = {"wizard": "explore", "station": "home", "live": "sensors", "moon": "dark_mode", "setups": "settings_input_antenna",
         "planner": "calendar_month", "log": "list_alt", "wsjtx": "radio", "gpsdo": "gps_fixed", "stations": "group",
         "new": "add_circle", "diary": "menu_book", "analysis": "analytics", "charts": "show_chart", "stats": "bar_chart",
         "pointing": "my_location", "camera": "photo_camera", "lna": "graphic_eq", "power": "bolt", "design": "science",
         "prints": "print", "database": "storage", "guide": "school"}
TAB_CSS = ("<style>[data-testid='stTab'] [data-testid='stIconMaterial'],"
           "[data-testid='stCheckbox'] [data-testid='stIconMaterial']{color:#7d8aa0}</style>")


def plain(label: str) -> str:
    """Label without its leading emoji («📷 Telecamera Astronomica» → «Telecamera Astronomica»)."""
    head, _, rest = label.partition(" ")
    return rest if rest and not any(ch.isalnum() for ch in head) else label


def title(k: str, label: str) -> str:
    """Translated tab title with its grey icon: the text the tab bar shows and the value of «main_tab»."""
    text = plain(i18n.tr(label))
    return f":material/{ICONS[k]}: {text}" if k in ICONS else i18n.tr(label)


def register(labels: dict[str, str]):
    """Called by app.py: tab key → Italian label of every tab EMELab knows."""
    _st.session_state["_nav_labels"] = dict(labels)


def target(kind: str, labels: dict[str, str], shown: list[str]) -> str | None:
    """Key of the tab that an alert of this kind opens (pure function: tested without Streamlit)."""
    for k in TARGETS.get(kind, [LIVE]):
        if k not in labels:
            continue
        if k == LIVE and k not in shown:
            continue
        return k
    return None


def _state():
    S = _st.session_state
    return S, S.get("_nav_labels") or {}, ["wizard", "station"] + list(S.get("tabs_on") or [])


def label(kind: str) -> str | None:
    """Translated label of the tab an alert opens, for the button text."""
    S, labels, shown = _state()
    k = target(kind, labels, shown)
    return i18n.tr(labels[k]) if k else None


def goto(kind: str):
    """Opens the tab of an alert (use it as on_click: it must run before the tab bar is drawn)."""
    S, labels, shown = _state()
    k = target(kind, labels, shown)
    if not k:
        return
    if k not in shown:
        S["tabs_on"] = list(S.get("tabs_on") or []) + [k]
    S["main_tab"] = title(k, labels[k])


def button(kind: str, key: str, on_click=None, container=None) -> bool:
    """«➡️ Apri <scheda>» button; on_click runs after the switch (e.g. to mark the alert as seen)."""
    lab = label(kind)
    if not lab:
        return False

    def _cb():
        goto(kind)
        if on_click:
            on_click()
    return (container or _st).button("➡️ " + i18n.tr("Apri") + " " + lab, key=key, on_click=_cb)


def toast_hook():
    """Makes the alert toasts clickable: a click selects the tab button with the target label (small script in the page)."""
    S, labels, shown = _state()
    links = {}
    for txt, kind in TOASTS.items():
        k = target(kind, labels, shown)
        if k:
            links[i18n.tr(txt)[:28]] = plain(i18n.tr(labels[k]))
    if not links:
        return
    js = """<script>
const LINKS = %s;
const doc = window.parent.document;
function tabText(b) {                                   // tab text without the icon's ligature name
  const c = b.cloneNode(true);
  c.querySelectorAll('[data-testid="stIconMaterial"]').forEach(i => i.remove());
  return c.innerText.trim();
}
function hook() {
  doc.querySelectorAll('[data-testid="stToast"]').forEach(t => {
    if (t.dataset.emeLink) return;
    const txt = t.innerText || '';
    const hit = Object.keys(LINKS).find(p => txt.includes(p));
    if (!hit) return;
    t.dataset.emeLink = '1';
    t.style.cursor = 'pointer';
    t.title = LINKS[hit];
    t.addEventListener('click', ev => {
      if (ev.target.closest('button')) return;           // the × keeps closing the toast
      const tab = [...doc.querySelectorAll('[role="tab"]')].find(b => tabText(b) === LINKS[hit]);
      if (tab) { tab.click(); tab.scrollIntoView({block: 'nearest', inline: 'center'}); }
      const x = t.querySelector('button'); if (x) x.click();
    });
  });
}
if (!window.emeTimer) window.emeTimer = setInterval(hook, 500);
</script>""" % json.dumps(links, ensure_ascii=False)
    if hasattr(_st, "iframe"):                       # Streamlit ≥ 1.52
        _st.iframe(js, height=1)
    else:
        import streamlit.components.v1 as components
        components.html(js, height=0)
