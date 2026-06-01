#!/usr/bin/env python3
"""
Estimate date_of_max_flood_extent for a KuroSiwo-style flood catalogue by
scanning already-extracted daily MODIS clipped GeoTIFFs.

This version DOES NOT download or extract MODIS data. It only:
  1. loops from date_start to date_end inclusive;
  2. looks for an existing clipped GeoTIFF for each date;
  3. computes flood / missing / valid pixel fractions;
  4. selects the date maximizing a cloud-aware score:

        score = flood_fraction_valid * (1 - missing_fraction_total)

  5. writes an updated CSV preserving the original catalogue columns, with
     date_of_max_flood_extent replaced by the best MODIS-observed date.

Expected input columns:
  flood_case,country,continent,date_start,date_end,
  lat_min,lat_max,lon_min,lon_max,
  max_flood_extent_km2,date_of_max_flood_extent

Accepted date formats in the CSV:
  YYYY-MM-DD or YYYYMMDD

Expected input directory structure:
  <raster-root>/<flood_case>/MCDWD_laads_F2_YYYYMMDD_clipped.tif

Example:
  python3 estimate_modis_peak_dates_csv_only.py \
    --csv Modis_floods_events_2016_onwards.csv \
    --out Modis_floods_events_2016_onwards_peakdates.csv \
    --raster-root modis_floods_events_2016_onwards \
    --composite F2 \
    --keep-original-date-column
"""

import argparse
import csv
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

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
    """Accept YYYY-MM-DD or YYYYMMDD."""
    s = str(s).strip()
    if not s:
        raise ValueError("Empty date string")
    if "-" in s:
        return datetime.strptime(s, "%Y-%m-%d")
    return datetime.strptime(s, "%Y%m%d")


def format_date(dt: datetime, output_format: str) -> str:
    if output_format == "yyyymmdd":
        return dt.strftime("%Y%m%d")
    if output_format == "iso":
        return dt.strftime("%Y-%m-%d")
    raise ValueError(f"Unknown date output format: {output_format}")


def daterange(start: datetime, end: datetime) -> Iterable[datetime]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def sanitize_name(s: str) -> str:
    return (
        str(s)
        .replace(" ", "_")
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


def expected_tif(event_dir: Path, source: str, composite: str, date_tag: str) -> Path:
    return event_dir / f"MCDWD_{source}_{composite}_{date_tag}_clipped.tif"


def find_existing_tif(event_dir: Path, source: str, composite: str, date_tag: str) -> Optional[Path]:
    """
    Prefer the standard filename, then fall back to a glob in case the extractor
    used a slightly different naming convention.
    """
    tif = expected_tif(event_dir, source, composite, date_tag)
    if tif.exists():
        return tif

    patterns = [
        f"*{source}*{composite}*{date_tag}*clipped*.tif",
        f"*{composite}*{date_tag}*clipped*.tif",
        f"*{date_tag}*clipped*.tif",
    ]
    for pattern in patterns:
        matches = sorted(event_dir.glob(pattern))
        if matches:
            return matches[0]

    return None


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
    water_mask = (
        valid_mask & np.isin(arr, water_values)
        if water_values
        else np.zeros(arr.shape, dtype=bool)
    )

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


def midpoint_date(date_start: str, date_end: str, output_format: str) -> str:
    s = parse_date(date_start)
    e = parse_date(date_end)
    mid = s + (e - s) / 2
    return format_date(mid, output_format)


def choose_best(rows: List[Dict[str, str]], min_valid_fraction: float) -> Optional[Dict[str, str]]:
    usable = [
        r
        for r in rows
        if r.get("status") == "ok"
        and float(r.get("valid_fraction_total", 0.0)) >= min_valid_fraction
    ]
    if not usable:
        return None

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
        description=(
            "Estimate MODIS peak dates from already-extracted daily clipped GeoTIFFs. "
            "No MODIS download/extraction is performed."
        )
    )
    parser.add_argument("--csv", required=True, help="Input KuroSiwo-style CSV file")
    parser.add_argument("--out", required=True, help="Output CSV with improved date_of_max_flood_extent")
    parser.add_argument(
        "--raster-root",
        default="modis_floods_events_2016_onwards",
        help="Root directory containing one subdirectory per flood_case with daily clipped GeoTIFFs",
    )
    parser.add_argument(
        "--diag-root",
        default=None,
        help="Directory for diagnostics CSVs. Default: same as --raster-root",
    )
    parser.add_argument("--source", default="laads", help="Source tag in filename. Default: laads")
    parser.add_argument("--composite", default="F2", choices=["F1", "F1C", "F2", "F3"], help="MODIS composite to scan")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of events to process")
    parser.add_argument(
        "--date-output-format",
        choices=["yyyymmdd", "iso"],
        default="yyyymmdd",
        help="Format written to date_of_max_flood_extent. Default: yyyymmdd",
    )

    parser.add_argument(
        "--flood-values",
        type=int,
        nargs="+",
        default=[3],
        help="Raster values counted as flood. Default: 3. Use '2 3' if both recurring and unusual flood are flood.",
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
    raster_root = Path(args.raster_root)
    diag_root = Path(args.diag_root) if args.diag_root else raster_root
    diag_root.mkdir(parents=True, exist_ok=True)

    print("Input CSV:         ", in_csv)
    print("Output CSV:        ", out_csv)
    print("Raster root:       ", raster_root)
    print("Diagnostics root:  ", diag_root)
    print("Source:            ", args.source)
    print("Composite:         ", args.composite)
    print("Flood values:      ", args.flood_values)
    print("Water values:      ", args.water_values)
    print("Missing values:    ", args.missing_values)
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
            event_dir = raster_root / safe_case
            event_diag_dir = diag_root / safe_case
            event_diag_dir.mkdir(parents=True, exist_ok=True)

            start = parse_date(row["date_start"])
            end = parse_date(row["date_end"])
            if end < start:
                raise SystemExit(f"date_end before date_start for {flood_case}")

            original_peak_date = row.get("date_of_max_flood_extent", "") or midpoint_date(
                row["date_start"], row["date_end"], args.date_output_format
            )

            print("\n" + "=" * 88)
            print(f"[{i}] {flood_case}")
            print(f"Period: {row['date_start']} to {row['date_end']}")
            print(f"Event raster dir: {event_dir}")
            print("=" * 88)

            event_diag_rows: List[Dict[str, str]] = []

            for d in daterange(start, end):
                date_tag = d.strftime("%Y%m%d")
                date_out = format_date(d, args.date_output_format)
                tif = find_existing_tif(event_dir, args.source, args.composite, date_tag)

                status = "ok"
                error = ""
                metrics = None

                if tif is None:
                    status = "missing_tif"
                    tif_display = str(expected_tif(event_dir, args.source, args.composite, date_tag))
                    error = tif_display
                else:
                    tif_display = str(tif)
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

                diag = {
                    "flood_case": flood_case,
                    "country": row.get("country", ""),
                    "date": date_out,
                    "date_tag": date_tag,
                    "composite": args.composite,
                    "status": status,
                    "tif": tif_display,
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
                        f"  {date_out}  flood_valid={diag['flood_fraction_valid']}  "
                        f"missing={diag['missing_fraction_total']}  score={diag['modis_peak_score']}"
                    )
                else:
                    print(f"  {date_out}  {status} {error}")

                event_diag_rows.append(diag)
                all_diag_rows.append(diag)

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

            if event_diag_rows:
                event_diag_csv = event_diag_dir / "daily_modis_peak_diagnostics.csv"
                write_csv(event_diag_csv, event_diag_rows, list(event_diag_rows[0].keys()))

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

    diag_csv = diag_root / "all_daily_modis_peak_diagnostics.csv"
    if all_diag_rows:
        write_csv(diag_csv, all_diag_rows, list(all_diag_rows[0].keys()))

    print("\nDone.")
    print(f"Updated event CSV: {out_csv}")
    print(f"Daily diagnostics: {diag_csv}")


if __name__ == "__main__":
    main()
