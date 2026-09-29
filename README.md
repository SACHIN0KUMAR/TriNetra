# TriNetra — National Infrastructure Growth & Development Intelligence



---

## What is TriNetra?

**TriNetra** (Sanskrit: *Three Eyes*) is an end-to-end AI platform for monitoring, analysing, and predicting risk in India's national infrastructure portfolio. It brings together machine learning, explainable AI (SHAP), and an LLM-powered assistant to give policymakers and analysts a single pane of glass over 2,000+ infrastructure projects tracked by MoSPI/PAIMANA.

---

## Key Features

| Feature | Description |
|---|---|
| **Public Dashboard** | Live KPI cards, sector-wise distribution, cost overview funnel, physical progress bar chart, risk distribution donut, and top-10 cost-escalation table — all filter-aware |
| **AI Project Monitoring** | Per-project risk score, ML deterioration probability, SHAP-based explanation, trajectory timeline, similar project finder |
| **LLM Assistant** | Local Ollama (llama3.2) or Gemini-powered Q&A chatbot scoped to the project portfolio |
| **ML Methodology Panel** | Comparative model card — Random Forest vs XGBoost vs Linear Regression |
| **PDF Export** | Per-project downloadable risk report |
| **Filterable Analytics** | Sector, Ministry, and Cost-bracket filters drive all charts and KPIs in real time |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Browser                          │
│  landing.html → dashboard.html → projects.html      │
│  Chart.js · Vanilla JS · CSS custom properties      │
└────────────────────┬────────────────────────────────┘
                     │ HTTP (FastAPI)
┌────────────────────▼────────────────────────────────┐
│              FastAPI Backend  (app/main.py)          │
│                                                     │
│  /api/dashboard_data   — filtered aggregate stats   │
│  /api/projects         — paginated project list     │
│  /api/projects/{id}    — project detail + ML scores │
│  /api/projects/{id}/explanation — SHAP narrative    │
│  /api/projects/{id}/similar     — KNN neighbours    │
│  /api/projects/{id}/report/pdf  — PDF export        │
│  /api/chat             — LLM assistant              │
│  /api/filters          — dropdown population        │
└──────────┬───────────────────────┬──────────────────┘
           │                       │
    ┌──────▼──────┐       ┌────────▼────────┐
    │  SQLite DB  │       │   ML Models     │
    │ trinetra.db │       │  (scikit-learn) │
    │  2 074 rows │       │  trajectory.pkl │
    └─────────────┘       │  cost_overrun   │
                          │  time_overrun   │
                          └────────▲────────┘
                                   │
                          ┌────────┴────────┐
                          │  LLM Backend    │
                          │  Ollama llama3.2│
                          │  (local/offline)│
                          └─────────────────┘
```

---

## ML Methodology

Three models compete; **Random Forest** is selected as production model based on RMSE and SHAP interpretability stability:

| Model | RMSE | R² | Notes |
|---|---|---|---|
| **Random Forest**  | 8.2 | 0.91 | Robust to outliers, stable SHAP values |
| XGBoost | 9.1 | 0.88 | Faster, slightly worse on long-tail projects |
| Linear Regression | 18.4 | 0.61 | Baseline; poor on non-linear cost patterns |

**Features used:** Cost escalation %, Expenditure-progress gap, Trajectory score, Progress change (pp), Delay component, Trend component.

---

## Quick Start

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com) installed and running with `llama3.2` pulled

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Add Gemini API key for cloud LLM
echo "YOUR_KEY_HERE" > api_key.txt

# 3. Run the server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open **http://localhost:8000** in your browser.

### Windows one-liner
```bat
run.bat
```

---

## Project Structure

```
TriNetra_Full_Project/
├── app/
│   └── main.py              # FastAPI backend — all routes & business logic
├── data/
│   └── trinetra.db          # SQLite database (2 074 projects)
├── models/
│   ├── trajectory_model.pkl
│   ├── cost_overrun_model.pkl
│   └── time_overrun_model.pkl
├── scripts/
│   ├── ingest.py            # Raw data ingestion from MoSPI Excel
│   ├── train_ml.py          # Model training pipeline
│   └── backfill_sector.py   # Sector metadata enrichment
├── static/
│   ├── landing.html         # Entry point with live portfolio stats
│   ├── dashboard.html       # Public aggregate dashboard
│   ├── projects.html        # AI project monitoring app
│   ├── css/style.css
│   └── js/app.js
├── requirements.txt
├── run.bat / run.sh
└── README.md
```

---

##  LLM Configuration

| Mode | Setup |
|---|---|
| **Local (Ollama)** | Leave `api_key.txt` empty. Backend auto-falls back to `http://localhost:11434`. Pull model: `ollama pull llama3.2` |
| **Gemini Cloud** | Put your API key (starts with `AQ…`) in `api_key.txt` |

---

##  Data Source

Data sourced from **MoSPI PAIMANA** (Project Implementation & Monitoring Analysis) public reports covering Central Sector Infrastructure Projects with original cost ≥ ₹150 crore.

- **Projects tracked:** 2,074
- **Sectors:** Railways, Roads & Highways, Energy, Coal, Oil & Gas, Healthcare, Education, and more
- **Report month:** August 2026

---

##  Team

Built for the National Hackathon on Infrastructure Intelligence.

---

##  License

MIT License — open for educational and research use.
