@echo off
REM PharmaTalk Main Application (Unified App) - One-click Start Script for Windows

cd /d "%~dp0"

echo ==========================================
echo  Starting PharmaTalk Main Application...
echo ==========================================

REM 0. Auto-merge if user dragged pharmatalk_offline_assets folder into project
if exist "pharmatalk_offline_assets" (
    echo [Info] Detected pharmatalk_offline_assets folder, ensuring files are placed...
    if exist "pharmatalk_offline_assets\.groq_api_key" copy /Y "pharmatalk_offline_assets\.groq_api_key" ".\" >nul 2>&1
    if exist "pharmatalk_offline_assets\.gemini_api_key" copy /Y "pharmatalk_offline_assets\.gemini_api_key" ".\" >nul 2>&1
    if exist "pharmatalk_offline_assets\api_keys\.groq_api_key" copy /Y "pharmatalk_offline_assets\api_keys\.groq_api_key" ".\" >nul 2>&1
    if exist "pharmatalk_offline_assets\api_keys\.gemini_api_key" copy /Y "pharmatalk_offline_assets\api_keys\.gemini_api_key" ".\" >nul 2>&1
    if not exist "models" mkdir models
    if not exist "core_api" mkdir core_api
    if not exist "record" mkdir record
    if exist "pharmatalk_offline_assets\models\typhoon-asr-realtime.nemo" copy /Y "pharmatalk_offline_assets\models\typhoon-asr-realtime.nemo" "models\" >nul 2>&1
    if exist "pharmatalk_offline_assets\core_api\serviceAccountKey.json" copy /Y "pharmatalk_offline_assets\core_api\serviceAccountKey.json" "core_api\" >nul 2>&1
    if exist "pharmatalk_offline_assets\credentials\serviceAccountKey.json" copy /Y "pharmatalk_offline_assets\credentials\serviceAccountKey.json" "core_api\" >nul 2>&1
    if exist "pharmatalk_offline_assets\core_api\api_queue.db" copy /Y "pharmatalk_offline_assets\core_api\api_queue.db" "core_api\" >nul 2>&1
    if exist "pharmatalk_offline_assets\databases\api_queue.db" copy /Y "pharmatalk_offline_assets\databases\api_queue.db" "core_api\" >nul 2>&1
    if exist "pharmatalk_offline_assets\record\pharmatalk.db" copy /Y "pharmatalk_offline_assets\record\pharmatalk.db" "record\" >nul 2>&1
    if exist "pharmatalk_offline_assets\databases\pharmatalk.db" copy /Y "pharmatalk_offline_assets\databases\pharmatalk.db" "record\" >nul 2>&1
)

REM 1. Check & Create Virtual Environment
if not exist "venv" (
    echo [Info] Creating virtual environment (venv)...
    python -m venv venv
)

REM 2. Activate Virtual Environment
call venv\Scripts\activate.bat

REM 3. Check Dependencies
python -c "import streamlit, fastapi, firebase_admin" >nul 2>&1
if %errorlevel% neq 0 (
    echo [Info] Installing dependencies for Main Application...
    python -m pip install --upgrade pip
    pip install streamlit fastapi uvicorn firebase-admin google-cloud-firestore google-cloud-storage reportlab
    pip install -r lab/requirements.txt
)

REM 4. Check API Key
if exist ".groq_api_key" (
    echo [Pass] Groq API Key detected.
) else (
    echo [Warning] .groq_api_key not found. Please extract pharmatalk_offline_assets.zip to project root.
)

REM 5. Launch Streamlit Unified App
echo [Info] Launching PharmaTalk Unified App on port 8515...
echo [Info] URL: http://localhost:8515
streamlit run unified_app/app.py --server.port 8515
pause
