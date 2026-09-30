"""Derived β(Mach) for a non-separating body (FRONT_END_DESIGN.md §10, P2-A).

For a unitary body the ballistic coefficient is emergent from the whole airframe,
not a free input: β = m/(Cd0_body(M)·A_base).  Leaving β at the sentinel 0 derives
a β(Mach) table (the burnout mass over the airframe Cd0 and base area), stashed
like the L/D(Mach) table and read by every drag term.  A separating RV, or a body
with β entered > 0, keeps its scalar untouched.

These tests pin:
  1. A body with β=0 derives a positive β (surfaced as result['derived_beta_kg_m2'])
     and flies with it — NOT as a zero/undefined β.
  2. The derived β uses the INHERITED burnout mass and base area (magnitude check).
  3. A body with β entered > 0 does NOT derive (keeps its scalar; no derived value).
  4. A separating RV never derives β (byte-identical to before).
"""

import numpy as np

from booster_models import (get_booster, load_booster_library, ROParams,
                            compose_loadout, effective_ro)
from trajectory import integrate_trajectory
import glider_ld

load_booster_library()


def _booster():
    p = get_booster("Scud-B (R-17)")
    p.body_reenters = True
    p.diameter_m = 1.1
    p.length_m = 6.7
    return p


def _fly(beta, sep="body", glider=True):
    p = _booster()
    p.body_reenters = (sep == "body")      # the booster owns the link
    ro = ROParams(name="RV", mass_kg=500.0, beta_kg_m2=beta, shape="karman",
                  diameter_m=1.1, length_m=2.0, separation_mode=sep,
                  glider_enabled=glider, glider_LD=(0.0 if glider else 0.0),
                  glider_guidance="damped_glide", body_nose_length_m=2.0)
    pc = compose_loadout(p, ro, 1)
    pc.ro = ro
    return integrate_trajectory(pc, 39.12, 125.67, 90.0,
                                burnout_angle_deg=-2.0, max_time_s=3600.0), pc


# ── 1. body β=0 derives a positive β and flies with it ──────────────────────

def test_body_zero_beta_derives_positive():
    r, _ = _fly(0.0)
    assert r["derived_beta_kg_m2"] is not None
    assert r["derived_beta_kg_m2"] > 0.0
    assert r["range_km"] and r["range_km"] > 0.0     # flew; no div-by-zero


def test_derived_beta_matches_hand_computation():
    """β_ref = m_burnout / (Cd0_body(Mref) · A_base) — the inherited burnout
    mass over the airframe drag, not the RO's own mass_kg field."""
    r, pc = _fly(0.0)
    last = glider_ld._last_stage(pc)
    A = np.pi * (last.diameter_m / 2.0) ** 2
    m = effective_ro(pc).mass_kg
    cd0 = glider_ld.body_cd0(pc, glider_ld.GLIDE_MACH_REF)
    expect = m / (cd0 * A)
    assert abs(r["derived_beta_kg_m2"] - expect) < 1.0
    assert m != 500.0            # inherited burnout mass, not the RO's 500 kg


def test_derived_beta_is_a_sane_mach_curve():
    """The derived β is the airframe Cd0 build-up over Mach (not a flat
    fallback): the ref-Mach value sits in a physical band for a slender dense
    body, and β=0 flies clearly differently from an arbitrary constant β."""
    r0, pc = _fly(0.0)
    beta_ref = r0["derived_beta_kg_m2"]
    assert 3000.0 < beta_ref < 12000.0
    # Cd0 falls with Mach, so β RISES with Mach — the table is not flat.
    lo = glider_ld.body_cd0(pc, 2.0)
    hi = glider_ld.body_cd0(pc, 12.0)
    assert lo > hi > 0.0                                         # genuine Mach curve
    r_diff, _ = _fly(2000.0)
    assert abs(r0["range_km"] - r_diff["range_km"]) > 20.0       # ≠ arbitrary β


# ── 3 & 4. entered β and separating RVs never derive ────────────────────────

def test_body_with_entered_beta_does_not_derive():
    r, _ = _fly(3000.0)
    assert r["derived_beta_kg_m2"] is None       # scalar respected, no derivation


def test_separating_rv_never_derives():
    """A separating object has no airframe to derive a beta from: beta 0 on
    one is refused (FRONT_END_DESIGN.md §18.2).  It used to fly with infinite
    drag and report no derived beta."""
    import pytest
    with pytest.raises(ValueError, match="beta_kg_m2"):
        _fly(0.0, sep="separating_ro", glider=False)
    r, _ = _fly(3000.0, sep="separating_ro", glider=False)
    assert r["derived_beta_kg_m2"] is None


# ── nose-first vs tumbling: the β regime follows the attitude ────────────────

def _fly_attitude(attitude, glider):
    p = _booster()
    ro = ROParams(name="b", mass_kg=500.0, beta_kg_m2=0.0, shape="karman",
                  diameter_m=1.1, length_m=2.0, separation_mode="body",
                  reentry_attitude=attitude, glider_enabled=glider, glider_LD=0.0,
                  glider_guidance="damped_glide", body_nose_length_m=2.0)
    pc = compose_loadout(p, ro, 1)
    pc.ro = ro
    return integrate_trajectory(pc, 39.12, 125.67, 90.0,
                                burnout_angle_deg=-2.0, max_time_s=3600.0)


def test_tumbling_body_uses_tumbling_beta_not_the_nose_first_table():
    """A body that cannot hold nose-first (reentry_attitude='tumbling') is a
    bluff spinning cylinder with a far LOWER β — the low-drag nose-first table
    must not apply, and no derived (nose-first) β is reported."""
    t = _fly_attitude("tumbling", glider=False)
    assert t["derived_beta_kg_m2"] is None            # no nose-first β for a tumbler


def test_nose_first_penetrates_faster_than_tumbling():
    """The physical distinction (user, 2026-08-21): a body reentering nose-first
    on its nose+fins has a much higher β than the same body tumbling, so it
    decelerates far less and strikes much faster."""
    tumbling = _fly_attitude("tumbling", glider=False)
    nose_first = _fly_attitude("trim", glider=True)
    assert nose_first["derived_beta_kg_m2"] > 0.0
    assert nose_first["impact_speed_ms"] > 2.0 * tumbling["impact_speed_ms"]
