"""State-specific data parsers for Landtag constituency data."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .errors import SourceDataError, ValidationError

log = logging.getLogger(__name__)


def validate_parser_output(
    df: pd.DataFrame,
    *,
    parser_name: str,
    allow_multi_wk_per_ags: bool,
) -> pd.DataFrame:
    """Validate and normalize parser output before municipality joins."""
    required = ["ags", "wk_nr", "wk_name"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise SourceDataError(f"{parser_name}: missing required columns {missing}")

    result = df[required].copy()
    result = result.dropna(subset=["ags", "wk_nr", "wk_name"])
    result["ags"] = result["ags"].astype(str).str.strip().str.zfill(8)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    bad_ags = result[~result["ags"].str.fullmatch(r"\d{8}")]
    if not bad_ags.empty:
        raise ValidationError(f"{parser_name}: found {len(bad_ags)} rows with invalid AGS codes")

    result = result.drop_duplicates(subset=["ags", "wk_nr", "wk_name"])
    multi_assignments = result.groupby("ags")["wk_nr"].nunique()
    split_ags = multi_assignments[multi_assignments > 1]
    if not allow_multi_wk_per_ags and not split_ags.empty:
        sample = ", ".join(split_ags.index[:5])
        raise ValidationError(
            f"{parser_name}: {len(split_ags)} AGS codes map to multiple Wahlkreise "
            f"but this parser is configured for single-assignment sources. Sample: {sample}"
        )

    if not split_ags.empty:
        log.info("%s: %d AGS codes span multiple Wahlkreise", parser_name, len(split_ags))

    if result.empty:
        raise ValidationError(f"{parser_name}: parser returned no usable rows")

    return result


def parse_excel_generic(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse a state's Excel file using column mappings from YAML config.

    Args:
        path: Path to the Excel file.
        config: The 'excel' section of the state's YAML config, containing:
            sheet_name: Sheet name or index (default: 0)
            header_row: Row number for column headers (default: 0)
            wk_nr_col: Column name for Wahlkreis number
            wk_name_col: Column name for Wahlkreis name
            ags_col: Column name for AGS (Amtlicher Gemeindeschlüssel)

    Returns:
        DataFrame with columns: ags (8-digit str), wk_nr (int), wk_name (str)
    """
    excel_cfg = config.get("excel", {})
    sheet = excel_cfg.get("sheet_name", 0)
    header = excel_cfg.get("header_row", 0)

    log.info("Parsing Excel: %s (sheet=%s, header_row=%d)", path.name, sheet, header)
    df = pd.read_excel(path, sheet_name=sheet, header=header)
    log.info("Excel columns: %s (%d rows)", list(df.columns), len(df))

    wk_nr_col = excel_cfg.get("wk_nr_col")
    wk_name_col = excel_cfg.get("wk_name_col")
    ags_col = excel_cfg.get("ags_col")

    if not all([wk_nr_col, wk_name_col, ags_col]):
        log.error(
            "Excel config must specify wk_nr_col, wk_name_col, and ags_col. Got: %s",
            excel_cfg,
        )
        raise ValueError("Incomplete excel config — missing column names")

    # Select and rename columns
    result = df[[ags_col, wk_nr_col, wk_name_col]].copy()
    result.columns = ["ags", "wk_nr", "wk_name"]

    result = validate_parser_output(
        result,
        parser_name="parse_excel_generic",
        allow_multi_wk_per_ags=bool(config.get("allow_multi_wk_per_ags", False)),
    )

    log.info("Parsed %d AGS-to-WK entries (%d unique WK)", len(result), result["wk_nr"].nunique())
    return result


def parse_landkreis_prefix(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse a CSV mapping AGS prefixes (Landkreis level) to Wahlkreise.

    Used for states where constituencies = collections of Landkreise (e.g., Saarland).
    The CSV has columns: ags_prefix (5-digit), wk_nr, wk_name.
    Expands to all Gemeinde AGS codes that start with each prefix.
    """
    log.info("Parsing Landkreis-prefix CSV: %s", path.name)
    df = pd.read_csv(path, dtype=str)

    # Load full PLZ-AGS mapping to get all Gemeinde AGS codes
    from .municipality import load_plz_ags_mapping
    from pathlib import Path as P
    cache = P(__file__).parent.parent.parent / "raw" / "municipality" / "plz-ags-mapping.parquet"
    plz_ags = load_plz_ags_mapping(cache)

    rows = []
    for _, prefix_row in df.iterrows():
        prefix = prefix_row["ags_prefix"]
        wk_nr = int(prefix_row["wk_nr"])
        wk_name = prefix_row["wk_name"]
        # Find all unique AGS codes with this prefix
        matching = plz_ags[plz_ags["ags"].str.startswith(prefix)]["ags"].unique()
        for ags in matching:
            rows.append({"ags": ags, "wk_nr": wk_nr, "wk_name": wk_name})

    result = validate_parser_output(
        pd.DataFrame(rows),
        parser_name="parse_landkreis_prefix",
        allow_multi_wk_per_ags=bool(config.get("allow_multi_wk_per_ags", False)),
    )
    log.info("Expanded %d prefixes to %d AGS-to-WK entries (%d unique WK)",
             len(df), len(result), result["wk_nr"].nunique())
    return result


def parse_sachsen(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse Sachsen election results Excel to extract AGS→Wahlkreis mapping.

    Sheet 'LW24_endgErgebnisse_GE&TG' has both Gemeinde (GE) and Teilgemeinde (TG)
    rows. TG rows have 9-digit AGS for cities split across multiple WK (Chemnitz,
    Leipzig, Dresden, Zwickau). We truncate these to 8-digit parent Gemeinde AGS
    so they match the PLZ-AGS mapping — the join then distributes overlap equally
    across WK within that city (same approach as NRW split cities).
    """
    sheet = "LW24_endgErgebnisse_GE&TG"
    log.info("Parsing Sachsen election results: %s (sheet=%s)", path.name, sheet)

    df = pd.read_excel(path, sheet_name=sheet, header=0)
    # Filter to GE and TG rows (col 'Ebene.1' due to duplicate column name)
    df = df[df["Ebene.1"].isin(["GE", "TG"])].copy()

    result = df[["AGS", "WK-Nr", "WK-Name"]].copy()
    result.columns = ["ags", "wk_nr", "wk_name"]
    result = result.dropna(subset=["ags", "wk_nr"])

    # Normalize AGS: truncate 9-digit TG codes to 8-digit Gemeinde, zero-pad shorter
    result["ags"] = result["ags"].astype(str).str.strip().str[:8].str.zfill(8)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    # Do NOT deduplicate — split cities have same 8-digit AGS in multiple WK
    result = validate_parser_output(
        result,
        parser_name="parse_sachsen",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_nrw(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse NRW Gemeinde→Wahlkreis CSV (semicolon-delimited, latin-1, 6-digit AGS).

    NRW publishes a CSV where 30 large cities are split across multiple
    Wahlkreise — the same Gemeindenummer appears in multiple WK rows.
    We must keep these duplicates so join_plz_to_wahlkreis can distribute
    PLZ overlap correctly.
    """
    csv_cfg = config.get("csv", {})
    wk_nr_col = csv_cfg.get("wk_nr_col")
    wk_name_col = csv_cfg.get("wk_name_col")
    ags_col = csv_cfg.get("ags_col")

    if not all([wk_nr_col, wk_name_col, ags_col]):
        raise ValueError("NRW config must specify csv.wk_nr_col, wk_name_col, ags_col")

    log.info("Parsing NRW CSV: %s", path.name)
    df = pd.read_csv(path, sep=";", encoding="latin-1")
    log.info("CSV columns: %s (%d rows)", list(df.columns), len(df))

    result = df[[ags_col, wk_nr_col, wk_name_col]].copy()
    result.columns = ["ags", "wk_nr", "wk_name"]
    result = result.dropna(subset=["ags", "wk_nr"])

    # NRW Gemeindenummer is 6-digit — prepend state code "05" for 8-digit AGS
    result["ags"] = "05" + result["ags"].astype(str).str.strip().str.zfill(6)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    # Do NOT deduplicate — split cities legitimately appear in multiple WK
    result = validate_parser_output(
        result,
        parser_name="parse_nrw",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_sachsen_anhalt(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse Sachsen-Anhalt Wahlkreise_Gemeinden.xlsx.

    Sheet 'WKR & GEM', header row 5. WK number and name only on first row
    of each group (needs forward-fill). AGS in 'Gemeinde-schlüssel' col (8-digit).
    Split cities: Magdeburg (4 WK), Halle (4 WK), Dessau-Roßlau (2 WK), etc.
    """
    log.info("Parsing Sachsen-Anhalt: %s", path.name)
    df = pd.read_excel(path, sheet_name="WKR & GEM", header=5)

    # Columns have line breaks from merged header cells
    wk_nr_col = df.columns[0]   # 'Nummer'
    wk_name_col = df.columns[1]  # 'Name'
    ags_col = df.columns[5]      # 'Gemeinde-\nschlüssel'

    # Forward-fill WK number and name (only set on first row of each group)
    df[wk_nr_col] = df[wk_nr_col].ffill()
    df[wk_name_col] = df[wk_name_col].ffill()

    # Drop rows without AGS
    df = df.dropna(subset=[ags_col])

    result = df[[ags_col, wk_nr_col, wk_name_col]].copy()
    result.columns = ["ags", "wk_nr", "wk_name"]
    result["ags"] = result["ags"].astype(float).astype(int).astype(str).str.zfill(8)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    result = validate_parser_output(
        result,
        parser_name="parse_sachsen_anhalt",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_niedersachsen(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse Niedersachsen Landtagswahlkreise XLSX.

    Columns: LANDTAGSWAHLKREIS (int), AGS (6-digit, needs '03' prefix), GEMEINDENAME.
    No WK name column — uses 'Wahlkreis {nr}' as placeholder.
    Split cities: Braunschweig (3 WK), Hannover (5 WK), etc.
    """
    log.info("Parsing Niedersachsen: %s", path.name)
    df = pd.read_excel(path, header=0)

    result = df[["AGS", "LANDTAGSWAHLKREIS"]].copy()
    result.columns = ["ags", "wk_nr"]
    result = result.dropna(subset=["ags", "wk_nr"])

    result["ags"] = "03" + result["ags"].astype(int).astype(str).str.zfill(6)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = "Wahlkreis " + result["wk_nr"].astype(str)

    result = validate_parser_output(
        result,
        parser_name="parse_niedersachsen",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_thueringen(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse Thüringen election results XLSX.

    Sheet 0, header row 3. Filter Satzart='G' for Gemeinde rows.
    AGS reconstructed from Kreisnummer (2-digit) + Gemeindenummer (3-digit):
    '16' + zfill(Kreis,3) + zfill(Gem,3).
    WK number in col 2 (3-digit zero-padded string), WK name from col 6 ('Name').
    """
    log.info("Parsing Thüringen: %s", path.name)
    df_all = pd.read_excel(path, header=3)

    satzart_col = df_all.columns[1]  # 'Satzart'
    wk_col = df_all.columns[2]       # 'Wahl-' (Wahlkreisnummer)
    kreis_col = df_all.columns[3]    # 'Kreis-'
    gem_col = df_all.columns[4]      # 'Ge-'
    name_col = df_all.columns[6]     # 'Name'

    # Build WK name lookup from WK-level rows (Satzart='K')
    wk_rows = df_all[df_all[satzart_col] == "K"]
    wk_names = dict(zip(
        wk_rows[wk_col].astype(int),
        wk_rows[name_col].astype(str).str.strip()
    ))

    # Filter to Gemeinde rows
    df = df_all[df_all[satzart_col] == "G"].copy()

    # Reconstruct 8-digit AGS: "16" + Kreis(3-digit) + Gemeinde(3-digit)
    result = pd.DataFrame()
    result["ags"] = "16" + df[kreis_col].astype(int).astype(str).str.zfill(3) + \
                    df[gem_col].astype(int).astype(str).str.zfill(3)
    result["wk_nr"] = df[wk_col].astype(int)
    result["wk_name"] = result["wk_nr"].map(wk_names).fillna("Wahlkreis " + result["wk_nr"].astype(str))

    result = validate_parser_output(
        result,
        parser_name="parse_thueringen",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_baden_wuerttemberg(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse BW election results CSV (semicolon, UTF-8).

    Filter Gebietsart='GEMEINDE'. For cities without GEMEINDE rows (Stuttgart,
    Karlsruhe, Mannheim — split across multiple WK), fall back to WAHLKREIS rows
    which carry the city AGS. This assigns the city to all its WK, and the
    municipality join distributes overlap equally (same approach as NRW split cities).
    """
    log.info("Parsing Baden-Württemberg: %s", path.name)
    df = pd.read_csv(path, sep=";", low_memory=False)

    gem = df[df["Gebietsart"] == "GEMEINDE"].copy()
    wk_with_gem = set(gem["Wahlkreisnummer"].dropna().astype(int))

    # Add WAHLKREIS rows for WK that have no GEMEINDE rows (split cities)
    all_wk = set(df[df["Gebietsart"] == "WAHLKREIS"]["Wahlkreisnummer"].dropna().astype(int))
    missing_wk = all_wk - wk_with_gem
    if missing_wk:
        city_rows = df[(df["Gebietsart"] == "WAHLKREIS") & (df["Wahlkreisnummer"].isin(missing_wk))]
        gem = pd.concat([gem, city_rows], ignore_index=True)
        log.info("Added %d WAHLKREIS rows for split cities (WK %s)",
                 len(city_rows), sorted(missing_wk))

    result = gem[["AGS", "Wahlkreisnummer", "Wahlkreisname"]].copy()
    result.columns = ["ags", "wk_nr", "wk_name"]
    result = result.dropna(subset=["ags", "wk_nr"])

    result["ags"] = result["ags"].astype(str).str.strip().str.zfill(8)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    result = validate_parser_output(
        result,
        parser_name="parse_baden_wuerttemberg",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_bayern(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse Bayern Gemeindeuebersicht Stimmkreise XLSX.

    No proper header — data starts at row 3. Cols: 0=Schlüssel-Nr (6-digit),
    1=Gemeinde, 6=Stimmkreis Nr, 7=Stimmkreis Name. AGS needs '09' prefix.
    3 cities span multiple SK as ranges (e.g. '101-109' for München):
    these are expanded so the city AGS appears once per SK.
    """
    log.info("Parsing Bayern: %s", path.name)
    df = pd.read_excel(path, header=None, skiprows=3)

    rows = []
    for _, r in df.iterrows():
        ags_raw = r.iloc[0]
        sk_raw = r.iloc[6]
        sk_name = str(r.iloc[7]).strip() if pd.notna(r.iloc[7]) else ""

        if pd.isna(ags_raw) or pd.isna(sk_raw):
            continue

        ags = "09" + str(int(ags_raw)).zfill(6)

        sk_str = str(sk_raw).strip()
        if "-" in sk_str:
            # Range like '101-109' → expand
            parts = sk_str.split("-")
            start, end = int(parts[0]), int(parts[1])
            for nr in range(start, end + 1):
                rows.append({"ags": ags, "wk_nr": nr, "wk_name": sk_name})
        else:
            rows.append({"ags": ags, "wk_nr": int(float(sk_str)), "wk_name": sk_name})

    result = validate_parser_output(
        pd.DataFrame(rows),
        parser_name="parse_bayern",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_brandenburg(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse Brandenburg LT-Wahlkreiseinteilung2024 sheet.

    Complex layout: WK number in col 0 (only on first row of group, needs ffill),
    WK name in col 1, Gemeinde name in col 5, 12-digit Regionalschlüssel in col 6.
    AGS derived from RS: first 5 digits + last 3 digits. Filter out Amt-level rows
    (which have 9-digit RS) and keep only Gemeinde rows (12-digit RS).
    """
    log.info("Parsing Brandenburg: %s", path.name)
    df = pd.read_excel(path, sheet_name="LT-Wahlkreiseinteilung2024", header=None, skiprows=5)

    # Forward-fill WK number and name
    df.iloc[:, 0] = df.iloc[:, 0].ffill()
    df.iloc[:, 1] = df.iloc[:, 1].ffill()

    # Filter to rows with Regionalschlüssel (col 6)
    df = df.dropna(subset=[df.columns[6]])

    # Keep only Gemeinde-level rows (12-digit RS, not 9-digit Amt rows)
    df["rs_str"] = df.iloc[:, 6].astype(int).astype(str)
    df = df[df["rs_str"].str.len() >= 12].copy()

    # Derive 8-digit AGS: first 5 digits + last 3 digits of 12-digit RS
    df["ags"] = df["rs_str"].str[:5] + df["rs_str"].str[-3:]

    result = pd.DataFrame()
    result["ags"] = df["ags"]
    result["wk_nr"] = df.iloc[:, 0].astype(int)
    result["wk_name"] = df.iloc[:, 1].astype(str).str.strip()

    result = validate_parser_output(
        result,
        parser_name="parse_brandenburg",
        allow_multi_wk_per_ags=True,
    )

    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_rheinland_pfalz(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse RLP LW_2021_GESAMT.xlsx (hierarchical election results).

    13-digit ID: B WW KKK VV GGG TT where B=Bezirk (1-4), WW=WK number.
    Filter: GUW='G', Bezirk>0, Stimmbezirk=0, gem_code!='000'.
    AGS = '07' + ID[3:6] + ID[7:10]. WK number = int(ID[1:3]).
    WK names from WK header rows (B>0, WW>0, rest=0).
    """
    log.info("Parsing Rheinland-Pfalz: %s", path.name)
    df = pd.read_excel(path, header=0, dtype={"ID": str})
    df = df[df["GUW"] == "G"].copy()
    df["ID"] = df["ID"].astype(str).str.zfill(13)

    # Build WK name lookup from WK header rows
    wk_headers = df[(df["ID"].str[0] != "0") &
                     (df["ID"].str[1:3] != "00") &
                     (df["ID"].str[3:13] == "0000000000")]
    wk_names = {}
    for _, r in wk_headers.iterrows():
        wk_nr = int(r["ID"][1:3])
        name = str(r["Bezeichnung"]).replace(", Wahlkreis", "").strip()
        wk_names[wk_nr] = name

    # Filter to lowest-level rows under WK hierarchy (Stimmbezirk=0, not aggregates)
    # 13-digit ID: B(1) WW(2) KKK(3) VV(2) GGG(3) TT(2)
    # Regular Gemeinden: AGS = '07' + KKK + GGG (positions 3-5 + 8-10)
    # Kreisfreie Städte split across WK use Stadtteil sub-IDs with GGG='000'
    # and VV='00' — detect these and use the city AGS instead
    all_rows = df[(df["ID"].str[0] != "0") &
                   (df["Stimmbezirk"] == 0) &
                   (df["ID"].str[3:13] != "0000000000")].copy()

    # Classify rows
    all_rows["kkk"] = all_rows["ID"].str[3:6]
    all_rows["vv"] = all_rows["ID"].str[6:8]
    all_rows["ggg"] = all_rows["ID"].str[8:11]
    all_rows["tt"] = all_rows["ID"].str[11:13]
    all_rows["wk_nr"] = all_rows["ID"].str[1:3].astype(int)

    # Regular Gemeinden: VV != '00' and GGG != '000'
    regular = all_rows[(all_rows["vv"] != "00") & (all_rows["ggg"] != "000")].copy()
    regular["ags"] = "07" + regular["kkk"] + regular["ggg"]

    # Kreisfreie Städte split into Stadtteile: VV='00', GGG='000', TT!='00'
    # These are city sub-districts — map them to the parent city AGS
    stadt = all_rows[(all_rows["vv"] == "00") & (all_rows["ggg"] == "000") & (all_rows["tt"] != "00")].copy()
    stadt["ags"] = "07" + stadt["kkk"] + "000"

    result = pd.concat([
        regular[["ags", "wk_nr"]],
        stadt[["ags", "wk_nr"]],
    ], ignore_index=True)
    result["wk_name"] = result["wk_nr"].map(wk_names).fillna("Wahlkreis " + result["wk_nr"].astype(str))

    # Deduplicate AGS per WK (VG-level rows create duplicates)
    result = validate_parser_output(
        result,
        parser_name="parse_rheinland_pfalz",
        allow_multi_wk_per_ags=True,
    )

    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_schleswig_holstein(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse SH polling-district CSV, resolve Amt codes to Gemeinden via VG250.

    CSV semicolon-delimited, latin-1. Each row is a Stimmbezirk.
    First 8 digits of 'Gemeinde/Amt Nr.' give an 8-digit code that is either:
    - A Gemeinde AGS (directly in VG250), or
    - An Amt code (digits 5-7 >= 500) that must be expanded to constituent
      Gemeinden via VG250's ARS field (ARS[5:8] matches the Amt code).
    """
    import geopandas as gpd

    log.info("Parsing Schleswig-Holstein: %s", path.name)
    df = pd.read_csv(path, sep=";", encoding="latin-1")

    df["code8"] = df["Gemeinde/Amt Nr."].astype(str).str.zfill(14).str[:8]
    df["wk_nr"] = df["Wahlkreis"].astype(int)

    # Deduplicate to unique code8-WK pairs
    pairs = df[["wk_nr", "code8"]].drop_duplicates()

    # Load VG250 SH Gemeinden for Amt resolution
    vg250_path = Path(__file__).parent.parent.parent / "raw" / "municipality" / "VG250_GEM.shp"
    vg_sh = gpd.read_file(vg250_path, where="AGS LIKE '01%'")[["AGS", "ARS"]]
    vg250_ags = set(vg_sh["AGS"])

    # Build Amt code → constituent Gemeinde AGS lookup
    # Amt code = Kreis(5 digits) + Amt(3 digits from ARS[5:8])
    vg_sh["amt_code"] = vg_sh["ARS"].str[:5] + vg_sh["ARS"].str[5:8]
    amt_to_gem = vg_sh.groupby("amt_code")["AGS"].apply(set).to_dict()

    rows = []
    for _, row in pairs.iterrows():
        code = row["code8"]
        wk = row["wk_nr"]

        if code in vg250_ags:
            # Direct Gemeinde match
            rows.append({"ags": code, "wk_nr": wk})
        else:
            # Try Amt resolution: code[:5] = Kreis, code[5:8] = Amt identifier
            amt_key = code[:5] + code[5:8]
            gemeinden = amt_to_gem.get(amt_key, set())
            if gemeinden:
                for ags in gemeinden:
                    rows.append({"ags": ags, "wk_nr": wk})
            else:
                # Fallback: use the code as-is (may not match PLZ-AGS)
                rows.append({"ags": code, "wk_nr": wk})

    result = pd.DataFrame(rows)
    result["wk_name"] = "Wahlkreis " + result["wk_nr"].astype(str)
    result = validate_parser_output(
        result,
        parser_name="parse_schleswig_holstein",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def parse_hessen(path: Path, config: dict[str, Any]) -> pd.DataFrame:
    """Parse pre-merged Hessen Gemeinde→Wahlkreis CSV.

    Downloaded from ekom21 CDN (26 per-Landkreis files merged into one).
    Columns: ags (8-digit), wk_nr (int), wk_name (str).
    Split cities (Frankfurt 6 WK, Kassel 2 WK, etc.) included.
    """
    log.info("Parsing Hessen: %s", path.name)
    df = pd.read_csv(path)

    result = df[["ags", "wk_nr", "wk_name"]].copy()
    result["ags"] = result["ags"].astype(str).str.strip().str.zfill(8)
    result["wk_nr"] = result["wk_nr"].astype(int)
    result["wk_name"] = result["wk_name"].astype(str).str.strip()

    result = validate_parser_output(
        result,
        parser_name="parse_hessen",
        allow_multi_wk_per_ags=True,
    )
    log.info("Parsed %d AGS-to-WK entries (%d unique WK, %d unique AGS)",
             len(result), result["wk_nr"].nunique(), result["ags"].nunique())
    return result


def get_parser(config: dict) -> callable:
    """Get the parser function for a state config.

    If config has a 'parser' field, look up a named parser function.
    Otherwise, use parse_excel_generic.
    """
    parser_name = config.get("parser")
    if parser_name:
        func = globals().get(f"parse_{parser_name}")
        if func is None:
            raise ValueError(f"Unknown parser: {parser_name} (expected parse_{parser_name} in parsers.py)")
        return func
    return parse_excel_generic
