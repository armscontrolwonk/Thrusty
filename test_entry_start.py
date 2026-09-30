"""Starting a flight from a stated entry condition (trajectory.integrate_entry).

1. THE STATE.  entry_state_ecef builds the Earth-fixed state that the stated
   speed, angle, heading, frame and altitude datum describe.
2. THE FLIGHT.  A reentry object flown from an entry state is flown as it is
   after separation: no stage events, no debris, no boost rows; the run opens
   with an "Entry interface" row.
3. NOTHING ELSE MOVES.  A launch from the pad is unchanged.
4. ACCURACY AGAINST NAMED CASES.
   Stardust  the reconstructed flight trajectory, Liu et al., AIAA 2008-1213,
             Table 3: started at the first tabulated point (34 s, 81.02 km,
             12385.12 m/s) and compared at later ones.  Geometry from the
             same paper (nose radius 0.2286 m, maximum diameter 0.8128 m).
   OSIRIS-REx the nominal entry timeline, Ajluni et al., "OSIRIS-REx,
             Returning the Asteroid Sample" (IEEE Aerospace Conference;
             NTRS 20150000809), Section 6 and Fig. 6-4: entry at 12.2 km/s,
             -8.2 deg, heading 62 deg, 125 km reference altitude; peak
             heating E+51 s; peak deceleration 31.8 g at E+61 s.

WHAT IS ASSUMED, NOT CITED, and therefore what these two cases can and cannot
show:
  * Ballistic coefficient 59.3 kg/m^2.  It is the median value implied by the
    Stardust flight table itself (drag = deceleration along the path); no
    capsule mass is given in either source.  OSIRIS-REx uses the same value on
    the strength of Ajluni et al.'s statement that the capsule is "identical
    to Stardust" in all aspects relating to reentry.
  * The Stardust start direction (flight-path angle from the table's altitude
    steps) and both vehicles' entry latitude, longitude and, for Stardust,
    heading are placeholders.  They move the result little; they are not data.
  * OSIRIS-REx's 12.2 km/s is read as inertial and its 125 km as a height
    above the equatorial radius.  The paper states neither.  With 125 km read
    as geodetic every event comes 6-8 s early, which is why the test pins the
    reading: it is a finding about the convention, not a free success.
The capsule's parachute descent is not modelled, so nothing after peak
deceleration is compared.
"""

import functools

import numpy as np
import pytest

import booster_models as bm
import trajectory as tr
from booster_models import get_booster
from coordinates import OMEGA_EARTH, ecef_to_geodetic
from gravity import RE

BETA = 59.3


def _capsule():
    return bm.ROParams(name="sample return capsule", mass_kg=45.8,
                       beta_kg_m2=BETA, diameter_m=0.8128, length_m=0.5,
                       nose_radius_m=0.2286)


# ── 1. the state ────────────────────────────────────────────────────────────
def test_relative_state_has_the_stated_speed_angle_and_heading():
    s = tr.entry_state_ecef(7000.0, -5.0, 120e3, 62.0, 37.0, -121.0,
                            speed_frame="relative")
    lat, lon, alt = ecef_to_geodetic(s[:3])
    assert np.degrees(lat) == pytest.approx(37.0, abs=1e-6)
    assert np.degrees(lon) == pytest.approx(-121.0, abs=1e-6)
    assert alt == pytest.approx(120e3, abs=0.01)
    e, n, u = tr._enu_frame(lat, lon)
    v = s[3:]
    assert np.linalg.norm(v) == pytest.approx(7000.0, rel=1e-12)
    assert np.degrees(np.arcsin(np.dot(v, u) / 7000.0)) == pytest.approx(-5.0)
    assert np.degrees(np.arctan2(np.dot(v, e), np.dot(v, n))) == \
        pytest.approx(62.0)


def test_inertial_state_removes_the_earths_rotation():
    s = tr.entry_state_ecef(12200.0, -8.2, 125e3, 62.0, 37.0, -121.0,
                            speed_frame="inertial")
    v_inertial = s[3:] + np.cross([0.0, 0.0, OMEGA_EARTH], s[:3])
    assert np.linalg.norm(v_inertial) == pytest.approx(12200.0, rel=1e-12)
    # heading has an eastward part, so the ground-relative speed is lower
    assert np.linalg.norm(s[3:]) < 12200.0


def test_equatorial_radius_datum_is_a_sphere():
    for lat in (0.0, 37.0, 80.0):
        s = tr.entry_state_ecef(7000.0, -5.0, 125e3, 90.0, lat, 10.0,
                                altitude_datum="equatorial_radius")
        assert np.linalg.norm(s[:3]) == pytest.approx(RE + 125e3, abs=0.01)
    # on the equator the two datums coincide; away from it the sphere is higher
    eq = tr.entry_state_ecef(7000.0, -5.0, 125e3, 90.0, 0.0, 10.0,
                             altitude_datum="equatorial_radius")
    assert ecef_to_geodetic(eq[:3])[2] == pytest.approx(125e3, abs=1.0)
    mid = tr.entry_state_ecef(7000.0, -5.0, 125e3, 90.0, 37.0, 10.0,
                              altitude_datum="equatorial_radius")
    assert 130e3 < ecef_to_geodetic(mid[:3])[2] < 136e3


def test_unknown_frame_or_datum_is_refused():
    with pytest.raises(ValueError):
        tr.entry_state_ecef(7000.0, -5.0, 120e3, 0.0, 0.0, 0.0,
                            speed_frame="ground")
    with pytest.raises(ValueError):
        tr.entry_state_ecef(7000.0, -5.0, 120e3, 0.0, 0.0, 0.0,
                            altitude_datum="msl")


# ── 2. the flight ───────────────────────────────────────────────────────────
@functools.lru_cache(maxsize=None)
def _osiris_rex(datum="equatorial_radius"):
    return tr.integrate_entry(_capsule(), 12200.0, -8.2, 125e3, 62.0,
                              37.0, -121.0, speed_frame="inertial",
                              altitude_datum=datum, dt_output=0.25,
                              max_time_s=1500.0)


def test_entry_run_opens_with_the_entry_interface_and_has_no_boost():
    r = _osiris_rex()
    events = [m['event'] for m in r['milestones']]
    assert events[0].startswith("Entry interface (0 s")
    assert events[-1].startswith("Impact")
    for word in ("gnition", "burnout", "Apogee", "Max q", "lateral load",
                 "Fairing", "empty"):
        assert not any(word in e for e in events), word
    assert r['debris_trajectories'] == []
    assert not r['orbital']


def test_entry_run_starts_in_the_stated_state_and_carries_the_object():
    r = _osiris_rex()
    assert r['t'][0] == 0.0
    assert r['inertial_speed'][0] == pytest.approx(12200.0, rel=1e-6)
    assert r['range'][0] == 0.0
    assert np.all(np.diff(r['range']) >= 0.0)
    assert r['mass'][5] == pytest.approx(45.8)
    assert r['mass'][-1] == pytest.approx(45.8)


def test_entry_run_is_heated():
    r = _osiris_rex()
    fom = r['heating_fom']
    assert fom and fom['q_peak_MW_m2'] > 1.0
    assert any(m['event'].startswith("Peak heating") for m in r['milestones'])


# ── 3. nothing else moves ───────────────────────────────────────────────────
def test_a_launch_from_the_pad_is_unchanged_by_the_new_argument():
    a = tr.integrate_trajectory(get_booster("Scud-B (R-17)"),
                                33.0, 44.0, 90.0)
    b = tr.integrate_trajectory(get_booster("Scud-B (R-17)"),
                                33.0, 44.0, 90.0, initial_state_ecef=None)
    assert np.array_equal(a['pos_ecef'], b['pos_ecef'])
    assert ([m['event'] for m in a['milestones']]
            == [m['event'] for m in b['milestones']])
    assert any(e['event'].startswith("Ignition") for e in a['milestones'])
    assert any(e['event'].startswith("Apogee") for e in a['milestones'])


# ── 4. accuracy against named cases ─────────────────────────────────────────
# Liu et al., AIAA 2008-1213, Table 3: t s, altitude km, speed m/s
STARDUST = ((34, 81.02, 12385.12), (36, 78.46, 12336.86),
            (38, 75.96, 12269.13), (40, 73.54, 12181.08),
            (42, 71.19, 12062.73), (44, 68.93, 11902.13),
            (46, 66.76, 11689.11), (48, 64.69, 11414.01),
            (51, 61.76, 10871.38), (53, 59.95, 10417.96),
            (56, 57.46, 9617.36), (59, 55.23, 8708.65),
            (62, 53.25, 7751.20), (66, 50.98, 6504.45))


def test_stardust_flight_trajectory():
    t0, z0, v0 = STARDUST[0]
    gamma = np.degrees(np.arcsin((STARDUST[1][1] - z0) * 1e3
                                 / (STARDUST[1][0] - t0) / v0))
    r = tr.integrate_entry(_capsule(), v0, gamma, z0 * 1e3, 80.0,
                           40.0, -116.0, speed_frame="relative",
                           dt_output=0.5, max_time_s=400.0)
    for t, z, v in STARDUST[1:]:
        i = int(np.argmin(np.abs(r['t'] - (t - t0))))
        assert r['alt'][i] / 1e3 == pytest.approx(z, abs=0.8)
        assert r['speed'][i] == pytest.approx(v, rel=0.015)


def _peak_deceleration(r):
    """Sensed deceleration (drag over mass) in g, and its time."""
    from atmosphere import atmosphere
    rho = np.array([atmosphere(max(a, 0.0))[2] for a in r['alt']])
    g = 0.5 * rho * r['speed'] ** 2 / BETA / 9.80665
    i = int(np.argmax(g))
    return float(g[i]), float(r['t'][i])


def _peak_heating_time(r):
    row = next(m for m in r['milestones']
               if m['event'].startswith("Peak heating"))
    return float(row['t_s'])


def test_osiris_rex_nominal_entry_timeline():
    r = _osiris_rex()
    g_peak, t_g = _peak_deceleration(r)
    assert _peak_heating_time(r) == pytest.approx(51.0, abs=2.0)
    assert t_g == pytest.approx(61.0, abs=2.0)
    assert g_peak == pytest.approx(31.8, rel=0.04)


def test_reading_125_km_as_geodetic_puts_every_event_early():
    r = _osiris_rex("geodetic")
    _, t_g = _peak_deceleration(r)
    assert 5.0 < 61.0 - t_g < 9.0
    assert 5.0 < 51.0 - _peak_heating_time(r) < 9.0
