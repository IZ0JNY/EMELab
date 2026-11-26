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


def test_assistant_moves_and_hides_tabs(tmp_path, monkeypatch):
    """In the Assistant: ⬆️ moves a tab earlier, unticking hides it, and both are saved in settings.json."""
    import json
    import os
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    monkeypatch.delenv("EMELAB_TABS", raising=False)            # the real defaults of a fresh PC
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not any("Schede da mostrare" in e.label for e in at.sidebar.expander)
    labels = [t.label for t in at.tabs]
    assert labels == ["🧭 Assistente", "🔴 Live", "🏠 Stazione", "🌙 Luna", "📡 Log QSO", "🗓️ Pianificatore"]
    at.button(key="tabup_planner").click().run()
    labels = [t.label for t in at.tabs]
    assert labels.index("🗓️ Pianificatore") == labels.index("📡 Log QSO") - 1
    at.checkbox(key="tabvis_moon").uncheck().run()
    assert "🌙 Luna" not in [t.label for t in at.tabs]
    s = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert s["tabs_order"].index("planner") < s["tabs_order"].index("log") and "moon" not in s["tabs"]
    at.checkbox(key="tabvis_camera").check().run()
    assert "📷 Telecamera Astronomica" in [t.label for t in at.tabs]
    at.button(key="tab_order_reset").click().run()
    labels = [t.label for t in at.tabs]
    assert labels.index("📡 Log QSO") < labels.index("🗓️ Pianificatore")


def test_new_defaults_once_on_a_pc_already_set_up(tmp_path, monkeypatch):
    """0.1.10: a PC with its own tab choice gets the new defaults once; afterwards its choice is kept."""
    import json
    import os
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    (tmp_path / "settings.json").write_text(json.dumps({"tabs": ["wsjtx", "gpsdo", "lna", "database"]}), encoding="utf-8")
    from streamlit.testing.v1 import AppTest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at.run()
    assert [t.label for t in at.tabs] == ["🧭 Assistente", "🔴 Live", "🏠 Stazione", "🌙 Luna", "📡 Log QSO",
                                          "🗓️ Pianificatore"]
    at.checkbox(key="tabvis_wsjtx").check().run()
    at2 = AppTest.from_file(os.path.join(root, "emelab_main.py"), default_timeout=300)
    at2.run()
    assert "📻 WSJT-X" in [t.label for t in at2.tabs] and "🛰️ GPSDO" not in [t.label for t in at2.tabs]
