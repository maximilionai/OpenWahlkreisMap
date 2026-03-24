# Data Sources

All source datasets used by OpenWahlkreisMap, with provenance and licensing.

## Bundestag Constituency Boundaries

| Field | Value |
|-------|-------|
| **Publisher** | Bundeswahlleiterin |
| **URL** | https://www.bundeswahlleiterin.de/bundestagswahlen/2025/wahlkreiseinteilung/downloads.html |
| **Files** | `btw25_wahlkreisnummern_namen.csv`, `btw25_wahlkreise_gemeinden.csv`, Shapefiles |
| **License** | Public domain (§5 UrhG — Amtliche Werke) |
| **Attribution** | Not legally required, but credited as good practice |
| **Election** | BTW 2025 (valid 2025–2029) |
| **Constituencies** | 299 |

## PLZ Boundary Polygons

| Field | Value |
|-------|-------|
| **Publisher** | BKG (Bundesamt für Kartographie und Geodäsie) |
| **URL** | https://gdz.bkg.bund.de/index.php/default/postleitzahlgebiete-deutschland-plz.html |
| **Documentation** | https://sg.geodatenzentrum.de/web_public/gdz/dokumentation/deu/plz.pdf |
| **License** | dl-de/by-2-0 (Datenlizenz Deutschland – Namensnennung – Version 2.0) |
| **Attribution** | © GeoBasis-DE / BKG (year of data) |
| **Contains** | PLZ polygons with AGS (Amtlicher Gemeindeschlüssel) mapping |

## Gemeindeverzeichnis (supplementary)

| Field | Value |
|-------|-------|
| **Publisher** | Destatis (Statistisches Bundesamt) |
| **URL** | https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis |
| **License** | dl-de/by-2-0 |
| **Attribution** | © Statistisches Bundesamt (Destatis) |
| **Limitation** | Only one PLZ per Gemeinde (Verwaltungssitz) |

## PLZ GeoJSON (open alternative)

| Field | Value |
|-------|-------|
| **Publisher** | yetzt/postleitzahlen (GitHub community) |
| **URL** | https://github.com/yetzt/postleitzahlen |
| **License** | ODbl |
| **Contains** | GeoJSON/TopoJSON of all PLZ areas |

## PLZ Centroid Coordinates

| Field | Value |
|-------|-------|
| **Publisher** | WZBSocialScienceCenter |
| **URL** | https://github.com/WZBSocialScienceCenter/plz_geocoord |
| **License** | MIT |
| **Contains** | Lat/lon coordinates for all PLZ centroids |

## Abgeordnetenwatch API (constituency metadata)

| Field | Value |
|-------|-------|
| **Publisher** | abgeordnetenwatch.de |
| **URL** | https://www.abgeordnetenwatch.de/api/v2 |
| **License** | CC0 1.0 |
| **Contains** | Constituency names, numbers, parliament period IDs for all 17 German parliaments |
| **Limitation** | No PLZ lookup, no geodata |

## Landtag Constituency Data (per state)

Each state publishes its own constituency-to-municipality assignments via the respective Landeswahlleiter. These are collected individually during processing. See `scripts/` for download details per state.

| State | Source | Format | Constituencies |
|-------|--------|--------|---------------|
| Baden-Württemberg | Statistisches Landesamt BW | PDF/Excel | 70 |
| Bayern | Landesamt für Statistik | Excel | 91 (Stimmkreise) |
| Berlin | Landeswahlleiter Berlin / FIS-Broker | Shapefile | 78 |
| Brandenburg | Landeswahlleiter BB | PDF/Excel | 44 |
| Bremen | Landeswahlleiter HB | PDF | 2 |
| Hamburg | Transparenzportal HH | Geodata | 17 |
| Hessen | Landeswahlleiter HE | Excel | 55 |
| Mecklenburg-Vorpommern | Landeswahlleiter MV | PDF | 36 |
| Niedersachsen | Landeswahlleiter NI | Excel | 87 |
| Nordrhein-Westfalen | Open.NRW / Landtag NRW | Shapefile/GeoJSON | 128 |
| Rheinland-Pfalz | wahlen.rlp.de | PDF/Excel | 52 |
| Saarland | Landeswahlleiter SL | PDF | 3 |
| Sachsen | Sachsen GDI | Geodata | 60 |
| Sachsen-Anhalt | Landeswahlleiter ST | Excel | 41 |
| Schleswig-Holstein | Landeswahlleiter SH | Excel | 35 |
| Thüringen | Landeswahlleiter TH | Excel | 44 |
