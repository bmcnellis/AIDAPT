#!/usr/bin/env python3
# Select one Pleiades acquisition for each final tile-season-year.

import geopandas as gpd
import pandas as pd

import config as cfg


def choose_dates(review):
    usable = review["metadata_usable"].astype("string").str.strip().str.lower()
    coverage = pd.to_numeric(review["airbus_tile_coverage_fraction"], errors="coerce")
    review = review[
        usable.isin({"true", "1", "yes", "y"})
        & coverage.ge(0.999999)
    ].copy()
    review = review.sort_values(
        ["design", "tile_order", "tile_id", "season_year", "date_order"]
    )
    return review.drop_duplicates(["design", "tile_id", "season_year"], keep="first")


def complete_tiles(chosen, design, years):
    work = chosen[chosen["design"].eq(design)]
    counts = work.groupby("tile_id")["season_year"].nunique()
    complete = set(counts[counts == len(years)].index)
    order = work[work["tile_id"].isin(complete)][["tile_id", "tile_order"]].drop_duplicates()
    return order.sort_values("tile_order")


def main():
    out_dir = cfg.OUTPUT_DIR / "imagery_selection"
    review = pd.read_csv(
        out_dir / "airbus_metadata_review.csv",
        dtype={"tile_id": str, "date": str},
    )
    chosen = choose_dates(review)

    six_ready = complete_tiles(chosen, "six_season", cfg.SIX_SEASON_YEARS)
    six_ids = six_ready.head(cfg.SIX_SEASON_TILES)["tile_id"].tolist()

    decade_ready = complete_tiles(chosen, "decade", cfg.DECADE_YEARS)
    decade_ready = decade_ready[~decade_ready["tile_id"].isin(six_ids)]
    decade_ids = decade_ready.head(cfg.ADDITIONAL_DECADE_TILES)["tile_id"].tolist()

    if len(six_ids) < cfg.SIX_SEASON_TILES or len(decade_ids) < cfg.ADDITIONAL_DECADE_TILES:
        raise RuntimeError("Not enough metadata-reviewed tiles yet.")

    six_dates = chosen[
        chosen["design"].eq("six_season") & chosen["tile_id"].isin(six_ids)
    ].copy()
    six_dates["sample_component"] = "six_season"

    decade_dates = chosen[
        chosen["design"].eq("decade") & chosen["tile_id"].isin(decade_ids)
    ].copy()
    decade_dates["sample_component"] = "additional_2013_2023"

    selected = pd.concat([six_dates, decade_dates], ignore_index=True)
    selected = selected.sort_values(["sample_component", "tile_id", "season_year"])
    selected = selected[[
        "sample_component", "tile_id", "season_year", "date", "date_order",
        "days_from_midpoint", "airbus_acquisition_id", "airbus_archive_identifier",
        "airbus_processing_level", "airbus_reported_cloud_cover",
        "airbus_tile_coverage_fraction", "airbus_quicklook",
    ]].rename(columns={"date": "acquisition_date"})

    for column in ("cloud", "haze", "shadow", "other_issue", "usable", "notes"):
        selected[column] = ""

    selected.to_csv(out_dir / "selected_imagery.csv", index=False)

    six_tiles = gpd.read_file(cfg.OUTPUT_DIR / "six_season_random_order.gpkg", layer="tiles")
    six_tiles = six_tiles[six_tiles["tile_id"].astype(str).isin(six_ids)].copy()
    six_tiles["tile_id"] = six_tiles["tile_id"].astype(str)
    six_tiles["sample_component"] = "six_season"

    decade_tiles = gpd.read_file(cfg.OUTPUT_DIR / "decade_random_order.gpkg", layer="tiles")
    decade_tiles = decade_tiles[decade_tiles["tile_id"].astype(str).isin(decade_ids)].copy()
    decade_tiles["tile_id"] = decade_tiles["tile_id"].astype(str)
    decade_tiles["sample_component"] = "additional_2013_2023"

    tiles = gpd.GeoDataFrame(
        pd.concat([six_tiles, decade_tiles], ignore_index=True),
        geometry="geometry",
        crs=six_tiles.crs,
    )

    tile_seasons = selected.merge(
        tiles[["tile_id", "geometry"]], on="tile_id", how="left"
    )
    tile_seasons = gpd.GeoDataFrame(tile_seasons, geometry="geometry", crs=tiles.crs)

    spatial = out_dir / "selected_imagery.gpkg"
    if spatial.exists():
        spatial.unlink()
    tiles.to_file(spatial, layer="tiles", driver="GPKG")
    tile_seasons.to_file(spatial, layer="tile_seasons", driver="GPKG", mode="a")

    print(f"Six-season tiles: {len(six_ids)}")
    print(f"Additional 2013/2023 tiles: {len(decade_ids)}")
    print(f"Pleiades acquisitions: {len(selected)}")
    print(f"Selected imagery: {out_dir / 'selected_imagery.csv'}")


if __name__ == "__main__":
    main()
