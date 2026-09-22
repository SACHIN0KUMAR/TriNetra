// ============================================================
// TRINETRA - FRONTEND APPLICATION
// Matched to current index.html
// ============================================================

const API_BASE = "";

let currentPage = 1;
let currentPageSize = 25;
let currentFilters = {};

let currentProject = null;

let riskChart = null;
let trajectoryChart = null;
let adminToken =
    sessionStorage.getItem(
        "trinetra_admin_token"
    );

/* =========================================================
   ADMIN AUTHENTICATION
========================================================= */

function updateAdminButton() {

    const button =
        document.getElementById(
            "adminLoginButton"
        );

    if (!button) return;

    if (adminToken) {

        button.textContent =
            "Admin Mode";

        button.classList.add(
            "admin-authenticated"
        );

    } else {

        button.textContent =
            "Admin Login";

        button.classList.remove(
            "admin-authenticated"
        );

    }

}


async function adminLogin(
    username,
    password
) {

    const response =
        await fetch(
            "/api/admin/login",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    username,
                    password
                })
            }
        );


    const data =
        await response.json();


    if (!response.ok) {

        throw new Error(
            data.detail ||
            "Login failed"
        );

    }


    adminToken =
        data.token;


    sessionStorage.setItem(
        "trinetra_admin_token",
        adminToken
    );


    updateAdminButton();


    return data;
}


async function verifyAdminSession() {

    if (!adminToken) {

        updateAdminButton();

        return false;

    }


    try {

        const response =
            await fetch(
                "/api/admin/session",
                {
                    headers: {
                        Authorization:
                            `Bearer ${adminToken}`
                    }
                }
            );


        if (!response.ok) {

            adminToken = null;

            sessionStorage.removeItem(
                "trinetra_admin_token"
            );

            updateAdminButton();

            return false;

        }


        updateAdminButton();

        return true;

    } catch (error) {

        return false;

    }

}


async function adminLogout() {

    if (adminToken) {

        try {

            await fetch(
                "/api/admin/logout",
                {
                    method: "POST",

                    headers: {
                        Authorization:
                            `Bearer ${adminToken}`
                    }
                }
            );

        } catch (error) {

            console.warn(
                "Admin logout request failed:",
                error
            );

        }

    }


    adminToken = null;


    sessionStorage.removeItem(
        "trinetra_admin_token"
    );


    updateAdminButton();

}


document.addEventListener(
    "DOMContentLoaded",
    () => {

        const loginButton =
            document.getElementById(
                "adminLoginButton"
            );


        const loginOverlay =
            document.getElementById(
                "adminLoginOverlay"
            );


        const closeLogin =
            document.getElementById(
                "closeAdminLogin"
            );


        const loginForm =
            document.getElementById(
                "adminLoginForm"
            );


        const loginError =
            document.getElementById(
                "adminLoginError"
            );


        loginButton?.addEventListener(
            "click",
            async () => {

                if (adminToken) {

                    const dashboard =
                        document.getElementById(
                            "adminDashboardOverlay"
                        );

                    dashboard?.classList.remove(
                        "hidden"
                    );

                    return;
                }


                loginOverlay?.classList.remove(
                    "hidden"
                );

            }
        );


        closeLogin?.addEventListener(
            "click",
            () => {

                loginOverlay?.classList.add(
                    "hidden"
                );

            }
        );


        loginOverlay?.addEventListener(
            "click",
            (event) => {

                if (
                    event.target ===
                    loginOverlay
                ) {

                    loginOverlay.classList.add(
                        "hidden"
                    );

                }

            }
        );


        loginForm?.addEventListener(
            "submit",
            async (event) => {

                event.preventDefault();


                loginError.textContent =
                    "";


                loginError.classList.add(
                    "hidden"
                );


                const username =
                    document.getElementById(
                        "adminUsername"
                    ).value.trim();


                const password =
                    document.getElementById(
                        "adminPassword"
                    ).value;


                try {

                    await adminLogin(
                        username,
                        password
                    );


                    loginForm.reset();


                    loginOverlay.classList.add(
                        "hidden"
                    );


                } catch (error) {

                    loginError.textContent =
                        error.message ||
                        "Invalid credentials";


                    loginError.classList.remove(
                        "hidden"
                    );

                }

            }
        );


        verifyAdminSession();

        const adminDashboard =
            document.getElementById(
                "adminDashboardOverlay"
            );


        const closeAdminDashboard =
            document.getElementById(
                "closeAdminDashboard"
            );


        const adminLogoutButton =
            document.getElementById(
                "adminLogoutButton"
            );


        closeAdminDashboard?.addEventListener(
            "click",
            () => {

                adminDashboard?.classList.add(
                    "hidden"
                );

            }
        );


        adminDashboard?.addEventListener(
            "click",
            (event) => {

                if (
                    event.target ===
                    adminDashboard
                ) {

                    adminDashboard.classList.add(
                        "hidden"
                    );

                }

            }
        );


        adminLogoutButton?.addEventListener(
            "click",
            async () => {

                await adminLogout();

                adminDashboard?.classList.add(
                    "hidden"
                );

            }
        );


        document
            .getElementById("adminAddProject")
            ?.addEventListener("click", () => {

                adminDashboardOverlay.classList.add(
                    "hidden"
                );

                adminProjectFormOverlay.classList.remove(
                    "hidden"
                );

            });
            document
    .getElementById("closeAdminProjectForm")
    ?.addEventListener("click", () => {

        const formOverlay =
            document.getElementById(
                "adminProjectFormOverlay"
            );

        const dashboard =
            document.getElementById(
                "adminDashboardOverlay"
            );

        formOverlay?.classList.add("hidden");

        dashboard?.classList.remove("hidden");

    });


        // ========================================================
        // ADMIN PROJECT SAVE
        // ========================================================

        document
            .getElementById("adminProjectForm")
            ?.addEventListener(
                "submit",
                async (event) => {

                    event.preventDefault();

                    const message =
                        document.getElementById(
                            "adminProjectFormMessage"
                        );

                    const value = id =>
                        document
                            .getElementById(id)
                            ?.value
                            ?.trim() || "";

                    const payload = {

                        project_id:
                            Number(
                                value(
                                    "adminProjectId"
                                )
                            ),

                        report_month:
                            value(
                                "adminReportMonth"
                            ),

                        project_name:
                            value(
                                "adminProjectName"
                            ),

                        sector:
                            value(
                                "adminSector"
                            ),

                        line_ministry:
                            value(
                                "adminMinistry"
                            ),

                        agency:
                            value(
                                "adminAgency"
                            ),

                        original_cost_cr:
                            Number(
                                value(
                                    "adminOriginalCost"
                                ) || 0
                            ),

                        revised_cost_cr:
                            Number(
                                value(
                                    "adminRevisedCost"
                                ) || 0
                            ),

                        expenditure_cr:
                            Number(
                                value(
                                    "adminExpenditure"
                                ) || 0
                            ),

                        physical_progress_pct:
                            Number(
                                value(
                                    "adminPhysicalProgress"
                                ) || 0
                            ),

                        original_date_of_commissioning:
                            value(
                                "adminOriginalDoc"
                            ),

                        revised_date_of_commissioning:
                            value(
                                "adminRevisedDoc"
                            ),

                        sanction_date:
                            value(
                                "adminSanctionDate"
                            )

                    };


                    try {

                        if (!adminToken) {

                            throw new Error(
                                "Admin session expired. Please login again."
                            );

                        }


                        if (!payload.project_id) {

                            throw new Error(
                                "Project ID is required."
                            );

                        }


                        if (!payload.project_name) {

                            throw new Error(
                                "Project Name is required."
                            );

                        }


                        if (!payload.report_month) {

                            throw new Error(
                                "Report Month is required."
                            );

                        }


                        if (message) {

                            message.textContent =
                                "Saving project...";

                            message.classList.remove(
                                "error"
                            );

                        }


                        const response =
                            await fetch(
                                "/api/admin/projects",
                                {
                                    method: "POST",

                                    headers: {
                                        "Content-Type":
                                            "application/json",

                                        "Authorization":
                                            `Bearer ${adminToken}`
                                    },

                                    body:
                                        JSON.stringify(
                                            payload
                                        )
                                }
                            );


                        const data =
                            await response.json();


                        if (!response.ok) {

                            throw new Error(
                                data.detail ||
                                "Failed to save project."
                            );

                        }


                        if (message) {

                            message.textContent =
                                "Project saved successfully.";

                            message.classList.remove(
                                "error"
                            );

                        }


                        alert(
                            `Project saved successfully!\n\n` +
                            `Project ID: ${payload.project_id}\n` +
                            `Project Name: ${payload.project_name}`
                        );


                        await loadSummary();

                        await loadRiskChart();

                        await loadProjects(1);


                        document
                            .getElementById(
                                "adminProjectFormOverlay"
                            )
                            ?.classList.add(
                                "hidden"
                            );


                        document
                            .getElementById(
                                "adminDashboardOverlay"
                            )
                            ?.classList.remove(
                                "hidden"
                            );


                    } catch (error) {

                        console.error(
                            "Save project error:",
                            error
                        );


                        if (message) {

                            message.textContent =
                                error.message ||
                                "Failed to save project.";

                            message.classList.add(
                                "error"
                            );

                        }


                        alert(
                            `Failed to save project:\n${error.message}`
                        );

                    }

                }
            );


        document
            .getElementById("adminUploadData")
            ?.addEventListener("click", () => {

                const input =
                    document.createElement(
                        "input"
                    );


                input.type = "file";

                input.accept =
                    ".xlsx,.xls,.csv";


                input.onchange = async () => {

                    const file =
                        input.files[0];


                    if (!file) return;


                    const formData =
                        new FormData();


                    formData.append(
                        "file",
                        file
                    );


                    try {

                        const response =
                            await fetch(
                                "/api/admin/upload",
                                {
                                    method: "POST",

                                    headers: {
                                        "Authorization":
                                            `Bearer ${adminToken}`
                                    },

                                    body:
                                        formData
                                }
                            );


                        const data =
                            await response.json();


                        if (!response.ok) {

                            throw new Error(
                                data.detail ||
                                "Upload failed"
                            );

                        }


                        alert(
                            `Upload successful.\n\n` +
                            `File: ${file.name}\n` +
                            `Rows processed: ${data.rows_processed ?? "N/A"}`
                        );


                        if (
                            typeof loadSummary ===
                            "function"
                        ) {

                            await loadSummary();

                        }


                        if (
                            typeof loadRiskChart ===
                            "function"
                        ) {

                            await loadRiskChart();

                        }


                        if (
                            typeof loadProjects ===
                            "function"
                        ) {

                            await loadProjects();

                        }


                    } catch (error) {

                        console.error(
                            "Upload error:",
                            error
                        );

                        alert(
                            `Upload failed: ${error.message}`
                        );

                    }

                };


                input.click();

            });


        document
            .getElementById("adminProjectReports")
            ?.addEventListener(
                "click",
                () => {

                    alert(
                        "Project report generation will be added next."
                    );

                }
            );

    }
);


// ============================================================
// API HELPER
// ============================================================

async function api(
    url,
    options = {}
) {

    const response =
        await fetch(
            `${API_BASE}${url}`,
            options
        );


    if (!response.ok) {

        throw new Error(
            `API ${response.status}: ${response.statusText}`
        );

    }


    return await response.json();

}


// ============================================================
// HELPERS
// ============================================================

function escapeHtml(value) {

    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");

}


function number(
    value,
    decimals = 1
) {

    const n =
        Number(value);


    if (!Number.isFinite(n)) {

        return "—";

    }


    return n.toFixed(decimals);

}


function setText(
    id,
    value
) {

    const element =
        document.getElementById(id);


    if (element) {

        element.textContent =
            value ?? "—";

    }

}


function riskClass(level) {

    const value =
        String(level || "")
            .toLowerCase();


    if (value === "high")
        return "risk-high";


    if (value === "medium")
        return "risk-medium";


    if (value === "low")
        return "risk-low";


    return "";

}


function riskBadge(level) {

    const value =
        String(level || "Unknown");


    return `
        <span class="risk-badge ${riskClass(value)}">
            ${escapeHtml(value)}
        </span>
    `;

}


// ============================================================
// CONNECTION STATUS
// ============================================================

async function checkConnection() {

    try {

        await api(
            "/api/summary"
        );


        const status =
            document.getElementById(
                "connectionStatus"
            );


        const dot =
            document.getElementById(
                "statusDot"
            );


        if (status) {

            status.textContent =
                "API Connected";

        }


        if (dot) {

            dot.classList.add(
                "connected"
            );

        }


    } catch (error) {

        console.error(
            "Connection error:",
            error
        );


        const status =
            document.getElementById(
                "connectionStatus"
            );


        if (status) {

            status.textContent =
                "API Offline";

        }

    }

}


// ============================================================
// SUMMARY
// ============================================================

async function loadSummary() {

    try {

        const data =
            await api(
                "/api/summary"
            );


        // Backend returns:
        // projects, high, medium, low, trajectory_rows, report_month


        setText(
            "totalProjects",
            data.projects ?? 0
        );


        setText(
            "highRisk",
            data.high ?? 0
        );


        setText(
            "mediumRisk",
            data.medium ?? 0
        );


        setText(
            "latestMonth",
            formatMonth(
                data.report_month
            )
        );


    } catch (error) {

        console.error(
            "Summary error:",
            error
        );

    }

}


// ============================================================
// DATE / MONTH FORMAT
// ============================================================

function formatMonth(value) {

    if (!value)
        return "—";


    const text =
        String(value);


    if (
        /^\d{4}-\d{2}/.test(
            text
        )
    ) {

        const date =
            new Date(text);


        if (
            !Number.isNaN(
                date.getTime()
            )
        ) {

            return date.toLocaleDateString(
                "en-IN",
                {
                    month: "short",
                    year: "numeric"
                }
            );

        }

    }


    return text;

}


// ============================================================
// FILTERS
// ============================================================

async function loadFilters() {

    try {

        const data =
            await api(
                "/api/filters"
            );


        // The HTML already contains the options,
        // so we don't need to rebuild them.
        // This function mainly confirms the endpoint works.


        console.log(
            "Filters loaded:",
            data
        );


    } catch (error) {

        console.error(
            "Filter error:",
            error
        );

    }

}


// ============================================================
// PROJECTS
// ============================================================

async function loadProjects(
    page = 1
) {

    currentPage =
        page;


    const table =
        document.getElementById(
            "projectTable"
        );


    if (!table) {

        console.error(
            "projectTable not found."
        );

        return;

    }


    table.innerHTML = `
        <tr>
            <td colspan="10" class="loading-cell">
                Loading projects...
            </td>
        </tr>
    `;


    try {

        const params =
            new URLSearchParams();


        params.set(
            "page",
            currentPage
        );


        params.set(
            "page_size",
            currentPageSize
        );


        const search =
            document
                .getElementById(
                    "search"
                )
                ?.value
                .trim() || "";


        const risk =
            document
                .getElementById(
                    "riskFilter"
                )
                ?.value || "";


        const trajectory =
            document
                .getElementById(
                    "trajectoryFilter"
                )
                ?.value || "";


        const priority =
            document
                .getElementById(
                    "priorityFilter"
                )
                ?.value || "";


        if (search) {

            params.set(
                "search",
                search
            );

        }


        if (risk) {

            params.set(
                "risk",
                risk
            );

        }


        if (trajectory) {

            params.set(
                "trajectory",
                trajectory
            );

        }


        if (priority) {

            params.set(
                "priority",
                priority
            );

        }


        currentFilters = {

            search,

            risk,

            trajectory,

            priority

        };


        const data =
            await api(
                `/api/projects?${params.toString()}`
            );


        renderProjects(
            data
        );


        updatePagination(
            data
        );


    } catch (error) {

        console.error(
            "Projects error:",
            error
        );


        table.innerHTML = `
            <tr>
                <td colspan="10" class="loading-cell">
                    Unable to load projects.
                </td>
            </tr>
        `;

    }

}


// ============================================================
// RENDER PROJECT TABLE
// ============================================================

function renderProjects(
    data
) {

    const table =
        document.getElementById(
            "projectTable"
        );


    if (!table) return;


    const projects =
        data.items ||
        data.projects ||
        [];


    const total =
        data.total ??
        projects.length;


    setText(
        "resultCount",
        `${total} projects`
    );


    if (!projects.length) {

        table.innerHTML = `
            <tr>
                <td colspan="10" class="loading-cell">
                    No projects found.
                </td>
            </tr>
        `;


        return;

    }


    table.innerHTML =
        projects
            .map(
                project => {

                    const projectId =
                        String(
                            project.project_id ??
                            ""
                        );


                    const mlRisk =
                        project.ml_deterioration_probability ??
                        project.ml_risk_probability ??
                        null;


                    return `

                        <tr
                            class="project-row"
                            data-project-id="${escapeHtml(projectId)}"
                            onclick="openProject('${escapeHtml(projectId)}')"
                        >

                            <td>

                                <div class="table-project-name">

                                    <strong>
                                        ${escapeHtml(
                                            project.project_name ||
                                            "Unnamed Project"
                                        )}
                                    </strong>

                                    <small>
                                        ID: ${escapeHtml(projectId)}
                                    </small>

                                </div>

                            </td>


                            <td>
                                ${escapeHtml(
                                    project.agency ||
                                    "—"
                                )}
                            </td>


                            <td>
                                ${escapeHtml(
                                    project.sector ||
                                    "—"
                                )}
                            </td>


                            <td>
                                ₹${number(
                                    project.original_cost_cr,
                                    2
                                )} Cr
                            </td>


                            <td>
                                ${number(
                                    project.physical_progress_pct,
                                    1
                                )}%
                            </td>


                            <td>
                                ${number(
                                    project.cost_escalation_pct,
                                    1
                                )}%
                            </td>


                            <td class="${riskClass(project.risk_level)}">

                                ${escapeHtml(
                                    project.risk_level ||
                                    "—"
                                )}

                            </td>


                            <td>

                                ${
                                    mlRisk !== null
                                        ? `${number(
                                            Number(mlRisk) * 100,
                                            1
                                        )}%`
                                        : "—"
                                }

                            </td>


                            <td>

                                ${escapeHtml(
                                    project.trajectory ||
                                    "—"
                                )}

                            </td>


                            <td>

                                ${escapeHtml(
                                    project.priority ||
                                    "—"
                                )}

                            </td>

                        </tr>

                    `;

                }
            )
            .join("");

}


// ============================================================
// PAGINATION
// ============================================================

function updatePagination(
    data
) {

    const page =
        Number(
            data.page ??
            currentPage
        );


    const pageSize =
        Number(
            data.page_size ??
            data.limit ??
            currentPageSize
        );


    const total =
        Number(
            data.total ??
            0
        );


    const pages =
        Number(
            data.pages ??
            Math.ceil(
                total /
                pageSize
            )
        );


    setText(
        "pageInfo",
        `Page ${page} of ${pages}`
    );


    const prev =
        document.getElementById(
            "prevButton"
        );


    const next =
        document.getElementById(
            "nextButton"
        );


    if (prev) {

        prev.disabled =
            page <= 1;

    }


    if (next) {

        next.disabled =
            page >= pages;

    }

}


// ============================================================
// OPEN PROJECT
// ============================================================

async function openProject(
    projectId
) {

    try {

        const project =
            await api(
                `/api/projects/${encodeURIComponent(projectId)}`
            );


        currentProject =
            project;


        renderProjectModal(
            project
        );


        openModal();


        // Load the intelligence sections

        loadProjectSHAP(
            project.project_id
        );


        loadProjectTrajectory(
            project.project_id
        );


        loadSimilarProjects(
            project.project_id
        );


    } catch (error) {

        console.error(
            "Project error:",
            error
        );


        showError(
            "Unable to load project details."
        );

    }

}


// ============================================================
// PROJECT MODAL
// ============================================================

function renderProjectModal(
    project
) {
        window.currentReportProject = project;
        const downloadButton =
        document.getElementById(
            "downloadProjectReport"
        );

    if (downloadButton) {

    downloadButton.onclick = () => {

        const menu =
            document.getElementById(
                "downloadReportMenu"
            );

        if (menu) {
            menu.classList.toggle("hidden");
        }

    };

}


const pdfButton =
    document.getElementById(
        "downloadPdfReport"
    );

if (pdfButton) {

    pdfButton.onclick = () => {

        window.open(
            `/api/projects/${encodeURIComponent(
                project.project_id
            )}/report/pdf`,
            "_blank"
        );

        document
            .getElementById(
                "downloadReportMenu"
            )
            ?.classList.add("hidden");

    };

}


const htmlButton =
    document.getElementById(
        "downloadHtmlReport"
    );

if (htmlButton) {

    htmlButton.onclick = () => {

        downloadProjectReport(
            project.project_id
        );

        document
            .getElementById(
                "downloadReportMenu"
            )
            ?.classList.add("hidden");

    };

}

    setText(
        "modalProjectName",
        project.project_name ||
        "Project"
    );


    setText(
        "modalProjectId",
        `Project ID: ${project.project_id ?? "—"}`
    );


    const details =
        document.getElementById(
            "modalDetails"
        );


    if (details) {

        details.innerHTML = `

            <div class="detail-card">

                <span>Agency</span>

                <strong>
                    ${escapeHtml(
                        project.agency ||
                        "—"
                    )}
                </strong>

            </div>

            <div class="detail-card">

                <span>Line Ministry</span>

                <strong>
                    ${project.line_ministry || "—"}
                </strong>

            </div>


            <div class="detail-card">

                <span>Sector</span>

                <strong>
                    ${escapeHtml(
                        project.sector ||
                        "—"
                    )}
                </strong>

            </div>


            <div class="detail-card">

                <span>Original Cost</span>

                <strong>
                    ₹${number(
                        project.original_cost_cr,
                        2
                    )} Cr
                </strong>

            </div>


            <div class="detail-card">

                <span>Revised Cost</span>

                <strong>
                    ₹${number(
                        project.revised_cost_cr,
                        2
                    )} Cr
                </strong>

            </div>


            <div class="detail-card">

                <span>Expenditure</span>

                <strong>
                    ₹${number(
                        project.expenditure_cr,
                        2
                    )} Cr
                </strong>

            </div>


            <div class="detail-card">

                <span>Physical Progress</span>

                <strong>
                    ${number(
                        project.physical_progress_pct,
                        1
                    )}%
                </strong>

            </div>


            <div class="detail-card">

                <span>Cost Escalation</span>

                <strong>
                    ${number(
                        project.cost_escalation_pct,
                        1
                    )}%
                </strong>

            </div>


            <div class="detail-card">

                <span>Expenditure / Progress Gap</span>

                <strong>
                    ${number(
                        project.expenditure_progress_gap,
                        1
                    )}
                </strong>

            </div>


            <div class="detail-card">

                <span>Risk Level</span>

                <strong>
                    ${escapeHtml(
                        project.risk_level ||
                        "—"
                    )}
                </strong>

            </div>


            <div class="detail-card">

                <span>Priority</span>

                <strong>
                    ${escapeHtml(
                        project.priority ||
                        "—"
                    )}
                </strong>

            </div>

        `;

    }


    // ML risk

    const mlRisk =
        project.ml_deterioration_probability ??
        project.ml_risk_probability;


    const mlValue =
        mlRisk !== undefined &&
        mlRisk !== null

            ? Number(mlRisk) * 100

            : Number(
                project.overall_risk_score ||
                0
            );


    setText(
        "modalMLRisk",
        `${number(
            mlValue,
            1
        )}%`
    );


    const bar =
        document.getElementById(
            "modalMLRiskBar"
        );


    if (bar) {

        const bounded =
            Math.max(
                0,
                Math.min(
                    100,
                    mlValue
                )
            );


        bar.style.width =
            `${bounded}%`;

    }


    // Existing risk drivers

    const drivers =
        document.getElementById(
            "modalDrivers"
        );


    if (drivers) {

        const raw =
            project.key_risk_drivers ||
            "";


        const list =
            typeof raw === "string"

                ? raw
                    .split(";")
                    .map(
                        x =>
                            x.trim()
                    )
                    .filter(Boolean)

                : Array.isArray(raw)

                    ? raw

                    : [];


        drivers.innerHTML = `

            <div class="modal-section-header">

                <div>

                    <h3>
                        Key Risk Drivers
                    </h3>

                    <p>
                        Current indicators associated with project risk
                    </p>

                </div>

            </div>


            <div class="driver-list">

                ${
                    list.length

                        ? list
                            .map(
                                driver => `
                                    <div class="driver-item">
                                        ${escapeHtml(driver)}
                                    </div>
                                `
                            )
                            .join("")

                        : `
                            <div class="driver-item">
                                No predefined drivers available.
                            </div>
                        `
                }

            </div>


            <div id="shapExplanation">

                <div class="similar-loading">
                    Calculating explainable AI contribution...
                </div>

            </div>

        `;

    }


    // Make sure Historical Intelligence exists
    ensureHistoricalSection();

}
async function downloadProjectReport(projectId) {

    try {

        const project =
            window.currentReportProject;

        if (
            !project ||
            String(project.project_id) !== String(projectId)
        ) {
            alert("Project data could not be found.");
            return;
        }


        // Fetch supporting intelligence
        let explanation = null;
        let trajectory = null;
        let similar = null;


        try {

            explanation = await api(
                `/api/projects/${encodeURIComponent(projectId)}/explanation`
            );

        } catch (error) {

            console.warn(
                "SHAP explanation unavailable:",
                error
            );

        }


        try {

            trajectory = await api(
                `/api/projects/${encodeURIComponent(projectId)}/trajectory`
            );

        } catch (error) {

            console.warn(
                "Trajectory unavailable:",
                error
            );

        }


        try {

            similar = await api(
                `/api/projects/${encodeURIComponent(projectId)}/similar`
            );

        } catch (error) {

            console.warn(
                "Similar-project intelligence unavailable:",
                error
            );

        }


        // ---------- Helpers ----------

        const safe = value =>
            escapeHtml(
                value === undefined ||
                value === null ||
                value === ""
                    ? "—"
                    : String(value)
            );


        const money = value =>
            Number.isFinite(Number(value))
                ? `₹${Number(value).toLocaleString(
                    "en-IN",
                    {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    }
                )} Cr`
                : "—";


        const percent = value =>
            Number.isFinite(Number(value))
                ? `${Number(value).toFixed(1)}%`
                : "—";


        // ---------- SHAP drivers ----------

        const shapDrivers =
            explanation &&
            Array.isArray(explanation.drivers)
                ? explanation.drivers
                : [];


        const mlProbability =
            explanation &&
            explanation.ml_probability_percent !== undefined
                ? Number(
                    explanation.ml_probability_percent
                )
                : (
                    project.ml_deterioration_probability !==
                    undefined
                        ? Number(
                            project.ml_deterioration_probability
                        ) * 100
                        : null
                );


        const shapHtml =
            shapDrivers.length

                ? shapDrivers
                    .map(
                        driver => `
                            <tr>
                                <td>
                                    ${safe(
                                        driver.label ||
                                        driver.feature ||
                                        "Risk factor"
                                    )}
                                </td>

                                <td>
                                    ${safe(
                                        driver.value
                                    )}
                                </td>

                                <td>
                                    ${safe(
                                        driver.direction ||
                                        "—"
                                    )}
                                </td>

                                <td>
                                    ${safe(
                                        driver.impact
                                    )}
                                </td>
                            </tr>
                        `
                    )
                    .join("")

                : `
                    <tr>
                        <td colspan="5">
                            Explainable AI contribution data unavailable.
                        </td>
                    </tr>
                `;


        // ---------- Trajectory ----------

        const trajectoryRows =
            trajectory &&
            Array.isArray(trajectory.trajectory)
                ? trajectory.trajectory
                : (
                    Array.isArray(trajectory)
                        ? trajectory
                        : []
                );


        const trajectoryHtml =
            trajectoryRows.length

                ? trajectoryRows
                    .map(
                        row => `
                            <tr>
                                <td>
                                    ${safe(
                                        row.report_month ||
                                        row.month ||
                                        row.date
                                    )}
                                </td>

                                <td>
                                    ${percent(
                                        row.physical_progress_pct ??
                                        row.physical_progress
                                    )}
                                </td>

                                <td>
                                    ${money(
                                        row.expenditure_cr ??
                                        row.expenditure
                                    )}
                                </td>

                                <td>
                                    ${percent(
                                        row.cost_escalation_pct ??
                                        row.cost_escalation
                                    )}
                                </td>

                                <td>
                                    ${safe(
                                        row.trajectory ||
                                        "—"
                                    )}
                                </td>
                            </tr>
                        `
                    )
                    .join("")

                : `
                    <tr>
                        <td colspan="5">
                            Historical trajectory data unavailable.
                        </td>
                    </tr>
                `;


        // ---------- Similar projects ----------

        const similarProjects =
    Array.isArray(similar?.similar_projects)
        ? similar.similar_projects
        : [];


        const similarHtml =
    similarProjects.length

        ? similarProjects
            .slice(0, 5)
            .map(
                item => `
                    <tr>

                        <td>
                            ${safe(
                                item.project_name ||
                                "—"
                            )}
                        </td>

                        <td>
                            ${safe(
                                item.project_id
                            )}
                        </td>

                        <td>
                            ${safe(
                                item.risk_level
                            )}
                        </td>

                        <td>
                            ${safe(
                                item.trajectory
                            )}
                        </td>

                        <td>
                            ${Number.isFinite(
                                Number(
                                    item.similarity_score
                                )
                            )
                                ? `${Number(
                                    item.similarity_score
                                ).toFixed(2)}%`
                                : "—"
                            }
                        </td>

                    </tr>
                `
            )
            .join("")

        : `
            <tr>
                <td colspan="5">
                    Similar-project intelligence unavailable.
                </td>
            </tr>
        `;

        // ---------- Generate report ----------

        const reportHtml = `
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>
    TriNetra Project Analysis -
    ${safe(project.project_name)}
</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 40px;
    font-family:
        Arial,
        Helvetica,
        sans-serif;
    color: #101828;
    background: #f8fafc;
    line-height: 1.5;
}

.container {
    max-width: 1100px;
    margin: auto;
}

.header {
    background: #0f172a;
    color: white;
    padding: 30px;
    border-radius: 14px;
    margin-bottom: 24px;
}

.brand {
    font-size: 28px;
    font-weight: 800;
    margin-bottom: 6px;
}

.subtitle {
    color: #cbd5e1;
    font-size: 14px;
}

.project-title {
    margin-top: 24px;
    font-size: 24px;
    font-weight: 700;
}

.project-id {
    color: #cbd5e1;
    font-size: 14px;
}

.section {
    background: white;
    border: 1px solid #e4e7ec;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 20px;
}

.section h2 {
    margin-top: 0;
    margin-bottom: 18px;
    font-size: 19px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(3, 1fr);
    gap: 14px;
}

.card {
    border: 1px solid #e4e7ec;
    border-radius: 10px;
    padding: 15px;
    background: #f9fafb;
}

.card span {
    display: block;
    color: #667085;
    font-size: 12px;
    margin-bottom: 6px;
}

.card strong {
    font-size: 16px;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}

th,
td {
    padding: 10px;
    border-bottom: 1px solid #eaecf0;
    text-align: left;
    font-size: 13px;
}

th {
    background: #f2f4f7;
    font-weight: 700;
}

.risk {
    font-size: 24px;
    font-weight: 800;
}

.note {
    background: #f8fafc;
    border-left: 4px solid #2563eb;
    padding: 14px;
    color: #475467;
    font-size: 13px;
}

.footer {
    margin-top: 30px;
    color: #667085;
    font-size: 12px;
    text-align: center;
}

@media print {

    body {
        background: white;
        padding: 20px;
    }

    .section,
    .header {
        break-inside: avoid;
    }

}

@media (max-width: 800px) {

    body {
        padding: 20px;
    }

    .grid {
        grid-template-columns: 1fr;
    }

}

</style>

</head>


<body>

<div class="container">


    <div class="header">

        <div class="brand">
            TriNetra
        </div>

        <div class="subtitle">
            Integrated Project Monitoring & Predictive Intelligence
        </div>

        <div class="project-title">
            ${safe(project.project_name)}
        </div>

        <div class="project-id">
            Project ID:
            ${safe(project.project_id)}
        </div>

    </div>


    <!-- PROJECT OVERVIEW -->

    <div class="section">

        <h2>
            Project Overview
        </h2>

        <div class="grid">

            <div class="card">
                <span>Agency</span>
                <strong>
                    ${safe(project.agency)}
                </strong>
            </div>

            <div class="card">
                <span>Line Ministry</span>
                <strong>
                    ${safe(project.line_ministry)}
                </strong>
            </div>

            <div class="card">
                <span>Sector</span>
                <strong>
                    ${safe(project.sector)}
                </strong>
            </div>

            <div class="card">
                <span>Report Month</span>
                <strong>
                    ${safe(project.report_month)}
                </strong>
            </div>

            <div class="card">
                <span>Original Cost</span>
                <strong>
                    ${money(project.original_cost_cr)}
                </strong>
            </div>

            <div class="card">
                <span>Revised Cost</span>
                <strong>
                    ${money(project.revised_cost_cr)}
                </strong>
            </div>

        </div>

    </div>


    <!-- FINANCIAL & PHYSICAL STATUS -->

    <div class="section">

        <h2>
            Financial & Implementation Status
        </h2>

        <div class="grid">

            <div class="card">
                <span>Expenditure</span>
                <strong>
                    ${money(project.expenditure_cr)}
                </strong>
            </div>

            <div class="card">
                <span>Physical Progress</span>
                <strong>
                    ${percent(project.physical_progress_pct)}
                </strong>
            </div>

            <div class="card">
                <span>Cost Escalation</span>
                <strong>
                    ${percent(project.cost_escalation_pct)}
                </strong>
            </div>

            <div class="card">
                <span>Expenditure / Progress Gap</span>
                <strong>
                    ${number(
                        project.expenditure_progress_gap,
                        1
                    )}
                </strong>
            </div>

        </div>

    </div>


    <!-- RISK -->

    <div class="section">

        <h2>
            TriNetra Risk Assessment
        </h2>

        <div class="grid">

            <div class="card">
                <span>Overall Risk Score</span>
                <strong class="risk">
                    ${number(
                        project.overall_risk_score,
                        1
                    )}
                </strong>
            </div>

            <div class="card">
                <span>Risk Level</span>
                <strong>
                    ${safe(project.risk_level)}
                </strong>
            </div>

            <div class="card">
                <span>Priority</span>
                <strong>
                    ${safe(project.priority)}
                </strong>
            </div>

            <div class="card">
                <span>Trajectory</span>
                <strong>
                    ${safe(project.trajectory)}
                </strong>
            </div>

            <div class="card">
                <span>ML Trajectory Risk</span>
                <strong>
                    ${
                        mlProbability !== null &&
                        Number.isFinite(mlProbability)
                            ? `${mlProbability.toFixed(1)}%`
                            : "—"
                    }
                </strong>
            </div>

        </div>

    </div>


    <!-- RISK DRIVERS -->

    <div class="section">

        <h2>
            Explainable AI — Risk Drivers
        </h2>

        <table>

            <thead>

                <tr>
                    <th>Factor</th>
                    <th>Value</th>
                    <th>Direction</th>
                    <th>Impact</th>
                </tr>

            </thead>

            <tbody>

                ${shapHtml}

            </tbody>

        </table>

    </div>


    <!-- TRAJECTORY -->

    <div class="section">

        <h2>
            Project Trajectory
        </h2>

        <table>

            <thead>

                <tr>
                    <th>Month</th>
                    <th>Physical Progress</th>
                    <th>Expenditure</th>
                    <th>Cost Escalation</th>
                    <th>Trajectory</th>
                </tr>

            </thead>

            <tbody>

                ${trajectoryHtml}

            </tbody>

        </table>

    </div>


    <!-- SIMILAR PROJECTS -->

    <div class="section">

        <h2>
            Historical Similar-Project Intelligence
        </h2>

        <table>

            <thead>

                <tr>
                    
                    <th>Project</th>
                    <th>Project ID</th>
                    <th>Risk Level</th>
                    <th>Trajectory</th>
                    <th>Similarity</th>
                </tr>
                

            </thead>

            <tbody>

                ${similarHtml}

            </tbody>

        </table>

    </div>


    <!-- DISCLAIMER -->

    <div class="section">

        <h2>
            Interpretation Note
        </h2>

        <div class="note">

            TriNetra's predictive indicators are intended to
            support project monitoring and prioritization.
            Risk scores and machine-learning outputs represent
            predictive signals based on available project data;
            they are not causal conclusions and should not be
            interpreted as proof that a particular factor caused
            a project outcome.

        </div>

    </div>


    <div class="footer">

        Generated by TriNetra Project Intelligence Platform

    </div>


</div>

</body>

</html>
`;


        // ---------- Download ----------

        const blob =
            new Blob(
                [reportHtml],
                {
                    type:
                        "text/html;charset=utf-8"
                }
            );


        const url =
            URL.createObjectURL(blob);


        const link =
            document.createElement("a");


        link.href = url;

        link.download =
            `TriNetra_Project_${projectId}_Analysis.html`;


        document.body.appendChild(link);

        link.click();

        document.body.removeChild(link);

        URL.revokeObjectURL(url);


    } catch (error) {

        console.error(
            "Project report generation failed:",
            error
        );

        alert(
            "Unable to generate the project analysis report."
        );

    }

}


// ============================================================
// SHAP
// ============================================================

// ============================================================
// SHAP / EXPLAINABLE AI
// ============================================================

async function loadProjectSHAP(
    projectId
) {

    const container =
        document.getElementById(
            "shapExplanation"
        );


    if (!container) return;


    container.innerHTML = `
        <div class="similar-loading">
            Calculating explainable AI contribution...
        </div>
    `;


    try {

        const data =
            await api(
                `/api/projects/${encodeURIComponent(projectId)}/explanation`
            );


        renderSHAP(
            data
        );


    } catch (error) {

        console.error(
            "SHAP error:",
            error
        );


        container.innerHTML = `
            <div class="similar-error">
                Explainable AI unavailable.
            </div>
        `;

    }

}


function renderSHAP(
    data
) {

    const container =
        document.getElementById(
            "shapExplanation"
        );


    if (!container) return;


    // Your backend returns "drivers"

    const drivers =
        Array.isArray(
            data.drivers
        )
            ? data.drivers
            : [];


    if (!drivers.length) {

        container.innerHTML = `
            <div class="similar-empty">
                No SHAP explanation available.
            </div>
        `;


        return;

    }


    const probability =
        Number(
            data.ml_probability_percent ??
            0
        );


    container.innerHTML = `

        <div class="modal-section-header">

            <div>

                <h3>
                    Explainable AI
                </h3>

                <p>
                    SHAP-based explanation of the
                    trajectory-risk prediction
                </p>

            </div>


            <strong class="shap-probability">

                ${probability.toFixed(1)}%

            </strong>

        </div>


        <div class="shap-list">

            ${
                drivers
                    .map(
                        driver => {

                            const impact =
                                Number(
                                    driver.impact ??
                                    0
                                );


                            const value =
                                Number(
                                    driver.value ??
                                    0
                                );


                            const increases =
                                String(
                                    driver.direction ||
                                    ""
                                )
                                .toLowerCase()
                                .includes(
                                    "increase"
                                );


                            return `

                                <div class="shap-item">

                                    <div class="shap-feature">

                                        <strong>
                                            ${escapeHtml(
                                                driver.label ||
                                                driver.feature ||
                                                "Feature"
                                            )}
                                        </strong>

                                        <small>

                                            Current value:
                                            ${
                                                Number.isFinite(
                                                    value
                                                )

                                                    ? value.toFixed(
                                                        2
                                                    )

                                                    : "—"
                                            }

                                        </small>

                                    </div>


                                    <div class="shap-impact">

                                        <span
                                            class="${
                                                increases
                                                    ? "shap-positive"
                                                    : "shap-negative"
                                            }"
                                        >

                                            ${
                                                increases
                                                    ? "+"
                                                    : "−"
                                            }

                                            ${Math.abs(
                                                impact
                                            ).toFixed(4)}

                                        </span>


                                        <small>

                                            ${escapeHtml(
                                                driver.direction ||
                                                ""
                                            )}

                                        </small>

                                    </div>

                                </div>

                            `;

                        }
                    )
                    .join("")
            }

        </div>


        <div class="shap-interpretation">

            <strong>
                Interpretation
            </strong>

            <p>

                ${escapeHtml(
                    data.interpretation ||
                    "These factors contributed to the model's predicted trajectory risk."
                )}

            </p>

        </div>

    `;

}


// ============================================================
// TRAJECTORY
// ============================================================

async function loadProjectTrajectory(
    projectId
) {

    try {

        const data =
            await api(
                `/api/projects/${encodeURIComponent(projectId)}/trajectory`
            );


        renderTrajectory(
            data
        );


    } catch (error) {

        console.error(
            "Trajectory error:",
            error
        );

    }

}


function renderTrajectory(
    data
) {

    const canvas =
        document.getElementById(
            "trajectoryChart"
        );


    if (!canvas) return;


    let rows =
        data.trajectory ||
        data.items ||
        data.projects ||
        data;


    if (!Array.isArray(rows)) {

        rows = [];

    }


    if (!rows.length) return;


    if (trajectoryChart) {

        trajectoryChart.destroy();

    }


    const labels =
        rows.map(
            row =>
                formatMonth(
                    row.report_month ||
                    row.month ||
                    ""
                )
        );


    const progress =
        rows.map(
            row =>
                Number(
                    row.physical_progress_pct ||
                    0
                )
        );


    const gap =
        rows.map(
            row =>
                Number(
                    row.expenditure_progress_gap ||
                    0
                )
        );


    trajectoryChart =
        new Chart(
            canvas,
            {

                type: "line",

                data: {

                    labels,

                    datasets: [

                        {
                            label:
                                "Physical Progress %",

                            data:
                                progress,

                            tension:
                                0.3,

                            yAxisID:
                                "progress"
                        },

                        {
                            label:
                                "Expenditure-Progress Gap",

                            data:
                                gap,

                            tension:
                                0.3,

                            yAxisID:
                                "gap"
                        }

                    ]

                },


                options: {

                    responsive: true,

                    maintainAspectRatio: false,

                    interaction: {

                        mode: "index",

                        intersect: false
                    },


                    scales: {

                        progress: {

                            position: "left",

                            beginAtZero: true

                        },


                        gap: {

                            position: "right",

                            beginAtZero: true,

                            grid: {

                                drawOnChartArea:
                                    false

                            }

                        }

                    }

                }

            }

        );

}


// ============================================================
// HISTORICAL INTELLIGENCE
// ============================================================

function ensureHistoricalSection() {

    if (
        document.getElementById(
            "historicalIntelligence"
        )
    ) {

        return;

    }


    const chartContainer =
        document.querySelector(
            ".trajectory-chart-container"
        );


    if (!chartContainer) {

        console.warn(
            "Trajectory container not found."
        );

        return;

    }


    const section =
        document.createElement(
            "div"
        );


    section.id =
        "historicalIntelligence";


    section.className =
        "historical-section";


    section.innerHTML = `

        <div class="modal-section-header">

            <div>

                <h3>
                    Historical Intelligence
                </h3>

                <p>
                    Projects with similar current
                    cost, progress and expenditure profiles
                </p>

            </div>

        </div>


        <div id="similarProjects">

            <div class="similar-loading">
                Finding historically similar projects...
            </div>

        </div>

    `;


    chartContainer.parentNode.insertBefore(
        section,
        chartContainer.nextSibling
    );

}


async function loadSimilarProjects(
    projectId
) {

    const container =
        document.getElementById(
            "similarProjects"
        );


    if (!container) {

        console.warn(
            "similarProjects container not found."
        );

        return;

    }


    // Show loading state first

    container.innerHTML = `

        <div class="similar-empty">

            Finding historically similar projects...

        </div>

    `;


    try {

        const data =
            await api(
                `/api/projects/${encodeURIComponent(projectId)}/similar?limit=5`
            );


        const projects =
            data.similar_projects ||
            [];


        if (!projects.length) {

            container.innerHTML = `

                <div class="similar-empty">

                    No sufficiently similar projects found.

                </div>

            `;


            return;

        }


        container.innerHTML =
            projects
                .map(
                    project => `

                        <div class="similar-project-card">

                            <div class="similar-project-top">

                                <div>

                                    <div class="similar-project-name">

                                        ${escapeHtml(
                                            project.project_name ||
                                            "Unnamed Project"
                                        )}

                                    </div>


                                    <div class="similar-project-id">

                                        Project ID:
                                        ${escapeHtml(
                                            project.project_id
                                        )}

                                    </div>

                                </div>


                                <div class="similarity-score">

                                    ${number(
                                        project.similarity_score,
                                        1
                                    )}%

                                    <span>
                                        similar
                                    </span>

                                </div>

                            </div>


                            <div class="similar-project-metrics">

                                <div class="similar-metric">

                                    <span>
                                        Progress
                                    </span>

                                    <strong>

                                        ${number(
                                            project.physical_progress_pct,
                                            1
                                        )}%

                                    </strong>

                                </div>


                                <div class="similar-metric">

                                    <span>
                                        Cost Escalation
                                    </span>

                                    <strong>

                                        ${number(
                                            project.cost_escalation_pct,
                                            1
                                        )}%

                                    </strong>

                                </div>


                                <div class="similar-metric">

                                    <span>
                                        Risk
                                    </span>

                                    <strong
                                        class="${riskClass(
                                            project.risk_level
                                        )}"
                                    >

                                        ${escapeHtml(
                                            project.risk_level ||
                                            "—"
                                        )}

                                    </strong>

                                </div>


                                <div class="similar-metric">

                                    <span>
                                        Trajectory
                                    </span>

                                    <strong>

                                        ${escapeHtml(
                                            project.trajectory ||
                                            "—"
                                        )}

                                    </strong>

                                </div>

                            </div>


                            <div class="similar-project-footer">

                                <span>

                                    Priority:

                                    <strong>

                                        ${escapeHtml(
                                            project.priority ||
                                            "—"
                                        )}

                                    </strong>

                                </span>


                                <span>

                                    Expenditure:

                                    <strong>

                                        ₹${number(
                                            project.expenditure_cr,
                                            1
                                        )} Cr

                                    </strong>

                                </span>

                            </div>

                        </div>

                    `
                )
                .join("");


    } catch (error) {

        console.error(
            "Historical intelligence error:",
            error
        );


        container.innerHTML = `

            <div class="similar-error">

                Unable to load historical intelligence.

            </div>

        `;

    }

}


// ============================================================
// MODAL OPEN / CLOSE
// ============================================================

function openModal() {

    const modal =
        document.getElementById(
            "modalOverlay"
        );


    if (!modal) return;


    modal.classList.remove(
        "hidden"
    );


    document.body.classList.add(
        "modal-open"
    );

}


function closeModal() {

    const modal =
        document.getElementById(
            "modalOverlay"
        );


    if (!modal) return;


    modal.classList.add(
        "hidden"
    );


    document.body.classList.remove(
        "modal-open"
    );


    currentProject =
        null;

}


// ============================================================
// FILTERS / SEARCH
// ============================================================

function applyFilters() {

    currentPage =
        1;


    loadProjects(
        1
    );

}


// ============================================================
// ERROR
// ============================================================

function showError(
    message
) {

    const box =
        document.getElementById(
            "errorBox"
        );


    if (!box) {

        console.error(
            message
        );

        return;

    }


    box.textContent =
        message;


    box.classList.remove(
        "hidden"
    );


    setTimeout(
        () => {

            box.classList.add(
                "hidden"
            );

        },
        5000
    );

}


// ============================================================
// RISK DISTRIBUTION CHART
// ============================================================

async function loadRiskChart() {

    const canvas =
        document.getElementById(
            "riskChart"
        );


    if (!canvas) return;


    try {

        const data =
            await api(
                "/api/portfolio/risk-distribution"
            );


        const rows =
            Array.isArray(data)
                ? data
                : [];


        const labels =
            rows.map(
                row =>
                    row.risk_level ||
                    "Unknown"
            );


        const values =
            rows.map(
                row =>
                    Number(
                        row.n ||
                        0
                    )
            );


        // Risk-level colors

        const riskColors =
            rows.map(
                row => {

                    switch (
                        row.risk_level
                    ) {

                        case "High":

                            return "#ef4444";

                        case "Medium":

                            return "#f59e0b";

                        case "Low":

                            return "#22c55e";

                        default:

                            return "#94a3b8";

                    }

                }
            );


        if (riskChart) {

            riskChart.destroy();

        }


        riskChart =
            new Chart(
                canvas,
                {

                    type: "doughnut",

                    data: {

                        labels: labels,

                        datasets: [

                            {
                                data: values,

                                backgroundColor:
                                    riskColors,

                                borderColor:
                                    "#ffffff",

                                borderWidth: 2,

                                hoverOffset: 6
                            }

                        ]

                    },

                    options: {

                        responsive: true,

                        maintainAspectRatio: false,

                        plugins: {

                            legend: {

                                position: "bottom"

                            }

                        }

                    }

                }
            );


    } catch (error) {

        console.error(
            "Risk chart error:",
            error
        );

    }

}


// ============================================================
// EVENT LISTENERS
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    () => {

        console.log(
            "TriNetra frontend initialized."
        );


        // Initial data

        checkConnection();


        loadSummary();


        loadFilters();


        loadProjects(
            1
        );


        loadRiskChart();


        // ----------------------------------------------------
        // SEARCH
        // ----------------------------------------------------

        const search =
            document.getElementById(
                "search"
            );


        if (search) {

            search.addEventListener(
                "input",
                debounce(
                    () =>
                        loadProjects(
                            1
                        ),
                    300
                )
            );


            search.addEventListener(
                "keypress",
                event => {

                    if (
                        event.key ===
                        "Enter"
                    ) {

                        loadProjects(
                            1
                        );

                    }

                }
            );

        }


        // ----------------------------------------------------
        // FILTERS
        // ----------------------------------------------------

        [
            "riskFilter",
            "trajectoryFilter",
            "priorityFilter"
        ]
        .forEach(
            id => {

                const element =
                    document.getElementById(
                        id
                    );


                if (element) {

                    element.addEventListener(
                        "change",
                        () =>
                            loadProjects(
                                1
                            )
                    );

                }

            }
        );


        // ----------------------------------------------------
        // PAGE SIZE
        // ----------------------------------------------------

        const pageSize =
            document.getElementById(
                "pageSize"
            );


        if (pageSize) {

            pageSize.addEventListener(
                "change",
                () => {

                    currentPageSize =
                        Number(
                            pageSize.value
                        ) || 25;


                    loadProjects(
                        1
                    );

                }
            );

        }


        // ----------------------------------------------------
        // PAGINATION
        // ----------------------------------------------------

        const prev =
            document.getElementById(
                "prevButton"
            );


        const next =
            document.getElementById(
                "nextButton"
            );


        if (prev) {

            prev.addEventListener(
                "click",
                () => {

                    if (
                        currentPage >
                        1
                    ) {

                        loadProjects(
                            currentPage -
                            1
                        );

                    }

                }
            );

        }


        if (next) {

            next.addEventListener(
                "click",
                () => {

                    loadProjects(
                        currentPage +
                        1
                    );

                }
            );

        }


        // ----------------------------------------------------
        // CLOSE MODAL
        // ----------------------------------------------------

        const close =
            document.getElementById(
                "closeModal"
            );


        if (close) {

            close.addEventListener(
                "click",
                closeModal
            );

        }


        // Close when clicking overlay

        const overlay =
            document.getElementById(
                "modalOverlay"
            );


        if (overlay) {

            overlay.addEventListener(
                "click",
                event => {

                    if (
                        event.target ===
                        overlay
                    ) {

                        closeModal();

                    }

                }
            );

        }


        // ESC key

        document.addEventListener(
            "keydown",
            event => {

                if (
                    event.key ===
                    "Escape"
                ) {

                    closeModal();

                }

            }
        );

    }
);


// ============================================================
// DEBOUNCE
// ============================================================

function debounce(
    callback,
    delay
) {

    let timeout;


    return (
        ...args
    ) => {

        clearTimeout(
            timeout
        );


        timeout =
            setTimeout(
                () =>
                    callback(
                        ...args
                    ),
                delay
            );

    };

}


// ============================================================
// EXPOSE FUNCTIONS
// ============================================================

window.openProject =
    openProject;


window.closeModal =
    closeModal;


window.loadProjects =
    loadProjects;