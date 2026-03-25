"""Shared output generation functions for OpenWahlkreisMap."""

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def write_json(mapping: dict, output_path: Path, meta: dict) -> None:
    """Write plz-wahlkreis.json with meta block.

    Args:
        mapping: Dict keyed by PLZ with wahlkreise/primary/period_id.
        output_path: Where to write the JSON file.
        meta: Dict with election, constituencies, sources, etc.
              plz_count and generated are added automatically.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    full_meta = {
        **meta,
        "plz_count": len(mapping),
        "generated": date.today().isoformat(),
    }

    output = {
        "meta": full_meta,
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
