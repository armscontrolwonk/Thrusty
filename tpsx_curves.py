"""Build data/tpsx/curves.json: TPSX property tables against temperature.

TPSX (NASA Ames Thermal Protection Systems Expert) gives each material one
value "at standard conditions" on its material page (archived as
data/tpsx/tpsx-mat-N.html, parsed into data/tpsx/catalog.json), and the full
table behind it -- value against temperature, and for porous insulators
against pressure too -- on a property page,
https://tpsx.arc.nasa.gov/MaterialProperty?id=N&property=P.

This script fetches the property pages for the materials named in MATERIALS
and the properties named in PROPERTIES, archives each page verbatim under
data/tpsx/property/, and writes the parsed tables to data/tpsx/curves.json:

    {"<material id>": {"name": ...,
                       "<property name>": {"property_id": P,
                                           "columns": [...],
                                           "rows": [[...], ...]}}}

Rows are kept as TPSX prints them (numbers where they parse, else text), in
SI units.  Nothing is fitted or smoothed here; heating.py interpolates.

    python3 tpsx_curves.py            # fetch what is missing, rebuild json
    python3 tpsx_curves.py --offline  # rebuild json from the archive only
"""

import html
import json
import os
import re
import sys
import subprocess
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
TPSX_DIR = os.path.join(_HERE, "data", "tpsx")
PROP_DIR = os.path.join(TPSX_DIR, "property")
OUT = os.path.join(TPSX_DIR, "curves.json")
BASE = "https://tpsx.arc.nasa.gov/MaterialProperty?id={mid}&property={pid}"
MATERIAL = "https://tpsx.arc.nasa.gov/Material?id={mid}"

# The TPSX entries behind heating.TPS_MATERIALS (see each k_source) and the
# insulators a layered interior may use.
MATERIALS = (
    1,                              # LI-900 tile
    12, 13, 14, 15, 16, 17, 18, 19,  # AFRSI, AFRSI-2200/2500, DURAFRSI,
                                    # CFBI, TABI, FRSI (Nomex felt), PBI
    24, 25, 26, 28, 30, 32, 36,     # RCC, ACC, C/SiC, ZrB2/SiC, HfB2/SiC,
                                    # silica aerogel, C/C ablative
    41, 43, 57, 60, 113, 162, 249, 261,  # SIRCA, PICA, SS 304, Al 2024,
                                    # Narmco 4028, MX2600, Nomex FRSI, Ti-6-4
    11, 48,                         # strain isolator pad, RTV-560 adhesive
)
PROPERTIES = ("Thermal Conductivity", "Specific Heat", "Density", "Emissivity")


def _text(fragment):
    s = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def property_links(mid):
    """[(property id, property name)] from the archived material page."""
    path = os.path.join(TPSX_DIR, f"tpsx-mat-{mid}.html")
    if not os.path.exists(path):              # past the original crawl
        subprocess.run(["curl", "-sS", "-f", "-m", "60", "-o", path,
                        MATERIAL.format(mid=mid)], check=True)
    page = open(path, errors="ignore").read()
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        m = re.search(r"MaterialProperty\?id=%d&property=(\d+)" % mid, row)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if not m or not cells:
            continue
        name = re.sub(r"<sup>.*?</sup>", "", cells[0], flags=re.S)
        out.append((int(m.group(1)), _text(name)))
    return out


def _num(s):
    try:
        return float(s)
    except ValueError:
        return s


def parse_property_page(page):
    """(columns, rows) of the data table on a property page."""
    tables = re.findall(r"<table[^>]*>(.*?)</table>", page, re.S)
    for tb in tables:
        cols = [_text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", tb, re.S)]
        if not cols or not cols[0].startswith("Value"):
            continue
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>",
                                                   tr, re.S)]
            if cells:
                rows.append([_num(c) for c in cells])
        return cols, rows
    return [], []


def fetch(mid, pid, offline=False):
    path = os.path.join(PROP_DIR, f"mp-{mid}-{pid}.html")
    if not os.path.exists(path):
        if offline:
            return None
        # curl, not urllib: urllib stalled for about a minute per page on
        # this server where curl takes half a second.
        os.makedirs(PROP_DIR, exist_ok=True)
        subprocess.run(["curl", "-sS", "-f", "-m", "60", "-o", path,
                        BASE.format(mid=mid, pid=pid)], check=True)
        time.sleep(0.3)                      # be gentle with the server
    return open(path, errors="ignore").read()


def build(offline=False):
    cat = json.load(open(os.path.join(TPSX_DIR, "catalog.json")))
    out = {}
    for mid in MATERIALS:
        entry = {"name": cat[str(mid)].get("name", "")}
        for pid, name in property_links(mid):
            if not name.startswith(PROPERTIES):
                continue
            page = fetch(mid, pid, offline)
            if page is None:
                continue
            cols, rows = parse_property_page(page)
            entry[name] = {"property_id": pid, "columns": cols, "rows": rows}
        out[str(mid)] = entry
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == "__main__":
    res = build(offline="--offline" in sys.argv)
    for mid, e in res.items():
        props = {k: len(v["rows"]) for k, v in e.items() if k != "name"}
        print(mid, e["name"], props)
