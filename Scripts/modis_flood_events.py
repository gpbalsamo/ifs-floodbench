#!/usr/bin/env python3
"""
Batch run MODIS extraction + plotting for all flood events in a csv file:
    KuroSiwo_events.csv

Expected CSV columns:
    flood_case,country,continent,date_start,date_end,
    lat_min,lat_max,lon_min,lon_max,
    max_flood_extent_km2,date_of_max_flood_extent

For each event:
    - use date_of_max_flood_extent as the MODIS date
    - build area as [North, West, South, East] = [lat_max, lon_min, lat_min, lon_max]
    - run extract_modis_flood.py
    - run plot_modis_flood.py

Example:
    python3 modis_flood_event.py \
        --csv KuroSiwo_events.csv \
        --outroot modis_kuroSiwo \
        --composite F2
"""

import csv
import argparse
import subprocess
from pathlib import Path
import os


def run_cmd(cmd, dry_run=False):
    print("\nRunning:")
    print(" ".join(str(c) for c in cmd))

    if dry_run:
        return 0

    p = subprocess.run(cmd)
    return p.returncode


def sanitize_name(s):
    """Safe directory/file-friendly string."""
    return (
        s.replace(" ", "_")
         .replace("/", "_")
         .replace("(", "")
         .replace(")", "")
         .replace(",", "")
         .replace("’", "")
         .replace("'", "")
    )


def main():
    parser = argparse.ArgumentParser(
        description="Batch process KuroSiwo events with MODIS flood extraction and plotting."
    )

    parser.add_argument(
        "--csv",
        required=True,
        help="Input CSV file, e.g. KuroSiwo_events.csv",
    )

    parser.add_argument(
        "--outroot",
        default="modis_kuroSiwo",
        help="Root output directory",
    )

    parser.add_argument(
        "--composite",
        default="F2",
        choices=["F1", "F1C", "F2", "F3"],
        help="MODIS composite to use. Default: F2",
    )

    parser.add_argument(
        "--padding",
        type=float,
        default=0.0,
        help="Optional geographic padding in degrees added around the event bbox.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of events to process.",
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip event if final plot PNG already exists.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running them.",
    )

    args = parser.parse_args()

    csv_file = Path(args.csv)
    outroot = Path(args.outroot)
    outroot.mkdir(parents=True, exist_ok=True)

    print("Current working directory:", os.getcwd())
    print("CSV file requested: ", args.csv)
    print("CSV file resolved:  ", csv_file)
    print("CSV file exists:    ", csv_file.exists())

    summary_file = outroot / "batch_summary.csv"

    rows_processed = 0
    summary_rows = []

    with open(csv_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=",")

        # Clean header names
        reader.fieldnames = [
            name.strip().replace("\ufeff", "")
            for name in reader.fieldnames
        ]

        print("CSV columns found:")
        print(reader.fieldnames)

        for row in reader:
            # Clean row keys as well
            row = {
                k.strip().replace("\ufeff", ""): v.strip()
                for k, v in row.items()
                if k is not None and v is not None
            }

            flood_case = row["flood_case"]
            country = row["country"]
            date_modis = row["date_of_max_flood_extent"]
            lat_min = float(row["lat_min"])
            lat_max = float(row["lat_max"])
            lon_min = float(row["lon_min"])
            lon_max = float(row["lon_max"])

            pad = args.padding

            north = lat_max + pad
            west = lon_min - pad
            south = lat_min - pad
            east = lon_max + pad

            # Per-event output directory
            safe_case = sanitize_name(flood_case)
            event_dir = outroot / safe_case
            event_dir.mkdir(parents=True, exist_ok=True)

            date_tag = date_modis.replace("-", "")
            composite = args.composite

            clipped_tif = event_dir / f"MCDWD_laads_{composite}_{date_tag}_clipped.tif"
            plot_png = event_dir / f"MCDWD_{composite}_{date_tag}_flood_missing.png"

            if args.skip_existing and plot_png.exists():
                print(f"\nSkipping {flood_case}: output already exists")
                summary_rows.append(
                    {
                        "flood_case": flood_case,
                        "country": country,
                        "date": date_modis,
                        "status": "skipped_existing",
                        "output_png": str(plot_png),
                    }
                )
                rows_processed += 1
                continue

            extract_cmd = [
                "python3",
                "extract_modis_flood.py",
                "--date", date_modis,
                "--area", str(north), str(west), str(south), str(east),
                "--composite", composite,
                "--outdir", str(event_dir),
            ]

            plot_cmd = [
                "python3",
                "plot_modis_flood.py",
                "--input", str(clipped_tif),
                "--flood-case", f"{flood_case} | {country} | {date_modis} | MODIS {composite}",
                "--output", str(plot_png),
            ]

            print("\n" + "=" * 80)
            print(f"Processing: {flood_case}")
            print(f"Country:    {country}")
            print(f"Date:       {date_modis}")
            print(f"Area:       N={north}, W={west}, S={south}, E={east}")
            print("=" * 80)

            rc1 = run_cmd(extract_cmd, dry_run=args.dry_run)

            if rc1 != 0:
                print(f"Extraction failed for {flood_case}")
                summary_rows.append(
                    {
                        "flood_case": flood_case,
                        "country": country,
                        "date": date_modis,
                        "status": f"extract_failed_{rc1}",
                        "output_png": "",
                    }
                )
                rows_processed += 1
                continue

            rc2 = run_cmd(plot_cmd, dry_run=args.dry_run)

            if rc2 != 0:
                print(f"Plotting failed for {flood_case}")
                summary_rows.append(
                    {
                        "flood_case": flood_case,
                        "country": country,
                        "date": date_modis,
                        "status": f"plot_failed_{rc2}",
                        "output_png": "",
                    }
                )
            else:
                summary_rows.append(
                    {
                        "flood_case": flood_case,
                        "country": country,
                        "date": date_modis,
                        "status": "ok",
                        "output_png": str(plot_png),
                    }
                )

            rows_processed += 1

    with open(summary_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["flood_case", "country", "date", "status", "output_png"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    print("\nDone.")
    print(f"Processed events: {rows_processed}")
    print(f"Summary written to: {summary_file}")


if __name__ == "__main__":
    main()
