#!/usr/bin/env python3
# Collate the final results:
#   1. export the tree-by-season table and matching spatial layers, and
#   2. write a PDF summary of the whole workflow: what went in, how many dates, tiles and years were
#      screened and selected, the tree results, and every input and output (including intermediate products).
#
# Run it after all the earlier stages, and after the tree detection results are in place. The numbers in
# the PDF are read from the pipeline outputs on disk when the script runs.

import datetime
import html
import json

import geopandas
import pandas
import reportlab.lib.colors
import reportlab.lib.enums
import reportlab.lib.pagesizes
import reportlab.lib.styles
import reportlab.lib.units
import reportlab.platypus

import config

# Constants: reportlab.lib.units.cm, reportlab.lib.enums.TA_RIGHT


def main():
    # The two sampling designs. "pool" names are used for the eligible tiles, "sample" names for the
    # selected tiles (the six-season tiles are excluded from the additional 2013/2023 sample).
    designs = {
        "six_season": {
            "pool_label": "Six-season",
            "sample_label": "Six-season",
            "sample_component": "six_season",
            "years": config.SIX_SEASON_YEARS,
            "tiles": config.SIX_SEASON_TILES,
            "eligible_file": config.SIX_SEASON_ELIGIBLE_FILE,
        },
        "decade": {
            "pool_label": "2013/2023",
            "sample_label": "Additional 2013/2023",
            "sample_component": "additional_2013_2023",
            "years": config.DECADE_YEARS,
            "tiles": config.ADDITIONAL_DECADE_TILES,
            "eligible_file": config.DECADE_ELIGIBLE_FILE,
        },
    }

    # Stop early, with the full list, if anything this script reads is missing.
    required = [
        config.TREE_OBSERVATIONS_FILE,
        config.TREE_LOCATIONS_FILE,
        config.SELECTED_IMAGERY_FILE,
        config.AIRBUS_REVIEW_FILE,
        config.FOOTPRINTS_FILE,
        config.CANDIDATE_DATES_FILE,
        config.TILE_DATE_FILE,
        config.SENSITIVITY_FILE,
        config.SIX_SEASON_ELIGIBLE_FILE,
        config.DECADE_ELIGIBLE_FILE,
    ]
    missing = [str(path) for path in required if not path.exists()]
    date_summaries = config.EXPORT_DIR / config.DATE_SUMMARY_NAME.format(day="*")
    if not any(config.EXPORT_DIR.glob(date_summaries.name)):
        missing.append(str(date_summaries))
    if missing:
        raise FileNotFoundError("Missing required inputs:\n  " + "\n  ".join(missing))

    # ---- Part 1: the tree-by-season table and matching spatial layers ----
    observations = pandas.read_csv(config.TREE_OBSERVATIONS_FILE)
    locations = geopandas.read_file(config.TREE_LOCATIONS_FILE, layer=config.TREE_LOCATIONS_LAYER)
    selected = pandas.read_csv(
        config.SELECTED_IMAGERY_FILE, dtype={"tile_id": str, "acquisition_date": str}
    )

    observations = observations[["tile_id", "season_year", "tree_id", "detected"]].copy()
    observations = observations.sort_values(["tile_id", "tree_id", "season_year"])

    # Add the sample component and acquisition date of the imagery each observation was made from. The link
    # to the imagery is still tile_id + season_year, which identify one selected acquisition; the two new
    # columns only repeat what selected_imagery.csv holds for that pair. The merge keeps every observation
    # once (validate= stops it if a tile-season-year were listed twice in selected_imagery.csv), and an
    # observation with no selected imagery keeps blank values in both columns.
    observations = observations.merge(
        selected[["tile_id", "season_year", "sample_component", "acquisition_date"]],
        on=["tile_id", "season_year"],
        how="left",
        validate="many_to_one",
    )

    config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    observations.to_csv(config.ANALYSIS_OBSERVATIONS_FILE, index=False)

    locations = locations[["tile_id", "tree_id", "geometry"]].copy()
    spatial_obs = locations.merge(observations, on=["tile_id", "tree_id"], how="inner")
    spatial_obs = geopandas.GeoDataFrame(spatial_obs, geometry="geometry", crs=locations.crs)

    if config.ANALYSIS_SPATIAL_FILE.exists():
        config.ANALYSIS_SPATIAL_FILE.unlink()
    locations.to_file(config.ANALYSIS_SPATIAL_FILE, layer="tree_locations", driver="GPKG")
    spatial_obs.to_file(config.ANALYSIS_SPATIAL_FILE, layer="tree_observations", driver="GPKG", mode="a")

    print(f"Tree-season rows: {len(observations):,}")

    # ---- Part 2: numbers for the summary ----
    # Stage 1, step 1: one summary JSON per screened date.
    date_results = pandas.DataFrame([
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(config.EXPORT_DIR.glob(date_summaries.name))
    ])
    candidate_dates = pandas.read_csv(config.CANDIDATE_DATES_FILE)
    footprints = geopandas.read_file(
        config.FOOTPRINTS_FILE, layer=config.FOOTPRINTS_LAYER, ignore_geometry=True
    )
    status_by_year = pandas.crosstab(date_results["season_year"], date_results["status"])
    status_by_year = status_by_year.reindex(columns=["OK", "NO_SCENES", "NO_VALID_PIXELS"], fill_value=0)

    # Stage 1, step 2: the tile-date table, summarised to tile-season-years (pass / fail / not_evaluable).
    tile_dates = geopandas.read_file(
        config.TILE_DATE_FILE, layer=config.TILE_DATE_LAYER, ignore_geometry=True
    )
    tile_dates["tile_contrast_evaluable"] = tile_dates["tile_contrast_evaluable"].fillna(False).astype(bool)
    tile_dates["tile_contrast_pass"] = tile_dates["tile_contrast_pass"].fillna(False).astype(bool)
    tile_seasons = tile_dates.groupby(["tile_id", "season_year"]).agg(
        any_evaluable=("tile_contrast_evaluable", "max"),
        any_pass=("tile_contrast_pass", "max"),
    ).reset_index()
    tile_seasons["outcome"] = "not_evaluable"
    tile_seasons.loc[tile_seasons["any_evaluable"], "outcome"] = "fail"
    tile_seasons.loc[tile_seasons["any_pass"], "outcome"] = "pass"
    outcome_by_year = pandas.crosstab(tile_seasons["season_year"], tile_seasons["outcome"])
    outcome_by_year = outcome_by_year.reindex(columns=["pass", "fail", "not_evaluable"], fill_value=0)

    pool_sizes = {
        design: len(geopandas.read_file(spec["eligible_file"], layer=config.POOL_LAYER, ignore_geometry=True))
        for design, spec in designs.items()
    }
    sensitivity = pandas.read_csv(config.SENSITIVITY_FILE)

    # Stage 2: the Airbus review table (as filled in by hand) and the final selection.
    review = pandas.read_csv(config.AIRBUS_REVIEW_FILE, dtype={"tile_id": str, "date": str})
    marked_usable = review["metadata_usable"].astype("string").str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )
    full_coverage = pandas.to_numeric(review["airbus_tile_coverage_fraction"], errors="coerce").ge(0.999999)
    review["entered"] = review["metadata_usable"].notna()
    review["acceptable"] = marked_usable & full_coverage

    selection = {}
    for design, spec in designs.items():
        chosen = selected[selected["sample_component"] == spec["sample_component"]]
        selection[design] = {
            "tiles": chosen["tile_id"].nunique(),
            "acquisitions": len(chosen),
            "years": sorted(int(year) for year in chosen["season_year"].unique()),
            "first_date": chosen["acquisition_date"].min() if len(chosen) else "-",
            "last_date": chosen["acquisition_date"].max() if len(chosen) else "-",
        }
    all_years = sorted(set(config.SIX_SEASON_YEARS) | set(config.DECADE_YEARS))
    visual_check = selected["usable"].astype("string").str.strip().str.lower()

    # Tree detection results, checked against the selected imagery and against each other.
    detected = observations["detected"].astype(bool)
    tree_years = observations.assign(detected=detected).groupby("season_year").agg(
        tiles=("tile_id", "nunique"),
        observations=("tree_id", "size"),
        detected=("detected", "sum"),
    )
    selected_keys = pandas.MultiIndex.from_frame(selected[["tile_id", "season_year"]])
    observed_keys = pandas.MultiIndex.from_frame(observations[["tile_id", "season_year"]])
    observed_trees = pandas.MultiIndex.from_frame(observations[["tile_id", "tree_id"]])
    located_trees = pandas.MultiIndex.from_frame(locations[["tile_id", "tree_id"]])
    checks = [
        (f"Tree observations in a tile-season-year that is not in {config.SELECTED_IMAGERY_FILE.name}",
         int((~observed_keys.isin(selected_keys)).sum())),
        ("Tree observations with no matching tree location",
         int((~observed_trees.isin(located_trees)).sum())),
        ("Tree locations with no observations",
         int((~located_trees.isin(observed_trees)).sum())),
        ("Selected tile-season-years with no tree observations",
         int((~selected_keys.isin(observed_keys)).sum())),
    ]
    for description, count in checks:
        if count:
            print(f"Check: {description}: {count:,}")

    tile_component = selected.drop_duplicates("tile_id").set_index("tile_id")["sample_component"]
    trees_by_component = locations["tile_id"].map(tile_component).fillna("not in selected imagery").value_counts()

    # ---- Part 3: the PDF summary ----
    # Every table is a section: (heading, note, rows, column widths, columns to right-align).
    # The first row of each table is its header.
    cm = reportlab.lib.units.cm
    sections = []

    sections.append((
        "1. Headline numbers",
        "Read from the pipeline outputs on disk when this summary was written.",
        [
            ["Measure", "Value", "How it is counted"],
            ["Pleiades acquisition dates in the footprint layer", f"{footprints[config.DATE_FIELD].nunique():,}",
             "Distinct dates in the merged footprints file"],
            ["Dates screened against Landsat", f"{len(date_results):,}",
             "Dates in the study period and screening season with a footprint in the AOI (Stage 1, step 1)"],
            ["Dates with usable Landsat (candidate dates)", f"{len(candidate_dates):,}",
             "Dates with status OK"],
            ["1 km tiles screened", f"{tile_dates['tile_id'].nunique():,}",
             "Tiles that met the Pleiades coverage and agricultural thresholds on at least one candidate date"],
            ["Tile-date rows screened", f"{len(tile_dates):,}", "One tile on one candidate date"],
            ["Tile-dates passing the contrast screen", f"{int(tile_dates['tile_contrast_pass'].sum()):,}",
             "Evaluable, with enough of the tile above the primary C30 threshold"],
            ["Tile-season-years screened", f"{len(tile_seasons):,}", "One tile in one season year"],
            ["Tile-season-years passing", f"{int((tile_seasons['outcome'] == 'pass').sum()):,}",
             "At least one date that season passed"],
            [f"Eligible tiles: {designs['six_season']['pool_label'].lower()} design", f"{pool_sizes['six_season']:,}",
             "Pass in every season year of the design"],
            [f"Eligible tiles: {designs['decade']['pool_label']} design", f"{pool_sizes['decade']:,}",
             "Pass in every season year of the design"],
            [f"Tiles selected: {designs['six_season']['sample_label']}",
             f"{selection['six_season']['tiles']:,} of {config.SIX_SEASON_TILES:,}",
             "Selected tiles out of the target"],
            [f"Tiles selected: {designs['decade']['sample_label']}",
             f"{selection['decade']['tiles']:,} of {config.ADDITIONAL_DECADE_TILES:,}",
             "Selected tiles out of the target (six-season tiles excluded)"],
            ["Total tiles selected", f"{selection['six_season']['tiles'] + selection['decade']['tiles']:,}", ""],
            ["Season years included", f"{len(all_years)}", ", ".join(str(year) for year in all_years)],
            ["Pleiades acquisitions selected", f"{len(selected):,}", "One per selected tile-season-year"],
            ["Trees", f"{len(locations):,}", f"In {locations['tile_id'].nunique():,} tiles"],
            ["Tree-season observations", f"{len(observations):,}",
             f"{int(detected.sum()):,} detected ({detected.mean():.1%})"],
        ],
        [6.2 * cm, 2.6 * cm, 8.2 * cm],
        {1},
    ))

    date_rows = [["Season year", "Dates screened", "OK", "NO_SCENES", "NO_VALID_PIXELS"]]
    for year, counts in status_by_year.iterrows():
        date_rows.append([int(year), f"{int(counts.sum()):,}"] + [f"{int(v):,}" for v in counts])
    date_rows.append(["All", f"{int(status_by_year.to_numpy().sum()):,}"]
                     + [f"{int(v):,}" for v in status_by_year.sum()])
    sections.append((
        "2. Stage 1, step 1: date screening against Landsat",
        "OK dates have valid Landsat NDVI in agricultural land and become candidate dates. "
        "NO_SCENES: no Landsat scene was found. NO_VALID_PIXELS: every pixel was masked.",
        date_rows,
        [3 * cm, 3.5 * cm, 3 * cm, 3.5 * cm, 4 * cm],
        {0, 1, 2, 3, 4},
    ))

    outcome_rows = [["Season year", "Tiles screened", "Pass", "Fail", "Not evaluable"]]
    for year, counts in outcome_by_year.iterrows():
        outcome_rows.append([int(year), f"{int(counts.sum()):,}"] + [f"{int(v):,}" for v in counts])
    outcome_rows.append(["All", f"{int(outcome_by_year.to_numpy().sum()):,}"]
                        + [f"{int(v):,}" for v in outcome_by_year.sum()])
    sections.append((
        "3. Stage 1, step 2: tile-season-year outcomes",
        "Pass: at least one date that season passed the contrast screen. Fail: some date was evaluable "
        "but none passed. Not evaluable: no date had enough valid Landsat coverage.",
        outcome_rows,
        [3 * cm, 3.5 * cm, 3 * cm, 3.5 * cm, 4 * cm],
        {0, 1, 2, 3, 4},
    ))

    for design, spec in designs.items():
        grid = sensitivity[sensitivity["design"] == design].pivot(
            index="c30_threshold", columns="area_threshold", values="eligible_tiles"
        )
        sensitivity_rows = [["C30 threshold"] + [f"Area share >= {area:g}" for area in grid.columns]]
        for c30, counts in grid.iterrows():
            sensitivity_rows.append([f"C30 >= {c30:g}"] + [f"{int(v):,}" for v in counts])
        sections.append((
            f"4{'ab'[list(designs).index(design)]}. Sensitivity of eligible tiles: {spec['pool_label']} design",
            f"Eligible tiles for each C30 threshold and minimum share of the tile's agricultural pixels above "
            f"it. The main screen uses C30 >= {config.PRIMARY_C30_THRESHOLD:g} and a share of "
            f"{config.MIN_TILE_CONTRAST_METRIC_VALUE:g}.",
            sensitivity_rows,
            [4 * cm] + [13 * cm / len(grid.columns)] * len(grid.columns),
            set(range(1, len(grid.columns) + 1)),
        ))

    review_rows = [["Design", "Candidate rows", "Metadata entered", "Meeting selection rule",
                    "Tile-season-years with an acceptable acquisition"]]
    for design, spec in designs.items():
        design_review = review[review["design"] == design]
        acceptable = design_review[design_review["acceptable"]]
        review_rows.append([
            spec["pool_label"],
            f"{len(design_review):,}",
            f"{int(design_review['entered'].sum()):,}",
            f"{len(acceptable):,}",
            f"{len(acceptable.drop_duplicates(['tile_id', 'season_year'])):,}",
        ])
    sections.append((
        "5. Stage 2, step 1: Airbus metadata review",
        "Rows are the candidate acquisitions written for review. The selection rule is: marked usable, and "
        "the acquisition covers the whole 1 km tile (coverage >= 0.999999).",
        review_rows,
        [3 * cm, 2.8 * cm, 3 * cm, 3.4 * cm, 4.8 * cm],
        {1, 2, 3, 4},
    ))

    selection_rows = [["Sample", "Tiles selected", "Target", "Season years", "Acquisitions", "Acquisition dates"]]
    for design, spec in designs.items():
        info = selection[design]
        selection_rows.append([
            spec["sample_label"],
            f"{info['tiles']:,}",
            f"{spec['tiles']:,}",
            ", ".join(str(year) for year in info["years"]) or "-",
            f"{info['acquisitions']:,}",
            f"{info['first_date']} to {info['last_date']}" if info["acquisitions"] else "-",
        ])
    sections.append((
        "6. Stage 2, step 2: selected imagery",
        "One Airbus acquisition for each selected tile-season-year.",
        selection_rows,
        [3 * cm, 2.2 * cm, 1.8 * cm, 4.5 * cm, 2.3 * cm, 3.2 * cm],
        {1, 2, 4},
    ))

    components = [spec["sample_component"] for spec in designs.values()]
    per_year = pandas.crosstab(selected["season_year"], selected["sample_component"])
    per_year = per_year.reindex(columns=components, fill_value=0)
    per_year_rows = [["Season year"] + [spec["sample_label"] for spec in designs.values()] + ["Total"]]
    for year, counts in per_year.iterrows():
        per_year_rows.append([int(year)] + [f"{int(v):,}" for v in counts] + [f"{int(counts.sum()):,}"])
    sections.append((
        "7. Selected acquisitions by season year",
        "",
        per_year_rows,
        [4 * cm, 4.3 * cm, 4.3 * cm, 4.4 * cm],
        {0, 1, 2, 3},
    ))

    check_rows = [["Visual check of downloaded imagery (usable column)", "Acquisitions"]]
    check_rows.append(["Not yet recorded (blank)", f"{int(visual_check.isna().sum()):,}"])
    for value, count in visual_check.value_counts().items():
        check_rows.append([f"usable = {value}", f"{int(count):,}"])
    sections.append((
        "8. Visual check status",
        f"The usable, cloud, haze, shadow and other_issue columns of {config.SELECTED_IMAGERY_FILE.name} are "
        "filled in by hand after the imagery is downloaded.",
        check_rows,
        [12 * cm, 5 * cm],
        {1},
    ))

    tree_rows = [["Season year", "Tiles with observations", "Tree observations", "Detected", "Detection rate"]]
    for year, counts in tree_years.iterrows():
        tree_rows.append([
            int(year), f"{int(counts['tiles']):,}", f"{int(counts['observations']):,}",
            f"{int(counts['detected']):,}", f"{counts['detected'] / counts['observations']:.1%}",
        ])
    tree_rows.append([
        "All", f"{observations['tile_id'].nunique():,}", f"{len(observations):,}",
        f"{int(detected.sum()):,}", f"{detected.mean():.1%}",
    ])
    sections.append((
        "9. Tree detection results",
        f"{len(locations):,} trees in {locations['tile_id'].nunique():,} tiles: "
        + "; ".join(
            f"{spec['sample_label']} {int(trees_by_component.get(spec['sample_component'], 0)):,}"
            for spec in designs.values()
        )
        + f"; not in selected imagery {int(trees_by_component.get('not in selected imagery', 0)):,}.",
        tree_rows,
        [3 * cm, 4 * cm, 3.6 * cm, 3 * cm, 3.4 * cm],
        {0, 1, 2, 3, 4},
    ))

    sections.append((
        "10. Data checks",
        "Each count should normally be zero, except for selected tile-season-years where no trees were found.",
        [["Check", "Count"]] + [[description, f"{count:,}"] for description, count in checks],
        [13 * cm, 4 * cm],
        {1},
    ))

    sections.append((
        "11. Settings used",
        "From config.py.",
        [
            ["Setting", "Value"],
            ["Study period", f"{config.START_DATE} to {config.END_DATE} (end date excluded)"],
            ["Screening season",
             f"Months {config.SCREENING_SEASON_START_MONTH} to {config.SCREENING_SEASON_END_MONTH} "
             "(season year = year the season starts)"],
            ["Landsat scenes",
             f"{', '.join(config.LANDSAT_ID_PREFIXES)} scenes within +/- {config.LANDSAT_WINDOW_DAYS} days of "
             f"each Pleiades date; Tier 1 only: {config.REQUIRE_TIER1}"],
            ["Grid", f"{config.GRID_SIZE_M} m tiles in {config.GRID_CRS}; Landsat at {config.SCALE_M} m"],
            ["C30 neighbourhood radius", f"{config.BACKGROUND_RADIUS_M:g} m"],
            ["C30 thresholds recorded", ", ".join(f"{t:g}" for t in config.C30_SENSITIVITY_THRESHOLDS)],
            ["Primary C30 threshold", f"{config.PRIMARY_C30_THRESHOLD:g}"],
            ["Tile-date pass rule",
             f"C30 >= {config.PRIMARY_C30_THRESHOLD:g} on at least {config.MIN_TILE_CONTRAST_METRIC_VALUE:.0%} "
             "of the tile's agricultural pixels"],
            ["Minimum Pleiades coverage of a tile", f"{config.MIN_PLEIADES_COVERAGE:.0%}"],
            ["Minimum agricultural fraction of a tile", f"{config.MIN_AGRICULTURAL_FRACTION:.0%}"],
            ["Minimum valid Landsat coverage of a tile", f"{config.MIN_TILE_VALID_COVERAGE:.0%}"],
            ["Sensitivity: minimum shares tried",
             ", ".join(f"{t:.0%}" for t in config.TILE_CONTRAST_AREA_SENSITIVITY_THRESHOLDS)],
            ["Six-season design",
             f"Season years {', '.join(str(y) for y in config.SIX_SEASON_YEARS)}; "
             f"{config.SIX_SEASON_TILES} tiles; random seed {config.SIX_SEASON_SEED}"],
            ["2013/2023 design",
             f"Season years {', '.join(str(y) for y in config.DECADE_YEARS)}; "
             f"{config.ADDITIONAL_DECADE_TILES} additional tiles; random seed {config.DECADE_SEED}"],
        ],
        [6 * cm, 11 * cm],
        set(),
    ))

    # Inputs and outputs. Each entry: role, stage, description, file (a path, whose file name may be a
    # glob pattern), type, and, for items with no file to check on disk (file is None), the location and
    # status to show instead. Update this list if the pipeline gains or loses a file.
    summary_folder = config.SUMMARY_PDF_FILE.parent.relative_to(config.BASE_DIR).as_posix()
    manifest = [
        ("input", "Stage 0", "AOI shapefiles (zip)", None, "",
         f"{config.AOI_ZIP} (or --aoi-zip)", "supplied by you"),
        ("input", "Stage 0", "Dated Pleiades footprint shapefiles (zip)", None, "",
         f"{config.FOOTPRINTS_ZIP} (or --footprints-zip)", "supplied by you"),
        ("input", "Stage 1", "CLUM agricultural land raster", config.CLUM_RASTER, "", None, None),
        ("input", "Stage 1", "Landsat 8 Collection 2 Level-2 scenes", None, "",
         "Microsoft Planetary Computer STAC catalogue", "online (needs internet)"),
        ("input", "Stage 2", "Airbus Pleiades archive metadata", None, "",
         f"typed into {config.AIRBUS_REVIEW_FILE.name}", "manual step"),
        ("input", "After Stage 2", "Downloaded Pleiades imagery for the selected acquisitions", None, "",
         "not tracked by this pipeline", "supplied by you"),
        ("input", "Analysis", "Tree observations from tree detection", config.TREE_OBSERVATIONS_FILE, "", None, None),
        ("input", "Analysis", "Tree locations from tree detection", config.TREE_LOCATIONS_FILE, "", None, None),
        ("input", "All", "Settings", config.BASE_DIR / "config.py", "", None, None),
        ("output", "Stage 0", "Merged AOI polygon", config.AOI_FILE, "intermediate", None, None),
        ("output", "Stage 0", "All Pleiades footprints, with dates", config.FOOTPRINTS_FILE, "intermediate", None, None),
        ("output", "Stage 1.1", "Per-date Landsat status",
         config.EXPORT_DIR / config.DATE_SUMMARY_NAME.format(day="*"), "intermediate", None, None),
        ("output", "Stage 1.1", "Per-date 1 km cell results",
         config.EXPORT_DIR / config.DATE_CELLS_NAME.format(day="*"), "intermediate", None, None),
        ("output", "Stage 1.1", "Candidate dates", config.CANDIDATE_DATES_FILE, "intermediate", None, None),
        ("output", "Stage 1.2", "Tile-date screening table", config.TILE_DATE_FILE, "intermediate", None, None),
        ("output", "Stage 1.2", "Threshold sensitivity table", config.SENSITIVITY_FILE, "intermediate", None, None),
        ("output", "Stage 1.2", "Eligible tiles, six-season", config.SIX_SEASON_ELIGIBLE_FILE, "intermediate", None, None),
        ("output", "Stage 1.2", "Eligible tiles, 2013/2023", config.DECADE_ELIGIBLE_FILE, "intermediate", None, None),
        ("output", "Stage 1.2", "Random order, six-season", config.SIX_SEASON_RANDOM_ORDER_FILE, "intermediate", None, None),
        ("output", "Stage 1.2", "Random order, 2013/2023", config.DECADE_RANDOM_ORDER_FILE, "intermediate", None, None),
        ("output", "Stage 2.1", "Airbus metadata review table (filled in by hand)", config.AIRBUS_REVIEW_FILE,
         "intermediate", None, None),
        ("output", "Stage 2.2", "Selected imagery table", config.SELECTED_IMAGERY_FILE, "final", None, None),
        ("output", "Stage 2.2", "Selected imagery, spatial", config.SELECTED_IMAGERY_GPKG, "final", None, None),
        ("output", "Analysis", "Tree-by-season table", config.ANALYSIS_OBSERVATIONS_FILE, "final", None, None),
        ("output", "Analysis", "Tree locations and observations, spatial", config.ANALYSIS_SPATIAL_FILE,
         "final", None, None),
        ("output", "Analysis", "This summary", None, "final",
         f"{summary_folder}/\n{config.SUMMARY_PDF_FILE.name}", "this file"),
    ]
    input_rows = [["Input", "Used by", "Location", "Status"]]
    output_rows = [["Stage", "Product", "Location", "Type", "Status"]]
    for role, stage, description, file, kind, location, status in manifest:
        if file is not None:
            folder_text = file.parent.relative_to(config.BASE_DIR).as_posix()
            location = file.name if folder_text == "." else f"{folder_text}/\n{file.name}"
            matches = sorted(file.parent.glob(file.name))
            size = sum(match.stat().st_size for match in matches)
            size_text = f"{size / 1e6:,.1f} MB" if size >= 1e6 else f"{size / 1e3:,.1f} KB"
            if not matches:
                status = "MISSING"
            elif "*" in file.name:
                status = f"{len(matches):,} files, {size_text}"
            else:
                status = f"found, {size_text}"
        if role == "input":
            input_rows.append([description, stage, location, status])
        else:
            output_rows.append([stage, description, location, kind, status])
    sections.append((
        "12. Inputs required to run the analysis",
        "Paths are relative to the folder containing config.py.",
        input_rows,
        [5 * cm, 2.2 * cm, 5.6 * cm, 4.2 * cm],
        set(),
    ))
    sections.append((
        "13. Outputs, including intermediate products",
        "Final products are the ones used for analysis. Intermediate products are kept so that a stage can be "
        "checked or re-run without repeating the earlier ones.",
        output_rows,
        [1.8 * cm, 4.6 * cm, 5.6 * cm, 2 * cm, 3 * cm],
        set(),
    ))

    # Build the document: a title block followed by each section as a heading, a note and a table.
    styles = reportlab.lib.styles.getSampleStyleSheet()
    heading_style = reportlab.lib.styles.ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], spaceBefore=12, keepWithNext=True
    )
    note_style = reportlab.lib.styles.ParagraphStyle(
        "SectionNote", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=reportlab.lib.colors.HexColor("#555555"), spaceAfter=4, keepWithNext=True
    )
    left_style = reportlab.lib.styles.ParagraphStyle("CellLeft", parent=styles["Normal"], fontSize=8, leading=10)
    right_style = reportlab.lib.styles.ParagraphStyle(
        "CellRight", parent=left_style, alignment=reportlab.lib.enums.TA_RIGHT
    )
    table_style = reportlab.platypus.TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), reportlab.lib.colors.HexColor("#E8EDF3")),
        ("GRID", (0, 0), (-1, -1), 0.25, reportlab.lib.colors.HexColor("#B0B7C0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])

    story = [
        reportlab.platypus.Paragraph("Pleiades screening: result summary", styles["Title"]),
        reportlab.platypus.Paragraph(
            f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. "
            f"Results folder: {html.escape(str(config.OUTPUT_DIR), quote=False)}",
            styles["Normal"],
        ),
    ]
    for heading, note, rows, widths, right_columns in sections:
        story.append(reportlab.platypus.Paragraph(heading, heading_style))
        if note:
            story.append(reportlab.platypus.Paragraph(html.escape(note, quote=False), note_style))
        cells = []
        for row_number, row in enumerate(rows):
            cells.append([
                reportlab.platypus.Paragraph(
                    f"<b>{html.escape(str(value), quote=False)}</b>" if row_number == 0
                    else html.escape(str(value), quote=False).replace("\n", "<br/>"),
                    right_style if column in right_columns else left_style,
                )
                for column, value in enumerate(row)
            ])
        story.append(reportlab.platypus.Table(cells, colWidths=widths, style=table_style, repeatRows=1))

    # Page number in the footer of every page (a callback, so it has to be a function).
    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(reportlab.lib.pagesizes.A4[0] / 2, 1 * cm, f"Page {doc.page}")
        canvas.restoreState()

    document = reportlab.platypus.SimpleDocTemplate(
        str(config.SUMMARY_PDF_FILE),
        pagesize=reportlab.lib.pagesizes.A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title="Pleiades screening: result summary",
    )
    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Wrote {config.SUMMARY_PDF_FILE}")


if __name__ == "__main__":
    main()
