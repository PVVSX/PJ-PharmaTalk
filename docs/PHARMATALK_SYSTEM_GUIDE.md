# PharmaTalk System Guide

## ภาพรวม

ระบบ PharmaTalk แบ่งการทำงานเป็น 3 ส่วนหลัก:

```text
Consent Page -> Bridge API -> Recorder
                         -> Core API -> ASR -> EMR
```

- หน้า Consent ขอความยินยอมและส่งสถานะ `READY`
- Bridge API รับสถานะและบันทึก consent ลง SQLite
- หน้า Recorder รับเสียงและบันทึกไฟล์ local
- Core API ประมวลผล ASR และ EMR แบบ background task
- Cloud upload ทำเมื่อผู้ใช้กดปุ่มเท่านั้น

## URL สำหรับใช้งาน

| ส่วนงาน | URL | หน้าที่ |
|---|---|---|
| Consent | `http://127.0.0.1:8502` | แบบฟอร์มยินยอม |
| Recorder | `http://127.0.0.1:8515` | อัดเสียงและดูประวัติ |
| Core API | `http://127.0.0.1:8080` | ประมวลผล task |
| API Docs | `http://127.0.0.1:8080/docs` | Swagger UI |
| API Health | `http://127.0.0.1:8080/health` | ตรวจสถานะ ASR |

## วิธีรันระบบ

เปิด PowerShell แยก 3 หน้าต่าง และใช้คำสั่งจาก root โปรเจกต์

### 1. Bridge API และหน้า Consent

```powershell
Set-Location C:\Users\asus\PJ-PharmaTalk
.venv\Scripts\python.exe api.py
```

เปิด:

```text
http://127.0.0.1:8502
```

### 2. Core API

```powershell
Set-Location C:\Users\asus\PJ-PharmaTalk\core_api
..\.venv\Scripts\python.exe main.py
```

ตรวจสอบ:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

ผลที่ควรได้มีค่า `asr_loaded: true`

### 3. Streamlit Recorder

```powershell
Set-Location C:\Users\asus\PJ-PharmaTalk
.venv\Scripts\python.exe -m streamlit run unified_app\app.py --server.address 127.0.0.1 --server.port 8515
```

เปิด:

```text
http://127.0.0.1:8515
```

## Flow การใช้งาน

1. เปิดหน้า Consent
2. อ่านเอกสารและติ๊กยืนยัน
3. กดยินยอม
4. ระบบส่งสถานะ `READY` ไปยัง Bridge API
5. หน้า Recorder ตรวจสถานะและปลดล็อกการบันทึกเสียง
6. กดเริ่มบันทึกและพูดผ่านไมโครโฟน
7. ไฟล์เสียงถูกเก็บไว้ที่ `record/audio/`
8. Recorder ส่งไฟล์ไป Core API ที่ `/upload-audio`
9. Core API สร้าง `task_id` และประมวลผลเบื้องหลัง
10. Recorder ตรวจสอบสถานะ task
11. เมื่อถอดเสียงเสร็จ transcript ถูกเก็บที่ `record/stt/`
12. หน้า EMR อ่านผล task และแสดงผลลัพธ์เมื่อมีข้อมูลครบ

## API Endpoints

### `GET /`

แสดงข้อมูล service และลิงก์เอกสาร API

### `GET /health`

ตรวจสถานะ Core API และ ASR:

```json
{
  "status": "ok",
  "asr_available": true,
  "asr_loaded": true
}
```

### `POST /upload-audio`

รับไฟล์เสียงแบบ multipart และคืนค่า `task_id`:

```json
{
  "message": "Audio received and queued",
  "task_id": "..."
}
```

### `GET /task/{task_id}`

อ่านสถานะ task เช่น:

- `UPLOADED`
- `STT_PROCESSING`
- `STT_DONE`
- `EMR_PROCESSING`
- `COMPLETED`
- `ERROR`

## การจัดเก็บข้อมูล

### Consent SQLite

ไฟล์ฐานข้อมูล:

```text
record/pharmatalk.db
```

ตาราง:

```text
consent_records
```

ข้อมูลหลัก:

- `consent_id`
- `consent_version`
- `consented_at`
- `recorded_at`

### Core API Task SQLite

ไฟล์ฐานข้อมูล:

```text
core_api/api_queue.db
```

ตาราง:

```text
tasks
```

ใช้ติดตาม task เสียง, transcript, EMR และ error

### ไฟล์เสียงและ transcript

```text
record/audio/*.wav
record/stt/*_stt.txt
record/emr/*.json
```

## การอัปโหลด Cloud

ระบบจะไม่อัปโหลดเสียงขึ้น Cloud อัตโนมัติ

ผู้ใช้ต้องกดปุ่ม `อัปโหลดขึ้น Cloud` ในหน้า Recorder เองเท่านั้น

ต้องตั้งค่า Firebase ก่อนใช้งาน:

```text
FIREBASE_CREDENTIALS=path/to/serviceAccountKey.json
FIREBASE_STORAGE_BUCKET=your-project.appspot.com
```

หากไม่มี credential ไฟล์เสียงจะยังอยู่ในเครื่อง และระบบจะแจ้งเตือนเมื่อกดปุ่มอัปโหลด

## Gemini EMR

ระบบ Core API ใช้ Gemini สำหรับวิเคราะห์ EMR ต้องสร้างไฟล์ที่ root โปรเจกต์:

```text
.gemini_api_key
```

ภายในไฟล์ใส่ API key เพียงบรรทัดเดียว และห้าม commit ไฟล์นี้ขึ้น Git

```text
YOUR_GEMINI_API_KEY
```

## ตรวจสอบปัญหาเบื้องต้น

### เปิด `http://127.0.0.1:8080/` แล้วได้ 404

ให้ตรวจว่า Core API เป็นเวอร์ชันล่าสุดและ restart service แล้ว จากนั้นควรเห็น JSON ข้อมูล service

### หน้า Recorder ไม่ปลดล็อก

ตรวจตามลำดับ:

1. หน้า Consent แสดงผลสำเร็จหรือไม่
2. ตรวจ `http://127.0.0.1:8502/api/state`
3. ตรวจว่าได้สถานะ `READY`
4. ตรวจหน้า Core API `/health`
5. ดู log ของ Streamlit และ Core API

### ASR ไม่พร้อม

ตรวจ:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

ต้องมี:

```text
asr_available = true
asr_loaded = true
```

### EMR ไม่ทำงาน

ตรวจว่ามีไฟล์ `.gemini_api_key` และ API key ใช้งานได้

## ข้อควรระวัง

- อย่าเปิด static server แยกที่พอร์ต `8520` เพราะไม่มี API เชื่อมต่อกับ Recorder
- ใช้ `api.py` ที่พอร์ต `8502` สำหรับหน้า Consent
- อย่าลบ `record/pharmatalk.db` หากต้องการเก็บประวัติ consent
- ไฟล์ฐานข้อมูลและไฟล์เสียงเป็นข้อมูล runtime ไม่ควร commit โดยไม่จำเป็น
- Cloud upload ต้องเกิดจากการกดปุ่มของผู้ใช้เท่านั้น
- การรัน Core API ครั้งแรกอาจใช้เวลาหลายวินาทีเพราะต้องโหลดโมเดล ASR
