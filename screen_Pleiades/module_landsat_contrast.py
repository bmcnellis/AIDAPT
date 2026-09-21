# Landsat NDVI and local contrast (C30) calculations for the Pleiades screening pipeline.
#
# Called from stage1_1_process_dates.py:
#   load_inputs, geometry_for_date, compute_date, summarize_cells
# Called only from within this module:
#   search_landsat, load_clum_source, clum_mask, median_ndvi, nanmedian, local_contrast
#
# Settings (dates, thresholds, file paths, ...) come from config.py.

import dataclasses
import datetime
import functools
import math
import pathlib
import re
import time
import warnings

import affine
import geopandas
import numpy
import odc.stac
import pandas
import pystac
import rasterio
import rasterio.features
import rasterio.transform
import rasterio.warp
import scipy.ndimage
import shapely
import shapely.geometry
import shapely.geometry.base

import config

# Functions used from other packages (called below with their full module path, e.g. shapely.make_valid).
#   dataclasses:            dataclass
#   datetime:               date.fromisoformat, timedelta
#   functools:              lru_cache
#   geopandas:              GeoDataFrame, GeoSeries, read_file
#   math:                   ceil, floor
#   numpy:                  abs, arange, asarray, count_nonzero, divide, full, isfinite, median,
#                           mgrid, nan_to_num, nanmedian, zeros
#   odc.stac:               load
#   pandas:                 to_datetime
#   pathlib:                Path
#   rasterio:               Env, open
#   rasterio.features:      geometry_mask, rasterize
#   rasterio.transform:     from_origin
#   rasterio.warp:          Resampling, reproject
#   re:                     search
#   scipy.ndimage:          generic_filter
#   shapely:                make_valid
#   shapely.geometry:       box, mapping, shape
#   time:                   sleep
#   warnings:               catch_warnings, simplefilter
# Used only as type annotations: affine.Affine, pystac.Item, shapely.geometry.base.BaseGeometry


@dataclasses.dataclass
class Inputs:
    aoi: shapely.geometry.base.BaseGeometry
    footprints: geopandas.GeoDataFrame


@dataclasses.dataclass
class DateResult:
    date: str
    status: str
    message: str
    scene_items: list[pystac.Item]
    ndvi: numpy.ndarray | None = None
    contrast: numpy.ndarray | None = None
    transform: affine.Affine | None = None

    @property
    def scene_count(self):
        return len(self.scene_items)


# ---- Inputs ----


def load_inputs():
    for path in (config.AOI_FILE, config.FOOTPRINTS_FILE, config.CLUM_RASTER):
        if not pathlib.Path(path).exists():
            raise FileNotFoundError(path)
    aoi = geopandas.read_file(config.AOI_FILE, layer=config.AOI_LAYER).to_crs(config.GRID_CRS)
    footprints = geopandas.read_file(
        config.FOOTPRINTS_FILE, layer=config.FOOTPRINTS_LAYER
    ).to_crs(config.GRID_CRS)
    footprints[config.DATE_FIELD] = pandas.to_datetime(
        footprints[config.DATE_FIELD]
    ).dt.strftime("%Y-%m-%d")
    aoi_geom = shapely.make_valid(aoi.geometry.union_all())
    footprints = footprints[footprints.geometry.notna()].copy()
    footprints["geometry"] = footprints.geometry.map(shapely.make_valid)
    footprints = footprints[footprints.intersects(aoi_geom)].copy()
    return Inputs(aoi_geom, footprints)


def geometry_for_date(inputs, date_string):
    rows = inputs.footprints[inputs.footprints[config.DATE_FIELD] == date_string]
    return shapely.make_valid(rows.geometry.union_all().intersection(inputs.aoi))


# ---- Landsat scene search ----


# Called twice in compute_date(): for the first attempt and again before each retry.
def search_landsat(catalog, date_string, geom):
    center = datetime.date.fromisoformat(date_string)
    start = center - datetime.timedelta(days=config.LANDSAT_WINDOW_DAYS)
    end = center + datetime.timedelta(days=config.LANDSAT_WINDOW_DAYS)
    geom_wgs84 = geopandas.GeoSeries([geom], crs=config.GRID_CRS).to_crs("EPSG:4326").iloc[0]
    search = catalog.search(
        collections=[config.STAC_COLLECTION],
        bbox=tuple(float(v) for v in geom_wgs84.bounds),
        datetime=f"{start.isoformat()}/{end.isoformat()}",
    )
    items = []
    for item in search.items():
        # Keep only the requested scenes: ID prefix, Tier 1 (if required) and all required assets.
        if not item.id.startswith(tuple(config.LANDSAT_ID_PREFIXES)):
            continue
        if config.REQUIRE_TIER1:
            category = item.properties.get("landsat:collection_category")
            if category is not None and str(category).upper() != "T1":
                continue
            if category is None and re.search(r"(?:^|_)T1(?:_|$)", item.id, re.IGNORECASE) is None:
                continue
        if not all(name in item.assets for name in config.REQUIRED_ASSETS):
            continue
        if item.geometry is not None and not shapely.make_valid(
            shapely.geometry.shape(item.geometry)
        ).intersects(geom_wgs84):
            continue
        items.append(item)
    return sorted(items, key=lambda x: (x.datetime.timestamp() if x.datetime else float("-inf"), x.id))


# ---- CLUM agricultural mask ----


# Cached so the CLUM raster is read from disk once per run, not once per date.
@functools.lru_cache(maxsize=1)
def load_clum_source():
    with rasterio.Env(GDAL_GEOREF_SOURCES=config.CLUM_GEOREF_SOURCES):
        with rasterio.open(config.CLUM_RASTER) as src:
            return src.read(1), src.transform, src.crs, src.nodata


# Called from both median_ndvi() and summarize_cells().
def clum_mask(shape_, transform):
    source, src_transform, src_crs, src_nodata = load_clum_source()
    destination = numpy.zeros(shape_, dtype=numpy.float32)
    rasterio.warp.reproject(
        source=source,
        destination=destination,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=src_nodata,
        dst_transform=transform,
        dst_crs=config.GRID_CRS,
        dst_nodata=0,
        resampling=rasterio.warp.Resampling.nearest,
    )
    return destination == float(config.CLUM_VALUE)


# ---- NDVI and local contrast ----


# Per-pixel median NDVI across the scenes, kept only for agricultural pixels inside the footprint.
def median_ndvi(ds, geom, transform):
    height = int(ds.sizes["y"])
    width = int(ds.sizes["x"])
    shape_ = (height, width)
    spatial = rasterio.features.geometry_mask(
        [shapely.geometry.mapping(geom)],
        out_shape=shape_,
        transform=transform,
        invert=True,
        all_touched=False,
    ) & clum_mask(shape_, transform)
    ndvi = numpy.full(shape_, numpy.nan, dtype=numpy.float32)

    size = config.PROCESSING_TILE_SIZE_PX
    for y0 in range(0, height, size):
        for x0 in range(0, width, size):
            y1 = min(y0 + size, height)
            x1 = min(x0 + size, width)
            spatial_tile = spatial[y0:y1, x0:x1]
            if not spatial_tile.any():
                continue

            tile = ds[list(config.REQUIRED_ASSETS)].isel(
                y=slice(y0, y1), x=slice(x0, x1)
            ).compute(scheduler="threads", num_workers=config.IO_THREADS)

            # Surface reflectance from the digital numbers; NDVI = (NIR - red) / (NIR + red).
            red = tile["red"].values.astype(numpy.float32) * config.SR_SCALE + config.SR_OFFSET
            nir = tile["nir08"].values.astype(numpy.float32) * config.SR_SCALE + config.SR_OFFSET
            denominator = nir + red

            # Missing QA values count as flagged / saturated, so those pixels are masked out.
            qa_pixel = numpy.nan_to_num(tile["qa_pixel"].values, nan=config.QA_BAD_BITS_0_TO_5).astype(numpy.uint32)
            qa_radsat = numpy.nan_to_num(tile["qa_radsat"].values, nan=1).astype(numpy.uint32)
            valid = (
                ((qa_pixel & config.QA_BAD_BITS_0_TO_5) == 0)
                & (qa_radsat == 0)
                & numpy.isfinite(denominator)  # also excludes NaN or infinite red/nir
                & (numpy.abs(denominator) > 1e-12)
                & spatial_tile[None, :, :]
            )

            stack = numpy.full(red.shape, numpy.nan, dtype=numpy.float32)
            numpy.divide(nir - red, denominator, out=stack, where=valid)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                median = numpy.nanmedian(stack, axis=0).astype(numpy.float32)
            median[~spatial_tile] = numpy.nan
            ndvi[y0:y1, x0:x1] = median

    ndvi[~spatial] = numpy.nan
    return ndvi


# scipy.ndimage.generic_filter needs a callable, so this stays a function. It is used instead of
# numpy.nanmedian because that is much slower on windows this small.
def nanmedian(values):
    values = values[numpy.isfinite(values)]
    return numpy.median(values) if values.size else numpy.nan


def local_contrast(ndvi):
    # Circular neighbourhood of radius BACKGROUND_RADIUS_M around each pixel, excluding the pixel itself.
    radius_px = config.BACKGROUND_RADIUS_M / config.SCALE_M
    half = int(math.ceil(radius_px))
    yy, xx = numpy.mgrid[-half : half + 1, -half : half + 1]
    footprint = (xx * xx + yy * yy) <= radius_px * radius_px + 1e-9
    footprint[half, half] = False

    local_median = scipy.ndimage.generic_filter(
        ndvi,
        nanmedian,
        footprint=footprint,
        mode="constant",
        cval=numpy.nan,
        output=numpy.float32,
    )
    contrast = (ndvi - local_median).astype(numpy.float32)
    contrast[~numpy.isfinite(ndvi)] = numpy.nan
    return contrast


# ---- Per-cell summaries and the per-date driver ----


# One row per 1 km cell: valid Landsat coverage, and the share of the cell's agricultural pixels
# (inside the footprint) with C30 at or above each threshold in config.C30_SENSITIVITY_THRESHOLDS.
def summarize_cells(date_string, geom, ndvi, contrast, transform):
    # Grid cells aligned to multiples of GRID_SIZE_M, clipped to the footprint geometry.
    size = config.GRID_SIZE_M
    geom_minx, geom_miny, geom_maxx, geom_maxy = geom.bounds
    grid_x0 = math.floor(geom_minx / size) * size
    grid_x1 = math.ceil(geom_maxx / size) * size
    grid_y0 = math.floor(geom_miny / size) * size
    grid_y1 = math.ceil(geom_maxy / size) * size
    cells = []
    for x in numpy.arange(grid_x0, grid_x1, size):
        for y in numpy.arange(grid_y0, grid_y1, size):
            clipped = shapely.make_valid(shapely.geometry.box(x, y, x + size, y + size).intersection(geom))
            if not clipped.is_empty and clipped.area > 0:
                cells.append((f"T_{int(x)}_{int(y)}", clipped))
    if not cells:
        return geopandas.GeoDataFrame(geometry=[], crs=config.GRID_CRS)

    cell_ids = rasterio.features.rasterize(
        [(shapely.geometry.mapping(cell), i + 1) for i, (_, cell) in enumerate(cells)],
        out_shape=ndvi.shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    eligible = rasterio.features.geometry_mask(
        [shapely.geometry.mapping(geom)],
        out_shape=ndvi.shape,
        transform=transform,
        invert=True,
        all_touched=False,
    ) & clum_mask(ndvi.shape, transform)
    records = []
    inv = ~transform
    height, width = ndvi.shape

    for i, (tile_id, cell) in enumerate(cells, start=1):
        minx, miny, maxx, maxy = cell.bounds
        c0, r1 = inv * (minx, miny)
        c1, r0 = inv * (maxx, maxy)
        row0 = max(0, int(math.floor(min(r0, r1))) - 1)
        row1 = min(height, int(math.ceil(max(r0, r1))) + 1)
        col0 = max(0, int(math.floor(min(c0, c1))) - 1)
        col1 = min(width, int(math.ceil(max(c0, c1))) + 1)

        ids = cell_ids[row0:row1, col0:col1]
        agri = (ids == i) & eligible[row0:row1, col0:col1]
        agri_n = int(agri.sum())
        if agri_n == 0:
            continue
        ndvi_view = ndvi[row0:row1, col0:col1]
        contrast_view = contrast[row0:row1, col0:col1]
        valid = agri & numpy.isfinite(ndvi_view)
        valid_n = int(valid.sum())
        values = contrast_view[valid & numpy.isfinite(contrast_view)]

        record = {
            "date": date_string,
            "tile_id": tile_id,
            "valid_coverage_fraction": valid_n / agri_n,
            "geometry": cell,
        }
        for threshold in config.C30_SENSITIVITY_THRESHOLDS:
            count = int(numpy.count_nonzero(values >= threshold))
            # Column name, e.g. threshold 0.03 -> "c30_0p03_area_fraction".
            record[f"c30_{threshold:.2f}_area_fraction".replace(".", "p")] = count / agri_n
        records.append(record)

    return geopandas.GeoDataFrame(records, geometry="geometry", crs=config.GRID_CRS)


# Landsat search, NDVI and C30 for one Pleiades date. The status is NO_SCENES, NO_VALID_PIXELS or OK.
def compute_date(catalog, inputs, date_string):
    geom = geometry_for_date(inputs, date_string)
    items = search_landsat(catalog, date_string, geom)
    if not items:
        return DateResult(date_string, "NO_SCENES", "No Landsat observations found.", [])

    minx, miny, maxx, maxy = geom.bounds
    for attempt in range(config.ASSET_READ_RETRIES + 1):
        try:
            # Lazily load the scene stack on the 30 m EPSG:3577 grid covering the footprint.
            ds = odc.stac.load(
                items,
                bands=list(config.REQUIRED_ASSETS),
                crs=config.GRID_CRS,
                resolution=config.SCALE_M,
                x=(minx, maxx),
                y=(miny, maxy),
                groupby="id",
                resampling={name: "nearest" for name in config.REQUIRED_ASSETS},
                chunks={"x": config.PROCESSING_TILE_SIZE_PX, "y": config.PROCESSING_TILE_SIZE_PX},
                fail_on_error=True,
            )
            # Affine transform of the loaded grid (from the odc geobox, else rebuilt from the coordinates).
            if hasattr(ds, "odc") and ds.odc.geobox is not None:
                transform = ds.odc.geobox.transform
            else:
                x = numpy.asarray(ds.x.values, dtype=float)
                y = numpy.asarray(ds.y.values, dtype=float)
                xres = abs(float(x[1] - x[0]))
                yres = abs(float(y[1] - y[0]))
                transform = rasterio.transform.from_origin(
                    float(x.min() - xres / 2),
                    float(y.max() + yres / 2),
                    xres,
                    yres,
                )
            ndvi = median_ndvi(ds, geom, transform)
            break
        except MemoryError:
            raise
        except Exception:
            if attempt == config.ASSET_READ_RETRIES:
                raise
            time.sleep(config.ASSET_READ_RETRY_SECONDS)
            items = search_landsat(catalog, date_string, geom)

    if not numpy.isfinite(ndvi).any():
        return DateResult(date_string, "NO_VALID_PIXELS", "No valid Landsat pixels after masking.", items)
    return DateResult(
        date_string,
        "OK",
        "",
        items,
        ndvi=ndvi,
        contrast=local_contrast(ndvi),
        transform=transform,
    )
