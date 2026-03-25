"""State-specific data parsers for Landtag constituency data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


def parse_excel_generic(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse a state's Excel file using column mappings from YAML config.

    Args:
        path: Path to the Excel file.
        config: The 'excel' section of the state's YAML config, containing:
            sheet_name: Sheet name or index (default: 0)
            header_row: Row number for column headers (default: 0)
            wk_nr_col: Column name for Wahlkreis number
            wk_name_col: Column name for Wahlkreis name
            ags_col: Column name for AGS (Amtlicher Gemeindeschlüssel)

    Returns:
        DataFrame with columns: ags (8-digit str), wk_nr (int), wk_name (str)
    """
    excel_cfg = config.get("excel", {})
    sheet = excel_cfg.get("sheet_name", 0)
    header = excel_cfg.get("header_row", 0)

    log.info("Parsing Excel: %s (sheet=%s, header_row=%d)", path.name, sheet, header)
    df = pd.read_excel(path, sheet_name=sheet, header=header)
    log.info("Excel columns: %s (%d rows)", list(df.columns), len(df))

    wk_nr_col = excel_cfg.get("wk_nr_col")
    wk_name_col = excel_cfg.get("wk_name_col")
    ags_col = excel_cfg.get("ags_col")

    if not all([wk_nr_col, wk_name_col, ags_col]):
        log.error(
            "Excel config must specify wk_nr_col, wk_name_col, and ags_col. Got: %s",
            excel_cfg,
        )
        raise ValueError("Incomplete excel config — missing column names")

    # Select and rename columns
    result = df[[ags_col, wk_nr_col, wk_name_col]].copy()
    result.columns = ["ags", "wk_nr", "wk_name"]

    # Clean up
    result = result.dropna(subset=["ags", "wk_nr"])
    result["ags"] = result["ags"].astype(str).str.strip().str.zfill(8)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    # Deduplicate (same AGS may appear multiple times)
    result = result.drop_duplicates(subset=["ags"])

    log.info("Parsed %d AGS-to-WK entries (%d unique WK)", len(result), result["wk_nr"].nunique())
    return result


def parse_landkreis_prefix(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse a CSV mapping AGS prefixes (Landkreis level) to Wahlkreise.

    Used for states where constituencies = collections of Landkreise (e.g., Saarland).
    The CSV has columns: ags_prefix (5-digit), wk_nr, wk_name.
    Expands to all Gemeinde AGS codes that start with each prefix.
    """
    log.info("Parsing Landkreis-prefix CSV: %s", path.name)
    df = pd.read_csv(path, dtype=str)

    # Load full PLZ-AGS mapping to get all Gemeinde AGS codes
    from .municipality import load_plz_ags_mapping
    from pathlib import Path as P
    cache = P(__file__).parent.parent.parent / "raw" / "municipality" / "plz-ags-mapping.parquet"
    plz_ags = load_plz_ags_mapping(cache)

    rows = []
    for _, prefix_row in df.iterrows():
        prefix = prefix_row["ags_prefix"]
        wk_nr = int(prefix_row["wk_nr"])
        wk_name = prefix_row["wk_name"]
        # Find all unique AGS codes with this prefix
        matching = plz_ags[plz_ags["ags"].str.startswith(prefix)]["ags"].unique()
        for ags in matching:
            rows.append({"ags": ags, "wk_nr": wk_nr, "wk_name": wk_name})

    result = pd.DataFrame(rows).drop_duplicates(subset=["ags"])
    log.info("Expanded %d prefixes to %d AGS-to-WK entries (%d unique WK)",
             len(df), len(result), result["wk_nr"].nunique())
    return result


def get_parser(config: dict) -> callable:
    """Get the parser function for a state config.

    If config has a 'parser' field, look up a named parser function.
    Otherwise, use parse_excel_generic.
    """
    parser_name = config.get("parser")
    if parser_name:
        func = globals().get(f"parse_{parser_name}")
        if func is None:
            raise ValueError(f"Unknown parser: {parser_name} (expected parse_{parser_name} in parsers.py)")
        return func
    return parse_excel_generic
