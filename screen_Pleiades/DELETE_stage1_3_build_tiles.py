#!/usr/bin/env python3
# Build the 1 km tile-date table and apply the tile screening rules.

import math

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely import make_valid
from shapely.geometry import box, mapping

import config as cfg


CLUM_GEOREF_SOURCES = "WORLDFILE,PAM,INTERNAL"


def make_grid(geom):
    size = cfg.GRID_SIZE_M
    minx, miny, maxx, maxy = geom.bounds
    x0 = math.floor(minx / size) * size
    y0 = math.floor(miny / size) * size
    x1 = math.ceil(maxx / size) * size
    y1 = math.ceil(maxy / size) * size

    rows = []
    for x in np.arange(x0, x1, size):
        for y in np.arange(y0, y1, size):
            cell = box(x, y, x + size, y + size)
            if cell.intersects(geom):
                rows.append({"tile_id": f"T_{int(x)}_{int(y)}", "geometry": cell})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=cfg.GRID_CRS)


def agricultural_fraction(src, geom):
    geom_src = gpd.GeoSeries([geom], crs=cfg.GRID_CRS).to_crs(src.crs).iloc[0]
    window = from_bounds(*geom_src.bounds, transform=src.transform)
    window = window.round_offsets().round_lengths()
    window = window.intersection(rasterio.windows.Window(0, 0, src.width, src.height))

    arr = src.read(1, window=window, masked=False)
    inside = geometry_mask(
        [mapping(geom_src)],
        out_shape=arr.shape,
        transform=src.window_transform(window),
        invert=True,
    )
    valid = inside & np.isfinite(arr)
    if src.nodata is not None:
        valid &= arr != src.nodata
    if not valid.any():
        return np.nan
    return float(((arr == cfg.CLUM_VALUE) & valid).sum() / valid.sum())


def c30_column(threshold):
    return f"c30_{threshold:.2f}_area_fraction".replace(".", "p")


def load_contrast(date_string):
    day = date_string.replace("-", "")
    cells = gpd.read_file(cfg.EXPORT_DIR / f"date_spatial_cells_{day}.geojson")
    keep = ["tile_id", "valid_coverage_fraction"] + [
        c30_column(t) for t in cfg.C30_SENSITIVITY_THRESHOLDS
    ]
    cells = cells[keep].copy()
    cells = cells.rename(columns={"valid_coverage_fraction": "tile_valid_coverage_fraction"})
    return pd.DataFrame(cells)


def build_date_tiles(date_string, season_year, footprints, clum, agri_cache):
    footprint = make_valid(footprints.geometry.union_all())
    grid = make_grid(footprint)
    grid["date"] = date_string
    grid["season_year"] = int(season_year)
    grid["pleiades_coverage_fraction"] = [
        cell.intersection(footprint).area / cell.area for cell in grid.geometry
    ]

    fractions = []
    for tile_id, cell in zip(grid["tile_id"], grid.geometry):
        if tile_id not in agri_cache:
            agri_cache[tile_id] = agricultural_fraction(clum, cell)
        fractions.append(agri_cache[tile_id])
    grid["agricultural_fraction"] = fractions

    grid = grid[
        (grid["pleiades_coverage_fraction"] >= cfg.MIN_PLEIADES_COVERAGE - 1e-9)
        & (grid["agricultural_fraction"] >= cfg.MIN_AGRICULTURAL_FRACTION)
    ].copy()

    grid = grid.merge(load_contrast(date_string), on="tile_id", how="left")
    primary = c30_column(cfg.PRIMARY_C30_THRESHOLD)
    grid["tile_contrast_evaluable"] = (
        grid["tile_valid_coverage_fraction"] >= cfg.MIN_TILE_VALID_COVERAGE
    ) & grid[primary].notna()
    grid["tile_contrast_pass"] = (
        grid["tile_contrast_evaluable"]
        & (grid[primary] >= cfg.MIN_TILE_CONTRAST_METRIC_VALUE)
    )
    return gpd.GeoDataFrame(grid, geometry="geometry", crs=cfg.GRID_CRS)


def main():
    candidates = pd.read_csv(cfg.OUTPUT_DIR / "candidate_dates.csv")
    candidates["date"] = pd.to_datetime(candidates["date"]).dt.strftime("%Y-%m-%d")
    season_year_by_date = dict(zip(candidates["date"], candidates["season_year"]))

    footprints = gpd.read_file(cfg.FOOTPRINTS_FILE, layer=cfg.FOOTPRINTS_LAYER).to_crs(cfg.GRID_CRS)
    footprints["date"] = pd.to_datetime(footprints[cfg.DATE_FIELD]).dt.strftime("%Y-%m-%d")
    footprints = footprints[footprints["date"].isin(season_year_by_date)].copy()

    outputs = []
    agri_cache = {}
    with rasterio.Env(GDAL_GEOREF_SOURCES=CLUM_GEOREF_SOURCES):
        with rasterio.open(cfg.CLUM_RASTER) as clum:
            for date_string, date_footprints in footprints.groupby("date"):
                tiles = build_date_tiles(
                    date_string,
                    season_year_by_date[date_string],
                    date_footprints,
                    clum,
                    agri_cache,
                )
                outputs.append(tiles)
                print(f"{date_string}: {len(tiles):,} eligible, {int(tiles['tile_contrast_pass'].sum()):,} pass")

    merged = gpd.GeoDataFrame(
        pd.concat(outputs, ignore_index=True), geometry="geometry", crs=cfg.GRID_CRS
    )
    out = cfg.OUTPUT_DIR / "tile_date_screening.gpkg"
    if out.exists():
        out.unlink()
    merged.to_file(out, layer="tile_dates", driver="GPKG")
    print(f"Tile-date rows: {len(merged):,}")


if __name__ == "__main__":
    main()
