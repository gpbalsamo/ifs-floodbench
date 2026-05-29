#!/usr/bin/env bash
set -euo pipefail

module load conda
conda activate modis_flood

WORKDIR="/home/pad/Notebooks"

cd "${WORKDIR}"

csv="KuroSiwo_events.csv"
dir=kurosiwo_modis

csv="Modis_floods_events_2016_onwards.csv"
csv_peak="Modis_floods_events_2016_onwards_peakdates.csv" \
dir=modis_floods_events_2016_onwards
wdir=$PERM/flood_cases/MODIS

python3 estimate_modis_peak_dates.py \
  --csv $csv \
  --out $csv_peak \
   --workdir $wdir \
  --composite F2

python3 modis_flood_events.py \
  --csv $csv_peak \
  --outroot $dir
  --composite F2 \
  --skip-existing
