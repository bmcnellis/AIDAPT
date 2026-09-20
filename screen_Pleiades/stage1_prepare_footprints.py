#!/usr/bin/env python3
# Merge dated Pleiades footprint shapefiles into one GeoPackage.

import argparse
import re
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd


DEFAULT_INPUT = Path("per_date_shapefiles.zip")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "inputs" / "pleiades_footprints_merged.gpkg"
DATE_RE = re.compile(r"(^|/)(\d{4}-\d{2}-\d{2})(/|$)")


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--crs", default="EPSG:3577")
    return p.parse_args()


def read_dated_shapefile(shp, root, crs):
    gdf = gpd.read_file(shp)
    if gdf.empty:
        return None

    date_col = next((c for c in gdf.columns if c.lower() == "date"), None)
    match = DATE_RE.search("/" + shp.relative_to(root).as_posix())
    if date_col is None and match is None:
        return None

    gdf = gdf.to_crs(crs)
    if date_col is not None:
        gdf["date"] = pd.to_datetime(gdf[date_col]).dt.strftime("%Y-%m-%d")
    else:
        gdf["date"] = match.group(2)
    return gdf[["date", "geometry"]]


def merge_footprints(zip_path, crs):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(src)

        parts = []
        for shp in sorted(src.rglob("*.shp")):
            part = read_dated_shapefile(shp, src, crs)
            if part is not None:
                parts.append(part)

        merged = gpd.GeoDataFrame(
            pd.concat(parts, ignore_index=True), geometry="geometry", crs=crs
        )
        merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
        return merged.sort_values("date").reset_index(drop=True)


def main():
    args = get_args()
    footprints = merge_footprints(args.input, args.crs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    footprints.to_file(args.output, layer="footprints", driver="GPKG")
    print(f"Dates: {footprints['date'].nunique():,}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
