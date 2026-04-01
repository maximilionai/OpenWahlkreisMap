"""
Build per-PLZ API files from the processed data.

Merges Bundestag + 16 Landtag mappings into one JSON file per PLZ
at api/v1/{plz}.json for static hosting via GitHub Pages.

Usage:
  python3 scripts/build_api.py
"""

import json
import shutil
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
BUNDESTAG_JSON = PROJECT_DIR / "data" / "bundestag" / "plz-wahlkreis.json"
LANDTAG_DIR = PROJECT_DIR / "data" / "landtag"
API_DIR = PROJECT_DIR / "api" / "v1"


def load_bundestag() -> dict:
    """Load Bundestag data keyed by PLZ."""
    with open(BUNDESTAG_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    return raw["data"], raw["meta"]


def load_landtag() -> dict:
    """Load all Landtag data keyed by PLZ, grouped by state."""
    plz_states = {}  # plz -> list of {state, wahlkreise, primary, period_id}

    for state_dir in sorted(LANDTAG_DIR.iterdir()):
        if not state_dir.is_dir():
            continue
        json_path = state_dir / "plz-wahlkreis.json"
        if not json_path.exists():
            continue

        state = state_dir.name
        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)

        for plz, entry in raw["data"].items():
            lt_entry = {
                "state": state,
                "wahlkreise": entry["wahlkreise"],
                "primary": entry["primary"],
                "period_id": entry["period_id"],
            }
            plz_states.setdefault(plz, []).append(lt_entry)

    # Sort landtage by state name for deterministic output
    for plz in plz_states:
        plz_states[plz].sort(key=lambda e: e["state"])

    return plz_states


def build_api():
    """Build per-PLZ API files."""
    print("Loading data...")
    bt_data, bt_meta = load_bundestag()
    lt_data = load_landtag()

    # Union of all PLZ
    all_plz = sorted(set(bt_data.keys()) | set(lt_data.keys()))
    print(f"  Bundestag: {len(bt_data)} PLZ")
    print(f"  Landtag:   {len(lt_data)} PLZ")
    print(f"  Union:     {len(all_plz)} PLZ")

    # Clean output directory
    if API_DIR.exists():
        shutil.rmtree(API_DIR)
    API_DIR.mkdir(parents=True)

    # Write per-PLZ files
    for plz in all_plz:
        entry = {"plz": plz}

        if plz in bt_data:
            bt = bt_data[plz]
            entry["bundestag"] = {
                "wahlkreise": bt["wahlkreise"],
                "primary": bt["primary"],
                "period_id": bt["period_id"],
            }
        else:
            entry["bundestag"] = None

        entry["landtage"] = lt_data.get(plz, [])

        out_path = API_DIR / f"{plz}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, separators=(",", ":"))

    # Write index
    index = {
        "version": "1.0.0",
        "plz_count": len(all_plz),
        "parliaments": 17,
        "generated": date.today().isoformat(),
        "bundestag": {
            "election": bt_meta.get("election"),
            "constituencies": bt_meta.get("constituencies"),
        },
    }
    with open(API_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {len(all_plz)} API files to {API_DIR}/")
    print(f"Index: {API_DIR / 'index.json'}")


if __name__ == "__main__":
    build_api()
