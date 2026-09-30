"""
Heating at each place a reentry object's file lists.

A reentry object lists the places on its airframe where heating is judged
(``ROParams.heating_locations``): a nose cap, leading edges, a windward face.
An entry carries only what no other field of the object holds; this module

  suggest_locations(ro)   proposes a list from the hardware already in the
                          file.  Used to fill a file in; never applied
                          silently at load.
  resolve_locations(ro)   gathers, for each listed place, every number the
                          heating relations need, says where each came from,
                          and names the ones the file does not give.
  evaluate_locations(...) runs the relations of heating_locations.py over a
                          flown arc and turns flux into temperature according
                          to how the part is built.

NOTHING IS SUPPLIED THAT THE FILE DOES NOT GIVE.  A place with a missing
number comes back as "cannot be evaluated", naming the number.  In particular
a nose radius left at zero is "not given" here, although the screening
verdicts of heating.py fall back on a bluntness heuristic for it
(booster_models.nose_tip_radius, "a transparent bluntness heuristic, not a
geometric derivation").

HOW FLUX BECOMES TEMPERATURE depends on how the part is built:

  an ablator              judged on heat load, as in heating.py; no wall
  (from its material)     temperature is reported, because it ablates at its
                          own surface temperature
  construction 'skin'     a thin shell that radiates its heat away:
                          heating_locations.radiating_wall
  construction 'solid'    a solid piece that conducts heat inward:
                          heating_solid.cone_tip_response (nose caps only),
                          which needs the material's density, specific heat
                          and conductivity
  construction not given  the radiating-wall temperature, reported as an
                          UPPER BOUND: if the part is in fact solid it runs
                          cooler, by a wide margin at a sharp tip

This module computes; it decides nothing about survival.  The verdicts remain
those of heating.py and survivability_report.py.
"""

import math

import numpy as np

import heating
import heating_locations as hl
import heating_solid
from atmosphere import atmosphere
from booster_models import biconic_angles, clean_heating_locations

# Stations along the windward face, as fractions of body length, at which the
# face is evaluated.  A choice of where to look, not a property of the object.
FACE_STATIONS = (0.25, 0.50, 0.75)
# Wall temperature at which an ablator's incident (cold-wall) flux is quoted.
COLD_WALL_K = 300.0
_FLAT_BOTTOM_FORMS = ("wedge", "half_cone")


def suggest_locations(ro) -> list:
    """A heating-locations list proposed from the hardware already in the
    object: every reentry body has a nose cap and a flank; a leading edge is
    proposed only where the file declares a wing.  No number is proposed, so
    a wing's edge comes back without a radius until someone supplies one."""
    out = [{'kind': 'nose_cap', 'name': 'nose'},
           {'kind': 'windward_face', 'name': 'body'}]
    if (float(getattr(ro, 'wing_sweep_deg', 0.0) or 0.0) > 0.0
            or float(getattr(ro, 'wing_area_m2', 0.0) or 0.0) > 0.0
            or float(getattr(ro, 'wing_span_exposed_m', 0.0) or 0.0) > 0.0):
        out.append({'kind': 'leading_edge', 'name': 'wing', 'of': 'wing'})
    return clean_heating_locations(out)


def _material(key):
    """(catalog entry or None, is_ablator or None)."""
    m = heating.TPS_MATERIALS.get(key) if key else None
    return m, (bool(m.get('is_ablator')) if m else None)


def _body_segments(ro, missing, taken):
    """The body's flank as [(x_start_m, x_end_m, half_angle_deg)], measured
    along the axis from the nose."""
    d = float(getattr(ro, 'diameter_m', 0.0) or 0.0)
    L = float(getattr(ro, 'length_m', 0.0) or 0.0)
    shape = str(getattr(ro, 'shape', '') or '')
    if d <= 0.0:
        missing.append("diameter_m is not given")
    if L <= 0.0:
        missing.append("length_m is not given")
    if shape != 'cone':
        missing.append(
            f"the flank angle: the body shape is {shape or 'not given'!r}, "
            f"not a cone, so diameter and length do not define one")
    if missing:
        return []
    form = str(getattr(ro, 'body_form', '') or 'axisymmetric')
    if bool(getattr(ro, 'biconic', False)) and form == 'axisymmetric':
        b = biconic_angles(d, L, getattr(ro, 'fore_length_m', 0.0),
                           getattr(ro, 'break_diameter_m', 0.0),
                           getattr(ro, 'nose_radius_m', 0.0))
        if b is None:
            missing.append("a valid biconic break: fore_length_m and "
                           "break_diameter_m do not describe one")
            return []
        Lf = float(ro.fore_length_m)
        taken['half_angle_deg'] = ("derived: two cones, from diameter_m, "
                                   "length_m, fore_length_m, break_diameter_m")
        return [(0.0, Lf, float(b[0])), (Lf, L, float(b[1]))]
    taken['half_angle_deg'] = "derived: atan((diameter_m / 2) / length_m)"
    return [(0.0, L, math.degrees(math.atan2(d / 2.0, L)))]


def _attitude(ro):
    """(alpha_deg, where it came from, what is missing or '').

    trim_alpha_deg is 0 when absent.  A body of revolution with no lift
    capability flies ballistically at zero angle of attack, as the
    integrator flies it; any lifting body needs its trim angle stated."""
    a = float(getattr(ro, 'trim_alpha_deg', 0.0) or 0.0)
    if a > 0.0:
        return a, 'trim_alpha_deg', ''
    form = str(getattr(ro, 'body_form', '') or 'axisymmetric')
    lifting = (form != 'axisymmetric'
               or bool(getattr(ro, 'maneuvering', False))
               or float(getattr(ro, 'glider_LD', 0.0) or 0.0) > 0.0)
    if not lifting:
        return 0.0, ("ballistic body of revolution with no lift capability: "
                     "zero angle of attack"), ''
    return None, '', ("trim_alpha_deg is not given: a lifting body flies at "
                      "an angle of attack the file does not state")


def resolve_locations(ro) -> list:
    """Every listed place, with the numbers its heating relations need.

    Returns a list of dicts, one per entry of ``ro.heating_locations``:

      kind, name, source      from the entry
      construction            'skin', 'solid' or '' (not given)
      material, is_ablator    the material key and whether the catalog calls
                              it an ablator (None when there is no material)
      emissivity              the object's
      geometry                the numbers, by name
      taken_from              for each number, the field it came from, or
                              'entry', or how it was derived
      missing                 what the file does not give; empty when the
                              place can be evaluated
    """
    out = []
    eps = float(getattr(ro, 'emissivity', 0.0) or 0.0)
    alpha, alpha_from, alpha_missing = _attitude(ro)
    for e in clean_heating_locations(getattr(ro, 'heating_locations', [])):
        kind = e['kind']
        geo, taken, missing = {}, {}, []
        if kind == 'nose_cap':
            key = ro.nose_material()
            taken['material'] = ('nose_tps_material' if ro.nose_tps_material
                                 else 'tps_material')
            r = float(getattr(ro, 'nose_radius_m', 0.0) or 0.0)
            if r > 0.0:
                geo['radius_m'] = r
                taken['radius_m'] = 'nose_radius_m'
            else:
                missing.append(
                    "nose_radius_m is not given (the screening verdicts use "
                    f"a bluntness heuristic, {ro.effective_nose_radius_m():g}"
                    " m, which is not a measurement)")
            if e.get('construction') == 'solid':
                seg_missing, seg_taken = [], {}
                segs = _body_segments(ro, seg_missing, seg_taken)
                if segs:
                    geo['half_angle_deg'] = segs[0][2]
                    taken['half_angle_deg'] = seg_taken['half_angle_deg']
                else:
                    missing.extend(seg_missing)
                if 'solid_length_m' in e:
                    geo['solid_length_m'] = e['solid_length_m']
                    taken['solid_length_m'] = 'entry'
                else:
                    missing.append("solid_length_m, the length of the solid "
                                   "piece, is not given in the entry")
        elif kind == 'windward_face':
            key = ro.body_material()
            taken['material'] = ('body_tps_material' if ro.body_tps_material
                                 else 'tps_material')
            form = str(getattr(ro, 'body_form', '') or 'axisymmetric')
            flat = form in _FLAT_BOTTOM_FORMS
            geo['flat_bottom'] = flat
            taken['flat_bottom'] = 'body_form'
            if flat:
                # Both lifting forms fly flat side down (booster_models:
                # the wedge's flat bottom, the half cone's diametral plane),
                # so the windward face is a flat surface along the body at
                # the angle of attack alone.
                L = float(getattr(ro, 'length_m', 0.0) or 0.0)
                segs = [(0.0, L, 0.0)] if L > 0.0 else []
                if not segs:
                    missing.append("length_m is not given")
                taken['surface_angle_deg'] = (
                    "flat bottom: the angle of attack alone")
            else:
                segs = _body_segments(ro, missing, taken)
            geo['segments'] = segs
            if alpha_missing:
                missing.append(alpha_missing)
            else:
                geo['alpha_deg'] = alpha
                taken['alpha_deg'] = alpha_from
            if segs and not alpha_missing:
                L = float(ro.length_m)
                geo['stations'] = []
                for f in FACE_STATIONS:
                    x = f * L
                    ang = next(a for x0, x1, a in segs if x0 <= x <= x1)
                    # distance along the surface: each segment's slant length
                    run = sum((min(x, x1) - x0) / math.cos(math.radians(a))
                              for x0, x1, a in segs if x0 < x)
                    geo['stations'].append(
                        dict(x_over_L=f, angle_deg=ang, run_m=run))
        else:                                           # leading_edge
            key = e.get('material', '')
            taken['material'] = 'entry'
            if not key:
                missing.append("material is not given in the entry")
            if 'radius_m' in e:
                geo['radius_m'] = e['radius_m']
                taken['radius_m'] = 'entry'
            else:
                missing.append("radius_m, the edge radius, is not given in "
                               "the entry")
            if e.get('of') == 'wing':
                sw = float(getattr(ro, 'wing_sweep_deg', 0.0) or 0.0)
                if sw > 0.0:
                    geo['sweep_deg'] = sw
                    taken['sweep_deg'] = 'wing_sweep_deg'
                else:
                    missing.append("wing_sweep_deg is not given")
            elif 'sweep_deg' in e:
                geo['sweep_deg'] = e['sweep_deg']
                taken['sweep_deg'] = 'entry'
            else:
                missing.append("sweep_deg is not given in the entry")
        if eps <= 0.0:
            missing.append("emissivity is not given")
        mat, abl = _material(key)
        if key and mat is None:
            missing.append(f"material {key!r} is not in the catalog")
        out.append(dict(kind=kind, name=e.get('name', ''),
                        source=e.get('source', ''),
                        construction=e.get('construction', ''),
                        material=key, is_ablator=abl, emissivity=eps,
                        geometry=geo, taken_from=taken, missing=missing))
    return out


def _wall_history(flux_of_T, eps, extra, n):
    """Radiating-wall temperature at each sample of an arc.  flux_of_T takes
    an array of wall temperatures and returns the convective flux there."""
    lo = np.full(n, 1.0)
    hi = np.full(n, 2.0e4)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        up = flux_of_T(mid) + extra - eps * hl.SIGMA * mid ** 4 > 0.0
        lo = np.where(up, mid, lo)
        hi = np.where(up, hi, mid)
    T = 0.5 * (lo + hi)
    return T, flux_of_T(T)


def _summary(t, q, T_wall=None):
    i = int(np.nanargmax(q))
    out = dict(q_peak_W_m2=float(q[i]), t_peak_s=float(t[i]),
               heat_load_J_m2=float(np.trapezoid(np.nan_to_num(q), t)))
    if T_wall is not None:
        out['T_wall_peak_K'] = float(np.nanmax(T_wall))
    return out


def _thermal(loc, t, flux_of_T, extra=None):
    """Flux history and, where the part radiates, wall temperature."""
    n = t.size
    extra = np.zeros(n) if extra is None else extra
    if loc['is_ablator']:
        q = flux_of_T(np.full(n, COLD_WALL_K)) + extra
        return _summary(t, q), (
            f"ablator: incident flux at a {COLD_WALL_K:.0f} K wall and its "
            f"heat load; judged on load, no wall temperature")
    T, q = _wall_history(flux_of_T, loc['emissivity'], extra, n)
    basis = ("radiating wall" if loc['construction'] == 'skin' else
             "radiating wall, an UPPER BOUND: the entry does not say how the "
             "part is built, and a solid part runs cooler")
    return _summary(t, q + extra, T), basis


def evaluate_locations(ro, t, rho, V, alt, *, T_inf=None) -> list:
    """Heating at each listed place over a flown arc.

    t, rho, V, alt : arrays over the arc (s, kg/m^3, m/s, m).
    T_inf          : free-stream temperature (K); from the atmosphere model
                     at ``alt`` when not given.

    Returns one dict per listed place:
      kind, name, status ('evaluated' | 'cannot be evaluated'), missing,
      material, construction, temperature_basis,
      results : by flow state, each with q_peak_W_m2, t_peak_s,
                heat_load_J_m2 and, where the part radiates, T_wall_peak_K;
                a leading edge and a flat-bottomed face carry a low and a
                high value from two relations
      notes, accuracy (heating_locations.ACCURACY for that kind of place)
    """
    t = np.asarray(t, float); rho = np.asarray(rho, float)
    V = np.asarray(V, float); alt = np.asarray(alt, float)
    if T_inf is None:
        T_inf = np.asarray(atmosphere(np.maximum(alt, 0.0))[0], float)
    T_inf = np.broadcast_to(np.asarray(T_inf, float), t.shape)
    out = []
    for loc in resolve_locations(ro):
        r = dict(kind=loc['kind'], name=loc['name'], material=loc['material'],
                 construction=loc['construction'], missing=loc['missing'],
                 results={}, notes=[], temperature_basis='',
                 accuracy=hl.ACCURACY[loc['kind']])
        if loc['missing'] or t.size < 2:
            r['status'] = 'cannot be evaluated'
            if t.size < 2 and not loc['missing']:
                r['missing'] = ["no flown arc to evaluate over"]
            out.append(r)
            continue
        r['status'] = 'evaluated'
        g = loc['geometry']
        if loc['kind'] == 'nose_cap':
            rn = g['radius_m']
            rad = heating.radiative_flux(rho, V, rn)[0]
            f = lambda Tw: hl.stagnation_point_flux(rho, V, rn, Tw, T_inf)
            if loc['construction'] == 'solid' and not loc['is_ablator']:
                res, r['temperature_basis'] = _solid_nose(
                    loc, t, rho, V, T_inf, r)
                if res:
                    r['results']['laminar'] = res
            else:
                r['results']['laminar'], r['temperature_basis'] = \
                    _thermal(loc, t, f, rad)
            if float(np.max(rad)) > 0.0:
                r['notes'].append(
                    "includes hot-gas radiation (Tauber-Sutton), peak "
                    f"{float(np.max(rad)) / 1e6:.2f} MW/m^2")
        elif loc['kind'] == 'leading_edge':
            rad_m, sw = g['radius_m'], g['sweep_deg']
            poll = lambda Tw: hl.attachment_line_flux(
                rho, V, rad_m, sw, Tw, T_inf)
            taub = lambda Tw: hl.swept_cylinder_flux(
                rho, V, rad_m, sw, Tw, T_inf)
            turb = lambda Tw: hl.attachment_line_flux(
                rho, V, rad_m, sw, Tw, T_inf, turbulent=True)
            a, basis = _thermal(loc, t, poll)
            b, _ = _thermal(loc, t, taub)
            r['results']['laminar'] = _band(a, b, "Poll", "Tauber Eq. 41")
            r['results']['turbulent'], _ = _thermal(loc, t, turb)
            r['temperature_basis'] = basis
            st = hl.attachment_line_state(rho, V, T_inf, rad_m, sw,
                                          COLD_WALL_K)
            r['Rbar_star_peak'] = float(np.nanmax(st['Rbar_star']))
            r['notes'].append(
                "which state applies is not decided here: turbulence is "
                "reported above a reference-temperature attachment-line "
                "Reynolds number of 300 to 500 on a disturbed edge and 600 "
                "to 800 on a smooth one (Holden & Kolly); the peak here is "
                f"{r['Rbar_star_peak']:.0f}")
            r['notes'].append(
                "the edge is evaluated at zero angle of attack: the "
                "relations used are for a swept edge alone, and the one that "
                "includes incidence (Tauber Eq. 49) has no test case")
            if loc['construction'] == 'solid':
                r['notes'].append(
                    "the entry says the edge is solid; conduction in a solid "
                    "edge is not modelled, so the temperature is the "
                    "radiating-wall value, an upper bound")
        else:                                           # windward_face
            r['stations'] = []
            for s in g['stations']:
                ang = s['angle_deg'] + g['alpha_deg']
                x = s['run_m']
                cone = lambda Tw, c=True: hl.laminar_surface_flux(
                    rho, V, x, ang, Tw, T_inf, cone=c)
                hi, basis = _thermal(loc, t, cone)
                res = {}
                if g['flat_bottom']:
                    lo, _ = _thermal(loc, t, lambda Tw: cone(Tw, False))
                    res['laminar'] = _band(lo, hi, "flat plate", "cone")
                else:
                    res['laminar'] = hi
                turb = lambda Tw: np.nan_to_num(hl.turbulent_surface_flux(
                    rho, V, x, ang, np.maximum(Tw, 1.0), T_inf,
                    cone=not g['flat_bottom']))
                res['turbulent'], _ = _thermal(loc, t, turb)
                r['stations'].append(dict(x_over_L=s['x_over_L'],
                                          angle_deg=ang, results=res))
            r['temperature_basis'] = basis
            hot = max(r['stations'], key=lambda st: _peak_q(
                st['results']['laminar']))
            r['results'] = hot['results']
            r['notes'].append(
                f"evaluated at an angle of attack of {g['alpha_deg']:g} deg "
                f"({loc['taken_from']['alpha_deg']}) at x/L of "
                + ", ".join(f"{f:g}" for f in FACE_STATIONS)
                + f"; 'results' repeats the hottest, x/L {hot['x_over_L']:g}")
            r['notes'].append(
                "the turbulent relation is stated for speeds above 1500 m/s "
                "and counts nothing below that")
        out.append(r)
    return out


def _peak_q(res):
    q = res['q_peak_W_m2']
    return max(q) if isinstance(q, tuple) else q


def _band(a, b, name_a, name_b):
    """Two relations for the same quantity, as a low and a high value."""
    lo, hi = (a, b) if a['q_peak_W_m2'] <= b['q_peak_W_m2'] else (b, a)
    lo_name, hi_name = ((name_a, name_b) if lo is a else (name_b, name_a))
    out = dict(q_peak_W_m2=(lo['q_peak_W_m2'], hi['q_peak_W_m2']),
               heat_load_J_m2=(lo['heat_load_J_m2'], hi['heat_load_J_m2']),
               t_peak_s=hi['t_peak_s'], low_is=lo_name, high_is=hi_name)
    if 'T_wall_peak_K' in lo:
        out['T_wall_peak_K'] = (lo['T_wall_peak_K'], hi['T_wall_peak_K'])
    return out


def _solid_nose(loc, t, rho, V, T_inf, r):
    """A solid nose tip: conduction, if the catalog gives the material's
    density, specific heat and conductivity; otherwise say which is absent."""
    mat, _ = _material(loc['material'])
    need = {'density_kg_m3': 'density', 'c_J_kgK': 'specific heat',
            'k_W_mK': 'conductivity'}
    absent = [label for k, label in need.items()
              if not (mat and mat.get(k))]
    if absent:
        r['status'] = 'cannot be evaluated'
        r['missing'] = [f"the {', '.join(absent)} of {loc['material']!r} "
                        f"is not in the materials catalog"]
        return None, ''
    g = loc['geometry']
    res = heating_solid.cone_tip_response(
        t, rho, V, T_inf, tip_radius_m=g['radius_m'],
        half_angle_deg=g['half_angle_deg'], length_m=g['solid_length_m'],
        density_kg_m3=float(mat['density_kg_m3']),
        specific_heat_J_kgK=float(mat['c_J_kgK']),
        conductivity_W_mK=float(mat['k_W_mK']),
        emissivity=loc['emissivity'], T_initial_K=COLD_WALL_K)
    q = hl.stagnation_point_flux(rho, V, g['radius_m'], res['T_tip_K'], T_inf)
    r['accuracy'] = heating_solid.ACCURACY['solid_cone_tip']
    r['notes'].append(
        "the catalog's conductivity is the through-thickness value of the "
        "bondline screen; the tip conducts along its axis, which for a fibre "
        "composite is a different number")
    return _summary(t, q, res['T_tip_K']), (
        "solid conduction along the tip, starting from "
        f"{COLD_WALL_K:.0f} K")
