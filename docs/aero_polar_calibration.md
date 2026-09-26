# Where the reentry drag polar gets its numbers — and which half is trustworthy

Scope: `trajectory._aero_polar`, `booster_models.lifting_body_sweep`, and the
question of replacing an asserted `glider_LD` with a geometry-derived one.
No vehicle-specific content; the findings below are properties of the two
methods, measured on generic slender shapes.

---

## 1. What the code does today

`_aero_polar` (trajectory.py) builds `C_D = C_D0 + k·C_L²` from **two scalar
user inputs**:

```
C_D0 = m / (beta_kg_m2 · A_ref)        # zero-lift drag, from the entered beta
k    = 1 / (4 · C_D0 · glider_LD²)     # back-solved so (L/D)max IS the input
C_L* = sqrt(C_D0 / k) = 2·C_D0·glider_LD
```

Two consequences follow directly from the algebra:

- The polar attains `glider_LD` at exactly **one** lift coefficient, `C_L*`.
  Everywhere else L/D is lower. Only `skip_glide` and the nominal branch of
  `damped_glide` fly at `C_L*`; `equilibrium_glide*` trims to
  `m·(g − V²/r)/cos σ`, a commanded pull-up trims to the structural g-limit,
  and banking raises the required `C_L` — all of which sit off the peak.
  (`glider_aero_model="constant_LD"` is the exception: there lift is literally
  `drag × L/D` at all times, by design, as the closed-form-range cross-check.)
- The peak always lands at `C_D = 2·C_D0`, as an identity of the construction
  rather than a result.

Note also that the reentry integrator carries **no angle of attack**. The polar
is parameterised in `C_L`; α appears only in boost-phase code
(`_alpha_limited_dir`, `_boost_alpha_aero_force`) and, on the reentry side,
solely as the fixed 25° cap that sets `C_L_max`.

## 2. The over-determination

`beta_kg_m2` is a statement about zero-lift drag. `glider_LD` is a statement
about peak efficiency. They are entered independently, and the back-solve
constructs whatever `k` reconciles them. **The model cannot disagree with the
user** — any pair yields a self-consistent vehicle.

A bottom-up estimator changes this. Integrating a pressure law and a friction
law over the geometry yields `C_L(α)` and `C_D(α)` as a coupled pair, so `C_D0`
*and* `k` both fall out of one shape. β and L/D then stop being independent
inputs; they become two projections of the same curve. Entering both would
over-determine the vehicle, and the schema question becomes which one is data
and which is an override.

Which one is data is not a close call for this project's evidence base. **β is
observable** — it falls out of measured deceleration along a track, given an
atmosphere. **L/D is not**: it is inferred from range and crossrange, which
depend on a guidance law and bank schedule that open sources do not supply. So
the intended shape is geometry plus β generating the polar, with L/D an
*output*; an override remains available but should have to state a reason and,
per §4a, say where the deficit goes.

## 3. Measured: C_D0 is well conditioned, k is not

Comparing the back-solve against an APAS-style impact method (tangent-cone
body, tangent-wedge fins, Eckert reference-temperature friction, and the
existing `cd_cone_hypersonic` base term) on slender shapes:

- **C_D0 / β agree to roughly 10%.** Zero-lift drag decomposes into terms that
  are separately estimable and individually citable — forebody pressure,
  wetted-area friction, base drag. A representative slender-cone split is
  ~39% pressure / ~37% friction / ~24% base. The residual spread between the
  two routes is dominated by the **friction** assumption (transition state,
  wall-temperature ratio, Reynolds number), not by the pressure law: taking
  `cd_cone_hypersonic`'s internal friction instead of an Eckert value at
  Re_L = 1e7 moves C_D0 by ~16% and β with it. That is an arguable modelling
  choice, not an unknown.

- **k can differ by a factor of ~2.** Drag-due-to-lift is never estimated in
  the back-solve; it is *inferred* from the asserted L/D. When the asserted
  value sits below what the geometry supports, the back-solve absorbs the
  entire deficit into `k`. That is a physically different vehicle from one
  carrying the same deficit as extra parasite drag: same peak, same β,
  different behaviour at every other lift coefficient — and off-peak is where
  most of a maneuvering trajectory lives.

The parabolic **form** holds on a bare body and degrades once lifting
surfaces are added. Fitted against an impact-method sweep, `k` holds to ±8%
over α = 2–15° on an unfinned slender body, and the `C_D = 2·C_D0` identity at
the peak emerges independently from that build-up (~2.0× measured). On a
configuration with a wing the point-by-point `k` is **not** flat: over
α = 2–12° it spreads 44% under tangent-wedge and 69% under Newtonian. Quote
the ±8% as a body-alone result only.

## 4. The pressure law fixes C_L and C_D, not their ratio

Relevant to any proposal to replace the Newtonian estimator. Exact
Taylor–Maccoll surface Cp (NACA 1135 relations, already implemented in
`validate_cone_wave_drag.py`) divided by Newtonian `Cp = 2 sin²θ`:

| cone half-angle | M3 | M6 | M10 |
|---|---|---|---|
| 5°  | 2.21 | 1.44 | 1.24 |
| 10° | 1.45 | 1.19 | 1.11 |
| 20° | 1.22 | 1.09 | 1.06 |

Substantial, and worst where the hypersonic similarity parameter `K = M·θ` is
smallest — which is exactly the regime a small fin at low incidence occupies,
and where the `sin²` law is furthest from the near-linear behaviour of real
thin-surface lift.

But the same factor multiplies windward lift and windward pressure drag, so it
largely cancels in the ratio. Measured on the same panels, changing only the
pressure law:

- **C_L** moves by 10–30%.
- **L/D** moves by ≤1% on a bare cone, ≤6% on a cone with a wing.

So a better pressure law buys real accuracy in `C_L`, in `C_D`, and therefore
in **β** — and essentially nothing in `glider_LD`. If a derived L/D looks
wrong, the pressure law is not the place to look. The terms that move L/D are
the ones that add drag without adding lift: appendages, control-surface trim
deflection, nose bluntness, and the laminar/turbulent state. Since
`(L/D)max ∝ 1/sqrt(C_D0·k)`, doubling parasite drag costs ~30% of the peak.

**The cancellation is a statement about the peak, not about the polar.** It
holds where the pressure law is wrong by a level at fixed inclination. It does
not hold where the law has the wrong *functional form* — and Newtonian's
`sin²` law does, on a thin surface at low incidence, where real lift is nearly
linear in α. That error lands in `k`. Measured on a winged configuration at
M10, swapping Newtonian for the tangent laws moved fitted `C_D0` by ×1.23 and
fitted `k` by ×0.83 while leaving `(L/D)max` at 6.25 → 6.17, a 1% change: the
two errors cancel *in the peak formula* and not in the curve either side of
it. Practical consequence — Newtonian is acceptable for a body-alone `C_D0`
and must be kept out of the `k` path for fins.

Corollary for diagnosis: if C_D0 agrees between the two routes and `k` does
not, that is a finding, not just a discrepancy. It localises the deficit to
drag-producing hardware absent from the geometry description, or to a
control-authority limit holding the vehicle off its aerodynamic peak — and
both of those are checkable against open evidence in a way that a bare L/D
number is not. `trim_gate` already expresses the second as
`LD_max` vs `LD_achievable`.

## 4a. Where a deficit should land: C_D0, not k

When a derived (L/D)max exceeds an asserted one, the difference has to go
somewhere, and the choice is not neutral. Holding the target peak fixed, a
representative case — geometry `C_D0 = 0.0590`, `k = 0.708`, peak 2.45,
asserted 1.80:

| deficit absorbed into | C_D0 | k | C_L* | C_D at C_L* |
|---|---|---|---|---|
| `C_D0` (parasite) | 0.1090 | 0.708 | 0.392 | 0.218 |
| `k` (induced) — what the back-solve does | 0.0590 | 1.308 | 0.212 | 0.118 |

Same peak, same input pair, **C_L\* differing by a factor of 1.85**. The
`k` route builds a polar that is too sharp: the vehicle trims at roughly half
the lift coefficient, so it wants to fly lower and faster, and every
high-`C_L` segment is over-penalised — by 1.06× at 1.5× the trim lift, 1.25×
at 2×, 1.49× at 3×. Those are exactly the segments that matter in a
maneuvering trajectory: equilibrium glide as the vehicle slows, commanded
pull-ups, banked turns. The result is a range and terminal-energy error
concentrated where the analysis is least forgiving.

The physical argument points the same way. Drag that a clean body-plus-fins
description omits — nose bluntness, trim deflection, gaps and protuberances,
a turbulent rather than laminar wall — is nearly all **parasite**. So the
default home for an unexplained deficit is `C_D0`, and routing it to `k`
should require a reason.

## 5. Validation status — read carefully

The impact method above reproduces the lift curves of the NASA TM 102610
generic winged-cone simulation database to within ~1% for α ≥ 6°, against
0.84–0.90 for Newtonian on the same panels. **This is method reproduction, not
validation.** TM 102610 p. 15 states its own database was generated by
APAS/HABP using "the tangent-cone (fuselage component) and tangent-wedge (wing
and tail components) methods… Prandtl-Meyer expansion… for all shadow
surfaces… viscous shear forces… estimated using the reference enthalpy
method." Agreement therefore confirms a correct implementation of the law and
says nothing about whether the law is right.

The actual accuracy claim is one step further out: Cruz & Wilhite
(AIAA-89-2173) put APAS within 10% of Space Shuttle databook values, with an
~11.8% overprediction of pressure drag against VSL3D. That is the bound any
screening-tier estimator built on this method inherits, and it is the number
to quote — not the 1%. Read it as optimistic for this application: the Shuttle
case is blunt, high-α and large-winged, a different corner of the method's
envelope from a slender body at low α. Note also the direction of the pressure
bias — overpredicting pressure drag biases a *derived* L/D low, so correcting
for it widens a gap against a lower asserted value rather than closing one.
The magnitude is small (pressure is ~39% of the zero-lift build-up, so ~12% on
pressure is ~2% on L/D), but the sign matters for diagnosis.

**The one non-circular check available is the cone-alone comparison** against
the exact Taylor–Maccoll solution in §4, which uses no impact-method reference
at all. Cite that, and the Cruz & Wilhite bound, in preference to the TM
102610 agreement.

## 6. What is now enforced

`booster_models.check_beta_ld_pairing()` supplies the disagreement §2 says the
polar cannot make. The entered pair fixes its own trim point with no geometry
involved — `C_D0 = m/(β·A_ref)`, `C_L* = 2·C_D0·(L/D)`, `C_D* = 2·C_D0`, the
last two being identities of the back-solve — and the swept geometry is asked
one question: *what is your drag at C_L\*?* Deliberately **no fitted k**, since
§3 shows a parabola is a poor summary once a lifting surface is present.

Two one-sided tests, because the sweep's C_D is a floor: `beta_below_shape`
(entered β claims less zero-lift drag than the shape has) and
`drag_below_shape` (the pair claims less drag than the shape has at the lift it
needs). Both can fail independently — a small `C_L*` leaves room for one to
pass while the other fails. An L/D *below* what the geometry supports is never
a failure; the surplus is reported as the parasite drag the pairing implies but
the description does not explain.

`check_ro_pairing_band()` sweeps M3–M20 and returns the **most permissive**
verdict, because β is a schema constant with no stated conditions while a
shape's own β varies several-fold across that band — a single-Mach verdict is
partly an artefact of the Mach chosen. Only *"no Mach in the band supports
this"* is defensible.

`pairing_note()` is the pure text/severity formatter, kept out of the GUI so it
is testable without a display. In the object editor the note has its own line
in the Maneuvering box, visible for every separation mode, and is **advisory
only** — nothing blocks a save. (The first version hung off the body-only L/D
preview label and was fed the derive-mode preview object, which carries β =
L/D = 0, so it never appeared for any separating object. Fixed, with a GUI
regression test in `test_beta_ref_mach.py`.) `test_beta_ld_pairing.py` carries the unit tests and a
characterisation table of the shipped library, so a change to any object's β,
L/D or dimensions surfaces in review.

A flag means the stored *geometry description* cannot support the stored pair,
which is as often an incomplete description as a wrong pair. Every shipped
lifting object declares fins with no stored planform, so the floor is a bare
body — which is exactly why the check warns rather than blocks.

## 7. Open items, in order

1. **`_calc_beta` routing.** thrusty.py routes only `wedge` and `half_cone`
   body forms to `lifting_body_sweep`; an axisymmetric form reaches the β-only
   dialog and never sees the α-sweep estimator, even though `'cone'` is a
   member of `_LIFTING_SWEEP_FORMS`. This is first: it is the reason an
   axisymmetric body cannot reach the estimator this memo argues should be
   authoritative — it can now be *told* its pair is inconsistent, but still
   cannot be given an estimated L/D to replace it. The fix is not a one-liner:
   `_calc_beta_lifting`'s non-wedge branch is written for `half_cone` (title,
   and a wing composite that `lifting_body_sweep` honours only for that form),
   so routing `cone` through it would silently drop the wing planform. Either
   extend the sweep's wing composite to `cone`, or branch the dialog
   explicitly — and keep the existing β-only dialog reachable, since it is the
   only path that handles biconic geometry.
2. **Nose bluntness.** Absent from the zero-lift build-up, and the largest
   single missing parasite term for a shape described as a sharp cone. A
   Newtonian cap estimate, `ΔC_D ≈ (Cp_stag/2)·(r_n/r_b)²` on base area, gives
   +0.010 at `r_n/r_b` = 0.10 and +0.021 at 0.15 (modified, Cp_stag = 1.84) —
   against a representative slender-cone `C_D0` of 0.059 that is 7% and 14%
   off the peak L/D respectively. Large, but on its own **not** enough to
   close a factor-two `k` gap, which would need roughly +0.050. The remainder
   has to come from fins, trim deflection and wall state. `nose_radius_m` is
   already stored, so this is computable now.
3. **The wing composite** in `lifting_body_sweep` is gated to `half_cone`.
4. **Wing-body carryover and shock-layer interference** are absent from both
   routes. Note the sign: carryover adds lift at little drag, so including it
   *lowers* `k` and *raises* the derived L/D — it cannot be the home for a
   residual that needs `k` to rise, and adding it widens the gap against a
   lower asserted value. That is further evidence the residual is drag
   hardware rather than pressure-law error. NACA 1307 supplies slender-body
   carryover factors but assumes a circular **cylinder**, which a cone frustum
   is not, and it is likely generous for small fins near the base, where much
   of the span sits in the body's boundary and entropy layers.
5. **Constant β in the schema — DONE.** `ROParams.beta_ref_mach` (hardware)
   states the Mach at which `beta_kg_m2` holds. 0 = the legacy constant β,
   byte-identical for every existing file (verified on full trajectories).
   When set, `booster_models.beta_mach_table` holds the entered β exact at
   that Mach and takes only the *relative* variation from the object's own
   zero-lift build-up — the same one the β estimator uses, so an estimate at
   Mach X stamped with X reproduces itself. An entered L/D is scaled by
   `sqrt(C_D0(M_ref)/C_D0(M))`, which keeps `k` fixed: the variation is
   zero-lift drag and lands in C_D0, per §4a. The integrator drives both the
   zero-lift drag and the glide polar from the tables; the pairing check tests
   at the stated Mach instead of the band; both estimator dialogs stamp their
   Mach into the new editor field on *Use*. Two cautions. The only
   Mach-dependent term is base drag, `2/(γM²)`, the p_base → 0 limit, which
   overstates base drag toward low supersonic Mach — the low-Mach end of the
   table is biased toward low β. And the reference Mach matters about as much
   as β itself: the same β stated at M5 versus M15 moves a horizontal-burnout
   glide from 1363 km to 937 km (1173 km at constant β).
6. **A tumbling object makes ascent integration crawl.** With
   `reentry_attitude = 'tumbling'` the boost phase spends its time in
   `drag_force_vector` → `_cd_nose_shape` taking very small steps; a flight
   that takes under a second otherwise does not finish in minutes. Found while
   testing item 5, in code item 5 does not touch; not investigated.

## References

- NACA Report 1135, *Equations, Tables, and Charts for Compressible Flow* —
  θ-β-M relation and the Taylor–Maccoll conical-flow solution.
- Cruz, C. I. & Wilhite, A. W., "Prediction of High-Speed Aerodynamic
  Characteristics Using the Aerodynamic Preliminary Analysis System (APAS),"
  AIAA-89-2173 — accuracy bounds for the tangent-cone/tangent-wedge method.
- Shaughnessy, J. D., Pinckney, S. Z., McMinn, J. D., Cruz, C. I. & Kelley,
  M.-L., *Hypersonic Vehicle Simulation Model: Winged-Cone Configuration*,
  NASA TM 102610, November 1990 — Table I geometry, Fig. 7 lift curves, and
  the p. 15 statement of method.
- Eckert, E. R. G., reference-temperature method — implemented as
  `cf_reference_temperature` in `booster_models.py`.
- Munk 1924; Ashley & Landahl §6-7 — the slender-body polar form cited in the
  `_aero_polar` docstring.
