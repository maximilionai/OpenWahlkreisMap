# CLAUDE.md — OpenWahlkreisMap

## Project Purpose

Open-source PLZ→Wahlkreis mapping for all German parliaments (Bundestag + 16 Landtage).
Published as static JSON/CSV, npm package, and GitHub Pages API.

---

## Open Source Best Practices (NON-NEGOTIABLE)

### What goes in git
- Final output data (`data/` directory — JSON, CSV)
- Processing scripts (`scripts/`)
- Tests and verification (`tests/`, `scripts/verify.py`)
- Documentation (README, SOURCES, CONTRIBUTING, LICENSE)
- Build/CI configuration (Makefile, GitHub Actions)

### What NEVER goes in git
- **Raw source data** — large binary files (shapefiles, GeoJSON) go in `raw/` which is gitignored. Document download URLs in `scripts/download_sources.sh` instead.
- **Intermediate artifacts** — temp files, caches, processing byproducts
- **Credentials or API keys** — even if currently unused
- **Personal notes or draft research** — keep in local files outside the repo
- **IDE/OS files** — .DS_Store, .vscode, .idea (gitignored)

### Reproducibility
- Anyone must be able to run `make all` to reproduce the full dataset from scratch
- Download → Process → Verify pipeline must be fully scripted
- Pin dependency versions in `requirements.txt`
- Document every data source in `SOURCES.md` with URL, license, and attribution

### Data provenance
- Every data source must be listed in `SOURCES.md` with its license
- BKG data requires attribution: `© GeoBasis-DE / BKG (year)`
- Bundeswahlleiterin data is public domain (§5 UrhG)
- abgeordnetenwatch data is CC0
- Include attribution in output files' metadata

---

## Architecture

```
raw/                    ← Downloaded source files (gitignored)
  bundestag/            ← Shapefiles from Bundeswahlleiterin
  plz/                  ← PLZ boundaries from BKG or community
  landtag/{state}/      ← Per-state constituency data

scripts/                ← Processing pipeline (tracked)
  download_sources.sh   ← Fetches raw data
  process_bundestag.py  ← Spatial intersection → JSON/CSV
  process_landtag.py    ← Per-state processing
  verify.py             ← Automated verification

data/                   ← Final output (tracked)
  bundestag/            ← PLZ→Bundestag-Wahlkreis
  landtag/{state}/      ← PLZ→Landtag-Wahlkreis

tests/                  ← Additional test files
```

### Processing pipeline
1. `make download` — fetch raw geodata to `raw/`
2. `make process` — spatial intersection, output to `data/`
3. `make verify` — check completeness, correctness, spot-checks
4. `make build-api` — generate per-PLZ API files to `api/v1/`

---

## Data Model

### Per-PLZ API format (`api/v1/{plz}.json`)
```json
{
  "plz": "87435",
  "bundestag": {
    "wahlkreise": [{ "nr": 256, "name": "Oberallgäu", "overlap": 0.95 }],
    "primary": 256,
    "period_id": 161
  },
  "landtage": [
    {
      "state": "bayern",
      "wahlkreise": [{ "nr": 407, "name": "Kempten", "overlap": 1.0 }],
      "primary": 407,
      "period_id": 149
    }
  ]
}
```

### Key concepts
- One PLZ can map to multiple Wahlkreise (PLZ boundaries ≠ constituency boundaries)
- `overlap` is the area percentage (0.0–1.0) of the PLZ that falls within each Wahlkreis
- `primary` is the Wahlkreis with the largest overlap
- `period_id` references the abgeordnetenwatch API parliament period

---

## API (GitHub Pages)

Static JSON served at: `https://openwahlkreismap.org/api/v1/{plz}.json`

- No auth, no rate limiting, CDN-backed
- Pre-generated one file per PLZ (~8,000 files)
- CORS-friendly (GitHub Pages default)
- Changes only on redistricting (every 4–5 years)

---

## Parliaments Covered

| Parliament | Constituencies | abgeordnetenwatch period_id |
|-----------|---------------|----------------------------|
| Bundestag | 299 | 161 |
| Baden-Württemberg | 70 | 163 |
| Bayern | 91 (Stimmkreise) | 149 |
| Berlin | 78 | 133 |
| Brandenburg | 44 | 158 |
| Bremen | 2 | 146 |
| Hamburg | 17 | 162 |
| Hessen | 55 | 150 |
| Mecklenburg-Vorpommern | 36 | 134 |
| Niedersachsen | 87 | 143 |
| Nordrhein-Westfalen | 128 | 139 |
| Rheinland-Pfalz | 52 | 164 |
| Saarland | 3 | 137 |
| Sachsen | 60 | 157 |
| Sachsen-Anhalt | 41 | 131 |
| Schleswig-Holstein | 35 | 138 |
| Thüringen | 44 | 156 |

---

## Commit conventions

- `feat:` — new data, new parliament coverage, new output format
- `fix:` — incorrect mapping data, verification fixes
- `data:` — regenerated output data after source update
- `docs:` — documentation changes
- `scripts:` — pipeline/tooling changes

---

## Boundaries — Ask Before Doing

| Do it | Ask first | Never |
|-------|-----------|-------|
| Update processing scripts | Change output format schema | Commit raw source data to git |
| Add verification checks | Add new parliament coverage | Remove attribution from sources |
| Fix mapping errors | Change license | Push unverified data |
| Update documentation | Modify the Makefile pipeline | Store credentials in repo |
