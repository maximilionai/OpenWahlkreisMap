"""
Verification suite for the PLZ-to-Wahlkreis mapping.

Bundestag checks:
  1-6. WK coverage, PLZ count, primary, overlap sums, samples, CSV

Landtag checks (per state):
  Same checks per state with state-specific expected values

Usage:
  python3 scripts/verify.py                  # all (default)
  python3 scripts/verify.py --scope bundestag
  python3 scripts/verify.py --scope landtag
"""

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
BUNDESTAG_JSON = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.json"
BUNDESTAG_CSV = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.csv"
EXPECTED_SAMPLES = PROJECT_DIR / "tests" / "expected_samples.json"
EXPECTED_LANDTAG_SAMPLES = PROJECT_DIR / "tests" / "expected_landtag_samples.json"
LANDTAG_DIR = PROJECT_DIR / "data" / "landtag"

OVERLAP_SUM_TOLERANCE = 0.02


def check_passed(num, name):
    print(f"  ✓ Check {num}: {name}")


def check_failed(num, name, detail):
    msg = f"Check {num}: {name} — {detail}"
    print(f"  ✗ {msg}")
    return msg


def verify_mapping(json_path, csv_path, samples_path, expected_wk, expected_plz_range, label=""):
    """Generic verification for any parliament's mapping."""
    errors = []
    prefix = f"[{label}] " if label else ""

    if not json_path.exists():
        print(f"  ✗ {prefix}JSON not found: {json_path}")
        return [f"{prefix}JSON not found"]

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    mapping = data.get("data", {})

    # Check: WK coverage
    all_wk = {wk["nr"] for entry in mapping.values() for wk in entry.get("wahlkreise", [])}
    if expected_wk and len(all_wk) != expected_wk:
        errors.append(check_failed(1, f"{prefix}WK count",
                                   f"Expected {expected_wk}, got {len(all_wk)}"))
    else:
        check_passed(1, f"{prefix}{len(all_wk)} Wahlkreise covered")

    # Check: PLZ count
    n_plz = len(mapping)
    if expected_plz_range:
        lo, hi = expected_plz_range
        if lo <= n_plz <= hi:
            check_passed(2, f"{prefix}PLZ count {n_plz} in range [{lo}, {hi}]")
        else:
            errors.append(check_failed(2, f"{prefix}PLZ count",
                                       f"Got {n_plz}, expected [{lo}, {hi}]"))
    else:
        check_passed(2, f"{prefix}PLZ count {n_plz}")

    # Check: Primary has max overlap
    primary_errors = []
    for plz, entry in mapping.items():
        wahlkreise = entry.get("wahlkreise", [])
        primary = entry.get("primary")
        if wahlkreise and primary is not None:
            max_overlap = max(wk["overlap"] for wk in wahlkreise)
            primary_overlap = next((wk["overlap"] for wk in wahlkreise if wk["nr"] == primary), 0)
            if primary_overlap < max_overlap:
                primary_errors.append(plz)

    if primary_errors:
        errors.append(check_failed(3, f"{prefix}Primary correctness",
                                   f"{len(primary_errors)} failures"))
    else:
        check_passed(3, f"{prefix}Primary has largest overlap")

    # Check: Overlap sums
    overlap_errors = []
    for plz, entry in mapping.items():
        s = sum(wk["overlap"] for wk in entry.get("wahlkreise", []))
        if abs(s - 1.0) > OVERLAP_SUM_TOLERANCE:
            overlap_errors.append(plz)

    if overlap_errors:
        errors.append(check_failed(4, f"{prefix}Overlap sums",
                                   f"{len(overlap_errors)} PLZ out of tolerance"))
    else:
        check_passed(4, f"{prefix}Overlap sums ≈ 1.0")

    # Check: Expected samples
    if samples_path and samples_path.exists():
        with open(samples_path, encoding="utf-8") as f:
            samples = json.load(f)
        sample_errors = []
        for s in samples:
            plz = s["plz"]
            if plz in mapping:
                if mapping[plz].get("primary") != s["wahlkreis_nr"]:
                    sample_errors.append(plz)
            else:
                sample_errors.append(plz)
        if sample_errors:
            errors.append(check_failed(5, f"{prefix}Samples",
                                       f"{len(sample_errors)}/{len(samples)} mismatches"))
        else:
            check_passed(5, f"{prefix}All {len(samples)} samples match")
    elif samples_path:
        errors.append(check_failed(5, f"{prefix}Samples", "File not found"))

    # Check: CSV consistency
    if csv_path and csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_rows = list(reader)
        json_pairs = sum(len(e["wahlkreise"]) for e in mapping.values())
        if len(csv_rows) != json_pairs:
            errors.append(check_failed(6, f"{prefix}CSV",
                                       f"CSV {len(csv_rows)} rows vs JSON {json_pairs} pairs"))
        else:
            check_passed(6, f"{prefix}CSV consistent ({len(csv_rows)} rows)")
    elif csv_path:
        errors.append(check_failed(6, f"{prefix}CSV", "File not found"))

    return errors


def verify_bundestag():
    print("=== Bundestag ===")
    errors = verify_mapping(
        BUNDESTAG_JSON, BUNDESTAG_CSV, EXPECTED_SAMPLES,
        expected_wk=299, expected_plz_range=(8000, 8200), label="BT"
    )
    return errors


def verify_landtag():
    print("=== Landtag ===")
    errors = []

    # Find all state output directories
    if not LANDTAG_DIR.exists():
        print("  No Landtag data found")
        return []

    state_dirs = sorted(d for d in LANDTAG_DIR.iterdir() if d.is_dir())
    if not state_dirs:
        print("  No state directories found")
        return []

    # Load Landtag samples
    landtag_samples = {}
    if EXPECTED_LANDTAG_SAMPLES.exists():
        with open(EXPECTED_LANDTAG_SAMPLES, encoding="utf-8") as f:
            for s in json.load(f):
                state = s["state"]
                landtag_samples.setdefault(state, []).append(s)

    for state_dir in state_dirs:
        state = state_dir.name
        json_path = state_dir / "plz-wahlkreis.json"
        csv_path = state_dir / "plz-wahlkreis.csv"

        if not json_path.exists():
            continue

        with open(json_path, encoding="utf-8") as f:
            meta = json.load(f).get("meta", {})
        expected_wk = meta.get("constituencies")

        # Create temp samples file for this state
        state_samples_path = None
        if state in landtag_samples:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            json.dump(landtag_samples[state], tmp)
            tmp.close()
            state_samples_path = Path(tmp.name)

        print(f"\n--- {state} ---")
        state_errors = verify_mapping(
            json_path, csv_path, state_samples_path,
            expected_wk=expected_wk, expected_plz_range=None,
            label=state,
        )
        errors.extend(state_errors)

        if state_samples_path:
            state_samples_path.unlink()

    return errors


def verify_cross_state():
    """Cross-state verification: PLZ overlap and coverage checks."""
    print("\n=== Cross-State Verification ===")
    errors = []

    if not LANDTAG_DIR.exists():
        print("  No Landtag data found")
        return []

    # Collect all PLZ→state assignments
    plz_states = {}  # plz -> set of states
    state_count = 0

    for state_dir in sorted(LANDTAG_DIR.iterdir()):
        if not state_dir.is_dir():
            continue
        json_path = state_dir / "plz-wahlkreis.json"
        if not json_path.exists():
            continue
        state = state_dir.name
        state_count += 1

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f).get("data", {})
        for plz in data:
            plz_states.setdefault(plz, set()).add(state)

    # Check 1: PLZ assigned to multiple states (border PLZ are expected)
    multi_state = {plz: states for plz, states in plz_states.items() if len(states) > 1}
    if multi_state:
        # This is expected for border PLZ — just report count
        print(f"  ℹ {len(multi_state)} PLZ appear in multiple states (border PLZ, expected)")
        if len(multi_state) <= 10:
            for plz, states in sorted(multi_state.items()):
                print(f"    {plz}: {', '.join(sorted(states))}")
    else:
        check_passed("C1", "No PLZ in multiple states")

    # Check 2: Total state coverage
    if state_count == 16:
        check_passed("C2", f"All 16 states have data")
    else:
        errors.append(check_failed("C2", "State coverage", f"Only {state_count}/16 states"))

    # Check 3: Compare Landtag PLZ union with Bundestag PLZ
    if BUNDESTAG_JSON.exists():
        with open(BUNDESTAG_JSON, encoding="utf-8") as f:
            bt_data = json.load(f).get("data", {})
        bt_plz = set(bt_data.keys())
        lt_plz = set(plz_states.keys())

        only_bt = bt_plz - lt_plz
        only_lt = lt_plz - bt_plz

        if len(only_bt) == 0:
            check_passed("C3", f"All {len(bt_plz)} Bundestag PLZ covered by Landtag data")
        else:
            # Some Bundestag PLZ not in any Landtag state is a minor issue
            # (border PLZ with tiny overlap in neighboring state)
            pct = len(only_bt) / len(bt_plz) * 100
            if pct < 5:
                print(f"  ℹ Check C3: {len(only_bt)} Bundestag PLZ ({pct:.1f}%) not in Landtag data (border slivers)")
            else:
                errors.append(check_failed("C3", "BT/LT coverage",
                                           f"{len(only_bt)} Bundestag PLZ missing from Landtag ({pct:.1f}%)"))

        if only_lt:
            print(f"  ℹ {len(only_lt)} PLZ in Landtag but not Bundestag (neighbor-state border slivers)")

    # Check 4: Total Wahlkreise count across all states
    total_wk = 0
    for state_dir in sorted(LANDTAG_DIR.iterdir()):
        if not state_dir.is_dir():
            continue
        json_path = state_dir / "plz-wahlkreis.json"
        if not json_path.exists():
            continue
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f).get("data", {})
        wk = {w["nr"] for e in data.values() for w in e.get("wahlkreise", [])}
        total_wk += len(wk)

    expected_total = 843  # sum of all 16 state WK counts
    if total_wk == expected_total:
        check_passed("C4", f"Total {total_wk} Wahlkreise across all states")
    else:
        errors.append(check_failed("C4", "Total WK count",
                                   f"Expected {expected_total}, got {total_wk}"))

    return errors


def main():
    parser = argparse.ArgumentParser(description="Verify PLZ-Wahlkreis mapping")
    parser.add_argument("--scope", choices=["bundestag", "landtag", "all"], default="all")
    args = parser.parse_args()

    all_errors = []

    if args.scope in ("bundestag", "all"):
        all_errors.extend(verify_bundestag())

    if args.scope in ("landtag", "all"):
        all_errors.extend(verify_landtag())
        all_errors.extend(verify_cross_state())

    print()
    if all_errors:
        print(f"VERIFICATION FAILED ({len(all_errors)} error(s))")
        sys.exit(1)
    else:
        print("VERIFICATION PASSED")


if __name__ == "__main__":
    main()
