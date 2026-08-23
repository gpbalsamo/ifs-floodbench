#!/usr/bin/env python3
"""
kurosiwo_dashboard.py

Generates the static HTML/CSS/JS for the KuroSiwo flood-events dashboard
(shell shared with modis2016_dashboard.py via dashboard_shell.py).

The dashboard shows, per event:
  - an "Events" list in the side panel, sorted by peak flood date
    newest-first, in addition to the map; clicking a list row or a map
    rectangle selects the event and zooms/pans the map to its bbox.
  - the event bounding box on a Leaflet map
  - a selectable "flooded fraction" threshold (5% / 10% / 25% / 50% of a
    ~1 arcmin cell), applied identically to the model and every
    observation source, since "what counts as flooded" is otherwise an
    arbitrary cutoff.
  - toggleable, opacity-adjustable georeferenced overlays for each
    available layer at that threshold: the CaMa-Flood (IFS) model output
    and the VIIRS / GFM / MODIS observations, assembled by
    `build_dashboard_manifest.py` into `dashboard_data/layers.json`.
  - a "Benchmark scores" table per event, one CSI/FAR/HR-by-threshold
    table per observation source (from `compute_flood_scores.py` via
    `build_dashboard_manifest.py --scores-csv`), all four thresholds
    visible at once.
  - the original labelled reference figure (river discharge + flood
    fraction), if present at `dashboard_data/floods_png/<flood_case>.png`.

Expected dashboard_data layout after running the full pipeline:
    dashboard_data/
        KuroSiwo_events.csv
        layers.json
        layers/
            t05/<flood_case>_cama_flood.png
            t10/<flood_case>_viirs.png
            t25/<flood_case>_gfm.png
            t50/<flood_case>_modis.png
            ...
        floods_png/
            <flood_case>.png   (optional reference figure)
"""
from pathlib import Path

from dashboard_shell import write_dashboard_shell

OUTDIR = Path("kurosiwo-dashboard")
DATA_DIR = OUTDIR / "dashboard_data"
PNG_DIR = DATA_DIR / "floods_png"
LAYERS_DIR = DATA_DIR / "layers"

write_dashboard_shell(
    OUTDIR,
    title="KuroSiwo Flood Events Dashboard",
    subtitle="Model vs. observations for clickable flood events from the KuroSiwo catalogue",
    events_csv="KuroSiwo_events.csv",
    reference_figures=True,
    nav_links=[("Post-2016 named events (MODIS-only) →", "../modis2016-dashboard/")],
)

print(f"Dashboard created in: {OUTDIR}")
print()
print("Populate dashboard_data/ with, at minimum:")
print(f"  cp KuroSiwo_events.csv {DATA_DIR / 'KuroSiwo_events.csv'}")
print()
print("For the multi-layer model/observation overlays, run first:")
print("  python3 fetch_kurosiwo_observations.py --csv KuroSiwo_events.csv --outroot kurosiwo_observations")
print("  python3 plot_kurosiwo_flood_cases.py --csv KuroSiwo_events.csv --outdir cama_png "
      "--overlay-dir cama_png/layers")
print("  python3 build_dashboard_manifest.py --csv KuroSiwo_events.csv "
      f"--cama-dir cama_png/layers --atlantis-root kurosiwo_observations --dashboard-data {DATA_DIR}")
print()
print("Optionally also copy the labelled reference figures:")
print(f"  cp cama_png/*.png {PNG_DIR}/.")
print()
print("Then run:")
print(f"  cd {OUTDIR}")
print("  python3 -m http.server 8000")
