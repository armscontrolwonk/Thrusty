"""How a spent stage falls (FRONT_END_DESIGN.md Part IV, Phase 3).

The drag curves in `spent_stage_aero` come from Jernell's flat-ended
cylinder (Mach 1.50-2.86) and Klett's Newtonian cylinder (Mach 10 up), and a
piece is flown end over end to apogee, then at both ends of its
trim-to-tumbling band, reporting the midpoint.  These tests pin the numbers
read from those sources and the shape of the band; none of them samples a
single endpoint of a long run.
"""

import math

import numpy as np
import pytest

import spent_stage_aero as ssa
import trajectory as tr
from coordinates import geodetic_to_ecef, range_between
from types import SimpleNamespace as NS

LD = 6.0   # Jernell's tabulated body


def _stage(**kw):
    base = dict(diameter_m=1.0, length_m=6.0, solid_motor=False,
                has_fins=False, has_grid_fins=False)
    base.update(kw)
    return NS(**base)


# ── drag curves ─────────────────────────────────────────────────────────────

def test_random_tumbling_reproduces_the_data_average_and_klett():
    # Jernell l/d 6, averaged over random orientation, cross-section area
    # (Part IV §19c: 7.3 at Mach 1.5, 6.6 at 2.86).
    assert ssa.random_cd(1.5, LD) == pytest.approx(7.25, abs=0.05)
    assert ssa.random_cd(2.86, LD) == pytest.approx(6.62, abs=0.05)
    # Klett eq. 36 at Mach 10, l/d 6: (4/pi)(0.393*6 + 0.178)(2 - K).
    assert ssa.random_cd(10.0, LD) == pytest.approx(ssa.klett_random_cd(10.0, LD))
    assert ssa.klett_random_cd(10.0, LD) == pytest.approx(5.893, abs=0.002)


def test_klett_equations_on_his_reference_area():
    # Klett writes eqs. 32 and 36 on area L*D; Thrusty's are on pi d^2/4.
    for M in (10.0, 20.0, 30.0):
        K = (0.4 * M * M + 2.0) / (2.4 * M * M)
        to_LD = (math.pi / 4.0) / LD
        assert ssa.klett_random_cd(M, LD) * to_LD == pytest.approx(
            (0.393 + 0.178 / LD) * (2.0 - K))
        assert ssa.klett_end_over_end_cd(M, LD) * to_LD == pytest.approx(
            (0.283 + 0.303 / LD) * (2.0 - K))


def test_end_over_end_lies_below_random_and_meets_klett_eq_32():
    for M in (1.5, 2.0, 2.86, 5.0, 10.0, 20.0):
        assert ssa.end_over_end_cd(M, LD) < ssa.random_cd(M, LD)
    assert ssa.end_over_end_cd(10.0, LD) == pytest.approx(
        ssa.klett_end_over_end_cd(10.0, LD))
    # Uniform average in angle: a quarter turn of the symmetric body.
    th = np.linspace(0.0, math.pi / 2.0, 181)
    cd = np.trapezoid([ssa.cd_at(math.degrees(t), 2.0, LD) for t in th], th)
    assert ssa.end_over_end_cd(2.0, LD) == pytest.approx(cd / (math.pi / 2.0))


@pytest.mark.parametrize('curve', [ssa.random_cd, ssa.end_over_end_cd])
def test_tumbling_curves_are_held_below_mach_1_5_and_continuous(curve):
    assert curve(0.3, LD) == curve(1.5, LD) == curve(1.0, LD)
    for M in (2.86, 10.0):                      # the joins
        assert curve(M - 1e-6, LD) == pytest.approx(curve(M + 1e-6, LD), rel=1e-3)
    # Monotone between the data and Klett: no bump from the blend.
    ms = np.linspace(2.86, 10.0, 30)
    v = [curve(m, LD) for m in ms]
    assert all(b <= a + 1e-12 for a, b in zip(v, v[1:]))


def test_normal_force_scales_with_planform_and_axial_force_does_not():
    cn6, ca6 = ssa._coeffs(45.0, 2.0, 6.0)
    cn9, ca9 = ssa._coeffs(45.0, 2.0, 9.0)
    assert cn9 == pytest.approx(1.5 * cn6)
    assert ca9 == ca6


def test_beyond_90_deg_the_body_is_mirrored_end_for_end():
    cn, ca = ssa._coeffs(30.0, 2.0, LD)
    cn2, ca2 = ssa._coeffs(150.0, 2.0, LD)
    assert cn2 == pytest.approx(cn) and ca2 == pytest.approx(-ca)
    assert ssa.cd_at(150.0, 2.0, LD) == pytest.approx(ssa.cd_at(30.0, 2.0, LD))


# ── trim ────────────────────────────────────────────────────────────────────

def test_trim_angle_from_the_measured_centre_of_pressure():
    # CG 0.40 of the length from the leading face (Part IV §19c: about 18 deg
    # at Mach 1.5 and 11-12 deg at Mach 2.86).
    assert ssa.trim_alpha(1.5, 0.40) == pytest.approx(18.0, abs=1.5)
    assert ssa.trim_alpha(2.86, 0.40) == pytest.approx(11.5, abs=1.5)
    a15, a20, a286 = (ssa.trim_alpha(m, 0.40) for m in (1.5, 2.0, 2.86))
    assert a15 > a20 > a286                      # interpolated in Mach
    assert ssa.trim_alpha(2.86, 0.40) == ssa.trim_alpha(5.0, 0.40)   # held
    assert ssa.trim_alpha(1.5, 0.40) == ssa.trim_alpha(1.0, 0.40)


def test_a_cg_the_cp_never_reaches_has_no_trim():
    assert ssa.trim_alpha(1.5, 0.50) is None
    assert ssa.trim_alpha(2.86, 0.55) is None
    assert ssa.trim_alpha(1.5, 0.05) == 0.0      # ahead of the CP: end-on


def test_trim_drag_is_far_below_tumbling():
    a, cd = ssa.trim_cd(2.86, LD, 0.40)
    assert 0 < cd < 0.5 * ssa.random_cd(2.86, LD)


# ── the stage kinds ─────────────────────────────────────────────────────────

def test_a_liquid_stage_trims_base_first():
    d = ssa.spent_stage_drag(_stage(), 1000.0, 'lower')
    assert d['cda_trim'] is not None and d['leading'] == 'base'
    assert any('Shu' in n for n in d['notes'])
    A = math.pi / 4.0
    assert d['cda_random'](2.0) == pytest.approx(ssa.random_cd(2.0, LD) * A)
    assert d['cda_end_over_end'](2.0) == pytest.approx(
        ssa.end_over_end_cd(2.0, LD) * A)
    assert d['cda_trim'](2.0) < d['cda_end_over_end'](2.0) < d['cda_random'](2.0)


@pytest.mark.parametrize('kw, word', [
    (dict(solid_motor=True), 'no thrust'),
    (dict(has_fins=True), 'finned'),
    (dict(has_grid_fins=True), 'finned'),
])
def test_finned_stages_and_solids_without_a_thrust_are_flown_tumbling_only(kw, word):
    d = ssa.spent_stage_drag(_stage(**kw), 1000.0, 'lower')
    assert d['cda_trim'] is None and d['leading'] is None
    assert any(word in n for n in d['notes'])
    assert d['cda_end_over_end'](3.0) > 0      # the climb leg still exists


def test_the_nozzle_share_is_the_ratio_of_romaniw_fits():
    # case 7e-5 T^1.2393, insulation 1e-4 T^1.1412, nozzle 0.0013 T^0.9615
    T = 290e3
    c, i, n = 7e-5 * T ** 1.2393, 1e-4 * T ** 1.1412, 0.0013 * T ** 0.9615
    assert ssa.solid_nozzle_share(T) == pytest.approx(n / (c + i + n))
    assert ssa.solid_nozzle_share(290e3) == pytest.approx(0.28, abs=0.01)
    assert ssa.solid_nozzle_share(10e6) == pytest.approx(0.14, abs=0.01)
    assert ssa.solid_nozzle_share(0.0) is None


def test_a_solid_stage_trims_base_first_with_the_nozzle_share_at_the_base():
    st = _stage(solid_motor=True, thrust_N=250e3, thrust_peak_N=290e3)
    f, basis = ssa.empty_cg_fraction_solid(st)
    s = ssa.solid_nozzle_share(290e3)            # peak thrust preferred
    assert f == pytest.approx(0.5 + 0.5 * s)
    assert 'Romaniw' in basis and '290 kN' in basis
    d = ssa.spent_stage_drag(st, 454.0, 'lower')
    assert d['cda_trim'] is not None and d['leading'] == 'base'
    # CG 0.36 from the base: about 15 deg off end-on at Mach 1.5 (Jernell).
    assert ssa.trim_alpha(1.5, 1.0 - f) == pytest.approx(15.0, abs=2.0)
    # Average thrust when no peak is given.
    f2, _ = ssa.empty_cg_fraction_solid(_stage(solid_motor=True, thrust_N=250e3))
    assert f2 == pytest.approx(0.5 + 0.5 * ssa.solid_nozzle_share(250e3))


def test_upper_stage_cg_sits_nearer_mid_length():
    f_lo, _ = ssa.empty_cg_fraction(_stage(), 1.0, 'lower')
    f_up, _ = ssa.empty_cg_fraction(_stage(), 1.0, 'upper')
    assert 0.5 < f_up < f_lo < 1.0
    assert f_lo == pytest.approx(0.5 + 0.5 * 0.25 / 1.25)


# ── flying the band ─────────────────────────────────────────────────────────

def _state(lat_deg, lon_deg, alt_m, speed, elev_deg, az_deg=90.0):
    """ECEF position and velocity: `speed` at `elev_deg` above local level."""
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    pos = np.asarray(geodetic_to_ecef(la, lo, alt_m), float)
    east = np.array([-math.sin(lo), math.cos(lo), 0.0])
    north = np.array([-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo),
                      math.cos(la)])
    up = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo),
                   math.sin(la)])
    e, a = math.radians(elev_deg), math.radians(az_deg)
    vel = speed * (math.cos(e) * (math.sin(a) * east + math.cos(a) * north)
                   + math.sin(e) * up)
    return pos, vel


def test_a_constant_cda_reproduces_the_beta_path():
    pos, vel = _state(33.0, 44.0, 60e3, 1500.0, -30.0)
    m, cda = 500.0, 2.0
    a = tr.integrate_debris(pos, vel, m / cda)
    b = tr.integrate_debris(pos, vel, 0.0, cda_of_mach=lambda M: cda, mass_kg=m)
    assert a == pytest.approx(b, rel=1e-6)


def test_a_climbing_piece_tumbles_end_over_end_to_apogee_then_flies_the_band():
    pos, vel = _state(33.0, 44.0, 40e3, 1800.0, 45.0)
    drag = ssa.spent_stage_drag(_stage(diameter_m=0.9, length_m=5.0), 450.0)
    lat, lon, t, spd, track, band = tr._fly_band(pos, vel, 450.0, drag, False)
    assert band['climb'] is not None
    assert band['climb']['apogee_km'] > 40.0 + 1.0
    assert 0.0 < band['climb']['t_s'] < t
    assert any('end over end' in n for n in band['notes'])
    # The track runs from separation through apogee to the reported point.
    assert track['t'][0] == 0.0 and track['t'][-1] == pytest.approx(t)
    assert np.all(np.diff(track['t']) > 0)
    assert np.argmax(track['alt']) > 0
    assert track['alt'][0] == pytest.approx(40e3, rel=1e-3)
    assert track['lat'][-1] == lat and track['lon'][-1] == lon
    # The reported point is the midpoint of the band.
    r, tm = band['random'], band['trim']
    d_rt = range_between(*map(math.radians, r), *map(math.radians, tm))
    d_rm = range_between(*map(math.radians, r), math.radians(lat), math.radians(lon))
    d_tm = range_between(*map(math.radians, tm), math.radians(lat), math.radians(lon))
    assert d_rm == pytest.approx(0.5 * d_rt, rel=1e-3)
    assert d_tm == pytest.approx(0.5 * d_rt, rel=1e-3)


def test_the_band_starts_at_apogee_not_at_separation():
    # Flown trimmed from separation, a light stage leaving at Mach 6 in dense
    # air lands tens of km from the tumbling case; from apogee the two ends
    # are close.  This is the 44 km AUR case of 2026-10-01.
    pos, vel = _state(33.0, 44.0, 38e3, 1860.0, 60.0)
    drag = ssa.spent_stage_drag(_stage(diameter_m=0.88, length_m=5.0), 454.0)
    *_, band = tr._fly_band(pos, vel, 454.0, drag, False)
    fly = lambda cda: tr.integrate_debris(pos, vel, 0.0, cda_of_mach=cda,
                                          mass_kg=454.0)
    a, b = fly(drag['cda_random']), fly(drag['cda_trim'])
    whole = range_between(*map(math.radians, a[:2]), *map(math.radians, b[:2]))
    split = range_between(*map(math.radians, band['random']),
                          *map(math.radians, band['trim']))
    assert split < 0.25 * whole


def test_a_falling_piece_has_no_climb_leg_and_no_trim_means_the_tumbling_point():
    pos, vel = _state(33.0, 44.0, 80e3, 2500.0, -20.0)
    drag = ssa.spent_stage_drag(_stage(solid_motor=True), 800.0)
    lat, lon, t, spd, track, band = tr._fly_band(pos, vel, 800.0, drag, False)
    assert band['climb'] is None and band['trim'] is None
    assert (lat, lon) == band['random']
    ref = tr.integrate_debris(pos, vel, 0.0, cda_of_mach=drag['cda_random'],
                              mass_kg=800.0)
    assert (lat, lon, t, spd) == pytest.approx(ref)
