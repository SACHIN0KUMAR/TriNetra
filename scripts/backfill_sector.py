from pathlib import Path
import sqlite3
import shutil
from datetime import datetime

import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = PROJECT_ROOT / "data" / "trinetra.db"

SOURCE_ROOT = Path(r"C:\paimana xl data")

BACKUP_PATH = (
    PROJECT_ROOT
    / "data"
    / f"trinetra_before_metadata_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
)

# PAIMANA Excel structure:
# Row 0 = Projects Details
# Row 1 = blank
# Row 2 = actual column headers
HEADER_ROW = 2


# ============================================================
# HELPERS
# ============================================================

def clean_project_id(value):
    """Convert Project Code into a consistent string."""

    if pd.isna(value):
        return None

    value = str(value).strip()

    # Excel may represent numeric IDs as 400298.0
    if value.endswith(".0"):
        value = value[:-2]

    return value


def clean_text(value):
    """Clean text fields while preserving their actual wording."""

    if pd.isna(value):
        return None

    value = str(value).strip()

    if not value:
        return None

    return value


# ============================================================
# START
# ============================================================

print("=" * 70)
print("TRINETRA - PAIMANA METADATA BACKFILL")
print("=" * 70)

print(f"\nDatabase:")
print(DB_PATH)

print(f"\nSource folder:")
print(SOURCE_ROOT)


# ============================================================
# FIND ORIGINAL PAIMANA FILES
# ============================================================

source_files = []

for year in ["2025", "2026"]:

    folder = SOURCE_ROOT / year

    if not folder.exists():
        print(f"WARNING: Folder not found: {folder}")
        continue

    for file in sorted(folder.glob("Projects_Report_*.xlsx")):

        # Ignore derived TriNetra workbooks
        if file.name.lower().startswith("trinetra_"):
            continue

        source_files.append(file)


print(f"\nOriginal PAIMANA files found: {len(source_files)}")

for file in source_files:
    print(f"  - {file.name}")


if not source_files:
    raise RuntimeError("No original PAIMANA files found.")


# ============================================================
# BACKUP DATABASE
# ============================================================

if not DB_PATH.exists():
    raise FileNotFoundError(
        f"Database not found: {DB_PATH}"
    )


print("\n" + "-" * 70)
print("Creating database backup...")

shutil.copy2(DB_PATH, BACKUP_PATH)

print(f"Backup created:")
print(BACKUP_PATH)


# ============================================================
# BUILD METADATA MAPPING
# ============================================================

metadata = {}

total_rows = 0
files_processed = 0


for file in source_files:

    print("\n" + "-" * 70)
    print(f"Reading: {file.name}")

    try:

        df = pd.read_excel(
            file,
            sheet_name="Sheet1",
            header=HEADER_ROW
        )

    except Exception as e:

        print(f"ERROR reading {file.name}: {e}")
        continue


    total_rows += len(df)

    print(f"Rows read: {len(df)}")


    # --------------------------------------------------------
    # Required columns
    # --------------------------------------------------------

    required_columns = [
        "Project Code",
        "Project Name",
        "Sector Name",
        "Line Ministry",
        "Implementing Agency",
    ]

    missing = [
        col for col in required_columns
        if col not in df.columns
    ]

    if missing:

        print("WARNING - missing columns:", missing)
        print("Available columns:")
        print(list(df.columns))
        continue


    # --------------------------------------------------------
    # Create Project Code → Metadata mapping
    # --------------------------------------------------------

    usable = 0

    for _, row in df.iterrows():

        project_id = clean_project_id(
            row["Project Code"]
        )

        if not project_id:
            continue


        project_name = clean_text(
            row["Project Name"]
        )

        sector = clean_text(
            row["Sector Name"]
        )

        ministry = clean_text(
            row["Line Ministry"]
        )

        agency = clean_text(
            row["Implementing Agency"]
        )


        metadata[project_id] = {
            "project_name": project_name,
            "sector": sector,
            "line_ministry": ministry,
            "agency": agency,
        }

        usable += 1


    print(
        f"Usable project metadata records: {usable}"
    )

    files_processed += 1


# ============================================================
# MAPPING SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("SOURCE DATA SUMMARY")
print("=" * 70)

print(f"Files processed       : {files_processed}")
print(f"Total Excel rows      : {total_rows}")
print(f"Unique Project IDs    : {len(metadata)}")


if not metadata:
    raise RuntimeError(
        "No project metadata was extracted."
    )


# ============================================================
# OPEN DATABASE
# ============================================================

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()


# ============================================================
# CHECK DATABASE COLUMNS
# ============================================================

cursor.execute(
    "PRAGMA table_info(projects_latest)"
)

columns = [
    row[1]
    for row in cursor.fetchall()
]

print("\nCurrent database columns:")
print(columns)


# ============================================================
# ADD NEW COLUMNS IF REQUIRED
# ============================================================

if "sector" not in columns:

    print("\nAdding sector column...")

    cursor.execute(
        """
        ALTER TABLE projects_latest
        ADD COLUMN sector TEXT
        """
    )


if "line_ministry" not in columns:

    print("Adding line_ministry column...")

    cursor.execute(
        """
        ALTER TABLE projects_latest
        ADD COLUMN line_ministry TEXT
        """
    )


conn.commit()


# ============================================================
# GET DATABASE PROJECT IDS
# ============================================================

cursor.execute(
    """
    SELECT project_id
    FROM projects_latest
    """
)

db_project_ids = set()

for row in cursor.fetchall():

    project_id = clean_project_id(row[0])

    if project_id:
        db_project_ids.add(project_id)


print(
    f"\nProjects in dashboard database: "
    f"{len(db_project_ids)}"
)


# ============================================================
# UPDATE METADATA
# ============================================================

updated = 0
matched = 0

for project_id, data in metadata.items():

    if project_id not in db_project_ids:
        continue

    matched += 1

    cursor.execute(
        """
        UPDATE projects_latest
        SET
            sector = ?,
            agency = ?,
            line_ministry = ?
        WHERE project_id = ?
        """,
        (
            data["sector"],
            data["agency"],
            data["line_ministry"],
            project_id,
        )
    )

    if cursor.rowcount > 0:
        updated += cursor.rowcount


conn.commit()


# ============================================================
# VERIFY
# ============================================================

cursor.execute(
    """
    SELECT COUNT(*)
    FROM projects_latest
    WHERE sector IS NOT NULL
      AND TRIM(sector) != ''
    """
)

sector_count = cursor.fetchone()[0]


cursor.execute(
    """
    SELECT COUNT(*)
    FROM projects_latest
    WHERE agency IS NOT NULL
      AND TRIM(agency) != ''
    """
)

agency_count = cursor.fetchone()[0]


cursor.execute(
    """
    SELECT COUNT(*)
    FROM projects_latest
    WHERE line_ministry IS NOT NULL
      AND TRIM(line_ministry) != ''
    """
)

ministry_count = cursor.fetchone()[0]


# ============================================================
# SAMPLE CHECK
# ============================================================

cursor.execute(
    """
    SELECT
        project_id,
        project_name,
        sector,
        line_ministry,
        agency
    FROM projects_latest
    WHERE project_id = 400298
    """
)

sample = cursor.fetchone()


# ============================================================
# CLOSE
# ============================================================

conn.close()


# ============================================================
# FINAL REPORT
# ============================================================

print("\n" + "=" * 70)
print("METADATA BACKFILL COMPLETE")
print("=" * 70)

print(f"\nProjects in database       : {len(db_project_ids)}")
print(f"Source Project IDs         : {len(metadata)}")
print(f"Matched projects           : {matched}")
print(f"Database rows updated      : {updated}")

print(f"\nProjects with Sector       : {sector_count}")
print(f"Projects with Agency       : {agency_count}")
print(f"Projects with Line Ministry: {ministry_count}")


if sample:

    print("\nSample project 400298:")
    print(f"Project ID     : {sample[0]}")
    print(f"Project Name   : {sample[1]}")
    print(f"Sector         : {sample[2]}")
    print(f"Line Ministry  : {sample[3]}")
    print(f"Agency         : {sample[4]}")


print("\nBackup:")
print(BACKUP_PATH)

print("\nDone.")