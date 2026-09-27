"""fairing_fit: the payload-vs-front-end containment warning.

House rules: identities against stored fields (a length overrun is
arithmetic, not eyeball), fallbacks surface in the result rather than
hiding, a fitting payload stays silent, and with no fairing there is
nothing to fit inside."""

import json
import math

import pytest

import fairing_fit as ff
from booster_models import BoosterParams, booster_from_dict, ro_from_dict
from booster_schematic import stage_chain


def _stage(name, dia, length, **kw):
    p = BoosterParams(name=name, mass_initial=1000.0, mass_propellant=800.0,
                      mass_final=200.0, diameter_m=dia, length_m=length,
                      thrust_N=1e5, burn_time_s=60.0, isp_s=250.0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _load_booster(name):
    return booster_from_dict(
        json.load(open(f"booster_library/{name}.booster.json")))


def _load_ro(name):
    return ro_from_dict(json.load(open(f"ro_library/{name}.ro.json")))


def test_swerve_on_stars1_has_nothing_to_be_contained_in():
    """The motivating case, retired 2026-09-27: SWERVE on STARS-1 declares NO
    fairing, so the object is the front end — drawn beside the stack, with no
    nose stacked for it to overrun (booster_schematic.exposed_front_object).
    Checking it against an invented 1.6×⌀ cone was a verdict on a drawing
    nobody flies, so no check applies."""
    veh = _load_booster("STARS-1")
    assert all(not (s.shroud_length_m or 0) for s in stage_chain(veh))
    veh.ro = _load_ro("SWERVE")
    assert ff.fairing_fit(veh) is None
    assert ff.fairing_fit_note(ff.fairing_fit(veh)) == ""


def test_too_long_under_a_fairing_is_the_blunted_length_overrun():
    """Under a fairing too short for it, SWERVE overruns by exactly its
    PHYSICAL length (the blunted sphere-cone, apex identity
    L − rn/sinθ + rn — the same body the 3-D export revolves, not the
    sharp-cone reference length) minus the envelope.  Taken from the
    OBJECT: the identity holds for any dimensions, so it must not be
    re-typed as literals here.  An unset fairing nose length is stood in
    for, and the warning says so."""
    ro = _load_ro("SWERVE")
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=1.0,
                 shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh.ro = ro
    fit = ff.fairing_fit(veh)
    assert fit is not None and not fit["fits"]
    assert fit["kind"] == "fairing"
    assert fit["env_len_m"] == pytest.approx(2.0)
    th = math.atan2(ro.diameter_m / 2, ro.length_m)
    L_blunt = ro.length_m - ro.nose_radius_m / math.sin(th) + ro.nose_radius_m
    assert fit["ro_len_m"] == pytest.approx(L_blunt)
    assert fit["len_over_m"] == pytest.approx(L_blunt - 2.0)
    note = ff.fairing_fit_note(fit)
    assert "does NOT fit" in note and "too long" in note
    assert "unset" not in note                 # every dimension was declared
    veh.shroud_nose_length_m = 0.0             # now one is stood in for —
    assert "nose length unset" in ff.fairing_fit_note(ff.fairing_fit(veh))


def test_fitting_payload_stays_silent():
    """A ⌀0.4 × 1.0 m cone under a ⌀1.0 × 2.0 m fairing fits; no flag."""
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=1.0,
                 shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh.ro = ro_from_dict(dict(json.load(open("ro_library/C-HGB.ro.json")),
                               diameter_m=0.4, length_m=1.0))
    fit = ff.fairing_fit(veh)
    assert fit["fits"] and fit["kind"] == "fairing"
    assert ff.fairing_fit_note(fit) == ""


def test_radial_interference_is_caught_with_its_station():
    """A payload fatter than the fairing tube violates radially even when
    short enough; the result names the height."""
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=0.6,
                 shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh.ro = ro_from_dict(dict(json.load(open("ro_library/C-HGB.ro.json")),
                               diameter_m=0.9, length_m=1.0))
    fit = ff.fairing_fit(veh)
    assert not fit["fits"]
    assert fit["len_over_m"] == 0.0
    assert fit["max_interference_m"] == pytest.approx(0.15, abs=0.01)
    assert fit["at_z_m"] == pytest.approx(0.0, abs=0.02)
    assert "radius over" in ff.fairing_fit_note(fit)


def test_taper_matters_not_just_bounding_boxes():
    """Profile-vs-profile, not bounding boxes: under a mostly-nose
    fairing (0.2 m cylinder + 1.8 m cone nose), a slender cone RV longer
    than the cylinder still fits by tapering with the nose — a box check
    would wrongly reject it.  A blunt dome RV of the same length keeps
    its radius too long and violates RADIALLY (not by length) mid-nose."""
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=1.0,
                 shroud_nose_length_m=1.8, shroud_nose_shape="cone")
    base = json.load(open("ro_library/C-HGB.ro.json"))
    veh.ro = ro_from_dict(dict(base, diameter_m=0.5, length_m=1.9,
                               nose_radius_m=0.0))
    assert ff.fairing_fit(veh)["fits"]
    veh.ro = ro_from_dict(dict(base, shape="blunt", diameter_m=0.9,
                               length_m=1.9, nose_radius_m=0.0))
    fit = ff.fairing_fit(veh)
    assert not fit["fits"]
    assert fit["len_over_m"] == 0.0            # short enough — shape kills it
    assert fit["max_interference_m"] > 0.01
    assert 0.2 < fit["at_z_m"] < 2.0           # mid-nose, not at the base


def test_wedge_uses_the_circumscribed_cone():
    """A wedge's rectangular section must clear the circle: ⌀0.5 depth ×
    0.8 span circumscribes r = 0.5·hypot(0.5, 0.8) ≈ 0.47 — too fat for
    a ⌀0.8 tube even though each side alone would pass."""
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=0.8,
                 shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh.ro = ro_from_dict(dict(json.load(open("ro_library/C-HGB.ro.json")),
                               body_form="wedge", diameter_m=0.5,
                               body_span_m=0.8, length_m=1.0))
    fit = ff.fairing_fit(veh)
    assert not fit["fits"]
    assert fit["max_interference_m"] == pytest.approx(
        0.5 * math.hypot(0.5, 0.8) - 0.4, abs=0.01)
    assert any("circumscribed" in n for n in fit["notes"])


def test_no_check_without_an_ro_or_dims():
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0)
    assert ff.fairing_fit(veh) is None                     # no RO
    veh.ro = ro_from_dict(dict(json.load(open("ro_library/C-HGB.ro.json")),
                               diameter_m=0.0))
    assert ff.fairing_fit(veh) is None                     # RO dims unset


def test_oml_assumption_is_stated():
    """The envelope has no stored wall thickness — every result says it
    checked the outer mold line."""
    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=1.0,
                 shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh.ro = _load_ro("SWERVE")
    assert any("outer mold line" in n for n in ff.fairing_fit(veh)["notes"])


def test_schematic_and_export_surface_the_warning():
    """The schematic flags the misfit AND draws the red on-canvas warning;
    the Blender export header carries the same line.  A fitting payload
    adds nothing anywhere."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from booster_schematic import draw_booster
    import blender_export as bx

    veh = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=1.0,
                 shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh.ro = _load_ro("SWERVE")                # 2.7 m under a 2.0 m fairing
    ax = Figure(figsize=(4, 8)).add_subplot(111)
    info = draw_booster(ax, veh)
    assert any("does NOT fit" in f for f in info["flags"])
    # the canvas carries the compact one-liner (the full sentence lives
    # in the flags / export header)
    assert any(t.get_text().startswith("⚠ payload does not fit")
               for t in ax.texts)
    obj_text, obj_info = bx.obj_export(veh)
    assert any("does NOT fit" in f for f in obj_info["flags"])
    assert "does NOT fit" in obj_text                      # header comment
    # fitting case: silent
    veh2 = _stage("V", 1.0, 8.0, shroud_length_m=2.0, shroud_diameter_m=1.0,
                  shroud_nose_length_m=0.9, shroud_nose_shape="cone")
    veh2.ro = ro_from_dict(dict(json.load(open("ro_library/C-HGB.ro.json")),
                                diameter_m=0.4, length_m=1.0))
    ax2 = Figure(figsize=(4, 8)).add_subplot(111)
    info2 = draw_booster(ax2, veh2)
    assert not any("fit" in f for f in info2["flags"])
    assert not any("⚠" in t.get_text() for t in ax2.texts)
