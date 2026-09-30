"""
Grid-fin static-margin sizing check.

Purpose: tell the user whether a vehicle's grid fins are appropriately sized for
a typical static margin, given the body diameter.  Two uses:
  * SANITY-CHECK an OSINT fin estimate (does the measured fin give a sane margin?)
  * ESTIMATE a missing fin size (what frame area "should" a vehicle of this
    diameter carry for a typical margin?)

Method (Barrowman).  The static margin is
    SM = (x_CP - x_CG) / D            [calibers]
with the combined centre of pressure the normal-force-weighted average of the
body (nose) and grid-fin contributions,
    x_CP = (C_Na,body * x_body + C_Na,fin * x_fin) / (C_Na,body + C_Na,fin).
Body normal force is the Barrowman nose term (C_Na = 2 referenced to the body
base area, CP at a shape-dependent fraction of nose length).  Grid-fin normal
force is _cl_alpha_gridfins evaluated at a representative ascent Mach (the
grid-fin C_Na model is the one validated against the nine-paper set recorded in
data/ -- see METHODS.md, section 8.5).  CG is estimated from the stage mass
stack (mass-weighted longitudinal centroid) at liftoff/full unless supplied.

Scaling note (why this is a useful OSINT check): to hold the static margin in
*calibers* roughly constant across geometrically similar vehicles, fin AREA
scales as D^2 (tail-volume argument).  So a measured fin that gives a wildly
atypical margin for the vehicle's diameter is a flag that the OSINT geometry --
or the CG/station assumptions -- are off.

APPROXIMATIONS (first-order; all flagged in the output):
  * CG from the stage stack assumes uniform mass density within each stage and a
    simple nose->payload->upper-stages->stage-1 longitudinal layout.  Supply
    x_cg_m to override.
  * Body normal force is nose-only (classic Barrowman for a constant-diameter
    body); flares/boattails and viscous body-crossflow lift are not added.
  * The fin longitudinal station defaults to near the aft of the finned stage;
    supply fin_station_m to override.
  * The grid-fin normal-force slope is the APPROXIMATE _cl_alpha_gridfins lift
    model (less validated than the drag model; it likely over-estimates C_Na by
    treating the full web wetted area as lifting, and is insensitive to the
    solidity override).  This is the dominant uncertainty in the static-margin
    MAGNITUDE.  In practice the VERDICT is robust to it -- because the fins sit
    far aft of the CG, the combined CP (hence the margin band) changes little
    across a 3x swing in fin C_Na -- but a precise margin would want the lift
    slope calibrated against measured grid-fin C_Na (e.g. W&M AIAA 93-0035,
    Fig. 6).
This is a preliminary-design / OSINT sanity tool, not a substitute for
Mach-resolved wind-tunnel/CFD stability data.
"""

from __future__ import annotations
import math
from booster_models import (BoosterParams, _cl_alpha_gridfins, effective_ro,
                             _SHAPE_ALIAS)

# Barrowman nose centre-of-pressure, as a fraction of nose length from the tip.
# NB the cone value is the slender-body limit of the flight-substantiated
# sharp-cone result 2/(3cos^2 delta) (Eastman, Boeing D2-36139-1 Eq. 3.2):
# within ~3% for delta <= 10 deg, ~13% low at 20 deg — see trim_gate.py note.
_NOSE_CP_FRACTION = {
    "cone":           0.666,
    "tangent_ogive":  0.466,
    "von_karman":     0.500,
    "lv_haack":       0.437,
    "parabola":       0.500,
    "blunt_cylinder": 0.500,
}

# Typical static-margin band (calibers) for a finned vehicle.
_SM_MARGINAL_LO = 0.5    # below this: marginal / insufficient
_SM_TYPICAL_HI  = 2.0    # above this: over-stabilised (over-finned)


def _nose_cp_fraction(shape: str) -> float:
    s = _SHAPE_ALIAS.get(shape, shape)
    return _NOSE_CP_FRACTION.get(s, 0.5)


def _front_nose(params: BoosterParams):
    """(nose_shape, nose_length_m, body_diameter_m) for the as-flown front end.

    Prefers an attached shroud/fairing nose, then the stage nose, then the
    RV/payload nose.  Falls back to a 3-caliber tangent ogive if none is set.
    """
    d = params.diameter_m
    # The nose caps the TOP stage, not stage 1 — use the top stage's diameter
    # so a multi-stage fallback nose isn't sized to the fat booster (which
    # inflated the stack length and mislaid the CG).
    top = params
    while getattr(top, "stage2", None) is not None:
        top = top.stage2
    d_top = float(getattr(top, "diameter_m", 0.0) or d)
    ro = effective_ro(params)
    # NON-SEPARATING body: the airframe IS the vehicle, so its nose is the
    # forward taper carved SUBTRACTIVELY from the last stage's own length
    # (FRONT_END_DESIGN.md), NOT the inherited full body length — using
    # ro.length_m here (which effective_ro sets to the stage length in body
    # mode) would stack the body on top of itself and float the CG out past
    # the tail, falsely flagging a stable body as unstable.
    if (ro is not None
            and getattr(ro, 'separation_mode', 'separating_ro') == 'body'
            and float(getattr(ro, 'diameter_m', 0.0) or 0.0) > 0.0):
        _bn = float(getattr(ro, 'body_nose_length_m', 0.0) or 0.0)
        if _bn <= 0.0:
            _bn = min(3.0 * d_top, 0.5 * float(top.length_m or (2.0 * d_top)))
        _bn = max(0.0, min(_bn, float(top.length_m or _bn)))
        return (getattr(ro, 'shape', '') or 'tangent_ogive', _bn,
                float(getattr(ro, 'diameter_m', 0.0) or d_top))
    # shroud nose (fairing on during ascent)
    if params.shroud_nose_shape and params.shroud_nose_length_m > 0:
        return (params.shroud_nose_shape, params.shroud_nose_length_m,
                params.shroud_diameter_m or d)
    if params.nose_shape and params.nose_length_m > 0:
        return params.nose_shape, params.nose_length_m, d_top
    if ro is not None and getattr(ro, 'shape', '') and getattr(ro, 'length_m', 0) > 0:
        # RV/HGB caps the stack and acts as the nose
        return ro.shape, ro.length_m, (getattr(ro, 'diameter_m', 0.0) or d_top)
    return "tangent_ogive", 1.6 * d_top, d_top   # matches the schematic nom.


def estimate_cg(params: BoosterParams, fuelled: bool = False):
    """Estimate (x_cg_m, total_length_m) from the stage stack at liftoff/full.

    x is measured aft from the nose tip.  The stack is laid out from the REAL
    per-stage geometry — each stage at its OWN ``length_m``, plus its declared
    interstage, plus the nose/fairing on top — exactly as the schematic draws
    it (``length_m`` is per-stage, NOT the whole stack; the earlier full-stack
    assumption squeezed a multi-stage vehicle and floated the CG upward).
    Each stage's OWN wet mass is m_i - m_{i+1} (cumulative-mass convention);
    the payload/RV mass sits in the nose region when the RV caps the stack,
    else just behind a separate nose/shroud.  Approximate (see docstring).

    ``fuelled`` matters ONLY for a non-separating body: False (default) returns
    the empty burnout/re-entry CG (airframe + warhead, no propellant) — the CG
    that governs re-entry glide stability, used by the trim gate; True adds the
    motor propellant in the aft body, giving the fuelled liftoff CG (the one the
    schematic labels 'fuelled').  The two differ substantially for a heavy motor
    (worked example: ~0.31 L empty vs ~0.57 L fuelled).  For a stack (separating RV) the
    normal path already uses fuelled stage masses, so the flag is a no-op."""
    nose_shape, nose_len, d = _front_nose(params)
    ro = effective_ro(params)
    payload = (params.payload_kg if params.payload_kg > 0
               else (ro.mass_kg if ro is not None else 0.0))
    nose_is_ro = not ((params.shroud_nose_shape and params.shroud_nose_length_m > 0)
                      or (params.nose_shape and params.nose_length_m > 0))

    chain = []                                     # [S1 (base) ... Sn (top)]
    s = params
    while s is not None:
        chain.append(s)
        s = s.stage2
    own = {}
    for i, st in enumerate(chain):
        nxt = chain[i + 1] if i + 1 < len(chain) else None
        upper = nxt.mass_initial if nxt is not None else payload
        own[id(st)] = max(st.mass_initial - upper, 0.0)

    # Build heights from the BASE up, mirroring booster_schematic.draw_booster:
    # stage, then its interstage (adapter atop it), ... then nose on top.
    seg_y = []                                     # (mass, height-from-base)
    y = 0.0
    for st in chain:
        L = st.length_m if st.length_m > 0 else max(1.0, 2.0 * st.diameter_m)
        seg_y.append((own[id(st)], y + 0.5 * L))
        if st.n_boosters and st.n_boosters > 0:    # strap-ons ride this stage
            b = st.n_boosters * (st.booster_prop_kg + st.booster_inert_kg)
            seg_y.append((b, y + 0.5 * L))
        y += L
        if getattr(st, "has_interstage", False) \
                and (getattr(st, "interstage_length_m", 0.0) or 0.0) > 0:
            y += st.interstage_length_m
    body_top = y
    _is_body = (ro is not None
                and getattr(ro, 'separation_mode', 'separating_ro') == 'body')
    if _is_body:
        # The reentering body IS the last stage, empty (its propellant is spent
        # and any earlier stages are gone).  The empty airframe is a uniform
        # tube centred at body_top/2.  A DECLARED warhead — ro.payload_kg, the
        # forward-packed warhead/guidance mass the A2 loadout folds into the
        # body — is NOT smeared over the tube: it rides in the nose region, so
        # place it at the nose centroid and mass-weight it against the empty
        # airframe.  This is what pulls the CG ahead of the CP for a
        # long-nosed, heavy-warhead body (worked example: 2.5 t in a 4.44 m nose →
        # CG ~0.30 L, ~1.5 cal stable → it glides instead of tumbling).  A body
        # with NO declared payload keeps the uniform-tube centroid (legacy,
        # backward-compatible); ROParams.reentry_cg_m still overrides either at
        # the trim gate.  (Full-tank vs burnout is a no-op here — the spent
        # airframe + warhead is the same body either way.)
        # The fuelled (liftoff) CG is the whole stack's; the reentry CG is the
        # body's alone, and the body is the LAST stage: the stages below it
        # are gone.  Measuring it over the whole stack put a multi-stage
        # body's CG in the wrong place (FRONT_END_DESIGN.md §17).
        _lastst = chain[-1]
        total = (body_top if fuelled else
                 (_lastst.length_m if _lastst.length_m > 0
                  else max(1.0, 2.0 * _lastst.diameter_m)))
        _x_air = 0.5 * total
        _pay = float(getattr(ro, 'payload_kg', 0.0) or 0.0)
        _body_mass = float(getattr(ro, 'mass_kg', 0.0) or 0.0)
        _airframe = _body_mass - _pay
        # The body's nose is the RO's own front end (body_nose_length_m), not the
        # base stage's nose field — the warhead rides in THAT nose.
        _nose = float(getattr(ro, 'body_nose_length_m', 0.0) or 0.0) or nose_len
        _segs = []                                      # (mass, x-aft-of-nose)
        if _pay > 0.0 and _airframe > 0.0 and _nose > 0.0:
            _segs.append((_pay, 0.5 * _nose))           # warhead in the nose
            _segs.append((_airframe, _x_air))           # empty airframe tube
        else:
            _segs.append((_body_mass, _x_air))          # uniform tube (legacy)
        if fuelled:
            # Motor propellant fills the aft body (below the warhead); its
            # centroid is the aft-section centre.  Single dominant term, so the
            # fuelled CG is robust to the airframe's own distribution.
            _prop = sum(float(getattr(st, 'mass_propellant', 0.0) or 0.0)
                        for st in chain)
            if _prop > 0.0 and total > _nose:
                _segs.append((_prop, _nose + 0.5 * (total - _nose)))
        _msum = sum(m for m, _ in _segs)
        if _msum > 0.0:
            return sum(m * x for m, x in _segs) / _msum, total
        return _x_air, total
    else:
        total = body_top + nose_len
        if payload > 0:                            # in / behind the nose
            seg_y.append((payload,
                          body_top + (0.5 * nose_len if nose_is_ro else 0.0)))

    msum = sum(m for m, _ in seg_y)
    my = sum(m * yy for m, yy in seg_y)
    y_cg = my / msum if msum > 0 else 0.5 * total
    return total - y_cg, total                     # x aft of the nose


def _stack_layout(params: BoosterParams):
    """Front->aft diameter profile for the body normal-force model.

    Returns (nose_base_d, nose_x_cp, sections, L_total) where `sections` is a
    list of (x_start_m, diameter_m) for the constant-diameter body sections aft
    of the nose, in nose->tail order.  Mirrors the stage layout used by
    estimate_cg (upper stages at their own length_m, aft stage takes the
    remainder), so the two agree on station positions."""
    d_body = params.diameter_m
    # One source of truth for the as-flown nose (handles the non-separating
    # body's subtractive taper), so the CP layout and the CG estimate agree.
    nshape, nlen, nd = _front_nose(params)
    # A declared biconic trims on its two-cone CP (area-weighted fore cone + aft
    # frustum), not a single-cone fraction — so the static margin sees the real
    # shape (FRONT_END_DESIGN.md).  Falls through when not a valid biconic.
    from booster_models import biconic_nose_geometry, biconic_nose_cp_fraction
    _bic = biconic_nose_geometry(params)
    if _bic is not None:
        nose_x_cp = biconic_nose_cp_fraction(
            _bic['break_ratio'], _bic['fore_len_m'],
            _bic['aft_len_m']) * _bic['nose_len_m']
    else:
        nose_x_cp = _nose_cp_fraction(nshape) * nlen
    L_total = max(params.length_m, nlen + 0.5)

    chain = []
    s = params
    while s is not None:
        chain.append(s)
        s = s.stage2
    fwd_to_aft = list(reversed(chain))
    body_len = L_total - nlen
    upper, aft = fwd_to_aft[:-1], fwd_to_aft[-1]
    lens = {id(st): (st.length_m if st.length_m > 0 else 0.0) for st in upper}
    if sum(lens.values()) >= body_len:                 # lengths inconsistent
        lens = {id(st): body_len / len(fwd_to_aft) for st in fwd_to_aft}
    else:
        lens[id(aft)] = body_len - sum(lens.values())

    sections, x = [], nlen
    for st in fwd_to_aft:
        sections.append((x, st.diameter_m if st.diameter_m > 0 else d_body))
        x += max(lens[id(st)], 1e-6)
    return nd, nose_x_cp, sections, L_total


def body_normal_force(params: BoosterParams):
    """(C_Na_body, x_cp_body_m) — the Barrowman body normal force summed over the
    nose AND every cross-sectional-area change along the stack (thesis Eq 3-65):

        ΔC_Nα = (2/A_r)·ΔA      at each transition, located at its station,

    referenced to the body base area A_r = π(d/2)² (d = params.diameter_m).  A
    multistage stack with a narrow payload/upper stage stepping up to a wider
    lower stage has a forward-facing shoulder that adds a stabilising (CP-aft)
    normal force; including it moves the body CP aft versus a nose-only model
    (the net C_Nα telescopes to 2·A_base/A_r, but its distribution — hence the
    CP — changes).  Constant-diameter sections add nothing.

    Limitation: a separate payload section (when the nose is not the RV) is not
    yet inserted as its own diameter step; only the nose and the stage-to-stage
    transitions are modelled."""
    import math
    d_ref = params.diameter_m
    a_ref = math.pi * (d_ref / 2.0) ** 2
    nose_d, nose_x_cp, sections, _ = _stack_layout(params)

    terms = []                                          # (C_Na, x)
    a_nose = math.pi * (nose_d / 2.0) ** 2
    terms.append((2.0 * a_nose / a_ref, nose_x_cp))     # nose: 0 -> A_nose
    prev_d = nose_d
    for x, dia in sections:
        if abs(dia - prev_d) > 1e-9:
            d_a = math.pi * ((dia / 2.0) ** 2 - (prev_d / 2.0) ** 2)
            terms.append((2.0 * d_a / a_ref, x))
        prev_d = dia

    c_na = sum(t[0] for t in terms)
    if c_na <= 1e-9:
        return 2.0, nose_x_cp                           # degenerate fallback
    x_cp = sum(t[0] * t[1] for t in terms) / c_na
    return c_na, x_cp


def grid_fin_static_margin(params: BoosterParams, mach: float = 1.5,
                           x_cg_m: float = None, fin_station_m: float = None,
                           solidity: float = None) -> dict:
    """Static margin (calibers) of the vehicle with its grid fins.

    Parameters
    ----------
    params        : BoosterParams with has_grid_fins (on the finned stage)
    mach          : representative ascent Mach for the fin C_Na (default 1.5)
    x_cg_m        : override CG location (m aft of nose); else estimated
    fin_station_m : override fin longitudinal station (m aft of nose); else
                    near the aft of the finned stage
    solidity      : override grid_fin_solidity for the C_Na (else from params)

    Returns a dict with the margin, its components, a verdict, and the
    assumptions used.
    """
    d = params.diameter_m
    if not getattr(params, 'has_grid_fins', False) or params.n_grid_fins <= 0:
        raise ValueError("params has no grid fins (has_grid_fins / n_grid_fins).")

    c_na_body, x_body = body_normal_force(params)

    sig = params.grid_fin_solidity if solidity is None else solidity
    c_na_fin = _cl_alpha_gridfins(
        params.n_grid_fins, params.grid_fin_width_m, params.grid_fin_height_m,
        params.grid_fin_chord_m, params.grid_fin_web_thickness_m,
        params.grid_fin_cell_pitch_m, d, mach, solidity=sig)

    x_cg, total_len = estimate_cg(params)
    if x_cg_m is not None:
        x_cg = x_cg_m
    if fin_station_m is not None:
        x_fin = fin_station_m
    else:
        # grid fins sit near the aft of their stage; default to just forward of
        # the aft end by half the fin chord.
        x_fin = total_len - 0.5 * max(params.grid_fin_chord_m, 0.0)

    denom = c_na_body + c_na_fin
    x_cp = (c_na_body * x_body + c_na_fin * x_fin) / denom if denom > 0 else x_body
    sm_cal = (x_cp - x_cg) / d if d > 0 else float('nan')

    if sm_cal < 0:
        verdict = "UNSTABLE (CP ahead of CG)"
    elif sm_cal < _SM_MARGINAL_LO:
        verdict = "marginal / low stability"
    elif sm_cal <= _SM_TYPICAL_HI:
        verdict = "appropriate (typical 0.5-2 cal)"
    else:
        verdict = "over-stabilised (more fin than needed)"

    return dict(
        static_margin_cal=sm_cal,
        x_cp_m=x_cp, x_cg_m=x_cg, x_body_m=x_body, x_fin_m=x_fin,
        c_na_body=c_na_body, c_na_fin=c_na_fin,
        total_length_m=total_len, diameter_m=d, mach=mach, verdict=verdict,
        cg_estimated=(x_cg_m is None), fin_station_estimated=(fin_station_m is None),
    )


def grid_fin_area_for_margin(params: BoosterParams, target_sm_cal: float = 1.5,
                             mach: float = 1.5, x_cg_m: float = None,
                             fin_station_m: float = None) -> dict:
    """Inverse: grid-fin frame area per fin needed to hit target_sm_cal.

    Because the grid-fin C_Na scales linearly with frame area in the model, the
    required area is the current area times the ratio of required to current
    C_Na.  Returns the per-fin frame area and the current value for comparison.
    """
    d = params.diameter_m
    cur = grid_fin_static_margin(params, mach=mach, x_cg_m=x_cg_m,
                                 fin_station_m=fin_station_m)
    c_na_body, x_body = cur['c_na_body'], cur['x_body_m']
    x_cg, x_fin = cur['x_cg_m'], cur['x_fin_m']

    x_cp_target = x_cg + target_sm_cal * d
    # C_Na,fin needed: C_Na,b*(x_cp - x_b) = C_Na,f*(x_f - x_cp)
    if x_fin <= x_cp_target:
        return dict(feasible=False,
                    reason="target CP is at/aft of the fin station -- "
                           "fins can't place it there; move target or station.",
                    **cur)
    c_na_fin_req = c_na_body * (x_cp_target - x_body) / (x_fin - x_cp_target)
    cur_area = params.grid_fin_width_m * params.grid_fin_height_m
    cur_c_na_fin = cur['c_na_fin']
    if cur_c_na_fin <= 0:
        return dict(feasible=False, reason="current fin C_Na is zero.", **cur)
    area_req = cur_area * (c_na_fin_req / cur_c_na_fin)
    return dict(
        feasible=True,
        target_sm_cal=target_sm_cal,
        frame_area_per_fin_m2_required=area_req,
        frame_area_per_fin_m2_current=cur_area,
        equivalent_square_side_m=math.sqrt(area_req) if area_req > 0 else 0.0,
        c_na_fin_required=c_na_fin_req, c_na_fin_current=cur_c_na_fin,
        current_static_margin_cal=cur['static_margin_cal'],
        diameter_m=d, mach=mach,
    )


if __name__ == "__main__":
    from booster_models import get_booster
    m = get_booster("STARS-1")
    print("=== STARS-1 grid-fin static-margin check (M=1.5, full/liftoff) ===")
    r = grid_fin_static_margin(m, mach=1.5)
    for k in ("static_margin_cal", "verdict", "x_cp_m", "x_cg_m", "x_body_m",
              "x_fin_m", "c_na_body", "c_na_fin", "total_length_m",
              "diameter_m", "cg_estimated", "fin_station_estimated"):
        v = r[k]
        print(f"  {k:24s}: {v:.3f}" if isinstance(v, float) else f"  {k:24s}: {v}")
    print("\n=== Inverse: frame area for SM = 1.5 cal ===")
    inv = grid_fin_area_for_margin(m, target_sm_cal=1.5, mach=1.5)
    for k, v in inv.items():
        print(f"  {k:32s}: {v:.4f}" if isinstance(v, float) else f"  {k:32s}: {v}")
