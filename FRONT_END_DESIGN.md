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
  *Later (2026-09-27):* with **no fairing**, the separating object is the
  front end and is drawn only in the corner — the stack no longer also carries a
  "payload / RV" nose (stored `nose_length_m` or the 1.6×⌀ fallback), which the
  physics never flew (`_boost_front_geometry` flies the object's own shape and
  length). The stack ends at the top stage, or at its interstage, whose top ⌀ is
  now derived from the object's base. The headline reports stack + object, and
  `fairing_fit` checks only against a declared fairing. One rule,
  `booster_schematic.exposed_front_object`, serves the schematic and the 3-D
  export.
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

---

# Part IV — One handoff at separation

Status: **approved 2026-09-30; Phases 0–2 built (boost nose held, §19a); Phase 3 revised, readings under way.** Parts I–III made the body
honest in what it shows and what it owns. Part IV makes the moment of
separation a single, explicit step, in both kinds of vehicle.

## 16. The principle

A run is composed from two hardware files, a booster and a reentry object, and
there is **always a handoff from one to the other at separation**:

- **Separating:** the object as stored is what flies on.
- **Non-separating (`body_reenters`):** the object is populated with the shape
  of what actually reenters — the last stage (for a single-stage missile, the
  whole booster), **fins included** — and that is what flies on.

Either way the handoff produces **the object as flown**, and every
reentry-phase consumer reads only that: drag, lift, trim, heating, reports.
None reads the booster to rebuild the body's shape for itself. The same
handoff hands each spent piece — empty stage, fairing, strap-on casings — to
the ground.

The work is writing in two directions, both **in the run, never in the files**:

- **forward**, booster → object as flown, at separation;
- **back**, the reentry results → the run record and report, and the editor's
  read-only "from booster" fields, which show the same handed-off values.

## 17. Why

The failures this part closes are one disease: each reentry-phase consumer
decided for itself where the body's shape came from, and several chose wrong.

| Symptom | Where |
|---|---|
| The whole booster flown as an object on top of itself (574 → 137 km) | `compose_loadout`, fixed in Part III |
| Stored copies of the booster's numbers in body files (Scud-B, Al Hussein: 1198/1334 kg, 0.84 m, 11.25/12.0 m), silently overridden | editor Save; two run paths that write the flown object back into `node.ro` (`analysis.py`, `trajectory.py`); an old migration; `_export_ro` falling back to the flown object |
| Whole-stage length taken as the nose length | `heating_by_location` and the windward-flank screen (fixed 381e2c0); still in `_boost_front_geometry` during boost |
| Multi-stage body CG summed over every stage | `grid_fin_sizing.estimate_cg` |
| A body object flown from an entry condition as if it separated | `entry_carrier` |
| A body object on a separating booster: 15.5 km, no warning (β = 0 "derive" becomes infinite drag) | no pairing check exists |
| Body and spent stage flown by different code (different drag, ground, precision) | main `_eom` vs `integrate_debris` |

## 18. Decisions (user, 2026-09-30)

1. **Files store only what the body adds.** A body's object file keeps nose
   shape, `body_nose_length_m`, nose radius, `payload_kg`, heat protection,
   heating locations, any entered β / L/D (0 = derive) and provenance.
   `mass_kg`, `diameter_m` and `length_m` are stored as **0 = from booster**
   (`mass_kg` stays in the file: it is a required key). Nothing about the
   booster is stored twice; the record of what flew belongs to the run.
2. **Pairing rule.** An object that takes its size from the booster (mass 0,
   or β 0 = derive) on a booster that **separates** is **refused**, naming the
   field. An object that stores its own size on a booster whose last stage
   **reenters** flies, and the run **reports** that the stored size is
   ignored — visible, not silent.
3. **Fins remain** on the handed-off body: the last stage's own fin and
   grid-fin fields (every fin, for a single stage). A flight-plan option to
   drop them comes later (timing is plan data; the fins stay booster hardware).
4. **Spent stages** go through the same handoff and the same flight code as the
   body. Where a tumbling stage lands matters more, for now, than its heating.
5. **Fins and tumbling drag.** Fins travel with a spent stage. How much drag
   the stage has depends on its attitude, which is set by the stage itself —
   see §18a. Nothing is added for fins without a cited method.
6. **Benchmark** for a stage's impact point: the user is sourcing it.

## 18a. How a spent stage falls (user's note, 2026-09-30)

The user's note *Do spent rocket stages tumble randomly?* (19 references)
sets the physics for Phase 3. In short:

- **A spent stage does not tumble randomly.** Outside the atmosphere it
  rotates in a plane, end over end (Shuttle external tank, Ariane 5 core
  stage, Ares I-X first stage; a free long body goes to flat spin). Once
  dynamic pressure builds the tumble is normally arrested and the stage
  oscillates about a **trim attitude set by its centre of gravity relative to
  its centre of pressure** (Tobak & Peterson, NASA TR R-203; Ares I-X
  pre-flight Monte Carlo and flight, Tartabini & Starr 2011; the AFGL reentry
  handbook, AFGL-TR-78-0019, which tabulates trim angle and drag for cylinders
  at Mach 2–8 against CG offset). Arrest is usual, not guaranteed.
- **Random tumbling is a convention**, used by range safety (FAA AC
  450.115-1A) and debris codes, not something an intact stage has been seen
  to do. It stays the nominal case, with a **two-sided band**: about 1.6×
  (broadside: CG near mid-length, flat spin, or a tumble across the flight
  path) down to about 0.3× (markedly tail-heavy) and 0.17× (end-on, L/D 10).
  The in-plane tumble, 0.76×, lies inside the band, not at its edge.
- **Fins decide the mode.** If the separated stage is still statically
  stable nose-first, it does not tumble: it flies end-on. If not, fins still
  shift the trim angle. Thrusty already computes CG, CP and static margin
  with fins (`grid_fin_sizing`, `trim_gate`); Phase 3 applies them to the
  spent stage.
- **Intact stage and fragments are separate cases.** The trim argument is for
  the intact stage; random tumbling is what the tables were written for
  after breakup. Lift of a trimmed, non-rolling stage (lift-to-drag of order
  1 near 135°) and breakup are carried as stated uncertainties, not modelled.

**Checked here.** Klett's (Sandia SC-RR-64-2141) random and in-plane averages
— 0.393 + 0.178·D/L and 0.283 + 0.303·D/L, on area L·D — are exactly the
orientation averages of his fixed-angle formula 0.667 sin³θ + 0.714 (D/L)
|cos θ|³ (integrated here to three decimals), and the note's ratios for L/D
5–12 reproduce. Hoerner's fixed-orientation pieces give the same fixed-angle
law (eq. 44 ⅔ broadside; the cross-flow law sin³α, eqs. 23 and 48). So the
averaging is arithmetic on cited formulas, not a new model.

**Hoerner, read 2026-09-30** (*Fluid-Dynamic Drag*, 1965; Thrusty's Drive
archive): the constants in `tumbling_cylinder_beta` are transcribed and
assigned correctly (eq. 41 1.84 − 0.76/M², above M ≈ 3; eq. 44 ⅔ broadside;
0.89 end face, above M ≈ 5). Not from Hoerner: the ½ average of the two
orientations and the 1.2 floor below M 3 (which steps to 1.756 at M 3). He has
no tumbling-cylinder, tumbling-fin or tumbling-plate data. His one
orientation-averaged measurement is rotating cubes in a ballistic range (Fig.
17, p. 16-14): C_D ≈ 0.75 subsonic rising to 1.11 above M ≈ 1.2, on 1.5 l²,
which he says represents "average conditions between all positions
statistically possible". That is a validation case for the averaging.

**Klett, read from primary 2026-09-30** (Sandia SC-RR-64-2141, December 1964;
the user's copy, OSTI 4630398). Reference area L·D throughout. Continuum
flow, modified Newtonian with local pressure p∞ + q∞(2 − K) cos²φ, K the
density ratio across a normal shock: side-on C_D = ⅔(2 − K) (eq. 21); end-on
0.714 (D/L)(2 − K) (eq. 23, from a face pressure of 0.909 of stagnation, after
Stoney & Swanson); at angle θ, C_D = C_D,side sin³θ + C_D,end cos³θ (eq. 28,
the axial and transverse drags added as vectors); end-over-end tumbling
(0.283 + 0.303 D/L)(2 − K) (eq. 32); random tumbling (0.393 + 0.178 D/L)(2 − K)
(eq. 36). Free-molecular: side-on 2, end-on 1.57 D/L, random 1.57 + 0.785 D/L
(eq. 12). A tumble in a plane perpendicular to the trajectory takes the
side-on value (p. 9). Stated range: Mach 10–30, laminar continuum above
roughly 70,000 ft; Klett gives no drag for the transition regime, only its
limits. (2 − K) for air at high Mach is ≈ 1.83, Hoerner's C_p• = 1.84 − 0.76/M²
in the limit; and Klett's 0.909 end face sits beside Hoerner's 0.89. The two
sources agree.

**Not verified; do not use.** The AFGL reentry handbook the note cites
(AFGL-TR-78-0019) may not be a real document (user, 2026-09-30). Everything
in the note that rests on it is withdrawn until a real source is found: the
table of trim angle and drag against CG offset, and the cross-check that
Klett's fixed-angle formula runs 10–17% low at 118° and 138°. The note's
other references are unread. One consequence: in Klett's own modified
Newtonian model a plain cylinder's cross-flow force acts at mid-length at
every angle, so it predicts no trim between end-on and broadside; any
intermediate trim needs a source that models it.

## 19. Phases

**Phase 0 — the invariants, as tests (`test_handoff.py`).** A body flies
identically with its stored size zeroed (true today, pinned). Mass after
separation is what the handoff says: a body carries the last stage's burnout
mass plus `payload_kg`; a separating object carries its own `mass_kg`. The
pairing rule of §18.2, marked expected-to-fail until Phase 2.

**Phase 1 — one handoff.** A core function builds the object as flown at
separation: mass, diameter, length, nose length, the last stage's fins, CG
from the last stage only, the β(Mach) and L/D(Mach) tables, and the trim
result (angle of attack or tumbling). `effective_ro` becomes a view of it.
Every reentry-phase consumer reads only it; the write-backs into stored
objects stop; `_boost_front_geometry`, `estimate_cg` and `entry_carrier` are
corrected. The run result gains `handoff`: what was handed off, from where,
and any notices. Trajectories do not move, except a multi-stage body's (its
CG).

**Phase 2 — files store only what the body adds.** The pairing rule is
enforced. The editor shows the booster's numbers and saves 0; export writes
the stored object. The three shipped body files (Scud-B, Al Hussein, generic
body missile warheads) are cleaned once and their recorded load results
regenerated on purpose. `upgrade_ro_dict` cannot do this — a file does not
know it is a body — so user files are handled by the pairing report instead.

**Phase 3 — spent pieces through the same handoff and flight code.** Each
empty stage, the fairing and the strap-on casings fly with their own mass,
dimensions and fins, the terrain model and the main flight's integration
tolerance. The debris release clock starts at `booster_core_delay_s`, as
every other stage clock does.

Attitude and drag (revised 2026-09-30, user): the stage's attitude comes from
its own moment balance, using the two-station all-angle build-up Thrusty
already cites for the trim gate — Allen & Perkins (NACA Rep. 1048), Jorgensen
(NASA TR R-474; TN D-7228, "angles of attack from 0° to 180°"), stations per
Simon & Blake (AIAA 99-4258): a potential normal force (∝ sin 2α) acting near
the front, and a viscous crossflow (∝ sin²α) acting at the planform
centroid, fins included. With two stations the balance point moves with
angle, so the trim angle follows the CG:

    tan α_trim = (x_cg − x_front)·C_Nα,pot ÷ [(x_centroid − x_cg)·η·C_dn·A_p/A_r]

— broadside when the CG sits at the planform centroid, toward end-on as it
moves away. That is the behaviour the withdrawn handbook table described,
from sources in hand. Klett's one-station Newtonian model cannot produce it.
For each spent stage: its own empty CG (engines aft) and planform with fins;
its trim angle; its drag at that attitude from the same build-up
(C_D = C_N sin α + C_A cos α), at every Mach number; Klett as the check at
Mach ≥ 10 (the build-up's C_dn = 1.2 against Klett's ⅔(2 − K) ≈ 1.23). Random
tumbling is reported alongside as the other end of the band, because whether
a tumble is arrested is dynamic, not settled by a static balance; each stage
lands as a stretch of ground. This also replaces the small-angle static
margin for the stability decision.

To read from primary before coding: how TN D-7228 treats α > 90° (base
leading); the potential term for a stage whose front is a flat bulkhead or an
open interstage, not a nose; fins at high angle; Tobak & Peterson (NASA TR
R-203) on the arrest of a tumble.

**Every debris impact point moves, on purpose**; before-and-after impact
points are reported for each shipped vehicle.

### 19c. Readings for Phase 3 (2026-09-30)

**Jorgensen, NASA TN D-6996 (1973), the 0–180° method** (user's copy). Its
equations (1)–(5) confirm TR R-474's, with A (not A_r) as reference area, d
as the moment length, and the minus sign in (5) on the first bracket only.
For a flat face leading, C_A ≈ C_p,stag (Fig. 7: 1.66 at M 2, 1.755 at M 3,
1.79 at M 4, 1.83 at M 10), plus skin friction and Gabeaud base pressure
(eq. 11); no transonic or subsonic C_A procedure.

**The measured flat-faced cylinder overturns the two-station assumption for
this shape.** Jernell's data (NASA TM X-1658, via D-6996 Figs. 10 and 16a;
checked against the page images): bodies 1 and 2, cylinders flat at both
ends, ℓ/d 6 and 8, M 2.86, Re_d 1.25×10⁵. Measured centre of pressure from the
leading face: about 0.25ℓ at 5°, 0.4ℓ at 10°, 0.46–0.48ℓ at 15–20°, 0.47–0.50ℓ
from 25° to about 90° (corrected from Jernell's own Fig. 9, below); measured
C_m about mid-length ≈ 0 throughout. Jorgensen's method, with
its potential force at the leading face, computes C_m peaks of +2.4 and +3.4
and a CP well forward (0.37–0.43ℓ at 20–50°), which the data do not show.
Measured C_N is within about 10% of computed. No measurements above 95° for
these bodies; the curve is taken as symmetric end for end (they are flat at
both ends), which is an inference.

Consequence: for a plain flat-ended cylinder the CP sits at mid-length except
within about 20° of end-on, where it moves toward the leading face. The trim
is where the CP meets the CG: a stage whose CG is a fraction g of its length
from the leading face, with 0.25 < g < 0.47, trims about 10–20° off end-on
with that face leading; a CG near mid-length gives no preferred attitude
(broadside or flat spin). An engine-heavy stage (CG aft) would fall base
first, about 10–20° off end-on, at close to end-on drag — far less drag than
random tumbling. This is from one Mach number, finless, flat both ends; it
disagrees with the withdrawn handbook's trims of 105–138°.

**Dynamics** (Tobak & Peterson TR R-203; Garber 1959; Regan & Anandakrishnan
1993 Ch. 12; Norling 1962): only Tobak & Peterson decide settle-or-tumble —
a nonlinear, large-angle, undamped analysis with arrest read from their Fig. 2
against the initial tumble rate — for one stable trim, a sine-law moment, and
entry from outside the atmosphere. The others are small-angle envelope laws
(∝ q^(−1/4)). So settling is reported as a labelled estimate, not used to
choose the band's end.

**Decision (user, 2026-09-30): finned stages are reported as a band only** —
trim unknown to random tumbling — until a source gives fin forces beyond
Jorgensen's tested 58°. A finless stage gets the trim from the measured
centre-of-pressure curve. Jernell's report itself (NASA TM X-1658, Mach
1.50–2.86, 0–180°) is now in hand and being read for the full Mach range.

**Jernell, NASA TM X-1658 (1968), read from the user's copy.** Langley
Unitary Plan, M 1.50, 1.90, 2.36, 2.86, Re 1.0×10⁶/ft, d = 1.5 in, moment
centre at mid-length, trips fore and aft, straight and 45°-bent stings (the
report blames its discontinuities on support interference). No stated
accuracy. The flat-ended cylinders were tested only to about 100°; only the
cone- and ogive-cylinders go to 185°. Values read from a 150 dpi scan
(C_N ±0.4, C_A ±0.03, C_m ±0.4).
- Centre of pressure from the leading face (Fig. 9): M 1.50, 0.11 at 5.5°,
  0.18 at 10°, 0.35–0.38 at 15°, 0.42 at 20°, 0.44–0.47 at 30–45°, 0.47–0.49
  at 60–85°; M 2.86, 0.24–0.27 at 5.5°, 0.38–0.41 at 10°, 0.45 at 15°, 0.48 at
  20°, 0.49–0.50 at 25–90°. Near end-on the CP moves toward the leading face
  at every Mach number, more strongly at lower Mach.
- Symmetry end for end: consistent between 80° and 100° within reading
  precision; not tested beyond. Supporting it: on the cone- and
  ogive-cylinders flying base first, the CP moves toward the leading flat base
  near end-on (0.75–0.8ℓ at 170°, 0.88ℓ at 180°, M 2.86).
- Axial force: face first 1.62–1.73 (≈ C_p,stag); base first −1.5 to −1.65.
- Drag averaged from these data over random orientation (mirrored beyond 90°,
  an inference), cross-section reference, ℓ/d 6: 7.3 (M 1.5), 7.2 (1.9),
  7.0 (2.36), 6.6 (2.86) — falling toward Klett's hypersonic 5.9. At a trim of
  5–20° off end-on it is 1.7–2.6: random tumbling has three to four times the
  drag of a trimmed stage.

### 19d. Phase 3 as built so far (2026-09-30)

- **Release time.** The spent-stage walk (and the orbital-lifetime walk)
  started its clock at 0; every other stage clock starts at
  `booster_core_delay_s`. With strap-ons lit first, every spent stage left
  from the wrong point of the flight. Fixed; tested on Strypi VIII R with a
  1 s core delay. No shipped vehicle sets a delay, so no shipped result moves.
- **Precision and ground.** `integrate_debris` now runs to the main ballistic
  flight's tolerances (rtol 1e-8, atol 1e-6 m, max_step 5 s; it was rtol 1e-5,
  atol 10 m, no step limit) and lands on the terrain model when the run uses
  it. Shipped debris impact points move 0–2.7 km (mostly 0.1–0.6 km; largest,
  Minotaur-IV's third stage, 2.7 km): that was the old integration error. Main
  trajectories are unchanged. Runtime about doubles for debris, still under a
  second per vehicle; the suite takes about 20 s longer.
- **Drag by attitude (2026-10-01).** `spent_stage_aero.py` builds three
  C_D·A(Mach) curves per spent stage or strap-on casing from Jernell's
  flat-ended cylinder (`data/aero/jernell_1968_flat_cylinders.csv`, l/d 6,
  Mach 1.50–2.86; C_N scaled by l/d) and Klett's Newtonian cylinder above:
  random tumbling (sin α weight; Klett eq. 36 from Mach 10, linear between),
  end over end (uniform in α; Klett eq. 32), and the trim where Jernell's
  Fig. 9 centre of pressure meets the empty CG. A liquid stage's CG puts the
  engine (κ_E/(1+κ_E) of the dry mass, Shu et al. 2020: 0.25 lower, 0.12
  upper) at the base and spreads the rest evenly: CG 0.40 or 0.45 of the
  length from the base, so it trims base first, 18° off end-on at Mach 1.5
  and 12° at 2.86 (lower stage). A solid stage or casing puts its nozzle at
  the base with the share given by the ratio of Romaniw's (2013, Appendix
  A) case, insulation and nozzle fits in motor thrust — 28% of the empty
  mass at 0.3 MN, 14% at 10 MN, peak thrust when the file has one — so AUR
  stage 1's CG is 0.36 from the base and it trims 15° off end-on at Mach
  1.5. Only the ratio is used: the absolute fits give 815 kg for AUR stage
  1's 454 kg (user, 2026-10-01: "the data isn't ideal but the ratios might
  be ok"). The MER folder in the Drive (18 papers) has no other case/nozzle
  split; Zandbergen 2026 Fig. 1 gives the Shuttle SRB's "SRM hardware,
  including the casing, nozzle, thermal insulation, and ignition system" as
  one 66 t number, and Rohrschneider's §6 is liquid-engine constants. A
  solid with no thrust in its file, and a finned stage (no fin forces
  beyond 58°), have no trim and are flown tumbling only. The fairing keeps
  the old β path.
- **The band and the one reported point.** `trajectory._fly_band` flies a
  piece tumbling randomly and, when it has one, trimmed, and reports the
  great-circle midpoint of the two impacts with the mean time and speed;
  both ends, the climb and the assumptions ride on the milestone as
  `impact_band`. With no trim the tumbling point is reported.
- **The climb leg, and where a 44 km band came from.** Flown trimmed or
  tumbling from separation, AUR's first stage (then entered as a liquid;
  separates at 38 km, 1.86 km/s, climbs to 157 km) gave a 44 km band; by
  switching the trimmed drag on over parts of the fall, 41 km of it was
  found to accrue on the climb (Mach 3–6, where the trim is only held at
  its Mach 2.86 value) and 2.5 km on the descent. A stage cannot trim on
  the climb: it leaves front-first, which is statically unstable (the CP
  sits near the leading face, Jernell Fig. 9), and the swing envelope grows
  as q falls (Tobak & Peterson eq. 33, Regan 13.56; both ∝ q^(−1/4)). No
  source treats arrest on a climb; the inference is stated in the run's
  notes. So a piece still climbing at separation is flown end over end
  (Klett's constant-rate case) to apogee and the band is flown from there.
  Shahab-3's stage-1 band went 17 → 8 km; the AUR case 44 → 2.5 km before
  its file was corrected.
- **AUR corrected (user, 2026-10-01).** Both stages are solid; stage 1 is a
  double-anchor (regressive) grain with 290 kN peak thrust. The shipped file
  had both as liquid. Main range at 33°N 44°E, az 60°: 4554 → 4133 km (the
  regressive curve at 290 kN peak gives 0.75 × 290 × 54 = 11.7 MN·s against
  12.4 MN·s from the file's 280 s Isp; the 290 kN is the user's number and
  stands). The damped-glide smoke test pins its carrier at the old
  constant-thrust stack, as it already pins mass and handoff altitude; the
  legacy-load golden was regenerated for this one file.
- **Effect on shipped vehicles** (33°N 44°E, az 60°, against 857cc42):
  main trajectories unchanged; debris impact points move 0–6 km, except
  Minotaur-IV's third stage, 25 km at 19,400 km downrange. Bands now:
  AUR 2 / 4 km, Generic ICBM 4 / 7 km, Shahab-3 8 km, Minotaur-IV 0.2 / 4 /
  16 km, Taepodong-I 5 km (stage 2), Taepodong-II 3 / 6 km (stages 2, 3),
  STARS-1 0 / 0.6 / 1 km, Strypi upper stages 0.6 km; finned stages 0. All
  13 vehicles run in 7 s against 5 s.
- **Validation debt.** Romaniw's ratio, Shu's κ_E as a CG, the climb-leg
  inference, and the end-for-end mirror are each a model with no
  Thrusty-collected check behind it; `TODO.md` now lists them with what
  data would test each.
- Tests: `test_spent_stage_aero.py` (the data averages, Klett's equations on
  his reference area, the joins, trim angles, the stage kinds, the band and
  its midpoint, the climb leg, the β path).
- Still open: a solid stage's CG (needs a cited nozzle mass); the
  settle-or-tumble estimate (Tobak & Peterson Fig. 2) as a labelled note;
  the stage-impact benchmark (user).

### 19e. Settle or tumble: the swing (2026-10-01)

The user's point: the tumble rate is not an input to look up, it follows
from the stage's mass, geometry and the energy the air puts into it. Built
as `spent_stage_aero.attitude_model` (inertia; the measured moment about
the CG, C_N times the lever from Jernell's centre of pressure; its
potential) and `trajectory._attitude_verdict` (the planar, undamped swing
followed along the flown climb and fall, for disturbances of ±0.5°, ±2°,
±10° from front-first at separation).

What it shows on shipped vehicles (33°N 44°E, az 60°):

| Stage | Spin leaving the atmosphere | On the way down | Reported |
|---|---|---|---|
| Shahab-3 stage 1 (4.8 t, 16.5 m, sep 51 km) | 19–39°/s | stops overturning at 55–75 km, before any drag | trimmed point (moves 4 km) |
| AUR stage 1 (454 kg, 5 m, sep 40 km) | 241–273°/s | some cases stop near 40 km, most never | midpoint of end-over-end and trimmed, ±1 km |
| Minotaur-IV stage 1 | 163–192°/s | unclear | midpoint (ends within 0.1 km) |
| Strypi VIII R strap-on casings (released at 1 km) | about 1000°/s | still tumbling at peak q | end-over-end point |
| every stage released above the air (upper stages; Generic ICBM stage 1 at 76 km) | under 1°/s from the air | — | midpoint, ± on the timeline row |

Rule (user, 2026-10-01, replacing "always the midpoint"): report the end
the physics picks — trimmed when no case can overturn after 5% of the
fall's drag impulse has accrued, end over end when every case is still
overturning at peak dynamic pressure — and the midpoint with its
half-width otherwise. A stage the air did not turn over keeps the
midpoint: its rate is the separation mechanism's, unknown. A stage the air
did turn over tumbles in its flight plane, so its tumbling end is flown
end over end, not random.

What a coupled check showed (scratch, drag taken at the swinging angle):
AUR stage 1 feels 3.1–3.2 m² when it keeps tumbling, against 3.3 end over
end and 4.1 random — the end-over-end curve is the right tumbling drag.
Shahab-3 stage 1, settled, feels 3.4–7.3 m² against 3.3–3.7 trimmed,
because the undamped swing left after arrest is large when the spin was
high; its impact lies 0.3–4.2 km beyond the trimmed point toward the
tumbling one (8 km away). Real damping shrinks that; no source gives it.
So the trimmed point is the likelier end but can be short by up to half
the old band. Listed in `TODO.md` item 10.

Cost: all 13 vehicles 8 s (was 7); suite 143 s (was 101).

### 19f. Two checks on stage ends and fins, and Ares I-X (2026-10-01)

**Finned stages, empty, front-first.** Moment about the empty CG at 10–20°
from Jernell's body force and centre of pressure against the fin normal
force from the existing build-up (`glider_ld.whole_booster_LD`), Mach 1.5
and 2.86:

| Stage | Fins' restoring moment ÷ body's overturning moment | Front-first |
|---|---|---|
| Strypi VIII R stage 1 (both files) | 1.3–1.9 | stable, +0.4 to +0.7 cal |
| Strypi VII R stage 1 | 1.0–1.4 | marginal to stable |
| No-dong stage 1 | 0.45–1.05 | unstable (marginal at 20°, Mach 2.86) |
| Taepodong-I stage 1 | 0.30–0.70 | unstable |
| Taepodong-II stage 1 | 0.44–0.85 | unstable |
| STARS-1 stage 1 | — | grid fins with no dimensions in the file |

The body force at these angles is read to ±0.4 in C_N and scaled by l/d
from an l/d 6 cylinder, so the ratios are rough. Reading: the Strypi first
stages probably fly on front-first like an arrow and are flown wrongly as
tumbling today; the Scud-family first stages turn over like bare ones, and
only then do fin forces at large angle matter. Not built.

**Stage ends.** Jernell's table perturbed and every trimmed stage reflown:

| Change | Reported point moves | Trimmed end moves |
|---|---|---|
| End-on drag ±20% | 0–2 km (Minotaur-IV stage 3: 8–10 km at 19,400 km) | 0–4 km (15–18 km) |
| Centre of pressure 0.05 L toward the leading face | 0–4 km | 0–8 km |
| Centre of pressure 0.05 L toward mid-length | 0–1 km | 0–2 km |

The centre of pressure near end-on matters more than the end-on drag, and
only in the direction that makes the stage trim closer to end-on; liquid
upper stages (CG 0.45) are the sensitive ones. A real stage's ends (open
interstage, nozzle) would enter here.

**Ares I-X** (Tartabini & Starr 2011, read 2026-10-01). The upper-stage
simulator, unstable in forward flight, began tumbling within seconds of
separation at high dynamic pressure, in more than 99% of pre-flight cases
and in flight; at a tenth of that dynamic pressure it would not have for
about 40 s. That is the climb-leg inference, observed, and the "no spin
from the air" case as well. The first stage was given a tumble by motors,
on purpose, to keep it from trimming nose-first; in flight it came in
tail-first (151° at max-q). Pre-flight Monte Carlo: nose-first 4%,
broadside 59%, tail-first 37%, set mainly by CG and centre-of-pressure
position, the centre of pressure being "difficult to characterize" in
tumbling flight. So a six-degree-of-freedom simulation with a wind-tunnel
database still could not call the attitude; Thrusty's "unclear → midpoint"
is the honest equivalent. Their footprints (first stage 32.7 × 9.2 nmi,
121.4 nmi from the pad) are a possible benchmark once a booster file
exists. `MISSING_DOCS.md` lists the papers it points to.

**Phase 4 — later.** A flight-plan option to drop the fins.

## 19a. Phase 1 as built (2026-09-30)

- `booster_models.hand_off(params, stored)` is the record of the handoff: the
  object as flown (still built by `effective_ro`, the per-step fast path),
  the airframe, where each size came from, the fins, and notices. The run
  result carries it as `result['handoff']`, and a size stored in a body's
  object file that the run ignores is reported there.
- `booster_models.reentering_airframe(params)`: the stage that reenters,
  standing alone. A single-stage missile is its own airframe (returned as
  is, so every shipped vehicle is byte-identical); for a multi-stage body it
  is the last stage alone, with the run's object and payload bookkeeping. The
  trim gate judges it, so a multi-stage body's CG, centre of pressure and
  fins are its last stage's. `grid_fin_sizing.estimate_cg` places a body's
  reentry CG within the last stage too (the fuelled, liftoff CG keeps the
  whole stack).
- The equilibrium-glide switch (`trajectory.py`) and
  `analysis.with_bank_schedule` change plan data on the object the stack
  holds; they used to install the object as flown in its place. Both worked
  on run-local copies, so no file was ever written, and results are
  unchanged.
- Moved to Phase 2, where the pairing rule lives: `entry_carrier` refusing an
  object sized by the booster.
- **Held for the user's decision: the boost nose.** During boost,
  `_boost_front_geometry` takes a body's nose length to be the object as
  flown's `length_m` — the whole last stage (11.25 m for Scud-B, a nose of
  fineness 13, clamped to 10). Using `body_nose_length_m` (0 = unset takes the
  function's existing fineness-3 default) moves shipped ranges: Scud-B 250.6
  → 241.1 km (−3.8%), Al Hussein 597.8 → 583.9 km (−2.3%), generic body
  missile 223.7 → 221.3 km (−1.1%) (launch 33° N 44° E, azimuth 45°).

Checked: all 13 shipped vehicles fly byte-identical to the previous commit
(position and mass histories, range, every debris impact point).

## 19b. Phase 2 as built (2026-09-30)

- `booster_models.check_pairing`, at the start of every integration: an
  object with `mass_kg` 0 or `beta_kg_m2` 0 on a booster that separates it, or
  flown from a stated entry condition (`entry_carrier` separates), is refused
  with a message naming the field. `test_body_beta_derive`'s separating β 0
  case, which used to fly with infinite drag, is now that refusal.
- The three shipped body object files (Scud-B, Al Hussein, generic body
  missile) store 0 for mass, diameter and length; their notes record the
  copies removed (1198/1334/988 kg, 0.84/0.84/1.1 m, 11.25/12.0/9.18 m). Their
  recorded load results were regenerated for exactly those fields and the
  provenance text, nothing else (asserted when regenerating). A test holds
  every shipped body object to it.
- The object editor saves 0 for a body's mass, diameter and length (it shows
  the booster's). An automatic nose radius, shown as the screening default,
  is saved as 0 (not given) unless the user changes it, so a bluntness
  heuristic never becomes a stored measurement; shown, it follows the
  diameter that flies. A body's biconic is checked against its nose taper,
  not the whole stage, and saves without a booster to show.
- A new booster-default body object is seeded with zeros; export and the
  one-time migration write the object as stored, never as flown. The 3-D
  export no longer draws a body's object beside the stack (the 2-D schematic
  never did).

Checked: all 13 shipped vehicles fly byte-identical to Phase 1.

Not done here, noted: `ro_xlsx` still writes and reads the derived
`separation_mode` (a four-inputs slip outside this part), and CLAUDE.md's
"the reentry object owns its mass" does not yet say that a body's object
stores 0 for it.

## 20. Acceptance (Part IV)

- No reentry-phase consumer reads the booster for the body's shape; a test
  enumerates them.
- No path writes booster numbers into a stored object.
- A body flies identically before and after Phase 2's file cleaning.
- The pairing rule holds in both directions, with its message and report.
- Spent pieces and the reentering object share one flight code path.
