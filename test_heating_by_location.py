"""Heating at the places a reentry object's file lists (heating_by_location).

Three kinds of test, kept apart:

1. THE FILE.  An entry carries only what no other field holds; the loader
   refuses a number stored twice and names the field that already holds it.
2. NOTHING IS SUPPLIED.  A place the file does not fully describe comes back
   "cannot be evaluated", naming the missing number.
3. THE WIRING.  Each evaluated place gives what the relations of
   heating_locations.py and heating_solid.py give when called directly, and
   says how its flux became a temperature.  Accuracy against flight and
   tunnel data is tested where the relations live (test_heating_locations.py,
   test_heating_solid.py), not repeated here.
"""

import glob
import json

import numpy as np
import pytest

import booster_models as bm
import heating
import heating_by_location as hb
import heating_locations as hl
import heating_solid
from atmosphere import atmosphere


def _object(**kw):
    base = dict(name="test body", mass_kg=45.8, beta_kg_m2=59.3, shape="cone",
                diameter_m=0.8, length_m=1.6, nose_radius_m=0.2,
                emissivity=0.85)
    base.update(kw)
    return bm.ROParams(**base)


def _arc():
    """A plain descending arc: 7 km/s falling to 3 km/s from 80 to 30 km."""
    t = np.linspace(0.0, 60.0, 121)
    alt = np.linspace(80e3, 30e3, t.size)
    V = np.linspace(7000.0, 3000.0, t.size)
    rho = np.array([atmosphere(a)[2] for a in alt])
    return t, rho, V, alt


def _one(ro):
    t, rho, V, alt = _arc()
    (r,) = hb.evaluate_locations(ro, t, rho, V, alt)
    return r


# ── 1. the file ─────────────────────────────────────────────────────────────
def test_a_listed_place_round_trips_and_an_empty_list_is_not_written():
    locs = [{'kind': 'nose_cap', 'name': 'nose', 'construction': 'skin'},
            {'kind': 'leading_edge', 'name': 'fin', 'radius_m': 0.01,
             'sweep_deg': 60.0, 'material': 'rcc', 'source': 'test'}]
    ro = _object(heating_locations=locs)
    d = json.loads(json.dumps(bm.ro_to_dict(ro)))
    assert bm.ro_from_dict(d).heating_locations == locs
    assert 'heating_locations' not in bm.ro_to_dict(_object())


@pytest.mark.parametrize('entry, field', [
    ({'kind': 'nose_cap', 'radius_m': 0.1}, 'nose_radius_m'),
    ({'kind': 'nose_cap', 'material': 'pica'}, 'nose_tps_material'),
    ({'kind': 'windward_face', 'alpha_deg': 5.0}, 'trim_alpha_deg'),
    ({'kind': 'windward_face', 'material': 'rcc'}, 'body_tps_material'),
    ({'kind': 'leading_edge', 'of': 'wing', 'sweep_deg': 70.0,
      'radius_m': 0.01}, 'wing_sweep_deg'),
])
def test_a_number_stored_twice_is_refused_naming_its_field(entry, field):
    d = bm.ro_to_dict(_object())
    d['heating_locations'] = [entry]
    with pytest.raises(ValueError, match="stored twice") as e:
        bm.ro_from_dict(d)
    assert field in str(e.value)


@pytest.mark.parametrize('entry, words', [
    ({'kind': 'wing_root'}, "not one of"),
    ({'kind': 'nose_cap', 'colour': 'black'}, "may carry only"),
    ({'kind': 'leading_edge', 'radius_m': 0.0}, "must be positive"),
    ({'kind': 'leading_edge', 'sweep_deg': 95.0}, "outside 0 to 90"),
    ({'kind': 'nose_cap', 'construction': 'ablator'}, "is not one of"),
    ({'kind': 'leading_edge', 'of': 'tail'}, "is not 'wing'"),
])
def test_a_malformed_entry_is_refused(entry, words):
    with pytest.raises(ValueError, match=words):
        bm.clean_heating_locations([entry])


def test_every_shipped_object_still_loads_and_resolves():
    files = glob.glob('ro_library/*.ro.json')
    assert files
    for f in files:
        ro = bm.ro_from_dict(json.load(open(f)))
        for loc in hb.resolve_locations(ro):
            assert isinstance(loc['missing'], list), f


# ── 2. nothing is supplied ──────────────────────────────────────────────────
def test_suggested_places_carry_no_numbers():
    plain = hb.suggest_locations(_object())
    assert [e['kind'] for e in plain] == ['nose_cap', 'windward_face']
    winged = hb.suggest_locations(_object(wing_sweep_deg=77.0))
    edge = winged[-1]
    assert edge == {'kind': 'leading_edge', 'name': 'wing', 'of': 'wing'}
    (res,) = [x for x in hb.resolve_locations(
        _object(wing_sweep_deg=77.0, heating_locations=winged))
        if x['kind'] == 'leading_edge']
    assert res['geometry']['sweep_deg'] == 77.0
    assert res['taken_from']['sweep_deg'] == 'wing_sweep_deg'
    assert any('radius_m' in m for m in res['missing'])
    assert any('material' in m for m in res['missing'])


def test_a_nose_radius_left_at_zero_is_not_given():
    r = _one(_object(nose_radius_m=0.0,
                     heating_locations=[{'kind': 'nose_cap'}]))
    assert r['status'] == 'cannot be evaluated'
    assert r['results'] == {}
    assert any('nose_radius_m is not given' in m for m in r['missing'])


def test_a_face_whose_flank_angle_is_not_defined_says_so():
    r = _one(_object(shape='ogive',
                     heating_locations=[{'kind': 'windward_face'}]))
    assert r['status'] == 'cannot be evaluated'
    assert any('flank angle' in m for m in r['missing'])


def test_a_solid_nose_without_a_catalog_conductivity_names_it(monkeypatch):
    # Every catalog entry now carries a TPSX k; remove one to test the gap.
    monkeypatch.setitem(heating.TPS_MATERIALS, 'titanium',
                        {**heating.TPS_MATERIALS['titanium'], 'k_W_mK': None})
    r = _one(_object(nose_tps_material='titanium', heating_locations=[
        {'kind': 'nose_cap', 'construction': 'solid',
         'solid_length_m': 0.1}]))
    assert r['status'] == 'cannot be evaluated'
    assert r['results'] == {}
    assert r['missing'] == ["the conductivity of 'titanium' is not in the "
                            "materials catalog"]


def test_no_arc_means_no_evaluation():
    ro = _object(heating_locations=[{'kind': 'nose_cap'}])
    (r,) = hb.evaluate_locations(ro, [0.0], [1e-3], [7000.0], [60e3])
    assert r['status'] == 'cannot be evaluated'
    assert r['missing'] == ["no flown arc to evaluate over"]


# ── 3. the wiring ───────────────────────────────────────────────────────────
def test_a_skin_nose_is_the_radiating_wall_balance_at_its_peak():
    ro = _object(nose_tps_material='rcc', heating_locations=[
        {'kind': 'nose_cap', 'construction': 'skin'}])
    r = _one(ro)
    assert r['status'] == 'evaluated'
    assert r['temperature_basis'] == 'radiating wall'
    t, rho, V, alt = _arc()
    T_inf = atmosphere(alt)[0]
    rad = heating.radiative_flux(rho, V, 0.2)[0]
    T = [hl.radiating_wall(
            lambda Tw, i=i: hl.stagnation_point_flux(
                rho[i], V[i], 0.2, Tw, T_inf[i]),
            0.85, extra_flux=rad[i])[0] for i in range(t.size)]
    assert r['results']['laminar']['T_wall_peak_K'] == pytest.approx(
        max(T), abs=0.05)
    assert r['accuracy'] is hl.ACCURACY['nose_cap']


def test_an_ablator_is_judged_on_load_with_no_wall_temperature():
    r = _one(_object(nose_tps_material='pica',
                     heating_locations=[{'kind': 'nose_cap'}]))
    lam = r['results']['laminar']
    assert 'T_wall_peak_K' not in lam
    assert r['temperature_basis'].startswith('ablator')
    t, rho, V, alt = _arc()
    q = (hl.stagnation_point_flux(rho, V, 0.2, hb.COLD_WALL_K,
                                  atmosphere(alt)[0])
         + heating.radiative_flux(rho, V, 0.2)[0])
    assert lam['q_peak_W_m2'] == pytest.approx(q.max(), rel=1e-12)
    assert lam['heat_load_J_m2'] == pytest.approx(np.trapezoid(q, t),
                                                  rel=1e-12)


def test_a_part_whose_construction_is_not_given_is_an_upper_bound():
    r = _one(_object(nose_tps_material='rcc',
                     heating_locations=[{'kind': 'nose_cap'}]))
    assert 'UPPER BOUND' in r['temperature_basis']


def test_a_solid_nose_runs_the_conduction_estimate(monkeypatch):
    mat = dict(heating.TPS_MATERIALS['c_sic'], density_kg_m3=1900.0,
               c_J_kgK=1100.0, k_W_mK=20.0, is_ablator=False)
    monkeypatch.setitem(heating.TPS_MATERIALS, 'test_solid', mat)
    ro = _object(nose_radius_m=0.005, diameter_m=0.4, length_m=1.2,
                 nose_tps_material='test_solid', heating_locations=[
                     {'kind': 'nose_cap', 'construction': 'solid',
                      'solid_length_m': 0.3}])
    r = _one(ro)
    assert r['status'] == 'evaluated', r['missing']
    t, rho, V, alt = _arc()
    direct = heating_solid.cone_tip_response(
        t, rho, V, atmosphere(alt)[0], tip_radius_m=0.005,
        half_angle_deg=np.degrees(np.arctan2(0.2, 1.2)), length_m=0.3,
        density_kg_m3=1900.0, specific_heat_J_kgK=1100.0,
        conductivity_W_mK=20.0, emissivity=0.85, T_initial_K=300.0)
    assert r['results']['laminar']['T_wall_peak_K'] == pytest.approx(
        float(np.max(direct['T_tip_K'])), rel=1e-12)
    assert r['accuracy'] is heating_solid.ACCURACY['solid_cone_tip']
    assert r['temperature_basis'].startswith('solid conduction')
    # a solid tip runs cooler than the same tip treated as a radiating skin
    skin = _one(ro.__class__(**{**ro.__dict__, 'heating_locations': [
        {'kind': 'nose_cap', 'construction': 'skin'}]}))
    assert (r['results']['laminar']['T_wall_peak_K']
            < skin['results']['laminar']['T_wall_peak_K'])


def test_a_leading_edge_is_a_band_between_two_laminar_relations():
    r = _one(_object(heating_locations=[
        {'kind': 'leading_edge', 'radius_m': 0.01, 'sweep_deg': 60.0,
         'material': 'rcc', 'construction': 'skin'}]))
    lam = r['results']['laminar']
    lo, hi = lam['q_peak_W_m2']
    assert lo <= hi
    assert {lam['low_is'], lam['high_is']} == {'Poll', 'Tauber Eq. 41'}
    assert lam['T_wall_peak_K'][0] <= lam['T_wall_peak_K'][1]
    assert 'turbulent' in r['results']
    assert r['Rbar_star_peak'] > 0.0


def test_a_wing_edge_is_evaluated_at_the_wing_sweep():
    ro = _object(wing_sweep_deg=70.0, heating_locations=[
        {'kind': 'leading_edge', 'of': 'wing', 'radius_m': 0.01,
         'material': 'rcc', 'construction': 'skin'}])
    own = _object(heating_locations=[
        {'kind': 'leading_edge', 'radius_m': 0.01, 'sweep_deg': 70.0,
         'material': 'rcc', 'construction': 'skin'}])
    assert (_one(ro)['results']['laminar']['q_peak_W_m2']
            == _one(own)['results']['laminar']['q_peak_W_m2'])


def test_the_windward_face_is_judged_at_three_stations():
    r = _one(_object(nose_tps_material='rcc', body_tps_material='rcc',
                     heating_locations=[{'kind': 'windward_face',
                                         'construction': 'skin'}]))
    assert [s['x_over_L'] for s in r['stations']] == list(hb.FACE_STATIONS)
    q = [s['results']['laminar']['q_peak_W_m2'] for s in r['stations']]
    assert q == sorted(q, reverse=True)          # laminar falls as x^-1/2
    assert r['results'] is r['stations'][0]['results']
    assert r['accuracy'] is hl.ACCURACY['windward_face']


def test_a_flat_bottomed_face_is_a_band_between_plate_and_cone():
    r = _one(_object(body_form='wedge', body_span_m=0.8, trim_alpha_deg=10.0,
                     heating_locations=[{'kind': 'windward_face',
                                         'construction': 'skin'}]))
    lam = r['results']['laminar']
    assert lam['low_is'] == 'flat plate' and lam['high_is'] == 'cone'
    assert lam['q_peak_W_m2'][0] < lam['q_peak_W_m2'][1]
    # both lifting forms fly flat side down: the face is inclined at the
    # angle of attack alone, and its running length is the body length
    assert [s['angle_deg'] for s in r['stations']] == [10.0] * 3
    (loc,) = hb.resolve_locations(_object(
        body_form='half_cone', trim_alpha_deg=10.0, length_m=2.0,
        heating_locations=[{'kind': 'windward_face'}]))
    assert [s['run_m'] for s in loc['geometry']['stations']] == [0.5, 1.0, 1.5]


# ── findings of the independent review, 2026-09-30 ─────────────────────────
def test_a_lifting_body_without_a_trim_angle_is_not_given():
    for kw in (dict(body_form='wedge'), dict(maneuvering=True),
               dict(glider_LD=2.5)):
        r = _one(_object(heating_locations=[{'kind': 'windward_face'}], **kw))
        assert r['status'] == 'cannot be evaluated', kw
        assert any('trim_alpha_deg is not given' in m for m in r['missing'])


def test_a_ballistic_body_flies_at_zero_angle_of_attack_and_says_so():
    (loc,) = hb.resolve_locations(_object(
        heating_locations=[{'kind': 'windward_face'}]))
    assert loc['geometry']['alpha_deg'] == 0.0
    assert loc['taken_from']['alpha_deg'].startswith('ballistic')


def test_the_running_length_follows_both_cones_of_a_biconic():
    ro = _object(diameter_m=1.0, length_m=4.0, biconic=True,
                 fore_length_m=1.0, break_diameter_m=0.6, nose_radius_m=0.0,
                 heating_locations=[{'kind': 'windward_face'}])
    (loc,) = hb.resolve_locations(ro)
    (_, _, a1, _), (_, _, a2, _) = loc['geometry']['segments']
    c = lambda a: np.cos(np.radians(a))
    for st in loc['geometry']['stations']:
        x = st['x_over_L'] * 4.0
        assert st['run_m'] == pytest.approx(1.0 / c(a1) + (x - 1.0) / c(a2))


def test_a_stale_biconic_flag_is_ignored_on_a_lifting_body():
    ro = _object(diameter_m=1.0, length_m=4.0, biconic=True,
                 fore_length_m=1.0, break_diameter_m=0.6, body_form='wedge',
                 trim_alpha_deg=8.0,
                 heating_locations=[{'kind': 'windward_face'}])
    (loc,) = hb.resolve_locations(ro)
    assert len(loc['geometry']['segments']) == 1


def test_an_emissivity_of_zero_is_not_given():
    r = _one(_object(emissivity=0.0, heating_locations=[{'kind': 'nose_cap'}]))
    assert "emissivity is not given" in r['missing']


def test_material_provenance_names_the_field_actually_used():
    (loc,) = hb.resolve_locations(_object(
        tps_material='rcc', heating_locations=[{'kind': 'nose_cap'}]))
    assert loc['material'] == 'rcc'
    assert loc['taken_from']['material'] == 'tps_material'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, '70°'])
def test_a_number_that_is_not_a_finite_number_is_refused(value):
    with pytest.raises(ValueError, match=r"heating_locations\[0\]"):
        bm.clean_heating_locations(
            [{'kind': 'leading_edge', 'sweep_deg': value}])


# ── a non-separating body: the booster's last stage reenters ──────────────
def _body(nose_len=0.0, **kw):
    """The Scud-B stack with its warhead object, as a run composes it; the
    object passed on is effective_ro, the object AS FLOWN, which carries the
    last stage's diameter and length."""
    import copy
    import dataclasses as dc
    p = bm.booster_from_dict(json.load(open(
        'booster_library/Scud-B_-R-17-.booster.json')))
    ro = bm.ro_from_dict(json.load(open('ro_library/Scud-B_warhead.ro.json')))
    ro = dc.replace(ro, body_nose_length_m=nose_len, nose_radius_m=0.05,
                    heating_locations=[{'kind': 'nose_cap'},
                                       {'kind': 'windward_face'}], **kw)
    p = copy.deepcopy(p)
    p.ro = ro
    flown = bm.effective_ro(bm.compose_loadout(p, ro, 1))
    assert flown.separation_mode == 'body'
    return flown


def test_a_body_is_a_nose_taper_on_a_cylinder_not_one_long_cone():
    ro = _body(nose_len=2.5)
    (_, face) = hb.resolve_locations(ro)
    (x0, x1, a, s1), (y0, y1, b, s2) = face['geometry']['segments']
    assert (x0, x1, s1) == (0.0, 2.5, 'cone')
    assert a == pytest.approx(np.degrees(np.arctan2(ro.diameter_m / 2, 2.5)))
    assert (y0, y1, b, s2) == (2.5, ro.length_m, 0.0, 'cylinder')
    assert [st['surface'] for st in face['geometry']['stations']] == \
        ['cylinder'] * 3                        # 2.8, 5.6 and 8.4 m aft


def test_a_body_without_a_nose_length_is_not_given():
    (_, face) = hb.resolve_locations(_body(nose_len=0.0))
    assert any(m.startswith('body_nose_length_m is not given')
               for m in face['missing'])


def test_a_ballistic_body_s_cylinder_along_the_flow_is_not_covered():
    ro = _body(nose_len=2.5)
    (_, face) = hb.evaluate_locations(ro, *_arc())
    assert face['status'] == 'not covered'
    assert all('not_covered' in st for st in face['stations'])
    # a longer nose puts the first station on the cone, which is evaluated
    (_, face) = hb.evaluate_locations(_body(nose_len=4.0), *_arc())
    assert face['status'] == 'evaluated'
    assert [bool(st['results']) for st in face['stations']] == \
        [True, False, False]


def test_a_body_at_incidence_takes_the_run_s_angle_and_bands_the_cylinder():
    att = dict(alpha_deg=10.0, source="the run's trim gate")
    (_, face) = hb.evaluate_locations(_body(nose_len=2.5), *_arc(),
                                      attitude=att)
    assert face['status'] == 'evaluated'
    for st in face['stations']:
        assert st['angle_deg'] == 10.0
        lam = st['results']['laminar']
        assert (lam['low_is'], lam['high_is']) == ('flat plate', 'cone')
    assert any("the run's trim gate" in n for n in face['notes'])


def test_the_run_s_attitude_wins_over_the_object_s_own_fields():
    ro = _object(trim_alpha_deg=5.0, heating_locations=[
        {'kind': 'windward_face'}])
    (loc,) = hb.resolve_locations(ro, dict(alpha_deg=12.0, source='run'))
    assert (loc['geometry']['alpha_deg'], loc['taken_from']['alpha_deg']) \
        == (12.0, 'run')


@pytest.mark.parametrize('how', ['plan', 'run'])
def test_a_tumbling_body_has_no_fixed_places_to_judge(how):
    import dataclasses as dc
    ro = _body(nose_len=3.0)
    att = None
    if how == 'plan':
        ro = dc.replace(ro, reentry_attitude='tumbling')
    else:
        att = hb.run_attitude({'reentry_trim': {'tumbles': True}})
    for r in hb.evaluate_locations(ro, *_arc(), attitude=att):
        assert r['status'] == 'not defined'
        assert r['not_defined'].startswith('the body tumbles')
        assert r['results'] == {}


def test_run_attitude_reads_the_trim_gate():
    assert hb.run_attitude({}) is None
    assert hb.run_attitude({'reentry_trim': None}) is None
    assert hb.run_attitude({'reentry_trim': {'alpha_glide_deg': 7.5}}) == \
        dict(alpha_deg=7.5,
             source="the run's trim gate: glide angle of attack")
    assert hb.run_attitude({'reentry_trim': {'tumbles': True,
                                              'alpha_glide_deg': 7.5}}
                           )['tumbling'] is True


def test_a_separating_object_is_still_one_cone_from_tip_to_base():
    (loc,) = hb.resolve_locations(_object(
        body_nose_length_m=0.3, heating_locations=[{'kind': 'windward_face'}]))
    assert [sf for *_, sf in loc['geometry']['segments']] == ['cone']
    assert loc['geometry']['segments'][0][1] == 1.6
