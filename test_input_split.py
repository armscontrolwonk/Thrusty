"""The four inputs stay apart.

Thrusty has four inputs: two hardware files (booster, reentry object) and two
non-hardware files (flight plan, reentry plan).  The rule, held here as a
schema test over the shipped files and the serialisers:

  * a hardware file carries no plan key, and a plan file carries no hardware
    key -- nothing is stored twice;
  * timings (when something jettisons, deploys or ignites) are plan data, even
    when the thing that jettisons is hardware;
  * the ONLY link between a booster and a reentry object is the booster's
    ``body_reenters`` flag.  Neither the object file nor the reentry plan
    stores a separation choice; the run derives it from the booster.

Pure JSON plus the serialisers -- no GUI needed.
"""

import dataclasses as dc
import glob
import json

import pytest

import booster_models as mm
import field_registry as fr
from booster_models import (BoosterParams, ROParams, booster_to_dict,
                            booster_from_dict, ro_to_dict, ro_from_dict,
                            apply_flight_plan, extract_flight_plan,
                            apply_reentry_plan, extract_reentry_plan,
                            compose_loadout, effective_ro,
                            run_separation_mode, bind_ro_separation,
                            get_booster)

# Every set below is READ OFF the ownership registry, never computed by
# subtracting one set from another.  That distinction is the point of this
# file: while hardware was "the fields nobody listed as a plan key", the
# overlap check below could not fail, and an unclassified new field became
# hardware in silence.  Now an unclassified field has no owner at all, and
# test_every_field_has_a_declared_owner says so.
def _own(registry, *owners):
    return {k for k, v in registry.items() if v in owners}


FLIGHT_PLAN_KEYS = _own(fr.BOOSTER_FIELD_OWNER,
                        fr.FLIGHT_PLAN_TOP, fr.FLIGHT_PLAN_STAGE)
REENTRY_PLAN_KEYS = _own(fr.RO_FIELD_OWNER, fr.REENTRY_PLAN)
LINK_KEY = 'body_reenters'
DERIVED = _own(fr.RO_FIELD_OWNER, fr.DERIVED) | _own(fr.BOOSTER_FIELD_OWNER, fr.DERIVED)
# Run-time scratch: the loadout record, plus the legacy separation spellings
# that old files still carry and the upgraders still read (those are file
# keys, not fields of either dataclass, so the registry does not cover them).
RUN_SCRATCH = (_own(fr.BOOSTER_FIELD_OWNER, fr.RUN_LOADOUT)
               | {'ro_separates', 'rv_separates'})
META = (_own(fr.BOOSTER_FIELD_OWNER, fr.META) | _own(fr.RO_FIELD_OWNER, fr.META)
        | set(fr.PLAN_FILE_META))   # a flight plan names the object it flies

BOOSTER_HARDWARE = _own(fr.BOOSTER_FIELD_OWNER, fr.HARDWARE)
RO_HARDWARE = _own(fr.RO_FIELD_OWNER, fr.HARDWARE)

# A shipped booster whose flight plan names the object it flies, for the
# export/import link test.  Picked from the data rather than hard-coded, so it
# survives the library being re-curated.
def _first_plan_naming_an_object():
    for _fp in sorted(glob.glob('flight_plans/*.flightplan.json')):
        _d = json.load(open(_fp))
        if _d.get('reentry_object'):
            return json.load(open(
                _fp.replace('flight_plans/', 'booster_library/')
                   .replace('.flightplan.json', '.booster.json')))['name']
    return None


BOOSTER_FILES = sorted(glob.glob('booster_library/*.booster.json') + glob.glob('*.booster.json'))
RO_FILES = sorted(glob.glob('ro_library/*.ro.json') + glob.glob('*.ro.json'))
FLIGHT_PLAN_FILES = sorted(glob.glob('flight_plans/*.flightplan.json'))
REENTRY_PLAN_FILES = sorted(glob.glob('reentry_plans/*.reentryplan.json'))
FLIGHT_PLAN_NAMING_AN_OBJECT = _first_plan_naming_an_object()


def _stages(d):
    node = d
    while node is not None:
        yield node
        node = node.get('stage2')


# ── the key sets themselves ─────────────────────────────────────────────────

def test_timings_are_flight_plan_keys():
    """When an adapter drops and when the core lights are flight decisions."""
    assert 'interstage_jettison_s' in mm._FLIGHT_PLAN_STAGE_KEYS
    assert 'grid_fin_deploy_schedule' in mm._FLIGHT_PLAN_STAGE_KEYS
    assert 'booster_core_delay_s' in mm._FLIGHT_PLAN_TOP_KEYS
    assert 'booster_jettison_s' in mm._FLIGHT_PLAN_TOP_KEYS
    assert 'shroud_jettison_alt_km' in mm._FLIGHT_PLAN_TOP_KEYS


def test_separation_is_not_a_plan_key_and_link_is_booster_hardware():
    assert 'separation_mode' not in REENTRY_PLAN_KEYS
    assert LINK_KEY in BOOSTER_HARDWARE
    assert LINK_KEY not in RO_HARDWARE and LINK_KEY not in REENTRY_PLAN_KEYS


def test_no_key_is_both_hardware_and_plan():
    """Single ownership.

    Be clear about what this does and does not prove.  A field cannot have two
    owners in a dict, so the first two lines still hold by construction -- as
    they did when hardware was computed by subtraction.  The difference is
    that the construction no longer decides anything on its own: a field must
    be IN the registry to be anything at all, and
    test_every_field_has_a_declared_owner is what enforces that.  The last two
    lines are real checks, because RUN_SCRATCH carries legacy file spellings
    the registry does not cover."""
    assert not (BOOSTER_HARDWARE & FLIGHT_PLAN_KEYS)
    assert not (RO_HARDWARE & REENTRY_PLAN_KEYS)
    assert not (BOOSTER_HARDWARE & RUN_SCRATCH)
    assert not (RO_HARDWARE & DERIVED)


@pytest.mark.parametrize('cls,registry,label', [
    (BoosterParams, fr.BOOSTER_FIELD_OWNER, 'BOOSTER_FIELD_OWNER'),
    (ROParams, fr.RO_FIELD_OWNER, 'RO_FIELD_OWNER'),
])
def test_every_field_has_a_declared_owner(cls, registry, label):
    """Adding a field is a decision about which of the four files owns it.

    This is the assertion that makes the rule enforceable rather than
    conventional: a new field must be classified, and until it is, nothing
    guesses on the author's behalf.  The old arrangement made the omission
    invisible -- an unlisted field was hardware, and no test disagreed.
    """
    fields = {f.name for f in dc.fields(cls)}
    missing = fields - set(registry)
    assert not missing, (
        f"{sorted(missing)} added to {cls.__name__} without an entry in "
        f"field_registry.{label}. Decide which of the four files owns it: "
        f"hardware belongs in the .booster.json/.ro.json, guidance and "
        f"timings in the plan, and anything composed per run in neither.")
    stale = set(registry) - fields
    assert not stale, (
        f"field_registry.{label} classifies {sorted(stale)}, which is no "
        f"longer a field of {cls.__name__}")


def test_the_exempt_categories_are_closed_sets():
    """The exemptions are the one place a field can hide.

    META, DERIVED and COMPOSED are excused from the hardware/plan checks, so
    relabelling a real hardware or plan field into one of them makes it
    invisible to every other test in this file -- and nothing else here would
    object, because the rest reason about HARDWARE and the plan sets.  I found
    this by trying it: marking `bus_mass_kg` as META defeated the whole file.

    So the exemptions are enumerated, not open.  Growing one is a deliberate
    edit here, with a reason, rather than a one-word change in the registry.
    """
    assert _own(fr.BOOSTER_FIELD_OWNER, fr.META) == {
        'name', 'source', 'notes', 'stage2'}
    assert _own(fr.RO_FIELD_OWNER, fr.META) == {'name', 'source', 'notes'}
    # recomputed on load from other stored values, so stored nowhere
    assert _own(fr.BOOSTER_FIELD_OWNER, fr.DERIVED) == {'thrust_N'}
    assert _own(fr.RO_FIELD_OWNER, fr.DERIVED) == {'separation_mode'}
    # the attached object, resolved per run from the plan's `reentry_object`
    assert _own(fr.BOOSTER_FIELD_OWNER, fr.COMPOSED) == {'ro'}
    assert not _own(fr.RO_FIELD_OWNER, fr.COMPOSED)


def test_the_derived_key_order_is_the_file_format():
    """Registry ORDER is a file format, so pin it.

    `extract_flight_plan` builds its dict by iterating these tuples and
    `save_flight_plan` writes it without sorting, so the order of entries in
    field_registry is literally the key order of every plan file Thrusty
    writes.  The registry is grouped under section comments, which invites
    tidying; re-ordering it would silently rewrite every saved plan.  This
    also catches a member quietly joining a tuple -- which is how
    `_RUN_LOADOUT_KEYS` grew from 2 to 4 during this very refactor, correctly
    but unnoticed."""
    assert mm._FLIGHT_PLAN_TOP_KEYS == (
        'guidance', 'burnout_angle_deg', 'loft_angle_rate_deg_s',
        'launch_elevation_deg', 'shroud_jettison_alt_km', 'booster_jettison_s',
        'booster_core_delay_s')
    assert mm._FLIGHT_PLAN_STAGE_KEYS == (
        'stage_turn_start_s', 'stage_turn_stop_s', 'stage_burnout_angle_deg',
        'coast_time_s', 'stage_cutoff_s', 'stage_yaw_start_s',
        'stage_yaw_stop_s', 'stage_yaw_final_az_deg',
        'grid_fin_deploy_schedule', 'interstage_jettison_s')
    assert mm._REENTRY_PLAN_KEYS == (
        'glider_enabled', 'glider_guidance', 'glider_pullup_g_max',
        'glider_terminal_dive', 'glider_terminal_alt_km',
        'glider_bank_schedule', 'glider_dive_target_lat_deg',
        'glider_dive_target_lon_deg', 'glider_dive_target_radius_km',
        'glider_skip_count', 'glider_damping_zeta',
        'glider_flap_deflection_deg', 'glider_pullup_start_alt_km',
        'glider_aero_model', 'reentry_attitude')
    # Written to no file, so order is free; membership is not.
    assert set(mm._RUN_LOADOUT_KEYS) == {
        'payload_kg', 'num_ros', 'ro_mass_kg', 'body_payload_kg'}


def test_every_owner_is_a_real_one():
    """Guards against a typo silently creating a new, unenforced category."""
    known = {fr.HARDWARE, fr.FLIGHT_PLAN_TOP, fr.FLIGHT_PLAN_STAGE,
             fr.REENTRY_PLAN, fr.RUN_LOADOUT, fr.DERIVED, fr.META, fr.COMPOSED}
    for label, registry in (('BOOSTER_FIELD_OWNER', fr.BOOSTER_FIELD_OWNER),
                            ('RO_FIELD_OWNER', fr.RO_FIELD_OWNER)):
        bad = {k: v for k, v in registry.items() if v not in known}
        assert not bad, f"field_registry.{label} uses unknown owners: {bad}"
    # the object side has no flight-plan fields and the booster side no
    # reentry-plan fields; a field on the wrong registry is a category error
    assert not _own(fr.RO_FIELD_OWNER, fr.FLIGHT_PLAN_TOP, fr.FLIGHT_PLAN_STAGE)
    assert not _own(fr.BOOSTER_FIELD_OWNER, fr.REENTRY_PLAN)


def test_the_serialisers_agree_with_the_registry():
    """The registry is only a single source of truth if the writers follow it.

    `booster_to_dict` and `ro_to_dict` are hand-written dict literals, so they
    can drift from the field list. Any hardware field they never write is a
    value that silently fails to round-trip through a library file."""
    b = get_booster("Scud-B (R-17)")
    unwritten = BOOSTER_HARDWARE - set(booster_to_dict(b))
    assert not unwritten, (
        f"booster_to_dict does not write hardware fields {sorted(unwritten)}; "
        f"they cannot survive a save/load round trip. Either serialise them, "
        f"or say in field_registry what they really are — this is how "
        f"ro_mass_kg, body_payload_kg and thrust_N were found to be loadout "
        f"bookkeeping and a derived value rather than hardware.")
    ro = ROParams(name="x", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                  diameter_m=0.5, length_m=1.0)
    assert not (RO_HARDWARE - set(ro_to_dict(ro))), (
        f"ro_to_dict does not write hardware fields "
        f"{sorted(RO_HARDWARE - set(ro_to_dict(ro)))}")


# ── the shipped files ───────────────────────────────────────────────────────

# Flat reentry fields from before the object became its own file.  They are
# not plan keys and not booster hardware, so no key-set check saw them -- but
# `upgrade_booster_dict` still reconstructs a whole object, reentry plan and
# all, from `ro_beta_kg_m2` plus whichever of these are present.
LEGACY_OBJECT_KEYS = {
    'ro_beta_kg_m2', 'rv_beta_kg_m2', 'ro_mass_kg', 'rv_mass_kg',
    'ro_shape', 'rv_shape', 'ro_diameter_m', 'rv_diameter_m',
    'ro_length_m', 'rv_length_m', 'ro_nose_radius_m', 'rv_nose_radius_m',
}


def test_the_shipped_library_is_present():
    """Fails loudly where the parametrized checks would go quiet.

    Seven tests in this file are parametrized over a glob of the four data
    directories, and pytest SKIPS a parametrized test whose argument list is
    empty -- it does not fail.  So emptying those directories, or running
    pytest from another working directory, silently removes most of the
    enforcement while the run still reports green.  This is the one assertion
    that notices."""
    assert BOOSTER_FILES and RO_FILES and FLIGHT_PLAN_FILES and REENTRY_PLAN_FILES, (
        f"no library to check (wrong working directory, or the data was "
        f"removed): {len(BOOSTER_FILES)} boosters, {len(RO_FILES)} objects, "
        f"{len(FLIGHT_PLAN_FILES)} flight plans, "
        f"{len(REENTRY_PLAN_FILES)} reentry plans")


@pytest.mark.parametrize('path', BOOSTER_FILES)
def test_booster_file_is_hardware_only(path):
    d = json.load(open(path))
    for i, st in enumerate(_stages(d)):
        leaked = set(st) & (FLIGHT_PLAN_KEYS | REENTRY_PLAN_KEYS | DERIVED
                            | RUN_SCRATCH | LEGACY_OBJECT_KEYS)
        assert not leaked, f"{path} stage {i + 1} stores plan/derived/loadout keys {sorted(leaked)}"


def _nested_objects(node, path='$'):
    """Every reentry-object-shaped dict anywhere inside a booster dict.

    A walk, not a key lookup, because the reader takes an embedded object from
    more than one place: `booster_from_dict` accepts `rv` as an alias for `ro`,
    and a hand-edited or pre-rename file can nest one below the stage2 chain
    that `_stages` follows.  Shape, not name, is the test: anything carrying a
    ballistic coefficient or reentry-plan keys is an object.
    """
    def _is_object(v):
        return isinstance(v, dict) and ('beta_kg_m2' in v
                                        or bool(set(v) & REENTRY_PLAN_KEYS))

    if isinstance(node, dict):
        for k, v in node.items():
            if _is_object(v):
                yield f"{path}.{k}", v
            yield from _nested_objects(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if _is_object(v):
                yield f"{path}[{i}]", v
            yield from _nested_objects(v, f"{path}[{i}]")


@pytest.mark.parametrize('path', BOOSTER_FILES)
def test_booster_file_embeds_no_reentry_object(path):
    """Stack-only, checked INSIDE the file rather than across its top keys.

    Every other check here intersects a dict's own key set with the forbidden
    ones, which cannot see a nested object: `ro` is subtracted out of
    BOOSTER_HARDWARE and `_stages` follows only the stage2 chain.  An embedded
    object is a violation twice over -- reentry hardware living in a booster
    file, and (because it is written by the full object serialiser) that
    object's whole reentry plan with it."""
    found = list(_nested_objects(json.load(open(path))))
    assert not found, "; ".join(
        f"{path} embeds a reentry object at {where} "
        f"({obj.get('name', '?')}, plan keys "
        f"{sorted(set(obj) & REENTRY_PLAN_KEYS)})" for where, obj in found)


@pytest.mark.parametrize('path', RO_FILES)
def test_ro_file_is_hardware_only(path):
    d = json.load(open(path))
    leaked = set(d) & (REENTRY_PLAN_KEYS | DERIVED | {LINK_KEY})
    assert not leaked, f"{path} stores plan/derived/link keys {sorted(leaked)}"


@pytest.mark.parametrize('path', FLIGHT_PLAN_FILES)
def test_flight_plan_file_has_no_hardware(path):
    d = json.load(open(path))
    leaked = set(d) & (BOOSTER_HARDWARE | DERIVED | {LINK_KEY})
    assert not leaked, f"{path} stores hardware keys {sorted(leaked)}"
    for i, st in enumerate(d.get('stages', []) or []):
        leaked = set(st) & BOOSTER_HARDWARE
        assert not leaked, f"{path} stage {i + 1} stores hardware keys {sorted(leaked)}"


@pytest.mark.parametrize('path', REENTRY_PLAN_FILES)
def test_reentry_plan_file_has_no_hardware_or_separation(path):
    d = json.load(open(path))
    leaked = set(d) & (RO_HARDWARE | DERIVED | {LINK_KEY})
    assert not leaked, f"{path} stores hardware/derived/link keys {sorted(leaked)}"


# ── the serialisers hold the line for user-saved files too ──────────────────

def test_booster_serialiser_omits_plan_keys_at_every_level():
    p = get_booster("Scud-B (R-17)")
    p.interstage_jettison_s = 12.0
    p.booster_core_delay_s = 3.0
    p.grid_fin_deploy_schedule = [[3, 4]]
    d = booster_to_dict(p, include_flight_plan=False)
    for st in _stages(d):
        assert not (set(st) & FLIGHT_PLAN_KEYS)
    # ...and the full round-trip still carries them for in-memory use.
    q = booster_from_dict(booster_to_dict(p))
    assert q.interstage_jettison_s == 12.0 and q.booster_core_delay_s == 3.0


def test_hardware_only_booster_serialiser_drops_the_embedded_object():
    """Regression for the leak the file checks could not see.

    `booster_to_dict(..., include_flight_plan=False)` -- the form the library
    stores and Export Booster writes -- used to emit `d['ro']` from the FULL
    object serialiser, so a "hardware-only" booster carried the object's
    reentry hardware AND all of its plan keys: guidance, damping, bank
    schedule, dive target.  Worse on read-back, because `get_booster` resolves
    the plan-named object only when the booster has none of its own, so the
    stale embedded plan won over the object's real one, silently.

    The object belongs in its own file; the flight plan names it.

    Built from bare dataclasses on purpose: this holds the serialiser itself
    and keeps working with no library at all, where the file-parametrized
    checks above would go quiet (see test_the_shipped_library_is_present).
    """
    p = BoosterParams(name="T", mass_initial=1000.0, mass_propellant=700.0,
                      mass_final=300.0, diameter_m=1.0, length_m=8.0,
                      thrust_N=30e3, burn_time_s=60.0, isp_s=250.0)
    p.ro = ROParams(name="w", mass_kg=800.0, beta_kg_m2=5000.0, shape="cone",
                    diameter_m=0.88, length_m=2.0, maneuvering=True,
                    glider_LD=2.0, glider_enabled=True,
                    glider_guidance='skip_glide',
                    glider_dive_target_lat_deg=38.5,
                    glider_dive_target_lon_deg=127.1)
    d = booster_to_dict(p, include_flight_plan=False)
    for i, st in enumerate(_stages(d)):
        assert 'ro' not in st, (
            f"stage {i + 1} embeds the object, carrying "
            f"{sorted(set(st['ro']) & REENTRY_PLAN_KEYS)}")
    # the full (internal) form still round-trips it, plan and all
    q = booster_from_dict(booster_to_dict(p))
    assert q.ro is not None and q.ro.name == "w"
    assert q.ro.glider_guidance == 'skip_glide'


def test_export_import_round_trip_keeps_the_object_link():
    """Dropping the embedded object is only safe if the link comes back.

    Export writes a hardware-only booster plus a companion flight plan, and
    the plan NAMES the object.  The booster alone can no longer reconstruct
    it, so the name in the plan is the whole of the link: if a reader ignores
    it, the visible leak this change removed is replaced by a silent loss, and
    the vehicle flies as a bare stack.  Pin both halves.
    """
    name = FLIGHT_PLAN_NAMING_AN_OBJECT
    if not name:
        pytest.skip("no shipped plan names an object "
                    "(test_the_shipped_library_is_present is the signal)")
    p = get_booster(name)
    assert p.ro is not None, f"{name}'s plan should name an object"
    oname = p.ro.name

    # export: the object is gone from the booster, the plan carries the name
    d = booster_to_dict(p, include_flight_plan=False)
    assert 'ro' not in d
    fp = dict(extract_flight_plan(p), reentry_object=oname)

    # import: the booster alone really has lost it...
    q = booster_from_dict(d)
    assert q.ro is None
    assert apply_flight_plan(q, fp).ro is None, (
        "apply_flight_plan copies guidance keys, not the object link — "
        "a reader must resolve 'reentry_object' itself")
    # ...and the name in the plan is enough to get it back
    back = mm.resolve_reentry_object(fp['reentry_object'], extra_dirs=mm.USER_RO_DIRS)
    assert back is not None and back.name == oname


def test_ro_serialiser_never_writes_separation_mode():
    ro = ROParams(name="x", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                  diameter_m=0.5, length_m=1.0, separation_mode="body")
    assert 'separation_mode' not in ro_to_dict(ro)
    assert 'separation_mode' not in ro_to_dict(ro, include_reentry_plan=False)
    assert not (set(ro_to_dict(ro, include_reentry_plan=False)) & REENTRY_PLAN_KEYS)


def test_reentry_plan_extract_omits_separation_and_apply_ignores_legacy():
    ro = ROParams(name="x", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                  diameter_m=0.5, length_m=1.0)
    assert 'separation_mode' not in extract_reentry_plan(ro)
    q = apply_reentry_plan(ro, {'separation_mode': 'body'})   # legacy plan file
    assert q.separation_mode == 'separating_ro'


def test_flight_plan_carries_the_timings():
    p = get_booster("Scud-B (R-17)")
    fp = extract_flight_plan(p)
    assert 'booster_core_delay_s' in fp
    assert all('interstage_jettison_s' in st for st in fp['stages'])
    q = apply_flight_plan(p, {'booster_core_delay_s': 2.5,
                              'stages': [{'interstage_jettison_s': 7.0}]})
    assert q.booster_core_delay_s == 2.5 and q.interstage_jettison_s == 7.0
    assert p.booster_core_delay_s == 0.0          # source untouched


# ── the one link, and only that link ────────────────────────────────────────

def _pair(body_reenters, ro_mode):
    p = get_booster("Scud-B (R-17)")
    p.body_reenters = body_reenters
    ro = ROParams(name="w", mass_kg=800.0, beta_kg_m2=5000.0, shape="cone",
                  diameter_m=0.88, length_m=2.0, separation_mode=ro_mode)
    p = compose_loadout(p, ro, 1)
    p.ro = ro
    return p


@pytest.mark.parametrize('ro_mode', ['separating_ro', 'body'])
def test_booster_flag_decides_regardless_of_object(ro_mode):
    assert run_separation_mode(_pair(True, ro_mode)) == 'body'
    assert run_separation_mode(_pair(False, ro_mode)) == 'separating_ro'
    assert effective_ro(_pair(True, ro_mode)).separation_mode == 'body'
    assert effective_ro(_pair(False, ro_mode)).separation_mode == 'separating_ro'


def test_bind_stamps_the_object_without_mutating_the_caller():
    p = _pair(True, 'separating_ro')
    q = bind_ro_separation(p)
    assert q.ro.separation_mode == 'body'
    assert p.ro.separation_mode == 'separating_ro'      # caller untouched
    assert bind_ro_separation(q) is q                    # already bound: no copy


def test_body_reenters_forces_single_object_loadout():
    p = get_booster("Scud-B (R-17)")
    p.body_reenters = True
    ro = ROParams(name="w", mass_kg=800.0, beta_kg_m2=5000.0, shape="cone",
                  diameter_m=0.88, length_m=2.0)
    assert compose_loadout(p, ro, 3).num_ros == 1


# ── g-limit is hardware; the plan commands at or below it ───────────────────

def test_beta_S_is_hardware_and_pullup_g_is_clamped_to_the_limit():
    assert 'glider_beta_entry_kg_m2' not in REENTRY_PLAN_KEYS
    assert 'glider_beta_entry_kg_m2' in RO_HARDWARE
    assert 'pullup_g_limit' in RO_HARDWARE and 'pullup_g_limit' not in REENTRY_PLAN_KEYS
    ro = ROParams(name="x", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                  diameter_m=0.5, length_m=1.0, pullup_g_limit=8.0,
                  glider_beta_entry_kg_m2=7.0)
    assert apply_reentry_plan(ro, {'glider_pullup_g_max': 30.0}).glider_pullup_g_max == 8.0
    assert apply_reentry_plan(ro, {'glider_pullup_g_max': 5.0}).glider_pullup_g_max == 5.0
    assert apply_reentry_plan(ro, {}).glider_pullup_g_max <= 8.0
    # an UNSET limit (0, the default) is unlimited: the plan's command stands
    free = ROParams(name="y", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                    diameter_m=0.5, length_m=1.0)
    assert free.pullup_g_limit == 0.0
    assert apply_reentry_plan(free, {'glider_pullup_g_max': 30.0}).glider_pullup_g_max == 30.0
    # a legacy plan carrying beta_S is ignored; the object's value stands
    assert apply_reentry_plan(ro, {'glider_beta_entry_kg_m2': 99.0}).glider_beta_entry_kg_m2 == 7.0
    # and both survive the hardware-only serialiser
    d = ro_to_dict(ro, include_reentry_plan=False)
    assert d['pullup_g_limit'] == 8.0 and d['glider_beta_entry_kg_m2'] == 7.0


# ── booster files are stack-only; the object owns its mass ──────────────────

def _legacy(payload, baked):
    """A pre-2026-09 booster dict: design payload inside every stage's launch
    mass and, when 'baked' (ro_separates False, Scud class), inside the last
    stage's burnout mass too."""
    d = booster_to_dict(get_booster("No-dong"))          # a separating stack
    node = d
    while node is not None:
        node['mass_initial'] += payload
        last = node
        node = node.get('stage2')
    if baked:
        last['mass_final'] += payload
    d['payload_kg'] = payload
    d['ro_separates'] = not baked
    return d


@pytest.mark.parametrize('baked', [False, True])
def test_legacy_payload_is_normalised_on_load_and_reproduced_by_composition(baked):
    clean = get_booster("No-dong")
    p = booster_from_dict(_legacy(1000.0, baked))
    # loaded chain is stack-only: same masses as the shipped (clean) file
    assert p.payload_kg == 0.0
    assert p.mass_initial == pytest.approx(clean.mass_initial)
    assert p.mass_final == pytest.approx(clean.mass_final)
    # composing the object that carries the mass reproduces the legacy launch mass
    ro = ROParams(name="w", mass_kg=1000.0, beta_kg_m2=5000.0, shape="cone",
                  diameter_m=1.32, length_m=1.0)
    c = compose_loadout(p, ro, 1)
    assert c.mass_initial == pytest.approx(clean.mass_initial + 1000.0)
    assert c.payload_kg == 1000.0


def test_hardware_only_booster_serialiser_omits_the_loadout_record():
    p = compose_loadout(get_booster("No-dong"),                # separating stack
                        ROParams(name="w", mass_kg=800.0, beta_kg_m2=5000.0,
                                 shape="cone", diameter_m=0.84, length_m=1.0), 2)
    assert p.payload_kg == 1600.0 and p.num_ros == 2
    d = booster_to_dict(p, include_flight_plan=False)
    assert not (set(d) & RUN_SCRATCH)
    # the full (internal) form still round-trips the record
    q = booster_from_dict(booster_to_dict(p))
    assert q.num_ros == 2


@pytest.mark.parametrize('path', FLIGHT_PLAN_FILES)
def test_plan_named_reentry_object_resolves(path):
    """A flight plan may name the object it flies; when it does, the object
    must ship (every default run that used to fly a stored payload now flies
    a real object)."""
    name = json.load(open(path)).get('reentry_object', '')
    if not name:
        return
    shipped = {json.load(open(f))['name'] for f in RO_FILES}
    assert name in shipped, f"{path} names '{name}', which is not in ro_library/"


def test_non_separating_shipped_boosters_carry_their_warhead_as_object_payload():
    """Scud-B and Al Hussein do not separate: the booster is body_reenters and
    the flight plan names a front-end object whose payload_kg is the warhead."""
    for bname in ("Scud-B (R-17)", "Al Hussein"):
        b = get_booster(bname)
        assert b.body_reenters is True
        oname = mm.load_flight_plan(bname)['reentry_object']
        ro = next(ro_from_dict(json.load(open(f))) for f in RO_FILES
                  if json.load(open(f))['name'] == oname)
        assert ro.payload_kg > 0 and ro.beta_kg_m2 == 0.0     # warhead rides; beta derived
        c = compose_loadout(b, ro, 1)
        assert c.mass_initial == pytest.approx(b.mass_initial + ro.payload_kg)
        assert c.mass_final == pytest.approx(b.mass_final + ro.payload_kg)


def test_headless_get_booster_attaches_the_plan_named_object_and_flies_its_mass():
    """A flight plan that names its object is honoured headless too: get_booster
    attaches it, and integrate_trajectory composes it onto the stack-only
    chain, so a 'bare' run carries the same front end the GUI default flies."""
    from trajectory import integrate_trajectory
    p = get_booster("No-dong")
    assert p.ro is not None and p.ro.name == "No-dong warhead"
    assert p.payload_kg == 0.0                       # stack-only until composed
    r = integrate_trajectory(p, 39.12, 125.67, 90.0, max_time_s=1200.0)
    assert r["range_km"] > 0
    # a booster whose plan names no object stays bare
    assert get_booster("Shahab-3").ro is None


# ── capability (object) vs intent (plan) ────────────────────────────────────

def test_plan_cannot_glide_a_non_maneuvering_object():
    """maneuvering is hardware; glider_enabled is plan intent clamped by it."""
    assert 'maneuvering' in RO_HARDWARE and 'maneuvering' not in REENTRY_PLAN_KEYS
    assert 'glider_enabled' in REENTRY_PLAN_KEYS
    can = ROParams(name="g", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                   diameter_m=0.5, length_m=1.0, maneuvering=True, glider_LD=2.0)
    cannot = ROParams(name="b", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                      diameter_m=0.5, length_m=1.0, maneuvering=False, glider_LD=2.0)
    assert apply_reentry_plan(can, {'glider_enabled': True}).glider_enabled is True
    assert apply_reentry_plan(cannot, {'glider_enabled': True}).glider_enabled is False
    assert apply_reentry_plan(can, {'glider_enabled': False}).glider_enabled is False


def test_legacy_object_file_derives_capability():
    """A file from before the split declared capability implicitly."""
    base = dict(name="x", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                diameter_m=0.5, length_m=1.0)
    assert ro_from_dict({**base, 'glider_LD': 1.8}).maneuvering is True
    assert ro_from_dict({**base, 'glider_enabled': True}).maneuvering is True
    assert ro_from_dict({**base, 'wing_area_m2': 0.3}).maneuvering is True
    assert ro_from_dict(base).maneuvering is False
    assert ro_from_dict({**base, 'glider_LD': 1.8, 'maneuvering': False}).maneuvering is False


@pytest.mark.parametrize('path', RO_FILES)
def test_shipped_object_declares_capability_consistently(path):
    d = json.load(open(path))
    assert 'maneuvering' in d, f"{path} lacks the maneuvering capability flag"
    rp = mm.load_reentry_plan(d['name']) or {}
    if rp.get('glider_enabled'):
        assert d['maneuvering'] is True, f"{path}: plan glides an object that cannot"


# ── nothing in a shipped file is unaccounted for ────────────────────────────
# The checks above ask whether a key is on the WRONG side.  This asks the
# other question: is it on any side at all?  A key nobody has classified is
# how the rule erodes -- it is read by whatever happens to look for it, it
# survives every round trip, and no test objects.  Shipped files are
# current-schema by rule (CLAUDE.md: compatibility lives only in the
# upgraders), so an old spelling here is a defect too, not just an unknown.

FILE_META = set(fr.FILE_META)
BOOSTER_FILE_KEYS = set(fr.BOOSTER_FIELD_OWNER) | FILE_META
RO_FILE_KEYS = set(fr.RO_FIELD_OWNER) | FILE_META
FLIGHT_PLAN_FILE_KEYS = (set(mm._FLIGHT_PLAN_TOP_KEYS) | set(fr.PLAN_FILE_META)
                         | FILE_META)
REENTRY_PLAN_FILE_KEYS = (set(mm._REENTRY_PLAN_KEYS) | set(fr.PLAN_FILE_META)
                          | set(fr.PLAN_ONLY_KEYS) | FILE_META)

_UNKNOWN_HELP = (
    "Give it an owner in field_registry if it is a real field; if it is an "
    "older spelling, it belongs only in a user file, because shipped files "
    "are current-schema and compatibility lives in upgrade_booster_dict / "
    "upgrade_ro_dict.")


def _unknown(path, where, keys, allowed):
    extra = sorted(set(keys) - allowed)
    return (f"{path} {where} carries {extra}, which no registry accounts for. "
            f"{_UNKNOWN_HELP}") if extra else ""


@pytest.mark.parametrize('path', BOOSTER_FILES)
def test_booster_file_has_no_unknown_keys(path):
    d = json.load(open(path))
    for i, st in enumerate(_stages(d)):
        msg = _unknown(path, f"stage {i + 1}", st, BOOSTER_FILE_KEYS)
        assert not msg, msg


@pytest.mark.parametrize('path', RO_FILES)
def test_object_file_has_no_unknown_keys(path):
    msg = _unknown(path, "", json.load(open(path)), RO_FILE_KEYS)
    assert not msg, msg


@pytest.mark.parametrize('path', FLIGHT_PLAN_FILES)
def test_flight_plan_file_has_no_unknown_keys(path):
    d = json.load(open(path))
    msg = _unknown(path, "", d, FLIGHT_PLAN_FILE_KEYS)
    assert not msg, msg
    for i, st in enumerate(d.get('stages') or []):
        msg = _unknown(path, f"stage {i + 1}", st, set(mm._FLIGHT_PLAN_STAGE_KEYS))
        assert not msg, msg


@pytest.mark.parametrize('path', REENTRY_PLAN_FILES)
def test_reentry_plan_file_has_no_unknown_keys(path):
    msg = _unknown(path, "", json.load(open(path)), REENTRY_PLAN_FILE_KEYS)
    assert not msg, msg


def test_the_serialisers_write_only_accounted_keys():
    """The walk above guards the files that exist; this guards the ones the
    program will write next.  A serialiser that emits a key no registry knows
    would seed exactly what the walk is there to catch."""
    b = get_booster("Scud-B (R-17)")
    for form in (booster_to_dict(b), booster_to_dict(b, include_flight_plan=False)):
        for i, st in enumerate(_stages(form)):
            assert not (set(st) - BOOSTER_FILE_KEYS), (
                f"booster_to_dict stage {i + 1} writes "
                f"{sorted(set(st) - BOOSTER_FILE_KEYS)}")
    ro = ROParams(name="x", mass_kg=1.0, beta_kg_m2=1.0, shape="cone",
                  diameter_m=0.5, length_m=1.0)
    for form in (ro_to_dict(ro), ro_to_dict(ro, include_reentry_plan=False)):
        assert not (set(form) - RO_FILE_KEYS), (
            f"ro_to_dict writes {sorted(set(form) - RO_FILE_KEYS)}")
    fp = extract_flight_plan(b)
    assert not (set(fp) - FLIGHT_PLAN_FILE_KEYS), (
        f"extract_flight_plan writes {sorted(set(fp) - FLIGHT_PLAN_FILE_KEYS)}")
    for st in fp.get('stages') or []:
        assert not (set(st) - set(mm._FLIGHT_PLAN_STAGE_KEYS))
    rp = extract_reentry_plan(ro)
    assert not (set(rp) - REENTRY_PLAN_FILE_KEYS), (
        f"extract_reentry_plan writes {sorted(set(rp) - REENTRY_PLAN_FILE_KEYS)}")


# ── which shipped files a saved copy is standing in front of ────────────────

def _lib(tmp_path, kind, name, payload):
    d = tmp_path / kind
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(payload))
    return str(d)


def test_no_user_directories_means_nothing_is_shadowed():
    """The headless default. A golden-output run must be able to assert it is
    reading shipped data and nothing else."""
    s = mm.shadowed_library_entries(flight_plan_dirs=[], reentry_plan_dirs=[],
                                    ro_dirs=[])
    assert s == {'flight_plan': {}, 'reentry_plan': {}, 'reentry_object': {}}
    assert mm.describe_shadows(s) == ""


def test_a_saved_copy_of_a_shipped_plan_is_reported(tmp_path):
    """The case that went unnoticed in use: a saved reentry plan overriding a
    shipped one decided what flew, and nothing said so."""
    name = json.load(open(REENTRY_PLAN_FILES[0]))
    stem = REENTRY_PLAN_FILES[0].split('/')[-1]
    d = _lib(tmp_path, "reentry_plans", stem, dict(name or {}, glider_enabled=False))
    s = mm.shadowed_library_entries(flight_plan_dirs=[], reentry_plan_dirs=[d],
                                    ro_dirs=[])
    key = stem[:-len(".reentryplan.json")]
    assert key in s['reentry_plan']
    shipped, user = s['reentry_plan'][key]
    assert shipped.endswith(stem) and user.endswith(stem)
    assert shipped != user
    assert key in mm.describe_shadows(s)


def test_a_user_file_with_no_shipped_counterpart_is_not_a_shadow(tmp_path):
    """Adding is not replacing.  Flagging every user file would bury the ones
    that actually stand in front of something."""
    d = _lib(tmp_path, "reentry_plans", "Nothing_Like_It.reentryplan.json",
             {"glider_enabled": True})
    s = mm.shadowed_library_entries(flight_plan_dirs=[], reentry_plan_dirs=[d],
                                    ro_dirs=[])
    assert s['reentry_plan'] == {}


def test_a_named_variant_is_not_a_shadow(tmp_path):
    """A variant is a deliberate, separately-listed artifact chosen from a
    dropdown.  Only the DEFAULT slot can stand in front of a shipped file."""
    stem = REENTRY_PLAN_FILES[0].split('/')[-1][:-len(".reentryplan.json")]
    d = _lib(tmp_path, "reentry_plans", f"{stem}__my_variant.reentryplan.json",
             {"glider_enabled": False})
    s = mm.shadowed_library_entries(flight_plan_dirs=[], reentry_plan_dirs=[d],
                                    ro_dirs=[])
    assert s['reentry_plan'] == {}


def test_an_object_is_matched_on_its_name_not_its_filename(tmp_path):
    """Objects are keyed by the `name` field, which is what RO_DB uses, so a
    renamed file still shadows and an identically-named file in a different
    filename does too."""
    # from ro_library/ specifically: RO_FILES also globs loose root-level
    # objects, which `_load_ro_library` never reads and so cannot be shadowed
    library = sorted(glob.glob('ro_library/*.ro.json'))
    shipped = json.load(open(library[0]))
    d = _lib(tmp_path, "ro_library", "renamed_on_disk.ro.json",
             dict(shipped, mass_kg=1.0))
    s = mm.shadowed_library_entries(flight_plan_dirs=[], reentry_plan_dirs=[],
                                    ro_dirs=[d])
    assert shipped['name'] in s['reentry_object']


def test_the_same_directory_twice_is_not_a_shadow_of_itself(tmp_path):
    """Running in place points a user directory at the bundled one.  It must
    not report every shipped file as overriding itself."""
    import os
    bundled = os.path.dirname(os.path.abspath(REENTRY_PLAN_FILES[0]))
    s = mm.shadowed_library_entries(flight_plan_dirs=[],
                                    reentry_plan_dirs=[bundled], ro_dirs=[])
    assert s['reentry_plan'] == {}
