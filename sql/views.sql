-- ===========================================================================
-- Analytical views.  Written in portable SQL so the identical file runs on
-- both MySQL and SQLite3 (DROP + CREATE instead of CREATE OR REPLACE).
-- ===========================================================================

-- Denormalised crime row: fact joined to every dimension. -------------------
DROP VIEW IF EXISTS vw_crime_full;
CREATE VIEW vw_crime_full AS
SELECT  c.case_number,
        c.id,
        c.date,
        c.year,
        c.month,
        c.day_of_week,
        c.hour,
        c.block,
        c.iucr_code,
        i.primary_type,
        i.description,
        i.index_code,
        c.location_desc,
        c.arrest,
        c.domestic,
        c.beat_num,
        c.district_code,
        d.district_name,
        c.ward_no,
        c.community_code,
        cc.community_name,
        cc.population,
        c.fbi_code,
        c.latitude,
        c.longitude
FROM        chicago_crime  c
LEFT JOIN   iucr           i  ON i.iucr_code      = c.iucr_code
LEFT JOIN   district_ps_info d ON d.district_code = c.district_code
LEFT JOIN   city_community cc ON cc.community_code = c.community_code;

-- Crimes, arrests and arrest rate per year. ---------------------------------
DROP VIEW IF EXISTS vw_crime_yearly;
CREATE VIEW vw_crime_yearly AS
SELECT  year,
        COUNT(*)                                        AS total_crimes,
        SUM(arrest)                                     AS arrests,
        ROUND(SUM(arrest) * 100.0 / COUNT(*), 2)        AS arrest_rate,
        SUM(domestic)                                   AS domestic_incidents
FROM    chicago_crime
GROUP BY year;

-- Volume and share per crime category. --------------------------------------
DROP VIEW IF EXISTS vw_crime_by_category;
CREATE VIEW vw_crime_by_category AS
SELECT  i.primary_type,
        COUNT(*)                                                            AS total_crimes,
        ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM chicago_crime), 2)   AS pct_of_total,
        SUM(c.arrest)                                                       AS arrests,
        ROUND(SUM(c.arrest) * 100.0 / COUNT(*), 2)                          AS arrest_rate
FROM        chicago_crime c
INNER JOIN  iucr i ON i.iucr_code = c.iucr_code
GROUP BY    i.primary_type;

-- Crime load per community area, normalised by population. -------------------
DROP VIEW IF EXISTS vw_crime_by_community;
CREATE VIEW vw_crime_by_community AS
SELECT  cc.community_code,
        cc.community_name,
        cc.population,
        COUNT(*)                                                AS total_crimes,
        ROUND(COUNT(*) * 10000.0 / cc.population, 2)            AS crimes_per_10k,
        ROUND(SUM(c.arrest) * 100.0 / COUNT(*), 2)              AS arrest_rate
FROM        chicago_crime  c
INNER JOIN  city_community cc ON cc.community_code = c.community_code
GROUP BY    cc.community_code, cc.community_name, cc.population;

-- Hour-of-day profile used for patrol shift planning. -----------------------
DROP VIEW IF EXISTS vw_crime_hourly;
CREATE VIEW vw_crime_hourly AS
SELECT  hour,
        COUNT(*)                                    AS total_crimes,
        ROUND(SUM(arrest) * 100.0 / COUNT(*), 2)    AS arrest_rate
FROM    chicago_crime
GROUP BY hour;

-- Top IUCR offence codes. ---------------------------------------------------
DROP VIEW IF EXISTS vw_top_iucr;
CREATE VIEW vw_top_iucr AS
SELECT  c.iucr_code,
        i.primary_type,
        i.description,
        i.index_code,
        COUNT(*) AS total_crimes
FROM        chicago_crime c
INNER JOIN  iucr i ON i.iucr_code = c.iucr_code
GROUP BY    c.iucr_code, i.primary_type, i.description, i.index_code;
