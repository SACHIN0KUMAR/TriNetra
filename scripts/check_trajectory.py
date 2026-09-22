import sqlite3
import pandas as pd

DB_PATH = "data/trinetra.db"

conn = sqlite3.connect(DB_PATH)

query = """
SELECT
    project_id,
    report_month,
    physical_progress_pct,
    progress_change_pp
FROM project_trajectory
WHERE project_id = '108841'
ORDER BY report_month
"""

df = pd.read_sql_query(query, conn)

conn.close()

print()
print("=" * 70)
print("TRAJECTORY CHECK — PROJECT 108841")
print("=" * 70)

print(df.to_string(index=False))

print()
print("Rows:", len(df))