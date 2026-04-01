"""
Generate src/data.json for the npm package.

Reads per-PLZ API files and bundles them into a single JSON object
keyed by PLZ for the TypeScript package to import.

Usage:
  python3 scripts/build_npm_data.py
"""

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
API_DIR = PROJECT_DIR / "api" / "v1"
OUTPUT = PROJECT_DIR / "src" / "data.json"


def main():
    if not API_DIR.exists():
        print("API directory not found — run 'make build-api' first", file=sys.stderr)
        sys.exit(1)

    data = {}
    for f in sorted(API_DIR.glob("*.json")):
        if f.name == "index.json":
            continue
        with open(f, encoding="utf-8") as fh:
            entry = json.load(fh)
        plz = f.stem
        # Strip the plz field from value (it's the key)
        del entry["plz"]
        data[plz] = entry

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    print(f"Wrote {len(data)} PLZ entries to {OUTPUT} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
