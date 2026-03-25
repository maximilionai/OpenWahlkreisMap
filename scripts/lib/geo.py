"""Shared spatial processing functions for PLZ-to-constituency mapping."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

TARGET_CRS = "EPSG:25832"  # UTM zone 32N — standard for German federal geodata
OVERLAP_THRESHOLD = 0.01   # 1% — filter geometry slivers below this

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_plz_polygons(
    path: Path,
    *,
    expected_plz_min: int = 8000,
    expected_plz_max: int = 8200,
) -> gpd.GeoDataFrame:
    """Load PLZ boundary polygons from GeoJSON.

    Returns GeoDataFrame with columns: plz (str), geometry in EPSG:25832.
    """
    log.info("Loading PLZ polygons from %s ...", path)
    gdf = gpd.read_file(path)

    # Identify the PLZ column
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
    if not (expected_plz_min <= n_plz <= expected_plz_max):
        log.warning(
            "PLZ count %d outside expected range [%d, %d]",
            n_plz, expected_plz_min, expected_plz_max,
        )

    return gdf


def load_constituency_polygons(
    path: Path,
    *,
    fmt: str = "shapefile",
    col_map: Optional[dict] = None,
    expected_count: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """Load constituency boundary polygons from shapefile or GeoJSON.

    Args:
        path: Path to shapefile directory (for shapefile) or file (for geojson/gpkg).
        fmt: Format — "shapefile", "geojson", or "gpkg".
        col_map: Dict mapping source column names to canonical names (wk_nr, wk_name).
                 If None, auto-detects columns.
        expected_count: Expected number of constituencies. Exits on mismatch if set.

    Returns GeoDataFrame with columns: wk_nr (int), wk_name (str), geometry in EPSG:25832.
    """
    # Resolve file path
    if path.is_dir():
        # Search for geodata files in directory
        patterns = {
            "shapefile": ["*.shp"],
            "geojson": ["*.geojson", "*.json"],
            "gpkg": ["*.gpkg"],
            "gml": ["*.gml"],
        }
        search = patterns.get(fmt, ["*.shp", "*.geojson", "*.gml", "*.gpkg"])
        file_path = None
        for pattern in search:
            matches = list(path.glob(pattern))
            if matches:
                file_path = matches[0]
                break
        if file_path is None:
            log.error("No geodata file found in %s (format=%s)", path, fmt)
            sys.exit(1)
    else:
        file_path = path

    log.info("Loading constituency polygons from %s ...", file_path.name)
    gdf = gpd.read_file(file_path)
    log.info("Columns: %s", list(gdf.columns))

    # Apply column mapping
    if col_map:
        gdf = gdf.rename(columns=col_map)
    else:
        # Auto-detect columns (Bundestag-style heuristic)
        detected = {}
        for col in gdf.columns:
            col_lower = col.lower()
            if "wkr_nr" in col_lower or ("wahlkreis" in col_lower and "nr" in col_lower):
                detected[col] = "wk_nr"
            elif "wkr_name" in col_lower or ("wahlkreis" in col_lower and "name" in col_lower):
                detected[col] = "wk_name"
            elif col_lower in ("nr", "wkr_nr", "wk_nr"):
                detected[col] = "wk_nr"
            elif col_lower in ("name", "wkr_name", "wk_name"):
                detected[col] = "wk_name"

        if "wk_nr" not in detected.values():
            for col in gdf.columns:
                if col == "geometry":
                    continue
                if gdf[col].dtype in ("int64", "float64"):
                    max_val = 999 if expected_count is None else expected_count + 50
                    if gdf[col].between(1, max_val).all():
                        detected[col] = "wk_nr"
                        log.info("Auto-detected WK number column: %s", col)
                        break

        if "wk_name" not in detected.values():
            for col in gdf.columns:
                if col == "geometry" or col in detected:
                    continue
                if gdf[col].dtype == "object":
                    detected[col] = "wk_name"
                    log.info("Auto-detected WK name column: %s", col)
                    break

        if "wk_nr" not in detected.values() or "wk_name" not in detected.values():
            log.error(
                "Cannot identify constituency number and name columns.\n"
                "Available columns: %s\nDetected mapping: %s",
                list(gdf.columns), detected,
            )
            sys.exit(1)

        gdf = gdf.rename(columns=detected)

    gdf = gdf[["wk_nr", "wk_name", "geometry"]].copy()
    gdf["wk_nr"] = gdf["wk_nr"].astype(int)
    gdf["wk_name"] = gdf["wk_name"].astype(str)

    # Dissolve duplicate WK numbers (multipart features)
    if gdf["wk_nr"].duplicated().any():
        log.info("Dissolving %d duplicate WK entries", gdf["wk_nr"].duplicated().sum())
        gdf = gdf.dissolve(by="wk_nr", as_index=False, aggfunc="first")

    # Set CRS if missing (some WFS sources don't embed it)
    if gdf.crs is None:
        log.info("CRS not detected, assuming %s", TARGET_CRS)
        gdf = gdf.set_crs(TARGET_CRS)

    # Reproject
    gdf = gdf.to_crs(TARGET_CRS)

    # Repair invalid geometries
    invalid_mask = ~gdf.geometry.is_valid
    n_invalid = invalid_mask.sum()
    if n_invalid > 0:
        log.info("Repairing %d invalid constituency geometries", n_invalid)
        gdf.loc[invalid_mask, "geometry"] = gdf.loc[invalid_mask, "geometry"].make_valid()

    n_wk = len(gdf)
    log.info("Loaded %d constituencies", n_wk)
    if expected_count is not None and n_wk != expected_count:
        log.error("Expected %d constituencies, got %d", expected_count, n_wk)
        sys.exit(1)

    return gdf


# ---------------------------------------------------------------------------
# Spatial intersection
# ---------------------------------------------------------------------------

def compute_intersections(
    plz_gdf: gpd.GeoDataFrame,
    wk_gdf: gpd.GeoDataFrame,
    *,
    overlap_threshold: float = OVERLAP_THRESHOLD,
) -> pd.DataFrame:
    """Compute spatial overlay of PLZ and constituency polygons.

    Returns DataFrame with columns: plz, wk_nr, wk_name, overlap (0.0–1.0).
    """
    log.info("Computing spatial intersection (%d PLZ × %d WK)...", len(plz_gdf), len(wk_gdf))

    # Store original PLZ areas (aggregate duplicates)
    plz_areas = plz_gdf.groupby("plz")["geometry"].apply(lambda g: g.area.sum()).to_dict()

    # Compute intersection
    intersection = gpd.overlay(plz_gdf, wk_gdf, how="intersection")
    intersection["intersection_area"] = intersection.geometry.area

    # Calculate overlap as fraction of original PLZ area (vectorized)
    plz_area_series = intersection["plz"].map(plz_areas)
    intersection["overlap"] = intersection["intersection_area"] / plz_area_series

    result = intersection[["plz", "wk_nr", "wk_name", "overlap"]].copy()

    # Filter slivers below threshold
    below = result["overlap"] < overlap_threshold
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
                plz, overlap_threshold * 100,
                row.iloc[0]["wk_nr"], row.iloc[0]["overlap"],
            )
            row["overlap"] = 1.0
            rescue_rows.append(row)

    # Keep rows above threshold (excluding all-below PLZ)
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
        "Intersection complete: %d PLZ-WK pairs across %d PLZ",
        len(result), result["plz"].nunique(),
    )
    return result


def determine_primary(df: pd.DataFrame, period_id: int) -> dict:
    """Build mapping dict from intersection results.

    Returns dict keyed by PLZ string with:
      wahlkreise: [{nr, name, overlap}, ...]
      primary: int (WK with largest overlap; lower number wins ties)
      period_id: int
    """
    df_sorted = df.sort_values(["plz", "overlap", "wk_nr"], ascending=[True, False, True])

    mapping = {}
    for plz, group in df_sorted.groupby("plz", sort=False):
        wahlkreise = [
            {"nr": int(r.wk_nr), "name": r.wk_name, "overlap": float(r.overlap)}
            for r in group.itertuples(index=False)
        ]
        primary = wahlkreise[0]["nr"]

        mapping[plz] = {
            "wahlkreise": wahlkreise,
            "primary": primary,
            "period_id": period_id,
        }

    return mapping


# ---------------------------------------------------------------------------
# PLZ filtering
# ---------------------------------------------------------------------------

def filter_plz_by_bbox(
    plz_gdf: gpd.GeoDataFrame,
    constituency_gdf: gpd.GeoDataFrame,
    buffer_m: float = 5000,
) -> gpd.GeoDataFrame:
    """Filter PLZ to those within the buffered bounding box of constituencies.

    Uses PLZ centroids for the containment check.
    Returns filtered GeoDataFrame (subset of plz_gdf).
    """
    bbox = constituency_gdf.total_bounds  # (minx, miny, maxx, maxy)
    from shapely.geometry import box
    bbox_geom = box(
        bbox[0] - buffer_m, bbox[1] - buffer_m,
        bbox[2] + buffer_m, bbox[3] + buffer_m,
    )

    centroids = plz_gdf.geometry.centroid
    mask = centroids.within(bbox_geom)
    filtered = plz_gdf[mask].copy()

    log.info("Filtered PLZ by bbox: %d → %d (buffer=%dm)", len(plz_gdf), len(filtered), buffer_m)
    return filtered
