"""
One-dimensional conduction estimate for a solid conical tip.

A sharp, solid tip is not a radiating skin.  Heat arriving at the point is
carried back into the body and shed from the much larger flank, so the
radiating-wall balance of heating_locations.radiating_wall() overstates the
tip temperature badly (SHEFEX II: 3100-3200 K against about 1900 K).  This
module replaces that balance, for solid parts only, with transient heat
conduction along the axis of the cone:

    rho c A(s) dT/dt = d/ds( k A(s) dT/ds ) + P(s) [ q_conv(s, T) - eps sigma T^4 ]

    s      distance along the axis from the cone's virtual apex
    A(s)   cross-section area, pi (s tan d)^2
    P(s)   lateral surface per unit axial length, 2 pi s tan d / cos d
    d      cone half angle

Temperature is taken as uniform over each cross-section, which is the
one-dimensional approximation: it holds where the section is small compared
with the distance heat has diffused, i.e. near the tip.  It is an ENGINEERING
estimate allowed by the project rule, not a thermal design tool: no variation
across the section, no temperature-dependent properties, no ablation, no
oxidation, no contact resistance at the mount.

HEATING
  Tip cap   Tauber TP-2914 Eq. (40), stagnation point.  The heat entering a
            spherical cap whose flux falls as the cosine of the body angle is
            the stagnation flux times the cap's PROJECTED area (TP-2914
            section 2.5; the cosine law holds to about 70 degrees).
  Flank     Tauber TP-2914 Eq. (46), laminar sharp cone, capped at the
            stagnation value so the flank never exceeds the tip.
  Both come from heating_locations and carry its hot-wall term.

BOUNDARIES
  The base of the cone is adiabatic.  Over a heating pulse of tens of seconds
  the heat has not reached the base of a cone some 10 cm long (diffusion
  length sqrt(alpha t) is about 2-3 cm in 100 s for a ceramic composite), so
  the choice does not affect the tip region.

NUMERICS
  Finite volumes along the axis, fine at the tip and growing geometrically.
  Conduction is implicit; the surface terms are linearised about the current
  temperature, so the step is stable where the tip cells have very little
  mass for their surface.  The scheme conserves energy exactly: the change in
  stored heat equals the net heat through the surface (tested).
"""

import numpy as np
from scipy.linalg import solve_banded

import heating_locations as hl

SIGMA = hl.SIGMA

# Accuracy against named cases, recomputed by test_heating_solid.py.
# Figures are (computed / measured - 1) on absolute temperature.
ACCURACY = {
    "solid_cone_tip": {
        "cases": [
            dict(case="SHEFEX II flight, thermocouple 20 mm behind the tip",
                 temperature=+0.05),
            dict(case="SHEFEX II arc-jet, thermocouple 20 mm behind the tip",
                 temperature=+0.02),
        ],
        "sources": "Bohrk et al., AIAA 2012-5919 (tip radius, material "
                   "Table 1, arc-jet Table 2, thermocouple peaks 848 C in "
                   "flight and 1179 C in the arc-jet)",
        "note": "Flight path rebuilt from the paper's stated end points "
                "(101 km at 2559 m/s to 30 km at 2791 m/s in 52 s) on the US "
                "Standard Atmosphere 1976; cone half angle from the stated "
                "mass, density and length.  The arc-jet is treated as the "
                "paper's authors treated it, as flight at the tunnel's "
                "density, speed and static temperature; with the tunnel's "
                "full 11.9 MJ/kg the same thermocouple comes out about 24% "
                "high, the difference being chemical energy a ceramic wall "
                "does not recover.  The tip itself was not measured: this "
                "model gives 2110 K in the arc-jet against 1908 K from the "
                "authors' own two-dimensional heat-balance code.",
    },
}


def equivalent_cone_half_angle_deg(mass_kg, density_kg_m3, length_m):
    """Half angle of the right circular cone with the given mass, density and
    length.  For a faceted tip (SHEFEX II is an octagonal pyramid) this is the
    cone of equal volume."""
    r_base = np.sqrt(3.0 * mass_kg / (density_kg_m3 * np.pi * length_m))
    return float(np.degrees(np.arctan(r_base / length_m)))


def _mesh(tip_radius_m, half_angle_deg, length_m, n_cells, growth):
    d = np.radians(half_angle_deg)
    tan, cos, sin = np.tan(d), np.cos(d), np.sin(d)
    # axial station, measured from the virtual apex, where the cap meets the cone
    s0 = tip_radius_m * cos / tan
    w = growth ** np.arange(n_cells)
    w = w / w.sum() * length_m
    faces = s0 + np.concatenate([[0.0], np.cumsum(w)])
    centres = 0.5 * (faces[1:] + faces[:-1])
    A_face = np.pi * (faces * tan) ** 2
    volume = np.pi * tan ** 2 * (faces[1:] ** 3 - faces[:-1] ** 3) / 3.0
    A_side = np.pi * tan * (faces[1:] ** 2 - faces[:-1] ** 2) / cos
    # spherical cap ahead of the tangency plane, lumped into the first cell
    cap_volume = np.pi * tip_radius_m ** 3 * (2.0 / 3.0 - sin + sin ** 3 / 3.0)
    cap_area = 2.0 * np.pi * tip_radius_m ** 2 * (1.0 - sin)
    cap_projected = np.pi * (tip_radius_m * cos) ** 2
    volume = volume.copy()
    volume[0] += cap_volume
    return dict(s0=s0, centres=centres, A_face=A_face, volume=volume,
                A_side=A_side, cap_area=cap_area, cap_projected=cap_projected,
                x_surface=centres / cos)


def cone_tip_response(t, rho, V, T_inf, *, tip_radius_m, half_angle_deg,
                      length_m, density_kg_m3, specific_heat_J_kgK,
                      conductivity_W_mK, emissivity=0.85, T_initial_K=300.0,
                      n_cells=120, growth=1.04, dt_max_s=0.05,
                      stagnation_constant=hl.STAG_C, wall_enthalpy=None):
    """Temperature history along the axis of a solid conical tip.

    t, rho, V, T_inf : 1-D arrays over the heating arc (s, kg/m^3, m/s, K).
    conductivity_W_mK : conductivity ALONG THE AXIS.  A fibre composite
        conducts differently along and across the fibres; use the axial value.

    Returns a dict:
      x_from_tip_m   cell centres, measured back from the cap junction
      T_K            array [len(t), n_cells], section-mean temperature
      T_tip_K        array [len(t)], the first cell
      stored_J       heat stored in the tip at each time, relative to the start
      net_surface_J  net heat through the surface up to each time
      accuracy       ACCURACY["solid_cone_tip"]
    """
    t = np.asarray(t, float); rho = np.asarray(rho, float)
    V = np.asarray(V, float); T_inf = np.asarray(T_inf, float)
    eps = float(emissivity)
    m = _mesh(tip_radius_m, half_angle_deg, length_m, int(n_cells), growth)
    sc, vol, A_side = m["centres"], m["volume"], m["A_side"]
    n = sc.size
    G = conductivity_W_mK * m["A_face"][1:-1] / (sc[1:] - sc[:-1])
    C = density_kg_m3 * specific_heat_J_kgK * vol

    def surface_power(T, rho_i, V_i, Tinf_i):
        """Net heat into each cell through its outer surface, W."""
        if rho_i > 0.0 and V_i > 0.0:
            q_stag = hl.stagnation_point_flux(
                rho_i, V_i, tip_radius_m, T, Tinf_i,
                constant=stagnation_constant, wall_enthalpy=wall_enthalpy)
            q_flank = np.minimum(
                hl.laminar_surface_flux(rho_i, V_i, m["x_surface"],
                                        half_angle_deg, T, Tinf_i, cone=True,
                                        wall_enthalpy=wall_enthalpy),
                q_stag)
        else:
            q_stag = np.zeros(n); q_flank = np.zeros(n)
        S = A_side * (q_flank - eps * SIGMA * T ** 4)
        S[0] += (m["cap_projected"] * q_stag[0]
                 - m["cap_area"] * eps * SIGMA * T[0] ** 4)
        return S

    T = np.full(n, float(T_initial_K))
    E0 = float(np.sum(C * T))
    history = [T.copy()]
    stored = [0.0]
    net = [0.0]
    net_running = 0.0
    for j in range(1, t.size):
        span = t[j] - t[j - 1]
        n_sub = max(1, int(np.ceil(span / dt_max_s)))
        dt = span / n_sub
        for k in range(n_sub):
            f = (k + 0.5) / n_sub
            rho_i = rho[j - 1] + f * (rho[j] - rho[j - 1])
            V_i = V[j - 1] + f * (V[j] - V[j - 1])
            Ti = T_inf[j - 1] + f * (T_inf[j] - T_inf[j - 1])
            S = surface_power(T, rho_i, V_i, Ti)
            dS = np.minimum(surface_power(T + 1.0, rho_i, V_i, Ti) - S, 0.0)
            ab = np.zeros((3, n))
            diag = C / dt - dS
            diag[:-1] += G
            diag[1:] += G
            ab[1] = diag
            ab[0, 1:] = -G
            ab[2, :-1] = -G
            T_new = solve_banded((1, 1), ab, C / dt * T + S - dS * T)
            net_running += float(np.sum(S + dS * (T_new - T))) * dt
            T = T_new
        history.append(T.copy())
        stored.append(float(np.sum(C * T)) - E0)
        net.append(net_running)
    history = np.array(history)
    return dict(x_from_tip_m=sc - m["s0"], T_K=history, T_tip_K=history[:, 0],
                stored_J=np.array(stored), net_surface_J=np.array(net),
                accuracy=ACCURACY["solid_cone_tip"])


def temperature_at(result, x_from_tip_m, index=-1):
    """Section-mean temperature at a distance behind the tip, at one output
    time (default: the last)."""
    return float(np.interp(x_from_tip_m, result["x_from_tip_m"],
                           result["T_K"][index]))
