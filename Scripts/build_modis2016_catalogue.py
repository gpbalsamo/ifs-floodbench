#!/usr/bin/env python3
"""
build_modis2016_catalogue.py

Builds the catalogue CSV for the standalone "post-2016 named events"
MODIS-only dashboard (kept separate from KuroSiwo_events.csv / the
KuroSiwo dashboard -- these are hand-picked notable global floods, not
part of the KuroSiwo benchmark).

Combines:
  * The authoritative event metadata CSV (event_name, start_date,
    end_date, country, continent, bbox_north/west/south/east,
    approx_flooded_area_km2, main_river_system) -- e.g.
    Notebooks/Modis_events.csv.
  * The already-picked peak observation date + clipped MODIS GeoTIFF
    per event from a modis_flood_events.py-style batch run's
    batch_summary.csv -- e.g.
    flood_cases/modis_floods_events_2016_onwards/.

Writes a KuroSiwo-style catalogue CSV (flood_case, country, continent,
date_start, date_end, lat_min, lat_max, lon_min, lon_max,
max_flood_extent_km2, date_of_max_flood_extent, main_river_system) and
copies each event's peak-date clipped GeoTIFF into
<modis-dir>/<flood_case>/ for build_dashboard_manifest.py.

Example:
    python3 build_modis2016_catalogue.py \
        --events-csv Notebooks/Modis_events.csv \
        --batch-root flood_cases/modis_floods_events_2016_onwards \
        --out Modis2016_events.csv \
        --modis-dir modis2016_events
"""

import ast
import csv
import shutil
import argparse
from pathlib import Path


def to_flood_case(event_name):
    return event_name.replace(" ", "_").replace("-", "_")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events-csv", required=True,
                         help="Authoritative event metadata CSV (event_name, start_date, end_date, "
                              "country, continent, bbox_north/west/south/east, "
                              "approx_flooded_area_km2, main_river_system).")
    parser.add_argument("--batch-root", required=True,
                         help="Directory with batch_summary.csv + one subdir per event "
                              "(each containing MCDWD_*_<date>_clipped.tif).")
    parser.add_argument("--out", default="Modis2016_events.csv")
    parser.add_argument("--modis-dir", required=True,
                         help="modis_flood_events.py-style output root; the peak-date clipped "
                              "GeoTIFF is copied to <modis-dir>/<flood_case>/")
    args = parser.parse_args()

    batch_root = Path(args.batch_root)
    modis_dir = Path(args.modis_dir)

    with open(batch_root / "batch_summary.csv", newline="") as f:
        peak_dates = {row["flood_case"]: ast.literal_eval(row["date"])[0]
                      for row in csv.DictReader(f)}

    fieldnames = ["flood_case", "country", "continent", "date_start", "date_end",
                  "lat_min", "lat_max", "lon_min", "lon_max",
                  "max_flood_extent_km2", "date_of_max_flood_extent", "main_river_system"]
    rows = []

    with open(args.events_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            flood_case = to_flood_case(row["event_name"])
            date = peak_dates.get(flood_case)
            if date is None:
                print(f"[{flood_case}] no peak-date entry in batch_summary.csv, skipping")
                continue
            date_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"

            tifs = sorted((batch_root / flood_case).glob(f"MCDWD_*_{date}_clipped.tif"))
            if not tifs:
                print(f"[{flood_case}] no clipped GeoTIFF for {date}, skipping")
                continue

            dest_dir = modis_dir / flood_case
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tifs[0], dest_dir / tifs[0].name)

            rows.append({
                "flood_case": flood_case,
                "country": row["country"].replace(";", " / "),
                "continent": row["continent"],
                "date_start": row["start_date"],
                "date_end": row["end_date"],
                "lat_min": row["bbox_south"], "lat_max": row["bbox_north"],
                "lon_min": row["bbox_west"], "lon_max": row["bbox_east"],
                "max_flood_extent_km2": row["approx_flooded_area_km2"],
                "date_of_max_flood_extent": date_iso,
                "main_river_system": row["main_river_system"],
            })
            print(f"[{flood_case}] {row['country']} / {row['continent']} peak={date_iso}")

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} events to {args.out}")


if __name__ == "__main__":
    main()
