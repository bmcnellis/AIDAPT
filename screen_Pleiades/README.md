# Pleiades screening

Two main stages:

1. **Stage 1:** use Pleiades footprints and Landsat to screen and select tiles.
2. **Stage 2:** choose the actual Pleiades acquisition to download.

Main settings are in `config.py`.

### Stage 0: Setup

`stage0_prepare_inputs.py` merges the raw input files into two GeoPackages in `inputs/`, both reprojected to a common CRS (`EPSG:3577` by default):

- `AOI_merged.gpkg` (layer `aoi`): all shapefiles in `AOI.zip` unioned into a single valid AOI polygon.
- `pleiades_footprints_merged.gpkg` (layer `footprints`): all dated footprint shapefiles in `per_date_shapefiles.zip` stacked into one layer, with a `date` column (`YYYY-MM-DD`) and sorted by date. Each shapefile's date comes from its `date` column if it has one, otherwise from a `YYYY-MM-DD` folder in its path (matched by `DATE_PATTERN` in `config.py`). Empty shapefiles, and shapefiles with no date from either source, are skipped.

## Stage 1: Footprint screening

### 1. Seasonal selection and Landsat processing

`stage1_1_process_dates.py` screens each Pleiades acquisition date against Landsat imagery, then lists the dates that passed.

Steps:

1. Keep the Pleiades dates from `START_DATE` (inclusive) to `END_DATE` (exclusive) that fall in the Nov-Feb screening season (`SCREENING_SEASON_START_MONTH` to `SCREENING_SEASON_END_MONTH`). Each date gets a `season_year`: the year the season starts, so Jan-Feb dates belong to the previous year's season.
2. For each date, find Landsat 8 scenes within ±8 days (`LANDSAT_WINDOW_DAYS`) that overlap that date's footprint, clipped to the AOI.
3. Mask fill, cloud, cloud shadow, cirrus, snow and saturated pixels, then calculate NDVI at 30 m as the per-pixel median across the scenes. NDVI is kept only for agricultural pixels inside the footprint.
4. Calculate C30 for each pixel: its NDVI minus the median NDVI of the neighbouring pixels within 30 m.
5. Summarise each 1 km grid cell: the share of its agricultural pixels (inside the footprint) with valid Landsat NDVI, and the share with C30 at or above each threshold in `C30_SENSITIVITY_THRESHOLDS`.
6. Give each date a status: `OK` if it has valid Landsat NDVI in agricultural land, `NO_SCENES` if no Landsat scene was found, or `NO_VALID_PIXELS` if every pixel was masked.
7. Merge the results: every `OK` date goes into `candidate_dates.csv`.

Inputs:

- `inputs/AOI_merged.gpkg` and `inputs/pleiades_footprints_merged.gpkg`: from the Setup step.
- `inputs/CLUM_agri.tif`: agricultural land raster. Pixels equal to `CLUM_VALUE` count as agricultural.
- Landsat 8 Collection 2 Level-2 (Tier 1) scenes, read on demand from the Microsoft Planetary Computer STAC catalogue, so internet access is required.

Outputs (folders set by `EXPORT_DIR` and `OUTPUT_DIR` in `config.py`):

- `exports_geojson/date_contrast_YYYYMMDD.json`: one per processed date, with `date`, `season_year`, `status`, `message` and `landsat_observations` (number of Landsat scenes found).
- `exports_geojson/date_spatial_cells_YYYYMMDD.geojson`: only for `OK` dates. One row per 1 km grid cell, with `tile_id` (`T_<x>_<y>`, the cell's lower-left corner in `EPSG:3577`), `valid_coverage_fraction`, and one `c30_<threshold>_area_fraction` column per threshold (e.g. `c30_0p03_area_fraction`). Saved in `EPSG:4326`. Cells with no agricultural pixels are left out.
- `merged_results/candidate_dates.csv`: `date` and `season_year` for every `OK` date, sorted by date.

Running it:

- Dates that already have a summary JSON are skipped (`RESUME` in `config.py`). `--force` reprocesses them.
- `--date YYYY-MM-DD` processes a single date, ignoring the season, date-range and index settings.
- `START_INDEX` and `END_INDEX` in `config.py` limit the run to a slice of the date list, for example to split it into chunks.
- Dates that raise an error are listed at the end and get no JSON, so the next run retries them.
- `candidate_dates.csv` is rebuilt at the end of every run from all the JSON files in `exports_geojson/`, so it stays partial until every date has been processed.

### 2. 1 km tile-date screening

- `stage1_3_build_tiles.py`: create 1 km tiles and apply:
  - Pleiades footprint coverage
  - agricultural land
  - Landsat coverage
  - C30 threshold
- `stage1_4_sensitivity.py`: repeat the contrast screen using the alternative C30 and area thresholds.

### 3. Tile-season-year eligibility

- `stage1_5_common_coverage.py`: summarise each tile-season-year as pass, fail or not evaluable. Also identify tiles eligible for:
  - six-season design
  - 2013/2023 design

### 4. Random sampling

- `stage1_6_sample_tiles.py`: give eligible tiles a fixed random order. Keep the same order if extra/replacement tiles are needed later.

## Stage 2: Imagery selection

- `stage2_1_prepare_imagery.py`: for each selected tile-season-year, order the passing Pleiades dates by distance from the middle of the Nov-Feb window. Create the Airbus metadata review table.
- `stage2_2_select_imagery.py`: choose one usable Airbus acquisition per tile-season-year. Check that the individual acquisition covers the full 1 km tile before selection.

Outputs:

- `selected_imagery.csv`
- `selected_imagery.gpkg`

> **Note:** Stage 1 uses the Pleiades footprint data for screening. A tile can pass that check even if no single Airbus acquisition covers the whole tile, so full individual-acquisition coverage is checked again in Stage 2.

After download, visually check:

- full raster coverage
- cloud, haze, shadow
- other obvious image problems

Keep `tile_id` and `season_year` throughout so imagery can be linked back to tree detections.

## Tree outputs

- `tree_locations.gpkg`: one stable `tree_id` and location for each tree.
- `tree_observations.csv`: one row per tree per season-year, with columns `tile_id`, `season_year`, `tree_id`, `detected`.

## Analysis

`analysis_output.py` creates:

- `analysis_tree_observations.csv`
- `analysis_spatial.gpkg`
