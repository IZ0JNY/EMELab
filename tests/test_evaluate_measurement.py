def test_evaluate_measurement_without_expected_y():
    """A stored snapshot with no expected Y (e.g. Moon below the horizon) must not crash the measurement log."""
    from emelab import analysis
    ev = analysis.evaluate_measurement({"kind": "moon", "y_db": 0.75, "calc": {"moon": {"y_db": None}}}, {})
    assert ev["y_expected"] is None and ev["y_delta"] is None
