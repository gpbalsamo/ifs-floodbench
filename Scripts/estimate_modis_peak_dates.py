#!/usr/bin/env python3
"""
Estimate date_of_max_flood_extent for a KuroSiwo-style flood catalogue by
scanning daily MODIS flood maps over each event period.

The script is designed to run BEFORE modis_flood_events.py.

For each event it:
  1. loops from date_start to date_end inclusive;
  2. calls extract_modis_flood.py for the event bbox and date;
  3. reads the clipped GeoTIFF;
  4. computes flood / missing / valid pixel fractions;
  5. selects the date maximizing a cloud-aware score:

        score = flood_fraction_valid * (1 - missing_fraction_total)

  6. writes an updated CSV preserving the original KuroSiwo columns, with
     date_of_max_flood_extent replaced by the best MODIS-observed date.

Expected input columns:
  flood_case,country,continent,date_start,date_end,
  lat_min,lat_max,lon_min,lon_max,
  max_flood_extent_km2,date_of_max_flood_extent

Default MODIS flood-product classes:
  flood value   = 3       # flood water, in NASA/DFO-style products
  missing value = 255     # insufficient data/cloud/missing in MCDWD products

For older products where 0 means insufficient data, run with:
  --missing-values 0 255

Example:
  python3 estimate_modis_peak_dates.py \
    --csv Modis_floods_events_2016_onwards.csv \
    --out Modis_floods_events_2016_onwards_peakdates.csv \
    --workdir modis_peak_scan \
    --composite F2 \
    --skip-existing

Then run:
  python3 modis_flood_events.py \
    --csv Modis_floods_events_2016_onwards_peakdates.csv \
    --outroot modis_floods_events_2016_onwards \
    --composite F2 \
    --skip-existing
"""

import argparse
import csv
import math
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

try:
    import rasterio
except ImportError as exc:
    raise SystemExit(
        "This script requires rasterio. Activate your modis_flood conda environment first."
    ) from exc


KUROSIWO_COLUMNS = [
    "flood_case",
    "country",
    "continent",
    "date_start",
    "date_end",
    "lat_min",
    "lat_max",
    "lon_min",
    "lon_max",
    "max_flood_extent_km2",
    "date_of_max_flood_extent",
]


def parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%d")


def daterange(start: datetime, end: datetime) -> Iterable[datetime]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def sanitize_name(s: str) -> str:
    return (
        s.replace(" ", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(",", "")
        .replace("’", "")
        .replace("'", "")
        .replace(";", "_")
    )


def clean_row(row: Dict[str, str]) -> Dict[str, str]:
    return {
        k.strip().replace("\ufeff", ""): (v.strip() if v is not None else "")
        for k, v in row.items()
        if k is not None
    }


def run_extract(
    extract_script: str,
    date_iso: str,
    north: float,
    west: float,
    south: float,
    east: float,
    composite: str,
    outdir: Path,
    dry_run: bool = False,
) -> int:
    cmd = [
        "python3",
        extract_script,
        "--date",
        date_iso,
        "--area",
        str(north),
        str(west),
        str(south),
        str(east),
        "--composite",
        composite,
        "--outdir",
        str(outdir),
    ]
    print("    " + " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd).returncode


def expected_tif(outdir: Path, composite: str, date_iso: str) -> Path:
    date_tag = date_iso.replace("-", "")
    return outdir / f"MCDWD_laads_{composite}_{date_tag}_clipped.tif"


def read_pixel_metrics(
    tif: Path,
    flood_values: List[int],
    water_values: List[int],
    missing_values: List[int],
    nodata_as_missing: bool = True,
) -> Dict[str, float]:
    with rasterio.open(tif) as src:
        arr = src.read(1)
        nodata = src.nodata

    total = int(arr.size)
    if total == 0:
        raise ValueError(f"Empty raster: {tif}")

    missing_mask = np.zeros(arr.shape, dtype=bool)

    if np.issubdtype(arr.dtype, np.floating):
        missing_mask |= ~np.isfinite(arr)

    if missing_values:
        missing_mask |= np.isin(arr, missing_values)

    if nodata_as_missing and nodata is not None:
        if isinstance(nodata, float) and math.isnan(nodata):
            missing_mask |= ~np.isfinite(arr)
        else:
            missing_mask |= arr == nodata

    valid_mask = ~missing_mask
    valid = int(valid_mask.sum())
    missing = int(missing_mask.sum())

    flood_mask = valid_mask & np.isin(arr, flood_values)
    water_mask = valid_mask & np.isin(arr, water_values) if water_values else np.zeros(arr.shape, dtype=bool)

    flood = int(flood_mask.sum())
    water = int(water_mask.sum())

    flood_fraction_valid = flood / valid if valid > 0 else 0.0
    flood_fraction_total = flood / total if total > 0 else 0.0
    water_fraction_valid = water / valid if valid > 0 else 0.0
    missing_fraction_total = missing / total if total > 0 else 1.0
    valid_fraction_total = valid / total if total > 0 else 0.0

    score = flood_fraction_valid * (1.0 - missing_fraction_total)

    return {
        "total_pixels": total,
        "valid_pixels": valid,
        "missing_pixels": missing,
        "flood_pixels": flood,
        "water_pixels": water,
        "flood_fraction_valid": flood_fraction_valid,
        "flood_fraction_total": flood_fraction_total,
        "water_fraction_valid": water_fraction_valid,
        "missing_fraction_total": missing_fraction_total,
        "valid_fraction_total": valid_fraction_total,
        "modis_peak_score": score,
    }


def midpoint_date(date_start: str, date_end: str) -> str:
    s = parse_date(date_start)
    e = parse_date(date_end)
    mid = s + (e - s) / 2
    return mid.strftime("%Y-%m-%d")


def choose_best(rows: List[Dict[str, str]], min_valid_fraction: float) -> Optional[Dict[str, str]]:
    usable = [
        r
        for r in rows
        if r.get("status") == "ok"
        and float(r.get("valid_fraction_total", 0.0)) >= min_valid_fraction
    ]
    if not usable:
        return None

    # Primary: cloud-aware score. Tie-breakers: more flood, less missing, more valid.
    return max(
        usable,
        key=lambda r: (
            float(r["modis_peak_score"]),
            float(r["flood_fraction_valid"]),
            -float(r["missing_fraction_total"]),
            float(r["valid_fraction_total"]),
        ),
    )


def write_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def format_float(x: float) -> str:
    return f"{x:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate MODIS-observed peak flood dates for KuroSiwo-style events."
    )
    parser.add_argument("--csv", required=True, help="Input KuroSiwo-style CSV file")
    parser.add_argument("--out", required=True, help="Output CSV with improved date_of_max_flood_extent")
    parser.add_argument("--workdir", default="modis_peak_scan", help="Directory for daily extracted rasters and diagnostics")
    parser.add_argument("--extract-script", default="extract_modis_flood.py", help="Path to extract_modis_flood.py")
    parser.add_argument("--composite", default="F2", choices=["F1", "F1C", "F2", "F3"], help="MODIS composite to scan")
    parser.add_argument("--padding", type=float, default=0.0, help="Optional bbox padding in degrees")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of events to process")
    parser.add_argument("--skip-existing", action="store_true", help="Reuse daily clipped GeoTIFFs if already present")
    parser.add_argument("--keep-tiffs", action="store_true", help="Keep daily clipped GeoTIFFs after metrics are computed")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only; do not run extraction")

    parser.add_argument(
        "--flood-values",
        type=int,
        nargs="+",
        default=[3],
        help="Raster values counted as flood. Default: 3",
    )
    parser.add_argument(
        "--water-values",
        type=int,
        nargs="*",
        default=[2],
        help="Raster values counted as permanent/reference surface water. Default: 2",
    )
    parser.add_argument(
        "--missing-values",
        type=int,
        nargs="+",
        default=[255],
        help="Raster values counted as missing/insufficient data. Default: 255. For older products try: 0 255",
    )
    parser.add_argument(
        "--min-valid-fraction",
        type=float,
        default=0.05,
        help="Minimum valid fraction required for a date to be eligible. Default: 0.05",
    )
    parser.add_argument(
        "--keep-original-date-column",
        action="store_true",
        help="Add date_of_max_flood_extent_original before replacing date_of_max_flood_extent",
    )

    args = parser.parse_args()

    in_csv = Path(args.csv)
    out_csv = Path(args.out)
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    print("Input CSV:        ", in_csv)
    print("Output CSV:       ", out_csv)
    print("Workdir:          ", workdir)
    print("Composite:        ", args.composite)
    print("Flood values:     ", args.flood_values)
    print("Water values:     ", args.water_values)
    print("Missing values:   ", args.missing_values)
    print("Min valid fraction:", args.min_valid_fraction)

    updated_rows: List[Dict[str, str]] = []
    all_diag_rows: List[Dict[str, str]] = []

    with open(in_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [name.strip().replace("\ufeff", "") for name in reader.fieldnames]
        input_columns = reader.fieldnames

        missing_columns = [c for c in KUROSIWO_COLUMNS if c not in input_columns]
        if missing_columns:
            raise SystemExit(f"Missing required columns in input CSV: {missing_columns}")

        for i, raw_row in enumerate(reader, start=1):
            if args.limit is not None and len(updated_rows) >= args.limit:
                break

            row = clean_row(raw_row)
            flood_case = row["flood_case"]
            safe_case = sanitize_name(flood_case)
            event_dir = workdir / safe_case
            event_dir.mkdir(parents=True, exist_ok=True)

            lat_min = float(row["lat_min"])
            lat_max = float(row["lat_max"])
            lon_min = float(row["lon_min"])
            lon_max = float(row["lon_max"])
            pad = args.padding
            north = lat_max + pad
            west = lon_min - pad
            south = lat_min - pad
            east = lon_max + pad

            start = parse_date(row["date_start"])
            end = parse_date(row["date_end"])
            if end < start:
                raise SystemExit(f"date_end before date_start for {flood_case}")

            original_peak_date = row.get("date_of_max_flood_extent", "") or midpoint_date(row["date_start"], row["date_end"])

            print("\n" + "=" * 88)
            print(f"[{i}] {flood_case}")
            print(f"Period: {row['date_start']} to {row['date_end']}  |  bbox N/W/S/E: {north}/{west}/{south}/{east}")
            print("=" * 88)

            event_diag_rows: List[Dict[str, str]] = []

            for d in daterange(start, end):
                date_iso = d.strftime("%Y-%m-%d")
                tif = expected_tif(event_dir, args.composite, date_iso)

                status = "ok"
                error = ""

                if not (args.skip_existing and tif.exists()):
                    rc = run_extract(
                        args.extract_script,
                        date_iso,
                        north,
                        west,
                        south,
                        east,
                        args.composite,
                        event_dir,
                        dry_run=args.dry_run,
                    )
                    if rc != 0:
                        status = f"extract_failed_{rc}"

                if args.dry_run:
                    metrics = None
                    status = "dry_run"
                elif status == "ok" and tif.exists():
                    try:
                        metrics = read_pixel_metrics(
                            tif,
                            flood_values=args.flood_values,
                            water_values=args.water_values,
                            missing_values=args.missing_values,
                        )
                    except Exception as exc:  # noqa: BLE001: useful for batch diagnostics
                        metrics = None
                        status = "read_failed"
                        error = str(exc)
                elif status == "ok":
                    metrics = None
                    status = "missing_tif"
                    error = str(tif)
                else:
                    metrics = None

                diag = {
                    "flood_case": flood_case,
                    "country": row.get("country", ""),
                    "date": date_iso,
                    "composite": args.composite,
                    "status": status,
                    "tif": str(tif),
                    "error": error,
                    "total_pixels": "",
                    "valid_pixels": "",
                    "missing_pixels": "",
                    "flood_pixels": "",
                    "water_pixels": "",
                    "flood_fraction_valid": "",
                    "flood_fraction_total": "",
                    "water_fraction_valid": "",
                    "missing_fraction_total": "",
                    "valid_fraction_total": "",
                    "modis_peak_score": "",
                }

                if metrics:
                    diag.update(
                        {
                            "total_pixels": str(int(metrics["total_pixels"])),
                            "valid_pixels": str(int(metrics["valid_pixels"])),
                            "missing_pixels": str(int(metrics["missing_pixels"])),
                            "flood_pixels": str(int(metrics["flood_pixels"])),
                            "water_pixels": str(int(metrics["water_pixels"])),
                            "flood_fraction_valid": format_float(metrics["flood_fraction_valid"]),
                            "flood_fraction_total": format_float(metrics["flood_fraction_total"]),
                            "water_fraction_valid": format_float(metrics["water_fraction_valid"]),
                            "missing_fraction_total": format_float(metrics["missing_fraction_total"]),
                            "valid_fraction_total": format_float(metrics["valid_fraction_total"]),
                            "modis_peak_score": format_float(metrics["modis_peak_score"]),
                        }
                    )
                    print(
                        f"  {date_iso}  flood_valid={diag['flood_fraction_valid']}  "
                        f"missing={diag['missing_fraction_total']}  score={diag['modis_peak_score']}"
                    )
                else:
                    print(f"  {date_iso}  {status} {error}")

                event_diag_rows.append(diag)
                all_diag_rows.append(diag)

                if not args.keep_tiffs and tif.exists():
                    # Keep the diagnostics CSV and save disk space.
                    try:
                        tif.unlink()
                    except OSError:
                        pass

            best = choose_best(event_diag_rows, min_valid_fraction=args.min_valid_fraction)
            if best is None:
                selected_date = original_peak_date
                selection_status = "fallback_original_or_midpoint"
                print(f"Selected: {selected_date} ({selection_status})")
            else:
                selected_date = best["date"]
                selection_status = "modis_peak_score"
                print(
                    f"Selected: {selected_date}  "
                    f"score={best['modis_peak_score']}  "
                    f"flood_valid={best['flood_fraction_valid']}  "
                    f"missing={best['missing_fraction_total']}"
                )

            if args.keep_original_date_column:
                row["date_of_max_flood_extent_original"] = original_peak_date

            row["date_of_max_flood_extent"] = selected_date
            row["date_of_max_flood_extent_method"] = selection_status

            if best is not None:
                row["modis_peak_score"] = best["modis_peak_score"]
                row["flood_pixel_fraction_at_peak"] = best["flood_fraction_valid"]
                row["missing_pixel_fraction_at_peak"] = best["missing_fraction_total"]
                row["valid_pixel_fraction_at_peak"] = best["valid_fraction_total"]
                row["n_total_pixels_at_peak"] = best["total_pixels"]
                row["n_valid_pixels_at_peak"] = best["valid_pixels"]
                row["n_flood_pixels_at_peak"] = best["flood_pixels"]
                row["n_missing_pixels_at_peak"] = best["missing_pixels"]
            else:
                row["modis_peak_score"] = ""
                row["flood_pixel_fraction_at_peak"] = ""
                row["missing_pixel_fraction_at_peak"] = ""
                row["valid_pixel_fraction_at_peak"] = ""
                row["n_total_pixels_at_peak"] = ""
                row["n_valid_pixels_at_peak"] = ""
                row["n_flood_pixels_at_peak"] = ""
                row["n_missing_pixels_at_peak"] = ""

            updated_rows.append(row)

            event_diag_csv = event_dir / "daily_modis_peak_diagnostics.csv"
            write_csv(event_diag_csv, event_diag_rows, list(event_diag_rows[0].keys()))

            if not args.keep_tiffs:
                # Remove empty per-date extraction artefacts only if the directory contains no diagnostics.
                # Some extractors write sidecar files; leave the event directory intact.
                pass

    # Preserve original KuroSiwo column order first, then append diagnostics columns.
    extra_cols = []
    if args.keep_original_date_column:
        extra_cols.append("date_of_max_flood_extent_original")
    extra_cols.extend(
        [
            "date_of_max_flood_extent_method",
            "modis_peak_score",
            "flood_pixel_fraction_at_peak",
            "missing_pixel_fraction_at_peak",
            "valid_pixel_fraction_at_peak",
            "n_total_pixels_at_peak",
            "n_valid_pixels_at_peak",
            "n_flood_pixels_at_peak",
            "n_missing_pixels_at_peak",
        ]
    )
    output_cols = KUROSIWO_COLUMNS + [c for c in extra_cols if c not in KUROSIWO_COLUMNS]

    write_csv(out_csv, updated_rows, output_cols)

    diag_csv = workdir / "all_daily_modis_peak_diagnostics.csv"
    if all_diag_rows:
        write_csv(diag_csv, all_diag_rows, list(all_diag_rows[0].keys()))

    print("\nDone.")
    print(f"Updated event CSV: {out_csv}")
    print(f"Daily diagnostics: {diag_csv}")


if __name__ == "__main__":
    main()
