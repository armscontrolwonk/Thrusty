"""Blender export of the vehicle — a dimensionally correct 3-D rough draft
for modelers (TODO item 2, option (a): a generated bpy script).

Emits a self-contained **Blender Python script**: the modeler opens
Blender, loads it in the Scripting tab, and runs it — each vehicle element
lands as a DISCRETE, named, editable mesh object (S1, Interstage_1,
Fairing, Fin_1, Strapon_2, RO_Body, …) in its own collection, at true
metres, +Z up (the vehicle axis).

Real 3-D shapes, not extruded silhouettes:
- stages are true cylinders / truncated cones (conical stages), built as
  closed solids of revolution;
- interstages are true frustums with the same derived diameters the 2-D
  schematic uses (this stage's top → the next stage's base);
- noses and fairings revolve their real analytic profiles — tangent
  ogive, Von Kármán / Sears-Haack (Haack series), parabolic, blunt dome,
  straight cone — so a Sears-Haack fairing is a true Haack surface;
- an axisymmetric RO revolves its declared profile, with a true
  sphere-cone blend when a nose radius is stored on a cone;
- known non-revolved parts extrude: fins are swept plates placed around
  the body, the wedge RO is a prism across its span, the half-cone RO is
  a half-revolution closed by its flat deck.

Derive, don't invent: geometry comes from the SAME stored fields the 2-D
schematic draws, with the same fallbacks — and every fallback that stood
in for unset data is listed in the emitted script's header and returned
in flags, never silently guessed.  Quantities the model simply does not
store (fin/wing thickness, aerospike stalk ⌀) get thin nominal values,
each one flagged.

Pure module: no Tk, no bpy import here (bpy exists only inside Blender).
The emitted script is plain Python — tests compile() it."""

import math
import os

from booster_schematic import (stage_chain, _stage_top_diameter, fin_polygon,
                               exposed_front_object)

_PROFILE_N = 24        # points per curved nose profile

# The Thrusty mascot as a FULL 3-D scale figure beside the stack, like the
# engineer in the classic V-2 cutaway.  Primary: the sculpted mesh asset
# (assets/thrusty_mesh.obj.gz + thrusty_diffuse.jpg — decimated from the
# user's 2M-triangle master, whose full-resolution source lives in Drive;
# 40k faces, UV-mapped, baked to z-up / facing -Y / 1.8 m / feet on z=0).
# Fallback when the asset is absent: the procedural palette figure from
# thrusty_figure3d (turnaround-sheet build), so a stripped checkout still
# ships a scale figure.
_FIGURE_M = 1.8
_PALETTE = {"white": (0.96, 0.96, 0.94), "black": (0.08, 0.08, 0.08),
            "red": (0.72, 0.18, 0.15)}
_FIGURE_MESH_PATH = os.path.join(os.path.dirname(__file__),
                                 "assets", "thrusty_mesh.obj.gz")
_FIGURE_TEX = "thrusty_diffuse.jpg"     # sidecar name next to OBJ exports
_FIGURE_TEX_PATH = os.path.join(os.path.dirname(__file__),
                                "assets", _FIGURE_TEX)
_figure_mesh_cache = None


def _load_figure_mesh():
    """(verts, uvs, faces) from the baked mesh asset — faces as triples
    of (v_idx, vt_idx) — or None when the asset is absent/unreadable.
    Cached after the first parse (~40k faces)."""
    global _figure_mesh_cache
    if _figure_mesh_cache is None:
        import gzip
        try:
            verts, uvs, faces = [], [], []
            with gzip.open(_FIGURE_MESH_PATH, "rt", encoding="utf-8") as f:
                for line in f:
                    p = line.split()
                    if not p:
                        continue
                    if p[0] == "v":
                        verts.append((float(p[1]), float(p[2]),
                                      float(p[3])))
                    elif p[0] == "vt":
                        uvs.append((float(p[1]), float(p[2])))
                    elif p[0] == "f":
                        faces.append(tuple(
                            (int(a[0]) - 1, int(a[1]) - 1)
                            for a in (tok.split("/") for tok in p[1:4])))
            _figure_mesh_cache = ((verts, uvs, faces)
                                  if verts and faces else False)
        except OSError:
            _figure_mesh_cache = False
    return _figure_mesh_cache or None


from stage_outline import (nose_profile as _nose_profile,   # one source: stage_outline
                           outline as _stage_outline, profile as _outline_profile,
                           strapon_piece as _strapon_piece,
                           NOZZLE_NECK_FRACTION as _NECK)


def _sphere_cone_profile(R, L, rn):
    """The tangent sphere-cone (ro_section.sphere_cone_profile)."""
    import ro_section
    return ro_section.sphere_cone_profile(R, L, rn)


def _f(v, default=0.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v


def vehicle_elements(p):
    """Geometry plan for the export: {'revolves': [(name, profile,
    (x, y, z), sweep)], 'plates': [(name, poly, thickness, (x, y, z),
    rot_z_deg)], 'flags': [...], 'total_height_m': float}.  Same stacking
    rules and fallbacks as booster_schematic.draw_booster."""
    stages = stage_chain(p)
    flags, revolves, plates, meshes = [], [], [], []
    z = 0.0
    finned = strap = grid_finned = None
    shroud_stage = next(
        (s for s in stages
         if (getattr(s, "shroud_length_m", 0.0) or 0.0) > 0.0), None)
    # An uncovered separating object is placed beside the stack, not on it.
    front_obj = exposed_front_object(p)

    stage_bases = []                      # (stage, aft-base z, ⌀) per stage
    for i, s in enumerate(stages):
        d = _f(getattr(s, "diameter_m", 0.0)) or 0.6
        L = _f(getattr(s, "length_m", 0.0)) or 1.0
        stage_bases.append((s, z, d))     # z is this stage's aft base
        if not _f(getattr(s, "diameter_m", 0.0)):
            flags.append(f"S{i+1} diameter unset — 0.6 m used")
        if not _f(getattr(s, "length_m", 0.0)):
            flags.append(f"S{i+1} length unset — 1 m used")
        d_top = _stage_top_diameter(s)
        # The stage's outline beyond a cylinder (stage_outline: the numbers
        # the schematic draws and the spent-stage physics flies).
        _o = _stage_outline(s)
        _prof = [(0.0, 0.0)]
        if _o.skirt_len > 0.0:
            _prof += [(_o.skirt_d / 2, 0.0), (d / 2, _o.skirt_len)]
        else:
            _prof.append((d / 2, 0.0))
            if (_f(getattr(s, "aft_skirt_length_m", 0.0)) > 0
                    or _f(getattr(s, "aft_skirt_diameter_m", 0.0)) > 0):
                flags.append(f"S{i+1} aft skirt incomplete or not wider than "
                             f"the body — not drawn or flown")
        _prof += [(d_top / 2, L), (0.0, L)]
        revolves.append((f"S{i+1}", _prof, (0.0, 0.0, z), "full"))
        if _o.nozzle_len > 0.0:
            _re = _o.nozzle_d / 2
            revolves.append((f"S{i+1}_NozzleCone",
                             [(0.0, -_o.nozzle_len), (_re, -_o.nozzle_len),
                              (_NECK * _re, 0.0), (0.0, 0.0)],
                             (0.0, 0.0, z), "full"))
            if int(getattr(s, "n_nozzles", 1) or 1) > 1:
                flags.append(f"S{i+1} nozzle cluster drawn and flown as one "
                             f"nozzle of the total exit area")
        elif _f(getattr(s, "nozzle_protrusion_m", 0.0)) > 0:
            flags.append(f"S{i+1} nozzle protrusion set but no exit area — "
                         f"not drawn or flown")
        if getattr(s, "has_fins", False) and _f(getattr(s, "fin_span_m", 0.0)) > 0:
            finned = (s, z)
        if getattr(s, "has_grid_fins", False) and int(getattr(s, "n_grid_fins", 0) or 0) > 0:
            grid_finned = (s, z)
        if int(getattr(s, "n_boosters", 0) or 0) > 0:
            strap = (s, z, L)
        z += L
        # a real adapter only when declared; diameters DERIVED, as in 2-D
        if getattr(s, "has_interstage", False) \
                and _f(getattr(s, "interstage_length_m", 0.0)) > 0:
            il = _f(s.interstage_length_m)
            nxt = stages[i + 1] if i + 1 < len(stages) else None
            if nxt is not None:
                d_is_top = _f(getattr(nxt, "diameter_m", 0.0)) or d_top
            elif front_obj is not None:
                d_is_top = _f(front_obj.diameter_m)      # the object's base
            else:
                d_is_top = d_top
            # Hollow adapter: an open frustum tube (no end caps) — it's a
            # shell between two stages, not a solid.  Profile is just the
            # wall, so both ends stay open.
            revolves.append((f"Interstage_{i+1}",
                             [(d_top / 2, 0.0), (d_is_top / 2, il)],
                             (0.0, 0.0, z), "full"))
            z += il

    top = stages[-1]
    top_surface_d = _stage_top_diameter(top)
    if shroud_stage is not None:
        sd = _f(getattr(shroud_stage, "shroud_diameter_m", 0.0)) \
            or top_surface_d
        sl = _f(getattr(shroud_stage, "shroud_length_m", 0.0)) or 2 * sd
        shape = getattr(shroud_stage, "shroud_nose_shape", "") or ""
        nose = _f(getattr(shroud_stage, "shroud_nose_length_m", 0.0))
        if not (0.0 < nose <= sl):
            nose = 0.45 * sl
            flags.append("fairing nose length unset — 0.45×length used")
        if not shape:
            flags.append("fairing nose shape unset — cone used")
        R = sd / 2.0
        cyl = sl - nose
        # No leading (0,0) apex: the fairing is a SHELL sitting on the
        # stack, so its base is OPEN (the stage below is capped).  Start
        # at the base rim (R, 0).
        profile = []
        if cyl > 0:
            profile += [(R, 0.0), (R, cyl)]
        profile += [(r, cyl + zz) for r, zz in
                    _nose_profile(shape or "cone", R, nose)]
        revolves.append(("Fairing", profile, (0.0, 0.0, z), "full"))
        nose_base_d = sd
        z += sl
    elif front_obj is not None:
        # The object is the front end and is exported beside the stack
        # (below); nothing is stacked here, as in the 2-D schematic.
        nose_base_d = _f(front_obj.diameter_m)
    else:
        nd = top_surface_d or 1.0
        shape = getattr(top, "nose_shape", "") or ""
        nl = _f(getattr(top, "nose_length_m", 0.0))
        if nl <= 0.0:
            nl = 1.6 * nd
            flags.append("nose length unset — 1.6×⌀ used")
        if not shape:
            flags.append("nose shape unset — cone used")
        # Open base (shell on the stack): start at the base rim, no cap.
        profile = _nose_profile(shape or "cone", nd / 2, nl)
        revolves.append(("Payload_Nose", profile, (0.0, 0.0, z), "full"))
        nose_base_d = nd
        z += nl

    a_LD = _f(getattr(p, "aerospike_LD", 0.0))
    if a_LD > 0 and front_obj is not None:
        flags.append("aerospike not drawn — it rides the separate "
                     "object's nose")
    elif a_LD > 0:
        L_spike = a_LD * nose_base_d
        r_stalk = 0.015 * nose_base_d
        flags.append("aerospike stalk ⌀ not stored — 0.03×⌀ nominal")
        revolves.append(("Aerospike",
                         [(0.0, 0.0), (r_stalk, 0.0), (r_stalk, L_spike),
                          (0.0, L_spike)],
                         (0.0, 0.0, z), "full"))
        a_dD = _f(getattr(p, "aerospike_dD", 0.0))
        if a_dD > 0:
            disk_d = a_dD * nose_base_d
            t_disk = 0.04 * nose_base_d
            revolves.append(("Aerodisk",
                             [(0.0, 0.0), (disk_d / 2, 0.0),
                              (disk_d / 2, t_disk), (0.0, t_disk)],
                             (0.0, 0.0, z + L_spike - t_disk), "full"))
        z += L_spike

    if finned:
        s, zb = finned
        R = _f(s.diameter_m) / 2.0
        span = _f(s.fin_span_m)
        root = _f(getattr(s, "fin_root_chord_m", 0.0)) or 0.8 * span
        tip = _f(getattr(s, "fin_tip_chord_m", 0.0)) or 0.4 * root
        sweep = _f(getattr(s, "fin_sweep_deg", 0.0))
        t = _f(getattr(s, "fin_thickness_m", 0.0))
        if t <= 0:
            t = max(0.01, 0.02 * span)
            flags.append("fin thickness unset — 0.02×span nominal")
        n_f = int(getattr(s, "n_fins", 0) or 4)
        poly = [(u, zz) for u, zz in
                fin_polygon(+1, R, 0.0, span, root, tip, sweep)]
        for k in range(n_f):
            plates.append((f"Fin_{k+1}", poly, t, (0.0, 0.0, zb),
                           360.0 * k / n_f))

    if grid_finned:
        s, zb = grid_finned
        R = _f(s.diameter_m) / 2.0
        gh = _f(getattr(s, "grid_fin_height_m", 0.0)) or 0.15 * 2 * R  # radial
        gw = _f(getattr(s, "grid_fin_width_m", 0.0)) or gh             # tangent.
        gc = _f(getattr(s, "grid_fin_chord_m", 0.0)) or 0.3 * gh       # stream
        n_g = int(s.n_grid_fins)
        # Solidity σ drives the mesh, LITERALLY: σ→1 a solid panel, σ→0 an
        # empty mesh, between an open lattice with the web thickness that
        # blocks σ.  Web+pitch (if given) set σ from the real geometry;
        # otherwise σ is the stored solidity.  No default — an all-unset
        # grid fin exports empty (a signal to set its solidity).
        sigma = _f(getattr(s, "grid_fin_solidity", 0.0))
        pitch = _f(getattr(s, "grid_fin_cell_pitch_m", 0.0)) \
            or min(gh, gw) / 6.0
        web = _f(getattr(s, "grid_fin_web_thickness_m", 0.0))
        if web > 0:
            from booster_models import grid_fin_solidity as _gfs
            sigma = _gfs(web, pitch)                   # real geometry wins
        elif sigma > 0:
            web = pitch * (1.0 - math.sqrt(max(0.0, 1.0 - sigma)))
        flags.append(f"grid fins: σ={sigma:.2f} "
                     + ("(solid panel)" if sigma >= 0.97
                        else "(empty — set solidity)" if sigma <= 0.01
                        else f"lattice, web {web*1000:.0f} mm / "
                             f"pitch {pitch*1000:.0f} mm"))
        for k in range(n_g):
            a = 2.0 * math.pi * k / n_g
            if sigma >= 0.97:                         # solid panel (disk)
                v, f = _grid_fin_box(a, R, gh, gw, gc, zb)
            elif sigma <= 0.01 or web <= 0:           # empty → nothing
                continue
            else:                                     # open lattice
                v, f = _grid_fin_lattice(a, R, gh, gw, gc, zb, pitch, web)
            meshes.append((f"GridFin_{k+1}", v, f))

    if strap:
        s, zb, Lc = strap
        n_b = int(s.n_boosters)
        # One outline (stage_outline), as in the 2-D schematic and as flown:
        # nothing invented.  No nose entered -> flat front; no length
        # entered -> 2 x diameter.
        piece = _strapon_piece(s)
        _o = _stage_outline(piece) if piece is not None else None
        bd = _o.d if _o is not None else 0.3
        bL = _o.L if _o is not None else 2.0 * bd
        if piece is not None and piece.length_unset:
            flags.append("strap-on length unset — 2 × diameter drawn and flown")
        if _o is not None and _o.nose_len <= 0.0:
            flags.append("strap-on nose (shape and length unset — flat front "
                         "drawn and flown; ascent drag from the entered Cd "
                         f"{_f(getattr(s, 'booster_cd', 0.0)):g})")
        if (_o is not None and _o.nozzle_len <= 0.0
                and _f(getattr(s, "booster_nozzle_protrusion_m", 0.0)) > 0):
            flags.append("strap-on nozzle protrusion set but no exit area — "
                         "not drawn or flown")
        cR = _f(s.diameter_m) / 2.0
        Rb = bd / 2.0
        c_dist = cR + Rb + 0.05
        # revolve profile (r, z up from the base), rear to front
        profile = ([(r, bL - x) for (x, r) in reversed(_outline_profile(piece))]
                   if piece is not None
                   else [(0.0, 0.0), (Rb, 0.0), (Rb, bL), (0.0, bL)])
        # Simple anti-collision rule: when the same stack carries FINS,
        # clock the strap-on ring by half a fin spacing so the boosters
        # sit in the GAPS between fins instead of overlapping them
        # (Strypi: 4 fins at 0/90/180/270 + 2 boosters would land at
        # 0/180 without this → boosters at 45/225 instead).  A modeler
        # can still move them; this just avoids the default clash.
        phase = 0.0
        if finned is not None:
            n_f = max(1, int(getattr(finned[0], "n_fins", 0) or 4))
            phase = math.pi / n_f
            flags.append("strap-ons clocked between fins (half a fin "
                         "spacing) to avoid overlap")
        for k in range(n_b):
            a = phase + 2.0 * math.pi * k / n_b
            revolves.append((f"Strapon_{k+1}", profile,
                             (c_dist * math.cos(a), c_dist * math.sin(a),
                              zb), "full"))

    # Nozzles on EVERY stage's aft base: n_nozzles flat disks, each of radius
    # sqrt(area_each/pi).  Upper-stage nozzles sit inside the stack (hidden),
    # but are drawn and named per stage so a modeler who deletes stage 1
    # still has them — S{i}_Nozzle_{k}.
    for i, (s, base_z, sd) in enumerate(stage_bases, start=1):
        n_noz = max(0, int(getattr(s, "n_nozzles", 1) or 1))
        tot_a = _f(getattr(s, "nozzle_exit_area_m2", 0.0))
        each_a = _f(getattr(s, "nozzle_area_each_m2", 0.0))
        if each_a <= 0 and tot_a > 0 and n_noz > 0:
            each_a = tot_a / n_noz         # total (e.g. Estimate) -> each
        if n_noz <= 0 or each_a <= 0:
            continue
        r_noz = math.sqrt(each_a / math.pi)
        R_base = 0.5 * sd
        disk = [(0.0, 0.0), (r_noz, 0.0)]  # flat filled circle (revolve)
        zb = base_z - 0.005                # a hair aft to avoid z-fighting
        if n_noz == 1:
            revolves.append((f"S{i}_Nozzle_1", disk, (0.0, 0.0, zb), "full"))
            continue
        bolt = min(0.62 * R_base, max(0.0, R_base - r_noz - 0.02))
        if r_noz > R_base or bolt <= 0:
            flags.append(f"S{i} nozzles (⌀{2*r_noz:.2f} m ×{n_noz}) do not "
                         f"fit the ⌀{sd:.2f} m base — drawn overlapping")
            bolt = max(bolt, 0.5 * R_base)
        for k in range(n_noz):
            a = 2.0 * math.pi * k / n_noz
            revolves.append((f"S{i}_Nozzle_{k+1}", disk,
                             (bolt * math.cos(a), bolt * math.sin(a), zb),
                             "full"))

    total = z
    ro = getattr(p, "ro", None)
    ro_x_off = ro_dia = 0.0
    # A body is not drawn beside the stack: it IS the stack's last stage
    # (as in the 2-D schematic), and its object file stores 0 for the size
    # it takes from the booster (FRONT_END_DESIGN.md §18.1).
    if (ro is not None and _f(getattr(ro, "diameter_m", 0.0)) > 0
            and not getattr(p, "body_reenters", False)):
        max_r = max((max(r for r, _ in prof) for _n, prof, _p, _s
                     in revolves), default=1.0)
        ro_dia = _f(ro.diameter_m)
        ro_x_off = max_r + 1.0 + ro_dia
        _ro_elements(ro, ro_x_off, revolves, plates, flags)
        # Same containment check the schematic shows — the export header
        # must not ship a stack whose payload cannot fit without saying so.
        from fairing_fit import fairing_fit, fairing_fit_note
        fit = fairing_fit(p)
        if fit is not None and not fit["fits"]:
            flags.append(fairing_fit_note(fit))

    # Full-stack fuelled CG — a SMALL classic symbol (ring + two opposite
    # filled quadrants) sitting on the body SURFACE at the balance station,
    # facing +X.  Raw pre-tessellated meshes (the "meshes" element type).
    # cg_z is also the origin the export centres on.
    cg_z = None
    try:
        from grid_fin_sizing import estimate_cg
        # Fuelled (liftoff) CG — propellant plus warhead — matching the 2-D
        # schematic.  The burnt-out body's re-entry CG is a different quantity
        # (trim-gate/glide stability) and is not marked on the model.
        x_cg, L_est = estimate_cg(p, fuelled=True)
        cg_z = max(0.0, min(total, L_est - x_cg))     # height from base
        R_local = 0.5 * (_f(getattr(stages[0], "diameter_m", 0.0)) or 0.6)
        for s, bz, sd in stage_bases:                 # radius at the station
            L = _f(getattr(s, "length_m", 0.0)) or 1.0
            if bz <= cg_z <= bz + L:
                R_local = 0.5 * sd
                break
        meshes += cg_marker_meshes(cg_z, R_local)
    except Exception:
        flags.append("CG marker skipped — could not estimate CG")

    # The full-3-D Thrusty on the ground line (stack base), parked beyond
    # everything already placed (fins, strap-ons, the RO) so nothing
    # overlaps — standing beside the stack, V-2-cutaway style.  Primary:
    # the sculpted UV-textured mesh asset; fallback: the procedural
    # palette figure.
    # Stack radial extents (RO excluded — it stands apart) for the V-2
    # scene.  Two numbers on purpose: the missile RESTS on its BODY
    # radius (ext_body — fins dip below the ground plane, exactly like
    # the classic V-2 cutaway, keeping the body low enough that Thrusty
    # shows over it), while Thrusty's standoff behind it must clear the
    # FIN span too (ext_all).
    ext_body = 0.0
    for _n, prof, pos, _s in revolves:
        if not _n.startswith("RO_"):
            ext_body = max(ext_body, math.hypot(pos[0], pos[1])
                           + max(r for r, _z in prof))
    ext = ext_body
    for _n, poly, _t, pos, _r in plates:
        if not _n.startswith("RO_"):
            ext = max(ext, math.hypot(pos[0], pos[1])
                      + max(abs(u) for u, _z in poly))
    # The figure stays CENTRED at the origin here; the writers' scene
    # transform places him (V-2 composition: standing behind the lying
    # missile at mid-length, facing -Y = the missile and the viewer).
    figures, tex_figure, fig_min_y = [], None, -0.3
    mesh = _load_figure_mesh()
    if mesh is not None:
        mverts, muvs, mfaces = mesh
        fig_min_y = min(v[1] for v in mverts)
        tex_figure = ("Thrusty", mverts, muvs, mfaces)
    else:
        try:
            from thrusty_figure3d import build as _fig_build, \
                bounds as _fig_bounds
            fparts = _fig_build(_FIGURE_M)
            (_fx0, fmy, fz0), _hi = _fig_bounds(fparts)
            fig_min_y = fmy
            figures = [(nm, [(x, y, z - fz0) for x, y, z in vs],
                        fs, col) for nm, vs, fs, col in fparts]
            flags.append("Thrusty mesh asset absent — procedural figure "
                         "shipped instead")
        except Exception:
            flags.append("Thrusty figure skipped — thrusty_figure3d failed")

    # V-2 scene parameters, applied by _scene_place in the writers:
    # stack rotated nose-to-+X lying on its widest point, Thrusty
    # upright behind it, the RO lying flat beyond the nose (same
    # nose-to-+X lay-down, resting on its own body radius).
    scene = dict(total=total, lift=ext_body,
                 fig_y=ext + 0.7 - fig_min_y,
                 ro_x_off=ro_x_off, ro_r=0.5 * ro_dia,
                 ro_x0=total + 1.0)
    return dict(revolves=revolves, plates=plates, flags=flags,
                meshes=meshes, figures=figures, tex_figure=tex_figure,
                cg_z=cg_z, total_height_m=total, scene=scene)


def _grid_fin_frame(a, R):
    """Local (u,w,z)->world mapper for a grid fin at clock angle `a`: u is
    radial (0 at the body skin R), w tangential, z the axis."""
    ct, st = math.cos(a), math.sin(a)

    def P(u, w, z):
        r = R + u
        return (r * ct - w * st, r * st + w * ct, z)
    return P


def _box_into(verts, faces, P, u0, u1, w0, w1, z0, z1):
    """Append a (u,w,z) box to shared verts/faces via mapper P."""
    b = len(verts)
    verts.extend([P(u0, w0, z0), P(u1, w0, z0), P(u1, w1, z0), P(u0, w1, z0),
                  P(u0, w0, z1), P(u1, w0, z1), P(u1, w1, z1), P(u0, w1, z1)])
    for fc in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1),
               (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
        faces.append(tuple(b + i for i in fc))


def _grid_fin_box(a, R, gh, gw, gc, z0):
    """A solid grid-fin panel (σ→1): one shallow box, broad face ⟂ flow."""
    P = _grid_fin_frame(a, R)
    verts, faces = [], []
    _box_into(verts, faces, P, 0.0, gh, -gw / 2, gw / 2, z0, z0 + gc)
    return verts, faces


def _grid_fin_lattice(a, R, gh, gw, gc, z0, pitch, web):
    """An open grid-fin lattice (0<σ<1): thin webs of thickness `web`,
    perpendicular spacing `pitch`, running along the two 45° DIAGONALS of
    the panel (the common real orientation — Tochka, Falcon 9 — cells read
    as diamonds), inside a solid outer frame; extruded the chord `gc`,
    broad face ⟂ flow.  Perpendicular web spacing is what the solidity
    formula uses, so σ = 1 − ((p−t)/p)² is orientation-independent.  One
    merged mesh."""
    P = _grid_fin_frame(a, R)
    z1 = z0 + gc
    t = min(web, 0.9 * pitch)
    verts, faces = [], []

    def _prism(poly):                     # extrude a convex (u,w) polygon
        m = len(poly)
        if m < 3:
            return
        b = len(verts)
        for (u, w) in poly:
            verts.append(P(u, w, z0))
        for (u, w) in poly:
            verts.append(P(u, w, z1))
        faces.append(tuple(range(b + m - 1, b - 1, -1)))          # bottom
        faces.append(tuple(range(b + m, b + 2 * m)))              # top
        for k in range(m):
            k2 = (k + 1) % m
            faces.append((b + k, b + k2, b + m + k2, b + m + k))

    u0, u1, w0, w1 = 0.0, gh, -gw / 2.0, gw / 2.0     # panel rectangle

    def _clip_rect(poly):
        """Sutherland–Hodgman clip of a convex polygon to the panel."""
        for axis, lim, keep_ge in ((0, u0, True), (0, u1, False),
                                   (1, w0, True), (1, w1, False)):
            out = []
            for i, cur in enumerate(poly):
                prev = poly[i - 1]

                def _in(pt):
                    return (pt[axis] >= lim - 1e-12 if keep_ge
                            else pt[axis] <= lim + 1e-12)

                def _ix(p, q):
                    d = q[axis] - p[axis]
                    f = 0.0 if abs(d) < 1e-15 else (lim - p[axis]) / d
                    return (p[0] + f * (q[0] - p[0]),
                            p[1] + f * (q[1] - p[1]))
                if _in(cur):
                    if not _in(prev):
                        out.append(_ix(prev, cur))
                    out.append(cur)
                elif _in(prev):
                    out.append(_ix(prev, cur))
            poly = out
            if not poly:
                return []
        return poly

    s2 = math.sqrt(0.5)
    cu, cw = 0.5 * (u0 + u1), 0.5 * (w0 + w1)         # lattice centre
    L = gh + gw                                       # covers the panel
    corners = [(u0, w0), (u1, w0), (u1, w1), (u0, w1)]
    for dx, dy in ((s2, s2), (-s2, s2)):              # two diagonal families
        nx, ny = -dy, dx                              # strip normal
        off_max = max(abs((x - cu) * nx + (y - cw) * ny) for x, y in corners)
        for i in range(-int(off_max / pitch) - 1, int(off_max / pitch) + 2):
            c = i * pitch
            bu, bw = cu + c * nx, cw + c * ny
            strip = [(bu - L * dx - t / 2 * nx, bw - L * dy - t / 2 * ny),
                     (bu + L * dx - t / 2 * nx, bw + L * dy - t / 2 * ny),
                     (bu + L * dx + t / 2 * nx, bw + L * dy + t / 2 * ny),
                     (bu - L * dx + t / 2 * nx, bw - L * dy + t / 2 * ny)]
            _prism(_clip_rect(strip))
    ft = max(t, 0.5 * pitch * (1.0 - math.sqrt(0.5)))  # solid outer frame
    for (a0, a1, b0, b1) in ((u0, u1, w0, w0 + ft), (u0, u1, w1 - ft, w1),
                             (u0, u0 + ft, w0, w1), (u1 - ft, u1, w0, w1)):
        _prism([(a0, b0), (a1, b0), (a1, b1), (a0, b1)])
    return verts, faces


def cg_marker_meshes(z_cg, r_body, name="CG_fuelled", n=24):
    """The classic CG symbol as a SMALL badge on the body surface: a thin
    ring plus two OPPOSITE filled quadrant wedges in the X-Z plane,
    centred just proud of the skin at (0, -(r_body+0.01), z_cg) — the
    -Y side, which the V-2-style scene rotation keeps facing the viewer.
    Returns [(name, verts, faces), ...]."""
    r = max(0.05, 0.35 * r_body)                      # small, ~⅓ body radius
    y0 = -(r_body + 0.01)                             # a hair proud of skin
    ri = 0.86 * r
    out = []
    outer, inner, rf = [], [], []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        outer.append((r * math.cos(a), y0, z_cg + r * math.sin(a)))
        inner.append((ri * math.cos(a), y0, z_cg + ri * math.sin(a)))
    for i in range(n):
        j = (i + 1) % n
        rf.append((i, j, n + j, n + i))
    out.append((f"{name}_ring", outer + inner, rf))
    for qi, a0 in ((1, 0.0), (3, math.pi)):           # opposite quadrants
        verts = [(0.0, y0, z_cg)]
        m = 6
        for k in range(m + 1):
            a = a0 + (math.pi / 2.0) * k / m
            verts.append((r * math.cos(a), y0, z_cg + r * math.sin(a)))
        faces = [(0, k, k + 1) for k in range(1, m + 1)]
        out.append((f"{name}_fill{qi}", verts, faces))
    return out


def _ro_elements(ro, x_off, revolves, plates, flags):
    """The reentry object beside the stack (base on z=0, like the 2-D
    schematic's corner drawing), from its own stored geometry."""
    D = _f(ro.diameter_m)
    L = _f(getattr(ro, "length_m", 0.0))
    if L <= 0:
        L = 1.6 * D
        flags.append("RO length unset — 1.6×⌀ used")
    rn = _f(getattr(ro, "nose_radius_m", 0.0))
    R = D / 2.0
    form = str(getattr(ro, "body_form", "") or "axisymmetric")
    if form not in ("wedge", "half_cone"):
        form = "axisymmetric"
    pos = (x_off, 0.0, 0.0)
    import ro_section
    if form != "axisymmetric" and ro_section.wall_layers(ro):
        flags.append(ro_section.LIFTING_NOT_SECTIONED)

    if form == "wedge":
        span = _f(getattr(ro, "body_span_m", 0.0))
        if span <= 0:
            span = D
            flags.append("wedge span unset — depth used as span (flagged)")
        h = D / 2.0                       # stored ⌀ IS the base depth
        plates.append(("RO_Body", [(-h, 0.0), (h, 0.0), (-h, L)],
                       span, pos, 0.0))
        return
    if form == "half_cone":
        # half-revolution of the cone, closed by its flat deck (the cut
        # is the diametral plane)
        revolves.append(("RO_Body", [(0.0, 0.0), (R, 0.0), (0.0, L)],
                        pos, "half"))
        return

    # The outline and the wall layers from ro_section, the module the
    # schematic and the cross-section draw from: what is drawn is exported.
    sec = ro_section.section(ro)
    profile = sec["outline"]
    flags.extend(f for f in sec["flags"] if f not in flags)
    bic = None
    if getattr(ro, "biconic", False):
        Lf = _f(getattr(ro, "fore_length_m", 0.0))
        Dbrk = _f(getattr(ro, "break_diameter_m", 0.0))
        if 0 < Lf < L and 0 < Dbrk < D:
            bic = (Lf, Dbrk)
    if not sec["pieces"]:
        revolves.append(("RO_Body", profile, pos, "full"))
    else:
        # One closed piece per region, outside in; RO_Body is the body's
        # outer layer, RO_Nose_<material> the nose tip (shell or plug) ahead
        # of the joint, RO_Interior the space left inside — each separate,
        # so it can be shown or hidden.
        k = 1
        for pc in sec["pieces"]:
            if pc["kind"] == "nose":
                name = f"RO_Nose_{pc['material']}"
            elif pc["kind"] == "interior":
                name = "RO_Interior"
            elif k == 1:
                name = "RO_Body"
            else:
                name = f"RO_Layer_{k}_{pc['material']}"
            if pc["kind"] == "layer":
                k += 1
            revolves.append((name, pc["profile"], pos, "full"))
        wall = [f"{lay['thickness_m'] * 100:.1f} cm {lay['label']}"
                for lay in sec["layers"]]
        if wall:
            flags.append("RO wall: " + " · ".join(wall))
        if sec["nose"]:
            nz = sec["nose"]
            nlab = next(pc["label"] for pc in sec["pieces"]
                        if pc["kind"] == "nose")
            flags.append(
                f"RO nose: {nlab}, "
                + (f"solid {nz['extent_m'] * 100:.1f} cm"
                   if nz["kind"] == "solid" else
                   f"{nz['thickness_m'] * 100:.1f} cm shell back "
                   f"{nz['extent_m'] * 100:.1f} cm")
                + " from the tip")

    # faithful wing panels only from a stored planform (same rule as 2-D)
    w_rc = _f(getattr(ro, "wing_root_chord_m", 0.0))
    w_ss = _f(getattr(ro, "wing_span_exposed_m", 0.0))
    if w_rc > 0 and w_ss > 0:
        w_sw = _f(getattr(ro, "wing_sweep_deg", 0.0))

        def r_local(zz):
            if bic is not None:
                Lf, Dbrk = bic
                La, R1 = L - Lf, Dbrk / 2.0
                if zz <= La:
                    return R - zz * (R - R1) / La
                return max(0.0, R1 * (1.0 - (zz - La) / Lf))
            return max(0.0, R * (1.0 - zz / L))
        y_tip = min(max(w_rc - w_ss * math.tan(math.radians(w_sw)), 0.0),
                    w_rc)
        # Honor the RO's stored wing_thickness_m; nominal only when unset.
        t = _f(getattr(ro, "wing_thickness_m", 0.0))
        if t <= 0:
            t = max(0.01, 0.02 * w_ss)
            flags.append("RO wing thickness unset — 0.02×span nominal")
        poly = [(r_local(0.0), 0.0), (r_local(w_rc), w_rc),
                (r_local(0.0) + w_ss, y_tip), (r_local(0.0) + w_ss, 0.0)]
        # Panel count from the RO's stored n_wings (default 4) — a C-HGB
        # carries 4 flaps, not a 2-panel wing; distribute them evenly
        # around the body like the booster fins (was hardcoded to 2).
        n_w = max(2, int(getattr(ro, "n_wings", 4) or 4))
        flags.append(f"RO wings: {n_w} panels (n_wings)")
        for k in range(n_w):
            plates.append((f"RO_Wing_{k+1}", poly, t, pos, 360.0 * k / n_w))


_SEG = 48                    # revolve segments (matches the emitted script)


def revolve_mesh(profile, pos, sweep_rad, seg=_SEG):
    """Tessellate an (r, z) profile revolved about local +Z at pos into
    (verts, faces) — 0-indexed.  The Python twin of the emitted script's
    _revolve, so the OBJ file and the in-Blender build are the same solid.
    r≈0 points become single apex vertices; a partial sweep (half-cone) is
    closed with a flat deck n-gon."""
    full = abs(sweep_rad - 2 * math.pi) < 1e-9
    S = seg if full else seg // 2
    cols = S if full else S + 1
    verts, rings = [], []
    for r, z in profile:
        if r < 1e-9:
            rings.append((len(verts),))
            verts.append((pos[0], pos[1], pos[2] + z))
        else:
            idx = []
            for k in range(cols):
                a = sweep_rad * k / S
                idx.append(len(verts))
                verts.append((pos[0] + r * math.cos(a),
                              pos[1] + r * math.sin(a), pos[2] + z))
            rings.append(tuple(idx))
    faces = []
    for j in range(len(rings) - 1):
        a, b = rings[j], rings[j + 1]
        if len(a) == 1 and len(b) == 1:
            continue
        for k in range(S):
            k2 = (k + 1) % S if full else k + 1
            if len(a) == 1:
                faces.append((a[0], b[k2], b[k]))
            elif len(b) == 1:
                faces.append((a[k], a[k2], b[0]))
            else:
                faces.append((a[k], a[k2], b[k2], b[k]))
    if not full:
        edge = [rr[0] for rr in rings] + [rr[-1] for rr in reversed(rings)]
        deck, seen = [], set()
        for i in edge:
            if i not in seen:
                seen.add(i)
                deck.append(i)
        if len(deck) >= 3:
            faces.append(tuple(deck))
    return verts, faces


def plate_mesh(poly, thickness, pos, rot_z_deg):
    """Tessellate a flat plate — 2-D polygon (u, z) extruded ±thickness/2 in
    v, rotated about +Z, placed at pos — into (verts, faces).  Twin of the
    emitted _plate."""
    t = thickness / 2.0
    a = math.radians(rot_z_deg)
    ca, sa = math.cos(a), math.sin(a)
    n = len(poly)
    verts = []
    for v in (-t, +t):
        for (u, z) in poly:
            verts.append((pos[0] + u * ca - v * sa,
                          pos[1] + u * sa + v * ca, pos[2] + z))
    faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    for k in range(n):
        k2 = (k + 1) % n
        faces.append((k, k2, n + k2, n + k))
    return verts, faces


def _center_shift(els):
    """The along-axis shift that puts the fuelled CG on the origin — cg_z
    when it was computed, else the geometric midpoint as a fallback."""
    cg = els.get("cg_z")
    return cg if cg is not None else 0.5 * els["total_height_m"]


def _scene_place(name, verts, sc, zc):
    """The V-2 composition (user decision 2026-08-17), ONE transform both
    writers share: the STACK (built nose-up along +Z) is laid down nose
    to +X, resting on its widest point at z=0, balance station (zc) at
    x=0; Thrusty stands UPRIGHT behind it (+Y side, facing -Y = the
    missile and the viewer) at mid-length; the RO is laid down the same
    way, flat beyond the nose, resting on its own body radius.  Scene
    coordinates are +Z-up; the OBJ writer re-axes them so Blender's
    DEFAULT import reproduces this scene."""
    if name == "Thrusty" or name.startswith("Thrusty_"):
        dx = sc["total"] / 2.0 - zc
        return [(x + dx, y + sc["fig_y"], z) for x, y, z in verts]
    if name.startswith("RO_"):
        # Built nose-up at x = ro_x_off; laid nose-to-+X starting 1 m
        # beyond the stack nose, on the ground at its body radius.
        return [(z + sc["ro_x0"] - zc, y,
                 sc["ro_r"] - (x - sc["ro_x_off"])) for x, y, z in verts]
    return [(z - zc, y, sc["lift"] - x) for x, y, z in verts]


def scene_meshes(els, zc):
    """Every export object, tessellated AND placed in the final V-2
    scene — ONE generator both writers consume, so OBJ and bpy can never
    disagree.  Yields (name, verts, faces, (kind, extra)): kind 'plain'
    (extra None), 'palette' (extra colour name), or 'textured' (extra =
    uv list; faces are then per-corner (v_idx, vt_idx) triples)."""
    sc = els["scene"]
    for name, prof, pos, sweep in els["revolves"]:
        verts, faces = revolve_mesh(
            prof, pos, math.pi if sweep == "half" else 2 * math.pi)
        yield name, _scene_place(name, verts, sc, zc), faces, ("plain", None)
    for name, poly, t, pos, rot in els["plates"]:
        verts, faces = plate_mesh(poly, t, pos, rot)
        yield name, _scene_place(name, verts, sc, zc), faces, ("plain", None)
    for name, verts, faces in els.get("meshes", []):
        yield name, _scene_place(name, verts, sc, zc), faces, ("plain", None)
    for name, verts, faces, colour in els.get("figures", []):
        yield (name, _scene_place(name, verts, sc, zc), faces,
               ("palette", colour))
    if els.get("tex_figure"):
        name, verts, uvs, faces = els["tex_figure"]
        yield (name, _scene_place(name, verts, sc, zc), faces,
               ("textured", uvs))


def obj_export(p, title="vehicle", center=True,
               mtl_name="thrusty_figure.mtl"):
    """A Wavefront OBJ of the vehicle — the format Blender opens DIRECTLY
    (File -> Import -> Wavefront .obj, DEFAULT settings).  The file is
    authored in the OBJ convention (Y up, -Z forward): scene (x,y,z)
    with +Z up is written as (x, z, -y), so Blender's default importer —
    which maps file (x,y,z) to world (x,-z,y) — reproduces the composed
    scene exactly.  Each element is its own named `o` group.  Metres.
    The scene is the V-2 cutaway composition: missile lying nose to +X
    on the ground plane, Thrusty standing behind it, the RO lying flat
    beyond the nose.  center=True puts the fuelled CG at x=0;
    center=False keeps the base at x=0.  Returns (obj_text, info)."""
    els = vehicle_elements(p)
    zc = _center_shift(els) if center else 0.0
    lines = [f"# Thrusty rough-draft 3-D export — {title}",
             "# Wavefront OBJ.  Blender: File -> Import -> Wavefront "
             "(.obj) — DEFAULT settings.",
             "# Authored Y-up per the OBJ convention; the default import "
             "lands it +Z up.",
             "# Units: metres.  V-2 composition: missile lying nose "
             "to +X,",
             "# Thrusty standing behind it, RO lying beyond the nose.  "
             "One object per element.",
             f"# Balance station (fuelled CG) at "
             f"{'x=0' if center else 'x = +CG station (base at x=0)'}."]
    for fl in els["flags"]:
        lines.append(f"# fallback: {fl}")
    if els.get("figures") or els.get("tex_figure"):
        lines.append(f"mtllib {mtl_name}")
    base = 1                                   # OBJ vertices are 1-indexed
    n = 0
    for name, verts, faces, (kind, extra) in scene_meshes(els, zc):
        n += 1
        lines.append(f"o {name}")
        for x, y, z in verts:                  # scene +Z-up -> file Y-up
            lines.append(f"v {x:.5f} {z:.5f} {-y:.5f}")
        if kind == "textured":
            for u, v in extra:
                lines.append(f"vt {u:.5f} {v:.5f}")
            lines.append("usemtl Thrusty_skin")
            for tri in faces:
                lines.append("f " + " ".join(f"{vi + base}/{ti + 1}"
                                             for vi, ti in tri))
        else:
            if kind == "palette":
                lines.append(f"usemtl Thrusty_{extra}")
            for f in faces:
                lines.append("f " + " ".join(str(i + base) for i in f))
        base += len(verts)
    return "\n".join(lines) + "\n", dict(
        n_objects=n, flags=list(els["flags"]),
        total_height_m=els["total_height_m"])


def figure_mtl():
    """The .mtl sidecar for the 3-D Thrusty: the textured skin material
    for the sculpted mesh (map_Kd → the diffuse JPEG shipped beside the
    OBJ) plus the three flat palette colours the procedural fallback
    figure references."""
    out = ["# Thrusty figure materials",
           "newmtl Thrusty_skin",
           "Ka 0.000 0.000 0.000",
           "Kd 1.000 1.000 1.000",
           "Ks 0.000 0.000 0.000",
           "d 1.0",
           "illum 1",
           f"map_Kd {_FIGURE_TEX}"]
    for name, (r, g, b) in _PALETTE.items():
        out += [f"newmtl Thrusty_{name}",
                "Ka 0.000 0.000 0.000",
                f"Kd {r:.3f} {g:.3f} {b:.3f}",
                "Ks 0.000 0.000 0.000",
                "d 1.0",
                "illum 1"]
    return "\n".join(out) + "\n"


def copy_figure_texture(dirname):
    """Copy the Thrusty diffuse JPEG beside an export (the .py script
    path needs it too).  Returns the written path, or None when the
    mesh asset isn't shipped."""
    import shutil
    if not os.path.exists(_FIGURE_TEX_PATH):
        return None
    dst = os.path.join(dirname or ".", _FIGURE_TEX)
    shutil.copyfile(_FIGURE_TEX_PATH, dst)
    return dst


def write_obj_bundle(path, p, title="vehicle", center=True):
    """Write the OBJ to `path` plus the sidecars the 3-D Thrusty needs
    (<name>.mtl, and the diffuse texture when the sculpted figure is
    shipped — OBJ cannot embed images), in the same directory.  Returns
    the obj_export info dict with a 'files' list added."""
    import shutil
    stem = os.path.splitext(os.path.basename(path))[0]
    mtl_name = stem + ".mtl"
    text, info = obj_export(p, title=title, center=center,
                            mtl_name=mtl_name)
    with open(path, "w") as f:
        f.write(text)
    files = [path]
    if f"mtllib {mtl_name}" in text:
        mtl_path = os.path.join(os.path.dirname(path) or ".", mtl_name)
        with open(mtl_path, "w") as f:
            f.write(figure_mtl())
        files.append(mtl_path)
    if "usemtl Thrusty_skin" in text and os.path.exists(_FIGURE_TEX_PATH):
        tex_path = os.path.join(os.path.dirname(path) or ".", _FIGURE_TEX)
        shutil.copyfile(_FIGURE_TEX_PATH, tex_path)
        files.append(tex_path)
    info["files"] = files
    return info


def _fmt_pts(pts):
    return "[" + ", ".join(f"({r:.6g}, {zz:.6g})" for r, zz in pts) + "]"


def _fmt_pos(pos, zc=0.0):
    return f"({pos[0]:.6g}, {pos[1]:.6g}, {pos[2] - zc:.6g})"


def bpy_script(p, title="vehicle", center=True):
    """The emitted Blender script (string) + a summary dict
    {'n_objects': int, 'flags': [...], 'total_height_m': float}.
    center=True (default) puts the fuelled CG at the origin — same
    convention as obj_export — so the built stack balances about it."""
    import datetime
    els = vehicle_elements(p)
    zc = _center_shift(els) if center else 0.0
    coll = title.strip() or "vehicle"
    flag_lines = ("".join(f"#   - {fl}\n" for fl in els["flags"])
                  or "#   (none — every dimension came from stored data)\n")

    def _fmt_verts(vs):
        return "[" + ", ".join(f"({x:.5f}, {y:.5f}, {z:.5f})"
                               for x, y, z in vs) + "]"

    def _fmt_faces(fs):
        return "[" + ", ".join("(" + ", ".join(str(i) for i in f) + ")"
                               for f in fs) + "]"
    mesh_lines, fig_lines, tex_fig_literal, n = "", "", "None", 0
    for name, verts, faces, (kind, extra) in scene_meshes(els, zc):
        n += 1
        if kind == "plain":
            mesh_lines += (f"    ({name!r}, {_fmt_verts(verts)}, "
                           f"{_fmt_faces(faces)}),\n")
        elif kind == "palette":
            fig_lines += (f"    ({name!r}, {_fmt_verts(verts)}, "
                          f"{_fmt_faces(faces)}, {extra!r}),\n")
        else:
            tex_fig_literal = (
                f"({name!r}, {_fmt_verts(verts)}, ["
                + ", ".join(f"({u:.5f}, {v:.5f})" for u, v in extra)
                + "], ["
                + ", ".join("(" + ", ".join(f"({vi}, {ti})"
                                            for vi, ti in tri)
                            + ")" for tri in faces) + "])")
    header = (
        f"# Thrusty rough-draft 3-D export — {coll}\n"
        f"# Generated {datetime.date.today().isoformat()}.  Run inside "
        "Blender: Scripting tab -> Open -> Run Script.\n"
        "# Units: metres, +Z up.  V-2 composition: missile lying nose to "
        "+X,\n# Thrusty standing behind it, the RO lying beyond the nose."
        "  Each "
        "element is a\n"
        f"# separate named, editable object in the {coll!r} collection.\n"
        "# Derive-don't-invent: only stored geometry is exported.\n"
        "# Fallbacks that stood in for unset data:\n" + flag_lines)
    body = '''
import bpy
import math

SEG = 48                     # revolve segments (mirror of blender_export._SEG)


def _mesh_obj(name, verts, faces, coll):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


_fig_mats = {}


def _figure_mesh(name, verts, faces, colour, coll):
    """One part of the 3-D Thrusty mascot: plain mesh plus a shared flat
    palette material.  Geometry always builds; the material is
    best-effort (viewport colour only — swap freely)."""
    obj = _mesh_obj(name, verts, faces, coll)
    try:
        mat = _fig_mats.get(colour)
        if mat is None:
            mat = bpy.data.materials.new("Thrusty_" + colour)
            mat.diffuse_color = PALETTE[colour] + (1.0,)
            _fig_mats[colour] = mat
        obj.data.materials.append(mat)
    except Exception as exc:
        print("Thrusty palette material not applied (%s)" % exc)
    return obj


def _tex_figure(name, verts, uvs, faces, coll):
    """The sculpted Thrusty: mesh always builds; the UV layer and the
    diffuse texture (FIGURE_JPG sidecar next to this script) are
    best-effort — a missing image leaves a plain grey figure."""
    obj = _mesh_obj(name, verts, [tuple(vi for vi, _t in tri)
                                  for tri in faces], coll)
    try:
        import os
        uvl = obj.data.uv_layers.new(name="UVMap")
        _loop = 0
        for tri in faces:
            for _vi, ti in tri:
                uvl.data[_loop].uv = uvs[ti]
                _loop += 1
        try:
            base = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base = os.getcwd()
        img = bpy.data.images.load(os.path.join(base, FIGURE_JPG))
        mat = bpy.data.materials.new(name + "_skin")
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(bsdf.inputs["Base Color"], tex.outputs["Color"])
        obj.data.materials.append(mat)
    except Exception as exc:
        print("Thrusty texture not applied (%s) — plain mesh kept" % exc)
    return obj


coll = bpy.data.collections.new(COLLECTION)
bpy.context.scene.collection.children.link(coll)
for _name, _verts, _faces in MESHES:      # every stack element, placed
    _mesh_obj(_name, _verts, _faces, coll)
for _name, _verts, _faces, _col in FIGURES:   # procedural fallback figure
    _figure_mesh(_name, _verts, _faces, _col, coll)
if TEXFIG is not None:                    # the sculpted Thrusty mascot
    _tex_figure(TEXFIG[0], TEXFIG[1], TEXFIG[2], TEXFIG[3], coll)
print("Thrusty export: %d objects in %r"
      % (len(MESHES) + len(FIGURES) + (1 if TEXFIG is not None else 0),
         COLLECTION))
'''
    data = (f"\nCOLLECTION = {coll!r}\n"
            f"PALETTE = {_PALETTE!r}\n"
            f"FIGURE_JPG = {_FIGURE_TEX!r}\n\n"
            f"MESHES = [\n{mesh_lines}]\n\n"
            f"FIGURES = [\n{fig_lines}]\n\n"
            f"TEXFIG = {tex_fig_literal}\n")
    script = header + data + body
    return script, dict(n_objects=n, flags=list(els["flags"]),
                        total_height_m=els["total_height_m"])
