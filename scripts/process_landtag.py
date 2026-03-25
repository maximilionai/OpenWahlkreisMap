"""
Generic Landtag processor — config-driven PLZ-to-Wahlkreis mapping.

Supports three processing methods:
  - spatial: Polygon intersection (like Bundestag) for states with geodata
  - municipality_join: PLZ→AGS→Wahlkreis via VG250 municipality boundaries
  - manual: Hardcoded mapping from YAML config (for tiny states)

Usage:
  python3 scripts/process_landtag.py --build-plz-ags [--force]
  python3 scripts/process_landtag.py --state berlin
  python3 scripts/process_landtag.py --all
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from lib.geo import load_plz_polygons
from lib.municipality import build_plz_ags_mapping, load_plz_ags_mapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

RAW_PLZ_PATH = PROJECT_DIR / "raw" / "plz" / "plz-5stellig.geojson"
VG250_GEM_PATH = PROJECT_DIR / "raw" / "municipality" / "VG250_GEM.shp"
PLZ_AGS_CACHE = PROJECT_DIR / "raw" / "municipality" / "plz-ags-mapping.parquet"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_build_plz_ags(force: bool = False) -> None:
    """Build the PLZ-to-AGS mapping (one-time, shared across states)."""
    if PLZ_AGS_CACHE.exists() and not force:
        log.info("PLZ-AGS mapping already cached at %s", PLZ_AGS_CACHE)
        log.info("Use --force to rebuild.")
        return

    if not VG250_GEM_PATH.exists():
        log.error("VG250 Gemeinden shapefile not found at %s", VG250_GEM_PATH)
        log.error("Run 'make download-landtag' first.")
        sys.exit(1)

    t0 = time.time()
    plz_gdf = load_plz_polygons(RAW_PLZ_PATH)
    result = build_plz_ags_mapping(plz_gdf, VG250_GEM_PATH, PLZ_AGS_CACHE)

    # Validate
    n_plz = result["plz"].nunique()
    n_ags = result["ags"].nunique()
    bad_ags = result[result["ags"].str.len() != 8]
    elapsed = time.time() - t0

    log.info("")
    log.info("=== PLZ-AGS Mapping Summary ===")
    log.info("PLZ mapped:    %d", n_plz)
    log.info("Gemeinden:     %d", n_ags)
    log.info("Total pairs:   %d", len(result))
    log.info("Build time:    %.1f seconds", elapsed)

    if len(bad_ags) > 0:
        log.error("INVALID: %d rows with non-8-digit AGS codes", len(bad_ags))
        sys.exit(1)

    if n_plz < 8000:
        log.warning("Only %d PLZ mapped (expected ~8175) — some PLZ may be missing", n_plz)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Landtag PLZ-to-Wahlkreis processor")
    parser.add_argument("--build-plz-ags", action="store_true",
                        help="Build PLZ-AGS mapping from VG250")
    parser.add_argument("--force", action="store_true",
                        help="Force rebuild of cached data")
    parser.add_argument("--state", type=str,
                        help="Process a single state (slug from configs/landtag/)")
    parser.add_argument("--all", action="store_true",
                        help="Process all states")

    args = parser.parse_args()

    if args.build_plz_ags:
        cmd_build_plz_ags(force=args.force)
    elif args.state:
        log.error("--state not yet implemented (task 3hy.3)")
        sys.exit(1)
    elif args.all:
        log.error("--all not yet implemented (task 3hy.3)")
        sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
