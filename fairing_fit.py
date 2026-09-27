"""Does the composed payload fit inside the vehicle's front end?

The SWERVE-on-STARS-1 case (2026-08-11): a ⌀0.48 × 2.6 m RV composed onto
a stack whose drawn nose region is barely over a metre tall — visibly
impossible, and nothing said so.  This module was the warning.  Since
2026-09-27 a separating object with no fairing is drawn BESIDE the stack
and no nose is stacked (booster_schematic.exposed_front_object), so that
case no longer draws anything for the object to overrun: containment is
checked only against a declared fairing.

The check is geometric containment, derive-don't-invent throughout: the
fairing ENVELOPE comes from the same stored fields (and the same
fallbacks, stated in the result) that booster_schematic draws and
blender_export ships — cylinder + nose profile, and the warning says
when an unset dimension was stood in for.  The RO's bounding radius profile uses its own true
geometry (sphere-cone tangency, ogive/Haack curves, biconic break); a
wedge or half-cone uses the circumscribed cone — their rectangular /
half-disc sections must clear the same circle.  Wing panels with a
stored planform add their exposed span over the root-chord region at the
base; wings declared by area alone cannot be placed and are noted as
unchecked.

Assumptions stated rather than hidden: no wall thickness is stored, so
the envelope is the OUTER mold line (real internal envelopes are
tighter — a "fits" verdict is therefore the optimistic bound, and a
"does not fit" verdict is certain); the RO sits base-down on the
envelope's base plane."""

import math

from booster_schematic import stage_chain, _stage_top_diameter
from blender_export import _nose_profile, _sphere_cone_profile


def _f(v, default=0.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v


def _interp(samples, z):
    """Linear interpolation on ascending (z, r) samples; clamps outside."""
    if z <= samples[0][0]:
        return samples[0][1]
    for (z0, r0), (z1, r1) in zip(samples, samples[1:]):
        if z <= z1:
            t = (z - z0) / (z1 - z0) if z1 > z0 else 0.0
            return r0 + t * (r1 - r0)
    return samples[-1][1]


def front_envelope(p):
    """The fairing's internal envelope as ascending (z, r) samples from
    its base plane, plus (kind, notes).  None when no fairing is declared
    — nothing then encloses the object (a separating object IS the front
    end and is drawn beside the stack; a non-separating body is the last
    stage) — or when there is no geometry to check against."""
    stages = stage_chain(p)
    if not stages:
        return None
    top_d = _stage_top_diameter(stages[-1])
    shroud = next((s for s in stages
                   if _f(getattr(s, "shroud_length_m", 0.0)) > 0.0), None)
    if shroud is None:
        return None
    notes = []
    sd = _f(getattr(shroud, "shroud_diameter_m", 0.0)) or top_d
    if not _f(getattr(shroud, "shroud_diameter_m", 0.0)):
        notes.append("fairing ⌀ unset — top-stage ⌀ used")
    sl = _f(getattr(shroud, "shroud_length_m", 0.0))
    nose = _f(getattr(shroud, "shroud_nose_length_m", 0.0))
    if not 0.0 < nose <= sl:
        nose = 0.45 * sl
        notes.append("fairing nose length unset — 0.45 L used")
    shape = getattr(shroud, "shroud_nose_shape", "") or "cone"
    kind = "fairing"
    R = 0.5 * sd
    if R <= 0.0 or sl <= 0.0:
        return None
    cyl = max(0.0, sl - nose)
    env = [(0.0, R)]
    if cyl > 0.0:
        env.append((cyl, R))
    env += [(cyl + z, r) for r, z in _nose_profile(shape, R, nose)
            if cyl + z > env[-1][0] + 1e-12]
    if env[-1][0] < sl:                      # ensure the tip closes at sl
        env.append((sl, 0.0))
    return env, kind, notes


def ro_bounding_profile(ro):
    """Ascending (z, r) bounding-radius samples of the RO standing
    nose-up from its base, plus notes.  None when core dims are unset."""
    L = _f(getattr(ro, "length_m", 0.0))
    R = 0.5 * _f(getattr(ro, "diameter_m", 0.0))
    if L <= 0.0 or R <= 0.0:
        return None
    form = getattr(ro, "body_form", "") or "axisymmetric"
    notes = []
    if form == "wedge":
        span = _f(getattr(ro, "body_span_m", 0.0)) or 2.0 * R
        base_r = 0.5 * math.hypot(2.0 * R, span)
        prof = [(0.0, base_r), (L, 0.0)]
        notes.append("wedge checked as its circumscribed cone")
    elif form == "half_cone":
        prof = [(0.0, R), (L, 0.0)]
        notes.append("half-cone checked as its circumscribed cone")
    elif getattr(ro, "biconic", False) \
            and _f(getattr(ro, "fore_length_m", 0.0)) > 0.0 \
            and _f(getattr(ro, "break_diameter_m", 0.0)) > 0.0:
        fore = _f(ro.fore_length_m)
        prof = [(0.0, R), (max(0.0, L - fore),
                           0.5 * _f(ro.break_diameter_m)), (L, 0.0)]
    else:
        shape = getattr(ro, "shape", "") or "cone"
        if any(k in shape.lower() for k in ("ogive", "haack", "karman",
                                            "parabola", "blunt")):
            prof = sorted((z, r) for r, z in _nose_profile(shape, R, L))
        else:
            rn = _f(getattr(ro, "nose_radius_m", 0.0))
            prof = sorted((z, r) for r, z in _sphere_cone_profile(R, L, rn))
    span = _f(getattr(ro, "wing_span_exposed_m", 0.0))
    root = _f(getattr(ro, "wing_root_chord_m", 0.0))
    if span > 0.0 and root > 0.0:
        # wing panels ride the body over the root-chord region at the
        # base (the schematic's aft-anchored convention)
        zr = min(root, L)
        prof = ([(z, r + span) for z, r in prof if z < zr]
                + [(zr, _interp(prof, zr) + span),
                   (zr + 1e-9, _interp(prof, zr))]
                + [(z, r) for z, r in prof if z > zr])
        notes.append("wing panels included over the root-chord region")
    elif _f(getattr(ro, "wing_area_m2", 0.0)) > 0.0:
        notes.append("wings declared by area only — NOT placeable, "
                     "not checked")
    return prof, notes


def fairing_fit(p, n=400):
    """Containment check of p.ro against the front-end envelope.  None
    when no check applies (no RO, or no dims on either side); else
    dict(fits, kind, len_over_m, max_interference_m, at_z_m, ro_len_m,
    env_len_m, notes)."""
    ro = getattr(p, "ro", None)
    if ro is None:
        return None
    env_out = front_envelope(p)
    prof_out = ro_bounding_profile(ro)
    if env_out is None or prof_out is None:
        return None
    env, kind, notes = env_out
    prof, ro_notes = prof_out
    notes = notes + ro_notes + ["envelope is the outer mold line — no "
                                "wall thickness is stored"]
    env_len = env[-1][0]
    ro_len = prof[-1][0]
    len_over = max(0.0, ro_len - env_len)
    max_int, at_z = 0.0, None
    z_hi = min(ro_len, env_len)
    for i in range(n + 1):
        z = z_hi * i / n
        d = _interp(prof, z) - _interp(env, z)
        if d > max_int:
            max_int, at_z = d, z
    return dict(fits=(len_over <= 1e-9 and max_int <= 1e-3),
                kind=kind, len_over_m=len_over,
                max_interference_m=max_int, at_z_m=at_z,
                ro_len_m=ro_len, env_len_m=env_len, notes=notes)


def fairing_fit_note(fit):
    """One-line warning for a failed fit (schematic flag / export
    header).  Empty string when it fits."""
    if fit is None or fit["fits"]:
        return ""
    parts = []
    if fit["len_over_m"] > 1e-9:
        parts.append(f"{fit['len_over_m']:.2g} m too long "
                     f"({fit['ro_len_m']:g} m vs {fit['env_len_m']:.3g} m)")
    if fit["max_interference_m"] > 1e-3:
        parts.append(f"radius over by {fit['max_interference_m']:.2g} m "
                     f"at {fit['at_z_m']:.2g} m above the base")
    msg = (f"payload does NOT fit the {fit['kind']}: " + "; ".join(parts))
    fallback = next((s for s in fit["notes"] if "unset" in s), None)
    if fallback:
        msg += f" ({fallback})"
    return msg


def fairing_fit_short(fit):
    """The one-line on-canvas version (the schematic has no room for the
    full sentence — that lives in the flags / export header)."""
    if fit is None or fit["fits"]:
        return ""
    if fit["len_over_m"] > 1e-9:
        how = f"{fit['len_over_m']:.2g} m too long"
    else:
        how = f"⌀ over by {2 * fit['max_interference_m']:.2g} m"
    return f"⚠ payload does not fit the {fit['kind']} — {how}"
