# Chicago Crime Data Analytics

An end-to-end Python data pipeline, analytics deliverable and web application built on the
Chicago Police Department crime extract — ingesting and cleaning the raw CSVs, warehousing
them in MySQL/SQLite, analysing them with Pandas and NumPy, and publishing the findings as
four PDF reports and a five-tab Flask dashboard.

---

## What is in here

| Deliverable | Location |
|---|---|
| **4 use-case scripts** | `usecases/usecase1…4_*.py` |
| **4 use-case PDF reports** | `usecases/reports/*.pdf` |
| **Web application (5 tabs)** | `webapp/` |
| Data pipeline / ETL | `db/etl.py` |
| Database schemas + views | `sql/` |
| Generated figures | `usecases/figures/` |

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run_all.py          # build the warehouse + generate all 4 PDF reports
python webapp/app.py       # start the dashboard at http://127.0.0.1:5000
```

`run_all.py` is idempotent — re-running it rebuilds the warehouse and regenerates every
report and figure from the raw CSVs.

---

## The database

The project runs on **MySQL** or **SQLite3**, selected by a single environment variable.
SQLite3 is the default so the project runs anywhere with no server setup, which is the
fallback the brief explicitly permits.

```bash
# SQLite3 (default) — writes to data/chicago_crime.db
python run_all.py

# MySQL
export DB_BACKEND=mysql
export MYSQL_USER=root MYSQL_PASSWORD=yourpassword
export MYSQL_HOST=localhost MYSQL_DATABASE=chicago_crime_dw
python run_all.py
```

`sql/schema_mysql.sql` and `sql/schema_sqlite.sql` are structurally identical; `sql/views.sql`
is portable SQL shared by both backends. `db/connection.py` exposes both a SQLAlchemy engine
(for bulk DataFrame writes) and a raw DB-API connector — PyMySQL or sqlite3 — for DDL, views
and hand-written SQL.

### Data model

A star schema: one fact table surrounded by five conformed dimensions.

```
chicago_crime (case_number PK, id UNIQUE)
    ├── iucr_code      → iucr             (primary_type, description, index_code)
    ├── beat_num       → police_beat_info (district, sector, beat)
    ├── district_code  → district_ps_info (station name, address, contacts)
    ├── community_code → city_community   (population, area, density)
    └── ward_no        → ward_office      (alderman, contacts) — FK not enforced, see below
```

`primary_type` and `description` are attributes of the **offence code**, not of an individual
crime, so they live once in the `iucr` dimension and are read back through the `vw_crime_full`
view. That keeps the fact table in third normal form.

**Views:** `vw_crime_full`, `vw_crime_yearly`, `vw_crime_by_category`, `vw_crime_by_community`,
`vw_crime_hourly`, `vw_top_iucr`.
**Summary tables:** `summary_crime_yearly`, `summary_crime_by_category`, `summary_crime_by_community`.

---

## Two things to know about the source data

**1. The supplied filenames did not match their contents.** Every file was identified by its
header row and re-mapped before any analysis was written:

| Supplied filename | Actual content | Rows |
|---|---|---|
| `chicago_crime_dataset.csv` | city community areas | 77 |
| `chicago_district_ps_info.csv` | **the master crime extract** | 2,000 |
| `chicago_police_beat_info.csv` | district police-station info | 22 |
| `chicago_ward_offices.csv` | police beat info | 198 |
| `iucr_codes.csv` | ward offices | 24 |

The corrected copies live in `data/raw/` under their true names.

**2. No genuine IUCR file was supplied**, so that dimension is reconstructed from the offence
attributes carried on each crime row (24 codes), with `index_code` derived from the FBI Part I
classification. It is written to `data/raw/iucr_codes.csv` by the ETL.

**On the unenforced ward foreign key:** the crime data references wards 1–50 but the supplied
ward-office file covers only wards 1–24, so a `ward_no` FK would reject ~49% of otherwise valid
records. Rejecting valid crime data to satisfy a reference-file gap would breach the brief's
requirement that nothing be discarded, so the gap is documented rather than deleted.

---

## The four use cases

Each script executes its own documented code, captures the real output, and renders a PDF that
states the requirement in plain English, shows the exact code that ran, and prints what it
produced. The code in the PDF *is* the code that produced the output — `Report.step()` executes
the source string it prints, so the two cannot drift apart.

| # | Script | Report |
|---|---|---|
| 1 | `usecase1_load_and_clean.py` | Load, profile, clean, engineer features, warehouse |
| 2 | `usecase2_eda_visualization.py` | Trends, categories, arrests, month/day heatmap, hotspots |
| 3 | `usecase3_statistical_insights.py` | Hourly intensity, IQR outliers, correlation |
| 4 | `usecase4_sql_reporting.py` | Summary tables, SQL queries, views, Pandas integration |

Run one on its own with `python usecases/usecase2_eda_visualization.py`.

### Headline findings

- **Volume is flat, not falling.** 2,000 crimes over 2015–2023, trend −0.37 crimes/year against
  a mean of 222 — inside normal year-to-year variation.
- **THEFT is the most common crime** at 20.8%; the top three categories are 46.9% of all crime
  and the top ten cover 91.8%.
- **29.8% of crimes end in an arrest**, and that rate is stable (std dev 2.6 points across nine
  years). Clearance varies enormously *by category* — 80.0% for homicide, 13.0% for burglary.
- **Time of day is the strongest signal in the data.** Crime swings 10.3× from a 05:00 trough
  (15) to an 18:00 peak (155); the 15:00–21:00 window carries 41% of the entire caseload.
  Hour-of-day varies 56.6% around its mean, against 8.7% for month and 5.2% for weekday.
- **There is no runaway geographic hotspot.** The IQR rule flags exactly one community area
  (Garfield Ridge, 40 crimes) past the 39.5 upper fence.
- **No numeric feature predicts an arrest** — the largest correlation anywhere in the matrix is
  0.076. Arrest outcome is driven by offence type, which is categorical.

---

## The web application

```bash
python webapp/app.py     # http://127.0.0.1:5000
```

| Tab | Contents |
|---|---|
| **1 · Crime Data** | CSV upload + full CRUD, search, filters, pagination — writes straight to the warehouse |
| **2 · Data Quality** | Use Case 1: completeness, cleaning rules, schema design |
| **3 · Exploration** | Use Case 2: trends, categories, arrest rates, heatmap, hotspots |
| **4 · Statistics** | Use Case 3: hourly intensity, IQR outliers, correlation |
| **5 · SQL Reports** | Use Case 4: queries, stored views, summary tables |

Tab 1 is fully live: uploads are cleaned with the Use Case 1 pipeline and merged by case number
(existing cases updated, new ones inserted, so re-uploading a corrected file never duplicates).
Records can be created, edited and deleted, and every change is validated against the IUCR,
district, beat and community dimensions before it is written. Charts on tabs 2–5 are rendered
from the database at request time, so an edit made on tab 1 shows up everywhere on the next load.

**Rebuild from source files** on tab 1 discards all edits and reloads from `data/raw/`.

---

## Project layout

```
.
├── config.py                  # paths + backend selection
├── run_all.py                 # build warehouse, generate all 4 reports
├── requirements.txt
├── data/
│   ├── raw/                   # the 5 source CSVs (correctly named) + derived iucr_codes.csv
│   └── processed/             # cleaned extract written by the pipeline
├── sql/
│   ├── schema_mysql.sql       # MySQL DDL (fact, dimensions, summary tables)
│   ├── schema_sqlite.sql      # structurally identical SQLite3 DDL
│   └── views.sql              # portable view definitions, shared by both backends
├── db/
│   ├── connection.py          # SQLAlchemy engine + raw DB-API connector
│   └── etl.py                 # extract, clean, feature-engineer, load
├── usecases/
│   ├── usecase1_load_and_clean.py
│   ├── usecase2_eda_visualization.py
│   ├── usecase3_statistical_insights.py
│   ├── usecase4_sql_reporting.py
│   ├── report_builder.py      # PDF engine (executes the code it documents)
│   ├── viz.py                 # shared chart styling
│   ├── reports/               # the 4 PDF deliverables
│   └── figures/               # generated PNGs
└── webapp/
    ├── app.py                 # Flask routes + CRUD
    ├── charts.py              # charts rendered from the warehouse
    ├── templates/             # 5 tabs + form + error page
    └── static/style.css
```

---

## Tech stack

Python 3 · Pandas · NumPy · Matplotlib · Seaborn · SQLAlchemy · PyMySQL · Flask · ReportLab ·
MySQL / SQLite3

Built for the Accenture Python Full Stack Program.
