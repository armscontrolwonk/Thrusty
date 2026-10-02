# AUR: provenance sheet (draft 2, 2026-10-02)

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
