"""
USE CASE 3 — Statistical Insights & Pattern Detection
=====================================================

Objective
    Go past descriptive counts: profile crime intensity through the day,
    isolate the community areas that are genuine statistical outliers, and test
    whether any numeric feature actually predicts an arrest.

Run:
    python usecases/usecase3_statistical_insights.py

Produces:
    usecases/reports/UseCase3_Statistical_Insights.pdf
    usecases/figures/uc3_*.png
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
    number=3,
    title="Statistical Insights and Pattern Detection",
    objective="Hour-of-day intensity, community-area outliers and feature correlation.",
    backend=dbc.backend_label(),
)
REPORT.env.update({"config": config, "dbc": dbc, "viz": viz, "Path": Path})


def main() -> Path:
    r = REPORT

    r.section("1. Setup")
    r.text("""
        This use case works from the same cleaned extract that Use Case 1
        produced. Where Use Case 2 asked <i>what</i> and <i>where</i>, this one
        asks <i>when</i>, <i>how unusual</i> and <i>how related</i> — the three
        questions that turn a crime count into a patrol decision.
    """)
    r.step("""
        import numpy as np
        import pandas as pd
        import matplotlib.pyplot as plt
        import seaborn as sns

        pd.set_option('display.width', 110)

        df = pd.read_csv(config.CLEAN_CRIME_CSV, parse_dates=['date'],
                         dtype={'iucr_code': str, 'fbi_code': str})
        community = pd.read_csv(config.COMMUNITY_CSV)

        print(f"{len(df):,} crimes | {df['community_code'].nunique()} community areas "
              f"| {df['year'].min()}-{df['year'].max()}")
    """)

    # ============================================================ 1. BY HOUR
    r.section("2. Crime intensity by time of day")
    r.requirement("""
        Derive the hour from the Date column, group the crimes by hour, and plot
        the resulting profile as a line chart across the 24-hour clock.
    """)
    r.step("""
        # The Hour feature was engineered in Use Case 1; recreated here so this
        # step stands on its own.
        df['Hour'] = df['date'].dt.hour
        crimes_by_hour = df.groupby('Hour').size()

        print(crimes_by_hour.to_string())

        peak, quiet = crimes_by_hour.idxmax(), crimes_by_hour.idxmin()
        print(f"\\nPeak hour   : {peak:02d}:00 with {crimes_by_hour.max()} crimes")
        print(f"Quietest    : {quiet:02d}:00 with {crimes_by_hour.min()} crimes")
        print(f"Peak/trough : {crimes_by_hour.max() / crimes_by_hour.min():.1f}x")
        print(f"Mean/hour   : {crimes_by_hour.mean():.1f}  "
              f"(std {crimes_by_hour.std(ddof=1):.1f})")
    """)
    r.step("""
        # Roll the 24 hours up into the four watches a shift roster works in.
        watches = pd.cut(df['Hour'], bins=[-1, 5, 11, 17, 23],
                         labels=['Night (00-05)', 'Morning (06-11)',
                                 'Afternoon (12-17)', 'Evening (18-23)'])

        watch_summary = (df.groupby(watches, observed=True)
                           .agg(crimes=('case_number', 'size'),
                                arrest_rate=('arrest', lambda s: round(s.mean() * 100, 1))))
        watch_summary['pct_of_all'] = (watch_summary['crimes'] / len(df) * 100).round(1)
        print(watch_summary.to_string())

        ev = watch_summary.loc['Evening (18-23)', 'crimes']
        ni = watch_summary.loc['Night (00-05)', 'crimes']
        print(f"\\nThe evening watch handles {ev / ni:.1f}x the volume of the night watch.")
    """)
    fig = _fig_hourly(REPORT.env)
    r.figure(fig, "Crimes per hour of day (left) and the same data rolled into four watches (right).")
    r.insight("""
        <b>This is the single strongest pattern in the entire dataset.</b> Crime
        climbs steadily from a 05:00 trough of 15 incidents to a 18:00 peak of
        155 — a <b>10.3× swing across the clock</b>, far larger than any
        year-on-year, monthly or day-of-week variation found in Use Case 2. The
        evening watch (18:00–23:59) absorbs 38% of all crime while the night
        watch (00:00–05:59) sees under 6%.
        <br/><br/>
        The operational recommendation follows directly: <b>weight patrol
        strength toward the 15:00–21:00 window</b>, six hours that carry 41.0%
        of the entire caseload; stretch it to 22:00 and seven of the day's
        twenty-four hours account for 47.3%. A roster that splits officers evenly across
        three eight-hour shifts is putting the same number of officers on the
        street at 04:00 as at 18:00, when the second sees ten times the work.
    """)

    # ======================================================== 2. OUTLIER AREAS
    r.section("3. Community-area outliers")
    r.requirement("""
        Aggregate crime counts by community area, use a box plot to reveal the
        outliers, then apply the IQR rule to list exactly which areas are
        statistically extreme.
    """)
    r.step("""
        area_counts = df.groupby('community_code').size().rename('crimes')

        # NumPy does the quartile arithmetic.
        counts = area_counts.to_numpy()
        q1, q3 = np.percentile(counts, [25, 75])
        iqr = q3 - q1
        upper_fence = q3 + 1.5 * iqr
        lower_fence = q1 - 1.5 * iqr

        print(f"Community areas : {len(counts)}")
        print(f"Mean / median   : {counts.mean():.1f} / {np.median(counts):.1f}")
        print(f"Std deviation   : {counts.std(ddof=1):.1f}")
        print(f"Range           : {counts.min()} to {counts.max()}")
        print()
        print(f"Q1 (25th pct)   : {q1:.1f}")
        print(f"Q3 (75th pct)   : {q3:.1f}")
        print(f"IQR             : {iqr:.1f}")
        print(f"Upper fence     : Q3 + 1.5*IQR = {upper_fence:.1f}")
        print(f"Lower fence     : Q1 - 1.5*IQR = {lower_fence:.1f}")
    """)
    r.step("""
        names = community.set_index('community_code')

        outliers = area_counts[(area_counts > upper_fence) | (area_counts < lower_fence)]
        report = (outliers.to_frame()
                          .join(names[['community_name', 'population']])
                          .assign(per_10k=lambda t: (t['crimes'] / t['population']
                                                     * 10000).round(2),
                                  side=lambda t: np.where(t['crimes'] > upper_fence,
                                                          'HIGH', 'LOW'))
                          .sort_values('crimes', ascending=False))

        print(f"IQR outliers found: {len(report)}")
        print(report.to_string())

        print("\\nClosest to the upper fence without crossing it:")
        near = area_counts[(area_counts <= upper_fence)].nlargest(5)
        print(near.to_frame().join(names[['community_name']]).to_string())
    """)
    fig = _fig_outliers(REPORT.env)
    r.figure(fig, "Distribution of crime counts across the 77 community areas. "
                  "The dot beyond the upper whisker is the single IQR outlier.")
    r.insight("""
        The 77 community areas are far more even than the raw top-ten table in
        Use Case 2 suggests. Counts sit in a tight band — mean 25.5, median 26,
        standard deviation 5.3 — and the IQR rule flags <b>exactly one extreme
        area: Garfield Ridge with 40 crimes</b>, just past the 39.5 upper fence.
        No area falls below the lower fence.
        <br/><br/>
        That is an important negative result: <b>this dataset does not contain
        a runaway crime hotspot at community-area level.</b> Crime is broadly
        distributed across the city, so a strategy of drawing a hard perimeter
        around two or three "worst" neighbourhoods would be built on noise
        rather than signal. The per-capita view from Use Case 2 — where Oakland
        runs at five times Garfield Ridge's rate per resident — remains the
        better basis for targeting prevention, because it corrects for how many
        people actually live in each area.
    """)

    # ====================================================== 3. CORRELATION
    r.section("4. Cross-correlation of numeric features")
    r.requirement("""
        Run Pandas .corr() across the numeric features (Year, Month, Arrest and
        so on) and visualise the correlation matrix as a heatmap.
    """)
    r.text("""
        One caution before the numbers. Several columns in this table are
        <i>numeric-looking but nominal</i>: <code>district_code</code>,
        <code>beat_num</code>, <code>ward_no</code> and
        <code>community_code</code> are labels that happen to be written as
        digits. District 22 is not "twice" district 11, so a Pearson
        correlation on them has no meaning. They are reported below for
        completeness because the brief asks for the full numeric matrix, but the
        interpretation that follows rests only on the genuinely quantitative
        features: year, month, hour, arrest and domestic.
    """)
    r.step("""
        numeric = df[['year', 'month', 'hour', 'arrest', 'domestic',
                      'latitude', 'longitude', 'community_code', 'district_code',
                      'beat_num', 'ward_no']]

        corr = numeric.corr(numeric_only=True)
        print(corr.round(2).to_string())
    """)
    r.step("""
        # Rank every distinct pair by absolute correlation strength.
        pairs = (corr.where(~np.eye(len(corr), dtype=bool))
                     .abs().unstack().dropna()
                     .sort_values(ascending=False).drop_duplicates())

        print("Strongest relationships anywhere in the matrix:")
        print(pairs.head(6).round(4).to_string())

        print("\\nWhat correlates with an arrest?")
        print(corr['arrest'].drop('arrest')
                  .sort_values(key=abs, ascending=False).round(4).to_string())

        print(f"\\nLargest absolute correlation in the whole matrix: {pairs.max():.3f}")
    """)
    fig = _fig_corr(REPORT.env)
    r.figure(fig, "Correlation matrix. The near-uniform pale field is the finding: "
                  "no numeric feature moves with any other.")
    r.insight("""
        <b>There is no meaningful linear relationship between any pair of
        numeric features — the largest absolute correlation in the entire
        matrix is 0.076.</b> In particular, whether a crime ends in an arrest is
        essentially uncorrelated with the year (r = 0.019), the month
        (r = −0.013), the hour of day (r = −0.008) or the location coordinates.
        <br/><br/>
        This is a genuinely useful result rather than a dead end. It says the
        arrest outcome is <b>not</b> driven by when or where a crime happens —
        it is driven by <i>what kind</i> of crime it is, which Use Case 2
        quantified precisely (80% clearance for homicide, 13% for burglary).
        Crime type is a categorical variable, so it cannot appear in a Pearson
        matrix at all, and that is exactly why the matrix looks empty. The
        practical consequence for the CPD: <b>a model built to predict arrest
        likelihood from time and place alone would fail</b>; any predictive work
        must be driven by offence type, and by the categorical context around
        it, rather than by these numeric columns.
    """)

    # ======================================================= 4. SYNTHESIS
    r.section("5. Where the signal actually is")
    r.step("""
        # Rank the dimensions by how much they actually move crime volume,
        # using the coefficient of variation as a like-for-like measure.
        def spread(series_counts, label):
            arr = series_counts.to_numpy()
            return {'dimension': label, 'levels': len(arr),
                    'min': int(arr.min()), 'max': int(arr.max()),
                    'max/min': round(arr.max() / arr.min(), 2),
                    'CV %': round(arr.std(ddof=1) / arr.mean() * 100, 1)}

        signal = pd.DataFrame([
            spread(df.groupby('Hour').size(), 'Hour of day'),
            spread(df.groupby('month').size(), 'Month'),
            spread(df.groupby('community_code').size(), 'Community area'),
            spread(df.groupby('district_code').size(), 'Police district'),
            spread(df.groupby('day_of_week').size(), 'Day of week'),
            spread(df.groupby('year').size(), 'Year'),
        ]).sort_values('CV %', ascending=False)

        print(signal.to_string(index=False))
    """)
    fig = _fig_signal(REPORT.env)
    r.figure(fig, "Which dimension actually moves crime volume, measured by coefficient of variation.")
    r.insight("""
        Ranking every dimension by how much it actually moves crime volume
        settles the resourcing argument. <b>Hour of day varies by 56.6% around
        its mean, while month varies by 8.7%, year by 6.5% and day of week by
        just 5.2%.</b> Time of day carries six times the signal of the month and
        eleven times that of the weekday. Community area (20.7%) is the
        strongest geographic dimension — nearly three times the spread of police
        district (7.4%), because district boundaries average several
        neighbourhoods together and flatten the contrast out.
        <br/><br/>
        <b>Recommendation to the CPD:</b> build the patrol model on the clock
        first and the map second. Shifting officers into the 15:00–21:00 window,
        weighted toward the higher-volume community areas, targets the only two
        dimensions in this data with a spread large enough to be worth acting
        on. Rostering by day of week, or waiting for a year-on-year trend to
        appear, chases variation that is statistically indistinguishable from
        noise.
    """)

    out = config.REPORTS_DIR / "UseCase3_Statistical_Insights.pdf"
    r.build(out)
    return out


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _fig_hourly(env) -> Path:
    import matplotlib.pyplot as plt

    by_hour = env["crimes_by_hour"]
    watch = env["watch_summary"]

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.4),
                             gridspec_kw={"width_ratios": [1.65, 1]})

    h, v = by_hour.index.to_numpy(), by_hour.to_numpy()
    axes[0].fill_between(h, v, alpha=0.14, color=viz.ACCENT)
    axes[0].plot(h, v, marker="o", linewidth=2.4, color=viz.ACCENT, markersize=5,
                 markerfacecolor="white", markeredgewidth=1.6)
    axes[0].axvspan(14.6, 21.4, color=viz.WARM, alpha=0.09)
    axes[0].text(18, v.max() * 1.03, "15:00–21:00 surge window · 41% of all crime", ha="center",
                 fontsize=8.5, color=viz.WARM, fontweight="bold")
    axes[0].annotate(f"peak {v.max()} @ 18:00", (h[v.argmax()], v.max()),
                     textcoords="offset points", xytext=(-6, -22), fontsize=8.5,
                     color=viz.NAVY, fontweight="bold",
                     arrowprops=dict(arrowstyle="->", color=viz.NAVY, lw=1))
    axes[0].annotate(f"trough {v.min()} @ 05:00", (h[v.argmin()], v.min()),
                     textcoords="offset points", xytext=(10, 16), fontsize=8.5,
                     color=viz.NAVY, fontweight="bold",
                     arrowprops=dict(arrowstyle="->", color=viz.NAVY, lw=1))
    axes[0].set_xticks(range(0, 24, 2))
    axes[0].set_xlabel("Hour of day")
    axes[0].set_ylabel("Number of crimes")
    axes[0].set_ylim(0, v.max() * 1.18)
    axes[0].set_title("Crime intensity across the 24-hour clock")
    axes[0].grid(axis="x", visible=False)

    labels = [str(x).split(" (")[0] for x in watch.index]
    bars = axes[1].bar(labels, watch["crimes"], color=[
        "#89C2D9", "#61A5C2", "#2A6F97", "#12263F"], width=0.66)
    for bar, n, p in zip(bars, watch["crimes"], watch["pct_of_all"]):
        axes[1].text(bar.get_x() + bar.get_width() / 2, n + 12, f"{n}\n{p}%",
                     ha="center", fontsize=8.4, color="#33475B")
    axes[1].set_ylim(0, watch["crimes"].max() * 1.26)
    axes[1].set_ylabel("Number of crimes")
    axes[1].set_title("Crime load by watch")
    axes[1].tick_params(axis="x", rotation=20, labelsize=8.5)
    axes[1].grid(axis="x", visible=False)

    fig.tight_layout()
    return viz.save(fig, "uc3_hourly_intensity")


def _fig_outliers(env) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np

    counts = env["area_counts"]
    names = env["names"]
    q1, q3 = np.percentile(counts.to_numpy(), [25, 75])
    upper = q3 + 1.5 * (q3 - q1)

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.4),
                             gridspec_kw={"width_ratios": [1, 1.3]})

    bp = axes[0].boxplot(counts.to_numpy(), vert=True, widths=0.42,
                         patch_artist=True, showfliers=True,
                         flierprops=dict(marker="o", markerfacecolor=viz.WARM,
                                         markeredgecolor=viz.WARM, markersize=7))
    bp["boxes"][0].set(facecolor="#C7DCEA", edgecolor=viz.ACCENT, linewidth=1.6)
    for part in ("whiskers", "caps"):
        for item in bp[part]:
            item.set(color=viz.ACCENT, linewidth=1.4)
    bp["medians"][0].set(color=viz.NAVY, linewidth=2.2)
    for code, n in counts[counts > upper].items():
        axes[0].annotate(f"  {names.loc[code, 'community_name']} ({n})", (1, n),
                         fontsize=8.5, color=viz.WARM, fontweight="bold", va="center")
    axes[0].set_xticks([])
    axes[0].set_ylabel("Crimes per community area")
    axes[0].set_title("Box plot — one area clears the upper fence")

    axes[1].hist(counts.to_numpy(), bins=14, color=viz.ACCENT, edgecolor="white")
    axes[1].axvline(upper, color=viz.WARM, linestyle="--", linewidth=1.8,
                    label=f"Upper fence {upper:.1f}")
    axes[1].axvline(counts.mean(), color=viz.NAVY, linestyle=":", linewidth=1.6,
                    label=f"Mean {counts.mean():.1f}")
    axes[1].set_xlabel("Crimes per community area")
    axes[1].set_ylabel("Number of areas")
    axes[1].set_title("Crime is evenly spread across the 77 areas")
    axes[1].legend(fontsize=8.5)
    axes[1].grid(axis="x", visible=False)

    fig.tight_layout()
    return viz.save(fig, "uc3_community_outliers")


def _fig_corr(env) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np
    import seaborn as sns

    corr = env["corr"]
    fig, ax = plt.subplots(figsize=(8.6, 6.6))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, annot=True, fmt=".2f", cmap=viz.DIVERGING,
                center=0, vmin=-0.25, vmax=0.25, linewidths=1.1, linecolor="white",
                square=True, cbar_kws={"label": "Pearson r", "shrink": 0.8}, ax=ax,
                annot_kws={"fontsize": 7.4})
    ax.set_title("Correlation matrix — every relationship is effectively zero\n"
                 "(colour scale capped at ±0.25 so any real signal would be visible)",
                 fontsize=11.5)
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.tick_params(axis="y", rotation=0, labelsize=8)
    for lbl in ax.get_xticklabels():
        lbl.set_ha("right")
    return viz.save(fig, "uc3_correlation_matrix")


def _fig_signal(env) -> Path:
    import matplotlib.pyplot as plt

    signal = env["signal"]
    fig, ax = plt.subplots(figsize=(9.6, 4.0))
    d = signal.iloc[::-1]
    colors = [viz.WARM if v == d["CV %"].max() else viz.ACCENT for v in d["CV %"]]
    bars = ax.barh(d["dimension"], d["CV %"], color=colors, height=0.62)
    for bar, cv, ratio in zip(bars, d["CV %"], d["max/min"]):
        ax.text(cv + 0.9, bar.get_y() + bar.get_height() / 2,
                f"{cv}%   (max/min {ratio}x)", va="center", fontsize=8.4,
                color="#33475B")
    ax.set_xlim(0, d["CV %"].max() * 1.42)
    ax.set_xlabel("Coefficient of variation in crime counts (%)")
    ax.set_title("Hour of day dominates every other dimension in the data")
    ax.grid(axis="y", visible=False)
    return viz.save(fig, "uc3_signal_strength")


if __name__ == "__main__":
    path = main()
    print(f"\n[Use Case 3] report written to {path}")
