# Handoff: Part IV Phase 3, spent stages (written 2026-10-01)

For a new Claude session picking up the separation-handoff work. Read
`CLAUDE.md` and `FRONT_END_DESIGN.md` Part IV (sections 16–19d) first; this
note says where the work stopped and what was decided along the way.

## Where it stopped

The previous session was blocked by the auto-mode safety check (it reacted to
earlier conversation content, not to any action). Nothing was lost.

**Committed** (on `main`, not pushed), newest first:

| Commit | What |
|---|---|
| `857cc42` | Phase 3 part 1: spent stages leave at their own burnout (the debris clock now starts at `booster_core_delay_s`); `integrate_debris` runs to the main flight's tolerances and lands on the terrain model |
| `fc2af62` | Part IV: Phase 3 revised from the readings; TN D-7228 title corrected in `data/REFERENCES.md` |
| `607ff0c` | Part IV: Klett read from primary; the unverified AFGL handbook withdrawn |
| `5b661b3` | Phase 2: a body's object file stores 0 = "from booster" for mass, diameter, length; pairing rule (`check_pairing`); editor saves zeros |
| `41aee67` | Phase 1: `hand_off()` record, `result['handoff']`, `reentering_airframe()` |
| `63dfa96` | Part IV design + Phase 0 tests (`test_handoff.py`) |

**Uncommitted, built, suite passes (1172) but no tests of their own yet:**

- `data/aero/jernell_1968_flat_cylinders.csv` (new). Jernell, NASA TM X-1658,
  flat-ended cylinder l/d 6, Mach 1.50/1.90/2.36/2.86, α 0–90°: C_N, C_A (cross-
  section area) and centre of pressure from the leading face. Digitised from a
  150 dpi scan; precision in the file header.
- `spent_stage_aero.py` (new). Drag of a spent stage as C_D·A against Mach:
  - **random tumbling**: Jernell's C_D(α) = C_N sin α + C_A cos α averaged over
    random orientation (mirrored beyond 90°, an inference), C_N scaled by l/d
    (Jernell: normal force follows planform area); held below Mach 1.5;
    linear in Mach from 2.86 to Klett's value at Mach 10; Klett eq. 36 above;
  - **trimmed**: trim where the measured CP (Jernell Fig. 9, Mach 1.50 and 2.86
    only, interpolated) meets the stage's empty CG; held outside 1.5–2.86;
  - **liquid stage CG**: engine share κ/(1+κ) of dry mass at the base, κ from
    Shu et al. 2020 via `mass_estimator._KAPPA_E_DEFAULT` (lower 0.25, upper
    0.12), the rest spread evenly → CG 0.40 (lower) or 0.45 (upper) of the
    length from the base, so the base leads;
  - **solid stages and strap-on casings**: CG unknown → tumbling only;
  - **finned stages** (fins or grid fins): trim unknown → tumbling only;
  - each stage's two curves are tabulated once on a Mach grid (`_MACH_GRID`).
- `trajectory.py`:
  - `integrate_debris(..., cda_of_mach=None, mass_kg=0.0)`: drag from C_D·A(Mach);
  - `_fly_band()`: flies a piece trimmed and tumbling, reports ONE impact point,
    the great-circle midpoint of the two (user's instruction: "report one
    number, the midpoint of the range"); time and speed are the means; the
    track is the two tracks averaged at equal fractions of flight time; the
    milestone carries `impact_band` (both ends, leading end, notes) but the
    timeline shows only the midpoint;
  - spent stage bodies and strap-on casings use it; **the fairing is unchanged**.

Effect on shipped vehicles (launch 33°N 44°E, azimuth 60°): main trajectories
unchanged; most debris points move a few km. Trim-to-tumble spread behind each
midpoint: AUR stage 1 44 km, Shahab-3 stage 1 17 km, upper stages 1–7 km,
solid and finned stages 0 (tumbling only).

## The open problem: speed

The suite went from about 1.6 min to **6.9 min**: every spent piece is now
flown twice at rtol 1e-8, atol 1e-6 m, max_step 5 s. That is metre-level
precision against a kilometre-scale spread. The previous session was about to
measure the impact-point change against run time for looser debris tolerances
(e.g. rtol 1e-7 / atol 1e-3 / 10 s and rtol 1e-6 / atol 0.1 / 20 s), on
Taepodong-II, AUR, Generic ICBM, Shahab-3 and Minotaur-IV, when it was blocked.
The design (Part IV §19, Phase 3) says "the main flight's integration
tolerance", so **a looser tolerance needs the user's agreement** — propose it
with the measured numbers. Profiling showed `ecef_to_geodetic` dominates the
debris equations of motion.

## Next steps, in order

1. Measure tolerance vs accuracy vs time (above); propose; apply once agreed.
2. Tests (`test_handoff.py` or a new `test_spent_stage_aero.py`):
   - `random_cd` reproduces the data average at the tested Machs (l/d 6: about
     7.25 at 1.5, 6.62 at 2.86) and equals `klett_random_cd` at Mach 10 (5.893
     for l/d 6); held below 1.5; continuous at 2.86 and 10;
   - Klett eq. 36 check: (0.393 + 0.178 D/L)(2 − K) on area L·D;
   - `trim_alpha`: CG 0.40 from the leading face → about 18° at Mach 1.5 and
     11.5° at 2.86; a CG past the CP plateau → None;
   - `spent_stage_drag`: liquid → trim with base leading; solid → tumbling
     only; finned or grid-finned → tumbling only;
   - `_fly_band`: midpoint lies between the two ends; with no trim it equals
     the tumbling impact; `impact_band` present on the milestone;
   - `integrate_debris` with a constant `cda_of_mach` equals the β path.
3. Docs: `NOTICE.md` (add a row for `data/aero/jernell_1968_flat_cylinders.csv`:
   NASA TM X-1658, U.S. Government work, values digitised by Thrusty);
   `data/REFERENCES.md` (Jernell row; Shu et al. if not present); METHODS
   (spent-stage drag section, §14.3 debris); README and CLAUDE.md layout rows
   for `spent_stage_aero.py`; FRONT_END_DESIGN.md §19d "as built".
4. Show the user before/after debris impact points per shipped vehicle, then
   commit as "Phase 3 part 2".

## Decisions the user made (do not re-litigate)

- One handoff at separation in both separating and body modes; files never
  store the booster's numbers (Part IV §16–18).
- Fins stay on a handed-off body; a flight-plan option to drop them comes later.
- Where a tumbling stage lands matters more than its heating, for now.
- **Finned stages: band only** (trim unknown) — with the midpoint rule, flown
  tumbling only.
- Outside Mach 1.5–2.86: hold Mach 1.5 values below; tumbling drag blends to
  Klett above; trim held at Mach 2.86.
- **Report one number: the midpoint of the range.**
- Boost-nose fix (a body's nose length during boost) is **held** until nose
  lengths are sourced (Part IV §19a).
- The user sources the stage-impact benchmark themselves.

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
