#!/usr/bin/env python3
# Screen the 1 km tiles on every candidate date, build the eligible tile pools, and give each
# pool a fixed random order. Each step writes its output file before the next step starts:
#   1. Tile-date table   -> tile_date_screening.gpkg
#   2. Sensitivity table -> contrast_sensitivity_summary.csv
#   3. Eligible pools    -> six_season_eligible.gpkg, decade_eligible.gpkg
#   4. Random orders     -> six_season_random_order.gpkg, decade_random_order.gpkg

import math

import geopandas
import numpy
import pandas
import rasterio
import rasterio.features
import rasterio.windows
import shapely
import shapely.geometry

import config

# Functions used from other packages (called below with their full module path, e.g. shapely.make_valid).
#   geopandas:          GeoDataFrame, GeoSeries, read_file
#   math:               ceil, floor
#   numpy:              arange, isfinite
#   pandas:             DataFrame, concat, read_csv, to_datetime
#   rasterio:           Env, open
#   rasterio.features:  geometry_mask
#   rasterio.windows:   Window, from_bounds
#   shapely:            make_valid
#   shapely.geometry:   box, mapping


def main():
    # Column written by module_landsat_contrast.summarize_cells() for each C30 threshold,
    # e.g. 0.03 -> "c30_0p03_area_fraction". The names must match what that function writes.
    c30_columns = {
        threshold: f"c30_{threshold:.2f}_area_fraction".replace(".", "p")
        for threshold in config.C30_SENSITIVITY_THRESHOLDS
    }
    primary_column = c30_columns[config.PRIMARY_C30_THRESHOLD]

    # The two sampling designs: the season years a tile must pass in, and the seed for its random order.
    designs = {
        "six_season": {"years": config.SIX_SEASON_YEARS, "seed": config.SIX_SEASON_SEED},
        "decade": {"years": config.DECADE_YEARS, "seed": config.DECADE_SEED},
    }

    # Step 1: build the tile-date table. For every candidate date, take the 1 km grid cells that touch
    # that date's Pleiades footprint and add: Pleiades coverage, agricultural fraction (from CLUM),
    # and the Landsat coverage and C30 results from stage1_1_process_dates.py.
    candidates = pandas.read_csv(config.OUTPUT_DIR / "candidate_dates.csv")
    candidates["date"] = pandas.to_datetime(candidates["date"]).dt.strftime("%Y-%m-%d")
    season_year_by_date = dict(zip(candidates["date"], candidates["season_year"]))

    footprints = geopandas.read_file(
        config.FOOTPRINTS_FILE, layer=config.FOOTPRINTS_LAYER
    ).to_crs(config.GRID_CRS)
    footprints["date"] = pandas.to_datetime(footprints[config.DATE_FIELD]).dt.strftime("%Y-%m-%d")
    footprints = footprints[footprints["date"].isin(season_year_by_date)].copy()

    outputs = []
    agri_cache = {}  # tile_id -> agricultural fraction; a tile's value does not change between dates
    with rasterio.Env(GDAL_GEOREF_SOURCES=config.CLUM_GEOREF_SOURCES), rasterio.open(config.CLUM_RASTER) as clum:
        for date_string, date_footprints in footprints.groupby("date"):
            footprint = shapely.make_valid(date_footprints.geometry.union_all())

            # Grid cells aligned to multiples of GRID_SIZE_M that touch the footprint.
            size = config.GRID_SIZE_M
            minx, miny, maxx, maxy = footprint.bounds
            x0 = math.floor(minx / size) * size
            y0 = math.floor(miny / size) * size
            x1 = math.ceil(maxx / size) * size
            y1 = math.ceil(maxy / size) * size
            grid_rows = []
            for x in numpy.arange(x0, x1, size):
                for y in numpy.arange(y0, y1, size):
                    cell = shapely.geometry.box(x, y, x + size, y + size)
                    if cell.intersects(footprint):
                        grid_rows.append({"tile_id": f"T_{int(x)}_{int(y)}", "geometry": cell})
            grid = geopandas.GeoDataFrame(grid_rows, geometry="geometry", crs=config.GRID_CRS)
            grid["date"] = date_string
            grid["season_year"] = int(season_year_by_date[date_string])
            grid["pleiades_coverage_fraction"] = [
                cell.intersection(footprint).area / cell.area for cell in grid.geometry
            ]

            # Agricultural fraction of each tile: the share of valid CLUM pixels equal to CLUM_VALUE
            # (NaN if the tile has no valid CLUM pixels).
            agri_fractions = []
            for tile_id, cell in zip(grid["tile_id"], grid.geometry):
                if tile_id not in agri_cache:
                    clum_cell = geopandas.GeoSeries([cell], crs=config.GRID_CRS).to_crs(clum.crs).iloc[0]
                    window = rasterio.windows.from_bounds(*clum_cell.bounds, transform=clum.transform)
                    window = window.round_offsets().round_lengths()
                    window = window.intersection(rasterio.windows.Window(0, 0, clum.width, clum.height))
                    clum_values = clum.read(1, window=window, masked=False)
                    inside = rasterio.features.geometry_mask(
                        [shapely.geometry.mapping(clum_cell)],
                        out_shape=clum_values.shape,
                        transform=clum.window_transform(window),
                        invert=True,
                    )
                    valid = inside & numpy.isfinite(clum_values)
                    if clum.nodata is not None:
                        valid &= clum_values != clum.nodata
                    if valid.any():
                        agri_cache[tile_id] = float(
                            ((clum_values == config.CLUM_VALUE) & valid).sum() / valid.sum()
                        )
                    else:
                        agri_cache[tile_id] = numpy.nan
                agri_fractions.append(agri_cache[tile_id])
            grid["agricultural_fraction"] = agri_fractions

            grid = grid[
                (grid["pleiades_coverage_fraction"] >= config.MIN_PLEIADES_COVERAGE - 1e-9)
                & (grid["agricultural_fraction"] >= config.MIN_AGRICULTURAL_FRACTION)
            ].copy()

            # Landsat results for this date: valid coverage and the area fraction at each C30 threshold.
            day = date_string.replace("-", "")
            landsat_cells = geopandas.read_file(config.EXPORT_DIR / f"date_spatial_cells_{day}.geojson")
            landsat_cells = landsat_cells[
                ["tile_id", "valid_coverage_fraction", *c30_columns.values()]
            ].rename(columns={"valid_coverage_fraction": "tile_valid_coverage_fraction"})
            grid = grid.merge(pandas.DataFrame(landsat_cells), on="tile_id", how="left")

            # A tile is evaluable if enough of it has valid Landsat NDVI, and passes if the area
            # fraction at the primary C30 threshold reaches MIN_TILE_CONTRAST_METRIC_VALUE.
            grid["tile_contrast_evaluable"] = (
                grid["tile_valid_coverage_fraction"] >= config.MIN_TILE_VALID_COVERAGE
            ) & grid[primary_column].notna()
            grid["tile_contrast_pass"] = grid["tile_contrast_evaluable"] & (
                grid[primary_column] >= config.MIN_TILE_CONTRAST_METRIC_VALUE
            )
            date_tiles = geopandas.GeoDataFrame(grid, geometry="geometry", crs=config.GRID_CRS)
            outputs.append(date_tiles)
            print(
                f"{date_string}: {len(date_tiles):,} eligible, "
                f"{int(date_tiles['tile_contrast_pass'].sum()):,} pass"
            )

    tiles = geopandas.GeoDataFrame(
        pandas.concat(outputs, ignore_index=True), geometry="geometry", crs=config.GRID_CRS
    )
    screening_path = config.OUTPUT_DIR / "tile_date_screening.gpkg"
    if screening_path.exists():
        screening_path.unlink()
    tiles.to_file(screening_path, layer="tile_dates", driver="GPKG")
    print(f"Tile-date rows: {len(tiles):,}")

    # Step 2: sensitivity. For each design, count the tiles that pass in every season year of the
    # design, for each combination of C30 threshold and area threshold.
    attributes = tiles.drop(columns="geometry")
    summary_rows = []
    for design, spec in designs.items():
        design_tiles = attributes[attributes["season_year"].isin(spec["years"])].copy()
        for c30 in config.C30_SENSITIVITY_THRESHOLDS:
            for area in config.TILE_CONTRAST_AREA_SENSITIVITY_THRESHOLDS:
                design_tiles["pass_test"] = (
                    design_tiles["tile_contrast_evaluable"] & (design_tiles[c30_columns[c30]] >= area)
                )
                season_pass = (
                    design_tiles.groupby(["tile_id", "season_year"])["pass_test"].max().reset_index()
                )
                passing_seasons = season_pass[season_pass["pass_test"]].groupby("tile_id")["season_year"].nunique()
                summary_rows.append({
                    "design": design,
                    "c30_threshold": c30,
                    "area_threshold": area,
                    "eligible_tiles": int((passing_seasons == len(spec["years"])).sum()),
                })

    summary = pandas.DataFrame(summary_rows)
    summary.to_csv(config.OUTPUT_DIR / "contrast_sensitivity_summary.csv", index=False)
    print(summary.to_string(index=False))

    # Step 3: eligible pools. Each tile-season-year is "pass" if any date that season passed,
    # "fail" if some date was evaluable but none passed, and "not_evaluable" otherwise. A tile is
    # eligible for a design if it passes in every season year of that design.
    outcomes = tiles.groupby(["tile_id", "season_year"]).agg(
        any_evaluable=("tile_contrast_evaluable", "max"),
        any_pass=("tile_contrast_pass", "max"),
    ).reset_index()
    outcomes["outcome"] = "not_evaluable"
    outcomes.loc[outcomes["any_evaluable"], "outcome"] = "fail"
    outcomes.loc[outcomes["any_pass"], "outcome"] = "pass"

    pools = {}
    for design, spec in designs.items():
        passing = outcomes[outcomes["season_year"].isin(spec["years"]) & outcomes["outcome"].eq("pass")]
        passing_seasons = passing.groupby("tile_id")["season_year"].nunique()
        eligible_ids = passing_seasons[passing_seasons == len(spec["years"])].index
        pool = tiles[tiles["tile_id"].isin(eligible_ids)][["tile_id", "geometry"]]
        pools[design] = pool.drop_duplicates("tile_id").sort_values("tile_id")

        pool_path = config.OUTPUT_DIR / f"{design}_eligible.gpkg"
        if pool_path.exists():
            pool_path.unlink()
        pools[design].to_file(pool_path, layer="tiles", driver="GPKG")
        print(f"{design}: {len(pools[design]):,} eligible tiles")

    # Step 4: random orders. Each pool is sorted by tile_id and shuffled with the design's fixed seed,
    # so the order is reproducible and can be extended later with extra or replacement tiles.
    for design, spec in designs.items():
        ordered = pools[design].sort_values("tile_id").sample(frac=1, random_state=spec["seed"])
        ordered = ordered.reset_index(drop=True)
        ordered["random_order"] = range(1, len(ordered) + 1)

        order_path = config.OUTPUT_DIR / f"{design}_random_order.gpkg"
        if order_path.exists():
            order_path.unlink()
        ordered.to_file(order_path, layer="tiles", driver="GPKG")
        print(f"{design}: random order saved (seed {spec['seed']})")


if __name__ == "__main__":
    main()
