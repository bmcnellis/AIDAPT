# AIDAPT: detecting and tracking paddock trees from satellite imagery

Yuqing Chen, Brandon McNellis, Michael Vardon

*Fenner School of Environment and Society, Australian National University,
Canberra, ACT, Australia*

AIDAPT measures change in the number of large scattered ("paddock") trees in
agricultural landscapes of the Australian Capital Territory and the South East NSW
Local Land Services region. Individual tree crowns are detected in 50 cm Pléiades
imagery with a YOLO object detector and then matched between dates, so that each
tree has a history rather than only a count. Two questions are addressed:

1. Can large paddock trees be detected and counted at landscape scale with a
   deep-learning object detector and high-resolution satellite imagery?
2. What is the level and rate of change in paddock tree numbers — persistence,
   loss and new appearance?

A paddock tree is defined operationally as a crown of at least 15 m diameter,
subject to landscape-context rules on distance to linear features and to tree
clusters.

**Status, 14 October 2026 (AEDT): this repository is incomplete and under active
development.** It currently holds the site-selection and covariate-extraction
material only; the detection, validation, and temporal-matching code is held
elsewhere and has not yet been added. The sections below say what is here and what
is not. Nothing in this repository should be taken as the analysis of record until
that code and the released data are in place.

## Analysis workflow

`meta/paddock_tree_detection_workflow_13102026.jpg` is the diagram of the full
analysis. Its six stages, and where each one stands in this repository, are:

| Stage | Step | Code in this repository |
|---|---|---|
| 1 | Training, validation and detection site selection: study area → eligible CLUM land use → eligible DEA land cover → Pléiades availability → training (10), validation (5) and detection (100) sites | Partly. The Landsat-contrast and Pléiades screening pipeline survives only in `archive/`; the covariate pulls in `GEE/` and `R/` support site stratification |
| 2 | Train YOLO on the 10 training sites: download and preprocess imagery, annotate crowns, train, select the best model | No |
| 3 | Quantify how image contrast affects detection and estimate the detectability correction | No |
| 4 | Validate the frozen model on the 5 independent validation sites (precision, recall, F1, spatial alignment; detectability-adjusted counts) | No |
| 5 | Detection: apply the final model to the 100-site longitudinal panel and store georeferenced detections with confidence scores | No |
| 6 | Temporal matching: match trees across years, calibrate the matching, classify persistent, lost and new trees, build contrast-adjusted tree histories | No |

The longitudinal panel is 100 × 1 km² sites in alternate years 2013–2025 (seven
dates). A separate 200-site endpoint panel was dropped on 7 October 2026.

## Repository layout

```
AIDAPT/
  GEE/      Google Earth Engine pulls of site covariates (DEM, NDVI, climate)
  R/        post-processing of the site table and of the NDVI pull
  data/     site bounding coordinates and the long-format site-by-image table
  meta/     the workflow diagram and a data dictionary for the GEE outputs
  archive/  code archive: zipped backups of superseded working code
```

`archive/` is a holding area, not part of the analysis. Its contents are snapshots
of earlier working code kept for reference and are not documented here.

| File | What it is |
|---|---|
| `GEE/GEE_functions.py` | Earth Engine helpers: elevation, slope and aspect statistics, monthly NDVI statistics, and the field lists and row builders for both outputs |
| `GEE/pull_GEE_DEM.py` | Per-site terrain statistics from the Geoscience Australia 1-second DEM-S |
| `GEE/pull_GEE_NDVI.py` | Per-site monthly NDVI, 2012–2025, from the Landsat 32-day NDVI composites |
| `GEE/pull_GEE_clim.py` | Per-site climate summaries — **incomplete, does not run** (see defects below) |
| `R/modify_long_format_sites.R` | Cleans `long_format_sites_20260527.csv` into `..._BM.csv`: normalises the QC notes, repairs one mis-typed date, and renames columns |
| `R/NDVI_summary.R` | Checks mean against median NDVI, plots each site's NDVI series, writes a tidied NDVI table |
| `data/bounding_coordinates_30_sites_20260526.csv` | 30 sites, bounding boxes in EPSG:4326 and EPSG:3577 |
| `data/long_format_sites_20260527.csv` | 1,506 site-by-image rows for those 30 sites, images 2012-11-06 to 2026-04-14, with free-text image QC notes |
| `data/long_format_sites_20260527_BM.csv` | The cleaned version produced by `R/modify_long_format_sites.R` |
| `meta/GEE_results_metadata_19052026.csv` | Column-level data dictionary for the GEE result tables |

The 30 sites in `data/` predate the 100-site longitudinal panel and are not that
panel; they are the sites used for the covariate and NDVI work.

## Data and service resources needed to run the analysis

### Hard data

| Resource | Needed by | Source and access | In this repository |
|---|---|---|---|
| Pléiades 50 cm imagery, November–February acquisitions, about 1,400 km² of 1 km² tiles | Stages 1, 2, 4, 5 | Airbus, purchased under licence. Not redistributable; the imagery budget is fully spent and committed to tiles already bought | No |
| Pléiades acquisition footprints, one shapefile per date (`per_date_shapefiles.zip`) | Stage 1 screening | Airbus catalogue | No |
| Study area boundary (`AOI.zip`) | Stage 1 screening | Project-defined, ACT and South East LLS region | No |
| CLUM agricultural land use raster (`inputs/CLUM_agri.tif`) | Stage 1 screening | ABARES Catchment Scale Land Use of Australia. The screening pipeline does not create it; it must be placed in `inputs/` | No |
| DEA Land Cover | Stage 1 site eligibility (woody cover exclusion) | Digital Earth Australia | No |
| Crown annotations for the 10 training sites | Stage 2 | Drawn in-project, by correcting detector pre-labels | No |
| Point labels and tree histories for the 5 validation sites | Stages 4 and 6 | Labelled in-project, independently of the training data | No |
| Trained YOLO weights | Stages 4 and 5 | Produced in Stage 2 | No |
| ACT 7.5 cm aerial imagery | Annotation aid only, for difficult crowns | ACT Government, free, ACT only | No |
| Site bounding coordinates and the site-by-image table | `GEE/`, `R/` | In `data/` | Yes |
| GEE result tables (DEM, NDVI, climate summaries) | `R/NDVI_summary.R` | Written by the `GEE/` scripts to a `results/` directory **outside** this repository | No |

### Cloud and API services

| Service | Used for | Access requirements |
|---|---|---|
| Google Earth Engine (Python `ee`, `geemap`) | `GEE/pull_GEE_*.py`: Geoscience Australia DEM-S (`AU/GA/DEM_1SEC/v10/DEM-S`), Landsat 32-day NDVI composites (`LANDSAT/COMPOSITES/C02/T1_L2_32DAY_NDVI`), and a climate collection still to be chosen | A registered Earth Engine account and a Cloud project. The scripts call `ee.Authenticate()` interactively and the project id is hard-coded as `ee-bmcnellis`, so another user must change it |
| Microsoft Planetary Computer STAC | Landsat 8 Collection 2 Level-2 Tier 1 scenes, read on demand by the archived screening pipeline for the NDVI contrast screen | Public STAC endpoint, no account; needs internet access and the `pystac-client`, `planetary-computer` and `odc-stac` packages |
| Airbus Pléiades catalogue (OneAtlas portal or API) | Looking up acquisition metadata and ordering imagery | A commercial Airbus account. The acquisition metadata review in the screening pipeline is a **manual** step: the script writes a review table and a person fills it in from the catalogue |
| GPU compute for YOLO training | Stage 2 | Not specified in this repository |

### Software

- Python 3.10 or newer. The GEE scripts need `earthengine-api` and `geemap`. The
  archived screening pipeline needs `geopandas` ≥ 1.0, `shapely` 2.x, `pandas`,
  `numpy`, `scipy`, `rasterio`, `affine`, `pystac`, `pystac-client`,
  `planetary-computer`, `odc-stac` (with `xarray` and `dask`), and `reportlab`,
  which it lists in its own `requirements.txt`.
- R with `dplyr` and `ggplot2`. `R/AIDAPT.Rproj` is an RStudio project file; the R
  scripts expect to be run with `R/` as the working directory.

## Known gaps

These are the sections a reader of the publication would expect and that are not
yet here:

1. No code for stages 2 to 6 — YOLO training, detection, accuracy assessment, the
   contrast/detectability correction, or temporal matching.
2. The screening pipeline of stage 1 exists only in `archive/`, not as live,
   runnable code in the repository tree. The two sampling designs it implements (a
   six-season design and a 2013/2023 "decade" design) are also superseded by the
   100-site alternate-year panel, so the archived code does not reproduce the
   current site selection.
3. No definition of the 100 detection sites, the 10 training sites or the 5
   validation sites; the only site table here is the earlier 30-site set.
4. No analysis outputs, figures or tables. Scripts write to a `results/` directory
   two levels above the repository root, which is outside version control.
5. No environment specification at the repository root (no `requirements.txt`,
   `environment.yml` or `renv.lock`), no `LICENSE`, and no `CITATION.cff`.
6. No data dictionary for the site tables in `data/`; the only dictionary,
   `meta/GEE_results_metadata_19052026.csv`, covers the GEE outputs, and is itself
   out of step with the code — it omits the `name`, `slope_mean_*` and
   `aspect_mean_*` columns that `GEE/GEE_functions.py` emits and documents
   `ndvi_change_*` columns that nothing currently produces.
7. No statement of what the code can and cannot be reused for. The approach
   transfers between regions but the trained model does not, and that statement is
   a planned deliverable in its own right.

## Known defects in the current code

Found by inspection on 14 October 2026 (AEDT). The syntax error and the broken
file paths have been repaired; the rest are open.

1. `GEE/pull_GEE_clim.py` is incomplete. `fieldnames` is used but never defined,
   the file still carries its `# TODO: need fieldnames` note, and the climate
   collection has not been chosen — `TODO.txt` weighs ERA5 (12 km, full series)
   against TerraClimate (4–5 km, no 2025). The empty monthly loop body that made
   the file a syntax error has been replaced with a `NotImplementedError`, so the
   script now parses and fails with that message if it is run.
2. `GEE/pull_GEE_NDVI.py` calls `make_ndvi_row(name, centroid, year, month, ndvi)`
   with five arguments against a six-parameter definition that expects
   `collection` second, so the call raises a `TypeError` and the `dataset` column
   would be wrong if it did not.
3. `GEE_functions.get_dem_stats()` computes the aspect statistics from the slope
   band: `calc_slp_asp_stats(slp, aoi, 'aspect', 30)` should pass `asp`. The
   reported `aspect_mean_rad` and `aspect_mean_deg` are therefore circular means
   of slope, not aspect.
4. The Earth Engine Cloud project (`ee-bmcnellis`) is hard-coded in all three pull
   scripts rather than read from configuration.
