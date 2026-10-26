# PharmaTalk — AI-Powered Pharmacy Speech-to-Text & EMR System

PharmaTalk คือระบบปัญญาประดิษฐ์ช่วยบันทึกและสกัดข้อมูลเวชระเบียนการบริบาลทางเภสัชกรรม (Electronic Medical Record: EMR) จากบทสนทนาระหว่างเภสัชกรและผู้ป่วยแบบอัตโนมัติ รองรับการถอดเสียงภาษาไทยความเร็วสูง (Real-time ASR), การตรวจแก้คำศัพท์เภสัชกรรมด้วยพจนานุกรมความปลอดภัย, การวิเคราะห์และสกัด EMR ด้วยโมเดลภาษาขนาดใหญ่ (LLMs), และการส่งออกรายงานเวชระเบียนทางการแพทย์ในรูปแบบ PDF

---

## 1. วิธีเริ่มต้นใช้งานด่วนบนเครื่องใหม่ (Quick Start)

ระบบได้รับการออกแบบให้ติดตั้งและเปิดใช้งานได้ทันทีใน 3 ขั้นตอน โดยไม่ต้องตั้งค่าหรือกรอก API Key เอง:

### ขั้นตอนที่ 1: โคลนโค้ดจาก Git
```bash
git clone https://github.com/PVVSX/PJ-PharmaTalk.git
cd PJ-PharmaTalk
```

### ขั้นตอนที่ 2: แตกไฟล์ ZIP Assets ลงในโฟลเดอร์โปรเจกต์
นำไฟล์ `pharmatalk_offline_assets.zip` มาวางไว้ที่โฟลเดอร์รากของโปรเจกต์ แล้วแตกไฟล์:
- **macOS / Linux:**
  ```bash
  unzip -o pharmatalk_offline_assets.zip
  ```
- **Windows:**
  คลิกขวาที่ไฟล์ `pharmatalk_offline_assets.zip` แล้วเลือก **Extract Here** (แตกไฟล์ลงในโฟลเดอร์ปัจจุบัน)

*(ไฟล์ API Key, โมเดล Typhoon ASR, และฐานข้อมูล SQLite จะถูกจัดวางลงตำแหน่งที่ถูกต้องทันที)*

### ขั้นตอนที่ 3: สั่งรันด้วยคลิกเดียว (One-Click Launch)
- **สำหรับ Windows:**
  ดับเบิลคลิกไฟล์:
  ```text
  run_lab.bat
  ```
- **สำหรับ macOS / Linux:**
  ```bash
  ./run_lab.sh
  ```

ระบบจะสร้าง Virtual Environment, ติดตั้ง Dependencies ที่จำเป็น, และเปิดหน้าเว็บ **PharmaTalk Lab** ที่ `http://localhost:8525` ให้โดยอัตโนมัติ

---

## 2. องค์ประกอบหลักของระบบ (System Architecture)

ระบบประกอบด้วยโมดูลหลัก 4 ส่วน:

```text
[เสียงบทสนทนา] ──▶ Typhoon ASR / Whisper ──▶ Pharmacy Dict ──▶ LLM EMR Extraction ──▶ PDF Export / Cloud Storage
```

1. **PharmaTalk Lab (`lab/`):**
   - ห้องปฏิบัติการทดสอบและประเมินผล (Benchmark & Ablation Lab)
   - แท็บ 1: ถอดเสียงบทสนทนา, สลับโมดูลย่อย (แก้สระลอย, แยกผู้พูด, จัดแชต), และสกัดเวชระเบียน EMR แบบเลือกโมเดลได้ตามต้องการ
   - แท็บ 2: ประเมินผลความถูกต้องเทียบกับคลังเฉลยอ้างอิง 25 เคส (Ground Truth Evaluation) ทั้งแบบเคสเดี่ยวและ Batch
   - พิมพ์รายงานเวชระเบียน PDF ฟอนต์ Kanit มาตรฐานทางการแพทย์

2. **Unified App (`unified_app/`):**
   - ส่วนติดต่อผู้ใช้หลักสำหรับทดสอบระบบเต็มรูปแบบและระบบหลังบ้าน (Back-office)
   - บันทึกเสียงผ่านเบราว์เซอร์, ติดตามสถานะงานถอดเสียง, ดูประวัติย้อนหลังผ่าน Firebase Firestore

3. **Pharmacist Point-of-Care App (`pharmacist_app.py`):**
   - หน้าจอการทำงานจริงสำหรับเภสัชกรหน้าร้านขายยาหรือห้องจ่ายยา
   - เชื่อมต่อหน้าจอยินยอมของผู้รับบริการ (Consent Gate) และแสดงผลสรุปเวชระเบียน

4. **Core API Server (`core_api/`):**
   - บริการหลังบ้านพัฒนาด้วย FastAPI รองรับ Background Task Processing
   - จัดการคิวงานถอดเสียง (STT), คัดกรองคำศัพท์ยา, เรียก LLM สกัด EMR, และบันทึกลง Cloud

---

## 3. โครงสร้างไดเรกทอรี (Directory Structure)

```text
PJ-PharmaTalk/
├── run_lab.sh                  # สคริปต์เปิด Lab ด้วยคลิกเดียว (macOS / Linux)
├── run_lab.bat                 # สคริปต์เปิด Lab ด้วยคลิกเดียว (Windows)
├── pharmacist_app.py           # หน้าจอเภสัชกรหน้าร้าน
├── api.py                      # เซิร์ฟเวอร์บริการหน้า Consent สำหรับผู้ป่วย
├── setup_machine.py            # สคริปต์ตรวจความพร้อมของเครื่อง
│
├── fonts/                      # แบบอักษรภาษาไทยมาตรฐาน
│   ├── Kanit-Regular.ttf
│   ├── Kanit-Medium.ttf
│   ├── Kanit-SemiBold.ttf
│   └── Kanit-Bold.ttf
│
├── lab/                        # ระบบห้องปฏิบัติการทดสอบ ASR และ EMR
│   ├── app.py                  # Streamlit Web App (พอร์ต 8525)
│   ├── pipeline.py             # เอนจินถอดเสียงและไปป์ไลน์การประมวลผล
│   ├── emr_models.py           # เอนจินเรียกโมเดล LLM หลากหลายค่าย
│   ├── requirements.txt        # ไลบรารีสำหรับ Lab
│   └── modules/
│       ├── emr_pdf.py          # ระบบสร้างเอกสารเวชระเบียน PDF (Kanit)
│       ├── emr_groq.py         # โครงสร้าง Prompt และการสกัด EMR
│       ├── pharmacy_dict.py    # พจนานุกรมศัพท์ยาและระบบ Fuzzy Match
│       └── pharmacy_data/      # บัญชียา ขนาดยา และตารางเทียบคำผิด
│
├── unified_app/                # แอปพลิเคชันรวม (Streamlit)
│   ├── app.py                  # หน้าจอหลัก Back-office
│   ├── modules/                # ไคลเอนต์และตัวจัดการสถานะ
│   └── pages/                  # หน้าบันทึกเสียง, ประวัติ, เวชระเบียน EMR
│
├── core_api/                   # เซิร์ฟเวอร์ประมวลผลหลัก (FastAPI)
│   ├── main.py                 # API Endpoints
│   ├── database.py             # จัดการคิวงาน SQLite
│   └── firebase_config.py      # เชื่อมต่อ Firestore & Storage
│
├── ground_truth/               # คลังเฉลยบทสนทนาอ้างอิง 25 เคส
├── tests/                      # ชุดทดสอบระบบอัตโนมัติ (Automated Tests)
│   └── run_tests.py            # รันการทดสอบระบบทั้งหมด
└── docs/                       # เอกสารคู่มือและการวิเคราะห์ทางเทคนิค
```

---

## 4. รายละเอียดโมเดลและการตั้งค่า (Technical Specs)

### โมเดลถอดเสียง (Speech-to-Text)
- **Typhoon ASR Realtime (Conformer-Transducer):** รันออฟไลน์ในเครื่องผ่าน NeMo (`models/typhoon-asr-realtime.nemo`) ความเร็วสูง ~1-2 วินาที
- **Whisper Large v3 (Groq API):** ความแม่นยำสูง เว้นวรรคและจับศัพท์การแพทย์ภาษาไทยได้ครบถ้วน

### โมเดลสกัดเวชระเบียน (EMR LLMs)
- **Groq Cloud:** `openai/gpt-oss-120b`, `meta-llama/llama-3.3-70b-versatile`
- **Google Gemini:** `gemini-2.5-flash`, `gemini-2.5-pro`
- **Anthropic Claude:** `claude-sonnet-4-5`, `claude-3-5-haiku-latest`

### รูปแบบเวชระเบียน 5 หมวด (Clinical EMR Schema)
1. **ประวัติการแพ้ยา:** ชื่อยา อาการไม่พึงประสงค์
2. **โรคประจำตัว:** ภาวะสุขภาพ อาการเรื้อรัง
3. **ประวัติการจ่ายยา / ยาเดิม:** รายการยาที่กำลังใช้อยู่
4. **บันทึกทางการแพทย์ (Clinical SOAP):** สรุปอาการสำคัญ การประเมินปัญหา
5. **คำแนะนำจากเภสัชกร:** แผนการใช้ยา คำเตือน และการปรับพฤติกรรม

---

## 5. การทดสอบความถูกต้องของระบบ (Automated Verification)

สามารถตรวจสอบการทำงานของโมเดล Typhoon ASR, การเชื่อมต่อ Groq API, และการสกัด EMR ได้ผ่านคำสั่ง:

```bash
python3 tests/run_tests.py
```

หากผลลัพธ์แสดง `Transcribing: 100%` พร้อมผลลัพธ์ JSON ของเวชระเบียน แสดงว่าระบบทำงานสมบูรณ์ 100%

---

## 6. ข้อกำหนดด้านความปลอดภัย (Security & Offline Assets)

ไฟล์ที่มีความอ่อนไหวจะไม่ถูกบันทึกลง Git Repository:
- ไฟล์ API Keys: `.groq_api_key`, `.gemini_api_key`
- ไฟล์กุญแจบริการ: `core_api/serviceAccountKey.json`
- ไฟล์ไบนารีโมเดลขนาดใหญ่: `models/typhoon-asr-realtime.nemo`
- ฐานข้อมูลและแคช: `*.db`, `lab/cache/`, `lab/cache_emr/`

หากต้องการใช้งานบนเครื่องใหม่ ให้ใช้ไฟล์ `pharmatalk_offline_assets.zip` ตามขั้นตอนใน Quick Start ด้านบน
