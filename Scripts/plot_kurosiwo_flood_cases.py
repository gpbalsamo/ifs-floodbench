#!/usr/bin/env python3
"""
plot_kurosiwo_flood_cases.py

Read a Kuro Siwo flood-event CSV catalogue and generate one PNG per event:
    <flood_case>.png

Each plot uses:
- flood_case
- date_of_max_flood_extent
- lat_min, lat_max, lon_min, lon_max

Example:
    python plot_kurosiwo_flood_cases.py \
        --csv KuroSiwo_events.csv \
        --outdir kurosiwo-dashboard/flood_png \
        --expver j1ee
"""

import os
import gc
import json
import argparse
import datetime as dt
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from overlay_utils import load_fraction_array, render_overlay_all_thresholds, LAYER_COLORS

# Must be set before importing metview
os.environ.setdefault("MARS_READANY_BUFFER_SIZE", "2147483648")

if os.environ.get("SCRATCHDIR"):
    os.environ.setdefault("TMPDIR", os.environ["SCRATCHDIR"])

import pandas as pd
import metview as mv


PARAMETERS = ["235270", "235275"]  # discharge, flood fraction

def parse_date_to_yyyymmdd(value):

    s = str(value).strip()

    if len(s) == 8 and s.isdigit():
        return int(s)

    d = pd.to_datetime(s)
    return int(d.strftime("%Y%m%d"))

def make_area(row, buffer_deg=0.0):
    """
    Metview area format: [North, West, South, East]
    CSV columns are lat_min, lat_max, lon_min, lon_max.
    """
    north = float(row["lat_max"]) + buffer_deg
    south = float(row["lat_min"]) - buffer_deg
    west = float(row["lon_min"]) - buffer_deg
    east = float(row["lon_max"]) + buffer_deg
    return [north, west, south, east]


def setup_styles():
    coastlines = mv.mcoast(
        map_coastline_resolution="high",
        map_coastline_sea_shade="on",
        map_coastline_sea_shade_colour="cyan",
        map_coastline_land_shade="on",
        map_coastline_land_shade_colour="cream",
        map_grid_frame_colour="grey",
        map_grid_frame_line_style="dash",
        map_grid_frame="off",
        map_coastline="on",
        map_label="off",
    )

    conr = mv.mcont(
        legend="on",
        contour_label="off",
        contour="off",
        contour_level_selection_type="level_list",
        contour_reference_level=0,
        contour_shade="on",
        contour_shade_min_level=0.01,
        contour_shade_max_level=250000,
        contour_level_list=[5, 10, 50, 100, 500, 1000, 5000, 10000, 50000],
        contour_shade_method="area_fill",
        contour_shade_technique="grid_shading",
        contour_line_colour="black",
        contour_highlight="off",
        contour_hilo="off",
        grib_scaling_of_retrieved_fields="off",
        contour_shade_max_level_colour="red",
        contour_shade_min_level_colour="white",
    )

    conm = mv.mcont(
        legend="on",
        contour_label="off",
        contour="off",
        contour_level_selection_type="level_list",
        contour_reference_level=0,
        contour_shade="on",
        contour_shade_min_level=-50000,
        contour_shade_max_level=-0.01,
        contour_level_list=[-5000, -1000, -500, -100, -50, -10, -5],
        contour_shade_method="area_fill",
        contour_shade_technique="grid_shading",
        contour_line_colour="black",
        contour_highlight="off",
        contour_hilo="off",
        grib_scaling_of_retrieved_fields="off",
        contour_shade_max_level_colour="white",
        contour_shade_min_level_colour="blue",
    )

    inundation = mv.mcont(
        legend="on",
        contour_label="off",
        contour="off",
        contour_level_selection_type="level_list",
        contour_min_level=0.01,
        contour_max_level=1.2,
        contour_shade="on",
        contour_shade_min_level=0.01,
        contour_shade_max_level=1.2,
        contour_level_list=[0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 0.7, 0.9, 1.1],
        contour_shade_max_level_colour="navy",
        contour_shade_min_level_colour="grey",
        contour_shade_technique="grid_shading",)

    legend = mv.mlegend(
        legend_title="on",
        legend_box_mode="positional",
        legend_box_x_position=1.0,
        legend_box_x_length=6.5,
        legend_box_y_position=0.3,
        legend_box_y_length=1.6,
        legend_display_type="continuous",
        legend_border="off",
        legend_text_font_size=0.14,
        legend_title_font_size=0.16,
        legend_text_colour="black",
        legend_title_text="Flooded fraction (-)",
        legend_title_orientation="horizontal",
    )
    return coastlines, conr, conm, inundation, legend

def retrieve_case(row, args, outdir):
    flood_case = str(row["flood_case"])
    peak_date = parse_date_to_yyyymmdd(row["date_of_max_flood_extent"])
    area = make_area(row, buffer_deg=args.buffer)

    if args.monthly_step_archive:
        # Some experiments (e.g. imxj) are archived as one long forecast
        # per month, initialised on the 1st, with the peak date reached at
        # a large step (6h resolution) rather than as its own short-range
        # forecast base date -- e.g. 2016-01-16 lives under
        # date=2016-01-01, step=360 (15 days * 24h), not date=2016-01-16.
        peak_dt = dt.datetime.strptime(str(peak_date), "%Y%m%d")
        base_dt = peak_dt.replace(day=1)
        date_yyyymmdd = int(base_dt.strftime("%Y%m%d"))
        step = (peak_dt - base_dt).days * 24
    else:
        date_yyyymmdd = peak_date
        step = args.step

    globe_grib = outdir / f"{flood_case}_flood_globe.grb"
    area_grib = outdir / f"{flood_case}_flood.grb"

    mars_request = {
        "class": args.mars_class,
        "expver": args.expver,
        "stream": args.stream,
        "type": "fc",
        "levtype": "sfc",
        "date": date_yyyymmdd,
        "time": args.time,
        "step": step,
        "param": PARAMETERS,
    }

    if not globe_grib.exists() or args.overwrite:
        print(f"[retrieve] {flood_case}: {mars_request}")
        fs = mv.retrieve(mars_request)
        fs.write(str(globe_grib))
    else:
        print(f"[skip retrieve] {globe_grib}")

    # Subset with wgrib2 if available. Otherwise use full GRIB directly.
    if args.use_wgrib2:
        cmd = (
            f"wgrib2 {globe_grib} "
            f"-small_grib {area[1]}:{area[3]} {area[2]}:{area[0]} "
            f"{area_grib}"
        )
        print(f"[subset] {cmd}")
        os.system(cmd)
        return area_grib, area

    return globe_grib, area


def plot_case_old (row, grib_path, area, styles, outdir, args):
    coastlines, conr, conm, inundation, legend = styles

    flood_case = str(row["flood_case"])
    country = str(row.get("country", "Unknown"))
    continent = str(row.get("continent", "Unknown"))
    date_label = pd.to_datetime(str(row["date_of_max_flood_extent"]),format="%Y%m%d").strftime("%Y-%m-%d")

    view_area = mv.geoview(
        map_area_definition="corners",
        area=area,
        coastlines=coastlines,
    )

    fc = mv.read(str(grib_path))
    data = mv.read(data=fc, step=args.step)

    title = mv.mtext(
        text_line_1="IFS River Discharge and Flood Extent",
        text_mode="positional",
        text_box_x_position=0.6,
        text_box_y_position=17.6,
        text_box_x_length=7.5,
        text_box_y_length=0.6,
        text_justification="centre",
        text_font_size=0.34,
        text_colour="black",
    )
    
    subtitle = mv.mtext(
        text_line_1=f"{flood_case} | {country} ({continent}) | {date_label}",
        text_mode="positional",
        text_box_x_position=0.6,
        text_box_y_position=17.0,
        text_box_x_length=7.5,
        text_box_y_length=0.6,
        text_justification="centre",
        text_font_size=0.24,
        text_colour="black",
    )

    notitle = mv.mtext(text_lines=[" "], text_font_size=0.35)

    png_base = outdir / flood_case
    mv.setoutput(
        mv.png_output(
            output_name=str(png_base),
            output_width=args.width,
            output_font_scale=args.font_scale,
        )
    )

    print(f"[plot] {png_base}.png")
    mv.plot(
        data[0], conm,
        data[0], conr,
        data[1], inundation,
        view_area,
        legend,
        notitle,
        title,
        subtitle,
    )

def find_var(ds, candidates):
    for name in candidates:
        if name in ds:
            return ds[name]

    raise ValueError(
        f"Could not find any of {candidates}. "
        f"Available variables are: {list(ds.data_vars)}"
    )


def prepare_lon(ds, lon_name="lon"):
    """
    Convert longitudes from 0..360 to -180..180 if needed.
    """
    lon = ds[lon_name]

    if float(lon.max()) > 180:
        ds = ds.assign_coords(
            {lon_name: (((lon + 180) % 360) - 180)}
        )
        ds = ds.sortby(lon_name)

    return ds


def load_cama_flood_fraction(grib_path, area):
    """
    Read a cached CaMa-Flood GRIB (as retrieved by retrieve_case) and
    return the flood-fraction DataArray subset to `area`, masked below 1%.
    Shared by plot_case() (figures) and compute_flood_scores.py (scoring).
    """
    fc = mv.read(str(grib_path))
    ds = fc.to_dataset()

    if "latitude" in ds.coords:
        ds = ds.rename({"latitude": "lat"})
    if "longitude" in ds.coords:
        ds = ds.rename({"longitude": "lon"})

    ds = prepare_lon(ds, lon_name="lon")

    flood = find_var(ds, ["avg_fldffr", "fldfrc", "flood_fraction"]).squeeze()

    north, west, south, east = area
    if ds.lat[0] > ds.lat[-1]:
        flood = flood.sel(lat=slice(north, south), lon=slice(west, east))
    else:
        flood = flood.sel(lat=slice(south, north), lon=slice(west, east))

    return flood.where(flood >= 0.01)


def write_cama_overlay(flood_plot, flood_case, date_label, overlay_dir):
    """
    Render the model flood-fraction field as a transparent map-overlay PNG
    per selectable threshold (for the multi-layer dashboard) alongside a
    JSON sidecar with the Leaflet-ready bounds. Independent of the
    labelled figure in plot_case().
    """
    overlay_dir = Path(overlay_dir)

    frac, bounds = load_fraction_array(
        flood_plot.lat.values,
        flood_plot.lon.values,
        flood_plot.values,
    )

    png_paths = render_overlay_all_thresholds(
        frac, bounds,
        lambda key: overlay_dir / key / f"{flood_case}_cama_flood.png",
        LAYER_COLORS["cama_flood"],
    )

    sidecar = overlay_dir / f"{flood_case}_cama_flood.json"
    sidecar.write_text(json.dumps({
        "png": {key: f"{key}/{path.name}" for key, path in png_paths.items()},
        "bounds": bounds,
        "date": date_label,
    }, indent=2))

    print(f"[overlay] {sidecar}")


def plot_case(row, grib_path, area, outdir, args):
    flood_case = str(row["flood_case"])
    date_label = pd.to_datetime(row["date_of_max_flood_extent"]).strftime("%Y-%m-%d")

    country = str(row.get("country", "Unknown"))
    continent = str(row.get("continent", "Unknown"))

    print(f"[plot] {flood_case} | {country} | {continent} | {date_label}")

    # Read GRIB with Metview, then convert to xarray
    fc = mv.read(str(grib_path))
    ds = fc.to_dataset()

    # Normalise coordinate names if needed
    if "latitude" in ds.coords:
        ds = ds.rename({"latitude": "lat"})
    if "longitude" in ds.coords:
        ds = ds.rename({"longitude": "lon"})

    ds = prepare_lon(ds, lon_name="lon")

    # Extract discharge (flood fraction comes from load_cama_flood_fraction)
    discharge = find_var(ds, ["avg_dis", "discharge", "river_discharge"]).squeeze()

    # Ensure correct map bounds
    north, west, south, east = area
    extent = [west, east, south, north]

    # Subset to plotting area
    if ds.lat[0] > ds.lat[-1]:
        discharge = discharge.sel(lat=slice(north, south), lon=slice(west, east))
    else:
        discharge = discharge.sel(lat=slice(south, north), lon=slice(west, east))

    flood_plot = load_cama_flood_fraction(grib_path, area)
    q_plot = discharge.where(np.abs(discharge) >= 5)

    if args.overlay_dir:
        write_cama_overlay(flood_plot, flood_case, date_label, args.overlay_dir)

    fig = plt.figure(figsize=(10, 8))
    ax = plt.axes(projection=ccrs.PlateCarree())

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.add_feature(cfeature.LAND, facecolor="0.92")
    ax.add_feature(cfeature.OCEAN, facecolor="0.85")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.7)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5)
    ax.add_feature(cfeature.RIVERS, linewidth=0.4, alpha=0.5)

    gl = ax.gridlines(
        draw_labels=True,
        linewidth=0.4,
        alpha=0.5,
        linestyle="--",
    )
    gl.top_labels = False
    gl.right_labels = False

# --------------------------------------------------
# Pixel-based plotting: no interpolation
# --------------------------------------------------

    # --------------------------------------------------
    # River discharge FIRST
    # --------------------------------------------------
    
    q_abs = np.abs(q_plot)
    
    q_levels = [5, 10, 50, 100, 500, 1000, 5000, 10000, 50000]
    
    q_norm = colors.BoundaryNorm(
        q_levels,
        ncolors=plt.get_cmap("Reds").N
    )
    
    im_q = ax.pcolormesh(
        q_abs.lon,
        q_abs.lat,
        q_abs,
    
        cmap="Reds",
        norm=q_norm,
    
        shading="nearest",
        transform=ccrs.PlateCarree(),
    
        alpha=0.55,
        zorder=1,
    )
    # --------------------------------------------------
    # Flood fraction ON TOP
    # --------------------------------------------------
    
    flood_levels = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 0.7, 0.9, 1.0]
    
    flood_norm = colors.BoundaryNorm(
        flood_levels,
        ncolors=plt.get_cmap("Blues").N
    )
    
    im_flood = ax.pcolormesh(
        flood_plot.lon,
        flood_plot.lat,
        flood_plot,
    
        cmap="Blues",
        norm=flood_norm,
    
        shading="nearest",
        transform=ccrs.PlateCarree(),
    
        alpha=0.90,
        zorder=2,
    )

    # Titles
    # Main title
    fig.suptitle(
        "IFS River Discharge & Flood Extent - CaMa-Flood 1 arcmin",
        fontsize=14,
        fontweight="bold",
        y=0.985,
    )
    
    fig.text(
        0.5,
        0.945,
        f"{flood_case} | {country} ({continent}) | {date_label}",
        ha="center",
        fontsize=10,
    )

    # --------------------------------------------------
    # Colour bars
    # --------------------------------------------------
    
    cbar_q = plt.colorbar(
        im_q,
        ax=ax,
        orientation="horizontal",
        pad=0.09,
        fraction=0.035,
    )
    
    cbar_q.set_label("River discharge |Q| (m³/s)", fontsize=9)
    cbar_q.ax.tick_params(labelsize=8)
    
    cbar_flood = plt.colorbar(
        im_flood,
        ax=ax,
        orientation="horizontal",
        pad=0.16,
        fraction=0.035,
    )
    
    cbar_flood.set_label("Flooded fraction (-)", fontsize=9)
    cbar_flood.ax.tick_params(labelsize=8)

    output_png = outdir / f"{flood_case}.png"

    plt.subplots_adjust(top=0.86,bottom=0.12,)
    plt.savefig(output_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    plt.close(fig)

    del fc, ds, discharge, flood_plot, q_plot
    del im_flood, im_q
    gc.collect()

    print(f"[saved] {output_png}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Kuro Siwo event catalogue CSV")
    parser.add_argument("--outdir", default="kurosiwo_flood_png", help="Output directory")
    parser.add_argument("--expver", default="j1ee", help="ECMWF experiment version")
    parser.add_argument("--stream", default="oper")
    parser.add_argument("--mars-class", default="rd")
    parser.add_argument("--time", default=0, type=int)
    parser.add_argument("--step", default=24, type=int)
    parser.add_argument("--monthly-step-archive", action="store_true",
                         help="For experiments archived as one long forecast per month, "
                              "initialised on the 1st (e.g. imxj): retrieve the peak date "
                              "via date=<1st of its month>, step=<days into month>*24, "
                              "instead of date=<peak date>, step=--step.")
    parser.add_argument("--buffer", default=0.5, type=float, help="Extra degrees around bbox")
    parser.add_argument("--width", default=1600, type=int)
    parser.add_argument("--font-scale", default=4, type=int)
    parser.add_argument("--use-wgrib2", action="store_true", help="Subset GRIB to bbox using wgrib2")
    parser.add_argument("--overlay-dir", default=None,
                         help="If set, also write a transparent CaMa-Flood map-overlay PNG "
                              "(+ bounds JSON sidecar) per event for the dashboard, "
                              "e.g. kurosiwo-dashboard/dashboard_data/layers")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", default=None, type=int, help="Only process first N events")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.csv)

    df["date_of_max_flood_extent"] = pd.to_datetime(
        df["date_of_max_flood_extent"].apply(parse_date_to_yyyymmdd).astype(str),
        format="%Y%m%d",
    )
    df = df.sort_values("date_of_max_flood_extent").reset_index(drop=True)

    required = [
        "flood_case",
        "date_of_max_flood_extent",
        "lat_min",
        "lat_max",
        "lon_min",
        "lon_max",
    ]

    
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    if args.limit:
        df = df.tail(args.limit)

#    styles = setup_styles()
    for i, (_, row) in enumerate(df.iterrows(), start=1):

        print(
            f"[{i:03d}/{len(df)}] "
            f"{row['flood_case']}  "
            f"{row['date_of_max_flood_extent'].strftime('%Y-%m-%d')}"
        )
    for _, row in df.iterrows():
        try:
            grib_path, area = retrieve_case(row, args, outdir)
#            plot_case_old(row, grib_path, area, styles, outdir, args)
            plot_case(row, grib_path, area, outdir, args)
        except Exception as e:
            print(f"[ERROR] {row.get('flood_case', 'unknown')}: {e}")

    country = str(row.get("country", "Unknown"))
    continent = str(row.get("continent", "Unknown"))
    
if __name__ == "__main__":
    main()
