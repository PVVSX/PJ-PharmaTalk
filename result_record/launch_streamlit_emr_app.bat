@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem เปลี่ยนไปโฟลเดอร์โปรเจกต์ (ที่วางไฟล์ .bat นี้)
cd /d "%~dp0"

title EMR Streamlit App

echo ========================================
echo   ระบบบันทึกเวชระเบียนอัตโนมัติ (EMR)
echo   streamlit_emr_app.py
echo ========================================
echo.

rem ใช้ Python จาก venv ถ้ามี (เลือกใช้ได้)
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON=venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ไม่พบ Python กรุณาติดตั้ง Python หรือสร้าง virtual environment ก่อน
    pause
    exit /b 1
)

"%PYTHON%" -m streamlit --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] ยังไม่มี Streamlit กำลังติดตั้งจาก demo_app\requirements.txt ...
    "%PYTHON%" -m pip install -r "demo_app\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] ติดตั้งแพ็กเกจไม่สำเร็จ
        pause
        exit /b 1
    )
)

echo.
echo กำลังเปิดแอปที่ http://localhost:8501
echo กด Ctrl+C ในหน้าต่างนี้เพื่อหยุดเซิร์ฟเวอร์
echo.

"%PYTHON%" -m streamlit run "streamlit_emr_app.py" --server.address localhost --server.port 8501

if errorlevel 1 (
    echo.
    echo [ERROR] รัน Streamlit ไม่สำเร็จ
    pause
    exit /b 1
)

endlocal
