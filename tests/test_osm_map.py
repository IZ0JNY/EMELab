"""Station tab map: OpenStreetMap component files, ground height from Open-Meteo, a click on the map → position."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("erfa")


def test_component_files_are_bundled():
    d = Path(__file__).resolve().parent.parent / "emelab" / "osm_map"
    html = (d / "index.html").read_text(encoding="utf-8")
    assert (d / "leaflet.js").stat().st_size > 100_000 and (d / "leaflet.css").exists()
    assert "tile.openstreetmap.org" in html and "OpenStreetMap" in html      # tiles + attribution
    assert "streamlit:setComponentValue" in html


def test_elevation_parses_open_meteo(monkeypatch):
    from emelab import weather
    seen = {}

    def fake(url, timeout=10.0):
        seen["url"] = url
        return json.dumps({"elevation": [312.0]}).encode()
    monkeypatch.setattr(weather, "_get", fake)
    assert weather.elevation(41.525926, 13.274918) == 312.0
    assert "api.open-meteo.com/v1/elevation" in seen["url"] and "latitude=41.525926" in seen["url"]


def _fake_st(monkeypatch, **state):
    from emelab import ui
    fake = SimpleNamespace(session_state=dict(state))
    monkeypatch.setattr(ui, "_st", fake)
    return ui, fake.session_state


def test_map_click_sets_position_and_height(monkeypatch):
    from emelab import weather
    monkeypatch.setattr(weather, "elevation", lambda lat, lon, timeout=6.0: 287.4)
    ui, ss = _fake_st(monkeypatch, em_osm={"lat": 41.525926, "lon": 13.274918, "zoom": 15, "t": 1})
    ui._osm_cb()
    assert ss["em_lat"] == 41.525926 and ss["em_lon"] == 13.274918
    assert ss["em_loc"] == "JN61pm" and ss["em_h"] == 287.0 and ss["em_pos_msg"][0] == "ok"
    ss["em_h"] = 5.0                                   # same click seen again at the next rerun: ignored
    ui._osm_cb()
    assert ss["em_h"] == 5.0


def test_map_click_offline_keeps_height(monkeypatch):
    from emelab import weather

    def down(lat, lon, timeout=6.0):
        raise OSError("offline")
    monkeypatch.setattr(weather, "elevation", down)
    ui, ss = _fake_st(monkeypatch, em_h=120.0, em_osm={"lat": 45.0, "lon": 9.0, "zoom": 12, "t": 7})
    ui._osm_cb()
    assert ss["em_lat"] == 45.0 and ss["em_h"] == 120.0 and ss["em_pos_msg"][0] == "warn"


def test_google_maps_paste_also_fills_height(monkeypatch):
    from emelab import weather
    monkeypatch.setattr(weather, "elevation", lambda lat, lon, timeout=6.0: 95.6)
    ui, ss = _fake_st(monkeypatch, em_gmaps="41.64581, 12.62503")
    ui._gmaps_cb()
    assert ss["em_lat"] == 41.64581 and ss["em_h"] == 96.0 and ss["em_gmaps"] == ""


def test_height_button(monkeypatch):
    from emelab import weather
    monkeypatch.setattr(weather, "elevation", lambda lat, lon, timeout=6.0: 401.2)
    ui, ss = _fake_st(monkeypatch, em_h=0.0)
    ui._height_cb(41.5, 13.3)
    assert ss["em_h"] == 401.0 and ss["em_h_msg"][0] == "ok"


def test_map_layers_and_grid_off_by_default():
    d = Path(__file__).resolve().parent.parent / "emelab" / "osm_map"
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "opentopomap.org" in html and "World_Imagery" in html and "Esri" in html
    assert "L.control.layers" in html and "grid = L.layerGroup();" in html     # grid not added to the map at start
    assert (d / "images" / "layers.png").exists()


def test_station_tab_fills_zero_height_once(tmp_path, monkeypatch):
    """Saved station with a position and height 0: the Station tab asks Open-Meteo once and fills the height."""
    from streamlit.testing.v1 import AppTest
    from emelab import db as edb, weather
    monkeypatch.setenv("EMELAB_CONFIG", str(tmp_path))
    monkeypatch.setenv("EMELAB_LANG", "it")
    calls = []
    monkeypatch.setattr(weather, "elevation", lambda lat, lon, timeout=6.0: calls.append((lat, lon)) or 312.0)
    edb.DB().save_station(callsign="IZ0XXX", locator="JN61pm", lat=41.525926, lon=13.274918, height_m=0.0)
    at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "emelab_main.py"), default_timeout=60).run()
    assert not at.exception
    assert at.session_state["em_h"] == 312.0 and len(calls) == 1
    at.run()
    assert len(calls) == 1
