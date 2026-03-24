#!/usr/bin/env bash
# Download raw source data for processing.
# These files are NOT tracked in git — they are large and have their own licenses.
# See SOURCES.md for provenance and attribution.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW_DIR="$SCRIPT_DIR/../raw"
REPO_BASE="https://github.com/maximilionai/OpenWahlkreisMap/releases/download"
DATA_TAG="v0.1.0-data"

# Expected SHA256 checksums
CHECKSUM_PLZ="99bdd1d5b648b3cf24c73a11fac0fabe47ceb5d45f24457fe4384a82b09d56d2"
CHECKSUM_WK="a237c32c45ff658784174d4b15e37abf657af82a1886ae467a865db733a274a0"

verify_checksum() {
  local file="$1"
  local expected="$2"
  local name
  name="$(basename "$file")"

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
PLZ_BR="$RAW_DIR/plz/postleitzahlen.geojson.br"
PLZ_JSON="$RAW_DIR/plz/plz-5stellig.geojson"

if [ -f "$PLZ_JSON" ]; then
  echo "  → plz-5stellig.geojson already exists, skipping"
else
  # Download brotli-compressed GeoJSON from latest GitHub release
  download_file \
    "https://github.com/yetzt/postleitzahlen/releases/latest/download/postleitzahlen.geojson.br" \
    "$PLZ_BR"
  echo "  → Decompressing (brotli)..."
  if command -v brotli &>/dev/null; then
    brotli -d "$PLZ_BR" -o "$PLZ_JSON" && rm -f "$PLZ_BR"
  else
    echo "  ✗ brotli not found. Install with: brew install brotli (macOS) or apt install brotli (Linux)"
    exit 1
  fi
  echo "  ✓ Decompressed to plz-5stellig.geojson"
fi
verify_checksum "$PLZ_JSON" "$CHECKSUM_PLZ"

echo ""
echo "=== 2/3: Wahlkreis boundary shapefiles (Bundeswahlleiterin, mirrored) ==="
WK_ZIP="$RAW_DIR/bundestag/btw25_geometrie_wahlkreise_vg250_shp.zip"
WK_SHP="$RAW_DIR/bundestag"

if ls "$WK_SHP"/*.shp 1>/dev/null 2>&1; then
  echo "  → Wahlkreis shapefiles already exist, skipping"
else
  download_file \
    "$REPO_BASE/$DATA_TAG/btw25_geometrie_wahlkreise_vg250_shp.zip" \
    "$WK_ZIP"
  verify_checksum "$WK_ZIP" "$CHECKSUM_WK"
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
