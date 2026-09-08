#!/usr/bin/env bash
set -euo pipefail

module load conda
conda activate modis_flood

# Edit to your own working directory and batch-run output directories.
WORKDIR="${WORKDIR:-.}"

cd "${WORKDIR}"

csv="KuroSiwo_events.csv"
dir=flood_cases/kurosiwo_modis

csv="Modis_floods_events_2016_onwards.csv"
dir=flood_cases/modis_floods_events_2016_onwards

python3 modis_flood_events.py \
  --csv $csv \
  --outroot $dir \
  --composite F2 \
  --all-days \
  --skip-plotting \
  --skip-existing
