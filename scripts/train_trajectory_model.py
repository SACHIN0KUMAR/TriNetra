from pathlib import Path
import pickle
import sqlite3

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score
)


ROOT = Path(__file__).resolve().parents[1]

DB = ROOT / "data" / "trinetra.db"

SOURCE = (
    ROOT
    / "data"
    / "TriNetra_Current_Data_Engineering_v1.xlsx"
)

MODEL = ROOT / "models" / "trajectory_rf.pkl"


FEATURES = [
    "original_cost_cr",
    "revised_cost_cr",
    "expenditure_cr",
    "physical_progress_pct",
    "cost_overrun_pct",
    "expenditure_pct_of_original",
    "expenditure_progress_gap_pp",
    "progress_change_pp",
    "expenditure_change_cr",
    "revised_cost_change_cr",
]


df = pd.read_excel(
    SOURCE,
    sheet_name="Master Monthly Panel"
)

df["report_month"] = pd.to_datetime(
    df["report_month"]
)

df = df.sort_values(
    ["project_code", "report_month"]
).copy()


df["next_month"] = (
    df.groupby("project_code")["report_month"]
      .shift(-1)
)

df["next_progress"] = (
    df.groupby("project_code")
      ["physical_progress_pct"]
      .shift(-1)
)

df["next_gap"] = (
    df.groupby("project_code")
      ["expenditure_progress_gap_pp"]
      .shift(-1)
)


df["month_diff"] = (
    (df["next_month"].dt.year - df["report_month"].dt.year)
    * 12
    +
    (df["next_month"].dt.month - df["report_month"].dt.month)
)


df = df[
    df["month_diff"] == 1
].copy()


# Prototype target:
# next month's physical progress does not increase
# OR the expenditure-progress gap increases.
df["target"] = (
    (df["next_progress"] <= df["physical_progress_pct"])
    |
    (df["next_gap"] > df["expenditure_progress_gap_pp"])
).astype(int)


for feature in FEATURES:
    df[feature] = pd.to_numeric(
        df[feature],
        errors="coerce"
    )

df[FEATURES] = (
    df[FEATURES]
    .replace([np.inf, -np.inf], np.nan)
    .fillna(0)
)


train = df[
    (df.report_month >= "2025-07-01")
    &
    (df.report_month < "2026-01-01")
]

validation = df[
    (df.report_month >= "2026-01-01")
    &
    (df.report_month < "2026-03-01")
]

test = df[
    (df.report_month >= "2026-03-01")
    &
    (df.report_month < "2026-05-01")
]


model = RandomForestClassifier(
    n_estimators=300,
    max_depth=8,
    min_samples_leaf=8,
    class_weight="balanced_subsample",
    random_state=42,
    n_jobs=-1,
)


model.fit(
    train[FEATURES],
    train["target"]
)


print(
    "Train:",
    len(train),
    "positives:",
    int(train.target.sum())
)


for name, part in [
    ("Validation", validation),
    ("Test", test),
]:

    if (
        len(part) > 0
        and part.target.nunique() > 1
    ):

        probability = model.predict_proba(
            part[FEATURES]
        )[:, 1]

        print(
            name,
            "n=",
            len(part),
            "positives=",
            int(part.target.sum()),
            "ROC-AUC=",
            round(
                roc_auc_score(
                    part.target,
                    probability
                ),
                4
            ),
            "PR-AUC=",
            round(
                average_precision_score(
                    part.target,
                    probability
                ),
                4
            )
        )


# Generate latest-project ML signal.

latest = pd.read_excel(
    SOURCE,
    sheet_name="Master Monthly Panel"
)

latest["report_month"] = pd.to_datetime(
    latest["report_month"]
)

latest = (
    latest
    .sort_values("report_month")
    .groupby("project_code")
    .tail(1)
    .copy()
)


for feature in FEATURES:

    latest[feature] = pd.to_numeric(
        latest[feature],
        errors="coerce"
    )

latest[FEATURES] = (
    latest[FEATURES]
    .replace([np.inf, -np.inf], np.nan)
    .fillna(0)
)


latest["ml_deterioration_probability"] = (
    model.predict_proba(
        latest[FEATURES]
    )[:, 1]
)


# Add ML probability to SQLite.

conn = sqlite3.connect(DB)

try:
    conn.execute(
        """
        ALTER TABLE projects_latest
        ADD COLUMN ml_deterioration_probability REAL
        """
    )
except sqlite3.OperationalError:
    pass


for project_id, probability in latest[
    [
        "project_code",
        "ml_deterioration_probability"
    ]
].itertuples(index=False):

    try:

        conn.execute(
            """
            UPDATE projects_latest
            SET ml_deterioration_probability = ?
            WHERE project_id = ?
            """,
            (
                float(probability),
                int(float(project_id))
            )
        )

    except Exception:
        pass


conn.commit()
conn.close()


MODEL.parent.mkdir(
    exist_ok=True
)


with open(MODEL, "wb") as file:

    pickle.dump(
        {
            "model": model,
            "features": FEATURES,
            "target_definition": (
                "Next-month trajectory deterioration: "
                "physical progress does not increase OR "
                "expenditure-progress gap increases."
            ),
            "train_period": "2025-07 through 2025-12",
            "validation_period": "2026-01 through 2026-02",
            "test_period": "2026-03 through 2026-04",
        },
        file
    )


print(
    "Saved model:",
    MODEL
)