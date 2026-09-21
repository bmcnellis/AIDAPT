#!/usr/bin/env python3
# Build the six-season and 2013/2023 eligible tile pools.

import geopandas as gpd

import config as cfg


def tile_season_outcomes(tiles):
    grouped = tiles.groupby(["tile_id", "season_year"])
    out = grouped.agg(
        any_evaluable=("tile_contrast_evaluable", "max"),
        any_pass=("tile_contrast_pass", "max"),
    ).reset_index()
    out["outcome"] = "not_evaluable"
    out.loc[out["any_evaluable"], "outcome"] = "fail"
    out.loc[out["any_pass"], "outcome"] = "pass"
    return out[["tile_id", "season_year", "outcome"]]


def eligible_ids(outcomes, years):
    passing = outcomes[
        outcomes["season_year"].isin(years) & outcomes["outcome"].eq("pass")
    ]
    counts = passing.groupby("tile_id")["season_year"].nunique()
    return set(counts[counts == len(years)].index.astype(str))


def save_pool(tiles, tile_ids, name):
    pool = tiles[tiles["tile_id"].isin(tile_ids)][["tile_id", "geometry"]]
    pool = pool.drop_duplicates("tile_id").sort_values("tile_id")
    out = cfg.OUTPUT_DIR / f"{name}_eligible.gpkg"
    if out.exists():
        out.unlink()
    pool.to_file(out, layer="tiles", driver="GPKG")
    return pool


def main():
    tiles = gpd.read_file(cfg.OUTPUT_DIR / "tile_date_screening.gpkg", layer="tile_dates")
    tiles["tile_id"] = tiles["tile_id"].astype(str)
    outcomes = tile_season_outcomes(tiles)

    six = save_pool(tiles, eligible_ids(outcomes, cfg.SIX_SEASON_YEARS), "six_season")
    decade = save_pool(tiles, eligible_ids(outcomes, cfg.DECADE_YEARS), "decade")

    print(f"Six-season eligible tiles: {len(six):,}")
    print(f"2013/2023 eligible tiles: {len(decade):,}")


if __name__ == "__main__":
    main()
