"""The handoff at separation (FRONT_END_DESIGN.md Part IV).

At separation the booster hands off to the reentry object in both kinds of
vehicle.  Separating: the object as stored flies on.  Non-separating
(`body_reenters`): the object is populated with what actually reenters, the
last stage, and that flies on.  These tests pin the invariants the handoff
must keep; those marked xfail describe work in later phases and turn into
failures (strict) the moment that work makes them pass, so the mark must be
removed with it.
"""

import copy
import dataclasses as dc
import json

import numpy as np
import pytest

import booster_models as bm
import trajectory as tr

SCUD = 'booster_library/Scud-B_-R-17-.booster.json'
SCUD_RO = 'ro_library/Scud-B_warhead.ro.json'
NODONG_RO = 'ro_library/No-dong_warhead.ro.json'


def _booster(path=SCUD, **kw):
    p = bm.booster_from_dict(json.load(open(path)))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _object(path=SCUD_RO, **kw):
    return dc.replace(bm.ro_from_dict(json.load(open(path))), **kw)


def _compose(p, ro):
    p = copy.deepcopy(p)
    p.ro = ro
    q = bm.compose_loadout(p, ro, 1)
    q.ro = ro
    return q


def _fly(p, ro):
    return tr.integrate_trajectory(_compose(p, ro), 33.0, 44.0, 90.0)


def _after_separation(res, p):
    """Masses sampled from 5 s after separation to 5 s before impact: the
    whole reentry arc, not an endpoint."""
    t = np.asarray(res['t'])
    t_sep = bm.total_burn_time(p)
    m = np.asarray(res['mass'])[(t > t_sep + 5.0) & (t < t[-1] - 5.0)]
    assert m.size > 10
    return m


# ── invariants that hold today ─────────────────────────────────────────────
def test_a_body_flies_identically_with_its_stored_size_zeroed():
    """The handoff, not the file, supplies a body's mass, diameter and
    length: zeroing the stored copies changes nothing that flies."""
    a = _fly(_booster(), _object())
    b = _fly(_booster(), _object(mass_kg=0.0, diameter_m=0.0, length_m=0.0))
    for k in ('t', 'pos_ecef', 'mass'):
        assert np.array_equal(a[k], b[k]), k
    assert a['range_km'] == b['range_km']


def test_a_body_carries_the_last_stage_burnout_mass_plus_its_payload():
    """Not the object's stored mass_kg, and not the stack plus the object
    (the 574 -> 137 km double count)."""
    p = _booster()
    ro = _object(mass_kg=12345.0)                  # a stored mass is ignored
    q = _compose(p, ro)
    last = q
    while last.stage2 is not None:
        last = last.stage2
    burnout = last.mass_initial - last.mass_propellant
    assert burnout == pytest.approx(
        p.mass_initial - p.mass_propellant + ro.payload_kg)
    m = _after_separation(_fly(p, ro), q)
    assert np.allclose(m, burnout, rtol=1e-9)


def test_a_separating_object_carries_its_own_mass():
    p = _booster(body_reenters=False)
    ro = _object(NODONG_RO)
    q = _compose(p, ro)
    m = _after_separation(_fly(p, ro), q)
    assert np.allclose(m, ro.mass_kg, rtol=1e-9)


# ── the pairing rule (Part IV §18.2): Phase 2 ──────────────────────────────
@pytest.mark.xfail(strict=True, reason="Part IV Phase 2: pairing rule")
@pytest.mark.parametrize('field, value', [('beta_kg_m2', 0.0),
                                          ('mass_kg', 0.0)])
def test_an_object_sized_by_the_booster_cannot_separate(field, value):
    """β 0 means "derive from the booster" and mass 0 means "from booster":
    on a booster that separates there is nothing to derive from.  Today this
    flies (β 0 is infinite drag: 15.5 km) without a word."""
    ro = _object(**{'beta_kg_m2': 5000.0, **{field: value}})
    with pytest.raises(ValueError, match=field):
        _fly(_booster(body_reenters=False), ro)


@pytest.mark.xfail(strict=True, reason="Part IV Phase 1-2: run reports")
def test_a_stored_size_ignored_by_a_body_is_reported():
    res = _fly(_booster(), _object(length_m=3.0))
    notes = ' '.join(res.get('handoff', {}).get('notices', []))
    assert 'length_m' in notes and 'ignored' in notes
