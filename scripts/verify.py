"""
Verification suite for the PLZ-to-Wahlkreis mapping.

Checks:
  1. All 299 Wahlkreise are covered
  2. PLZ count is in expected range (8,000–8,200)
  3. Primary Wahlkreis has the largest overlap for each PLZ
  4. Overlap sums are approximately 1.0 for each PLZ
  5. Expected samples from tests/expected_samples.json all match
  6. CSV output exists and is consistent with JSON
"""

import csv
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
DATA_DIR = PROJECT_DIR / "data" / "bundestag"
BUNDESTAG_JSON = DATA_DIR / "plz-wahlkreis.json"
BUNDESTAG_CSV = DATA_DIR / "plz-wahlkreis.csv"
EXPECTED_SAMPLES = PROJECT_DIR / "tests" / "expected_samples.json"

EXPECTED_WK_COUNT = 299
EXPECTED_PLZ_MIN = 8000
EXPECTED_PLZ_MAX = 8200
OVERLAP_SUM_TOLERANCE = 0.02


def check_passed(num: int, name: str) -> None:
    print(f"  ✓ Check {num}: {name}")


def check_failed(num: int, name: str, detail: str) -> str:
    msg = f"Check {num}: {name} — {detail}"
    print(f"  ✗ {msg}")
    return msg


def verify():
    errors = []

    # -------------------------------------------------------------------
    # Load JSON
    # -------------------------------------------------------------------
    if not BUNDESTAG_JSON.exists():
        print(f"ERROR: {BUNDESTAG_JSON} not found. Run 'make process' first.")
        sys.exit(1)

    with open(BUNDESTAG_JSON, encoding="utf-8") as f:
        data = json.load(f)

    mapping = data.get("data", {})
    print(f"Loaded {len(mapping)} PLZ entries from {BUNDESTAG_JSON.name}")
    print()

    # -------------------------------------------------------------------
    # Check 1: All 299 Wahlkreise covered
    # -------------------------------------------------------------------
    all_wk = set()
    for entry in mapping.values():
        for wk in entry.get("wahlkreise", []):
            all_wk.add(wk["nr"])

    missing_wk = set(range(1, EXPECTED_WK_COUNT + 1)) - all_wk
    if missing_wk:
        errors.append(check_failed(
            1, "All 299 Wahlkreise covered",
            f"Missing {len(missing_wk)} Wahlkreise: {sorted(missing_wk)[:20]}"
        ))
    else:
        check_passed(1, f"All {EXPECTED_WK_COUNT} Wahlkreise covered")

    # -------------------------------------------------------------------
    # Check 2: PLZ count in range
    # -------------------------------------------------------------------
    n_plz = len(mapping)
    if EXPECTED_PLZ_MIN <= n_plz <= EXPECTED_PLZ_MAX:
        check_passed(2, f"PLZ count {n_plz} in range [{EXPECTED_PLZ_MIN}, {EXPECTED_PLZ_MAX}]")
    else:
        errors.append(check_failed(
            2, "PLZ count in expected range",
            f"Got {n_plz}, expected [{EXPECTED_PLZ_MIN}, {EXPECTED_PLZ_MAX}]"
        ))

    # -------------------------------------------------------------------
    # Check 3: Primary has largest overlap
    # -------------------------------------------------------------------
    primary_errors = []
    for plz, entry in mapping.items():
        wahlkreise = entry.get("wahlkreise", [])
        primary = entry.get("primary")
        if wahlkreise and primary is not None:
            max_overlap = max(wk["overlap"] for wk in wahlkreise)
            primary_overlap = next(
                (wk["overlap"] for wk in wahlkreise if wk["nr"] == primary), 0
            )
            if primary_overlap < max_overlap:
                max_wk = max(wahlkreise, key=lambda w: w["overlap"])
                primary_errors.append(
                    f"PLZ {plz}: primary={primary} (overlap={primary_overlap}) "
                    f"but WK {max_wk['nr']} has overlap={max_wk['overlap']}"
                )

    if primary_errors:
        errors.append(check_failed(
            3, "Primary has largest overlap",
            f"{len(primary_errors)} failures: {primary_errors[0]}"
        ))
    else:
        check_passed(3, "Primary has largest overlap for all PLZ")

    # -------------------------------------------------------------------
    # Check 4: Overlap sums ≈ 1.0
    # -------------------------------------------------------------------
    overlap_errors = []
    for plz, entry in mapping.items():
        wahlkreise = entry.get("wahlkreise", [])
        overlap_sum = sum(wk["overlap"] for wk in wahlkreise)
        if abs(overlap_sum - 1.0) > OVERLAP_SUM_TOLERANCE:
            overlap_errors.append(f"PLZ {plz}: sum={overlap_sum:.4f}")

    if overlap_errors:
        errors.append(check_failed(
            4, "Overlap sums ≈ 1.0",
            f"{len(overlap_errors)} PLZ out of tolerance: {overlap_errors[:5]}"
        ))
    else:
        check_passed(4, f"Overlap sums within {OVERLAP_SUM_TOLERANCE} of 1.0 for all PLZ")

    # -------------------------------------------------------------------
    # Check 5: Expected samples
    # -------------------------------------------------------------------
    if not EXPECTED_SAMPLES.exists():
        errors.append(check_failed(
            5, "Expected samples",
            f"File not found: {EXPECTED_SAMPLES}"
        ))
    else:
        with open(EXPECTED_SAMPLES, encoding="utf-8") as f:
            samples = json.load(f)

        sample_errors = []
        for sample in samples:
            plz = sample["plz"]
            expected_nr = sample["wahlkreis_nr"]
            if plz not in mapping:
                sample_errors.append(f"PLZ {plz} not in mapping")
            else:
                actual_primary = mapping[plz].get("primary")
                if actual_primary != expected_nr:
                    sample_errors.append(
                        f"PLZ {plz} ({sample.get('bundesland', '?')}): "
                        f"expected WK {expected_nr}, got {actual_primary}"
                    )

        if sample_errors:
            errors.append(check_failed(
                5, "Expected samples",
                f"{len(sample_errors)}/{len(samples)} mismatches: {sample_errors[0]}"
            ))
        else:
            check_passed(5, f"All {len(samples)} expected samples match")

    # -------------------------------------------------------------------
    # Check 6: CSV consistency
    # -------------------------------------------------------------------
    if not BUNDESTAG_CSV.exists():
        errors.append(check_failed(
            6, "CSV output",
            f"File not found: {BUNDESTAG_CSV}"
        ))
    else:
        with open(BUNDESTAG_CSV, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_columns = reader.fieldnames or []
            csv_rows = list(reader)

        expected_columns = {"plz", "wahlkreis_nr", "wahlkreis_name", "overlap", "is_primary"}
        actual_columns = set(csv_columns)
        if not expected_columns.issubset(actual_columns):
            missing_cols = expected_columns - actual_columns
            errors.append(check_failed(
                6, "CSV columns",
                f"Missing columns: {missing_cols}"
            ))
        else:
            # Count total PLZ-Wahlkreis pairs in JSON
            json_pairs = sum(len(entry["wahlkreise"]) for entry in mapping.values())
            csv_pair_count = len(csv_rows)

            if csv_pair_count != json_pairs:
                errors.append(check_failed(
                    6, "CSV row count",
                    f"CSV has {csv_pair_count} rows, JSON has {json_pairs} pairs"
                ))
            else:
                check_passed(6, f"CSV consistent: {csv_pair_count} rows, correct columns")

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print()
    if errors:
        print(f"VERIFICATION FAILED ({len(errors)} error(s))")
        sys.exit(1)
    else:
        print(f"VERIFICATION PASSED: {n_plz} PLZ → {len(all_wk)} Wahlkreise")


if __name__ == "__main__":
    verify()
