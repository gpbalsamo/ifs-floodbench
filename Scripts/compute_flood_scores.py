#!/usr/bin/env python3
"""
compute_flood_scores.py

Verification scores (CSI, FAR, Hit Rate / POD) comparing the CaMa-Flood
model against VIIRS / GFM / MODIS observations, at each of the
selectable flooded-fraction thresholds (5% / 10% / 25% / 50%, see
overlay_utils.THRESHOLDS). This generalises the manual, single-threshold
scoring cells in Notebooks/Bench_CMF_{GFM,VIIRS,MODIS}_Inundation.ipynb
(where a threshold `Flmin` is hardcoded and the notebook re-run by hand)
into a batch script that sweeps all four thresholds for every event.

For each event and each available observation source:
  1. Load the CaMa-Flood flood-fraction field from the cached GRIB
     (as retrieved by plot_kurosiwo_flood_cases.py) -- this is the
     reference grid, matching this project's benchmarking convention of
     regridding observations onto the (coarser) model grid.
  2. Load the observation's flood-fraction field (atlantis-harmonised
     GeoTIFF for VIIRS/GFM, aggregated MCDWD raster for MODIS).
  3. Regrid the observation onto the CaMa-Flood grid (average resampling).
  4. At each threshold, binarize both fields and build a 2x2 contingency
     table treating the observation as truth and the model as forecast:
         tp = obs flooded & model flooded
         fp = obs not flooded & model flooded   (false alarm)
         fn = obs flooded & model not flooded   (miss)
         tn = obs not flooded & model not flooded
     computed only over pixels valid in both fields.
     CSI = tp / (tp+fp+fn), FAR = fp / (tp+fp), HR (POD) = tp / (tp+fn).

Writes one row per (flood_case, source, threshold) to a CSV.

Example:
    python3 compute_flood_scores.py \
        --csv KuroSiwo_events.csv \
        --cama-grib-dir cama_png \
        --atlantis-root kurosiwo_observations \
        --modis-dir modis_events \
        --out scores.csv
"""

import csv
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from overlay_utils import (
    load_fraction_geotiff,
    load_fraction_mcdwd,
    load_fraction_array,
    regrid_to,
    THRESHOLDS,
)
from plot_kurosiwo_flood_cases import (
    load_cama_flood_fraction,
    make_area,
    parse_date_to_yyyymmdd,
)

ATLANTIS_SOURCES = ["viirs", "gfm"]


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


def pick_harmonised_tif(source_dir):
    harmonised_dir = Path(source_dir) / "harmonised"
    tifs = sorted(harmonised_dir.glob("*_harmonised.tif"))
    return tifs[-1] if tifs else None


def contingency_scores(cama_bin, obs_bin, valid):
    tp = int(np.sum(valid & obs_bin & cama_bin))
    fp = int(np.sum(valid & ~obs_bin & cama_bin))
    fn = int(np.sum(valid & obs_bin & ~cama_bin))
    tn = int(np.sum(valid & ~obs_bin & ~cama_bin))

    csi = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else float("nan")
    far = fp / (tp + fp) if (tp + fp) > 0 else float("nan")
    hr = tp / (tp + fn) if (tp + fn) > 0 else float("nan")

    return tp, fp, fn, tn, csi, far, hr


def score_one(flood_case, cama_frac, cama_bounds, obs_frac, obs_bounds, source, obs_date, cama_date):
    obs_regridded = regrid_to(obs_frac, obs_bounds, cama_frac.shape, cama_bounds)
    valid = ~np.isnan(cama_frac) & ~np.isnan(obs_regridded)

    rows = []
    for key, threshold in THRESHOLDS:
        cama_bin = np.nan_to_num(cama_frac, nan=-1.0) >= threshold
        obs_bin = np.nan_to_num(obs_regridded, nan=-1.0) >= threshold
        tp, fp, fn, tn, csi, far, hr = contingency_scores(cama_bin, obs_bin, valid)
        rows.append({
            "flood_case": flood_case,
            "source": source,
            "threshold_key": key,
            "threshold": threshold,
            "n_valid": int(valid.sum()),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "csi": csi, "far": far, "hr": hr,
            "cama_date": cama_date,
            "obs_date": obs_date,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="KuroSiwo-style CSV catalogue")
    parser.add_argument("--cama-grib-dir", required=True,
                         help="Directory with cached <flood_case>_flood_globe.grb files "
                              "(the --outdir used with plot_kurosiwo_flood_cases.py)")
    parser.add_argument("--atlantis-root", default=None,
                         help="Root directory from fetch_kurosiwo_observations.py (viirs/gfm)")
    parser.add_argument("--modis-dir", default=None,
                         help="Root directory from modis_flood_events.py (modis)")
    parser.add_argument("--out", default="scores.csv")
    parser.add_argument("--buffer", type=float, default=0.5,
                         help="Degrees of padding around the event bbox, must match the "
                              "--buffer used with plot_kurosiwo_flood_cases.py. Default: 0.5")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows_csv = [
            {k.strip(): v.strip() for k, v in row.items() if k is not None and v is not None}
            for row in reader
        ]
    if args.limit:
        rows_csv = rows_csv[: args.limit]

    all_rows = []

    for row in rows_csv:
        flood_case = row["flood_case"]
        grib_path = Path(args.cama_grib_dir) / f"{flood_case}_flood_globe.grb"
        if not grib_path.exists():
            print(f"[{flood_case}] no cached CaMa-Flood GRIB, skipping")
            continue

        area = make_area(row, buffer_deg=args.buffer)
        cama_date = pd.to_datetime(
            str(parse_date_to_yyyymmdd(row["date_of_max_flood_extent"])), format="%Y%m%d"
        ).strftime("%Y-%m-%d")

        try:
            flood = load_cama_flood_fraction(grib_path, area)
        except Exception as e:
            print(f"[{flood_case}] failed to load CaMa-Flood fraction: {e}")
            continue

        cama_frac, cama_bounds = load_fraction_array(flood.lat.values, flood.lon.values, flood.values)

        found_any = False

        if args.atlantis_root:
            atlantis_event_dir = Path(args.atlantis_root) / sanitize_name(flood_case) / "atlantis"
            for source in ATLANTIS_SOURCES:
                tif_path = pick_harmonised_tif(atlantis_event_dir / source)
                if tif_path is None:
                    continue
                obs_frac, obs_bounds = load_fraction_geotiff(tif_path)
                parts = tif_path.stem.split("_")
                obs_date = parts[-3] if len(parts) >= 3 else None
                all_rows.extend(score_one(flood_case, cama_frac, cama_bounds, obs_frac, obs_bounds,
                                           source, obs_date, cama_date))
                found_any = True

        if args.modis_dir:
            event_dir = Path(args.modis_dir) / flood_case
            tifs = sorted(event_dir.glob("MCDWD_*_clipped.tif"))
            if tifs:
                tif_path = tifs[-1]
                obs_frac, obs_bounds = load_fraction_mcdwd(tif_path)
                parts = tif_path.stem.split("_")
                date_tag = parts[-2] if len(parts) >= 2 else None
                obs_date = (f"{date_tag[:4]}-{date_tag[4:6]}-{date_tag[6:8]}"
                            if date_tag and len(date_tag) == 8 else date_tag)
                all_rows.extend(score_one(flood_case, cama_frac, cama_bounds, obs_frac, obs_bounds,
                                           "modis", obs_date, cama_date))
                found_any = True

        print(f"[{flood_case}] {'scored' if found_any else 'no observations available'}")

    if not all_rows:
        print("No scores computed.")
        return

    fieldnames = list(all_rows[0].keys())
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} score rows to {args.out}")


if __name__ == "__main__":
    main()
