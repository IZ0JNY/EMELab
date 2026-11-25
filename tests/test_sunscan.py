"""Sun scan model (IZ0JNY erf strip model, 2D disc) against the literature (Baars 1973 width approximation)."""
import math

import numpy as np

from emelab import sunscan as S


def test_iz0jny_sheet_values():
    hp = S.hpbw_deg(24, 1.2)                 # sheet: D = 120 cm, k = 70°
    assert abs(hp - 0.7287) < 1e-3 and abs(S.sigma_of(hp) - 0.3094) < 1e-3
    th = np.array([0.0])
    s = S.sigma_of(hp)
    from scipy.special import erf
    R = 0.265
    ref = s * math.sqrt(math.pi / 2) * (erf(R / (math.sqrt(2) * s)) - erf(-R / (math.sqrt(2) * s)))
    assert abs(S.scan_strip(th, hp)[0] - ref) < 1e-12


def test_disc_scan_width_matches_baars_where_valid():
    for hp in (0.45, 0.73, 1.5):                       # beam ≳ 0.8 × Sun diameter
        th = np.linspace(-3, 3, 6001)
        y = S.scan_disc(th, hp)
        w = th[y >= y.max() / 2].max() - th[y >= y.max() / 2].min()
        assert abs(w - S.baars_width(hp)) / w < 0.03
        assert abs(S.beam_from_scan_width(S.baars_width(hp)) - hp) < 1e-9


def test_k_from_taper():
    assert abs(S.k_from_taper(0) - 58.4) < 0.1 and 68.5 < S.k_from_taper(13.5) < 69.5 and 69.5 < S.k_from_taper(15) < 70.5


def test_fit_recovers_beam_and_offset():
    th = np.linspace(-2, 2, 801)
    p = 100 + 400 * S.scan_disc(th - 0.07, 0.35) / S.scan_disc(np.array([0.0]), 0.35).max()
    r = S.fit_scan(th, p)
    assert abs(r["hpbw_deg"] - 0.35) < 0.005 and abs(r["offset_deg"] - 0.07) < 0.003


def test_pointing_loss_grows_with_frequency():
    l10, l47 = (S.pointing_loss_db(0.2, 0.1, S.hpbw_deg(f, 2.4), f) for f in (10, 47))
    assert l47 < l10 < 0


def test_baars_breaks_down_for_beams_much_narrower_than_the_sun():
    th = np.linspace(-3, 3, 6001)
    y = S.scan_disc(th, 0.18)
    w = th[y >= y.max() / 2].max() - th[y >= y.max() / 2].min()
    assert abs(w - S.baars_width(0.18)) / w > 0.1
    r = S.fit_scan(th, 50 + 300 * y / y.max())
    assert abs(r["hpbw_deg"] - 0.18) < 0.005
