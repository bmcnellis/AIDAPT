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

- `stage1_1_process_dates.py`: keep Nov-Feb Pleiades dates. For each date, find Landsat 8 within ±8 days, mask cloud/invalid pixels, calculate NDVI and C30, and keep dates with valid Landsat NDVI in agricultural land.
- `stage1_2_merge_results.py`: combine retained dates into `candidate_dates.csv`.

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
