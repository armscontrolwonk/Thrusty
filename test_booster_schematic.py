"""Schematic renderer (booster_schematic.draw_booster).

The panel exists to make bad geometry visible, so the tests hold it to the
same data-honesty it enforces: heights are the arithmetic of stored fields
(identity, not eyeball), unset fields must surface as flags rather than be
silently invented, and the nose must point forward (the sin-vs-cos inverted
cone was a real prototype bug).  Nothing here pins a "pretty" outcome.
"""

import glob
import json
import math

import pytest

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure

from booster_models import booster_from_dict
from booster_schematic import draw_booster, stage_chain, fin_polygon


def _ax():
    return Figure(figsize=(4, 8)).add_subplot(111)


def _load(name):
    return booster_from_dict(
        json.load(open(f"booster_library/{name}.booster.json")))


# ── nose patch draws the TRUE analytic profile per declared shape ───────────
def test_nose_patch_uses_the_declared_analytic_profile():
    """The schematic's nose outline is the same curve the 3-D export
    revolves (one source of truth — no more one-cosine-fits-all): the four
    curved shapes each draw their OWN profile, so e.g. tangent ogive and
    Von Kármán genuinely differ (subtly — a few % of local radius is what
    the real equations give at equal L and ⌀)."""
    from booster_schematic import _nose_patch
    from blender_export import _nose_profile

    def outline(shape):
        ax = _ax()
        _nose_patch(ax, 0.0, 0.0, 2.0, 3.0, "#eee", "#333", shape)
        return [tuple(v) for v in ax.patches[-1].get_xy()]

    for s in ("tangent_ogive", "von_karman", "lv_haack", "parabola"):
        # left edge == the export's analytic profile, mirrored to x0=0
        want = [c for r, z in _nose_profile(s, 1.0, 3.0) for c in (-r, z)]
        got = [c for pt in outline(s)[:len(want) // 2] for c in pt]
        assert got == pytest.approx(want), s
    # the shapes genuinely differ (all four sample the same z grid): the
    # real equations put them a few % of local radius apart at equal L, ⌀
    prof = {s: _nose_profile(s, 1.0, 3.0)
            for s in ("tangent_ogive", "von_karman", "lv_haack", "parabola")}
    names = list(prof)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert any(abs(ra - rb) > 1e-3 for (ra, _), (rb, _)
                       in zip(prof[a], prof[b])), (a, b)


# ── every library booster draws without error ───────────────────────────────
def test_every_library_booster_renders():
    for f in glob.glob("booster_library/*.booster.json"):
        b = booster_from_dict(json.load(open(f)))
        info = draw_booster(_ax(), b)
        assert info["total_height_m"] > 0, f
        assert math.isfinite(info["total_height_m"]), f


# ── height is the arithmetic of the stored fields ───────────────────────────
def test_total_height_is_sum_of_stage_lengths_plus_front_end():
    """AUR: 5.0 (S1) + 2.6 (S2) + 2.67 (full-length conical fairing) with no
    interstage frustum (constant diameter).  The identity that caught the
    original 10.2 m all-up-round-in-the-S1-field error."""
    info = draw_booster(_ax(), _load("AUR"))
    assert info["total_height_m"] == (5.0 + 2.6 + 2.67)


def test_corrected_aur_carries_no_fallback_flags():
    """AUR's geometry is fully specified (shape=cone, nose length set), so
    the drawing must not need — or report — any invented values."""
    info = draw_booster(_ax(), _load("AUR"))
    assert info["flags"] == []


def test_unset_fields_are_flagged_not_silently_defaulted():
    """Minotaur's shroud has no nose shape/length in the file; Strypi's
    strap-ons have no length.  Fallbacks are drawn but must be declared."""
    mi = draw_booster(_ax(), _load("Minotaur-IV_-_HTV-2"))
    assert any("shape unset" in f for f in mi["flags"])
    st = draw_booster(_ax(), _load("Strypi_VIII_R"))
    assert any("strap-on" in f and "unset" in f for f in st["flags"])


# ── the nose points forward ─────────────────────────────────────────────────
def test_nose_apex_is_the_topmost_point():
    """The stack's maximum y must lie on the vehicle centreline (the nose
    tip), not at a shoulder — a taper drawn the wrong way round (the
    inverted-cone bug) puts the widest section at the very top instead."""
    ax = _ax()
    info = draw_booster(ax, _load("AUR"))
    top_y = info["total_height_m"]
    for patch in ax.patches:
        for (x, y) in patch.get_path().vertices:
            if abs(y - top_y) < 1e-9:
                assert abs(x) < 1e-9, (x, y)


# ── feature presence tracks the data ────────────────────────────────────────
def test_features_draw_iff_the_data_declares_them():
    """Strypi (fins + strap-ons) must produce more patches than a plain
    single-stack of the same stage count would; a booster with no fins,
    shroud, or straps must not sprout any."""
    plain = draw_booster(_ax(), _load("No-dong"))
    assert plain["flags"] == [] or all("strap" not in f for f in plain["flags"])
    ax_st = _ax()
    draw_booster(ax_st, _load("Strypi_VIII_R"))
    ax_nd = _ax()
    draw_booster(ax_nd, _load("No-dong"))
    assert len(ax_st.patches) > len(ax_nd.patches)


# ── tail fins point the right way ────────────────────────────────────────────
def test_fin_trailing_edge_sits_at_the_base_not_floating_high():
    """The reversed-fin bug: anchoring the tip to the leading edge left a
    clipped fin (tip < root) floating above the base with a forward-swept
    trailing edge.  A correct tail fin has its trailing edge AT the base (or
    below, once swept), never hanging above it."""
    yb = 0.0
    for sweep in (0.0, 30.0, 45.0):
        pts = fin_polygon(+1, R=0.66, yb=yb, span=1.0, root=2.0, tip=1.0,
                          sweep_deg=sweep)
        ys = [p[1] for p in pts]
        # the fin's lowest point (a tip trailing corner) is at or below the base
        assert min(ys) <= yb + 1e-9, (sweep, ys)
        # and the highest point is the root leading edge, at yb + root
        assert max(ys) == yb + 2.0


def test_leading_edge_is_swept_back_not_forward():
    """Going outboard, the leading (forward, upper) edge must move AFT (down):
    the tip leading edge is below the root leading edge.  Forward sweep (tip
    leading above root leading) is the reversed rendering."""
    root = 1.5
    root_leading_y = 0.0 + root
    for sweep in (0.0, 20.0, 40.0):
        _, _, tip_leading, _ = fin_polygon(+1, R=0.5, yb=0.0, span=1.0,
                                           root=root, tip=0.6, sweep_deg=sweep)
        assert tip_leading[1] < root_leading_y, (sweep, tip_leading)


# ── aerospike / aerodisk (drawn only when ticked) ───────────────────────────
def _strypi(LD=0.0, dD=0.0):
    b = _load("Strypi_VIII_R")
    b.aerospike_LD = LD
    b.aerospike_dD = dD
    return b


def test_aerospike_length_is_LD_times_forebody_and_adds_height():
    """Spike length = aerospike_LD × forebody diameter, drawn forward from the
    nose apex — so the stack's drawn height grows by exactly that."""
    fb = _load("Strypi_VIII_R").stage2.diameter_m        # forebody = top-stage ⌀
    h0 = draw_booster(_ax(), _strypi(LD=0.0))["total_height_m"]
    h1 = draw_booster(_ax(), _strypi(LD=1.5))["total_height_m"]
    assert h1 == pytest.approx(h0 + 1.5 * fb)


def test_no_aerospike_draws_nothing_extra():
    """LD = 0 (unticked) must be byte-identical to a plain nose — no stalk."""
    fb = _load("Strypi_VIII_R").stage2.diameter_m
    h0 = draw_booster(_ax(), _strypi(LD=0.0))["total_height_m"]
    # a vehicle with no aerospike has no vertical stalk line rising past the nose
    ax = _ax(); draw_booster(ax, _strypi(LD=0.0))
    tops = [max(ln.get_ydata()) for ln in ax.lines if len(ln.get_ydata()) == 2]
    assert all(t <= h0 + 1e-9 for t in tops)


def test_aerodisk_is_one_extra_patch_only_when_dD_positive():
    """A pointed spike (dD = 0) adds no patch; a disk (dD > 0) adds exactly one
    (the aerodisk), sized aerospike_dD × forebody."""
    from matplotlib.patches import Rectangle
    n_point = sum(isinstance(p, Rectangle)
                  for p in _draw_patches(_strypi(LD=1.5, dD=0.0)))
    n_disk = sum(isinstance(p, Rectangle)
                 for p in _draw_patches(_strypi(LD=1.5, dD=0.3)))
    assert n_disk == n_point + 1


def _draw_patches(b):
    ax = _ax()
    draw_booster(ax, b)
    return ax.patches


# ── reentry object drawn to scale in the lower-right ────────────────────────
def _with_ro(bname="Strypi_VIII_R", roname="C-HGB"):
    import booster_models as mm
    from booster_models import ro_from_dict
    p = _load(bname)
    ro = ro_from_dict(json.load(open(f"ro_library/{roname}.ro.json")))
    p = mm.compose_loadout(p, ro, 1)
    p.ro = ro
    return p, ro


def test_reentry_object_drawn_to_scale_bottom_right():
    """When a loadout object is composed, it is drawn as a cone of its true
    base diameter, base on the ground line (y=0), over on the right side."""
    from matplotlib.patches import Polygon
    p, ro = _with_ro()
    ax = _ax()
    draw_booster(ax, p)
    found = False
    for patch in ax.patches:
        if isinstance(patch, Polygon):
            v = patch.get_path().vertices
            w = v[:, 0].max() - v[:, 0].min()
            if abs(w - ro.diameter_m) < 1e-6 and v[:, 1].min() <= 1e-9 \
                    and v[:, 0].min() > 0:                  # right side, base at 0
                found = True
    assert found, "reentry-object cone not found at lower-right"


def test_reentry_object_wings_drawn_only_when_area_set():
    """Wings appear only when a wing area (or planform) is stored — two small
    surfaces; a reentry object with neither draws none."""
    import dataclasses
    p0, _ = _with_ro()                              # C-HGB: no wing area
    ax0 = _ax(); draw_booster(ax0, p0)
    n0 = len(ax0.patches)
    p1, ro1 = _with_ro()
    p1.ro = dataclasses.replace(ro1, wing_area_m2=0.2, wing_aspect_ratio=0.0)
    ax1 = _ax(); draw_booster(ax1, p1)
    assert len(ax1.patches) == n0 + 2              # two wing patches


def test_area_only_wings_are_flagged_schematic_not_fake_dimensions():
    """S and AR alone cannot define a planform (no position, root chord, or
    shape), so with only an area stored the wings draw as a FIXED-proportion
    tab and the label declares '(schematic' — never dimensions derived by
    invention (the old 0.25·R clamp)."""
    import dataclasses
    p, ro = _with_ro(bname="AUR")            # finless: only the RO's wings at y=0
    p.ro = dataclasses.replace(ro, wing_area_m2=0.2, wing_aspect_ratio=0.0)
    ax = _ax(); draw_booster(ax, p)
    wing_txt = [t.get_text() for t in ax.texts if "wings" in t.get_text()]
    assert wing_txt and "(schematic" in wing_txt[0]
    # the tab is proportional to the BODY (0.35·R outboard), independent of S
    p2, ro2 = _with_ro(bname="AUR")
    p2.ro = dataclasses.replace(ro2, wing_area_m2=1.5, wing_aspect_ratio=0.0)
    ax2 = _ax(); draw_booster(ax2, p2)
    def _wing_extent(ax_, D):
        from matplotlib.patches import Polygon
        ws = [q for q in ax_.patches if isinstance(q, Polygon)
              and q.get_path().vertices[:, 1].min() <= 1e-9
              and abs(q.get_path().vertices[:, 0].max()
                      - q.get_path().vertices[:, 0].min() - D) > 1e-6]
        return max(q.get_path().vertices[:, 0].max()
                   - q.get_path().vertices[:, 0].min() for q in ws)
    assert _wing_extent(ax, ro.diameter_m) == pytest.approx(
        _wing_extent(ax2, ro2.diameter_m))


def test_planform_wings_draw_the_entered_dimensions():
    """With root chord + exposed span entered, the wings draw faithfully:
    the panel rises exactly the root chord and extends exactly the exposed
    span outboard of the body flank, with the label NOT flagged schematic."""
    import dataclasses
    from matplotlib.patches import Polygon
    rc, ss = 0.6, 0.15
    p, ro = _with_ro(bname="AUR")            # finless: only the RO's wings at y=0
    p.ro = dataclasses.replace(ro, wing_area_m2=0.2, wing_aspect_ratio=0.0,
                               wing_root_chord_m=rc, wing_span_exposed_m=ss,
                               wing_sweep_deg=65.0)
    ax = _ax(); draw_booster(ax, p)
    ws = [q for q in ax.patches if isinstance(q, Polygon)
          and q.get_path().vertices[:, 1].min() <= 1e-9
          and abs(q.get_path().vertices[:, 0].max()
                  - q.get_path().vertices[:, 0].min() - ro.diameter_m) > 1e-6]
    assert len(ws) == 2
    for q in ws:
        v = q.get_path().vertices
        assert v[:, 1].max() == pytest.approx(rc)          # rises the root chord
    # outboard extent = flank radius at base + exposed span
    right_wing = max(ws, key=lambda q: q.get_path().vertices[:, 0].max())
    cone = [q for q in ax.patches if isinstance(q, Polygon)
            and abs(q.get_path().vertices[:, 0].max()
                    - q.get_path().vertices[:, 0].min() - ro.diameter_m) < 1e-6
            and q.get_path().vertices[:, 1].min() <= 1e-9
            and q.get_path().vertices[:, 0].min() > 0][0]
    cone_right = cone.get_path().vertices[:, 0].max()
    assert right_wing.get_path().vertices[:, 0].max() == \
        pytest.approx(cone_right + ss)
    wing_txt = [t.get_text() for t in ax.texts if "wings" in t.get_text()]
    assert wing_txt and "(schematic" not in wing_txt[0]


def test_reentry_object_wings_sit_on_the_ro_not_the_vehicle_centreline():
    """Regression: fin_polygon returns x centred on 0 (it was built for the
    booster stack, always at x=0), so drawing the RO's wings with its raw
    output — without shifting by the RO's own x0, off in the corner — put
    the wing patches at x≈0, y≈0: the MAIN VEHICLE's base, not the RO.  The
    wings must sit within one RO-body-width of the RO cone, nowhere near the
    vehicle centreline the RO is offset well away from."""
    import dataclasses
    from matplotlib.patches import Polygon
    p, ro = _with_ro(bname="AUR")            # finless, no strap-ons at the base
    p.ro = dataclasses.replace(ro, wing_area_m2=0.2, wing_aspect_ratio=0.0)
    ax = _ax()
    draw_booster(ax, p)

    ro_cone_x = None
    for patch in ax.patches:
        if isinstance(patch, Polygon):
            v = patch.get_path().vertices
            w = v[:, 0].max() - v[:, 0].min()
            if abs(w - ro.diameter_m) < 1e-6 and v[:, 1].min() <= 1e-9 \
                    and v[:, 0].min() > 0:
                ro_cone_x = 0.5 * (v[:, 0].min() + v[:, 0].max())
    assert ro_cone_x is not None and ro_cone_x > 1.0, \
        "test fixture assumption failed: RO should be well off-centre"

    # the two wing patches: small quads at y≈0 (RO base), not the RO cone itself
    wing_patches = [p_ for p_ in ax.patches
                   if isinstance(p_, Polygon)
                   and p_.get_path().vertices[:, 1].min() <= 1e-9
                   and abs(p_.get_path().vertices[:, 0].max()
                           - p_.get_path().vertices[:, 0].min()
                           - ro.diameter_m) > 1e-6]
    assert len(wing_patches) == 2
    for wp in wing_patches:
        wx = wp.get_path().vertices[:, 0]
        # must sit near the RO, not straddle x=0 (the vehicle centreline)
        assert wx.min() > 0.0, \
            f"wing patch at x={wx} crosses the vehicle centreline"
        assert abs(0.5 * (wx.min() + wx.max()) - ro_cone_x) < 2.0 * ro.diameter_m


def test_reentry_object_label_sits_to_the_right():
    """The reentry-object caption is placed to the right of its body (extends
    rightward), not over it."""
    p, _ = _with_ro()
    ax = _ax(); draw_booster(ax, p)
    ro_txt = [t for t in ax.texts if t.get_text().startswith("reentry object")]
    assert ro_txt and ro_txt[0].get_ha() == "left"


def test_no_reentry_object_when_none_composed():
    """With no reentry object (ro is None) the drawing simply omits it and
    never crashes."""
    p = _load("Strypi_VIII_R")
    p.ro = None
    info = draw_booster(_ax(), p)
    assert info["total_height_m"] > 0          # renders fine, RO just omitted


# ── an uncovered separating object is drawn beside the stack, not on it ─────
def _stack_len(p):
    return sum(float(s.length_m) + (float(s.interstage_length_m or 0.0)
                                    if s.has_interstage else 0.0)
               for s in stage_chain(p))


def _adapter_widths(ax, y0, length):
    """(bottom, top) width of the body patch spanning y0 → y0+length."""
    from matplotlib.patches import Polygon, Rectangle
    for patch in ax.patches:
        if not isinstance(patch, (Polygon, Rectangle)):
            continue
        v = patch.get_patch_transform().transform(patch.get_path().vertices) \
            if isinstance(patch, Rectangle) else patch.get_path().vertices
        if abs(v[:, 1].min() - y0) < 1e-9 \
                and abs(v[:, 1].max() - (y0 + length)) < 1e-9 \
                and abs(v[:, 0].max() + v[:, 0].min()) < 1e-6:   # centreline
            lo = v[abs(v[:, 1] - y0) < 1e-9, 0]
            hi = v[abs(v[:, 1] - (y0 + length)) < 1e-9, 0]
            return lo.max() - lo.min(), hi.max() - hi.min()
    return None


def test_uncovered_separating_object_is_not_also_stacked_as_a_nose():
    """No fairing and a separating object: the object IS the front end and is
    drawn to scale beside the stack, so the stack ends at its top stage — no
    'payload / RV' nose on top (whose length, stored or the 1.6×⌀ fallback,
    the physics never flies) and no containment verdict against it.  The
    vehicle's length is still reported: the stack plus the object."""
    p, ro = _with_ro()
    assert not p.body_reenters
    assert all(not (s.shroud_length_m or 0) for s in stage_chain(p))
    ax = _ax()
    info = draw_booster(ax, p)
    assert info["total_height_m"] == pytest.approx(_stack_len(p))
    assert info["front_object_length_m"] == pytest.approx(ro.length_m)
    assert info["overall_length_m"] == pytest.approx(_stack_len(p)
                                                     + ro.length_m)
    fe = info["front_end"]
    assert fe["kind"] == "separate_object"
    assert fe["body_diameter_m"] == pytest.approx(ro.diameter_m)
    assert not any("payload / RV" in t.get_text() for t in ax.texts)
    assert not any(f.startswith("nose") for f in info["flags"])
    assert not any("⚠" in t.get_text() for t in ax.texts)
    # the object itself is still drawn, beside the stack
    assert any(t.get_text().startswith("reentry object") for t in ax.texts)


def test_the_stacked_nose_stays_when_nothing_else_draws_the_front_end():
    """Without an object, or with one inside a fairing, the stack still
    carries its front end, and the vehicle length is the stack as drawn."""
    bare = _load("Strypi_VIII_R")
    ax = _ax()
    info = draw_booster(ax, bare)
    assert info["total_height_m"] > _stack_len(bare)          # nose on top
    assert any("payload / RV" in t.get_text() for t in ax.texts)
    assert info["front_object_length_m"] == 0.0
    assert info["overall_length_m"] == info["total_height_m"]

    p, _ = _with_ro()
    top = stage_chain(p)[-1]
    top.shroud_length_m = 2.0; top.shroud_diameter_m = 0.7
    top.shroud_nose_length_m = 0.9; top.shroud_nose_shape = "cone"
    info = draw_booster(_ax(), p)
    assert info["front_end"]["kind"] == "fairing"
    assert info["total_height_m"] == pytest.approx(_stack_len(p) + 2.0)
    assert info["overall_length_m"] == info["total_height_m"]


def test_interstage_on_top_tapers_to_the_uncovered_object():
    """An interstage declared on the LAST stage is the adapter to the object
    riding on it, so its diameters are derived the same way as between
    stages — this stage's top → the object's base — instead of holding the
    stage ⌀ as a straight band.  Narrower object: a taper."""
    import booster_models as mm
    from booster_models import ro_from_dict
    p = _load("Strypi_VIII_R")
    ro = ro_from_dict(dict(json.load(open("ro_library/C-HGB.ro.json")),
                           diameter_m=0.4))
    p = mm.compose_loadout(p, ro, 1)
    p.ro = ro
    top = stage_chain(p)[-1]
    top.has_interstage = True; top.interstage_length_m = 0.5
    ax = _ax()
    info = draw_booster(ax, p)
    y0 = _stack_len(p) - 0.5                     # adapter base = stage top
    assert _adapter_widths(ax, y0, 0.5) == pytest.approx((top.diameter_m, 0.4))
    assert info["total_height_m"] == pytest.approx(_stack_len(p))
    # with nothing riding on it the adapter holds the stage ⌀, as before
    p.ro = None
    ax = _ax(); draw_booster(ax, p)
    assert _adapter_widths(ax, y0, 0.5) == pytest.approx(
        (top.diameter_m, top.diameter_m))


def test_equal_aspect_is_enforced():
    """Proportion honesty is the whole point: the axes must be metre-true in
    both directions, not stretched to fit the panel — including after the
    scale-figure imshow, which must not flip the axes to aspect='auto'."""
    ax = _ax()
    draw_booster(ax, _load("AUR"))
    assert ax.get_aspect() == 1.0


# ── the Thrusty scale reference (~1.8 m figure + 5 m bar) ────────────────────
def test_scale_figure_stands_at_the_human_height():
    """The mascot silhouette is placed at _SCALE_FIGURE_M (~1.8 m, human
    height), feet on y=0, so it reads as a person beside the stack — while the
    quantitative reference is carried by the separate 5 m bar."""
    import booster_schematic as bs
    if bs._scale_image() is None:
        pytest.skip("scale asset not present in this checkout")
    ax = _ax()
    draw_booster(ax, _load("Scud-B_-R-17-"))
    imgs = ax.get_images()
    assert len(imgs) == 1
    x0, x1, y0, y1 = imgs[0].get_extent()
    assert (y0, y1) == (0.0, bs._SCALE_FIGURE_M)          # feet at 0, head at 1.8 m
    assert bs._SCALE_FIGURE_M == 1.8
    # width preserves the art's aspect ratio (never stretched)
    h_px, w_px = imgs[0].get_array().shape[:2]
    assert (x1 - x0) == pytest.approx(bs._SCALE_FIGURE_M * w_px / h_px)


def test_reference_bar_is_the_five_metre_quantitative_scale():
    """The dimension bar spans 0→5 m and is labelled '5 m' — the numeric
    reference, distinct from the figure's felt human height."""
    import booster_schematic as bs
    ax = _ax()
    draw_booster(ax, _load("Scud-B_-R-17-"))
    assert bs._SCALE_BAR_M == 5.0
    assert any(t.get_text() == "5 m" for t in ax.texts)
    # a vertical line 0→5 m exists (the bar)
    spans = [tuple(round(v, 3) for v in ln.get_ydata())
             for ln in ax.lines if len(ln.get_ydata()) == 2]
    assert (0.0, 5.0) in spans


def test_scale_reference_falls_back_without_the_asset(monkeypatch):
    """A stripped checkout (no assets/) must still render — the reference
    degrades to the 5 m bar alone, never a crash."""
    import booster_schematic as bs
    monkeypatch.setattr(bs, "_scale_img_cache", None)     # simulate missing asset
    ax = _ax()
    info = draw_booster(ax, _load("Scud-B_-R-17-"))
    assert info["total_height_m"] > 0
    assert ax.get_images() == []                          # no silhouette drawn
    assert ax.get_aspect() == 1.0
    assert any(t.get_text() == "5 m" for t in ax.texts)   # bar still labelled
