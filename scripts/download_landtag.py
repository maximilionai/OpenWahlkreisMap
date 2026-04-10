#!/usr/bin/env python3
"""Config-driven downloader/checker for Landtag raw source data."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import shutil
import sys
import urllib.parse
import zipfile
from pathlib import Path

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
