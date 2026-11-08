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

### ขั้นตอนที่ 3: ติดตั้งและเปิดระบบ (macOS)

1. ติดตั้งครั้งแรก (Python 3.11 — **Python 3.13 ใช้กับ NeMo ไม่ได้**): ดับเบิลคลิก `setup_pharmalog.command`
   หรือ `python3.11 -m venv venv && venv/bin/pip install -r requirements.txt`
2. เปิดระบบทั้งหมด: ดับเบิลคลิก `start_pharmalog.command` (อ่านค่าจาก `pharmalog.env`, log อยู่ใน `logs/`)

| เว็บ/บริการ | URL | ใช้ทำอะไร |
|---|---|---|
| Consent (คนไข้) | http://localhost:8500 | คนไข้กดยินยอม/ไม่ยินยอม |
| เภสัชกร | http://127.0.0.1:8501 | อัดได้เมื่อคนไข้ยินยอมแล้วเท่านั้น → ส่งประมวลผล → ตรวจทาน/ยืนยัน EMR |
| หลังบ้าน | http://127.0.0.1:8515 | อัดได้ทันทีไม่ต้องรอยินยอม + ประวัติ + ตั้งค่า |
| Core API | http://127.0.0.1:8080/docs | ถอดเสียง → พจนานุกรมยา → สรุป EMR |
| Lab (ไม่บังคับ) | http://localhost:8525 | `./run_lab.sh` หรือ `run_lab.bat` |

> ถ้าสคริปต์แจ้งว่า "พอร์ตมีโปรแกรมอื่นใช้อยู่" ให้ปิดโปรแกรมเก่านั้นก่อน (เช่นเซิร์ฟเวอร์ Streamlit ที่เปิดค้างจากโปรเจกต์อื่น) ไม่เช่นนั้นเบราว์เซอร์จะเปิดโปรแกรมเก่าแทน

---

## 2. โครงสร้างระบบและแอปพลิเคชัน (Applications & Components)

โปรเจกต์แบ่งออกเป็น 2 ระบบการทำงานหลัก:

### ส่วนที่ 1: ระบบแอปพลิเคชันหลักสำหรับการใช้งานจริง (Production & Clinic Suite)

ระบบหลักสำหรับการปฏิบัติงานของเภสัชกร ประกอบด้วย 4 แอปพลิเคชันย่อยที่เชื่อมต่อกัน:

```text
[คนไข้] ──กดยินยอม──▶ Bridge API + หน้า Consent (api.py:8500)
                          │  สถานะ WAITING → READY → RECORDING → FINISHED (บันทึกใน record/pharmalog.db)
                          ▼
           หน้าเภสัชกร (8501: ต้องมี consent)  /  หน้าหลังบ้าน (8515: ไม่ต้องมี consent)
                          │  อัดเสียง WAV 16 kHz → ฟังทวน → ส่งประมวลผล
                          ▼
                Core API (core_api/main.py:8080)  คิวงานใน core_api/api_queue.db
                          │
       ┌──────────────────┼──────────────────────────────┐
       ▼                  ▼                              ▼
 ถอดเสียง (Typhoon     พจนานุกรมยา 4 ชั้น          Groq LLM: แยกผู้พูด (ตามหมายเลขประโยค)
 Whisper Large v3 หรือ  (เก็บข้อความดิบไว้ด้วย)       + เวชระเบียน 6 หมวด + ข้อควรระวังด้านยา
 Realtime, ตัดช่วง ≤25 วิ)
                          │
                          ▼
     หน้า "วิเคราะห์ EMR": เภสัชกรตรวจทาน แก้ไข และยืนยัน  →  (ถ้าเปิด Cloud) Firebase Firestore
```

1. **Unified Application (`unified_app/app.py` — พอร์ต 8515) — หลังบ้าน:**
   - อัดเสียงได้ทันทีโดยไม่ต้องรอ consent
   - หน้า **อัดเสียง** (อัด → ฟังทวน → ส่งประมวลผล → ลองใหม่ได้ถ้าผิดพลาด), **วิเคราะห์ EMR** (ตรวจทาน/แก้ไข/ยืนยัน, ดูข้อความดิบและคำที่พจนานุกรมแก้), **ประวัติข้อมูล** (ดึงจาก Firestore เมื่อเปิด Cloud), **ตั้งค่า** (สถานะ Core API, โมเดลถอดเสียง, Cloud, Groq)

2. **Pharmacist Portal (`pharmacist_app.py` — พอร์ต 8501) — หน้าร้าน:**
   - ปุ่มอัดเสียงล็อกจนกว่าคนไข้จะกดยินยอม และตัวอัดต้องได้สถานะ `RECORDING` จาก Bridge ก่อนจึงจะเริ่มอัด
   - consent หมดอายุถ้าไม่เริ่มอัดภายใน `PHARMALOG_CONSENT_TTL` วินาที; สถานะ `RECORDING` ที่ค้าง (เช่นปิดเบราว์เซอร์กลางคัน) จะถูกปลดเองหลัง `PHARMALOG_RECORDING_MAX_S` วินาที (30 นาที)
   - มีหน้า อัดเสียง, วิเคราะห์ EMR และ ประวัติข้อมูล

3. **Bridge API + Patient Consent (`api.py` — พอร์ต 8500):**
   - หน้าขอความยินยอมบนแท็บเล็ตหน้าร้าน; กดยินยอมจะสร้าง `consent_id` ใหม่ทุกครั้ง (ใช้ซ้ำไม่ได้), กดไม่ยินยอมจะล้าง consent ทันที
   - เป็นผู้ตัดสินกฎการเปลี่ยนสถานะทั้งหมด (ไม่ใช่เบราว์เซอร์) และเก็บประวัติทุกเหตุการณ์ใน `consent_events`; เมื่อเสร็จงานจะผูก consent กับ `task_id` และชื่อไฟล์เสียง
   - `GET /api/consents` ดูรายการความยินยอม

4. **Core Processing API (`core_api/main.py` — พอร์ต 8080):**
   - `POST /upload-audio` (ตรวจไฟล์ ถ้าไม่ใช่เสียงหรือว่างเปล่าตอบ 400), `GET /task/{id}`, `GET /tasks`, `POST /task/{id}/retry`, `POST /task/{id}/confirm`, `GET /health`
   - เก็บไฟล์เสียงไว้จนกว่างานจะสำเร็จ จึงกดลองใหม่ได้; ถ้าเซิร์ฟเวอร์ปิดกลางงาน งานค้างจะถูกตั้งเป็น ERROR ตอนเปิดใหม่
   - เขียน Firestore เฉพาะเมื่อไม่ได้ตั้ง `PHARMALOG_DISABLE_CLOUD=1`

---

### ส่วนที่ 2: ระบบห้องปฏิบัติการทดสอบและวิจัย (Research & Benchmark Lab)

**PharmaLog AI Lab (`lab/app.py` — พอร์ต 8525):**
ออกแบบขึ้นมาเพื่อการทดลอง ประเมินผลเชิงลึก และการพัฒนาด้านการแพทย์โดยเฉพาะ ประกอบด้วย:

1. **แท็บ 1: การประมวลผลเสียงและสกัดเวชระเบียน (Audio Processing & Multi-Model EMR):**
   - รองรับทั้งโมเดล Typhoon ASR ออฟไลน์ และ Whisper Large v3
   - มีระบบ Ablation Study สำหรับเปิด/ปิดฟังก์ชันย่อย: ระบบแก้คำศัพท์ยา (Pharmacy Dict), ระบบแยกบทบาทผู้พูด, และระบบจัดแชต
   - **ระบบเลือกโมเดล EMR แบบอิสระ:** เลือกประมวลผลพร้อมกันหลายโมเดลได้ เช่น GPT-OSS-120B, Qwen3 และ Gemini 2.5 Flash (บัญชี Groq ปัจจุบันใช้ LLaMA 3.3 70B ไม่ได้แล้ว)
   - ใช้พจนานุกรมยาชุดเดียวกับระบบหลัก (`unified_app/modules/pharmacy_dict.py`)
   - **ระบบออกเอกสารเวชระเบียน PDF:** ออกแบบใหม่ด้วยฟอนต์ Kanit จัดวางหน้าเวชระเบียนอย่างเป็นทางการ และมีปุ่มดาวน์โหลดทันที

2. **แท็บ 2: การประเมินผลเทียบชุดข้อมูลอ้างอิง (Ground Truth Evaluation):**
   - เชื่อมต่อคลังเฉลย 25 เคสทางการแพทย์สำหรับการวัดผลความแม่นยำ
   - รองรับทั้งการประเมินเคสเดี่ยวและการรัน Batch อัตโนมัติ พร้อมคำนวณคะแนนความคล้ายคลึง

---

## 3. ขั้นตอนการทำงานจริงในร้านยา (Clinic Flow)

1. **คนไข้** กด "ยินยอมให้บันทึกเสียง" ที่หน้า Consent → ระบบสร้าง `consent_id` ใหม่ทุกครั้ง (ใช้ซ้ำไม่ได้) และสถานะเป็น `READY`
   - กด "ไม่ยินยอม" → สถานะกลับเป็น `WAITING` และล้าง consent ทันที (หน้าเภสัชกรล็อก)
   - ถ้าเภสัชกรไม่เริ่มอัดภายใน `PHARMALOG_CONSENT_TTL` วินาที (ค่าเริ่มต้น 120) consent หมดอายุ → ล็อกอีกครั้ง
2. **เภสัชกร** กด "เริ่มอัดเสียง" → ตัวอัดขอสถานะ `RECORDING` จาก Bridge ก่อน (ถ้าไม่มี consent ที่ใช้ได้จะไม่อัด) → อัดเป็น WAV 16 kHz
3. กดหยุด → ฟังทวน → "ส่งประมวลผล" → Core API ถอดเสียง (ตัดเป็นช่วง ≤25 วินาทีตรงช่วงเงียบ) → พจนานุกรมยา → LLM สรุป EMR
4. เสร็จแล้วสถานะเป็น `FINISHED` และบันทึก `task_id` + ชื่อไฟล์เสียงลงใน consent record (ตาราง `consent_records`, ประวัติทุกเหตุการณ์ใน `consent_events` ของ `record/pharmalog.db`)
5. หน้า **วิเคราะห์ EMR**: ดูบทสนทนาแยกผู้พูด, ข้อความดิบก่อนแก้, คำที่พจนานุกรมแก้, แก้ไขฟอร์มแล้วกด "ยืนยัน" (เก็บทั้งฉบับ AI และฉบับที่เภสัชกรยืนยัน)
6. กด "บันทึกผู้ป่วยรายใหม่" → สถานะกลับเป็น `WAITING`
7. ถ้าประมวลผลผิดพลาด (เช่น Core API ปิดกลางคัน หรือโควตา LLM หมด) ไฟล์เสียงจะถูกเก็บไว้ กด "ลองประมวลผลใหม่" ได้ (`POST /task/{id}/retry`)

หลังบ้าน (8515) ใช้หน้าเดียวกันแต่ไม่ต้องรอ consent

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
├── tests/                      # stt_compare.py, choose_engine.py, e2e_check.py (+ สคริปต์เก่า)
├── start_pharmalog.command     # เปิดทั้งระบบ (macOS)
├── run_all.command             # ติดตั้งส่วนที่ขาด + เทียบโมเดล + ทดสอบทั้งระบบ
└── docs/                       # เอกสารสถาปัตยกรรมระบบและรายงานผลการทดลอง
```

---

## 5. รายละเอียดโมเดลและการตั้งค่า (Technical Specs)

### โมเดลถอดเสียง (เลือกด้วย `PHARMALOG_STT_ENGINE`)
- **`whisper` (ค่าหลักของโปรเจกต์):** `typhoon-ai/typhoon-whisper-large-v3` ผ่าน transformers (เปลี่ยนรุ่นได้ด้วย `PHARMALOG_WHISPER_MODEL`)
  — ดาวน์โหลดครั้งแรก ~6.2 GB, ต้องการ RAM ว่าง ~7 GB (แนะนำเครื่อง 16 GB+) หรือ GPU NVIDIA
  — **ยังไม่ได้วัดความแม่นยำ** เพราะเครื่องพัฒนามี RAM 8 GB ไม่พอ ดูวิธีให้เครื่องอื่นทดสอบที่ [WHISPER_TEST_GUIDE.md](WHISPER_TEST_GUIDE.md)
  — `start_pharmalog.command` จะเตือนและให้เลือกใช้ Realtime แทนชั่วคราวถ้าเครื่องมี RAM < 16 GB
- **`realtime` (ตัวสำรองที่เบา):** `typhoon-ai/typhoon-asr-realtime` (NeMo FastConformer-Transducer) ในเครื่อง `models/typhoon-asr-realtime.nemo` บน Apple MPS
  — ผลทดสอบ 25 ไฟล์ (88 นาที): CER เฉลี่ย 0.544 ดิบ / 0.538 หลังพจนานุกรม (มัธยฐาน 0.463; ไม่นับ 2 ไฟล์ที่เฉลยไม่ครบ 0.444), เร็ว ~40 เท่าของเวลาจริง (RTF 0.025)
- ทั้งสอง engine ตัดเสียงเป็นช่วง ≤ 25 วินาทีตรงช่วงเงียบ ข้ามช่วงเงียบ และเก็บข้อความดิบคู่กับข้อความที่พจนานุกรมแก้แล้ว

### โมเดลสรุปเวชระเบียน (Groq, `PHARMALOG_EMR_MODELS`)
`openai/gpt-oss-120b` → `qwen/qwen3.8-27b` → `openai/gpt-oss-20b` (สลับอัตโนมัติเมื่อโมเดลแรกติดโควตา/ตอบไม่ใช้ได้)
- บัญชี Groq แบบฟรี: **8,000 โทเคน/นาที และ 200,000 โทเคน/วัน ต่อโมเดล** (≈ 50–80 เคส/วัน/โมเดล) ระบบรอและลองใหม่ให้อัตโนมัติ ถ้าใช้งานจริงปริมาณมากควรอัปเกรดเป็น Dev Tier
- LLM ตอบ "ช่วงผู้พูด" ตามหมายเลขประโยค แล้วระบบสร้างบทสนทนาจากข้อความถอดเสียงจริง — LLM แก้ข้อความบทสนทนาไม่ได้
- บทสนทนายาวมาก (> ~5,000 โทเคน) จะแบ่งเป็นช่วงแล้วรวมผลอัตโนมัติ

### โครงสร้างเวชระเบียน
1. ประวัติการแพ้ยา 2. โรคประจำตัว 3. ประวัติการจ่ายยา (ยาที่ใช้ก่อนมาครั้งนี้) 4. บันทึกทางการแพทย์ 5. คำแนะนำจากเภสัช
6. **ข้อควรระวังด้านความปลอดภัยของยา** (AI แจ้งเตือน ต้องให้เภสัชกรทบทวน) + บทสนทนาที่แยกผู้พูดแล้ว

### ตัวแปรตั้งค่า (`pharmalog.env` หรือ environment)
| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `PHARMALOG_STT_ENGINE` | `whisper` | `whisper` หรือ `realtime` |
| `PHARMALOG_WHISPER_MODEL` | `typhoon-ai/typhoon-whisper-large-v3` | รุ่น Whisper จาก Hugging Face |
| `PHARMALOG_WHISPER_DEVICE` | `cuda` ถ้ามี ไม่งั้น `cpu` | `cpu` / `mps` / `cuda` (MPS เคยไม่เสถียรกับ Whisper) |
| `PHARMALOG_DISABLE_CLOUD` | (ว่าง) | `1` = ไม่เขียน Firestore/Storage — **ต้องตั้งทุกครั้งที่ทดสอบ** |
| `PHARMALOG_CONSENT_TTL` | `120` | วินาทีที่ consent ใช้ได้ก่อนเริ่มอัด |
| `PHARMALOG_RECORDING_MAX_S` | `1800` | ปลดสถานะ RECORDING ที่ค้าง (เช่นปิดเบราว์เซอร์กลางคัน) |
| `PHARMALOG_ROLE_RULES` | `1` (ใน pharmalog.env) | ใช้กฎตรวจผู้พูดเสริม LLM (ทดสอบแล้วแม่นกว่า: 0.82 vs 0.74) |
| `PHARMALOG_EMR_MODELS` | ดูด้านบน | ลำดับโมเดล LLM |
| `PHARMALOG_EMR_DEADLINE_S` | `180` | เวลาสูงสุดในการสรุป EMR ต่อช่วง |
| `PHARMALOG_EMR_TPM` | `8000` | งบโทเคนต่อนาทีของบัญชี Groq |
| `PHARMALOG_PHONETIC_MIN_SIM` | `0.80` | ความคล้ายขั้นต่ำของพจนานุกรมชั้น soundex |
| `PHARMALOG_HOST` | `127.0.0.1` | ที่อยู่ที่ API รับการเชื่อมต่อ |

---

## 6. การทดสอบความถูกต้องของระบบ (Automated Verification)

ปิดระบบที่เปิดค้างก่อน (ต้องว่างพอร์ต 8500/8080) แล้วรัน — ไม่มีการเขียนข้อมูลขึ้น Cloud:

```bash
source venv/bin/activate
python tests/stt_compare.py        # เทียบโมเดลถอดเสียงกับ ground_truth/ → logs/stt_compare.md (รันต่อจากเดิมได้)
python tests/choose_engine.py      # สรุปและแนะนำโมเดล → logs/stt_decision.txt (--apply เพื่อเขียนลง pharmalog.env)
PHARMALOG_DISABLE_CLOUD=1 python tests/e2e_check.py   # ทดสอบทั้งระบบ → logs/e2e_report.md
```
หรือดับเบิลคลิก `run_all.command` เพื่อรันทั้งสามขั้น — ลองเร็วๆ ด้วย `STT_COMPARE_MAX_FILES=3 python tests/stt_compare.py`
หมายเหตุ: `e2e_check.py` ส่งข้อความถอดเสียง ~40 ครั้งไปที่ Groq (ใช้โควตารายวันเกือบครึ่ง) อย่ารันซ้ำหลายรอบในวันเดียว และจะลบเคสทดสอบของตัวเองทิ้งตอนจบ (ตั้ง `E2E_KEEP_TASKS=1` ถ้าต้องการเก็บไว้ดู)

คู่มือ PDF (`PharmaLog_User_Manual.pdf`) สร้างจาก `python docs/make_user_manual.py` — แก้เนื้อหาในสคริปต์แล้วรันใหม่

---

## 7. ข้อกำหนดด้านความปลอดภัย (Security & Offline Assets)

ไฟล์ที่มีความอ่อนไหวจะไม่ถูกบันทึกลง Git Repository:
- ไฟล์ API Keys: `.groq_api_key`, `.gemini_api_key`
- ไฟล์กุญแจบริการ: `core_api/serviceAccountKey.json`
- ไฟล์ไบนารีโมเดลขนาดใหญ่: `models/typhoon-asr-realtime.nemo`
- ฐานข้อมูลและแคช: `*.db`, `lab/cache/`, `lab/cache_emr/`

เมื่อดาวน์โหลดโปรเจกต์บนเครื่องใหม่ ให้ใช้ไฟล์ `pharmalog_offline_assets.zip` แตกไฟล์ลงที่โฟลเดอร์โปรเจกต์โดยตรงตามขั้นตอนใน Quick Start
