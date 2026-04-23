from __future__ import annotations

import zipfile
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon
from shapely import to_wkt

from download_landtag import (
    normalize_berlin_zip_wahlkreise,
    verify_checksum,
    verify_geodata_checksum,
    verify_geodata_footprint_checksum,
)


def _write_geojson(path: Path, rows: list[dict], crs: str = "EPSG:25832") -> None:
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    gdf.to_file(path, driver="GeoJSON")


def _geodata_checksum(path: Path, key_fields: list[str]) -> str:
    gdf = gpd.read_file(path)
    rows = []
    for _, row in gdf.iterrows():
        entry = {field: row[field] for field in key_fields}
        for field, value in list(entry.items()):
            if isinstance(value, float) and value.is_integer():
                entry[field] = int(value)
            else:
                entry[field] = value if isinstance(value, int) else str(value)
        geometry = row.geometry.normalize() if hasattr(row.geometry, "normalize") else row.geometry
        entry["wkt"] = to_wkt(geometry, rounding_precision=3)
        rows.append(entry)
    rows.sort(key=lambda item: tuple(item[field] for field in key_fields) + (item["wkt"],))
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _geodata_footprint_checksum(path: Path, key_fields: list[str]) -> str:
    gdf = gpd.read_file(path)
    rows = []
    for _, row in gdf.iterrows():
        entry = {field: row[field] for field in key_fields}
        for field, value in list(entry.items()):
            if isinstance(value, float) and value.is_integer():
                entry[field] = int(value)
            else:
                entry[field] = value if isinstance(value, int) else str(value)
        entry["area"] = round(float(row.geometry.area), 3)
        entry["bounds"] = [round(float(coord), 3) for coord in row.geometry.bounds]
        rows.append(entry)
    rows.sort(key=lambda item: tuple(item[field] for field in key_fields))
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_verify_checksum_accepts_matching_hash(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("hello\n", encoding="utf-8")

    verify_checksum(path, "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03")


def test_verify_checksum_rejects_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("hello\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        verify_checksum(path, "deadbeef")


def test_verify_geodata_checksum_and_footprint(tmp_path: Path) -> None:
    path = tmp_path / "sample.geojson"
    _write_geojson(
        path,
        [
            {"wk_nr": 1, "wk_name": "A", "geometry": Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])},
            {"wk_nr": 2, "wk_name": "B", "geometry": Polygon([(1, 0), (1, 1), (2, 1), (2, 0)])},
        ],
    )

    verify_geodata_checksum(
        path,
        _geodata_checksum(path, ["wk_nr", "wk_name"]),
        ["wk_nr", "wk_name"],
    )
    verify_geodata_footprint_checksum(
        path,
        _geodata_footprint_checksum(path, ["wk_nr", "wk_name"]),
        ["wk_nr", "wk_name"],
    )


def test_normalize_berlin_zip_wahlkreise_from_official_schema(tmp_path: Path) -> None:
    shp_dir = tmp_path / "shape"
    shp_dir.mkdir()
    shapefile_path = shp_dir / "AWK_AH2026.shp"
    output_path = tmp_path / "wahlkreise.geojson"
    mapping_path = tmp_path / "berlin_lookup.csv"

    rows = []
    mapping_rows = []
    for wk_local in range(1, 79):
        x0 = wk_local - 1
        rows.append(
            {
                "AWK": f"01{wk_local:02d}",
                "BEZ": "01",
                "AWK2": f"{wk_local:02d}",
                "geometry": Polygon([(x0, 0), (x0, 1), (x0 + 1, 1), (x0 + 1, 0)]),
            }
        )
        mapping_rows.append(
            {"bezirk": "01", "wk_local": f"{wk_local:02d}", "wk_name": f"Mitte {wk_local:02d}"}
        )

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:25832")
    gdf.to_file(shapefile_path)

    pd.DataFrame(mapping_rows).to_csv(mapping_path, index=False)

    normalize_berlin_zip_wahlkreise(shapefile_path, mapping_path, output_path)

    normalized = gpd.read_file(output_path).sort_values("wk_nr")
    assert len(normalized) == 78
    assert normalized.iloc[0][["wk_nr", "wk_name"]].to_dict() == {"wk_nr": 101, "wk_name": "Mitte 01"}
    assert normalized.iloc[-1][["wk_nr", "wk_name"]].to_dict() == {"wk_nr": 178, "wk_name": "Mitte 78"}
