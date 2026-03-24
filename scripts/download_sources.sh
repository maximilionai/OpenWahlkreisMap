#!/usr/bin/env bash
# Download raw source data for processing.
# These files are NOT tracked in git — they are large and have their own licenses.
# See SOURCES.md for provenance and attribution.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW_DIR="$SCRIPT_DIR/../raw"
REPO_BASE="https://github.com/maximilionai/OpenWahlkreisMap/releases/download"
DATA_TAG="v0.1.0-data"

# Expected SHA256 checksums (update after uploading release assets)
# Set to "SKIP" to skip verification (first-time setup)
declare -A CHECKSUMS=(
  ["plz-5stellig.geojson"]="SKIP"
  ["btw25_geometrie_wahlkreise_shp.zip"]="SKIP"
)

verify_checksum() {
  local file="$1"
  local name
  name="$(basename "$file")"
  local expected="${CHECKSUMS[$name]:-SKIP}"

  if [ "$expected" = "SKIP" ]; then
    echo "  ⚠ Checksum verification skipped for $name (set hash in script to enable)"
    return 0
  fi

  local actual
  actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    echo "  ✗ Checksum MISMATCH for $name"
    echo "    Expected: $expected"
    echo "    Actual:   $actual"
    return 1
  fi
  echo "  ✓ Checksum OK for $name"
  return 0
}

download_file() {
  local url="$1"
  local dest="$2"
  local name
  name="$(basename "$dest")"

  if [ -f "$dest" ]; then
    echo "  → $name already exists, skipping download"
    return 0
  fi

  echo "  → Downloading $name..."
  if ! curl -fSL --progress-bar -o "$dest" "$url"; then
    echo "  ✗ Failed to download $name from:"
    echo "    $url"
    rm -f "$dest"
    return 1
  fi
  echo "  ✓ Downloaded $name"
}

mkdir -p "$RAW_DIR/bundestag" "$RAW_DIR/plz"

echo "=== 1/3: PLZ boundary polygons (yetzt/postleitzahlen) ==="
PLZ_GZ="$RAW_DIR/plz/plz-5stellig.geojson.gz"
PLZ_JSON="$RAW_DIR/plz/plz-5stellig.geojson"

if [ -f "$PLZ_JSON" ]; then
  echo "  → plz-5stellig.geojson already exists, skipping"
else
  download_file \
    "https://github.com/yetzt/postleitzahlen/raw/main/data/plz-5stellig.geojson.gz" \
    "$PLZ_GZ"
  echo "  → Decompressing..."
  gunzip -f "$PLZ_GZ"
  echo "  ✓ Decompressed to plz-5stellig.geojson"
fi
verify_checksum "$PLZ_JSON"

echo ""
echo "=== 2/3: Wahlkreis boundary shapefiles (Bundeswahlleiterin, mirrored) ==="
WK_ZIP="$RAW_DIR/bundestag/btw25_geometrie_wahlkreise_shp.zip"
WK_SHP="$RAW_DIR/bundestag"

if ls "$WK_SHP"/*.shp 1>/dev/null 2>&1; then
  echo "  → Wahlkreis shapefiles already exist, skipping"
else
  download_file \
    "$REPO_BASE/$DATA_TAG/btw25_geometrie_wahlkreise_shp.zip" \
    "$WK_ZIP"
  verify_checksum "$WK_ZIP"
  echo "  → Decompressing..."
  unzip -o -q "$WK_ZIP" -d "$WK_SHP"
  rm -f "$WK_ZIP"
  echo "  ✓ Decompressed shapefiles to raw/bundestag/"
fi

echo ""
echo "=== 3/3: PLZ centroid coordinates (WZB, supplementary) ==="
download_file \
  "https://raw.githubusercontent.com/WZBSocialScienceCenter/plz_geocoord/master/plz_geocoord.csv" \
  "$RAW_DIR/plz/plz_geocoord.csv"

echo ""
echo "=== Download complete ==="
echo "Run 'make check' to verify all required files are present."
