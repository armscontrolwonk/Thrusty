"""analysis.py — the sweep drivers and result post-processing that used to
live inside thrusty.py's dialog classes.

The pure functions are pinned with synthetic result dicts; the sweep
generators are driven with a stubbed integrator so the orchestration (which
parameter varies, how failures are reported, how impacts are read) is tested
without flying anything.  The last block re-runs the GUI dialogs' worker
methods on the same stubs to prove the Tk wiring still lands rows in the
widgets (skips where Tk / a display is unavailable)."""
import inspect
import math
import numpy as np
import pytest

import analysis
import coordinates as co
import booster_models as mm
import trajectory as _trajectory

# The real callees, captured at import, before any test patches them.  Every
# stub below binds its arguments against the real signature FIRST, so a caller
# passing a keyword the real function does not take fails here.  Permissive
# `**kw` stubs let the footprint sweep call integrate_trajectory(azimuth_deg=…)
# — a name it has never had — while every run failed silently in the GUI, and
# the test even asserted the wrong name.
_REAL = {"integrate_trajectory": _trajectory.integrate_trajectory,
         "maximize_range": _trajectory.maximize_range}


def _bind(name, *a, **kw):
    """Raise TypeError exactly where the real `name` would."""
    inspect.signature(_REAL[name]).bind(*a, **kw)


# ── synthetic results ───────────────────────────────────────────────────────

def _result(n=50, t_end=500.0, lon0=170.0, dlon=20.0, impact_t=None,
            with_burnout=True):
    """A ballistic-looking arc: altitude a parabola to 300 km, longitude
    sweeping east across the antimeridian."""
    t = np.linspace(0.0, t_end, n)
    alt = 300e3 * (1 - ((t - t_end / 2) / (t_end / 2)) ** 2)
    alt[-1] = 0.0
    lon = ((lon0 + dlon * t / t_end + 180.0) % 360.0) - 180.0
    ms = []
    if with_burnout:
        ms += [dict(event="Stage 1 burnout", t_s=60.0),
               dict(event="Stage 2 cutoff", t_s=120.0)]
    ms.append(dict(event="Debris impact", t_s=200.0, is_debris=True))
    if impact_t is not None:
        ms.append(dict(event="Impact", t_s=impact_t))
    return dict(t=t, alt=alt, speed=np.full(n, 3000.0),
                lat=np.linspace(30.0, 40.0, n), lon=lon,
                range=np.linspace(0, 1e6, n), milestones=ms)


# ── post-processing ─────────────────────────────────────────────────────────

def test_impact_point_reads_the_non_debris_impact_milestone():
    r = _result(impact_t=250.0)
    lat, lon = analysis.impact_point(r)
    assert lat == pytest.approx(35.0)                       # halfway, 30→40
    assert abs(abs(lon) - 180.0) < 1e-9                     # 170→−170 crosses ±180


def test_impact_point_none_without_impact():
    assert analysis.impact_point(_result()) is None         # only debris


def test_final_position():
    r = _result()
    assert analysis.final_position(r) == (40.0, pytest.approx(r['lon'][-1]))
    assert analysis.final_position(dict(lat=[], lon=[])) is None


def test_position_at_time_is_antimeridian_safe():
    r = _result(lon0=175.0, dlon=10.0)          # 175 → 185 ≡ −175
    lat, lon = analysis.position_at_time(r, 250.0)
    assert lat == pytest.approx(35.0)
    assert lon == pytest.approx(180.0, abs=1e-9) or lon == pytest.approx(-180.0, abs=1e-9)
    # naive interpolation would have given ~0° (through the far side)
    naive = float(np.interp(250.0, r['t'], r['lon']))
    assert abs(naive) < 90.0


def test_burnout_time_is_the_last_cutoff():
    assert analysis.burnout_time(_result()) == 120.0
    assert analysis.burnout_time(_result(with_burnout=False)) is None


def test_derived_aero_mach_q_and_burn_mask():
    r = _result()
    def atm(h):              # T, P, rho, a — a→0 above 86 km like the models
        return 250.0, 1e3, 1.0 * math.exp(-h / 8000.0), (300.0 if h < 86e3 else 0.0)
    d = analysis.derived_aero(r, atm)
    assert d['t_cutoff'] == 120.0
    assert d['burn_mask'].sum() == (r['t'] <= 120.0).sum()
    low = r['alt'] < 86e3
    assert np.allclose(d['mach'][low], 10.0)
    assert np.isnan(d['mach'][~low]).all()
    assert d['q_kpa'][0] == pytest.approx(0.5 * 1.0 * 3000.0 ** 2 / 1e3)
    assert analysis.derived_aero(dict(alt=[], t=[], speed=[]), atm) is None


def test_glide_state_from_result_medians_the_glide_band():
    r = _result()
    st = analysis.glide_state_from_result(r)
    assert st is not None
    v, h = st
    assert v == pytest.approx(3.0)
    assert 25.0 <= h <= 55.0
    assert analysis.glide_state_from_result(dict(alt=[1, 2], speed=[1, 2])) is None


# ── ladders ─────────────────────────────────────────────────────────────────

def test_sweep_points_linspace_semantics():
    pts = analysis.sweep_points(0, 10, 2.5)
    assert list(pts) == [0.0, 2.5, 5.0, 7.5, 10.0]
    assert len(analysis.sweep_points(0, 1, 100)) == 2               # at least 2
    with pytest.raises(ValueError):
        analysis.sweep_points(0, 1, 0)


def test_bank_angles_arithmetic_ladder():
    assert analysis.bank_angles(-30, 30, 15) == [-30.0, -15.0, 0.0, 15.0, 30.0]
    assert analysis.bank_angles(0, 10, 4) == [0.0, 4.0, 8.0]            # no stretch
    with pytest.raises(ValueError):
        analysis.bank_angles(10, 0, 1)


# ── sweep drivers on a stubbed integrator ───────────────────────────────────

class _Stub:
    """Records every call; returns a result whose range encodes the inputs."""
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def integrate(self, booster, lat, lon, az, **kw):
        _bind("integrate_trajectory", booster, lat, lon, az, **kw)
        self.calls.append((az, kw))
        if self.fail_on is not None and self.fail_on(az, kw):
            raise RuntimeError("boom")
        r = _result(impact_t=250.0)
        r['range_km'] = 1000.0 + az + (kw.get('burnout_angle_deg') or 0.0)
        r['apogee_km'] = 300.0
        r['heating_fom'] = dict(q_peak_MW_m2=1.5, integrated_load_MJ_m2=20.0)
        return r

    def maximize(self, booster, lat, lon, az, **kw):
        _bind("maximize_range", booster, lat, lon, az, **kw)
        self.calls.append((az, kw))
        if self.fail_on is not None and self.fail_on(az, kw):
            raise RuntimeError("boom")
        return _result(impact_t=250.0, lon0=lon + az / 10.0)


def test_iter_parametric_sweep_varies_only_the_named_parameter(monkeypatch):
    import trajectory
    stub = _Stub()
    monkeypatch.setattr(trajectory, "integrate_trajectory", stub.integrate)
    rows = list(analysis.iter_parametric_sweep(
        object(), 0.0, 0.0, "burnout_angle", [20.0, 30.0],
        azimuth_deg=90.0, burnout_angle_deg=45.0, cutoff_time_s=60.0,
        gt_turn_stop_s=None, guidance="pitch_program", keep_trajectories=True))
    assert [c[0] for c in stub.calls] == [90.0, 90.0]                 # az held
    assert [c[1]['burnout_angle_deg'] for c in stub.calls] == [20.0, 30.0]
    assert all(c[1]['cutoff_time_s'] == 60.0 for c in stub.calls)
    assert all(c[1]['guidance'] == "pitch_program" for c in stub.calls)
    assert [r.value for r in rows] == [20.0, 30.0]
    assert rows[0].range_km == pytest.approx(1110.0)
    assert rows[0].q_peak_MW_m2 == 1.5 and rows[0].result is not None
    assert rows[0].as_tuple() == (20.0, 1110.0, 300.0, 1.5, 20.0)


def test_iter_parametric_sweep_azimuth_and_failures(monkeypatch):
    import trajectory
    stub = _Stub(fail_on=lambda az, kw: az == 180.0)
    monkeypatch.setattr(trajectory, "integrate_trajectory", stub.integrate)
    rows = list(analysis.iter_parametric_sweep(
        object(), 0.0, 0.0, "azimuth", [90.0, 180.0],
        azimuth_deg=0.0, burnout_angle_deg=45.0, cutoff_time_s=None))
    assert [c[0] for c in stub.calls] == [90.0, 180.0]
    assert rows[0].range_km == pytest.approx(1135.0)
    assert math.isnan(rows[1].range_km) and rows[1].result is None   # failure → NaN row
    with pytest.raises(ValueError):
        next(analysis.iter_parametric_sweep(object(), 0, 0, "nope", [1],
                                            azimuth_deg=0, burnout_angle_deg=0,
                                            cutoff_time_s=None))


def test_iter_range_ring_spacing_and_impacts(monkeypatch):
    import trajectory
    stub = _Stub(fail_on=lambda az, kw: az == 90.0)
    monkeypatch.setattr(trajectory, "maximize_range", stub.maximize)
    ring = list(analysis.iter_range_ring(object(), 10.0, 20.0, n_az=4,
                                         guidance="gravity_turn"))
    assert [p[0] for p in ring] == [0.0, 90.0, 180.0, 270.0]
    assert ring[1][1:] == (None, None)                                # failed az
    az, lon, lat = ring[2]
    assert lat == pytest.approx(35.0)                                  # impact_t midway
    assert all(c[1]['guidance'] == "gravity_turn" for c in stub.calls)


def test_with_bank_schedule_replaces_the_ro_on_a_deep_copy():
    from booster_models import get_booster, load_booster_library
    load_booster_library()
    b = get_booster("AUR")
    m = analysis.with_bank_schedule(b, 25.0, 3600.0)
    assert m is not b
    ro = mm.effective_ro(m)
    assert ro.glider_enabled and ro.glider_bank_schedule == [(0.0, 3600.0, 25.0)]
    assert mm.effective_ro(b).glider_bank_schedule != ro.glider_bank_schedule


def test_iter_bank_footprint_flies_each_bank(monkeypatch):
    import trajectory
    from booster_models import get_booster, load_booster_library
    load_booster_library()
    seen = []
    def fake(booster, lat, lon, **kw):
        _bind("integrate_trajectory", booster, lat, lon, **kw)
        bk = mm.effective_ro(booster).glider_bank_schedule[0][2]
        if bk == 30.0:
            raise RuntimeError("stalled")
        seen.append((bk, kw))
        return _result(impact_t=250.0)
    monkeypatch.setattr(trajectory, "integrate_trajectory", fake)
    errors = []
    out = list(analysis.iter_bank_footprint(get_booster("AUR"), 0.0, 0.0,
                                            [-10.0, 10.0, 30.0],
                                            launch_azimuth_deg=45.0,
                                            guidance="pitch_program",
                                            errors=errors))
    assert [b for b, _ in seen] == [-10.0, 10.0]
    assert all(kw['launch_azimuth_deg'] == 45.0 and kw['max_time_s'] == 3600.0
               and 'errors' not in kw for _, kw in seen)
    assert [b for b, r in out] == [-10.0, 10.0, 30.0]
    assert [r is not None for _, r in out] == [True, True, False]
    # the failure is reported with its reason, not only as a None
    assert [(b, str(e)) for b, e in errors] == [(30.0, "stalled")]


def test_a_wrong_keyword_now_fails_the_stub():
    """The guard itself: the keyword the footprint sweep used to pass is
    rejected exactly as the real integrator rejects it."""
    with pytest.raises(TypeError):
        _bind("integrate_trajectory", object(), 0.0, 0.0, azimuth_deg=45.0)
    _bind("integrate_trajectory", object(), 0.0, 0.0, launch_azimuth_deg=45.0)


# ── geometry of results ─────────────────────────────────────────────────────

def test_footprint_envelope_is_a_closed_hull_ignoring_interior_points():
    pts = [(0, 0), (0, 1), (1, 1), (1, 0), (0.5, 0.5)]
    env = analysis.footprint_envelope(pts)
    assert env[0] == env[-1] and len(env) == 5
    assert [0.5, 0.5] not in env
    # collinear → fallback keeps the given order and closes the ring
    col = analysis.footprint_envelope([(0, 0), (1, 1), (2, 2)])
    assert col == [[0, 0], [1, 1], [2, 2], [0, 0]]
    assert analysis.footprint_envelope([]) == []
    assert analysis.footprint_envelope([(1, 2)]) == [[1, 2], [1, 2]]


def test_mean_range_km():
    # one degree of longitude on the equator ≈ 111.3 km (WGS-84)
    m = analysis.mean_range_km(0.0, 0.0, [(1.0, 0.0), (-1.0, 0.0)])
    assert m == pytest.approx(111.32, abs=0.1)
    assert analysis.mean_range_km(0.0, 0.0, []) is None


# ── aiming geometry (coordinates.py) ────────────────────────────────────────

def test_initial_bearing_cardinal_directions():
    r = np.radians
    assert co.initial_bearing_deg(0, 0, 0, r(10)) == pytest.approx(90.0)
    assert co.initial_bearing_deg(0, 0, r(10), 0) == pytest.approx(0.0)
    assert co.initial_bearing_deg(0, 0, r(-10), 0) == pytest.approx(180.0)
    assert co.initial_bearing_deg(0, 0, 0, r(-10)) == pytest.approx(270.0)


def test_rotation_corrected_azimuth_shifts_east_with_flight_time():
    r = np.radians
    c0 = co.rotation_corrected_azimuth(r(35), r(127), r(38), r(140), 0.0)
    assert c0['azimuth_deg'] == pytest.approx(c0['azimuth_uncorrected_deg'])
    assert c0['drift_deg'] == 0.0
    c = co.rotation_corrected_azimuth(r(35), r(127), r(38), r(140), 600.0)
    assert c['drift_deg'] == pytest.approx(math.degrees(co.OMEGA_EARTH * 600.0))
    assert c['azimuth_deg'] > c['azimuth_uncorrected_deg']       # aim further east
    assert c['range_km'] == pytest.approx(1210.1, abs=0.5)


def test_min_energy_flight_time():
    assert co.min_energy_flight_time_s(1000e3) == pytest.approx(math.sqrt(2e6 / 9.81))


# ── small design formulas (booster_models.py) ───────────────────────────────

def test_editor_formulas():
    assert mm.base_area_m2(2.0) == pytest.approx(math.pi)
    assert mm.ballistic_coefficient(450.0, 0.1, 0.58) == pytest.approx(
        450.0 / (0.1 * math.pi * 0.29 ** 2))
    assert mm.ballistic_coefficient(450.0, 0.0, 0.58) == float('inf')
    assert mm.cone_half_angle_deg(2.0, 1.0) == pytest.approx(45.0)
    assert mm.thrust_for_acceleration(1000.0, 0.0, 0.0) == pytest.approx(1000.0 * 9.80665)
    assert mm.nozzle_exit_area_estimate(100.0, 280.0, 0.1) == pytest.approx(
        9.80665 / 101325.0 * 100.0 * 280.0 * 0.1)
    with pytest.raises(ValueError):
        mm.nozzle_exit_area_estimate(0.0, 280.0, 0.1)
    # exposed wing area matches wing_geometry's planform derivation (no carry-through)
    assert mm.wing_exposed_area_m2(1.0, 0.5, 0.0) == pytest.approx(1.0)
    assert mm.wing_exposed_area_m2(1.0, 0.5, 30.0) == pytest.approx(
        (1.0 + (1.0 - 0.5 * math.tan(math.radians(30.0)))) * 0.5)
    assert mm.wing_exposed_area_m2(0.0, 0.5, 0.0) == 0.0


# ── GUI wiring: the dialog workers still land rows in their widgets ─────────

tk = pytest.importorskip("tkinter", reason="no Tk in this interpreter")


@pytest.fixture(scope="module")
def app():
    import matplotlib
    matplotlib.use("Agg")
    import thrusty
    try:
        a = thrusty.BoosterFlyoutApp()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    a.withdraw()
    yield a
    a.destroy()


def _pump(widget, n=20):
    for _ in range(n):
        widget.update()


def test_parametric_sweep_dialog_worker_fills_the_table(app, monkeypatch):
    import thrusty, trajectory
    from booster_models import get_booster
    stub = _Stub()
    monkeypatch.setattr(trajectory, "integrate_trajectory", stub.integrate)
    dlg = thrusty.ParametricSweepDialog(app)
    try:
        dlg._results, dlg._traj_store = [], []
        dlg._sweep_worker(get_booster("AUR"), "pitch_program", 0.0, 0.0, 90.0,
                          45.0, 60.0, "burnout_angle", [20.0, 30.0], False)
        _pump(dlg)
        assert [r[0] for r in dlg._results] == [20.0, 30.0]
        assert len(dlg._tree.get_children()) == 2
        assert dlg._results[0][1] == pytest.approx(1110.0)
    finally:
        dlg.destroy()


def test_range_ring_dialog_worker_collects_points(app, monkeypatch):
    import thrusty, trajectory
    from booster_models import get_booster
    stub = _Stub(fail_on=lambda az, kw: az == 90.0)
    monkeypatch.setattr(trajectory, "maximize_range", stub.maximize)
    dlg = thrusty.RangeRingDialog(app)
    try:
        dlg._N_AZ = 4
        dlg._worker(get_booster("AUR"), "pitch_program", 10.0, 20.0, 45.0,
                    5.0, None, 90.0)
        _pump(dlg)
        assert dlg._ring is not None and len(dlg._ring) == 3          # one az failed
        assert [p[0] for p in dlg._ring] == [0.0, 180.0, 270.0]
        assert dlg._launch_lat == 10.0 and dlg._launch_lon == 20.0
    finally:
        dlg.destroy()


def test_footprint_dialog_worker_records_each_bank(app, monkeypatch):
    import thrusty, trajectory
    from booster_models import get_booster
    calls = []
    def fake(booster, lat, lon, **kw):
        _bind("integrate_trajectory", booster, lat, lon, **kw)
        calls.append(mm.effective_ro(booster).glider_bank_schedule[0][2])
        return _result(impact_t=250.0)
    monkeypatch.setattr(trajectory, "integrate_trajectory", fake)
    monkeypatch.setattr(thrusty.FootprintDialog, "_on_done", lambda self: None)
    dlg = thrusty.FootprintDialog(app)
    try:
        dlg._worker(get_booster("AUR"), "pitch_program", 0.0, 0.0, 90.0, None,
                    45.0, 5.0, None, None, None, 90.0, [-20.0, 0.0, 20.0])
        _pump(dlg)
        assert calls == [-20.0, 0.0, 20.0]
        assert [b for b, _ in dlg._results] == [-20.0, 0.0, 20.0]
        assert dlg._errors == []
    finally:
        dlg.destroy()
