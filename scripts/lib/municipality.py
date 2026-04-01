"""PLZ-to-municipality (AGS) mapping and municipality-join processing."""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .geo import TARGET_CRS, OVERLAP_THRESHOLD

log = logging.getLogger(__name__)


def build_plz_ags_mapping(
    plz_gdf: gpd.GeoDataFrame,
    vg250_path: Path,
    cache_path: Path,
) -> pd.DataFrame:
    """Build PLZ-to-AGS mapping via spatial intersection.

    Intersects PLZ polygons with VG250 Gemeinden boundaries to produce
    a mapping from PLZ to AGS (Amtlicher Gemeindeschlüssel) codes with
    overlap percentages.

    Args:
        plz_gdf: PLZ GeoDataFrame (from load_plz_polygons).
        vg250_path: Path to VG250_GEM.shp file.
        cache_path: Where to write/read the parquet cache.

    Returns:
        DataFrame with columns: plz (str), ags (str, 8-digit), gem_name (str), overlap (float).
    """
    log.info("Building PLZ-AGS mapping via spatial intersection...")
    log.info("Loading VG250 Gemeinden from %s ...", vg250_path)

    gem_gdf = gpd.read_file(vg250_path)
    log.info("VG250 columns: %s", list(gem_gdf.columns))

    # Keep only relevant columns — AGS and GEN (Gemeinde name)
    gem_gdf = gem_gdf[["AGS", "GEN", "geometry"]].copy()
    gem_gdf = gem_gdf.rename(columns={"AGS": "ags", "GEN": "gem_name"})

    # Normalize AGS to 8-digit zero-padded string
    gem_gdf["ags"] = gem_gdf["ags"].astype(str).str.zfill(8)

    # Ensure same CRS
    if gem_gdf.crs != plz_gdf.crs:
        gem_gdf = gem_gdf.to_crs(TARGET_CRS)

    # Filter out empty/null geometries
    null_mask = gem_gdf.geometry.is_empty | gem_gdf.geometry.isna()
    if null_mask.any():
        log.warning("Dropping %d Gemeinden with null geometry", null_mask.sum())
        gem_gdf = gem_gdf[~null_mask].copy()

    # Repair invalid geometries
    invalid_mask = ~gem_gdf.geometry.is_valid
    if invalid_mask.any():
        log.info("Repairing %d invalid Gemeinde geometries", invalid_mask.sum())
        gem_gdf.loc[invalid_mask, "geometry"] = gem_gdf.loc[invalid_mask, "geometry"].make_valid()

    log.info("Loaded %d Gemeinden", len(gem_gdf))

    # Store original PLZ areas
    plz_areas = plz_gdf.groupby("plz")["geometry"].apply(lambda g: g.area.sum()).to_dict()

    # Compute spatial intersection
    log.info("Computing PLZ × Gemeinden intersection (%d × %d)...", len(plz_gdf), len(gem_gdf))
    intersection = gpd.overlay(plz_gdf, gem_gdf, how="intersection")
    intersection["intersection_area"] = intersection.geometry.area

    # Calculate overlap as fraction of PLZ area
    plz_area_series = intersection["plz"].map(plz_areas)
    intersection["overlap"] = intersection["intersection_area"] / plz_area_series

    result = intersection[["plz", "ags", "gem_name", "overlap"]].copy()
    result["overlap"] = result["overlap"].round(6)

    log.info(
        "PLZ-AGS mapping: %d pairs across %d PLZ and %d Gemeinden",
        len(result), result["plz"].nunique(), result["ags"].nunique(),
    )

    # Write cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache_path, index=False)
    log.info("Cached PLZ-AGS mapping to %s", cache_path)

    return result


def load_plz_ags_mapping(cache_path: Path) -> pd.DataFrame:
    """Load cached PLZ-AGS mapping from parquet."""
    log.info("Loading PLZ-AGS mapping from %s", cache_path)
    return pd.read_parquet(cache_path)


def join_plz_to_wahlkreis(
    plz_ags_df: pd.DataFrame,
    ags_wk_lookup: pd.DataFrame,
    period_id: int,
) -> dict:
    """Join PLZ-AGS mapping with state's AGS-to-Wahlkreis lookup.

    Args:
        plz_ags_df: DataFrame with columns plz, ags, overlap (from PLZ-AGS mapping,
                    filtered to this state's AGS codes).
        ags_wk_lookup: DataFrame with columns ags (8-digit str), wk_nr (int), wk_name (str).
        period_id: abgeordnetenwatch parliament period ID.

    Returns:
        Mapping dict keyed by PLZ, same format as determine_primary() output.
    """
    # Join PLZ-AGS with AGS-WK
    merged = plz_ags_df.merge(ags_wk_lookup, on="ags", how="inner")

    if len(merged) == 0:
        log.warning("No matches found in PLZ-AGS to WK join — check AGS format compatibility")
        return {}

    # Aggregate overlaps per PLZ-Wahlkreis pair
    # (multiple municipalities in the same WK → sum their overlaps)
    grouped = merged.groupby(["plz", "wk_nr", "wk_name"])["overlap"].sum().reset_index()

    # Renormalize per PLZ so overlaps sum to 1.0
    totals = grouped.groupby("plz")["overlap"].transform("sum")
    grouped["overlap"] = grouped.apply(
        lambda row: round(row["overlap"] / totals[row.name], 6)
        if totals[row.name] > 0
        else round(1.0 / (grouped["plz"] == row["plz"]).sum(), 6),
        axis=1,
    )

    # Build mapping dict (same format as geo.determine_primary)
    grouped_sorted = grouped.sort_values(
        ["plz", "overlap", "wk_nr"], ascending=[True, False, True]
    )

    mapping = {}
    for plz, grp in grouped_sorted.groupby("plz", sort=False):
        wahlkreise = [
            {"nr": int(r.wk_nr), "name": r.wk_name, "overlap": float(r.overlap)}
            for r in grp.itertuples(index=False)
        ]
        primary = wahlkreise[0]["nr"]

        mapping[plz] = {
            "wahlkreise": wahlkreise,
            "primary": primary,
            "period_id": period_id,
        }

    log.info("Municipality join: %d PLZ → %d Wahlkreise", len(mapping),
             len({wk["nr"] for e in mapping.values() for wk in e["wahlkreise"]}))

    return mapping
