import sqlite3
import joblib
import pandas as pd
import numpy as np
import shap

# ============================================================
# CONFIG
# ============================================================

DB_PATH = "data/trinetra.db"
MODEL_PATH = "models/trajectory_model.pkl"

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

# ============================================================
# LOAD MODEL
# ============================================================

model_data = joblib.load(MODEL_PATH)

# Our training script saved the model inside a dictionary.
if isinstance(model_data, dict):
    model = model_data["model"]
else:
    model = model_data

print("Model loaded.")

print("Features:")
for feature in FEATURES:
    print(" -", feature)

# ============================================================
# LOAD DATA
# ============================================================

conn = sqlite3.connect(DB_PATH)

query = f"""
SELECT
    project_id,
    project_name,
    {", ".join(FEATURES)}
FROM project_trajectory
WHERE
    original_cost_cr IS NOT NULL
    AND revised_cost_cr IS NOT NULL
    AND expenditure_cr IS NOT NULL
    AND physical_progress_pct IS NOT NULL
    AND cost_escalation_pct IS NOT NULL
    AND expenditure_pct_original IS NOT NULL
    AND expenditure_progress_gap IS NOT NULL
    AND progress_change_pp IS NOT NULL
    AND expenditure_change_cr IS NOT NULL
    AND cost_escalation_change_pp IS NOT NULL
"""

df = pd.read_sql_query(query, conn)
conn.close()

print()
print("Rows loaded:", len(df))

# ============================================================
# PREPARE FEATURES
# ============================================================

X = df[FEATURES].copy()

# Make sure everything is numeric.
X = X.apply(pd.to_numeric, errors="coerce")

# Remove invalid rows.
valid = X.notna().all(axis=1)

X = X.loc[valid].reset_index(drop=True)
df = df.loc[valid].reset_index(drop=True)

print("Valid rows:", len(X))

# ============================================================
# SHAP EXPLAINER
# ============================================================

print()
print("Creating SHAP explainer...")

explainer = shap.TreeExplainer(model)

# Explain one project first.
sample = X.iloc[[0]]

shap_values = explainer.shap_values(sample)

print()
print("SHAP output type:", type(shap_values))

if isinstance(shap_values, list):
    print("SHAP output is a list.")
    print("Number of outputs:", len(shap_values))

    # Binary classification:
    # class 1 = deterioration / higher risk
    if len(shap_values) == 2:
        values = np.asarray(shap_values[1])[0]
    else:
        values = np.asarray(shap_values[0])[0]

else:
    shap_array = np.asarray(shap_values)

    print("SHAP output shape:", shap_array.shape)

    # Newer SHAP versions may return:
    # (samples, features, classes)
    if shap_array.ndim == 3:

        # Class 1 = positive/deterioration class
        values = shap_array[0, :, 1]

    # Standard format:
    # (samples, features)
    elif shap_array.ndim == 2:

        values = shap_array[0]

    else:
        raise ValueError(
            f"Unexpected SHAP output shape: {shap_array.shape}"
        )

# ============================================================
# VERIFY SHAPE
# ============================================================

values = np.asarray(values).reshape(-1)

if len(values) != len(FEATURES):
    raise ValueError(
        f"SHAP values length ({len(values)}) "
        f"does not match feature count ({len(FEATURES)})."
    )

# ============================================================
# FEATURE IMPORTANCE FOR THIS PROJECT
# ============================================================

importance = pd.DataFrame({
    "feature": FEATURES,
    "shap_value": values,
    "absolute_impact": np.abs(values),
    "feature_value": sample.iloc[0].values
})

importance = importance.sort_values(
    "absolute_impact",
    ascending=False
)

# ============================================================
# PROJECT INFORMATION
# ============================================================

project_id = df.iloc[0]["project_id"]
project_name = df.iloc[0]["project_name"]

probability = model.predict_proba(sample)[0][1]

print()
print("=" * 70)
print("PROJECT")
print("=" * 70)

print("Project ID:", project_id)
print("Project Name:", project_name)

print()
print("Predicted deterioration probability:")
print(f"{probability:.4f} ({probability * 100:.2f}%)")

print()
print("=" * 70)
print("TOP SHAP DRIVERS")
print("=" * 70)

for _, row in importance.head(10).iterrows():

    direction = (
        "INCREASES risk"
        if row["shap_value"] > 0
        else "REDUCES risk"
    )

    print(
        f"{row['feature']:<35} "
        f"SHAP={row['shap_value']:+.6f}  "
        f"value={row['feature_value']:.4f}  "
        f"{direction}"
    )

print()
print("SHAP explanation completed successfully.")