"""Image dimensioning tool — GUI wiring (Phase A).

The measurement math is covered by test_image_measure.py; these tests cover
the editor-side wiring the pure core can't reach: the dialog builds, the
"Measure from image…" button exists, and the apply path writes accepted
values into the editor fields and stamps the notes (the tool's only durable
outputs).  The canvas click plumbing needs a real event loop and is verified
by hand, not here.

Skips cleanly where tkinter / a display is unavailable.
"""

import json

import pytest

pytest.importorskip("tkinter", reason="no Tk in this interpreter")

import matplotlib
matplotlib.use("Agg")
import tkinter as tk

import thrusty
import image_measure as im
from booster_models import ro_from_dict


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    r.withdraw()
    yield r
    r.destroy()


def _editor(root):
    ro = ro_from_dict(json.load(open("ro_library/C-HGB.ro.json")))
    dlg = thrusty.ROEditorDialog(root, ro=ro)
    dlg.withdraw()
    return dlg


def _all(w, acc=None):
    acc = [] if acc is None else acc
    for c in w.winfo_children():
        acc.append(c); _all(c, acc)
    return acc


def test_measure_button_exists(root):
    dlg = _editor(root)
    labels = [b.cget("text") for b in _all(dlg)
              if isinstance(b, tk.ttk.Button)]
    assert any("Measure from image" in t for t in labels)


def test_apply_writes_fields_and_stamps_notes(root):
    """The tool's durable outputs: accepted values land in the editor fields,
    and a dimensional-draft stamp is appended to notes.  Refused measurements
    (below the resolution floor) never reach apply, so nothing about them is
    written."""
    pytest.importorskip("PIL")
    dlg = _editor(root)
    s = im.Scale((0, 0), (1000, 0), 10.0, anchor_note="claimed L=10 m")
    length = im.Measurement("_len_var", *s.measure((0, 0), (200, 0)), scale=s,
                            convention="ro_length")          # 2.0 m
    diam = im.Measurement("_dia_var", *s.measure((0, 0), (58, 0)), scale=s,
                          convention="ro_diameter")          # 0.58 m
    accepted = {"_len_var": length.value_m, "_dia_var": diam.value_m}
    dlg._apply_image_measurements(accepted, [length, diam], s)

    assert float(dlg._len_var.get()) == pytest.approx(2.0)
    assert float(dlg._dia_var.get()) == pytest.approx(0.58)
    notes = dlg._notes_text.get("1.0", "end-1c")
    assert "dimensional draft from image" in notes
    assert "claimed L=10 m" in notes and "1 px = 1 cm" in notes


def test_apply_corrects_nose_radius_for_cone_tangency(root):
    """The blunt-tip click sees the sphere-cone TANGENCY circle (width
    2·R_N·cos θ), not the full sphere — so on a cone, Apply divides the
    half-width by cos(θ), θ derived from the same session's length/⌀.
    Curved profiles keep the plain hemisphere convention (their blend slope
    is not the L-⌀ cone angle), and a biconic uses the FORE cone's θ."""
    import math
    dlg = _editor(root)
    dlg._shape_var.set(dlg._shape_label_for("cone", "axisymmetric"))
    dlg._update_body_form_state()
    dlg._apply_image_measurements(
        {"_len_var": 3.0, "_dia_var": 1.0, "_nose_var": 0.05}, [], None)
    th = math.atan2(0.5, 3.0)
    assert float(dlg._nose_var.get()) \
        == pytest.approx(0.05 / math.cos(th), rel=1e-3)
    # a curved profile: half-width stored untouched
    dlg._shape_var.set(dlg._shape_label_for("tangent_ogive", "axisymmetric"))
    dlg._update_body_form_state()
    dlg._apply_image_measurements(
        {"_len_var": 3.0, "_dia_var": 1.0, "_nose_var": 0.05}, [], None)
    assert float(dlg._nose_var.get()) == pytest.approx(0.05)
    # biconic: the fore cone carries the tip → θ from fore-length/break-⌀
    dlg._shape_var.set(dlg._BICONIC_LABEL)
    dlg._update_body_form_state()
    dlg._apply_image_measurements(
        {"_fore_len_var": 1.0, "_break_dia_var": 0.8, "_nose_var": 0.05},
        [], None)
    th_fore = math.atan2(0.4, 1.0)
    assert float(dlg._nose_var.get()) \
        == pytest.approx(0.05 / math.cos(th_fore), rel=1e-3)


def test_apply_maps_body_span_for_wedge(root):
    dlg = _editor(root)
    dlg._shape_var.set(dlg._BODY_FORM_LABELS["wedge"])
    dlg._update_body_form_state()
    s = im.Scale((0, 0), (1000, 0), 10.0)
    span = im.Measurement("_body_span_var", *s.measure((0, 0), (90, 0)),
                          scale=s, view="plan", convention="wedge_span")  # 0.9 m
    dlg._apply_image_measurements({"_body_span_var": span.value_m}, [span], s)
    assert float(dlg._body_span_var.get()) == pytest.approx(0.9)


def test_apply_maps_biconic_and_wing_planform(root):
    """The RO tool covers the editor's FULL dimensional field set: biconic
    break geometry and the wing planform land in their fields, and the wing
    S/AR derivation fires from the written planform (measure the planform,
    derive the area — never the other way)."""
    dlg = _editor(root)
    dlg._glider_var.set(True)
    dlg._biconic_var.set(True); dlg._update_biconic_state()
    acc = {"_fore_len_var": 1.1, "_break_dia_var": 0.3,
           "_wing_root_var": 0.7, "_wing_span_var": 0.45}
    dlg._apply_image_measurements(acc, [], None)
    assert float(dlg._fore_len_var.get()) == pytest.approx(1.1)
    assert float(dlg._break_dia_var.get()) == pytest.approx(0.3)
    assert float(dlg._wing_root_var.get()) == pytest.approx(0.7)
    assert float(dlg._wing_span_var.get()) == pytest.approx(0.45)
    assert float(dlg._wing_area_var.get()) > 0.0     # S derived from planform


def test_wing_prompts_offered_without_maneuvering_and_apply_enables_it(root):
    """The wings are visible in the image whether or not Maneuvering is
    ticked yet: the checklist offers the wing planform (and sweep angle)
    regardless, and APPLYING wing geometry enables the Maneuvering section —
    the same measured-it-so-show-it rule as the booster's fairing/fins.
    Without it the measured values would sit in disabled fields and be
    silently dropped on save."""
    dlg = _editor(root)
    dlg._glider_var.set(False); dlg._update_glider_state()
    fields = [p["field"] for p in im.ro_prompts("axisymmetric")]
    assert "_wing_root_var" in fields and "_wing_span_var" in fields
    assert "_wing_tip_derive" in fields               # sweep derives from tip
    dlg._apply_image_measurements(
        {"_wing_root_var": 0.7, "_wing_span_var": 0.45}, [], None)
    assert dlg._glider_var.get() is True              # auto-enabled
    assert str(dlg._wing_root_ent.cget("state")) == "normal"
    assert float(dlg._wing_area_var.get()) > 0.0      # S derived, visible
    ro = dlg._build_ro()
    assert ro.wing_root_chord_m == pytest.approx(0.7)  # stored, not dropped


def test_wing_sweep_derives_from_planform_on_apply(root):
    """The end of the sweep saga: applying root + span (+ optional tip) writes
    the DERIVED sweep, no angle measured.  Delta (no tip): atan(root/span) —
    the 77° that finally draws a triangle.  Tip > 0: a trapezoid, lower Λ."""
    import math
    dlg = _editor(root)
    dlg._apply_image_measurements(
        {"_wing_root_var": 0.5315, "_wing_span_var": 0.1204}, [], None)
    delta = float(dlg._wing_sweep_var.get())
    assert delta == pytest.approx(math.degrees(math.atan2(0.5315, 0.1204)),
                                  abs=0.05)
    assert delta == pytest.approx(77.2, abs=0.3)
    # and the schematic tip height collapses to 0 → a triangle prints
    import booster_models as bm
    S, AR, src = bm.wing_geometry(dlg._build_ro())
    assert src == "planform" and S > 0
    # a measured tip chord makes it a trapezoid (smaller sweep)
    dlg._apply_image_measurements(
        {"_wing_root_var": 0.5315, "_wing_span_var": 0.1204,
         "_wing_tip_derive": 0.20}, [], None)
    assert float(dlg._wing_sweep_var.get()) < delta


def test_apply_with_nothing_accepted_is_a_noop(root):
    dlg = _editor(root)
    before_len = dlg._len_var.get()
    before_notes = dlg._notes_text.get("1.0", "end-1c")
    dlg._apply_image_measurements({}, [], None)
    assert dlg._len_var.get() == before_len
    assert dlg._notes_text.get("1.0", "end-1c") == before_notes


def test_booster_button_and_apply(root):
    """A2: the booster editor gets the same tool.  Its apply writes stage,
    fairing, one-fin and one-strap-on GEOMETRY into the existing fields while
    leaving the declared COUNTS untouched (measure-one-declare-count — the
    model replicates)."""
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    assert any("Measure from image" in b.cget("text")
               for b in _all(d) if isinstance(b, tk.ttk.Button))
    d._n_stages_var.set("2"); d._update_stage_frames()
    d._shroud_var.set(True); d._update_shroud_state()
    d._fins_var.set(True); d._update_fins_state(); d._fin_n_var.set("4")
    d._n_boosters_var.set("4")
    s = im.Scale((0, 0), (1000, 0), 10.0, anchor_note="L=10 m")
    acc = {"stage1_len": 9.0, "stage2_dia": 0.88, "fairing_len": 2.6,
           "fin_span": 0.5, "strapon_dia": 1.2}
    d._apply_image_measurements(acc, [], s)
    assert float(d._stage_frames[0]._length.get()) == pytest.approx(9.0)
    assert float(d._stage_frames[1]._dia.get()) == pytest.approx(0.88)
    assert float(d._shroud_length_var.get()) == pytest.approx(2.6)
    assert float(d._fin_span_var.get()) == pytest.approx(0.5)
    assert float(d._b_diam_var.get()) == pytest.approx(1.2)
    assert d._fin_n_var.get() == "4"          # declared count untouched
    d.destroy()


def test_booster_apply_converts_nozzle_diameter_to_per_nozzle_area(root):
    """UNITS boundary: the tool measured nozzle-exit DIAMETERS (metres),
    one per stage; the editor stores per-nozzle AREA (m²) = π(d/2)² on
    EACH stage's frame, and each declared nozzle count multiplies it into
    that stage's total via the existing trace — measure one, declare
    count.  The delta preview speaks diameters, so _current_image_values
    reports the diameter each stage's stored area implies."""
    import math
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    d._n_stages_var.set("2"); d._update_stage_frames()
    f1, f2 = d._stage_frames[0], d._stage_frames[1]
    f1._n_nozzles.set("4")
    dia_before = f1._dia.get()
    d._apply_image_measurements(
        {"stage1_nozzle_dia": 0.8, "stage2_nozzle_dia": 0.5}, [], None)
    each1, each2 = math.pi * 0.4 ** 2, math.pi * 0.25 ** 2
    assert float(f1._nozzle_each.get()) == pytest.approx(each1, rel=1e-3)
    assert float(f1._nozzle_area.get()) == pytest.approx(4 * each1, rel=1e-3)
    assert f1._n_nozzles.get() == "4"            # declared count untouched
    assert float(f2._nozzle_each.get()) == pytest.approx(each2, rel=1e-3)
    assert float(f2._nozzle_area.get()) == pytest.approx(each2, rel=1e-3)
    # stage diameters untouched (the nozzle field must not alias _dia)
    assert f1._dia.get() == dia_before
    cur = d._current_image_values(["stage1_nozzle_dia", "stage2_nozzle_dia"])
    assert cur["stage1_nozzle_dia"] == pytest.approx(0.8, rel=1e-3)
    assert cur["stage2_nozzle_dia"] == pytest.approx(0.5, rel=1e-3)
    d.destroy()


def test_booster_apply_ignores_the_check_only_total(root):
    """The overall-length cross-check measurement exists only to feed the
    closure warning: apply must not write it anywhere (there is no editor
    field for a derived total)."""
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    d._n_stages_var.set("1"); d._update_stage_frames()
    before = d._stage_frames[0]._length.get()
    d._apply_image_measurements({im.OVERALL_LEN_CHECK_FIELD: 10.2}, [], None)
    assert d._stage_frames[0]._length.get() == before
    d.destroy()


def test_clocking_control_present_for_fins(root):
    """R1: when the declared topology has fins, the shared dialog carries the
    clocking selector (the cos45 correction the pure core already applies) with
    the do-nothing option first.  The RO dialog, whose prompts have no span a
    ×-roll foreshortens, must not offer it."""
    pytest.importorskip("PIL")
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    d._fins_var.set(True); d._update_fins_state(); d._fin_n_var.set("4")
    opened = []
    orig = tk.Toplevel
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        d._measure_from_image()
    finally:
        tk.Toplevel = orig
    combos = [w for w in _all(opened[-1]) if isinstance(w, tk.ttk.Combobox)]
    clock = [c for c in combos
             if any("×-rolled" in v for v in c.cget("values"))]
    assert clock, "fin topology must expose the clocking selector"
    assert im.CLOCKING_OPTIONS[0][0] in clock[0].cget("values")
    opened[-1].destroy(); d.destroy()

    # WEDGE editor: its body IS the lifting surface — no wing prompts, and
    # its plan-view span is a true span (no foreshortening), so no
    # clocking-sensitive prompt exists and the selector is not built at all.
    dlg = _editor(root)
    dlg._shape_var.set(dlg._BODY_FORM_LABELS["wedge"])
    dlg._update_body_form_state()
    opened2 = []
    tk.Toplevel = lambda *a, **k: (lambda w: (opened2.append(w), w)[1])(orig(*a, **k))
    try:
        dlg._measure_from_image()
    finally:
        tk.Toplevel = orig
    ro_combos = [w for w in _all(opened2[-1]) if isinstance(w, tk.ttk.Combobox)]
    assert not any("×-rolled" in v for c in ro_combos for v in c.cget("values"))
    opened2[-1].destroy()


def _open_measure_dialog(dlg):
    opened = []
    orig = tk.Toplevel
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        dlg._measure_from_image()
    finally:
        tk.Toplevel = orig
    return opened[-1]


def test_paste_and_new_image_resets_scale(root, tmp_path, monkeypatch):
    """Paste accepts both a raw clipboard image and a copied-file list, and
    loading ANY new image resets the scale — metres-per-pixel belongs to the
    image it was anchored on; carrying it to a different picture would be
    silently wrong."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    side = d._im_views["side"]
    # ⌘V of a raw clipboard image (a screenshot)
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard",
                        lambda: Image.new("RGB", (300, 200), "white"))
    d._im_paste()
    assert side["img"] is not None
    # anchor a scale, then load a NEW image → scale must clear
    side["scale"] = im.Scale((0, 0), (100, 0), 1.0)
    p = tmp_path / "v.png"
    Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    assert side["scale"] is None
    assert side["img"].size == (400, 150)
    # ⌘V of a copied FILE (Finder copy) → the file loads
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: [str(p)])
    side["img"] = None
    d._im_paste()
    assert side["img"] is not None
    d.destroy()


def test_paste_button_and_opportunistic_dnd(root):
    """The Paste button is always there; drag-and-drop is enabled exactly when
    the OPTIONAL tkinterdnd2 package is importable (no hard dependency)."""
    pytest.importorskip("PIL")
    d = _open_measure_dialog(_editor(root))
    btxt = [b.cget("text") for b in _all(d) if isinstance(b, tk.ttk.Button)]
    assert any("Paste image" in t for t in btxt)
    try:
        import tkinterdnd2                     # noqa: F401
        assert d._im_dnd is True
    except ImportError:
        assert d._im_dnd is False
    d.destroy()


def test_type_value_needs_no_image_or_scale(root, monkeypatch):
    """The checklist never forces a click: a known dimension can be TYPED for
    the selected prompt with no image loaded and no scale set (only Measure
    needs those).  The value lands in accepted, recorded as hand-entered so
    the stamp cannot claim it was measured."""
    pytest.importorskip("PIL")
    d = _open_measure_dialog(_editor(root))
    import tkinter.simpledialog as sd
    monkeypatch.setattr(sd, "askfloat", lambda *a, **k: 0.58)
    d._im_type_value()
    st = d._im_state
    assert d._im_views["side"]["img"] is None             # truly ungated:
    assert d._im_views["side"]["scale"] is None           # no image, no scale
    assert list(st["accepted"].values()) == [pytest.approx(0.58)]
    assert getattr(st["measurements"][0], "hand_entered", False) is True
    d.destroy()


def _wedge_editor(root):
    dlg = _editor(root)
    dlg._shape_var.set(dlg._BODY_FORM_LABELS["wedge"])
    dlg._update_body_form_state()
    return dlg


def test_multiview_gating_and_per_view_scales(root, tmp_path):
    """Phase B: the wedge checklist needs side + plan.  The dialog gets a view
    selector; each view carries its OWN image and scale; a plan-view prompt is
    HARD-GATED on the plan view being loaded and scaled (the old label-only
    warning let a span be clicked off a side elevation — pure garbage, the
    span runs into the page); and the side view's scale survives plan loads."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_wedge_editor(root))
    assert set(d._im_views) == {"side", "plan"}

    # side view: load + scale
    ps = tmp_path / "side.png"; Image.new("RGB", (400, 100), "gray").save(ps)
    d._im_load_path(str(ps))
    d._im_views["side"]["scale"] = im.Scale((0, 0), (400, 0), 8.0)

    # select the plan-only span prompt and try to measure with NO plan image:
    # must refuse to arm
    span_label = next(lab for lab, p in
                      [(f"{p['field']}  —  {p['label']}", p)
                       for p in im.ro_prompts("wedge")]
                      if "_body_span_var" in lab)
    d._im_prompt_var.set(span_label)
    d._im_begin_measure()
    assert d._im_state["mode"] == "idle"          # refused: no plan image
    assert d._im_state["cur"] == "plan"           # but auto-switched view

    # load the plan image: side's scale must be untouched, plan's is its own
    pp = tmp_path / "plan.png"; Image.new("RGB", (500, 300), "gray").save(pp)
    d._im_load_path(str(pp))                       # loads into CURRENT (plan)
    assert d._im_views["plan"]["img"].size == (500, 300)
    assert d._im_views["side"]["scale"] is not None   # untouched
    d._im_begin_measure()
    assert d._im_state["mode"] == "idle"          # still refused: no plan scale
    d._im_views["plan"]["scale"] = im.Scale((0, 0), (250, 0), 8.0)
    d._im_begin_measure()
    assert d._im_state["mode"] == "measure"       # armed at last
    d.destroy()


def test_single_view_dialog_has_no_view_selector(root):
    pytest.importorskip("PIL")
    d = _open_measure_dialog(_editor(root))       # axisymmetric: side only
    assert set(d._im_views) == {"side"}
    assert not any(isinstance(w, tk.ttk.Radiobutton) for w in _all(d))
    d.destroy()


def test_zoom_never_touches_measurements(root, tmp_path):
    """Zoom is display-only: clicks are stored in ORIGINAL-image pixels, so a
    measurement's value and quantum are identical at any zoom."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    side = d._im_views["side"]
    side["scale"] = im.Scale((0, 0), (400, 0), 10.0)
    d._im_state["clicks"] = [(0.0, 0.0), (200.0, 0.0)]
    before = list(d._im_state["clicks"])
    z0 = side["zoom"]
    d._im_zoom_at(2.0)
    assert side["zoom"] == pytest.approx(z0 * 2.0)
    assert d._im_state["clicks"] == before        # image-px clicks unmoved
    assert side["scale"].m_per_px == pytest.approx(0.025)   # 10 m / 400 px
    d._im_fit()
    assert side["zoom"] == pytest.approx(z0)
    d.destroy()


def test_zoom_buttons_and_keys_are_device_independent(root, tmp_path):
    """A Mac trackpad has no wheel and its pinch never reaches Tk, so zoom
    must not depend on wheel events: the +/− buttons and the +/−/0 keys are
    the guaranteed path (they call the same _zoom_at/_fit as the wheel)."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    side = d._im_views["side"]
    z0 = side["zoom"]
    btns = {b.cget("text"): b for b in _all(d) if isinstance(b, tk.ttk.Button)}
    assert "+" in btns and "−" in btns and "Fit" in btns
    btns["+"].invoke()
    assert side["zoom"] == pytest.approx(z0 * 1.25)
    btns["−"].invoke()
    assert side["zoom"] == pytest.approx(z0)
    d._im_key_zoom(1.25)
    d._im_key_zoom(1.25)
    assert side["zoom"] == pytest.approx(z0 * 1.25 ** 2)
    d._im_key_zoom(None)                              # 0 = fit
    assert side["zoom"] == pytest.approx(z0)
    d.destroy()


def test_wheel_routing_pans_plain_and_zooms_modified(root, tmp_path):
    """Mac-convention wheel routing: a plain scroll (trackpad two-finger
    drag) PANS and never changes zoom; only ⌘/Ctrl-scroll zooms.  Momentum
    events with delta 0 — which the old handler read as zoom-OUT — are
    dropped, and per-event steps are normalized (Windows ±120/notch vs Mac
    ±1-ish) and clamped so a fling cannot slam the zoom limit."""
    pytest.importorskip("PIL")
    import types as _t
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    side = d._im_views["side"]
    # step normalization: 0 dropped, ±120 = 1 notch, small Mac deltas as-is,
    # everything clamped to ±2 per event
    assert d._im_wheel_steps(0) == 0.0
    assert d._im_wheel_steps(120) == pytest.approx(1.0)
    assert d._im_wheel_steps(-120) == pytest.approx(-1.0)
    assert d._im_wheel_steps(1) == pytest.approx(1.0)
    assert d._im_wheel_steps(600) == pytest.approx(2.0)     # clamped
    assert d._im_wheel_steps(-7) == pytest.approx(-2.0)     # clamped
    z0 = side["zoom"]
    d._im_wheel_pan(_t.SimpleNamespace(delta=3, x=10, y=10))
    assert side["zoom"] == pytest.approx(z0)          # pan never zooms
    d._im_wheel_zoom(_t.SimpleNamespace(delta=0, x=10, y=10))
    assert side["zoom"] == pytest.approx(z0)          # momentum tail dropped
    d._im_wheel_zoom(_t.SimpleNamespace(delta=120, x=10, y=10))
    assert side["zoom"] == pytest.approx(z0 * 1.15)
    d.destroy()


def test_arrow_keys_pan_and_toplevel_wheel_fallback(root, tmp_path):
    """Pan must not depend on wheel delivery either: arrow keys pan through
    the same _pan_by as the wheel (guaranteed on any device), and a toplevel
    wheel fallback re-routes events that Aqua delivered to the FOCUSED
    widget instead of the canvas — but only when the pointer is actually
    over the canvas (hit-test), so scrolling elsewhere in the dialog never
    drags the image around."""
    pytest.importorskip("PIL")
    import types as _t
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    d._im_zoom_at(4.0)                    # scrollregion now exceeds the window
    cv = d._im_canvas
    x0, y0 = cv.xview()[0], cv.yview()[0]
    d._im_key_pan(40, 0)
    assert cv.xview()[0] > x0             # → panned right
    d._im_key_pan(0, 40)
    assert cv.yview()[0] > y0             # ↓ panned down
    d._im_key_pan(-40, -40)
    assert cv.xview()[0] == pytest.approx(x0)
    assert cv.yview()[0] == pytest.approx(y0)
    # plain arrows can be eaten by whichever widget has focus (Tk traversal
    # / combobox bindings), so the modified spellings are bound explicitly —
    # ⌘-arrows on a Mac, Ctrl-arrows elsewhere — as the always-works path
    for arrow in ("Left", "Right", "Up", "Down"):
        assert d.bind(f"<Key-{arrow}>")
        assert d.bind(f"<Control-Key-{arrow}>")
    # fallback hit-test: pointer not over the canvas (here: nowhere — the
    # dialog is withdrawn) → the event is ignored, nothing moves or zooms
    z0 = d._im_views["side"]["zoom"]
    ev = _t.SimpleNamespace(delta=120, x=5, y=5, x_root=0, y_root=0)
    assert d._im_route_wheel(ev, "zoom") is None
    assert d._im_route_wheel(ev, "pan") is None
    assert d._im_views["side"]["zoom"] == pytest.approx(z0)
    assert cv.xview()[0] == pytest.approx(x0)
    d.destroy()


def test_accept_records_overlay_annotation(root, tmp_path):
    """The overlay audits what was clicked: accepting a measurement stores its
    clicked segment (view-tagged, original-image px) for drawing."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    d._im_views["side"]["scale"] = im.Scale((0, 0), (400, 0), 10.0)
    st = d._im_state
    st["prompt"] = im.ro_prompts("axisymmetric")[0]        # _len_var, side
    st["clicks"] = [(50.0, 40.0), (250.0, 40.0)]
    st["_finish_measure"]()                                 # proposes 5.0 m
    acc = [b for b in _all(d) if isinstance(b, tk.ttk.Button)
           and b.cget("text") == "Accept"][0]
    acc.invoke()
    assert st["accepted"]["_len_var"] == pytest.approx(5.0)
    view, p1, p2, label, vtx = st["annotations"]["_len_var"]
    assert view == "side" and p1 == (50.0, 40.0) and p2 == (250.0, 40.0)
    assert vtx is None                                    # linear: no vertex
    assert "5" in label
    d.destroy()


def test_booster_provenance_stamps_notes_and_round_trips(root):
    """Parity with the RO editor: the booster now has a Notes box — the
    provenance stamp appends there on Apply, _collect stores it on
    BoosterParams.notes, and booster_to_dict/from_dict round-trip it (the
    model fields already existed; only the GUI never exposed them)."""
    pytest.importorskip("PIL")
    from booster_models import booster_to_dict, booster_from_dict
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    s = im.Scale((0, 0), (1000, 0), 10.0, anchor_note="claimed L=10 m")
    m = im.Measurement("stage1_len", *s.measure((0, 0), (200, 0)), scale=s,
                       convention="stage_length")
    d._apply_image_measurements({"stage1_len": m.value_m}, [m], s)
    notes = d._notes_text.get("1.0", "end-1c")
    assert "dimensional draft from image" in notes
    assert "claimed L=10 m" in notes
    p = d._collect()
    assert "claimed L=10 m" in p.notes
    rt = booster_from_dict(booster_to_dict(p))
    assert rt.notes == p.notes
    d.destroy()


def test_typing_zero_tip_updates_the_diagram(root):
    """Field bug: typing 0 for the C-HGB's pointed wing tip never updated
    the diagram — the layout dims were frozen at dialog-open, and no
    redraw fired when the checklist had nowhere to advance.  Accepted
    values now merge into live dims and every record redraws."""
    pytest.importorskip("PIL")
    dlg = _editor(root)
    dlg._glider_var.set(True); dlg._update_glider_state()
    dlg._wing_root_var.set("0.6"); dlg._wing_span_var.set("0.3")
    dlg._wing_sweep_var.set("60")
    d = _open_measure_dialog(dlg)
    tipp = [q for q in im.ro_prompts("axisymmetric")
            if q["field"] == "_wing_tip_derive"][0]
    d._im_prompt_var.set(f"{tipp['field']}  —  {tipp['label']}")
    d._im_on_prompt()
    before = d._im_diag._photo
    from tkinter import simpledialog
    orig = simpledialog.askfloat
    simpledialog.askfloat = lambda *a, **k: 0.0
    try:
        d._im_type_value()
    finally:
        simpledialog.askfloat = orig
    assert d._im_state["accepted"]["_wing_tip_derive"] == 0.0
    assert d._im_diag._photo is not None
    assert d._im_diag._photo is not before          # the diagram DID update
    d.destroy(); dlg.destroy()


def test_redo_flow_hides_old_mark_and_flags_the_advance(root, tmp_path):
    """Field report: redoing a measurement 'didn't kill the older one'.
    Two traps, both closed: (a) after Accept the checklist auto-advances,
    so pressing Measure again would record under the NEXT field — the
    result line now says the selection moved and how to redo; (b) while
    re-measuring a recorded field, its old green overlay mark hides (the
    value survives until the new reading is Accepted), so fresh clicks
    can't be confused with the mark they replace — and a redo's Accept
    REPLACES the value, never duplicates it."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 150), "gray").save(p)
    d._im_load_path(str(p))
    d._im_views["side"]["scale"] = im.Scale((0, 0), (400, 0), 10.0)
    st = d._im_state
    st["prompt"] = im.ro_prompts("axisymmetric")[0]        # _len_var
    st["clicks"] = [(50.0, 40.0), (250.0, 40.0)]
    st["_finish_measure"]()                                # proposes 5.0 m
    acc = [b for b in _all(d) if isinstance(b, tk.ttk.Button)
           and b.cget("text") == "Accept"][0]
    acc.invoke()
    res = [w for w in _all(d) if isinstance(w, tk.ttk.Label)
           and "advanced" in str(w.cget("text"))]
    assert res                                             # trap (a) flagged
    assert "re-select _len_var" in str(res[0].cget("text"))
    # (b) re-select the measured field and start a redo: notice + hidden mark
    first = f"_len_var  —  {im.ro_prompts('axisymmetric')[0]['label']}"
    d._im_prompt_var.set(first); d._im_on_prompt()
    d._im_begin_measure()
    assert st["mode"] == "measure"
    notice = [w for w in _all(d) if isinstance(w, tk.ttk.Label)
              and "re-measuring _len_var" in str(w.cget("text"))]
    assert notice and "5" in str(notice[0].cget("text"))   # old value named
    c = d._im_canvas
    texts = [c.itemcget(i, "text") for i in c.find_all()
             if c.type(i) == "text"]
    assert not any("_len_var" in t for t in texts)         # old mark hidden
    # completing the redo REPLACES the value — one measurement, not two
    st["clicks"] = [(50.0, 80.0), (170.0, 80.0)]
    st["_finish_measure"]()                                # proposes 3.0 m
    acc.invoke()
    assert st["accepted"]["_len_var"] == pytest.approx(3.0)
    assert len([m for m in st["measurements"]
                if m.field == "_len_var"]) == 1
    texts = [c.itemcget(i, "text") for i in c.find_all()
             if c.type(i) == "text"]
    assert any("3" in t and "_len_var" in t for t in texts)  # new mark shown
    d.destroy()


def test_starting_a_measurement_clears_the_stale_reading(root, tmp_path):
    """Field bug: a completed-but-unaccepted angle left its value and armed
    Accept button in place, so a NEW measurement (still mid-clicks) showed —
    and could Accept — the STALE number.  Clicking Measure must retire the
    pending value and disarm Accept until a fresh reading completes."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    p = tmp_path / "v.png"; Image.new("RGB", (400, 200), "gray").save(p)
    d._im_load_path(str(p))
    st = d._im_state
    ang = [q for q in im.ro_angle_prompts("axisymmetric")
           if q["field"] == im.FLANK_UPPER_FIELD][0]
    # first measurement completes but is NOT accepted
    st["prompt"] = ang
    st["clicks"] = [(0.0, 0.0), (200.0, 0.0), (140.0, 140.0)]
    st["_finish_measure"]()
    assert st["_pending"] is not None
    acc = [b for b in _all(d) if isinstance(b, tk.ttk.Button)
           and b.cget("text") == "Accept"][0]
    assert str(acc.cget("state")) == "normal"
    # now start a fresh measurement of the SAME prompt via the Measure button
    d._im_prompt_var.set(f"{ang['field']}  —  {ang['label']}")
    [b for b in _all(d) if isinstance(b, tk.ttk.Button)
     and b.cget("text") == "Measure"][0].invoke()
    assert st["_pending"] is None                          # stale value gone
    assert str(acc.cget("state")) == "disabled"            # can't accept it
    assert im.FLANK_UPPER_FIELD not in st["accepted"]      # nothing recorded
    d.destroy()


def test_dialog_builds_without_error(root):
    """Smoke: the Toplevel and all its widgets construct (catches layout/closure
    errors the apply-path test skips).  Pillow present → real dialog."""
    pytest.importorskip("PIL")
    dlg = _editor(root)
    opened = []
    orig = tk.Toplevel
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        dlg._measure_from_image()
    finally:
        tk.Toplevel = orig
    assert opened and "Measure from image" in opened[-1].title()
    # a canvas and the Load/Set-scale/Measure/Apply buttons are present
    ws = _all(opened[-1])
    assert any(isinstance(w, tk.Canvas) for w in ws)
    btxt = [b.cget("text") for b in ws if isinstance(b, tk.ttk.Button)]
    for want in ("Load image…", "Set scale…", "Measure", "Apply to editor"):
        assert any(want in t for t in btxt), want
    opened[-1].destroy()


def test_flank_angle_measure_is_check_only(root, tmp_path):
    """The only remaining measured angles are the check-only cone flanks:
    a 3-click finish proposes degrees with NO scale (anchor-free), Accept
    records it into `accepted`, but Apply never writes it — there is no
    editor field for a flank half-angle (it audits ⌀/L, never stored)."""
    pytest.importorskip("PIL")
    from PIL import Image
    dlg = _editor(root)
    d = _open_measure_dialog(dlg)
    st = d._im_state
    p = tmp_path / "v.png"; Image.new("RGB", (400, 200), "gray").save(p)
    d._im_load_path(str(p))
    assert d._im_views["side"]["scale"] is None            # no scale on purpose
    ang = [q for q in im.ro_angle_prompts("axisymmetric")
           if q["field"] == im.FLANK_UPPER_FIELD][0]
    st["prompt"] = ang
    st["clicks"] = [(0.0, 0.0), (200.0, 0.0), (140.0, 140.0)]   # 45°
    st["_finish_measure"]()
    acc = [b for b in _all(d) if isinstance(b, tk.ttk.Button)
           and b.cget("text") == "Accept"][0]
    acc.invoke()
    assert st["accepted"][im.FLANK_UPPER_FIELD] == pytest.approx(45.0)
    dlg._apply_image_measurements(
        {im.FLANK_UPPER_FIELD: 45.0}, st["measurements"], None)
    assert not hasattr(dlg, im.FLANK_UPPER_FIELD)          # check-only: no var
    d.destroy()


def test_flank_symmetry_check_flags_a_tilted_image(root, tmp_path):
    """Two asymmetric flank half-angles turn the angle-check line red-worded
    (ASYMMETRIC → the image is tilted / perspective) — warn-only."""
    pytest.importorskip("PIL")
    from PIL import Image
    dlg = _editor(root)
    d = _open_measure_dialog(dlg)
    st = d._im_state
    p = tmp_path / "v.png"; Image.new("RGB", (400, 200), "gray").save(p)
    d._im_load_path(str(p))
    st["accepted"].update({im.FLANK_UPPER_FIELD: 10.0,
                           im.FLANK_LOWER_FIELD: 20.0})     # 2× apart
    st["_refresh_closure"]()
    var_texts = []
    for w in [w for w in _all(d) if isinstance(w, tk.ttk.Label)]:
        tv = str(w.cget("textvariable"))
        if tv:
            try:
                var_texts.append(str(w.tk.globalgetvar(tv)))
            except Exception:
                pass
    assert any("ASYMMETRIC" in t for t in var_texts)
    d.destroy()


def test_apply_shows_delta_preview_and_writes_only_on_confirm(root):
    """R8 end-to-end: Apply opens the old-vs-new preview instead of writing;
    Back leaves every field untouched; Write commits.  The check-only total
    is counted as audit-only, never listed as a write."""
    pytest.importorskip("PIL")
    dlg = _editor(root)
    dlg._len_var.set("3.0")
    d = _open_measure_dialog(dlg)
    d._im_state["accepted"] = {"_len_var": 3.3}
    apply_btn = [b for b in _all(d) if isinstance(b, tk.ttk.Button)
                 and "Apply to editor" in b.cget("text")][0]

    opened = []
    orig = tk.Toplevel
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        apply_btn.invoke()
    finally:
        tk.Toplevel = orig
    pv = opened[-1]
    assert "Apply preview" in pv.title()
    assert dlg._len_var.get() == "3.0"            # nothing written yet
    texts = [str(w.cget("text")) for w in _all(pv)
             if isinstance(w, tk.ttk.Label)]
    assert any("+10.0%" in t for t in texts)      # the delta is shown
    # Back: no write
    [b for b in _all(pv) if isinstance(b, tk.ttk.Button)
     and b.cget("text") == "Back"][0].invoke()
    assert dlg._len_var.get() == "3.0"
    # Apply again and confirm: written
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        apply_btn.invoke()
    finally:
        tk.Toplevel = orig
    pv2 = opened[-1]
    [b for b in _all(pv2) if isinstance(b, tk.ttk.Button)
     and "Write" in b.cget("text")][0].invoke()
    assert float(dlg._len_var.get()) == pytest.approx(3.3)


def test_accept_advances_the_checklist(root, tmp_path):
    """Checklist behavior: after a value is recorded the prompt selection
    ADVANCES to the next unmeasured dimension — a selection parked on the old
    prompt is how a fin chord ends up recorded as the vehicle length
    (observed in use).  Already-measured prompts are skipped."""
    pytest.importorskip("PIL")
    from PIL import Image
    d = _open_measure_dialog(_editor(root))
    st = d._im_state
    p = tmp_path / "v.png"; Image.new("RGB", (400, 200), "gray").save(p)
    d._im_load_path(str(p))
    d._im_views["side"]["scale"] = im.Scale((0, 0), (400, 0), 10.0)
    prompts = im.ro_prompts("axisymmetric") + im.ro_angle_prompts("axisymmetric")
    assert d._im_prompt_var.get().startswith("_len_var")   # starts at the top
    st["prompt"] = prompts[0]                              # _len_var, side
    st["clicks"] = [(0.0, 0.0), (200.0, 0.0)]
    st["_finish_measure"]()
    acc = [b for b in _all(d) if isinstance(b, tk.ttk.Button)
           and b.cget("text") == "Accept"][0]
    acc.invoke()
    assert d._im_prompt_var.get().startswith("_dia_var")   # advanced
    # Type value on the now-selected prompt advances too, skipping measured
    import tkinter.simpledialog as sd
    orig_ask = sd.askfloat
    sd.askfloat = lambda *a, **k: 0.58
    try:
        d._im_type_value()
    finally:
        sd.askfloat = orig_ask
    assert d._im_prompt_var.get().startswith("_nose_var")
    d.destroy()


def test_prompt_diagram_renders_antialiased_image(root):
    """The diagram is now an antialiased matplotlib/Agg render (the
    schematic's architecture) displayed as ONE image on the canvas — the
    style/subject contract itself is pixel-tested in test_diagram_render;
    here we pin the GUI plumbing: an image item, a live photo ref, and the
    render actually honouring the subject through the real dialog path."""
    pytest.importorskip("PIL")
    from PIL import ImageTk
    st = im.DIAGRAM_STYLE
    dlg = _editor(root)
    dlg._len_var.set("")           # core dim blank → representative art
    d = _open_measure_dialog(dlg)
    c = d._im_diag
    assert [c.type(i) for i in c.find_all()] == ["image"]
    assert c._photo is not None
    img = ImageTk.getimage(c._photo)
    w, h = img.size
    # _len_var (first prompt) measures the BODY: subject fills white while
    # the fins stay grey (sample the right fin's interior)
    fin_px = img.getpixel((round(0.70 * (w - 1)), round(0.82 * (h - 1))))
    assert all(abs(v - 0xEC) <= 12 for v in fin_px[:3])   # grey fin
    d.destroy()


def test_prompt_diagram_draws_loaded_proportions(root):
    """With dimensions loaded in the editor, the diagram draws THIS
    vehicle's proportions: a 10:1 body renders slender, so a pixel that
    the default representative art covers is background here.  Blanking
    the length (a 'new'-object core dim) falls back to the default art —
    same pixel is body again."""
    pytest.importorskip("PIL")
    from PIL import ImageTk

    def open_with_len(length):
        dlg = _editor(root)
        dlg._len_var.set(length)          # C-HGB ⌀ 0.58 stays loaded
        d = _open_measure_dialog(dlg)
        img = ImageTk.getimage(d._im_diag._photo)
        w, h = img.size
        px = img.getpixel((round(0.42 * (w - 1)), round(0.50 * (h - 1))))
        d.destroy(); dlg.destroy()
        return sum(px[:3]) / 3.0
    assert open_with_len("6.0") > 245     # slender: sample is background
    assert open_with_len("") < 245        # fallback default art: body/edge


def test_prompt_diagram_draws_and_tracks_selection(root):
    """The what-to-click diagram sits under the selector, drawn for the
    FIRST prompt at open, and redraws when the selection changes."""
    pytest.importorskip("PIL")
    dlg = _editor(root)
    d = _open_measure_dialog(dlg)
    first = d._im_diag._photo
    assert first is not None
    ang = [q for q in im.ro_angle_prompts("axisymmetric")
           if q["field"] == im.FLANK_UPPER_FIELD][0]
    d._im_prompt_var.set(f"{ang['field']}  —  {ang['label']}")
    d._im_on_prompt()
    assert d._im_diag._photo is not None
    assert d._im_diag._photo is not first          # redrawn for the new prompt
    assert [d._im_diag.type(i) for i in d._im_diag.find_all()] == ["image"]
    d.destroy()


def test_interstage_length_measures_and_enables_the_section(root):
    """A declared interstage's LENGTH flows to the right stage frame's
    _is_len_var, and applying it enables that stage's interstage section
    (measured-it-so-show-it), so the value isn't stranded in a disabled
    entry."""
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    d._n_stages_var.set("2"); d._update_stage_frames()
    fr = d._stage_frames[0]
    # the field map routes the interstage length to the frame's _is_len_var
    assert d._img_field_var("stage1_interstage_len") is fr._is_len_var
    assert d._img_field_var("stage1_len") is fr._length      # not confused
    fr._interstage_var.set(False); fr._on_interstage()
    d._apply_image_measurements({"stage1_interstage_len": 1.4}, [], None)
    assert float(fr._is_len_var.get()) == pytest.approx(1.4)
    assert fr._interstage_var.get() is True                  # section enabled
    assert str(fr._is_len_entry.cget("state")) == "normal"
    d.destroy()


def test_fairing_nose_length_maps_to_the_editor_field(root):
    """The fairing nose-segment length routes to _shroud_nose_length_var and
    keeps the fairing section enabled (measured-it-so-show-it)."""
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    d._shroud_var.set(False); d._update_shroud_state()
    assert d._img_field_var("fairing_nose_len") is d._shroud_nose_length_var
    d._apply_image_measurements({"fairing_nose_len": 1.8}, [], None)
    assert float(d._shroud_nose_length_var.get()) == pytest.approx(1.8)
    assert d._shroud_var.get() is True                # section enabled
    d.destroy()


def test_ro_diagram_is_shape_aware(root):
    """A Sears-Haack (lv_haack) RO's diagram draws the curved profile; a cone
    draws the straight one — the base art follows the declared shape via the
    ctx passed to the dialog."""
    pytest.importorskip("PIL")
    ro = ro_from_dict(json.load(open("ro_library/C-HGB.ro.json")))

    def open_for(shape_key):
        dlg = thrusty.ROEditorDialog(root, ro=ro); dlg.withdraw()
        dlg._shape_var.set(thrusty.NOSE_SHAPE_LABELS[shape_key])
        dlg._update_body_form_state()
        dlg._len_var.set("")       # default-art path (the layout path's
        # shape-awareness is pinned in test_ro_side_layout_...)
        opened = []
        orig = tk.Toplevel
        tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
        try:
            dlg._measure_from_image()
        finally:
            tk.Toplevel = orig
        d = opened[-1]
        d._im_prompt_var.set(f"_len_var  —  "
                             f"{im.ro_prompts('axisymmetric')[0]['label']}")
        d._im_on_prompt()
        from PIL import ImageTk
        # sample where the haack curve bulges past the straight cone flank
        # (x≈0.399 at y=0.5): dark linework for the curve, background for
        # the cone — proving the ctx-declared shape reached the render
        img = ImageTk.getimage(d._im_diag._photo)
        w, h = img.size
        px = img.getpixel((round(0.399 * (w - 1)), round(0.50 * (h - 1))))
        d.destroy(); dlg.destroy()
        return sum(px[:3]) / 3.0

    assert open_for("cone") > 245          # background at the sample point
    assert open_for("lv_haack") < 200      # the curve's linework crosses it


def test_conical_top_diameter_maps_and_enables_the_section(root):
    """The conical top ⌀ routes to _top_dia_var (distinct from the base _dia),
    and applying it enables that stage's conical section."""
    d = thrusty.BoosterDialog(root, on_save=lambda *a, **k: None)
    d.withdraw()
    d._n_stages_var.set("2"); d._update_stage_frames()
    fr = d._stage_frames[0]
    assert d._img_field_var("stage1_top_dia") is fr._top_dia_var
    assert d._img_field_var("stage1_dia") is fr._dia          # not confused
    fr._conical_var.set(False); fr._on_conical()
    d._apply_image_measurements({"stage1_top_dia": 2.4}, [], None)
    assert float(fr._top_dia_var.get()) == pytest.approx(2.4)
    assert fr._conical_var.get() is True                     # section enabled
    assert str(fr._top_dia_entry.cget("state")) == "normal"
    d.destroy()


# ── the click path itself ───────────────────────────────────────────────────
# Everything above drives the dialog's helpers directly.  The CLICK path was
# never covered -- this file's own docstring said it "needs a real event loop
# and is verified by hand".  It was not verified by hand either: the tool
# reached the author's desk telling him, after a completed reading, to click
# the point he had just clicked, and silently dropping every click after that.
# These drive `_on_click` for real.

class _Ev:
    """A click at canvas coordinates (the handler reads only .x/.y)."""
    def __init__(self, x, y):
        self.x, self.y = x, y


def _ready_to_measure(root, tmp_path, w=1200, h=600, anchor_px=400,
                      anchor_m=10.0):
    """A dialog with an image loaded and a scale anchored, ready to click."""
    pytest.importorskip("PIL")
    from PIL import Image
    p = tmp_path / "fig.png"
    Image.new("RGB", (w, h), "gray").save(p)
    d = _open_measure_dialog(_editor(root))
    d._im_load_path(str(p))
    d._im_views[d._im_state["cur"]]["scale"] = im.Scale(
        (0.0, 0.0), (float(anchor_px), 0.0), anchor_m)
    return d


def test_a_finished_reading_does_not_still_ask_for_the_click(root, tmp_path):
    """The status line must describe the state the tool is actually in.

    The last click of a measurement goes straight to the finish handler, so
    the per-click progress message ("[1/2] click the second point") was never
    refreshed.  It stayed on screen while the mode had dropped to idle and
    the marks had been erased -- telling the user to do the one thing that
    would now be ignored.  That, not any arithmetic, is what "sometimes it
    accepts and sometimes it does not" was."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(100, 100))
        assert "click the second point" in d._im_status.get()   # correct here
        d._im_on_click(_Ev(500, 300))
        assert d._im_state["mode"] == "idle"
        assert d._im_state.get("_pending") is not None
        assert "click the second point" not in d._im_status.get()
        assert "Accept" in d._im_status.get()
    finally:
        d.destroy()


def test_the_finished_reading_stays_on_screen_until_accepted(root, tmp_path):
    """Completing a measurement clears the click list, so the marks used to
    vanish on the very click that produced the answer -- no trace of what had
    been measured.  The pending points and the span between them stay drawn."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(100, 100))
        d._im_on_click(_Ev(500, 300))
        assert not d._im_state["clicks"]          # the reading is finished...
        assert d._im_canvas.find_withtag("pend")  # ...and still visible
    finally:
        d.destroy()


def test_accept_disarms_itself(root, tmp_path):
    """Accept was armed in one place and disarmed in another that only ran
    when a NEW measurement began, so from the first Accept onward it stayed
    lit for ever and every later press did nothing at all.  A lit button that
    does nothing is indistinguishable from a broken tool."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(100, 100))
        d._im_on_click(_Ev(500, 300))
        assert str(d._im_accept_btn.cget("state")) == "normal"
        d._im_accept_btn.invoke()
        assert d._im_state["accepted"]                  # it recorded
        assert d._im_state.get("_pending") is None
        assert str(d._im_accept_btn.cget("state")) == "disabled"
    finally:
        d.destroy()


def test_a_click_with_nothing_armed_is_not_silent(root, tmp_path):
    """Mode returns to idle after every completed reading, and a click then
    hit a bare `return`: no mark, no message, no change of any kind.  It must
    at least leave the status line saying what to press."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(100, 100))
        d._im_on_click(_Ev(500, 300))
        d._im_accept_btn.invoke()                       # back to idle
        d._im_status.set("")                            # prove the click writes it
        d._im_on_click(_Ev(700, 400))
        assert "Measure" in d._im_status.get()
        assert not d._im_state["clicks"]                # and took no point
    finally:
        d.destroy()


def test_typing_a_value_retires_an_unaccepted_reading(root, tmp_path, monkeypatch):
    """Type value… exists so a known dimension is recorded as entered by hand.
    It left any pending measurement armed, so Type value… then Accept replaced
    the typed number with the older measured one AND re-stamped its provenance
    as measured off the image -- the exact claim this path exists to avoid."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(100, 100))
        d._im_on_click(_Ev(500, 300))
        measured = d._im_state["_pending"].value_m
        monkeypatch.setattr("tkinter.simpledialog.askfloat",
                            lambda *a, **k: 7.25)
        d._im_type_value()
        field = d._im_state["prompt"]["field"]
        assert d._im_state["accepted"][field] == 7.25
        assert d._im_state.get("_pending") is None
        assert str(d._im_accept_btn.cget("state")) == "disabled"
        d._im_accept_btn.invoke()                       # must not resurrect it
        assert d._im_state["accepted"][field] == 7.25 != measured
        assert type(d._im_state["measurements"][-1]).__name__ == "HandEntry"
    finally:
        d.destroy()


def test_changing_the_selection_abandons_a_half_clicked_measurement(root, tmp_path):
    """`state["prompt"]` is written only when a measurement begins, so
    changing the checklist selection part-way through clicking left the
    in-flight reading pointing at the OLD field: one stale point plus the next
    click spanned two unrelated features and recorded it under the wrong
    dimension.  Switching views already reset this way; selection now does."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(100, 100))
        assert d._im_state["mode"] == "measure" and d._im_state["clicks"]
        d._im_on_prompt()                        # user picks another dimension
        assert d._im_state["mode"] == "idle"
        assert not d._im_state["clicks"]
    finally:
        d.destroy()


def test_a_refusal_does_not_look_like_a_success(root, tmp_path):
    """Refusal and success rendered in the same green, so "nothing recorded"
    read as "recorded" at a glance.  The refusal also names the floor in
    METRES and says zooming cannot help, because clicks are stored in image
    pixels and reaching for zoom is the natural, useless response."""
    d = _ready_to_measure(root, tmp_path)
    try:
        d._im_begin_measure()
        d._im_on_click(_Ev(300, 300))
        d._im_on_click(_Ev(303, 300))            # ~3 px: under the floor
        assert d._im_state.get("_pending") is None
        assert str(d._im_accept_btn.cget("state")) == "disabled"
        text = d._im_result.get()
        assert "refused" in text and "Zooming will not help" in text
        ok_dlg = _ready_to_measure(root, tmp_path)
        try:
            ok_dlg._im_begin_measure()
            ok_dlg._im_on_click(_Ev(100, 100))
            ok_dlg._im_on_click(_Ev(500, 300))
            assert (str(d._im_result_lbl.cget("foreground"))
                    != str(ok_dlg._im_result_lbl.cget("foreground")))
        finally:
            ok_dlg.destroy()
    finally:
        d.destroy()


# ── legacy reentry-object files still load ──────────────────────────────────

def test_legacy_rv_json_objects_are_still_read(root, tmp_path, monkeypatch):
    """`rv_library/*.rv.json` is the pre-rename spelling, and README and the
    code comment both promise it still loads.  It had stopped: the rv->ro
    terminology sweep rewrote the string literal inside the legacy glob, so
    the loader globbed `*.ro.json` twice and the legacy directory was walked
    for nothing."""
    import json as _json
    legacy = tmp_path / "rv_library"; legacy.mkdir()
    newdir = tmp_path / "ro_library"; newdir.mkdir()

    def _obj(name, mass):
        return _json.dumps({"name": name, "mass_kg": mass, "beta_kg_m2": 2222.0,
                            "shape": "cone", "diameter_m": 0.5, "length_m": 1.5})

    # (a) reachable ONLY through the legacy spelling -- this is the regression
    (legacy / "Only_Legacy.rv.json").write_text(_obj("Only Legacy", 111.0))
    # (b) present in both spellings -- the new form must win
    (legacy / "Both.rv.json").write_text(_obj("Both", 111.0))
    (newdir / "Both.ro.json").write_text(_obj("Both", 999.0))

    monkeypatch.setattr(thrusty, "_BUNDLED_RO_LIBRARY_PATH", tmp_path / "empty")
    monkeypatch.setattr(thrusty, "_LEGACY_RO_LIBRARY_PATH", legacy)
    monkeypatch.setattr(thrusty, "_RO_LIBRARY_PATH", newdir)
    thrusty._load_ro_library()

    assert "Only Legacy" in thrusty.RO_DB, (
        "a .rv.json object reachable only through the legacy spelling did not "
        "load -- the legacy glob is broken again")
    assert thrusty.RO_DB["Only Legacy"]().mass_kg == 111.0
    assert thrusty.RO_DB["Both"]().mass_kg == 999.0, (
        "the new-form file must override the legacy one of the same name")
