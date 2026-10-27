# PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์

PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ คือระบบปัญญาประดิษฐ์ครบวงจรสำหรับการบันทึกและสกัดข้อมูลเวชระเบียนการบริบาลทางเภสัชกรรม (Electronic Medical Record: EMR) จากบทสนทนาระหว่างเภสัชกรและผู้ป่วยแบบอัตโนมัติ ออกแบบมาเพื่อรองรับทั้ง **การใช้งานจริงในร้านยา/คลินิก (Production & Clinic Application Suite)** และ **การวิจัยทดสอบประสิทธิภาพโมเดล (Research & Benchmark Lab)**

---

## 1. วิธีเริ่มต้นใช้งานด่วนบนเครื่องใหม่ (Quick Start)

ระบบได้รับการออกแบบให้ติดตั้งและเปิดใช้งานได้ทันทีใน 3 ขั้นตอน โดยไม่ต้องตั้งค่าหรือกรอก API Key เอง:

### ขั้นตอนที่ 1: โคลนโค้ดจาก Git
```bash
git clone https://github.com/PVVSX/PharmaLog.git
cd PharmaLog
```

### ขั้นตอนที่ 2: แตกไฟล์ ZIP Assets ลงในโฟลเดอร์โปรเจกต์
นำไฟล์ `pharmalog_offline_assets.zip` มาวางไว้ที่โฟลเดอร์รากของโปรเจกต์ แล้วแตกไฟล์:
- **macOS / Linux:**
  ```bash
  unzip -o pharmalog_offline_assets.zip
  ```
- **Windows:**
  คลิกขวาที่ไฟล์ `pharmalog_offline_assets.zip` แล้วเลือก **Extract Here** (แตกไฟล์ลงในโฟลเดอร์ปัจจุบัน)

*(ไฟล์ API Key, โมเดล Typhoon ASR, และฐานข้อมูล SQLite จะถูกจัดวางลงตำแหน่งที่ถูกต้องทันที)*

### ขั้นตอนที่ 3: เริ่มต้นรันระบบ

สามารถเลือกรันระบบที่ต้องการใช้งานได้ดังนี้:

#### ก. เปิดแอปพลิเคชันหลัก (PharmaLog AI Main Application — พอร์ต 8080 & 8515)
1. รันเซิร์ฟเวอร์ประมวลผลเบื้องหลัง (Core API — พอร์ต 8080):
   ```bash
   python core_api/main.py
   ```
2. เปิดหน้าเว็บแอปพลิเคชันหลัก (Unified App — พอร์ต 8515):
   ```bash
   streamlit run unified_app/app.py --server.port 8515
   ```
- *เปิดใช้งานผ่านเบราว์เซอร์ที่: `http://localhost:8515`*

#### ข. เปิดระบบห้องแล็บทดสอบ (PharmaLog AI Lab — พอร์ต 8525)
- **Windows:** ดับเบิลคลิก `run_lab.bat`
- **macOS / Linux:** รันคำสั่ง `./run_lab.sh`
- *เปิดใช้งานผ่านเบราว์เซอร์ที่: `http://localhost:8525`*

---

## 2. โครงสร้างระบบและแอปพลิเคชัน (Applications & Components)

โปรเจกต์แบ่งออกเป็น 2 ระบบการทำงานหลัก:

### ส่วนที่ 1: ระบบแอปพลิเคชันหลักสำหรับการใช้งานจริง (Production & Clinic Suite)

ระบบหลักสำหรับการปฏิบัติงานของเภสัชกร ประกอบด้วย 4 แอปพลิเคชันย่อยที่เชื่อมต่อกัน:

```text
[ผู้รับบริการ] ──▶ Consent Page (api.py:8500) ──READY──▶ Pharmacist App (8501) หรือ Unified App (8515)
                                                                 │
                                                          อัปโหลดไฟล์เสียง
                                                                 ▼
                                                    Core API (core_api:8080)
                                                                 │
                                                ┌────────────────┴────────────────┐
                                                ▼                                 ▼
                                      Typhoon ASR Engine                 Groq LLM Extraction
                                     (+ พจนานุกรมศัพท์ยา)                  (เวชระเบียน 5 หมวด)
                                                │                                 │
                                                └────────────────┬────────────────┘
                                                                 ▼
                                                  Firebase Firestore & Storage
```

1. **Unified Application (`unified_app/app.py` — พอร์ต 8515):**
   - **แอปพลิเคชันหลักสำหรับผู้ดูแลระบบและหลังบ้าน (Back-Office & Standalone Portal)**
   - ใช้งานได้ทันทีโดยไม่ต้องผ่าน Consent Gate
   - ประกอบด้วย 4 หน้าการทำงานครบวงจร:
     - **หน้าบันทึกเสียง (Recorder):** บันทึกเสียงบทสนทนาสดผ่านไมโครโฟน, อัพโหลดไฟล์เสียง WAV, ตรวจสอบความพร้อมของระบบ และส่งเข้าคิวประมวลผล
     - **หน้าประวัติข้อมูล (History):** ดูรายการเวชระเบียนย้อนหลังที่ดึงจาก Cloud Firestore, ค้นหาตามชื่อ/วันที่, เล่นไฟล์เสียงที่บันทึกไว้ใน Firebase Storage และดาวน์โหลดเอกสารสรุป
     - **หน้าวิเคราะห์เวชระเบียน (EMR Analysis):** แสดงผลการถอดเสียงบทสนทนา (Transcript) แยกบทบาทเภสัชกร-คนไข้ พร้อมแสดงฟอร์มเวชระเบียนทางการแพทย์ SOAP
     - **หน้าตั้งค่าระบบ (Settings):** ตรวจสอบสถานะการเชื่อมต่อ Core API, ความพร้อมของโมเดล Typhoon ASR, บัญชี Firebase, และสถานะของ Groq API Key

2. **Pharmacist Point-of-Care Portal (`pharmacist_app.py` — พอร์ต 8501):**
   - **หน้าจอสำหรับเภสัชกรผู้ปฏิบัติงานหน้าร้านยาหรือห้องจ่ายยา**
   - เชื่อมต่อกับระบบขอความยินยอม (Patient Consent Gate) อย่างเข้มงวด โดยปุ่มบันทึกเสียงจะถูกล็อกไว้จนกว่าผู้ป่วยจะกดยินยอมผ่านหน้าจอ Consent
   - เน้นความสะดวกในการทำงาน รวดเร็ว และแสดงผลเฉพาะหน้าบันทึกเสียงและประวัติข้อมูล

3. **Patient Consent Gateway (`api.py` — พอร์ต 8500):**
   - **เว็บแอปพลิเคชันขอความยินยอมจากผู้รับบริการ (PDPA / Consent Form)**
   - แสดงข้อกำหนดการบันทึกเสียงเพื่อการบริบาลทางเภสัชกรรมบนแท็บเล็ตหน้าร้าน
   - เมื่อผู้รับบริการกด "ยินยอม" ระบบจะบันทึกข้อมูลลงฐานข้อมูลและส่งสัญญาณสถานะ `READY` ไปยังหน้าจอเภสัชกรเพื่อปลดล็อกการบันทึกเสียงทันที

4. **Core Processing API (`core_api/main.py` — พอร์ต 8080):**
   - **เซิร์ฟเวอร์ประมวลผลเบื้องหลัง (FastAPI Engine & Background Task Queue)**
   - ทำงานแบบ Asynchronous รองรับงานหนักโดยไม่ทำให้หน้าเว็บค้าง
   - จัดการคิวงานถอดเสียงด้วย Typhoon ASR, กรองคำศัพท์เฉพาะทางด้วย Pharmacy Dictionary, วิเคราะห์สกัด EMR ด้วย Groq LLM, และอัพโหลดข้อมูลขึ้น Firebase Firestore และ Storage อัตโนมัติ

---

### ส่วนที่ 2: ระบบห้องปฏิบัติการทดสอบและวิจัย (Research & Benchmark Lab)

**PharmaLog AI Lab (`lab/app.py` — พอร์ต 8525):**
ออกแบบขึ้นมาเพื่อการทดลอง ประเมินผลเชิงลึก และการพัฒนาด้านการแพทย์โดยเฉพาะ ประกอบด้วย:

1. **แท็บ 1: การประมวลผลเสียงและสกัดเวชระเบียน (Audio Processing & Multi-Model EMR):**
   - รองรับทั้งโมเดล Typhoon ASR ออฟไลน์ และ Whisper Large v3
   - มีระบบ Ablation Study สำหรับเปิด/ปิดฟังก์ชันย่อย: ระบบแก้คำศัพท์ยา (Pharmacy Dict), ระบบแยกบทบาทผู้พูด, และระบบจัดแชต
   - **ระบบเลือกโมเดล EMR แบบอิสระ:** สามารถเลือกประมวลผลพร้อมกันหลายโมเดลได้ตามต้องการ เช่น GPT-OSS-120B, LLaMA 3.3 70B, และ Gemini 2.5 Flash
   - **ระบบออกเอกสารเวชระเบียน PDF:** ออกแบบใหม่ด้วยฟอนต์ Kanit จัดวางหน้าเวชระเบียนอย่างเป็นทางการ และมีปุ่มดาวน์โหลดทันที

2. **แท็บ 2: การประเมินผลเทียบชุดข้อมูลอ้างอิง (Ground Truth Evaluation):**
   - เชื่อมต่อคลังเฉลย 25 เคสทางการแพทย์สำหรับการวัดผลความแม่นยำ
   - รองรับทั้งการประเมินเคสเดี่ยวและการรัน Batch อัตโนมัติ พร้อมคำนวณคะแนนความคล้ายคลึง

---

## 3. วิธีการรันระบบหลักแบบเต็มรูปแบบ (Full Clinic Production Flow)

หากต้องการรันระบบจำลองการทำงานจริงในร้านยา ให้เปิด 3 หน้าต่าง Terminal:

### หน้าต่างที่ 1: เปิดหน้า Consent สำหรับผู้ป่วย (พอร์ต 8500)
```bash
python3 api.py
```
*เปิดใช้งานสำหรับผู้ป่วยที่: `http://localhost:8500`*

### หน้าต่างที่ 2: เปิด Core API ประมวลผลเบื้องหลัง (พอร์ต 8080)
```bash
cd core_api
python3 main.py
```
*ตรวจสอบความพร้อมของระบบได้ที่: `http://localhost:8080/health` (ต้องได้ `asr_available: true`)*

### หน้าต่างที่ 3: เปิดหน้าจอเภสัชกรหน้าร้าน (พอร์ต 8501)
```bash
streamlit run pharmacist_app.py --server.port 8501
```
*เปิดใช้งานสำหรับเภสัชกรที่: `http://localhost:8501`*

---

## 4. โครงสร้างไฟล์ในโปรเจกต์ (Project Directory Layout)

```text
PharmaLog/
├── run_lab.sh                  # สคริปต์คลิกเดียวเปิด Lab (macOS / Linux)
├── run_lab.bat                 # สคริปต์คลิกเดียวเปิด Lab (Windows)
│
├── pharmacist_app.py           # หน้าจอเภสัชกรหน้าร้าน (พอร์ต 8501)
├── api.py                      # เซิร์ฟเวอร์หน้า Consent ผู้ป่วย (พอร์ต 8500)
├── setup_machine.py            # สคริปต์ตรวจความพร้อมของเครื่อง
│
├── unified_app/                # แอปหลัก Back-office & Standalone (พอร์ต 8515)
│   ├── app.py                  # Entry Point ของ Unified App
│   ├── assets/style.css        # ดีไซน์และธีมของระบบ
│   ├── components/             # ตัวบันทึกเสียง Custom Browser Component
│   ├── modules/                # ไคลเอนต์ Task API, State Manager, พจนานุกรมยา
│   └── pages/                  # หน้าบันทึกเสียง, ประวัติ, เวชระเบียน EMR, ตั้งค่า
│
├── core_api/                   # FastAPI Backend Server (พอร์ต 8080)
│   ├── main.py                 # API Endpoints (Upload, Task, Health)
│   ├── database.py             # จัดการคิวงาน SQLite
│   ├── firebase_config.py      # เชื่อมต่อ Firestore & Storage
│   └── requirements.txt        # ไลบรารีสำหรับ Core API
│
├── lab/                        # ระบบห้องปฏิบัติการทดสอบ (พอร์ต 8525)
│   ├── app.py                  # Streamlit Web App ของ Lab
│   ├── pipeline.py             # เอนจินถอดเสียงและ Ablation
│   ├── emr_models.py           # เอนจินสกัด EMR หลายโมเดล
│   ├── requirements.txt        # ไลบรารีสำหรับ Lab
│   └── modules/                # โมดูล PDF (Kanit), Prompt EMR, ฐานข้อมูลยา
│
├── fonts/                      # แบบอักษรภาษาไทย Kanit สำหรับเอกสาร PDF
├── ground_truth/               # ชุดข้อมูลเฉลยบทสนทนาอ้างอิง 25 เคส
├── tests/                      # สคริปต์ทดสอบระบบอัตโนมัติ (tests/run_tests.py)
└── docs/                       # เอกสารสถาปัตยกรรมระบบและรายงานผลการทดลอง
```

---

## 5. รายละเอียดโมเดลและการตั้งค่า (Technical Specs)

### โมเดลถอดเสียง (Speech-to-Text Engines)
- **Typhoon ASR Realtime (Conformer-Transducer):** โมเดลออฟไลน์ในเครื่องผ่าน NeMo (`models/typhoon-asr-realtime.nemo`) ประมวลผลรวดเร็ว ~1-2 วินาที
- **Whisper Large v3 (Groq API):** ความแม่นยำสูง เว้นวรรคและจับศัพท์การแพทย์ภาษาไทยได้ครบถ้วน

### โมเดลสกัดเวชระเบียน (EMR LLMs)
- **Groq Cloud:** `openai/gpt-oss-120b`, `meta-llama/llama-3.3-70b-versatile`
- **Google Gemini:** `gemini-2.5-flash`, `gemini-2.5-pro`
- **Anthropic Claude:** `claude-sonnet-4-5`, `claude-3-5-haiku-latest`

### โครงสร้างเวชระเบียน 5 หมวด (Clinical EMR Schema)
1. **ประวัติการแพ้ยา:** ชื่อยา อาการแพ้ ระดับความรุนแรง
2. **โรคประจำตัว:** ภาวะสุขภาพ อาการเรื้อรัง
3. **ประวัติการจ่ายยา / ยาเดิม:** รายการยาที่ผู้ป่วยกำลังรับประทาน
4. **บันทึกทางการแพทย์ (Clinical SOAP):** สรุปอาการสำคัญ ผลการประเมิน
5. **คำแนะนำจากเภสัชกร:** แผนการใช้ยา คำเตือน และการดูแลตนเอง

---

## 6. การทดสอบความถูกต้องของระบบ (Automated Verification)

สามารถตรวจสอบการทำงานของโมเดล Typhoon ASR, การเชื่อมต่อ Groq API, และการสกัด EMR ได้ผ่านคำสั่งเดียว:

```bash
python3 tests/run_tests.py
```

หากผลลัพธ์แสดง `Transcribing: 100%` พร้อมผลลัพธ์ JSON ของเวชระเบียน แสดงว่าระบบทำงานสมบูรณ์ 100%

---

## 7. ข้อกำหนดด้านความปลอดภัย (Security & Offline Assets)

ไฟล์ที่มีความอ่อนไหวจะไม่ถูกบันทึกลง Git Repository:
- ไฟล์ API Keys: `.groq_api_key`, `.gemini_api_key`
- ไฟล์กุญแจบริการ: `core_api/serviceAccountKey.json`
- ไฟล์ไบนารีโมเดลขนาดใหญ่: `models/typhoon-asr-realtime.nemo`
- ฐานข้อมูลและแคช: `*.db`, `lab/cache/`, `lab/cache_emr/`

เมื่อดาวน์โหลดโปรเจกต์บนเครื่องใหม่ ให้ใช้ไฟล์ `pharmalog_offline_assets.zip` แตกไฟล์ลงที่โฟลเดอร์โปรเจกต์โดยตรงตามขั้นตอนใน Quick Start
