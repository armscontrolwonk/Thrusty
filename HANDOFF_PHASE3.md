# Handoff: Part IV Phase 3, spent stages (refreshed 2026-10-01)

For a new Claude session picking up the separation-handoff work. Read
`CLAUDE.md` and `FRONT_END_DESIGN.md` Part IV (sections 16–19d) first; this
note says where the work stands and what was decided along the way.

## Where it stands

Phase 3 is built, tested, documented and committed (on `main`, not pushed).
Suite: 1180 passed, 2 skipped, about 100 s. Newest first:

| Commit | What |
|---|---|
| `fa97577` | Phase 3 part 3: the stage's own swing (`attitude_model`, `_attitude_verdict`) picks the reported point; ± on midpoint rows |
| `2c16c25` | `CLAUDE.md` layout row for `spent_stage_aero.py` |
| `6a074fa` | Phase 3 part 2: drag by attitude (`spent_stage_aero.py`, Jernell data in `data/aero/`), the end-over-end climb leg to apogee, the trim-to-tumbling band reported at its midpoint, solid stages trimmed from Romaniw's nozzle ratio; `test_spent_stage_aero.py`; METHODS §14.3/§16, Part IV §19d, NOTICE, REFERENCES, README, `TODO.md` item 10 |
| `e82c23c` | AUR corrected (user): both stages solid, stage 1 double-anchor grain at 290 kN peak; legacy-load golden regenerated for that file; damped-glide smoke test pins its constant-thrust carrier |
| `857cc42` | Phase 3 part 1: spent stages leave at their own burnout (the debris clock starts at `booster_core_delay_s`); `integrate_debris` runs to the main flight's tolerances and lands on the terrain model |
| `fc2af62` | Part IV: Phase 3 revised from the readings; TN D-7228 title corrected in `data/REFERENCES.md` |
| `607ff0c` | Part IV: Klett read from primary; the unverified AFGL handbook withdrawn |
| `5b661b3` | Phase 2: a body's object file stores 0 = "from booster" for mass, diameter, length; pairing rule (`check_pairing`); editor saves zeros |
| `41aee67` | Phase 1: `hand_off()` record, `result['handoff']`, `reentering_airframe()` |
| `63dfa96` | Part IV design + Phase 0 tests (`test_handoff.py`) |

How a spent stage or strap-on casing is flown now (details in
`spent_stage_aero.py`'s docstring, METHODS §14.3, Part IV §19d):

- still climbing at separation: end over end in the plane of flight to
  apogee (it leaves front-first, which is unstable, and the swing grows while
  dynamic pressure falls; an inference from Tobak & Peterson eq. 33 and
  Regan 13.56, stated in the run's notes);
- from apogee (or from separation if already falling): twice, tumbling and
  trimmed; the swing calculation picks which is reported (settles → trimmed;
  still tumbling at peak q → end over end; unclear, or no spin from the air
  → the great-circle midpoint with ± on the timeline row); both ends, the
  climb, the spin and the assumptions ride on the milestone as `impact_band`;
- trim from Jernell's measured centre of pressure against the empty CG:
  liquid, engine share (Shu et al. 2020) at the base; solid, nozzle share
  (ratio of Romaniw 2013's fits at peak thrust) at the base; finned stages
  and solids with no thrust in the file have no trim (tumbling only);
- the fairing is unchanged (old β path).

The 44 km band on AUR stage 1 that prompted this: 41 km of it accrued on the
climb. Shipped bands are now 0–8 km (Minotaur-IV stage 3: 16 km at 19,400 km
downrange). Main trajectories unchanged. All 13 vehicles run in 7 s; the
"6.9 min suite" reported earlier did not reproduce, so the debris tolerances
stay at the main flight's values.

## What is left in Phase 3

1. **Stage-impact benchmark.** The user is sourcing one; nothing checks a
   debris impact point against an observation yet.
2. **Settle or tumble** is built and committed (`fa97577`, Part IV §19e): the swing is followed along the flight and picks the trimmed
   or end-over-end point when it is clear; the midpoint, with ± on the
   timeline row, when it is not. Still open under it: Tobak & Peterson's
   Fig. 2 as a check of the integrator, pitch damping, the separation kick.
3. **Validation list.** `TODO.md` item 10 lists every model adopted on a
   ratio, an extrapolation or an inference, with the data that would test it.
4. **Real stage ends** (open interstage, nozzles) and **fin forces beyond
   58°**: no source in hand.
5. **AUR's Isp.** The double-anchor curve at 290 kN peak delivers 11.7 MN·s;
   the file's 280 s Isp implies 12.4 MN·s. The thrust curve governs; the Isp
   may be high. AUR stage 2 has no grain given (constant thrust).
6. **Strap-on casings on the Strypi VIII R files** separate about 1 km up and
   land at 0.0 km range; pre-existing, not looked into.
7. `TODO.md` item 6 still says the fairing has no trajectory or impact point;
   out of date.

Phase 4 (later): a flight-plan option to drop the fins.

## Decisions the user made (do not re-litigate)

- One handoff at separation in both separating and body modes; files never
  store the booster's numbers (Part IV §16–18).
- Fins stay on a handed-off body; a flight-plan option to drop them comes later.
- Where a tumbling stage lands matters more than its heating, for now.
- **Finned stages: band only** (trim unknown) — with the midpoint rule, flown
  tumbling only.
- Outside Mach 1.5–2.86: hold Mach 1.5 values below; tumbling drag blends to
  Klett above; trim held at Mach 2.86.
- **Report one number.** First the midpoint of the range (2026-09-30); then
  (2026-10-01) the end the physics picks when it picks one, the midpoint
  with its half-width on the timeline row when it does not. Assumptions stay
  in the data and the docs, not on screen.
- Boost-nose fix (a body's nose length during boost) is **held** until nose
  lengths are sourced (Part IV §19a).
- The user sources the stage-impact benchmark themselves.
- (2026-10-01) AUR is solid in both stages; stage 1 double-anchor, 290 kN peak.
- (2026-10-01) Romaniw's case/insulation/nozzle fits are used **as a ratio
  only** ("the data isn't ideal but the ratios might be ok"); peak thrust is
  the input.
- (2026-10-01) Keep a list of models to validate with Thrusty-collected data
  (`TODO.md` item 10).

## What the sources showed (all read from primary, page refs in Part IV §19c)

- **Klett**, Sandia SC-RR-64-2141 (`~/Desktop/4630398.pdf`): cylinder drag
  side-on, end-on, fixed angle (sin³/cos³), end-over-end, random; Mach 10–30.
- **Hoerner**, *Fluid-Dynamic Drag* (`~/Downloads/Fluid-dynamic_drag__Hoerner__1965_text.pdf`;
  also Drive): Thrusty's tumbling constants are right; the ½ average and the
  1.2 floor below Mach 3 are Thrusty's own; rotating cubes (Fig. 17, p. 16-14)
  are the one orientation-averaged measurement.
- **Jorgensen** TN D-6996 (`~/Desktop/80643181.pdf`, the 0–180° report), TR
  R-474 and TN D-7228 (`~/Desktop/Stuff/Thrusty-papers/`): 0–180° build-up;
  its potential term at a flat face is contradicted by the data below.
- **Jernell** TM X-1658 (`~/Desktop/19680026721.pdf`): flat-ended cylinders
  only to about 100°; near end-on the CP moves toward the leading face at every
  Mach; mid-length from about 25° to 90°.
- **Tobak & Peterson** TR R-203 (`~/Downloads/20010120134.pdf`): the only
  settle-or-tumble criterion; one stable trim, entry from outside the
  atmosphere; usable only as a labelled estimate. Garber 1959, Norling 1962
  (`~/Desktop/garber1959.pdf`, `~/Desktop/norling1962.pdf`), Regan 1984 and
  Regan & Anandakrishnan 1993 (complete, `~/Desktop/Stuff/Thrusty-papers/`):
  small-angle envelopes only.
- **Romaniw** 2013, Georgia Tech dissertation (Drive, id
  `12a4--7Hd-JpbF2Rl37XTvT7WHCq9cNlE`), Appendix A pp. 289–291: solid motor
  case, insulation and nozzle mass against thrust; his own regressions, data
  not tabulated. The MER folder (Drive `1j3157f0u6UjmJ2KsKPauePtgaBZdY9GK`, 18
  papers) has no other case/nozzle split; Rohrschneider §6 is liquid-engine
  constants; Shu et al. 2020 Table 11 is the κ_E source.
- The AFGL reentry handbook (AFGL-TR-78-0019) cited in the user's note
  `~/Downloads/spent-stage-tumbling.md` **may not exist**; nothing from it is used.
- The file named "Dynamics of Atmospheric Re-Entry … Anna's Archive.pdf" is
  actually Hankey, *Re-Entry Aerodynamics* (1988).

## Tracked items outside this phase

1. The object editor drops `structure_material` / `structure_limit_K` on save.
2. Per-location heating (`heating_by_location`) is built but not wired into
   any screening; pass `effective_ro(params)` and `run_attitude(result)`.
3. `ro_xlsx` writes and reads the derived `separation_mode` (a four-inputs slip).
4. `glider_ld._CDN_VS_MCROSS` disagrees with Jorgensen's crossflow-drag curve
   (TR R-474 Fig. 1, TN D-6996 Fig. 1) by up to about 10%; re-read Gowen &
   Perkins Fig. 7 before changing it.
5. The shipped **Strypi VII R stalls** at Mach 1.001 (~8.5 s) at any launch
   site tried; pre-existing.
6. **Nose-cap heating validation (open since the heating revision).** Tauber
   Eq. 40 reads 29% low in flux, about 8% low in temperature, against the
   Stardust detailed computation (Trumble et al. 2010, 942 W/cm² at 51 s) —
   outside the 3–5% temperature target. Against FIRE II flight (Hash et al.
   2007) it is within about 5% in temperature, but the convective part is
   18–24% below fully catalytic computation. Read so far as a gap between
   correlations and CFD, not a Thrusty error; not closed. See
   `heating_locations.ACCURACY['nose_cap']` and METHODS §13.15.
7. **Body nose length and nose radius.** Scud-B and Al Hussein store
   `body_nose_length_m` 0 and `nose_radius_m` 0, so their nose-cap and
   windward-face heating report "not given", and the held boost-nose fix
   (Part IV §19a) waits on the same numbers. Needs a sourced value; do not
   invent one.
8. **Conductivity for a solid, non-ablating nose tip.** `heating_by_location`
   evaluates a solid tip with `heating_solid.cone_tip_response`, which needs
   the material's density, specific heat and AXIAL conductivity. The catalog
   (`heating.TPS_MATERIALS`) carries `k_W_mK` only for three ablators, and
   that value is through-thickness (bondline screen); ablators do not take the
   solid path. So every solid non-ablating tip (C/C-SiC, carbon-carbon, RCC,
   UHTC, metals) reports "conductivity not in the materials catalog". The
   SHEFEX II check's 17 W/(m K) (Böhrk et al. 2012, Table 1, exponent
   unreadable in the scan) lives only in `test_heating_solid.py`. Likely fix:
   read the TPSX archive already in the repo (`data/tpsx/catalog.json`; C/SiC
   is id 26; `test_tpsx_crosscheck.py` shows how fields are pinned) for the
   isotropic or in-plane conductivity of each solid tip material, wire it as
   the axial value with its direction stated, and pin it in the cross-check
   test. TPSX values are mostly room temperature; carbon composites change a
   lot with temperature, so state that limit in the output.
9. **Wing leading edge with angle of attack** (Tauber Eq. 49): no test case.
   **Windward face**: reported as a flat-plate–cone band; neither end meets
   3–5% yet (STS-3, Throckmorton et al. NASA TM 84500).

## Working notes

- Tests: system `python3 -m pytest -q -p no:cacheprovider` (the `.venv` has no
  pytest). The spreadsheet tests need `openpyxl`, which is not installed: put
  it in the session scratchpad with `pip install --target <scratch>/pylib
  openpyxl` and run with `PYTHONPATH=<scratch>/pylib`, or they skip.
- Any script that dumps trajectories must blank `USER_FLIGHT_PLAN_DIRS`,
  `USER_REENTRY_PLAN_DIRS` and `USER_RO_DIRS` first (CLAUDE.md).
- PDFs: `pdftoppm` is not installed. Text via `pypdf` (install to the
  scratchpad; open with `PdfReader(path, strict=False)` and logging disabled —
  one Regan file has a damaged index that floods warnings). Page images via a
  small Swift script using PDFKit (`PDFDocument`, `page.draw(with:.mediaBox,
  to:)` into an `NSBitmapImageRep`), then the Read tool on the PNG.
- Files over 10 MB in the Drive cannot be downloaded through the Drive tools;
  use the local copies listed above.
- The user prefers plain-language discussion before building, short
  recommendations rather than surveys, and explicit approval before commits.
