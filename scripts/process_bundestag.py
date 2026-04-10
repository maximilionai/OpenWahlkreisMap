"""
Process raw geodata into PLZ-to-Wahlkreis mapping for Bundestag.

Algorithm (Method B — spatial intersection):
  1. Load PLZ boundary polygons (from yetzt/postleitzahlen GeoJSON)
  2. Load Wahlkreis boundary polygons (from Bundeswahlleiterin shapefiles)
  3. Compute spatial intersection of all PLZ × Wahlkreis polygon pairs
  4. Calculate area overlap percentage for each intersection
  5. Filter geometry slivers (<1% overlap), renormalize
  6. Output JSON and CSV

Requirements: geopandas, shapely, pandas
"""

import logging
import sys
import time
from pathlib import Path

from lib.errors import DataPipelineError
from lib.geo import (
    compute_intersections,
    determine_primary,
    load_constituency_polygons,
    load_plz_polygons,
)
from lib.output import write_csv, write_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

RAW_PLZ_PATH = PROJECT_DIR / "raw" / "plz" / "plz-5stellig.geojson"
RAW_WK_PATH = PROJECT_DIR / "raw" / "bundestag"
OUTPUT_JSON_PATH = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.json"
OUTPUT_CSV_PATH = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.csv"

EXPECTED_WK_COUNT = 299
PERIOD_ID = 161  # abgeordnetenwatch API parliament period for Bundestag 2025

META = {
    "election": "BTW 2025",
    "constituencies": EXPECTED_WK_COUNT,
    "sources": [
        "Bundeswahlleiterin — Wahlkreiseinteilung BTW 2025 (public domain, §5 UrhG)",
        "yetzt/postleitzahlen — PLZ boundary polygons (ODbL)",
    ],
}

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()

    # Load data
    plz_gdf = load_plz_polygons(RAW_PLZ_PATH)
    wk_gdf = load_constituency_polygons(RAW_WK_PATH, expected_count=EXPECTED_WK_COUNT)

    # Compute intersections
    intersections = compute_intersections(plz_gdf, wk_gdf)

    # Build mapping with primary assignment
    mapping = determine_primary(intersections, PERIOD_ID)

    # Write output
    write_json(mapping, OUTPUT_JSON_PATH, META)
    write_csv(mapping, OUTPUT_CSV_PATH)

    # Summary
    elapsed = time.time() - t0
    n_plz = len(mapping)
    all_wk = {wk["nr"] for entry in mapping.values() for wk in entry["wahlkreise"]}
    multi_wk = sum(1 for entry in mapping.values() if len(entry["wahlkreise"]) > 1)

    log.info("")
    log.info("=== Summary ===")
    log.info("PLZ processed:     %d", n_plz)
    log.info("Wahlkreise covered: %d / %d", len(all_wk), EXPECTED_WK_COUNT)
    log.info("Multi-assignment:  %d PLZ (%.1f%%)", multi_wk, 100 * multi_wk / n_plz if n_plz else 0)
    log.info("Processing time:   %.1f seconds", elapsed)


if __name__ == "__main__":
    try:
        main()
    except DataPipelineError as exc:
        log.error("%s", exc)
        sys.exit(1)
