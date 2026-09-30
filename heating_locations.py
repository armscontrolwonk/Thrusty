"""
Engineering-tier convective heating, computed per LOCATION on the vehicle.

One closed-form relation per kind of location, each carrying its own hot-wall
term, followed by a wall energy balance that turns flux into temperature:

    nose cap            stagnation point on a hemisphere          Eq. (40)
    swept cylinder      stagnation line, the leading-edge block   Eq. (41)
    wing leading edge   cylinder + flat plate combined (Rubesin)  Eq. (49)
    windward face       cone or inclined flat plate, laminar      Eqs. (46), (48)
    windward face       the same, turbulent                       Eqs. (56a/b), (59)

and, for the attachment line of a swept edge, laminar or TURBULENT, the
relations of Poll (1981), attachment_line_flux(), described where they are
defined.

Every Tauber equation number refers to

    Tauber, M. E., "A Review of High-Speed, Convective, Heat-Transfer
    Computation Methods", NASA Technical Paper 2914, 1989 (NTRS 19890017745)

read from primary, 2026-09-29.  The constants below are the printed ones; SI
in (kg/m^3, m/s, m, K), W/m^2 out.  Nothing here is fitted or tuned.

A vehicle is a list of locations, not a shape category: a capsule has a nose
cap; a cone has a nose cap and a flank; a glider or space plane has a nose
cap, leading edges and a windward face.

WHAT THIS MODULE DOES NOT DO
  * It is not wired into heating.py's verdicts.  Nothing shipped changes.
  * No conduction into solid parts.  A sharp, solid tip is NOT a radiating
    skin; radiating_wall() overstates its temperature by a large margin (see
    ACCURACY["sharp_tip"]).  Use heating_solid.cone_tip_response() for those.
  * No low-density correction.  Tauber Fig. 8: neglecting wall slip
    overpredicts stagnation heating by 130% at a Knudsen number of 0.1, which
    a sub-millimetre tip reaches at altitude.
  * No surface chemistry.  The relations assume a fully catalytic wall in
    equilibrium air; a non-catalytic wall runs cooler.
  * No blunt-nose entropy layer.  Close behind a blunt nose the windward
    heating is higher than these relations give (Tauber & Adelman 1987).
  * No shock interaction, gap, step or roughness heating.

WALL ENTHALPY
  The hot-wall terms need the enthalpy of air at the wall temperature.  The
  default is the perfect-gas value c_p*T_w with c_p = gamma*R/(gamma-1), built
  from the constants atmosphere.py already uses.  Real air stores more energy
  than that once vibration and dissociation set in, so the default UNDERSTATES
  h_w and therefore OVERSTATES flux and wall temperature.  Pass wall_enthalpy=
  to any function to substitute a better gas model once one is cited.
"""

import numpy as np

from atmosphere import _R as R_AIR, _GAMMA as GAMMA_AIR

SIGMA = 5.670374419e-8                          # Stefan-Boltzmann, W/m^2/K^4
CP_AIR = GAMMA_AIR * R_AIR / (GAMMA_AIR - 1.0)  # perfect-gas c_p, J/(kg K)

# --- Printed constants, Tauber TP-2914 --------------------------------------
STAG_C = 1.83e-4           # Eq. (40), Newtonian stagnation velocity gradient
# "If the velocity gradient value of reference 8 were used in equation (40),
# the constant would increase from 1.83 to 1.90" (p. 7): the Newtonian gradient
# is 7.7% low for a sphere.  Offered as the upper edge of a band, not applied.
STAG_C_MEASURED_GRADIENT = 1.90e-4
CYL_C = 1.29e-4            # Eq. (41)
CYL_SWEEP_K = 0.18         # Eq. (41), (1 - 0.18 sin^2 sweep)
CONE_LAM_C = 4.03e-5       # Eq. (46)
PLATE_LAM_C = 2.42e-5      # Eq. (48)
LAM_RECOVERY_K = 0.40      # Eqs. (46)/(48): h_aw = h_inf + 0.40 V^2
TURB_LO_C = 3.72e-4        # Eq. (56a), 1500 < V <= 3960 m/s
TURB_HI_C = 2.45e-5        # Eq. (56b), V > 3960 m/s
TURB_SPLIT_V = 3960.0      # m/s
TURB_VMIN = 1500.0         # m/s, lower edge of Eq. (56a)'s stated range
TURB_TW_REF_K = 555.0      # Eq. (56a)
TURB_WALL_K = 0.9          # Eq. (56): (0.9 - h_w/H_e)
TURB_CONE_FACTOR = 1.15    # Eq. (59)

# --- Printed constants, Poll (1981) -----------------------------------------
# Poll, D. I. A., "Skin Friction and Heat Transfer at an Infinite Swept
# Attachment Line", The Aeronautical Quarterly 32, Nov. 1981, pp. 299-318.
# Read from primary, 2026-09-29.  Page numbers are the journal's.
POLL_GAMMA = 1.4           # notation, p. 301: "1.4 unless otherwise stated"
POLL_PR = 0.7              # notation, p. 300: "0.7 unless otherwise stated"
POLL_RECOVERY = 0.89       # p. 307: "gamma, Pr and r had constant values of
                           #          1.4, 0.7 and 0.89" - the TURBULENT
                           #          data reduction.  Poll gives no laminar
                           #          recovery factor.
# Laminar recovery factor on the spanwise flow, from Tauber's swept-cylinder
# recovery enthalpy, Eq. (41): h_aw = h_inf + 0.5 V^2 (1 - 0.18 sin^2 sweep),
# which is the edge enthalpy plus (1 - 0.18) of the spanwise kinetic energy.
LAMINAR_EDGE_RECOVERY = 1.0 - CYL_SWEEP_K
POLL_LAM_ST = 0.571        # Eq. (11), p. 304: St_e = 0.571 / (Pr^(2/3) Rbar)
POLL_TURB_ST = 0.0345      # Eq. (14), p. 307
POLL_TURB_RBAR_EXP = 0.42  # Eq. (14)
POLL_TURB_T_EXP = 0.79     # Eq. (14): (T_e / T*)^0.79
POLL_TURB_MU_EXP = 0.21    # Eq. (14): (mu(T*) / mu(T_e))^0.21
POLL_K1 = 0.10             # Eq. (15), p. 308: T* = T_e + 0.10 (T_w - T_e)
POLL_K2 = 0.60             #                        + 0.60 (T_r - T_e)

# How each location did against the test cases, stated per the project rule
# that a heating output carries its own accuracy.  Each figure is
# (computed / reference - 1) and is recomputed by test_heating_locations.py, so
# this record cannot drift from the code.
#   flux        : heat flux
#   temperature : radiating-wall temperature.  Where the reference is a flux
#                 (FIRE II calorimeters), it is the fourth-root equivalent of
#                 the flux error, not a measured wall temperature.
ACCURACY = {
    "nose_cap": {
        "cases": [
            dict(case="FIRE II 1636 s, flight total", flux=+0.22, temperature=+0.05),
            dict(case="FIRE II 1643 s, flight total", flux=+0.18, temperature=+0.04),
            dict(case="FIRE II 1651 s, flight total", flux=-0.02, temperature=-0.01),
            dict(case="Stardust 51 s, detailed computation", flux=-0.29, temperature=-0.08),
            dict(case="Spheres, wind tunnel, 8 cases", flux=+0.03, temperature=+0.01),
        ],
        "sources": "Hash et al., AIAA 2007-605 (Tables I, II and flight totals); "
                   "Liu et al., AIAA 2008-1213 (Table 3); "
                   "Trumble et al., JSR 47(5), 2010; "
                   "Zhou et al., AIAA Journal 61(3), 2023 (Table 1); "
                   "Park et al., Acta Astronautica 187, 2021 (Tables 1, 2)",
        "note": "FIRE II totals add Tauber-Sutton radiative heating "
                "(heating.radiative_flux).  Convective alone is 18-24% below "
                "fully catalytic computation at all three FIRE II points.  "
                "In cold wind-tunnel air the relation is within a few "
                "percent, and reproduces Park et al.'s own evaluation of it "
                "(9.2 and 9.6 W/cm2): the shortfall is confined to "
                "high-enthalpy flight.",
    },
    "windward_face": {
        "cases": [
            dict(case="STS-3 belly, laminar, flat-plate value, flight",
                 flux=-0.25, temperature=-0.07),
            dict(case="STS-3 belly, laminar, cone value, flight",
                 flux=+0.26, temperature=+0.06),
            dict(case="STS-3 belly, turbulent, flat-plate value, flight",
                 flux=+0.18, temperature=+0.04),
        ],
        "sources": "Throckmorton, Hamilton & Zoby, NASA TM 84500, 1982, "
                   "Table I (flight conditions, wall temperature and "
                   "convective heating; L = 32.89 m)",
        "note": "Means over stations x/L 0.194-0.592 at five laminar flight "
                "points (7.40 to 3.44 km/s), and x/L 0.255-0.795 at one "
                "turbulent point (2.21 km/s).  Surface angle taken as the "
                "angle of attack.  Flight lies between the flat-plate and "
                "cone values at 28 of 30 laminar stations: a body of finite "
                "width sheds boundary layer sideways, which a flat plate "
                "cannot and a cone does fully.  Report the pair as a band; "
                "the flat-plate value alone reads low.",
    },
    "leading_edge": {
        "cases": [
            dict(case="Swept cylinders, laminar, wind tunnel, 15 cases",
                 flux=+0.06, temperature=+0.01),
            dict(case="Unswept cylinders, wind tunnel, 3 cases",
                 flux=-0.02, temperature=-0.00),
            dict(case="Swept cylinder, laminar, tunnel density given, 6 runs",
                 flux=+0.10, temperature=+0.02),
            dict(case="Attachment line, laminar, Poll, same 6 runs",
                 flux=-0.07, temperature=-0.02),
            dict(case="Attachment line, turbulent, Poll, 6 tripped runs",
                 flux=-0.26, temperature=-0.07),
            dict(case="Attachment line, laminar, Poll, Bushnell Mach 8, "
                      "4 runs", flux=-0.01, temperature=-0.00),
            dict(case="Attachment line, turbulent, Poll, Bushnell Mach 8, "
                      "9 runs", flux=-0.14, temperature=-0.04),
            dict(case="Swept cylinder, laminar, Eq. 41, Bushnell Mach 8, "
                      "4 runs", flux=+0.14, temperature=+0.03),
        ],
        "sources": "Zhou, Yi, Wang & Li, AIAA Journal 61(3), 2023, Table 1 "
                   "(measured Stanton numbers; radius 5-38 mm, sweep 60 and "
                   "66.5 deg, Mach 6-11.9; stated uncertainty 5-10%); "
                   "Holden & Kolly, AIAA 95-2279, Tables 5 and 7 (the "
                   "tunnel conditions behind Zhou's CUBRC rows, density "
                   "tabulated); Bushnell, NASA TN D-3094, 1965, Figs. 16(b) "
                   "and 17(b) (1 in. cylinder alone at 45 and 60 deg sweep, "
                   "Mach 8; values read from figures; stated accuracy 15%)",
        "note": "Tests the swept-cylinder relation, Eq. (41), which is the "
                "main term of the leading-edge relation, Eq. (49).  Cold "
                "wind-tunnel air at 1.0-2.7 km/s: no real-gas effects, and "
                "the low end of Tauber's stated speed range.  14 of 15 swept "
                "cases are within 20%.  Density recovered from the unit "
                "Reynolds number with Sutherland's law.  Eq. (49) itself, "
                "with its flat-plate term and angle of attack, has no test "
                "case yet: that needs a wing, not a cylinder.  TURBULENT "
                "EDGES: Eq. (41) is laminar, and on six tripped, turbulent "
                "runs the measurement is 1.5 to 2.3 times what it gives.  "
                "attachment_line_flux(turbulent=True), Poll's relation, "
                "reads 20% to 38% low on those runs, which lie outside the "
                "range it was fitted over (Mach 2.4-8, wall at 0.4-1 of "
                "stagnation temperature; these are Mach 10-12 and about "
                "0.25) and which Holden & Kolly say overshoot downstream of "
                "the trips.  Within its fitted range Poll states an RMS "
                "error of 7.1%, maximum 19%.  BUSHNELL's Mach 8 runs, with "
                "the wall at 0.42 of stagnation temperature, lie inside that "
                "range: there Poll's turbulent relation is 5% to 22% low "
                "(mean 14%, about 4% in temperature) and his laminar one "
                "within 4%, so the CUBRC shortfall belongs to the range, "
                "not the transcription.  Density recovered from the "
                "free-stream Reynolds number with Sutherland's law; with "
                "Keyes' law the Bushnell figures rise by 4 to 6 points.  "
                "Whether Bushnell's runs are among the 84 Poll fitted has "
                "not been checked; if they are, this check is not "
                "independent of the fit.",
    },
    "sharp_tip": {
        "cases": [
            dict(case="SHEFEX II arc-jet, 0.8 mm tip", flux=None, temperature=+0.69),
        ],
        "sources": "Bohrk et al., AIAA 2012-5919 (Table 2; tip 1635 C)",
        "note": "A solid tip conducts heat into the body, so the radiating-"
                "wall temperature is far too high.  Do not use "
                "radiating_wall() for solid parts; heating_solid."
                "cone_tip_response() is within 5% of the SHEFEX II "
                "thermocouples.",
    },
}


def wall_enthalpy_perfect_gas(T_wall_K):
    """Enthalpy of air at the wall, J/kg, perfect gas: c_p * T_w.

    Understates h_w at high wall temperature (no vibration or dissociation),
    which overstates flux.  See the module docstring.
    """
    return CP_AIR * np.asarray(T_wall_K, float)


def _h_inf(T_inf_K, h_inf=None):
    """Free-stream static enthalpy, J/kg.  c_p*T_inf for flight; pass h_inf
    directly for a wind tunnel whose stream is already hot or dissociated."""
    if h_inf is not None:
        return np.asarray(h_inf, float)
    return CP_AIR * np.asarray(T_inf_K, float)


def _hot_wall(h_ref, T_wall_K, wall_enthalpy, offset=1.0):
    """(offset - h_w/h_ref), floored at zero: a wall at the recovery enthalpy
    takes in no heat, and this module does not model a wall cooling the gas."""
    h_w = (wall_enthalpy or wall_enthalpy_perfect_gas)(T_wall_K)
    return np.maximum(offset - h_w / h_ref, 0.0)


def stagnation_point_flux(rho, V, nose_radius_m, T_wall_K=0.0, T_inf_K=0.0, *,
                          constant=STAG_C, wall_enthalpy=None, h_inf=None):
    """Nose cap.  Tauber Eq. (40):

        q = 1.83e-4 (rho/r_n)^0.5 V^3 (1 - h_w/H_s),   H_s = h_inf + V^2/2
    """
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    H_s = _h_inf(T_inf_K, h_inf) + 0.5 * V * V
    return (constant * np.sqrt(rho / nose_radius_m) * V ** 3
            * _hot_wall(H_s, T_wall_K, wall_enthalpy))


def swept_cylinder_flux(rho, V, radius_m, sweep_deg, T_wall_K=0.0,
                        T_inf_K=0.0, *, wall_enthalpy=None, h_inf=None):
    """Stagnation line of a swept, infinite cylinder.  Tauber Eq. (41):

        q = 1.29e-4 (rho/r)^0.5 (1 - 0.18 sin^2 L) V^3 (1 - h_w/h_aw) cos L
        h_aw = h_inf + 0.5 V^2 (1 - 0.18 sin^2 L)

    L is the sweepback angle; L = 0 is a cylinder square to the flow.
    """
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    L = np.radians(sweep_deg)
    k = 1.0 - CYL_SWEEP_K * np.sin(L) ** 2
    h_aw = _h_inf(T_inf_K, h_inf) + 0.5 * V * V * k
    return (CYL_C * np.sqrt(rho / radius_m) * k * V ** 3
            * _hot_wall(h_aw, T_wall_K, wall_enthalpy) * np.cos(L))


def laminar_surface_flux(rho, V, x_m, surface_angle_deg, T_wall_K=0.0,
                         T_inf_K=0.0, *, cone=False, wall_enthalpy=None, h_inf=None):
    """Windward face, laminar.  Tauber Eq. (48) for an inclined flat plate or
    wedge, Eq. (46) for a sharp cone (cone=True):

        q = C (rho cos d / x)^0.5 V^3.2 sin d (1 - h_w/h_aw)
        C = 2.42e-5 (plate), 4.03e-5 (cone);   h_aw = h_inf + 0.40 V^2

    AIAA-87-1514's appendix prints 2.53e-5 for the plate; TP-2914 prints
    2.42e-5 "after adjusting the Newtonian values".  The later value is used.

    A flat plate is two-dimensional and a cone sheds its boundary layer all
    round.  The windward face of a body of finite width lies between them:
    STS-3 flight heating falls inside the [plate, cone] pair at 28 of 30
    stations (ACCURACY["windward_face"]).  Evaluate both and report the band.

    d is the angle between the surface and the free stream (cone half angle,
    wedge angle, or a plate's angle of attack); x is the distance back along
    the surface from its leading edge or apex.
    """
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    d = np.radians(surface_angle_deg)
    h_aw = _h_inf(T_inf_K, h_inf) + LAM_RECOVERY_K * V * V
    C = CONE_LAM_C if cone else PLATE_LAM_C
    return (C * np.sqrt(rho * np.cos(d) / x_m) * V ** 3.2 * np.sin(d)
            * _hot_wall(h_aw, T_wall_K, wall_enthalpy))


def turbulent_surface_flux(rho, V, x_m, surface_angle_deg, T_wall_K,
                           T_inf_K=0.0, *, x_transition_m=0.0, cone=False,
                           wall_enthalpy=None, h_inf=None):
    """Windward face, turbulent.  Tauber Eqs. (56a), (56b) for a flat plate,
    times 1.15 for a sharp cone, Eq. (59):

        V <= 3960 m/s:  q = 3.72e-4 (rho sin^2 d cos^2.22 d)^0.8
                            / [(x - x_bt)^0.2 (T_w/555)^0.25]
                            * V^3.37 (0.9 - h_w/H_e)
        V >  3960 m/s:  q = 2.45e-5 (rho sin^2 d cos^2.62 d)^0.8
                            / (x - x_bt)^0.2 * V^3.7 (0.9 - h_w/H_e)

    x_bt is where transition begins; the turbulent layer is taken to start
    there.  Stated validity +/-15% above 1500 m/s.  Eq. (56a) divides by the
    wall temperature, so T_wall_K must be positive; a cold-wall turbulent
    value has no meaning in this relation.  Returns NaN below 1500 m/s.
    """
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    Tw = np.asarray(T_wall_K, float)
    if np.any(Tw <= 0.0):
        raise ValueError("turbulent_surface_flux needs a positive wall "
                         "temperature (Tauber Eq. 56a divides by it)")
    run = x_m - x_transition_m
    if run <= 0.0:
        raise ValueError("x_m must lie downstream of x_transition_m")
    d = np.radians(surface_angle_deg)
    H_e = _h_inf(T_inf_K, h_inf) + 0.5 * V * V
    wall = _hot_wall(H_e, Tw, wall_enthalpy, offset=TURB_WALL_K)
    s2 = np.sin(d) ** 2
    lo = (TURB_LO_C * (rho * s2 * np.cos(d) ** 2.22) ** 0.8
          / (run ** 0.2 * (Tw / TURB_TW_REF_K) ** 0.25) * V ** 3.37 * wall)
    hi = (TURB_HI_C * (rho * s2 * np.cos(d) ** 2.62) ** 0.8
          / run ** 0.2 * V ** 3.7 * wall)
    q = np.where(V > TURB_SPLIT_V, hi, lo)
    q = np.where(V < TURB_VMIN, np.nan, q)
    return q * (TURB_CONE_FACTOR if cone else 1.0)


def leading_edge_flux(rho, V, radius_m, sweep_deg, alpha_deg, x_m,
                      surface_angle_deg, T_wall_K=0.0, T_inf_K=0.0, *,
                      turbulent=False, wall_enthalpy=None, h_inf=None):
    """Cylindrical leading edge of a finite wing.  Tauber Eq. (49), after
    Rubesin:

        q_LE = (q_cyl^2 + q_FP^2 sin^2 L)^0.5 cos(alpha)

    q_cyl from Eq. (41); q_FP from Eq. (48), or from Eq. (56) when the flow
    along the edge is turbulent (Tauber p. 14).

    Tauber & Adelman's earlier paper (AIAA-87-1514, Eq. 15) prints a different
    form, 0.5 (q_0^2 cos^2 L + q_FP^2 sin^2 L)^0.5 cos(alpha), built on the
    SPHERE stagnation value q_0.  The two differ by up to about 40% on the
    cylinder term.  This module follows the 1989 review, whose cylinder-to-
    sphere ratio (1.29/1.83 = 0.705) matches the theoretical 1/sqrt(2).  "For highly swept leading
    edges, equation (49) is limited to small angles of attack, since the
    stagnation line moves from the cylindrical leading edge onto the lower
    surface of the wing as the angle of attack increases."
    """
    q_cyl = swept_cylinder_flux(rho, V, radius_m, sweep_deg, T_wall_K,
                                T_inf_K, wall_enthalpy=wall_enthalpy,
                                h_inf=h_inf)
    if turbulent:
        q_fp = turbulent_surface_flux(rho, V, x_m, surface_angle_deg,
                                      T_wall_K, T_inf_K,
                                      wall_enthalpy=wall_enthalpy,
                                      h_inf=h_inf)
    else:
        q_fp = laminar_surface_flux(rho, V, x_m, surface_angle_deg, T_wall_K,
                                    T_inf_K, wall_enthalpy=wall_enthalpy,
                                    h_inf=h_inf)
    L = np.radians(sweep_deg)
    return (np.sqrt(q_cyl ** 2 + (q_fp * np.sin(L)) ** 2)
            * np.cos(np.radians(alpha_deg)))


def keyes_viscosity(T_K):
    """Viscosity of air, Pa s, by the formula Poll used to reduce the
    turbulent heat-transfer data (Poll 1981, p. 307, after Keyes):

        mu = 1.488e-6 T^(3/2) / (T + 122.1 * 10^(-5/T))

    The turbulent reference-temperature constants were fitted with this law,
    so the turbulent relation is evaluated with it.  Unlike Sutherland's law
    it stays accurate at the very low temperatures of hypersonic tunnels.
    """
    T = np.asarray(T_K, float)
    return 1.488e-6 * T ** 1.5 / (T + 122.1 * 10.0 ** (-5.0 / T))


def attachment_line_state(rho, V, T_inf_K, radius_m, sweep_deg, T_wall_K,
                          *, recovery_factor=POLL_RECOVERY):
    """Flow at the edge of the boundary layer on the attachment line of a
    swept circular cylinder, perfect gas, after Poll (1981).

    The free stream is split into a component normal to the edge,
    U = V cos(sweep), which is brought to rest, and one along it,
    V_e = V sin(sweep), which is carried through the bow shock unchanged.

      T_e    = T_inf (1 + (g-1)/2 M_n^2),   M_n = M cos(sweep)   Eq. (18c)
      p_e    = pitot pressure at M_n (normal shock, then brought to rest);
               for M_n <= 1 there is no shock and the rise is isentropic
      rho_e  = p_e / (R T_e)
      dU/dx  = (2/D) [2 (p_e/rho_e) (1 - p_inf/p_e)]^(1/2)       Eq. (18b)
               the modified-Newtonian value for a circular cylinder; the
               same as Tauber's Eq. (39a), which Tauber says "is accurate
               for the circular cylinder"
      eta    = (nu / (dU/dx))^(1/2),   Rbar = V_e eta / nu       Eqs. (1), (2)
      T_r    = T_e (1 + r (g-1)/2 M_e^2),   M_e = V_e / a_e
      T*     = T_e + 0.10 (T_w - T_e) + 0.60 (T_r - T_e)         Eq. (15)

    Returns a dict of those quantities, with Rbar at edge conditions and
    Rbar_star at the reference temperature.  Viscosity is Keyes' formula.
    The default recovery factor is Poll's turbulent 0.89, the one T* and
    Rbar_star were defined with.

    Holden & Kolly (AIAA 95-2279) report turbulence on the attachment line at
    Rbar_star above 300 to 500 where a wing root or roughness disturbs the
    flow (Poll's earlier value: 245), and above 600 to 800 on a smooth edge.
    """
    g, R = POLL_GAMMA, R_AIR
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    T = np.asarray(T_inf_K, float); Tw = np.asarray(T_wall_K, float)
    L = np.radians(sweep_deg)
    M = V / np.sqrt(g * R * T)
    Mn = M * np.cos(L)
    p = rho * R * T
    with np.errstate(invalid='ignore', divide='ignore'):
        pitot = (((g + 1) / 2 * Mn ** 2) ** (g / (g - 1))
                 * ((g + 1) / (2 * g * Mn ** 2 - (g - 1))) ** (1 / (g - 1)))
    isentropic = (1 + (g - 1) / 2 * Mn ** 2) ** (g / (g - 1))
    p_e = p * np.where(Mn > 1.0, pitot, isentropic)
    T_e = T * (1 + (g - 1) / 2 * Mn ** 2)
    rho_e = p_e / (R * T_e)
    V_e = V * np.sin(L)
    dudx = (2.0 / (2.0 * radius_m)) * np.sqrt(
        2.0 * (p_e / rho_e) * (1.0 - p / p_e))
    M_e = V_e / np.sqrt(g * R * T_e)
    T_r = T_e * (1 + recovery_factor * (g - 1) / 2 * M_e ** 2)
    T_star = T_e + POLL_K1 * (Tw - T_e) + POLL_K2 * (T_r - T_e)
    mu_e, mu_s = keyes_viscosity(T_e), keyes_viscosity(T_star)
    rho_s = p_e / (R * T_star)
    with np.errstate(invalid='ignore', divide='ignore'):
        Rbar = V_e / np.sqrt((mu_e / rho_e) * dudx)
        Rbar_star = V_e / np.sqrt((mu_s / rho_s) * dudx)
    return dict(p_e=p_e, T_e=T_e, rho_e=rho_e, V_e=V_e, M_e=M_e, T_r=T_r,
                T_star=T_star, mu_e=mu_e, mu_star=mu_s, dUdx=dudx,
                Rbar=Rbar, Rbar_star=Rbar_star)


def attachment_line_flux(rho, V, radius_m, sweep_deg, T_wall_K, T_inf_K, *,
                         turbulent=False, recovery_factor=None,
                         prandtl=POLL_PR):
    """Heat flux on the attachment line of a swept cylindrical edge, laminar
    or turbulent.  Poll (1981).

    Laminar, Eq. (11), with every property at the edge of the boundary layer
    (Poll found the edge temperature itself to be the best reference
    temperature for laminar flow, K1 = K2 = 0, p. 303):

        St_e = 0.571 / (Pr^(2/3) Rbar)

    Turbulent, Eqs. (14) and (15):

        St_e = 0.0345 / Pr^(2/3) * (T_e/T*)^0.79 * (mu(T*)/mu(T_e))^0.21
               / Rbar^0.42

    with St_e = h / (c_p rho_e V_e); all quantities from
    attachment_line_state().

    WHAT POLL LEAVES TO THE READER, and what is done here:
      * the heat flux is taken as q = h (T_r - T_w).  Poll never writes it,
        but plots his data against (T_r - T_w) and speaks of "heat transfer
        at the wall (T_r > T_w)";
      * the recovery factor is Poll's 0.89 for turbulent flow; for laminar
        flow, where Poll gives none, it is 0.82, from Tauber's Eq. (41);
      * the edge conditions and the velocity gradient are Poll's Eqs. (18b)
        and (18c), which he prints for the hypersonic case and which are
        used here at any Mach number.

    STATED ACCURACY AND RANGE.  Laminar: within +7% / -14% of the exact
    similar solutions in skin friction, for sweep 0 to 70 degrees.
    Turbulent: fitted to 84 measurements at Mach 2.4 to 8, sweep 10 to 78
    degrees and wall-to-stagnation temperature ratio 0.4 to 1, RMS error
    7.1%, maximum 19%.  Flight at high speed has a colder wall than that
    range, and the relation is a perfect-gas one: see
    ACCURACY["leading_edge"] for how it does outside the range.

    The turbulent relation goes to zero as sweep goes to zero, which Poll
    calls "clearly physically unrealistic" (p. 316): below a critical Rbar
    turbulence is not sustained and the flow is laminar.  Use the laminar
    value there; attachment_line_state() gives Rbar_star to judge by.
    """
    if recovery_factor is None:
        recovery_factor = POLL_RECOVERY if turbulent else LAMINAR_EDGE_RECOVERY
    st = attachment_line_state(rho, V, T_inf_K, radius_m, sweep_deg,
                               T_wall_K, recovery_factor=recovery_factor)
    cp = POLL_GAMMA * R_AIR / (POLL_GAMMA - 1.0)
    dT = np.maximum(st["T_r"] - np.asarray(T_wall_K, float), 0.0)
    if not turbulent:
        # 0.571 rho_e V_e / Rbar, written out so that it stays finite at
        # zero sweep, where V_e and Rbar both vanish
        return (POLL_LAM_ST / prandtl ** (2.0 / 3.0) * cp * dT
                * np.sqrt(st["rho_e"] * st["mu_e"] * st["dUdx"]))
    swept = st["V_e"] > 0.0
    Rbar = np.where(swept, st["Rbar"], 1.0)
    St = (POLL_TURB_ST / prandtl ** (2.0 / 3.0)
          * (st["T_e"] / st["T_star"]) ** POLL_TURB_T_EXP
          * (st["mu_star"] / st["mu_e"]) ** POLL_TURB_MU_EXP
          / Rbar ** POLL_TURB_RBAR_EXP)
    return np.where(swept, St * st["rho_e"] * st["V_e"] * cp * dT, 0.0)


def radiating_wall(flux_of_wall_temperature, emissivity=0.85, *,
                   extra_flux=0.0, T_lo=1.0, T_hi=2.0e4, tol_K=0.01):
    """Temperature of a thin, insulated, radiating skin.

    Solves   q_conv(T_w) + extra_flux = emissivity * sigma * T_w^4   for T_w.

    flux_of_wall_temperature : callable T_w -> convective flux (W/m^2), e.g.
        lambda T: stagnation_point_flux(rho, V, r_n, T, T_inf)
    extra_flux : heating that does not depend on the wall temperature, such
        as hot-gas radiation from heating.radiative_flux (W/m^2).

    Returns (T_wall_K, q_conv_W_m2).  Scalars in, scalars out.

    Convective flux falls with wall temperature and re-radiation rises, so
    the balance has one root and bisection finds it.  With extra_flux = 0 the
    result cannot exceed the temperature at which the hot-wall term vanishes:
    the wall cannot be hotter than the gas heating it.

    Valid ONLY where the surface sheds its heat by radiating: tiles, hot
    structures, thin skins.  Not for solid or sharp parts, where conduction
    into the body governs, and not for ablators, which are judged on heat
    load (heating.py).
    """
    eps = max(float(emissivity), 1e-3)

    def residual(T):
        return float(flux_of_wall_temperature(T)) + extra_flux - eps * SIGMA * T ** 4

    lo, hi = float(T_lo), float(T_hi)
    if residual(lo) <= 0.0:
        return lo, float(flux_of_wall_temperature(lo))
    while hi - lo > tol_K:
        mid = 0.5 * (lo + hi)
        if residual(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    T = 0.5 * (lo + hi)
    return T, float(flux_of_wall_temperature(T))
