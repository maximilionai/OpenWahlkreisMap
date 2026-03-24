# OpenWahlkreisMap

Open-source mapping of German 5-digit postal codes (PLZ) to electoral constituencies for **all 17 German parliaments** — the Bundestag and all 16 Landtage.

Published as static JSON, CSV, npm package, and a free public API via GitHub Pages.

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
export function getWahlkreise(plz: string): { nr: number; name: string; overlap: number }[]
export function getPrimaryWahlkreis(plz: string): { nr: number; name: string } | null
```

## Tech Stack

- **Python 3.11+** for data processing
- **geopandas** + **shapely** for spatial operations
- **pandas** for data joins
- **pytest** for verification
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
- Potential expansion: Landtag constituencies, EU Parliament constituencies
