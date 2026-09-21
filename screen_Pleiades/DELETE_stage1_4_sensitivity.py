#!/usr/bin/env python3
# Count eligible tiles across the C30 and area thresholds.

import geopandas as gpd
import pandas as pd

import config as cfg


def c30_column(threshold):
    return f"c30_{threshold:.2f}_area_fraction".replace(".", "p")


def eligible_count(tiles, years, c30, area):
    work = tiles[tiles["season_year"].isin(years)].copy()
    work["pass_test"] = (
        work["tile_contrast_evaluable"].fillna(False)
        & (pd.to_numeric(work[c30_column(c30)], errors="coerce") >= area)
    )
    season_pass = work.groupby(["tile_id", "season_year"])["pass_test"].max().reset_index()
    counts = season_pass[season_pass["pass_test"]].groupby("tile_id")["season_year"].nunique()
    return int((counts == len(years)).sum())


def main():
    tiles = gpd.read_file(
        cfg.OUTPUT_DIR / "tile_date_screening.gpkg",
        layer="tile_dates",
        ignore_geometry=True,
    )
    designs = {
        "six_season": cfg.SIX_SEASON_YEARS,
        "decade": cfg.DECADE_YEARS,
    }

    rows = []
    for design, years in designs.items():
        for c30 in cfg.C30_SENSITIVITY_THRESHOLDS:
            for area in cfg.TILE_CONTRAST_AREA_SENSITIVITY_THRESHOLDS:
                rows.append({
                    "design": design,
                    "c30_threshold": c30,
                    "area_threshold": area,
                    "eligible_tiles": eligible_count(tiles, years, c30, area),
                })

    summary = pd.DataFrame(rows)
    summary.to_csv(cfg.OUTPUT_DIR / "contrast_sensitivity_summary.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
