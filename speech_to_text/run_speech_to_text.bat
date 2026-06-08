@echo off
chcp 65001 >nul
cls
echo ========================================
echo   Speech-to-Text with Typhoon ASR
echo ========================================
echo.

REM ตรวจสอบว่า Python ติดตั้งหรือยัง
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] ไม่พบ Python
    echo กรุณาติดตั้ง Python จาก https://www.python.org/downloads/
    pause
    exit /b 1
)

REM แสดงเวอร์ชัน Python
echo [INFO] ตรวจสอบ Python...
python --version
echo.

REM ตรวจสอบว่า streamlit ติดตั้งหรือยัง
where streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] ไม่พบ Streamlit
    echo กำลังติดตั้ง Streamlit...
    pip install streamlit
    if %errorlevel% neq 0 (
        echo [ERROR] ไม่สามารถติดตั้ง Streamlit ได้
        echo กรุณาติดตั้งด้วยคำสั่ง: pip install streamlit
        pause
        exit /b 1
    )
    echo [SUCCESS] ติดตั้ง Streamlit สำเร็จ
    echo.
)

REM ตรวจสอบว่าโฟลเดอร์ app มีอยู่หรือไม่
if not exist "app" (
    echo [ERROR] ไม่พบโฟลเดอร์ app
    echo กรุณาตรวจสอบว่าไฟล์อยู่ในตำแหน่งที่ถูกต้อง
    pause
    exit /b 1
)

REM ตรวจสอบว่าไฟล์หลักมีอยู่หรือไม่
if not exist "app\speech_to_text_streamlit.py" (
    echo [ERROR] ไม่พบไฟล์ app\speech_to_text_streamlit.py
    echo กรุณาตรวจสอบว่าไฟล์อยู่ในตำแหน่งที่ถูกต้อง
    pause
    exit /b 1
)

REM ตรวจสอบว่าโมเดลมีอยู่หรือไม่ (optional check)
if not exist "app\backend\typhoon-asr-realtime\typhoon-asr-realtime.nemo" (
    echo [WARNING] ไม่พบไฟล์โมเดล
    echo โมเดลควรอยู่ที่: app\backend\typhoon-asr-realtime\typhoon-asr-realtime.nemo
    echo โปรแกรมอาจไม่สามารถทำงานได้
    echo.
    choice /C YN /M "ต้องการดำเนินการต่อหรือไม่"
    if errorlevel 2 exit /b 1
    echo.
)

echo ========================================
echo   กำลังเปิดโปรแกรม Speech-to-Text...
echo ========================================
echo.
echo [INFO] เปิดเบราว์เซอร์อัตโนมัติ...
echo [INFO] กด Ctrl+C เพื่อหยุดโปรแกรม
echo.

cd app
if %errorlevel% neq 0 (
    echo [ERROR] ไม่สามารถเข้าโฟลเดอร์ app ได้
    pause
    exit /b 1
)

REM รัน Streamlit
streamlit run speech_to_text_streamlit.py

REM ตรวจสอบ exit code
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] เกิดข้อผิดพลาดในการรันโปรแกรม
    echo.
    echo วิธีแก้ไข:
    echo 1. ตรวจสอบว่า Streamlit ติดตั้งแล้ว: pip install streamlit
    echo 2. ตรวจสอบว่า dependencies ติดตั้งแล้ว: pip install -r requirements.txt
    echo 3. ตรวจสอบว่าโมเดลอยู่ในตำแหน่งที่ถูกต้อง
    echo.
    pause
    exit /b 1
)

pause

