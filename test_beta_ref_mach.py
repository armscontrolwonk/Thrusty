"""β stated at a Mach — `ROParams.beta_ref_mach` (memo §7 item 5).

beta_kg_m2 used to be one number at every Mach.  A slender body's own zero-lift
drag varies several-fold across a glide (base drag, 2/(γM²)), so a constant β
is a Mach-less assertion.  With beta_ref_mach > 0 the entered β is held EXACT
at that Mach and the object's geometry supplies only the relative variation;
an entered L/D is scaled so the drag-due-to-lift factor k stays fixed (the
variation is zero-lift drag and belongs in C_D0 — docs/aero_polar_calibration
§4a).  beta_ref_mach = 0 is the legacy constant β, byte-identical.
"""
import copy
import dataclasses as dc
import glob
import json
import math
import os

import numpy as np
import pytest

import booster_models as bm
from booster_models import ro_from_dict, ro_to_dict
from trajectory import _aero_polar

HERE = os.path.dirname(os.path.abspath(__file__))


def _ro(name="SWERVE", **kw):
    ro = ro_from_dict(json.load(open(os.path.join(HERE, "ro_library",
                                                  f"{name}.ro.json"))))
    return dc.replace(ro, **kw)


# ── schema ──────────────────────────────────────────────────────────────────
def test_every_shipped_object_loads_as_constant_beta():
    for path in glob.glob(os.path.join(HERE, "ro_library", "*.ro.json")):
        assert ro_from_dict(json.load(open(path))).beta_ref_mach == 0.0, path


def test_field_round_trips_and_is_hardware():
    ro = _ro(beta_ref_mach=7.5)
    d = ro_to_dict(ro, include_reentry_plan=False)
    assert d["beta_ref_mach"] == 7.5
    assert ro_from_dict(d).beta_ref_mach == 7.5
    # it qualifies the β measurement — an RO hardware key, never a plan key
    assert "beta_ref_mach" not in set(bm._REENTRY_PLAN_KEYS)


# ── the table ───────────────────────────────────────────────────────────────
def test_no_reference_mach_means_no_table():
    assert bm.beta_mach_table(_ro()) is None
    assert bm.beta_mach_table(_ro(beta_ref_mach=10.0, beta_kg_m2=0.0)) is None


@pytest.mark.parametrize("mref", [4.0, 7.0, 10.0, 18.0])
def test_entered_beta_is_exact_at_its_mach(mref):
    t = bm.beta_mach_table(_ro(beta_ref_mach=mref))
    j = list(t["machs"]).index(mref)
    assert t["beta"][j] == pytest.approx(24733.0, rel=1e-12)
    assert t["ld_scale"][j] == pytest.approx(1.0, rel=1e-12)


def test_cone_beta_rises_with_mach_and_is_flat_below_the_floor():
    t = bm.beta_mach_table(_ro(beta_ref_mach=10.0))
    M, b = t["machs"], t["beta"]
    hi = M >= 3.0
    assert np.all(np.diff(b[hi]) > 0.0)          # base drag falls with Mach
    assert np.allclose(b[M <= 3.0], b[M <= 3.0][0])   # hypersonic floor M3
    assert t["source"] == "cd_cone_hypersonic"   # the β dialog's own build-up
    assert np.allclose(t["ld_scale"], np.sqrt(t["ratio"]))


def test_k_is_fixed_across_mach():
    """The whole point of the L/D scaling: C_D0 moves, k does not."""
    ro = _ro(beta_ref_mach=10.0)
    t = bm.beta_mach_table(ro)
    ks = [_aero_polar(ro, ld_override=1.8 * s, beta_override=b).k
          for b, s in zip(t["beta"], t["ld_scale"])]
    c0 = [_aero_polar(ro, ld_override=1.8 * s, beta_override=b).C_D0
          for b, s in zip(t["beta"], t["ld_scale"])]
    assert np.allclose(ks, ks[0], rtol=1e-12)
    assert max(c0) / min(c0) > 3.0                # while C_D0 really varies


def test_a_dialog_estimate_reproduces_itself():
    """β estimated in the cone dialog at Mach X, stamped with X, must come
    back out of the table at X — same build-up, same conventions."""
    ro = _ro()
    th = math.degrees(math.atan2(ro.diameter_m / 2, ro.length_m))
    eps = 2 * ro.nose_radius_m / ro.diameter_m
    A = math.pi * (ro.diameter_m / 2) ** 2
    for X in (5.0, 12.0):
        beta_x = ro.mass_kg / (bm.cd_cone_hypersonic(th, eps, mach=X)["total"] * A)
        t = bm.beta_mach_table(dc.replace(ro, beta_kg_m2=beta_x, beta_ref_mach=X))
        for M in (4.0, 8.0, 20.0):
            direct = ro.mass_kg / (bm.cd_cone_hypersonic(th, eps, mach=M)["total"] * A)
            assert np.interp(M, t["machs"], t["beta"]) == pytest.approx(direct, rel=1e-9)


# ── the pairing check follows a stated Mach ─────────────────────────────────
def test_a_stated_mach_replaces_the_band():
    r = bm.check_ro_pairing_band(_ro(beta_ref_mach=10.0))
    assert r["mach_band"] == (10.0,)
    assert "over M" not in bm.pairing_note(_ro(beta_ref_mach=10.0))[0]
    text, sev = bm.pairing_note(_ro(beta_ref_mach=10.0, glider_LD=4.0))
    assert sev == "bad" and text.startswith("at M 10") and "no Mach" not in text


# ── integrator ──────────────────────────────────────────────────────────────
def _fly(ro, max_time_s=3600.0):
    from booster_models import get_booster, load_reentry_plan, apply_reentry_plan
    from trajectory import integrate_trajectory
    ro = apply_reentry_plan(ro, dict(load_reentry_plan("SWERVE") or {},
                                     glider_guidance="damped_glide",
                                     glider_damping_zeta=0.7))
    p = get_booster("Strypi VIII R")
    p.ro = copy.deepcopy(ro)
    p.guidance = "pitch_program"
    # horizontal burnout (γ ≈ 0 at cutoff) — a boost-glide entry, not a lob
    return integrate_trajectory(p, 22.0228, -159.785, 270.0,
                                burnout_angle_deg=-26.93, cutoff_time_s=57.0,
                                gt_turn_start_s=0.0, gt_turn_stop_s=50.0,
                                launch_elevation_deg=70.0, max_time_s=max_time_s,
                                dt_output=1.0)


def test_unset_field_never_builds_a_table(monkeypatch):
    """beta_ref_mach = 0 must not even reach the table code — the guarantee
    behind 'byte-identical for every existing file'."""
    def _boom(*a, **k):
        raise AssertionError("beta_mach_table called with beta_ref_mach = 0")
    monkeypatch.setattr(bm, "beta_mach_table", _boom)
    r = _fly(_ro())
    assert r["range_km"] and r["range_km"] > 0


def test_tumbling_body_keeps_its_tumbling_beta(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("stated-β table applied to a tumbling body")
    monkeypatch.setattr(bm, "beta_mach_table", _boom)
    # The guard acts at setup, before integration; a short flight is enough.
    # (A tumbling object makes the ASCENT integration crawl — pre-existing,
    # in the boost-phase drag model, unrelated to the stated-β table.)
    _fly(_ro(beta_ref_mach=10.0, reentry_attitude="tumbling"), max_time_s=2.0)


def test_the_reference_mach_moves_the_glide_the_right_way():
    """β stated at LOW Mach extrapolates UP (less base drag) at glide speeds,
    so it glides further than the same β stated at HIGH Mach."""
    r_lo = _fly(_ro(beta_ref_mach=5.0))
    r_hi = _fly(_ro(beta_ref_mach=15.0))
    assert r_lo["range_km"] > r_hi["range_km"] * 1.2


# ── GUI (skips without Tk / a display) ──────────────────────────────────────
@pytest.fixture(scope="module")
def root():
    tk = pytest.importorskip("tkinter", reason="no Tk in this interpreter")
    import matplotlib
    matplotlib.use("Agg")
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    r.withdraw()
    yield r
    r.destroy()


def _editor(root, name):
    import thrusty
    d = thrusty.ROEditorDialog(root, ro=_ro(name))
    d.withdraw()
    root.update()
    return d


def test_gui_pairing_note_fires_for_a_separating_object(root):
    """Regression: the note used to hang off the body-only L/D preview label
    and was fed the derive-mode preview object (β = L/D = 0), so it never
    showed for any separating object — every shipped glider."""
    d = _editor(root, "C-HGB")
    try:
        assert d._plan_sep != "body"
        lbl = d._pairing_lbl
        assert lbl.winfo_manager()                      # actually on screen
        assert "no Mach supports" in lbl.cget("text")
        assert str(lbl.cget("foreground")) == d._PAIRING_COLOUR["bad"]
        d._glider_var.set(False); root.update()
        assert lbl.cget("text") == ""                   # moot without lift
    finally:
        d.destroy()


def test_gui_note_tracks_edits(root):
    d = _editor(root, "SWERVE")
    try:
        assert "consistent" in d._pairing_lbl.cget("text")
        d._LD_var.set("4.0"); root.update()
        assert "no Mach supports" in d._pairing_lbl.cget("text")
        d._beta_mach_var.set("10"); root.update()
        assert d._pairing_lbl.cget("text").startswith("β + L/D: at M 10")
    finally:
        d.destroy()


def test_gui_beta_mach_survives_a_save(root):
    """The editor rebuilds ROParams from its widgets; a field it does not
    carry is silently reset on save.  This one must be carried."""
    d = _editor(root, "SWERVE")
    try:
        d._beta_mach_var.set("7")
        assert d._build_ro().beta_ref_mach == 7.0
        d._beta_mach_var.set("0")
        assert d._build_ro().beta_ref_mach == 0.0
    finally:
        d.destroy()


def test_gui_cone_estimate_stamps_its_mach(root):
    import tkinter as tk
    d = _editor(root, "SWERVE")
    opened, orig = [], tk.Toplevel
    tk.Toplevel = lambda *a, **k: (lambda w: (opened.append(w), w)[1])(orig(*a, **k))
    try:
        d._calc_beta()
    finally:
        tk.Toplevel = orig
    try:
        dlg = opened[-1]

        def walk(w):
            for c in w.winfo_children():
                yield c
                yield from walk(c)
        entries = [w for w in walk(dlg) if isinstance(w, tk.ttk.Entry)]
        # rows: mass, diameter, half-angle, eps, Eval Mach, ...
        mach_entry = entries[4]
        mach_entry.delete(0, "end"); mach_entry.insert(0, "12")
        root.update()
        use = next(w for w in walk(dlg)
                   if isinstance(w, tk.ttk.Button) and w.cget("text").startswith("Use"))
        use.invoke(); root.update()
        assert float(d._beta_mach_var.get()) == 12.0
    finally:
        d.destroy()
