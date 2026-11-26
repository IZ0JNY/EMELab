"""Dish and power per band from the HB9Q logger: profile text → CSV → comparison → corrections by hand."""
from emelab import hb9q

PROFILE = """9A5AA / Dragan CW
Equipment
1296 MHz - 2,4m offset dish - 400W
10xxx MHz - 2,4m offset dish - LNA 0,5dB, 32W, MN 2,2dB RX/TX: 10.368, 10450
24048 MHz - 2,4m offset dish - 30W
47088 MHz - 44 cm modified Icom - 1.2KW
Locator
JN75XT"""


def test_parse_equipment_keeps_only_10ghz_and_up():
    e = hb9q.parse_equipment(PROFILE)
    assert list(e) == ["10G", "24G", "47G"]
    assert e["10G"]["antenna"] == "2.4m dish OS" and e["10G"]["power_w"] == 32
    assert e["47G"]["antenna"] == "0.44m dish" and e["47G"]["power_w"] == 1200


def test_csv_roundtrip_and_band_labels():
    rows = hb9q.parse_csv(hb9q.to_csv({"9a5aa": PROFILE}))
    assert [(r["call"], r["band"]) for r in rows] == [("9A5AA", "10G"), ("9A5AA", "24G"), ("9A5AA", "47G")]
    assert hb9q.parse_csv("call,band,antenna,power_w\nOK1KIR,24GHz,4.5m dish,40\nOK1KIR,1296,x,1\n")[0]["band"] == "24G"


def test_compare_states():
    rows = [{"call": "PA0PLY", "band": "10G", "antenna": "3m dish", "power_w": 50, "hb9q": ""},
            {"call": "PA0PLY", "band": "24G", "antenna": "1.2m dish", "power_w": 20, "hb9q": ""},
            {"call": "PA0PLY", "band": "47G", "antenna": "0.6m dish", "power_w": 5, "hb9q": ""},
            {"call": "DF3GJ", "band": "24G", "antenna": "2m dish", "power_w": 10, "hb9q": ""}]
    cur = {"PA0PLY": {"10G": {"antenna": "3m dish", "power_w": 52}, "24G": {"antenna": "1.8m dish", "power_w": 20}},
           "DF3GJ": {"24G": {"antenna": "2m dish", "power_w": None}}}
    st = [r["state"] for r in hb9q.compare(rows, cur)]
    assert st == ["uguale", "diverso", "nuovo", "manca"]


def test_applied_as_revertible_correction(tmp_path):
    from emelab import db as edb
    D = edb.DB(tmp_path / "t.sqlite")
    D.upsert_station("DF3GJ", eme=1, data={"directory": {"24G": {"antenna": "2m dish", "power_w": None}}})
    D.commit()
    r = hb9q.compare([{"call": "DF3GJ", "band": "24G", "antenna": "", "power_w": 10, "hb9q": ""}],
                     {"DF3GJ": D.directory_of(D.station_of("DF3GJ")["data"])})[0]
    D.set_station_manual("DF3GJ", None, {"24G": hb9q.merged(r)})
    assert D.directory_of(D.station_of("DF3GJ")["data"])["24G"] == {"antenna": "2m dish", "power_w": 10}
    D.set_station_manual("DF3GJ", None, {"24G": None})
    assert D.directory_of(D.station_of("DF3GJ")["data"])["24G"]["power_w"] is None
