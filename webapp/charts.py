"""
Chart generation for the web application.

Every chart is rendered from the warehouse at request time and returned as PNG
bytes, so the dashboards always reflect whatever the CRUD screen has just done
to the data. Results are memoised against a data-version counter that the app
bumps on every write.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import connection as dbc  # noqa: E402
from usecases import viz  # noqa: E402

viz.setup_style()

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]

_CACHE: dict[tuple[str, int], bytes] = {}


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _empty(message: str) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12,
            color=viz.NAVY)
    ax.axis("off")
    return _png(fig)


def render(name: str, version: int = 0) -> bytes:
    """Return PNG bytes for a named chart, memoised on the data version."""
    key = (name, version)
    if key in _CACHE:
        return _CACHE[key]
    fn = CHARTS.get(name)
    if fn is None:
        return _empty(f"Unknown chart: {name}")
    try:
        png = fn()
    except Exception as exc:  # a broken chart must not take the page down
        png = _empty(f"Chart unavailable\n{type(exc).__name__}: {exc}")
    if len(_CACHE) > 120:
        _CACHE.clear()
    _CACHE[key] = png
    return png


def clear_cache() -> None:
    _CACHE.clear()


# --------------------------------------------------------------------------- #
# Tab 2 — Use Case 1: ingestion and data quality
# --------------------------------------------------------------------------- #
def chart_completeness() -> bytes:
    cols = ["location_desc", "latitude", "longitude", "x_coordinate",
            "y_coordinate", "ward_no", "community_code", "iucr_code",
            "district_code", "beat_num"]
    total = dbc.read_sql("SELECT COUNT(*) AS n FROM chicago_crime")["n"].iloc[0]
    if not total:
        return _empty("No crime records loaded yet.")
    sel = ", ".join(f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS {c}" for c in cols)
    row = dbc.read_sql(f"SELECT {sel} FROM chicago_crime").iloc[0]
    pct = (row.astype(float) / total * 100).sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(pct.index[::-1], pct.values[::-1], color=viz.ACCENT, height=0.62)
    ax.axvline(50, color=viz.WARM, linestyle="--", linewidth=1.4)
    ax.text(50.8, -0.45, "50% drop threshold", color=viz.WARM, fontsize=8.5,
            fontweight="bold")
    ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8, color="#33475B")
    ax.set_xlim(0, max(55, pct.max() * 1.3))
    ax.set_xlabel("Missing values (%)")
    ax.set_title("Field completeness across the warehouse")
    ax.grid(axis="y", visible=False)
    return _png(fig)


def chart_records_by_source() -> bytes:
    d = dbc.read_sql("""
        SELECT year, COUNT(*) AS crimes,
               SUM(CASE WHEN latitude IS NULL THEN 1 ELSE 0 END) AS no_geo
        FROM chicago_crime GROUP BY year ORDER BY year
    """)
    if d.empty:
        return _empty("No crime records loaded yet.")
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(d["year"], d["crimes"], color=viz.ACCENT, width=0.62, label="Geocoded")
    ax.bar(d["year"], d["no_geo"], color=viz.WARM, width=0.62, label="Missing coordinates")
    ax.set_xticks(d["year"])
    ax.set_xlabel("Year")
    ax.set_ylabel("Records")
    ax.set_title("Records loaded per year, and how many lack coordinates")
    ax.legend(fontsize=8.5)
    ax.grid(axis="x", visible=False)
    return _png(fig)


def chart_dimension_sizes() -> bytes:
    tables = ["chicago_crime", "iucr", "city_community", "district_ps_info",
              "police_beat_info", "ward_office"]
    counts = {}
    for t in tables:
        try:
            counts[t] = int(dbc.read_sql(f"SELECT COUNT(*) AS n FROM {t}")["n"].iloc[0])
        except Exception:
            counts[t] = 0
    s = pd.Series(counts).sort_values()

    fig, ax = plt.subplots(figsize=(9, 3.6))
    colors = [viz.NAVY if k == "chicago_crime" else viz.ACCENT for k in s.index]
    bars = ax.barh(s.index, s.values, color=colors, height=0.6)
    ax.bar_label(bars, fmt="%d", padding=4, fontsize=8.5, color="#33475B")
    ax.set_xscale("log")
    ax.set_xlim(1, s.max() * 3)
    ax.set_xlabel("Rows (log scale)")
    ax.set_title("Warehouse table sizes — one fact table, five dimensions")
    ax.grid(axis="y", visible=False)
    return _png(fig)


# --------------------------------------------------------------------------- #
# Tab 3 — Use Case 2: exploratory analysis
# --------------------------------------------------------------------------- #
def chart_trend() -> bytes:
    d = dbc.read_sql("SELECT year, total_crimes FROM vw_crime_yearly ORDER BY year")
    if len(d) < 2:
        return _empty("Not enough years of data to plot a trend.")
    x, y = d["year"].to_numpy(), d["total_crimes"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)

    fig, ax = plt.subplots(figsize=(9.5, 4))
    ax.fill_between(x, y, alpha=0.12, color=viz.ACCENT)
    ax.plot(x, y, marker="o", linewidth=2.6, color=viz.ACCENT, markersize=8,
            markerfacecolor="white", markeredgewidth=2.4, label="Recorded crimes")
    ax.plot(x, slope * x + intercept, "--", color=viz.WARM, linewidth=1.8,
            label=f"Trend {slope:+.1f}/yr")
    for xi, yi in zip(x, y):
        ax.annotate(f"{yi}", (xi, yi), textcoords="offset points", xytext=(0, 11),
                    ha="center", fontsize=8.5, color=viz.NAVY, fontweight="bold")
    ax.set_xticks(x)
    ax.set_ylim(y.min() * 0.86, y.max() * 1.12)
    ax.set_xlabel("Year")
    ax.set_ylabel("Number of crimes")
    ax.set_title("Total recorded crimes per year")
    ax.legend(fontsize=8.5, loc="lower left", ncol=2)
    ax.grid(axis="x", visible=False)
    return _png(fig)


def chart_top_categories() -> bytes:
    d = dbc.read_sql("""
        SELECT primary_type, total_crimes, pct_of_total
        FROM vw_crime_by_category ORDER BY total_crimes DESC LIMIT 10
    """)
    if d.empty:
        return _empty("No categories to show.")
    t = d.iloc[::-1]
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    bars = ax.barh(t["primary_type"], t["total_crimes"], color=viz.ACCENT, height=0.68)
    for bar, n, p in zip(bars, t["total_crimes"], t["pct_of_total"]):
        ax.text(n + t["total_crimes"].max() * 0.015,
                bar.get_y() + bar.get_height() / 2, f"{n:,}  ({p}%)",
                va="center", fontsize=8.4, color="#33475B")
    ax.set_xlim(0, t["total_crimes"].max() * 1.26)
    ax.set_xlabel("Number of crimes")
    ax.set_title("Top 10 crime categories")
    ax.tick_params(axis="y", labelsize=8.5)
    ax.grid(axis="y", visible=False)
    return _png(fig)


def chart_arrest_by_year() -> bytes:
    d = dbc.read_sql("SELECT year, arrest_rate FROM vw_crime_yearly ORDER BY year")
    if d.empty:
        return _empty("No arrest data.")
    overall = dbc.read_sql(
        "SELECT ROUND(SUM(arrest)*100.0/COUNT(*),2) AS r FROM chicago_crime")["r"].iloc[0]
    fig, ax = plt.subplots(figsize=(9.5, 3.8))
    bars = ax.bar(d["year"], d["arrest_rate"], color=viz.ACCENT, width=0.64)
    ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8, color="#33475B")
    ax.axhline(float(overall), color=viz.WARM, linestyle="--", linewidth=1.6,
               label=f"Overall {overall}%")
    ax.set_xticks(d["year"])
    ax.set_ylim(0, d["arrest_rate"].max() * 1.3)
    ax.set_xlabel("Year")
    ax.set_ylabel("Arrest rate (%)")
    ax.set_title("Arrest rate by year")
    ax.legend(fontsize=8.5)
    ax.grid(axis="x", visible=False)
    return _png(fig)


def chart_month_day_heatmap() -> bytes:
    d = dbc.read_sql("""
        SELECT month, day_of_week, COUNT(*) AS crimes
        FROM chicago_crime GROUP BY month, day_of_week
    """)
    if d.empty:
        return _empty("No data for the heatmap.")
    pivot = (d.pivot(index="month", columns="day_of_week", values="crimes")
              .reindex(columns=DAY_ORDER).fillna(0))
    pivot.index = [MONTHS[int(m) - 1] for m in pivot.index]

    fig, ax = plt.subplots(figsize=(8.6, 5))
    sns.heatmap(pivot, annot=True, fmt=".0f", cmap=viz.SEQUENTIAL, linewidths=1.2,
                linecolor="white", cbar_kws={"label": "Crimes"}, ax=ax,
                annot_kws={"fontsize": 8.5})
    ax.set_title("Crime frequency by month and day of week")
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticklabels([t.get_text()[:3] for t in ax.get_xticklabels()], rotation=0)
    ax.tick_params(axis="y", rotation=0)
    return _png(fig)


def chart_top_communities() -> bytes:
    d = dbc.read_sql("""
        SELECT community_name, total_crimes, crimes_per_10k
        FROM vw_crime_by_community ORDER BY total_crimes DESC LIMIT 10
    """)
    if d.empty:
        return _empty("No community data.")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    t = d.iloc[::-1]
    b1 = axes[0].barh(t["community_name"], t["total_crimes"], color=viz.ACCENT, height=0.66)
    axes[0].bar_label(b1, fmt="%d", padding=3, fontsize=8, color="#33475B")
    axes[0].set_xlim(0, t["total_crimes"].max() * 1.18)
    axes[0].set_xlabel("Number of crimes")
    axes[0].set_title("Top 10 areas by crime volume")

    p = dbc.read_sql("""
        SELECT community_name, crimes_per_10k FROM vw_crime_by_community
        WHERE total_crimes >= 10 ORDER BY crimes_per_10k DESC LIMIT 10
    """).iloc[::-1]
    b2 = axes[1].barh(p["community_name"], p["crimes_per_10k"], color=viz.WARM, height=0.66)
    axes[1].bar_label(b2, fmt="%.1f", padding=3, fontsize=8, color="#33475B")
    axes[1].set_xlim(0, p["crimes_per_10k"].max() * 1.18)
    axes[1].set_xlabel("Crimes per 10,000 residents")
    axes[1].set_title("Top 10 areas per capita")

    for a in axes:
        a.tick_params(axis="y", labelsize=8)
        a.grid(axis="y", visible=False)
    fig.tight_layout()
    return _png(fig)


# --------------------------------------------------------------------------- #
# Tab 4 — Use Case 3: statistical insights
# --------------------------------------------------------------------------- #
def chart_hourly() -> bytes:
    d = dbc.read_sql("SELECT hour, total_crimes FROM vw_crime_hourly ORDER BY hour")
    if d.empty:
        return _empty("No hourly data.")
    h, v = d["hour"].to_numpy(), d["total_crimes"].to_numpy()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.fill_between(h, v, alpha=0.14, color=viz.ACCENT)
    ax.plot(h, v, marker="o", linewidth=2.4, color=viz.ACCENT, markersize=5,
            markerfacecolor="white", markeredgewidth=1.6)
    ax.axvspan(14.6, 21.4, color=viz.WARM, alpha=0.09)
    ax.text(18, v.max() * 1.06, "15:00–21:00 surge window", ha="center",
            fontsize=9, color=viz.WARM, fontweight="bold")
    ax.set_xticks(range(0, 24, 2))
    ax.set_ylim(0, v.max() * 1.2)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Number of crimes")
    ax.set_title("Crime intensity across the 24-hour clock")
    ax.grid(axis="x", visible=False)
    return _png(fig)


def chart_outliers() -> bytes:
    d = dbc.read_sql("""
        SELECT community_name, total_crimes FROM vw_crime_by_community
    """)
    if len(d) < 5:
        return _empty("Not enough community areas for an outlier analysis.")
    counts = d["total_crimes"].to_numpy()
    q1, q3 = np.percentile(counts, [25, 75])
    upper = q3 + 1.5 * (q3 - q1)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2),
                             gridspec_kw={"width_ratios": [1, 1.3]})
    bp = axes[0].boxplot(counts, widths=0.42, patch_artist=True,
                         flierprops=dict(marker="o", markerfacecolor=viz.WARM,
                                         markeredgecolor=viz.WARM, markersize=7))
    bp["boxes"][0].set(facecolor="#C7DCEA", edgecolor=viz.ACCENT, linewidth=1.6)
    for part in ("whiskers", "caps"):
        for item in bp[part]:
            item.set(color=viz.ACCENT, linewidth=1.4)
    bp["medians"][0].set(color=viz.NAVY, linewidth=2.2)
    for _, row in d[d["total_crimes"] > upper].iterrows():
        axes[0].annotate(f"  {row['community_name']} ({row['total_crimes']})",
                         (1, row["total_crimes"]), fontsize=8.5, color=viz.WARM,
                         fontweight="bold", va="center")
    axes[0].set_xticks([])
    axes[0].set_ylabel("Crimes per community area")
    axes[0].set_title("Box plot with IQR outliers")

    axes[1].hist(counts, bins=14, color=viz.ACCENT, edgecolor="white")
    axes[1].axvline(upper, color=viz.WARM, linestyle="--", linewidth=1.8,
                    label=f"Upper fence {upper:.1f}")
    axes[1].axvline(counts.mean(), color=viz.NAVY, linestyle=":", linewidth=1.6,
                    label=f"Mean {counts.mean():.1f}")
    axes[1].set_xlabel("Crimes per community area")
    axes[1].set_ylabel("Number of areas")
    axes[1].set_title("Distribution across community areas")
    axes[1].legend(fontsize=8.5)
    axes[1].grid(axis="x", visible=False)
    fig.tight_layout()
    return _png(fig)


def chart_correlation() -> bytes:
    d = dbc.read_sql("""
        SELECT year, month, hour, arrest, domestic, latitude, longitude,
               community_code, district_code
        FROM chicago_crime
    """)
    if len(d) < 10:
        return _empty("Not enough records for a correlation matrix.")
    corr = d.corr(numeric_only=True)
    fig, ax = plt.subplots(figsize=(7.6, 6))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap=viz.DIVERGING,
                center=0, vmin=-0.25, vmax=0.25, linewidths=1.1, linecolor="white",
                square=True, cbar_kws={"label": "Pearson r", "shrink": 0.8}, ax=ax,
                annot_kws={"fontsize": 7.4})
    ax.set_title("Correlation matrix (scale capped at ±0.25)", fontsize=11.5)
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.tick_params(axis="y", rotation=0, labelsize=8)
    for lbl in ax.get_xticklabels():
        lbl.set_ha("right")
    return _png(fig)


def chart_signal_strength() -> bytes:
    dims = {
        "Hour of day": "SELECT COUNT(*) AS n FROM chicago_crime GROUP BY hour",
        "Community area": "SELECT COUNT(*) AS n FROM chicago_crime GROUP BY community_code",
        "Month": "SELECT COUNT(*) AS n FROM chicago_crime GROUP BY month",
        "Police district": "SELECT COUNT(*) AS n FROM chicago_crime GROUP BY district_code",
        "Year": "SELECT COUNT(*) AS n FROM chicago_crime GROUP BY year",
        "Day of week": "SELECT COUNT(*) AS n FROM chicago_crime GROUP BY day_of_week",
    }
    rows = []
    for label, q in dims.items():
        arr = dbc.read_sql(q)["n"].to_numpy()
        if len(arr) > 1 and arr.mean():
            rows.append({"dimension": label,
                         "cv": arr.std(ddof=1) / arr.mean() * 100,
                         "ratio": arr.max() / max(arr.min(), 1)})
    if not rows:
        return _empty("Not enough data.")
    s = pd.DataFrame(rows).sort_values("cv")

    fig, ax = plt.subplots(figsize=(9.5, 3.8))
    colors = [viz.WARM if v == s["cv"].max() else viz.ACCENT for v in s["cv"]]
    bars = ax.barh(s["dimension"], s["cv"], color=colors, height=0.6)
    for bar, cv, ratio in zip(bars, s["cv"], s["ratio"]):
        ax.text(cv + s["cv"].max() * 0.02, bar.get_y() + bar.get_height() / 2,
                f"{cv:.1f}%   (max/min {ratio:.1f}x)", va="center", fontsize=8.4,
                color="#33475B")
    ax.set_xlim(0, s["cv"].max() * 1.45)
    ax.set_xlabel("Coefficient of variation in crime counts (%)")
    ax.set_title("Which dimension actually moves crime volume")
    ax.grid(axis="y", visible=False)
    return _png(fig)


# --------------------------------------------------------------------------- #
# Tab 5 — Use Case 4: SQL reporting
# --------------------------------------------------------------------------- #
def chart_sql_yearly() -> bytes:
    d = dbc.read_sql("""
        SELECT year, total_crimes, arrests, arrest_rate
        FROM vw_crime_yearly ORDER BY year
    """)
    if d.empty:
        return _empty("No data in vw_crime_yearly.")
    x = np.arange(len(d))
    w = 0.42
    fig, ax = plt.subplots(figsize=(10, 4.2))
    b1 = ax.bar(x - w / 2, d["total_crimes"], w, label="Total crimes", color=viz.ACCENT)
    b2 = ax.bar(x + w / 2, d["arrests"], w, label="Arrests", color=viz.NAVY)
    ax.bar_label(b1, fmt="%d", padding=2, fontsize=7.6, color="#33475B")
    ax.bar_label(b2, fmt="%d", padding=2, fontsize=7.6, color="#33475B")
    ax2 = ax.twinx()
    ax2.plot(x, d["arrest_rate"], marker="o", color=viz.WARM, linewidth=2.2,
             markersize=6, markerfacecolor="white", markeredgewidth=2,
             label="Arrest rate (%)")
    ax2.set_ylim(0, d["arrest_rate"].max() * 2.1)
    ax2.set_ylabel("Arrest rate (%)", color=viz.WARM)
    ax2.tick_params(axis="y", colors=viz.WARM)
    ax2.grid(False)
    ax.set_xticks(x)
    ax.set_xticklabels(d["year"].astype(int))
    ax.set_ylabel("Count")
    ax.set_ylim(0, d["total_crimes"].max() * 1.25)
    ax.set_title("SELECT * FROM vw_crime_yearly")
    ax.grid(axis="x", visible=False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", ncol=3, fontsize=8.5)
    fig.tight_layout()
    return _png(fig)


def chart_sql_quadrant() -> bytes:
    c = dbc.read_sql("""
        SELECT primary_type, total_crimes, arrest_rate
        FROM vw_crime_by_category ORDER BY total_crimes DESC
    """)
    if len(c) < 3:
        return _empty("Not enough categories.")
    med_v, med_r = c["total_crimes"].median(), c["arrest_rate"].median()
    fig, ax = plt.subplots(figsize=(9.5, 5))
    ax.axvspan(med_v, c["total_crimes"].max() * 1.25, color=viz.WARM, alpha=0.06)
    ax.axhline(med_r, color="#8FA9C2", linestyle=":", linewidth=1.2)
    ax.axvline(med_v, color="#8FA9C2", linestyle=":", linewidth=1.2)
    for _, row in c.iterrows():
        priority = row["total_crimes"] > med_v and row["arrest_rate"] < med_r
        ax.scatter(row["total_crimes"], row["arrest_rate"], s=120,
                   color=viz.WARM if priority else viz.ACCENT,
                   edgecolor="white", linewidth=1.4, zorder=3)
        ax.annotate(row["primary_type"].title(),
                    (row["total_crimes"], row["arrest_rate"]),
                    textcoords="offset points", xytext=(7, 4), fontsize=7.4,
                    color=viz.NAVY if priority else "#5A6B7C")
    ax.text(c["total_crimes"].max() * 0.62, max(med_r * 0.3, 3),
            "PRIORITY QUADRANT\nhigh volume · low clearance", fontsize=9,
            color=viz.WARM, fontweight="bold", ha="center")
    ax.set_xlim(0, c["total_crimes"].max() * 1.25)
    ax.set_xlabel("Total crimes")
    ax.set_ylabel("Arrest rate (%)")
    ax.set_title("vw_crime_by_category — volume against clearance")
    return _png(fig)


def chart_sql_top_iucr() -> bytes:
    d = dbc.read_sql("""
        SELECT iucr_code, primary_type, description, index_code, total_crimes
        FROM vw_top_iucr ORDER BY total_crimes DESC LIMIT 12
    """)
    if d.empty:
        return _empty("No IUCR data.")
    d["label"] = d["iucr_code"] + "  " + d["description"].str.title().str[:28]
    t = d.iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    colors = [viz.WARM if i == "I" else viz.ACCENT for i in t["index_code"]]
    bars = ax.barh(t["label"], t["total_crimes"], color=colors, height=0.68)
    ax.bar_label(bars, fmt="%d", padding=3, fontsize=8, color="#33475B")
    ax.set_xlim(0, t["total_crimes"].max() * 1.16)
    ax.set_xlabel("Number of crimes")
    ax.set_title("Top IUCR offence codes  (orange = FBI Part I index crime)")
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", visible=False)
    return _png(fig)


CHARTS = {
    "completeness": chart_completeness,
    "records_by_source": chart_records_by_source,
    "dimension_sizes": chart_dimension_sizes,
    "trend": chart_trend,
    "top_categories": chart_top_categories,
    "arrest_by_year": chart_arrest_by_year,
    "month_day_heatmap": chart_month_day_heatmap,
    "top_communities": chart_top_communities,
    "hourly": chart_hourly,
    "outliers": chart_outliers,
    "correlation": chart_correlation,
    "signal_strength": chart_signal_strength,
    "sql_yearly": chart_sql_yearly,
    "sql_quadrant": chart_sql_quadrant,
    "sql_top_iucr": chart_sql_top_iucr,
}
