# Pleiades screening

This pipeline screens Pleiades acquisition dates and 1 km tiles using Landsat NDVI contrast, draws a fixed random order of eligible tiles, and selects one Airbus Pleiades acquisition per tile-season-year to download for tree detection.

Every threshold, folder, file name and date range is set in `config.py`, which is organised by topic and says which script reads each setting. The paths shown in this README are the defaults from `config.py`.

## Pipeline at a glance

| Step | Script | What it does | Main outputs |
|---|---|---|---|
| Stage 0 | `stage0_prepare_inputs.py` | Merge the raw AOI and footprint shapefiles into GeoPackages | `inputs/AOI_merged.gpkg`, `inputs/pleiades_footprints_merged.gpkg` |
| Stage 1, step 1 | `stage1_1_process_dates.py` | Screen each Pleiades date against Landsat | `exports_geojson/*`, `merged_results/candidate_dates.csv` |
| Stage 1, step 2 | `stage1_2_tile_screening.py` | Screen 1 km tiles, build the eligible pools, give each a random order | `merged_results/tile_date_screening.gpkg`, `*_eligible.gpkg`, `*_random_order.gpkg`, `contrast_sensitivity_summary.csv` |
| Stage 2, step 1 | `stage2_1_prepare_imagery.py` | Order the candidate dates and write the Airbus metadata review table | `merged_results/imagery_selection/airbus_metadata_review.csv` |
| Manual review | | Fill in the Airbus metadata by hand | |
| Stage 2, step 2 | `stage2_2_select_imagery.py` | Choose one Airbus acquisition per final tile-season-year | `merged_results/imagery_selection/selected_imagery.csv` and `.gpkg` |
| Tree detection | | Detect trees in the downloaded imagery (outside this pipeline) | `merged_results/tree_detection/tree_observations.csv`, `tree_locations.gpkg` |
| Analysis | `analysis_output.py` | Collate the tree results and write a PDF summary of the whole workflow | `merged_results/analysis/analysis_tree_observations.csv`, `analysis_spatial.gpkg`, `pleiades_screening_summary.pdf` |

`module_landsat_contrast.py` holds the input loading, Landsat search, NDVI, C30 and cell-summary functions called by `stage1_1_process_dates.py`. It is not run directly.

Run the scripts in this order:

```
python stage0_prepare_inputs.py
python stage1_1_process_dates.py
python stage1_2_tile_screening.py
python stage2_1_prepare_imagery.py
# fill in merged_results/imagery_selection/airbus_metadata_review.csv by hand
python stage2_2_select_imagery.py
# download the imagery, run tree detection, and place its outputs in merged_results/tree_detection/
python analysis_output.py
```

## Requirements

- Python 3.10 or newer.
- `geopandas` 1.0 or newer (for `union_all`), `shapely` 2.x, `pandas`, `numpy`, `scipy`, `rasterio`, `affine`, `pystac`, `pystac-client`, `planetary-computer` and `odc-stac`. `analysis_output.py` also needs `reportlab`, to write the summary PDF. `odc-stac` loads Landsat as dask-backed xarray arrays, so `xarray` and `dask` must also be installed (`odc-stac` normally brings them in).
- Internet access for `stage1_1_process_dates.py`, which reads Landsat on demand from the Microsoft Planetary Computer.
- The agricultural land raster `inputs/CLUM_agri.tif`. The pipeline does not create it, so place it there yourself.

## Configuration (`config.py`)

| Section | What it controls |
|---|---|
| 1. Folders | `INPUT_DIR`, `EXPORT_DIR`, `OUTPUT_DIR` and its subfolders for the imagery selection, tree detection and analysis |
| 2. Input and output files | Every file the pipeline reads or writes, grouped by stage: the raw zips, AOI, footprint and CLUM files, the per-date file names, the tile tables, pools and random orders, the Airbus review and selected imagery, the tree detection inputs and the analysis outputs. Also the GeoPackage layer names shared between scripts, the date column, and how CLUM is read (`CLUM_VALUE`, `CLUM_GEOREF_SOURCES`) |
| 3. Study period and season | `START_DATE`, `END_DATE`, and the Nov-Feb screening season |
| 4. Grid and coordinate system | `GRID_CRS`, `SCALE_M` (Landsat pixel size), `GRID_SIZE_M` (tile size) |
| 5. Landsat scenes and NDVI | Scene search window and filters, required assets, reflectance scaling, QA mask |
| 6. C30 and tile screening thresholds | The contrast radius, the C30 thresholds, and the coverage and agricultural cut-offs |
| 7. Sampling designs | Season years, tile counts and random seeds for the two designs |
| 8. Runtime and performance | Threads, block size, retries, and the resume and slice options of `stage1_1_process_dates.py` |

`analysis_output.py` reports the main settings from sections 3 to 7 in its summary PDF.

## Stage 0: Setup

`stage0_prepare_inputs.py` merges the raw input files into two GeoPackages in `inputs/`, both reprojected to a common CRS (`GRID_CRS` in `config.py`, `EPSG:3577` by default):

- `AOI_merged.gpkg` (layer `aoi`): all shapefiles in `AOI.zip` unioned into a single valid AOI polygon.
- `pleiades_footprints_merged.gpkg` (layer `footprints`): all dated footprint shapefiles in `per_date_shapefiles.zip` stacked into one layer, with a `date` column (`YYYY-MM-DD`) and sorted by date. Each shapefile's date comes from its `date` column if it has one, otherwise from a `YYYY-MM-DD` folder in its path (matched by `DATE_PATTERN` in `config.py`). Empty shapefiles, and shapefiles with no date from either source, are skipped.

Options (all optional):

| Option | Default | Meaning |
|---|---|---|
| `--aoi-zip` | `AOI_ZIP` from `config.py` (`AOI.zip`, in the folder you run the script from) | Zip of AOI shapefiles |
| `--footprints-zip` | `FOOTPRINTS_ZIP` from `config.py` (`per_date_shapefiles.zip`, in the folder you run the script from) | Zip of dated footprint shapefiles |
| `--output-dir` | `INPUT_DIR` from `config.py` (`inputs/`) | Where the GeoPackages are written |
| `--crs` | `GRID_CRS` from `config.py` (`EPSG:3577`) | CRS the GeoPackages are stored in |

The GeoPackages are written with the file names and layer names in `AOI_FILE`, `AOI_LAYER`, `FOOTPRINTS_FILE` and `FOOTPRINTS_LAYER` in `config.py`, which later steps also read. If you pass a different `--crs`, later steps still reproject to `GRID_CRS`, so it only affects how the GeoPackages are stored.

## Stage 1: Footprint screening

### Step 1: Seasonal selection and Landsat processing

`stage1_1_process_dates.py` screens each Pleiades acquisition date against Landsat imagery, then lists the dates that passed.

Steps:

1. Keep the Pleiades dates from `START_DATE` (inclusive) to `END_DATE` (exclusive) that fall in the Nov-Feb screening season (`SCREENING_SEASON_START_MONTH` to `SCREENING_SEASON_END_MONTH`). Each date gets a `season_year`: the year the season starts, so Jan-Feb dates belong to the previous year's season.
2. For each date, find Landsat 8 scenes within ±8 days (`LANDSAT_WINDOW_DAYS`) that overlap that date's footprint, clipped to the AOI. Only Tier 1 scenes with all required assets are used.
3. Mask fill, cloud, cloud shadow, cirrus, snow and saturated pixels, then calculate NDVI at 30 m as the per-pixel median across the scenes. NDVI is kept only for agricultural pixels inside the footprint.
4. Calculate C30 for each pixel: its NDVI minus the median NDVI of the neighbouring pixels within 30 m (`BACKGROUND_RADIUS_M`), which at 30 m resolution is the four pixels directly above, below, left and right.
5. Summarise each 1 km grid cell. Both measures are shares of the cell's agricultural pixels inside the footprint: the share with valid Landsat NDVI, and the share with C30 at or above each threshold in `C30_SENSITIVITY_THRESHOLDS`. Pixels without valid NDVI count against the C30 share.
6. Give each date a status: `OK` if it has valid Landsat NDVI in agricultural land, `NO_SCENES` if no Landsat scene was found, or `NO_VALID_PIXELS` if every pixel was masked.
7. Merge the results: every `OK` date goes into `candidate_dates.csv`.

Inputs:

- `inputs/AOI_merged.gpkg` and `inputs/pleiades_footprints_merged.gpkg`: from Stage 0.
- `inputs/CLUM_agri.tif`: agricultural land raster. Pixels equal to `CLUM_VALUE` count as agricultural.
- Landsat 8 Collection 2 Level-2 (Tier 1) scenes, read on demand from the Microsoft Planetary Computer STAC catalogue, so internet access is required.

Outputs (folders set by `EXPORT_DIR` and `OUTPUT_DIR` in `config.py`):

- `exports_geojson/date_contrast_YYYYMMDD.json`: one per processed date, with `date`, `season_year`, `status`, `message` and `landsat_observations` (number of Landsat scenes found).
- `exports_geojson/date_spatial_cells_YYYYMMDD.geojson`: only for `OK` dates. One row per 1 km grid cell, with `tile_id` (`T_<x>_<y>`, the cell's lower-left corner in `GRID_CRS`), `valid_coverage_fraction`, and one `c30_<threshold>_area_fraction` column per threshold (e.g. `c30_0p03_area_fraction`). Saved in `EPSG:4326`. Cells with no agricultural pixels are left out.
- `merged_results/candidate_dates.csv`: `date` and `season_year` for every `OK` date, sorted by date.

Running it:

```
python stage1_1_process_dates.py [--date YYYY-MM-DD] [--force]
```

- Dates that already have a summary JSON are skipped (`RESUME` in `config.py`). `--force` reprocesses them.
- `--date YYYY-MM-DD` processes a single date, ignoring the season, date-range and index settings. Use it only for dates inside the screening season: a date outside it is given no `season_year`, which `stage1_2_tile_screening.py` cannot handle if that date is `OK`.
- `START_INDEX` and `END_INDEX` in `config.py` limit the run to a slice of the date list, for example to split it into chunks.
- Dates that raise an error are listed at the end and get no JSON, so the next run retries them.
- `candidate_dates.csv` is rebuilt at the end of every run from all the JSON files in `exports_geojson/`, so it stays partial until every date has been processed.

### Step 2: 1 km tile screening, eligible pools and random order

`stage1_2_tile_screening.py` takes the candidate dates from Step 1 and runs four steps in one go. It takes no options, reads `candidate_dates.csv`, and overwrites its outputs on every run. Each step writes its output before the next starts.

1. **Tile-date table** (`tile_date_screening.gpkg`, layer `tile_dates`). For every candidate date, take the 1 km grid cells that touch that date's footprints and add:
   - `pleiades_coverage_fraction`: the share of the tile covered by the date's footprints.
   - `agricultural_fraction`: the share of valid CLUM pixels in the tile equal to `CLUM_VALUE`.
   - `tile_valid_coverage_fraction` and the `c30_*_area_fraction` columns, joined from the Step 1 GeoJSON.

   Tiles below `MIN_PLEIADES_COVERAGE` or `MIN_AGRICULTURAL_FRACTION` are dropped. The rest get two flags:
   - `tile_contrast_evaluable`: `tile_valid_coverage_fraction` is at least `MIN_TILE_VALID_COVERAGE` and the primary C30 value exists.
   - `tile_contrast_pass`: evaluable, and the area fraction for `PRIMARY_C30_THRESHOLD` is at least `MIN_TILE_CONTRAST_METRIC_VALUE`.
2. **Sensitivity** (`contrast_sensitivity_summary.csv`). For each design and every combination of C30 threshold (`C30_SENSITIVITY_THRESHOLDS`) and area threshold (`TILE_CONTRAST_AREA_SENSITIVITY_THRESHOLDS`), count the tiles that pass in every season year of the design. A tile passes a season year if any of its dates is evaluable and reaches the area threshold. Columns: `design`, `c30_threshold`, `area_threshold`, `eligible_tiles`.
3. **Eligible pools** (`six_season_eligible.gpkg`, `decade_eligible.gpkg`, layer `tiles`). Each tile-season-year is `pass` if any date that season passed, `fail` if some date was evaluable but none passed, and `not_evaluable` otherwise. A tile is eligible for a design if it passes in every season year of that design (`SIX_SEASON_YEARS` for the six-season design, `DECADE_YEARS` for the 2013/2023 design). This step uses the primary threshold (`tile_contrast_pass`).
4. **Random order** (`six_season_random_order.gpkg`, `decade_random_order.gpkg`, layer `tiles`). Each pool is sorted by `tile_id`, shuffled with a fixed seed (`SIX_SEASON_SEED`, `DECADE_SEED`), and numbered in a `random_order` column. The order is reproducible only for the same pool: changing a screening setting can change the pool, and with it the order.

## Stage 2: Imagery selection

### Step 1: Prepare the review table

`stage2_1_prepare_imagery.py` reads `tile_date_screening.gpkg` and the two `*_random_order.gpkg` files. For each design it lists the passing dates (`tile_contrast_pass`) of every tile in the random-order pool, for that design's season years. Within each tile-season-year the dates are ordered by distance from the middle of the Nov-Feb window (`days_from_midpoint`), so `date_order` 1 is the preferred date.

It writes `merged_results/imagery_selection/airbus_metadata_review.csv` with these columns:

- Filled in by the script: `design`, `tile_order` (the tile's `random_order`), `tile_id`, `season_year`, `date`, `date_order`, `days_from_midpoint`.
- Blank, for you to fill in from the Airbus catalogue: `airbus_acquisition_id`, `airbus_archive_identifier`, `airbus_processing_level`, `airbus_reported_cloud_cover`, `airbus_tile_coverage_fraction`, `airbus_quicklook`, `metadata_usable`, `notes`.

> **Warning:** running this script again overwrites `airbus_metadata_review.csv`, including anything you have filled in. Copy the file first if you need to regenerate it.

### Manual step: fill in the review table

For each row, look up the Pleiades acquisition in the Airbus archive and record its metadata.

- `airbus_tile_coverage_fraction`: the share of the 1 km tile covered by that one acquisition.
- `metadata_usable`: `true`, `yes`, `y` or `1` (any capitalisation) if the acquisition is usable. Any other value, including blank, means the row is ignored.

Work down each design in `tile_order`, because Step 2 takes the first tiles in that order. You do not need to review `decade` rows for tiles that end up in the six-season sample.

### Step 2: Select the imagery

`stage2_2_select_imagery.py` reads the filled-in review table and, for each tile-season-year, keeps the best-ordered row (lowest `date_order`) that is marked usable and whose acquisition covers the whole tile (`airbus_tile_coverage_fraction` of at least 0.999999). It then takes:

- **six-season sample:** the first `SIX_SEASON_TILES` tiles, in random order, with a usable acquisition in every season year of `SIX_SEASON_YEARS`.
- **additional 2013/2023 sample:** the first `ADDITIONAL_DECADE_TILES` tiles, in random order, with a usable acquisition in both `DECADE_YEARS`, skipping tiles already in the six-season sample.

If either design has too few reviewed tiles it stops with "Not enough metadata-reviewed tiles yet". Fill in more rows and run it again.

Outputs in `merged_results/imagery_selection/`:

- `selected_imagery.csv`: one row per selected acquisition, with `sample_component` (`six_season` or `additional_2013_2023`), `tile_id`, `season_year`, `acquisition_date`, `date_order`, `days_from_midpoint`, the six `airbus_*` metadata columns, and blank columns (`cloud`, `haze`, `shadow`, `other_issue`, `usable`, `notes`) for the visual check after download.
- `selected_imagery.gpkg`: layer `tiles` (the selected tiles) and layer `tile_seasons` (one row per selected acquisition, with the tile geometry).

> **Note:** Stage 1 uses the Pleiades footprint data for screening. A tile can pass that check even if no single Airbus acquisition covers the whole tile, so full individual-acquisition coverage is checked again in Stage 2.

After download, visually check:

- full raster coverage
- cloud, haze, shadow
- other obvious image problems

Keep `tile_id` and `season_year` throughout so imagery can be linked back to tree detections.

## Folder layout

```
inputs/                          INPUT_DIR
  AOI_merged.gpkg                  Stage 0
  pleiades_footprints_merged.gpkg  Stage 0
  CLUM_agri.tif                    supplied by you
exports_geojson/                 EXPORT_DIR
  date_contrast_YYYYMMDD.json      Stage 1, step 1
  date_spatial_cells_YYYYMMDD.geojson
merged_results/                  OUTPUT_DIR
  candidate_dates.csv              Stage 1, step 1
  tile_date_screening.gpkg         Stage 1, step 2
  contrast_sensitivity_summary.csv
  six_season_eligible.gpkg
  decade_eligible.gpkg
  six_season_random_order.gpkg
  decade_random_order.gpkg
  imagery_selection/
    airbus_metadata_review.csv     Stage 2, step 1 (then filled in by hand)
    selected_imagery.csv           Stage 2, step 2
    selected_imagery.gpkg
  tree_detection/                  from tree detection (outside this pipeline)
    tree_observations.csv
    tree_locations.gpkg
  analysis/                        analysis_output.py
    analysis_tree_observations.csv
    analysis_spatial.gpkg
    pleiades_screening_summary.pdf
```

## Tree detection outputs

Tree detection is done outside this pipeline, on the downloaded imagery. `analysis_output.py` expects its results at `TREE_OBSERVATIONS_FILE` and `TREE_LOCATIONS_FILE` in `config.py` (by default in `merged_results/tree_detection/`):

- `tree_locations.gpkg` (layer `trees`): one stable `tree_id` and location for each tree, with `tile_id`.
- `tree_observations.csv`: one row per tree per season-year, with columns `tile_id`, `season_year`, `tree_id`, `detected`.

## Analysis

`analysis_output.py` collates the final results. It takes no options and overwrites its outputs on every run. Run it after every earlier stage and after the tree detection results are in place. If any file it reads is missing, it stops at the start and lists them all.

It reads the tree detection outputs above, plus the outputs of every earlier stage (for the summary), and writes to `merged_results/analysis/`:

- `analysis_tree_observations.csv`: the tree observations (`tile_id`, `season_year`, `tree_id`, `detected`), sorted by `tile_id`, `tree_id`, `season_year`, followed by `sample_component` and `acquisition_date` taken from `selected_imagery.csv`.
- `analysis_spatial.gpkg`: layer `tree_locations` (every tree location) and layer `tree_observations` (each observation, with the same columns as the CSV, joined to its tree location; observations with no matching location are left out).
- `pleiades_screening_summary.pdf`: a summary of the whole workflow (see below).

`tile_id` and `season_year` remain the link between a tree observation and its imagery: together they identify exactly one selected acquisition, and the two added columns only repeat what `selected_imagery.csv` holds for that pair. Every observation appears once. An observation whose tile-season-year has no selected imagery keeps blank values in both columns, and is counted in the data checks below. If `selected_imagery.csv` ever listed one tile-season-year twice, the script stops with an error instead of duplicating observations.

The PDF contains:

1. Headline numbers: dates screened, tiles screened, tile-season-years passing, eligible tiles, tiles and acquisitions selected, season years included, and tree counts.
2. Date screening by season year (Stage 1, step 1) and tile-season-year outcomes (Stage 1, step 2).
3. Threshold sensitivity tables for each design.
4. The Airbus metadata review and the selected imagery: tiles selected against the targets, acquisitions by season year, and the status of the visual check.
5. Tree detection results by season year.
6. Data checks, each normally zero: tree observations outside the selected tile-season-years, observations with no tree location, tree locations with no observations, and selected tile-season-years with no tree observations. Non-zero counts are also printed when the script runs.
7. The main settings from `config.py`.
8. Every input needed to run the analysis and every output, including intermediate products, with its location and whether it was found on disk.

The numbers come from the files on disk when the script runs. The input and output lists are written in the script itself (the `manifest` list in `analysis_output.py`), so update them if the pipeline gains or loses a file.
