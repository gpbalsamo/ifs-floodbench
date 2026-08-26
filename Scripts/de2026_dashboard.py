#!/usr/bin/env python3
"""
de2026_dashboard.py

Generates the static HTML/CSS/JS for the "recent events" dashboard (shell
shared with kurosiwo_dashboard.py / modis2016_dashboard.py via
dashboard_shell.py).

Unlike modis2016-dashboard, this one uses the same full CaMa-Flood +
VIIRS/GFM/MODIS + benchmark-scores layer set as kurosiwo-dashboard --
it's for recent/ongoing events tracked by DEflood2026_events.csv,
retrieved from a CaMa-Flood experiment version that actually reaches
these dates (KuroSiwo/Modis2016's default expver j1ee does not).

MODIS here does NOT come from atlantis (its lance_geotiff backend only
serves ~1 week of NRT data, and the laads_hdf4 historical backend needs a
GDAL build with HDF4 support that atlantis's own venv lacks) -- it comes
from extract_modis_flood.py, run directly in the `modis_flood` conda env,
which has a working HDF4-capable GDAL.

Example:
    python3 fetch_kurosiwo_observations.py \\
        --csv DEflood2026_events.csv --outroot de2026_observations \\
        --source viirs,gfm --window-days 3 --max-tile-deg 5.0

    python3 plot_kurosiwo_flood_cases.py \\
        --csv DEflood2026_events.csv --outdir de2026_png \\
        --overlay-dir de2026_png/layers --expver j01b

    # In the modis_flood conda env, once per event:
    python3 extract_modis_flood.py --date <peak date> \\
        --area <lat_max> <lon_min> <lat_min> <lon_max> \\
        --composite F2 --source laads --outdir de2026_events/<flood_case>

    python3 compute_flood_scores.py --csv DEflood2026_events.csv \\
        --cama-grib-dir de2026_png --atlantis-root de2026_observations \\
        --modis-dir de2026_events --out de2026_scores.csv

    python3 build_dashboard_manifest.py --csv DEflood2026_events.csv \\
        --cama-dir de2026_png/layers --atlantis-root de2026_observations \\
        --modis-dir de2026_events --scores-csv de2026_scores.csv \\
        --dashboard-data de2026-dashboard/dashboard_data
"""
from pathlib import Path

from dashboard_shell import write_dashboard_shell

OUTDIR = Path("de2026-dashboard")
DATA_DIR = OUTDIR / "dashboard_data"
LAYERS_DIR = DATA_DIR / "layers"

write_dashboard_shell(
    OUTDIR,
    title="Recent Flood Events Dashboard (2026)",
    subtitle="Ongoing/recent flood events, CaMa-Flood (expver j01b) vs. VIIRS/GFM/MODIS observations",
    events_csv="DEflood2026_events.csv",
    reference_figures=False,
    nav_links=[
        ("← KuroSiwo benchmark dashboard", "../kurosiwo-dashboard/"),
        ("Post-2016 named events (MODIS+CaMa) →", "../modis2016-dashboard/"),
    ],
)

print(f"Dashboard created in: {OUTDIR}")
print()
print("Fetch VIIRS/GFM (tiled automatically for large bboxes):")
print("  python3 fetch_kurosiwo_observations.py \\")
print("    --csv DEflood2026_events.csv --outroot de2026_observations \\")
print("    --source viirs,gfm --window-days 3 --max-tile-deg 5.0 --skip-existing")
print()
print("Retrieve the CaMa-Flood layer (note --expver, this catalogue needs a")
print("different experiment than KuroSiwo/Modis2016's default j1ee):")
print("  python3 plot_kurosiwo_flood_cases.py \\")
print("    --csv DEflood2026_events.csv --outdir de2026_png \\")
print("    --overlay-dir de2026_png/layers --expver j01b")
print()
print("MODIS (atlantis can't reach these dates -- use extract_modis_flood.py")
print("directly, in the `modis_flood` conda env, once per event):")
print("  conda activate modis_flood")
print("  python3 extract_modis_flood.py --date <peak date> \\")
print("    --area <lat_max> <lon_min> <lat_min> <lon_max> \\")
print("    --composite F2 --source laads --outdir de2026_events/<flood_case>")
print()
print("Compute benchmark scores:")
print("  python3 compute_flood_scores.py --csv DEflood2026_events.csv \\")
print("    --cama-grib-dir de2026_png --atlantis-root de2026_observations \\")
print("    --modis-dir de2026_events --out de2026_scores.csv")
print()
print("Assemble the manifest:")
print("  python3 build_dashboard_manifest.py --csv DEflood2026_events.csv \\")
print("    --cama-dir de2026_png/layers --atlantis-root de2026_observations \\")
print(f"    --modis-dir de2026_events --scores-csv de2026_scores.csv \\")
print(f"    --dashboard-data {DATA_DIR}")
print()
print("Then copy the catalogue CSV and run:")
print(f"  cp DEflood2026_events.csv {DATA_DIR / 'DEflood2026_events.csv'}")
print(f"  cd {OUTDIR}")
print("  python3 -m http.server 8002")
