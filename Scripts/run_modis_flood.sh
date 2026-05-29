#!/usr/bin/env bash
set -euo pipefail

# --------------------------------------------------
# Activate conda environment
# --------------------------------------------------
module load conda
conda activate modis_flood

# --------------------------------------------------
# Run MODIS extraction/plotting
# --------------------------------------------------
python3 extract_modis_flood.py --date 2022-08-31  --area 31 66 22 72  --composite F2 --outdir modis_flood_pakistan

python3 plot_modis_flood.py --input modis_flood_pakistan/MCDWD_laads_F2_20220831_clipped.tif   --flood-case "Pakistan 2022-08-31 MODIS F2"   --output modis_flood_pakistan/MCDWD_F2_20220831_flood_missing.png

