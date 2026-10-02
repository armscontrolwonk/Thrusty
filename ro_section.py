"""The one outline of a reentry object, and the layers inside its wall.

The schematic, the cross-section view and the 3-D export all read this
module, so what is drawn is what is exported: the outer outline, the body's
outer layer (body_tps_material at body_tps_thickness_m) and each entry of
interior_layers, outside in, and the space left inside them.

Outline (r, z): from the axis at the base (0, 0) out to the base edge, up
the wall to the tip on the axis.  A blunted cone is the true tangent
sphere-cone; a biconic is the aft frustum then a blunted forward cone; any
other declared shape is its analytic nose curve (stage_outline.nose_profile).

Layers: each is the region between two inward offsets of the wall, the
thickness measured normal to the wall.  The base is not a wall here (the
object lists no layers for its base), so the layers end at the base plane.
Offsets are taken by clipping the half-section with each wall edge moved
inward, which is exact for the convex outlines Thrusty draws.  The lifting
forms (wedge, half-cone) are not sectioned; both the drawing and the export
say so.
"""

import math

from stage_outline import nose_profile

LIFTING_NOT_SECTIONED = ("layers not drawn for a lifting body "
                         "(wedge or half-cone)")


def sphere_cone_profile(R, L, rn):
    """Spherically blunted cone, base (R, 0) -> dome apex: straight flank to
    the sphere-cone tangency circle, then the true spherical cap.  Falls
    back to the sharp cone when rn is unset or oversize."""
    if rn <= 1e-9 or rn >= 0.9 * R or L <= rn:
        return [(R, 0.0), (0.0, L)]
    th = math.atan2(R, L)                        # cone half-angle
    zc = L - rn / math.sin(th)                   # sphere centre (on axis)
    pts = [(R, 0.0), (rn * math.cos(th), zc + rn * math.sin(th))]
    n = 10
    for i in range(1, n + 1):
        t = th + (math.pi / 2 - th) * i / n
        pts.append((rn * math.cos(t), zc + rn * math.sin(t)))
    return pts


def _f(v):
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def outline(ro):
    """dict(form, profile, D, L, flags).  profile is the half-section
    [(0, 0), (R, 0), ..., (0, L)] for a body of revolution (form
    'axisymmetric' or 'half_cone'); for a wedge it is the side elevation
    [(-h, 0), (h, 0), (-h, L)] with h = depth / 2.  flags say what was
    assumed (a length that is not entered)."""
    D = _f(getattr(ro, "diameter_m", 0.0))
    L = _f(getattr(ro, "length_m", 0.0))
    flags = []
    if L <= 0:
        L = 1.6 * D
        flags.append("RO length unset — 1.6×⌀ used")
    rn = _f(getattr(ro, "nose_radius_m", 0.0))
    R = D / 2.0
    form = str(getattr(ro, "body_form", "") or "axisymmetric")
    if form not in ("wedge", "half_cone"):
        form = "axisymmetric"
    if form == "wedge":
        h = D / 2.0
        return dict(form=form, profile=[(-h, 0.0), (h, 0.0), (-h, L)],
                    D=D, L=L, flags=flags)
    if form == "half_cone":
        return dict(form=form, profile=[(0.0, 0.0), (R, 0.0), (0.0, L)],
                    D=D, L=L, flags=flags)
    bic = None
    if getattr(ro, "biconic", False):
        Lf = _f(getattr(ro, "fore_length_m", 0.0))
        Dbrk = _f(getattr(ro, "break_diameter_m", 0.0))
        if 0 < Lf < L and 0 < Dbrk < D:
            bic = (Lf, Dbrk)
    shape = str(getattr(ro, "shape", "") or "cone").lower()
    if bic is not None:
        Lf, Dbrk = bic
        La, R1 = L - Lf, Dbrk / 2.0
        fore = sphere_cone_profile(R1, Lf, min(rn, 0.9 * R1))
        prof = [(R, 0.0), (R1, La)] + [(r, La + z) for r, z in fore[1:]]
    elif "cone" in shape and "blunt" not in shape:
        prof = sphere_cone_profile(R, L, rn)
    else:
        if rn > 0:
            flags.append(f"RO nose radius not blended into '{shape}' "
                         "profile (drawn per the analytic shape)")
        prof = nose_profile(shape, R, L)
    return dict(form=form, profile=[(0.0, 0.0)] + prof, D=D, L=L,
                flags=flags)


def _clip(poly, n, c):
    """Sutherland-Hodgman: keep the part of poly with n . p >= c."""
    out = []
    for i in range(len(poly)):
        p, q = poly[i - 1], poly[i]
        fp = n[0] * p[0] + n[1] * p[1] - c
        fq = n[0] * q[0] + n[1] * q[1] - c
        if fq >= 0:
            if fp < 0:
                s = fp / (fp - fq)
                out.append((p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])))
            out.append(q)
        elif fp >= 0:
            s = fp / (fp - fq)
            out.append((p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])))
    return out


def inset(profile, d):
    """The half-section moved inward by d from every wall edge (not the
    base, not the axis): a profile of the same form, [(0, 0), (r, 0), ...,
    (0, top)], or None when nothing is left."""
    if d <= 0:
        return list(profile)
    poly = list(profile)                          # closes back down the axis
    walls = profile[1:]
    for (r0, z0), (r1, z1) in zip(walls[:-1], walls[1:]):
        L = math.hypot(r1 - r0, z1 - z0)
        if L < 1e-12:
            continue
        n = (-(z1 - z0) / L, (r1 - r0) / L)      # inward (left) normal
        poly = _clip(poly, n, n[0] * r0 + n[1] * z0 + d)
        if len(poly) < 3:
            return None
    # back to profile order: start on the axis at the base, end on the axis
    i0 = min(range(len(poly)), key=lambda i: (abs(poly[i][0]) > 1e-9,
                                              poly[i][1]))
    poly = poly[i0:] + poly[:i0]
    poly = [(max(r, 0.0), z) for r, z in poly]
    if poly[-1][0] > 1e-9:                        # make sure it ends on axis
        poly.append((0.0, poly[-1][1]))
    out = [poly[0]]
    for p in poly[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-12:
            out.append(p)
    if len(out) < 3:
        return None
    return out


def wall_layers(ro):
    """[(material key, thickness_m, source)] from the outside in: the body
    layer, then each interior layer.  [] when the body layer's thickness is
    not entered."""
    import booster_models as bm
    body = (ro.body_material() if hasattr(ro, "body_material")
            else str(getattr(ro, "body_tps_material", "") or ""))
    th = _f(getattr(ro, "body_tps_thickness_m", 0.0))
    if th <= 0:
        return []
    out = [(body, th, "")]
    for e in (getattr(ro, "interior_layers", None) or []):
        out.append((str(e.get("material", "")), _f(e.get("thickness_m")),
                    str(e.get("source", "") or "")))
    return out


def section(ro):
    """dict(form, outline, layers, interior, flags).

    layers: one dict per wall layer, outside in, with material, label,
    thickness_m, depth_m (to its outer face) and outer / inner profiles;
    interior: the profile of the space inside the last layer (None when
    the layers fill the body).  For a lifting body, layers is [] and a flag
    says why."""
    import heating
    o = outline(ro)
    flags = list(o["flags"])
    layers, interior = [], None
    wl = wall_layers(ro)
    if wl and o["form"] != "axisymmetric":
        flags.append(LIFTING_NOT_SECTIONED)
        wl = []
    depth = 0.0
    outer = o["profile"]
    for mat, th, src in wl:
        inner = inset(o["profile"], depth + th)
        m = heating.TPS_MATERIALS.get(mat) or {}
        layers.append(dict(material=mat, label=m.get("label") or mat or "?",
                           group=m.get("group", ""), thickness_m=th,
                           depth_m=depth, source=src,
                           outer=outer, inner=inner))
        depth += th
        if inner is None:
            flags.append(f"the layers fill the body by "
                         f"{m.get('label') or mat}; nothing is left inside")
            break
        outer = inner
    if wl:
        interior = outer if layers and layers[-1]["inner"] is not None else None
    return dict(form=o["form"], outline=o["profile"], D=o["D"], L=o["L"],
                layers=layers, interior=interior, flags=flags)


def band(outer, inner):
    """A closed (r, z) loop for one layer, for revolving into a shell: up
    the outer wall from the base edge to the tip, back down the inner wall,
    and closed across the base.  inner None = a solid (the outer profile)."""
    if inner is None:
        return list(outer)
    loop = list(outer[1:]) + list(reversed(inner[1:]))
    return loop + [loop[0]]
