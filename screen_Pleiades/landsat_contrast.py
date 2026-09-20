# Landsat NDVI and local C30 calculations.

import math
import re
import time
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
from affine import Affine
import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from odc import stac
from pystac import Item
from pystac_client import Client
from rasterio.features import geometry_mask, rasterize
from rasterio.warp import Resampling, reproject
from scipy.ndimage import generic_filter
from shapely import make_valid
from shapely.geometry import box, mapping, shape
from shapely.geometry.base import BaseGeometry

import config as cfg

REQUIRED_ASSETS = ("red", "nir08", "qa_pixel", "qa_radsat")
QA_BAD_BITS_0_TO_5 = 0b111111


@dataclass
class Inputs:
    aoi: BaseGeometry
    footprints: gpd.GeoDataFrame


@dataclass
class DateResult:
    date: str
    status: str
    message: str
    scene_items: list[Item]
    ndvi: np.ndarray | None = None
    contrast: np.ndarray | None = None
    transform: Affine | None = None

    @property
    def scene_count(self):
        return len(self.scene_items)


def load_inputs():
    for path in (cfg.AOI_FILE, cfg.FOOTPRINTS_FILE, cfg.CLUM_RASTER):
        if not Path(path).exists():
            raise FileNotFoundError(path)

    aoi = gpd.read_file(cfg.AOI_FILE, layer=cfg.AOI_LAYER).to_crs(cfg.GRID_CRS)
    footprints = gpd.read_file(cfg.FOOTPRINTS_FILE, layer=cfg.FOOTPRINTS_LAYER).to_crs(cfg.GRID_CRS)
    footprints[cfg.DATE_FIELD] = pd.to_datetime(footprints[cfg.DATE_FIELD]).dt.strftime("%Y-%m-%d")

    aoi_geom = make_valid(aoi.geometry.union_all())
    footprints = footprints[footprints.geometry.notna()].copy()
    footprints["geometry"] = footprints.geometry.map(make_valid)
    footprints = footprints[footprints.intersects(aoi_geom)].copy()
    return Inputs(aoi_geom, footprints)


def acquisition_dates(inputs):
    dates = sorted(inputs.footprints[cfg.DATE_FIELD].dropna().astype(str).unique())
    return [d for d in dates if cfg.START_DATE <= d < cfg.END_DATE]


def geometry_for_date(inputs, date_string):
    rows = inputs.footprints[inputs.footprints[cfg.DATE_FIELD] == date_string]
    return make_valid(rows.geometry.union_all().intersection(inputs.aoi))


def open_catalog():
    return Client.open(cfg.STAC_URL, modifier=planetary_computer.sign_inplace)


def requested_landsat_item(item):
    if not item.id.startswith(tuple(cfg.LANDSAT_ID_PREFIXES)):
        return False
    if cfg.REQUIRE_TIER1:
        category = item.properties.get("landsat:collection_category")
        if category is not None and str(category).upper() != "T1":
            return False
        if category is None and re.search(r"(?:^|_)T1(?:_|$)", item.id, re.IGNORECASE) is None:
            return False
    return all(name in item.assets for name in REQUIRED_ASSETS)


def search_landsat(catalog, date_string, geom):
    center = date.fromisoformat(date_string)
    start = center - timedelta(days=cfg.LANDSAT_WINDOW_DAYS)
    end = center + timedelta(days=cfg.LANDSAT_WINDOW_DAYS)
    geom_wgs84 = gpd.GeoSeries([geom], crs=cfg.GRID_CRS).to_crs("EPSG:4326").iloc[0]

    search = catalog.search(
        collections=[cfg.STAC_COLLECTION],
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
        bands=list(REQUIRED_ASSETS),
        crs=cfg.GRID_CRS,
        resolution=cfg.SCALE_M,
        x=(minx, maxx),
        y=(miny, maxy),
        groupby="id",
        resampling={name: "nearest" for name in REQUIRED_ASSETS},
        chunks={"x": cfg.PROCESSING_TILE_SIZE_PX, "y": cfg.PROCESSING_TILE_SIZE_PX},
        fail_on_error=True,
    )


def grid_transform(ds):
    if hasattr(ds, "odc") and ds.odc.geobox is not None:
        return ds.odc.geobox.transform

    x = np.asarray(ds.x.values, dtype=float)
    y = np.asarray(ds.y.values, dtype=float)
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
        with rasterio.open(cfg.CLUM_RASTER) as src:
            return src.read(1), src.transform, src.crs, src.nodata


def clum_mask(shape_, transform):
    source, src_transform, src_crs, src_nodata = load_clum_source()
    destination = np.zeros(shape_, dtype=np.float32)
    reproject(
        source=source,
        destination=destination,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=src_nodata,
        dst_transform=transform,
        dst_crs=cfg.GRID_CRS,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    return destination == float(cfg.CLUM_VALUE)


def median_ndvi(ds, geom, transform):
    height = int(ds.sizes["y"])
    width = int(ds.sizes["x"])
    shape_ = (height, width)
    spatial = footprint_mask(geom, shape_, transform) & clum_mask(shape_, transform)
    ndvi = np.full(shape_, np.nan, dtype=np.float32)

    size = cfg.PROCESSING_TILE_SIZE_PX
    for y0 in range(0, height, size):
        for x0 in range(0, width, size):
            y1 = min(y0 + size, height)
            x1 = min(x0 + size, width)
            spatial_tile = spatial[y0:y1, x0:x1]
            if not spatial_tile.any():
                continue

            tile = ds[list(REQUIRED_ASSETS)].isel(
                y=slice(y0, y1), x=slice(x0, x1)
            ).compute(scheduler="threads", num_workers=cfg.IO_THREADS)

            red_dn = np.asarray(tile["red"].values)
            nir_dn = np.asarray(tile["nir08"].values)
            qa_pixel = np.asarray(tile["qa_pixel"].values)
            qa_radsat = np.asarray(tile["qa_radsat"].values)

            red = red_dn.astype(np.float32) * cfg.SR_SCALE + cfg.SR_OFFSET
            nir = nir_dn.astype(np.float32) * cfg.SR_SCALE + cfg.SR_OFFSET
            denominator = nir + red

            qa_pixel = np.nan_to_num(qa_pixel, nan=QA_BAD_BITS_0_TO_5).astype(np.uint32)
            qa_radsat = np.nan_to_num(qa_radsat, nan=1).astype(np.uint32)
            valid = (
                ((qa_pixel & QA_BAD_BITS_0_TO_5) == 0)
                & (qa_radsat == 0)
                & np.isfinite(red)
                & np.isfinite(nir)
                & np.isfinite(denominator)
                & (np.abs(denominator) > 1e-12)
                & spatial_tile[None, :, :]
            )

            stack = np.full(red.shape, np.nan, dtype=np.float32)
            np.divide(nir - red, denominator, out=stack, where=valid)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                median = np.nanmedian(stack, axis=0).astype(np.float32)
            median[~spatial_tile] = np.nan
            ndvi[y0:y1, x0:x1] = median

    ndvi[~spatial] = np.nan
    return ndvi


def contrast_footprint():
    radius_px = cfg.BACKGROUND_RADIUS_M / cfg.SCALE_M
    half = int(math.ceil(radius_px))
    yy, xx = np.mgrid[-half : half + 1, -half : half + 1]
    footprint = (xx * xx + yy * yy) <= radius_px * radius_px + 1e-9
    footprint[half, half] = False
    return footprint


def nanmedian(values):
    values = values[np.isfinite(values)]
    return np.median(values) if values.size else np.nan


def local_contrast(ndvi):
    local_median = generic_filter(
        ndvi,
        nanmedian,
        footprint=contrast_footprint(),
        mode="constant",
        cval=np.nan,
        output=np.float32,
    )
    contrast = (ndvi - local_median).astype(np.float32)
    contrast[~np.isfinite(ndvi)] = np.nan
    return contrast


def c30_column(threshold):
    return f"c30_{threshold:.2f}_area_fraction".replace(".", "p")


def aligned_grid_cells(geom):
    size = cfg.GRID_SIZE_M
    minx, miny, maxx, maxy = geom.bounds
    x0 = math.floor(minx / size) * size
    x1 = math.ceil(maxx / size) * size
    y0 = math.floor(miny / size) * size
    y1 = math.ceil(maxy / size) * size

    cells = []
    for x in np.arange(x0, x1, size):
        for y in np.arange(y0, y1, size):
            clipped = make_valid(box(x, y, x + size, y + size).intersection(geom))
            if not clipped.is_empty and clipped.area > 0:
                cells.append((f"T_{int(x)}_{int(y)}", clipped))
    return cells


def summarize_cells(date_string, geom, ndvi, contrast, transform):
    cells = aligned_grid_cells(geom)
    if not cells:
        return gpd.GeoDataFrame(geometry=[], crs=cfg.GRID_CRS)

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
        valid = agri & np.isfinite(ndvi_view)
        valid_n = int(valid.sum())
        values = contrast_view[valid & np.isfinite(contrast_view)]

        record = {
            "date": date_string,
            "tile_id": tile_id,
            "valid_coverage_fraction": valid_n / agri_n,
            "geometry": cell,
        }
        for threshold in cfg.C30_SENSITIVITY_THRESHOLDS:
            count = int(np.count_nonzero(values >= threshold))
            record[c30_column(threshold)] = count / agri_n
        records.append(record)

    return gpd.GeoDataFrame(records, geometry="geometry", crs=cfg.GRID_CRS)


def compute_date(catalog, inputs, date_string):
    geom = geometry_for_date(inputs, date_string)
    items = search_landsat(catalog, date_string, geom)
    if not items:
        return DateResult(date_string, "NO_SCENES", "No Landsat observations found.", [])

    for attempt in range(cfg.ASSET_READ_RETRIES + 1):
        try:
            ds = load_landsat_stack(items, geom)
            transform = grid_transform(ds)
            ndvi = median_ndvi(ds, geom, transform)
            break
        except MemoryError:
            raise
        except Exception:
            if attempt == cfg.ASSET_READ_RETRIES:
                raise
            time.sleep(cfg.ASSET_READ_RETRY_SECONDS)
            items = search_landsat(catalog, date_string, geom)

    if not np.isfinite(ndvi).any():
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
