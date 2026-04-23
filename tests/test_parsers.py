from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from lib.errors import SourceDataError, ValidationError
from lib.parsers import parse_landkreis_prefix, parse_plz_mapping, validate_parser_output


def test_validate_parser_output_normalizes_and_deduplicates() -> None:
    df = pd.DataFrame(
        [
            {"ags": "123456", "wk_nr": "7", "wk_name": " North "},
            {"ags": "00123456", "wk_nr": 7, "wk_name": "North"},
        ]
    )

    result = validate_parser_output(
        df,
        parser_name="test_parser",
        allow_multi_wk_per_ags=False,
    )

    assert result.to_dict(orient="records") == [
        {"ags": "00123456", "wk_nr": 7, "wk_name": "North"}
    ]


def test_validate_parser_output_rejects_split_ags_when_disallowed() -> None:
    df = pd.DataFrame(
        [
            {"ags": "01001000", "wk_nr": 1, "wk_name": "A"},
            {"ags": "01001000", "wk_nr": 2, "wk_name": "B"},
        ]
    )

    with pytest.raises(ValidationError, match="map to multiple Wahlkreise"):
        validate_parser_output(
            df,
            parser_name="test_parser",
            allow_multi_wk_per_ags=False,
        )


def test_parse_plz_mapping_normalizes_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "mapping.csv"
    path.write_text(
        "plz,wk_nr,wk_name\n"
        "101,1, Mitte \n"
        "00101,1,Mitte\n",
        encoding="utf-8",
    )

    result = parse_plz_mapping(path, {})

    assert result.to_dict(orient="records") == [
        {"plz": "00101", "wk_nr": 1, "wk_name": "Mitte"}
    ]


def test_parse_plz_mapping_rejects_bad_plz(tmp_path: Path) -> None:
    path = tmp_path / "mapping.csv"
    path.write_text("plz,wk_nr,wk_name\n12A45,1,Bad\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid PLZ"):
        parse_plz_mapping(path, {})


def test_parse_landkreis_prefix_expands_using_cached_plz_ags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lib.municipality as municipality

    monkeypatch.setattr(
        municipality,
        "load_plz_ags_mapping",
        lambda _path: pd.DataFrame(
            [
                {"plz": "10000", "ags": "12010001", "overlap": 1.0},
                {"plz": "10001", "ags": "12010002", "overlap": 1.0},
                {"plz": "20000", "ags": "13000001", "overlap": 1.0},
            ]
        ),
    )

    config = {
        "landkreis_prefix_mapping": [
            {"ags_prefix": "12010", "wk_nr": 3, "wk_name": "Berlin-Nord"},
        ]
    }

    result = parse_landkreis_prefix(None, config)

    assert result.to_dict(orient="records") == [
        {"ags": "12010001", "wk_nr": 3, "wk_name": "Berlin-Nord"},
        {"ags": "12010002", "wk_nr": 3, "wk_name": "Berlin-Nord"},
    ]


def test_parse_plz_mapping_requires_columns(tmp_path: Path) -> None:
    path = tmp_path / "mapping.csv"
    path.write_text("plz,wk_nr\n10115,1\n", encoding="utf-8")

    with pytest.raises(SourceDataError, match="missing required columns"):
        parse_plz_mapping(path, {})
