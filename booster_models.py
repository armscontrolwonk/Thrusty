"""
Booster parameter models matching Forden's:
  missileMass.m, missileRadius.m, thrust.m, thrustAngle.m,
  dragForce.m, Drag.m, calcCm_delta.m, aeroQ.m, calcMissileParameters.m

Built-in booster definitions follow Forden (2007) Table 1 parameters for the
four packaged models: Scud-B, Al Hussein, No-dong, and Taepodong-I.
Loft angle / loft angle rate for Scud-B taken from Figure 3 of the same paper.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from atmosphere import (atmosphere, dynamic_pressure,
                        configure_atmosphere, atmosphere_source)

_G0 = 9.80665   # standard gravity (m/s²)


def _thrust_from_isp(isp_s: float, propellant_kg: float, burn_s: float) -> float:
    """Vacuum thrust (N) derived from Isp, propellant mass, and burn time."""
    return isp_s * _G0 * propellant_kg / burn_s


@dataclass
class BoosterParams:
    """All parameters needed to simulate one booster type."""
    name: str

    # Mass (kg)
    mass_initial: float       # launch mass (structure + propellant + payload)
    mass_propellant: float    # propellant mass
    mass_final: float         # burnout mass (structure + payload)

    # Geometry
    diameter_m: float         # body diameter (m)
    length_m: float           # body length (m)

    # Propulsion
    thrust_N: float           # vacuum thrust (N)
    burn_time_s: float        # powered flight duration (s)
    isp_s: float              # specific impulse (s)

    # Nozzle exit area (m²).  When > 0, thrust at altitude is computed as
    # T(h) = T_vac − P_amb(h) × Ae  (proper pressure-thrust correction).
    # When 0, a legacy 2 % sea-level back-pressure approximation is used.
    # This is the TOTAL exit area — the only quantity the physics needs, and
    # what the Estimate button fills.
    nozzle_exit_area_m2: float = 0.0
    # Nozzle COUNT and per-nozzle area — geometry only (the 3-D export draws
    # n_nozzles disks on the base).  When nozzle_area_each_m2 > 0 the TOTAL
    # is nozzle_area_each_m2 × n_nozzles (per-nozzle drives total); otherwise
    # each = total / n_nozzles is derived (total from Estimate drives each).
    n_nozzles:           int   = 1
    nozzle_area_each_m2: float = 0.0

    # Guidance mode
    #   "loft"         — Forden pitch-over (SRBM/MRBM): pitch to burnout_angle_deg
    #                    at loft_angle_rate_deg_s then hold.  Floor preserved.
    #   "pitch_program" — kick off vertical to burnout_angle_deg at
    #                    loft_angle_rate_deg_s, then lock thrust to velocity
    #                    vector (IRBM/ICBM).  burnout_angle_deg here is the kick
    #                    elevation (°, above horizontal; e.g. 85° = 5° from
    #                    vertical) and loft_angle_rate_deg_s is the kick rate.
    guidance: str = "pitch_program"

    burnout_angle_deg: float = 45.0        # Forden: final elev (°); GT: kick elev (°)
    loft_angle_rate_deg_s: float = 2.0  # Forden: pitch rate (°/s); GT: kick rate
    launch_elevation_deg: float = 90.0  # elevation at liftoff (°); 90 = vertical

    # Aerodynamics — Cd vs Mach lookup table
    mach_table: list = field(default_factory=list)
    cd_table:   list = field(default_factory=list)

    # Staging (optional next stage)
    stage2: Optional['BoosterParams'] = None

    # Coast time (s) between this stage's burnout and the next stage's ignition.
    # Ignored (irrelevant) for the last / only stage.
    coast_time_s: float = 0.0

    # Payload (kg) — total front-end mass carried to burnout (bus + all RVs),
    # i.e. the throw weight as CURRENTLY COMPOSED.  A RUN-TIME record on the
    # top-level stage only, never stored: booster files are stack-only, the
    # reentry object owns its mass, and compose_loadout() sets this from the
    # selected object (bus + N × object mass), adjusting the stage launch
    # masses by the delta.  A legacy file that baked a design payload into
    # its stage masses is normalised to stack-only on load (booster_from_dict).
    payload_kg: float = 0.0

    # Payload decomposition (throw-weight): bus (post-boost vehicle) + N reentry
    # objects.  bus_mass_kg + num_ros * ro_mass_kg should equal payload_kg.
    # bus_mass_kg is booster hardware (the PBV, carried as dead mass for now);
    # num_ros / ro_mass_kg are run-level loadout bookkeeping stamped by
    # compose_loadout — NOT reentry-object hardware (beta, L/D, TPS, glide law
    # all live on params.ro).
    ro_mass_kg:    float = 0.0   # per-object mass, for the throw-weight breakdown
    bus_mass_kg:   float = 0.0
    num_ros:       int   = 1
    # Body-payload idempotency baseline: how much non-separating-body payload
    # (ro.payload_kg) compose_loadout has ALREADY folded into this chain.  A
    # fresh booster carries 0 (no added body payload); compose adds the delta to
    # the target payload and updates this, so composing twice adds it once.
    # Kept SEPARATE from payload_kg, whose baseline is the separating design
    # payload — reusing that made a body subtract the booster's baked warhead.
    # Runtime bookkeeping only; not serialised (a loaded booster starts at 0).
    body_payload_kg: float = 0.0

    # Non-separating vehicle: True marks this booster as one whose front end
    # does NOT separate — the last stage IS the reentry body (quasi-ballistic maneuvering body /
    # Iskander / Scud class).  This is the SINGLE SOURCE of the
    # booster↔reentry-object link, the one place the four inputs (booster,
    # reentry object, flight plan, reentry plan) are allowed to touch: neither
    # the object file nor the reentry plan stores a separation choice.  The
    # run derives ro.separation_mode from this flag (run_separation_mode /
    # bind_ro_separation); the sidebar Separation indicator only displays it.
    body_reenters: bool  = False

    # When True this stage uses a solid rocket motor that cannot be shut off.
    # Orbital insertion guidance runs the engine to natural burnout and reports
    # the resulting orbit rather than commanding a cutoff at the target energy.
    solid_motor:   bool  = False

    # Solid-motor grain profile (Shafer 1959).
    # grain_type: canonical key from _GRAIN_CURVES, or "" for liquid / constant.
    # thrust_peak_N: peak vacuum thrust (N); 0 = derive from thrust_N.
    # thrust_profile: bespoke [(t_frac, F_frac), ...] list; overrides grain_type.
    grain_type:     str  = ""
    thrust_peak_N:  float = 0.0
    thrust_profile: list = field(default_factory=list)

    # ── Per-stage advanced pitch program (optional) ──────────────────────────
    # When set on a stage, these override the top-level turn_start / turn_stop /
    # burnout_angle for that stage's burn interval.  None = use global values.
    # Stored on each stage object in the chain independently so stages can have
    # different pitch schedules (e.g. Stage 1 aggressive pitch-over, Stage 3
    # horizontal burn for orbital insertion).
    stage_turn_start_s:      Optional[float] = None
    stage_turn_stop_s:       Optional[float] = None
    stage_burnout_angle_deg: Optional[float] = None

    # Commanded engine cutoff for this stage: burn DURATION (s from this stage's
    # ignition) after which thrust is cut.  None = burn to completion.  Liquid
    # engines only — ignored on solid motors (they cannot be shut down).  The
    # stage still occupies its full burn_time_s slot; the tail after cutoff is a
    # dead coast with the unburned propellant riding as mass until jettison.
    stage_cutoff_s:          Optional[float] = None

    # Per-stage yaw (dogleg) overrides.  Same priority as pitch overrides:
    # if stage_yaw_final_az_deg is not None the stage performs a linear
    # azimuth schedule from current az to final_az over [yaw_start, yaw_stop].
    stage_yaw_start_s:     Optional[float] = None
    stage_yaw_stop_s:      Optional[float] = None
    stage_yaw_final_az_deg: Optional[float] = None

    # Conical (tapered) stage body.  When conical is True the stage is a
    # frustum from diameter_m (bottom) to top_diameter_m (top); a cylinder
    # otherwise.  Phase-1 geometry only: drag still references the base
    # (bottom) diameter, so a taper is drawn and carried but does not yet
    # change the aero (see METHODS -- interstage/conical plan).
    conical:                bool  = False
    top_diameter_m:         float = 0.0    # stage top diameter (m); frustum top

    # Interstage adapter sitting ON TOP of this stage, connecting it to the
    # next.  has_interstage toggles it on; the only free parameters are length,
    # mass, and jettison time -- the frustum's diameters are DERIVED (bottom =
    # this stage's top diameter, top = the next stage's base diameter) so the
    # drawing can never invent a transition the data did not specify.
    # interstage_jettison_s: absolute time from T=0; None = jettison with this
    # stage's separation (its burnout).  Phase-1: mass is carried while
    # attached and dropped at jettison; drag is unchanged.
    has_interstage:         bool  = False
    interstage_length_m:    float = 0.0
    interstage_mass_kg:     float = 0.0
    interstage_jettison_s:  Optional[float] = None

    # Shroud jettisoned during ascent.
    # shroud_mass_kg is included in mass_initial at launch and subtracted once
    # the booster crosses shroud_jettison_alt_km.  0 = no shroud.
    shroud_mass_kg:         float = 0.0
    shroud_jettison_alt_km: float = 80.0
    # Physical dimensions of the shroud — used for drag (pre-jettison reference
    # area uses shroud_diameter_m when > 0) and debris tumbling-cylinder β.
    shroud_length_m:        float = 0.0
    shroud_diameter_m:      float = 0.0   # outer diameter of shroud/fairing (m)

    # Nose-shape aerodynamics (Chin/NACA decomposed model).
    # "" = no shape set → drag_force_vector falls back to mach_table/cd_table.
    # L/D is computed internally as nose_length_m / diameter_m (or shroud_diameter_m).
    # 0 = not specified → L/D defaults to 3.0 inside _cd_nose_shape.
    nose_shape:             str   = ""
    nose_length_m:          float = 0.0    # physical nose-cone length (m)
    shroud_nose_shape:      str   = ""
    shroud_nose_length_m:   float = 0.0    # physical shroud nose-cone length (m)

    # Aerospike (drag-reduction probe protruding from the forebody).
    # When aerospike_LD > 0, the forebody wave drag is computed from an
    # "effective body" cone whose fineness ratio is derived from the
    # dividing-streamline geometry measured by Ahmed & Qin (2011) Fig. 5:
    #     L/D_eff = 1.0 + (2/3)·spike_LD + 2.0·spike_dD
    # The model takes whichever wave-drag is lower (actual nose vs. effective
    # body), so a spike never makes a slender body worse.
    # spike_LD = spike length / body diameter (typical 1.0–3.0)
    # spike_dD = aerodisk diameter / body diameter (0 = pointed tip; 0.05–0.4)
    aerospike_LD:           float = 0.0
    aerospike_dD:           float = 0.0

    # Fins — trapezoidal planar fins attached to the last stage body.
    # When has_fins is True the fin lift slope and drag are computed and added
    # to the body-only values (used by the L/D estimator and the synthesised
    # no-sep ROParams beta).  Fin aerodynamics follow the DATCOM/Barrowman
    # model (friction: Mandell et al. 1973; lift: DATCOM supersonic formula).
    # All dimensions in metres; sweep is leading-edge sweep in degrees.
    has_fins:             bool  = False
    n_fins:               int   = 4
    fin_span_m:           float = 0.0   # exposed semi-span from body surface
    fin_root_chord_m:     float = 0.0
    fin_tip_chord_m:      float = 0.0
    fin_thickness_m:      float = 0.0   # max thickness
    fin_sweep_deg:        float = 0.0   # leading-edge sweep angle

    # Grid (lattice) fins — a box-frame lattice of thin cells, NOT a planar
    # airfoil.  When has_grid_fins is True the grid-fin drag (and lift slope
    # for the estimator) is computed by _cd_gridfins/_cl_alpha_gridfins
    # (Washington & Miller; Kantrowitz start limit) and added to the body
    # values.  Attach to the stage on which the fins are mounted (they apply
    # only while that stage is the active stage, e.g. a finned first stage).
    has_grid_fins:        bool  = False
    n_grid_fins:          int   = 0
    grid_fin_width_m:         float = 0.0   # frame width (azimuthal span)
    grid_fin_height_m:        float = 0.0   # frame height (radial)
    grid_fin_chord_m:         float = 0.0   # streamwise lattice depth
    grid_fin_web_thickness_m: float = 0.0   # cell wall (web) thickness
    grid_fin_cell_pitch_m:    float = 0.0   # cell centre-to-centre spacing
    grid_fin_solidity:        float = 0.0   # σ = blocked frontal fraction; if >0
    #   used directly (approximation for web+pitch), else derived from them.
    grid_fin_edge_factor:     float = 1.0   # 1.0 blunt webs; ~0.6-0.85 shaped
    # Deployment schedule: list of [deploy_time_s, n_fins] batches (absolute
    # mission time).  n fins become aerodynamically active at deploy_time_s;
    # the deployed count (capped at n_grid_fins) scales the grid-fin drag.
    # Empty -> all n_grid_fins active from t=0.  E.g. STARS deploys 4 fins at
    # tower-clear and 4 more 60 s later: [[t_clear, 4], [t_clear+60, 4]].
    grid_fin_deploy_schedule: list = field(default_factory=list)

    # Payload diameter (m).  When > 0, used as the frontal reference diameter
    # for aerodynamic drag after shroud jettison (or throughout flight when no
    # shroud is fitted).  Falls back to the stage body diameter_m when 0.
    payload_diameter_m:     float = 0.0

    # Reentry-object hardware (beta, mass, geometry, L/D, glide law, TPS) lives
    # ONLY on params.ro (ROParams) — the booster no longer carries any reentry
    # fields.  Old JSON that stored them inline is migrated to a synthesised
    # params.ro at load time (see booster_from_dict).

    # Post-boost vehicle (PBV) geometry — mass is already carried in bus_mass_kg.
    pbv_diameter_m: float = 0.0
    pbv_length_m:   float = 0.0

    # Provenance — where these numbers came from and how firm they are
    # (mirrors ROParams.source/notes).
    source: str = ""
    notes:  str = ""

    # Strap-on boosters — fire from t=0 in parallel with stage 1; separate at
    # booster_burn_time_s.  These fields are only meaningful on the top-level
    # (stage-1) node; upper-stage nodes ignore them.
    n_boosters:             int   = 0
    booster_thrust_n:       float = 0.0    # vacuum thrust per booster (N)
    booster_burn_time_s:    float = 0.0    # burn duration (s)
    booster_inert_kg:       float = 0.0    # inert (empty) mass per booster (kg)
    booster_prop_kg:        float = 0.0    # propellant mass per booster (kg)
    booster_isp_s:          float = 0.0    # specific impulse (s)
    booster_nozzle_area_m2: float = 0.0    # nozzle exit area for P correction (m²)
    booster_diam_m:         float = 0.0    # outer diameter per booster (m)
    booster_length_m:       float = 0.0    # length per booster (0 → 2×diameter)
    booster_cd:             float = 0.20   # zero-lift Cd (0.20 = tangent ogive)
    # Seconds after T=0 (strap-on ignition / liftoff) before stage-1 core ignites.
    # 0 = all ignite together (Soyuz).  >0 = sequential (LVM3, Titan IIIC).
    booster_core_delay_s:   float = 0.0
    # Time (s after T=0) the spent boosters are physically jettisoned.  Many
    # strap-ons burn out and are then carried as dead (thrustless) mass for a
    # short coast before separation — during that coast they still add inert
    # mass and parasitic drag.  0 = jettison coincides with burnout (legacy).
    booster_jettison_s:     float = 0.0

    # ── RV reference (new architecture) ─────────────────────────────────────
    # When set, all RV flight properties (β, shape, glider params) are read
    # from this object rather than from the deprecated inline fields below.
    # Populated by the booster editor when "RV separates" is checked.
    ro: Optional['ROParams'] = None


# ---------------------------------------------------------------------------
# ROParams — independently loadable reentry-vehicle / glide-body definition.
# All fields that were previously scattered across BoosterParams as rv_* and
# glider_* inline fields now live here.  The inline fields on BoosterParams
# are kept for backward-compatible reading of old JSON files but are no
# longer written by the editor or read by the integrator when params.ro is set.
# ---------------------------------------------------------------------------

# Valid ROParams.body_form values (see the field's comment below).
BODY_FORMS = ("axisymmetric", "wedge", "half_cone")


@dataclass
class ROParams:
    """Reentry vehicle or hypersonic glide body — independently loadable."""
    name:       str
    mass_kg:    float   # single-RV mass (kg)
    beta_kg_m2: float   # ballistic coefficient β = m/(Cd·A) (kg/m²)
    # Mach at which beta_kg_m2 is stated.  0.0 = legacy CONSTANT β at every
    # Mach (byte-identical to files that predate the field).  > 0: the entered
    # β is held EXACT at this Mach and the object's own geometry supplies only
    # the RELATIVE variation, β(M) = β · C_D0(M_ref)/C_D0(M) — derive, don't
    # invent (beta_mach_table).  Hardware: it qualifies the β measurement,
    # like a unit, not how a particular run is flown.
    beta_ref_mach: float = 0.0

    # Geometry — for Cd model on boost phase and for β-calculator round-trip
    shape:      str   = ""    # key from NOSE_SHAPES; "" → Forden Cd fallback
    diameter_m: float = 0.0
    length_m:   float = 0.0
    # Nose-tip (stagnation) radius of curvature (m), used for Sutton-Graves
    # stagnation heating q̇ ∝ 1/√R_N.  0.0 = AUTO: derive a screening default
    # from the nose shape + base diameter (see nose_tip_radius / the
    # effective_nose_radius_m() accessor).  A positive value is authoritative
    # and overrides the derived default.
    nose_radius_m: float = 0.0

    # Biconic (two-cone) body.  When True the RV is a forward cone meeting an
    # aft frustum at break_diameter_m, break_diameter_m across, fore_length_m
    # from the nose.  The half-angles derive from these + diameter_m/length_m
    # (booster_models.biconic_angles); the β estimator uses the two-cone
    # build-up (cd_biconic_hypersonic).  Default off → plain cone, unchanged.
    biconic:         bool  = False
    fore_length_m:   float = 0.0    # length of the forward cone (m)
    break_diameter_m: float = 0.0   # diameter at the cone-cone junction (m)

    # Body form — how the airframe carries its volume.  Phase 1: data model +
    # honest depiction ONLY.  The trajectory physics ride on β / L/D / the
    # derived polar and are IDENTICAL across forms (a lifting-body trim
    # estimator and a shape-derived pull ceiling are Phase 2/3).
    #   "axisymmetric" — body of revolution (cone / biconic).  Default.
    #   "wedge"        — flattened wedge lifting body (HTV-2 class).
    #                    diameter_m is the BASE DEPTH (thickness); the
    #                    planform span is NOT modeled and the schematic
    #                    flags it rather than inventing one.
    #   "half_cone"    — half-cone lifting body (flat diametral plane over a
    #                    conical lower surface); diameter_m is the full cone
    #                    diameter, so the side-elevation depth is D/2.
    # biconic applies only to "axisymmetric" (it is a body-of-revolution
    # concept); consumers ignore it for the lifting-body forms.
    body_form: str = "axisymmetric"
    # Planform span of a WEDGE lifting body: tip-to-tip base width (m).  The
    # wedge's BODY is its lifting surface, so this is body geometry — DISTINCT
    # from wing_span_exposed_m, which is the exposed panel span of a wing
    # mounted ON a body (and feeds wing_geometry()'s reference-wing S/AR
    # derivation).  Conflating them would derive a phantom wing from the body
    # width; wing_geometry() must never read this field.  0 = unset (the
    # schematic flags "span not modeled").  Meaningful only for
    # body_form == "wedge": a half-cone's span IS its diameter, and a body of
    # revolution has none.
    body_span_m: float = 0.0

    # Forward-taper (nose) length of a NON-SEPARATING body, in metres.  A
    # unitary missile (V-2 / Scud) is one airframe whose length is the
    # last stage's length_m; this field is the forward portion of that length
    # that tapers into the nose (shape = self.shape), carved SUBTRACTIVELY from
    # the top — never a section stacked on top (see FRONT_END_DESIGN.md §4).
    # 0 = unset → the schematic draws a flagged shape-appropriate default and
    # says so.  Meaningful only for separation_mode == "body"; a separating RV
    # carries its own independent length_m instead and ignores this field.
    body_nose_length_m: float = 0.0

    # Reentry centre-of-gravity of a NON-SEPARATING body, metres aft of the nose
    # tip.  The reentry static margin (trim_gate.py) — which decides nose-first
    # trim vs tumbling, hence the whole glide — turns on where the CG sits, and
    # the auto-estimate treats the empty airframe as a uniform tube (CG at the
    # centroid).  A real missile packs its dense warhead/guidance forward, moving
    # the CG ahead of that centroid and making the body markedly more stable.
    # 0 = auto (uniform-airframe centroid, grid_fin_sizing.estimate_cg); a
    # positive value overrides it.  Meaningful only for separation_mode=="body".
    reentry_cg_m: float = 0.0

    # Payload mass (kg) carried by a NON-SEPARATING body, ON TOP of the
    # airframe's own last-stage burnout mass.  A body (V-2 / Scud) IS
    # the last stage, so its structural + residual burnout mass comes from the
    # booster (effective_ro inherits it); this field is the ADDED payload the
    # front end owns — warhead, bus, guidance — that the modeller enters here
    # rather than folding into the stage's dry mass.  compose_loadout adds it to
    # the boosted stack and keeps it fused through burnout, so the reentry mass
    # is airframe_burnout + payload.  0 = none (every existing file flies
    # unchanged); meaningful only for separation_mode=="body".  A SEPARATING RV
    # carries its mass in mass_kg instead — this field is ignored there.
    payload_kg: float = 0.0

    # Separation mode — does the terminal vehicle separate from the booster
    # body, or IS the booster body the terminal vehicle?
    #   "separating_ro" — distinct payload, mass/beta/diameter independent
    #                     (ICBM with MIRV, Scud-style separated warhead, …)
    #   "body"          — vehicle IS the booster body (quasi-ballistic maneuvering body,
    #                     Pershing II MaRV, single-stage maneuvering body).
    #                     mass/beta/diameter are inherited from the booster's
    #                     last stage (mass_final, beta_kg_m2, diameter_m)
    #                     by effective_ro() at runtime.
    # DERIVED, never stored: the value is set at run time from the booster's
    # body_reenters (the single source of the link) by bind_ro_separation /
    # effective_ro.  It is omitted from object and plan files.  Legacy files
    # that still carry it are read (normalised) but the booster wins.
    separation_mode: str = "separating_ro"

    # Glider / HGV properties
    #
    # glider_guidance — one of:
    #   "equilibrium_glide":       Tracy 2020.  Analytical Acton pull-up
    #                              (Eq. 11) applied as a one-shot arc
    #                              between the 100 km pierce point and
    #                              h_eq; the schema's t₂ and t₃ coincide
    #                              (no separate direct-re-entry phase).
    #                              Uses one β (= β_L for glide).
    #   "equilibrium_glide_acton": Acton 2015 three-phase model.  After
    #                              piercing at 100 km the vehicle enters a
    #                              direct-re-entry segment with β_S drag
    #                              and L/D = 0 until alt = h_3 (Acton
    #                              Eq. 8); at t_3 the analytical pull-up
    #                              fires.  Requires β_S =
    #                              glider_beta_entry_kg_m2 > 0.
    #   "skip_glide":              no analytical pull-up; the vehicle re-
    #                              enters with whatever γ it had and the
    #                              natural EOM produces a phugoid.
    #   "skip_to_equilibrium":     RETIRED — aliased to "damped_glide" on load
    #                              (_norm_glide_mode).  It started as skip_glide
    #                              and after N upward crossings switched one-way
    #                              to equilibrium_glide; the damped phugoid glide
    #                              produces the same "skip a while, then settle"
    #                              behaviour continuously, so the discrete
    #                              handoff (and its glider_skip_count) is gone.
    #                              The EOM path is retained but unreachable.
    #   "damped_glide":            skip_glide plus continuous altitude-rate
    #                              lift feedback (Lu 2013 / Yu & Chen 2011)
    #                              that damps the phugoid to a target ratio
    #                              ζ = glider_damping_zeta.  ζ=0
    #                              ≡ skip_glide; large ζ → equilibrium_glide.
    #                              See DAMPED_GLIDE.md.
    # Capability vs intent.  `maneuvering` is HARDWARE: the object can
    # generate lift (an aeroshell trimmed at angle of attack, wings, control
    # surfaces) — the object editor's Maneuvering checkbox.  `glider_enabled`
    # is the reentry PLAN's intent to fly it as a glider on this run, and
    # apply_reentry_plan clamps it by the capability: a plan can fly a glider
    # ballistic, never a ballistic object as a glider.
    maneuvering:            bool  = False
    glider_enabled:         bool  = False
    glider_LD:              float = 0.0
    # Wing geometry — the physical anchor for the DECOUPLED drag polar
    # (trajectory._aero_polar).  Both HARDWARE (shape), default 0 = no wings =
    # the slender-body polar unchanged.  A user can measure these off a
    # planform (span × chord) when detailed aero data is absent; they replace
    # the un-physical hardcoded pull-C_L ceiling with a geometry-anchored one.
    #   wing_area_m2       — total wing planform area (m²).  Raises the pull
    #                        C_L,max ceiling; 0 keeps the bare-body 0.873.
    #   wing_aspect_ratio  — b²/S_w.  OPTIONAL: softens the induced-drag rise
    #                        in a hard pull (broader bucket for a high-AR wing),
    #                        cruise L/D untouched.  0 = unset → fail safe: keep
    #                        today's induced drag, credit only the ceiling from
    #                        area.  Never invents efficiency it can't support.
    wing_area_m2:           float = 0.0
    wing_aspect_ratio:      float = 0.0
    # Optional wing PLANFORM (depiction only — the polar needs only S and AR).
    # S and AR alone cannot define a planform on a conical body (no position,
    # root chord, or shape), so the schematic draws the wings faithfully ONLY
    # when these are entered; otherwise it falls back to a small fixed-
    # proportion glyph labelled "(schematic)".  A planform is "specified" when
    # both root chord and exposed span are > 0.
    wing_root_chord_m:      float = 0.0   # root chord along the body flank (m)
    wing_span_exposed_m:    float = 0.0   # per-side exposed span from the surface (m)
    wing_sweep_deg:         float = 0.0   # leading-edge sweep (0 = tip at TE height)
    # GEOMETRY-only (feeds the 3-D Blender export; NOT the polar, which uses
    # area/AR/sweep): the panel thickness and how many panels ring the body
    # (a C-HGB carries 4 flaps; a delta glider 2).
    wing_thickness_m:       float = 0.0   # panel max thickness (0 = export nom.)
    n_wings:                int   = 4     # panels around the body for export
    # Trim row from the lifting-body α-sweep estimator (Phase 3 consumers:
    # the offset polar and the windward-α consistency guard).  SWEEP-native
    # coefficients — referenced to the estimator's stated A_ref (planform for
    # a wedge, base area otherwise); the polar converts.  0 = absent → the
    # symmetric polar, byte-identical.  Written by "Use β and L/D" (lifting
    # forms only; zeroed on save for a body of revolution — a stale offset
    # from a former form would silently skew the polar).
    trim_alpha_deg:         float = 0.0   # α* of (L/D)max
    trim_CL0:               float = 0.0   # camber offset: C_L at minimum drag
    # Default reentry mode for a freshly-built maneuvering object is a CORE
    # glide law (the smooth numerical equilibrium glide), not the legacy
    # analytic Tracy `equilibrium_glide`.  Legacy .json files that omit the key
    # keep loading as `equilibrium_glide` via ro_from_dict's explicit fallback,
    # so old data is unchanged; only new ROParams() default to the core law.
    glider_guidance:        str   = "dynamic_equilibrium_glide"
    # Pull-up load factor.  pullup_g_limit is HARDWARE (the airframe's
    # structural limit, stored on the object); glider_pullup_g_max is the
    # PLAN's commanded value, clamped to the limit on apply_reentry_plan —
    # "fly it worse, never better", the same shape as commanded_LD ≤ glider_LD.
    # A limit of 0 (the default) means UNLIMITED: no clamp is applied, so a
    # plan can command an extreme manoeuvre to see what load it produces.
    pullup_g_limit:         float = 0.0
    glider_pullup_g_max:    float = 10.0
    # Terminal dive: 0 km = glide to impact (no altitude-triggered dive; the
    # target-proximity trigger still fires if armed).  A positive value
    # commands the dive when the vehicle descends below that altitude.  The
    # analytical Tracy/Acton glide always ends at its 30 km validity floor
    # regardless, handing off to the ballistic-descent integration below it.
    glider_terminal_dive:   bool  = False
    glider_terminal_alt_km: float = 0.0
    # Bank-turn schedule: list of (t_start_s, t_end_s, bank_deg) tuples in
    # mission-elapsed seconds.  Positive bank = right turn; negative = left.
    # Up to 3 entries.  When non-empty, equilibrium-glide modes fall back
    # to numerical integration during the glide phase because the analytical
    # equilibrium-glide formula cannot represent banked maneuvers.
    glider_bank_schedule:   list  = field(default_factory=list)
    # Aerodynamic model used in the numerical EOM during glide:
    #   "polar"       — slender-body drag polar (Munk 1924, Ashley & Landahl
    #                   §6-7, §9-8): C_L = 2α with C_L referenced to the
    #                   base area, C_D = C_D0 + k·C_L².  C_D0 is derived
    #                   from the user's β (treated as zero-lift) and base
    #                   diameter; k is back-solved from the user's
    #                   glider_LD so (L/D)_max matches input exactly.
    #                   Vehicle trims for the lift required to balance the
    #                   centripetal deficit (m·(g − V²/r) / cos σ); off-
    #                   trim banking and pull-up incur the correct induced-
    #                   drag penalty.  DEFAULT — the realistic model.
    #   "constant_LD" — idealized fixed-L/D upper bound: lift = drag · L/D
    #                   with L/D from glider_LD, β-derived drag.  Implicitly
    #                   assumes the vehicle always flies at max-L/D AoA and
    #                   never pays induced drag off-design, so it over-ranges
    #                   relative to the polar.  Kept for cross-checking the
    #                   closed-form Sänger/Tracy/Acton range solutions, which
    #                   assume constant L/D.  At its trim point (C_L = C_L*)
    #                   the polar reproduces this model exactly.
    glider_aero_model:      str   = "polar"
    # Reentry attitude — how the reentering body is flown, a plan property:
    #   'trim'     : stable, controlled, at a trim angle of attack (aeroshell β
    #                as given; L/D from geometry for a body, or the designed
    #                value for a separating RV).  The Iskander / MaRV case.
    #   'tumbling' : uncontrolled, no attitude hold — L/D = 0 and the ballistic
    #                coefficient is DERIVED from geometry as a tumbling cylinder
    #                (Hoerner two-orientation form), not the aeroshell's β.  The
    #                spent-stage / failed-RV case.
    reentry_attitude:       str   = "trim"
    # Target-based dive trigger.  When glider_dive_target_radius_km > 0 the
    # vehicle starts the terminal dive (bank = π) as soon as its great-circle
    # distance to the target (lat/lon) drops below the radius — in addition
    # to the altitude trigger, whichever fires first.  Disabled when radius
    # = 0.  Detected in the EOM each step; max_step is tightened to ~2 s
    # while the trigger is armed so the granularity is ~6–8 km at HGV
    # speeds.  If used in equilibrium-glide modes, the analytical closed-form
    # is bypassed in favour of the numerical EOM (the analytical glide can't
    # see the target).
    glider_dive_target_lat_deg:    float = 0.0
    glider_dive_target_lon_deg:    float = 0.0
    glider_dive_target_radius_km:  float = 0.0     # 0 = disabled
    # Acton 2015 Phase-3 (direct re-entry) ballistic coefficient β_S.
    # During Phase 3 the glider holds a high-AoA orientation: flat lower
    # surface to airflow, large drag, L/D = 0.  Acton's HTV-2 fit gives
    # β_S ≈ 7 kg/m² (Table 3, p. 206).  Used only by the
    # "equilibrium_glide_acton" guidance mode; ignored otherwise.  Set 0
    # to disable Phase 3 (effectively reverts to Tracy when paired with
    # Acton mode).  HARDWARE: a vehicle property stored on the object, not a
    # reentry-plan key.
    glider_beta_entry_kg_m2: float = 0.0
    # Number of phugoid upward crossings of the equilibrium curve before the
    # one-way handoff to equilibrium glide.  Only used by skip_to_equilibrium.
    glider_skip_count:      int   = 1

    # Target damping ratio ζ for the "damped_glide" guidance mode.  The vehicle
    # flies at the max-L/D trim angle α* plus a flight-path-angle feedback term
    #     α = α* + k_γ·(γ* − γ)                      (Yu & Chen 2011, Eq. 19)
    # whose gain k_γ is computed each step for this ζ from the phugoid natural
    # frequency obtained by linearising the equilibrium-glide EOM from first
    # principles (lift ∝ ρ ∝ e^(−h/H_ρ) ⇒ d a_L/dh = −g_eff/H_ρ), giving the
    # control law of Lu, Forbes & Baldwin AIAA 2013-4648 Eq. 33.  The phugoid
    # frequency is corroborated empirically by Liu et al. 2025 (0.021–0.037
    # rad/s).  See DAMPED_GLIDE_MEMO.md §2.
    #     ω_p² = g_eff/H_ρ ,  k_γ = ζ·C_L*·V/√(g_eff·H_ρ)
    # with g_eff = g − V²/r and H_ρ the local density scale height.  ζ = 0
    # recovers undamped skip_glide exactly (k_γ = 0); ζ ≈ 0.7 gives a couple of
    # decaying oscillations into equilibrium glide; large ζ → equilibrium_glide.
    # Only used by the "damped_glide" mode.
    glider_damping_zeta:    float = 0.7

    # Commanded pull-up initiation altitude (km) — a PLAN-PHASE MODIFIER for
    # the numerical glide family (damped_glide / dynamic_equilibrium_glide /
    # skip_glide), not a guidance mode.  Above this altitude the vehicle falls
    # with ZERO commanded lift (β-based drag only — the low-AoA ballistic
    # descent real MaRVs fly); at it, a hard pull is commanded at full
    # authority (capped by glider_pullup_g_max AND by what q and the aero
    # model supply — triggering too high undershoots honestly); once the sink
    # rate is arrested to the glide law's own equilibrium target the selected
    # law takes over, one-way.  0 = no commanded pull: capture happens however
    # the glide law does it (byte-identical to pre-modifier behaviour).
    # Flight precedent: SWERVE III commanded its pull-out at Mach 12 /
    # high altitude as a discrete event (the -10 deg AoA pull at t=20 s in
    # Iliff & Shafer, AIAA 93-0311, Fig. 20).  Ignored by the
    # analytic family, which flies its own closed-form pull-up arc.
    glider_pullup_start_alt_km: float = 0.0

    # Control-surface descriptor: how much lifting/control-surface area the
    # vehicle carries.  Read by TWO consumers, and for one of them it DOES
    # change the flown trajectory:
    #   * damping_estimate (docs/damping_estimate_spec.md) — bounds the
    #     achievable ζ.  "unknown" → the estimator returns its widest band;
    #     "none"/"small"/"substantial" select a tier.  Estimate only.
    #   * trim_gate.control_authority — maps the tier to a usable one-sided
    #     deflection (none/small/substantial/unknown → 0/5/15/10°), which sets
    #     the trimmable α and hence LD_achievable.  For a NO-SEPARATION body
    #     that feeds the flown glide — so the tier changes range.  A separating
    #     RV with its own designed glider_LD is unaffected.  ("No-separation"
    #     is not stored here: the run derives ro.separation_mode from the
    #     booster's body_reenters flag, per the note on that field.  The gate
    #     fires when the derived mode is "body" with reentry_attitude "trim",
    #     glider_enabled, and glider_LD left at 0.)
    # glider_flap_area_ratio (S_flap/S_ref) and glider_flap_deflection_deg, when
    # > 0, override the tier with an explicit Newtonian-flap computation in the
    # damping estimator; glider_flap_deflection_deg ALSO overrides the trim
    # gate's tier deflection (still capped at the separation limit).
    # glider_flap_area_ratio is read by the damping estimator only.
    glider_control_surfaces:   str   = "unknown"
    glider_flap_area_ratio:    float = 0.0      # 0 ⇒ use the tier default
    glider_flap_deflection_deg: float = 0.0     # 0 ⇒ use the 12° default

    # Surface emissivity used for radiative-equilibrium temperature at the
    # stagnation point: T_eq = (q̇ / (σ·ε))^(1/4).  0.85 matches the value
    # Anderson, "Hypersonic and High-Temperature Gas Dynamics," 2nd ed.,
    # AIAA, 2006, Section 18.8 (p. 781), uses in a worked HERMES reentry
    # example, citing Hirschel, "Basics of Aerothermodynamics," Springer.
    #
    # Verified RCC ε(T) values from Williams & Curry, "Thermal Protection
    # Materials: Thermophysical Property Data," NASA RP-1289, Dec. 1992
    # (Table for RCC, attributed to Space Shuttle Program Thermodynamic
    # Design Data Book SD73-SH-0226, Rockwell International, 1981):
    #     ε = 0.78 at   0°F   (256 K)
    #     ε = 0.87 at 1000°F  (811 K)
    #     ε = 0.90 at 1500°F (1089 K)  ← peak
    #     ε = 0.89 at 2000°F (1367 K)
    #     ε = 0.83 at 2500°F (1644 K)
    #     ε = 0.75 at 2800°F (1811 K)  ← max tabulated
    # Recent arc-jet measurements (Ohlhorst et al., NASA NTRS 20070031768,
    # 2007) report 0.88–0.91 at 2700–3000°F, suggesting the design data
    # are conservative.  For peak-heating T_eq in the 2500–3800 K range
    # RCC is above its working temperature anyway (surface ablates, no
    # longer at equilibrium); the constant-ε model is a lower bound there.
    emissivity:             float = 0.85
    # TPS material class for the heating survivability figure of merit (see
    # heating.py TPS_MATERIALS): '' / 'aluminum' / 'titanium' / 'steel' /
    # 'silica_tile' / 'rcc' / 'uhtc' / 'carbon_ablator'.  '' → physical heating
    # numbers only, no pass/fail verdict.
    tps_material:           str   = ""
    # Per-location TPS materials (HEATING_MODEL_CROSSCHECK.md §10.1 / §11 Phase 1).
    # Both selectable for every RV.  When blank, they fall back to tps_material for
    # BOTH locations (via nose_material()/body_material()), so existing RVs are
    # unchanged.  body_tps_thickness_m is the designed body-layer thickness (or, for
    # a bare hot structure, the skin/wall thickness feeding the transient heat-sink).
    # structure_material / structure_limit_K carry the bondline verdict; for a
    # hot-structure body (heating.is_hot_structure) the bondline collapses onto the
    # body material's own limit.  NOT yet consumed by the FOM — wired in Phase 2.
    nose_tps_material:      str   = ""
    body_tps_material:      str   = ""
    body_tps_thickness_m:   float = 0.0
    structure_material:     str   = ""
    structure_limit_K:      float = 0.0
    # Bespoke (user-defined) material properties, keyed by location.  When a
    # location's material is the sentinel 'custom_nose' / 'custom_body', the
    # matching dict here holds a catalog-shaped entry (label, group, is_ablator,
    # peak_K/continuous_K/melt_K, density_kg_m3, H_eff_MJ_kg) that
    # heating.register_custom_material() injects into TPS_MATERIALS before the FOM
    # runs.  Empty/None for the usual catalog-key case.
    nose_tps_custom:        Optional[dict] = None
    body_tps_custom:        Optional[dict] = None
    # Provenance: where this vehicle's numbers came from and how firm they are.
    # `source` is a short citation; `notes` is free-form (e.g. "mass 300 kg is a
    # trajectory-fit value, no primary source").  Round-tripped by
    # ro_to_dict/ro_from_dict so the justification travels with the vehicle and
    # is never silently dropped on a GUI/library save.
    source:                 str   = ""
    notes:                  str   = ""

    def nose_material(self) -> str:
        """Nose TPS material key, falling back to the single tps_material (Phase-1
        back-compat: a lone tps_material governs both nose and body)."""
        return self.nose_tps_material or self.tps_material

    def body_material(self) -> str:
        """Body/acreage TPS material key, falling back to the single tps_material."""
        return self.body_tps_material or self.tps_material

    def effective_nose_radius_m(self) -> float:
        """Stagnation radius (m) for Sutton-Graves heating: the explicit
        nose_radius_m when set (>0), otherwise the shape/diameter screening
        default from nose_tip_radius()."""
        if self.nose_radius_m and self.nose_radius_m > 0.0:
            return float(self.nose_radius_m)
        return nose_tip_radius(self.shape, self.diameter_m)


def _norm_sep_mode(v) -> str:
    """Normalise a separation_mode value to the current two-token vocabulary
    ('separating_ro' | 'body').  Legacy aliases from older saved files:
    'separating_rv' -> 'separating_ro' (pre-Phase-2 rename) and
    'non_separating' -> 'body' (the run path only branches on 'body', so the
    old token silently missed the body-mode mass/geometry inheritance)."""
    s = str(v or 'separating_ro')
    return {'separating_rv': 'separating_ro',
            'non_separating': 'body'}.get(s, s)


def _norm_glide_mode(v) -> str:
    """Normalise a glider_guidance value to the current vocabulary.  Retired
    modes are aliased to their live equivalent so old saved files/plans keep
    working:
      'constant_bank'       -> 'skip_glide'  (old bank-angle knob removed)
      'azimuth_command'     -> 'skip_glide'  (proportional heading hold removed)
      'skip_to_equilibrium' -> 'damped_glide' (the damped phugoid glide covers
                               the same "skip a while, then settle" behaviour
                               continuously, so the discrete N-skip handoff is
                               retired)."""
    s = str(v or 'equilibrium_glide')
    return {'constant_bank': 'skip_glide',
            'azimuth_command': 'skip_glide',
            'skip_to_equilibrium': 'damped_glide'}.get(s, s)


# Integration families.  The reentry laws divide by HOW the trajectory is
# integrated, and that boundary is a capability fork (banking, dive-at-target
# and the Mach-varying L/D table exist only in the numerical family; the
# analytic family is constant-L/D and always captures).  The family is a pure
# function of the glide law — no stored field — and it is the reentry plan's
# IDENTITY: the sidebar strip only offers in-family laws, and New Reentry Plan
# chooses the family up front (see REENTRY_FAMILY_DESIGN.md).  Ballistic lives
# inside the numerical family (numerically integrated, lift off), so
# ballistic <-> glide stays an in-family tweak.
GLIDE_FAMILY_NUMERICAL = ('ballistic', 'skip_glide', 'damped_glide',
                          'dynamic_equilibrium_glide')
GLIDE_FAMILY_ANALYTIC  = ('equilibrium_glide_acton', 'equilibrium_glide')


def glide_family(guidance) -> str:
    """'numerical' | 'analytic' for a glider_guidance value (after aliasing
    retired modes).  Unknown values fall to 'numerical' — the EOM is the
    default integrator, so that is always a safe answer."""
    g = _norm_glide_mode(guidance)
    return 'analytic' if g in GLIDE_FAMILY_ANALYTIC else 'numerical'


def ro_to_dict(ro: ROParams, include_reentry_plan: bool = True) -> dict:
    """Serialise an ROParams to a JSON-compatible dict.

    ``separation_mode`` is never written: it is derived from the booster's
    ``body_reenters`` at run time (see run_separation_mode).
    With ``include_reentry_plan=False`` the reentry-plan fields (everything in
    ``_REENTRY_PLAN_KEYS`` -- glide mode, turns, dives) are omitted,
    yielding a hardware-only reentry object; that is the form ro_library stores,
    with the plan travelling separately in a ``.reentryplan.json`` file.  The
    ``glider_LD`` capability stays: it is what the airframe *can* do.  The
    default (``True``) keeps the full serialisation for internal round-trips.
    """
    d = {
        'name':                  ro.name,
        'mass_kg':               ro.mass_kg,
        'beta_kg_m2':            ro.beta_kg_m2,
        'beta_ref_mach':         ro.beta_ref_mach,
        'shape':                 ro.shape,
        'diameter_m':            ro.diameter_m,
        'length_m':              ro.length_m,
        'nose_radius_m':         ro.nose_radius_m,
        'biconic':               ro.biconic,
        'fore_length_m':         ro.fore_length_m,
        'break_diameter_m':      ro.break_diameter_m,
        'body_form':             ro.body_form,
        'body_span_m':           ro.body_span_m,
        'body_nose_length_m':    ro.body_nose_length_m,
        'reentry_cg_m':          ro.reentry_cg_m,
        'payload_kg':            ro.payload_kg,
        'maneuvering':           ro.maneuvering,
        'glider_enabled':        ro.glider_enabled,
        'glider_LD':             ro.glider_LD,
        'wing_area_m2':          ro.wing_area_m2,
        'wing_aspect_ratio':     ro.wing_aspect_ratio,
        'wing_root_chord_m':     ro.wing_root_chord_m,
        'wing_span_exposed_m':   ro.wing_span_exposed_m,
        'wing_sweep_deg':        ro.wing_sweep_deg,
        'wing_thickness_m':      ro.wing_thickness_m,
        'n_wings':               ro.n_wings,
        'trim_alpha_deg':        ro.trim_alpha_deg,
        'trim_CL0':              ro.trim_CL0,
        'glider_guidance':       ro.glider_guidance,
        'pullup_g_limit':        ro.pullup_g_limit,
        'glider_pullup_g_max':   ro.glider_pullup_g_max,
        'glider_terminal_dive':  ro.glider_terminal_dive,
        'glider_terminal_alt_km':ro.glider_terminal_alt_km,
        'glider_bank_schedule':  ro.glider_bank_schedule,
        'glider_aero_model':     ro.glider_aero_model,
        'glider_dive_target_lat_deg':   ro.glider_dive_target_lat_deg,
        'glider_dive_target_lon_deg':   ro.glider_dive_target_lon_deg,
        'glider_dive_target_radius_km': ro.glider_dive_target_radius_km,
        'glider_beta_entry_kg_m2': ro.glider_beta_entry_kg_m2,
        'glider_skip_count':     ro.glider_skip_count,
        'glider_damping_zeta':   ro.glider_damping_zeta,
        'glider_pullup_start_alt_km': ro.glider_pullup_start_alt_km,
        'glider_control_surfaces':   ro.glider_control_surfaces,
        'glider_flap_area_ratio':    ro.glider_flap_area_ratio,
        'glider_flap_deflection_deg':ro.glider_flap_deflection_deg,
        'reentry_attitude':      ro.reentry_attitude,
        'emissivity':            ro.emissivity,
        'tps_material':          ro.tps_material,
        'nose_tps_material':     ro.nose_tps_material,
        'body_tps_material':     ro.body_tps_material,
        'body_tps_thickness_m':  ro.body_tps_thickness_m,
        'structure_material':    ro.structure_material,
        'structure_limit_K':     ro.structure_limit_K,
        'nose_tps_custom':       ro.nose_tps_custom,
        'body_tps_custom':       ro.body_tps_custom,
        'source':                ro.source,
        'notes':                 ro.notes,
    }
    if not include_reentry_plan:
        for _k in _REENTRY_PLAN_KEYS:
            d.pop(_k, None)
    return d


def upgrade_ro_dict(d: dict) -> dict:
    """Convert a reentry-object dict of ANY vintage into the current schema.

    The object-side counterpart of :func:`upgrade_booster_dict`: pure,
    idempotent, and the only place old object files are understood.

    Conversions:

    * Retired glide laws are aliased to their live equivalent
      (``constant_bank`` and ``azimuth_command`` -> ``skip_glide``,
      ``skip_to_equilibrium`` -> ``damped_glide``).  A file with no glide law
      at all predates the field and meant Tracy's ``equilibrium_glide``.
    * Separation tokens ``separating_rv`` -> ``separating_ro`` (the rename)
      and ``non_separating`` -> ``body`` (the run path only ever branched on
      ``body``, so the old token silently missed body-mode inheritance).
      The value is derived from the booster at run time now; it is normalised
      here so an old file still reads sensibly.
    * An unknown or absent ``body_form`` means a body of revolution.
    * ``maneuvering`` (the lift capability) postdates the capability/intent
      split.  A file without it declared capability implicitly: a stored
      ``glider_enabled``, a positive L/D, or wing geometry.
    """
    if not isinstance(d, dict):
        raise TypeError("reentry-object dict expected")
    d = dict(d)
    if d.get('schema') == RO_SCHEMA:
        return d
    d['glider_guidance'] = _norm_glide_mode(
        d.get('glider_guidance', 'equilibrium_glide'))
    d['separation_mode'] = _norm_sep_mode(
        d.get('separation_mode', 'separating_ro'))
    _bf = str(d.get('body_form', '') or '')
    d['body_form'] = _bf if _bf in BODY_FORMS else 'axisymmetric'
    if 'maneuvering' not in d:
        d['maneuvering'] = bool(
            d.get('glider_enabled', False)
            or float(d.get('glider_LD', 0.0) or 0.0) > 0.0
            or float(d.get('wing_area_m2', 0.0) or 0.0) > 0.0)
    d['schema'] = RO_SCHEMA
    return d


def ro_from_dict(d: dict) -> ROParams:
    """Reconstruct an ROParams from an object dict.

    The dict is passed through :func:`upgrade_ro_dict` first, so this function
    reads the CURRENT schema only.  A new compatibility rule goes there.
    """
    d = upgrade_ro_dict(d)
    return ROParams(
        name=str(d.get('name', 'RV')),
        mass_kg=float(d['mass_kg']),
        beta_kg_m2=float(d['beta_kg_m2']),
        beta_ref_mach=float(d.get('beta_ref_mach', 0.0) or 0.0),
        shape=str(d.get('shape', '')),
        diameter_m=float(d.get('diameter_m', 0.0)),
        length_m=float(d.get('length_m', 0.0)),
        nose_radius_m=float(d.get('nose_radius_m', 0.0)),   # 0 = auto (shape)
        biconic=bool(d.get('biconic', False)),
        fore_length_m=float(d.get('fore_length_m', 0.0)),
        break_diameter_m=float(d.get('break_diameter_m', 0.0)),
        body_form=str(d['body_form']),
        body_span_m=float(d.get('body_span_m', 0.0) or 0.0),
        body_nose_length_m=float(d.get('body_nose_length_m', 0.0) or 0.0),
        reentry_cg_m=float(d.get('reentry_cg_m', 0.0) or 0.0),
        payload_kg=float(d.get('payload_kg', 0.0) or 0.0),
        maneuvering=bool(d['maneuvering']),
        glider_enabled=bool(d.get('glider_enabled', False)),
        glider_LD=float(d.get('glider_LD', 0.0)),
        wing_area_m2=float(d.get('wing_area_m2', 0.0) or 0.0),
        wing_aspect_ratio=float(d.get('wing_aspect_ratio', 0.0) or 0.0),
        wing_root_chord_m=float(d.get('wing_root_chord_m', 0.0) or 0.0),
        wing_span_exposed_m=float(d.get('wing_span_exposed_m', 0.0) or 0.0),
        wing_sweep_deg=float(d.get('wing_sweep_deg', 0.0) or 0.0),
        wing_thickness_m=float(d.get('wing_thickness_m', 0.0) or 0.0),
        n_wings=int(d.get('n_wings', 4) or 4),
        trim_alpha_deg=float(d.get('trim_alpha_deg', 0.0) or 0.0),
        trim_CL0=float(d.get('trim_CL0', 0.0) or 0.0),
        glider_guidance=str(d['glider_guidance']),
        pullup_g_limit=float(d.get('pullup_g_limit', 0.0) or 0.0),   # 0 = unlimited
        glider_pullup_g_max=float(d.get('glider_pullup_g_max', 10.0)),
        glider_terminal_dive=bool(d.get('glider_terminal_dive', False)),
        glider_terminal_alt_km=float(d.get('glider_terminal_alt_km', 0.0)),
        glider_bank_schedule=[tuple(b) for b in d.get('glider_bank_schedule', [])],
        glider_aero_model=str(d.get('glider_aero_model', 'polar')),
        glider_dive_target_lat_deg=float(d.get('glider_dive_target_lat_deg', 0.0)),
        glider_dive_target_lon_deg=float(d.get('glider_dive_target_lon_deg', 0.0)),
        glider_dive_target_radius_km=float(d.get('glider_dive_target_radius_km', 0.0)),
        glider_beta_entry_kg_m2=float(d.get('glider_beta_entry_kg_m2', 0.0)),
        glider_skip_count=int(d.get('glider_skip_count', 1)),
        glider_damping_zeta=float(d.get('glider_damping_zeta', 0.7)),
        glider_pullup_start_alt_km=float(d.get('glider_pullup_start_alt_km', 0.0) or 0.0),
        glider_control_surfaces=str(d.get('glider_control_surfaces', 'unknown')),
        glider_flap_area_ratio=float(d.get('glider_flap_area_ratio', 0.0)),
        glider_flap_deflection_deg=float(d.get('glider_flap_deflection_deg', 0.0)),
        separation_mode=str(d['separation_mode']),
        reentry_attitude=str(d.get('reentry_attitude', 'trim')),
        emissivity=float(d.get('emissivity', 0.85)),
        tps_material=str(d.get('tps_material', '')),
        nose_tps_material=str(d.get('nose_tps_material', '')),
        body_tps_material=str(d.get('body_tps_material', '')),
        body_tps_thickness_m=float(d.get('body_tps_thickness_m', 0.0)),
        structure_material=str(d.get('structure_material', '')),
        structure_limit_K=float(d.get('structure_limit_K', 0.0)),
        nose_tps_custom=(d.get('nose_tps_custom') or None),
        body_tps_custom=(d.get('body_tps_custom') or None),
        source=str(d.get('source', '')),
        notes=str(d.get('notes', '')),
    )


def run_separation_mode(params) -> str:
    """The run's separation mode, derived from the booster alone.

    ``'body'`` when the booster is marked ``body_reenters`` (its front end does
    not separate; the last stage IS the reentry body), else
    ``'separating_ro'``.  This is the ONLY place the booster and the reentry
    object are linked: the object file and the reentry plan carry no
    separation choice of their own.
    """
    return 'body' if bool(getattr(params, 'body_reenters', False)) else 'separating_ro'


def bind_ro_separation(params: 'BoosterParams') -> 'BoosterParams':
    """Return ``params`` with ``params.ro.separation_mode`` stamped from the
    booster's ``body_reenters`` so every reader of the object's mode agrees
    with the booster.  A shallow copy is returned when a change is needed;
    the caller's chain is never mutated.  No-op without a reentry object."""
    ro = getattr(params, 'ro', None)
    if ro is None:
        return params
    mode = run_separation_mode(params)
    if getattr(ro, 'separation_mode', 'separating_ro') == mode:
        return params
    import copy as _copy
    import dataclasses as _dc
    q = _copy.copy(params)
    q.ro = _dc.replace(ro, separation_mode=mode)
    return q


def effective_ro(params: 'BoosterParams') -> Optional[ROParams]:
    """Return the active reentry object (ROParams), or None if none is set.

    The reentry object is params.ro; the booster carries no reentry hardware.

    When the booster is marked ``body_reenters`` (the single source of the
    separation link; ro.separation_mode is derived from it and stamped onto the
    returned object) the reentering body IS the booster's own last stage (Pershing II MaRV class, or an
    SSTO where that stage is the whole vehicle) — not a separating object.
    In that case mass_kg / diameter_m / length_m are
    inherited from the booster's last-stage burnout state (mass_final,
    beta_kg_m2, diameter_m) instead of being independent payload fields.
    The user only has to set the maneuvering properties (L/D, g-limit,
    βₛ) — the body's mass and shape come from the booster params.
    """
    if params.ro is not None:
        ro = params.ro
        import dataclasses as _dc
        # ── Per-integration memo ──────────────────────────────────────────
        # effective_ro is a pure function of params.ro plus (for a body) the
        # last stage's static burnout mass/geometry — none of which change
        # during a flyout, yet _eom calls it every RK step.  The body branch
        # runs a dataclasses.replace (and a tumbling body a second one) on
        # every call, which profiling showed to be ~15 % of a body
        # trajectory.  Cache the derived object under a signature that captures
        # every input: the identity of params.ro (a new object whenever the RO
        # is edited or the equilibrium-glide split swaps it) and the last
        # stage's burnout mass/diameter/length.  A signature match returns the
        # cached object; any change misses and recomputes, so the result is
        # byte-identical to the uncached path.  The memo holds the source ro by
        # reference and compares it with `is` (not id(), which a freed object's
        # successor could re-use), so a swapped or edited RO always misses.
        _last = params
        while _last.stage2 is not None:
            _last = _last.stage2
        _body_mass = (_last.mass_initial - _last.mass_propellant
                      if _last.mass_propellant > 0 else _last.mass_final)
        _mode = run_separation_mode(params)
        _memo = params.__dict__.get('_ero_memo')
        if (_memo is not None and _memo[0] is ro
                and _memo[1] == (_body_mass, _last.diameter_m, _last.length_m,
                                 _mode)):
            return _memo[2]
        if getattr(ro, 'separation_mode', 'separating_ro') != _mode:
            ro = _dc.replace(ro, separation_mode=_mode)
        if _mode == 'body':
            # The vehicle IS the booster body — inherit mass and geometry
            # from the last stage's burnout state.  β remains user-specified
            # on the RV itself because there's no clean way to derive a
            # single scalar β from a Mach-dependent body Cd table.
            ro = _dc.replace(ro,
                mass_kg=float(_body_mass) if _body_mass > 0 else ro.mass_kg,
                diameter_m=(float(_last.diameter_m)
                            if _last.diameter_m > 0 else ro.diameter_m),
                length_m=(float(_last.length_m)
                          if _last.length_m > 0 else ro.length_m))
        # Reentry attitude: an uncontrolled (tumbling) body generates no lift
        # and its ballistic coefficient is DERIVED from geometry as a tumbling
        # cylinder (Hoerner two-orientation form) rather than the aeroshell's β.
        if getattr(ro, 'reentry_attitude', 'trim') == 'tumbling':
            _bt = tumbling_cylinder_beta(ro.mass_kg, ro.diameter_m,
                                         ro.length_m, cd=None)
            if _bt > 0:
                ro = _dc.replace(ro, beta_kg_m2=float(_bt),
                                 glider_enabled=False, glider_LD=0.0)
        params.__dict__['_ero_memo'] = (
            params.ro, (_body_mass, _last.diameter_m, _last.length_m, _mode), ro)
        return ro
    # No reentry object configured.  (Old JSON that stored reentry fields inline
    # is migrated to a synthesised params.ro in booster_from_dict, so by the time
    # we get here params.ro is the single source of truth.)
    return None


def compose_loadout(params: 'BoosterParams', ro=None,
                    num_ros: int = 1) -> 'BoosterParams':
    """Apply a run-level front-end loadout to a booster stage chain.

    The modeling contract: the stack carries the WHOLE front end through
    boost — bus + N × reentry object (+ fairing until jettison) — but only
    ONE object is modeled on the way back (the PBV is not maneuvering, so a
    single object's arc represents the pattern).

    Chains are stack-only (booster files carry no payload; a legacy file
    that did is normalised on load).  ``params.payload_kg`` is the run-time
    record of what is already composed onto the chain, so every stage's
    launch mass is adjusted by the DELTA between the new loadout
    (bus_mass_kg + N × ro.mass_kg) and that record: a chain composed twice
    is idempotent, and re-composing with a different object replaces the
    previous loadout rather than stacking on it.

    A body-reentering booster (``params.body_reenters``, the single source of
    the separation link) forces N = 1 — the object IS the last stage; a
    multi-object non-separating loadout is meaningless.

    Returns a deep copy; the input chain is never mutated.  When ro is None
    or carries no usable mass the chain is returned as built.
    """
    import copy as _copy
    p = _copy.deepcopy(params)
    if ro is None:
        return p
    n = max(1, int(num_ros))
    ro_mass = float(getattr(ro, 'mass_kg', 0.0) or 0.0)
    if run_separation_mode(params) == 'body':
        # NON-SEPARATING body: the airframe IS the last stage, so its structural
        # + residual burnout mass is ALREADY in the stage masses — adding the
        # RO's mass_kg would double-count (a unitary body seeded with the 2198 kg
        # burnout mass gained 2198 kg and its range collapsed 574 → 137 km), so
        # mass_kg is NEVER added for a body.  What the front end DOES own is an
        # explicit ADDED payload (ro.payload_kg: warhead / bus / guidance), which
        # rides the boosted stack and stays fused through burnout.  Add it with
        # the same tracked-baseline delta the separating path uses so composing
        # twice is idempotent: delta = payload − the already-baked body payload
        # (p.payload_kg).  Default 0 → every existing file flies byte-identical.
        payload = float(getattr(ro, 'payload_kg', 0.0) or 0.0)
        delta = payload - float(getattr(p, 'body_payload_kg', 0.0) or 0.0)
        if delta != 0.0:
            _node = p
            _last = p
            while _node is not None:
                _node.mass_initial += delta      # whole stack above carries it
                _last = _node
                _node = _node.stage2
            # Fused through burnout: the payload must sit in the last stage's
            # burnout mass so _mass_at_time (mass_initial − propellant) and
            # effective_ro inherit it for the reentry body.
            _last.mass_final += delta
        p.body_payload_kg = payload
        p.num_ros = 1
        p.ro_mass_kg = payload
        return p
    if ro_mass <= 0:
        return p          # nothing meaningful to compose; fly as built
    bus = float(getattr(p, 'bus_mass_kg', 0.0) or 0.0)
    loadout = bus + n * ro_mass
    delta = loadout - (p.payload_kg if p.payload_kg > 0 else 0.0)
    # Every stage's launch mass includes the whole stack above it, payload
    # included, so the delta applies to every node in the chain.
    _node = p
    _last = p
    while _node is not None:
        _node.mass_initial += delta
        _last = _node
        _node = _node.stage2
    p.payload_kg = loadout
    p.ro_mass_kg = ro_mass
    p.num_ros    = n
    return p


# ---------------------------------------------------------------------------
# Shared Cd vs Mach table — Forden Figure 1 piecewise-linear approximation.
# All packaged boosters use this same curve (Forden note 6).
# ---------------------------------------------------------------------------
_FORDEN_MACH = [0.0, 0.85, 1.0,  1.2,  2.0,  4.5]
_FORDEN_CD   = [0.2, 0.20, 0.27, 0.27, 0.20, 0.20]

# ---------------------------------------------------------------------------
# Decomposed drag model  (Chin 1961; NACA TN 4201; Crowell 1996)
# Cd_total = Cd_wave_nose + Cd_friction + Cd_base
# ---------------------------------------------------------------------------

NOSE_SHAPES = ["cone", "tangent_ogive", "von_karman",
               "lv_haack", "parabola", "blunt_cylinder"]

NOSE_SHAPE_LABELS = {
    "cone":           "Cone",
    "tangent_ogive":  "Tangent Ogive",
    "von_karman":     "Von Kármán (LD-Haack)",
    "lv_haack":       "LV-Haack (Sears-Haack)",
    "parabola":       "Parabola",
    "blunt_cylinder": "Blunt Cylinder",
}

# Backwards-compatibility aliases for configurations saved with old shape names.
_SHAPE_ALIAS = {
    "conical":    "cone",
    "parabolic":  "parabola",
    "sears_haack":"lv_haack",
    "v2":         "tangent_ogive",
    "elliptical": "cone",
}

# Tabulated wave drag (Cd_wave) at reference l/d_nose = 3.0.
# Source: NACA TN 4201 comparison data (models 56-63, l/d_nose=3, M=0.8-2.0)
# calibrated against Chin (1961) cone formula to isolate wave component.
# Scaled to actual ld via (ld_ref/ld)^2 from slender-body theory.
_WAVE_MACH   = [0.0,  0.6,  0.8,  0.9,  1.0,  1.1,  1.2,  1.5,  2.0,  3.0,  4.0,  5.0]
_WAVE_VK     = [0.000, 0.000, 0.000, 0.010, 0.030, 0.050, 0.060, 0.069, 0.067, 0.058, 0.052, 0.047]
_WAVE_LVH    = [0.000, 0.000, 0.010, 0.030, 0.070, 0.082, 0.085, 0.084, 0.077, 0.068, 0.061, 0.055]
_WAVE_PARA   = [0.000, 0.000, 0.010, 0.040, 0.090, 0.100, 0.100, 0.094, 0.087, 0.077, 0.069, 0.062]
_WAVE_LD_REF = 3.0

# Base-drag coefficient (referenced to base area) vs Mach, power-off.
# Two selectable empirical sources (see MODEL_OPTIONS below):
#   'datcom' — Booster DATCOM 2014, Fig 4.2.3.1-60 (verbatim DATA D4360) for the
#              supersonic table; the subsonic (M<1) portion is retained from
#              Chin because DATCOM's subsonic body base drag is a shape-dependent
#              correlation, not a Mach-only table.
#   'chin'   — Chin (1961) Fig 3-15 base-pressure coefficient (CD_base = -Cpb).
_BASE_MACH_CHIN = [0.0,   0.8,  1.0,  1.2,  1.5,  2.0,  2.5,  3.0,  4.0,  5.0]
_BASE_CDB_CHIN  = [0.000, 0.13, 0.20, 0.18, 0.14, 0.10, 0.08, 0.06, 0.05, 0.04]
_BASE_MACH_DATCOM = [0.0,  0.8,  0.9,   1.0,   1.125, 1.25, 1.5,  2.0,  2.5,
                     3.0,  3.5,  4.0,   4.5,   5.0,   5.5,  6.0]
_BASE_CDB_DATCOM  = [0.000, 0.13, 0.15, 0.178, 0.215, 0.20, 0.178, 0.144, 0.118,
                     0.097, 0.080, 0.068, 0.057, 0.049, 0.042, 0.037]


# ── Swappable reference-data / model sources ────────────────────────────────
# Lets the user pick the empirical source behind a model term, surfaced in the
# GUI under Analysis ▸ Reference Data.  Future toggles (atmosphere, etc.) are
# added as new entries with the same shape; the menu builds itself from this.
MODEL_OPTIONS = {
    "base_drag": {
        "label":   "Base drag",
        "choices": ("datcom", "chin"),
        "labels":  {"datcom": "DATCOM 2014 (Fig 4.2.3.1-60)",
                    "chin":    "Chin 1961 (Fig 3-15)"},
        "default": "datcom",
    },
    "friction": {
        "label":   "Skin friction",
        "choices": ("chin", "sommer_short"),
        "labels":  {"chin":         "Chin 1961 (mixed BL, Frankl-Voishel)",
                    "sommer_short": "Sommer-Short (reference temperature)"},
        "default": "chin",
    },
    "atmosphere": {
        "label":   "Atmosphere",
        "choices": ("msis", "std1976", "hot", "cold", "polar", "tropical"),
        "labels":  {"msis":     "NRLMSISE-00 (mean)",
                    "std1976":  "US Std 1976",
                    "hot":      "MIL-STD-210A hot day",
                    "cold":     "MIL-STD-210A cold day",
                    "polar":    "MIL-STD-210A polar day",
                    "tropical": "MIL-STD-210A tropical day"},
        "default": "msis",
        # Atmosphere model lives in atmosphere.py; reconfigure it on change.
        "apply":   lambda v: configure_atmosphere(model=v),
    },
    "terrain": {
        "label":   "Terrain (DEM)",
        "choices": ("terrarium", "glo30", "coarse"),
        "labels":  {"terrarium": "Terrarium z11 tiles (network, cached)",
                    "glo30":     "Copernicus GLO-30 (30 m TanDEM-X, network)",
                    "coarse":    "Bundled 0.05° grid (offline)"},
        "default": "terrarium",
        # Governs GUI-side pad-elevation sampling (terrain.py); the trajectory
        # integrator always uses the offline coarse grid for determinism.
        "apply":   lambda v: __import__("terrain").configure_terrain(v),
    },
}
_MODEL_SELECTION = {k: v["default"] for k, v in MODEL_OPTIONS.items()}
# Reflect the atmosphere model actually active (msis may have fallen back to
# std1976 if pymsis is unavailable) so the menu shows the true state.
_MODEL_SELECTION["atmosphere"] = atmosphere_source()


def get_model_option(key: str) -> str:
    """Currently selected source for model option *key*."""
    return _MODEL_SELECTION.get(key, MODEL_OPTIONS[key]["default"])


def set_model_option(key: str, value: str) -> None:
    """Select source *value* for model option *key* (validated)."""
    if key not in MODEL_OPTIONS:
        raise KeyError(f"unknown model option '{key}'")
    if value not in MODEL_OPTIONS[key]["choices"]:
        raise ValueError(f"'{value}' not a choice for '{key}' "
                         f"({MODEL_OPTIONS[key]['choices']})")
    _MODEL_SELECTION[key] = value
    _apply = MODEL_OPTIONS[key].get("apply")
    if _apply is not None:
        _apply(value)


# ---------------------------------------------------------------------------
# Solid-rocket-motor grain profiles  (Shafer 1959, Ch.16, Space Technology)
# Normalised (t/burn_time, F/F_peak) piecewise-linear curves.
# ---------------------------------------------------------------------------
_GRAIN_CURVES = {
    # Progressive: growing internal port — thrust rises through burn.
    "tubular":          [(0.0, 0.700), (0.25, 0.775), (0.50, 0.850),
                         (0.75, 0.925), (1.0, 1.000)],
    # Neutral: rod + annular tube areas cancel — nearly flat.
    "rod_tube":         [(0.0, 1.000), (0.50, 1.000), (1.0, 0.970)],
    # Regressive: large initial web area decreases with burnback.
    "double_anchor":    [(0.0, 1.000), (0.25, 0.875), (0.50, 0.750),
                         (0.75, 0.625), (1.0, 0.500)],
    # Neutral: star port maintains near-constant burning perimeter.
    "star":             [(0.0, 0.950), (0.10, 1.000), (0.40, 1.000),
                         (0.70, 0.980), (1.0, 0.950)],
    # Two-phase boost-sustain: high initial thrust then step down.
    "multi_fin":        [(0.0, 1.000), (0.35, 1.000), (0.40, 0.450), (1.0, 0.430)],
    # Two-phase: high-energy outer propellant then lower-energy core.
    "dual_composition": [(0.0, 1.000), (0.30, 1.000), (0.33, 0.300), (1.0, 0.280)],
}

GRAIN_LABELS = {
    "tubular":          "Tubular (progressive)",
    "rod_tube":         "Rod and tube (neutral)",
    "double_anchor":    "Double anchor (regressive)",
    "star":             "Star (neutral)",
    "multi_fin":        "Multi-fin (two-phase)",
    "dual_composition": "Dual composition (two-phase)",
}

# Realistic fill-factor (F_avg/F_peak) ranges per grain type — for UI warnings.
_GRAIN_FILL_RANGE = {
    "tubular":          (0.70, 0.95),
    "rod_tube":         (0.90, 1.00),
    "double_anchor":    (0.60, 0.85),
    "star":             (0.85, 1.00),
    "multi_fin":        (0.50, 0.75),
    "dual_composition": (0.35, 0.60),
}


def grain_fill_factor(grain_type: str) -> float:
    """F_avg/F_peak (fill factor) computed by trapezoidal integration of the grain curve."""
    curve = _GRAIN_CURVES.get(grain_type)
    if curve is None:
        return 1.0
    total = 0.0
    for i in range(len(curve) - 1):
        t0, f0 = curve[i]; t1, f1 = curve[i + 1]
        total += 0.5 * (f0 + f1) * (t1 - t0)
    return total


def _instantaneous_thrust_frac(grain_type: str, t_frac: float,
                                thrust_profile=None) -> float:
    """Return F(t)/F_peak at normalised time t/burn_time."""
    if thrust_profile:
        ts = [p[0] for p in thrust_profile]
        fs = [p[1] for p in thrust_profile]
        return _lin_interp(t_frac, ts, fs)
    curve = _GRAIN_CURVES.get(grain_type)
    if curve is None:
        return 1.0
    ts = [p[0] for p in curve]
    fs = [p[1] for p in curve]
    return _lin_interp(t_frac, ts, fs)


def _lin_interp(x, xs, ys):
    """Piecewise-linear interpolation, clamped at endpoints."""
    if x <= xs[0]:  return ys[0]
    if x >= xs[-1]: return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def _chin_pressure_coeff(sigma_deg: float, mach: float) -> float:
    """Chin (1961) Eq. 3-4: pressure coefficient for a cone of half-angle σ°."""
    if mach < 1e-6:
        return 0.0
    return (0.083 + 0.096 / mach**2) * (sigma_deg / 10.0) ** 1.69


def _cd_wave_cone(ld: float, mach: float) -> float:
    """Cone wave drag — Chin (1961) Eq. 3-4/3-6.  Linear ramp M=0.8→1.0."""
    import math
    sigma_deg = math.degrees(math.atan(1.0 / (2.0 * max(0.5, ld))))
    if mach >= 1.0:
        return _chin_pressure_coeff(sigma_deg, mach)
    if mach <= 0.8:
        return 0.0
    return _chin_pressure_coeff(sigma_deg, 1.0) * (mach - 0.8) / 0.2


def _cd_wave_ogive(ld: float, mach: float) -> float:
    """Tangent-ogive wave drag — Chin (1961) Eq. 3-9 (Miles formula)."""
    import math
    ld = max(0.5, ld)
    sigma_deg = math.degrees(math.atan(1.0 / (2.0 * ld)))
    if mach >= 1.0:
        P      = _chin_pressure_coeff(sigma_deg, mach)
        num    = 2.0 * (196.0 * ld**2 - 16.0)
        denom  = 28.0 * (mach + 18.0) * ld**2
        factor = max(0.0, 1.0 - num / denom)
        return P * factor
    if mach <= 0.8:
        return 0.0
    return _cd_wave_ogive(ld, 1.0) * (mach - 0.8) / 0.2


def _cd_wave_table(table_y, ld: float, mach: float) -> float:
    """Wave drag from NACA TN 4201 table at reference ld=3, scaled via (3/ld)²."""
    cd3 = _lin_interp(mach, _WAVE_MACH, table_y)
    return cd3 * (_WAVE_LD_REF / max(0.5, ld)) ** 2


def _nose_profile(shape: str, ld: float, n: int = 200):
    """
    Normalised (x, r) profile for a nose cone: x ∈ [0,1] (tip→base), r ∈ [0,1].
    r is radius / R_body, x is axial / L_nose.  Crowell (1996) geometry.
    """
    import math
    xs = np.linspace(0.0, 1.0, n + 1)

    if shape == 'cone':
        rs = xs.copy()

    elif shape == 'tangent_ogive':
        lod = 2.0 * max(0.5, ld)              # L/R
        rho = (lod**2 + 1.0) / 2.0            # radius of curvature / R
        rs  = np.sqrt(np.maximum(0.0, rho**2 - (lod * (1.0 - xs))**2)) - (rho - 1.0)

    elif shape == 'von_karman':
        theta = np.arccos(np.clip(1.0 - 2.0 * xs, -1.0, 1.0))
        rs    = np.sqrt(np.maximum(0.0, theta - np.sin(2.0 * theta) / 2.0)) / math.sqrt(math.pi)

    elif shape == 'lv_haack':
        theta = np.arccos(np.clip(1.0 - 2.0 * xs, -1.0, 1.0))
        rs    = np.sqrt(np.maximum(0.0,
                    theta - np.sin(2.0 * theta) / 2.0 + np.sin(theta)**3 / 3.0
                )) / math.sqrt(math.pi)

    elif shape == 'parabola':
        rs = 2.0 * xs - xs**2   # K'=1 tangent parabola (Crowell Eq. 7)

    else:
        rs = xs.copy()

    rs[0] = 0.0
    return xs, rs


# Shape bluntness multipliers for the screening nose-tip-radius default,
# relative to a sharp cone (=1.0), ordered by how rounded each profile runs
# near the tip (cone sharpest → Haack series bluntest; a blunt cylinder has a
# near-hemispherical cap).  These are deliberately MODEST, transparent factors,
# NOT a geometric tip curvature: the idealised nose profiles are all
# geometrically sharp at the very tip (R→0), and real nose-tip bluntness is a
# design choice the outer shape does not fix — every reentry object in ro_library/ is a
# "cone" yet spans 1–5 cm tips.  An explicit nose_radius_m therefore overrides
# this default (see ROParams.effective_nose_radius_m).
_NOSE_BLUNTNESS = {
    'cone':           1.0,
    'tangent_ogive':  1.25,
    'parabola':       1.25,
    'von_karman':     1.5,
    'lv_haack':       1.75,
    'blunt_cylinder': 3.0,
}


def nose_tip_radius(shape: str, diameter_m: float) -> float:
    """Screening default for the Sutton-Graves stagnation radius R_n (m) when an
    RV does not set nose_radius_m explicitly.

    R_n ≈ 0.10·R_body for a sharp cone — mid the 0.1–0.2 R_n/R_base range
    typical of blunted re-entry bodies — scaled up for blunter profiles via
    _NOSE_BLUNTNESS, clamped to [5 mm, R_body].  This is a transparent
    bluntness heuristic, not a geometric derivation; an explicit nose_radius_m
    is authoritative and overrides it.
    """
    R_body = 0.5 * max(0.0, float(diameter_m or 0.0))
    if R_body <= 0.0:
        return 0.05                       # legacy 5 cm fallback (no diameter)
    f = _NOSE_BLUNTNESS.get(_SHAPE_ALIAS.get(shape, shape), 1.0)
    return float(min(max(0.10 * R_body * f, 0.005), R_body))


def _s_wet_ratio(shape: str, ld: float) -> float:
    """
    Nose wetted area / reference area (A_ref = π R²).
    Numerical integration of 2π r ds.  (Crowell 1996 §5)
    ld = nose_length / body_diameter.
    """
    xs, rs   = _nose_profile(shape, ld)
    k        = 1.0 / (2.0 * max(0.5, ld))      # R/L
    drs      = np.diff(rs) / np.diff(xs)
    rs_mid   = 0.5 * (rs[:-1] + rs[1:])
    integrand = rs_mid * np.sqrt(1.0 + (k * drs)**2)
    return 4.0 * ld * float(np.sum(integrand * np.diff(xs)))  # = 2(L/R)·∫


def _mu_air(T_K: float) -> float:
    """Dynamic viscosity of air (Pa·s) — Sutherland's law."""
    T_ref, mu_ref, S = 273.15, 1.716e-5, 110.4
    return mu_ref * (T_K / T_ref) ** 1.5 * (T_ref + S) / (T_K + S)


def _cf_schoenherr(re_l: float) -> float:
    """Turbulent Cf — Schoenherr (Chin Eq. 4-2): √Cf·log₁₀(Cf·Re)=0.242."""
    import math
    cf = max(1e-8, 0.074 / re_l ** 0.2)   # Prandtl–Schlichting initial guess
    for _ in range(30):
        sq = math.sqrt(cf)
        f  = sq * math.log10(cf * re_l) - 0.242
        df = (math.log10(cf * re_l) / (2.0 * sq)
              + sq / (cf * math.log(10.0)))
        if abs(df) < 1e-15:
            break
        cf = max(1e-8, cf - f / df)
    return cf


def _cf_sommer_short(re_l: float, mach: float, temp_k: float = 250.0) -> float:
    """Mean all-turbulent flat-plate Cf — Sommer & Short reference-temperature
    method (PDAS TURBSF; Sivells-Payne incompressible base).  Validated to
    within ±3% of the published table at M≤3; better than Frankl-Voishel in the
    hypersonic regime where wall temperature matters.  temp_k defaults to a
    representative 250 K (the result is weakly T-dependent below ~M3)."""
    import math
    if re_l < 10.0:
        return 0.0
    SUTH = 110.4
    xx   = math.log10(re_l) - 1.5
    cfi  = 0.088 / (xx * xx)
    z    = 1.0 + 0.115 * mach * mach
    rstar = re_l / (((temp_k + SUTH) / (z * temp_k + SUTH)) * z ** 2.5)
    xx   = xx / (math.log10(rstar) - 1.5)
    return xx * xx * (cfi / z)


def _cd_friction(re_l: float, mach: float, s_wet_ratio: float) -> float:
    """
    Friction drag coefficient.  Source selectable via MODEL_OPTIONS['friction']:
      'chin' (default) — Blasius laminar (Chin Eq. 4-1) + Schoenherr turbulent
                         (Eq. 4-2), mixed BL at Re_tr=5×10^5 (Eq. 4-3),
                         Frankl-Voishel compressibility (Eq. 4-6).
      'sommer_short'   — Sommer-Short all-turbulent reference-temperature Cf
                         (better in the hypersonic regime).
    Both add a +10% roughness allowance (Chin §4-2).
    s_wet_ratio : S_wet / A_ref
    """
    import math
    if re_l < 1.0 or s_wet_ratio <= 0.0:
        return 0.0
    if get_model_option("friction") == "sommer_short":
        return _cf_sommer_short(re_l, mach) * 1.10 * s_wet_ratio
    re_tr  = 5.0e5
    cf_lam  = 1.328 / math.sqrt(re_l)   # Blasius (Chin Eq. 4-1)
    cf_turb = _cf_schoenherr(re_l)       # Schoenherr (Chin Eq. 4-2)
    s_lam   = min(1.0, re_tr / re_l)
    cf_mix  = cf_lam * s_lam + cf_turb * (1.0 - s_lam)   # Chin Eq. 4-3
    fv      = (1.0 + 0.2 * mach**2) ** (-0.467)           # Frankl-Voishel (Chin Eq. 4-6)
    return cf_mix * fv * 1.10 * s_wet_ratio                # +10% roughness


def _total_nozzle_exit_area(s: 'BoosterParams') -> float:
    """Total nozzle exit area (m²) of a stage.  Prefers the authoritative
    ``nozzle_exit_area_m2`` (the value the thrust pressure-correction uses);
    falls back to per-nozzle area × count when only the geometry fields are
    set.  0 when no nozzle data is stored."""
    if s is None:
        return 0.0
    tot = float(getattr(s, 'nozzle_exit_area_m2', 0.0) or 0.0)
    if tot > 0.0:
        return tot
    each = float(getattr(s, 'nozzle_area_each_m2', 0.0) or 0.0)
    n    = int(getattr(s, 'n_nozzles', 1) or 1)
    return each * max(1, n)


def base_bleed_ratio(stage: 'BoosterParams', base_diameter_m: float) -> float:
    """Power-on base-drag fraction (0–1) for a firing stage.

    A running engine's exhaust plume fills the nozzle exit, so base drag acts
    only over the ANNULUS of the aft face outside the exit:
    ``ratio = 1 − A_exit / A_base`` (floored at 0), with A_base the stage's own
    aft cross-section π(d/2)² and A_exit its total nozzle exit area.  Multiplied
    into the base-drag term, it removes the nozzle-covered share of the
    power-off base drag the build-up would otherwise charge during burn.

    Returns 1.0 (full power-off base drag, unchanged) when no nozzle area is
    stored or the diameter is unknown — so vehicles without nozzle data, and
    coast/reentry (unpowered) evaluations, are byte-identical.

    This is a screening midpoint: a full-flowing supersonic nozzle typically
    suppresses base drag almost entirely (power-on base drag ≈ 0), while the
    annulus form keeps the conservative geometric share outside the exit.
    """
    import math
    d = float(base_diameter_m or 0.0)
    if d <= 0.0:
        return 1.0
    A_base = math.pi * (d / 2.0) ** 2
    A_exit = _total_nozzle_exit_area(stage)
    if A_exit <= 0.0 or A_base <= 0.0:
        return 1.0
    return max(0.0, 1.0 - A_exit / A_base)


def _cd_base(mach: float, base_area_ratio: float = 1.0) -> float:
    """Base drag coefficient (ref. base area), power-off.

    Source selectable via MODEL_OPTIONS['base_drag']:
      'datcom' (default) — Booster DATCOM 2014 Fig 4.2.3.1-60
      'chin'             — Chin (1961) Fig 3-15
    """
    if get_model_option("base_drag") == "chin":
        cdb = _lin_interp(mach, _BASE_MACH_CHIN, _BASE_CDB_CHIN)
    else:
        cdb = _lin_interp(mach, _BASE_MACH_DATCOM, _BASE_CDB_DATCOM)
    return cdb * base_area_ratio


def _aerospike_effective_LD(spike_LD: float, spike_dD: float) -> float:
    """
    Effective-body fineness ratio for an aerospiked forebody.
    Derived from Ahmed & Qin (2011) Fig. 5 dividing-streamline angles for
    sharp pointed spikes on hemisphere-cylinder models:
        spike L/D = 1.5 → θ ≈ 14°  → L/D_eff ≈ 2.0
        spike L/D = 2.0 → θ ≈ 12.5° → L/D_eff ≈ 2.3
        spike L/D = 2.5 → θ ≈ 11°  → L/D_eff ≈ 2.6
    Linear fit:  L/D_eff = 1.0 + (2/3)·spike_LD
    Aerodisk contribution from §3.2.1 / Fig. 6:  + 2.0·spike_dD
    """
    if spike_LD <= 0.0:
        return 0.0
    return 1.0 + (2.0 / 3.0) * spike_LD + 2.0 * spike_dD


# ---------------------------------------------------------------------------
# Fin aerodynamics (lift + drag)
# ---------------------------------------------------------------------------

def _cl_alpha_fins(n_fins: int, span_m: float, c_root_m: float,
                   c_tip_m: float, body_diam_m: float,
                   mach: float, sweep_deg: float = 0.0) -> float:
    """
    Total fin normal-force (lift-curve) slope, /radian, referenced to body base
    area A_ref = π(d/2)².  Barrowman 1967 thesis **Eq 3-12** (subsonic, N fins),
    with the standard β = √(M²−1) supersonic extension:

        A_f  = s·(c_root + c_tip)/2        # one exposed fin planform
        AR   = (2s)² / A_f                 # reflected aspect ratio (span b = 2s)
        β    = √|M²−1|                     # Prandtl-Glauert (sub) / supersonic
        Γ_c  = mid-chord sweep; from LE sweep Λ:
                 tan Γ_c = tan Λ + (c_tip − c_root)/(2s)

        (C_Nα)_T = N·π·AR·(A_f/A_ref) / [ 2 + √(4 + (β·AR/cos Γ_c)²) ]

    The N·π numerator (Eq 3-12) is the correct cruciform result: for N=4, two
    fins lie in the pitch plane, giving 2× the single-fin 2π form (Eq 3-6).
    Body-fin interference uses Barrowman's simplified slender-body factor
    (Eq. K_T(B), the r/(s+r) form), identical to 1 + d/(2s+d):

        K_T(B) = 1 + r/(s+r) = 1 + d/(2s+d)

    NOTE — REGIME: this is Barrowman's small-AoA, linear, fin-stabilized
    slender-vehicle theory.  It is for BOOSTER fins (ascent stability / static
    margin), NOT for a high-AoA hypersonic gliding RV, whose L/D is a
    lifting-body (Newtonian) property and is supplied as ro.glider_LD.

    Falls back gracefully when span or chords are not yet entered.
    """
    import math
    if n_fins < 1 or span_m <= 0 or c_root_m <= 0 or body_diam_m <= 0:
        return 0.0
    c_tip_m = max(c_tip_m, 0.0)
    a_f = span_m * (c_root_m + c_tip_m) / 2.0       # one-fin exposed planform
    if a_f <= 0:
        return 0.0
    ar = (2.0 * span_m) ** 2 / a_f                  # reflected aspect ratio
    beta = math.sqrt(abs(mach * mach - 1.0))        # 0 at M=1 (finite denom)
    tan_gc = math.tan(math.radians(sweep_deg)) + (c_tip_m - c_root_m) / (2.0 * span_m)
    cos_gc = 1.0 / math.sqrt(1.0 + tan_gc * tan_gc)
    a_ref = math.pi * (body_diam_m / 2.0) ** 2
    denom = 2.0 + math.sqrt(4.0 + (beta * ar / cos_gc) ** 2)
    cn_alpha = n_fins * math.pi * ar * (a_f / a_ref) / denom
    k_tb = 1.0 + body_diam_m / (2.0 * span_m + body_diam_m)
    return float(cn_alpha * k_tb)


def _cd_fins(n_fins: int, span_m: float, c_root_m: float, c_tip_m: float,
             thickness_m: float, body_diam_m: float,
             mach: float, re_l: float = 5e6,
             sweep_deg: float = 0.0) -> float:
    """
    Total fin drag coefficient increment referenced to body base area A_ref.

    Two components (both at zero angle of attack):

    1. Friction drag — Mandell, Caporaso & Bengen (1973) / FerencDV model:
         CF = 1.328/√Re_c        (laminar, Re_c < 5×10⁵)
              0.074/Re_c⁰·²      (turbulent, Re_c ≥ 5×10⁵)
         mean chord  c_m  = (c_root + c_tip)/2
         AFP  = planform including body-overlap: A_exp + 0.5·c_root·d
         Cd_fric = 2·n·CF·(1 + 2·t/c_m)·AFP / A_ref   (both sides)

    2. Zero-lift wave drag at supersonic speeds (thin airfoil, Ackeret):
         Cd_wave = 4·n·(t/c_m)² / β  · A_exp / A_ref   (leading & trailing)

    Total = Cd_fric + Cd_wave.  Returns 0 when fins are not configured.
    """
    import math
    if n_fins < 1 or span_m <= 0 or c_root_m <= 0 or body_diam_m <= 0:
        return 0.0
    c_tip_m    = max(c_tip_m, 0.0)
    c_m        = 0.5 * (c_root_m + c_tip_m)          # mean chord
    a_exp      = span_m * c_m                          # exposed planform
    a_fp       = a_exp + 0.5 * c_root_m * body_diam_m # full planform (+ overlap)
    a_ref      = math.pi * (body_diam_m / 2.0) ** 2
    if a_ref <= 0 or c_m <= 0:
        return 0.0

    # Skin-friction coefficient at mean-chord Reynolds number
    mu_air = 1.789e-5                      # dynamic viscosity (kg/m·s, sea-level)
    speed_of_sound_ref = 340.0             # m/s reference (exact value doesn't
    # matter — re_l is passed in from the caller which has the real speed)
    # Use chord-based Re approximated from body Re_l and chord/length ratio.
    # Guard against body length zero.
    re_c = re_l * (c_m / max(c_m, 1.0))   # simplifies to re_l when body≈chord
    # A better estimate: use Re_l directly (conservative; fin is shorter).
    re_c = max(re_l * (c_m / max(c_m + span_m, 1e-3)), 1e3)

    if re_c < 5e5:
        cf = 1.328 / math.sqrt(re_c)
    else:
        cf = 0.074 / (re_c ** 0.2)

    tc = thickness_m / c_m if (thickness_m > 0 and c_m > 0) else 0.0
    cd_fric = (2.0 * n_fins * cf * (1.0 + 2.0 * tc) * a_fp) / a_ref

    # Supersonic wave drag (Ackeret thin-airfoil)
    beta = math.sqrt(max(mach ** 2 - 1.0, 0.0))
    if beta > 0.05 and tc > 0:
        cd_wave = (4.0 * n_fins * tc ** 2 / beta) * (a_exp / a_ref)
    else:
        cd_wave = 0.0

    return float(cd_fric + cd_wave)


# ---------------------------------------------------------------------------
# Grid (lattice) fins.  CALIBRATED to Washington & Miller, "Grid Fins - A New
# Concept for Booster Stability and Control," AIAA 93-0035 (the S1 fine-mesh
# configuration, their Fig. 2 geometry and Fig. 14 drag data).  Corroborated by
# three further papers (all read):
#   * Miller & Washington, "An Experimental Investigation of Grid Fin Drag
#     Reduction Techniques," AIAA 94-1914 — fin-only axial force for six
#     frame/web variants.  Confirms the transonic peak (CD rises 0.5→0.9,
#     decreases above 0.9) and quantifies that frame SHAPING cuts drag ~20-45%
#     (subsonic) / ~8-27% (supersonic; half-diamond best) vs the blunt baseline
#     F1, and that thick webs add ~13-19%.  This motivates the edge-shape factor
#     below; the model's default (blunt) matches W&M S1 ≈ Miller F1.
#   * DeSpirito & Sahu, ARL-RP-19 / AIAA 2001-0257 — total-booster Cx ≈ 0.43
#     (M2) → 0.45 (M3), roughly flat: corroborates the flat supersonic baseline.
#   * Abate, Duckerschein & Hathaway, AIAA 2000-0937 — free-flight GTCM;
#     total Cx flat below M≈0.77 then a steep transonic rise to a peak ~M1.05,
#     independently confirming the choke ONSET Mach (~0.77 ≈ _GRIDFIN_M_SUB).
# A grid fin is a
# box-frame lattice of thin cells, NOT a planar airfoil, so the flat-plate/
# Ackeret _cd_fins model does not apply.  W&M's measured axial-force (drag)
# coefficient, referenced to body cross-section, for the S1 fin (96.8% open,
# blunt-edged webs) is roughly FLAT at ~0.040 outside transonic with a modest
# transonic BUMP to ~0.065 (≈1.5×) peaking near M≈0.95 — NOT a large spike.
# The model therefore is:
#
#   drag = friction (on the wetted web area, chord Reynolds)
#        + blunt edge/profile drag (× web frontal blockage area)
#        + a transonic bump over [M_sub, M_rec] peaking at M_peak.
#
# The three flow regimes W&M describe (Fig. 6/7) — cells CHOKE below M=1, flow
# spills around the fin, the shock attaches then passes undisturbed, restoring
# supersonic behaviour by M≈1.6 — set the bump's onset/peak/recovery Mach
# anchors.  W&M (and Miller, Ref. 3) used 1-D isentropic relations for these;
# the Kantrowitz helper below reproduces that class of analysis, but note its
# GEOMETRIC contraction (1/porosity) under-predicts the choke for thin-web
# fins because boundary-layer blockage in the small cells is the co-cause W&M
# identify — so the bump Mach anchors are taken from the S1 data, not from
# geometric Kantrowitz alone.
#
# CALIBRATION CAVEATS: anchored to a single blunt-edged config (S1).  Sharp
# edges cut supersonic drag (W&M note this explicitly); the bucket shifts with
# cell size / Reynolds number; extrapolation to other geometries is uncertain.
# Constants are exposed for tuning.
#
# Supersonic corroboration (qualitative only): DeSpirito & Sahu, "Viscous CFD
# Calculations of Grid Fin Booster Aerodynamics in the Supersonic Flow Regime,"
# ARL-RP-19 / AIAA 2001-0257, measure a TOTAL-booster axial force Cx ≈ 0.43 at
# M2 and ≈ 0.45 at M3 (roughly flat / slightly rising) on a grid-finned TCAAM.
# That flat supersonic trend is consistent with this model's flat baseline and
# rules out a decaying-with-Mach form, but DeSpirito does NOT isolate the fin
# increment nor specify the cell web/pitch, so it is corroboration, not a
# quantitative fin-drag validation.
_GRIDFIN_CD_EDGE = 0.50   # blunt LE+TE / profile drag (× web blockage area)
_GRIDFIN_BUMP    = 0.55   # transonic peak as a fraction above the baseline
_GRIDFIN_M_SUB   = 0.75   # drag-rise onset Mach (W&M S1; Abate free-flight 0.77)
_GRIDFIN_M_PEAK  = 0.97   # Mach of the transonic drag peak (W&M S1; Miller ~0.9)
_GRIDFIN_M_REC   = 1.60   # Mach of recovery to supersonic behaviour (W&M S1)
# Edge-shape factor on the pressure (edge + transonic-bump) drag, NOT friction.
# 1.0 = blunt rectangular webs (W&M S1, Miller F1 baseline — the conservative
# default).  Miller 94-1914 Tables 2/3: shaping the frame cross-section to a
# single wedge / half-diamond cuts drag ~20-45% subsonic, ~8-27% supersonic, so
# a sharp/shaped fin is ~0.6-0.85.  Per-vehicle via grid_fin_edge_factor.
_GRIDFIN_EDGE_BLUNT = 1.0


def _isentropic_area_ratio(mach: float, gamma: float = 1.4) -> float:
    """A/A* for quasi-1D isentropic flow (Mach ≠ 0)."""
    import math
    if mach <= 0:
        return float('inf')
    return ((1.0 / mach)
            * ((2.0 / (gamma + 1.0)) * (1.0 + 0.5 * (gamma - 1.0) * mach * mach))
            ** ((gamma + 1.0) / (2.0 * (gamma - 1.0))))


def _kantrowitz_contraction_ratio(mach: float, gamma: float = 1.4) -> float:
    """
    Maximum self-starting internal contraction ratio CR = A_capture/A_throat
    at flight Mach `mach` (Kantrowitz & Donaldson, NACA 1945).  A normal shock
    at the face decelerates the flow to subsonic Mach M_y; the throat must then
    pass that subsonic flow at M=1, so CR = (A/A*)|_{M_y}.
    """
    import math
    if mach <= 1.0:
        return 1.0
    my2 = ((1.0 + 0.5 * (gamma - 1.0) * mach * mach)
           / (gamma * mach * mach - 0.5 * (gamma - 1.0)))
    return _isentropic_area_ratio(math.sqrt(my2), gamma)


def _gridfin_start_mach(contraction_ratio: float, gamma: float = 1.4) -> float:
    """
    Mach at which a lattice of contraction ratio CR (=1/porosity) self-starts,
    by inverting the Kantrowitz limit (monotone in M).  Bisection on [1.01, 8].
    """
    cr = max(float(contraction_ratio), 1.0 + 1e-6)
    lo, hi = 1.01, 8.0
    if _kantrowitz_contraction_ratio(hi, gamma) < cr:
        return hi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if _kantrowitz_contraction_ratio(mid, gamma) < cr:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Grid-fin SOLIDITY (σ)
# ---------------------------------------------------------------------------
# Solidity σ is the fraction of the grid fin's frontal frame area that is
# blocked by the lattice webs (σ = 1 − porosity φ).  It is the single physical
# quantity that drives grid-fin drag, and it stands in for TWO geometric
# details that are very hard to obtain from open sources — the web (wall)
# thickness t and the cell pitch (centre-to-centre spacing) p.
#
# If you DO know t and p, compute σ exactly for a square lattice from:
#
#       σ = 1 − ((p − t) / p)²        (≈ 2·t/p for thin webs)
#
# If you DON'T, estimate σ from imagery (how "filled in" the lattice looks).
# Empirical range for REAL fins (see METHODS "Empirical σ range"): the aero
# region is σ ≈ 0.04–0.12.  Large booster / launch-vehicle / SLBM fins (STARS,
# Topol, Falcon 9, R-77 boosters) sit open, σ ≈ 0.04–0.06; the smaller air-to-
# air (AA-12) class is σ ≈ 0.09–0.12.  σ ≳ 0.15 is atypical for an aero surface
# (only structural fin-roots / deliberately thick CFD cases — they choke
# transonically).  Booster default ≈ 0.05.  Supplying σ avoids guessing t and p
# separately; grid_fin_solidity() below converts t,p → σ when you have them.

# Representative cells-across-frame used to estimate the (secondary) friction
# wetted area when σ is given but the cell pitch is not.
_GRIDFIN_DEFAULT_CELLS = 10.0


def grid_fin_solidity(web_thickness_m: float, cell_pitch_m: float) -> float:
    """
    Grid-fin solidity σ (blocked frontal fraction) from web thickness and cell
    pitch, assuming a square lattice:

        σ = 1 − ((p − t) / p)²

    Returns σ clamped to (0, 1).  Use this to convert a known web/pitch pair
    into the σ that the drag model consumes; if web/pitch are unknown, estimate
    σ directly from imagery instead (see the section header above).
    """
    p = float(cell_pitch_m)
    t = float(web_thickness_m)
    if p <= 0.0:
        return 0.0
    t = min(max(t, 0.0), p)                       # web cannot exceed the pitch
    sigma = 1.0 - ((p - t) / p) ** 2
    return min(max(sigma, 1e-3), 0.999)


def _gridfin_geometry(width_m: float, height_m: float, chord_m: float,
                      web_thickness_m: float, cell_pitch_m: float,
                      solidity: float = 0.0):
    """
    Derived lattice geometry for one grid fin.  Returns
    (A_frame, porosity φ, A_block, web_wetted_area).  Square cells assumed.

    Blockage source: if `solidity` (σ) > 0 it is used directly (the
    approximation path — σ stands in for web thickness + cell pitch); otherwise
    σ is derived from web_thickness_m and cell_pitch_m via grid_fin_solidity().
    The friction wetted area needs an absolute cell pitch; when only σ is given
    (no pitch), a representative pitch (frame / _GRIDFIN_DEFAULT_CELLS) is used,
    which affects only the secondary friction term.
    """
    a_frame = max(width_m * height_m, 0.0)
    if solidity and solidity > 0.0:
        phi = 1.0 - min(max(float(solidity), 1e-3), 0.999)
        pitch = (cell_pitch_m if cell_pitch_m > 0.0
                 else max(min(width_m, height_m), 1e-3) / _GRIDFIN_DEFAULT_CELLS)
    else:
        pitch = max(cell_pitch_m, web_thickness_m + 1e-4)
        phi = ((pitch - web_thickness_m) / pitch) ** 2     # open-area fraction
    phi = min(max(phi, 0.02), 0.98)
    a_block = (1.0 - phi) * a_frame
    # Total web length in the frontal plane (horizontal + vertical members).
    # For a w×h frame on pitch p this is ≈ 2·A_frame/p for many cells.
    l_web = 2.0 * a_frame / pitch
    a_wet = 2.0 * l_web * max(chord_m, 0.0)            # both faces of each web
    return a_frame, phi, a_block, a_wet


def grid_fins_deployed(n_total: int, deploy_schedule, t_s) -> int:
    """
    Number of grid fins aerodynamically active at mission time t_s.

    deploy_schedule is a list of [deploy_time_s, n_fins] batches; n_fins become
    active once t_s >= deploy_time_s.  An empty/None schedule (or t_s None) means
    all n_total fins are active (the steady-state / no-timing case).  The result
    is capped at n_total.
    """
    if n_total <= 0:
        return 0
    if not deploy_schedule or t_s is None:
        return n_total
    deployed = 0
    for entry in deploy_schedule:
        try:
            t_dep, count = float(entry[0]), int(entry[1])
        except (TypeError, IndexError, ValueError):
            continue
        if t_s >= t_dep:
            deployed += count
    return max(0, min(deployed, n_total))


def _cd_gridfins(n_fins: int, width_m: float, height_m: float, chord_m: float,
                 web_thickness_m: float, cell_pitch_m: float,
                 body_diam_m: float, mach: float, re_chord: float = 5e6,
                 edge_factor: float = _GRIDFIN_EDGE_BLUNT,
                 solidity: float = 0.0) -> float:
    """
    Total grid-fin axial-force (drag) coefficient increment referenced to the
    body base area A_ref = π(d/2)².  Calibrated to Washington & Miller S1
    (AIAA 93-0035, Fig. 14): a roughly flat baseline (web friction + blunt-edge
    drag) plus a modest transonic bump.  See the module header for references
    and calibration caveats.  Returns 0 when not configured.

    Blockage source: if `solidity` (σ) > 0 it is used directly (σ stands in for
    web thickness + cell pitch — see grid_fin_solidity()); otherwise σ is
    derived from web_thickness_m and cell_pitch_m.

    edge_factor scales the pressure (edge + transonic-bump) drag, not friction:
    1.0 = blunt webs (W&M S1 / Miller F1 baseline); ~0.6-0.85 for shaped/sharp
    frames (Miller 94-1914 Tables 2/3).

    Validated against W&M S1 (4 fins, frame 2.14×3.243 in, web 0.006 in, pitch
    0.371 in, chord 0.384 in, 5.0 in body): reproduces ~0.042 subsonic,
    ~0.065 transonic peak, ~0.038 supersonic.
    """
    import math
    if (n_fins < 1 or width_m <= 0 or height_m <= 0 or chord_m <= 0
            or body_diam_m <= 0):
        return 0.0
    a_ref = math.pi * (body_diam_m / 2.0) ** 2
    if a_ref <= 0:
        return 0.0
    a_frame, phi, a_block, a_wet = _gridfin_geometry(
        width_m, height_m, chord_m, web_thickness_m, cell_pitch_m,
        solidity=solidity)

    # Baseline drag (roughly Mach-flat outside transonic):
    #   (a) skin friction on the wetted web area (flat-plate, chord Reynolds)
    #   (b) blunt leading/trailing-edge + profile drag on the web blockage area,
    #       scaled by the edge-shape factor (sharpening cuts pressure drag).
    re_c = max(re_chord, 1e3)
    cf = 1.328 / math.sqrt(re_c) if re_c < 5e5 else 0.074 / (re_c ** 0.2)
    cd_fric = n_fins * cf * a_wet / a_ref
    cd_edge = n_fins * _GRIDFIN_CD_EDGE * a_block / a_ref * max(edge_factor, 0.0)
    base = cd_fric + cd_edge

    # Transonic bump (choke → spillage → shock-attachment), peaking at M_peak
    # and recovering by M_rec.  Smooth half-cosines, zero outside [M_sub, M_rec].
    bump = 0.0
    if _GRIDFIN_M_SUB <= mach <= _GRIDFIN_M_REC:
        if mach <= _GRIDFIN_M_PEAK:
            x = (mach - _GRIDFIN_M_SUB) / (_GRIDFIN_M_PEAK - _GRIDFIN_M_SUB)
            shape = 0.5 * (1.0 - math.cos(math.pi * x))          # 0 → 1
        else:
            x = (mach - _GRIDFIN_M_PEAK) / (_GRIDFIN_M_REC - _GRIDFIN_M_PEAK)
            shape = 0.5 * (1.0 + math.cos(math.pi * x))          # 1 → 0
        bump = _GRIDFIN_BUMP * base * shape

    return float(base + bump)


def _cl_alpha_gridfins(n_fins: int, width_m: float, height_m: float,
                       chord_m: float, web_thickness_m: float,
                       cell_pitch_m: float, body_diam_m: float,
                       mach: float, solidity: float = 0.0) -> float:
    """
    Grid-fin normal-force slope (/rad) referenced to body base area, used by
    the L/D estimator (the trajectory integrator flies a pitch program and does
    not use fin lift).  Reduced-order cascade model: the lattice members act as
    low-aspect-ratio lifting surfaces; the slope scales with the lifting
    planform (≈ web-wetted area) and a per-Mach 2-D lift slope, with the
    transonic "bucket" (W&M Fig. 6: C_NF,α drops through M_sub..M_rec) folded
    in.  Approximate — flagged as such; the trajectory does not use it.
    """
    import math
    if (n_fins < 1 or width_m <= 0 or height_m <= 0 or chord_m <= 0
            or body_diam_m <= 0):
        return 0.0
    a_ref = math.pi * (body_diam_m / 2.0) ** 2
    if a_ref <= 0:
        return 0.0
    a_frame, phi, a_block, a_wet = _gridfin_geometry(
        width_m, height_m, chord_m, web_thickness_m, cell_pitch_m,
        solidity=solidity)
    # 2-D lift slope per member surface (Prandtl-Glauert / Ackeret)
    if mach < 0.95:
        cla_2d = 2.0 * math.pi / math.sqrt(max(1.0 - mach * mach, 0.04))
    else:
        cla_2d = 4.0 / math.sqrt(max(mach * mach - 1.0, 0.04))
    # Lifting planform ≈ half the wetted web area (the load-bearing members)
    a_lift = 0.5 * a_wet
    # Transonic "bucket": effectiveness drops through the choked band
    # [M_sub, M_rec] and recovers to full once the cells start (W&M Fig. 6).
    eff = 1.0
    if _GRIDFIN_M_SUB <= mach < _GRIDFIN_M_REC:
        eff = 0.5                                    # degraded while choked
    return float(n_fins * cla_2d * eff * a_lift / a_ref)


def _cd_nose_shape(nose_shape: str, ld: float, mach: float,
                   re_l: float = 5e6, ld_body: float = None,
                   aerospike_LD: float = 0.0,
                   aerospike_dD: float = 0.0,
                   base_area_ratio: float = 1.0,
                   biconic: tuple = None) -> float:
    """
    Total zero-lift drag coefficient (Cd_wave + Cd_friction + Cd_base).
    Source: Chin (1961) *Booster Configuration Design*; NACA TN 4201; Crowell (1996).

    nose_shape   : key from NOSE_SHAPES
    ld           : nose fineness ratio = nose_length / body_diameter (clamped 0.5–10)
    mach         : free-stream Mach number
    re_l         : Reynolds number based on body length (default 5×10^6)
    ld_body      : full-body fineness ratio = body_length / body_diameter;
                   drives cylinder friction term.  None → 2×ld estimate.
    aerospike_LD : spike length / body diameter (0 = no aerospike)
    aerospike_dD : aerodisk diameter / body diameter (0 = pointed tip)
                   When aerospike_LD > 0, wave drag is replaced by the
                   minimum of (actual nose, effective-body cone) — see
                   _aerospike_effective_LD docstring.  Active only above
                   Mach 0.8 since a spike requires a bow shock to replace.
    """
    nose_shape = _SHAPE_ALIAS.get(nose_shape, nose_shape)
    ld   = max(0.5, min(float(ld), 10.0))
    mach = max(0.0, float(mach))

    # ── Blunt Cylinder ────────────────────────────────────────────────────────
    if nose_shape == 'blunt_cylinder':
        if mach <= 0.8:   cd_blunt = 0.9
        elif mach <= 1.5: cd_blunt = 0.9 + (mach - 0.8) / 0.7 * 1.3
        else:             cd_blunt = 2.2
        if aerospike_LD > 0.0 and mach > 0.8:
            # Spike replaces the blunt shock with an effective slender cone.
            ld_eff = _aerospike_effective_LD(aerospike_LD, aerospike_dD)
            # Friction (~0.05) + base (~0.06) typical for hemisphere-cylinder.
            return _cd_wave_cone(ld_eff, mach) + 0.11
        return cd_blunt

    # ── Forden fallback (legacy) ──────────────────────────────────────────────
    if nose_shape in ('forden', '', None):
        return _lin_interp(mach, _FORDEN_MACH, _FORDEN_CD)

    # ── Wave drag (nose shape-specific) ──────────────────────────────────────
    if nose_shape == 'cone':
        cd_wave = _cd_wave_cone(ld, mach)
    elif nose_shape == 'tangent_ogive':
        cd_wave = _cd_wave_ogive(ld, mach)
    elif nose_shape == 'von_karman':
        cd_wave = _cd_wave_table(_WAVE_VK, ld, mach)
    elif nose_shape == 'lv_haack':
        cd_wave = _cd_wave_table(_WAVE_LVH, ld, mach)
    elif nose_shape == 'parabola':
        cd_wave = _cd_wave_table(_WAVE_PARA, ld, mach)
    else:
        cd_wave = _cd_wave_cone(ld, mach)

    # ── Aerospike: replace wave drag with effective-body cone if smaller ──────
    if aerospike_LD > 0.0 and mach > 0.8:
        ld_eff = _aerospike_effective_LD(aerospike_LD, aerospike_dD)
        cd_wave = min(cd_wave, _cd_wave_cone(ld_eff, mach))

    # ── Biconic (two-cone) wave drag, Chin framework ─────────────────────────
    # A declared biconic nose is a steep fore cone on a shallow aft frustum;
    # its transonic/supersonic wave drag is the SUM of the two, not a single
    # cone.  Kept in the SAME Chin cone-pressure framework as the single noses
    # (valid across the boost regime, unlike the hypersonic-Newtonian reentry
    # build-up), so the ascent M0.8-1.2 wave-drag peak is right.  Each segment's
    # cone-pressure coefficient is taken at its OWN half-angle and weighted by
    # its base-area share; the fore cone rides on the break area (br²), the aft
    # frustum on the annulus (1-br²).  Reduces EXACTLY to the single cone when
    # the two half-angles are equal (both terms share one Cp).  Overrides the
    # single-nose wave term above (biconic and aerospike are mutually exclusive
    # in practice; if both are set the biconic two-cone form wins).
    if biconic is not None:
        import math as _m
        _ld_fore, _theta2_deg, _br = biconic
        _br = max(1e-3, min(float(_br), 1.0))
        _ld_aft_eq = 1.0 / (2.0 * _m.tan(_m.radians(
            max(1.0, min(float(_theta2_deg), 89.0)))))
        cd_wave = (_cd_wave_cone(float(_ld_fore), mach) * _br * _br
                   + _cd_wave_cone(_ld_aft_eq, mach) * (1.0 - _br * _br))

    # ── Friction drag (nose wetted area + cylindrical body section) ───────────
    nose_swet = _s_wet_ratio(nose_shape, ld)
    if ld_body is None:
        ld_body = max(ld * 2.0, ld + 2.0)
    # cylinder S_wet/A_ref = π D L_cyl/(π R²) = 4 L_cyl/D = 4(ld_body − ld_nose)
    cyl_swet = 4.0 * max(0.0, ld_body - ld)
    cd_fric  = _cd_friction(re_l, mach, nose_swet + cyl_swet)

    # ── Base drag ─────────────────────────────────────────────────────────────
    # base_area_ratio < 1 during powered flight: the plume fills the nozzle
    # exit, so the base drag is charged only over the annulus outside it
    # (base_bleed_ratio).  1.0 (default) = full power-off base drag, unchanged.
    cd_base = _cd_base(mach, base_area_ratio)

    return cd_wave + cd_fric + cd_base


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Built-in booster database (data files, not code)
# ---------------------------------------------------------------------------

# Boosters are DATA, not code: BOOSTER_DB is populated from
# booster_library/*.booster.json by load_booster_library() at the end of this
# module.  Additional boosters are loaded at runtime from custom_boosters.json
# and overlay any same-name entries.
BOOSTER_DB: dict = {}


# Extra dirs (highest precedence last) for user reentry objects; the GUI sets
# this to its writable library, mirroring USER_FLIGHT_PLAN_DIRS.
USER_RO_DIRS: list = []


def resolve_reentry_object(name: str, extra_dirs=()):
    """The shipped (or user) reentry object called ``name`` as hardware-only
    ROParams with its default reentry plan applied, or None.  Files are
    matched by their ``name`` field, as the GUI library loader does; a user
    file of the same name overrides the bundled one."""
    import json as _js
    from pathlib import Path as _P
    found = None
    _bundled = _P(__file__).resolve().parent / "ro_library"
    for d in [_bundled, *[_P(x) for x in extra_dirs]]:
        if not d.exists():
            continue
        for fp in sorted(d.glob("*.ro.json")):
            try:
                dd = _js.loads(fp.read_text())
            except Exception:
                continue
            if str(dd.get('name', '')) == name:
                found = dd
    if found is None:
        return None
    ro = ro_from_dict(found)
    rp = load_reentry_plan(name, extra_dirs=USER_REENTRY_PLAN_DIRS)
    return apply_reentry_plan(ro, rp) if rp is not None else ro


def get_booster(name: str, plan: str = None) -> BoosterParams:
    """Return the named booster with its flight plan applied, and with the
    reentry object the plan names (``reentry_object``) attached when the
    booster carries none — so a headless run flies what the GUI's default run
    flies.  Booster files are stack-only; the object's mass is composed onto
    the chain by integrate_trajectory / compose_loadout.

    A booster can fly many flight plans: the booster-named file is the
    "(default)" plan; named variants (see list_flight_plans) reference the
    booster and are applied ON TOP of the default, so a variant need only
    carry the fields it changes.  ``plan`` selects a variant explicitly;
    when None, the ACTIVE_FLIGHT_PLANS selection (set by the GUI) is used,
    falling back to the default.  Headless callers that never touch either
    get the default plan, exactly as before.
    """
    if name not in BOOSTER_DB:
        raise ValueError(f"Unknown booster '{name}'. Available: {list(BOOSTER_DB)}")
    p = BOOSTER_DB[name]()
    fp = load_flight_plan(name, extra_dirs=USER_FLIGHT_PLAN_DIRS)
    if fp is not None:
        p = apply_flight_plan(p, fp)
    if plan is None:
        plan = ACTIVE_FLIGHT_PLANS.get(name)
    vp = None
    if plan and plan != DEFAULT_PLAN_LABEL:
        vp = load_flight_plan(name, extra_dirs=USER_FLIGHT_PLAN_DIRS, plan=plan)
        if vp is not None:
            p = apply_flight_plan(p, vp)
    if p.ro is None:
        _fp_all = fp or {}
        if plan and plan != DEFAULT_PLAN_LABEL and vp:
            _fp_all = {**_fp_all, **vp}
        _oname = str(_fp_all.get('reentry_object', '') or '')
        if _oname:
            _ro = resolve_reentry_object(_oname, extra_dirs=USER_RO_DIRS)
            if _ro is not None:
                p.ro = _ro
    return p




def booster_to_dict(p: BoosterParams, include_flight_plan: bool = True) -> dict:
    """Serialise a BoosterParams to a JSON-compatible dict.

    With ``include_flight_plan=False`` the flight-plan fields (guidance and the
    per-stage schedule -- everything in ``_FLIGHT_PLAN_TOP_KEYS`` and
    ``_FLIGHT_PLAN_STAGE_KEYS``) are omitted at every nesting level, yielding a
    hardware-only booster.  That is the form the booster library stores; the
    flight plan travels separately in a ``.flightplan.json`` file.  The default
    (``True``) keeps the full serialisation for internal round-trips.
    """
    d = {
        'name':                  p.name,
        'mass_initial':          p.mass_initial,
        'mass_propellant':       p.mass_propellant,
        'mass_final':            p.mass_final,
        'diameter_m':            p.diameter_m,
        'length_m':              p.length_m,
        'burn_time_s':           p.burn_time_s,
        'coast_time_s':          p.coast_time_s,
        'isp_s':                 p.isp_s,
        'guidance':               p.guidance,
        'burnout_angle_deg':        p.burnout_angle_deg,
        'loft_angle_rate_deg_s': p.loft_angle_rate_deg_s,
        'mach_table':            list(p.mach_table),
        'cd_table':              list(p.cd_table),
        'payload_kg':            p.payload_kg,
        'body_reenters':         p.body_reenters,
        'bus_mass_kg':           p.bus_mass_kg,
        'num_ros':               p.num_ros,
        'shroud_mass_kg':         p.shroud_mass_kg,
        'shroud_jettison_alt_km': p.shroud_jettison_alt_km,
        'shroud_length_m':        p.shroud_length_m,
        'shroud_diameter_m':      p.shroud_diameter_m,
        'nozzle_exit_area_m2':    p.nozzle_exit_area_m2,
        'n_nozzles':              p.n_nozzles,
        'nozzle_area_each_m2':    p.nozzle_area_each_m2,
        'solid_motor':            p.solid_motor,
        'grain_type':             p.grain_type,
        'thrust_peak_N':          p.thrust_peak_N,
        'thrust_profile':         list(p.thrust_profile),
        'conical':                p.conical,
        'top_diameter_m':         p.top_diameter_m,
        'has_interstage':         p.has_interstage,
        'interstage_length_m':    p.interstage_length_m,
        'interstage_mass_kg':     p.interstage_mass_kg,
        'interstage_jettison_s':  p.interstage_jettison_s,
        'nose_shape':             p.nose_shape,
        'nose_length_m':          p.nose_length_m,
        'shroud_nose_shape':      p.shroud_nose_shape,
        'shroud_nose_length_m':   p.shroud_nose_length_m,
        'aerospike_LD':           p.aerospike_LD,
        'aerospike_dD':           p.aerospike_dD,
        'has_fins':               p.has_fins,
        'n_fins':                 p.n_fins,
        'fin_span_m':             p.fin_span_m,
        'fin_root_chord_m':       p.fin_root_chord_m,
        'fin_tip_chord_m':        p.fin_tip_chord_m,
        'fin_thickness_m':        p.fin_thickness_m,
        'fin_sweep_deg':          p.fin_sweep_deg,
        'has_grid_fins':          p.has_grid_fins,
        'n_grid_fins':            p.n_grid_fins,
        'grid_fin_width_m':         p.grid_fin_width_m,
        'grid_fin_height_m':        p.grid_fin_height_m,
        'grid_fin_chord_m':         p.grid_fin_chord_m,
        'grid_fin_web_thickness_m': p.grid_fin_web_thickness_m,
        'grid_fin_cell_pitch_m':    p.grid_fin_cell_pitch_m,
        'grid_fin_solidity':        p.grid_fin_solidity,
        'grid_fin_edge_factor':     p.grid_fin_edge_factor,
        'grid_fin_deploy_schedule': list(p.grid_fin_deploy_schedule or []),
        'payload_diameter_m':     p.payload_diameter_m,
        'pbv_diameter_m':         p.pbv_diameter_m,
        'pbv_length_m':           p.pbv_length_m,
        'source':                 p.source,
        'notes':                  p.notes,
        'n_boosters':             p.n_boosters,
        'booster_thrust_n':       p.booster_thrust_n,
        'booster_burn_time_s':    p.booster_burn_time_s,
        'booster_inert_kg':       p.booster_inert_kg,
        'booster_prop_kg':        p.booster_prop_kg,
        'booster_isp_s':          p.booster_isp_s,
        'booster_nozzle_area_m2': p.booster_nozzle_area_m2,
        'booster_diam_m':         p.booster_diam_m,
        'booster_length_m':       p.booster_length_m,
        'booster_cd':             p.booster_cd,
        'booster_core_delay_s':   p.booster_core_delay_s,
        'booster_jettison_s':     p.booster_jettison_s,
    }
    # Reentry object: written as the embedded 'ro' dict when present.  The
    # booster carries no reentry hardware, so there is nothing else to write.
    if p.ro is not None:
        d['ro'] = ro_to_dict(p.ro)
    # Per-stage pitch overrides — only written when set (keeps dicts compact)
    if p.stage_turn_start_s is not None:
        d['stage_turn_start_s'] = p.stage_turn_start_s
    if p.stage_turn_stop_s is not None:
        d['stage_turn_stop_s'] = p.stage_turn_stop_s
    if p.stage_burnout_angle_deg is not None:
        d['stage_burnout_angle_deg'] = p.stage_burnout_angle_deg
    if p.stage_cutoff_s is not None:
        d['stage_cutoff_s'] = p.stage_cutoff_s
    if p.stage_yaw_start_s is not None:
        d['stage_yaw_start_s'] = p.stage_yaw_start_s
    if p.stage_yaw_stop_s is not None:
        d['stage_yaw_stop_s'] = p.stage_yaw_stop_s
    if p.stage_yaw_final_az_deg is not None:
        d['stage_yaw_final_az_deg'] = p.stage_yaw_final_az_deg
    if p.stage2 is not None:
        d['stage2'] = booster_to_dict(p.stage2, include_flight_plan)
    if not include_flight_plan:
        # Hardware-only: no plan keys, and no run-time loadout record either
        # (the composed payload and object count belong to the run, not the
        # booster file — the reentry object carries its own mass).
        for _k in (*_FLIGHT_PLAN_TOP_KEYS, *_FLIGHT_PLAN_STAGE_KEYS,
                   *_RUN_LOADOUT_KEYS):
            d.pop(_k, None)
    return d


BOOSTER_SCHEMA = 2      # bump when a conversion is added below
RO_SCHEMA = 2


def upgrade_booster_dict(d: dict) -> dict:
    """Convert a booster dict of ANY vintage into the current schema.

    This is the single place old Thrusty files are understood.  Every
    compatibility rule lives here as an explicit conversion, so
    :func:`booster_from_dict` can read the current schema and nothing else.
    The function is pure (the caller's dict is not mutated) and idempotent:
    a dict already at ``BOOSTER_SCHEMA`` is returned unchanged.

    Conversions, oldest first:

    * ``guidance="gravity_turn"`` meant a user-directed ENU pitch program;
      the name now belongs to the true (velocity-aligned) gravity turn, so it
      becomes ``pitch_program``.
    * ``guidance="loft"`` was Forden's ``el(t) = max(la, 90 − rate·t)``, which
      is the same trajectory as a linear pitch program with ``turn_start = 0``
      and ``turn_stop = (90 − la)/rate``; it is rewritten as those overrides.
    * ``loft_angle_deg`` was the burnout angle's old name.
    * The ``rv_*`` field family predates the rename to ``ro_*`` (reentry
      object): ``num_rvs``, ``rv_mass_kg``, ``rv_separates``, and the inline
      ``rv_beta_kg_m2`` / ``rv_shape`` / ``rv_diameter_m`` / ``rv_length_m``.
    * ``nose_ld_ratio`` / ``shroud_nose_ld_ratio`` gave nose length as a
      multiple of the stage diameter; they become absolute lengths.
    * Reentry hardware used to live on the booster, first as inline fields and
      then under an embedded ``rv`` / ``ro`` key.  Both become a nested ``ro``
      dict, which :func:`ro_from_dict` reads.
    * A design payload used to be stored in ``payload_kg`` *and* baked into
      every stage's launch mass (and, when ``ro_separates`` was false, into the
      last stage's burnout mass).  Booster files are stack-only now and the
      reentry object owns its mass, so the payload is subtracted back out.
    """
    if not isinstance(d, dict):
        raise TypeError("booster dict expected")
    d = dict(d)
    if d.get('schema') == BOOSTER_SCHEMA:
        return d
    # Sub-stages are upgraded first, exactly as the loader recursed, so a
    # legacy stage inside a legacy stack is converted on its own terms before
    # this stage's whole-chain rules (payload, loft) run over it.
    if d.get('stage2'):
        d['stage2'] = upgrade_booster_dict(d['stage2'])

    _raw_guidance = str(d.get('guidance', 'pitch_program'))
    if _raw_guidance == 'gravity_turn':
        d['guidance'] = 'pitch_program'

    if 'burnout_angle_deg' not in d and 'loft_angle_deg' in d:
        d['burnout_angle_deg'] = d['loft_angle_deg']
    d.pop('loft_angle_deg', None)

    for _new, _old in (('num_ros', 'num_rvs'), ('ro_mass_kg', 'rv_mass_kg'),
                       ('ro_separates', 'rv_separates')):
        if _new not in d and _old in d:
            d[_new] = d[_old]
        d.pop(_old, None)

    _dia = float(d.get('diameter_m', 0.0) or 0.0)
    for _len_key, _ratio_key in (('nose_length_m', 'nose_ld_ratio'),
                                 ('shroud_nose_length_m', 'shroud_nose_ld_ratio')):
        if _len_key not in d and _ratio_key in d:
            d[_len_key] = float(d.get(_ratio_key, 0.0) or 0.0) * _dia
        d.pop(_ratio_key, None)

    # The payload the file baked into its stage masses.  Read before it is
    # removed, because the inline-object conversion below falls back to it.
    _payload = float(d.get('payload_kg', 0.0) or 0.0)
    _baked = not bool(d.get('ro_separates', False))

    # Reentry hardware -> a nested 'ro' dict.
    _ro_data = d.pop('ro', None) or d.pop('rv', None)
    d.pop('rv', None)
    if _ro_data is None:
        _rb = float(d.get('ro_beta_kg_m2', d.get('rv_beta_kg_m2', 0.0)) or 0.0)
        if _rb > 0:
            # Gated on an inline ballistic coefficient: without one there is no
            # reentry vehicle described, only stray keys.
            _ro_data = dict(
                name='(migrated)',
                mass_kg=float(d.get('ro_mass_kg', 0.0) or 0.0) or _payload,
                beta_kg_m2=_rb,
                shape=str(d.get('ro_shape', d.get('rv_shape', '')) or ''),
                diameter_m=float(d.get('ro_diameter_m',
                                       d.get('rv_diameter_m', 0.0)) or 0.0),
                length_m=float(d.get('ro_length_m',
                                     d.get('rv_length_m', 0.0)) or 0.0),
                glider_enabled=bool(d.get('glider_enabled', False)),
                glider_LD=float(d.get('glider_LD', 0.0) or 0.0),
                glider_guidance=str(d.get('glider_guidance',
                                          'equilibrium_glide')),
                glider_pullup_g_max=float(d.get('glider_pullup_g_max', 10.0)),
                glider_terminal_dive=bool(d.get('glider_terminal_dive', False)),
                glider_terminal_alt_km=float(
                    d.get('glider_terminal_alt_km', 0.0) or 0.0),
            )
    for _k in ('ro_beta_kg_m2', 'rv_beta_kg_m2', 'ro_shape', 'rv_shape',
               'ro_diameter_m', 'rv_diameter_m', 'ro_length_m', 'rv_length_m',
               'glider_enabled', 'glider_LD', 'glider_guidance',
               'glider_pullup_g_max', 'glider_terminal_dive',
               'glider_terminal_alt_km'):
        d.pop(_k, None)
    if _ro_data is not None:
        d['ro'] = upgrade_ro_dict(_ro_data)

    # Stack-only masses: subtract the baked payload from the whole chain.
    if _payload > 0:
        _node = d
        while _node is not None:
            _node['mass_initial'] = float(_node['mass_initial']) - _payload
            _last = _node
            _node = _node.get('stage2')
        if _baked and float(_last.get('mass_final', 0.0)) > _payload:
            _last['mass_final'] = float(_last['mass_final']) - _payload
    d.pop('payload_kg', None)
    d.pop('ro_separates', None)

    # Forden's loft law -> the equivalent pitch-program overrides.  Applied
    # last, over the fully-converted chain, as the loader did after building it.
    if _raw_guidance == 'loft':
        _la = float(d.get('burnout_angle_deg', 45.0))
        _rate = float(d.get('loft_angle_rate_deg_s', 2.0) or 0.0)
        d['guidance'] = 'pitch_program'
        if d.get('stage_turn_start_s') is None:
            d['stage_turn_start_s'] = 0.0
        if d.get('stage_turn_stop_s') is None and _rate > 0:
            d['stage_turn_stop_s'] = round((90.0 - _la) / _rate, 1)
        if d.get('stage_burnout_angle_deg') is None:
            d['stage_burnout_angle_deg'] = _la
        _s = d.get('stage2')
        while _s is not None:
            if _s.get('guidance') == 'loft':
                _s['guidance'] = 'pitch_program'
            if _s.get('stage_burnout_angle_deg') is None:
                _s['stage_burnout_angle_deg'] = _la
            _s = _s.get('stage2')

    d['schema'] = BOOSTER_SCHEMA
    return d


def booster_from_dict(d: dict) -> BoosterParams:
    """Reconstruct a BoosterParams from a dict produced by booster_to_dict.

    The dict is passed through :func:`upgrade_booster_dict` first, so this
    function reads the CURRENT schema only: no legacy aliases or shapes are
    understood here.  A new compatibility rule goes in the upgrader.
    """
    d = upgrade_booster_dict(d)
    prop  = float(d['mass_propellant'])
    burn  = float(d['burn_time_s'])
    isp   = float(d['isp_s'])
    m0    = float(d['mass_initial'])
    stage2 = booster_from_dict(d['stage2']) if d.get('stage2') else None
    _p = BoosterParams(
        name=d['name'],
        mass_initial=m0,
        mass_propellant=prop,
        mass_final=float(d['mass_final']) if 'mass_final' in d else m0 - prop,
        diameter_m=float(d['diameter_m']),
        length_m=float(d['length_m']),
        thrust_N=round(_thrust_from_isp(isp, prop, burn)),
        burn_time_s=burn,
        coast_time_s=float(d.get('coast_time_s', 0.0)),
        isp_s=isp,
        guidance=str(d.get('guidance', 'pitch_program')),
        burnout_angle_deg=float(d.get('burnout_angle_deg', 45.0)),
        loft_angle_rate_deg_s=float(d.get('loft_angle_rate_deg_s', 2.0)),
        mach_table=list(d.get('mach_table', _FORDEN_MACH)),
        cd_table=list(d.get('cd_table', _FORDEN_CD)),
        stage2=stage2,
        payload_kg=0.0,                 # stack-only; legacy payload handled below
        body_reenters=bool(d.get('body_reenters', False)),
        bus_mass_kg=float(d.get('bus_mass_kg', 0.0)),
        num_ros=int(d.get('num_ros', 1)),
        ro_mass_kg=float(d.get('ro_mass_kg', 0.0)),
        shroud_mass_kg=float(d.get('shroud_mass_kg', 0.0)),
        shroud_jettison_alt_km=float(d.get('shroud_jettison_alt_km', 80.0)),
        shroud_length_m=float(d.get('shroud_length_m', 0.0)),
        shroud_diameter_m=float(d.get('shroud_diameter_m', 0.0)),
        nozzle_exit_area_m2=float(d.get('nozzle_exit_area_m2', 0.0)),
        n_nozzles=int(d.get('n_nozzles', 1) or 1),
        nozzle_area_each_m2=float(d.get('nozzle_area_each_m2', 0.0) or 0.0),
        solid_motor=bool(d.get('solid_motor', False)),
        grain_type=d.get('grain_type', ''),
        thrust_peak_N=float(d.get('thrust_peak_N', 0.0)),
        thrust_profile=list(d.get('thrust_profile', [])),
        conical=bool(d.get('conical', False)),
        top_diameter_m=float(d.get('top_diameter_m', 0.0)),
        has_interstage=bool(d.get('has_interstage', False)),
        interstage_length_m=float(d.get('interstage_length_m', 0.0)),
        interstage_mass_kg=float(d.get('interstage_mass_kg', 0.0)),
        interstage_jettison_s=(float(d['interstage_jettison_s'])
                               if d.get('interstage_jettison_s') is not None else None),
        nose_shape=d.get('nose_shape', ''),
        nose_length_m=float(d.get('nose_length_m', 0.0)),
        shroud_nose_shape=d.get('shroud_nose_shape', ''),
        shroud_nose_length_m=float(d.get('shroud_nose_length_m', 0.0)),
        aerospike_LD=float(d.get('aerospike_LD', 0.0)),
        aerospike_dD=float(d.get('aerospike_dD', 0.0)),
        has_fins=bool(d.get('has_fins', False)),
        n_fins=int(d.get('n_fins', 4)),
        fin_span_m=float(d.get('fin_span_m', 0.0)),
        fin_root_chord_m=float(d.get('fin_root_chord_m', 0.0)),
        fin_tip_chord_m=float(d.get('fin_tip_chord_m', 0.0)),
        fin_thickness_m=float(d.get('fin_thickness_m', 0.0)),
        fin_sweep_deg=float(d.get('fin_sweep_deg', 0.0)),
        has_grid_fins=bool(d.get('has_grid_fins', False)),
        n_grid_fins=int(d.get('n_grid_fins', 0)),
        grid_fin_width_m=float(d.get('grid_fin_width_m', 0.0)),
        grid_fin_height_m=float(d.get('grid_fin_height_m', 0.0)),
        grid_fin_chord_m=float(d.get('grid_fin_chord_m', 0.0)),
        grid_fin_web_thickness_m=float(d.get('grid_fin_web_thickness_m', 0.0)),
        grid_fin_cell_pitch_m=float(d.get('grid_fin_cell_pitch_m', 0.0)),
        grid_fin_solidity=float(d.get('grid_fin_solidity', 0.0)),
        grid_fin_edge_factor=float(d.get('grid_fin_edge_factor', 1.0)),
        grid_fin_deploy_schedule=list(d.get('grid_fin_deploy_schedule', []) or []),
        payload_diameter_m=float(d.get('payload_diameter_m', 0.0)),
        pbv_diameter_m=float(d.get('pbv_diameter_m', 0.0)),
        pbv_length_m=float(d.get('pbv_length_m', 0.0)),
        source=str(d.get('source', '')),
        notes=str(d.get('notes', '')),
        n_boosters=int(d.get('n_boosters', 0)),
        booster_thrust_n=float(d.get('booster_thrust_n', 0.0)),
        booster_burn_time_s=float(d.get('booster_burn_time_s', 0.0)),
        booster_inert_kg=float(d.get('booster_inert_kg', 0.0)),
        booster_prop_kg=float(d.get('booster_prop_kg', 0.0)),
        booster_isp_s=float(d.get('booster_isp_s', 0.0)),
        booster_nozzle_area_m2=float(d.get('booster_nozzle_area_m2', 0.0)),
        booster_diam_m=float(d.get('booster_diam_m', 0.0)),
        booster_length_m=float(d.get('booster_length_m', 0.0)),
        booster_cd=float(d.get('booster_cd', 0.20)),
        booster_core_delay_s=float(d.get('booster_core_delay_s', 0.0)),
        booster_jettison_s=float(d.get('booster_jettison_s', 0.0)),
        stage_turn_start_s=(float(d['stage_turn_start_s'])
                            if d.get('stage_turn_start_s') is not None else None),
        stage_turn_stop_s=(float(d['stage_turn_stop_s'])
                           if d.get('stage_turn_stop_s') is not None else None),
        stage_burnout_angle_deg=(float(d['stage_burnout_angle_deg'])
                                 if d.get('stage_burnout_angle_deg') is not None else None),
        stage_cutoff_s=(float(d['stage_cutoff_s'])
                        if d.get('stage_cutoff_s') is not None else None),
        stage_yaw_start_s=(float(d['stage_yaw_start_s'])
                           if d.get('stage_yaw_start_s') is not None else None),
        stage_yaw_stop_s=(float(d['stage_yaw_stop_s'])
                          if d.get('stage_yaw_stop_s') is not None else None),
        stage_yaw_final_az_deg=(float(d['stage_yaw_final_az_deg'])
                                if d.get('stage_yaw_final_az_deg') is not None else None),
    )
    # The upgrader guarantees a nested 'ro' dict (or none): reentry hardware
    # never lives on the booster in the current schema.
    if d.get('ro') is not None:
        _p.ro = ro_from_dict(d['ro'])
    return _p  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Physics helper functions
# ---------------------------------------------------------------------------

def _hoerner_cp_impact(mach: float) -> float:
    """Hypersonic stagnation (impact) pressure coefficient C_p• of a blunt face.

    Hoerner, *Fluid-Dynamic Drag* (1965), Ch. XVIII eq. (41):

        C_p• = 1.84 − 0.76 / M²          (M ≳ 3; → 1.84 as M → ∞)

    Below M ≈ 3 the hypersonic form is not valid; the value is floored at the
    incompressible bluff-body level (~1.2) so callers get a sane number.
    """
    if mach is None or mach < 3.0:
        return 1.2
    return 1.84 - 0.76 / (mach * mach)


# ---------------------------------------------------------------------------
# Blunted-cone hypersonic Cd — the "Estimate Object β" physics
# ---------------------------------------------------------------------------
# Newtonian blunted-cone PRESSURE Cd is a closed form (see below), derived
# from the Newtonian impact expressions in Wells & Armstrong, NASA TR R-127
# (1962).  It replaced an earlier unattributed "Ref (4) Ch. 5" chart table
# that under-counted blunt-nose drag.
def cd_blunted_cone_newtonian(theta_deg: float, eps: float) -> float:
    """Newtonian PRESSURE Cd (base-area ref) of a spherically-blunted cone at
    zero angle of attack — the EXACT closed form, not a chart:

        C_D = 2·sin²θ + ε²·cos⁴θ                 (ε = r_N / r_b)

    theta_deg : cone half-angle (degrees)
    eps       : nose-radius ratio r_N/r_b (0 = sharp tip, 1 = r_N = r_b)

    It is the superposition of the spherical nose cap and the truncated cone
    frustum it caps, each base-area referenced:
        cap      drag/q = π·r_N²·(1 − sin⁴θ)   →   ε²·(1 − sin⁴θ)
        frustum  2·sin²θ·(1 − ε²·cos²θ)          (tangency at r = r_N·cosθ)
    which sum, exactly, to 2·sin²θ + ε²·cos⁴θ.  Reductions: ε=0 gives the sharp
    cone 2·sin²θ; the ε²·cos⁴θ term is the blunt-nose pressure the sharp
    formula omits (dominant for a slender, blunt nose).

    Source: the zero-AoA reduction of the developed Newtonian impact
    expressions for complete conic and spheric bodies in Wells & Armstrong,
    NASA TR R-127 (1962); also Anderson, *Hypersonic and High-Temperature Gas
    Dynamics*.  This REPLACES an earlier unattributed "Ref (4) Ch. 5"
    interpolation chart that materially UNDER-counted blunt-nose drag (e.g.
    θ=10°, ε=0.6: chart 0.08 vs. the correct 0.40 — a 5× error).

    Inviscid pressure term ONLY; on a slender cone friction dominates the axial
    drag — use cd_cone_hypersonic() for a total-Cd estimate.
    """
    import math
    th = math.radians(max(1.0, min(float(theta_deg), 89.0)))
    ep = max(0.0, min(float(eps), 1.0))
    return 2.0 * math.sin(th) ** 2 + ep * ep * math.cos(th) ** 4


# Screening constants for the viscous/base completion of the cone Cd.
# Cf: turbulent hypersonic flat-plate/cone class value.  Flight-Reynolds
# slender cones run Cf ≈ 0.0008–0.0015 (compressibility-reduced turbulent);
# 0.0012 is the mid-band SCREENING value — an inference, not a cited
# measurement, and the honest uncertainty on it is ~±30%.
CONE_CF_TURBULENT = 0.0012
_GAMMA_AIR = 1.4


def cd_cone_hypersonic(theta_deg: float, eps: float, mach: float = 10.0,
                       cf: float = CONE_CF_TURBULENT,
                       wing_area_ratio: float = 0.0) -> dict:
    """Total zero-AoA hypersonic axial Cd build-up for a blunted cone.

    Returns {'pressure', 'friction', 'base', 'wing', 'total', 'swet_ratio'} —
    all Cd components referenced to the base area, so β = m / (total · π·d²/4).

    `wing_area_ratio` = S_w/A_base (default 0).  When > 0 the estimate accounts
    for the wing's zero-lift drag — the ADVISORY half of the wing decoupling
    (Level 2): a winged vehicle's β is LOWER (draggier) than the bare cone, so
    the suggested value drops.  Screening: wing zero-lift drag is friction-
    dominated for thin surfaces, Cd_wing ≈ Cf · 2·(S_w/A_base) (both faces
    wetted); wing wave drag needs thickness/sweep the geometry alone can't give
    and is omitted (labeled, conservative-low on the wing term).

      pressure : Newtonian closed form 2·sin²θ + ε²·cos⁴θ
                 (cd_blunted_cone_newtonian; Wells & Armstrong NASA TR R-127)
      friction : Cf · S_wet/A_base.  Exact frustum geometry: the conical
                 surface runs from the sphere-cone tangency radius
                 r_t = ε·r_b·cosθ to r_b, so
                 S_wet/A_base = (1 − ε²cos²θ) / sinθ.  The spherical-cap
                 wetted area is omitted (its drag sits in the pressure
                 table).  Cf is a labeled screening constant (see
                 CONE_CF_TURBULENT).
      base     : 2/(γ·M²) — the p_base → 0 hypersonic limit (exact limit
                 formula; the wake cannot push on the base harder than
                 removing ambient pressure entirely).

    WHY THIS EXISTS: the pure-Newtonian estimator under-counts a slender
    cone's drag by ~4× (at θ = 5.25°, pressure Cd ≈ 0.017 while friction
    alone is ≈ 0.013 and base ≈ 0.014 at M 10), which inflated estimated β
    to ~10⁵ kg/m² — the "anomalous ballistic coefficient" fault.  For blunt
    RVs (θ ≥ 20°) pressure dominates and the added terms are a 2–4%
    perturbation, so ballistic estimates are essentially unchanged.
    """
    import math
    th  = math.radians(max(1.0, min(float(theta_deg), 89.0)))
    eps = max(0.0, min(float(eps), 1.0))
    m   = max(float(mach), 3.0)              # hypersonic form; floor as Hoerner
    pressure = cd_blunted_cone_newtonian(theta_deg, eps)
    swet = (1.0 - (eps * math.cos(th)) ** 2) / math.sin(th)
    friction = float(cf) * swet
    base = 2.0 / (_GAMMA_AIR * m * m)
    wing = float(cf) * 2.0 * max(0.0, float(wing_area_ratio))   # both faces
    return dict(pressure=float(pressure), friction=float(friction),
                base=float(base), wing=wing,
                total=float(pressure + friction + base + wing),
                swet_ratio=float(swet))


def cd_biconic_hypersonic(theta1_deg: float, theta2_deg: float,
                          break_ratio: float, eps: float, mach: float = 10.0,
                          cf: float = CONE_CF_TURBULENT,
                          wing_area_ratio: float = 0.0) -> dict:
    """Total zero-AoA hypersonic axial Cd build-up for a BICONIC (two-cone) body.

    A biconic is a forward cone (half-angle theta1, nose-blunted) meeting an aft
    frustum (half-angle theta2) at a break diameter.  Same physics core as
    cd_cone_hypersonic, but the pressure and friction terms are summed over BOTH
    segments — a single cone cannot represent it (a steep fore-cone on a shallow
    aft-frustum has genuinely different pressure and wetted area than either
    cone alone).

    Parameters (all ratios to the BASE radius r_b = diameter/2):
      theta1_deg   : forward-cone half-angle
      theta2_deg   : aft-frustum half-angle
      break_ratio  : r_break / r_b  (diameter at the cone-cone junction / base)
      eps          : r_nose / r_b   (nose-radius ratio, as for cd_cone_hypersonic)

    Newtonian pressure (base-area ref):
      fore : cd_blunted_cone_newtonian(theta1, r_nose/r_break) · break_ratio²
             (the blunted fore-cone on its OWN base π·r_break², scaled to A_b)
      aft  : 2·sin²theta2 · (1 − break_ratio²)   (frustum pressure on the annulus)
    Friction : Cf · (S_wet,fore + S_wet,aft)/A_b, with
      S_wet,fore/A_b = (break_ratio² − (eps·cos theta1)²) / sin theta1
      S_wet,aft /A_b = (1 − break_ratio²) / sin theta2
    Base : 2/(γM²).  Wing : Cf·2·(S_w/A_b), as in cd_cone_hypersonic.

    Exact single-cone reduction (regression anchor): break_ratio → 1 collapses
    the aft annulus to zero and returns the cd_cone_hypersonic(theta1, eps)
    value; and for a sharp cone (eps = 0) with theta2 = theta1 the two segments
    sum to the single cone for ANY break_ratio.

    Returns {'pressure','friction','base','wing','total','pressure_fore',
    'pressure_aft','swet_fore','swet_aft'} — all base-area-referenced.
    """
    import math
    th1 = math.radians(max(1.0, min(float(theta1_deg), 89.0)))
    th2 = math.radians(max(1.0, min(float(theta2_deg), 89.0)))
    br  = max(1e-3, min(float(break_ratio), 1.0))
    eps = max(0.0, min(float(eps), 1.0))
    m   = max(float(mach), 3.0)

    # Pressure: blunted fore-cone (on its own base, scaled to A_b) + aft annulus
    eps_fore = min(eps / br, 1.0)                       # r_nose / r_break
    pressure_fore = cd_blunted_cone_newtonian(theta1_deg, eps_fore) * br * br
    pressure_aft  = 2.0 * math.sin(th2) ** 2 * (1.0 - br * br)
    pressure = pressure_fore + pressure_aft

    # Friction: exact frustum wetted ratios for both segments
    r_t = eps * math.cos(th1)                           # fore tangency radius / r_b
    swet_fore = max(0.0, (br * br - r_t * r_t)) / math.sin(th1)
    swet_aft  = (1.0 - br * br) / math.sin(th2)
    friction  = float(cf) * (swet_fore + swet_aft)

    base = 2.0 / (_GAMMA_AIR * m * m)
    wing = float(cf) * 2.0 * max(0.0, float(wing_area_ratio))
    return dict(pressure=float(pressure), friction=float(friction),
                base=float(base), wing=wing,
                total=float(pressure + friction + base + wing),
                pressure_fore=float(pressure_fore), pressure_aft=float(pressure_aft),
                swet_fore=float(swet_fore), swet_aft=float(swet_aft))


# ===========================================================================
# Lifting-body angle-of-attack sweep (Phase 2a estimator core)
# ---------------------------------------------------------------------------
# Modified-Newtonian aerodynamics (Cp = K·cos²η) for LIFTING bodies at
# incidence, giving C_L(α)/C_D(α) → (L/D)max and the trim-consistent β — the
# machinery the flat, zero-AoA cone/biconic estimators above lack.  See
# PHASE2_LIFTING_BODY_PLAN.md.  Primary sources: AEDC-TDR-64-25 (closed-form
# Newtonian, K-factor), Corda & Anderson 1988 (Eckert Cf), Fetterman NASA
# TN D-2942/2956 (measured half-cone anchors), Candler & Leyva 2022 (CFD).
#
# Discipline: physics stays untouched in the trajectory — β and L/D are the
# carriers; this is where the geometry content lives.  Every returned row
# STATES the conditions (M, Re, laminar/turbulent, base on/off, A_ref, K) it
# was computed at.  Tests are identities (sharp-cone reduction, flat plate,
# K-linearity) and measured anchors — never fits.
# ===========================================================================

# K in Cp = K·cos²η (AEDC-TDR-64-25 §1).  K=2 is classic Newtonian (slender,
# attached shock — the default, matching the zero-AoA estimators above);
# K=γ+1 is Love's flat-plate value; K=(γ+3)/(γ+1)≈1.83 is Lees' blunt-body
# (detached-shock) value.
NEWTON_K_SLENDER = 2.0
NEWTON_K_FLATPLATE = _GAMMA_AIR + 1.0                 # ≈ 2.4
NEWTON_K_BLUNT = (_GAMMA_AIR + 3.0) / (_GAMMA_AIR + 1.0)   # ≈ 1.833


def _newton_sector_I0_I1(a, b, lo, hi):
    """Definite integrals of (a+b·sinφ)² and (a+b·sinφ)²·sinφ over [lo,hi].

    Elementary antiderivatives (the plan's `∫(a−b sinφ)²·{1,sinφ} dφ`):
        F0 = a²φ − 2ab cosφ + b²(φ/2 − sin2φ/4)
        F1 = −a² cosφ + 2ab(φ/2 − sin2φ/4) + b²(−cosφ + cos³φ/3)
    """
    import math
    def F0(x):
        return (a * a * x - 2.0 * a * b * math.cos(x)
                + b * b * (x / 2.0 - math.sin(2.0 * x) / 4.0))
    def F1(x):
        return (-a * a * math.cos(x)
                + 2.0 * a * b * (x / 2.0 - math.sin(2.0 * x) / 4.0)
                + b * b * (-math.cos(x) + math.cos(x) ** 3 / 3.0))
    return F0(hi) - F0(lo), F1(hi) - F1(lo)


def _newton_lit_subintervals(a, b, lo, hi):
    """Sub-intervals of [lo,hi] where the surface faces the flow (cos η =
    a + b·sinφ ≥ 0); the rest is shadowed (Cp = 0).  Splits at the roots of
    a + b·sinφ = 0 and keeps the lit pieces (Newtonian shadow rule)."""
    import math
    pts = [lo, hi]
    if abs(b) > 1e-12:
        s = -a / b
        if -1.0 <= s <= 1.0:
            base = math.asin(max(-1.0, min(1.0, s)))
            for r in (base, math.pi - base):
                k0 = math.floor((lo - r) / (2.0 * math.pi))
                for k in (k0, k0 + 1, k0 + 2):
                    phi = r + 2.0 * math.pi * k
                    if lo < phi < hi:
                        pts.append(phi)
    pts = sorted(set(pts))
    out = []
    for l, h in zip(pts[:-1], pts[1:]):
        if a + b * math.sin(0.5 * (l + h)) >= 0.0:
            out.append((l, h))
    return out


def cone_sector_newtonian(theta_deg, alpha_deg, phi_lo, phi_hi,
                          K=NEWTON_K_SLENDER):
    """Newtonian pressure (C_N, C_A) of the azimuthal SECTOR [phi_lo, phi_hi]
    of a SHARP cone's lateral surface at angle of attack, base-area referenced.

    Cone half-angle θ, apex forward, axis +x; azimuth φ measured so φ = +π/2
    is the −z (windward-at-positive-α) ray.  Local inclination (AEDC Eq. 127,
    β=0):  cos η = cosα·sinθ + sinα·cosθ·sinφ.  Integrating Cp = K·cos²η over
    the lit part of the sector (elemental area ρ/sinθ dρ dφ), base-area
    referenced (S = π·r_b²):

        C_A = (K / 2π) · ∫ cos²η dφ
        C_N = (K·cosθ / 2π·sinθ) · ∫ cos²η·sinφ dφ

    Full sector [−π/2, 3π/2] at α = 0 gives C_A = K·sin²θ (= the sharp-cone
    2·sin²θ at K=2) and C_N = 0 — the identity anchors.  A half-shell (e.g.
    [π/2, 3π/2]) at α > 0 differs from its opposite half: windward ≠ leeward.
    """
    import math
    th = math.radians(max(0.5, min(float(theta_deg), 89.5)))
    al = math.radians(float(alpha_deg))
    a = math.cos(al) * math.sin(th)
    b = math.sin(al) * math.cos(th)
    I0 = I1 = 0.0
    for l, h in _newton_lit_subintervals(a, b, float(phi_lo), float(phi_hi)):
        d0, d1 = _newton_sector_I0_I1(a, b, l, h)
        I0 += d0
        I1 += d1
    C_A = K / (2.0 * math.pi) * I0
    C_N = K * math.cos(th) / (2.0 * math.pi * math.sin(th)) * I1
    return dict(C_N=float(C_N), C_A=float(C_A))


def flat_plate_newtonian(alpha_deg, K=NEWTON_K_SLENDER):
    """Newtonian pressure on ONE face of a flat plate at incidence, per unit
    of the plate's own planform area.  Windward (α>0 for the underside):
    Cp = K·sin²α acting normal to the plate → C_N = K·sin²α, C_A = 0 (a thin
    plate has no axial projection).  Leeward (α≤0): shadowed, both zero."""
    import math
    al = math.radians(float(alpha_deg))
    if al <= 0.0:
        return dict(C_N=0.0, C_A=0.0)
    cp = K * math.sin(al) ** 2
    return dict(C_N=float(cp), C_A=0.0)


def cf_reference_temperature(mach, reynolds_length, wall_temp_ratio=1.0,
                             turbulent=True, recovery=0.89):
    """Flat-plate skin-friction coefficient Cf at the Eckert reference
    temperature (Corda & Anderson 1988; validated to ~10% of an integral
    boundary-layer method even at high hypersonic Mach).

    A PRE-FILL helper — the estimator still accepts a Cf directly (continuity
    with the shipped cone estimator).  Incompressible Cf (Blasius laminar /
    Schlichting turbulent on Re_L) is scaled by (ρ*μ*)/(ρ_e μ_e) evaluated at
    Eckert's reference temperature T*/T_e = 1 + 0.032·M² + 0.58·(T_w/T_e − 1),
    with ρ ∝ 1/T (constant p) and μ ∝ T^0.7 (power-law).  Returns the
    length-averaged Cf; wall_temp_ratio = T_w/T_e (1.0 = a stated cold-ish
    wall — the assumption is explicit, never implicit)."""
    import math
    M = max(float(mach), 0.0)
    ReL = max(float(reynolds_length), 1.0)
    r = float(recovery)
    Tw = max(1e-3, float(wall_temp_ratio))
    # Eckert reference-temperature ratio T*/T_e (Meador-Smart / Eckert form).
    Tstar = 1.0 + 0.032 * M * M + 0.58 * (Tw - 1.0) + 0.10 * r * 0.2 * M * M
    Tstar = max(Tstar, 1.0)
    rho_ratio = 1.0 / Tstar                 # ρ*/ρ_e at constant pressure
    mu_ratio = Tstar ** 0.7                 # μ*/μ_e, power-law viscosity
    if turbulent:
        cf_inc = 0.0592 / ReL ** 0.2        # Schlichting turbulent flat plate
        cstar = (rho_ratio * mu_ratio) ** 0.2
    else:
        cf_inc = 1.328 / math.sqrt(ReL)     # Blasius laminar flat plate
        cstar = math.sqrt(rho_ratio * mu_ratio)
    return float(cf_inc * cstar)


def _half_cone_coeffs(theta_deg, alpha_deg, K, cf, base_drag, mach,
                      wing_ratio=0.0):
    """Base-area-referenced (C_L, C_D, C_N, C_A) of a flat-side-DOWN half-cone
    at one α.  Composition (PHASE2_LIFTING_BODY_PLAN §2.1):

      flat underside  : a delta plate, windward for α>0 — Cp = K·sin²α on its
                        own planform (area/base = 1/(π·tanθ)), pushing UP;
      upper half-shell: the leeward semicircle φ∈[π,2π] of the cone lateral
                        surface (cone_sector_newtonian), mostly shadowed at α>0;
      friction        : Cf over the true wetted ratio (half lateral + flat),
                        α-independent (Lobanovskii), drag-aligned;
      base            : 2/(γM²) on the half-disc base (area/base = ½), optional.

    Flat side down is the default (Fetterman TN D-2942: flat-bottom superior).

    Phase 2b — WING-BODY COMPOSITE (`wing_ratio` = exposed wing planform /
    base area, both panels): the delta wing is mounted flush with the flat
    underside, so the whole lower surface (body flat + wing panels) is ONE
    coplanar plate — its Cp is K·sin²α regardless of planform shape, so the
    wing enters through AREA alone (which is where planform sweep enters:
    a more-swept delta of the same root has less area).  At α < 0 the wing
    UPPER faces are lit and push down; friction wets both wing faces.
    Non-interference superposition (Fetterman: interference dissipates by
    ~M 11 and flat-bottom wins in the glide regime — the defensible choice).
    """
    import math
    th = math.radians(max(0.5, min(float(theta_deg), 89.5)))
    al = math.radians(float(alpha_deg))
    shell = cone_sector_newtonian(theta_deg, alpha_deg, math.pi, 2.0 * math.pi, K)
    flat = flat_plate_newtonian(alpha_deg, K)
    flat_ratio = 1.0 / (math.pi * math.tan(th))          # S_flat / S_base
    wr = max(0.0, float(wing_ratio))
    lower_ratio = flat_ratio + wr                        # coplanar lower plate
    C_N = shell['C_N'] + flat['C_N'] * lower_ratio
    C_A = shell['C_A'] + flat['C_A'] * lower_ratio
    if wr > 0.0:
        up = flat_plate_newtonian(-alpha_deg, K)         # wing tops, lit α<0
        C_N -= up['C_N'] * wr                            # pushes DOWN
    C_L = C_N * math.cos(al) - C_A * math.sin(al)
    C_D = C_N * math.sin(al) + C_A * math.cos(al)         # pressure only so far
    swet_ratio = (1.0 / (2.0 * math.sin(th)) + flat_ratio
                  + 2.0 * wr)                            # + wing, both faces
    C_D += float(cf) * swet_ratio                         # friction (α-indep.)
    if base_drag:
        C_D += (2.0 / (_GAMMA_AIR * max(float(mach), 3.0) ** 2)) * 0.5
    return dict(C_L=float(C_L), C_D=float(C_D), C_N=float(C_N), C_A=float(C_A))


def _bor_coeffs(theta1_deg, alpha_deg, K, cf, base_drag, mach,
                eps=0.0, theta2_deg=None, break_ratio=1.0):
    """Base-area-referenced (C_L, C_D, C_N, C_A) of a body of revolution —
    (blunted) cone or biconic — at incidence (Phase 2b: the α-sweep upgrade
    of the zero-AoA cd_cone_hypersonic / cd_biconic_hypersonic build-ups).

    Superposition with rescaling (Grant & Braun 2010 Eq. 23), each component
    on the SAME full-range sector integral machinery as the lifting forms:

      fore-cone lateral : cone_sector_newtonian at θ1 over the full φ range,
                          restricted to its frustum (tangency ρ_t = ε_f·cosθ1
                          to the break) by self-similar area scaling — the
                          lit-φ set is ρ-independent, so the sub-cone
                          subtraction is exact at every α;
      aft frustum       : the θ2 virtual cone scaled by (1 − br²);
      nose cap          : spherical segment, treated as AXIAL and
                          α-INDEPENDENT at screening level (stated in the
                          sweep conditions; second-order for small caps):
                          C_A,cap = (K/2)·ε²·(1 − sin⁴θ1) — the R-127 closed
                          form, so the α = 0 pressure sums EXACTLY to
                          cd_blunted_cone_newtonian / the biconic build-up;
      friction          : Cf × exact frustum wetted ratios (α-independent);
      base              : 2/(γM²), optional.

    A plain cone is the theta2_deg=None / break_ratio=1 special case.
    """
    import math
    th1 = math.radians(max(1.0, min(float(theta1_deg), 89.0)))
    br = max(1e-3, min(float(break_ratio if theta2_deg is not None else 1.0), 1.0))
    ep = max(0.0, min(float(eps), 1.0))
    al = math.radians(float(alpha_deg))
    eps_fore = min(ep / br, 1.0)                        # r_nose / r_break
    rho_t = eps_fore * math.cos(th1)                    # tangency / r_break

    fore = cone_sector_newtonian(theta1_deg, alpha_deg,
                                 -0.5 * math.pi, 1.5 * math.pi, K)
    C_N = fore['C_N'] * (1.0 - rho_t * rho_t) * br * br
    C_A = fore['C_A'] * (1.0 - rho_t * rho_t) * br * br
    swet = max(0.0, (br * br - (ep * math.cos(th1)) ** 2)) / math.sin(th1)
    if theta2_deg is not None and br < 1.0:
        th2 = math.radians(max(1.0, min(float(theta2_deg), 89.0)))
        aft = cone_sector_newtonian(theta2_deg, alpha_deg,
                                    -0.5 * math.pi, 1.5 * math.pi, K)
        C_N += aft['C_N'] * (1.0 - br * br)
        C_A += aft['C_A'] * (1.0 - br * br)
        swet += (1.0 - br * br) / math.sin(th2)
    if ep > 0.0:
        C_A += 0.5 * K * ep * ep * (1.0 - math.sin(th1) ** 4)   # cap, axial
    C_L = C_N * math.cos(al) - C_A * math.sin(al)
    C_D = C_N * math.sin(al) + C_A * math.cos(al)
    C_D += float(cf) * swet
    if base_drag:
        C_D += 2.0 / (_GAMMA_AIR * max(float(mach), 3.0) ** 2)
    return dict(C_L=float(C_L), C_D=float(C_D), C_N=float(C_N), C_A=float(C_A))


def _v_sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _v_dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _planar_face_force(verts, v_hat, K, out_hint):
    """(force-per-q vector, true area) for one flat triangular face under
    modified-Newtonian flow.  The outward normal is the face normal flipped to
    agree with `out_hint` (a direction known a priori to point outward for this
    face — robust where a global interior point would misfire on thin/near-
    degenerate faces).  Windward when cos η = −V̂·n̂ > 0 (else shadowed, Cp = 0,
    but the area still counts toward wetted area).  Pressure pushes along −n̂."""
    import math
    v0, v1, v2 = verts
    n = _v_cross(_v_sub(v1, v0), _v_sub(v2, v0))
    mag = math.sqrt(_v_dot(n, n))
    if mag < 1e-15:
        return (0.0, 0.0, 0.0), 0.0
    area = 0.5 * mag
    nhat = (n[0] / mag, n[1] / mag, n[2] / mag)
    if _v_dot(nhat, out_hint) < 0.0:                    # orient outward
        nhat = (-nhat[0], -nhat[1], -nhat[2])
    cos_eta = -_v_dot(v_hat, nhat)
    if cos_eta <= 0.0:
        return (0.0, 0.0, 0.0), area                    # shadowed
    cp = K * cos_eta * cos_eta
    return (-cp * area * nhat[0], -cp * area * nhat[1], -cp * area * nhat[2]), area


def _swept_cylinder_force(axis_hat, radius, seg_length, v_hat, K):
    """Force-per-q vector of a SWEPT circular-cylinder leading edge under
    Newtonian flow (AEDC-TDR-64-25 §2.1.3 / the independence principle): only
    the freestream component NORMAL to the cylinder axis carries pressure.
    With crossflow fraction w = |V̂ − (V̂·ê)ê|, integrating Cp = K·(w·cosφ)²
    over the lit half gives force = (4/3)·K·w²·r·ℓ per q, along the crossflow
    direction n̂ — so the drag contribution scales as w³ = cos³(effective
    sweep): more sweep, less leading-edge drag (the Fetterman trend the sharp
    facets cannot express)."""
    import math
    d = _v_dot(v_hat, axis_hat)
    vn = (v_hat[0] - d * axis_hat[0], v_hat[1] - d * axis_hat[1],
          v_hat[2] - d * axis_hat[2])
    w2 = _v_dot(vn, vn)
    if w2 < 1e-15:
        return (0.0, 0.0, 0.0)
    mag = (4.0 / 3.0) * K * w2 * float(radius) * float(seg_length)
    w = math.sqrt(w2)
    return (mag * vn[0] / w, mag * vn[1] / w, mag * vn[2] / w)


def _wedge_coeffs(length, depth, span, alpha_deg, K, cf, base_drag, mach,
                  s_ref, r_le=0.0):
    """Planform-referenced (C_L, C_D) of a sharp-LE flat-bottom delta wedge at
    one α (PHASE2_LIFTING_BODY_PLAN §2.1).  Geometry: nose at origin, +x aft,
    +z up; flat bottom in z=0 (delta, span `span`, root `length`); a centreline
    ridge rising to `depth` at the base; two top facets ridge→leading-edge; a
    base triangle (always leeward → base-drag term only).

    Faces are built from vertices with an explicit outward normal + Newtonian
    shadow rule — NOT AEDC's rectangular-planform formulas, which don't apply
    to a delta.  Verified against both the flat-plate identity (depth→0) and
    AEDC Eq. 72's swept-wedge upper-surface Cp (see tests).  Friction (Eckert
    Cf over true wetted area, α-independent) and base drag are drag-aligned."""
    import math
    L = max(1e-6, float(length)); t = max(0.0, float(depth))
    b = max(1e-6, float(span))
    al = math.radians(float(alpha_deg))
    v_hat = (math.cos(al), 0.0, math.sin(al))            # freestream direction
    l_hat = (-math.sin(al), 0.0, math.cos(al))           # lift direction
    nose = (0.0, 0.0, 0.0); ridge = (L, 0.0, t)
    rt = (L, 0.5 * b, 0.0); lt = (L, -0.5 * b, 0.0)
    # (vertices, outward-hint): bottom faces down, top facets up, base aft.
    faces = [((nose, rt, lt), (0.0, 0.0, -1.0)),        # flat bottom
             ((nose, ridge, rt), (0.0, 0.0, 1.0)),      # right top facet
             ((nose, lt, ridge), (0.0, 0.0, 1.0)),      # left top facet
             ((rt, ridge, lt), (1.0, 0.0, 0.0))]        # base (always leeward)
    F = [0.0, 0.0, 0.0]; wetted = 0.0; base_area = 0.0
    for i, (verts, hint) in enumerate(faces):
        f, area = _planar_face_force(verts, v_hat, K, hint)
        F[0] += f[0]; F[1] += f[1]; F[2] += f[2]
        if i == 3:
            base_area = area
        else:
            wetted += area
    # Phase 2b: swept-cylinder leading edges (r_le = 0 → sharp, term vanishes
    # exactly — continuity).  Superposed on the sharp facets (the facet-area
    # overlap is second-order in r_le, stated in the sweep conditions).
    if r_le and float(r_le) > 0.0:
        ell = math.sqrt(L * L + 0.25 * b * b)            # one LE's true length
        for sign in (1.0, -1.0):
            e = (L / ell, sign * 0.5 * b / ell, 0.0)
            f = _swept_cylinder_force(e, float(r_le), ell, v_hat, K)
            F[0] += f[0]; F[1] += f[1]; F[2] += f[2]
    drag = _v_dot(F, v_hat) / s_ref
    lift = _v_dot(F, l_hat) / s_ref
    drag += float(cf) * wetted / s_ref                   # friction, drag-aligned
    if base_drag:
        drag += (2.0 / (_GAMMA_AIR * max(float(mach), 3.0) ** 2)) \
            * (base_area / s_ref)
    return dict(C_L=float(lift), C_D=float(drag), C_N=0.0, C_A=0.0)


def wedge_planform_area(length, span):
    """Planform (reference) area of the flat-bottom delta wedge: ½·span·root."""
    return 0.5 * float(span) * float(length)


# forms whose sweep is implemented (2a: lifting forms; 2b: bodies of
# revolution on the same sector machinery).
_LIFTING_SWEEP_FORMS = ("half_cone", "wedge", "cone", "biconic")


def lifting_body_sweep(form, theta_deg=None, mach=10.0, cf=None,
                       reynolds_length=None, wall_temp_ratio=1.0,
                       turbulent=True, K=NEWTON_K_SLENDER, base_drag=True,
                       alpha_min_deg=-10.0, alpha_max_deg=25.0, n_alpha=71,
                       mass_kg=None, a_ref_m2=None,
                       length_m=None, depth_m=None, span_m=None,
                       wing_exposed_m2=0.0, r_le_m=0.0,
                       eps=0.0, theta2_deg=None, break_ratio=1.0):
    """Angle-of-attack sweep for a lifting body: C_L(α), C_D(α), L/D(α), and a
    single CONSISTENT trim row (α*, C_L*, C_D*, (L/D)max, β at α=0 and α*, and
    the camber offset C_L0 = C_L at min C_D) — never a peak L/D detached from
    the α that produces it (the Tracy & Wright error, per Candler & Leyva).

    Half-cone coefficients are BASE-AREA referenced (pass a_ref_m2 = π·r_b²
    for β); wedge coefficients are PLANFORM referenced (A_ref defaults to
    ½·span·length).  Cf is either given directly or pre-filled from (mach,
    reynolds_length, wall_temp_ratio, turbulent) via the Eckert helper; Cf = 0
    (no Re) gives the inviscid ceiling (anchor use only).  β columns are filled
    only when mass_kg and an A_ref (given or, for the wedge, the planform
    default) are available.

    Returns dict(conditions=…, alpha=[…rows…], trim=…).  Every row and the
    trim summary carry the evaluation conditions — Fetterman: L/D is meaningful
    only at a stated Mach, Reynolds number, and boundary-layer state.
    """
    import math
    if form not in _LIFTING_SWEEP_FORMS:
        raise ValueError(f"lifting_body_sweep: form {form!r} not implemented "
                         f"(have {_LIFTING_SWEEP_FORMS})")
    if form in ("half_cone", "cone", "biconic") and theta_deg is None:
        raise ValueError(f"{form} sweep needs theta_deg")
    if form == "biconic" and theta2_deg is None:
        raise ValueError("biconic sweep needs theta2_deg (and break_ratio)")
    if form == "wedge" and not (length_m and span_m):
        raise ValueError("wedge sweep needs length_m and span_m (span REQUIRED)")
    if cf is None:
        cf = (cf_reference_temperature(mach, reynolds_length, wall_temp_ratio,
                                       turbulent)
              if reynolds_length else 0.0)

    # Reference area: base area (caller-supplied) for the half-cone and the
    # bodies of revolution; planform (derived, stated) for the wedge — the
    # pull limit q·C_L,max·A_ref/m is not invariant to the choice, so A_ref is
    # never implicit.
    if form == "wedge":
        s_ref = float(a_ref_m2) if a_ref_m2 else wedge_planform_area(length_m, span_m)
        eps_deg = math.degrees(math.atan2(float(depth_m or 0.0), float(length_m)))
        sweep_deg = math.degrees(math.atan2(2.0 * float(length_m), float(span_m)))
    else:
        s_ref = a_ref_m2
        eps_deg = sweep_deg = None
    beta_ref = s_ref if (form == "wedge") else a_ref_m2

    # Wing-body composite (half-cone + planform, Phase 2b): the wing enters
    # as exposed-planform / base-area — needs a base area to ratio against.
    wing_ratio = 0.0
    if form == "half_cone" and wing_exposed_m2 and float(wing_exposed_m2) > 0.0:
        if not a_ref_m2:
            raise ValueError("winged half_cone sweep needs a_ref_m2 (base "
                             "area) to reference the wing planform")
        wing_ratio = float(wing_exposed_m2) / float(a_ref_m2)

    def _coeffs(a):
        if form == "wedge":
            return _wedge_coeffs(length_m, depth_m or 0.0, span_m, a, K, cf,
                                 base_drag, mach, s_ref, r_le=r_le_m)
        if form == "half_cone":
            return _half_cone_coeffs(theta_deg, a, K, cf, base_drag, mach,
                                     wing_ratio=wing_ratio)
        return _bor_coeffs(theta_deg, a, K, cf, base_drag, mach, eps=eps,
                           theta2_deg=(theta2_deg if form == "biconic" else None),
                           break_ratio=(break_ratio if form == "biconic" else 1.0))

    conditions = dict(form=form, theta_deg=theta_deg, mach=float(mach),
                      cf=float(cf), reynolds_length=reynolds_length,
                      wall_temp_ratio=float(wall_temp_ratio),
                      turbulent=bool(turbulent), K=float(K),
                      base_drag=bool(base_drag), a_ref_m2=beta_ref,
                      a_ref_kind=("planform" if form == "wedge" else "base"),
                      ridge_angle_deg=eps_deg, sweep_deg=sweep_deg,
                      inviscid=(float(cf) == 0.0),
                      wing_ratio=wing_ratio, r_le_m=float(r_le_m or 0.0),
                      eps=float(eps or 0.0),
                      theta2_deg=(theta2_deg if form == "biconic" else None),
                      break_ratio=(float(break_ratio) if form == "biconic"
                                   else None),
                      cap_axial_alpha_independent=(float(eps or 0.0) > 0.0))
    n = max(3, int(n_alpha))
    rows = []
    for i in range(n):
        a = alpha_min_deg + (alpha_max_deg - alpha_min_deg) * i / (n - 1)
        c = _coeffs(a)
        ld = (c['C_L'] / c['C_D']) if c['C_D'] > 1e-9 else float('-inf')
        row = dict(alpha_deg=float(a), C_L=c['C_L'], C_D=c['C_D'], L_D=float(ld))
        if mass_kg and beta_ref and c['C_D'] > 1e-9:
            row['beta'] = float(mass_kg) / (c['C_D'] * float(beta_ref))
        rows.append(row)

    star = max(rows, key=lambda r: r['L_D'])          # α* = argmax L/D
    cd0_row = min(rows, key=lambda r: r['C_D'])        # min-drag point → C_L0
    row0 = min(rows, key=lambda r: abs(r['alpha_deg']))  # nearest α = 0
    trim = dict(alpha_star_deg=star['alpha_deg'], C_L_star=star['C_L'],
                C_D_star=star['C_D'], LD_max=star['L_D'],
                C_L0=cd0_row['C_L'], C_D0=row0['C_D'])
    if mass_kg and beta_ref:
        trim['beta_zero_lift'] = float(mass_kg) / (row0['C_D'] * float(beta_ref))
        trim['beta_trim'] = float(mass_kg) / (star['C_D'] * float(beta_ref))
    return dict(conditions=conditions, alpha=rows, trim=trim)


# Tolerance on the drag floor, as a fraction of the geometry's own C_D at the
# tested lift.  The floor is only as good as its friction term: route-to-route
# C_D0 agreement is ~10%, and the Eckert-vs-internal friction convention alone
# moves C_D0 by ~16% (docs/aero_polar_calibration.md §3).  A violation smaller
# than this is inside the modelling band, not a finding.
PAIRING_DRAG_TOL = 0.15


def check_beta_ld_pairing(sweep, mass_kg, a_ref_m2, beta_kg_m2, glider_LD,
                          tol=PAIRING_DRAG_TOL):
    """Is an entered (β, (L/D)max) pair physically consistent with the shape?

    β and glider_LD are entered independently, and `trajectory._aero_polar`
    back-solves whatever `k` reconciles them — so the polar can never disagree
    with the user (docs/aero_polar_calibration.md §2).  This is the missing
    disagreement.

    The pair already fixes its own trim point, with no geometry involved::

        C_D0 = m / (β · A_ref)          (β is a zero-lift statement)
        C_L* = 2 · C_D0 · (L/D)         (the lift the pair trims to)
        C_D* = 2 · C_D0                 (the drag it claims there)

    The last two are identities of the back-solve, not results.  So ask the
    swept geometry ONE question — what is *your* drag at C_L*? — and compare.

    Deliberately no fitted `k`.  Point-by-point `k` is flat to ±8% on a bare
    body but spreads 44-69% once a lifting surface is added (§3), so a
    parabola is a poor summary; evaluating at the single lift coefficient the
    pair actually trims to sidesteps the question.

    ONE-SIDED BY CONSTRUCTION.  The sweep's C_D is a floor — pressure plus
    friction plus base, and every term it omits (nose bluntness, fins, trim
    deflection, protuberances, a turbulent rather than laminar wall) ADDS
    drag.  So this can say "you cannot have less drag than this" and can never
    say "you must have this much."  An entered L/D *below* what the geometry
    supports is normal and is never a failure; the surplus is reported as the
    parasite drag the pairing implies but the shape description does not
    explain.  Carryover lift is the one term that pushes the other way (it
    lowers `k`, raising the derived L/D) and is absent from both sides, which
    makes the floor conservative rather than optimistic (§6.4).

    `sweep` is a `lifting_body_sweep()` result; its `conditions` are carried
    into the verdict, because a drag floor without its Mach, Reynolds number
    and wall state is not a number (Fetterman).

    Returns a dict with `verdict` one of:

      'ok'               C_D* ≥ the shape's drag at C_L*.  `implied_parasite`
                         is the unexplained surplus (≥ 0).
      'marginal'         C_D* short of the floor, but inside `tol`.
      'drag_below_shape' C_D* short of the floor by more than `tol` — the pair
                         claims less total drag than the shape has at the lift
                         it needs.
      'lift_unreachable' C_L* exceeds the largest C_L on the sweep: the shape
                         cannot make that much lift at any swept α.
      'insufficient'     inputs missing; nothing tested.

    Never raises on a bad pairing and never blocks — the caller decides.
    """
    out = dict(verdict='insufficient', reason='', conditions=sweep.get(
        'conditions', {}) if isinstance(sweep, dict) else {})
    try:
        m = float(mass_kg or 0.0); a = float(a_ref_m2 or 0.0)
        bet = float(beta_kg_m2 or 0.0); ld = float(glider_LD or 0.0)
    except (TypeError, ValueError):
        out['reason'] = 'non-numeric input'
        return out
    if not (m > 0.0 and a > 0.0 and bet > 0.0 and ld > 0.0):
        out['reason'] = 'need mass, A_ref, beta and glider_LD all > 0'
        return out
    rows = [r for r in (sweep.get('alpha') or []) if r['alpha_deg'] >= 0.0]
    if len(rows) < 2:
        out['reason'] = 'sweep has no positive-alpha rows'
        return out

    C_D0 = m / (bet * a)
    C_L_star = 2.0 * C_D0 * ld
    C_D_star = 2.0 * C_D0
    out.update(C_D0_entered=C_D0, C_L_star=C_L_star, C_D_star=C_D_star)

    # Ceilings, reported whatever the verdict.  beta_ceiling: the shape's own
    # zero-lift drag is a floor, so its beta is a ceiling.  ld_ceiling: give
    # the shape the user's unexplained parasite drag (the §4a "deficit into
    # C_D0" route) and re-peak — that is the best L/D their beta can support.
    geo = sweep.get('trim') or {}
    C_D0_geo = float(geo.get('C_D0', 0.0) or 0.0)
    if C_D0_geo <= 0.0:
        out['reason'] = 'sweep produced no zero-lift drag'
        return out
    out['beta_ceiling'] = m / (C_D0_geo * a)
    extra = max(0.0, C_D0 - C_D0_geo)
    out['ld_ceiling'] = max((r['C_L'] / (r['C_D'] + extra))
                            for r in rows if (r['C_D'] + extra) > 0.0)
    out['LD_max_geo'] = float(geo.get('LD_max', 0.0) or 0.0)

    # Two independent one-sided tests.  beta alone can be impossible even when
    # the trim point passes: C_D0 is compared at zero lift, C_D* at C_L*, and
    # a small C_L* leaves room for one to pass while the other fails.
    beta_short = (C_D0_geo - C_D0) if C_D0_geo > 0.0 else 0.0
    if beta_short > tol * C_D0_geo:
        out['beta_verdict'] = 'beta_below_shape'
    elif beta_short > 0.0:
        out['beta_verdict'] = 'marginal'
    else:
        out['beta_verdict'] = 'ok'

    cl = [r['C_L'] for r in rows]
    if C_L_star > max(cl):
        out.update(verdict='lift_unreachable', C_L_max_geo=max(cl),
                   reason=(f"trim C_L* = {C_L_star:.4f} exceeds the shape's "
                           f"largest swept C_L = {max(cl):.4f}"))
        return out

    # C_L rises monotonically with alpha over the positive range for every
    # form the sweep implements, so a straight interpolation on C_L is safe.
    import numpy as _np
    order = _np.argsort(_np.asarray(cl))
    C_D_geo = float(_np.interp(C_L_star, _np.asarray(cl)[order],
                               _np.asarray([r['C_D'] for r in rows])[order]))
    a_geo = float(_np.interp(C_L_star, _np.asarray(cl)[order],
                             _np.asarray([r['alpha_deg'] for r in rows])[order]))
    surplus = C_D_star - C_D_geo
    out.update(C_D_geo_at_C_L_star=C_D_geo, alpha_star_deg_geo=a_geo,
               implied_parasite=surplus)
    if surplus >= 0.0:
        trim_verdict, why = 'ok', (
            f"pairing implies {surplus:.4f} of C_D beyond the modelled shape")
    elif -surplus <= tol * C_D_geo:
        trim_verdict, why = 'marginal', (
            f"C_D* = {C_D_star:.4f} is {-surplus:.4f} short of the shape's "
            f"{C_D_geo:.4f} at C_L* — inside the {tol:.0%} modelling band")
    else:
        trim_verdict, why = 'drag_below_shape', (
            f"C_D* = {C_D_star:.4f} is below the shape's own {C_D_geo:.4f} at "
            f"C_L* = {C_L_star:.4f} (alpha ~ {a_geo:.1f} deg) by "
            f"{-surplus / C_D_geo:.0%}")
    out['trim_verdict'] = trim_verdict

    # Summary verdict: the more severe of the two, with the reason naming both
    # when both fail.  beta_below_shape is reported only when the trim test
    # passes, so a single verdict never hides the stronger statement.
    _rank = {'ok': 0, 'marginal': 1, 'beta_below_shape': 2,
             'drag_below_shape': 3}
    bv = out['beta_verdict']
    if _rank.get(bv, 0) > _rank[trim_verdict]:
        out.update(verdict=bv, reason=(
            f"entered beta implies C_D0 = {C_D0:.4f}, below the shape's own "
            f"{C_D0_geo:.4f} by {beta_short / C_D0_geo:.0%} — less zero-lift "
            f"drag than the geometry has ({why})"))
    else:
        out.update(verdict=trim_verdict, reason=(
            why if bv == 'ok' else f"{why}; beta test: {bv}"))
    return out


def _ro_sweep_kwargs(ro):
    """Map a reentry object's stored geometry onto `lifting_body_sweep()`
    keyword arguments.  Returns (kwargs, a_ref_m2, reason) — kwargs is None
    with a reason when the object lacks the geometry to sweep.  Shared by the
    pairing check and the β(Mach) table so there is one mapping, not two.
    β is always BASE-referenced here (A_ref = π·d²/4), for every form."""
    import math
    form = str(getattr(ro, 'body_form', '') or 'axisymmetric')
    d = float(getattr(ro, 'diameter_m', 0.0) or 0.0)
    L = float(getattr(ro, 'length_m', 0.0) or 0.0)
    m = float(getattr(ro, 'mass_kg', 0.0) or 0.0)
    if not (d > 0.0 and L > 0.0):
        return None, 0.0, 'object has no diameter/length to sweep'
    a_ref = 0.25 * math.pi * d * d
    kw = dict(mass_kg=m, a_ref_m2=a_ref, length_m=L)
    theta = math.degrees(math.atan2(d / 2.0, L))
    if form == 'wedge':
        span = float(getattr(ro, 'body_span_m', 0.0) or 0.0)
        if span <= 0.0:
            return None, a_ref, 'wedge body has no body_span_m; sweep needs the span'
        kw.update(form='wedge', span_m=span, depth_m=d)
    elif form == 'half_cone':
        s_e = float(getattr(ro, 'wing_span_exposed_m', 0.0) or 0.0)
        c_r = float(getattr(ro, 'wing_root_chord_m', 0.0) or 0.0)
        wing = 0.0
        if s_e > 0.0 and c_r > 0.0:
            sw = math.radians(float(getattr(ro, 'wing_sweep_deg', 0.0) or 0.0))
            c_t = max(0.0, c_r - s_e * math.tan(sw))
            wing = 0.5 * (c_r + c_t) * s_e
        kw.update(form='half_cone', theta_deg=theta, wing_exposed_m2=wing)
    else:
        kw.update(form='cone', theta_deg=theta)
    return kw, a_ref, ''


def sweep_and_check_ro(ro, mach=5.0, reynolds_length=None,
                       wall_temp_ratio=1.0, turbulent=True,
                       tol=PAIRING_DRAG_TOL):
    """Run the α-sweep for a reentry object's own geometry and test its stored
    (β, glider_LD) pair against it.  Convenience wrapper over
    `lifting_body_sweep()` + `check_beta_ld_pairing()`; the single entry point
    the GUI warning and the library test both use, so the geometry mapping
    lives in one place.

    `mach` defaults to 5.0, matching `glider_ld.GLIDE_MACH_REF` (not imported
    here — glider_ld imports this module).

    **`reynolds_length=None` (the default) gives the INVISCID floor**, and that
    is the deliberate choice for an impossibility test: pressure plus base drag
    alone, with no friction term to argue about.  A pairing that violates the
    inviscid floor is impossible on any friction convention.  Supply a Reynolds
    number to tighten the floor to a plausibility test at stated conditions —
    stricter, but only as good as the wall-state assumption
    (docs/aero_polar_calibration.md §3).

    Returns the `check_beta_ld_pairing()` dict, with 'insufficient' whenever
    the object lacks the geometry to sweep.  Never raises on bad data.
    """
    def _bad(why):
        return dict(verdict='insufficient', reason=why, conditions={})

    kw, a_ref, why = _ro_sweep_kwargs(ro)
    if kw is None:
        return _bad(why)
    m = kw['mass_kg']
    kw.update(mach=mach, reynolds_length=reynolds_length,
              wall_temp_ratio=wall_temp_ratio, turbulent=turbulent)
    try:
        sweep = lifting_body_sweep(**kw)
    except (ValueError, ZeroDivisionError) as exc:
        return _bad(f'sweep failed: {exc}')
    return check_beta_ld_pairing(
        sweep, m, a_ref,
        float(getattr(ro, 'beta_kg_m2', 0.0) or 0.0),
        float(getattr(ro, 'glider_LD', 0.0) or 0.0), tol=tol)


# Mach band a reentry / glide body is swept over when the schema does not say
# where its beta was claimed.  beta_kg_m2 is a single constant but a shape's
# own beta varies several-fold across this band, so a verdict at one Mach is an
# artefact of that choice (docs/aero_polar_calibration.md §6.5).
PAIRING_MACH_BAND = (3.0, 5.0, 8.0, 10.0, 12.0, 15.0, 20.0)

_PAIRING_RANK = {'ok': 0, 'marginal': 1, 'beta_below_shape': 2,
                 'drag_below_shape': 3, 'lift_unreachable': 4,
                 'insufficient': 5}


def check_ro_pairing_band(ro, machs=PAIRING_MACH_BAND, **kw):
    """`sweep_and_check_ro()` over a Mach band, reporting the MOST PERMISSIVE
    verdict and where it holds.

    `beta_kg_m2` is one number and the schema does not record the Mach at which
    it is claimed, while the same shape's zero-lift beta varies several-fold
    across a glide band.  A verdict at a single Mach therefore says as much
    about the Mach chosen as about the pairing.  The defensible one-sided
    statement is over the whole band: **a pairing is impossible only if no Mach
    in the band supports it.**  That is what this returns.

    Result adds to the `check_beta_ld_pairing()` dict of the best Mach:
      `mach_best`     the Mach giving the least severe verdict
      `mach_band`     the band swept
      `mach_ok`       Machs whose verdict was 'ok' or 'marginal'
      `by_mach`       {mach: verdict} for the whole band

    Use this, not the single-Mach form, whenever the object does not state the
    conditions its beta belongs to.
    """
    # A stated reference Mach removes the ambiguity the band exists for: the
    # entered β belongs to that Mach, so test the pair there and only there.
    _m_ref = float(getattr(ro, 'beta_ref_mach', 0.0) or 0.0)
    if _m_ref > 0.0:
        machs = (_m_ref,)
    best, by_mach = None, {}
    for M in machs:
        r = sweep_and_check_ro(ro, mach=float(M), **kw)
        by_mach[float(M)] = r.get('verdict', 'insufficient')
        if best is None or (_PAIRING_RANK.get(r.get('verdict'), 5)
                            < _PAIRING_RANK.get(best[1].get('verdict'), 5)):
            best = (float(M), r)
    if best is None:
        return dict(verdict='insufficient', reason='empty Mach band',
                    conditions={}, by_mach={})
    out = dict(best[1])
    out['mach_best'] = best[0]
    out['mach_band'] = tuple(float(m) for m in machs)
    out['mach_ok'] = tuple(m for m, v in by_mach.items()
                           if v in ('ok', 'marginal'))
    out['by_mach'] = by_mach
    if out['mach_ok']:
        out['reason'] = (f"{out['reason']}  [best at M{best[0]:.0f}; "
                         f"supported at M "
                         f"{', '.join(f'{m:.0f}' for m in out['mach_ok'])}]")
    else:
        out['reason'] = (f"{out['reason']}  [no Mach in "
                         f"{min(out['mach_band']):.0f}-"
                         f"{max(out['mach_band']):.0f} supports this pairing]")
    return out


# Mach grid for the stated-β table.  Below M3 the hypersonic build-up floors
# (cd_cone_hypersonic uses max(M, 3)), so the table is flat there; np.interp
# clamps outside the grid.  The upper end covers a boost-glide entry.
BETA_MACH_GRID = (1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0)


def beta_mach_table(ro, machs=BETA_MACH_GRID):
    """β(Mach) for an object whose entered β is stated at `ro.beta_ref_mach`.

    The entered β is held EXACT at the reference Mach.  The object's own
    geometry supplies only the RELATIVE variation — derive, don't invent::

        β(M)   = β_entered · C_D0(M_ref) / C_D0(M)
        L/D(M) = L/D_entered · sqrt(C_D0(M_ref) / C_D0(M))

    The L/D line keeps the drag-due-to-lift factor k FIXED at its reference-
    Mach value: with C_D0 = m/(β·A) and k = 1/(4·C_D0·(L/D)²), scaling both as
    above leaves k unchanged.  The Mach variation is zero-lift (base) drag, so
    it belongs in C_D0 and costs peak L/D where C_D0 rises — it is not absorbed
    into k (docs/aero_polar_calibration.md §4a).

    C_D0(M) comes from the SAME build-up the "Estimate Object β" dialog uses,
    so a β estimated at Mach X and stamped with X reproduces itself:
    cd_cone_hypersonic / cd_biconic_hypersonic (θ = atan(r_b/L), ε = 2·r_n/d,
    wing zero-lift drag from the stored planform) for a body of revolution,
    and the α = 0 row of lifting_body_sweep at the same Cf for the lifting
    forms.  In every form the only Mach-dependent term is base drag, 2/(γM²) —
    the p_base → 0 limit, exact at hypersonic speed and an upper bound that
    OVERSTATES base drag toward low supersonic Mach.  So the table's low-Mach
    end is the least certain part: β there is biased low.

    Returns None when `beta_ref_mach` is 0 (constant β — the legacy
    behaviour), when β is not entered, or when the geometry cannot be swept.
    Otherwise a dict: machs, cd0, ratio (= C_D0(M_ref)/C_D0(M)), ref_mach,
    cd0_ref, beta (β·ratio), ld_scale (sqrt(ratio)), source.
    """
    import math
    import numpy as _np
    m_ref = float(getattr(ro, 'beta_ref_mach', 0.0) or 0.0)
    beta = float(getattr(ro, 'beta_kg_m2', 0.0) or 0.0)
    if m_ref <= 0.0 or beta <= 0.0:
        return None
    form = str(getattr(ro, 'body_form', '') or 'axisymmetric')
    d = float(getattr(ro, 'diameter_m', 0.0) or 0.0)
    L = float(getattr(ro, 'length_m', 0.0) or 0.0)
    if not (d > 0.0 and L > 0.0):
        return None
    a_base = 0.25 * math.pi * d * d

    if form == 'axisymmetric':
        rn = float(getattr(ro, 'nose_radius_m', 0.0) or 0.0)
        eps = max(0.0, min(2.0 * rn / d, 1.0))
        s_w = float(wing_geometry(ro)[0] or 0.0)
        war = s_w / a_base if a_base > 0.0 else 0.0
        bic = (biconic_angles(d, L, float(getattr(ro, 'fore_length_m', 0.0) or 0.0),
                              float(getattr(ro, 'break_diameter_m', 0.0) or 0.0), rn)
               if getattr(ro, 'biconic', False) else None)
        if bic:
            th1, th2, br = bic[0], bic[1], bic[2]
            cd0 = lambda M: cd_biconic_hypersonic(th1, th2, br, eps, mach=M,
                                                  wing_area_ratio=war)['total']
            source = 'cd_biconic_hypersonic'
        else:
            th = math.degrees(math.atan2(d / 2.0, L))
            cd0 = lambda M: cd_cone_hypersonic(th, eps, mach=M,
                                               wing_area_ratio=war)['total']
            source = 'cd_cone_hypersonic'
    else:
        kw, _a, _why = _ro_sweep_kwargs(ro)
        if kw is None:
            return None
        kw = dict(kw, cf=CONE_CF_TURBULENT, alpha_min_deg=0.0,
                  alpha_max_deg=0.0, n_alpha=1)

        def cd0(M, _kw=kw):
            return lifting_body_sweep(mach=M, **_kw)['trim']['C_D0']
        source = f'lifting_body_sweep({form}, alpha=0)'

    try:
        grid = _np.asarray(sorted(set(float(x) for x in machs) | {m_ref}))
        cds = _np.asarray([float(cd0(M)) for M in grid])
        c_ref = float(cd0(m_ref))
    except (ValueError, ZeroDivisionError, TypeError, KeyError):
        return None
    if not (c_ref > 0.0 and _np.all(_np.isfinite(cds)) and _np.all(cds > 0.0)):
        return None
    ratio = c_ref / cds
    return dict(machs=grid, cd0=cds, ratio=ratio, ref_mach=m_ref,
                cd0_ref=c_ref, beta=beta * ratio, ld_scale=_np.sqrt(ratio),
                source=source)


def pairing_note(ro, machs=PAIRING_MACH_BAND, **kw):
    """One-line, user-facing verdict on an object's stored (β, glider_LD) pair.

    Pure formatting over `check_ro_pairing_band()`, kept out of the GUI so it
    is testable without a display.  Returns `(text, severity)` where severity
    is 'none' (nothing to say), 'ok', 'warn' or 'bad' — the caller maps it to a
    colour.  **Advisory only**: nothing here blocks a save.
    """
    try:
        r = check_ro_pairing_band(ro, machs=machs, **kw)
    except Exception as exc:                      # never break an editor
        return (f"pairing not checked ({exc.__class__.__name__})", 'none')
    v = r.get('verdict', 'insufficient')
    if v == 'insufficient':
        return ('', 'none')
    ceil = float(r.get('ld_ceiling', 0.0) or 0.0)
    m_ok = tuple(r.get('mach_ok') or ())
    # A stated β Mach tests ONE Mach, so the wording must not claim a band.
    single = len(tuple(r.get('mach_band') or ())) == 1
    where = f"at M {r['mach_band'][0]:g}" if single else None
    if v == 'ok':
        surplus = float(r.get('implied_parasite', 0.0) or 0.0)
        band = where or (f"over M {min(m_ok):.0f}–{max(m_ok):.0f}" if len(m_ok) > 1
                         else (f"at M {m_ok[0]:.0f}" if m_ok
                               else "over the swept band"))
        return (f"consistent with the shape {band}; implies "
                f"+{surplus:.3f} C_D of parasite drag the geometry does not "
                f"model", 'ok')
    if v == 'marginal':
        return (f"borderline — at this β the shape supports about L/D "
                f"{ceil:.2f}, inside the modelling band", 'warn')
    if v == 'lift_unreachable':
        return ("the shape cannot reach the lift this pair needs at any swept "
                "angle of attack", 'bad')
    if v == 'beta_below_shape':
        bc = float(r.get('beta_ceiling', 0.0) or 0.0)
        return (f"β claims less drag than the shape has — its own β ceiling "
                f"is {bc:,.0f} kg/m²", 'bad')
    lead = (f"{where}, this pair is not supported" if single
            else "no Mach supports this pair")
    return (f"{lead} — at this β the shape reaches about L/D {ceil:.2f}; "
            f"check the fin and nose geometry before the numbers", 'bad')


def wing_geometry(ro):
    """Effective wing (S, AR, source) for a reentry object — single source of
    truth for every consumer (drag polar, β estimator, editor, schematic).

    The wing PLANFORM (wing_root_chord_m, wing_span_exposed_m, wing_sweep_deg)
    is the PRIMARY data when present: chords and spans are measurable off an
    image, an area is not, so S and AR are ALWAYS DERIVED from the planform —
    a stored wing_area_m2/wing_aspect_ratio can never disagree with it.  Direct
    S/AR entry is the fallback when no planform is stored.

    Derivation (reference-wing convention, carry-through included):
        c_t   = max(0, c_r − s_e·tanΛ)          tip chord (TE straight)
        S_exp = (c_r + c_t)·s_e                  both exposed panels
        S     = S_exp + c_r·D                    + carry-through at the root
        b     = 2·s_e + D                        tip-to-tip span
        AR    = b²/S

    Returns (S_m2, AR, source): source is 'planform' (derived), 'direct'
    (stored S; AR may be 0 = caller default), or None (no wings).
    """
    import math
    c_r = float(getattr(ro, 'wing_root_chord_m', 0.0) or 0.0)
    s_e = float(getattr(ro, 'wing_span_exposed_m', 0.0) or 0.0)
    if c_r > 0.0 and s_e > 0.0:
        sw = math.radians(float(getattr(ro, 'wing_sweep_deg', 0.0) or 0.0))
        D = max(0.0, float(getattr(ro, 'diameter_m', 0.0) or 0.0))
        c_t = max(0.0, c_r - s_e * math.tan(sw))
        S = (c_r + c_t) * s_e + c_r * D
        b = 2.0 * s_e + D
        return S, (b * b / S if S > 0 else 0.0), 'planform'
    S = float(getattr(ro, 'wing_area_m2', 0.0) or 0.0)
    if S > 0.0:
        return S, float(getattr(ro, 'wing_aspect_ratio', 0.0) or 0.0), 'direct'
    return 0.0, 0.0, None


def biconic_angles(diameter_m: float, length_m: float, fore_length_m: float,
                   break_diameter_m: float, nose_radius_m: float = 0.0):
    """Derive (theta1_deg, theta2_deg, break_ratio, eps) for a biconic from its
    stored geometry — the free inputs are fore_length_m and break_diameter_m;
    the half-angles fall out.  Returns None if the geometry is not a valid
    biconic (missing/degenerate break)."""
    import math
    r_b = float(diameter_m) / 2.0
    r_1 = float(break_diameter_m) / 2.0
    Lf  = float(fore_length_m)
    La  = float(length_m) - Lf
    if r_b <= 0 or r_1 <= 0 or r_1 >= r_b or Lf <= 0 or La <= 0:
        return None
    theta1 = math.degrees(math.atan2(r_1, Lf))          # fore-cone half-angle
    theta2 = math.degrees(math.atan2(r_b - r_1, La))    # aft-frustum half-angle
    eps    = max(0.0, min(float(nose_radius_m) / r_b, 1.0))
    return theta1, theta2, r_1 / r_b, eps


def biconic_nose_geometry(params: 'BoosterParams'):
    """As-flown biconic-nose geometry for the front end, or None when it is not
    a valid biconic.

    ONE source of truth so a declared biconic FLIES (glider_ld Cd0 + planform),
    TRIMS (grid_fin_sizing CP) and DRAWS (booster_schematic) as two cones — the
    DRAWN ≡ FLOWN contract (FRONT_END_DESIGN.md).  For a non-separating body the
    biconic occupies the forward ``body_nose_length_m`` of the airframe (the nose
    carved subtractively from the last stage); a separating biconic RV uses its
    own ``length_m``.  The break geometry (``fore_length_m``, ``break_diameter_m``)
    must be set and valid, else this returns None and callers keep the single-
    cone path — so biconic activates only once the two extra fields are entered.

    Returns {theta1_deg, theta2_deg, break_ratio, eps, fore_len_m, aft_len_m,
    nose_len_m, base_diameter_m, break_diameter_m} — all as-flown.
    """
    ro = effective_ro(params)
    if ro is None or not bool(getattr(ro, 'biconic', False)):
        return None
    body = getattr(ro, 'separation_mode', 'separating_ro') == 'body'
    base_d = float(getattr(ro, 'diameter_m', 0.0) or 0.0)
    if base_d <= 0.0:
        return None
    if body:
        # The nose is carved from the last stage: the biconic IS the forward
        # body_nose_length_m (same subtractive taper the schematic/CG use).
        last = params
        while getattr(last, 'stage2', None) is not None:
            last = last.stage2
        nose_len = float(getattr(ro, 'body_nose_length_m', 0.0) or 0.0)
        if nose_len <= 0.0:
            nose_len = min(3.0 * base_d,
                           0.5 * float(last.length_m or (2.0 * base_d)))
        nose_len = max(0.0, min(nose_len, float(last.length_m or nose_len)))
    else:
        nose_len = float(getattr(ro, 'length_m', 0.0) or 0.0)
    fore_len = float(getattr(ro, 'fore_length_m', 0.0) or 0.0)
    break_d  = float(getattr(ro, 'break_diameter_m', 0.0) or 0.0)
    nose_rn  = float(getattr(ro, 'nose_radius_m', 0.0) or 0.0)
    ang = biconic_angles(base_d, nose_len, fore_len, break_d, nose_rn)
    if ang is None:
        return None
    theta1, theta2, br, eps = ang
    return dict(theta1_deg=theta1, theta2_deg=theta2, break_ratio=br, eps=eps,
                fore_len_m=fore_len, aft_len_m=nose_len - fore_len,
                nose_len_m=nose_len, base_diameter_m=base_d,
                break_diameter_m=break_d)


def cd0_biconic_body(geom: dict, ld_body: float, mach: float,
                     cf: float = CONE_CF_TURBULENT,
                     wing_area_ratio: float = 0.0) -> float:
    """Zero-lift body Cd0 (base-area referenced) for a biconic-nosed body: the
    two-cone hypersonic build-up (cd_biconic_hypersonic) plus the cylindrical
    afterbody friction aft of the nose.  ``geom`` is a biconic_nose_geometry()
    dict; ``ld_body`` is the full-body fineness (body_length / diameter).

    Framework note: this is the hypersonic Newtonian two-cone model (valid
    M ≥ 3), distinct from the Chin/NACA single-nose build-up (_cd_nose_shape)
    used for single-profile noses; toggling biconic therefore shifts frameworks,
    comparable but not identical at a shared Mach.  Reduces to a single hyper-
    sonic cone (cd_cone_hypersonic + the same afterbody term) when θ2 = θ1,
    sharp — the regression anchor cd_biconic_hypersonic already guarantees.
    """
    base_d = float(geom['base_diameter_m'])
    ld_nose = geom['nose_len_m'] / base_d if base_d > 0.0 else 0.0
    r = cd_biconic_hypersonic(geom['theta1_deg'], geom['theta2_deg'],
                              geom['break_ratio'], geom['eps'], mach=mach,
                              cf=cf, wing_area_ratio=wing_area_ratio)
    swet_cyl = 4.0 * max(0.0, float(ld_body) - ld_nose)      # base-area ref
    return float(r['total'] + cf * swet_cyl)


def biconic_nose_cp_fraction(break_ratio: float, fore_len_m: float,
                             aft_len_m: float) -> float:
    """Barrowman centre-of-pressure of a biconic nose, as a fraction of the total
    nose length from the tip.  The area-weighted CP of the fore cone (tip →
    break) and the aft frustum (break → base), each weighted by its Barrowman
    normal-force slope CNα ∝ Δ(r²)/r_base².  A function of the break ratio and
    the two segment lengths only (the half-angles are redundant — fixed by those
    plus the base diameter).  Reduces to 2/3 (the single-cone value) when the
    break lies on a straight cone (break_ratio = fore_len/nose_len); a slender
    break (smaller ratio) throws more area onto the aft frustum and moves the CP
    aft, a fat break moves it forward — the two-cone stability a single-cone
    fraction cannot show.
    """
    br = max(1e-6, min(float(break_ratio), 1.0 - 1e-9))
    Lf = max(0.0, float(fore_len_m))
    La = max(0.0, float(aft_len_m))
    nose_len = Lf + La
    if nose_len <= 0.0:
        return 0.666
    cn_fore = br * br                        # (r_break² − 0) / r_base²
    cn_aft  = 1.0 - br * br                  # (r_base² − r_break²) / r_base²
    x_fore = (2.0 / 3.0) * Lf                # cone (dr = 0): 2/3 of its length
    if La > 0.0:
        # frustum CP from its front, transition dr = d_break/d_base = br
        x_aft = Lf + (La / 3.0) * (1.0 + (1.0 - br) / (1.0 - br * br))
    else:
        x_aft = Lf
    cn = cn_fore + cn_aft
    if cn <= 0.0:
        return 0.666
    return (cn_fore * x_fore + cn_aft * x_aft) / cn / nose_len


def tumbling_cylinder_beta(mass_kg: float, diameter_m: float, length_m: float,
                           cd: float = 1.0, mach: float = None) -> float:
    """
    Ballistic coefficient β (kg/m²) for a tumbling cylinder.

    Two forms are available:

    * **Legacy single-Cd** (``cd`` given, the default ``cd = 1.0``): one drag
      coefficient on the mean of the end-on and broadside projected areas,

          A_eff = (π d² / 4  +  d · L) / 2 ,   β = m / (Cd · A_eff)

      Cd = 1.0 is representative of a subsonic/transonic tumbling bluff body.
      This is what the spent-casing / shroud debris arcs use, so those callers
      are unchanged.

    * **Hoerner two-orientation** (``cd = None``): each orientation carries its
      OWN drag coefficient, referenced to its own projected area —

          (Cd·A)_eff = ½ [ Cd_broadside · d·L  +  Cd_end · π d²/4 ]
          β          = m / (Cd·A)_eff

      with primary hypersonic coefficients from Hoerner, *Fluid-Dynamic Drag*
      (1965):
        - broadside (cross-flow cylinder): Cd = ⅔·C_p•    (Ch. XVIII eq. 44, Fig. 24)
        - end-on (blunt cylinder face):    Cd = 0.89·C_p•  (Ch. XVIII Fig. 22)
      and C_p• = 1.84 − 0.76/M² (eq. 41).  At hypersonic M: ≈ 1.2 broadside,
      ≈ 1.6 end-on.  ``mach`` selects the coefficients (default: the M → ∞
      limit, C_p• = 1.84).  This is the form for an uncontrolled reentry body.

    Returns 0 if length or diameter is zero.
    """
    A_end  = np.pi * diameter_m ** 2 / 4.0
    A_side = diameter_m * length_m
    if A_end + A_side <= 0:
        return 0.0
    if cd is not None:
        A_eff = (A_end + A_side) / 2.0
        return mass_kg / (cd * A_eff) if A_eff > 0 else 0.0
    cp = _hoerner_cp_impact(mach if mach is not None else 1e9)
    cd_broadside = (2.0 / 3.0) * cp        # cross-flow cylinder (eq. 44)
    cd_end       = 0.89 * cp               # blunt cylinder face (Fig. 22)
    cdA_eff = 0.5 * (cd_broadside * A_side + cd_end * A_end)
    return mass_kg / cdA_eff if cdA_eff > 0 else 0.0


def _eff_burn(s: BoosterParams) -> float:
    """Effective powered-burn duration for stage `s` (s).

    Equals burn_time_s unless a commanded engine cutoff (stage_cutoff_s) shuts
    the stage down early.  Cutoff applies to liquid engines only — a solid
    motor burns to completion regardless.  The value is clamped to
    [0, burn_time_s]; the stage's slot in the timeline is unchanged (only the
    powered fraction shrinks), so this never moves staging or guidance timing.
    """
    c = s.stage_cutoff_s
    if c is None or s.solid_motor or s.burn_time_s <= 0:
        return s.burn_time_s
    return max(0.0, min(float(c), s.burn_time_s))


def total_burn_time(params: BoosterParams) -> float:
    """Total time from launch (T=0) to end of last stage's burn.

    Includes booster_core_delay_s when strap-ons ignite before the core.
    """
    t, s = params.booster_core_delay_s, params
    while s is not None:
        t += s.burn_time_s
        if s.stage2 is not None:
            t += s.coast_time_s   # inter-stage coast before next ignition
        s  = s.stage2
    return t


def active_stage(params: BoosterParams, t: float) -> BoosterParams:
    """Return the BoosterParams for the stage (or vehicle) active at time t.

    During powered flight this is the burning stage.  During a coast phase
    it is the next (upper) stage — stage N has been jettisoned and the
    remaining vehicle has stage N+1's geometry.  After all stages have fired
    it is the last stage (used for drag during the ballistic coast/re-entry).
    """
    t_rem, s = t, params
    while s.stage2 is not None:
        if t_rem < s.burn_time_s:
            return s
        t_rem -= s.burn_time_s
        if t_rem < s.coast_time_s:
            return s.stage2   # coasting: stage s jettisoned, next is the vehicle
        t_rem -= s.coast_time_s
        s      = s.stage2
    return s   # last stage (or only stage)


def active_stage_and_t(params: BoosterParams, t: float):
    """Return (active_stage, t_since_ignition) for time t.

    t_since_ignition is the time elapsed since the returned stage ignited,
    used to evaluate per-stage pitch-over guidance.  During a coast phase
    the next stage is returned with t_since_ignition = 0.
    """
    t_rem, s = t, params
    while s.stage2 is not None:
        if t_rem < s.burn_time_s:
            return s, t_rem
        t_rem -= s.burn_time_s
        if t_rem < s.coast_time_s:
            return s.stage2, 0.0   # coasting; next stage not yet ignited
        t_rem -= s.coast_time_s
        s      = s.stage2
    return s, t_rem   # last stage


def booster_separation_time(params: BoosterParams) -> float:
    """Time (s after T=0) the spent strap-on boosters physically leave.

    booster_jettison_s if set later than burnout, else burnout.  A jettison
    time at or before burnout is treated as "separate at burnout" — boosters
    cannot leave while still thrusting.
    """
    t_b = params.booster_burn_time_s
    return params.booster_jettison_s if params.booster_jettison_s > t_b else t_b


def _booster_mass_addend(params: BoosterParams, t: float) -> float:
    """Mass (kg) contributed by attached strap-on boosters; 0 after separation.

    Between burnout and jettison (when booster_jettison_s > burn time) the
    spent boosters ride along as dead inert mass.
    """
    n, t_b = params.n_boosters, params.booster_burn_time_s
    if n <= 0 or t_b <= 0 or t > booster_separation_time(params):
        return 0.0
    t = max(0.0, t)
    if t >= t_b:                       # burned out, not yet jettisoned
        return n * params.booster_inert_kg
    return (n * (params.booster_prop_kg + params.booster_inert_kg)
            - n * params.booster_prop_kg / t_b * t)


# Free-molecular heating flux at which a payload shroud/fairing is jettisoned.
# 1135 W/m^2 = 0.1 BTU/ft^2-s, the standard launch-vehicle fairing-jettison
# thermal criterion (ULA Atlas V / Delta IV and SpaceX Falcon user's guides;
# collated in Isakowitz, International Reference Guide to Space Launch Systems).
# q_dot = 1/2 rho V^3 is the free-molecular convective flux (accommodation ~1).
SHROUD_Q_FAIRING = 1135.0   # W/m^2


def _shroud_jettisoned(params: 'BoosterParams', alt_m: float) -> bool:
    """Has the payload shroud been jettisoned by this point in the flight?

    Two modes, selected by shroud_jettison_alt_km:
      * > 0  — explicit altitude override: jettison at that altitude (altitude
               is monotonic during boost, so this is self-latching).
      * <= 0 — heating default ("exoatmospheric"): jettison once the
               free-molecular flux 1/2 rho V^3 falls below SHROUD_Q_FAIRING
               after max-q.  The EOM maintains the latch
               params._shroud_latch = [armed, jettisoned, t_jettison]; this
               reads the jettisoned flag.  Before integration (no latch set),
               the shroud is treated as still attached.
    """
    if params.shroud_jettison_alt_km > 0:
        return alt_m / 1000.0 >= params.shroud_jettison_alt_km
    lat = getattr(params, '_shroud_latch', None)
    return bool(lat[1]) if lat is not None else False


def _stage_chain_mass(params: BoosterParams, t: float, alt_m: float = 0.0) -> float:
    """Mass of the stage chain only (excludes strap-on boosters)."""
    if t <= 0:
        return params.mass_initial
    t_rem, s = t, params
    while s is not None:
        if t_rem < s.burn_time_s:
            mdot = s.mass_propellant / s.burn_time_s
            # Propellant is consumed only up to the commanded cutoff; after that
            # the unburned propellant rides on as dead mass until jettison.
            mass = s.mass_initial - mdot * min(t_rem, _eff_burn(s))
            if params.shroud_mass_kg > 0 and _shroud_jettisoned(params, alt_m):
                mass -= params.shroud_mass_kg
            return mass
        t_rem -= s.burn_time_s
        if s.stage2 is None:
            # Post-burnout mass follows the run-level separation: a
            # separating loadout coasts on as the payload alone, while a
            # body-mode vehicle (V2 / Scud class) keeps the empty stage
            # fused to the warhead and coasts at full burnout mass.
            if (getattr(params, 'ro', None) is not None
                    and run_separation_mode(params) == 'body'):
                return (s.mass_initial - s.mass_propellant
                        if s.mass_propellant > 0 else s.mass_final)
            return params.payload_kg if params.payload_kg > 0 else s.mass_final
        if t_rem < s.coast_time_s:
            return s.stage2.mass_initial
        t_rem -= s.coast_time_s
        s = s.stage2
    return params.mass_final


def _interstage_mass_addend(params: BoosterParams, t: float) -> float:
    """Mass (kg) from interstage adapters still attached at time t.

    Each stage may carry an interstage on top of it (has_interstage).  The
    adapter rides with the stack from launch until its jettison event:
    interstage_jettison_s if set, else this stage's separation (its burnout,
    the same instant the stage leaves).  The stored stage masses do NOT include
    the interstage (the fields are additive, defaulting to zero), so this term
    is the whole of the interstage's contribution and existing vehicles get +0.
    """
    total = 0.0
    t_cursor = max(0.0, params.booster_core_delay_s)   # start of stage-1 burn
    s = params
    while s is not None:
        sep_t = t_cursor + s.burn_time_s               # this stage separates here
        if getattr(s, 'has_interstage', False) and getattr(s, 'interstage_mass_kg', 0.0) > 0:
            jt = getattr(s, 'interstage_jettison_s', None)
            jett = float(jt) if jt is not None else sep_t
            if t <= jett:
                total += float(s.interstage_mass_kg)
        t_cursor = sep_t + s.coast_time_s              # next stage ignites after coast
        s = s.stage2
    return total


def booster_mass(params: BoosterParams, t: float, alt_m: float = 0.0) -> float:
    """Current mass (kg) at time t seconds after launch.  Handles N stages,
    strap-on boosters, and interstage adapters.

    alt_m is the current altitude in metres; used for shroud-jettison accounting.
    When booster_core_delay_s > 0 the stage chain hasn't started burning until
    t >= delay, so we shift the time seen by _stage_chain_mass.
    """
    t_chain = t - params.booster_core_delay_s
    return (_stage_chain_mass(params, max(0.0, t_chain), alt_m)
            + _booster_mass_addend(params, max(0.0, t))
            + _interstage_mass_addend(params, max(0.0, t)))


def _boost_front_geometry(top_params: 'BoosterParams', params: BoosterParams,
                          altitude_m: float = None):
    """Front-end geometry exposed to the airstream during powered flight.

    Returns (nose_shape, diameter_m, nose_length_m, body_length_m, is_shroud).

    During boost the drag is set by whatever caps the front of the stack:
    the payload shroud/fairing while it is still attached, and the RV/payload
    nose once the shroud is gone.  The SAME body supplies both the reference
    area and the nose-shape Cd, so the two can never disagree (previously the
    area read the inline `ro_diameter_m` while the Cd read the ROParams
    diameter, which could differ).

    The front end sets the nose SHAPE (Cd); the reference DIAMETER is the
    widest body actually flying — normally the stage body, since an RV/payload
    rides atop a booster that is as wide or wider.  Using max(nose, stage)
    keeps the area correct during lower-stage burn (the fat booster, not the
    little RV, is what plows through the dense air) and also covers the rare
    case of an RV flared wider than its final stage.  When the diameters are
    equal — the usual nose-caps-body case — the choice is moot.

    The "warhead does not separate" case is handled by effective_ro(): a
    body-mode RV (separation_mode='body') inherits the body's own diameter, so
    the front end is the full body width rather than a narrower notional RV.
    The RV nose is the front end whether or not it later separates —
    separation happens at/after burnout, so it does not affect boost geometry.

    Deliberately omitted: slim-forebody "shielding" (a slender RV/payload on a
    wider body creating a shock the base rides in, the way our aerospike model
    reduces a blunt body's wave drag).  It is real physics, but for a launch
    where the RV is shrouded through the dense atmosphere and only exposed at
    high altitude (low q), the effect was measured at ~0.01% of burnout speed
    for the Minotaur-IV + HTV-2 case — two-to-three orders of magnitude below
    ordinary propulsion (~3%) and glide-model (~3%) error.  Treating the
    widest diameter as an unshielded nose is therefore close enough; the
    shielding term would only matter for an unshrouded slim body exposed in
    dense air, a different vehicle class.
    """
    if (top_params is not None
            and top_params.shroud_diameter_m > 0
            and altitude_m is not None
            and not _shroud_jettisoned(top_params, altitude_m)):
        return (top_params.shroud_nose_shape, top_params.shroud_diameter_m,
                top_params.shroud_nose_length_m, top_params.shroud_length_m, True)
    # Multi-object loadout: with no fairing (or after jettison) the exposed
    # front is a bus face carrying a cluster of RVs — a blunt cylinder, not a
    # single clean cone.  Keep the blunt/default nose drag rather than crediting
    # one RV's slender shape.  Conservative (more drag) exactly where it matters:
    # a low fairing-jettison altitude on a depressed trajectory, in thick air.
    # A single-object loadout (V-2 / Scud) IS a lone nose, so it keeps
    # the RV shape below.
    _multi = (top_params is not None and getattr(top_params, 'num_ros', 1) > 1)
    ro = effective_ro(top_params) if top_params is not None else None
    if ro is not None and ro.diameter_m > 0:
        _shape = 'blunt_cylinder' if _multi else ro.shape
        return (_shape, max(ro.diameter_m, params.diameter_m),
                ro.length_m, params.length_m, False)
    if top_params is not None and top_params.payload_diameter_m > 0:
        return (top_params.nose_shape,
                max(top_params.payload_diameter_m, params.diameter_m),
                top_params.nose_length_m, params.length_m, False)
    return (params.nose_shape, params.diameter_m,
            params.nose_length_m, params.length_m, False)


def booster_area(params: BoosterParams, altitude_m: float = None,
                 top_params: 'BoosterParams' = None) -> float:
    """Reference cross-sectional area (m^2) of the exposed front end.

    Tracks the same front-end body as the nose-shape drag model: the shroud
    while attached, otherwise the RV/payload nose (see _boost_front_geometry).
    """
    _, d, _, _, _ = _boost_front_geometry(top_params, params, altitude_m)
    if d <= 0:
        d = params.diameter_m
    return np.pi * (d / 2) ** 2


def drag_coefficient(params: BoosterParams, mach: float) -> float:
    """Cd interpolated from Mach table; falls back to Forden table if empty."""
    if params.mach_table:
        return float(np.interp(mach, params.mach_table, params.cd_table))
    return float(_lin_interp(mach, _FORDEN_MACH, _FORDEN_CD))


def _ro_nose_shape(p: BoosterParams) -> str:
    """RV nose shape: from params.ro when available, else deprecated inline field."""
    ro = effective_ro(p)
    return ro.shape if ro is not None else getattr(p, 'ro_shape', '')


def _ro_diameter(p: BoosterParams) -> float:
    ro = effective_ro(p)
    return ro.diameter_m if ro is not None else getattr(p, 'ro_diameter_m', 0.0)


def _ro_length(p: BoosterParams) -> float:
    ro = effective_ro(p)
    return ro.length_m if ro is not None else getattr(p, 'ro_length_m', 0.0)


def _flare_cd(d_aft: float, d_fwd: float, L: float, mach: float,
              A_ref: float) -> float:
    """Screening wave-drag increment (ref A_ref) of a single conical transition.

    A flare — the body WIDER at its aft (downstream) end than its forward end —
    presents a forward-facing conical surface to the nose-first flow, so it adds
    pressure drag: the cone-pressure coefficient at the flare half-angle
    (`_cd_wave_cone`, the same Chin primitive the nose and the biconic aft
    frustum use) times the frontal-area INCREASE, referenced to A_ref.  A
    boattail (narrower aft) or a same-diameter section returns 0 — conservative,
    and a boattail's small base-drag credit is below screening granularity.
    A near-zero length (a bare step) floors the fineness at 0.5 (blunt)."""
    import math
    r_aft, r_fwd = float(d_aft) / 2.0, float(d_fwd) / 2.0
    dA = math.pi * (r_aft * r_aft - r_fwd * r_fwd)
    if dA <= 0.0 or A_ref <= 0.0:
        return 0.0
    theta = math.atan((r_aft - r_fwd) / max(float(L), 1e-6))
    ld = 1.0 / (2.0 * math.tan(theta)) if theta > 1e-6 else 0.5
    return _cd_wave_cone(ld, mach) * (dA / A_ref)


def _transition_wave_drag(params: BoosterParams, active_stage: BoosterParams,
                          mach: float, A_ref: float) -> float:
    """Total flare wave-drag increment (ref A_ref) from the ATTACHED stack's
    conical stages and interstages (Phase 2 of the interstage/conical work,
    METHODS §6.7).  Walks from the active stage upward — stages below it have
    separated — and sums `_flare_cd` for each opt-in feature:

      * conical stage — frustum from `diameter_m` (base, aft) to
        `top_diameter_m` (top, forward); a flare when the base is wider.
      * interstage — frustum from this stage's top diameter (aft) to the next
        stage's base diameter (forward); a flare when this stage is fatter.

    Zero unless a stage sets `conical` or `has_interstage`, so a plain stack is
    byte-identical.  Lean by design: friction over the added wetted length is
    below the front-end drag model's granularity (it already counts only the
    front-end body), and contractions are not credited."""
    if A_ref <= 0.0:
        return 0.0
    total = 0.0
    s = active_stage
    while s is not None:
        if getattr(s, 'conical', False) and float(getattr(s, 'top_diameter_m', 0.0)) > 0.0:
            total += _flare_cd(s.diameter_m, s.top_diameter_m,
                               s.length_m, mach, A_ref)
        if (getattr(s, 'has_interstage', False)
                and float(getattr(s, 'interstage_length_m', 0.0)) > 0.0
                and s.stage2 is not None):
            d_aft = (s.top_diameter_m if (getattr(s, 'conical', False)
                                          and s.top_diameter_m > 0.0)
                     else s.diameter_m)
            total += _flare_cd(d_aft, s.stage2.diameter_m,
                               s.interstage_length_m, mach, A_ref)
        s = s.stage2
    return total


def drag_force_vector(params: BoosterParams, vel_ecef, altitude_m,
                      top_params: 'BoosterParams' = None,
                      t_s: float = None, powered: bool = False) -> np.ndarray:
    """
    Aerodynamic drag force vector (N) opposing velocity.

    Parameters
    ----------
    params     : BoosterParams (current stage)
    vel_ecef   : velocity vector in ECEF (m/s), shape (3,)
    altitude_m : scalar altitude (m)
    top_params : top-level BoosterParams (for shroud diameter lookup); optional
    t_s        : mission time (s); used for the grid-fin deployment schedule.
                 If None, all grid fins are treated as deployed.

    Returns
    -------
    F_drag : ndarray (3,) in Newtons (opposing velocity direction)
    """
    speed = np.linalg.norm(vel_ecef)
    if speed < 1e-6:
        return np.zeros(3)
    T, _, rho, a_sound = atmosphere(altitude_m)
    mach  = speed / a_sound
    mu    = _mu_air(T)
    L_ref = params.length_m if params.length_m > 0.0 else 1.0
    re_l  = rho * speed * L_ref / mu if mu > 0.0 else 5e6

    # Choose Cd source: decomposed nose-shape model or Forden mach_table.
    # The front-end body (shroud while attached, else RV/payload nose) sets
    # both the nose shape and the reference diameter — the same selector used
    # by booster_area() — so Cd and reference area always agree.
    _shape, _diam, _nose_len, _body_len, _is_shroud = _boost_front_geometry(
        top_params, params, altitude_m)
    if top_params is not None and _shape not in ('', 'forden') and _diam > 0:
        _ld = (_nose_len / _diam if _nose_len > 0 and _diam > 0 else 3.0)
        _ld_body = (_body_len / _diam if _body_len > 0 and _diam > 0 else None)
        # Power-on base bleed: while `params` (the active stage) is firing, its
        # plume fills the nozzle exit and suppresses the nozzle-covered share of
        # base drag.  Referenced to the stage's own aft area; 1.0 (no change)
        # when unpowered or no nozzle area stored.  Only the decomposed build-up
        # separates base drag — the Forden table (else branch below) bakes it in.
        _bar = base_bleed_ratio(params, params.diameter_m) if powered else 1.0
        if _is_shroud:
            cd = _cd_nose_shape(_shape, _ld, mach, re_l=re_l, ld_body=_ld_body,
                                aerospike_LD=top_params.aerospike_LD,
                                aerospike_dD=top_params.aerospike_dD,
                                base_area_ratio=_bar)
        else:
            # Aerospike is attached to the shroud, so it stops working once
            # the shroud is jettisoned — no aerospike effect on this branch.
            # Biconic front end (unshrouded body / bare RV): the exposed nose is
            # two cones, so the boost wave drag is the two-cone Chin form, not a
            # single cone.  biconic_nose_geometry is the SAME resolver the
            # reentry build-up and schematic use, so drawn == flown on ascent
            # too.  None (not a valid biconic) keeps the single-cone wave.
            _tp_ro = getattr(top_params, 'ro', None)
            _bic = (biconic_nose_geometry(top_params)
                    if (_tp_ro is not None and getattr(_tp_ro, 'biconic', False))
                    else None)
            _bic_arg = None
            if _bic is not None and float(_bic["break_diameter_m"]) > 0.0:
                _bic_arg = (_bic["fore_len_m"] / _bic["break_diameter_m"],
                            _bic["theta2_deg"], _bic["break_ratio"])
            cd = _cd_nose_shape(_shape, _ld, mach, re_l=re_l, ld_body=_ld_body,
                                base_area_ratio=_bar, biconic=_bic_arg)
    else:
        cd = drag_coefficient(params, mach)

    area = booster_area(params, altitude_m=altitude_m, top_params=top_params)
    # Interstage / conical flare wave drag (additive, ref same `area`): a
    # declared flare adds forward-facing pressure drag the front-end nose model
    # misses.  0 unless a stage opts into `conical`/`has_interstage`, so a plain
    # stack is byte-identical.  (METHODS §6.7 Phase 2.)
    cd += _transition_wave_drag(top_params if top_params is not None else params,
                                params, mach, area)
    q    = 0.5 * rho * speed**2
    drag_mag = cd * q * area

    # Grid (lattice) fins on the active stage — add their drag increment.
    # _cd_gridfins is referenced to the body base area π(d/2)², so multiply by
    # that same reference area (not the front-end `area`, which may be the
    # shroud/RV frontal area).
    if getattr(params, 'has_grid_fins', False) and params.n_grid_fins > 0:
        n_dep = grid_fins_deployed(
            params.n_grid_fins,
            getattr(params, 'grid_fin_deploy_schedule', None), t_s)
        if n_dep > 0:
            re_c = rho * speed * params.grid_fin_chord_m / mu if mu > 0.0 else 5e6
            cd_gf = _cd_gridfins(
                n_dep, params.grid_fin_width_m,
                params.grid_fin_height_m, params.grid_fin_chord_m,
                params.grid_fin_web_thickness_m, params.grid_fin_cell_pitch_m,
                params.diameter_m, mach, re_chord=re_c,
                edge_factor=getattr(params, 'grid_fin_edge_factor', 1.0),
                solidity=getattr(params, 'grid_fin_solidity', 0.0))
            a_base = np.pi * (params.diameter_m / 2.0) ** 2
            drag_mag += cd_gf * q * a_base

    # Planar fins on the active stage — add their drag increment.  Booster fins
    # (e.g. a finned first stage) plow through the dense lower atmosphere during
    # ascent and their drag matters for range; they jettison with their stage,
    # so gating on the active stage's has_fins is correct.  No lift is added:
    # an ascending vehicle flies at ~0 deg AoA, so the fins' normal force is a
    # stability effect (static margin), not a trajectory force.  _cd_fins is
    # referenced to the body base area, like the grid-fin term above.
    if getattr(params, 'has_fins', False) and params.n_fins > 0 \
            and params.fin_span_m > 0 and params.fin_root_chord_m > 0:
        cd_pf = _cd_fins(
            params.n_fins, params.fin_span_m, params.fin_root_chord_m,
            params.fin_tip_chord_m, params.fin_thickness_m, params.diameter_m,
            mach, re_l=re_l, sweep_deg=params.fin_sweep_deg)
        a_base = np.pi * (params.diameter_m / 2.0) ** 2
        drag_mag += cd_pf * q * a_base

    return -drag_mag * (vel_ecef / speed)


def _stage_chain_thrust(params: BoosterParams, t: float, altitude_m: float,
                        thrust_dir: np.ndarray) -> np.ndarray:
    """Thrust from the stage chain only (excludes strap-on boosters)."""
    if t < 0:
        return np.zeros(3)
    t_rem, s = t, params
    while s is not None:
        if t_rem <= s.burn_time_s:
            if t_rem > _eff_burn(s):
                return np.zeros(3)   # engine cut early — dead-coasting the tail
            _, P_amb, _, _ = atmosphere(altitude_m)
            if s.grain_type or s.thrust_profile:
                T_peak = s.thrust_peak_N if s.thrust_peak_N > 0.0 else s.thrust_N
                t_frac = t_rem / s.burn_time_s if s.burn_time_s > 0.0 else 0.0
                frac   = _instantaneous_thrust_frac(
                    s.grain_type, t_frac,
                    s.thrust_profile if s.thrust_profile else None)
                T_vac = T_peak * frac
            else:
                T_vac = s.thrust_N
            if s.nozzle_exit_area_m2 > 0:
                thrust_mag = max(0.0, T_vac - P_amb * s.nozzle_exit_area_m2)
            else:
                thrust_mag = T_vac * (1.0 - 0.02 * (P_amb / 101325.0))
            return thrust_mag * thrust_dir
        t_rem -= s.burn_time_s
        if s.stage2 is None:
            return np.zeros(3)
        if t_rem <= s.coast_time_s:
            return np.zeros(3)
        t_rem -= s.coast_time_s
        s      = s.stage2
    return np.zeros(3)


def thrust_force(params: BoosterParams, t: float, altitude_m: float,
                 thrust_dir: np.ndarray) -> np.ndarray:
    """
    Thrust force vector (N).  Handles N stages and strap-on boosters.

    Parameters
    ----------
    params     : BoosterParams (stage-1 node of the linked list)
    t          : time since launch (s)
    altitude_m : current altitude for ambient pressure correction
    thrust_dir : unit vector in direction of thrust (ECEF)

    Returns
    -------
    F_thrust : ndarray (3,) Newtons
    """
    # Stage chain only fires after booster_core_delay_s has elapsed.
    t_chain = t - params.booster_core_delay_s
    f = (_stage_chain_thrust(params, t_chain, altitude_m, thrust_dir)
         if t_chain >= 0 else np.zeros(3))

    # Add strap-on booster thrust while boosters are burning
    n, t_b = params.n_boosters, params.booster_burn_time_s
    if n > 0 and t_b > 0 and 0.0 <= t <= t_b:
        _, P_amb, _, _ = atmosphere(altitude_m)
        T_vac = params.booster_thrust_n
        if params.booster_nozzle_area_m2 > 0:
            T_mag = max(0.0, T_vac - P_amb * params.booster_nozzle_area_m2)
        else:
            T_mag = T_vac * (1.0 - 0.02 * (P_amb / 101325.0))
        f = f + n * T_mag * thrust_dir

    return f


def booster_drag_vector(top_params: BoosterParams, vel_ecef: np.ndarray,
                        altitude_m: float) -> np.ndarray:
    """
    Aerodynamic drag force (N) from the strap-on booster pack.

    Returns a zero vector when n_boosters == 0, booster_diam_m == 0, or
    speed is negligible.  Callers must gate by time: only invoke while
    t <= top_params.booster_burn_time_s.
    """
    n = top_params.n_boosters
    d = top_params.booster_diam_m
    if n <= 0 or d <= 0:
        return np.zeros(3)
    speed = np.linalg.norm(vel_ecef)
    if speed < 1e-6:
        return np.zeros(3)
    _, _, rho, _ = atmosphere(altitude_m)
    q        = 0.5 * rho * speed ** 2
    A_total  = n * np.pi * (d / 2.0) ** 2
    drag_mag = top_params.booster_cd * q * A_total
    return -drag_mag * (vel_ecef / speed)


# ---------------------------------------------------------------------------
# Booster library — shipped boosters live as data files (booster_library/
# *.booster.json), the same pattern as the reentry-object library.  The files
# are loaded here and overlaid onto BOOSTER_DB; the builder functions above
# remain as a fallback if a file is missing or fails to load.  Writers emit
# the new file form; the migration keeps builders authoritative until the
# file path is proven equivalent.
# ---------------------------------------------------------------------------
import glob as _glob
import json as _json
from pathlib import Path as _Path

_BUNDLED_BOOSTER_LIB = _Path(__file__).resolve().parent / "booster_library"


def load_booster_library(extra_dirs=()) -> int:
    """Overlay booster_library/*.booster.json onto BOOSTER_DB.

    Bundled files load first; any extra dirs (e.g. the user's writable
    library) override same-name entries.  Returns the number of files loaded.
    Never raises: a bad file is logged and skipped so the app still starts.
    """
    dirs = [_BUNDLED_BOOSTER_LIB, *[_Path(d) for d in extra_dirs]]
    n = 0
    for d in dirs:
        if not d.exists():
            continue
        for fp in sorted(d.glob("*.booster.json")):
            try:
                p = booster_from_dict(_json.loads(fp.read_text()))
                key = p.name or fp.name.replace(".booster.json", "")
                BOOSTER_DB[key] = (lambda _p=p: _p)
                n += 1
            except Exception as exc:   # pragma: no cover
                print(f"Warning: could not load booster '{fp.name}': {exc}")
    return n


load_booster_library()


# ---------------------------------------------------------------------------
# Flight plans — the "how it's flown" half of a booster,
# kept separate from the "what it is" hardware.  A flight plan carries the
# guidance mode, burnout/launch angles, and the per-stage pitch / yaw / coast /
# cutoff schedule.  Shipped as flight_plans/*.flightplan.json, applied onto a
# booster at run time.  Booster files stay hardware-only.
# ---------------------------------------------------------------------------
_FLIGHT_PLAN_TOP_KEYS = ('guidance', 'burnout_angle_deg', 'loft_angle_rate_deg_s',
                      'launch_elevation_deg',
                      # Subsystem-deployment timing read from the root booster:
                      # when the payload shroud is jettisoned (altitude, or <=0
                      # for the heating-flux default) and when spent strap-on
                      # boosters separate.  Both are flight decisions, not
                      # hardware, so they live in the flight plan.  Likewise
                      # the strap-on core ignition delay: when the core lights
                      # relative to the strap-ons is a flight decision.
                      'shroud_jettison_alt_km', 'booster_jettison_s',
                      'booster_core_delay_s')
# Run-time loadout record written by compose_loadout; omitted from the
# hardware-only booster file (the reentry object owns its mass).
_RUN_LOADOUT_KEYS = ('payload_kg', 'num_ros')
_FLIGHT_PLAN_STAGE_KEYS = ('stage_turn_start_s', 'stage_turn_stop_s',
                        'stage_burnout_angle_deg', 'coast_time_s', 'stage_cutoff_s',
                        'stage_yaw_start_s', 'stage_yaw_stop_s', 'stage_yaw_final_az_deg',
                        # Grid-fin deployment schedule is read per active stage
                        # (drag_force_vector receives the current stage), so it is
                        # a per-stage flight-plan field.
                        'grid_fin_deploy_schedule',
                        # Interstage jettison time: WHEN the adapter drops is a
                        # flight decision (the adapter's mass/length are hardware).
                        'interstage_jettison_s')


def extract_flight_plan(p: BoosterParams) -> dict:
    """Pull the flight plan (guidance) out of a booster into a plain dict."""
    stages = []
    s = p
    while s is not None:
        stages.append({k: getattr(s, k) for k in _FLIGHT_PLAN_STAGE_KEYS})
        s = s.stage2
    fp = {k: getattr(p, k) for k in _FLIGHT_PLAN_TOP_KEYS}
    fp['stages'] = stages
    return fp


def apply_flight_plan(p: BoosterParams, fp: dict) -> BoosterParams:
    """Return a copy of booster `p` with flight plan `fp` stamped onto it.

    Top-level guidance fields and the per-stage schedule are set from `fp`;
    hardware is untouched.  Missing keys leave the booster's own value in place.
    """
    import copy as _copy
    q = _copy.deepcopy(p)
    for k in _FLIGHT_PLAN_TOP_KEYS:
        if k in fp:
            setattr(q, k, fp[k])
    node = q
    for st in fp.get('stages', []):
        if node is None:
            break
        for k in _FLIGHT_PLAN_STAGE_KEYS:
            if k in st:
                setattr(node, k, st[k])
        node = node.stage2
    return q


_BUNDLED_FLIGHT_PLANS = _Path(__file__).resolve().parent / "flight_plans"

# Extra directories (highest precedence last) searched for user flight plans,
# e.g. the GUI's writable ~/Documents/Thrusty/flight_plans.  A user file is
# merged *over* the bundled plan per key, so a user booster save can override
# just the fields it owns (subsystem-deployment timing) without discarding the
# shipped guidance.  Empty by default so headless/library use only sees the
# bundled plans.
USER_FLIGHT_PLAN_DIRS: list = []


def _merge_flight_plans(base: dict, over: dict) -> dict:
    """Overlay flight plan ``over`` onto ``base``, per key and per stage."""
    out = {k: v for k, v in base.items() if k != 'stages'}
    for k, v in over.items():
        if k != 'stages':
            out[k] = v
    stages = [dict(s) for s in base.get('stages', [])]
    for i, ost in enumerate(over.get('stages', [])):
        if i < len(stages):
            stages[i].update(ost)
        else:
            stages.append(dict(ost))
    if stages or 'stages' in base or 'stages' in over:
        out['stages'] = stages
    return out


# Sentinel label for the booster-named default plan (undeletable; the file
# named after the booster itself).
DEFAULT_PLAN_LABEL = "(default)"

# Reserved variant name for the auto-generated maximum-range plan.  The GUI's
# Max Range button writes its optimised (burnout angle, turn-stop) here instead
# of mutating the active plan, so the user can toggle between "as flown" and
# "as optimised".  Regenerated on every Max Range run; users cannot hand-create
# a plan with this name.  The optimum depends on launch site / azimuth / reentry
# object, so the file stamps that context into its notes.
MAX_RANGE_PLAN_LABEL = "max-range"

# Reserved variant name for the auto-generated orbital-insertion plan.  The
# GUI's Plan Orbit button solves the two-phase boost program for a target
# orbit altitude and writes it here (same generator-not-editor contract as
# Max Range): regenerated on every run, launch context stamped in the notes.
ORBITAL_PLAN_LABEL = "orbital"

# Reserved variant name for a loaded scenario whose guidance law differs from
# the active plan's.  A scenario is a full-state bundle (booster + reentry
# object + site + guidance); rather than silently rewriting the active plan's
# law via write-through, a law-changing scenario is isolated into this slot.
SCENARIO_PLAN_LABEL = "scenario"

# All reserved (auto-generated / non-user-creatable) plan names.
RESERVED_PLAN_NAMES = frozenset({
    DEFAULT_PLAN_LABEL, MAX_RANGE_PLAN_LABEL, ORBITAL_PLAN_LABEL,
    SCENARIO_PLAN_LABEL})

# Active named flight plan per booster, set by the GUI (booster name -> plan
# name).  Consulted by get_booster when no explicit plan is passed; headless
# callers that never populate it always get the default plan.
ACTIVE_FLIGHT_PLANS: dict = {}


def load_flight_plan(name: str, extra_dirs=(), plan: str = None):
    """Load a booster's flight plan; None if none found.

    With ``plan=None``, loads the (default) plan: bundled directory first, then
    each of ``extra_dirs`` in order, merging each file found over the
    accumulated plan (later dirs win) — a user file need only carry the fields
    it overrides.  With a ``plan`` name, loads that named variant the same way.
    """
    from pathlib import Path as _P
    fname = flight_plan_filename(name, plan)
    result = None
    for d in [_BUNDLED_FLIGHT_PLANS, *[_P(x) for x in extra_dirs]]:
        fp = d / fname
        if fp.exists():
            try:
                data = _json.loads(fp.read_text())
            except Exception:
                continue
            result = data if result is None else _merge_flight_plans(result, data)
    return result


def flight_plan_filename(name: str, plan: str = None) -> str:
    """Canonical flight-plan filename: booster-named for the default plan,
    ``<booster>__<plan>.flightplan.json`` for a named variant."""
    if plan and plan != DEFAULT_PLAN_LABEL:
        return f"{_re_safe(name)}__{_re_safe(plan)}.flightplan.json"
    return f"{_re_safe(name)}.flightplan.json"


def list_flight_plans(name: str, extra_dirs=()) -> list:
    """Names of the flight plans available for booster ``name``.

    Always starts with DEFAULT_PLAN_LABEL; named variants follow in sorted
    order, discovered in the bundled dir and ``extra_dirs`` by the
    ``<booster>__<plan>.flightplan.json`` naming convention.
    """
    from pathlib import Path as _P
    prefix = f"{_re_safe(name)}__"
    suffix = ".flightplan.json"
    plans = set()
    for d in [_BUNDLED_FLIGHT_PLANS, *[_P(x) for x in extra_dirs]]:
        if not d.exists():
            continue
        for fp in d.glob(f"{prefix}*{suffix}"):
            token = fp.name[len(prefix):-len(suffix)]
            if not token:
                continue
            try:
                data = _json.loads(fp.read_text())
                label = str(data.get('name', '')) or token
            except Exception:
                label = token
            plans.add(label)
    return [DEFAULT_PLAN_LABEL, *sorted(plans)]


def save_flight_plan(name: str, fp: dict, out_dir, plan: str = None) -> str:
    """Write flight plan ``fp`` for booster ``name`` into ``out_dir``.

    ``plan`` names a variant (stamped into the file as ``name``/``booster``
    metadata so the file is self-describing); None writes the default plan.
    Returns the path.  ``fp`` is typically from :func:`extract_flight_plan`.
    """
    from pathlib import Path as _P
    d = _P(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    if plan and plan != DEFAULT_PLAN_LABEL:
        fp = {**fp, 'name': plan, 'booster': name}
    path = d / flight_plan_filename(name, plan)
    path.write_text(_json.dumps(fp, indent=2) + "\n")
    return str(path)


def _re_safe(s: str, maxlen: int = 60) -> str:
    import re as _re
    s = _re.sub(r'\s+', '_', (s or '').strip())
    s = _re.sub(r'[^\w\-]', '-', s)
    return s[:maxlen] or 'booster'


# ---------------------------------------------------------------------------
# Reentry plans — the "how it's flown" half of a reentry object, the down-leg
# analogue of the flight plan.  A reentry object owns *what it is* (shape, beta,
# mass, TPS, and its max L/D capability); the reentry plan owns *how it flies the
# reentry* — glide mode, commanded L/D (capped at capability), turns, pull-ups,
# dives, and whether it separates.  Shipped as reentry_plans/*.reentryplan.json
# and applied onto a reentry object at run time; reentry-object files stay
# hardware-only.  The schema is deliberately open (schedules are list-valued) so
# cross-range S-turns, multi-phase pull-ups, and waypoints can be added as new
# keys without a format change; apply_reentry_plan ignores keys it does not
# know.  Reserved for later (no format change needed when they land):
#   'deployment' — post-boost bus/PBV dispense: a separation *time* (today
#                  separation is pinned to last-stage burnout) and, eventually,
#                  per-object aimpoints so the bus can deploy multiple reentry
#                  objects rather than carry one as dead mass.
_REENTRY_PLAN_KEYS = (
    'glider_enabled', 'glider_guidance', 'glider_pullup_g_max',
    'glider_terminal_dive', 'glider_terminal_alt_km', 'glider_bank_schedule',
    'glider_dive_target_lat_deg', 'glider_dive_target_lon_deg',
    'glider_dive_target_radius_km',
    'glider_skip_count', 'glider_damping_zeta', 'glider_flap_deflection_deg',
    'glider_pullup_start_alt_km',
    'glider_aero_model', 'reentry_attitude',
    # NOTE: separation_mode is NOT a plan key.  The booster↔object link is the
    # booster's body_reenters flag (run_separation_mode); a legacy plan file
    # that still carries separation_mode is ignored on apply.
)


def extract_reentry_plan(ro: ROParams) -> dict:
    """Pull the reentry plan out of a reentry object into a plain dict.

    ``commanded_LD`` defaults to the vehicle's full L/D capability, so applying
    the extracted plan is a no-op; lowering it later flies the vehicle worse.
    """
    rp = {k: getattr(ro, k) for k in _REENTRY_PLAN_KEYS}
    rp['commanded_LD'] = ro.glider_LD
    return rp


def apply_reentry_plan(ro: ROParams, rp: dict) -> ROParams:
    """Return a copy of reentry object ``ro`` with reentry plan ``rp`` applied.

    Plan fields are stamped onto the copy; hardware (shape/beta/mass/TPS and the
    ``glider_LD`` capability) is untouched.  The commanded L/D is clamped to the
    vehicle's capability so a plan can only fly it worse, never beyond its
    aerodynamic limit.  Missing keys leave the object's own value in place.
    """
    import copy as _copy
    q = _copy.deepcopy(ro)
    for k in _REENTRY_PLAN_KEYS:
        if k in rp:
            setattr(q, k, rp[k])
    # Plan files bypass ro_from_dict, so legacy separation tokens and retired
    # glide modes are normalised here too ('non_separating' -> 'body';
    # 'skip_to_equilibrium' -> 'damped_glide').
    q.separation_mode = _norm_sep_mode(q.separation_mode)
    q.glider_guidance = _norm_glide_mode(q.glider_guidance)
    # Intent is clamped by capability: only a maneuvering object can glide.
    q.glider_enabled = bool(q.glider_enabled) and bool(getattr(ro, 'maneuvering', False))
    cmd = rp.get('commanded_LD')
    if cmd is not None:
        q.glider_LD = min(float(cmd), ro.glider_LD)  # fly it worse, never better
    # The commanded pull-up g is likewise clamped to the airframe's structural
    # limit (hardware, on the object): a plan can ask for less, never more.
    # An unset limit (0) is unlimited — no clamp.
    _lim = float(getattr(ro, 'pullup_g_limit', 0.0) or 0.0)
    if _lim > 0:
        q.glider_pullup_g_max = min(float(q.glider_pullup_g_max), _lim)
    return q


_BUNDLED_REENTRY_PLANS = _Path(__file__).resolve().parent / "reentry_plans"
# Extra dirs (highest precedence last) for user reentry plans; merged over the
# bundled plan per key, mirroring USER_FLIGHT_PLAN_DIRS.
USER_REENTRY_PLAN_DIRS: list = []


def reentry_plan_filename(name: str, plan: str = None) -> str:
    """Canonical reentry-plan filename: object-named for the default plan,
    ``<object>__<plan>.reentryplan.json`` for a named variant (mirrors
    :func:`flight_plan_filename`)."""
    if plan and plan != DEFAULT_PLAN_LABEL:
        return f"{_re_safe(name)}__{_re_safe(plan)}.reentryplan.json"
    return f"{_re_safe(name)}.reentryplan.json"


# Active named reentry plan per reentry object (object name -> plan name), set
# by the GUI; consulted when RO_DB is (re)built and by the write-through path.
ACTIVE_REENTRY_PLANS: dict = {}


def list_reentry_plans(name: str, extra_dirs=()) -> list:
    """Names of the reentry plans available for reentry object ``name``.

    Always starts with DEFAULT_PLAN_LABEL; named variants follow in sorted
    order, discovered by the ``<object>__<plan>.reentryplan.json`` convention."""
    from pathlib import Path as _P
    prefix = f"{_re_safe(name)}__"
    suffix = ".reentryplan.json"
    plans = set()
    for d in [_BUNDLED_REENTRY_PLANS, *[_P(x) for x in extra_dirs]]:
        if not d.exists():
            continue
        for fp in d.glob(f"{prefix}*{suffix}"):
            token = fp.name[len(prefix):-len(suffix)]
            if not token:
                continue
            try:
                data = _json.loads(fp.read_text())
                label = str(data.get('name', '')) or token
            except Exception:
                label = token
            plans.add(label)
    return [DEFAULT_PLAN_LABEL, *sorted(plans)]


def load_reentry_plan(name: str, extra_dirs=(), plan: str = None):
    """Load a reentry object's plan by name; None if none found.

    With ``plan=None`` loads the (default) plan: bundled dir first, then each of
    ``extra_dirs`` merged over it (later wins), so a user plan need only carry
    the fields it overrides.  With a ``plan`` name, the named variant is merged
    ON TOP of the default (a variant carries only its diffs), mirroring
    :func:`load_flight_plan`.
    """
    from pathlib import Path as _P

    def _merge_dirs(fname):
        result = None
        for d in [_BUNDLED_REENTRY_PLANS, *[_P(x) for x in extra_dirs]]:
            fp = d / fname
            if fp.exists():
                try:
                    data = _json.loads(fp.read_text())
                except Exception:
                    continue
                result = data if result is None else {**result, **data}
        return result

    base = _merge_dirs(reentry_plan_filename(name))
    if plan and plan != DEFAULT_PLAN_LABEL:
        variant = _merge_dirs(reentry_plan_filename(name, plan))
        if variant is not None:
            return {**(base or {}), **variant}
    return base


def save_reentry_plan(name: str, rp: dict, out_dir, plan: str = None) -> str:
    """Write reentry plan ``rp`` for ``name`` into ``out_dir``; return the path.

    ``plan`` names a variant (stamped into the file so it is self-describing);
    None writes the default plan."""
    from pathlib import Path as _P
    d = _P(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    if plan and plan != DEFAULT_PLAN_LABEL:
        rp = {**rp, 'name': plan, 'reentry_object': name}
    path = d / reentry_plan_filename(name, plan)
    path.write_text(_json.dumps(rp, indent=2) + "\n")
    return str(path)
