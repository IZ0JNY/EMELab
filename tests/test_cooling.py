"""Cooling of the power device: passive, fan, water; Q65 heating over time; Arrhenius life."""
import math

from emelab import cooling as c

ARGS = dict(n_dev=1, rth_jc=1.5, rth_cs=0.2, period_s=120.0)
KW = {"passivo": dict(t_ref_c=35.0, sink=c.SINK), "ventilato": dict(t_ref_c=35.0, sink=c.SINK, flow_m3h=100, through=0.5),
      "acqua": dict(t_ref_c=35.0, flow_lmin=2.0)}


def test_fan_and_water_beat_passive():
    r = {m: c.solve(m, 60, duty=0.5, **ARGS, **kw) for m, kw in KW.items()}
    assert 0.4 < r["passivo"]["r_kw"] < 1.2 and 0.1 < r["ventilato"]["r_kw"] < 0.5 and r["acqua"]["r_kw"] < 0.1
    assert r["acqua"]["tj_c"] < r["ventilato"]["tj_c"] < r["passivo"]["tj_c"]


def test_time_constant_sets_averaging():
    # a big passive sink averages the 60 s T/R, a cold plate sees each transmission
    p = c.solve("passivo", 60, duty=0.5, **ARGS, **KW["passivo"])
    w = c.solve("acqua", 60, duty=0.5, **ARGS, **KW["acqua"])
    assert p["tau_s"] > 300 and abs(p["peak_factor"] - 0.5) < 0.05
    assert w["tau_s"] < 60 and w["peak_factor"] > 0.9
    assert c.peak_factor(1e9, 0.5, 120) == c.peak_factor(1e9, 0.5, 120) and abs(c.peak_factor(1e9, 0.5, 120) - 0.5) < 1e-3


def test_more_flow_lower_r():
    assert c.r_forced(c.SINK, 200)["r_kw"] < c.r_forced(c.SINK, 50)["r_kw"]
    assert c.r_water(6)["r_kw"] < c.r_water(1)["r_kw"]
    assert abs(c.r_water(2.0, 0.04, 2.0)["r_kw"] - 0.04) < 1e-6          # datasheet point reproduced


def test_max_power_hits_target():
    for m, kw in KW.items():
        pm = c.max_p_diss(m, 150, 0.5, **ARGS, **kw)
        assert abs(c.solve(m, pm, duty=0.5, **ARGS, **kw)["tj_c"] - 150) < 0.1
        assert c.max_p_diss(m, 150, 1.0, **ARGS, **kw) <= pm
    assert c.max_duty("passivo", 1.0, 150, **ARGS, **KW["passivo"]) == 1.0
    assert c.max_duty("passivo", 500, 150, **ARGS, **KW["passivo"]) is None


def test_simulation_qso_and_cycle():
    seq = c.schedule("qso", 60, cq_tx=10, qso_tx=6, cool_min=10)
    assert sum(d for d, tx in seq if tx) == 16 * 60
    for m, kw in KW.items():
        kw = dict(kw)
        t_ref = kw.pop("t_ref_c")
        s = c.simulate(m, 40, 1, 1.5, 0.2, t_ref, seq, **kw)
        assert s["tj_c"][0] == t_ref and s["tj_c"][-1] < s["tj_max_c"]
        # never above the periodic steady state
        assert s["tj_max_c"] <= c.solve(m, 40, duty=0.5, **ARGS, t_ref_c=t_ref, **kw)["tj_c"] + 0.5
    assert len(c.schedule("ciclo", 120, minutes=30)) == 2 * round(30 * 60 / 240)


def test_arrhenius():
    assert c.mttf_h(150, 1.5, 1e7, 150) == 1e7
    f = c.life_factor(150, 140, 1.7)
    assert 2.5 < f < 3.5 and math.isclose(c.life_factor(150, 140, 1.7) * c.life_factor(140, 130, 1.7),
                                          c.life_factor(150, 130, 1.7))


def test_device_thermal_from_notes():
    d = c.device_thermal({"tech": "LDMOS", "notes": "datasheet; rth_jc=0.35, tj_max=200"})
    assert d == {"tech": "LDMOS / MOSFET", "rth_jc": 0.35, "tj_max": 200.0, "pae_pct": None}
    assert c.device_thermal({"tech": "TWT"})["tech"] is None
