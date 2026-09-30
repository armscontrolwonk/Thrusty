"""One-dimensional conduction in a solid conical tip (heating_solid.py).

Kept apart, as in test_heating_locations.py:

1. NUMERICS.  Energy is conserved, the answer does not depend on the mesh or
   the time step, and with nothing driving it the tip stays as it was.
2. PHYSICS.  Conduction cools the tip below the radiating-wall value and
   warms the body behind it; more conductive material, cooler tip.
3. ACCURACY AGAINST NAMED CASES.  SHEFEX II, in flight and in the arc-jet,
   against the thermocouple 20 mm behind the tip.  The figures recorded in
   heating_solid.ACCURACY are recomputed here.

Case data: Bohrk, Dittert, Weihs, Thiele & Gulhan, AIAA 2012-5919, read from
page images (the paper is a scan).
  tip radius 0.8 mm; mass about 680 g; tip length 160 mm (Fig. 3)
  C/C-SiC, Table 1: density 1900 kg/m^3, emissivity 0.85, c_p 1322 J/(kg K),
    conductivity 17 (x, along the axis) and 8 (y) W/(m K).  The exponent
    printed beside the conductivities is unreadable in this copy; 17 and 8
    W/(m K) is the reading that is physically possible.
  flight: 52 s from 101 km at 2559 m/s to 30 km at 2791 m/s; foremost
    thermocouple peaked at 848 C; thermocouples start near 150 C (Fig. 15)
  arc-jet, Table 2: density 4.1e-4 kg/m^3, 3803 m/s, static temperature
    411 K; foremost thermocouple reached 1179 C; heating lasted about 70 s
    (Fig. 9); tip 1635 C by the authors' heat-balance code

The flight path between the two stated end points is a reconstruction: speed
changing linearly with time, flight-path angle constant, US Standard
Atmosphere 1976 (called directly, so the result does not depend on whether
the optional atmosphere package is installed).
"""

import functools

import numpy as np
import pytest

import heating_locations as hl
import heating_solid as hs
from atmosphere import _atmosphere_std1976

TIP = dict(tip_radius_m=0.0008, length_m=0.160, density_kg_m3=1900.0,
           specific_heat_J_kgK=1322.0, conductivity_W_mK=17.0,
           emissivity=0.85)
HALF_ANGLE = hs.equivalent_cone_half_angle_deg(0.68, 1900.0, 0.160)
THERMOCOUPLE_X = 0.020


def _shefex_flight_arc():
    t = np.linspace(0.0, 52.0, 209)
    V = np.linspace(2559.0, 2791.0, t.size)
    sin_gamma = 71.0e3 / np.trapezoid(V, t)
    alt = 101.0e3 - np.cumsum(
        np.r_[0.0, 0.5 * (V[1:] + V[:-1]) * np.diff(t)]) * sin_gamma
    atm = [_atmosphere_std1976(float(a)) for a in alt]
    return (t, np.array([a[2] for a in atm]), V,
            np.array([a[0] for a in atm]))


def _flight(**over):
    t, rho, V, T_inf = _shefex_flight_arc()
    kw = dict(TIP, half_angle_deg=HALF_ANGLE, T_initial_K=150.0 + 273.15)
    kw.update(over)
    return hs.cone_tip_response(t, rho, V, T_inf, **kw)


def _arc_jet(**over):
    t = np.linspace(0.0, 70.0, 281)
    n = t.size
    kw = dict(TIP, half_angle_deg=HALF_ANGLE, T_initial_K=300.0)
    kw.update(over)
    return t, hs.cone_tip_response(t, np.full(n, 4.1e-4), np.full(n, 3803.0),
                                   np.full(n, 411.0), **kw)


@functools.lru_cache(maxsize=None)
def _baseline_flight():
    return _flight()


@pytest.fixture
def flight():
    return _baseline_flight()


def _recorded(prefix):
    for c in hs.ACCURACY["solid_cone_tip"]["cases"]:
        if c["case"].startswith(prefix):
            return c
    raise KeyError(prefix)


# ── geometry ────────────────────────────────────────────────────────────────
def test_equivalent_cone_has_the_stated_mass():
    d = np.radians(HALF_ANGLE)
    volume = np.pi * (0.160 * np.tan(d)) ** 2 * 0.160 / 3.0
    assert volume * 1900.0 == pytest.approx(0.68, rel=1e-12)
    assert HALF_ANGLE == pytest.approx(16.1, abs=0.05)


# ── 1. numerics ─────────────────────────────────────────────────────────────
def test_energy_is_conserved(flight):
    stored, net = flight["stored_J"], flight["net_surface_J"]
    assert stored[-1] > 0.0
    assert np.allclose(stored, net, rtol=1e-10, atol=1e-6)


def test_nothing_in_nothing_out():
    """No air and a surface that cannot radiate: the tip keeps its
    temperature."""
    t = np.linspace(0.0, 30.0, 31)
    z = np.zeros_like(t)
    r = hs.cone_tip_response(t, z, z, z + 250.0, half_angle_deg=HALF_ANGLE,
                             T_initial_K=700.0, **dict(TIP, emissivity=0.0))
    assert np.allclose(r["T_K"], 700.0, atol=1e-9)


def test_answer_does_not_depend_on_mesh_or_time_step(flight):
    base = hs.temperature_at(flight, THERMOCOUPLE_X)
    finer_mesh = hs.temperature_at(_flight(n_cells=240), THERMOCOUPLE_X)
    finer_step = hs.temperature_at(_flight(dt_max_s=0.0125), THERMOCOUPLE_X)
    assert finer_mesh == pytest.approx(base, rel=2e-3)
    assert finer_step == pytest.approx(base, rel=2e-3)
    # the tip cell itself, where the mesh is finest
    assert _flight(n_cells=240)["T_tip_K"][-1] == pytest.approx(
        flight["T_tip_K"][-1], rel=5e-3)


# ── 2. physics ──────────────────────────────────────────────────────────────
def test_conduction_cools_the_tip_below_the_radiating_wall(flight):
    t, rho, V, T_inf = _shefex_flight_arc()
    T_skin, _ = hl.radiating_wall(
        lambda T: hl.stagnation_point_flux(rho[-1], V[-1], 0.0008, T,
                                           T_inf[-1]), 0.85)
    T_tip = flight["T_tip_K"][-1]
    assert T_tip < T_skin - 500.0
    assert T_tip > hs.temperature_at(flight, THERMOCOUPLE_X)


def test_temperature_falls_with_distance_from_the_tip(flight):
    T_end = flight["T_K"][-1]
    assert np.all(np.diff(T_end) <= 1e-9)


def test_more_conductive_material_has_a_cooler_tip(flight):
    low_k = _flight(conductivity_W_mK=8.0)
    assert low_k["T_tip_K"][-1] > flight["T_tip_K"][-1]


# ── 3. accuracy against named cases ─────────────────────────────────────────
def test_shefex_flight_thermocouple(flight):
    T = hs.temperature_at(flight, THERMOCOUPLE_X)
    err = T / (848.0 + 273.15) - 1.0
    assert err == pytest.approx(_recorded("SHEFEX II flight")["temperature"],
                                abs=0.01)
    assert abs(err) < 0.06


def test_shefex_arc_jet_thermocouple():
    _, r = _arc_jet()
    T = hs.temperature_at(r, THERMOCOUPLE_X)
    err = T / (1179.0 + 273.15) - 1.0
    assert err == pytest.approx(_recorded("SHEFEX II arc-jet")["temperature"],
                                abs=0.01)
    assert abs(err) < 0.05


def test_shefex_arc_jet_tip_against_the_authors_own_code():
    """Not a measurement: the authors' two-dimensional heat-balance code gave
    1635 C at the tip.  This model is about a tenth higher."""
    t, r = _arc_jet()
    T_tip = r["T_tip_K"][int(np.argmin(np.abs(t - 60.0)))]
    assert T_tip / (1635.0 + 273.15) - 1.0 == pytest.approx(0.11, abs=0.01)


def test_conduction_direction_matters_less_than_the_target():
    """Axial (17) against transverse (8) conductivity moves the thermocouple
    by under 3%: the unreadable exponent aside, the choice between the two
    printed values does not decide the comparison."""
    a = hs.temperature_at(_flight(), THERMOCOUPLE_X)
    b = hs.temperature_at(_flight(conductivity_W_mK=8.0), THERMOCOUPLE_X)
    assert abs(b / a - 1.0) < 0.03
