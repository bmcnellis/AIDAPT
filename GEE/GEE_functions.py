
# Dependencies
import ee
import csv
import datetime

# Defs
def get_dem_stats(collection, aoi, epsg):
    
    # Handle both Image and ImageCollection inputs
    if isinstance(collection, ee.Image):
        image = collection.clip(aoi).select("elevation")
    else:
        image = (
            ee.ImageCollection(collection)
            .filterBounds(aoi)
            .mosaic()
            .clip(aoi)
            .select("elevation")
        )

    return (
        image
        .reduceRegion(
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
            scale=5,
            maxPixels=int(1e9),
        )
        .getInfo()
    )
  
def get_ndvi_stats(collection, aoi, years, epsg):
  
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

def make_dem_row(name, centroid, dem_stats):
    return {
        "name":             name,
        "center_lon":       centroid[0],
        "center_lat":       centroid[1],
        #"year":             None,
        #"month":            None,
        "dataset":          "AU/GA/AUSTRALIA_5M_DEM",
        "elevation_mean":   dem_stats.get("elevation_mean"),
        "elevation_stdDev": dem_stats.get("elevation_stdDev"),
        "elevation_min":    dem_stats.get("elevation_min"),
        "elevation_max":    dem_stats.get("elevation_max"),
        "elevation_median": dem_stats.get("elevation_median"),
        "elevation_count":  dem_stats.get("elevation_count"),
        #"ndvi_mean":        None,
        #"ndvi_stdDev":      None,
        #"ndvi_min":         None,
        #"ndvi_max":         None,
        #"ndvi_median":      None,
        #"ndvi_count":       None,
    }


def make_ndvi_row(name, centroid, year, month, ndvi):
    return {
        "name":             name,
        "center_lon":       centroid[0],
        "center_lat":       centroid[1],
        "year":             year,
        "month":            month,
        "dataset":          "LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI",
        #"elevation_mean":   None,
        #"elevation_stdDev": None,
        #"elevation_min":    None,
        #"elevation_max":    None,
        #"elevation_median": None,
        #"elevation_count":  None,
        "ndvi_mean":        ndvi.get("ndvi_mean"),
        "ndvi_stdDev":      ndvi.get("ndvi_stdDev"),
        "ndvi_min":         ndvi.get("ndvi_min"),
        "ndvi_max":         ndvi.get("ndvi_max"),
        "ndvi_median":      ndvi.get("ndvi_median"),
        "ndvi_count":       ndvi.get("ndvi_count"),
    }
