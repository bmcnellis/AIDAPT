# Pleiades screening



Two main stages:



Stage 1: use Pleiades footprints and Landsat to screen/select tiles

Stage 2: choose the actual Pleiades acquisition to download

## Stage 1 - footprint screening



Setup



stage1\_prepare\_aoi.py

Merge AOI files.



stage1\_prepare\_footprints.py

Merge dated Pleiades footprints.



1\. Seasonal selection + Landsat processing



stage1\_1\_process\_dates.py

Keep Nov-Feb Pleiades dates. For each date, find Landsat 8 within +/-8 days, mask cloud/invalid pixels, calculate NDVI and C30, and keep dates with valid Landsat NDVI in agricultural land.



stage1\_2\_merge\_results.py

Combine retained dates into candidate\_dates.csv.



2\. 1 km tile-date screening



stage1\_3\_build\_tiles.py

Create 1 km tiles and apply:



Pleiades footprint coverage

agricultural land

Landsat coverage

C30 threshold



stage1\_4\_sensitivity.py

Repeat the contrast screen using the alternative C30 and area thresholds.



3\. Tile-season-year eligibility



stage1\_5\_common\_coverage.py

Summarise each tile-season-year as pass, fail or not evaluable. Also identify tiles eligible for:



six-season design

2013/2023 design



4\. Random sampling



stage1\_6\_sample\_tiles.py

Give eligible tiles a fixed random order. Keep the same order if extra/replacement tiles are needed later.



## Stage 2 - imagery selection



stage2\_1\_prepare\_imagery.py

For each selected tile-season-year, order the passing Pleiades dates by distance from the middle of the Nov-Feb window. Create the Airbus metadata review table.



stage2\_2\_select\_imagery.py

Choose one usable Airbus acquisition per tile-season-year. Check that the individual acquisition covers the full 1 km tile before selection.



Outputs:



selected\_imagery.csv

selected\_imagery.gpkg



Stage 1 uses the Pleiades footprint data for screening. A tile can pass that check even if no single Airbus acquisition covers the whole tile, so full individual-acquisition coverage is checked again in Stage 2.



After download, visually check:



full raster coverage

cloud, haze, shadow

other obvious image problems



Keep tile\_id and season\_year throughout so imagery can be linked back to tree detections.



Tree outputs



tree\_locations.gpkg

One stable tree\_id + location for each tree.



tree\_observations.csv

One row per tree per season-year:

tile\_id, season\_year, tree\_id, detected



analysis\_output.py



Creates:



analysis\_tree\_observations.csv

analysis\_spatial.gpkg



Main settings are in config.py.

