@echo off
title TriNetra — National Infrastructure Intelligence

cd /d %~dp0

echo.
echo  ████████╗██████╗ ██╗███╗   ██╗███████╗████████╗██████╗  █████╗
echo  ╚══██╔══╝██╔══██╗██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██╔══██╗
echo     ██║   ██████╔╝██║██╔██╗ ██║█████╗     ██║   ██████╔╝███████║
echo     ██║   ██╔══██╗██║██║╚██╗██║██╔══╝     ██║   ██╔══██╗██╔══██║
echo     ██║   ██║  ██║██║██║ ╚████║███████╗   ██║   ██║  ██║██║  ██║
echo     ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
echo.
echo  National Infrastructure Growth ^& Development Intelligence
echo  ============================================================
echo.

:: Create venv if not exists
if not exist .venv (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
)

:: Activate and install deps
echo [2/3] Installing dependencies...
call .venv\Scripts\activate
pip install -r requirements.txt -q

:: Start server
echo [3/3] Starting TriNetra server at http://localhost:8000
echo.
echo  Open your browser at: http://localhost:8000
echo  Press Ctrl+C to stop.
echo.

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000