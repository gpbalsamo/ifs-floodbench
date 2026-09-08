
# Edit these to point at your own batch-run output directories.
dir_cases="${dir_cases:-modis_floods_events_2016_onwards}"
gap_filled_cases="${gap_filled_cases:-modis_gapfilled}"
for flood_case in `ls "${dir_cases}"/`
do
  ls ${dir_cases}/${flood_case} | wc
  python3 gapfill_modis_flood.py \
  --indir ${dir_cases}/${flood_case} \
  --pattern "*.tif" \
  --outdir ${gap_filled_cases}/${flood_case} \
  --block-size 512 --overwrite
done

