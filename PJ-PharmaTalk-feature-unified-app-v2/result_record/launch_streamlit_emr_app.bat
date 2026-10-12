@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

rem เปลี่ยนไปโฟลเดอร์โปรเจกต์ (ที่วางไฟล์ .bat นี้)
cd /d "%~dp0"

title EMR Streamlit App

echo ========================================
echo   ระบบบันทึกเวชระเบียนอัตโนมัติ (EMR)
echo   streamlit_emr_app.py
echo ========================================
echo.

set "PYTHON="

rem ใช้ .venv ในโปรเจกต์เป็นหลัก (แยกจาก Python ระบบ)
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    call :create_venv
)

if not defined PYTHON (
    echo [ERROR] ไม่พบ Python 3.10 ขึ้นไป หรือสร้าง .venv ไม่สำเร็จ
    echo         ติดตั้งจาก https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [INFO] ใช้ Python: !PYTHON!
"!PYTHON!" --version
echo.

"!PYTHON!" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] ต้องใช้ Python 3.10 ขึ้นไป
    pause
    exit /b 1
)

echo [INFO] เตรียม pip และ build tools ...
"!PYTHON!" -m pip install --upgrade pip
"!PYTHON!" -m pip install "setuptools>=70,<82" wheel Cython
if errorlevel 1 (
    echo [ERROR] เตรียม pip / build tools ไม่สำเร็จ
    pause
    exit /b 1
)

rem บังคับใช้ wheel ของ PyYAML — กัน error build บน Windows
echo [INFO] ติดตั้ง PyYAML จาก wheel ...
"!PYTHON!" -m pip install --only-binary=PyYAML "PyYAML>=6.0.2"
if errorlevel 1 (
    echo [ERROR] ติดตั้ง PyYAML ไม่สำเร็จ
    pause
    exit /b 1
)

echo [INFO] ติดตั้งแพ็กเกจหลัก demo_app\requirements-core.txt ...
"!PYTHON!" -m pip install -r "demo_app\requirements-core.txt"
if errorlevel 1 (
    echo [ERROR] ติดตั้งแพ็กเกจหลักไม่สำเร็จ
    pause
    exit /b 1
)

echo [INFO] ติดตั้งแพ็กเกจ ASR demo_app\requirements-asr.txt ...
echo        ครั้งแรกอาจใช้เวลานาน 10-30 นาที
"!PYTHON!" -m pip install --prefer-binary -r "demo_app\requirements-asr.txt"
if errorlevel 1 (
    echo [WARN] ติดตั้ง ASR ไม่ครบ — แอปยังเปิดได้ แต่ถอดเสียง/diarization อาจใช้ไม่ได้
    echo        ลองรันเอง: .venv\Scripts\python.exe -m pip install -r demo_app\requirements-asr.txt
    echo.
)

set "PORT_START=8501"
if defined EMR_STREAMLIT_PORT set "PORT_START=!EMR_STREAMLIT_PORT!"
set "STREAMLIT_PORT="
call :pick_free_port !PORT_START!
if not defined STREAMLIT_PORT (
    echo [ERROR] พอร์ต !PORT_START!-!PORT_END! ถูกใช้งานหมดแล้ว
    echo         ปิด Streamlit เก่า หรือตั้ง EMR_STREAMLIT_PORT=8511
    pause
    exit /b 1
)

if not "!STREAMLIT_PORT!"=="!PORT_START!" (
    echo [WARN] พอร์ต !PORT_START! ถูกใช้อยู่ — ใช้พอร์ต !STREAMLIT_PORT! แทน
    echo.
)

echo กำลังเปิดแอปที่ http://localhost:!STREAMLIT_PORT!
echo กด Ctrl+C ในหน้าต่างนี้เพื่อหยุดเซิร์ฟเวอร์
echo.

"!PYTHON!" -m streamlit run "streamlit_emr_app.py" --server.address localhost --server.port !STREAMLIT_PORT!

if errorlevel 1 (
    echo.
    echo [ERROR] รัน Streamlit ไม่สำเร็จ
    pause
    exit /b 1
)

endlocal
exit /b 0

:create_venv
for %%V in (3.12 3.11 3.10) do (
    if not defined PYTHON (
        py -%%V -c "import sys" >nul 2>&1
        if not errorlevel 1 (
            echo [INFO] สร้าง virtual environment .venv ด้วย Python %%V ...
            py -%%V -m venv .venv
            if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
        )
    )
)
exit /b 0

:pick_free_port
set "START_PORT=%~1"
set /a "END_PORT=START_PORT+9"
set "PORT_END=!END_PORT!"
for /L %%P in (!START_PORT!,1,!END_PORT!) do (
    if not defined STREAMLIT_PORT (
        call :is_port_free %%P
        if errorlevel 1 set "STREAMLIT_PORT=%%P"
    )
)
exit /b 0

:is_port_free
set "CHECK_PORT=%~1"
netstat -ano | findstr /C:":%CHECK_PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0
