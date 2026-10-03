"""To-scale side elevation of a booster stack — the Schematic tab's renderer.

Draws the vehicle purely from stored geometry fields on a BoosterParams chain:
per-stage diameter/length, nose shape and length, shroud (fairing) dimensions
and nose shape, fin planform (span/chords/sweep), grid fins, and strap-on
boosters.  Equal-aspect metres on both axes, so proportions are literal — the
panel exists to make a mis-entered length or an oversized fairing obvious at
a glance (it caught the AUR's all-up-round length sitting in the stage-1
field, and its ogive-vs-cone fairing, on its first outing).

Data honesty: nothing is invented silently.  Where a field the drawing needs
is unset (nose shape, nose length, strap-on length), a conservative fallback
is drawn and the label is flagged "(… unset)" — missing geometry should be
visible, not papered over.  The same fields feed the boost-phase drag build-up
(booster_models._cd_nose_shape), so what you see is what the physics flies.

Pure matplotlib (no Tk import) — embeddable in the GUI via FigureCanvasTkAgg
and testable headless under Agg.
"""

import math
import os

import matplotlib.image as mpimg
from matplotlib.patches import Circle, Polygon, Rectangle, Wedge

# Thrusty mascot silhouette: a human-relatable figure standing beside the
# vehicle for a felt sense of scale, with the quantitative reference carried by
# a dimensioned metre bar next to it.  Loaded once and cached; a missing asset
# falls back to the bar alone, so headless renders and stripped checkouts work.
_SCALE_IMG_PATH = os.path.join(os.path.dirname(__file__),
                               "assets", "thrusty_scale.png")
_SCALE_FIGURE_M = 1.8                      # the mascot stands ~1.8 m tall (human)
_SCALE_BAR_M    = 5.0                      # the quantitative reference bar
_UNLOADED = object()                       # sentinel (image may be an ndarray)
_scale_img_cache = _UNLOADED


def _scale_image():
    global _scale_img_cache
    if _scale_img_cache is _UNLOADED:
        try:
            _scale_img_cache = mpimg.imread(_SCALE_IMG_PATH)
        except (FileNotFoundError, OSError):
            _scale_img_cache = None
    return _scale_img_cache

# Muted, print-friendly greys; the fairing is the one tinted element because
# it is the piece most worth eyeballing.
BODY, BODY_E     = "#c9ccd1", "#5a5e66"
SHROUD, SHROUD_E = "#b7c7d8", "#4a6076"
FIN, FIN_E       = "#9aa0a8", "#4a4e56"
STRAP            = "#bfc4cb"
NOSE             = "#d7dae0"
LABEL, LABEL_MUT = "#333333", "#555555"


from stage_outline import (outline as _stage_outline, profile as _outline_profile,
                           strapon_piece as _strapon_piece,
                           NOZZLE_NECK_FRACTION as _NECK)


def stage_chain(p):
    """The stage list, bottom (stage 1) first, walking the .stage2 chain."""
    out, node = [], p
    while node is not None:
        out.append(node)
        node = getattr(node, "stage2", None)
    return out


def fin_polygon(sgn, R, yb, span, root, tip, sweep_deg):
    """Side-elevation outline of one tail fin, vehicle nose-up (forward = +y).

    The trailing (aft) edge sits at the stage base yb; the leading edge sweeps
    back, so the tip is forward of the root and, for sweep_deg > 0, shifted aft
    (down).  Anchoring the tip to the TRAILING edge is what keeps a clipped fin
    (tip < root) reading as swept-back, not the reversed forward-swept look.
    Returns four (x, y) points: root-trailing, root-leading, tip-leading,
    tip-trailing.
    """
    off = span * math.tan(math.radians(sweep_deg))
    return [(sgn * R, yb),
            (sgn * R, yb + root),
            (sgn * (R + span), yb + tip - off),
            (sgn * (R + span), yb - off)]


def _body_patch(ax, x0, y0, d_bottom, d_top, length, color, edge):
    """A stage/interstage body from y0 up to y0+length, centred on x0.

    A cylinder when d_bottom == d_top, otherwise a frustum (trapezoid) tapering
    from d_bottom at the base to d_top at the top.
    """
    Rb, Rt = d_bottom / 2.0, d_top / 2.0
    if abs(d_bottom - d_top) < 1e-9:
        ax.add_patch(Rectangle((x0 - Rb, y0), d_bottom, length,
                               fc=color, ec=edge, lw=1.3, zorder=2))
    else:
        ax.add_patch(Polygon([(x0 - Rb, y0), (x0 + Rb, y0),
                              (x0 + Rt, y0 + length), (x0 - Rt, y0 + length)],
                             closed=True, fc=color, ec=edge, lw=1.3, zorder=2))


def _stage_top_diameter(s):
    """The diameter at the top of stage `s` — its top_diameter_m when the stage
    is conical (and set), else its base diameter."""
    d = float(getattr(s, "diameter_m", 0.0) or 0.6)
    if getattr(s, "conical", False):
        dt = float(getattr(s, "top_diameter_m", 0.0) or 0.0)
        if dt > 0:
            return dt
    return d


def exposed_front_object(p):
    """The reentry object that caps the stack with nothing over it — a
    SEPARATING object and no fairing — else None.

    It is the vehicle's front end in flight (_boost_front_geometry flies its
    own shape and length), and it is drawn to scale BESIDE the stack, so the
    stack stops at the top stage or its adapter: stacking a nose as well
    would show the front end twice, at a length nothing flies.  A fairing
    encloses its object, and a non-separating body is the last stage itself,
    so neither has one.  The schematic and the 3-D export both ask here."""
    if any((getattr(s, "shroud_length_m", 0.0) or 0.0) > 0.0
           for s in stage_chain(p)):
        return None
    from booster_models import effective_ro
    ro = effective_ro(p)
    if ro is None or getattr(ro, "separation_mode", "separating_ro") == "body":
        return None
    if float(getattr(ro, "diameter_m", 0.0) or 0.0) <= 0.0:
        return None
    return ro


def _reentry_shape(ax, x0, y0, diam, length, nose_r, color, edge):
    """A reentry vehicle drawn nose-up: a cone of base `diam` and height
    `length` from the base at y0, with the tip blunted to radius `nose_r`
    (0 = sharp).  Its own true geometry — no fabrication."""
    R = diam / 2.0
    rn = min(max(nose_r, 0.0), 0.9 * R)
    if rn <= 1e-6 or length <= rn:
        pts = [(x0 - R, y0), (x0 + R, y0), (x0, y0 + length)]        # sharp cone
    else:
        capc = y0 + length - rn                                      # cap centre
        n = 14
        arc = [(x0 + rn * math.cos(math.pi * i / n),
                capc + rn * math.sin(math.pi * i / n)) for i in range(n + 1)]
        pts = [(x0 - R, y0), (x0 + R, y0)] + arc                     # blunted cone
    ax.add_patch(Polygon(pts, closed=True, fc=color, ec=edge, lw=1.3, zorder=3))


def _biconic_shape(ax, x0, y0, diam, length, break_d, fore_len, nose_r,
                   color, edge):
    """A biconic RV nose-up: an aft frustum from base `diam` up to `break_d` at
    the junction, then a forward cone to a tip blunted to radius `nose_r`."""
    r_b, r_1 = diam / 2.0, break_d / 2.0
    La = length - fore_len                                # aft-frustum height
    rn = min(max(nose_r, 0.0), 0.9 * r_1)
    if rn <= 1e-6 or fore_len <= rn:
        fore = [(x0, y0 + length)]                        # sharp apex
    else:
        capc = y0 + length - rn
        n = 12
        fore = [(x0 + rn * math.cos(math.pi * i / n),
                 capc + rn * math.sin(math.pi * i / n)) for i in range(n + 1)]
    pts = ([(x0 - r_b, y0), (x0 + r_b, y0), (x0 + r_1, y0 + La)]
           + fore + [(x0 - r_1, y0 + La)])
    ax.add_patch(Polygon(pts, closed=True, fc=color, ec=edge, lw=1.3, zorder=3))


def _lifting_body_shape(ax, x0, y0, depth, length, color, edge):
    """A lifting body in side elevation, nose-up: the flat surface is a
    straight flank parallel to the axis (drawn on the left), the opposite
    surface slopes from the base up to the nose tip over the flat flank —
    visibly NOT a body of revolution.  `depth` is the side-view thickness at
    the base (wedge: the stored ⌀ = base depth; half-cone: ⌀/2, cut at the
    diametral plane).  The unmodeled spanwise width is flagged in the caption,
    never drawn."""
    h = depth / 2.0
    pts = [(x0 - h, y0), (x0 + h, y0), (x0 - h, y0 + length)]
    ax.add_patch(Polygon(pts, closed=True, fc=color, ec=edge, lw=1.3, zorder=3))


# Wall layers in a cross-section, by the catalog's material group; a second
# or third material of the same group takes the next shade, so a carbon tip
# on a carbon-phenolic body still reads as two materials.
LAYER_FILL = {"ablative": ("#8b5a2b", "#c4823f", "#5e3a17"),
              "insulative": ("#efe2a8", "#d9c66b", "#f7f0d2"),
              "metal": ("#a7adb4", "#6f7780", "#cfd3d8"),
              "hot_structure": ("#4b4f57", "#7b6f9a", "#2a2d33")}
LAYER_FILL_OTHER = ("#c9b8d9", "#9fc5b8", "#e0b7b7")
INTERIOR_FILL = "white"


def material_colours(sec):
    """{material key: fill} for every piece of a section, in order of
    appearance, one shade per distinct material within its group."""
    out, used = {}, {}
    for pc in sec.get("pieces", []):
        m = pc["material"]
        if pc["kind"] == "interior" or m in out:
            continue
        shades = LAYER_FILL.get(pc["group"], LAYER_FILL_OTHER)
        k = used.get(pc["group"], 0)
        out[m] = shades[k % len(shades)]
        used[pc["group"]] = k + 1
    return out


def _closed(profile, x0, y0, sgn=+1):
    """A half-section profile [(r, z)...] as a polygon closed along the
    axis, placed at (x0, y0) on the right (sgn +1) or left (-1) side."""
    return [(x0 + sgn * r, y0 + z) for r, z in profile]


def _ro_sectioned(ax, sec, x0, y0, color, edge):
    """The object from ro_section: the left half its outside, the right half
    cut open to show each piece of the wall (the layers, the nose tip ahead
    of its joint) and the space inside.  With nothing entered, both halves
    are the outside."""
    prof = sec["outline"]
    left = _closed(prof, x0, y0, -1)
    if not sec["pieces"]:
        right = _closed(prof, x0, y0, +1)
        pts = left + list(reversed(right))
        ax.add_patch(Polygon(pts, closed=True, fc=color, ec=edge, lw=1.3,
                             zorder=3))
        return
    ax.add_patch(Polygon(left, closed=True, fc=color, ec=edge, lw=1.3,
                         zorder=3))
    colours = material_colours(sec)
    for pc in sec["pieces"]:
        fc = (INTERIOR_FILL if pc["kind"] == "interior"
              else colours.get(pc["material"], LAYER_FILL_OTHER[0]))
        ax.add_patch(Polygon(_closed(pc["loop"], x0, y0), closed=True,
                             fc=fc, ec=edge, lw=0.6, zorder=3))
    ax.plot([x0, x0], [y0, y0 + sec["L"]], color=edge, lw=0.6, ls="-.",
            zorder=4)


def section_caption(sec):
    """One line per wall layer, outside in, then the nose tip, for a
    caption or legend."""
    out = [f"{lay['thickness_m'] * 100:.1f} cm {lay['label']}"
           for lay in sec["layers"]]
    nz = sec.get("nose")
    if nz:
        lab = next(pc["label"] for pc in sec["pieces"] if pc["kind"] == "nose")
        out.append(f"nose: {lab}, " + (
            f"solid {nz['extent_m'] * 100:.1f} cm" if nz["kind"] == "solid"
            else f"{nz['thickness_m'] * 100:.1f} cm shell back "
                 f"{nz['extent_m'] * 100:.1f} cm"))
    return out


def draw_ro_section(ax, ro, title=None):
    """The reentry object's cross-section, large: the outside on the left,
    the wall layers and the space inside them on the right, each layer
    labelled with its thickness and material, from ro_section (the module
    the 3-D export reads).  Says plainly what is not entered."""
    import ro_section
    ax.clear()
    ax.set_aspect("equal")
    ax.axis("off")
    sec = ro_section.section(ro)
    D, L = sec["D"], sec["L"]
    if D <= 0:
        ax.text(0.5, 0.5, "diameter not entered", ha="center", va="center",
                transform=ax.transAxes, color=LABEL_MUT)
        return sec
    if sec["form"] == "axisymmetric":
        _ro_sectioned(ax, sec, 0.0, 0.0, NOSE, BODY_E)
    elif sec["form"] == "wedge":
        _lifting_body_shape(ax, 0.0, 0.0, D, L, NOSE, BODY_E)
    else:
        _lifting_body_shape(ax, 0.0, 0.0, D / 2.0, L, NOSE, BODY_E)
    R = D / 2.0
    total = sum(lay["thickness_m"] for lay in sec["layers"])
    x_bar = R * 1.35
    w_bar = 0.12 * max(D, L)
    if total > 0:
        # The wall, magnified: every layer to scale against the others, the
        # outer face at the top, with the magnification stated.
        H = (0.62 if sec.get("nose") else 0.75) * L
        mag = H / total
        y = 0.9 * L
        colours = material_colours(sec)
        for lay in sec["layers"]:
            h = lay["thickness_m"] * mag
            ax.add_patch(Rectangle((x_bar, y - h), w_bar, h,
                                   fc=colours.get(lay["material"],
                                                  LAYER_FILL_OTHER[0]),
                                   ec=BODY_E, lw=0.6, zorder=3))
            ax.text(x_bar + w_bar * 1.15, y - h / 2.0,
                    f"{lay['thickness_m'] * 100:.1f} cm {lay['label']}",
                    fontsize=8, color=LABEL_MUT, va="center")
            y -= h
        ax.text(x_bar, 0.9 * L + 0.03 * L, f"wall, outside at top (×{mag:.0f})",
                fontsize=7.5, color=LABEL_MUT, va="bottom")
        ax.text(x_bar + w_bar * 1.15, y - 0.04 * L, "inside", fontsize=8,
                color=LABEL_MUT, va="top")
    if sec.get("nose"):
        # the nose tip's swatch, under the wall bar
        npc = next(pc for pc in sec["pieces"] if pc["kind"] == "nose")
        ys = 0.08 * L
        ax.add_patch(Rectangle((x_bar, ys), w_bar, 0.06 * L,
                               fc=material_colours(sec).get(
                                   npc["material"], LAYER_FILL_OTHER[0]),
                               ec=BODY_E, lw=0.6, zorder=3))
        ax.text(x_bar + w_bar * 1.15, ys + 0.03 * L, section_caption(sec)[-1],
                fontsize=8, color=LABEL_MUT, va="center")
    notes = []
    if not sec["layers"] and sec["form"] == "axisymmetric":
        notes.append("no wall layers entered (body layer thickness 0)")
    if sec.get("nose"):
        notes.append(section_caption(sec)[-1]
                     + f" (joint {sec['nose']['z_joint_m']:.3g} m up)")
    notes += sec["flags"]
    import textwrap
    lines = [title or (getattr(ro, "name", "") or "reentry object"),
             f"⌀{D:g} × {L:g} m"]
    for nt in notes:
        lines += textwrap.wrap(nt, 64)
    ax.text(-R, -0.08 * L, "\n".join(lines), fontsize=8, color=LABEL_MUT,
            va="top", ha="left")
    ax.set_xlim(-R * 1.1, x_bar + w_bar + 0.75 * max(D, L))
    ax.set_ylim(-0.08 * L - 0.12 * L * (len(lines)), L * 1.05)
    return sec


def _draw_reentry_object(ax, ro, view_right, yl, veh_right=0.0):
    """Draw the reentry object to scale in the lower-RIGHT corner, base on the
    y = 0 ground line, from its own stored geometry, with its text to the right.

    Wings: S and AR alone cannot define a planform on a conical body (they give
    area and slenderness, not position, root chord, or shape).  So the wings
    are drawn FAITHFULLY only when the optional planform fields are entered
    (wing_root_chord_m + wing_span_exposed_m, with wing_sweep_deg): a panel
    whose root follows the body flank, trailing edge on the base line, leading
    edge swept back from the spanwise axis.  With only a wing AREA stored, a
    small fixed-proportion delta tab is drawn at the aft flank and the label
    says "(schematic)" — an honest marker, never fake dimensions.  A length of
    0 falls back to a nominal cone and is flagged, like the nose.

    body_form "wedge" / "half_cone" draws the asymmetric side elevation (flat
    flank + sloped surface) with the form named in the caption; the wedge's
    unmodeled span is flagged, and wings — spanwise, out of the side-elevation
    plane — are reported in the caption but not drawn."""
    D = float(getattr(ro, "diameter_m", 0.0) or 0.0)
    if D <= 0:
        return
    L = float(getattr(ro, "length_m", 0.0) or 0.0)
    flag = ""
    if L <= 0:
        L = 1.6 * D
        flag = " (length unset)"
    rn = float(getattr(ro, "nose_radius_m", 0.0) or 0.0)
    R = D / 2.0

    # Body form: axisymmetric (default) or a lifting body.  Wedge: the stored
    # ⌀ is the base DEPTH (side-view thickness); half-cone: the stored ⌀ is
    # the full cone diameter, so the side view is ⌀/2 deep at the cut plane.
    form = str(getattr(ro, "body_form", "") or "axisymmetric")
    if form not in ("wedge", "half_cone"):
        form = "axisymmetric"
    lifting = form != "axisymmetric"
    depth = D if form == "wedge" else D / 2.0        # side-view base thickness
    R_view = (depth / 2.0) if lifting else R          # half-extent for layout

    # Biconic body when declared and geometrically valid; else a plain cone.
    # A body-of-revolution concept — ignored for the lifting-body forms.
    bic = None
    if getattr(ro, "biconic", False) and not lifting:
        Lf = float(getattr(ro, "fore_length_m", 0.0) or 0.0)
        Dbrk = float(getattr(ro, "break_diameter_m", 0.0) or 0.0)
        if 0 < Lf < L and 0 < Dbrk < D:
            bic = (Lf, Dbrk)

    def r_local(y):
        """Body flank radius at height y — cone or biconic piecewise."""
        if bic is not None:
            Lf, Dbrk = bic
            La, R1 = L - Lf, Dbrk / 2.0
            if y <= La:
                return R - y * (R - R1) / La
            return max(0.0, R1 * (1.0 - (y - La) / Lf))
        return max(0.0, R * (1.0 - y / L))

    # Wing depiction mode.  wing_geometry() is the single source of truth:
    # 'planform' → faithful panels + DERIVED S/AR in the label; 'direct' →
    # flagged schematic tab from the stored area; None → nothing.
    from booster_models import wing_geometry
    S_eff, AR_eff, w_src = wing_geometry(ro)
    w_rc = float(getattr(ro, "wing_root_chord_m", 0.0) or 0.0)
    w_ss = float(getattr(ro, "wing_span_exposed_m", 0.0) or 0.0)
    w_sw = float(getattr(ro, "wing_sweep_deg", 0.0) or 0.0)
    planform = (w_src == 'planform')
    wing_flag = ""
    if w_src == 'direct' and AR_eff <= 0:
        wing_flag = " · AR def."                      # polar fail-safe, flagged
    if lifting:
        # Spanwise panels are out of the drawing plane in a lifting-body side
        # elevation — the caption still reports S/AR, flagged "not drawn".
        wing_ext, glyph, planform = 0.0, False, False
    elif planform:
        wing_ext, glyph = w_ss, False
    elif w_src == 'direct':
        wing_ext, glyph = 0.35 * R, True              # fixed-proportion tab
    else:
        wing_ext, glyph = 0.0, False

    # Reserve room for the right-hand label from its pixel size (text is fixed
    # points, so its width in metres scales with the view).
    pos = ax.get_position(original=True)
    _fw_in, fh_in = ax.figure.get_size_inches()
    H = max(yl[1] - yl[0], 1e-6)
    m_per_in = H / max(pos.height * fh_in, 1e-6)
    label_w = 1.7 * m_per_in           # room for the longest label line
    x0 = view_right - 0.25 - label_w - (R_view + wing_ext)
    # Never drift left into (or past) the vehicle on small views: the RO stays
    # a clear margin right of the stack even if the label then runs tight.
    x0 = max(x0, veh_right + 0.4 + wing_ext + R_view)

    import ro_section
    sec = ro_section.section(ro)
    if lifting:
        _lifting_body_shape(ax, x0, 0.0, depth, L, NOSE, BODY_E)
    else:
        # The outline and wall layers from ro_section — the module the 3-D
        # export revolves — so the tangent sphere-cone, the biconic and each
        # analytic nose curve are drawn as exported; the right half is cut
        # open to show the layers when they are entered.
        _ro_sectioned(ax, sec, x0, 0.0, NOSE, BODY_E)

    if planform:
        # Faithful panel: root follows the flank from the base to the root
        # chord; trailing edge straight on the base line; the leading edge
        # sweeps back (from the spanwise axis) so the tip chord shrinks —
        # collapsing to a delta when the sweep consumes the whole chord.
        y_tip_le = min(max(w_rc - w_ss * math.tan(math.radians(w_sw)), 0.0), w_rc)
        for sgn in (+1, -1):
            pts = [(x0 + sgn * r_local(0.0), 0.0),
                   (x0 + sgn * r_local(w_rc), w_rc),
                   (x0 + sgn * (r_local(0.0) + w_ss), y_tip_le),
                   (x0 + sgn * (r_local(0.0) + w_ss), 0.0)]
            ax.add_patch(Polygon(pts, closed=True, fc=FIN, ec=FIN_E,
                                 lw=1.0, zorder=2))
    elif glyph:
        # Schematic tab: a small delta hugging the aft flank, deliberately
        # fixed-proportion (0.35·R out, 0.22·L up) — a marker, not a claim.
        rc_g = 0.22 * L
        for sgn in (+1, -1):
            pts = [(x0 + sgn * r_local(0.0), 0.0),
                   (x0 + sgn * r_local(rc_g), rc_g),
                   (x0 + sgn * (r_local(0.0) + wing_ext), 0.0)]
            ax.add_patch(Polygon(pts, closed=True, fc=FIN, ec=FIN_E,
                                 lw=1.0, zorder=2))

    name = getattr(ro, "name", "") or "RV"
    beta = float(getattr(ro, "beta_kg_m2", 0.0) or 0.0)
    ld = float(getattr(ro, "glider_LD", 0.0) or 0.0)
    if form == "wedge":
        size_line = f"depth {D:g} × {L:g} m{flag}"
    else:
        size_line = f"⌀{D:g}×{L:g} m{flag}"
    lines = [f"reentry object: {name}", size_line]
    if form == "wedge":
        # span is out of the side-elevation plane: reported, not drawn —
        # stored (body_span_m) when known, flagged when not.
        b_span = float(getattr(ro, "body_span_m", 0.0) or 0.0)
        lines.append(f"wedge lifting body · span {b_span:g} m (not drawn)"
                     if b_span > 0 else "wedge lifting body · span not modeled")
    elif form == "half_cone":
        lines.append("half-cone lifting body (side depth ⌀/2)")
    tail = []
    if beta > 0:
        tail.append(f"β {beta:,.0f}")
    if ld > 0:
        tail.append(f"L/D {ld:g}")
    if tail:
        lines.append(" · ".join(tail))
    if bic is not None:
        Lf, Dbrk = bic
        th1 = math.degrees(math.atan2(Dbrk / 2.0, Lf))
        th2 = math.degrees(math.atan2((D - Dbrk) / 2.0, L - Lf))
        lines.append(f"biconic {th1:.1f}°/{th2:.1f}°")
    if sec["pieces"]:
        lines.append("wall: " + " · ".join(section_caption(sec)))
    elif ro_section.LIFTING_NOT_SECTIONED in sec["flags"]:
        lines.append(ro_section.LIFTING_NOT_SECTIONED)
    if planform:
        lines.append(f"wings S={S_eff:.3g} m² · AR {AR_eff:.2g} (derived)")
    elif glyph:
        lines.append(f"wings S={S_eff:g} m² (schematic{wing_flag})")
    elif lifting and w_src is not None:
        # Wing data on a lifting body: reported, honestly not drawn (spanwise
        # panels are out of the side-elevation plane).
        if w_src == 'planform':
            lines.append(f"wings S={S_eff:.3g} m² · AR {AR_eff:.2g} "
                         "(derived · not drawn)")
        else:
            lines.append(f"wings S={S_eff:g} m² (not drawn{wing_flag})")
    # text to the RIGHT of the body/wings
    label_x = x0 + R_view + wing_ext + 0.2
    ax.text(label_x, L / 2.0, "\n".join(lines),
            va="center", ha="left", fontsize=7.5, color=LABEL_MUT)
    # widen the view rightward if the caption would run past the edge (keeps
    # the RO clear of the stack AND the text on-panel on narrow views)
    lbl_right = label_x + label_w
    if lbl_right > view_right:
        ax.set_xlim(ax.get_xlim()[0], lbl_right + 0.1)


def _nose_patch(ax, x0, y0, diam, length, color, edge, shape):
    """A nose from y0 up to y0+length, base width diam, centred on x0.

    Drawn from the TRUE analytic profile for the declared shape (the same
    curve the 3-D export revolves — one source of truth), so a tangent
    ogive, Von Kármán, LV-Haack and parabola each show their own outline.
    The differences ARE subtle at schematic scale (a few % of the local
    radius); honesty here means the curve is right, not that the shapes
    look dramatically different.
    """
    from blender_export import _nose_profile   # local: it imports this module
    R = diam / 2.0
    if R <= 0.0 or length <= 0.0:              # degenerate: plain taper
        shape = "cone"
    left = [(x0 - r, y0 + z) for (r, z) in _nose_profile(shape, R, length)]
    pts = left + [(2 * x0 - xx, yy) for (xx, yy) in reversed(left)]
    ax.add_patch(Polygon(pts, closed=True, fc=color, ec=edge, lw=1.2, zorder=3))


def draw_booster(ax, p, title=None):
    """Draw the stack on `ax` (cleared first).  Returns a summary dict:
    {'total_height_m': float, 'overall_length_m': float,
    'front_object_length_m': float, 'flags': [str, ...], 'front_end': {...}}
    — total_height_m is the stack as drawn; when an uncovered separating
    object caps it (drawn beside, see exposed_front_object) its length is
    front_object_length_m and overall_length_m adds it back, so the vehicle's
    length is still reported.  flags list every place a fallback stood in for
    unset data."""
    ax.clear()
    stages = stage_chain(p)
    flags = []
    x0 = 0.0
    finned = grid_finned = strap = None

    shroud_stage = next(
        (s for s in stages
         if (getattr(s, "shroud_length_m", 0.0) or 0.0) > 0.0), None)

    # DRAWN ≡ FLOWN (FRONT_END_DESIGN.md §3): the front end is read from the
    # SAME object the physics flies, effective_ro(p).  For a NON-SEPARATING
    # body (V-2/Scud) the reentering vehicle IS the last stage, so its
    # nose is carved SUBTRACTIVELY from the top of that stage (body length
    # unchanged) — never a cone stacked on top, and never a separate corner
    # object.  front_end records what was actually drawn, so the invariant is
    # machine-checkable.
    from booster_models import effective_ro as _effective_ro
    _eff_ro = _effective_ro(p)
    _sep = (getattr(_eff_ro, "separation_mode", "separating_ro")
            if _eff_ro is not None else None)
    _body_mode = (_eff_ro is not None and _sep == "body"
                  and float(getattr(_eff_ro, "diameter_m", 0.0) or 0.0) > 0.0
                  and shroud_stage is None)
    front_end = {"kind": "none", "shape": "", "nose_length_m": 0.0,
                 "body_diameter_m": 0.0}
    # A separating object with no fairing is drawn beside the stack, not on it.
    _front_obj = exposed_front_object(p)
    _bn_len = 0.0
    _bn_shape = ""
    # A declared biconic body draws its two cones (fore cone + aft frustum),
    # the same geometry the physics flies — biconic_nose_geometry is the ONE
    # source shared with the drag / CP paths, so DRAWN ≡ FLOWN holds.
    from booster_models import biconic_nose_geometry as _bic_geom
    _body_bic = _bic_geom(p) if _body_mode else None
    if _body_mode:
        _ls = stages[-1]
        _ls_d = float(getattr(_ls, "diameter_m", 0.0) or 0.6)
        _ls_L = float(getattr(_ls, "length_m", 0.0) or 1.0)
        _bn_len = float(getattr(_eff_ro, "body_nose_length_m", 0.0) or 0.0)
        _bn_shape = getattr(_eff_ro, "shape", "") or ""
        if _bn_len <= 0.0:
            _bn_len = min(3.0 * _ls_d, 0.5 * _ls_L)   # flagged default fraction
            flags.append(f"body nose length unset — {_bn_len:.2g} m used "
                         "(3⌀, capped at ½ body)")
        _bn_len = max(0.0, min(_bn_len, _ls_L))        # carved from the body
        if not _bn_shape:
            flags.append("body nose shape unset — cone shown")

    y = 0.0
    for i, s in enumerate(stages):
        d = float(getattr(s, "diameter_m", 0.0) or 0.6)
        L = float(getattr(s, "length_m", 0.0) or 1.0)
        R = d / 2.0
        d_top = _stage_top_diameter(s)                 # equals d unless conical
        if (i == len(stages) - 1) and _body_mode and _bn_len > 0.0:
            # Non-separating body: the forward _bn_len of this (last) stage is
            # the nose taper, carved from the body — cylinder below, the
            # declared analytic nose profile above.  Total height unchanged.
            _cyl = L - _bn_len
            if _cyl > 1e-9:
                _body_patch(ax, x0, y, d, d_top, _cyl, BODY, BODY_E)
            if _body_bic is not None:
                # Two cones carved from the top: aft frustum then fore cone.
                _biconic_shape(ax, x0, y + max(_cyl, 0.0), d_top,
                               _body_bic['nose_len_m'],
                               _body_bic['break_diameter_m'],
                               _body_bic['fore_len_m'],
                               float(getattr(_eff_ro, 'nose_radius_m', 0.0) or 0.0),
                               BODY, BODY_E)
                front_end = {"kind": "body_biconic", "shape": "biconic",
                             "nose_length_m": _body_bic['nose_len_m'],
                             "body_diameter_m": float(_eff_ro.diameter_m)}
            else:
                _nose_patch(ax, x0, y + max(_cyl, 0.0), d_top, _bn_len,
                            BODY, BODY_E, _bn_shape or "cone")
                front_end = {"kind": "body_nose", "shape": _bn_shape or "cone",
                             "nose_length_m": _bn_len,
                             "body_diameter_m": float(_eff_ro.diameter_m)}
        else:
            _body_patch(ax, x0, y, d, d_top, L, BODY, BODY_E)
        # The stage's outline beyond a cylinder (stage_outline: the same
        # numbers the spent-stage physics flies).  Drawn over the body.
        _o = _stage_outline(s)
        _extra = []
        if _o.skirt_len > 0.0:
            _rs = _o.skirt_d / 2.0
            ax.add_patch(Polygon([(x0 - _rs, y), (x0 + _rs, y),
                                  (x0 + R, y + _o.skirt_len),
                                  (x0 - R, y + _o.skirt_len)], closed=True,
                                 fc=BODY, ec=BODY_E, lw=1.2, zorder=2.2))
            _extra.append(f"skirt ⌀{_o.skirt_d:g}×{_o.skirt_len:g} m")
        elif (float(getattr(s, "aft_skirt_length_m", 0.0) or 0.0) > 0.0
              or float(getattr(s, "aft_skirt_diameter_m", 0.0) or 0.0) > 0.0):
            flags.append(f"S{i+1} aft skirt incomplete or not wider than "
                         f"the body — not drawn or flown")
        if _o.nozzle_len > 0.0:
            _rn, _re = _NECK * _o.nozzle_d / 2.0, _o.nozzle_d / 2.0
            ax.add_patch(Polygon([(x0 - _rn, y), (x0 + _rn, y),
                                  (x0 + _re, y - _o.nozzle_len),
                                  (x0 - _re, y - _o.nozzle_len)], closed=True,
                                 fc=STRAP, ec=BODY_E, lw=1.1, zorder=4))
            _extra.append(f"nozzle +{_o.nozzle_len:g} m")
            if int(getattr(s, "n_nozzles", 1) or 1) > 1:
                flags.append(f"S{i+1} nozzle cluster drawn and flown as one "
                             f"nozzle of the total exit area")
        elif float(getattr(s, "nozzle_protrusion_m", 0.0) or 0.0) > 0.0:
            flags.append(f"S{i+1} nozzle protrusion set but no exit area — "
                         f"not drawn or flown")
        _lbl = (f"S{i+1}: ⌀{d:g}→{d_top:g}×{L:g} m" if d_top != d
                else f"S{i+1}: ⌀{d:g}×{L:g} m")
        if _extra:
            _lbl += "\n" + " · ".join(_extra)
        ax.text(x0 + R + 0.15, y + L / 2, _lbl,
                va="center", ha="left", fontsize=8, color=LABEL)
        if getattr(s, "has_fins", False) and (getattr(s, "fin_span_m", 0.0) or 0) > 0:
            finned = (s, y)
        if getattr(s, "has_grid_fins", False) and (getattr(s, "n_grid_fins", 0) or 0) > 0:
            grid_finned = (s, y, L)
        if (getattr(s, "n_boosters", 0) or 0) > 0:
            strap = (s, y, L)
        # Stages butt directly together — a diameter change shows as an honest
        # step, never a smoothing frustum (inventing one would hide an
        # unspecified transition, which this panel exists to surface).  A real
        # adapter is drawn ONLY when the stage declares an interstage; its
        # diameters are DERIVED (this stage's top -> the base of whatever sits
        # on it: the next stage, or an uncovered object riding the last stage)
        # so nothing about the transition is fabricated.
        y = y + L
        if getattr(s, "has_interstage", False) \
                and (getattr(s, "interstage_length_m", 0.0) or 0) > 0:
            il = float(s.interstage_length_m)
            d_is_bot = d_top                                    # this stage's top
            nxt = stages[i + 1] if i + 1 < len(stages) else None
            if nxt is not None:
                d_is_top = float(getattr(nxt, "diameter_m", 0.0) or d_top)
            elif _front_obj is not None:
                d_is_top = float(_front_obj.diameter_m)         # object's base
            else:
                d_is_top = d_top                                 # hold
            _body_patch(ax, x0, y, d_is_bot, d_is_top, il, SHROUD, BODY_E)
            _im = getattr(s, "interstage_mass_kg", 0.0) or 0.0
            _jt = getattr(s, "interstage_jettison_s", None)
            _jtxt = f"{_jt:g} s" if _jt is not None else "with stage"
            ax.text(x0 - max(d_is_bot, d_is_top) / 2 - 0.15, y + il / 2,
                    f"interstage {il:g} m, {_im:g} kg\njett {_jtxt}",
                    va="center", ha="right", fontsize=7.5, color=SHROUD_E)
            y += il

    top = stages[-1]
    top_surface_d = _stage_top_diameter(top)       # nose/fairing sits on this
    if shroud_stage is not None:
        sd = float(getattr(shroud_stage, "shroud_diameter_m", 0.0)
                   or top_surface_d)
        sl = float(getattr(shroud_stage, "shroud_length_m", 0.0) or 2 * sd)
        shape = getattr(shroud_stage, "shroud_nose_shape", "") or ""
        nose = float(getattr(shroud_stage, "shroud_nose_length_m", 0.0) or 0.0)
        R = sd / 2.0
        flag = ""
        if not (0.0 < nose <= sl):
            nose = 0.45 * sl
            flag = " (nose length unset)"
        if not shape:
            flag += " (shape unset — cone shown)"
        cyl = sl - nose
        if cyl > 0:
            ax.add_patch(Rectangle((x0 - R, y), sd, cyl,
                                   fc=SHROUD, ec=SHROUD_E, lw=1.3, zorder=3))
        _nose_patch(ax, x0, y + cyl, sd, nose, SHROUD, SHROUD_E, shape or "cone")
        ax.text(x0 - R - 0.15, y + sl * 0.5,
                f"fairing ⌀{sd:g}×{sl:g} m{flag}".replace(" (", "\n("),
                va="center", ha="right", fontsize=8, color=SHROUD_E)
        if flag:
            flags.append("fairing" + flag)
        front_end = {"kind": "fairing", "shape": shape or "cone",
                     "nose_length_m": nose, "body_diameter_m": sd}
        nose_base_d = sd
        y += sl
    elif _body_mode:
        # The nose was carved into the last stage above (subtractive); nothing
        # is stacked on top.  nose_base_d for the aerospike is the body ⌀.
        nose_base_d = top_surface_d or float(_eff_ro.diameter_m) or 1.0
    elif _front_obj is not None:
        # The object IS the front end and is drawn to scale in the corner;
        # nothing is stacked here, so the stack ends at the stage / adapter.
        front_end = {"kind": "separate_object",
                     "shape": getattr(_front_obj, "shape", "") or "",
                     "nose_length_m": float(_front_obj.length_m or 0.0),
                     "body_diameter_m": float(_front_obj.diameter_m)}
        nose_base_d = float(_front_obj.diameter_m)
    else:
        nd = top_surface_d or 1.0
        # No object drawn beside the stack (none composed, or one with no ⌀
        # set): the stack carries its own front end.  Shape from the composed
        # object when there is one, else the top stage's stored nose shape.
        shape = ((getattr(_eff_ro, "shape", "") if _eff_ro is not None else "")
                 or getattr(top, "nose_shape", "") or "")
        nl = float(getattr(top, "nose_length_m", 0.0) or 0.0)
        flag = ""
        if nl <= 0.0:
            nl = 1.6 * nd
            flag = " (nose length unset)"
        if not shape:
            flag += " (shape unset — cone shown)"
        _nose_patch(ax, x0, y, nd, nl, NOSE, BODY_E, shape or "cone")
        ax.text(x0 - nd / 2 - 0.15, y + 0.5 * nl,
                f"payload / RV{flag}".replace(" (", "\n("),
                va="center", ha="right", fontsize=8, color=LABEL_MUT)
        if flag:
            flags.append("nose" + flag)
        front_end = {"kind": "declared_nose" if nl and flag == "" else "fallback",
                     "shape": shape or "cone", "nose_length_m": nl,
                     "body_diameter_m": nd}
        nose_base_d = nd
        y += nl

    # Aerospike — a forward drag-reduction probe from the nose apex.  Length and
    # aerodisk diameter come straight from the stored ratios (× the forebody
    # diameter): aerospike_LD = spike length / D, aerospike_dD = disk ⌀ / D
    # (0 = pointed).  A top-level booster property, so read from the root node.
    a_LD = float(getattr(p, "aerospike_LD", 0.0) or 0.0)
    if a_LD > 0 and _front_obj is not None:
        # The probe stands on the nose, and the nose is the separate object —
        # a spike out of the stack's flat top would be drawn nowhere real.
        flags.append("aerospike not drawn — it rides the separate "
                     "object's nose")
    elif a_LD > 0:
        a_dD = float(getattr(p, "aerospike_dD", 0.0) or 0.0)
        L_spike = a_LD * nose_base_d
        tip_y = y + L_spike
        ax.plot([x0, x0], [y, tip_y], color=BODY_E, lw=2.0, zorder=4)   # stalk
        if a_dD > 0:                                        # aerodisk at the tip
            disk_d = a_dD * nose_base_d
            ax.add_patch(Rectangle((x0 - disk_d / 2, tip_y - 0.02 * nose_base_d),
                                   disk_d, 0.04 * nose_base_d,
                                   fc=BODY, ec=BODY_E, lw=1.0, zorder=4))
            _lbl = f"aerospike {L_spike:.2g} m · disk ⌀{disk_d:.2g} m"
        else:                                               # pointed spike
            _lbl = f"aerospike {L_spike:.2g} m (pointed)"
        ax.text(x0 + nose_base_d / 2 + 0.15, y + L_spike / 2, _lbl,
                va="center", ha="left", fontsize=7.5, color=LABEL_MUT)
        y = tip_y

    if finned:
        s, yb = finned
        d = float(s.diameter_m); R = d / 2.0
        span = float(s.fin_span_m)
        root = float(getattr(s, "fin_root_chord_m", 0.0) or 0.8 * span)
        tip = float(getattr(s, "fin_tip_chord_m", 0.0) or 0.4 * root)
        sweep_deg = float(getattr(s, "fin_sweep_deg", 0.0) or 0.0)
        off = span * math.tan(math.radians(sweep_deg))
        for sgn in (+1, -1):
            pts = fin_polygon(sgn, R, yb, span, root, tip, sweep_deg)
            ax.add_patch(Polygon(pts, closed=True, fc=FIN, ec=FIN_E,
                                 lw=1.1, zorder=1))
        # label BELOW the fins (clear of the planform), never across them
        ax.text(0, yb - max(0.0, off) - 0.4,
                f"{int(s.n_fins or 4)} fins  span {span:g} m",
                va="top", ha="center", fontsize=7.5, color=LABEL_MUT)

    if grid_finned:
        s, yb, Lc = grid_finned
        d = float(s.diameter_m); R = d / 2.0
        gh = float(getattr(s, "grid_fin_height_m", 0.0) or 0.15 * d)
        gc = float(getattr(s, "grid_fin_chord_m", 0.0) or gh)
        # Grid fins sit at the stage BASE (aft), like tail fins — the panel's
        # bottom edge just above the base line, not partway up the body.
        yg = yb + 0.2
        for sgn in (+1, -1):
            ax.add_patch(Rectangle((sgn * R if sgn > 0 else -R - gh, yg),
                                   gh, gc, fc=FIN, ec=FIN_E, lw=1.0,
                                   zorder=1, hatch="++"))
        ax.text(0, yb - 0.4,
                f"{int(s.n_grid_fins)} grid fins {gh:g}×{gc:g} m",
                va="top", ha="center", fontsize=7.5, color=LABEL_MUT)

    if strap:
        s, yb, Lc = strap
        n = int(s.n_boosters)
        # The strap-on is drawn from its ONE outline (stage_outline), the
        # same the spent casing is flown with and ascent drag is built from.
        # Nothing is invented: with no nose entered it is flat-fronted, as
        # flown; with no length entered it is 2 x diameter, as flown.
        piece = _strapon_piece(s)
        if piece is not None:
            _o = _stage_outline(piece)
            bd, bL = _o.d, _o.L
            flag = ""
            if piece.length_unset:
                flag = " (len. unset)"
                flags.append("strap-on (length unset — 2 × diameter drawn "
                             "and flown)")
            if _o.nose_len <= 0.0:
                flags.append("strap-on nose (shape and length unset — flat "
                             "front drawn and flown; ascent drag from the "
                             f"entered Cd {float(s.booster_cd):g})")
            if (_o.nozzle_len <= 0.0 and float(getattr(
                    s, "booster_nozzle_protrusion_m", 0.0) or 0.0) > 0.0):
                flags.append("strap-on nozzle protrusion set but no exit "
                             "area — not drawn or flown")
            cR = float(s.diameter_m) / 2.0
            R = bd / 2.0
            prof = _outline_profile(piece)             # (x from front, r)
            for sgn in (+1, -1):
                cx = sgn * (cR + R + 0.05)
                left = [(cx - r, yb + bL - x) for (x, r) in prof]
                pts = left + [(2 * cx - xx, yy) for (xx, yy) in reversed(left)]
                ax.add_patch(Polygon(pts, closed=True, fc=STRAP, ec=BODY_E,
                                     lw=1.1, zorder=1))
            _bits = [f"⌀{bd:g}×{bL:.1f} m{flag}"]
            if _o.nose_len > 0.0:
                _bits.append(f"{_o.nose_shape} nose {_o.nose_len:g} m")
            if _o.skirt_len > 0.0:
                _bits.append(f"skirt ⌀{_o.skirt_d:g}×{_o.skirt_len:g} m")
            if _o.nozzle_len > 0.0:
                _bits.append(f"nozzle +{_o.nozzle_len:g} m")
            # label in the tall clear LEFT margin at the strap top, wrapped so
            # it never runs over the core body (nor off the panel edge)
            ax.text(-(cR + 2 * R + 0.35), yb + bL,
                    f"{n}× strap-on\n" + "\n".join(_bits),
                    va="center", ha="right", fontsize=7.5, color=LABEL_MUT)

    ax.set_aspect("equal")
    ax.relim(); ax.autoscale_view()
    xl, yl = ax.get_xlim(), ax.get_ylim()
    _new_left, _view_right = _draw_scale_reference(ax, xl, yl)
    # A to-scale reentry object in the lower-right corner (when a loadout object
    # is composed onto the stack); drawn from its own geometry.  A NON-
    # separating body is NOT a separate object — it was drawn in place as the
    # last stage's nose above — so it gets neither the corner callout nor a
    # containment check (there is nothing for it to be contained in).
    _ro = getattr(p, "ro", None)
    if (_ro is not None and not _body_mode
            and float(getattr(_ro, "diameter_m", 0.0) or 0.0) > 0):
        _draw_reentry_object(ax, _ro, _view_right, yl, veh_right=xl[1])
        # Containment check: does this RO actually fit inside the drawn
        # fairing?  (fairing_fit is None without one — an uncovered object
        # is the front end, drawn right here, not inside anything.)
        from fairing_fit import fairing_fit, fairing_fit_note, \
            fairing_fit_short
        _fit = fairing_fit(p)
        if _fit is not None and not _fit["fits"]:
            flags.append(fairing_fit_note(_fit))   # full sentence: flags,
            ax.text(0.5, 0.998, fairing_fit_short(_fit),   # short: canvas
                    transform=ax.transAxes, ha="center", va="top",
                    fontsize=9, color="#b0201f", weight="bold", zorder=6)
    # Full-stack fuelled CG — the classic center-of-gravity symbol (a circle
    # with two opposite quadrants filled) on the axis at the balance station.
    _draw_cg_marker(ax, p, y)
    if title:
        ax.set_title(title, fontsize=11, weight="bold")
    ax.axis("off")
    _obj_len = (float(getattr(_front_obj, "length_m", 0.0) or 0.0)
                if _front_obj is not None else 0.0)
    return {"total_height_m": y, "overall_length_m": y + _obj_len,
            "front_object_length_m": _obj_len,
            "flags": flags, "front_end": front_end}


def _draw_cg_marker(ax, p, total_h):
    """Draw the FUELLED (liftoff) CG symbol — propellant plus warhead.  This is
    the ONLY CG the schematic shows: the burnt-out body's re-entry CG is a
    different quantity (used by the trim gate for glide stability) and is
    reported in the trim/stability readout, not drawn here.  estimate_cg
    measures x AFT FROM THE NOSE; the schematic is nose-up with the base at y=0,
    so a CG at x_cg sits at y = total − x_cg on the axis."""
    try:
        from grid_fin_sizing import estimate_cg
        x_fuel, L_est = estimate_cg(p, fuelled=True)
    except Exception:
        return
    d_body = float(getattr(p, "diameter_m", 0.0) or 1.0)
    r = d_body / 20.0                                # symbol radius = ⌀/20
    # Pixel floor so a slender vehicle's marker stays legible: convert a
    # minimum on-screen radius to data units from the axes geometry (equal
    # aspect, so the y scale sets it).  Recomputed each redraw, so it holds
    # after a resize.
    _MIN_PX = 9.0
    try:
        fig = ax.figure
        ax_h_px = ax.get_position().height * fig.get_size_inches()[1] * fig.dpi
        yl = ax.get_ylim()
        data_per_px = (yl[1] - yl[0]) / max(ax_h_px, 1.0)
        r = max(r, _MIN_PX * data_per_px)
    except Exception:
        pass

    # classic CG glyph: two opposite quadrants filled, two white, black rim
    y_cg = max(0.0, min(total_h, L_est - x_fuel))
    for a0 in (0.0, 180.0):
        ax.add_patch(Wedge((0.0, y_cg), r, a0, a0 + 90.0, facecolor="black",
                           edgecolor="black", lw=0.8, zorder=6))
    for a0 in (90.0, 270.0):
        ax.add_patch(Wedge((0.0, y_cg), r, a0, a0 + 90.0, facecolor="white",
                           edgecolor="black", lw=0.8, zorder=6))
    ax.add_patch(Circle((0.0, y_cg), r, fill=False, edgecolor="black",
                        lw=1.0, zorder=7))


def _draw_scale_reference(ax, xl, yl):
    """Anchor the reference group (~1.8 m Thrusty · thin 5 m bar · "5 m") in the
    LOWER-LEFT corner of the panel, feet/base on the y = 0 ground line.

    A tall, thin stack makes the equal-aspect axes box tall and narrow, which
    matplotlib centres in the panel — so a group pinned just left of the stack
    rides toward the middle and crowds it (all the empty space is panel padding
    outside the box).  We instead widen the data x-range to fill the axes box
    exactly, which removes the centring padding, then place the group at the
    far left.  The mascot's metre height is unchanged (equal aspect), only its
    position moves.  Falls back to the bar alone when the asset is absent."""
    img = _scale_image()
    fig_w = 0.0
    if img is not None:
        h_px, w_px = img.shape[0], img.shape[1]
        fig_w = _SCALE_FIGURE_M * (w_px / h_px)         # preserve the art's aspect
    bar_gap, label_w = 0.35, 0.8
    group_w = fig_w + bar_gap + 0.2 + label_w           # silhouette · bar · "5 m"

    # Data width that fills the axes box at equal aspect: box_aspect × height.
    figr = ax.figure
    pos = ax.get_position(original=True)   # panel rect BEFORE equal-aspect shrink
    fw_in, fh_in = figr.get_size_inches()
    box_aspect = (pos.width * fw_in) / max(pos.height * fh_in, 1e-6)
    H = max(yl[1] - yl[0], 1e-6)
    want_w = max(box_aspect * H, group_w + 1.0)
    # Keep the stack centred (its side labels stay clear of the panel edges,
    # since text is not counted in autoscale) and fill the box; the extra width
    # opens as empty margin the group drops into at the lower-left.
    cx = 0.5 * (xl[0] + xl[1])
    new_left = cx - want_w / 2.0
    view_right = cx + want_w / 2.0

    x = new_left + 0.3                                   # left margin
    if img is not None:
        left, right = x, x + fig_w
        # origin='upper' puts image row 0 (the head) at the top of the extent
        ax.imshow(img, extent=(left, right, 0.0, _SCALE_FIGURE_M),
                  aspect="equal", zorder=3, interpolation="antialiased")
        bar_x = right + bar_gap
    else:
        bar_x = x
    # Thin 5 m reference bar with end ticks — reads as a rule, not a beam
    ax.plot([bar_x, bar_x], [0, _SCALE_BAR_M], color="k", lw=1.0, zorder=4)
    for yy in (0.0, _SCALE_BAR_M):
        ax.plot([bar_x - 0.12, bar_x + 0.12], [yy, yy],
                color="k", lw=1.0, zorder=4)
    ax.text(bar_x + 0.18, _SCALE_BAR_M / 2, "5 m",
            va="center", ha="left", fontsize=9, weight="bold")

    # imshow re-tightens the view; restore the full extent (group at far left,
    # stack toward the right) so the box fills the panel and nothing is centred.
    ax.set_xlim(new_left, view_right)
    ax.set_ylim(yl)
    return new_left, view_right
