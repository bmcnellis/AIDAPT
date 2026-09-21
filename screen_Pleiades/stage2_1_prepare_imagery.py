#!/usr/bin/env python3
# Order passing Pleiades dates within each selected tile-season-year, and write the Airbus
# metadata review table to fill in by hand before running stage2_2_select_imagery.py.

import geopandas
import pandas

import config

def main():
    # The two sampling designs: the season years each one needs, and the file with its random order
    # (written by stage1_2_tile_screening.py).
    designs = {
        "six_season": {"years": config.SIX_SEASON_YEARS, "random_order_file": config.SIX_SEASON_RANDOM_ORDER_FILE},
        "decade": {"years": config.DECADE_YEARS, "random_order_file": config.DECADE_RANDOM_ORDER_FILE},
    }

    tile_dates = geopandas.read_file(
        config.TILE_DATE_FILE,
        layer=config.TILE_DATE_LAYER,
        ignore_geometry=True,
    )
    tile_dates["tile_id"] = tile_dates["tile_id"].astype(str)

    # For each design, list the dates that passed the contrast screen for every tile in its random
    # order. Within each tile-season-year the dates are ordered by distance from the middle of the
    # screening season, so date_order 1 is the preferred date.
    design_reviews = []
    for design, spec in designs.items():
        years = spec["years"]
        random_order = geopandas.read_file(
            spec["random_order_file"],
            layer=config.POOL_LAYER,
            ignore_geometry=True,
        )
        order = random_order.set_index("tile_id")["random_order"]
        work = tile_dates[
            tile_dates["tile_id"].isin(order.index)
            & tile_dates["season_year"].isin(years)
            & tile_dates["tile_contrast_pass"].fillna(False)
        ].copy()
        work["design"] = design
        work["tile_order"] = work["tile_id"].map(order)
        work["date"] = pandas.to_datetime(work["date"])

        # Middle of each season: halfway between the 1st of the start month and the 1st of the month
        # after the end month. A season spanning new year (e.g. Nov-Feb) is labelled by the year it
        # starts in.
        start_month = config.SCREENING_SEASON_START_MONTH
        end_month = config.SCREENING_SEASON_END_MONTH
        midpoints = {}
        for season_year in years:
            start = pandas.Timestamp(year=season_year, month=start_month, day=1)
            end_year = season_year + 1 if start_month > end_month else season_year
            after_end_month = end_month % 12 + 1
            if after_end_month == 1:
                end_year += 1
            end = pandas.Timestamp(year=end_year, month=after_end_month, day=1)
            midpoints[season_year] = start + (end - start) / 2

        work["days_from_midpoint"] = (
            (work["date"] - work["season_year"].map(midpoints)).abs().dt.total_seconds() / 86400
        )
        work = work.sort_values(
            ["tile_order", "tile_id", "season_year", "days_from_midpoint", "date"]
        )
        work["date_order"] = work.groupby(["tile_id", "season_year"]).cumcount() + 1
        work["date"] = work["date"].dt.strftime("%Y-%m-%d")
        design_reviews.append(work[[
            "design", "tile_order", "tile_id", "season_year", "date",
            "date_order", "days_from_midpoint",
        ]])

    # Blank columns to fill in by hand from the Airbus catalogue.
    review = pandas.concat(design_reviews, ignore_index=True)
    for column in (
        "airbus_acquisition_id", "airbus_archive_identifier", "airbus_processing_level",
        "airbus_reported_cloud_cover", "airbus_tile_coverage_fraction", "airbus_quicklook",
        "metadata_usable", "notes",
    ):
        review[column] = ""

    config.IMAGERY_SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    review.to_csv(config.AIRBUS_REVIEW_FILE, index=False)
    print(f"Candidate acquisition rows: {len(review):,}")
    print(f"Fill in: {config.AIRBUS_REVIEW_FILE}")


if __name__ == "__main__":
    main()
