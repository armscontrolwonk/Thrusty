# Thrusty — project context for Claude

## What this is

Thrusty is an open-source, 3-DOF trajectory and reentry simulator for
policy and arms-control analysis. It is a Python/Tkinter port and extension
of Geoffrey Forden's published MATLAB tool, *Simulating the Operation of
Ballistic Missiles*, Science & Global Security 15 (2007). The purpose is
**analytic verification**: checking whether publicly reported ranges,
apogees, payloads, and reentry behaviour of tested vehicles are physically
consistent with what open sources say about them.

The intended user is a policy-focused modeler (see `thresholds.py`
docstring), not a vehicle designer. The tool answers "is this claim
plausible?" and "what does open evidence imply?", not "how do I build or
improve this."

## Data provenance

- Every model traces to a citable open publication (see `METHODS.md`
  §16 and `data/REFERENCES.md`): Forden 2007, Schilling 2009, Sutton &
  Graves 1971, Tracy & Wright 2020, Acton 2015, Barrowman 1967, NACA/NASA
  technical reports, Digital DATCOM (public domain).
- Vehicle parameter files in `booster_library/`, `ro_library/`, and
  `flight_plans/` are built from open sources: published papers, official
  test announcements, imagery-derived dimensions (`image_measure.py`), and
  standard engineering estimators (`mass_estimator.py`). No controlled or
  proprietary data is used or wanted.
- Screening thresholds are curated from flight-demonstrated open
  literature, with each number's citation recorded in `thresholds.py`.
- Gazetteer and terrain data are public BGN and AWS Terrarium tiles, used
  to identify test impact zones and launch-site elevations.

- Licensing: code GPL-3.0-or-later (`LICENSE`), Thrusty-authored docs and
  vehicle data CC BY-SA 4.0 (`LICENSE-DATA`), mascot artwork and icon all
  rights reserved, bundled third-party data under its own terms (`NOTICE.md`). Outside contributions need the CLA in
  `CONTRIBUTING.md`. Keep new data files' sources recorded in `NOTICE.md`.

## Working rules

- **Derive, don't invent.** Never hard-code a coefficient from memory;
  it must come from a cited document in `data/`. Flag uncertainty rather
  than fabricate a source.
- **Usage-neutral physics.** The same integrator serves sounding rockets,
  space launch vehicles, and ballistic reentry bodies. Keep it that way.
- **Screening tier, not design tier.** Heating and survivability outputs
  are qualitative consequence bands anchored to flight experience. Do not
  add design-fidelity thermal, structural, or guidance models.
- **The GUI computes nothing.** `thrusty.py` is widgets, threads and
  plotting only. A formula or sweep loop belongs in a core module
  (`analysis.py`, `coordinates.py`, `booster_models.py`, …) with a test;
  the dialog calls it. This keeps the core portable and testable headless.
- **Tests read only what is committed.** `conftest.py` blanks the user
  library paths (`USER_FLIGHT_PLAN_DIRS` and friends) that `thrusty.py` sets
  on import, so a run never picks up `~/Documents/Thrusty/`. Any script that
  dumps reference trajectories must do the same. A test asserting on a
  sampled endpoint or a strict local extremum is a metric to distrust: two
  false alarms in `test_pullup.py` and one in `test_terrain_dem.py` came from
  exactly that (see `TODO.md`).
- Requests in this repo are about the simulator: integrator bugs, guidance
  branch selection, plotting, file formats, validation against published
  benchmarks, and documentation. Frame work that way.
- **Four inputs, kept apart.** A run is composed from two hardware files
  (booster, reentry object) and two non-hardware files (flight plan,
  reentry plan). Hardware files carry no plan key and plan files carry no
  hardware key; nothing is stored twice. Booster files are stack-only: the
  reentry object owns its mass, and a flight plan may name the object it
  flies. Timings are plan data even when
  the thing that moves is hardware (grid fins are hardware, when they
  deploy is flight plan). The only link between a booster and a reentry
  object is the booster's `body_reenters` flag; neither the object nor the
  reentry plan stores a separation choice. `test_input_split.py` enforces
  this over the shipped files and the serialisers. **A new field must be
  given an owner in `field_registry.py`** — hardware is enumerated there, not
  left over, so an unclassified field fails the suite instead of silently
  becoming hardware. Compatibility with
  older files lives only in `upgrade_booster_dict` / `upgrade_ro_dict`; the
  `*_from_dict` constructors read the current schema and nothing else.

## Out of scope

This project does not do, and should not be extended to do: weapon design
optimisation, defense-penetration analysis, or targeting of specific
locations. "Aim at Target" and "dive-at-target" exist to reproduce
observed test-flight impact zones for analytic comparison.

## Layout

| File | Purpose |
|---|---|
| `thrusty.py` | Tkinter GUI |
| `trajectory.py` | 3-DOF integrator, guidance laws, range optimiser, orbital planner, reentry glide |
| `booster_models.py` | Booster and reentry-object dataclasses, drag, thrust, staging |
| `field_registry.py` | Which of the four files owns each dataclass field. Pure data; the key tuples and the split tests derive from it |
| `analysis.py` | Sweep drivers (range ring, parametric sweep, footprint) and result post-processing; the GUI orchestrates these, never computes |
| `heating.py`, `tps_ladder.py`, `survivability_report.py` | Reentry aerothermal screening |
| `slv_performance.py` | Schilling payload-to-orbit estimator |
| `METHODS.md` | Governing equations and citations for every model |
| `BENCHMARKING.md` | Validation against published figures |

Run tests with `pytest`. See `README.md` for the full source-file guide.
