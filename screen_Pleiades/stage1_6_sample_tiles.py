#!/usr/bin/env python3
# Give each eligible tile a fixed random order.

import geopandas as gpd

import config as cfg


def random_order(tiles, seed):
    tiles = tiles.sort_values("tile_id").sample(frac=1, random_state=seed).reset_index(drop=True)
    tiles["random_order"] = range(1, len(tiles) + 1)
    return tiles


def save_order(tiles, name):
    out = cfg.OUTPUT_DIR / f"{name}_random_order.gpkg"
    if out.exists():
        out.unlink()
    tiles.to_file(out, layer="tiles", driver="GPKG")


def main():
    six = gpd.read_file(cfg.OUTPUT_DIR / "six_season_eligible.gpkg", layer="tiles")
    decade = gpd.read_file(cfg.OUTPUT_DIR / "decade_eligible.gpkg", layer="tiles")

    six = random_order(six, cfg.SIX_SEASON_SEED)
    decade = random_order(decade, cfg.DECADE_SEED)
    save_order(six, "six_season")
    save_order(decade, "decade")

    print(f"Six-season pool: {len(six):,}")
    print(f"2013/2023 pool: {len(decade):,}")


if __name__ == "__main__":
    main()
