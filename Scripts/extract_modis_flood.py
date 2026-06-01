#!/usr/bin/env python3
"""
Extract and plot NASA MODIS MCDWD flood product for historical and NRT dates.

Supports:
  - LAADS historical archive 2003–2025:
        MCDWD_L3, HDF
  - LAADS archived NRT 2026–present:
        MCDWD_L3_NRT, HDF
  - LANCE NRT recent files, normally about last week:
        MCDWD_L3_F1_NRT, MCDWD_L3_F1C_NRT, MCDWD_L3_F2_NRT, MCDWD_L3_F3_NRT, GeoTIFF

Recommended for floods covering the years 2002 to 2025 :
    --source laads
    --composite F2

Example:
    python extract_modis_flood.py \
      --date 2010-08-10 \
      --area 31 66 22 72 \
      --composite F2 \
      --source laads \
      --outdir modis_20100810_pakistan
"""

import argparse
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

import numpy as np
import requests
import rasterio
from rasterio.merge import merge
from rasterio.mask import mask
from shapely.geometry import box, mapping

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import matplotlib.patches as mpatches


LAADS_BASE = "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61"
LANCE_BASE = "https://nrt3.modaps.eosdis.nasa.gov/archive/allData/61"

COMPOSITE_TO_HDF_LAYER = {
    "F1": "Flood_1Day_250m",
    "F1C": "FloodCS_1Day_250m",
    "F2": "Flood_2Day_250m",
    "F3": "Flood_3Day_250m",
}


def get_earthdata_token() -> str:
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Missing EARTHDATA_TOKEN.\n"
            "Create a NASA Earthdata token, then run:\n"
            "    export EARTHDATA_TOKEN='YOUR_TOKEN'\n"
        )
    return token


def date_to_year_doy(date_str: str):
    date_str = date_str.strip()

    if "-" in date_str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        dt = datetime.strptime(date_str, "%Y%m%d")

    year = dt.year
    doy = int(dt.strftime("%j"))
    adate = f"A{year}{doy:03d}"
    return year, doy, adate


def modis_ll_tiles_for_aoi(north, west, south, east):
    """
    MODIS linear lat/lon tile convention:
        h = floor((lon + 180) / 10)
        v = floor((90 - lat) / 10)

    Product tiles are 10° x 10°.
    """
    if south > north:
        raise ValueError("Area must be NORTH WEST SOUTH EAST.")

    if west > east:
        raise ValueError("This script does not yet handle dateline-crossing AOIs.")

    h_min = int(np.floor((west + 180.0) / 10.0))
    h_max = int(np.floor((east + 180.0) / 10.0))

    v_min = int(np.floor((90.0 - north) / 10.0))
    v_max = int(np.floor((90.0 - south) / 10.0))

    h_min = max(0, min(35, h_min))
    h_max = max(0, min(35, h_max))
    v_min = max(0, min(17, v_min))
    v_max = max(0, min(17, v_max))

    tiles = []
    for h in range(h_min, h_max + 1):
        for v in range(v_min, v_max + 1):
            tiles.append(f"h{h:02d}v{v:02d}")

    return tiles


def list_directory(url, token, suffix):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, timeout=90)
    r.raise_for_status()

    hrefs = re.findall(r'href="([^"]+{}[^"]*)"'.format(re.escape(suffix)), r.text)
    hrefs = sorted(set(hrefs))

    if not hrefs:
        raise RuntimeError(f"No *{suffix} files found in:\n{url}")

    return hrefs


def download_file(url, outpath, token, overwrite=False):
    outpath = Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)

    if outpath.exists() and not overwrite:
        print(f"Already exists: {outpath}")
        return outpath

    headers = {"Authorization": f"Bearer {token}"}

    print(f"Downloading: {url}")
    with requests.get(url, headers=headers, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(outpath, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return outpath


def laads_shortname_for_date(year):
    """
    NASA LAADS holdings:
      2003–2025: MCDWD_L3
      2026–present: MCDWD_L3_NRT
    """
    if year <= 2025:
        return "MCDWD_L3"
    return "MCDWD_L3_NRT"


def download_laads_hdf_tiles(date, area, outdir, overwrite=False):
    token = get_earthdata_token()
    year, doy, adate = date_to_year_doy(date)
    shortname = laads_shortname_for_date(year)

    north, west, south, east = area
    tiles = modis_ll_tiles_for_aoi(north, west, south, east)

    directory_url = f"{LAADS_BASE}/{shortname}/{year}/{doy:03d}/"

    print(f"Source: LAADS")
    print(f"Shortname: {shortname}")
    print(f"Directory: {directory_url}")
    print(f"Needed tiles: {', '.join(tiles)}")

    hrefs = list_directory(directory_url, token, ".hdf")

    selected = []
    for href in hrefs:
        fname = Path(href).name
        if adate not in fname:
            continue
        if any(tile in fname for tile in tiles):
            selected.append(href)

    selected = sorted(set(selected))

    if not selected:
        raise RuntimeError(
            "No matching LAADS HDF tiles found.\n"
            f"Directory: {directory_url}\n"
            f"Tiles: {tiles}"
        )

    local_files = []
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for href in selected:
        fname = Path(href).name
        url = urljoin(directory_url, href)
        outpath = outdir / fname
        local_files.append(download_file(url, outpath, token, overwrite=overwrite))

    return local_files


def download_lance_geotiff_tiles(date, area, composite, outdir, overwrite=False):
    """
    Use only for very recent NRT dates, normally last week.
    """
    token = get_earthdata_token()
    year, doy, adate = date_to_year_doy(date)

    product = f"MCDWD_L3_{composite}_NRT"

    north, west, south, east = area
    tiles = modis_ll_tiles_for_aoi(north, west, south, east)

    directory_url = f"{LANCE_BASE}/{product}/{year}/{doy:03d}/"

    print(f"Source: LANCE NRT GeoTIFF")
    print(f"Product: {product}")
    print(f"Directory: {directory_url}")
    print(f"Needed tiles: {', '.join(tiles)}")

    hrefs = list_directory(directory_url, token, ".tif")

    selected = []
    for href in hrefs:
        fname = Path(href).name
        if adate not in fname:
            continue
        if any(tile in fname for tile in tiles):
            selected.append(href)

    selected = sorted(set(selected))

    if not selected:
        raise RuntimeError(
            "No matching LANCE GeoTIFF tiles found.\n"
            "This source normally only has the latest NRT files.\n"
            f"Directory: {directory_url}\n"
            f"Tiles: {tiles}"
        )

    local_files = []
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    for href in selected:
        fname = Path(href).name
        url = urljoin(directory_url, href)
        outpath = outdir / fname
        local_files.append(download_file(url, outpath, token, overwrite=overwrite))

    return local_files




def run_cmd(cmd):
    print("Running:", " ".join(str(c) for c in cmd))

    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if p.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(str(c) for c in cmd)
            + "\n\nSTDOUT:\n"
            + p.stdout
            + "\n\nSTDERR:\n"
            + p.stderr
        )

    return p.stdout


def tile_bounds_from_filename(hdf_file):
    """
    MODIS MCDWD linear lat/lon tile bounds.
    h = 0..35, v = 0..17
    each tile is 10 degrees x 10 degrees.
    """
    name = Path(hdf_file).name

    m = re.search(r"\.h(\d{2})v(\d{2})\.", name)
    if not m:
        raise ValueError(f"Could not parse MODIS tile h/v from filename: {name}")

    h = int(m.group(1))
    v = int(m.group(2))

    west = -180.0 + h * 10.0
    east = west + 10.0
    north = 90.0 - v * 10.0
    south = north - 10.0

    return west, south, east, north


def extract_hdf_layer_to_geotiff(hdf_file, composite, out_tif):
    """
    Extract one flood layer from MCDWD HDF4 using GDAL command-line tools,
    and explicitly assign the correct geographic transform.
    This avoids NotGeoreferencedWarning later in rasterio.
    """
    hdf_file = Path(hdf_file)
    out_tif = Path(out_tif)
    out_tif.parent.mkdir(parents=True, exist_ok=True)

    layer_name = COMPOSITE_TO_HDF_LAYER[composite]

    info = run_cmd(["gdalinfo", str(hdf_file)])

    matches = []
    for line in info.splitlines():
        line = line.strip()

        if line.startswith("SUBDATASET_") and "_NAME=" in line and layer_name in line:
             matches.append(line.split("=", 1)[1])

    if not matches:
        raise RuntimeError(
            f"Could not find layer '{layer_name}' in {hdf_file}\n\n"
            "Run manually:\n"
            f"    gdalinfo {hdf_file}\n\n"
            "First part of gdalinfo output:\n"
            + info[:5000]
        )

    subdataset = matches[0]

    west, south, east, north = tile_bounds_from_filename(hdf_file)

    print(f"Selected subdataset for {composite}:")
    print(subdataset)

    print(
        f"Assigning tile bounds: "
        f"west={west}, south={south}, east={east}, north={north}"
    )

    run_cmd(
        [
            "gdal_translate",
            "-of", "GTiff",
            "-co", "COMPRESS=LZW",
            "-a_srs", "EPSG:4326",
            "-a_ullr", str(west), str(north), str(east), str(south),
            "-a_nodata", "255",
            subdataset,
            str(out_tif),
        ]
    )

    return out_tif

def prepare_input_geotiffs(files, source, composite, workdir):
    """
    For LANCE GeoTIFFs, return files directly.
    For LAADS HDFs, extract requested flood layer to temporary GeoTIFFs.
    """
    if source == "lance":
        return files

    extracted = []
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    for hdf in files:
        hdf = Path(hdf)
        out_tif = workdir / f"{hdf.stem}_{composite}.tif"
        if not out_tif.exists():
            print(f"Extracting {COMPOSITE_TO_HDF_LAYER[composite]} from {hdf.name}")
            extract_hdf_layer_to_geotiff(hdf, composite, out_tif)
        extracted.append(out_tif)

    return extracted


def mosaic_and_clip(files, area, out_tif):
    north, west, south, east = area
    geom = [mapping(box(west, south, east, north))]

    srcs = [rasterio.open(f) for f in files]

    try:
        mosaic_arr, mosaic_transform = merge(srcs)

        meta = srcs[0].meta.copy()
        meta.update(
            {
                "height": mosaic_arr.shape[1],
                "width": mosaic_arr.shape[2],
                "transform": mosaic_transform,
                "count": 1,
                "nodata": 255,
                "compress": "lzw",
            }
        )

        tmp_tif = Path(out_tif).with_suffix(".mosaic_tmp.tif")
        with rasterio.open(tmp_tif, "w", **meta) as dst:
            dst.write(mosaic_arr)

        with rasterio.open(tmp_tif) as src:
            clipped_arr, clipped_transform = mask(
                src,
                geom,
                crop=True,
                filled=True,
                nodata=255,
            )

            clipped_meta = src.meta.copy()
            clipped_meta.update(
                {
                    "height": clipped_arr.shape[1],
                    "width": clipped_arr.shape[2],
                    "transform": clipped_transform,
                    "nodata": 255,
                    "compress": "lzw",
                }
           )

        with rasterio.open(out_tif, "w", **clipped_meta) as dst:
            dst.write(clipped_arr)

        tmp_tif.unlink(missing_ok=True)

    finally:
        for src in srcs:
            src.close()

    return out_tif


def plot_modis_flood(tif, png, title, show_background=False):
    with rasterio.open(tif) as src:
        data = src.read(1)
        bounds = src.bounds

    plot_data = np.full(data.shape, 4, dtype=np.uint8)
    plot_data[data == 0] = 0
    plot_data[data == 1] = 1
    plot_data[data == 2] = 2
    plot_data[data == 3] = 3
    plot_data[data == 255] = 4

    if not show_background:
        plot_data = np.ma.masked_where(plot_data == 0, plot_data)

    cmap = ListedColormap(
        [
            "#f2f2f2",  # no water
            "#2b83ba",  # surface water
            "#fdae61",  # recurring flood
            "#d7191c",  # unusual flood
            "#bdbdbd",  # insufficient data
        ]
    )

    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap.N)

    fig, ax = plt.subplots(figsize=(9, 7), constrained_layout=True)

    ax.imshow(
        plot_data,
        extent=[bounds.left, bounds.right, bounds.bottom, bounds.top],
        origin="upper",
        cmap=cmap,
        norm=norm,
        interpolation="nearest",
    )

    ax.set_title(title)
    ax.set_xlabel("Longitude (°)")
    ax.set_ylabel("Latitude (°)")
    ax.set_aspect("equal", adjustable="box")

    legend_items = [
        mpatches.Patch(color="#2b83ba", label="Surface water"),
        mpatches.Patch(color="#fdae61", label="Recurring flood"),
        mpatches.Patch(color="#d7191c", label="Unusual flood"),
        mpatches.Patch(color="#bdbdbd", label="Insufficient data"),
    ]

    if show_background:
        legend_items.insert(0, mpatches.Patch(color="#f2f2f2", label="No water"))

    ax.legend(
        handles=legend_items,
        loc="lower left",
        frameon=True,
        framealpha=0.9,
        fontsize=9,
    )

    fig.savefig(png, dpi=200)
    plt.close(fig)

    print(f"Saved plot: {png}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract and plot MODIS MCDWD flood product for historical and NRT dates."
    )

    parser.add_argument("--date", required=True, help="Date as YYYY-MM-DD.")

    parser.add_argument(
        "--area",
        nargs=4,
        type=float,
        required=True,
        metavar=("NORTH", "WEST", "SOUTH", "EAST"),
        help="AOI as North West South East, e.g. --area 31 66 22 72",
    )

    parser.add_argument(
        "--composite",
        default="F2",
        choices=["F1", "F1C", "F2", "F3"],
        help="F1, F1C, F2, or F3. Default: F2.",
    )

    parser.add_argument(
        "--source",
        default="laads",
        choices=["laads", "lance"],
        help=(
            "laads = stable archive, HDF, works for historical and 2026+ archive. "
            "lance = recent NRT GeoTIFF only, normally about last week."
        ),
    )

    parser.add_argument(
        "--outdir",
        default="modis_flood_output",
        help="Output directory.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite downloads.",
    )

    parser.add_argument(
        "--show-background",
        action="store_true",
        help="Show no-water pixels.",
    )

    args = parser.parse_args()

    outdir = Path(args.outdir)
    rawdir = outdir / "raw"
    workdir = outdir / "work"
    outdir.mkdir(parents=True, exist_ok=True)

    year, doy, adate = date_to_year_doy(args.date)
    date_tag = args.date.replace("-", "")
    composite = args.composite.upper()

    print(f"Date: {args.date}  year={year} doy={doy:03d}")
    print(f"Composite: {composite}")

    if args.source == "laads":
        raw_files = download_laads_hdf_tiles(
            date=args.date,
            area=args.area,
            outdir=rawdir,
            overwrite=args.overwrite,
        )
    else:
        raw_files = download_lance_geotiff_tiles(
            date=args.date,
            area=args.area,
            composite=composite,
            outdir=rawdir,
            overwrite=args.overwrite,
        )

    input_tifs = prepare_input_geotiffs(
        files=raw_files,
        source=args.source,
        composite=composite,
        workdir=workdir,
    )

    clipped_tif = outdir / f"MCDWD_{args.source}_{composite}_{date_tag}_clipped.tif"
    png = outdir / f"MCDWD_{args.source}_{composite}_{date_tag}_plot.png"

    mosaic_and_clip(input_tifs, args.area, clipped_tif)

    title = f"MODIS MCDWD {composite}, {args.date}, source={args.source}"
    plot_modis_flood(
        clipped_tif,
        png,
        title=title,
        show_background=args.show_background,
    )

    print(f"Saved clipped GeoTIFF: {clipped_tif}")


if __name__ == "__main__":
    main()
