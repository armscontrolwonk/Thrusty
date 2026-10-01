"""Smoke tests for the two dynamic glide modes (see DAMPED_GLIDE.md and
GLIDE_CAPTURE_DESIGN.md).  Both remove the old "free lift" (drag is coupled to
the actual commanded lift, lift bounded by the aerodynamic ceiling):

  damped_glide              — NOMINAL = max-L/D α* (skip) lift + ζ altitude-rate
                              damping.  Preserves the phugoid, so ζ genuinely
                              DAMPS the skips: ζ=0 ≡ skip_glide (undamped), larger
                              ζ → fewer/smaller decaying skips into equilibrium.
  dynamic_equilibrium_glide — NOMINAL = equilibrium trim m·(g − V²/r); captures
                              SMOOTHLY (no oscillation).  ζ is a tracking gain.

Both PLUNGE an uncapturable (lofted) entry; capturability is entry-geometry
dependent (read off by glide_regime.py).

Run:  python damped_glide_smoke_test.py        (needs numpy + scipy)

RE-ANCHORING NOTE (2026-07-30).  These anchors were calibrated with the
then-default 30 km terminal handoff.  Commit db73fa1 (2026-07-10) changed the
default glider_terminal_alt_km to 0 = glide-to-impact (and updated the shipped
reentry plans), which let the marginal lofted case keep flying — verdict
drifted plunge→skip and the ζ=0 re-climb crossed the 60 km line — and the two
tests sat failing (deselected) until bisected to that commit.  The fixtures
now PIN glider_terminal_alt_km explicitly, so the anchors are tied to their
calibration point rather than to a shippable default that may move again.
The ζ=0 ≡ skip_glide identity is asserted with the dive OFF: the two modes'
dive handoff differs by one output sample (discretization, not physics).
"""

import copy
import dataclasses
import json

import numpy as np

from booster_models import get_booster, ro_from_dict, ro_to_dict, effective_ro
from trajectory import integrate_trajectory
from glide_regime import regime_from_result

_BOOSTER = "Minotaur-IV + HTV-2"
_CHGB = ro_from_dict(json.load(open("ro_library/C-HGB.ro.json")))
# Reentry-object files are hardware-only; apply the shipped reentry plan.
from booster_models import apply_reentry_plan as _arp, load_reentry_plan as _lrp
_rp = _lrp("C-HGB")
if _rp is not None:
    _CHGB = _arp(_CHGB, _rp)
# The former AUR+HGB variant flew a distinct "HGB" glide body (⌀0.8, L 2.0, L/D 1.8) that used
# to be embedded in the booster JSON.  Boosters no longer embed reentry objects,
# so reconstruct it here as a test fixture (same β and mass as C-HGB; only the
# glide-relevant geometry / L/D differ) for the AUR capture cases below.
_HGB = dataclasses.replace(_CHGB, name="HGB", diameter_m=0.8, length_m=2.0,
                           nose_radius_m=0.0, glider_LD=1.8,
                           glider_beta_entry_kg_m2=7.0)
_CUTOFF = 170.0


def _fly(mode, zeta=None, aero="polar", cutoff=_CUTOFF):
    """Lofted sub-circular C-HGB entry (steep → uncapturable)."""
    p = get_booster(_BOOSTER)
    ro = copy.deepcopy(_CHGB)
    ro.glider_guidance, ro.glider_aero_model = mode, aero
    # Pin the terminal handoff these anchors were calibrated at (30 km).  The
    # shipped default changed to 0 = glide-to-impact (db73fa1, 2026-07-10),
    # which let the marginal lofted case keep flying (skip, 67 km re-climb)
    # instead of plunging — pinning the knob here keeps the fixtures at their
    # original operating point regardless of future default drift.
    ro.glider_terminal_alt_km = 30.0
    if zeta is not None:
        ro.glider_damping_zeta = zeta
    # Pin the boosted front-end mass these anchors were calibrated at.  The
    # Minotaur-IV + HTV-2 booster file used to bake its 1000 kg HTV-2 payload
    # into the stage masses, so this fixture flew a 1000 kg front end while
    # reentering as the 450 kg C-HGB.  Booster files are now stack-only and
    # integrate_trajectory composes the flown object's own mass (2fe10e6),
    # which made the stack 550 kg lighter at burnout and let the marginal
    # lofted case capture instead of plunging.  Carry the difference as bus
    # mass so the boost stays at the anchors' operating point.
    p.bus_mass_kg = 1000.0 - ro.mass_kg
    p.ro = ro
    r = integrate_trajectory(p, 0.0, 0.0, 90.0, max_time_s=8000.0,
                             dt_output=2.0, cutoff_time_s=cutoff)
    return r, ro


def _fly_aur_shallow(mode, zeta=None, aero="polar", terminal_alt_km=30.0):
    """AUR on a depressed (shallow) insertion — capturable (adv-pitch program:
    stage 1 → 27°, stage 2 → 0° flat, launch elev 80°, az 103°, cutoff 117 s)."""
    p = copy.deepcopy(get_booster("AUR"))
    # Pin the carrier's propulsion at the anchors' operating point.  The
    # shipped AUR became a solid with a regressive (double-anchor) stage-1
    # grain on 2026-10-01 (a data correction from the user); on this program
    # that stack burns out slower and no longer reaches the skip regime these
    # anchors were calibrated in (less speed at burnout, so the shallow
    # insertion plunges instead of skipping).  The test is about the glider's damping
    # law, not AUR, so it keeps flying the constant-thrust stack.
    for s in (p, p.stage2):
        s.grain_type, s.thrust_peak_N = "", 0.0
    p.stage_turn_start_s, p.stage_turn_stop_s, p.stage_burnout_angle_deg = 1.0, 30.0, 27.0
    if getattr(p, "stage2", None) is not None:
        p.stage2.stage_turn_start_s = 54.0
        p.stage2.stage_turn_stop_s = 90.0
        p.stage2.stage_burnout_angle_deg = 0.0
    p.launch_elevation_deg = 80.0
    # Compose the reentry object explicitly (boosters no longer embed one).
    ro = copy.deepcopy(_HGB)
    ro.glider_guidance, ro.glider_aero_model = mode, aero
    ro.glider_terminal_alt_km = terminal_alt_km   # pinned; see _fly
    if zeta is not None:
        ro.glider_damping_zeta = zeta
    p.ro = ro
    r = integrate_trajectory(p, 28.458, -80.5286, 103.0, guidance="pitch_program",
                             burnout_angle_deg=25.0, cutoff_time_s=117.0,
                             gt_turn_start_s=5.0, launch_elevation_deg=80.0,
                             max_time_s=8000.0, dt_output=2.0)
    return r, ro


def _alt(r):
    return np.asarray(r["alt"]).ravel() / 1000.0


def _range_km(r):
    return float(np.asarray(r["range"]).ravel()[-1] / 1000.0)


def _reclimb_km(r):
    a = _alt(r)
    post = a[int(np.argmax(a)):]
    return float(np.max(post - np.minimum.accumulate(post))) if len(post) else 0.0


# --------------------------------------------------------------------------
def test_serialization_roundtrip():
    for mode in ("damped_glide", "dynamic_equilibrium_glide"):
        ro = copy.deepcopy(_CHGB)
        ro.glider_guidance, ro.glider_damping_zeta = mode, 0.55
        ro2 = ro_from_dict(ro_to_dict(ro))
        assert ro2.glider_guidance == mode
        assert abs(ro2.glider_damping_zeta - 0.55) < 1e-9
    print("  ok  serialization round-trip (both modes)")


def test_damped_nests_to_skip_glide():
    # damped_glide ζ=0 reduces exactly to skip_glide (α* lift, no feedback).
    # Asserted on the PURE glide (terminal dive off): the identity is about
    # the glide law, and the two modes' 30-km dive HANDOFF differs by one
    # output sample (same dive, ±dt_output discretization — not physics).
    a_s, _ = _fly_aur_shallow("skip_glide", terminal_alt_km=0.0)
    a_d, _ = _fly_aur_shallow("damped_glide", zeta=0.0, terminal_alt_km=0.0)
    s, d = _alt(a_s), _alt(a_d)
    n = min(len(s), len(d))
    dmax = float(np.max(np.abs(s[:n] - d[:n])))
    assert len(s) == len(d) and dmax < 1e-9, f"ζ=0 not identical to skip_glide (max|Δ|={dmax})"
    print("  ok  damped_glide ζ=0 ≡ skip_glide (max|Δalt|=%.1e km)" % dmax)


def test_damped_decaying_skips():
    # Increasing ζ damps the phugoid: the skip amplitude (max re-climb) falls
    # monotonically toward zero.
    climbs = [_reclimb_km(_fly_aur_shallow("damped_glide", zeta=z)[0])
              for z in (0.0, 0.4, 0.7, 2.0)]
    assert climbs[0] > climbs[1] > climbs[2] >= climbs[3], f"skips not decaying: {climbs}"
    assert climbs[0] > 20.0 and climbs[3] < 1.0, f"endpoints off: {climbs}"
    print("  ok  damped_glide decaying skips: re-climb %s km (ζ=0→2)" %
          " → ".join(f"{c:.0f}" for c in climbs))


def test_damped_no_free_lift():
    # A captured damped glide must not out-range a true equilibrium glide.
    eq = _range_km(_fly_aur_shallow("equilibrium_glide", aero="constant_LD")[0])
    for z in (0.7, 1.0, 2.0):
        d = _range_km(_fly_aur_shallow("damped_glide", zeta=z, aero="constant_LD")[0])
        assert d <= eq * 1.02, f"ζ={z}: damped {d:.0f} > equilibrium {eq:.0f} (free lift!)"
    print(f"  ok  damped_glide no free lift (≤ equilibrium {eq:.0f} km)")


def test_lofted_plunges_both_modes():
    for mode in ("damped_glide", "dynamic_equilibrium_glide"):
        for aero in ("polar", "constant_LD"):
            r, ro = _fly(mode, zeta=0.7, aero=aero)
            g = regime_from_result(r, ro=ro)
            assert g.verdict == "plunge", f"{mode}/{aero} lofted: expected plunge, got {g}"
    print("  ok  lofted entry plunges (both modes, both aero)")


def test_dyneq_captures_smoothly():
    # dynamic_equilibrium_glide captures the shallow insertion with NO skips
    # (smooth) and no free lift.
    eq = _range_km(_fly_aur_shallow("equilibrium_glide", aero="polar")[0])
    r, ro = _fly_aur_shallow("dynamic_equilibrium_glide", zeta=0.7, aero="polar")
    g = regime_from_result(r, ro=ro)
    assert g.verdict == "capture", f"dyn-eq should capture, got {g}"
    assert _reclimb_km(r) < 1.0, "dyn-eq should capture smoothly (no climb)"
    assert _range_km(r) <= eq * 1.02, "dyn-eq exceeds equilibrium (free lift!)"
    print(f"  ok  dynamic_equilibrium_glide smooth capture ({_range_km(r):.0f} km, no climb)")


def test_no_zoom_climb():
    # No post-apogee zoom-climb — check the *capturing* shallow insertion (where
    # the β-cap must prevent the m·g_eff zoom for constant_LD) and the lofted boost.
    for fly in (_fly, _fly_aur_shallow):
        for mode in ("damped_glide", "dynamic_equilibrium_glide"):
            for aero in ("polar", "constant_LD"):
                for z in (0.0, 0.7, 2.0):
                    r, _ = fly(mode, zeta=z, aero=aero)
                    rc = _reclimb_km(r)
                    # damped_glide legitimately skips at low ζ (decaying phugoid);
                    # only flag a *runaway* zoom (> 60 km) there.  dyn-eq must be
                    # monotonic (< 1 km).
                    lim = 60.0 if mode == "damped_glide" else 1.0
                    assert rc < lim, f"{fly.__name__} {mode}/{aero} ζ={z}: re-climb {rc:.1f} km"
    print("  ok  no runaway zoom-climb (damped skips bounded; dyn-eq monotonic)")


def main():
    tests = [
        test_serialization_roundtrip,
        test_damped_nests_to_skip_glide,
        test_damped_decaying_skips,
        test_damped_no_free_lift,
        test_lofted_plunges_both_modes,
        test_dyneq_captures_smoothly,
        test_no_zoom_climb,
    ]
    for t in tests:
        t()
    print(f"\n{len(tests)}/{len(tests)} glide-mode checks passed.")


if __name__ == "__main__":
    main()
