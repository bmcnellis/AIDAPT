# External Dependencies
import os
import ee
import geemap
import csv
import datetime

# Start GEE client
ee.Authenticate()
ee.Initialize(project="ee-bmcnellis")

# Local Dependencies
import functions
with open("bounding_coordinates_30_sites_20260526.csv", "r", newline="") as f:
    aoi_df = list(csv.DictReader(f))

# Constants/Inits
fieldnames = [
    "name", "center_lon", "center_lat", "year", "month", "dataset",
    "elevation_mean", "elevation_stdDev", "elevation_min", "elevation_max", "elevation_median", "elevation_count",
    "ndvi_mean", "ndvi_stdDev", "ndvi_min", "ndvi_max", "ndvi_median", "ndvi_count"
]
out_file = f"../results/dem_ndvi_summary_{datetime.date.today().strftime('%Y-%m-%d')}.csv"
partial_dir = "../results/partial"
epsg = "EPSG:3577"
yrs = range(2012, 2026)

# Generate the AOI list from the provided coordinates to iterate over
aoi_list = [
    (row["site"], ee.Geometry.Rectangle(
        [float(row["xmin_3577"]), float(row["ymin_3577"]), float(row["xmax_3577"]), float(row["ymax_3577"])],
        epsg,
        False,
    ))
    for row in aoi_df
]

# Pull GEE data
for name, aoi in aoi_list:
    centroid = (aoi.centroid(maxError=1).transform(epsg, 1).coordinates().getInfo())
    partial_data = []
    partial_data_file = f"{partial_dir}/{name}_{centroid[0]}_{centroid[1]}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    dem_stats = functions.get_dem_stats("AU/GA/AUSTRALIA_5M_DEM", aoi, epsg)
    ndvi_stats_keyed = functions.get_ndvi_stats("LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI", aoi, yrs, epsg)

    partial_data.append(functions.make_dem_row(name, centroid, dem_stats))
    for year in yrs:
        for month in range(1, 13):
            ndvi = ndvi_stats_keyed.get((year, month), {})
            partial_data.append(functions.make_ndvi_row(name, centroid, year, month, ndvi))
            
    # write the partial datafiles so that the process can be interrupted
    with open(partial_data_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(partial_data)

# Compile finished results
out_data = []
for filename in os.listdir(partial_dir):
    if filename.endswith(".csv"):
        with open(os.path.join(partial_dir, filename), "r", newline="") as f:
            reader = csv.DictReader(f)
            out_data.extend(reader)

with open(out_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(out_data)
            

