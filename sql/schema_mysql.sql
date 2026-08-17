-- ===========================================================================
-- Chicago Crime Data Warehouse - MySQL DDL
-- Implements the supplied data model: one fact table (chicago_crime) with
-- five conformed dimensions (iucr, police_beat_info, district_ps_info,
-- ward_office, city_community).
-- ===========================================================================

CREATE DATABASE IF NOT EXISTS chicago_crime_dw
    DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE chicago_crime_dw;

-- ---------------------------------------------------------------- dimensions
CREATE TABLE IF NOT EXISTS iucr (
    iucr_code     VARCHAR(4)   NOT NULL,
    primary_type  VARCHAR(64)  NOT NULL,
    description   VARCHAR(128) NOT NULL,
    index_code    CHAR(1)      NOT NULL,          -- 'I' = FBI index crime
    PRIMARY KEY (iucr_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS city_community (
    community_code   INT          NOT NULL,
    community_name   VARCHAR(96)  NOT NULL,
    population       INT,
    area_sqmile      DECIMAL(10,4),
    area_sqkm        DECIMAL(10,4),
    density_per_sqmi DECIMAL(14,4),
    density_per_sqkm DECIMAL(14,4),
    PRIMARY KEY (community_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS district_ps_info (
    district_code INT          NOT NULL,
    district_name VARCHAR(96),
    address       VARCHAR(192),
    city          VARCHAR(64),
    state         VARCHAR(8),
    zip           VARCHAR(12),
    website       VARCHAR(255),
    phone         VARCHAR(32),
    fax           VARCHAR(32),
    tty           VARCHAR(32),
    x_coordinate  DECIMAL(16,4),
    y_coordinate  DECIMAL(16,4),
    latitude      DECIMAL(12,8),
    longitude     DECIMAL(12,8),
    location      VARCHAR(96),
    PRIMARY KEY (district_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS police_beat_info (
    beat_num INT NOT NULL,
    district INT,
    sector   INT,
    beat     INT,
    PRIMARY KEY (beat_num),
    KEY ix_beat_district (district)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ward_office (
    ward_no           INT NOT NULL,
    alderman          VARCHAR(96),
    address           VARCHAR(192),
    city              VARCHAR(64),
    state             VARCHAR(8),
    zipcode           VARCHAR(12),
    ward_phone        VARCHAR(32),
    ward_fax          VARCHAR(32),
    email             VARCHAR(128),
    website           VARCHAR(255),
    location          VARCHAR(96),
    city_hall_address VARCHAR(192),
    city_hall_city    VARCHAR(64),
    city_hall_state   VARCHAR(8),
    city_hall_zipcode VARCHAR(12),
    city_hall_phone   VARCHAR(32),
    PRIMARY KEY (ward_no)
) ENGINE=InnoDB;

-- --------------------------------------------------------------- fact table
-- primary_type / description are NOT repeated here: they are attributes of
-- the IUCR dimension (3NF).  Use vw_crime_full to read the denormalised row.
CREATE TABLE IF NOT EXISTS chicago_crime (
    case_number    VARCHAR(16)  NOT NULL,
    id             BIGINT       NOT NULL,
    date           DATETIME     NOT NULL,
    block          VARCHAR(128),
    iucr_code      VARCHAR(4),
    location_desc  VARCHAR(96),
    arrest         TINYINT(1)   NOT NULL DEFAULT 0,
    domestic       TINYINT(1)   NOT NULL DEFAULT 0,
    beat_num       INT,
    district_code  INT,
    ward_no        INT,
    community_code INT,
    fbi_code       VARCHAR(4),
    x_coordinate   DECIMAL(16,4),
    y_coordinate   DECIMAL(16,4),
    year           SMALLINT,
    month          TINYINT,
    day_of_week    VARCHAR(12),
    hour           TINYINT,
    date_of_update DATETIME,
    latitude       DECIMAL(12,8),
    longitude      DECIMAL(12,8),
    location       VARCHAR(96),
    PRIMARY KEY (case_number),
    UNIQUE KEY uq_crime_id (id),
    KEY ix_crime_year (year),
    KEY ix_crime_iucr (iucr_code),
    KEY ix_crime_community (community_code),
    KEY ix_crime_date (date),
    CONSTRAINT fk_crime_iucr      FOREIGN KEY (iucr_code)      REFERENCES iucr(iucr_code),
    CONSTRAINT fk_crime_beat      FOREIGN KEY (beat_num)       REFERENCES police_beat_info(beat_num),
    CONSTRAINT fk_crime_district  FOREIGN KEY (district_code)  REFERENCES district_ps_info(district_code),
    CONSTRAINT fk_crime_community FOREIGN KEY (community_code) REFERENCES city_community(community_code)
) ENGINE=InnoDB;
-- NOTE: no FK on ward_no.  The supplied ward_office file covers only wards
-- 1-24 while the crime data references wards 1-50, so the constraint would
-- reject ~49% of otherwise valid rows.  Nothing is discarded (see brief).

-- ------------------------------------------------------------ summary tables
CREATE TABLE IF NOT EXISTS summary_crime_yearly (
    year         SMALLINT NOT NULL,
    total_crimes INT      NOT NULL,
    arrests      INT      NOT NULL,
    arrest_rate  DECIMAL(6,2),
    PRIMARY KEY (year)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS summary_crime_by_category (
    primary_type VARCHAR(64) NOT NULL,
    total_crimes INT         NOT NULL,
    pct_of_total DECIMAL(6,2),
    arrests      INT,
    arrest_rate  DECIMAL(6,2),
    PRIMARY KEY (primary_type)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS summary_crime_by_community (
    community_code INT NOT NULL,
    community_name VARCHAR(96),
    total_crimes   INT NOT NULL,
    population     INT,
    crimes_per_10k DECIMAL(12,2),
    PRIMARY KEY (community_code)
) ENGINE=InnoDB;
