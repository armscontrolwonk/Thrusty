"""
Reentry-heating survivability figure of merit.

Given a reentry/glide arc (time, density, airspeed), evaluate three
complementary failure criteria and return per-criterion margins, the earliest
"compromise point", and a verdict.  Grounded in HEATING_TPS_REFERENCES.md:

  1. Peak surface temperature — radiative-equilibrium T_eq = (q̇/εσ)^¼ vs the
     TPS material's SHORT-DURATION limit.  Surface melts/ablates at the peak
     (pull-out).  q̇ is Sutton-Graves stagnation heating at the NOSE radius
     (the engineering reduction of Fay-Riddell; radiative gas heating is
     negligible <~9 km/s per Tauber-Sutton and omitted).

  2. Heat soak (oxidation) — time the surface holds above the material's
     CONTINUOUS-use limit.  TPS oxidizes/degrades over a long glide
     (the HTV-2 aeroshell mode); the literature-standard reusable-TPS
     criterion is time-at-temperature.

  3. Lumped heat-sink burn-up — Reynerson, AIAA 2006-6275.  Integrated heat
     that the surface cannot re-radiate soaks into the body mass; the body
     melts when that accumulated heat exceeds m·c·(T_melt−T₀).  Driven by the
     BODY-radius stagnation flux (blunter → lower than the nose).  The
     re-radiation cap is taken at the continuous limit, so a surface that can
     reject its flux never accumulates (correct for a radiating glider), while
     a flux spike above the cap soaks in (the bare-body / short-pulse case).

All temperatures are kelvin.  This is a screening figure of merit, not a
through-wall conduction solution (that backface upgrade is future work).
"""
import numpy as np

SIGMA = 5.670374419e-8            # Stefan-Boltzmann, W/m²/K⁴
_SG_K = 1.7415e-4                 # Sutton-Graves constant (SI, W/m²), Earth air
_T0   = 298.0                     # reference temperature, K
NOTHING_SURVIVES_K = 4000.0       # T_eq above all usable materials → the
                                  # no-ablation equilibrium model is invalid here
                                  # (ablators survive by recession/blowing, not by
                                  # staying below a fixed surface limit)

# TPS material ladder — HEATING_TPS_REFERENCES.md §2 + HEATING_MODEL_CROSSCHECK.md §10.4.
# CONSUMED by the current FOM (do not change for existing keys — verdict stability):
#   peak_K       : short-duration surface limit (melt / ablation onset)
#   continuous_K : sustained / oxidation (soak) limit, also the re-radiation cap
#   melt_K       : bulk melt/sublimation for the lumped heat sink (None → continuous_K)
#   c_J_kgK      : specific heat for the lumped heat sink
#   label        : display name
# Phase-1 metadata (NOT yet consumed — used by the per-location evaluator, Phase 2+):
#   group        : 'metal' | 'hot_structure' | 'insulative' | 'ablative'.  Architecture flag:
#                  'metal'/'hot_structure' = the material IS the load path → bondline collapses
#                  onto its own limit (§10.1, non-separating hot-structure case); 'insulative'/
#                  'ablative' = a layer over a separate structure → bondline applies.  Also the
#                  GUI-flyout dropdown grouping.
#   is_ablator   : recedes (δ = Q/(ρ·H_eff)); else reradiative/heat-sink limited
#   density_kg_m3: for the lumped heat-sink mass and ablator recession
#   H_eff_MJ_kg  : effective heat of ablation Q* (ablators only; None otherwise).
#                  Q* is enthalpy-dependent, NOT a fixed constant; these nominals sit at the
#                  conservative (low) end of the flight/handbook band (CP ~10-30, PICA higher,
#                  C/C sublimation regime) so the recession screen OVER-predicts.  Bands +
#                  provenance: BENCHMARKING.md "Form A anchors"; benchmarks/form_a/phase2-heff-bands.md.
#                  Direction is bound-checked in test_form_a_bounds.py (predicted delta >= measured
#                  for the recovered Stardust/Hayabusa capsules).  NOT tuned to those capsules.
#   oxidation_dwell_s : representative oxidation-limited dwell life at its severe-use temperature
#                  (UHTC ~60-140 s at 2700 °C, §10.4/Tului); None if not dwell-limited
# NEW entries (carbon_carbon, carbon_phenolic, c_sic, cc_hot_structure, silica_phenolic, sirca,
# pica) carry SCREENING-tier peak/continuous estimates pending a verification pass (§10.4).
# The `uhtc` entry is RETUNED per SURVIVABILITY_REPORT_DESIGN.md §11.4 (grounded glass ceiling +
# demonstrated dwell floor) — see the inline comment on the entry; the envelope-coverage verdict
# that consumes it lives in survivability_report.py (green/amber/red, §11.3).
TPS_MATERIALS = {
    # --- structural metals (heat-sink / bare hot structure) ---
    "aluminum":        dict(peak_K=775,  continuous_K=450,  melt_K=775,  c_J_kgK=900,  label="Aluminum",
                            group="metal", is_ablator=False, density_kg_m3=2700, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=177.0,
                            k_source="TPSX id 60, Al 2024-T6: 177 W/m·K isotropic, room temperature"),
    "titanium":        dict(peak_K=1900, continuous_K=870,  melt_K=1900, c_J_kgK=520,  label="Titanium",
                            group="metal", is_ablator=False, density_kg_m3=4500, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=6.92,
                            k_source="TPSX id 261, Ti-6Al-4V: 6.92 W/m·K isotropic, room temperature (rises with temperature)"),
    "steel":           dict(peak_K=1700, continuous_K=1100, melt_K=1700, c_J_kgK=500,  label="Steel",
                            group="metal", is_ablator=False, density_kg_m3=7800, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=14.9,
                            k_source="TPSX id 57, AISI 304 stainless: 14.9 W/m·K isotropic, room temperature (rises with temperature)"),
    # --- non-ablating hot structures (the material IS the structure) ---
    "rcc":             dict(peak_K=1922, continuous_K=1811, melt_K=None, c_J_kgK=1200, label="Coated carbon-carbon (RCC)",
                            group="hot_structure", is_ablator=False, density_kg_m3=1600, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=3.89,
                            k_source="TPSX id 24, RCC (19-ply, coated): 3.89 W/m·K through the thickness (6.07 in-plane), room temperature"),
    # C/SiC limits per TPSX id 26: multiple-use 1920 K (continuous), single-
    # use 1980 K (peak) — replaces the flat screening 1970/1970 estimate with
    # NASA's own database values (crawl archived in data/tpsx/).
    "c_sic":           dict(peak_K=1980, continuous_K=1920, melt_K=None, c_J_kgK=1200, label="C/SiC (coated CMC)",
                            group="hot_structure", is_ablator=False, density_kg_m3=2000, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=4.01,
                            k_source="TPSX id 26, 2-D C/SiC: 4.01 W/m·K through the thickness (11.7 in-plane), room temperature"),
    "cc_hot_structure":dict(peak_K=2170, continuous_K=2170, melt_K=None, c_J_kgK=1200, label="C/C hot structure (HTV-2)",
                            group="hot_structure", is_ablator=False, density_kg_m3=1800, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=3.63,
                            k_source="TPSX id 25, ACC (2-D woven PAN carbon-carbon): 3.63 W/m·K, room temperature — the closest woven C/C in TPSX, not a measured HTV-2 aeroshell value; the ablative C/C entry (id 36) is 110 W/m·K, so the interior answer for this material is uncertain by more than an order of magnitude"),
    # uhtc: retuned per SURVIVABILITY_REPORT_DESIGN.md §11.4 (was continuous_K 1900, dwell 120 s
    # hard line).  continuous_K = 1923 K (1650 °C) — the borosilicate-glass PROTECTIVENESS
    # ceiling, ≥5 sources (Monteverde 2012, Peters 2024, Fahrenholtz & Hilmas, Marschall, Li).
    # oxidation_dwell_s = 300 s — the DEMONSTRATED FLOOR above the ceiling, conservatively the
    # low anchor (Monteverde 2013: 300 s at 1973 K, zero recession; sharp-tip survival extends
    # to ~575 s at 2450 °C, Monteverde 2012).  A floor, NOT a cliff: past it the report flags
    # extrapolation, it does not assert failure (§11.1).  peak_K 2700 ≈ the demonstrated sharp
    # ZrB2-SiC tip peak (2450 °C, CFD-sourced).  Anchor dataset: survivability_report.UHTC_ANCHORS.
    "uhtc":            dict(peak_K=2700, continuous_K=1923, melt_K=3500, c_J_kgK=600,  label="UHTC (ZrB2/HfB2-SiC)",
                            group="hot_structure", is_ablator=False, density_kg_m3=6000, H_eff_MJ_kg=None, oxidation_dwell_s=300,
                            k_W_mK=98.7,
                            k_source="TPSX id 28, ZrB2/SiC (MANLABS, AFML-TR-68-190): 98.7 W/m·K ±5%, measured 100–2000 °C in argon; HfB2/SiC (id 30) is 79.1, and Squire & Marschall 2010 Table 1 give 130 (295 K) to 71 (2000 K) for an HfB2 composite — UHTC conductivity depends on how the part was made"),
    # --- reusable insulator (a layer over a separate structure) ---
    "silica_tile":     dict(peak_K=1811, continuous_K=1533, melt_K=None, c_J_kgK=1000, label="Silica tile (LI-900)",
                            group="insulative", is_ablator=False, density_kg_m3=144, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=0.0476,
                            k_source="TPSX id 1, LI-900: 0.0476 W/m·K through the thickness, measured, room temperature (rises several-fold when hot, so this runs cool)"),
    # Blankets and an aerogel for the layers inside a body (TODO item 11,
    # step 2).  Every number is the TPSX entry's own: density, specific heat,
    # single-use limit (peak_K), multiple-use limit (continuous_K) and the
    # standard-conditions conductivity; the conductivity curves are in
    # TPSX_CURVES below.
    "afrsi":           dict(peak_K=1090, continuous_K=922,  melt_K=None, c_J_kgK=741,  label="AFRSI blanket",
                            group="insulative", is_ablator=False, density_kg_m3=96.1, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=0.0329,
                            k_source="TPSX id 12, AFRSI blanket: 0.0329 W/m·K through the thickness, standard conditions"),
    "tabi":            dict(peak_K=1700, continuous_K=1480, melt_K=None, c_J_kgK=741,  label="TABI blanket",
                            group="insulative", is_ablator=False, density_kg_m3=112, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=0.0395,
                            k_source="TPSX id 17, TABI blanket: 0.0395 W/m·K, standard conditions"),
    "nomex_felt":      dict(peak_K=644,  continuous_K=506,  melt_K=None, c_J_kgK=1310, label="Nomex felt (FRSI)",
                            group="insulative", is_ablator=False, density_kg_m3=86.5, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=0.0406,
                            k_source="TPSX id 18, FRSI blanket (Nomex felt): 0.0406 W/m·K, standard conditions"),
    "silica_aerogel":  dict(peak_K=1270, continuous_K=873,  melt_K=None, c_J_kgK=755,  label="Silica aerogel",
                            group="insulative", is_ablator=False, density_kg_m3=100, H_eff_MJ_kg=None, oxidation_dwell_s=None,
                            k_W_mK=0.0099,
                            k_source="TPSX id 32, silica aerogel: 0.0099 W/m·K, standard conditions"),
    # --- ablators (sacrificial layer; recede) ---
    # Ablator verdicts compare the flown heat LOAD against a demonstrated flight
    # record (like the UHTC dwell floor), NOT a computed recession point-value:
    #   demonstrated_load_MJ_m2 : the largest cited flight stagnation heat load
    #                             for this material family (None where the open
    #                             record has no integrated-load anchor).
    #   H_eff_bound_MJ_kg       : the MOST OPTIMISTIC cited effective-heat-of-
    #                             ablation, used ONLY for the burn-through
    #                             tripwire (red fires only if the shield is
    #                             consumed even at this best case).  The nominal
    #                             H_eff_MJ_kg drives only the reported δ band.
    # carbon_ablator is the family-generic carbon entry: it carries the SAME
    # graphite/C-C family flight record + optimistic H_eff bound as
    # carbon_carbon (records are family-level, METHODS §13.6).  Leaving these
    # unset silently collapsed the burn-through BOUND to the conservative
    # nominal H_eff — turning the tripwire back into the banned point-estimate
    # (a C-HGB-class carbon nose at ~97% of the Reentry-F load read false-red).
    "carbon_ablator":  dict(peak_K=3900, continuous_K=2000, melt_K=3900, c_J_kgK=1500, label="Ablative carbon-carbon",
                            group="ablative", is_ablator=True, density_kg_m3=1450, H_eff_MJ_kg=15, oxidation_dwell_s=None,
                            k_W_mK=110.0,
                            k_source="TPSX id 36, carbon-carbon ablative heatshield (Aerotherm 1989): 110 W/m·K isotropic, room temperature",
                            demonstrated_load_MJ_m2=3870, H_eff_bound_MJ_kg=175,
                            demonstrated_load_source="Reentry-F graphite nosetip flew Q ≈ 3.87 GJ/m² (NASA CR-154044 / LWP-460, pixel-traced, ±20%; family-level record)"),
    "carbon_carbon":   dict(peak_K=3900, continuous_K=2000, melt_K=3900, c_J_kgK=1500, label="Bare carbon-carbon (nose)",
                            group="ablative", is_ablator=True, density_kg_m3=1800, H_eff_MJ_kg=40, oxidation_dwell_s=None,
                            k_W_mK=110.0,
                            k_source="TPSX id 36, carbon-carbon ablative heatshield (Aerotherm 1989): 110 W/m·K isotropic, room temperature",
                            demonstrated_load_MJ_m2=3870, H_eff_bound_MJ_kg=175,
                            demonstrated_load_source="Reentry-F graphite nosetip flew Q ≈ 3.87 GJ/m² (NASA CR-154044 / LWP-460, pixel-traced, ±20%)"),
    # k_W_mK: through-thickness thermal conductivity for the bondline screen
    # (§13.10) — wired ONLY where citable; None = bondline not evaluated.
    # Since 2026-10-02 every entry carries one: the hot structures, metals,
    # tile and C/C take the TPSX value named in their k_source (pinned in
    # test_tpsx_crosscheck.py).  TPSX quotes these near room temperature;
    # the k_source says where a material's k moves strongly when hot.
    #   carbon_phenolic 1.5  — CHAR value at ~1900 K (Cabrera & West 2026
    #       Table A4, Sutton's data: 1.502 W/mK at 1923 K; virgin runs
    #       0.48–0.77, Table A3) — char > virgin, conservative-HIGH for
    #       bondline conduction.
    #   silica_phenolic 0.35 — glass-fiber phenolic 0.20 Btu/hr·ft·°F
    #       (Handbook of Materials Science III p.34, via Finke IDA P-2395);
    #       VIRGIN value — char conductivity uncited, so margins near the
    #       limit are soft (flagged in the screen's warnings).
    "carbon_phenolic": dict(peak_K=3900, continuous_K=2000, melt_K=3900, c_J_kgK=1120, label="Carbon phenolic",
                            group="ablative", is_ablator=True, density_kg_m3=1450, H_eff_MJ_kg=15, oxidation_dwell_s=None,
                            demonstrated_load_MJ_m2=60, H_eff_bound_MJ_kg=20, k_W_mK=1.5,
                            k_source="char k at ~1900 K (Cabrera & West 2026 Table A4, Sutton's data) — conservative-high",
                            demonstrated_load_source="Pioneer Venus Large Probe CP heatshield survived ~60 MJ/m² stagnation (Cabrera & West 2026, JSR 63(2) coupled reconstruction; figure-integrated ±25%; short radiation-heavy CO₂ pulse — conservative as a load record; Hayabusa CP corroborates ~2-3× higher, pulse-duration-soft)"),
    # silica_phenolic is flight-flown ACREAGE TPS on this exact vehicle class:
    # SWERVE's body TPS was silica phenolic over machined aluminum (C-C tip/
    # leading edges) — Murbach AIAA 93-0313, firsthand.  CMA response for the
    # SWERVE-derived shield (Murbach SSC97-V-2 Table 1, Mars entry): ZERO
    # surface recession at 0.68 MW/m² / 1411 K sidewall (char 0.3 cm,
    # pyrolysis 2.6 cm, aluminum 483 K behind 5 cm); 1.0 cm recession at the
    # 4.65 MW/m² / 2200 K wing LE.  No flown-load record wired: the flown
    # SWERVE heat load is not published (reconstruction = a P3 item).
    "silica_phenolic": dict(peak_K=1700, continuous_K=1700, melt_K=1700, c_J_kgK=1000, label="Silica phenolic",
                            group="ablative", is_ablator=True, density_kg_m3=1700, H_eff_MJ_kg=10, oxidation_dwell_s=None,
                            demonstrated_load_MJ_m2=None, demonstrated_load_source="", H_eff_bound_MJ_kg=10, k_W_mK=0.710,
                            k_source="TPSX id 162, MX2600 (90°, cross-ply = through-thickness) virgin: 0.710 W/m·K (TPSX source-field 'unknown'; the classic RV silica-phenolic) — supersedes the 0.35 glass-fiber Handbook value (Finke IDA P-2395), conservative-high for bondline; char k still uncited"),
    # SIRCA-14A per TPSX id 41 (NASA Ames TPS Materials db, virgin; page
    # captured 2026-07-23; POC F. Milos; refs Tran et al., TPSX #70-73):
    # AIM-10 tile infiltrated w/ silicone, final ρ ≈ 0.224 g/cc (measured,
    # ±4.8%); c 1200 J/kg·K; k 0.0629 W/m·K (TPSX flags nonstp/source-
    # unknown).  H_eff from TPSX's 5-point curve vs PRESSURE (22.5–40.5 kPa):
    # 37.4 MJ/kg at 40.5 kPa rising to 2.1 GJ/kg at 22.5 kPa.  Wiring:
    # nominal = 37.4 (the curve's high-pressure MINIMUM — and RV stagnation
    # pressures exceed the curve's 0.4 atm ceiling, so even the nominal may
    # be optimistic for steep entries: Q* is pressure-sensitive and this
    # screen is pressure-blind, the Dec & Braun PICA lesson); bound = 165
    # (top of the 25–31 kPa cluster 103–165; the 2.1 GJ/kg point is EXCLUDED
    # from the bound as a recession→0 artifact — documented in BENCHMARKING,
    # never silently dropped).
    "sirca":           dict(peak_K=1700, continuous_K=1700, melt_K=1700, c_J_kgK=1200, label="SIRCA-14A (low-density ablator)",
                            group="ablative", is_ablator=True, density_kg_m3=224,  H_eff_MJ_kg=37.4, oxidation_dwell_s=None,
                            demonstrated_load_MJ_m2=None, demonstrated_load_source="", H_eff_bound_MJ_kg=165.0, k_W_mK=0.0629,
                            k_source="TPSX (NASA Ames) SIRCA-14A virgin, id 41: 0.0629 W/m·K (TPSX flags nonstp/source-unknown); supersedes the Murbach-1997 ratio estimate 0.04"),
    # PICA k + H_eff bound per TPSX id 43 (virgin; crawl archived in
    # data/tpsx/): k 0.305 W/m·K MEASURED (Tran et al. AIAA 96-1911, TPSX
    # nonstp flag — conservative-high for the bondline screen) closes the
    # "low-density ablator k" ledger item; H_eff 115 ±5.8 MJ/kg MEASURED
    # (Tran arc-jet, TPSX #68/#74, nonstp*) becomes the optimistic bound
    # (supersedes Winter-2014's implied 77 top; nominal 35 unchanged).  TPSX
    # density 236 ±12 vs our wired 270 — logged, not churned (BENCHMARKING).
    "pica":            dict(peak_K=3600, continuous_K=2000, melt_K=3600, c_J_kgK=1200, label="PICA (low-density ablator)",
                            group="ablative", is_ablator=True, density_kg_m3=270,  H_eff_MJ_kg=35, oxidation_dwell_s=None,
                            demonstrated_load_MJ_m2=276, H_eff_bound_MJ_kg=115, k_W_mK=0.305,
                            k_source="TPSX (NASA Ames) PICA virgin, id 43: 0.305 W/m·K, measured (Tran et al. AIAA 96-1911; TPSX nonstp flag — conservative-high for bondline)",
                            demonstrated_load_source="Stardust PICA forebody flew Q ≈ 276 MJ/m² and was recovered (Stackpoole et al. AIAA 2008-1202)"),
}

# Dropdown groups for the GUI flyout (§10.1/§10.4) — order = display order.
TPS_MATERIAL_GROUPS = ("metal", "hot_structure", "insulative", "ablative")


def materials_by_group():
    """Return {group: [(key, label), ...]} for building the per-location material dropdown.

    Both the nose and body selectors draw from the full catalog (a non-separating warhead
    needs metals/hot-structure in the nose slot too, §10.1); the GUI orders by group.
    """
    out = {g: [] for g in TPS_MATERIAL_GROUPS}
    for key, m in TPS_MATERIALS.items():
        out.setdefault(m.get("group", "ablative"), []).append((key, m["label"]))
    return out


# Property curves against temperature from TPSX (data/tpsx/curves.json, built
# by tpsx_curves.py from the archived property pages).  (TPSX id, property
# name) per catalog key.  Where a key is absent the conduction screen uses the
# single k_W_mK / c_J_kgK above:
#   carbon_phenolic keeps its CHAR k (Cabrera & West); Narmco 4028's TPSX
#     curve is virgin material to 675 K, the wrong state for a heated shield.
#   carbon_carbon, carbon_ablator (id 36) and pica (id 43): TPSX gives no table.
#   silica_phenolic (id 162): the table is the single standard value.
TPSX_CURVES = {
    "aluminum":         dict(k=(60, "Thermal Conductivity (Isotropic)"),  c=(60, "Specific Heat")),
    "titanium":         dict(k=(261, "Thermal Conductivity (Isotropic)"), c=(261, "Specific Heat")),
    "steel":            dict(k=(57, "Thermal Conductivity (Isotropic)"),  c=(57, "Specific Heat")),
    "rcc":              dict(k=(24, "Thermal Conductivity (Thru-the-Thickness)"), c=(24, "Specific Heat")),
    "c_sic":            dict(k=(26, "Thermal Conductivity (Thru-the-Thickness)"), c=(26, "Specific Heat")),
    "cc_hot_structure": dict(k=(25, "Thermal Conductivity (Isotropic)")),
    "uhtc":             dict(k=(28, "Thermal Conductivity (Isotropic)"),  c=(28, "Specific Heat")),
    "silica_tile":      dict(k=(1, "Thermal Conductivity (Thru-the-Thickness)"), c=(1, "Specific Heat")),
    "sirca":            dict(k=(41, "Thermal Conductivity (Isotropic)"),  c=(41, "Specific Heat")),
    "afrsi":            dict(k=(12, "Thermal Conductivity (Thru-the-Thickness)"), c=(12, "Specific Heat")),
    "tabi":             dict(k=(17, "Thermal Conductivity (Isotropic)"),  c=(17, "Specific Heat")),
    "nomex_felt":       dict(k=(18, "Thermal Conductivity (Isotropic)"),  c=(18, "Specific Heat")),
    "silica_aerogel":   dict(k=(32, "Thermal Conductivity (Isotropic)"),  c=(32, "Specific Heat")),
}
_CURVE_CACHE = {}


def material_curve(material_key, which):
    """(T_K, value, note) for a material's TPSX curve, which = 'k' or 'c';
    None if the catalog names none.  Porous insulators are tabulated by gas
    pressure too: the highest tabulated pressure is used (the most
    conductive, the cautious side for whatever sits behind the layer).
    Where TPSX repeats a temperature, the largest k (or the mean c) is
    kept.  The note says which entry, which pressure and what range."""
    spec = TPSX_CURVES.get(str(material_key or ""), {}).get(which)
    if not spec:
        return None
    key = (spec, which)
    if key in _CURVE_CACHE:
        return _CURVE_CACHE[key]
    import json, os
    if "_all" not in _CURVE_CACHE:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "tpsx", "curves.json")
        _CURVE_CACHE["_all"] = json.load(open(path))
    mid, prop = spec
    tab = _CURVE_CACHE["_all"].get(str(mid), {}).get(prop)
    if not tab or not tab["rows"]:
        _CURVE_CACHE[key] = None
        return None
    cols = tab["columns"]
    vi = 0
    ti = next(i for i, c in enumerate(cols) if c.startswith("Temperature"))
    pi = next((i for i, c in enumerate(cols) if c.startswith("Pressure")), None)
    rows = [r for r in tab["rows"]
            if isinstance(r[vi], float) and isinstance(r[ti], float)]
    p_used = None
    if pi is not None:
        ps = [r[pi] for r in rows if isinstance(r[pi], float)]
        if ps:
            p_used = max(ps)
            rows = [r for r in rows if r[pi] == p_used]
    by_T = {}
    for r in rows:
        by_T.setdefault(r[ti], []).append(r[vi])
    T = np.array(sorted(by_T))
    if T.size < 2:
        _CURVE_CACHE[key] = None
        return None
    agg = max if which == "k" else (lambda v: sum(v) / len(v))
    V = np.array([agg(by_T[x]) for x in T])
    note = (f"TPSX id {mid} {prop.lower()} curve, {T[0]:,.0f}–{T[-1]:,.0f} K"
            + (f" at {p_used:,.0f} Pa" if p_used else ""))
    _CURVE_CACHE[key] = (T, V, note)
    return _CURVE_CACHE[key]


def is_hot_structure(material_key):
    """True if the material is its own load path (metal / hot structure) → bondline collapses
    onto its own limit (§10.1).  Layers (insulative / ablative) sit over a separate structure."""
    m = TPS_MATERIALS.get(material_key or "")
    return bool(m) and m.get("group") in ("metal", "hot_structure")


# Sentinel material keys for user-defined (bespoke) materials, one per location.
CUSTOM_NOSE_KEY = "custom_nose"
CUSTOM_BODY_KEY = "custom_body"


def register_custom_material(key, props):
    """Inject a user-defined material into TPS_MATERIALS so the key-based FOM can consume it.

    `props` is a partial catalog entry (from ROParams.nose_tps_custom / body_tps_custom);
    missing fields are filled with safe defaults so a bespoke material is always well-formed.
    Called for any RV carrying custom props before the heating FOM runs.  A falsy `props`
    removes any stale registration for `key`.  Returns the resolved key (or "" if cleared).
    """
    if not key or not props:
        TPS_MATERIALS.pop(key, None)
        return ""
    is_abl = bool(props.get("is_ablator", False))
    limit = props.get("continuous_K") or props.get("peak_K") or 0.0
    try:
        limit = float(limit)
    except (TypeError, ValueError):
        limit = 0.0
    def _num(v, default):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    entry = dict(
        label=str(props.get("label") or "Custom material"),
        group="ablative" if is_abl else "hot_structure",
        is_ablator=is_abl,
        peak_K=_num(props.get("peak_K"), limit),
        continuous_K=_num(props.get("continuous_K"), limit),
        melt_K=_num(props.get("melt_K"), limit) if props.get("melt_K") else None,
        c_J_kgK=_num(props.get("c_J_kgK"), 1200.0),
        density_kg_m3=_num(props.get("density_kg_m3"), 1800.0),
        H_eff_MJ_kg=(_num(props.get("H_eff_MJ_kg"), 15.0) if is_abl else None),
        oxidation_dwell_s=None,
        # Bespoke ablators have no flight record; the tripwire falls back to the
        # nominal H_eff (conservative — it may over-flag burn-through).
        demonstrated_load_MJ_m2=None, demonstrated_load_source="",
        H_eff_bound_MJ_kg=(_num(props.get("H_eff_MJ_kg"), 15.0) if is_abl else None),
    )
    TPS_MATERIALS[key] = entry
    return key

# Reentry heating benchmarks — HEATING_TPS_REFERENCES.md §3.  Per entry:
#   q_MW : peak stagnation flux (MW/m²);  Q_MJ : integrated load (MJ/m², per
#   unit area, = ∫q̇ dt);  conf : 'solid' (CFD reconstruction) or 'rough'.
# Apollo (793 W/cm², 46,792 J/cm²), Stardust (942 W/cm², 27.6 kJ/cm²) and MSL
# (197 W/cm² design, 5,477 J/cm²) are CFD-solid.  Shuttle is now pinned to the
# STS-1 flight reconstruction (NASA LaRC benchmark, NTRS 19820036242 /
# 19820015618): windward tiles ~5 Btu/ft²·s (≈0.06 MW/m²), RCC nose-cap /
# wing-leading-edge stagnation peak ~50 Btu/ft²·s (≈0.6 MW/m², surface ~1650 °C);
# we anchor q_MW on the RCC stagnation peak (the hot spot).  Q_MJ≈66 MJ/m² is
# the integrated load at the windward centerline x/L=0.4 — the acreage/tile
# location where the soak and TPS mass live, the right place for the load metric
# — obtained by integrating the STS-1 flight-data heat-flux history (radiation-
# equilibrium reduction, Ried et al. NTRS 19820015618 Fig. 11: peak ~6 W/cm²
# over a ~1500 s pulse → ∫q̇dt ≈ 6.6 kJ/cm²; ±~20% from digitizing the plot).
# So the Shuttle's two metrics intentionally reference their most-relevant
# locations (peak→RCC nose, load→windward acreage).  ICBM-RV is anchored on
# Reentry F (5° half-angle cone, R_n=2.54 mm initial, Mach ~20, V≈6.1 km/s).
# Its stagnation heating 9,000–28,000 Btu/ft²·s (≈102–318 MW/m²) is the NASA
# PREFLIGHT-predicted nominal (LWP-460, via Berry Fig. 6) — the ablating
# graphite tip was not calorimetered, so the flight-MEASURED data is the
# cone-flank turbulent heating (15–50 Btu/ft²·s, TM X-2253) and the nose
# recession.  The flight flew near-nominal and the prediction methods were
# validated against the flank flight data (Thompson et al. 1989), so we keep
# the 318 MW/m² peak but it is a flight-validated PREDICTION, not a measurement;
# blunter 1–5 cm operational tips scale to ~70–160 MW/m² (1/√R_N).  conf='solid'.
# Q_MJ omitted (steep, ~few-second ablative pulse; no clean ∫q̇dt value).
_BENCHMARKS = {
    "ICBM RV":  dict(q_MW=318.0, Q_MJ=None, conf="solid"),
    "Stardust": dict(q_MW=9.4,  Q_MJ=276.0, conf="solid"),
    "Apollo":   dict(q_MW=7.9,  Q_MJ=468.0, conf="solid"),
    "MSL":      dict(q_MW=2.0,  Q_MJ=55.0,  conf="solid"),
    "Shuttle":  dict(q_MW=0.6,  Q_MJ=66.0,  conf="solid"),
}


def _nearest_benchmark(value, key):
    """Nearest benchmark to *value* by log-distance on field *key* ('q_MW' or
    'Q_MJ'), as a ratio string; '(rough)' appended for flagged anchors."""
    cands = [(n, b[key], b["conf"]) for n, b in _BENCHMARKS.items() if b.get(key)]
    if value <= 0 or not cands:
        return "n/a"
    n, v, conf = min(cands, key=lambda c: abs(np.log(value / c[1])))
    return f"{value / v:.1f}× {n}" + (" (rough)" if conf == "rough" else "")


def _stag_flux(rho, V, radius_m):
    return _SG_K * np.sqrt(np.asarray(rho) / max(radius_m, 1e-4)) * np.asarray(V) ** 3


def heating_figure_of_merit(t, rho, V, alt, rng, *, nose_radius_m=0.05,
                            body_radius_m=0.0, emissivity=0.85, material="",
                            mass_kg=0.0, frontal_area_m2=0.0, soak_dwell_s=120.0,
                            recession_depth_m=0.0, include_radiative=True):
    """Evaluate the heating-survivability SCREENING figure of merit over a
    reentry arc.  This is a stagnation-point convective indicator, not a
    through-wall TPS response model; verdicts are screening flags (see the
    "warnings" key), not survival guarantees.

    t, rho, V, alt, rng : 1-D arrays over the reentry/glide phase (SI).
    Returns a dict: q_peak (NOSE-STAGNATION reference flux), peak T_eq,
    integrated load, per-criterion margins, compromise point, verdict,
    benchmark ratios, and screening-validity 'warnings'.
    """
    t = np.asarray(t, float); rho = np.asarray(rho, float); V = np.asarray(V, float)
    alt = np.asarray(alt, float); rng = np.asarray(rng, float)
    eps = max(float(emissivity), 1e-3)

    q_conv = _stag_flux(rho, V, nose_radius_m)              # convective (Sutton-Graves)
    # Radiative gas heating (Tauber-Sutton 1991) — exactly zero below 9 km/s,
    # so the sub-9 km/s fleet (RVs ~7, HGVs ~5-6 km/s) is untouched.
    if include_radiative:
        q_rad, _rad_info = radiative_flux(rho, V, nose_radius_m)
    else:
        q_rad = np.zeros_like(q_conv)
        _rad_info = {"q_rad_peak_MW_m2": 0.0, "valid": True,
                     "note": "radiative term disabled by caller"}
    q_surf = q_conv + q_rad                                 # total surface flux
    T_eq = (q_surf / (SIGMA * eps)) ** 0.25
    ipk = int(np.argmax(q_surf)) if q_surf.size else 0
    q_peak = float(q_surf[ipk]) if q_surf.size else 0.0
    T_peak = float(T_eq[ipk]) if q_surf.size else 0.0
    Q_area = (float(np.sum(0.5 * (q_surf[1:] + q_surf[:-1]) * np.diff(t)))
              if q_surf.size > 1 else 0.0)

    _duration_s = float(t[-1] - t[0]) if np.asarray(t).size > 1 else 0.0
    out = {
        "q_peak_MW_m2": q_peak / 1e6,
        "T_eq_peak_K": T_peak,
        "integrated_load_MJ_m2": Q_area / 1e6,
        "duration_s": _duration_s,       # reentry/glide-arc span (feeds the TPS ladder)
        "benchmark": _nearest_benchmark(q_peak / 1e6, "q_MW"),
        "benchmark_load": _nearest_benchmark(Q_area / 1e6, "Q_MJ"),
        "material": material,
        "q_rad_peak_MW_m2": _rad_info["q_rad_peak_MW_m2"],
        "radiative": _rad_info,
        "criteria": {},
        "compromise": None,
        "verdict": "",
    }

    # Validity guards — this is a screening indicator, NOT a through-wall TPS
    # response model; the labels below keep callers from over-reading it.
    out["warnings"] = [
        "Screening model: nose-stagnation Sutton-Graves convective flux + "
        "radiative-equilibrium wall temperature.  No ablation/recession/pyrolysis, "
        "backface conduction, or off-stagnation (shoulder/leading-edge/acreage) "
        "heating.  Verdicts are screening flags, not TPS-survival guarantees.",
        "q_peak is a NOSE-STAGNATION reference flux, not the heat over the whole "
        "vehicle.",
        "Benchmark ratios are single-scalar (flux or load) matches; entry regime, "
        "heating location (stagnation/acreage/leading-edge), beta, lift and TPS "
        "type are not matched.",
    ]
    _Vmax = float(np.max(V)) if V.size else 0.0
    _qr_pk = float(_rad_info["q_rad_peak_MW_m2"])
    if _qr_pk > 0.0:
        _frac = _qr_pk / max(q_peak / 1e6, 1e-9)
        out["warnings"].append(
            f"Radiative gas heating COMPUTED and included: peak "
            f"{_qr_pk:.2f} MW/m² ({_frac:.0%} of the total surface flux) — "
            f"Tauber-Sutton 1991 equilibrium correlation.  "
            f"{_rad_info['note']}.  Equilibrium + cold-wall: an UPPER BOUND "
            f"for small or high-altitude bodies (nonequilibrium and optically "
            f"thin shock layers radiate less).")
    elif _Vmax > 9000.0 and not include_radiative:
        out["warnings"].append(
            f"Radiative gas heating suppressed by the caller (peak V "
            f"{_Vmax/1000:.1f} km/s) — convective-only figure.")

    mat = TPS_MATERIALS.get(material)
    is_ablator = bool(mat and mat.get("is_ablator"))

    # NOTHING_SURVIVES guard applies to RERADIATIVE surfaces (and the no-material
    # case): a non-ablating wall above ~4000 K is beyond the no-ablation
    # equilibrium model.  An ABLATOR is *supposed* to sit above it — it survives
    # by receding at its ablation temperature, not by staying below a surface
    # limit — so ablators skip this guard and are judged by RECESSION below.
    if not is_ablator and T_peak >= NOTHING_SURVIVES_K:
        out["verdict"] = (f"outside no-ablation model validity (peak T_eq ≈ {T_peak:.0f} K "
                          f"≥ {NOTHING_SURVIVES_K:.0f} K) — requires ablation/material-response analysis")
        return out

    if not mat:
        out["verdict"] = ("physical numbers only — set the RV's tps_material "
                          "for a screening verdict")
        return out

    crossings = []   # (index, mode label)
    dt = np.diff(t, prepend=t[0])

    if is_ablator:
        # === ABLATOR: heat-load vs demonstrated flight record + bounded tripwire.
        # An ablator does NOT fail by exceeding a surface temperature — it
        # ablates AT its surface temperature and carries the heat away.  A
        # point-estimate of recession depth is NOT reported as a verdict: the
        # effective heat of ablation H_eff varies ~5× with flight regime, so
        # δ = ∫q̇dt/(ρ·H_eff) inherits that spread while looking precise (this
        # is what over-flagged the Mk21 at δ/R_n ≈ 0.4; see METHODS §13.6).
        # Instead:
        #   (a) the flown ablating heat LOAD is compared against the material
        #       family's demonstrated flight record (like the UHTC dwell floor);
        #   (b) burn-through is a BOUND — red fires only if the shield is
        #       consumed even at the most OPTIMISTIC cited H_eff;
        #   (c) δ is reported only as a BAND across the cited H_eff range, in
        #       the full analysis, never as a tier-driving point value.
        rho_abl = float(mat.get("density_kg_m3") or 0.0)
        T_onset = float(mat["continuous_K"])                   # ablation/oxidation onset
        depth = (float(recession_depth_m) if recession_depth_m and recession_depth_m > 0
                 else float(nose_radius_m))
        H_nom = float(mat.get("H_eff_MJ_kg") or 0.0) * 1e6     # J/kg (nominal, conservative-low)
        H_bnd = float(mat.get("H_eff_bound_MJ_kg") or mat.get("H_eff_MJ_kg") or 0.0) * 1e6  # optimistic
        out["criteria"]["peak_surface"] = {
            "margin": T_peak / mat["peak_K"], "limit_K": mat["peak_K"],
            "T_eq_peak_K": T_peak,
            "note": "informational for an ablator — it ablates at its surface "
                    "temperature; exceeding T_eq is expected, not a failure"}
        # Ablating heat load: the incident load accrued while the surface is at
        # or above its ablation onset.
        #
        # BASIS: the integrand is the CONVECTIVE flux, not the total.  Every
        # demonstrated-load record and every H_eff in the catalog was derived
        # on a convective basis, and our own Stardust reconstruction closes at
        # 1.00x of its record on that basis.  Folding in the Tauber-Sutton
        # equilibrium radiative term — which over-predicts several-fold for
        # small, high-altitude capsules (test_radiative.py) — pushed the
        # recovered Stardust capsule to 1.26x its OWN record, i.e. a false
        # "beyond the flight record" verdict.  Radiative heating still raises
        # T_eq (the ablation-onset gate just below) and the reported peak
        # flux, and is disclosed in the warnings; it does not enter the
        # record ladder or the burn-through bound.
        q_recess = np.where(T_eq >= T_onset, q_conv, 0.0)
        Q_ablating = float(np.sum(q_recess * dt))              # J/m²
        record = mat.get("demonstrated_load_MJ_m2")
        record_J = (float(record) * 1e6) if record else None
        crit = {
            "load_MJ_m2": Q_ablating / 1e6,
            "demonstrated_load_MJ_m2": record,
            "load_fraction": (Q_ablating / record_J) if record_J else None,
            "demonstrated_load_source": mat.get("demonstrated_load_source", ""),
            "depth_m": depth, "rho_kg_m3": rho_abl,
            "H_eff_nominal_MJ_kg": mat.get("H_eff_MJ_kg"),
            "H_eff_bound_MJ_kg": mat.get("H_eff_bound_MJ_kg") or mat.get("H_eff_MJ_kg"),
        }
        # δ band across the cited H_eff range (context only, full-analysis text).
        if rho_abl > 0 and H_nom > 0 and depth > 0:
            crit["delta_nominal_cm"] = 100.0 * Q_ablating / (rho_abl * H_nom)
            crit["delta_optimistic_cm"] = 100.0 * Q_ablating / (rho_abl * H_bnd)
            crit["basis"] = (
                "load compared to the demonstrated flight record; δ shown as a "
                "band across the cited H_eff range (optimistic..nominal); "
                "burn-through is a bound at the optimistic H_eff, not a "
                "point-estimate of recession")
            # Bounded tripwire: burn-through only if consumed at the OPTIMISTIC H_eff.
            delta_opt_final = Q_ablating / (rho_abl * H_bnd)
            crit["burnthrough_bound"] = bool(delta_opt_final >= depth)
            if delta_opt_final >= depth:
                delta_opt_cum = np.cumsum(q_recess * dt) / (rho_abl * H_bnd)
                bt = np.where(delta_opt_cum >= depth)[0]
                if bt.size:
                    crossings.append((int(bt[0]),
                                      "burn-through bound — shield consumed even "
                                      "at the most optimistic cited H_eff"))
        else:
            out["warnings"].append(
                "Ablator load/bound not fully evaluated (missing H_eff / density "
                "/ depth) — physical numbers only for this location.")
        out["criteria"]["recession"] = crit
    else:
        # === RERADIATIVE / non-ablating: the existing screen (unchanged) ===
        # 1. Peak surface temperature vs short-duration limit
        out["criteria"]["peak_surface"] = {
            "margin": T_peak / mat["peak_K"], "limit_K": mat["peak_K"],
            "T_eq_peak_K": T_peak}
        ex = np.where(T_eq > mat["peak_K"])[0]
        if ex.size:
            # T_eq is the zero-thermal-mass EQUILIBRIUM wall temperature, so this
            # timestamp is when the flux first EXCEEDS the surface limit — the
            # real (finite-thermal-mass) skin reaches failure seconds to tens of
            # seconds later (τ ≈ ρcδ·ΔT/q̇).  Label accordingly.
            crossings.append((int(ex[0]), "flux above surface melt/ablation limit"))

        # 2. Heat-soak: dwell above the continuous (oxidation) limit.
        #    A material-supplied oxidation_dwell_s is a DEMONSTRATED FLOOR
        #    (SURVIVABILITY_REPORT_DESIGN.md §11.4: within it → inside the
        #    demonstrated envelope; past it → extrapolation, NOT asserted
        #    failure — the report layer renders that distinction).  Materials
        #    without one keep the generic 120-s screening surrogate.
        _mat_dwell = mat.get("oxidation_dwell_s")
        _dwell_lim = float(_mat_dwell) if _mat_dwell else float(soak_dwell_s)
        _is_floor = bool(_mat_dwell)
        above = T_eq > mat["continuous_K"]
        cum_above = np.cumsum(np.where(above, dt, 0.0))
        time_above = float(cum_above[-1]) if cum_above.size else 0.0
        out["criteria"]["soak"] = {
            "margin": time_above / _dwell_lim, "time_above_s": time_above,
            "limit_K": mat["continuous_K"], "dwell_s": _dwell_lim,
            "floor": _is_floor,
            "basis": ("demonstrated oxidation-dwell floor (anchor dataset; "
                      "past it = extrapolation, not asserted failure)"
                      if _is_floor else
                      "empirical dwell-above-continuous-limit damage surrogate "
                      "(not an oxidation-kinetics closure)")}
        js = np.where(cum_above >= _dwell_lim)[0]
        if js.size:
            crossings.append((int(js[0]),
                              "past demonstrated oxidation-dwell floor "
                              "(extrapolation)" if _is_floor
                              else "TPS oxidation soak (glide)"))

        # 3. Lumped heat-sink burn-up (Reynerson): flux above the re-radiation cap
        #    soaks into the body mass; melt when accumulated heat ≥ m·c·(T_melt−T₀).
        if mass_kg > 0 and frontal_area_m2 > 0 and body_radius_m > 0:
            q_body = _stag_flux(rho, V, body_radius_m)
            q_cap = eps * SIGMA * mat["continuous_K"] ** 4          # re-radiation cap
            q_excess = np.maximum(q_body - q_cap, 0.0)
            Q_in = np.cumsum(q_excess * dt) * frontal_area_m2       # J absorbed by mass
            Tm = mat["melt_K"] or mat["continuous_K"]
            Q_melt = mass_kg * mat["c_J_kgK"] * (Tm - _T0)
            out["criteria"]["heat_sink"] = {
                "margin": Q_melt / max(float(Q_in[-1]), 1e-9),
                "Q_absorbed_MJ": float(Q_in[-1]) / 1e6,
                "Q_melt_MJ": Q_melt / 1e6, "melt_K": Tm}
            jh = np.where(Q_in >= Q_melt)[0]
            if jh.size:
                crossings.append((int(jh[0]), "bare-body melt (heat sink)"))

    out["is_ablator"] = is_ablator
    if crossings:
        ci, mode = min(crossings, key=lambda c: c[0])
        out["compromise"] = {
            "t_s": float(t[ci]), "alt_km": float(alt[ci]) / 1000.0,
            "range_km": float(rng[ci]) / 1000.0, "V_kms": float(V[ci]) / 1000.0,
            "mode": mode}
        out["verdict"] = (f"COMPROMISED — {mode} at t={t[ci]:.0f}s, "
                          f"{alt[ci]/1000:.0f} km, {V[ci]/1000:.1f} km/s "
                          f"({mat['label']})")
    elif is_ablator and "recession" in out["criteria"]:
        # survives by ablation: state the load vs the flight record (no
        # point-estimate of recession — δ is a band in the criteria dict).
        rc = out["criteria"]["recession"]
        _Q = rc.get("load_MJ_m2", 0.0)
        _frac = rc.get("load_fraction")
        if _frac is not None:
            out["verdict"] = (f"no screened burn-through ({mat['label']}); "
                              f"ablating load {_Q:,.0f} MJ/m² = {_frac:.0%} of "
                              f"the demonstrated flight record")
        else:
            out["verdict"] = (f"no screened burn-through ({mat['label']}); "
                              f"ablating load {_Q:,.0f} MJ/m² "
                              f"(no cited flight-load record for this family)")
    else:
        out["verdict"] = f"no screened thermal failure ({mat['label']})"
    return out


# ---------------------------------------------------------------------------
# Two-location screening verdict (HEATING_MODEL_CROSSCHECK.md §11, lean Phase 2)
# ---------------------------------------------------------------------------
# Acreage flux fraction: windward cone-flank/tail heating as a fraction of the
# nose stagnation flux.  Screening constant: Lu/Shi & Zhang 2024 give a
# cone-tail/stagnation ratio ≈ 0.13 (engineering distribution validated vs
# NASA TN D-5450 to <9%); the STS-1 windward-acreage-vs-RCC-stagnation ratio
# (~0.1) is consistent.  One number, flagged — not a heating distribution.
#
# DOMAIN — this is a CONE number.  Cones and flat-bottom lifting bodies
# (body_form "wedge"/"half_cone") carry their windward acreage by DIFFERENT
# physics: a cone flank wraps the flow and heats near 0.13× of stagnation,
# whereas a flat lower surface at incidence is a flat-plate boundary layer that
# runs ~7× cooler relative to its blunt-scale stagnation.  The Candler & Leyva
# 2022 CFD anchor (generic HGV, 6 km/s glide) implies an effective fraction
# ≈0.018 for the flat case — see METHODS §13.8 and
# test_candler_windward_anchor.py.  0.13 is kept for its VALIDATED CONE DOMAIN;
# applying it to a flat-bottom form OVER-predicts (conservative / screening-
# safe, but imprecise).  Do NOT lower 0.13 to fit the flat case — that would
# corrupt the cone domain to match the wedge (a compensating error).  The
# correct fix is a body_form-aware fraction (below), not a retune of this
# constant.
BODY_FLUX_FRACTION = 0.13

# FLAT-BOTTOM lifting bodies (body_form "wedge" / "half_cone", flat side
# windward): the windward acreage is a flat-plate boundary layer, ~7× cooler
# relative to its blunt-scale stagnation than a cone flank.  0.018 is the
# value implied by the Candler & Leyva 2022 CFD of a generic HGV at its glide
# point (6 km/s, 49.7 km, α=14°, laminar: windward plateau ≈1175 K) —
# a SINGLE-POINT anchor, stated as such, against flight-validated CFD (their
# code is within ~100 K of Shuttle thermocouples).  See METHODS §13.8 and
# test_candler_windward_anchor.py.  windward_flank_flux() selects between
# the two by body_form; the cone value above is untouched (its own domain).
BODY_FLUX_FRACTION_FLAT = 0.018

# --- Windward-flank heating band (glide AoA probe) ---------------------------
# The α=0 acreage flux above times a windward amplification A(α)=sin(δ+α)/sin(δ):
# the modified-Newtonian surface-pressure ratio Cp ∝ sin²θ fed through the
# reference-enthalpy laminar scaling q̇ ∝ √ρ_e ∝ √p_e (Eckert/Hung C_h ∝ Re*^−½,
# HEATING_MODEL_CROSSCHECK.md reference-enthalpy section).  CP_MAX cancels in the
# ratio, so A(α) is purely geometric.  The METHOD FAMILY (Van Driest St∝1/√Re
# laminar + Eckert-Tewfik reference enthalpy) and the windward-vs-leeward
# ORDERING it reproduces are CITED (AGARD-R-754 Kapp/Mathauer/Rieger 1988,
# validated on the Tracy M=7.95 cone at α=12°/24°); the closed-form sin-ratio
# reduction itself is an INFERENCE (BENCHMARKING.md "Windward/AoA heating
# probe").  ρ_e∝p_e holds edge temperature fixed, so behind the stronger
# windward shock the true ρ_e ratio is below the p_e ratio — the sin-ratio
# mildly OVER-predicts (conservative for a screen).
_WINDWARD_ALPHA_BAND  = (5.0, 20.0)   # deg; ends coincide with Thompson 1989's cited error anchors
_WINDWARD_DELTA_FLOOR = 5.0           # deg; numerical guard — A(α) diverges as δ→0 (RV forebodies are 5–15° cones)
# Gate: keep windward heating as a CONTEXT overlay by default (does not change
# any shipped verdict).  Flip to True to let it downgrade survive→degraded /
# flag needs-analysis.  Screening cannot place the transition or fin-gap
# reattachment line, so it never asserts a hard fail even when True.
WINDWARD_DRIVES_VERDICT = False

# --- Boundary-layer transition gate (METHODS §13.11) -------------------------
# The acreage/flank boundary layer trips laminar→turbulent as the vehicle
# descends into denser air.  Placed IN THE TRAJECTORY (when), not on the body
# (where) — a screening gate on the freestream Reynolds number based on nose
# radius, Re_Rn = ρ·V·R_n/μ.  Calibrated + verified against Kuntz 1999
# (AIAA 99-3460) Table 1, the IRV-2 CFD case: laminar at Re_Rn 1.7e6 (13.96 km),
# transition first appears at 2.1e6 (12.7 km), fully turbulent by 3.9e6
# (5.5 km).  The SPATIAL criterion (local Re_x) is NOT single-valued in that
# data — ~1e7 on the cone vs ~1e6 at the sphere-cone juncture — which is why a
# screening gate uses the nose-radius Reynolds onset, the classic nosetip-
# transition scaling (PANT lineage), not an on-body placement.  Feeds the
# windward-flank and bondline ACREAGE flux; the nose stagnation point is always
# laminar and is untouched.  thresholds.apply() drives the two Re thresholds.
RE_RN_TRANSITION_ONSET = 2.0e6     # Re_Rn at which acreage transition begins
RE_RN_FULLY_TURBULENT  = 3.5e6     # Re_Rn at which the acreage is fully turbulent
# Both calibrated to Kuntz 1999 Table 1 (IRV-2, R_n 1.905 cm): onset brackets
# pt15 laminar (Re_Rn 1.72e6) / pt16 transitional (2.07e6); fully-turbulent
# brackets pt19 transitional (3.32e6) / pt20 turbulent (3.89e6).
# Turbulent-to-laminar acreage flux ratio, clamped to the cited 3–5× band
# (turbulent flank runs 3–5× the laminar value; T_eq ~1.3–1.5×).  Computed
# within the band from how far past onset the flow is (St_lam∝Re^−½,
# St_turb∝Re^−⅕ → the ratio grows with Re).
_TURB_FLUX_RATIO_LO = 3.0
_TURB_FLUX_RATIO_HI = 5.0


def _sutherland_mu(T_K):
    """Dynamic viscosity of air, Sutherland's law (Pa·s)."""
    T = np.asarray(T_K, float)
    return 1.716e-5 * (T / 273.15) ** 1.5 * (273.15 + 110.4) / (T + 110.4)


def transition_factor(rho, V, alt, nose_radius_m, *,
                      onset=None, fully=None):
    """Acreage boundary-layer transition gate → a per-sample turbulent flux
    multiplier for the flank/acreage heating (1.0 = laminar).

    Re_Rn = ρ·V·R_n/μ(T_∞); laminar below `onset`, ramping to the turbulent
    flux ratio by `fully`.  Returns (factor_array, Re_Rn_array, state) where
    state ∈ 'laminar' | 'transitional' | 'turbulent' over the arc, plus the
    peak Re_Rn.  Resolves the two Re thresholds from the module attrs at call
    time so thresholds.apply() drives them.
    """
    onset = RE_RN_TRANSITION_ONSET if onset is None else float(onset)
    fully = RE_RN_FULLY_TURBULENT if fully is None else float(fully)
    fully = max(fully, onset * 1.0001)
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    Rn = float(nose_radius_m or 0.0)
    if Rn <= 0.0:
        z = np.zeros(np.broadcast(rho, V).shape)
        return (np.ones_like(z) if z.shape else 1.0), z, "laminar"
    import atmosphere as _atm
    T = np.asarray(_atm.atmosphere(np.asarray(alt, float))[0], float)
    Re_Rn = rho * V * Rn / _sutherland_mu(T)
    # transitional fraction 0→1 across [onset, fully]
    frac = np.clip((Re_Rn - onset) / (fully - onset), 0.0, 1.0)
    # turbulent flux ratio within the cited band, growing with Re past `fully`
    over = np.clip(np.log(np.maximum(Re_Rn, 1.0) / fully) / np.log(3.0), 0.0, 1.0)
    ratio = _TURB_FLUX_RATIO_LO + over * (_TURB_FLUX_RATIO_HI - _TURB_FLUX_RATIO_LO)
    factor = 1.0 + frac * (ratio - 1.0)
    peak = float(np.max(Re_Rn)) if Re_Rn.size else 0.0
    state = ("turbulent" if peak >= fully else
             "transitional" if peak >= onset else "laminar")
    return factor, Re_Rn, state


# --- Stagnation-point RADIATIVE gas heating (METHODS §13.13) --------------
# Tauber & Sutton 1991, "Stagnation-Point Radiative Heating Relations for
# Earth and Mars Entries", J. Spacecraft & Rockets 28(1):40-42 (read from
# primary; PDF in data/).  Earth/air equilibrium correlation, Eqs. (1)-(2):
#
#     q_r = C · r_n^a · rho^b · f_E(V)          [W/cm^2]
#     C = 4.736e4,  b = 1.22
#     a = 1.072e6 · V^-1.88 · rho^-0.325   (capped, see below)
#
# f_E(V) is the paper's Table 1, linear interpolation, defined 9-16 km/s.
# BELOW 9 km/s the correlation is not defined and radiative heating is
# negligible — the function returns exactly ZERO there, so every ICBM-RV
# (~7 km/s) and HGV (~5-6 km/s) case in Thrusty's fleet is untouched.
#
# EPISTEMIC STATUS: this is an EQUILIBRIUM, cold-wall correlation built for
# blunt bodies (r_n 0.3-3 m).  For small, fast, high-altitude probes it runs
# CONSERVATIVE-HIGH: the flow is chemically nonequilibrium and the shock
# layer is optically thin, both of which reduce real radiation.  Verified
# against Stardust in test_radiative.py — the correlation over-predicts the
# flight-derived radiative fraction (~9% of peak, Kontinos & Stackpoole
# AIAA 2008-1197) by several fold at r_n 0.23 m.  It is therefore used as an
# UPPER BOUND, and the validity flags say when it is being extrapolated.
_TS_C   = 4.736e4        # W/cm^2 (air)
_TS_B   = 1.22
_TS_VMIN = 9000.0        # m/s — f_E table floor; below this q_rad := 0
# Paper Table 1: f_E(V), V in m/s
_TS_FE_V = np.array([9000., 9250., 9500., 9750., 10000., 10250., 10500.,
                     10750., 11000., 11500., 12000., 12500., 13000., 13500.,
                     14000., 14500., 15000., 15500., 16000.])
_TS_FE_F = np.array([1.5, 4.3, 9.7, 19.5, 35., 55., 81., 115., 151., 238.,
                     359., 495., 660., 850., 1065., 1313., 1550., 1780., 2040.])
# Stated validity envelope of Eqs. (1)-(2) (paper, p. 41)
_TS_VALID_V   = (10000.0, 16000.0)        # m/s
_TS_VALID_RHO = (6.66e-5, 6.31e-4)        # kg/m^3  (~72-54 km)
_TS_VALID_RN  = (0.3, 3.0)                # m


def radiative_flux(rho, V, nose_radius_m):
    """Stagnation-point RADIATIVE gas heating, Tauber-Sutton 1991 (Earth/air).

    Returns (q_rad_W_m2, info) where info carries the peak, the validity
    verdict, and the reason when the correlation is extrapolated.  Exactly
    zero below 9 km/s (correlation floor; radiative heating is negligible
    there), so sub-9 km/s cases are numerically untouched.

    Equilibrium + cold-wall: an UPPER BOUND for small/high-altitude bodies
    (see the module comment and test_radiative.py's Stardust check).
    """
    rho = np.asarray(rho, float)
    V = np.asarray(V, float)
    r_n = float(nose_radius_m or 0.0)
    zero = np.zeros(np.broadcast(rho, V).shape)
    if r_n <= 0.0:
        return zero, {"q_rad_peak_MW_m2": 0.0, "valid": True,
                      "note": "no nose radius — radiative not evaluated"}

    hot = (V >= _TS_VMIN) & (rho > 0.0)
    q = np.zeros_like(zero)
    if np.any(hot):
        _V = V[hot]
        _rho = rho[hot]
        a = 1.072e6 * _V ** (-1.88) * _rho ** (-0.325)
        a = np.minimum(a, 1.0)                      # paper: a <= 1 always
        if 1.0 <= r_n <= 2.0:
            a = np.minimum(a, 0.6)
        elif 2.0 < r_n <= 3.0:
            a = np.minimum(a, 0.5)
        f_E = np.interp(_V, _TS_FE_V, _TS_FE_F,
                        left=0.0, right=_TS_FE_F[-1])
        q[hot] = _TS_C * (r_n ** a) * (_rho ** _TS_B) * f_E * 1.0e4  # -> W/m^2

    peak = float(np.max(q)) if q.size else 0.0
    # Validity: judged at the peak-radiative sample (where it matters).
    reasons = []
    if peak > 0.0:
        i = int(np.argmax(q))
        _v, _r = float(V[i]), float(rho[i])
        if not (_TS_VALID_V[0] <= _v <= _TS_VALID_V[1]):
            reasons.append(f"V {_v/1000:.1f} km/s outside 10-16 km/s")
        if not (_TS_VALID_RHO[0] <= _r <= _TS_VALID_RHO[1]):
            reasons.append(f"rho {_r:.2e} outside {_TS_VALID_RHO[0]:.2e}-"
                           f"{_TS_VALID_RHO[1]:.2e} kg/m^3")
        if not (_TS_VALID_RN[0] <= r_n <= _TS_VALID_RN[1]):
            reasons.append(f"R_n {r_n:.2f} m outside {_TS_VALID_RN[0]}-"
                           f"{_TS_VALID_RN[1]} m")
    info = {"q_rad_peak_MW_m2": peak / 1e6,
            "valid": not reasons,
            "note": ("within the correlation's stated envelope" if not reasons
                     else "EXTRAPOLATED — " + "; ".join(reasons))}
    return q, info


# --- Interior (bondline) screen (METHODS §13.10) -----------------------------
# TPS-structure bondline design limit: the ablative-TPS sizing criterion the
# industry iterates shield thickness against (Dec & Braun, NTRS 20060004824 —
# their tool holds bondline ≤ 250 °C; Orion used 260 °C, NTRS 20080013535).
# Crossing it maps to BEYOND DESIGN ENVELOPE (yellow) — a design limit, not a
# demonstrated-death bound — never red.  thresholds.apply() drives this.
BONDLINE_LIMIT_C = 250.0


def _layer_props(material):
    """(material dict, k(T), c(T), notes) for one layer, or (None, reason)."""
    mat = TPS_MATERIALS.get(str(material or ""))
    if not mat:
        return None, "material/thickness unset"
    k0 = float(mat.get("k_W_mK") or 0.0)
    if k0 <= 0.0:
        return None, "no cited through-thickness conductivity for this material"
    rho = float(mat.get("density_kg_m3") or 0.0)
    c0 = float(mat.get("c_J_kgK") or 0.0)
    if rho <= 0 or c0 <= 0:
        return None, "material density/heat capacity unset"
    notes, rng = [], {}
    kc = material_curve(material, "k")
    cc = material_curve(material, "c")
    if kc:
        k_of = (lambda T, _c=kc: np.interp(T, _c[0], _c[1]))
        notes.append(f"k from the {kc[2]}")
        rng["k"] = (float(kc[0][0]), float(kc[0][-1]))
    else:
        k_of = (lambda T, _k=k0: np.full_like(T, _k))
        notes.append(f"k = {k0:g} W/m·K, one value"
                     + (f" — {mat['k_source']}" if mat.get("k_source") else ""))
    if cc:
        c_of = (lambda T, _c=cc: np.interp(T, _c[0], _c[1]))
        notes.append(f"c from the {cc[2]}")
        rng["c"] = (float(cc[0][0]), float(cc[0][-1]))
    else:
        c_of = (lambda T, _c=c0: np.full_like(T, _c))
        notes.append(f"c = {c0:g} J/kg·K, one value")
    return dict(mat=mat, rho=rho, k=k_of, c=c_of, notes=notes, range=rng,
                label=mat.get("label") or str(material)), None


def layered_conduction(t, q_w, layers, *, emissivity=0.85, T0_K=300.0,
                       n_per_layer=24, dt_max_s=1.0):
    """One-dimensional transient conduction through a stack of layers.

    layers: [(material key, thickness_m), ...] from the outer surface in.
    The outer face takes the absorbed flux and radiates (εq̇ − εσT⁴,
    linearised about the previous step); the innermost face is insulated,
    so nothing leaves the stack and every inner temperature is an upper
    bound.  Layers touch perfectly (no contact resistance, the cautious
    side).  k and c follow each material's TPSX curve where the catalog
    names one (material_curve; held at the table's end value outside it),
    else the catalog's single value; density is constant.  Finite volumes,
    implicit in temperature, properties taken at the start of each substep.

    Returns dict(evaluated, faces, T_faces (n_faces × len(t), K),
    T_surf_peak_K, warnings, notes) where face 0 is the outer surface,
    face i the joint behind layer i, and the last face the innermost; or
    dict(evaluated=False, reason=...)."""
    t = np.asarray(t, float); q_w = np.asarray(q_w, float)
    props = []
    for mat, th in layers:
        if not th or th <= 0.0:
            return dict(evaluated=False, reason="material/thickness unset")
        pr, why = _layer_props(mat)
        if pr is None:
            return dict(evaluated=False, reason=why, material=mat)
        props.append((pr, float(th)))
    if not props or t.size < 2:
        return dict(evaluated=False, reason="material/thickness unset")
    eps = max(float(emissivity or 0.85), 1e-3)

    n = int(n_per_layer)
    lay = np.repeat(np.arange(len(props)), n)            # layer of each cell
    dx = np.concatenate([np.full(n, th / n) for _, th in props])
    rho = np.concatenate([np.full(n, pr['rho']) for pr, _ in props])
    N = dx.size
    T = np.full(N, float(T0_K))
    T_hi = np.full(len(props), float(T0_K))               # hottest per layer

    def kc(Tc):
        k = np.empty(N); c = np.empty(N)
        for li, (pr, _) in enumerate(props):
            sl = slice(li * n, (li + 1) * n)
            k[sl] = pr['k'](Tc[sl]); c[sl] = pr['c'](Tc[sl])
        return k, c

    def faces(Tc, k):
        out = [Tc[0]]
        for li in range(1, len(props)):
            a, b = li * n - 1, li * n
            Ga, Gb = 2.0 * k[a] / dx[a], 2.0 * k[b] / dx[b]
            out.append((Ga * Tc[a] + Gb * Tc[b]) / (Ga + Gb))
        out.append(Tc[-1])
        return out

    k, c = kc(T)
    hist = np.empty((len(props) + 1, t.size))
    hist[:, 0] = faces(T, k)
    for i in range(1, t.size):
        dt_seg = float(t[i] - t[i - 1])
        if dt_seg > 0:
            nsub = max(1, int(np.ceil(dt_seg / dt_max_s)))
            dt = dt_seg / nsub
            for j_ in range(nsub):
                frac = (j_ + 0.5) / nsub
                q_now = q_w[i - 1] + frac * (q_w[i] - q_w[i - 1])
                k, c = kc(T)
                C = rho * c * dx / dt                    # J/m²K per step
                G = 1.0 / (dx[:-1] / (2 * k[:-1]) + dx[1:] / (2 * k[1:]))
                Ts = T[0]
                a = np.zeros(N); cu = np.zeros(N)
                a[1:] = -G; cu[:-1] = -G
                b = C.copy()
                b[:-1] += G; b[1:] += G
                b[0] += 4.0 * eps * SIGMA * Ts ** 3
                d = C * T
                d[0] += eps * q_now + 3.0 * eps * SIGMA * Ts ** 4
                for m in range(1, N):                    # Thomas algorithm
                    w = a[m] / b[m - 1]
                    b[m] -= w * cu[m - 1]
                    d[m] -= w * d[m - 1]
                T[-1] = d[-1] / b[-1]
                for m in range(N - 2, -1, -1):
                    T[m] = (d[m] - cu[m] * T[m + 1]) / b[m]
                for li in range(len(props)):
                    T_hi[li] = max(T_hi[li], float(T[li * n:(li + 1) * n].max()))
        hist[:, i] = faces(T, k)

    warnings, notes = [], []
    for li, (pr, th) in enumerate(props):
        notes.append(f"{pr['label']} ({th * 100:.1f} cm): "
                     + "; ".join(pr['notes']))
        for which, (lo, hi) in pr['range'].items():
            if T_hi[li] > hi:
                warnings.append(
                    f"{pr['label']} reaches {T_hi[li]:,.0f} K, past the end "
                    f"of its TPSX {which} table ({hi:,.0f} K): held at the "
                    f"last tabulated value.")
    names = (["outer surface"]
             + [f"behind {pr['label']}" for pr, _ in props])
    return dict(evaluated=True, faces=names, T_faces=hist,
                T_surf_peak_K=float(hist[0].max()),
                layer_peak_K=[float(x) for x in T_hi],
                warnings=warnings, notes=notes)


def bondline_screen(t, q_w, *, material, thickness_m, emissivity=0.85,
                    T0_K=300.0, limit_C=None, n_nodes=24, dt_max_s=1.0):
    """Screening 1-D transient conduction through the body TPS layer → does
    the structure behind it (the bondline) stay below the design limit?

    Dec & Braun's (NTRS 20060004824) "approximate option," further simplified
    to screening tier: implicit finite-difference conduction (k and c from the
    TPSX curves where the catalog names one, else constant; ρ constant), a surface energy balance q̇_net = α·q̇ − εσT_s⁴ (radiation
    linearized about the previous step), and an insulated back face (their
    worst case).  Deliberate omissions, direction labeled:
      + no pyrolysis-gas energy absorption (Dec & Braun quantify this as
        ~11% conservative on required insulation);
      + no ablation heat consumption at the surface (inert wall runs hotter);
      + carbon-phenolic k is the CHAR value (conservative-high);
      − no recession thinning of the layer (warned when the body δ estimate
        is a meaningful fraction of the thickness — caller's judgement).
    Verdict mapping is the CALLER's job; this returns physics + a crossing.

    Returns dict(evaluated, T_bond_peak_K/C, T_surf_peak_K, t_cross_s,
    crossed, margin, limit_C, k_W_mK, thickness_m, warnings, basis).
    """
    if limit_C is None:
        limit_C = BONDLINE_LIMIT_C           # resolve live (thresholds.apply)
    mat = TPS_MATERIALS.get(str(material or ""))
    if not mat or not thickness_m or thickness_m <= 0.0:
        return dict(evaluated=False, reason=(
            "no cited through-thickness conductivity for this material"
            if mat and not mat.get("k_W_mK") else "material/thickness unset"))
    t = np.asarray(t, float)
    res = layered_conduction(t, q_w, [(material, float(thickness_m))],
                             emissivity=emissivity, T0_K=T0_K,
                             n_per_layer=n_nodes, dt_max_s=dt_max_s)
    if not res.get("evaluated"):
        return dict(evaluated=False, reason=res.get("reason", ""))
    back = res["T_faces"][-1]
    limit_K = float(limit_C) + 273.15
    over = np.nonzero(back >= limit_K)[0]
    t_cross = float(t[over[0]]) if over.size else None
    T_bond_pk = float(back.max())
    T_surf_pk = res["T_surf_peak_K"]

    warnings = [
        "Inert-wall screening conduction (Dec & Braun approximate option, "
        "sans pyrolysis/decomposition): no pyrolysis-gas energy absorption "
        "(~11% conservative on insulation per NTRS 20060004824), no ablation "
        "heat consumption at the surface, no recession thinning of the layer.",
    ] + [n_ + "." for n_ in res["notes"]] + res["warnings"]
    if T_surf_pk > float(mat.get("peak_K") or 1e9):
        warnings.append(
            "Surface modeled inert past its ablation temperature — bondline "
            "estimate runs conservative-high in this regime.")

    return dict(
        evaluated=True, T_bond_peak_K=T_bond_pk,
        T_bond_peak_C=T_bond_pk - 273.15, T_surf_peak_K=T_surf_pk,
        limit_C=float(limit_C), margin=(T_bond_pk - 273.15) / float(limit_C),
        crossed=bool(t_cross is not None), t_cross_s=t_cross,
        k_W_mK=float(mat.get("k_W_mK") or 0.0), thickness_m=float(thickness_m),
        basis=("1-D implicit FD conduction, insulated back face, radiative "
               "surface balance — bondline vs the ablative-TPS sizing "
               "criterion (Dec & Braun NTRS 20060004824)"),
        warnings=warnings)


def _severity(res):
    """Rank a single-location FOM result for binding-location selection
    (higher = closer to / past failure; ≥1 means a criterion is exceeded).
    -inf = no material set (no verdict to bind on)."""
    if not res or not res.get("material"):
        return float("-inf")
    crit = res.get("criteria") or {}
    # Ablator: severity is the flown load vs the demonstrated flight record
    # (≥1 = past the record); the burn-through bound outranks everything (a
    # consumed shield is the true failure).  T_eq / peak_surface are
    # informational — an ablator is meant to run hot and recede.
    if res.get("is_ablator") and "recession" in crit:
        rc = crit["recession"]
        if rc.get("burnthrough_bound"):
            return float("inf")
        lf = rc.get("load_fraction")
        return float(lf) if lf is not None else 0.0
    # Reradiative: outside-validity is worst, else the worst criterion margin.
    if res.get("T_eq_peak_K", 0.0) >= NOTHING_SURVIVES_K:
        return float("inf")
    worst = float("-inf")
    if "peak_surface" in crit:
        worst = max(worst, crit["peak_surface"]["margin"])
    if "soak" in crit:
        worst = max(worst, crit["soak"]["margin"])
    if "heat_sink" in crit:
        m = crit["heat_sink"]["margin"]
        worst = max(worst, (1.0 / m) if m > 0 else float("inf"))
    return worst


def acreage_flux(t, rho, V, alt, *, nose_radius_m, body_radius_m,
                 body_flux_fraction=None):
    """Heat flux on the body acreage over an arc, the one heating_fom_per_
    location uses for the body and the interior: a screening fraction of the
    BODY-scale stagnation flux, turbulent-augmented at low altitude by the
    transition gate (§13.11).

    Returns (q_W_m2 array, transition_state, peak transition factor)."""
    if body_flux_fraction is None:
        body_flux_fraction = BODY_FLUX_FRACTION
    f = min(max(float(body_flux_fraction), 1e-3), 1.0)
    r_ref = body_radius_m if body_radius_m and body_radius_m > 0.0 \
        else nose_radius_m
    r_t = nose_radius_m if nose_radius_m and nose_radius_m > 0.0 else r_ref
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    tf, _, state = transition_factor(rho, V, alt, r_t)
    return f * _stag_flux(rho, V, r_ref) * tf, state, float(np.max(tf))


def heating_fom_per_location(t, rho, V, alt, rng, *, nose_radius_m=0.05,
                             body_radius_m=0.0, emissivity=0.85,
                             nose_material="", body_material="",
                             mass_kg=0.0, frontal_area_m2=0.0,
                             soak_dwell_s=120.0, nose_solid_depth_m=0.0,
                             body_thickness_m=0.0,
                             body_flux_fraction=None):
    """Two-location screening verdict: the SAME evaluator run at the nose
    (stagnation flux, nose material) and at the body acreage
    (body_flux_fraction × stagnation, body material); the headline verdict is
    the BINDING location — outside-validity first, else earliest compromise,
    else worst margin.

    The acreage call reuses heating_figure_of_merit unchanged by exploiting
    q̇ ∝ 1/√R: a flux fraction f is exactly an effective radius R_ref/f²,
    where R_ref is the BODY radius (flank heating carries no tip-radius term).
    The lumped heat-sink criterion (mass/frontal-area) runs on the body call
    only (it is a whole-body bulk criterion; running it at the nose too would
    double-count).

    Returns the binding location's dict (same top-level keys as
    heating_figure_of_merit, so existing consumers are unchanged) plus:
      binding_location : 'nose' | 'body'
      locations        : {'nose': <full result>, 'body': <full result>}
    and compromise (when present) gains a 'location' key.
    """
    # Recession depth per location (only used if the material is an ablator):
    #   nose  → solid-tip depth (default = nose radius, a conservative screen);
    #   body  → the designed TPS-layer thickness (MUST be passed explicitly —
    #           the body call's inflated effective radius is not a depth).
    nose = heating_figure_of_merit(
        t, rho, V, alt, rng, nose_radius_m=nose_radius_m, body_radius_m=0.0,
        emissivity=emissivity, material=nose_material, mass_kg=0.0,
        frontal_area_m2=0.0, soak_dwell_s=soak_dwell_s,
        recession_depth_m=nose_solid_depth_m)
    if body_flux_fraction is None:      # resolve the live module attr at call time
        body_flux_fraction = BODY_FLUX_FRACTION
    f = min(max(float(body_flux_fraction), 1e-3), 1.0)
    # Acreage reference scale: the flank/acreage boundary layer is set by the
    # BODY scale and contains no tip-radius term — referencing the fraction to
    # the sharp-tip stagnation flux would inflate body heating by
    # sqrt(R_body/R_n) (3.8x for SWERVE's 1.7 cm tip on a 24 cm body).  So the
    # fraction multiplies the body-scale stagnation flux (same reference the
    # heat_sink criterion already uses); sharp tip and blunt capsule then give
    # the same acreage estimate for the same body.
    _R_ref = body_radius_m if body_radius_m > 0.0 else nose_radius_m
    # Body ablator depth: the designed layer thickness, or a 2 cm screening
    # default when the RV does not specify one (flagged in warnings below).
    _body_depth = float(body_thickness_m) if body_thickness_m and body_thickness_m > 0 else 0.02
    body = heating_figure_of_merit(
        t, rho, V, alt, rng, nose_radius_m=_R_ref / f ** 2,
        body_radius_m=body_radius_m, emissivity=emissivity,
        material=body_material, mass_kg=mass_kg,
        frontal_area_m2=frontal_area_m2, soak_dwell_s=soak_dwell_s,
        recession_depth_m=_body_depth)

    # Binding location: validity breach > earlier compromise > worst margin.
    sn, sb = _severity(nose), _severity(body)
    if sn == float("inf") or sb == float("inf"):
        name = "nose" if sn >= sb else "body"
    else:
        nc, bc = nose.get("compromise"), body.get("compromise")
        if nc and bc:
            name = "nose" if nc["t_s"] <= bc["t_s"] else "body"
        elif nc or bc:
            name = "nose" if nc else "body"
        else:
            name = "nose" if sn >= sb else "body"
    binding, other = (nose, body) if name == "nose" else (body, nose)
    other_name = "body" if name == "nose" else "nose"

    # Interior (bondline) screen: 1-D conduction through the body TPS layer,
    # driven by the same acreage flux the body location sees (f × body-scale
    # stagnation).  Evaluates only for an ablative body with a cited k.
    _body_mat = TPS_MATERIALS.get(str(body_material or "")) if body_material else None
    _bl = None
    if _body_mat and _body_mat.get("is_ablator") and _body_mat.get("k_W_mK"):
        # Acreage flux, turbulent-augmented at low altitude (transition gate,
        # §13.11) — a turbulent acreage cooks the interior faster.
        _q_body, _ts_b, _tfpk_b = acreage_flux(
            t, rho, V, alt, nose_radius_m=nose_radius_m,
            body_radius_m=body_radius_m, body_flux_fraction=f)
        _bl = bondline_screen(np.asarray(t, float), _q_body,
                              material=str(body_material), thickness_m=_body_depth,
                              emissivity=emissivity)
        if _bl.get("evaluated"):
            # Carry the gate's state on the result so the report's survival-map
            # regime line can name it on every form (not just Form C).
            _bl["transition_state"] = _ts_b
            _bl["transition_factor_peak"] = _tfpk_b
            if _ts_b != "laminar":
                _bl.setdefault("warnings", []).append(
                    f"Acreage boundary layer {_ts_b} at low altitude — flux "
                    f"turbulent-augmented before conduction (transition gate).")
            if not (body_thickness_m and body_thickness_m > 0):
                _bl.setdefault("warnings", []).append(
                    "Body TPS thickness unset — bondline screened at the 2 cm "
                    "default layer (flagged).")

    out = dict(binding)
    out["binding_location"] = name
    out["bondline"] = _bl
    out["locations"] = {"nose": nose, "body": body}
    out["verdict"] = f"{name.upper()} binds — {binding['verdict']}"
    if other.get("material"):
        out["verdict"] += f"  [{other_name}: {other['verdict']}]"
    if out.get("compromise"):
        out["compromise"] = dict(binding["compromise"], location=name)
    out["warnings"] = list(binding.get("warnings", [])) + [
        f"Body acreage flux modeled as a single screening fraction "
        f"({f:.2f} × body-scale stagnation flux; Lu/Shi & Zhang 2024 cone-tail "
        f"ratio, referenced to the body radius so tip sharpness does not "
        f"inflate acreage heating) — not a heating distribution; windward/"
        f"turbulent flank heating can run 3–5× higher than the laminar value "
        f"used here.",
    ]
    return out


def windward_amplification(delta_deg, alpha_deg):
    """Windward / leeward laminar-heating amplification over the α=0 flank.

    A(α) = sin(δ+α)/sin(δ)  (windward generator);  leeward uses sin(max(δ−α,0)).
    Modified-Newtonian pressure ratio through the √p_e laminar scaling; CP_MAX
    cancels.  δ is floored at _WINDWARD_DELTA_FLOOR (A diverges as δ→0)."""
    d = np.radians(max(float(delta_deg), _WINDWARD_DELTA_FLOOR))
    a = np.radians(max(float(alpha_deg), 0.0))
    sd = np.sin(d)
    win = np.sin(min(d + a, np.pi / 2.0)) / sd
    lee = np.sin(max(d - a, 0.0)) / sd
    return float(win), float(lee)


def windward_flank_flux(t, rho, V, alt, rng, *, body_radius_m,
                        flank_half_angle_deg, alpha_band_deg=None,
                        alpha_op_deg=None, emissivity=0.85, body_material="",
                        nose_radius_m=0.0, body_flux_fraction=None,
                        glide_mask=None, delta_defaulted=False,
                        body_form="axisymmetric"):
    """Screening windward-flank convective heating for a lifting RV at AoA.

    Model (all closed-form, Sutton-Graves altitude):
        q̇_flank0 = body_flux_fraction · q̇_stag(ρ,V,R_body)   (α=0 acreage flux)
        q̇_windward(α) = q̇_flank0 · A(α),  A(α)=sin(δ+α)/sin(δ)
        T_eq,w = (q̇_windward / (σ·ε))^¼
    Evaluated over the glide sub-arc (pass glide_mask to exclude the low-AoA
    terminal dive).  Reported as a band across alpha_band_deg with the operating
    AoA marked when supplied.  Windward is off-nose acreage — the nose remains
    the hard-fail driver; this is a body-location severity overlay.

    Returns a flat dict: q_windward_MW_m2 / T_eq_windward_K each {lo,op,hi},
    delta_deg, alpha_band_deg, alpha_op_deg, amplification {lo,op,hi},
    criteria {windward_surface: {...}}, verdict, warnings.
    """
    rho = np.asarray(rho, float); V = np.asarray(V, float)
    alt = np.asarray(alt, float); t = np.asarray(t, float)
    eps = max(float(emissivity or 0.85), 1e-3)
    warnings = []
    # Resolve the live module attrs at call time so thresholds.apply() drives them.
    if alpha_band_deg is None:
        alpha_band_deg = _WINDWARD_ALPHA_BAND
    # Acreage fraction is BODY-FORM-AWARE (METHODS §13.8: cones and flat-bottom
    # lifting bodies carry windward acreage by different physics): cone flank →
    # BODY_FLUX_FRACTION (0.13); flat-bottom wedge/half-cone → the ~7× lower
    # flat-surface value (0.018, single-point Candler CFD anchor).  An explicit
    # body_flux_fraction argument still overrides both.
    flat_form = str(body_form or "axisymmetric") in ("wedge", "half_cone")
    if body_flux_fraction is None:
        body_flux_fraction = (BODY_FLUX_FRACTION_FLAT if flat_form
                              else BODY_FLUX_FRACTION)
        if flat_form:
            warnings.append(
                "Flat-bottom lifting body: acreage fraction "
                f"{BODY_FLUX_FRACTION_FLAT:g} (Candler & Leyva 2022 CFD "
                "anchor, single-point) — the cone value "
                f"{BODY_FLUX_FRACTION:g} does not apply.")

    delta = max(float(flank_half_angle_deg or 0.0), _WINDWARD_DELTA_FLOOR)
    if float(flank_half_angle_deg or 0.0) < _WINDWARD_DELTA_FLOOR:
        warnings.append(
            f"Forebody half-angle {float(flank_half_angle_deg or 0.0):.1f}° "
            f"floored to {_WINDWARD_DELTA_FLOOR:.0f}° (windward amplification "
            f"diverges as δ→0; screening guard, not a cited threshold).")
    if delta_defaulted:
        warnings.append(
            f"Forebody geometry unset — half-angle defaulted to {delta:.0f}° "
            f"(flagged inference).")

    R_body = float(body_radius_m) if body_radius_m and body_radius_m > 0 else float(nose_radius_m or 0.0)
    if R_body <= 0:
        return dict(verdict="windward not evaluated (no body radius)",
                    warnings=["no body/nose radius for the windward acreage scale"],
                    delta_deg=delta, criteria={})

    # α=0 flank flux over the (glide-masked) arc, then peak.  The acreage
    # boundary layer trips turbulent at low altitude (transition gate, §13.11):
    # multiply the laminar flank flux by the per-sample turbulent factor before
    # taking the peak, so the peak reflects turbulent augmentation where it
    # actually occurs on the arc.
    _R_trans = float(nose_radius_m) if nose_radius_m and nose_radius_m > 0 else R_body
    _tf, _re_rn, _tstate = transition_factor(rho, V, alt, _R_trans)
    q_flank0 = float(body_flux_fraction) * _stag_flux(rho, V, R_body) * _tf
    q_stag_nose = _stag_flux(rho, V, float(nose_radius_m)) if nose_radius_m and nose_radius_m > 0 else None
    mask = np.ones(t.shape, bool) if glide_mask is None else np.asarray(glide_mask, bool)
    if mask.shape != q_flank0.shape or not mask.any():
        mask = np.ones(q_flank0.shape, bool)
        if glide_mask is not None:
            warnings.append("glide-phase mask empty — windward evaluated over the full arc.")
    q_flank0_pk = float(np.max(q_flank0[mask])) if q_flank0[mask].size else 0.0
    _tf_pk = float(np.max(np.asarray(_tf)[mask])) if np.ndim(_tf) and np.asarray(_tf)[mask].size else float(np.max(_tf) if np.ndim(_tf) else _tf)

    a_lo, a_hi = float(alpha_band_deg[0]), float(alpha_band_deg[1])
    A_lo, _ = windward_amplification(delta, a_lo)
    A_hi, _ = windward_amplification(delta, a_hi)
    A_op = windward_amplification(delta, alpha_op_deg)[0] if alpha_op_deg is not None else None

    def _T(q):    return float((q / (eps * SIGMA)) ** 0.25) if q > 0 else 0.0
    q_lo, q_hi = q_flank0_pk * A_lo, q_flank0_pk * A_hi
    T_lo, T_hi = _T(q_lo), _T(q_hi)
    q_op = (q_flank0_pk * A_op) if A_op is not None else None
    T_op = _T(q_op) if q_op is not None else None

    # Stagnation-approach guard: windward should stay below the nose stagnation
    # flux for the screening regime.
    if q_stag_nose is not None and q_stag_nose[mask].size:
        q_stag_pk = float(np.max(q_stag_nose[mask]))
        if q_stag_pk > 0 and q_hi >= q_stag_pk:
            warnings.append(
                f"Windward estimate ({q_hi/1e6:.1f} MW/m²) approaches the nose "
                f"stagnation flux ({q_stag_pk/1e6:.1f} MW/m²) — sharp tip + small "
                f"δ + high α is outside the screening regime; treat as a flag.")

    # Body material limits → the windward criterion.
    mat = TPS_MATERIALS.get(str(body_material or "")) if body_material else None
    criteria = {}
    verdict = ""
    if mat and not mat.get("is_ablator"):
        cont, peak = float(mat["continuous_K"]), float(mat["peak_K"])
        criteria["windward_surface"] = {
            "limit_continuous_K": cont, "limit_peak_K": peak,
            "T_lo_K": T_lo, "T_hi_K": T_hi, "T_op_K": T_op,
            # margins: robust (even at the gentlest α=lo) and worst (α=hi)
            "margin_soak_lo": (T_lo / cont) if cont else 0.0,
            "margin_peak_hi": (T_hi / peak) if peak else 0.0}
        if T_lo > cont:
            verdict = (f"windward flank exceeds the body continuous limit "
                       f"({mat['label']} {cont:.0f} K) even at α={a_lo:.0f}° — "
                       f"body TPS runs beyond its soak limit on the windward side")
        elif T_hi > peak:
            verdict = (f"windward flank can exceed the body peak limit "
                       f"({mat['label']} {peak:.0f} K) at α≤{a_hi:.0f}° — "
                       f"needs a dedicated AoA/transition analysis")
        else:
            verdict = (f"windward flank within the body limits across α "
                       f"{a_lo:.0f}–{a_hi:.0f}° ({mat['label']})")
    elif mat and mat.get("is_ablator"):
        verdict = (f"body is an ablator ({mat['label']}) — windward reported as "
                   f"flux/T_eq only (recession is the failure mode, not T_eq)")
    else:
        verdict = "windward flux/T_eq only (no body TPS material set)"

    # Transition state → a computed turbulent factor (was a static 3–5× flag).
    _re_pk = float(np.max(_re_rn)) if np.ndim(_re_rn) and np.asarray(_re_rn).size else float(_re_rn)
    if _tstate == "laminar":
        warnings.append(
            f"Acreage boundary layer laminar over the glide (peak Re_Rn "
            f"{_re_pk:.1e} < {RE_RN_TRANSITION_ONSET:.0e} onset) — no turbulent "
            f"augmentation (Kuntz 1999 transition gate, §13.11).")
    else:
        warnings.append(
            f"Acreage boundary layer {_tstate}: flux ×{_tf_pk:.1f} applied to "
            f"the flank at peak (Re_Rn to {_re_pk:.1e}; turbulent 3–5× band, "
            f"Kuntz 1999 transition gate, §13.11).")
    warnings.append(
        "Control-fin / body-fin gap interference heating can reach 10–80× the "
        "fin-off flank value at reattachment (Alviani 2022, AEDC Mach-6); "
        "screening cannot place the reattachment line — flagged, not computed. "
        "Computed value needs a coupled solver (Murray & Russell 2002, MASCC).")
    if alpha_op_deg is None:
        warnings.append(
            "No trimmed operating AoA (separating RV or geometry unset) — "
            "windward reported as a band only.")

    return dict(
        q_windward_MW_m2={"lo": q_lo / 1e6, "op": (q_op / 1e6 if q_op is not None else None), "hi": q_hi / 1e6},
        T_eq_windward_K={"lo": T_lo, "op": T_op, "hi": T_hi},
        delta_deg=delta, alpha_band_deg=(a_lo, a_hi), alpha_op_deg=alpha_op_deg,
        amplification={"lo": A_lo, "op": A_op, "hi": A_hi},
        acreage_fraction=float(body_flux_fraction),
        body_form=str(body_form or "axisymmetric"),
        q_flank0_peak_MW_m2=q_flank0_pk / 1e6, body_material=str(body_material or ""),
        transition_state=_tstate, transition_factor_peak=_tf_pk, Re_Rn_peak=_re_pk,
        criteria=criteria, verdict=verdict,
        thompson_band="engineering-code AoA uncertainty ~15–40% (Thompson 1989)",
        warnings=warnings)
