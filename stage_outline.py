"""One outline per piece: what the schematic draws, the 3-D export builds and
the physics flies (FRONT_END_DESIGN.md §3 "drawn ≡ flown", §19j).

A spent stage or a strap-on booster is more than a cylinder when it has a
nose, a flared aft skirt or a nozzle sticking out.  That shape is described
ONCE, here, as a profile of radius against distance from the front.  The
schematic (`booster_schematic`) and the 3-D export (`blender_export`) draw
this profile; `spent_stage_aero` takes its side-on area and centroid from it;
a strap-on's ascent drag is computed from the same nose and skirt
(`booster_models.booster_drag_vector`).  Nothing is flown that is not drawn,
and an unset field shows as what is flown in its absence — a flat front, no
skirt, no nozzle — so the user can see what has not been entered.

Pure geometry: imports nothing from the rest of Thrusty.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

PROFILE_N = 24        # points per curved nose profile

# A protruding nozzle is drawn and flown widening from this fraction of its
# exit diameter, where it leaves the base, to the exit diameter.  The files
# carry no throat or neck size, so the half is an assumption (TODO item 10).
NOZZLE_NECK_FRACTION = 0.5


def nose_profile(shape, R, L):
    """(r, z) nose profile from base (r=R, z=0) to tip (r=0, z=L) — the
    true analytic curve for the declared shape."""
    s = (shape or "cone").lower()
    n = PROFILE_N
    if "karman" in s or "haack" in s:
        # Haack series, x measured from the tip: C=0 → Von Kármán (LD),
        # C=1/3 → LV-Haack (= Sears-Haack body nose in this code base).
        C = 1.0 / 3.0 if ("lv" in s or "sears" in s) else 0.0
        pts = []
        for i in range(n + 1):
            x = L * (1.0 - i / n)
            th = math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * x / L)))
            r = R / math.sqrt(math.pi) * math.sqrt(
                max(0.0, th - math.sin(2.0 * th) / 2.0
                    + C * math.sin(th) ** 3))
            pts.append((r, L - x))
        return pts
    if "ogive" in s:
        rho = (R * R + L * L) / (2.0 * R)       # tangent-ogive radius
        return [(math.sqrt(max(0.0, rho * rho - (L - x) ** 2)) + R - rho,
                 L - x)
                for x in (L * (1.0 - i / n) for i in range(n + 1))]
    if "parabola" in s:
        # parabolic series K'=1: r = R(2ξ − ξ²), ξ measured from the tip
        return [(R * (2.0 * xi - xi * xi), L * (1.0 - xi))
                for xi in (1.0 - i / n for i in range(n + 1))]
    if "blunt" in s:
        return [(R * math.cos(math.pi / 2 * i / n),
                 L * math.sin(math.pi / 2 * i / n)) for i in range(n + 1)]
    return [(R, 0.0), (0.0, L)]                  # straight cone


def _f(piece, key):
    return max(float(getattr(piece, key, 0.0) or 0.0), 0.0)


def strapon_piece(p):
    """A strap-on booster of `p` as a piece with the attributes the outline
    and the spent-stage model read, or None when `p` carries none.

    `length_unset` is True when the file gives no length and twice the
    diameter is used — the value that is flown, so the value that is drawn.
    A nose exists only when BOTH a shape and a length are entered; it lies
    inside the stated length."""
    if int(getattr(p, 'n_boosters', 0) or 0) <= 0:
        return None
    d = _f(p, 'booster_diam_m')
    if d <= 0.0:
        return None
    L = _f(p, 'booster_length_m')
    unset = L <= 0.0
    if unset:
        L = 2.0 * d
    shape = (getattr(p, 'booster_nose_shape', '') or '').strip()
    nose_len = min(_f(p, 'booster_nose_length_m'), L)
    if not shape or nose_len <= 0.0:
        shape, nose_len = '', 0.0
    return SimpleNamespace(
        diameter_m=d, length_m=L, length_unset=unset,
        own_nose_shape=shape, own_nose_length_m=nose_len,
        aft_skirt_length_m=_f(p, 'booster_aft_skirt_length_m'),
        aft_skirt_diameter_m=_f(p, 'booster_aft_skirt_diameter_m'),
        nozzle_protrusion_m=_f(p, 'booster_nozzle_protrusion_m'),
        nozzle_exit_area_m2=_f(p, 'booster_nozzle_area_m2'),
        solid_motor=True, has_fins=False, has_grid_fins=False,
        thrust_N=_f(p, 'booster_thrust_n'), thrust_peak_N=0.0)


def outline(piece):
    """The piece's outline as plain numbers:

      d, L            body diameter and length (m); L runs to the base
      nose_shape, nose_len    the piece's OWN nose, inside L ('' and 0 = a
                      flat front).  Read from `own_nose_*`, which only a
                      strap-on carries: a stage's `nose_shape` describes the
                      front of the whole vehicle, not of the spent stage.
      skirt_len, skirt_d      an aft skirt over the last skirt_len of L,
                      flaring to skirt_d (0, 0 when not wider than the body)
      nozzle_len, nozzle_d    a nozzle beyond the base and its exit diameter
                      (0, 0 without both a protrusion and an exit area).  A
                      cluster is one nozzle of the total exit area.
      L_all           overall length, L + nozzle_len
    """
    d = _f(piece, 'diameter_m')
    L = _f(piece, 'length_m') or 2.0 * d
    shape = (getattr(piece, 'own_nose_shape', '') or '').strip()
    nose_len = min(_f(piece, 'own_nose_length_m'), L)
    if not shape or nose_len <= 0.0:
        shape, nose_len = '', 0.0
    skirt_d = _f(piece, 'aft_skirt_diameter_m')
    skirt_len = min(_f(piece, 'aft_skirt_length_m'), L - nose_len)
    if skirt_d <= d or skirt_len <= 0.0:
        skirt_d, skirt_len = 0.0, 0.0
    nozzle_len = _f(piece, 'nozzle_protrusion_m')
    nozzle_d = math.sqrt(4.0 * _f(piece, 'nozzle_exit_area_m2') / math.pi)
    if nozzle_len <= 0.0 or nozzle_d <= 0.0:
        nozzle_len, nozzle_d = 0.0, 0.0
    return SimpleNamespace(d=d, L=L, nose_shape=shape, nose_len=nose_len,
                           skirt_len=skirt_len, skirt_d=skirt_d,
                           nozzle_len=nozzle_len, nozzle_d=nozzle_d,
                           L_all=L + nozzle_len)


def profile(piece):
    """[(x, r), ...]: radius against distance from the front, front to rear,
    closed on the axis at both ends.  A step (a flat front, the base around a
    nozzle) is two points at the same x."""
    o = outline(piece)
    R = o.d / 2.0
    pts = [(0.0, 0.0)]
    if o.nose_len > 0.0:
        tip_first = sorted(((o.nose_len - z, r) for r, z in
                            nose_profile(o.nose_shape, R, o.nose_len)))
        pts += [pt for pt in tip_first if pt[0] > 0.0]
    else:
        pts.append((0.0, R))
    body_end = o.L - o.skirt_len
    if body_end > pts[-1][0]:
        pts.append((body_end, R))
    if o.skirt_len > 0.0:
        pts.append((o.L, o.skirt_d / 2.0))
    if o.nozzle_len > 0.0:
        pts.append((o.L, NOZZLE_NECK_FRACTION * o.nozzle_d / 2.0))
        pts.append((o.L_all, o.nozzle_d / 2.0))
    pts.append((o.L_all, 0.0))
    return pts


def side_area_and_centroid(piece):
    """(side-on area in m², its centroid's distance from the front in m,
    overall length in m), integrated over profile()."""
    pts = profile(piece)
    area = moment = 0.0
    for (x0, r0), (x1, r1) in zip(pts, pts[1:]):
        dx = x1 - x0
        if dx <= 0.0:
            continue
        a = dx * (r0 + r1)                        # width 2r, trapezoid
        area += a
        moment += a * (x0 + dx * (r0 + 2.0 * r1) / (3.0 * (r0 + r1))
                       if (r0 + r1) > 0.0 else 0.0)
    return area, (moment / area if area > 0.0 else 0.0), pts[-1][0]
