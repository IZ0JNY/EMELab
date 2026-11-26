# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""Reference spectrum of WSJT-X («Ref Spec»), to be measured again every time the radio is switched on.

DL3WDG («Using WSJT-X for Microwave EME», EME 2022): the reference spectrum flattens the audio response of the
receiver, can widen the usable audio passband, helps the weakest decodes, the S/N reports and the Echo mode. It has to
be measured again whenever the receiver settings change. WSJT-X keeps it in refspec.dat, next to WSJT-X.ini: EMELab
only reads the date of that file and reminds you once per operating session (from the first WSJT-X status after
EMELab starts) until the file is newer or you confirm it. It never writes the file nor changes WSJT-X."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

STEPS = [
    "Nella finestra Wide Graph spunta Flatten (va acceso prima di iniziare).",
    "Togli l'antenna dalla Luna (cielo freddo) o sintonizzati su una frequenza silenziosa, senza birdie.",
    "Lascia il ricevitore come lo usi sempre: stessa banda passante IF, stesso guadagno; noise blanker spento.",
    "Menu Tools di WSJT-X: «Erase reference spectrum», poi «Measure reference spectrum».",
    "Con Monitor acceso aspetta almeno 60 secondi, poi premi Monitor per fermare l'ascolto.",
    "Nel Wide Graph lascia spuntati Flatten e Ref Spec, poi riaccendi Monitor.",
]


def find(ini_path: str | Path | None = None) -> Path | None:
    """refspec.dat in the WSJT-X folder (the one of WSJT-X.ini / wsjtx_log.adi)."""
    try:
        from . import wsjtx_ini
        p = Path(ini_path) if ini_path else wsjtx_ini.find()
    except Exception:
        return None
    if not p:
        return None
    f = (p if p.is_dir() else p.parent) / "refspec.dat"
    return f if f.is_file() else None


def measured_utc(path: str | Path | None) -> datetime | None:
    """When refspec.dat was last written (UTC), None when there is no file."""
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc) if path else None
    except OSError:
        return None


def due(measured: datetime | None, session_start: datetime | None, confirmed: str | None = None) -> bool:
    """True when the reference spectrum is older than this operating session and you have not confirmed it since."""
    if session_start is None:
        return False
    if measured is not None and measured >= session_start:
        return False
    if confirmed:
        try:
            if datetime.fromisoformat(confirmed.replace("Z", "+00:00")) >= session_start:
                return False
        except ValueError:
            pass
    return True


def confirm(now: datetime | None = None) -> dict:
    from . import settings as _s
    now = now or datetime.now(timezone.utc)
    return _s.save_settings(refspec_ok_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
