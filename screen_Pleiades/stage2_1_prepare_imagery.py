#!/usr/bin/env python3
# Order passing Pleiades dates within each selected tile-season-year.

import geopandas as gpd
import pandas as pd

import config as cfg


def season_midpoint(season_year):
    start = pd.Timestamp(year=season_year, month=cfg.SCREENING_SEASON_START_MONTH, day=1)
    end_year = season_year + 1 if cfg.SCREENING_SEASON_START_MONTH > cfg.SCREENING_SEASON_END_MONTH else season_year
    end_month = cfg.SCREENING_SEASON_END_MONTH % 12 + 1
    if end_month == 1:
        end_year += 1
    end = pd.Timestamp(year=end_year, month=end_month, day=1)
    return start + (end - start) / 2


def candidate_dates(tile_dates, random_order, years, design):
    order = random_order.set_index("tile_id")["random_order"]
    work = tile_dates[
        tile_dates["tile_id"].isin(order.index)
        & tile_dates["season_year"].isin(years)
        & tile_dates["tile_contrast_pass"].fillna(False)
    ].copy()

    work["design"] = design
    work["tile_order"] = work["tile_id"].map(order)
    work["date"] = pd.to_datetime(work["date"])
    midpoint = work["season_year"].map(season_midpoint)
    work["days_from_midpoint"] = (
        (work["date"] - midpoint).abs().dt.total_seconds() / 86400
    )
    work = work.sort_values(
        ["tile_order", "tile_id", "season_year", "days_from_midpoint", "date"]
    )
    work["date_order"] = work.groupby(["tile_id", "season_year"]).cumcount() + 1
    work["date"] = work["date"].dt.strftime("%Y-%m-%d")
    return work[[
        "design", "tile_order", "tile_id", "season_year", "date",
        "date_order", "days_from_midpoint",
    ]]


def main():
    tile_dates = gpd.read_file(
        cfg.OUTPUT_DIR / "tile_date_screening.gpkg",
        layer="tile_dates",
        ignore_geometry=True,
    )
    tile_dates["tile_id"] = tile_dates["tile_id"].astype(str)

    six_order = gpd.read_file(
        cfg.OUTPUT_DIR / "six_season_random_order.gpkg",
        layer="tiles",
        ignore_geometry=True,
    )
    decade_order = gpd.read_file(
        cfg.OUTPUT_DIR / "decade_random_order.gpkg",
        layer="tiles",
        ignore_geometry=True,
    )

    review = pd.concat([
        candidate_dates(tile_dates, six_order, cfg.SIX_SEASON_YEARS, "six_season"),
        candidate_dates(tile_dates, decade_order, cfg.DECADE_YEARS, "decade"),
    ], ignore_index=True)
    review["airbus_acquisition_id"] = ""
    review["airbus_archive_identifier"] = ""
    review["airbus_processing_level"] = ""
    review["airbus_reported_cloud_cover"] = ""
    review["airbus_tile_coverage_fraction"] = ""
    review["airbus_quicklook"] = ""
    review["metadata_usable"] = ""
    review["notes"] = ""

    out_dir = cfg.OUTPUT_DIR / "imagery_selection"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "airbus_metadata_review.csv"
    review.to_csv(out, index=False)
    print(f"Candidate acquisition rows: {len(review):,}")
    print(f"Fill in: {out}")


if __name__ == "__main__":
    main()
