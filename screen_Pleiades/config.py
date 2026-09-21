# Configuration for the Pleiades screening pipeline.
#
# Scripts, in run order (README.md describes what each one does):
#   stage0_prepare_inputs.py     merge the raw AOI and Pleiades footprint shapefiles into GeoPackages
#   stage1_1_process_dates.py    screen each Pleiades date against Landsat (calls module_landsat_contrast.py)
#   stage1_2_tile_screening.py   screen the 1 km tiles, build the eligible pools, give each a random order
#   stage2_1_prepare_imagery.py  order the candidate dates and write the Airbus metadata review table
#   stage2_2_select_imagery.py   choose one Airbus acquisition for each final tile-season-year
#
# Settings are grouped by topic. The "Used in:" line above a setting names the scripts that read it.

import pathlib
import re


# ======================================================================================
# 1. Folders
# ======================================================================================

# Folder containing this file. The folders below are relative to it.
BASE_DIR = pathlib.Path(__file__).resolve().parent

# Input data: the merged AOI and footprint GeoPackages and the CLUM raster (see section 2).
# Used in: stage0_prepare_inputs.py (default of its --output-dir option)
INPUT_DIR = BASE_DIR / "inputs"

# Per-date Landsat results: one summary JSON per date, plus a GeoJSON of 1 km cells for dates
# with usable Landsat.
# Used in: stage1_1_process_dates.py (writes), stage1_2_tile_screening.py (reads the GeoJSON cells)
EXPORT_DIR = BASE_DIR / "exports_geojson"

# Merged and selection results: candidate_dates.csv, the tile tables, the eligible pools and random
# orders, and the imagery_selection/ subfolder.
# Used in: stage1_1_process_dates.py, stage1_2_tile_screening.py, stage2_1_prepare_imagery.py,
# stage2_2_select_imagery.py
OUTPUT_DIR = BASE_DIR / "merged_results"


# ======================================================================================
# 2. Input files
# ======================================================================================

# Study area polygon (all AOI shapefiles unioned into one). File name and layer name are written
# by stage0_prepare_inputs.py, which hard-codes them, so change them here only together with that script.
# Used in: module_landsat_contrast.py (load_inputs)
AOI_FILE = INPUT_DIR / "AOI_merged.gpkg"
AOI_LAYER = "aoi"

# Pleiades footprints for every acquisition date, one row per footprint, with a date column.
# File name and layer name are written by stage0_prepare_inputs.py, which hard-codes them.
# Used in: module_landsat_contrast.py (load_inputs), stage1_2_tile_screening.py
FOOTPRINTS_FILE = INPUT_DIR / "pleiades_footprints_merged.gpkg"
FOOTPRINTS_LAYER = "footprints"

# Name of the footprint date column (YYYY-MM-DD). Keep this as "date": stage0_prepare_inputs.py
# writes that name and stage1_2_tile_screening.py also refers to "date" directly.
# Used in: module_landsat_contrast.py (load_inputs, geometry_for_date), stage1_1_process_dates.py,
# stage1_2_tile_screening.py
DATE_FIELD = "date"

# Used in: stage0_prepare_inputs.py
# Used when merging the per-date footprint shapefiles. If a shapefile has no "date" column,
# its date is taken from a YYYY-MM-DD folder in its path inside the zip
# (e.g. 2020-11-05/footprints.shp). Group 2 is the date.
DATE_PATTERN = re.compile(r"(^|/)(\d{4}-\d{2}-\d{2})(/|$)")

# Agricultural land raster (CLUM). Not produced by the pipeline: place it in INPUT_DIR yourself.
# Used in: module_landsat_contrast.py (load_inputs, load_clum_source), stage1_2_tile_screening.py
CLUM_RASTER = INPUT_DIR / "CLUM_agri.tif"

# Raster value that counts as agricultural land; every other value is not agricultural.
# Used in: module_landsat_contrast.py (clum_mask), stage1_2_tile_screening.py
CLUM_VALUE = 1

# GDAL_GEOREF_SOURCES used when opening CLUM_RASTER: where GDAL looks for the georeferencing, in
# priority order (a world file, then a PAM .aux.xml sidecar, then the georeferencing in the file itself).
# Used in: module_landsat_contrast.py (load_clum_source), stage1_2_tile_screening.py
CLUM_GEOREF_SOURCES = "WORLDFILE,PAM,INTERNAL"


# ======================================================================================
# 3. Study period and screening season
# ======================================================================================

# Only Pleiades dates from START_DATE up to (but not including) END_DATE are screened.
# Used in: stage1_1_process_dates.py
START_DATE = "2013-04-10"
END_DATE = "2024-03-01"  # exclusive

# Screening season: dates from SCREENING_SEASON_START_MONTH to SCREENING_SEASON_END_MONTH inclusive
# (11 and 2 = Nov-Feb; a season that spans new year is allowed). Each date gets a season_year, the
# year its season starts in, so Jan-Feb dates belong to the previous year's season.
# Used in: stage1_1_process_dates.py (which dates to screen, and their season_year),
# stage2_1_prepare_imagery.py (middle of the season, for ordering dates)
SCREENING_SEASON_START_MONTH = 11
SCREENING_SEASON_END_MONTH = 2


# ======================================================================================
# 4. Grid and coordinate system
# ======================================================================================

# Coordinate system for all processing: the Landsat grid, the 1 km tiles and the tile IDs
# (T_<x>_<y> is the tile's lower-left corner in this CRS). It is also the default of stage0's --crs
# option, the CRS the GeoPackages are stored in; every later step reprojects to GRID_CRS anyway.
# Used in: stage0_prepare_inputs.py, module_landsat_contrast.py, stage1_2_tile_screening.py
GRID_CRS = "EPSG:3577"

# Landsat pixel size in metres: the resolution Landsat is loaded and NDVI/C30 are calculated at.
# Used in: module_landsat_contrast.py
SCALE_M = 30

# Side length of the square tiles in metres, aligned to multiples of this value in GRID_CRS.
# Used in: module_landsat_contrast.py (summarize_cells), stage1_2_tile_screening.py
GRID_SIZE_M = 1000


# ======================================================================================
# 5. Landsat scenes and NDVI (stage1_1_process_dates.py, through module_landsat_contrast.py)
# ======================================================================================

# Landsat scenes within +/- this many days of a Pleiades date are used for that date. Their NDVI is
# combined by a per-pixel median.
# Used in: module_landsat_contrast.py (search_landsat)
LANDSAT_WINDOW_DAYS = 8

# STAC catalogue and collection the scenes are read from (Microsoft Planetary Computer,
# Landsat Collection 2 Level-2). Needs internet access.
# Used in: stage1_1_process_dates.py (STAC_URL, to open the catalogue),
# module_landsat_contrast.py (STAC_COLLECTION, in search_landsat)
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
STAC_COLLECTION = "landsat-c2-l2"

# Scene filters: scene IDs must start with one of these prefixes ("LC08_" = Landsat 8), and, if
# REQUIRE_TIER1 is True, be Tier 1 scenes.
# Used in: module_landsat_contrast.py (search_landsat)
LANDSAT_ID_PREFIXES = ("LC08_",)
REQUIRE_TIER1 = True

# Landsat assets read for every scene, named as in the Planetary Computer landsat-c2-l2 collection:
# "red" and "nir08" are the surface reflectance bands used for NDVI, "qa_pixel" holds the
# cloud/shadow/snow flags and "qa_radsat" the radiometric saturation flags (any set bit masks
# the pixel). Scenes missing any of them are skipped.
# Used in: module_landsat_contrast.py (search_landsat, compute_date, median_ndvi)
REQUIRED_ASSETS = ("red", "nir08", "qa_pixel", "qa_radsat")

# Conversion of the red and nir08 digital numbers to surface reflectance: DN * SR_SCALE + SR_OFFSET
# (the Collection 2 Level-2 scale factor and offset).
# Used in: module_landsat_contrast.py (median_ndvi)
SR_SCALE = 0.0000275
SR_OFFSET = -0.2

# Bit mask for the QA_PIXEL flags that make a pixel unusable: bits 0-5 (fill, dilated cloud,
# cirrus, cloud, cloud shadow, snow). A pixel is kept only if (qa_pixel & QA_BAD_BITS_0_TO_5) == 0.
# Missing qa_pixel values are set to this mask, so they count as flagged and are masked out.
# Used in: module_landsat_contrast.py (median_ndvi)
QA_BAD_BITS_0_TO_5 = 0b111111


# ======================================================================================
# 6. C30 contrast and tile screening thresholds
# ======================================================================================
# C30 is the local contrast of a pixel: its NDVI minus the median NDVI of the pixels within
# BACKGROUND_RADIUS_M of it. With 30 m pixels and a 30 m radius, that is the four pixels directly
# above, below, left and right of it.
#
# stage1_1_process_dates.py summarises C30 for every 1 km cell. stage1_2_tile_screening.py then
# passes a tile-date when ALL of these hold:
#   - the date's Pleiades footprint covers at least MIN_PLEIADES_COVERAGE of the tile
#   - at least MIN_AGRICULTURAL_FRACTION of the tile is agricultural (CLUM)
#   - Landsat NDVI is valid for at least MIN_TILE_VALID_COVERAGE of the tile's agricultural pixels
#   - at least MIN_TILE_CONTRAST_METRIC_VALUE of those agricultural pixels have C30 >= PRIMARY_C30_THRESHOLD

# Radius of the neighbourhood used for the local median in C30, in metres. (The "30" in the C30
# name and in the c30_* column names refers to this default radius.)
# Used in: module_landsat_contrast.py (local_contrast)
BACKGROUND_RADIUS_M = 30.0

# C30 values at which stage1_1_process_dates.py records the share of each tile's agricultural pixels
# with C30 at or above that value (columns named like c30_0p03_area_fraction for 0.03). These are
# also the C30 thresholds compared in the sensitivity table.
# Used in: module_landsat_contrast.py (summarize_cells), stage1_2_tile_screening.py
C30_SENSITIVITY_THRESHOLDS = (0.02, 0.03, 0.04)

# The C30 threshold used for the main screen. Must be one of C30_SENSITIVITY_THRESHOLDS.
# Used in: stage1_2_tile_screening.py
PRIMARY_C30_THRESHOLD = 0.03

# Minimum share of a tile's agricultural pixels whose C30 reaches PRIMARY_C30_THRESHOLD for the
# tile-date to pass the contrast screen.
# Used in: stage1_2_tile_screening.py
MIN_TILE_CONTRAST_METRIC_VALUE = 0.01

# Alternative values of that minimum share, compared in the sensitivity table (with each of
# C30_SENSITIVITY_THRESHOLDS).
# Used in: stage1_2_tile_screening.py
TILE_CONTRAST_AREA_SENSITIVITY_THRESHOLDS = (0.01, 0.02, 0.03)

# Minimum share of the tile covered by the date's Pleiades footprint (1.00 = fully covered).
# Used in: stage1_2_tile_screening.py
MIN_PLEIADES_COVERAGE = 1.00

# Minimum share of the tile that is agricultural: valid CLUM pixels equal to CLUM_VALUE, out of all
# valid CLUM pixels in the tile.
# Used in: stage1_2_tile_screening.py
MIN_AGRICULTURAL_FRACTION = 0.90

# Minimum share of the tile's agricultural pixels (inside the footprint) that must have valid Landsat
# NDVI for the tile-date to be evaluable. Tile-dates below this are "not evaluable" rather than failed.
# Used in: stage1_2_tile_screening.py
MIN_TILE_VALID_COVERAGE = 0.70


# ======================================================================================
# 7. Sampling designs
# ======================================================================================
# Two designs. A tile is eligible for a design if it passes the screen in every season year of that
# design (stage1_2_tile_screening.py).
#   six_season: the six season years in SIX_SEASON_YEARS
#   decade:     the two season years in DECADE_YEARS (2013 and 2023)
# A season year is the year the Nov-Feb season starts in (2013 = Nov 2013 to Feb 2014).

# Season years each design needs imagery for.
# Used in: stage1_2_tile_screening.py, stage2_1_prepare_imagery.py, stage2_2_select_imagery.py
SIX_SEASON_YEARS = (2013, 2015, 2017, 2019, 2021, 2023)
DECADE_YEARS = (2013, 2023)

# Number of tiles to select. The six-season tiles also have 2013 and 2023 imagery, so the
# 2013/2023 design totals SIX_SEASON_TILES + ADDITIONAL_DECADE_TILES tiles. The additional decade
# tiles exclude the six-season tiles.
# Used in: stage2_2_select_imagery.py
SIX_SEASON_TILES = 117
ADDITIONAL_DECADE_TILES = 349

# Seeds for the fixed random order of each design's eligible tiles. The order is reproducible only
# for the same eligible pool: changing any screening setting can change the pool, and with it the order.
# Used in: stage1_2_tile_screening.py
SIX_SEASON_SEED = 42
DECADE_SEED = 43


# ======================================================================================
# 8. Runtime and performance (stage1_1_process_dates.py, through module_landsat_contrast.py)
# ======================================================================================

# Number of threads used to read Landsat tiles.
# Used in: module_landsat_contrast.py (median_ndvi)
IO_THREADS = 4

# Size in pixels of the square blocks Landsat is loaded and processed in. Smaller uses less memory.
# Used in: module_landsat_contrast.py (compute_date, median_ndvi)
PROCESSING_TILE_SIZE_PX = 1024

# If loading a date's Landsat fails, retry up to ASSET_READ_RETRIES more times, waiting
# ASSET_READ_RETRY_SECONDS between attempts. Scenes are searched for again before each retry.
# Used in: module_landsat_contrast.py (compute_date)
ASSET_READ_RETRIES = 2
ASSET_READ_RETRY_SECONDS = 3

# Skip dates that already have a summary JSON in EXPORT_DIR (--force reprocesses them).
# Used in: stage1_1_process_dates.py
RESUME = True

# Process only dates START_INDEX up to (not including) END_INDEX of the sorted date list, for
# example to split a run into chunks. END_INDEX = None means to the end of the list.
# Used in: stage1_1_process_dates.py
START_INDEX = 0
END_INDEX = None
