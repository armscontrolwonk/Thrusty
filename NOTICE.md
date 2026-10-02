# Third-party data and attributions

Thrusty's own code is licensed under GPL-3.0-or-later (`LICENSE`) and its own
documentation and vehicle data files under CC BY-SA 4.0 (`LICENSE-DATA`); the
Thrusty mascot artwork and icon are all rights reserved (see *Artwork* below
and the *License* section of `README.md`).  The repository also bundles data
produced by others.  Those files keep their original terms, listed here.
Where a source is a work of the United States Government it is not subject to
copyright in the United States (17 U.S.C. § 105).

## Geographic reference data

| Files | Source | Terms |
|---|---|---|
| `data/gazetteer/gnis_us.txt.gz` | USGS Geographic Names Information System, Domestic Names | U.S. Government work, public domain |
| `data/gazetteer/antarctica.txt.gz` | U.S. Board on Geographic Names / ACAN Antarctic gazetteer | U.S. Government work, public domain |
| `data/gazetteer/gns_*.txt.gz` | National Geospatial-Intelligence Agency, GEOnet Names Server (GNS) | U.S. Government work, public domain. NGA asks that GNS data not be represented as an official NGA product once modified |
| `data/ne_50m_countries.geojson` | Natural Earth, 1:50m Admin 0 countries | Public domain (Natural Earth places all its data in the public domain) |
| `data/dem/terrain_0p05deg.npy` | Resampled from the Mapzen / Tilezen *Terrarium* elevation tiles (AWS Open Data `elevation-tiles-prod`), themselves a blend of SRTM (NASA/USGS), GMTED2010 (USGS), ETOPO1 (NOAA) and national DEMs | The U.S. sources are public domain. Several national contributors require attribution; the full list is maintained at <https://github.com/tilezen/joerd/blob/master/docs/attribution.md>. Attribution as requested there: *ArcticDEM terrain data DEM(s) were created from DigitalGlobe, Inc., imagery and funded under NSF awards; Australia terrain data © Commonwealth of Australia (Geoscience Australia) 2017; Austria terrain data © offene Daten Österreichs, Digitales Geländemodell (DGM) Österreich; Canada terrain data contains information licensed under the Open Government Licence – Canada; Europe terrain data produced using Copernicus data and information funded by the European Union – EU-DEM layers; Global ETOPO1 terrain data U.S. National Oceanic and Atmospheric Administration; Mexico terrain data source: INEGI, Continental relief, 2016; New Zealand terrain data Copyright 2011 Crown copyright (c) Land Information New Zealand and the New Zealand Government (CC BY 4.0); Norway terrain data © Kartverket; United Kingdom terrain data © Environment Agency copyright and/or database right 2015; United States 3DEP and GMTED2010 terrain data courtesy of the U.S. Geological Survey.* |

The gazetteer and terrain files are derived products; `gazetteer_build.py` and
`dem_build.py` reproduce them from the sources above.

## Navigational warnings

| Files | Source | Terms |
|---|---|---|
| `provenance/AUR_warning_boxes.json` | Hazard-area coordinates of a navigational warning for an AUR flight test from Cape Canaveral, transcribed from the maintainer's Google Earth file; warnings are issued by the U.S. National Geospatial-Intelligence Agency (the warning's number and text are to be confirmed; see the file's `_source`) | U.S. Government work, not subject to copyright in the United States |

## Aerodynamic reference data

| Files | Source | Terms |
|---|---|---|
| `data/aero/jernell_1968_flat_cylinders.csv` | Jernell, L. S., *Aerodynamic Characteristics of Bodies of Revolution at Mach Numbers from 1.50 to 2.86 and Angles of Attack to 180°*, NASA TM X-1658, 1968 (NTRS 19680026721). Values digitised by Thrusty from the report's Figs. 3 and 9 (2026-09-30); precision stated in the file header | U.S. Government work, not subject to copyright in the United States. The digitised table is Thrusty's and is released under CC BY-SA 4.0 (`LICENSE-DATA`) |

## Materials and propulsion data

| Files | Source | Terms |
|---|---|---|
| `data/tpsx/` | NASA Ames Thermal Protection Systems Expert (TPSX) materials database, archived page crawl and the catalog derived from it | NASA work, not subject to copyright in the United States; used under NASA's media and data usage guidelines. NASA does not endorse this project |
| `mass_data/ng_motors*.csv` | Numeric specifications transcribed from the Northrop Grumman *Propulsion Products Catalog* (January 2023) | Factual data. The catalog itself remains © Northrop Grumman; only the tabulated values are reproduced |

## Validation and benchmark data

| Files | Source | Terms |
|---|---|---|
| `benchmarks/form_a/*.csv`, `benchmarks/verification/*.csv`, `benchmarks/swerve/*.csv` | Numeric values digitised from figures in published papers and NASA/NACA technical reports (Sutton & Graves 1971; the REENTRY-F, Stardust and Hayabusa flight reports; Finke, IDA P-2395; the SWERVE corridor). Full citations in `METHODS.md` §16 and `HEATING_TPS_REFERENCES.md` | Extracted data points, cited to their sources. Government reports are public domain; the digitised values from journal articles are factual data, reproduced for verification |
| `benchmarks/form_a/*.png`, `benchmarks/verification/*.png` | Figure scans from the NASA/NACA and IDA reports above, kept beside their digitisations | U.S. Government works, public domain |
| `validation/datcom/` | Input and output of USAF Digital DATCOM | Public domain (U.S. Government work) |
| `benchmarks/verification/hayabusa2_remm_fig19.csv` | Temperatures read from Fig. 19 of Yamada & Yoshihara, *Post-Flight Analysis of Recovered Components of Hayabusa2 Sample Return Capsule*, J. Evolving Space Activities 1 (2023) 16 | The article is CC BY-NC-ND 4.0. Only measured values read from the figure are kept (factual data, cited); the figure itself is not reproduced |
| `data/tpsx/property/`, `data/tpsx/curves.json` | NASA Ames TPSX property pages (each material's values against temperature and pressure), archived and parsed by `tpsx_curves.py` | NASA work, as for `data/tpsx/` above |

## Artwork (not third-party, but separately reserved)

| Files | Terms |
|---|---|
| `assets/` (thrusty.png, thrusty.icns, thrusty_diffuse.jpg, thrusty_figure.png, thrusty_scale.png, thrusty_mesh.obj.gz), `data/Thrusty.png`, `data/Thrusty2.png`, `data/Thrusty3.png`, `data/Thrusty_tall.png`, `data/Thrusty_silhouette.jpg`, `Thrusty.app/Contents/Resources/thrusty.icns` | © 2026 Jeffrey Lewis. All rights reserved. These files are aggregated with the program for convenience and are not part of the GPL-licensed work; Permission is granted to redistribute unmodified copies of Thrusty with these files intact. Any other reproduction, modification or redistribution, including in a modified Thrusty, requires the author's permission or replacement of the files. The application runs without them (a missing icon falls back to the stock one). |

## Lineage

Thrusty descends from Geoffrey Forden's MATLAB tool described in *Simulating
the Operation of Ballistic Missiles*, Science & Global Security 15 (2007).
The MATLAB program was received in MATLAB-encrypted form; Thrusty's design was
inferred from that program's file structure and the published paper, and the
code was written independently.  No Forden code is included in this
repository; the encrypted files once kept under `archive/matlab` were removed
on 2026-09-18 as they were unusable and not ours to distribute.

## Python dependencies

Thrusty imports NumPy, SciPy, Matplotlib and Pillow (and optionally geopy,
cartopy, folium, openpyxl, tkinterdnd2, pymsis).  They are not bundled in this
repository; each is obtained separately under its own license.
