#!/usr/bin/env python3
# Merge the AOI shapefiles and the dated Pleiades footprint shapefiles into GeoPackages.

import argparse
import pathlib
import tempfile
import zipfile

import geopandas
import pandas
import shapely

import config

# Functions used from other packages (called below with their full module path, e.g. shapely.make_valid).
#   argparse:    ArgumentParser
#   geopandas:   GeoDataFrame, read_file
#   pandas:      concat, to_datetime
#   pathlib:     Path
#   shapely:     make_valid
#   tempfile:    TemporaryDirectory
#   zipfile:     ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aoi-zip", type=pathlib.Path, default=config.AOI_ZIP,
                        help="zip of AOI shapefiles")
    parser.add_argument("--footprints-zip", type=pathlib.Path, default=config.FOOTPRINTS_ZIP,
                        help="zip of dated Pleiades footprint shapefiles")
    parser.add_argument("--output-dir", type=pathlib.Path, default=config.INPUT_DIR,
                        help="folder the GeoPackages are written to (default: INPUT_DIR in config.py)")
    parser.add_argument("--crs", default=config.GRID_CRS,
                        help="CRS the GeoPackages are stored in (default: GRID_CRS in config.py)")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    aoi_output = args.output_dir / config.AOI_FILE.name
    footprints_output = args.output_dir / config.FOOTPRINTS_FILE.name

    # AOI: union all shapefile geometries into a single valid polygon.
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(args.aoi_zip) as archive:
            archive.extractall(tmp)

        aoi_parts = []
        for shapefile in sorted(pathlib.Path(tmp).rglob("*.shp")):
            part = geopandas.read_file(shapefile).to_crs(args.crs)
            if not part.empty:
                aoi_parts.append(part[["geometry"]])

    aoi_geometry = shapely.make_valid(pandas.concat(aoi_parts, ignore_index=True).union_all())
    aoi = geopandas.GeoDataFrame([{"name": "AOI", "geometry": aoi_geometry}], crs=args.crs)

    aoi_output.unlink(missing_ok=True)
    aoi.to_file(aoi_output, layer=config.AOI_LAYER, driver="GPKG")
    print(f"Wrote {aoi_output}")

    # Footprints: stack all shapefiles, taking each date from a "date" column
    # or, failing that, from a YYYY-MM-DD folder name in the shapefile's path.
    with tempfile.TemporaryDirectory() as tmp:
        extract_dir = pathlib.Path(tmp)
        with zipfile.ZipFile(args.footprints_zip) as archive:
            archive.extractall(extract_dir)

        footprint_parts = []
        for shapefile in sorted(extract_dir.rglob("*.shp")):
            part = geopandas.read_file(shapefile)
            if part.empty:
                continue

            date_column = next((column for column in part.columns if column.lower() == "date"), None)
            folder_match = config.DATE_PATTERN.search("/" + shapefile.relative_to(extract_dir).as_posix())
            if date_column is None and folder_match is None:
                continue

            part = part.to_crs(args.crs)
            if date_column is not None:
                part["date"] = pandas.to_datetime(part[date_column]).dt.strftime("%Y-%m-%d")
            else:
                part["date"] = folder_match.group(2)
            footprint_parts.append(part[["date", "geometry"]])

    footprints = pandas.concat(footprint_parts, ignore_index=True).sort_values("date", ignore_index=True)

    footprints_output.unlink(missing_ok=True)
    footprints.to_file(footprints_output, layer=config.FOOTPRINTS_LAYER, driver="GPKG")
    print(f"Dates: {footprints['date'].nunique():,}")
    print(f"Wrote {footprints_output}")


if __name__ == "__main__":
    main()
