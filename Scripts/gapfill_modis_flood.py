#!/usr/bin/env python3

import argparse
import csv
import re
from pathlib import Path
from datetime import datetime

import numpy as np
import rasterio
from rasterio.windows import Window


MAX_GAP_DAYS = 5

NO_WATER = 0
PERMANENT_WATER = 1
RECURRING_FLOOD = 2
UNUSUAL_FLOOD = 3
MISSING = 255


def extract_date(path: Path) -> datetime:
    m = re.search(r"(19\d{6}|20\d{6})", path.name)
    if not m:
        raise ValueError(f"Cannot find YYYYMMDD date in filename: {path.name}")
    return datetime.strptime(m.group(1), "%Y%m%d")


def fill_value_from_bounds(left_val, right_val):
    """
    Conservative temporal filling.
    Keeps original MODIS classes.
    """

    if left_val == right_val:
        return int(left_val)

    # If both sides are flood, fill as unusual flood.
    if left_val in (RECURRING_FLOOD, UNUSUAL_FLOOD) and right_val in (
        RECURRING_FLOOD,
        UNUSUAL_FLOOD,
    ):
        return UNUSUAL_FLOOD

    return None


def gapfill_block(stack, dates):
    """
    stack shape: time, y, x

    Classes:
      0   no water
      1   permanent/surface water
      2   recurring flood
      3   unusual flood
      255 missing

    Only 255 pixels are modified.
    """

    nt, ny, nx = stack.shape
    out = stack.copy()

    stats = {
        "missing_before": int((stack == MISSING).sum()),
        "missing_after": 0,
        "missing_reduced": 0,
        "propagated_permanent_water": 0,
        "filled_no_water": 0,
        "filled_permanent_water": 0,
        "filled_recurring_flood": 0,
        "filled_unusual_flood": 0,
    }

    # Propagate permanent water through time, but only into missing pixels.
    permanent_mask = np.any(stack == PERMANENT_WATER, axis=0)

    for t in range(nt):
        fill_perm = permanent_mask & (out[t] == MISSING)
        n = int(fill_perm.sum())
        if n:
            out[t, fill_perm] = PERMANENT_WATER
            stats["propagated_permanent_water"] += n
            stats["filled_permanent_water"] += n

    # Fill remaining short temporal gaps.
    for y in range(ny):
        for x in range(nx):

            if permanent_mask[y, x]:
                continue

            values = out[:, y, x]

            if not np.any(values == MISSING):
                continue

            i = 0
            while i < nt:

                if values[i] != MISSING:
                    i += 1
                    continue

                gap_start = i

                while i < nt and values[i] == MISSING:
                    i += 1

                gap_end = i - 1

                left_idx = gap_start - 1
                right_idx = gap_end + 1

                if left_idx < 0 or right_idx >= nt:
                    continue

                left_val = values[left_idx]
                right_val = values[right_idx]

                if left_val == MISSING or right_val == MISSING:
                    continue

                gap_days = (dates[right_idx] - dates[left_idx]).days

                if gap_days > MAX_GAP_DAYS:
                    continue

                fill_val = fill_value_from_bounds(left_val, right_val)

                if fill_val is None:
                    continue

                nfill = gap_end - gap_start + 1
                values[gap_start : gap_end + 1] = fill_val

                if fill_val == NO_WATER:
                    stats["filled_no_water"] += nfill
                elif fill_val == PERMANENT_WATER:
                    stats["filled_permanent_water"] += nfill
                elif fill_val == RECURRING_FLOOD:
                    stats["filled_recurring_flood"] += nfill
                elif fill_val == UNUSUAL_FLOOD:
                    stats["filled_unusual_flood"] += nfill

            out[:, y, x] = values

    stats["missing_after"] = int((out == MISSING).sum())
    stats["missing_reduced"] = stats["missing_before"] - stats["missing_after"]

    return out, stats


def add_stats(total, block_stats):
    for k, v in block_stats.items():
        total[k] = total.get(k, 0) + int(v)


def main():
    parser = argparse.ArgumentParser(
        description="Blockwise temporal gap filling for MODIS MCDWD flood sequences."
    )

    parser.add_argument("--indir", required=True)
    parser.add_argument(
        "--pattern",
        default="MCDWD_laads_F2_*_clipped.tif",
    )
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--block-size", type=int, default=512)
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    indir = Path(args.indir)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    files = sorted(indir.glob(args.pattern), key=extract_date)

    if not files:
        raise FileNotFoundError(f"No files found in {indir} matching {args.pattern}")

    dates = [extract_date(f) for f in files]

    print(f"Input directory:  {indir}")
    print(f"Output directory: {outdir}")
    print(f"Number of files:  {len(files)}")
    print(f"MAX_GAP_DAYS:     {MAX_GAP_DAYS}")
    print(f"Block size:       {args.block_size}")

    srcs = [rasterio.open(f) for f in files]

    total_stats = {
        "missing_before": 0,
        "missing_after": 0,
        "missing_reduced": 0,
        "propagated_permanent_water": 0,
        "filled_no_water": 0,
        "filled_permanent_water": 0,
        "filled_recurring_flood": 0,
        "filled_unusual_flood": 0,
    }

    try:
        profile = srcs[0].profile.copy()
        height = srcs[0].height
        width = srcs[0].width
        transform = srcs[0].transform
        crs = srcs[0].crs

        for src in srcs[1:]:
            if src.height != height or src.width != width:
                raise ValueError(f"Raster size mismatch: {src.name}")
            if src.transform != transform:
                raise ValueError(f"Raster transform mismatch: {src.name}")
            if src.crs != crs:
                raise ValueError(f"Raster CRS mismatch: {src.name}")

        profile.update(
            dtype="uint8",
            count=1,
            nodata=MISSING,
            compress="lzw",
        )

        dsts = []

        for f in files:
            out_name = f.name.replace("_clipped.tif", "_gapfilled_clipped.tif")
            out_path = outdir / out_name

            if out_path.exists() and not args.overwrite:
                raise FileExistsError(
                    f"Output exists: {out_path}\nUse --overwrite to replace it."
                )

            dsts.append(rasterio.open(out_path, "w", **profile))

        try:
            block = args.block_size

            for row0 in range(0, height, block):
                for col0 in range(0, width, block):

                    win_h = min(block, height - row0)
                    win_w = min(block, width - col0)
                    window = Window(col0, row0, win_w, win_h)

                    stack = np.empty(
                        (len(srcs), win_h, win_w),
                        dtype=np.uint8,
                    )

                    for t, src in enumerate(srcs):
                        stack[t] = src.read(1, window=window).astype(np.uint8)

                    filled, block_stats = gapfill_block(stack, dates)
                    add_stats(total_stats, block_stats)

                    for t, dst in enumerate(dsts):
                        dst.write(filled[t], 1, window=window)

                print(f"Processed row block starting at {row0}/{height}")

        finally:
            for dst in dsts:
                dst.close()

    finally:
        for src in srcs:
            src.close()

    stats_csv = outdir / "gapfill_statistics.csv"

    with open(stats_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "pixels"])
        for k, v in total_stats.items():
            writer.writerow([k, v])

    print("\nGap-filling statistics:")
    for k, v in total_stats.items():
        print(f"  {k}: {v:,}")

    print(f"\nStatistics written to: {stats_csv}")
    print(f"Gap-filled files written to: {outdir}")


if __name__ == "__main__":
    main()
