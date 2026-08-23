#!/usr/bin/env python3
"""
build_dashboard_manifest.py

Assemble the multi-layer manifest (`layers.json`) consumed by the
kurosiwo-dashboard, combining:

  * the CaMa-Flood (IFS model) overlay PNGs produced by
    `plot_kurosiwo_flood_cases.py --overlay-dir ...`
  * the VIIRS / GFM / MODIS observation overlays, rendered here from the
    harmonised GeoTIFFs produced by `fetch_kurosiwo_observations.py`
    (which wraps the `atlantis fetch --harmonise` pipeline) and from
    `modis_flood_events.py`'s raw MCDWD GeoTIFFs.

Every layer is rendered at each of the selectable "flooded fraction"
thresholds in overlay_utils.THRESHOLDS (5% / 10% / 25% / 50%), so the
dashboard can switch between them without re-fetching or re-processing
any data. For each flood_case, whichever layers are available are
copied/rendered into `<dashboard-data>/layers/<threshold>/` and recorded
in `<dashboard-data>/layers.json`.

Example:
    python3 build_dashboard_manifest.py \
        --csv KuroSiwo_events.csv \
        --cama-dir cama_png/layers \
        --atlantis-root kurosiwo_observations \
        --modis-dir modis_events \
        --dashboard-data kurosiwo-dashboard/dashboard_data
"""

import csv
import json
import shutil
import argparse
from pathlib import Path

from overlay_utils import (
    load_fraction_geotiff,
    load_fraction_mcdwd,
    render_overlay_all_thresholds,
    LAYER_COLORS,
    THRESHOLDS,
)

# VIIRS and GFM come from atlantis (--atlantis-root); MODIS comes from
# ifs-floodbench's own extract_modis_flood.py / modis_flood_events.py
# (--modis-dir), since atlantis's laads_hdf4 MODIS backend needs an
# osgeo.gdal build with HDF4 support that isn't available in its own
# environment on this system, whereas the dedicated `modis_flood` conda
# env already has it (see Scripts/README.md).
ATLANTIS_SOURCES = ["viirs", "gfm"]

LAYERS_META = {
    "cama_flood": {"label": "CaMa-Flood (IFS model)", "color": "#1e3c96"},
    "viirs": {"label": "VIIRS (observation)", "color": "#e67e22"},
    "gfm": {"label": "GFM Sentinel-1 (observation)", "color": "#9b26b6"},
    "modis": {"label": "MODIS (observation)", "color": "#27ae60"},
}

THRESHOLDS_META = [{"key": key, "value": value, "label": f"{int(value * 100)}%"}
                    for key, value in THRESHOLDS]


def sanitize_name(s):
    return (
        s.replace(" ", "_")
         .replace("/", "_")
         .replace("(", "")
         .replace(")", "")
         .replace(",", "")
         .replace("’", "")
         .replace("'", "")
    )


def read_flood_cases(csv_path):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [row["flood_case"].strip() for row in reader if row.get("flood_case")]


def add_cama_layer(flood_case, cama_dir, layers_out_dir):
    """Copy an existing CaMa-Flood overlay PNG set + JSON sidecar into place."""
    cama_dir = Path(cama_dir)
    sidecar = cama_dir / f"{flood_case}_cama_flood.json"
    if not sidecar.exists():
        return None

    meta = json.loads(sidecar.read_text())
    png_by_threshold = {}
    for key, rel_path in meta["png"].items():
        src_png = cama_dir / rel_path
        if not src_png.exists():
            continue
        dst_png = layers_out_dir / key / src_png.name
        dst_png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_png, dst_png)
        png_by_threshold[key] = f"layers/{key}/{dst_png.name}"

    if not png_by_threshold:
        return None

    return {"png": png_by_threshold, "bounds": meta["bounds"], "date": meta.get("date")}


def pick_harmonised_tif(source_dir):
    """
    Pick the harmonised GeoTIFF to display for a source. With the default
    `--strategy peak` there is exactly one; if several dates exist
    (`--strategy all`), pick the most recent.
    """
    harmonised_dir = Path(source_dir) / "harmonised"
    tifs = sorted(harmonised_dir.glob("*_harmonised.tif"))
    return tifs[-1] if tifs else None


def render_layer_all_thresholds(flood_case, source, frac, bounds, layers_out_dir):
    png_by_threshold = render_overlay_all_thresholds(
        frac, bounds,
        lambda key: layers_out_dir / key / f"{flood_case}_{source}.png",
        LAYER_COLORS[source],
    )
    return {key: f"layers/{key}/{path.name}" for key, path in png_by_threshold.items()}


def add_modis_layer(flood_case, modis_dir, layers_out_dir, flood_classes=(3,)):
    """
    Pick the most recent MCDWD_*_clipped.tif from modis_flood_events.py's
    per-event output directory, aggregate it onto the 1 arcmin grid, and
    render the "modis" overlay at every threshold.
    """
    event_dir = Path(modis_dir) / flood_case
    tifs = sorted(event_dir.glob("MCDWD_*_clipped.tif"))
    if not tifs:
        return None
    tif_path = tifs[-1]

    # MCDWD_<source>_<composite>_<YYYYMMDD>_clipped.tif
    parts = tif_path.stem.split("_")
    date_tag = parts[-2] if len(parts) >= 2 else None
    date = f"{date_tag[:4]}-{date_tag[4:6]}-{date_tag[6:8]}" if date_tag and len(date_tag) == 8 else date_tag

    frac, bounds = load_fraction_mcdwd(tif_path, flood_classes=flood_classes)
    png_by_threshold = render_layer_all_thresholds(flood_case, "modis", frac, bounds, layers_out_dir)

    return {"png": png_by_threshold, "bounds": bounds, "date": date}


def add_observation_layer(flood_case, source, atlantis_event_dir, layers_out_dir):
    tif_path = pick_harmonised_tif(Path(atlantis_event_dir) / source)
    if tif_path is None:
        return None

    # <flood_case>_<date>_<source>_harmonised.tif -> pull the date back out.
    parts = tif_path.stem.split("_")
    date = parts[-3] if len(parts) >= 3 else None

    frac, bounds = load_fraction_geotiff(tif_path)
    png_by_threshold = render_layer_all_thresholds(flood_case, source, frac, bounds, layers_out_dir)

    return {"png": png_by_threshold, "bounds": bounds, "date": date}


def load_scores(scores_csv):
    """
    Load compute_flood_scores.py's output and index it as
    {(flood_case, source): {threshold_key: {csi, far, hr, n_valid}}}.
    """
    scores = {}
    with open(scores_csv, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["flood_case"], row["source"])
            scores.setdefault(key, {})[row["threshold_key"]] = {
                "csi": float(row["csi"]) if row["csi"] != "nan" else None,
                "far": float(row["far"]) if row["far"] != "nan" else None,
                "hr": float(row["hr"]) if row["hr"] != "nan" else None,
                "n_valid": int(row["n_valid"]),
            }
    return scores


def main():
    parser = argparse.ArgumentParser(description="Build the multi-layer manifest for kurosiwo-dashboard.")
    parser.add_argument("--csv", required=True, help="KuroSiwo-style CSV catalogue")
    parser.add_argument("--cama-dir", default=None,
                         help="Directory with *_cama_flood.png/.json from plot_kurosiwo_flood_cases.py --overlay-dir")
    parser.add_argument("--atlantis-root", default=None,
                         help="Root directory from fetch_kurosiwo_observations.py "
                              "(contains <flood_case>/atlantis/<source>/harmonised/*.tif); "
                              "supplies the viirs and gfm layers.")
    parser.add_argument("--modis-dir", default=None,
                         help="Root directory from modis_flood_events.py "
                              "(contains <flood_case>/MCDWD_*_clipped.tif); supplies the modis layer.")
    parser.add_argument("--scores-csv", default=None,
                         help="Output of compute_flood_scores.py; attaches CSI/FAR/HR per "
                              "(event, source, threshold) to each observation layer.")
    parser.add_argument("--dashboard-data", default="kurosiwo-dashboard/dashboard_data",
                         help="Dashboard data directory (layers/ and layers.json are written here)")
    args = parser.parse_args()

    scores = load_scores(args.scores_csv) if args.scores_csv else {}

    dashboard_data = Path(args.dashboard_data)
    layers_out_dir = dashboard_data / "layers"
    layers_out_dir.mkdir(parents=True, exist_ok=True)

    flood_cases = read_flood_cases(args.csv)

    manifest = {
        "layers_meta": LAYERS_META,
        "thresholds": THRESHOLDS_META,
        "default_threshold": THRESHOLDS_META[0]["key"],
        "events": {},
    }

    for flood_case in flood_cases:
        event_entry = {}

        if args.cama_dir:
            cama = add_cama_layer(flood_case, args.cama_dir, layers_out_dir)
            if cama:
                event_entry["cama_flood"] = cama

        if args.atlantis_root:
            atlantis_event_dir = Path(args.atlantis_root) / sanitize_name(flood_case) / "atlantis"
            for source in ATLANTIS_SOURCES:
                layer = add_observation_layer(flood_case, source, atlantis_event_dir, layers_out_dir)
                if layer:
                    if (flood_case, source) in scores:
                        layer["scores"] = scores[(flood_case, source)]
                    event_entry[source] = layer

        if args.modis_dir:
            layer = add_modis_layer(flood_case, args.modis_dir, layers_out_dir)
            if layer:
                if (flood_case, "modis") in scores:
                    layer["scores"] = scores[(flood_case, "modis")]
                event_entry["modis"] = layer

        if event_entry:
            manifest["events"][flood_case] = event_entry
            print(f"[{flood_case}] layers: {sorted(event_entry.keys())}")
        else:
            print(f"[{flood_case}] no layers found")

    manifest_path = dashboard_data / "layers.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nEvents with at least one layer: {len(manifest['events'])} / {len(flood_cases)}")
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
