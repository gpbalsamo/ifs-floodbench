#!/usr/bin/env python3
"""
Plot MODIS MCDWD flooded area and missing data.

MODIS MCDWD classes:
    0   no water
    1   surface/reference water
    2   recurring flood
    3   unusual flood
    255 insufficient data / missing observation

Recommended interpretation:
    flooded area = class 3
    flooded + recurring = classes 2 and 3
    missing/cloud/insufficient = class 255
"""

import argparse
import numpy as np
import rasterio

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import matplotlib.patches as mpatches

import cartopy.crs as ccrs


def plot_modis_flood_and_missing(
    modis_tif,
    flood_case="MODIS MCDWD",
    output_png=None,
    include_recurring=True,
    show_reference_water=True,
    show_no_water=False,
):
    # --------------------------------------------------
    # Read MODIS clipped GeoTIFF
    # --------------------------------------------------
    with rasterio.open(modis_tif) as src:
        mosaic = src.read(1)
        transform = src.transform

    # --------------------------------------------------
    # Compute geographic extent
    # --------------------------------------------------
    height, width = mosaic.shape

    lon_min = transform.c
    lon_max = transform.c + transform.a * width
    lat_max = transform.f
    lat_min = transform.f + transform.e * height  # e is negative

    extent = [lon_min, lon_max, lat_min, lat_max]

    # --------------------------------------------------
    # Build plotting class
    #
    # plot_data classes:
    #   0 = no water / transparent or white
    #   1 = reference water
    #   2 = flooded area
    #   3 = missing / insufficient data
    # --------------------------------------------------
    plot_data = np.zeros(mosaic.shape, dtype=np.uint8)

    if show_reference_water:
        plot_data[mosaic == 1] = 1

    if include_recurring:
        # recurring flood + unusual flood
        plot_data[(mosaic == 2) | (mosaic == 3)] = 2
        flood_label = "Flooded area: recurring + unusual flood"
    else:
        # unusual flood only
        plot_data[mosaic == 3] = 2
        flood_label = "Flooded area: unusual flood only"

    # Missing / insufficient observations, often cloud-contaminated or no valid observation
    plot_data[mosaic == 255] = 3

    # Optionally mask no-water pixels for a clean map background
    if not show_no_water:
        plot_data = np.ma.masked_where(plot_data == 0, plot_data)

    # --------------------------------------------------
    # Colour map
    # --------------------------------------------------
    # 0 no water: white
    # 1 reference water: pale blue
    # 2 flood: dark blue
    # 3 missing/cloud: grey
    cmap = ListedColormap(
        [
            "#ffffff",  # no water
            "#9ecae1",  # reference water
            "#08519c",  # flood
            "#bdbdbd",  # missing/cloud/insufficient
        ]
    )

    norm = BoundaryNorm(
        [-0.5, 0.5, 1.5, 2.5, 3.5],
        cmap.N,
    )

    # --------------------------------------------------
    # Plot
    # --------------------------------------------------
    fig = plt.figure(figsize=(10, 8))
    ax = plt.axes(projection=ccrs.PlateCarree())

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.imshow(
        plot_data,
        cmap=cmap,
        norm=norm,
        extent=extent,
        transform=ccrs.PlateCarree(),
        origin="upper",
        interpolation="nearest",  # critical: no interpolation, native pixels
    )

    ax.coastlines(resolution="10m", linewidth=0.8)

    gl = ax.gridlines(
        draw_labels=True,
        linewidth=0.4,
        alpha=0.5,
        linestyle="--",
    )
    gl.top_labels = False
    gl.right_labels = False

    # --------------------------------------------------
    # Legend
    # --------------------------------------------------
    legend_items = []

    if show_no_water:
        legend_items.append(
            mpatches.Patch(color="#ffffff", label="No water")
        )

    if show_reference_water:
        legend_items.append(
            mpatches.Patch(color="#9ecae1", label="Reference/surface water")
        )

    legend_items.extend(
        [
            mpatches.Patch(color="#08519c", label=flood_label),
            mpatches.Patch(color="#bdbdbd", label="Missing / insufficient data"),
        ]
    )

    ax.legend(
        handles=legend_items,
        loc="lower left",
        frameon=True,
        framealpha=0.9,
        fontsize=9,
    )

    ax.set_title("MODIS Flood Composite (" + flood_case + ")")

    # --------------------------------------------------
    # Add simple pixel statistics
    # --------------------------------------------------
    n_total = np.count_nonzero(mosaic != 255) + np.count_nonzero(mosaic == 255)
    n_missing = np.count_nonzero(mosaic == 255)

    if include_recurring:
        n_flood = np.count_nonzero((mosaic == 2) | (mosaic == 3))
    else:
        n_flood = np.count_nonzero(mosaic == 3)

    missing_pct = 100.0 * n_missing / n_total if n_total > 0 else np.nan
    flood_pct = 100.0 * n_flood / n_total if n_total > 0 else np.nan

    txt = (
        f"Flood pixels: {flood_pct:.2f}%\n"
        f"Missing pixels: {missing_pct:.2f}%"
    )

    ax.text(
        0.99,
        0.01,
        txt,
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        bbox=dict(facecolor="white", alpha=0.85, edgecolor="none"),
    )

    if output_png is not None:
        plt.savefig(output_png, dpi=200, bbox_inches="tight")
        print(f"Saved: {output_png}")
    else:
        plt.show()

    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Plot MODIS MCDWD flooded area and missing data."
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Input clipped MODIS MCDWD GeoTIFF.",
    )

    parser.add_argument(
        "--flood-case",
        default="MODIS MCDWD",
        help="Title label, e.g. 'Pakistan 2022-08-30 F2'.",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Optional output PNG.",
    )

    parser.add_argument(
        "--unusual-only",
        action="store_true",
        help="Plot only class 3 as flood. Default plots classes 2 and 3.",
    )

    parser.add_argument(
        "--hide-reference-water",
        action="store_true",
        help="Do not show class 1 reference/surface water.",
    )

    parser.add_argument(
        "--show-no-water",
        action="store_true",
        help="Show no-water pixels in white instead of masking them.",
    )

    args = parser.parse_args()

    plot_modis_flood_and_missing(
        modis_tif=args.input,
        flood_case=args.flood_case,
        output_png=args.output,
        include_recurring=not args.unusual_only,
        show_reference_water=not args.hide_reference_water,
        show_no_water=args.show_no_water,
    )


if __name__ == "__main__":
    main()
