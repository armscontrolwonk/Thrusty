# Front-End Redesign: the non-separating reentry body

Design document for making Thrusty's depiction and modeling of a **unitary,
non-separating** missile (V-2, Scud, a quasi-ballistic body / Iskander, Pershing II MaRV) mutually
consistent. Companion to `BODY_REENTRY_DESIGN.md` (which established
`separation_mode` and the run-level loadout) and `GLIDE_CAPTURE_DESIGN.md`.

Status: **Phases 0–2 implemented** (2026-08-21); Phase 3 deferred (see §6).
Decisions settled with the user 2026-08-21. Governing rule, as everywhere:
derive, don't invent.

---

## 1. The principle this serves

> **The schematic must be accurate because it is how a human user oversees the
> code. If what is drawn does not match what is flown, the human has no way to
> exercise authority over the model.**

This is the whole motivation. The schematic is not decoration and not a
convenience preview — it is the oversight surface. A screening tool whose
picture disagrees with its physics silently launders modeling errors past the
one reviewer (the human) who could catch them. So the redesign's success
criterion is a single invariant, stated in §3, and every phase is measured
against it.

---

## 2. The bug, precisely

Reconstructing the user's a quasi-ballistic body (single stage ⌀1.1 × 6.7 m; reentry object
"quasi-ballistic body front end" ⌀1.1 × 2.0 m, Von Kármán, `separation_mode = "body"`) exposes
**three distinct defects that happen to overlap** on this vehicle:

| # | Layer | What happens | Evidence |
|---|-------|--------------|----------|
| **A** | Schematic — fabrication | With no fairing, `draw_booster` ignores the reentry object entirely and draws a generic **1.6 × ⌀ = 1.76 m cone** on top of the 6.7 m stage → an **8.46 m** stack that exists nowhere in the data. | `booster_schematic.py:436` (`nl = 1.6 * nd`) |
| **B** | Schematic — wrong shape | Even the to-scale RO drawn in the corner is rendered by `_reentry_shape()`, which **always draws a straight cone** and ignores `ro.shape`. A Von Kármán RV shows as a sharp triangle. | `booster_schematic.py:258` (`_reentry_shape`, unconditional) |
| **C** | Physics ↔ editor mismatch — **CLOSED 2026-09-22** (`_show_inherited_from_booster`; the fields now display the inherited values and a GUI test pins them to `effective_ro`) | For `separation_mode = "body"`, `effective_ro()` **overrides the RO's length with the stage length**: the RO editor shows L = 2.0 m, but the body actually flown is ⌀1.1 × **6.7 m**. The number the user typed is discarded, silently. | `booster_models.py:836–839` |

Defect **C** is the deep one and the reason a plan is needed rather than two
patches. The `fairing_fit` "0.24 m too long" warning is a *fourth* symptom: the
containment check compares the real 2.0 m RO against the fabricated 1.76 m cone
(defect A) — a warning generated entirely from invented geometry.

### Why C exists (and why it is half-right)

`BODY_REENTRY_DESIGN.md` established the correct doctrine: *there is always a
reentry object; a V-2 has a warhead, it just doesn't separate.* For a body-mode
vehicle the reentering object **is** the last stage, so `effective_ro` inherits
the stage's **mass** and **diameter** — which is right, because the body's mass
is the burnout mass and its width is the airframe width. But it *also* inherits
**length**, and that is where the model and the human's input diverge: the user
was given a length field, told it means "the reentry body," and then the code
throws it away in favor of the motor-tube length. The physics then treats the
entire 6.7 m tube as the reentering body (`_boost_front_geometry` returns
`ro.length_m = 6.7`), which is defensible for a tumbling spent stage but wrong
for a shaped MaRV whose actual reentry body is the forward ~2 m.

---

## 3. The invariant

Every phase below is in service of one testable statement:

> **DRAWN ≡ FLOWN.** The geometry rendered by `booster_schematic.draw_booster`
> is the same geometry consumed by the physics through `effective_ro` /
> `_boost_front_geometry` — same overall length, same body diameter, same nose
> shape and nose length, same body form. No element is drawn that the physics
> does not use; no element is flown that the schematic does not show. Where a
> value is a fallback, it is flagged identically in both.

This is enforceable as a test (Phase 1) and is the acceptance gate for the whole
effort.

---

## 4. The design decision: subtractive length

The user chose the **subtractive** model for a unitary body (over the additive
"motor tube + separate nose section" alternative):

> **The last-stage length IS the whole airframe. The nose is the forward taper
> carved out of the top of that length — not an extra section stacked on top.**

For a a quasi-ballistic body that means: one true length, 6.7 m. The forward (say) 2.0 m is the
shaped ogive/Von-Kármán nose; the aft 4.7 m is the cylindrical motor body. Total
drawn height = 6.7 m, matching the airframe and the flown body. There is no
8.46 m anywhere.

### Why subtractive, not additive

- **A unitary missile has one length.** A V-2/Scud is a single tube with a
  pointed top. "Motor length 6.7 m" already *includes* the ogive on any real
  drawing; asking the user to enter 4.7 m of motor + 2.0 m of nose forces them to
  hand-subtract and invites the exact double-count we are removing.
- **It makes DRAWN ≡ FLOWN natural.** `effective_ro` already inherits the stage
  length as the body length. Subtractive keeps that: the body length is the stage
  length, and the nose length is a *portion* of it, so nothing is overridden or
  discarded — the RO's role narrows honestly to *shape + nose fraction*, not a
  competing length.
- **Additive re-introduces the mismatch.** If the nose were a separate stacked
  length the user sets, the physics would again have to choose between the RO
  length and the stage length — the very fork that produced defect C.

### Consequence for the data model

For `separation_mode = "body"`:

- **Body length** = last-stage `length_m` (authoritative; the airframe).
- **Body diameter** = last-stage `diameter_m` (already inherited; unchanged).
- **Body mass** = last-stage burnout mass (already inherited; unchanged).
- **Nose shape** = `ro.shape` (the RO contributes this — now actually used).
- **Nose length** = the forward taper carved from the body. Sourced, in order:
  (a) an explicit nose-length field if the RO carries one; else (b) a
  shape-appropriate default *fraction* of the body length, **flagged** as a
  fallback. It is bounded to `≤ body length`, so a nose can never exceed the
  airframe (the class of defect A can never recur).
- The RO editor's **length field becomes derived/read-only in body mode** (it
  displays the inherited body length) so the human is never shown an input that
  the code will discard. In `separating_ro` mode the length field stays a live,
  independent input exactly as today — separating RVs are unaffected by all of
  this.

Resolved (user, 2026-08-21): the nose length is a **new stored field**,
`ROParams.body_nose_length_m` — additive-free, separating RVs ignore it, and it
does not overload `nose_radius_m` (which means something else). It defaults to a
flagged shape-appropriate fraction when 0, and is bounded to the body length so a
nose can never exceed the airframe.

---

## 5. Scope boundaries

**In scope:** the non-separating (`body`) unitary missile — how its front end is
stored, flown, and drawn, and the guarantee that those three agree.

**Explicitly out of scope (unchanged by this work):**

- **Separating RVs** (`separating_ro`). Their length is a real independent input;
  the corner-drawn RO already uses its own geometry. Only defect **B** (wrong
  shape in the corner drawing) touches them, and its fix is shape-only.
- **Multi-object loadouts** (N > 1). The bus-face blunt-cylinder nose
  (`_boost_front_geometry`, `_multi`) is a deliberate conservative choice and
  stays. Body mode already pins N = 1.
- **Lifting-body forms** (wedge / half-cone). Their depiction and the "span not
  drawn" honesty are already correct; the invariant test will cover them but no
  behavior changes.
- **The trajectory/aero numbers themselves.** This work makes the *depiction*
  match the *existing* physics and stops `effective_ro` from discarding a user
  input. Where the flown body length changes (a shaped MaRV whose reentry body
  becomes the forward taper rather than the whole tube), that is a physics change
  and is called out as its own phase (Phase 3) with before/after ranges reported,
  not folded in silently.

---

## 6. Phased plan

Each phase is independently shippable, ends green, and is gated on the invariant.
Phases 0–2 are **done**; Phase 3 is deferred until a shaped-MaRV physics change is
actually wanted; Phase 4 is folded into this doc's status.

### Phase 0 — the invariant test (write first, RED) — DONE
`test_front_end_consistency.py`. `draw_booster` returns a `front_end`
dict `{kind, shape, nose_length_m, body_diameter_m}`; the test asserts it equals
what `effective_ro` flies, for the body-mode a quasi-ballistic body fixture and every library
booster. Red on the pre-fix 8.46 ≠ 6.7 / cone ≠ Von Kármán, green after Phase 1.

### Phase 1 — schematic truth (fix A + B) — DONE
Body mode draws the last stage with its nose carved subtractively from the top
(the airframe length is the total height); the corner reentry object and the
containment check are skipped for a body (nothing contains it); the corner RO and
the stack nose draw the declared analytic profile (`_nose_profile`) instead of an
unconditional cone. a quasi-ballistic body: 8.46 m → 6.7 m, Von Kármán, no phantom "too long".

### Phase 2 — data model + editor — DONE
`ROParams.body_nose_length_m` (JSON + xlsx round-trip); the RO editor gains a
"Body nose length (m)" field active only in body mode, while mass/diameter/length
already grey out there (inherited from the last stage). Legacy files default the
field to 0 → the schematic's flagged fraction.

### Phase 3 — physics reconciliation (deferred, only if body-length semantics change)
Today the *drawing* uses `body_nose_length_m` (the taper), while the *aero*
(`_boost_front_geometry`) still treats the whole airframe as the reference body —
consistent, because the aero consumes only body diameter (for area) and nose
shape (for Cd), not the taper length. If we later decide the flown reentry body
for a shaped MaRV is the forward taper rather than the whole tube, that changes
`_boost_front_geometry`'s returned body length and therefore drag/heating: treat
it as a distinct, measured change — report before/after range and heating for the
a quasi-ballistic body and the body-mode library entries, keep axisymmetric byte-identity for
everything not in body mode, and pin with tests. Do **not** fold it into the
drawing work above.

### Phase 4 — docs — DONE
This doc's status and §4 resolution updated; the DRAWN ≡ FLOWN invariant and its
test (`test_front_end_consistency.py`) stand as the guarantee.

---

## 7. Acceptance

- The invariant test (Phase 0) is green and runs in CI over every library
  vehicle plus the body-mode fixture.
- The a quasi-ballistic body draws at 6.7 m with a Von Kármán nose and no "too long" warning.
- No input shown to the user in the RO editor is silently discarded by the code.
- Separating-RV, multi-object, and lifting-body behavior is unchanged (pinned).
- Any change to flown numbers (Phase 3) is reported with before/after, never
  silent.

---

# Part II — Ownership and derivation (the booster-default RO)

Status: **proposed** (decisions settled with the user 2026-08-21; not yet built).
Part I made the *depiction* honest. Part II makes the *authorship* honest: for a
non-separating body the "reentry object" is not an independent thing you design
in isolation — it is a **view onto this booster's front end**, with its geometry
inherited from the airframe and its aero (β, L/D, stability) *emergent from the
whole stack*. The current separate-RO editor invites you to type those emergent
quantities as if they were free inputs, which is the root of every inconsistency
in this document (the CG double-count of §2/the 2fb6cf5 fix was the same disease
in the physics path).

## 8. Ownership — the booster-default reentry object

**Decision (user, 2026-08-21): keep the "there is always a reentry object"
doctrine; a non-separating plan auto-seeds a booster-default RO.** When
`separation_mode = "body"` is selected, the RV is not a blank object the user
must invent — it is seeded as *this booster's front end* and presented as such:

- **Inherited-from-booster fields** (mass, diameter, length) are shown
  **read-only**, labeled "from booster" — meaning **from the last stage's own
  Stage-panel fields** (`diameter_m`, `length_m`, and the burnout mass
  `mass_final`), which the user already enters there. This is NOT a
  fairing-style parallel entry: a fairing is separate, jettisonable hardware
  with its own `shroud_mass_kg`/`shroud_length_m`/`shroud_diameter_m` (additive,
  sits on top), whereas a unitary body's front end adds no mass and no length —
  the airframe *is* the last stage, and the nose is the forward taper carved
  from it (subtractive). So there is no new "front-end mass/diameter/length"
  box to add; `effective_ro` already inherits those, and the editor only
  surfaces them read-only so the inheritance is visible.
- **Front-end fields** (nose shape, `body_nose_length_m`, nose radius, TPS
  material) are editable and labeled **"this airframe's nose"** — they are the
  only geometry a unitary body actually adds, and they live here rather than in
  a phantom detached object.
- **Emergent aero** (β, L/D, static-margin verdict) is **derived, not typed**
  (§9–§10): shown with a live value and an Estimate/preview, `0 = derive`.

Rejected alternative (A): moving the front end into the booster editor's Front
End panel. It reads intuitively for a unitary missile but forks the reentry
model — β/L-D/TPS/attitude would have to migrate onto the booster too — and
undoes the BODY_REENTRY_DESIGN.md consolidation. Option B keeps one home for all
reentry physics and one code path (`effective_ro`), while fixing the *framing* so
the object visibly belongs to the booster.

## 9. The derived-vs-entered matrix

The heart of the user's concern: for a non-separating body, be explicit about
which quantities are inherited, which are genuine front-end inputs, and which are
**derived from the full booster+RO stack** and must never be free inputs.

| Quantity | Non-separating body | Why |
|---|---|---|
| mass, diameter, length | **inherited** (read-only, "from booster") | the airframe IS the last stage (`effective_ro`) |
| nose shape, `body_nose_length_m`, nose radius, TPS material | **entered** ("this airframe's nose") | the only geometry a unitary body adds |
| **β (ballistic coeff.)** | **derived β(Mach)** from the airframe Cd₀ (§10); `0 = derive` | β = m/(Cd·A) of the *whole* body, not a sub-cone |
| **L/D** | **derived** (`glider_ld` + `trim_gate`); `0 = derive` | emergent from nose+body+fins at trim (already built) |
| CG / CP / static margin | **derived** from the full stack (`grid_fin_sizing`) | position depends on the whole mass+area layout |
| boost front-end drag/area | **derived** (`_boost_front_geometry`) | the exposed nose is the front end |
| g-limit, bank, terminal dive, pull-up, ζ | **entered** | the maneuvering *plan*, not geometry |
| `separation_mode`, `reentry_attitude` | **plan-level** (sidebar) | how it is flown |

For a **separating RV** the same matrix flips the top three rows to *entered*:
mass/diameter/length/β/L-D are the RV's own designed properties (it is a real,
detachable object), so nothing here changes for that case.

## 10. Deriving β(Mach) from the airframe

Today β is the one emergent quantity still typed on a body (the design comment
even says "no clean way to derive a single scalar β from a Mach-dependent body Cd
table"). That is exactly right — and the fix is to stop asking for a single
scalar. Mirror what L/D already does: derive a **β(Mach) table**, not a number.

The primitives exist: `glider_ld._body_cd0(last, mach)` (nose + skin-friction +
base Cd₀ of the airframe) and `booster_area(params)` (the front-end reference
area). So for a body with `beta_kg_m2 <= 0`:

```
β_body(M) = effective_ro.mass_kg / ( _body_cd0(last, M) · A_ref )
```

sampled over the same Mach grid the L/D table uses (`trajectory.py` ~2070),
stashed as `params._beta_of_mach` alongside `params._ld_of_mach`, and read by the
drag terms (`trajectory.py:1099/1232/1267/1347`) in place of the scalar
`_ero.beta_kg_m2`. A **scalar fallback** at `GLIDE_MACH_REF` fills the analytic
paths and any non-table read, exactly as L/D does. A separating RV, or any body
with β entered `> 0`, keeps its scalar untouched — `0 = derive` is opt-in and the
legacy default (β = 10000) still means "typed".

**Two β regimes — nose-first vs tumbling (user, 2026-08-21).** The derived β
above is the **nose-first** β: the airframe flying pointed, held there by its
nose and (especially) fins. A body that *cannot* hold that attitude **tumbles** —
a bluff spinning cylinder with a far lower β (heavy drag, near-terminal impact),
which `effective_ro` already derives from `tumbling_cylinder_beta` when
`reentry_attitude == 'tumbling'`. These are physically distinct — a finned
a quasi-ballistic body strikes fast, a bare spent stage flutters down — and the tool already has
the discriminator: the **trim gate** (which includes the fins in the CP) decides
nose-first-vs-tumbling, and β simply follows it. So the nose-first β(Mach) table
is used only while the body is nose-first; the moment the gate (or the user)
declares tumbling, the table is dropped and the tumbling scalar wins. A separated
nose leaves the spent stage as its own tumbling debris object — a different case,
handled by the debris path, not this table.

Honesty caveats to surface (not hide): a Mach-dependent β makes the "ballistic
coefficient" a curve, so the reports/estimator must show β at the reference Mach
plus its range, and note it is a screening Cd₀ build-up, not a measured value —
the same disclosure standard as the L/D estimate. `result['derived_beta_kg_m2']`
carries the nose-first ref-Mach value (or `None` when not derived / tumbling).

## 11. Phasing (Part II)

Independently shippable, each gated on tests. **P2-A/B/C/D done (2026-08-21).**

- **P2-A — β(Mach) derivation — DONE.** `_beta_of_mach` for a body with β≤0,
  mirroring `_ld_of_mach`; the drag reads prefer it via `_beta_eff`; scalar
  fallback at the ref Mach, surfaced as `result['derived_beta_kg_m2']`. The
  nose-first table applies only while the body is nose-first — a tumbling body
  keeps `effective_ro`'s tumbling-cylinder β (§10). `_body_cd0`/`whole_booster_LD`
  now read the as-flown nose (the RO's shape for a body via `_front_nose_aero`),
  so β and the L/D build-up reflect the real nose, not the flat Forden fallback —
  β(M) rises 4300→8000 across M2→M12 instead of a flat 8934.
  `test_body_beta_derive.py`.
- **P2-B — editor framing — DONE.** β and L/D default to `0 = derive` in body
  mode with green hints; inherited mass/diameter/length are labeled
  "(from booster)" (read-only) — from the last stage's Stage-panel fields, not
  a fairing-style parallel entry (§8). Separating RVs keep their designed-value
  defaults and no hint. No physics change.
- **P2-C — the derived-vs-entered guard — DONE.** `test_front_end_matrix.py`
  pins the §9 matrix: for a body, mass/dia/length are inherited (the RO's own
  values are ignored) and β/L-D are derived when 0; for a separating RV those
  fields are its own honored inputs.
- **P2-D — docs — DONE.** This doc's status; METHODS §6.4 (Part I) carries the
  DRAWN ≡ FLOWN note.

Follow-ups — **all done (2026-08-21):**
- **Reentry CG** — `ROParams.reentry_cg_m` (0 = uniform-airframe centroid; a
  positive value overrides at the trim gate), body-only editor field, round-trip.
  Investigation showed burnout-vs-full-tank CG is a no-op for a uniform single
  body — both centre on the tube — so the real lever is CG *placement*
  (warhead-forward → stable). `test_body_cg_stability.py`.
- **Report surfacing** — the Booster Parameters tab previews the derived β (ref
  Mach + M2–12 range + screening caveat) and the trim-gated L/D whenever they
  are left at 0 = derive.  The L/D preview names the static margin, the usable
  control deflection, and whether that deflection was ASSUMED (the `unknown`
  tier), and distinguishes three no-glide outcomes: tumbling (unstable),
  ballistic nose-first (stable, no commanded control surfaces), and no trimmed
  attitude at full deflection.  The β preview shows the tumbling-cylinder β only
  when the body actually tumbles — a stable body that makes no lift still flies
  nose-first and keeps its nose-first β.
- **Estimate body L/D button** — the whole-body build-up (`_estimate_body_LD`)
  is wired to a sidebar "Estimate body L/D…" button and composes the current
  object so it matches the run.

Open question deferred to build time: the CG estimate is *full-tank* (§ Part I,
`estimate_cg` docstring) but reentry stability wants the *empty/burnout* CG;
with a near-neutral body (the a quasi-ballistic body came out SM ≈ 0) that difference can flip the
verdict. Worth a burnout-CG option, but it is a separate correctness item from
the ownership/β framing here.

---

# Part III — Biconic, payload ownership, and the vehicle-level switch

**All done (2026-08-22).** Three gaps surfaced once the body was being driven
in earnest: a declared biconic was drawn and flown as a single cone, a body's
payload had no home but the stage's dry mass, and separation lived only on the
flight plan. Each is closed below.

## 12. Biconic end-to-end (declared ≡ modeled)

The DRAWN ≡ FLOWN invariant (§3) was holding in the grimmest way for a biconic:
the schematic drew one cone because the physics *flew* one cone. The break
fields (`fore_length_m`, `break_diameter_m`) were stored but read by **only** the
manual β-estimate dialog (`cd_biconic_hypersonic`); every other consumer — the
flown drag, the trim gate's CP, the L/D build-up, the schematic — keyed on the
shape *string*, which for a biconic is `'cone'`. So the user could declare a
biconic, type a biconic β, and unknowingly fly a single cone with a
single-cone CP. That is exactly the declared-vs-modeled mismatch the invariant
exists to prevent — it just sat one level below "schematic vs physics."

The fix promotes the biconic to a first-class shape through all four consumers
from **one shared resolver** so they cannot drift:

- `booster_models.biconic_nose_geometry(params)` — the as-flown two-cone
  geometry (θ₁, θ₂, break ratio, ε, segment lengths), or `None` when the break
  fields are unset/invalid (so callers keep the single-cone path — biconic
  activates only once fully specified). For a body the biconic occupies the
  subtractive `body_nose_length_m`; total height is unchanged.
- `cd0_biconic_body()` — body Cd0 = `cd_biconic_hypersonic` (two-cone Newtonian)
  + the cylindrical-afterbody friction. Feeds the flown β(M) and the L/D
  denominator via `glider_ld.body_cd0` / `whole_booster_LD`.
- `biconic_nose_cp_fraction()` — the area-weighted Barrowman CP of the fore cone
  + aft frustum; feeds the trim gate through `grid_fin_sizing`.
- planform in `whole_booster_LD` — fore triangle + aft trapezoid + afterbody,
  not one fill fraction.
- `booster_schematic` — the body-nose path draws the two cones (`_biconic_shape`)
  and records `front_end` kind `body_biconic`.

**Two exact reduction identities anchor it** (`test_biconic_front_end.py`): a
biconic with θ₂ = θ₁, sharp, is a single hypersonic cone (Cd0 matches to machine
precision); and a break lying on a straight cone recovers the single-cone CP
fraction 2/3. The break ratio is the CP lever — a slender break throws area onto
the aft frustum and moves the CP aft, a fat break moves it forward.

**Framework note (documented in `cd0_biconic_body`).** A biconic uses the
hypersonic Newtonian two-cone build-up (valid M ≥ 3), distinct from the
Chin/NACA single-nose build-up (`_cd_nose_shape`) used for single-profile noses.
Toggling biconic therefore shifts frameworks — comparable but not identical at a
shared Mach — by design. Single-profile noses (cone, tangent ogive, Von Kármán,
LV-Haack, parabola) were **already** end-to-end: every consumer keys on the same
shape string, so only the biconic (a flag, not a string) was second-class.

## 13. Payload ownership — A2 (the front end owns its payload)

A non-separating body IS the last stage, so its structural + residual burnout
mass is inherited (§ Part I). The remaining question — *where does the warhead /
bus / guidance mass go?* — had no good answer: it was folded silently into the
stage's dry mass, with no distinct knob. **A2** gives the front end an explicit
added payload:

- `ROParams.payload_kg` — the added body payload, on top of the inherited
  airframe burnout mass. Round-trips through JSON and the `.xlsx` sheet.
- `compose_loadout` (body branch) adds it to the boosted stack and to the last
  stage's burnout mass (fused through burnout), via a **tracked-baseline delta**
  so composing twice adds it once. The RO's own `mass_kg` is still **never**
  added for a body — the 574 → 137 km double-count guard holds; only
  `payload_kg` is.
- `BoosterParams.body_payload_kg` — the idempotency baseline, kept **separate**
  from `payload_kg`. `payload_kg`'s baseline is the separating design payload;
  reusing it made a body *subtract* the booster's baked warhead (a Scud-B bakes
  1000 kg). Runtime bookkeeping, not serialised.
- No reentry-side code: `effective_ro` / `_mass_at_time` already derive the
  body's reentry mass from `mass_initial − propellant`, so both pick up the
  payload automatically.

Default 0 → every existing file flies byte-identical. With payload set, the
boost mass and the reentry mass both rise by it and the flyout lands short
(+500 kg: 466 → 261 km). The editor shows an editable "+ payload" beside the
read-only airframe mass and a live "= N kg reentry (airframe + payload)" line.
`test_body_payload.py`.

Why A2 over A1 (a stage-level warhead field): the user chose it so the front end
is the single console where its own properties are overseen — "there is no reason
it can't live inside the reentry object." The idempotent-compose discipline (the
separate baseline) is what makes A2 safe.

## 14. Separation is a vehicle property — `body_reenters`

Separation used to live only on the reentry plan (chosen so one aeroshell could
be A/B'd separating vs. integrated). But for a Scud / a quasi-ballistic body the body reenters —
full stop; that is a fact about the missile, not the flight. `BoosterParams.
body_reenters` (a checkbox in the booster editor's Payload / Front End section)
makes the vehicle the master: when set, the sidebar locks the reentry-plan
Separation to "body" and greys the combo; the reentry Mode still defaults to
ballistic and stays switchable. Unchecked, the plan owns separation exactly as
before. A pure-physics no-op — the run reads the plan's `separation_mode`; the
flag only drives the editor lock. Default off → existing boosters unchanged.
`test_body_payload.py` (round-trip + physics-noop).

## 15. Acceptance (Part III)

- A biconic a quasi-ballistic body shows a different Cd0, CP/static margin, L/D and flyout range
  than the single-cone control, and the schematic matches. ✓ (15 tests)
- Reduction identities exact (Cd0 to machine precision, CP to 2/3). ✓
- Payload 0 = byte-identical; +N raises boost and reentry mass and shortens
  range; compose is idempotent; `mass_kg` never added for a body. ✓ (9 tests)
- `body_reenters` round-trips and is a physics no-op. ✓
- Suite 479 → 503.
