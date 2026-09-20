#!/usr/bin/env python3
# Export the final tree-by-season table and matching spatial layers.

import geopandas as gpd
import pandas as pd

import config as cfg


def main():
    tree_dir = cfg.OUTPUT_DIR / "tree_detection"
    observations = pd.read_csv(tree_dir / "tree_observations.csv")
    locations = gpd.read_file(tree_dir / "tree_locations.gpkg", layer="trees")

    observations = observations[["tile_id", "season_year", "tree_id", "detected"]].copy()
    observations = observations.sort_values(["tile_id", "tree_id", "season_year"])

    out_dir = cfg.OUTPUT_DIR / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    observations.to_csv(out_dir / "analysis_tree_observations.csv", index=False)

    locations = locations[["tile_id", "tree_id", "geometry"]].copy()
    spatial_obs = locations.merge(observations, on=["tile_id", "tree_id"], how="inner")
    spatial_obs = gpd.GeoDataFrame(spatial_obs, geometry="geometry", crs=locations.crs)

    spatial = out_dir / "analysis_spatial.gpkg"
    if spatial.exists():
        spatial.unlink()
    locations.to_file(spatial, layer="tree_locations", driver="GPKG")
    spatial_obs.to_file(spatial, layer="tree_observations", driver="GPKG", mode="a")

    print(f"Tree-season rows: {len(observations):,}")


if __name__ == "__main__":
    main()
