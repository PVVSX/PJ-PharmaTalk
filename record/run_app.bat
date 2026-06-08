@echo off
setlocal

rem Change to this script's directory
cd /d "%~dp0"

rem Check Python availability
where python >nul 2>&1
if errorlevel 1 (
  echo Python not found in PATH. Please install Python 3 and try again.
  pause
  exit /b 1
)

rem Create virtual environment if missing
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)

rem Activate venv
call ".venv\Scripts\activate.bat"

rem Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

rem Run the Streamlit app
streamlit run app.py

rem Keep window open after exit
pause


