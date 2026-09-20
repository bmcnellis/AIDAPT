#!/usr/bin/env python3
# Process the Nov-Feb Pleiades dates with Landsat.

import argparse
import json


import config as cfg
from landsat_contrast import (
    acquisition_dates,
    compute_date,
    geometry_for_date,
    load_inputs,
    open_catalog,
    summarize_cells,
    write_geojson,
)
from season_utils import season_year


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--date")
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def output_paths(date_string):
    day = date_string.replace("-", "")
    return (
        cfg.EXPORT_DIR / f"date_contrast_{day}.json",
        cfg.EXPORT_DIR / f"date_spatial_cells_{day}.geojson",
    )


def process_date(catalog, inputs, date_string):
    result = compute_date(catalog, inputs, date_string)
    sy = season_year(
        date_string,
        cfg.SCREENING_SEASON_START_MONTH,
        cfg.SCREENING_SEASON_END_MONTH,
    )
    row = {
        "date": date_string,
        "season_year": sy,
        "status": result.status,
        "message": result.message,
        "landsat_observations": result.scene_count,
    }

    if result.status != "OK":
        return row, None

    cells = summarize_cells(
        date_string,
        geometry_for_date(inputs, date_string),
        result.ndvi,
        result.contrast,
        result.transform,
    )
    return row, cells


def main():
    args = get_args()
    inputs = load_inputs()
    dates = [
        d for d in acquisition_dates(inputs)
        if season_year(
            d,
            cfg.SCREENING_SEASON_START_MONTH,
            cfg.SCREENING_SEASON_END_MONTH,
        ) is not None
    ]

    if args.date:
        dates = [args.date]
    else:
        stop = cfg.END_INDEX if cfg.END_INDEX is not None else len(dates)
        dates = dates[cfg.START_INDEX:stop]

    cfg.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    catalog = open_catalog()
    failed = []

    for i, date_string in enumerate(dates, start=1):
        json_path, cells_path = output_paths(date_string)
        if cfg.RESUME and not args.force and json_path.exists():
            print(f"[{i}/{len(dates)}] {date_string}: skip")
            continue

        print(f"[{i}/{len(dates)}] {date_string}")
        try:
            row, cells = process_date(catalog, inputs, date_string)
            json_path.write_text(json.dumps(row, indent=2), encoding="utf-8")
            if cells is not None:
                write_geojson(cells, cells_path)
            print(f"  {row['status']}")
        except Exception as exc:
            failed.append(date_string)
            print(f"  ERROR: {exc}")

    if failed:
        print("Failed dates: " + ", ".join(failed))


if __name__ == "__main__":
    main()
