
# Dependencies
import ee
import geemap
import csv
import datetime

# Start GEE client
ee.Authenticate()
ee.Initialize()

# Environment/Object Setup
aoi = ee.Geometry.Rectangle(
    [1535557.8379021066, -3957765.875192861,
     1536889.676893365,  -3956800.2729655616],
    "EPSG:3577",
    False,
)
aoi_area_km2 = aoi.area(maxError=1, proj="EPSG:3577").divide(1e6).getInfo()
aoi_wgs84 = aoi.transform("EPSG:4326", 1)
centroid = aoi_wgs84.centroid(maxError=1).coordinates().getInfo()
center_lon, center_lat = centroid[0], centroid[1]
fieldnames = [
    "center_lon", "center_lat", "year", "month", "dataset",
    "elevation_mean", "elevation_stdDev", "elevation_min", "elevation_max", "elevation_median", "elevation_count",
    "ndvi_mean", "ndvi_stdDev", "ndvi_min", "ndvi_max", "ndvi_median", "ndvi_count"
]
output_path = f"../../dem_ndvi_summary_{datetime.date.today().strftime('%Y-%m-%d')}.csv"

# Pull Collections
dem = (
    ee.ImageCollection("AU/GA/AUSTRALIA_5M_DEM")
    .filterBounds(aoi)
    .mosaic()
    .clip(aoi)
)
ndvi_collection = (
    ee.ImageCollection("LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI")
    .filterBounds(aoi)
)

# Summarize Collections
dem_stats = (
    dem.select("elevation")
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
        crs="EPSG:3577",
        scale=5,
        maxPixels=int(1e9),
    )
    .getInfo()
)

# Annual summary
def annual_ndvi_stats(year):
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    image = (
        ndvi_collection
        .filterDate(start, end)
        .select("NDVI")
        .mean()
        .clip(aoi)
    )
    stats = image.reduceRegion(
        reducer=(
            ee.Reducer.mean()
            .combine(ee.Reducer.stdDev(), "", True)
            .combine(ee.Reducer.min(), "", True)
            .combine(ee.Reducer.max(), "", True)
            .combine(ee.Reducer.median(), "", True)
            .combine(ee.Reducer.count(), "", True)
        ),
        geometry=aoi,
        crs="EPSG:3577",
        scale=30,
        maxPixels=int(1e9),
    ).getInfo()
    return image, stats

#ndvi_2012_image, ndvi_2012_stats = annual_ndvi_stats(2012)
#ndvi_2025_image, ndvi_2025_stats = annual_ndvi_stats(2025)

# Monthly Summary

def monthly_ndvi_stats(year):
    rows = []
    for month in range(1, 13):
        start = datetime.date(year, month, 1)
        if month == 12:
            end = datetime.date(year, 12, 31)
        else:
            end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

        image = (
            ndvi_collection
            .filterDate(start.isoformat(), (end + datetime.timedelta(days=1)).isoformat())
            .select("NDVI")
            .mean()
            .clip(aoi)
        )

        stats = image.reduceRegion(
            reducer=(
                ee.Reducer.mean()
                .combine(ee.Reducer.stdDev(), "", True)
                .combine(ee.Reducer.min(), "", True)
                .combine(ee.Reducer.max(), "", True)
                .combine(ee.Reducer.median(), "", True)
                .combine(ee.Reducer.count(), "", True)
            ),
            geometry=aoi,
            crs="EPSG:3577",
            scale=30,
            maxPixels=int(1e9),
        ).getInfo()

        rows.append({
            "year": year,
            "month": month,
            "ndvi_mean":    stats.get("NDVI_mean"),
            "ndvi_stdDev":  stats.get("NDVI_stdDev"),
            "ndvi_min":     stats.get("NDVI_min"),
            "ndvi_max":     stats.get("NDVI_max"),
            "ndvi_median":  stats.get("NDVI_median"),
            "ndvi_count":   stats.get("NDVI_count"),
        })
    return rows

ndvi_2012_monthly = monthly_ndvi_stats(2012)
ndvi_2025_monthly = monthly_ndvi_stats(2025)


# Create output CSV from the data
ndvi_rows_by_key = {
    (r["year"], r["month"]): r
    for r in ndvi_2012_monthly + ndvi_2025_monthly
}

for month in range(1, 13):
    start = datetime.date(2012, month, 1)
    if month == 12:
        end = datetime.date(2012, 12, 31)
    else:
        end = datetime.date(2012, month + 1, 1) - datetime.timedelta(days=1)

    img_2012 = (
        ndvi_collection
        .filterDate(start.isoformat(), (end + datetime.timedelta(days=1)).isoformat())
        .select("NDVI")
        .mean()
        .clip(aoi)
    )

    start_25 = datetime.date(2025, month, 1)
    if month == 12:
        end_25 = datetime.date(2025, 12, 31)
    else:
        end_25 = datetime.date(2025, month + 1, 1) - datetime.timedelta(days=1)

    img_2025 = (
        ndvi_collection
        .filterDate(start_25.isoformat(), (end_25 + datetime.timedelta(days=1)).isoformat())
        .select("NDVI")
        .mean()
        .clip(aoi)
    )

with open(output_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    writer.writerow({
        "center_lon":        center_lon,
        "center_lat":        center_lat,
        "year":              None,
        "month":             None,
        "dataset":           "AU/GA/AUSTRALIA_5M_DEM",
        "elevation_mean":    dem_stats.get("elevation_mean"),
        "elevation_stdDev":  dem_stats.get("elevation_stdDev"),
        "elevation_min":     dem_stats.get("elevation_min"),
        "elevation_max":     dem_stats.get("elevation_max"),
        "elevation_median":  dem_stats.get("elevation_median"),
        "elevation_count":   dem_stats.get("elevation_count"),
        "ndvi_mean":         None,
        "ndvi_stdDev":       None,
        "ndvi_min":          None,
        "ndvi_max":          None,
        "ndvi_median":       None,
        "ndvi_count":        None
    })

    for year in (2012, 2025):
        for month in range(1, 13):
            ndvi = ndvi_rows_by_key.get((year, month), {})
            change = change_by_month.get(month, {}) if year == 2025 else {}
            writer.writerow({
                "center_lon":        center_lon,
                "center_lat":        center_lat,
                "year":              year,
                "month":             month,
                "dataset":           "LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI",
                "elevation_mean":    None,
                "elevation_stdDev":  None,
                "elevation_min":     None,
                "elevation_max":     None,
                "elevation_median":  None,
                "elevation_count":   None,
                "ndvi_mean":         ndvi.get("ndvi_mean"),
                "ndvi_stdDev":       ndvi.get("ndvi_stdDev"),
                "ndvi_min":          ndvi.get("ndvi_min"),
                "ndvi_max":          ndvi.get("ndvi_max"),
                "ndvi_median":       ndvi.get("ndvi_median"),
                "ndvi_count":        ndvi.get("ndvi_count")
            })

# end
