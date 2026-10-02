"""The layers between the body's outer layer and the payload (TODO item 11,
step 2): conductivity and specific heat against temperature from the TPSX
curves, a one-dimensional stack, and the two inside rows of the report.
"""

import copy

import numpy as np
import pytest

import booster_models as bm
import heating
import survivability_report as sr
from test_thresholds import _fly_glider

_CACHE = {}


def _glider():
    if 'g' not in _CACHE:
        _CACHE['g'] = _fly_glider()
    return copy.deepcopy(_CACHE['g'])


def _flat(dur, q):
    t = np.linspace(0.0, dur, int(dur) + 1)
    return t, np.full_like(t, q)


def _row(rows, place):
    return next(r for r in rows if r['place'].startswith(place))


# ── the curves ───────────────────────────────────────────────────────────────
def test_tile_conductivity_is_the_one_atmosphere_curve():
    T, k, note = heating.material_curve('silica_tile', 'k')
    assert "101,330 Pa" in note and "TPSX id 1" in note
    assert k[0] == pytest.approx(0.0403) and k[-1] == pytest.approx(0.502)
    assert k[-1] > 10 * heating.TPS_MATERIALS['silica_tile']['k_W_mK']


def test_uhtc_conductivity_falls_with_temperature():
    T, k, _ = heating.material_curve('uhtc', 'k')
    assert k[0] == pytest.approx(98.7) and k[-1] == pytest.approx(69.0)


def test_a_material_without_a_curve_uses_its_one_value():
    assert heating.material_curve('carbon_phenolic', 'k') is None
    res = heating.layered_conduction(*_flat(60, 2e5),
                                     [('carbon_phenolic', 0.02)])
    assert any("k = 1.5 W/m·K, one value" in n for n in res['notes'])


# ── the stack ────────────────────────────────────────────────────────────────
def test_splitting_a_layer_in_two_changes_nothing():
    t, q = _flat(300, 3e5)
    one = heating.layered_conduction(t, q, [('carbon_phenolic', 0.02)],
                                     n_per_layer=40)
    two = heating.layered_conduction(t, q, [('carbon_phenolic', 0.01),
                                            ('carbon_phenolic', 0.01)],
                                     n_per_layer=20)
    assert two['T_faces'][-1].max() == pytest.approx(
        one['T_faces'][-1].max(), rel=0.01)


def test_a_layer_behind_the_shield_cools_its_back_face_and_the_inside_more():
    t, q = _flat(400, 3e5)
    alone = heating.layered_conduction(t, q, [('carbon_phenolic', 0.01)])
    stack = heating.layered_conduction(t, q, [('carbon_phenolic', 0.01),
                                              ('aluminum', 0.003),
                                              ('tabi', 0.02)])
    bond_alone = alone['T_faces'][-1].max()
    bond, inner = stack['T_faces'][1].max(), stack['T_faces'][-1].max()
    assert bond < bond_alone           # the aluminium soaks heat away
    assert inner < bond                # the blanket holds the rest back


def test_past_the_end_of_a_table_is_said():
    res = heating.layered_conduction(*_flat(600, 1.5e6), [('tabi', 0.01)])
    assert any("past the end of its TPSX k table" in w
               for w in res['warnings'])


def test_an_unknown_layer_material_is_not_evaluated():
    res = heating.layered_conduction(*_flat(10, 1e5),
                                     [('carbon_phenolic', 0.01), ('', 0.01)])
    assert res['evaluated'] is False


# ── the field ────────────────────────────────────────────────────────────────
def test_layers_are_checked():
    ok = bm.clean_interior_layers([{'material': 'tabi', 'thickness_m': '0.02',
                                    'source': 'x'}])
    assert ok == [{'material': 'tabi', 'thickness_m': 0.02, 'source': 'x'}]
    for bad, msg in (([{'material': 'cork', 'thickness_m': 0.01}], "catalog"),
                     ([{'material': 'tabi', 'thickness_m': 0}], "positive"),
                     ([{'material': 'tabi', 'thickness_m': '1 cm'}], "plain"),
                     ([{'material': 'tabi', 'thickness_m': 0.01, 'k': 1}],
                      "may carry only")):
        with pytest.raises(ValueError, match=msg):
            bm.clean_interior_layers(bad)


# ── the two inside rows ──────────────────────────────────────────────────────
def _with_stack(r, layers, limit_C=80.0):
    p = r['heating_arc']['profile']
    p.update(body_material='carbon_phenolic', body_thickness_m=0.02,
             interior_layers=layers, interior_limit_C=limit_C)
    return r


def test_the_payload_row_reads_the_innermost_face():
    r = _with_stack(_glider(), [{'material': 'aluminum', 'thickness_m': 0.003},
                                {'material': 'tabi', 'thickness_m': 0.03}])
    rows = sr.answers(r)
    inside, bond = _row(rows, "Interior"), _row(rows, "Bondline")
    assert inside['tier'] in ('experience', 'beyond')
    assert "at the inner face of 3.0 cm of TABI blanket" in inside['value']
    assert "no payload mass" in inside['basis']
    assert "Accuracy not yet established" in inside['basis']
    t_in = float(inside['value'].split(" °C")[0].replace(",", ""))
    t_bond = float(bond['value'].split(" °C")[0].replace(",", ""))
    assert t_in <= t_bond


def test_a_low_interior_limit_turns_the_headline():
    r = _with_stack(_glider(), [{'material': 'aluminum', 'thickness_m': 0.003}],
                    limit_C=-50.0)
    assert _row(sr.answers(r), "Interior")['tier'] == 'beyond'
    assert "interior" in sr.build_report(r)['headline'].split("past limit")[0]


# ── the drawing and the export agree ─────────────────────────────────────────
def _capsule():
    ro = bm.ROParams(name="test capsule", mass_kg=16.0, beta_kg_m2=1.0,
                     diameter_m=0.4, length_m=0.2, nose_radius_m=0.12,
                     shape="cone", body_tps_material="carbon_phenolic",
                     body_tps_thickness_m=0.0255)
    ro.interior_layers = [{'material': 'titanium', 'thickness_m': 0.003},
                          {'material': 'tabi', 'thickness_m': 0.02}]
    return ro


def test_each_layer_is_offset_by_its_thickness_normal_to_the_wall():
    import math
    import ro_section
    sec = ro_section.section(_capsule())
    o = sec["outline"]
    (r0, z0), (r1, z1) = o[1], o[2]                 # the conical flank
    L = math.hypot(r1 - r0, z1 - z0)
    n = (-(z1 - z0) / L, (r1 - r0) / L)
    depth = 0.0
    for lay in sec["layers"]:
        depth += lay["thickness_m"]
        p = lay["inner"][2]
        assert n[0] * (p[0] - r0) + n[1] * (p[1] - z0) == pytest.approx(depth)
    assert sec["interior"] == sec["layers"][-1]["inner"]


def test_the_export_revolves_the_drawn_layers():
    import blender_export as bx
    import ro_section
    ro = _capsule()
    revolves, plates, flags = [], [], []
    bx._ro_elements(ro, 0.0, revolves, plates, flags)
    names = [n for n, *_ in revolves]
    assert names == ["RO_Body", "RO_Layer_2_titanium", "RO_Layer_3_tabi",
                     "RO_Interior"]
    sec = ro_section.section(ro)
    for (name, prof, _p, _s), lay in zip(revolves, sec["layers"]):
        assert prof == ro_section.band(lay["outer"], lay["inner"])
    assert revolves[-1][1] == sec["interior"]
    assert any(f.startswith("RO wall: 2.5 cm Carbon phenolic") for f in flags)


def test_the_schematic_draws_from_the_same_outline():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import booster_schematic as bs
    import ro_section
    fig, ax = plt.subplots()
    sec = bs.draw_ro_section(ax, _capsule())
    polys = [p.get_xy() for p in ax.patches if hasattr(p, "get_xy")]
    right = [(x, y) for x, y in ro_section.section(_capsule())["interior"]]
    assert any(len(p) >= len(right) and
               np.allclose(p[:len(right)], right) for p in polys)
    texts = " ".join(t.get_text() for t in ax.texts)
    assert "0.3 cm Titanium" in texts and "2.0 cm TABI blanket" in texts
    plt.close(fig)


def test_a_lifting_body_says_its_layers_are_not_drawn_in_both():
    import blender_export as bx
    import ro_section
    ro = _capsule()
    ro.body_form = "wedge"
    flags = []
    bx._ro_elements(ro, 0.0, [], [], flags)
    assert ro_section.LIFTING_NOT_SECTIONED in flags
    assert ro_section.LIFTING_NOT_SECTIONED in ro_section.section(ro)["flags"]


# ── the editor ───────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def root():
    tk = pytest.importorskip("tkinter")
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    r.withdraw()
    yield r
    r.destroy()


def test_the_editor_keeps_the_layers(root):
    import thrusty
    dlg = thrusty.ROEditorDialog(root, ro=_capsule())
    dlg.withdraw()
    assert len(dlg._layer_rows) == 2
    dlg._redraw_section()
    out = dlg._build_ro()
    assert out.interior_layers == _capsule().interior_layers
    dlg._layer_rows[0][2].set("-1")
    import tkinter.messagebox as mb
    shown = []
    orig = mb.showerror
    thrusty.messagebox.showerror = lambda *a, **k: shown.append(a)
    try:
        assert dlg._build_ro() is None
    finally:
        thrusty.messagebox.showerror = orig
    assert shown and "positive" in shown[0][1]
    dlg.destroy()
