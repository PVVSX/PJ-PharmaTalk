@echo off
REM PharmaTalk Lab - One-click Start Script for Windows

cd /d "%~dp0"

echo ==========================================
echo  Starting PharmaTalk Lab...
echo ==========================================

REM 1. Check & Create Virtual Environment
if not exist "venv" (
    echo [Info] Creating virtual environment (venv)...
    python -m venv venv
)

REM 2. Activate Virtual Environment
call venv\Scripts\activate.bat

REM 3. Check Dependencies
python -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo [Info] Installing dependencies from lab/requirements.txt...
    python -m pip install --upgrade pip
    pip install -r lab/requirements.txt
)

REM 4. Check API Key
if exist ".groq_api_key" (
    echo [Pass] Groq API Key detected.
) else (
    echo [Warning] .groq_api_key not found. Please extract pharmatalk_offline_assets.zip to project root.
)

REM 5. Launch Streamlit Lab
echo [Info] Launching Streamlit on port 8525...
echo [Info] URL: http://localhost:8525
streamlit run lab/app.py --server.port 8525
pause
