from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

SOURCE = ROOT / "data" / "TriNetra_Risk_Engine_Prototype.xlsx"
DB = ROOT / "data" / "trinetra.db"


def clip01(value):
    return np.clip(value, 0, 1)


def risk_engine(df):
    d = df.copy()

    numeric_columns = [
        "original_cost_cr",
        "revised_cost_cr",
        "expenditure_cr",
        "physical_progress_pct",
        "cost_escalation_pct",
        "expenditure_pct_original",
        "expenditure_progress_gap",
        "progress_change_pp",
    ]

    for column in numeric_columns:
        d[column] = pd.to_numeric(
            d[column],
            errors="coerce"
        ).fillna(0.0)

    # Cost-related component
    cost = (
        0.70
        * clip01(
            d["cost_escalation_pct"].clip(lower=0) / 50.0
        )
        +
        0.30
        * clip01(
            d["expenditure_progress_gap"].clip(lower=0) / 100.0
        )
    )

    # Schedule/delay-related component
    delay = (
        0.55
        * clip01(
            d["expenditure_progress_gap"].clip(lower=0) / 100.0
        )
        +
        0.25
        * clip01(
            (-d["progress_change_pp"]).clip(lower=0) / 20.0
        )
        +
        0.20
        * clip01(
            (100 - d["physical_progress_pct"]).clip(lower=0) / 100.0
        )
    )

    # Recent deterioration indicators
    trend = (
        0.60
        * clip01(
            (-d["progress_change_pp"]).clip(lower=0) / 20.0
        )
        +
        0.40
        * clip01(
            d["cost_escalation_pct"].clip(lower=0) / 100.0
        )
    )

    d["cost_component"] = clip01(cost)
    d["delay_component"] = clip01(delay)
    d["trend_component"] = clip01(trend)

    d["overall_risk_score"] = (
        100
        * (
            0.45 * d["cost_component"]
            +
            0.45 * d["delay_component"]
            +
            0.10 * d["trend_component"]
        )
    )

    d["trajectory"] = np.select(
        [
            d["progress_change_pp"] <= -2,
            d["progress_change_pp"] >= 2,
        ],
        [
            "Worsening",
            "Improving",
        ],
        default="Watch"
    )

    d["risk_level"] = pd.cut(
        d["overall_risk_score"],
        bins=[-np.inf, 35, 65, np.inf],
        labels=["Low", "Medium", "High"]
    ).astype(str)

    # Financial exposure
    exposure = np.log1p(
        d["original_cost_cr"].clip(lower=0)
    )

    low = exposure.min()
    high = exposure.max()

    if high > low:
        exposure_norm = (
            (exposure - low) /
            (high - low)
        )
    else:
        exposure_norm = exposure * 0

    d["priority_score"] = (
        100
        * (
            0.80 * d["overall_risk_score"] / 100
            +
            0.20 * exposure_norm
        )
    )

    d["priority"] = pd.cut(
        d["priority_score"],
        bins=[-np.inf, 35, 65, np.inf],
        labels=["Low", "Medium", "High"]
    ).astype(str)

    def drivers(row):
        output = []

        if row.cost_escalation_pct > 5:
            output.append("Existing cost escalation")

        if row.expenditure_progress_gap > 20:
            output.append(
                "High expenditure-progress gap"
            )

        if row.physical_progress_pct < 25:
            output.append(
                "Low physical progress"
            )

        if row.progress_change_pp < -2:
            output.append(
                "Recent progress deterioration"
            )

        if not output:
            output.append(
                "No dominant threshold breach"
            )

        return "; ".join(output[:3])

    d["key_risk_drivers"] = d.apply(
        drivers,
        axis=1
    )

    return d


def main():

    latest = pd.read_excel(
        SOURCE,
        sheet_name="Risk Dashboard Data"
    )

    trajectory = pd.read_excel(
        SOURCE,
        sheet_name="Full Trajectory Data"
    )

    latest["report_month"] = pd.to_datetime(
        latest["report_month"],
        errors="coerce"
    )

    trajectory["report_month"] = pd.to_datetime(
        trajectory["report_month"],
        errors="coerce"
    )

    latest = latest.drop_duplicates(
        ["project_id"],
        keep="last"
    )

    trajectory = trajectory.drop_duplicates(
        ["project_id", "report_month"],
        keep="last"
    )

    scored = risk_engine(latest)

    conn = sqlite3.connect(DB)

    cursor = conn.cursor()

    cursor.executescript(
        """
        DROP TABLE IF EXISTS projects_latest;
        DROP TABLE IF EXISTS project_trajectory;
        DROP TABLE IF EXISTS metadata;

        CREATE TABLE projects_latest (
            project_id INTEGER PRIMARY KEY,
            project_name TEXT,
            agency TEXT,
            state TEXT,
            report_month TEXT,

            original_cost_cr REAL,
            revised_cost_cr REAL,
            expenditure_cr REAL,

            physical_progress_pct REAL,
            cost_escalation_pct REAL,
            expenditure_pct_original REAL,
            expenditure_progress_gap REAL,
            progress_change_pp REAL,

            cost_component REAL,
            delay_component REAL,
            trend_component REAL,

            overall_risk_score REAL,
            risk_level TEXT,
            trajectory TEXT,

            priority_score REAL,
            priority TEXT,

            key_risk_drivers TEXT
        );

        CREATE TABLE project_trajectory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            report_month TEXT,
            project_id INTEGER,
            project_name TEXT,
            agency TEXT,

            legacy_ocms TEXT,
            pmgid TEXT,
            state TEXT,

            approval_date TEXT,
            start_date TEXT,
            original_doc TEXT,
            revised_doc TEXT,

            original_cost_cr REAL,
            revised_cost_cr REAL,
            expenditure_cr REAL,

            physical_progress_pct REAL,

            pdf_page INTEGER,

            cost_escalation_pct REAL,
            expenditure_pct_original REAL,
            expenditure_progress_gap REAL,

            progress_change_pp,
            expenditure_change_cr REAL,
            cost_escalation_change_pp REAL,

            trajectory TEXT
        );

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )

    scored["report_month"] = (
        scored["report_month"]
        .dt.strftime("%Y-%m-%d")
    )

    scored.to_sql(
        "projects_latest",
        conn,
        if_exists="append",
        index=False
    )

    trajectory["report_month"] = (
        trajectory["report_month"]
        .dt.strftime("%Y-%m-%d")
    )

    trajectory.to_sql(
        "project_trajectory",
        conn,
        if_exists="append",
        index=False
    )

    metadata = {
        "source_file": SOURCE.name,
        "latest_projects": str(len(scored)),
        "trajectory_rows": str(len(trajectory)),
        "latest_report_month": str(
            scored["report_month"].max()
        ),
        "risk_definition": (
            "Explainable prototype index using "
            "cost escalation, expenditure-progress gap, "
            "physical progress and progress change."
        ),
        "live_api_connected": "false",
    }

    pd.DataFrame(
        metadata.items(),
        columns=["key", "value"]
    ).to_sql(
        "metadata",
        conn,
        if_exists="append",
        index=False
    )

    conn.close()

    print("Database created:")
    print(DB)
    print(f"Projects: {len(scored):,}")
    print(f"Trajectory rows: {len(trajectory):,}")


if __name__ == "__main__":
    main()