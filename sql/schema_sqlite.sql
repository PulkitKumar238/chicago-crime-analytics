-- ===========================================================================
-- Chicago Crime Data Warehouse - SQLite3 DDL
-- Fallback backend (see brief: "Incase MySQL is not available use SQLite3").
-- Structurally identical to sql/schema_mysql.sql.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS iucr (
    iucr_code    TEXT PRIMARY KEY,
    primary_type TEXT NOT NULL,
    description  TEXT NOT NULL,
    index_code   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS city_community (
    community_code   INTEGER PRIMARY KEY,
    community_name   TEXT NOT NULL,
    population       INTEGER,
    area_sqmile      REAL,
    area_sqkm        REAL,
    density_per_sqmi REAL,
    density_per_sqkm REAL
);

CREATE TABLE IF NOT EXISTS district_ps_info (
    district_code INTEGER PRIMARY KEY,
    district_name TEXT,
    address       TEXT,
    city          TEXT,
    state         TEXT,
    zip           TEXT,
    website       TEXT,
    phone         TEXT,
    fax           TEXT,
    tty           TEXT,
    x_coordinate  REAL,
    y_coordinate  REAL,
    latitude      REAL,
    longitude     REAL,
    location      TEXT
);

CREATE TABLE IF NOT EXISTS police_beat_info (
    beat_num INTEGER PRIMARY KEY,
    district INTEGER,
    sector   INTEGER,
    beat     INTEGER
);

CREATE TABLE IF NOT EXISTS ward_office (
    ward_no           INTEGER PRIMARY KEY,
    alderman          TEXT,
    address           TEXT,
    city              TEXT,
    state             TEXT,
    zipcode           TEXT,
    ward_phone        TEXT,
    ward_fax          TEXT,
    email             TEXT,
    website           TEXT,
    location          TEXT,
    city_hall_address TEXT,
    city_hall_city    TEXT,
    city_hall_state   TEXT,
    city_hall_zipcode TEXT,
    city_hall_phone   TEXT
);

CREATE TABLE IF NOT EXISTS chicago_crime (
    case_number    TEXT PRIMARY KEY,
    id             INTEGER NOT NULL UNIQUE,
    date           TEXT    NOT NULL,
    block          TEXT,
    iucr_code      TEXT REFERENCES iucr(iucr_code),
    location_desc  TEXT,
    arrest         INTEGER NOT NULL DEFAULT 0,
    domestic       INTEGER NOT NULL DEFAULT 0,
    beat_num       INTEGER REFERENCES police_beat_info(beat_num),
    district_code  INTEGER REFERENCES district_ps_info(district_code),
    ward_no        INTEGER,
    community_code INTEGER REFERENCES city_community(community_code),
    fbi_code       TEXT,
    x_coordinate   REAL,
    y_coordinate   REAL,
    year           INTEGER,
    month          INTEGER,
    day_of_week    TEXT,
    hour           INTEGER,
    date_of_update TEXT,
    latitude       REAL,
    longitude      REAL,
    location       TEXT
);

CREATE INDEX IF NOT EXISTS ix_crime_year      ON chicago_crime(year);
CREATE INDEX IF NOT EXISTS ix_crime_iucr      ON chicago_crime(iucr_code);
CREATE INDEX IF NOT EXISTS ix_crime_community ON chicago_crime(community_code);
CREATE INDEX IF NOT EXISTS ix_crime_date      ON chicago_crime(date);

CREATE TABLE IF NOT EXISTS summary_crime_yearly (
    year         INTEGER PRIMARY KEY,
    total_crimes INTEGER NOT NULL,
    arrests      INTEGER NOT NULL,
    arrest_rate  REAL
);

CREATE TABLE IF NOT EXISTS summary_crime_by_category (
    primary_type TEXT PRIMARY KEY,
    total_crimes INTEGER NOT NULL,
    pct_of_total REAL,
    arrests      INTEGER,
    arrest_rate  REAL
);

CREATE TABLE IF NOT EXISTS summary_crime_by_community (
    community_code INTEGER PRIMARY KEY,
    community_name TEXT,
    total_crimes   INTEGER NOT NULL,
    population     INTEGER,
    crimes_per_10k REAL
);
