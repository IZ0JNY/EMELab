import os


def test_app_starts_on_a_fresh_pc(tmp_path, monkeypatch):
    """Fresh settings folder (no station, no data): every tab renders without exceptions."""
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("EMELab" in t.value for t in at.title)
