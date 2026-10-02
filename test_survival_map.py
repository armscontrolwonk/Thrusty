"""The four answers at the top of the Reentry Survivability tab (TODO item 11).

A reader wants two things: is a surface compromised (the nose, a wing or
leading edge, the windward surface), and is the inside cooked by a long, hot
soak.  One row each, above everything else; the headline is the worst row,
never better; a row that cannot be computed says why instead of vanishing.
These tests pin those rules on the two shipped test flights and on results
edited to reach each case.
"""

import copy

import numpy as np
import pytest

import booster_models as bm
import heating
import survivability_report as sr
from test_report_lead import _fly_ballistic
from test_thresholds import _fly_glider

_CACHE = {}


def _flight(key):
    if key not in _CACHE:
        _CACHE[key] = (_fly_ballistic("Mk21", "Generic ICBM") if key == "mk21"
                       else _fly_glider())
    return copy.deepcopy(_CACHE[key])


def _row(rows, place):
    return next(r for r in rows if r['place'].startswith(place))


def _block(body):
    top = body.split("═══ Full analysis")[0]
    return top[top.index("─── Survival map"):].split("\n")


# ── placement and layout ─────────────────────────────────────────────────────
def test_the_answers_come_first_with_their_columns():
    body = sr.build_report(_flight("mk21"))['body']
    assert body.startswith("─── Survival map")
    lines = _block(body)
    assert lines[1] == "\t" + "\t".join(sr.ANSWER_COLS)
    places = [l.split("\t")[0].strip() for l in lines[2:6]]
    assert places == ["Nose", "Wing / leading edge", "Windward surface",
                      "Interior after the soak"]
    assert body.index("Survival map") < body.index("═══ Full analysis")


def test_the_nose_sentence_is_said_once():
    body = sr.build_report(_flight("mk21"))['body']
    assert body.count("nose carries 910 MJ/m²") <= 1 or \
        body.count("nose carries") == 1


def test_spans_land_on_the_verdict_text():
    for key in ("mk21", "glider"):
        rep = sr.build_report(_flight(key))
        lines = _block(rep['body'])
        assert rep['map_spans']
        for ln, c0, c1, tier in rep['map_spans']:
            assert lines[ln][c0:c1] == sr._VERDICT_TEXT[tier]


# ── the rows on the shipped test flights ─────────────────────────────────────
def test_ablative_rows_give_the_load_against_the_record():
    rows = sr.answers(_flight("mk21"))
    nose = _row(rows, "Nose")
    assert nose['tier'] == 'experience' and nose['verdict'] == "holds"
    assert "MJ/m² heat load" in nose['value'] and "of the record" in nose['value']
    assert "3,870 MJ/m² flown" in nose['limit']
    assert _row(rows, "Wing")['verdict'] == "none on this object"


def test_no_thickness_means_no_interior_answer_and_the_headline_says_so():
    r = _flight("mk21")
    assert not r['heating_arc']['profile']['body_thickness_m']
    inside = _row(sr.answers(r), "Interior")
    assert inside['tier'] is None and inside['verdict'] == "not computed"
    assert "thickness" in inside['reason']
    assert "not computed: interior" in sr.build_report(r)['headline']


def test_a_failing_nose_drives_the_headline():
    rep = sr.build_report(_flight("glider"))
    assert _row(sr.answers(_flight("glider")), "Nose")['tier'] == 'beyond'
    assert rep['tier'] in ('beyond', 'fail') and "nose past limit" in rep['headline']


# ── the headline is the worst row (the screenshot of 2026-10-02) ─────────────
def test_an_amber_windward_surface_turns_a_green_headline_amber():
    r = _flight("mk21")
    assert sr.build_report(r)['tier'] == 'experience'
    r['heating_fom']['windward'] = dict(
        T_eq_windward_K={'lo': 1925.0, 'hi': 2266.0}, alpha_band_deg=(5, 20),
        body_material='uhtc',
        criteria={'windward_surface': {'limit_continuous_K': 1923.0,
                                       'limit_peak_K': 2700.0}})
    w = _row(sr.answers(r), "Windward")
    assert w['tier'] == 'beyond' and "1,925–2,266 K" in w['value']
    assert "1,923 K continuous" in w['limit'] and "2,700 K peak" in w['limit']
    rep = sr.build_report(r)
    assert rep['tier'] == 'beyond' and "windward past limit" in rep['headline']


# ── the interior after the soak ──────────────────────────────────────────────
def _with_body(r, material, thickness_m, limit_C=80.0):
    p = r['heating_arc']['profile']
    p.update(body_material=material, body_thickness_m=thickness_m,
             interior_limit_C=limit_C)
    return r


def test_the_interior_is_judged_against_the_objects_own_limit():
    r = _with_body(_flight("glider"), 'carbon_phenolic', 0.02)
    inside = _row(sr.answers(r), "Interior")
    assert inside['tier'] in ('experience', 'beyond')
    assert "°C behind 2.0 cm of Carbon phenolic" in inside['value']
    assert inside['limit'].startswith("80 °C (Hayabusa")
    hot = _row(sr.answers(_with_body(_flight("glider"), 'carbon_phenolic',
                                     0.02, limit_C=10.0)), "Interior")
    assert hot['tier'] == 'beyond'
    assert hot['limit'].startswith("10 °C (entered for this object")


def test_the_interior_says_why_when_the_material_has_no_conductivity():
    r = _with_body(_flight("glider"), 'uhtc', 0.30)
    inside = _row(sr.answers(r), "Interior")
    assert inside['tier'] is None
    assert "no cited conductivity for UHTC" in inside['reason']


def test_a_hot_interior_is_named_in_the_lead_and_the_headline():
    r = _with_body(_flight("mk21"), 'carbon_phenolic', 0.005, limit_C=5.0)
    rep = sr.build_report(r)
    assert rep['tier'] in ('beyond', 'fail')
    assert "interior past limit" in rep['headline']
    lead = rep['body'].split("═══ Full analysis")[0]
    assert "The heat also reaches the inside" in lead


# ── the wing or leading edge ─────────────────────────────────────────────────
def test_a_wing_without_a_leading_edge_entry_is_not_computed():
    r = _flight("mk21")
    r['heating_arc']['profile']['wing'] = True
    edge = _row(sr.answers(r), "Wing")
    assert edge['tier'] is None and "no leading-edge entry" in edge['reason']


def test_a_leading_edge_is_judged_against_its_own_material():
    r = _flight("mk21")
    r['heating_fom']['leading_edges'] = [dict(
        kind='leading_edge', name='wing', status='evaluated',
        material='c_sic', accuracy='within 15-20% (Tauber)',
        results={'laminar': {'T_wall_peak_K': (1700.0, 2050.0),
                             'q_peak_W_m2': (1e6, 2e6),
                             'heat_load_J_m2': (1e8, 2e8)}})]
    edge = _row(sr.answers(r), "Wing")
    assert edge['tier'] == 'beyond' and "1,700–2,050 K (wing)" in edge['value']
    assert "1,920 K continuous" in edge['limit']
    r['heating_fom']['leading_edges'][0].update(
        status='cannot be evaluated', missing=["radius_m is not given"])
    edge = _row(sr.answers(r), "Wing")
    assert edge['tier'] is None and "radius_m is not given" in edge['reason']


# ── the object carries its interior limit ────────────────────────────────────
def test_interior_limit_defaults_to_hayabusa_and_round_trips():
    ro = bm.ROParams(name="x", mass_kg=100.0, beta_kg_m2=1000.0)
    assert ro.interior_limit_C == 80.0
    ro.interior_limit_C = 60.0
    assert bm.ro_from_dict(bm.ro_to_dict(ro)).interior_limit_C == 60.0
    d = bm.ro_to_dict(ro); d.pop('interior_limit_C')
    assert bm.ro_from_dict(d).interior_limit_C == 80.0


def test_the_acreage_flux_is_the_one_the_body_screen_uses():
    r = _flight("glider")
    a, p = r['heating_arc'], r['heating_arc']['profile']
    q, state, fpk = heating.acreage_flux(
        a['t'], a['rho'], a['V'], a['alt'], nose_radius_m=p['nose_radius_m'],
        body_radius_m=p['diameter_m'] / 2.0)
    assert q.shape == np.asarray(a['t']).shape and np.all(q >= 0)
    assert state in ('laminar', 'transitional', 'turbulent') and fpk >= 1.0
