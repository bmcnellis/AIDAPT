#!/usr/bin/env python3
# Select one Pleiades acquisition for each final tile-season-year, from the Airbus metadata
# review table filled in after stage2_1_prepare_imagery.py.

import geopandas
import pandas

import config

# Functions used from other packages (called below with their full module path, e.g. pandas.concat).
#   geopandas:  GeoDataFrame, read_file
#   pandas:     concat, read_csv, to_numeric


def main():
    # The two sampling designs: the season years a tile must have imagery for, how many tiles to take,
    # the sample_component label used in the outputs, the label used in the printed summary, and the
    # file with the design's random order (written by stage1_2_tile_screening.py).
    designs = {
        "six_season": {
            "years": config.SIX_SEASON_YEARS,
            "tiles": config.SIX_SEASON_TILES,
            "sample_component": "six_season",
            "label": "Six-season tiles",
            "random_order_file": config.SIX_SEASON_RANDOM_ORDER_FILE,
        },
        "decade": {
            "years": config.DECADE_YEARS,
            "tiles": config.ADDITIONAL_DECADE_TILES,
            "sample_component": "additional_2013_2023",
            "label": "Additional 2013/2023 tiles",
            "random_order_file": config.DECADE_RANDOM_ORDER_FILE,
        },
    }

    # Keep only the rows marked usable whose individual Airbus acquisition covers the whole tile,
    # then take the best-ordered remaining date for each tile-season-year.
    review = pandas.read_csv(
        config.AIRBUS_REVIEW_FILE,
        dtype={"tile_id": str, "date": str},
    )
    usable = review["metadata_usable"].astype("string").str.strip().str.lower()
    coverage = pandas.to_numeric(review["airbus_tile_coverage_fraction"], errors="coerce")
    review = review[
        usable.isin({"true", "1", "yes", "y"})
        & coverage.ge(0.999999)
    ].copy()
    review = review.sort_values(
        ["design", "tile_order", "tile_id", "season_year", "date_order"]
    )
    chosen = review.drop_duplicates(["design", "tile_id", "season_year"], keep="first")

    # For each design, take the first tiles (in random order) that have a usable acquisition in every
    # season year of the design. Tiles already taken by an earlier design are skipped.
    taken_ids = []
    design_dates = []
    design_tiles = []
    for design, spec in designs.items():
        work = chosen[chosen["design"].eq(design)]
        counts = work.groupby("tile_id")["season_year"].nunique()
        complete_ids = counts[counts == len(spec["years"])].index
        ready = work[work["tile_id"].isin(complete_ids)][["tile_id", "tile_order"]]
        ready = ready.drop_duplicates().sort_values("tile_order")
        ready = ready[~ready["tile_id"].isin(taken_ids)]
        tile_ids = ready.head(spec["tiles"])["tile_id"].tolist()
        if len(tile_ids) < spec["tiles"]:
            raise RuntimeError("Not enough metadata-reviewed tiles yet.")
        taken_ids += tile_ids

        dates = work[work["tile_id"].isin(tile_ids)].copy()
        dates["sample_component"] = spec["sample_component"]
        design_dates.append(dates)

        tiles = geopandas.read_file(spec["random_order_file"], layer=config.POOL_LAYER)
        tiles = tiles[tiles["tile_id"].astype(str).isin(tile_ids)].copy()
        tiles["tile_id"] = tiles["tile_id"].astype(str)
        tiles["sample_component"] = spec["sample_component"]
        design_tiles.append(tiles)

        print(f"{spec['label']}: {len(tile_ids)}")

    selected = pandas.concat(design_dates, ignore_index=True)
    selected = selected.sort_values(["sample_component", "tile_id", "season_year"])
    selected = selected[[
        "sample_component", "tile_id", "season_year", "date", "date_order",
        "days_from_midpoint", "airbus_acquisition_id", "airbus_archive_identifier",
        "airbus_processing_level", "airbus_reported_cloud_cover",
        "airbus_tile_coverage_fraction", "airbus_quicklook",
    ]].rename(columns={"date": "acquisition_date"})

    # Blank columns for the visual check of the downloaded imagery.
    for column in ("cloud", "haze", "shadow", "other_issue", "usable", "notes"):
        selected[column] = ""
    selected.to_csv(config.SELECTED_IMAGERY_FILE, index=False)

    tiles = geopandas.GeoDataFrame(
        pandas.concat(design_tiles, ignore_index=True),
        geometry="geometry",
        crs=design_tiles[0].crs,
    )
    tile_seasons = selected.merge(tiles[["tile_id", "geometry"]], on="tile_id", how="left")
    tile_seasons = geopandas.GeoDataFrame(tile_seasons, geometry="geometry", crs=tiles.crs)

    if config.SELECTED_IMAGERY_GPKG.exists():
        config.SELECTED_IMAGERY_GPKG.unlink()
    tiles.to_file(config.SELECTED_IMAGERY_GPKG, layer="tiles", driver="GPKG")
    tile_seasons.to_file(config.SELECTED_IMAGERY_GPKG, layer="tile_seasons", driver="GPKG", mode="a")

    print(f"Pleiades acquisitions: {len(selected)}")
    print(f"Selected imagery: {config.SELECTED_IMAGERY_FILE}")


if __name__ == "__main__":
    main()
