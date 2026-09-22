from pathlib import Path
import sqlite3
import pickle

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score
)


ROOT = Path(__file__).resolve().parents[1]

DB = ROOT / "data" / "trinetra.db"

MODEL_DIR = ROOT / "models"

MODEL_DIR.mkdir(
    exist_ok=True
)


# --------------------------------------------------
# LOAD TRAJECTORY DATA
# --------------------------------------------------

conn = sqlite3.connect(DB)

df = pd.read_sql_query(
    """
    SELECT *
    FROM project_trajectory
    ORDER BY project_id, report_month
    """,
    conn
)

conn.close()


if df.empty:

    raise RuntimeError(
        "No trajectory data found in database."
    )


df["report_month"] = pd.to_datetime(
    df["report_month"],
    errors="coerce"
)


df = df.sort_values(
    [
        "project_id",
        "report_month"
    ]
).copy()


# --------------------------------------------------
# CREATE NEXT-MONTH VALUES
# --------------------------------------------------

group = df.groupby(
    "project_id"
)


df["next_progress"] = (
    group["physical_progress_pct"]
    .shift(-1)
)


df["next_gap"] = (
    group["expenditure_progress_gap"]
    .shift(-1)
)


df["next_month"] = (
    group["report_month"]
    .shift(-1)
)


# Make sure the next observation is actually
# the next calendar month.

month_difference = (
    (df["next_month"].dt.year -
     df["report_month"].dt.year) * 12
    +
    (df["next_month"].dt.month -
     df["report_month"].dt.month)
)


df["month_difference"] = month_difference


df = df[
    df["month_difference"] == 1
].copy()


print(
    "Next-month observations:",
    len(df)
)


# --------------------------------------------------
# TARGET
# --------------------------------------------------

# Trajectory deterioration means:
#
# 1. Physical progress does not increase
# OR
#
# 2. Expenditure-progress gap increases


df["target"] = (
    (
        df["next_progress"]
        <=
        df["physical_progress_pct"]
    )
    |
    (
        df["next_gap"]
        >
        df["expenditure_progress_gap"]
    )
).astype(int)


print(
    "Positive deterioration cases:",
    int(df["target"].sum())
)


print(
    "Positive rate:",
    round(
        df["target"].mean() * 100,
        2
    ),
    "%"
)


# --------------------------------------------------
# FEATURES
# --------------------------------------------------

FEATURES = [

    "original_cost_cr",

    "revised_cost_cr",

    "expenditure_cr",

    "physical_progress_pct",

    "cost_escalation_pct",

    "expenditure_pct_original",

    "expenditure_progress_gap",

    "progress_change_pp",

    "expenditure_change_cr",

    "cost_escalation_change_pp",

]


for column in FEATURES:

    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )


df[FEATURES] = (
    df[FEATURES]
    .replace(
        [np.inf, -np.inf],
        np.nan
    )
    .fillna(0)
)


# --------------------------------------------------
# TEMPORAL SPLIT
# --------------------------------------------------

train = df[
    df["report_month"] < "2026-06-01"
].copy()


test = df[
    df["report_month"] >= "2026-06-01"
].copy()


print(
    "\nTrain:",
    len(train)
)


print(
    "Train positives:",
    int(train["target"].sum())
)


print(
    "Test:",
    len(test)
)


print(
    "Test positives:",
    int(test["target"].sum())
)


if train.empty or test.empty:

    raise RuntimeError(
        "Not enough temporal data for train/test split."
    )


# --------------------------------------------------
# LOGISTIC REGRESSION
# --------------------------------------------------

logistic = Pipeline(
    [
        (
            "scaler",
            StandardScaler()
        ),

        (
            "model",
            LogisticRegression(
                max_iter=2000,
                class_weight="balanced"
            )
        )
    ]
)


logistic.fit(
    train[FEATURES],
    train["target"]
)


logistic_probability = (
    logistic.predict_proba(
        test[FEATURES]
    )[:, 1]
)


# --------------------------------------------------
# RANDOM FOREST
# --------------------------------------------------

forest = RandomForestClassifier(

    n_estimators=300,

    max_depth=8,

    min_samples_leaf=8,

    class_weight="balanced_subsample",

    random_state=42,

    n_jobs=-1
)


forest.fit(
    train[FEATURES],
    train["target"]
)


forest_probability = (
    forest.predict_proba(
        test[FEATURES]
    )[:, 1]
)


# --------------------------------------------------
# EVALUATION
# --------------------------------------------------

if test["target"].nunique() > 1:

    logistic_roc = roc_auc_score(
        test["target"],
        logistic_probability
    )

    logistic_pr = average_precision_score(
        test["target"],
        logistic_probability
    )

    forest_roc = roc_auc_score(
        test["target"],
        forest_probability
    )

    forest_pr = average_precision_score(
        test["target"],
        forest_probability
    )


    print("\nMODEL RESULTS")

    print(
        "Logistic ROC-AUC:",
        round(logistic_roc, 4)
    )

    print(
        "Logistic PR-AUC:",
        round(logistic_pr, 4)
    )

    print(
        "Random Forest ROC-AUC:",
        round(forest_roc, 4)
    )

    print(
        "Random Forest PR-AUC:",
        round(forest_pr, 4)
    )


# --------------------------------------------------
# SAVE MODEL
# --------------------------------------------------

model_file = (
    MODEL_DIR
    / "trajectory_model.pkl"
)


with open(
    model_file,
    "wb"
) as f:

    pickle.dump(
        {
            "model": forest,

            "features": FEATURES,

            "target": (
                "Next-month trajectory deterioration"
            ),

            "train_period": (
                "Before June 2026"
            ),

            "test_period": (
                "June-July 2026"
            )
        },
        f
    )


print(
    "\nModel saved to:"
)

print(model_file)


# --------------------------------------------------
# ADD CURRENT PREDICTIONS TO DATABASE
# --------------------------------------------------

# Latest available observation for each project.

latest = (
    df
    .sort_values("report_month")
    .groupby("project_id")
    .tail(1)
    .copy()
)


latest_probability = (
    forest.predict_proba(
        latest[FEATURES]
    )[:, 1]
)


latest["ml_deterioration_probability"] = (
    latest_probability
)


conn = sqlite3.connect(DB)

# Add column if it doesn't exist.

try:

    conn.execute(
        """
        ALTER TABLE projects_latest
        ADD COLUMN ml_deterioration_probability REAL
        """
    )

except sqlite3.OperationalError:

    pass


for row in latest[
    [
        "project_id",
        "ml_deterioration_probability"
    ]
].itertuples(index=False):

    conn.execute(
        """
        UPDATE projects_latest

        SET
            ml_deterioration_probability = ?

        WHERE
            project_id = ?
        """,
        (
            float(
                row.ml_deterioration_probability
            ),

            int(
                row.project_id
            )
        )
    )


conn.commit()

conn.close()


print(
    "ML probabilities added to database."
)