"""
USE CASE 1 — Load and Clean Chicago Crime Data
==============================================

Objective
    Build a data-ingestion pipeline that reads the raw CPD extract, profiles it,
    cleans it, engineers the time features the rest of the project depends on,
    and lands it in the data warehouse.

Run:
    python usecases/usecase1_load_and_clean.py

Produces:
    usecases/reports/UseCase1_Load_and_Clean.pdf
    usecases/figures/uc1_*.png
    data/processed/chicago_crime_clean.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from db import connection as dbc
from usecases import viz
from usecases.report_builder import Report

viz.setup_style()

REPORT = Report(
    number=1,
    title="Load and Clean Chicago Crime Data",
    objective="Ingest, profile, clean and warehouse the CPD crime extract.",
    backend=dbc.backend_label(),
)

# The namespace every code step shares.
REPORT.env.update({"config": config, "dbc": dbc, "viz": viz, "Path": Path})


def main() -> Path:
    r = REPORT

    # ================================================================== INTRO
    r.section("1. Loading the dataset")
    r.requirement("""
        Read the master crime CSV into a Pandas DataFrame, show the first ten
        rows, print the schema and data types, and state exactly how many rows
        and columns we are dealing with.
    """)
    r.text("""
        A note on the source files before anything else. The five CSVs handed
        over by the CPD were named inconsistently with their contents — the
        file called <b>chicago_crime_dataset.csv</b> actually held the 77
        community areas, while the real 2,000-row crime extract arrived under
        the name <b>chicago_district_ps_info.csv</b>. Every file was inspected
        by its header row and re-mapped to the entity it genuinely contains
        before a single line of analysis was written. The file supposedly
        holding IUCR codes contained ward offices, so the IUCR dimension is
        reconstructed from the offence attributes carried on each crime row
        (Section 6). This is recorded here because silently loading a
        mislabelled file is exactly the class of error that corrupts a
        warehouse.
    """)

    r.step("""
        import numpy as np
        import pandas as pd

        pd.set_option('display.width', 110)
        pd.set_option('display.max_columns', 30)

        # iucr_code and fbi_code are identifiers, not numbers: '0110' must not
        # become 110, so they are read as text from the very first touch.
        df = pd.read_csv(config.CRIME_CSV,
                         dtype={'iucr_code': str, 'fbi_code': str, 'case_number': str})

        print(f"Rows    : {df.shape[0]:,}")
        print(f"Columns : {df.shape[1]}")
        print(f"Memory  : {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
    """)

    r.sub("First 10 rows")
    r.step("""
        preview_cols = ['case_number', 'date', 'primary_type',
                        'location_desc', 'arrest', 'district_code']
        print(df[preview_cols].head(10).to_string(index=False))
    """)

    r.sub("Schema and data types")
    r.step("""
        schema = pd.DataFrame({
            'dtype': df.dtypes.astype(str),
            'non_null': df.notna().sum(),
            'nulls': df.isna().sum(),
            'unique': df.nunique(),
        })
        print(schema.to_string())
    """)

    r.insight("""
        The extract is 2,000 crime records across 22 columns spanning 2015 to
        2023. Every row is uniquely keyed by <b>case_number</b>, which makes it
        a safe natural primary key for the warehouse fact table.
    """)

    # =============================================================== MISSING
    r.section("2. Missing-value profile with NumPy")
    r.requirement("""
        Use NumPy to calculate the percentage of missing values in every column,
        and drop any column that is more than 50% empty.
    """)
    r.step("""
        # NumPy does the arithmetic on the raw boolean matrix.
        null_matrix = df.isna().to_numpy()
        missing_pct = np.round(null_matrix.sum(axis=0) / len(df) * 100, 2)

        missing = (pd.Series(missing_pct, index=df.columns, name='missing_%')
                     .sort_values(ascending=False))
        print(missing[missing > 0].to_string())

        over_half = missing[missing > 50]
        print(f"\\nColumns above the 50% threshold: "
              f"{list(over_half.index) if len(over_half) else 'none'}")
        print(f"Worst column is '{missing.idxmax()}' at {missing.max()}% missing.")
    """)
    r.text("""
        <b>Can we drop any column with more than 50% missing?</b> No — and that
        is the finding, not a non-answer. The emptiest column,
        <i>location_desc</i>, is only 4.7% empty, so the 50% rule removes
        nothing here. The rule is still implemented in the pipeline
        (<code>db/etl.py</code>, <code>drop_threshold=50.0</code>) so that a
        future extract with a genuinely hollow column is handled automatically
        rather than by hand.
    """)

    fig = _fig_missing(REPORT.env)
    r.figure(fig, "Missing values per column. No column comes close to the 50% drop line.")
    r.insight("""
        The gaps cluster in the geospatial block — latitude, longitude,
        x/y coordinates and location are missing together on roughly 3–4% of
        rows, which is the signature of a failed geocode rather than random
        loss. Those rows keep their district, beat and community codes, so they
        stay fully usable for every non-map analysis. Nothing is discarded.
    """)

    # ================================================================ CLEAN
    r.section("3. Cleaning the dataset")
    r.requirement("""
        Convert Date into a real datetime, deal with missing values in the key
        fields, and standardise the categorical fields — strip stray whitespace
        and unify the casing.
    """)

    r.sub("3.1 Dates")
    r.step("""
        # Parse explicitly rather than letting pandas guess row by row:
        # 03/04/2022 is 4 March, never 3 April.
        parsed = pd.to_datetime(df['date'], format='%m/%d/%Y %H:%M', errors='coerce')
        print(f"Rows that failed the primary format : {parsed.isna().sum()}")

        df['date'] = parsed
        df['date_of_update'] = pd.to_datetime(df['date_of_update'],
                                              format='%m/%d/%Y %H:%M', errors='coerce')

        print(f"Earliest crime : {df['date'].min()}")
        print(f"Latest crime   : {df['date'].max()}")
        print(f"Reporting span : {df['date'].dt.year.min()}-{df['date'].dt.year.max()}")

        # Integrity check: does the stored 'year' column agree with the date?
        print(f"year column disagreeing with date : {(df['date'].dt.year != df['year']).sum()}")
    """)

    r.sub("3.2 Categorical standardisation")
    r.step("""
        text_cols = ['primary_type', 'description', 'location_desc', 'block', 'fbi_code']
        for col in text_cols:
            df[col] = df[col].astype('string').str.strip().str.upper()
            df[col] = df[col].replace({'': pd.NA, 'NAN': pd.NA, 'NONE': pd.NA})

        df['case_number'] = df['case_number'].str.strip().str.upper()

        # IUCR is a 4-character zero-padded code.
        df['iucr_code'] = df['iucr_code'].str.strip().str.zfill(4)

        # Arrest / Domestic become 0-1 integers so they can be averaged directly.
        for col in ['arrest', 'domestic']:
            df[col] = (df[col].astype(str).str.strip().str.upper()
                       .map({'TRUE': 1, 'FALSE': 0}).fillna(0).astype(int))

        print(f"primary_type  : {df['primary_type'].nunique()} distinct values")
        print(f"location_desc : {df['location_desc'].nunique()} distinct values")
        print(f"iucr_code     : {df['iucr_code'].nunique()} distinct codes, "
              f"sample {sorted(df['iucr_code'].unique())[:6]}")
        print(f"arrest        : {dict(df['arrest'].value_counts())}")
    """)

    r.sub("3.3 Key fields and duplicates")
    r.step("""
        print(f"Duplicate case_number : {df['case_number'].duplicated().sum()}")
        print(f"Duplicate id          : {df['id'].duplicated().sum()}")

        # An unknown location is recorded as UNKNOWN, never guessed. Ward,
        # community and coordinates stay NULL: inventing a location would
        # corrupt the patrol-allocation analysis that depends on them.
        filled = df['location_desc'].isna().sum()
        df['location_desc'] = df['location_desc'].fillna('UNKNOWN')
        print(f"location_desc set to UNKNOWN : {filled}")
        print(f"ward_no left null            : {df['ward_no'].isna().sum()}")
        print(f"community_code left null     : {df['community_code'].isna().sum()}")
    """)

    # ============================================================== ANOMALIES
    r.section("4. Anomalies and outliers")
    r.requirement("""
        Are there anomalies in the date formats, or obvious outliers in the data?
    """)
    r.step("""
        checks = {}

        # a) date format consistency
        checks['unparsable dates'] = int(df['date'].isna().sum())
        checks['dates in the future'] = int((df['date'] > pd.Timestamp.now()).sum())

        # b) an update that predates the crime it updates
        bad_update = (df['date_of_update'] < df['date']).sum()
        checks['date_of_update before date'] = int(bad_update)

        # c) coordinates outside the Chicago bounding box
        outside = df['latitude'].notna() & (~df['latitude'].between(41.60, 42.10)
                                            | ~df['longitude'].between(-87.95, -87.50))
        checks['coordinates outside Chicago'] = int(outside.sum())

        # d) referential gaps against the reference files
        wards = pd.read_csv(config.WARD_CSV)
        checks['ward_no with no ward office'] = int((~df['ward_no'].dropna()
                                                     .isin(wards['WARD_NO'])).sum())

        for k, v in checks.items():
            print(f"{k:32s}: {v}")

        print("\\nHour-of-day spread (a flat 00:00 spike would signal a time-parsing bug):")
        print(df['date'].dt.hour.value_counts().sort_index().to_string())
    """)
    r.insight("""
        The date column is clean: a single format, zero parse failures, no
        future-dated crimes, and hours spread across the full 24-hour clock
        rather than piling up at midnight. The one real referential gap is
        <b>ward_no</b> — the crime data references wards 1–50 but the supplied
        ward-office file covers only wards 1–24, so roughly half the rows point
        at a ward with no office record. That gap is documented and the ward
        foreign key is deliberately left unenforced rather than deleting 988
        valid crime records to satisfy a constraint.
    """)

    # =============================================================== FEATURES
    r.section("5. Feature engineering")
    r.requirement("""
        Derive Year, Month and DayOfWeek from the Date column (plus Hour, which
        Use Case 3 needs for the time-of-day analysis).
    """)
    r.step("""
        df['Year'] = df['date'].dt.year
        df['Month'] = df['date'].dt.month
        df['DayOfWeek'] = df['date'].dt.day_name()
        df['Hour'] = df['date'].dt.hour

        print(df[['date', 'Year', 'Month', 'DayOfWeek', 'Hour']].head(8).to_string(index=False))
        print()
        print("Crimes per year:")
        print(df['Year'].value_counts().sort_index().to_string())
    """)

    fig = _fig_features(REPORT.env)
    r.figure(fig, "The three engineered features at a glance: year, weekday and month.")

    # ================================================================ QUESTIONS
    r.section("6. Warehouse load")
    r.requirement("""
        Design a crime table schema in the database and write the cleaned data
        into it using SQLAlchemy or PyMySQL.
    """)
    r.text("""
        The warehouse follows the supplied data model: one fact table
        (<b>chicago_crime</b>, keyed on case_number) surrounded by five
        dimensions — <b>iucr</b>, <b>city_community</b>, <b>district_ps_info</b>,
        <b>police_beat_info</b> and <b>ward_office</b>. Because
        <i>primary_type</i> and <i>description</i> are attributes of the offence
        code rather than of an individual crime, they live in the IUCR
        dimension and are read back through the <code>vw_crime_full</code> view.
        That is what keeps the fact table in third normal form and stops the
        same offence label being spelled two ways in two rows.
        <br/><br/>
        The DDL lives in <code>sql/schema_mysql.sql</code> with a structurally
        identical SQLite3 version in <code>sql/schema_sqlite.sql</code>, so the
        same pipeline runs on either backend — as the brief allows when a MySQL
        server is not available.
    """)
    r.code_block("""
        -- sql/schema_mysql.sql (extract)
        CREATE TABLE chicago_crime (
            case_number    VARCHAR(16) NOT NULL,
            id             BIGINT      NOT NULL,
            date           DATETIME    NOT NULL,
            block          VARCHAR(128),
            iucr_code      VARCHAR(4),
            location_desc  VARCHAR(96),
            arrest         TINYINT(1)  NOT NULL DEFAULT 0,
            domestic       TINYINT(1)  NOT NULL DEFAULT 0,
            beat_num       INT,
            district_code  INT,
            ward_no        INT,
            community_code INT,
            fbi_code       VARCHAR(4),
            year  SMALLINT,  month TINYINT,  day_of_week VARCHAR(12),  hour TINYINT,
            latitude  DECIMAL(12,8),  longitude DECIMAL(12,8),
            PRIMARY KEY (case_number),
            UNIQUE  KEY uq_crime_id (id),
            KEY ix_crime_year (year),
            CONSTRAINT fk_crime_iucr      FOREIGN KEY (iucr_code)      REFERENCES iucr(iucr_code),
            CONSTRAINT fk_crime_beat      FOREIGN KEY (beat_num)       REFERENCES police_beat_info(beat_num),
            CONSTRAINT fk_crime_district  FOREIGN KEY (district_code)  REFERENCES district_ps_info(district_code),
            CONSTRAINT fk_crime_community FOREIGN KEY (community_code) REFERENCES city_community(community_code)
        ) ENGINE=InnoDB;
    """, label="SCHEMA")

    r.sub("Reconstructing the IUCR dimension")
    r.step("""
        INDEX_FBI = {'01A','01B','02','03','04A','04B','05','06','07','09'}

        iucr = (df[['iucr_code', 'primary_type', 'description', 'fbi_code']]
                  .drop_duplicates(subset='iucr_code')
                  .sort_values('iucr_code').reset_index(drop=True))
        iucr['index_code'] = np.where(iucr['fbi_code'].isin(INDEX_FBI), 'I', 'N')
        iucr = iucr[['iucr_code', 'primary_type', 'description', 'index_code']]

        print(f"{len(iucr)} IUCR codes rebuilt "
              f"({(iucr.index_code == 'I').sum()} FBI index crimes)")
        print(iucr.head(8).to_string(index=False))
    """)

    r.sub("Writing the cleaned data")
    r.step("""
        from db.etl import full_refresh

        # full_refresh() runs the whole documented pipeline end to end:
        # create schema -> clear rows (DDL preserved) -> clean -> load
        # dimensions -> load facts -> build views -> build summary tables.
        # DataFrames are written with SQLAlchemy's to_sql(); DDL and views go
        # through the raw DB-API connector.
        result = full_refresh(verbose=True)

        print()
        print(f"Backend       : {dbc.backend_label()}")
        print(f"Crimes loaded : {result['crimes']:,}")
        print(f"IUCR codes    : {result['iucr_codes']}")
    """)

    r.step("""
        # Read it straight back out to prove the round trip.
        check = dbc.read_sql('''
            SELECT COUNT(*) AS crimes,
                   COUNT(DISTINCT iucr_code)     AS iucr_codes,
                   COUNT(DISTINCT community_code) AS communities,
                   MIN(year) AS first_year, MAX(year) AS last_year
            FROM chicago_crime
        ''')
        print(check.to_string(index=False))

        print()
        print(dbc.read_sql('''
            SELECT primary_type, COUNT(*) AS crimes
            FROM vw_crime_full GROUP BY primary_type
            ORDER BY crimes DESC LIMIT 5
        ''').to_string(index=False))
    """)

    # ================================================================ ANSWERS
    r.section("7. Answers to the Use Case 1 questions")

    r.sub("How many unique crime types exist in the dataset?")
    r.step("""
        print(f"Distinct primary_type values : {df['primary_type'].nunique()}")
        print(f"Distinct IUCR codes          : {df['iucr_code'].nunique()}")
        print(f"Distinct FBI codes           : {df['fbi_code'].nunique()}")
        print()
        print(df['primary_type'].value_counts().to_string())
    """)
    r.insight("""
        <b>16 unique crime types</b>, expressed through 24 distinct IUCR offence
        codes. The two numbers differ because one crime type covers several
        specific offences — THEFT alone spans shoplifting, theft over $500 and
        theft under $500.
    """)

    r.sub("Are there anomalies in date formats or obvious outliers?")
    r.text("""
        Covered in full in Section 4. In short: <b>no date anomalies</b> — one
        consistent <code>MM/DD/YYYY HH:MM</code> format, zero parse failures,
        no future dates, and the stored <i>year</i> column agrees with the
        parsed date on all 2,000 rows. The outliers that do exist are
        structural rather than dirty data: missing geocodes on ~4% of rows, and
        the ward reference gap described above. Community-area crime-count
        outliers are quantified with the IQR method in Use Case 3.
    """)

    r.sub("Cleaning summary")
    r.step("""
        summary = pd.DataFrame({
            'Metric': ['Rows in', 'Rows out', 'Columns in', 'Columns out',
                       'Duplicate cases removed', 'Unparsable dates',
                       'location_desc set to UNKNOWN', 'Columns dropped (>50% null)',
                       'Unique crime types', 'Unique IUCR codes'],
            'Value': [2000, len(df), 22, df.shape[1],
                      int(df['case_number'].duplicated().sum()),
                      int(df['date'].isna().sum()),
                      94, 0,
                      df['primary_type'].nunique(), df['iucr_code'].nunique()],
        })
        print(summary.to_string(index=False))

        # The brief names the new features Year / Month / DayOfWeek, but the
        # warehouse and every downstream use case speak snake_case. The
        # canonical extract is written once, under the warehouse names, so no
        # column exists twice under two spellings.
        canonical = (df.drop(columns=['year'])
                       .rename(columns={'Year': 'year', 'Month': 'month',
                                        'DayOfWeek': 'day_of_week', 'Hour': 'hour'}))
        canonical.to_csv(config.CLEAN_CRIME_CSV, index=False)
        print(f"\\nCleaned extract written to {config.CLEAN_CRIME_CSV.name} "
              f"({canonical.shape[0]:,} rows x {canonical.shape[1]} columns)")
    """)

    r.insight("""
        The pipeline is idempotent and lossless: every one of the 2,000 source
        rows survives into the warehouse, no column is dropped, and re-running
        it reproduces the identical result. That satisfies the brief's
        requirement that no data be discarded, keeping the extract usable for
        regulatory-compliance and insurance use cases downstream.
    """)

    out = config.REPORTS_DIR / "UseCase1_Load_and_Clean.pdf"
    r.build(out)
    return out


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _fig_missing(env) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    df = env["df"]
    pct = (pd.Series(np.round(df.isna().to_numpy().sum(axis=0) / len(df) * 100, 2),
                     index=df.columns).sort_values(ascending=False))
    pct = pct[pct > 0]

    fig, ax = plt.subplots(figsize=(9, 4.2))
    bars = ax.barh(pct.index[::-1], pct.values[::-1], color=viz.ACCENT, height=0.65)
    ax.axvline(50, color=viz.WARM, linestyle="--", linewidth=1.4)
    ax.text(50.6, -0.4, "50% drop threshold", color=viz.WARM, fontsize=8.5,
            fontweight="bold", va="bottom")
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8, color="#33475B")
    ax.set_xlim(0, 55)
    ax.set_xlabel("Missing values (%)")
    ax.set_title("Missing-value profile — no column is a candidate for dropping")
    ax.grid(axis="y", visible=False)
    return viz.save(fig, "uc1_missing_values")


def _fig_features(env) -> Path:
    import matplotlib.pyplot as plt

    df = env["df"]
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 3.6))

    y = df["Year"].value_counts().sort_index()
    axes[0].plot(y.index, y.values, marker="o", color=viz.ACCENT, linewidth=2.2,
                 markerfacecolor="white", markeredgewidth=2)
    axes[0].fill_between(y.index, y.values, alpha=0.12, color=viz.ACCENT)
    axes[0].set_title("Year")
    axes[0].set_ylabel("Crimes")

    d = df["DayOfWeek"].value_counts().reindex(order)
    axes[1].bar([x[:3] for x in order], d.values, color=viz.ACCENT, width=0.68)
    axes[1].set_title("Day of week")

    m = df["Month"].value_counts().reindex(range(1, 13), fill_value=0)
    axes[2].bar(months, m.values, color=viz.ACCENT, width=0.68)
    axes[2].set_title("Month")
    axes[2].tick_params(axis="x", rotation=45)

    for a in axes:
        a.grid(axis="x", visible=False)
    fig.suptitle("Engineered time features", fontsize=13, fontweight="bold",
                 color=viz.NAVY, y=1.04)
    return viz.save(fig, "uc1_features")


if __name__ == "__main__":
    path = main()
    print(f"\n[Use Case 1] report written to {path}")
