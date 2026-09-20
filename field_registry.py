"""Who owns every field — the one place the four-inputs rule is declared.

Thrusty composes a run from four files: two hardware (booster, reentry
object) and two plan (flight plan, reentry plan).  A hardware file carries no
plan key and a plan file carries no hardware key; nothing is stored twice.

That rule used to be spread across four hand-maintained key tuples, two
hand-written serialiser literals and the test's own sets, with **hardware
defined by subtraction** -- everything nobody had listed as a plan key.  The
consequence was that forgetting to classify a new field was not an error but
a silent decision: the field became hardware, the test that claimed to check
for overlap could not fail (an intersection with a set built by subtracting
that same set is empty by construction), and a timing or guidance value could
settle into a hardware file unnoticed.  That is how the rule came to be, in
the project owner's words, unenforceable.

So ownership is ENUMERATED here instead, one entry per dataclass field, and
everything else is derived from it.  A new field with no entry fails
`test_input_split.py` rather than defaulting to anything.

Two registries, not one: `payload_kg` is a run-time loadout record on a
booster and the warhead mass a non-separating object carries, so a single
table keyed by field name would have to lie about one of them.

Owners
------
HARDWARE            the thing itself; belongs in the .booster.json / .ro.json
FLIGHT_PLAN_TOP     whole-vehicle guidance; belongs in the .flightplan.json
FLIGHT_PLAN_STAGE   the per-stage schedule, inside that plan's `stages` list
REENTRY_PLAN        how an object is flown; belongs in the .reentryplan.json
RUN_LOADOUT         composed per run from booster + object + count; stored in
                    no file
DERIVED             computed at run time from another file's value
META                identity and provenance; exempt from the split, allowed
                    on either side
COMPOSED            an attached sub-object, resolved for a run rather than
                    stored (the booster's `ro`)

This file is pure data and imports nothing, so the dataclasses, the
serialisers and the tests can all derive from it without a cycle.

ORDER MATTERS.  The plan-key tuples are derived by filtering these dicts in
insertion order, and `extract_flight_plan` / `extract_reentry_plan` build
their dicts by iterating those tuples, which are then written unsorted.  So
the order of entries below is the key order of every plan file Thrusty
writes.  Re-ordering a section to tidy it would rewrite every saved plan.
`test_the_derived_key_order_is_the_file_format` pins it.
"""

HARDWARE = 'hardware'
FLIGHT_PLAN_TOP = 'flight_plan_top'
FLIGHT_PLAN_STAGE = 'flight_plan_stage'
REENTRY_PLAN = 'reentry_plan'
RUN_LOADOUT = 'run_loadout'
DERIVED = 'derived'
META = 'meta'
COMPOSED = 'composed'


BOOSTER_FIELD_OWNER = {
    # ── flight plan: the whole-vehicle guidance decisions ──────────────
    'guidance':                        FLIGHT_PLAN_TOP,
    'burnout_angle_deg':               FLIGHT_PLAN_TOP,
    'loft_angle_rate_deg_s':           FLIGHT_PLAN_TOP,
    'launch_elevation_deg':            FLIGHT_PLAN_TOP,
    'shroud_jettison_alt_km':          FLIGHT_PLAN_TOP,
    'booster_jettison_s':              FLIGHT_PLAN_TOP,
    'booster_core_delay_s':            FLIGHT_PLAN_TOP,
    # ── flight plan: the per-stage schedule ────────────────────────────
    #   Timings are plan data even when the thing that moves is hardware:
    #   grid fins are hardware, WHEN they deploy is the flight plan.
    'stage_turn_start_s':              FLIGHT_PLAN_STAGE,
    'stage_turn_stop_s':               FLIGHT_PLAN_STAGE,
    'stage_burnout_angle_deg':         FLIGHT_PLAN_STAGE,
    'coast_time_s':                    FLIGHT_PLAN_STAGE,
    'stage_cutoff_s':                  FLIGHT_PLAN_STAGE,
    'stage_yaw_start_s':               FLIGHT_PLAN_STAGE,
    'stage_yaw_stop_s':                FLIGHT_PLAN_STAGE,
    'stage_yaw_final_az_deg':          FLIGHT_PLAN_STAGE,
    'grid_fin_deploy_schedule':        FLIGHT_PLAN_STAGE,
    'interstage_jettison_s':           FLIGHT_PLAN_STAGE,
    # ── run loadout: composed per run, never stored on the booster ─────
    #   compose_loadout stamps these from booster + object + count.  The
    #   dataclass says so of the last two: "run-level loadout bookkeeping
    #   ... NOT reentry-object hardware" and "Runtime bookkeeping only; not
    #   serialised".  They were hardware only because no tuple listed them.
    'payload_kg':                      RUN_LOADOUT,
    'num_ros':                         RUN_LOADOUT,
    'ro_mass_kg':                      RUN_LOADOUT,
    'body_payload_kg':                 RUN_LOADOUT,
    # ── meta: identity and provenance, exempt from the split ───────────
    'name':                            META,
    'source':                          META,
    'notes':                           META,
    'stage2':                          META,
    # ── derived: recomputed on load ────────────────────────────────────
    #   No .booster.json carries thrust_N; booster_from_dict recomputes it
    #   from Isp, propellant mass and burn time (_thrust_from_isp).  Note the
    #   XLSX path DOES round-trip a thrust column, and booster_from_dict
    #   discards it on the way back in — a pre-existing lossy path, recorded
    #   in TODO.md, not something this label endorses.
    'thrust_N':                        DERIVED,
    # ── composed: the object attached for a run, resolved from the plan ─
    'ro':                              COMPOSED,
    # ── hardware: the stack itself ─────────────────────────────────────
    'mass_initial':                    HARDWARE,
    'mass_propellant':                 HARDWARE,
    'mass_final':                      HARDWARE,
    'diameter_m':                      HARDWARE,
    'length_m':                        HARDWARE,
    'burn_time_s':                     HARDWARE,
    'isp_s':                           HARDWARE,
    'nozzle_exit_area_m2':             HARDWARE,
    'n_nozzles':                       HARDWARE,
    'nozzle_area_each_m2':             HARDWARE,
    'mach_table':                      HARDWARE,
    'cd_table':                        HARDWARE,
    'bus_mass_kg':                     HARDWARE,
    'body_reenters':                   HARDWARE,
    'solid_motor':                     HARDWARE,
    'grain_type':                      HARDWARE,
    'thrust_peak_N':                   HARDWARE,
    'thrust_profile':                  HARDWARE,
    'conical':                         HARDWARE,
    'top_diameter_m':                  HARDWARE,
    'has_interstage':                  HARDWARE,
    'interstage_length_m':             HARDWARE,
    'interstage_mass_kg':              HARDWARE,
    'shroud_mass_kg':                  HARDWARE,
    'shroud_length_m':                 HARDWARE,
    'shroud_diameter_m':               HARDWARE,
    'nose_shape':                      HARDWARE,
    'nose_length_m':                   HARDWARE,
    'shroud_nose_shape':               HARDWARE,
    'shroud_nose_length_m':            HARDWARE,
    'aerospike_LD':                    HARDWARE,
    'aerospike_dD':                    HARDWARE,
    'has_fins':                        HARDWARE,
    'n_fins':                          HARDWARE,
    'fin_span_m':                      HARDWARE,
    'fin_root_chord_m':                HARDWARE,
    'fin_tip_chord_m':                 HARDWARE,
    'fin_thickness_m':                 HARDWARE,
    'fin_sweep_deg':                   HARDWARE,
    'has_grid_fins':                   HARDWARE,
    'n_grid_fins':                     HARDWARE,
    'grid_fin_width_m':                HARDWARE,
    'grid_fin_height_m':               HARDWARE,
    'grid_fin_chord_m':                HARDWARE,
    'grid_fin_web_thickness_m':        HARDWARE,
    'grid_fin_cell_pitch_m':           HARDWARE,
    'grid_fin_solidity':               HARDWARE,
    'grid_fin_edge_factor':            HARDWARE,
    'payload_diameter_m':              HARDWARE,
    'pbv_diameter_m':                  HARDWARE,
    'pbv_length_m':                    HARDWARE,
    'n_boosters':                      HARDWARE,
    'booster_thrust_n':                HARDWARE,
    'booster_burn_time_s':             HARDWARE,
    'booster_inert_kg':                HARDWARE,
    'booster_prop_kg':                 HARDWARE,
    'booster_isp_s':                   HARDWARE,
    'booster_nozzle_area_m2':          HARDWARE,
    'booster_diam_m':                  HARDWARE,
    'booster_length_m':                HARDWARE,
    'booster_cd':                      HARDWARE,
}

RO_FIELD_OWNER = {
    # ── reentry plan: how the object is flown ──────────────────────────
    'glider_enabled':                  REENTRY_PLAN,
    'glider_guidance':                 REENTRY_PLAN,
    'glider_pullup_g_max':             REENTRY_PLAN,
    'glider_terminal_dive':            REENTRY_PLAN,
    'glider_terminal_alt_km':          REENTRY_PLAN,
    'glider_bank_schedule':            REENTRY_PLAN,
    'glider_dive_target_lat_deg':      REENTRY_PLAN,
    'glider_dive_target_lon_deg':      REENTRY_PLAN,
    'glider_dive_target_radius_km':    REENTRY_PLAN,
    'glider_skip_count':               REENTRY_PLAN,
    'glider_damping_zeta':             REENTRY_PLAN,
    'glider_flap_deflection_deg':      REENTRY_PLAN,
    'glider_pullup_start_alt_km':      REENTRY_PLAN,
    'glider_aero_model':               REENTRY_PLAN,
    'reentry_attitude':                REENTRY_PLAN,
    # ── derived at run time from the booster's body_reenters flag ──────
    'separation_mode':                 DERIVED,
    # ── meta ───────────────────────────────────────────────────────────
    'name':                            META,
    'source':                          META,
    'notes':                           META,
    # ── hardware: the airframe ─────────────────────────────────────────
    'mass_kg':                         HARDWARE,
    'beta_kg_m2':                      HARDWARE,
    'shape':                           HARDWARE,
    'diameter_m':                      HARDWARE,
    'length_m':                        HARDWARE,
    'nose_radius_m':                   HARDWARE,
    'biconic':                         HARDWARE,
    'fore_length_m':                   HARDWARE,
    'break_diameter_m':                HARDWARE,
    'body_form':                       HARDWARE,
    'body_span_m':                     HARDWARE,
    'body_nose_length_m':              HARDWARE,
    'reentry_cg_m':                    HARDWARE,
    'payload_kg':                      HARDWARE,
    'maneuvering':                     HARDWARE,
    'glider_LD':                       HARDWARE,
    'wing_area_m2':                    HARDWARE,
    'wing_aspect_ratio':               HARDWARE,
    'wing_root_chord_m':               HARDWARE,
    'wing_span_exposed_m':             HARDWARE,
    'wing_sweep_deg':                  HARDWARE,
    'wing_thickness_m':                HARDWARE,
    'n_wings':                         HARDWARE,
    'trim_alpha_deg':                  HARDWARE,
    'trim_CL0':                        HARDWARE,
    'pullup_g_limit':                  HARDWARE,
    'glider_beta_entry_kg_m2':         HARDWARE,
    'glider_control_surfaces':         HARDWARE,
    'glider_flap_area_ratio':          HARDWARE,
    'emissivity':                      HARDWARE,
    'tps_material':                    HARDWARE,
    'nose_tps_material':               HARDWARE,
    'body_tps_material':               HARDWARE,
    'body_tps_thickness_m':            HARDWARE,
    'structure_material':              HARDWARE,
    'structure_limit_K':               HARDWARE,
    'nose_tps_custom':                 HARDWARE,
    'body_tps_custom':                 HARDWARE,
}

# Keys a PLAN file may carry that are not fields of any dataclass: the plan's
# own identity, the per-stage list, and the name of the object a flight plan
# flies (the one booster-to-object link the rule allows).
PLAN_FILE_META = frozenset({
    'booster', 'base_plan', 'stages', 'reentry_object', 'source', 'notes',
})

# A plan value with no dataclass field behind it.  `extract_reentry_plan`
# writes commanded_LD from the object's glider_LD capability, and
# `apply_reentry_plan` clamps it back to that capability -- so a plan can fly
# an object worse than its airframe allows, never better.  Declared here
# because every shipped reentry plan carries it and the unknown-key walk
# would otherwise have to special-case it.
PLAN_ONLY_KEYS = frozenset({'commanded_LD'})


def _named(registry, owner):
    """Field names with this owner, in registry order."""
    return tuple(k for k, v in registry.items() if v == owner)
