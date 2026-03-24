"""
Process raw geodata into PLZ-to-Wahlkreis mapping for Bundestag.

Approach:
  1. Load PLZ boundary polygons (from BKG or yetzt/postleitzahlen)
  2. Load Wahlkreis boundary polygons (from Bundeswahlleiterin)
  3. Compute spatial intersection for each PLZ
  4. Calculate area overlap percentage
  5. Output JSON and CSV

Requirements: geopandas, shapely, pandas
"""

# TODO: Implement once raw data is downloaded
# See README.md "Approach" section for detailed algorithm

print("process_bundestag.py: Not yet implemented.")
print("Run 'make download' first, then implement this script.")
