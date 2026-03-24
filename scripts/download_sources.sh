#!/usr/bin/env bash
# Download raw source data for processing.
# These files are NOT tracked in git — they are large and have their own licenses.
# See SOURCES.md for provenance and attribution.

set -euo pipefail

RAW_DIR="$(dirname "$0")/../raw"
mkdir -p "$RAW_DIR/bundestag" "$RAW_DIR/plz" "$RAW_DIR/gemeinden"

echo "=== Downloading Bundeswahlleiterin constituency data ==="
# TODO: Add direct download URLs once confirmed
# curl -L -o "$RAW_DIR/bundestag/btw25_wahlkreise_gemeinden.csv" "URL"
# curl -L -o "$RAW_DIR/bundestag/btw25_wahlkreise.shp.zip" "URL"
echo "  → Manual download required from:"
echo "    https://www.bundeswahlleiterin.de/bundestagswahlen/2025/wahlkreiseinteilung/downloads.html"
echo "    Place files in: $RAW_DIR/bundestag/"

echo ""
echo "=== Downloading BKG PLZ boundary data ==="
# TODO: BKG requires account registration for some datasets
echo "  → Manual download may be required from:"
echo "    https://gdz.bkg.bund.de/index.php/default/postleitzahlgebiete-deutschland-plz.html"
echo "    Place files in: $RAW_DIR/plz/"

echo ""
echo "=== Downloading PLZ GeoJSON (open alternative) ==="
curl -L -o "$RAW_DIR/plz/plz-5stellig.geojson.gz" \
  "https://github.com/yetzt/postleitzahlen/raw/main/data/plz-5stellig.geojson.gz" 2>/dev/null \
  && echo "  → Downloaded plz-5stellig.geojson.gz" \
  || echo "  → Failed to download, check URL"

echo ""
echo "=== Downloading PLZ centroid coordinates ==="
curl -L -o "$RAW_DIR/plz/plz_geocoord.csv" \
  "https://raw.githubusercontent.com/WZBSocialScienceCenter/plz_geocoord/master/plz_geocoord.csv" 2>/dev/null \
  && echo "  → Downloaded plz_geocoord.csv" \
  || echo "  → Failed to download, check URL"

echo ""
echo "Done. Check $RAW_DIR/ for downloaded files."
echo "Some files require manual download — see messages above."
