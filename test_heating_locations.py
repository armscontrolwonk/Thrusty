"""Location-based convective heating — Tauber, NASA TP-2914 (1989).

Three kinds of test, kept apart:

1. TRANSCRIPTION.  Each relation reproduces a value worked by hand from the
   printed equation, so a mistyped constant or exponent fails here.
2. PHYSICS THE EQUATIONS IMPLY.  Scalings and limits that must hold whatever
   the constants are (flux falls as the wall heats; a radiating wall cannot
   be hotter than the gas).
3. ACCURACY AGAINST NAMED CASES.  The figures recorded in
   heating_locations.ACCURACY are recomputed from the published conditions.
   These are statements of how well the method does, NOT targets it was
   tuned to meet: several are outside the project's 3-5% temperature goal,
   and the test pins them where they are so that an improvement or a
   regression is visible.

Sources for the case data, all read from primary:
  FIRE II   Hash et al., AIAA 2007-605, Table I (conditions, measured wall
            temperature, nose radius), Table II (computed convective), and
            the measured total heating quoted on p. 4
  Stardust  Liu et al., AIAA 2008-1213, Table 3 (flight reconstruction) and
            geometry; Trumble et al., JSR 47(5), 2010 (942 W/cm^2, wall
            emissivity 0.85)
  SHEFEX II Bohrk et al., AIAA 2012-5919, Table 2 (arc-jet conditions), tip
            radius 0.8 mm, tip temperature 1635 C
  H2K       Park, Neeb, Plyushchev, Leyland & Gulhan, Acta Astronautica 187
            (2021), Tables 1 and 2: DLR H2K tunnel conditions, measured
            stagnation heating on a 12.5 mm sphere, and the paper's own
            evaluation of eleven correlations including Tauber's.
  Poll      D. I. A. Poll, "Skin Friction and Heat Transfer at an Infinite
            Swept Attachment Line", The Aeronautical Quarterly 32 (1981)
            299-318.  Transcribed by three independent readers using
            different methods and reconciled; every equation used here was
            read identically by all three.  Its printed limits (1.07, 6.44,
            0.90 + 0.53 tan^2) are reproduced below.
  CUBRC     Holden & Kolly, AIAA 95-2279, Tables 5 and 7: conditions for each
            run on a 3 inch diameter swept cylinder, in US customary units,
            with density tabulated.  Matched to Zhou's cases 25-36 by sweep,
            Mach number, unit Reynolds number and temperature.
  Cylinders Zhou, Yi, Wang & Li, AIAA Journal 61(3), 2023, Table 1: measured
            Stanton numbers on spheres, cylinders and swept cylinders in
            five wind tunnels, with radius, sweep, Mach number, unit
            Reynolds number, free-stream and wall temperature.  The CALVT
            sphere cases (9-12) are left out: no wall temperature is given.
  STS-3     Throckmorton, Hamilton & Zoby, NASA TM 84500, 1982, Table I:
            flight conditions with day-of-flight density, and measured wall
            temperature and convective heating along the windward
            centreline; reference length L = 32.89 m.  Transcribed from the
            page images of six of the 21 tabulated flight points.
"""

import math

import numpy as np
import pytest

import heating
import heating_locations as hl


# ── 1. Transcription ────────────────────────────────────────────────────────
def test_stagnation_point_is_equation_40():
    # 1.83e-4 * sqrt(1e-4 / 1.0) * 7000^3, cold wall
    q = hl.stagnation_point_flux(1.0e-4, 7000.0, 1.0)
    assert float(q) == pytest.approx(1.83e-4 * 1.0e-2 * 3.43e11, rel=1e-12)


def test_stagnation_constant_against_sutton_graves():
    """Same functional form as heating.py's Sutton-Graves; only the constant
    differs (1.83 against 1.7415)."""
    rho, V, r = 3.0e-4, 6500.0, 0.3
    ratio = float(hl.stagnation_point_flux(rho, V, r)) / float(
        heating._stag_flux(rho, V, r))
    assert ratio == pytest.approx(1.83 / 1.7415, rel=1e-9)


def test_swept_cylinder_is_equation_41():
    rho, V, r, sweep = 1.0e-4, 6000.0, 0.04, 60.0
    k = 1.0 - 0.18 * math.sin(math.radians(sweep)) ** 2          # 0.865
    expected = 1.29e-4 * math.sqrt(rho / r) * k * V ** 3 * math.cos(
        math.radians(sweep))
    assert k == pytest.approx(0.865)
    assert float(hl.swept_cylinder_flux(rho, V, r, sweep)) == pytest.approx(
        expected, rel=1e-12)


def test_unswept_cylinder_to_sphere_ratio():
    """Equal radius, square to the flow, cold wall: 1.29 / 1.83."""
    rho, V, r = 2.0e-4, 5000.0, 0.1
    ratio = float(hl.swept_cylinder_flux(rho, V, r, 0.0)) / float(
        hl.stagnation_point_flux(rho, V, r))
    assert ratio == pytest.approx(1.29 / 1.83, rel=1e-9)


def test_laminar_plate_and_cone_are_equations_48_and_46():
    rho, V, x, d = 5.0e-4, 4000.0, 2.0, 20.0
    common = (math.sqrt(rho * math.cos(math.radians(d)) / x) * V ** 3.2
              * math.sin(math.radians(d)))
    assert float(hl.laminar_surface_flux(rho, V, x, d)) == pytest.approx(
        2.42e-5 * common, rel=1e-12)
    assert float(hl.laminar_surface_flux(rho, V, x, d, cone=True)) == \
        pytest.approx(4.03e-5 * common, rel=1e-12)


def test_turbulent_plate_is_equation_56_on_both_sides_of_the_split():
    rho, x, d, Tw = 1.0e-3, 3.0, 15.0, 900.0
    s2 = math.sin(math.radians(d)) ** 2
    c = math.cos(math.radians(d))
    for V in (3000.0, 5000.0):
        wall = 0.9 - hl.CP_AIR * Tw / (0.5 * V * V)
        if V <= 3960.0:
            expected = (3.72e-4 * (rho * s2 * c ** 2.22) ** 0.8
                        / (x ** 0.2 * (Tw / 555.0) ** 0.25) * V ** 3.37 * wall)
        else:
            expected = (2.45e-5 * (rho * s2 * c ** 2.62) ** 0.8
                        / x ** 0.2 * V ** 3.7 * wall)
        assert float(hl.turbulent_surface_flux(rho, V, x, d, Tw)) == \
            pytest.approx(expected, rel=1e-12)


def test_turbulent_cone_is_1p15_times_plate():
    a = float(hl.turbulent_surface_flux(1e-3, 3000.0, 3.0, 15.0, 900.0))
    b = float(hl.turbulent_surface_flux(1e-3, 3000.0, 3.0, 15.0, 900.0,
                                        cone=True))
    assert b / a == pytest.approx(1.15, rel=1e-12)


def test_turbulent_run_is_measured_from_transition():
    a = float(hl.turbulent_surface_flux(1e-3, 3000.0, 3.0, 15.0, 900.0,
                                        x_transition_m=1.0))
    b = float(hl.turbulent_surface_flux(1e-3, 3000.0, 2.0, 15.0, 900.0))
    assert a == pytest.approx(b, rel=1e-12)


def test_turbulent_relation_refuses_what_it_cannot_represent():
    with pytest.raises(ValueError):          # Eq. 56a divides by T_w
        hl.turbulent_surface_flux(1e-3, 3000.0, 3.0, 15.0, 0.0)
    with pytest.raises(ValueError):          # station ahead of transition
        hl.turbulent_surface_flux(1e-3, 3000.0, 1.0, 15.0, 900.0,
                                  x_transition_m=2.0)
    # below the stated 1500 m/s floor there is no answer, not a wrong one
    assert math.isnan(float(hl.turbulent_surface_flux(1e-3, 1200.0, 3.0,
                                                      15.0, 900.0)))


def test_leading_edge_is_equation_49():
    rho, V, r, sweep, alpha, x, d = 2e-4, 5500.0, 0.05, 50.0, 10.0, 1.5, 10.0
    q_cyl = float(hl.swept_cylinder_flux(rho, V, r, sweep))
    q_fp = float(hl.laminar_surface_flux(rho, V, x, d))
    expected = (math.sqrt(q_cyl ** 2
                          + (q_fp * math.sin(math.radians(sweep))) ** 2)
                * math.cos(math.radians(alpha)))
    assert float(hl.leading_edge_flux(rho, V, r, sweep, alpha, x, d)) == \
        pytest.approx(expected, rel=1e-12)


def test_unswept_leading_edge_at_zero_incidence_is_the_cylinder():
    q_le = float(hl.leading_edge_flux(2e-4, 5500.0, 0.05, 0.0, 0.0, 1.5, 10.0))
    assert q_le == pytest.approx(
        float(hl.swept_cylinder_flux(2e-4, 5500.0, 0.05, 0.0)), rel=1e-12)


# ── 2. Physics the equations imply ──────────────────────────────────────────
def test_laminar_flux_falls_as_inverse_root_of_distance():
    a = float(hl.laminar_surface_flux(7e-4, 3536.0, 2.0, 39.2, 800.0, 260.0))
    b = float(hl.laminar_surface_flux(7e-4, 3536.0, 4.0, 39.2, 800.0, 260.0))
    assert a / b == pytest.approx(math.sqrt(2.0), rel=1e-12)


def test_flux_falls_as_the_wall_heats_and_never_goes_negative():
    rho, V, r, Tinf = 1e-2, 2800.0, 0.05, 230.0
    q = [float(hl.stagnation_point_flux(rho, V, r, Tw, Tinf))
         for Tw in (300.0, 1000.0, 2000.0, 3000.0, 6000.0)]
    assert all(x >= y for x, y in zip(q, q[1:]))
    assert q[0] > 0.0
    assert q[-1] == 0.0          # wall above the recovery enthalpy: no heat in


def test_radiating_wall_balances_and_stays_below_the_gas():
    rho, V, r, Tinf, eps = 1.84e-2, 2791.0, 0.05, 227.0, 0.85
    Tw, q = hl.radiating_wall(
        lambda T: hl.stagnation_point_flux(rho, V, r, T, Tinf), eps)
    assert q == pytest.approx(eps * hl.SIGMA * Tw ** 4, rel=1e-4)
    # temperature at which the hot-wall term vanishes
    T_gas = (hl.CP_AIR * Tinf + 0.5 * V * V) / hl.CP_AIR
    assert Tw < T_gas


def test_the_cold_wall_screen_breaks_that_limit_and_this_one_does_not():
    """The case that prompted the revision: SHEFEX II at 30 km, 0.8 mm tip.
    heating.py's cold-wall radiative equilibrium gives a wall hotter than the
    air's own total temperature; the wall balance here cannot."""
    rho, V, r, Tinf, eps = 1.84e-2, 2791.0, 0.0008, 227.0, 0.85
    T_gas = Tinf + 0.5 * V * V / hl.CP_AIR
    T_cold = (float(heating._stag_flux(rho, V, r)) / (eps * hl.SIGMA)) ** 0.25
    T_bal, _ = hl.radiating_wall(
        lambda T: hl.stagnation_point_flux(rho, V, r, T, Tinf), eps)
    assert T_cold > T_gas
    assert T_bal < T_gas


def test_extra_flux_raises_the_wall_temperature():
    f = lambda T: hl.stagnation_point_flux(8e-4, 10000.0, 0.8, T, 270.0)
    T0, _ = hl.radiating_wall(f, 0.85)
    T1, _ = hl.radiating_wall(f, 0.85, extra_flux=3.0e6)
    assert T1 > T0


# ── 3. Accuracy against named cases ─────────────────────────────────────────
#            time    V      rho      r_n     T_inf  T_wall  flight total
FIRE_II = [(1636, 11310.0, 8.57e-5, 0.9347, 210.0, 810.0, 290.0),
           (1643, 10480.0, 7.80e-4, 0.8052, 276.0, 640.0, 1025.0),
           (1651, 6190.0, 6.05e-3, 0.7021, 253.0, 1060.0, 390.0)]
# computed convective, W/cm^2, 11 species: (DPLR, LAURA, US3D)
FIRE_II_SUPERCATALYTIC = {1636: (301, 307, 309), 1643: (805, 802, 797),
                          1651: (511, 477, 506)}


def _fire_ii_total(V, rho, r_n, T_inf, T_wall):
    conv = float(hl.stagnation_point_flux(rho, V, r_n, T_wall, T_inf))
    rad = float(heating.radiative_flux(np.array([rho]), np.array([V]),
                                       r_n)[0][0])
    return conv, rad


def _recorded(location, case_prefix):
    for c in hl.ACCURACY[location]["cases"]:
        if c["case"].startswith(case_prefix):
            return c
    raise KeyError(case_prefix)


@pytest.mark.parametrize("t,V,rho,r_n,T_inf,T_wall,flight", FIRE_II)
def test_fire_ii_flight_totals(t, V, rho, r_n, T_inf, T_wall, flight):
    conv, rad = _fire_ii_total(V, rho, r_n, T_inf, T_wall)
    err = (conv + rad) / (flight * 1e4) - 1.0
    rec = _recorded("nose_cap", f"FIRE II {t} s")
    assert err == pytest.approx(rec["flux"], abs=0.01)
    assert (1.0 + err) ** 0.25 - 1.0 == pytest.approx(rec["temperature"],
                                                      abs=0.01)
    assert abs(err) < 0.25          # inside the flux target band, with margin


@pytest.mark.parametrize("t,V,rho,r_n,T_inf,T_wall,flight", FIRE_II)
def test_fire_ii_convective_is_below_fully_catalytic_computation(
        t, V, rho, r_n, T_inf, T_wall, flight):
    """The stated shortfall, pinned: 18-24% at all three points."""
    conv, _ = _fire_ii_total(V, rho, r_n, T_inf, T_wall)
    cfd = float(np.mean(FIRE_II_SUPERCATALYTIC[t])) * 1e4
    assert -0.24 < conv / cfd - 1.0 < -0.18


def test_stardust_peak_heating_point():
    rho, V, r_n, T_inf, eps = 2.11e-4, 10871.38, 0.2286, 234.95, 0.85
    T_wall, q = hl.radiating_wall(
        lambda T: hl.stagnation_point_flux(rho, V, r_n, T, T_inf), eps)
    q_ref = 942.0e4
    T_ref = (q_ref / (eps * hl.SIGMA)) ** 0.25
    rec = _recorded("nose_cap", "Stardust")
    assert q / q_ref - 1.0 == pytest.approx(rec["flux"], abs=0.01)
    assert T_wall / T_ref - 1.0 == pytest.approx(rec["temperature"], abs=0.01)


def test_sharp_solid_tip_is_outside_the_radiating_wall_model():
    """SHEFEX II arc-jet.  The tunnel stream carries 11.9 MJ/kg in total, more
    than its speed alone accounts for, so the static part is passed as h_inf."""
    rho, V, r, eps = 4.1e-4, 3803.0, 0.0008, 0.85
    h_inf = 11.9e6 - 0.5 * V * V
    T_wall, _ = hl.radiating_wall(
        lambda T: hl.stagnation_point_flux(rho, V, r, T, h_inf=h_inf), eps)
    T_ref = 1635.0 + 273.15
    rec = _recorded("sharp_tip", "SHEFEX II")
    assert T_wall / T_ref - 1.0 == pytest.approx(rec["temperature"], abs=0.01)
    assert T_wall / T_ref > 1.5      # the failure is large, and is recorded


# STS-3 windward centreline, NASA TM 84500 Table I.
STS3_L = 32.89                                   # m, reference body length
STS3_XL = (0.025, 0.098, 0.140, 0.166, 0.194, 0.255, 0.285, 0.401, 0.497,
           0.592, 0.795, 0.894, 0.986)
# time s: (V m/s, alpha deg, T_inf K, rho kg/m3, T_wall K[...], q_c kW/m2[...])
STS3 = {
    350: (7400.0, 39.6, 199.0, 3.32e-5,
          (1324, 1124, 1108, 1193, 1051, 1048, 1019, 1016, 1009, 1002, 1017, 971, 647),
          (168.0, 86.7, 81.7, 112.0, 67.3, 66.2, 59.4, 58.6, 57.3, 56.5, 59.1, 50.2, 10.4)),
    745: (6090.0, 39.9, 233.0, 1.23e-4,
          (1403, 1211, 1200, 1192, 1136, 1113, 1096, 1064, 1038, 1033, 1041, 988, 673),
          (205.0, 114.0, 109.0, 106.0, 87.7, 81.3, 76.2, 67.9, 61.7, 60.4, 62.2, 51.1, 11.4)),
    920: (4980.0, 43.0, 262.0, 2.77e-4,
          (1384, 1183, 1147, 1145, 1082, 1052, 1048, 1016, 982, 955, 981, 963, 662),
          (192.0, 103.0, 90.5, 89.9, 72.0, 64.4, 63.7, 56.2, 48.9, 43.9, 48.9, 45.7, 9.2)),
    1015: (4070.0, 39.6, 272.0, 5.80e-4,
           (1295, 1102, 1066, 1054, 1007, 967, 967, 938, 918, 877, 874, 889, 594),
           (145.0, 76.7, 67.0, 62.5, 53.5, 42.8, 45.5, 40.3, 37.1, 30.8, 29.5, 31.8, 5.8)),
    1080: (3440.0, 38.9, 273.0, 8.36e-4,
           (1204, 1021, 978, 965, 930, 895, 901, 875, 865, 807, 798, 799, 574),
           (107.0, 54.8, 45.4, 42.9, 37.2, 32.0, 32.8, 29.4, 29.1, 20.2, 19.1, 19.3, 5.3)),
    1220: (2210.0, 29.6, 259.0, 2.72e-3,
           (972, 820, 941, 936, 929, 924, 924, 928, 937, 940, 947, 889, 858),
           (41.6, 20.5, 42.1, 39.8, 39.6, 39.1, 39.3, 40.1, 41.2, 40.4, 40.9, 31.6, 27.8)),
}
STS3_LAMINAR_POINTS = (350, 745, 920, 1015, 1080)
STS3_MIDBODY = range(4, 10)          # x/L 0.194 .. 0.592


def _sts3_laminar_errors(cone):
    """(computed / flight - 1) at the mid-body stations of the five laminar
    flight points.  The measured wall temperature feeds the hot-wall term, so
    no emissivity is assumed."""
    errs = []
    for t in STS3_LAMINAR_POINTS:
        V, alpha, T_inf, rho, T_wall, q_flight = STS3[t]
        for i in STS3_MIDBODY:
            q = float(hl.laminar_surface_flux(
                rho, V, STS3_XL[i] * STS3_L, alpha, T_wall[i], T_inf,
                cone=cone))
            errs.append(q / (q_flight[i] * 1e3) - 1.0)
    return np.array(errs)


@pytest.mark.parametrize("cone,case", [
    (False, "STS-3 belly, laminar, flat-plate value"),
    (True, "STS-3 belly, laminar, cone value"),
])
def test_sts3_laminar_windward_face(cone, case):
    e = _sts3_laminar_errors(cone)
    rec = _recorded("windward_face", case)
    assert e.mean() == pytest.approx(rec["flux"], abs=0.01)
    assert ((1.0 + e) ** 0.25 - 1.0).mean() == pytest.approx(
        rec["temperature"], abs=0.01)


def test_sts3_flight_lies_between_plate_and_cone():
    plate = _sts3_laminar_errors(cone=False)
    cone = _sts3_laminar_errors(cone=True)
    inside = int(np.sum((plate <= 0.0) & (cone >= 0.0)))
    assert plate.size == 30
    assert inside == 28


def test_sts3_turbulent_windward_face():
    """2.21 km/s, 42.8 km.  The flight distribution jumps between x/L 0.098
    and 0.140, so transition is taken to begin at 0.098."""
    V, alpha, T_inf, rho, T_wall, q_flight = STS3[1220]
    e = np.array([
        float(hl.turbulent_surface_flux(
            rho, V, STS3_XL[i] * STS3_L, alpha, T_wall[i], T_inf,
            x_transition_m=0.098 * STS3_L)) / (q_flight[i] * 1e3) - 1.0
        for i in range(5, 11)])               # x/L 0.255 .. 0.795
    rec = _recorded("windward_face", "STS-3 belly, turbulent")
    assert e.mean() == pytest.approx(rec["flux"], abs=0.01)
    assert ((1.0 + e) ** 0.25 - 1.0).mean() == pytest.approx(
        rec["temperature"], abs=0.01)


# Zhou et al. 2023, Table 1.
# case, kind (s sphere, c cylinder, scl swept cylinder laminar), radius m,
# sweep deg, Mach, Reynolds per metre, T_inf K, T_wall K, Stanton x 100
ZHOU = (
    (1, "s", 0.0125, 0.0, 5.3, 1.6e7, 65.0, 303.0, 1.0),
    (2, "s", 0.0125, 0.0, 5.3, 5.9e6, 76.0, 298.0, 1.6),
    (3, "s", 0.01, 0.0, 6.0, 5.5e6, 124.0, 286.0, 1.7),
    (4, "s", 0.01, 0.0, 6.0, 8.4e6, 102.0, 286.0, 1.4),
    (5, "s", 0.02, 0.0, 10.0, 1.9e6, 60.0, 300.0, 3.3),
    (6, "s", 0.02, 0.0, 10.0, 7.3e6, 56.0, 300.0, 1.7),
    (7, "s", 0.02, 0.0, 11.7, 1.7e6, 51.0, 300.0, 4.2),
    (8, "s", 0.02, 0.0, 11.9, 4.4e6, 50.0, 300.0, 2.5),
    (13, "c", 0.012, 0.0, 6.0, 5.5e6, 124.0, 297.0, 1.2),
    (14, "c", 0.015, 0.0, 6.0, 7.2e5, 69.0, 300.0, 3.3),
    (15, "c", 0.008, 0.0, 10.0, 1.7e5, 52.0, 300.0, 13.0),
    (16, "scl", 0.005, 60.0, 6.0, 5.5e6, 124.0, 286.0, 0.76),
    (17, "scl", 0.005, 60.0, 6.0, 8.4e6, 102.0, 286.0, 0.61),
    (18, "scl", 0.01, 60.0, 6.0, 5.5e6, 124.0, 286.0, 0.54),
    (19, "scl", 0.005, 60.0, 10.0, 1.9e6, 60.0, 300.0, 1.8),
    (20, "scl", 0.005, 60.0, 10.0, 7.3e6, 56.0, 300.0, 0.95),
    (21, "scl", 0.005, 60.0, 11.7, 1.7e6, 51.0, 300.0, 2.2),
    (22, "scl", 0.005, 60.0, 11.9, 4.4e6, 50.0, 300.0, 1.4),
    (23, "scl", 0.02, 60.0, 10.0, 1.9e6, 60.0, 300.0, 1.1),
    (24, "scl", 0.02, 60.0, 11.7, 1.7e6, 51.0, 300.0, 1.3),
    (25, "scl", 0.038, 60.0, 10.6, 6.2e6, 46.0, 294.0, 0.42),
    (26, "scl", 0.038, 66.5, 10.4, 2.7e6, 52.0, 294.0, 0.43),
    (27, "scl", 0.038, 66.5, 10.5, 8.0e6, 53.0, 294.0, 0.26),
    (28, "scl", 0.038, 66.5, 10.6, 1.2e7, 53.0, 294.0, 0.23),
    (29, "scl", 0.038, 66.5, 11.3, 1.4e5, 142.0, 294.0, 1.8),
    (30, "scl", 0.038, 66.5, 11.4, 5.1e5, 73.0, 294.0, 1.1),
)


def _zhou_errors(kind):
    """(computed / measured - 1) in Stanton number, the paper's Eq. (2).

    The table gives unit Reynolds number, not density.  Density is recovered
    with Sutherland's viscosity law (heating._sutherland_mu).  The paper's
    own Eq. (4), a power law, must NOT be used for this: at the 46-142 K of
    these tunnels it overstates viscosity by up to half, which overstates
    density and makes every case read about 15% low.  Sutherland's law is
    within 4% of the viscosity implied by the DLR tunnel's own pressure,
    temperature and Reynolds number (test below)."""
    errs = []
    for _, k, r, sweep, mach, re_m, T_inf, T_wall, st in ZHOU:
        if k != kind:
            continue
        U = mach * math.sqrt(1.4 * 287.0 * T_inf)
        rho = re_m * float(heating._sutherland_mu(T_inf)) / U
        if k == "s":
            q = float(hl.stagnation_point_flux(rho, U, r, T_wall, T_inf))
        else:
            q = float(hl.swept_cylinder_flux(rho, U, r, sweep, T_wall, T_inf))
        h0 = hl.CP_AIR * T_inf + 0.5 * U * U
        st_calc = q / (rho * U * (h0 - hl.CP_AIR * T_wall)) * 100.0
        errs.append(st_calc / st - 1.0)
    return np.array(errs)


@pytest.mark.parametrize("kind,location,case,n", [
    ("s", "nose_cap", "Spheres, wind tunnel", 8),
    ("c", "leading_edge", "Unswept cylinders, wind tunnel", 3),
    ("scl", "leading_edge", "Swept cylinders, laminar, wind tunnel", 15),
])
def test_wind_tunnel_spheres_and_cylinders(kind, location, case, n):
    e = _zhou_errors(kind)
    assert e.size == n
    rec = _recorded(location, case)
    assert e.mean() == pytest.approx(rec["flux"], abs=0.01)
    assert ((1.0 + e) ** 0.25 - 1.0).mean() == pytest.approx(
        rec["temperature"], abs=0.01)


def test_most_wind_tunnel_cases_are_within_twenty_percent():
    assert int(np.sum(np.abs(_zhou_errors("s")) <= 0.20)) == 8
    assert int(np.sum(np.abs(_zhou_errors("c")) <= 0.20)) == 3
    assert int(np.sum(np.abs(_zhou_errors("scl")) <= 0.20)) == 14


# CUBRC 48-inch shock tunnel, Holden & Kolly, AIAA 95-2279, Tables 5 and 7.
# Zhou case: (run, sweep deg, U ft/s, T_inf deg R, density slug/ft3,
#             viscosity slug/(ft s), measured Stanton x 100 from Zhou Table 1)
FT, SLUG_FT3, RANKINE, SLUG_FT_S = 0.3048, 515.378818, 5.0 / 9.0, 47.880259
CUBRC_RADIUS = 1.5 * 0.0254
CUBRC_T_WALL = 294.0                   # Zhou's assumption; not in the original
CUBRC_LAMINAR = {
    25: (34, 60.0, 4756.6, 82.36, 2.563e-5, 6.490e-8, 0.42),
    26: (4, 66.5, 5037.8, 94.43, 1.201e-5, 7.433e-8, 0.43),
    27: (5, 66.5, 5112.5, 95.32, 3.567e-5, 7.502e-8, 0.26),
    28: (18, 66.5, 5114.5, 94.81, 5.239e-5, 7.462e-8, 0.23),
    29: (1, 66.5, 8961.2, 255.7, 9.531e-7, 2.000e-7, 1.8),
    30: (2, 66.5, 6386.8, 130.5, 2.657e-6, 1.092e-7, 1.1),
}
CUBRC_TRIPPED_TURBULENT = {
    31: (13, 66.5, 4865.0, 86.39, 2.479e-5, 6.804e-8, 0.60),
    32: (9, 66.5, 5097.8, 94.74, 3.559e-5, 7.457e-8, 0.58),
    33: (6, 66.5, 5095.7, 94.20, 4.770e-5, 7.415e-8, 0.56),
    34: (16, 66.5, 6778.8, 135.5, 1.626e-5, 1.071e-7, 0.69),
    35: (26, 70.0, 5018.0, 91.00, 5.459e-5, 7.164e-8, 0.48),
    36: (28, 75.0, 4988.3, 89.81, 5.641e-5, 7.071e-8, 0.33),
}


def _cubrc_ratio(row):
    """Eq. (41) Stanton number over the measured one, tunnel density used
    as tabulated."""
    _, sweep, U, T, rho, _, st = row
    U, T, rho = U * FT, T * RANKINE, rho * SLUG_FT3
    q = float(hl.swept_cylinder_flux(rho, U, CUBRC_RADIUS, sweep,
                                     CUBRC_T_WALL, T))
    h0 = hl.CP_AIR * T + 0.5 * U * U
    return q / (rho * U * (h0 - hl.CP_AIR * CUBRC_T_WALL)) * 100.0 / st


def test_swept_cylinder_with_the_tunnel_density_given():
    e = np.array([_cubrc_ratio(r) for r in CUBRC_LAMINAR.values()]) - 1.0
    rec = _recorded("leading_edge", "Swept cylinder, laminar, tunnel density")
    assert e.mean() == pytest.approx(rec["flux"], abs=0.01)
    assert ((1.0 + e) ** 0.25 - 1.0).mean() == pytest.approx(
        rec["temperature"], abs=0.01)
    assert np.all(np.abs(e) <= 0.20)


def test_sutherland_recovers_the_tabulated_tunnel_density():
    """The check that was missing when density was first backed out of
    Zhou's Reynolds numbers with the wrong viscosity law."""
    for rows in (CUBRC_LAMINAR, CUBRC_TRIPPED_TURBULENT):
        for _, _, U, T, rho, mu, _ in rows.values():
            re_m = rho * SLUG_FT3 * U * FT / (mu * SLUG_FT_S)
            rho_back = (re_m * float(heating._sutherland_mu(T * RANKINE))
                        / (U * FT))
            assert rho_back == pytest.approx(rho * SLUG_FT3, rel=0.08)


# ── Poll (1981): the attachment line, laminar and turbulent ─────────────────
_POLL_CASE = dict(rho=2.0e-3, V=3000.0, radius_m=0.05, sweep_deg=60.0,
                  T_wall_K=600.0, T_inf_K=230.0)


def _poll_stanton(turbulent):
    """St_e = q / (c_p rho_e V_e (T_r - T_w)), recovered from the flux."""
    c = _POLL_CASE
    r = hl.POLL_RECOVERY if turbulent else hl.LAMINAR_EDGE_RECOVERY
    st = hl.attachment_line_state(c['rho'], c['V'], c['T_inf_K'],
                                  c['radius_m'], c['sweep_deg'],
                                  c['T_wall_K'], recovery_factor=r)
    q = float(hl.attachment_line_flux(c['rho'], c['V'], c['radius_m'],
                                      c['sweep_deg'], c['T_wall_K'],
                                      c['T_inf_K'], turbulent=turbulent))
    St = q / (hl.CP_AIR * st['rho_e'] * st['V_e']
              * (st['T_r'] - c['T_wall_K']))
    return float(St), st


def test_poll_laminar_is_equation_11():
    St, st = _poll_stanton(False)
    assert St * 0.7 ** (2.0 / 3.0) * float(st['Rbar']) == pytest.approx(
        0.571, rel=1e-4)


def test_poll_turbulent_is_equations_14_and_15():
    St, st = _poll_stanton(True)
    T_star = (st['T_e'] + 0.10 * (600.0 - st['T_e'])
              + 0.60 * (st['T_r'] - st['T_e']))
    assert float(st['T_star']) == pytest.approx(float(T_star), rel=1e-12)
    expected = (0.0345 / 0.7 ** (2.0 / 3.0)
                * (st['T_e'] / T_star) ** 0.79
                * (hl.keyes_viscosity(T_star)
                   / hl.keyes_viscosity(st['T_e'])) ** 0.21
                / st['Rbar'] ** 0.42)
    assert St == pytest.approx(float(expected), rel=1e-4)


def test_poll_attachment_line_reynolds_number_is_equation_2():
    _, st = _poll_stanton(True)
    nu_e = float(st['mu_e'] / st['rho_e'])
    eta = math.sqrt(nu_e / float(st['dUdx']))
    assert float(st['Rbar']) == pytest.approx(float(st['V_e']) * eta / nu_e,
                                              rel=1e-12)
    assert float(st['V_e']) == pytest.approx(
        3000.0 * math.sin(math.radians(60.0)), rel=1e-12)


def test_poll_printed_hypersonic_limits_are_reproduced():
    """Eq. (18b): (D/C) U_1 -> 1.07.  Eq. (18c): rho_e/rho_inf -> 6.44.
    Eq. (22e): T*/T_e -> 0.90 + 0.53 tan^2(sweep), cold wall, r = 0.89."""
    sweep, T, rho = 60.0, 200.0, 1.0e-3
    V = 400.0 * math.sqrt(1.4 * hl.R_AIR * T)          # Mach 400
    st = hl.attachment_line_state(rho, V, T, 0.05, sweep, 1.0e-6)
    U_inf = V * math.cos(math.radians(sweep))
    assert float(st['dUdx']) * 0.10 / U_inf == pytest.approx(1.07, abs=0.005)
    assert float(st['rho_e']) / rho == pytest.approx(6.44, abs=0.005)
    assert float(st['T_star'] / st['T_e']) == pytest.approx(
        0.90 + 0.53 * math.tan(math.radians(sweep)) ** 2, rel=0.01)


def test_keyes_and_sutherland_viscosity_agree_where_both_apply():
    T = np.array([216.0, 300.0, 600.0, 1000.0, 2000.0])
    ratio = hl.keyes_viscosity(T) / heating._sutherland_mu(T)
    assert np.all(np.abs(ratio - 1.0) < 0.03)


def test_two_sources_agree_on_the_unswept_laminar_cylinder():
    """Poll's laminar relation at zero sweep against Tauber's Eq. (41): two
    sources, two derivations, within 5% of each other from 3 to 6 km/s.
    Poll's is a perfect-gas relation, and at 6 km/s its edge temperature is
    far above what real air reaches; the heat flux still agrees, because it
    depends on the enthalpy difference, not on that temperature.  Below
    about 2 km/s they part (9% at 1.5 km/s): Tauber's relation is a
    high-speed form, Poll's holds at any Mach number."""
    for rho, V, T in ((1e-3, 3000.0, 230.0), (1e-3, 4500.0, 240.0),
                      (3e-4, 6000.0, 250.0)):
        poll = float(hl.attachment_line_flux(rho, V, 0.05, 0.0, 300.0, T))
        tauber = float(hl.swept_cylinder_flux(rho, V, 0.05, 0.0, 300.0, T))
        assert poll == pytest.approx(tauber, rel=0.05)


def test_turbulent_relation_vanishes_at_zero_sweep_and_laminar_does_not():
    """Poll, p. 316: the turbulent result at zero sweep is 'clearly
    physically unrealistic'; the flow there is laminar."""
    assert float(hl.attachment_line_flux(1e-3, 3000.0, 0.05, 0.0, 300.0,
                                         230.0, turbulent=True)) == 0.0
    assert float(hl.attachment_line_flux(1e-3, 3000.0, 0.05, 0.0, 300.0,
                                         230.0)) > 0.0


def test_attachment_line_flux_accepts_arrays():
    q = hl.attachment_line_flux(np.array([1e-3, 2e-3]),
                                np.array([3000.0, 2500.0]), 0.05, 60.0,
                                300.0, np.array([230.0, 240.0]),
                                turbulent=True)
    assert q.shape == (2,) and np.all(q > 0.0)


def _cubrc_poll_errors(rows, turbulent):
    # CUBRC_* and the unit constants are defined with the CUBRC cases below
    errs = []
    for _, sweep, U, T, rho, _, st in rows.values():
        U, T, rho = U * FT, T * RANKINE, rho * SLUG_FT3
        q = float(hl.attachment_line_flux(rho, U, CUBRC_RADIUS, sweep,
                                          CUBRC_T_WALL, T,
                                          turbulent=turbulent))
        h0 = hl.CP_AIR * T + 0.5 * U * U
        errs.append(q / (rho * U * (h0 - hl.CP_AIR * CUBRC_T_WALL))
                    * 100.0 / st - 1.0)
    return np.array(errs)


@pytest.mark.parametrize("rows,turbulent,case", [
    (CUBRC_LAMINAR, False, "Attachment line, laminar, Poll"),
    (CUBRC_TRIPPED_TURBULENT, True, "Attachment line, turbulent, Poll"),
])
def test_poll_relations_against_the_cubrc_runs(rows, turbulent, case):
    e = _cubrc_poll_errors(rows, turbulent)
    rec = _recorded("leading_edge", case)
    assert e.mean() == pytest.approx(rec["flux"], abs=0.01)
    assert ((1.0 + e) ** 0.25 - 1.0).mean() == pytest.approx(
        rec["temperature"], abs=0.01)


def test_poll_laminar_is_within_fifteen_percent_on_every_smooth_run():
    assert np.all(np.abs(_cubrc_poll_errors(CUBRC_LAMINAR, False)) < 0.15)


def test_poll_turbulent_reads_low_beyond_its_fitted_range():
    """Mach 10-12 and a wall at about a quarter of the stagnation
    temperature, against a fit made at Mach 2.4-8 and 0.4-1.  Every tripped
    run reads low, by 20% to 38%: a recorded limitation.  It is still far
    closer than the laminar relation, which is 42% to 67% low on the same
    runs."""
    e_turb = _cubrc_poll_errors(CUBRC_TRIPPED_TURBULENT, True)
    e_lam = _cubrc_poll_errors(CUBRC_TRIPPED_TURBULENT, False)
    assert -0.39 < e_turb.min() and e_turb.max() < -0.19
    assert np.all(e_lam < e_turb)
    assert -0.68 < e_lam.min() and e_lam.max() < -0.41


def test_tripped_runs_sit_where_holden_and_kolly_put_transition():
    """Holden & Kolly: with contamination the attachment line turns
    turbulent at reference-temperature Reynolds numbers of 300 to 500.
    Loose: their reference temperature is not defined identically."""
    for _, sweep, U, T, rho, _, _ in CUBRC_TRIPPED_TURBULENT.values():
        st = hl.attachment_line_state(rho * SLUG_FT3, U * FT, T * RANKINE,
                                      CUBRC_RADIUS, sweep, CUBRC_T_WALL)
        assert 250.0 < float(st['Rbar_star']) < 550.0


def test_a_turbulent_edge_runs_far_hotter_than_the_laminar_relation():
    """A recorded LIMITATION, not a success: no turbulent edge relation is
    implemented, and on tripped runs the measurement is 1.5 to 2.3 times
    what the laminar relation gives."""
    ratio = np.array([1.0 / _cubrc_ratio(r)
                      for r in CUBRC_TRIPPED_TURBULENT.values()])
    assert 1.45 < ratio.min() < 1.55
    assert 2.25 < ratio.max() < 2.40


# DLR H2K tunnel, Park et al., Acta Astronautica 187 (2021), Table 1 and
# Table 2: a 12.5 mm radius sphere with the tunnel's own static pressure, so
# no viscosity law is needed.  The paper evaluates Tauber's relation itself.
#          p_inf Pa, T_inf K, U m/s, T_wall K, measured, paper's Tauber value
H2K = (("Run01", 1560.0, 65.33, 862.23, 303.0, 9.6, 9.2),
       ("Run02", 740.0, 75.78, 924.29, 298.0, 10.2, 9.6))


@pytest.mark.parametrize("name,p,T_inf,U,T_wall,q_measured,q_paper", H2K)
def test_h2k_sphere(name, p, T_inf, U, T_wall, q_measured, q_paper):
    rho = p / (287.0 * T_inf)
    q = float(hl.stagnation_point_flux(rho, U, 0.0125, T_wall, T_inf)) / 1e4
    # the implementation reproduces an independent evaluation of Eq. (40)
    assert q == pytest.approx(q_paper, abs=0.1)
    # and is within the probe's stated 5-10% of the measurement
    assert abs(q / q_measured - 1.0) < 0.06


def test_sutherland_matches_the_viscosity_the_tunnel_data_imply():
    p, T_inf, U, re_m = 1560.0, 65.33, 862.23, 15.8e6
    mu_implied = p / (287.0 * T_inf) * U / re_m
    assert float(heating._sutherland_mu(T_inf)) == pytest.approx(
        mu_implied, rel=0.05)
    # the power law printed in Zhou et al. is far off at this temperature
    assert 1.716e-5 * (T_inf / 273.0) ** 0.67 > 1.4 * mu_implied


def test_every_location_states_its_accuracy():
    for name in ("nose_cap", "windward_face", "leading_edge", "sharp_tip"):
        rec = hl.ACCURACY[name]
        assert rec["note"]
        assert rec["cases"] or "yet" in rec["note"].lower()
        assert bool(rec["cases"]) == bool(rec["sources"])


# ── Bushnell, NASA TN D-3094 (1965): swept cylinder alone, Mach 8 ───────────
# Langley Mach 8 variable-density tunnel, 1 in. diameter cylinder at 45 and
# 60 deg sweep, run without the wedge ("undisturbed infinite-cylinder data").
# h = q / (T_aw - T_w) in Btu/ft^2 s R, with recovery factor 0.85 laminar and
# 0.89 turbulent (p. 8): the same definition as Poll's h at 0.89.  Stated
# accuracy 15%.  Values READ FROM FIGURES 16(b) (45 deg, T0 = 1325 R, M 7.95)
# and 17(b) (60 deg, T0 = 1330 R, M 7.95), about +/-3% in each coordinate;
# the highest-Reynolds run in each is the 2600 psi run, where Bushnell
# assumed Mach 8.  States: the author puts laminar flow up to R_inf,D of
# about 1.4e5 (p. 15); rows plotted on or near his turbulent line are taken
# as turbulent, rows between the lines are transitional and not used.
# Wall temperature: the author's reference, 100 F (p. 15); models started at
# room temperature and ran about 4 s.  Static temperature is not printed and
# is taken as isentropic from T0; density is recovered from R_inf,D with
# Sutherland's law, as for Zhou's cases.  With Keyes' law instead every
# figure moves up by 4 to 6 points.
BTU_FT2_S_R = 2.042e4                     # W/m^2 K, Bushnell p. 5
BUSHNELL_D = 0.0254
BUSHNELL_T_WALL = 311.0
BUSHNELL = {   # sweep: (T0 K, [(R_inf_D, h_s Btu/ft^2 s R, state)])
    45.0: (1325.0 / 1.8, [(0.88e5, .0079, 'lam'), (1.25e5, .0095, 'lam'),
                          (2.90e5, .0233, 'turb'), (3.17e5, .0266, 'turb'),
                          (8.74e5, .055, 'turb')]),
    60.0: (1330.0 / 1.8, [(0.88e5, .0054, 'lam'), (1.25e5, .0062, 'lam'),
                          (1.98e5, .0121, 'turb'), (2.26e5, .0141, 'turb'),
                          (2.54e5, .0160, 'turb'), (2.88e5, .0180, 'turb'),
                          (3.36e5, .0201, 'turb'), (8.64e5, .044, 'turb')]),
}


def _bushnell(state, relation):
    """(computed h / measured h - 1, Rbar_star) for every run in a state."""
    g = hl.POLL_GAMMA
    out = []
    for sweep, (T0, rows) in BUSHNELL.items():
        for Re, h_s, s in rows:
            if s != state:
                continue
            M = 8.0 if Re > 5e5 else 7.95
            T = T0 / (1.0 + (g - 1.0) / 2.0 * M * M)
            V = M * math.sqrt(g * hl.R_AIR * T)
            rho = Re * float(heating._sutherland_mu(T)) / (V * BUSHNELL_D)
            r = BUSHNELL_D / 2.0
            st = hl.attachment_line_state(rho, V, T, r, sweep,
                                          BUSHNELL_T_WALL)
            if relation == 'Eq. 41':
                T_r = st['T_e'] * (1.0 + hl.LAMINAR_EDGE_RECOVERY
                                   * (g - 1.0) / 2.0 * st['M_e'] ** 2)
                h = (float(hl.swept_cylinder_flux(rho, V, r, sweep,
                                                  BUSHNELL_T_WALL, T))
                     / (float(T_r) - BUSHNELL_T_WALL))
            else:
                q = hl.attachment_line_flux(rho, V, r, sweep,
                                            BUSHNELL_T_WALL, T,
                                            turbulent=(state == 'turb'))
                rf = hl.POLL_RECOVERY if state == 'turb' \
                    else hl.LAMINAR_EDGE_RECOVERY
                T_r = st['T_e'] * (1.0 + rf * (g - 1.0) / 2.0
                                   * st['M_e'] ** 2)
                h = float(q) / (float(T_r) - BUSHNELL_T_WALL)
            out.append((h / (h_s * BTU_FT2_S_R) - 1.0,
                        float(st['Rbar_star'])))
    return np.array(out)


@pytest.mark.parametrize("state,relation,case", [
    ('lam', 'Poll', "Attachment line, laminar, Poll, Bushnell"),
    ('turb', 'Poll', "Attachment line, turbulent, Poll, Bushnell"),
    ('lam', 'Eq. 41', "Swept cylinder, laminar, Eq. 41, Bushnell"),
])
def test_bushnell_mach_8_swept_cylinder(state, relation, case):
    e = _bushnell(state, relation)[:, 0]
    rec = _recorded("leading_edge", case)
    assert e.mean() == pytest.approx(rec["flux"], abs=0.01)
    assert ((1.0 + e) ** 0.25 - 1.0).mean() == pytest.approx(
        rec["temperature"], abs=0.01)


def test_poll_turbulent_holds_inside_its_fitted_range():
    """Mach 8, wall at 0.42 of stagnation temperature: inside the range Poll
    fitted (Mach 2.4-8, 0.4-1).  Every turbulent run is within Poll's stated
    maximum error of 19% plus the figure-reading uncertainty, against 20% to
    38% low on the CUBRC runs outside that range: the shortfall there is the
    range, not the transcription."""
    e = _bushnell('turb', 'Poll')[:, 0]
    assert np.all(e > -0.23) and np.all(e < 0.0)
    assert np.all(np.abs(_bushnell('lam', 'Poll')[:, 0]) < 0.06)


def test_bushnell_transition_sits_at_polls_critical_reynolds_number():
    """Laminar runs lie below Poll's critical Rbar* of about 245, turbulent
    runs above it."""
    assert np.all(_bushnell('lam', 'Poll')[:, 1] < 245.0)
    assert np.all(_bushnell('turb', 'Poll')[:, 1] > 245.0)
