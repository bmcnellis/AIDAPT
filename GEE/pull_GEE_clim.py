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
with open("bounding_coordinates_30_sites_20260526.csv", "r", newline="") as f:
    aoi_df = list(csv.DictReader(f))

# Constants/Inits
# TODO: need fieldnames
out_file = f"../../results/clim_summary_{datetime.date.today().strftime('%Y-%m-%d')}.csv"
partial_dir = "../../results/partial"
epsg = "EPSG:3577"
yrs = range(2012, 2024)

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

    for year in yrs:
        for month in range(1, 13):
            
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
            

