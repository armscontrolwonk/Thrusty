"""A nose tip of a different material from the body (TODO item 11): where
it is entered, how it is drawn and exported, and the second conduction
column it adds to the bondline and interior rows.
"""

import copy
import math

import numpy as np
import pytest

import booster_models as bm
import ro_section
import survivability_report as sr
from test_thresholds import _fly_glider

_CACHE = {}


def _glider():
    if 'g' not in _CACHE:
        _CACHE['g'] = _fly_glider()
    return copy.deepcopy(_CACHE['g'])


def _ro(nose_entry, nose_mat="silica_phenolic", body_th=0.0255):
    ro = bm.ROParams(name="test", mass_kg=16.0, beta_kg_m2=1.0,
                     diameter_m=0.4, length_m=0.2, nose_radius_m=0.12,
                     shape="cone", nose_tps_material=nose_mat,
                     body_tps_material="carbon_phenolic",
                     body_tps_thickness_m=body_th)
    ro.interior_layers = [{'material': 'titanium', 'thickness_m': 0.003},
                          {'material': 'tabi', 'thickness_m': 0.02}]
    ro.heating_locations = [nose_entry] if nose_entry else []
    return ro


SHELL = {'kind': 'nose_cap', 'construction': 'skin', 'thickness_m': 0.015,
         'length_m': 0.09}
SOLID = {'kind': 'nose_cap', 'construction': 'solid', 'solid_length_m': 0.05}


# ── the entry ────────────────────────────────────────────────────────────────
def test_each_construction_carries_only_its_own_keys():
    assert bm.clean_heating_locations([SHELL]) == [SHELL]
    with pytest.raises(ValueError, match="solid tip gives solid_length_m"):
        bm.clean_heating_locations([dict(SOLID, thickness_m=0.01)])
    with pytest.raises(ValueError, match="skin gives thickness_m"):
        bm.clean_heating_locations([dict(SHELL, solid_length_m=0.1)])


# ── the geometry ─────────────────────────────────────────────────────────────
def test_the_joint_is_measured_from_the_real_tip():
    # a blunted cone's tip is below length_m, which runs to where a sharp
    # cone's point would be
    sec = ro_section.section(_ro(SHELL))
    z_tip = max(z for _r, z in sec["outline"])
    assert z_tip < 0.2
    assert sec["nose"]["z_joint_m"] == pytest.approx(z_tip - 0.09)


def test_a_shell_nose_is_its_own_piece_and_the_layers_run_under_it():
    sec = ro_section.section(_ro(SHELL))
    kinds = [(pc["kind"], pc["material"]) for pc in sec["pieces"]]
    assert kinds == [("layer", "carbon_phenolic"), ("nose", "silica_phenolic"),
                     ("layer", "titanium"), ("layer", "tabi"),
                     ("interior", "")]
    zj = sec["nose"]["z_joint_m"]
    body = sec["pieces"][0]["loop"]
    nose = sec["pieces"][1]["loop"]
    assert max(z for _r, z in body) == pytest.approx(zj)
    assert min(z for _r, z in nose) == pytest.approx(zj)
    ti = sec["pieces"][2]["loop"]
    assert max(z for _r, z in ti) > zj      # the titanium runs under it


def test_a_solid_tip_fills_the_nose_and_the_layers_run_flat_under_it():
    sec = ro_section.section(_ro(SOLID, nose_mat="carbon_carbon"))
    zj = sec["nose"]["z_joint_m"]
    plug = next(pc for pc in sec["pieces"] if pc["kind"] == "nose")
    assert plug["solid"] and min(z for _r, z in plug["loop"]) == \
        pytest.approx(zj)
    assert any(r < 1e-9 and z == pytest.approx(zj) for r, z in plug["loop"])
    ti = next(pc for pc in sec["pieces"] if pc["material"] == "titanium")
    # the bulkhead: the titanium reaches the axis just under the joint
    assert any(r < 1e-9 and z == pytest.approx(zj) for r, z in ti["loop"])
    assert any(r < 1e-9 and z == pytest.approx(zj - 0.003) for r, z in
               ti["loop"])
    assert any("bulkhead (assumed)" in f for f in sec["flags"])


def test_a_different_nose_material_without_an_extent_is_said():
    sec = ro_section.section(_ro(None))
    assert sec["nose"] is None
    assert any("its extent is not entered" in f for f in sec["flags"])


def test_the_export_names_the_nose_and_revolves_the_drawn_pieces():
    import blender_export as bx
    ro = _ro(SHELL)
    revolves, flags = [], []
    bx._ro_elements(ro, 0.0, revolves, [], flags)
    assert [n for n, *_ in revolves] == [
        "RO_Body", "RO_Nose_silica_phenolic", "RO_Layer_2_titanium",
        "RO_Layer_3_tabi", "RO_Interior"]
    sec = ro_section.section(ro)
    assert [p for _n, p, *_ in revolves] == [pc["profile"]
                                            for pc in sec["pieces"]]
    assert any(f.startswith("RO nose: Silica phenolic, 1.5 cm shell")
               for f in flags)


# ── the physics ──────────────────────────────────────────────────────────────
def _with(r, ro):
    p = r['heating_arc']['profile']
    p.update(body_material=ro.body_material(),
             body_thickness_m=ro.body_tps_thickness_m,
             interior_layers=ro.interior_layers,
             nose_piece=ro_section.nose_piece(ro)[0])
    return r


def _row(rows, place):
    return next(r for r in rows if r['place'].startswith(place))


def test_the_nose_is_a_second_column_in_both_inside_rows():
    r = _with(_glider(), _ro(SHELL))
    rows = sr.answers(r)
    bond, inside = _row(rows, "Bondline"), _row(rows, "Interior")
    assert "; nose: " in bond['value'] and "1.5 cm of Silica phenolic" in \
        bond['value']
    assert "under the nose (1.5 cm of Silica phenolic)" in inside['value']
    assert "stagnation-point heating" in inside['basis']


def test_the_nose_column_is_hotter_under_the_stagnation_heating():
    # same material and thickness as the body: only the heating differs
    ro = _ro(dict(SHELL, thickness_m=0.0255), nose_mat="carbon_phenolic")
    r = _with(_glider(), ro)
    bond = _row(sr.answers(r), "Bondline")
    body_C, nose_C = (float(x.split(" °C")[0].split(": ")[-1].replace(",", ""))
                      for x in bond['value'].split("; "))
    assert nose_C > body_C


def test_a_solid_tip_is_a_slab_of_its_length():
    r = _with(_glider(), _ro(SOLID, nose_mat="carbon_carbon"))
    bond = _row(sr.answers(r), "Bondline")
    assert "5.0 cm of Bare carbon-carbon (solid tip, as a slab)" in \
        bond['value']


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


def test_the_editor_edits_the_nose_piece_and_keeps_the_rest(root):
    import thrusty
    ro = _ro(dict(SHELL, name="nose", source="drawing"))
    dlg = thrusty.ROEditorDialog(root, ro=ro)
    dlg.withdraw()
    assert dlg._nose_kind_var.get() == "shell"
    out = dlg._build_ro()
    assert out.heating_locations == ro.heating_locations
    dlg._nose_kind_var.set("solid tip")
    dlg._nose_ext_var.set("0.04")
    out = dlg._build_ro()
    assert out.heating_locations == [{'kind': 'nose_cap', 'name': 'nose',
                                      'construction': 'solid',
                                      'solid_length_m': 0.04,
                                      'source': 'drawing'}]
    dlg._redraw_section()
    dlg.destroy()
