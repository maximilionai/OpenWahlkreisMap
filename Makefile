.PHONY: all download process verify clean

all: download process verify

# Download raw source data (not tracked in git)
download:
	@echo "Downloading source data to raw/..."
	@mkdir -p raw
	bash scripts/download_sources.sh

# Process raw data into final mapping
process:
	@echo "Processing PLZ-to-Wahlkreis mapping..."
	python3 scripts/process_bundestag.py

# Run verification suite
verify:
	@echo "Verifying mapping..."
	python3 scripts/verify.py

# Remove raw downloads and intermediate files
clean:
	rm -rf raw/ tmp/
	@echo "Cleaned raw/ and tmp/"
