# Scripts

This directory contains command-line scripts for extracting, plotting, and benchmarking flood inundation products used in the `ifs-floodbench` workflow.

The scripts currently support five main workflows:

1. Extraction and plotting of NASA MODIS MCDWD flood composites for individual events.
2. Batch processing of flood-event catalogues using KuroSiwo-style metadata.
3. Generation of IFS/CaMa-Flood flood and river-discharge maps.
4. Fetching VIIRS/GFM/MODIS observations via the [`atlantis`](https://github.com/opageo/atlantis)
   project and assembling a multi-layer HTML dashboard that overlays the
   CaMa-Flood model and all three EO observation sources on the same map,
   toggleable per layer (`fetch_kurosiwo_observations.py`,
   `build_dashboard_manifest.py`, `overlay_utils.py`, `kurosiwo_dashboard.py`).
   `fetch_kurosiwo_observations.py` shells out to atlantis's own CLI/environment
   (default: `/perm/pad/atlantis/.venv/bin/atlantis`), so atlantis must be set
   up separately — see its README for `uv`/`pixi` install instructions and
   NASA Earthdata credentials.
5. A second, standalone MODIS-only dashboard (`build_modis2016_catalogue.py`,
   `modis2016_dashboard.py`) for named post-2016 flood events that aren't part
   of the KuroSiwo catalogue, kept separate so the KuroSiwo dashboard stays
   exactly the curated, fully-scored benchmark. The two dashboards share their
   UI code (`dashboard_shell.py`) and cross-link to each other.

The standard Conda environment used for the MODIS workflow is:

```bash
conda activate modis_flood
```

On ECMWF/HPC systems this may require:

```bash
module load conda
conda activate modis_flood
```

## Required catalogue format

Most event-based scripts expect a KuroSiwo-style CSV catalogue with the following columns:

```text
flood_case
country              (optional; see add_country_continent.py)
continent            (optional; see add_country_continent.py)
date_start
date_end
lat_min
lat_max
lon_min
lon_max
max_flood_extent_km2
date_of_max_flood_extent
```

The bounding-box convention is:

```text
lat_min, lat_max, lon_min, lon_max
```

Internally, the scripts convert this to the area convention used by MODIS/Metview workflows:

```text
North, West, South, East = lat_max, lon_min, lat_min, lon_max
```

## Environment

The MODIS scripts require a Conda environment with geospatial Python packages and GDAL command-line tools.

Typical packages include:

```text
python
numpy
pandas
rasterio
rioxarray
xarray
geopandas
shapely
pyproj
matplotlib
cartopy
requests
tqdm
netcdf4
gdal
```

To document the environment reproducibly, keep an environment file in the repository, for example:

```text
envs/modis_flood.yml
```

Users can then create the environment with:

```bash
conda env create -f envs/modis_flood.yml
conda activate modis_flood
```

## NASA Earthdata authentication

The MODIS extraction script downloads NASA MODIS MCDWD products from LAADS or LANCE. It requires a NASA Earthdata token to be available as an environment variable:

```bash
export EARTHDATA_TOKEN="YOUR_TOKEN_HERE"
```

Do not commit tokens or credentials to GitHub.

## MODIS MCDWD classes

The MODIS MCDWD flood product is interpreted as:

```text
0     no water
1     surface/reference water
2     recurring flood
3     unusual flood
255   insufficient data / missing observation
```

For most flood-event processing, class `3` is treated as the main flood class. Some plotting options can include both recurring and unusual flood classes, i.e. classes `2` and `3`.

---

# Script overview

## `extract_modis_flood.py`

Extracts NASA MODIS MCDWD flood data for a given date and area of interest.

The script can use:

* `laads`: stable LAADS archive, suitable for historical dates and archived 2026+ products.
* `lance`: recent near-real-time LANCE GeoTIFF products, usually only available for recent dates.

It downloads the required MODIS tiles, extracts the requested flood composite, mosaics the tiles, clips them to the requested bounding box, and writes a clipped GeoTIFF.

Example:

```bash
python3 extract_modis_flood.py \
  --date 2022-08-31 \
  --area 31 66 22 72 \
  --composite F2 \
  --source laads \
  --outdir modis_flood_pakistan
```

Arguments:

```text
--date        Date in YYYY-MM-DD format.
--area        Area as North West South East.
--composite   MODIS composite: F1, F1C, F2, or F3. Default: F2.
--source      Data source: laads or lance. Default: laads.
--outdir      Output directory.
--overwrite   Redownload files if they already exist.
```

Main outputs:

```text
MCDWD_<source>_<composite>_<YYYYMMDD>_clipped.tif
MCDWD_<source>_<composite>_<YYYYMMDD>_plot.png
```

---

## `plot_modis_flood.py`

Plots a clipped MODIS MCDWD GeoTIFF produced by `extract_modis_flood.py`.

The plot shows flood pixels, reference water, and missing/insufficient observations. It also reports simple pixel statistics for flood and missing-data fractions.

Example:

```bash
python3 plot_modis_flood.py \
  --input modis_flood_pakistan/MCDWD_laads_F2_20220831_clipped.tif \
  --flood-case "Pakistan 2022-08-31 MODIS F2" \
  --output modis_flood_pakistan/MCDWD_F2_20220831_flood_missing.png
```

Arguments:

```text
--input                  Input clipped MODIS GeoTIFF.
--flood-case             Text label used in the plot title.
--output                 Optional output PNG.
--unusual-only           Plot only class 3 as flood.
--hide-reference-water   Hide class 1 reference/surface water.
--show-no-water          Show no-water pixels instead of masking them.
```

---

## `modis_flood_events.py`

Batch-runs MODIS extraction and plotting for all flood events in a KuroSiwo-style CSV catalogue.

For each event, the script:

1. Reads `date_of_max_flood_extent`.
2. Builds the event area from `lat_min`, `lat_max`, `lon_min`, `lon_max`.
3. Calls `extract_modis_flood.py`.
4. Calls `plot_modis_flood.py`.
5. Writes a batch summary CSV.

Example:

```bash
python3 modis_flood_events.py \
  --csv Modis_floods_events_2016_onwards.csv \
  --outroot modis_floods_events_2016_onwards \
  --composite F2 \
  --skip-existing
```

Arguments:

```text
--csv             Input flood-event catalogue.
--outroot         Root output directory.
--composite       MODIS composite: F1, F1C, F2, or F3. Default: F2.
--padding         Optional geographic padding in degrees around the event bbox.
--limit           Optional limit on the number of events to process.
--skip-existing   Skip events where the final PNG already exists.
--dry-run         Print commands without executing them.
```

Main outputs:

```text
<outroot>/<flood_case>/MCDWD_laads_F2_<YYYYMMDD>_clipped.tif
<outroot>/<flood_case>/MCDWD_F2_<YYYYMMDD>_flood_missing.png
<outroot>/batch_summary.csv
```

---

## `estimate_modis_peak_dates.py`

Estimates a better `date_of_max_flood_extent` for each event by scanning the full event period with MODIS.

This script is intended to run before `modis_flood_events.py`.

For each event, it:

1. Loops from `date_start` to `date_end`.
2. Calls `extract_modis_flood.py` for each day.
3. Reads the clipped MODIS GeoTIFF.
4. Computes valid, missing, water, and flood pixel fractions.
5. Selects the best date using a cloud-aware score:

```text
score = flood_fraction_valid * (1 - missing_fraction_total)
```

6. Writes an updated CSV where `date_of_max_flood_extent` is replaced by the best MODIS-observed date.

Example:

```bash
python3 estimate_modis_peak_dates.py \
  --csv Modis_floods_events_2016_onwards.csv \
  --out Modis_floods_events_2016_onwards_peakdates.csv \
  --workdir modis_peak_scan \
  --composite F2 \
  --skip-existing
```

Then run:

```bash
python3 modis_flood_events.py \
  --csv Modis_floods_events_2016_onwards_peakdates.csv \
  --outroot modis_floods_events_2016_onwards \
  --composite F2 \
  --skip-existing
```

Arguments:

```text
--csv                         Input KuroSiwo-style CSV.
--out                         Output CSV with updated date_of_max_flood_extent.
--workdir                     Working directory for daily MODIS extractions and diagnostics.
--extract-script              Path to extract_modis_flood.py.
--composite                   MODIS composite to scan. Default: F2.
--padding                     Optional bbox padding in degrees.
--limit                       Optional number of events to process.
--skip-existing               Reuse existing daily clipped GeoTIFFs.
--keep-tiffs                  Keep daily clipped GeoTIFFs after diagnostics.
--dry-run                     Print commands without running extraction.
--flood-values                Raster values counted as flood. Default: 3.
--water-values                Raster values counted as water. Default: 2.
--missing-values              Raster values counted as missing. Default: 255.
--min-valid-fraction          Minimum valid-pixel fraction required for a date to be eligible.
--keep-original-date-column   Add date_of_max_flood_extent_original before replacing the peak date.
```

Additional output columns may include:

```text
date_of_max_flood_extent_method
modis_peak_score
flood_pixel_fraction_at_peak
missing_pixel_fraction_at_peak
valid_pixel_fraction_at_peak
n_total_pixels_at_peak
n_valid_pixels_at_peak
n_flood_pixels_at_peak
n_missing_pixels_at_peak
```

---

## `run_modis_flood.sh`

Shell wrapper for a single MODIS extraction and plot.

It activates the `modis_flood` Conda environment and runs:

1. `extract_modis_flood.py`
2. `plot_modis_flood.py`

Example use case: Pakistan flood example for 2022-08-31.

Run with:

```bash
bash Scripts/run_modis_flood.sh
```

Before running, edit the script if needed to change:

```text
date
area
composite
output directory
plot title
```

---

## `run_modis_flood_events.sh`

Shell wrapper for catalogue-wide MODIS processing.

It activates the `modis_flood` Conda environment, changes to the working directory, and runs `modis_flood_events.py` on the selected event catalogue.

Run with:

```bash
bash Scripts/run_modis_flood_events.sh
```

Typical workflow:

```bash
python3 modis_flood_events.py \
  --csv Modis_floods_events_2016_onwards.csv \
  --outroot modis_floods_events_2016_onwards \
  --composite F2 \
  --skip-existing
```

Before running, check that the script points to the correct working directory and catalogue:

```text
WORKDIR
csv
dir
```

---

## `run_modis_flood_events_with_estimated_peak.sh`

Shell wrapper for the improved peak-date workflow.

It should run:

1. `estimate_modis_peak_dates.py`
2. `modis_flood_events.py`

The intended workflow is:

```bash
python3 estimate_modis_peak_dates.py \
  --csv Modis_floods_events_2016_onwards.csv \
  --out Modis_floods_events_2016_onwards_peakdates.csv \
  --workdir "$PERM/flood_cases/MODIS" \
  --composite F2 \
  --skip-existing

python3 modis_flood_events.py \
  --csv Modis_floods_events_2016_onwards_peakdates.csv \
  --outroot modis_floods_events_2016_onwards \
  --composite F2 \
  --skip-existing
```

Run with:

```bash
bash Scripts/run_modis_flood_events_with_estimated_peak.sh
```

This is the recommended workflow when the original `date_of_max_flood_extent` is uncertain or when cloud cover may make the midpoint date unsuitable.

---

## `modis_flood_events.py`

Plots IFS/CaMa-Flood river discharge and flood fraction for each event in a KuroSiwo-style catalogue.

This script uses ECMWF/Metview and retrieves fields from MARS. It is intended for ECMWF environments where MARS and Metview are available.

The script retrieves:

```text
235270   flood fraction
235275   river discharge
```

For each event it:

1. Reads the event date and bounding box.
2. Retrieves the relevant IFS/CaMa-Flood fields.
3. Subsets to the event area.
4. Produces a PNG showing river discharge and flood fraction.
5. Saves one image per `flood_case`.

Example:

```bash
python3 plot_kurosiwo_flood_cases.py \
  --csv KuroSiwo_events.csv \
  --outdir kurosiwo-dashboard/dashboard_data/floods_png \
  --expver j1ee \
  --step 24
```

Arguments:

```text
--csv          Input KuroSiwo-style catalogue.
--outdir       Output directory for PNG files.
--expver       ECMWF experiment version.
--stream       MARS stream. Default: oper.
--mars-class   MARS class. Default: rd.
--time         Forecast start time. Default: 0.
--step         Forecast step. Default: 24.
--buffer       Extra degrees around the event bbox. Default: 0.5.
--width        Output width for Metview output.
--font-scale   Font scaling for Metview output.
--use-wgrib2   Optionally subset GRIB using wgrib2.
--overwrite    Redownload/recompute existing cases.
--limit        Process only a limited number of events.
```

The plotting uses pixel-based rendering with no interpolation. River discharge is plotted first, and flood fraction is plotted on top.

---

## `overlay_utils.py`

Shared helper module (not a CLI) for turning a flood raster — model or EO
observation — into a transparent, georeferenced RGBA PNG overlay that can
be dropped directly onto a Leaflet map with `L.imageOverlay(png, bounds)`.

Each source is rendered as one solid colour with per-pixel alpha
proportional to the flooded fraction, rather than a colourmap gradient, so
that overlapping layers from different sources stay visually
distinguishable when stacked:

```text
cama_flood   navy    (30, 60, 150)
viirs        orange  (230, 126, 34)
gfm          purple  (155, 38, 182)
modis        green   (39, 174, 96)
```

Used by `plot_kurosiwo_flood_cases.py` (model layer) and
`build_dashboard_manifest.py` (observation layers).

---

## `fetch_kurosiwo_observations.py`

Batch-fetches VIIRS / GFM / MODIS observations for every event in a
KuroSiwo-style CSV catalogue, using the
[`atlantis`](https://github.com/opageo/atlantis) CLI as the fetch and
harmonisation backend. Atlantis resamples every source to a common
1 arcmin grid, which is what makes the sources directly comparable as map
overlays.

For each event it runs:

```bash
atlantis fetch \
  --event <flood_case> --source all \
  --bbox "<west> <south> <east> <north>" \
  --start-date ... --end-date ... \
  --harmonise --strategy peak \
  --output <outroot>/<flood_case>/atlantis
```

Example:

```bash
python3 fetch_kurosiwo_observations.py \
  --csv KuroSiwo_events.csv \
  --outroot kurosiwo_observations \
  --source all \
  --window-days 3 \
  --skip-existing
```

Arguments:

```text
--csv              KuroSiwo-style CSV catalogue.
--outroot           Root output directory. Default: kurosiwo_observations.
--source            gfm, viirs, modis, or all. Default: all.
--atlantis-bin       Path to the atlantis executable.
                     Default: /perm/pad/atlantis/.venv/bin/atlantis
--padding            Optional geographic padding in degrees around the event bbox.
--window-days        If set, fetch a +/- N day window around date_of_max_flood_extent
                     instead of the catalogue's full date_start..date_end window.
--modis-composite    MODIS composite passed through to atlantis. Default: F2.
--limit              Optional limit on number of events to process.
--skip-existing      Skip events that already have harmonised GeoTIFFs for all requested sources.
--dry-run            Print atlantis commands without running them.
```

This requires the atlantis environment to be set up separately (see the
atlantis README) and, for MODIS/VIIRS, a NASA Earthdata token — see
atlantis's `docs/setup.md`.

Main outputs (per event, written by atlantis itself):

```text
<outroot>/<flood_case>/atlantis/<source>/harmonised/<flood_case>_<date>_<source>_harmonised.tif
```

---

## `compute_flood_scores.py`

Computes verification scores (CSI, FAR, Hit Rate / POD) comparing the
CaMa-Flood model against each available VIIRS / GFM / MODIS observation,
for every event and at every one of the four flooded-fraction thresholds
in `overlay_utils.THRESHOLDS` (5% / 10% / 25% / 50%). One row is written
per `(flood_case, source, threshold)` combination.

The observation is regridded onto the (coarser) CaMa-Flood grid, both
fields are binarized at the threshold, and a 2x2 contingency table is
built treating the observation as truth and the model as forecast:

```text
tp = obs flooded & model flooded
fp = obs not flooded & model flooded   (false alarm)
fn = obs flooded & model not flooded   (miss)
tn = obs not flooded & model not flooded

CSI = tp / (tp+fp+fn)
FAR = fp / (tp+fp)
HR  = tp / (tp+fn)
```

Example:

```bash
python3 compute_flood_scores.py \
  --csv KuroSiwo_events.csv \
  --cama-grib-dir cama_png \
  --atlantis-root kurosiwo_observations \
  --modis-dir modis_events \
  --out scores.csv
```

Arguments:

```text
--csv               KuroSiwo-style CSV catalogue.
--cama-grib-dir     Directory with cached <flood_case>_flood_globe.grb
                     files (the --outdir used with plot_kurosiwo_flood_cases.py).
                     Events without a cached GRIB are skipped.
--atlantis-root     Root directory from fetch_kurosiwo_observations.py (viirs/gfm).
--modis-dir         Root directory from modis_flood_events.py (modis).
--out               Output CSV. Default: scores.csv.
--buffer            Degrees of padding around the event bbox, must match the
                     --buffer used with plot_kurosiwo_flood_cases.py. Default: 0.5.
--limit             Optional limit on number of events to process.
```

Feed the output into `build_dashboard_manifest.py --scores-csv scores.csv`
so the dashboard shows CSI/FAR/HR per event, per source, and per
threshold.

---

## `build_dashboard_manifest.py`

Assembles the multi-layer manifest (`layers.json`) consumed by the
dashboard, combining the CaMa-Flood overlay produced by
`plot_kurosiwo_flood_cases.py --overlay-dir ...` with the VIIRS/GFM/MODIS
harmonised GeoTIFFs from `fetch_kurosiwo_observations.py`. It renders the
observation overlays (via `overlay_utils.geotiff_to_overlay`) and copies
everything into `dashboard_data/layers/`.

Example:

```bash
python3 build_dashboard_manifest.py \
  --csv KuroSiwo_events.csv \
  --cama-dir cama_png/layers \
  --atlantis-root kurosiwo_observations \
  --dashboard-data kurosiwo-dashboard/dashboard_data
```

Arguments:

```text
--csv               KuroSiwo-style CSV catalogue.
--cama-dir          Directory with *_cama_flood.png/.json from plot_kurosiwo_flood_cases.py --overlay-dir.
--atlantis-root      Root directory from fetch_kurosiwo_observations.py; supplies viirs/gfm layers.
--modis-dir          Root directory from modis_flood_events.py; supplies the modis layer.
--scores-csv         Output of compute_flood_scores.py; attaches CSI/FAR/HR per
                     (event, source, threshold) to each observation layer.
--dashboard-data     Dashboard data directory. Default: kurosiwo-dashboard/dashboard_data.
```

Output: `dashboard_data/layers.json` plus the overlay PNGs under
`dashboard_data/layers/`.

---

## `kurosiwo_dashboard.py`

Creates a lightweight static HTML dashboard for browsing flood events,
comparing the CaMa-Flood model against VIIRS/GFM/MODIS observations.

The script creates:

```text
kurosiwo-dashboard/
├── index.html
├── style.css
├── app.js
└── dashboard_data/
    ├── floods_png/
    └── layers/
```

The dashboard uses:

* Leaflet for the interactive map.
* PapaParse for loading the event CSV.
* Event bounding boxes from the catalogue.
* `layers.json` (from `build_dashboard_manifest.py`) for the per-event,
  per-source georeferenced overlays. Selecting an event on the map adds an
  `L.imageOverlay` for each available layer (CaMa-Flood model, VIIRS, GFM,
  MODIS), each independently toggleable and opacity-adjustable from the
  "Layers" panel in the side panel — so model and observations can be
  compared directly on the map instead of as separate static images.
* An "Events" list in the side panel, sorted by `date_of_max_flood_extent`
  newest-first, in addition to the map. Clicking either a list row or a
  map rectangle selects the event and zooms/pans the map to its
  bounding box (`map.fitBounds`).
* A "Benchmark scores" table per event, one CSI/FAR/HR-by-threshold table
  per observation source (from `compute_flood_scores.py` via
  `build_dashboard_manifest.py --scores-csv`), showing all four
  thresholds (5% / 10% / 25% / 50%) at once regardless of which
  threshold is currently selected for the map overlay.
* The original single reference figure (`floods_png/<flood_case>.png`,
  from `plot_kurosiwo_flood_cases.py`'s labelled discharge+flood plot) is
  still shown, collapsed under "Reference figure", if present.

Run with:

```bash
python3 kurosiwo_dashboard.py
```

Full pipeline, from a KuroSiwo catalogue to a populated dashboard:

```bash
# 1. Model layer (ECMWF systems with Metview/MARS access)
python3 plot_kurosiwo_flood_cases.py \
  --csv KuroSiwo_events.csv --outdir cama_png \
  --overlay-dir cama_png/layers

# 2. Observation layers (VIIRS/GFM/MODIS via atlantis)
python3 fetch_kurosiwo_observations.py \
  --csv KuroSiwo_events.csv --outroot kurosiwo_observations

# 3. Assemble the manifest
python3 build_dashboard_manifest.py \
  --csv KuroSiwo_events.csv \
  --cama-dir cama_png/layers \
  --atlantis-root kurosiwo_observations \
  --dashboard-data kurosiwo-dashboard/dashboard_data

# 4. Dashboard shell + remaining static data
python3 kurosiwo_dashboard.py
cp KuroSiwo_events.csv kurosiwo-dashboard/dashboard_data/
cp cama_png/*.png kurosiwo-dashboard/dashboard_data/floods_png/   # optional reference figures
```

Expected dashboard data layout:

```text
kurosiwo-dashboard/
├── index.html
├── style.css
├── app.js
└── dashboard_data/
    ├── KuroSiwo_events.csv
    ├── layers.json
    ├── layers/
    │   ├── <flood_case>_cama_flood.png
    │   ├── <flood_case>_viirs.png
    │   ├── <flood_case>_gfm.png
    │   └── <flood_case>_modis.png
    └── floods_png/
        └── <flood_case>.png   (optional)
```

---

## `add_country_continent.py`

Adds `country` and `continent` columns to a KuroSiwo-style CSV catalogue,
looked up from each event's bounding-box centroid against a bundled
Natural Earth 1:110m admin-0 countries dataset
(`Scripts/data/ne_110m_admin_0_countries.geojson`). Pure Python
(point-in-polygon ray-casting), no geopandas/shapely dependency. Falls
back to the nearest country boundary for coastal/river-mouth events that
don't land inside any polygon at 110m resolution.

Example:

```bash
python3 add_country_continent.py --csv KuroSiwo_events.csv
```

Arguments:

```text
--csv                  KuroSiwo-style CSV catalogue, updated in place.
--out                  Output CSV path. Default: overwrite --csv.
--countries-geojson    Natural Earth admin-0 countries GeoJSON.
                       Default: Scripts/data/ne_110m_admin_0_countries.geojson
```

Run this once per catalogue (or whenever event bounding boxes change) so
`country`/`continent` show up correctly in the dashboard instead of
"Unknown".

---

## `dashboard_shell.py`

Not a CLI -- the shared Leaflet/PapaParse HTML+CSS+JS generator used by
both `kurosiwo_dashboard.py` and `modis2016_dashboard.py`, so the UI
(event list, map, score tables, threshold/layer controls) only needs to
be written once and both dashboards stay in sync. Exposes
`write_dashboard_shell(outdir, title, subtitle, events_csv,
reference_figures, nav_links)`.

---

## `build_modis2016_catalogue.py` / `modis2016_dashboard.py`

Builds a **second, standalone** dashboard for named, hand-picked
post-2016 flood events (Yangtze 2016, Pakistan monsoon 2022, Libya Derna
2023, ...) that were run through `modis_flood_events.py` separately from
the KuroSiwo catalogue and have no CaMa-Flood/VIIRS/GFM data -- kept out
of `KuroSiwo_events.csv` / the KuroSiwo dashboard on purpose, so that
catalogue stays exactly the curated, fully-scored KuroSiwo benchmark
(see workflow 6 below).

`build_modis2016_catalogue.py` combines:
* an authoritative event-metadata CSV (`event_name`, `start_date`,
  `end_date`, `country`, `continent`, `bbox_north/west/south/east`,
  `approx_flooded_area_km2`, `main_river_system`) -- e.g.
  `/home/pad/Notebooks/Modis_events.csv`
* the peak observation date + clipped MODIS GeoTIFF already picked by a
  `modis_flood_events.py`-style batch run's `batch_summary.csv` -- e.g.
  `/perm/pad/flood_cases/modis_floods_events_2016_onwards/`

into a KuroSiwo-style catalogue CSV (plus a `main_river_system` column,
shown in the dashboard's event-info panel when present), copying each
event's peak-date GeoTIFF into `<modis-dir>/<flood_case>/` for
`build_dashboard_manifest.py`.

Example:

```bash
python3 build_modis2016_catalogue.py \
  --events-csv /home/pad/Notebooks/Modis_events.csv \
  --batch-root /perm/pad/flood_cases/modis_floods_events_2016_onwards \
  --out Modis2016_events.csv \
  --modis-dir modis2016_events
```

Arguments:

```text
--events-csv    Authoritative event metadata CSV (see columns above).
--batch-root    Directory with batch_summary.csv + one subdir per event
               (each containing MCDWD_*_<date>_clipped.tif).
--out           Output catalogue CSV. Default: Modis2016_events.csv.
--modis-dir     modis_flood_events.py-style output root; the peak-date
               clipped GeoTIFF is copied to <modis-dir>/<flood_case>/.
```

`modis2016_dashboard.py` generates the dashboard shell into
`modis2016-dashboard/` (same UI as the KuroSiwo dashboard, minus the
"Reference figure" section, which doesn't apply here), with a small
cross-link in the header back to the KuroSiwo dashboard and vice versa.

---

# Recommended workflows

## 1. Single MODIS event

Use this for testing one date and one area.

```bash
bash Scripts/run_modis_flood.sh
```

or manually:

```bash
python3 Scripts/extract_modis_flood.py \
  --date 2022-08-31 \
  --area 31 66 22 72 \
  --composite F2 \
  --source laads \
  --outdir modis_flood_pakistan

python3 Scripts/plot_modis_flood.py \
  --input modis_flood_pakistan/MCDWD_laads_F2_20220831_clipped.tif \
  --flood-case "Pakistan 2022-08-31 MODIS F2" \
  --output modis_flood_pakistan/MCDWD_F2_20220831_flood_missing.png
```

## 2. Batch MODIS processing using existing peak dates

Use this when `date_of_max_flood_extent` is already trusted.

```bash
bash Scripts/run_modis_flood_events.sh
```

or manually:

```bash
python3 Scripts/modis_flood_events.py \
  --csv Modis_floods_events_2016_onwards.csv \
  --outroot modis_floods_events_2016_onwards \
  --composite F2 \
  --skip-existing
```

## 3. Batch MODIS processing with estimated peak dates

Use this when cloud cover may make the original `date_of_max_flood_extent` unreliable.

```bash
bash Scripts/run_modis_flood_events_with_estimated_peak.sh
```

or manually:

```bash
python3 Scripts/estimate_modis_peak_dates.py \
  --csv Modis_floods_events_2016_onwards.csv \
  --out Modis_floods_events_2016_onwards_peakdates.csv \
  --workdir modis_peak_scan \
  --composite F2 \
  --skip-existing

python3 Scripts/modis_flood_events.py \
  --csv Modis_floods_events_2016_onwards_peakdates.csv \
  --outroot modis_floods_events_2016_onwards \
  --composite F2 \
  --skip-existing
```

## 4. IFS/CaMa-Flood event plotting

Use this on ECMWF systems with Metview and MARS access.

```bash
python3 Scripts/plot_kurosiwo_flood_cases.py \
  --csv KuroSiwo_events.csv \
  --outdir kurosiwo-dashboard/dashboard_data/floods_png \
  --expver j1ee \
  --step 24
```

## 5. Multi-layer dashboard (model + observations)

```bash
python3 Scripts/add_country_continent.py --csv KuroSiwo_events.csv

python3 Scripts/plot_kurosiwo_flood_cases.py \
  --csv KuroSiwo_events.csv --outdir cama_png \
  --overlay-dir cama_png/layers

python3 Scripts/fetch_kurosiwo_observations.py \
  --csv KuroSiwo_events.csv --outroot kurosiwo_observations

python3 Scripts/compute_flood_scores.py \
  --csv KuroSiwo_events.csv \
  --cama-grib-dir cama_png \
  --atlantis-root kurosiwo_observations \
  --modis-dir modis_events \
  --out scores.csv

python3 Scripts/build_dashboard_manifest.py \
  --csv KuroSiwo_events.csv \
  --cama-dir cama_png/layers \
  --atlantis-root kurosiwo_observations \
  --modis-dir modis_events \
  --scores-csv scores.csv \
  --dashboard-data kurosiwo-dashboard/dashboard_data

python3 Scripts/kurosiwo_dashboard.py

cp KuroSiwo_events.csv kurosiwo-dashboard/dashboard_data/
cp cama_png/*.png kurosiwo-dashboard/dashboard_data/floods_png/   # optional reference figures

cd kurosiwo-dashboard
python3 -m http.server 8000
```

Then open:

```text
http://127.0.0.1:8000
```

Or to see an example open:

```text
https://sites.ecmwf.int/pad/floodbench/kurosiwo-dashboard/
```

## 6. Standalone post-2016 named-events dashboard (MODIS-only)

Kept as a **separate** dashboard from KuroSiwo (see
`build_modis2016_catalogue.py` / `modis2016_dashboard.py` above), so the
KuroSiwo catalogue and dashboard stay exactly the curated, fully-scored
benchmark:

```bash
python3 Scripts/build_modis2016_catalogue.py \
  --events-csv /home/pad/Notebooks/Modis_events.csv \
  --batch-root /perm/pad/flood_cases/modis_floods_events_2016_onwards \
  --out Modis2016_events.csv \
  --modis-dir modis2016_events

python3 Scripts/build_dashboard_manifest.py \
  --csv Modis2016_events.csv \
  --modis-dir modis2016_events \
  --dashboard-data modis2016-dashboard/dashboard_data

python3 Scripts/modis2016_dashboard.py
cp Modis2016_events.csv modis2016-dashboard/dashboard_data/

cd modis2016-dashboard
python3 -m http.server 8001
```

These events show up in their own map/event list with only a `modis`
layer and no benchmark scores (no CaMa-Flood/VIIRS/GFM data was fetched
for them). Each dashboard's header links to the other.

---

# Notes and caveats

## Cloud cover and missing data

MODIS optical flood products can be strongly affected by cloud cover. For this reason, the recommended event workflow is to run `estimate_modis_peak_dates.py` first. This selects the date with the best balance between detected flood pixels and available valid observations.

## Composite choice

The default composite is `F2`, the 2-day composite. This is often a reasonable compromise between flood detection and cloud contamination.

Available composites are:

```text
F1    1-day flood
F1C   1-day cloud-screened flood
F2    2-day flood
F3    3-day flood
```

## File naming

The event-based scripts create one subdirectory per flood case. Event names are sanitised by replacing spaces and unsafe characters.

Typical output:

```text
modis_floods_events_2016_onwards/
├── <flood_case>/
│   ├── raw/
│   ├── work/
│   ├── MCDWD_laads_F2_<YYYYMMDD>_clipped.tif
│   └── MCDWD_F2_<YYYYMMDD>_flood_missing.png
└── batch_summary.csv
```

## Reproducibility

For reproducibility, commit the following files to GitHub:

```text
Scripts/*.py
Scripts/*.sh
envs/modis_flood.yml
README.md
Scripts/README.md
```

---

## Future Work

* Consider gap filling for EO missing data (persistence, precipitation-screening)
* Integration with Earth System Model workflows
* Quantitative benchmark scores (e.g. IoU/CSI between model and observation layers) surfaced in the dashboard, not just visual overlay comparison

---
