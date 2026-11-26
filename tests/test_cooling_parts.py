"""Cooling catalogue: library overrides, thermal pastes, datasheet heat sinks, water loop, chillers, PDF reader."""
from emelab import cooling as c, cooling_parts as cp


def test_library_overrides_and_reverts():
    hs = cp.parts("dissipatore")[0]
    lib = cp.save([], {**hs, "r_nat_kw": 0.8})
    p = [x for x in cp.parts("dissipatore", lib) if x["part"] == hs["part"]][0]
    assert p["origin"] == "edited" and p["r_nat_kw"] == 0.8 and p["catalog"]["r_nat_kw"] == hs["r_nat_kw"] and p["verified"]
    mine = cp.save(lib, {"cat": "dissipatore", "part": "Il mio", "maker": "IZ0JNY", "r_nat_kw": 0.5})
    assert any(x["origin"] == "mine" for x in cp.parts("dissipatore", mine))
    assert all(x["origin"] == "catalog" for x in cp.parts("dissipatore", cp.revert(lib, p)))


def test_paste_beats_pad():
    a = 100.0
    paste = cp.r_tim(8.5, 30, a)
    pad = cp.r_tim(1.5, 508, a)
    assert paste < 0.1 < 1.0 < pad
    assert cp.r_tim(8.5, 30, 400) < paste                       # bigger contact, lower R


def test_vevor_cw3000_in_catalogue():
    ch = [x for x in cp.parts("chiller") if x["maker"] == "VEVOR"][0]
    assert ch["part"] == "CW-3000" and ch["kind"] == "passivo" and abs(1 / ch["r_kw"] - 50) < 1e-9
    ci = cp.coolant_inlet(ch, 50.0, 30.0)
    assert abs(ci["t_in_c"] - 31.0) < 1e-9                      # 50 W / (50 W/°C) above the air


def test_compressor_chiller_holds_set_point_until_capacity():
    ch = [x for x in cp.parts("chiller") if x["part"] == "CW-5000"][0]
    assert cp.coolant_inlet(ch, 100, 35, 20)["t_in_c"] == 20
    assert cp.coolant_inlet(ch, 1000, 35, 20)["t_in_c"] > 20


def test_loop_operating_point():
    pump = {"h_max_m": 4.0, "q_max_lmin": 10.0}
    lp = cp.loop_point(pump, [(10.0, 2.0)])
    assert 0 < lp["flow_lmin"] < 10 and abs(lp["dp_pump_kpa"] - sum(lp["dp_parts_kpa"])) < 1e-9
    # on the pump curve
    assert abs(lp["dp_pump_kpa"] - lp["p_max_kpa"] * (1 - (lp["flow_lmin"] / 10) ** 2)) < 1e-6
    assert cp.loop_point(pump, [(40.0, 2.0)])["flow_lmin"] < lp["flow_lmin"]


def test_datasheet_heat_sink_in_solver():
    hs = [x for x in cp.parts("dissipatore") if x["part"].startswith("SK 89")][0]
    args = dict(n_dev=1, rth_jc=1.5, rth_cs=0.1, t_ref_c=35.0, duty=0.5, period_s=120.0)
    rp = c.solve("passivo", 35, sink=hs, **args)
    rf = c.solve("ventilato", 35, sink=hs, flow_m3h=100, through=0.5, **args)
    assert rp["datasheet"] and rf["r_kw"] < rp["r_kw"] and rf["tj_c"] < rp["tj_c"]
    tun = [x for x in cp.parts("dissipatore") if x.get("r_fan_kw") and not x.get("r_nat_kw")][0]
    assert c.solve("ventilato", 35, sink=tun, flow_m3h=100, through=0.5, **args)["r_kw"] == tun["r_fan_kw"]


def test_read_datasheet_units():
    v = cp.read_datasheet("Air flow 60.0 CFM\nStatic pressure 2.5 mm H2O", "ventola")
    assert abs(v["flow_m3h"] - 101.94) < 0.1 and abs(v["p_max_pa"] - 24.5) < 0.1 and v["_lines"]
    v = cp.read_datasheet("Thermal resistance 0.55 K/W at length 150 mm", "dissipatore")
    assert v["r_nat_kw"] == 0.55 and v["l_mm"] == 150
    v = cp.read_datasheet("Thermal conductivity 8.5 W/mK, bond line 30 µm", "tim")
    assert v["k_wmk"] == 8.5 and v["t_um"] == 30
    v = cp.read_datasheet("Pressure drop 2 psi at 1 gpm", "piastra")
    assert abs(v["dp_kpa"] - 13.79) < 0.01 and abs(v["flow_lmin"] - 3.785) < 0.01
