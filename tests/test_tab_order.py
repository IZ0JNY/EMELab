from emelab import tab_order as to

DEF = ["station", "moon", "planner", "log", "camera"]


def test_no_saved_order_is_default():
    assert to.merge(DEF, None) == DEF
    assert to.merge(DEF, []) == DEF


def test_saved_order_kept_and_unknown_dropped():
    assert to.merge(DEF, ["log", "station", "old", "moon", "planner", "camera"]) == ["log", "station", "moon", "planner", "camera"]


def test_new_tab_goes_after_its_default_predecessor():
    assert to.merge(DEF, ["log", "station", "planner", "camera"]) == ["log", "station", "moon", "planner", "camera"]
    assert to.merge(["new"] + DEF, DEF) == ["new"] + DEF


def test_move():
    assert to.move(DEF, "log", -1) == ["station", "moon", "log", "planner", "camera"]
    assert to.move(DEF, "station", -1) == DEF
    assert to.move(DEF, "camera", +1) == DEF
    assert to.move(DEF, "moon", +2) == ["station", "planner", "log", "moon", "camera"]


def _name(label):
    """Tab text without the «:material/…:» icon."""
    return label.split(": ", 1)[1] if label.startswith(":material/") else label


def test_tab_titles_have_grey_icons_not_emoji():
    from emelab import nav
    assert nav.title("camera", "📷 Telecamera Astronomica") == ":material/photo_camera: Telecamera Astronomica"
    assert nav.plain("🛰️ Configurazioni") == "Configurazioni" and nav.plain("Log QSO") == "Log QSO"


def test_assistant_moves_and_hides_tabs(tmp_path, monkeypatch):
    """In the Assistant: ⬆️ moves a tab earlier, unticking hides it, and both are saved in settings.json."""
    import json
    import os
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any("Schede da mostrare" in e.label for e in at.sidebar.expander)
    labels = [_name(t.label) for t in at.tabs]
    assert labels[0] == "Assistente" and labels.index("Log QSO") > labels.index("Pianificatore")
    at.button(key="tabup_log").click().run()
    labels = [_name(t.label) for t in at.tabs]
    assert labels.index("Log QSO") == labels.index("Pianificatore") - 1
    at.checkbox(key="tabvis_moon").uncheck().run()
    assert "Luna" not in [_name(t.label) for t in at.tabs]
    s = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert s["tabs_order"].index("log") < s["tabs_order"].index("planner") and "moon" not in s["tabs"]
    at.checkbox(key="tabvis_camera").check().run()
    assert "Telecamera Astronomica" in [_name(t.label) for t in at.tabs]
    at.button(key="tab_order_reset").click().run()
    labels = [_name(t.label) for t in at.tabs]
    assert labels.index("Log QSO") > labels.index("Pianificatore")
