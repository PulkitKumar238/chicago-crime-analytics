"""
ETL pipeline: raw CSV -> cleaned DataFrame -> data warehouse.

Run as a script to (re)build the whole warehouse from data/raw:

    python -m db.etl              # create schema, load everything, build views
    python -m db.etl --reset      # drop existing rows first
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text as sa_text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from db import connection as dbc

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
CRIME_COLUMNS = [
    "case_number", "id", "date", "block", "iucr_code", "location_desc",
    "arrest", "domestic", "beat_num", "district_code", "ward_no",
    "community_code", "fbi_code", "x_coordinate", "y_coordinate", "year",
    "month", "day_of_week", "hour", "date_of_update", "latitude",
    "longitude", "location",
]

# FBI codes that make an offence a "Part I / Index" crime.
INDEX_FBI_CODES = {"01A", "01B", "02", "03", "04A", "04B", "05", "06", "07", "09"}

CATEGORICAL_UPPER = ["primary_type", "description", "location_desc", "block", "fbi_code"]

DATE_FORMATS = ["%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S"]


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #
def read_crime_csv(path: Path | str = None) -> pd.DataFrame:
    """Read the master crime CSV keeping code columns as text."""
    path = Path(path or config.CRIME_CSV)
    return pd.read_csv(path, dtype={"iucr_code": str, "fbi_code": str,
                                    "case_number": str})


# --------------------------------------------------------------------------- #
# Transform
# --------------------------------------------------------------------------- #
def parse_dates(series: pd.Series) -> pd.Series:
    """Parse a date column that may use more than one textual format."""
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    remaining = series.notna()
    for fmt in DATE_FORMATS:
        if not remaining.any():
            break
        parsed = pd.to_datetime(series[remaining], format=fmt, errors="coerce")
        out.loc[parsed.notna()[parsed.notna()].index] = parsed.dropna()
        remaining = out.isna() & series.notna()
    if remaining.any():  # last resort: let pandas infer
        inferred = pd.to_datetime(series[remaining], errors="coerce")
        out.loc[inferred.notna()[inferred.notna()].index] = inferred.dropna()
    return out


def missing_pct(df: pd.DataFrame) -> pd.Series:
    """Percentage of missing values per column, computed with NumPy."""
    pct = np.round(np.sum(df.isna().to_numpy(), axis=0) / len(df) * 100, 2)
    return pd.Series(pct, index=df.columns, name="missing_pct").sort_values(ascending=False)


def clean_crime_frame(df: pd.DataFrame, drop_threshold: float = 50.0) -> tuple[pd.DataFrame, dict]:
    """
    Apply the full Use Case 1 cleaning contract.

    Returns the cleaned frame plus an audit dict describing what changed, so
    the pipeline stays traceable for the regulatory-compliance requirement.
    """
    audit: dict = {"rows_in": len(df), "columns_in": df.shape[1]}
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # 1. dates -------------------------------------------------------------
    df["date"] = parse_dates(df["date"])
    audit["unparsable_dates"] = int(df["date"].isna().sum())
    if "date_of_update" in df:
        df["date_of_update"] = parse_dates(df["date_of_update"])
    df = df[df["date"].notna()]

    # 2. duplicates --------------------------------------------------------
    before = len(df)
    df = df.drop_duplicates(subset=["case_number"], keep="last")
    audit["duplicate_case_numbers"] = before - len(df)

    # 3. categorical standardisation --------------------------------------
    for col in CATEGORICAL_UPPER:
        if col in df:
            df[col] = df[col].astype("string").str.strip().str.upper()
            df[col] = df[col].replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA})

    if "case_number" in df:
        df["case_number"] = df["case_number"].astype("string").str.strip().str.upper()

    # IUCR codes are 4-character zero-padded text, never numbers.
    df["iucr_code"] = (df["iucr_code"].astype("string").str.strip()
                       .str.upper().str.zfill(4))

    # 4. booleans ----------------------------------------------------------
    for col in ("arrest", "domestic"):
        df[col] = (df[col].astype(str).str.strip().str.upper()
                   .map({"TRUE": 1, "FALSE": 0, "1": 1, "0": 0, "Y": 1, "N": 0})
                   .fillna(0).astype(int))

    # 5. key fields: an unknown location is recorded, not invented ----------
    audit["location_desc_filled"] = int(df["location_desc"].isna().sum())
    df["location_desc"] = df["location_desc"].fillna("UNKNOWN")

    # 6. geographic sanity — Chicago bounding box --------------------------
    geo_bad = (
        df["latitude"].notna()
        & (~df["latitude"].between(41.60, 42.10) | ~df["longitude"].between(-87.95, -87.50))
    )
    audit["geo_outliers_nulled"] = int(geo_bad.sum())
    df.loc[geo_bad, ["latitude", "longitude", "location"]] = np.nan

    # 7. derived time features --------------------------------------------
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["day_of_week"] = df["date"].dt.day_name()
    df["hour"] = df["date"].dt.hour

    # 8. numeric coercion --------------------------------------------------
    for col in ("id", "beat_num", "district_code", "ward_no", "community_code"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("x_coordinate", "y_coordinate", "latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 9. columns that are more hole than data ------------------------------
    pct = missing_pct(df)
    dropped = [c for c in pct[pct > drop_threshold].index if c not in ("case_number", "date")]
    audit["dropped_columns"] = dropped
    audit["max_missing_pct"] = float(pct.max())
    df = df.drop(columns=dropped)

    audit["rows_out"] = len(df)
    audit["columns_out"] = df.shape[1]
    return df, audit


def derive_iucr_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the IUCR dimension from the master file.

    The supplied iucr_codes.csv actually contained ward-office records, so the
    dimension is reconstructed from the offence attributes carried on each
    crime row.  index_code follows the FBI Part I ("Index") classification.
    """
    iucr = (df[["iucr_code", "primary_type", "description", "fbi_code"]]
            .dropna(subset=["iucr_code"])
            .drop_duplicates(subset=["iucr_code"], keep="first")
            .sort_values("iucr_code")
            .reset_index(drop=True))
    iucr["index_code"] = np.where(iucr["fbi_code"].isin(INDEX_FBI_CODES), "I", "N")
    return iucr[["iucr_code", "primary_type", "description", "index_code"]]


def to_warehouse_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Project the cleaned frame onto the chicago_crime table columns."""
    out = df.copy()
    for col in CRIME_COLUMNS:
        if col not in out:
            out[col] = pd.NA
    out = out[CRIME_COLUMNS]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    out["date_of_update"] = pd.to_datetime(out["date_of_update"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    return out.astype(object).where(pd.notna(out), None)


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
# Delete order that respects the foreign keys (children before parents).
TRUNCATE_ORDER = [
    "summary_crime_by_community", "summary_crime_by_category", "summary_crime_yearly",
    "chicago_crime",
    "ward_office", "police_beat_info", "district_ps_info", "city_community", "iucr",
]


def _load_frame(df: pd.DataFrame, table: str, mode: str = "append") -> int:
    """
    Write a DataFrame to a warehouse table.

    mode="truncate" empties the table first but, unlike to_sql(if_exists=
    "replace"), never drops it -- so the primary keys, foreign keys and indexes
    declared in sql/schema_*.sql survive every reload.
    """
    engine = dbc.get_engine()
    with engine.begin() as conn:
        if mode == "truncate":
            conn.execute(sa_text(f"DELETE FROM {table}"))
        df.to_sql(table, conn, if_exists="append", index=False, chunksize=500)
    return len(df)


def truncate_all() -> None:
    """Empty every warehouse table in foreign-key-safe order."""
    engine = dbc.get_engine()
    with engine.begin() as conn:
        for table in TRUNCATE_ORDER:
            if dbc.table_exists(table):
                conn.execute(sa_text(f"DELETE FROM {table}"))


def load_dimensions() -> dict:
    """Load the five dimension tables."""
    counts: dict = {}

    community = pd.read_csv(config.COMMUNITY_CSV)
    community.columns = [c.strip().lower() for c in community.columns]
    community["community_name"] = community["community_name"].str.strip()
    counts["city_community"] = _load_frame(community, "city_community", "truncate")

    district = pd.read_csv(config.DISTRICT_CSV)
    district.columns = [c.strip().lower() for c in district.columns]
    counts["district_ps_info"] = _load_frame(district, "district_ps_info", "truncate")

    beat = pd.read_csv(config.BEAT_CSV)
    beat.columns = [c.strip().lower() for c in beat.columns]
    counts["police_beat_info"] = _load_frame(
        beat[["beat_num", "district", "sector", "beat"]], "police_beat_info", "truncate")

    ward = pd.read_csv(config.WARD_CSV)
    ward.columns = [c.strip().lower() for c in ward.columns]
    counts["ward_office"] = _load_frame(ward, "ward_office", "truncate")

    return counts


def build_summary_tables() -> dict:
    """Populate the pre-aggregated reporting tables (Use Case 4)."""
    yearly = dbc.read_sql(
        "SELECT year, total_crimes, arrests, arrest_rate FROM vw_crime_yearly ORDER BY year")
    category = dbc.read_sql(
        "SELECT primary_type, total_crimes, pct_of_total, arrests, arrest_rate "
        "FROM vw_crime_by_category ORDER BY total_crimes DESC")
    community = dbc.read_sql(
        "SELECT community_code, community_name, total_crimes, population, crimes_per_10k "
        "FROM vw_crime_by_community ORDER BY total_crimes DESC")

    return {
        "summary_crime_yearly": _load_frame(yearly, "summary_crime_yearly", "truncate"),
        "summary_crime_by_category": _load_frame(category, "summary_crime_by_category", "truncate"),
        "summary_crime_by_community": _load_frame(community, "summary_crime_by_community", "truncate"),
    }


def upsert_crimes(rows: pd.DataFrame) -> tuple[int, int]:
    """
    Insert-or-update crime rows by case_number.  Used by the web application's
    CSV upload so re-uploading a corrected file never duplicates cases.
    Returns (inserted, updated).
    """
    rows = to_warehouse_frame(rows)
    existing = set(dbc.read_sql("SELECT case_number FROM chicago_crime")["case_number"])
    mask = rows["case_number"].isin(existing)
    updates, inserts = rows[mask], rows[~mask]

    with dbc.connector() as conn:
        cur = conn.cursor()
        ph = "%s" if config.DB_BACKEND == "mysql" else "?"
        if len(inserts):
            cols = ", ".join(CRIME_COLUMNS)
            marks = ", ".join([ph] * len(CRIME_COLUMNS))
            cur.executemany(f"INSERT INTO chicago_crime ({cols}) VALUES ({marks})",
                            list(inserts.itertuples(index=False, name=None)))
        if len(updates):
            setters = ", ".join(f"{c} = {ph}" for c in CRIME_COLUMNS if c != "case_number")
            payload = [tuple(r[c] for c in CRIME_COLUMNS if c != "case_number") + (r["case_number"],)
                       for _, r in updates.iterrows()]
            cur.executemany(
                f"UPDATE chicago_crime SET {setters} WHERE case_number = {ph}", payload)
        cur.close()
    return len(inserts), len(updates)


def sync_iucr(iucr: pd.DataFrame) -> int:
    """Add any IUCR codes that are not in the dimension yet."""
    known = set(dbc.read_sql("SELECT iucr_code FROM iucr")["iucr_code"])
    new = iucr[~iucr["iucr_code"].isin(known)]
    if len(new):
        _load_frame(new, "iucr", "append")
    return len(new)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def full_refresh(verbose: bool = True) -> dict:
    """Rebuild the entire warehouse from data/raw."""
    def log(msg):
        if verbose:
            print(msg)

    log(f"[1/6] Target backend  : {dbc.backend_label()}")
    dbc.create_schema()
    truncate_all()
    log("[2/6] Schema created (existing rows cleared, DDL preserved)")

    raw = read_crime_csv()
    clean, audit = clean_crime_frame(raw)
    clean.to_csv(config.CLEAN_CRIME_CSV, index=False)
    log(f"[3/6] Cleaned {audit['rows_in']} -> {audit['rows_out']} rows "
        f"({audit['duplicate_case_numbers']} duplicates, "
        f"{audit['unparsable_dates']} bad dates removed)")

    iucr = derive_iucr_table(clean)
    iucr.to_csv(config.IUCR_CSV, index=False)
    _load_frame(iucr, "iucr", "truncate")
    dims = load_dimensions()
    log(f"[4/6] Dimensions loaded: iucr={len(iucr)}, " +
        ", ".join(f"{k}={v}" for k, v in dims.items()))

    _load_frame(to_warehouse_frame(clean), "chicago_crime", "truncate")
    log(f"[5/6] Fact table loaded: {len(clean)} crimes")

    dbc.create_views()
    summaries = build_summary_tables()
    log("[6/6] Views + summary tables built: " +
        ", ".join(f"{k}={v}" for k, v in summaries.items()))

    return {"audit": audit, "dimensions": dims, "summaries": summaries,
            "iucr_codes": len(iucr), "crimes": len(clean)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Chicago crime warehouse")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    result = full_refresh(verbose=not args.quiet)
    print(f"\nDone. {result['crimes']} crimes across "
          f"{result['iucr_codes']} IUCR codes are queryable.")
