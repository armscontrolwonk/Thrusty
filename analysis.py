"""
Analysis drivers and trajectory post-processing.

Everything here used to live inside Tkinter dialog classes in thrusty.py.
It is pure computation over the core models (trajectory, booster_models,
atmosphere, coordinates): no widgets, no threads, no plotting.  The GUI
owns orchestration — progress bars, cancel buttons, worker threads — and
calls these functions; the functions never call back into the GUI.

Sweeps are generators so a caller can report progress and stop early
without the sweep knowing anything about how.  Each yielded item is one
completed run.

Contents
--------
Post-processing of an integrate_trajectory() result dict:
    impact_point            impact (lat, lon) from the impact milestone
    final_position          last sample (lat, lon)
    position_at_time        (lat, lon) at a time, antimeridian-safe
    burnout_time            last burnout / cutoff milestone time
    derived_aero            Mach, dynamic pressure, density, sound speed
    glide_state_from_result mid-glide (V, h) anchor for the damping estimator

Sweep drivers:
    sweep_points            evenly spaced parameter values (linspace)
    bank_angles             arithmetic bank-angle ladder
    iter_range_ring         maximum-range impact point per azimuth
    iter_parametric_sweep   one guidance parameter varied, range/apogee/heating
    iter_bank_footprint     reachable footprint from a bank-angle sweep

Geometry of results:
    footprint_envelope      convex hull of impact points, closed polygon
    mean_range_km           mean geodesic range from a launch point
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Callable, Iterator, Optional, Sequence

import numpy as np

from coordinates import range_between


# ---------------------------------------------------------------------------
# Result post-processing
# ---------------------------------------------------------------------------

def _is_impact_milestone(m: dict) -> bool:
    return ('impact' in str(m.get('event', '')).lower()
            and not m.get('is_debris', False))


def impact_point(result: dict) -> Optional[tuple[float, float]]:
    """(lat_deg, lon_deg) of the primary impact, interpolated at the impact
    milestone's time (antimeridian-safe, see position_at_time).  None if the
    flight has no (non-debris) impact milestone, e.g. an orbital insertion."""
    impact = next((m for m in result.get('milestones', [])
                   if _is_impact_milestone(m)), None)
    if impact is None:
        return None
    return position_at_time(result, float(impact['t_s']))


def final_position(result: dict) -> Optional[tuple[float, float]]:
    """(lat_deg, lon_deg) of the last integrated sample, or None if empty."""
    lat = result.get('lat')
    if lat is None or len(lat) == 0:
        return None
    return float(lat[-1]), float(result['lon'][-1])


def _unwrap_deg(lon: np.ndarray) -> np.ndarray:
    """Longitude series made continuous across the antimeridian."""
    lon = np.asarray(lon, dtype=float)
    if lon.size == 0:
        return lon
    d = np.diff(lon)
    d = (d + 180.0) % 360.0 - 180.0
    out = np.empty_like(lon)
    out[0] = lon[0]
    if d.size:
        out[1:] = lon[0] + np.cumsum(d)
    return out


def wrap_lon_deg(lon: float) -> float:
    """Wrap a longitude to [-180, 180)."""
    return ((float(lon) + 180.0) % 360.0) - 180.0


def position_at_time(result: dict, t_s: float) -> tuple[float, float]:
    """(lat_deg, lon_deg) along the track at time t_s.  Longitude is
    unwrapped before interpolation so a track crossing ±180° does not
    interpolate through the far side of the planet."""
    t = np.asarray(result['t'], dtype=float)
    lat = np.asarray(result['lat'], dtype=float)
    lon_uw = _unwrap_deg(result['lon'])
    return (float(np.interp(t_s, t, lat)),
            wrap_lon_deg(float(np.interp(t_s, t, lon_uw))))


_BURNOUT_KEYS = ('burnout', 'cutoff', 'burn out')


def burnout_time(result: dict) -> Optional[float]:
    """Time of the LAST burnout / cutoff milestone, or None if there is none."""
    times = [float(m['t_s']) for m in result.get('milestones', [])
             if any(k in str(m.get('event', '')).lower() for k in _BURNOUT_KEYS)]
    return max(times) if times else None


def derived_aero(result: dict, atm_fn: Optional[Callable] = None,
                 sound_floor_ms: float = 10.0) -> Optional[dict]:
    """Aerodynamic quantities the integrator does not store.

    Returns a dict of arrays aligned with result['t']:
        t          time (s)
        rho        density (kg/m³)
        sound      speed of sound (m/s)
        mach       speed / sound; NaN where the atmosphere model reports a
                   sound speed at or below `sound_floor_ms` (above ~86 km
                   the models return 0)
        q_kpa      dynamic pressure ½ρV² (kPa)
        t_cutoff   last burnout/cutoff time (s), or the final time
        burn_mask  boolean, t <= t_cutoff
    or None when the result carries no altitude series.

    `atm_fn(alt_m) -> (T, P, rho, a)` defaults to atmosphere.atmosphere.
    """
    alt = np.asarray(result.get('alt', []), dtype=float)
    if alt.size == 0:
        return None
    if atm_fn is None:
        from atmosphere import atmosphere as atm_fn
    t = np.asarray(result['t'], dtype=float)
    spd = np.asarray(result['speed'], dtype=float)
    rho = np.empty(alt.size)
    sound = np.empty(alt.size)
    for i, h in enumerate(alt):
        _, _, rho[i], sound[i] = atm_fn(float(h))
    mach = np.full(alt.size, np.nan)
    ok = sound > sound_floor_ms
    mach[ok] = spd[ok] / sound[ok]
    q_kpa = 0.5 * rho * spd ** 2 / 1e3
    t_cut = burnout_time(result)
    if t_cut is None:
        t_cut = float(t[-1])
    return dict(t=t, rho=rho, sound=sound, mach=mach, q_kpa=q_kpa,
                t_cutoff=t_cut, burn_mask=(t <= t_cut))


def glide_state_from_result(result: dict,
                            band_km: tuple[float, float] = (25.0, 55.0)
                            ) -> Optional[tuple[float, float]]:
    """Mid-glide (V_kms, alt_km) from a trajectory result dict, or None.

    Takes the median speed/altitude over the post-apogee in-atmosphere glide
    (25–55 km by default) so the damping estimate can anchor on a flown
    state."""
    try:
        alt = np.asarray(result['alt'], dtype=float).ravel() / 1000.0
        spd = np.asarray(result['speed'], dtype=float).ravel() / 1000.0
        if alt.size < 5:
            return None
        iap = int(np.argmax(alt))
        a, v = alt[iap:], spd[iap:]
        m = (a >= band_km[0]) & (a <= band_km[1])
        if not m.any():
            return None
        return float(np.median(v[m])), float(np.median(a[m]))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sweep drivers
# ---------------------------------------------------------------------------

def sweep_points(lo: float, hi: float, step: float) -> np.ndarray:
    """Evenly spaced values from lo to hi inclusive, count chosen from step
    (at least 2).  This is the Parametric Sweep ladder."""
    lo, hi, step = float(lo), float(hi), float(step)
    if step <= 0:
        raise ValueError("Step must be > 0.")
    n = max(2, int(round((hi - lo) / step)) + 1)
    return np.linspace(lo, hi, n)


def bank_angles(lo: float, hi: float, step: float) -> list[float]:
    """Arithmetic ladder lo, lo+step, … ≤ hi (each rounded to 1e-6 deg).
    This is the Footprint bank-angle ladder; unlike sweep_points it never
    stretches the last step to land exactly on hi."""
    lo, hi, step = float(lo), float(hi), float(step)
    if step <= 0 or lo > hi:
        raise ValueError("Check sweep range (lo ≤ hi, step > 0).")
    out = []
    v = lo
    while v <= hi + 1e-9:
        out.append(round(v, 6))
        v += step
    return out


def iter_range_ring(booster, lat_deg: float, lon_deg: float, *,
                    n_az: int = 72, **maxrange_kwargs
                    ) -> Iterator[tuple[float, Optional[float], Optional[float]]]:
    """Maximum-range impact point in each of n_az equally spaced azimuths.

    Yields (azimuth_deg, impact_lon_deg, impact_lat_deg) per azimuth, with
    (az, None, None) when that direction produced no impact (failed
    optimisation, or no impact milestone).  Extra keyword arguments go to
    trajectory.maximize_range (guidance, burnout_angle_deg, gt_turn_*…).
    """
    from trajectory import maximize_range
    for az in np.linspace(0.0, 360.0, int(n_az), endpoint=False):
        az = float(az)
        try:
            result = maximize_range(booster, lat_deg, lon_deg, az,
                                    **maxrange_kwargs)
            pt = impact_point(result)
        except Exception:
            pt = None
        if pt is None:
            yield az, None, None
        else:
            yield az, pt[1], pt[0]


@dataclasses.dataclass
class SweepRow:
    """One completed run of a parametric sweep.  NaN marks a failed run."""
    value: float
    range_km: float
    apogee_km: float
    q_peak_MW_m2: float
    integrated_load_MJ_m2: float
    result: Optional[dict] = None      # full trajectory when requested

    def as_tuple(self):
        return (self.value, self.range_km, self.apogee_km,
                self.q_peak_MW_m2, self.integrated_load_MJ_m2)


# Parameter keys the sweep can vary and the integrate_trajectory keyword
# each one overrides.
SWEEP_PARAMS = {
    "azimuth":       "azimuth_deg",
    "burnout_angle": "burnout_angle_deg",
    "cutoff":        "cutoff_time_s",
    "turn_stop":     "gt_turn_stop_s",
}


def iter_parametric_sweep(booster, lat_deg: float, lon_deg: float,
                          param_key: str, values: Sequence[float], *,
                          azimuth_deg: float, burnout_angle_deg: float,
                          cutoff_time_s: Optional[float],
                          gt_turn_start_s: float = 5.0,
                          gt_turn_stop_s: Optional[float] = None,
                          keep_trajectories: bool = False,
                          **integrate_kwargs) -> Iterator[SweepRow]:
    """Vary ONE guidance parameter over `values`, holding the others fixed.

    param_key is one of SWEEP_PARAMS.  Each run reads range, apogee and the
    survivability figures of merit (integrate_trajectory computes
    result['heating_fom'] for free).  A run that raises yields a NaN row
    rather than aborting the sweep.
    """
    from trajectory import integrate_trajectory
    if param_key not in SWEEP_PARAMS:
        raise ValueError(f"unknown sweep parameter {param_key!r}; "
                         f"expected one of {sorted(SWEEP_PARAMS)}")
    base = dict(azimuth_deg=azimuth_deg, burnout_angle_deg=burnout_angle_deg,
                cutoff_time_s=cutoff_time_s, gt_turn_start_s=gt_turn_start_s,
                gt_turn_stop_s=gt_turn_stop_s)
    nan = float("nan")
    for val in values:
        val = float(val)
        kw = dict(base)
        kw[SWEEP_PARAMS[param_key]] = val
        az = kw.pop("azimuth_deg")
        try:
            r = integrate_trajectory(booster, lat_deg, lon_deg, az,
                                     **kw, **integrate_kwargs)
            fom = r.get("heating_fom") or {}
            yield SweepRow(
                val,
                r["range_km"] if r.get("range_km") is not None else nan,
                float(r["apogee_km"]),
                float(fom.get("q_peak_MW_m2") or nan),
                float(fom.get("integrated_load_MJ_m2") or nan),
                r if keep_trajectories else None)
        except Exception:
            yield SweepRow(val, nan, nan, nan, nan, None)


def with_bank_schedule(booster, bank_deg: float, t_end_s: float):
    """Deep copy of `booster` whose reentry object holds `bank_deg` for the
    whole flight window [0, t_end_s].  The bank is only applied while the
    glider is active, so the full window safely covers the glide phase
    whenever it begins.  Returns the copy unchanged if the stack carries no
    reentry object."""
    from booster_models import effective_ro
    m = copy.deepcopy(booster)
    ero = effective_ro(m)
    if ero is None:
        return m
    new_ro = dataclasses.replace(
        ero, glider_enabled=True,
        glider_bank_schedule=[(0.0, float(t_end_s), float(bank_deg))])
    node = m
    while node is not None:
        if node.ro is not None:
            node.ro = new_ro
            break
        node = node.stage2
    return m


def iter_bank_footprint(booster, lat_deg: float, lon_deg: float,
                        banks_deg: Sequence[float], *,
                        max_time_s: float = 3600.0,
                        errors: Optional[list] = None,
                        **integrate_kwargs
                        ) -> Iterator[tuple[float, Optional[dict]]]:
    """Fly the stack once per bank angle, the glider holding that bank for
    the whole flight.  Yields (bank_deg, result) with result None on failure;
    when `errors` is a list, each failure is also appended to it as
    (bank_deg, exception), so a caller can say WHY rather than just "failed".
    Keyword arguments go to trajectory.integrate_trajectory."""
    from trajectory import integrate_trajectory
    for bk in banks_deg:
        bk = float(bk)
        m = with_bank_schedule(booster, bk, max_time_s)
        try:
            r = integrate_trajectory(m, lat_deg, lon_deg,
                                     max_time_s=max_time_s, **integrate_kwargs)
        except Exception as exc:
            r = None
            if errors is not None:
                errors.append((bk, exc))
        yield bk, r


# ---------------------------------------------------------------------------
# Geometry of results
# ---------------------------------------------------------------------------

def footprint_envelope(points: Sequence[Sequence[float]]) -> list[list[float]]:
    """Closed boundary polygon around impact points, as [[lat, lon], …] with
    the first vertex repeated at the end.

    Uses the convex hull, so impacts that crash short (e.g. inverted-lift
    dives from banks beyond ±90°) fall inside and cannot distort the
    boundary.  Falls back to the points in the given order when a hull
    cannot be formed (fewer than 3 points, all collinear, SciPy missing).
    """
    pts = [[float(p[0]), float(p[1])] for p in points]
    if not pts:
        return []
    if len(pts) >= 3:
        try:
            from scipy.spatial import ConvexHull
            arr = np.array(pts)
            hull = ConvexHull(arr)
            env = [arr[i].tolist() for i in hull.vertices]
            return env + [env[0]]
        except Exception:
            pass
    return pts + [pts[0]]


def mean_range_km(launch_lat_deg: float, launch_lon_deg: float,
                  points_lon_lat: Sequence[tuple[float, float]]
                  ) -> Optional[float]:
    """Mean geodesic range (km) from the launch point to (lon, lat) points.
    None if no point could be measured."""
    la1, lo1 = np.radians(launch_lat_deg), np.radians(launch_lon_deg)
    out = []
    for lon, lat in points_lon_lat:
        try:
            out.append(range_between(la1, lo1, np.radians(lat),
                                     np.radians(lon)) / 1000.0)
        except Exception:
            pass
    return float(np.mean(out)) if out else None
