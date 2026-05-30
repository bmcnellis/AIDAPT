
# Dependencies
import ee
import csv
import datetime
import math

# Defs
def calc_slp_asp_stats(image: ee.Image, aoi: ee.Geometry, var: str, scale: int = 30) -> dict:
  
    image_rad = image.multiply(math.pi / 180)
    sin_image = image_rad.sin().rename('sin_image')
    cos_image = image_rad.cos().rename('cos_image')
    
    sin_cos_image = ee.Image.cat([sin_image, cos_image])

    sin_cos_stats = sin_cos_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi,
        scale=scale,
        maxPixels=1e10
    ).getInfo()

    mean_var_rad = math.atan2(sin_cos_stats['sin_image'], sin_cos_stats['cos_image'])
    mean_var_deg = math.degrees(mean_var_rad) % 360
    
    # for s.d. or other stats: https://stackoverflow.com/questions/55616697/how-to-calculate-standard-deviation-of-circular-data

    return {
        f'mean_{var}_rad': mean_var_rad,
        f'mean_{var}_deg': mean_var_deg
    }
    
def get_dem_stats(image: ee.Image, aoi: ee.Geometry, epsg: str, scale: int = 30) -> dict:
  
    dem = ee.Image(image).clip(aoi).select('elevation')
        
    ter = ee.Terrain.products(dem)
    slp = ter.select('slope')
    asp = ter.select('aspect')
    
    mean_elev = dem.reduceRegion(
      reducer=(
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), "", True)
        .combine(ee.Reducer.min(), "", True)
        .combine(ee.Reducer.max(), "", True)
        .combine(ee.Reducer.median(), "", True)
        .combine(ee.Reducer.count(), "", True)
        ),
        geometry=aoi,
        crs=epsg,
        scale=scale,
        maxPixels=int(1e10)
        ).getInfo()
        
    slp_stats = calc_slp_asp_stats(slp, aoi, 'slope')
    asp_stats = calc_slp_asp_stats(slp, aoi, 'aspect')
    
    return {
      **mean_elev,
      **slp_stats,
      **asp_stats
    }
  
def get_ndvi_stats(collection: ee.ImageCollection, aoi: ee.Geometry, years: list[int], epsg: str) -> dict:
  
    ndvi_collection = ee.ImageCollection(collection).filterBounds(aoi)
    
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.stdDev(), "", True)
        .combine(ee.Reducer.min(), "", True)
        .combine(ee.Reducer.max(), "", True)
        .combine(ee.Reducer.median(), "", True)
        .combine(ee.Reducer.count(), "", True)
    )

    results = []
    for year in years:
        for month in range(1, 13):
            start = datetime.date(year, month, 1)
            end = (datetime.date(year, 12, 31) if month == 12
                   else datetime.date(year, month + 1, 1) - datetime.timedelta(days=1))
            image = (
                ndvi_collection
                .filterDate(start.isoformat(), (end + datetime.timedelta(days=1)).isoformat())
                .select("NDVI")
                .mean()
                .clip(aoi)
            )
            results.append(ee.Feature(None, 
                image.reduceRegion(reducer, aoi, scale=30, crs=epsg, maxPixels=int(1e9))
                .set("year", year).set("month", month)
            ))

    fc_info = ee.FeatureCollection(results).getInfo()
    
    lookup = {}
    for feat in fc_info["features"]:
        p = feat["properties"]
        lookup[(p["year"], p["month"])] = {
            "year": p["year"], "month": p["month"],
            "ndvi_mean":   p.get("NDVI_mean"),
            "ndvi_stdDev": p.get("NDVI_stdDev"),
            "ndvi_min":    p.get("NDVI_min"),
            "ndvi_max":    p.get("NDVI_max"),
            "ndvi_median": p.get("NDVI_median"),
            "ndvi_count":  p.get("NDVI_count"),
        }
    return lookup

def make_dem_fields() -> list:
    return list({
        "name":             None,
        "center_lon":       None,
        "center_lat":       None,
        "dataset":          None,
        "elevation_mean":   None,
        "elevation_stdDev": None,
        "elevation_min":    None,
        "elevation_max":    None,
        "elevation_median": None,
        "elevation_count":  None,
        "slope_mean_rad":   None,
        "slope_mean_deg":   None,
        "aspect_mean_rad":  None,
        "aspect_mean_deg":  None
    }.keys())

def make_dem_row(name: str, centroid: list[float], dem_stats: dict) -> dict:
    values = [
        name,
        centroid[0],
        centroid[1],
        "AU/GA/AUSTRALIA_5M_DEM",
        dem_stats.get("elevation_mean"),
        dem_stats.get("elevation_stdDev"),
        dem_stats.get("elevation_min"),
        dem_stats.get("elevation_max"),
        dem_stats.get("elevation_median"),
        dem_stats.get("elevation_count"),
        dem_stats.get("mean_slope_rad"),
        dem_stats.get("mean_slope_deg"),
        dem_stats.get("mean_aspect_rad"),
        dem_stats.get("mean_aspect_deg")
    ]

    fields = make_dem_fields()

    if len(fields) != len(values):
        raise ValueError(
            f"Field/value length mismatch: {len(fields)} fields vs {len(values)} values"
        )

    return dict(zip(fields, values))

def make_ndvi_fields() -> list:
    return list({
        "name":        None,
        "center_lon":  None,
        "center_lat":  None,
        "year":        None,
        "month":       None,
        "dataset":     None,
        "ndvi_mean":   None,
        "ndvi_stdDev": None,
        "ndvi_min":    None,
        "ndvi_max":    None,
        "ndvi_median": None,
        "ndvi_count":  None,
    }.keys())

def make_ndvi_row(name: str, centroid: list[float], year: int, month: int, ndvi: dict) -> dict:
    values = [
        name,
        centroid[0],
        centroid[1],
        year,
        month,
        "LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI",
        ndvi.get("ndvi_mean"),
        ndvi.get("ndvi_stdDev"),
        ndvi.get("ndvi_min"),
        ndvi.get("ndvi_max"),
        ndvi.get("ndvi_median"),
        ndvi.get("ndvi_count"),
    ]

    fields = make_ndvi_fields()

    if len(fields) != len(values):
        raise ValueError(
            f"Field/value length mismatch: {len(fields)} fields vs {len(values)} values"
        )

    return dict(zip(fields, values))
