# OpenWahlkreisMap

Open-source mapping of German 5-digit postal codes (PLZ) to electoral constituencies for **all 17 German parliaments** — the Bundestag and all 16 Landtage.

Published as static JSON, CSV, npm package, and a free public API via GitHub Pages.

## Quick Start

### API (no setup needed)

```bash
curl https://openwahlkreismap.org/v1/10117.json
```

```json
{
  "plz": "10117",
  "bundestag": {
    "wahlkreise": [{ "nr": 74, "name": "Berlin-Mitte", "overlap": 1.0 }],
    "primary": 74,
    "period_id": 161
  },
  "landtage": [{
    "state": "berlin",
    "wahlkreise": [
      { "nr": 102, "name": "Alexanderplatz, Engelbecken", "overlap": 0.520094 },
      { "nr": 101, "name": "Charité, Oranienburger Tor", "overlap": 0.479906 }
    ],
    "primary": 102,
    "period_id": 133
  }]
}
```

### npm package

```bash
npm install open-wahlkreis-map
```

```typescript
import {
  getBundestagWahlkreis,
  getConstituencies,
  getLandtagWahlkreise,
} from 'open-wahlkreis-map';

const result = getConstituencies('10117');
// { plz: '10117', bundestag: { primary: 74, ... }, landtage: [{ state: 'berlin', ... }] }

const bt = getBundestagWahlkreis('10117');
// { wahlkreise: [{ nr: 74, name: 'Berlin-Mitte', overlap: 1.0 }], primary: 74, period_id: 161 }

const berlin = getLandtagWahlkreise('10117', 'berlin');
// [{ state: 'berlin', wahlkreise: [...], primary: 102, period_id: 133 }]
```

The npm package is an in-memory lookup table and bundles the full dataset for fast local reads. If bundle size matters, prefer the static API or consume generated JSON directly.

## The Problem

There is **no official dataset** that maps PLZ → Wahlkreis. This has been confirmed through multiple FragDenStaat freedom-of-information requests — the Bundeswahlleiterin explicitly states they only map at the Gemeinde (municipality) level.

PLZ boundaries (managed by Deutsche Post) and Wahlkreis boundaries (managed by the Bundeswahlleiterin) **do not align**:
- One PLZ can span multiple Wahlkreise
- One Wahlkreis can contain parts of many PLZ areas
- PLZ boundaries follow postal logistics, Wahlkreis boundaries follow population counts

Every civic tech project that needs this mapping (abgeordnetenwatch.de, wahl-o-mat tools, lobbying platforms, etc.) builds their own internal lookup — usually closed-source and not shared.

## Goal

Produce an open, machine-readable, verified mapping:

```
PLZ (5-digit) → Wahlkreis number(s) + confidence
```

Published as:
- **JSON** (`plz-wahlkreis.json`) — primary format
- **CSV** (`plz-wahlkreis.csv`) — for spreadsheet users
- **TypeScript** (`plz-wahlkreis.ts`) — for JS/TS projects
- **npm package** — `open-wahlkreis-map` for easy consumption

## Data Sources

### 1. Wahlkreis → Gemeinde (authoritative)

**Source:** Bundeswahlleiterin — Wahlkreiseinteilung BTW 2025
**URL:** https://www.bundeswahlleiterin.de/bundestagswahlen/2025/wahlkreiseinteilung/downloads.html

Two files available:
- `btw25_wahlkreisnummern_namen.csv` — 299 Wahlkreise with numbers and names (13 KB)
- `btw25_wahlkreise_gemeinden.csv` — All Wahlkreise with their constituent Gemeinden, identified by AGS (Amtlicher Gemeindeschlüssel) (1.36 MB)

The Gemeinde file is the key dataset. It tells us exactly which municipalities belong to which constituency.

### 2. PLZ → Gemeinde (geographic)

**Source:** BKG (Bundesamt für Kartographie und Geodäsie) — Postleitzahlengebiete
**URL:** https://gdz.bkg.bund.de/index.php/default/postleitzahlgebiete-deutschland-plz.html
**Documentation:** https://sg.geodatenzentrum.de/web_public/gdz/dokumentation/deu/plz.pdf

Provides vector polygons (shapefiles) of all 5-digit PLZ areas with a mapping of PLZ → AGS (official municipality key). This is the bridge between PLZ and Gemeinde.

**License:** dl-de/by-2-0 (attribution required, commercial use OK)

### 3. Gemeindeverzeichnis (supplementary)

**Source:** Destatis (Statistisches Bundesamt) — GV-ISys Gemeindeverzeichnis
**URL:** https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugQ/AuszugGV2QAktuell.html

Provides every Gemeinde with its AGS and the PLZ of its administrative seat.

**Limitation:** Only lists ONE PLZ per Gemeinde (the Verwaltungssitz). Large cities with many PLZ areas are not fully covered. Useful as a supplement/cross-check but not sufficient alone.

### 4. Wahlkreis boundary shapefiles (for spatial approach)

**Source:** Bundeswahlleiterin — Geometrien der Wahlkreise
**URL:** https://www.bundeswahlleiterin.de/bundestagswahlen/2025/wahlkreiseinteilung/downloads.html

Exact Wahlkreis boundary polygons. Can be intersected with PLZ polygons for a purely geometric approach.

### 5. PLZ centroid coordinates (for point-in-polygon fallback)

**Source:** WZBSocialScienceCenter/plz_geocoord (GitHub)
**URL:** https://github.com/WZBSocialScienceCenter/plz_geocoord

Geocoordinates for all PLZ centroids. Useful for a simpler point-in-polygon approach (check which Wahlkreis the center of each PLZ falls in), though this misses PLZ that straddle boundaries.

### 6. PLZ boundary GeoJSON (open alternative to BKG)

**Source:** yetzt/postleitzahlen (GitHub)
**URL:** https://github.com/yetzt/postleitzahlen

GeoJSON/TopoJSON of all German PLZ areas (2025 edition). No Wahlkreis linkage, but useful if BKG data is hard to obtain.

## Approach

Two methods, in order of preference:

### Method A: AGS-based join (simpler, slightly less precise)

```
PLZ shapefile (BKG)     →  PLZ → AGS mapping
Gemeinde-Wahlkreis CSV  →  AGS → Wahlkreis mapping
                         ─────────────────────────
                         =  PLZ → Wahlkreis mapping
```

1. From the BKG PLZ shapefile, extract which AGS codes each PLZ overlaps with
2. From the Bundeswahlleiterin CSV, get which Wahlkreis each AGS belongs to
3. Join on AGS: for each PLZ, collect all Wahlkreise that its constituent Gemeinden belong to
4. Output: `{ plz: "87435", wahlkreise: [256], primary: 256 }`

**Pros:** Straightforward data join, no complex geometry needed
**Cons:** Depends on PLZ↔AGS mapping quality in the BKG data

### Method B: Spatial intersection (most precise)

```
PLZ boundary polygons    ─┐
                          ├→ geometric intersection → PLZ → Wahlkreis + area overlap %
Wahlkreis boundary polygons ─┘
```

1. Load PLZ boundary polygons (from BKG or yetzt/postleitzahlen)
2. Load Wahlkreis boundary polygons (from Bundeswahlleiterin)
3. For each PLZ polygon, compute intersection with all Wahlkreis polygons
4. Calculate area overlap percentage
5. Mark primary Wahlkreis (largest overlap) and secondary ones
6. Output: `{ plz: "87435", wahlkreise: [{ nr: 256, overlap: 0.95 }, { nr: 255, overlap: 0.05 }], primary: 256 }`

**Pros:** Most precise, captures boundary-straddling PLZ with percentages
**Cons:** Requires geopandas/shapely, heavier computation

### Recommended: Method B with Method A as cross-check

Run Method B to get the precise mapping with overlap percentages, then cross-check against Method A to catch any data anomalies.

## Output Format

### JSON (primary)

```json
{
  "meta": {
    "election": "BTW 2025",
    "constituencies": 299,
    "plz_count": 8168,
    "generated": "2026-03-24",
    "sources": [
      "Bundeswahlleiterin Wahlkreiseinteilung 2025",
      "BKG Postleitzahlengebiete 2025"
    ]
  },
  "data": {
    "87435": {
      "wahlkreise": [
        { "nr": 256, "name": "Oberallgäu", "overlap": 0.95 },
        { "nr": 255, "name": "Memmingen – Unterallgäu", "overlap": 0.05 }
      ],
      "primary": 256
    }
  }
}
```

### CSV

```csv
plz,wahlkreis_nr,wahlkreis_name,overlap,is_primary
87435,256,Oberallgäu,0.95,true
87435,255,Memmingen – Unterallgäu,0.05,false
```

### TypeScript

```typescript
export function getConstituencies(plz: string): PlzResult | null
export function getBundestagWahlkreis(plz: string): BundestagEntry | null
export function getLandtagWahlkreise(plz: string, state?: string): LandtagEntry[]
```

## Tech Stack

- **Python 3.11+** for data processing
- **geopandas** + **shapely** for spatial operations
- **pandas** for data joins
- **pytest** for unit and fixture-based integration tests
- Optionally: **DuckDB** with spatial extension as a faster alternative

## Verification

- Total Wahlkreise in output must equal 299
- Every Wahlkreis must appear at least once
- Every valid 5-digit PLZ must map to at least one Wahlkreis
- Primary Wahlkreis must have the largest overlap for each PLZ
- Cross-check: compare against 2-digit prefix mapping from liebemdb (sanity check)
- Spot-check: manually verify ~50 PLZ across all Bundesländer

## Update Cycle

The mapping only changes when:
- Wahlkreis boundaries are redrawn (every ~4 years, before each Bundestagswahl)
- PLZ boundaries change (Deutsche Post updates these occasionally)

For BTW 2025, this mapping is valid 2025–2029.

## Coverage

### Bundestag

299 Wahlkreise. The exact bundled PLZ count is stored in [`data/bundestag/plz-wahlkreis.json`](data/bundestag/plz-wahlkreis.json) under `meta.plz_count`.

### Landtage (all 16 states)

| State | Parliament | WK | PLZ | Method | Election |
|-------|-----------|-----|-----|--------|----------|
| Baden-Württemberg | Landtag | 70 | 1,309 | municipality_join | LTW 2026 |
| Bayern | Landtag | 91 | 2,174 | municipality_join | LTW 2023 |
| Berlin | Abgeordnetenhaus | 78 | 216 | spatial (repo-local official ZIP) | AgH 2026 |
| Brandenburg | Landtag | 44 | 310 | municipality_join | LTW 2024 |
| Bremen | Bürgerschaft | 2 | 40 | plz_mapping | BW 2023 |
| Hamburg | Bürgerschaft | 17 | 123 | spatial (WFS) | BüW 2025 |
| Hessen | Landtag | 55 | 668 | municipality_join | LTW 2023 |
| Mecklenburg-Vorpommern | Landtag | 36 | 224 | spatial | LTW 2021 |
| Niedersachsen | Landtag | 87 | 919 | municipality_join | LTW 2022 |
| Nordrhein-Westfalen | Landtag | 128 | 961 | municipality_join | LTW 2022 |
| Rheinland-Pfalz | Landtag | 52 | 737 | municipality_join | LTW 2021 |
| Saarland | Landtag | 3 | 92 | municipality_join | LTW 2022 |
| Sachsen | Landtag | 60 | 428 | municipality_join | LTW 2024 |
| Sachsen-Anhalt | Landtag | 41 | 280 | municipality_join | LTW 2021 |
| Schleswig-Holstein | Landtag | 35 | 464 | municipality_join | LTW 2022 |
| Thüringen | Landtag | 44 | 312 | municipality_join | LTW 2024 |
| **Total** | | **843** | **9,256** | | |

Processing methods:
- **spatial**: Direct polygon intersection of PLZ and Wahlkreis boundaries
- **municipality_join**: PLZ→AGS→Wahlkreis via VG250 municipality boundaries
- **plz_mapping**: Direct PLZ→Wahlkreis mapping for compact city-state cases

Landtag downloads are fully scripted. `make download-landtag` fetches or generates every state source from config, including Berlin, Hamburg, and Saarland.

Berlin has one special-case manual source step: place the official archive at `raw/landtag/berlin/RBS_OD_Wahlkreise_AH2026.zip`. The downloader requires that ZIP and verifies it before normalizing the shapefile into the repo format.

The tracked file `configs/landtag/berlin_ortsteil_wahlkreis.csv` is retained only as a Berlin `wk_nr -> wk_name` lookup. As of April 23, 2026, I could not find a better machine-readable official name table on the Berlin election/statistics sites. The names were derived from the official Berlin Wahlkreiskarten PDFs published at `https://www.statistik-berlin-brandenburg.de/wahlkreiskarten-2026/`.

## Testing

Use two layers:

- `make test` runs the fast `pytest` suite for parser helpers, checksum helpers, and small fixture-based processing tests.
- `make verify` runs `scripts/verify.py`, which is the release gate for final published outputs and built artifacts.

## Related Projects

| Project | What it does | PLZ mapping? |
|---------|-------------|--------------|
| [abgeordnetenwatch.de](https://www.abgeordnetenwatch.de) | Politician transparency platform | Internal, closed-source |
| [bundestag.de Wahlkreissuche](https://www.bundestag.de/abgeordnete/wahlkreissuche) | Official constituency finder | Web UI only, no API |
| [okfde/wahldaten](https://github.com/okfde/wahldaten) | Open election data | Wahlkreis geometries, no PLZ |
| [yetzt/postleitzahlen](https://github.com/yetzt/postleitzahlen) | PLZ GeoJSON boundaries | No Wahlkreis linkage |
| [WZBSocialScienceCenter/plz_geocoord](https://github.com/WZBSocialScienceCenter/plz_geocoord) | PLZ centroids | No Wahlkreis linkage |

## Legal / Licensing

- Bundeswahlleiterin data: public domain (Amtliche Werke, §5 UrhG)
- BKG data: dl-de/by-2-0 (attribution required)
- Destatis data: dl-de/by-2-0
- Output dataset: to be published under CC0 or MIT

## Future

- EU AI Act (Art. 50, Aug 2026): if this data is used to power AI-assisted civic participation tools, the generated content may need labeling
- Wirtschafts-Identifikationsnummer (W-IdNr., Dec 2026): not relevant to this project but worth noting for downstream users
- Landtag coverage complete (all 16 states, 843 Wahlkreise)
- Potential expansion: EU Parliament constituencies
