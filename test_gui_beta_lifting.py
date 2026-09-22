"""β-estimator dialog routing by body form (Phase 2c GUI wiring).

The estimator dialog is presentation over booster_models.lifting_body_sweep()
and cd_cone_hypersonic(); these tests check the WIRING the pure-function tests
can't reach: that a lifting body opens the α-sweep estimator, an axisymmetric
body opens the cone build-up, and that "Use β and L/D" writes both the β and
the glider-L/D fields from one consistent trim row.

Skips cleanly where tkinter / a display is unavailable.
"""

import json

import pytest

pytest.importorskip("tkinter", reason="no Tk in this interpreter")

import matplotlib
matplotlib.use("Agg")
import tkinter as tk

import thrusty
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


def _editor(root, form):
    ro = ro_from_dict(json.load(open("ro_library/C-HGB.ro.json")))
    dlg = thrusty.ROEditorDialog(root, ro=ro)
    dlg.withdraw()
    # merged Shape selector: a lifting form is its own entry; 'axisymmetric'
    # is any nose profile (Cone here).
    label = (dlg._BODY_FORM_LABELS[form] if form in ("wedge", "half_cone")
             else thrusty.NOSE_SHAPE_LABELS["cone"])
    dlg._shape_var.set(label)
    dlg._update_body_form_state()
    dlg._mass_var.set("900"); dlg._len_var.set("3.6"); dlg._dia_var.set("0.5")
    return dlg


def _capture_dialog(dlg):
    """Invoke _calc_beta and return the Toplevel it creates."""
    opened = []
    orig = tk.Toplevel
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        dlg._calc_beta()
    finally:
        tk.Toplevel = orig
    return opened[-1]


def _all_widgets(w, acc=None):
    acc = [] if acc is None else acc
    for c in w.winfo_children():
        acc.append(c); _all_widgets(c, acc)
    return acc


def test_axisymmetric_opens_the_cone_builder(root):
    dlg = _editor(root, "axisymmetric")
    sub = _capture_dialog(dlg)
    assert sub.title() == "Estimate Object β"


@pytest.mark.parametrize("form,frag", [("wedge", "wedge"),
                                       ("half_cone", "half-cone")])
def test_lifting_forms_open_the_alpha_sweep_estimator(root, form, frag):
    dlg = _editor(root, form)
    sub = _capture_dialog(dlg)
    assert "L/D" in sub.title() and frag in sub.title()


def test_use_writes_both_beta_and_ld_from_one_trim_row(root):
    dlg = _editor(root, "wedge")
    sub = _capture_dialog(dlg)
    ents = [w for w in _all_widgets(sub) if isinstance(w, tk.ttk.Entry)]
    # rows: mass, length, depth, span, mach, Re, T_w  → span is index 3
    ents[3].insert(0, "0.9")                 # REQUIRED planform span
    sub.update_idletasks()
    use = next(w for w in _all_widgets(sub)
               if isinstance(w, tk.ttk.Button) and w.cget("text").startswith("Use"))
    use.invoke()
    beta = float(dlg._beta_var.get())
    ld = float(dlg._LD_var.get())
    assert beta > 0.0                        # zero-lift β written
    assert 2.0 < ld < 6.0                    # (L/D)max written, sharp-body band


def test_merged_shape_selector_sets_both_shape_and_body_form(root):
    """One selector, two data fields: an axisymmetric nose profile implies a
    body of revolution; a lifting-body entry sets body_form and keeps a
    (moot) cone nose."""
    import dataclasses
    dlg = _editor(root, "axisymmetric")
    dlg._shape_var.set(thrusty.NOSE_SHAPE_LABELS["tangent_ogive"])
    dlg._update_body_form_state()
    ro = dlg._build_ro()
    assert ro.shape == "tangent_ogive" and ro.body_form == "axisymmetric"
    dlg._shape_var.set(dlg._BODY_FORM_LABELS["wedge"])
    dlg._update_body_form_state()
    ro2 = dlg._build_ro()
    assert ro2.body_form == "wedge" and ro2.shape == "cone"


def test_lifting_form_wins_the_label_on_reopen_and_clears_biconic(root):
    """Reopening a stored (shape, body_form, biconic): a lifting body_form
    shows its own label regardless of the stored nose shape and clears the
    biconic flag (body-of-revolution only); an axisymmetric body shows its
    nose profile; a stored biconic shows the Biconic dropdown entry."""
    import dataclasses
    dlg = _editor(root, "wedge")
    wedge_ro = dataclasses.replace(dlg._build_ro(), shape="tangent_ogive")
    reopened = thrusty.ROEditorDialog(root, ro=wedge_ro); reopened.withdraw()
    assert reopened._body_form_key() == "wedge"
    assert reopened._shape_var.get() == reopened._BODY_FORM_LABELS["wedge"]
    assert reopened._biconic_var.get() is False
    # an ogive-nosed round body shows the ogive; not biconic
    og = dataclasses.replace(wedge_ro, body_form="axisymmetric", shape="tangent_ogive")
    r2 = thrusty.ROEditorDialog(root, ro=og); r2.withdraw()
    assert r2._shape_key() == "tangent_ogive" and r2._body_form_key() == "axisymmetric"
    assert r2._biconic_var.get() is False
    # a stored biconic reopens on the Biconic entry with fore/break enabled
    bic = dataclasses.replace(og, biconic=True, fore_length_m=0.9,
                              break_diameter_m=0.25)
    r3 = thrusty.ROEditorDialog(root, ro=bic); r3.withdraw()
    assert r3._shape_var.get() == r3._BICONIC_LABEL
    assert r3._biconic_var.get() is True
    assert str(r3._fore_len_entry.cget("state")) == "normal"


def test_biconic_is_a_shape_dropdown_entry(root):
    """The user-facing answer to 'where is biconic?': in the Shape list.
    Selecting the Biconic entry sets the flag, enables the break-geometry
    fields, and _build_ro stores biconic=True with shape normalized to
    'cone'; selecting a plain profile clears it all."""
    dlg = _editor(root, "axisymmetric")
    assert dlg._BICONIC_LABEL in dlg._shape_combo.cget("values")
    dlg._shape_var.set(dlg._BICONIC_LABEL)
    dlg._update_body_form_state()
    assert dlg._biconic_var.get() is True
    assert str(dlg._fore_len_entry.cget("state")) == "normal"
    dlg._fore_len_var.set("0.9"); dlg._break_dia_var.set("0.25")
    ro = dlg._build_ro()
    assert ro.biconic is True and ro.shape == "cone" \
        and ro.body_form == "axisymmetric"
    assert ro.fore_length_m == pytest.approx(0.9)
    dlg._shape_var.set(thrusty.NOSE_SHAPE_LABELS["cone"])
    dlg._update_body_form_state()
    assert dlg._biconic_var.get() is False
    assert str(dlg._fore_len_entry.cget("state")) == "disabled"
    assert dlg._build_ro().biconic is False


def test_span_and_wing_fields_gate_by_body_form(root):
    """The user-visible rule: body span is a WEDGE field; the wing rows are
    for bodies that can carry a wing ON them — axisymmetric AND half-cone
    (Fetterman's half-cone delta-wing is a real configuration) — and are
    disabled for the wedge, whose body IS the lifting surface."""
    dlg = _editor(root, "wedge")
    dlg._glider_var.set(True); dlg._update_glider_state()
    assert str(dlg._body_span_entry.cget("state")) == "normal"
    assert all(str(e.cget("state")) == "disabled" for e in dlg._wing_entries)
    for form, span_state in (("axisymmetric", "disabled"),
                             ("half_cone", "disabled")):
        d = _editor(root, form)
        d._glider_var.set(True); d._update_glider_state()
        assert str(d._body_span_entry.cget("state")) == span_state, form
        # wing rows live for both (S/AR may be readonly when derived — the
        # gate only forbids 'disabled')
        assert all(str(e.cget("state")) != "disabled"
                   for e in d._wing_entries), form


def test_wing_rows_gate_on_maneuvering(root):
    """Two-column layout: the wing planform lives in the GEOMETRY group (a
    wing is hardware) but stays declared topology of the maneuvering model —
    rows grey out until the Maneuvering checkbox is ticked (same pattern as
    the biconic fields), and the L/D row greys with it.  Grey-out, not hide:
    the checkbox must stay visible either way."""
    dlg = _editor(root, "axisymmetric")
    dlg._glider_var.set(False); dlg._update_glider_state()
    assert all(str(e.cget("state")) == "disabled" for e in dlg._wing_entries)
    assert str(dlg._LD_entry.cget("state")) == "disabled"
    dlg._glider_var.set(True); dlg._update_glider_state()
    assert all(str(e.cget("state")) != "disabled" for e in dlg._wing_entries)
    assert str(dlg._LD_entry.cget("state")) == "normal"


def test_wedge_stores_span_and_zeroes_hidden_wing_fields(root):
    """What you see is what's stored: the wedge persists body_span_m, and the
    disabled wing rows save as zero (hidden-but-active wing physics through
    the polar's e_pull would be dishonest)."""
    dlg = _editor(root, "wedge")
    dlg._glider_var.set(True); dlg._update_glider_state()
    dlg._body_span_var.set("0.9")
    dlg._wing_area_var.set("0.5")            # stale value from a former form
    ro = dlg._build_ro()
    assert ro.body_span_m == 0.9
    assert ro.wing_area_m2 == 0.0            # not silently carried
    assert ro.glider_LD > 0.0                # glider L/D survives (dangling-else guard)
    # and the estimator dialog pre-fills its REQUIRED span from the stored one
    sub = _capture_dialog(dlg)
    ents = [w for w in _all_widgets(sub) if isinstance(w, tk.ttk.Entry)]
    assert ents[3].get() == "0.9"            # span row, pre-filled
    sub.destroy()


def test_missing_required_span_yields_no_result(root):
    """Span is required for the wedge; without it the dialog must refuse to
    produce a β (the derive-don't-invent rule — no fabricated planform)."""
    dlg = _editor(root, "wedge")
    before = dlg._beta_var.get()
    sub = _capture_dialog(dlg)               # span left at default 0
    use = next(w for w in _all_widgets(sub)
               if isinstance(w, tk.ttk.Button) and w.cget("text").startswith("Use"))
    use.invoke()
    assert dlg._beta_var.get() == before     # unchanged — nothing written


# ── Phase 2b GUI wiring: LE radius (wedge) + wing composite (half-cone) ──────
def test_wedge_dialog_offers_le_radius_prefilled_from_nose(root):
    """The wedge's 'nose' IS its leading edge, so the RO nose-radius field
    pre-fills the swept-cylinder LE radius (0 = sharp keeps the documented
    upper-bound behavior)."""
    dlg = _editor(root, "wedge")
    dlg._nose_var.set("0.03")
    dlg._body_span_var.set("1.4")
    sub = _capture_dialog(dlg)
    labels = [str(w.cget("text")) for w in _all_widgets(sub)
              if isinstance(w, tk.ttk.Label)]
    assert any("Leading-edge radius" in t for t in labels)
    ents = [w for w in _all_widgets(sub) if isinstance(w, tk.ttk.Entry)]
    # mass, length, depth, span, LE radius
    assert ents[4].get() == "0.03"
    sub.destroy()


def test_half_cone_dialog_composites_declared_wings(root):
    """The Fetterman configuration end-to-end: a half-cone whose editor
    declares a wing planform shows the composite S_exp in the dialog, and the
    conditions line carries the wing ratio (S/A_b) so the number can never be
    quoted without its configuration."""
    dlg = _editor(root, "half_cone")
    dlg._glider_var.set(True); dlg._update_glider_state()
    dlg._wing_root_var.set("2.0"); dlg._wing_span_var.set("0.8")
    dlg._wing_sweep_var.set("0")
    sub = _capture_dialog(dlg)
    sub.update_idletasks()
    labels = [str(w.cget("text")) for w in _all_widgets(sub)
              if isinstance(w, tk.ttk.Label)]
    assert any("S_exp = 3.2" in t for t in labels), \
        [t for t in labels if "S_exp" in t or "none" in t]
    assert any("wing S/A_b" in t for t in labels)
    sub.destroy()


def test_half_cone_dialog_without_wings_says_body_alone(root):
    dlg = _editor(root, "half_cone")
    dlg._glider_var.set(False); dlg._update_glider_state()
    sub = _capture_dialog(dlg)
    sub.update_idletasks()
    labels = [str(w.cget("text")) for w in _all_widgets(sub)
              if isinstance(w, tk.ttk.Label)]
    assert any("none (body alone)" in t for t in labels)
    sub.destroy()


# ── Phase 3: the trim row persists from the SAME sweep as β and L/D ──────────
def test_use_stores_trim_row_and_axisymmetric_zeroes_it(root):
    """"Use β and L/D" persists α* and C_L0 alongside β/L-D — one consistent
    row (the anti-Tracy&Wright invariant, now stored).  Switching the form
    back to a body of revolution zeroes them on save: a stale camber offset
    on an axisymmetric body would silently skew the polar."""
    dlg = _editor(root, "half_cone")
    dlg._glider_var.set(True); dlg._update_glider_state()
    sub = _capture_dialog(dlg)
    sub.update_idletasks()
    # the live compute has run; take its consistent row via the Use button
    use = [b for b in _all_widgets(sub) if isinstance(b, tk.ttk.Button)
           and "Use β" in b.cget("text")][0]
    use.invoke()
    assert dlg._trim_alpha_val > 0.0            # α* of a real sweep
    ro = dlg._build_ro()
    assert ro.trim_alpha_deg == pytest.approx(dlg._trim_alpha_val)
    assert ro.trim_CL0 == pytest.approx(dlg._trim_cl0_val)
    # same editor, form switched to a body of revolution → zeroed on save
    dlg._shape_var.set(thrusty.NOSE_SHAPE_LABELS["cone"])
    dlg._update_body_form_state()
    ro2 = dlg._build_ro()
    assert ro2.trim_alpha_deg == 0.0 and ro2.trim_CL0 == 0.0


# ── the "(from booster)" fields say what the run will use ───────────────────

def _body_pair(length_m=7.5, diameter_m=0.515, m0=2635.0, mprop=2335.0,
               stored_len=2.97, stored_dia=0.52, stored_mass=300.0,
               payload=150.0):
    """A body-reentering booster plus an object whose STORED geometry
    deliberately disagrees with it, which is the situation that shipped."""
    from booster_models import BoosterParams, ROParams
    p = BoosterParams(name="B", mass_initial=m0, mass_propellant=mprop,
                      mass_final=m0 - mprop, diameter_m=diameter_m,
                      length_m=length_m, thrust_N=43e3, burn_time_s=134.0,
                      isp_s=250.0, body_reenters=True)
    ro = ROParams(name="front end", mass_kg=stored_mass, beta_kg_m2=0.0,
                  shape="tangent_ogive", diameter_m=stored_dia,
                  length_m=stored_len, payload_kg=payload,
                  body_nose_length_m=2.0)
    return p, ro


def test_inherited_fields_show_what_the_run_will_use(root):
    """The editor labels mass, diameter and length "(from booster)" for a
    non-separating body, then used to populate them from the STORED object --
    so it showed a 2.97 m front end while the run flew the whole 7.50 m
    airframe, and the number the user had measured off an image was discarded
    in silence.  FRONT_END_DESIGN.md lists that as defect C and requires the
    field to display the inherited value instead.

    Pin the two surfaces to each other: whatever the editor shows under that
    label must be what effective_ro hands the integrator."""
    from booster_models import compose_loadout, effective_ro
    p, ro = _body_pair()
    dlg = thrusty.ROEditorDialog(root, ro=ro, booster=p, plan_sep='body')
    try:
        dlg.withdraw()
        composed = compose_loadout(p, ro, 1)
        composed.ro = ro
        flown = effective_ro(composed)
        assert float(dlg._len_var.get()) == pytest.approx(flown.length_m, abs=5e-3)
        assert float(dlg._dia_var.get()) == pytest.approx(flown.diameter_m, abs=5e-4)
        # the mass field is the AIRFRAME alone; the payload is added beside it
        assert (float(dlg._mass_var.get()) + ro.payload_kg
                == pytest.approx(flown.mass_kg, abs=0.5))
        # ...and none of them is the stored value that the run ignores
        assert float(dlg._len_var.get()) != pytest.approx(ro.length_m, abs=1e-3)
    finally:
        dlg.destroy()


def test_inherited_mass_tracks_a_booster_edit(root):
    """The fields were seeded once and never refreshed, so editing the
    booster's dry mass left the editor's "= N kg reentry" line stale against
    a run that flew something else."""
    from booster_models import compose_loadout, effective_ro
    p, ro = _body_pair(m0=2635.0, mprop=2275.0)      # airframe 360, not 300
    dlg = thrusty.ROEditorDialog(root, ro=ro, booster=p, plan_sep='body')
    try:
        dlg.withdraw()
        assert float(dlg._mass_var.get()) == pytest.approx(360.0, abs=0.5)
        composed = compose_loadout(p, ro, 1)
        composed.ro = ro
        assert effective_ro(composed).mass_kg == pytest.approx(510.0, abs=0.5)
        assert "510" in dlg._payload_total_lbl.cget("text")
    finally:
        dlg.destroy()


def test_the_beta_estimator_is_seeded_on_the_body_that_flies(root):
    """The β estimator seeds its cone half-angle from those same fields, so
    while they held the stored front end it answered for a body less than half
    the real length: a 5.0° cone rather than the airframe's 2.0°."""
    import math
    p, ro = _body_pair()
    dlg = thrusty.ROEditorDialog(root, ro=ro, booster=p, plan_sep='body')
    try:
        dlg.withdraw()
        d, L = float(dlg._dia_var.get()), float(dlg._len_var.get())
        seeded = math.degrees(math.atan(1.0 / (2.0 * L / d)))
        assert seeded == pytest.approx(2.0, abs=0.15)
        stored = math.degrees(math.atan(1.0 / (2.0 * ro.length_m / ro.diameter_m)))
        assert stored == pytest.approx(5.0, abs=0.15)      # what it used to be
    finally:
        dlg.destroy()
