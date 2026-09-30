# Thrusty — Methods

This document is the technical reference for Thrusty's models and algorithms.
It complements the in-repo [`README.md`](README.md) (overview, source-file
guide, quick-start). Each section gives the governing equation(s), a brief
description of the implementation, and citations to primary sources where one
exists. Code is referenced by file and symbol name (e.g. `trajectory.py:
integrate_trajectory`) rather than line number, so the references stay valid
as the source evolves.

Conventions:

- All lengths are metres, masses kilograms, times seconds, angles radians
  internally (degrees on the GUI surface).
- `g₀ = 9.80665 m/s²` is *standard gravity* (BIPM-defined nominal
  acceleration of free fall at Earth's surface), used as the
  definitional constant in propulsion expressions such as
  `T = I_sp · g₀ · ṁ`. This is distinct from the local gravitational
  acceleration `g(r)` from the J₂ field (Section 3), which varies
  with position.
- The Earth gravitational parameter `μ = GM = 3.986004418×10¹⁴ m³/s²` and
  equatorial radius `R_E = 6 378 137 m` are WGS-84 values.

> **Lineage and provenance.** Thrusty follows the structure of Geoffrey
> Forden's MATLAB tool (Science & Global Security 15, 2007). That program
> reached the author in MATLAB-encrypted form; its file structure and the
> paper defined the module boundaries and the Table 3 validation targets, and
> every routine here was written independently from the cited sources. No
> Forden code is included. The encrypted files formerly under
> `archive/matlab` were removed on 2026-09-18.

> **Draft status note.** Specific equation, section, and figure numbers
> for Chin (1961), *Missile Configuration Design* appearing in Section
> 8 are taken from source-code docstrings; they have not been
> independently re-verified against the PDF in the current editing
> environment. Citations to Tracy & Wright 2020, Acton 2015, Schilling
> 2009, Sutton & Graves 1971, Forden 2007, Anderson 2006, and the NACA
> reports are verified to publication level. Readers preparing the
> document for publication should spot-check the Chin equation numbers
> before quoting.

---

## Table of contents

1. [Overview and modelling approach](#1-overview-and-modelling-approach)
2. [Coordinate systems and reference frames](#2-coordinate-systems-and-reference-frames)
3. [Gravity model](#3-gravity-model)
4. [Atmosphere](#4-atmosphere)
5. [Equations of motion](#5-equations-of-motion)
6. [Mass and staging](#6-mass-and-staging)
7. [Propulsion](#7-propulsion)
8. [Aerodynamics](#8-aerodynamics)
9. [Guidance laws](#9-guidance-laws)
10. [Range optimisation and targeting](#10-range-optimisation-and-targeting)
11. [SLV performance estimation](#11-slv-performance-estimation)
12. [Hypersonic glide vehicles](#12-hypersonic-glide-vehicles)
13. [Stagnation heating](#13-stagnation-heating)
14. [Outputs, events, and milestones](#14-outputs-events-and-milestones)
15. [Validation and built-in missile definitions](#15-validation-and-built-in-missile-definitions)
16. [References](#16-references)

---

## 1. Overview and modelling approach

Thrusty is a three-degree-of-freedom (3-DOF) trajectory simulator. The state
vector is the missile centre of mass position and velocity in an Earth-Centred
Earth-Fixed (ECEF) frame:

```
y(t) = [x, y, z, ẋ, ẏ, ż]ᵀ
```

The single ODE integrated by `integrate_trajectory` (`trajectory.py`) is

```
ẏ = [v,  g_ECEF(r) + a_drag + a_thrust + a_Coriolis + a_centrifugal]
```

with each term derived in the sections below.

**Operating concept — three phases.** A flight separates into three regimes,
each governed by a distinct set of inputs. (1) **Boost (up):** powered ascent,
set by the booster's *shape* (drag — Section 8), its *motor* (thrust / `I_sp` /
burn — Section 7), and its *trajectory* (the guidance flight plan — Section 9).
(2) **Free-fall (coast):** the exo-atmospheric ballistic arc after burnout —
pure gravitational dynamics fixed by the burnout state (speed, flight-path angle,
position), with drag zeroed above 120 km — which either closes into an orbit
(Section 11) or falls back toward the surface. (3) **Reentry (down):**
atmospheric descent of the reentry object, governed by its ballistic coefficient
β (and, when maneuvering, its L/D — Section 8.10) and the aerothermal load. The
same drag term is evaluated *shape-resolved* (`C_d·A`) during boost and *lumped*
(`β = m/(C_d·A)`) during reentry (Section 8.8) — matching what is known about the
object in each phase.

The 3-DOF formulation captures translational dynamics only — attitude is not a
state variable but is *prescribed* by the guidance law (Section 9). This is
the standard approximation for preliminary missile and launch-vehicle analysis,
where pitch-program scheduling rather than full rigid-body dynamics determines
the trajectory shape.

Numerical integration uses `scipy.integrate.solve_ivp` with the explicit
adaptive Runge–Kutta 4(5) method (RK45) and event detection for ground impact,
apogee, milestone-altitude crossings, and orbital-energy cutoff. The original
Forden tool ([Forden 2007](#16-references)) used forward Euler; Thrusty's
adaptive RK45 is strictly more accurate for the same time-step budget, at the
cost of variable step size.

The design intent is *preliminary aerothermal and trajectory analysis* —
the kind of figure-of-merit work used in arms-control verification, threat
modelling, and reentry-vehicle scoping. It is **not** a 6-DOF flight dynamics
simulator and does not replace tools such as POST, OTIS, or ASTOS for vehicle
design.

### 1.1 Design principles

Several recurring choices give the code a particular character worth
flagging up front:

- **Mean-conditions defaults, extension hooks for accuracy.** Every
  modelling choice that has a reasonable "mean" or "conservative"
  value uses that value as the default, but exposes a configuration
  hook for users who need higher fidelity for a specific scenario.
  The atmosphere model (Section 4.1) uses NRLMSISE-00 at mean solar
  conditions by default, with `configure_atmosphere()` accepting real
  date / solar / geomagnetic inputs for cases tied to specific
  flights. Per-stage guidance overrides (Section 9.4) let advanced
  users replicate documented pitch programs without disturbing the
  simple case. The `glider_guidance` dropdown (Section 12) exposes
  four glide laws of increasing physical fidelity. The RV library
  (`ro_library/*.json`) provides a clean extension point for adding
  user-defined reentry vehicles, and the JSON missile-save format
  (`booster_to_dict` / `booster_from_dict`) gives users a way to
  share, version, and refine their own missile definitions. The
  pattern is consistent: keep the out-of-box case simple and
  reproducible, but never bake in an assumption that prevents a more
  careful user from improving it.

- **Closed-form first, table second, integration third.** Where a
  closed-form expression captures the physics (Chin's cone wave-drag
  formula, Tsiolkovsky's ΔV, vis-viva at perigee, Wheelon's optimal
  angle), it is preferred for both transparency and speed. Tabulated
  data (NACA TN 4201 wave drag, Chin Fig. 3-15 base pressure) is used
  where no closed form is available. Full numerical integration of
  the EOM is used only when the integrated trajectory itself is what
  is wanted.

- **Honest physics with flagged simplifications.** Where a
  simplification is made deliberately (power-off base drag during
  boost, no booster–core base-drag interaction, no rotational
  dynamics, no angle-of-attack-dependent Cd), this document flags it
  explicitly rather than presenting the formula as if it were
  rigorous. The intent is that a careful reader can see exactly what
  the tool is and is not modelling, and can extend it where needed.

---

## 2. Coordinate systems and reference frames

### 2.1 Frames in use

| Frame | Use |
|---|---|
| **ECEF** | Integration state vector; gravity, drag, thrust forces resolved here |
| **Geodetic (lat, lon, alt)** | All user-visible coordinates; launch sites; targets |
| **ENU (East–North–Up)** | Local frame for resolving the guidance thrust direction |

The ECEF frame co-rotates with the Earth at angular rate `ω = 7.2921150×10⁻⁵ rad/s`
about the polar axis. Choosing ECEF as the integration frame keeps launch
sites stationary, simplifies range calculations, and lets the user specify
azimuth as a local heading rather than an inertial direction. The cost is
that ECEF is non-inertial, so two fictitious accelerations — Coriolis
(velocity-dependent) and centrifugal (position-dependent) — must be
carried explicitly in the equations of motion (Section 5) to recover
Newton's second law.

### 2.2 Geodetic ↔ ECEF conversions

`coordinates.py:geodetic_to_ecef` and `coordinates.py:ecef_to_geodetic`
implement the WGS-84 ellipsoidal conversions. The forward conversion is
closed-form:

```
N(φ)  = R_E / √(1 − e² sin²φ)
x     = (N + h) cos φ cos λ
y     = (N + h) cos φ sin λ
z     = (N(1 − e²) + h) sin φ
```

where `φ` is geodetic latitude, `λ` longitude, `h` altitude above the
ellipsoid, `e² = 2f − f² = 6.694…×10⁻³` is the first eccentricity squared,
and `f = 1/298.257223563` is the WGS-84 flattening.

The inverse conversion uses Bowring's iterative method (10 fixed-point
iterations, converging to machine precision in 3–4 in practice).

### 2.3 Surface distance — Vincenty geodesic

`coordinates.py:range_between` implements the Vincenty inverse geodesic
formula on the WGS-84 ellipsoid. Vincenty achieves sub-millimetre accuracy
over arbitrary distances and replaces the spherical haversine formula used
by the original Forden tool, which has ~0.5 % error at long ranges. For
near-antipodal pairs where Vincenty's iteration does not converge (an
inherent limitation of the inverse formula), the code falls back to
haversine.

### 2.4 ENU local frame

For guidance computations the ECEF velocity is resolved into a local
East–North–Up (ENU) basis attached to the missile's current latitude and
longitude (`_enu_frame`, `trajectory.py`). The unit vectors are

```
ê_E = [−sin λ,            cos λ,            0       ]
ê_N = [−sin φ cos λ,     −sin φ sin λ,      cos φ   ]
ê_U = [ cos φ cos λ,      cos φ sin λ,      sin φ   ]
```

The thrust direction is computed in ENU according to the guidance law
(Section 9) and then transformed back to ECEF for the EOM integration.

### 2.5 Terrain — digital elevation model

By default the Earth's surface is the WGS-84 ellipsoid at `h = 0`:
trajectories launch from sea level and terminate when the altitude crosses
zero, whatever the real ground underneath. This is the flat-surface
condition all the Forden benchmark comparisons (Section 15) were validated
against, and it remains the default. The **Use terrain (DEM)** checkbox in
the Launch Site panel opts a run into real topography
(`integrate_trajectory(terrain_dem=True)`), which changes exactly two
things:

1. **Launch altitude.** The initial state is placed at the launch site's
   real ground elevation. A pad's precise elevation, when known, is passed
   as `launch_elev_m` — every bundled site in `launch_sites.json` carries a
   pre-baked `elev_m` (with an `elev_source` provenance string) sampled once
   from high-resolution tiles; a hand-entered pad falls back to the bundled
   coarse grid. Starting Xichang at its true 1 857 m rather than 0 m gives
   the vehicle ~1.9 km less atmosphere to climb through, a ~1 % range
   effect for an MRBM-class booster.

2. **Ground-impact termination.** The `_hit_ground` event root-finds
   `alt − h_ground(φ, λ)` instead of `alt`, where `h_ground` is the terrain
   height under the sub-vehicle point, floored to 0 over the oceans
   (`terrain.py:ground_elevation` — the sea surface, not the sea floor, is
   the trajectory floor). The same floor terminates a shot into the Tibetan
   plateau ~4 000 m earlier than the sea-level assumption. Bilinear
   interpolation keeps the event function continuous, which `solve_ivp`'s
   root-finder requires.

**Elevation data (`terrain.py`).** Two layers, both derived from the AWS
Open Data *Terrarium* terrain tiles (`elevation-tiles-prod`, a public global
blend of SRTM, GMTED2010, ETOPO1, and national DEMs; elevation is
PNG-encoded as `h = 256R + G + B/256 − 32768` metres):

* **Coarse (bundled, offline)** — `data/dem/terrain_0p05deg.npy`, a
  7200×3600 int16 grid at 0.05° (~5.5 km) resolution covering the globe,
  produced reproducibly by `dem_build.py` from the full zoom-5 tile set
  (native Web-Mercator, inverse-Mercator resampled to equirectangular;
  poleward of Mercator's ±85.05° cutoff the edge value is held). The grid
  is memory-mapped on first use and sampled bilinearly with longitude
  wraparound. ~52 MB on disk, no network dependency.
* **High-resolution (on demand)** — individual Terrarium tiles at zoom 11
  (~76 m/px at the equator, scaling with cos φ), fetched over the network,
  cached on disk (`~/.gui_missile_flyout/dem_tiles`), and sampled
  bilinearly. Any failure — offline, timeout, missing tile — silently falls
  back to the coarse grid, so an elevation query always returns a value.

* **Copernicus GLO-30 (on demand, opt-in)** — the higher-accuracy source:
  uniform 30 m TanDEM-X (~2–4 m vertical, better void handling than the
  Terrarium SRTM/GMTED/ETOPO blend). Each 1°×1° tile is a float32
  Cloud-Optimized GeoTIFF on the public AWS Open Data bucket
  (`copernicus-dem-30m`), read with **Pillow alone — no rasterio/GDAL**; the
  lat/lon→pixel mapping comes straight from the file's `ModelPixelScale` /
  `ModelTiepoint` tags, so the poleward longitude-thinning is handled
  automatically (Plesetsk at 62° N included). Whole 1°-tile fetch (~40 MB),
  disk-cached, then a small in-process array cache; a missing tile (ocean /
  404) or any network failure falls through to the Terrarium tile and then
  the coarse grid, so the query still always returns a value.

The active source for default lookups is selectable under **Analysis ▸
Reference Data ▸ Terrain (DEM)** (the same `MODEL_OPTIONS` registry as the
atmosphere and drag sources, Section 4): *Terrarium z11 tiles* (network,
cached), *Copernicus GLO-30* (30 m TanDEM-X, network), or *Bundled 0.05°
grid* (offline). The choice governs GUI-side
sampling — the pad-elevation readout and site baking. **The trajectory
integrator itself always uses the offline coarse grid** (`hi_res=False`),
so a run never blocks on the network and results are deterministic and
reproducible regardless of connectivity.

A 0.05° cell averages ~5.5 km of relief, so a valley pad in steep terrain
can sit several hundred metres below its cell mean (Xichang: 1 857 m pad in
a ~2 400 m cell) — this is why site elevations are baked from the hi-res
layer rather than sampled from the grid at run time. Heights are metres
above the tiles' native vertical datum (a geoid proxy), treated
interchangeably with ellipsoidal height; the ~±50 m geoid separation is
well inside the tens-of-metres screening accuracy of the tool. Terrain is
evaluated only for the launch state and the impact/floor test — it does not
occult line-of-sight or modify the atmosphere column.

---

## 3. Gravity model

Thrusty uses a WGS-84 gravity field truncated to the second zonal
harmonic `J₂` — that is, a spherical-harmonic expansion of the
geopotential keeping only the spherical and oblateness terms. The
acceleration in ECEF is computed component-wise
(`gravity.py:gravity_ecef`):

```
g_x = −(GM·x/r³) · [1 − (3J₂R_E²/2r²) · (5(z/r)² − 1)]
      − (GM · 3J₂R_E² / 2r⁵) · x · (1 − 5z²/r²)

g_y = −(GM·y/r³) · [1 − (3J₂R_E²/2r²) · (5(z/r)² − 1)]
      − (GM · 3J₂R_E² / 2r⁵) · y · (1 − 5z²/r²)

g_z = −(GM·z/r³) · [1 − (3J₂R_E²/2r²) · (5(z/r)² − 1)]
      − (GM · 3J₂R_E² / 2r⁵) · z · (3 − 5z²/r²)
```

The first term in each component is the spherical (point-mass at
Earth's centre) gravity with a J₂-dependent latitudinal correction; the
second term is the extra zonal contribution that gives the field a
component pointing toward the equatorial plane at non-equatorial
latitudes. Note that the z-component has a `(3 − 5z²/r²)` factor versus
`(1 − 5z²/r²)` for the x and y components — that asymmetry is what
makes the J₂ field oblate-symmetric rather than spherically symmetric.

The constants are the WGS-84 values (`gravity.py–13`):

| Symbol | Value | Description |
|---|---|---|
| `GM` | 3.986 004 418×10¹⁴ m³/s² | Earth gravitational parameter |
| `R_E` | 6 378 137 m | Equatorial radius |
| `J₂` | 1.082 626 68×10⁻³ | Second zonal harmonic |

The J₂ correction is roughly 0.1 % of the leading spherical term but is
significant at ICBM and SLV altitudes. A circular orbit at 400 km
experiences argument-of-perigee drift under J₂ that depends strongly on
inclination — from about +16°/day at the equator to zero at the
critical inclination of 63.4° to about −4°/day at polar orbits. For
the sub-orbital trajectories Thrusty is primarily used for, the J₂
correction shows up as a few-kilometre range bias relative to a
spherical Earth, larger for high-apogee lofted profiles.

Higher-order zonal harmonics (`J₃`, `J₄`, …) and the tesseral harmonics
(longitude-dependent terms) are not modelled. These matter for
orbit-tracking precision but not for the engineering questions Thrusty
answers.

---

## 4. Atmosphere

`atmosphere.py` provides a single function `atmosphere(altitude_m) → (T, P, ρ, a)`
returning temperature (K), pressure (Pa), density (kg/m³), and speed of
sound (m/s). Two models are selectable:

### 4.1 NRLMSISE-00 (default)

The default model is NRLMSISE-00 ([Picone, Hedin, Drob & Aikin
2002](#16-references)) accessed through the `pymsis` package. NRLMSISE-00
returns species-resolved number densities, total mass density, and
temperature for the upper atmosphere; for trajectory work the mass density
is what matters.

The model is queried once at module import for 0–1000 km at 500 m spacing,
producing a pre-computed lookup table with interpolation on `log ρ` and
`log P` to preserve the exponential character of upper-atmosphere variation.
Per-trajectory calls use this lookup at ~10 μs per scalar evaluation
(measured; vectorised batch calls amortise to far less per point), which
keeps the EOM evaluation cheap.

Default conditions (set in `_ATM_CONFIG`):

| Parameter | Default | Meaning |
|---|---|---|
| `f107` | 150 | Daily F10.7 solar flux index |
| `f107a` | 150 | 81-day average F10.7 |
| `ap` | 4 | Geomagnetic Ap index (quiet) |
| `doy` | 80 | Day of year (~vernal equinox) |
| `ut_sec` | 43 200 | Universal time (noon UT) |
| `lat_deg`, `lon_deg` | 0, 0 | Geographic location for the MSIS evaluation |

The user can override any of these via `configure_atmosphere(**kwargs)`,
which rebuilds the lookup table in ~100 ms. This is the path to model a real
launch date and site with measured solar indices.

#### Design rationale

**Implementation summary.** The NRLMSISE-00 table covers 0–1000 km at
500 m intervals — `alts_km = np.arange(0.0, 1000.5, 0.5)` — built at
import time from a single `pymsis.calculate()` call
(`atmosphere.py`). The COESA 1976 code (`_atmosphere_std1976`,
`atmosphere.py`) remains available both as an automatic fallback if
`pymsis` is not installed and as an explicit user choice via
`configure_atmosphere(model='std1976')`. The `atmosphere(altitude_m)`
function signature is identical in both modes, so no caller in
`trajectory.py`, `booster_models.py`, or `thrusty.py` needs to know
which model is active.

The lower atmosphere (0–86 km) is well-mixed and well-measured; US Std
Atm 1976 and NRLMSISE-00 agree to within ~10 % across most of that band
because both are anchored to the same tropospheric/stratospheric data.
The two models diverge meaningfully above ~200 km, where MSIS's
solar-cycle and latitudinal corrections start to matter. Measured
density differences at the mean-conditions defaults (computed
end-to-end against the actual implementation):

| Altitude | ρ_MSIS (kg/m³) | ρ_StdAtm (kg/m³) | % difference |
|---:|---:|---:|---:|
| 0 km | 1.16 | 1.23 | 5.4 % |
| 30 km | 1.78×10⁻² | 1.80×10⁻² | 1.1 % |
| 70 km | 8.32×10⁻⁵ | 7.42×10⁻⁵ | 12 % |
| 86 km | 6.22×10⁻⁶ | 5.64×10⁻⁶ | 10 % |
| 100 km | 6.21×10⁻⁷ | 5.60×10⁻⁷ | 11 % |
| 120 km | 2.02×10⁻⁸ | 2.22×10⁻⁸ | 9 % |
| 200 km | 2.88×10⁻¹⁰ | 2.54×10⁻¹⁰ | 13 % |
| 300 km | 3.15×10⁻¹¹ | 1.92×10⁻¹¹ | 64 % |
| 500 km | 1.31×10⁻¹² | 5.22×10⁻¹³ | 151 % |

Below 200 km the two models agree to 10–15 %, which is small compared
to typical parameter uncertainties on a missile's drag coefficient.
Above 200 km the divergence grows rapidly, but the absolute density is
small enough that drag is essentially negligible for the trajectory
regimes Thrusty addresses.

NRLMSISE-00 also captures variability that US Std Atm 1976 cannot —
the solar cycle (F10.7), geomagnetic activity (Ap), and diurnal,
seasonal, and latitudinal variation. Measured solar-cycle density
ratios (F10.7 = 70 vs F10.7 = 250 at the mean-conditions defaults
otherwise):

| Altitude | ρ(F10.7=250) / ρ(F10.7=70) |
|---:|---:|
| 100 km | 1.1× |
| 150 km | 1.4× |
| 200 km | 2.4× |
| 300 km | 6.6× |
| 500 km | 33× |

The amplification is geometric with altitude. For HGV glide trajectories
dwelling in the 60–100 km band the solar-cycle effect is small
(< 1.5×); for orbital-decay studies or for trajectories with sustained
flight above 200 km, MSIS at the actual mission conditions is the right
choice.

The "mean conditions" defaults are not arbitrary — each was chosen
deliberately to produce a *close-to-mean atmosphere*, so that switching
the default model from US Std Atm 1976 to MSIS would not silently
shift results:

| Parameter | Default | Why this value approximates "mean" |
|---|---|---|
| `f107` | 150 | Long-term mean of the 11-year solar cycle |
| `f107a` | 150 | Same — 81-day average set to the long-term mean |
| `ap` | 4 | Quiet geomagnetic state (near the historical median) |
| `doy` | 80 | Vernal equinox — geometrically between summer and winter solstices |
| `ut_sec` | 43 200 | Noon UT — a clean reference time |
| `lat`, `lon` | 0, 0 | Equator / prime meridian — a clean reference location |

Measured against a 5×4×5 grid sweep of (doy, UT, latitude) at the same
solar/Ap state, the default profile is within 5–10 % of the geometric
mean below 86 km (where ballistic-missile drag matters) and 11–22 %
above 100 km. The upper-altitude divergence comes from the noon-UT /
equator geometry sitting on the diurnal bulge peak rather than
averaging it out — a known feature of the choice, traded for the
simplicity of a fixed reference point.

The result is that scenarios run under the new MSIS default give
effectively the same answers as the prior US-Std-Atm default across
the drag-relevant atmospheric regime (within 10–15 % across 50 km –
200 km). Most users will never need to touch `configure_atmosphere()`
— it is there for the ~1-in-100 case of real flight data tied to a
specific date and time, or for solar-cycle sensitivity studies.

This is one example of the broader design pattern named in Section 1.1:
the default is a sensible mean-conditions reference, the configuration
hook is there for users who need to model a specific scenario more
accurately. A user analysing a real test launch with known date and
solar indices can drop those into `configure_atmosphere()` before
running the trajectory and recover the actual atmosphere the missile
flew through.

#### Expected impact on ballistic trajectories

For typical ballistic-missile and HGV scenarios the
atmosphere-model choice moves the answer by a small but non-zero
amount. The rough magnitudes recorded during development (engineering
estimates for an AUR/C-HGB-class case at β ≈ 15 000, apogee ≈ 200 km,
under the full range of solar variability):

| Quantity | Expected swing (solar min ↔ max) |
|---|---|
| Apogee | ±0.1 to ±1 km |
| Total ballistic range (3 000+ km flight) | ±1 to ±5 km |
| HGV glide range | ±1 – 3 % |

These are order-of-magnitude estimates, not measured values from a
calibrated test suite; the HGV glide-range swing is the largest of the
three because the glider dwells in the 60–100 km band where solar
variability accumulates over hundreds of seconds of flight time. For
ordinary ballistic-missile range/apogee studies the difference is
dwarfed by parameter uncertainties on mass, Isp, and loft angle.

### 4.2 US Standard Atmosphere 1976 (fallback)

If `pymsis` is unavailable, or if `configure_atmosphere(model='std1976')` is
called explicitly, the model falls back to the US Standard Atmosphere 1976
extended to 1000 km. The COESA layer base altitudes, temperatures, and lapse
rates are tabulated in `_LAYERS`:

| Layer base (m) | T (K) | Lapse rate (K/m) |
|---:|---:|---:|
| 0 | 288.15 | −0.0065 |
| 11 000 | 216.65 | 0 |
| 20 000 | 216.65 | +0.001 |
| 32 000 | 228.65 | +0.0028 |
| 47 000 | 270.65 | 0 |
| 51 000 | 270.65 | −0.0028 |
| 71 000 | 214.65 | −0.002 |
| 86 000 | 186.87 | 0 |

Pressure within each layer follows the analytic integration of hydrostatic
balance under constant lapse rate:

- Non-isothermal layer (`L ≠ 0`): `P = P_b · (T_b / T)^(g₀ / (R · L))`
- Isothermal layer (`L = 0`): `P = P_b · exp(−g₀ · Δh / (R · T_b))`

with `R = 287.052 87 J/(kg·K)` for dry air. Density is recovered from the
ideal gas law `ρ = P/(R T)`.

Above 86 km the fallback uses an exponential interpolation between the
US Std Atm 1976 Table I/II reference points at 86, 91, 100, 110, 120, 150,
200, 300, 500, and 1000 km.

### 4.3 Dynamic pressure and Mach number

Two convenience functions on top of the atmosphere model:

```
q       = ½ ρ V²                     (dynamic pressure, Pa)
M       = V / a                       (Mach number)
```

where `a = √(γ R T)` is the speed of sound and `γ = 1.4`.

### 4.4 Other atmosphere models

The atmosphere module is structured around a fixed signature
(`atmosphere(altitude_m) → (T, P, ρ, a)`) and a configuration dictionary. The
configuration interface has been exercised with Martian parameters, but the
Mars atmosphere is not a documented capability of the production code path.
Treat the Mars files as exploratory tests rather than a supported feature.

---

## 5. Equations of motion

The full equation of motion in ECEF is

```
r̈ = g_ECEF(r) + a_thrust + a_drag − 2 ω × ṙ − ω × (ω × r)
```

(`_eom`, `trajectory.py`). The right-hand side gives acceleration
in m/s² directly; each of the five terms is an acceleration, not a
force. Below they are listed in the order they appear in the code.

### 5.1 Gravity

`g_ECEF(r)` from Section 3.

### 5.2 Thrust acceleration

```
a_thrust = T(h) · û_thrust(t) / m(t)
```

The thrust magnitude `T(h)` is altitude-corrected (Section 7.2); the unit
vector `û_thrust` is set by the guidance law (Section 9); and `m(t)` is the
instantaneous mass (Section 6).

### 5.3 Drag acceleration

```
a_drag = −½ ρ V² · C_D · A_ref / m · v̂
```

with `V = |ṙ|`, `v̂ = ṙ / V`, `C_D` and `A_ref` from Section 8. For
post-burnout flight with a ballistic-coefficient parameterisation
`β = m / (C_D · A_ref)` the drag magnitude reduces to `q · m / β`.

### 5.4 Coriolis

```
a_Coriolis = −2 ω × ṙ
```

with `ω = [0, 0, Ω_Earth]ᵀ` in the ECEF frame. For a 4 km/s velocity
this is up to `2 · Ω · |v| ≈ 0.58 m/s²` — small instantaneously but
cumulatively significant over long flight times. The Coriolis term
deflects long-range trajectories laterally — the well-known equatorward
or poleward drift depending on hemisphere and launch direction — and
contributes to the cross-range bias that targeting algorithms must
account for.

### 5.5 Centrifugal

```
a_centrifugal = −ω × (ω × r) = Ω² · [x, y, 0]ᵀ
```

At the equator at sea level this is 0.034 m/s², equivalent to ~0.35 % of
local gravity. It is included for self-consistency with the rotating frame
formulation.

### 5.6 Integration

`scipy.integrate.solve_ivp` with `method='RK45'`. Tolerances vary by path:
the full-fidelity ballistic integration uses relative tolerance `1e-8` and
absolute tolerance `1e-6`; the faster range-search and glide integrations
use looser tolerances (as coarse as `~1e-5`/`1e-2`), and the apogee
pre-finder coarser still. Adaptive step sizing concentrates evaluations
during the boost phase (where mass and thrust change rapidly) and stretches
them during coast.

Event functions used (passed to `solve_ivp(events=...)`):

| Event | Purpose |
|---|---|
| `_hit_ground` | Trajectory termination at altitude ≤ 0 (or ≤ real terrain height with the DEM on, Section 2.5) |
| `_apogee_event` (sign change of `ṙ·r̂`) | Apogee detection |
| Milestone-altitude crossings | 100 km re-entry, shroud jettison, user-defined queries |
| `_glider_pierce_atmosphere` | HGV pull-up / equilibrium-glide handoff |

Orbital-energy engine cutoff is **not** a `solve_ivp` event — it is applied
inline inside `_eom` (the thrust is zeroed once the specific orbital energy
`ε = ½|v_ECI|² − μ/r` reaches the target `ε_target = −μ/(2 r_target)`, for a
liquid final stage only). Detected events become rows in the Flight Timeline
output (Section 14).

---

## 6. Mass and staging

A missile is represented by a linked-chain `BoosterParams` dataclass
(`booster_models.py`). Each stage carries its own propulsive and
geometric parameters; the `.stage2` attribute points to the next stage.
Top-level fields (payload, shroud, RV) apply to the whole vehicle.

### 6.1 Mass schedule

For a stage with initial mass `m₀`, propellant mass `m_p`, and burn time `t_b`,
the instantaneous mass during burn is linear in time:

```
m(τ) = m₀ − (m_p / t_b) · τ              0 ≤ τ ≤ t_b
```

where `τ` is local stage burn time. The burnout mass is `m_f = m₀ − m_p`.

The full-vehicle mass `booster_mass(params, t)` (`booster_models.py`)
walks the stage chain to determine which stage is active and adds the mass
of all subsequent stages plus payload. After a stage burns out the spent
casing is jettisoned and its dry mass is removed from the chain.

### 6.2 Coast and inter-stage events

Each stage has an optional `coast_time_s` — a quiescent interval between
that stage's burnout and the next stage's ignition. During coast the engine
produces no thrust and drag plus gravity govern the trajectory. The
Flight Timeline records each stage's ignition, burnout, coast end, and any
shroud-jettison events.

### 6.3 Shroud jettison

The payload shroud (or fairing) is treated as a top-level mass that
contributes to drag area until it is jettisoned. The jettison rule is a
flight-plan choice, selected by `shroud_jettison_alt_km`:

- **Altitude** (`> 0`): the event fires on the first *upward* crossing of
  that altitude.
- **Heating criterion** (`<= 0`, a blank field in the GUI): the event fires
  when the free-molecular heating flux q̇ = ½ρV³ falls below
  `SHROUD_Q_FAIRING` = 1135 W/m², having first risen above it on the way
  through max-q. This is the launch-vehicle convention for protecting a
  spacecraft: the Falcon Payload User's Guide (SpaceX, May 2025, p. 42)
  states that the fairing "will nominally be deployed when free molecular
  aero-thermal heating is less than 1,135 W/m²". It is a payload-protection
  rule for satellites, not a statement about any particular missile or
  glide vehicle; where the actual jettison point of a vehicle is known from
  open sources, enter it as an altitude.

After firing, the shroud's mass is subtracted from the missile total and the
reference geometry for drag switches from the shroud envelope to the payload
or re-entry vehicle (Section 8.2).

**The fairing cannot outlast separation.** A separating reentry object flies
on its own mass and aerodynamics from final-stage burnout (Section 6.4), so a
fairing whose rule has not fired by then leaves with the stage. On a
depressed trajectory this is the normal case for the heating criterion: a
flight at 5.5 km/s must be above roughly 125 km before ½ρV³ drops below
1135 W/m², and a boost-glide profile may never get there. The Flight
Timeline then reports `Fairing released at separation`, with the reason —
the rule was met only later (`heating criterion not met until 249 s`), or
never (`heating criterion never met: flight minimum 1594 W/m² > 1135 W/m²`)
— and the fairing's debris arc starts from the separation point. When
nothing separates and the rule never fires, the row reads `Fairing
retained`. These rows are reporting only; they describe what the dynamics
already do and do not change the trajectory.

### 6.4 Reentry vehicle separation

Whether the reentry object separates from the final-stage body at burnout is a
property of the **booster**, and the one place the booster and the reentry
object are linked. `BoosterParams.body_reenters` (a checkbox in the booster
editor) marks a vehicle whose front end never separates — Scud / a quasi-ballistic body /
unitary-airframe class — so the last stage *is* the reentering body. The run derives the
object's `separation_mode ∈ {separating_ro, body}` from that flag
(`run_separation_mode`; `bind_ro_separation` stamps it onto the object at the
start of every integration, and `effective_ro` on every read), so every path
that branches on `ro.separation_mode` agrees with the booster. Neither the
reentry-object file nor the reentry plan stores a separation choice: the key is
omitted by `ro_to_dict` and is not a reentry-plan key, and a legacy plan file
that still carries it is ignored on apply. The sidebar **Separation** box is a
read-only indicator of the booster flag. Any object can be flown on any
booster; the reentry mode still defaults to ballistic and stays switchable.
`test_input_split.py` holds this, and the wider four-inputs rule (hardware
files carry no plan key, plan files carry no hardware key), over the shipped
files and the serialisers. Where a plan value meets a hardware limit the plan
is clamped on apply — commanded L/D ≤ `glider_LD`, commanded pull-up g ≤
`pullup_g_limit` (0 = unlimited), and the plan's `glider_enabled` intent by
the object's `maneuvering` capability — so a plan can fly a vehicle worse
than its hardware allows, never better.

- **Separating** (`separating_ro`): the object departs at burnout and reenters
  on its own geometry/β; the spent final stage tumbles away as debris (§14.3).
  The casing's debris mass is the last stage's **burnout mass**
  (`mass_initial − mass_propellant`) minus the object's mass, so a warhead that
  was carried inside the stage's mass budget is not counted twice.
- **Non-separating** (`body`): the last stage *is* the reentering vehicle
  (generic maneuvering body / Pershing-II MaRV class). `effective_ro` inherits the stage's
  burnout mass, diameter, and length; no separate last-stage debris arc is
  emitted. Attitude (§8.11) then decides trimmed vs. tumbling drag. Because the
  airframe is one body, its nose is drawn **subtractively** — the forward
  `ROParams.body_nose_length_m` is the taper carved from the top of the stage,
  not a section stacked on it — so the schematic's total height is the airframe
  length, matching what is flown. This DRAWN ≡ FLOWN invariant (the schematic is
  the human's oversight surface) is pinned by `test_front_end_consistency.py`;
  see `FRONT_END_DESIGN.md`. The airframe mass is inherited, but the front end
  owns an explicit **added payload** (`ROParams.payload_kg` — warhead / bus /
  guidance): `compose_loadout` adds it to the boosted stack and keeps it fused
  through burnout (a tracked-baseline delta makes composing idempotent), so the
  reentry mass is airframe-burnout + payload. The object's own `mass_kg` is
  never added for a body (that was a range-halving double-count); default
  `payload_kg = 0` leaves existing files byte-identical. `test_body_payload.py`.

Old files are converted before they are read: `upgrade_booster_dict` and
`upgrade_ro_dict` (booster_models.py) hold every compatibility rule Thrusty
has ever needed — Forden's `loft` guidance, the `rv_*` field family, nose
length as a diameter ratio, reentry hardware stored on the booster, retired
glide-law and separation tokens — and the constructors read only the current
schema. `test_legacy_upgrade.py` pins each conversion against a golden record
of what it used to produce.

Booster files are **stack-only**: no payload is stored, the reentry object
owns its mass, and `compose_loadout` adds it at run time (`payload_kg` on the
chain is the run's record of what is composed). The former `ro_separates`
build flag is retired; a legacy file that baked a design payload into its
stage masses (and, Scud-class, into the last stage's burnout mass) is
normalised to stack-only when loaded, and composing the object that carries
that mass reproduces the original masses exactly (`test_input_split.py`).
Post-burnout drag uses the reentering vehicle's geometry
and ballistic coefficient rather than the spent stage's. This matters for ICBMs
and SLVs where the spent upper stage has very different drag characteristics
from the warhead or payload it deployed.

### 6.5 Strap-on boosters

A vehicle may carry up to nine strap-on boosters that fire in parallel
with stage 1 from t = 0, then separate at a configurable burn time.
These appear in operational launch vehicles (e.g. Delta-IV Heavy,
Ariane 5, H-IIA, ISRO PSLV) and in some ballistic-missile derivatives.

Booster parameters live on the *top-level* `BoosterParams` node as 11
fields (defaults zero, so existing missile definitions are unaffected):

| Field | Meaning |
|---|---|
| `n_boosters` | Number of identical boosters (0–9) |
| `booster_thrust_n` | Vacuum thrust per booster (N) |
| `booster_burn_time_s` | Burn duration (s); separation occurs at this time |
| `booster_inert_kg` | Empty (dry) mass per booster (kg) |
| `booster_prop_kg` | Propellant mass per booster (kg) |
| `booster_isp_s` | Specific impulse (s) |
| `booster_nozzle_area_m2` | Nozzle exit area per booster (m²) |
| `booster_diam_m` | Outer diameter per booster (m) |
| `booster_length_m` | Length per booster (0 → defaults to 2 × diameter) |
| `booster_cd` | Zero-lift drag coefficient per booster (default 0.20 ≈ tangent ogive) |
| `booster_core_delay_s` | Seconds after T = 0 before stage-1 core ignites |

**Mass schedule.** Total vehicle mass at time `t` during the booster
burn is:

```
m(t) = m_core(t) + n_boosters · (booster_inert + booster_prop · (1 − t/t_booster))
```

At separation (`t > booster_burn_time_s`) the booster contribution to
vehicle mass drops to zero — the casings (now with empty propellant
tanks) detach from the vehicle (`_booster_mass_addend`,
`booster_models.py`). The spent casings then follow tumbling-cylinder
debris arcs separately (Section 14.3).

**Thrust addition.** During the booster burn window `t ∈ [0, t_booster]`,
the booster contribution adds to the stage-1 thrust:

```
T_total(t) = T_core(t) + n_boosters · T_booster(h)
```

with each `T_booster(h)` getting its own ambient-pressure correction
(Section 7.2). The core may be delayed up to `booster_core_delay_s`
after liftoff to model vehicles whose core engine ignites only after
the boosters lift the stack off the pad.

**Drag addition.** Booster aerodynamic drag is computed as a parallel
cluster of cylinders independent of the core (`booster_drag_vector`,
`booster_models.py`):

```
D_booster = n_boosters · C_D,booster · q · π · (d_booster / 2)²
```

opposing the velocity vector. The booster `C_D` is a single user-set
value covering wave + friction + base. The default `0.20` is appropriate
for a tangent-ogive booster (consistent with Section 8.2.2); the GUI
tooltip flags `0.10 – 1.00` as the realistic range.

**Simplification flagged.** The cluster of boosters around the rear of
the core would, in reality, change the core's base-pressure
distribution (the boosters partially fill the wake region where suction
develops). Thrusty does not model this interaction — both the core
base drag (Section 8.4) and the booster drag are computed
independently. The error is small relative to the boosters' direct
contribution at supersonic Mach but could matter at transonic flight
of a heavily-boostered vehicle.

**Separation event.** "Booster separation" is inserted chronologically
into the flight timeline at `t = booster_burn_time_s`. Spent booster
casings then follow tumbling-cylinder ballistic arcs (Section 14.3)
until impact, recorded as separate debris-impact rows in the timeline.

### 6.6 Stage dry-mass estimation (independent cross-check)

Thrusty integrates from each stage's **burnout mass**, supplied directly by the
user (Section 6.1). The dry-mass estimator (`mass_estimator.py`; full tables and
sources in [`MASS_ESTIMATOR.md`](MASS_ESTIMATOR.md)) is a separate design-time
tool that helps you judge whether a stated dry mass is plausible, using several
popular mass-estimating relationships (MERs). It never feeds the trajectory — it
is a sanity check on the number the trajectory trusts.

There is no single authoritative dry-mass equation: the published MERs are a
*range* fit to different datasets and eras, and they disagree — two reasonable
ones can differ by tens of percent on the same stage. The tool runs several side
by side and reports the spread, so their agreement (or disagreement) is itself
the signal for how trustworthy a stated dry mass is.

These relations fall into two complementary families:

| Family | Inputs needed | Best for |
|---|---|---|
| **Component-level** (Wilhite-school MERs) | geometry, propellant split, thrust | large LV stages; itemised "where is the mass" breakdown |
| **Aggregate** (whole-stage relations) | propellant mass (+ thrust) | quick sanity bound; small stages; solids |

The two families are themselves the cross-check: in the small / tactical-scale
regime the component build-up's fixed terms (engine `+59 kg`, avionics, wiring)
dominate and **over-predict**, so the aggregate ε estimate is the one to trust
there — an explicit "use family B to catch family A's failure mode." Solids and
liquids are split on physics grounds: a solid case is a *pressure-loaded* vessel
(chamber pressure × grain volume), whereas a liquid's tanks are *near-unloaded*,
sized by propellant volume.

#### 6.6.1 Liquid stages

The component path (`estimate_liquid_stage`) sums itemised MERs from D. L. Akin's
*Mass Estimating Relations* (UMD ENAE 791) — the SI compilation descending from
the Heineman / MacConochie–Klich / Glatt (WAATS) lineage, the same school as
Wilhite's SSDL relations, and independently corroborated against Rohrschneider /
SSDL and Gaspar (2014). Tanks, cryogenic insulation, pump-fed engines, thrust
structure, gimbals, fairing, avionics, and wiring each have their own relation;
only the **tanks** are scaled by `tank_material` (`material_tank_factor`:
Al 1.00, Al-Li 0.74, composite 0.45, steel 1.60) — engines, thrust structure and
avionics are treated as material-independent. Avionics is **one guidance package
per vehicle**, carried on the upper stage only and sized on vehicle gross
liftoff mass, not the stage it rides on.

> *Engine-MER decision.* Akin's lecture table lists 373 kg/engine, but his own
> formula gives ≈ 641 kg at the worked example — which matches the independent
> Zandbergen (2015) pump-fed-engine fit to ~5 %. The implementation follows the
> **formula** and treats the 373 kg slide value as an arithmetic slip;
> `test_mass_estimator.py` pins it against Zandbergen.

A **physics-based tank option** (`tank_structural_mass`, the GT-STRESS method of
Hutchinson & Olds) can replace the empirical tank MER: it sizes each tank as a
thin shell under the worse of a max-axial (burnout) and a max-q-α (liftoff, full
tank + lateral-g) load case, taking thickness as the max over ultimate, yield,
buckling, and minimum-gauge, times a `TANK_CORRELATION = 1.50` factor. Here
**material choice is physics, not a multiplier** (ρ, σ, E, gauge from
`MATERIALS`). Axial load comes from thrust, so no trajectory run is needed;
refining the loads from a flown trajectory is a flagged follow-on.

The aggregate path deliberately distinguishes *predictions* from *tautologies* —
a core philosophy of the tool:

- **Engine-mass-ratio** (`engine_mass_ratio_inert`, Shu et al. 2020) is the real
  predictive aggregate for any liquid: inert = `M_engine·(1 + 1/κ_E)` with
  `M_engine` predicted from thrust and `κ_E` (`_KAPPA_E_DEFAULT`: lower 0.25,
  upper 0.12) varying over a much narrower band than ε. This fills the
  non-hydrolox gap that an assumed ε could not.
- **Pietrobon** hydrolox stage-mass power law (`pietrobon_stage_mass`) is shown
  only for LOX/LH₂.
- An **assumed structural coefficient** (`inert_from_structural_coefficient`) is
  **opt-in only and explicitly not a prediction** — it merely restates an ε you
  supply, in kilograms, "carrying no information beyond the assumption itself,"
  and was deliberately demoted from a default estimate to an opt-in reporting
  lens.

#### 6.6.2 Solid stages

The headline solid estimate (`solid_stage_inert`) uses the whole-stage
regressions of Zandbergen (2026), fit to flown stages, because open-literature
*component* MERs for solids are sparse — nozzle and internal-insulation MERs are
**intentionally not invented**. A best-in-class cross-check (`source="lewis"`)
regresses the Northrop Grumman Propulsion Products Catalog (29 Orion / Castor /
GEM motors); being mature flight motors it runs ~10 % lighter — the lower edge of
the inert band. When length and diameter are both supplied a **slenderness (L/D)
correction** is added, with a *positive* exponent: a more slender motor carries
*more* inert per unit propellant, because case wall and insulation scale with
surface area, not enclosed volume. The L/D term expects the **motor** length
*including the nozzle* — trim only non-motor structure (interstages, skirts),
never the nozzle.

#### 6.6.3 The divergence report

When a stated dry mass is supplied, `divergence_report` leads with the
**structural coefficient** `ε = dry / (dry + propellant)` it implies (and
`λ = dry/propellant`), then lists each method's *estimated* ε beside the
percentage divergence and a verdict: **consistent** (≤ 15 %), **marginal**
(≤ 35 %), otherwise **optimistic** / **conservative**. Reporting in ε lets a
design be judged "in the units you think in," and — because tank material moves
the estimated ε — directly answers *is this dry mass plausible for this
material?* A large negative divergence means the stated structure is lighter than
any flown analogue (Peacekeeper-derived motors read "optimistic").

A hard physical bound backstops the report: the **Goldyn et al. (2025)
feasibility ceiling** `ε_max = 1/exp(Δv/(g₀·I_sp))` (`structural_index_ceiling`).
Above it the rocket equation drives propellant mass negative, so any stated or
estimated ε breaching the ceiling is flagged as impossible. This is the same
estimate-and-flag posture used throughout Thrusty (Section 1.1): give a
defensible default, surface the assumptions, and flag what is physically out of
bounds rather than silently accepting it.

> **Provenance note.** The estimator postdates the development-session logs
> that were once committed to this repo (since removed; see
> [`PROVENANCE.md`](PROVENANCE.md)), so its rationale was never in those logs;
> the authoritative record is the module's own git history and
> [`MASS_ESTIMATOR.md`](MASS_ESTIMATOR.md), on which this section is based.

### 6.7 Interstages and conical stages (Phase 1: geometry + mass)

Two optional per-stage structural features, both defaulting off so every
existing vehicle is byte-identical until it opts in.

**Interstage adapter.** Any stage may carry an interstage on top of it —
the structural section connecting it to the next stage. It is toggled by
`has_interstage`; the only free parameters are `interstage_length_m`,
`interstage_mass_kg`, and `interstage_jettison_s`. The frustum's
**diameters are derived, never entered**: the bottom equals this stage's
top diameter (its `top_diameter_m` when conical, else `diameter_m`) and
the top equals the next stage's base diameter. This is deliberate — the
schematic must never invent a transition the data did not specify, so the
adapter's shape is forced to match the real neighbouring geometry.

*Mass schedule.* The interstage rides with the stack from launch until
its jettison event — `interstage_jettison_s` if set, otherwise the
carrying stage's separation (its burnout, the instant that stage leaves).
It is an **additive** term (`_interstage_mass_addend`, `booster_models.py`),
so the stored stage masses are unchanged and a vehicle with no interstage
gets `+0`. The interstage is a booster-side adapter, never part of
`payload_kg` / the throw-weight tally.

*Drag.* **Phase 2 adds a flare wave-drag increment** (`_transition_wave_drag`,
`booster_models.py`). An interstage that steps DOWN to a narrower upper stage
— wider at its aft end than its forward end — is a flare: it presents a
forward-facing conical surface to the nose-first flow and adds pressure drag,
the cone-pressure coefficient at the flare half-angle (`_cd_wave_cone`, the
same Chin primitive as the nose and biconic terms) times the frontal-area
increase, referenced to the boost area. A same-diameter interstage adds
nothing. The reference area is unchanged (still the widest front-end body).

**Conical (tapered) stage.** `conical = True` with `top_diameter_m > 0`
makes the stage body a frustum from `diameter_m` (base) to `top_diameter_m`
(top), a cylinder otherwise. A tapered stage (base wider than top) is a flare
in the flow: it is charged the same `_flare_cd` increment as an interstage,
referenced to the base diameter (the reference area is unchanged). Distinct
from an interstage —
a conical stage is load-bearing structure that stays; an interstage is a
jettisonable adapter.

Both are drawn to scale in the **Schematic** tab (a conical stage as a
trapezoid; an interstage as its derived-diameter frustum, labelled with
length, mass, and jettison), so a mis-sized adapter or taper is visible at
a glance.

*Screening scope.* Only FLARES are charged (forward-facing area growth);
boattails / tapers narrowing aft are not credited (their small base-drag
benefit is below screening granularity), and the added skin friction of an
interstage is not separately counted because the front-end drag model already
resolves only the front-end body — adding one interstage's friction would be
inconsistent granularity. A plain stack (no `conical`, no `has_interstage`)
is byte-identical. `test_transition_drag.py`.

---

## 7. Propulsion

### 7.1 Thrust from `I_sp`

The mass-flow rate, burn time, and vacuum thrust are linked by the
standard definition of specific impulse:

```
T_vac = I_sp · g₀ · ṁ                     (definition of I_sp, rearranged)
ṁ     = m_p / t_b                          (constant-mass-flow burn)
```

so any two of `T_vac`, `I_sp`, `t_b` determine the third given `m_p`.
(This is not the Tsiolkovsky rocket equation — that is the integrated
`Δv = I_sp · g₀ · ln(m₀ / m_f)` form used for stack-ΔV estimation in
Section 10.1.) `booster_models.py:_thrust_from_isp` is used by the GUI's
"Suggest" thrust estimator (Section 14 of the user guide) and by the
built-in missile definitions that specify `I_sp` and burn time rather
than thrust directly.

### 7.2 Ambient-pressure correction

Vacuum thrust overstates the thrust at lower altitudes because ambient
back-pressure works against the exhaust. The corrected thrust is

```
T(h) = T_vac − P_amb(h) · A_e
```

where `A_e` is the nozzle exit area and `P_amb(h)` comes from the
atmosphere model (Section 4). The nozzle-area parameter `nozzle_exit_area_m2`
on each stage enables this correction; if it is zero, a default 2 %
sea-level back-pressure approximation is used instead. The "Estimate"
button next to the nozzle-area field in the GUI uses an expansion-ratio
heuristic to pre-fill plausible values.

### 7.3 Solid motor grain profiles

For a solid motor the bulk thrust integral `∫T dt = I_sp g₀ m_p` is
constrained by total impulse, but the instantaneous thrust profile depends
on the grain geometry. Thrusty supports six grain types via a
`grain_type` field and an associated `thrust_peak_N` parameter (the peak
vacuum thrust). The `thrust_N` field continues to hold the *average*
vacuum thrust, and the ratio `thrust_N / thrust_peak_N` defines the
fill factor implied by the grain shape.

The grain types, after Shafer (1959), Ch. 16 in *Space Technology*. The
fill factor ranges are stored in the code as `_GRAIN_FILL_RANGE` and used
by the GUI to warn if a user-entered combination is unphysical for the
chosen grain:

| Grain type | Burn character | Realistic fill-factor range |
|---|---|---|
| Tubular | Progressive | 0.70 – 0.95 |
| Rod and tube | Neutral | 0.90 – 1.00 |
| Double anchor | Regressive | 0.60 – 0.85 |
| Star | Neutral | 0.85 – 1.00 |
| Multi-fin | Two-phase (boost-sustain) | 0.50 – 0.75 |
| Dual composition | Two-phase | 0.35 – 0.60 |

Each grain type also has a normalised piecewise-linear thrust-time
profile `_GRAIN_CURVES[grain]` giving `F/F_peak` at fractional burn
time `τ/t_b`. The instantaneous thrust fraction
`_instantaneous_thrust_frac(grain, τ_frac)` returns the thrust at
fractional burn time `τ/t_b ∈ [0, 1]` for the chosen grain by
linear interpolation on the appropriate curve. A user-supplied `thrust_profile` list of `(t_frac, F_frac)` pairs
overrides the built-in shape — this is the path for loading a CSV burn
curve from test data.

Note: for liquid stages the GUI does not expose grain selection because
liquid engines run at essentially constant thrust; the `grain_type = "liquid"`
sentinel disables the grain machinery and produces a flat thrust history.

> *Implementation rationale for the choice of this particular Shafer grain
> set is not recorded in available development history. The set covers
> the basic progressive / neutral / regressive characters plus two
> two-phase patterns, which span the range of behaviours seen in
> operational tactical and strategic solid motors.*

### 7.4 Solid motor cutoff

Liquid stages can be commanded to cut off early (the user-visible "Engine
Cutoff" field or, in orbital-insertion mode, the energy-cutoff event). Solid
stages cannot be shut off and burn to natural propellant exhaustion. The
`solid_motor` boolean on each stage gates this behaviour: the
orbital-insertion energy cutoff (applied inline in `_eom`) only fires for a
non-solid final stage, and the early-cutoff handling in the range/aim
solvers likewise applies to liquid stages — a `solid_motor = True` stage
always burns to natural propellant exhaustion.

This matters operationally because it changes the optimisation surface for
range maximisation (Section 10): a liquid-motor SCUD can trade burn time
for loft angle, but a solid-motor ICBM stage cannot.

### 7.5 Strap-on booster thrust

When `n_boosters > 0` on the top-level node (Section 6.5), the booster
contribution adds to the stage-1 thrust during the booster burn window:

```
T_total(t) = T_core(t) + n_boosters · T_booster(h)              for t ∈ [0, t_booster]
```

Each booster's vacuum thrust receives its own ambient-pressure correction
(7.2). After separation (`t > booster_burn_time_s`) only the core stage
contributes thrust. The core may optionally be delayed by
`booster_core_delay_s` to model liftoff on boosters alone before the
main engine ignites.

---

## 8. Aerodynamics

The boost-phase drag is computed by the **component build-up method**:
the total drag coefficient is assembled from independently-sourced wave,
friction, and base contributions, with optional boattail and aerospike
corrections, each evaluated against its own primary reference. This is
the USAF DATCOM-style preliminary-design approach.

```
C_D,total = C_D,wave(shape, M, l/d)
          + C_D,friction(M, Re, S_wet/S_ref)        × 1.10  (roughness)
          + C_D,base(M, S_base/S_ref)
          [+ C_D,boattail(M)]                       (if boattailed)
          [+ aerospike correction]                  (if spike present)
```

(`_cd_nose_shape`, `booster_models.py`). Each component has a
distinct, citable source: nose wave drag from
[Chin (1961)](#16-references) and the [NACA TN 4201](#16-references)
comparison report; friction from Chin's combination of Blasius
(laminar) and Schoenherr (turbulent) with the Frankl-Voishel
compressibility correction; base drag from Chin Fig. 3-15. This
replaces a single empirical `C_D(M)` lookup table used in earlier
versions and in the original Forden tool — that table is retained as a
fallback when no shape is specified (see Section 8.7).

For post-burnout flight the boost-phase build-up is replaced by a
ballistic-coefficient parameterisation (Section 8.8).

### 8.1 Nose shapes supported

The implemented nose-shape library is documented in
[`booster_models.py`](booster_models.py) under `NOSE_SHAPES` and
`NOSE_SHAPE_LABELS`:

| Key | Display name | Mathematical form | Wave-drag character |
|---|---|---|---|
| `cone` | Cone | Straight-line generator | Closed-form (Chin Eq. 3-4) |
| `tangent_ogive` | Tangent Ogive | Circular-arc generator tangent to body | Closed-form (Chin Eq. 3-9, Miles) |
| `von_karman` | Von Kármán (LD-Haack) | LD-Haack series, C = 0 | NACA RM tables |
| `lv_haack` | LV-Haack (Sears-Haack) | LD-Haack series, C = 1/3 | NACA RM tables |
| `parabola` | Parabola | y ∝ x − K·x², K = 1 | NACA RM tables |
| `blunt_cylinder` | Blunt Cylinder | Flat-faced | Sharp transonic rise, ~2.2 supersonic |

The five recommended shapes (cone through parabola) cover the range of
operational and developmental missile geometries; the blunt-cylinder option
is provided for testing and for unaerodynamic payloads. Elliptical and V-2
shapes available in some related tools are not implemented because no
properly-sourced wave-drag data was found for them with the same evidentiary
standard as the NACA reports.

### 8.2 Nose wave drag

#### 8.2.1 Cone — closed-form (Chin Eq. 3-4 / 3-6)

For a sharp cone with semi-vertex angle σ in *degrees*, valid for
attached flow (`M ≳ 1.2` for typical missile half-angles, `σ ≲ 50°`)
(`_chin_pressure_coeff`, `booster_models.py`):

```
Δp/q          = (0.083 + 0.096 / M²) · (σ° / 10)^1.69
C_D,wave,cone = Δp/q
```

The half-angle is derived from the user-specified fineness ratio
`l/d = nose_length / body_diameter` as
`σ = arctan(1 / (2 · l/d))`, then converted to degrees for the formula.

The code applies a transonic linear ramp to avoid the formula's
behaviour near the shock-attachment limit
(`_cd_wave_cone`, `booster_models.py`):

```
M ≤ 0.8:    C_D,wave,cone = 0
0.8 < M < 1.0:  C_D,wave,cone = (Δp/q at M=1.0) · (M − 0.8) / 0.2
M ≥ 1.0:    Use the formula directly
```

This smooths the subsonic-to-supersonic transition: below M = 0.8 the
nose wave drag is zero (the friction-dominated subsonic regime, handled
by Section 8.3), and the linear ramp avoids a discontinuous jump at the
critical Mach.

The 5 % accuracy quoted by Chin is adequate for the preliminary-design
role this simulator fills.

#### 8.2.2 Tangent ogive — closed-form (Chin Eq. 3-9, Miles formula)

For a tangent-ogive nose with fineness ratio `l/d`, Chin's adaptation of the
Miles slender-body formula is implemented as
(`_cd_wave_ogive`, `booster_models.py`):

```
σ              = arctan(1 / (2 · l/d))                  [radians; converted to ° for P]
P              = (0.083 + 0.096/M²) · (σ° / 10)^1.69    [cone reference]
factor         = max(0, 1 − 2·[196·(l/d)² − 16] / [28·(M + 18)·(l/d)²])
C_D,wave,ogive = P · factor
```

The reference pressure coefficient P is the Chin cone formula
(Section 8.2.1) evaluated at the tangent-ogive's equivalent half-angle;
the Miles factor reduces P toward zero as the ogive becomes more slender
(higher l/d) or as Mach increases. The `max(0, ...)` clip protects
against unphysical negative values at very high l/d where the formula
predicts more drag reduction than is physical.

The tangent ogive is the most common operational nose shape for ballistic
missiles and military rockets, and Chin reports satisfactory agreement
with correlated wind-tunnel data for preliminary design.

#### 8.2.3 Power-series shapes — NACA TN 4201 (with fineness scaling)

For the Von Kármán (LD-Haack, C = 0), LV-Haack / Sears-Haack (C = 1/3),
and parabola (K' = 1) shapes Chin provides no closed-form formula; the
wave-drag coefficient is obtained from **NACA TN 4201**, which compares
these shapes side-by-side at a reference fineness ratio
`l/d_nose = 3` (`_cd_wave_table`, `booster_models.py`).

For other fineness ratios the table is scaled by

```
C_D,wave(l/d) = C_D,wave(l/d_ref) · (l/d_ref / l/d)²
```

with `l/d_ref = 3`. This is the slender-body 1/f² scaling — exact for
cones and standard NACA practice for inter-fineness comparison of
power-series shapes.

**Note on how the lookup table is populated.** TN 4201's comparison figures
plot *total body drag* for a complete nose + cylindrical afterbody + 3.2°
boattail configuration, not nose wave drag alone. The wave-drag-only
component is isolated by **calibrating against Chin's closed-form cone
formula** (Section 8.2.1): the cone result is treated as the known reference,
and the residual offset between TN 4201's total-drag curves and the
cone-formula prediction at matching geometry gives the friction-plus-base
contribution. That contribution is then subtracted from each shape's total
drag to yield the wave-drag-only table. The source comment in the code
reads: *"Source: NACA TN 4201 comparison data (models 56-63, l/d_nose=3,
M=0.8-2.0) calibrated against Chin (1961) cone formula to isolate wave
component."*

The implemented table (at `l/d_nose = 3`):

| M | Von Kármán | LV-Haack | Parabola |
|---|---:|---:|---:|
| 0.0 – 0.8 | 0.000 | 0.000 – 0.010 | 0.000 – 0.010 |
| 0.9 | 0.010 | 0.030 | 0.040 |
| 1.0 | 0.030 | 0.070 | 0.090 |
| 1.1 | 0.050 | 0.082 | 0.100 |
| 1.2 | 0.060 | 0.085 | 0.100 |
| 1.5 | 0.069 | 0.084 | 0.094 |
| 2.0 | 0.067 | 0.077 | 0.087 |
| 3.0 | 0.058 | 0.068 | 0.077 |
| 4.0 | 0.052 | 0.061 | 0.069 |
| 5.0 | 0.047 | 0.055 | 0.062 |

Above M = 2.0 the table is extrapolated smoothly (no TN 4201 data above
M = 2); the trend from 2 → 5 reflects the expected slow decline of nose
wave drag at high supersonic Mach. Von Kármán is meaningfully (~30 – 50 %)
better than LV-Haack and parabola at the transonic peak — a real
performance difference, not a relabel.

#### 8.2.4 Blunt cylinder

For the `blunt_cylinder` option the wave-drag is a simple Mach-dependent
piecewise model:

```
M ≤ 0.8:        C_D ≈ 0.9
0.8 < M ≤ 1.5:  C_D ≈ 0.9 + (M − 0.8) / 0.7 · 1.3      (linear rise)
M > 1.5:        C_D ≈ 2.2
```

This is provided for blunt-faced payloads (e.g. unaerodynamic test
articles); it is not a recommended shape for any operational design.

#### 8.2.5 Blunting allowance

For sharp shapes (cone, tangent ogive) Chin §3-10 establishes that the
nose tip may be blunted to a radius ratio `r_N / r_b ≤ 0.2` with no
significant drag penalty. NACA TN 4201 Figure 7 (parabolic body at
fineness ratio 8.91) extends this finding — the curves at
`r_N / r_b = 0, 0.187, 0.274` are nearly indistinguishable over
M = 0.6 – 1.5, and significant drag rise only appears above
`r_N / r_b ≈ 0.4`. The empirical threshold is therefore *looser* than
Chin's conservative rule.

The code accordingly does not apply a separate bluntness correction
in the wave-drag term — bluntness only enters via the stagnation-heating
calculation (Section 13) and the Newtonian β calculator
(Section 8.8). For nose tips outside the safe regime
(`r_N / r_b > 0.4`), the user should switch to the `blunt_cylinder`
shape.

### 8.3 Skin friction

The skin-friction coefficient is computed as the Reynolds-number-weighted
sum of laminar and turbulent contributions, modified by compressibility
and a roughness allowance (`_cd_friction`, `booster_models.py`):

```
C_D,friction = (S_wet / S_ref) · C_f,mixed · C_compress(M) · 1.10
s_lam        = min(1, Re_tr / Re_L)
C_f,mixed    = s_lam · C_f,lam  +  (1 − s_lam) · C_f,turb
```

with transition Reynolds number `Re_tr = 5×10⁵` (Chin Eq. 4-3). The
`min(1, ...)` clamp ensures that when `Re_L ≤ Re_tr` the boundary layer
is treated as fully laminar (`s_lam = 1`), and for `Re_L → ∞`
`s_lam → 0` so the flow becomes fully turbulent. The length-based
Reynolds number `Re_L = ρ V L / μ` uses the active stage's body length
and the dynamic viscosity from Sutherland's law (8.3.4).

#### 8.3.1 Laminar Cf — Blasius (Chin Eq. 4-1)

```
C_f,lam = 1.328 / √Re_L
```

The Blasius flat-plate result. For typical missile boost-phase conditions
`Re_L` exceeds 10⁶ within seconds of liftoff, so the laminar contribution
is small but not negligible at the nose-body junction.

#### 8.3.2 Turbulent Cf — Schoenherr (Chin Eq. 4-2)

The incompressible turbulent flat-plate coefficient `C_f,turb` satisfies
the implicit Schoenherr equation:

```
√C_f,turb · log₁₀(C_f,turb · Re_L) = 0.242
```

Solved by Newton iteration from a Prandtl–Schlichting initial guess
(`C_f ≈ 0.074 · Re_L^(−0.2)`); convergence is 3–4 iterations to machine
precision in practice.

#### 8.3.3 Compressibility correction — Frankl-Voishel (Chin Eq. 4-6)

```
C_compress(M) = (1 + 0.2 M²)^(−0.467)
```

The compressibility factor reduces `C_f` modestly at low supersonic
speeds (about 17 % at M = 2) and more strongly at higher Mach. The
formula is fit to adiabatic-wall flat-plate data over 0 ≲ M ≲ 5.

#### 8.3.4 Viscosity — Sutherland's law

```
μ(T) = μ_ref · (T / T_ref)^1.5 · (T_ref + S) / (T + S)
```

with `μ_ref = 1.716×10⁻⁵ Pa·s`, `T_ref = 273.15 K`, `S = 110.4 K`
(`_mu_air`, `booster_models.py`). Sutherland's law provides
viscosity over the temperature range encountered in atmospheric flight
to within 1 % accuracy. Combined with `ρ` and `T` from the atmosphere
model (Section 4) and the missile's instantaneous speed and length,
this gives the Reynolds number used by the friction calculation.

#### 8.3.5 Mixed laminar/turbulent flow

The mixed Cf above assumes the boundary layer is laminar from the nose
tip to the point where local Reynolds equals `Re_tr = 5×10⁵`, then
turbulent beyond. For `Re_L < Re_tr` the boundary layer is entirely
laminar and `C_f,mixed = C_f,lam`; for `Re_L >> Re_tr` it is essentially
fully turbulent. For most operational missile boost trajectories the
turbulent regime dominates within the first few seconds.

#### 8.3.6 Wetted area — Crowell (1996)

The friction integral requires the wetted area `S_wet` of each body
component, taken as the area-weighted sum of nose wetted area and
cylindrical-body wetted area. The nose contribution is computed by
numerical integration of the appropriate generator profile
(`_s_wet_ratio`, `booster_models.py`, after [Crowell 1996](#16-references)):

| Component | Treatment |
|---|---|
| Cylindrical body | `S = π · L_body · D` — exact |
| Cone | `S = π R √(R² + L²)` — slant area, closed form |
| Tangent ogive | Closed form from Crowell |
| Parabola (K' = 1) | Closed form from Crowell Eq. 7 |
| Von Kármán / LV-Haack | Numerical 1-D quadrature of frustum panels |

#### 8.3.7 Surface roughness

Chin recommends adding 10 % to the smooth-wall friction coefficient
for typical operational missile surface finishes (Chin §4-2). The code
applies this as a flat multiplicative factor `× 1.10` on the friction
term, which is then summed with the wave-drag and base-drag terms.

#### 8.3.8 Alternatives considered

- **Reference-temperature method (Eckert 1955)**: Compute a reference
  temperature `T* = 0.5(T_wall + T_static) + 0.22(T_stag − T_static)`,
  evaluate properties at `T*`, then apply a Prandtl–Schlichting
  flat-plate formula. More physically grounded for hypersonic flow but
  requires wall temperature, which a 3-DOF trajectory tool does not
  track. The Frankl-Voishel approach is the textbook-standard simpler
  choice for preliminary work and matches NACA-era validation data
  cited in Chin Chapter 4.
- **Van Driest II compressibility correction**: higher fidelity than
  Frankl-Voishel but also requires wall conditions. Same reason for
  deferring.

### 8.4 Base drag

The base-drag coefficient is taken from Chin's digitised Fig. 3-15 (power-off
base pressure coefficient):

```
C_D,base = −C_pb · (S_base / S_ref)
```

with `C_pb` (the base pressure coefficient, negative — i.e. suction)
from `_BASE_CPB` (`booster_models.py`):

| M | C_pb |
|---|---:|
| 0.0 | 0.000 |
| 0.8 | −0.13 |
| 1.0 | −0.20 |
| 1.2 | −0.18 |
| 1.5 | −0.14 |
| 2.0 | −0.10 |
| 2.5 | −0.08 |
| 3.0 | −0.06 |
| 4.0 | −0.05 |
| 5.0 | −0.04 |

with linear interpolation between table entries. Note the inversion:
`C_pb` is negative (suction at the base), so `−C_pb` gives the positive
drag coefficient.

A useful closed-form approximation consistent with Chin's table and
USAF DATCOM:

```
M < 1:        C_D,base ≈ 0.12
M ≥ 1:        C_D,base ≈ 0.12 / M
```

agreeing with the tabulated values to ~10 % over M = 1–3.

**Power-on base bleed — modelled (screening).** Chin's Fig. 3-15 data is
explicitly power-off: the engine is not firing, so the entire base area
sees atmospheric back-pressure, producing the suction (negative `C_pb`)
that drives the drag. When the engine is firing, the exhaust plume fills
the nozzle exit and suppresses the base suction over that area, so power-on
base drag is *lower* than power-off. Thrusty applies a geometric annulus
correction (`base_bleed_ratio`, `booster_models.py`): while the active
stage is producing thrust, the base-drag term is scaled by

```
ratio = max(0, 1 − A_exit / A_base)          A_base = π(d_stage/2)²
```

where `A_exit` is the stage's total nozzle exit area (the same field the
thrust pressure-correction uses) and `A_base` its own aft cross-section.
The EOM gates this on the powered window (`_eff_burn`, honouring per-stage
cutoff, and the global cutoff); coast and reentry evaluate at `ratio = 1`
(full power-off base drag), and a stage with no stored nozzle area is
unchanged — so every vehicle without nozzle data, and every unpowered
phase, is byte-identical. Only the decomposed nose-shape build-up
(`_cd_nose_shape`) separates base drag and receives the correction; the
Forden mach-table path bakes base drag into the total and is untouched.

This is a screening midpoint, not a plume solution: a full-flowing
supersonic nozzle typically suppresses base drag almost entirely
(power-on base drag ≈ 0), while the annulus form keeps the conservative
geometric share of the aft face outside the exit. Removing the previous
full power-off charge during burn recovers a real drag over-estimate —
larger than any boattail term (which is why the boattail geometry was not
worth modelling): for a solid-motor body with A_exit/A_base ≈ 0.5 it is a
few percent of range. `test_base_bleed.py` pins the ratio math, the
base-only Cd reduction, the isolated range gain (thrust held constant),
and the no-nozzle-data no-op. Modelling the residual plume physics
(pressurised near-wake, altitude-varying exit flow) would require nozzle
exit conditions and plume CFD, outside a preliminary 3-DOF tool.

The same simplification applies in the presence of strap-on boosters
(Section 6.5): the booster cluster around the rear of the core would,
in reality, partially fill the wake region where base suction develops,
reducing the core's `C_D,base`. This interaction is not modelled.

### 8.5 Fin drag and lift

For finned vehicles (e.g. SCUD-B and other early ballistic missiles)
two contributions are added:

**Fin lift slope** (`_cl_alpha_fins`, `booster_models.py`) — the fin
normal-force-curve slope from **Barrowman's 1967 thesis, Eq 3-12** (the
canonical slender-finned-vehicle method; the thesis itself is in
`data/`), referenced to the body base area `A_ref = π(d/2)²`:

```
A_f  = s·(c_root + c_tip)/2                 # one exposed fin planform
AR   = (2s)² / A_f                          # reflected aspect ratio (span 2s)
β    = √|M² − 1|                            # Prandtl-Glauert (sub) / supersonic
Γ_c  = mid-chord sweep;  tan Γ_c = tan Λ_LE + (c_tip − c_root)/(2s)

C_Nα = N·π·AR·(A_f/A_ref) / [ 2 + √(4 + (β·AR / cos Γ_c)²) ]   ·  K_T(B)
```

The `N·π` numerator is Barrowman's cruciform result — for N=4, two fins lie in
the pitch plane, giving 2× the single-fin `2π` form (Eq 3-6). Body–fin
interference uses Barrowman's simplified slender-body factor
`K_T(B) = 1 + r/(s+r) = 1 + d/(2s+d)`.

**Regime — this is BOOSTER aerodynamics, not a glider model.** Eq 3-12 is
small-angle-of-attack, linear, fin-stabilised slender-vehicle theory (valid to
~7° AoA, subsonic through supersonic). It is used for a **booster's static
margin** (Section 8.9). It is deliberately **not** applied to a gliding RV: a
glide vehicle is a high-AoA hypersonic *lifting body* whose L/D is a Newtonian
property, supplied directly as `ro.glider_LD` and used by the glide trajectory
(Section 12). Earlier code mis-applied a (buggy) fin lift slope to the glider
L/D estimate; that has been removed.

**Fin drag** (`_cd_fins`, `booster_models.py`) — flat-plate skin friction
on the fin wetted area plus a thickness/wave term:

```
C_D,fric = (2 N · A_fp / A_ref) · C_f · (1 + 2 t/c̄)      # both faces, Mandell 1973
C_D,wave = (4 N · A_exp / A_ref) · (t/c̄)² / β            # Ackeret, supersonic
```

with `N` the fin count, `A_exp` the exposed planform, `A_fp = A_exp + ½ c_root·d`
the body-overlap planform, `t/c̄` the thickness-to-mean-chord ratio, and
`β = √(M²−1)`. This is a **subset of Barrowman's §4** fin-drag decomposition
(`C_D = C_Df + C_DL + C_DB + C_Dw`: friction + leading-edge pressure +
trailing-edge/base + wave); the leading-edge and base components are not yet
modelled, so fin drag is mildly under-counted.

For strategic and theatre-range missiles flying mostly through the upper
atmosphere, fin drag is a second-order effect and is sometimes set to
zero by leaving the fin parameters at their default zero values. For
short-range tactical missiles or atmospheric flight the fin term matters
and should be enabled.

**Planar fin drag is applied in the trajectory** (`drag_force_vector`) while
the finned stage is the active stage — a finned first stage plows through the
dense lower atmosphere during ascent, so its fin drag affects range. It is
referenced to the body base area and added to the body drag exactly as the
grid-fin term is. **No lift is added**: an ascending vehicle flies at ≈0° angle
of attack, so the fins' normal force is a stability effect (static margin), not
a trajectory force — boosters are thus treated as drag + stability, distinct
from RVs/gliders where lift (L/D) is the governing aerodynamics. (Example: the
Strypi VIII R's four large swept Castor fins cost it ~18% of range; the effect
scales with (t/c)² in the wave-drag term, so it is sensitive to the fin
thickness when that is estimated.)

**Grid (lattice) fins** (`_cd_gridfins`, `_cl_alpha_gridfins`,
`booster_models.py`) — a grid fin is a box-frame lattice of thin cells, not
a planar airfoil, so the flat-plate/Ackeret model above does not apply. The
drag model is **calibrated to Washington & Miller, AIAA 93-0035** (the S1
fine-mesh configuration: their Fig. 2 geometry and Fig. 14 drag data). The
measured axial-force coefficient (referenced to body cross-section) is
roughly **flat at ~0.040 outside transonic with a modest bump to ~0.065
(≈1.5×) peaking near M ≈ 0.95** — not a large spike. The model is:

```
C_D,gridfin = C_friction(wetted web area, chord Re)
            + C_edge   (blunt LE+TE/profile drag × web blockage area)
            + transonic bump over [M_sub, M_rec], peaking at M_peak
```

with the web blockage area `(1 − φ)·A_frame`, porosity `φ = ((p − t)/p)²` for
cell pitch `p` and web thickness `t`.

**Solidity (σ) — the practical input.** The drag is driven by the blocked
frontal fraction, the *solidity* `σ = 1 − φ = 1 − ((p − t)/p)²` (≈ 2·t/p for
thin webs). σ is the single quantity that stands in for the two lattice
details that are hardest to obtain from open sources — web (wall) thickness `t`
and cell pitch `p` (centre-to-centre). See `docs/grid_fin_solidity_diagram.png`
for a labelled frontal view of `t`, `p`, and the open window `(p − t)`.

This blockage parameterisation is independently corroborated by **Dikbaş 2015**
(METU M.S. thesis, *Design of a Grid Fin… for Transonic Flight*; held in the
Drive library, not the repo — `data/` holds no PDFs),
whose grid-fin design driver is the **web-to-cell ratio `t/w`** — i.e. exactly
`σ/2` for thin webs. His transonic design study (D = 400 mm, c = 0.1 D, fixed
1 mm web, cell width swept) spans `t/w = 0.0025–0.030`, i.e. **σ ≈ 0.005–0.06 —
all open**, and the drag-optimal direction is toward *larger* cells (lower σ),
reinforcing that transonic-efficient fins are open. The thesis also validates
its CFD against Washington-Miller (our calibration anchor), and its "unit grid
fin" (single-cell) result — that grid-fin loads scale per-cell × cell count —
is the same per-cell basis as the σ·(frame area) scaling used here. It adds no
new fielded fin and no closed-form correlation to adopt; it corroborates the
approach rather than changing it. Two ways to supply σ:

- If `t` and `p` are known, `grid_fin_solidity(t, p)` converts them to σ via
  the equation above (or just enter `grid_fin_web_thickness_m`/
  `grid_fin_cell_pitch_m` and let the model derive φ).
- If they are not, set `grid_fin_solidity` directly — estimate it from imagery.
  The reference classes below are **anchored to real published fins** (σ computed
  from their cited geometry), and the key finding is that measured grid fins are
  **very open** — far more open than a naïve "looks blocked" guess:
  - **open · σ ≈ 0.04–0.06** — two independent real fins land here:
    (i) the standard US-tested fin: 0.371 in cell pitch (centre-to-centre,
    Miller-Washington 1994 AIAA-94-1914 Fig. 1; same lattice in
    Kretzschmar-Burkhalter 1998 G12–G16), 0.008 in web → σ = 1−(0.363/0.371)² =
    **0.043** (the most-tested grid fin in the open literature); and
    (ii) a **real Russian patented design** — RU 2 686 593 C1 (Komarov et al.,
    2019), worked example: 36 mm cell pitch, 1 mm wall → σ = 1−(35/36)² =
    **0.055**.
  - **typical · σ ≈ 0.09–0.12** — the **AA-12-class reference fin** used across
    ~20 studies: Debiasi 2020 (J. Spacecraft & Rockets, DOI 1.C035626) Fig. 1
    baseline, 0.1109 D pitch, 0.007 D wall → σ = 1−(0.1039/0.1109)² = **0.122**
    (measured wind-tunnel model). The same family with the thinner 0.005 D web —
    Abate 2000's GTCM fin and the DRDC/DeSpirito fin re-used by Despeyroux 2015
    (D = 30 mm) — gives σ ≈ 0.087–0.09, so several independent groups corroborate
    this anchor.
  - **dense · σ ≈ 0.2–0.3** — occurs on real hardware, but **localised to the
    structurally-loaded root** of a large fin, not the aero span. The **SpaceX
    Falcon 9** titanium grid fin (≈1.2 m, ~8 cells of **14.5 cm** pitch across)
    is the clean example: its lattice walls are only ~2–3 mm at the aerodynamic
    *tip* → σ = 1−(142/145)² ≈ **0.04** (open, same ballpark as the MICOM fin),
    but thicken markedly toward the *root* where they carry the fin's bending
    load — a ~15–25 mm root web gives σ ≈ **0.20–0.32**. So a single flight fin
    spans the whole open→dense range. (The only fully *aero* example of a dense
    lattice is Chen 2000's thick-web DREV CFD case, σ = 0.225 — the same
    AA-12-class fin with ~3× the standard web — and the literature notes such
    thick lattices choke and add transonic drag, which is why nobody flies a
    uniformly dense fin.) Falcon 9 cell/web figures are from observation/public
    imagery; SpaceX has not published official dimensions.

  **σ is not a single number for a real fin — it varies span-wise** (open
  aero-tip → dense structural-root, as above). The single σ this model takes
  should represent the **aerodynamically active** region (the open/typical tip
  and mid-span); the dense root is a structural feature contributing little
  lift or projected drag area.

  **Empirical σ range (all real fins gathered).** Pooling every fin for which a
  σ can be computed from cited/observed geometry (web-to-cell `t/w ≈ σ/2`):

  | Fin | type | σ | t/w |
  |---|---|---|---|
  | US MICOM (W&M / Kretzschmar) baseline | measured | 0.043 | 0.022 |
  | US MICOM thick-web variant | measured | 0.064 | 0.032 |
  | Russian patent (Komarov RU 2686593) | patent design | 0.055 | 0.028 |
  | AA-12-class, 0.005 D web (Abate/DeSpirito) | measured | 0.088 | 0.045 |
  | AA-12-class, 0.007 D web (Debiasi) | measured | 0.122 | 0.063 |
  | SpaceX Falcon 9 — aero tip | observed | 0.041 | 0.021 |
  | Dikbaş transonic design sweep | CFD design | 0.005–0.06 | 0.003–0.03 |
  | — Falcon 9 structural root (~20 mm web) | observed | ≈0.26 | 0.14 |
  | — Chen DREV thick web | CFD parametric | 0.225 | 0.12 |

  So the **aerodynamically-active σ of real grid fins is ≈ 0.04–0.12**
  (`t/w ≈ 0.02–0.06`). Large **booster / launch-vehicle / SLBM** fins — the class
  relevant to most vehicles modelled here (STARS-class boosters, Topol, Falcon 9,
  Russian SLBMs) — sit at the **open end, σ ≈ 0.04–0.06**; the denser ≈0.09–0.12
  values are the smaller **air-to-air (AA-12) class**. Only structural roots and
  deliberately thick CFD cases exceed ≈0.15 (and those choke transonically). A
  sensible default for a booster grid fin is therefore **σ ≈ 0.05**; treat σ ≳
  0.15 as atypical for an aero surface.

  See `docs/grid_fin_solidity_classes.png` for the three classes side by side.
  (Earlier drafts used invented bands of 0.10–0.30; those were not anchored to
  data and read too dense — corrected here against the cited geometry. The
  Russian patent independently confirms the construction the model assumes:
  square lattice cells at 45° with wedge-sharpened edges.)

  *Origin source.* The foundational monograph — **S. M. Belotserkovsky (ed.),
  "Решетчатые крылья" (Reshetchatye Krylya / Lattice Wings), Mashinostroenie,
  Moscow, 1985** (the original of the 1987 FTD translation) — is held in the
  Drive library, not the repo (`data/` holds no PDFs; see `data/REFERENCES.md`). It
  is a theory/structures/materials work (vortex-lattice aerodynamics, structural
  mechanics, manufacturing), **not** a catalogue of fielded-missile fin
  dimensions, so it yields no new σ data point. Worth recording, though: its
  primary *dimensionless* geometric parameter (§1.1) is the **relative pitch
  t̄ = t/b** (cell pitch ÷ chord), and it shows lift depends on size and t̄,
  independent of cell-shape (frame "рамное" vs honeycomb "сотовое"). So the
  origin literature parameterises by t/b — neither the blockage *solidity* used
  here (a Western/derived convention) nor the chord/height ratio that an earlier
  draft of this note wrongly invented. σ remains the practical input for the
  drag model; t/b is the classical lift parameter.

  *Provenance:* these are mostly **research / generic test fins**, not fielded
  hardware — the open anchor is the US Army Missile Command (MICOM) grid-fin
  R&D fin (plus a Russian *patent*, which is a design rather than a known
  fielded missile), and the typical anchor is the AA-12-class reference fin
  (also the body of Abate's explicitly "Generic" Tail Control Missile). The
  closest tie to a fielded weapon is that AA-12-class geometry, which several
  papers state resembles the **Russian R-77 / AA-12 "Adder"**. Grid fins *are*
  widely fielded — the Sharma-Kumar 2019 review (INCAS Bull. 11(1)) lists, among
  others, the Soviet/Russian **SS-20, SS-21, SS-25 (Topol)** ballistic missiles,
  **MOAB**, **Soyuz** (launch-escape/braking), and **R-77/AA-12** — but it
  publishes no dimensioned cell geometry for them, so their σ cannot be computed
  from these sources. A second Russian patent — **RU 2 532 287 C1** (Leonov
  et al., **NPO Mashinostroyeniya**, 2014) — is a real missile-bureau design
  using **folding lattice stabilizers on the boost stage of a submarine-launched
  missile** (a direct analogue of the timed-deploy booster grid fins modelled
  here, §grid-fin deployment), but it likewise gives no cell dimensions. (That review also asserts the US AMRAAM uses grid fins;
  that appears to be an error — AMRAAM uses planar tail fins.) So the bands
  reflect grid-fin *technology*
  as tested in the open literature; the consistent picture across US (MICOM),
  Russian (patent), and AA-12-class sources is that real fins are **open to
  typical (σ ≈ 0.04–0.12)**, with higher σ only from deliberately thick webs.
  The review independently corroborates this: it notes thick fin panels *degrade*
  performance and that thinning the webs *reduces* drag, i.e. designs favour thin
  (low-σ) lattices.
  When σ
  is given without a pitch, a representative cell count (`_GRIDFIN_DEFAULT_CELLS`
  = 10) sets the wetted area for the *secondary* friction term only.

σ sets the blockage exactly but cannot recover the absolute mesh scale that
fixes friction, so the σ-only path agrees with the full web/pitch path to
~7% for blockage-dominated (thicker-web) fins like STARS, and less well for
unusually fine thin-web meshes (e.g. W&M S1, which is friction-dominated — use
its known `t`/`p` there). The bump represents the three flow
regimes W&M describe (Fig. 6/7): the cells **choke below M = 1**, flow spills
around the fin, the shock attaches and then passes undisturbed, restoring
supersonic behaviour by **M ≈ 1.6**. Those onset/peak/recovery Mach anchors
(`_GRIDFIN_M_SUB`/`M_PEAK`/`M_REC` = 0.75/0.97/1.60) are taken from the S1
data. A `_kantrowitz_contraction_ratio`/`_gridfin_start_mach` helper computes
the self-starting Mach for contraction ratio `CR = 1/φ` from the standard
normal-shock area relation (the class of 1-D isentropic analysis W&M used);
note its *geometric* contraction under-predicts the choke for thin-web fins
because boundary-layer blockage in the small cells is a co-cause, so the bump
anchors come from data, not geometric Kantrowitz alone.

An **edge-shape factor** (`grid_fin_edge_factor`, default 1.0 = blunt
rectangular webs) scales the pressure (edge + transonic-bump) drag but not the
friction. Miller & Washington (AIAA 94-1914, Tables 2/3) measured that shaping
the frame cross-section (single wedge, half-diamond) cuts grid-fin drag ~20–45%
subsonic and ~8–27% supersonic versus the blunt baseline, so a sharp/shaped fin
is ~0.6–0.85; the default matches the blunt W&M S1 / Miller F1 case.

**Validation:** run on W&M's exact S1 geometry the model reproduces ~0.042
(subsonic), ~0.065 (transonic peak) and ~0.038 (supersonic) to within ±13%
across M = 0.5–3.5. Three further papers (all read) corroborate the structure:

- **Miller & Washington, AIAA 94-1914** (fin-only axial force, six frame/web
  variants) confirms the transonic peak (CD rises 0.5→0.9, decreases above 0.9)
  and quantifies the edge-shape and web-thickness sensitivities above.
- **DeSpirito & Sahu, ARL-RP-19 / AIAA 2001-0257** (viscous CFD + DREV tunnel)
  gives a *total*-missile Cx ≈ 0.43 (M2) → 0.45 (M3), roughly flat — supporting
  the flat supersonic baseline and ruling out a decaying form.
- **DeSpirito et al., AIAA 2000-0391** (viscous CFD vs DERA tunnel, M 2.5)
  computes the missile body-alone, with planar fins, and with grid fins, which
  **isolates the grid-fin axial increment**: ΔCx ≈ 0.47 − 0.19 = **0.28** (4 L2
  fins, ref body area) — ~1.75× the equivalent planar-fin increment. This is the
  one fin-isolated supersonic check available: the model reproduces 0.28 at
  σ ≈ 0.33 (0.21–0.24 at σ = 0.25–0.30), and the flat M1.5→3 shape matches. Since
  the L2 fin's web/pitch (hence σ) is unpublished it is a consistency check, not
  a pinned match — but it validates the **solidity scaling** across ~10× from the
  σ ≈ 0.032 W&M S1 calibration point (and hints at a possible mild
  under-prediction of supersonic fin drag at high solidity).
- **Abate, Duckerschein & Hathaway, AIAA 2000-0937** (free-flight GTCM) finds
  total Cx flat below **M ≈ 0.77** then a steep transonic rise, independently
  confirming the choke-onset Mach (`_GRIDFIN_M_SUB` = 0.75).
- **Chen, Khalid, Xu & Lesage, AIAA 2000-0987** (Euler CFD, M 1.5/2.0,
  parametric in panel thickness and edge shape) corroborates three behaviours
  directly: thicker panels raise axial force (the solidity scaling), a
  knife-edge face "naturally produces less axial force than a blunt block"
  (the edge-factor sign), and axial force is higher at M1.5 than M2.0 with
  thick-web choking persisting to higher Mach (the transonic peak + choke).
- **Brooks & Burkhalter, J. Aircraft 1989** is the foundational subsonic
  vortex-lattice analysis underlying the Kretzschmar & Burkhalter method;
  incompressible and lift-focused, it confirms drag rises with added
  slats/blockage and the grid-fins-as-drag-brakes concept (no supersonic drag
  data).
- **Munawar, ICAS 2010** (standalone-fin RANS, M 0.5–2.5) qualitatively
  confirms the rise in grid-fin effectiveness from low to high supersonic as
  the shock is swallowed through the lattice (the recovery regime). Its drag is
  referenced to an unstated/fin-based area, has no cell spacing (no σ), and no
  Cd–Mach curve at α=0, so it is not quantitatively comparable.
- **Theerthamalai & Nagarathinam, J. Spacecraft & Rockets 43(4), 2006** is a
  shock-expansion analytical method for supersonic grid fins, validated against
  experiment for normal force, pitching moment, and axial force. Two points
  bear on this model: (a) supersonic fin axial force gently *reduces* with Mach
  (this model holds a flat supersonic baseline, matching its flat W&M S1
  calibration anchor; the decline is mild and within scatter, so it is left
  flat); (b) even this dedicated method under-predicts axial force by **<10%**
  vs experiment — i.e. ~10% is the achievable accuracy for supersonic grid-fin
  axial force, which puts this reduced-order model's ~13% (DeSpirito-2000
  check) in context rather than indicating a defect. High grid density at low
  supersonic is the hardest regime (web shock interaction), as caveated.
- **Kretzschmar & Burkhalter, "Aerodynamic Prediction Methodology for Grid
  Fins"** (NATO RTO-MP-5, 1998) is an independent analytical method (vortex
  lattice + Evvard's theory) whose grid-fin axial force decomposes the same way
  as this model — skin friction (wetted area, Cf(Re)) + pressure drag on the
  fin **frontal area** + an interference term — and is α-independent. Its
  flow-regime table (subsonic M<0.8; **choked 0.8<M<1.0**; bow shock 1.0–1.4;
  shock swallowed **1.4–1.9**) brackets our Mach anchors, and it models the
  transonic choke with the **same isentropic throat-area relation** used here,
  explicitly attributing the sub-M=1 choke to cell-wall *and boundary-layer*
  blockage — the co-cause noted above. K&B treats fin **span, cell density, and
  chord** as *independent* geometric parameters and varies each one directly
  (G12/G13 span, G12/G14 cell density, G15/G16 chord). It does **not** define a
  chord-to-height (`C/h`) normalizing ratio or state that chord scales with
  height — that framing, and any `C/h ≈ 0.07–0.35` range, were this author's
  inference and are **not** a sourced K&B design rule. Chord is an independent
  parameter; the model takes it as a direct input.
- **Washington & Miller, "Experimental Investigations of Grid Fin Aerodynamics:
  A Synopsis of Nine Wind Tunnel and Three Flight Tests"** (AGARD/RTO, 1998) is
  the umbrella dataset (26 configs; the Miller 94-1914 drag fins are G6–G11 and
  the Kretzschmar fins are G12–G16). Its Figure 8 marks the flow regimes as
  **choked flow at M = 0.75, leading-edge shock attachment at M = 1.35, and no
  shock reflection (supersonic recovery) at M = 1.60** — i.e. `_GRIDFIN_M_SUB`
  and `_GRIDFIN_M_REC` match W&M's own markers exactly. It confirms the five
  defining parameters (span, chord, height, cell spacing, web thickness) that
  the model takes as direct inputs (the G12–G16 fins are the Kretzschmar set).

**Limitation — fin sweep not modelled.** W&M (Synopsis, §3.7) found that
sweeping a grid fin forward or aft by ±30° **amplifies its axial force by a
factor of 2–3** while leaving normal force essentially unchanged (grid fins can
be used as deployable drag brakes). This model assumes **unswept** fins; a
swept installation would have substantially higher drag than computed.

The DeSpirito and Abate data are total-missile (not fin-isolated) and Abate's
fins are blunt sub-scale, so they are qualitative corroboration, not
quantitative fin-drag checks. **Caveats:** calibrated to a single blunt-edged
configuration; the bucket shifts with cell size/Reynolds number; extrapolation
to other geometries is uncertain. STARS-1 uses `grid_fin_edge_factor` = 1.0
(blunt — conservative) because its fin edge shape is not documented. Drag is referenced to body base area and added in
`drag_force_vector` only while the finned stage is active (first-stage fins
jettison at staging). The STARS-1 booster (AHW Flight-1 carrier) carries eight
first-stage grid fins via this model (dimensions are engineering estimates);
they cost it ~200 km of range from ascent drag.

### 8.6 Aerospike correction

An aerospike is a forward-projecting spike (sometimes terminated in a
small aerodisk) that creates a slender bow shock to replace the strong
detached shock of a blunt body, reducing wave drag at supersonic Mach
(`_aerospike_effective_LD`, `booster_models.py`).

The implementation replaces the actual nose's wave drag with the
*minimum* of (actual nose drag) and (effective-body cone drag), where the
effective body is a cone whose *fineness ratio* `L/D_eff` is set from the
spike geometry by a linear fit to the Ahmed & Qin (2011) dividing-streamline
angles for sharp spikes on hemisphere-cylinder models:

```
spike L/D = L_spike / D_body
spike d/D = D_aerodisk / D_body
L/D_eff   = 1.0 + (2/3)·spike_LD + 2.0·spike_dD      (Ahmed & Qin 2011 fit)
```

`L/D_eff` is then passed to the cone wave-drag routine `_cd_wave_cone`
(Section 8.2.1); the half-angle conversion `arctan(1/(2·L/D))` happens
*inside* that routine, not in the spike model itself.

For a hemispherical aerodisk tip the spike behaves as a blunt protrusion
that detaches the bow shock at the spike rather than at the body, and
the effective body is the cone running from the aerodisk to the body
shoulder. The correction is active only above M = 0.8 (where a bow
shock exists to replace).

This term is provided for cases where a missile is known to use an
aerospike (some SLBM and modern SLV designs); the GUI fields are zero
by default, leaving the standard nose drag intact.

### 8.7 Reference geometry and shroud transitions

The reference area `S_ref` used to non-dimensionalise drag depends on
flight phase:

| Phase | Reference geometry | Nose-shape source |
|---|---|---|
| Boost with shroud attached | Shroud envelope | `shroud_nose_shape`, `shroud_diameter_m`, `shroud_length_m` |
| Boost after shroud jettison, RV stays with stage | Payload geometry | `nose_shape`, `diameter_m`, `length_m` from active stage |
| Boost after shroud jettison, RV separates (`ro_separates = True`) | RV geometry | `ro_shape`, `ro_diameter_m`, `ro_length_m` |
| Coast / re-entry with `ro_beta > 0` | β-based — no `S_ref` needed | n/a (see 8.8) |
| Coast / re-entry with `ro_beta = 0` | Final stage Mach-table fallback | Final stage |

The shroud-jettison event (Section 6.3) handles the first transition. The
`ro_separates` flag handles the second. The fall-through cases use
sensible defaults; if a missile has neither a configured RV β nor a
specified RV geometry the original Forden Mach-table model applies.

### 8.8 Ballistic-coefficient parameterisation (coast and re-entry)

After final-stage burnout, drag on a reentry vehicle is conventionally
parameterised by its ballistic coefficient:

```
β = m / (C_D · A)              [kg/m²]
F_drag = q · m / β             [N]
```

This is a closed-form way to write drag without separately specifying
`C_D` and `A` — a small `β` indicates high drag (light, high-Cd), a large
`β` indicates low drag (heavy or aerodynamically clean). Operational
warheads typically run `β` ~ 10⁴ – 10⁵ kg/m²; light reentry test
articles can be ~ 10³.

The GUI provides a β calculator (Section 14 of the user guide) that
estimates β for a cone-shaped RV from its half-angle, bluntness ratio and
an evaluation Mach.  The physics lives in
`booster_models.cd_cone_hypersonic`, a three-term axial-Cd build-up
(base-area referenced):

```
C_D = C_D,pressure + C_D,friction + C_D,base

C_D,pressure : Newtonian 2·sin²θ + published bluntness excess
               (4×6 chart table, θ 10–40°, ε = r_N/r_b 0–1;
               cd_blunted_cone_newtonian)
C_D,friction : Cf · S_wet/A_base,  S_wet/A_base = (1 − ε²cos²θ)/sinθ
               (exact frustum geometry; Cf = 0.0012, a turbulent-
               hypersonic SCREENING constant, honest band 0.0008–0.0015)
C_D,base     : 2/(γM²) — the p_base → 0 hypersonic limit
```

**Why three terms (fault fixed 2026-07-25).**  The calculator originally
used the Newtonian pressure term alone.  That is adequate for blunt RVs
(θ ≥ 20°, pressure-dominated, and the added terms perturb C_D by only
2–4%), but on a slender cone the pressure term nearly vanishes —
2·sin²(5.25°) ≈ 0.017 — while friction (≈ 0.013) and base drag (≈ 0.014 at
M 10) do not.  The pressure-only estimate under-counted C_D by ~4× and
emitted β ≈ 95,000 kg/m² for a SWERVE-geometry cone, an order of magnitude
above any physical slender-RV value.  With the viscous and base terms
carried the same geometry reads β ≈ 37,000–41,000 kg/m² over M 10–12.
`test_beta_estimator.py` pins the component identities, the blunt-RV
invariance, and the slender-cone sanity band — deliberately as physics
identities, never as a fit to any vehicle's reconstructed β.  Note the
estimator describes a **bare cone**: wings, fins or flaps add wetted area
and interference drag it does not carry, so a winged vehicle's true β is
lower than the bare-cone estimate.

**Biconic (two-cone) bodies** (`cd_biconic_hypersonic`).  A biconic RV — a
steep forward cone on a shallow aft frustum (the C-HGB / MaRV / HGV class)
— cannot be represented by the single cone without inventing an
"equivalent" half-angle.  The build-up is summed over both segments,
base-area referenced:

```
C_D,pressure = cd_blunted_cone_newtonian(θ1, r_N/r_break)·(r_break/r_b)²   (fore)
             + 2·sin²θ2·(1 − (r_break/r_b)²)                              (aft annulus)
C_D,friction = Cf·[ (r_break² − (ε·cosθ1)²)/sinθ1                          (fore wetted)
                  + (1 − r_break²)/sinθ2 ]                                (aft wetted)
C_D,base     = 2/(γM²)
```

The half-angles are **derived**, not entered: `biconic_angles()` takes the
two free inputs (`fore_length_m`, `break_diameter_m`) and returns
(θ1, θ2, r_break/r_b, ε) against the stored base diameter, length, and nose
radius.  Two exact single-cone reductions anchor it as regression tests:
`break_ratio → 1` collapses the aft annulus and returns
`cd_cone_hypersonic(θ1)` component-for-component, and a sharp θ2 = θ1
biconic equals the single cone for any break location.
`test_biconic_estimator.py` pins the reductions, the component and geometry
identities, and a slender-RV β band.

**As-flown biconic (not just the estimate).** A declared biconic is a
first-class shape through the whole flown build-up, not only the manual β
dialog. `biconic_nose_geometry(params)` is the single shared resolver;
`cd0_biconic_body()` composes the two-cone build-up above **plus** the
cylindrical afterbody friction into the body Cd0 that drives the derived
β(Mach) and the whole-airframe L/D (§8.10), and `biconic_nose_cp_fraction()`
gives the trim gate (§8.9) an area-weighted two-cone centre of pressure
(fore cone at 2⁄3 of its length, aft frustum by the Barrowman transition
formula) rather than a single-cone fraction — so the break ratio moves the
static margin. The subtractive schematic (§6.4) draws the two cones to
match. This closes a DRAWN ≡ FLOWN gap one level below the schematic: the
biconic fields used to be read *only* by the β dialog, so a user could
declare a biconic, type a biconic β, and unknowingly fly a single cone with
a single-cone CP. `test_biconic_front_end.py` pins all four consumers moving
together and the two reduction identities. Framework note: the flown biconic
Cd0 is the hypersonic Newtonian two-cone model (M ≥ 3), distinct from the
Chin/NACA single-nose build-up (§8.2) — comparable but not identical at a
shared Mach; single-profile noses (cone, ogive, Von Kármán, LV-Haack,
parabola) were already end-to-end because every consumer keys on the shared
shape string.

**Biconic on ascent, too.** The boost-phase drag (`_cd_nose_shape`, used for
an unshrouded biconic body or bare RV) takes the SAME two-cone treatment, but
in the Chin cone-pressure framework rather than the hypersonic-Newtonian one:
the wave term is the fore cone on the break area (br²) plus the aft frustum on
the annulus (1−br²), each at its own half-angle, friction and base unchanged.
This is correct for transonic/supersonic ascent (it keeps the M0.8–1.2
wave-drag peak the Newtonian form floors away) and reduces EXACTLY to the
single cone when the half-angles are equal.  A shrouded RV flies on the
fairing's shape until jettison, so this applies only to bodies exposed through
the dense atmosphere.  `test_biconic_front_end.py`.

For blunted cones the pressure drag is the **exact closed form**

```
C_D = 2·sin²θ + ε²·cos⁴θ            (base-area ref, ε = r_N/r_b)
```

the superposition of the spherical nose cap (`ε²·(1−sin⁴θ)`) and the cone
frustum it caps (`2·sin²θ·(1−ε²·cos²θ)`, tangency at `r = r_N·cosθ`), which
sum exactly to the expression above.  It is the zero-AoA reduction of the
developed Newtonian impact expressions for complete and partial conic and
spheric bodies in **Wells & Armstrong, NASA TR R-127 (1962)** (also Anderson,
*Hypersonic and High-Temperature Gas Dynamics*).

This **replaced** an earlier unattributed "Ref (4) Ch. 5" interpolation
chart (4 half-angles × 6 nose ratios) that was found, on cross-check against
the closed form, to materially **under-count** blunt-nose pressure drag —
e.g. at θ=10°, ε=0.6 the chart gave 0.08 where the correct value is 0.40 (a
5× error), because it merely interpolated between the sharp cone (2·sin²θ)
and a hemisphere (1.0) rather than integrating the sphere-cone. Estimated β
for blunt-nosed reentry objects therefore **drops** relative to older runs
(higher pressure drag → lower β); sharp objects (ε=0) are unchanged, and for
slender objects friction still dominates the total so the shift is modest.

For hypersonic glide vehicles the constant-β model is augmented by a
lift term and (optionally) a polar-drag model — see Section 12.

**Lifting-body forms (wedge, half-cone) — data model and depiction only.**
`ROParams.body_form` declares how the airframe carries its volume:
`"axisymmetric"` (default — cone or biconic body of revolution), `"wedge"`
(flattened wedge lifting body, HTV-2 class; `diameter_m` is the **base
depth**, and the planform span is stored in `body_span_m` — tip-to-tip
base width, BODY geometry distinct from the wing planform, which
`wing_geometry()` never reads; unset (0) is flagged by the schematic
rather than invented), or `"half_cone"` (flat diametral plane over a
conical lower surface; `diameter_m` is the full cone diameter, so the
side-elevation depth is ⌀/2).  The schematic draws the asymmetric
silhouette (flat flank + sloped surface) and names the form in the caption;
`biconic` applies only to bodies of revolution and is ignored otherwise.

The lifting-body trim estimator (Phases 2a–2c, and the 2b completion:
cone/biconic α-sweep on the same sector machinery, the half-cone + delta-wing
composite, and the swept-cylinder leading edge — design and anchors in
PHASE2_LIFTING_BODY_PLAN.md, implementation `lifting_body_sweep` in
`booster_models.py`) supplies trim-consistent β and L/D from measurable
geometry.  **Phase 3 (2026-08-01)** then closed the three limitations this
section used to list, touching trajectory physics for the FIRST time and
only behind a body-form gate (every axisymmetric vehicle is byte-identical,
pinned by test):

1. *Pull ceiling — CLOSED for lifting forms.*  `C_L,max` is now derived
   from the stored geometry: the Newtonian pressure C_L at the same 25° AoA
   cap (wedge: needs its `body_span_m`, else keeps the Munk 0.873 body
   value, flagged not invented; half-cone: from ⌀/L plus any declared wing
   planform).  A flat-bottomed wedge's pull limit rises severalfold; a fat
   half-cone's honestly falls.  Because the derived value is converted at
   force level (× A_sweep/A_ref), the pull limit `q·C_L,max·A_ref/m` is now
   INVARIANT to the reference-area convention — which also closes old
   limitation 3 for the derived forms.
2. *Trim-β vs zero-lift-β — CLOSED by the estimator* (the dialog's "Use β"
   writes β at zero lift, never trim β, from one consistent sweep row).
3. *Symmetric-polar camber — CLOSED by the offset polar.*  "Use β and L/D"
   also persists the sweep's trim row (`trim_alpha_deg`, `trim_CL0`,
   sweep-native coefficients) on the RO.  The polar becomes Lobanovskii's
   trinomial `C_D = C_D0 + k·[(C_L − C_L0)² − C_L0²]` — anchored so
   `C_D(0) = C_D0` exactly (β keeps its zero-lift meaning) with k
   back-solved ON the offset parabola so the polar's (L/D)max stays exactly
   `glider_LD` (C_L* = √(C_D0/k) is unchanged by the offset; a C_L0 too
   large for the discriminant, > LD·C_D0/2, is inconsistent with the stated
   L/D and falls back to symmetric rather than inventing).  Measured
   support: Fetterman TN D-2942 Fig. 6b's C_N zero-crossing at negative α.
   The stored α* additionally pre-fills the windward-heating operating AoA
   (§13.8) when no static-margin trim exists — attitude and L/D from the
   SAME sweep, the Candler consistency guard.

### 8.9 Static margin and grid-fin sizing

The static margin tells whether a vehicle's fins are appropriately sized for
stable, controllable flight. It is computed (`grid_fin_sizing.py`) the Barrowman
way — the centre of pressure is the normal-force-weighted average of the
component contributions (thesis Eq 3-107):

```
x_CP = Σ_i (C_Nα,i · x_i) / Σ_i C_Nα,i
SM   = (x_CP − x_CG) / D            [calibers]
```

A margin of **~0.5–2 calibers** is the conventional "appropriate" band; below 0
is unstable, well above ~2 is over-finned. Two uses: **sanity-check** an OSINT
fin estimate, or **invert** for the fin area a vehicle of a given diameter
*should* carry (fins scale as area ∝ D² to hold the margin in calibers).

Component normal forces (all referenced to body base area `A_ref = π(d/2)²`):

- **Nose / body** (Barrowman Eq 3-65/3-66): `C_Nα = 2·A_base/A_r` (= 2 for a
  nose capping the body), with CP at a shape-dependent fraction of nose length
  (cone ⅔·L_N, tangent ogive ≈0.466·L_N, Eq 3-89/3-90).
- **Fins**: Barrowman Eq 3-12 (Section 8.5) for planar fins; the dedicated
  grid-fin slope `_cl_alpha_gridfins` for grid fins.

CG is estimated from the stage mass stack (mass-weighted longitudinal centroid
at liftoff/full — the most-aft CG, i.e. the *minimum*-margin case), overridable.
This is the **booster** stability tool; it does not apply to a gliding RV.

**Diameter transitions** are included (`body_normal_force` via `_stack_layout`):
Barrowman's body term is `ΔC_Nα = (2/A_r)·ΔA` at *every* cross-sectional-area
change, not just the nose. A multistage stack with a narrow payload/upper stage
stepping up to a wide lower stage has a forward-facing shoulder that adds a
stabilising (CP-aft) normal force. The net body C_Nα telescopes to `2·A_base/A_r`
(= 2 when the reference is the base), but its *distribution* — hence the body CP
— shifts aft when the transitions are modelled. For STARS-1 the narrow HGB→wide
first-stage shoulder moves the body CP from 1.33 m (nose-only) to 2.82 m,
raising the static margin from ~1.43 to ~1.59 cal. (Remaining limitation: a
separate payload section, when the nose is not the RV, is not yet inserted as
its own diameter step — only the nose and stage-to-stage transitions.)

### 8.10 No-separation glider: derived L/D and the trim/control gate

When the RV does **not** separate, the gliding/maneuvering vehicle is the whole
airframe and its L/D is an emergent geometric property (not a designed input,
as for a separating RV). Two modules handle this.

**Whole-missile L/D (`glider_ld.py`)** — the semi-empirical body+fin build-up at
angle of attack (the theoretical core of Missile DATCOM), assembled from the
primary sources cited here. (Those documents are **not in the repo**: `data/`
holds no PDFs — papers live in Drive per `data/REFERENCES.md`, which does not
list these either. The citations are the record, not a file you can open; the
one cross-check with committed primary material is Digital DATCOM, in
`validation/datcom/`.) Body normal force from **Jorgensen (NASA TR R-474)** Eq 2.12
— slender-body potential + **Allen-Perkins (NACA 1048)** viscous crossflow;
wing-body interference from **Pitts-Nielsen-Kaattari (NACA 1307)**, whose
slender-body factors satisfy the identity `K_W(B)+K_B(W) = (1+r/s)²`; combined
with Jorgensen Eq 5.3's `sin(2α)/(2α)` high-AoA correction. Referenced to body
base area:

```
C_Nα_pot = 2·(A_b/A_r) + (1+r/s)²·(C_Lα)_W·(S_W/A_r)
C_N(α)   = C_Nα_pot·sin(2α)/2 + η·C_dn(M_n)·(A_p/A_r)·sin²α
C_A(α)   = C_A0·cos²α ;  C_L = C_N cosα − C_A sinα ;  C_D = C_N sinα + C_A cosα
```
where `A_p` is the body's true side-projected **planform** area (the area the
Allen-Perkins crossflow term acts on): nose + cylindrical afterbody,
`A_p = fill·L_nose·d + (L−L_nose)·d`, with a shape fill factor (cone 0.5, tangent
ogive ≈0.67 by exact integration). The two crossflow factors are **sourced, not
assumed**: `η = 1` for supersonic/hypersonic free-stream Mach per **Jorgensen
(NASA TN D-7228, 1973)** — the analytic statement of this exact build-up
(Eq. 1) — and the crossflow drag coefficient `C_dn` is a function of the
crossflow Mach `M_n = M·sinα`, read from **Gowen & Perkins (NACA TN 2960, 1953)**
Fig. 7: ~1.2 at low M_n, a transonic peak ~2.1 at M_n=1, decaying to ~1.34 at
M_n=2.9. L/D is maximised over α. It is a preliminary-design estimate (a slender
body is a poor lifting shape, so L/D is modest, ~2–3).

**Validation against Digital DATCOM (USAF, public-domain, PDAS).** The build-up
was cross-checked against Digital DATCOM (AFFDL-TR-79-3032) for the finless
slender reference body (D=0.5 m, L=4 m, 1.5 m tangent-ogive nose) at M2/3/5,
α=0–20°. Zero-lift drag agrees within ~10% (C_A0: glider_ld 0.245/0.184/0.121 vs
DATCOM 0.272/0.189/0.109), and the best-glide AoA matches closely (16/14/12° vs
16/14/10°). The cross-check drove two sourced corrections:

1. The original `A_p = ½Ld` (a cone-only triangle) underestimated the planform
   of a body with a long cylinder, driving L/D ~20–30% low (worsening with
   Mach); replaced by the true nose+afterbody planform.
2. The original constant `C_dn = 1.2` under-predicted crossflow lift at high
   Mach — at a M5 best-glide AoA the crossflow Mach `M_n = M·sinα ≈ 1`, where
   the cylinder `C_dn ≈ 2.1`, not 1.2 — which is why the gap grew with Mach;
   replaced by `C_dn(M_n)` from Gowen-Perkins TN 2960 Fig. 7.

Together these bring L/D to within **−5%/−9%/−10%** (M2/3/5) of DATCOM, with the
residual now roughly **flat** in Mach instead of growing. `glider_ld` remains
slightly conservative (under-predicts L/D — the safe direction for range); the
~10% residual is consistent with the slender-body potential slope vs DATCOM's
fuller body-lift method. The input deck, reference output, and comparison script
are in `validation/datcom/`.

**Trim/control gate (`trim_gate.py`)** — a derived L/D is only *achievable* if
the airframe can trim and hold that AoA. The pitching moment about the CG is
summed **term by term**, because the build-up's normal force is nonlinear in α
and its three contributions act at three different stations
(`glider_ld.cn_components` regroups the same `C_N` the L/D sweep forms, exactly):
```
C_m(α,δ)·d = −[ C_N,body(α)·(x_body−x_CG)          slender-body potential, Barrowman c.p.
              + C_N,cross(α)·(x_planform−x_CG)     Allen-Perkins crossflow, planform centroid
              + C_N,fin(α)·(x_fin−x_CG)            fin + N-K-P carryover, fin station
              + control_eff·C_Nα,fin·δ·(x_fin−x_CG) ]   commanded control
α_trim(δ) = root of C_m = 0, by bisection on the sweep's own 1–59° interval
```
The crossflow term grows as `sin²α` on the body **planform**, well aft of the
nose c.p., so the centre of pressure migrates aft and the airframe stiffens with
incidence. That is the restoring mechanism, and it is why the balance has to be
solved rather than linearised.

Outcomes: **SM ≤ 0 → unstable → tumbles → ballistic** (L/D≈0); **δ_max = 0
(fixed surfaces) → trims at zero incidence → ballistic**, whatever the
aerodynamic ceiling; `α_trim,max ≥ α_LDmax` → control reaches best glide (full
L/D); `α_trim,max < α_LDmax` → **control-limited**, achievable L/D is the best
value of the curve over the reachable band `(0, α_trim,max]`; **no root at
δ_max** → the control moment beats the restoring moment everywhere on the sweep,
reported as "not a glide" rather than as unlimited authority. Achievable L/D is
the best value over the reachable band, not the value at its endpoint, because
deflection is commandable and L/D falls away beyond best glide. The gate uses
the static margin of §8.9 (body incl. transitions + fins) and the `glider_ld`
L/D curve, with a mass-stack CG and aft fin station (both overridable). It is a
preliminary gate, not a 6-DOF trim solution.

**Control authority is read from the vehicle, not assumed.** The reentry
object's `glider_control_surfaces` descriptor (`none` / `small` /
`substantial` / `unknown`) sets the usable one-sided deflection: `none` → 0°,
`small` → 5°, `substantial` → 15°, `unknown` → 10° **reported as an
assumption**. An explicit `glider_flap_deflection_deg` overrides the tier, still
capped at the separation limit; `damping_estimate.py` caps at the same 15°.
Control effectiveness is real-gas derated above M≈7 (Maus et al., *J. Spacecraft
& Rockets* 21(2), 1984, and the STS-1 trim anomaly), matching that module's
`REAL_GAS_DERATE`.

The cap is bounded by **incipient separation** of the flap boundary layer.
Kumar & Stollery (*The Aeronautical Journal* **100**(996), June/July 1996,
pp. 197–208) carry the Needham & Stollery criterion (AIAA 66-455) as their
Eq. (6):

```
M∞·β_i = 80·χ̄_L^(1/2) ,    χ = M³·√(C/Re_x) ,    β_i in degrees
```

evaluated at the hingeline length. At the paper's own conditions (M 8.2,
Re∞/cm 9.0 × 10⁴, L = 15.9 cm) this returns 6.62° against their stated 6.6° —
a check on our transcription and units, not an independent validation, since
their 6.6° is this same equation evaluated rather than a measured angle. What
they measured is the bracket around it: with a sharp leading edge β = 5° is
attached and β = 10° separated. (Leading-edge bluntness changes that — at
d = 4–6 mm, β = 10° attaches — but it also "causes significant loss of control
effectiveness", so it buys attachment rather than authority.)
That is the **laminar** branch. Needham's Fig. 11 also gives a transitional
branch and a **turbulent** branch roughly 5× higher (`β_i/√M∞ ≈ 9.7–13`).
Thrusty's bodies run Re_L ≈ 1.4 × 10⁶–4.9 × 10⁷ (6 m body) at the fin station over
M 3–10 and 25–40 km, i.e. past the laminar branch, where the criterion gives
**17–41°**. The 15° cap is therefore *conservative* against the onset in the
regime actually flown, not a laminar limit being exceeded. Turning the tiers
into a computed `β_max(M, Re_L, boundary-layer state)` is the outstanding
improvement — see `TODO.md` item 9(d).

**Control effectiveness is now derived, not assumed.** `C_Nδ = control_eff ·
C_Nα,fin` with

```
control_eff = k_W(B) / K_W(B)
```

both from NACA Rep. 1307 slender-body theory, normalised by the same wing-alone
`(C_Lα)_W` (their Eqs. 5 and 8), so the ratio is exact within that theory.
`K_W(B)` is `glider_ld.nkp_interference`; `k_W(B)` is `nkp_deflection_factor`,
the closed form of their **Eq. (19)** in `τ = s/r`.

The body carryover *cancels* rather than being neglected. The full fin
construction is `[k_W(B) + k_B(W)] / [K_W(B) + K_B(W)]` (Moore, McInville &
Hymer, JSR 33(3), 1996 — matching the carryover `c_na_fin` already carries), and
NACA 1307 Eq. (34) gives `k_B(W) ≈ k_W(B)·K_B(W)/K_W(B)`, stated to differ from
the exact Eq. (33) value by no more than 0.01. Substituting, the bracket divides
out exactly and leaves `k_W(B)/K_W(B)`.

The transcription of Eq. (19) is checked two ways: against its theoretical
limits (→ 1 as the body vanishes, and again as the fin is buried in it), and
against **Chart 1** of the same report, which plots all four factors against
`r/s` — `k_W(B)` starts at 1.0, dips to a shallow minimum near 0.93 around
`r/s = 0.4`, and returns to 1.0, while `K_W(B)` runs 1.0 → 2.0. Both are pinned
by tests.

This replaced a hard-coded `0.85` with no backing document. The derived value is
a **function of fin geometry**, running ~1.0 for a vanishing body down to ~0.52
for a fin nearly buried in one, so no constant could have been right in form.
For typical tail fins it lands well below 0.85 — a Scud-B's fins give 0.66 —
meaning the old constant overstated control authority, the non-conservative
direction.

*Provenance, stated plainly.* Both anchors are now marked **[verified]** in
`docs/cl_margin_references.md`, read against the primary PDFs on 2026-09-07:
Kumar & Stollery 1996 and Needham & Stollery AIAA 66-455. Getting here took two
wrong readings, both recorded in that file rather than quietly overwritten. The
figure entered as a `[snippet]` — a web-search extract describing a "5–15° band
at M ≈ 10" that the paper does not contain — adopted because it replaced a 25°
default carrying **no citation at all**. A later pass then "corrected" the
citation and the numbers in the wrong direction. The lesson worth keeping is not
about the marking, which worked: it is that the snippet became load-bearing by
being *reused across modules on internal authority* rather than by anyone opening
the paper, and that a correction made without the primary in hand can be worse
than the error it replaces.

**Where the CG has to be (`cg_targets`).** "Set the CG forward" is not
actionable without a station, so the gate answers the question directly. Since
`SM = (x_cp − x_cg)/d` is the gate's own definition, a target margin inverts
exactly:

```
x_cg(SM) = x_cp − SM·d
```

`cg_targets()` returns the **neutral point** `x_cp` (the CG must be forward of
it or the body tumbles), the current CG and its margin in both calibers and
metres, the CG that would buy a requested margin, and optionally the CG at which
the body first reaches its full aerodynamic ceiling. That last one is found by
scanning the stable range rather than inverting, because trim angle depends on
the CG through the whole nonlinear moment balance, not through the static margin
alone; it is skippable, since it costs a few hundred gate evaluations and the
live previews only need the closed-form fields.

The estimator reports the **trade**, not just the stability side. Moving the CG
forward buys margin but stiffens the airframe, so the same deflection trims to a
smaller angle of attack and achievable L/D *falls*. There is normally a usable
window rather than a best value, and an estimator that showed only the margin
would push a user straight through it. Both directions are pinned by tests.

*What is validated, and what is not.* The gate's dependency is the **moment**,
so `validation/datcom/compare_datcom.py` now also compares the modelled centre
of pressure against the committed DATCOM `CM`/`XCP` columns (which had been in
the repo unread since the case was added). Result for the finless reference
body:

| Mach | DATCOM x_cp, α 2→20° | model x_cp | error |
|---|---|---|---|
| 2 | 1.43 → 1.91 m | 0.93 → 1.73 m | −12.4 … −4.6 % of L |
| 3 | 1.61 → 1.99 m | 0.93 → 1.84 m | −16.9 … −3.7 % of L |
| 5 | 1.72 → 2.01 m | 0.93 → 1.75 m | −19.7 … −6.3 % of L |

Both curves migrate **aft** with α, so the two-station mechanism is the right
shape: the `sin²α` crossflow term on the planform does overtake the potential
term and stiffen the airframe, which is what supplies the restoring moment the
linearised gate could not see. But the model's c.p. is **forward of DATCOM at
every point**, by up to ~20 % of body length, worst at low α and high Mach. The
cause is structural: slender-body theory puts the entire potential normal force
at the nose c.p., while the real body-alone c.p. at low incidence lies much
further aft.

**The direction is non-conservative for the gate.** A c.p. modelled too far
forward understates the restoring moment, so a given deflection trims to a
*higher* α than it really would, and the gate over-grants glide. No correction
is applied: fitting one would be a calibration with no source behind it, which
is exactly what this project's derive-don't-invent rule forbids. The bias is
instead measured, pinned by `test_cp_bias_is_forward_and_bounded`, and recorded
as an open item in `TODO.md`.

*Is the reference good enough to blame the model?* Yes. **Sooy & Schmidt**
(JSR 42(2), 2005) validated Missile DATCOM against wind-tunnel data and found its
centre-of-pressure error below **2 % of body length at any angle of attack** for
body-wing-tail (M1.5, M4.6) and body-tail (M2.0) configurations; **Simon & Blake**
(AIAA 99-4258) report c.p. "well predicted at all angles of attack" at supersonic
speeds. The 5–20 % gap above is therefore model error, not reference noise. (Sooy
& Schmidt's body-*alone* case is explicitly inconclusive — the test data are
biased, non-zero C_N at α = 0 — so it is not used here.)

*The stations themselves are sourced.* **Simon & Blake**, describing Missile
DATCOM's implementation of this same Allen-Perkins/Jorgensen build-up, state that
"the center of pressure of the body at large angles of attack is effectively at
the planform centroid", and give the moment as the two-station sum
`C_m = (x_ac − x_cg)·C_N,potential + (x_c − x_cg)·C_N,viscous` (their Eq. 6) —
the form used above — with the **fin's** viscous part acting at the **panel
centroid** rather than the fin aerodynamic centre. `glider_ld` returns that panel
centroid in closed form for a straight-tapered panel (it reduces to the root
mid-chord for an unswept rectangular fin) and the gate places the fin's crossflow
term there. The same source explains the low-α end of the bias: DATCOM uses
empirical charts and Van Dyke hybrid theory there, not the nose-concentrated
slender-body result, which is why the gap is worst at low α.

Note the remaining scope limit: the committed deck is **body-alone and finless**,
so while the fin's viscous *station* is now sourced, the fin normal-force term
and the control-deflection term are still validated against no data at all.

*Why this replaced a linearised relation.* The previous gate used
`α_trim,max = (C_Nδ/C_Nα,total)·(x_fin−x_CG)/(x_CP−x_CG)·δ_max`, which assumes a
constant normal-force slope and a **fixed** centre of pressure. Because `x_CP`
is a weighted average of `x_body` and `x_fin`, the lever
`(x_fin−x_CG)/(x_CP−x_CG)` exceeds 1 for **every** stable CG, so `α_trim,max`
had a hard floor of `control_eff·(C_Nα,fin/C_Nα,total)·δ_max` — 12.8° for a
Scud-B body, already above its 11° best-glide α. The gate therefore returned the
full aerodynamic peak at every CG in the stable range, with `α_trim` running from
33° to 642° as the static margin approached zero. A gate whose failure mode is
to grant the unconstrained ceiling is not a gate; this was the open item recorded
in `BODY_GLIDE_LD_PLAN.md` §7.1 and `TODO.md`.

**Wiring.** The GUI L/D estimator calls `whole_booster_LD` directly. In the
trajectory, a no-separation body glider left at the sentinel `glider_LD = 0` has
its value auto-derived once at integration setup; a separating RV, or any body
with an explicit `glider_LD > 0`, is left untouched (a separating HGV's L/D is a
designed property of an aeroshape Thrusty does not store, so the slender-missile
build-up would not apply). The derive runs at setup, not per step (it is outside
the EOM hot loop). The setup sequence is:

1. Run the trim/control gate at `GLIDE_MACH_REF = 5`. If **SM ≤ 0** the body
   cannot hold a trim AoA → the effective reentry attitude is forced to
   `tumbling` (§8.11: derived tumbling β, no lift). If **control-limited**, the
   ceiling is the L/D the fins can actually trim to, not the aerodynamic peak.
2. If the gate passes (`LD_achievable > 0`), build a **Mach-varying `(L/D)_max`
   table**: sample `whole_booster_LD` over `M ∈ {1.5, 2, 3, 4, 5, 6, 8, 12}`,
   cap each node at the gate's `LD_achievable`, and stash a linear interpolator
   on the run parameters. The **numerical** glide modes (`skip_glide`,
   `skip_to_equilibrium`, `damped_glide`) interpolate it on the local Mach each
   EOM step; below M1.5 the M1.5 value is held (linear wing theory invalid) and
   above M12 the M12 value. The **analytical** Tracy/Acton modes keep a constant
   L/D (their closed form requires it), evaluated at the scalar fallback = the
   M5 table value. `commanded_LD` (the plan) still caps the whole curve.

The measured airframe swing is ~12–16 % over M1.5→M5 (largest for terminal-phase
quantities flown at M2–4). For total **range** the effect is sub-1 % on a
non-separating body: such a body is aeroballistic (range set by the
exo-atmospheric arc, with the atmospheric glide a terminal sliver), so the
Mach dependence bites the terminal phase, not the down-leg length.

**L/D during a pull-up maneuver.** The geometry-derived `L/D_max` above is the
*peak* lift-to-drag, available only at the best-glide angle of attack. A
non-separating warhead that pulls up does not fly there. A pull-up commands a
load factor `n` (capped at `glider_pullup_g_max`), so the lift it must generate
is `L = n·m·g`, i.e. a lift coefficient

```
C_L = n·m·g / (q·A_ref) ,     q = ½ρV²
```

The *effective* lift-to-drag at that commanded `C_L` follows from the drag polar
(§12.2.2, `_aero_polar`), whose two coefficients are back-solved from the
vehicle's ballistic coefficient β and its `L/D_max`:

```
C_D0 = m / (β·A_ref) ,    k = 1 / (4·C_D0·(L/D_max)²)
L/D(C_L) = C_L / (C_D0 + k·C_L²)
```

This peaks at `C_L* = √(C_D0/k)`, where it recovers exactly the input
`L/D_max = 1/(2·√(C_D0·k))` (and `C_D* = 2·C_D0`). Pulling harder than `C_L*`
— any load factor above the equilibrium-glide value — drives `C_L` up the
induced-drag branch `k·C_L²`, so the *instantaneous* L/D drops below `L/D_max`:
a steep pull-up trades glide efficiency for turn rate. The command is bounded —
`C_L ≤ C_L_lim ≈ 2·(25°·π/180) ≈ 0.87` (the slender-body `C_L ≈ 2α` at α_max)
and `n ≤ glider_pullup_g_max` — so the worst-case induced-drag penalty is
capped. For a **non-separating** body the `L/D_max` in these formulas is the
geometry-derived value from this section; for a separating RV it is the designed
input. The pull-up arc itself and the guidance modes that drive it are §12.

### 8.11 Reentry attitude: trimmed vs. tumbling drag

"Non-separating" hides two distinct physical regimes, and the reentry plan names
which one applies through `reentry_attitude ∈ {trim, tumbling}`:

- **Trim** — a stable, controlled body (Iskander / MaRV / Pershing-II class).
  Drag is the aeroshell's ballistic coefficient β as given; lift is the
  geometry-derived L/D of §8.10, subject to the trim gate. This is the default.
- **Tumbling** — an uncontrolled body (a spent stage that reenters, a failed
  RV, or a finless/aft-CG body the trim gate flags SM ≤ 0). It generates **no
  lift**, and its β is *derived* from geometry as a tumbling cylinder rather
  than inherited from the aeroshell. The graft of "aeroshell β + stage mass"
  would be physically meaningless here: a tumbling stage presents a huge mean
  projected area (low β), the opposite of a streamlined RV.

The tumbling β uses a **two-orientation Hoerner form**, each orientation
carrying its own hypersonic drag coefficient on its own projected area
(`tumbling_cylinder_beta(..., cd=None)`, `booster_models.py`):

```
(C_D·A)_eff = ½ [ C_D,broadside · d·L  +  C_D,end · π d²/4 ]
β_tumble    = m / (C_D·A)_eff
```

with coefficients transcribed from Hoerner, *Fluid-Dynamic Drag* (1965),
Ch. XVIII (hypersonic bluff bodies):

| Term | Coefficient | Hypersonic value | Source |
|---|---|---|---|
| impact-pressure coefficient | `C_p• = 1.84 − 0.76/M²` | → 1.84 (M→∞) | eq. (41) |
| broadside (cross-flow cylinder) | `C_D = ⅔·C_p•` | ≈ **1.2** | eq. (44), Fig. 24 |
| end-on (blunt cylinder face) | `C_D = 0.89·C_p•` | ≈ **1.6** | Fig. 22 |

Below M ≈ 3 the hypersonic form is invalid; `C_p•` is floored at the
incompressible bluff-body level (~1.2). Continuum anchors from the same source
(§3-5/§3-6, Figs. 12/28) — 2-D cross-flow cylinder `C_D ≈ 1.17–1.2` subcritical,
normal disc 1.17 (3-D) — bracket the low-Mach floor. This is the **same**
function that computes spent-casing debris arcs (§14.3), which keep the legacy
single-`C_D = 1.0` mean-area form; the two-term Hoerner form is selected
(`cd=None`) only for a reentering body's derived β.

`effective_ro` applies this: when the run's attitude resolves to `tumbling` it
replaces the aeroshell β with `β_tumble`, disables the glider, and zeroes L/D.
The mass/geometry inheritance for a non-separating body (mass, diameter, length
from the last-stage burnout state) is unchanged.

---

## 9. Guidance laws

In a 3-DOF formulation the missile's attitude is not a state variable —
it is *prescribed* by the guidance law as a unit thrust-direction vector
at each time step. Thrusty implements three guidance backend modes,
exposed in the GUI through a four-item "Ascent Mode" dropdown:

| GUI label | Backend mode | Notes |
|---|---|---|
| Simple pitch profile | `pitch_program` (basic) | Linear pitch to a single burnout angle |
| Advanced pitch profile | `pitch_program` (per-stage) | Per-stage pitch overrides exposed |
| Gravity turn | `true_gravity_turn` | Velocity-aligned thrust (Wright 2020) |
| Orbital insertion | `orbital_insertion` | Two-phase boost + horizontal final-stage burn |

Yaw (dogleg) maneuvers can be layered on top of any mode, either as
mission-level segments or per-stage overrides.

### 9.1 Pitch program (Forden / Levinger / Wright convention)

`_gravity_turn_thrust_dir` (`trajectory.py`) implements the linear
pitch program first introduced by Forden (2007) and refined by
Levinger / Wright. The elevation angle `θ(t)` above local horizontal is:

```
Phase 1   (0 ≤ t ≤ t_start):              θ(t) = θ_start
Phase 2   (t_start < t < t_stop):         θ(t) = θ_start − (t − t_start)/(t_stop − t_start) · (θ_start − θ_burnout)
Phase 3   (t ≥ t_stop):                   θ(t) = θ_burnout
```

`θ_start` is typically 90° (vertical) for the first stage; for upper stages
it inherits the previous stage's burnout angle. `θ_burnout` is the
user-specified burnout elevation, normally chosen to match the Wheelon
optimal angle (Section 10.2) for maximum range.

The commanded thrust unit vector in ENU is

```
û_thrust = cos θ · sin ψ · ê_E + cos θ · cos ψ · ê_N + sin θ · ê_U
```

where `ψ` is the commanded azimuth from the yaw program (Section 9.5).
The ENU vector is then transformed back to ECEF for the EOM.

### 9.2 True gravity turn (Wright 2020 convention)

`_true_gravity_turn_thrust_dir` (`trajectory.py`) implements a
velocity-aligned thrust direction with an optional tilt angle `η` (degrees
below velocity vector). At each step:

```
v̂           = velocity / |velocity|
n̂_perp      = (r̂ − (r̂ · v̂) v̂) / |·|              ("above velocity" unit vector)
û_thrust    = cos η · v̂  −  sin η · n̂_perp
```

`η > 0` tilts thrust *below* the velocity vector, which actively lowers
the flight-path angle γ — matching Wright's `etad` convention.

A near-vertical singularity (`r̂ ‖ v̂`) is handled by falling back to a
trajectory-plane basis defined by the launch azimuth. During the initial
liftoff window (`t < 4 s` or `|v| < 50 m/s`) thrust is held along
local-up to avoid the `v̂` singularity at zero velocity.

By default `η = 0` throughout the burn, giving a pure (velocity-aligned)
gravity turn. The per-stage `stage_burnout_angle_deg` field is reused as
`η` for the true gravity turn mode — non-zero values produce a controlled
pitch-over below pure velocity tracking (Section 9.5).

### 9.3 Orbital insertion (two-phase)

`_orbital_insertion_thrust_dir` (`trajectory.py`) implements a
two-phase program designed for space-launch vehicles:

```
Phase 1  (all stages before the final, t < t_final_ignition):
            Linear pitch from 90° at t = 0 down to boost_angle_deg
            over the window [t_start, t_stop], then hold boost_angle_deg
            until final-stage ignition.

Phase 2  (final stage, t ≥ t_final_ignition):
            Hold 0° (horizontal) so the final stage adds horizontal
            velocity at the boost-arc apogee until orbital energy
            cutoff fires.
```

Engine cutoff for the final stage is *not* time-based — it is commanded
by an event function that monitors the specific orbital energy

```
ε(t) = ½ |v_ECI|² − μ/r
```

against the target circular-orbit energy `ε_target = −μ/(2 r_target)`.
When `ε(t) = ε_target` the engine cuts off. This makes the trajectory
self-correcting: the burn ends when the orbit is closed, regardless of
small thrust or mass-flow errors. Solid stages cannot be commanded off,
so they burn to natural propellant exhaustion; the orbital-energy
condition only applies to liquid final stages.

The companion planner `plan_orbital_insertion` (`trajectory.py`)
searches automatically for the `boost_angle_deg` that places the perigee
closest to the requested orbit altitude, returning success/perigee/apogee
in a single call.

### 9.4 Per-stage pitch overrides

When "Advanced pitch profile" is selected, each stage exposes three
override fields (`stage_turn_start_s`, `stage_turn_stop_s`,
`stage_burnout_angle_deg`) that take priority over the missile-level
schedule. This is how the built-in missiles replicate published
boost-phase pitch programs — for example, a three-stage ICBM whose
documented profile has different turn-start/stop times in stages 1, 2,
and 3 sets each stage's overrides independently.

Per-stage overrides apply to all three guidance modes:

| Mode | Per-stage meaning |
|---|---|
| `pitch_program` | Three-phase linear pitch with stage-specific start/stop/end angles |
| `true_gravity_turn` | `stage_burnout_angle_deg` is reused as η (degrees below velocity); start/stop bracket the active η window |
| `orbital_insertion` | Override the boost-angle schedule for that stage |

Unset overrides default to the mission-level schedule. The flag for
"this stage uses overrides" is the presence of all three fields; if any
is `None` the global schedule applies.

### 9.5 Yaw program (dogleg maneuvers)

`_yaw_program` (`trajectory.py`) implements a multi-segment azimuth
schedule. Each segment is a tuple `(start_s, stop_s, final_az_deg)`
giving start and end times (mission-elapsed) and the commanded final
azimuth. Between segments the commanded azimuth interpolates linearly
from the previous segment's ending value:

```
For t in segment k with previous azimuth ψ_{k-1} and target ψ_k:
   ψ(t) = ψ_{k-1} + (t − start_k)/(stop_k − start_k) · (ψ_k − ψ_{k-1})
```

This is the model for dogleg maneuvers used by ICBMs and SLVs to adjust
the post-staging ground track without changing the launch azimuth.
Per-stage yaw fields (`stage_yaw_start_s`, `stage_yaw_stop_s`,
`stage_yaw_final_az_deg`) take priority over the mission-level list when
present. The commanded `ψ(t)` feeds the pitch-program's azimuth slot
(Section 9.1) at every EOM step; pitch (elevation) and yaw (azimuth)
combine in the ENU resolution via the standard spherical-coordinate
basis projection, with elevation θ and azimuth ψ as independent
parameters.

### 9.6 Boost angle of attack, the q·α load, and the α envelope (SP-8099)

The commanded thrust axis is not generally aligned with the velocity
vector. The angle between them — the boost angle of attack α — is the
physically limiting quantity for a maneuvering booster: the combined
aerodynamic + steering load scales with the product of dynamic pressure
and angle of attack, **q·α**, and NASA SP-8099 (*Combining Ascent
Loads*, 1972) is the criteria monograph for how those loads combine.
Its §2.1.2.2 (p. 12) gives the standard preliminary-design load
condition — *"a 5° to 10° angle of attack at the maximum dynamic
pressure condition"*, bounded by the *"hard-over engine condition"* —
and its p. 13 case study is the exact maneuver Thrusty's yaw program
commands: a sharp range-safety *"dog-leg"* whose *"large angle of
attack"* and steering-plus-aero load *"were found to be the design
combined-load condition."* (For scale, SP-8099 p. 10 tabulates
steering / pitch-command loads at 0.05–0.15 of the wind bending moment
in nominal flight — small until a sharp maneuver makes them dominant.)

Without a constraint, the guidance model would fly any commanded
attitude instantly and for free: thrust is applied along the commanded
direction, only axial drag is charged, and a 1-second 90° dogleg at
max-q reports no consequence. Two mechanisms close that gap:

**Reporting (always on).** Every run computes, at each output step of
powered flight, `α(t)` = angle between the commanded thrust direction
(the same `_commanded_thrust_dir` the EOM flew) and the air-relative
velocity (ECEF velocity — the atmosphere co-rotates), the dynamic
pressure `q(t) = ½ρv²`, the combined-load trace `q·α(t)` (kPa·°), and
the **applied lateral load factor** `n_lat(t) = q·A_ref·C_Nα·α / (m·g₀)`
(the aerodynamic side load in g — the quantity payload user's guides
tabulate; see below). These are returned as `alpha_deg`, `alpha_cmd_deg`,
`q_pa`, `q_alpha_kpa_deg`, and `lateral_g`. The guidance plot draws the
flown α (solid) and, when the clamp engaged, the commanded α (dashed) so
the gap shows what the limit held back; the dynamic-pressure plot draws
max-q and a peak lateral-g readout. q·α is proportional to the lateral-g
readout, so it is reported only as a **Max q·α** Flight Timeline
milestone (alongside **Max lateral load**) rather than annotated on the
plot. When *no* limit is set, a plan that
demands α > 25° while q > 1 kPa gets a **⚠ α exceeds SP-8099 envelope**
timeline warning: the maneuver is still flown as commanded, but never
silently.

**The α limit — a constant-q·α load envelope (per flight plan).**
`integrate_trajectory` accepts `alpha_limit_deg` (GUI: the "α limit"
field in the Flight Plan dialog's yaw/dogleg panel, **defaulting to
10°** — the top of SP-8099's 5–10° band — and user-editable; blank =
no limit, warn only). The number is read in SP-8099's own convention:
the maximum α *at the maximum-dynamic-pressure condition*. The enforced
quantity is therefore the **load**, not the angle —

```
q(t)·α(t) ≤ q_max-q · alpha_limit_deg      ⇒      α_allow(t) = alpha_limit_deg · q_max-q / q(t)
```

— so the allowance equals the limit at max-q, grows in proportion as q
falls, and is unbounded as `q → 0`. The commanded thrust is clamped to a
cone of half-angle `α_allow(t)` about the velocity vector (spherical
interpolation from `v̂` toward the command, stopped at the cone). This
**replaces the earlier hand-picked 100 Pa pressure gate**: the envelope
now self-deactivates in vacuum as a *consequence of the load physics*
(q·α → 0), with no arbitrary constant. `q_max-q` is the ascent max-q,
tracked as a running maximum during integration (`params._maxq_pa`);
max-q is reached early, before any dogleg, so the reference is settled
by the time a maneuver needs clamping. Under the clamp the vehicle turns
only as fast as the bounded lateral force rotates the velocity vector, so
a commanded instantaneous dogleg stretches over the time it physically
needs; a maneuver whose *load* stays under the ceiling (e.g. a large-α
turn where q is already low) is permitted, while one that would spike
q·α at max-q is held to the envelope. Engagement — the clamp actually
reducing the commanded angle — is reported (`alpha_limit_engaged`) and
flagged as an **α-limit engaged** milestone. `alpha_limit_deg = None`
(the `integrate_trajectory` default; the GUI default is 10°) is
byte-identical to the legacy behavior.

**α-induced drag (opt-in, per flight plan).** By default the α term is
reporting-only — the boost drag stays axial (Section 8), so the q·α
trace exposes the load without feeding back on the trajectory's energy
budget. Setting `alpha_induced_drag=True` (GUI: the "α induced drag"
checkbox in the yaw/dogleg panel) closes that gap: a commanded thrust
axis offset from the velocity by α develops an aerodynamic normal force,
modeled with the same Jorgensen slender-body-potential + Allen-Perkins
viscous cross-flow build-up used for glider L/D (Section 12,
`glider_ld.py`), referenced to the boost frontal area:

```
C_N(α) = C_Nα_pot·sin(2α)/2 + η·C_dn(M·sinα)·(A_p/A_ref)·sin²α
```

with `C_Nα_pot = 2` per rad (slender-body, nose-dominated), `η = 1`, and
`A_p` the side-projected planform of the still-attached stack. Only the
**induced-drag** projection of that normal force, `N·sinα` along −v, is
applied to the trajectory (`_boost_alpha_aero_force`). It bleeds kinetic
energy and so reshapes q — scaling as α² at small α, since `C_N ∝ α` —
which is the energy cost SP-8099's q·α metric implies and that agile-
maneuver studies charge explicitly: Fresconi et al. (2017, ARL-TR-8085)
with a sin²α cross-flow axial term, and Kim et al. (2013) with the
induced-drag polar `C_D = C_D0 + k·C_L²` whose dynamic-pressure collapse
(velocity falling to ~10 m/s) is what makes their 180° extreme-α reversal
flyable at all.

The **lift** projection (`N·cosα`, perpendicular to v) is deliberately
*not* applied as a trajectory force. An ascending booster is designed to
fly at low α precisely to avoid these loads, and crediting its body
normal force as free loft would let the simplified pitch program's few-
degree α mimic a lifting body (an early build did exactly this and
*extended* range by ~30 km on a straight ascent — the wrong sign for a
maneuver penalty). This matches `drag_force_vector`'s established ascent
convention, where a finned stage's normal force is a static-margin
(stability) effect, not a trajectory force. So the α term is a pure
cost — it can only slow the vehicle, and with it enabled max-q genuinely
moves (a plain No-dong ascent: 629 → 617 kPa; a hard dogleg pays far
more). The term vanishes at α = 0, so `alpha_induced_drag=False` (the
default everywhere) is byte-identical to the legacy dynamics.

Scope note: this is a screening-grade model. `C_Nα_pot = 2` is the
slender-body potential value, the planform is a rectangular
length × diameter approximation, and body–fin and configurational
asymmetries (the phantom-yaw side forces and canard–fin vortex coupling
that Fresconi's 6-DOF model resolves) are out of scope for this 3-DOF
point-mass tool — as is the fin-effectiveness dead zone (Kim's
uncontrollable 35° < α < 130° domain), which is a control-authority
limit an engine-gimballed booster does not share (SP-8099's "hard-over
engine" remains the correct attitude bound). The α limit above keeps the
maneuver inside the envelope where the screening cross-flow model is
defensible.

#### Lateral load factor, and the shelved vehicle-derived capacity

The **applied** lateral load factor `n_lat = q·A_ref·C_Nα·α / (m·g₀)`
(returned as `lateral_g`, shown as a "peak lateral N g" plot readout and
a "Max lateral load" milestone) is the aerodynamic side load in g — the
same quantity every payload user's guide tabulates for the atmospheric
phase. Cross-checking against published guides puts the steady-state
first-stage lateral load in a tight band: **START-1 0.7 g, Cyclone-4
0.3–0.6 g, Minotaur I/IV < 0.5 g** (with a slender liquid like Scud
estimated ~0.2 g). This band, plus SP-8099's 5–10° and the CNES result
that a simplified q·α estimate matches full 6-DOF within ~5%
(Delorme et al., EUCASS 2013), is what justifies the 10° / order-of-
0.5 g default. It is an *applied-load* readout only — no structural
capacity is claimed.

A **vehicle-derived structural capacity** was prototyped and
deliberately **shelved** (kept here as a documented option, not wired
in). The idea: anchor a thin-cylinder bending capacity to the axial
thrust the case demonstrably carries, `M_cap ≈ F·R/2`, and convert to a
lateral-g ceiling — no material or skin-gauge data needed. It reproduces
the right order of magnitude (START-1: estimate 0.56 g vs published
0.7 g) but was judged **not accurate or general enough to enforce a
limit**, for reasons worth recording:

- It estimates *capacity*, whereas the guides publish *experienced*
  load; the two coincide only for loads-optimised vehicles. A repurposed
  ICBM motor (Minotaur-IV = Peacekeeper SR118) is over-built for its SLV
  role, so the estimate (1.05 g) far exceeds its < 0.5 g nominal —
  consistent (`capacity ≥ nominal·FoS`) but unvalidatable, since capacity
  ground truth is proprietary. Net accuracy is **≈ ±2×, anchored at a
  single point**.
- `M_cr = P_cr·R/2` assumes **monocoque** construction; it is meaningless
  for a pressure-stabilised (balloon) tank, and the `P_cr ≈ thrust`
  anchor ignores that ground-handling or the combined max-q case may
  size the structure instead.
- The bending arm (`≈ 0.25·L`) swings the answer ~3× and was effectively
  fitted to the one anchor; the real methods (SMC-S-004; CNES) carry
  distributed mass/aero to locate critical stations.
- It limits the **steering** term, which SP-8099 (p. 10) and CNES both
  put at 0.05–0.15 of the *wind* bending moment — and Thrusty models no
  winds, so the load that actually sizes the airframe is out of reach.

The honest conclusion: the enforced envelope is the SP-8099 α limit
(constant-q·α, 10° default, user-set), the reporting is the q·α and
lateral-g traces, and `F·R/2` remains a research-grade capacity gauge
recorded here for anyone who later adds a structural model. See TODO.md.

---

## 10. Range optimisation and targeting

### 10.1 Tsiolkovsky stack ΔV (pre-estimate)

The total vacuum ΔV available from the stage chain is

```
ΔV_total = Σ_stages  I_sp · g₀ · ln( m_initial / m_burnout )
```

(`_tsiolkovsky_dv`, `trajectory.py`). This is used as a fast estimate
of achievable burnout speed before the range-maximisation search — it
costs no integration calls and provides a tight bound for narrowing
the search window. The empirical relation

```
v_burnout ≈ 0.82 · ΔV_total − 300 m/s
```

calibrates the ideal ΔV against typical gravity-drag losses for
ballistic boost profiles. For SLVs the SLV-specific Schilling penalty
(Section 11) is used instead.

### 10.2 Wheelon optimal burnout angle

For a given burnout speed `v_bo` at altitude `h_bo`, the burnout
elevation angle that maximises ballistic range on a spherical Earth is
(Wheelon):

```
Q      = v_bo² / (g_bo · r_bo)        r_bo = R_E + h_bo,  g_bo = GM/r_bo²
γ_opt  = ½ · arccos( Q / (2 − Q) )
```

(`_wheelon_gamma_opt`, `trajectory.py`). The dimensionless ratio
`Q` is bounded above by 1 (orbital velocity); for sub-orbital
trajectories Q < 1 and γ_opt is well-defined and lies between 0° (Q = 1,
flat orbit) and 45° (Q → 0, throw the rock from a tower).

Used as the centre of a coarse-grid search window
`γ ∈ [γ_opt − 10°, γ_opt + 10°]`. This roughly two-thirds reduction in
search volume relative to a 5°–80° unbounded scan brings the
range-maximisation cost down to a level where a parallel grid search
finishes in seconds for typical missiles.

### 10.3 Range maximisation algorithm

`maximize_range` (`trajectory.py`) is a two-phase search over
(burnout angle, turn-stop time):

1. **Coarse coordinate descent.** Burnout angle and turn-stop are only
   mildly coupled, so rather than the full Cartesian product of the two
   candidate lists (angle window × turn-stop window ≈ 200 trajectories,
   which with the GIL-bound EOM ran essentially serially on the thread
   pool), the search descends one axis at a time from a good starting
   line. The angle window is bounded by Wheelon (Section 10.2); the
   turn-stop window covers the powered-flight duration, with a 3600 s
   outer cap to bail out on degenerate cases that never impact. Seeded at
   the Wheelon-optimal angle `γ_opt`, it (a) sweeps the turn-stop along
   `γ_opt`, (b) sweeps the angle at the winning turn-stop, then (c) — only
   if the angle moved — re-sweeps the turn-stop at the winning angle. Each
   sweep runs on a thread pool (up to 8 workers, capped to avoid
   hyperthreading thrash). This evaluates ≈ ¼ of the trajectories of the
   full grid and, validated against it (`test_max_range_search.py`),
   lands on the same optimum to within the grid's own 2° / 2 s
   granularity — including the coupled case of a lofted non-separating
   body glider, whose optimum sits at a long turn-stop that a
   short-turn-stop seed would miss. Seeding the descent at the physics-
   based angle (not an arbitrary grid corner) is what makes one descent
   pass sufficient.
2. **Bounded polish.** The best coarse candidate is refined by a single
   `scipy.optimize.minimize_scalar(method='bounded')` pass (bounded Brent
   over an interval) on the burnout angle, with the turn-stop fixed at the
   coarse optimum.

The result dictionary returns the maximum range plus the optimal
`(burnout_angle, turn_stop)` and the full trajectory at the optimum.
A `cancel_event` parameter allows GUI cancellation between coarse-grid
evaluations.

Because both optimisation variables are the *global* (simple-profile)
pitch knobs — and per-stage overrides take precedence over them in the
guidance law (Section 9) — the search is only meaningful on a simple
pitch profile; on an advanced per-stage plan the swept globals are masked
and the reported optimum is noise. The optimum is also not a property of
the booster: it depends on launch latitude, azimuth (Earth rotation), and
the reentry object's drag. The GUI therefore treats Max Range as a
*generator*, not an editor: it writes the optimised `(burnout_angle,
turn_stop)` to a reserved `max-range` flight-plan variant (stamped with
the launch context it is valid for) and switches to it, leaving the
loaded plan untouched. Plan Orbit follows the same contract, writing its
solved two-phase boost program to a reserved `orbital` variant. Both sit
within the law-as-identity model: a flight plan's guidance law is chosen
at creation and never changed in place (only the Simple/Advanced
parameterisation of a pitch plan toggles), so each generated variant
carries the law it was optimised under. Conceptually Max Range is the
numeric rung between the closed-form Wheelon estimate (Section 10.2)
that seeds its search window and a future full per-stage-profile
optimisation that would seed from *its* result in turn.

### 10.4 Aim at target

`aim_booster` (`trajectory.py`) finds the engine cutoff time that
produces a specified range. With burnout angle held fixed, range is a
monotonic function of cutoff time (more burn ↔ more range), so Brent's
method on the scalar `cutoff_time` is well-behaved:

```
cutoff_time = brentq( range(cutoff) − target_range, lo=5 s, hi=t_burn_total )
```

`xtol = 1 s`, `maxiter = 50`. If the target range is outside the feasible
envelope (either because the missile lacks the energy or because even
zero-burn ballistic flight overshoots), the function returns `t_burn_total`
and the caller observes the resulting overshoot.

For a target *point* (lat/lon) rather than a target range, the caller
first computes the great-circle distance using Vincenty (Section 2.3),
then aims for that range.

### 10.5 Find range

`find_range` (`trajectory.py`) is a trivial wrapper around
`integrate_trajectory` that returns only the range; used by GUI calls
that don't need the full trajectory dictionary back.

---

## 11. SLV performance estimation

For space-launch vehicles the question is *can this rocket put a given
payload into a given orbit*, not *how far does it fly ballistically*.
This is answered by the Schilling method, an algebraic ΔV budget that does
not require trajectory integration (`slv_performance.py`).

### 11.1 The Schilling method

The available ΔV from a stack of stages is the Tsiolkovsky sum
(Section 10.1). The required ΔV to reach a target orbit is

```
ΔV_req  = V_inj  +  ΔV_pen  −  V_rot
V_inj   = √( μ · (2/r_p − 1/a) )                vis-viva at perigee
a       = (r_p + r_a) / 2                       semi-major axis
V_rot   = R_E · Ω · cos(lat) · sin(azimuth)     Earth-rotation assist
```

`V_inj` is the inertial-frame injection speed at perigee from the
vis-viva equation; for a circular orbit this collapses to
`√(μ/r)`, the circular orbital speed. For an elliptical transfer the
formula gives the perigee speed of the target orbit. `V_rot` is the
eastward ground-frame velocity at the launch site, which is "free" — a
launch toward the east adds Earth's rotation to the inertial speed at no
propellant cost. With azimuth measured clockwise from north, `sin(azimuth)`
picks out the eastward component (maximal due-east, zero for a polar
launch).

`ΔV_pen` is the empirical Schilling penalty that bundles gravity
losses, drag losses, and steering losses into a single function of
ascent time and perigee altitude. The formulae are
([Schilling 2009](#16-references)):

```
T_3s    = 3 · [1 − exp(−0.333 · ΔV_avail / (g₀ · I_sp_avg))] · g₀ · I_sp_avg / A₀
T_mix   = 0.405 · T_actual  +  0.595 · T_3s
ΔV_pen  = K_3 + K_4 · T_mix
K_3     = 429.9 + 1.602 · H_p + 1.224×10⁻³ · H_p²       (H_p in km)
K_4     = 2.328 − 9.687×10⁻⁴ · H_p                       (H_p in km)
```

`T_3s` is a notional 3-stage ascent time, `T_actual` is the real burn
time of the stack, and `T_mix` is the empirical blend Schilling found
to fit the calibration data best. `H_p` is the perigee altitude in km.

The vehicle has *positive ΔV margin* (i.e. can reach the target
orbit with the stated payload) iff `ΔV_avail > ΔV_req`.

### 11.2 Maximum payload — binary search

Payload enters the budget on only one side: it lowers every stage's
burnout mass and therefore `ΔV_avail` (through the Tsiolkovsky sum). The
ascent-time term `T_actual` in the penalty is held fixed at the stack's
nominal burn time, so `ΔV_req` does **not** move with payload — no outer
fixed-point iteration is needed.

The implementation is therefore a single binary search on payload between
0 and a fixed upper bound of 200 000 kg, bisecting on the sign of the
margin `ΔV_avail(payload) − ΔV_req` for 50 iterations, which converges to
sub-kilogram precision.

### 11.3 Accuracy and use cases

Schilling reports ~260 m/s RMS error in total mission ΔV calibrated
against historical launches, equivalent to ~10 % error in payload
capacity. This is sufficient for the questions the method is designed
to answer:

- *Is the claimed orbit feasible with the claimed payload?*
- *What is the maximum payload for this orbit and azimuth?*
- *How sensitive is payload to perigee altitude / azimuth / launch latitude?*

The algebraic approach is much faster than trajectory integration
(milliseconds vs. seconds) and guidance-law-agnostic — you don't need
to know the actual pitch program. For questions that need trajectory
shape (peak altitude, burnout velocity vector, range, debris arcs of
spent stages) the 3-DOF integrator (Sections 5–10) is the right tool.

The natural division of labour for a complete SLV analysis:

| Question | Tool |
|---|---|
| Can the full SLV reach the claimed orbit with the claimed payload? | Schilling (Section 11) |
| What does the stripped-down booster do as a ballistic missile? | 3-DOF simulation (Sections 5–10) |

---

## 12. Hypersonic glide vehicles

A boost-glide weapon is a re-entry vehicle (RV) that, after separating from
its booster on a depressed or lofted ballistic trajectory, re-enters the
upper atmosphere, executes a pull-up maneuver, and then *glides* at
hypersonic speed for thousands of kilometres before terminal dive on the
target. Compared to a ballistic RV, the glider trades range for lower
flight altitude, in-flight cross-range manoeuvring, and a flight profile
that bypasses exo-atmospheric defences.

The HGV machinery in Thrusty has six interlocking pieces, each documented
in its own subsection below: a state-machine latch that decides when the
vehicle is in "glide mode"; two aerodynamic models (constant L/D and a
drag polar); the guidance modes, split by integration method into
**numerical (EOM)** and **closed-form analytic** families; a bank-to-turn
cross-range model; an inverted terminal dive; and a JSON-based RV library
for shipping or extending vehicle definitions.

The trajectory machinery and physical conventions follow
[Tracy & Wright 2020](#16-references) and
[Acton 2015](#16-references). The modes divide by how they are integrated.
The **numerical (EOM)** family integrates the equations of motion with a
per-step lift command and spans a phugoid-suppression spectrum: `ballistic`
(no lift), `skip_glide` (undamped phugoid, ζ = 0), `damped_glide` (a guided
pull-up plus a few decaying skips, ζ ≈ 0.7, [Lu 2013](#16-references)), and
`dynamic_equilibrium_glide` (equilibrium-trim capture, ζ a tracking gain).
The **closed-form analytic** family reaches the same equilibrium glide via an
imposed pull-up arc + range formula: `equilibrium_glide_acton` (Acton 2015
three-phase non-oscillatory capture) and `equilibrium_glide` (Tracy & Wright
2020, single-arc). The analytic family exists mainly as a fast closed-form
*comparison* against the numerical sim; it always captures and cannot bank,
dive-at-target, or take the Mach-varying L/D table.
(`skip_to_equilibrium`, a Thrusty-original discrete N-skip handoff, is
**retired** — aliased to `damped_glide`, which covers it continuously.)
See [`DAMPED_GLIDE.md`](DAMPED_GLIDE.md) and
[`DAMPED_GLIDE_MEMO.md`](DAMPED_GLIDE_MEMO.md) for the full damped-glide
derivation.

#### 12.0.1 Commanded pull-up (`glider_pullup_start_alt_km`)

A **plan-phase modifier**, not a guidance mode: it composes with any of the
three numerical glide laws (`damped_glide`, `dynamic_equilibrium_glide`,
`skip_glide`) the way banks and the terminal dive do.  A single user input —
the pull-up start altitude (km) — splits capture into three phases via a
one-way latch (`params._pullup_phase`, `trajectory.py`):

1. **Fall** (above the trigger): **zero commanded lift**, β-based drag only —
   the low-AoA ballistic descent a real MaRV flies to preserve energy.
2. **Pull** (at the trigger, descending): a hard pull at **full authority**,
   capped by BOTH the commanded pull-up g (`glider_pullup_g_max`, itself
   clamped to the object's structural `pullup_g_limit` when that is set;
   0 = unlimited) AND what
   dynamic pressure + the aero model can supply.  Triggering too high, where
   there is no q to pull with, therefore **undershoots honestly** — no lift is
   conjured — rather than faking a catch.
3. **Handoff** (once the sink rate is arrested to the glide law's own
   equilibrium target `γ* = −2·H_ρ·g/(V²·cosσ·(L/D))`, Lu Eq. 31): the
   selected law takes over, one-way.

**Why it exists.**  A user campaign of nine runs against the digitized
SWERVE III corridor (`benchmarks/swerve/`) showed the constant-ζ architecture
tracing a smooth *frontier*: every knob (ζ, lift, booster energy, loft) trades
capture-trough depth against arrival speed, and the flight point — a 25.8 km
shelf held from Mach 12 — sits outside the reachable set.  The reason is
structural: one damping gain was being asked to be both "off during the fall"
and "10 g at the shelf".  The real vehicle did not do that — Iliff & Shafer
(AIAA 93-0311, Fig. 20) describe SWERVE III's capture as a
**discrete commanded pull-out at Mach 12** (a −10° AoA pull at t = 20 s), which
is exactly this modifier.  With the pull owning capture, ζ returns to the job
its linearization assumes — damping small residuals near equilibrium — instead
of arresting a km/s-class fall.  `glider_pullup_start_alt_km = 0` (default) is
byte-identical to the plain glide laws, so every shipped plan is unchanged.
The analytic family ignores the field (it flies its own closed-form pull-up
arc).  `test_pullup.py` pins the phase behaviour, the ζ-decoupling, and the
zero-trigger identity.

#### 12.0.2 Wing-decoupled drag polar (`wing_area_m2`, `wing_aspect_ratio`)

The polar `C_D = C_D0 + k·C_L²` back-solves both coefficients from (β, L/D):
`C_D0 = m/(β·A_ref)`, `k = 1/(4·C_D0·(L/D)²)`.  That fully determines the
curve — which means it pins the vehicle to the slender-**body** lift behaviour,
with a hardcoded pull ceiling `C_L ≤ 2·25° = 0.873`.  The SWERVE campaign
exposed the consequence: a hard commanded pull rails at that ceiling and runs
at **L/D ≈ 0.94, half the nominal** — the "pull tax" that catches the vehicle
on the shelf but bleeds Mach doing it.

The fix anchors the missing degree of freedom to **geometry the user can
measure**, not a performance number they'd guess.  Two hardware fields on the
reentry object (both default 0 = slender body, byte-identical):

- **`wing_area_m2`** (S_w) — total wing planform area.
- **`wing_aspect_ratio`** (optional) — b²/S_w.

A winged vehicle carries lift more efficiently *off* the cruise point, so it
flattens the L/D curve there.  The decoupling models exactly that — it
broadens the drag bucket on the **pull side only** (`_polar_cd`, C_L > C_L\*),
leaving the cruise bucket (and therefore glider_LD) untouched, so nothing is
double-credited:

```
λ       = wing_area / A_ref                        (planform ratio)
AR      = wing_aspect_ratio, or WING_DEFAULT_AR=2 if unset   (fail safe)
e_pull  = 1 + WING_PULL_GAIN·λ·AR/(AR + WING_PULL_AR0)   (WING_PULL_GAIN=1, AR0=4)

C_D(C_L ≤ C_L*)  = C_D0 + k·C_L²                   (cruise — unchanged)
C_D(C_L > C_L*)  = C_D* + (k/e_pull)·(C_L² − C_L*²)   (pull — softened)
```

Two deliberate design choices, both discovered empirically and pinned by
`test_wing_polar.py`:

- **The C_L ceiling is NOT raised by wings.**  `|α| ≲ 25°` is a max-AoA limit
  for a body or a winged vehicle alike.  Raising it merely lets the pull rail
  at ruinous induced drag — *verified to deepen the trough and crash the
  vehicle*.  Only the bucket width (`e_pull`) changes.
- **Area-only fails safe.**  Wing area with no declared AR assumes a stubby,
  low-efficiency wing (`WING_DEFAULT_AR = 2`): a modest, conservative benefit
  from area alone, never the optimistic high-AR value.  Missing span costs
  accuracy, not correctness.

`WING_PULL_GAIN`, `WING_PULL_AR0` and `WING_DEFAULT_AR` are screening
inferences with ~±30% bands — never fit to a flight.

**Advisory drag side (Level 2).**  The same wing area also makes the "Estimate
Object β" dialog honest: a winged vehicle is draggier than the bare cone
(`cd_cone_hypersonic` adds `Cf·2·S_w/A_base` for the two wetted faces), so the
*suggested* β drops.  This is advisory only — the run-time drag equation stays
`q·m/β` with the single committed β, so there is no double-count between the
estimator's suggestion and the run.  Wing wave drag (thickness/sweep) is not
carried and is labeled conservative-low.

#### 12.0.3 The β convention: zero-lift, with the analytic β_L derived

`beta_kg_m2` has one meaning across the whole model: the **zero-lift**
ballistic coefficient, the polar's convention `C_D0 = m/(β·A_ref)`.  The
analytic modes (Tracy `equilibrium_glide`, Acton `equilibrium_glide_acton`)
need a *different* quantity — Acton's `β_L`, the ballistic coefficient **in
glide trim**, `m/(C_D,glide·A)`.  At the max-L/D trim `C_D = 2·C_D0`, so

```
β_L = β_zerolift / 2          (labeled INFERENCE — Acton gives no β_L formula,
                               only a fitted value in his Table 3)
```

The analytic path (`trajectory.py`) derives β_L this way from the stored
zero-lift β, so the same number serves both families without the ~2× semantic
mismatch that would otherwise sit between them.  Acton's entry-phase `β_S`
(`glider_beta_entry_kg_m2`, a vehicle property stored on the reentry object)
is a separate, directly-stored fit (his high-AoA flat-plate value), not
subject to the halving.

**Why this matters — HTV-2 (re-based 2026-07-25).**  HTV-2 shipped with
`β = 13,000`, which is Acton 2015 Table 3's fitted *glide* β_L, not a zero-lift
value.  Read by the polar as zero-lift it gave an implausible `C_D0 = 0.27` and
an operating `C_L* = 1.4` (past stall).  Re-based to the zero-lift `β = 26,000`,
the polar reads `C_D0 = 0.14` / `C_L* = 0.71`, and the analytic path derives
`β_L = 26,000/2 = 13,000` — reproducing Acton's Table 3 exactly, so HTV-2 stays
**validatable against Acton** while its polar operating point becomes physical.
The trajectory moved < 1 % (equilibrium-glide range is L/D-dominated): this is
a correctness/consistency fix, not a behaviour change.

**Scope.**  Only HTV-2's stored β changed.  The derivation is shared code but
behaviour-neutral for the rest of the shipped fleet: the only plans on an
analytic mode (Generic_RV, Mk21) are ballistic (`glider_LD = 0`, so the
analytic pull-up never runs and β_L is unused), and every shipped glider
defaults to a numerical mode that reads β as zero-lift directly.
`test_acton_beta.py` pins the Acton reproduction, the plausible polar point,
the untouched fleet, and that the analytic run actually uses the halved β.

### 12.1 Glide activation — the apogee transition

Glide-mode aero forces are *not* active throughout the flight; the lifting
phase begins at **apogee** — the physical start of the descending glide.
The integrator makes this concrete by splitting every glider run at apogee:
Phase 1 (launch → apogee) is flown with the glider **off**, so the ascent
arc is purely ballistic and mode-independent; Phase 2 (apogee → ground)
is flown with the glider **on**. The pre-apogee flag `_glider_phase1`
records which phase is active, and the EOM gate is simply

```
glide_active = ( RV is the terminal vehicle       # effective_ro()
               ∧ glider_enabled ∧ glider_LD > 0
               ∧ past apogee (not _glider_phase1)   # Phase 2
               ∧ q > 0 )                            # dynamic pressure present
```

`effective_ro()` (`booster_models.py`) separately selects *which* RV is the
terminal vehicle (glider, separating warhead, or maneuvering body).

Whether an armed glider then **captures** (settles onto a sustained glide),
**skips** (re-climbs), or **plunges** is decided by the equilibrium-glide
dynamics of the selected law (§12.3, `glide_regime.py`), not by any altitude
threshold: the vehicle catches when it descends into air dense enough that
the trimmed lift `q·A·C_L` can arrest the sink toward the equilibrium
flight-path angle `γ* = −2·H_ρ·g/(V²·cosσ·(L/D))`. This is a dynamic-pressure
condition, so it holds wherever the glide physically occurs — including a
depressed quasi-ballistic trajectory whose apogee is only ~40–60 km.

**The 100 km pierce is Acton-specific.** `ACTON_PIERCE_ALT_M = 100_000.0`
(the Kármán line, Acton 2015 p. 204 — the start of his Phase 3 direct
re-entry) is used **only** by the analytic Acton skip-glide / equilibrium
family (`equilibrium_glide_acton` and the analytic handoff), whose closed
form is genuinely an exo-atmospheric re-entry model and is undefined below
its entry interface. That family keeps the 100 km handoff on its own
analytic path (the `_glider_pierce_atmosphere` event, §14). The numerical
EOM laws — phugoid / skip-glide, damped-phugoid, and dynamic-equilibrium
glide — do **not** use it; they arm on the apogee transition above.

*History (2026-08-21).* The numerical laws previously shared the Acton
100 km gate through a `_gl_above_pierce` latch that required the vehicle to
climb above 100 km and descend back through it before any lift was allowed.
For an exo-atmospheric entry this is identical to the apogee rule — the
vehicle is post-apogee *and* below 100 km at the same instant — but it
silently disabled lift for any vehicle whose apogee never reached 100 km. A
quasi-ballistic quasi-ballistic missile (apogee ~50 km, a commanded pull-up at
~40 km) therefore could not glide *at all*: turning the glider on changed
its range by < 1 km. Gating the numerical laws on the apogee transition
instead fixes this while leaving every exo-atmospheric benchmark
byte-identical (the Minotaur-IV + HTV-2 and Tracy/Wright/Acton cases are
unchanged).

### 12.2 Aerodynamic models

Two models are available for the glide phase, set on each RV by
`glider_aero_model ∈ {'constant_LD', 'polar'}`:

#### 12.2.1 Constant L/D (default)

Lift and drag are linked by a fixed ratio:

```
L = D · (L/D)
```

The drag itself is computed from the standard ballistic-coefficient form
`D = q·m / β`, with `β = m / (C_D · A)` stored as `beta_kg_m2` on the RV.
This is the model Tracy & Wright 2020 use throughout their analysis with
`L/D = 2.6` and `β = 13 000 kg/m²` for an HTV-2-class glider.

Default for new RV definitions and the convention used by all the shipped
RV-library entries unless overridden.

#### 12.2.2 Drag polar

An optional higher-fidelity model uses an explicit drag polar

```
C_D(C_L) = C_D0 + k · C_L²
```

with zero-lift drag coefficient `C_D0`, induced-drag factor `k`, and
reference area `A_ref` taken from the RV's `glider_CD0`, `glider_k_polar`,
and a derived reference area (`_aero_polar`, `trajectory.py`). The
drag polar lets the EOM see induced-drag rise as the guidance commands
larger C_L — important for steep pull-ups or aggressive cross-range
turns, where the constant-L/D approximation under-estimates drag.

In polar mode the guidance trims to a particular `C_L` rather than a
particular L/D:

- *Equilibrium-glide modes*: solve for the `C_L` that satisfies
  `L · cos σ = m·(g − v²/r)` (Tracy Eq. 7 with a bank-angle factor), then
  compute `C_D` and the corresponding drag from the polar.
- *Phugoid modes*: fly at the max-L/D angle of attack, where
  `C_L* = √(C_D0 / k)` and `C_D* = 2·C_D0`. Lift then scales linearly with
  q.

A `C_L` cap of `2 · (25°·π/180) ≈ 0.873` is applied in both modes
(`_C_L_lim` at `trajectory.py`), representing the slender-body
small-angle relation `C_L ≈ 2α` evaluated at α_max = 25°. At 25° the
linearization is starting to lose validity — the exact Newtonian value
`sin 2α` gives 0.766 — so this is best read as a conservative upper bound
on the trim solution rather than a precise aerodynamic limit.

### 12.3 Guidance modes

The `glider_guidance` field on each RV selects the reentry law, exposed by the
GUI dropdown. The laws split by **how the trajectory is integrated**, and that
family is the reentry plan's **identity**: chosen when the plan is created (New
Reentry Plan asks family first, then the starting law), fixed for the plan's
life, and the sidebar dropdown lists only the active plan's family — the law is
switchable *within* the family, never across it (mirroring the flight-plan
law-as-identity rule; see `REENTRY_FAMILY_DESIGN.md`). Cross-family comparison
(the analytic laws' main purpose) is done by keeping one plan per family and
flipping the Reentry Plan dropdown. The family is derived from the law — no
stored field:

**Numerical (EOM)** — `_eom` is integrated step by step with the lift/drag
command below; supports banking, dive-at-target, and the Mach-varying L/D table
(§8.10), and is honest about capturability (a lofted entry plunges):

| GUI label | `glider_guidance` value | Origin | Lift command |
|---|---|---|---|
| Ballistic | `ballistic` (glider off) | — | none (drag + gravity only) |
| Phugoid / skip-glide | `skip_glide` | Sänger / classical skip-glide | max-L/D α*, ζ = 0 (undamped) |
| Damped-phugoid glide | `damped_glide` | Lu 2013 (Thrusty default) | α* + ζ phugoid damping (ζ ≈ 0.7) |
| Dynamic equilibrium glide | `dynamic_equilibrium_glide` | Tracy Eq. 7 trim + Lu feedback | equilibrium trim + ζ tracking gain (smooth capture) |

**Closed-form analytic** — Tracy/Acton pull-up arc + equilibrium-glide range
formula; constant L/D, always captures (the arc is imposed). Cannot bank or
dive-at-target — those are numerical-family capabilities, and the plan editor
does not offer them on an analytic plan (the old *silent* fallback that swapped
in the numerical EOM when banking appeared on an analytic run is deleted; any
such fields in legacy data are ignored, and a one-shot migration rewrites those
plans to the numerical family). Cannot take the Mach-varying L/D table (the
closed form needs a constant L/D):

| GUI label | `glider_guidance` value | Origin | Phugoid |
|---|---|---|---|
| Non-oscillatory glide (Acton) | `equilibrium_glide_acton` | Acton 2015 | none (analytic) |
| Equilibrium glide (Tracy) | `equilibrium_glide` | Tracy & Wright 2020 | none (analytic) |

The glide modes form a spectrum of *how aggressively the guidance suppresses
phugoid amplitude*, ordered by ζ: from "let it ride at max-L/D α*"
(`skip_glide`, undamped, ζ = 0), through the tunable middle (`damped_glide`, a
guided pull-up plus a few decaying skips, ζ ≈ 0.7), to full suppression —
either the numerical `dynamic_equilibrium_glide` (equilibrium-trim capture, ζ a
tracking gain) or the analytic Acton/Tracy closed forms. Atmospheric drag damps
all of these — bounded oscillations, not unbounded ones.

> **Retired:** `skip_to_equilibrium` (Lewis, "let it ride for N skips, then
> suppress") is aliased to `damped_glide` on load — the continuous damped
> phugoid covers the same behaviour without the discrete N-skip handoff. Old
> files/plans naming it fly `damped_glide`; the EOM path is retained but
> unreachable.

#### 12.3.1 Equilibrium glide (Tracy)

The simplest mode. At the pierce point (100 km on descent) the vehicle
is treated as already in equilibrium glide; no pull-up arc is modelled.
The EOM is integrated with constant L/D (or the polar trim) and a single
β throughout the glide phase. The integrator's natural dynamics keep the
vehicle near equilibrium because Tracy's Eq. (7) is satisfied at the
pierce point by construction (`trajectory.py–112`):

```
L · cos σ = m · (g − v² / r_e)              [Tracy 2020 Eq. (7)]
```

The equivalent statement: lift balances *gravity minus centripetal*. In
the EOM this appears as the trim condition (`trajectory.py`):

```python
_g_perp = g_mag - speed * speed / r_mag
lift_mag = min( rv_mass * _g_perp / cos(bank),
                drag_mag * glider_LD,
                _erv.glider_pullup_g_max * g_mag * rv_mass )
```

Three caps act in sequence:

1. **The Tracy analytic value** `m · g_⊥ / cos σ` — exactly Eq. (7) with
   the bank-angle factor.
2. **Aerodynamic supply cap** `D · L/D` — what the wings can actually
   deliver given the local dynamic pressure. Without this cap the
   analytic lift term would still be applied when q is negligible (high
   altitude, thin atmosphere), locking the vehicle at the handoff
   altitude and producing unrealistically long range (`trajectory.py`
   comment). With it, when `v < v_eq` and the analytic g_⊥ exceeds what
   the aero can supply, the vehicle descends naturally to denser air.
3. **Structural cap** `n_max · m · g` — the user-set maximum pull-up load
   factor (`glider_pullup_g_max`, default 10 g; settable per RV).

The full Tracy & Wright 3D EOM (their Eqs. 1–6) is recovered by
combining this lift trim with the drag and the standard ECEF gravity
field of Section 5. Maneuvering is by bank angle σ (Section 12.4); the
inverted dive is σ = π (Section 12.5).

The result is a *mild damped phugoid* oscillation about the equilibrium
altitude, matching the small oscillations visible in Figure 4 of Tracy
& Wright 2020 (their note: *"Minor oscillations about the equilibrium
flight altitude, called phugoid motion, result from the dynamics of this
process. These could be damped by active control of the vehicle."*). The
equilibrium trim is the closest the 3-DOF formulation can get to "active
control" without modelling explicit roll-rate dynamics.

#### 12.3.2 Equilibrium glide (Acton)

Same equilibrium-glide EOM as Tracy mode, but with an explicit *pull-up
arc* bridging the descent from the 100 km pierce point down to the
equilibrium-glide start altitude. Implements Acton 2015's three-phase
structure (his §"Pull-up Phase"):

| Phase | Span | Aero |
|---|---|---|
| 3. Direct re-entry | h₂ = 100 km → h₃ | Large angle-of-attack, drag-only, β = β_S |
| 4. Pull-up arc | h₃ → h₄ = h_eq | Smooth analytic arc, gradual rotation |
| 5. Equilibrium glide | h_eq → terminal | Constant L/D and β = β_L (Tracy mode) |

Acton's central simplification is that the pull-up is *deliberately
smooth and non-oscillatory*: the vehicle gradually rotates from high-α
direct-re-entry to low-α equilibrium glide such that ρ/β stays constant
through the pull-up (Acton Eq. 8):

```
ρ(h₃) / β_S  =  ρ(h_eq) / β_L                       [Acton 2015 Eq. (8)]
```

This is the rationale for the on-RV parameter `glider_beta_entry_kg_m2`
(β_S) on top of the glide-phase `beta_kg_m2` (β_L). The code uses
Acton's isothermal-atmosphere fit (his p. 197) over the relevant
altitude band:

```
ACTON_SCALE_HEIGHT_M  = 6970.0                      # trajectory.py
ACTON_SEA_LEVEL_RHO   = 1.46                        # trajectory.py
```

so that h_eq follows from the L/D, β_L, and pierce velocity by
inverting Acton's equilibrium-altitude formula
(`h_eq = H · ln(ρ_0 · r_e / (2·β_L · L/D) · v² / v_e²)`, his Table 1
equilibrium-glide column).

The Phase 3 → Phase 4 transition altitude h₃ is then fixed by Eq. (8):
`h₃ = H · ln(ρ_0 · β_S / β_L · exp(h_eq / H))`. The Phase 4 arc itself is
the analytic circular arc fitted between `(h₃, γ = −θ₂)` at the start
and `(h_eq, γ = 0)` at the end (Acton's small-angle Eqs. 18 / 21):

```
R = (h₃ − h_eq) / (1 − cos θ₂)
h(θ) = h₃ − R · (cos θ − cos θ₂)
```

implemented by `_acton_pullup_arc` (`trajectory.py`). The arc is
applied as a one-shot state reset at the Phase 3 → Phase 4 boundary
(detected by the descending crossing of h₃ via the event function
`_make_phase3_end_event`, `trajectory.py`), after which equilibrium
glide proceeds exactly as in Tracy mode.

Implementation detail: Acton mode falls back to Tracy mode if
`glider_beta_entry_kg_m2 ≤ 0`, since without a positive β_S the Phase 3
direct-re-entry segment is ill-defined. This guarantees the user always
gets an analytical pull-up rather than a phugoid in cases where the
small-β data is missing (`trajectory.py`).

#### 12.3.3 Phugoid / skip-glide

In this mode the guidance does *not* trim to suppress oscillation.
Instead the vehicle flies at the max-L/D angle of attack throughout, so
lift is proportional to dynamic pressure and the natural phugoid
oscillation about the equilibrium altitude is preserved at full
amplitude (`trajectory.py`):

```python
# skip_glide / phugoid: fly at max-L/D AoA (α*)
# so lift ∝ q and the natural phugoid oscillation
# is preserved.  C_L* = √(C_D0/k); C_D* = 2·C_D0.
```

In constant-L/D mode this collapses to `L = D · (L/D)` with no
equilibrium trim, so the lift force is set by whatever density and speed
the vehicle finds itself at — the classic phugoid restoring mechanism.

This is the "skip glider" of classical re-entry literature (e.g. Sänger,
Chapman 1958). Real boost-glide vehicles avoid this mode because the
large oscillations carry the vehicle in and out of severe heating
regimes; Acton explicitly notes (2015 p. 195) that DARPA's design
schematics show the glider "bouncing just once during the pull-up"
rather than continuing in unsuppressed phugoid. The mode is included
for pedagogical completeness, for true skip-vehicle modelling, and as a
sanity check against the equilibrium-glide modes.

The oscillations are *bounded and damped* — atmospheric drag removes
energy on every cycle (the up-swing into thinner air loses less than the
down-swing into denser air), and the amplitude decays over many cycles.
Bounded does not mean small: the first-cycle peak-to-trough altitude
swing can be tens of kilometres for a vehicle entering at v ≈ 6 km/s.

#### 12.3.4 Skip-to-equilibrium (Lewis) — *retired*

> **Retired.** `skip_to_equilibrium` is aliased to `damped_glide` on load
> (`_norm_glide_mode`, `booster_models.py`) and is no longer offered in the
> dropdown. The continuous damped phugoid glide produces the same "skip a
> while, then settle" behaviour without the discrete N-skip handoff, so the
> handoff and its `glider_skip_count` control are gone. The EOM path described
> below is retained but unreachable; the description is kept for provenance.

A Thrusty-original hybrid that bridges the gap between Acton's idealized
smooth pull-up and the unsuppressed phugoid of skip-glide. The vehicle
flies in `skip_glide` (phugoid) mode for a user-specified number of
*upward crossings of the equilibrium-speed curve*, then transitions
one-way to `equilibrium_glide` (Tracy) mode for the remainder of the
flight (`trajectory.py`).

The skip count `glider_skip_count` (default 1; GUI spinbox 1–10) gates
the handoff. With `N = 1` the vehicle pulls up phugoidally once, then
settles into equilibrium glide on the first descent leg — a close match
to the DARPA HTV-2 schematic that Acton describes. With `N = 2 – 3` the
vehicle skips two or three times before settling, which is closer to
what real, marginally-damped boost-glide vehicles probably do. With
large N the mode approaches pure phugoid skip-glide; with `N = 1` and a
smooth initial trajectory it approaches Acton.

The motivating physical observation: a real boost-glide vehicle is
unlikely to either oscillate forever (skip-glide) or settle perfectly
on the first cycle (Acton's idealization). Some bounded number of
damped phugoid cycles before quasi-equilibrium is a more realistic
intermediate picture. The skip-to-equilibrium mode captures this
without requiring a full 6-DOF model with explicit roll-rate dynamics.

At the handoff the milestone logger emits a *"Skip-to-equilibrium
handoff"* event, and the trajectory dictionary's `flight_events` records
the time, altitude, and speed of the transition. The handoff itself is
implemented as a one-way mode flag flip — the EOM continues integrating
the same state vector, only the lift-trim rule changes (`trajectory.py:
2556`).

#### 12.3.5 Damped-phugoid glide (Lu)

The `damped_glide` mode (the Thrusty default for new glide RVs) fills the
physical middle of the spectrum between undamped `skip_glide` (ζ = 0) and
the analytic non-oscillatory capture of Acton (ζ → ∞). It reproduces what
a *guided* hypersonic glider actually does — a pull-up plus a few
**decaying** skips settling into equilibrium glide — with the number of
skips emerging from a single damping knob rather than a hand-set integer.

The vehicle flies the max-L/D trim angle α\* (identical to `skip_glide`)
plus a feedback term proportional to the altitude-rate error, which bleeds
energy out of the phugoid ([Lu 2013](#16-references) Eq. 33; equivalently
Yu & Chen 2011 Eq. 19):

```
L·cos σ_cmd = L·cos σ_nom − k_h·(ḣ − ḣ_eq)
```

with `ḣ = V·sin γ` the current altitude rate and `ḣ_eq = V·γ*` the
command, where `γ* = −2·H_ρ·g / (V²·cos σ·(L/D))` is the
quasi-equilibrium-glide flight-path angle (Lu Eq. 31 — L/D in the
denominator, so higher L/D glides shallower; matches Vinh, Coppola &
de-Olivé Ferreira 1996 and the classic γ = −1/(L/D)).

**The gain — derived, not fitted.** Linearising the planar equilibrium-glide
EOM about equilibrium gives, from first principles, a harmonic oscillator for
the altitude perturbation. At fixed angle of attack lift ∝ ρ ∝ e^(−h/H_ρ), so a
displacement δh changes the lift acceleration by `d a_L/dh = −g_eff/H_ρ`, giving
the open-loop mode

```
δḧ + ω_p²·δh = 0,    ω_p² = g_eff / H_ρ   (g_eff = g − V²/r)
```

where `H_ρ = −ρ/(dρ/dh)` is the local density scale height (the restoring force
is the density lapse). This linearisation is the second-order entry theory. The
primary source is Chapman (NACA TN 4276 / NASA TR R-11), who reduces the planar
entry equations to one second-order nonlinear ODE (Eq. 21) in a density-like
variable `Z(ū)`; its truncation neglecting vertical acceleration is the
equilibrium glide (his `Z_II` solution, attributed to Sänger), and the full
equation produces, for higher L/D, the oscillation he calls "numerous skips of
sizable intensity" (Fig. 6). Yaroshevskii's equation (Vinh, Busemann & Culp,
Ch. 10, Eq. 10-55) is a special case, with the same Sänger equilibrium glide
(Eq. 10-61) and the same numerically-shown oscillation (Fig. 10-10). The
oscillator above is the linearisation of that ODE about equilibrium glide; all
three sources show the oscillation but none writes the closed-form oscillator.
The frequency is also corroborated empirically by [Liu et al. 2025](#16-references)
(measured skip phugoid 0.021–0.037 rad/s). The altitude-rate feedback adds the `2ζω_p·δḣ`
damping term; matching the feedback contribution to `2ζω_p` fixes the gain for a
target damping ratio ζ:

```
k_h = 2·ζ·m·√(g_eff / H_ρ)
```

The gain is recomputed each integration step from the current state, so it
schedules down naturally as V and g_eff change (matching Lu's
velocity-scheduled gain, his Eq. 34).

**Why ζ = 0.7.** ζ is the single user knob (`glider_damping_zeta`, default
**0.7**). The 0.7 default is the classical second-order control value: it
sits in the desirable ζ = 0.4–0.8 band that the standard control texts
recommend for transient response — below 0.4 yields excessive overshoot,
above 0.8 responds sluggishly ([Ogata 2010](#16-references) §5-3, p. 171;
[Franklin, Powell & Emami-Naeini 2019](#16-references) §3.4.2 / Fig. 3.24,
which lists ζ = 0.7 → ~5 % overshoot as a "frequently used value"). The
first overshoot is `M_p = exp(−πζ/√(1−ζ²))` ≈ 4.3 % at ζ = 1/√2 (~5 % at
ζ = 0.7; Ogata Eq. 5-21, Franklin Eq. 3.72), and ζ ≈ 0.7 is very nearly
the *settling-time-minimizing* damping (Ogata p. 173 finds t_s bottoms out
near ζ = 0.68–0.76) — so it is the fastest settling without a sluggish
approach. (ζ = 1/√2 is also the "maximally flat" 2nd-order Butterworth
value in the *frequency* domain, but that is a separate characterisation,
not the time-domain transient-response argument above.) ζ = 0.7 is a
modelling choice describing a competently-guided vehicle, not a physical
constant of the airframe; it is freely dialled — ~0.3 gives several lazy
skips, ≥ 1.0 collapses to a smooth equilibrium capture. In short, ζ is a
property of the *guidance*, not the airframe — the bare vehicle's skip
phugoid is essentially undamped and is suppressed only by active control
([Tracy & Wright 2020](#16-references)) — so the designer chooses it,
dialling in more damping for a smoother, single-bounce capture
([Acton 2015](#16-references)) or less for a bouncier, longer-skipping
profile, with 0.7 the conventional well-guided midpoint
([Ogata 2010](#16-references); [Franklin et al. 2019](#16-references)).

**Nesting (the safety property).** ζ = 0 ⇒ k_h = 0 ⇒ the feedback term
vanishes ⇒ the lift law is *exactly* `skip_glide`. This is verified
bit-exact (`max|Δaltitude| = 0.000000 km` over a full integration, both
aero models) in `damped_glide_smoke_test.py`. Large ζ drives the
trajectory onto equilibrium glide, so `damped_glide` continuously
interpolates between the two existing endpoints.

**Validation.** Flying the repo's C-HGB glide body on a sub-circular
(MRBM-class) boost, entering at ~5.6 km/s:

| mode | fraction of glide above 100 km | range |
|---|---:|---:|
| `skip_glide` | 57 % (skips out of the atmosphere) | 2445 km |
| `damped_glide` ζ = 0 | 57 % (bit-identical to skip_glide) | 2445 km |
| `damped_glide` ζ = 0.7 | 14 % (glides in the atmosphere) | 6187 km |
| `equilibrium_glide` | 27 % | 6246 km |

Damping at ζ = 0.7 converts a skip that spends most of its flight *above*
the atmosphere into a true in-atmosphere glide, nearly tripling range to
match the analytic equilibrium glide.

**Limits.** Gated, like `skip_glide`, on being below the 100 km pierce
altitude and on dynamic pressure (`q > 1` Pa) — no aerodynamic control in
vacuum. The feedback is disabled when `g_eff ≤ 0` (at/above circular speed
the phugoid restoring force is undefined); the vehicle then flies plain
α\*. `H_ρ` is finite-differenced from the atmosphere and clamped to
4–12 km. Lift is bounded by the existing `glider_pullup_g_max` cap, so the
manoeuvre respects the structural g-limit automatically.

### 12.4 Bank-to-turn (cross-range manoeuvring)

Cross-range manoeuvring is by *bank-to-turn* with roll angle σ
(`bank_rad` in the code, settable via the RV's bank schedule or a target
point). Banking partitions the lift vector between vertical and
horizontal components:

```
F_lift = L · ( cos σ · n̂_up  +  sin σ · n̂_cross )
```

(`trajectory.py`). This is exactly the Tracy & Wright 2020 EOM
(their Eq. 2 with the `cos σ` factor and Eq. 3 with the `sin σ` factor).
Banking simultaneously reduces the vertical lift component to `L · cos σ`
— which forces the vehicle to fly at a lower equilibrium altitude in
denser air, raising drag — and steers horizontally by `L · sin σ`. This
is the source of the cross-range / range trade-off documented in Tracy &
Wright 2020 Figure 6.

A bank-angle schedule (lat, lon, time tuples) can be set directly on the
RV; alternatively, the GUI's "Aim at target" dialog computes the bank
trajectory that delivers the glider to a specified terminal lat/lon.
The dialog uses Brent's method on bank angle σ with the trajectory
integrator as the inner cost function — analogous to the `aim_booster`
function for ballistic flight (Section 10.4).

### 12.5 Terminal dive (inverted)

When the vehicle approaches the target it transitions to a terminal
dive by rolling to σ = π (inverted), which puts the lift force pointing
toward the ground rather than away from it (`trajectory.py–722`).
The dive is the most efficient way to traverse the dense lower
atmosphere while preserving as much speed as possible — matching the
HTV-2 test profile (Tracy & Wright 2020 §"Computational results",
inverted dive at end of glide).

Two trigger conditions are available:

- **Altitude trigger** (`glider_terminal_dive = True`,
  `glider_terminal_alt_km`): when `alt < terminal_alt_km` the dive
  begins. Default 30 km.
- **Range trigger** (`glider_dive_target_radius_km`): when the
  great-circle distance to a specified target lat/lon falls below
  `radius_km` the dive begins, regardless of altitude. This is the model
  for a glider that dives over the target rather than at a fixed
  altitude band.

When `_dive_now = True` the bank angle is held at π and the inverted-dive
section integrates with the same EOM as the glide phase but with the lift
sign flipped; the vehicle accelerates slightly under combined gravity and
downward lift, traversing the dense lower atmosphere in a few seconds.

Note that `_dive_now` is **re-evaluated every integration step, not
latched.** For the altitude trigger this is immaterial — descent is
monotonic, so once `alt < terminal_alt_km` the condition stays true to
impact. For the range trigger it matters: `_dive_now` is a *region*
(inside the target circle), not a *state*, so the dive holds only while the
vehicle is inside the radius.

#### 12.5.1 The dive radius is a lead distance, not a bullseye

A consequence of the stateless range trigger: a fast, high glider can
**cross the target circle before the dive brings it to the ground.** On the
far side `_dist_km ≥ radius_km` goes true, `_dive_now` releases, the bank
snaps back to the schedule, and the glide law — seeing the large sink rate
the dive built up — arrests it and pulls the vehicle back up. The altitude
trace shows a characteristic **notch** (a dip, then a climb) and the vehicle
overflies the target by a wide margin. The glide law and the dive command
are not fighting a bug; each is doing its job, and which one owns the step
depends only on whether the vehicle is inside the circle *this* step.

The radius therefore behaves as a **lead distance**: it must be large enough
that the vehicle commits to the dive with enough horizontal room to reach
the ground *before* it crosses the circle, but not so large that it commits
far short of the target. The dependence is **non-monotonic** — both too-small
and too-large miss — with three regimes (illustrated with a C-HGB glider off
the AUR stack, diving from ≈29 km at ≈Mach 4–5; the numbers are
vehicle- and speed-specific, the *shape* is general):

| radius | behaviour | impact miss |
|---|---|---|
| ≤ ~30 km | dive triggers late/close; vehicle crosses the circle, recovers (the **notch**), overflies | ~130–250 km beyond |
| ~35–60 km | single committed dive to ground inside the circle; no notch | ~20–30 km |
| ≥ ~100 km | dives too early; falls **short** of the target, miss growing with radius | 40 → 230 km short |

The residual miss at the sweet spot (~20 km here) is not a dive artefact: it
is the offset between the glider's ground track and the target (the track
passes ≈20 km abeam), which is an aim/azimuth matter — no terminal dive can
recover cross-track error the glide did not already null out.

**Operating guidance.** Treat the radius as a tuning knob, not a target
size. Start from a value comparable to the horizontal distance the vehicle
covers while descending from its trigger altitude (roughly *trigger
altitude × (L/D)* for a lift-down dive), then increase it until the notch
disappears and the impact is closest; if the impact then begins to fall
short, the radius has passed the lead distance and should come back down.
The trigger is stateless by construction, so the radius — not a latch — is
where the operator sets the commit distance. (A one-way latch that commits
on first entry is a possible alternative model; it would remove the
overshoot regime but also remove the operator's control over *where* along
the approach the commitment happens, and is not the model implemented here.)

### 12.6 RV library

The reentry-vehicle library is a directory of JSON files
(`ro_library/*.ro.json`), each fully specifying one RV's mass, geometry,
ballistic coefficient, L/D, drag polar, nose-tip radius, emissivity, and
default guidance mode. The shipped library covers a spectrum of
public-domain reference vehicles:

| File | Class | L/D | β (kg/m²) |
|---|---|---:|---:|
| `C-HGB.ro.json` | Common-Hypersonic-Glide-Body | 2.0 | 15 000 |
| `HGB.ro.json` | Generic hypersonic glider (HTV-2-class) | 1.8 | 15 000 |
| `HGB-LD3.ro.json` | Hypothetical high-L/D glider | 3.0 | 10 000 |
| `Generic-RV.ro.json` | Generic ballistic RV (no glide) | 0.0 | 10 000 |
| `Mk21.ro.json` | Mk-21 RV (LGM-30 / LGM-118) | 0.0 | 75 000 |

A user can copy any of these as a starting template, edit the JSON
fields, and drop the file into `ro_library/`; the GUI's RV dropdown
re-scans the directory on startup. This is one of the extension hooks
named in §1.1: the shipped vehicles are a starting set, not a closed
inventory.

The JSON file for an RV contains only the fields the author wanted to
set; anything omitted inherits the `ROParams` default. The shipped
`HGB.ro.json` is representative — twelve fields, no glider-polar
parameters and no Acton-mode β_S:

```json
{
  "name":                    "HGB",
  "mass_kg":                 450,
  "beta_kg_m2":              15000,
  "shape":                   "cone",
  "diameter_m":              0.5,
  "length_m":                2.0,
  "glider_enabled":          true,
  "glider_LD":               1.8,
  "glider_guidance":         "equilibrium_glide",
  "glider_pullup_g_max":     10,
  "glider_terminal_dive":    false,
  "glider_terminal_alt_km":  30
}
```

The full set of fields recognised by the JSON loader, with their
defaults:

| Field | Default | Notes |
|---|---|---|
| `mass_kg` | (required) | Vehicle mass |
| `diameter_m` | 0.5 | Reference diameter |
| `length_m` | (optional) | Used for slender-body checks |
| `shape` | `"cone"` | Nose-shape selector |
| `nose_radius_m` | 0.0 = auto | Stagnation radius for heating (Section 13.1); 0 ⇒ derived from nose shape + diameter, a positive value overrides |
| `emissivity` | 0.85 | Surface emissivity for T_eq calculation |
| `beta_kg_m2` | 10000 | β_L — equilibrium-glide ballistic coefficient |
| `glider_beta_entry_kg_m2` | 0.0 | β_S — Acton direct-re-entry β; 0 disables Acton mode |
| `glider_enabled` | `false` | Master toggle for HGV machinery |
| `glider_LD` | 0.0 | Lift-to-drag ratio |
| `glider_aero_model` | `"constant_LD"` | Or `"polar"` (Section 12.2) |
| `glider_CD0` | 0.05 | Zero-lift drag coefficient (polar mode) |
| `glider_k_polar` | 0.10 | Induced-drag factor (polar mode) |
| `glider_guidance` | `"equilibrium_glide"` | Section 12.3 |
| `glider_skip_count` | 1 | Skip-to-equilibrium handoff count |
| `glider_pullup_g_max` | 10.0 | Structural load-factor cap |
| `glider_terminal_dive` | `false` | Enable inverted terminal dive |
| `glider_terminal_alt_km` | 30.0 | Altitude trigger for terminal dive |

The full schema lives in the module-level loader `ro_from_dict`
(`booster_models.py`).

**Acton mode and β_S.** The shipped JSON RVs leave `glider_beta_entry_kg_m2`
at zero, since β_S (the high-α drag direct-re-entry ballistic coefficient)
is published for only a handful of vehicles. Selecting Acton mode for an
RV with β_S = 0 falls back to Tracy mode (Section 12.3.2). For the
HTV-2-class built-in missiles defined programmatically rather than via the
RV library — `Forden_HTV2` and its variants — the code sets
`glider_beta_entry_kg_m2 = 7.0` based on Acton 2015 Table 3
(`booster_models.py, 1635`). A user wanting to run Acton mode on a
custom RV will need to research and set β_S themselves; this is by design,
since silently fabricating β_S for arbitrary vehicles would be misleading.

The values shipped in the library are starting points calibrated against
public literature (e.g. `C-HGB.ro.json`'s L/D = 2.0 follows the open-source
DoD common-glide-body briefings, and `HGB.ro.json`'s L/D = 1.8 / β =
15 000 kg/m² approximates the HTV-2 class without claiming to be HTV-2);
users should re-verify them against the specific scenario being modelled
rather than treating them as endorsed estimates.

---

## 13. Stagnation heating

For HGV trajectories Thrusty reports a single stagnation-heating
milestone — the peak heat-flux value and the corresponding
radiative-equilibrium wall temperature — at the time during the glide
phase when stagnation heating is maximum. This is the minimal
information needed to compare a simulated trajectory against
public-source claims about peak nose-tip temperatures and material
limits, without taking on the substantially larger modelling burden of
a full transient aerothermal solution.

The model is convective heating only — no radiative gas-cap heating, no
ablation, no wall conduction, no transient temperature. For preliminary
trajectory work these omissions are appropriate; for vehicle thermal
design or material selection they are not, and a different tool
(CBAERO, MINIVER, or full CFD) is the right choice.

### 13.1 Sutton-Graves stagnation heat flux

The convective heat flux at the stagnation point is computed from the
Sutton-Graves correlation
([Sutton & Graves 1971](#16-references), NASA TR R-376):

```
q̇ = K · √(ρ / R_N) · V³                     [W/m²]
```

with `K = 1.7415×10⁻⁴ W·s³/(kg^½·m^(5/2))` for Earth atmosphere,
`ρ` the free-stream density in kg/m³, `R_N` the nose-tip radius of
curvature in m, and `V` the free-stream velocity in m/s
(`trajectory.py`).

The Sutton-Graves correlation is a fit to chemical-equilibrium boundary
layer calculations across a wide range of base gases, enthalpies (2.3 to
116.2 MJ/kg), and pressures. For Earth re-entry conditions it
agrees with the more rigorous Fay-Riddell relation to within ~10 % over
the speed range relevant to HGV glide.

Three implementation conventions:

1. **ECEF velocity, not inertial.** `V` is the vehicle's speed relative
   to the rotating atmosphere (i.e. the airspeed), not the inertial
   ECI speed. At the equator this differs by ~465 m/s; the difference
   matters at HGV velocities of 3–6 km/s. The relevant comment is at
   `trajectory.py`.

2. **Per-RV nose-tip radius.** `R_N` is the active RV's effective
   stagnation radius (`ROParams.effective_nose_radius_m`, used in
   `trajectory.py`), making the stagnation-point formula geometry-aware.
   An explicit `nose_radius_m` is authoritative; when it is 0/absent the
   value is a screening default derived from the nose shape and base
   diameter (`nose_tip_radius`, `booster_models.py`): `R_N ≈ 0.10·R_body`
   for a sharp cone, scaled up for blunter profiles (von Kármán, LV-Haack),
   clamped to [5 mm, R_body]. This is a transparent bluntness heuristic,
   not a geometric tip-curvature — the idealised profiles are all
   geometrically sharp at the tip, and real bluntness is a design choice
   the outer shape does not fix (every shipped library RV is a `cone` yet
   spans 1–5 cm tips). The shipped library sets explicit radii where known
   (HTV-2 1 cm, C-HGB 2 cm, AHW 5 cm). Two RVs at the same speed and
   density see different stagnation fluxes: `q̇ ∝ 1/√R_N`, so a 1 cm nose
   sees about 2.2× the flux of a 5 cm nose. The peak-heating *time* is
   independent of `R_N`; only the peak *magnitude* changes.

3. **Re-entry/descent phase.** Heating is computed for any re-entering
   terminal vehicle — a ballistic RV as well as a glider — over the
   descent arc after the 100 km crossing (Section 12.1; for sub-100 km
   profiles, after apogee). A steep ballistic RV is the high-flux regime
   the survivability FOM most needs to score, so it is no longer excluded.
   Glide-specific milestones (pull-up / glide-start / skips / terminal
   dive) remain gated on a lifting vehicle. Boost and ascent heating is
   not separately reported because for typical operational vehicles the
   boost-phase stagnation flux is much smaller than the descent peak, and
   the booster nose is not the surface that matters for payload survival.

### 13.2 Radiative-equilibrium wall temperature

The peak heat-flux value is converted to a radiative-equilibrium
stagnation-point temperature via the Stefan-Boltzmann law assuming
all incoming convective flux is balanced by surface re-radiation:

```
σ · ε · T_eq⁴ = q̇_peak             ⇒    T_eq = (q̇_peak / (σ · ε))^(1/4)
```

with `σ = 5.670374419×10⁻⁸ W/(m²·K⁴)` (CODATA 2019, Stefan-Boltzmann
constant) and `ε` from the RV's `emissivity` field (default 0.85; set
at `ROParams`, `booster_models.py`). The default is consistent with
[Anderson 2006](#16-references) §18.8 (HERMES emissivity example) and
the upper end of the operational range for reinforced carbon-carbon
(RCC) materials reported by [Williams & Curry 1992](#16-references) in
NASA RP-1289 (RCC ε(T) measurements).

This is a radiative-equilibrium estimate, not a transient temperature.
It assumes the surface has reached steady-state at peak-heating
conditions; in reality the wall temperature lags peak heating slightly
because of the surface's thermal mass. For a thin RCC leading edge the
lag is small (seconds); for a thick ceramic ablator it can be
significant. The radiative-equilibrium value is therefore an
*upper bound* on the actual wall temperature at peak heating — the true
surface is somewhat cooler because it is still warming when peak
flux occurs.

### 13.3 What is not modelled

Several aerothermal effects are deliberately *not* implemented, to keep
the heating model simple and the failure modes obvious:

- **No cone-flank or boattail heating.** Only the stagnation point is
  computed. For a slender HGV the stagnation-point flux is the
  worst-case value; cone-flank heating downstream of the nose is lower
  by a factor that depends on local-flow Reynolds number and pressure
  gradient. If a finer-grained heating breakdown is needed, Tauber's
  1989 sharp-cone heating relation (NASA TP-2914, Eq. 46) or Lees 1956
  blunt-body laminar-heating treatment would be natural extensions —
  but neither is in the current code.
- **No emissivity vs. temperature.** Real materials have temperature-
  dependent emissivity (e.g. RCC's ε rises from 0.78 at 1500 K to
  ~0.88 at 2200 K per [Williams & Curry 1992](#16-references)). The
  code uses a single user-set value across the full trajectory.
- **No radiative gas-cap heating.** At V > ~7 km/s the shock layer
  begins to radiate appreciably, contributing additional heating
  beyond pure convection. This is small for HGV velocities below
  ~6 km/s but becomes significant for steep ballistic re-entry from
  ICBM trajectories.
- **No ablation cooling in the surface balance.** The radiative-
  equilibrium surface temperature assumes a steady non-ablating
  surface; an ablating shield absorbs part of the incoming flux as
  mass-loss enthalpy, so the real surface runs cooler than T_eq
  (the surface screen is conservative-high in that regime).  *Wall
  conduction is now modelled for the interior axis* — see §13.10, the
  bondline screen — but the surface energy balance itself stays
  radiative-equilibrium.
- **No rarefied/transition regime.** Sutton-Graves (laminar continuum)
  is applied at every altitude.  Above the free-molecule crossover —
  ρ_c/ρ₀ = (2.023×10⁻⁸/R_n)·V^0.3, ≈ 90–95 km for cm-scale nose radii at
  ICBM speeds — the true (free-molecule) heating is *lower* (q ∝ ρ vs
  ∝ √ρ), so the continuum-everywhere choice over-predicts there:
  conservative in sign, negligible in integrated load, but heating-onset
  altitudes read slightly early/hot.  Finke (IDA P-2395, 1990; DTIC
  ADA231552, read from primary) gives the standard fix — a bridging
  function q̄ = (q_FM⁻ⁿ + q_L⁻ⁿ)^(−1/n) — if onset timing above ~90 km
  ever matters.  The same paper independently reproduces this section's
  entire T_eq chain to 1–9% (`test_finke_check.py`; BENCHMARKING
  "Heating-chain verification").

All five omissions can be addressed by post-processing the trajectory
in a more capable aerothermal tool (CBAERO, MINIVER, or CFD); the
trajectory itself is what Thrusty is built to produce, and the
single-point heating estimate provides the validation hook against
published peak-temperature claims.

### 13.4 Output and milestone format

When a glide trajectory completes, the code computes `q̇` at every
glide-phase time step (`trajectory.py`), finds the argmax, and
emits a flight-events row:

```
Peak heating  ({q̇_peak/1e6:.1f} MW/m², T_eq ≈ {T_eq:.0f} K)
```

inserted chronologically into the trajectory's `flight_events` list at
the time of peak heating. This is the only heating-derived output; the
full `q̇(t)` time series is computed internally but not exposed to the
user. Adding a CSV column for `q_dot_W_m2` would be a small extension
if a user wanted the time series for plotting.

### 13.5 Survivability judgements: the unified 4-tier survival ladder

Every material — ablator, hot structure, metal, tile — reports the **same
four-tier verdict**, so the reader never has to know which criterion fired
(recession vs temperature vs dwell vs heat-sink).  The underlying test
differs by material; the headline your eye reads is always one of these four
(`survivability_report.SURVIVAL_TIERS` / `survival_tier()`):

| Tier | Colour | Meaning |
|---|---|---|
| **Within experience** | green | comparable objects/materials have *demonstrated* this (flight or test) |
| **Within design envelope** | blue | beyond demonstration but within design/theory — *permitted extrapolation* |
| **Beyond design envelope** | yellow | past design too — undemonstrated *and* unsupported; less likely |
| **Cannot survive** | red | a **computed** failure — burn-through, melt, a t_fail crossing |

The report body is layered as an **inverted pyramid** for the policy reader:
a plain-language lead (what was flown; why the verdict is what it is —
binding location + mechanism; what would change it; one NRC design-lineage
context sentence, phrased so the lineage rungs are never mistaken for a
demonstration of the flown material), then a "Full analysis" divider, below
which the complete engineering text — heating budget, per-location margins,
judgement with citations, the NRC ladder — is unchanged.  The coverage text
names the tier bands the plot actually shades (blue "within design" for
too-long, yellow "beyond design" for too-hot); pinned by
`test_report_lead.py`.

Two honesty rules are built into the ladder: **red is reserved for a computed
failure** (never a soft "probably won't"), and **blue is only reachable for a
material with a demonstrated envelope to extrapolate past** — the direct
payoff of a curated anchor dataset.  A material with no curated envelope can
only land green / yellow / red; it cannot claim "within design but beyond
experience," because without the data that distinction isn't ours to make.

A third rule keeps the axes honest: **the ladder answers "does it survive,
and on what evidence" — a survivable consequence does not drag the tier
down.**  A ballistic RV or glider whose ablative nose recedes carries a
consequence (dispersion growth, aeroshape drift) that is itself flight-
demonstrated (Lin 1982; PANT; Reentry-F flew ≈0.7 R_n) — so it stays *within
experience* (green) as long as its flown heat load is within the family
flight record (§13.6), with the accuracy consequence stated as a report
sentence, not allowed to set the survival tier.  (The motivating regression:
a Mk21-class RV on an easier-than-design IRBM trajectory briefly read "beyond
design envelope" because a recession point-estimate — over-predicted by the
conservative-low H_eff — was tested against measured-recession thresholds and
allowed to drive the tier.)  Yellow is reserved for genuine envelope exits:
the passive→active oxidation edge, an ablator load *past* its flight record,
or a state the screen cannot assess (T_eq past the 4,000 K no-ablation
bound).  Burn-through (the bounded tripwire), melt, and t_fail crossings
remain red; a material with anchor
data (UHTC, and RCC/C-SiC as curated) uses the demonstrated-envelope
coverage below.

For UHTC hot-structure gliders that judgement is
deliberately **not** a pass/fail number.  The flight and arc-jet record
for these materials is sparse and one-sided — nearly every published test
is a *survival* (the test stopped; it did not fail) — so a single
oxidation-dwell cliff would overclaim in both directions.  Instead the
report states **coverage against a demonstrated envelope** (design:
`SURVIVABILITY_REPORT_DESIGN.md` §11; anchor dataset:
`BENCHMARKING.md`):

- **Below the ~1650 °C borosilicate-glass ceiling** (multiply-sourced:
  Monteverde 2012, Peters 2024, Fahrenholtz & Hilmas, Marschall, Li) the
  material is silica-protected and no dwell clock runs.
- **Above the ceiling but inside the demonstrated floor** (e.g. 300 s at
  1973 K with zero recession; ~575 s at a 2450 °C sharp tip with
  measurable blunting) the trajectory is *within the envelope*, consuming
  recession margin.
- **Beyond the envelope** — the surface crosses the **passive→active (PA)
  oxidation boundary** (protective silica lost, heating runs away —
  Marschall's +400 K jump), or dwell outruns the demonstrated floor — the
  report says *extrapolation*/runaway, not a bare pass: the data does not
  license a clean verdict.  The PA edge is a **flux/pressure surface, not a
  fixed temperature** (plain ZrB₂-SiC went active at ~2215 K / 2 MW/m² /
  10 kPa on a flat face, but stayed passive to 2450 °C at 7 MW/m² on a sharp
  conducting tip), so it is evaluated at the run's own flux and pressure.

The envelope is **derived from a per-datum anchor table**, not hardcoded:
survivals bound it from below, failures cap it from above.  Caps come from the
Levine et al. 2003 1-atm furnace failures (NTRS 20040033992, passive-oxidation
regime only); two convergent doped/complex *oxide-detachment* caps — the Di Maso
2009 HfB₂-TaSi₂ sharp cone and the De Prisco 2026 ZrB₂-TiB₂-SiC hemispheres (*J.
Eur. Ceram. Soc.* 46, 118184) at ~2700–2800 K; and the keystone **plain-ZrB₂-SiC
PA transition**, a pressure-explicit, flight-corroborated (SHARP-B1) runaway
threshold that is triple-sourced — Marschall 2012 (*J. Thermophys. Heat
Transfer* 26(4), +400 K jump at ~2 MW/m² / 10 kPa), Monteverde 2017 (*J. Eur.
Ceram. Soc.* 37, onset ~2050 K), and Zhang 2008 (*Compos. Sci. Technol.* 68,
flux-bracketed passive at 1.7 MW/m² ↔ active at 5.4 MW/m² with ~5 µm/s
recession).  All cap
doped/complex diborides, never plain ones.  The De Prisco pair, same specimens
run at two pressures, is direct evidence that the SiC active/passive transition
is pressure-sensitive: survived 1700–1800 K at 3×10⁻³ atm, detached at 2700 K
at 2.3×10⁻² atm.  A new flight or test strengthens the dataset as a data edit.  Two scoping rules carry
citations: dopant effects invert with temperature (TaSi₂ best-in-class at
1627 °C, destroyed at 1927 °C — Levine 2003, low side corroborated by Gasch &
Johnson 2010), so envelopes are built per material *class* and doped variants
are never averaged into the parent; and the aero-convective anchors span a wide
pressure range — 3×10⁻³ atm (De Prisco Mach 6) to ~1 atm (Savino et al. 2008,
HfB₂/HfC-MoSi₂) — but the long-dwell points are low-pressure, so in-envelope
coverage still carries a facility-pressure caveat since the SiC active/passive
transition is pressure-sensitive.

The **complete anchor dataset** (every flight/arc-jet/plasma-torch/furnace
datum, with verified numbers and exact citations) lives in `BENCHMARKING.md`;
the survival side of each material class is covered there — ZrB₂-SiC
(Monteverde & Savino 2012 sharp, Scatteia et al. 2010 blunt, Monteverde 2013,
Zhang 2008), HfB₂-SiC (Gasch & Johnson 2010; Sevastyanov et al. 2014 at
2500–2700 °C for 15–18 min), HfB₂/HfC-MoSi₂ (Savino 2008), and carbide-boride
(Xu et al. 2026) — alongside the review-level corroboration (Peters et al. 2024;
Glass 2011, AIAA 2011-2304, which also confirms the literature UHTC *component*
failures were mechanical/attachment, not oxidation).  METHODS names the
threshold-setting sources inline; `BENCHMARKING.md` is the citation of record for
the full set.

*Status:* **implemented** (SRD §11.7 steps 1–4).  The `uhtc` catalog entry
carries the cited thresholds (`continuous_K` = 1923 K glass ceiling;
`oxidation_dwell_s` = 300 s demonstrated floor, labeled floor-not-cliff);
the anchor dataset lives as `survivability_report.UHTC_ANCHORS` (§11.2
schema, one record per cited datum — a new flight is a data edit); Form B/C
verdicts for UHTC hot-structure noses use the green/amber/red coverage
shading with the two named exits (too hot = PA transition at the
sharp/blunt-appropriate anchor; too long = past the demonstrated floor),
report **extrapolation rather than asserted failure**, cite the bounding
anchors inline, and carry the §11.6 ground-facility-pressure asterisk; the
Reentry Survivability tab shades the flux/load plot with the coverage
bands.

### 13.6 Ballistic-RV ablator recession: bounding vs. tuning anchors

For ablative ballistic RVs (Form A) the survival question is recession, not a
surface-temperature limit: an ablator sits *above* its onset temperature and
survives by receding at its ablation temperature.

**Verdict logic (revised 2026-07): compare load to the flight record; compute
only a bound.**  The screen no longer reports a recession *point-estimate* as
its verdict.  A point value of `δ = ∫q̇dt / (ρ·H_eff)` inherits the ~5× flight-
regime spread of `H_eff` while *looking* precise — that is what over-flagged an
Mk21-class RV on an easier-than-design IRBM trajectory at δ/R_n ≈ 0.4 (the
δ/R_n consequence ladder's thresholds, 0.10 / 0.50, are *measured*-recession
values, so testing an over-predicted δ against them compares unlike things).
Instead, mirroring the UHTC dwell-floor treatment (§13.5):

- **Load vs. record.**  The flown ablating heat load Q (the integral of the
  incident flux while the surface is above its ablation onset) is compared
  against the material family's **demonstrated flight-load record** — a cited,
  editable benchmark (Screening Envelope dialog): graphite / bare carbon-carbon
  ≈ 3,870 MJ/m² (Reentry-F), PICA ≈ 276 MJ/m² (Stardust), carbon-phenolic
  ≈ 60 MJ/m² (Pioneer Venus Large Probe — Cabrera & West 2026 coupled
  reconstruction; a short radiation-heavy CO₂ pulse, so deliberately
  conservative as a load record; Hayabusa corroborates higher — BENCHMARKING
  "CLOSED — carbon-phenolic demonstrated load").  Within the record →
  *within experience* (green); past it → *beyond design envelope* (yellow, no
  comparable flight experience — undemonstrated, not impossible); the
  low-density ablators (SIRCA, ablative C-C blend, silica phenolic) still have
  **no cited integrated-load anchor** and read "survives by design; recession
  is a refinement question" until the tripwire.
- **Burn-through is a BOUND, not a point.**  Red ("cannot survive") fires only
  if the shield is consumed even at the **most optimistic cited `H_eff`**
  (`H_eff_bound_MJ_kg`) — so a computed failure is a genuine bound, never a
  point-estimate that could be an artifact of the conservative-low `H_eff`.
  Validated both directions by `test_form_a_bounds.py`: the tripwire must NOT
  fire for the recovered Stardust/Hayabusa capsules, and DOES fire for a 2 mm
  shield under Stardust's load.  P3-class caveat (Hassan 1998 / Kuntz 1999,
  BENCHMARKING "CFD lineage"): the flux history is fixed-geometry, so in
  severe-recession regimes where the ablating tip reshapes and heating feeds
  back (their IRV-2 receded past its own initial nose radius, late heating
  ~70 MW/m²) the bound fires LATE — mitigated because the load-vs-record
  verdict goes yellow well before any current use case nears that regime.
- **δ survives only as context.**  The full analysis still prints δ as a *band*
  across the cited `H_eff` range (optimistic..nominal) — "a band, not a
  prediction" — never as a tier-driving number.  The accuracy consequence
  (recession-driven dispersion) is a cited sentence (Lin 1982; PANT; Reentry-F
  flew ≈0.7 R_n), promoted to the report lead only past ~50% of the record; it
  never drags the *survival* tier down (survival and accuracy are separate
  axes — §13.5).  An ablator's "Peak T_eq" is suppressed entirely: an ablating
  surface caps its own temperature, so a T_eq for it is a flux restated in
  kelvin, not a temperature anything experiences.

The `H_eff` bands, the Reentry-F tuning trace, and the capsule bounds below are
the evidentiary base for the load records and the tripwire bound — `H_eff` is
no longer a buried constant that silently sets a verdict; its one remaining role
(bracketing the tripwire) is stated in the report.  The closed-form recession
screen itself (δ = ∫q̇dt/(ρ·H_eff), material ablating at a fixed temperature) is
independently corroborated by a CFD-tier study: Tabiei & Sockalingam 2011
(FLUENT/LS-DYNA coupled multiphysics) uses the identical ṡ = q_w/(ρ·Q\*) form
for surface recession (BENCHMARKING "Methods + material corroboration").

`H_eff` is the **effective heat of ablation Q\***, which is *enthalpy- and
regime-dependent*, not a fixed constant — so the catalog nominals
(carbon-phenolic 15, PICA 35, carbon-carbon 40 MJ/kg) are deliberately set at
the **conservative (severe-regime) end** of the cited data, which makes the
screen **over-predict** recession in benign regimes.  Each nominal is now
cited: CP 15 equals the measured *mechanical-char-removal-regime* value
(Sutton, NASA TN D-5930, 1970: Q\* collapses to 14–20 MJ/kg once char removal
begins — onset as low as 2.4 atm stagnation in air — while clean low-pressure
rows run 68–195 MJ/kg); PICA 35 sits at/below the Winter 2014 arc-jet point
(38–77 MJ/kg); C/C 40 sits below the Reentry-F flight bracket and Scala/Perini
diffusion-limit theory, with the Nestler ≥80 atm severe-regime floor as its
validity limit.  Uncertainty bands and provenance: `BENCHMARKING.md`
("Form A recession anchors"); `benchmarks/form_a/phase2-heff-bands.md`.

The anchors split by role, and the split is load-bearing:

- **Reentry-F** (Mach ~20, ATJ graphite nosetip; NASA CR-154044 / TM X-1856 /
  LWP-460, via Berry's nose-tip white paper in the project Drive) is the
  **in-envelope tuning anchor**, wired as the δ/R_n shape-change ladder.  Its
  nosetip recession history after ~60,000 ft is carried as a *spread*, now
  quantified from the clean TM X-1856 Fig. 11 (digitized:
  `benchmarks/form_a/reentryf_tmx1856_fig11.csv`): final radius ~0.20 in
  (thermochemical) to ~0.31 in (erosion-corrected) — 1–2.1 R_n₀ radial growth —
  with the pressure-derived estimates mostly straddling the lower curve, and the
  worst case (reaching the ~0.39 in graphite-plug exposure radius at 458.7 s)
  refuted by the report itself.  The nominal stagnation
  heat pulse is now *pixel-traced* from the nominal-trajectory figure
  (γ_E 21.2°, V_E 20,300 ft/s; embedded scan extracted from the Berry PDF,
  per-ruler tick calibration, apex-first slope tracking, overlay-QC'd; method +
  summary in `benchmarks/form_a/reentryf_nominal_qdot.csv`, full trace in
  `reentryf_qdot_trace_full.csv`): **Q ≈ 3.87 GJ/m² ±20% cold-wall**, apex
  ≈ 348 MW/m² at ~47 kft (the 318 MW/m² benchmark pin equals LWP-460's
  window-max quote; the traced in-window flux range 10–30×10³ Btu/ft²·s matches
  the quoted 9–28×10³), 100→50 kft window ≈ 8 s.  Against the 0.6–1.0 in
  axial-recession spread this gives a flight-derived H_eff *bracket* of
  **70–175 MJ/kg (central ≈ 114)** — independently corroborated by
  boundary-layer theory: Scala's CO-diffusion-limit correlation (via Perini,
  JHU/APL ANSP-M-1, 1971, read from primary) gives Q\* ≈ h_t/0.1725, which at
  Reentry-F's ~18.6 MJ/kg enthalpy predicts ≈ 108 MJ/kg, within ~6% of the
  flight-derived central.  The model's carbon-carbon nominal 40 sits
  below it and **over-predicts recession ~2.9×** — the conservative side for a
  screen, and the same sign as the capsule bounds.  (Both the earlier ~1 GJ/m²
  order-of-magnitude read — and its ~25% under-prediction caveat — and an
  intermediate 2.85 GJ/m² eyeball table are superseded by the pixel trace; the
  eyeball had followed a lower curve through the mid-rise, caught in overlay
  QC.)  Still a bracket, never a single-point H_eff calibration, and
  `heating._BENCHMARKS` Q_MJ stays None: the pulse is a preflight prediction —
  no flight-measured stagnation heating exists (TM X-2560).
- **Stardust** (PICA, recovered, 12.8 km/s) and **Hayabusa** (carbon-phenolic,
  recovered, >12 km/s) are **bounding anchors, not fits** — both now firsthand.
  Post-flight analysis found equilibrium-style ablation chemistry *over*-predicts
  their recession (Hayabusa: measured ~0.3 mm at stagnation by laser scan with
  <10% error, none downstream, against calculation over-estimating by a factor
  of three at a reconstructed peak of 5.3 MW/m² convective + ~1 MW/m² radiative
  — Suzuki et al. *J. Spacecraft & Rockets* 51(1) 2014, DOI 10.2514/1.A32549;
  Stardust 51–61% over at the near-stagnation core — measured 5.7±0.3 mm vs
  8.6–9.2 mm calculated — and 22–25% at mid-flank: Kontinos & Stackpoole AIAA
  2008-1197 Table 1 and the primary itself, Stackpoole, Sepka, Cozmuta &
  Kontinos AIAA 2008-1202 — both held firsthand, identical tables; the
  primary adds that the flank discrepancy sits within the FIAT/PICA-v3.3
  model's own arc-jet calibration scatter while the near-stagnation 61%
  over-prediction was "not fully understood" at publication).  That
  chemistry conservatism *exceeds* the radiative-gas heating the convective-only
  screen omits above ~9 km/s — for Stardust the radiative part was only 9% of
  peak rate / 4% of load, and including it moved the calculated recession just
  9.6 → 10.4 mm — so the net bias is over-prediction.  The capsules therefore
  validate the chain only as a **lower bound** — the model must predict ≥
  measured recession — enforced by `test_form_a_bounds.py` (predicted/measured:
  Stardust 5.1×, Hayabusa 31×).
  **Raising H_eff to shrink that ratio is the failure mode this design forbids.**

Two limitations are logged rather than hidden: **P3-radiative** (convective-only
above ~9 km/s; the omission is *size-dependent* — 9% of peak rate on the 0.827 m
Stardust capsule but ~40% on a CEV-scale 5 m blunt body, both per Kontinos &
Stackpoole AIAA 2008-1197 — and no operational Form A trajectory in the current
use set exceeds 9 km/s) and **P3-chemistry** (equilibrium recession is
conservative vs. flight — the larger bias at capsule scale; a finite-rate
Park/Milos option is the eventual fix, and until then the bound tests enforce
the conservative sign).

*Changelog (symmetry with the UHTC `oxidation_dwell_s` retirement, §13.5):* the
Form A `H_eff_MJ_kg` values were promoted from bare screening guesses to
**conservative-low nominals inside cited Q\* bands**, each independently
bound-checked against the recovered Stardust and Hayabusa capsules.  No nominal
changed value (verdict-stable); the epistemic status did.  H_eff was **not** tuned
to the capsule measurements — by design (see above).

### 13.7 Maneuver-load anchors (demonstrated envelope)

For any glider flying with a commanded lift cap the report adds a
**demonstrated maneuver-load context block** (see §13.14 for why this is
keyed on the lift cap and not on a vehicle "Form").  The anchor
dataset lives as `survivability_report.MANEUVER_ANCHORS` (same data-edit
philosophy as `UHTC_ANCHORS` — one cited record per demonstrated or
published-representative load; the `BENCHMARKING.md` maneuver-anchor campaign
— filed there under its historical "Form C" heading — is the citation of
record): Regan 1984's worked 4-g accuracy-maneuver case, Pershing II's ~25-g
operational pullout (Yengst 2010; maneuver corroborated by Lund 1984),
BGRV's 25-g component qualification (Yengst), AMaRV's flight-measured ~100 g
(Yengst; Bell XI accelerometers, three flights 1979–81), and Regan &
Anandakrishnan 1993's representative 100-g evader (Table D.1).  The block
compares the plan's commanded lift cap (`glider_pullup_g_max`, plumbed into
the heating profile) to the ladder: ≤25 g is the operational-MaRV class,
25–100 g is inside the AMaRV flight-demonstrated ceiling, and >100 g exceeds
every load in the open flight record.  **Context, never a verdict**: the
anchors are structural/guidance survived-the-maneuver demonstrations, not
thermal limits, so the block never changes the survivability status.

### 13.8 Windward-flank heating (glide AoA probe)

A lifting reentry vehicle flies its glide at angle of attack, so the
**windward generator** — not the nose — carries the off-nose acreage heat.
`heating.windward_flank_flux` computes it at screening tier: the α=0 acreage
flux (the cited `BODY_FLUX_FRACTION = 0.13 × body-stagnation` from §13.5's
two-location screen) times a **modified-Newtonian windward amplification**
`A(α) = sin(δ+α)/sin(δ)`, where δ is the forebody half-angle and α the trim
AoA.  The amplification is the surface-pressure ratio `Cp ∝ sin²θ` fed through
the reference-enthalpy laminar scaling `q̇ ∝ √ρ_e ∝ √p_e` (`CP_MAX` cancels, so
it is purely geometric); the method family (Van Driest + Eckert–Tewfik) and
the windward-vs-leeward ordering it reproduces are cited (AGARD-R-754; Tracy
M-7.95 cone gives `A(12°)≈2.46`, `A(24°)≈3.81`), while the closed-form
sin-ratio reduction is a labeled inference (mildly conservative — `ρ_e∝p_e`
holds edge temperature fixed).  It is evaluated over the **glide sub-arc**
(the low-AoA terminal dive is masked out and keeps the nose-stagnation block),
reported as a **T_eq band across α = 5–20°** (ends = Thompson 1989's error
anchors) with the trimmed operating AoA (`alpha_glide_deg` from the
static-margin gate) marked inside for a non-sep body glider; a separating RV
is band-only.  **Turbulent flank (~3–5×) and control-fin gap interference
(Alviani 2022, 10–80× at reattachment) are flags, not computed** — screening
cannot place the transition or reattachment line; Murray & Russell 2002
(MASCC) is the named computed-value upgrade.  The verdict role is gated by
`heating.WINDWARD_DRIVES_VERDICT` (default **off**, a context overlay; when on
it downgrades survive→degraded past the body soak limit at the gentlest α, or
flags needs-analysis past the peak limit — never a hard fail, since the nose
remains the primary hard-fail driver and the AoA/transition uncertainty
forbids false precision).  Source pack and inference labels: `BENCHMARKING.md`
"Windward/AoA heating probe"; pinned by `test_windward_flank.py`.

**Design decision — cones and flat-bottom lifting bodies use different
windward physics.**  The windward acreage flux is `BODY_FLUX_FRACTION ×
q̇_stag(R_body) × A(α)`, and the fraction `0.13` is a **cone** quantity: it is
the cone tail-to-stagnation ratio (Lu/Shi & Zhang 2024; STS-1 consistent).  A
**cone flank** wraps the flow around the body and genuinely heats at that
fraction of the stagnation flux.  A **flat-bottom lifting body** (`body_form`
= `wedge` / `half_cone`) does not: its windward surface at incidence is a
flat-plate boundary layer, which runs **~7× cooler** relative to its
blunt-scale stagnation than a cone flank does.  These are different flow
regimes, so **one acreage fraction cannot serve both forms.**  The decision
keeps `0.13` for its **validated cone domain**; critically, `0.13` is
**not** lowered to fit the flat case — that would corrupt the cone domain to
match the wedge, the compensating-error pattern the whole anchoring
discipline exists to prevent (cf. the retired Ref-(4) blunt-cone chart, §8.8,
where a wrong pressure term had been absorbable into a tuned `Cf`).

**Implemented (2026-07-30): the fraction is selected by `body_form`.**
`windward_flank_flux` uses `BODY_FLUX_FRACTION_FLAT = 0.018` for
`wedge`/`half_cone` (flat side windward — the half-cone's windward acreage is
its flat plane) and `BODY_FLUX_FRACTION = 0.13` for bodies of revolution;
`trajectory.py` forwards the reentry object's `body_form`.  0.018 is the
Candler-implied flat-surface value — a **single-point anchor** at the
generic-HGV glide point, stated as such on the output and in the
survivability report (an explicit `body_flux_fraction` argument still
overrides both).  With it, the windward screen lands on the CFD plateau
(closure pinned by `test_candler_windward_anchor.py`; the naive cone-fraction
over-prediction remains pinned alongside as the domain-boundary record).

**CFD anchor and its limit (Candler & Leyva 2022, S&GS 30).**  Their US.3D
CFD of a generic HGV — flight-validated to ~100 K against Shuttle
thermocouples — at exactly our use case (6 km/s, 49.7 km, ε=0.85, laminar,
non-catalytic, α = 14° = L/D_max) puts the **windward centreline plateau at
≈1150–1200 K** (their Fig. 3).  Run through `windward_flank_flux` with the
app's geometry mapping (δ = atan((D/2)/L) ≈ 7°, `R_body` = D/2), the model
returns **≈1934 K — an over-prediction of ×1.65 in temperature, ×7 in flux**.
The cause is structural and specific: `BODY_FLUX_FRACTION = 0.13` is a **cone
tail/stagnation ratio**, and a **flat-bottom** lifting body's windward
surface runs ~7× cooler relative to its blunt-scale stagnation than a cone
flank does (the effective fraction Candler implies is ≈0.018).  The bias is
**conservative** (screening-safe — it over-flags, never under-flags) and does
**not** touch the constant's validated cone domain, so `0.13` is unchanged.
It does mean the windward screen **over-predicts the new `body_form` wedge /
half-cone lifting bodies**; a body-form-aware acreage fraction is future work
(the ≈0.018 flat-surface target is recorded).  The anchor numbers are pinned
by `test_candler_windward_anchor.py` so any future fix is a deliberate,
measured change — not silent drift.  (`R_body` cannot explain the gap:
`T ∝ R_body^−1⁄₈`, so closing it that way needs a ~24 m curvature scale.)

### 13.9 Adjustable screening thresholds (`thresholds.py`)

The survivability screen rests on a small set of **benchmark numbers**: the
UHTC demonstrated dwell floor, the operational and flight-demonstrated MaRV
g-ceilings, the **ablator demonstrated-load records** (graphite / bare
carbon-carbon from Reentry-F, PICA from Stardust, carbon-phenolic from the
Pioneer Venus Large Probe — the ablator analogue of the UHTC dwell floor;
§13.6), and the two model-conservatism knobs (the
body-acreage flux fraction and the windward AoA band).  (The `δ/R_n`
shape-change / severe-blunting / glider-tip numbers were retired from the
dialog when the ablator verdict moved from a computed recession to a
load-vs-record comparison — §13.6; they survive as the cited δ ladder inside
the report's accuracy warning text, not as tier-driving thresholds.)  These
are the numbers a **policy-focused modeler** is most likely to
want to move — a new flight extends how long an object is *demonstrated* to
glide, or how hard a MaRV is *demonstrated* to pull — so Thrusty makes exactly
this set editable (Analysis ▸ Screening Envelope…, `ScreeningEnvelopeDialog`)
and leaves the material catalog and per-vehicle anchor datasets for a future
spreadsheet project.  The set is curated **by user story**, not by where each
number lives in code: `thresholds.REGISTRY` pulls each one from wherever its
consumer reads it (a module scalar such as `SHAPE_CHANGE_ONSET`, or a material
field such as `TPS_MATERIALS['uhtc']['oxidation_dwell_s']`).

Two disciplines are structural.  **Shipped defaults are frozen:** the registry
holds each default plus its citation of record; a user edit lives only in an
overlay file (`benchmark_overrides.json`, `thresholds.load/save`), and
`thresholds.reset()` (the dialog's *Restore All Defaults*) discards it.
`thresholds.apply()` is the single writer that pushes the effective values into
the live modules — including the two windward kwarg defaults
(`body_flux_fraction`, `alpha_band_deg`), which resolve from their module
attributes **at call time** so a change actually reaches them.
`test_thresholds.py` pins the registry defaults to the live constants (a drift
guard) and covers the overlay round-trip and the apply/reset paths.  **Modified
benchmarks self-disclose:** `thresholds.modified()` lists every overridden
number, and `build_report` stamps the headline with an asterisk and prints a
*Modified benchmarks* block naming each changed value, its shipped default, and
the default's source — so a hand-edited number never rides on the shipped
numbers' citations.

### 13.10 Interior (bondline) survivability screen (`heating.bondline_screen`)

Every other screen answers "does the *skin* survive."  The bondline screen adds
the axis a policy reader actually cares about — **does the structure behind the
TPS survive** — because a vehicle whose skin holds while its interior cooks is a
failed weapon that looks like a survivor from the outside.

The method is Dec & Braun's approximate TPS-sizing option (NTRS 20060004824),
reduced to screening tier: **1-D transient conduction** through the body TPS
layer (implicit finite-difference, Thomas-solved), a **radiative surface energy
balance** `α·q̇ = εσT_s⁴ + q_cond` (radiation linearized about the previous
step), and an **insulated back face** (their worst case — no heat leaves the
structure).  The flux driving it is the same body-acreage flux the body
location sees (`f × body-scale stagnation`).  The peak bondline temperature over
the arc is compared against the **TPS-structure design limit** (`BONDLINE_LIMIT_C`,
default **250 °C** — the ablative-TPS sizing criterion; editable in the Screening
Envelope dialog).  Crossing it maps to **BEYOND DESIGN ENVELOPE (yellow)** — a
design-sizing limit, not a demonstrated-death bound — so it escalates
survive→beyond and **never to red**.

Every simplification is in the conservative (hotter-bondline) direction, and
labeled: no pyrolysis-gas energy absorption (Dec & Braun quantify this as ~11%
conservative on required insulation), no ablation heat consumption at the
surface (the wall is modelled inert — hotter than a real ablator), and
carbon-phenolic uses its **char** conductivity (higher than virgin → faster
inward conduction).  The one non-conservative omission — no recession thinning
of the layer — is flagged when the body TPS thickness is unset (screened at a
2 cm default).

Honesty gate: the screen evaluates **only for an ablative body with a cited
through-thickness conductivity** — carbon phenolic (char k ≈ 1.5 W/m·K, Cabrera
& West 2026 Table A4 / Sutton) and silica phenolic (virgin k ≈ 0.35 W/m·K,
Handbook of Materials Science via Finke; char k uncited, so near-limit margins
are flagged soft).  PICA, SIRCA, and the metals/hot-structures return
"bondline not evaluated" rather than a guessed number — the same discipline as
the ablator load records.  Method + conservatism validation: Dec & Braun
reproduce CMA within ~11% in-depth (BENCHMARKING "Method-stack validation");
`test_bondline.py` pins the four physical regimes (thick/short safe,
thin/long cooks, steady-state bound, uncited-declines) and the report
escalation.

### 13.11 Boundary-layer transition gate (`heating.transition_factor`)

The acreage/flank boundary layer runs laminar high in the atmosphere and trips
turbulent as the vehicle descends into denser air; turbulent acreage heating
runs 3–5× the laminar value.  Thrusty places transition **in the trajectory
(when), not on the body (where)** — a screening gate on the freestream Reynolds
number based on nose radius, **Re_Rₙ = ρ·V·R_n / μ(T_∞)** (Sutherland
viscosity).  Below the onset threshold the flow is laminar (factor 1); across
[onset, fully-turbulent] the turbulent flux ratio ramps in, computed from how
far past onset the flow is and **clamped to the cited 3–5× band** (St_lam ∝
Re^−½, St_turb ∝ Re^−⅕ → the ratio grows with Re).  The per-sample factor
multiplies the laminar flank flux (`windward_flank_flux`) and the bondline
acreage flux (§13.10) before their peaks, so augmentation applies exactly where
on the arc it occurs.  The **nose stagnation point is always laminar and is
untouched** — transition is a downstream/acreage phenomenon.

The two thresholds are **calibrated and verified against Kuntz 1999
(AIAA 99-3460) Table 1** — the IRV-2 CFD case, which tabulates the flow state at
every trajectory point.  The freestream-Re criterion reproduces it: onset at
Re_Rₙ ≈ 2×10⁶ brackets pt15 laminar (1.72×10⁶) / pt16 transitional (2.07×10⁶);
fully-turbulent at ≈ 3.5×10⁶ brackets pt19 transitional (3.32×10⁶) / pt20
turbulent (3.89×10⁶).  The *spatial* criterion (local Re_x) is deliberately not
used: it is not single-valued in the data (~10⁷ on the cone vs ~10⁶ at the
sphere-cone juncture — the reason the source needed two separate correlations),
whereas the nose-radius Reynolds onset is the classic nosetip-transition scaling
(PANT lineage) and captures the *when* a screen needs.  Both thresholds are
editable in the Screening Envelope dialog (`re_rn_transition_onset`,
`re_rn_fully_turbulent`); `test_transition.py` pins the Kuntz reproduction.

**Standing caveat — transition placement is genuinely unreliable, and flight
data says so.**  Williamson (Sandia, AIAA 92-3989, read from primary, PDF in
`data/`) compares two standard engineering criteria — the G.E. Low Mass
Addition (GELMA) criterion and the NASP Re_θ = 150·M_e rule — against Sandia
ballistic flight data and finds *"the predictions are not good … clearly
indicative of our inability to predict transition"* (Figs. 28–29).  His Fig. 27
shows laminar and turbulent local conditions **overlapping heavily in the same
(Re_θ, M_e) region**, i.e. identical conditions producing either state, and
photodiode data on a maneuvering vehicle (Fig. 26) show the flow *"jumped back
and forth between laminar and turbulent."*  He also notes transition visibly
shifting the flight-derived C_mα, C_Nα and static margin (Figs. 22–24).
Thrusty's gate is calibrated to a **single** CFD case (Kuntz IRV-2) and returns
a single sharp onset; the honest reading is that it places transition to
within a band that flight data does not resolve, and that the 3–5× turbulent
augmentation is the load-bearing output, not the exact instant.  This is why
the gate feeds a *screening* flux multiplier and never a hard verdict.

**The sharpest counter-example is SWERVE — the vehicle class Thrusty models.**
Iliff & Shafer (NASA Dryden, AIAA 93-0311, read from primary; PDF in the Drive
library, not the repo)
report the third SWERVE flight — a 5.25° ablating slender cone, i.e. almost
exactly a Thrusty reentry object — and find the boundary layer was
**turbulent at Mach 12 and laminar at Mach 8** (their words: *"Surprisingly,
the flight data exhibited a turbulent boundary layer at Mach 12 and a laminar
boundary layer at Mach 8"*).  Their Fig. 23 shows the flight temperature
tracking the *turbulent* prediction early and falling toward the *laminar*
one later; Fig. 24 shows that when the vehicle changed attitude the windward
ray went laminar→turbulent while the leeward ray went turbulent→laminar; and
Fig. 25 shows laminar and turbulent flight points **overlapping in the same
(Re_s, M_e) region**, with the GELMA criterion line failing to separate them.

This is a direct falsification of the *monotonic* assumption our gate makes:
Re_Rₙ rises as the vehicle descends, so the gate can only ever go
laminar → transitional → turbulent, never back.  A real ablating, maneuvering
cone did the reverse — plausibly because ablation blowing stabilises the
boundary layer and nosetip shape change alters the entropy layer, neither of
which the gate models.  Read the gate accordingly: it is a **conservative
screening switch for when turbulent-level acreage heating is credible**, not a
prediction of the boundary-layer state at a given instant.  For an ablating
vehicle the state may reverse, and for a maneuvering one it differs
windward-to-leeward at the same instant.

This upgrades the former static *"turbulent flank ~3–5×"* warning into a
computed, trajectory-resolved factor.  Because transition is a low-altitude
phenomenon, it is correctly dormant for high-altitude HGV cruise (Re_Rₙ stays
below onset — C-HGB/HTV-2 flanks read laminar) and active for the fast,
low-altitude ballistic acreage (a Mk21-class terminal bondline sees turbulent
augmentation) — leaving the shipped fleet's verdicts unchanged only because
their margins are large, not because the gate is inert.

### 13.12 Survival map (`survivability_report._survival_map`)

Between the plain-language lead and the "Full analysis" divider, the report
prints a one-glance **station × question matrix** — the hinge into the detail
and its table of contents.  Rows are stations in the order the heat visits
them (outside-in, front-to-back: **nose → body skin → windward flank →
interior**); columns are the three ladder questions every material answers
(**surface holds? / endures the duration? / within the flown record?**).
Presentation choices, each deliberate:

* **One number per cell** — the single figure the cell's tier was decided on
  (a load fraction, a dwell vs its floor, a bondline temperature vs its
  limit).  The matrix says *where to look*; the full analysis below says what
  happened.  Cells are colorized in the GUI with the §13.5 tier colors.
* **Cell roster follows the material's failure axes.**  An ablator answers
  surface (burn-through bound) and record (load vs the family flight record)
  but has no separate duration question; a UHTC nose maps its coverage
  verdict onto all three (P→A boundary / dwell vs floor / coverage fraction);
  a reradiative skin answers surface (peak T_eq vs limit) and duration (soak
  dwell, or the heat-sink melt budget when that is the crossed criterion).
* **"—" is one glyph for two things** — physically-N/A and
  not-computed-at-screening-tier; the full analysis carries the distinction.
  Rows with no populated cell are dropped (a ballistic RV's map is shorter
  than a MaRV's).  The windward row appears only when the windward criterion
  is computed (non-ablator body) — for an ablator body T_eq is not the
  failure axis and the flux-only estimate stays in the Form C block.
* **The Regime line is prose, not cells** — the transition-gate state
  (§13.11) and validity guards (e.g. radiative gas heating past ~9 km/s)
  answer none of the three questions, so forcing them into cells would be
  false symmetry.

`test_survival_map.py` pins the placement, the per-material cell logic, and
that every colorization span lands exactly on its cell text.

### 13.13 Radiative gas heating (`heating.radiative_flux`)

Above roughly 9 km/s the shock layer itself becomes an important radiator, and
a convective-only screen understates the environment.  Thrusty computes the
stagnation-point radiative flux with the **Tauber & Sutton 1991** Earth/air
correlation (*JSR* 28(1):40–42, read from primary; PDF in the Drive library,
not the repo):

> q̇_r = C · R_n^a · ρ^b · f_E(V)  [W/cm²],  C = 4.736×10⁴, b = 1.22,
> a = 1.072×10⁶ · V^−1.88 · ρ^−0.325 (capped: a ≤ 0.6 for 1 ≤ R_n ≤ 2 m,
> a ≤ 0.5 for 2 < R_n ≤ 3 m, a ≤ 1 always), with f_E(V) the paper's Table 1
> (9–16 km/s, linear interpolation).

The result is **added to the Sutton-Graves convective flux** to form the total
surface flux that drives peak T_eq and the reradiative surface criteria, and
its peak plus the radiative fraction are disclosed in the report warnings.
This retires the former *"convective-only model; radiative gas heating NOT
assessed"* caveat.

**Nothing in the shipped fleet moves.**  The correlation is defined only at and
above 9 km/s and returns exactly zero below it, so ballistic RVs (~7 km/s) and
HGVs (~5–6 km/s) are numerically untouched — pinned by
`test_radiative.py::test_shipped_fleet_flux_unchanged_by_radiative`.  Radiative
heating matters for the capsule-class anchors (Stardust 12.9 km/s, Hayabusa
12.2 km/s) and for any max-energy or lunar-return case a user constructs.

**Epistemic status — an upper bound, deliberately.**  The correlation assumes
thermochemical *equilibrium* and a cold wall, and was fitted for blunt bodies
(R_n 0.3–3 m).  Small, fast, high-altitude probes fly with a chemically
nonequilibrium, optically thin shock layer that radiates *less*, so the
correlation over-predicts there.  Verified: against Stardust's flight-derived
radiative fraction (~9 % of peak rate; Kontinos & Stackpoole AIAA 2008-1197)
the correlation returns ~23 % of total — a **2.6× over-prediction**, correctly
flagged as extrapolated (R_n 0.20 m is below the 0.3 m floor).  The validity
envelope is checked at the peak-radiative sample and the report says when the
correlation is being extrapolated.  The test pins the *direction*: a future
retune may not silently flip it to under-prediction.

**Basis discipline — the record ladder stays convective.**  The ablator
load-vs-flight-record comparison and the burn-through bound (§13.6) integrate
the **convective** flux only.  Every demonstrated-load record and every H_eff
in the catalog was derived on a convective basis, and Thrusty's own Stardust
reconstruction closes at 1.00× of its record on that basis.  Folding the
over-predicted equilibrium radiative term into that integral pushed the
*recovered* Stardust capsule to 1.26× its own record — a false "beyond the
flight record" verdict.  Radiative heating therefore raises T_eq and the
reported peak flux, and is disclosed, but does not enter the record ladder.
Guarded by `test_radiative.py::test_record_ladder_stays_on_the_convective_basis`.

**Verification of the correlation family.**  The companion Venus paper
(Tauber, Palmer & Prabhu, NTRS 20120001655) publishes both CFD values *and*
its own fitted-equation values for the Pioneer Venus Large Probe, so our
coding of that correlation family is checked against published numbers at both
ends — no digitization anywhere.  We reproduce its Eq. (2) column to within
0.4 % at all ten tabulated points.

**Bonus corroboration of the carbon-phenolic record.**  Integrating the
radiative pulse that this independent NASA team computed for the Pioneer Venus
Large Probe gives ≈ 46 MJ/m² of *radiative* load over the tabulated window,
against the ≈ 60 MJ/m² *total* load record Thrusty carries for carbon phenolic
(Cabrera & West 2026, who describe the pulse as radiation-heavy).  Two
independent reconstructions of the same flight agreeing at that level firms up
what had been the weakest of the three ablator records.

### 13.14 Arc descriptors: retiring Form C (`survivability_report.descriptors`)

The report originally sorted every vehicle into one of three **Forms**, keyed
automatically from the reentry plan.  Two of those were real; the third was a
category error, and it is now retired.

**What was real.**  Ballistic RVs and gliders are judged by genuinely
different models — the ablator load-vs-record / accuracy ladder (§13.6) versus
the stopwatch of survival-time against glide-time (§13.5, NRC duration
ladder).  That single fork survives as `classify()`, which now returns
`'ballistic'` or `'glide'` and nothing else.

**What was not.**  "Form C — Maneuvering (MaRV)" was triggered by
`glider_terminal_alt_km > 0 or glider_dive_target_radius_km > 0` — that is, by
a commanded **terminal dive**.  Diving is not maneuvering, and the mismatch
ran in both directions:

* **False negatives.**  SWERVE — a lifting body that flew at −10° AoA and was
  rated to 10 g, i.e. the one vehicle in the shipped library whose flight
  record *is* an AoA-maneuver demonstration — commands no terminal dive, so it
  classified as a plain glider and was denied both the windward-flank heating
  block (§13.8) and the maneuver-load anchors (§13.7): the two blocks most
  specifically about what it did.  In fact **no shipped vehicle ever reached
  Form C**: the C-HGB, AHW and generic maneuvering body plans set `glider_terminal_dive =
  True` with `glider_terminal_alt_km = 0.0`, which the integrator reads as
  *glide to impact*, not as a dive.  Both blocks were effectively dead code
  for the whole shipped library.
* **False positives.**  A plan carrying a dive altitude and an *empty* bank
  schedule was announced in the headline as "Form C (maneuvering (MaRV))" — an
  assertion about vehicle behaviour that the plan did not carry.

**The fix is structural, not cosmetic.**  Each block now hangs on its own
trigger, and each headline descriptor is earned by its own fact:

| Report element | Trigger (the fact it actually depends on) |
|---|---|
| ballistic vs glide judgement model | `profile['glider']` |
| windward-flank heating block | windward numbers present in the FOM |
| terminal-dive transient block | `terminal_alt_km > 0` or `dive_target_radius_km > 0` |
| maneuver-load anchor block | `pullup_g_max > 0` |
| `banking` descriptor | a non-empty `glider_bank_schedule` |

`descriptors()` returns the headline phrase from those same facts —
`ballistic RV`, or `glide` joined with whichever of `banking`, `terminal
dive`, `dive-at-target` the plan carries.  A vehicle that banks but never
dives now reads *glide · banking*; one that dives without banking is no longer
called maneuvering.  The Form letter is gone from the headline entirely.

This changes **which blocks print**, never a survival tier: all five blocks
were and remain presentation or context, with the single documented exception
of the windward overlay behind `heating.WINDWARD_DRIVES_VERDICT` (§13.8,
default off).  `test_arc_descriptors.py` pins each trigger independently, the
SWERVE regression, and the tier-invariance; `test_gui_survivability.py` pins
the same triggers as *rendered in the tab*, plus the tier tag, the survival
map's pixel tab stops and colorization spans, and the ballistic-only
sweep-context gate (`thrusty.py`) — the sole consumer of the report's `form`
outside `survivability_report.py`.

**Running the GUI test.** It needs a real Tk, and skips cleanly without one.
On a desktop install `pytest test_gui_survivability.py` just works.  In a
container whose default interpreter was built without Tk, point pytest at one
that has it and give it a virtual display:

```
xvfb-run -a /usr/bin/python3.12 -m pytest test_gui_survivability.py -q
```

Note for readers of the ledger: `BENCHMARKING.md` still files its source
campaigns under the historical "Form A/B/C" headings.  Those are the names the
citation campaigns were run under and are left intact as a provenance record —
Form A ↦ ballistic, Form B ↦ glide, Form C ↦ the maneuver/AoA source pack.

### 13.15 Location-based heating, engineering tier (`heating_locations.py`)

Sections 13.1–13.14 scale every heating number from one quantity, the
cold-wall stagnation flux at the nose. That is adequate for a blunt nose and
wrong elsewhere: the SHEFEX II sharp tip came out at 4,394 K, hotter than the
air heating it. `heating_locations.py` replaces that with one closed-form
relation per *location* and a wall energy balance. **It is not yet wired into
the verdicts; nothing in 13.1–13.14 has changed.**

A vehicle is a list of locations, not a shape category. A capsule has a nose
cap; a cone has a nose cap and a flank; a glider or space plane has a nose
cap, leading edges and a windward face.

All relations are from Tauber, NASA TP-2914 (1989), read from primary, in SI
(kg/m³, m/s, m, K) giving W/m². Each carries its own hot-wall term.

| Location | Relation | Tauber |
|---|---|---|
| Nose cap | q = 1.83×10⁻⁴ (ρ/r_n)^½ V³ (1 − h_w/H_s) | Eq. 40 |
| Swept cylinder | q = 1.29×10⁻⁴ (ρ/r)^½ (1 − 0.18 sin²Λ) V³ (1 − h_w/h_aw) cos Λ | Eq. 41 |
| Wing leading edge | q = (q_cyl² + q_FP² sin²Λ)^½ cos α | Eq. 49 |
| Windward face, laminar | q = C (ρ cos δ / x)^½ V^3.2 sin δ (1 − h_w/h_aw); C = 2.42×10⁻⁵ plate, 4.03×10⁻⁵ cone | Eqs. 48, 46 |
| Windward face, turbulent, V ≤ 3960 m/s | q = 3.72×10⁻⁴ (ρ sin²δ cos^2.22 δ)^0.8 (x − x_bt)^−0.2 (T_w/555)^−¼ V^3.37 (0.9 − h_w/H_e) | Eq. 56a |
| Windward face, turbulent, V > 3960 m/s | q = 2.45×10⁻⁵ (ρ sin²δ cos^2.62 δ)^0.8 (x − x_bt)^−0.2 V^3.7 (0.9 − h_w/H_e) | Eq. 56b |
| Turbulent cone | 1.15 × the plate value | Eq. 59 |

H_s = H_e = h_∞ + V²/2. For the laminar face h_aw = h_∞ + 0.40 V²; for the
swept cylinder h_aw = h_∞ + 0.5 V² (1 − 0.18 sin²Λ). Λ is sweepback, δ the
angle between surface and free stream, x the distance back along the surface,
x_bt where transition begins. Tauber states ±15% for Eq. 56 above 1500 m/s.
The nose-cap constant becomes 1.90 if the measured rather than the Newtonian
velocity gradient is used (Tauber p. 7); the code keeps 1.83 and offers 1.90
as the upper edge of a band.

**Wall energy balance.** For a thin, insulated, radiating skin the wall
temperature solves q(T_w) + q_extra = ε σ T_w⁴, where q_extra is any heating
independent of wall temperature (hot-gas radiation, §13.13). Because the
hot-wall term drives q to zero as h_w approaches the recovery enthalpy, the
wall cannot come out hotter than the gas.

**Wall enthalpy.** h_w = c_p T_w with c_p = γR/(γ−1) = 1004.7 J/(kg K), from
the constants `atmosphere.py` already uses. Real air stores more energy once
vibration and dissociation set in, so this understates h_w and overstates
flux and temperature. A cited gas model can be substituted through the
`wall_enthalpy` argument.

**Accuracy against named cases.** Recorded in `heating_locations.ACCURACY` and
recomputed by `test_heating_locations.py`. Figures are computed ÷ reference − 1.

| Location | Case | Flux | Temperature |
|---|---|---|---|
| Nose cap | FIRE II 1636 s, flight total | +22% | +5% |
| Nose cap | FIRE II 1643 s, flight total | +18% | +4% |
| Nose cap | FIRE II 1651 s, flight total | −2% | −1% |
| Nose cap | Stardust 51 s, detailed computation | −29% | −8% |
| Sharp solid tip | SHEFEX II arc-jet | — | +69% |
| Windward face, laminar, flat-plate value | STS-3 belly, flight | −25% | −7% |
| Windward face, laminar, cone value | STS-3 belly, flight | +26% | +6% |
| Windward face, turbulent, flat-plate value | STS-3 belly, flight | +18% | +4% |
| Swept cylinder, laminar | 15 wind-tunnel cases, sweep 60° and 66.5° | +6% | +1% |
| Unswept cylinder | 3 wind-tunnel cases | −2% | 0% |
| Swept cylinder, laminar | 6 CUBRC runs, tunnel density tabulated | +10% | +2% |
| Attachment line, laminar (Poll) | same 6 runs | −7% | −2% |
| Attachment line, turbulent (Poll) | 6 tripped CUBRC runs | −26% | −7% |
| Attachment line, laminar (Poll) | Bushnell, Mach 8, 4 runs | −1% | 0% |
| Attachment line, turbulent (Poll) | Bushnell, Mach 8, 9 runs | −14% | −4% |
| Swept cylinder, laminar | Bushnell, Mach 8, 4 runs | +14% | +3% |
| Nose cap | 8 wind-tunnel spheres | +3% | +1% |
| Nose cap | DLR H2K sphere, two runs | −4%, −5% | −1% |
| Wing leading edge (Eq. 49) | none yet | | |

The STS-3 figures are means over mid-body stations (x/L 0.194–0.592 at five
laminar flight points from 7.40 to 3.44 km/s; x/L 0.255–0.795 at one turbulent
point, 2.21 km/s), with the surface angle taken as the angle of attack and the
measured wall temperature in the hot-wall term, so no emissivity is assumed.
**Flight lies between the flat-plate and cone values at 28 of 30 laminar
stations.** A flat plate is two-dimensional; a cone sheds its boundary layer
all round; a body of finite width does something in between. The windward
face is therefore reported as the pair, not as the flat-plate value alone.

The wind-tunnel cases are from Zhou et al. 2023, Table 1: measured Stanton
numbers in cold air at 1.0–2.7 km/s, stated uncertainty 5–10%. They test the
swept-cylinder relation, Eq. 41, the main term of the leading-edge relation;
14 of the 15 swept cases are within 20%. Eq. 49 itself, with its flat-plate
term and angle of attack, has no test case. The table gives unit Reynolds
number, not density; density is recovered with Sutherland's law. The power law
printed in that paper (its Eq. 4) must not be used for this: at the 46–142 K
of these tunnels it overstates viscosity by up to half, and with it every case
reads about 15% low. Sutherland's law is within 4% of the viscosity implied by
the DLR tunnel's own pressure, temperature and Reynolds number.

Six of those swept-cylinder cases are Holden & Kolly's (AIAA 95-2279), whose
Tables 5 and 7 tabulate the tunnel density for every run. With that density
and no viscosity law, Eq. 41 is +3% to +20% on the six laminar runs, and
Sutherland's law recovers the tabulated density to within 8%.

**Attachment line of a swept edge, laminar and turbulent
(`attachment_line_flux`, Poll 1981).** Tauber gives no relation for a
turbulent edge, and on six tripped, turbulent runs of Holden & Kolly the
measured heating is 1.5 to 2.3 times what the laminar Eq. 41 gives. Poll's
relations cover both states. The free stream is split into a component normal
to the edge, which is brought to rest, and one along it, V_e = V sin Λ, which
passes the bow shock unchanged:

| Quantity | Relation | Poll |
|---|---|---|
| Edge temperature | T_e = T_∞ (1 + (γ−1)/2 · M_n²), M_n = M cos Λ | Eq. 18c |
| Edge pressure | pitot pressure at M_n | Eq. 18c |
| Velocity gradient | dU/dx = (2/D) [2 (p_e/ρ_e)(1 − p_∞/p_e)]^½ | Eq. 18b |
| Length scale, Reynolds number | η = (ν_e / (dU/dx))^½, R̄ = V_e η / ν_e | Eqs. 1, 2 |
| Laminar | St_e = 0.571 / (Pr^⅔ R̄) | Eq. 11 |
| Turbulent | St_e = 0.0345 Pr^−⅔ (T_e/T*)^0.79 (μ(T*)/μ(T_e))^0.21 R̄^−0.42 | Eq. 14 |
| Reference temperature | T* = T_e + 0.10 (T_w − T_e) + 0.60 (T_r − T_e) | Eq. 15 |
| Viscosity | μ = 1.488×10⁻⁶ T^1.5 / (T + 122.1 × 10^(−5/T)) (Keyes) | p. 307 |

with St_e = h / (c_p ρ_e V_e), γ = 1.4, Pr = 0.7. Poll found that for
*laminar* flow the edge temperature is itself the best reference temperature,
so the laminar relation carries no T*. (Holden & Kolly apply a reference
temperature to the laminar relation too; evaluated that way it reads 24% low
on their own smooth runs, against +1% to −7% evaluated Poll's way.)

The paper was transcribed by three independent readers using different
methods and the results reconciled; every equation above was read identically
by all three, and the implementation reproduces the limits Poll prints
(velocity-gradient parameter 1.07, density ratio 6.44, T*/T_e = 0.90 +
0.53 tan²Λ). Three things Poll leaves to the reader are settled as follows:

- *Heat flux.* q = h (T_r − T_w). Poll never writes it, but plots his data
  against (T_r − T_w).
- *Recovery factor.* 0.89 for turbulent flow (Poll, p. 307). Poll gives none
  for laminar flow; 0.82 is used, from Tauber's Eq. 41.
- *Edge conditions.* Eqs. 18b and 18c are printed for the hypersonic case and
  are used here at any Mach number; where the normal Mach number is below one
  the pressure rise is isentropic.

Stated accuracy: laminar, within +7% / −14% of exact similar solutions in skin
friction, sweep 0–70°; turbulent, fitted to 84 measurements at Mach 2.4–8,
sweep 10–78°, wall at 0.4–1 of stagnation temperature, RMS error 7.1%, maximum
19%. Measured against the Holden & Kolly runs, which lie outside that range
(Mach 10–12, wall at about 0.25):

| Runs | Relation | Flux | Temperature |
|---|---|---|---|
| 6 smooth, laminar | Poll laminar | −7% (−12% to −2%) | −2% |
| 6 smooth, laminar | Tauber Eq. 41 | +10% (+3% to +20%) | +2% |
| 6 tripped, turbulent | Poll turbulent | −26% (−38% to −20%) | −7% |
| 6 tripped, turbulent | Tauber Eq. 41 (laminar) | −52% (−67% to −42%) | — |

Inside the fitted range, Bushnell's Mach 8 runs (NASA TN D-3094; a 1 in.
cylinder alone at 45° and 60° sweep, wall at 0.42 of stagnation temperature;
values read from his Figs. 16(b) and 17(b), stated accuracy 15%):

| Runs | Relation | Flux | Temperature |
|---|---|---|---|
| 4 laminar | Poll laminar | −1% (−4% to 0%) | 0% |
| 4 laminar | Tauber Eq. 41 | +14% (+10% to +19%) | +3% |
| 9 turbulent | Poll turbulent | −14% (−22% to −5%) | −4% |

So the CUBRC shortfall belongs to running the relation outside its range,
not to its transcription. Laminar runs lie below Poll's critical R̄* of about
245 and turbulent runs above it. Caveats: the free-stream density is
recovered from Bushnell's diameter Reynolds number with Sutherland's law (with
Keyes' law every figure rises by 4–6 points); the static temperature is taken
as isentropic from the stagnation temperature; and whether Bushnell's runs
are among the 84 Poll fitted has not been checked.

Holden & Kolly say of the same comparison that their turbulent measurements
are "greater than the predicted levels, particularly for the boundary layers
tripped by the 0.030-inch roughness", and attribute it to a heating overshoot
downstream of the trips. At zero sweep Poll's laminar relation and Tauber's
Eq. 41 agree within 5% from 3 to 6 km/s.

Poll's relations are perfect-gas ones. At flight speeds the edge temperature
they compute is far above what real air reaches; the heat flux depends on the
enthalpy difference and is much less affected, but no flight case tests it.

**When the edge turns turbulent.** `attachment_line_state` returns R̄ and
R̄* (R̄ with properties at T*). Holden & Kolly report turbulence at R̄* above
300–500 where a wing root or roughness disturbs the flow (Poll's earlier
figure: 245) and above 600–800 on a smooth edge, equivalent to a free-stream
Reynolds number of about 8×10⁵ on edge diameter (their conclusions print
8×10⁶; the abstract and §3.4.3 say 8×10⁵). Poll's paper gives no number. The
six tripped runs have R̄* of 279–490 as computed here. No gate is applied in
the code: the caller chooses the state.

The H2K runs are from Park et al. 2021, which gives the tunnel's static
pressure directly and evaluates Tauber's relation itself: 9.2 and 9.6 W/cm²,
which `stagnation_point_flux` reproduces. **In cold air the relations are
within a few percent. The shortfalls below are confined to high-enthalpy
flight.**

The FIRE II totals add Tauber-Sutton radiative heating. FIRE II measured flux,
not wall temperature, so its temperature column is the fourth-root equivalent
of the flux error. Convective heating alone is 18–24% below fully catalytic
computation at all three FIRE II points and 29% below it for Stardust; the
targets (temperature within 3–5%, flux within 15–20%) are therefore met on
FIRE II, met on the STS-3 turbulent point, and not yet met on Stardust or on
the STS-3 laminar face, where either edge of the band is 6–7% out in
temperature.

**Not modelled.**

- *Conduction into solid parts.* A sharp solid tip is not a radiating skin;
  the wall balance overstates its temperature by about two-thirds. §13.16
  covers solid conical tips.
- *Low-density flow.* Tauber Fig. 8: neglecting wall slip overpredicts
  stagnation heating by 130% at a Knudsen number of 0.1.
- *Surface chemistry.* The relations assume a fully catalytic wall.
- *Blunt-nose entropy layer.* Close behind a blunt nose the windward heating
  is higher than these relations give (Tauber & Adelman 1987).
- *Shock interaction, gaps, steps, roughness.*

**Two Tauber papers, two leading-edge forms.** Tauber & Adelman 1987
(AIAA-87-1514, Eq. 15) print q_LE = ½ (q₀² cos²Λ + q_FP² sin²Λ)^½ cos α, built
on the sphere stagnation value q₀; TP-2914 Eq. 49 builds on the swept cylinder
of Eq. 41. They differ by up to about 40% on the cylinder term. The code
follows TP-2914, whose cylinder-to-sphere ratio (1.29/1.83 = 0.705) matches the
theoretical 1/√2. The 1987 appendix also prints the laminar plate constant as
2.53×10⁻⁵ where TP-2914 has 2.42×10⁻⁵; the turbulent relations agree.

Sources: Tauber 1989 (NASA TP-2914); Tauber & Adelman 1987 (AIAA-87-1514);
Throckmorton, Hamilton & Zoby 1982 (NASA TM 84500); Zhou et al. 2023 (AIAA
Journal 61(3)); Holden & Kolly 1995 (AIAA 95-2279); Poll 1981 (Aeronautical
Quarterly 32); Park et al. 2021 (Acta Astronautica 187); Hash et al. 2007 (AIAA 2007-605); Liu et
al. 2008 (AIAA 2008-1213); Trumble et al. 2010 (JSR 47(5)); Böhrk et al. 2012
(AIAA 2012-5919). See `data/REFERENCES.md`.

### 13.16 Conduction in a solid conical tip (`heating_solid.py`)

A sharp, solid tip sheds the heat arriving at its point by conducting it back
into the body, where the much larger flank radiates it away. The radiating-wall
balance of §13.15 has no such path and overstates the tip temperature badly.
For solid parts only, `heating_solid.cone_tip_response` solves transient
conduction along the axis of the cone:

    ρ c A(s) ∂T/∂t = ∂/∂s ( k A(s) ∂T/∂s ) + P(s) [ q_conv(s, T) − ε σ T⁴ ]

with s the distance along the axis from the virtual apex, A = π (s tan δ)² the
cross-section, P = 2π s tan δ / cos δ the lateral surface per unit axial
length, and δ the half angle. Temperature is uniform over each cross-section.
**Not yet wired into the verdicts.**

| Term | Source |
|---|---|
| Tip cap heating | Tauber Eq. 40 × the cap's projected area: a flux falling as the cosine of the body angle (TP-2914 §2.5) integrates over a spherical cap to the stagnation flux times π (r_n cos δ)² |
| Flank heating | Tauber Eq. 46, laminar sharp cone, capped at the stagnation value |
| Hot-wall terms | as in §13.15 |
| Base | adiabatic; over tens of seconds heat diffuses √(αt) ≈ 2–3 cm and does not reach it |

Finite volumes along the axis, fine at the tip and growing geometrically;
conduction implicit, surface terms linearised. The scheme conserves energy to
rounding error, and the result at the SHEFEX II thermocouple station changes by
under 0.1% when the mesh or the time step is refined.

**Accuracy against named cases** (`heating_solid.ACCURACY`, recomputed by
`test_heating_solid.py`; absolute temperature, computed ÷ measured − 1):

| Case | Model | Measured | Error |
|---|---|---|---|
| SHEFEX II flight, thermocouple 20 mm behind the tip | 1178 K | 848 °C = 1121 K | +5% |
| SHEFEX II arc-jet, same thermocouple | 1487 K | 1179 °C = 1452 K | +2% |
| Radiating-wall balance at the tip, for comparison | 3100–3200 K | — | — |

The tip itself was not measured. In the arc-jet this model gives 2110 K there,
against 1908 K from the authors' own two-dimensional heat-balance code.

Caveats on those figures:

- *Flight path.* The paper states the two ends of the 52 s experiment window;
  the path between them is rebuilt with speed linear in time and a constant
  flight-path angle, on the US Standard Atmosphere 1976.
- *Geometry.* The half angle, 16.1°, is that of the cone with the stated mass
  (680 g), density and length (160 mm). SHEFEX II's tip is an octagonal pyramid.
- *Conductivity.* Table 1 prints 17 and 8 beside an exponent that is unreadable
  in the copy read; 17 and 8 W/(m K) is the physically possible reading. The
  axial value, 17, is used; using 8 moves the thermocouple by under 3%.
- *Arc-jet enthalpy.* The case is treated as the paper's authors treated it, as
  flight at the tunnel's density, speed and static temperature. With the
  tunnel's full 11.9 MJ/kg the thermocouple comes out about 24% high; the
  difference is chemical energy in the dissociated stream that a ceramic wall
  does not recover.
- *Low-density flow* at the top of the flight window is not corrected for
  (§13.15).

Source: Böhrk et al. 2012 (AIAA 2012-5919).

---

## 14. Outputs, events, and milestones

Every `integrate_trajectory()` call returns a single dictionary capturing
the full state-time history plus a chronological list of milestones, plus
ancillary data products (debris arcs from spent stages, orbital elements
for vehicles that achieve orbit, commanded pitch / azimuth time series).
The GUI consumes this dictionary to populate the on-screen plots and the
event timeline; the Excel, KML, CSV, Folium, and Cartopy exports all
read from the same structure.

### 14.1 The trajectory dictionary

The canonical return structure (`trajectory.py`):

| Key | Type | Meaning |
|---|---|---|
| `t` | array | Time array (s) |
| `lat`, `lon`, `alt` | arrays | Geodetic latitude (deg), longitude (deg), altitude (m) |
| `speed` | array | Airspeed (ECEF-frame, m/s) — used for drag and heating |
| `inertial_speed` | array | Inertial speed (ECI-frame, m/s) — used for orbital queries |
| `accel` | array | Acceleration magnitude (m/s²) |
| `mass` | array | Vehicle mass time history (kg) |
| `range` | array | Cumulative great-circle range from launch (km) |
| `pos_ecef`, `vel_ecef` | (N,3) arrays | Full ECEF state |
| `orbital` | bool | True if the vehicle achieved bound orbit (no impact) |
| `impact_lat`, `impact_lon`, `range_km` | scalars | Final impact point and total range (None if `orbital`) |
| `apogee_km`, `apogee_lat_deg`, `apogee_lon_deg` | scalars | Apogee summary |
| `time_of_flight_s`, `impact_speed_ms` | scalars | Mission summary |
| `milestones` | list of dicts | Chronological flight events (Section 14.2) |
| `debris_trajectories` | list | Spent-stage and shroud debris arcs (Section 14.3) |
| `orbital_elements` | dict | Six-element Keplerian set, if orbital |
| `pitch_cmd_deg`, `az_cmd_deg` | arrays | Commanded guidance time histories |

Distinguishing airspeed (ECEF) from inertial speed (ECI) explicitly in
two columns turns out to matter in practice — orbital-insertion checks
need ECI for energy and `√(μ/r)` comparisons, while drag and heating
need ECEF because the atmosphere co-rotates with Earth (Section 13.1).
Both are exposed rather than forcing the caller to convert.

### 14.2 Milestone catalogue

Milestones are inserted chronologically into the `milestones` list by
`_insert_chrono()` (`trajectory.py`). Each milestone is a dict with
`{t_s, alt_km, range_km, mass_t, speed_ms, event}` populated by
interpolation onto the trajectory array (`_interp_milestone`,
`trajectory.py`). The exhaustive set of event labels currently
emitted:

| Phase | Event |
|---|---|
| Boost | Stage `N` ignition / Stage `N` empty body — in orbit / Stage `N` empty impact |
| Boost | Fairing jettison / Fairing released at separation / Fairing retained / Fairing impact |
| Boost | Booster casing impact (strap-on, after separation) |
| Boost / coast | Apogee (`{alt} km`) |
| Coast | Perigee (`{alt} km`) — for orbital trajectories |
| Coast | Yaw segment start / Yaw segment end (azimuth before → after) |
| Coast | Burnout (each stage's natural exhaustion or commanded cutoff) |
| Glide entry | Re-entry (100 km) — pierce-altitude descent crossing |
| Glide | Pull-up start (`{alt} km`) — Acton mode Phase 4 entry |
| Glide | Glide start (`{alt} km`) — equilibrium-glide handoff (Tracy / Acton) |
| Glide | → Equilibrium glide (`{alt} km`) — skip-to-equilibrium handoff |
| Glide | Skip *N* pull-up (`{alt} km`) — Nth phugoid trough |
| Glide | Skip *N* apex (`{alt} km`) — Nth phugoid crest |
| Glide | Peak heating (`{q̇} MW/m², T_eq ≈ {T} K`) — Section 13 |
| Glide | Max-G (`{n} g`) — peak structural load factor |
| Terminal | Terminal dive (`{alt} km`) — start of inverted dive |
| Terminal | Re-entry query (`{alt} km`) — user-set diagnostic altitude crossing |
| End | Orbital insertion (`{a_km} km × {e}`) — for orbital final stages |
| End | Impact (`{mass} kg`) — final ground impact |

The `Re-entry query` event is a user-controllable diagnostic: setting
`reentry_query_alt_km` causes the integrator to emit a milestone at the
descending crossing of that altitude with the full state at that
instant. Useful for comparing computed vs. published "100 km re-entry
velocity" or "30 km terminal velocity" claims.

### 14.3 Debris arcs

After staging or shroud jettison, each spent body continues on a
ballistic arc until impact, computed with a tumbling-cylinder ballistic
coefficient (`tumbling_cylinder_beta`, `booster_models.py`). This
gives a more realistic descent than treating the spent body as a point
mass:

```
A_end   = π · D² / 4                          [end-on cross-section]
A_side  = D · L                               [broadside cross-section]
A_eff   = (A_end + A_side) / 2                [arithmetic mean]
β_tumble = m / (C_D · A_eff)                  [kg/m²]
```

The arithmetic mean of end-on and broadside projected areas
approximates the time-averaged area for a cylinder tumbling in the
pitch plane. `C_D = 1.0` (the function's default) is representative of
bluff-body turbulent flow ([Hoerner 1965](#16-references)). The function
returns 0 if either length or diameter is zero, so missiles without a
configured shroud or spent-body geometry simply have no debris arcs
computed. The same function has a **two-orientation hypersonic form**
(`cd=None`, each orientation with its own Hoerner Ch. XVIII coefficient)
used for a reentering body flagged `tumbling` (§8.11); debris arcs keep
the legacy single-`C_D = 1.0` mean-area form above.

Whether the **last** stage sheds a debris body is the run-level separation
decision (§6.4): a separating run tumbles the casing; a non-separating (`body`)
run keeps it fused as the reentering vehicle, so no last-stage arc is emitted.
The casing mass for that arc is the stage's burnout mass
(`mass_initial − mass_propellant`) minus the reentry object's mass — so a
warhead carried inside the stage's mass budget is stripped from the casing
rather than double-counted. (Non-last stages always shed their full
`mass_final`.)

Spent bodies that re-enter compute their own impact point and add a
"Stage N empty impact" or "Fairing impact" or "Booster casing impact"
event to the master milestone list. The full debris-arc time-series is
also stored in `debris_trajectories` for plotting on the same map as
the primary trajectory. Stages that reach orbit are flagged with
"Stage N empty body — in orbit" instead of an impact.

### 14.4 Export formats

Five export targets are exposed through the GUI's File and Cartopy
menus:

| Format | Trigger | Contents |
|---|---|---|
| **KML** | File → Export Trajectory KML | Primary trajectory polyline + milestone markers + debris arcs, opened in Google Earth |
| **CSV** | Save sweep / save scenario buttons | Range vs. burnout-angle sweep tables; per-scenario parameter dumps |
| **Folium HTML** | Cartopy → Open Folium Map | Interactive web map with all trajectories, milestones, and impact ellipses; opens in browser |
| **Cartopy PNG** | Cartopy → Export Cartopy Map | High-resolution flat or globe projection map, publication-ready |
| **Excel XLSX** | File → Save Missile to XLSX | Full missile parameter set in a structured workbook (see Section 14.5) |

The KML output uses a fixed colour scheme — primary trajectory red,
debris arcs grey, impact points white — and embeds altitude as the third
KML coordinate so the trajectory renders three-dimensionally in Google
Earth. Milestone markers are placed at their interpolated lat/lon and
labelled with the event string from Section 14.2.

### 14.5 Excel missile import/export

`booster_xlsx.py` provides a 2-way bridge between the in-memory
`BoosterParams` tree and an Excel workbook. Each stage gets its own
worksheet with parameters labelled in the first column and values in
the second; the top sheet holds vehicle-level parameters (name, base
diameter, total stages, glider settings, RV selection). The
`export_booster_xlsx(path, params)` and `import_booster_xlsx(path)`
functions round-trip cleanly — a parameter set exported to XLSX and
re-imported produces an identical `BoosterParams` object.

This is the *recommended* mechanism for sharing missile definitions with
collaborators who don't run Python: an analyst can edit cells in Excel
and re-import without touching the codebase. The JSON save format
(`booster_to_dict` / `booster_from_dict`) is the lower-level alternative,
preferred for version control because text diffs are readable.

### 14.6 Auxiliary GUI dialogs

Three secondary dialogs supplement the main trajectory view:

- **FootprintDialog** (`thrusty.py`). Sweeps the bank-angle schedule
  for an HGV across a range of cross-range maneuvers and computes the
  envelope of reachable terminal points. Output: an impact-zone polygon
  rendered on the map.
- **RangeRingDialog** (`thrusty.py`). Draws great-circle range
  rings at user-specified distances from the launch site or any other
  reference point. Useful for visualising the launch vehicle's
  performance envelope against named geographic features.
- **Thrust estimator**. Given mass-at-liftoff and an observed time to
  reach a sighted altitude milestone (e.g. "the missile crossed 30 km at
  t = 35 s"), the estimator back-computes the average thrust and Isp
  consistent with the observation. This is a forensic / OSINT tool for
  reconstructing motor parameters from telemetry-deprived launch
  observations.

---

## 15. Validation and built-in missile definitions

Thrusty ships with a `pytest` regression suite (the `test_*.py` files in
the repository) covering the aerodynamics, mass/staging, guidance, glide,
heating, schematic, and reentry-body models. On top of that, validation
against reality is performed by reproducing published trajectory parameters
from the open arms-control literature and confirming that the simulator's
output matches the published flight profiles within the modelling fidelity
of a 3-DOF point-mass code.

The twelve builder functions in `booster_models.py` represent the
qualitative validation set. Each is documented in code comments with
its source citation, parameter table, and any reproduction-specific
notes. Only two are registered in the runtime `BOOSTER_DB` and exposed
in the GUI's "Missile" dropdown at startup; the others are available
as builder functions and can be added to `custom_boosters.json` for
runtime registration by users who want them visible.

### 15.1 Forden Table 1 — the four reference vehicles

The four missiles from [Forden 2007](#16-references) Table 1 are
implemented as builder functions `_scud_b`, `_al_hussein`, `_nodong`,
`_taepodong_i` (`booster_models.py–1071`). Each carries the exact
mass, Isp, burn time, diameter, and payload values from Forden Table 1
in its source comment:

| Builder | Dry (kg) | Fueled (kg) | Isp (s) | Burn (s) | Dia (m) | Payload (kg) |
|---|---:|---:|---:|---:|---:|---:|
| `_scud_b` | 1 198 | 4 897 | 230 | 75 | 0.84 | 1 000 |
| `_al_hussein` | 1 334 | 6 073 | 230 | 90 | 0.84 | 191 |
| `_nodong` | 3 900 | 19 900 | 240 | 70 | 0.88 | 1 000 |
| `_taepodong_i` | (stage 1 = Nodong body) | | | | | 454 |

The thrust values are derived from these by the rocket identity
`T = I_sp · g₀ · m_p / t_b` (Section 7.1) so they match Forden's
implied thrust to within rounding. Running each missile with Forden's
documented launch elevation and pitch program reproduces the apogee
and range from Forden's Table 1 to within a few percent — the residual
being attributable to the difference between Forden's Cd table
treatment and Thrusty's decomposed wave + friction + base model
(Section 8).

These four missiles are attributable to **Forden (2007)**, not to
Thrusty's authors — they are reproductions of the published reference
cases, included to anchor the simulator's behaviour against an
independent published benchmark.

### 15.2 Extended literature missiles

Six additional builder functions extend the Forden reference set to
cover later vehicles documented in the open literature:

| Builder | Class | Primary source |
|---|---|---|
| `_shahab3` | Shahab-3 (Iranian Nodong derivative) | Open-source literature |
| `_generic_icbm` | Generic three-stage ICBM | Forden-style template |
| `_taepodong_ii` | Taepodong-II / Unha SLV | Forden 2007 discussion |
| `_zoljanah` | Zoljanah SLV (Iran) | Open-source launch reporting |
| `_zoljanah_slv` | Zoljanah configured as SLV | Same vehicle, SLV mode |
| `_minotaur_4_htv2` | Minotaur-IV Lite + HTV-2 glider | [Wright 2015](#16-references) Table 2 |

The `_minotaur_4_htv2` builder is the most heavily documented (and most
carefully validated) of these, because it serves as the test case for
the HGV machinery of Section 12. The booster parameters come from
Wright's [Science & Global Security 2015](#16-references) Table 2
(originally sourced from the Orbital ATK Minotaur-IV User's Guide), and
the glider parameters come from [Acton 2015](#16-references) Table 3
with `glider_beta_entry_kg_m2 = 7.0` set for the Acton-mode β_S
direct-re-entry segment (Section 12.3.2).

These vehicles also draw on parameters from the published literature;
they are *reconstructions* in the same sense as the Forden missiles,
not original work by Thrusty's authors.

### 15.3 AUR — Lewis original

The `_aur` builder (`booster_models.py`) and its variant
`_aur_hgb` (`booster_models.py`) are an original Thrusty
contribution by the author of this document. AUR is a hypothetical
two-stage solid-propellant ballistic missile assembled from
open-source body-dimension and propulsion-class data; it is *not* a
reconstruction of a specific named vehicle from the literature. To
fly it as a boost-glide vehicle, the AUR carries a hypersonic glide
body (a reentry object with the constant-L/D guidance modes of
Section 12) in place of a conventional warhead — chosen at run time
from the sidebar, since the front-end loadout is a run-level choice and
no longer a separate booster variant.

The AUR booster is registered in the runtime `BOOSTER_DB` as `"AUR"`,
alongside the Minotaur-IV + HTV-2 reproduction. (A former `"AUR+HGB"`
variant that baked the glide body into the booster JSON was removed once
loadout became a run-level choice.)

### 15.4 Reproducibility caveats

The qualitative validation against Forden 2007 and Wright 2015 should
not be over-interpreted. What is established:

- The basic 3-DOF integrator produces the same apogee and range from
  the same propulsion and aerodynamic parameters as the published
  source, within the limits of the decomposed-drag model.
- The HGV trajectory machinery (Section 12) reproduces the Tracy &
  Wright 2020 equilibrium-glide ansatz and the Acton 2015 three-phase
  formulation to the level documented in the source papers.

What is *not* established:

- Thrusty has not been compared against actual flight-test telemetry
  for any of the modelled vehicles, because that telemetry is not
  publicly available for any of them.
- The decomposed-drag model (wave + friction + base, Section 8) has
  not been validated against wind-tunnel data for full-vehicle
  configurations; each piece has been validated against its primary
  source (Chin 1961, NACA TN 4201, Crowell 1996) but the full assembly
  has not been independently calibrated.
- The Schilling SLV performance method (§11) has been calibrated
  against historical launch records by Schilling himself; Thrusty
  inherits that calibration without adding its own.

The intended use case — preliminary trajectory analysis for arms-control
verification and threat modelling — is well served by this level of
validation. Use cases that require higher confidence (vehicle thermal
design, terminal-guidance algorithm development, propellant load
optimisation) should use higher-fidelity tools.

---

## 16. References

> **Draft status note.** Specific equation, section, and figure
> numbers for Chin (1961) appearing in Section 8 are taken from
> source-code docstrings; they have not been independently re-verified
> against the PDF in the current editing environment. Citations to
> Tracy & Wright 2020, Acton 2015, Schilling 2009, Sutton & Graves
> 1971, Forden 2007, Anderson 2006, and the NACA reports are verified
> to publication level. Readers preparing the document for publication
> should spot-check the Chin equation numbers before quoting.

### Primary aerodynamics and propulsion

- **Chin, S. S.** (1961). *Missile Configuration Design.*
  McGraw-Hill, New York. Source for cone wave drag (Eqs. 3-4 / 3-6),
  tangent ogive wave drag (Eq. 3-9 / Miles formula), Blasius laminar
  Cf (Eq. 4-1), Schoenherr turbulent Cf (Eq. 4-2), Frankl-Voishel
  compressibility correction (Eq. 4-6), and base pressure coefficient
  (Fig. 3-15). Used throughout Section 8.

- **NACA TN 4201**: Stoney, W. E. Jr. (1958). *Collection of Zero-Lift
  Drag Data on Bodies of Revolution from Free-Flight Investigations.*
  NACA Technical Note 4201. Source for the Von Kármán, LV-Haack /
  Sears-Haack, and parabolic wave-drag comparison data (Section
  8.2.3); also the bluntness extension to r/R ≈ 0.4 (Fig. 7, Section
  8.2.5).

- **Crowell, G. A.** (1996). *The Descriptive Geometry of Nose Cones.*
  Self-published. Source for wetted-area formulas for the five
  implemented nose shapes (Section 8.3.6).

- **Shafer, J. I.** (1959). "Solid Rocket Propulsion," Chapter 16 in
  *Space Technology*, ed. Howard S. Seifert. Wiley, New York. Source
  for the solid-motor grain profile catalogue and fill-factor ranges
  (Section 7.3).

- **Hoerner, S. F.** (1965). *Fluid-Dynamic Drag.* Self-published,
  Bricktown, NJ. Source for the tumbling-cylinder drag coefficient
  used in debris arc calculations (Section 14.3), and — Ch. XVIII
  (hypersonic bluff bodies) — for the two-orientation reentry-body
  tumbling β (Section 8.11): impact-pressure coefficient
  `C_p• = 1.84 − 0.76/M²` (eq. 41), cross-flow cylinder `C_D = ⅔·C_p•`
  (eq. 44, Fig. 24), and blunt cylinder face `C_D = 0.89·C_p•` (Fig. 22),
  with continuum cross-flow anchors from §3-5/§3-6 (Figs. 12/28).

### Atmosphere

- **Picone, J. M., Hedin, A. E., Drob, D. P., & Aikin, A. C.** (2002).
  "NRLMSISE-00 empirical model of the atmosphere: Statistical
  comparisons and scientific issues." *Journal of Geophysical
  Research: Space Physics* 107(A12): 1468. The default upper-atmosphere
  model, accessed via the `pymsis` Python package (Section 4.1).

- **U.S. Standard Atmosphere 1976.** NOAA / NASA / USAF, Washington
  DC, NOAA-S/T 76-1562 (1976). Fallback atmosphere model, used when
  `pymsis` is unavailable or selected explicitly via
  `configure_atmosphere(model='std1976')` (Section 4.2).

### Trajectory and guidance

- **Forden, G.** (2007). "Reducing a Common Danger: Improving Russia's
  Early-Warning System." *Cato Policy Analysis* No. 399 (and the
  associated MATLAB tool that Thrusty was originally a Python port of).
  Source for the four reference vehicles (Section 15.1) and for the
  basic pitch-program guidance convention (Section 9.1).

- **Wheelon, A. D.** (1959). "Free Flight of a Ballistic Missile."
  *ARS Journal* 29: 915–926. Source for the optimal-burnout-angle
  formula `γ_opt = ½·arccos(Q/(2−Q))` (Section 10.2).

- **NASA SP-8099** (1972). *Combining Ascent Loads.* NASA Space Vehicle
  Design Criteria (Structures) monograph. Source for the boost q·α
  combined-load metric and the α envelope (Section 9.6): the 5°–10°
  angle-of-attack-at-max-q preliminary-design condition and hard-over
  engine bound (§2.1.2.2, p. 12), the range-safety dogleg case study in
  which the large-α steering + aero load became the design combined-load
  condition (p. 13), and the relative-magnitude table putting steering /
  pitch-command loads at 0.05–0.15 of the wind bending moment (p. 10).

- **Fresconi, F., Gruenwald, B., Yucelen, T., & Sahu, J.** (2017).
  *Adaptive Missile Flight Control for Complex Aerodynamic Phenomena.*
  US Army Research Laboratory, ARL-TR-8085. Corroborating source for the
  α-induced boost aero (Section 9.6): the high-maneuvering aerodynamic
  model with a sin²α cross-flow axial-force term and sinα + sin³α normal-
  force terms (its Eq. 3), which the Jorgensen cross-flow build-up used
  here reduces to. Its 6-DOF phenomena (phantom-yaw side forces,
  canard–fin vortex coupling, α-dependent roll) are explicitly out of
  scope for the 3-DOF screening model.

- **Kim, Y., Kim, B. S., & Park, J.** (2013). "Aerodynamic pitch control
  design for reversal of missile's flight direction." *Proc. IMechE Part
  G: J. Aerospace Engineering* 227(9): 1523–1532. Corroborating source
  for the α energy cost (Section 9.6): the induced-drag polar
  `C_D = C_D0 + k·C_L²` and the observation that an extreme-α (180°)
  reversal is only flyable because dynamic pressure collapses (velocity
  to ~10 m/s) — the same q-dependence behind the constant-q·α envelope.
  Its fin-effectiveness dead zone (35° < α < 130°) is a control-authority
  limit specific to fin-steered airframes, not gimballed boosters.

- **Delorme, D., Desmariaux, J., Carpentier, B., & Espinosa, A.** (2013).
  "Day-of-launch wind biasing trajectory optimization impact on launch
  vehicles pre-dimensioning methodologies." *5th European Conference for
  Aerospace Sciences (EUCASS)*, CNES Launchers Directorate. Source for
  the q·α load framing (Section 9.6): states q·α as "the main driver of
  the lateral loads applied to the structure of the launch vehicle during
  atmospheric flight," and validates that a simplified "phase-1" q·α
  estimate matches full 6-DOF within ~5% (slightly conservative) — the
  fidelity warrant for a screening q·α limit. Its controllability
  criterion (K1 control efficiency vs A6 aerodynamic instability) uses
  the same inputs (thrust, lever arm, inertia, q, S, C_Nα, CP–CoM arm).

- **Payload user's guides** (lateral load-factor cross-check, Section
  9.6): START-1 *Space Launch System User's Handbook Vol. I* (2002),
  Table 4-1 — 1st-stage lateral 0.7 g; Cyclone-4 User's Guide §5.5 Tables
  20–21 — 1st-stage lateral 0.3–0.6 g; Orbital/Northrop *Minotaur I*
  (TM-14025) and *Minotaur IV/V/VI* (TM-17589) — steady-state lateral
  < 0.5 g (large CLA transient laterals are structural-dynamics response,
  out of scope for a 3-DOF tool); Pegasus User's Guide Fig. 4-3 — the
  −2.33 g aerodynamic pull-up is a winged-lift load, the air-launch
  analogue relevant to the parked air-launch work (TODO.md).

- **Tsiolkovsky, K. E.** (1903). *Issledovanie mirovykh prostranstv
  reaktivnymi priborami* [Exploration of Outer Space by Reaction
  Devices]. The rocket equation, used for the stack ΔV pre-estimate
  (Section 10.1) and as the basis for the Schilling SLV
  performance method (Section 11.1).

- **Vincenty, T.** (1975). "Direct and Inverse Solutions of Geodesics
  on the Ellipsoid with Application of Nested Equations." *Survey
  Review* 23(176): 88–93. The Vincenty inverse formula used for
  surface distance (Section 2.3).

### SLV performance

- **Schilling, J. R.** (2009). *Estimating the Performance of
  Hypothetical Foreign Space-Launch Vehicles.* International
  Assessment and Strategy Center, working paper. The empirical ΔV
  penalty formulation and `K_3`, `K_4` calibration (Section 11.1).

### Mass estimation

The dry-mass estimator (Section 6.6) draws on a larger source set; the
principal references are listed here, with the full collection (including the
underlying Heineman / MacConochie–Klich / Glatt lineage) in
[`MASS_ESTIMATOR.md`](MASS_ESTIMATOR.md).

- **Akin, D. L.** (2016). *Mass Estimating Relations*, ENAE 791, U. Maryland.
  The primary SI component-level MER set (tanks, engines, thrust structure,
  avionics, wiring) — the "Wilhite-school" relations of Section 6.6.1.
- **Rohrschneider, R. R.** (2002; AIAA 2001-4542). *MER Database for Launch
  Vehicle Conceptual Design*, Georgia Tech / SSDL. Cross-validation of the
  structure/skirt/thrust-structure forms.
- **Hutchinson, V. L. & Olds, J. R.** (2004). *Estimation of Launch Vehicle
  Propellant Tank Structural Weight* (GT-STRESS), AIAA 2004-3661. Basis for the
  physics-based tank option (Section 6.6.1).
- **Zandbergen, B. T. C.** (2015, 6th EUCASS). Pump-fed engine mass/size
  regression — the engine-MER cross-check.
- **Zandbergen, B. T. C.** (2026, TU Delft). *Simple Parametric Relations for
  Solid Rocket Stage Inert Mass Estimation* — the headline solid whole-stage
  estimate (Section 6.6.2).
- **Pietrobon, S. S.** (2009). *Analysis of Propellant Tank Masses* — hydrolox
  aggregate stage-mass law and the Al-Li tank factor.
- **Shu, J.-I., et al.** (2020). *Multistage Liquid Rocket Weight Estimation…*,
  J. Aerospace Eng. 33(6) — the engine-mass-ratio aggregate (κ_E).
- **Goldyn, P., et al.** (2025). *Preliminary Design of Expendable and Reusable
  Mixed-Staged Launch Vehicles*, J. Spacecraft & Rockets — the structural-index
  feasibility ceiling.
- **Northrop Grumman Propulsion Products Catalog** (Jan 2023). Per-motor data for
  the best-in-class solid inert-mass fit (Section 6.6.2).

### Hypersonic glide vehicles

- **Tracy, C. L. & Wright, D.** (2020). "Modeling the Performance of
  Hypersonic Boost-Glide Missiles." *Science & Global Security* 28(3):
  135–170. The equilibrium-glide ansatz `L·cos σ = m·(g − v²/r)`
  (Eq. 7), the 3D EOM with bank-to-turn (Eqs. 1–6), and the inverted-
  dive terminal phase (Section 12.3.1, 12.4, 12.5).
  Available at: https://scienceandglobalsecurity.org/archive/sgs28tracy.pdf

- **Acton, J. M.** (2015). "Hypersonic Boost-Glide Weapons." *Science
  & Global Security* 23(3): 191–219. The three-phase pull-up
  formulation, the ρ/β invariant (Eq. 8), the isothermal scale-height
  and sea-level density fits, and the small-angle circular-arc
  bridging solution (Eqs. 18 / 21). Pierce altitude 100 km
  (Section 12.1, 12.3.2).
  Available at: https://scienceandglobalsecurity.org/archive/sgs23acton.pdf

- **Wright, D.** (2015). "Analysis of the Boost Phase of the HTV-2
  Hypersonic Glider Tests." *Science & Global Security* 23(3):
  220–229. Source for the Minotaur-IV booster stage parameters in
  `_minotaur_4_htv2` (Section 15.2).

- **Lu, P., Forbes, S. & Baldwin, M.** (2013). "Gliding Guidance of High
  L/D Hypersonic Vehicles." AIAA 2013-4648. The altitude-rate feedback
  damping law (Eq. 33), the velocity-scheduled gain (Eq. 34), and the
  command flight-path angle γ\* (Eq. 31) for the `damped_glide` mode
  (Section 12.3.5).

- **Yu, W. & Chen, W.** (2011). "Guidance Scheme for Glide Range
  Maximization of a Hypersonic Vehicle." AIAA 2011-6714. The
  flight-path-angle feedback (Eq. 19) and the empirical gain / heating /
  range sweep corroborating the `damped_glide` gain magnitude
  (Section 12.3.5).

- **Liu, Z., Hu, Y., Gao, C., Jing, W. & Ji, X.** (2025). "Modeling and analysis
  of maneuver laws based on higher-order multi-resolution dynamic mode
  decomposition for hypersonic glide vehicles." *Defence Technology* 48, 34–47.
  Data-driven (DMD) decomposition of HGV skip-glide; independently measures the
  skip phugoid frequency (0.0207–0.0374 rad/s), corroborating the first-
  principles ω_p = √(g_eff/H_ρ) (Section 12.3.5).

- **Chapman, D. R.** (1958/1959). *An Approximate Analytical Method for Studying
  Entry Into Planetary Atmospheres.* NACA TN 4276 / NASA TR R-11. The **primary**
  second-order nonlinear entry ODE (Eq. 21, in the density-like variable `Z(ū)`,
  `ū = V/V_circ`); the equilibrium-glide `Z_II` truncation attributed to Sänger;
  and the lift-driven transition from non-oscillatory glide to "numerous skips of
  sizable intensity" (Fig. 6) — the phugoid, shown numerically. The §12.3.5
  oscillator is the small-perturbation linearisation of this ODE about
  equilibrium glide. (Pages 14, 15, 21, 22, 24, 25 read and verified.)

- **Vinh, N. X., Busemann, A. & Culp, R. D.** (1980). *Hypersonic and Planetary
  Entry Flight Mechanics.* University of Michigan Press. Ch. 10 (Yaroshevskii's
  theory) gives the second-order nonlinear entry ODE (Eq. 10-55) — a special case
  of Chapman's Eq. 21 — and its equilibrium-glide reference state (Eq. 10-61, the
  Sänger condition), and shows the oscillation about equilibrium glide numerically
  (Fig. 10-10). (Vinh §7-2 / §7-5 are the first-order steady-glide and skip
  solutions and contain no oscillator; the perturbation oscillation lives in the
  Ch. 10 second-order theory. Pages 158-162 and 172-176 read and verified.)

### Control theory

- **Ogata, K.** (2010). *Modern Control Engineering*, 5th ed. Prentice
  Hall. §5-3 "Second-Order Systems": standard form, max-overshoot
  Eq. (5-21), the desirable damping-ratio band ζ = 0.4–0.8 (p. 171), and
  the settling-time minimum near ζ = 0.68–0.76 (p. 173). Source for the
  `damped_glide` ζ ≈ 0.7 default (Section 12.3.5).

- **Franklin, G. F., Powell, J. D. & Emami-Naeini, A.** (2019). *Feedback
  Control of Dynamic Systems*, 8th ed. (Global). Pearson. §3.4.2
  "Overshoot and Peak Time": overshoot Eq. (3.72) and Fig. 3.24, which
  lists ζ = 0.7 → 5 % overshoot as a "frequently used value." Source for
  the `damped_glide` ζ ≈ 0.7 default (Section 12.3.5).

### Stagnation heating

- **Sutton, K. & Graves, R. A.** (1971). *A General Stagnation-Point
  Convective-Heating Equation for Arbitrary Gas Mixtures.* NASA
  Technical Report R-376. The stagnation heat-flux correlation
  `q̇ = K·√(ρ/R_N)·V³` with `K = 1.7415×10⁻⁴` for Earth (Section 13.1).

- **Anderson, J. D.** (2006). *Hypersonic and High-Temperature Gas
  Dynamics*, 2nd ed. AIAA Education Series. Reference for the
  emissivity default `ε = 0.85` (§18.8, p. 781, HERMES example,
  Section 13.2).

- **Williams, S. D. & Curry, D. M.** (1992). *Thermal Protection
  Materials: Thermophysical Property Data.* NASA Reference Publication
  1289. Source for the reinforced carbon-carbon emissivity
  temperature-dependence reference (Section 13.2, 13.3).

### Earth model

- **WGS-84:** *Department of Defense World Geodetic System 1984: Its
  Definition and Relationships with Local Geodetic Systems.* NIMA
  Technical Report TR8350.2, 3rd ed. (2000). Source for `GM`, `R_E`,
  flattening `f`, J₂, and the Earth rotation rate `Ω` used throughout
  the EOM (Section 3, Section 5).

- **Terrarium terrain tiles.** *Terrain Tiles* on the AWS Open Data
  Registry (`elevation-tiles-prod`), originally produced by Mapzen — a
  global, openly licensed blend of NASA SRTM, USGS GMTED2010, NOAA
  ETOPO1, and national DEMs, PNG-encoded at 256 px Web-Mercator tiles
  (`h = 256R + G + B/256 − 32768` m). Source for both the bundled 0.05°
  coarse elevation grid and the on-demand zoom-11 lookups (Section 2.5).

- **Farr, T. G., et al. (2007).** "The Shuttle Radar Topography
  Mission." *Reviews of Geophysics* 45(2): RG2004. The ~30 m radar DEM
  underlying the Terrarium blend across ±60° latitude — the effective
  native resolution of the hi-res layer over nearly all launch and
  impact terrain of interest (Section 2.5).

### Numerical methods

- **scipy** (Virtanen et al. 2020, *Nature Methods* 17: 261–272).
  The `solve_ivp` ODE integrator with RK45 method (Section 5.6),
  `brentq` for cutoff/range root-finding (Section 10.4), and
  `minimize_scalar` for range maximisation (Section 10.3).

- **pymsis** (Lucas 2022). Python wrapper around the official NRL
  Fortran NRLMSISE-00 source, providing the atmosphere lookup
  (Section 4.1).
