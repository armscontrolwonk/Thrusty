"""Max Range coordinate-descent search matches the full 2-D grid.

maximize_range used to evaluate the full Cartesian product of the Wheelon
burnout-angle window and the turn-stop candidate list — ~200 trajectories that,
with the GIL-bound EOM defeating the ThreadPool, ran essentially serially and
were the whole "runs forever" cost of a Max Range click.

It now runs a coordinate descent seeded at the Wheelon-optimal angle (sweep
turn-stop along it, then angle at the best turn-stop, then turn-stop at the best
angle) plus the existing Phase-2 angle polish — ~1/4 the trajectories.  These
tests pin that the descent lands on the same optimum as the exhaustive grid
(within the grid's own 2°/2 s granularity) so the speedup never costs range.
"""

import copy
import math

import numpy as np
import pytest

import trajectory as T
from booster_models import (get_booster, load_booster_library, ROParams,
                            compose_loadout)
from trajectory import (maximize_range, _search_one, _wheelon_gamma_opt,
                        _tsiolkovsky_dv, total_burn_time)

load_booster_library()


def _full_grid_best(params, lat, lon, az):
    """The exhaustive (burnout_angle × turn_stop) optimum — the old behaviour,
    reproduced here as the reference the descent must match."""
    total_burn = total_burn_time(params)
    _dv = _tsiolkovsky_dv(params)
    _v = max(1000.0, _dv * 0.82 - 300.0)
    _g = _wheelon_gamma_opt(_v)
    lo, hi = max(5.0, _g - 10.0), min(80.0, _g + 10.0)
    cutoff = total_burn
    ts_min = 5.0 + 5.0
    early = [ts_min + 2.0 * i
             for i in range(int((min(40.0, cutoff) - ts_min) / 2.0) + 1)]
    late = [45.0, 60.0, 90.0, min(120.0, cutoff),
            min(180.0, cutoff), cutoff]
    ts_c = sorted({t for t in early + late if ts_min <= t <= cutoff})
    common = (params, lat, lon, az, params.guidance, cutoff, 5.0, 3600.0,
              False, None)
    best = -1.0
    for ba in np.arange(lo, hi + 1.0, 2.0):
        for ts in ts_c:
            r = _search_one((float(ba), ts, *common))
            if r > best:
                best = r
    return best


def _body_glider():
    """A lofted non-separating body glider — the coupled case whose optimum
    sits at a long turn-stop, defeating a short-turn-stop seed."""
    base = copy.deepcopy(get_booster("Scud-B (R-17)"))
    base.body_reenters = True
    base.guidance = "pitch_program"
    _last = base
    while getattr(_last, 'stage2', None) is not None:
        _last = _last.stage2
    ro = ROParams(name="fe", mass_kg=max(float(_last.mass_final), 1.0),
                  beta_kg_m2=0.0, shape="cone",
                  diameter_m=float(_last.diameter_m),
                  length_m=float(_last.length_m), separation_mode='body',
                  glider_enabled=True, glider_LD=0.0,
                  glider_guidance="damped_glide")
    p = compose_loadout(base, ro, 1)
    p.ro = ro
    return p


def _flat(name):
    p = copy.deepcopy(get_booster(name))
    p.guidance = "pitch_program"
    return p


@pytest.mark.parametrize("factory", [
    lambda: _flat("Scud-B (R-17)"),   # flat single-stage
    _body_glider,                     # lofted coupled body glider (long ts)
])
def test_descent_matches_full_grid(factory):
    p = factory()
    ref = _full_grid_best(p, 39.0, 125.0, 90.0)
    assert ref > 0.0
    got = maximize_range(p, 39.0, 125.0, 90.0)["max_range_km"]
    assert got is not None
    # Within 1.5 % of the exhaustive grid — the descent may differ only by the
    # grid's own turn-stop granularity, never by a missed basin.  (Phase 2
    # polishes the angle, so the descent often beats the raw grid.)
    assert got >= ref * 0.985, f"descent {got:.1f} vs grid {ref:.1f}"


def test_fixed_turn_stop_still_sweeps_angle():
    """A user-fixed turn-stop takes the single-line branch: the angle is still
    optimised, and the result is a valid range."""
    p = _flat("Scud-B (R-17)")
    r = maximize_range(p, 39.0, 125.0, 90.0, gt_turn_stop_s=30.0)
    assert r["max_range_km"] > 0.0
    assert r["optimal_gt_turn_stop_s"] == 30.0


# ── the stall guard ─────────────────────────────────────────────────────────

def test_a_stalled_run_raises_instead_of_hanging():
    """An adaptive step cannot always cross a sharp change in the derivative.
    If the vehicle sits on one rather than passing through it, the step size
    collapses and the run never ends -- no error, no progress, and in the GUI
    a frozen window.  Strypi VII R does exactly that: it reaches Mach 1.001 at
    1.4 km and stays there, taking 459 s to fly what its near-identical
    sibling flies in 0.22 s.  Raise instead, with the stall point named."""
    from trajectory import IntegratorStalled, integrate_trajectory
    import booster_models as bm
    bm.load_booster_library()
    with pytest.raises(IntegratorStalled) as exc:
        integrate_trajectory(bm.get_booster("Strypi VII R"), 40.0, 40.0, 90.0,
                             max_time_s=3600.0)
    msg = str(exc.value)
    assert "stopped advancing" in msg
    assert "Mach" in msg and "evaluations" in msg


def test_the_guard_leaves_healthy_vehicles_alone():
    """The threshold has to sit far above normal behaviour.  Every shipped
    vehicle that flies normally stays under 250 consecutive evaluations
    without advancing; the limit is 50,000."""
    import booster_models as bm
    from trajectory import integrate_trajectory
    bm.load_booster_library()
    for name in ("No-dong", "Scud-B (R-17)", "AUR", "Taepodong-II",
                 "Strypi VIII R"):
        r = integrate_trajectory(bm.get_booster(name), 40.0, 40.0, 90.0,
                                 max_time_s=3600.0)
        assert r["range_km"] > 0, name


def test_the_guard_can_be_switched_off():
    """Someone who would rather wait keeps the option.  Proved on behaviour
    rather than internals: a deliberately tiny limit trips on a healthy
    vehicle, and zero lets that same vehicle finish."""
    from trajectory import IntegratorStalled, integrate_trajectory
    import booster_models as bm
    bm.load_booster_library()
    with pytest.raises(IntegratorStalled):
        integrate_trajectory(bm.get_booster("Scud-B (R-17)"), 40.0, 40.0, 90.0,
                             max_time_s=600.0, stall_evals=10)
    r = integrate_trajectory(bm.get_booster("Scud-B (R-17)"), 40.0, 40.0, 90.0,
                             max_time_s=600.0, stall_evals=0)
    assert r["range_km"] > 0
