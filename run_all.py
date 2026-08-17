"""
Run the whole delivery end to end:
    build the warehouse, then generate all four use-case reports.

    python run_all.py
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
STEPS = [
    ("Building the data warehouse", [sys.executable, "-m", "db.etl"]),
    ("Use Case 1 — Load and Clean",
     [sys.executable, "usecases/usecase1_load_and_clean.py"]),
    ("Use Case 2 — EDA and Visualization",
     [sys.executable, "usecases/usecase2_eda_visualization.py"]),
    ("Use Case 3 — Statistical Insights",
     [sys.executable, "usecases/usecase3_statistical_insights.py"]),
    ("Use Case 4 — SQL Reporting",
     [sys.executable, "usecases/usecase4_sql_reporting.py"]),
]


def main() -> int:
    for i, (label, cmd) in enumerate(STEPS, 1):
        print(f"\n{'=' * 72}\n[{i}/{len(STEPS)}] {label}\n{'=' * 72}")
        result = subprocess.run(cmd, cwd=BASE)
        if result.returncode != 0:
            print(f"\nFAILED: {label}")
            return result.returncode

    reports = sorted((BASE / "usecases" / "reports").glob("*.pdf"))
    figures = sorted((BASE / "usecases" / "figures").glob("*.png"))
    print(f"\n{'=' * 72}\nDone. {len(reports)} reports and {len(figures)} figures generated.")
    for r in reports:
        print(f"  {r.relative_to(BASE)}  ({r.stat().st_size / 1024:.0f} KB)")
    print("\nStart the web application with:  python webapp/app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
