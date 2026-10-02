# AUR: provenance sheet (draft 3, 2026-10-02)

The first re-admission sheet under `LIBRARY_RESET_PLAN.md`. It lists every
value stored for AUR, where it came from, and what is still open.

Sources used here:

- **Notes** — the user's draft paper *Analysis of the U.S. Intermediate-Range
  Hypersonic Weapon* (Google Doc "Dark Eagle", read 2026-10-02; the user
  calls it incomplete). It names its own sources: environmental
  assessments, canister markings in photographs, a DoD still image and
  diagrams, a launch video by John Concilus, navigational warnings, a CBO
  description of the trajectory, statements to the Secretary of Defense,
  the Northrop Grumman Propulsion Products Catalogue. Those documents are
  not themselves in the repository or cited by number.
- **History** — the original definition of AUR, a Python builder removed
  2026-07-05 (recoverable at `6707dd1^`), whose numbers are the notes'
  model table.
- **User** — stated in conversation.

Claude has supplied no number or source from memory.

"Kind": *published* (a document states it), *measured* (from imagery or
video), *modelled* (the user's choice within what the evidence allows),
*estimated* (from a named estimator), *assumed*.

AUR as flown is four files: the booster, its flight plan, the object the
plan names (C-HGB) and that object's reentry plan.

## 1. Booster — `AUR.booster.json`

### Whole vehicle (constraints the stage numbers must meet)

| Quantity | Value | Source | Kind |
|---|---|---|---|
| Diameter | 34.5 in = 0.8763 m | Notes: environmental assessments; the tests are of the "34.5 inch AUR"; checked against a DoD still image | published, checked by measurement |
| Overall length | 33.6 ft = 10.2 m | Notes: environmental assessments; checked against the DoD image | published, checked by measurement |
| All-up mass with payload | 16,300 lb ≈ 7,400 kg | Notes: canister markings in photographs (March 2021, confirmed November 2025): 20,500 lb loaded, 4,200 lb spent | measured (read from markings) |
| Total propellant | "15,000 or 20,000 lb" | Notes: a Supplemental Environmental Assessment gives both, apparently rounded up | published, imprecise |
| Payload | 1,000 lb ≈ 450 kg (FE-2); 750 lb (FT-3) | Notes: environmental assessments | published |

### Stage 1

| Field | Value | Source | Kind | Open |
|---|---|---|---|---|
| Diameter | 0.8763 m | as above | published | |
| Length | 5.0 m | Notes, model table; stage split from DoD diagrams (motor volumes about 7:3) | modelled | |
| Propellant | 4,509 kg | Notes, model table: 14,000 lb total propellant, chosen between the mass from the canister and the rounded assessment figures, split 7:3 | modelled | The notes also say the first-stage motor "should contain about 6,400 kg" from its volume; that reads as the total for both stages |
| Burnout mass | 454 kg | Notes: "dry masses around 9 percent for each stage … derived from existing GEM and Orion rocket motors" | modelled | Which motors, and their dry fractions |
| Launch mass (`mass_initial`) | 7,013.5 kg | 4,963 + 2,028 + 22.5 fairing (user, 2026-10-02: the fairing is added to the mass) | derived | With the 450 kg object the stack is 7,463.5 kg against 7,400 kg from the canister: see §5 |
| Burn time | 54 s | Notes, model table. The video shows "approximately 56 seconds" | modelled from a measurement | 54 or 56? |
| Specific impulse | 280 s | Notes, model table; no basis stated | assumed | |
| Nozzle exit area | 0.30 m² (radius 0.31 m) | Notes, model table; no basis stated | | Measured from an image, or assumed? |
| Solid motor | yes | Notes ("two-stage solid rocket booster"); user | published | |
| Grain | regressive; Thrusty's "double anchor" curve | Notes: high early thrust implies a regressive grain, by analogy with the Orion 32XL (maximum 224 kN at 11 s, 1.4 × its 156 kN average over 52.4 s; Northrop Grumman Propulsion Products Catalogue) | modelled by analogy | The curve flown is Thrusty's generic one (Shafer 1959): peak at ignition, 2 × the final thrust. The Orion 32XL's peaks at 11 s at 1.4 × average |
| Peak thrust | 290 kN | User: measured from video — acceleration over the first few seconds times the mass. Notes: "an average thrust of about 300 kN over the 2 s–7 s burn time that is visible", scale from the 10.2 m length, mass 7,400 kg, gravity accounted for (video by John Concilus) | measured | Three points in §5 |
| Average thrust | 230 kN (not stored) | Notes: "agrees with both the observed burn time and propellant masses" and with a maximum near 300 kN | modelled | |
| Fins | none | | | Confirm |

### Stage 2

| Field | Value | Source | Kind | Open |
|---|---|---|---|---|
| Diameter | 0.8763 m | as above | published | |
| Length | 2.6 m | Notes, model table | modelled | |
| Fuelled mass | 2,028 kg | Notes (2,027 in the table) | modelled | |
| Propellant | 1,842 kg | Notes, model table | modelled | |
| Burnout mass | 186 kg | Notes: 9.2% dry fraction | modelled | |
| Burn time | 63 s | Notes, model table. The video shows "at least 46 seconds" | modelled | 63 s is not what was observed; it follows from the thrust and propellant chosen |
| Specific impulse | 280 s | Notes, model table; no basis stated | assumed | |
| Nozzle exit area | 0.30 m² | History; the notes give a nozzle only for stage 1 | | Copied from stage 1? |
| Thrust | 80 kN (derived as 80.3) | Notes, model table; no basis stated | modelled | |
| Grain | none entered: constant thrust | | | |

### Fairing

| Field | Value | Source | Kind | Open |
|---|---|---|---|---|
| Shape | cone | User, 2026-07-28 | stated by the user | |
| Length | 2.67 m | File notes. The user's notes give the payload section as 2.6 m | | 2.6 or 2.67? |
| Base diameter | 0.8763 m | | | |
| Mass | 22.5 kg | Akin, ENAE 791: M = 4.95·A^1.15 on the cone's 3.72 m² | estimated | |

Not entered: aft skirt, nozzle protrusion, interstage.

## 2. Flight plan — `AUR.flightplan.json`

The file has no `source` and no `notes`. The user's notes describe a
fitted trajectory that is **not** the one in the file.

| Field | In the file | In the user's notes | Source of the constraint |
|---|---|---|---|
| Launch elevation | 90° | 80° | Notes: stated to the Secretary of Defense by Lt. Col. Mainwaring |
| First turn | 0 to 21.7 s, to 25° | begins at 1 s, complete at 44 s, burnout angle 24° | fitted |
| Second turn | none | from second-stage ignition to 86 s, burnout angle −2° | fitted |
| Apogee to reproduce | not recorded | about 120 km | Notes: Congressional Budget Office |
| First-stage drop zone | not recorded | about 300 km downrange | Notes: navigational warnings |
| Second-stage drop zone | not recorded | about 2,000 km downrange | Notes: navigational warnings |
| Range | not recorded | 3,500 km stated; warnings span 3,500–4,500 km | Notes: statements to the Secretary; navigational warnings |
| Fairing jettison | 0 km = Thrusty's heating rule | a fairing drop zone is in the warnings | |

The file's values are the old builder's "starting values; tune
experimentally". The plan to admit is the fitted one, with the navigational
warnings (coordinates, dates) recorded as what it reproduces. **The drop
zones are the stage-impact benchmark the spent-stage work has been waiting
for.**

## 3. Object — `C-HGB.ro.json`

| Field | Value in the file | Source | Kind | Open |
|---|---|---|---|---|
| Mass | 450 kg | File: U.S. Navy SSP, Final EA/OEA for Flight Experiment-2, Dec. 2019, §2.5.6; U.S. Army, Biological Assessment for Flight Test-3, 22 Sept. 2020, §2.2.1. Notes: 454 kg "including approximately 115 kg of tungsten" | published | |
| Length, base diameter, nose radius | 1.5 m, 0.58 m, 0.02 m | File: measured with `image_measure.py`, May 2026; "the image, scale anchor and pixel quantum are not recorded" | measured, record lost | Re-measure with the image recorded |
| Shape | cone | | | |
| Ballistic coefficient | 15,000 kg/m² | File: "a PLACEHOLDER with no public source". **Notes: "we estimate a beta of around 2000"**, from a drag coefficient of 0.294 in a Chinese paper and the 454 kg mass | assumed | The file and the notes differ by a factor of 7.5 |
| Glide L/D | 2.0 | File: "a representative estimate". Notes: Rigali on SWERVE, 1.2–1.8 at 5–15° angle of attack; a Chinese paper on AHW, maximum 1.4–2.1 | modelled within a published range | The citations for Rigali and the Chinese paper |
| Control surfaces | "unknown" | | | |
| Emissivity | 0.85 | none | | |
| Thermal protection, nose / body | UHTC / carbon phenolic | none | | No source |
| Heating locations | nose cap, windward face | none | | |

## 4. Reentry plan — `C-HGB.reentryplan.json`

No `source`, no `notes`.

| Field | Value | Source | Open |
|---|---|---|---|
| Glide law | damped glide | File notes on the object | |
| Damping ratio | 0.7 | none | |
| Pull-up limit | 10 g | none | |
| Skip count | 1 | none | |
| Terminal dive | on | none | Notes: impact near 400 m/s inferred from crater size in the environmental documents; a check, not a setting |
| Commanded L/D | 2.0 | equals the object's | |
| Glide altitudes to reproduce | not recorded | Notes: CBO, "most of its flight at an altitude between 30 km and 40 km"; pull-up from 30 km to 40 km | |

## 5. Open points

1. **Total mass.** With the fairing added the stack is 7,013.5 kg and, with
   the 450 kg object, 7,463.5 kg. The canister markings give about 7,400 kg
   for everything. The model table's 7,440 kg already ran 40 kg over.
   Either accept 64 kg (0.9%) as inside the precision of the markings, or
   take the fairing's mass out of something else.
2. **The thrust measurement and how Thrusty uses it.**
   - It was taken at launch, at sea level. Thrusty's peak thrust is a
     vacuum figure, from which it subtracts ambient pressure times the
     nozzle exit area: 101 kPa × 0.30 m² ≈ 30 kN. So a stored 290 kN flies
     as about 260 kN off the pad, below what was measured. A measured
     290–300 kN at sea level corresponds to a vacuum figure near 320–330 kN.
   - It is an average over 2–7 s, not the value at ignition. Thrusty's
     curve puts the peak at t = 0 and has already fallen about 6% by 4.5 s.
   - The notes say "about 300 kN"; the file has 290 kN.
   - A vacuum peak near 320–330 kN on this curve would deliver 13.0–13.4
     MN·s against the 12.4 MN·s that 280 s and 4,509 kg imply; 290 kN
     delivers 11.7. The measurement and the 280 s are closer together than
     the file makes them look, once the sea-level correction is made.
3. **Burn times.** 56 s observed against 54 s stored; "at least 46 s"
   observed against 63 s stored.
4. **Specific impulse 280 s**, both stages: no basis recorded.
5. **The flight plan in the file is not the fitted one** (§2).
6. **C-HGB's ballistic coefficient**: 15,000 (file, a placeholder) against
   about 2,000 (notes).
7. **Fairing length**: 2.67 m against 2.6 m.

## 6. What admission still needs

- The documents behind the notes, cited so someone else could find them:
  the environmental assessments (title, date, section), the navigational
  warnings (numbers, dates, coordinates), the CBO report, the catalogue
  page for the Orion 32XL, the Rigali and Chinese papers, and where the
  video and the canister photographs are kept.
- Decisions on the open points in §5.
- A ruling on *modelled* and *assumed* values: most of the stage masses
  are the user's model, constrained by measurements but not themselves
  published. The gate as first written ("every value has a source")
  should probably read "every value has a stated basis", with the kind
  shown. That is the user's call.

## 7. Decisions of 2026-10-02 and the candidate files

The user decided: cap the all-up mass at 7,400 kg and take the excess from
the stages; the measured thrust is a sea-level figure; the grain is
strongly regressive (double anchor); match the video, allowing that the
visible burn includes some tail-off, but six seconds of it is too much
and the thrust was too high; the launch angle is 80°; the fairing is 2.7 m
long; use the photographed stage lengths.

The current `booster_library/AUR.booster.json` is left as it is: under the
reset plan it becomes a test stand-in and its numbers must not move. The
re-admission candidate is built beside this sheet:

- `provenance/candidates/AUR.booster.json`
- `provenance/candidates/AUR.flightplan.json`
- `provenance/AUR_warning_boxes.json` (what the plan is fitted to)

| | Stand-in (current file) | Candidate | Basis |
|---|---|---|---|
| Stage lengths | 5.0 m, 2.6 m | 4.95 m, 2.36 m | measured on the launch photograph (talk notes) |
| Fairing | 2.67 m, 22.5 kg | 2.7 m, 22.7 kg | user; Akin's relation on the new area |
| Stage 1 propellant / burnout | 4,509 / 454 kg | 4,467.9 / 449.9 kg | scaled by 0.99089 so the stack with the 450 kg object is 7,400.0 kg; dry fraction and 7:3 split kept |
| Stage 2 propellant / burnout | 1,842 / 186 kg | 1,825.2 / 184.3 kg | same |
| Stack launch mass | 7,013.5 kg | 6,950.0 kg | |
| Stage 1 burn time | 54 s | 54 s | about 55 s seen, less a second or so of tail-off |
| Stage 1 peak thrust (vacuum) | 290 kN | 302.9 kN | follows from 54 s, 280 s and the propellant on the double-anchor curve |
| … as it would be measured | | about 260 kN at sea level over 2–7 s; 2.8 g off the pad | between the two video figures, 222 kN and 290–300 kN |
| Launch elevation | 90° | 80° | user |
| Pitch plan | one turn, 0–21.7 s to 25° | 0–40 s to 22°; 54–120 s to −4°; yaw to 108° at 70–80 s | fitted to the warning boxes: §9 |

The three lengths sum to 10.01 m against the published 10.2 m; the
difference (0.19 m) is not assigned to anything.

## 8. The talk notes of 29 Sep 2026 and what they change

The user also supplied speaker notes for a talk (29 Sep 2026), newer than
the draft paper. They agree with it on diameter, length, mass and payload,
and differ on four things:

1. **The thrust.** The talk gives "on the order of 50,000 lbf, a bit over
   2 g off the pad", tracked against the SLC-46 lightning towers (two 183
   ft towers) for scale. 50,000 lbf is 222 kN. The draft paper gives
   "about 300 kN" over 2–7 s, scaled from the missile's own length, and the
   user gave 290 kN in conversation. These cannot all be the same
   measurement. What each implies, at 280 s and this propellant, on the
   double-anchor curve:

   | Sea-level thrust, 2–7 s | Vacuum peak | Burn time | Off the pad |
   |---|---|---|---|
   | 222 kN (talk) | 262 kN | 62.5 s | 2.2 g |
   | 250 kN | 292 kN | 56.0 s | 2.6 g |
   | 290 kN (candidate) | 336 kN | 48.7 s | 3.2 g |
   | 300 kN (draft paper) | 347 kN | 47.1 s | 3.4 g |

   The talk's 222 kN matches its own "a bit over 2 g", but then the motor
   would have to burn 62 s, longer than the 55 s seen, unless the specific
   impulse is nearer 250 s or the curve falls further than a double
   anchor's. About 250 kN would make thrust, burn time and 280 s agree
   with no tail-off at all. The candidate uses 290 kN as instructed.
2. **Component lengths**, measured from a launch photograph calibrated by
   the published diameter and length: first stage about 4.95 m, second
   stage about 2.36 m, fairing about 2.67 m. The files have 5.0, 2.6 and
   (now) 2.7 m. The second stage differs by 0.24 m.
3. **Burn time**: "about 55 s" for the first stage; the second stage's end
   is "fuzzier" because of tail-off.
4. **The trajectory.** Fitting NAVAREA IV 221/23 (March 2023, hazard boxes
   A–G) needs an apogee of about 160 km; 120 km "can't hit the drop zones".
   The kinetic range is "greater than 4,000 km". So the plan to admit is
   the 160 km fit, and the warning itself (its text and coordinates) is the
   benchmark. The user's event log of 28 Sep 2026 with the old numbers:
   apogee 160 km, first stage down at 111 km, second stage at 2,142 km,
   fairing at 2,073 km, glider at 4,238 km.

Flown under that pitch plan without re-fitting, the candidate gives an
apogee of 216 km and puts the first stage at 130 km and the second at
2,630 km: its higher thrust and shorter burn need the plan fitted again,
which needs the warning's box coordinates.

Glider, from the talk: lift-to-drag "peaks near 2 at about 10° angle of
attack and barely changes with Mach number" (a Chinese paper on the "AHW
optimized configuration" at Mach 5, 10 and 20), which supports the file's
2.0; the glider levels off "near 75,000 ft, about 23 km"; the thermal
protection, not the booster, limits the system.

## 9. The fit to the navigational warning (2026-10-02)

Boxes from the user's Google Earth file (`AUR_warning_boxes.json`),
measured from the launch site:

| Box | Distance | Bearing to centre |
|---|---|---|
| A | 6–52 km | 102° |
| C | 49–174 km | 102° |
| B | 173–315 km | 103° |
| E | 1,837–2,396 km | 105° |
| G | 3,489–4,468 km | 106° |
| D | 1,734–2,126 km | 90° |
| F | 3,055–3,541 km | 78° |

A, C, B, E and G lie along one track. D and F lie well north of it; what
they are for is not known here.

The candidate flown from SLC-46 at azimuth 101°, with the user's turn
timings and yaw, scanning the two burnout angles:

| Burnout angles (stage 1, stage 2) | Apogee | First stage | Second stage | Fairing |
|---|---|---|---|---|
| 20°, −5° | 133 km | 92 km, in C | 2,051 km, in E | 1,837 km, outside |
| 20°, −4° | 139 km | 92 km, in C | 2,123 km, in E | 1,924 km, in E |
| 20°, −1° | 160 km | 92 km, in C | 2,346 km, in E | 2,183 km, in E |
| **22°, −4°** (candidate) | **160 km** | **103 km, in C** | **2,316 km, in E** | **2,186 km, in E** |
| 23°, −5° | 163 km | 109 km, in C | 2,316 km, in E | 2,200 km, in E |
| 22°, −3° | 167 km | 103 km, in C | 2,378 km, outside | 2,256 km, in E |
| 25°, −5° (the 28 Sep plan) | 185 km | 123 km, in C | 2,476 km, outside | 2,388 km, outside |

- **All three pieces fall in their boxes for an apogee between about 139
  and 163 km.** That agrees with the talk's "about 160 km" and with its
  finding that 120 km cannot hit the boxes.
- The first stage falls in box C (49–174 km), not B. The draft paper's
  "about 300 km" for the first stage is box B's far edge; nothing here
  lands in B.
- How the spent stages are flown: the first stage (released at about
  29 km) is spun up by the air to several hundred degrees a second and
  keeps tumbling, so its end-over-end point is reported; the second stage
  settles, so its trimmed point is reported.
- The glider flies about 5,200–5,300 km on the shipped C-HGB object and
  plan with no turns, past box G's far edge (4,468 km). The user's run of
  28 Sep reached 4,238 km with ±45° banks. The object's ballistic
  coefficient and lift-to-drag ratio are placeholders (§3), so this says
  little yet.
- Burnout speed 5.2–5.3 km/s (the talk: "about 5 km/s or Mach 15").

This is a fit of the plan to the warning, which is what a flight plan is
admitted on. It is also the first comparison of Thrusty's spent-stage
impacts with reported drop zones; it becomes a test once the candidate is
admitted and the warning's text is recorded.
