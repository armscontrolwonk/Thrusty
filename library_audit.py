"""Inventory of the vehicle libraries: what each file stores, what a run
actually uses, and what the file says about where its numbers came from
(LIBRARY_RESET_PLAN.md, Phase 0).

The four libraries (boosters, reentry objects, flight plans, reentry plans)
are presented to a user as models.  This module reports on them without
changing them, so a person can judge each file:

  * every stored value that differs from the dataclass default;
  * provenance: the `source` and `notes` text, and words in it that suggest
    a value was chosen to make a run work;
  * what is flown: which drag source the ascent really uses (a nose-shape
    model, a table stored in the file, or the built-in table), whether the
    stage masses add up, whether the vehicle flies at all;
  * what the two audit views say: the fallback flags raised by the
    schematic and the 3-D export.

It asserts nothing about whether a number is right.  It only makes visible
what is there.

Run as a script to write the report:

    python library_audit.py > LIBRARY_INVENTORY.md

The user library paths are blanked first, so only the files in the
repository are read (CLAUDE.md, "Tests read only what is committed").
"""

from __future__ import annotations

import dataclasses as dc
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# Words in a file's own notes that suggest a value was chosen for its effect
# on a run and not taken from a source.
_FITTING = re.compile(
    r"\b(trajectory fit|fitted|fit to|pinned|tuned|calibrated to|held at|"
    r"to match|chosen to|so the run|breaks the|stops? gliding|placeholder|"
    r"assumed|guess(?:ed)?|nominal|approximate(?:ly)?|estimate[ds]?)\b", re.I)

_EMPTY = (None, '', 0, 0.0, [], (), False)


def _defaults(cls):
    out = {}
    for f in dc.fields(cls):
        if f.default is not dc.MISSING:
            out[f.name] = f.default
        elif f.default_factory is not dc.MISSING:
            out[f.name] = f.default_factory()
    return out


def stored_values(d: dict, cls, skip=()):
    """{key: value} for every key of `d` whose value differs from the
    dataclass default (or that the dataclass does not know).  Nested dicts
    and the keys in `skip` are left out."""
    defs = _defaults(cls)
    out = {}
    for k, v in d.items():
        if k in skip or isinstance(v, dict):
            continue
        if k not in defs:
            if v not in _EMPTY:
                out[k] = v
            continue
        dv = defs[k]
        if isinstance(v, (list, tuple)) and list(v) == list(dv or []):
            continue
        if v == dv or (v in _EMPTY and dv in _EMPTY):
            continue
        out[k] = v
    return out


def fitting_words(text: str):
    """Sorted distinct words or phrases in `text` that suggest a fitted,
    assumed or estimated value."""
    return sorted({m.group(1).lower() for m in _FITTING.finditer(text or '')})


def provenance(d: dict):
    src, notes = (d.get('source') or '').strip(), (d.get('notes') or '').strip()
    return dict(source=src, notes_chars=len(notes),
                flags=fitting_words(src + ' ' + notes))


def stage_dicts(d: dict):
    out, s = [], d
    while s:
        out.append(s)
        s = s.get('stage2')
    return out


def mass_residuals(d: dict):
    """Per stage: what is left of its launch mass after the stages above,
    the fairing, its propellant and its burnout mass are taken away.  Zero
    for a lower stage whose numbers add up; on the last stage it is the
    payload the file carries inside the stack, if any."""
    stages = stage_dicts(d)
    out = []
    for i, s in enumerate(stages):
        above = stages[i + 1].get('mass_initial', 0.0) if i + 1 < len(stages) else 0.0
        shroud = d.get('shroud_mass_kg', 0.0) if i == 0 else 0.0
        out.append(float(s.get('mass_initial', 0.0)) - above - shroud
                   - float(s.get('mass_propellant', 0.0))
                   - float(s.get('mass_final', 0.0)))
    return out


def flown_drag_sources(params, lat=33.0, lon=44.0, az=60.0):
    """Share of ascent drag evaluations by source, from one run:
    {'nose model (cone)': 0.56, 'table stored in the file': 0.44, ...}, or
    {'error': '...'} when the vehicle does not fly."""
    import booster_models as bm
    import trajectory as tr
    count = {}
    nose, table = bm._cd_nose_shape, bm.drag_coefficient

    def _nose(shape, *a, **k):
        key = f"nose model ({shape or 'unset'})"
        count[key] = count.get(key, 0) + 1
        return nose(shape, *a, **k)

    def _table(p, mach):
        key = ('table stored in the file' if p.mach_table
               else 'built-in Forden table')
        count[key] = count.get(key, 0) + 1
        return table(p, mach)

    bm._cd_nose_shape, bm.drag_coefficient = _nose, _table
    try:
        result = tr.integrate_trajectory(params, lat, lon, az)
    except Exception as exc:
        return {'error': f"{type(exc).__name__}: {str(exc)[:90]}"}
    finally:
        bm._cd_nose_shape, bm.drag_coefficient = nose, table
    total = sum(count.values()) or 1
    out = {k: v / total for k, v in count.items()}
    out['_range_km'] = result.get('range_km')
    return out


def view_flags(params):
    """(schematic flags, 3-D export flags) for the vehicle as composed."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import blender_export
    import booster_schematic
    fig, ax = plt.subplots()
    try:
        flags2d = list(booster_schematic.draw_booster(ax, params)['flags'])
    except Exception as exc:
        flags2d = [f"schematic failed: {exc}"]
    plt.close(fig)
    try:
        flags3d = list(blender_export.vehicle_elements(params)['flags'])
    except Exception as exc:
        flags3d = [f"3-D export failed: {exc}"]
    return flags2d, flags3d


def audit_booster(path: str, fly: bool = True):
    import booster_models as bm
    d = json.load(open(path))
    stages = stage_dicts(d)
    out = dict(
        file=os.path.basename(path), name=d.get('name', ''),
        provenance=provenance(d),
        stages=[stored_values(s, bm.BoosterParams,
                              skip=('name', 'source', 'notes', 'stage2',
                                    'mass_initial', 'mass_propellant',
                                    'mass_final', 'diameter_m', 'length_m',
                                    'burn_time_s', 'isp_s'))
                for s in stages],
        basics=[{k: s.get(k) for k in ('mass_initial', 'mass_propellant',
                                       'mass_final', 'diameter_m', 'length_m',
                                       'burn_time_s', 'isp_s')} for s in stages],
        mass_residuals=mass_residuals(d),
        stage_names=[s.get('name', '') for s in stages])
    if fly:
        params = bm.get_booster(out['name'])
        out['drag'] = flown_drag_sources(params)
        out['flags_2d'], out['flags_3d'] = view_flags(bm.get_booster(out['name']))
    return out


def audit_plain(path: str, cls=None):
    d = json.load(open(path))
    skip = ('name', 'source', 'notes', 'stages')
    stored = (stored_values(d, cls, skip=skip) if cls is not None else
              {k: v for k, v in d.items()
               if k not in skip and not isinstance(v, dict) and v not in _EMPTY})
    return dict(file=os.path.basename(path), name=d.get('name', ''),
                provenance=provenance(d), stored=stored,
                stages=d.get('stages'))


# ── the report ──────────────────────────────────────────────────────────────

def _short(v, n=70):
    s = json.dumps(v, default=str)
    return s if len(s) <= n else s[:n - 1] + '…'


def _prov_cell(p):
    bits = ['source: ' + (_short(p['source'], 60) if p['source'] else '**none**'),
            f"notes: {p['notes_chars']} characters" if p['notes_chars'] else 'notes: **none**']
    if p['flags']:
        bits.append('words to check: ' + ', '.join(p['flags']))
    return '; '.join(bits)


def report(root: str = HERE) -> str:
    import booster_models as bm
    bm.USER_FLIGHT_PLAN_DIRS, bm.USER_REENTRY_PLAN_DIRS, bm.USER_RO_DIRS = [], [], []
    bm.load_booster_library()
    L = ["# Library inventory",
         "",
         "Generated by `python library_audit.py > LIBRARY_INVENTORY.md`; do "
         "not edit by hand. It lists what each shipped file stores, what a "
         "run uses, and what the file says about its sources. It does not "
         "say whether any number is right. See `LIBRARY_RESET_PLAN.md`.",
         "",
         "Reference flight for the \"flown\" columns: launch 33°N 44°E, "
         "azimuth 60°, the file's own flight plan.",
         ""]
    boosters = [audit_booster(p) for p in
                sorted(glob.glob(os.path.join(root, 'booster_library', '*.booster.json')))]
    L += ["## Boosters at a glance", "",
          "| Vehicle | Stages | Source | Notes | Ascent drag actually flown | Audit-view flags | Masses add up |",
          "|---|---|---|---|---|---|---|"]
    for b in boosters:
        drag = b['drag']
        if 'error' in drag:
            dcell = '**does not fly**: ' + drag['error']
        else:
            dcell = '; '.join(f"{k} {100 * v:.0f}%" for k, v in
                              sorted(((k, v) for k, v in drag.items() if not k.startswith('_')),
                                     key=lambda kv: -kv[1]) if v >= 0.005)
        lower = b['mass_residuals'][:-1]
        mcell = ('yes' if all(abs(r) < 0.5 for r in lower) else
                 'NO: ' + ', '.join(f"{r:+.0f} kg" for r in lower))
        if abs(b['mass_residuals'][-1]) >= 0.5:
            mcell += f"; last stage carries {b['mass_residuals'][-1]:+.0f} kg beyond propellant and burnout mass"
        p = b['provenance']
        L.append(f"| {b['name']} | {len(b['stages'])} | "
                 f"{'yes' if p['source'] else '**none**'} | "
                 f"{p['notes_chars'] or '**none**'} | {dcell} | "
                 f"{len(b['flags_2d'])} schematic, {len(b['flags_3d'])} 3-D | {mcell} |")
    L.append("")
    for b in boosters:
        L += [f"## Booster: {b['name']}", "", f"File `{b['file']}`. {_prov_cell(b['provenance'])}.", ""]
        for i, (basics, stored) in enumerate(zip(b['basics'], b['stages']), start=1):
            L.append(f"**Stage {i}** ({b['stage_names'][i - 1]}): " +
                     ', '.join(f"{k} {v:g}" for k, v in basics.items() if v is not None))
            L.append("")
            if stored:
                L += ["| Stored value (not the default) | |", "|---|---|"]
                L += [f"| `{k}` | {_short(v)} |" for k, v in stored.items()]
            else:
                L.append("No other stored value differs from the default.")
            L.append("")
        if b['flags_2d'] or b['flags_3d']:
            L.append("Flags raised by the audit views (a fallback was drawn, or something was not drawn or flown):")
            L += [f"- schematic: {f}" for f in b['flags_2d']]
            L += [f"- 3-D export: {f}" for f in b['flags_3d'] if f not in b['flags_2d']]
            L.append("")
    for title, sub, pat, cls in (
            ("Reentry objects", 'ro_library', '*.ro.json', bm.ROParams),
            ("Flight plans", 'flight_plans', '*.flightplan.json', None),
            ("Reentry plans", 'reentry_plans', '*.reentryplan.json', None)):
        L += [f"## {title}", ""]
        for path in sorted(glob.glob(os.path.join(root, sub, pat))):
            a = audit_plain(path, cls)
            L += [f"### {a['name'] or a['file']}", "",
                  f"File `{a['file']}`. {_prov_cell(a['provenance'])}.", ""]
            if a['stored']:
                L += ["| Stored value | |", "|---|---|"]
                L += [f"| `{k}` | {_short(v)} |" for k, v in a['stored'].items()]
                L.append("")
            for i, st in enumerate(a['stages'] or [], start=1):
                kept = {k: v for k, v in st.items() if v not in _EMPTY}
                if kept:
                    L.append(f"Stage {i}: " + ', '.join(f"`{k}` {_short(v, 40)}" for k, v in kept.items()))
            if a['stages']:
                L.append("")
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    import warnings
    warnings.filterwarnings('ignore')
    print(report(), end='')
