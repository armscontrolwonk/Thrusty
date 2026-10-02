# Thrusty — Booster & Reentry Trajectory Simulator

Thrusty is a 3-DOF trajectory and reentry-survivability tool for **boosters**
(things that go up) and **reentry objects** (things that come down), implemented
as a Python/Tkinter desktop application. It is usage-neutral: the same models
serve ballistic missiles, space launch vehicles, sounding rockets, and reentry
bodies.

It is modelled after Geoffrey Forden's MATLAB tool
(*Simulating the Operation of Ballistic Missiles*, Science & Global Security, 2007);
the design was inferred from that program's file structure and the paper, and
the code written independently (see *Lineage* in [`NOTICE.md`](NOTICE.md)).
The integrator reproduces Forden's Table 3 maximum-range figures for the classic
SRBM/MRBM set (Scud-B, Al Hussein, No-dong, Taepodong-I). No vehicle is defined
in code: every booster, reentry object and launch site the pickers offer is
read from a file (`booster_library/`, `ro_library/`, `launch_sites.json`, plus
the user's `~/Documents/Thrusty/` libraries). The boosters shipped (see
[Built-in boosters](#built-in-boosters)) focus on reentry / hypersonic-glide
testbeds.

For the full technical reference — governing equations, algorithms, and primary
citations for every model — see [`METHODS.md`](METHODS.md).
For the record of values and citations that were caught and corrected during
development, see [`PROVENANCE.md`](PROVENANCE.md).

---

## How Thrusty models a flight

A flight has three phases, and each is governed by a **different set of inputs**:

1. **Boost (up)** — powered ascent. Governed by the booster's **shape**
   (drag: nose shape, shroud, fins, reference area), its **motor** (thrust, Isp,
   burn time, grain profile), and its **trajectory** (the guidance *flight plan*:
   launch elevation, pitch / gravity-turn schedule, staging). This is the only
   phase with control inputs.

2. **Midcourse (coast)** — the ballistic or orbital arc above the sensible
   atmosphere. Pure physics: once the booster burns out, the arc is fixed by the
   burnout **state** (speed, flight-path angle, position) under gravity alone —
   drag is zeroed above 120 km. No further input.

3. **Reentry (down)** — atmospheric descent of the reentry object. Governed by
   its **ballistic coefficient β** and, if it maneuvers, its **lift-to-drag L/D**,
   plus the aerothermal parameters (heating, TPS) that decide survival.

The same physical drag is modelled **two ways**, matching what you actually know
in each phase: **shape-resolved `Cd·A` on the way up** (you have the geometry),
**lumped `β = m/(Cd·A)` on the way down** (you characterise the object by one
number). So: boost is *hardware + flight plan*, midcourse is *physics*, reentry is
the *reentry object's own hardware*. Guidance and coast are flight-plan choices,
never booster hardware.

### Flight plans are named, switchable artifacts

A booster can fly many flight plans. Each is a file (`<booster>.flightplan.json`
for the default, `<booster>__<name>.flightplan.json` for a named variant), and
the **Flight Plan** dropdown switches between them. The sidebar and the Flight
Plan dialog are two views of the *same* active plan; **running a trajectory
writes the panel through to that plan file** ("the plan you fly is the plan on
disk"), and *Reset trajectory to defaults* reverts to the shipped default.

**The guidance law is the plan's identity.** When you create a plan (New) you
name it *and* choose its law — pitch program, gravity turn, or orbital
insertion — and that law is fixed for the life of the plan. Neither the sidebar
Mode selector nor the editor can change it; they only toggle **Simple vs.
Advanced pitch**, which is the same pitch-program law with per-stage overrides,
not a different law. Switching laws means switching (or creating) a plan — an
"orbital insertion plan" and a "max-range pitch plan" are different artifacts,
not two states of one. New seeds the non-law fields (launch elevation,
deployment events, yaw program) from the active plan, so choosing a new law
never means re-entering the fairing altitude.

**The optimisers are generators, not editors.** Neither Max Range nor Plan
Orbit ever edits the plan you loaded; each writes its result to a reserved
variant and switches to it, leaving your plan one dropdown click away for A/B
toggling:

- **Max Range → `max-range`**: sweeps burnout angle and turn-stop (full
  trajectory integrations) under the active plan's law. Refused on
  Advanced-pitch plans (per-stage angles mask the swept globals — switch to
  Simple) and on orbital plans (that goal belongs to Plan Orbit).
- **Plan Orbit → `orbital`**: solves the two-phase boost program for the
  target orbit altitude; available when an orbital-insertion plan is active.

Both reserved variants are scratch artifacts: regenerated on every run, launch
context (site, azimuth, reentry object / target altitude) stamped into their
notes — because the optimum shifts with all of it — and never worth
hand-curating. The names `max-range`, `orbital`, and `scenario` are reserved.
An imported flight plan (File ▸ Load Flight Plan) always lands as a **new named
variant** rather than overwriting the active plan — an imported plan carries its
own law, and the law is identity. A loaded **scenario** whose guidance law
differs from the active plan is likewise isolated into the reserved `scenario`
variant, so restoring a bundle never silently rewrites a curated plan's law.

### Reentry plans mirror flight plans

The down-leg has the same single-store model, **including named variants**. A
reentry object's **hardware** (mass, β, shape, TPS, L/D capability) lives in its
`.ro.json`; **how it is flown** — glide law, commanded L/D, ζ damping, skip
count, bank schedule, terminal-dive altitude, dive-at-target, separation mode,
reentry attitude (trim vs. tumbling) — lives in a `.reentryplan.json` (object-named for the default,
`<object>__<name>.reentryplan.json` for a variant that carries only its diffs).
The **Reentry Plan** dropdown in the sidebar switches between an object's plans
(default plus New/Edit…/Delete variants), mirroring the Flight Plan dropdown —
the dropdown sits above its own New/Edit…/Delete row, like every other library
section. The glider controls below it are the live strip editor for the quick
run-to-run picks (glide law, separation, terminal-dive altitude, aero model,
skip count); **Edit…** opens the full Reentry Plan dialog for the tuning fields
(commanded L/D, pull-up g, flap, reentry attitude, ζ damping with its
estimator, bank schedule, dive-at-target, provenance). **Running
writes the strip through to the active plan**, and selecting the object or a
variant repopulates from it, so a dive-altitude tweak (or a switch to Ballistic)
survives switching boosters and sessions. The airframe's **L/D capability** is
hardware (object editor); the plan's **commanded L/D** is clamped to it — a plan
can fly an object *worse* than its hardware allows, never better. The active
variant per object is remembered in
`~/.gui_missile_flyout/active_reentry_plans.json`.

---

## Source files

| File | Lines | Purpose |
|---|---|---|
| `thrusty.py` | ~16 000 | GUI application — all Tkinter widgets, dialogs, plotting, export. Holds no physics: every number it shows comes from the modules below |
| `trajectory.py` | ~3 460 | 3-DOF integrator, guidance laws, range optimiser, orbital planner, reentry glide |
| `booster_models.py` | ~3 260 | `BoosterParams` + `ROParams` dataclasses, drag, thrust, mass, staging, grain profiles |
| `heating.py` | ~610 | Reentry aerothermal screening (Sutton-Graves flux, radiative-equilibrium wall temp) + TPS material catalog |
| `heating_locations.py` | ~300 | Engineering-tier convective heating per location (nose cap, leading edge, windward face; Tauber NASA TP-2914) with a radiating-wall energy balance. Not yet wired into the verdicts |
| `heating_solid.py` | ~190 | One-dimensional transient conduction in a solid conical tip, for sharp solid parts where a radiating-wall balance is invalid. Not yet wired into the verdicts |
| `heating_by_location.py` | ~410 | Heating at the places a reentry object's file lists (`heating_locations`): resolves each place's numbers from the object's own fields, names any that are missing, and evaluates the relations above. Not yet wired into the verdicts |
| `glider_ld.py` | ~275 | Geometry-derived L/D for non-separating reentry objects (Missile-DATCOM-style build-up) |
| `grid_fin_sizing.py` | ~350 | Barrowman static-margin / centre-of-pressure sizing for finned boosters |
| `trim_gate.py` | ~160 | Trim/control gate — is a derived L/D actually achievable? |
| `coordinates.py` | ~240 | WGS-84 coordinate conversions, Vincenty geodesic, Coriolis/centrifugal, great-circle bearing and Earth-rotation-corrected aiming |
| `spent_stage_aero.py` | ~300 | Drag of a spent stage after separation, as C_D·A against Mach by attitude: random tumbling and end over end from Jernell's flat-ended cylinder blended to Klett's Newtonian cylinder, and the trim where the measured centre of pressure meets the empty centre of gravity. `trajectory._fly_band` flies a stage end over end to apogee, then at both ends of its trim-to-tumbling band, and reports the midpoint |
| `stage_outline.py` | ~170 | The one outline of a spent stage or strap-on (own nose, aft skirt, protruding nozzle) as radius against distance from the front. The schematic and the 3-D export draw it, the spent-stage model integrates it, strap-on ascent drag is built from it: drawn ≡ flown. Pure geometry |
| `analysis.py` | ~330 | Sweep drivers (range ring, parametric sweep, bank-angle footprint) and result post-processing (impact point, derived Mach/q, footprint envelope) — the computation the dialogs used to do inline; the GUI only orchestrates |
| `atmosphere.py` | ~355 | NRLMSISE-00 (default) / US Std Atm 1976 (fallback), 0–1000 km, dynamic pressure |
| `gravity.py` | ~62 | WGS-84 J2 gravity vector in ECEF |
| `slv_performance.py` | ~287 | Algebraic payload-to-orbit estimation (Schilling) |
| `booster_schematic.py` | ~210 | To-scale side elevation of the stack (Schematic tab renderer); pure matplotlib, data-honest fallback flags |
| `mass_estimator.py` | ~1 260 | Stage dry-mass estimator (Wilhite-school MERs + aggregate relations); divergence cross-check. See `MASS_ESTIMATOR.md` |
| `booster_xlsx.py` / `ro_xlsx.py` | ~740 / ~320 | Spreadsheet (XLSX) import/export for boosters and reentry objects |
| `gazetteer.py` | ~560 | Bundled offline gazetteer (10.4 M official BGN-lineage names): variant-aware search, nearest-populated / nearest-any lookups (Nearby Places report), sampled viewport queries (Gazetteer Explorer) |

`trajectory.py` glide modes model reentry as a **phugoid-damping spectrum**:
skip-glide (undamped, ζ=0) → damped-phugoid glide (ζ≈0.7) → non-oscillatory glide /
Acton (ζ→∞); plus equilibrium-glide (Tracy) and skip→equilibrium for comparison.
See `DAMPED_GLIDE.md` (implementation) and `DAMPED_GLIDE_MEMO.md` (approach,
citations, Acton comparison).

---

## Quick start

```
pip install -r requirements.txt            # core: numpy, scipy, matplotlib, Pillow
pip install -r requirements-optional.txt   # optional features (see that file)
python thrusty.py
```

The core set is all the app needs to run trajectories, plots, and the
schematic.  Each optional package unlocks one feature and the app degrades
gracefully without it (online place search → geopy, map picker → cartopy,
HTML maps → folium, spreadsheet I/O → openpyxl, image drag-and-drop →
tkinterdnd2).  The offline place gazetteer needs no extra package.

User data is stored in `~/.gui_missile_flyout/` (the app config folder name is
kept for back-compatibility):

| File | Contents |
|---|---|
| `custom_boosters.json` | User-defined booster definitions (legacy `custom_missiles.json` is still read) |
| `custom_sites.json` | User-defined launch sites |
| `trajectory_profiles.json` | Per-booster guidance settings (loft angle, turn schedule, etc.) |

Reentry objects are stored as a first-class library in `ro_library/*.ro.json`
(shipped defaults next to the code; user-saved objects under
`~/Documents/Thrusty/ro_library/`). Legacy `rv_library/*.rv.json` files are still
read. How each object is *flown* is stored separately in
`~/Documents/Thrusty/reentry_plans/*.reentryplan.json` (the down-leg analogue of
`flight_plans/*.flightplan.json`), written through from the sidebar on every run.
Flight-plan variants live in `~/Documents/Thrusty/flight_plans/`, and the active
variant per booster in `~/.gui_missile_flyout/active_flight_plans.json`.

**Reading old files.** Every file vintage Thrusty has accepted is understood
in one place per kind: `upgrade_booster_dict` and `upgrade_ro_dict` convert a
dict of any age to the current schema (stamped `schema`), and
`booster_from_dict` / `ro_from_dict` then read the current schema and nothing
else. A new compatibility rule goes in the upgrader, never in a constructor.
`test_legacy_upgrade.py` pins the behaviour: `legacy_corpus.py` holds one dict
per historical shape, and `tests_data/legacy_load_golden.json` records what
each loaded to before the rule moved, so a conversion cannot drift silently.

These are the **four inputs**, kept apart: two hardware files (booster, reentry
object) and two plan files (flight plan, reentry plan). A hardware file stores
no plan key and a plan file stores no hardware key; timings (fairing and
strap-on drop, interstage jettison, core ignition delay, grid-fin deployment)
are flight-plan data even though the thing that moves is hardware. Booster
files are stack-only: the reentry object owns its mass, and a flight plan may
name the object it flies (`reentry_object`) — plan data, not a hardware link.
The sidebar picks it up when nothing else is selected, `get_booster` attaches
it for headless runs, and `integrate_trajectory` composes an object onto a
chain that was not composed already, so a run with an object always carries
its mass. Where hardware and plan meet, the plan is clamped by the hardware:
commanded L/D ≤ airframe L/D, commanded g ≤ structural limit, and a glide is
flown only if the object is `maneuvering`. The only link
between a booster and a reentry object is the booster's `body_reenters` flag.
`test_input_split.py` holds the rule over the shipped files and the
serialisers.

---

## User interface

The window is split into a scrollable **left control panel** and a **right
tabbed notebook**.

### Left control panel

- **Booster Type** — select from built-in or user-defined boosters;
  New / Edit… / Delete buttons open `BoosterDialog`.
- **Reentry Object** — select the object carried to burnout (the payload). New /
  Edit… open the reentry-object editor; objects live in a shared library. A
  **Loadout: N ×** spinbox sets how many of the object the stack carries through
  boost: the launch mass composes as bus + N × object mass, so more objects (or
  a heavier one) honestly cost boost range, while **one** object is modeled on
  the way back. Non-separating (body) runs pin N = 1.
- **Reentry Plan** — the down-leg analogue of Flight Plan: a dropdown of the
  active object's reentry plans (`(default)` plus New/Delete variants) above its
  New/Edit…/Delete row, over the quick glider picks (glide law, terminal-dive
  altitude, aero model). The controls are the live editor and write
  through on every run. The reentry laws divide into two **integration
  families** — **numerical (EOM)** (Ballistic, phugoid/skip, damped phugoid,
  dynamic equilibrium; step-by-step integration, banking, dive-at-target,
  Mach-varying L/D, honest capture) and **closed-form analytic** (Acton, Tracy;
  pull-up arc + range formula, constant L/D, always captures) — and the family
  is the plan's **identity**: **New Reentry Plan** asks for the family first,
  then the starting law; the strip dropdown lists only the active plan's
  family, so the law is switchable *within* the family, never across it. To
  compare across families, keep one plan per family and flip the Reentry Plan
  dropdown. Each object ships with a default law tied to its type
  (C-HGB/generic maneuvering body → their characterized damped-glide; the other gliders →
  dynamic equilibrium glide; ballistic RVs → Ballistic, which lives inside the
  numerical family so glide on/off is an in-family tweak). (The old discrete
  `skip→equilibrium` mode is retired — it now flies the equivalent
  damped-phugoid glide.) A **Separation** indicator (*Separates at burnout* /
  *Non-separating — body reenters*) sits here too, read-only: separation is the
  **booster's** property (its `body_reenters` checkbox in the booster editor),
  the one link between a booster and a reentry object. Neither the object nor
  the reentry plan stores a separation choice, so any object flies on any
  booster. Non-separating inherits the last stage's burnout mass and geometry;
  the casing debris on a separating run carries the burnout mass minus the
  object, so nothing is double-counted. Below the glide
  law, the strip carries the one knob you iterate per-run: **ζ** (damping ratio
  for damped phugoid, tracking gain for dynamic equilibrium — with its estimator
  for the damped case), shown only for those two laws. **Edit…** opens the full
  plan editor for the set-once tuning — commanded L/D, pull-up g, flap,
  **reentry attitude** (trimmed vs. tumbling), **terminal-dive altitude**, the
  **aero model** (drag polar vs. fixed L/D), the **bank schedule**, and
  **dive-at-target**.
- **Display Units** — km / nmi / miles for all plots and timeline distances.
- **Launch Site** — pick from a built-in list or define custom sites (lat/lon);
  azimuth is set manually (°, clockwise from North).
- **Flight Plan** — the dropdown selects among the booster's flight plans
  (`(default)` plus named variants and the auto-generated `max-range` /
  `orbital`); New (name **and** guidance law — the law is fixed at creation) /
  Edit… / Delete manage variants, and the sidebar strip below edits the active
  plan's burnout angle, turn start/stop, Simple↔Advanced pitch, and (in
  Advanced) per-stage rows. Yaw / doglegs and deployment events are edited in
  the Flight Plan dialog.
- Engine cutoff moved to **Analysis ▸ Engine Cutoff (liquid)…** — optional early
  cutoff time (s), liquid engines only; blank = full burn. Aim-at-Target writes
  its computed cutoff to the same setting.
- **Target / Range** — optional target lat/lon or slant range for the
  *Aim at Target* function.
- Re-entry query moved to **Analysis ▸ Re-entry Query…** — a per-run diagnostic
  that reports reentry speed and angle at a chosen descent altitude in the
  Flight Timeline; blank disables it.
- Action buttons: **Run**, **Maximize Range**, **Aim at Target**,
  **Parametric Sweep**, **Plan Orbit**.

### Right tabs

| Tab | Contents |
|---|---|
| **Plots** | Altitude-vs-range, altitude-vs-time, speed-vs-time, and dynamic pressure / Mach curves on a Matplotlib canvas |
| **Flight Timeline** | Tabular milestone events (ignition, burnout, apogee, shroud jettison, reentry, impact) with lat/lon/alt/speed/range |
| **Booster Parameters** | Read-only summary of the active booster's mass, geometry, propulsion, and payload |
| **Schematic** | To-scale side elevation of the stack **as it will fly** (same composed loadout as Booster Parameters), drawn purely from stored geometry — stages, interstage frustums, nose/fairing (honouring `nose_shape`/`shroud_nose_shape`, the same fields the boost drag build-up reads), fin planform, grid fins, strap-ons — at equal aspect with a 5 m scale bar, so a mis-entered length or oversized fairing is visible at a glance. Unset fields draw a conservative fallback **flagged in the label** ("shape unset — cone shown") rather than silently invented. Redraws live on every booster change, edit, and loadout choice (`booster_schematic.py`) |
| **Reentry Survivability** | Mode-keyed survivability *report* (`SURVIVABILITY_REPORT_DESIGN.md`): flux/load plot, a plain-language lead (verdict → why → what would change it), then a **survival map** — a station × question matrix (nose → body skin → windward flank → interior, vs *surface holds / endures duration / within flown record*, one tier-colored number per cell; METHODS §13.12) as the hinge into the full analysis — then a judgement with consequences — ballistic RVs compare their flown ablator heat load against the material family's demonstrated flight record, gliders are judged on survival-time vs glide-time + the NRC-2008 TPS duration ladder. Everything beyond that fork — the windward-flank AoA block, the terminal-dive transient, the maneuver-load anchors — is gated on its own trigger rather than on a vehicle “Form”, and the headline names what the plan actually does (“glide · banking · terminal dive”; METHODS §13.14). For UHTC hot-structure gliders the verdict is moving from a pass/fail dwell to a **demonstrated-envelope coverage** statement — how much of the glide lies *within* the flight/arc-jet/furnace record (`SURVIVABILITY_REPORT_DESIGN.md` §11) — backed by a living anchor dataset in `BENCHMARKING.md` — ~18 flight/arc-jet/plasma-torch/furnace sources across every UHTC class (ZrB₂-SiC, HfB₂-SiC, HfB₂/HfC-MoSi₂, complex- and carbide-borides), each row with verified numbers and an exact citation, spanning ~1650–2700 °C and 3×10⁻³–1 atm. Survivals bound the envelope from below, failures cap it from above; a new flight strengthens the dataset as a data edit, not a code change. For ballistic-RV ablators the same discipline applies: the verdict compares the flown heat load against a cited demonstrated flight-load record (graphite/C-C from Reentry-F, PICA from Stardust), and computes only a **burn-through bound** (red fires only if the shield is consumed even at the most optimistic cited `H_eff`) — no recession point-estimate. The bound is validated against the recovered Stardust and Hayabusa capsules (the tripwire must not fire for a survived flight; the conservative δ still over-predicts measured recession — bounds, not fits), with radiative-heating and equilibrium-chemistry conservatism logged as P3 items. `BENCHMARKING.md` is the citation of record for the full paper set |
| **SLV Performance** | Algebraic payload-to-orbit analysis (circular or elliptical orbit) |

### Dialogs

- **BoosterDialog** — define a booster with up to three stages plus its own
  front-end hardware. Each stage has: fueled mass, dry mass, diameter, length,
  thrust (with Suggest estimator), Isp, nozzle exit area (with Estimate tool),
  burn time (computed), coast time, and a solid-motor flag with grain type
  selection. Each stage also has a **Conical stage** toggle (tapered body →
  enter a top diameter) and an **Interstage on top** toggle (an adapter whose
  length, mass, and jettison time are entered; its diameters are derived from
  the neighbouring stages, never invented). Both carry mass in Phase 1;
  aerodynamic coupling is Phase 2 (METHODS §6.7). The *Front End* panel holds
  only what the booster owns — the
  bus/PBV mass (carried as dead mass for now) and the fairing. It does **not**
  reference the reentry object: which object and how many is the sidebar's
  **Loadout** choice, composed onto the stage masses at run time (bus + N ×
  object mass). Stage masses are stored stack-only; throw weight is a computed
  tally shown on the Booster-Parameters tab, not an input here.
- **Reentry-object editor** — define a reentry object's **hardware**: mass,
  ballistic coefficient β (with a Newtonian β Calculator), nose shape/geometry,
  a **Maneuvering** checkbox (the hardware *capability* to generate lift — an
  object without it can only fly ballistic, whatever a plan asks), the
  airframe's **L/D capability**, its **structural pull-up g-limit** (0 =
  unlimited, so an extreme manoeuvre shows the load it would demand), the
  Acton **entry βₛ**, TPS materials (nose and body, from a catalog or bespoke
  values), and provenance. Separation is shown read-only here (it is the
  booster's property). How the object is *flown* — commanded L/D (≤
  capability), commanded pull-up g (≤ the limit), glide law, dives, banks,
  attitude — lives in the Reentry Plan, not here.
- **Reentry-plan editor** — the down-leg analogue of the flight-plan dialog
  (Reentry Plan ▸ Edit…), **family-aware**: commanded L/D clamped to the
  airframe capability ("fly it worse, never better"), whether this run
  *glides* at all (`glider_enabled`, clamped by the object's Maneuvering
  capability the same way), commanded pull-up g (clamped to the object's
  structural limit, when one is set), flap deflection,
  **reentry attitude** (trimmed vs. tumbling), and plan source/notes always;
  a **numerical** plan adds **ζ damping** (with its estimator), the **bank
  schedule**, and **dive-at-target** — the analytic closed form cannot bank,
  steer to a target, or damp a phugoid. The quick run-to-run picks (glide
  law within the family, separation, terminal-dive altitude, aero model) stay
  on the sidebar strip.
- **Parametric Sweep** — vary any one guidance parameter over a range and plot
  impact range vs. the swept variable.
- **β Calculator** — estimates reentry-object ballistic coefficient from cone
  geometry (half-angle, nose bluntness ratio, eval Mach, optional wing area):
  Newtonian pressure (closed form 2·sin²θ + ε²·cos⁴θ, Wells & Armstrong
  TR R-127) + turbulent skin friction + hypersonic base drag + wing friction,
  each component shown (METHODS §8.8).
- **Wing-decoupled drag polar** — a reentry object with a declared wing area
  (and optional aspect ratio) pulls more efficiently than a bare slender body:
  the drag bucket is broadened on the pull side only, so a commanded pull-up
  retains more energy while cruise L/D is untouched (METHODS §12.0.2). Wing
  area = 0 keeps the slender-body polar exactly.
- **Biconic reentry bodies** — a reentry object can be marked **biconic**
  (a forward cone on an aft frustum, the C-HGB / MaRV / HGV class): enter the
  fore-cone length and break diameter and the half-angles derive from the base
  geometry. The **β estimator** gains a two-cone build-up
  (`cd_biconic_hypersonic`, summing pressure + friction over both segments;
  exact single-cone reduction at `break⌀ = base⌀`), and the **Schematic** draws
  the true two-cone profile. β and L/D remain the reentry carriers; biconic
  geometry sharpens the estimate and the picture (METHODS §8.8).
- **Lifting-body forms (wedge / half-cone)** — a reentry object can declare
  its **body form**: body of revolution (default), **flattened wedge**
  (HTV-2 class; ⌀ = base depth, planform span stored as body geometry —
  flagged when unset, never invented), or
  **half-cone** (flat diametral plane over a conical surface). The Schematic
  draws the honest asymmetric side elevation and names the form; the
  trajectory physics are unchanged — β and L/D carry them, with two caveats
  worth knowing: published lifting-body β is usually quoted *at trim* (the
  polar wants zero-lift β), and the pull ceiling is a body-of-revolution
  value, conservative for wedges (METHODS §8.8).
- **Lifting-body β + L/D estimator** — for a wedge or half-cone, the object
  editor's **Estimate β** button opens an angle-of-attack sweep (modified-
  Newtonian pressure + Eckert reference-temperature skin friction + base
  drag) that returns one *consistent* trim row: **β at zero lift** (what the
  drag polar wants), **(L/D)max quoted with the α\* that produces it**, and
  the camber offset C_L0. Enter measurable geometry (length, base depth,
  **required** planform span for the wedge); every result states its
  conditions (Mach, Reynolds number, boundary-layer state, base-drag
  convention, reference area, K-factor). The estimate is a **sharp-body
  upper bound** — real blunt/viscous vehicles run ~30–40% lower, and the
  dialog says so and flags any L/D above the viscous-waverider band
  (METHODS §8.8). Bodies of revolution keep the zero-AoA cone/biconic
  build-up.
- **Dive-at-target radius is a lead distance, not a target size.** The
  range-triggered terminal dive fires while the glider is *inside* the
  target circle and releases when it leaves — it is a region, not a latch.
  A fast, high glider can cross a small circle before the dive reaches the
  ground; on exit the glide law arrests the sink and pulls back up, leaving
  a tell-tale **notch** in the altitude trace and a long overshoot. The cure
  is to dive earlier by enlarging the radius — but only up to a point: the
  dependence is non-monotonic, so too small overshoots (with the notch) and
  too large dives short. Tune the radius as a lead distance (start near
  *trigger-altitude × L/D*), raising it until the notch clears and impact is
  closest, backing off if impact then falls short (METHODS §12.5.1).
- **Thrust Estimator** — back-calculates engine thrust from observed acceleration
  during boost: `T = m · √(a_h² + (a_v + g)²)`.
- **Dry Mass Estimator** (Analysis menu) — estimates a stage's dry/inert mass
  from its geometry, propellant and thrust using component-level Wilhite-school
  mass estimating relationships (Akin/UMD) and aggregate relations (Pietrobon
  hydrolox; structural coefficient; Zandbergen and Lewis/NG-catalog best-in-class
  solid-stage regressions), and reports how far the booster's stated burnout mass
  diverges from each. Pulls per-stage parameters from the selected booster; works
  standalone too (`python mass_estimator.py --demo`). Full method notes in
  `MASS_ESTIMATOR.md`.
- **Screening Envelope** (Analysis menu) — view and, if new data warrants,
  adjust the ~12 **benchmark thresholds** behind the survivability screen (glide
  endurance, maneuver g-ceiling, the ablator demonstrated-load records, the
  bondline structure limit, the boundary-layer transition Re, and the
  model-conservatism knobs). Each row shows the current value, the greyed
  **shipped default**, and the default's citation; the shipped defaults are
  frozen, an edit lives only in an overlay file (`benchmark_overrides.json`),
  and **Restore All Defaults** discards it. A changed number self-discloses in
  the report — see *Adjustable screening thresholds* below.

---

### Adjustable screening thresholds

The survivability verdict rests on a small set of **benchmark numbers** — how
long a glider is *demonstrated* to endure, how hard a MaRV is *demonstrated* to
pull, how much heat load an ablator family has *flown and survived*, and a
couple of model-conservatism factors. New flights and tests move these numbers,
so the tool lets a user view and change them (Analysis ▸ Screening Envelope…),
while **always** being able to return to the shipped defaults.

**Why the thresholds, and only the thresholds.** Thrusty exposes exactly one
editable surface — these ~12 curated *envelope* numbers — and defers the full
material catalog and the anchor datasets to a future spreadsheet project. The
reasoning: a Thrusty user is a **policy-focused modeler**. That person is far
likelier to model a reentry object that *survived* and want to adjust the
envelope — the length of time an object might glide, the g a MaRV might pull —
in light of new open-source data, than to integrate new coupon data for one
particular material. So the first (and, for now, only) place to turn a knob is
the envelope, curated **by user story**, not by where the number lives in the
code. Material coupons and per-vehicle anchor records are a heavier,
spreadsheet-shaped job and are recorded as deferred work.

**Two disciplines keep an edit honest.** The shipped defaults are *frozen*: the
registry in `thresholds.py` holds each default plus its citation of record, a
user edit lives only in the overlay file, and a drift test
(`test_thresholds.py`) pins the registry defaults to the live model constants
so the dialog can never show one number while the model uses another. And a
modified benchmark *self-discloses*: the survivability report stamps its
headline with an asterisk and prints a **Modified benchmarks** block naming each
changed number, its shipped default, and the default's source — so a hand-edited
value never quietly rides on the shipped numbers' citations.

---

## Booster model (`BoosterParams`)

A booster is a linked chain of `BoosterParams` nodes (`stage2` pointer for
upper stages).  Key fields on the top-level node:

**Propulsion (per stage)**
- `mass_initial`, `mass_propellant`, `mass_final` (kg)
- `thrust_N` (average vacuum thrust, N), `isp_s` (s), `burn_time_s` (s)
- `nozzle_exit_area_m2` — enables proper ambient-pressure thrust correction
  `T(h) = T_vac − P_amb(h) · Ae`; zero falls back to a 2 % sea-level
  back-pressure approximation
- `coast_time_s` — inter-stage coast interval (s); a *flight-plan* value, left at
  0 for the pure-hardware built-ins (coast is guidance, not booster hardware)
- `solid_motor` — if true the engine cannot be shut off early

**Solid motor grain profile (per stage)**
- `grain_type` — one of six Shafer (1959) grain geometries (see table below);
  controls the instantaneous thrust-vs-time curve shape
- `thrust_peak_N` — peak vacuum thrust (N); `thrust_N` holds the average;
  the ratio `thrust_N / thrust_peak_N` is the fill factor for the chosen grain
- `thrust_profile` — optional list of `(t_frac, F_frac)` pairs for a
  user-supplied CSV curve; overrides the built-in grain shape when present

| Grain type | Burn character | Approx. fill factor |
|---|---|---|
| Tubular | Progressive | 0.85 |
| Rod and tube | Neutral | 0.99 |
| Double anchor | Regressive | 0.75 |
| Star | Neutral | 0.98 |
| Multi-fin | Two-phase | 0.65 |
| Dual composition | Two-phase | 0.51 |

**Geometry (per stage)**
- `diameter_m`, `length_m`
- `nose_shape` — one of `forden`, `v2`, `elliptical`, `conical`, `parabolic`,
  `tangent_ogive`, `sears_haack` (controls the FerencDV Cd model)
- `nose_length_m` — used to compute fineness ratio L/D for the nose model

**Shroud (top-level)**
- `shroud_mass_kg`, `shroud_jettison_alt_km` (default 80 km)
- `shroud_diameter_m`, `shroud_length_m`, `shroud_nose_shape`,
  `shroud_nose_length_m` — aerodynamics before jettison

**Payload / reentry object (top-level)**
- `payload_kg`, `num_ros`, `ro_mass_kg` — **run-time** loadout record written
  by `compose_loadout(booster, ro, N)` (throw weight = bus + N × object mass),
  never stored: booster files are **stack-only** and the reentry object owns
  its mass. Every stage's launch mass is adjusted at run time, so a heavier
  object or more objects honestly cost boost range while one object is
  modeled on the way back. A legacy file that baked
  a design payload into its stage masses (and, Scud-class, into the last
  stage's burnout mass, the retired `ro_separates = false` convention) is
  normalised to stack-only on load; composing the object that carries that
  mass reproduces the original masses exactly
- `body_reenters` — the **separation link**, and the only place a booster and
  a reentry object touch: `True` means the front end does not separate and the
  last stage is the reentering body. The run derives the object's
  `separation_mode` from it (`run_separation_mode`); object and reentry-plan
  files never store one
- `bus_mass_kg` — the bus/PBV mass (booster hardware). `num_ros`, `ro_mass_kg`
  — run-level loadout bookkeeping stamped by `compose_loadout`
- `ro_beta_kg_m2`, `ro_shape`, `ro_diameter_m`, `ro_length_m` —
  *deprecated* inline fields, superseded by the linked `ro` object
  (`ROParams`); kept only so old saved files still load. The reentry object's
  own β, mass, and geometry now live on `params.ro`.

**Guidance (top-level, with optional per-stage overrides)** — a *flight plan*,
not booster hardware
- `guidance`: `pitch_program` (default), `true_gravity_turn`, or
  `orbital_insertion` (legacy `loft` is auto-migrated to `pitch_program`)
- `launch_elevation_deg` — elevation at liftoff (°); 90 = vertical
- `burnout_angle_deg` — kick (burnout) elevation angle (°)
- `loft_angle_rate_deg_s` — pitch-over rate during the kick phase (°/s)
- Per-stage overrides: `stage_turn_start_s`, `stage_turn_stop_s`,
  `stage_burnout_angle_deg`, `stage_yaw_*` — override the global schedule
  for a specific stage; used by the built-in boosters to replicate
  published boost-phase pitch programs

---

## Physics

### Reference frame

The state vector `[x, y, z, vx, vy, vz]` is in **ECEF** (Earth-Centred
Earth-Fixed), which rotates with the Earth.  Earth's rotation is fully
accounted for through Coriolis and centrifugal pseudo-forces; no explicit
rotation term is needed in the initial conditions.

Inertial (ECI-frame) speed is recovered when needed as
`v_eci = v_ecef + ω × r`, where `ω = [0, 0, Ω_Earth]`.

### Equations of motion (`_eom`, `trajectory.py:656`)

At each integration step:

```
ẍ = g_ecef(r)  +  a_drag  +  a_thrust  +  a_coriolis  +  a_centrifugal
```

- **Gravity**: WGS-84 J2 oblate-spheroid model (`gravity_ecef`, `gravity.py`).
- **Coriolis**: `−2 ω × v` (`coriolis_acceleration`, `coordinates.py`).
- **Centrifugal**: `−ω × (ω × r)` (`centrifugal_acceleration`, `coordinates.py`).
- **Integration**: `scipy.integrate.solve_ivp` with RK45 and event detection
  for ground impact, apogee, and milestone altitudes.

### Atmosphere

COESA 1976 standard atmosphere (`atmosphere.py`), seven layers from 0–86 km,
exact layer lapse rates and pressure integrals.  Clamped to 86 km for the
standard model.

For drag above 86 km and up to 120 km an exponential interpolation of a
tabulated NRLMSISE-00 density profile is used (solar flux F10.7 = 150,
conservative low-activity estimate).  **Above 120 km drag is zeroed** because
the atmosphere model becomes unreliable — this is the boost/midcourse boundary.

### Drag — the three phases in code

The three-phase schema above maps directly to three drag regimes: shape-resolved
`Cd·A` while boosting, no drag while coasting exo-atmospherically, and lumped `β`
on the way down.

| Phase | Drag model |
|---|---|
| **Boost** (shroud attached) | `Cd × A`; reference area uses shroud diameter and nose shape |
| **Boost** (shroud jettisoned, `ro_separates` false) | `Cd × A`; reference area and nose shape from payload geometry |
| **Boost** (shroud jettisoned, `ro_separates` true) | `Cd × A`; reference area and nose shape from reentry-object geometry |
| **Midcourse** (above 120 km) | drag zeroed — pure ballistic/orbital coast |
| **Reentry** (`β > 0`) | β ballistic coefficient: `F_drag = q · m_ro / β` |
| **Reentry** (`β = 0`) | Falls back to final-stage Mach-table `Cd × A` |

The shroud-jettison event fires on the first upward crossing of
`shroud_jettison_alt_km`.  At that point shroud mass is subtracted and the
reference geometry switches accordingly.

The Forden Mach table (Figure 1, piecewise linear):
`Mach = [0.0, 0.85, 1.0, 1.2, 2.0, 4.5]`,
`Cd   = [0.20, 0.20, 0.27, 0.27, 0.20, 0.20]`.

**Strap-on booster drag** is computed independently in `booster_drag_vector`
(`booster_models.py:3241`) as n × Cd_booster × q × πr² and added to the
core-body drag vector.  The presence of strap-ons does **not** trigger any
correction to the core's base drag.  Physically, a strap-on cluster attached
to the rear of the core alters the base-pressure and wake-suction development,
which would reduce or eliminate base drag on the core aft section while the
strap-ons are attached.  This interaction is not modelled; core drag and strap-on
drag are treated as fully independent.  The simplification is conservative
(slightly over-predicts total drag at low Mach numbers) but should be noted
when interpreting boost-phase range or burnout-velocity results for boosters
with large strap-ons.

### Fins and stability

Thrusty handles two fin types, and treats **finned boosters** (fins for *drag +
stability*) separately from **gliding reentry objects** (whose *lift*/`L/D` is a
hypersonic lifting-body property, set per-object — fins do **not** add lift to an
ascending booster, which flies at ≈0° angle of attack).

**Fin drag is applied in the trajectory** (`drag_force_vector`) while the finned
stage is active, referenced to body base area and added to body drag; fins
jettison with their stage.  This affects range for finned atmospheric boosters
(e.g. the Strypi VIII R's large Castor fins cost it ~18% range).  Two models:

- **Planar fins** (`_cd_fins`): flat-plate skin friction + Ackeret wave drag.
- **Grid (lattice) fins** (`_cd_gridfins`): a box-frame lattice is not a planar
  airfoil — it has a transonic-choke drag bump and a roughly flat supersonic
  level.  The model is calibrated to Washington & Miller (AIAA 93-0035) and
  corroborated against eight further grid-fin papers (cited only — `data/` holds
  no PDFs; papers live in Drive per `data/REFERENCES.md`).  Inputs
  are kept observable: count, frame width/height, chord, **solidity σ = 1 −
  ((p−t)/p)²** (the blocked frontal fraction, estimable from imagery, or via a
  **"Calculate σ…"** button that derives it from the web thickness `t` and cell
  pitch `p`), edge factor, and a **deployment schedule**.  All of these are
  editable in the booster editor's *Fins* panel ("Has grid (lattice) fins").  Grid
  fins can deploy in timed batches: the deploy-schedule field takes `t:n, …`
  entries — e.g. STARS flies `3:4, 63:4` (4 fins at tower-clear ≈ t=3 s, 4 more at
  t=63 s); a blank field means all fins are deployed from launch.  The deployed
  count scales the grid-fin drag in the trajectory (`grid_fins_deployed`).

**Static margin** (`grid_fin_sizing.py`) answers "are these fins sized right?"
the Barrowman way — the centre of pressure is the normal-force-weighted average
of the nose and fin contributions, and

```
x_CP = Σ_i (C_Nα,i · x_i) / Σ_i C_Nα,i
SM   = (x_CP − x_CG) / D          [calibers;  ~0.5–2 is "appropriate"]
```

The fin normal-force slope is **Barrowman 1967 thesis Eq 3-12**
(`_cl_alpha_fins`; the thesis is cited only — it is not in `data/`, which holds
no PDFs):

```
AR = (2s)²/A_f,   β = √|M²−1|,   tan Γ_c = tan Λ_LE + (c_tip−c_root)/(2s)
C_Nα = N·π·AR·(A_f/A_ref) / [2 + √(4 + (β·AR/cos Γ_c)²)] · (1 + d/(2s+d))
```

This is small-AoA, fin-stabilised slender-body theory — used for **booster**
static margin, **not** for a gliding reentry object (whose L/D is a hypersonic
lifting-body property; see below).  CG is estimated from the stage mass stack
(overridable).

### No-separation glider: L/D derived from geometry

A **separating** reentry object carries its own designed `glider_LD`.  But when the
object does **not** separate (generic maneuvering body / Pershing II MaRV class), the gliding body
*is* the whole airframe, so its L/D is an emergent geometric property, not an
input. `glider_ld.py` derives it from the semi-empirical body+fin force build-up
at angle of attack — the analytic core of Missile DATCOM — assembled from the
primary sources cited below (which are **not in the repo**: `data/` holds no
PDFs; papers live in Drive per `data/REFERENCES.md`):

- **body normal force**: slender-body potential lift + viscous crossflow
  (**Allen-Perkins**, NACA Rep. 1048 / RM A50L07; **Jorgensen**, NASA TN D-7228
  Eq. 1 and TR R-474),
- **wing-body interference**: **Pitts-Nielsen-Kaattari** (NACA Rep. 1307), whose
  slender-body factors satisfy `K_W(B) + K_B(W) = (1 + r/s)²`.

Referenced to body base area, with `M_n = M·sinα` the crossflow Mach:

```
C_Nα,pot = 2·(A_b/A_r) + (1+r/s)²·(C_Lα)_W·(S_W/A_r)
C_N(α)   = C_Nα,pot·sin(2α)/2 + η·C_dn(M_n)·(A_p/A_r)·sin²α
C_A(α)   = C_A0·cos²α ;   C_L = C_N cosα − C_A sinα ;   C_D = C_N sinα + C_A cosα
```

L/D is maximised over α.  The two crossflow factors are **sourced, not assumed**:
`η = 1` for supersonic/hypersonic free-stream Mach (Jorgensen TN D-7228), and the
cylinder crossflow drag coefficient `C_dn(M_n)` is read from **Gowen-Perkins**
(NACA TN 2960) Fig. 7 — ~1.2 at low `M_n`, a transonic peak ~2.1 at `M_n = 1`,
decaying to ~1.34 at `M_n = 2.9`.  `A_p` is the body's true side-projected
planform (nose `fill·L_nose·d` + cylinder `(L−L_nose)·d`; cone fill 0.5, ogive
~0.67).  For a no-sep body left at `glider_LD = 0`, the trajectory auto-derives
this value at setup; existing objects with an explicit `glider_LD > 0` are
untouched.  The derivation is **Mach-varying**: at setup a `(L/D)_max(M)` table
is sampled over `M ∈ {1.5…12}` (capped by the trim gate below) and interpolated
per step on local Mach in the numerical glide modes (below M1.5 the M1.5 value
is held; analytical Tracy/Acton modes keep a constant L/D at the M5 value). The
airframe swing is ~12–16 % over M1.5→M5; for total range it is sub-1 % on a
non-separating (aeroballistic) body, biggest for terminal-phase quantities.

This build-up is **validated against Digital DATCOM** (USAF, public-domain) for a
finless slender body at M2/3/5: L/D agrees to within ~10% (and zero-lift drag and
best-glide AoA closely), `glider_ld` staying slightly conservative.  The deck,
reference output, and comparison script are in `validation/datcom/`.

**Trim/control gate** (`trim_gate.py`) — a derived L/D is only *achievable* if
the airframe can trim and hold that AoA.  The pitching moment about the CG is
summed **term by term**, because the build-up's normal force is nonlinear in α
and its three terms act at three different stations:

```
C_m(α,δ)·d = −[ C_N,body(α)·(x_body−x_CG)          slender-body potential
              + C_N,cross(α)·(x_planform−x_CG)     crossflow, at the planform centroid
              + C_N,fin(α)·(x_fin−x_CG)            fin + N-K-P carryover
              + control_eff·C_Nα,fin·δ·(x_fin−x_CG) ]   commanded control
α_trim(δ) = root of C_m = 0, bisected on the build-up's own 1–59° sweep
```

Outcomes: `SM ≤ 0` → unstable → tumbles → ballistic (drag re-derived as a
tumbling cylinder); **`δ_max = 0` (fixed surfaces) → trims at zero incidence →
ballistic nose-first** (no lift, but the aeroshell β is kept — *not* tumbling);
`α_trim,max ≥ α_LDmax` → control reaches best glide (full L/D); otherwise
control-limited → the best L/D over the reachable band `(0, α_trim,max]`.

**Control authority is read from the vehicle,** not assumed: the reentry
object's `glider_control_surfaces` descriptor sets the usable deflection
(`none` → 0°, `small` → 5°, `substantial` → 15°, `unknown` → 10° reported as an
assumption), capped at the same incipient-separation limit `damping_estimate.py`
uses.  That limit comes from the Needham & Stollery criterion (AIAA 66-455) as
carried by Kumar & Stollery, *The Aeronautical Journal* 100(996), 1996 — both
read against the primaries.  At Thrusty's flight Reynolds numbers the criterion's
turbulent branch puts incipient separation at 17–41°, so 15° is a conservative
cap rather than a laminar limit; see METHODS.md §8.10.  A previous 25°
all-moving-control default made the gate unable to limit a fin-stabilised body at
*any* CG.

**Reentry attitude — trimmed vs. tumbling.** The reentry plan carries
`reentry_attitude ∈ {trim, tumbling}`. *Trim* (default) is the stable controlled
body above. *Tumbling* is an uncontrolled body (spent stage, failed RV, or any
body the gate flags `SM ≤ 0`): it makes **no lift**, and its β is *derived* from
geometry as a tumbling cylinder rather than inherited from the aeroshell —
grafting the aeroshell's low-drag β onto a tumbling body would be physically
wrong (a tumbler presents a huge mean area, i.e. low β). The derived β uses a
two-orientation **Hoerner** form (*Fluid-Dynamic Drag* 1965, Ch. XVIII), each
orientation with its own hypersonic coefficient: broadside cross-flow cylinder
`C_D = ⅔·C_p•` ≈ 1.2 (eq. 44/Fig. 24) on `d·L`, end-on blunt face
`C_D = 0.89·C_p•` ≈ 1.6 (Fig. 22) on `πd²/4`, with `C_p• = 1.84 − 0.76/M²`
(eq. 41). The same `tumbling_cylinder_beta` computes spent-casing debris arcs,
which keep the legacy single-`C_D = 1.0` form.

**L/D in a pull-up.** `L/D_max` is the *peak*, reached only at the best-glide
angle of attack. A non-separating reentry object that pulls up commands a load
factor `n` (≤ `glider_pullup_g_max`), needing lift `L = n·m·g`, i.e.
`C_L = n·m·g/(q·A_ref)` with `q = ½ρV²`. The effective L/D at that `C_L` comes
from the back-solved drag polar (`_aero_polar`):

```
C_D0 = m/(β·A_ref) ;  k = 1/(4·C_D0·(L/D_max)²) ;  L/D(C_L) = C_L/(C_D0 + k·C_L²)
```

which peaks at `C_L* = √(C_D0/k)` recovering `L/D_max`. Any pull harder than
`C_L*` climbs the induced-drag branch `k·C_L²`, so the instantaneous L/D drops
below `L/D_max` — a steep pull-up trades glide range for turn rate. `C_L` is
capped at ≈0.87 (`C_L ≈ 2α` at α_max = 25°) and `n` at `glider_pullup_g_max`.
For a no-sep body the `L/D_max` here is the geometry-derived value above; for a
separating object it is the designed input. (The pull-up arc and glide-guidance
modes are in METHODS §12.)

### Guidance laws (the boost-phase flight plan)

**Pitch Program** (`pitch_program`, the default) — The booster launches at
`launch_elevation_deg`, kicks off vertical to `burnout_angle_deg` at
`loft_angle_rate_deg_s` (the kick rate), then locks thrust to the velocity
vector for the remainder of powered flight.  This is the mode used by most
built-in boosters. The legacy `loft` mode (Forden pitch-over) is auto-migrated to
`pitch_program` on load.

**True Gravity Turn** (`true_gravity_turn`) — The booster launches at
`launch_elevation_deg` and pitches over at `loft_angle_rate_deg_s` from
`stage_turn_start_s` until reaching `burnout_angle_deg` (the burnout elevation),
then thrust follows the velocity vector and gravity does the rotation for the
remainder of powered flight.  Used by the AUR / Minotaur-class stacks.

Per-stage overrides (`stage_turn_start_s`, `stage_turn_stop_s`,
`stage_burnout_angle_deg`) let each stage follow an independent pitch
program — this is how the built-in boosters replicate their published boost-phase
pitch schedules.  Azimuth is fixed at launch; optional yaw overrides add
cross-range steering.

**Orbital Insertion** (`orbital_insertion`) — Identical to a gravity turn during
boost, but engine cutoff is commanded when the state vector reaches the target
orbital energy rather than at a fixed burn time.  Solid stages burn to natural
burnout regardless.

All three modes support optional advanced per-stage pitch and yaw programs that
override the global schedule for a specific stage.

> **Gliding reentry objects** carry a separate guidance axis (`glider_guidance`),
> grouped by integration method.  The **numerical (EOM)** modes span the
> phugoid-damping spectrum — `ballistic` (no lift), `skip_glide` (undamped
> phugoid), `damped_glide` (the realistic guided pull-up, default ζ≈0.7), and
> `dynamic_equilibrium_glide` (equilibrium-trim capture) — plus two **closed-form
> analytic** comparison laws: `equilibrium_glide_acton` (Acton non-oscillatory
> capture) and `equilibrium_glide` (Tracy).  (`skip_to_equilibrium` is retired,
> aliased to `damped_glide`.)  The ζ≈0.7 default is the classical
> second-order control damping ratio — the desirable ζ=0.4–0.8 band (Ogata §5-3;
> Franklin §3.4.2, ζ=0.7 → ~5% overshoot) and very nearly settling-time-optimal.
> See `DAMPED_GLIDE.md` for details.

---

## Key algorithms

### Vincenty geodesic (`range_between`, `coordinates.py:122`)

Replaces Forden's spherical haversine with the Vincenty inverse formula on the
WGS-84 ellipsoid (~0.5 mm accuracy).  Falls back to haversine for near-antipodal
pairs where Vincenty does not converge.

### Wheelon optimal burnout angle (`_wheelon_gamma_opt`, `trajectory.py:3274`)

For a given burnout speed `v_bo` and altitude, the optimal elevation angle
that maximises range on a spherical Earth is:

```
Q       = v_bo² / (g_bo · r_bo)
γ_opt   = ½ · arccos( Q / (2 − Q) )
```

Used by `maximize_range` to narrow the coarse grid search to ±10° around
`γ_opt`, reducing evaluations by ~67%.

### Tsiolkovsky stack ΔV (`_tsiolkovsky_dv`, `trajectory.py:3261`)

Sums ideal vacuum ΔV across all stages: `Σ Isp_i · g₀ · ln(m0_i / mf_i)`
(the rocket equation).  Used to estimate burnout speed before the
range-maximisation search.

### Range maximisation (`maximize_range`, `trajectory.py:3286`)

Two-phase parallel search over the **simple** pitch profile (global burnout
angle × turn-stop); each candidate is a full trajectory integration:

1. **Coarse grid** — evaluate (burnout angle × turn-stop) candidates on a thread
   pool; the angle window is ±10° of the Wheelon optimum, and turn-stop is
   sampled densely over the early window where the range peak is narrow.
2. **Fine optimisation** — `scipy.optimize.minimize_scalar` (Brent) polishes the
   burnout angle at the coarse-best turn-stop.

The optimum depends on launch site, azimuth, and reentry-object drag, so it is
not a property of the booster. The GUI writes the result to a reserved
`max-range` flight-plan variant (see *Flight plans are named, switchable
artifacts*) rather than editing the active plan, and refuses to run on an
Advanced-pitch plan whose per-stage angles would mask the swept globals. This is
the numeric rung between the closed-form **Wheelon ε\*** estimator (instant,
idealised) and any future full per-stage profile optimisation.

### Aim at target (`aim_booster`, `trajectory.py:3051`)

Binary search on engine cutoff time to minimise range error to the target
geodetic point (Vincenty distance).

### SLV algebraic estimator (`slv_performance.py`)

Schilling method.  No integration required.  Computes the required
ΔV for a circular or elliptical orbit (vis-viva at perigee), applies an
empirical gravity/drag/steering-loss penalty derived from ascent time, and
solves for the maximum deliverable payload.  Accuracy ~260 m/s RMS in total
mission ΔV; ~10% payload error.

### Cone β calculator (`booster_models.cd_cone_hypersonic`)

Hypersonic axial Cd for a blunted cone as a three-term build-up: Newtonian
pressure (the exact closed form `2·sin²θ + ε²·cos⁴θ`, Wells & Armstrong
TR R-127 — sharp cone `2·sin²θ` at ε=0) **plus** turbulent skin friction
(`Cf·S_wet/A_base`, exact frustum geometry, Cf = 0.0012 screening constant)
**plus** hypersonic base drag (`2/γM²`).  The viscous
and base terms matter enormously for slender cones — pressure-only
under-counted a 5.25° cone's Cd ~4× and inflated its estimated β to
~10⁵ kg/m² (METHODS §8.8) — and are a 2–4% perturbation for blunt RVs.
Bare-cone estimate: wings/fins add drag it does not carry.

### Reentry heating (`heating.py`)

A screening estimate of whether the reentry object survives its heat load —
Sutton-Graves stagnation-point convective flux `q̇ = k·√(ρ/R_n)·V³`, a
radiative-equilibrium wall temperature `T_w = (q̇/(εσ))^¼`, and the integrated
load over the trajectory, evaluated at the nose tip and over the body acreage
using the per-location TPS materials. It is a screening indicator, **not** a
through-wall TPS design analysis. See `HEATING_MODEL_CROSSCHECK.md`.

---

## Outputs

| Output | How to produce |
|---|---|
| **Altitude / speed plots** | Runs automatically; displayed in the Plots tab |
| **Dynamic pressure / Mach plot** | Displayed in the Plots tab alongside altitude curves |
| **Flight Timeline** | Tabular milestones in the Flight Timeline tab |
| **Booster Parameters** | Summary in the Booster Parameters tab |
| **Reentry Survivability** | Mode-keyed screening report + flux/load plot in its tab |
| **Folium map** | File → Export Folium Map; interactive HTML map with ground track, milestone markers, debris arcs, and leader-line labels |
| **KML** | File → Export KML; opens in Google Earth |
| **Trajectory CSV** | File → Save Trajectory; time-series state vector |
| **Timeline CSV** | File → Export Timeline |
| **Booster JSON / XLSX** | File → Export Booster Definition / Save Booster to XLSX |
| **Reentry-object JSON / XLSX** | File → Save Reentry Object / Save Reentry Object to XLSX |

---

## Built-in boosters

The shipped boosters are reentry / hypersonic-glide testbed stacks — each carries
a reentry object and is set up for a lofted or depressed reentry. Most use
`pitch_program` guidance with per-stage pitch overrides tuned to replicate
published boost-phase pitch programs; the Minotaur-IV stack uses
`true_gravity_turn`.

| Booster | Stages | Reentry object | Guidance |
|---|---|---|---|
| Minotaur-IV + HTV-2 | 3 | HTV-2 (glider) | true gravity turn |
| Strypi VIII R | 2 (+ Castor I strap-on) | SWERVE (glider) | pitch program |
| Strypi VIII R (Castor II) | 2 (+ Castor II strap-on) | SWERVE (glider) | pitch program |
| Strypi VII R | 3 | Strypi VII R RV (ballistic) | pitch program |
| STARS-1 | 3 | AHW (glider) | pitch program |

The classic Forden (2007) Table 1 boosters — Scud-B, Al Hussein, No-dong,
Taepodong-I/II, Shahab-3, Zoljanah, and a generic three-stage ICBM — remain as
builder functions in `booster_models.py` but are **not registered** in
`BOOSTER_DB` by default (they are the validation reference set, not the shipped
picker).

---

## Dependencies

Core (`requirements.txt` — the app will not start without these):

```
numpy  >= 1.24
scipy  >= 1.10
matplotlib >= 3.7
Pillow >= 9.0
```

Optional (`requirements-optional.txt` — one feature per package, graceful
degradation with an on-screen hint when absent):

| Package | Feature |
|---|---|
| `geopy` | Find Location → "Search online…" (OSM Nominatim) |
| `cartopy` | Find Location → "Pick on map…" |
| `folium` | interactive HTML trajectory map export |
| `openpyxl` | booster / RO spreadsheet import-export |
| `tkinterdnd2` | drag-and-drop / ⌘V images onto the measure tool |

The offline place gazetteer (10.4 M named places, Analysis ▸ Reference
Data ▸ Offline Gazetteer) is bundled in `data/gazetteer/` and indexed with
the standard library — no package needed; it replaces the old
`geonamescache` dependency.  Standard library otherwise (tkinter, json,
pathlib, threading, math).

---

## License

- **Code** (all `.py` files, the app bundle, scripts): GNU General Public
  License v3.0 or later — [`LICENSE`](LICENSE).
- **Documentation and vehicle data authored for Thrusty** (`*.md`, the
  `booster_library/`, `ro_library/`, `flight_plans/`, `reentry_plans/` and
  `launch_sites.json` files, `design/`, the diagrams under `docs/`): Creative
  Commons Attribution-ShareAlike 4.0 International — [`LICENSE-DATA`](LICENSE-DATA).
- **Artwork** — the Thrusty mascot and icon: everything in `assets/`, the
  `Thrusty*.png` / `Thrusty_silhouette.jpg` renders in `data/`, and the
  `.icns` in the app bundle: **© 2026 Jeffrey Lewis, all rights reserved.**
  Not covered by either license above. You may pass along unmodified copies
  of Thrusty with the artwork intact; any other use, and any modified
  Thrusty, needs permission or must replace them.
- **Bundled third-party data** (gazetteer, terrain, borders, TPSX materials,
  motor catalog values, digitised benchmarks) keeps its original terms, listed
  with attributions in [`NOTICE.md`](NOTICE.md).

Copyright © 2026 Jeffrey Lewis.  Contributions require a contributor license
agreement; see [`CONTRIBUTING.md`](CONTRIBUTING.md).  The scope statement in
`CLAUDE.md` (analytic verification, not design) is a project norm, not a
license term.
