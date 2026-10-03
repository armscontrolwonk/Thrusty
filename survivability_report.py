"""Reentry Survivability report — the down-leg Schilling/Townsend panel.

Assembles a mode-keyed report (SURVIVABILITY_REPORT_DESIGN.md) from a
trajectory result: inputs echoed → budget table → per-criterion margins →
a JUDGEMENT WITH CONSEQUENCES (accuracy band / time-to-failure / maneuver
envelope) → method + flight-anchor references.  TWO judgement models, keyed
automatically from the reentry plan already baked into the result:

  ballistic RV : the δ/R_n accuracy ladder (accuracy fails before survival;
                 PANT / Lin 1982 / Reentry-F)
  glide / HGV  : the stopwatch (survival-time vs glide-time, NRC-2008
                 duration ladder; thermal-range cap)

Everything ELSE that varies between vehicles — the windward-flank block, the
terminal-dive transient, the maneuver-load anchors — is gated on its own
trigger (windward data present; a commanded dive; a commanded lift cap), not
on a vehicle "Form".  A third "maneuvering" Form used to bundle those three
blocks behind a terminal-dive flag, which mislabelled every banking glider
that did not dive and every diving vehicle that did not bank.

Everything here is PRESENTATION over numbers heating.py already computed
(result['heating_fom']) plus the stashed reentry arc (result['heating_arc']).
Screening tier throughout: Sutton-Graves cold-wall stagnation flux +
radiative-equilibrium wall temperature; consequence bands are qualitative and
flight-anchored (the user-benchmarkable part, design doc §10).
"""

from __future__ import annotations
import re
import numpy as np

import heating
import tps_ladder
import thresholds
from booster_models import glide_family

# ── Unified survival ladder ────────────────────────────────────────────────
# One 4-tier verdict for EVERY material (ablator, hot structure, metal, tile).
# The underlying test differs by material; the output your eye reads is always
# one of these four.  Colors carry the intended semantics: green = demonstrated
# experience; blue = permitted extrapolation (permission, NOT caution); yellow
# = caution / beyond design; red = reserved for a COMPUTED failure.
SURVIVAL_TIERS = {
    'experience': ("WITHIN EXPERIENCE",      "#2e8b57"),  # green
    'design':     ("WITHIN DESIGN ENVELOPE", "#2f6fb0"),  # blue (permission)
    'beyond':     ("BEYOND DESIGN ENVELOPE", "#c78a0a"),  # yellow (caution)
    'fail':       ("CANNOT SURVIVE",         "#c0392b"),  # red
}
_TIER_KEYS = ('experience', 'design', 'beyond', 'fail')
# Per-timestep coverage-band class → tier (for the plot shading).  0 below the
# glass ceiling and 1 above-but-within the demonstrated envelope are both
# demonstrated → experience; 2 (dwell past the demonstrated floor, still
# passive) is design-vouched extrapolation → design; 3 (passive→active
# transition) is beyond-design caution.
_BAND_CLASS_TIER = {'green': 'experience', 'amber': 'experience',
                    'red': 'design', 'redhot': 'beyond'}


def survival_tier(status, coverage=None):
    """Collapse the internal status (+ UHTC coverage) into one survival tier.

    RED ('cannot survive') is reserved for a COMPUTED failure — burn-through,
    melt, a t_fail crossing.  BLUE ('within design') is only reachable for a
    material with a demonstrated envelope to extrapolate past (the payoff of a
    curated anchor dataset); a material without one shows green/yellow/red only.

    'degraded' maps to EXPERIENCE, not beyond: it means the vehicle SURVIVES
    with a consequence (recession-induced accuracy loss, glider aeroshape
    change) that is itself flight-demonstrated (Reentry-F flew ≈0.7 R_n;
    PANT documented the dispersion growth).  The survival ladder answers
    "does it survive, and on what evidence" — the consequence is annotated on
    the headline, not allowed to drag the survival verdict to yellow.  (A
    Mk21-class RV on an easier-than-design trajectory that recedes 0.4 R_n is
    within experience; calling it 'beyond design envelope' overclaims.)
    """
    if status == 'fail':
        return 'fail'
    if coverage is not None and coverage.get('exits'):
        ex = coverage['exits']
        if 'too hot' in ex:        # passive→active oxidation: beyond design, less likely
            return 'beyond'
        if 'too long' in ex:       # past demonstrated dwell, still passive: design vouches
            return 'design'
    if status in ('analysis', 'beyond'):
        # 'analysis' = screen can't assess (e.g. T_eq past 4,000 K);
        # 'beyond'   = ablator load past its demonstrated flight record.
        return 'beyond'
    return 'experience'

# δ/R_n consequence ladder (design doc §3; crosscheck §10.2).  These are NO
# LONGER verdict thresholds: the ablator verdict compares flown load against a
# flight record (§13.6), not a computed δ against these steps.  They are kept as
# the CITED δ ladder referenced in the report's accuracy-warning text — the
# provenance behind "accuracy effects are documented from small shape changes
# onward":
#   0.1  — Lin 1982 (TRW-SCATHE): 0.1 R_N at 67 kft already "mildly indented";
#          PANT: asymmetric recession → dispersion well below blunting levels.
#   0.5–1 — Reentry-F flew its full mission at ≈0.7 R_n radial blunting.
#   glider tip — Murbach 1993/AEOLUS (SWERVE C-C nose) + AHW's move to
#          non-ablating tips: any meaningful recession corrupts the aeroshape.
SHAPE_CHANGE_ONSET = 0.10
SEVERE_BLUNTING    = 0.50
GLIDER_ABL_TIP_FLAG = 0.05

# ---------------------------------------------------------------------------
# UHTC anchor dataset (SURVIVABILITY_REPORT_DESIGN.md §11.2) — one record per
# flight / arc-jet / plasma-torch / furnace datum.  "A new flight strengthens
# the dataset" is a DATA EDIT here, not a code change.  Sources are exact
# (never paraphrased); BENCHMARKING.md §UHTC is the citation of record with the
# full per-datum discussion.  Fields None where the source does not give them.
# ---------------------------------------------------------------------------
UHTC_ANCHORS = [
    dict(id="Monteverde-2013-ZS", material_class="zrb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=None, flux_kind=None, stag_pressure_Pa=None,
         peak_T_K=1973, T_source="measured", dwell_s=300, recession_um=0,
         mass_change_pct=None, outcome="survived", failure_mode=None,
         source="Monteverde & Savino 2013, Corros. Sci. 75 (300 s at 1973 K, zero recession)"),
    dict(id="Monteverde-2012-ZS-sharp", material_class="zrb2_sic", kind="arcjet",
         tip_radius_m=0.002, flux_MW_m2=7.0, flux_kind="cold_wall", stag_pressure_Pa=None,
         peak_T_K=2723, T_source="cfd", dwell_s=575, recession_um=None,
         mass_change_pct=None, outcome="survived", failure_mode=None,
         source="Monteverde & Savino 2012 (sharp ZrB2-SiC tip, passive to ~2450 °C CFD at ~7 MW/m², ~575 s, measurable blunting)"),
    dict(id="Scatteia-2010-blunt", material_class="zrb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=26.0, flux_kind="cold_wall", stag_pressure_Pa=None,
         peak_T_K=None, T_source=None, dwell_s=None, recession_um=None,
         mass_change_pct=None, outcome="survived", failure_mode=None,
         source="Scatteia et al. 2010, DOI 10.2514/1.42834 (blunt; passive-band recession ~3.6 µm/s at 26 MW/m²)"),
    dict(id="Zhang-2008-passive", material_class="zrb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=1.7, flux_kind="cold_wall", stag_pressure_Pa=None,
         peak_T_K=None, T_source=None, dwell_s=None, recession_um=None,
         mass_change_pct=0.0, outcome="survived", failure_mode=None,
         source="Zhang et al. 2008, Compos. Sci. Technol. 68:1718 (passive at 1.7 MW/m², ~0% mass loss)"),
    dict(id="Zhang-2008-active", material_class="zrb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=5.4, flux_kind="cold_wall", stag_pressure_Pa=None,
         peak_T_K=None, T_source=None, dwell_s=None, recession_um=3000,
         mass_change_pct=-15.75, outcome="failed", failure_mode="active oxidation (~5 µm/s recession)",
         source="Zhang et al. 2008, Compos. Sci. Technol. 68:1718 (active at 5.4 MW/m²; 15.75% mass loss, ~3 mm)"),
    dict(id="Marschall-2012-PA", material_class="zrb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=2.02, flux_kind="cold_wall", stag_pressure_Pa=10000,
         peak_T_K=2215, T_source="measured", dwell_s=None, recession_um=None,
         mass_change_pct=None, outcome="degraded", failure_mode="passive→active transition (+400 K temperature jump)",
         source="Marschall et al. 2012, JTHT 26(4), DOI 10.2514/1.T3798 (flat face, ~2 MW/m² / 10 kPa)"),
    dict(id="SHARP-B1", material_class="zrb2_sic", kind="flight",
         tip_radius_m=None, flux_MW_m2=None, flux_kind=None, stag_pressure_Pa=None,
         peak_T_K=None, T_source=None, dwell_s=None, recession_um=None,
         mass_change_pct=None, outcome="degraded", failure_mode="flight corroboration of the PA/runaway threshold",
         source="SHARP-B1 (Kolodziej et al.)"),
    dict(id="Gasch-Johnson-2010-HS", material_class="hfb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=2.5, flux_kind="cold_wall", stag_pressure_Pa=None,
         peak_T_K=1963, T_source="measured", dwell_s=600, recession_um=None,
         mass_change_pct=None, outcome="survived", failure_mode=None,
         source="Gasch & Johnson 2010 (HfB2-SiC, ~1690 °C at ~2.5 MW/m², 600 s)"),
    dict(id="Sevastyanov-2014-HfB2-45SiC", material_class="hfb2_sic", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=None, flux_kind=None, stag_pressure_Pa=None,
         peak_T_K=2973, T_source="measured", dwell_s=1080, recession_um=None,
         mass_change_pct=-1.5, outcome="survived", failure_mode=None,
         source="Sevastyanov et al. 2014, DOI 10.1134/S0036023614110217 (2500–2700 °C, 15–18 min, 1.5% mass loss, no cracking; high-SiC ~20%-porous variant, 10–30 kPa)"),
    dict(id="Savino-2008-1atm", material_class="hfb2_hfc_mosi2", kind="arcjet",
         tip_radius_m=None, flux_MW_m2=None, flux_kind=None, stag_pressure_Pa=118000,
         peak_T_K=2273, T_source="measured", dwell_s=40, recession_um=None,
         mass_change_pct=None, outcome="survived", failure_mode=None,
         source="Savino et al. 2008, DOI 10.1016/j.jeurceramsoc.2007.11.021 (~1 atm, >2000 °C, ~30–40 s)"),
    dict(id="DePrisco-2026-lowp", material_class="complex_boride", kind="plasma_torch",
         tip_radius_m=None, flux_MW_m2=None, flux_kind=None, stag_pressure_Pa=300,
         peak_T_K=1800, T_source="measured", dwell_s=None, recession_um=None,
         mass_change_pct=None, outcome="survived", failure_mode=None,
         source="De Prisco et al. 2026, JECS 46:118184 (ZrB2-TiB2-SiC hemisphere, 3×10⁻³ atm)"),
    dict(id="DePrisco-2026-highp", material_class="complex_boride", kind="plasma_torch",
         tip_radius_m=None, flux_MW_m2=None, flux_kind=None, stag_pressure_Pa=2300,
         peak_T_K=2700, T_source="measured", dwell_s=None, recession_um=None,
         mass_change_pct=None, outcome="failed", failure_mode="oxide-scale detachment",
         source="De Prisco et al. 2026, JECS 46:118184 (same specimens at 2.3×10⁻² atm — pressure-sensitivity evidence)"),
]

# Envelope constants consumed by the coverage verdict (§11.3/§11.4).  Values
# read from the anchors above; the sharp/blunt PA split follows §11.4: the PA
# edge is a flux/pressure surface, screened here by the two bounding anchors.
_UHTC_SHARP_RN_M = 0.05           # below this, use the sharp-conducting-tip anchor
_UHTC_PA_SHARP_K = 2723.0         # Monteverde-2012-ZS-sharp (passive to 2450 °C @ 7 MW/m²)
_UHTC_PA_BLUNT_K = 2215.0         # Marschall-2012-PA (flat face, ~2 MW/m² / 10 kPa)


def _uhtc_coverage(t, q, eps, nose_radius_m, mat):
    """Envelope-coverage classification for a UHTC hot-structure nose (§11.3).

    Returns dict(bands=[(t0,t1,'green'|'amber'|'red'),...] (absolute times),
    dwell_s, covered_s, coverage (fraction of above-ceiling dwell inside the
    demonstrated envelope; 1.0 when nothing exceeds the ceiling), exits
    (subset of {'too hot','too long'}), pa_K, pa_anchor, floor_s, lines
    (report text block)).
    """
    t = np.asarray(t, float); q = np.asarray(q, float)
    eps = max(float(eps or 0.85), 1e-3)
    T_eq = (q / (heating.SIGMA * eps)) ** 0.25
    ceiling = float(mat["continuous_K"])                    # 1923 K (1650 °C)
    floor_s = float(mat.get("oxidation_dwell_s") or 300.0)  # demonstrated floor
    sharp = float(nose_radius_m or 0.0) < _UHTC_SHARP_RN_M
    pa_K = _UHTC_PA_SHARP_K if sharp else _UHTC_PA_BLUNT_K
    pa_anchor = ("Monteverde-2012-ZS-sharp (sharp conducting tip: passive to "
                 "~2450 °C at ~7 MW/m²)" if sharp else
                 "Marschall-2012-PA (flat face: PA jump at ~2215 K / "
                 "~2 MW/m² / 10 kPa)")
    dt = np.diff(t, prepend=t[0])
    above = T_eq > ceiling
    cum = np.cumsum(np.where(above, dt, 0.0))
    # per-sample class
    cls = np.full(t.shape, 0, int)                          # 0 green
    cls[above] = 1                                          # amber candidate
    cls[(above) & (cum > floor_s)] = 2                      # red: too long
    cls[T_eq > pa_K] = 3                                    # red: too hot (wins)
    dwell = float(cum[-1]) if cum.size else 0.0
    covered = float(np.sum(dt[cls == 1])) if t.size else 0.0
    coverage = 1.0 if dwell <= 0 else covered / dwell
    exits = set()
    if np.any(cls == 3):
        exits.add("too hot")
    if np.any(cls == 2):
        exits.add("too long")
    # contiguous bands for the plot
    bands = []
    if t.size:
        # 2 = dwell past the demonstrated floor (still passive) → design tier;
        # 3 = passive→active transition → beyond tier (see _BAND_CLASS_TIER).
        colour = {0: 'green', 1: 'amber', 2: 'red', 3: 'redhot'}
        i0 = 0
        for i in range(1, len(cls) + 1):
            if i == len(cls) or colour[cls[i]] != colour[cls[i0]]:
                bands.append((float(t[i0]), float(t[min(i, len(cls) - 1)]),
                              colour[cls[i0]]))
                i0 = i
    # report text
    lines = []
    if dwell <= 0:
        lines.append(f"  Envelope coverage: GREEN — nose never exceeds the "
                     f"{ceiling - 273.15:.0f} °C glass ceiling; "
                     f"silica-protected, no dwell clock runs.")
    else:
        lines.append(f"  Nose above {ceiling - 273.15:.0f} °C for "
                     f"{dwell:,.0f} s: {covered:,.0f} s within the "
                     f"demonstrated ZrB₂-SiC envelope "
                     f"(floor {floor_s:.0f} s — Monteverde-2013-ZS, "
                     f"1973 K · 300 s; sharp-tip extension 575 s).")
        if "too long" in exits:
            lines.append(f"  TOO LONG (blue 'within design' band): dwell "
                         f"outruns the demonstrated floor — the test record "
                         f"simply ENDS here.  The data is a floor, not a "
                         f"fence (nearly every anchor is a survival where "
                         f"the test stopped), so survival past the floor is "
                         f"plausible but undemonstrated — this is "
                         f"extrapolation, not a failure prediction.  "
                         f"Fix: shorten exposure.")
        if "too hot" in exits:
            lines.append(f"  TOO HOT (yellow 'beyond design' band): surface "
                         f"crosses the passive→active oxidation boundary — "
                         f"unlike 'too long', this exit has failure-side "
                         f"physics behind it: protective silica is lost, "
                         f"heating jumps (~+400 K, Marschall) and recession "
                         f"runs ~10× faster per unit flux (Zhang 2008, "
                         f"~5 µm/s active).  Rapid degradation expected, "
                         f"though not an asserted kill at screening tier.  "
                         f"Anchor: {pa_anchor}.  Fix: loft / blunt tip / "
                         f"lower flux.")
        if not exits:
            lines.append("  Within the demonstrated envelope (green band), "
                         "consuming recession margin.")
        lines.append("  * Demonstrated at ground-facility pressure "
                     "(anchors span 3×10⁻³–1 atm, but long-dwell points are "
                     "low-pressure; the SiC active/passive transition is "
                     "pressure-sensitive — §11.6).")
    return dict(bands=bands, dwell_s=dwell, covered_s=covered,
                coverage=coverage, exits=exits, pa_K=pa_K,
                pa_anchor=pa_anchor, floor_s=floor_s, lines=lines)


# ---------------------------------------------------------------------------
# Maneuver-load anchor dataset — one record per demonstrated (or
# published-representative) MaRV maneuver load.  Same philosophy as
# UHTC_ANCHORS: a new flight datum is a DATA EDIT, not a code change; sources
# are exact and BENCHMARKING.md §Maneuver anchors is the citation of record.
# These are
# structural/guidance survived-the-maneuver demonstrations, NOT thermal
# limits — the context block below is a demonstrated-envelope comparison,
# never a pass/fail verdict.
# ---------------------------------------------------------------------------
MANEUVER_ANCHORS = [
    dict(id="Regan-1984-worked-4g", vehicle="Regan 1984 worked case", g=4.0,
         kind="textbook",
         note="fixed L/D=1.5, β=10⁴ kg/m² MaRV hits the 4-g transverse limit "
              "at ≈45 km (gentle accuracy-maneuver class)",
         source="Regan 1984, Re-Entry Vehicle Dynamics (AIAA), Tables 6.7/6.8"),
    dict(id="Pershing-II-pullout", vehicle="Pershing II", g=25.0,
         kind="operational_flight",
         note="~25-g pullout below ~50 kft after ~Mach-8 reentry (RADAG "
              "map-match segment); velocity-control pullup/pulldown, fielded "
              "Dec 1983",
         source="Yengst 2010, Lightning Bolts; maneuver corroborated by "
                "Lund 1984 (Martin Marietta/AIAA)"),
    dict(id="BGRV-qual-25g", vehicle="BGRV", g=25.0, kind="qualification",
         note="components qualified to 25 g (Atlas-boosted, >Mach-15 "
              "separation onto low-altitude glide)",
         source="Yengst 2010, Lightning Bolts"),
    dict(id="AMaRV-flight-100g", vehicle="AMaRV", g=100.0,
         kind="flight_measured",
         note="Bell XI accelerometers measured >100-g reentry-maneuver "
              "levels; guidance held accuracy through ~100-g maneuvers "
              "(3 flights, 1979–81)",
         source="Yengst 2010, Lightning Bolts"),
    dict(id="Regan-1993-evader-cap", vehicle="Regan 1993 evader", g=100.0,
         kind="textbook",
         note="representative evader max side acceleration 100 g (140 kg, "
              "⌀ 0.4 m, (L/D)max 2.5, β ≈ 1.1×10⁴ kg/m²)",
         source="Regan & Anandakrishnan 1993, Dynamics of Atmospheric "
                "Re-Entry (AIAA), Table D.1"),
    dict(id="Wang-2019-PII-overload", vehicle="Pershing II-modeled HGRV",
         g=25.0, kind="textbook",
         note="modern guidance-simulation overload constraint ±25 g for a "
              "Pershing II-modeled vehicle (Table 1); glide/bleed phase at "
              "~16 km matches Yengst's sub-50-kft band — independent "
              "corroboration of the 25-g class, not flight data",
         source="Wang, Tang & Zhang 2019, IEEE Access 7:47437, "
                "DOI 10.1109/ACCESS.2019.2909589"),
]

# Envelope constants read from the anchors above.
_MARV_G_OPERATIONAL = 25.0    # Pershing-II-pullout (fielded system)
_MARV_G_DEMONSTRATED = 100.0  # AMaRV-flight-100g (flight-measured ceiling)


def _maneuver_context(g_cmd):
    """Demonstrated maneuver-load envelope context (text block).

    Compares the plan's commanded lift cap (glider_pullup_g_max, in g) to the
    flight-demonstrated ladder.  Context only — the anchors are structural/
    guidance demonstrations, not thermal limits, so this never changes the
    survivability status.
    """
    g_cmd = float(g_cmd or 0.0)
    if g_cmd <= 0.0:
        return []
    lines = ["─── Maneuver-load anchors (demonstrated envelope) ──────────",
             f"  Commanded lift cap {g_cmd:g} g vs the open flight record: "
             f"4 g (Regan textbook gentle) · 25 g (Pershing II operational "
             f"pullout; BGRV qual) · ~100 g (AMaRV, flight-measured)."]
    if g_cmd <= _MARV_G_OPERATIONAL:
        lines.append("  Within the operational-MaRV class (Pershing II "
                     "~25-g pullout, fielded Dec 1983).")
    elif g_cmd <= _MARV_G_DEMONSTRATED:
        lines.append("  Above the operational Pershing II class but inside "
                     "the AMaRV flight-demonstrated ~100-g ceiling "
                     "(3 flights, 1979–81).")
    else:
        lines.append(f"  EXCEEDS every flight-demonstrated maneuver load in "
                     f"the open record (~{_MARV_G_DEMONSTRATED:.0f} g, "
                     f"AMaRV) — structural/guidance extrapolation beyond the "
                     f"anchor dataset.")
    lines.append("  * Load anchors are survived-the-maneuver structural/"
                 "guidance demonstrations, not thermal limits; windward/AoA "
                 "heating during the pull-up is a later-tier probe "
                 "(engineering-code uncertainty ~15–40% at AoA, "
                 "Thompson 1989).")
    return lines


def classify(result) -> str:
    """'ballistic' | 'glide' — the ONE structural fork in the report.

    It keys the two genuinely different judgement models: the ballistic
    load-vs-record / accuracy ladder, versus the glider stopwatch (survival
    time vs glide time).  Everything else that used to hang off a third
    "maneuvering" Form now hangs off its own trigger — see descriptors().
    """
    prof = (result.get('heating_arc') or {}).get('profile') or {}
    return 'glide' if prof.get('glider') else 'ballistic'


def descriptors(result) -> list:
    """Arc descriptors, each derived from its OWN trigger.

    The retired Form C ("maneuvering") was keyed on a commanded terminal dive,
    which is not what maneuvering means: SWERVE pulled -10° AoA at 10 g and
    read as a plain glider, while a vehicle with a dive altitude and an empty
    bank schedule was labelled maneuvering.  Each fact now speaks for itself —
    banking comes from a non-empty bank schedule, diving from the two dive
    knobs — so the headline never asserts a behaviour the plan does not carry.
    """
    prof = (result.get('heating_arc') or {}).get('profile') or {}
    if not prof.get('glider'):
        return ["ballistic RV"]
    out = ["glide"]
    if prof.get('banking'):
        out.append("banking")
    if float(prof.get('terminal_alt_km') or 0.0) > 0.0:
        out.append("terminal dive")
    elif float(prof.get('dive_target_radius_km') or 0.0) > 0.0:
        out.append("dive-at-target")
    return out


def _dives(prof) -> bool:
    """True when the plan commands a terminal dive (either knob)."""
    return bool(float(prof.get('terminal_alt_km') or 0.0) > 0.0
                or float(prof.get('dive_target_radius_km') or 0.0) > 0.0)


def _fwhm_s(t, q):
    """Width (s) of the flux pulse above half its peak."""
    q = np.asarray(q, float); t = np.asarray(t, float)
    if q.size < 2 or np.max(q) <= 0:
        return 0.0
    m = q >= 0.5 * np.max(q)
    return float(t[m][-1] - t[m][0]) if m.any() else 0.0


def _load_MJ(t, q):
    """Running integrated load Q(t), MJ/m² (trapezoid)."""
    t = np.asarray(t, float); q = np.asarray(q, float)
    if t.size < 2:
        return np.zeros_like(t)
    dQ = 0.5 * (q[1:] + q[:-1]) * np.diff(t)
    return np.concatenate([[0.0], np.cumsum(dQ)]) / 1e6


# Load fraction above which the accuracy consequence is worth a LEAD sentence
# (below it, recession is a full-analysis footnote only).  Display choice, not
# physics — the accuracy anchors themselves are the citations in the warning.
_ABLATOR_LEAD_FRACTION = 0.50


def _ablator_regime(rc, nose_label="nose"):
    """Classify an ablator location from its load-vs-record criteria dict.

    Returns dict(status, load_sentence, accuracy_sentence, context, fix,
    lead_accuracy) or None if `rc` is absent:
      status          : 'survive' | 'beyond' | 'fail'   (feeds survival_tier)
      load_sentence   : the always-shown lead sentence — the flown load placed
                        against the flight record
      accuracy_sentence : the recession/accuracy consequence (or None)
      lead_accuracy   : whether accuracy_sentence belongs in the LEAD (past
                        ~50% of the record) vs. full-analysis only
      context         : extra full-analysis lines (δ band, record provenance)
      fix             : "what would change the verdict" phrase, or None
    The accuracy consequence (recession-driven dispersion) is flight-
    demonstrated (Lin 1982; PANT; Reentry-F flew ≈0.7 R_n), so it never drives
    the SURVIVAL tier.  Yellow is reserved for a load past the flight record;
    red for the burn-through BOUND only.
    """
    if rc is None:
        return None
    Q = rc.get('load_MJ_m2', 0.0)
    frac = rc.get('load_fraction')
    src = rc.get('demonstrated_load_source', '')
    lbl = f"The {nose_label}"
    band = None
    if rc.get('delta_optimistic_cm') is not None:
        band = (f"δ across the cited H_eff range ({rc.get('H_eff_bound_MJ_kg')}–"
                f"{rc.get('H_eff_nominal_MJ_kg')} MJ/kg): "
                f"{rc['delta_optimistic_cm']:.1f}–{rc['delta_nominal_cm']:.1f} cm "
                f"— a band, not a prediction.")
    acc = ("Recession in this regime is measured, not hypothetical — accuracy "
           "effects are documented from small shape changes onward (Lin 1982; "
           "PANT ADA019186; Reentry-F flew ≈0.7 R_n, NASA CR-154044).")
    prov = f"Demonstrated record: {src}." if src else ""

    if rc.get('burnthrough_bound'):
        return dict(status='fail', lead_accuracy=False,
            load_sentence=(f"{lbl} heat load exceeds the shield's capacity even "
                           f"at the most optimistic cited heat of ablation — a "
                           f"bound, not an estimate, and it is crossed."),
            accuracy_sentence=None, context=[band] if band else [],
            fix="more capable TPS, a blunter nose, or a less demanding trajectory")

    if frac is None:
        return dict(status='survive', lead_accuracy=False,
            load_sentence=(f"{lbl} carries an ablating heat load of "
                           f"{Q:,.0f} MJ/m² and does not burn through. This "
                           f"material family has no cited flight-load anchor to "
                           f"compare against, so recession is a refinement "
                           f"question here, not a survival one."),
            accuracy_sentence=None, context=[acc] + ([band] if band else []),
            fix=None)

    if frac > 1.0:
        return dict(status='beyond', lead_accuracy=False,
            load_sentence=(f"{lbl} carries {Q:,.0f} MJ/m² — about {frac:.1f}× "
                           f"the largest load in the open flight record for "
                           f"this material family. No comparable flight "
                           f"experience supports survival here; the burn-through "
                           f"bound is not crossed, so this is undemonstrated, "
                           f"not impossible."),
            accuracy_sentence=None, context=[prov, acc] + ([band] if band else []),
            fix="a lower-load (shorter or steeper) trajectory, or more capable TPS")

    if frac >= _ABLATOR_LEAD_FRACTION:
        return dict(status='survive', lead_accuracy=True,
            load_sentence=(f"{lbl} carries {Q:,.0f} MJ/m² — the upper part of "
                           f"the flight record for this material family "
                           f"({frac:.0%} of it). Survival at this load is "
                           f"flight-demonstrated."),
            accuracy_sentence=("But vehicles in this regime measurably recede, "
                               "so accuracy — not survival — is the open "
                               "question."),
            context=[prov, acc] + ([band] if band else []), fix=None)

    return dict(status='survive', lead_accuracy=False,
        load_sentence=(f"{lbl} carries {Q:,.0f} MJ/m² — about {frac:.0%} of the "
                       f"flight record for this material family, a load "
                       f"vehicles of this class carry routinely."),
        accuracy_sentence=None, context=[prov, acc] + ([band] if band else []),
        fix=None)


def _loc_line(name, L):
    """One per-location margin line for the budget table.  Ablators show flux +
    load (an ablating surface caps its own temperature, so a T_eq for it is a
    flux restated in kelvin — not a temperature anything experiences)."""
    if not L or not L.get('material'):
        return f"  {name:<5s} (no TPS material set)"
    mat = str(L.get('material'))
    crit = L.get('criteria') or {}
    cmp_ = L.get('compromise')
    T = float(L.get('T_eq_peak_K', 0.0) or 0.0)
    if L.get('is_ablator') and 'recession' in crit:
        rc = crit['recession']
        q = float(L.get('q_peak_MW_m2', 0.0) or 0.0)
        frac = rc.get('load_fraction')
        rec = (f"{frac:.0%} of flight-record load" if frac is not None
               else "no cited load record")
        if cmp_:
            rec = cmp_['mode']
        return (f"  {name:<5s} {mat:<18s} q̇ {q:>6,.1f} MW/m²  "
                f"load {rc.get('load_MJ_m2', 0):>5,.0f} MJ/m²  {rec}")
    if T >= heating.NOTHING_SURVIVES_K:
        det = f"T_eq {T:,.0f} K ≥ 4,000 K screen — beyond screening"
    elif cmp_:
        det = f"{cmp_['mode']} at t={cmp_['t_s']:.0f} s"
    else:
        worst = max((v.get('margin', 0.0) for v in crit.values()), default=0.0)
        det = f"worst margin {worst:.2f}"
    return f"  {name:<5s} {mat:<18s} T_eq {T:>7,.0f} K   {det}"


# ── Survival map: the one-glance station × question matrix ──────────────────
# Rows are stations in the order the heat visits them (outside-in, front-to-
# back: nose → body skin → windward flank → interior); columns are the three
# ladder questions.  Each populated cell shows the ONE number its tier was
# decided on — the matrix says WHERE to look, the full analysis below says
# what happened.  "—" covers both physically-N/A and not-computed-at-
# screening-tier; the full analysis carries that distinction.  The Regime
# line is prose (validity guards and the transition state answer none of the
# three questions — forcing them into cells would be false symmetry).
# Cells are TAB-separated: the GUI aligns columns with pixel tab stops (a
# character grid breaks when cells render bold — bold fixed fonts don't share
# regular metrics on every platform, e.g. macOS).
_MAP_COLS = ("Surface holds?", "Endures duration?", "Within flown record?")


def _record_anchor(src):
    """Short anchor name from a demonstrated-load citation ('Reentry-F
    graphite ... flew' → 'Reentry-F graphite')."""
    words = str(src or "").split()
    return " ".join(words[:2]) if words else "flight record"


def _map_skin_cells(L, coverage=None):
    """(surface, duration, record) cells for one skin location; each cell is
    (text, tier_key) or None (rendered as '—')."""
    if not L or not L.get('material'):
        return (None, None, None)
    crit = L.get('criteria') or {}
    T = float(L.get('T_eq_peak_K', 0.0) or 0.0)
    if coverage is not None:
        # UHTC hot-structure nose: the coverage verdict owns all three cells.
        ex = coverage.get('exits') or set()
        surf = (f"{T:,.0f} K of {coverage['pa_K']:,.0f} K",
                'beyond' if 'too hot' in ex else 'experience')
        if coverage['dwell_s'] > 0:
            dur = (f"{coverage['dwell_s']:,.0f} s of {coverage['floor_s']:.0f} s",
                   'design' if 'too long' in ex else 'experience')
        else:
            dur = ("0 s above ceiling", 'experience')
        rec_tier = ('beyond' if 'too hot' in ex else
                    'design' if 'too long' in ex else 'experience')
        rec = (f"{coverage['coverage']:.0%} of dwell in envelope", rec_tier)
        return (surf, dur, rec)
    if L.get('is_ablator') and 'recession' in crit:
        # Ablator: surface = the burn-through bound; record = load vs the
        # family flight record.  Duration is not a separate ablator question.
        rc = crit['recession']
        surf = (("burn-through bound", 'fail') if rc.get('burnthrough_bound')
                else ("no burn-through", 'experience'))
        frac = rc.get('load_fraction')
        if frac is None:
            rec = ("no cited flight record", 'experience')
        else:
            num = f"{frac:.1f}×" if frac >= 2.0 else f"{frac:.0%}"
            rec = (f"{num} of {_record_anchor(rc.get('demonstrated_load_source'))}",
                   'beyond' if frac > 1.0 else 'experience')
        return (surf, None, rec)
    # Reradiative skin: surface = peak T_eq vs limit; duration = soak dwell
    # (or the heat-sink melt budget when that criterion is the one crossed).
    if T >= heating.NOTHING_SURVIVES_K:
        return (("past 4,000 K screen", 'beyond'), None, None)
    surf = dur = None
    ps = crit.get('peak_surface')
    if ps:
        surf = (f"{T:,.0f} K of {ps['limit_K']:,.0f} K",
                'fail' if ps['margin'] > 1.0 else 'experience')
    sk = crit.get('soak')
    if sk:
        _t = ('design' if (sk['margin'] >= 1.0 and sk.get('floor'))
              else 'fail' if sk['margin'] >= 1.0 else 'experience')
        dur = (f"{sk['time_above_s']:,.0f} s of {sk['dwell_s']:,.0f} s", _t)
    hs = crit.get('heat_sink')
    if hs and hs.get('margin', float('inf')) <= 1.0:
        dur = (f"{hs['Q_absorbed_MJ']:,.0f} of {hs['Q_melt_MJ']:,.0f} MJ", 'fail')
    return (surf, dur, None)


# ── The four answers (TODO item 11; user, 2026-10-02) ──────────────────────
# What a reader wants from this tab: is a surface compromised (the nose, a
# wing or leading edge, the windward surface), and is the inside cooked by
# a long, hot soak.  One row each; the headline is the worst row.
_TIER_RANK = {'experience': 0, 'design': 1, 'beyond': 2, 'fail': 3}
_VERDICT_TEXT = {'experience': "holds", 'design': "past tested dwell",
                 'beyond': "beyond its limit", 'fail': "fails"}
ANSWER_COLS = ("Verdict", "Value", "Limit")


def _worst(cells):
    """(text, tier) of the worst cell among (text, tier) pairs or None."""
    cells = [c for c in cells if c]
    return max(cells, key=lambda c: _TIER_RANK.get(c[1], 0)) if cells else None


def _row(place, tier=None, value="", limit="", basis="", reason="",
         verdict=None, short=None):
    """One answer.  tier None = not computed (reason says why) or, with
    verdict given, a neutral statement such as 'none on this object'.
    short is the row's name in the headline (default: the first word)."""
    return dict(place=place, tier=tier,
                short=short or place.split(' ')[0].lower(),
                verdict=(verdict or (_VERDICT_TEXT[tier] if tier
                                     else "not computed")),
                value=value, limit=limit, basis=basis, reason=reason)


def _label(key):
    m = heating.TPS_MATERIALS.get(str(key or ""))
    return re.sub(r'\s*\(.*\)$', '', (m or {}).get('label') or str(key or ""))


def _ablator_row(place, L, worst, mat):
    """An ablative location: its flown heat load against the material's
    flight record (the burn-through bound overrides)."""
    rc = (L.get('criteria') or {}).get('recession') or {}
    if rc.get('burnthrough_bound'):
        return _row(place, 'fail', "burn-through", f"the layer's capacity ({mat})",
                    basis="the burn-through bound at the most optimistic "
                          "cited heat of ablation")
    rec = rc.get('demonstrated_load_MJ_m2')
    Q = float(rc.get('load_MJ_m2', 0.0) or 0.0)
    if not rec:
        return _row(place, reason=f"no flown heat-load record for {mat}")
    return _row(place, 'beyond' if Q > rec else 'experience',
                f"{Q:,.0f} MJ/m² heat load ({Q / rec:.0%} of the record)",
                f"{rec:,.0f} MJ/m² flown, "
                f"{_record_anchor(rc.get('demonstrated_load_source'))} ({mat})",
                basis="ablative: judged on flown heat load against the "
                      "material's flight record")


def _nose_answer(nose, coverage, prof):
    if not (nose or {}).get('material') and not prof.get('nose_material'):
        return _row("Nose", reason="no nose material entered")
    mat = _label(prof.get('nose_material') or nose.get('material'))
    surf, dur, rec = _map_skin_cells(nose, coverage)
    worst = _worst([surf, dur, rec])
    if worst is None:
        return _row("Nose", reason=f"no limit on file for {mat}")
    if coverage is not None:
        return _row("Nose", worst[1], surf[0].split(" of ")[0],
                    f"{coverage['pa_K']:,.0f} K, the edge of passive oxidation; "
                    f"tested to {coverage['floor_s']:.0f} s ({mat})",
                    basis="the UHTC envelope coverage")
    if nose.get('is_ablator'):
        return _ablator_row("Nose", nose, worst, mat)
    ps = (nose.get('criteria') or {}).get('peak_surface')
    if surf and ps:
        return _row("Nose", worst[1], surf[0].split(" of ")[0],
                    f"{ps['limit_K']:,.0f} K peak ({mat})",
                    basis="radiative-equilibrium wall temperature")
    return _row("Nose", worst[1], worst[0], mat)


def _windward_answer(fom, body_loc, prof):
    w = (fom or {}).get('windward')
    wc = ((w or {}).get('criteria') or {}).get('windward_surface')
    if w and wc and w.get('T_eq_windward_K'):
        Tw = w['T_eq_windward_K']
        over = (Tw['lo'] > wc['limit_continuous_K']
                or Tw['hi'] > wc['limit_peak_K'])
        ab = w.get('alpha_band_deg') or (5, 20)
        return _row("Windward surface", 'beyond' if over else 'experience',
                    f"{Tw['lo']:,.0f}–{Tw['hi']:,.0f} K at α {ab[0]:.0f}–{ab[1]:.0f}°",
                    f"{wc['limit_continuous_K']:,.0f} K continuous, "
                    f"{wc['limit_peak_K']:,.0f} K peak "
                    f"({_label(w.get('body_material'))})",
                    basis=w.get('thompson_band', '') or
                    "windward flank, modified-Newtonian amplification")
    if body_loc is None or not body_loc.get('material'):
        if not prof.get('body_material'):
            return _row("Windward surface", reason="no body material entered")
        return _row("Windward surface",
                    reason="no windward heating computed for this flight")
    mat = _label(body_loc.get('material'))
    surf, dur, rec = _map_skin_cells(body_loc)
    worst = _worst([surf, dur, rec])
    if worst is None:
        return _row("Windward surface", reason=f"no limit on file for {mat}")
    if body_loc.get('is_ablator'):
        r = _ablator_row("Windward surface", body_loc, worst, mat)
        if r['tier']:
            r['basis'] = "body acreage at zero angle of attack; " + r['basis']
        return r
    ps = (body_loc.get('criteria') or {}).get('peak_surface')
    return _row("Windward surface", worst[1],
                surf[0].split(" of ")[0] if surf else worst[0],
                (f"{ps['limit_K']:,.0f} K ({mat})" if ps else mat),
                basis="body acreage at zero angle of attack")


def _edge_answer(fom, prof):
    les = (fom or {}).get('leading_edges') or []
    if not les:
        if prof.get('wing'):
            return _row("Wing / leading edge",
                        reason="the object has a wing, but no leading-edge "
                               "entry (edge radius and material) in its "
                               "heating locations")
        if prof.get('body_form') in ('wedge', 'half_cone'):
            return _row("Wing / leading edge",
                        reason=f"a {prof['body_form'].replace('_', ' ')} has "
                               f"edges, but none is entered in the object's "
                               f"heating locations")
        return _row("Wing / leading edge", verdict="none on this object",
                    reason="no wing, fin or leading edge entered")
    worst = None
    for le in les:
        name = le.get('name') or 'leading edge'
        if le.get('status') != 'evaluated':
            r = _row("Wing / leading edge",
                     reason=f"{name}: " + "; ".join(le.get('missing') or
                                                    [le.get('status', '')]))
        else:
            res = (le.get('results') or {}).get('laminar') or {}
            mat = heating.TPS_MATERIALS.get(str(le.get('material') or ''))
            T = res.get('T_wall_peak_K')
            if mat is None:
                r = _row("Wing / leading edge",
                         reason=f"{name}: material not in the catalog")
            elif mat.get('is_ablator'):
                rec = mat.get('demonstrated_load_MJ_m2')
                Q = res['heat_load_J_m2']
                Q = (max(Q) if isinstance(Q, tuple) else Q) / 1e6
                if not rec:
                    r = _row("Wing / leading edge",
                             reason=f"{name}: no flown heat-load record for "
                                    f"{_label(le['material'])}")
                else:
                    r = _row("Wing / leading edge",
                             'beyond' if Q > rec else 'experience',
                             f"{Q:,.0f} MJ/m² heat load",
                             f"{rec:,.0f} MJ/m² flown ({_label(le['material'])})",
                             basis=le.get('accuracy', ''))
            elif T is not None:
                lo, hi = T if isinstance(T, tuple) else (T, T)
                cont, peak = float(mat['continuous_K']), float(mat['peak_K'])
                tier = ('beyond' if (lo > cont or hi > peak) else 'experience')
                r = _row("Wing / leading edge", tier,
                         (f"{lo:,.0f}–{hi:,.0f} K" if hi > lo else f"{hi:,.0f} K")
                         + f" ({name})",
                         f"{cont:,.0f} K continuous, {peak:,.0f} K peak "
                         f"({_label(le['material'])})",
                         basis=le.get('accuracy', ''))
            else:
                r = _row("Wing / leading edge",
                         reason=f"{name}: no wall temperature computed")
        if worst is None or _TIER_RANK.get(r['tier'], -1) > _TIER_RANK.get(worst['tier'], -1):
            worst = r
    return worst


def _stack(arc, prof):
    """The conduction screen through the body's outer layer and whatever
    the object lists behind it (heating.layered_conduction), on the
    acreage flux; cached on the arc for the inputs it used.  None when the
    outer layer is not entered; else the result dict (evaluated or not)."""
    mat = prof.get('body_material')
    thick = float(prof.get('body_thickness_m', 0.0) or 0.0)
    t = np.asarray(arc.get('t', []), float)
    if not mat or thick <= 0.0 or t.size < 2:
        return None
    layers = [(str(mat), thick)] + [
        (str(e['material']), float(e['thickness_m']))
        for e in (prof.get('interior_layers') or [])]
    key = (tuple(layers), float(prof.get('emissivity', 0.85) or 0.85),
           float(prof.get('nose_radius_m', 0.0) or 0.0),
           float(prof.get('diameter_m', 0.0) or 0.0))
    cache = arc.setdefault('_stack_cache', {})
    if key not in cache:
        q, _, _ = heating.acreage_flux(
            t, arc['rho'], arc['V'], arc['alt'],
            nose_radius_m=key[2], body_radius_m=key[3] / 2.0)
        cache[key] = heating.layered_conduction(t, q, layers,
                                                emissivity=key[1])
    return cache[key]


def _nose_stack(arc, prof):
    """The conduction screen through the nose piece (ro_section.nose_piece)
    and the layers behind it, on the stagnation-point flux the nose row
    uses.  A shell is its thickness; a solid tip is a slab of its length.
    Cached like _stack.  None when no nose piece is entered."""
    nz = prof.get('nose_piece')
    t = np.asarray(arc.get('t', []), float)
    if not nz or t.size < 2 or 'q_dot' not in arc:
        return None
    layers = [(str(nz['material']), float(nz['thickness_m']))] + [
        (str(e['material']), float(e['thickness_m']))
        for e in (prof.get('interior_layers') or [])]
    key = ('nose', tuple(layers),
           float(prof.get('emissivity', 0.85) or 0.85))
    cache = arc.setdefault('_stack_cache', {})
    if key not in cache:
        cache[key] = heating.layered_conduction(
            t, np.asarray(arc['q_dot'], float), layers, emissivity=key[2])
    return cache[key]


def _nose_phrase(nz):
    return (f"{nz['thickness_m'] * 100:.1f} cm of {_label(nz['material'])}"
            + (" (solid tip, as a slab)" if nz['kind'] == 'solid' else ""))


_NOSE_BASIS = ("; the nose: the same through the nose piece and the layers "
               "behind it under the stagnation-point heating, which "
               "overstates it away from the tip")


def _face_limit(mat, prof):
    """(limit °C, text) for the face behind an outer piece of `mat`: its
    own continuous limit for a hot structure or metal, else the structure
    limit entered for the object, else the bondline design limit."""
    m = heating.TPS_MATERIALS.get(str(mat or ""))
    if heating.is_hot_structure(mat):
        lim = float((m or {}).get('continuous_K') or 0.0) - 273.15
        return lim, f"{lim:,.0f} °C ({_label(mat)} continuous limit)"
    if float(prof.get('structure_limit_K', 0.0) or 0.0) > 0.0:
        lim = float(prof['structure_limit_K']) - 273.15
        return lim, f"{lim:,.0f} °C (structure limit entered for this object)"
    lim = float(heating.BONDLINE_LIMIT_C)
    return lim, (f"{lim:,.0f} °C (bondline design limit, Dec & Braun, "
                 f"NTRS 20060004824)")


def _crossing(t, T_K, limit_C):
    over = np.nonzero(np.asarray(T_K) >= limit_C + 273.15)[0]
    return float(np.asarray(t)[over[0]]) if over.size else None


def _back_face_answer(arc, prof):
    """The back of the body's outer layer after the soak, judged against
    what sits there.  Behind a heat shield (an ablator or tile over a
    separate structure) that is the bondline: the structure limit entered
    for the object, else the bondline design limit.  A hot structure or a
    metal skin IS the structure, so its back face is judged against the
    material's own continuous limit.  With layers entered behind it, the
    face is the joint with the first of them.  A nose piece of its own
    (ro_section.nose_piece) is a second column, judged the same way by its
    own material; the row takes the worse.  Neither is the payload: see
    _interior_answer."""
    mat = prof.get('body_material')
    hot = heating.is_hot_structure(mat)
    place = ("Back of the hot structure" if hot
             else "Bondline (heat shield to structure)")
    short = "back face" if hot else "bondline"
    if not mat:
        return _row(place, reason="no body heat-shield material entered",
                    short=short)
    thick = float(prof.get('body_thickness_m', 0.0) or 0.0)
    if thick <= 0.0:
        return _row(place, reason="no body heat-shield thickness entered",
                    short=short)
    limit, lim_txt = _face_limit(mat, prof)
    res = _stack(arc, prof)
    if res is None:
        return _row(place, limit=lim_txt,
                    reason="no reentry arc to evaluate over", short=short)
    if not res.get('evaluated'):
        why = res.get('reason', '')
        if 'conductivity' in why:
            why = (f"no cited conductivity for "
                   f"{_label(res.get('material') or mat)} in the catalog")
        return _row(place, limit=lim_txt, reason=why, short=short)
    face = res['T_faces'][1]
    crossed = _crossing(arc['t'], face, limit) is not None
    value = (f"{float(face.max()) - 273.15:,.0f} °C behind "
             f"{thick * 100:.1f} cm of {_label(mat)}")
    inner = len(prof.get('interior_layers') or []) > 0
    basis = ("one-dimensional conduction through the body layer "
             + ("and the layers entered behind it, in perfect contact, with "
                "an insulated innermost face" if inner
                else "with an insulated inner face")
             + " (Dec & Braun), to impact: an upper bound for that face")
    nz = prof.get('nose_piece')
    nres = _nose_stack(arc, prof)
    reason = ""
    if nz and nres is not None and nres.get('evaluated'):
        n_lim, n_txt = _face_limit(nz['material'], prof)
        nface = nres['T_faces'][1]
        crossed = crossed or (_crossing(arc['t'], nface, n_lim) is not None)
        value += (f"; nose: {float(nface.max()) - 273.15:,.0f} °C behind "
                  f"{_nose_phrase(nz)}")
        if n_txt != lim_txt:
            lim_txt = f"body {lim_txt}; nose {n_txt}"
        basis += _NOSE_BASIS
    elif nz and nres is not None:
        reason = f"the nose path is not computed: {nres.get('reason', '')}"
    return _row(place, 'beyond' if crossed else 'experience', value,
                lim_txt, basis=basis, reason=reason, short=short)


def _interior_answer(arc, prof):
    """The payload, judged against the object's interior limit, at the
    innermost face of the layers entered behind the body's outer layer.
    Not computed when none are entered: the back of the outer layer is not
    the inside (Hayabusa2's sample-container plate rose about 2 °C while
    the shield's back face reached about 84 °C, Yamada & Yoshihara 2023
    Fig. 19)."""
    limit = float(prof.get('interior_limit_C', 80.0) or 80.0)
    lim_src = ("Hayabusa sample container, Yada et al. 2014"
               if abs(limit - 80.0) < 1e-9 else "entered for this object")
    lim_txt = f"{limit:,.0f} °C ({lim_src})"
    layers = prof.get('interior_layers') or []
    if not layers:
        return _row("Interior (payload)", limit=lim_txt,
                    reason="nothing entered between the shell and the payload",
                    short="interior")
    res = _stack(arc, prof)
    if res is None:
        return _row("Interior (payload)", limit=lim_txt,
                    reason="the body layer's material or thickness is not "
                           "entered", short="interior")
    if not res.get('evaluated'):
        return _row("Interior (payload)", limit=lim_txt,
                    reason=res.get('reason', ''), short="interior")
    face = res['T_faces'][-1]
    crossed = _crossing(arc['t'], face, limit) is not None
    last = layers[-1]
    value = (f"{float(face.max()) - 273.15:,.0f} °C at the inner face of "
             f"{float(last['thickness_m']) * 100:.1f} cm of "
             f"{_label(last['material'])}")
    nz = prof.get('nose_piece')
    nres = _nose_stack(arc, prof)
    nose_basis, reason = "", ""
    if nz and nres is not None and nres.get('evaluated'):
        nface = nres['T_faces'][-1]
        crossed = crossed or (_crossing(arc['t'], nface, limit) is not None)
        value += (f"; under the nose ({_nose_phrase(nz)}): "
                  f"{float(nface.max()) - 273.15:,.0f} °C")
        nose_basis = _NOSE_BASIS
    elif nz and nres is not None:
        reason = f"the nose path is not computed: {nres.get('reason', '')}"
    return _row("Interior (payload)",
                'beyond' if crossed else 'experience',
                value,
                lim_txt, reason=reason,
                basis=(f"one-dimensional conduction through the body layer "
                       f"and {len(layers)} layer"
                       f"{'s' if len(layers) > 1 else ''} behind it, in "
                       f"perfect contact, the innermost face insulated and "
                       f"no payload mass, to impact: an upper bound. "
                       f"Accuracy not yet established; the Hayabusa2 flight "
                       f"record is the test case being set up" + nose_basis),
                short="interior")


def answers(result) -> list:
    """The answers: nose, wing or leading edge, windward surface, the back
    of the body's outer layer, and the interior (payload).  Each row is a dict with place, tier (None =
    not computed or not applicable), verdict, value, limit, basis and
    reason.  Presentation over numbers already computed, except the
    back-face row, which runs the existing one-dimensional conduction
    screen against the limit of whatever sits behind the layer."""
    fom = result.get('heating_fom') or {}
    arc = result.get('heating_arc') or {}
    prof = arc.get('profile') or {}
    locs = fom.get('locations') or {'nose': fom}
    nose = locs.get('nose') or fom
    body_loc = locs.get('body')
    t = np.asarray(arc.get('t', []), float)
    q = np.asarray(arc.get('q_dot', []), float)
    _nm = heating.TPS_MATERIALS.get(str(prof.get('nose_material') or ""))
    coverage = None
    if (classify(result) == 'glide' and _nm and not _nm.get('is_ablator')
            and _nm.get('oxidation_dwell_s') and t.size > 1):
        coverage = _uhtc_coverage(t, q, prof.get('emissivity', 0.85),
                                  prof.get('nose_radius_m', 0.0), _nm)
    return [_nose_answer(nose, coverage, prof),
            _edge_answer(fom, prof),
            _windward_answer(fom, body_loc, prof),
            _back_face_answer(arc, prof),
            _interior_answer(arc, prof)]


def answers_block(rows):
    """(lines, spans) for the GUI: the header line, the column titles, one
    tab-separated line per answer, then the reasons and bases.  Spans are
    (line index in the block, start, end, tier) on each verdict cell."""
    lines = ["─── Survival map ───────────────────────────────────────────",
             "\t" + "\t".join(ANSWER_COLS)]
    spans = []
    for r in rows:
        line = "  " + r['place'] + "\t"
        if r['tier']:
            spans.append((len(lines), len(line), len(line) + len(r['verdict']),
                          r['tier']))
        line += r['verdict'] + "\t" + (r['value'] or "—") + "\t" \
            + (r['limit'] or "—")
        lines.append(line)
    notes = [f"  {r['place']}: {r['reason']}." for r in rows if r['reason']]
    notes += [f"  {r['place']}: {r['basis']}." for r in rows
              if r['basis'] and r['tier']]
    if notes:
        lines.append("")
        lines += notes
    return lines, spans


def _survival_map(nose, body_loc, coverage, windward, bondline, warnings):
    """Assemble the matrix.  Returns (lines, spans); spans are
    (line_idx_within_block, char_start, char_end, tier_key) for the GUI to
    colorize — line 0 is the '─── Survival map' header."""
    rows = [("Nose", _map_skin_cells(nose, coverage))]
    if body_loc is not None and body_loc.get('material'):
        rows.append(("Body skin", _map_skin_cells(body_loc)))
    if windward and windward.get('T_eq_windward_K'):
        wc = (windward.get('criteria') or {}).get('windward_surface')
        Tw = windward['T_eq_windward_K']
        if wc:
            over = (Tw['lo'] > wc['limit_continuous_K']
                    or Tw['hi'] > wc['limit_peak_K'])
            rows.append(("Windward flank",
                         ((f"{Tw['hi']:,.0f} K of {wc['limit_continuous_K']:,.0f} K",
                           'beyond' if over else 'experience'), None, None)))
    if bondline and bondline.get('evaluated'):
        rows.append(("Interior",
                     (None,
                      (f"{bondline['T_bond_peak_C']:,.0f} of "
                       f"{bondline['limit_C']:.0f} °C",
                       'beyond' if bondline['crossed'] else 'experience'),
                      None)))
    rows = [(lbl, cells) for lbl, cells in rows if any(cells)]
    if not rows:
        return [], []

    lines = ["─── Survival map ───────────────────────────────────────────"]
    lines.append("\t" + "\t".join(_MAP_COLS))
    spans = []
    for lbl, cells in rows:
        line = "  " + lbl
        for cell in cells:
            line += "\t"
            if cell is None:
                line += "—"
            else:
                spans.append((len(lines), len(line), len(line) + len(cell[0]),
                              cell[1]))
                line += cell[0]
        lines.append(line)
    # Regime line: the located rows' remainder — transition state (where the
    # gate feeds a computed screen) and validity guards.
    bits = []
    tr = (windward if (windward and windward.get('transition_state'))
          else bondline if (bondline and bondline.get('evaluated')
                            and bondline.get('transition_state')) else None)
    if tr:
        st = tr['transition_state']
        _fp = float(tr.get('transition_factor_peak', 1.0) or 1.0)
        bits.append(
            "acreage boundary layer laminar throughout" if st == 'laminar'
            else f"acreage boundary layer {st} at low altitude "
                 + (f"(flank flux ×{_fp:.1f})" if _fp >= 1.05
                    else "(just past onset)"))
    if any('radiative gas heating NOT assessed' in w for w in (warnings or [])):
        bits.append("radiative gas heating not assessed (V > 9 km/s)")
    if bits:
        lines.append("  Regime: " + "; ".join(bits) + ".")
    return lines, spans


def build_report(result) -> dict:
    """Assemble the survivability report.

    Returns {'status', 'headline', 'body', 'form', 'plot'} — plot carries
    (t, q_MW, Q_MJ, t_fail, glide_s, tiers) for the flux/load axes.  status ∈
    'survive' | 'degraded' | 'fail' | 'analysis' | 'none' (tab colouring).
    """
    fom = result.get('heating_fom')
    arc = result.get('heating_arc')
    if not fom or not arc:
        return dict(status='none', headline="No reentry heating computed",
                    body="Fly a trajectory that reenters (and set TPS "
                         "materials on the reentry object).",
                    form=None, plot=None)
    prof = arc.get('profile') or {}
    form = classify(result)
    fam = glide_family(prof.get('guidance')) if prof.get('glider') else None

    t = np.asarray(arc['t'], float)
    q = np.asarray(arc['q_dot'], float)
    t0 = float(t[0]) if t.size else 0.0
    q_MW = q / 1e6
    Q_MJ = _load_MJ(t, q)
    dur = float(fom.get('duration_s') or (t[-1] - t0 if t.size else 0.0))

    # Locations (per-location FOM when present, else the single-location dict).
    locs = fom.get('locations') or {'nose': fom}
    nose = locs.get('nose') or fom
    body_loc = locs.get('body')

    # UHTC hot-structure nose → the envelope-coverage verdict (§11.3) replaces
    # the boolean dwell fail for the nose; its dwell-floor "compromise" is an
    # extrapolation flag, not a failure, so it must not drive t_fail.
    _nose_mat = heating.TPS_MATERIALS.get(str(prof.get('nose_material') or ""))
    uhtc_nose = bool(form == 'glide' and _nose_mat
                     and not _nose_mat.get('is_ablator')
                     and _nose_mat.get('oxidation_dwell_s'))
    coverage = None
    if uhtc_nose:
        coverage = _uhtc_coverage(t, q, prof.get('emissivity', 0.85),
                                  prof.get('nose_radius_m', 0.0), _nose_mat)

    # t_fail: earliest compromise across locations (absolute mission time —
    # heating.py evaluated the arc on t_arr, so compromise t_s is absolute).
    t_fail = None
    _fail_loc = _fail_mode = None
    for name_, L in locs.items():
        if uhtc_nose and name_ == 'nose':
            continue                      # coverage verdict owns the nose
        c = (L or {}).get('compromise')
        if c and (t_fail is None or c['t_s'] < t_fail):
            t_fail = float(c['t_s'])
            _fail_loc, _fail_mode = name_, c.get('mode')

    # ---- header ------------------------------------------------------------
    mode_str = ('ballistic' if form == 'ballistic' else prof.get('guidance', ''))
    fam_str = f"   [{fam} family]" if fam else ""
    hdr = [
        f"Reentry object:  {prof.get('name') or '(unnamed)'}   "
        f"(R_n {prof.get('nose_radius_m', 0)*100:.1f} cm, "
        f"⌀ {prof.get('diameter_m', 0):.2f} m, "
        f"{prof.get('mass_kg', 0):,.0f} kg)",
        f"Reentry mode:    {mode_str}{fam_str}",
        f"Entry (arc start): {arc.get('entry_V_ms', 0)/1000:.2f} km/s at "
        f"γ = {arc.get('entry_gamma_deg', 0):+.1f}°",
        f"TPS:             nose {prof.get('nose_material') or '(none)'} · "
        f"body {prof.get('body_material') or '(none)'}"
        + (f" {prof.get('body_thickness_m', 0)*100:.1f} cm"
           if prof.get('body_thickness_m') else ""),
    ]

    # ---- budget ------------------------------------------------------------
    # An ablator caps its own surface temperature by ablating, so a "Peak T_eq"
    # for an ablating nose is a flux restated in kelvin, not a temperature
    # anything experiences — show the flux + load line instead.
    _nose_abl = bool(nose.get('is_ablator'))
    budget = [
        "─── Heating budget ─────────────────────────────────────────",
        f"  Peak stagnation flux:  {fom.get('q_peak_MW_m2', 0):.1f} MW/m²"
        f"   (pulse width {_fwhm_s(t, q):.0f} s)",
        f"  Integrated load:       {fom.get('integrated_load_MJ_m2', 0):,.0f} MJ/m²",
    ]
    if not _nose_abl:
        budget.append(f"  Peak T_eq:             {fom.get('T_eq_peak_K', 0):,.0f} K")
    budget += [
        f"  Reentry-arc duration:  {dur:,.0f} s",
        "─── Per-location margins ───────────────────────────────────",
        _loc_line("nose", nose),
    ]
    if body_loc is not None:
        budget.append(_loc_line("body", body_loc))

    # ---- judgement (mode-keyed) ---------------------------------------------
    j = ["─── Judgement ──────────────────────────────────────────────"]
    status = 'survive'
    _not_thermal = []

    # Ablator load-vs-record regime (nose) — shared by the lead and judgement.
    rc = (nose.get('criteria') or {}).get('recession')
    _nose_lbl_raw = (_nose_mat.get('label') if _nose_mat else None) \
        or prof.get('nose_material') or 'nose'
    _nose_lbl = re.sub(r'\s*\(.*\)$', '', _nose_lbl_raw)   # drop a trailing "(...)"
    regime = (_ablator_regime(rc, f"{_nose_lbl} nose")
              if nose.get('is_ablator') else None)

    if form == 'ballistic':
        if regime is not None:
            status = regime['status']
            # The load sentence (and, when it leads, the accuracy sentence)
            # is in the lead above; the judgement does not repeat it.
            if regime['accuracy_sentence'] and not regime['lead_accuracy']:
                j.append("  " + regime['accuracy_sentence'])
            for c in regime['context']:
                if c:
                    j.append(f"  {c}")
        elif t_fail is not None:
            status = 'fail'
            j.append(f"  CANNOT SURVIVE at t≈{t_fail:,.0f} s — "
                     f"{_fail_mode or 'thermal limit exceeded'}.")
        elif float(nose.get('T_eq_peak_K', 0)) >= heating.NOTHING_SURVIVES_K:
            status = 'analysis'
            j.append("  BEYOND SCREENING — reradiative surface above the "
                     "4,000 K no-ablation screen; needs ablation analysis.")
        else:
            j.append("  SURVIVES — reradiative nose within its surface limits; "
                     "no recession (accuracy preserved).")
        j.append("  (Loft/depress trade: run a burnout-angle sweep to see "
                 "flux vs load across shaping.)")

    else:   # glide — the stopwatch
        glide_range_km = None
        if t_fail is not None and t.size:
            rng = np.asarray(arc['range'], float)
            r_fail = float(np.interp(t_fail, t, rng)) / 1000.0
            r_end = float(rng[-1]) / 1000.0
            glide_range_km = (r_fail, r_end)
            status = 'fail'
            j.append(f"  TPS LIKELY FAILS at t≈{t_fail - t0:,.0f} s of the "
                     f"{dur:,.0f}-s glide "
                     f"({(t_fail - t0)/max(dur, 1e-9):.0%} of the mission).")
            j.append(f"  Thermal range ≈ {r_fail:,.0f} km of the "
                     f"{r_end:,.0f}-km aero range → the vehicle is "
                     f"thermal-range capped (min(aero, thermal)).")
        elif coverage is not None:
            # UHTC hot-structure nose: envelope-coverage verdict (§11.3) —
            # green/amber inside the demonstrated record, red = extrapolation
            # (named exit), never an asserted failure.
            j += coverage['lines']
            if coverage['exits']:
                status = 'analysis'
            elif coverage['dwell_s'] > 0:
                j.append(f"  Coverage: {coverage['coverage']:.0%} of "
                         f"above-ceiling dwell inside the demonstrated "
                         f"envelope.")
            if body_loc is not None and body_loc.get('material') \
                    and not body_loc.get('compromise'):
                j.append(f"  Body holds the full {dur:,.0f}-s glide.")
        elif regime is not None:
            # Ablative-nosed glider: same load-vs-record regime as a ballistic RV.
            status = regime['status']
            if regime['accuracy_sentence'] and not regime['lead_accuracy']:
                j.append("  " + regime['accuracy_sentence'])
            for c in regime['context']:
                if c:
                    j.append(f"  {c}")
            # glider ablative-tip aeroshape note (SWERVE→AHW): recession on a
            # glider tip corrupts the aeroshape it steers with — a design
            # signal, not a survival-tier driver (gliders moved to non-ablating
            # UHTC tips for exactly this reason).
            j.append("  Note: an ablative glider tip recedes as it steers — the "
                     "aeroshape drifts even when the TPS survives; gliders moved "
                     "to non-ablating (UHTC-class) tips for this reason "
                     "[SWERVE→AHW].")
        else:
            # survives — but distinguish honest survive from beyond-screening
            _worst_T = float(nose.get('T_eq_peak_K', 0) or 0)
            if _worst_T >= heating.NOTHING_SURVIVES_K and not nose.get('is_ablator'):
                status = 'analysis'
                j.append(f"  NOSE BEYOND SCREENING (T_eq "
                         f"{_worst_T:,.0f} K ≥ 4,000 K): a tip at this "
                         f"equilibrium needs ablation/oxidation-life analysis "
                         f"this tier cannot provide (R_n "
                         f"{prof.get('nose_radius_m', 0)*100:.0f} cm drives "
                         f"q̇ ∝ 1/√R_n).")
                if body_loc is not None and not body_loc.get('compromise'):
                    j.append(f"  Body holds the full {dur:,.0f}-s glide.")
            else:
                j.append(f"  TPS SURVIVES THE FULL {dur:,.0f}-s GLIDE.")
        if fam == 'analytic':
            j.append("  Family note: analytic (idealized smooth capture) — "
                     "as-flown numerical modes typically read 2–4× higher "
                     "peak flux (phugoid troughs).")

        # Windward-flank heating (screening AoA probe): a lifting vehicle
        # flies its glide at AoA, so the windward generator — not the nose —
        # carries the off-nose acreage heat.  The α=0 acreage flux scaled by
        # the modified-Newtonian amplification A(α)=sin(δ+α)/sin(δ), over the
        # glide sub-arc (heating.windward_flank_flux).  Gated on the windward
        # numbers EXISTING, not on a vehicle Form: every glider flies its
        # acreage at AoA whether or not it also dives at the end.
        _w = (fom or {}).get('windward')
        if _w and _w.get('T_eq_windward_K'):
            _T = _w['T_eq_windward_K']; _qw = _w['q_windward_MW_m2']
            _amp = _w['amplification']; _ab = _w['alpha_band_deg']
            j.append("─── Windward-flank heating (screening) ─────────────────────")
            _opstr = (f", {_T['op']:.0f} K at trim α={_w['alpha_op_deg']:.0f}°"
                      if _w.get('alpha_op_deg') is not None and _T.get('op') else "")
            j.append(f"  Windward T_eq {_T['lo']:.0f}–{_T['hi']:.0f} K across "
                     f"α {_ab[0]:.0f}–{_ab[1]:.0f}°{_opstr}  "
                     f"(δ={_w['delta_deg']:.0f}° flank; "
                     f"{_qw['lo']:.1f}–{_qw['hi']:.1f} MW/m², "
                     f"{_amp['lo']:.1f}–{_amp['hi']:.1f}× the α=0 acreage flux).")
            if _w.get('body_form') in ('wedge', 'half_cone'):
                j.append(f"  Flat-bottom lifting body: acreage fraction "
                         f"{_w.get('acreage_fraction', 0.0):g} (Candler & "
                         f"Leyva 2022 CFD anchor, single-point; the cone "
                         f"value does not apply — METHODS §13.8).")
            _wc = (_w.get('criteria') or {}).get('windward_surface')
            if _wc:
                j.append(f"  vs body {_w['body_material']}: soak "
                         f"{_wc['limit_continuous_K']:.0f} K / peak "
                         f"{_wc['limit_peak_K']:.0f} K — {_w['verdict']}.")
                if heating.WINDWARD_DRIVES_VERDICT:
                    if _wc['T_lo_K'] > _wc['limit_continuous_K'] and status == 'survive':
                        status = 'degraded'
                    elif _wc['T_hi_K'] > _wc['limit_peak_K'] and status == 'survive':
                        status = 'analysis'
            elif _w.get('verdict'):
                j.append(f"  {_w['verdict']}.")
            # Boundary-layer transition (computed gate, §13.11).
            _tst = _w.get('transition_state')
            if _tst and _tst != 'laminar':
                j.append(f"  Acreage boundary layer {_tst} at low altitude "
                         f"(Re_Rn to {_w.get('Re_Rn_peak', 0):.1e}) — flank "
                         f"flux ×{_w.get('transition_factor_peak', 1):.1f} "
                         f"applied (Kuntz 1999 gate; turbulent 3–5× band).")
            else:
                j.append(f"  Acreage boundary layer laminar over the glide "
                         f"(Re_Rn {_w.get('Re_Rn_peak', 0):.1e} below onset).")
            j.append(f"  {_w.get('thompson_band', '')}; control-fin gap "
                     f"interference 10–80× at reattachment (Alviani 2022) — "
                     f"flagged, not computed at screening tier.")

        # Terminal-dive transient block (screening): the low-AoA arc below the
        # commanded dive altitude (or 15 km for dive-at-target) — the
        # nose-stagnation complement to the windward glide flank above.  Gated
        # on the plan actually COMMANDING a dive, which is what this block
        # describes; it says nothing about whether the vehicle maneuvers.
        if _dives(prof):
            _h_dive = (prof.get('terminal_alt_km', 0.0) or 15.0) * 1000.0
            alt = np.asarray(arc['alt'], float)
            m = alt <= _h_dive
            if m.any() and np.count_nonzero(m) > 1:
                q_d = q[m]; t_d = t[m]
                j.append("─── Terminal-dive transient (screening) ───────────────────")
                j.append(f"  Dive segment below {_h_dive/1000:.0f} km: peak "
                         f"{np.max(q_d)/1e6:.1f} MW/m² over "
                         f"{t_d[-1]-t_d[0]:.0f} s — heat-sink regime "
                         f"(nose-stagnation; the windward flank/fin LE is the "
                         f"block above).")

        # Maneuver-load anchors: gated on a commanded lift cap (the helper
        # self-suppresses at g ≤ 0), so a glider that pulls g gets its
        # demonstrated-envelope context whether or not it dives at the end —
        # the case the old Form C trigger got backwards (SWERVE pulled -10°
        # AoA at 10 g and never saw this block).
        _not_thermal = _maneuver_context(prof.get('pullup_g_max', 0.0))

    # ---- NRC ladder (gliders) + method line ---------------------------------
    tail = []
    # Not about temperature: the maneuver-load context, kept at the end.
    if _not_thermal:
        tail += ["", "─── Not thermal ────────────────────────────────────────────"]
        tail += _not_thermal
    if form == 'glide' and dur > 60.0:
        tail += ["", tps_ladder.format_ladder(dur)]
    tail += [
        "",
        "Method: screening tier — Sutton-Graves cold-wall stagnation flux +",
        "radiative-equilibrium wall T; consequence bands are qualitative and",
        "flight-anchored (Reentry-F, PANT, Lin 1982, HTV-2, NRC-2008 tiers).",
        "Interior: screening bondline conduction (Dec & Braun approximate",
        "method, sans pyrolysis) where the body TPS has a cited conductivity;",
        "not a full charring-ablator (CMA-class) analysis.",
    ]

    # ── Modified-benchmark self-disclosure ───────────────────────────────────
    # A user-edited screening threshold rides on NONE of the shipped citations,
    # so the report says so plainly: an asterisk on the headline and a block
    # naming each changed number, its shipped default, and the default's source.
    _mods = thresholds.modified()
    if _mods:
        tail += ["", "Modified benchmarks (screening thresholds changed from the",
                 "shipped defaults — this verdict does not carry the citation of",
                 "record for the numbers below):"]
        for m in _mods:
            _u = (" " + m["units"]) if m["units"] else ""
            tail.append(f"  • {m['label']}: {m['value']:g}{_u} "
                        f"(default {m['default']:g}{_u}, {m['source']})")

    # ── Unified 4-tier verdict (the headline every material now shares) ──────
    tier = survival_tier(status, coverage)
    # The headline is the worst answer, never better (user, 2026-10-02).
    _answers = answers(result)
    for _a in _answers:
        if _a['tier'] and _TIER_RANK[_a['tier']] > _TIER_RANK[tier]:
            tier = _a['tier']
    tier_label, tier_color = SURVIVAL_TIERS[tier]
    if coverage is not None and coverage.get('exits') and tier in ('design', 'beyond'):
        tier_label += "  (" + " + ".join(sorted(coverage['exits'])) + ")"
    if status == 'degraded':
        # Survival is demonstrated; a screening overlay flagged a consequence.
        tier_label += "  (degraded — see report)"
    # The headline names what the plan ACTUALLY does — each descriptor earned
    # by its own trigger (descriptors()), never a Form letter standing in for
    # behaviour the plan may not carry.
    headline = f"{tier_label}   —   {' · '.join(descriptors(result))}"
    _bad = [a['short'] for a in _answers
            if a['tier'] in ('beyond', 'fail')]
    _unk = [a['short'] for a in _answers
            if a['tier'] is None and a['verdict'] == 'not computed']
    if _bad:
        headline += "   ·   " + " and ".join(_bad) + " past limit"
    if _unk:
        headline += "   ·   not computed: " + ", ".join(_unk)
    if _mods:
        headline += "  *"

    # ── Plain-language lead (inverted pyramid) ───────────────────────────────
    # Three layers a policy reader needs, in order: what was flown, why the
    # verdict is what it is (binding location + mechanism), and what would
    # change it.  The full engineering analysis — citations intact — follows
    # below the divider, unchanged.
    _name = prof.get('name') or '(unnamed)'
    _mode_phrase = ('ballistic reentry' if form == 'ballistic'
                    else f"{prof.get('guidance', 'glide')} glide")
    lead = [f"{_name} — {_mode_phrase}, {dur:,.0f}-s reentry arc."]
    because, fix = [], None
    if form == 'ballistic':
        if regime is not None:
            because.append(regime['load_sentence'])
            if regime['accuracy_sentence'] and regime['lead_accuracy']:
                because.append(regime['accuracy_sentence'])
            fix = regime['fix']
        elif status == 'fail':
            _when = f" at t≈{t_fail:,.0f} s" if t_fail is not None else ""
            because.append(f"The {_fail_loc or 'nose'} TPS fails{_when}: "
                           f"{_fail_mode or 'thermal limit exceeded'}.")
            fix = ("more capable TPS, a blunter nose, or a less demanding "
                   "trajectory")
        elif status == 'analysis':
            because.append(
                f"The nose reaches {float(nose.get('T_eq_peak_K', 0) or 0):,.0f} K — "
                f"hotter than any non-ablating surface can reradiate away, so "
                f"this screen cannot assess it; it needs a dedicated ablation "
                f"analysis.")
            fix = "a blunter nose (flux falls as 1/√R_n) or an ablative tip"
        else:
            because.append("The vehicle survives — the reradiating nose stays "
                           "within its surface limits and does not recede "
                           "(accuracy preserved).")
    else:
        _body_holds = bool(body_loc is not None and body_loc.get('material')
                           and not body_loc.get('compromise'))
        if status == 'fail' and t_fail is not None and regime is None:
            _rng = np.asarray(arc['range'], float)
            _rf = float(np.interp(t_fail, t, _rng)) / 1000.0
            _re = float(_rng[-1]) / 1000.0
            because.append(
                f"The {_fail_loc or 'nose'} TPS likely fails at "
                f"t≈{t_fail - t0:,.0f} s "
                f"({_fail_mode or 'thermal limit exceeded'}) — "
                f"{(t_fail - t0)/max(dur, 1e-9):.0%} into the glide; range is "
                f"thermally capped at ≈{_rf:,.0f} of the {_re:,.0f}-km aero "
                f"range.")
            fix = "a shorter or steeper profile, or more capable TPS"
        elif regime is not None:
            # Ablative-nosed glider: load-vs-record regime (as for a ballistic RV).
            because.append(regime['load_sentence'])
            if regime['accuracy_sentence'] and regime['lead_accuracy']:
                because.append(regime['accuracy_sentence'])
            if regime['status'] != 'fail' and _body_holds:
                because.append("The body TPS holds the full glide.")
            fix = regime['fix']
        elif coverage is not None and coverage.get('exits'):
            _ceil_C = (float(_nose_mat['continuous_K']) - 273.15) if _nose_mat else 1650.0
            _dwell_cl = (
                f"the demonstrated test record ends at "
                f"{coverage['floor_s']:.0f} s, so most of this dwell is "
                f"extrapolation, not demonstration"
                if 'too long' in coverage['exits'] else
                f"within the {coverage['floor_s']:.0f}-s demonstrated dwell "
                f"record")
            because.append(
                f"The {_nose_lbl} nose runs above {_ceil_C:.0f} °C for "
                f"{coverage['dwell_s']:,.0f} s — {_dwell_cl}.")
            if 'too hot' in coverage['exits']:
                because.append(
                    "The surface crosses into active oxidation — the "
                    "protective silica layer is lost and degradation "
                    "accelerates; this is the failure-side edge of the "
                    "envelope, not just missing data.")
            if _body_holds:
                because.append(f"The body TPS holds the full glide; the nose "
                               f"is the binding problem.")
            fix = ("loft, blunt the tip, or fly a lower-flux profile"
                   if 'too hot' in coverage['exits']
                   else "shorten the hot dwell (a steeper or shorter glide)")
        elif status == 'analysis':
            because.append(
                f"The nose reaches {float(nose.get('T_eq_peak_K', 0) or 0):,.0f} K — "
                f"hotter than any non-ablating surface can reradiate away, so "
                f"this screen cannot assess it; it needs a dedicated ablation "
                f"analysis." + ("  The body TPS holds the full glide."
                                if _body_holds else ""))
            fix = "a blunter nose (flux falls as 1/√R_n) or an ablative tip"
        elif status == 'degraded':
            because.append("The TPS survives, but a screening overlay "
                           "(windward-flank heating) flags a consequence — "
                           "see the full analysis below.")
        else:
            because.append(f"Nose and body both hold the full {dur:,.0f}-s "
                           f"glide within the demonstrated record.")
    # The back of the body layer in the LEAD when it is past its limit: the
    # skin can hold while the structure behind it cooks, which a nose/skin
    # verdict alone would miss.  Said of the structure, not the payload.
    _bf = next((a for a in answers(result)
                if a['short'] in ('bondline', 'back face')), None)
    if _bf and _bf['tier'] in ('beyond', 'fail'):
        _where = ("the bondline" if _bf['short'] == 'bondline'
                  else "the back of the hot structure")
        because.append(
            f"The heat also reaches {_where}: {_bf['value']}, past the "
            f"{_bf['limit']} limit — the skin may hold, but the structure "
            f"behind it does not.")
        if not fix:
            fix = "thicker body TPS, a lower-load trajectory, or an insulating sub-layer"
    lead += ["", " ".join(because)]
    if fix:
        lead += ["", f"What would change the verdict: {fix}."]
    # NRC lineage context, written to keep the two ladders distinct: the NRC
    # rungs are a DESIGN LINEAGE (what TPS class each mission duration
    # historically required), not a demonstration of the flown material.
    if form == 'glide' and dur > 60.0:
        _ctx = (f"For context: gliders of this class historically used "
                f"ablative carbon-phenolic to ~800 s (NRC 2008, AMaRV "
                f"lineage); past ~{tps_ladder.CROSSOVER_S:,.0f} s the record "
                f"steps to advanced carbon-carbon.")
        if uhtc_nose and coverage is not None:
            _ctx += (f"  This vehicle instead flies a reradiating UHTC nose — "
                     f"a different material with a different failure mode, "
                     f"whose own demonstrated record ends at "
                     f"{coverage['floor_s']:.0f} s.")
        elif _nose_mat and _nose_mat.get('is_ablator'):
            _ctx += (f"  This vehicle flies an ablative nose "
                     f"({_nose_mat.get('label', '?')}), judged here by its "
                     f"flown heat load, not dwell.")
        lead += ["", _ctx]
    if _mods:
        lead += ["", "* Screening benchmarks modified from the shipped "
                     "defaults — see Modified benchmarks below."]

    # ── Survival map: the hinge between the lead and the full analysis — a
    # one-glance station × question matrix; each cell elaborated below it.
    _map_lines, _map_spans = answers_block(_answers)
    _map_block = "\n".join(_map_lines) + "\n\n"

    # The four answers first; the plain-language lead and everything else
    # below them, the engineering detail behind the divider.
    _divider = "═══ Full analysis " + "═" * 42
    body = _map_block + "\n".join(lead) + "\n\n" + _divider + "\n\n" \
           + "\n".join(hdr) + "\n\n" + "\n".join(budget) + "\n" \
           + "\n".join(j) + "\n" + "\n".join(tail) + "\n"

    plot = dict(
        t=t - t0, q_MW=q_MW, Q_MJ=Q_MJ,
        t_fail=(t_fail - t0) if t_fail is not None else None,
        glide_s=dur if form == 'glide' else None,
        tiers=(tps_ladder.NAS_LINEAGE if form == 'glide' else None),
        tier=tier, tier_color=tier_color,
        # bands recolored from per-timestep coverage class → survival tier
        bands=([(b0 - t0, b1 - t0, _BAND_CLASS_TIER.get(c, c))
                for b0, b1, c in coverage['bands']]
               if coverage is not None else None),
    )
    return dict(status=status, tier=tier, headline=headline, body=body,
                form=form, plot=plot, map_spans=_map_spans)
