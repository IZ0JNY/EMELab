from emelab import stallwatch


def test_stall_time_measured_only_while_a_run_is_in_progress():
    stallwatch.run_finished()
    assert stallwatch.stalled_for() is None
    stallwatch.run_started()
    s = stallwatch.stalled_for()
    assert s is not None and s >= 0
    stallwatch.run_finished()
    assert stallwatch.stalled_for() is None
