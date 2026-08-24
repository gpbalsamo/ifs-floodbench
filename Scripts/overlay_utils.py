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
    "cama_flood": (30, 60, 150),     # navy
    "viirs": (230, 126, 34),         # orange
    "gfm": (155, 38, 182),           # purple
    "modis": (39, 174, 96),          # green
    "reference_water": (0, 172, 193),  # teal: permanent/reference water, not new flooding
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

# "No observation" markers for VIIRS/GFM/MODIS layers, split by cause
# since the two are physically different and shouldn't look the same:
#   - VIIRS/MODIS are optical sensors -- gaps are cloud cover, irregular
#     in shape and can differ day to day within the compositing window.
#   - GFM is SAR (radar), which sees through cloud, so its gaps are pure
#     satellite swath geometry -- a hard-edged strip that repeats in the
#     same place on nearby dates, unrelated to weather.
# Both are kept subtle since either can cover a large share of an event's
# footprint (e.g. a fully cloud-covered MODIS pass, or an AOI straddling
# a swath edge).
CLOUD_GAP_RGBA = (120, 120, 120, 90)     # gray: VIIRS / MODIS (optical, cloud-limited)
SWATH_GAP_RGBA = (90, 110, 150, 90)      # slate blue: GFM (SAR, swath-limited)

# Minimum fraction of valid (non-missing) sub-pixels required for a
# 1 arcmin cell to be considered informative, used when aggregating
# native-resolution rasters (e.g. MODIS) onto the 1 arcmin grid.
MIN_VALID_FRACTION = 0.1

ONE_ARCMIN_DEG = 1.0 / 60.0


def _hatch_mask(shape, spacing=6, width=2):
    """
    Boolean mask of diagonal stripes (True = paint), used to turn a flat
    fill into a hatched pattern so a layer reads as "known background
    context" rather than a normal flooded-fraction fill.
    """
    h, w = shape
    rows = np.arange(h)[:, None]
    cols = np.arange(w)[None, :]
    return ((rows + cols) % spacing) < width


def _colorize(frac, rgb, threshold, min_alpha=MIN_ALPHA, max_alpha=MAX_ALPHA, nodata_rgba=None, hatch=False):
    """
    frac: 2D array of flooded fraction in [0, 1], NaN where invalid/nodata.
    Returns an (H, W, 4) uint8 RGBA array. Pixels below `threshold` are
    fully transparent; alpha above threshold scales with the fraction.

    nodata_rgba: if given, an (r, g, b, a) tuple painted onto NaN pixels
    instead of leaving them transparent like a confirmed-dry pixel. Used
    for observation layers (VIIRS/GFM/MODIS), where NaN means "no valid
    observation" (cloud cover / SAR swath gap) and must stay visually
    distinct from a pixel the source actually observed as dry. Left None
    for the CaMa-Flood layer, whose NaN comes from an intentional <1%
    declutter mask (see load_cama_flood_fraction), not missing data.

    hatch: if True, paint the fill as a diagonal-stripe hatch instead of a
    flat fill. Used for the reference-water layer so "known lake/river,
    not new flooding" reads as fixed background context rather than as
    another flavor of "missing/uncertain" alongside the nodata_rgba gray.
    """
    missing = np.isnan(frac)
    frac = np.clip(np.nan_to_num(frac, nan=0.0), 0.0, 1.0)

    alpha = np.where(
        frac >= threshold,
        min_alpha + frac * (max_alpha - min_alpha),
        0,
    ).astype(np.uint8)

    if hatch:
        alpha = np.where(_hatch_mask(frac.shape), alpha, 0).astype(np.uint8)

    h, w = frac.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = rgb[0]
    rgba[..., 1] = rgb[1]
    rgba[..., 2] = rgb[2]
    rgba[..., 3] = alpha

    if nodata_rgba is not None:
        rgba[missing] = nodata_rgba

    return rgba


def render_overlay(frac, bounds, out_png, rgb, threshold, nodata_rgba=None, hatch=False):
    """
    Render a precomputed flooded-fraction array (row 0 = north) at a given
    threshold and write a transparent RGBA PNG. Returns out_png.
    """
    rgba = _colorize(frac, rgb, threshold, nodata_rgba=nodata_rgba, hatch=hatch)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(out_png)
    return out_png


def render_overlay_all_thresholds(frac, bounds, out_png_for_key, rgb, nodata_rgba=None, hatch=False):
    """
    Render `frac` at every threshold in THRESHOLDS.
    out_png_for_key: callable(threshold_key) -> output path.
    Returns {threshold_key: png_path}.
    """
    return {key: render_overlay(frac, bounds, out_png_for_key(key), rgb, value,
                                 nodata_rgba=nodata_rgba, hatch=hatch)
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


def load_reference_water_mask(tif_path, band=1):
    """
    Load an atlantis per-scene permanent-water classification
    (<event>_<date>_<viirs|gfm>_permanent_water.tif, uint8, 1=water) as a
    (frac, bounds) pair, frac in {0.0, 1.0}, on the same footing as the
    flood-fraction loaders.

    CaMa-Flood's flood fraction includes the standing river/lake/reservoir
    extent that's always there, not just new flooding, while VIIRS/GFM/MODIS
    already exclude their own reference-water class from what they report
    as "flooded" (see atlantis's viirs/gfm processors). This mask lets
    build_dashboard_manifest.py show that extent as its own layer and lets
    compute_flood_scores.py exclude it from the contingency table so
    CaMa's permanent water isn't counted as a false alarm.
    """
    import rasterio

    with rasterio.open(tif_path) as ds:
        data = ds.read(band)
        frac = (data == 1).astype(float)

        if ds.transform.e > 0:
            frac = np.flipud(frac)

        west, south, east, north = ds.bounds
        bounds = [[float(south), float(west)], [float(north), float(east)]]

    return frac, bounds


def pick_reference_water_tif(atlantis_source_dir, harmonised_tif, source):
    """
    Find the processed/*_permanent_water.tif for the same date as the
    given harmonised flood_fraction tif (viirs/gfm), so the reference-water
    mask lines up with the exact scene used for that source's flood layer.
    """
    if harmonised_tif is None:
        return None
    processed_dir = Path(atlantis_source_dir) / "processed"
    if not processed_dir.is_dir():
        return None

    parts = harmonised_tif.stem.split("_")
    date = parts[-3] if len(parts) >= 3 else None
    if date is None:
        return None
    date_compact = date.replace("-", "")

    candidates = sorted(processed_dir.glob(f"*_{date_compact}_{source}_permanent_water.tif"))
    return candidates[-1] if candidates else None


def pick_harmonised_tif(source_dir):
    """
    Pick the harmonised GeoTIFF to display/score for a source. With the
    default --strategy peak there is exactly one; if several dates exist
    (--strategy all), pick the most recent.
    """
    harmonised_dir = Path(source_dir) / "harmonised"
    tifs = sorted(harmonised_dir.glob("*_harmonised.tif"))
    return tifs[-1] if tifs else None


# Priority order for picking one authoritative reference-water (lakes /
# rivers / reservoirs) mask per event. VIIRS is deliberately excluded:
# its processed/*_permanent_water.tif is written per-day at native
# (~375m) VIIRS resolution rather than the ~1 arcmin canonical grid GFM
# and MODIS use, and was found to misclassify most of the AOI as "water"
# for several events with no lake/reservoir anywhere near that size (e.g.
# ~70-80% flagged "water" over inland France / the Philippines) -- not
# reliable enough to subtract from either the map or the scores.
REFERENCE_WATER_SOURCE_PRIORITY = ["modis", "gfm"]


def pick_event_reference_water(flood_case, atlantis_event_dir, modis_dir):
    """
    Pick a single, best-available reference-water mask for one event,
    shared by build_dashboard_manifest.py (the diagnostic map layer) and
    compute_flood_scores.py (excluded from every source's CaMa comparison
    for this event, not just one source's own mask -- a lake is the same
    lake regardless of which sensor is being scored).

    atlantis_event_dir: <atlantis_root>/<sanitized flood_case>/atlantis,
    or None if no atlantis root was given.

    Returns (frac, bounds, source_used), or (None, None, None) if no
    source in REFERENCE_WATER_SOURCE_PRIORITY has usable data.
    """
    if "modis" in REFERENCE_WATER_SOURCE_PRIORITY and modis_dir:
        event_dir = Path(modis_dir) / flood_case
        tifs = sorted(event_dir.glob("MCDWD_*_clipped.tif"))
        if tifs:
            frac, bounds = load_fraction_mcdwd(tifs[-1], flood_classes=(1, 2))
            if np.any(np.nan_to_num(frac, nan=0.0) > 0):
                return frac, bounds, "modis"

    if "gfm" in REFERENCE_WATER_SOURCE_PRIORITY and atlantis_event_dir:
        harmonised_tif = pick_harmonised_tif(Path(atlantis_event_dir) / "gfm")
        pw_tif = pick_reference_water_tif(Path(atlantis_event_dir) / "gfm", harmonised_tif, "gfm")
        if pw_tif is not None:
            frac, bounds = load_reference_water_mask(pw_tif)
            if np.any(frac > 0):
                return frac, bounds, "gfm"

    return None, None, None


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
