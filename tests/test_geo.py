from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from lib.errors import SourceDataError
from lib.geo import load_constituency_polygons


def _write_geojson(path: Path, rows: list[dict]) -> None:
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:25832")
    gdf.to_file(path, driver="GeoJSON")


def test_load_constituency_polygons_detects_keyword_columns(tmp_path: Path) -> None:
    path = tmp_path / "wahlkreise.geojson"
    _write_geojson(
        path,
        [
            {
                "WKR_NR": 1,
                "WKR_NAME": "Nord",
                "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            },
        ],
    )

    gdf = load_constituency_polygons(path, fmt="geojson", expected_count=1)

    assert gdf.iloc[0][["wk_nr", "wk_name"]].to_dict() == {"wk_nr": 1, "wk_name": "Nord"}


def test_load_constituency_polygons_rejects_generic_string_fallback(tmp_path: Path) -> None:
    path = tmp_path / "wahlkreise.geojson"
    _write_geojson(
        path,
        [
            {
                "WKR_NR": 1,
                "county": "Kreis A",
                "description": "Should not become the constituency name",
                "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            },
        ],
    )

    with pytest.raises(SourceDataError, match="Cannot identify constituency number and name columns"):
        load_constituency_polygons(path, fmt="geojson", expected_count=1)


def test_load_constituency_polygons_rejects_ambiguous_name_columns(tmp_path: Path) -> None:
    path = tmp_path / "wahlkreise.geojson"
    _write_geojson(
        path,
        [
            {
                "WKR_NR": 1,
                "wahlkreis_name": "Nord",
                "wahlkreis_bezeichnung": "WK 1 Nord",
                "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            },
        ],
    )

    with pytest.raises(SourceDataError, match="Ambiguous constituency name columns"):
        load_constituency_polygons(path, fmt="geojson", expected_count=1)


def test_load_constituency_polygons_allows_explicit_generic_columns(tmp_path: Path) -> None:
    path = tmp_path / "wahlkreise.geojson"
    _write_geojson(
        path,
        [
            {
                "number": 1,
                "label": "Nord",
                "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            },
        ],
    )

    gdf = load_constituency_polygons(
        path,
        fmt="geojson",
        col_map={"number": "wk_nr", "label": "wk_name"},
        expected_count=1,
    )

    assert gdf.iloc[0][["wk_nr", "wk_name"]].to_dict() == {"wk_nr": 1, "wk_name": "Nord"}
