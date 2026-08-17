"""
Central configuration for the Chicago Crime Data Analytics project.

Database backend is selectable so the same code runs against MySQL (the target
platform) or SQLite3 (the documented fallback when MySQL is unavailable).

    DB_BACKEND=sqlite   -> data/chicago_crime.db          (default)
    DB_BACKEND=mysql    -> mysql+pymysql://user:pass@host:port/schema
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
SQL_DIR = BASE_DIR / "sql"
FIGURES_DIR = BASE_DIR / "usecases" / "figures"
REPORTS_DIR = BASE_DIR / "usecases" / "reports"

for _d in (PROCESSED_DIR, FIGURES_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Source files -----------------------------------------------------------
CRIME_CSV = RAW_DIR / "chicago_crime_dataset.csv"
COMMUNITY_CSV = RAW_DIR / "chicago_city_community.csv"
DISTRICT_CSV = RAW_DIR / "chicago_district_ps_info.csv"
BEAT_CSV = RAW_DIR / "chicago_police_beat_info.csv"
WARD_CSV = RAW_DIR / "chicago_ward_offices.csv"
IUCR_CSV = RAW_DIR / "iucr_codes.csv"          # derived by db/etl.py if absent

CLEAN_CRIME_CSV = PROCESSED_DIR / "chicago_crime_clean.csv"

# --- Database ---------------------------------------------------------------
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").lower()

MYSQL = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "chicago_crime_dw"),
}

SQLITE_PATH = BASE_DIR / "data" / os.getenv("SQLITE_FILE", "chicago_crime.db")


def sqlalchemy_url(include_db: bool = True) -> str:
    """SQLAlchemy connection URL for the configured backend."""
    if DB_BACKEND == "mysql":
        schema = MYSQL["database"] if include_db else ""
        return (
            f"mysql+pymysql://{MYSQL['user']}:{MYSQL['password']}"
            f"@{MYSQL['host']}:{MYSQL['port']}/{schema}?charset=utf8mb4"
        )
    return f"sqlite:///{SQLITE_PATH}"


# --- Presentation -----------------------------------------------------------
PALETTE = "crest"
FIG_DPI = 120
