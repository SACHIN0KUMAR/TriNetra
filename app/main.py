from pathlib import Path
import sqlite3
import threading

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
# ADMIN PROJECT DATA UPLOAD
# ============================================================

def infer_report_month_from_filename(filename: str):
    """
    Infer YYYY-MM from standard PAIMANA filenames such as:
    Projects_Report_July2026.xlsx
    Projects_Report_August2025.xlsx
    Projects_Report_Dec2025.xlsx
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

    return None


def clean_column_name(column):
    """
    Normalize PAIMANA Excel column names.
    """
    return (
        str(column)
        .replace("\n", " ")
        .replace("\r", " ")
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
    # Read report month from filename
    # --------------------------------------------------------

    report_month = infer_report_month_from_filename(
        file.filename
    )

    if report_month is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not determine report month from filename. "
                "Use a PAIMANA-style filename such as "
                "'Projects_Report_July2026.xlsx'."
            )
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

            # PAIMANA project-level Excel files have:
            # row 0 = title
            # row 1 = blank
            # row 2 = actual headers

            df = pd.read_excel(
                BytesIO(contents),
                sheet_name=0,
                header=2
            )

    except Exception as error:

        raise HTTPException(
            status_code=400,
            detail=f"Could not read uploaded file: {error}"
        )

    if df.empty:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file contains no project rows."
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
            "ProjectID"
        ]
    )

    project_name_col = find_column(
        df,
        [
            "Project Name"
        ]
    )

    sector_col = find_column(
        df,
        [
            "Sector Name",
            "Sector"
        ]
    )

    ministry_col = find_column(
        df,
        [
            "Line Ministry",
            "Ministry"
        ]
    )

    agency_col = find_column(
        df,
        [
            "Implementing Agency",
            "Agency"
        ]
    )

    original_cost_col = find_column(
        df,
        [
            "Original Cost (in cr.)",
            "Original Cost"
        ]
    )

    revised_cost_col = find_column(
        df,
        [
            "Revised Cost (in cr.)",
            "Revised Cost"
        ]
    )

    expenditure_col = find_column(
        df,
        [
            "Expenditure (in cr.)",
            "Expenditure"
        ]
    )

    progress_col = find_column(
        df,
        [
            "Physical Progress (in %)",
            "Physical Progress"
        ]
    )

    original_doc_col = find_column(
        df,
        [
            "Original Date of Commissioning",
            "Original Date of Commissioning "
        ]
    )

    revised_doc_col = find_column(
        df,
        [
            "Revised Date of Commissioning",
            "Revised Date of Commissioning "
        ]
    )

    sanction_col = find_column(
        df,
        [
            "Sanction Date"
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
    return FileResponse(STATIC / "index.html")


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

    conn.close()

    return {
        "sectors": sectors,
        "agencies": agencies
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

    return dict(row)


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

    
    pdfmetrics.registerFont(
    TTFont(
        "Arial",
        r"C:\Windows\Fonts\arial.ttf"
    )
)

    pdfmetrics.registerFont(
    TTFont(
        "Arial-Bold",
        r"C:\Windows\Fonts\arialbd.ttf"
    )
)
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
    fontName="Arial-Bold",
    fontSize=22,
    leading=26,
    alignment=TA_CENTER,
    spaceAfter=6
)


    subtitle_style = ParagraphStyle(
    "TriNetraSubtitle",
    parent=styles["Normal"],
    fontName="Arial",
    fontSize=9,
    textColor=colors.grey,
    alignment=TA_CENTER,
    spaceAfter=16
)

    heading_style = ParagraphStyle(
    "SectionHeading",
    parent=styles["Heading2"],
    fontName="Arial-Bold",
    fontSize=14,
    leading=18,
    spaceBefore=10,
    spaceAfter=8
)

    normal_style = ParagraphStyle(
    "NormalSmall",
    parent=styles["Normal"],
    fontName="Arial",
    fontSize=9,
    leading=12
)

    small_style = ParagraphStyle(
    "Small",
    parent=styles["Normal"],
    fontName="Arial",
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
                "Arial"
            ),

            (
                "FONTNAME",
                (0, 0),
                (0, -1),
                "Arial-Bold"
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
                "Arial-Bold"
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
                "Arial-Bold"
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
                    "Arial-Bold"
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
                    "Arial-Bold"
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