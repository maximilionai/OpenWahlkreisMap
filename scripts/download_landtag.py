#!/usr/bin/env python3
"""Config-driven downloader/checker for Landtag raw source data."""

from __future__ import annotations

import argparse
import csv
import io
import hashlib
import json
import re
import subprocess
import shutil
import sys
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import geopandas as gpd
import pandas as pd
from shapely import to_wkt
import yaml

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONFIGS_DIR = PROJECT_DIR / "configs" / "landtag"
RAW_DIR = PROJECT_DIR / "raw"
LANDTAG_RAW_DIR = RAW_DIR / "landtag"
REPO_BASE = "https://github.com/maximilionai/OpenWahlkreisMap/releases/download"
DATA_TAG = "v0.2.0-data"
VG250_URL = f"{REPO_BASE}/{DATA_TAG}/vg250_gem_utm32s.zip"
VG250_CHECKSUM = "90da099f38d3e252abb8ef028e1afbf70465d73f6ed40e79e1589594e97ab408"

FORMAT_PATTERNS = {
    "csv": ["*.csv"],
    "excel": ["*.xlsx", "*.xls"],
    "shapefile": ["*.shp", "*.shx", "*.dbf", "*.prj"],
    "gml": ["*.gml"],
    "geojson": ["*.geojson", "*.json"],
    "gpkg": ["*.gpkg"],
}


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: Path, expected: str | None) -> None:
    if not expected:
        print(f"  ! Checksum not set for {path.name}")
        return
    actual = sha256sum(path)
    if actual != expected:
        raise RuntimeError(
            f"Checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )
    print(f"  ✓ Checksum OK for {path.name}")


def maybe_verify_checksum(path: Path, expected: str | None, *, label: str | None = None) -> None:
    if expected:
        verify_checksum(path, expected)
    elif label:
        print(f"  ! Checksum not set for {label}")


def verify_geodata_checksum(
    path: Path,
    expected: str | None,
    key_fields: list[str],
    *,
    dissolve_by: str | None = None,
) -> None:
    if not expected:
        print(f"  ! Checksum not set for {path.name}")
        return

    gdf = gpd.read_file(path)
    if dissolve_by and dissolve_by in gdf.columns:
        gdf[dissolve_by] = gdf[dissolve_by].astype(int)
        if gdf[dissolve_by].duplicated().any():
            gdf = gdf.dissolve(by=dissolve_by, as_index=False, aggfunc="first")
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
    actual = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"Checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )
    print(f"  ✓ Checksum OK for {path.name}")


def verify_geodata_footprint_checksum(
    path: Path,
    expected: str | None,
    key_fields: list[str],
    *,
    dissolve_by: str | None = None,
) -> None:
    if not expected:
        print(f"  ! Checksum not set for {path.name}")
        return

    gdf = gpd.read_file(path)
    if dissolve_by and dissolve_by in gdf.columns:
        gdf[dissolve_by] = gdf[dissolve_by].astype(int)
        if gdf[dissolve_by].duplicated().any():
            gdf = gdf.dissolve(by=dissolve_by, as_index=False, aggfunc="first")

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
    actual = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"Checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )
    print(f"  ✓ Checksum OK for {path.name}")


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        subprocess.run(
            ["curl", "-fsSL", "-A", "OpenWahlkreisMap downloader", "-o", str(tmp_path), url],
            check=True,
        )
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def curl_text(url: str) -> str | None:
    result = subprocess.run(
        ["curl", "-fsSL", "-A", "OpenWahlkreisMap downloader", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def infer_mode(config: dict) -> str:
    download = config.get("download", {})
    if download.get("mode"):
        return str(download["mode"])
    if config.get("method") == "manual":
        return "manual"
    if download.get("url"):
        return "auto"
    return "derived"


def infer_filename(config: dict) -> str:
    download = config.get("download", {})
    if download.get("filename"):
        return str(download["filename"])

    url = download.get("url", "")
    path = urllib.parse.urlparse(url).path
    name = Path(path).name
    if name:
        return name

    fmt = download.get("format", "bin")
    suffix = {
        "csv": ".csv",
        "excel": ".xlsx",
        "shapefile": ".zip",
        "gml": ".gml",
        "geojson": ".geojson",
        "gpkg": ".gpkg",
    }.get(fmt, ".bin")
    return f"{config['state']}{suffix}"


def expected_patterns(config: dict) -> tuple[list[str], bool]:
    download = config.get("download", {})
    if download.get("expected_files"):
        return [str(p) for p in download["expected_files"]], True
    if download.get("expected_glob"):
        return [str(download["expected_glob"])], False

    fmt = download.get("format", "csv")
    patterns = FORMAT_PATTERNS.get(fmt, ["*"])
    require_all = fmt == "shapefile"
    return patterns, require_all


def has_expected_files(dest_dir: Path, patterns: list[str], require_all: bool) -> bool:
    if not dest_dir.exists():
        return False
    matches = [bool(list(dest_dir.rglob(pattern))) for pattern in patterns]
    return all(matches) if require_all else any(matches)


def extract_zip(path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        zf.extractall(dest_dir)


def load_configs(selected_state: str | None = None) -> list[dict]:
    configs = []
    for config_path in sorted(CONFIGS_DIR.glob("*.yaml")):
        with config_path.open(encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        if selected_state and config["state"] != selected_state:
            continue
        configs.append(config)
    if selected_state and not configs:
        raise RuntimeError(f"No config found for state '{selected_state}'")
    return configs


def get_hessen_authorities() -> list[tuple[str, str]]:
    text = curl_text("https://wahlen.votemanager.de/behoerden.json")
    if not text:
        raise RuntimeError("Failed to fetch votemanager authority index for Hessen")

    try:
        data = json.loads(text)["data"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError("Failed to parse votemanager authority index for Hessen") from exc

    authorities: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for html, _, state in data:
        if state != "Hessen":
            continue
        match = re.search(r'href="([^"]+)"', html)
        if not match:
            continue
        url = match.group(1)
        parts = urlparse(url)
        segments = [segment for segment in parts.path.split("/") if segment]
        if not segments:
            continue
        ags = segments[0]
        if not ags.endswith("000"):
            continue
        authority = (parts.netloc, ags)
        if authority not in seen:
            seen.add(authority)
            authorities.append(authority)

    return sorted(authorities)


def match_hessen_landtag_term(terms: list[dict], election_date: str) -> dict | None:
    for term in terms:
        name = str(term.get("name", "")).lower()
        if term.get("date") == election_date and "landtag" in name:
            return term
    return None


def get_term_date_slug(term: dict) -> str | None:
    url = term.get("url") or term.get("url_alt") or ""
    match = re.search(r"\.\./([^/]+)/", url)
    if match:
        return match.group(1)
    return None


def build_hessen_dataset(config: dict, dest_dir: Path) -> None:
    election_date = config["download"].get("election_date", "08.10.2023")
    output_name = config["download"].get("filename", "gemeinden_wahlkreise.csv")
    output_path = dest_dir / output_name

    def probe(args: tuple[str, str]) -> tuple[str, str, str] | None:
        host, ags = args
        text = curl_text(f"https://{host}/{ags}/api/termine.json")
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        term = match_hessen_landtag_term(data.get("termine", []), election_date)
        if not term:
            return None
        date_slug = get_term_date_slug(term)
        if not date_slug:
            return None
        return (host, ags, date_slug)

    print("  → Probing ekom21 authority sites for Hessen")
    authorities: list[tuple[str, str, str]] = []
    with ThreadPoolExecutor(max_workers=16) as executor:
        for result in executor.map(probe, get_hessen_authorities()):
            if result:
                authorities.append(result)

    if not authorities:
        raise RuntimeError("No Hessen ekom21 authority sites found for Landtagswahl 2023")

    rows: set[tuple[str, int, str]] = set()
    wk_name_pattern = re.compile(r"Wahlkreis\s+(\d+)\s+-\s*(.+)$")
    wk_csv_pattern = re.compile(r"Gemeinden \(Wahlkreis: (\d+)\)")

    for host, ags, date_slug in sorted(authorities):
        base = f"https://{host}/{date_slug}/{ags}/daten"
        open_data_text = curl_text(base + "/opendata/open_data.json")
        termin_text = curl_text(base + "/api/termin.json")
        if not open_data_text or not termin_text:
            continue

        open_data = json.loads(open_data_text)
        termin = json.loads(termin_text)
        wk_names: dict[int, str] = {}

        for entry in termin.get("wahleintraege", []):
            title = entry.get("wahl", {}).get("titel", "")
            match = wk_name_pattern.search(title)
            if match:
                wk_names[int(match.group(1))] = match.group(2).strip()

        for item in open_data.get("csvs", []):
            ebene = item.get("ebene", "")
            match = wk_csv_pattern.match(ebene)
            if not match:
                continue

            wk_nr = int(match.group(1))
            wk_name = wk_names.get(wk_nr, f"Wahlkreis {wk_nr}")
            csv_text = curl_text(base + "/opendata/" + item["url"])
            if not csv_text:
                continue

            reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
            for record in reader:
                record_ags = str(record["ags"]).strip().zfill(8)
                rows.add((record_ags, wk_nr, wk_name))

    if not rows:
        raise RuntimeError("Failed to build Hessen Gemeinden→Wahlkreis dataset from ekom21 sources")

    dest_dir.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ags", "wk_nr", "wk_name"])
        for ags, wk_nr, wk_name in sorted(rows):
            writer.writerow([ags, wk_nr, wk_name])

    verify_checksum(output_path, config["download"].get("generated_checksum_sha256"))
    print(f"  ✓ Generated Hessen source file at {output_path}")


def normalize_berlin_zip_wahlkreise(source_path: Path, mapping_path: Path, output_path: Path) -> None:
    gdf = gpd.read_file(source_path)
    if "wk_nr" in gdf.columns and "wk_name" in gdf.columns:
        normalized = gdf[["wk_nr", "wk_name", "geometry"]].copy()
        normalized["wk_nr"] = normalized["wk_nr"].astype(int)
        normalized.to_file(output_path, driver="GeoJSON")
        return

    if "AWK" not in gdf.columns:
        raise RuntimeError(
            f"Berlin ZIP shapefile missing expected constituency code column: {list(gdf.columns)}"
        )

    mapping = pd.read_csv(mapping_path, dtype=str)
    mapping["wk_nr"] = mapping["bezirk"].astype(int) * 100 + mapping["wk_local"].astype(int)
    wk_names = mapping.drop_duplicates("wk_nr").set_index("wk_nr")["wk_name"]

    normalized = gdf.copy()
    normalized["wk_nr"] = normalized["AWK"].astype(str).str.zfill(4).astype(int)
    normalized["wk_name"] = normalized["wk_nr"].map(wk_names)
    if normalized["wk_name"].isna().any():
        missing = sorted(normalized.loc[normalized["wk_name"].isna(), "wk_nr"].astype(int).tolist())
        raise RuntimeError(f"Berlin ZIP shapefile has unknown Wahlkreis numbers: {missing}")
    normalized = normalized[["wk_nr", "wk_name", "geometry"]].copy()
    if len(normalized) != 78:
        raise RuntimeError(f"Berlin ZIP normalization produced {len(normalized)} Wahlkreise, expected 78")
    normalized.to_file(output_path, driver="GeoJSON")


def build_berlin_dataset(config: dict, dest_dir: Path) -> None:
    download = config["download"]
    zip_path = PROJECT_DIR / download.get("local_zip_path", "raw/landtag/berlin/RBS_OD_Wahlkreise_AH2026.zip")
    output_path = dest_dir / download.get("source_file", "wahlkreise.geojson")

    mapping_template = PROJECT_DIR / download.get("name_lookup", "")
    if not mapping_template.exists():
        raise RuntimeError(f"Berlin name lookup not found: {mapping_template}")

    dest_dir.mkdir(parents=True, exist_ok=True)

    def try_zip_archive(archive_path: Path, *, source_label: str) -> bool:
        expected_output_checksum = download.get(
            "zip_generated_checksum_sha256",
            download.get("generated_checksum_sha256"),
        )
        expected_output_mode = download.get(
            "zip_generated_checksum_mode",
            download.get("generated_checksum_mode"),
        )
        try:
            if not zipfile.is_zipfile(archive_path):
                print(f"  ! {source_label} did not provide a valid ZIP archive")
                return False

            maybe_verify_checksum(archive_path, download.get("checksum_sha256"), label=archive_path.name)
            print(f"  → Extracting Berlin Wahlkreise ZIP from {source_label}")
            extract_zip(archive_path, dest_dir)
            shp_files = sorted(dest_dir.rglob("*.shp"))
            if not shp_files:
                raise RuntimeError("Berlin ZIP extracted without any shapefile")
            print("  → Converting Berlin Wahlkreise shapefile to normalized GeoJSON")
            normalize_berlin_zip_wahlkreise(shp_files[0], mapping_template, output_path)
            if expected_output_mode == "geodata":
                verify_geodata_checksum(output_path, expected_output_checksum, ["wk_nr", "wk_name"])
            else:
                maybe_verify_checksum(output_path, expected_output_checksum, label=output_path.name)
            print(f"  ✓ Downloaded direct Berlin source files in {dest_dir}")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"  ! Berlin ZIP processing failed for {source_label} ({exc})")
            return False
    if zip_path.exists():
        print(f"  → Using repo-local Berlin Wahlkreise ZIP: {zip_path}")
        if try_zip_archive(zip_path, source_label=str(zip_path)):
            return

    raise RuntimeError(
        "Berlin requires the official Wahlkreise ZIP at "
        f"{zip_path}. See README.md for the manual acquisition step."
    )


def build_hamburg_dataset(config: dict, dest_dir: Path) -> None:
    download = config["download"]
    output_path = dest_dir / download.get("source_file", infer_filename(config))
    dest_dir.mkdir(parents=True, exist_ok=True)

    print("  → Downloading Hamburg Bürgerschaftswahlkreise from LGV WFS")
    download_file(str(download["url"]), output_path)
    if download.get("checksum_mode") == "geodata":
        verify_geodata_checksum(
            output_path,
            download.get("checksum_sha256"),
            ["wahlkreisnummer", "wahlkreisname", "wahl_datum"],
            dissolve_by="wahlkreisnummer",
        )
    elif download.get("checksum_mode") == "geodata_footprint":
        verify_geodata_footprint_checksum(
            output_path,
            download.get("checksum_sha256"),
            ["wahlkreisnummer", "wahlkreisname", "wahl_datum"],
            dissolve_by="wahlkreisnummer",
        )
    else:
        maybe_verify_checksum(output_path, download.get("checksum_sha256"), label=output_path.name)
    print(f"  ✓ Downloaded Hamburg source file at {output_path}")


def build_inline_prefix_dataset(config: dict, dest_dir: Path) -> None:
    download = config["download"]
    rows = config.get("landkreis_prefix_mapping", [])
    if not rows:
        raise RuntimeError(f"{config['state']}: no landkreis_prefix_mapping configured")

    output_path = dest_dir / download.get("source_file", infer_filename(config))
    dest_dir.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ags_prefix", "wk_nr", "wk_name"])
        for row in rows:
            writer.writerow([row["ags_prefix"], row["wk_nr"], row["wk_name"]])

    print(f"  ✓ Generated inline Landkreis-prefix CSV at {output_path}")


def build_inline_plz_dataset(config: dict, dest_dir: Path) -> None:
    download = config["download"]
    rows = config.get("plz_mapping", [])
    if not rows:
        raise RuntimeError(f"{config['state']}: no plz_mapping configured")

    output_path = dest_dir / download.get("source_file", infer_filename(config))
    dest_dir.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["plz", "wk_nr", "wk_name"])
        for row in rows:
            wk_nr = row["wk_nr"]
            wk_name = row["wk_name"]
            for plz in row["plz"]:
                writer.writerow([str(plz).zfill(5), wk_nr, wk_name])

    print(f"  ✓ Generated inline PLZ mapping CSV at {output_path}")


def ensure_vg250(force: bool = False) -> None:
    print("=== VG250 Gemeinden boundaries (shared) ===")
    dest_dir = RAW_DIR / "municipality"
    shp_path = dest_dir / "VG250_GEM.shp"
    zip_path = dest_dir / "vg250_gem_utm32s.zip"

    if shp_path.exists() and not force:
        print("  ✓ VG250 already extracted")
        return

    print("  → Downloading vg250_gem_utm32s.zip")
    download_file(VG250_URL, zip_path)
    verify_checksum(zip_path, VG250_CHECKSUM)
    print("  → Extracting VG250 shapefiles")
    extract_zip(zip_path, dest_dir)
    zip_path.unlink(missing_ok=True)
    if not shp_path.exists():
        raise RuntimeError(f"Expected extracted shapefile at {shp_path}")
    print("  ✓ VG250 ready")


def describe_skip(config: dict, mode: str) -> str:
    notes = config.get("download", {}).get("notes")
    if notes:
        return str(notes)
    if mode == "manual":
        return "manual source preparation required"
    return "derived source preparation required"


def download_state(config: dict, force: bool = False) -> bool:
    state = config["state"]
    download = config.get("download", {})
    mode = infer_mode(config)
    dest_dir = LANDTAG_RAW_DIR / download.get("raw_subdir", state)
    patterns, require_all = expected_patterns(config)

    print(f"\n=== {config['state_name']} ({state}) ===")

    if mode != "auto":
        print(f"  - Skipped ({mode}): {describe_skip(config, mode)}")
        return True

    if has_expected_files(dest_dir, patterns, require_all) and not force:
        print(f"  ✓ Raw source already present in {dest_dir}")
        return True

    strategy = download.get("strategy")
    if strategy == "hessen_votemanager":
        output_name = download.get("filename", "gemeinden_wahlkreise.csv")
        output_path = dest_dir / output_name
        if output_path.exists() and not force:
            verify_checksum(output_path, download.get("generated_checksum_sha256"))
            print(f"  ✓ Raw source already present in {output_path}")
            return True
        build_hessen_dataset(config, dest_dir)
        return True
    if strategy == "berlin_zip":
        build_berlin_dataset(config, dest_dir)
        return True
    if strategy == "hamburg_wfs":
        build_hamburg_dataset(config, dest_dir)
        return True
    if strategy == "inline_landkreis_prefix":
        build_inline_prefix_dataset(config, dest_dir)
        return True
    if strategy == "inline_plz_mapping":
        build_inline_plz_dataset(config, dest_dir)
        return True

    url = download.get("url")
    if not url:
        raise RuntimeError(f"{state}: download.mode=auto but no URL is configured")

    filename = infer_filename(config)
    archive = download.get("archive")
    if not archive and filename.endswith(".zip"):
        archive = "zip"

    dest_dir.mkdir(parents=True, exist_ok=True)
    file_path = dest_dir / filename

    print(f"  → Downloading {filename}")
    download_file(str(url), file_path)
    verify_checksum(file_path, download.get("checksum_sha256"))

    if archive == "zip":
        print(f"  → Extracting {filename}")
        extract_zip(file_path, dest_dir)
        file_path.unlink(missing_ok=True)

    if not has_expected_files(dest_dir, patterns, require_all):
        raise RuntimeError(
            f"{state}: downloaded source but expected files were not found in {dest_dir}"
        )

    print(f"  ✓ Source ready in {dest_dir}")
    return True


def check_state(config: dict) -> tuple[bool, str]:
    state = config["state"]
    download = config.get("download", {})
    mode = infer_mode(config)
    dest_dir = LANDTAG_RAW_DIR / download.get("raw_subdir", state)
    patterns, require_all = expected_patterns(config)

    if mode != "auto":
        return True, f"{state}: skipped ({mode})"
    if has_expected_files(dest_dir, patterns, require_all):
        return True, f"{state}: ok"
    return False, f"{state}: missing raw files in {dest_dir}"


def cmd_download(args: argparse.Namespace) -> int:
    ensure_vg250(force=args.force)
    configs = load_configs(args.state)
    ok = True
    for config in configs:
        try:
            download_state(config, force=args.force)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  ✗ {config['state']}: {exc}")
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    print("=== Checking Landtag raw source files ===")
    errors = 0

    vg250_path = RAW_DIR / "municipality" / "VG250_GEM.shp"
    if vg250_path.exists() and vg250_path.stat().st_size > 0:
        print("  ✓ VG250 Gemeinden shapefile")
    else:
        print(f"  ✗ Missing VG250 Gemeinden shapefile: {vg250_path}")
        errors += 1

    for config in load_configs(args.state):
        ok, message = check_state(config)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {message}")
        if not ok:
            errors += 1

    return 0 if errors == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download or check Landtag source data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download raw source data")
    download_parser.add_argument("--state", help="Only download a single state by slug")
    download_parser.add_argument("--force", action="store_true", help="Re-download even if files exist")
    download_parser.set_defaults(func=cmd_download)

    check_parser = subparsers.add_parser("check", help="Check raw source availability")
    check_parser.add_argument("--state", help="Only check a single state by slug")
    check_parser.set_defaults(func=cmd_check)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
