# Contributing to OpenWahlkreisMap

Thank you for your interest in contributing!

## How to Help

### Data verification
The most valuable contribution is verifying the PLZ→Wahlkreis mapping for your area. If you find an incorrect assignment, please open an issue with:
- The PLZ in question
- The expected Wahlkreis (number and name)
- The source of your information (e.g., your Wahlbenachrichtigung, the Landeswahlleiter website)

### Adding Landtag data
We're building out Landtag constituency mappings state by state. If you have access to official constituency-to-municipality assignment data for your Bundesland, we'd love your help. See the `scripts/` directory for how existing mappings are structured.

### Code contributions
1. Fork the repository
2. Create a feature branch
3. Run `npm run release:check` or `make verify` to ensure your changes pass the published-package checks
4. Submit a pull request

## Reproducing the Dataset

```bash
# Set up Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Download source data (not tracked in git)
make download

# Run fast unit + fixture tests
make test

# Process and generate mapping
make process

# Run release-gate verification
make verify

# Rebuild API + npm bundle from tracked data
npm run build:data
```

`make download-landtag` downloads all states with direct source URLs and prints notes for the remaining manual inputs. Berlin additionally requires the official ZIP to be copied to `raw/landtag/berlin/RBS_OD_Wahlkreise_AH2026.zip`.

## Code of Conduct

Be respectful and constructive. This is a civic tech project — we're here to make democracy more accessible.
