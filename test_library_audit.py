"""The library inventory (LIBRARY_RESET_PLAN.md, Phase 0) reports what a
file stores and what a run uses.  These tests pin the reporting on
synthetic inputs, so they do not depend on which vehicles are shipped."""

import json

import booster_models as bm
import library_audit as la


def test_stored_values_are_those_that_differ_from_the_default():
    d = dict(name='x', mass_initial=10.0, isp_s=250.0, booster_cd=0.20,
             has_fins=False, fin_span_m=0.0, mach_table=[0.0, 1.0],
             cd_table=[0.3, 0.4], not_a_field=7, stage2={'isp_s': 300.0})
    got = la.stored_values(d, bm.BoosterParams, skip=('name',))
    assert got == dict(mass_initial=10.0, isp_s=250.0, mach_table=[0.0, 1.0],
                       cd_table=[0.3, 0.4], not_a_field=7)


def test_provenance_reports_missing_source_and_words_that_suggest_fitting():
    p = la.provenance(dict(source='', notes='Mass is a trajectory fit, '
                           'pinned at the edge of the range; beta held at '
                           'its old value.'))
    assert p['source'] == '' and p['notes_chars'] > 0
    assert {'trajectory fit', 'pinned', 'held at'} <= set(p['flags'])
    assert la.provenance(dict(source='Forden 2007, Table 2', notes=''))['flags'] == []


def test_mass_residuals_show_a_stage_whose_numbers_do_not_add_up():
    good = dict(mass_initial=1000.0, mass_propellant=600.0, mass_final=100.0,
                shroud_mass_kg=20.0,
                stage2=dict(mass_initial=280.0, mass_propellant=200.0,
                            mass_final=50.0))
    assert la.mass_residuals(good) == [0.0, 30.0]      # 30 kg carried on top
    bad = json.loads(json.dumps(good))
    bad['mass_initial'] = 900.0
    assert la.mass_residuals(bad)[0] == -100.0


def test_the_drag_source_that_is_flown_is_reported_not_the_one_stored():
    # A single-stage stack with no front-end shape flies on its table.
    p = bm.BoosterParams(name='t', mass_initial=5000.0, mass_propellant=3500.0,
                         mass_final=1500.0, diameter_m=0.9, length_m=10.0,
                         thrust_N=120e3, burn_time_s=70.0, isp_s=240.0,
                         mach_table=[0.0, 1.0, 5.0], cd_table=[0.3, 0.5, 0.3])
    got = la.flown_drag_sources(p)
    assert got.get('table stored in the file', 0.0) > 0.99
    p.mach_table, p.cd_table = [], []
    got = la.flown_drag_sources(p)
    assert got.get('built-in Forden table', 0.0) > 0.99
    # The instrumenting is undone afterwards.
    assert bm._cd_nose_shape.__name__ == '_cd_nose_shape'
    assert bm.drag_coefficient.__name__ == 'drag_coefficient'


def test_the_report_runs_over_the_committed_libraries():
    text = la.report()
    assert text.startswith('# Library inventory')
    assert '## Boosters at a glance' in text and '## Reentry objects' in text
