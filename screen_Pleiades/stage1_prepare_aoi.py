#!/usr/bin/env python3
# Merge AOI shapefiles into one GeoPackage.

import argparse
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid


DEFAULT_INPUT = Path("AOI.zip")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "inputs" / "AOI_merged.gpkg"


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--crs", default="EPSG:3577")
    return p.parse_args()


def merge_aoi(zip_path, crs):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(src)

        parts = []
        for shp in sorted(src.rglob("*.shp")):
            gdf = gpd.read_file(shp).to_crs(crs)
            if not gdf.empty:
                parts.append(gdf[["geometry"]])

        merged = gpd.GeoDataFrame(
            pd.concat(parts, ignore_index=True), geometry="geometry", crs=crs
        )
        geom = make_valid(merged.geometry.union_all())
        return gpd.GeoDataFrame([{"name": "AOI", "geometry": geom}], crs=crs)


def main():
    args = get_args()
    out = merge_aoi(args.input, args.crs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    out.to_file(args.output, layer="aoi", driver="GPKG")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
