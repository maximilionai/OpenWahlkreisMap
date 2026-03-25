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

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import yaml

from lib.geo import (
    compute_intersections,
    determine_primary,
    filter_plz_by_bbox,
    load_constituency_polygons,
    load_plz_polygons,
)
from lib.municipality import (
    build_plz_ags_mapping,
    join_plz_to_wahlkreis,
    load_plz_ags_mapping,
)
from lib.output import write_csv, write_json
from lib.parsers import get_parser

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

RAW_PLZ_PATH = PROJECT_DIR / "raw" / "plz" / "plz-5stellig.geojson"
VG250_GEM_PATH = PROJECT_DIR / "raw" / "municipality" / "VG250_GEM.shp"
PLZ_AGS_CACHE = PROJECT_DIR / "raw" / "municipality" / "plz-ags-mapping.parquet"
CONFIGS_DIR = PROJECT_DIR / "configs" / "landtag"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Cache PLZ GeoDataFrame across multiple state runs
_plz_gdf_cache = None


def get_plz_gdf():
    """Load PLZ GeoDataFrame (cached for multi-state runs)."""
    global _plz_gdf_cache
    if _plz_gdf_cache is None:
        _plz_gdf_cache = load_plz_polygons(RAW_PLZ_PATH)
    return _plz_gdf_cache


# ---------------------------------------------------------------------------
# Processing methods
# ---------------------------------------------------------------------------

def process_spatial(config: dict) -> dict:
    """Process a state using spatial intersection (Tier 1)."""
    state = config["state"]
    raw_dir = PROJECT_DIR / "raw" / "landtag" / config["download"]["raw_subdir"]

    # Load constituency polygons
    col_map = config.get("columns")
    # Convert null values to None for auto-detection
    if col_map and all(v is None for v in col_map.values()):
        col_map = None

    wk_gdf = load_constituency_polygons(
        raw_dir,
        fmt=config["download"].get("format", "shapefile"),
        col_map=col_map,
        expected_count=config["expected_wk_count"],
    )

    # Filter PLZ to state bounding box
    plz_gdf = get_plz_gdf()
    state_plz = filter_plz_by_bbox(plz_gdf, wk_gdf)

    # Compute intersections
    intersections = compute_intersections(state_plz, wk_gdf)

    # Build mapping
    mapping = determine_primary(intersections, config["period_id"])
    return mapping


def process_municipality_join(config: dict) -> dict:
    """Process a state using municipality join (Tier 2)."""
    state = config["state"]
    raw_dir = PROJECT_DIR / "raw" / "landtag" / config["download"]["raw_subdir"]

    # Load PLZ-AGS mapping
    if not PLZ_AGS_CACHE.exists():
        raise RuntimeError("PLZ-AGS mapping not found. Run: make process-landtag-plz-ags")
    plz_ags_df = load_plz_ags_mapping(PLZ_AGS_CACHE)

    # Parse state's constituency-municipality data
    data_format = config["download"].get("format", "excel")
    if data_format == "excel":
        excel_files = list(raw_dir.glob("*.xlsx")) + list(raw_dir.glob("*.xls"))
        if not excel_files:
            raise FileNotFoundError(f"No Excel file found in {raw_dir}")
        parser = get_parser(config)
        ags_wk_lookup = parser(excel_files[0], config)
    elif data_format == "csv":
        csv_files = list(raw_dir.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No CSV file found in {raw_dir}")
        parser = get_parser(config)
        ags_wk_lookup = parser(csv_files[0], config)
    else:
        raise ValueError(f"Unsupported format for municipality_join: {data_format}")

    # Filter PLZ-AGS to this state's AGS codes
    state_ags = set(ags_wk_lookup["ags"])
    state_plz_ags = plz_ags_df[plz_ags_df["ags"].isin(state_ags)].copy()

    if len(state_plz_ags) == 0:
        raise RuntimeError(f"No PLZ-AGS matches for state {state} — check AGS format")

    # Join PLZ → AGS → Wahlkreis
    mapping = join_plz_to_wahlkreis(state_plz_ags, ags_wk_lookup, config["period_id"])
    return mapping


def process_manual(config: dict) -> dict:
    """Process a state using hardcoded manual mapping from config."""
    manual = config.get("manual_mapping", [])
    if not manual:
        raise ValueError(f"No manual_mapping in config for state {config['state']}")

    mapping = {}
    for entry in manual:
        wk_nr = entry["wk_nr"]
        wk_name = entry["wk_name"]
        for plz in entry["plz"]:
            plz = str(plz).zfill(5)
            if plz in mapping:
                # PLZ already assigned — add this WK
                mapping[plz]["wahlkreise"].append({
                    "nr": wk_nr, "name": wk_name, "overlap": 0.0,
                })
            else:
                mapping[plz] = {
                    "wahlkreise": [{"nr": wk_nr, "name": wk_name, "overlap": 1.0}],
                    "primary": wk_nr,
                    "period_id": config["period_id"],
                }

    # For PLZ in multiple WK, set equal overlap and pick primary (lowest nr)
    for plz, entry in mapping.items():
        if len(entry["wahlkreise"]) > 1:
            n = len(entry["wahlkreise"])
            for wk in entry["wahlkreise"]:
                wk["overlap"] = round(1.0 / n, 6)
            entry["primary"] = min(wk["nr"] for wk in entry["wahlkreise"])

    log.info("Manual mapping: %d PLZ → %d Wahlkreise",
             len(mapping), len({wk["nr"] for e in mapping.values() for wk in e["wahlkreise"]}))
    return mapping


# ---------------------------------------------------------------------------
# State processing orchestration
# ---------------------------------------------------------------------------

def load_config(state_slug: str) -> dict:
    """Load YAML config for a state."""
    config_path = CONFIGS_DIR / f"{state_slug}.yaml"
    if not config_path.exists():
        log.error("Config not found: %s", config_path)
        log.info("Available configs: %s", [p.stem for p in CONFIGS_DIR.glob("*.yaml")])
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def process_state(state_slug: str) -> bool:
    """Process a single state. Returns True on success."""
    config = load_config(state_slug)
    state = config["state"]
    method = config["method"]

    log.info("")
    log.info("=" * 60)
    log.info("Processing %s (%s, method=%s, %d WK expected)",
             config["state_name"], config.get("parliament", "Landtag"),
             method, config["expected_wk_count"])
    log.info("=" * 60)

    t0 = time.time()

    # Dispatch by method
    if method == "spatial":
        mapping = process_spatial(config)
    elif method == "municipality_join":
        mapping = process_municipality_join(config)
    elif method == "manual":
        mapping = process_manual(config)
    else:
        log.error("Unknown method: %s", method)
        return False

    # Write output
    output_dir = PROJECT_DIR / "data" / "landtag" / state
    meta = {
        "election": config["election"],
        "constituencies": config["expected_wk_count"],
        "sources": config.get("sources", []),
    }
    write_json(mapping, output_dir / "plz-wahlkreis.json", meta)
    write_csv(mapping, output_dir / "plz-wahlkreis.csv")

    # Summary
    elapsed = time.time() - t0
    n_plz = len(mapping)
    all_wk = {wk["nr"] for entry in mapping.values() for wk in entry["wahlkreise"]}
    multi_wk = sum(1 for entry in mapping.values() if len(entry["wahlkreise"]) > 1)

    log.info("")
    log.info("--- %s Summary ---", config["state_name"])
    log.info("PLZ processed:     %d", n_plz)
    log.info("Wahlkreise covered: %d / %d", len(all_wk), config["expected_wk_count"])
    log.info("Multi-assignment:  %d PLZ", multi_wk)
    log.info("Processing time:   %.1f seconds", elapsed)

    if len(all_wk) != config["expected_wk_count"]:
        log.warning("WARNING: Expected %d WK, got %d", config["expected_wk_count"], len(all_wk))
        return False

    return True


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
    plz_gdf = get_plz_gdf()
    result = build_plz_ags_mapping(plz_gdf, VG250_GEM_PATH, PLZ_AGS_CACHE)

    # Validate
    n_plz = result["plz"].nunique()
    bad_ags = result[result["ags"].str.len() != 8]
    elapsed = time.time() - t0

    log.info("")
    log.info("=== PLZ-AGS Mapping Summary ===")
    log.info("PLZ mapped:    %d", n_plz)
    log.info("Gemeinden:     %d", result["ags"].nunique())
    log.info("Total pairs:   %d", len(result))
    log.info("Build time:    %.1f seconds", elapsed)

    if len(bad_ags) > 0:
        log.error("INVALID: %d rows with non-8-digit AGS codes", len(bad_ags))
        sys.exit(1)


def cmd_process_all() -> None:
    """Process all states with configs."""
    configs = sorted(CONFIGS_DIR.glob("*.yaml"))
    if not configs:
        log.error("No configs found in %s", CONFIGS_DIR)
        sys.exit(1)

    log.info("Found %d state configs", len(configs))
    results = {}

    for config_path in configs:
        slug = config_path.stem
        try:
            success = process_state(slug)
            results[slug] = "OK" if success else "WARN"
        except Exception as e:
            log.error("FAILED: %s — %s", slug, e)
            results[slug] = "FAIL"

    # Print summary
    log.info("")
    log.info("=" * 60)
    log.info("=== All States Summary ===")
    for slug, status in sorted(results.items()):
        icon = "✓" if status == "OK" else "⚠" if status == "WARN" else "✗"
        log.info("  %s %s: %s", icon, slug, status)

    n_ok = sum(1 for s in results.values() if s == "OK")
    n_fail = sum(1 for s in results.values() if s != "OK")
    log.info("")
    log.info("Completed: %d/%d succeeded, %d failed", n_ok, len(results), n_fail)

    if n_fail > 0:
        sys.exit(1)


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
                        help="Process all states with configs")

    args = parser.parse_args()

    if args.build_plz_ags:
        cmd_build_plz_ags(force=args.force)
    elif args.state:
        success = process_state(args.state)
        if not success:
            sys.exit(1)
    elif args.all:
        cmd_process_all()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
