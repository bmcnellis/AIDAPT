#!/usr/bin/env python3
# Process the Nov-Feb Pleiades dates with Landsat, then list the dates that passed
# the date-level Landsat screen.

import argparse
import json

import pandas

import config
import module_landsat_contrast

# Functions used from module_landsat_contrast (called below as module_landsat_contrast.<name>).
#   acquisition_dates
#   compute_date
#   geometry_for_date
#   load_inputs
#   open_catalog
#   summarize_cells
#   write_geojson


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    start_month = config.SCREENING_SEASON_START_MONTH
    end_month = config.SCREENING_SEASON_END_MONTH
    inputs = module_landsat_contrast.load_inputs()
    dates = [args.date] if args.date else module_landsat_contrast.acquisition_dates(inputs)

    # Season year of each date, or None if it falls outside the screening season. A season that
    # spans new year (e.g. Nov-Feb) is labelled by the year it starts in, so Jan-Feb dates
    # belong to the previous year's season.
    season_years = {}
    for date_string in dates:
        timestamp = pandas.Timestamp(date_string)
        if start_month <= end_month:
            season_years[date_string] = (
                timestamp.year if start_month <= timestamp.month <= end_month else None
            )
        elif timestamp.month >= start_month:
            season_years[date_string] = timestamp.year
        elif timestamp.month <= end_month:
            season_years[date_string] = timestamp.year - 1
        else:
            season_years[date_string] = None

    if not args.date:
        dates = [candidate for candidate in dates if season_years[candidate] is not None]
        stop = config.END_INDEX if config.END_INDEX is not None else len(dates)
        dates = dates[config.START_INDEX:stop]

    # Process each date: one summary JSON, plus a GeoJSON of tile cells if Landsat was usable.
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    catalog = module_landsat_contrast.open_catalog()
    failed = []

    for index, date_string in enumerate(dates, start=1):
        day = date_string.replace("-", "")
        json_path = config.EXPORT_DIR / f"date_contrast_{day}.json"
        cells_path = config.EXPORT_DIR / f"date_spatial_cells_{day}.geojson"
        if config.RESUME and not args.force and json_path.exists():
            print(f"[{index}/{len(dates)}] {date_string}: skip")
            continue

        print(f"[{index}/{len(dates)}] {date_string}")
        try:
            result = module_landsat_contrast.compute_date(catalog, inputs, date_string)
            row = {
                "date": date_string,
                "season_year": season_years[date_string],
                "status": result.status,
                "message": result.message,
                "landsat_observations": result.scene_count,
            }
            cells = None
            if result.status == "OK":
                cells = module_landsat_contrast.summarize_cells(
                    date_string,
                    module_landsat_contrast.geometry_for_date(inputs, date_string),
                    result.ndvi,
                    result.contrast,
                    result.transform,
                )
            json_path.write_text(json.dumps(row, indent=2), encoding="utf-8")
            if cells is not None:
                module_landsat_contrast.write_geojson(cells, cells_path)
            print(f"  {row['status']}")
        except Exception as error:
            failed.append(date_string)
            print(f"  ERROR: {error}")

    if failed:
        print("Failed dates: " + ", ".join(failed))

    # Merge: dates with usable Landsat become candidate_dates.csv (all dates processed so far).
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(config.EXPORT_DIR.glob("date_contrast_*.json"))
    ]
    results = pandas.DataFrame(rows)
    candidates = results[results["status"].eq("OK")][["date", "season_year"]]
    candidates = candidates.sort_values("date").drop_duplicates()

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(config.OUTPUT_DIR / "candidate_dates.csv", index=False)
    print(f"Candidate dates: {len(candidates):,}")


if __name__ == "__main__":
    main()
