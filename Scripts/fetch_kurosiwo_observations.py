#!/usr/bin/env python3
"""
fetch_kurosiwo_observations.py

Batch-fetch EO flood observations (VIIRS, GFM, MODIS) for every event in a
KuroSiwo-style CSV catalogue, using the `atlantis` CLI
(https://github.com/opageo/atlantis) as the fetch/harmonisation backend.

For each event, this calls:

    atlantis fetch --event <flood_case> --source <source> \
        --bbox "<west> <south> <east> <north>" \
        --start-date <...> --end-date <...> \
        --harmonise --strategy peak \
        --output <outroot>/<flood_case>/atlantis

Atlantis harmonises every source to a common 1 arcmin grid and writes
`<event>_<date>_<source>_harmonised.tif`, which `build_dashboard_manifest.py`
later turns into map overlay PNGs alongside the CaMa-Flood model layer.

Expected CSV columns (same catalogue used by modis_flood_events.py):
    flood_case,country,continent,date_start,date_end,
    lat_min,lat_max,lon_min,lon_max,
    max_flood_extent_km2,date_of_max_flood_extent

Example:
    python3 fetch_kurosiwo_observations.py \
        --csv KuroSiwo_events.csv \
        --outroot kurosiwo_observations \
        --source all \
        --window-days 3 \
        --skip-existing
"""

import csv
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta


DEFAULT_ATLANTIS_BIN = "/perm/pad/atlantis/.venv/bin/atlantis"

# Sources that produce a *_<source>_harmonised.tif once fetched.
ALL_SOURCES = ["viirs", "gfm", "modis"]


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


def parse_date(s):
    s = str(s).strip()
    if "-" in s:
        return datetime.strptime(s, "%Y-%m-%d")
    return datetime.strptime(s, "%Y%m%d")


def event_window(row, window_days):
    """
    Returns (start_date, end_date) as YYYY-MM-DD strings.

    If --window-days is given, use a symmetric window around
    date_of_max_flood_extent. Otherwise use date_start/date_end from the
    catalogue.
    """
    if window_days:
        peak = parse_date(row["date_of_max_flood_extent"])
        start = peak - timedelta(days=window_days)
        end = peak + timedelta(days=window_days)
    else:
        start = parse_date(row["date_start"])
        end = parse_date(row["date_end"])
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def harmonised_outputs_exist(event_dir, sources):
    """True if every requested source already has a harmonised GeoTIFF."""
    for source in sources:
        harmonised_dir = event_dir / source / "harmonised"
        if not harmonised_dir.is_dir():
            return False
        if not list(harmonised_dir.glob("*_harmonised.tif")):
            return False
    return True


def run_cmd(cmd, dry_run=False, timeout=600):
    print("\nRunning:")
    print(" ".join(str(c) for c in cmd))

    if dry_run:
        return 0

    try:
        p = subprocess.run(cmd, timeout=timeout)
        return p.returncode
    except subprocess.TimeoutExpired:
        print(f"[timeout] command exceeded {timeout}s, treating as failed and continuing")
        return -1


def main():
    parser = argparse.ArgumentParser(
        description="Batch-fetch VIIRS/GFM/MODIS observations for a "
                     "KuroSiwo catalogue via the atlantis CLI."
    )
    parser.add_argument("--csv", required=True, help="KuroSiwo-style CSV catalogue")
    parser.add_argument("--outroot", default="kurosiwo_observations",
                         help="Root output directory")
    parser.add_argument("--source", default="all",
                         help="atlantis source(s): gfm, viirs, modis, or all. Default: all")
    parser.add_argument("--atlantis-bin", default=DEFAULT_ATLANTIS_BIN,
                         help=f"Path to the atlantis executable. Default: {DEFAULT_ATLANTIS_BIN}")
    parser.add_argument("--padding", type=float, default=0.0,
                         help="Optional geographic padding in degrees around the event bbox.")
    parser.add_argument("--window-days", type=int, default=0,
                         help="If set, fetch a +/- N day window around date_of_max_flood_extent "
                              "instead of the full date_start..date_end catalogue window.")
    parser.add_argument("--modis-composite", default="F2", choices=["F1", "F1C", "F2", "F3"])
    parser.add_argument("--limit", type=int, default=None,
                         help="Optional limit on number of events to process.")
    parser.add_argument("--skip-existing", action="store_true",
                         help="Skip events that already have harmonised GeoTIFFs for all requested sources.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print atlantis commands without running them.")
    parser.add_argument("--timeout", type=int, default=600,
                         help="Per-event timeout in seconds; a hung fetch is killed and "
                              "recorded as failed so the batch keeps going. Default: 600.")
    args = parser.parse_args()

    csv_file = Path(args.csv)
    outroot = Path(args.outroot)
    outroot.mkdir(parents=True, exist_ok=True)

    requested_sources = ALL_SOURCES if args.source == "all" else [args.source]
    summary_file = outroot / "batch_summary.csv"
    summary_rows = []

    with open(csv_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [name.strip().replace("﻿", "") for name in reader.fieldnames]
        rows = [
            {k.strip().replace("﻿", ""): v.strip() for k, v in row.items() if k is not None and v is not None}
            for row in reader
        ]

    if args.limit:
        rows = rows[: args.limit]

    for i, row in enumerate(rows, start=1):
        flood_case = row["flood_case"]
        safe_case = sanitize_name(flood_case)
        event_dir = outroot / safe_case / "atlantis"

        print("\n" + "=" * 80)
        print(f"[{i:03d}/{len(rows)}] {flood_case} ({row.get('country', 'Unknown')})")

        if args.skip_existing and harmonised_outputs_exist(event_dir, requested_sources):
            print(f"Skipping {flood_case}: harmonised outputs already exist")
            summary_rows.append({"flood_case": flood_case, "status": "skipped_existing", "output_dir": str(event_dir)})
            continue

        lat_min, lat_max = float(row["lat_min"]), float(row["lat_max"])
        lon_min, lon_max = float(row["lon_min"]), float(row["lon_max"])
        pad = args.padding
        # atlantis bbox convention: "west south east north"
        bbox = f"{lon_min - pad} {lat_min - pad} {lon_max + pad} {lat_max + pad}"

        start_date, end_date = event_window(row, args.window_days)

        cmd = [
            args.atlantis_bin, "fetch",
            "--event", flood_case,
            "--source", args.source,
            "--output", str(event_dir),
            "--bbox", bbox,
            "--start-date", start_date,
            "--end-date", end_date,
            "--modis-composite", args.modis_composite,
            "--harmonise",
            "--strategy", "peak",
        ]

        rc = run_cmd(cmd, dry_run=args.dry_run, timeout=args.timeout)

        summary_rows.append({
            "flood_case": flood_case,
            "status": "ok" if rc == 0 else f"failed_{rc}",
            "output_dir": str(event_dir),
        })

    with open(summary_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["flood_case", "status", "output_dir"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print("\nDone.")
    print(f"Processed events: {len(summary_rows)}")
    print(f"Summary written to: {summary_file}")


if __name__ == "__main__":
    main()
