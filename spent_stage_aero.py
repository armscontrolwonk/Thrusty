"""
Drag of a spent stage falling after separation (FRONT_END_DESIGN.md Part IV,
Phase 3).

A spent stage does not tumble randomly once dynamic pressure builds: it
settles to a trim set by where its centre of gravity sits against its centre
of pressure.  Whether it gets there is a dynamic question no source in hand
settles for a stage that separates inside the atmosphere, so a stage is flown
twice — trimmed, and tumbling — and the run reports one point: the end that
the stage's own swing picks when it is clear (attitude_model here,
trajectory._attitude_verdict), else the midpoint of the two impact points
(user, 2026-09-30 and 2026-10-01).

A stage that separates while still climbing is flown a third way until
apogee: tumbling end over end in the plane of its flight (Klett's
end-over-end case).  Two measured facts rule out a trim on the climb.  A
stage leaves its booster flying front-first, and near end-on the centre of
pressure of a flat-ended cylinder sits close to the leading face (Jernell,
Fig. 9), ahead of the empty centre of gravity: the attitude is statically
unstable and the stage swings away from it.  Every published envelope for
the swing that follows grows as dynamic pressure falls (Tobak & Peterson
TR R-203 eq. 33; Regan 1984 eq. 13.56; both ~ q^(-1/4)), and on a climb
dynamic pressure falls, so nothing arrests the swing before apogee.  No
source treats arrest on a climb directly, so this is an inference from
those two results; the ends of the trim-to-tumbling band are then flown
from the apogee state (2026-10-01).  Before this leg was added the band
for a stage separating at Mach 6 in dense air was 44 km wide, 41 km of it
accrued on the climb.

SOURCES
  Jernell, NASA TM X-1658 (1968): a circular cylinder flat at both ends, l/d 6,
      tested at Mach 1.50, 1.90, 2.36 and 2.86 from 0 to about 100 deg
      (data/aero/jernell_1968_flat_cylinders.csv).  Normal force "primarily
      dependent upon the magnitude of the planform area", so C_N is scaled by
      l/d from the l/d 6 body; fineness ratio has "little effect" on C_A.
      Near end-on the centre of pressure moves toward the leading face
      (Fig. 9); from about 25 deg to 90 deg it sits near mid-length.
  Klett, Sandia SC-RR-64-2141 (1964), eq. 36: random tumbling in continuum
      flow, C_D = (0.393 + 0.178 D/L)(2 - K) on area L*D, Mach 10-30; K the
      density ratio across a normal shock (perfect gas, gamma 1.4).  Eq. 32:
      end-over-end tumbling at constant rate, the same model averaged
      uniformly in angle, C_D = (0.283 + 0.303 D/L)(2 - K) on area L*D.
  Shu et al. (2020), via mass_estimator._KAPPA_E_DEFAULT: engine-to-
      structure mass ratio by stage role (lower 0.25, upper 0.12; anchors
      KSLV-II 0.252/0.177/0.094, Titan II 0.250/0.111), for a liquid stage's
      empty centre of gravity.
  Romaniw (2013), Georgia Tech dissertation, Appendix A Figs. A2-A4: solid
      motor case, insulation and nozzle mass as power laws in motor thrust
      (N), his own regressions on data he does not tabulate, plotted to
      12 MN (R^2 0.97-0.98).  Only the RATIO of the three is used, for the
      nozzle's share of a solid stage's empty mass; the absolute fits
      overshoot a small motor badly (815 kg against AUR stage 1's 454 kg)
      and are not used (user, 2026-10-01).

WHAT IS INFERRED, NOT MEASURED (each stated in the output):
  * Beyond 90 deg the flat-ended cylinder is taken as symmetric end for end:
    Jernell tested it only to about 100 deg; the data near 90 deg agree with
    symmetry, and his cone- and ogive-cylinders show the same pull of the CP
    toward a leading flat base near end-on.
  * Outside Mach 1.50-2.86 (user, 2026-09-30): below Mach 1.50 the Mach 1.50
    values are held; above Mach 2.86 the random-tumbling and end-over-end
    drags are interpolated linearly in Mach to Klett's values at Mach 10, and
    Klett's are used above that; the trimmed state is held at its Mach 2.86
    value.
  * End over end, the stage is taken to turn at a constant rate, as Klett
    does (eq. 30: the drag averaged uniformly in angle).
  * A liquid stage's empty CG: the engine, kappa/(1+kappa) of the dry mass
    (Shu et al.), at the base; the rest spread evenly along the stage.
  * A solid stage's or casing's empty CG: the nozzle, Romaniw's share of
    case + insulation + nozzle at the motor's thrust (about 28% at 0.3 MN,
    14% at 10 MN; peak thrust when the file gives one, else the average),
    at the base; case and insulation spread evenly.  A solid whose file
    gives no thrust has no CG estimate and is flown tumbling only.
  * The trim uses the centre-of-pressure curves Jernell printed (Fig. 9, Mach
    1.50 and 2.86), interpolated linearly in Mach; the values computed from
    C_m/C_N at Mach 1.90 and 2.36 are too uncertain near end-on (+-0.1).
  * A finned stage: fin forces beyond 58 deg are not in any source in hand,
    so its trim is not computed and it is reported as tumbling (user decision,
    2026-09-30: finned stages as a band only).
The real ends of a stage — an open interstage, nozzles — differ from the flat
faces tested; no source in hand covers them.
"""

from __future__ import annotations

import csv
import math
import os
from functools import lru_cache

import numpy as np

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'aero',
                     'jernell_1968_flat_cylinders.csv')
DATA_LD = 6.0                  # fineness ratio of the tabulated body
MACH_LO, MACH_HI = 1.50, 2.86  # tested range
KLETT_MACH = 10.0              # lower end of Klett's stated range
GAMMA = 1.4


@lru_cache(maxsize=1)
def _table():
    """{mach: (alpha_deg, CN, CA, xcp_over_l)} as arrays, sorted by alpha."""
    rows = {}
    with open(_DATA) as f:
        for r in csv.DictReader(line for line in f if not line.startswith('#')):
            m = float(r['mach'])
            x = r['xcp_over_l'].strip()
            rows.setdefault(m, []).append((float(r['alpha_deg']), float(r['CN']),
                                           float(r['CA']),
                                           float(x) if x else np.nan))
    out = {}
    for m, v in rows.items():
        v.sort()
        out[m] = tuple(np.array(c) for c in zip(*v))
    return out


def _bracket(mach):
    """The two tabulated Mach numbers around `mach` and the weight of the
    upper one; held at the ends of the tested range."""
    ms = sorted(_table())
    m = min(max(float(mach), ms[0]), ms[-1])
    for lo, hi in zip(ms, ms[1:]):
        if m <= hi:
            return lo, hi, (m - lo) / (hi - lo)
    return ms[-1], ms[-1], 0.0


def _coeffs(alpha_deg, mach, ld):
    """C_N (scaled to fineness ratio ld by planform area) and C_A of the
    flat-ended cylinder at alpha 0-180 deg, cross-section reference.  Beyond
    90 deg the body is taken as symmetric end for end (an inference)."""
    a = float(alpha_deg) % 360.0
    a = 360.0 - a if a > 180.0 else a
    mirror = a > 90.0
    a1 = 180.0 - a if mirror else a
    lo, hi, w = _bracket(mach)
    def at(m):
        al, cn, ca, _ = _table()[m]
        return np.interp(a1, al, cn), np.interp(a1, al, ca)
    (n0, x0), (n1, x1) = at(lo), at(hi)
    cn = (1.0 - w) * n0 + w * n1
    ca = (1.0 - w) * x0 + w * x1
    return cn * ld / DATA_LD, (-ca if mirror else ca)


def cd_at(alpha_deg, mach, ld):
    """Drag coefficient on the cross-section area at angle alpha:
    C_D = C_N sin(alpha) + C_A cos(alpha) (Jorgensen, TR R-474 eq. 2.17)."""
    cn, ca = _coeffs(alpha_deg, mach, ld)
    a = math.radians(alpha_deg)
    return cn * math.sin(a) + ca * math.cos(a)


@lru_cache(maxsize=4096)
def _random_from_data(mach, ld):
    """Average of cd_at over random orientation (weight sin alpha)."""
    th = np.linspace(0.0, math.pi / 2.0, 181)
    f = [cd_at(math.degrees(t), mach, ld) * math.sin(t) for t in th]
    return float(np.trapezoid(f, th))


@lru_cache(maxsize=4096)
def _end_over_end_from_data(mach, ld):
    """Average of cd_at over a turn at constant rate in the plane of flight
    (uniform weight in alpha; Klett eq. 30).  Symmetric end for end, so the
    quarter turn stands for the whole."""
    th = np.linspace(0.0, math.pi / 2.0, 181)
    f = [cd_at(math.degrees(t), mach, ld) for t in th]
    return float(np.trapezoid(f, th) / (math.pi / 2.0))


def _klett_2_minus_K(mach):
    """2 - K, K = [(gamma-1)M^2 + 2] / [(gamma+1)M^2] (normal shock, perfect
    gas): the modified-Newtonian pressure factor in Klett's drag equations."""
    m2 = float(mach) ** 2
    return 2.0 - ((GAMMA - 1.0) * m2 + 2.0) / ((GAMMA + 1.0) * m2)


def klett_random_cd(mach, ld):
    """Klett eq. 36 on the cross-section area: (4/pi)(0.393 l/d + 0.178)(2-K)."""
    return (4.0 / math.pi) * (0.393 * ld + 0.178) * _klett_2_minus_K(mach)


def klett_end_over_end_cd(mach, ld):
    """Klett eq. 32 on the cross-section area: (4/pi)(0.283 l/d + 0.303)(2-K)."""
    return (4.0 / math.pi) * (0.283 * ld + 0.303) * _klett_2_minus_K(mach)


def _blend_to_klett(mach, ld, from_data, klett):
    """The data value up to Mach 2.86, Klett's from Mach 10, linear in Mach
    between (user, 2026-09-30)."""
    m = float(mach)
    if m <= MACH_HI:
        return from_data(m, ld)
    if m >= KLETT_MACH:
        return klett(m, ld)
    a, b = from_data(MACH_HI, ld), klett(KLETT_MACH, ld)
    return a + (b - a) * (m - MACH_HI) / (KLETT_MACH - MACH_HI)


def klett_end_on_cd(mach, ld=None):
    """Klett eq. 22 on the cross-section area, flat face first: 0.909 (2-K)
    (the average face pressure is 0.909 of stagnation, after Stoney &
    Swanson)."""
    return 0.909 * _klett_2_minus_K(mach)


def front_first_cd(mach, ld):
    """Drag coefficient on the cross-section area flying end-on: Jernell's
    axial force at zero angle of attack, blended to Klett eq. 22."""
    return _blend_to_klett(mach, ld, lambda m, _ld: _coeffs(0.0, m, _ld)[1],
                           klett_end_on_cd)


def random_cd(mach, ld):
    """Random-tumbling drag coefficient on the cross-section area."""
    return _blend_to_klett(mach, ld, _random_from_data, klett_random_cd)


def end_over_end_cd(mach, ld):
    """Drag coefficient on the cross-section area, tumbling end over end in
    the plane of flight."""
    return _blend_to_klett(mach, ld, _end_over_end_from_data,
                           klett_end_over_end_cd)


def trim_alpha(mach, g):
    """Angle off end-on (deg) at which the measured centre of pressure meets
    a CG a fraction g of the length from the leading face, or None when the
    CP never reaches it (CG at or beyond mid-length: no preferred attitude).
    g below the CP at the smallest tabulated angle trims at end-on (0)."""
    if g >= 0.5:
        # The measured CP never passes mid-length, so such a CG meets it
        # only broadside, by symmetry: no preferred attitude (Part IV §18a).
        return None
    m = min(max(float(mach), MACH_LO), MACH_HI)
    lo, hi = MACH_LO, MACH_HI                      # Jernell Fig. 9 curves
    w = (m - lo) / (hi - lo)
    grid = np.arange(0.0, 90.0001, 0.25)
    def curve(mm):
        al, _, _, xcp = _table()[mm]
        ok = ~np.isnan(xcp)
        return np.interp(grid, al[ok], xcp[ok], left=np.nan)
    xcp = (1.0 - w) * curve(lo) + w * curve(hi)
    defined = ~np.isnan(xcp)
    if g < np.nanmin(xcp[defined][:1]):
        return 0.0
    idx = np.where(defined & (xcp >= g))[0]
    return float(grid[idx[0]]) if idx.size else None


def trim_cd(mach, ld, g):
    """(alpha_trim_deg, C_D at trim) on the cross-section area, or None.
    Held at its Mach 2.86 value above the tested range and at Mach 1.50
    below it."""
    m = min(max(float(mach), MACH_LO), MACH_HI)
    a = trim_alpha(m, g)
    if a is None:
        return None
    return a, abs(cd_at(a, m, ld))


def empty_cg_fraction(stage, dry_mass_kg, role='lower'):
    """(CG fraction of length from the FRONT of the stage, basis) for an empty
    liquid stage: the engine, kappa/(1+kappa) of the dry mass with kappa the
    engine-to-structure ratio for its role (Shu et al. 2020, via
    mass_estimator._KAPPA_E_DEFAULT: 'lower' 0.25, 'upper' 0.12), at the base;
    the rest spread evenly."""
    from mass_estimator import _KAPPA_E_DEFAULT
    k = _KAPPA_E_DEFAULT.get(role, _KAPPA_E_DEFAULT[''])
    share = k / (1.0 + k)
    f = share * 1.0 + (1.0 - share) * 0.5
    return f, (f"liquid {role} stage: engine {share:.0%} of the dry mass "
               f"(engine/structure {k:g}, Shu et al. 2020) at the base, the "
               f"rest spread evenly")


def solid_nozzle_share(thrust_N):
    """The nozzle's share of a solid motor's case + insulation + nozzle mass,
    from the ratio of Romaniw's (2013, Figs. A2-A4) fits in motor thrust (N):
    case 7e-5 T^1.2393, insulation 1e-4 T^1.1412, nozzle 0.0013 T^0.9615.
    The share falls with size because the nozzle grows nearly linearly in
    thrust and the case faster."""
    T = float(thrust_N)
    if T <= 0.0:
        return None
    case = 7e-5 * T ** 1.2393
    ins = 1e-4 * T ** 1.1412
    noz = 0.0013 * T ** 0.9615
    return noz / (case + ins + noz)


def empty_cg_fraction_solid(stage):
    """(CG fraction of length from the FRONT, basis) for an empty solid stage
    or casing: the nozzle, Romaniw's share at the motor's thrust, at the base;
    case and insulation spread evenly.  None when the file gives no thrust."""
    T = float(getattr(stage, 'thrust_peak_N', 0.0) or 0.0) or \
        float(getattr(stage, 'thrust_N', 0.0) or 0.0)
    s = solid_nozzle_share(T)
    if s is None:
        return None, ("solid stage: no thrust in its file, so no nozzle share "
                      "and no CG estimate; flown tumbling only")
    f = s * 1.0 + (1.0 - s) * 0.5
    return f, (f"solid stage: nozzle {s:.0%} of the empty mass (ratio of "
               f"Romaniw 2013 case/insulation/nozzle fits at {T/1e3:.0f} kN) "
               f"at the base, case and insulation spread evenly")


def _cp_from_leading_face(a1_deg, mach):
    """Centre of pressure as a fraction of length from the leading face at
    a1 (0-90 deg off end-on): Jernell's Fig. 9 curves (Mach 1.50 and 2.86)
    interpolated in Mach, held outside; below the smallest angle read, the
    value there (the normal force vanishes with it)."""
    m = min(max(float(mach), MACH_LO), MACH_HI)
    w = (m - MACH_LO) / (MACH_HI - MACH_LO)
    def curve(mm):
        al, _, _, xcp = _table()[mm]
        ok = ~np.isnan(xcp)
        return np.interp(a1_deg, al[ok], xcp[ok])
    return (1.0 - w) * curve(MACH_LO) + w * curve(MACH_HI)


def moment_about_cg(alpha_deg, mach, ld, f):
    """Pitching-moment coefficient about the CG on area * LENGTH, positive
    when it increases alpha.  alpha is measured from FRONT-first (0) through
    broadside to base-first (180 deg); f is the CG's fraction of the length
    from the front.  The normal force (C_N, scaled by planform) acts at the
    measured centre of pressure; the axial force acts along the axis and
    gives no moment."""
    a = float(alpha_deg)
    if a <= 90.0:
        cn, _ = _coeffs(a, mach, ld)
        return cn * (f - float(_cp_from_leading_face(a, mach)))
    a1 = 180.0 - a
    cn, _ = _coeffs(a1, mach, ld)
    return -cn * ((1.0 - f) - float(_cp_from_leading_face(a1, mach)))


def attitude_model(length_m, diameter_m, mass_kg, f):
    """What the planar swing of a spent stage needs (trajectory.
    _attitude_verdict): its transverse moment of inertia, and the measured
    moment about its CG as a function of attitude and Mach.

    The empty stage is a thin-walled cylinder carrying a point mass at the
    base (the engine or nozzle share that put the CG at f from the front:
    share = 2f - 1).  The swing is planar and undamped, as in Tobak &
    Peterson (NASA TR R-203), with the measured moment in place of their
    sine law.

    Returns a dict:
      I         kg m^2, about the CG
      SL        reference area * length, m^3
      cm(alpha_rad, mach)        moment coefficient, any angle (array)
      energy(alpha_rad, omega, q, mach)     (1/2) I omega^2 + V, J; V the
                potential of the moment, zero at front-first (its maximum)
      rotating(alpha_rad, omega, q, mach)   True where that energy is
                positive: the swing can pass front-first again
    """
    L, d, m = float(length_m), float(diameter_m), float(mass_kg)
    ld = L / d
    share = min(max(2.0 * f - 1.0, 0.0), 1.0)
    I = ((1.0 - share) * m * (L * L / 12.0 + d * d / 8.0
                              + (f - 0.5) ** 2 * L * L)
         + share * m * ((1.0 - f) * L) ** 2)
    machs = np.array(sorted(_table()))
    grid = np.arange(0.0, 180.5, 1.0)
    cm_tab = np.array([[moment_about_cg(a, mm, ld, f) for a in grid]
                       for mm in machs])
    rad = np.radians(grid)
    v_tab = -np.concatenate(
        [np.zeros((machs.size, 1)),
         np.cumsum(0.5 * (cm_tab[:, 1:] + cm_tab[:, :-1]) * np.diff(rad),
                   axis=1)], axis=1)

    def _at(tab, alpha_rad, mach, odd):
        a = np.degrees(np.asarray(alpha_rad, float)) % 360.0
        over = a > 180.0
        a = np.where(over, 360.0 - a, a)
        mm = min(max(float(mach), machs[0]), machs[-1])
        j = int(min(np.searchsorted(machs, mm, side='right') - 1,
                    machs.size - 2))
        w = (mm - machs[j]) / (machs[j + 1] - machs[j])
        y = ((1.0 - w) * np.interp(a, grid, tab[j])
             + w * np.interp(a, grid, tab[j + 1]))
        return np.where(over, -y, y) if odd else y

    SL = math.pi * d * d / 4.0 * L
    energy = lambda alpha, omega, q, mach: (
        0.5 * I * np.asarray(omega, float) ** 2
        + q * SL * _at(v_tab, alpha, mach, False))
    return dict(
        I=I, SL=SL,
        cm=lambda alpha, mach: _at(cm_tab, alpha, mach, True),
        energy=energy,
        rotating=lambda alpha, omega, q, mach: energy(alpha, omega, q, mach) > 0.0)


# Angles and reading precision for the finned-stage check: Jernell's C_N is
# read to +-0.4 (file header), too coarse a fraction of it below 15 deg.
_FIN_CHECK_ALPHA_DEG = (15.0, 20.0)
_CN_READING = 0.4


def fin_stability(stage, f):
    """Whether tail fins hold an empty stage front-first (FRONT_END_DESIGN.md
    §19f).  About the CG (f of the length from the front), the body's
    normal force acts ahead of it and overturns the stage (Jernell C_N at
    his centre of pressure); the fins' acts behind it and restores
    (glider_ld's fin slope with the N-K-P carryover, C_N = slope sin(2a)/2,
    at the fin's mid-root-chord station).  The ratio restoring/overturning
    is taken at 15 and 20 deg, Mach 1.50 and 2.86, with the body force at
    its reading, and at its reading +-0.4.

    Returns (verdict, lowest nominal ratio, highest nominal ratio):
      'stable'    restoring wins everywhere even with the body force read high
      'unstable'  overturning wins everywhere even with it read low
      'marginal'  otherwise
    or None when the fin force cannot be computed (no planar-fin dimensions).
    The fins' own mass is not in the CG."""
    import copy
    import glider_ld
    try:
        st = copy.copy(stage)
        st.stage2, st.ro = None, None
        d, L = float(st.diameter_m), float(st.length_m)
        x_fin = L - 0.5 * float(st.fin_root_chord_m or 0.0)
        slopes = {m: float(glider_ld.whole_booster_LD(st, mach=m)['c_na_fin'])
                  for m in (MACH_LO, MACH_HI)}
    except Exception:
        return None
    if min(slopes.values()) <= 0.0 or x_fin <= f * L:
        return None
    ld = L / d
    nom, pess, opt = [], [], []
    for m, slope in slopes.items():
        for a in _FIN_CHECK_ALPHA_DEG:
            cn, _ = _coeffs(a, m, ld)
            lever = (f - float(_cp_from_leading_face(a, m))) * L
            restoring = (slope * math.sin(2.0 * math.radians(a)) / 2.0
                         * (x_fin - f * L))
            dcn = _CN_READING * ld / DATA_LD
            nom.append(restoring / (cn * lever))
            pess.append(restoring / ((cn + dcn) * lever))
            opt.append(restoring / (max(cn - dcn, 1e-9) * lever))
    verdict = ('stable' if min(pess) >= 1.0 else
               'unstable' if max(opt) < 1.0 else 'marginal')
    return verdict, min(nom), max(nom)


# Mach grid on which a stage's two drag curves are tabulated once, then
# interpolated in the equations of motion: the tested points, a fine step to
# Klett's Mach 10, and on to 30 for his weak (2 - K) dependence.
_MACH_GRID = np.unique(np.r_[0.0, 1.5, 1.9, 2.36, 2.86,
                             np.arange(3.0, 10.01, 0.5),
                             np.arange(12.0, 30.01, 2.0)])


def _tabulated(f):
    """f(Mach) evaluated on _MACH_GRID and returned as a fast interpolant."""
    y = np.array([f(m) for m in _MACH_GRID])
    return lambda M, _x=_MACH_GRID, _y=y: float(np.interp(M, _x, _y))


def spent_stage_drag(stage, dry_mass_kg, role='lower'):
    """Drag of a spent cylindrical stage, as (C_D*A)(Mach) in m^2.

    Returns a dict:
      cda_random        callable Mach -> C_D*A, random tumbling
      cda_end_over_end  callable Mach -> C_D*A, tumbling end over end in the
                        plane of flight (the climb to apogee)
      cda_trim          callable Mach -> C_D*A at its trim, or None
      attitude    attitude_model(...) when there is a trim, else absent
      cda_front_first, fin_stability   a finned stage whose fins hold it
                  front-first ('stable') or may ('marginal'): C_D*A flown
                  front-first, flat-face drag plus fin drag
      leading     'front' | 'base' | None — the end that leads when trimmed
      notes       plain sentences on what was assumed
    """
    d = float(stage.diameter_m or 0.0)
    L = float(stage.length_m or 0.0) or 2.0 * d
    ld = L / d if d > 0 else DATA_LD
    area = math.pi * d * d / 4.0
    notes = []
    out = dict(cda_random=_tabulated(lambda M: random_cd(M, ld) * area),
               cda_end_over_end=_tabulated(
                   lambda M: end_over_end_cd(M, ld) * area),
               cda_trim=None, leading=None, notes=notes)
    if getattr(stage, 'has_fins', False) or getattr(stage, 'has_grid_fins', False):
        f = (empty_cg_fraction_solid(stage) if getattr(stage, 'solid_motor', False)
             else empty_cg_fraction(stage, dry_mass_kg, role))[0]
        stab = fin_stability(stage, f) if f is not None else None
        if stab is None or stab[0] == 'unstable':
            notes.append(
                "finned: " + (
                    "its fins cannot hold it front-first (their restoring "
                    f"moment is {stab[1]:.1f}-{stab[2]:.1f} of the body's "
                    "overturning moment), so it turns over; "
                    if stab else "") +
                "trim not computed (no fin forces beyond 58 deg in the "
                "sources); flown tumbling only")
            return out
        from booster_models import _cd_fins
        def cda_front(M):
            return (front_first_cd(M, ld) + _cd_fins(
                stage.n_fins, stage.fin_span_m, stage.fin_root_chord_m,
                stage.fin_tip_chord_m, stage.fin_thickness_m, d, M,
                sweep_deg=stage.fin_sweep_deg)) * area
        out['cda_front_first'] = _tabulated(cda_front)
        out['fin_stability'] = stab[0]
        notes.append(
            f"finned: its fins' restoring moment is {stab[1]:.1f}-{stab[2]:.1f} "
            f"of the body's overturning moment at 15-20 deg, Mach 1.5-2.86 "
            f"(Jernell body force, read to +-0.4; fin force from the "
            f"build-up): " + (
                "it stays front-first like an arrow and is flown that way, "
                "at flat-face drag plus fin drag"
                if stab[0] == 'stable' else
                "too close to call, so the midpoint of the front-first and "
                "tumbling impacts is reported"))
        return out
    if getattr(stage, 'solid_motor', False):
        f, basis = empty_cg_fraction_solid(stage)
        notes.append(basis)
        if f is None:
            return out
    else:
        f, basis = empty_cg_fraction(stage, dry_mass_kg, role)
        notes.append(basis)
    g = min(f, 1.0 - f)
    lead = 'base' if f > 0.5 else 'front'
    if trim_alpha(MACH_HI, g) is None and trim_alpha(MACH_LO, g) is None:
        notes.append("CG at mid-length: no preferred attitude; flown "
                     "tumbling only")
        return out
    def cda_trim(M, _g=g):
        t = trim_cd(M, ld, _g)
        return (t[1] if t is not None else random_cd(M, ld)) * area
    out['cda_trim'] = _tabulated(cda_trim)
    out['leading'] = lead
    if dry_mass_kg and dry_mass_kg > 0:
        out['attitude'] = attitude_model(L, d, dry_mass_kg, f)
    a_lo, a_hi = trim_alpha(MACH_LO, g), trim_alpha(MACH_HI, g)
    notes.append(f"trims with its {lead} leading, CG {g:.2f} of its length "
                 f"from that end: "
                 f"{'end-on' if not a_lo else f'{a_lo:.0f} deg'} off end-on at "
                 f"Mach 1.5, {'end-on' if not a_hi else f'{a_hi:.0f} deg'} at "
                 f"Mach 2.86 (Jernell flat-ended cylinder)")
    return out
