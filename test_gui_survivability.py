"""Reentry Survivability TAB — the render path the headless tests never reach.

`survivability_report.build_report()` is pure text assembly and is covered by
test_report_lead / test_survival_map / test_arc_descriptors.  Everything
BETWEEN that string and the user's eye lives in `thrusty.py` and needs a real
Tk: the tier tag on the headline, the pixel tab stops that keep the survival
map's columns aligned when bold cells break character-grid alignment
(macOS font metrics — the bug that produced the "table's spacing is messed
up" screenshot), the per-cell colorization spans, and the ballistic-only
sweep-context gate.

Skips cleanly where tkinter is unavailable.  To run it in a container whose
default interpreter was built without Tk, point at one that has it:

    xvfb-run -a /usr/bin/python3.12 -m pytest test_gui_survivability.py -q

On a normal desktop install `pytest test_gui_survivability.py` just works.
"""

import copy
import json

import pytest

pytest.importorskip("tkinter", reason="no Tk in this interpreter")

import matplotlib
matplotlib.use("Agg")

import thrusty


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def app():
    tk = pytest.importorskip("tkinter")
    try:
        a = thrusty.BoosterFlyoutApp()
    except tk.TclError as e:                     # no display
        pytest.skip(f"no display: {e}")
    a.withdraw()
    yield a
    a.destroy()


def _fly(ro_name, booster, **patch):
    from booster_models import (get_booster, ro_from_dict, apply_reentry_plan,
                                load_reentry_plan)
    from trajectory import integrate_trajectory
    ro = ro_from_dict(json.load(open(f"ro_library/{ro_name}.ro.json")))
    rp = load_reentry_plan(ro_name)
    if rp is not None:
        ro = apply_reentry_plan(ro, rp)
    p = get_booster(booster)
    p.ro = copy.deepcopy(ro)
    r = integrate_trajectory(p, 0.0, 0.0, 90.0, max_time_s=6000.0,
                             dt_output=2.0)
    r["heating_arc"]["profile"].update(patch)
    return r


_RUNS = {}


def _run(key, *a, **kw):
    if key not in _RUNS:
        _RUNS[key] = _fly(*a, **kw)
    return copy.deepcopy(_RUNS[key])


def _ballistic():
    return _run("b", "Mk21", "Generic ICBM")


def _glider():
    return _run("g", "C-HGB", "AUR")


def _render(app, result):
    app._populate_survivability(result)
    return app._surv_text.get("1.0", "end")


# ── the tab renders at all, for both judgement models ───────────────────────
def test_tab_renders_both_forms(app):
    for r in (_ballistic(), _glider()):
        txt = _render(app, r)
        assert len(txt) > 500
        assert "═══ Full analysis" in txt


def test_headline_carries_its_tier_tag(app):
    """The tier tag is what colors the headline; a form-keyed regression that
    left `tier` None would render the verdict in body text."""
    for r, want in ((_ballistic(), "experience"), (_glider(), "beyond")):
        _render(app, r)
        assert want in app._surv_text.tag_names("1.0"), \
            f"headline missing the {want} tier tag"


# ── survival map: tab stops + colorization spans ────────────────────────────
def test_every_tabbed_map_row_gets_pixel_tab_stops(app):
    """Space padding drifts when bold cells don't share the regular font's
    metrics, so the map is tab-separated with measured pixel tab stops.  Every
    tabbed line of the block must carry the `mapgrid` tag or its columns walk."""
    for r in (_ballistic(), _glider()):
        _render(app, r)
        idx = app._surv_text.search("─── Survival map", "1.0")
        assert idx, "survival map block did not render"
        ln, rows = int(idx.split(".")[0]) + 1, 0
        while "\t" in app._surv_text.get(f"{ln}.0", f"{ln}.end"):
            assert "mapgrid" in app._surv_text.tag_names(f"{ln}.0"), \
                f"tabbed map row {ln} has no tab stops"
            rows += 1
            ln += 1
        assert rows >= 3, "expected at least the header + two station rows"


def test_map_spans_land_on_live_cell_text(app):
    """Colorization spans are (line-in-block, c0, c1, tier), self-locating off
    the map header.  Each must resolve to non-blank text inside its own line."""
    import survivability_report as sr
    r = _glider()
    rep = sr.build_report(r)
    _render(app, r)
    base = int(app._surv_text.search("─── Survival map", "1.0").split(".")[0])
    assert rep.get("map_spans")
    for ln, c0, c1, tier in rep["map_spans"]:
        cell = app._surv_text.get(f"{base + ln}.{c0}", f"{base + ln}.{c1}")
        assert cell.strip(), f"span {(ln, c0, c1)} landed on blank text"
        assert f"map_{tier}" in app._surv_text.tag_names(f"{base + ln}.{c0}")


# ── the trigger-gated blocks, as the user actually sees them ────────────────
def test_blocks_follow_their_own_triggers_in_the_rendered_tab(app):
    """The GUI-side confirmation of test_arc_descriptors: a ballistic RV shows
    none of the glide blocks, a glider shows the two that need no dive, and
    commanding a dive adds the third."""
    BLOCKS = ("Windward-flank heating", "Terminal-dive transient",
              "Maneuver-load anchors")
    txt = _render(app, _ballistic())
    assert not any(b in txt for b in BLOCKS)

    txt = _render(app, _glider())
    assert "Windward-flank heating" in txt
    assert "Maneuver-load anchors" in txt
    assert "Terminal-dive transient" not in txt

    txt = _render(app, _fly("C-HGB", "AUR", terminal_alt_km=15.0))
    assert "Terminal-dive transient" in txt


def test_headline_descriptors_reach_the_widget(app):
    txt = _render(app, _fly("C-HGB", "AUR", banking=True,
                            terminal_alt_km=15.0))
    head = txt.splitlines()[0]
    assert "glide · banking · terminal dive" in head
    assert "Form " not in head


# ── the ballistic-only sweep-context gate (thrusty.py) ──────────────────────
def test_sweep_context_is_ballistic_only(app):
    """`rep['form'] == 'ballistic'` gates this block — the sole consumer of the
    report's form outside survivability_report.py, and the line the headless
    tests cannot reach."""
    sweep = dict(booster="Generic ICBM", param="Burnout angle", unit="°",
                 rows=[(30.0, 0, 0, 12.0, 250.0), (45.0, 0, 0, 18.0, 190.0)])
    app._last_heating_sweep = sweep
    app._booster_var.set("Generic ICBM")
    assert "Sweep context" in _render(app, _ballistic())

    app._last_heating_sweep = dict(sweep, booster="AUR")
    app._booster_var.set("AUR")
    assert "Sweep context" not in _render(app, _glider())

    app._last_heating_sweep = None


# ── Schematic tab (lives here to reuse the app fixture) ─────────────────────
def test_schematic_tab_exists_and_tracks_booster_switch(app):
    """The Schematic tab must be present in the right notebook and its axes
    must redraw when the sidebar booster changes — the live-panel contract."""
    tabs = [app._right_nb.tab(t, "text") for t in app._right_nb.tabs()]
    assert any("Schematic" in t for t in tabs)
    assert hasattr(app, "_schem_ax")

    app._booster_var.set("Strypi VIII R")
    app._on_booster_changed()
    n_strypi = len(app._schem_ax.patches)
    t_strypi = app._schem_ax.get_title()

    app._booster_var.set("No-dong")
    app._on_booster_changed()
    n_nodong = len(app._schem_ax.patches)
    t_nodong = app._schem_ax.get_title()

    assert n_strypi > 0 and n_nodong > 0
    # Strypi carries fins + strap-ons; No-dong is a plain single stack.
    assert n_strypi > n_nodong
    assert "Strypi" in t_strypi and "No-dong" in t_nodong


def test_schematic_title_gives_the_vehicle_length_not_just_the_stack(app):
    """An uncovered separating object is drawn beside the stack, not on it,
    so the stack alone is short of the vehicle: the headline must be the
    vehicle's length and say it is stack + object (numbers from the core)."""
    import booster_models as mm
    import booster_schematic as bsch
    from matplotlib.figure import Figure
    p = mm.booster_from_dict(json.load(
        open("booster_library/Strypi_VIII_R.booster.json")))
    ro = mm.ro_from_dict(json.load(open("ro_library/C-HGB.ro.json")))
    p = mm.compose_loadout(p, ro, 1)
    p.ro = ro
    app._update_schematic(p, "Probe")
    head, sub = app._schem_ax.get_title().splitlines()
    info = bsch.draw_booster(Figure().add_subplot(111), p)
    assert head.endswith(f"{info['overall_length_m']:.1f} m")
    assert sub == (f"{info['total_height_m']:.1f} m stack + "
                   f"{info['front_object_length_m']:.1f} m object")
    p.ro = None                                 # nothing beside: one line
    app._update_schematic(p, "Probe")
    assert "\n" not in app._schem_ax.get_title()


# ── Booster Parameters Front-End: guidance is sourced from the live plan ────
def test_front_end_guidance_tracks_reentry_plan_not_object_default(app):
    """The Front End "Guidance:" row is a reentry-PLAN choice, so switching the
    sidebar glide law must change the Booster Parameters panel — it must not be
    pinned to the object's baked-in glider_guidance."""
    app._booster_var.set("AUR")
    app._on_booster_changed()
    # Compose a glider reentry object via the sidebar loadout (boosters no
    # longer embed one), so the Front End has a glide row to source.
    app._ro_main_var.set("C-HGB")

    def _front_end_texts():
        texts = []
        for lf in app._params_inner.winfo_children():
            if getattr(lf, "cget", None) and lf.winfo_class() == "TLabelframe" \
                    and lf.cget("text") == "Front End":
                for w in lf.winfo_children():
                    if w.winfo_class() == "TLabel":
                        texts.append(w.cget("text"))
        return texts

    app._main_guidance_var.set("Damped phugoid glide")
    app._update_params_display()
    assert "Damped phugoid glide" in _front_end_texts()

    app._main_guidance_var.set("Equilibrium glide (Tracy)")
    app._update_params_display()
    fe = _front_end_texts()
    assert "Equilibrium glide (Tracy)" in fe
    assert "Damped phugoid glide" not in fe

    # Ballistic hides the glide row entirely (no glider L/D or guidance line).
    app._main_guidance_var.set("Ballistic (drag · gravity · rotation)")
    app._update_params_display()
    assert not any("Guidance" in t for t in _front_end_texts())
