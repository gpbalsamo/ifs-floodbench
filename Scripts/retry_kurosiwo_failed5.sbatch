#!/bin/bash
#SBATCH --job-name=kurosiwo-retry5
#SBATCH --partition=par
#SBATCH --account=ecrdmocp
#SBATCH --qos=np
#SBATCH --time=04:00:00
#SBATCH --mem=16G
#SBATCH --output=/etc/ecmwf/nfs/dh2_perm_a/pad/ifs-floodbench/kurosiwo_retry5_%j.log

set -uo pipefail
cd /etc/ecmwf/nfs/dh2_perm_a/pad/ifs-floodbench

python3 Scripts/fetch_kurosiwo_observations.py \
  --csv KuroSiwo_events_retry5.csv \
  --outroot kurosiwo_observations \
  --source gfm \
  --window-days 3 \
  --timeout 1800 \
  --skip-existing
