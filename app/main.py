from pathlib import Path
import sqlite3
import threading
import pickle

import joblib
import numpy as np
import pandas as pd
import shap
import os
import secrets
import time

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Header,
    Depends,
    UploadFile,
    File
)
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials
)

from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from io import BytesIO

from fastapi.responses import StreamingResponse
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)



# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "trinetra.db"
STATIC = ROOT / "static"
MODEL_PATH = ROOT / "models" / "trajectory_model.pkl"


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="TriNetra API",
    version="1.0.0"
)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

ADMIN_USERNAME = os.getenv(
    "TRINETRA_ADMIN_USERNAME",
    "admin"
)

ADMIN_PASSWORD = os.getenv(
    "TRINETRA_ADMIN_PASSWORD",
    "trinetra@123"
)

ADMIN_SESSION_DURATION = 8 * 60 * 60  # 8 hours

admin_sessions = {}
security = HTTPBearer(auto_error=False)


class AdminLoginRequest(BaseModel):

    username: str
    password: str

class AdminProjectRequest(BaseModel):

    project_id: int
    project_name: str

    sector: str = ""
    line_ministry: str = ""
    agency: str = ""

    original_cost_cr: float
    revised_cost_cr: float = 0
    expenditure_cr: float = 0
    physical_progress_pct: float = 0

    original_date_of_commissioning: str = ""
    revised_date_of_commissioning: str = ""
    sanction_date: str = ""

    report_month: str
    
def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required"
        )

    token = credentials.credentials

    expiry = admin_sessions.get(token)

    if expiry is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid admin session"
        )

    if time.time() > expiry:
        admin_sessions.pop(token, None)

        raise HTTPException(
            status_code=401,
            detail="Admin session expired"
        )

    return True
# ============================================================
# ADMIN AUTHENTICATION ROUTES
# ============================================================

@app.post("/api/admin/login")
def admin_login(credentials: AdminLoginRequest):

    username_ok = secrets.compare_digest(
        credentials.username,
        ADMIN_USERNAME
    )

    password_ok = secrets.compare_digest(
        credentials.password,
        ADMIN_PASSWORD
    )

    if not username_ok or not password_ok:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    token = secrets.token_urlsafe(32)

    admin_sessions[token] = (
        time.time() + ADMIN_SESSION_DURATION
    )

    return {
        "authenticated": True,
        "token": token,
        "expires_in": ADMIN_SESSION_DURATION
    }


@app.get("/api/admin/session")
def admin_session(
    _: bool = Depends(require_admin)
):
    return {
        "authenticated": True
    }


@app.post("/api/admin/logout")
def admin_logout(
    authorization: str = Header(default="")
):

    if authorization.startswith("Bearer "):

        token = authorization.replace(
            "Bearer ",
            "",
            1
        ).strip()

        admin_sessions.pop(token, None)

    return {
        "authenticated": False
    }
def clamp01(value):
    return max(0.0, min(1.0, float(value)))


def calculate_manual_risk(
    original_cost,
    revised_cost,
    expenditure,
    physical_progress,
    previous_progress=None
):

    original_cost = max(
        float(original_cost or 0),
        0
    )

    revised_cost = max(
        float(revised_cost or 0),
        0
    )

    expenditure = max(
        float(expenditure or 0),
        0
    )

    physical_progress = max(
        0,
        min(
            100,
            float(physical_progress or 0)
        )
    )


    # --------------------------------------------------------
    # Cost escalation
    # --------------------------------------------------------

    if original_cost > 0 and revised_cost > 0:

        cost_escalation_pct = (
            (revised_cost - original_cost)
            / original_cost
        ) * 100

    else:

        cost_escalation_pct = 0


    # --------------------------------------------------------
    # Expenditure as percentage of original cost
    # --------------------------------------------------------

    if original_cost > 0:

        expenditure_pct_original = (
            expenditure /
            original_cost
        ) * 100

    else:

        expenditure_pct_original = 0


    # --------------------------------------------------------
    # Expenditure-progress gap
    # --------------------------------------------------------

    expenditure_progress_gap = (
        expenditure_pct_original
        -
        physical_progress
    )


    # --------------------------------------------------------
    # Recent progress change
    # --------------------------------------------------------

    if previous_progress is not None:

        progress_change_pp = (
            physical_progress
            -
            float(previous_progress)
        )

    else:

        progress_change_pp = 0


    # --------------------------------------------------------
    # Cost component
    # --------------------------------------------------------

    cost = (

        0.70
        *
        clamp01(
            max(
                cost_escalation_pct,
                0
            ) / 50.0
        )

        +

        0.30
        *
        clamp01(
            max(
                expenditure_progress_gap,
                0
            ) / 100.0
        )

    )


    # --------------------------------------------------------
    # Delay component
    # --------------------------------------------------------

    delay = (

        0.55
        *
        clamp01(
            max(
                expenditure_progress_gap,
                0
            ) / 100.0
        )

        +

        0.25
        *
        clamp01(
            max(
                -progress_change_pp,
                0
            ) / 20.0
        )

        +

        0.20
        *
        clamp01(
            max(
                100 - physical_progress,
                0
            ) / 100.0
        )

    )


    # --------------------------------------------------------
    # Recent deterioration indicators
    # --------------------------------------------------------

    trend = (

        0.60
        *
        clamp01(
            max(
                -progress_change_pp,
                0
            ) / 20.0
        )

        +

        0.40
        *
        clamp01(
            max(
                cost_escalation_pct,
                0
            ) / 100.0
        )

    )


    # --------------------------------------------------------
    # Overall score
    # --------------------------------------------------------

    overall_risk_score = (

        100
        *
        (
            0.45 * cost
            +
            0.45 * delay
            +
            0.10 * trend
        )

    )


    # --------------------------------------------------------
    # Risk level
    # --------------------------------------------------------

    if overall_risk_score >= 70:

        risk_level = "High"

    elif overall_risk_score >= 40:

        risk_level = "Medium"

    else:

        risk_level = "Low"


    return {

        "cost_escalation_pct":
            cost_escalation_pct,

        "expenditure_pct_original":
            expenditure_pct_original,

        "expenditure_progress_gap":
            expenditure_progress_gap,

        "progress_change_pp":
            progress_change_pp,

        "cost_component":
            clamp01(cost),

        "delay_component":
            clamp01(delay),

        "trend_component":
            clamp01(trend),

        "overall_risk_score":
            overall_risk_score,

        "risk_level":
            risk_level

    }
    # ============================================================
# ADMIN PROJECT MANAGEMENT
# ============================================================

@app.post("/api/admin/projects")
def admin_add_or_update_project(
    project: AdminProjectRequest,
    _: bool = Depends(require_admin)
):

    conn = db()

    try:

        # ----------------------------------------------------
        # Check whether project already exists
        # ----------------------------------------------------

        existing = conn.execute(
            """
            SELECT
                physical_progress_pct
            FROM projects_latest
            WHERE project_id = ?
            """,
            (project.project_id,)
        ).fetchone()


        previous_progress = (
            existing["physical_progress_pct"]
            if existing
            else None
        )


        # ----------------------------------------------------
        # Calculate derived intelligence
        # ----------------------------------------------------

        risk = calculate_manual_risk(

            project.original_cost_cr,

            project.revised_cost_cr,

            project.expenditure_cr,

            project.physical_progress_pct,

            previous_progress

        )


        # ----------------------------------------------------
        # Priority
        # ----------------------------------------------------

        priority_score = (
            risk["overall_risk_score"]
        )


        if priority_score >= 70:

            priority = "High"

        elif priority_score >= 40:

            priority = "Medium"

        else:

            priority = "Low"


        # ----------------------------------------------------
        # Key risk drivers
        # ----------------------------------------------------

        drivers = []


        if risk["cost_escalation_pct"] > 5:

            drivers.append(
                "Existing cost escalation"
            )


        if risk["expenditure_progress_gap"] > 10:

            drivers.append(
                "High expenditure-progress gap"
            )


        if risk["progress_change_pp"] < 0:

            drivers.append(
                "Recent progress deterioration"
            )


        if project.physical_progress_pct < 30:

            drivers.append(
                "Low physical progress"
            )


        if not drivers:

            drivers.append(
                "No major rule-based risk driver"
            )


        key_risk_drivers = "; ".join(
            drivers[:3]
        )


        # ----------------------------------------------------
        # Trajectory
        # ----------------------------------------------------

        if (
            previous_progress is not None
            and risk["progress_change_pp"] < -1
        ):

            trajectory = "Worsening"

        else:

            trajectory = "Stable/Improving"


        # ----------------------------------------------------
        # Insert / update
        # ----------------------------------------------------

        conn.execute(
    """
    INSERT INTO projects_latest (

        project_id,
        project_name,
        agency,
        state,
        report_month,

        sector,
        line_ministry,

        original_date_of_commissioning,
        revised_date_of_commissioning,
        sanction_date,

        original_cost_cr,
        revised_cost_cr,
        expenditure_cr,
        physical_progress_pct,

        cost_escalation_pct,
        expenditure_pct_original,
        expenditure_progress_gap,
        progress_change_pp,

        cost_component,
        delay_component,
        trend_component,

        overall_risk_score,
        risk_level,
        trajectory,

        priority_score,
        priority,
        key_risk_drivers,

        ml_deterioration_probability

    )

    VALUES (

        ?, ?, ?, NULL, ?,

        ?, ?,

        ?, ?, ?,

        ?, ?, ?, ?,

        ?, ?, ?, ?,

        ?, ?, ?,

        ?, ?, ?,

        ?, ?, ?,

        NULL

    )

    ON CONFLICT(project_id)
    DO UPDATE SET

        project_name =
            excluded.project_name,

        agency =
            excluded.agency,

        report_month =
            excluded.report_month,

        sector =
            excluded.sector,

        line_ministry =
            excluded.line_ministry,

        original_date_of_commissioning =
            CASE
                WHEN excluded.original_date_of_commissioning != ''
                THEN excluded.original_date_of_commissioning
                ELSE projects_latest.original_date_of_commissioning
            END,

        revised_date_of_commissioning =
            CASE
                WHEN excluded.revised_date_of_commissioning != ''
                THEN excluded.revised_date_of_commissioning
                ELSE projects_latest.revised_date_of_commissioning
            END,

        sanction_date =
            CASE
                WHEN excluded.sanction_date != ''
                THEN excluded.sanction_date
                ELSE projects_latest.sanction_date
            END,

        original_cost_cr =
            excluded.original_cost_cr,

        revised_cost_cr =
            excluded.revised_cost_cr,

        expenditure_cr =
            excluded.expenditure_cr,

        physical_progress_pct =
            excluded.physical_progress_pct,

        cost_escalation_pct =
            excluded.cost_escalation_pct,

        expenditure_pct_original =
            excluded.expenditure_pct_original,

        expenditure_progress_gap =
            excluded.expenditure_progress_gap,

        progress_change_pp =
            excluded.progress_change_pp,

        cost_component =
            excluded.cost_component,

        delay_component =
            excluded.delay_component,

        trend_component =
            excluded.trend_component,

        overall_risk_score =
            excluded.overall_risk_score,

        risk_level =
            excluded.risk_level,

        trajectory =
            excluded.trajectory,

        priority_score =
            excluded.priority_score,

        priority =
            excluded.priority,

        key_risk_drivers =
            excluded.key_risk_drivers

    """,

    (

        project.project_id,
        project.project_name,
        project.agency,
        project.report_month,

        project.sector,
        project.line_ministry,

        project.original_date_of_commissioning,
        project.revised_date_of_commissioning,
        project.sanction_date,

        project.original_cost_cr,
        project.revised_cost_cr,
        project.expenditure_cr,
        project.physical_progress_pct,

        risk["cost_escalation_pct"],
        risk["expenditure_pct_original"],
        risk["expenditure_progress_gap"],
        risk["progress_change_pp"],

        risk["cost_component"],
        risk["delay_component"],
        risk["trend_component"],

        risk["overall_risk_score"],
        risk["risk_level"],
        trajectory,

        priority_score,
        priority,
        key_risk_drivers

    )
)


        conn.commit()


        action = (
            "updated"
            if existing
            else "created"
        )


        return {

            "success": True,

            "action": action,

            "project_id":
                project.project_id,

            "risk_score":
                round(
                    risk["overall_risk_score"],
                    2
                ),

            "risk_level":
                risk["risk_level"],

            "priority":
                priority

        }


    except sqlite3.IntegrityError as error:

        conn.rollback()

        raise HTTPException(
            status_code=400,
            detail=f"Project could not be saved: {error}"
        )


    except Exception as error:

        conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Project save failed: {error}"
        )


    finally:

        conn.close()


# ============================================================
# ADMIN DELETE PROJECT
# ============================================================

@app.delete("/api/admin/projects/{project_id}")
def admin_delete_project(
    project_id: int,
    _: bool = Depends(require_admin)
):
    conn = db()
    try:
        existing = conn.execute(
            """
            SELECT project_id, project_name
            FROM projects_latest
            WHERE project_id = ?
            """,
            (project_id,)
        ).fetchone()

        if not existing:
            raise HTTPException(
                status_code=404,
                detail=f"Project with ID {project_id} not found."
            )

        name = existing["project_name"]

        conn.execute(
            "DELETE FROM projects_latest WHERE project_id = ?",
            (project_id,)
        )
        conn.execute(
            "DELETE FROM project_trajectory WHERE project_id = ?",
            (project_id,)
        )
        conn.commit()

        globals().get("_shap_cache", {}).pop(project_id, None)

        return {
            "success": True,
            "message": f"Project {project_id} ('{name}') was permanently deleted.",
            "project_id": project_id
        }
    except HTTPException:
        raise
    except Exception as error:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Project deletion failed: {error}"
        )
    finally:
        conn.close()


# ============================================================
# ADMIN PROJECT DATA UPLOAD
# ============================================================

def infer_report_month_from_filename(filename: str, df=None):
    """
    Infer YYYY-MM from:
    1. Month name + year in filename (e.g. Projects_Report_July2026.xlsx, August_2025.csv)
    2. YYYY-MM or YYYY_MM in filename (e.g. 2026-08, 2026_08)
    3. Report Month column in the dataframe if present
    4. Default to current year-month
    """

    import re
    from datetime import datetime

    name = filename.lower()

    months = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    for month_name, month_number in months.items():

        match = re.search(
            rf"{month_name}[_\-\s]?(\d{{4}})",
            name
        )

        if match:
            year = int(match.group(1))

            if 2000 <= year <= 2100:
                return f"{year:04d}-{month_number:02d}"

    # Check for YYYY-MM or YYYY_MM pattern in filename
    ym_match = re.search(r"(20\d{2})[_\-\.](0[1-9]|1[0-2])", name)
    if ym_match:
        return f"{ym_match.group(1)}-{ym_match.group(2)}"

    # Check dataframe columns if provided
    if df is not None and not df.empty:
        col = find_column(df, ["Report Month", "Month", "ReportMonth", "report_month"])
        if col:
            first_val = str(df[col].dropna().iloc[0] if not df[col].dropna().empty else "").strip()
            m = re.search(r"(20\d{2})[_\-\.](0[1-9]|1[0-2])", first_val)
            if m:
                return f"{m.group(1)}-{m.group(2)}"

    # Graceful fallback to current month
    return datetime.now().strftime("%Y-%m")


def clean_column_name(column):
    """
    Normalize PAIMANA / Excel / CSV column names.
    """
    return (
        str(column)
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("_", " ")
        .strip()
        .lower()
    )


def find_column(df, possible_names):
    """
    Find a dataframe column using normalized names.
    """
    normalized = {
        clean_column_name(col): col
        for col in df.columns
    }

    for name in possible_names:
        key = clean_column_name(name)

        if key in normalized:
            return normalized[key]

    return None


def safe_float(value, default=0.0):
    """
    Convert Excel values into safe numeric values.
    """
    if pd.isna(value):
        return default

    if isinstance(value, str):
        value = (
            value
            .replace(",", "")
            .replace("₹", "")
            .replace("%", "")
            .strip()
        )

        if value == "":
            return default

    try:
        return float(value)
    except Exception:
        return default


def safe_string(value):
    """
    Convert Excel values into clean strings.
    """
    if pd.isna(value):
        return ""

    return str(value).strip()


@app.post("/api/admin/upload")
async def admin_upload_project_data(
    file: UploadFile = File(...),
    _: bool = Depends(require_admin)
):

    # --------------------------------------------------------
    # Validate file
    # --------------------------------------------------------

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file selected."
        )

    filename = file.filename.lower()

    allowed_extensions = (
        ".xlsx",
        ".xls",
        ".csv"
    )

    if not filename.endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail="Only XLSX, XLS or CSV files are supported."
        )

    # --------------------------------------------------------
    # Read uploaded file
    # --------------------------------------------------------

    try:

        contents = await file.read()

        if filename.endswith(".csv"):

            from io import BytesIO

            df = pd.read_csv(
                BytesIO(contents)
            )

        else:

            from io import BytesIO

            # An Excel file might have headers at row 2 (PAIMANA format)
            # or row 0 / 1 (standard user export)
            df = None
            last_err = None
            for h in [2, 0, 1]:
                try:
                    candidate = pd.read_excel(BytesIO(contents), sheet_name=0, header=h)
                    candidate_cols = [clean_column_name(c) for c in candidate.columns]
                    if any(key in candidate_cols for key in ["project code", "project id", "projectid", "project name", "name"]):
                        df = candidate
                        break
                except Exception as err:
                    last_err = err

            if df is None:
                try:
                    df = pd.read_excel(BytesIO(contents), sheet_name=0, header=0)
                except Exception:
                    if last_err:
                        raise last_err
                    raise

    except Exception as error:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read uploaded file: {error}"
        )

    if df is None or df.empty:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file contains no project rows."
        )

    # --------------------------------------------------------
    # Read report month
    # --------------------------------------------------------

    report_month = infer_report_month_from_filename(
        file.filename,
        df
    )

    # --------------------------------------------------------
    # Identify columns
    # --------------------------------------------------------

    project_id_col = find_column(
        df,
        [
            "Project Code",
            "Project ID",
            "Project Id",
            "ProjectID",
            "project_id",
            "id",
            "code"
        ]
    )

    project_name_col = find_column(
        df,
        [
            "Project Name",
            "ProjectName",
            "project_name",
            "name",
            "project"
        ]
    )

    sector_col = find_column(
        df,
        [
            "Sector Name",
            "Sector",
            "SectorName",
            "sector"
        ]
    )

    ministry_col = find_column(
        df,
        [
            "Line Ministry",
            "Ministry",
            "LineMinistry",
            "line_ministry"
        ]
    )

    agency_col = find_column(
        df,
        [
            "Implementing Agency",
            "Agency",
            "ImplementingAgency",
            "implementing_agency"
        ]
    )

    original_cost_col = find_column(
        df,
        [
            "Original Cost (in cr.)",
            "Original Cost (in cr)",
            "Original Cost",
            "original_cost",
            "original_cost_cr",
            "Cost"
        ]
    )

    revised_cost_col = find_column(
        df,
        [
            "Revised Cost (in cr.)",
            "Revised Cost (in cr)",
            "Revised Cost",
            "revised_cost",
            "revised_cost_cr"
        ]
    )

    expenditure_col = find_column(
        df,
        [
            "Expenditure (in cr.)",
            "Expenditure (in cr)",
            "Expenditure",
            "expenditure",
            "expenditure_cr"
        ]
    )

    progress_col = find_column(
        df,
        [
            "Physical Progress (in %)",
            "Physical Progress (%)",
            "Physical Progress",
            "physical_progress",
            "physical_progress_pct",
            "Progress (%)",
            "Progress"
        ]
    )

    original_doc_col = find_column(
        df,
        [
            "Original Date of Commissioning",
            "Original Date of Commissioning ",
            "original_doc",
            "original doc"
        ]
    )

    revised_doc_col = find_column(
        df,
        [
            "Revised Date of Commissioning",
            "Revised Date of Commissioning ",
            "revised_doc",
            "revised doc"
        ]
    )

    sanction_col = find_column(
        df,
        [
            "Sanction Date",
            "sanction_date",
            "sanction date"
        ]
    )

    # --------------------------------------------------------
    # Required columns
    # --------------------------------------------------------

    missing = []

    if project_id_col is None:
        missing.append("Project Code")

    if project_name_col is None:
        missing.append("Project Name")

    if original_cost_col is None:
        missing.append("Original Cost")

    if progress_col is None:
        missing.append("Physical Progress")

    if missing:

        raise HTTPException(
            status_code=400,
            detail=(
                "Required columns missing: "
                + ", ".join(missing)
            )
        )

    # --------------------------------------------------------
    # Process rows
    # --------------------------------------------------------

    conn = db()

    processed = 0
    skipped = 0
    created = 0
    updated = 0

    errors = []

    try:

        for index, row in df.iterrows():

            # ------------------------------------------------
            # Project ID
            # ------------------------------------------------

            raw_project_id = row[project_id_col]

            if pd.isna(raw_project_id):
                skipped += 1
                continue

            try:

                # Excel can sometimes read IDs as floats.
                project_id = int(float(raw_project_id))

            except Exception:

                skipped += 1

                if len(errors) < 10:
                    errors.append(
                        f"Row {index + 2}: invalid Project Code"
                    )

                continue

            # ------------------------------------------------
            # Basic project information
            # ------------------------------------------------

            project_name = safe_string(
                row[project_name_col]
            )

            if not project_name:
                skipped += 1
                continue

            sector = (
                safe_string(row[sector_col])
                if sector_col
                else ""
            )

            line_ministry = (
                safe_string(row[ministry_col])
                if ministry_col
                else ""
            )

            agency = (
                safe_string(row[agency_col])
                if agency_col
                else ""
            )

            # ------------------------------------------------
            # Financial / physical data
            # ------------------------------------------------

            original_cost = safe_float(
                row[original_cost_col]
            )

            revised_cost = (
                safe_float(row[revised_cost_col])
                if revised_cost_col
                else 0
            )

            expenditure = (
                safe_float(row[expenditure_col])
                if expenditure_col
                else 0
            )

            physical_progress = (
                safe_float(row[progress_col])
            )

            physical_progress = max(
                0,
                min(
                    100,
                    physical_progress
                )
            )

            # ------------------------------------------------
            # Dates
            # ------------------------------------------------

            original_doc = (
                safe_string(row[original_doc_col])
                if original_doc_col
                else ""
            )

            revised_doc = (
                safe_string(row[revised_doc_col])
                if revised_doc_col
                else ""
            )

            sanction_date = (
                safe_string(row[sanction_col])
                if sanction_col
                else ""
            )

            # ------------------------------------------------
            # Existing project
            # ------------------------------------------------

            existing = conn.execute(
                """
                SELECT
                    physical_progress_pct,
                    original_date_of_commissioning,
                    revised_date_of_commissioning,
                    sanction_date
                FROM projects_latest
                WHERE project_id = ?
                """,
                (project_id,)
            ).fetchone()

            previous_progress = (
                existing["physical_progress_pct"]
                if existing
                else None
            )

            # Preserve existing dates when the upload
            # doesn't contain usable values.

            if existing:

                if not original_doc:
                    original_doc = (
                        existing[
                            "original_date_of_commissioning"
                        ]
                        or ""
                    )

                if not revised_doc:
                    revised_doc = (
                        existing[
                            "revised_date_of_commissioning"
                        ]
                        or ""
                    )

                if not sanction_date:
                    sanction_date = (
                        existing[
                            "sanction_date"
                        ]
                        or ""
                    )

            # ------------------------------------------------
            # Calculate TriNetra risk
            # ------------------------------------------------

            risk = calculate_manual_risk(
                original_cost,
                revised_cost,
                expenditure,
                physical_progress,
                previous_progress
            )

            priority_score = (
                risk["overall_risk_score"]
            )

            if priority_score >= 70:
                priority = "High"

            elif priority_score >= 40:
                priority = "Medium"

            else:
                priority = "Low"

            # ------------------------------------------------
            # Risk drivers
            # ------------------------------------------------

            drivers = []

            if risk["cost_escalation_pct"] > 5:

                drivers.append(
                    "Existing cost escalation"
                )

            if risk["expenditure_progress_gap"] > 10:

                drivers.append(
                    "High expenditure-progress gap"
                )

            if risk["progress_change_pp"] < 0:

                drivers.append(
                    "Recent progress deterioration"
                )

            if physical_progress < 30:

                drivers.append(
                    "Low physical progress"
                )

            if not drivers:

                drivers.append(
                    "No major rule-based risk driver"
                )

            key_risk_drivers = "; ".join(
                drivers[:3]
            )

            # ------------------------------------------------
            # Trajectory
            # ------------------------------------------------

            if (
                previous_progress is not None
                and risk["progress_change_pp"] < -1
            ):

                trajectory = "Worsening"

            else:

                trajectory = "Stable/Improving"

            # ------------------------------------------------
            # Insert / update
            # ------------------------------------------------

            conn.execute(
                """
                INSERT INTO projects_latest (

                    project_id,
                    project_name,
                    agency,
                    state,
                    report_month,

                    sector,
                    line_ministry,

                    original_date_of_commissioning,
                    revised_date_of_commissioning,
                    sanction_date,

                    original_cost_cr,
                    revised_cost_cr,
                    expenditure_cr,
                    physical_progress_pct,

                    cost_escalation_pct,
                    expenditure_pct_original,
                    expenditure_progress_gap,
                    progress_change_pp,

                    cost_component,
                    delay_component,
                    trend_component,

                    overall_risk_score,
                    risk_level,
                    trajectory,

                    priority_score,
                    priority,
                    key_risk_drivers,

                    ml_deterioration_probability

                )

                VALUES (

                    ?, ?, ?, NULL, ?,

                    ?, ?,

                    ?, ?, ?,

                    ?, ?, ?, ?,

                    ?, ?, ?, ?,

                    ?, ?, ?,

                    ?, ?, ?,

                    ?, ?, ?,

                    NULL

                )

                ON CONFLICT(project_id)
                DO UPDATE SET

                    project_name =
                        excluded.project_name,

                    agency =
                        excluded.agency,

                    report_month =
                        excluded.report_month,

                    sector =
                        excluded.sector,

                    line_ministry =
                        excluded.line_ministry,

                    original_date_of_commissioning =
                        CASE
                            WHEN excluded.original_date_of_commissioning != ''
                            THEN excluded.original_date_of_commissioning
                            ELSE projects_latest.original_date_of_commissioning
                        END,

                    revised_date_of_commissioning =
                        CASE
                            WHEN excluded.revised_date_of_commissioning != ''
                            THEN excluded.revised_date_of_commissioning
                            ELSE projects_latest.revised_date_of_commissioning
                        END,

                    sanction_date =
                        CASE
                            WHEN excluded.sanction_date != ''
                            THEN excluded.sanction_date
                            ELSE projects_latest.sanction_date
                        END,

                    original_cost_cr =
                        excluded.original_cost_cr,

                    revised_cost_cr =
                        excluded.revised_cost_cr,

                    expenditure_cr =
                        excluded.expenditure_cr,

                    physical_progress_pct =
                        excluded.physical_progress_pct,

                    cost_escalation_pct =
                        excluded.cost_escalation_pct,

                    expenditure_pct_original =
                        excluded.expenditure_pct_original,

                    expenditure_progress_gap =
                        excluded.expenditure_progress_gap,

                    progress_change_pp =
                        excluded.progress_change_pp,

                    cost_component =
                        excluded.cost_component,

                    delay_component =
                        excluded.delay_component,

                    trend_component =
                        excluded.trend_component,

                    overall_risk_score =
                        excluded.overall_risk_score,

                    risk_level =
                        excluded.risk_level,

                    trajectory =
                        excluded.trajectory,

                    priority_score =
                        excluded.priority_score,

                    priority =
                        excluded.priority,

                    key_risk_drivers =
                        excluded.key_risk_drivers

                """,

                (

                    project_id,
                    project_name,
                    agency,
                    report_month,

                    sector,
                    line_ministry,

                    original_doc,
                    revised_doc,
                    sanction_date,

                    original_cost,
                    revised_cost,
                    expenditure,
                    physical_progress,

                    risk["cost_escalation_pct"],
                    risk["expenditure_pct_original"],
                    risk["expenditure_progress_gap"],
                    risk["progress_change_pp"],

                    risk["cost_component"],
                    risk["delay_component"],
                    risk["trend_component"],

                    risk["overall_risk_score"],
                    risk["risk_level"],
                    trajectory,

                    priority_score,
                    priority,
                    key_risk_drivers

                )
            )

            if existing:
                updated += 1
            else:
                created += 1

            processed += 1

        conn.commit()

    except Exception as error:

        conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Upload processing failed: {error}"
        )

    finally:

        conn.close()

    return {
        "success": True,
        "filename": file.filename,
        "report_month": report_month,
        "rows_received": len(df),
        "rows_processed": processed,
        "rows_skipped": skipped,
        "projects_created": created,
        "projects_updated": updated,
        "errors": errors
    }
app.mount(
    "/static",
    StaticFiles(directory=STATIC),
    name="static"
)


# ============================================================
# DATABASE
# ============================================================

def db():
    """Open a SQLite connection using the project-root database."""
    if not DB.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Database not found: {DB}"
        )

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():
    return FileResponse(STATIC / "landing.html")

@app.get("/projects")
def projects_page():
    return FileResponse(STATIC / "projects.html")

@app.get("/dashboard")
def dashboard_page():
    return FileResponse(STATIC / "dashboard.html")

# ============================================================
# DASHBOARD DATA
# ============================================================
from collections import defaultdict

@app.get("/api/dashboard_data")
def get_dashboard_data(
    sector: str = "",
    ministry: str = "",
    cost_bracket: str = "",
    month: str = ""
):
    conn = db()
    query = "SELECT * FROM projects_latest WHERE 1=1"
    params = []
    
    if sector and sector != "All":
        query += " AND sector = ?"
        params.append(sector)
    
    if ministry and ministry != "All":
        query += " AND line_ministry = ?"
        params.append(ministry)
        
    if month and month != "All":
        query += " AND report_month = ?"
        params.append(month)

    if cost_bracket and cost_bracket != "All":
        if cost_bracket == "< 500":
            query += " AND original_cost_cr < 500"
        elif cost_bracket == "500-1000":
            query += " AND original_cost_cr >= 500 AND original_cost_cr < 1000"
        elif cost_bracket == "1000-2000":
            query += " AND original_cost_cr >= 1000 AND original_cost_cr < 2000"
        elif cost_bracket == "> 2000":
            query += " AND original_cost_cr >= 2000"

    rows = conn.execute(query, params).fetchall()
    
    total_projects = len(rows)
    total_original_cost = sum(r["original_cost_cr"] or 0 for r in rows)
    total_revised_cost = sum(r["revised_cost_cr"] or 0 for r in rows)
    total_expenditure = sum(r["expenditure_cr"] or 0 for r in rows)
    
    sector_dist_count = defaultdict(int)
    progress_dist = {"< 20": 0, "20-40": 0, "40-60": 0, "60-80": 0, ">= 80": 0}
    risk_dist = {"High": 0, "Medium": 0, "Low": 0}

    for r in rows:
        sec = r["sector"] if r["sector"] else "Others"
        sector_dist_count[sec] += 1

        prog = r["physical_progress_pct"] or 0
        if prog < 20: progress_dist["< 20"] += 1
        elif prog < 40: progress_dist["20-40"] += 1
        elif prog < 60: progress_dist["40-60"] += 1
        elif prog < 80: progress_dist["60-80"] += 1
        else: progress_dist[">= 80"] += 1

        rl = r["risk_level"] or "Low"
        if rl in risk_dist:
            risk_dist[rl] += 1

    # Top 10 projects by cost escalation
    delayed = sorted(
        [r for r in rows if r["cost_escalation_pct"] is not None],
        key=lambda r: r["cost_escalation_pct"],
        reverse=True
    )[:10]
    top_delayed = [
        {
            "project_name": r["project_name"],
            "sector": r["sector"] or "—",
            "state": r["state"] or "—",
            "original_cost_cr": round(r["original_cost_cr"] or 0, 1),
            "revised_cost_cr": round(r["revised_cost_cr"] or 0, 1),
            "cost_escalation_pct": round(r["cost_escalation_pct"] or 0, 1),
            "physical_progress_pct": round(r["physical_progress_pct"] or 0, 1),
            "risk_level": r["risk_level"] or "—",
        }
        for r in delayed
    ]

    return {
        "kpi": {
            "project_count": total_projects,
            "original_cost": total_original_cost,
            "revised_cost": total_revised_cost,
            "expenditure": total_expenditure
        },
        "sector_dist_count": dict(sector_dist_count),
        "progress_dist": progress_dist,
        "risk_dist": risk_dist,
        "top_delayed": top_delayed
    }

# ============================================================
# SUMMARY
# ============================================================

@app.get("/api/summary")
def summary():
    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM projects_latest"
    ).fetchone()["n"]

    high = conn.execute(
        "SELECT COUNT(*) AS n FROM projects_latest "
        "WHERE risk_level='High'"
    ).fetchone()["n"]

    medium = conn.execute(
        "SELECT COUNT(*) AS n FROM projects_latest "
        "WHERE risk_level='Medium'"
    ).fetchone()["n"]

    low = conn.execute(
        "SELECT COUNT(*) AS n FROM projects_latest "
        "WHERE risk_level='Low'"
    ).fetchone()["n"]

    trajectory_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM project_trajectory"
    ).fetchone()["n"]

    latest_month = conn.execute(
        "SELECT MAX(report_month) AS m FROM projects_latest"
    ).fetchone()["m"]

    conn.close()

    return {
        "projects": total,
        "high": high,
        "medium": medium,
        "low": low,
        "trajectory_rows": trajectory_rows,
        "report_month": latest_month
    }


# ============================================================
# FILTERS
# ============================================================

@app.get("/api/filters")
def filters():
    conn = db()

    sectors = [
        row["sector"]
        for row in conn.execute(
            """
            SELECT DISTINCT sector
            FROM projects_latest
            WHERE sector IS NOT NULL
              AND TRIM(sector) <> ''
            ORDER BY sector
            """
        )
    ]

    agencies = [
        row["agency"]
        for row in conn.execute(
            """
            SELECT DISTINCT agency
            FROM projects_latest
            WHERE agency IS NOT NULL
              AND TRIM(agency) <> ''
            ORDER BY agency
            """
        )
    ]

    ministries = [
        row["line_ministry"]
        for row in conn.execute(
            """
            SELECT DISTINCT line_ministry
            FROM projects_latest
            WHERE line_ministry IS NOT NULL
              AND TRIM(line_ministry) <> ''
            ORDER BY line_ministry
            """
        )
    ]

    conn.close()

    return {
        "sectors": sectors,
        "agencies": agencies,
        "ministries": ministries
    }


# ============================================================
# PROJECT LIST
# ============================================================

@app.get("/api/projects")
def projects(
    search: str = "",
    risk: str = "",
    trajectory: str = "",
    priority: str = "",
    sector: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100)
):
    where = []
    params = []

    if search:
        where.append(
            """
            (
                project_name LIKE ?
                OR CAST(project_id AS TEXT) LIKE ?
                OR agency LIKE ?
            )
            """
        )

        q = f"%{search}%"
        params.extend([q, q, q])

    filters_to_apply = [
        ("risk_level", risk),
        ("trajectory", trajectory),
        ("priority", priority),
        ("sector", sector),
    ]

    for field, value in filters_to_apply:
        if value:
            where.append(f"{field} = ?")
            params.append(value)

    clause = ""

    if where:
        clause = " WHERE " + " AND ".join(where)

    conn = db()

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM projects_latest
        {clause}
        """,
        params
    ).fetchone()["n"]

    offset = (page - 1) * page_size

    rows = conn.execute(
        f"""
        SELECT *
        FROM projects_latest
        {clause}
        ORDER BY overall_risk_score DESC,
                 original_cost_cr DESC
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset]
    ).fetchall()

    conn.close()

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "items": [dict(row) for row in rows]
    }


COST_MODEL_PATH = ROOT / "models" / "cost_overrun_model.pkl"
TIME_MODEL_PATH = ROOT / "models" / "time_overrun_model.pkl"

_cost_model = None
_time_model = None

def load_overrun_models():
    global _cost_model, _time_model
    if _cost_model is None and COST_MODEL_PATH.exists():
        with open(COST_MODEL_PATH, "rb") as f:
            _cost_model = pickle.load(f)
    if _time_model is None and TIME_MODEL_PATH.exists():
        with open(TIME_MODEL_PATH, "rb") as f:
            _time_model = pickle.load(f)

# ============================================================
# SINGLE PROJECT
# ============================================================

@app.get("/api/projects/{project_id}")
def project(project_id: int):
    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM projects_latest
        WHERE project_id = ?
        """,
        (project_id,)
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )
        
    project_dict = dict(row)
    
    # Generate predictive metrics
    load_overrun_models()
    if _cost_model and _time_model:
        features = _cost_model["features"]
        df = pd.DataFrame([{f: project_dict.get(f, 0) or 0 for f in features}])
        
        predicted_cost = _cost_model["model"].predict(df)[0]
        predicted_time = _time_model["model"].predict(df)[0]
        
        project_dict["predicted_cost_overrun_cr"] = round(float(predicted_cost), 2)
        project_dict["predicted_time_overrun_months"] = round(float(predicted_time), 1)

    return project_dict


# ============================================================
# PROJECT TRAJECTORY
# ============================================================

@app.get("/api/projects/{project_id}/trajectory")
def trajectory(project_id: int):
    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM project_trajectory
        WHERE project_id = ?
        ORDER BY report_month
        """,
        (project_id,)
    ).fetchall()

    conn.close()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Trajectory not found"
        )

    return [dict(row) for row in rows]


# ============================================================
# PORTFOLIO RISK DISTRIBUTION
# ============================================================

@app.get("/api/portfolio/risk-distribution")
def risk_distribution():
    conn = db()

    rows = conn.execute(
        """
        SELECT risk_level, COUNT(*) AS n
        FROM projects_latest
        GROUP BY risk_level
        ORDER BY risk_level
        """
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# ============================================================
# SHAP / EXPLAINABLE AI
# ============================================================

SHAP_FEATURES = [
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

FEATURE_LABELS = {
    "original_cost_cr": "Original project cost",
    "revised_cost_cr": "Revised project cost",
    "expenditure_cr": "Cumulative expenditure",
    "physical_progress_pct": "Physical progress",
    "cost_escalation_pct": "Cost escalation",
    "expenditure_pct_original": "Expenditure / original cost",
    "expenditure_progress_gap": "Expenditure–progress gap",
    "progress_change_pp": "Recent progress change",
    "expenditure_change_cr": "Recent expenditure change",
    "cost_escalation_change_pp": "Recent cost escalation change",
}


# Always define these, even if model loading fails.
_shap_model = None
_shap_explainer = None

# Project-ID -> already calculated explanation.
_shap_cache = {}

# Prevent two browser requests for the same new project from
# calculating SHAP simultaneously.
_shap_lock = threading.Lock()


def _load_shap_model():
    global _shap_model
    global _shap_explainer

    if not MODEL_PATH.exists():
        print(f"SHAP model not found: {MODEL_PATH}")
        return

    try:
        model_data = joblib.load(MODEL_PATH)

        if isinstance(model_data, dict):
            _shap_model = model_data["model"]
        else:
            _shap_model = model_data

        # Build the TreeExplainer only once.
        _shap_explainer = shap.TreeExplainer(_shap_model)

        print("SHAP model loaded.")

    except Exception as exc:
        _shap_model = None
        _shap_explainer = None
        print(f"SHAP initialization failed: {exc}")


_load_shap_model()


def _calculate_shap_values(X):
    """
    Calculate SHAP values for one binary-classification row.

    check_additivity=False avoids an unnecessary additional
    consistency calculation and is appropriate here because
    this endpoint is being used for explanation/ranking rather
    than numerical model auditing.
    """

    raw_shap = _shap_explainer.shap_values(
        X,
        check_additivity=False
    )

    if isinstance(raw_shap, list):

        if len(raw_shap) == 2:
            values = np.asarray(raw_shap[1])[0]
        else:
            values = np.asarray(raw_shap[0])[0]

    else:

        shap_array = np.asarray(raw_shap)

        # Newer SHAP versions for binary classifiers:
        # (samples, features, classes)
        if shap_array.ndim == 3:
            values = shap_array[0, :, 1]

        # Older/common format:
        # (samples, features)
        elif shap_array.ndim == 2:
            values = shap_array[0]

        else:
            raise ValueError(
                f"Unexpected SHAP output shape: {shap_array.shape}"
            )

    values = np.asarray(values).reshape(-1)

    if len(values) != len(SHAP_FEATURES):
        raise ValueError(
            f"Expected {len(SHAP_FEATURES)} SHAP values, "
            f"received {len(values)}."
        )

    return values


@app.get("/api/projects/{project_id}/explanation")
def project_explanation(project_id: int):

    # --------------------------------------------------------
    # 1. FAST PATH: cached explanation
    # --------------------------------------------------------

    if project_id in _shap_cache:
        return _shap_cache[project_id]

    # --------------------------------------------------------
    # 2. Check model availability
    # --------------------------------------------------------

    if _shap_model is None or _shap_explainer is None:
        raise HTTPException(
            status_code=503,
            detail="SHAP model is not available."
        )

    # --------------------------------------------------------
    # 3. Load the latest trajectory row
    # --------------------------------------------------------

    conn = db()

    row = conn.execute(
        f"""
        SELECT
            project_id,
            project_name,
            report_month,
            {", ".join(SHAP_FEATURES)}
        FROM project_trajectory
        WHERE project_id = ?
        ORDER BY report_month DESC
        LIMIT 1
        """,
        (project_id,)
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Project trajectory not found."
        )

    # --------------------------------------------------------
    # 4. Prepare exactly one model row
    # --------------------------------------------------------

    data = dict(row)

    X = pd.DataFrame(
        [[data.get(feature) for feature in SHAP_FEATURES]],
        columns=SHAP_FEATURES
    )

    X = X.apply(
        pd.to_numeric,
        errors="coerce"
    )

    # Keep the same simple prototype behavior used previously.
    X = X.fillna(0)

    # --------------------------------------------------------
    # 5. Calculate prediction + SHAP under a lock
    # --------------------------------------------------------
    #
    # Another browser tab/request may arrive while the first
    # calculation is running. Re-check the cache after acquiring
    # the lock so we don't calculate the same project twice.

    with _shap_lock:

        if project_id in _shap_cache:
            return _shap_cache[project_id]

        probability = float(
            _shap_model.predict_proba(X)[0][1]
        )

        shap_values = _calculate_shap_values(X)

    # --------------------------------------------------------
    # 6. Build driver list
    # --------------------------------------------------------

    drivers = []

    for feature, shap_value, feature_value in zip(
        SHAP_FEATURES,
        shap_values,
        X.iloc[0].values
    ):

        drivers.append({
            "feature": feature,
            "label": FEATURE_LABELS.get(
                feature,
                feature
            ),
            "value": round(
                float(feature_value),
                4
            ),
            "impact": round(
                float(shap_value),
                6
            ),
            "direction": (
                "increases risk"
                if shap_value > 0
                else "reduces risk"
            ),
        })

    drivers.sort(
        key=lambda item: abs(item["impact"]),
        reverse=True
    )

    # Keep the UI concise.
    drivers = drivers[:6]

    # --------------------------------------------------------
    # 7. Final response
    # --------------------------------------------------------

    result = {
        "project_id": project_id,
        "project_name": data["project_name"],
        "report_month": data["report_month"],
        "ml_probability": round(
            probability,
            4
        ),
        "ml_probability_percent": round(
            probability * 100,
            2
        ),
        "drivers": drivers,
        "interpretation": (
            "These factors contributed to the model's "
            "predicted trajectory risk. They should not "
            "be interpreted as causal effects."
        ),
    }

    # --------------------------------------------------------
    # 8. Cache result
    # --------------------------------------------------------

    _shap_cache[project_id] = result

    return result


# ============================================================
# SHAP CACHE MANAGEMENT
# ============================================================

@app.get("/api/shap/status")
def shap_status():
    return {
        "model_loaded": _shap_model is not None,
        "explainer_loaded": _shap_explainer is not None,
        "cached_projects": len(_shap_cache),
    }


@app.delete("/api/shap/cache")
def clear_shap_cache():
    _shap_cache.clear()

    return {
        "status": "cleared"
    }
    # ============================================================
# HISTORICAL SIMILAR PROJECTS
# ============================================================

@app.get("/api/projects/{project_id}/similar")
def similar_projects(
    
    project_id: int,
    limit: int = Query(5, ge=1, le=10)
):

    conn = db()

    # --------------------------------------------------------
    # Current project
    # --------------------------------------------------------

    current = conn.execute(
        """
        SELECT
            project_id,
            project_name,
            original_cost_cr,
            revised_cost_cr,
            expenditure_cr,
            physical_progress_pct,
            cost_escalation_pct,
            expenditure_pct_original,
            expenditure_progress_gap,
            progress_change_pp
        FROM projects_latest
        WHERE project_id = ?
        """,
        (project_id,)
    ).fetchone()

    if not current:

        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Project not found."
        )


    # --------------------------------------------------------
    # Convert current project to numeric vector
    # --------------------------------------------------------

    features = [
        "original_cost_cr",
        "cost_escalation_pct",
        "physical_progress_pct",
        "expenditure_pct_original",
        "expenditure_progress_gap",
        "progress_change_pp"
    ]


    current_values = np.array(
        [
            float(current[f] or 0)
            for f in features
        ],
        dtype=float
    )


    # --------------------------------------------------------
    # Get candidate projects
    # --------------------------------------------------------

    candidates = conn.execute(
        """
        SELECT
            project_id,
            project_name,
            original_cost_cr,
            revised_cost_cr,
            expenditure_cr,
            physical_progress_pct,
            cost_escalation_pct,
            expenditure_pct_original,
            expenditure_progress_gap,
            progress_change_pp,
            risk_level,
            overall_risk_score,
            trajectory,
            priority
        FROM projects_latest
        WHERE project_id != ?
        """,
        (project_id,)
    ).fetchall()


    conn.close()


    # --------------------------------------------------------
    # Calculate similarity
    # --------------------------------------------------------

    results = []


    for row in candidates:

        try:

            values = np.array(
                [
                    float(row[f] or 0)
                    for f in features
                ],
                dtype=float
            )


            # ------------------------------------------------
            # Relative difference
            # ------------------------------------------------
            #
            # This prevents project cost from dominating
            # the similarity calculation.
            #

            denominator = (
                np.abs(current_values) +
                np.abs(values) +
                1e-6
            )


            relative_difference = (
                np.abs(
                    current_values -
                    values
                )
                /
                denominator
            )


            distance = np.mean(
                relative_difference
            )


            similarity = (
                1 /
                (1 + distance)
            ) * 100


            results.append({

                "project_id":
                    row["project_id"],

                "project_name":
                    row["project_name"],

                "original_cost_cr":
                    row["original_cost_cr"],

                "revised_cost_cr":
                    row["revised_cost_cr"],

                "expenditure_cr":
                    row["expenditure_cr"],

                "physical_progress_pct":
                    row["physical_progress_pct"],

                "cost_escalation_pct":
                    row["cost_escalation_pct"],

                "expenditure_pct_original":
                    row["expenditure_pct_original"],

                "expenditure_progress_gap":
                    row["expenditure_progress_gap"],

                "progress_change_pp":
                    row["progress_change_pp"],

                "risk_level":
                    row["risk_level"],

                "overall_risk_score":
                    row["overall_risk_score"],

                "trajectory":
                    row["trajectory"],

                "priority":
                    row["priority"],

                "similarity_score":
                    round(
                        float(similarity),
                        2
                    )

            })


        except Exception:

            continue


    # --------------------------------------------------------
    # Sort by similarity
    # --------------------------------------------------------

    results.sort(
        key=lambda x:
            x["similarity_score"],
        reverse=True
    )


    return {

        "project_id":
            project_id,

        "count":
            min(
                limit,
                len(results)
            ),

        "similar_projects":
            results[:limit]

    }

@app.get("/api/projects/{project_id}/report/pdf")
def download_project_pdf(project_id: int):

    conn = db()

    # --------------------------------------------------------
    # Project
    # --------------------------------------------------------

    project = conn.execute(
        """
        SELECT *
        FROM projects_latest
        WHERE project_id = ?
        """,
        (project_id,)
    ).fetchone()

    if not project:

        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Project not found."
        )

    project = dict(project)


    # --------------------------------------------------------
    # Trajectory
    # --------------------------------------------------------

    trajectory_rows = conn.execute(
        """
        SELECT *
        FROM project_trajectory
        WHERE project_id = ?
        ORDER BY report_month
        """,
        (project_id,)
    ).fetchall()

    trajectory_rows = [
        dict(row)
        for row in trajectory_rows
    ]


    conn.close()


    # --------------------------------------------------------
    # Similar projects
    # --------------------------------------------------------

    similar_data = similar_projects(
        project_id=project_id,
        limit=5
    )

    similar_rows = (
        similar_data.get(
            "similar_projects",
            []
        )
    )


    # --------------------------------------------------------
    # PDF setup
    # --------------------------------------------------------

    font_normal = "Helvetica"
    font_bold = "Helvetica-Bold"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm
    )


    styles = getSampleStyleSheet()


    title_style = ParagraphStyle(
        "TriNetraTitle",
        parent=styles["Title"],
        fontName=font_bold,
        fontSize=22,
        leading=26,
        alignment=TA_CENTER,
        spaceAfter=6
    )


    subtitle_style = ParagraphStyle(
        "TriNetraSubtitle",
        parent=styles["Normal"],
        fontName=font_normal,
        fontSize=9,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=16
    )

    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName=font_bold,
        fontSize=14,
        leading=18,
        spaceBefore=10,
        spaceAfter=8
    )

    normal_style = ParagraphStyle(
        "NormalSmall",
        parent=styles["Normal"],
        fontName=font_normal,
        fontSize=9,
        leading=12
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontName=font_normal,
        fontSize=8,
        leading=10
    )


    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    def value(
        key,
        default="—"
    ):

        result = project.get(key)

        if result is None or result == "":
            return default

        return result


    def money(
        key
    ):

        result = project.get(key)

        if result is None:
            return "—"

        try:

            return (
                f"₹{float(result):,.2f} Cr"
            )

        except Exception:

            return "—"


    def pct(
        key,
        decimals=1
    ):

        result = project.get(key)

        if result is None:
            return "—"

        try:

            return (
                f"{float(result):.{decimals}f}%"
            )

        except Exception:

            return "—"


    def text(value):

        if value is None:
            return "—"

        return str(value)


    # --------------------------------------------------------
    # Document
    # --------------------------------------------------------

    story = []


    story.append(
        Paragraph(
            "TriNetra",
            title_style
        )
    )


    story.append(
        Paragraph(
            "Integrated Project Monitoring & "
            "Predictive Intelligence",
            subtitle_style
        )
    )


    story.append(
        Paragraph(
            text(
                value(
                    "project_name"
                )
            ),
            heading_style
        )
    )


    story.append(
        Paragraph(
            f"Project ID: "
            f"{text(value('project_id'))}",
            normal_style
        )
    )


    story.append(
        Spacer(
            1,
            8
        )
    )


    # --------------------------------------------------------
    # Project Overview
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Project Overview",
            heading_style
        )
    )


    overview_data = [

        [
            "Agency",
            text(
                value("agency")
            )
        ],

        [
            "Line Ministry",
            text(
                value("line_ministry")
            )
        ],

        [
            "Sector",
            text(
                value("sector")
            )
        ],

        [
            "Report Month",
            text(
                value("report_month")
            )
        ],

        [
            "Original Cost",
            money("original_cost_cr")
        ],

        [
            "Revised Cost",
            money("revised_cost_cr")
        ]

    ]


    overview_table = Table(
        overview_data,
        colWidths=[
            45 * mm,
            125 * mm
        ]
    )


    overview_table.setStyle(
        TableStyle([

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor(
                    "#F2F4F7"
                )
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor(
                    "#D0D5DD"
                )
            ),

            (
                "FONTNAME",
                (0, 0),
                (-1, -1),
                font_normal
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                font_bold
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )

        ])
    )


    story.append(
        overview_table
    )


    # --------------------------------------------------------
    # Financial / Implementation
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Financial & Implementation Status",
            heading_style
        )
    )


    status_data = [

        [
            "Expenditure",
            money("expenditure_cr")
        ],

        [
            "Physical Progress",
            pct("physical_progress_pct")
        ],

        [
            "Cost Escalation",
            pct("cost_escalation_pct")
        ],

        [
            "Expenditure / Progress Gap",
            pct(
                "expenditure_progress_gap"
            )
        ]

    ]


    status_table = Table(
        status_data,
        colWidths=[
            70 * mm,
            100 * mm
        ]
    )


    status_table.setStyle(
        TableStyle([

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor(
                    "#F2F4F7"
                )
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor(
                    "#D0D5DD"
                )
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                font_bold
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )

        ])
    )


    story.append(
        status_table
    )


    # --------------------------------------------------------
    # Risk Assessment
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "TriNetra Risk Assessment",
            heading_style
        )
    )


    risk_data = [

        [
            "Overall Risk Score",
            text(
                value(
                    "overall_risk_score"
                )
            )
        ],

        [
            "Risk Level",
            text(
                value("risk_level")
            )
        ],

        [
            "Priority",
            text(
                value("priority")
            )
        ],

        [
            "Trajectory",
            text(
                value("trajectory")
            )
        ],

        [
            "ML Trajectory Risk",
            (
                f"{float(project['ml_deterioration_probability']) * 100:.1f}%"
                if project.get(
                    "ml_deterioration_probability"
                ) is not None
                else "—"
            )
        ]

    ]


    risk_table = Table(
        risk_data,
        colWidths=[
            70 * mm,
            100 * mm
        ]
    )


    risk_table.setStyle(
        TableStyle([

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor(
                    "#F2F4F7"
                )
            ),

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor(
                    "#D0D5DD"
                )
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                font_bold
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )

        ])
    )


    story.append(
        risk_table
    )


    # --------------------------------------------------------
    # Key Risk Drivers
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Key Risk Drivers",
            heading_style
        )
    )


    raw_drivers = (
        project.get(
            "key_risk_drivers"
        )
        or ""
    )


    if isinstance(
        raw_drivers,
        str
    ):

        drivers = [
            item.strip()
            for item in raw_drivers.split(";")
            if item.strip()
        ]

    else:

        drivers = []


    if drivers:

        driver_data = [
            [
                str(index + 1),
                driver
            ]
            for index, driver
            in enumerate(drivers)
        ]

    else:

        driver_data = [
            [
                "—",
                "No predefined drivers available."
            ]
        ]


    driver_table = Table(
        driver_data,
        colWidths=[
            12 * mm,
            158 * mm
        ]
    )


    driver_table.setStyle(
        TableStyle([

            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor(
                    "#D0D5DD"
                )
            ),

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor(
                    "#F2F4F7"
                )
            ),

            (
                "FONTSIZE",
                (0, 0),
                (-1, -1),
                8
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            )

        ])
    )


    story.append(
        driver_table
    )


    # --------------------------------------------------------
    # Historical Trajectory
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Project Trajectory",
            heading_style
        )
    )


    if trajectory_rows:

        trajectory_data = [

            [
                "Month",
                "Progress",
                "Expenditure",
                "Cost Esc.",
                "Trajectory"
            ]

        ]


        for row in trajectory_rows:

            trajectory_data.append([

                text(
                    row.get(
                        "report_month"
                    )
                ),

                (
                    f"{float(row.get('physical_progress_pct') or 0):.1f}%"
                ),

                (
                    f"₹{float(row.get('expenditure_cr') or 0):,.2f} Cr"
                ),

                (
                    f"{float(row.get('cost_escalation_pct') or 0):.1f}%"
                ),

                text(
                    row.get(
                        "trajectory"
                    )
                )

            ])


        trajectory_table = Table(
            trajectory_data,
            repeatRows=1,
            colWidths=[
                28 * mm,
                25 * mm,
                38 * mm,
                28 * mm,
                45 * mm
            ]
        )


        trajectory_table.setStyle(
            TableStyle([

                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor(
                        "#E4E7EC"
                    )
                ),

                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    font_bold
                ),

                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#D0D5DD"
                    )
                ),

                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                )

            ])
        )


        story.append(
            trajectory_table
        )

    else:

        story.append(
            Paragraph(
                "Historical trajectory data unavailable.",
                normal_style
            )
        )


    # --------------------------------------------------------
    # Similar Projects
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Historical Similar-Project Intelligence",
            heading_style
        )
    )


    if similar_rows:

        similar_table_data = [

            [
                "Project",
                "ID",
                "Risk",
                "Trajectory",
                "Similarity"
            ]

        ]


        for row in similar_rows:

            similar_table_data.append([

                Paragraph(
                    text(
                        row.get(
                            "project_name"
                        )
                    ),
                    small_style
                ),

                text(
                    row.get(
                        "project_id"
                    )
                ),

                text(
                    row.get(
                        "risk_level"
                    )
                ),

                Paragraph(
                    text(
                        row.get(
                            "trajectory"
                        )
                    ),
                    small_style
                ),

                (
                    f"{float(row.get('similarity_score') or 0):.2f}%"
                )

            ])


        similar_table = Table(
            similar_table_data,
            repeatRows=1,
            colWidths=[
                70 * mm,
                20 * mm,
                20 * mm,
                40 * mm,
                20 * mm
            ]
        )


        similar_table.setStyle(
            TableStyle([

                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor(
                        "#E4E7EC"
                    )
                ),

                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    font_bold
                ),

                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor(
                        "#D0D5DD"
                    )
                ),

                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7
                ),

                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP"
                ),

                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                ),

                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    4
                )

            ])
        )


        story.append(
            similar_table
        )

    else:

        story.append(
            Paragraph(
                "Similar-project intelligence unavailable.",
                normal_style
            )
        )


    # --------------------------------------------------------
    # Interpretation note
    # --------------------------------------------------------

    story.append(
        Paragraph(
            "Interpretation Note",
            heading_style
        )
    )


    story.append(
        Paragraph(
            "TriNetra predictive indicators are intended "
            "to support project monitoring and prioritization. "
            "Risk scores and machine-learning outputs represent "
            "predictive signals based on available project data; "
            "they are not causal conclusions and should not be "
            "interpreted as proof that a particular factor caused "
            "a project outcome.",
            normal_style
        )
    )


    story.append(
        Spacer(
            1,
            12
        )
    )


    story.append(
        Paragraph(
            "Generated by TriNetra Project Intelligence Platform",
            subtitle_style
        )
    )


    # --------------------------------------------------------
    # Build PDF
    # --------------------------------------------------------

    doc.build(
        story
    )


    buffer.seek(0)


    filename = (
        f"TriNetra_Project_"
        f"{project_id}_Analysis.pdf"
    )


    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="{filename}"'
        }
    )


# ============================================================
# AI PROJECT INTELLIGENCE ASSISTANT
# ============================================================

class AssistantRequest(BaseModel):
    project_id: int
    question: str


def _build_project_context(project_id: int) -> str:
    """Build a rich text context block from project data."""
    conn = db()

    row = conn.execute(
        "SELECT * FROM projects_latest WHERE project_id = ?",
        (project_id,)
    ).fetchone()

    if not row:
        conn.close()
        return ""

    p = dict(row)

    # Pull last 6 months of trajectory
    traj = conn.execute(
        """
        SELECT report_month, physical_progress_pct, expenditure_cr, revised_cost_cr
        FROM project_trajectory
        WHERE project_id = ?
        ORDER BY report_month DESC
        LIMIT 6
        """,
        (project_id,)
    ).fetchall()
    conn.close()

    # Run overrun predictions
    load_overrun_models()
    predicted_cost = None
    predicted_time = None
    if _cost_model and _time_model:
        features = _cost_model["features"]
        df = pd.DataFrame([{f: p.get(f, 0) or 0 for f in features}])
        predicted_cost = round(float(_cost_model["model"].predict(df)[0]), 2)
        predicted_time = round(float(_time_model["model"].predict(df)[0]), 1)

    traj_lines = "\n".join([
        f"  - {r['report_month']}: progress={r['physical_progress_pct']}%, "
        f"expenditure=Rs.{r['expenditure_cr']} Cr, revised_cost=Rs.{r['revised_cost_cr']} Cr"
        for r in traj
    ]) if traj else "  No historical data available."

    ctx = (
        "PROJECT INTELLIGENCE BRIEF\n"
        "===========================\n"
        f"Project Name   : {p.get('project_name', 'N/A')}\n"
        f"Project ID     : {p.get('project_id', 'N/A')}\n"
        f"Sector         : {p.get('sector', 'N/A')}\n"
        f"Line Ministry  : {p.get('line_ministry', 'N/A')}\n"
        f"Agency         : {p.get('agency', 'N/A')}\n\n"
        "FINANCIAL SNAPSHOT\n"
        "-------------------\n"
        f"Original Cost  : Rs.{p.get('original_cost_cr', 0)} Cr\n"
        f"Revised Cost   : Rs.{p.get('revised_cost_cr', 0)} Cr\n"
        f"Expenditure    : Rs.{p.get('expenditure_cr', 0)} Cr\n"
        f"Cost Escalation: {p.get('cost_escalation_pct', 0)}%\n\n"
        "PROGRESS & RISK\n"
        "----------------\n"
        f"Physical Progress        : {p.get('physical_progress_pct', 0)}%\n"
        f"Expenditure-Progress Gap : {p.get('expenditure_progress_gap', 0):.1f} pp\n"
        f"Risk Level               : {p.get('risk_level', 'N/A')}\n"
        f"Overall Risk Score       : {p.get('overall_risk_score', 0):.2f}\n"
        f"Trajectory               : {p.get('trajectory', 'N/A')}\n"
        f"Priority                 : {p.get('priority', 'N/A')}\n"
        f"Key Risk Drivers         : {p.get('key_risk_drivers', 'N/A')}\n\n"
        "AI PREDICTIONS (ML Models)\n"
        "---------------------------\n"
        f"Predicted Cost Overrun   : Rs.{predicted_cost} Cr "
        f"{'(OVER BUDGET)' if predicted_cost and predicted_cost > 0 else '(UNDER BUDGET)'}\n"
        f"Predicted Schedule Delay : {predicted_time} months "
        f"{'(DELAYED)' if predicted_time and predicted_time > 0 else '(AHEAD OF SCHEDULE)'}\n\n"
        "RECENT TRAJECTORY (Last 6 Months)\n"
        "------------------------------------\n"
        f"{traj_lines}\n\n"
        "DATES\n"
        "------\n"
        f"Sanction Date              : {p.get('sanction_date', 'N/A')}\n"
        f"Original Commissioning Date: {p.get('original_date_of_commissioning', 'N/A')}\n"
        f"Revised Commissioning Date : {p.get('revised_date_of_commissioning', 'N/A')}\n"
        f"Report Month               : {p.get('report_month', 'N/A')}\n"
    )
    return ctx.strip()


SYSTEM_PROMPT = (
    "You are TriNetra AI, an expert infrastructure project analyst for India's national "
    "infrastructure monitoring system (PAIMANA / MoSPI). You help policymakers, project "
    "administrators, and monitoring agencies understand project health, diagnose risks, and "
    "recommend interventions for Central Sector Infrastructure Projects costing Rs.150 crore "
    "and above. You are given a structured data brief for a specific project. Answer the "
    "user's question concisely and insightfully. Be specific — reference actual numbers from "
    "the brief. When relevant, suggest practical policy interventions. Use plain English. "
    "Do not fabricate data not in the brief. Keep answers under 200 words unless a detailed "
    "explanation is explicitly requested."
)


@app.post("/api/assistant")
def assistant(req: AssistantRequest):
    context = _build_project_context(req.project_id)
    if not context:
        raise HTTPException(status_code=404, detail="Project not found")

    def _clean_key(raw_val: str) -> str:
        if not raw_val:
            return ""
        s = raw_val.strip()
        if "=" in s:
            s = s.split("=", 1)[1].strip()
        return s.strip("'\" \t\r\n")

    # 1. Check for Groq API key (Environment or File)
    groq_key = _clean_key(os.getenv("GROQ_API_KEY", ""))
    if not groq_key and os.path.exists("groq_key.txt"):
        try:
            with open("groq_key.txt", "r") as f:
                groq_key = _clean_key(f.read())
        except Exception:
            pass

    # Also check api_key.txt if it contains a Groq key (starts with 'gsk_')
    if not groq_key and os.path.exists("api_key.txt"):
        try:
            with open("api_key.txt", "r") as f:
                content = _clean_key(f.read())
                if content.startswith("gsk_"):
                    groq_key = content
        except Exception:
            pass

    # -- Groq path (Fastest cloud LLM inference) --
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            models = [
                "qwen/qwen3.8-27b",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b"
            ]
            last_err = None
            for m in models:
                try:
                    chat_completion = client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": f"{context}\n\nUSER QUESTION: {req.question}"}
                        ],
                        model=m,
                        max_tokens=400,
                        temperature=0.3
                    )
                    ans = chat_completion.choices[0].message.content
                    if ans:
                        return {"answer": ans, "backend": f"groq:{m}"}
                except Exception as model_err:
                    last_err = model_err
            if last_err:
                print("Groq API Error:", last_err)
        except Exception as e:
            print("Groq Client Error:", e)

    # 2. Check for Gemini API key
    gemini_key = _clean_key(os.getenv("GEMINI_API_KEY", ""))
    
    if not gemini_key and os.path.exists("api_key.txt"):
        try:
            with open("api_key.txt", "r") as f:
                content = _clean_key(f.read())
                if not content.startswith("gsk_"):
                    gemini_key = content
        except Exception:
            pass

    # -- Gemini path --
    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            prompt = f"{context}\n\nUSER QUESTION: {req.question}"
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT
                )
            )
            return {"answer": response.text, "backend": "gemini"}
        except Exception as e:
            print("Gemini API Error:", e)
            pass  # fall through to Ollama

    # -- Ollama fallback --
    try:
        import urllib.request
        import json as _json
        payload = _json.dumps({
            "model": "llama3.2",
            "prompt": f"{SYSTEM_PROMPT}\n\n{context}\n\nUSER QUESTION: {req.question}",
            "stream": False
        }).encode()
        req_obj = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req_obj, timeout=60) as resp:
            data = _json.loads(resp.read())
            return {"answer": data.get("response", ""), "backend": "ollama"}
    except Exception:
        pass

    # -- Fallback Heuristic Analyst (if neither Gemini nor Ollama is available) --
    try:
        # Extract key highlights from context
        lines = [line.strip() for line in context.split("\n") if ":" in line]
        kv = {}
        for l in lines:
            parts = l.split(":", 1)
            if len(parts) == 2:
                kv[parts[0].strip()] = parts[1].strip()

        pname = kv.get("Project Name", "This project")
        risk = kv.get("Risk Level", "Medium")
        score = kv.get("Overall Risk Score", "—")
        prog = kv.get("Physical Progress", "—")
        cost = kv.get("Original Cost", "—")
        rev_cost = kv.get("Revised Cost", "—")
        exp = kv.get("Expenditure", "—")
        esc = kv.get("Cost Escalation", "—")
        drivers = kv.get("Key Risk Drivers", "cost and schedule variances")
        delay = kv.get("Predicted Schedule Delay", "—")
        overrun = kv.get("Predicted Cost Overrun", "—")

        fallback_answer = (
            f"**TriNetra Project Summary for {pname}**\n\n"
            f"• **Risk Classification:** Evaluated at **{risk} Risk** (TriNetra Risk Score: {score}/100).\n"
            f"• **Physical Progress:** Standing at **{prog}** with cumulative expenditure of {exp} against an original budget of {cost} (Revised: {rev_cost}, Escalation: {esc}).\n"
            f"• **ML Predictions:** Estimated schedule adjustment of {delay}, with cost overrun outlook of {overrun}.\n"
            f"• **Key Drivers & Outlook:** Primary risk drivers flagged include {drivers}. Interventions should prioritize unblocking critical milestones, reconciling expenditure gaps, and expediting regulatory clearances."
        )
        return {"answer": fallback_answer, "backend": "analytical_engine"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="No AI backend available. Set GEMINI_API_KEY environment variable or run Ollama locally."
        )
