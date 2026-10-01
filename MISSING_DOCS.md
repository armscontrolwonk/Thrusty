# Documents to track down

Sources Thrusty needs and does not have. Kept by the user; add a row when a
gap is found, move it to "Received" when the document arrives (with where it
was put), and add it to `data/REFERENCES.md` once something from it is used.
Citations are given as the citing document gives them; where a title or
number is uncertain it says so. Do not use a number from any of these until
the document itself has been read.

## Wanted

### Spent stages: forces, attitude, impact (FRONT_END_DESIGN.md Part IV; TODO.md item 10)

| # | Document | Why | Cited by / lead |
|---|---|---|---|
| 1 | The Space Shuttle SRB reentry aerodynamic database (four- and five-segment), or the wind-tunnel reports behind it: forces and centre of pressure at Mach 0.5–6, 0–180°, all roll angles | **First priority.** The numbers for a real spent stage (nose cone, nozzle, flared aft skirt). Purinton et al. describe it and were made to strip the values from their plots. Would replace the flat-ended cylinder for stage ends and settle why real boosters trim near broadside | Purinton et al. 2011; Shuttle-era MSFC/Rockwell reports on NTRS, not yet identified by number |
| 2 | Bauer, S. X. & Krist, S. E., "Aerodynamic Assessment of the Ares I-X Flight Test Vehicle", 58th JANNAF Propulsion Meeting, April 2011 | The aerodynamic database behind the Ares I-X reentry simulation, including the upper-stage simulator's centre of pressure against angle of attack at Mach 4.5 (Tartabini & Starr Fig. 8) | Tartabini & Starr 2011, ref. 4 |
| 3 | Smith, R. M. & Bryant, R. B., "Significant Technical Results for the Ares I-X Flight Test", 58th JANNAF Propulsion Meeting, April 2011 | Flight results: splashdown positions and reconstructed attitudes for both stages, a candidate stage-impact benchmark | Tartabini & Starr 2011, ref. 2 |
| 4 | Starr, B. R., Gowan, J. W. & Thompson, B. G., "Ares I-X Range Safety Analyses Overview", 58th JANNAF, April 2011; and Tarpley et al., "Ares I-X Range Safety Trajectory Analysis and IV&V", AIAA Atmospheric Flight Mechanics Conference 2011 | Impact ellipses and how they were built; coordinates of the footprints | Tartabini & Starr 2011, refs. 10, 11 |
| 5 | Starr, B. R., Gumbert, C. R. & Tartabini, P. V., "Ares I-X Test Flight Reference Trajectory Development", 58th JANNAF, April 2011 | The ascent trajectory and mass properties needed to build an Ares I-X booster file for a benchmark run | Tartabini & Starr 2011, ref. 1 |
| 6 | Jorgensen, L. H. & Treon, S. L., NASA TM X-580 (1961): a rocket booster tested from 0° to 180°, Mach 0.6 to 4 (title not confirmed) | A finned or booster-shaped body through 180°: fin forces beyond 58° and the base-first side | Jorgensen TR R-474 / TN D-6996; tried once, not obtainable |
| 7 | Lockwood, NASA TN D-3932: flat-front cylinders (title not confirmed) | Subsonic and transonic flat-faced cylinder data, below Jernell's Mach 1.5 | Jorgensen TN D-6996 |
| 8 | Kelly, 1954: blunt-based bodies (full citation not in hand) | Base-first forces | Jorgensen TR R-474 |
| 9 | Randall, Sandia SC-TM-64-528 | The source of Klett's side-on, end-on and end-over-end cylinder drag | Klett 1964, ref. 2 |
| 10 | Stoney & Swanson (NACA; number not in hand): pressure on the flat face of a cylinder | The 0.909 end-face factor in Klett eq. 22 | Klett 1964 |
| 11 | Shuttle SRB reentry aerodynamic data (wind-tunnel reports or data book, 0–180°) | The largest body of 0–180° data on a spent booster; not yet identified by title | to be identified on NTRS |
| 12 | Pitch-damping data for a cylinder or spent stage at large angle of attack | The swing in `_attitude_verdict` is undamped; damping decides how fast a settled stage stops swinging | none yet |
| 13 | Separation tumble rates: any user's guide or flight report giving the rate a stage is left with (retro-rockets, springs, tumble motors) | Stages released above the air get no spin from it; their rate is the mechanism's | Ares I-X used four tumble motors (Tartabini & Starr); King, Hengel & Wolf, "Ares I First Stage Booster Deceleration System: An Overview", AIAA 2009-2984 |
| 14 | Component masses of real solid motors: case, insulation, nozzle (a manufacturer's motor catalogue or NASA motor data sheets) | To check the nozzle share now taken from the ratio of Romaniw's fits | none yet |
| 15 | A reported spent-stage impact zone for a shipped vehicle with a known launch (NOTAM, recovery report, test announcement) | The stage-impact benchmark | user is sourcing |
| 16 | AFGL-TR-78-0019, a reentry handbook said to tabulate cylinder trim angle against CG offset | Existence unverified; nothing from it is used | the user's note `spent-stage-tumbling.md` |

### Other open items

| # | Document | Why | Lead |
|---|---|---|---|
| 17 | Gowen & Perkins, NACA TN 2960, a clean copy of Fig. 7 | `glider_ld._CDN_VS_MCROSS` disagrees with Jorgensen's crossflow-drag curve by up to 10%; the scan in hand is cut off at the right edge | `data/REFERENCES.md` |
| 18 | Böhrk et al. 2012 (SHEFEX II), a legible copy of Table 1 | The conductivity exponent is unreadable in the scan; needed for solid nose-tip conduction | `test_heating_solid.py` |
| 19 | A sourced nose length and nose radius for Scud-B and Al Hussein | Their nose-cap heating reports "not given"; the boost-nose fix is held on the same numbers | Part IV §19a |
| 20 | A third flight case for nose-cap heating (beyond Stardust and FIRE II) | To decide whether Tauber eq. 40's 29% gap is the correlation or the comparison | `heating_locations.ACCURACY` |
| 21 | Wilhite 2012 (as cited by Romaniw 2013, Table A1) | The source of the component MERs Romaniw tabulates | Romaniw 2013 |

## Received

| Date | Document | Where | What it gave |
|---|---|---|---|
| 2026-10-01 | Tartabini, P. V. & Starr, B. R., "Ares I-X Separation and Reentry Trajectory Analyses", AIAA 2011 (NTRS 20110014618) | `~/Desktop/20110014618.pdf` | Read. A real unstable stage released at high dynamic pressure tumbles within seconds; at low dynamic pressure it would not for about 40 s. The first stage reentered tail-first in flight; pre-flight Monte Carlo gave 4% nose-first, 59% broadside, 37% tail-first, decided mainly by CG and centre-of-pressure position. Footprints: first stage 32.7 × 9.2 nmi centred 121.4 nmi from the pad; upper stage 34.2 × 18.0 nmi at 131.5 nmi. Fig. 8 (centre of pressure against angle at Mach 4.5, read from a rendered page) is recorded in Part IV §19f; Fig. 13 (tumble rate against time) not yet read |
| 2026-10-01 | Purinton, D. C., Blevins, J. A., Pritchett, V., Haynes, D. & Carpenter, M., "Aerodynamic Characterization and Simulation of a Solid Rocket Booster During Reentry Flight", AIAA 2011-14 | `~/Desktop/purinton-et-al-2012-….pdf` | Read, figures included. A methods paper; the values were removed from its plots (Sensitive But Unclassified), so no data. Says the booster trims near broadside and that small shape or mass changes alter the reentry markedly. Points to the Shuttle SRB reentry database (now item 1) |
| 2026-10-01 | Ruchała, P. et al., "Wind Tunnel Tests of Influence of Boosters and Fins on Aerodynamic Characteristics of the Experimental Rocket Platform", Transactions of the Institute of Aviation (Warsaw) | `~/Downloads/` | Read. Low speed (60 m/s), angles of attack to 10° only, one sounding rocket with strap-ons. No use for spent stages; could serve as a small-angle, low-speed check of the fin-and-body normal-force build-up if ever wanted |
| 2026-10-01 | Romaniw, Y. A., PhD dissertation, Georgia Tech 2013 | Drive | In use: nozzle share of a solid stage's empty mass (ratio only) |
| 2026-09-30 | Jernell TM X-1658; Klett SC-RR-64-2141; Tobak & Peterson TR R-203; Jorgensen TN D-6996; Norling 1962; Garber 1959; Regan 1984; Regan & Anandakrishnan 1993 | local copies (see `HANDOFF_PHASE3.md`) | In use or read; rows in `data/REFERENCES.md` |
