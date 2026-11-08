# PharmaLog AI: Terminal Setup & Run Cheat Sheet (คู่มือคำสั่งใน Terminal)
## ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์

คำสั่งสำหรับติดตั้งบนคอมพิวเตอร์เครื่องใหม่จนเปิดใช้งานได้ (ปรับปรุง 2026-11-07)

---

## ขั้นตอนที่ 1: เตรียมเครื่อง

- **Python 3.10–3.12** (แนะนำ 3.11) — **Python 3.13 ใช้ไม่ได้** เพราะ NeMo ยังไม่รองรับ
  - macOS: `brew install python@3.11`
  - Windows: ติดตั้ง Python 3.11 จาก python.org (ติ๊ก "Add to PATH")
- RAM: ใช้ Typhoon Whisper Large v3 (ค่าหลัก) ต้อง 16 GB ขึ้นไป หรือมี GPU NVIDIA; เครื่อง 8 GB ให้ใช้ `PHARMALOG_STT_ENGINE=realtime`
- ดิสก์ว่างอย่างน้อย 20 GB

---

## ขั้นตอนที่ 2: Clone โค้ด

```bash
git clone https://github.com/PVVSX/PharmaLog.git
cd PharmaLog
```

---

## ขั้นตอนที่ 3: ติดตั้ง Python Dependencies

### macOS (ทางลัด)
ดับเบิลคลิก `setup_pharmalog.command`

### macOS / Linux
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)
```powershell
py -3.11 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
ถ้ามี GPU NVIDIA ให้ติดตั้ง torch รุ่น CUDA ตามคำสั่งจาก https://pytorch.org ก่อน `pip install -r requirements.txt`

---

## ขั้นตอนที่ 4: วางไฟล์ที่อยู่นอก Git

1. **โมเดล Typhoon ASR Realtime** (ตัวสำรอง): `PharmaLog/models/typhoon-asr-realtime.nemo`
2. **Groq API Key:** `PharmaLog/.groq_api_key` (บรรทัดเดียว)
3. **Firebase Key** (เฉพาะถ้าใช้ Cloud): `PharmaLog/core_api/serviceAccountKey.json`

Typhoon Whisper Large v3 จะดาวน์โหลดเองจาก Hugging Face ครั้งแรก (~6.2 GB)

---

## ขั้นตอนที่ 5: ตั้งค่า (`pharmalog.env`)

```text
PHARMALOG_STT_ENGINE=whisper          # หรือ realtime สำหรับเครื่อง RAM น้อย
PHARMALOG_WHISPER_MODEL=typhoon-ai/typhoon-whisper-large-v3
PHARMALOG_ROLE_RULES=1
```
ตัวแปรอื่นดูตารางใน `README.md` ส่วนที่ 5

---

## ขั้นตอนที่ 6: เปิดระบบ

### macOS
ดับเบิลคลิก `start_pharmalog.command` (เปิดครบ 4 ส่วนและเปิดเบราว์เซอร์ให้)

### รันเอง (4 หน้าต่าง Terminal จากโฟลเดอร์ root หลัง activate venv)
```bash
python api.py
```
```bash
cd core_api && python main.py
```
```bash
streamlit run pharmacist_app.py --server.address 127.0.0.1 --server.port 8501
```
```bash
streamlit run unified_app/app.py --server.address 127.0.0.1 --server.port 8515
```
Windows ใช้ `unified_app\app.py` และตั้งตัวแปรด้วย `$env:PHARMALOG_STT_ENGINE="realtime"` ก่อนรันถ้าต้องการ
(สคริปต์ `.command` ใช้ได้เฉพาะ macOS — บน Windows ต้องตั้งค่าจาก `pharmalog.env` เองด้วย `$env:`)

---

## ขั้นตอนที่ 7: เข้าใช้งาน

1. หน้ายินยอม (คนไข้): http://localhost:8500
2. หน้าเภสัชกร: http://127.0.0.1:8501
3. หน้าหลังบ้าน: http://127.0.0.1:8515
4. สถานะ Core API: http://127.0.0.1:8080/health (ต้องได้ `"asr_loaded": true`)

---

## ทดสอบระบบ

```bash
python tests/stt_compare.py
python tests/choose_engine.py
PHARMALOG_DISABLE_CLOUD=1 python tests/e2e_check.py
```
รายละเอียดดู `README.md` ส่วนที่ 6 และ `WHISPER_TEST_GUIDE.md`
