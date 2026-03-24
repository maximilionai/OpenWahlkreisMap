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

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent

RAW_PLZ_PATH = PROJECT_DIR / "raw" / "plz" / "plz-5stellig.geojson"
RAW_WK_PATH = PROJECT_DIR / "raw" / "bundestag"
OUTPUT_JSON_PATH = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.json"
OUTPUT_CSV_PATH = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.csv"

TARGET_CRS = "EPSG:25832"  # UTM zone 32N — standard for German federal geodata
OVERLAP_THRESHOLD = 0.01   # 1% — filter geometry slivers below this
EXPECTED_PLZ_MIN = 8000
EXPECTED_PLZ_MAX = 8200
EXPECTED_WK_COUNT = 299
PERIOD_ID = 161  # abgeordnetenwatch API parliament period for Bundestag 2025

SOURCES = [
    "Bundeswahlleiterin — Wahlkreiseinteilung BTW 2025 (public domain, §5 UrhG)",
    "yetzt/postleitzahlen — PLZ boundary polygons (ODbL)",
]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_plz_polygons(path: Path) -> gpd.GeoDataFrame:
    """Load PLZ boundary polygons from yetzt/postleitzahlen GeoJSON.

    Returns GeoDataFrame with columns: plz (str), geometry (Polygon/MultiPolygon)
    in EPSG:25832.
    """
    log.info("Loading PLZ polygons from %s ...", path)
    gdf = gpd.read_file(path)

    # Identify the PLZ column (yetzt uses 'plz')
    plz_col = None
    for candidate in ("plz", "PLZ", "postcode", "zipcode"):
        if candidate in gdf.columns:
            plz_col = candidate
            break
    if plz_col is None:
        log.error("Cannot find PLZ column. Available columns: %s", list(gdf.columns))
        sys.exit(1)

    gdf = gdf[[plz_col, "geometry"]].rename(columns={plz_col: "plz"})
    gdf["plz"] = gdf["plz"].astype(str).str.zfill(5)

    # Filter null/empty geometries (e.g., Postfach-PLZ)
    null_mask = gdf.geometry.is_empty | gdf.geometry.isna()
    if null_mask.any():
        dropped = gdf.loc[null_mask, "plz"].tolist()
        log.warning("Dropping %d PLZ with null/empty geometry: %s", len(dropped), dropped[:20])
        gdf = gdf[~null_mask].copy()

    # Reproject to metric CRS for area calculations
    gdf = gdf.to_crs(TARGET_CRS)

    # Repair invalid geometries
    invalid_mask = ~gdf.geometry.is_valid
    n_invalid = invalid_mask.sum()
    if n_invalid > 0:
        log.info("Repairing %d invalid geometries with make_valid()", n_invalid)
        gdf.loc[invalid_mask, "geometry"] = gdf.loc[invalid_mask, "geometry"].make_valid()

    n_plz = len(gdf)
    log.info("Loaded %d PLZ polygons", n_plz)
    if not (EXPECTED_PLZ_MIN <= n_plz <= EXPECTED_PLZ_MAX):
        log.warning(
            "PLZ count %d outside expected range [%d, %d]",
            n_plz, EXPECTED_PLZ_MIN, EXPECTED_PLZ_MAX,
        )

    return gdf


def load_wahlkreis_polygons(path: Path) -> gpd.GeoDataFrame:
    """Load Wahlkreis boundary polygons from Bundeswahlleiterin shapefiles.

    Returns GeoDataFrame with columns: wk_nr (int), wk_name (str), geometry
    in EPSG:25832.
    """
    # Find the .shp file in the directory
    shp_files = list(path.glob("*.shp"))
    if not shp_files:
        log.error("No .shp file found in %s", path)
        sys.exit(1)
    shp_file = shp_files[0]
    log.info("Loading Wahlkreis polygons from %s ...", shp_file.name)

    gdf = gpd.read_file(shp_file)
    log.info("Shapefile columns: %s", list(gdf.columns))

    # Map shapefile columns to canonical names
    # Bundeswahlleiterin uses various naming conventions — detect dynamically
    col_map = {}
    for col in gdf.columns:
        col_lower = col.lower()
        if "wkr_nr" in col_lower or "wahlkreis" in col_lower and "nr" in col_lower:
            col_map[col] = "wk_nr"
        elif "wkr_name" in col_lower or "wahlkreis" in col_lower and "name" in col_lower:
            col_map[col] = "wk_name"
        elif col_lower in ("nr", "wkr_nr", "wk_nr"):
            col_map[col] = "wk_nr"
        elif col_lower in ("name", "wkr_name", "wk_name"):
            col_map[col] = "wk_name"

    if "wk_nr" not in col_map.values():
        # Fallback: use first integer-like column
        for col in gdf.columns:
            if col == "geometry":
                continue
            if gdf[col].dtype in ("int64", "float64") and gdf[col].between(1, 299).all():
                col_map[col] = "wk_nr"
                log.info("Auto-detected WK number column: %s", col)
                break

    if "wk_name" not in col_map.values():
        # Fallback: use first string column that isn't already mapped
        for col in gdf.columns:
            if col == "geometry" or col in col_map:
                continue
            if gdf[col].dtype == "object":
                col_map[col] = "wk_name"
                log.info("Auto-detected WK name column: %s", col)
                break

    if "wk_nr" not in col_map.values() or "wk_name" not in col_map.values():
        log.error(
            "Cannot identify Wahlkreis number and name columns.\n"
            "Available columns: %s\nDetected mapping: %s",
            list(gdf.columns), col_map,
        )
        sys.exit(1)

    gdf = gdf.rename(columns=col_map)[["wk_nr", "wk_name", "geometry"]]
    gdf["wk_nr"] = gdf["wk_nr"].astype(int)
    gdf["wk_name"] = gdf["wk_name"].astype(str)

    # Reproject
    gdf = gdf.to_crs(TARGET_CRS)

    # Repair invalid geometries
    invalid_mask = ~gdf.geometry.is_valid
    n_invalid = invalid_mask.sum()
    if n_invalid > 0:
        log.info("Repairing %d invalid Wahlkreis geometries", n_invalid)
        gdf.loc[invalid_mask, "geometry"] = gdf.loc[invalid_mask, "geometry"].make_valid()

    n_wk = len(gdf)
    log.info("Loaded %d Wahlkreise", n_wk)
    if n_wk != EXPECTED_WK_COUNT:
        log.error("Expected %d Wahlkreise, got %d", EXPECTED_WK_COUNT, n_wk)
        sys.exit(1)

    return gdf


# ---------------------------------------------------------------------------
# Spatial intersection
# ---------------------------------------------------------------------------

def compute_intersections(
    plz_gdf: gpd.GeoDataFrame,
    wk_gdf: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Compute spatial overlay of PLZ and Wahlkreis polygons.

    Returns DataFrame with columns: plz, wk_nr, wk_name, overlap (0.0–1.0).
    Overlaps below OVERLAP_THRESHOLD are filtered as geometry slivers.
    Remaining overlaps are renormalized to sum to 1.0 per PLZ.
    """
    log.info("Computing spatial intersection (%d PLZ × %d WK)...", len(plz_gdf), len(wk_gdf))

    # Store original PLZ areas for percentage calculation (aggregate duplicates)
    plz_areas = plz_gdf.groupby("plz")["geometry"].apply(lambda g: g.area.sum()).to_dict()

    # Compute intersection
    intersection = gpd.overlay(plz_gdf, wk_gdf, how="intersection")
    intersection["intersection_area"] = intersection.geometry.area

    # Calculate overlap as fraction of original PLZ area (vectorized)
    plz_area_series = intersection["plz"].map(plz_areas)
    intersection["overlap"] = intersection["intersection_area"] / plz_area_series

    result = intersection[["plz", "wk_nr", "wk_name", "overlap"]].copy()

    # Filter slivers below threshold
    below = result["overlap"] < OVERLAP_THRESHOLD
    dropped = result[below]

    # Identify PLZ where ALL intersections are below threshold
    plz_all_below = set(dropped.groupby("plz").filter(
        lambda g: g["plz"].iloc[0] not in result[~below]["plz"].values
    )["plz"]) if below.any() else set()

    # For PLZ with all-below-threshold: keep only the largest intersection
    rescue_rows = []
    if plz_all_below:
        for plz in plz_all_below:
            group = result[result["plz"] == plz]
            idx = group["overlap"].idxmax()
            row = group.loc[[idx]].copy()
            log.warning(
                "PLZ %s: all overlaps below %.0f%% threshold, keeping largest (WK %d, %.4f)",
                plz, OVERLAP_THRESHOLD * 100,
                row.iloc[0]["wk_nr"], row.iloc[0]["overlap"],
            )
            row["overlap"] = 1.0
            rescue_rows.append(row)

    # Keep rows above threshold (excluding all-below PLZ, which are handled above)
    result = result[~below | result["plz"].isin(plz_all_below)]
    result = result[~result["plz"].isin(plz_all_below)]

    # Renormalize overlaps to sum to 1.0 per PLZ (vectorized)
    totals = result.groupby("plz")["overlap"].transform("sum")
    result = result.copy()
    result["overlap"] = result["overlap"] / totals

    # Add back rescued rows
    if rescue_rows:
        result = pd.concat([result] + rescue_rows, ignore_index=True)

    result["overlap"] = result["overlap"].round(6)
    result["wk_nr"] = result["wk_nr"].astype(int)

    log.info(
        "Intersection complete: %d PLZ-Wahlkreis pairs across %d PLZ",
        len(result), result["plz"].nunique(),
    )
    return result


def determine_primary(df: pd.DataFrame) -> dict:
    """Build mapping dict from intersection results.

    Returns dict keyed by PLZ string with:
      wahlkreise: [{nr, name, overlap}, ...]
      primary: int (WK with largest overlap; lower number wins ties)
      period_id: int
    """
    # Sort once for consistent ordering (descending overlap, ascending WK number)
    df_sorted = df.sort_values(["plz", "overlap", "wk_nr"], ascending=[True, False, True])

    mapping = {}
    for plz, group in df_sorted.groupby("plz", sort=False):
        wahlkreise = [
            {"nr": int(r.wk_nr), "name": r.wk_name, "overlap": float(r.overlap)}
            for r in group.itertuples(index=False)
        ]

        # Primary: largest overlap, tie-break by lower WK number (first in sorted order)
        primary = wahlkreise[0]["nr"]

        mapping[plz] = {
            "wahlkreise": wahlkreise,
            "primary": primary,
            "period_id": PERIOD_ID,
        }

    return mapping


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def write_json(mapping: dict, output_path: Path) -> None:
    """Write full plz-wahlkreis.json with meta block."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "meta": {
            "election": "BTW 2025",
            "constituencies": EXPECTED_WK_COUNT,
            "plz_count": len(mapping),
            "generated": date.today().isoformat(),
            "sources": SOURCES,
        },
        "data": mapping,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    log.info("Wrote JSON: %s (%d PLZ)", output_path, len(mapping))


def write_csv(mapping: dict, output_path: Path) -> None:
    """Write plz-wahlkreis.csv with one row per PLZ-Wahlkreis pair."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for plz, entry in sorted(mapping.items()):
        primary = entry["primary"]
        for wk in sorted(entry["wahlkreise"], key=lambda w: w["nr"]):
            rows.append({
                "plz": plz,
                "wahlkreis_nr": wk["nr"],
                "wahlkreis_name": wk["name"],
                "overlap": wk["overlap"],
                "is_primary": wk["nr"] == primary,
            })

    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    log.info("Wrote CSV: %s (%d rows)", output_path, len(df))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()

    # Load data
    plz_gdf = load_plz_polygons(RAW_PLZ_PATH)
    wk_gdf = load_wahlkreis_polygons(RAW_WK_PATH)

    # Compute intersections
    intersections = compute_intersections(plz_gdf, wk_gdf)

    # Build mapping with primary assignment
    mapping = determine_primary(intersections)

    # Write output
    write_json(mapping, OUTPUT_JSON_PATH)
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
    main()
