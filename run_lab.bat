@echo off
REM PharmaLog AI Lab: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ - One-click Start Script for Windows

cd /d "%~dp0"

echo ==========================================
echo  Starting PharmaLog AI Lab...
echo  ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์
echo ==========================================

REM 0. Auto-merge if user dragged pharmalog_offline_assets or pharmatalk_offline_assets folder into project
for %%D in (pharmalog_offline_assets pharmatalk_offline_assets) do (
    if exist "%%D" (
        echo [Info] Detected %%D folder, ensuring files are placed...
        if exist "%%D\.groq_api_key" copy /Y "%%D\.groq_api_key" ".\" >nul 2>&1
        if exist "%%D\.gemini_api_key" copy /Y "%%D\.gemini_api_key" ".\" >nul 2>&1
        if exist "%%D\api_keys\.groq_api_key" copy /Y "%%D\api_keys\.groq_api_key" ".\" >nul 2>&1
        if exist "%%D\api_keys\.gemini_api_key" copy /Y "%%D\api_keys\.gemini_api_key" ".\" >nul 2>&1
        if not exist "models" mkdir models
        if not exist "core_api" mkdir core_api
        if not exist "record" mkdir record
        if exist "%%D\models\typhoon-asr-realtime.nemo" copy /Y "%%D\models\typhoon-asr-realtime.nemo" "models\" >nul 2>&1
        if exist "%%D\core_api\serviceAccountKey.json" copy /Y "%%D\core_api\serviceAccountKey.json" "core_api\" >nul 2>&1
        if exist "%%D\credentials\serviceAccountKey.json" copy /Y "%%D\credentials\serviceAccountKey.json" "core_api\" >nul 2>&1
        if exist "%%D\core_api\api_queue.db" copy /Y "%%D\core_api\api_queue.db" "core_api\" >nul 2>&1
        if exist "%%D\databases\api_queue.db" copy /Y "%%D\databases\api_queue.db" "core_api\" >nul 2>&1
        if exist "%%D\record\pharmatalk.db" copy /Y "%%D\record\pharmatalk.db" "record\" >nul 2>&1
        if exist "%%D\databases\pharmatalk.db" copy /Y "%%D\databases\pharmatalk.db" "record\" >nul 2>&1
        if exist "%%D\record\pharmalog.db" copy /Y "%%D\record\pharmalog.db" "record\" >nul 2>&1
        if exist "%%D\databases\pharmalog.db" copy /Y "%%D\databases\pharmalog.db" "record\" >nul 2>&1
    )
)

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
    echo [Warning] .groq_api_key not found. Please extract offline assets zip to project root.
)

REM 5. Launch Streamlit Lab
echo [Info] Launching Streamlit on port 8525...
echo [Info] URL: http://localhost:8525
streamlit run lab/app.py --server.port 8525
pause
