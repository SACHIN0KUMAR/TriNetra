@echo off

cd /d %~dp0

if not exist .venv (
    python -m venv .venv
)

call .venv\Scripts\activate

python -m pip install --upgrade pip

pip install -r requirements.txt

if not exist data\trinetra.db (
    python scripts\ingest.py
)

python scripts\train_trajectory_model.py

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000