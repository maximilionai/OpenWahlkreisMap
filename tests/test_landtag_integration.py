from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

import process_landtag


def _write_geojson(path: Path, rows: list[dict], crs: str = "EPSG:25832") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    gdf.to_file(path, driver="GeoJSON")


@pytest.fixture
def isolated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project_dir = tmp_path / "project"
    (project_dir / "raw" / "landtag").mkdir(parents=True)
    (project_dir / "raw" / "plz").mkdir(parents=True)
    (project_dir / "raw" / "municipality").mkdir(parents=True)

    monkeypatch.setattr(process_landtag, "PROJECT_DIR", project_dir)
    monkeypatch.setattr(process_landtag, "RAW_PLZ_PATH", project_dir / "raw" / "plz" / "plz-5stellig.geojson")
    monkeypatch.setattr(process_landtag, "PLZ_AGS_CACHE", project_dir / "raw" / "municipality" / "plz-ags-mapping.parquet")
    monkeypatch.setattr(process_landtag, "_plz_gdf_cache", None)
    return project_dir


def test_process_spatial_with_real_fixture_geometries(isolated_project: Path) -> None:
    _write_geojson(
        isolated_project / "raw" / "plz" / "plz-5stellig.geojson",
        [
            {"plz": "10000", "geometry": Polygon([(0, 0), (0, 2), (2, 2), (2, 0)])},
            {"plz": "10001", "geometry": Polygon([(2, 0), (2, 2), (4, 2), (4, 0)])},
        ],
    )
    _write_geojson(
        isolated_project / "raw" / "landtag" / "spatial" / "wahlkreise.geojson",
        [
            {"wk_nr": 1, "wk_name": "West", "geometry": Polygon([(0, 0), (0, 2), (3, 2), (3, 0)])},
            {"wk_nr": 2, "wk_name": "East", "geometry": Polygon([(3, 0), (3, 2), (4, 2), (4, 0)])},
        ],
    )

    config = {
        "state": "mock-spatial",
        "period_id": 123,
        "expected_wk_count": 2,
        "download": {"raw_subdir": "spatial", "source_file": "wahlkreise.geojson", "format": "geojson"},
        "columns": {"wk_nr": "wk_nr", "wk_name": "wk_name"},
    }

    mapping = process_landtag.process_spatial(config)

    assert mapping["10000"]["primary"] == 1
    assert mapping["10001"]["primary"] == 1
    assert len(mapping["10001"]["wahlkreise"]) == 2


def test_process_municipality_join_with_small_fixture(
    isolated_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pd.DataFrame(
        [
            {"plz": "20000", "ags": "01001001", "overlap": 0.6},
            {"plz": "20000", "ags": "01001002", "overlap": 0.4},
            {"plz": "20001", "ags": "01001002", "overlap": 1.0},
        ]
    ).to_parquet(isolated_project / "raw" / "municipality" / "plz-ags-mapping.parquet", index=False)

    source_dir = isolated_project / "raw" / "landtag" / "join"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "ags.csv").write_text(
        "ags,wk_nr,wk_name\n01001001,10,Nord\n01001002,11,Sued\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        process_landtag,
        "get_parser",
        lambda _config: (lambda path, _cfg: pd.read_csv(path, dtype={"ags": str})),
    )

    config = {
        "state": "mock-join",
        "period_id": 456,
        "download": {"raw_subdir": "join", "format": "csv", "source_file": "ags.csv"},
        "parser": "custom_csv",
    }

    mapping = process_landtag.process_municipality_join(config)

    assert mapping["20000"]["primary"] == 10
    assert {wk["nr"] for wk in mapping["20000"]["wahlkreise"]} == {10, 11}
    assert mapping["20001"]["primary"] == 11


def test_process_plz_mapping_with_small_fixture(isolated_project: Path) -> None:
    source_dir = isolated_project / "raw" / "landtag" / "plz"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "mapping.csv").write_text(
        "plz,wk_nr,wk_name\n30000,20,Zentrum\n30001,21,Nord\n",
        encoding="utf-8",
    )

    config = {
        "state": "mock-plz",
        "period_id": 789,
        "download": {"raw_subdir": "plz", "source_file": "mapping.csv"},
        "parser": "plz_mapping",
    }

    mapping = process_landtag.process_plz_mapping(config)

    assert mapping == {
        "30000": {
            "wahlkreise": [{"nr": 20, "name": "Zentrum", "overlap": 1.0}],
            "primary": 20,
            "period_id": 789,
        },
        "30001": {
            "wahlkreise": [{"nr": 21, "name": "Nord", "overlap": 1.0}],
            "primary": 21,
            "period_id": 789,
        },
    }
