"""TPSX cross-check drift guard — every material field wired FROM the TPSX
crawl must equal the archived primary (data/tpsx/catalog.json), and the
documented intentional divergences must stay documented, not drift silently.

The full 14-entry audit and its dispositions live in BENCHMARKING.md
("CROSS-CHECKED" note): matches within ~5% are logged; the c_p gaps on hot
structures are a regime difference (ours are high-T averages for the melt
integral, TPSX quotes room temperature); char-vs-virgin k on carbon phenolic
is a state difference; ACC is not the HTV-2-class C/C.  This test pins only
what was WIRED from TPSX, against the archive itself.
"""

import json

import heating

_CAT = json.load(open("data/tpsx/catalog.json"))


def _tpsx(mid, prop):
    for row in _CAT[str(mid)]["props"]:
        if row[0].rstrip("0123456789 ") == prop:
            return float(row[1])
    raise KeyError((mid, prop))


def test_sirca_14a_matches_tpsx_id41():
    m = heating.TPS_MATERIALS["sirca"]
    assert m["density_kg_m3"] == _tpsx(41, "Density") == 224.0
    assert m["c_J_kgK"] == _tpsx(41, "Specific Heat") == 1200.0
    assert m["k_W_mK"] == _tpsx(41, "Thermal Conductivity (Isotropic)") == 0.0629
    # nominal = TPSX's standard-conditions H_eff (the curve's high-pressure
    # minimum); the bound 165 is from the curve's mid-pressure cluster and is
    # deliberately NOT the standard-conditions value.
    assert m["H_eff_MJ_kg"] == _tpsx(41, "Effective Heat of Ablation") / 1e6 == 37.4


def test_pica_matches_tpsx_id43():
    m = heating.TPS_MATERIALS["pica"]
    assert m["k_W_mK"] == _tpsx(43, "Thermal Conductivity (Isotropic)") == 0.305
    assert m["c_J_kgK"] == _tpsx(43, "Specific Heat") == 1200.0
    assert m["H_eff_bound_MJ_kg"] == _tpsx(43, "Effective Heat of Ablation") / 1e6 == 115.0
    # density intentionally kept at the flight-era 270 (Stackpoole/PICA v3.3)
    # vs TPSX's early 236 ±12 — documented divergence, both must still exist.
    assert m["density_kg_m3"] == 270.0
    assert _tpsx(43, "Density") == 236.0


def test_silica_phenolic_k_matches_mx2600_crossply():
    m = heating.TPS_MATERIALS["silica_phenolic"]
    assert m["k_W_mK"] == _tpsx(162, "Thermal Conductivity (Isotropic)") == 0.710


def test_carbon_phenolic_c_matches_narmco():
    # Narmco 4028 (TPSX id 113) is the exact Sutton TN D-5930 material; its
    # room-T c feeds the bondline soak (conservative-low vs the old high-T
    # 1500).  The char k=1.5 (Cabrera-West) is a STATE choice, not a TPSX
    # value — Narmco's 0.367 is virgin and must not overwrite it.
    m = heating.TPS_MATERIALS["carbon_phenolic"]
    assert m["c_J_kgK"] == _tpsx(113, "Specific Heat") == 1120.0
    assert m["k_W_mK"] == 1.5 and _tpsx(113, "Thermal Conductivity (Isotropic)") == 0.367


def test_c_sic_limits_match_tpsx_id26():
    m = heating.TPS_MATERIALS["c_sic"]
    assert m["continuous_K"] == _tpsx(26, "Multiple Use Temperature Limit") == 1920.0
    assert m["peak_K"] == _tpsx(26, "Single Use Temperature Limit") == 1980.0


# Conductivities for the interior-after-the-soak row (TODO item 11): each
# catalog material's k is the TPSX entry named in its k_source, through the
# thickness where TPSX gives a direction.
_K_FROM_TPSX = {
    "aluminum": (60, "Thermal Conductivity (Isotropic)"),
    "titanium": (261, "Thermal Conductivity (Isotropic)"),
    "steel": (57, "Thermal Conductivity (Isotropic)"),
    "rcc": (24, "Thermal Conductivity (Thru-the-Thickness)"),
    "c_sic": (26, "Thermal Conductivity (Thru-the-Thickness)"),
    "cc_hot_structure": (25, "Thermal Conductivity (Isotropic)"),
    "uhtc": (28, "Thermal Conductivity (Isotropic)"),
    "silica_tile": (1, "Thermal Conductivity (Thru-the-Thickness)"),
    "carbon_ablator": (36, "Thermal Conductivity (Isotropic)"),
    "carbon_carbon": (36, "Thermal Conductivity (Isotropic)"),
}


def test_every_catalog_material_has_a_cited_conductivity():
    for key, m in heating.TPS_MATERIALS.items():
        assert m.get("k_W_mK", 0) > 0 and m.get("k_source"), key


def test_wired_conductivities_match_their_tpsx_entries():
    for key, (mid, prop) in _K_FROM_TPSX.items():
        m = heating.TPS_MATERIALS[key]
        assert m["k_W_mK"] == _tpsx(mid, prop), key
        assert f"TPSX id {mid}," in m["k_source"], key
