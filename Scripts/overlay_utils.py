#!/usr/bin/env python3
"""
overlay_utils.py

Shared helpers for turning flood rasters (model or EO observations) into
transparent, georeferenced RGBA PNG overlays that can be dropped directly
onto a Leaflet map with `L.imageOverlay(png, bounds)`.

Every source is reduced to the same thing: a "flooded fraction" array on
(approximately) the CaMa-Flood 1 arcmin grid, in [0, 1], NaN where
invalid/missing. A pixel counts as "flooded" for a given comparison
threshold (5% / 10% / 25% / 50%, see THRESHOLDS below) if its fraction is
>= that threshold. This lets the dashboard let users pick the threshold
that defines "flooded" instead of baking in one arbitrary cutoff.

Each source is rendered as one solid colour with alpha increasing with
the flooded fraction (rgb constant, alpha varies), so overlapping layers
from different sources stay visually distinguishable when stacked.

Two-phase API:
    load_fraction_*(...)   -> (frac, bounds)   # read/aggregate once
    render_overlay(frac, bounds, out_png, rgb, threshold)  # render many times

Used by:
    plot_kurosiwo_flood_cases.py   (CaMa-Flood / IFS model layer)
    build_dashboard_manifest.py    (VIIRS / GFM / MODIS layers)
"""

from pathlib import Path

import numpy as np
from PIL import Image

# Default colours per source, shared with the dashboard legend.
LAYER_COLORS = {
    "cama_flood": (30, 60, 150),   # navy
    "viirs": (230, 126, 34),       # orange
    "gfm": (155, 38, 182),         # purple
    "modis": (39, 174, 96),        # green
}

# Selectable "what counts as flooded" thresholds, applied uniformly to
# every source's flooded-fraction array. Key is used in filenames / the
# manifest; value is the fraction cutoff.
THRESHOLDS = [
    ("t05", 0.05),
    ("t10", 0.10),
    ("t25", 0.25),
    ("t50", 0.50),
]
DEFAULT_THRESHOLD_KEY = "t05"

MIN_ALPHA = 90
MAX_ALPHA = 225

# Minimum fraction of valid (non-missing) sub-pixels required for a
# 1 arcmin cell to be considered informative, used when aggregating
# native-resolution rasters (e.g. MODIS) onto the 1 arcmin grid.
MIN_VALID_FRACTION = 0.1

ONE_ARCMIN_DEG = 1.0 / 60.0


def _colorize(frac, rgb, threshold, min_alpha=MIN_ALPHA, max_alpha=MAX_ALPHA):
    """
    frac: 2D array of flooded fraction in [0, 1], NaN where invalid/nodata.
    Returns an (H, W, 4) uint8 RGBA array. Pixels below `threshold` are
    fully transparent; alpha above threshold scales with the fraction.
    """
    frac = np.clip(np.nan_to_num(frac, nan=0.0), 0.0, 1.0)

    alpha = np.where(
        frac >= threshold,
        min_alpha + frac * (max_alpha - min_alpha),
        0,
    ).astype(np.uint8)

    h, w = frac.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = rgb[0]
    rgba[..., 1] = rgb[1]
    rgba[..., 2] = rgb[2]
    rgba[..., 3] = alpha
    return rgba


def render_overlay(frac, bounds, out_png, rgb, threshold):
    """
    Render a precomputed flooded-fraction array (row 0 = north) at a given
    threshold and write a transparent RGBA PNG. Returns out_png.
    """
    rgba = _colorize(frac, rgb, threshold)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(out_png)
    return out_png


def render_overlay_all_thresholds(frac, bounds, out_png_for_key, rgb):
    """
    Render `frac` at every threshold in THRESHOLDS.
    out_png_for_key: callable(threshold_key) -> output path.
    Returns {threshold_key: png_path}.
    """
    return {key: render_overlay(frac, bounds, out_png_for_key(key), rgb, value)
            for key, value in THRESHOLDS}


def load_fraction_array(lat, lon, values, value_scale=1.0):
    """
    Wrap a lat/lon-indexed 2D array (e.g. an xarray DataArray's .values,
    with matching 1D lat/lon coordinate arrays) as a (frac, bounds) pair.

    lat, lon: 1D coordinate arrays (any order).
    values:   2D array shaped (len(lat), len(lon)).
    value_scale: multiplier applied to `values` to obtain a 0..1 fraction.

    bounds = [[south, west], [north, east]], Leaflet-ready.
    """
    lat = np.asarray(lat)
    lon = np.asarray(lon)
    frac = np.asarray(values, dtype=float) * value_scale

    if lat[0] < lat[-1]:
        # ascending (south -> north): flip so row 0 is north, matching PNG's
        # top-to-bottom row order.
        frac = np.flipud(frac)

    bounds = [[float(lat.min()), float(lon.min())],
              [float(lat.max()), float(lon.max())]]
    return frac, bounds


def load_fraction_geotiff(tif_path, value_scale=1.0 / 100.0, band=1):
    """
    Load a single-band classified GeoTIFF (e.g. an Atlantis harmonised
    flood_fraction raster, uint8 0-100 with nodata=255) as a (frac, bounds)
    pair, already on ~1 arcmin resolution.
    """
    import rasterio

    with rasterio.open(tif_path) as ds:
        data = ds.read(band).astype(float)
        if ds.nodata is not None:
            data[data == ds.nodata] = np.nan
        frac = data * value_scale

        # rasterio arrays are row 0 = top of raster; for a standard
        # north-up transform (e < 0) that is already north, matching PNG
        # row order. Flip only if the transform is south-up.
        if ds.transform.e > 0:
            frac = np.flipud(frac)

        west, south, east, north = ds.bounds
        bounds = [[float(south), float(west)], [float(north), float(east)]]

    return frac, bounds


def load_fraction_mcdwd(tif_path, flood_classes=(3,), missing_value=255,
                         cell_deg=ONE_ARCMIN_DEG, band=1):
    """
    Aggregate a raw, native-resolution NASA MODIS MCDWD class raster
    (0=no water, 1=reference water, 2=recurring flood, 3=unusual flood,
    255=missing), as produced by ifs-floodbench's own
    extract_modis_flood.py, onto a 1 arcmin grid, computing per-cell the
    fraction of valid native sub-pixels classified as flood. This puts
    MODIS on the same "flooded fraction at ~1 arcmin" footing as the
    CaMa-Flood model and the atlantis-harmonised GFM/VIIRS rasters, so the
    same threshold means the same thing for every source.

    Returns (frac, bounds) where bounds = [[south, west], [north, east]].
    """
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.transform import from_origin

    with rasterio.open(tif_path) as ds:
        data = ds.read(band)
        src_transform = ds.transform
        src_crs = ds.crs
        west, south, east, north = ds.bounds

    flood_mask = np.isin(data, flood_classes).astype("float32")
    valid_mask = (data != missing_value).astype("float32")

    dst_west = np.floor(west / cell_deg) * cell_deg
    dst_north = np.ceil(north / cell_deg) * cell_deg
    width = max(1, int(round((east - dst_west) / cell_deg)))
    height = max(1, int(round((dst_north - south) / cell_deg)))
    dst_transform = from_origin(dst_west, dst_north, cell_deg, cell_deg)

    flood_agg = np.zeros((height, width), dtype="float32")
    valid_agg = np.zeros((height, width), dtype="float32")

    reproject(flood_mask, flood_agg, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=src_crs, resampling=Resampling.average)
    reproject(valid_mask, valid_agg, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=src_crs, resampling=Resampling.average)

    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(valid_agg >= MIN_VALID_FRACTION, flood_agg / np.maximum(valid_agg, 1e-6), np.nan)

    dst_south = dst_north - height * cell_deg
    dst_east = dst_west + width * cell_deg
    bounds = [[float(dst_south), float(dst_west)], [float(dst_north), float(dst_east)]]

    return frac, bounds


def regrid_to(frac_src, bounds_src, shape_dst, bounds_dst):
    """
    Resample a flooded-fraction array (row 0 = north) onto a different
    grid, defined by its target shape and bounds, via average resampling.
    NaN in the source is treated as missing (excluded from averaging) and
    destination cells with no overlapping valid source data come back NaN.

    Used to put an observation's fraction array on the same grid as the
    CaMa-Flood model output before computing a per-pixel contingency table
    (hits/misses/false alarms), matching the benchmarking convention of
    the Bench_CMF_*_Inundation notebooks (regrid observations onto the
    model grid).

    bounds_*: [[south, west], [north, east]].
    """
    import rasterio
    from rasterio.warp import reproject, Resampling
    from rasterio.transform import from_bounds

    (s0, w0), (n0, e0) = bounds_src
    (s1, w1), (n1, e1) = bounds_dst
    h0, w0n = frac_src.shape
    h1, w1n = shape_dst

    src_transform = from_bounds(w0, s0, e0, n0, w0n, h0)
    dst_transform = from_bounds(w1, s1, e1, n1, w1n, h1)

    nodata = -1.0
    src = np.where(np.isnan(frac_src), nodata, frac_src).astype("float32")
    dst = np.full((h1, w1n), nodata, dtype="float32")

    reproject(
        src, dst,
        src_transform=src_transform, src_crs="EPSG:4326", src_nodata=nodata,
        dst_transform=dst_transform, dst_crs="EPSG:4326", dst_nodata=nodata,
        resampling=Resampling.average,
    )

    return np.where(dst == nodata, np.nan, dst)
