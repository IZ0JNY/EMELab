"""RF Power tab: a device selector state that is not a valid index (Streamlit can hand back the shown label
after a rerun in which the options changed) must not crash the tab (TypeError: '>=' between str and int, 0.1.17)."""
import os

import pytest

pytest.importorskip("streamlit")

SCRIPT = """
import sys
sys.path.insert(0, {root!r})
from emelab import ui, db
ui._power_tab(db.DB())
"""


@pytest.mark.parametrize("bad", ["RW1136 — Siemens", 99, -1, None, 1.5])
def test_power_tab_survives_bad_device_state(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_string(SCRIPT.format(root=root), default_timeout=90)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.selectbox(key="pw_band").set_value(24.048).run()          # 24 GHz: catalogue TWT (RW1136)
    at.radio(key="pw_kind").set_value("SSPA").run()
    at.session_state["pw_dev_TWT"] = bad          # the TWT selector is not on screen: plain state
    at.radio(key="pw_kind").set_value("TWT").run()
    assert not at.exception, [e.value for e in at.exception]
    assert isinstance(at.session_state["pw_dev_TWT"], int)
    at.radio(key="pw_kind").set_value("SSPA").run()
    assert not at.exception, [e.value for e in at.exception]
