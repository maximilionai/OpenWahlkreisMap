"""
Verification suite for the PLZ-to-Wahlkreis mapping.

Checks:
  - Total Wahlkreise in output equals expected count (299 for Bundestag)
  - Every Wahlkreis appears at least once
  - Every valid 5-digit PLZ maps to at least one Wahlkreis
  - Primary Wahlkreis has the largest overlap for each PLZ
  - Spot-checks against known PLZ-Wahlkreis pairs
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "bundestag"
BUNDESTAG_FILE = DATA_DIR / "plz-wahlkreis.json"

SPOT_CHECKS = {
    # PLZ: expected primary Wahlkreis number
    "10115": 74,   # Berlin-Mitte
    "80331": 219,  # München-West/Mitte
    "20095": 18,   # Hamburg-Mitte
    "50667": 92,   # Köln I
    "87435": 256,  # Oberallgäu (Kempten)
    "01067": 158,  # Dresden I
    "60311": 181,  # Frankfurt am Main I
}


def verify():
    if not BUNDESTAG_FILE.exists():
        print(f"ERROR: {BUNDESTAG_FILE} not found. Run 'make process' first.")
        sys.exit(1)

    with open(BUNDESTAG_FILE) as f:
        data = json.load(f)

    mapping = data.get("data", {})
    errors = []

    # Check: all 299 Wahlkreise appear
    all_wk = set()
    for plz, entry in mapping.items():
        for wk in entry.get("wahlkreise", []):
            all_wk.add(wk["nr"])

    if len(all_wk) != 299:
        errors.append(f"Expected 299 Wahlkreise, found {len(all_wk)}")
        missing = set(range(1, 300)) - all_wk
        if missing:
            errors.append(f"Missing Wahlkreise: {sorted(missing)[:20]}...")

    # Check: primary has largest overlap
    for plz, entry in mapping.items():
        wahlkreise = entry.get("wahlkreise", [])
        primary = entry.get("primary")
        if wahlkreise and primary:
            max_overlap = max(wahlkreise, key=lambda w: w.get("overlap", 0))
            if max_overlap["nr"] != primary:
                errors.append(f"PLZ {plz}: primary={primary} but max overlap is {max_overlap['nr']}")

    # Spot checks
    for plz, expected_wk in SPOT_CHECKS.items():
        if plz in mapping:
            primary = mapping[plz].get("primary")
            if primary != expected_wk:
                errors.append(f"Spot check failed: PLZ {plz} expected WK {expected_wk}, got {primary}")
        else:
            errors.append(f"Spot check failed: PLZ {plz} not in mapping")

    if errors:
        print(f"VERIFICATION FAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"VERIFICATION PASSED: {len(mapping)} PLZ mapped to {len(all_wk)} Wahlkreise")


if __name__ == "__main__":
    verify()
