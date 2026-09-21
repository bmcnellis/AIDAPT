# Landsat NDVI and local C30 calculations.

import math
import re
import time
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import geopandas
import numpy
import pandas
import planetary_computer
import rasterio
from affine import Affine
from odc import stac
from pystac import Item
from pystac_client import Client
from rasterio.features import geometry_mask, rasterize
from rasterio.warp import Resampling, reproject
from scipy.ndimage import generic_filter
from shapely import make_valid
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry

import config


@dataclass
class Inputs:
    aoi: BaseGeometry
    footprints: geopandas.GeoDataFrame


@dataclass
class DateResult:
    date: str
    status: str
    message: str
    scene_items: list[Item]
    ndvi: numpy.ndarray | None = None
    contrast: numpy.ndarray | None = None
    transform: Affine | None = None

    @property
    def scene_count(self):
        return len(self.scene_items)


def load_inputs():
    for path in (config.AOI_FILE, config.FOOTPRINTS_FILE, config.CLUM_RASTER):
        if not Path(path).exists():
            raise FileNotFoundError(path)
    aoi = geopandas.read_file(config.AOI_FILE, layer=config.AOI_LAYER).to_crs(config.GRID_CRS)
    footprints = geopandas.read_file(
        config.FOOTPRINTS_FILE, layer=config.FOOTPRINTS_LAYER
    ).to_crs(config.GRID_CRS)
    footprints[config.DATE_FIELD] = pandas.to_datetime(
        footprints[config.DATE_FIELD]
    ).dt.strftime("%Y-%m-%d")
    aoi_geom = make_valid(aoi.geometry.union_all())
    footprints = footprints[footprints.geometry.notna()].copy()
    footprints["geometry"] = footprints.geometry.map(make_valid)
    footprints = footprints[footprints.intersects(aoi_geom)].copy()
    return Inputs(aoi_geom, footprints)


def acquisition_dates(inputs):
    dates = sorted(inputs.footprints[config.DATE_FIELD].dropna().astype(str).unique())
    return [d for d in dates if config.START_DATE <= d < config.END_DATE]


def geometry_for_date(inputs, date_string):
    rows = inputs.footprints[inputs.footprints[config.DATE_FIELD] == date_string]
    return make_valid(rows.geometry.union_all().intersection(inputs.aoi))


def open_catalog():
    return Client.open(config.STAC_URL, modifier=planetary_computer.sign_inplace)


def requested_landsat_item(item):
    if not item.id.startswith(tuple(config.LANDSAT_ID_PREFIXES)):
        return False
    if config.REQUIRE_TIER1:
        category = item.properties.get("landsat:collection_category")
        if category is not None and str(category).upper() != "T1":
            return False
        if category is None and re.search(r"(?:^|_)T1(?:_|$)", item.id, re.IGNORECASE) is None:
            return False
    return all(name in item.assets for name in config.REQUIRED_ASSETS)


def search_landsat(catalog, date_string, geom):
    center = date.fromisoformat(date_string)
    start = center - timedelta(days=config.LANDSAT_WINDOW_DAYS)
    end = center + timedelta(days=config.LANDSAT_WINDOW_DAYS)
    geom_wgs84 = geopandas.GeoSeries([geom], crs=config.GRID_CRS).to_crs("EPSG:4326").iloc[0]
    search = catalog.search(
        collections=[config.STAC_COLLECTION],
        bbox=tuple(float(v) for v in geom_wgs84.bounds),
        datetime=f"{start.isoformat()}/{end.isoformat()}",
    )
    items = []
    for item in search.items():
        if not requested_landsat_item(item):
            continue
        if item.geometry is not None and not make_valid(shape(item.geometry)).intersects(geom_wgs84):
            continue
        items.append(item)
    return sorted(items, key=lambda x: (x.datetime.timestamp() if x.datetime else float("-inf"), x.id))


def load_landsat_stack(items, geom):
    minx, miny, maxx, maxy = geom.bounds
    return stac.load(
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


def grid_transform(ds):
    if hasattr(ds, "odc") and ds.odc.geobox is not None:
        return ds.odc.geobox.transform
    x = numpy.asarray(ds.x.values, dtype=float)
    y = numpy.asarray(ds.y.values, dtype=float)
    xres = abs(float(x[1] - x[0]))
    yres = abs(float(y[1] - y[0]))
    return rasterio.transform.from_origin(
        float(x.min() - xres / 2),
        float(y.max() + yres / 2),
        xres,
        yres,
    )


def footprint_mask(geom, shape_, transform):
    return geometry_mask(
        [mapping(geom)],
        out_shape=shape_,
        transform=transform,
        invert=True,
        all_touched=False,
    )


@lru_cache(maxsize=1)
def load_clum_source():
    with rasterio.Env(GDAL_GEOREF_SOURCES="WORLDFILE,PAM,INTERNAL"):
        with rasterio.open(config.CLUM_RASTER) as src:
            return src.read(1), src.transform, src.crs, src.nodata


def clum_mask(shape_, transform):
    source, src_transform, src_crs, src_nodata = load_clum_source()
    destination = numpy.zeros(shape_, dtype=numpy.float32)
    reproject(
        source=source,
        destination=destination,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=src_nodata,
        dst_transform=transform,
        dst_crs=config.GRID_CRS,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    return destination == float(config.CLUM_VALUE)


def median_ndvi(ds, geom, transform):
    height = int(ds.sizes["y"])
    width = int(ds.sizes["x"])
    shape_ = (height, width)
    spatial = footprint_mask(geom, shape_, transform) & clum_mask(shape_, transform)
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
            red_dn = numpy.asarray(tile["red"].values)
            nir_dn = numpy.asarray(tile["nir08"].values)
            qa_pixel = numpy.asarray(tile["qa_pixel"].values)
            qa_radsat = numpy.asarray(tile["qa_radsat"].values)
            red = red_dn.astype(numpy.float32) * config.SR_SCALE + config.SR_OFFSET
            nir = nir_dn.astype(numpy.float32) * config.SR_SCALE + config.SR_OFFSET
            denominator = nir + red

            qa_pixel = numpy.nan_to_num(qa_pixel, nan=config.QA_BAD_BITS_0_TO_5).astype(numpy.uint32)
            qa_radsat = numpy.nan_to_num(qa_radsat, nan=1).astype(numpy.uint32)
            valid = (
                ((qa_pixel & config.QA_BAD_BITS_0_TO_5) == 0)
                & (qa_radsat == 0)
                & numpy.isfinite(red)
                & numpy.isfinite(nir)
                & numpy.isfinite(denominator)
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


def contrast_footprint():
    radius_px = config.BACKGROUND_RADIUS_M / config.SCALE_M
    half = int(math.ceil(radius_px))
    yy, xx = numpy.mgrid[-half : half + 1, -half : half + 1]
    footprint = (xx * xx + yy * yy) <= radius_px * radius_px + 1e-9
    footprint[half, half] = False
    return footprint


def nanmedian(values):
    values = values[numpy.isfinite(values)]
    return numpy.median(values) if values.size else numpy.nan


def local_contrast(ndvi):
    local_median = generic_filter(
        ndvi,
        nanmedian,
        footprint=contrast_footprint(),
        mode="constant",
        cval=numpy.nan,
        output=numpy.float32,
    )
    contrast = (ndvi - local_median).astype(numpy.float32)
    contrast[~numpy.isfinite(ndvi)] = numpy.nan
    return contrast


def c30_column(threshold):
    return f"c30_{threshold:.2f}_area_fraction".replace(".", "p")


def aligned_grid_cells(geom):
    size = config.GRID_SIZE_M
    minx, miny, maxx, maxy = geom.bounds
    x0 = math.floor(minx / size) * size
    x1 = math.ceil(maxx / size) * size
    y0 = math.floor(miny / size) * size
    y1 = math.ceil(maxy / size) * size
    cells = []
    for x in numpy.arange(x0, x1, size):
        for y in numpy.arange(y0, y1, size):
            clipped = make_valid(box(x, y, x + size, y + size).intersection(geom))
            if not clipped.is_empty and clipped.area > 0:
                cells.append((f"T_{int(x)}_{int(y)}", clipped))
    return cells


def summarize_cells(date_string, geom, ndvi, contrast, transform):
    cells = aligned_grid_cells(geom)
    if not cells:
        return geopandas.GeoDataFrame(geometry=[], crs=config.GRID_CRS)

    cell_ids = rasterize(
        [(mapping(cell), i + 1) for i, (_, cell) in enumerate(cells)],
        out_shape=ndvi.shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    eligible = footprint_mask(geom, ndvi.shape, transform) & clum_mask(ndvi.shape, transform)
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
            record[c30_column(threshold)] = count / agri_n
        records.append(record)

    return geopandas.GeoDataFrame(records, geometry="geometry", crs=config.GRID_CRS)


def compute_date(catalog, inputs, date_string):
    geom = geometry_for_date(inputs, date_string)
    items = search_landsat(catalog, date_string, geom)
    if not items:
        return DateResult(date_string, "NO_SCENES", "No Landsat observations found.", [])

    for attempt in range(config.ASSET_READ_RETRIES + 1):
        try:
            ds = load_landsat_stack(items, geom)
            transform = grid_transform(ds)
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


def write_geojson(gdf, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_crs("EPSG:4326").to_file(path, driver="GeoJSON")
