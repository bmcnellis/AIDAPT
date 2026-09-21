#!/usr/bin/env python3
# Make the list of dates that passed the date-level Landsat screen.

import json

import pandas as pd

import config as cfg


def main():
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(cfg.EXPORT_DIR.glob("date_contrast_*.json"))
    ]
    results = pd.DataFrame(rows)
    candidates = results[results["status"].eq("OK")][["date", "season_year"]].copy()
    candidates = candidates.sort_values("date").drop_duplicates()

    cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(cfg.OUTPUT_DIR / "candidate_dates.csv", index=False)
    print(f"Candidate dates: {len(candidates):,}")


if __name__ == "__main__":
    main()
