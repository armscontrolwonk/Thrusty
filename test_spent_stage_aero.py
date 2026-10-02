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
    # One point is reported: an end the swing picked, or the midpoint.
    r, tm = band['random'], band['trim']
    if band['reported'] == 'midpoint':
        d_rt = range_between(*map(math.radians, r), *map(math.radians, tm))
        d_rm = range_between(*map(math.radians, r), math.radians(lat), math.radians(lon))
        d_tm = range_between(*map(math.radians, tm), math.radians(lat), math.radians(lon))
        assert d_rm == pytest.approx(0.5 * d_rt, rel=1e-3)
        assert d_tm == pytest.approx(0.5 * d_rt, rel=1e-3)
        assert band['half_width_km'] == pytest.approx(0.5 * d_rt / 1000.0)
    else:
        assert (lat, lon) == {'trim': tm, 'tumbling': r}[band['reported']]
        assert band['half_width_km'] is None


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


# ── the swing: does it settle or keep tumbling ──────────────────────────────

def test_the_moment_about_the_cg_vanishes_at_the_trim_and_pushes_off_front_first():
    f = 0.60                                   # CG from the front: base leads
    for M in (1.5, 2.86):
        trim = ssa.trim_alpha(M, 1.0 - f)      # off end-on, base leading
        a = 180.0 - trim
        assert ssa.moment_about_cg(a - 2.0, M, LD, f) > 0      # toward the trim
        assert ssa.moment_about_cg(a + 2.0, M, LD, f) < 0
        # Front-first is unstable: the moment increases the angle all the way
        # to broadside.
        assert all(ssa.moment_about_cg(x, M, LD, f) > 0 for x in (5, 20, 45, 89))


def test_attitude_model_inertia_and_potential():
    m, L, d = 1000.0, 6.0, 1.0
    even = ssa.attitude_model(L, d, m, 0.5)          # no mass at the base
    assert even['I'] == pytest.approx(m * (L * L / 12 + d * d / 8))
    att = ssa.attitude_model(L, d, m, 0.6)
    share = 0.2
    assert att['I'] == pytest.approx(
        (1 - share) * m * (L * L / 12 + d * d / 8 + 0.01 * L * L)
        + share * m * (0.4 * L) ** 2)
    # Front-first is the top of the potential: at rest anywhere else the
    # energy is negative, and the moment is odd about the axis.
    al = np.radians(np.arange(1.0, 360.0, 1.0))
    assert np.all(att['energy'](al, 0.0, 1000.0, 2.0) < 0)
    assert att['energy'](0.0, 0.0, 1000.0, 2.0) == 0.0
    assert att['cm'](np.radians(40.0), 2.0) == pytest.approx(
        -att['cm'](np.radians(320.0), 2.0))
    assert not att['rotating'](np.pi, 0.0, 1000.0, 2.0)
    assert att['rotating'](np.pi, 50.0, 1000.0, 2.0)


def test_the_swing_conserves_energy_in_steady_flow():
    att = ssa.attitude_model(6.0, 1.0, 1000.0, 0.6)
    t = np.linspace(0.0, 20.0, 41)
    flow = dict(t=t, q=np.full(t.size, 2000.0), mach=np.full(t.size, 2.0),
                turn=np.zeros(t.size))
    a0 = np.radians([30.0, 150.0, 170.0])
    w0 = np.array([0.0, 0.5, 3.0])
    e0 = att['energy'](a0, w0, 2000.0, 2.0)
    for t1 in (3.0, 11.0, 20.0):
        a1, w1 = tr._swing(att, flow, a0, w0, 0.0, t1)
        assert att['energy'](a1, w1, 2000.0, 2.0) == pytest.approx(e0, rel=2e-2, abs=5.0)


def test_a_stage_released_in_vacuum_gets_no_spin_and_keeps_the_midpoint():
    pos, vel = _state(33.0, 44.0, 200e3, 3000.0, 30.0)
    drag = ssa.spent_stage_drag(_stage(diameter_m=1.5, length_m=8.0), 4000.0, 'upper')
    lat, lon, t, spd, track, band = tr._fly_band(pos, vel, 4000.0, drag, False)
    assert band['verdict'] is None and band['tumbling'] == 'random'
    assert band['tumble_deg_s'][1] < 5.0
    assert band['reported'] == 'midpoint' and band['half_width_km'] > 0
    assert any('separation mechanism' in n for n in band['notes'])


def test_a_light_stage_released_in_dense_air_is_spun_up_by_it():
    pos, vel = _state(33.0, 44.0, 38e3, 1860.0, 60.0)
    drag = ssa.spent_stage_drag(_stage(diameter_m=0.88, length_m=5.0), 454.0)
    *_, band = tr._fly_band(pos, vel, 454.0, drag, False)
    assert band['tumbling'] == 'end_over_end'
    assert band['verdict'] in ('settles', 'tumbles', 'unclear')
    lo, hi = band['tumble_deg_s']
    assert 60.0 < lo <= hi < 1000.0            # hundreds of deg/s
    assert hi < 1.5 * lo                       # robust to the disturbance


def test_a_heavy_stage_settles_and_the_trimmed_point_is_reported():
    # A long, heavy liquid stage released near 50 km spins slowly (tens of
    # deg/s) and the rising air stops it well above the drag phase.
    pos, vel = _state(33.0, 44.0, 51e3, 1775.0, 45.0)
    drag = ssa.spent_stage_drag(_stage(diameter_m=1.32, length_m=16.5), 4800.0)
    lat, lon, t, spd, track, band = tr._fly_band(pos, vel, 4800.0, drag, False)
    assert band['verdict'] == 'settles' and band['reported'] == 'trim'
    assert (lat, lon) == band['trim'] and band['half_width_km'] is None
    assert band['tumble_deg_s'][1] < 100.0
    assert track['lat'][-1] == pytest.approx(lat) and track['t'][-1] == pytest.approx(t)


def test_the_half_width_label_on_a_debris_row():
    assert tr._pm_label(dict(half_width_km=None)) == ''
    assert tr._pm_label(dict(half_width_km=0.04)) == ''
    assert tr._pm_label(dict(half_width_km=0.34)) == ' ±0.3 km'
    assert tr._pm_label(dict(half_width_km=3.6)) == ' ±4 km'


# ── finned stages: do the fins hold it front-first ──────────────────────────

import json
import booster_models as bm


def _shipped_stage1(name):
    return bm.booster_from_dict(json.load(open(f'booster_library/{name}.booster.json')))


def test_front_first_drag_is_the_flat_face_value():
    assert ssa.front_first_cd(1.5, LD) == pytest.approx(1.62, abs=0.01)   # Jernell, alpha 0
    assert ssa.front_first_cd(0.5, LD) == ssa.front_first_cd(1.5, LD)     # held below
    K = (0.4 * 100 + 2.0) / (2.4 * 100)
    assert ssa.front_first_cd(10.0, LD) == pytest.approx(0.909 * (2.0 - K))  # Klett eq. 22
    assert ssa.front_first_cd(2.0, LD) < 0.5 * ssa.end_over_end_cd(2.0, LD)


@pytest.mark.parametrize('name, verdict', [
    ('Strypi_VIII_R', 'stable'),       # large fins on a short solid stage
    ('No-dong', 'marginal'),
    ('Taepodong-II', 'unstable'),      # small fins on a wide liquid stage
])
def test_whether_the_fins_hold_a_shipped_first_stage_front_first(name, verdict):
    p = _shipped_stage1(name)
    f = (ssa.empty_cg_fraction_solid(p) if p.solid_motor
         else ssa.empty_cg_fraction(p, p.mass_final, 'lower'))[0]
    got, lo, hi = ssa.fin_stability(p, f)
    assert got == verdict and 0 < lo <= hi
    d = ssa.spent_stage_drag(p, p.mass_final, 'lower')
    assert d['cda_trim'] is None
    if verdict == 'unstable':
        assert d.get('cda_front_first') is None
        assert any('cannot hold it front-first' in n for n in d['notes'])
    else:
        assert d['fin_stability'] == verdict
        # Flat face plus fins: far less drag than tumbling.
        assert 0 < d['cda_front_first'](2.0) < 0.5 * d['cda_end_over_end'](2.0)


def test_bigger_fins_are_more_stabilising_and_no_fin_size_means_no_answer():
    p = _shipped_stage1('Taepodong-II')
    f = ssa.empty_cg_fraction(p, p.mass_final, 'lower')[0]
    small = ssa.fin_stability(p, f)
    p.fin_span_m *= 3.0
    big = ssa.fin_stability(p, f)
    assert big[1] > small[1]
    p.fin_span_m = 0.0
    assert ssa.fin_stability(p, f) is None
    assert ssa.fin_stability(_stage(has_fins=True), 0.6) is None   # no fin fields


def test_a_stage_its_fins_hold_is_flown_front_first_from_separation():
    pos, vel = _state(33.0, 44.0, 30e3, 1200.0, 50.0)
    p = _shipped_stage1('Strypi_VIII_R')
    drag = ssa.spent_stage_drag(p, p.mass_final, 'lower')
    lat, lon, t, spd, track, band = tr._fly_band(pos, vel, p.mass_final, drag, False)
    assert band['reported'] == 'front_first' and band['climb'] is None
    assert (lat, lon) == band['front_first'] and band['half_width_km'] is None
    ref = tr.integrate_debris(pos, vel, 0.0, cda_of_mach=drag['cda_front_first'],
                              mass_kg=p.mass_final)
    assert (lat, lon, t, spd) == pytest.approx(ref)
    # It lands beyond where the same stage would land tumbling.
    tumbling = tr._fly_band(pos, vel, p.mass_final,
                            dict(drag, cda_front_first=None), False)
    here = lambda la, lo: range_between(math.radians(33.0), math.radians(44.0),
                                        math.radians(la), math.radians(lo))
    assert here(lat, lon) > here(tumbling[0], tumbling[1])


def test_a_marginal_finned_stage_reports_the_midpoint_with_its_half_width():
    pos, vel = _state(33.0, 44.0, 50e3, 2000.0, 45.0)
    p = _shipped_stage1('No-dong')
    drag = ssa.spent_stage_drag(p, p.mass_final, 'lower')
    lat, lon, t, spd, track, band = tr._fly_band(pos, vel, p.mass_final, drag, False)
    assert band['reported'] == 'midpoint' and band['half_width_km'] > 0
    d_ends = range_between(*map(math.radians, band['front_first']),
                           *map(math.radians, band['random']))
    d_mid = range_between(*map(math.radians, band['front_first']),
                          math.radians(lat), math.radians(lon))
    assert d_mid == pytest.approx(0.5 * d_ends, rel=1e-3)
    assert band['half_width_km'] == pytest.approx(0.5 * d_ends / 1000.0)
    assert track['lat'][-1] == lat and track['t'][-1] == pytest.approx(t)


# ── a stage's outline: forward taper, aft skirt, protruding nozzle ──────────

# The 0.563% Shuttle SRB wind-tunnel model, inches (Johnson & Braddock,
# DMS-DR-2111, Fig. 2): overall 9.808; nose cone 1.059; body 0.800 dia;
# skirt 0.524 long flaring to 1.082; nozzle 0.294 beyond it, exit 0.798.
_M449 = dict(diameter_m=0.800, length_m=9.808 - 0.294,
             forward_taper_length_m=1.059, aft_skirt_length_m=0.524,
             aft_skirt_diameter_m=1.082, nozzle_protrusion_m=0.294,
             nozzle_exit_area_m2=math.pi * 0.798 ** 2 / 4.0)


def test_a_plain_cylinder_has_no_outline_shift():
    off, L, area = ssa.planform_centroid_offset(_stage())
    assert off == 0.0 and L == 6.0 and area == 6.0
    assert ssa.planform_centroid_offset(
        _stage(aft_skirt_length_m=0.5, aft_skirt_diameter_m=0.9)) == (0.0, 6.0, 6.0)   # not wider


def test_the_srb_models_side_on_area_is_centred_aft_of_mid_length():
    off, L, _ = ssa.planform_centroid_offset(NS(**_M449))
    assert L == pytest.approx(9.808)
    # Bacchus, Kross & Moog give about 53% for the SRB's area centroid.
    assert 0.5 + off == pytest.approx(0.53, abs=0.01)


def test_each_outline_piece_moves_the_centroid_aft():
    base = ssa.planform_centroid_offset(_stage())[0]
    taper = ssa.planform_centroid_offset(_stage(forward_taper_length_m=1.0))[0]
    skirt = ssa.planform_centroid_offset(
        _stage(aft_skirt_length_m=0.5, aft_skirt_diameter_m=1.4))[0]
    nozzle, L, area = ssa.planform_centroid_offset(
        _stage(nozzle_protrusion_m=0.6, nozzle_exit_area_m2=0.5))
    assert base == 0.0 and taper > 0 and skirt > 0
    assert L == pytest.approx(6.6) and area > 6.0  # the nozzle adds length
    # A slender nozzle moves the centroid aft in metres, though not as a
    # fraction of the longer overall length.
    assert (0.5 + nozzle) * L > 3.0
    # A triangle of base d and length 1 in place of a 1 x d rectangle:
    assert taper == pytest.approx((5.0 * 3.5 + 0.5 * 2.0 / 3.0) / 5.5 / 6.0 - 0.5)


def test_the_outline_moves_the_trim_away_from_end_on():
    plain = ssa.spent_stage_drag(_stage(), 1000.0, 'lower')
    shaped = ssa.spent_stage_drag(
        _stage(forward_taper_length_m=1.0, aft_skirt_length_m=0.5,
               aft_skirt_diameter_m=1.4), 1000.0, 'lower')
    assert any('outline' in n for n in shaped['notes'])
    assert not any('outline' in n for n in plain['notes'])
    # More drag at the trim: the stage sits further from end-on.
    for M in (1.5, 2.0, 2.86):
        assert shaped['cda_trim'](M) > plain['cda_trim'](M)
    # Tumbling drag follows the side-on area: the taper removes more of it
    # than this skirt adds.
    a_plain = ssa.planform_centroid_offset(_stage())[2]
    a_shaped = ssa.planform_centroid_offset(
        _stage(forward_taper_length_m=1.0, aft_skirt_length_m=0.5,
               aft_skirt_diameter_m=1.4))[2]
    assert a_shaped < a_plain
    assert shaped['cda_random'](2.0) < plain['cda_random'](2.0)


def test_a_cg_at_the_area_centroid_leaves_no_trim():
    # Shift the centre of pressure as far aft as the CG: no preferred
    # attitude short of broadside (Bacchus et al.: CG at the centroid, 90 deg).
    st = _stage(forward_taper_length_m=3.0, aft_skirt_length_m=1.0,
                aft_skirt_diameter_m=2.0)
    off = ssa.planform_centroid_offset(st)[0]
    assert off > 0.10                                  # beyond the liquid CG, 0.60
    d = ssa.spent_stage_drag(st, 1000.0, 'lower')
    assert d['leading'] in (None, 'front')             # no base-first trim


def test_an_aft_skirt_adds_flare_drag_on_ascent_and_nothing_when_absent():
    p = _shipped_stage1('Shahab-3')
    A = math.pi * p.diameter_m ** 2 / 4.0
    assert bm._transition_wave_drag(p, p, 2.0, A) == 0.0
    p.aft_skirt_diameter_m, p.aft_skirt_length_m = 1.35 * p.diameter_m, 0.65 * p.diameter_m
    got = bm._transition_wave_drag(p, p, 2.0, A)
    assert got == pytest.approx(bm._flare_cd(p.aft_skirt_diameter_m, p.diameter_m,
                                             p.aft_skirt_length_m, 2.0, A))
    assert 0.05 < got < 0.5
    assert bm._transition_wave_drag(p, p, 0.5, A) == 0.0      # wave drag: supersonic only


def test_outline_fields_round_trip_through_the_booster_file():
    p = _shipped_stage1('Shahab-3')
    p.forward_taper_length_m, p.aft_skirt_length_m = 1.1, 0.7
    p.aft_skirt_diameter_m, p.nozzle_protrusion_m = 1.8, 0.4
    q = bm.booster_from_dict(bm.booster_to_dict(p))
    assert (q.forward_taper_length_m, q.aft_skirt_length_m,
            q.aft_skirt_diameter_m, q.nozzle_protrusion_m) == (1.1, 0.7, 1.8, 0.4)


# ── benchmark: the Shuttle SRB (BENCHMARKING.md; Part IV §19h-i) ────────────

_FT, _LBM, _LBF, _PSF = 0.3048, 0.45359237, 4.4482216, 47.880259


def _srb(outline):
    LT, d = 149.16 * _FT, 12.17 * _FT                 # Moore et al. 2012
    k = LT / 9.808                                    # model 449 proportions
    geo = (dict(length_m=LT - 0.294 * k, forward_taper_length_m=1.059 * k,
                aft_skirt_length_m=0.524 * k, aft_skirt_diameter_m=d * 1.082 / 0.800,
                nozzle_protrusion_m=0.294 * k,
                nozzle_exit_area_m2=math.pi * (d * 0.798 / 0.800) ** 2 / 4.0)
           if outline else dict(length_m=LT))
    return NS(diameter_m=d, solid_motor=True, has_fins=False, has_grid_fins=False,
              thrust_N=2.59e6 * _LBF, thrust_peak_N=3.31e6 * _LBF, **geo)   # McDonald 1985


def _peak_q_psf(pos, vel, mass, cda):
    r = tr.integrate_debris(pos, vel, 0.0, max_time_s=3000.0, return_trajectory=True,
                            cda_of_mach=cda, mass_kg=mass, return_solution=True)
    return float(np.max(tr._flow_history(r[5], r[2])['q'])) / _PSF


def test_the_shuttle_srb_falls_between_the_trimmed_and_tumbling_ends():
    # Separation 154,000 ft, 4,330 fps (Moore et al. 2012, Fig. 10); 30.8 deg
    # is the flight-path angle that gives the published apogee, 230,000 ft.
    # Published peak dynamic pressure on the way down: 1,600 psf (Moore),
    # 1,700 psf (McDonald 1985, Fig. 19).
    mass = 170000 * _LBM                               # Bacchus, Kross & Moog 1985
    pos, vel = _state(28.6, -80.6, 154000 * _FT, 4330 * _FT, 30.8)
    peaks = {}
    for outline in (False, True):
        drag = ssa.spent_stage_drag(_srb(outline), mass, 'lower')
        apo = tr._climb_to_apogee(pos, vel, mass, drag['cda_end_over_end'])
        assert 220e3 < ecef_alt_ft(apo[0]) < 240e3 and 65.0 < apo[2] < 76.0
        peaks[outline] = (_peak_q_psf(apo[0], apo[1], mass, drag['cda_trim']),
                          _peak_q_psf(apo[0], apo[1], mass, drag['cda_end_over_end']))
    for trimmed, tumbling in peaks.values():
        assert tumbling < 1600.0 and 1700.0 < trimmed          # the band holds it
    # The SRB's outline moves the trimmed end toward the published value.
    assert peaks[True][0] < 0.9 * peaks[False][0]


def ecef_alt_ft(pos):
    from coordinates import ecef_to_geodetic
    return ecef_to_geodetic(pos)[2] / _FT
