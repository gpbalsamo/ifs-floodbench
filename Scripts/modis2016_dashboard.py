#!/usr/bin/env python3
"""
modis2016_dashboard.py

Generates the static HTML/CSS/JS for the standalone "post-2016 named
events" dashboard (shell shared with kurosiwo_dashboard.py via
dashboard_shell.py).

Kept separate from the KuroSiwo dashboard on purpose: these are
hand-picked notable global floods (Yangtze 2016, Pakistan monsoon 2022,
Libya Derna 2023, ...) with only a MODIS observation layer -- no
CaMa-Flood GRIB, no VIIRS/GFM atlantis fetch, no benchmark scores --
unlike the curated, fully-scored KuroSiwo catalogue. Mixing the two
would make KuroSiwo_events.csv misleading (not every row would actually
be a KuroSiwo event) and silently downgrade what "select an event" means
for roughly a third of the catalogue.

Build the catalogue + copy the MODIS layers first with
build_modis2016_catalogue.py, then assemble the manifest with
build_dashboard_manifest.py (--modis-dir only, no --cama-dir/--atlantis-root),
then run this script for the dashboard shell.
"""
from pathlib import Path

from dashboard_shell import write_dashboard_shell

OUTDIR = Path("modis2016-dashboard")
DATA_DIR = OUTDIR / "dashboard_data"
LAYERS_DIR = DATA_DIR / "layers"

write_dashboard_shell(
    OUTDIR,
    title="Post-2016 Flood Events Dashboard (MODIS)",
    subtitle="Notable named global flood events since 2016, MODIS observation only",
    events_csv="Modis2016_events.csv",
    reference_figures=False,
    nav_links=[("← KuroSiwo benchmark dashboard", "../kurosiwo-dashboard/")],
)

print(f"Dashboard created in: {OUTDIR}")
print()
print("Build the catalogue + copy MODIS layers:")
print("  python3 build_modis2016_catalogue.py \\")
print("    --events-csv /home/pad/Notebooks/Modis_events.csv \\")
print("    --batch-root /perm/pad/flood_cases/modis_floods_events_2016_onwards \\")
print("    --out Modis2016_events.csv \\")
print("    --modis-dir modis2016_events")
print()
print("Assemble the manifest (MODIS-only: no --cama-dir/--atlantis-root):")
print("  python3 build_dashboard_manifest.py \\")
print("    --csv Modis2016_events.csv \\")
print("    --modis-dir modis2016_events \\")
print(f"    --dashboard-data {DATA_DIR}")
print()
print("Then copy the catalogue CSV and run:")
print(f"  cp Modis2016_events.csv {DATA_DIR / 'Modis2016_events.csv'}")
print(f"  cd {OUTDIR}")
print("  python3 -m http.server 8001")
