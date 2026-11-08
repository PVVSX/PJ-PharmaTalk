# PharmaLog AI System Guide: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์

> ปรับปรุงล่าสุด 2026-11-07 ให้ตรงกับระบบหลังการแก้ไข (consent ใหม่, STT 2 engine, EMR แบบแยกผู้พูดตามหมายเลขประโยค, หน้าตรวจทาน/ยืนยัน EMR)

## ภาพรวม

```text
คนไข้ ──▶ หน้า Consent + Bridge API (8500) ──สถานะ──▶ หน้าเภสัชกร (8501) / หน้าหลังบ้าน (8515)
                                                          │ อัดเสียง WAV 16 kHz → ฟังทวน → ส่ง
                                                          ▼
                                             Core API (8080) — คิวงานเบื้องหลัง
                                       ถอดเสียง → พจนานุกรมยา → Groq LLM สรุป EMR
                                                          │
                                                          ▼
                                 หน้า "วิเคราะห์ EMR": ตรวจทาน แก้ไข ยืนยัน  → (ถ้าเปิด Cloud) Firestore
```

| ส่วนงาน | URL | หน้าที่ |
|---|---|---|
| Consent (คนไข้) | `http://localhost:8500` | หน้าขอความยินยอม + Bridge API (`/api/state`, `/api/consents`) |
| เภสัชกร | `http://127.0.0.1:8501` | อัดได้เมื่อคนไข้ยินยอม, วิเคราะห์ EMR, ประวัติ |
| หลังบ้าน | `http://127.0.0.1:8515` | อัดได้ทันที, วิเคราะห์ EMR, ประวัติ, ตั้งค่า |
| Core API | `http://127.0.0.1:8080/docs` | Swagger UI |
| Health | `http://127.0.0.1:8080/health` | สถานะโมเดลถอดเสียง (`asr_loaded`, `stt_engine`, `stt_device`, `cloud_enabled`) |

## วิธีรันระบบ

**macOS:** ดับเบิลคลิก `start_pharmalog.command` (เปิดทุกส่วน อ่านค่าจาก `pharmalog.env` และเขียน log ไว้ที่ `logs/`)
สคริปต์จะหยุดถ้ามีโปรแกรมอื่นใช้พอร์ต 8500/8080/8501/8515 อยู่ และเตือนถ้า RAM ไม่พอสำหรับ Whisper Large v3

**รันแยกเอง (ทุกระบบปฏิบัติการ)** — เปิดจากโฟลเดอร์ root ของโปรเจกต์ หลัง activate venv:
```bash
python api.py                                   # 1) Bridge + Consent (8500)
cd core_api && python main.py                   # 2) Core API (8080) — รอจน /health ได้ asr_loaded: true
streamlit run pharmacist_app.py --server.address 127.0.0.1 --server.port 8501   # 3) เภสัชกร
streamlit run unified_app/app.py --server.address 127.0.0.1 --server.port 8515  # 4) หลังบ้าน
```
ระหว่างทดสอบให้ตั้ง `PHARMALOG_DISABLE_CLOUD=1` ทุกครั้ง (ไม่เขียน Firestore/Storage)

## Flow การใช้งาน

1. คนไข้กด **ยินยอมให้บันทึกเสียง** → หน้า Consent สร้าง `consent_id` ใหม่ (UUID) ส่ง `READY` ไป Bridge
   - กด **ไม่ยินยอม** → `WAITING` และล้าง consent; หน้าเภสัชกรล็อก
2. หน้าเภสัชกรปลดล็อก แสดงเวลาที่เหลือ (consent หมดอายุใน `PHARMALOG_CONSENT_TTL` วินาที ถ้ายังไม่เริ่มอัด)
3. กด **เริ่มอัดเสียง** → ตัวอัดขอ `RECORDING` จาก Bridge ก่อน ถ้าถูกปฏิเสธจะไม่อัด
4. กด **หยุด** → ฟังทวน → **ส่งประมวลผล** หรือ **อัดใหม่** (ไฟล์เก็บที่ `record/audio/`)
5. Core API: ตรวจไฟล์ → ถอดเสียง (ตัดช่วง ≤ 25 วิ ตรงช่วงเงียบ ข้ามช่วงเงียบ) → พจนานุกรมยา → LLM
6. เสร็จแล้ว Bridge เป็น `FINISHED` และผูก consent กับ `task_id` + ชื่อไฟล์เสียง
7. หน้า **วิเคราะห์ EMR**: แก้ไขฟอร์ม → **ยืนยันและบันทึกเวชระเบียน** (เก็บทั้งฉบับ AI และฉบับยืนยัน)
8. **บันทึกผู้ป่วยรายใหม่** → `WAITING`

กรณีผิดพลาด: งานที่ล้มเหลวกด **ลองประมวลผลใหม่** ได้ (ไฟล์เสียงเก็บไว้จนงานสำเร็จ); ถ้า Core API ปิดกลางงาน
งานนั้นจะถูกตั้งเป็น `ERROR` ตอนเปิดใหม่; ถ้าเบราว์เซอร์เภสัชกรปิดกลางการอัด สถานะ `RECORDING` จะถูกปลดเองหลัง
`PHARMALOG_RECORDING_MAX_S` วินาที (ค่าเริ่มต้น 30 นาที) และ consent นั้นถูกบันทึกเป็น `abandoned`

## สถานะของ Bridge (`record/shared_state.json`)

| สถานะ | เข้าได้จาก | หมายเหตุ |
|---|---|---|
| `WAITING` | ทุกสถานะ | ล้าง consent เสมอ (reason: `declined`, `new_patient`, `expired`) |
| `READY` | ต้องมี `consent_id` ใหม่ที่ไม่เคยใช้ | ใช้ซ้ำได้ 409, ขณะมีคนอัดอยู่ 409, หมดอายุตาม TTL |
| `RECORDING` | จาก `READY` ที่ยังไม่หมดอายุเท่านั้น | ไม่มี consent → 409 |
| `FINISHED` | หลังงานประมวลผลเสร็จ | ผูก `task_id` และ `audio_filename` |

## Core API Endpoints

| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/health` | สถานะโมเดลและ Cloud |
| POST | `/upload-audio` | multipart `file` (+ `consent_id`, `source`) → `task_id`; ไฟล์ว่าง/ไม่ใช่เสียง → 400 |
| GET | `/task/{id}` | สถานะ + `stt_text`, `raw_stt_text`, `stt_meta`, `emr_json`, `confirmed_emr_json`, `can_retry` |
| GET | `/tasks?limit=20` | งานล่าสุด (ซ่อนงานทดสอบอัตโนมัติ เว้นแต่ `include_test=1`) |
| POST | `/task/{id}/retry` | ลองใหม่เฉพาะงาน `ERROR` |
| POST | `/task/{id}/confirm` | บันทึก EMR ที่เภสัชกรยืนยัน (body `{"emr": {...}}`) |

สถานะงาน: `UPLOADED` → `STT_PROCESSING` → `STT_DONE` → `EMR_PROCESSING` (→ `RETRYING_EMR_IN_10S`) → `COMPLETED` / `ERROR`

## การจัดเก็บข้อมูล

| ที่เก็บ | เนื้อหา |
|---|---|
| `record/pharmalog.db` | `consent_records` (consent_id, version, consented_at, recorded_at, status, task_id, audio_filename) และ `consent_events` (ประวัติทุกการเปลี่ยนสถานะ) |
| `core_api/api_queue.db` | ตาราง `tasks` (สร้าง/เพิ่มคอลัมน์ใหม่อัตโนมัติ) |
| `core_api/temp_audio/` | ไฟล์เสียงของงานที่ยังไม่สำเร็จ (ลบเมื่อสำเร็จ) |
| `record/audio/`, `record/stt/` | ไฟล์เสียงที่อัดในเครื่องและข้อความถอดเสียง |
| Firestore `patients_emr/{task_id}` | เมื่อเปิด Cloud เท่านั้น |

## Cloud

- Core API เขียนผล EMR ลง Firestore อัตโนมัติ **เมื่อไม่ได้ตั้ง** `PHARMALOG_DISABLE_CLOUD=1`
- ไฟล์เสียงขึ้น Storage เฉพาะเมื่อผู้ใช้กดปุ่ม **อัปโหลด Cloud** เท่านั้น
- ต้องมี `core_api/serviceAccountKey.json` (หรือ `FIREBASE_CREDENTIALS=path`) และตั้ง `FIREBASE_STORAGE_BUCKET` ถ้าไม่ใช่ค่าเดิม

## โมเดล

- ถอดเสียง: `PHARMALOG_STT_ENGINE=whisper` (Typhoon Whisper Large v3, ค่าหลัก — ต้องการ RAM ~7 GB หรือ GPU) หรือ `realtime` (Typhoon ASR Realtime, เบา)
  ผลวัดและวิธีทดสอบดู `README.md` ส่วนที่ 5 และ `WHISPER_TEST_GUIDE.md`
- สรุป EMR: Groq — ต้องมีไฟล์ `.groq_api_key` ที่ root (หรือ `GROQ_API_KEY`) ลำดับโมเดล `PHARMALOG_EMR_MODELS`
  (`openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b`) บัญชีฟรีจำกัด 8,000 โทเคน/นาที และ 200,000 โทเคน/วัน ต่อโมเดล

## ตรวจสอบปัญหาเบื้องต้น

| อาการ | ตรวจ |
|---|---|
| เปิด 8501 แล้วเจอหน้าเก่า/ชื่อโปรแกรมอื่น | มีโปรแกรมเก่าใช้พอร์ตอยู่: `lsof -nP -iTCP:8501 -sTCP:LISTEN` แล้วปิดโปรแกรมนั้น |
| หน้าเภสัชกรไม่ปลดล็อก | `curl http://127.0.0.1:8500/api/state` ต้องเป็น `READY`; ถ้าเป็น `RECORDING` ค้างให้กด "บันทึกผู้ป่วยรายใหม่" |
| "ระบบถอดเสียงยังไม่พร้อม" | `curl http://127.0.0.1:8080/health` ดู `stt_error`; Whisper ครั้งแรกต้องดาวน์โหลด ~6.2 GB |
| EMR ล้มเหลว "เรียก LLM ไม่สำเร็จทุกโมเดล" | โควตา Groq รายวันหมด/ไม่มี `.groq_api_key` — รอแล้วกด "ลองประมวลผลใหม่" |
| อัดเสียงยาวแล้วไฟล์ไม่ขึ้น | ต้องมี `.streamlit/config.toml` ที่ตั้ง `maxWidgetStateSize = 120` และรัน streamlit จาก root ของโปรเจกต์ |
| ดู log | `logs/api.log`, `logs/core_api.log`, `logs/pharmacist_app.log`, `logs/unified_app.log` |

## ข้อควรระวัง

- ห้ามขึ้น Cloud ระหว่างทดสอบ และห้าม commit `*.wav`, `*.db`, API keys
- ไฟล์ในโฟลเดอร์ `ไฟล์เสียงทั้งหมด/` และ `ground_truth/` เป็นข้อมูลจริงของผู้รับบริการ
- อย่าลบ `record/pharmalog.db` ถ้าต้องการเก็บหลักฐานการยินยอม
