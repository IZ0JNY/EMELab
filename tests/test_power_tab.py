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


def test_ypa47_lineup_driver_and_two_in_parallel(tmp_path, monkeypatch):
    """47 GHz: the YPA47-4653C1 fills a driver + 2 modules line-up, DC from Vd × Id, driver heat on the same cooling."""
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_string(SCRIPT.format(root=root), default_timeout=120)
    at.run()
    at.selectbox(key="pw_band").set_value(47.088).run()
    assert not at.exception, [e.value for e in at.exception]
    ss = at.session_state
    assert (ss["sp_n"], ss["sp_drv"], ss["sp_vd"], ss["sp_id"], ss["sp_dcm"], ss["sp_psat"]) == (2, True, 18.0, 1.4, "vi", 41.3)
    m = {x.label: x.value for x in at.metric}
    assert m["Consumo DC"].startswith("76 W")                 # 3 dies × 18 V × 1.4 A
    tab = [d.value for d in at.dataframe if "Raffreddamento" in d.value.columns][0]
    assert "Giunzione del pilota (°C)" in tab.columns
