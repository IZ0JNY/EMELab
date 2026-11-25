# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ivan De Cesaris, IZ0JNY
"""EMELab entry point:  streamlit run emelab_main.py"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "emelab" / "app.py"), run_name="__main__")
