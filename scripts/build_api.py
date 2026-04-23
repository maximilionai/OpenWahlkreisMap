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
PAGES_ROOT = PROJECT_DIR / "api"


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
    if PAGES_ROOT.exists():
        shutil.rmtree(PAGES_ROOT)
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

    # Write a minimal landing page so the Pages root is useful.
    index_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OpenWahlkreisMap API</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f4ec;
      --panel: #fffdf8;
      --text: #1f1a14;
      --muted: #6d6255;
      --accent: #9a3412;
      --border: #dfd4c4;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top right, rgba(154, 52, 18, 0.12), transparent 26rem),
        linear-gradient(180deg, #fbf8f1 0%, var(--bg) 100%);
      color: var(--text);
    }}
    main {{
      max-width: 46rem;
      margin: 0 auto;
      padding: 4rem 1.5rem 5rem;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 1rem;
      box-shadow: 0 18px 50px rgba(31, 26, 20, 0.08);
      padding: 2rem;
    }}
    h1 {{
      margin: 0 0 0.75rem;
      font-size: clamp(2rem, 6vw, 3.25rem);
      line-height: 1;
    }}
    p {{
      margin: 0 0 1rem;
      line-height: 1.6;
    }}
    .muted {{
      color: var(--muted);
    }}
    code {{
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
      font-size: 0.95em;
    }}
    a {{
      color: var(--accent);
    }}
    ul {{
      padding-left: 1.2rem;
    }}
  </style>
</head>
<body>
  <main>
    <div class="panel">
      <h1>OpenWahlkreisMap API</h1>
      <p class="muted">Static postcode-to-constituency data for Bundestag and all 16 Landtage.</p>
      <p>Current dataset version: <code>{index["version"]}</code>. Generated: <code>{index["generated"]}</code>.</p>
      <ul>
        <li>API index: <a href="/v1/index.json"><code>/v1/index.json</code></a></li>
        <li>Example PLZ: <a href="/v1/10117.json"><code>/v1/10117.json</code></a></li>
        <li>Project repository: <a href="https://github.com/maximilionai/OpenWahlkreisMap">GitHub</a></li>
      </ul>
    </div>
  </main>
</body>
</html>
"""
    with open(PAGES_ROOT / "index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"\nWrote {len(all_plz)} API files to {API_DIR}/")
    print(f"Index: {API_DIR / 'index.json'}")


if __name__ == "__main__":
    build_api()
