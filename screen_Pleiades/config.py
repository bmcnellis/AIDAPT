import re
from pathlib import Path

# Used in: stage0_prepare_inputs.py
# Used when merging the per-date footprint shapefiles. If a shapefile has no "date" column, 
# its date is taken from a YYYY-MM-DD folder in its path inside the zip 
# (e.g. 2020-11-05/footprints.shp). Group 2 is the date.
DATE_PATTERN = re.compile(r"(^|/)(\d{4}-\d{2}-\d{2})(/|$)")

# Used in: module_landsat_contrast.py
# Landsat assets read for every scene, named as in the Planetary Computer landsat-c2-l2 collection:
# "red" and "nir08" are the surface reflectance bands used for NDVI, "qa_pixel" holds the
# cloud/shadow/snow flags and "qa_radsat" the radiometric saturation flags (any set bit masks
# the pixel). Used in landsat_contrast.py: requested_landsat_item() skips scenes missing any of
# them, load_landsat_stack() loads them, and median_ndvi() reads them tile by tile.
REQUIRED_ASSETS = ("red", "nir08", "qa_pixel", "qa_radsat")
# Bit mask for the QA_PIXEL flags that make a pixel unusable: bits 0-5 (fill, dilated cloud,
# cirrus, cloud, cloud shadow, snow). Used in landsat_contrast.py by median_ndvi(), which keeps
# a pixel only if (qa_pixel & QA_BAD_BITS_0_TO_5) == 0. Missing qa_pixel values are set to this
# mask, so they count as flagged and are masked out.
QA_BAD_BITS_0_TO_5 = 0b111111

CLUM_GEOREF_SOURCES = "WORLDFILE,PAM,INTERNAL"

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "inputs"
EXPORT_DIR = BASE_DIR / "exports_geojson"
OUTPUT_DIR = BASE_DIR / "merged_results"

AOI_FILE = INPUT_DIR / "AOI_merged.gpkg"
AOI_LAYER = "aoi"
FOOTPRINTS_FILE = INPUT_DIR / "pleiades_footprints_merged.gpkg"
FOOTPRINTS_LAYER = "footprints"
DATE_FIELD = "date"
CLUM_RASTER = INPUT_DIR / "CLUM_agri.tif"
CLUM_VALUE = 1

START_DATE = "2013-04-10"
END_DATE = "2024-03-01"  # exclusive
SCREENING_SEASON_START_MONTH = 11
SCREENING_SEASON_END_MONTH = 2
LANDSAT_WINDOW_DAYS = 8

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
STAC_COLLECTION = "landsat-c2-l2"
LANDSAT_ID_PREFIXES = ("LC08_",)
REQUIRE_TIER1 = True
SR_SCALE = 0.0000275
SR_OFFSET = -0.2

GRID_CRS = "EPSG:3577"
SCALE_M = 30
GRID_SIZE_M = 1000
BACKGROUND_RADIUS_M = 30.0

MIN_PLEIADES_COVERAGE = 1.00
MIN_AGRICULTURAL_FRACTION = 0.90
MIN_TILE_VALID_COVERAGE = 0.70
PRIMARY_C30_THRESHOLD = 0.03
MIN_TILE_CONTRAST_METRIC_VALUE = 0.01
C30_SENSITIVITY_THRESHOLDS = (0.02, 0.03, 0.04)
TILE_CONTRAST_AREA_SENSITIVITY_THRESHOLDS = (0.01, 0.02, 0.03)

SIX_SEASON_YEARS = (2013, 2015, 2017, 2019, 2021, 2023)
DECADE_YEARS = (2013, 2023)
SIX_SEASON_TILES = 117
ADDITIONAL_DECADE_TILES = 349
SIX_SEASON_SEED = 42
DECADE_SEED = 43

IO_THREADS = 4
PROCESSING_TILE_SIZE_PX = 1024
ASSET_READ_RETRIES = 2
ASSET_READ_RETRY_SECONDS = 3
RESUME = True
START_INDEX = 0
END_INDEX = None
