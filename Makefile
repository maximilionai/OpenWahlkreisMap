.PHONY: all download download-landtag check process process-bundestag \
       process-landtag process-landtag-plz-ags verify build-api verify-api clean

all: download process verify build-api

# Download raw source data (not tracked in git)
download: download-bundestag download-landtag

download-bundestag:
	@echo "Downloading Bundestag source data..."
	@mkdir -p raw
	bash scripts/download_sources.sh

download-landtag:
	@echo "Downloading Landtag source data..."
	@mkdir -p raw
	bash scripts/download_landtag.sh

# Validate required raw files exist
check:
	@bash scripts/check_raw_data.sh

# Process raw data into final mapping (runs check first)
process: check process-bundestag process-landtag

# Bundestag PLZ-to-Wahlkreis mapping
process-bundestag:
	@echo "Processing Bundestag PLZ-to-Wahlkreis mapping..."
	python3 scripts/process_bundestag.py

# Landtag processing
process-landtag: process-landtag-plz-ags
	@echo "Processing Landtag PLZ-to-Wahlkreis mapping (all states)..."
	python3 scripts/process_landtag.py --all

process-landtag-plz-ags:
	@echo "Building PLZ-AGS mapping..."
	python3 scripts/process_landtag.py --build-plz-ags

# Per-state processing (e.g., make process-landtag-berlin)
process-landtag-%:
	python3 scripts/process_landtag.py --state $*

# Run verification suite
verify:
	@echo "Verifying mapping..."
	python3 scripts/verify.py

# Build per-PLZ API files for static hosting
build-api:
	@echo "Building per-PLZ API files..."
	python3 scripts/build_api.py

# Verify API output
verify-api:
	@echo "Verifying API output..."
	python3 scripts/verify.py --scope api

# Remove raw downloads and intermediate files
clean:
	rm -rf raw/ tmp/
	@echo "Cleaned raw/ and tmp/"
