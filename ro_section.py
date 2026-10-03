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
    body = (ro.body_material() if hasattr(ro, "body_material")
            else str(getattr(ro, "body_tps_material", "") or ""))
    th = _f(getattr(ro, "body_tps_thickness_m", 0.0))
    if th <= 0:
        return []
    out = [(body, th, "")]
    out += interior_layers(ro)
    return out


def interior_layers(ro):
    """[(material key, thickness_m, source)] behind the outer layer."""
    return [(str(e.get("material", "")), _f(e.get("thickness_m")),
             str(e.get("source", "") or ""))
            for e in (getattr(ro, "interior_layers", None) or [])]


def nose_piece(ro):
    """The nose tip when its extent is entered, from the object's first
    nose_cap entry in heating_locations:

      solid  construction 'solid' with solid_length_m: a plug of the nose
             material filling the outline ahead of the joint
      shell  construction 'skin' with thickness_m and length_m: a shell of
             the nose material ahead of the joint, the layers behind it
             continuing underneath

    Returns (piece, flag): piece is dict(kind, material, extent_m,
    thickness_m) or None; flag says why there is none when the nose
    material differs from the body's, else ''."""
    nose = (ro.nose_material() if hasattr(ro, "nose_material")
            else str(getattr(ro, "nose_tps_material", "") or ""))
    body = (ro.body_material() if hasattr(ro, "body_material")
            else str(getattr(ro, "body_tps_material", "") or ""))
    entry = next((e for e in (getattr(ro, "heating_locations", None) or [])
                  if e.get("kind") == "nose_cap"), None)
    piece = None
    if entry and nose:
        con = entry.get("construction", "")
        if con == "solid" and _f(entry.get("solid_length_m")) > 0:
            ext = _f(entry["solid_length_m"])
            piece = dict(kind="solid", material=nose, extent_m=ext,
                         thickness_m=ext)
        elif (con == "skin" and _f(entry.get("thickness_m")) > 0
              and _f(entry.get("length_m")) > 0):
            piece = dict(kind="shell", material=nose,
                         extent_m=_f(entry["length_m"]),
                         thickness_m=_f(entry["thickness_m"]))
    if piece is None and nose and body and nose != body:
        import heating
        lab = (heating.TPS_MATERIALS.get(nose) or {}).get("label") or nose
        return None, (f"nose of {lab}: its extent is not entered (nose cap "
                      f"entry: solid_length_m, or thickness_m and length_m), "
                      f"so the wall is drawn as the body's to the tip")
    return piece, ""


def _cut(pts, zlo, zhi):
    """The part of a polyline with zlo <= z <= zhi, with the crossing
    points added."""
    out = []
    for i, (r, z) in enumerate(pts):
        if i > 0:
            r0, z0 = pts[i - 1]
            xs = []
            for zc in (zlo, zhi):
                if (z0 - zc) * (z - zc) < 0:
                    f = (zc - z0) / (z - z0)
                    xs.append((f, (r0 + f * (r - r0), zc)))
            out += [p for _f_, p in sorted(xs)]
        if zlo - 1e-12 <= z <= zhi + 1e-12:
            out.append((r, z))
    ded = []
    for p in out:
        if not ded or math.hypot(p[0] - ded[-1][0], p[1] - ded[-1][1]) > 1e-12:
            ded.append(p)
    return ded


def _close(prof):
    """End a half-section profile on the axis."""
    if prof and prof[-1][0] > 1e-9:
        prof = prof + [(0.0, prof[-1][1])]
    return prof


def _loop(wa, wb):
    """The closed outline of the region between two walls."""
    return list(wa) + list(reversed(wb or []))


def section(ro):
    """dict(form, outline, D, L, layers, nose, pieces, interior, flags).

    layers: the body column, one dict per wall layer outside in, with
    material, label, group, thickness_m, depth_m and its full-length outer /
    inner profiles (for captions).  nose: the nose piece (nose_piece) and its
    joint plane z_joint_m, or None.  pieces: what is drawn and exported, one
    dict per region with kind ('layer', 'nose', 'interior'), material,
    label, group, thickness_m, loop (closed (r, z) outline) and profile (for
    revolving).  interior: the profile of the space inside the wall.  For a
    lifting body, layers and pieces are [] and a flag says why."""
    import heating
    o = outline(ro)
    flags = list(o["flags"])
    L = o["L"]
    prof0 = o["profile"]
    empty = dict(form=o["form"], outline=prof0, D=o["D"], L=L, layers=[],
                 nose=None, pieces=[], interior=None, flags=flags)
    nose, nflag = nose_piece(ro)
    wl = wall_layers(ro)
    if o["form"] != "axisymmetric":
        if wl or nose:
            flags.append(LIFTING_NOT_SECTIONED)
        return empty
    if nflag:
        flags.append(nflag)
    # the extent is measured back from the actual tip (below L when the
    # cone is blunted: L runs to where a sharp cone's point would be)
    z_tip = max(z for _r, z in prof0)
    if nose and not 0 < nose["extent_m"] < z_tip:
        flags.append(f"the nose tip's extent ({nose['extent_m']:g} m) is not "
                     f"inside the body's length; not drawn")
        nose = None
    if not wl and not nose:
        return empty

    def mat_info(key):
        m = heating.TPS_MATERIALS.get(key) or {}
        return (m.get("label") or key or "?"), m.get("group", "")

    inner = interior_layers(ro)
    zj = z_tip - nose["extent_m"] if nose else math.inf
    # cumulative depths, body column and nose column, for ranks 0..n
    body_th = [t for _m, t, _s in wl] if wl else []
    if not wl:                       # a nose tip without a body layer
        mats = []
    else:
        mats = [m for m, _t, _s in wl]
    n = len(mats)
    Db = [sum(body_th[:i]) for i in range(n + 1)]
    if nose and nose["kind"] == "shell":
        nose_th = [nose["thickness_m"]] + [t for _m, t, _s in inner]
        Dn = [sum(nose_th[:i]) for i in range(n + 1)]
    elif nose:                       # solid: the layers behind run flat
        Dn = [0.0] + [sum(t for _m, t, _s in inner[:i])   # under the plug
                      for i in range(n)]

    def region(i):
        """Half-section profile of everything inside rank i, or None."""
        if i == 0:
            return list(prof0)
        b = inset(prof0, Db[i])
        if b is None:
            return None
        if not nose:
            return b
        if nose["kind"] == "shell":
            nn = inset(prof0, Dn[i])
            part = [(0.0, 0.0)] + _cut(b[1:], 0.0, zj)
            if nn is not None:
                part += _cut(nn[1:], zj, math.inf)
            return _close(part)
        zt = zj - Dn[i]
        if zt <= 0:
            return None
        return _close([(0.0, 0.0)] + _cut(b[1:], 0.0, zt))

    regions = [region(i) for i in range(n + 1)]
    pieces, layers = [], []
    for i in range(n):
        if regions[i] is None:
            break
        mat, th, src = wl[i]
        lab, grp = mat_info(mat)
        outer_w, inner_w = regions[i][1:], (regions[i + 1] or [])[1:]
        layers.append(dict(material=mat, label=lab, group=grp,
                           thickness_m=th, depth_m=Db[i], source=src,
                           outer=inset(prof0, Db[i]) if i else list(prof0),
                           inner=inset(prof0, Db[i + 1])))
        if i == 0 and nose:
            bw_o, bw_i = _cut(outer_w, 0.0, zj), _cut(inner_w, 0.0, zj)
            # on the joint plane keep one point each side: the body column's
            # inner wall ends where it meets the joint, the nose column's
            # begins there
            k = next((j for j, p in enumerate(bw_i) if abs(p[1] - zj) < 1e-9),
                     None)
            if k is not None:
                bw_i = bw_i[:k + 1]
            pieces.append(dict(kind="layer", zone="body", material=mat,
                               label=lab, group=grp, thickness_m=th,
                               loop=_loop(bw_o, bw_i)))
            nlab, ngrp = mat_info(nose["material"])
            nw_o, nw_i = _cut(outer_w, zj, math.inf), _cut(inner_w, zj,
                                                         math.inf)
            on = [j for j, p in enumerate(nw_i) if abs(p[1] - zj) < 1e-9]
            if nose["kind"] == "shell" and on:
                nw_i = nw_i[on[-1]:]
            pieces.append(dict(kind="nose", zone="nose",
                               material=nose["material"], label=nlab,
                               group=ngrp, thickness_m=nose["thickness_m"],
                               solid=nose["kind"] == "solid",
                               loop=_loop(nw_o, nw_i)))
        else:
            pieces.append(dict(kind="layer", zone="all", material=mat,
                               label=lab, group=grp, thickness_m=th,
                               loop=_loop(outer_w, inner_w)))
        if regions[i + 1] is None:
            flags.append(f"the layers fill the body by {lab}; nothing is "
                         f"left inside")
    if not wl and nose:
        # a nose piece and no body layer: the plug or shell alone
        nlab, ngrp = mat_info(nose["material"])
        if nose["kind"] == "solid":
            loop = _close([(0.0, zj)] + _cut(prof0[1:], zj, math.inf))
        else:
            sh = inset(prof0, nose["thickness_m"])
            loop = _loop(_cut(prof0[1:], zj, math.inf),
                         _cut((sh or [])[1:], zj, math.inf))
        pieces.append(dict(kind="nose", zone="nose", material=nose["material"],
                           label=nlab, group=ngrp,
                           thickness_m=nose["thickness_m"],
                           solid=nose["kind"] == "solid", loop=loop))
        regions = [None]
    interior = regions[n] if wl and len(regions) > n else None
    if interior is not None:
        pieces.append(dict(kind="interior", zone="all", material="",
                           label="inside", group="", thickness_m=0.0,
                           loop=list(interior)))
    for pc in pieces:
        lp = pc["loop"]
        if pc["kind"] == "interior" or (lp and lp[0][0] < 1e-9):
            pc["profile"] = list(lp)
        else:
            pc["profile"] = list(lp) + [lp[0]]
    if nose:
        nose = dict(nose, z_joint_m=zj)
        if nose["kind"] == "solid" and len(wl) > 1:
            flags.append("under the solid tip the layers behind the body "
                         "layer are drawn running flat across the joint, "
                         "the first as its bulkhead (assumed)")
    return dict(form=o["form"], outline=prof0, D=o["D"], L=L, layers=layers,
                nose=nose, pieces=pieces, interior=interior, flags=flags)


def band(outer, inner):
    """A closed (r, z) loop for one layer, for revolving into a shell: up
    the outer wall from the base edge to the tip, back down the inner wall,
    and closed across the base.  inner None = a solid (the outer profile)."""
    if inner is None:
        return list(outer)
    loop = list(outer[1:]) + list(reversed(inner[1:]))
    return loop + [loop[0]]
