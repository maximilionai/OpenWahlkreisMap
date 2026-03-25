#!/usr/bin/env bash
# Download raw source data for Landtag processing.
# VG250 municipality boundaries + per-state constituency data.
# See SOURCES.md for provenance and attribution.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW_DIR="$SCRIPT_DIR/../raw"
REPO_BASE="https://github.com/maximilionai/OpenWahlkreisMap/releases/download"
DATA_TAG="v0.2.0-data"

# SHA256 checksums
CHECKSUM_VG250="$(shasum -a 256 /dev/null | awk '{print "SKIP"}')"  # TODO: set after first download

verify_checksum() {
  local file="$1"
  local expected="$2"
  local name
  name="$(basename "$file")"

  if [ "$expected" = "SKIP" ]; then
    echo "  ⚠ Checksum skipped for $name"
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
}

download_file() {
  local url="$1"
  local dest="$2"
  local name
  name="$(basename "$dest")"

  if [ -f "$dest" ]; then
    echo "  → $name already exists, skipping"
    return 0
  fi

  echo "  → Downloading $name..."
  if ! curl -fSL --progress-bar -o "$dest" "$url"; then
    echo "  ✗ Failed to download $name"
    rm -f "$dest"
    return 1
  fi
  echo "  ✓ Downloaded $name"
}

mkdir -p "$RAW_DIR/municipality" "$RAW_DIR/landtag"

echo "=== 1: VG250 Gemeinden boundaries (BKG) ==="
VG250_ZIP="$RAW_DIR/municipality/vg250_gem_utm32s.zip"
VG250_SHP="$RAW_DIR/municipality/VG250_GEM.shp"

if [ -f "$VG250_SHP" ]; then
  echo "  → VG250 Gemeinden already extracted, skipping"
else
  download_file "$REPO_BASE/$DATA_TAG/vg250_gem_utm32s.zip" "$VG250_ZIP"
  echo "  → Extracting..."
  unzip -o -q "$VG250_ZIP" -d "$RAW_DIR/municipality/"
  rm -f "$VG250_ZIP"
  echo "  ✓ Extracted VG250 Gemeinden shapefiles"
fi

echo ""
echo "=== Landtag downloads complete ==="
echo "Per-state data will be added as configs are created."
