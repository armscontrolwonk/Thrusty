"""
3-DOF trajectory integrator matching Forden's missileFull3D.m /
integrateTrajectory.m.

Reference frame
---------------
The state vector [x, y, z, vx, vy, vz] is expressed in ECEF
(Earth-Centered, Earth-Fixed) — a frame that rotates with Earth at
OMEGA_EARTH = 7.2921150e-5 rad/s.  Consequently:

  * Velocities (and the "ground speed" output) are *relative to Earth's
    surface*, not relative to inertial space.
  * A booster sitting on the launch pad has ECEF velocity ≈ 0, which is
    the correct initial condition for this frame — no explicit Earth-
    rotation term needs to be added to v0.
  * Earth's rotation is fully accounted for during flight through the
    Coriolis (-2 ω × v) and centrifugal (-ω × (ω × r)) pseudo-forces
    that appear in the ECEF equations of motion.

Inertial speed
--------------
For applications that require inertial (ECI-frame) speed — re-entry
heating, radar cross-section, or energy calculations — the inertial
velocity vector is obtained by adding back the Earth-rotation contribution:

    v_inertial = v_ecef + ω × r

where ω = [0, 0, OMEGA_EARTH] and r is the ECEF position vector.
At a launch latitude of 33°N this adds ≈ 390 m/s eastward at the pad
and grows to several hundred m/s of correction at apogee.  Both ground
speed and inertial speed are included in the output arrays and the Flight
Timeline milestones.

Physics included
----------------
  - Gravity (J2 spheroid — more accurate than Forden's point-mass)
  - Aerodynamic drag  (Forden Eq. 3)
  - Thrust (powered phase, user-directed gravity-turn pitch program)
  - Coriolis acceleration  (-2 ω × v)
  - Centrifugal acceleration  (-ω × (ω × r))

Guidance law — user-directed gravity turn
-----------------------------------------
The booster launches at launch_elevation_deg (default 90° vertical) and
linearly pitches from that angle to burnout_angle_deg between turn_start_s
and turn_stop_s, then holds the burnout angle for the remainder of powered
flight.  Per-stage overrides (stage_turn_start_s, stage_turn_stop_s,
stage_burnout_angle_deg) take priority over the global pitch program.

Azimuth is constant by default; optional yaw maneuvers provide dogleg
corrections.  The ENU frame is re-evaluated at each step so that "local
vertical" tracks the booster as it moves downrange.

Boost angle of attack and the q·α load (NASA SP-8099)
-----------------------------------------------------
The commanded thrust axis is not generally aligned with the velocity
vector, and the angle between them — the boost angle of attack α — sets
the combined aerodynamic + steering load q·α that sizes the structure
(NASA SP-8099, "Combining Ascent Loads", 1972).  Every run reports
α(t), q(t) and q·α(t) plus a "Max q·α" timeline milestone.  An optional
per-plan α limit (integrate_trajectory alpha_limit_deg; SP-8099
§2.1.2.2's preliminary-design envelope is 5°–10° at max q) clamps the
commanded attitude to a cone about the velocity vector while q is
significant, so a sharp dogleg slews over the time it physically needs
instead of being flown instantaneously at α ≈ 90° for free.

Validation against Forden Table 3 (maximum ranges, azimuth 40° East of N):
  Booster         Our model   Forden    Notes
  Scud-B          ~288 km     288 km    matches with correct params + guidance
  Al Hussein      ~693 km     693 km    matches with correct params + guidance
  No-dong         ~973 km     973 km    matches with correct params + guidance
  Taepodong-I    ~2349 km    2349 km    2-stage, matches with correct params
"""

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize_scalar
from collections import namedtuple as _namedtuple
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from gravity import gravity_ecef, GM, RE
from atmosphere import atmosphere, speed_of_sound
import heating
from coordinates import (
    geodetic_to_ecef, ecef_to_geodetic,
    coriolis_acceleration, centrifugal_acceleration,
    range_between, OMEGA_EARTH,
)
from booster_models import (
    BoosterParams, booster_mass, drag_force_vector, thrust_force,
    active_stage, active_stage_and_t, total_burn_time, tumbling_cylinder_beta,
    _eff_burn,
    booster_drag_vector, effective_ro, booster_separation_time,
    run_separation_mode, bind_ro_separation, compose_loadout,
    booster_area,
    wing_geometry, wedge_planform_area,
    _wedge_coeffs, _half_cone_coeffs, NEWTON_K_SLENDER,
    SHROUD_Q_FAIRING,
)


class MaxRangeCancelled(Exception):
    """Raised by maximize_range() when a cancel_event is set by the caller."""


class IntegratorStalled(Exception):
    """The solver stopped advancing and would not have finished.

    An adaptive step cannot always get past a place where the derivative
    turns sharply -- a drag build-up that kinks at Mach 1 is the usual one --
    and if the vehicle happens to sit on that point rather than pass through
    it, the step size collapses and the run never ends.  There is no error to
    report and no progress either: the solver keeps evaluating at the same
    instant for as long as it is allowed to.

    Observed on a real vehicle: 1.37 million evaluations pinned at t = 16.7 s,
    2.5 km altitude, Mach 1.001, with a healthy thrust-to-weight of 3.55.  A
    shipped vehicle (Strypi VII R) reaches the same state and takes 459 s to
    fly what its near-identical sibling flies in 0.22 s.

    Raising beats hanging: the caller gets the stall point and can act on it,
    a sweep marks that one case failed instead of freezing, and the window
    stays usable.  `integrate_trajectory(..., stall_evals=0)` disables the
    guard for anyone who would rather wait.
    """


# Consecutive evaluations at or behind the furthest time reached before the
# run is called stalled.  Every shipped vehicle that flies normally stays
# under 250 (the worst is No-dong at 248, on runs of at most 5,624
# evaluations in total); a stalled one sits there for millions.  50,000 is
# 200x the healthy worst and still trips in well under a second.
STALL_EVAL_LIMIT = 50_000


# ---------------------------------------------------------------------------
# High-altitude atmosphere for orbital lifetime (NRLMSISE-00 tabulation,
# F10.7=150 solar flux, Ap=4 low activity — conservative decay estimate).
# Density in kg/m³ vs altitude in km.
# ---------------------------------------------------------------------------
_HIGH_ATM_KM  = np.array([200, 250, 300, 350, 400, 450, 500,
                           600, 700, 800, 900, 1000])
_HIGH_ATM_RHO = np.array([2.53e-10, 6.07e-11, 1.92e-11, 7.06e-12, 2.80e-12,
                           1.18e-12, 5.21e-13, 1.14e-13, 3.07e-14, 1.14e-14,
                           5.24e-15, 2.95e-15])

# Tracy & Wright 2020 (sgs28tracy.pdf) boost-glide model.
#
# The pull-up is treated analytically following Acton 2015 (Eq. 11):
# at the moment the vehicle pierces the upper atmosphere on descent,
# the state is reset to equilibrium-glide initial conditions:
#     v_4  = v_3 · exp(−(D/L)·θ_2)        (Acton Eq. 11)
#     γ    = 0   (velocity rotated to local horizontal)
#     h    = h_eq(v_4) from the equilibrium-glide relation (Tracy Eq. 7)
# where v_3, θ_2 are the speed and (positive) descent angle at piercing.
#
# After this one-shot reset, the glide and terminal phases are simulated
# by direct integration of the existing equations of motion with constant
# L/D and a single β.  No Phase-3 / β_S drag, no equilibrium-lift cap —
# the vehicle's natural EOM keeps it near equilibrium because it starts
# AT equilibrium (Tracy Eq. 7).  Mild phugoid oscillation is physical.
ACTON_PIERCE_ALT_M    = 100_000.0
# Acton's isothermal-atmosphere fit for 30 < h < 100 km (p. 197):
ACTON_SCALE_HEIGHT_M  = 6970.0
ACTON_SEA_LEVEL_RHO   = 1.46


def _atm_density_high(alt_km: float) -> float:
    """
    Exponential interpolation of the tabulated high-altitude density.
    Returns kg/m³.  Clamped to table limits.
    """
    alt_km = float(np.clip(alt_km, _HIGH_ATM_KM[0], _HIGH_ATM_KM[-1]))
    log_rho = float(np.interp(alt_km, _HIGH_ATM_KM, np.log(_HIGH_ATM_RHO)))
    return float(np.exp(log_rho))


def orbital_elements_from_state(pos_ecef: np.ndarray,
                                vel_ecef: np.ndarray) -> dict:
    """
    Compute classical orbital elements from an ECEF state vector.

    The ECI velocity is recovered via v_eci = v_ecef + ω × r.
    Because ECEF and ECI share the z-axis (Earth's rotation axis) the
    inclination calculation does not need Greenwich Sidereal Time.

    Returns a dict with keys:
        semi_major_km   : semi-major axis (km)
        eccentricity    : dimensionless
        inclination_deg : inclination to equatorial plane (°)
        perigee_km      : altitude of perigee above WGS-84 equatorial radius (km)
        apogee_km       : altitude of apogee (km)
        period_min      : orbital period (minutes)
        energy_mj_kg    : specific orbital energy (MJ/kg, negative = bound)
    """
    omega_vec = np.array([0.0, 0.0, OMEGA_EARTH])
    vel_eci   = vel_ecef + np.cross(omega_vec, pos_ecef)

    r  = np.linalg.norm(pos_ecef)
    v  = np.linalg.norm(vel_eci)
    eps = 0.5 * v**2 - GM / r              # specific orbital energy (J/kg)
    a   = -GM / (2.0 * eps)                # semi-major axis (m); eps<0 → bound

    h_vec = np.cross(pos_ecef, vel_eci)    # specific angular momentum
    h     = np.linalg.norm(h_vec)

    # Eccentricity
    e = float(np.sqrt(max(0.0, 1.0 - h**2 / (GM * a))))

    # Inclination  (h_z / |h| is frame-independent: z is shared by ECEF/ECI)
    inc_deg = float(np.degrees(np.arccos(np.clip(h_vec[2] / h, -1.0, 1.0))))

    # Perigee / apogee altitudes above mean equatorial radius
    r_perigee = a * (1.0 - e) - RE        # m above equatorial surface
    r_apogee  = a * (1.0 + e) - RE

    # Orbital period
    period_s = 2.0 * np.pi * np.sqrt(a**3 / GM)

    return {
        'semi_major_km':   a / 1000.0,
        'eccentricity':    e,
        'inclination_deg': inc_deg,
        'perigee_km':      r_perigee / 1000.0,
        'apogee_km':       r_apogee  / 1000.0,
        'period_min':      period_s  / 60.0,
        'energy_mj_kg':    eps / 1e6,
    }


def orbital_lifetime_estimate(perigee_km: float, apogee_km: float,
                              beta_kg_m2: float) -> float:
    """
    Estimate orbital decay lifetime using the King-Hele formula.

    Integrates dT ≈ β / (ρ(h) · √(GM · (RE+h))) dh from h=apogee down to
    h=80 km (effective re-entry altitude), treating each 1-km shell as
    independently circular (valid for low-eccentricity orbits; gives the
    right order-of-magnitude for higher eccentricities).

    Parameters
    ----------
    perigee_km  : perigee altitude (km above equatorial radius)
    apogee_km   : apogee altitude (km)
    beta_kg_m2  : ballistic coefficient β = m/(Cd·A) in kg/m²

    Returns
    -------
    lifetime_years : estimated orbital lifetime in years
                     (returns np.inf if perigee is above 1000 km)
    """
    REENTRY_KM = 80.0
    if perigee_km > 1000.0:
        return float('inf')
    h_lo = max(perigee_km, REENTRY_KM)
    h_hi = min(apogee_km, _HIGH_ATM_KM[-1])
    if h_lo >= h_hi:
        return 0.0   # already below re-entry altitude

    hs   = np.arange(h_lo, h_hi + 1.0, 1.0)  # 1-km steps
    rhot = np.array([_atm_density_high(h) for h in hs])
    v_circ = np.sqrt(GM / (RE + hs * 1000.0)) # circular orbit speed at each h
    # dt/dh = β / (ρ · v_circ)  — time to decay through 1 m of altitude
    # integrate over the full range (h in km, convert to m for denominator)
    dh_m  = 1000.0   # 1 km in metres
    dt_s  = np.sum(beta_kg_m2 / (rhot * v_circ)) * dh_m
    SECONDS_PER_YEAR = 365.25 * 86400.0
    return dt_s / SECONDS_PER_YEAR


# ---------------------------------------------------------------------------
# Flight-event helpers
# ---------------------------------------------------------------------------

def _stage_event_times(params: BoosterParams):
    """
    Walk the stage linked list and return a list of
    (event_label, mission_elapsed_time_s) pairs for every stage
    ignition and burnout.

    Stage 1 fires at t=0 ("Ignition").  Each subsequent stage emits both
    a burnout for the previous stage and an ignition for itself.  When
    coast_time_s == 0 both events share the same timestamp; when there is
    a coast gap they are separated by that gap.
    """
    delay = getattr(params, 'booster_core_delay_s', 0.0)
    events = []

    # When strap-ons ignite before the core, T=0 is liftoff (strap-on ignition)
    # and core/stage-1 ignites later.
    if delay > 0:
        events.append(("Launch", 0.0))

    t = delay
    node = params
    stage = 1
    while node is not None:
        if stage == 1:
            label = "Core ignition" if delay > 0 else "Ignition"
        else:
            label = f"Stage {stage} ignition"
        events.append((label, t))
        t_burnout = t + node.burn_time_s
        events.append((f"Stage {stage} burnout", t_burnout))
        if node.stage2 is not None:
            t = t_burnout + node.coast_time_s
        node = node.stage2
        stage += 1

    # Insert booster separation in chronological order
    if params.n_boosters > 0 and params.booster_burn_time_s > 0:
        t_sep = booster_separation_time(params)
        for i, (_, t_ev) in enumerate(events):
            if t_ev > t_sep:
                events.insert(i, ("Booster separation", t_sep))
                break
        else:
            events.append(("Booster separation", t_sep))

    return events


def _interp_milestone(t_event, t_arr, alt_arr, range_arr, speed_arr,
                      inertial_speed_arr, accel_arr, mass_arr):
    """
    Interpolate all channel arrays at t_event.  Clamps to the array bounds
    so events that fall after cutoff (engine off) still return valid values.

    speed_arr          — ECEF-frame (ground) speed, m/s
    inertial_speed_arr — ECI-frame (inertial) speed, m/s;
                         = ||v_ecef + ω × r||, used for re-entry heating etc.
    """
    t_event = float(np.clip(t_event, t_arr[0], t_arr[-1]))
    return {
        't_s':              t_event,
        'alt_km':           float(np.interp(t_event, t_arr, alt_arr  / 1000.0)),
        'range_km':         float(np.interp(t_event, t_arr, range_arr / 1000.0)),
        'speed_kms':        float(np.interp(t_event, t_arr, speed_arr / 1000.0)),
        'inertial_speed_kms': float(np.interp(t_event, t_arr,
                                              inertial_speed_arr / 1000.0)),
        'accel_ms2':        float(np.interp(t_event, t_arr, accel_arr)),
        'mass_t':           float(np.interp(t_event, t_arr, mass_arr  / 1000.0)),
    }


# ---------------------------------------------------------------------------
# Guidance helpers
# ---------------------------------------------------------------------------

def _cross3(a, b):
    """Cross product of two length-3 vectors, returned as a length-3 ndarray.

    numpy's generic np.cross spends most of its time dispatching on shape/axis;
    for the fixed 3-vectors in the per-step EOM/guidance hot path this explicit
    form is several times faster and bit-for-bit identical.
    """
    return np.array((a[1] * b[2] - a[2] * b[1],
                     a[2] * b[0] - a[0] * b[2],
                     a[0] * b[1] - a[1] * b[0]))


def _enu_frame(lat_rad: float, lon_rad: float):
    """Return (e_east, e_north, e_up) unit vectors in ECEF at given geodetic pos."""
    sin_lat, cos_lat = np.sin(lat_rad), np.cos(lat_rad)
    sin_lon, cos_lon = np.sin(lon_rad), np.cos(lon_rad)
    e_east  = np.array([-sin_lon,           cos_lon,           0.0    ])
    e_north = np.array([-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat])
    e_up    = np.array([ cos_lat * cos_lon,  cos_lat * sin_lon, sin_lat])
    return e_east, e_north, e_up


def _prev_burnout_angle(root_params, current_stage) -> float:
    """Return the burnout angle (°) of the stage immediately preceding
    current_stage in the chain, or launch_elevation_deg if current_stage is
    the first stage (so the pitch ramp starts from the launch angle).
    """
    if current_stage is root_params:
        return float(root_params.launch_elevation_deg)
    s = root_params
    while s.stage2 is not None and s.stage2 is not current_stage:
        s = s.stage2
    # When a stage has no explicit burnout angle (no per-stage pitch override),
    # fall back to launch_elevation_deg so the pitch display is consistent with
    # the ODE, which uses root_params.launch_elevation_deg as start_angle_deg.
    return (float(s.stage_burnout_angle_deg)
            if s.stage_burnout_angle_deg is not None
            else float(root_params.launch_elevation_deg))


def _gravity_turn_thrust_dir(lat_rad, lon_rad, azimuth_rad,
                             burnout_angle_deg, turn_start_s, turn_stop_s, t,
                             start_angle_deg=90.0):
    """
    Linear pitch program to Wheelon-optimal burnout angle (Levanger/Wright).

    Phase 1 (0 – turn_start_s): hold start_angle_deg (90° for stage 1,
        previous stage's burnout angle for later stages).
    Phase 2 (turn_start_s – turn_stop_s): constant pitch rate from
        start_angle_deg down to burnout_angle_deg.
    Phase 3 (> turn_stop_s): hold burnout_angle_deg.

    burnout_angle_deg : desired elevation at end of pitch program (°).
    turn_start_s      : time to begin pitching (s); default 5.0.
    turn_stop_s       : time to reach burnout_angle_deg and hold (s);
                        default = total powered-flight duration.
    """
    if t <= turn_start_s:
        el_deg = start_angle_deg
    elif t >= turn_stop_s:
        el_deg = burnout_angle_deg
    else:
        pitch_duration = max(turn_stop_s - turn_start_s, 1.0)
        frac = (t - turn_start_s) / pitch_duration
        el_deg = start_angle_deg - frac * (start_angle_deg - burnout_angle_deg)

    el_rad = np.radians(el_deg)
    e_east, e_north, e_up = _enu_frame(lat_rad, lon_rad)
    thrust = (np.cos(el_rad) * np.sin(azimuth_rad) * e_east +
              np.cos(el_rad) * np.cos(azimuth_rad) * e_north +
              np.sin(el_rad) * e_up)
    norm = np.linalg.norm(thrust)
    return thrust / norm if norm > 1e-12 else e_up


def _orbital_insertion_thrust_dir(lat_rad, lon_rad, azimuth_rad,
                                   boost_angle_deg, turn_start_s, turn_stop_s,
                                   t_final_ignition, t):
    """
    Two-phase pitch program for orbital insertion.

    Phase 1 — all stages before the final (t < t_final_ignition):
        Pitch from 90° (vertical) to boost_angle_deg over the window
        [turn_start_s, turn_stop_s], then hold boost_angle_deg.
        turn_stop_s is normally set to just before final-stage ignition so
        the boost stages complete their pitch-over before handoff.

    Phase 2 — final stage (t >= t_final_ignition):
        Hold 0° (horizontal).  The final stage burns near apogee of the boost
        arc, adding horizontal velocity until the energy-based cutoff fires.
    """
    if t >= t_final_ignition:
        el_deg = 0.0          # horizontal burn for final stage
    elif t <= turn_start_s:
        el_deg = 90.0
    elif t >= turn_stop_s:
        el_deg = boost_angle_deg
    else:
        frac   = (t - turn_start_s) / max(turn_stop_s - turn_start_s, 1.0)
        el_deg = 90.0 - frac * (90.0 - boost_angle_deg)

    el_rad = np.radians(el_deg)
    e_east, e_north, e_up = _enu_frame(lat_rad, lon_rad)
    thrust = (np.cos(el_rad) * np.sin(azimuth_rad) * e_east +
              np.cos(el_rad) * np.cos(azimuth_rad) * e_north +
              np.sin(el_rad) * e_up)
    norm = np.linalg.norm(thrust)
    return thrust / norm if norm > 1e-12 else e_up


# ---------------------------------------------------------------------------
# True gravity turn (Wright 2020 convention)
# ---------------------------------------------------------------------------
#
# Thrust is aligned with the velocity vector and offset by an angle-of-attack
# η ("eta") in the local trajectory plane.  η > 0 tilts the thrust BELOW the
# velocity vector — this is Wright's convention (positive etad lowers γ).
#
# Each stage may schedule a kick window [stage_turn_start_s, stage_turn_stop_s]
# during which η = stage_burnout_angle_deg (re-using the existing per-stage
# field as the "η during kick window" value).  Outside any window η = 0, so
# thrust is exactly along velocity and gravity does the trajectory turning —
# the textbook gravity-turn behaviour.
#
# Initial-kick handling: while ground speed is below 50 m/s OR mission time
# is below 4 s (Wright's lines 1173, 1213), we hold thrust along local-vertical
# instead.  This avoids the v_hat singularity at launch.
#
# Reference: David Wright, "Missile_trajectory_v5_2.py" (2020), eta_calc().

_TGT_KICK_HOLD_T_S = 4.0
_TGT_KICK_HOLD_V_MS = 50.0


def _tgt_eta_now(active_stage, t):
    """Return η (deg) for the active stage at mission-elapsed time t.

    Re-uses the per-stage fields stage_turn_start_s, stage_turn_stop_s,
    stage_burnout_angle_deg as (kick_start, kick_stop, η_deg).  Outside the
    window η = 0.  Stages without these overrides default to η = 0 (pure
    gravity turn for that burn).
    """
    if active_stage is None:
        return 0.0
    t_s = active_stage.stage_turn_start_s
    t_e = active_stage.stage_turn_stop_s
    eta = active_stage.stage_burnout_angle_deg
    if t_s is None or t_e is None or eta is None:
        return 0.0
    if t_s < t <= t_e:
        return float(eta)
    return 0.0


def _true_gravity_turn_thrust_dir(pos, vel, lat_rad, lon_rad,
                                  azimuth_rad, t, active_stage):
    """Thrust direction for the true (velocity-aligned) gravity-turn mode.

    Returns a unit vector in ECEF.  During the initial-kick window (t < 4s
    or |v| < 50 m/s) thrust is held along local-vertical so the rocket
    lifts off without a v_hat singularity.

    For non-zero η, the kick direction n_perp is the unit vector in the
    trajectory plane perpendicular to v_hat, pointing "above velocity"
    (toward local-up).  Sign convention: η > 0 → thrust is BELOW velocity,
    which lowers γ (matches Wright's etad).

    For a near-vertical vehicle, r_hat ‖ v_hat and the local-up component
    perpendicular to v_hat is degenerate.  Fall back to the launch-azimuth-
    defined trajectory plane: n_perp = ((v̂ × e_az) × v̂) gives the
    "above velocity in the (v̂, e_az) plane" direction, well-defined for
    any v_hat that isn't parallel to e_az (which only happens for a
    purely-horizontal vehicle along the launch heading — that case keeps
    using the r_hat-based formula since v_hat is far from r_hat).
    """
    speed = float(np.linalg.norm(vel))
    if t < _TGT_KICK_HOLD_T_S or speed < _TGT_KICK_HOLD_V_MS:
        # Vertical kick at the configured launch azimuth.
        _, _, e_up = _enu_frame(lat_rad, lon_rad)
        return e_up

    v_hat = vel / speed
    r_mag = float(np.linalg.norm(pos))
    r_hat = pos / r_mag if r_mag > 1.0 else np.array([0.0, 0.0, 1.0])

    # Primary n_perp from local-up minus its v_hat-parallel component.
    n_perp = r_hat - np.dot(r_hat, v_hat) * v_hat
    n_mag  = float(np.linalg.norm(n_perp))
    if n_mag < 0.1:
        # Near-vertical vehicle (r_hat ≈ v_hat).  Fall back to the launch
        # azimuth to define the trajectory plane.
        e_east, e_north, _ = _enu_frame(lat_rad, lon_rad)
        e_az = (np.sin(azimuth_rad) * e_east
                + np.cos(azimuth_rad) * e_north)
        n_side = _cross3(v_hat, e_az)
        ns_mag = float(np.linalg.norm(n_side))
        if ns_mag > 1e-6:
            n_side = n_side / ns_mag
            # cross(v_hat, n_side) gives the "below velocity, toward
            # +e_az" direction in the trajectory plane — i.e., the
            # direction we want to subtract from v_hat for η > 0.
            n_perp = _cross3(v_hat, n_side)
        else:
            # v_hat ‖ e_az (purely horizontal along launch heading) —
            # use local-up directly.
            _, _, e_up = _enu_frame(lat_rad, lon_rad)
            n_perp = e_up - np.dot(e_up, v_hat) * v_hat
        n_mag = float(np.linalg.norm(n_perp))

    if n_mag > 1e-9:
        n_perp = n_perp / n_mag
    else:
        n_perp = np.zeros(3)

    eta_rad = np.radians(_tgt_eta_now(active_stage, t))
    # η > 0 tilts thrust BELOW velocity (toward −n_perp = "below velocity"),
    # so the perpendicular thrust component lowers γ.  Wright convention.
    return np.cos(eta_rad) * v_hat - np.sin(eta_rad) * n_perp


# ---------------------------------------------------------------------------
# Yaw (dogleg) program
# ---------------------------------------------------------------------------

def _yaw_program(t, launch_az_rad, active_stage, yaw_maneuvers):
    """
    Multi-segment azimuth schedule for dogleg maneuvers (mission-elapsed time).

    yaw_maneuvers is a list of (start_s, stop_s, final_az_deg) tuples in
    chronological order.  Each segment linearly interpolates from the previous
    segment's ending azimuth (or launch_az for the first) to its own final
    azimuth.  Per-stage override fields on active_stage take priority.
    Returns commanded azimuth in radians at time t.
    """
    if (active_stage is not None
            and active_stage.stage_yaw_final_az_deg is not None):
        maneuvers = [(active_stage.stage_yaw_start_s,
                      active_stage.stage_yaw_stop_s,
                      active_stage.stage_yaw_final_az_deg)]
    else:
        maneuvers = yaw_maneuvers or []

    current_az = launch_az_rad
    for (yaw_start, yaw_stop, yaw_final_deg) in maneuvers:
        if yaw_final_deg is None:
            continue
        if yaw_start is None:
            yaw_start = 0.0
        if yaw_stop is None:
            yaw_stop = yaw_start
        yaw_final_rad = np.radians(yaw_final_deg)
        if t < yaw_start:
            return current_az
        if t >= yaw_stop:
            current_az = yaw_final_rad
            continue
        frac = (t - yaw_start) / max(yaw_stop - yaw_start, 1.0)
        return current_az + frac * (yaw_final_rad - current_az)
    return current_az


# ---------------------------------------------------------------------------
# Slender-body drag polar (Munk 1924, Ashley & Landahl §6-7, §9-8)
# ---------------------------------------------------------------------------

# The polar as a named record — richer than the old (C_D0, k, A_ref) tuple so
# the wing-decoupled ceiling (C_L_max) and pull-efficiency (e_pull) travel with
# it.  All call sites take the record and read attributes.
_Polar = _namedtuple('_Polar', 'C_D0 k A_ref C_L_star C_L_max e_pull C_L0')
# C_L0 (Phase 3, lifting forms only): the camber offset — the C_L at minimum
# drag, in POLAR coefficients (converted from the estimator's sweep-native
# value).  Default 0 = the symmetric polar, byte-identical for every existing
# vehicle.
_Polar.__new__.__defaults__ = (0.0,)

# Bare-body maximum usable C_L: Munk C_L = 2α evaluated at |α| ≲ 25° — the
# un-physical hardcoded ceiling the wing decoupling replaces when wings exist.
_C_L_MAX_BODY = 2.0 * np.radians(25.0)          # ≈ 0.873

# Wing-decoupling screening constants (METHODS §12.0.2).  Labeled inferences
# with ~±30% bands, never fit to a flight.  The wing acts on ONE physical
# quantity — the width of the drag bucket (induced-drag efficiency in a hard
# pull), NOT the C_L ceiling: |α| ≲ 25° is a max-AoA limit for a body OR a
# winged vehicle alike, and raising it just lets the pull rail at ruinous
# induced drag.  A high-AR wing carries lift more efficiently off-design, so
# it flattens the L/D curve away from the cruise point.
WING_PULL_GAIN  = 1.0    # scale of the bucket-broadening per unit wing-area
                         # ratio (S_w/A_ref) at high AR.
WING_PULL_AR0   = 4.0    # aspect-ratio half-saturation: AR/(AR+4) → 0.5 at
                         # AR=4, → 1 as AR → ∞ (tip losses shrink the benefit
                         # for a stubby wing).
WING_DEFAULT_AR = 2.0    # FAIL SAFE: wing area given but no span/AR → assume a
                         # stubby, low-efficiency wing.  Credits a modest,
                         # conservative benefit from area alone; a declared AR
                         # overrides.  Never overclaims efficiency span can't
                         # support.
_WING_E_PULL_CAP = 3.0   # bound the induced-drag softening.


def _polar_cd(C_L: float, pol: '_Polar') -> float:
    """Drag coefficient at lift C_L on the (possibly wing-decoupled) polar.

    Cruise side (C_L ≤ C_L*): the OFFSET polar
        C_D = C_D0 + k·[(C_L − C_L0)² − C_L0²]
    (Lobanovskii's asymmetric-body trinomial; Fetterman Fig. 6b measured).
    Anchored so C_D(0) = C_D0 EXACTLY — β keeps its zero-lift meaning — and
    minimum drag sits at C_L0, nonzero for a cambered body.  C_L0 = 0 (every
    body of revolution, and any lifting form without an estimator trim row)
    reduces to the symmetric C_D0 + k·C_L², byte-identical.  Commanded lift
    is taken in the camber-favored direction (|C_L|), the screening reading
    of a trimmed glide.

    Pull side (C_L > C_L*): the induced-drag rise above the bucket is softened
    by e_pull (≥ 1, from aspect ratio) — the same offset parabola about C_L0
    with k/e_pull curvature.  e_pull = 1 reproduces the single-k polar
    exactly, so this is byte-identical off the wing path.
    """
    cl = min(abs(float(C_L)), pol.C_L_max)
    cl0 = getattr(pol, 'C_L0', 0.0)

    def _base(c):
        return pol.C_D0 + pol.k * ((c - cl0) * (c - cl0) - cl0 * cl0)

    if cl <= pol.C_L_star or pol.e_pull <= 1.0:
        return _base(cl)
    return _base(pol.C_L_star) + (pol.k / pol.e_pull) * (
        (cl - cl0) * (cl - cl0)
        - (pol.C_L_star - cl0) * (pol.C_L_star - cl0))


def _aero_polar(ro, ld_override: float = None) -> '_Polar':
    """The drag polar as a `_Polar` record (Munk 1924; Ashley & Landahl §6-7).

    Linear slender-body theory gives C_L = 2α referenced to A_ref = π·d²/4;
    the drag-due-to-lift is C_Di = k·C_L², so C_D = C_D0 + k·C_L².  C_D0 and k
    are back-solved from the user's β and (L/D)_max:

        A_ref  = π·d²/4
        C_D0   = m / (β · A_ref)            (β at zero lift)
        k      = 1 / (4·C_D0·(L/D)_max²)    (polar yields (L/D)_max at α*)
        C_L*   = √(C_D0/k)                  (the max-L/D trim lift)

    WING DECOUPLING (METHODS §12.0.2).  `wing_area_m2 > 0` broadens the drag
    bucket — the ONE thing the 2-input (β, L/D) model can't express.  The
    cruise bucket (C_L ≤ C_L*) is UNCHANGED, so glider_LD keeps its meaning and
    every non-winged vehicle is byte-identical; only the induced-drag rise in a
    HARD PULL (C_L > C_L*) is softened, via _polar_cd:

        λ        = wing_area / A_ref                        (planform ratio)
        AR       = wing_aspect_ratio, or WING_DEFAULT_AR if unset (fail safe)
        e_pull   = 1 + WING_PULL_GAIN · λ · AR/(AR + AR0)

    A high-AR wing carries lift more efficiently off the cruise point, so it
    flattens the L/D curve there — exactly the pull tax the SWERVE campaign
    exposed (the pull ran at L/D ≈ 0.94, half the nominal).  The C_L ceiling is
    NOT raised: |α| ≲ 25° is a max-AoA limit for a body or a winged vehicle
    alike, and raising it merely lets the pull rail at ruinous induced drag
    (verified — it deepens the trough).  Constants are screening inferences
    with ~±30% bands, never fit to a flight.  Returns a `_Polar`; falls back to
    generic-HGV defaults if β/mass are missing.
    """
    d = float(getattr(ro, 'diameter_m', 0.0) or 0.0)
    if d <= 0.0:
        d = 0.5                                 # generic HGV fallback
    A_ref = 0.25 * np.pi * d * d
    m   = float(getattr(ro, 'mass_kg', 0.0) or 0.0)
    bet = float(getattr(ro, 'beta_kg_m2', 0.0) or 0.0)
    LD  = float(ld_override if ld_override is not None
                else (getattr(ro, 'glider_LD', 0.0) or 0.0))
    if m > 0.0 and bet > 0.0:
        C_D0 = m / (bet * A_ref)               # β at zero lift
    else:
        C_D0 = 0.08                             # generic HGV C_D0

    form = str(getattr(ro, 'body_form', '') or 'axisymmetric')
    L_body = float(getattr(ro, 'length_m', 0.0) or 0.0)
    b_span = float(getattr(ro, 'body_span_m', 0.0) or 0.0)

    # ---- camber offset (Phase 3, lifting forms with an estimator trim row) --
    # trim_CL0 is stored SWEEP-native (the estimator's A_ref: planform for a
    # wedge, base area otherwise); lift force is invariant, so the polar's
    # value is scaled by A_sweep/A_ref.  A wedge without its span cannot state
    # A_sweep — offset off, matching the schematic's span-not-modeled flag.
    cl0 = 0.0
    trim_cl0 = float(getattr(ro, 'trim_CL0', 0.0) or 0.0)
    if trim_cl0 != 0.0 and form in ('wedge', 'half_cone'):
        if form == 'wedge':
            a_sweep = (wedge_planform_area(L_body, b_span)
                       if (L_body > 0.0 and b_span > 0.0) else 0.0)
        else:
            a_sweep = A_ref                     # half-cone: full-circle base
        if a_sweep > 0.0:
            cl0 = trim_cl0 * a_sweep / A_ref

    # k back-solved so the polar's (L/D)max is EXACTLY glider_LD on the
    # OFFSET parabola (C_L* = √(C_D0/k) is unchanged by the offset; the
    # optimum satisfies u = √(C_D0·k):  2·LD·C_L0·u² − 2·LD·C_D0·u + C_D0 = 0,
    # minus root → the symmetric 1/(4·C_D0·LD²) as C_L0 → 0).  A C_L0 too
    # large for the discriminant (C_L0 > LD·C_D0/2) is inconsistent with the
    # stated L/D — fall back to the symmetric polar rather than invent.
    if LD > 0.0:
        disc = LD * LD * C_D0 * C_D0 - 2.0 * LD * cl0 * C_D0
        if cl0 != 0.0 and disc > 0.0:
            u = (LD * C_D0 - float(np.sqrt(disc))) / (2.0 * LD * cl0)
            k = u * u / C_D0
        else:
            cl0 = 0.0
            k = 1.0 / (4.0 * C_D0 * LD * LD)
    else:
        cl0 = 0.0
        k = 0.5
    k = max(min(k, 5.0), 0.05)
    C_D0 = max(min(C_D0, 1.0), 0.005)          # clamp AFTER the back-solve,
    C_L_star = float(np.sqrt(C_D0 / k))        # matching the original order

    # ---- wing decoupling (default off: byte-identical to the old polar) -----
    # Wings broaden the pull-side bucket only (e_pull); the ceiling stays the
    # universal max-AoA limit.  S and AR come from wing_geometry(): ALWAYS
    # derived from the planform when one is stored (the planform is the
    # image-measurable primary data), else the direct S/AR entries.
    S_w, _AR_eff, _w_src = wing_geometry(ro)
    e_pull = 1.0
    if S_w > 0.0 and A_ref > 0.0:
        lam = S_w / A_ref
        AR = _AR_eff or WING_DEFAULT_AR
        e_pull = 1.0 + WING_PULL_GAIN * lam * AR / (AR + WING_PULL_AR0)
        e_pull = min(e_pull, _WING_E_PULL_CAP)
    # ---- ceiling (Phase 3): shape-derived for lifting forms ------------------
    # The universal 0.873 is Munk's slender-BODY-OF-REVOLUTION C_L = 2α at the
    # 25° AoA cap — badly conservative for a flat-bottomed wedge (several
    # times the usable lift) and honest in neither direction for a half-cone.
    # For lifting forms with sufficient stored geometry, evaluate the Newtonian
    # pressure C_L at the SAME 25° cap (Cf/base drag do not move C_L) and
    # convert to polar coefficients (× A_sweep/A_ref).  Missing geometry
    # (a wedge without its span) keeps the body ceiling — flagged elsewhere,
    # never invented.  Axisymmetric vehicles are byte-identical.
    C_L_max = _C_L_MAX_BODY
    _cap_deg = 25.0
    if form == 'wedge' and L_body > 0.0 and b_span > 0.0:
        s_plan = wedge_planform_area(L_body, b_span)
        c = _wedge_coeffs(L_body, d, b_span, _cap_deg, NEWTON_K_SLENDER,
                          0.0, False, 10.0, s_plan)
        C_L_max = max(c['C_L'] * s_plan / A_ref, 1e-6)
    elif form == 'half_cone' and L_body > 0.0 and d > 0.0:
        th_deg = float(np.degrees(np.arctan2(d / 2.0, L_body)))
        # Wing composite: the same exposed planform the estimator uses.
        wr = 0.0
        c_r = float(getattr(ro, 'wing_root_chord_m', 0.0) or 0.0)
        s_e = float(getattr(ro, 'wing_span_exposed_m', 0.0) or 0.0)
        if c_r > 0.0 and s_e > 0.0:
            sw = np.radians(float(getattr(ro, 'wing_sweep_deg', 0.0) or 0.0))
            c_t = max(0.0, c_r - s_e * float(np.tan(sw)))
            wr = (c_r + c_t) * s_e / A_ref
        c = _half_cone_coeffs(th_deg, _cap_deg, NEWTON_K_SLENDER,
                              0.0, False, 10.0, wing_ratio=wr)
        C_L_max = max(c['C_L'], 1e-6)          # base-referenced = A_ref
    # Floored above the cruise trim so a pull always has margin.
    C_L_max = max(C_L_max, 1.05 * C_L_star)
    return _Polar(C_D0, k, A_ref, C_L_star, C_L_max, e_pull, cl0)


# ---------------------------------------------------------------------------
# Commanded thrust direction — the single source of truth for attitude
# ---------------------------------------------------------------------------

# Angle-of-attack envelope (NASA SP-8099, "Combining Ascent Loads", 1972).
# A booster in atmosphere cannot fly at arbitrary α: the q·α (dynamic pressure
# × angle of attack) load is the structure-sizing combined-load condition, and
# SP-8099 §2.1.2.2 gives 5°–10° α at max-q as the standard preliminary-design
# envelope (the "hard-over engine" case bounds it).  Its p. 13 dogleg example
# — a sharp range-safety dogleg whose large α + steering load became the
# design combined-load condition — is exactly the maneuver Thrusty's yaw
# program commands, so the guidance must not fly an α the airframe could not.
#
# The α limit is enforced as a CONSTANT-q·α (constant-load) envelope, not a
#   fixed angle gated on an absolute pressure.  The user's alpha_limit_deg is
#   read as SP-8099's convention — the maximum α "at the maximum dynamic
#   pressure condition" — so the enforced quantity is the LOAD:
#       q(t)·α(t) ≤ q_max-q · alpha_limit_deg
#   Rearranged, the instantaneous allowance is α_allow(t) = alpha_limit_deg ·
#   q_max-q / q(t): exactly the limit at max-q, proportionally more where q is
#   lower, and unbounded as q → 0.  So the envelope self-deactivates in vacuum
#   with NO arbitrary pressure threshold (this replaces the old hand-picked
#   100 Pa gate).  q_max-q is the ascent max-q, tracked as a running maximum on
#   params._maxq_pa during integration (max-q is reached early, before any
#   dogleg, so the reference is settled by the time a maneuver needs clamping).
# _ALPHA_WARN_DEG / _ALPHA_WARN_Q_PA: reporting-only thresholds for the "no
#   limit set" timeline warning — NOT part of the enforced physics.  |α| ≲ 25°
#   is the Munk-model validity edge used throughout this codebase.
_ALPHA_WARN_DEG  = 25.0
_ALPHA_WARN_Q_PA = 1000.0     # only warn where q makes the α load meaningful


def _alpha_limited_dir(thrust_dir, vel, alpha_limit_deg, alt_m, maxq_ref_pa):
    """Clamp a commanded thrust direction to the constant-q·α load envelope.

    Returns the unit vector within a cone about the velocity direction (a slerp
    from v̂ toward the command, stopped at the cone) whose half-angle is the
    instantaneous α allowance α_allow = alpha_limit_deg · q_max-q / q — i.e. the
    angle that holds the load q·α at the ceiling set by alpha_limit_deg at
    max-q.  With the clamp active the vehicle turns only as fast as the bounded
    lateral (thrust-component) force rotates the velocity vector, so a
    commanded instantaneous dogleg stretches over the time it physically needs
    (SP-8099 p. 13) — and the allowance grows smoothly as q falls, vanishing in
    vacuum, with no arbitrary pressure gate.

    maxq_ref_pa is the ascent max-q reference (running max on params._maxq_pa).
    Falls through unclamped below the launch kick-hold speed (v̂ undefined at
    liftoff) and until a max-q reference / nonzero q exists.
    """
    speed = float(np.linalg.norm(vel))
    if speed < _TGT_KICK_HOLD_V_MS:
        return thrust_dir
    _, _, rho, _ = atmosphere(max(float(alt_m), 0.0))
    q = 0.5 * rho * speed * speed
    if q <= 0.0 or maxq_ref_pa <= 0.0:
        return thrust_dir
    # Constant-load allowance: the α that keeps q·α at the max-q ceiling.
    alpha_allow_deg = alpha_limit_deg * (maxq_ref_pa / q)
    v_hat = vel / speed
    cos_a = float(np.clip(np.dot(thrust_dir, v_hat), -1.0, 1.0))
    ang   = float(np.arccos(cos_a))
    lim   = np.radians(alpha_allow_deg)
    if ang <= lim:
        return thrust_dir
    sin_ang = float(np.sin(ang))
    if sin_ang < 1e-6:
        # Command anti-parallel to velocity — no unique great-circle path;
        # leave the command unclamped rather than invent a turn plane.
        return thrust_dir
    d = (np.sin(ang - lim) * v_hat + np.sin(lim) * thrust_dir) / sin_ang
    n = float(np.linalg.norm(d))
    return d / n if n > 1e-12 else thrust_dir


# Slender-body potential normal-force slope (per rad), referenced to the
# frontal/base area.  Munk/slender-body theory gives 2·(A_base/A_ref); for a
# pointed body with A_base = A_ref this is 2.0 and is nose-dominated (the
# cylindrical afterbody adds none in potential flow — only viscous cross-flow).
# The same value the glider-L/D build-up uses for its body term (glider_ld.py).
_BOOST_C_NA_POT = 2.0
_BOOST_CROSSFLOW_ETA = 1.0    # viscous cross-flow proportionality (Jorgensen p.26)


def _attached_planform_area(astage):
    """Side-projected planform area (m²) of the currently-flying stack — the
    active (burning) stage and every stage still stacked above it — for the
    Allen-Perkins viscous cross-flow term.  Lower stages have already
    separated; upper stages are reached by walking the stage2 chain from the
    active stage.  A stage with no explicit length falls back to a 5-caliber
    body, matching the glider-L/D build-up's convention."""
    A_p = 0.0
    s = astage
    while s is not None:
        d = float(getattr(s, 'diameter_m', 0.0) or 0.0)
        if d > 0.0:
            L = float(s.length_m) if s.length_m > 0.0 else 5.0 * d
            A_p += L * d
        s = s.stage2
    return A_p


def _boost_alpha_aero_force(astage, top_params, vel, alt_m, thrust_dir):
    """α-induced aerodynamic force during powered atmospheric flight.

    When the commanded thrust axis is offset from the velocity vector by an
    angle of attack α, the airframe develops an aerodynamic normal force
    N = q·A_ref·C_N.  Modeled with the Jorgensen slender-body-potential +
    Allen-Perkins viscous cross-flow build-up (the same one used for glider
    L/D, glider_ld.py), referenced to the boost frontal area so it is
    consistent with the axial zero-lift drag:

        C_N(α) = C_Nα_pot·sin(2α)/2 + η·C_dn(M·sinα)·(A_p/A_ref)·sin²α

    Only the INDUCED-DRAG projection of that normal force, N·sinα along −v, is
    applied to the trajectory: it bleeds kinetic energy and so reshapes q
    (∝ α² at small α, since C_N ∝ α).  This is the energy cost SP-8099's q·α
    metric implies and that agile-maneuver studies charge explicitly —
    Fresconi et al. 2017 (ARL-TR-8085) with a sin²α cross-flow axial term, and
    Kim et al. 2013 with the induced-drag polar C_D = C_D0 + k·C_L² whose
    dynamic-pressure collapse is what makes an extreme-α maneuver flyable.

    The lift projection (N·cosα perpendicular to v) is deliberately NOT applied
    as a trajectory force: an ascending booster is designed to fly at low α
    precisely to avoid these loads, and treating its body normal force as free
    loft would let the simplified pitch program's few-degree α mimic a lifting
    body.  This matches drag_force_vector's established ascent convention,
    where a finned stage's normal force is a stability (static-margin) effect,
    not a trajectory force.  So the α term here is a pure cost — it can only
    slow the vehicle, never extend its range.

    Vanishes at α = 0, so with no maneuver this returns a zero vector and the
    boost trajectory is unchanged.  Returns an ECEF force vector (N) to ADD to
    the axial zero-lift drag.
    """
    speed = float(np.linalg.norm(vel))
    if speed < _TGT_KICK_HOLD_V_MS:
        return np.zeros(3)
    v_hat = vel / speed
    cos_a = float(np.clip(np.dot(thrust_dir, v_hat), -1.0, 1.0))
    alpha = float(np.arccos(cos_a))
    if alpha < 1e-4:
        return np.zeros(3)

    _, _, rho, a_snd = atmosphere(max(float(alt_m), 0.0))
    if rho <= 0.0 or a_snd <= 0.0:
        return np.zeros(3)
    q    = 0.5 * rho * speed * speed
    mach = speed / a_snd

    A_ref = booster_area(astage, altitude_m=alt_m, top_params=top_params)
    if A_ref <= 0.0:
        return np.zeros(3)
    A_p = _attached_planform_area(astage)

    from glider_ld import crossflow_cd
    sn   = np.sin(alpha)
    c_dn = crossflow_cd(mach * sn)
    C_N  = (_BOOST_C_NA_POT * np.sin(2.0 * alpha) / 2.0
            + _BOOST_CROSSFLOW_ETA * c_dn * (A_p / A_ref) * sn * sn)

    N = q * A_ref * C_N                       # ⟂ body axis
    return -(N * sn) * v_hat                   # induced drag, along −velocity


def _commanded_thrust_dir(params, astage, pos, vel, lat_rad, lon_rad,
                          azimuth_rad, t, gt_turn_start_s, gt_turn_stop_s,
                          t_final_ignition=0.0, alt_m=None,
                          apply_alpha_limit=True):
    """Unit thrust-pointing vector (ECEF) for the active guidance law.

    Single source of truth for commanded attitude: the EOM applies thrust along
    exactly this vector, and the guidance-program plot derives its pitch/azimuth
    from the SAME call — so the plotted command can never drift from what was
    flown (previously the plot re-derived pitch with a parallel formula that
    diverged whenever the per-stage fields changed).  `azimuth_rad` must already
    include any yaw / dogleg program.

    When the flight plan sets an α limit (params._alpha_limit_deg, stashed by
    integrate_trajectory) the raw command is clamped to the α envelope while
    dynamic pressure is significant — see _alpha_limited_dir.  The plot loop
    passes apply_alpha_limit=False to recover the raw command for the
    envelope-violation diagnostics.  alt_m avoids re-deriving altitude when
    the caller already has it; only needed when a limit is set.
    """
    if params.guidance == "true_gravity_turn":
        raw = _true_gravity_turn_thrust_dir(
            pos, vel, lat_rad, lon_rad, azimuth_rad, t, astage)
    elif astage is not None and astage.stage_burnout_angle_deg is not None:
        _eff_start = (astage.stage_turn_start_s
                      if astage.stage_turn_start_s is not None else gt_turn_start_s)
        _eff_stop  = (astage.stage_turn_stop_s
                      if astage.stage_turn_stop_s is not None else gt_turn_stop_s)
        raw = _gravity_turn_thrust_dir(
            lat_rad, lon_rad, azimuth_rad,
            astage.stage_burnout_angle_deg, _eff_start, _eff_stop, t,
            start_angle_deg=_prev_burnout_angle(params, astage))
    elif params.guidance == "orbital_insertion":
        raw = _orbital_insertion_thrust_dir(
            lat_rad, lon_rad, azimuth_rad,
            params.burnout_angle_deg, gt_turn_start_s, gt_turn_stop_s,
            t_final_ignition, t)
    else:
        # A stage with no per-stage burnout angle continues the ascent from where
        # the previous stage left off -- NOT from launch elevation.  When no stage
        # carries an override, _prev_burnout_angle() returns launch_elevation_deg
        # for every stage, so the whole boost is the single continuous global ramp.
        # When an earlier stage DID pitch to a per-stage angle, this later stage
        # holds/continues from that angle instead of snapping the pitch back up to
        # 90 deg and re-running the global ramp (the "pitch resets each stage" bug).
        _start_angle = (_prev_burnout_angle(params, astage)
                        if astage is not None else params.launch_elevation_deg)
        raw = _gravity_turn_thrust_dir(
            lat_rad, lon_rad, azimuth_rad,
            params.burnout_angle_deg, gt_turn_start_s, gt_turn_stop_s, t,
            start_angle_deg=_start_angle)

    _lim = getattr(params, '_alpha_limit_deg', None)
    if apply_alpha_limit and _lim is not None and _lim > 0.0:
        if alt_m is None:
            _, _, alt_m = ecef_to_geodetic(pos)
        _maxq_ref = getattr(params, '_maxq_pa', [0.0])[0]
        raw = _alpha_limited_dir(raw, vel, float(_lim), alt_m, _maxq_ref)
    return raw


# ---------------------------------------------------------------------------
# Equations of motion
# ---------------------------------------------------------------------------

def _eom(t, state, params, cutoff_time, azimuth_rad, gt_turn_start_s,
         gt_turn_stop_s, target_orbit_alt_m=0.0, t_final_ignition=0.0,
         yaw_maneuvers=None):
    """
    Equations of motion in ECEF frame (Forden Eq. 5/6).

    state = [x, y, z, vx, vy, vz]
    Returns d(state)/dt.

    Guidance uses the user-directed gravity-turn pitch program driven by
    mission elapsed time t.  thrust_force() returns zero during coast so
    attitude during coast has no effect on the trajectory.

    gt_turn_start_s / gt_turn_stop_s are used only when params.guidance ==
    "pitch_program"; they bound the active pitch window.

    target_orbit_alt_m  : when params.guidance == "orbital_insertion" and the
        active stage is NOT a solid motor, engine cutoff is commanded once the
        specific orbital energy reaches the target circular-orbit energy.
        Ignored for solid-motor stages (burn to natural burnout).
    t_final_ignition    : mission-elapsed time at which the final stage
        ignites; used by the two-phase orbital insertion pitch program to
        switch from the boost pitch to the horizontal final-stage burn.
    """
    # ── Stall watch ───────────────────────────────────────────────────────
    # Refuse to evaluate forever at an instant the solver cannot get past.
    # The step size collapses where the derivative kinks (the transonic drag
    # rise is the usual place) if the vehicle sits on the kink instead of
    # crossing it, and nothing else would ever stop the run.  See
    # IntegratorStalled.
    _sw = getattr(params, '_stall_watch', None)
    if _sw is not None:
        if t > _sw[0]:
            _sw[0] = t
            _sw[1] = 0
        else:
            _sw[1] += 1
            if _sw[1] >= _sw[2]:
                _s_lat, _s_lon, _s_alt = ecef_to_geodetic(state[:3])
                _s_v = float(np.linalg.norm(state[3:]))
                _s_snd = speed_of_sound(max(_s_alt, 0.0))
                raise IntegratorStalled(
                    f"the integrator stopped advancing at t = {_sw[0]:.2f} s "
                    f"({_s_alt / 1000.0:.2f} km, {_s_v:.0f} m/s"
                    + (f", Mach {_s_v / _s_snd:.3f}" if _s_snd > 1.0 else "")
                    + f") after {_sw[1]:,} evaluations at that instant. "
                    "The step size has collapsed, most often on a sharp change "
                    "in drag near Mach 1. Check the vehicle's aerodynamic "
                    "inputs — fin thickness against span is the usual culprit "
                    "— or pass stall_evals=0 to let it run regardless.")

    pos = state[:3]
    vel = state[3:]

    lat, lon, alt = ecef_to_geodetic(pos)
    alt = max(alt, 0.0)

    # Track running ASCENT max-q — the reference q for the constant-q·α α
    # envelope (_alpha_limited_dir).  Gated to powered flight so the (higher)
    # reentry q never inflates the reference; the α clamp only acts during
    # powered flight anyway, and by burnout this holds the true ascent max-q.
    _mq = getattr(params, '_maxq_pa', None)
    if _mq is not None and t <= total_burn_time(params):
        _spd_mq = float(np.linalg.norm(vel))
        if _spd_mq > 0.0:
            _, _, _rho_mq, _ = atmosphere(alt)
            _q_mq = 0.5 * _rho_mq * _spd_mq * _spd_mq
            if _q_mq > _mq[0]:
                _mq[0] = _q_mq

    # --- Gravity ---
    g = gravity_ecef(pos)

    # Active stage (needed for drag and mass; guidance uses top-level params)
    astage, _t_since_ign = active_stage_and_t(params, t)


    # Shroud heating-jettison latch (heating mode only: shroud_jettison_alt_km<=0).
    # Free-molecular flux q_dot = 1/2 rho V^3 arms above SHROUD_Q_FAIRING (past
    # max-q) then jettisons on the first drop below it; latched thereafter.
    _sh = getattr(params, '_shroud_latch', None)
    if (_sh is not None and not _sh[1] and params.shroud_mass_kg > 0
            and params.shroud_jettison_alt_km <= 0):
        _spd = float(np.linalg.norm(vel))
        _, _, _rho_sh, _ = atmosphere(alt)
        _qdot = 0.5 * _rho_sh * _spd ** 3
        if not _sh[0]:
            if _qdot > SHROUD_Q_FAIRING:
                _sh[0] = True                    # armed: through max-q
        elif _qdot < SHROUD_Q_FAIRING and alt > 40_000.0:
            # alt guard: the real fairing-flux crossing is high (~110 km); this
            # stops a fresh integration pass (t=0, alt=0, armed already latched
            # on params from an earlier pass) from jettisoning at liftoff.
            _sh[1] = True; _sh[2] = t            # jettison, latched

    # --- Drag ---
    # Density comes from NRLMSISE-00 (or US Std Atm 1976 fallback), both
    # tabulated to 1000 km, so drag is computed from the physical ρ at any
    # altitude — no hard cutoff.  At high altitudes ρ is small enough that
    # the drag force is naturally negligible.
    if (_ero := effective_ro(params)) is not None and t > total_burn_time(params):
        # After final-stage burnout, RV is flying: use β-based drag + optional lift.
        speed = np.linalg.norm(vel)
        if speed > 1e-6:
            _, _, rho, _a_snd = atmosphere(alt)
            q        = 0.5 * rho * speed ** 2
            ro_mass  = _ero.mass_kg
            # Mach-varying (L/D)_max for the derived no-sep body: a table
            # L/D_max(M) is stashed on params at setup (numerical glide modes
            # only); interpolate it on local Mach.  Falls back to the object's
            # constant glider_LD when no table is present (separating RVs, and
            # the analytical Tracy/Acton modes, keep their constant L/D).
            _ld_eff = _ero.glider_LD
            _ld_tab = getattr(params, '_ld_of_mach', None)
            if _ld_tab is not None and _a_snd > 0.0:
                _ld_eff = _ld_tab(speed / _a_snd)
            # Mach-varying β for a derived-β no-sep body (β(Mach) table stashed
            # at setup, like _ld_of_mach); falls back to the object's scalar
            # β_kg_m2 when no table is present (separating RVs, and any body with
            # β entered > 0).  See FRONT_END_DESIGN.md §10.
            # The β(Mach) table is the NOSE-FIRST β (the airframe flying pointed,
            # stabilised by its nose+fins).  A body that cannot hold that attitude
            # TUMBLES — a bluff spinning cylinder with a far lower β — so the
            # tumbling scalar β from effective_ro wins and the nose-first table is
            # ignored.  The trim gate (which includes the fins) makes the
            # nose-first-vs-tumbling call; β simply follows it.
            _beta_eff = float(_ero.beta_kg_m2)
            _beta_tab = getattr(params, '_beta_of_mach', None)
            if (_beta_tab is not None and _a_snd > 0.0
                    and getattr(_ero, 'reentry_attitude', 'trim') != 'tumbling'):
                _beta_eff = _beta_tab(speed / _a_snd)
            drag_mag = q * ro_mass / _beta_eff
            # Glide-phase activation.  The lifting phase begins at APOGEE — the
            # physical start of the descending glide — which the pre-/post-apogee
            # integration split already encodes in _glider_phase1 (True on the
            # ballistic ascent, False from apogee on).  So the numerical
            # phugoid / damped-phugoid / dynamic-equilibrium laws arm on that
            # physical transition, NOT on a fixed 100 km "reentry pierce".
            #
            # The 100 km pierce (ACTON_PIERCE_ALT_M) belongs to the exo-
            # atmospheric Acton skip-glide entry only, and lives on its own
            # analytic path (the _glider_pierce_atmosphere event).  Requiring it
            # HERE silently disabled lift for any vehicle whose apogee never
            # reaches 100 km — a quasi-ballistic quasi-ballistic missile that pulls
            # up at ~40–50 km could not glide at all (the _gl_above_pierce latch
            # never armed).  Dropping that requirement is byte-identical for an
            # exo-atmospheric entry: there the vehicle is post-apogee AND below
            # 100 km at the same instant (the alt < 100 km gate below still holds
            # lift off through the thin near-apogee air on the way down).
            _glider_active = not getattr(params, '_glider_phase1', False)
            v_hat    = vel / speed
            f_drag   = -drag_mag * v_hat
            # Gate all glider activity (lift, polar drag-override) on being
            # below the re-entry pierce altitude.  Above 100 km the vehicle
            # is in ballistic coast — it isn't trimmed at the max-L/D AoA
            # and isn't producing useful lift, so both aero modes should
            # collapse to the same β-based drag computed above.  Without
            # this gate the polar mode applies its α*-trim induced drag
            # (C_D = 2·C_D0) during the post-burnout ascent through the
            # 86–120 km band, costing velocity and dropping apogee
            # relative to constant_LD.
            # A ballistic reentry generates NO lift, full stop — drag · gravity ·
            # rotation only.  The lift block below has no 'ballistic' case, so it
            # relied on glider_enabled being off to stay quiet; but the body
            # setup (setup block ~line 2090) derives glider_LD > 0 for ANY
            # glider_enabled body, and the polar catch-all (elif glider_aero_model
            # == 'polar') then flies even a ballistic-guidance body at max-L/D
            # α* — a hidden skip-glide.  Enforce ballistic = no lift here, in the
            # physics, independent of glider_enabled / glider_LD, so a plan that
            # left glider_enabled on can never leak glide range.
            _ballistic_reentry = (getattr(_ero, 'glider_guidance', 'ballistic')
                                  == 'ballistic')
            if (_ero.glider_enabled and _ero.glider_LD > 0
                    and not _ballistic_reentry
                    and alt < ACTON_PIERCE_ALT_M
                    and _glider_active):
                # Lift direction: vertical-up component of (r̂ ⟂ v̂), banked.
                r_mag = np.linalg.norm(pos)
                if r_mag > 1e-3:
                    r_hat = pos / r_mag
                    n_up = r_hat - np.dot(r_hat, v_hat) * v_hat
                    n_up_mag = np.linalg.norm(n_up)
                    if n_up_mag > 1e-9:
                        n_up   = n_up / n_up_mag
                        n_side = _cross3(v_hat, n_up)
                        g_mag  = np.linalg.norm(g)
                        # Bank angle from the user's bank schedule (list of
                        # (t_start_s, t_end_s, bank_deg) entries in mission-
                        # elapsed seconds).  Positive bank = right turn.
                        bank_rad = 0.0
                        for (_bt_s, _bt_e, _bk_deg) in (_ero.glider_bank_schedule or []):
                            if _bt_s <= t <= _bt_e:
                                bank_rad = np.radians(_bk_deg)
                                break
                        if _ero.glider_terminal_dive:
                            # 0 km = glide to impact: the altitude check can
                            # never fire, so only the target-proximity
                            # trigger below can command the dive.
                            _dive_now = (alt < _ero.glider_terminal_alt_km * 1000.0)
                            # Target-proximity dive trigger: bypasses the
                            # altitude check when the vehicle gets within
                            # the user-set radius of (target_lat, target_lon).
                            _td_r = float(getattr(_ero, 'glider_dive_target_radius_km', 0.0) or 0.0)
                            if not _dive_now and _td_r > 0.0:
                                _t_lat = np.radians(float(_ero.glider_dive_target_lat_deg))
                                _t_lon = np.radians(float(_ero.glider_dive_target_lon_deg))
                                # Haversine distance, vehicle ↔ target
                                _dlat = lat - _t_lat
                                _dlon = lon - _t_lon
                                _hav  = (np.sin(0.5*_dlat)**2
                                         + np.cos(_t_lat) * np.cos(lat) * np.sin(0.5*_dlon)**2)
                                _hav  = min(max(_hav, 0.0), 1.0)
                                _dist_km = 2.0 * 6_371.0 * np.arcsin(np.sqrt(_hav))
                                if _dist_km < _td_r:
                                    _dive_now = True
                            if _dive_now:
                                bank_rad = np.pi

                        # ---- Commanded pull-up (plan-phase modifier) --------
                        # glider_pullup_start_alt_km > 0 splits capture into
                        # three phases: ballistic fall (zero commanded lift,
                        # the β drag already computed) above the trigger; a
                        # hard pull at the trigger, at full authority capped
                        # by BOTH the structural g-limit and what q + the aero
                        # model supply (triggering too high undershoots
                        # honestly — no lift is conjured); then a ONE-WAY
                        # handoff to the selected glide law once the sink rate
                        # is arrested to the law's own equilibrium target
                        # γ* = −2·H_ρ·g/(V²·cosσ·(L/D)) (Lu Eq. 31).  This
                        # frees ζ to do the job its linearization assumes —
                        # damping small residuals near equilibrium — instead
                        # of arresting a km/s-class fall.  Flight precedent:
                        # SWERVE III's discrete commanded pull-out at Mach 12
                        # (Iliff & Shafer, AIAA 93-0311, Fig. 20, t = 20 s).
                        # Unset (0) is byte-identical to the plain glide laws.
                        _pu_handled = False
                        _pu_alt_m = float(getattr(_ero, 'glider_pullup_start_alt_km',
                                                  0.0) or 0.0) * 1000.0
                        _pu = getattr(params, '_pullup_phase', None)
                        if (_pu_alt_m > 0.0 and _pu is not None
                                and _ero.glider_guidance in
                                    ('damped_glide', 'dynamic_equilibrium_glide',
                                     'skip_glide')):
                            _hdot_pu = speed * float(np.dot(v_hat, r_hat))
                            if _pu[0] == 0 and alt <= _pu_alt_m and _hdot_pu < 0.0:
                                _pu[0] = 1
                            if _pu[0] == 1:
                                _dh = 200.0
                                _rho0 = atmosphere(max(alt, 0.0))[2]
                                _rho1 = atmosphere(max(alt, 0.0) + _dh)[2]
                                _Hrho_pu = (_dh / np.log(_rho0 / _rho1)
                                            if (_rho1 > 0.0 and _rho0 > _rho1)
                                            else 7000.0)
                                _Hrho_pu = min(max(_Hrho_pu, 4000.0), 12000.0)
                                _cosb_pu = max(abs(float(np.cos(bank_rad))), 0.05)
                                _gstar_pu = (-2.0 * _Hrho_pu * g_mag
                                             / (speed * speed * _cosb_pu * _ld_eff))
                                if _hdot_pu >= speed * _gstar_pu:
                                    _pu[0] = 2      # captured — glide law owns it
                            if _pu[0] == 0:
                                # Ballistic fall: no commanded lift; the
                                # β-based zero-lift drag stands unmodified.
                                lift_mag = 0.0
                                _pu_handled = True
                            elif _pu[0] == 1:
                                _L_struct = (_ero.glider_pullup_g_max
                                             * g_mag * ro_mass)
                                if q > 1.0:
                                    if getattr(_ero, 'glider_aero_model',
                                               'polar') == 'polar':
                                        _polp = _aero_polar(_ero, _ld_eff)
                                        _C_L = min(_L_struct / (q * _polp.A_ref),
                                                   _polp.C_L_max)
                                        lift_mag = q * _polp.A_ref * _C_L
                                        drag_mag = q * _polp.A_ref * _polar_cd(_C_L, _polp)
                                    else:
                                        _drag_b = (q / _beta_eff) * ro_mass
                                        lift_mag = min(_L_struct, _drag_b * _ld_eff)
                                        drag_mag = max(_drag_b,
                                                       lift_mag / max(_ld_eff, 1e-6))
                                    f_drag = -drag_mag * v_hat
                                else:
                                    lift_mag = 0.0
                                _pu_handled = True

                        if _pu_handled:
                            pass
                        elif _ero.glider_guidance == 'damped_glide':
                            # Damped-phugoid glide.  NOMINAL = the max-L/D α* (skip)
                            # lift — so the natural phugoid is preserved (α* lift ∝ q
                            # over/undershoots equilibrium) — plus ζ altitude-rate
                            # damping (Lu Eq. 33) that genuinely DAMPS the skips:
                            #   γ* = −2·H_ρ·g / (V²·cosσ·(L/D))      (Lu Eq. 31)
                            #   ḣ_eq = V·γ* ;  k_h = 2·ζ·m·√(g_eff/H_ρ)
                            # ζ controls the decay — ζ=0 ≡ skip_glide (undamped
                            # skips); larger ζ → fewer/smaller decaying skips into
                            # equilibrium.  Lift is capped at the aerodynamic ceiling
                            # and drag is coupled to the actual commanded lift, so
                            # there is NO free lift.  On an uncapturable (lofted)
                            # entry it plunges, like skip_glide.  (For a smooth,
                            # non-oscillatory capture see dynamic_equilibrium_glide.)
                            _polar = (getattr(_ero,'glider_aero_model','polar')=='polar')
                            _L_max = _ero.glider_pullup_g_max * g_mag * ro_mass
                            _cos_b = max(abs(float(np.cos(bank_rad))), 0.05)
                            _g_eff = max(g_mag - speed*speed/r_mag, 0.0)
                            if q > 1.0:
                                if _polar:
                                    _pol=_aero_polar(_ero, _ld_eff)
                                    _CLstar=min(_pol.C_L_star, _pol.C_L_max)
                                    _L_nom=q*_pol.A_ref*_CLstar
                                else:
                                    _drag_beta=(q/_beta_eff)*ro_mass
                                    _L_nom=_drag_beta*_ld_eff
                                if _g_eff > 1e-3:
                                    _dh=200.0
                                    _rho0=atmosphere(max(alt,0.0))[2]; _rho1=atmosphere(max(alt,0.0)+_dh)[2]
                                    _Hrho=(_dh/np.log(_rho0/_rho1) if (_rho1>0.0 and _rho0>_rho1) else 7000.0)
                                    _Hrho=min(max(_Hrho,4000.0),12000.0)
                                    _hdot=speed*float(np.dot(v_hat,r_hat))
                                    _gstar=(-2.0*_Hrho*g_mag/(speed*speed*_cos_b*_ld_eff))
                                    _k_h=(2.0*max(float(_ero.glider_damping_zeta),0.0)*ro_mass*np.sqrt(_g_eff/_Hrho))
                                    _L_target=_L_nom - _k_h*(_hdot - speed*_gstar)
                                else:
                                    _L_target=_L_nom
                                if _polar:
                                    _C_L=min(max(_L_target/(q*_pol.A_ref),0.0),_pol.C_L_max)
                                    drag_mag=q*_pol.A_ref*_polar_cd(_C_L,_pol)
                                    lift_mag=q*_pol.A_ref*_C_L
                                else:
                                    # constant_LD: cap at the β-available lift
                                    # (= the α* nominal here), so the lumped model
                                    # cannot pull out beyond what the aero supplies
                                    # — consistent with the physical polar ceiling
                                    # (otherwise the structural cap lets it over-
                                    # capture a lofted entry).  Feedback can still
                                    # reduce lift to damp the skip-up.
                                    lift_mag=min(max(_L_target,0.0),_L_nom,_L_max)
                                    drag_mag=lift_mag/max(_ld_eff,1e-6)
                                f_drag=-drag_mag*v_hat
                            else:
                                lift_mag=0.0
                        elif _ero.glider_guidance == 'dynamic_equilibrium_glide':
                            # Dynamic equilibrium glide (EOM).  NOMINAL = the
                            # equilibrium-glide trim L·cosσ = m·(g − V²/r); the ζ
                            # knob here is a TRACKING GAIN on the altitude-rate
                            # error (not a phugoid damping ratio — this mode does
                            # not oscillate, it captures smoothly).  Lift is
                            # β-capped (zoom-prevention) and drag coupled to the
                            # actual lift.  Honest dynamic capture: shallow
                            # insertions capture, lofted entries plunge.  Distinct
                            # from the analytic equilibrium_glide (which always
                            # captures via the closed-form arc).  See
                            # GLIDE_CAPTURE_DESIGN.md §8.
                            _polar = (getattr(_ero, 'glider_aero_model',
                                              'polar') == 'polar')
                            _L_max = _ero.glider_pullup_g_max * g_mag * ro_mass
                            _cos_b = max(abs(float(np.cos(bank_rad))), 0.05)
                            _g_eff = max(g_mag - speed * speed / r_mag, 0.0)
                            if q > 1.0 and _g_eff > 1e-3:
                                _dh = 200.0
                                _rho0 = atmosphere(max(alt, 0.0))[2]
                                _rho1 = atmosphere(max(alt, 0.0) + _dh)[2]
                                _Hrho = (_dh / np.log(_rho0 / _rho1)
                                         if (_rho1 > 0.0 and _rho0 > _rho1)
                                         else 7000.0)
                                _Hrho = min(max(_Hrho, 4000.0), 12000.0)
                                _hdot = speed * float(np.dot(v_hat, r_hat))
                                _gstar = (-2.0 * _Hrho * g_mag
                                          / (speed * speed * _cos_b
                                             * _ld_eff))
                                _k_h = (2.0 * max(float(_ero.glider_damping_zeta), 0.0)
                                        * ro_mass * np.sqrt(_g_eff / _Hrho))
                                # equilibrium trim + phugoid damping:
                                _L_target = (ro_mass * _g_eff / _cos_b
                                             - _k_h * (_hdot - speed * _gstar))
                                if _polar:
                                    _pol = _aero_polar(_ero, _ld_eff)
                                    # aerodynamic lift ceiling: C_L <= C_L,max
                                    _C_L = min(max(_L_target / (q * _pol.A_ref), 0.0),
                                               _pol.C_L_max)
                                    drag_mag = q * _pol.A_ref * _polar_cd(_C_L, _pol)
                                    lift_mag = q * _pol.A_ref * _C_L
                                else:
                                    # lumped model: drag tracks lift at the fixed
                                    # L/D.  Cap at the β-based available lift
                                    # (q/β)·m·(L/D) (as equilibrium_glide) — this
                                    # shrinks as the vehicle slows, so once captured
                                    # it descends to denser air instead of
                                    # zoom-climbing on the growing m·g_eff term
                                    # (the lumped model has no aerodynamic C_L,max
                                    # ceiling to do this on its own).
                                    _beta_cap = (q / _beta_eff) * ro_mass * _ld_eff
                                    lift_mag = min(max(_L_target, 0.0), _beta_cap, _L_max)
                                    drag_mag = lift_mag / max(_ld_eff, 1e-6)
                                f_drag = -drag_mag * v_hat
                            else:
                                lift_mag = 0.0
                        elif getattr(_ero, 'glider_aero_model', 'polar') == 'polar':
                            _pol = _aero_polar(_ero, _ld_eff)
                            _Aref = _pol.A_ref
                            _C_L_lim = _pol.C_L_max     # geometry-anchored ceiling
                            _L_max = _ero.glider_pullup_g_max * g_mag * ro_mass
                            if _ero.glider_guidance in (
                                    'equilibrium_glide', 'equilibrium_glide_acton'):
                                # Equilibrium trim: solve for the C_L that
                                # satisfies L·cos σ = m·(g − V²/r).  Suppresses
                                # phugoid, giving steady equilibrium-glide descent.
                                _g_perp = g_mag - speed * speed / r_mag
                                if _g_perp < 0.0:
                                    _g_perp = 0.0
                                _cos_b = abs(float(np.cos(bank_rad)))
                                if _cos_b < 0.05:
                                    _cos_b = 0.05
                                # β-based aerodynamic cap (same as constant_LD):
                                # lift ≤ (q/β)·m·L/D.  This cap decreases as v
                                # drops, so when v < v_eq the vehicle descends to
                                # denser air rather than zooming up.  Without it,
                                # the analytic m·g_perp term grows as v decreases
                                # (g_perp = g − v²/r increases), driving a zoom
                                # climb instead of a descending equilibrium glide.
                                _drag_beta  = (q / _beta_eff) * ro_mass
                                _lift_beta_cap = _drag_beta * _ld_eff
                                _L_total = min(ro_mass * _g_perp / _cos_b,
                                              _lift_beta_cap,
                                              _L_max)
                                if q > 1.0:
                                    _C_L = min(_L_total / (q * _Aref), _C_L_lim)
                                    _C_D = _polar_cd(_C_L, _pol)
                                    drag_mag = q * _Aref * _C_D
                                    lift_mag = q * _Aref * _C_L
                                else:
                                    lift_mag = 0.0
                            else:
                                # skip_glide / phugoid: fly at max-L/D AoA (α*)
                                # so lift ∝ q and the natural phugoid oscillation
                                # is preserved.  C_L* = √(C_D0/k); C_D* = 2·C_D0.
                                if q > 1.0:
                                    _C_L = min(_pol.C_L_star, _C_L_lim)
                                    _C_D = _polar_cd(_C_L, _pol)
                                    drag_mag = q * _Aref * _C_D
                                    lift_mag = min(q * _Aref * _C_L, _L_max)
                                else:
                                    lift_mag = 0.0
                            # Override drag with the polar-derived value
                            f_drag = -drag_mag * v_hat
                        else:
                            # constant_LD (idealized fixed-L/D): lift is drag × L/D unless
                            # equilibrium-glide guidance is selected, in which
                            # case we trim to L·cos σ = m·g⊥ (suppresses the
                            # phugoid, matching the closed-form Tracy/Acton soln).
                            if _ero.glider_guidance in (
                                    'equilibrium_glide', 'equilibrium_glide_acton'):
                                _g_perp_c = max(g_mag - speed * speed / r_mag, 0.0)
                                _cos_b_c  = max(abs(float(np.cos(bank_rad))), 0.05)
                                # Cap at what the aerodynamics can actually supply
                                # (drag × L/D).  Without this cap the analytical
                                # lift term m·g⊥ is applied even when dynamic
                                # pressure is negligible (high altitude, thin
                                # atmosphere), locking the vehicle at the handoff
                                # altitude and producing unrealistically long range.
                                # When v < v_eq (above equilibrium altitude) the
                                # aero cap is smaller than m·g⊥ and the vehicle
                                # descends naturally to the proper glide altitude.
                                lift_mag  = min(
                                    ro_mass * _g_perp_c / _cos_b_c,
                                    drag_mag * _ld_eff,
                                    _ero.glider_pullup_g_max * g_mag * ro_mass)
                            else:
                                lift_mag = drag_mag * _ld_eff
                            lift_cap = _ero.glider_pullup_g_max * g_mag * ro_mass
                            if lift_mag > lift_cap:
                                lift_mag = lift_cap

                        f_lift = lift_mag * (np.cos(bank_rad) * n_up
                                             + np.sin(bank_rad) * n_side)
                        f_drag = f_drag + f_lift
        else:
            f_drag = np.zeros(3)
        _in_boost_drag = False
    else:
        # Powered = the active stage is within its effective burn (per-stage
        # cutoff honoured by _eff_burn) and before any global cutoff.  Gates the
        # power-on base-bleed drag reduction; coast phases (t_since = 0) and
        # post-cutoff are unpowered, so base drag stays at its power-off value.
        _powered = (0.0 < _t_since_ign < _eff_burn(astage)) and (t <= cutoff_time)
        f_drag = drag_force_vector(astage, vel, alt, top_params=params, t_s=t,
                                   powered=_powered)
        if params.n_boosters > 0 and t <= booster_separation_time(params):
            f_drag = f_drag + booster_drag_vector(params, vel, alt)
        _in_boost_drag = True

    # --- Thrust with mode-selected guidance ---
    # For orbital_insertion mode with a liquid-engine final stage, check
    # whether the current specific orbital energy has reached the target value;
    # if so, shut down the engine regardless of cutoff_time.
    #
    # Two guards prevent a spurious cutoff that would produce an orbit with
    # perigee underground:
    #   (a) only fire during the FINAL-stage burn (not stage 1/2 — astage is
    #       the currently burning stage; _final_stage is the last in the chain)
    #   (b) vehicle must already be above 80 % of the target orbit altitude, so
    #       the resulting orbit's perigee stays well above the atmosphere
    engine_on = (t <= cutoff_time)
    if engine_on and params.guidance == "orbital_insertion" and target_orbit_alt_m > 0:
        _final_stage = params
        while _final_stage.stage2 is not None:
            _final_stage = _final_stage.stage2
        if astage is _final_stage and not _final_stage.solid_motor:
            omega_vec = np.array([0.0, 0.0, OMEGA_EARTH])
            vel_eci   = vel + _cross3(omega_vec, pos)
            r         = np.linalg.norm(pos)
            eps_now   = 0.5 * np.dot(vel_eci, vel_eci) - GM / r
            eps_target = -GM / (2.0 * (RE + target_orbit_alt_m))
            if eps_now >= eps_target:
                # Verify the resulting orbit has a survivable perigee (> 80 km).
                # A steeply-ascending cutoff can produce an orbit whose perigee
                # is underground even though the energy is correct; the altitude
                # guard in the previous version was too strict (blocked insertion
                # burns at 150–200 km for 500 km target orbits).
                h_vec = _cross3(pos, vel_eci)
                h2    = np.dot(h_vec, h_vec)
                a     = -GM / (2.0 * eps_now)
                e     = np.sqrt(max(0.0, 1.0 - h2 / (GM * a)))
                r_perigee = a * (1.0 - e)
                if r_perigee > RE + 80_000:   # perigee above 80 km
                    engine_on = False

    # Compute time-varying azimuth (dogleg yaw program).
    # This runs regardless of engine state so the guidance attitude is
    # always defined; future callers can derive sideslip from the result.
    azimuth_rad = _yaw_program(t, azimuth_rad, astage, yaw_maneuvers)

    if engine_on:
        # Commanded attitude comes from the single shared guidance function so
        # the guidance-program plot (which calls the same function) shows exactly
        # what was flown.
        thrust_dir = _commanded_thrust_dir(
            params, astage, pos, vel, lat, lon, azimuth_rad, t,
            gt_turn_start_s, gt_turn_stop_s, t_final_ignition, alt_m=alt)
        f_thrust = thrust_force(params, t, alt, thrust_dir)
    else:
        f_thrust = np.zeros(3)

    # --- α-induced aerodynamic force (opt-in; SP-8099 / Fresconi / Kim) ---
    # While the engine is on and the vehicle is in the powered atmospheric
    # (boost) drag regime, a commanded thrust axis offset from the velocity by
    # an angle of attack develops an aerodynamic normal force whose induced-
    # drag component bleeds energy and reshapes q.  Off by default (pure zero
    # increment) so every validated trajectory is unchanged; enabled per plan
    # via alpha_induced_drag.  Zero at α = 0 regardless.
    f_alpha = np.zeros(3)
    if (engine_on and _in_boost_drag
            and getattr(params, '_alpha_induced_drag', False)):
        f_alpha = _boost_alpha_aero_force(astage, params, vel, alt, thrust_dir)

    # --- Mass ---
    m = booster_mass(params, t, alt)

    # --- Non-inertial frame corrections ---
    a_coriolis    = coriolis_acceleration(vel)
    a_centrifugal = centrifugal_acceleration(pos)

    # --- Total acceleration (Forden Eq. 6) ---
    accel = g + (f_drag + f_thrust + f_alpha) / m + a_coriolis + a_centrifugal

    return np.concatenate([vel, accel])


def _hit_ground(t, state, params, cutoff_time, azimuth_rad, gt_turn_start_s,
                gt_turn_stop_s, target_orbit_alt_m=0.0, t_final_ignition=0.0,
                yaw_maneuvers=None):
    """Event: booster hits the ground.

    With the DEM on (params._terrain_dem), the ground is the real terrain height
    at the sub-vehicle point (terrain.py coarse grid — offline, bilinear, so the
    event stays continuous for the root-finder); otherwise flat sea level."""
    lat, lon, alt = ecef_to_geodetic(state[:3])
    if getattr(params, '_terrain_dem', False):
        import terrain as _terrain
        return alt - _terrain.ground_elevation(np.degrees(lat), np.degrees(lon),
                                               hi_res=False)
    return alt

_hit_ground.terminal  = True
_hit_ground.direction = -1


def _glider_pierce_atmosphere(t, state, params, cutoff_time, azimuth_rad,
                              gt_turn_start_s, gt_turn_stop_s,
                              target_orbit_alt_m=0.0, t_final_ignition=0.0,
                              yaw_maneuvers=None):
    """Event: glider pierces upper atmosphere on descent (alt = ACTON_PIERCE_ALT_M)."""
    _, _, alt = ecef_to_geodetic(state[:3])
    return alt - ACTON_PIERCE_ALT_M

_glider_pierce_atmosphere.terminal  = True
_glider_pierce_atmosphere.direction = -1


def _make_phase3_end_event(h_3_target_m: float):
    """
    Acton-mode event: descending crossing of h_3, the altitude at which
    the high-AoA direct-re-entry orientation transitions to glide
    orientation.  ρ(h_3)/β_S = ρ(h_eq)/β_L  (Acton 2015 Eq. 8).
    """
    def _evt(t, state, *args, **kwargs):
        _, _, alt = ecef_to_geodetic(state[:3])
        return alt - h_3_target_m
    _evt.terminal  = True
    _evt.direction = -1
    return _evt


def _acton_pullup_arc(pos: np.ndarray, vel: np.ndarray,
                      LD: float, beta_L: float,
                      n_samples: int = 12) -> tuple:
    """
    Generate samples along Acton's analytical pull-up arc (Acton 2015,
    Eqs. 11, 13–17) plus Tracy's equilibrium-glide initial condition
    (Tracy 2020, Eq. 7).

    The arc is a circular path in the local (downrange, vertical) plane
    fitted between (h_3, γ = −θ_2) at the pierce point and (h_eq, γ = 0)
    at the start of equilibrium glide.  The geometric radius is

        R = (h_3 − h_eq) / (1 − cos θ_2)              (small-angle limit
                                                       coincides with
                                                       Acton's Eq. 13).

    Velocity along the arc follows Acton Eq. 11:
        V(γ) = V_3 · exp(−(D/L)·(θ_2 − θ))            with θ = −γ.

    Pull-up duration uses the high-speed-limit form of Acton Eq. 15:
        t_pullup = R · θ_2 / V_3.

    Returns (samples, t_pullup, post_state) where:
      • samples is a list of (t_offset, pos_ecef, vel_ecef) for the arc,
        excluding the pierce point itself but including the endpoint;
      • t_pullup is the total arc duration (s);
      • post_state is the (pos, vel) at γ = 0 — the IC for Tracy glide.

    If geometry is degenerate (ascending, super-orbital, or h_eq outside
    fit validity) returns ([], 0.0, pos+vel) so the caller falls back to
    the unmodified state.
    """
    speed = float(np.linalg.norm(vel))
    r_mag = float(np.linalg.norm(pos))
    fallback = ([], 0.0, np.concatenate([pos, vel]))
    if speed < 1.0 or r_mag < 1e3:
        return fallback

    r_hat = pos / r_mag
    v_hat = vel / speed
    sin_gamma = float(np.dot(v_hat, r_hat))           # >0 ascending
    if sin_gamma >= 0.0:
        return fallback
    theta_2 = float(np.arcsin(min(1.0, -sin_gamma)))

    # Acton Eq. 11 — velocity at end of pull-up: dV/V = −(D/L)·dγ → exp(−θ/(L/D))
    v_4 = speed * float(np.exp(-theta_2 / LD))

    # Tracy Eq. 7 — equilibrium altitude h_eq(v_4).
    g_mag = float(np.linalg.norm(gravity_ecef(pos)))
    radial_acc = g_mag - v_4**2 / r_mag
    if radial_acc <= 0.0:
        return fallback
    rho_eq = 2.0 * beta_L * radial_acc / (v_4**2 * LD)
    if rho_eq <= 0.0:
        return fallback
    # Equilibrium altitude from Acton's isothermal exponential atmosphere
    # (same model used by _analytical_equil_glide for the glide phase).
    h_eq = ACTON_SCALE_HEIGHT_M * float(np.log(ACTON_SEA_LEVEL_RHO / rho_eq))
    if not (5_000.0 < h_eq < 80_000.0):
        return fallback

    lat, lon, h_3 = ecef_to_geodetic(pos)
    if h_3 <= h_eq:
        return fallback                               # already below h_eq

    # Geometric arc radius fitting (h_3, −θ_2) to (h_eq, 0).
    # For very shallow entry angles the denominator (1 − cos θ₂) → 0, making
    # R = (h₃ − h_eq)/(1 − cos θ₂) unphysically large (> Earth's radius at
    # θ₂ < ~8°; > Earth-Moon distance at θ₂ ≈ 1°).  This happens when a
    # booster burns nearly horizontally so apogee barely exceeds 100 km and
    # the pierce angle is ~1°.  Below 3° the vehicle is already in near-
    # equilibrium glide and needs no pull-up arc; return the fallback so the
    # caller starts the analytical glide immediately from the pierce state.
    one_minus_cos = 1.0 - float(np.cos(theta_2))
    if theta_2 < np.radians(3.0) or one_minus_cos < 1e-9:
        return fallback
    R = (h_3 - h_eq) / one_minus_cos
    t_pullup = R * theta_2 / speed                    # high-speed limit

    # Ground-track azimuth at the pierce point — direction of horizontal
    # velocity in the local ENU frame.
    e_east, e_north, e_up = _enu_frame(lat, lon)
    v_e = float(np.dot(vel, e_east))
    v_n = float(np.dot(vel, e_north))
    if abs(v_e) < 1e-6 and abs(v_n) < 1e-6:
        return fallback
    azimuth = float(np.arctan2(v_e, v_n))             # 0 = north, π/2 = east

    # Spherical-Earth great-circle move helper (good enough for ~10³ km arcs).
    R_e = 6_371_000.0
    sin_az, cos_az = float(np.sin(azimuth)), float(np.cos(azimuth))
    sin_lat0, cos_lat0 = float(np.sin(lat)), float(np.cos(lat))

    def _move(downrange_m: float):
        d = downrange_m / R_e                         # angular distance
        sd, cd = float(np.sin(d)), float(np.cos(d))
        sin_lat2 = sin_lat0 * cd + cos_lat0 * sd * cos_az
        lat2 = float(np.arcsin(max(-1.0, min(1.0, sin_lat2))))
        lon2 = lon + float(np.arctan2(
            sin_az * sd * cos_lat0,
            cd - sin_lat0 * sin_lat2))
        # Local heading at lat2/lon2 along the great circle (azimuth here).
        # For short arcs the bearing rotation is small; preserve original
        # azimuth at the destination.
        return lat2, lon2

    # Generate arc samples.  i = 1 .. n_samples, sample i at fraction i/N
    # of the arc (γ goes linearly from −θ_2 to 0).
    samples = []
    for i in range(1, n_samples + 1):
        frac      = i / float(n_samples)
        theta     = theta_2 * (1.0 - frac)            # θ from θ_2 down to 0
        downrange = R * (float(np.sin(theta_2)) - float(np.sin(theta)))
        alt       = h_3 - R * (float(np.cos(theta)) - float(np.cos(theta_2)))
        v_at      = speed * float(np.exp(-(theta_2 - theta) / LD))
        t_off     = R * (theta_2 - theta) / speed     # high-speed limit

        lat_i, lon_i = _move(downrange)
        pos_i = geodetic_to_ecef(lat_i, lon_i, alt)

        # Velocity in the local ENU at sample point.
        e_east_i, e_north_i, e_up_i = _enu_frame(lat_i, lon_i)
        forward_i = sin_az * e_east_i + cos_az * e_north_i
        vel_i = v_at * (float(np.cos(theta)) * forward_i
                        - float(np.sin(theta)) * e_up_i)

        samples.append((t_off, pos_i, vel_i))

    # Endpoint = post-pull-up state for the equilibrium-glide integration.
    post_pos = samples[-1][1]
    post_vel = samples[-1][2]
    post_state = np.concatenate([post_pos, post_vel])
    return samples, t_pullup, post_state


def _analytical_equil_glide(
        start_pos: np.ndarray,
        start_vel: np.ndarray,
        beta_L: float,
        LD: float,
        h_terminal_m: float = 30_000.0,
        n_samples: int = 200,
        bank_schedule: list = None,
        t_offset: float = 0.0,
) -> tuple:
    """
    Tracy 2020 / Acton 2015 Phase-5 equilibrium glide, closed-form.

    Uses the isothermal exponential atmosphere (Acton's fit, valid 30–100 km):
        ρ(h) = ρ_0 · exp(−h / H)

    Range (Tracy Eq. ~10):
        R(V) = (L/D · r / 2) · ln[(g·r − V²) / (g·r − V_4²)]

    Equilibrium altitude:
        h(V) = H · ln(ρ_0 / ρ_eq(V)),   ρ_eq = 2β(g − V²/r) / (V²·L/D)

    Glide ends when h_eq reaches h_terminal_m.  Returns (t_rel, pos_ecef,
    vel_ecef) where t_rel are time offsets (s) from the arc endpoint, and
    pos_ecef / vel_ecef are N×3 arrays.
    """
    H    = ACTON_SCALE_HEIGHT_M
    rho0 = ACTON_SEA_LEVEL_RHO

    V_4 = float(np.linalg.norm(start_vel))
    r_s = float(np.linalg.norm(start_pos))
    if V_4 < 100.0 or r_s < 1e3:
        return (np.array([0.0]),
                start_pos.reshape(1, 3),
                start_vel.reshape(1, 3))

    g = GM / r_s**2
    r = r_s

    # Terminal velocity where equilibrium altitude = h_terminal_m
    rho_term  = rho0 * float(np.exp(-h_terminal_m / H))
    denom_f   = rho_term * LD * r + 2.0 * beta_L
    V_f       = float(np.sqrt(max(2.0 * beta_L * g * r / denom_f, 1.0)))
    if V_f >= V_4:
        return (np.array([0.0]),
                start_pos.reshape(1, 3),
                start_vel.reshape(1, 3))

    # Heading azimuth at the glide start (γ ≈ 0, so velocity ≈ horizontal)
    lat_s, lon_s, _ = ecef_to_geodetic(start_pos)
    e_east_s, e_north_s, _ = _enu_frame(lat_s, lon_s)
    v_hat = start_vel / V_4
    azimuth  = float(np.arctan2(float(np.dot(v_hat, e_east_s)),
                                float(np.dot(v_hat, e_north_s))))
    sin_az   = float(np.sin(azimuth));  cos_az  = float(np.cos(azimuth))
    sin_lat0 = float(np.sin(lat_s));    cos_lat0 = float(np.cos(lat_s))
    R_e = 6_371_000.0

    # Sample velocity grid
    V_arr = np.linspace(V_4, V_f, n_samples)
    V_c2  = g * r

    # Cumulative downrange (Tracy range formula). For V<V_4 the numerator
    # (g·r−V²) exceeds the denominator (g·r−V_4²), so R grows monotonically
    # forward along the bearing as V decreases.
    R_arr = (LD * r / 2.0) * np.log(
        np.maximum(V_c2 - V_arr**2, 1.0) / max(V_c2 - V_4**2, 1.0))

    # Equilibrium altitude h(V)
    radial_acc = g - V_arr**2 / r
    rho_eq_arr = 2.0 * beta_L * np.maximum(radial_acc, 1e-30) / (V_arr**2 * LD)
    h_arr      = H * np.log(rho0 / np.maximum(rho_eq_arr, 1e-30))
    h_arr      = np.maximum(h_arr, 0.0)

    # Cumulative time: dt/dV = L/D / (g − V²/r), V decreasing
    t_arr = np.zeros(n_samples)
    for i in range(1, n_samples):
        dV     = abs(V_arr[i] - V_arr[i - 1])
        ra_avg = 0.5 * (float(radial_acc[i]) + float(radial_acc[i - 1]))
        t_arr[i] = t_arr[i - 1] + (LD * dV / ra_avg if ra_avg > 1e-6 else 0.0)

    # Heading at each sample.  Bank σ tilts the lift vector laterally; with
    # equilibrium balance L·cos σ = m·(g − V²/r), the horizontal component
    # gives turn rate dψ/dt = (g − V²/r)·tan σ / V.  Positive σ = right turn
    # (matches the n_side = v_hat × n_up convention used in the numerical EOM).
    psi_arr = np.zeros(n_samples)
    psi_arr[0] = azimuth
    for i in range(1, n_samples):
        sigma_i = 0.0
        if bank_schedule:
            t_mid = 0.5 * (float(t_arr[i]) + float(t_arr[i - 1])) + t_offset
            for (_bs, _be, _bk) in bank_schedule:
                if _bs <= t_mid <= _be:
                    sigma_i = float(np.radians(_bk))
                    break
        V_mid  = 0.5 * (float(V_arr[i]) + float(V_arr[i - 1]))
        ra_mid = 0.5 * (float(radial_acc[i]) + float(radial_acc[i - 1]))
        dt     = float(t_arr[i] - t_arr[i - 1])
        d_psi  = ra_mid * float(np.tan(sigma_i)) / max(V_mid, 1.0) * dt
        psi_arr[i] = psi_arr[i - 1] + d_psi

    # Iterative great-circle stepping with time-varying bearing
    pos_out = np.zeros((n_samples, 3))
    vel_out = np.zeros((n_samples, 3))
    cur_lat, cur_lon = lat_s, lon_s
    pos_out[0] = geodetic_to_ecef(cur_lat, cur_lon, float(h_arr[0]))
    e_e0, e_n0, _ = _enu_frame(cur_lat, cur_lon)
    sa0 = float(np.sin(psi_arr[0])); ca0 = float(np.cos(psi_arr[0]))
    vel_out[0] = V_arr[0] * (sa0 * e_e0 + ca0 * e_n0)
    for i in range(1, n_samples):
        d   = float(R_arr[i] - R_arr[i - 1]) / R_e
        sd, cd = float(np.sin(d)), float(np.cos(d))
        sa, ca = float(np.sin(psi_arr[i])), float(np.cos(psi_arr[i]))
        scl = float(np.sin(cur_lat)); ccl = float(np.cos(cur_lat))
        sl2 = scl * cd + ccl * sd * ca
        new_lat = float(np.arcsin(max(-1.0, min(1.0, sl2))))
        new_lon = cur_lon + float(np.arctan2(sa * sd * ccl,
                                              cd - scl * sl2))
        pos_out[i] = geodetic_to_ecef(new_lat, new_lon, float(h_arr[i]))
        e_e_i, e_n_i, _ = _enu_frame(new_lat, new_lon)
        vel_out[i] = V_arr[i] * (sa * e_e_i + ca * e_n_i)
        cur_lat, cur_lon = new_lat, new_lon

    return t_arr, pos_out, vel_out


# ---------------------------------------------------------------------------
# Debris ballistic arc integrator
# ---------------------------------------------------------------------------

def integrate_debris(pos_ecef: np.ndarray, vel_ecef: np.ndarray,
                     beta_kg_m2: float,
                     max_time_s: float = 7200.0,
                     return_trajectory: bool = False):
    """
    Integrate a tumbling debris piece from separation to ground impact.

    Uses β-based drag  (F_drag / m = q / β),  gravity (J2),  Coriolis, and
    centrifugal — the same physics as the main integrator but with no thrust
    and a constant ballistic coefficient in place of stage aerodynamics.

    Parameters
    ----------
    pos_ecef   : ECEF position at separation (m), shape (3,)
    vel_ecef   : ECEF velocity at separation (m/s), shape (3,)
    beta_kg_m2 : ballistic coefficient β = m / (Cd · A_eff) in kg/m²
    max_time_s : integration timeout (s)

    Returns
    -------
    impact_lat_deg  : geodetic latitude of debris impact (°)
    impact_lon_deg  : longitude of debris impact (°)
    flight_time_s   : time from separation to impact (s)
    impact_speed_ms : ECEF-frame speed at impact (m/s)
    """
    def _eom(t, state):
        pos, vel = state[:3], state[3:]
        _, _, alt = ecef_to_geodetic(pos)
        g     = gravity_ecef(pos)
        speed = np.linalg.norm(vel)
        if speed > 1e-6:
            _, _, rho, _ = atmosphere(max(alt, 0.0))
            q      = 0.5 * rho * speed ** 2
            a_drag = -(q / beta_kg_m2) * (vel / speed)
        else:
            a_drag = np.zeros(3)
        a_cor = coriolis_acceleration(vel)
        a_cen = centrifugal_acceleration(pos)
        return np.concatenate([vel, g + a_drag + a_cor + a_cen])

    def _ground(t, state):
        _, _, alt = ecef_to_geodetic(state[:3])
        return alt
    _ground.terminal  = True
    _ground.direction = -1

    state0 = np.concatenate([pos_ecef, vel_ecef])
    # Single pass: find the impact time with the event detector.  When the
    # caller wants the trajectory we request dense output and SAMPLE the same
    # integration's interpolant rather than re-integrating a second time — the
    # old code ran solve_ivp twice per debris piece, and debris was ~half of a
    # multi-stage run's cost.
    sol_ev = solve_ivp(_eom, (0.0, max_time_s), state0,
                       method='RK45', events=_ground,
                       rtol=1e-5, atol=10.0, dense_output=return_trajectory)

    # If the ground event never fired the stage did not impact within the
    # timeout — it is in orbit (or on a very long sub-orbital arc).  Return
    # None so the caller can skip the debris milestone rather than reporting
    # a spurious in-orbit position as a ground impact.
    if len(sol_ev.t_events[0]) == 0:
        return None

    t_impact = float(sol_ev.t_events[0][0])
    # Impact state from the event detector (exact terminal state).
    pos_f = sol_ev.y_events[0][0][:3]
    vel_f = sol_ev.y_events[0][0][3:]
    lat_f, lon_f, _ = ecef_to_geodetic(pos_f)
    result = (float(np.degrees(lat_f)),
              float(np.degrees(lon_f)),
              t_impact,
              float(np.linalg.norm(vel_f)))

    if not return_trajectory:
        return result

    # Smooth output on a regular 10-second grid, sampled from the SAME
    # integration's dense interpolant (no second integration).
    t_eval = np.append(np.arange(0.0, t_impact, 10.0), t_impact)
    ys = sol_ev.sol(t_eval)          # shape (6, N)

    d_lats, d_lons, d_alts = [], [], []
    for i in range(ys.shape[1]):
        la, lo, al = ecef_to_geodetic(ys[:3, i])
        d_lats.append(float(np.degrees(la)))
        d_lons.append(float(np.degrees(lo)))
        d_alts.append(float(al))
    traj = {
        't':   t_eval,
        'lat': np.array(d_lats),
        'lon': np.array(d_lons),
        'alt': np.array(d_alts),
    }
    return result + (traj,)


# ---------------------------------------------------------------------------
# Public integration interface
# ---------------------------------------------------------------------------

def integrate_trajectory(params: BoosterParams,
                         launch_lat_deg: float,
                         launch_lon_deg: float,
                         launch_azimuth_deg: float,
                         guidance: str = None,
                         burnout_angle_deg: float = None,
                         cutoff_time_s: float = None,
                         dt_output: float = 1.0,
                         max_time_s: float = 3600.0,
                         gt_turn_start_s: float = 5.0,
                         gt_turn_stop_s: float = None,
                         reentry_query_alt_km: float = None,
                         target_orbit_alt_km: float = None,
                         yaw_maneuvers: list = None,
                         launch_elevation_deg: float = None,
                         alpha_limit_deg: float = None,
                         alpha_induced_drag: bool = False,
                         terrain_dem: bool = False,
                         launch_elev_m: float = None,
                         stall_evals: int = STALL_EVAL_LIMIT,
                         _search_mode: bool = False):
    """
    Integrate a booster trajectory from launch to impact.

    Parameters
    ----------
    params                : BoosterParams
    launch_lat_deg        : geodetic launch latitude (degrees)
    launch_lon_deg        : launch longitude (degrees)
    launch_azimuth_deg    : launch azimuth clockwise from North (degrees)
    burnout_angle_deg        : burnout elevation above horizontal (°); defaults to
                            params.burnout_angle_deg
    cutoff_time_s         : engine cutoff time (s); defaults to full burn
    dt_output             : output time step (s)
    max_time_s            : maximum flight time (s)
    alpha_limit_deg       : sustained angle-of-attack envelope (°) enforced on
                            the commanded thrust direction while dynamic
                            pressure exceeds _ALPHA_GATE_Q_PA.  NASA SP-8099
                            §2.1.2.2 gives 5°–10° at max-q as the standard
                            preliminary-design envelope.  None/0 = no limit
                            (legacy behavior); commanded α is then only
                            reported/flagged, never constrained.
    alpha_induced_drag    : when True, the angle of attack develops an
                            aerodynamic normal force during boost whose
                            induced-drag component bleeds energy and reshapes q
                            (Jorgensen cross-flow build-up; see
                            _boost_alpha_aero_force).  Off by default so every
                            validated trajectory is byte-identical; the effect
                            is a pure increment that vanishes at α = 0.
    terrain_dem           : when True, the trajectory starts at the launch
                            site's real ground elevation and terminates on real
                            terrain height (terrain.py bundled coarse grid —
                            offline, no network inside the integrator).  Off by
                            default = flat sea-level Earth, byte-identical to
                            the legacy dynamics and the Forden benchmarks.
    launch_elev_m         : precise launch-pad elevation (m) to use instead of
                            the coarse-grid sample — e.g. the hi-res value
                            baked into launch_sites.json.  Only read when
                            terrain_dem is True; None = sample the grid.

    Returns
    -------
    result : dict with keys
        't'         : time array (s)
        'lat'       : geodetic latitude array (deg)
        'lon'       : longitude array (deg)
        'alt'       : altitude array (m)
        'speed'     : speed array (m/s)
        'range'     : downrange distance from launch (m)
        'pos_ecef'  : (N,3) ECEF positions (m)
        'vel_ecef'  : (N,3) ECEF velocities (m/s)
        'impact_lat': impact latitude (deg)
        'impact_lon': impact longitude (deg)
        'range_km'  : total range (km)
        'apogee_km' : maximum altitude (km)
    """
    import copy
    # The booster owns the separation link (body_reenters): stamp it onto the
    # reentry object up front so every reader of ro.separation_mode below
    # agrees with the booster.  Copies only when a change is needed.
    params = bind_ro_separation(params)
    # A chain flown with a reentry object carries that object's mass.  Booster
    # files are stack-only, so a caller that set params.ro without composing
    # (compose_loadout) would fly the boost without the front end and coast
    # on the empty stage.  compose_loadout is idempotent through the run-time
    # payload_kg record, so a chain the GUI already composed is untouched.
    if (params.ro is not None
            and float(getattr(params, 'payload_kg', 0.0) or 0.0) <= 0.0):
        _n = max(1, int(getattr(params, 'num_ros', 1) or 1))
        params = compose_loadout(params, params.ro, _n)
    # Apply session-level overrides non-destructively.  guidance and
    # burnout_angle_deg are flight parameters (like launch site) that the caller
    # may override independently of the stored booster definition.
    if guidance is not None or burnout_angle_deg is not None or launch_elevation_deg is not None:
        params = copy.copy(params)
        if guidance is not None:
            params.guidance = guidance
        if burnout_angle_deg is not None:
            params.burnout_angle_deg = burnout_angle_deg
        if launch_elevation_deg is not None:
            params.launch_elevation_deg = launch_elevation_deg

    # Auto-derive the no-separation (body) ballistic coefficient β from geometry
    # when left at the sentinel 0.  For a body the WHOLE airframe sets the drag,
    # so β = m / (Cd0_body(M)·A_base) is a β(Mach) TABLE — like the L/D table
    # below — not a scalar: there is no single-Mach β for a Mach-varying body
    # Cd0 (FRONT_END_DESIGN.md §10).  Independent of the glide settings (β
    # governs any body's drag, gliding or ballistic).  A separating RV, or a
    # body with β entered > 0, keeps its scalar β untouched.
    _derived_beta_ref = None      # ref-Mach derived β for the result/report
    _bro = params.ro
    if (_bro is not None
            and getattr(_bro, 'separation_mode', 'separating_ro') == 'body'
            and getattr(_bro, 'reentry_attitude', 'trim') != 'tumbling'
            and float(getattr(_bro, 'beta_kg_m2', 0.0) or 0.0) <= 0.0):
        try:
            import glider_ld as _gld
            import dataclasses as _dcb
            _blast = _gld._last_stage(params)
            _bmass = float(effective_ro(params).mass_kg)
            _bAref = np.pi * (float(_blast.diameter_m) / 2.0) ** 2
            if _bmass > 0.0 and _bAref > 0.0:
                _bm = np.array([1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 12.0])
                _bv = np.array([
                    _bmass / (max(float(_gld.body_cd0(params, _M)), 1e-6) * _bAref)
                    for _M in _bm])
                if np.all(np.isfinite(_bv)) and np.all(_bv > 0.0):
                    params = copy.copy(params)
                    params._beta_of_mach = (lambda M, _x=_bm, _y=_bv:
                                            float(np.interp(M, _x, _y)))
                    # Scalar fallback at the reference Mach (analytic paths /
                    # any non-table read / the reports).
                    _derived_beta_ref = float(
                        np.interp(_gld.GLIDE_MACH_REF, _bm, _bv))
                    params.ro = _dcb.replace(_bro,
                                             beta_kg_m2=_derived_beta_ref)
        except Exception:
            pass

    # Auto-derive the no-separation (body) glider L/D from geometry when it was
    # left at the sentinel 0.  For a no-sep body the airframe IS the glider, so
    # its (L/D)_max follows from the whole-booster build-up (glider_ld.py:
    # Jorgensen + Allen-Perkins + N-K-P).  A SEPARATING RV keeps its own
    # designed glider_LD; any body whose glider_LD was set >0 is untouched.
    #
    # The static-margin / trim gate (trim_gate.py) decides whether that L/D is
    # ACHIEVABLE: an unstable body (CP ahead of CG) can't hold a trim AoA -> it
    # tumbles (attitude forced to 'tumbling', so effective_ro derives a tumbling
    # β and kills lift); an over-stable / weak-control body is limited to the
    # L/D its control authority can trim to, not the aerodynamic peak.
    _reentry_trim = None
    _ro = params.ro
    if (_ro is not None
            and getattr(_ro, 'separation_mode', 'separating_ro') == 'body'
            and getattr(_ro, 'reentry_attitude', 'trim') == 'trim'
            and getattr(_ro, 'glider_enabled', False)
            and float(getattr(_ro, 'glider_LD', 0.0)) <= 0.0):
        try:
            import glider_ld
            import trim_gate as _tg
            import dataclasses as _dc
            _cg_ovr = float(getattr(_ro, 'reentry_cg_m', 0.0) or 0.0)
            _g = _tg.trim_gate(params, mach=glider_ld.GLIDE_MACH_REF,
                               x_cg_m=(_cg_ovr if _cg_ovr > 0.0 else None))
            if not _g.get("error"):
                _reentry_trim = {
                    'static_margin_cal': _g['static_margin_cal'],
                    'LD_max': _g['LD_max'], 'LD_achievable': _g['LD_achievable'],
                    'alpha_trim_max_deg': _g['alpha_trim_max_deg'],
                    'alpha_glide_deg': _g.get('alpha_glide_deg'),
                    # Control authority the gate actually used, and whether it
                    # was assumed — a reported glide that rests on the 'unknown'
                    # default must say so in the run record, not just in the GUI.
                    'delta_max_deg': _g.get('delta_max_deg'),
                    'control_tier': _g.get('control_tier'),
                    'control_assumed': _g.get('control_assumed'),
                    'tumbles': _g.get('tumbles'),
                    'trim_unbounded': _g.get('trim_unbounded'),
                    'verdict': _g['verdict'],
                }
                params = copy.copy(params)
                if _g.get('tumbles'):
                    # Statically UNSTABLE -> cannot hold an attitude -> tumbles.
                    # effective_ro's tumbling branch will derive the ballistic
                    # coefficient and zero the lift.  The nose-first β table no
                    # longer applies (the body is not nose-first): drop it so the
                    # tumbling β wins, and clear the reported derived-β so the
                    # result stays honest.
                    params.ro = _dc.replace(_ro, reentry_attitude='tumbling')
                    params._beta_of_mach = None
                    _derived_beta_ref = None
                elif _g['LD_achievable'] <= 0.0:
                    # STABLE but nothing can command an incidence (fixed control
                    # surfaces, or no trimmed attitude at full deflection).  The
                    # body still flies NOSE-FIRST: it just makes no lift.  Zero
                    # the glide and leave the attitude — and therefore the
                    # nose-first β and its Mach table — exactly as they are.
                    # Forcing 'tumbling' here would hand a fin-stabilised
                    # ballistic body a tumbling-cylinder drag it does not have.
                    params.ro = _dc.replace(_ro, glider_enabled=False,
                                            glider_LD=0.0)
                else:
                    # Mach-varying (L/D)_max: sample the geometry build-up over
                    # a Mach grid, capped by the control-achievable L/D, and
                    # stash an interpolator on params for the numerical glide
                    # EOM.  np.interp holds the endpoints, so below M1.5 (where
                    # the linear wing theory is invalid) the M1.5 value is used.
                    _ceil = float(_g['LD_achievable'])
                    _machs = [1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 12.0]
                    _lds = []
                    for _M in _machs:
                        try:
                            _lm = float(glider_ld.whole_booster_LD(
                                params, mach=_M).get('ld_max', 0.0))
                        except Exception:
                            _lm = _ceil
                        _lds.append(min(_lm, _ceil) if _lm > 0 else _ceil)
                    _ma = np.asarray(_machs); _la = np.asarray(_lds)
                    params._ld_of_mach = (lambda M, _x=_ma, _y=_la:
                                          float(np.interp(M, _x, _y)))
                    # Scalar fallback (analytical modes / any non-table read):
                    # the reference-Mach value.
                    params.ro = _dc.replace(
                        _ro, glider_LD=float(np.interp(
                            glider_ld.GLIDE_MACH_REF, _ma, _la)))
            else:
                # Gate could not evaluate (no geometry) — fall back to the raw
                # aerodynamic L/D so a configured glider still glides.
                _ld = glider_ld.derive_glider_LD(params)
                if _ld > 0.0:
                    params = copy.copy(params)
                    params.ro = _dc.replace(_ro, glider_LD=_ld)
        except Exception:
            pass   # leave glider_LD at 0; glide modes will treat it as no lift

    total_burn = total_burn_time(params)
    if cutoff_time_s is None:
        cutoff_time_s = total_burn

    if not hasattr(params, '__dict__'):
        params = copy.copy(params)
    # Angle-of-attack envelope for the boost guidance (SP-8099).  Stashed on
    # params (like the latches below) so _commanded_thrust_dir — shared by the
    # EOM and the guidance-program plot — sees it without changing the
    # eom_args tuple shape used by many call sites.  None/0 = no limit.
    params._alpha_limit_deg = (float(alpha_limit_deg)
                               if alpha_limit_deg else None)
    # Running ascent max-q (Pa), the reference for the constant-q·α envelope.
    # Updated every EOM call; settled by the time any dogleg needs clamping.
    params._maxq_pa = [0.0]
    # α-induced boost aero (normal force + induced drag).  Opt-in; default off
    # is byte-identical to the legacy dynamics.
    params._alpha_induced_drag = bool(alpha_induced_drag)
    # Terrain DEM: when on, launch from real ground elevation and terminate the
    # trajectory on real ground height (terrain.py coarse grid — offline, no
    # network inside the integrator).  Opt-in; default off = flat sea-level
    # Earth, byte-identical to the legacy dynamics and the Forden benchmarks.
    params._terrain_dem = bool(terrain_dem)
    # Commanded pull-up phase latch [0 fall | 1 pulling | 2 handed off] —
    # one-way per mission; persists across integration passes, reset here.
    params._pullup_phase = [0]
    # [furthest t reached, consecutive evaluations since it last advanced].
    # _eom keeps it; see IntegratorStalled.
    params._stall_watch = [float('-inf'), 0,
                           (stall_evals if stall_evals and stall_evals > 0
                            else float('inf'))]
    # Shroud heating-jettison latch [armed, jettisoned, t_jettison], used only
    # when shroud_jettison_alt_km <= 0 (heating default).  armed once q_dot has
    # risen above the fairing flux (past max-q); jettisoned on the first drop
    # back below it.  Latched — never re-attaches on reentry.
    params._shroud_latch = [False, False, None]
    params._glider_phase1   = False     # True during pre-apogee Phase 1

    # Compute the mission-elapsed time at which the final stage ignites.
    # This is the sum of all earlier stage burn times and coast times.
    # Used only by the orbital_insertion two-phase pitch program.
    _t_final_ignition = 0.0
    _node = params
    while _node.stage2 is not None:
        _t_final_ignition += _node.burn_time_s + _node.coast_time_s
        _node = _node.stage2

    if gt_turn_stop_s is None:
        if params.guidance == "orbital_insertion" and _t_final_ignition > 0:
            # End the boost pitch just before the final stage ignites so the
            # pre-final stages complete their pitch-over before handoff.
            gt_turn_stop_s = max(_t_final_ignition - 1.0, gt_turn_start_s + 1.0)
        else:
            gt_turn_stop_s = total_burn

    lat0 = np.radians(launch_lat_deg)
    lon0 = np.radians(launch_lon_deg)
    az   = np.radians(launch_azimuth_deg)

    # Initial position on surface; initial velocity: small nudge along the
    # launch direction so the integrator starts above ground.  With the DEM on,
    # start at the launch site's real elevation (the caller's precise baked
    # value when given, else the coarse grid); flat sea level otherwise.
    if terrain_dem:
        import terrain as _terrain
        _launch_elev = (float(launch_elev_m) if launch_elev_m is not None
                        else _terrain.ground_elevation(launch_lat_deg, launch_lon_deg,
                                                       hi_res=False))
    else:
        _launch_elev = 0.0
    pos0 = geodetic_to_ecef(lat0, lon0, _launch_elev)
    e_east0, e_north0, e_up0 = _enu_frame(lat0, lon0)
    el0  = np.radians(params.launch_elevation_deg)
    launch_dir = (np.cos(el0) * np.sin(az) * e_east0 +
                  np.cos(el0) * np.cos(az) * e_north0 +
                  np.sin(el0) * e_up0)
    v0 = 10.0 * launch_dir

    state0 = np.concatenate([pos0, v0])

    t_span    = (0.0, max_time_s)
    _target_orbit_alt_m = (target_orbit_alt_km * 1000.0
                           if target_orbit_alt_km is not None else 0.0)
    _yaw_maneuvers = yaw_maneuvers or None
    eom_args  = (params, cutoff_time_s, az, gt_turn_start_s,
                 gt_turn_stop_s, _target_orbit_alt_m, _t_final_ignition,
                 _yaw_maneuvers)

    if _search_mode:
        # Loose tolerances — we only need range_km, not a smooth trajectory.
        # Skipping t_eval avoids building and interpolating thousands of output
        # points, and larger max_step lets the integrator stride faster through
        # the coasting arc.
        sol = solve_ivp(
            fun=_eom,
            t_span=t_span,
            y0=state0,
            method='RK45',
            t_eval=None,
            events=_hit_ground,
            args=eom_args,
            rtol=1e-5,
            atol=1e-3,
            dense_output=False,
            max_step=30.0,
        )
        # Fast-path return.
        orbital = len(sol.t_events[0]) == 0
        if orbital:
            # Perigee check — weed out long sub-orbital arcs.
            _oe_s = orbital_elements_from_state(sol.y[:3, -1], sol.y[3:, -1])
            if _oe_s['perigee_km'] < 80.0:
                orbital = False
        if orbital:
            return {'orbital': True, 'range_km': None,
                    'perigee_km': _oe_s['perigee_km'],
                    'apogee_km':  _oe_s['apogee_km']}
        if sol.y_events[0].shape[0] == 0:
            return {'orbital': False, 'range_km': None,
                    'perigee_km': None, 'apogee_km': None}
        pos_impact = sol.y_events[0][0, :3]
        la_f, lo_f, _ = ecef_to_geodetic(pos_impact)
        rng_km = range_between(lat0, lon0, la_f, lo_f) / 1000.0
        return {'orbital': False, 'range_km': rng_km,
                'perigee_km': None, 'apogee_km': None}

    # Full-fidelity integration for display/export.
    # When glider mode is on, the post-burnout phase develops phugoid
    # skip-glide oscillations that the default 1e-8 / max_step=5 s tolerances
    # try to resolve to absurd precision (taking minutes per skip cycle).
    # Loosen them: a Tracy/Wright glide is already an idealisation; sub-metre
    # altitude precision over a 10 km skip is meaningless.
    t_eval = np.arange(0.0, max_time_s, dt_output)
    _ero_full = effective_ro(params)
    if _ero_full is not None and _ero_full.glider_enabled and _ero_full.glider_LD > 0:
        _rtol, _atol, _maxstep = 1e-5, 1e-2, 20.0
    else:
        _rtol, _atol, _maxstep = 1e-8, 1e-6, 5.0
    # Target-proximity dive trigger needs sub-step granularity because the
    # vehicle covers ~80 km per default 20-s glider step at HGV speeds —
    # easy to leap over a small radius.  Tighten max_step to ~2 s so the
    # spatial granularity is ~6–8 km, which is sufficient for radii ≥ 10 km.
    _target_trigger_active = (
        _ero_full is not None
        and _ero_full.glider_enabled
        and getattr(_ero_full, 'glider_dive_target_radius_km', 0.0) > 0.0)
    if _target_trigger_active:
        _maxstep = min(_maxstep, 2.0)
    # Boost-glide modes with an analytical Acton pull-up arc applied at
    # the pierce point.  Two flavours:
    #   • equilibrium_glide        — Tracy 2020.  Two-phase: ballistic +
    #                                pierce → analytical arc → glide.
    #   • equilibrium_glide_acton  — Acton 2015 three-phase.  Adds a
    #                                direct-re-entry segment with β_S
    #                                drag and zero lift between the
    #                                100 km pierce point (t₂) and the
    #                                Phase-3→4 transition altitude
    #                                h_3 (t₃), where the analytical
    #                                pull-up arc starts.
    _pullup_mode = (_ero_full is not None
                    and _ero_full.glider_enabled
                    and _ero_full.glider_LD > 0
                    and _ero_full.glider_guidance in
                        ("equilibrium_glide", "equilibrium_glide_acton"))
    # Acton three-phase requires β_S > 0; otherwise we fall back to Tracy
    # (one-shot arc at the pierce point) so the user always gets an
    # analytical pull-up rather than a phugoid.
    _acton_mode = (_pullup_mode
                   and _ero_full.glider_guidance == "equilibrium_glide_acton"
                   and _ero_full.glider_beta_entry_kg_m2 > 0)
    # Hybrid mode: phugoid skip-glide for N upward crossings of the
    # equilibrium speed curve, then one-way switch to equilibrium-glide EOM.
    _skip_to_eq_mode = (_ero_full is not None
                        and _ero_full.glider_enabled
                        and _ero_full.glider_LD > 0
                        and _ero_full.glider_guidance == "skip_to_equilibrium")

    # Apogee event: r̂·v crosses zero descending (ascending → descending).
    # Used to split Phase 1 (glider off, pre-apogee) from Phase 2 (glider
    # on, post-apogee).  Gated on t > total_burn so it never fires during
    # powered flight.
    _t_apo_gate = total_burn
    def _apogee_event(t, s, *_,
                      _gate=_t_apo_gate):
        if t <= _gate:
            return 1.0
        r, v = s[:3], s[3:]
        rmag = float(np.linalg.norm(r))
        if rmag < 1.0:
            return 1.0
        return float(np.dot(r, v) / rmag)
    _apogee_event.terminal  = True
    _apogee_event.direction = -1   # r̂·v: + → −  (ascending → descending)

    # Mission-elapsed times of the analytical pull-up arc start and the
    # equilibrium-glide start, captured below for use by the milestone
    # logger.  These are the only points in the analytical glide that are
    # not detectable from altitude extrema (the post-pull-up profile is
    # monotone), so they have to be emitted explicitly.
    _t_ms_pullup_start = None
    _t_ms_glide_start  = None

    if _pullup_mode:
        sol_pre = solve_ivp(
            fun=_eom,
            t_span=t_span,
            y0=state0,
            method='RK45',
            t_eval=t_eval,
            events=[_hit_ground, _glider_pierce_atmosphere],
            args=eom_args,
            rtol=_rtol,
            atol=_atol,
            dense_output=False,
            max_step=_maxstep,
        )
        _pierce_fired = (len(sol_pre.t_events[1]) > 0
                         and (len(sol_pre.t_events[0]) == 0
                              or sol_pre.t_events[1][0] <
                                 sol_pre.t_events[0][0]))
        if _pierce_fired:
            t_pierce     = float(sol_pre.t_events[1][0])
            state_pierce = sol_pre.y_events[1][0]
            # Acton's/Tracy's β_L is the ballistic coefficient IN GLIDE TRIM,
            # β_L = m/(C_D,glide·A).  `beta_kg_m2` is stored zero-lift (the
            # polar's convention, C_D0 = m/(β·A)), and at the max-L/D trim
            # C_D = 2·C_D0, so β_L = β_zerolift / 2 (labeled INFERENCE — Acton
            # gives no β_L formula, only a fit).  This keeps ONE meaning for
            # `beta_kg_m2` across the numerical polar and the analytic modes;
            # e.g. HTV-2's zero-lift β = 26,000 → β_L = 13,000, reproducing
            # Acton 2015 Table 3.  METHODS §12.0.3.
            beta_L = float(_ero_full.beta_kg_m2) / 2.0
            LD     = float(_ero_full.glider_LD)
            H    = ACTON_SCALE_HEIGHT_M
            rho0 = ACTON_SEA_LEVEL_RHO

            # ---- Acton Phase 3: analytical constant-γ drag descent ----------
            if _acton_mode:
                beta_S  = float(_ero_full.glider_beta_entry_kg_m2)
                v2      = float(np.linalg.norm(state_pierce[3:]))
                rmag    = float(np.linalg.norm(state_pierce[:3]))
                v_hat_p = state_pierce[3:] / max(v2, 1e-9)
                r_hat_p = state_pierce[:3] / rmag
                sin_g2  = float(np.dot(v_hat_p, r_hat_p))
                theta_2 = (float(np.arcsin(min(1.0, max(-1.0, -sin_g2))))
                           if sin_g2 < 0 else 0.0)
                g_p     = float(np.linalg.norm(gravity_ecef(state_pierce[:3])))

                # Fixed-point iteration: h_3 ↔ V_3 ↔ h_eq  (Acton Eq. 8)
                V_3 = v2
                h_3 = float(ACTON_PIERCE_ALT_M)
                for _ in range(25):
                    V_4t = V_3 * float(np.exp(-theta_2 / LD))
                    if V_4t < 100.0:
                        break
                    ra_t = g_p - V_4t**2 / rmag
                    if ra_t <= 0.0:
                        break
                    rho_eq_t = 2.0 * beta_L * ra_t / (V_4t**2 * LD)
                    h_eq_t   = H * float(np.log(rho0 / max(rho_eq_t, 1e-30)))
                    h_3t     = h_eq_t + H * float(np.log(max(beta_L / beta_S, 1.0)))
                    h_3t     = min(h_3t, float(ACTON_PIERCE_ALT_M) - 1.0)
                    rho_h3t  = rho0 * float(np.exp(-h_3t / H))
                    V_3n     = v2 * float(np.exp(
                        -H * rho_h3t / (2.0 * beta_S
                                        * max(float(np.sin(theta_2)), 1e-9))))
                    if abs(V_3n - V_3) < 0.1:
                        V_3 = V_3n; h_3 = h_3t; break
                    V_3 = V_3n; h_3 = h_3t

                # Build Phase 3 ECEF samples for visualisation
                lat_p, lon_p, h_2m = ecef_to_geodetic(state_pierce[:3])
                e_east_p, e_north_p, _ = _enu_frame(lat_p, lon_p)
                v_horiz_p = state_pierce[3:] - sin_g2 * v2 * r_hat_p
                v_hm_p    = float(np.linalg.norm(v_horiz_p))
                if v_hm_p > 1.0:
                    _vhh = v_horiz_p / v_hm_p
                    az_p = float(np.arctan2(float(np.dot(_vhh, e_east_p)),
                                            float(np.dot(_vhh, e_north_p))))
                else:
                    az_p = 0.0
                sin_az_p  = float(np.sin(az_p)); cos_az_p  = float(np.cos(az_p))
                sin_lat_p = float(np.sin(lat_p)); cos_lat_p = float(np.cos(lat_p))
                _sin_t2   = max(float(np.sin(theta_2)), 1e-9)
                _cos_t2   = float(np.cos(theta_2))
                _Re_p     = 6_371_000.0
                _h_pts    = np.linspace(float(h_2m), float(h_3), 21)[1:]
                p3_samps  = []
                _pt3 = 0.0; _pV3 = v2; _ph3 = float(h_2m)
                for _hi in _h_pts:
                    _ri   = rho0 * float(np.exp(-_hi / H))
                    _Vi   = v2 * float(np.exp(-H * _ri / (2.0 * beta_S * _sin_t2)))
                    _dr_i = (float(h_2m) - _hi) * _cos_t2 / _sin_t2
                    _ti   = _pt3 + (_ph3 - _hi) / (0.5 * (_pV3 + _Vi) * _sin_t2)
                    _drad = _dr_i / _Re_p
                    _sd, _cd = float(np.sin(_drad)), float(np.cos(_drad))
                    _sl2  = sin_lat_p * _cd + cos_lat_p * _sd * cos_az_p
                    _lai  = float(np.arcsin(max(-1.0, min(1.0, _sl2))))
                    _loi  = lon_p + float(np.arctan2(sin_az_p * _sd * cos_lat_p,
                                                      _cd - sin_lat_p * _sl2))
                    _pi   = geodetic_to_ecef(_lai, _loi, _hi)
                    _ee, _en, _eu = _enu_frame(_lai, _loi)
                    _fwd  = sin_az_p * _ee + cos_az_p * _en
                    _vi   = _Vi * (_cos_t2 * _fwd - _sin_t2 * _eu)
                    p3_samps.append((_ti, _pi, _vi))
                    _pt3 = _ti; _pV3 = _Vi; _ph3 = _hi

                if p3_samps:
                    t_arc_start     = t_pierce + p3_samps[-1][0]
                    state_arc_start = np.concatenate([p3_samps[-1][1],
                                                      p3_samps[-1][2]])
                else:
                    t_arc_start     = t_pierce
                    state_arc_start = state_pierce
            else:
                # Tracy mode: arc starts directly at the pierce point
                p3_samps        = []
                t_arc_start     = t_pierce
                state_arc_start = state_pierce

            # ---- Phase 4: analytical pull-up arc ----------------------------
            arc_samples, t_pullup, state_post = _acton_pullup_arc(
                state_arc_start[:3], state_arc_start[3:], LD, beta_L)
            t_glide_start = t_arc_start + t_pullup

            # Capture the mission-elapsed times of the analytical pull-up
            # arc start and the equilibrium-glide start for the milestone
            # logger.  These are emitted unconditionally for analytical
            # modes because the post-arc altitude profile is monotone
            # (no extrema to detect).
            _t_ms_pullup_start = float(t_arc_start)
            _t_ms_glide_start  = float(t_glide_start)

            # ---- Phase 5: equilibrium glide (Tracy / Acton) ----------------
            # A commanded dive altitude > 0 ends the analytical glide there;
            # 0 (= glide to impact) keeps the glide down to the 30 km validity
            # floor of Acton's exponential-atmosphere fit, below which the
            # ballistic-descent handoff carries the trajectory to the ground.
            _h_term = (float(_ero_full.glider_terminal_alt_km) * 1e3
                       if (_ero_full.glider_terminal_dive
                           and _ero_full.glider_terminal_alt_km > 0)
                       else 30_000.0)
            # The analytic family is purely analytic: banking and dive-at-
            # target are NUMERICAL-family capabilities (the closed-form turn
            # rate ∝ g − V²/r → 0 hypersonically, and the formula has no
            # ground-target concept), so the family-scoped plan editor never
            # offers them on an analytic plan.  The old silent fallback that
            # swapped in the numerical EOM when a bank schedule or dive
            # trigger appeared on an analytic run is deleted; any such fields
            # left in legacy data are ignored here (a one-shot migration
            # rewrites those plans to the numerical family).
            # See REENTRY_FAMILY_DESIGN.md.

            # When the analytical pull-up arc returned no samples (shallow
            # pierce angle below 3° → degenerate arc geometry), the
            # analytical equilibrium-glide formula would teleport the vehicle
            # from the pierce altitude (~100 km) to h_eq(V_pierce) (~60 km),
            # creating a non-physical altitude jump in plots.  Run a brief
            # numerical-EOM bridge from the pierce state until altitude
            # reaches ~h_eq + 2 km, then hand off to the analytical glide.
            # This preserves Tracy/Acton's analytical solution for the long-
            # range portion while keeping the descent visually continuous.
            _bridge_t = np.empty(0)
            _bridge_pos = np.empty((0, 3))
            _bridge_vel = np.empty((0, 3))
            if len(arc_samples) == 0:
                # Estimate target equilibrium altitude h_eq from V_pierce.
                _vp_mag = float(np.linalg.norm(state_pierce[3:]))
                _r_mag  = float(np.linalg.norm(state_pierce[:3]))
                _g_p    = float(np.linalg.norm(gravity_ecef(state_pierce[:3])))
                _ra_p   = _g_p - _vp_mag * _vp_mag / _r_mag
                if _ra_p > 0.0:
                    _rho_eq_b = (2.0 * beta_L * _ra_p
                                 / (_vp_mag * _vp_mag * LD))
                    _h_eq_b   = (ACTON_SCALE_HEIGHT_M
                                 * float(np.log(ACTON_SEA_LEVEL_RHO
                                                / max(_rho_eq_b, 1e-30))))
                    _h_target = max(_h_eq_b + 2_000.0, 30_000.0)

                    def _bridge_done(_t, _s, *_a, _ht=_h_target):
                        _, _, _h = ecef_to_geodetic(_s[:3])
                        return float(_h) - float(_ht)
                    _bridge_done.terminal  = True
                    _bridge_done.direction = -1

                    _sol_br = solve_ivp(
                        _eom, (t_pierce, t_pierce + 200.0),
                        np.concatenate([state_pierce[:3], state_pierce[3:]]),
                        method='RK45',
                        events=[_hit_ground, _bridge_done],
                        args=eom_args,
                        rtol=_rtol, atol=_atol,
                        dense_output=False, max_step=2.0)
                    if _sol_br.y.shape[1] > 1:
                        _bridge_t   = _sol_br.t[1:]   # drop pierce sample (already in pre)
                        _bridge_pos = _sol_br.y[:3, 1:].T
                        _bridge_vel = _sol_br.y[3:, 1:].T
                        # Hand off the analytical glide from the bridge endpoint.
                        state_post   = _sol_br.y[:, -1]
                        t_glide_start = float(_sol_br.t[-1])
                        _t_ms_pullup_start = float(t_pierce)
                        _t_ms_glide_start  = float(t_glide_start)

            _t_gl_rel, _pos_gl, _vel_gl = _analytical_equil_glide(
                state_post[:3], state_post[3:], beta_L, LD, _h_term,
                bank_schedule=None,
                t_offset=t_glide_start)
            _t_gl_abs = _t_gl_rel + t_glide_start

            # _analytical_equil_glide returns a single point when the
            # pierce speed is below the equilibrium-glide terminal speed
            # — e.g. a quasi-ballistic booster (quasi-ballistic body) that just
            # clipped 100 km rather than arriving at hypersonic glide
            # conditions.  Fall back to the full EOM with lift so we get
            # a physically correct skip-glide trajectory rather than a
            # no-lift ballistic plunge.
            _glide_degenerate = (len(_t_gl_rel) <= 1)

            # ---- Terminal dive / fallback from glide endpoint to ground ------
            _, _, _h_gl_end = ecef_to_geodetic(_pos_gl[-1])
            if _h_gl_end > 500.0:
                _t0_td = float(_t_gl_abs[-1])
                _s0_td = np.concatenate([_pos_gl[-1], _vel_gl[-1]])

                if _glide_degenerate:
                    # Analytical glide was degenerate — run full EOM with lift
                    # (equivalent to skip_glide from the pierce/arc-start point).
                    _sol_td = solve_ivp(
                        _eom, (_t0_td, _t0_td + 3600.0), _s0_td,
                        method='RK45', events=_hit_ground, args=eom_args,
                        rtol=_rtol, atol=_atol,
                        dense_output=False, max_step=_maxstep)
                else:
                    def _eom_td(t, s, _bL=beta_L):
                        _p, _v = s[:3], s[3:]
                        _, _, _alt = ecef_to_geodetic(_p)
                        _gv  = gravity_ecef(_p)
                        _spd = float(np.linalg.norm(_v))
                        if _spd > 1e-6:
                            _, _, _rho, _ = atmosphere(max(float(_alt), 0.0))
                            _ad = -(0.5 * _rho * _spd / _bL) * _v
                        else:
                            _ad = np.zeros(3)
                        return np.concatenate(
                            [_v, _gv + _ad
                             + coriolis_acceleration(_v)
                             + centrifugal_acceleration(_p)])

                    def _td_gnd(t, s):
                        _, _, _alt = ecef_to_geodetic(s[:3])
                        return float(_alt)
                    _td_gnd.terminal  = True
                    _td_gnd.direction = -1

                    _sol_td = solve_ivp(
                        _eom_td, (_t0_td, _t0_td + 600.0), _s0_td,
                        method='RK45', events=_td_gnd,
                        rtol=_rtol, atol=_atol,
                        dense_output=False, max_step=_maxstep)

                if _sol_td.y.shape[1] > 1:
                    _t_gl_abs = np.concatenate([_t_gl_abs, _sol_td.t[1:]])
                    _pos_gl   = np.vstack([_pos_gl, _sol_td.y[:3, 1:].T])
                    _vel_gl   = np.vstack([_vel_gl, _sol_td.y[3:, 1:].T])

            _glide_y  = np.vstack([_pos_gl.T, _vel_gl.T])   # 6 × N
            orbital   = False

            # ---- Build Phase 4 arc arrays -----------------------------------
            if arc_samples:
                _arc_t = np.concatenate([
                    [t_arc_start],
                    [t_arc_start + s[0] for s in arc_samples]])
                _anchor = np.concatenate(
                    [state_arc_start[:3],
                     state_arc_start[3:]]).reshape(6, 1)
                _arc_y = np.concatenate([
                    _anchor,
                    np.column_stack([np.concatenate([s[1], s[2]])
                                     for s in arc_samples])
                ], axis=1)
            else:
                _arc_t = np.empty(0)
                _arc_y = np.empty((6, 0))

            # ---- Assemble full trajectory ------------------------------------
            _pre_mask = sol_pre.t < t_pierce
            _pre_t    = sol_pre.t[_pre_mask]
            _pre_y    = sol_pre.y[:, _pre_mask]
            if p3_samps:
                _p3_t = np.array([t_pierce + s[0] for s in p3_samps])
                _p3_y = np.column_stack(
                    [np.concatenate([s[1], s[2]]) for s in p3_samps])
            else:
                _p3_t = np.empty(0)
                _p3_y = np.empty((6, 0))
            # Bridge samples (numerical descent from pierce to ~h_eq) — only
            # populated when the arc returned fallback for shallow γ pierce.
            if _bridge_t.size > 0:
                _br_y = np.vstack([_bridge_pos.T, _bridge_vel.T])  # 6 × N
            else:
                _br_y = np.empty((6, 0))
            t_arr   = np.concatenate([_pre_t, _p3_t, _arc_t,
                                      _bridge_t, _t_gl_abs])
            sol_y   = np.concatenate([_pre_y, _p3_y, _arc_y,
                                      _br_y, _glide_y],
                                     axis=1)
            pos_arr = sol_y[:3].T
            vel_arr = sol_y[3:].T
        else:
            t_arr   = sol_pre.t
            pos_arr = sol_pre.y[:3].T
            vel_arr = sol_pre.y[3:].T
            orbital = (len(sol_pre.t_events[0]) == 0)
    elif _skip_to_eq_mode:
        # Phugoid skip-glide until N upward crossings of the equilibrium speed
        # curve v_eq²(h) = 2β·g⊥/(ρ·L/D), then one-way switch to
        # equilibrium-glide EOM.  An "upward crossing" is when δ = v²−v_eq²
        # goes from + to − while the vehicle is ascending; this corresponds
        # to scipy event direction = −1.
        _n_target  = max(1, int(getattr(_ero_full, 'glider_skip_count', 1)))
        _beta_ste  = float(_ero_full.beta_kg_m2)
        _LD_ste    = float(_ero_full.glider_LD)

        # Earliest time the equilibrium-crossing event is eligible to fire.
        # For a separating RV the vehicle is still attached to the last stage
        # until total_burn; for a body-mode vehicle, engine cutoff is enough.
        _is_separating = (getattr(_ero_full, 'separation_mode', 'separating_ro')
                          == 'separating_ro')
        _t_eligible = total_burn if _is_separating else cutoff_time_s

        _t_handoff = None
        _s_handoff = None

        # Phase 0 — glider disabled; integrate from launch to apogee.
        # This makes the pre-apogee arc mode-independent (purely ballistic)
        # for all aero modes, then seeds the skip loop from the apogee state.
        params._glider_phase1 = True
        _sol_pre_ste = solve_ivp(
            _eom, (0.0, max_time_s), state0,
            method='RK45',
            t_eval=t_eval,
            events=[_hit_ground, _apogee_event],
            args=eom_args,
            rtol=_rtol, atol=_atol,
            dense_output=False, max_step=_maxstep,
        )
        params._glider_phase1 = False

        _apo_fired_ste = (len(_sol_pre_ste.t_events[1]) > 0
                          and (len(_sol_pre_ste.t_events[0]) == 0
                               or (_sol_pre_ste.t_events[1][0] <
                                   _sol_pre_ste.t_events[0][0])))
        if _apo_fired_ste:
            _t_now = float(_sol_pre_ste.t_events[1][0])
            _s_now = _sol_pre_ste.y_events[1][0].copy()
        else:
            _t_now = 0.0
            _s_now = state0.copy()

        _segs_t   = [_sol_pre_ste.t]
        _segs_pos = [_sol_pre_ste.y[:3].T]
        _segs_vel = [_sol_pre_ste.y[3:].T]

        for _skip_i in range(_n_target if _apo_fired_ste else 0):
            _te_seg  = t_eval[t_eval >= _t_now]

            # Re-define the event each iteration so the flags are fresh.
            # The handoff fires on the ASCENDING LEG when v² first drops
            # below v_eq²(h) = 2β·g⊥/(ρ·L/D).  That is exactly the
            # altitude and speed at which equilibrium glide is correct.
            # The flight path angle at the crossing is non-zero (vehicle
            # still climbing), so the handoff state is immediately corrected
            # to γ = 0 before passing it to the equilibrium-glide EOM —
            # see the FPA correction below.  In the limit of many damped
            # skips the FPA at the crossing converges to zero anyway; the
            # correction simply applies that limit analytically.
            #
            # _eq_armed suppresses the event until v is clearly above the
            # curve (δ > 0.1·v_eq²), preventing a spurious trigger at the
            # segment start where δ ≈ 0 from float round-off.  While not
            # armed the function returns a negative sentinel so scipy never
            # sees a + → − transition at t₀.
            #
            # _t_eligible gates out firing during boost / pre-separation.
            _eq_armed = [False]

            def _eq_upward_xing(t, s, *_,
                                _b=_beta_ste, _ld=_LD_ste,
                                _arm=_eq_armed,
                                _min_t=_t_eligible):
                if t < _min_t:
                    return -1.0         # boost / pre-separation — ignore
                _p, _v = s[:3], s[3:]
                _, _, _h = ecef_to_geodetic(_p)
                _h = max(_h, 0.0)
                _spd = np.linalg.norm(_v)
                if _spd < 50.0:
                    return -1.0 if not _arm[0] else 1.0
                _, _, _rho, _ = atmosphere(_h)
                if _rho < 1e-20:
                    return -1.0 if not _arm[0] else 1.0
                _rmag  = np.linalg.norm(_p)
                _gperp = max(float(np.linalg.norm(gravity_ecef(_p)))
                             - _spd * _spd / _rmag, 0.0)
                _den = _rho * _ld
                if _den < 1e-30:
                    return -1.0 if not _arm[0] else 1.0
                _v_eq_sq = 2.0 * _b * _gperp / _den
                _delta   = _spd * _spd - _v_eq_sq
                if _delta > 0.1 * _v_eq_sq:
                    _arm[0] = True      # clearly above v_eq curve — arm
                if not _arm[0]:
                    return -1.0         # negative sentinel until armed
                return _delta

            _eq_upward_xing.terminal  = True
            _eq_upward_xing.direction = -1   # δ: + → − when v descends through v_eq

            _sol_seg = solve_ivp(
                _eom, (_t_now, max_time_s), _s_now,
                method='RK45',
                t_eval=_te_seg if len(_te_seg) > 0 else None,
                events=[_hit_ground, _eq_upward_xing],
                args=eom_args,
                rtol=_rtol, atol=_atol,
                dense_output=False, max_step=_maxstep,
            )
            _tdata   = _sol_seg.t
            _posdata = _sol_seg.y[:3].T
            _veldata = _sol_seg.y[3:].T

            _ground_hit = (len(_sol_seg.t_events[0]) > 0)
            _cross_hit  = (len(_sol_seg.t_events[1]) > 0)
            _took_cross = (_cross_hit and
                           (not _ground_hit or
                            _sol_seg.t_events[1][0] < _sol_seg.t_events[0][0]))

            if _took_cross:
                _t_handoff = float(_sol_seg.t_events[1][0])
                _s_handoff = _sol_seg.y_events[1][0].copy()
                # FPA correction: the v = v_eq crossing occurs on the
                # ascending leg where the flight path angle γ is non-zero.
                # Project the velocity onto the local horizontal plane and
                # rescale to preserve the original speed magnitude (= v_eq).
                # This places the vehicle at (h, v_eq, γ=0) — the exact
                # initial condition for equilibrium glide.
                # Physically: the phugoid damps asymptotically to v=v_eq,
                # γ=0 (radial KE → altitude via zoom, not heat), so rescaling
                # correctly represents the limiting post-damping state.
                # Not rescaling (giving v=v_eq·cos γ) leaves the vehicle
                # below the v_eq curve, where the glide EOM cannot generate
                # enough lift and the vehicle sinks rather than glides.
                _p_ho    = _s_handoff[:3]
                _v_ho    = _s_handoff[3:].copy()
                _rhat_ho = _p_ho / np.linalg.norm(_p_ho)
                _spd_ho  = float(np.linalg.norm(_v_ho))
                _v_horiz = _v_ho - float(np.dot(_rhat_ho, _v_ho)) * _rhat_ho
                _vhm     = float(np.linalg.norm(_v_horiz))
                if _vhm > 1.0:
                    _s_handoff[3:] = (_v_horiz / _vhm) * _spd_ho  # v = v_eq, γ = 0
                _tdata   = np.append(_tdata,   _t_handoff)
                _posdata = np.vstack([_posdata, _s_handoff[:3]])
                _veldata = np.vstack([_veldata, _s_handoff[3:]])

            # Drop the first point only if it exactly coincides with the
            # last point already in the buffer (happens when t_eval=None
            # is passed and scipy includes the IC at t=_t_now).
            if (_segs_t and len(_tdata) > 0 and len(_segs_t[-1]) > 0
                    and abs(_tdata[0] - _segs_t[-1][-1]) < 1e-6):
                _tdata   = _tdata[1:]
                _posdata = _posdata[1:]
                _veldata = _veldata[1:]
            _segs_t.append(_tdata)
            _segs_pos.append(_posdata)
            _segs_vel.append(_veldata)

            if _took_cross:
                _t_now = _t_handoff
                _s_now = _s_handoff
            else:
                break   # ground reached before the N-th crossing
        else:
            # for/else: all N crossings achieved — switch to equilibrium-glide EOM.
            # _t_handoff is None when Phase 0 didn't reach apogee (range was 0);
            # in that case the trajectory is just the Phase 0 arc.
            if _t_handoff is not None:
                import dataclasses as _dc_ste
                _params_eq = copy.deepcopy(params)
                _ero_eq_obj = effective_ro(_params_eq)
                if _ero_eq_obj is not None:
                    _ero_eq_new = _dc_ste.replace(_ero_eq_obj,
                                                  glider_guidance="equilibrium_glide")
                    _neq = _params_eq
                    while _neq is not None:
                        if _neq.ro is not None:
                            _neq.ro = _ero_eq_new
                            break
                        _neq = getattr(_neq, 'stage2', None)
                _eom_args_eq = (_params_eq, cutoff_time_s, az,
                                gt_turn_start_s, gt_turn_stop_s,
                                _target_orbit_alt_m, _t_final_ignition,
                                _yaw_maneuvers)
                _te_glide  = t_eval[t_eval >= _t_handoff]
                _sol_glide = solve_ivp(
                    _eom, (_t_handoff, max_time_s), _s_handoff,
                    method='RK45',
                    t_eval=_te_glide if len(_te_glide) > 0 else None,
                    events=_hit_ground,
                    args=_eom_args_eq,
                    rtol=_rtol, atol=_atol,
                    dense_output=False, max_step=_maxstep,
                )
                # Drop first point only if it duplicates the crossing state
                # (coincidence with a t_eval grid point, or t_eval=None case).
                _tg = _sol_glide.t
                _pg = _sol_glide.y[:3].T
                _vg = _sol_glide.y[3:].T
                if (len(_tg) > 0 and len(_segs_t) > 0 and len(_segs_t[-1]) > 0
                        and abs(_tg[0] - _segs_t[-1][-1]) < 1e-6):
                    _tg = _tg[1:]
                    _pg = _pg[1:]
                    _vg = _vg[1:]
                if len(_tg) > 0:
                    _segs_t.append(_tg)
                    _segs_pos.append(_pg)
                    _segs_vel.append(_vg)
                _t_ms_glide_start = _t_handoff   # milestone: handoff point

        if _segs_t:
            t_arr   = np.concatenate(_segs_t)
            pos_arr = np.concatenate(_segs_pos)
            vel_arr = np.concatenate(_segs_vel)
        else:
            t_arr   = np.array([0.0])
            pos_arr = state0[:3].reshape(1, 3)
            vel_arr = state0[3:].reshape(1, 3)
        orbital = False

    else:
        # For glider modes (non-pullup, non-skip), split at apogee:
        # Phase 1 (glider off) integrates to apogee so the ascent arc is
        # always mode-independent; Phase 2 (glider on) continues to ground.
        _needs_apo_split = (_ero_full is not None
                            and _ero_full.glider_enabled
                            and _ero_full.glider_LD > 0)
        if _needs_apo_split:
            params._glider_phase1 = True
            _sol_p1 = solve_ivp(
                fun=_eom,
                t_span=t_span,
                y0=state0,
                method='RK45',
                t_eval=t_eval,
                events=[_hit_ground, _apogee_event],
                args=eom_args,
                rtol=_rtol,
                atol=_atol,
                dense_output=False,
                max_step=_maxstep,
            )
            _apo_fired = (len(_sol_p1.t_events[1]) > 0
                          and (len(_sol_p1.t_events[0]) == 0
                               or (_sol_p1.t_events[1][0] <
                                   _sol_p1.t_events[0][0])))
            if _apo_fired:
                params._glider_phase1 = False
                _t_apo  = float(_sol_p1.t_events[1][0])
                _s_apo  = _sol_p1.y_events[1][0]
                _te_p2  = t_eval[t_eval >= _t_apo]
                _sol_p2 = solve_ivp(
                    fun=_eom,
                    t_span=(_t_apo, max_time_s),
                    y0=_s_apo,
                    method='RK45',
                    t_eval=_te_p2 if len(_te_p2) > 0 else None,
                    events=_hit_ground,
                    args=eom_args,
                    rtol=_rtol,
                    atol=_atol,
                    dense_output=False,
                    max_step=_maxstep,
                )
                # Stitch phases; drop duplicate at the apogee joint if
                # _t_apo coincides with a t_eval grid point.
                _t1, _y1 = _sol_p1.t, _sol_p1.y
                _t2, _y2 = _sol_p2.t, _sol_p2.y
                if len(_t1) > 0 and len(_t2) > 0 and abs(_t1[-1] - _t2[0]) < 1e-6:
                    _t2 = _t2[1:]
                    _y2 = _y2[:, 1:]
                t_arr   = np.concatenate([_t1, _t2])
                pos_arr = np.concatenate([_y1[:3].T, _y2[:3].T])
                vel_arr = np.concatenate([_y1[3:].T, _y2[3:].T])
                orbital = (len(_sol_p2.t_events[0]) == 0)
            else:
                params._glider_phase1 = False
                t_arr   = _sol_p1.t
                pos_arr = _sol_p1.y[:3].T
                vel_arr = _sol_p1.y[3:].T
                orbital = (len(_sol_p1.t_events[0]) == 0)
        else:
            sol = solve_ivp(
                fun=_eom,
                t_span=t_span,
                y0=state0,
                method='RK45',
                t_eval=t_eval,
                events=_hit_ground,
                args=eom_args,
                rtol=_rtol,
                atol=_atol,
                dense_output=False,
                max_step=_maxstep,
            )

            t_arr    = sol.t
            pos_arr  = sol.y[:3].T   # (N, 3)
            vel_arr  = sol.y[3:].T   # (N, 3)

            # Detect whether the warhead actually reached the ground.  When the
            # _hit_ground event never fires the vehicle is on an orbital or
            # very-long-range sub-orbital arc that didn't return within max_time_s.
            orbital = len(sol.t_events[0]) == 0

    # Verify the orbital flag by computing the perigee of the trajectory's
    # osculating orbit at the final state.  A long sub-orbital arc (apogee
    # thousands of km, flight time > max_time_s) has perigee underground and
    # must be treated as sub-orbital even if _hit_ground never fired.
    if orbital:
        _oe_verify = orbital_elements_from_state(pos_arr[-1], vel_arr[-1])
        if _oe_verify['perigee_km'] < 80.0:
            orbital = False   # long sub-orbital arc, not a stable orbit

    lats, lons, alts = [], [], []
    for p in pos_arr:
        la, lo, al = ecef_to_geodetic(p)
        lats.append(np.degrees(la))
        lons.append(np.degrees(lo))
        alts.append(al)

    lats   = np.array(lats)
    lons   = np.array(lons)
    alts   = np.array(alts)
    speeds = np.linalg.norm(vel_arr, axis=1)

    # Cumulative ground-track path length.  Using geodesic-from-origin would
    # cause the range axis to go backward when the trajectory curves near the
    # antipodal zone, producing a non-physical loop on the altitude-vs-range
    # plot.  Cumulative step-to-step arc length is always monotonically
    # increasing and gives a physically correct downrange axis.
    _lat_r = np.radians(lats)
    _lon_r = np.radians(lons)
    ranges = np.zeros(len(lats))
    for _i in range(1, len(lats)):
        ranges[_i] = ranges[_i - 1] + float(
            range_between(_lat_r[_i - 1], _lon_r[_i - 1],
                          _lat_r[_i],     _lon_r[_i])
        )
    # Geodesic from launch to impact (operational range, used in flight events)
    _range_km_geodesic = (
        range_between(lat0, lon0, _lat_r[-1], _lon_r[-1]) / 1000.0
        if len(lats) > 0 else 0.0
    )

    apo_idx = int(np.argmax(alts))

    # --- Mass array -------------------------------------------------------
    masses = np.array([booster_mass(params, t_arr[i], alts[i])
                       for i in range(len(t_arr))])

    # --- Inertial (ECI-frame) speed ---------------------------------------
    # v_inertial = v_ecef + ω × r   (ω = Earth rotation vector)
    # This is needed for re-entry heating, radar, and energy calculations.
    omega_vec = np.array([0.0, 0.0, OMEGA_EARTH])
    inertial_vel_arr = vel_arr + np.cross(omega_vec, pos_arr)
    inertial_speeds  = np.linalg.norm(inertial_vel_arr, axis=1)

    # --- Acceleration array (central finite-difference on ground speed) ---
    accels = np.empty_like(speeds)
    accels[1:-1] = (speeds[2:] - speeds[:-2]) / (t_arr[2:] - t_arr[:-2])
    accels[0]    = accels[1]
    accels[-1]   = accels[-2]

    # --- Flight-event milestones ------------------------------------------
    milestones = []

    def _insert_chrono(row):
        """Insert a milestone dict in ascending t_s order."""
        for i, m in enumerate(milestones):
            if m['t_s'] > row['t_s']:
                milestones.insert(i, row)
                return
        milestones.append(row)

    def _alt_crossing(threshold_m, ascending):
        """
        Return the interpolated time of the first altitude crossing of
        threshold_m in the requested direction (ascending=True → going up,
        False → going down).  Returns None if not found.
        """
        delta = alts - threshold_m
        sign_changes = np.diff(np.sign(delta))
        direction = 1 if ascending else -1
        indices = np.where(sign_changes * direction > 0)[0]
        if not len(indices):
            return None
        idx = indices[0]
        frac = (threshold_m - alts[idx]) / (alts[idx + 1] - alts[idx])
        return float(t_arr[idx] + frac * (t_arr[idx + 1] - t_arr[idx]))

    def _milestone(t_ev):
        return _interp_milestone(t_ev, t_arr, alts, ranges, speeds,
                                 inertial_speeds, accels, masses)

    # Stage ignition / burnout events from the stage list
    for label, t_ev in _stage_event_times(params):
        if t_ev > t_arr[-1]:
            break          # vehicle hit ground before this event
        row = _milestone(t_ev)
        row['event'] = label
        milestones.append(row)

    # Shroud jettison — altitude crossing (override) or heating-latch time.
    if params.shroud_mass_kg > 0:
        if params.shroud_jettison_alt_km > 0:
            t_ev = _alt_crossing(params.shroud_jettison_alt_km * 1000.0,
                                 ascending=True)
        else:
            t_ev = getattr(params, '_shroud_latch', [None, None, None])[2]
        if t_ev is not None:
            row = _milestone(t_ev)
            row['event'] = "Fairing jettison"
            _insert_chrono(row)

    # --- Debris impact arcs (tumbling empty stages + shroud) -----------------
    # Helper: interpolate ECEF state at time t_ev from the dense arrays.
    def _ecef_state_at(t_ev):
        t_ev = float(np.clip(t_ev, t_arr[0], t_arr[-1]))
        pos = np.array([np.interp(t_ev, t_arr, pos_arr[:, i]) for i in range(3)])
        vel = np.array([np.interp(t_ev, t_arr, vel_arr[:, i]) for i in range(3)])
        return pos, vel

    _debris_trajectories = []   # list of {label, t, lat, lon, alt} dicts

    # Walk stages: every jettisoned stage body gets a debris arc.
    # Non-last stages are always jettisoned.  Whether the LAST stage body is
    # separate debris is the separation decision, owned by the BOOSTER
    # (body_reenters): a separating reentry object sheds the
    # casing at burnout; a body-mode ('no separation') vehicle keeps the stage
    # fused — the body IS the reentering vehicle, not debris.  The decision is
    # the booster's alone (body_reenters via run_separation_mode); the legacy
    # ro_separates build flag is mass bookkeeping, not a separation input.
    _ro_run = params.ro
    _run_separates = (run_separation_mode(params) == 'separating_ro')
    _t_node = 0.0
    _node   = params
    _sn     = 1
    while _node is not None:
        _t_bo    = _t_node + _node.burn_time_s
        _is_last = (_node.stage2 is None)
        if _is_last:
            _body_jettisoned = _run_separates
            # Casing mass: the physical burnout mass of the last stage is
            # mass_initial − mass_propellant (independent of whether the
            # builder baked the payload into mass_final — Scud-class — or
            # kept it separate — Minotaur-class).  What tumbles after the
            # reentry object departs is that burnout mass minus the object.
            # For payload==object this reproduces the stored mass_final
            # exactly; for a non-separating-built booster flown with a
            # separating object it correctly strips the warhead mass from
            # the casing instead of counting it twice.
            _m_bo = (_node.mass_initial - _node.mass_propellant
                     if _node.mass_propellant > 0 else _node.mass_final)
            # What departs at burnout is the WHOLE front-end loadout —
            # bus + N × object, i.e. payload_kg as composed by
            # compose_loadout — not just the single object modeled on the
            # way back.  Fall back to the object's own mass for chains
            # that never went through composition.
            _m_ro = (params.payload_kg if params.payload_kg > 0 else
                     (float(getattr(_ro_run, 'mass_kg', 0.0) or 0.0)
                      if _ro_run is not None else 0.0))
            _cas_mass = _m_bo - _m_ro if _m_bo > _m_ro else _node.mass_final
        else:
            _body_jettisoned = True   # non-last stages always shed their body
            _cas_mass = _node.mass_final

        if _body_jettisoned and _cas_mass > 0 and _t_bo <= t_arr[-1]:
            beta = tumbling_cylinder_beta(_cas_mass,
                                          _node.diameter_m, _node.length_m)
            if beta > 0:
                _pos_s, _vel_s = _ecef_state_at(_t_bo)
                _debris = integrate_debris(_pos_s, _vel_s, beta,
                                           max_time_s=14400.0,
                                           return_trajectory=True)
                if _debris is None:
                    # Stage did not re-enter within the integration window —
                    # it is in orbit; add an informational row with no impact
                    # coordinates so no spurious marker appears on the map.
                    _insert_chrono({
                        'event':   f"Stage {_sn} empty body — in orbit",
                        't_s':     _t_bo,
                        'alt_km':  0.0, 'range_km': 0.0,
                        'speed_kms': 0.0, 'inertial_speed_kms': 0.0,
                        'accel_ms2': 0.0,
                        'mass_t':  _cas_mass / 1000.0,
                        'is_debris': True,
                    })
                else:
                    _d_lat, _d_lon, _dt, _d_spd, _d_traj = _debris
                    _rng = range_between(lat0, lon0,
                                         np.radians(_d_lat), np.radians(_d_lon))
                    _insert_chrono({
                        'event':              f"Stage {_sn} empty impact",
                        't_s':                _t_bo + _dt,
                        'alt_km':             0.0,
                        'range_km':           _rng / 1000.0,
                        'speed_kms':          _d_spd / 1000.0,
                        'inertial_speed_kms': _d_spd / 1000.0,
                        'accel_ms2':          0.0,
                        'mass_t':             _cas_mass / 1000.0,
                        'is_debris':          True,
                        'impact_lat':         _d_lat,
                        'impact_lon':         _d_lon,
                    })
                    _d_traj['t'] = _d_traj['t'] + _t_bo
                    _debris_trajectories.append({
                        'label': f"Stage {_sn} body",
                        **_d_traj,
                    })
        _t_node = _t_bo + _node.coast_time_s
        _node   = _node.stage2
        _sn    += 1

    # Shroud debris arc.  If length is given use tumbling-cylinder β; otherwise
    # fall back to end-on disc area so the impact row is always shown.
    if params.shroud_mass_kg > 0:
        if params.shroud_jettison_alt_km > 0:
            _t_fair = _alt_crossing(params.shroud_jettison_alt_km * 1000.0,
                                    ascending=True)
        else:
            _t_fair = getattr(params, '_shroud_latch', [None, None, None])[2]
        if _t_fair is not None and _t_fair <= t_arr[-1]:
            _sd = params.shroud_diameter_m if params.shroud_diameter_m > 0 else params.diameter_m
            if params.shroud_length_m > 0:
                beta = tumbling_cylinder_beta(params.shroud_mass_kg,
                                              _sd, params.shroud_length_m)
                _beta_note = f"β={beta:.0f} kg/m²"
            else:
                # Length unknown — use end-on disc area as a conservative estimate.
                _A_end = np.pi * _sd ** 2 / 4.0
                beta = (params.shroud_mass_kg / _A_end) if _A_end > 0 else 0.0
                _beta_note = f"β={beta:.0f} kg/m² (disc, no length)"
            if beta > 0:
                _pos_s, _vel_s = _ecef_state_at(_t_fair)
                _debris = integrate_debris(_pos_s, _vel_s, beta,
                                           return_trajectory=True)
                if _debris is not None:
                    _d_lat, _d_lon, _dt, _d_spd, _d_traj = _debris
                    _rng = range_between(lat0, lon0,
                                         np.radians(_d_lat), np.radians(_d_lon))
                    _insert_chrono({
                        'event':              "Fairing impact",
                        't_s':                _t_fair + _dt,
                        'alt_km':             0.0,
                        'range_km':           _rng / 1000.0,
                        'speed_kms':          _d_spd / 1000.0,
                        'inertial_speed_kms': _d_spd / 1000.0,
                        'accel_ms2':          0.0,
                        'mass_t':             params.shroud_mass_kg / 1000.0,
                        'is_debris':          True,
                        'impact_lat':         _d_lat,
                        'impact_lon':         _d_lon,
                    })
                    _d_traj['t'] = _d_traj['t'] + _t_fair
                    _debris_trajectories.append({
                        'label': 'Fairing',
                        **_d_traj,
                    })

    # Booster casing debris — all n_boosters casings follow the same tumbling arc.
    if (params.n_boosters > 0
            and params.booster_diam_m > 0
            and params.booster_inert_kg > 0):
        _t_bsep = booster_separation_time(params)
        if _t_bsep > 0 and _t_bsep <= t_arr[-1]:
            _b_len = (params.booster_length_m
                      if params.booster_length_m > 0
                      else 2.0 * params.booster_diam_m)
            _beta_b = tumbling_cylinder_beta(
                params.booster_inert_kg,
                params.booster_diam_m,
                _b_len,
            )
            if _beta_b > 0:
                _pos_b, _vel_b = _ecef_state_at(_t_bsep)
                _debris_b = integrate_debris(_pos_b, _vel_b, _beta_b,
                                             max_time_s=14400.0,
                                             return_trajectory=True)
                if _debris_b is not None:
                    _d_lat, _d_lon, _dt, _d_spd, _d_traj = _debris_b
                    _rng = range_between(lat0, lon0,
                                         np.radians(_d_lat), np.radians(_d_lon))
                    _insert_chrono({
                        'event':              "Booster casing impact",
                        't_s':                _t_bsep + _dt,
                        'alt_km':             0.0,
                        'range_km':           _rng / 1000.0,
                        'speed_kms':          _d_spd / 1000.0,
                        'inertial_speed_kms': _d_spd / 1000.0,
                        'accel_ms2':          0.0,
                        'mass_t':             params.booster_inert_kg / 1000.0,
                        'is_debris':          True,
                        'impact_lat':         _d_lat,
                        'impact_lon':         _d_lon,
                    })
                    _d_traj['t'] = _d_traj['t'] + _t_bsep
                    _debris_trajectories.append({
                        'label': f'Booster casings ({params.n_boosters}×)',
                        **_d_traj,
                    })

    # Apogee
    apo_row = _milestone(t_arr[apo_idx])
    apo_row['event'] = f"Apogee ({apo_row['alt_km']:.0f} km)"
    _insert_chrono(apo_row)

    # Perigee — first altitude minimum after powered flight ends (orbital only).
    # Scan for the first sign change from negative to positive in d(alt)/dt
    # after total burn time: that crossing marks the first perigee passage.
    if orbital:
        _ins_idx = int(np.searchsorted(t_arr, total_burn))
        if _ins_idx + 2 < len(alts):
            _d_alt = np.diff(alts[_ins_idx:])
            for _j in range(len(_d_alt) - 1):
                if _d_alt[_j] <= 0 and _d_alt[_j + 1] > 0:
                    _pi = _ins_idx + _j + 1
                    if alts[_pi] > 80_000:   # > 80 km → genuine orbital perigee
                        _pr = _milestone(t_arr[_pi])
                        _pr['event'] = f"Perigee ({_pr['alt_km']:.0f} km)"
                        _insert_chrono(_pr)
                    break

    # Yaw (dogleg) maneuver milestones
    if _yaw_maneuvers:
        _prev_az_deg = np.degrees(az)
        for _mi, (_ys, _ye, _yf) in enumerate(_yaw_maneuvers):
            if _yf is None:
                continue
            _lbl = f"Yaw {_mi + 1}" if len(_yaw_maneuvers) > 1 else "Yaw"
            if _ys is not None and _ys <= t_arr[-1]:
                _ym = _milestone(_ys)
                _ym['event'] = f"{_lbl} start ({_prev_az_deg:.1f}°\u2192{_yf:.1f}°)"
                _insert_chrono(_ym)
            if _ye is not None and _ye <= t_arr[-1]:
                _ym = _milestone(_ye)
                _ym['event'] = f"{_lbl} end ({_yf:.1f}°)"
                _insert_chrono(_ym)
            _prev_az_deg = _yf

    # Bank-turn milestones
    _ero_bk = effective_ro(params)
    if (_ero_bk is not None and _ero_bk.glider_enabled
            and _ero_bk.glider_bank_schedule):
        for _bi, (_bs, _be, _bk) in enumerate(_ero_bk.glider_bank_schedule):
            _lbl = (f"Bank {_bi + 1}" if len(_ero_bk.glider_bank_schedule) > 1
                    else "Bank turn")
            if _bs is not None and float(_bs) <= t_arr[-1]:
                _bm = _milestone(float(_bs))
                _bm['event'] = f"{_lbl} start ({_bk:+.0f}°)"
                _insert_chrono(_bm)
            if _be is not None and float(_be) <= t_arr[-1]:
                _bm = _milestone(float(_be))
                _bm['event'] = f"{_lbl} end"
                _insert_chrono(_bm)

    # Re-entry interface — first downward crossing of 100 km (after apogee)
    REENTRY_ALT_M = 100_000.0
    if np.max(alts) > REENTRY_ALT_M:
        t_ev = _alt_crossing(REENTRY_ALT_M, ascending=False)
        if t_ev is not None and t_ev > t_arr[apo_idx]:
            row = _milestone(t_ev)
            row['event'] = "Re-entry (100 km)"
            _insert_chrono(row)

    # Re-entry event set for the terminal vehicle (ballistic RV *or* glider).
    #   • Peak heating   (Sutton-Graves stagnation rate at the RV nose radius)
    #   • Heating FOM    (peak-surface / oxidation-soak / heat-sink survivability)
    #   • Max-G          (peak structural load factor on the descent arc)
    # Glide-only events (gated on _is_glider below):
    #   • Pull-up start  (first altitude minimum after re-entry)
    #   • Glide start    (first altitude maximum after pull-up start)
    #   • Skip N pull-up / Skip N apex (subsequent extrema for skip-glide)
    #   • Terminal dive  (downward crossing of the user-set dive altitude)
    # Heating is evaluated for ANY re-entering RV — a steep ballistic RV is the
    # high-flux regime (cf. the ICBM-RV benchmark in heating.py), so excluding
    # it would skip the very case the survivability FOM most needs to score.
    _ero_ms = effective_ro(params)
    _heating_fom = None
    _heating_arc = None      # reentry-arc arrays + profile (survivability report)
    if _ero_ms is not None:
        _is_glider = bool(_ero_ms.glider_enabled and _ero_ms.glider_LD > 0)
        # For trajectories that reach space use the 100 km descent crossing;
        # for sub-100 km HGV profiles use apogee as the glide-phase start.
        if np.max(alts) > REENTRY_ALT_M:
            _re_t   = _alt_crossing(REENTRY_ALT_M, ascending=False)
            _re_idx = (int(np.searchsorted(t_arr, _re_t))
                       if _re_t is not None else apo_idx)
        else:
            _re_idx = apo_idx
        if _re_idx < len(alts) - 2:
            # Pull-up start / Glide start.
            #
            # For analytical modes (Tracy / Acton equilibrium glide) the
            # post-pierce altitude profile is monotone: there are no
            # altitude extrema for the extrema-detector to find, so the
            # arc-start and glide-start times are captured explicitly
            # during the analytical phase and emitted here.
            #
            # For skip_glide and the numerical-fallback (analytical with a
            # bank schedule) the glide oscillates, so we fall back to the
            # generic extrema detector below.
            _emitted_pullup_glide = False
            if _t_ms_pullup_start is not None and _t_ms_glide_start is not None:
                _ipu = int(np.searchsorted(t_arr, _t_ms_pullup_start))
                _ipu = max(0, min(_ipu, len(alts) - 1))
                _row = _milestone(float(t_arr[_ipu]))
                _row['event'] = f"Pull-up start ({alts[_ipu]/1000:.0f} km)"
                _insert_chrono(_row)
                _igs = int(np.searchsorted(t_arr, _t_ms_glide_start))
                _igs = max(0, min(_igs, len(alts) - 1))
                _row = _milestone(float(t_arr[_igs]))
                _row['event'] = f"Glide start ({alts[_igs]/1000:.0f} km)"
                _insert_chrono(_row)
                _emitted_pullup_glide = True
            elif _t_ms_glide_start is not None:
                # skip_to_equilibrium: emit the handoff milestone; skip phases
                # are handled by the extrema detector below.
                _igs = int(np.searchsorted(t_arr, _t_ms_glide_start))
                _igs = max(0, min(_igs, len(alts) - 1))
                _row = _milestone(float(t_arr[_igs]))
                _row['event'] = f"→ Equilibrium glide ({alts[_igs]/1000:.0f} km)"
                _insert_chrono(_row)

            if _is_glider and not _emitted_pullup_glide:
                # Altitude extrema after re-entry: alternating minima
                # (pull-ups) and maxima (apexes / glide tops).
                # Glide-only: a ballistic descent is monotone (no extrema),
                # and this guard keeps stray numerical wiggles from being
                # mislabelled as pull-ups on a non-gliding RV.
                _post = alts[_re_idx:]
                _dh   = np.diff(_post)
                _sign = np.sign(_dh)
                _ext_locs = np.where(np.diff(_sign) != 0)[0] + 1
                pus_count = 0
                apx_count = 0
                _last_alt = None
                # For skip_to_equilibrium, label all skips up to the handoff;
                # for other modes, emit only the primary pull-up/apex pair.
                _is_ste = (_t_ms_glide_start is not None)
                for ic in _ext_locs:
                    if not (1 <= ic < len(_post) - 1):
                        continue
                    is_min = _post[ic-1] > _post[ic] and _post[ic] < _post[ic+1]
                    is_max = _post[ic-1] < _post[ic] and _post[ic] > _post[ic+1]
                    if not (is_min or is_max):
                        continue
                    # Suppress sub-km numerical wiggles in equilibrium glide.
                    if _last_alt is not None and abs(_post[ic] - _last_alt) < 1000.0:
                        continue
                    _last_alt = _post[ic]
                    full_idx = _re_idx + ic
                    # For skip_to_equilibrium stop labelling skips at the handoff.
                    if _is_ste and t_arr[full_idx] >= _t_ms_glide_start:
                        break
                    _row = _milestone(t_arr[full_idx])
                    if is_min:
                        pus_count += 1
                        _n_lbl = f" {pus_count}" if (_is_ste and pus_count > 1) else ""
                        _row['event'] = (f"Skip{_n_lbl} pull-up"
                                         if _is_ste else
                                         f"Pull-up start "
                                         f"({alts[full_idx]/1000:.0f} km)")
                        if not _is_ste and pus_count > 1:
                            continue   # only first pull-up for non-ste modes
                        _row['event'] += f" ({alts[full_idx]/1000:.0f} km)"
                        _insert_chrono(_row)
                    else:
                        apx_count += 1
                        _n_lbl = f" {apx_count}" if (_is_ste and apx_count > 1) else ""
                        _row['event'] = (f"Skip{_n_lbl} apex"
                                         if _is_ste else
                                         f"Glide start "
                                         f"({alts[full_idx]/1000:.0f} km)")
                        _row['event'] += f" ({alts[full_idx]/1000:.0f} km)"
                        _insert_chrono(_row)
                        if not _is_ste:
                            break  # only emit the primary pull-up/glide pair

            # Peak heating: Sutton-Graves stagnation-point rate using the RV's
            # nose-tip radius — explicit nose_radius_m, else a shape/diameter
            # screening default (ROParams.effective_nose_radius_m).  Peak time
            # is independent of RN; the reported MW/m² scales as 1/√RN.
            _RN = (_ero_ms.effective_nose_radius_m()
                   if hasattr(_ero_ms, 'effective_nose_radius_m')
                   else float(getattr(_ero_ms, 'nose_radius_m', 0.05) or 0.05))
            _glide_a = alts[_re_idx:]
            # Sutton-Graves uses airspeed (ECEF), not inertial speed,
            # because the atmosphere co-rotates with Earth.
            _glide_v = speeds[_re_idx:]
            _rho_g   = np.array([atmosphere(a)[2] for a in _glide_a])
            _q_dot   = 1.7415e-4 * np.sqrt(_rho_g / _RN) * _glide_v ** 3
            # Stash the arc + a minimal reentry profile for the survivability
            # report (survivability_report.py): the EXACT arrays the FOM sees,
            # so the report's flux/load plot is apples-to-apples with the
            # verdict, plus entry conditions and the plan/mode identity the
            # report keys its form on.  Entry flight-path angle from the ECEF
            # state at the arc start (names the loft/MET shaping).
            _p0 = pos_arr[_re_idx]; _v0 = vel_arr[_re_idx]
            _v0m = float(np.linalg.norm(_v0))
            _gam0 = (float(np.degrees(np.arcsin(
                float(np.dot(_v0, _p0 / np.linalg.norm(_p0))) / _v0m)))
                     if _v0m > 1e-6 else 0.0)
            _heating_arc = {
                't':       t_arr[_re_idx:],
                'rho':     _rho_g,
                'V':       _glide_v,
                'alt':     _glide_a,
                'range':   ranges[_re_idx:],
                'q_dot':   _q_dot,          # nose-stagnation reference flux
                'entry_V_ms':      _v0m,
                'entry_gamma_deg': _gam0,
                'profile': {
                    'name':        str(getattr(_ero_ms, 'name', '') or ''),
                    'guidance':    str(getattr(_ero_ms, 'glider_guidance', '') or ''),
                    'glider':      bool(_ero_ms.glider_enabled and _ero_ms.glider_LD > 0),
                    'nose_radius_m':   float(_RN),
                    'diameter_m':      float(getattr(_ero_ms, 'diameter_m', 0.0) or 0.0),
                    'mass_kg':         float(getattr(_ero_ms, 'mass_kg', 0.0) or 0.0),
                    'emissivity':      float(getattr(_ero_ms, 'emissivity', 0.85) or 0.85),
                    'nose_material':   (_ero_ms.nose_material()
                                        if hasattr(_ero_ms, 'nose_material') else ''),
                    'body_material':   (_ero_ms.body_material()
                                        if hasattr(_ero_ms, 'body_material') else ''),
                    'body_thickness_m': float(getattr(_ero_ms, 'body_tps_thickness_m', 0.0) or 0.0),
                    'pullup_g_max':    float(getattr(_ero_ms, 'glider_pullup_g_max', 0.0) or 0.0),
                    'terminal_alt_km': (float(getattr(_ero_ms, 'glider_terminal_alt_km', 0.0) or 0.0)
                                        if getattr(_ero_ms, 'glider_terminal_dive', False) else 0.0),
                    'dive_target_radius_km': float(getattr(_ero_ms, 'glider_dive_target_radius_km', 0.0) or 0.0),
                    'pullup_start_alt_km': float(getattr(_ero_ms, 'glider_pullup_start_alt_km', 0.0) or 0.0),
                    # Lateral maneuver: a non-empty bank schedule.  Feeds the
                    # report's honest arc descriptors (a vehicle that BANKS is
                    # what "maneuvering" means; diving is a separate fact).
                    'banking':     bool(getattr(_ero_ms, 'glider_bank_schedule', None)),
                },
            }
            if len(_q_dot) and np.max(_q_dot) > 0:
                _ipk = int(np.argmax(_q_dot))
                _row = _milestone(t_arr[_re_idx + _ipk])
                # Radiative-equilibrium stagnation temperature:
                # T_eq = (q̇ / (σ·ε))^(1/4).  Validates against public-source
                # claims about peak RV nose temperatures.
                _eps  = float(getattr(_ero_ms, 'emissivity', 0.85) or 0.85)
                _T_eq = (_q_dot[_ipk] / (5.670374419e-8 * _eps)) ** 0.25
                _row['event'] = (f"Peak heating "
                                 f"({_q_dot[_ipk]/1e6:.1f} MW/m², "
                                 f"T_eq ≈ {_T_eq:.0f} K)")
                _insert_chrono(_row)

            # Heating survivability figure of merit (heating.py): peak-surface,
            # oxidation-soak, and lumped heat-sink criteria → margins,
            # compromise point, and verdict (stored in result['heating_fom']).
            if len(_glide_v) > 1:
                _diam = float(getattr(_ero_ms, 'diameter_m', 0.0) or 0.0)
                # Per-location (nose + body acreage) verdict when the RV sets
                # split materials (§10.1); otherwise the legacy single-material
                # call — byte-identical for existing RVs.
                _split = bool(getattr(_ero_ms, 'nose_tps_material', '') or
                              getattr(_ero_ms, 'body_tps_material', ''))
                # Bespoke materials: inject the RV's user-defined props into the
                # catalog under their sentinel keys so the key-based FOM resolves
                # them (§10 materials dropdown, "Custom…").
                if getattr(_ero_ms, 'nose_tps_custom', None):
                    heating.register_custom_material(
                        heating.CUSTOM_NOSE_KEY, _ero_ms.nose_tps_custom)
                if getattr(_ero_ms, 'body_tps_custom', None):
                    heating.register_custom_material(
                        heating.CUSTOM_BODY_KEY, _ero_ms.body_tps_custom)
                if _split:
                    _heating_fom = heating.heating_fom_per_location(
                        t_arr[_re_idx:], _rho_g, _glide_v, _glide_a, ranges[_re_idx:],
                        nose_radius_m=_RN, body_radius_m=_diam / 2.0,
                        emissivity=float(getattr(_ero_ms, 'emissivity', 0.85) or 0.85),
                        nose_material=_ero_ms.nose_material(),
                        body_material=_ero_ms.body_material(),
                        mass_kg=float(getattr(_ero_ms, 'mass_kg', 0.0) or 0.0),
                        frontal_area_m2=(np.pi * (_diam / 2.0) ** 2 if _diam > 0 else 0.0),
                        body_thickness_m=float(getattr(_ero_ms, 'body_tps_thickness_m', 0.0) or 0.0))
                else:
                    _heating_fom = heating.heating_figure_of_merit(
                        t_arr[_re_idx:], _rho_g, _glide_v, _glide_a, ranges[_re_idx:],
                        nose_radius_m=_RN, body_radius_m=_diam / 2.0,
                        emissivity=float(getattr(_ero_ms, 'emissivity', 0.85) or 0.85),
                        material=str(getattr(_ero_ms, 'tps_material', '') or ''),
                        mass_kg=float(getattr(_ero_ms, 'mass_kg', 0.0) or 0.0),
                        frontal_area_m2=(np.pi * (_diam / 2.0) ** 2 if _diam > 0 else 0.0))
                # Windward-flank heating band (glide AoA probe, heating.py):
                # the α=0 acreage flux scaled by the modified-Newtonian windward
                # amplification A(α)=sin(δ+α)/sin(δ), over the glide sub-arc
                # (the low-AoA terminal dive is masked out).  A lifting vehicle
                # flies its glide at AoA, so the windward flank — not the nose —
                # carries the off-nose acreage heat.  Context overlay by default.
                if (isinstance(_heating_fom, dict) and _diam > 0
                        and getattr(_ero_ms, 'glider_enabled', False)
                        and float(getattr(_ero_ms, 'glider_LD', 0.0)) > 0.0):
                    _L_fore = float(getattr(_ero_ms, 'length_m', 0.0) or 0.0)
                    _delta_defaulted = not (_L_fore > 0.0)
                    _delta_deg = (float(np.degrees(np.arctan((_diam / 2.0) / _L_fore)))
                                  if _L_fore > 0.0 else 8.0)
                    # Operating glide AoA: the trimmed AoA already found by the
                    # static-margin gate (non-sep body); else the ESTIMATOR'S
                    # stored trim α* (Phase 3 — the Candler consistency guard:
                    # the attitude the heating is evaluated at comes from the
                    # same sweep as the L/D, so they can never contradict);
                    # else None -> windward reported band-only.
                    _alpha_op = (_reentry_trim.get('alpha_glide_deg')
                                 if _reentry_trim else None)
                    if _alpha_op is None:
                        _ta = float(getattr(_ero_ms, 'trim_alpha_deg', 0.0) or 0.0)
                        _alpha_op = _ta if _ta > 0.0 else None
                    # Glide sub-arc: exclude the commanded terminal dive.
                    _term_alt = (float(getattr(_ero_ms, 'glider_terminal_alt_km', 0.0) or 0.0) * 1000.0
                                 if getattr(_ero_ms, 'glider_terminal_dive', False) else 0.0)
                    _gmask = (np.asarray(_glide_a, float) > _term_alt) if _term_alt > 0 else None
                    try:
                        _heating_fom['windward'] = heating.windward_flank_flux(
                            t_arr[_re_idx:], _rho_g, _glide_v, _glide_a, ranges[_re_idx:],
                            body_radius_m=(_diam / 2.0), nose_radius_m=_RN,
                            flank_half_angle_deg=_delta_deg, alpha_op_deg=_alpha_op,
                            emissivity=float(getattr(_ero_ms, 'emissivity', 0.85) or 0.85),
                            body_material=(_ero_ms.body_material()
                                           if hasattr(_ero_ms, 'body_material') else ''),
                            glide_mask=_gmask, delta_defaulted=_delta_defaulted,
                            body_form=str(getattr(_ero_ms, 'body_form', '')
                                          or 'axisymmetric'))
                    except Exception:
                        pass   # windward is an overlay; never break the FOM

                _cmp = _heating_fom.get('compromise')
                if _cmp is not None:
                    _row = _milestone(_cmp['t_s'])
                    _loc = _cmp.get('location')
                    _row['event'] = ("TPS compromise — " +
                                     ((_loc + ": ") if _loc else "") + _cmp['mode'])
                    _insert_chrono(_row)

            # Max structural load factor n = |a_proper| / g0, where
            # a_proper = d v_inertial / d t − local gravity.  Captures
            # both transverse (lift) and longitudinal (drag) loads.
            _glide_pos = pos_arr[_re_idx:]
            _glide_iv  = inertial_vel_arr[_re_idx:]
            _glide_t   = t_arr[_re_idx:]
            # np.gradient requires strictly increasing spacing; drop duplicate t.
            _uniq = np.concatenate(([True], np.diff(_glide_t) > 0))
            _glide_pos = _glide_pos[_uniq]
            _glide_iv  = _glide_iv[_uniq]
            _glide_t   = _glide_t[_uniq]
            if len(_glide_t) >= 3:
                _iacc = np.gradient(_glide_iv, _glide_t, axis=0)
                _r_n  = np.linalg.norm(_glide_pos, axis=1)
                _g_v  = -GM * _glide_pos / _r_n[:, None]**3
                _n    = np.linalg.norm(_iacc - _g_v, axis=1) / 9.80665
                if len(_n) and np.max(_n) > 0:
                    _img = int(np.argmax(_n))
                    _row = _milestone(t_arr[_re_idx + _img])
                    _row['event'] = f"Max-G ({_n[_img]:.1f} g)"
                    _insert_chrono(_row)
        if (_is_glider and _ero_ms.glider_terminal_dive
                and _ero_ms.glider_terminal_alt_km > 0):
            _td_m = _ero_ms.glider_terminal_alt_km * 1000.0
            if np.max(alts) > _td_m:
                _td_t = _alt_crossing(_td_m, ascending=False)
                if _td_t is not None and _td_t > t_arr[apo_idx]:
                    _row = _milestone(_td_t)
                    _row['event'] = (f"Terminal dive "
                                     f"({_ero_ms.glider_terminal_alt_km:.0f} km)")
                    _insert_chrono(_row)

    # Optional user-specified re-entry query altitude (e.g. 50 km for
    # aeroballistic / hypersonic-glider handoff conditions).
    if reentry_query_alt_km is not None:
        _q_m = reentry_query_alt_km * 1000.0
        if np.max(alts) > _q_m:
            t_ev = _alt_crossing(_q_m, ascending=False)
            if t_ev is not None and t_ev > t_arr[apo_idx]:
                row = _milestone(t_ev)
                row['event'] = f"Re-entry query ({reentry_query_alt_km:.0f} km)"
                _insert_chrono(row)

    # Orbital elements — computed when the vehicle stays in orbit (no impact)
    # or when orbital_insertion mode is active (elements reported at end of burn
    # for every stage that may have been inserted into orbit).
    _orb_elements = None
    if orbital:
        # Compute orbital elements from the final state vector.
        _orb_elements = orbital_elements_from_state(pos_arr[-1], vel_arr[-1])

        # Walk the stage list; for any stage whose burnout time is within the
        # arc AND whose debris does NOT re-enter, report orbital elements.
        _t_node2 = 0.0
        _node2   = params
        _sn2     = 1
        while _node2 is not None:
            _t_bo2 = _t_node2 + _node2.burn_time_s
            _is_last2 = (_node2.stage2 is None)
            if _is_last2 and _t_bo2 <= t_arr[-1]:
                # Final stage / payload — report orbital elements milestone.
                _pos_bo, _vel_bo = _ecef_state_at(_t_bo2)
                _oe = orbital_elements_from_state(_pos_bo, _vel_bo)
                _beta_orb = (tumbling_cylinder_beta(_node2.mass_final,
                                                    _node2.diameter_m,
                                                    _node2.length_m)
                             if _node2.mass_final > 0 else 0.0)
                _life = (orbital_lifetime_estimate(_oe['perigee_km'],
                                                   _oe['apogee_km'],
                                                   _beta_orb)
                         if _beta_orb > 0 else None)
                _life_str = (f", {_life:.1f} yr decay" if _life is not None
                             and not np.isinf(_life) else
                             (", lifetime >100 yr" if _life is not None else ""))
                _row = _milestone(_t_bo2)
                _row['event'] = (f"Orbital insertion"
                                 f" ({_oe['perigee_km']:.0f}×"
                                 f"{_oe['apogee_km']:.0f} km"
                                 f", {_oe['inclination_deg']:.1f}°)")
                _row['orbital_elements'] = _oe
                _insert_chrono(_row)
            _t_node2 = _t_bo2 + _node2.coast_time_s
            _node2   = _node2.stage2
            _sn2    += 1

    # Impact — only add if the vehicle actually reached the ground.
    if not orbital:
        imp_row = _milestone(t_arr[-1])
        imp_row['event'] = f"Impact ({imp_row['mass_t']*1000:.0f} kg)"
        milestones.append(imp_row)

    # Annotate every event label with its mission-clock time.
    # Events that already carry a parenthetical (Apogee, Impact, Re-entry …)
    # get the time inserted as the first item: "Apogee (691 s, 955 km)".
    # Plain labels get it appended: "Ignition (0 s)".
    for m in milestones:
        t_s = m['t_s']
        ev  = m['event']
        if '(' in ev:
            m['event'] = ev.replace('(', f'({t_s:.0f} s, ', 1)
        else:
            m['event'] = f'{ev} ({t_s:.0f} s)'

    # Guidance-program output arrays (for the Guidance Program plot).
    # Values are NaN outside of powered-burn windows so the plot only draws
    # lines during active thrust phases (coast and ballistic shown as gaps).
    _burn_windows = []
    _s_bw, _t_bw = params, 0.0
    while _s_bw is not None:
        _burn_windows.append((_t_bw, _t_bw + _s_bw.burn_time_s))
        _t_bw  += _s_bw.burn_time_s + _s_bw.coast_time_s
        _s_bw   = _s_bw.stage2

    def _in_burn_window(t):
        for _tb0, _tb1 in _burn_windows:
            if _tb0 <= t <= _tb1:
                return True
        return False

    _final_burn_end = _burn_windows[-1][1] if _burn_windows else 0.0

    # Derive the commanded pitch/azimuth from the SAME thrust-direction function
    # the EOM flew (_commanded_thrust_dir) — no parallel pitch formula, so the
    # plot cannot disagree with the trajectory.  During a burn we evaluate the
    # real thrust vector at that step's state and read its elevation/azimuth;
    # through inter-stage coasts we hold the last commanded value; after final
    # burnout the arrays go NaN so the plot shows a gap.
    _pitch_cmd  = []
    _az_cmd     = []
    _last_pitch = float(params.launch_elevation_deg)
    _last_az    = float('nan')
    # Boost angle of attack and q·α (NASA SP-8099 "Combining Ascent Loads").
    # α = angle between the FLOWN thrust axis (α-limit applied, if set) and
    # the air-relative velocity (= ECEF velocity: the atmosphere co-rotates).
    # α_cmd is the RAW commanded α before the limit — the two differ only
    # while the α-limit is engaged.  Both are NaN outside powered flight and
    # below the kick-hold speed (v̂ undefined at liftoff).  q·α is SP-8099's
    # design combined-load metric for a maneuvering booster — the quantity a
    # dogleg actually spikes (its §2.1.2.2 envelope: 5–10° α at max q).
    _alpha_deg     = []
    _alpha_cmd_deg = []
    for _i_gp, _t_gp in enumerate(t_arr):
        _gp_stage, _t_since = active_stage_and_t(params, _t_gp)
        _a_now, _ac_now = float('nan'), float('nan')
        if _in_burn_window(_t_gp):
            _lat_i = np.radians(lats[_i_gp])
            _lon_i = np.radians(lons[_i_gp])
            _az_i  = _yaw_program(_t_gp, az, _gp_stage, _yaw_maneuvers)
            _tdir  = _commanded_thrust_dir(
                params, _gp_stage, pos_arr[_i_gp], vel_arr[_i_gp],
                _lat_i, _lon_i, _az_i, _t_gp,
                gt_turn_start_s, gt_turn_stop_s, _t_final_ignition,
                alt_m=alts[_i_gp])
            _ee, _en, _eu = _enu_frame(_lat_i, _lon_i)
            _last_pitch = float(np.degrees(np.arcsin(
                np.clip(float(np.dot(_tdir, _eu)), -1.0, 1.0))))
            # Azimuth from the horizontal projection; undefined near vertical
            # thrust (cos elevation ~ 0), so hold the last value there.
            _e_comp, _n_comp = float(np.dot(_tdir, _ee)), float(np.dot(_tdir, _en))
            if _e_comp * _e_comp + _n_comp * _n_comp > 1e-8:
                _az_raw = float(np.degrees(np.arctan2(_e_comp, _n_comp)))  # [-180,180]
                if np.isfinite(_last_az):
                    # Keep the trace continuous with the previous sample rather
                    # than wrapping to [0,360).  For a due-N/S heading the east
                    # component is machine-zero and its SIGN is pure round-off,
                    # so a plain "% 360" flickers the heading between ~0° and
                    # ~360° every step (the vertical-spike glitch).  Unwrapping
                    # relative to the last value pins it smoothly instead.
                    _az_raw += 360.0 * round((_last_az - _az_raw) / 360.0)
                    _last_az = _az_raw
                else:
                    _last_az = _az_raw % 360.0
            if speeds[_i_gp] >= _TGT_KICK_HOLD_V_MS:
                _v_hat_i = vel_arr[_i_gp] / speeds[_i_gp]
                _a_now = float(np.degrees(np.arccos(
                    np.clip(float(np.dot(_tdir, _v_hat_i)), -1.0, 1.0))))
                if getattr(params, '_alpha_limit_deg', None):
                    _tdir_raw = _commanded_thrust_dir(
                        params, _gp_stage, pos_arr[_i_gp], vel_arr[_i_gp],
                        _lat_i, _lon_i, _az_i, _t_gp,
                        gt_turn_start_s, gt_turn_stop_s, _t_final_ignition,
                        alt_m=alts[_i_gp], apply_alpha_limit=False)
                    _ac_now = float(np.degrees(np.arccos(
                        np.clip(float(np.dot(_tdir_raw, _v_hat_i)),
                                -1.0, 1.0))))
                else:
                    _ac_now = _a_now
        if _t_gp <= _final_burn_end:
            _pitch_cmd.append(_last_pitch)
            _az_cmd.append(_last_az)
        else:
            _pitch_cmd.append(float('nan'))
            _az_cmd.append(float('nan'))
        _alpha_deg.append(_a_now)
        _alpha_cmd_deg.append(_ac_now)

    # Dynamic pressure and the q·α combined-load trace (SP-8099 §2.1.2.2).
    _alpha_deg     = np.asarray(_alpha_deg)
    _alpha_cmd_deg = np.asarray(_alpha_cmd_deg)
    _q_pa = np.empty(len(t_arr))
    for _i_q in range(len(t_arr)):
        _, _, _rho_q, _ = atmosphere(max(float(alts[_i_q]), 0.0))
        _q_pa[_i_q] = 0.5 * _rho_q * speeds[_i_q] ** 2
    _q_alpha_kpa_deg = (_q_pa / 1e3) * _alpha_deg     # NaN off-burn, as α

    # Lateral load-factor readout (the APPLIED aerodynamic side load, honestly
    # computable — NOT a structural capacity).  n_lat = N/(m·g0) with the
    # small-angle body normal force N ≈ q·A_ref·C_Nα·α (slender-body C_Nα = 2
    # /rad), referenced to the boost frontal area.  This is what payload user's
    # guides tabulate as the ascent lateral load factor (e.g. START-1 ~0.7 g,
    # Cyclone-4 / Minotaur steady lateral 0.3–0.7 g).  NaN outside powered
    # flight, as α.
    _lateral_g = np.full(len(t_arr), np.nan)
    for _i_lg in range(len(t_arr)):
        _a_lg = _alpha_deg[_i_lg]
        if np.isfinite(_a_lg) and masses[_i_lg] > 0.0:
            _gp_lg, _ = active_stage_and_t(params, float(t_arr[_i_lg]))
            _aref_lg = booster_area(_gp_lg if _gp_lg is not None else params,
                                    altitude_m=float(alts[_i_lg]),
                                    top_params=params)
            _N_lg = (_q_pa[_i_lg] * _aref_lg * _BOOST_C_NA_POT
                     * np.radians(abs(_a_lg)))
            _lateral_g[_i_lg] = _N_lg / (masses[_i_lg] * 9.80665)

    # Timeline milestones for the ascent-load picture.  Labels carry their
    # own "(N s, …)" parenthetical because the generic time-annotation pass
    # above has already run.
    _qa_fin = np.where(np.isfinite(_q_alpha_kpa_deg), _q_alpha_kpa_deg, -1.0)
    if np.any(_qa_fin > 0.0):
        _i_qa = int(np.argmax(_qa_fin))
        _row_qa = _milestone(float(t_arr[_i_qa]))
        _row_qa['event'] = (
            f"Max q·α ({t_arr[_i_qa]:.0f} s, "
            f"{_q_alpha_kpa_deg[_i_qa]:.1f} kPa·°: "
            f"q {_q_pa[_i_qa]/1e3:.1f} kPa, α {_alpha_deg[_i_qa]:.1f}°)")
        _insert_chrono(_row_qa)

    # Max lateral load-factor milestone (the applied aero side load).
    _lg_fin = np.where(np.isfinite(_lateral_g), _lateral_g, -1.0)
    if np.any(_lg_fin > 0.0):
        _i_lgm = int(np.argmax(_lg_fin))
        _row_lg = _milestone(float(t_arr[_i_lgm]))
        _row_lg['event'] = (
            f"Max lateral load ({t_arr[_i_lgm]:.0f} s, "
            f"{_lateral_g[_i_lgm]:.2f} g at α {_alpha_deg[_i_lgm]:.1f}°)")
        _insert_chrono(_row_lg)

    # α-limit engagement flag.  With the constant-q·α envelope the clamp
    # "engages" wherever it actually reduced the commanded angle — i.e. the
    # flown α fell meaningfully short of the raw command.  (No pressure gate:
    # the envelope self-relaxes as q falls, so engagement is read directly from
    # the clamp biting, not from an arbitrary q threshold.)
    _alpha_limit_engaged = None
    _lim_ms = getattr(params, '_alpha_limit_deg', None)
    if _lim_ms:
        _eng = (np.isfinite(_alpha_cmd_deg) & np.isfinite(_alpha_deg)
                & (_alpha_cmd_deg > _alpha_deg + 0.5))
        if np.any(_eng):
            _ie = np.where(_eng)[0]
            _alpha_limit_engaged = {
                't_start_s':         float(t_arr[_ie[0]]),
                't_end_s':           float(t_arr[_ie[-1]]),
                'alpha_cmd_max_deg': float(np.max(_alpha_cmd_deg[_ie])),
                'alpha_limit_deg':   float(_lim_ms),
            }
            _row_al = _milestone(float(t_arr[_ie[0]]))
            _row_al['event'] = (
                f"α-limit engaged ({t_arr[_ie[0]]:.0f}–{t_arr[_ie[-1]]:.0f} s, "
                f"cmd α up to {_alpha_limit_engaged['alpha_cmd_max_deg']:.0f}° "
                f"held to the q·α envelope, {_lim_ms:.0f}° at max-q)")
            _insert_chrono(_row_al)
    else:
        # No limit set: a large-α maneuver is flown as commanded, so make the
        # load consequence visible — SP-8099's dogleg example (p. 13) is
        # precisely a large-α maneuver becoming the design load condition.
        _viol = (np.isfinite(_alpha_deg)
                 & (_alpha_deg > _ALPHA_WARN_DEG)
                 & (_q_pa > _ALPHA_WARN_Q_PA))
        if np.any(_viol):
            _iv = np.where(_viol)[0]
            _iv_pk = _iv[int(np.argmax(_alpha_deg[_iv]))]
            _row_av = _milestone(float(t_arr[_iv[0]]))
            _row_av['event'] = (
                f"⚠ α exceeds SP-8099 envelope ({t_arr[_iv[0]]:.0f} s, "
                f"α up to {_alpha_deg[_iv_pk]:.0f}° at "
                f"q {_q_pa[_iv_pk]/1e3:.0f} kPa — set an α limit)")
            _insert_chrono(_row_av)

    # Diagnostic glide-regime verdict (skip / capture / plunge) for lifting
    # glide RVs.  See glide_regime.py and GLIDE_CAPTURE_DESIGN.md.
    _glide_regime = None
    try:
        _ro_gr = effective_ro(params)
        _GLIDE_MODES = ('skip_glide', 'damped_glide', 'dynamic_equilibrium_glide',
                        'equilibrium_glide', 'equilibrium_glide_acton',
                        'skip_to_equilibrium')
        if (_ro_gr is not None and not orbital
                and getattr(_ro_gr, 'glider_guidance', None) in _GLIDE_MODES):
            from glide_regime import classify_glide_regime
            _gr = classify_glide_regime(
                np.asarray(alts) / 1000.0, np.asarray(speeds), np.asarray(t_arr),
                g_limit_g=float(getattr(_ro_gr, 'glider_pullup_g_max', 10.0)))
            _glide_regime = {
                'verdict': _gr.verdict, 'a_max_g': _gr.a_max_g,
                'n_reascents': _gr.n_reascents, 'above_frac': _gr.above_frac,
                'glide_frac': _gr.glide_frac, 'min_alt_km': _gr.min_alt_km,
                'notes': _gr.notes,
            }
    except Exception:
        _glide_regime = None

    return {
        'reentry_trim':       _reentry_trim,   # static-margin / trim-gate verdict, or None
        'derived_beta_kg_m2': _derived_beta_ref,  # β derived from body geometry (ref Mach), or None
        't':                  t_arr,
        'lat':                lats,
        'lon':                lons,
        'alt':                alts,
        'heating_fom':        _heating_fom,     # heating survivability (heating.py)
        'heating_arc':        _heating_arc,     # reentry-arc arrays + profile (survivability report)
        'speed':              speeds,          # ECEF-frame (ground speed), m/s
        'inertial_speed':     inertial_speeds, # ECI-frame (inertial speed), m/s
        'accel':              accels,
        'mass':               masses,
        'range':              ranges,
        'pos_ecef':           pos_arr,
        'vel_ecef':           vel_arr,
        'orbital':            orbital,
        'impact_lat':         None if orbital else lats[-1],
        'impact_lon':         None if orbital else lons[-1],
        'range_km':           None if orbital else _range_km_geodesic,
        'apogee_km':          np.max(alts) / 1000.0,
        'apogee_lat_deg':     lats[apo_idx],
        'apogee_lon_deg':     lons[apo_idx],
        'time_of_flight_s':   None if orbital else t_arr[-1],
        'impact_speed_ms':    None if orbital else speeds[-1],
        'milestones':            milestones,
        'debris_trajectories':   _debris_trajectories,
        'orbital_elements':      _orb_elements,
        'pitch_cmd_deg':         _pitch_cmd,
        'az_cmd_deg':            _az_cmd,
        # Ascent combined-load traces (SP-8099): flown α, raw commanded α
        # (differs from flown only while the α-limit is engaged), dynamic
        # pressure (Pa), and the q·α design metric (kPa·°).  α-based arrays
        # are NaN outside powered flight / below the kick-hold speed.
        'alpha_deg':             _alpha_deg,
        'alpha_cmd_deg':         _alpha_cmd_deg,
        'q_pa':                  _q_pa,
        'q_alpha_kpa_deg':       _q_alpha_kpa_deg,
        'lateral_g':             _lateral_g,
        'alpha_limit_engaged':   _alpha_limit_engaged,
        'alpha_induced_drag':    bool(getattr(params, '_alpha_induced_drag', False)),
        'glide_regime':          _glide_regime,
    }


def aim_booster(params: BoosterParams,
                launch_lat_deg: float,
                launch_lon_deg: float,
                launch_azimuth_deg: float,
                target_range_km: float,
                guidance: str = None,
                burnout_angle_deg: float = None,
                gt_turn_start_s: float = 5.0,
                gt_turn_stop_s: float = None) -> float:
    """
    Find the engine cutoff time (seconds) that produces the desired range.

    Returns cutoff_time_s.
    """
    from scipy.optimize import brentq

    la = burnout_angle_deg if burnout_angle_deg is not None else params.burnout_angle_deg

    def range_error(cutoff):
        r = integrate_trajectory(params, launch_lat_deg, launch_lon_deg,
                                 launch_azimuth_deg,
                                 guidance=guidance,
                                 burnout_angle_deg=la,
                                 cutoff_time_s=cutoff,
                                 gt_turn_start_s=gt_turn_start_s,
                                 gt_turn_stop_s=gt_turn_stop_s)
        return r['range_km'] - target_range_km

    total_burn = total_burn_time(params)
    lo, hi = 5.0, total_burn
    try:
        cutoff = brentq(range_error, lo, hi, xtol=1.0, maxiter=50)
    except ValueError:
        cutoff = total_burn
    return cutoff


def find_range(params: BoosterParams,
               launch_lat_deg: float,
               launch_lon_deg: float,
               launch_azimuth_deg: float,
               burnout_angle_deg: float = None,
               cutoff_time_s: float = None) -> float:
    """Return the range (km) for the given burnout angle and cutoff time."""
    result = integrate_trajectory(
        params, launch_lat_deg, launch_lon_deg, launch_azimuth_deg,
        burnout_angle_deg=burnout_angle_deg,
        cutoff_time_s=cutoff_time_s,
    )
    return result['range_km']


# ---------------------------------------------------------------------------
# Orbital insertion planner
# ---------------------------------------------------------------------------

def plan_orbital_insertion(params: BoosterParams,
                           launch_lat_deg: float,
                           launch_lon_deg: float,
                           launch_azimuth_deg: float,
                           target_orbit_alt_km: float,
                           gt_turn_start_s: float = 5.0) -> dict:
    """
    Automatically find the two-phase pitch program for orbital insertion.

    Searches for the boost_angle_deg (applied to all pre-final stages) that,
    combined with a horizontal final-stage burn and energy-based cutoff,
    achieves a stable orbit with perigee as close as possible to
    target_orbit_alt_km.

    The final stage always burns at 0° (horizontal), regardless of the boost
    angle.  The turn_stop is automatically set to just before final-stage
    ignition.  This works for 2-, 3-, or 4-stage vehicles; the final stage is
    identified dynamically by walking the stage chain.

    Parameters
    ----------
    params               : BoosterParams (top-level stage)
    launch_lat/lon_deg   : geodetic launch coordinates
    launch_azimuth_deg   : launch azimuth clockwise from North
    target_orbit_alt_km  : desired circular orbit altitude (km)
    gt_turn_start_s      : time to start pitching (s); default 5 s

    Returns
    -------
    dict with keys:
        success          : bool
        boost_angle_deg  : found boost angle for pre-final stages (°)
        turn_stop_s      : pitch end time (s)
        perigee_km       : achieved perigee altitude (km)
        apogee_km        : achieved apogee altitude (km)
        message          : human-readable result summary
    """
    # Compute final-stage ignition time and auto turn-stop.
    _t_fi = 0.0
    _node = params
    while _node.stage2 is not None:
        _t_fi += _node.burn_time_s + _node.coast_time_s
        _node = _node.stage2
    turn_stop_s = max(_t_fi - 1.0, gt_turn_start_s + 1.0)

    # Evaluate orbits at natural burnout rather than running the full 3-hour
    # simulation.  A low-perigee insertion orbit (e.g. 80 km) decays rapidly
    # due to atmospheric drag: the vehicle re-enters within a few orbits, which
    # causes _hit_ground to fire and orbital=False even though insertion was
    # achieved.  By capping max_time at natural burnout we check orbital elements
    # at the moment of engine cutoff, before drag has time to degrade the orbit.
    _natural_burnout = total_burn_time(params)
    _eval_max_time = _natural_burnout

    def _eval(boost_angle):
        """Return (perigee_km, apogee_km) for this boost angle, or (None, None)."""
        r = integrate_trajectory(
            params, launch_lat_deg, launch_lon_deg, launch_azimuth_deg,
            guidance="orbital_insertion",
            burnout_angle_deg=float(boost_angle),
            gt_turn_start_s=gt_turn_start_s,
            gt_turn_stop_s=turn_stop_s,
            target_orbit_alt_km=target_orbit_alt_km,
            max_time_s=_eval_max_time,
            _search_mode=True)
        return r.get('perigee_km'), r.get('apogee_km')

    # Coarse grid: 5° to 80° in 5° steps (run in parallel).
    coarse_angles = list(range(5, 81, 5))
    coarse_results = {}
    with ThreadPoolExecutor(max_workers=min(len(coarse_angles), 8)) as ex:
        futs = {ex.submit(_eval, a): a for a in coarse_angles}
        for fut in as_completed(futs):
            coarse_results[futs[fut]] = fut.result()

    orbital_coarse = [(a, p, ap) for a, (p, ap) in coarse_results.items()
                      if p is not None]
    if not orbital_coarse:
        return {
            'success': False,
            'message': ('No orbital solution found across boost angles 5°–80°.  '
                        'Check that the booster has sufficient delta-V for the '
                        f'target orbit ({target_orbit_alt_km:.0f} km).'),
        }

    # Best coarse angle: perigee closest to target altitude.
    best_a, best_p, best_ap = min(orbital_coarse,
                                  key=lambda x: abs(x[1] - target_orbit_alt_km))

    # Fine grid: ±5° around best coarse angle in 1° steps.
    fine_lo = max(1, best_a - 5)
    fine_hi = min(85, best_a + 6)
    fine_angles = [a for a in range(fine_lo, fine_hi)
                   if a not in coarse_results]
    fine_results = dict(coarse_results)
    if fine_angles:
        with ThreadPoolExecutor(max_workers=min(len(fine_angles), 8)) as ex:
            futs = {ex.submit(_eval, a): a for a in fine_angles}
            for fut in as_completed(futs):
                fine_results[futs[fut]] = fut.result()

    orbital_fine = [(a, p, ap) for a, (p, ap) in fine_results.items()
                    if p is not None]
    best_a, best_p, best_ap = min(orbital_fine,
                                  key=lambda x: abs(x[1] - target_orbit_alt_km))

    return {
        'success':         True,
        'boost_angle_deg': best_a,
        'turn_stop_s':     turn_stop_s,
        'perigee_km':      best_p,
        'apogee_km':       best_ap,
        'message': (f'Boost angle {best_a}°  →  '
                    f'{best_p:.0f} × {best_ap:.0f} km orbit'),
    }


# ---------------------------------------------------------------------------
# Parallel search worker — module-level so it is importable by worker threads
# ---------------------------------------------------------------------------

def _search_one(args):
    """
    Evaluate a single (burnout_angle, turn_stop) candidate and return
    range_km, or -1.0 on failure / orbital.

    All arguments are passed as a single tuple so the function can be
    submitted to concurrent.futures without lambda.
    """
    (la, ts,
     params, lat, lon, az,
     guidance, cutoff, gt_start, max_time_s,
     terrain_dem, launch_elev_m) = args
    ts_str = f"ts={ts:.1f}s" if ts is not None else "ts=full"
    try:
        r = integrate_trajectory(
            params, lat, lon, az,
            guidance=guidance,
            burnout_angle_deg=la,
            cutoff_time_s=cutoff,
            gt_turn_start_s=gt_start,
            gt_turn_stop_s=ts,
            max_time_s=max_time_s,
            terrain_dem=terrain_dem,
            launch_elev_m=launch_elev_m,
            _search_mode=True,
        )
        if r.get('orbital', False):
            print(f"  [{la:.1f}° {ts_str}] → ORBITAL")
            return -1.0
        rng = float(r.get('range_km') or -1.0)
        return rng
    except Exception as e:
        print(f"  [{la:.1f}° {ts_str}] → ERROR {type(e).__name__}: {e}")
        return -1.0


def _tsiolkovsky_dv(params: BoosterParams) -> float:
    """Ideal (vacuum) delta-V: sum Tsiolkovsky rocket equation over all stages."""
    G0 = 9.80665
    dv, node = 0.0, params
    while node is not None:
        if node.burn_time_s > 0 and node.mass_propellant > 0:
            m_bo = node.mass_initial - node.mass_propellant
            if node.mass_initial > m_bo > 0:
                dv += node.isp_s * G0 * np.log(node.mass_initial / m_bo)
        node = node.stage2
    return dv


def _wheelon_gamma_opt(v_bo: float, burnout_alt_m: float = 150_000.0) -> float:
    """
    Wheelon optimal burnout elevation angle above local horizontal (degrees).
    γ_opt = ½ arccos(Q / (2 − Q)),  Q = V²/(g_bo · r_bo).
    """
    r_bo = RE + burnout_alt_m
    g_bo = GM / r_bo ** 2
    Q = min(v_bo ** 2 / (g_bo * r_bo), 0.9999)
    cos_2g = max(-1.0, min(1.0, Q / (2.0 - Q)))
    return 0.5 * np.degrees(np.arccos(cos_2g))


def wheelon_burnout_angle(params: BoosterParams) -> float:
    """Estimated Wheelon-optimal burnout elevation angle (deg) for max range.

    Public one-shot estimator: derives an ideal burnout speed from the
    Tsiolkovsky delta-V (de-rated for gravity/drag losses the way
    maximize_range seeds its search) and returns the Wheelon gamma_opt.  This
    is the same estimate maximize_range narrows its grid around, exposed so the
    GUI can fill the burnout-angle field without a full range sweep.
    """
    _dv_ideal = _tsiolkovsky_dv(params)
    _v_bo_est = max(1000.0, _dv_ideal * 0.82 - 300.0)
    return _wheelon_gamma_opt(_v_bo_est)


def maximize_range(params: BoosterParams,
                   launch_lat_deg: float,
                   launch_lon_deg: float,
                   launch_azimuth_deg: float = 0.0,
                   guidance: str = None,
                   burnout_angle_deg: float = None,
                   cutoff_time_s: float = None,
                   gt_turn_start_s: float = 5.0,
                   gt_turn_stop_s: float = None,
                   reentry_query_alt_km: float = None,
                   cancel_event: threading.Event = None,
                   terrain_dem: bool = False,
                   launch_elev_m: float = None) -> dict:
    """
    Find the maximum range by optimising burnout angle and turn-stop time.

    If burnout_angle_deg is provided, the trajectory is run with that fixed
    burnout angle (no angle optimisation).  gt_turn_stop_s is also optimised
    when it is None (not user-specified).  A short turn_stop allows the vehicle
    to reach its burnout angle early and hold it flat, which dramatically
    increases range for multi-stage vehicles with long total burn times.

    Returns the full trajectory dict plus:
        'max_range_km'            : achieved maximum range (km)
        'optimal_burnout_angle_deg'  : best burnout angle (°)
        'optimal_gt_turn_stop_s'  : best turn-stop time (s)
    """
    total_burn = total_burn_time(params)
    effective_cutoff = cutoff_time_s if cutoff_time_s is not None else total_burn
    effective_guidance = guidance if guidance is not None else params.guidance

    # Wheelon optimal angle: narrow the coarse-grid search window.
    _dv_ideal  = _tsiolkovsky_dv(params)
    _v_bo_est  = max(1000.0, _dv_ideal * 0.82 - 300.0)
    _gamma_opt = _wheelon_gamma_opt(_v_bo_est)
    _angle_lo  = max(5.0,  _gamma_opt - 10.0)
    _angle_hi  = min(80.0, _gamma_opt + 10.0)

    # If burnout angle is supplied, run with that fixed value (no angle search).
    if burnout_angle_deg is not None:
        traj = integrate_trajectory(
            params, launch_lat_deg, launch_lon_deg, launch_azimuth_deg,
            guidance=guidance,
            burnout_angle_deg=burnout_angle_deg,
            cutoff_time_s=effective_cutoff,
            gt_turn_start_s=gt_turn_start_s,
            gt_turn_stop_s=gt_turn_stop_s,
            terrain_dem=terrain_dem,
            launch_elev_m=launch_elev_m,
        )
        traj['max_range_km']           = traj['range_km']
        traj['optimal_burnout_angle_deg'] = burnout_angle_deg
        traj['optimal_gt_turn_stop_s'] = (gt_turn_stop_s if gt_turn_stop_s is not None
                                          else total_burn)
        return traj

    # Number of parallel workers — use all physical cores; cap at 8 so we
    # don't thrash on hyperthreaded machines with many logical CPUs.
    n_workers = min(8, os.cpu_count() or 1)

    # Common kwargs passed unchanged to every _search_one call.
    _common = (params, launch_lat_deg, launch_lon_deg, launch_azimuth_deg,
               effective_guidance, effective_cutoff, gt_turn_start_s, 3600.0,
               terrain_dem, launch_elev_m)

    def _run_parallel(candidates, label="coarse"):
        """Submit a list of (la, ts) pairs; return (la, ts, range_km) list.

        Raises MaxRangeCancelled if cancel_event is set between completions.
        """
        jobs = [(*c, *_common) for c in candidates]
        results = []
        n_total = len(jobs)
        running_best = -1.0
        print(f"  [{label}] {n_total} candidates, {n_workers} workers")
        # ThreadPoolExecutor can be safely called from daemon threads
        # (e.g. thrusty's _run_thread on macOS), and scipy's solve_ivp
        # releases the GIL during its inner loops, giving genuine parallelism.
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futures = {ex.submit(_search_one, j): j for j in jobs}
            for n_done, fut in enumerate(as_completed(futures), 1):
                if cancel_event is not None and cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    raise MaxRangeCancelled()
                la, ts = futures[fut][:2]
                rng = fut.result()
                results.append((la, ts, rng))
                if rng > running_best:
                    running_best = rng
                    ts_str = f"ts={ts:.1f}s" if ts is not None else "ts=full"
                    print(f"  [{label}] {n_done}/{n_total}  "
                          f"new best {rng:.1f} km @ {la:.1f}° {ts_str}")
        print(f"  [{label}] done — best {running_best:.1f} km")
        return results

    best_range = -1.0
    best_la    = params.burnout_angle_deg
    best_ts    = total_burn if gt_turn_stop_s is None else gt_turn_stop_s

    if effective_guidance == "pitch_program":
        ts_min = gt_turn_start_s + 5.0
        if gt_turn_stop_s is None:
            # Dense 2-s steps over the early window where the range peak is
            # narrow; coarser sampling for longer turn-stop values.
            _early = [ts_min + 2.0 * i
                      for i in range(int((min(40.0, effective_cutoff) - ts_min) / 2.0) + 1)]
            _late  = [45.0, 60.0, 90.0,
                      min(120.0, effective_cutoff),
                      min(180.0, effective_cutoff),
                      effective_cutoff]
            ts_candidates = sorted({t for t in _early + _late
                                    if ts_min <= t <= effective_cutoff})
        else:
            ts_candidates = [gt_turn_stop_s]

        # ── Phase 1: coordinate-descent over (burnout_angle, turn_stop) ──
        # The full 2-D grid is len(angles) × len(ts) trajectories, and with the
        # EOM holding the GIL the ThreadPool gives little real parallelism, so
        # that product was the whole "runs forever" cost.  Burnout angle and
        # turn-stop are only mildly coupled, so a coordinate descent recovers
        # the same optimum in ~1/4 the trajectories — provided it STARTS from a
        # good line rather than an arbitrary corner.  The Wheelon estimate
        # _gamma_opt is exactly that: a physics-based near-optimal burnout
        # angle, so the descent seeds the angle there, sweeps the turn-stop
        # along it, then sweeps the angle at the winning turn-stop, then re-
        # sweeps the turn-stop at the winning angle.  Phase 2's minimize_scalar
        # polishes the angle.  Validated against the full grid in
        # test_max_range_search.py.
        _angles = [float(ba)
                   for ba in np.arange(_angle_lo, _angle_hi + 1.0, 2.0)]
        # Angle nearest the Wheelon optimum seeds the first turn-stop sweep.
        _seed_angle = min(_angles, key=lambda a: abs(a - _gamma_opt))

        def _absorb(results):
            nonlocal best_range, best_la, best_ts
            for la, ts, rng in results:
                if rng > best_range:
                    best_range, best_la, best_ts = rng, la, ts

        if len(ts_candidates) > 1:
            # Round 1 — turn-stop sweep along the Wheelon-optimal angle.
            _absorb(_run_parallel([(_seed_angle, ts) for ts in ts_candidates],
                                  label="turn-stop"))
            _ts0 = best_ts
            # Round 2 — angle sweep at the best turn-stop.
            _absorb(_run_parallel([(ba, best_ts) for ba in _angles],
                                  label="angle"))
            # Round 3 — turn-stop re-sweep at the best angle, only if the angle
            # moved (else Round 1 already covered this line).  This is the step
            # that recovers a coupled optimum whose best turn-stop shifts with
            # the angle.
            if best_la != _seed_angle:
                _absorb(_run_parallel([(best_la, ts) for ts in ts_candidates],
                                      label="turn-stop₂"))
        else:
            # A single (user-fixed) turn-stop: just sweep the angle along it.
            _absorb(_run_parallel([(ba, ts_candidates[0]) for ba in _angles],
                                  label="angle"))

        # ── Phase 2: single minimize_scalar at the coarse-best turn_stop ──
        # The coarse grid already found the best ts; running minimize_scalar
        # over every ts candidate (the old approach) adds ~400 serial calls.
        # One bounded 1-D search at best_ts converges in ~10–15 evaluations.
        if cancel_event is not None and cancel_event.is_set():
            raise MaxRangeCancelled()

        def _neg_range_gt(ba, _ts=best_ts):
            if cancel_event is not None and cancel_event.is_set():
                return 0.0   # scalar must return a number; optimizer will stop at maxiter
            r = _search_one((float(ba), _ts, *_common))
            return -r if r > 0 else 0.0

        lo = max(1.0,  best_la - 8.0)
        hi = min(80.0, best_la + 8.0)
        res = minimize_scalar(_neg_range_gt, bounds=(lo, hi),
                              method='bounded',
                              options={'xatol': 0.25, 'maxiter': 20})
        if cancel_event is not None and cancel_event.is_set():
            raise MaxRangeCancelled()
        if -res.fun > best_range:
            best_range, best_la = -res.fun, float(res.x)

    if best_range < 0.0:
        # Every candidate was orbital or failed; return as-is so the caller
        # can display a sensible "in orbit" message.
        traj = integrate_trajectory(
            params, launch_lat_deg, launch_lon_deg, launch_azimuth_deg,
            guidance=guidance,
            burnout_angle_deg=params.burnout_angle_deg,
            cutoff_time_s=effective_cutoff,
            gt_turn_start_s=gt_turn_start_s,
            gt_turn_stop_s=gt_turn_stop_s,
            reentry_query_alt_km=reentry_query_alt_km,
            terrain_dem=terrain_dem,
            launch_elev_m=launch_elev_m,
        )
        traj['max_range_km']           = None
        traj['optimal_burnout_angle_deg'] = None
        traj['optimal_gt_turn_stop_s'] = None
        return traj

    # Final full-fidelity integration at the optimal parameters.
    traj = integrate_trajectory(
        params, launch_lat_deg, launch_lon_deg, launch_azimuth_deg,
        guidance=guidance,
        burnout_angle_deg=best_la,
        cutoff_time_s=effective_cutoff,
        gt_turn_start_s=gt_turn_start_s,
        gt_turn_stop_s=best_ts,
        reentry_query_alt_km=reentry_query_alt_km,
        terrain_dem=terrain_dem,
        launch_elev_m=launch_elev_m,
    )
    traj['max_range_km']           = traj['range_km']
    traj['optimal_burnout_angle_deg'] = best_la
    traj['optimal_gt_turn_stop_s'] = best_ts
    return traj
