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
import json
import shutil
import argparse
import subprocess
from math import ceil
from pathlib import Path
from datetime import datetime, timedelta


DEFAULT_ATLANTIS_BIN = "/perm/pad/atlantis/.venv/bin/atlantis"

# Sources that produce a *_<source>_harmonised.tif once fetched.
ALL_SOURCES = ["viirs", "gfm", "modis"]

# Above this width/height (degrees), a fetch is split into a grid of
# sub-tiles instead of one atlantis call over the full bbox. Continental
# event bboxes (e.g. Pakistan monsoon, Amazon) OOM or time out when fetched
# whole -- the cost is driven by the AOI's pixel count at native sensor
# resolution, not by the number of days in the fetch window, so shrinking
# the date window alone doesn't help. Libya_Derna_Floods (~3.8x4.5 deg)
# fetches fine unsplit, so this default has some headroom below that.
DEFAULT_MAX_TILE_DEG = 5.0

# harmonised.tif (all sources) and gfm's processed/permanent_water.tif are
# written on the same canonical ~1 arcmin global grid (snapped to a global
# origin), so adjacent tiles merge directly with rasterio.merge -- no
# reprojection needed. VIIRS/MODIS processed/permanent_water.tif is native
# per-scene resolution/extent instead and is NOT safe to merge this way;
# it isn't needed here since VIIRS is excluded from reference-water
# picking and MODIS reference water comes from a separate non-atlantis
# pipeline (see overlay_utils.pick_event_reference_water).
HARMONISED_NODATA = 255


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


# atlantis's default MODIS backend (lance_geotiff) only serves the last
# ~1 week of near-real-time data; every event in these catalogues is older
# than that, so a MODIS harmonised.tif can never appear here regardless of
# how many times a tile/event is retried. Excluded from skip-existing
# detection only (not from what's fetched -- the attempt itself is cheap,
# it just fails fast) so its permanent absence doesn't block skip logic for
# viirs/gfm, which do succeed. The dashboards' own MODIS layer comes from a
# separate, non-atlantis pipeline (build_modis2016_catalogue.py /
# extract_modis_flood.py), so this doesn't affect what ends up on the map.
SKIP_CHECK_EXCLUDE_SOURCES = {"modis"}


def _coverage_sidecar_path(event_dir):
    """
    Per-event JSON recording, per source, how many of the tiles the bbox
    was split into actually produced a harmonised.tif when a tiled fetch
    last ran (see run_tiled_event). A tile-fetch batch can be interrupted
    (SLURM timeout, an earlier OOM kill, a killed session) and resumed
    later with --skip-existing; without this, a mosaic silently built from
    a subset of tiles (e.g. only the tiles that happened to survive an
    earlier interrupted run) looks identical on disk to a complete one --
    both just have *a* harmonised.tif -- so a resume would skip the event
    entirely and the gap would never get filled. This file lets
    harmonised_outputs_exist tell "complete" apart from "partial".
    """
    return event_dir / "_tile_coverage.json"


def harmonised_outputs_exist(event_dir, sources):
    """
    True if every requested source already has a harmonised GeoTIFF AND
    (for a tiled fetch) every tile the bbox was split into contributed to
    it -- see _coverage_sidecar_path. An event/tile with no coverage
    sidecar (non-tiled fetch) is judged on file existence alone, as
    before.
    """
    sources = [s for s in sources if s not in SKIP_CHECK_EXCLUDE_SOURCES]
    coverage = {}
    sidecar = _coverage_sidecar_path(event_dir)
    if sidecar.exists():
        try:
            coverage = json.loads(sidecar.read_text())
        except (json.JSONDecodeError, OSError):
            coverage = {}

    for source in sources:
        harmonised_dir = event_dir / source / "harmonised"
        if not harmonised_dir.is_dir():
            return False
        if not list(harmonised_dir.glob("*_harmonised.tif")):
            return False
        cov = coverage.get(source)
        if cov and cov.get("ok_tiles", 0) < cov.get("total_tiles", 0):
            return False
    return True


def split_bbox(lon_min, lat_min, lon_max, lat_max, max_deg):
    """
    Split a bbox into a grid of sub-tiles, each no wider/taller than
    max_deg, by dividing each axis into equal-sized shares (not fixed-size
    tiles with a ragged remainder). Returns a list of
    (lon_min, lat_min, lon_max, lat_max) tuples.
    """
    width = lon_max - lon_min
    height = lat_max - lat_min
    n_lon = max(1, ceil(width / max_deg))
    n_lat = max(1, ceil(height / max_deg))

    tiles = []
    for j in range(n_lat):
        tile_lat_min = lat_min + j * height / n_lat
        tile_lat_max = lat_min + (j + 1) * height / n_lat
        for i in range(n_lon):
            tile_lon_min = lon_min + i * width / n_lon
            tile_lon_max = lon_min + (i + 1) * width / n_lon
            tiles.append((tile_lon_min, tile_lat_min, tile_lon_max, tile_lat_max))
    return tiles


def mosaic_geotiffs(tile_paths, out_path):
    """
    Merge same-grid GeoTIFF tiles (uint8, nodata=255) into one file via
    rasterio.merge -- valid only for atlantis outputs that share the
    canonical global grid (harmonised.tif for all sources; gfm's
    processed/permanent_water.tif). See HARMONISED_NODATA note above.
    """
    import rasterio
    from rasterio.merge import merge

    srcs = [rasterio.open(p) for p in tile_paths]
    try:
        merged, merged_transform = merge(srcs, nodata=HARMONISED_NODATA)
        crs = srcs[0].crs
    finally:
        for s in srcs:
            s.close()

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "count": 1,
        "height": merged.shape[1],
        "width": merged.shape[2],
        "crs": crs,
        "transform": merged_transform,
        "nodata": HARMONISED_NODATA,
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(merged[0], 1)
    return out_path


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


def run_atlantis_fetch(atlantis_bin, flood_case, source_arg, requested_sources, output_dir,
                        bbox, start_date, end_date, modis_composite, timeout, dry_run=False,
                        modis_backend="lance_geotiff"):
    """
    Run one atlantis fetch per requested source. atlantis's own --source flag
    only accepts a single value or "all" (not a comma list), so when
    source_arg == "all" this is one combined call as before; otherwise each
    source in requested_sources gets its own atlantis invocation (e.g. to
    fetch viirs+modis without touching a slow/expensive gfm run). Returns
    the worst (most negative / most "failed") returncode across calls, or 0
    if every call succeeded.
    """
    if source_arg == "all":
        source_calls = ["all"]
    else:
        source_calls = requested_sources

    worst_rc = 0
    for source in source_calls:
        cmd = [
            atlantis_bin, "fetch",
            "--event", flood_case,
            "--source", source,
            "--output", str(output_dir),
            "--bbox", bbox,
            "--start-date", start_date,
            "--end-date", end_date,
            "--modis-composite", modis_composite,
            "--modis-backend", modis_backend,
            "--harmonise",
            "--strategy", "peak",
        ]
        rc = run_cmd(cmd, dry_run=dry_run, timeout=timeout)
        if rc != 0:
            worst_rc = rc
    return worst_rc


def run_tiled_event(flood_case, row, args, event_dir, bbox_bounds, start_date, end_date,
                     requested_sources, keep_tile_dirs=False):
    """
    Fetch one event whose bbox exceeds --max-tile-deg by splitting it into
    a grid of smaller sub-tiles (each fetched via run_atlantis_fetch,
    --strategy peak), then mosaicking each source's
    harmonised.tif (and gfm's permanent_water.tif) back into a single
    file under event_dir, matching the layout a non-tiled fetch produces.

    Per-tile --strategy peak can pick a different date in each sub-tile
    (different parts of a continental event may flood on different days
    within the window); the mosaic is labelled with the catalogue's
    date_of_max_flood_extent rather than any one tile's date, since it's a
    composite of whichever near-peak scene was clearest in each sub-area.

    Returns a status string for the batch summary.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_bounds
    tiles = split_bbox(lon_min, lat_min, lon_max, lat_max, args.max_tile_deg)
    tiles_root = event_dir / "_tiles"

    print(f"Bbox {lon_max - lon_min:.1f}x{lat_max - lat_min:.1f} deg exceeds "
          f"--max-tile-deg {args.max_tile_deg}: splitting into {len(tiles)} tile(s)")

    for ti, (t_lon_min, t_lat_min, t_lon_max, t_lat_max) in enumerate(tiles):
        tile_dir = tiles_root / f"tile_{ti:02d}"
        bbox = f"{t_lon_min} {t_lat_min} {t_lon_max} {t_lat_max}"
        print(f"\n-- tile {ti + 1}/{len(tiles)}: bbox {bbox} --")

        if args.skip_existing and harmonised_outputs_exist(tile_dir, requested_sources):
            print(f"[tile {ti:02d}] skipping: harmonised outputs already exist")
            continue

        rc = run_atlantis_fetch(
            args.atlantis_bin, flood_case, args.source, requested_sources, tile_dir,
            bbox, start_date, end_date, args.modis_composite, args.timeout,
            dry_run=args.dry_run, modis_backend=args.modis_backend,
        )
        if rc != 0:
            print(f"[tile {ti:02d}] at least one source failed (rc={rc}), continuing with remaining tiles")

    if args.dry_run:
        return "ok"

    peak_token = parse_date(row["date_of_max_flood_extent"]).strftime("%Y%m%d")
    total_tiles = len(tiles)
    coverage = {}
    status_parts = []
    any_incomplete = False

    for source in requested_sources:
        harmonised_tifs = sorted(tiles_root.glob(f"tile_*/{source}/harmonised/*_harmonised.tif"))
        # Count distinct contributing tile dirs, not files, in case a tile
        # ever produced more than one date's harmonised.tif.
        n_ok = len({p.parents[2] for p in harmonised_tifs})
        coverage[source] = {"ok_tiles": n_ok, "total_tiles": total_tiles}

        status_relevant = source not in SKIP_CHECK_EXCLUDE_SOURCES

        if n_ok == 0:
            if status_relevant:
                status_parts.append(f"{source}:missing")
                any_incomplete = True
            continue

        out_tif = event_dir / source / "harmonised" / f"{flood_case}_{peak_token}_{source}_harmonised.tif"
        mosaic_geotiffs(harmonised_tifs, out_tif)
        print(f"[{source}] mosaicked {n_ok}/{total_tiles} tile(s) -> {out_tif}")

        if n_ok < total_tiles:
            if status_relevant:
                status_parts.append(f"{source}:{n_ok}/{total_tiles}")
                any_incomplete = True
        elif status_relevant:
            status_parts.append(f"{source}:ok")

        if source == "gfm":
            pw_tifs = sorted(tiles_root.glob("tile_*/gfm/processed/*_permanent_water.tif"))
            if pw_tifs:
                out_pw = event_dir / "gfm" / "processed" / f"{flood_case}_{peak_token}_gfm_permanent_water.tif"
                mosaic_geotiffs(pw_tifs, out_pw)
                print(f"[gfm] mosaicked {len(pw_tifs)} permanent_water tile(s) -> {out_pw}")

    event_dir.mkdir(parents=True, exist_ok=True)
    _coverage_sidecar_path(event_dir).write_text(json.dumps(coverage, indent=2))

    # Only clean up tiles once every requested source has full coverage --
    # an incomplete tile set needs to survive so a later --skip-existing
    # resume can find and reuse the tiles that already succeeded instead
    # of silently accepting the gap or refetching everything from scratch.
    if not keep_tile_dirs and not any_incomplete:
        shutil.rmtree(tiles_root, ignore_errors=True)

    if all(c["ok_tiles"] == 0 for c in coverage.values()):
        return "failed_all_tiles"
    return "partial_" + "_".join(status_parts) if any_incomplete else "ok"


def main():
    parser = argparse.ArgumentParser(
        description="Batch-fetch VIIRS/GFM/MODIS observations for a "
                     "KuroSiwo catalogue via the atlantis CLI."
    )
    parser.add_argument("--csv", required=True, help="KuroSiwo-style CSV catalogue")
    parser.add_argument("--outroot", default="kurosiwo_observations",
                         help="Root output directory")
    parser.add_argument("--source", default="all",
                         help="atlantis source(s): gfm, viirs, modis, a comma list (e.g. "
                              "'viirs,modis' to skip gfm), or all. A comma list runs one "
                              "atlantis call per source instead of one combined --source all "
                              "call (atlantis itself only accepts a single value or 'all'). "
                              "Default: all")
    parser.add_argument("--atlantis-bin", default=DEFAULT_ATLANTIS_BIN,
                         help=f"Path to the atlantis executable. Default: {DEFAULT_ATLANTIS_BIN}")
    parser.add_argument("--padding", type=float, default=0.0,
                         help="Optional geographic padding in degrees around the event bbox.")
    parser.add_argument("--window-days", type=int, default=0,
                         help="If set, fetch a +/- N day window around date_of_max_flood_extent "
                              "instead of the full date_start..date_end catalogue window.")
    parser.add_argument("--modis-composite", default="F2", choices=["F1", "F1C", "F2", "F3"])
    parser.add_argument("--modis-backend", default="lance_geotiff", choices=["lance_geotiff", "laads_hdf4"],
                         help="atlantis MODIS backend. lance_geotiff (default) only serves the "
                              "last ~1 week of near-real-time data -- use laads_hdf4 for any "
                              "event older than that (2003-2025 reprocessed archive).")
    parser.add_argument("--limit", type=int, default=None,
                         help="Optional limit on number of events to process.")
    parser.add_argument("--skip-existing", action="store_true",
                         help="Skip events that already have harmonised GeoTIFFs for all requested sources.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print atlantis commands without running them.")
    parser.add_argument("--timeout", type=int, default=600,
                         help="Per-event timeout in seconds (per-tile, if the event is split); "
                              "a hung fetch is killed and recorded as failed so the batch keeps "
                              "going. Default: 600.")
    parser.add_argument("--max-tile-deg", type=float, default=DEFAULT_MAX_TILE_DEG,
                         help="If an event's bbox is wider or taller than this many degrees, "
                              "split it into a grid of sub-tiles fetched separately and "
                              "mosaicked back together, instead of one atlantis call over the "
                              f"whole bbox. Default: {DEFAULT_MAX_TILE_DEG} (continental bboxes "
                              "OOM/timeout the underlying fetch regardless of --window-days).")
    parser.add_argument("--keep-tile-dirs", action="store_true",
                         help="Keep each tile's raw atlantis output under <event>/_tiles/ after "
                              "mosaicking, instead of deleting it to save disk.")
    args = parser.parse_args()

    csv_file = Path(args.csv)
    outroot = Path(args.outroot)
    outroot.mkdir(parents=True, exist_ok=True)

    requested_sources = ALL_SOURCES if args.source == "all" else [s.strip() for s in args.source.split(",")]
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
        bbox_lon_min, bbox_lat_min = lon_min - pad, lat_min - pad
        bbox_lon_max, bbox_lat_max = lon_max + pad, lat_max + pad

        start_date, end_date = event_window(row, args.window_days)

        needs_tiling = (
            (bbox_lon_max - bbox_lon_min) > args.max_tile_deg
            or (bbox_lat_max - bbox_lat_min) > args.max_tile_deg
        )

        if needs_tiling:
            status = run_tiled_event(
                flood_case, row, args, event_dir,
                (bbox_lon_min, bbox_lat_min, bbox_lon_max, bbox_lat_max),
                start_date, end_date, requested_sources,
                keep_tile_dirs=args.keep_tile_dirs,
            )
        else:
            # atlantis bbox convention: "west south east north"
            bbox = f"{bbox_lon_min} {bbox_lat_min} {bbox_lon_max} {bbox_lat_max}"
            rc = run_atlantis_fetch(
                args.atlantis_bin, flood_case, args.source, requested_sources, event_dir,
                bbox, start_date, end_date, args.modis_composite, args.timeout,
                dry_run=args.dry_run, modis_backend=args.modis_backend,
            )
            status = "ok" if rc == 0 else f"failed_{rc}"

        summary_rows.append({
            "flood_case": flood_case,
            "status": status,
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
