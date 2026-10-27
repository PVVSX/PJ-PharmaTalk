# PharmaLog AI: Terminal Setup & Run Cheat Sheet (คู่มือคำสั่งใน Terminal)
## ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์

คู่มือนี้สรุปคำสั่งทั้งหมดสำหรับนำไปรันบนคอมพิวเตอร์เครื่องใหม่ตั้งแต่ต้นจนเปิดใช้งานได้สมบูรณ์

---

## ขั้นตอนที่ 1: ติดตั้ง ffmpeg ในเครื่อง

### สำหรับ macOS:
```bash
brew install ffmpeg
```

### สำหรับ Windows (PowerShell Run as Administrator):
```powershell
winget install Gyan.FFmpeg
```

---

## ขั้นตอนที่ 2: Clone โค้ดลงเครื่อง

```bash
git clone https://github.com/PVVSX/PharmaLog.git
cd PharmaLog
```

---

## ขั้นตอนที่ 3: ติดตั้ง Python Dependencies

### สำหรับ macOS / Linux:
```bash
# 1. สร้างและเปิดใช้งาน Virtual Environment
python3 -m venv .venv
source .venv/bin/activate

# 2. ติดตั้งแพ็กเกจที่จำเป็น
pip install fastapi uvicorn sqlalchemy python-multipart firebase-admin requests streamlit streamlit-autorefresh groq pydub soundfile librosa torch
pip install "nemo_toolkit[asr]"
```

### สำหรับ Windows (PowerShell / CMD):
```powershell
# 1. สร้างและเปิดใช้งาน Virtual Environment
python -m venv .venv
.venv\Scripts\activate

# 2. ติดตั้งแพ็กเกจที่จำเป็น
pip install fastapi uvicorn sqlalchemy python-multipart firebase-admin requests streamlit streamlit-autorefresh groq pydub soundfile librosa torch
pip install "nemo_toolkit[asr]"
```

---

## ขั้นตอนที่ 4: วางไฟล์คีย์และโมเดล (ที่อยู่นอก Git)

ก๊อปปี้ 3 ไฟล์นี้มาวางในโฟลเดอร์โปรเจกต์:

1. **โมเดลเสียง:** สร้างโฟลเดอร์ `models` แล้ววาง `typhoon-asr-realtime.nemo` ไว้ที่:
   ```text
   PharmaLog/models/typhoon-asr-realtime.nemo
   ```
2. **Groq API Key:** สร้างไฟล์ `.groq_api_key` ไว้ที่ Root ของโปรเจกต์:
   ```text
   PharmaLog/.groq_api_key
   ```
3. **Firebase Key:** นำไฟล์ `serviceAccountKey.json` ไปวางในโฟลเดอร์ `core_api/`:
   ```text
   PharmaLog/core_api/serviceAccountKey.json
   ```

---

## ขั้นตอนที่ 5: คำสั่งเปิดรันโปรแกรม (เปิด 3 หน้าต่าง Terminal)

เปิด Terminal หรือ PowerShell แยกกัน **3 หน้าต่าง** แล้วรันจากโฟลเดอร์ Root ของโปรเจกต์:

### หน้าต่างที่ 1: Consent & Bridge API (พอร์ต 8500)
```bash
# macOS / Linux:
python3 api.py

# Windows:
python api.py
```

---

### หน้าต่างที่ 2: Core API ประมวลผล ASR & EMR (พอร์ต 8080)
```bash
# macOS / Linux:
cd core_api && python3 main.py

# Windows:
cd core_api
python main.py
```
*(รอประมาณ 15-20 วินาทีจนขึ้น `Typhoon ASR Model loaded successfully!`)*

---

### หน้าต่างที่ 3: หน้าจอเภสัชกร Streamlit (พอร์ต 8515)
```bash
# macOS / Linux:
python3 -m streamlit run unified_app/app.py --server.address 127.0.0.1 --server.port 8515

# Windows:
python -m streamlit run unified_app\app.py --server.address 127.0.0.1 --server.port 8515
```

---

## ขั้นตอนที่ 6: เข้าใช้งานในเบราว์เซอร์

1. **หน้าจอยินยอม (คนไข้):** [http://127.0.0.1:8500](http://127.0.0.1:8500)
2. **หน้าจอหลัก (เภสัชกร):** [http://127.0.0.1:8515](http://127.0.0.1:8515)
3. **เช็กสถานะ Core API:** [http://127.0.0.1:8080/health](http://127.0.0.1:8080/health)
