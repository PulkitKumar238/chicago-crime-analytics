"""
USE CASE 2 — Exploratory Analysis & Visualization of Crime
==========================================================

Objective
    Analyse trends and patterns in the cleaned crime data using Pandas, NumPy,
    Matplotlib and Seaborn, and turn each chart into a statement the CPD can
    act on.

Run:
    python usecases/usecase2_eda_visualization.py

Produces:
    usecases/reports/UseCase2_EDA_and_Visualization.pdf
    usecases/figures/uc2_*.png
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

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]

REPORT = Report(
    number=2,
    title="Exploratory Analysis and Visualization",
    objective="Find the trends, categories, hotspots and arrest patterns in the data.",
    backend=dbc.backend_label(),
)
REPORT.env.update({"config": config, "dbc": dbc, "viz": viz, "Path": Path,
                   "MONTHS": MONTHS, "DAY_ORDER": DAY_ORDER})


def load_clean_frame():
    """Use the cleaned extract from Use Case 1, rebuilding it if it is absent."""
    if not config.CLEAN_CRIME_CSV.exists():
        from db.etl import clean_crime_frame, read_crime_csv
        clean, _ = clean_crime_frame(read_crime_csv())
        clean.to_csv(config.CLEAN_CRIME_CSV, index=False)


def main() -> Path:
    load_clean_frame()
    r = REPORT

    r.section("1. Loading the cleaned extract")
    r.text("""
        Use Case 1 wrote a cleaned, feature-engineered copy of the crime extract
        to <code>data/processed/chicago_crime_clean.csv</code>. Every figure in
        this report is built from that single file, so the numbers here and the
        numbers in the warehouse cannot disagree.
    """)
    r.step("""
        import numpy as np
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns

        df = pd.read_csv(config.CLEAN_CRIME_CSV, parse_dates=['date'],
                         dtype={'iucr_code': str, 'fbi_code': str})

        print(f"{len(df):,} crimes | {df['year'].min()}-{df['year'].max()} | "
              f"{df['primary_type'].nunique()} crime types | "
              f"{df['community_code'].nunique()} community areas")
    """)

    # ============================================================== 1. TREND
    r.section("2. Crime trend over the years")
    r.requirement("""
        Plot the total number of crimes per year and read the chart: is crime in
        Chicago rising or falling over the reporting period?
    """)
    r.step("""
        crimes_per_year = df.groupby('year').size()
        print(crimes_per_year.to_string())

        # Least-squares slope: the direction of travel in crimes per year.
        years = crimes_per_year.index.to_numpy()
        counts = crimes_per_year.to_numpy()
        slope, intercept = np.polyfit(years, counts, 1)

        first, last = counts[0], counts[-1]
        print(f"\\nMean per year   : {counts.mean():,.1f}")
        print(f"Std deviation   : {counts.std(ddof=1):,.1f} "
              f"({counts.std(ddof=1) / counts.mean() * 100:.1f}% of the mean)")
        print(f"Peak year       : {years[counts.argmax()]} ({counts.max()} crimes)")
        print(f"Lowest year     : {years[counts.argmin()]} ({counts.min()} crimes)")
        print(f"Change {years[0]}->{years[-1]} : {(last - first) / first * 100:+.1f}%")
        print(f"Trend slope     : {slope:+.2f} crimes per year")
    """)
    fig = _fig_trend(REPORT.env)
    r.figure(fig, "Total recorded crimes per year with the fitted linear trend.")
    r.insight("""
        <b>Neither rising nor falling — the series is flat.</b> The fitted trend
        is −0.37 crimes per year against a mean of 222, i.e. effectively zero,
        and the year-to-year spread is only 6.5% of the mean. 2016 is the
        busiest year (242) and 2017 the quietest (192), leaving the whole period
        4.8% lower than it started — a difference well inside normal
        year-to-year variation. For the CPD the operational reading is that
        total volume is stable, so resourcing decisions should be driven by
        <i>where</i> and <i>when</i> crime happens rather than by any expectation
        that the overall caseload is shrinking.
    """)

    # ========================================================== 2. CATEGORIES
    r.section("3. Top 10 crime categories")
    r.requirement("""
        Identify the top 10 crime categories by Primary Type, with both the
        count and the percentage each one represents.
    """)
    r.step("""
        counts = df['primary_type'].value_counts()
        top10 = (counts.head(10).rename('crimes').to_frame()
                   .assign(pct_of_all=lambda t: (t['crimes'] / len(df) * 100).round(2),
                           cumulative_pct=lambda t: t['pct_of_all'].cumsum().round(2)))
        print(top10.to_string())

        print(f"\\nThe top 10 categories cover {top10['pct_of_all'].sum():.1f}% "
              f"of all {len(df):,} recorded crimes.")
        print(f"The top 3 alone cover {top10['pct_of_all'].head(3).sum():.1f}%.")
    """)
    fig = _fig_categories(REPORT.env)
    r.figure(fig, "Top 10 crime categories by volume, with each category's share of the total.")
    r.insight("""
        Crime in this extract is heavily concentrated: <b>THEFT (20.8%),
        BATTERY (16.4%) and ASSAULT (9.75%) together account for 46.9% of every
        reported crime</b>, and the top ten of sixteen categories cover 91.8%. A
        prevention programme aimed at theft and battery alone would address
        37% of the CPD's total caseload.
    """)

    # ============================================================= 3. ARRESTS
    r.section("4. Arrests and crime outcomes")
    r.requirement("""
        What percentage of recorded crimes actually result in an arrest, and is
        that rate steady across the years?
    """)
    r.step("""
        # arrest is stored 0/1, so the mean IS the arrest rate.
        arrest_rate = df['arrest'].mean() * 100
        print(f"Overall arrest rate : {arrest_rate:.2f}%")
        print(f"Arrests             : {int(df['arrest'].sum()):,} of {len(df):,}")

        by_year = df.groupby('year')['arrest'].agg(
            crimes='size', arrests='sum', arrest_rate=lambda s: round(s.mean() * 100, 2))
        print()
        print(by_year.to_string())

        rates = by_year['arrest_rate']
        print(f"\\nSpread : {rates.min():.2f}% ({rates.idxmin()}) to "
              f"{rates.max():.2f}% ({rates.idxmax()}) — a {rates.max() - rates.min():.2f} pt range")
        print(f"Std dev: {rates.std(ddof=1):.2f} pts")
    """)
    r.step("""
        # Which categories does the CPD actually clear?
        by_type = (df.groupby('primary_type')['arrest']
                     .agg(crimes='size', arrests='sum',
                          arrest_rate=lambda s: round(s.mean() * 100, 1))
                     .sort_values('arrest_rate', ascending=False))
        print(by_type.to_string())
    """)
    fig = _fig_arrests(REPORT.env)
    r.figure(fig, "Arrest rate per year (left) and per crime category (right).")
    r.insight("""
        <b>29.8% of recorded crimes end in an arrest, and that rate is
        stable</b> — it moves between 25.6% (2016) and 33.8% (2018) with a
        standard deviation of only 2.6 points, which is ordinary sampling noise
        on ~220 crimes a year rather than a real change in effectiveness. The
        variation that matters is by category, not by year: <b>HOMICIDE clears
        at 80.0% and NARCOTICS at 56.7%, while BURGLARY clears at 13.0% and
        THEFT at 14.9%</b>. Offences either witnessed by an officer or worked as
        a major investigation are cleared at four times the rate of
        property crimes reported after the fact — the strongest argument in
        this report for putting more officers on the street in the right places.
    """)

    # ============================================================= 4. HEATMAP
    r.section("5. When does crime happen? Month vs day of week")
    r.requirement("""
        Build a Seaborn heatmap of crime frequency pivoted by Month against
        DayOfWeek.
    """)
    r.step("""
        pivot = (df.pivot_table(index='month', columns='day_of_week',
                                values='case_number', aggfunc='count')
                   .reindex(columns=DAY_ORDER))
        pivot.index = [MONTHS[m - 1] for m in pivot.index]

        print(pivot.to_string())
        print(f"\\nBusiest cell : {pivot.stack().idxmax()} with "
              f"{int(pivot.stack().max())} crimes")
        print(f"Quietest cell: {pivot.stack().idxmin()} with "
              f"{int(pivot.stack().min())} crimes")

        print("\\nTotals by month:")
        print(df['month'].value_counts().sort_index()
                .rename(index=lambda m: MONTHS[m - 1]).to_string())
        print("\\nTotals by day of week:")
        print(df['day_of_week'].value_counts().reindex(DAY_ORDER).to_string())
    """)
    fig = _fig_heatmap(REPORT.env)
    r.figure(fig, "Crime frequency by month and day of week; darker cells are busier.")
    r.insight("""
        The seasonal signal here is real but modest, and it is <b>not</b> the
        textbook summer peak. <b>October is the busiest month (190 crimes),
        followed by December (188) and July (184); April is the quietest
        (150)</b> — a 27% gap between best and worst. Across the week the load
        is flatter still, and it leans the opposite way to the usual
        expectation: <b>Thursday is the heaviest day (300) and Sunday the
        lightest (264)</b>, so weekends are not the pressure point in this
        extract. The busiest single cell is November Thursdays (34 crimes)
        against a quietest of April Mondays (15). The planning implication is
        that a modest autumn/winter uplift is worth rostering for, while
        day-of-week rebalancing would buy the CPD very little.
    """)

    # ========================================================== 5. COMMUNITIES
    r.section("6. Top community areas")
    r.requirement("""
        List the ten community areas with the highest crime counts and plot them
        on a bar chart.
    """)
    r.step("""
        community = pd.read_csv(config.COMMUNITY_CSV)

        top_areas = (df.groupby('community_code').size()
                       .rename('crimes').reset_index()
                       .merge(community[['community_code', 'community_name', 'population']],
                              on='community_code', how='left')
                       .sort_values('crimes', ascending=False)
                       .head(10).reset_index(drop=True))

        # Raw counts favour big areas, so normalise by population too.
        top_areas['crimes_per_10k'] = (top_areas['crimes'] /
                                       top_areas['population'] * 10000).round(2)
        top_areas['pct_of_all'] = (top_areas['crimes'] / len(df) * 100).round(2)

        print(top_areas[['community_code', 'community_name', 'population',
                         'crimes', 'pct_of_all', 'crimes_per_10k']].to_string(index=False))

        print(f"\\nThese 10 of 77 community areas carry "
              f"{top_areas['pct_of_all'].sum():.1f}% of all crime.")
    """)
    fig = _fig_communities(REPORT.env)
    r.figure(fig, "Top 10 community areas by crime volume (left) and by crimes per 10,000 residents (right).")
    r.insight("""
        The ten worst community areas of 77 carry 16.9% of all recorded
        crime — but the two rankings tell different stories. Garfield Ridge
        tops the volume ranking with 40 crimes yet only 11.0 per 10,000
        residents, while <b>Oakland records 32 crimes against a population of
        5,918 — 54.1 per 10,000, five times Garfield Ridge's rate</b>.
        Ranking by raw volume points at large, populous areas; ranking per
        10,000 residents promotes small areas whose residents face a far higher
        individual risk. Patrol allocation should follow the volume ranking (that is
        where the calls are), while prevention and community programmes should
        follow the per-capita ranking (that is where residents are most exposed).
    """)

    # ============================================================== ANSWERS
    r.section("7. Answers to the Use Case 2 questions")
    r.step("""
        top_type = df['primary_type'].value_counts()
        busiest_month = df['month'].value_counts().idxmax()
        month_counts = df['month'].value_counts().sort_index()
        yearly_rates = df.groupby('year')['arrest'].mean() * 100

        print("Q1. Which crime category is most frequent?")
        print(f"    {top_type.index[0]} — {top_type.iloc[0]:,} crimes "
              f"({top_type.iloc[0] / len(df) * 100:.2f}% of all reports)\\n")

        print("Q2. Is the arrest rate consistent across different years?")
        print(f"    Yes. Overall {df['arrest'].mean() * 100:.2f}%; yearly rates run "
              f"{yearly_rates.min():.2f}%-{yearly_rates.max():.2f}% "
              f"(std dev {yearly_rates.std(ddof=1):.2f} pts).\\n")

        print("Q3. Which month has the highest crime frequency?")
        print(f"    {MONTHS[busiest_month - 1]} — {month_counts[busiest_month]:,} crimes; "
              f"quietest is {MONTHS[month_counts.idxmin() - 1]} "
              f"({month_counts.min():,}), a {month_counts.max() / month_counts.min() - 1:+.0%} gap.")
    """)
    r.insight("""
        Three findings for the command team. <b>THEFT is the single most common
        crime</b> at one in five reports. <b>The arrest rate is consistent</b>
        at roughly 30% every year, so any improvement has to come from changing
        tactics rather than waiting for the trend. <b>October is the peak
        month</b>, 27% above April, with December close behind — the CPD's
        surge window is autumn into winter, not the summer that conventional
        wisdom would suggest.
    """)

    out = config.REPORTS_DIR / "UseCase2_EDA_and_Visualization.pdf"
    r.build(out)
    return out


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _fig_trend(env) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np

    s = env["crimes_per_year"]
    years, counts = s.index.to_numpy(), s.to_numpy()
    slope, intercept = np.polyfit(years, counts, 1)

    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.fill_between(years, counts, alpha=0.12, color=viz.ACCENT)
    ax.plot(years, counts, marker="o", linewidth=2.6, color=viz.ACCENT,
            markersize=8, markerfacecolor="white", markeredgewidth=2.4,
            label="Recorded crimes", zorder=3)
    ax.plot(years, slope * years + intercept, "--", color=viz.WARM, linewidth=1.8,
            label=f"Trend: {slope:+.1f} crimes/year")
    ax.axhline(counts.mean(), color="#8FA9C2", linewidth=1, linestyle=":",
               label=f"Mean {counts.mean():.0f}")
    for x, y in zip(years, counts):
        ax.annotate(f"{y}", (x, y), textcoords="offset points", xytext=(0, 11),
                    ha="center", fontsize=8.5, color=viz.NAVY, fontweight="bold")
    ax.set_xticks(years)
    ax.set_xlabel("Year")
    ax.set_ylabel("Number of crimes")
    ax.set_ylim(counts.min() * 0.88, counts.max() * 1.10)
    ax.set_title("Chicago crime volume is flat, not falling (2015–2023)")
    ax.legend(loc="lower left", ncol=3, fontsize=8.5)
    ax.grid(axis="x", visible=False)
    return viz.save(fig, "uc2_trend_by_year")


def _fig_categories(env) -> Path:
    import matplotlib.pyplot as plt

    top10 = env["top10"]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6),
                             gridspec_kw={"width_ratios": [1.35, 1]})

    labels = top10.index[::-1]
    values = top10["crimes"].to_numpy()[::-1]
    pcts = top10["pct_of_all"].to_numpy()[::-1]
    colors = [viz.WARM if i >= len(values) - 3 else viz.ACCENT for i in range(len(values))]
    bars = axes[0].barh(labels, values, color=colors, height=0.68)
    for bar, v, p in zip(bars, values, pcts):
        axes[0].text(v + 5, bar.get_y() + bar.get_height() / 2,
                     f"{v:,}  ({p:.1f}%)", va="center", fontsize=8.4, color="#33475B")
    axes[0].set_xlim(0, values.max() * 1.24)
    axes[0].set_xlabel("Number of crimes")
    axes[0].set_title("Top 10 categories by volume")
    axes[0].grid(axis="y", visible=False)

    cum = top10["cumulative_pct"].to_numpy()
    axes[1].plot(range(1, 11), cum, marker="o", color=viz.NAVY, linewidth=2.2,
                 markerfacecolor="white", markeredgewidth=2)
    axes[1].fill_between(range(1, 11), cum, alpha=0.10, color=viz.NAVY)
    axes[1].axhline(80, color=viz.WARM, linestyle="--", linewidth=1.4)
    axes[1].text(1.1, 81.5, "80% of all crime", color=viz.WARM, fontsize=8.5,
                 fontweight="bold")
    axes[1].set_xticks(range(1, 11))
    axes[1].set_xlabel("Number of categories included")
    axes[1].set_ylabel("Cumulative share (%)")
    axes[1].set_ylim(0, 105)
    axes[1].set_title("Concentration: few categories, most of the crime")
    axes[1].grid(axis="x", visible=False)

    fig.tight_layout()
    return viz.save(fig, "uc2_top_categories")


def _fig_arrests(env) -> Path:
    import matplotlib.pyplot as plt

    by_year, by_type = env["by_year"], env["by_type"]
    overall = env["arrest_rate"]

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4),
                             gridspec_kw={"width_ratios": [1, 1.15]})

    yrs = by_year.index.to_numpy()
    rates = by_year["arrest_rate"].to_numpy()
    bars = axes[0].bar(yrs, rates, color=viz.ACCENT, width=0.66)
    axes[0].axhline(overall, color=viz.WARM, linestyle="--", linewidth=1.6,
                    label=f"Overall {overall:.1f}%")
    axes[0].bar_label(bars, fmt="%.1f", padding=3, fontsize=8, color="#33475B")
    axes[0].set_xticks(yrs)
    axes[0].set_ylim(0, max(rates) * 1.28)
    axes[0].set_ylabel("Arrest rate (%)")
    axes[0].set_title("Arrest rate holds steady near 30%")
    axes[0].legend(fontsize=8.5)
    axes[0].grid(axis="x", visible=False)

    t = by_type.sort_values("arrest_rate")
    cols = [viz.WARM if v < overall else viz.ACCENT for v in t["arrest_rate"]]
    b2 = axes[1].barh(t.index, t["arrest_rate"], color=cols, height=0.7)
    axes[1].axvline(overall, color=viz.NAVY, linestyle="--", linewidth=1.4)
    axes[1].bar_label(b2, fmt="%.0f%%", padding=3, fontsize=7.6, color="#33475B")
    axes[1].set_xlim(0, t["arrest_rate"].max() * 1.20)
    axes[1].set_xlabel("Arrest rate (%)")
    axes[1].set_title("Clearance varies hugely by crime type")
    axes[1].tick_params(axis="y", labelsize=7.6)
    axes[1].grid(axis="y", visible=False)

    fig.tight_layout()
    return viz.save(fig, "uc2_arrest_rates")


def _fig_heatmap(env) -> Path:
    import matplotlib.pyplot as plt
    import seaborn as sns

    pivot = env["pivot"]
    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    sns.heatmap(pivot, annot=True, fmt=".0f", cmap=viz.SEQUENTIAL, linewidths=1.2,
                linecolor="white", cbar_kws={"label": "Crimes"}, ax=ax,
                annot_kws={"fontsize": 8.5})
    ax.set_title("Crime frequency by month and day of week")
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticklabels([t.get_text()[:3] for t in ax.get_xticklabels()], rotation=0)
    ax.tick_params(axis="y", rotation=0)
    return viz.save(fig, "uc2_month_day_heatmap")


def _fig_communities(env) -> Path:
    import matplotlib.pyplot as plt
    import pandas as pd

    df, community = env["df"], env["community"]
    top_areas = env["top_areas"]

    per_capita = (df.groupby("community_code").size().rename("crimes").reset_index()
                  .merge(community[["community_code", "community_name", "population"]],
                         on="community_code", how="left"))
    per_capita = per_capita[per_capita["crimes"] >= 10]
    per_capita["per_10k"] = per_capita["crimes"] / per_capita["population"] * 10000
    per_capita = per_capita.sort_values("per_10k", ascending=False).head(10)

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.8))

    t = top_areas.iloc[::-1]
    b1 = axes[0].barh(t["community_name"], t["crimes"], color=viz.ACCENT, height=0.68)
    axes[0].bar_label(b1, fmt="%d", padding=3, fontsize=8, color="#33475B")
    axes[0].set_xlim(0, t["crimes"].max() * 1.18)
    axes[0].set_xlabel("Number of crimes")
    axes[0].set_title("Top 10 by crime volume — where the calls are")
    axes[0].grid(axis="y", visible=False)

    p = per_capita.iloc[::-1]
    b2 = axes[1].barh(p["community_name"], p["per_10k"], color=viz.WARM, height=0.68)
    axes[1].bar_label(b2, fmt="%.1f", padding=3, fontsize=8, color="#33475B")
    axes[1].set_xlim(0, p["per_10k"].max() * 1.18)
    axes[1].set_xlabel("Crimes per 10,000 residents")
    axes[1].set_title("Top 10 per capita — where residents are most exposed")
    axes[1].grid(axis="y", visible=False)

    for a in axes:
        a.tick_params(axis="y", labelsize=8)
    fig.tight_layout()
    return viz.save(fig, "uc2_top_communities")


if __name__ == "__main__":
    path = main()
    print(f"\n[Use Case 2] report written to {path}")
