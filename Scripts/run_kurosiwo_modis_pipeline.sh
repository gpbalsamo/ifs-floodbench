#!/usr/bin/env bash
set -uo pipefail

WORKDIR=/etc/ecmwf/nfs/dh2_perm_a/pad/ifs-floodbench
cd "$WORKDIR/Scripts"

CONDA_PREFIX=/perm/pad/conda/envs/modis_flood
export CONDA_PREFIX
export PATH="$CONDA_PREFIX/bin:$PATH"
export GDAL_DATA="$CONDA_PREFIX/share/gdal"
export GDAL_DRIVER_PATH="$CONDA_PREFIX/lib/gdalplugins"
[ -d "$GDAL_DRIVER_PATH" ] || unset GDAL_DRIVER_PATH
export PROJ_DATA="$CONDA_PREFIX/share/proj"
export CPL_ZIP_ENCODING=UTF-8

WINDOW_CSV="$WORKDIR/KuroSiwo_events_modiswindow.csv"
SCRATCH_ROOT="$WORKDIR/kurosiwo_modis_scratch"
PEAKDATES_CSV="$WORKDIR/KuroSiwo_modis_peakdates.csv"
FINAL_ROOT="$WORKDIR/kurosiwo_modis"

echo "=== Step 1: all-days scan (window CSV) ==="
python3 modis_flood_events.py \
  --csv "$WINDOW_CSV" \
  --outroot "$SCRATCH_ROOT" \
  --composite F2 --all-days --skip-plotting --skip-existing
step1_rc=$?
echo "Step 1 exit code: $step1_rc"

echo "=== Step 2: estimate best (least-cloudy) date per event ==="
python3 estimate_modis_peak_dates_csv_only.py \
  --csv "$WINDOW_CSV" \
  --out "$PEAKDATES_CSV" \
  --raster-root "$SCRATCH_ROOT" \
  --composite F2 \
  --keep-original-date-column
step2_rc=$?
echo "Step 2 exit code: $step2_rc"

echo "=== Step 3: final single-day extraction + plot per event ==="
python3 modis_flood_events.py \
  --csv "$PEAKDATES_CSV" \
  --outroot "$FINAL_ROOT" \
  --composite F2
step3_rc=$?
echo "Step 3 exit code: $step3_rc"

echo "=== DONE (rc: $step1_rc $step2_rc $step3_rc) ==="
