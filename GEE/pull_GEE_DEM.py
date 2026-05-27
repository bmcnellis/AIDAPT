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
import GEE_functions
with open("data/bounding_coordinates_30_sites_20260526.csv", "r", newline="") as f:
    aoi_df = list(csv.DictReader(f))

# Constants/Inits
collection = "AU/GA/DEM_1SEC/v10/DEM-S"
fieldnames = [
    "name", "center_lon", "center_lat", "dataset",
    "elevation_mean", "elevation_stdDev", "elevation_min", "elevation_max", "elevation_median", "elevation_count"
]
out_file = f"../../results/DEM_summary_{datetime.date.today().strftime('%Y-%m-%d')}.csv"
partial_dir = "../../results/partial"
epsg = "EPSG:4326"

# Generate the AOI list from the provided coordinates to iterate over
aoi_list = [
    (row["site"], ee.Geometry.Rectangle(
        [float(row["xmin_4326"]), float(row["ymin_4326"]), float(row["xmax_4326"]), float(row["ymax_4326"])],
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
    
    dem_stats = GEE_functions.get_dem_stats(collection, aoi, epsg)

    partial_data.append(GEE_functions.make_dem_row(name, centroid, dem_stats))
            
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
            

