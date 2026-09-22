from pathlib import Path
from datetime import datetime, date
import re
import shutil
import sqlite3

import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "trinetra.db"

SOURCE_DIRS = [
    Path(r"C:\paimana xl data\2025"),
    Path(r"C:\paimana xl data\2026"),
]


# ============================================================
# HELPERS
# ============================================================

def clean_column_name(value):
    """Normalize Excel column names for reliable matching."""
    return re.sub(
        r"\s+",
        " ",
        str(value).replace("\n", " ")
    ).strip().lower()


def find_column(columns, target):
    """Find an Excel column by normalized name."""
    target = target.lower().strip()

    for column in columns:
        if clean_column_name(column) == target:
            return column

    return None


def clean_project_id(value):
    """Convert Excel project IDs into clean string IDs."""
    if pd.isna(value):
        return None

    text = str(value).strip()

    # Excel may convert numeric IDs such as 400298 -> 400298.0
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]

    if not text:
        return None

    return text


def parse_report_month(filename):
    """
    Extract (year, month) from filenames such as:

    Projects_Report_July2025.xlsx
    Projects_Report_August2025.xlsx
    Projects_Report_Dec2025.xlsx
    Projects_Report_feb2026.xlsx
    Projects_Report_jan2026.xlsx
    """

    month_patterns = [
        (1, ["jan", "january"]),
        (2, ["feb", "february"]),
        (3, ["mar", "march"]),
        (4, ["apr", "april"]),
        (5, ["may"]),
        (6, ["jun", "june"]),
        (7, ["jul", "july"]),
        (8, ["aug", "august"]),
        (9, ["sep", "sept", "september"]),
        (10, ["oct", "october"]),
        (11, ["nov", "november"]),
        (12, ["dec", "december"]),
    ]

    name = Path(filename).stem.lower()

    for month_number, names in month_patterns:
        for month_name in names:

            pattern = rf"{month_name}[_-]?(\d{{4}})"
            match = re.search(pattern, name)

            if match:
                year = int(match.group(1))
                return year, month_number

    return None


def parse_date(value):
    """
    Convert PAIMANA Excel date values into YYYY-MM-DD.
    """

    if pd.isna(value):
        return None

    # Already a pandas/datetime/date object
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")

    # Excel serial date
    if isinstance(value, (int, float)) and not isinstance(value, bool):

        number = float(value)

        if 1 <= number <= 100000:

            try:
                parsed = (
                    pd.Timestamp("1899-12-30")
                    + pd.to_timedelta(number, unit="D")
                )

                return parsed.strftime("%Y-%m-%d")

            except Exception:
                pass

    text = str(value).strip()

    if not text:
        return None

    parsed = pd.to_datetime(
        text,
        dayfirst=True,
        errors="coerce"
    )

    if pd.isna(parsed):
        return None

    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


# ============================================================
# FIND SOURCE FILES
# ============================================================

files = []

for source_dir in SOURCE_DIRS:

    if not source_dir.exists():

        print(
            f"WARNING: folder not found: {source_dir}"
        )

        continue

    files.extend(
        source_dir.glob("Projects_Report_*.xlsx")
    )


# Keep only files for which the month/year can be detected.
valid_files = []

for file in files:

    report_month = parse_report_month(file.name)

    if report_month is None:

        print(
            f"WARNING: could not determine report month "
            f"from {file.name}"
        )

        continue

    valid_files.append(file)


# Sort chronologically.
files = sorted(
    valid_files,
    key=lambda p: parse_report_month(p.name)
)


# ============================================================
# START
# ============================================================

print("=" * 70)
print("TriNetra — PAIMANA commissioning-date backfill")
print("=" * 70)

print(f"Database: {DB}")
print(f"Source files found: {len(files)}")

for file in files:
    print(f"  - {file}")


if not files:

    raise SystemExit(
        "No valid Projects_Report_*.xlsx files were found."
    )


# ============================================================
# DATABASE BACKUP
# ============================================================

backup_name = (
    "trinetra_before_date_backfill_"
    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
)

backup_path = ROOT / "data" / backup_name

shutil.copy2(
    DB,
    backup_path
)

print()
print("Database backup created:")
print(f"  {backup_path}")


# ============================================================
# SOURCE DATE FIELDS
# ============================================================

date_fields = {
    "original_date_of_commissioning":
        "original date of commissioning",

    "revised_date_of_commissioning":
        "revised date of commissioning",

    "sanction_date":
        "sanction date",
}


# ============================================================
# COLLECT LATEST SOURCE VALUES
# ============================================================

"""
Structure:

latest_dates[project_id][field] = {
    "report_month": (year, month),
    "value": "YYYY-MM-DD"
}
"""

latest_dates = {}

total_rows = 0
total_project_ids = 0


for file in files:

    report_month = parse_report_month(file.name)

    print()
    print(f"Reading: {file.name}")

    try:

        df = pd.read_excel(
            file,
            sheet_name="Sheet1",
            header=2
        )

    except Exception as exc:

        print(f"  ERROR: {exc}")
        continue

    total_rows += len(df)

    # --------------------------------------------------------
    # Project ID column
    # --------------------------------------------------------

    project_id_column = find_column(
        df.columns,
        "project code"
    )

    if project_id_column is None:

        print(
            "  ERROR: Project Code column not found."
        )

        continue


    # --------------------------------------------------------
    # Date columns
    # --------------------------------------------------------

    date_columns = {}

    for field, target in date_fields.items():

        column = find_column(
            df.columns,
            target
        )

        if column is None:

            print(
                f"  WARNING: column not found: {target}"
            )

        else:

            date_columns[field] = column


    # --------------------------------------------------------
    # Read project rows
    # --------------------------------------------------------

    file_ids = 0

    for _, row in df.iterrows():

        project_id = clean_project_id(
            row[project_id_column]
        )

        if project_id is None:
            continue

        file_ids += 1
        total_project_ids += 1

        if project_id not in latest_dates:
            latest_dates[project_id] = {}


        # ----------------------------------------------------
        # Read each date field
        # ----------------------------------------------------

        for field, column in date_columns.items():

            parsed = parse_date(
                row[column]
            )

            if parsed is None:
                continue


            previous = latest_dates[
                project_id
            ].get(field)


            # Keep the value from the latest report
            if (
                previous is None
                or report_month >= previous["report_month"]
            ):

                latest_dates[
                    project_id
                ][field] = {
                    "report_month": report_month,
                    "value": parsed
                }


    print(f"  Rows: {len(df)}")
    print(f"  Project IDs: {file_ids}")


print()
print("=" * 70)
print("SOURCE EXTRACTION COMPLETE")
print("=" * 70)

print(f"Total Excel rows read: {total_rows}")
print(f"Unique project IDs collected: {len(latest_dates)}")


# ============================================================
# OPEN DATABASE
# ============================================================

conn = sqlite3.connect(DB)


# ============================================================
# ADD DATE COLUMNS IF NEEDED
# ============================================================

existing_columns = {
    row[1]
    for row in conn.execute(
        "PRAGMA table_info(projects_latest)"
    ).fetchall()
}


new_columns = [
    "original_date_of_commissioning",
    "revised_date_of_commissioning",
    "sanction_date",
]


for column in new_columns:

    if column not in existing_columns:

        conn.execute(
            f"""
            ALTER TABLE projects_latest
            ADD COLUMN {column} TEXT
            """
        )

        print(
            f"Added database column: {column}"
        )

    else:

        print(
            f"Database column already exists: {column}"
        )


conn.commit()


# ============================================================
# BACKFILL PROJECTS
# ============================================================

matched_projects = 0
updated_projects = 0

date_counts = {
    field: 0
    for field in new_columns
}


for project_id, values in latest_dates.items():

    # Our current PAIMANA IDs are numeric.
    try:

        numeric_id = int(project_id)

    except ValueError:

        continue


    # --------------------------------------------------------
    # Confirm project exists in TriNetra DB
    # --------------------------------------------------------

    exists = conn.execute(
        """
        SELECT project_id
        FROM projects_latest
        WHERE project_id = ?
        """,
        (numeric_id,)
    ).fetchone()


    if exists is None:
        continue

    matched_projects += 1


    # --------------------------------------------------------
    # Get current database values
    # --------------------------------------------------------

    current = conn.execute(
        """
        SELECT
            original_date_of_commissioning,
            revised_date_of_commissioning,
            sanction_date
        FROM projects_latest
        WHERE project_id = ?
        """,
        (numeric_id,)
    ).fetchone()


    updates = {}


    # --------------------------------------------------------
    # Compare source values with database values
    # --------------------------------------------------------

    for index, field in enumerate(new_columns):

        previous_db_value = current[index]

        source_record = values.get(field)

        if source_record is None:
            continue

        # IMPORTANT:
        # source_record is:
        # {
        #     "report_month": (...),
        #     "value": "YYYY-MM-DD"
        # }
        #
        # We must store only the actual date string.
        source_value = source_record["value"]


        # Fill missing DB value
        if (
            source_value is not None
            and not previous_db_value
        ):

            updates[field] = source_value


        # Update if latest source differs
        elif (
            source_value is not None
            and previous_db_value != source_value
        ):

            updates[field] = source_value


    # --------------------------------------------------------
    # Apply updates
    # --------------------------------------------------------

    if not updates:
        continue


    set_clause = ", ".join(
        f"{field} = ?"
        for field in updates
    )


    params = list(
        updates.values()
    )

    params.append(
        numeric_id
    )


    conn.execute(
        f"""
        UPDATE projects_latest
        SET {set_clause}
        WHERE project_id = ?
        """,
        params
    )


    updated_projects += 1


    for field in updates:
        date_counts[field] += 1


# Save all updates
conn.commit()


# ============================================================
# FINAL AUDIT
# ============================================================

total_db_projects = conn.execute(
    """
    SELECT COUNT(*)
    FROM projects_latest
    """
).fetchone()[0]


print()
print("=" * 70)
print("BACKFILL COMPLETE")
print("=" * 70)

print(
    f"Projects currently in DB: "
    f"{total_db_projects}"
)

print(
    f"Source unique project IDs: "
    f"{len(latest_dates)}"
)

print(
    f"Matched DB projects: "
    f"{matched_projects}"
)

print(
    f"Projects updated: "
    f"{updated_projects}"
)


print()
print("Values written:")

for field, count in date_counts.items():

    print(
        f"  {field}: {count}"
    )


# ============================================================
# VERIFY DATABASE COLUMNS
# ============================================================

print()
print("Database columns:")

columns = conn.execute(
    "PRAGMA table_info(projects_latest)"
).fetchall()

for row in columns:

    print(
        f"  {row[1]} ({row[2]})"
    )


# ============================================================
# SAMPLE RECORDS
# ============================================================

print()
print("Sample records:")

sample_rows = conn.execute(
    """
    SELECT
        project_id,
        project_name,
        original_date_of_commissioning,
        revised_date_of_commissioning,
        sanction_date
    FROM projects_latest
    WHERE
        original_date_of_commissioning IS NOT NULL
        OR revised_date_of_commissioning IS NOT NULL
        OR sanction_date IS NOT NULL
    LIMIT 5
    """
).fetchall()


for row in sample_rows:

    print(
        f"  {row[0]} | {row[1]} | "
        f"Original DoC={row[2]} | "
        f"Revised DoC={row[3]} | "
        f"Sanction={row[4]}"
    )


# ============================================================
# CLOSE
# ============================================================

conn.close()

print()
print(f"Backup: {backup_path}")
print("Done.")