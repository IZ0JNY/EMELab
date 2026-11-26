import pytest


@pytest.fixture(autouse=True)
def _all_tabs(monkeypatch):
    """The app tests look at every tab: on a fresh settings folder EMELab would show only the default ones."""
    monkeypatch.setenv("EMELAB_TABS", "all")
