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
# Worked example: 2022-08-31 Pakistan floods. Edit OUTDIR to your own
# batch-run output directory.
OUTDIR="${OUTDIR:-flood_cases/Pakistan}"
python3 extract_modis_flood.py --date 2022-08-31  --area 31 66 22 72  --composite F2 --outdir "$OUTDIR"

python3 plot_modis_flood.py --input "$OUTDIR/MCDWD_laads_F2_20220831_clipped.tif"   --flood-case "Pakistan 2022-08-31 MODIS F2"   --output modis_flood_pakistan/MCDWD_F2_20220831_flood_missing.png

