"""
USE CASE 4 — MySQL Reporting & Integration
==========================================

Objective
    Store, query and present the analytical results from the database itself:
    populate summary tables through a Python DB connector, answer the reporting
    questions in SQL rather than in Pandas, publish stored views, read those
    views back into Pandas and chart them.

Backend
    The brief targets MySQL and permits SQLite3 where MySQL is unavailable.
    The code below is backend-neutral: set DB_BACKEND=mysql (plus MYSQL_USER /
    MYSQL_PASSWORD) to run the identical pipeline against a MySQL server.

Run:
    python usecases/usecase4_sql_reporting.py

Produces:
    usecases/reports/UseCase4_SQL_Reporting.pdf
    usecases/figures/uc4_*.png
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
    number=4,
    title="Database Reporting and Pandas Integration",
    objective="Summary tables, SQL reporting queries, stored views and charts from SQL.",
    backend=dbc.backend_label(),
)
REPORT.env.update({"config": config, "dbc": dbc, "viz": viz, "Path": Path})


def ensure_warehouse():
    """Make sure the warehouse exists before the report queries it."""
    if not dbc.table_exists("chicago_crime"):
        from db.etl import full_refresh
        full_refresh(verbose=False)


def main() -> Path:
    ensure_warehouse()
    r = REPORT

    # ================================================================= INTRO
    r.section("1. Connecting to the warehouse")
    r.text(f"""
        Everything in this use case is executed against the database, not
        against a DataFrame. The connection is opened with a raw Python DB-API
        connector — <code>pymysql</code> for MySQL, <code>sqlite3</code> for the
        fallback backend — because the brief asks for the summary tables to be
        created and loaded "through the Python connector". Bulk DataFrame reads
        use SQLAlchemy on top of the same connection string.
        <br/><br/>
        This run targets <b>{dbc.backend_label()}</b>. A MySQL server was not
        reachable with credentials in this environment, so the SQLite3 fallback
        the brief explicitly allows is in use. Nothing else changes: the DDL in
        <code>sql/schema_mysql.sql</code> and
        <code>sql/schema_sqlite.sql</code> is structurally identical, and the
        view definitions in <code>sql/views.sql</code> are portable SQL shared
        by both backends.
    """)
    r.step("""
        import numpy as np
        import pandas as pd

        pd.set_option('display.width', 110)

        # Raw DB-API connection: pymysql.connect(...) or sqlite3.connect(...)
        # depending on DB_BACKEND. See db/connection.py.
        conn = dbc.get_connector()
        cur = conn.cursor()

        print(f"Backend : {dbc.backend_label()}")

        table_sql = ("SHOW TABLES" if config.DB_BACKEND == 'mysql' else
                     "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        cur.execute(table_sql)
        print("Tables  :", ", ".join(row[0] for row in cur.fetchall()))
    """)

    r.step("""
        cur.execute("SELECT COUNT(*) FROM chicago_crime")
        crimes = cur.fetchone()[0]

        for table in ['iucr', 'city_community', 'district_ps_info',
                      'police_beat_info', 'ward_office']:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"{table:20s}: {cur.fetchone()[0]:>5,} rows")
        print(f"{'chicago_crime':20s}: {crimes:>5,} rows  (fact table)")
    """)

    # ======================================================= 2. SUMMARY TABLES
    r.section("2. Designing and populating the summary tables")
    r.requirement("""
        Create summary tables in the database and load them, doing the work
        through the Python database connector rather than by hand.
    """)
    r.text("""
        Three pre-aggregated tables serve the reporting layer. They exist so a
        dashboard never has to scan the fact table for a headline number: the
        yearly and category rollups answer the questions below in a single
        indexed row read each.
    """)
    r.code_block("""
        -- sql/schema_mysql.sql (summary layer)
        CREATE TABLE summary_crime_yearly (
            year         SMALLINT NOT NULL,
            total_crimes INT      NOT NULL,
            arrests      INT      NOT NULL,
            arrest_rate  DECIMAL(6,2),
            PRIMARY KEY (year)
        ) ENGINE=InnoDB;

        CREATE TABLE summary_crime_by_category (
            primary_type VARCHAR(64) NOT NULL,
            total_crimes INT         NOT NULL,
            pct_of_total DECIMAL(6,2),
            arrests      INT,
            arrest_rate  DECIMAL(6,2),
            PRIMARY KEY (primary_type)
        ) ENGINE=InnoDB;

        CREATE TABLE summary_crime_by_community (
            community_code INT NOT NULL,
            community_name VARCHAR(96),
            total_crimes   INT NOT NULL,
            population     INT,
            crimes_per_10k DECIMAL(12,2),
            PRIMARY KEY (community_code)
        ) ENGINE=InnoDB;
    """, label="SCHEMA — summary tables")

    r.step("""
        # Populate summary_crime_yearly straight from the fact table, using the
        # connector's parameter binding rather than string-formatted SQL.
        placeholder = '%s' if config.DB_BACKEND == 'mysql' else '?'

        cur.execute("DELETE FROM summary_crime_yearly")
        cur.execute('''
            SELECT year,
                   COUNT(*)                                 AS total_crimes,
                   SUM(arrest)                              AS arrests,
                   ROUND(SUM(arrest) * 100.0 / COUNT(*), 2) AS arrest_rate
            FROM   chicago_crime
            GROUP  BY year
            ORDER  BY year
        ''')
        rows = cur.fetchall()

        cur.executemany(
            f"INSERT INTO summary_crime_yearly "
            f"(year, total_crimes, arrests, arrest_rate) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
            rows)
        conn.commit()

        print(f"{cur.rowcount if cur.rowcount > 0 else len(rows)} rows written "
              f"to summary_crime_yearly")
        cur.execute("SELECT * FROM summary_crime_yearly ORDER BY year")
        for row in cur.fetchall():
            print(f"  {row[0]}  crimes={row[1]:>4}  arrests={row[2]:>3}  rate={row[3]:>6}%")
    """)

    r.step("""
        # The other two summary tables are rebuilt the same way by the pipeline.
        from db.etl import build_summary_tables

        written = build_summary_tables()
        for table, n in written.items():
            print(f"{table:28s}: {n:>3} rows")

        print()
        print(dbc.read_sql('''
            SELECT primary_type, total_crimes, pct_of_total, arrest_rate
            FROM   summary_crime_by_category
            ORDER  BY total_crimes DESC LIMIT 8
        ''').to_string(index=False))
    """)

    # ============================================================ 3. QUERIES
    r.section("3. The reporting queries, written in SQL")
    r.requirement("""
        Write SQL that computes the crime count per year, the top 5 crime types
        with their percentages, and the arrest count per year.
    """)

    r.sub("3.1 Crime count per year")
    r.step("""
        q_yearly = '''
            SELECT year,
                   COUNT(*) AS crime_count
            FROM   chicago_crime
            GROUP  BY year
            ORDER  BY year
        '''
        cur.execute(q_yearly)
        for year, count in cur.fetchall():
            bar = '#' * int(count / 6)
            print(f"{year}  {count:>4}  {bar}")
    """)

    r.sub("3.2 Top 5 crime types and their percentages")
    r.step("""
        q_top5 = '''
            SELECT i.primary_type,
                   COUNT(*)                                                          AS crime_count,
                   ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM chicago_crime), 2)  AS pct_of_total
            FROM       chicago_crime c
            INNER JOIN iucr i ON i.iucr_code = c.iucr_code
            GROUP  BY  i.primary_type
            ORDER  BY  crime_count DESC
            LIMIT  5
        '''
        cur.execute(q_top5)
        top5 = cur.fetchall()

        print(f"{'PRIMARY TYPE':<24}{'COUNT':>8}{'% OF ALL':>10}")
        print("-" * 42)
        running = 0
        for name, count, pct in top5:
            running += pct
            print(f"{name:<24}{count:>8,}{pct:>9.2f}%")
        print("-" * 42)
        print(f"{'TOP 5 COMBINED':<24}{sum(t[1] for t in top5):>8,}{running:>9.2f}%")
    """)

    r.sub("3.3 Arrest count per year")
    r.step("""
        q_arrests = '''
            SELECT year,
                   COUNT(*)                                 AS crimes,
                   SUM(arrest)                              AS arrests,
                   COUNT(*) - SUM(arrest)                   AS no_arrest,
                   ROUND(SUM(arrest) * 100.0 / COUNT(*), 2) AS arrest_rate
            FROM   chicago_crime
            GROUP  BY year
            ORDER  BY year
        '''
        arrests_df = dbc.read_sql(q_arrests)
        print(arrests_df.to_string(index=False))

        print(f"\\nTotal arrests {arrests_df['arrests'].sum():,} of "
              f"{arrests_df['crimes'].sum():,} crimes "
              f"({arrests_df['arrests'].sum() / arrests_df['crimes'].sum() * 100:.2f}%)")
    """)

    r.sub("3.4 A question only SQL answers cleanly: joined hotspot reporting")
    r.step("""
        q_hotspots = '''
            SELECT cc.community_name,
                   d.district_name,
                   COUNT(*)                                  AS crimes,
                   SUM(c.arrest)                             AS arrests,
                   ROUND(SUM(c.arrest)*100.0 / COUNT(*), 1)  AS arrest_rate
            FROM       chicago_crime    c
            INNER JOIN city_community   cc ON cc.community_code = c.community_code
            INNER JOIN district_ps_info d  ON d.district_code   = c.district_code
            GROUP  BY  cc.community_name, d.district_name
            HAVING     COUNT(*) >= 10
            ORDER  BY  crimes DESC
            LIMIT      10
        '''
        print(dbc.read_sql(q_hotspots).to_string(index=False))
    """)
    r.insight("""
        The join above is the reason the data was modelled as a star schema in
        the first place. Community name, district name and arrest outcome live
        in three different tables, and a single SQL statement assembles the
        patrol-level report from all of them — no data movement, no Python loop,
        and every number consistent with the fact table by construction.
    """)

    # ============================================================== 4. VIEWS
    r.section("4. Stored database views")
    r.requirement("""
        Create the views vw_crime_yearly and vw_crime_by_category in the
        database.
    """)
    r.text("""
        Views push the business logic into the database, so the web application,
        this report and any future BI tool all read the same definition of
        "arrest rate" rather than each re-implementing it. Six views ship with
        the project; the two the brief names are shown below in full.
    """)
    r.code_block("""
        -- sql/views.sql
        DROP VIEW IF EXISTS vw_crime_yearly;
        CREATE VIEW vw_crime_yearly AS
        SELECT  year,
                COUNT(*)                                 AS total_crimes,
                SUM(arrest)                              AS arrests,
                ROUND(SUM(arrest) * 100.0 / COUNT(*), 2) AS arrest_rate,
                SUM(domestic)                            AS domestic_incidents
        FROM    chicago_crime
        GROUP BY year;

        DROP VIEW IF EXISTS vw_crime_by_category;
        CREATE VIEW vw_crime_by_category AS
        SELECT  i.primary_type,
                COUNT(*)                                                          AS total_crimes,
                ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM chicago_crime), 2) AS pct_of_total,
                SUM(c.arrest)                                                     AS arrests,
                ROUND(SUM(c.arrest) * 100.0 / COUNT(*), 2)                        AS arrest_rate
        FROM        chicago_crime c
        INNER JOIN  iucr i ON i.iucr_code = c.iucr_code
        GROUP BY    i.primary_type;
    """, label="SQL — stored views")

    r.step("""
        # create_views() executes sql/views.sql statement by statement through
        # the connector, so the same file provisions MySQL or SQLite.
        n = dbc.create_views()
        print(f"{n} view statements executed from sql/views.sql")

        view_sql = ("SELECT table_name FROM information_schema.views "
                    "WHERE table_schema = DATABASE()"
                    if config.DB_BACKEND == 'mysql' else
                    "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
        cur.execute(view_sql)
        for (name,) in cur.fetchall():
            print(f"  - {name}")
    """)

    # ================================================== 5. PANDAS INTEGRATION
    r.section("5. Reading the views back into Pandas")
    r.requirement("""
        Read the stored views into Pandas DataFrames for further analysis, e.g.
        pd.read_sql("SELECT * FROM vw_crime_yearly", conn).
    """)
    r.step("""
        yearly = pd.read_sql("SELECT * FROM vw_crime_yearly ORDER BY year", conn)
        category = pd.read_sql(
            "SELECT * FROM vw_crime_by_category ORDER BY total_crimes DESC", conn)

        print("vw_crime_yearly")
        print(yearly.to_string(index=False))
        print(f"\\ndtypes: {dict(yearly.dtypes.astype(str))}")
    """)
    r.step("""
        print("vw_crime_by_category")
        print(category.to_string(index=False))
    """)
    r.step("""
        # With the views in a DataFrame, ordinary Pandas analysis continues.
        yearly['crimes_vs_mean'] = (yearly['total_crimes'] -
                                    yearly['total_crimes'].mean()).round(1)
        yearly['yoy_change_pct'] = (yearly['total_crimes'].pct_change() * 100).round(2)

        print(yearly[['year', 'total_crimes', 'crimes_vs_mean',
                      'yoy_change_pct', 'arrest_rate']].to_string(index=False))

        print(f"\\nSharpest fall : {yearly['yoy_change_pct'].min():.2f}% in "
              f"{int(yearly.loc[yearly['yoy_change_pct'].idxmin(), 'year'])}")
        print(f"Sharpest rise : +{yearly['yoy_change_pct'].max():.2f}% in "
              f"{int(yearly.loc[yearly['yoy_change_pct'].idxmax(), 'year'])}")

        hi_vol_low_clear = category[(category['total_crimes'] > category['total_crimes'].median())
                                    & (category['arrest_rate'] < category['arrest_rate'].median())]
        print("\\nHigh volume but below-median clearance — the priority quadrant:")
        print(hi_vol_low_clear[['primary_type', 'total_crimes',
                                'arrest_rate']].to_string(index=False))
    """)
    r.insight("""
        Filtering the category view to above-median volume and below-median
        clearance isolates four categories — <b>THEFT, ASSAULT, BURGLARY and
        MOTOR VEHICLE THEFT — which together are 45.3% of all recorded
        crime</b>. Three of them are property crimes clustered at just 13.0%
        to 16.1% clearance, less than half the 29.8% force-wide average;
        ASSAULT sits marginally below the median at 29.7%. The property-crime
        trio is where additional investigative capacity would change the most
        outcomes, because it combines the largest caseload in the city with the
        worst clearance in the city.
    """)

    # =============================================== 6. CHARTS FROM SQL DATA
    r.section("6. Visualising the SQL results")
    r.requirement("""
        Plot the SQL-extracted data with Matplotlib.
    """)
    r.text("""
        Every series below was read out of a database view rather than computed
        in Pandas, which is what makes these charts reproducible from the
        warehouse alone.
    """)
    fig = _fig_yearly(REPORT.env)
    r.figure(fig, "vw_crime_yearly — crime volume and arrests per year, straight from the view.")
    fig = _fig_category(REPORT.env)
    r.figure(fig, "vw_crime_by_category — volume against clearance rate, with the priority quadrant marked.")

    r.step("""
        top_communities = pd.read_sql('''
            SELECT community_name, total_crimes, crimes_per_10k, arrest_rate
            FROM   vw_crime_by_community
            ORDER  BY total_crimes DESC
            LIMIT  12
        ''', conn)
        print(top_communities.to_string(index=False))

        hourly = pd.read_sql("SELECT * FROM vw_crime_hourly ORDER BY hour", conn)
        print(f"\\nPeak hour from vw_crime_hourly: "
              f"{int(hourly.loc[hourly['total_crimes'].idxmax(), 'hour']):02d}:00 "
              f"({int(hourly['total_crimes'].max())} crimes)")
    """)
    fig = _fig_community_hour(REPORT.env)
    r.figure(fig, "vw_crime_by_community and vw_crime_hourly rendered with Matplotlib.")

    r.step("""
        cur.close()
        conn.close()
        print("Connection closed cleanly.")
    """)

    r.section("7. What the database layer delivers")
    r.text("""
        The warehouse now holds 2,000 crimes in a normalised star schema with
        enforced primary and foreign keys, three pre-aggregated summary tables,
        and six stored views that define every published metric exactly once.
        The same schema runs on MySQL or SQLite3 from a single environment
        variable, and the web application in <code>webapp/</code> reads and
        writes through this identical layer — so a record edited in the browser
        is immediately reflected in every query, view and chart shown here.
    """)
    r.insight("""
        <b>Three things this layer gives the CPD that a spreadsheet cannot.</b>
        First, one definition of truth: arrest rate is computed in
        <code>vw_crime_yearly</code> and nowhere else, so no two reports can
        disagree. Second, referential integrity: a crime cannot be filed
        against a district, beat, community or IUCR code that does not exist.
        Third, a genuine audit trail — every row of the original extract is
        preserved with its case number, which is what the brief's regulatory
        compliance, insurance and public-safety use cases depend on.
    """)

    out = config.REPORTS_DIR / "UseCase4_SQL_Reporting.pdf"
    r.build(out)
    return out


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _fig_yearly(env) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np

    y = env["yearly"]
    fig, ax = plt.subplots(figsize=(10.4, 4.4))
    x = np.arange(len(y))
    w = 0.42

    b1 = ax.bar(x - w / 2, y["total_crimes"], w, label="Total crimes", color=viz.ACCENT)
    b2 = ax.bar(x + w / 2, y["arrests"], w, label="Arrests", color=viz.NAVY)
    ax.bar_label(b1, fmt="%d", padding=2, fontsize=7.6, color="#33475B")
    ax.bar_label(b2, fmt="%d", padding=2, fontsize=7.6, color="#33475B")

    ax2 = ax.twinx()
    ax2.plot(x, y["arrest_rate"], marker="o", color=viz.WARM, linewidth=2.2,
             markersize=6, markerfacecolor="white", markeredgewidth=2,
             label="Arrest rate (%)")
    ax2.set_ylim(0, max(y["arrest_rate"]) * 2.1)
    ax2.set_ylabel("Arrest rate (%)", color=viz.WARM)
    ax2.tick_params(axis="y", colors=viz.WARM)
    ax2.grid(False)

    ax.set_xticks(x)
    ax.set_xticklabels(y["year"].astype(int))
    ax.set_ylabel("Count")
    ax.set_ylim(0, y["total_crimes"].max() * 1.24)
    ax.set_title("SELECT * FROM vw_crime_yearly")
    ax.grid(axis="x", visible=False)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", ncol=3, fontsize=8.5)
    fig.tight_layout()
    return viz.save(fig, "uc4_yearly_from_view")


def _fig_category(env) -> Path:
    import matplotlib.pyplot as plt

    c = env["category"]
    med_v = c["total_crimes"].median()
    med_r = c["arrest_rate"].median()

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.8),
                             gridspec_kw={"width_ratios": [1, 1.12]})

    t = c.head(10).iloc[::-1]
    bars = axes[0].barh(t["primary_type"], t["total_crimes"], color=viz.ACCENT, height=0.68)
    for bar, n, p in zip(bars, t["total_crimes"], t["pct_of_total"]):
        axes[0].text(n + 5, bar.get_y() + bar.get_height() / 2, f"{n} ({p}%)",
                     va="center", fontsize=8, color="#33475B")
    axes[0].set_xlim(0, t["total_crimes"].max() * 1.26)
    axes[0].set_xlabel("Total crimes")
    axes[0].set_title("vw_crime_by_category — volume")
    axes[0].tick_params(axis="y", labelsize=8)
    axes[0].grid(axis="y", visible=False)

    ax = axes[1]
    ax.axvspan(med_v, c["total_crimes"].max() * 1.2, ymin=0, ymax=1,
               color=viz.WARM, alpha=0.06)
    ax.axhline(med_r, color="#8FA9C2", linestyle=":", linewidth=1.2)
    ax.axvline(med_v, color="#8FA9C2", linestyle=":", linewidth=1.2)
    for _, row in c.iterrows():
        priority = row["total_crimes"] > med_v and row["arrest_rate"] < med_r
        ax.scatter(row["total_crimes"], row["arrest_rate"], s=110,
                   color=viz.WARM if priority else viz.ACCENT,
                   edgecolor="white", linewidth=1.4, zorder=3)
        ax.annotate(row["primary_type"].title(),
                    (row["total_crimes"], row["arrest_rate"]),
                    textcoords="offset points", xytext=(7, 4), fontsize=7,
                    color=viz.NAVY if priority else "#5A6B7C")
    ax.text(c["total_crimes"].max() * 0.62, med_r * 0.35,
            "PRIORITY QUADRANT\nhigh volume · low clearance",
            fontsize=8.5, color=viz.WARM, fontweight="bold", ha="center")
    ax.set_xlim(0, c["total_crimes"].max() * 1.22)
    ax.set_xlabel("Total crimes")
    ax.set_ylabel("Arrest rate (%)")
    ax.set_title("Volume vs clearance — where to add capacity")

    fig.tight_layout()
    return viz.save(fig, "uc4_category_from_view")


def _fig_community_hour(env) -> Path:
    import matplotlib.pyplot as plt

    top = env["top_communities"]
    hourly = env["hourly"]

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.4),
                             gridspec_kw={"width_ratios": [1, 1.15]})

    t = top.head(10).iloc[::-1]
    b = axes[0].barh(t["community_name"], t["total_crimes"], color=viz.ACCENT, height=0.66)
    axes[0].bar_label(b, fmt="%d", padding=3, fontsize=8, color="#33475B")
    axes[0].set_xlim(0, t["total_crimes"].max() * 1.16)
    axes[0].set_xlabel("Total crimes")
    axes[0].set_title("vw_crime_by_community — top 10 areas")
    axes[0].tick_params(axis="y", labelsize=8)
    axes[0].grid(axis="y", visible=False)

    h = hourly
    axes[1].fill_between(h["hour"], h["total_crimes"], alpha=0.14, color=viz.ACCENT)
    axes[1].plot(h["hour"], h["total_crimes"], marker="o", color=viz.ACCENT,
                 linewidth=2.2, markersize=4.5, markerfacecolor="white",
                 markeredgewidth=1.4)
    axes[1].set_xticks(range(0, 24, 2))
    axes[1].set_xlabel("Hour of day")
    axes[1].set_ylabel("Total crimes")
    axes[1].set_title("vw_crime_hourly — the patrol-planning curve")
    axes[1].grid(axis="x", visible=False)

    fig.tight_layout()
    return viz.save(fig, "uc4_community_hourly_from_view")


if __name__ == "__main__":
    path = main()
    print(f"\n[Use Case 4] report written to {path}")
