#!/usr/bin/env python3
"""
add_country_continent.py

Adds `country` and `continent` columns to a KuroSiwo-style flood-event
CSV catalogue, looked up from each event's bounding-box centroid against
a bundled Natural Earth 1:110m admin-0 countries dataset
(Scripts/data/ne_110m_admin_0_countries.geojson). Pure Python, no
geopandas/shapely dependency, so it can run in any environment.

For each event:
  1. Compute the bbox centroid: ((lat_min+lat_max)/2, (lon_min+lon_max)/2).
  2. Point-in-polygon test (even-odd rule, handles holes and
     MultiPolygon) against every country feature.
  3. If the centroid falls in no polygon (e.g. river mouths, small
     islands, or coastline mismatch at 110m resolution), fall back to
     the country whose boundary is geometrically closest to the point.

Example:
    python3 add_country_continent.py --csv KuroSiwo_events.csv
"""

import csv
import json
import argparse
from pathlib import Path

DEFAULT_COUNTRIES_GEOJSON = Path(__file__).parent / "data" / "ne_110m_admin_0_countries.geojson"


def point_in_ring(x, y, ring):
    """Even-odd ray-casting test against a single linear ring."""
    inside = False
    n = len(ring)
    x1, y1 = ring[0]
    for i in range(1, n + 1):
        x2, y2 = ring[i % n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
        x1, y1 = x2, y2
    return inside


def point_in_polygon(x, y, rings):
    """Even-odd across all rings of one Polygon geometry (handles holes)."""
    inside = False
    for ring in rings:
        if point_in_ring(x, y, ring):
            inside = not inside
    return inside


def point_in_geometry(x, y, geometry):
    gtype = geometry["type"]
    if gtype == "Polygon":
        return point_in_polygon(x, y, geometry["coordinates"])
    if gtype == "MultiPolygon":
        return any(point_in_polygon(x, y, poly) for poly in geometry["coordinates"])
    return False


def min_dist_to_geometry(x, y, geometry):
    """Rough nearest-vertex distance, used only as a coastal fallback."""
    gtype = geometry["type"]
    polys = geometry["coordinates"] if gtype == "MultiPolygon" else [geometry["coordinates"]]
    best = float("inf")
    for poly in polys:
        for ring in poly:
            for vx, vy in ring:
                d = (vx - x) ** 2 + (vy - y) ** 2
                if d < best:
                    best = d
    return best


def load_countries(geojson_path):
    data = json.loads(Path(geojson_path).read_text())
    return data["features"]


def lookup_country(lon, lat, features):
    for feature in features:
        if point_in_geometry(lon, lat, feature["geometry"]):
            props = feature["properties"]
            return props.get("ADMIN"), props.get("CONTINENT")

    # Fallback: nearest country boundary (coastal / small-island events).
    best_feature, best_dist = None, float("inf")
    for feature in features:
        d = min_dist_to_geometry(lon, lat, feature["geometry"])
        if d < best_dist:
            best_dist, best_feature = d, feature
    if best_feature is not None:
        props = best_feature["properties"]
        return props.get("ADMIN"), props.get("CONTINENT")
    return None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="KuroSiwo-style CSV catalogue (updated in place)")
    parser.add_argument("--out", default=None, help="Output CSV path. Default: overwrite --csv.")
    parser.add_argument("--countries-geojson", default=str(DEFAULT_COUNTRIES_GEOJSON),
                         help="Natural Earth admin-0 countries GeoJSON.")
    args = parser.parse_args()

    features = load_countries(args.countries_geojson)

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = [row for row in reader]

    if "country" not in fieldnames or "continent" not in fieldnames:
        idx = fieldnames.index("flood_case") + 1
        new_fields = [c for c in ("country", "continent") if c not in fieldnames]
        fieldnames = fieldnames[:idx] + new_fields + fieldnames[idx:]

    for row in rows:
        lat = (float(row["lat_min"]) + float(row["lat_max"])) / 2
        lon = (float(row["lon_min"]) + float(row["lon_max"])) / 2
        country, continent = lookup_country(lon, lat, features)
        row["country"] = country or "Unknown"
        row["continent"] = continent or "Unknown"
        print(f"[{row['flood_case']}] {row['country']} / {row['continent']}")

    out_path = args.out or args.csv
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
