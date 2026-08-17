"""
Chicago Crime Analytics — web application.

Five tabs:
    1. Crime Data   — CSV upload + full CRUD against the warehouse
    2. Data Quality — Use Case 1 insights (ingestion and cleaning)
    3. Exploration  — Use Case 2 insights (trends, categories, hotspots)
    4. Statistics   — Use Case 3 insights (hourly, outliers, correlation)
    5. SQL Reports  — Use Case 4 insights (views, summary tables)

Tab 1 writes straight through to MySQL/SQLite, and tabs 2-5 read from the same
warehouse, so any edit made here is visible in every chart on the next load.

Run:
    python webapp/app.py            then open http://127.0.0.1:5000
"""
from __future__ import annotations

import io
import math
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, url_for)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from db import connection as dbc  # noqa: E402
from db import etl  # noqa: E402
from webapp import charts  # noqa: E402

app = Flask(__name__)
app.secret_key = "cpd-crime-analytics-accenture"
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB uploads

PAGE_SIZE = 25

# Bumped on every write so chart caches and <img> URLs invalidate together.
DATA_VERSION = {"v": 0}


def bump_version() -> None:
    DATA_VERSION["v"] += 1
    charts.clear_cache()


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #
def ensure_warehouse() -> None:
    """Build the warehouse from data/raw the first time the app runs."""
    try:
        if not dbc.table_exists("chicago_crime"):
            app.logger.info("Warehouse not found — running the ETL pipeline.")
            etl.full_refresh(verbose=False)
        elif dbc.read_sql("SELECT COUNT(*) AS n FROM chicago_crime")["n"].iloc[0] == 0:
            app.logger.info("Warehouse is empty — running the ETL pipeline.")
            etl.full_refresh(verbose=False)
    except Exception:
        app.logger.error("Warehouse bootstrap failed:\n%s", traceback.format_exc())


# --------------------------------------------------------------------------- #
# Shared context
# --------------------------------------------------------------------------- #
@app.context_processor
def inject_globals():
    return {
        "backend": dbc.backend_label(),
        "data_version": DATA_VERSION["v"],
        "now": datetime.now(),
    }


def headline_stats() -> dict:
    """The KPI strip shown at the top of every tab."""
    try:
        row = dbc.read_sql("""
            SELECT COUNT(*)                                  AS crimes,
                   SUM(arrest)                               AS arrests,
                   SUM(domestic)                             AS domestic,
                   COUNT(DISTINCT community_code)            AS areas,
                   COUNT(DISTINCT iucr_code)                 AS offences,
                   MIN(year)                                 AS first_year,
                   MAX(year)                                 AS last_year
            FROM chicago_crime
        """).iloc[0]
        crimes = int(row["crimes"] or 0)
        arrests = int(row["arrests"] or 0)
        top = dbc.read_sql("""
            SELECT primary_type, total_crimes FROM vw_crime_by_category
            ORDER BY total_crimes DESC LIMIT 1
        """)
        return {
            "crimes": crimes,
            "arrests": arrests,
            "arrest_rate": round(arrests / crimes * 100, 1) if crimes else 0.0,
            "domestic": int(row["domestic"] or 0),
            "areas": int(row["areas"] or 0),
            "offences": int(row["offences"] or 0),
            "span": (f"{int(row['first_year'])}–{int(row['last_year'])}"
                     if crimes else "—"),
            "top_type": top["primary_type"].iloc[0] if len(top) else "—",
        }
    except Exception:
        app.logger.error("headline_stats failed:\n%s", traceback.format_exc())
        return {"crimes": 0, "arrests": 0, "arrest_rate": 0.0, "domestic": 0,
                "areas": 0, "offences": 0, "span": "—", "top_type": "—"}


def lookup_options() -> dict:
    """Reference data used to populate the CRUD form's dropdowns."""
    try:
        return {
            "iucr": dbc.read_sql(
                "SELECT iucr_code, primary_type, description FROM iucr "
                "ORDER BY primary_type, description").to_dict("records"),
            "districts": dbc.read_sql(
                "SELECT district_code, district_name FROM district_ps_info "
                "ORDER BY district_code").to_dict("records"),
            "communities": dbc.read_sql(
                "SELECT community_code, community_name FROM city_community "
                "ORDER BY community_name").to_dict("records"),
            "beats": dbc.read_sql(
                "SELECT beat_num FROM police_beat_info ORDER BY beat_num"
            )["beat_num"].tolist(),
            "locations": dbc.read_sql(
                "SELECT DISTINCT location_desc FROM chicago_crime "
                "WHERE location_desc IS NOT NULL ORDER BY location_desc"
            )["location_desc"].tolist(),
        }
    except Exception:
        return {"iucr": [], "districts": [], "communities": [], "beats": [],
                "locations": []}


# --------------------------------------------------------------------------- #
# Tab 1 — Crime data: browse + CRUD
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return redirect(url_for("data_tab"))


@app.route("/data")
def data_tab():
    q = (request.args.get("q") or "").strip()
    ptype = (request.args.get("type") or "").strip()
    year = (request.args.get("year") or "").strip()
    arrest = (request.args.get("arrest") or "").strip()
    page = max(1, int(request.args.get("page") or 1))

    where, params = [], {}
    if q:
        where.append("(UPPER(v.case_number) LIKE :q OR UPPER(v.block) LIKE :q "
                     "OR UPPER(v.primary_type) LIKE :q OR UPPER(v.location_desc) LIKE :q "
                     "OR UPPER(v.community_name) LIKE :q)")
        params["q"] = f"%{q.upper()}%"
    if ptype:
        where.append("v.primary_type = :ptype")
        params["ptype"] = ptype
    if year:
        where.append("v.year = :year")
        params["year"] = int(year)
    if arrest in ("0", "1"):
        where.append("v.arrest = :arrest")
        params["arrest"] = int(arrest)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = int(dbc.read_sql(
        f"SELECT COUNT(*) AS n FROM vw_crime_full v {clause}", params)["n"].iloc[0])
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, pages)

    frame = dbc.read_sql(f"""
        SELECT v.case_number, v.id, v.date, v.primary_type, v.description,
               v.location_desc, v.block, v.arrest, v.domestic, v.district_name,
               v.community_name, v.year, v.iucr_code
        FROM vw_crime_full v
        {clause}
        ORDER BY v.date DESC
        LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}
    """, params)
    # NaN would render as the literal string "nan" in the template.
    rows = frame.astype(object).where(pd.notna(frame), None).to_dict("records")

    filters = {
        "types": dbc.read_sql(
            "SELECT DISTINCT primary_type FROM iucr ORDER BY primary_type"
        )["primary_type"].tolist(),
        "years": dbc.read_sql(
            "SELECT DISTINCT year FROM chicago_crime ORDER BY year DESC"
        )["year"].tolist(),
    }

    return render_template("tab1_data.html", tab="data", rows=rows, total=total,
                           page=page, pages=pages, filters=filters,
                           stats=headline_stats(),
                           query={"q": q, "type": ptype, "year": year,
                                  "arrest": arrest})


@app.route("/data/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV file before uploading.", "error")
        return redirect(url_for("data_tab"))
    if not file.filename.lower().endswith(".csv"):
        flash("Only .csv files can be uploaded.", "error")
        return redirect(url_for("data_tab"))

    try:
        raw = pd.read_csv(io.BytesIO(file.read()),
                          dtype={"iucr_code": str, "fbi_code": str,
                                 "case_number": str})
    except Exception as exc:
        flash(f"Could not read that CSV: {exc}", "error")
        return redirect(url_for("data_tab"))

    required = {"case_number", "date", "iucr_code"}
    missing = required - {c.strip().lower().replace(" ", "_") for c in raw.columns}
    if missing:
        flash(f"That file is missing required column(s): {', '.join(sorted(missing))}. "
              "Upload an extract shaped like chicago_crime_dataset.csv.", "error")
        return redirect(url_for("data_tab"))

    try:
        clean, audit = etl.clean_crime_frame(raw)
        new_codes = etl.sync_iucr(etl.derive_iucr_table(clean))
        inserted, updated = etl.upsert_crimes(clean)
        etl.build_summary_tables()
        bump_version()
    except Exception as exc:
        app.logger.error("Upload failed:\n%s", traceback.format_exc())
        flash(f"Upload failed while writing to the warehouse: {exc}", "error")
        return redirect(url_for("data_tab"))

    flash(f"Loaded {file.filename}: {inserted:,} new record(s), {updated:,} updated, "
          f"{new_codes} new IUCR code(s). "
          f"Cleaning removed {audit['duplicate_case_numbers']} duplicate case number(s) "
          f"and {audit['unparsable_dates']} unparsable date(s).", "success")
    return redirect(url_for("data_tab"))


@app.route("/data/new", methods=["GET", "POST"])
def create_record():
    if request.method == "POST":
        return _save_record(None)
    return render_template("tab1_form.html", tab="data", record=None,
                           options=lookup_options(), stats=headline_stats())


@app.route("/data/<case_number>/edit", methods=["GET", "POST"])
def edit_record(case_number):
    if request.method == "POST":
        return _save_record(case_number)
    rows = dbc.read_sql(
        "SELECT * FROM chicago_crime WHERE case_number = :c",
        {"c": case_number}).to_dict("records")
    if not rows:
        abort(404)
    return render_template("tab1_form.html", tab="data", record=rows[0],
                           options=lookup_options(), stats=headline_stats())


@app.route("/data/<case_number>/delete", methods=["POST"])
def delete_record(case_number):
    ph = "%s" if config.DB_BACKEND == "mysql" else "?"
    try:
        with dbc.connector() as conn:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM chicago_crime WHERE case_number = {ph}",
                        (case_number,))
            deleted = cur.rowcount
            cur.close()
        etl.build_summary_tables()
        bump_version()
    except Exception as exc:
        flash(f"Could not delete {case_number}: {exc}", "error")
        return redirect(url_for("data_tab"))

    if deleted:
        flash(f"Deleted case {case_number}.", "success")
    else:
        flash(f"No case named {case_number} exists.", "error")
    return redirect(request.form.get("next") or url_for("data_tab"))


def _save_record(existing_case: str | None):
    """Insert or update one crime record from the form payload."""
    form = request.form

    def val(name, cast=None, default=None):
        raw = (form.get(name) or "").strip()
        if raw == "":
            return default
        if cast is None:
            return raw
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default

    case_number = (val("case_number") or "").upper()
    if not case_number:
        flash("Case number is required.", "error")
        return redirect(request.url)

    date_raw = val("date")
    if not date_raw:
        flash("Date is required.", "error")
        return redirect(request.url)
    try:
        dt = pd.to_datetime(date_raw)
    except Exception:
        flash(f"Could not read '{date_raw}' as a date and time.", "error")
        return redirect(request.url)

    iucr = (val("iucr_code") or "").zfill(4)
    fbi = dbc.read_sql("SELECT iucr_code FROM iucr WHERE iucr_code = :i",
                       {"i": iucr})
    if fbi.empty:
        flash(f"IUCR code {iucr} is not in the offence dimension.", "error")
        return redirect(request.url)

    record = {
        "case_number": case_number,
        "id": val("id", int) or int(datetime.now().timestamp() * 1000) % 10**10,
        "date": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "block": (val("block") or "").upper() or None,
        "iucr_code": iucr,
        "location_desc": (val("location_desc") or "UNKNOWN").upper(),
        "arrest": 1 if form.get("arrest") else 0,
        "domestic": 1 if form.get("domestic") else 0,
        "beat_num": val("beat_num", int),
        "district_code": val("district_code", int),
        "ward_no": val("ward_no", int),
        "community_code": val("community_code", int),
        "fbi_code": (val("fbi_code") or "").upper() or None,
        "x_coordinate": val("x_coordinate", float),
        "y_coordinate": val("y_coordinate", float),
        "year": dt.year,
        "month": dt.month,
        "day_of_week": dt.day_name(),
        "hour": dt.hour,
        "date_of_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latitude": val("latitude", float),
        "longitude": val("longitude", float),
        "location": None,
    }
    if record["latitude"] is not None and record["longitude"] is not None:
        record["location"] = f"({record['latitude']}, {record['longitude']})"

    if not existing_case:
        clash = dbc.read_sql(
            "SELECT case_number FROM chicago_crime WHERE case_number = :c",
            {"c": case_number})
        if not clash.empty:
            flash(f"Case {case_number} already exists — open it from the list to edit it.",
                  "error")
            return redirect(request.url)

    cols = etl.CRIME_COLUMNS
    ph = "%s" if config.DB_BACKEND == "mysql" else "?"
    try:
        with dbc.connector() as conn:
            cur = conn.cursor()
            if existing_case:
                setters = ", ".join(f"{c} = {ph}" for c in cols if c != "case_number")
                cur.execute(
                    f"UPDATE chicago_crime SET {setters} WHERE case_number = {ph}",
                    tuple(record[c] for c in cols if c != "case_number") + (existing_case,))
                verb = "Updated"
            else:
                marks = ", ".join([ph] * len(cols))
                cur.execute(
                    f"INSERT INTO chicago_crime ({', '.join(cols)}) VALUES ({marks})",
                    tuple(record[c] for c in cols))
                verb = "Created"
            cur.close()
        etl.build_summary_tables()
        bump_version()
    except Exception as exc:
        app.logger.error("Save failed:\n%s", traceback.format_exc())
        flash(f"Could not save case {case_number}: {exc}", "error")
        return redirect(request.url)

    flash(f"{verb} case {case_number}.", "success")
    return redirect(url_for("data_tab"))


@app.route("/data/rebuild", methods=["POST"])
def rebuild():
    """Discard edits and reload everything from data/raw."""
    try:
        result = etl.full_refresh(verbose=False)
        bump_version()
        flash(f"Warehouse rebuilt from the source files: "
              f"{result['crimes']:,} crimes, {result['iucr_codes']} IUCR codes.",
              "success")
    except Exception as exc:
        app.logger.error("Rebuild failed:\n%s", traceback.format_exc())
        flash(f"Rebuild failed: {exc}", "error")
    return redirect(url_for("data_tab"))


# --------------------------------------------------------------------------- #
# Tabs 2-5 — insight dashboards
# --------------------------------------------------------------------------- #
@app.route("/quality")
def quality_tab():
    audit = {}
    try:
        audit["total"] = int(dbc.read_sql(
            "SELECT COUNT(*) AS n FROM chicago_crime")["n"].iloc[0])
        audit["dupes"] = int(dbc.read_sql(
            "SELECT COUNT(*) - COUNT(DISTINCT case_number) AS n "
            "FROM chicago_crime")["n"].iloc[0])
        audit["unknown_location"] = int(dbc.read_sql(
            "SELECT COUNT(*) AS n FROM chicago_crime "
            "WHERE location_desc = 'UNKNOWN'")["n"].iloc[0])
        audit["no_geo"] = int(dbc.read_sql(
            "SELECT COUNT(*) AS n FROM chicago_crime "
            "WHERE latitude IS NULL")["n"].iloc[0])
        audit["no_ward"] = int(dbc.read_sql(
            "SELECT COUNT(*) AS n FROM chicago_crime "
            "WHERE ward_no IS NULL")["n"].iloc[0])
        audit["orphan_ward"] = int(dbc.read_sql(
            "SELECT COUNT(*) AS n FROM chicago_crime c "
            "WHERE c.ward_no IS NOT NULL AND c.ward_no NOT IN "
            "(SELECT ward_no FROM ward_office)")["n"].iloc[0])
        audit["tables"] = dbc.read_sql("""
            SELECT 'chicago_crime' AS name, COUNT(*) AS rows_n FROM chicago_crime
        """).to_dict("records")
    except Exception:
        app.logger.error("quality_tab failed:\n%s", traceback.format_exc())

    return render_template("tab2_quality.html", tab="quality",
                           stats=headline_stats(), audit=audit)


@app.route("/exploration")
def exploration_tab():
    ctx = {}
    try:
        ctx["categories"] = dbc.read_sql("""
            SELECT primary_type, total_crimes, pct_of_total, arrest_rate
            FROM vw_crime_by_category ORDER BY total_crimes DESC LIMIT 10
        """).to_dict("records")
        ctx["yearly"] = dbc.read_sql(
            "SELECT * FROM vw_crime_yearly ORDER BY year").to_dict("records")
        ctx["communities"] = dbc.read_sql("""
            SELECT community_name, total_crimes, crimes_per_10k, arrest_rate
            FROM vw_crime_by_community ORDER BY total_crimes DESC LIMIT 10
        """).to_dict("records")
        months = dbc.read_sql(
            "SELECT month, COUNT(*) AS n FROM chicago_crime GROUP BY month")
        if not months.empty:
            top = months.loc[months["n"].idxmax()]
            low = months.loc[months["n"].idxmin()]
            ctx["busiest_month"] = charts.MONTHS[int(top["month"]) - 1]
            ctx["busiest_month_n"] = int(top["n"])
            ctx["quietest_month"] = charts.MONTHS[int(low["month"]) - 1]
            ctx["quietest_month_n"] = int(low["n"])
        days = dbc.read_sql(
            "SELECT day_of_week, COUNT(*) AS n FROM chicago_crime GROUP BY day_of_week")
        if not days.empty:
            ctx["busiest_day"] = days.loc[days["n"].idxmax(), "day_of_week"]
            ctx["quietest_day"] = days.loc[days["n"].idxmin(), "day_of_week"]
    except Exception:
        app.logger.error("exploration_tab failed:\n%s", traceback.format_exc())

    return render_template("tab3_exploration.html", tab="exploration",
                           stats=headline_stats(), **ctx)


@app.route("/statistics")
def statistics_tab():
    ctx = {}
    try:
        hourly = dbc.read_sql("SELECT * FROM vw_crime_hourly ORDER BY hour")
        if not hourly.empty:
            ctx["peak_hour"] = int(hourly.loc[hourly["total_crimes"].idxmax(), "hour"])
            ctx["peak_hour_n"] = int(hourly["total_crimes"].max())
            ctx["quiet_hour"] = int(hourly.loc[hourly["total_crimes"].idxmin(), "hour"])
            ctx["quiet_hour_n"] = int(hourly["total_crimes"].min())
            ctx["hour_ratio"] = round(ctx["peak_hour_n"] / max(ctx["quiet_hour_n"], 1), 1)
            window = hourly[hourly["hour"].between(15, 20)]["total_crimes"].sum()
            ctx["surge_pct"] = round(window / hourly["total_crimes"].sum() * 100, 1)

        ctx["watches"] = dbc.read_sql("""
            SELECT CASE WHEN hour <= 5  THEN 'Night (00-05)'
                        WHEN hour <= 11 THEN 'Morning (06-11)'
                        WHEN hour <= 17 THEN 'Afternoon (12-17)'
                        ELSE 'Evening (18-23)' END          AS watch,
                   COUNT(*)                                 AS crimes,
                   ROUND(SUM(arrest) * 100.0 / COUNT(*), 1) AS arrest_rate
            FROM chicago_crime GROUP BY watch ORDER BY crimes DESC
        """).to_dict("records")

        areas = dbc.read_sql(
            "SELECT community_name, total_crimes FROM vw_crime_by_community")
        if len(areas) > 4:
            import numpy as np
            arr = areas["total_crimes"].to_numpy()
            q1, q3 = np.percentile(arr, [25, 75])
            fence = q3 + 1.5 * (q3 - q1)
            ctx["iqr"] = {"q1": round(float(q1), 1), "q3": round(float(q3), 1),
                          "iqr": round(float(q3 - q1), 1),
                          "fence": round(float(fence), 1),
                          "mean": round(float(arr.mean()), 1),
                          "median": round(float(np.median(arr)), 1),
                          "std": round(float(arr.std(ddof=1)), 1)}
            ctx["outliers"] = (areas[areas["total_crimes"] > fence]
                               .sort_values("total_crimes", ascending=False)
                               .to_dict("records"))

        corr = dbc.read_sql("""
            SELECT year, month, hour, arrest, domestic, latitude, longitude
            FROM chicago_crime
        """).corr(numeric_only=True)
        import numpy as np
        off_diag = corr.where(~np.eye(len(corr), dtype=bool)).abs()
        ctx["max_corr"] = round(float(off_diag.max().max()), 3)
        ctx["arrest_corr"] = (corr["arrest"].drop("arrest").round(3)
                              .sort_values(key=abs, ascending=False).to_dict())
    except Exception:
        app.logger.error("statistics_tab failed:\n%s", traceback.format_exc())

    return render_template("tab4_statistics.html", tab="statistics",
                           stats=headline_stats(), **ctx)


@app.route("/sql")
def sql_tab():
    ctx = {"queries": []}
    try:
        ctx["queries"] = [
            {
                "title": "Crime count per year",
                "sql": "SELECT year, COUNT(*) AS crime_count\n"
                       "FROM   chicago_crime\n"
                       "GROUP  BY year\n"
                       "ORDER  BY year;",
                "rows": dbc.read_sql(
                    "SELECT year, COUNT(*) AS crime_count FROM chicago_crime "
                    "GROUP BY year ORDER BY year").to_dict("records"),
            },
            {
                "title": "Top 5 crime types and their percentages",
                "sql": "SELECT i.primary_type,\n"
                       "       COUNT(*) AS crime_count,\n"
                       "       ROUND(COUNT(*) * 100.0 /\n"
                       "             (SELECT COUNT(*) FROM chicago_crime), 2) AS pct_of_total\n"
                       "FROM       chicago_crime c\n"
                       "INNER JOIN iucr i ON i.iucr_code = c.iucr_code\n"
                       "GROUP  BY  i.primary_type\n"
                       "ORDER  BY  crime_count DESC\n"
                       "LIMIT  5;",
                "rows": dbc.read_sql("""
                    SELECT i.primary_type,
                           COUNT(*) AS crime_count,
                           ROUND(COUNT(*) * 100.0 /
                                 (SELECT COUNT(*) FROM chicago_crime), 2) AS pct_of_total
                    FROM       chicago_crime c
                    INNER JOIN iucr i ON i.iucr_code = c.iucr_code
                    GROUP  BY  i.primary_type
                    ORDER  BY  crime_count DESC LIMIT 5
                """).to_dict("records"),
            },
            {
                "title": "Arrest count per year",
                "sql": "SELECT year,\n"
                       "       COUNT(*)               AS crimes,\n"
                       "       SUM(arrest)            AS arrests,\n"
                       "       COUNT(*) - SUM(arrest) AS no_arrest,\n"
                       "       ROUND(SUM(arrest) * 100.0 / COUNT(*), 2) AS arrest_rate\n"
                       "FROM   chicago_crime\n"
                       "GROUP  BY year\n"
                       "ORDER  BY year;",
                "rows": dbc.read_sql("""
                    SELECT year, COUNT(*) AS crimes, SUM(arrest) AS arrests,
                           COUNT(*) - SUM(arrest) AS no_arrest,
                           ROUND(SUM(arrest) * 100.0 / COUNT(*), 2) AS arrest_rate
                    FROM chicago_crime GROUP BY year ORDER BY year
                """).to_dict("records"),
            },
        ]
        ctx["views"] = dbc.read_sql(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
            if config.DB_BACKEND != "mysql" else
            "SELECT table_name AS name FROM information_schema.views "
            "WHERE table_schema = DATABASE()")["name"].tolist()
        ctx["summary_yearly"] = dbc.read_sql(
            "SELECT * FROM summary_crime_yearly ORDER BY year").to_dict("records")
        ctx["summary_category"] = dbc.read_sql(
            "SELECT * FROM summary_crime_by_category "
            "ORDER BY total_crimes DESC LIMIT 8").to_dict("records")
    except Exception:
        app.logger.error("sql_tab failed:\n%s", traceback.format_exc())

    return render_template("tab5_sql.html", tab="sql", stats=headline_stats(), **ctx)


# --------------------------------------------------------------------------- #
# Chart endpoint
# --------------------------------------------------------------------------- #
@app.route("/chart/<name>.png")
def chart(name):
    png = charts.render(name, DATA_VERSION["v"])
    return Response(png, mimetype="image/png",
                    headers={"Cache-Control": "no-cache"})


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404,
                           message="That page or record does not exist.",
                           stats=headline_stats(), tab=""), 404


@app.errorhandler(500)
def server_error(_):
    return render_template("error.html", code=500,
                           message="Something went wrong handling that request.",
                           stats=headline_stats(), tab=""), 500


if __name__ == "__main__":
    ensure_warehouse()
    print(f"\n  Chicago Crime Analytics  —  {dbc.backend_label()}")
    print("  http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
