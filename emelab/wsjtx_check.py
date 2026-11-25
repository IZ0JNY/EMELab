# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Are the WSJT-X settings right for EME on this band? Checked on every UDP Status message.

What the Status message shows, and what EMELab can do about it:
- mode, submode and T/R period (Q65-60D at 10 GHz, Q65-60E from 24 GHz up, or your choice per band): corrected by
  EMELab with the Configure message, if WSJT-X has «Accept UDP requests» ticked; otherwise only a warning;
- frequency tolerance (F Tol) of the band preset: corrected with Configure like the mode;
- Rx audio frequency (Rx DF) of the preset: set with Configure when you change band (afterwards you may move it by
  clicking a decode, so it is only a mild note);
- Tx audio frequency (Tx DF) and configuration name of the preset: only a mild note (Configure cannot set them);
- dial frequency outside the bands from 10 GHz up, callsign and locator different from the EMELab station,
  TX watchdog: only a warning (the UDP protocol cannot change them).
«Tx even/1st», Max Drift, Auto Seq, Doppler tracking, Split Operation, Prop Mode, audio and rig settings are not in
the Status message: the first five are read from WSJT-X.ini (wsjtx_ini) when it is found, otherwise confirmed by hand.

Band presets (settings «wsjtx_presets», editable in the 📻 WSJT-X tab), from IZ0JNY's WSJT-X v3.3.0:
- 24 GHz: configuration «EME mm-wave», Q65-60E, T/R 60 s, Tx even/1st, Tx 700 Hz, Rx 700 Hz, F Tol 200 Hz,
  Max Drift 0, Auto Seq on;
- 10 GHz: Q65-60D, Tx 1000 Hz, Rx 1000 Hz, Doppler tracking CFOM (Constant Frequency On Moon); the rest as 24 GHz;
- every band: Split Operation «Rig»;
- the higher bands copy 24 GHz (assumed values, to be checked)."""
from __future__ import annotations

from . import dx, stations

NULL = 0xFFFFFFFF
Q65_STANDARD = {"10G": "60D", "24G": "60E", "47G": "60E", "76G": "60E", "122G": "60E", "134G": "60E"}


def expected_mode(band: str) -> str:
    """Q65 submode for the band ('60D'): the user's choice when EMELab has one (dx.band_mode), else the standard."""
    fn = getattr(dx, "band_mode", None)
    if fn:
        try:
            return fn(band)
        except Exception:
            pass
    return Q65_STANDARD.get(band, "60E")


PRESET_DEFAULT = {"config": "EME mm-wave", "tx_df": 700, "rx_df": 700, "f_tol": 200, "max_drift": 0,
                  "tx_first": True, "auto_seq": True, "doppler": "CFOM", "split": "Rig"}
PRESET_BAND = {"10G": {"tx_df": 1000, "rx_df": 1000, "doppler": "CFOM"}}
PRESET_GIVEN = {"10G", "24G"}       # bands whose preset IZ0JNY gave; the others are assumed copies of 24 GHz
DOPPLER = {"CFOM": "CFOM (Constant Frequency On Moon)", "Full": "Full Doppler to DX Grid", "OwnEcho": "Own Echo",
           "OnDxEcho": "On DX Echo", "CallDx": "Call DX", "None": "nessuno"}
SPLIT = ("Rig", "Fake It", "None")
MANUAL = [("doppler", "Doppler tracking (finestra Astro)"), ("split", "Split Operation"), ("tx_first", "«Tx even/1st»"),
          ("max_drift", "Max Drift"), ("auto_seq", "Auto Seq")]


def _num(v):
    return None if v in (None, NULL) else int(v)


def preset(band: str, settings: dict | None = None) -> dict:
    """The WSJT-X preset of the band: {"mode": '60E', "tr": 60, "submode": 'E', config, tx_df, rx_df, f_tol, …,
    "saved": True when the user stored it}."""
    if settings is None:
        from . import settings as _s
        settings = _s.load_settings()
    mine = (settings.get("wsjtx_presets") or {}).get(band) or {}
    p = {**PRESET_DEFAULT, **PRESET_BAND.get(band, {}), **{k: v for k, v in mine.items() if k in PRESET_DEFAULT}}
    try:
        mode = dx.band_mode(band, settings)
    except Exception:
        mode = Q65_STANDARD.get(band, "60E")
    return {**p, "mode": mode, "tr": int(mode[:-1]), "submode": mode[-1], "saved": bool(mine),
            "assumed": not mine and band not in PRESET_GIVEN}


def save_preset(band: str, **values) -> dict:
    """Store the band's preset (only the known keys); the Q65 submode goes to «q65_modes» like the Signal tab."""
    from . import settings as _s
    sets = _s.load_settings()
    all_p = dict(sets.get("wsjtx_presets") or {})
    mode = values.pop("mode", None)
    all_p[band] = {**(all_p.get(band) or {}), **{k: v for k, v in values.items() if k in PRESET_DEFAULT}}
    kw = {"wsjtx_presets": all_p}
    if mode in dx.Q65_MODES:
        kw["q65_modes"] = {**(sets.get("q65_modes") or {}), band: mode}
    return _s.save_settings(**kw)


def check(status: dict, station: dict | None = None, settings: dict | None = None) -> list[dict]:
    """Problems in the WSJT-X Status: [{"code", "msg", "detail", "fix", "cfg", "soft"}]: fix = the Q65 code to send
    ('60D') or None; cfg = other values Configure can set ({"freq_tol": 200} or {"rx_df": 700}); soft = mild note,
    not shown in the warning at the top of every page."""
    out = []
    hz = status.get("dial_hz")
    band = stations.band_of(hz / 1e6) if hz else None
    if hz and band is None:
        out.append({"code": "band", "msg": "WSJT-X non è su una banda EME da 10 GHz in su", "detail": f"{hz / 1e6:,.3f} MHz",
                    "fix": None})
    if band:
        try:
            pre = preset(band, settings)
        except Exception:
            pre = {**PRESET_DEFAULT, "config": ""}
        want = pre.get("mode") or expected_mode(band)
        mode = (status.get("mode") or "").strip()
        sub = (status.get("submode") or "").strip().upper()
        tr = status.get("tr_period")
        tr = None if tr in (None, 0, NULL) else int(tr)
        have = f"{mode}" + (f"-{tr or ''}{sub}" if mode.upper().startswith("Q65") else (f" {sub}" if sub else ""))
        if not mode.upper().startswith("Q65") or sub != want[-1] or (tr is not None and tr != int(want[:-1])):
            out.append({"code": "mode", "msg": "Modo diverso da quello della banda", "detail": f"{have} → Q65-{want} ({stations.band_label(band)})",
                        "fix": want})
        ftol = _num(status.get("freq_tolerance"))
        if ftol is not None and pre.get("f_tol") and ftol != int(pre["f_tol"]):
            out.append({"code": "ftol", "msg": "F Tol diversa dal preset della banda", "detail": f"{ftol} → {pre['f_tol']} Hz",
                        "fix": None, "cfg": {"freq_tol": int(pre["f_tol"])}})
        rx = _num(status.get("rx_df"))
        if rx is not None and pre.get("rx_df") is not None and abs(rx - int(pre["rx_df"])) > 5:
            out.append({"code": "rx_df", "msg": "Rx diversa dal preset della banda", "detail": f"{rx} → {pre['rx_df']} Hz",
                        "fix": None, "cfg": {"rx_df": int(pre["rx_df"])}, "soft": True})
        tx = _num(status.get("tx_df"))
        if tx is not None and pre.get("tx_df") is not None and abs(tx - int(pre["tx_df"])) > 5:
            out.append({"code": "tx_df", "msg": "Tx diversa dal preset della banda: impostala a mano in WSJT-X",
                        "detail": f"{tx} → {pre['tx_df']} Hz", "fix": None})
        cfg = (status.get("config_name") or "").strip()
        if cfg and pre.get("config") and cfg.casefold() != str(pre["config"]).strip().casefold():
            out.append({"code": "config", "msg": "Configurazione di WSJT-X diversa dal preset della banda",
                        "detail": f"«{cfg}» → «{pre['config']}» (Configurations)", "fix": None, "soft": True})
    stn = station or {}
    my_call = (stn.get("callsign") or "").upper().strip()
    de_call = (status.get("de_call") or "").upper().strip()
    if my_call and de_call and de_call.split("/")[0] != my_call.split("/")[0]:
        out.append({"code": "call", "msg": "Nominativo in WSJT-X diverso da quello della stazione", "detail": f"{de_call} ≠ {my_call}",
                    "fix": None})
    my_loc = (stn.get("locator") or "").upper().strip()
    de_grid = (status.get("de_grid") or "").upper().strip()
    if my_loc and de_grid and de_grid[:4] != my_loc[:4]:
        out.append({"code": "grid", "msg": "Locator in WSJT-X diverso da quello della stazione", "detail": f"{de_grid} ≠ {my_loc}",
                    "fix": None})
    if status.get("tx_watchdog"):
        out.append({"code": "watchdog", "msg": "Il TX watchdog di WSJT-X ha fermato la trasmissione", "detail": "",
                    "fix": None})
    return out
