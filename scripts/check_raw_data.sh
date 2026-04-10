#!/usr/bin/env bash
# Validate that all required raw files exist before processing.
# Called by 'make check' and as a dependency of 'make process'.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW_DIR="$SCRIPT_DIR/../raw"
ERRORS=0

check_file() {
  local path="$1"
  local description="$2"
  local help_msg="$3"

  if [ ! -f "$path" ] || [ ! -s "$path" ]; then
    echo "  ✗ MISSING: $description"
    echo "    Expected: $path"
    echo "    Fix: $help_msg"
    ERRORS=$((ERRORS + 1))
  else
    echo "  ✓ $description"
  fi
}

echo "=== Checking required raw data files ==="
echo ""

echo "PLZ boundaries:"
check_file \
  "$RAW_DIR/plz/plz-5stellig.geojson" \
  "PLZ boundary polygons (GeoJSON)" \
  "Run 'make download' to fetch from yetzt/postleitzahlen"

echo ""
echo "Wahlkreis boundaries:"

SHAPEFILE_FOUND=false
for ext in shp shx dbf prj; do
  MATCHED=$(find "$RAW_DIR/bundestag" -name "*.${ext}" 2>/dev/null | head -1)
  if [ -n "$MATCHED" ] && [ -s "$MATCHED" ]; then
    echo "  ✓ Wahlkreis .$ext file"
    SHAPEFILE_FOUND=true
  else
    echo "  ✗ MISSING: Wahlkreis .$ext file"
    echo "    Expected: raw/bundestag/*.$ext"
    echo "    Fix: Run 'make download' — requires GitHub Release v0.1.0-data with Bundeswahlleiterin shapefiles"
    ERRORS=$((ERRORS + 1))
  fi
done

echo ""
echo "Landtag source files:"
python3 "$SCRIPT_DIR/download_landtag.py" check || ERRORS=$((ERRORS + 1))

echo ""
if [ "$ERRORS" -gt 0 ]; then
  echo "=== FAILED: $ERRORS required file(s) missing ==="
  echo "Run 'make download' first, then re-run 'make check'."
  exit 1
else
  echo "=== All required files present ==="
  exit 0
fi
