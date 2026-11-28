import plotly.graph_objects as go
import streamlit as st

from emelab import charts


def test_defaults_add_wheel_zoom_and_keep_own_config():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]), layout=dict(title="Banda 10GHz"))
    cfg = charts.defaults(fig, {"displayModeBar": False}, "k")
    assert cfg["scrollZoom"] is True and cfg["displayModeBar"] is False
    assert fig.layout.uirevision == "k|Banda 10GHz"


def test_defaults_keep_existing_uirevision():
    fig = go.Figure(layout=dict(uirevision="sd"))
    charts.defaults(fig)
    assert fig.layout.uirevision == "sd"


def test_install_patches_st_and_columns(monkeypatch):
    seen = []
    from streamlit.delta_generator import DeltaGenerator
    from streamlit.elements.plotly_chart import PlotlyMixin
    monkeypatch.setattr(DeltaGenerator, "plotly_chart",
                        lambda self, fig, *a, config=None, **kw: seen.append(config), raising=False)
    monkeypatch.setattr(st, "plotly_chart", st.plotly_chart)
    charts.install()
    st.plotly_chart(go.Figure())
    DeltaGenerator.plotly_chart(st._main, go.Figure(), config={"x": 1})
    assert seen[0]["scrollZoom"] and seen[1] == {**charts.CONFIG, "x": 1}
    assert PlotlyMixin.plotly_chart is not DeltaGenerator.plotly_chart
