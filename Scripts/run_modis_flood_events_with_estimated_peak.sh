#!/usr/bin/env bash
set -euo pipefail

module load conda
conda activate modis_flood

# Edit these to your own batch-run output directories.
csv="KuroSiwo_events.csv"
csv_peak="Modis_KuroSiwo_peakdates.csv"
dir=flood_cases/kurosiwo_modis

csv="Modis_floods_events_2016_onwards.csv"
csv_peak="Modis_floods_events_2016_onwards_peakdates.csv"
dir=flood_cases/modis_floods_events_2016_onwards

wdir=flood_cases/MODIS

python3 estimate_modis_peak_dates_csv_only.py \
  --csv $csv \
  --out $csv_peak \
  --raster-root $wdir \
  --composite F2 \
  --keep-original-date-column

python3 modis_flood_events.py \
  --csv $csv_peak \
  --outroot $dir \
  --composite F2
