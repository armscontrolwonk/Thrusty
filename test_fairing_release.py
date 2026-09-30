"""Fairing release is reported on every flight that carries a fairing.

The contract:
  * a separating reentry object flies free from final burnout, so the fairing
    cannot outlast separation — when the jettison rule (heating criterion or
    altitude override) has not fired by then, the timeline reports the fairing
    released AT separation and says which rule was not met, instead of staying
    silent or reporting a jettison the dynamics never honoured;
  * a rule that fires during boost is reported as before;
  * this is reporting only: two flights that both carry the fairing to
    separation fly the same trajectory whatever the rule was.

The flight plan is written out here rather than read from a plan file, and the
flights are cached by a plain function called from inside each test (not a
module-scoped fixture, which would run before conftest blanks the user
library paths).
"""

import functools

import numpy as np
import pytest

from booster_models import get_booster, apply_flight_plan, total_burn_time
from trajectory import integrate_trajectory


@functools.lru_cache(maxsize=None)
def _fly(jettison_alt_km, stage2_angle_deg=0.0):
    """Shipped AUR on a depressed boost-glide profile.  With the second stage
    flown flat the apogee stays below 100 km, two orders of magnitude in flux
    short of the heating criterion; at 10 deg it is met, but only in the coast
    after separation."""
    plan = {
        'guidance': 'pitch_program', 'burnout_angle_deg': 25.0,
        'launch_elevation_deg': 90.0,
        'shroud_jettison_alt_km': jettison_alt_km,
        'stages': [
            {'stage_turn_start_s': 0.0, 'stage_turn_stop_s': 15.0,
             'stage_burnout_angle_deg': 25.0},
            {'stage_turn_start_s': 57.0, 'stage_turn_stop_s': None,
             'stage_burnout_angle_deg': stage2_angle_deg},
        ],
    }
    p = apply_flight_plan(get_booster("AUR"), plan)
    return p, integrate_trajectory(p, 13.5, 144.8, 300.0, gt_turn_start_s=0.0)


def _release_row(r):
    rows = [m for m in r['milestones']
            if m['event'].startswith("Fairing") and not m.get('is_debris')]
    assert len(rows) == 1
    return rows[0]


def test_heating_rule_never_met_is_reported_at_separation():
    p, r = _fly(0.0)
    row = _release_row(r)
    assert row['event'].startswith("Fairing released at separation (")
    assert "heating criterion never met" in row['event']
    assert row['t_s'] == pytest.approx(total_burn_time(p))


def test_heating_rule_met_after_separation_is_reported_at_separation():
    p, r = _fly(0.0, stage2_angle_deg=10.0)
    row = _release_row(r)
    assert row['event'].startswith("Fairing released at separation (")
    assert "heating criterion not met until" in row['event']
    assert row['t_s'] == pytest.approx(total_burn_time(p))


def test_altitude_never_reached_is_reported_at_separation():
    p, r = _fly(500.0)
    row = _release_row(r)
    assert row['event'].startswith("Fairing released at separation (")
    assert "500 km jettison altitude never reached" in row['event']
    assert row['t_s'] == pytest.approx(total_burn_time(p))


def test_released_fairing_gets_its_debris_arc():
    _, r = _fly(0.0)
    assert 'Fairing' in [d['label'] for d in r['debris_trajectories']]
    assert any(m['event'].startswith("Fairing impact")
               for m in r['milestones'])


def test_rule_met_during_boost_is_reported_as_jettison():
    p, r = _fly(20.0)
    row = _release_row(r)
    assert row['event'].startswith("Fairing jettison (")
    assert row['t_s'] < total_burn_time(p)
    assert row['alt_km'] == pytest.approx(20.0, abs=0.5)


def test_reporting_does_not_move_the_trajectory():
    # Both flights carry the fairing to separation; only the label differs.
    _, a = _fly(0.0)
    _, b = _fly(500.0)
    assert np.array_equal(np.asarray(a['pos_ecef']), np.asarray(b['pos_ecef']))
