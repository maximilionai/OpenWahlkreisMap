#!/usr/bin/env bash
# Wrapper for the config-driven Landtag downloader.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/download_landtag.py" download "$@"
