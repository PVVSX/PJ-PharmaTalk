# PharmaLog AI: Unified App (Architecture Guide)

`unified_app/` คือส่วนหน้าจอ (Streamlit) ของ PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ ใช้อัดเสียงบทสนทนาระหว่างเภสัชกรกับคนไข้ ส่งไปถอดเสียงและสรุปเป็นเวชระเบียน (EMR) แล้วแสดงผลและประวัติ เอกสารนี้อธิบายโครงสร้างโค้ดและการแบ่งความรับผิดชอบ เพื่อให้ทีมแก้โค้ดได้โดยไม่กระทบส่วนอื่น

ขั้นตอนการรันระบบทั้งหมดดูได้ที่ [`docs/PHARMALOG_SYSTEM_GUIDE.md`](../docs/PHARMALOG_SYSTEM_GUIDE.md)

## ภาพรวมการทำงาน

```text
Consent page (api.py) ──READY──▶ Recorder (Streamlit)
                                      │  อัปโหลดไฟล์เสียง
                                      ▼
                              Core API (core_api/main.py)
                                      │  background task
                                      ├─▶ Typhoon ASR (+ พจนานุกรมแก้ชื่อยา)
                                      ├─▶ Groq LLM สกัด EMR 6 ช่อง
                                      └─▶ Firestore + Firebase Storage
```

แอปนี้ไม่ได้รันโมเดลเอง งานถอดเสียงและสกัด EMR ทำใน Core API ส่วนหน้าจอแค่ส่งไฟล์และรอผลผ่าน `modules/task_api.py`

## จุดเริ่มต้น (Entry points)

| ไฟล์ | ใช้สำหรับ | หน้าที่มี | ต้องผ่าน Consent |
| --- | --- | --- | --- |
| `unified_app/app.py` | Back-office / ทดสอบ | อัดเสียง, ประวัติข้อมูล, วิเคราะห์ EMR, ตั้งค่า | ไม่ต้อง (`is_backoffice = True`) |
| `pharmacist_app.py` (root) | หน้าจอเภสัชกรหน้าร้าน | อัดเสียง, ประวัติข้อมูล | ต้อง (อ่านสถานะจาก `record/shared_state.json`) |

ทั้งสองไฟล์ใช้หน้าใน `pages/` ชุดเดียวกัน

## โครงสร้างโฟลเดอร์

```text
unified_app/
├── app.py                  # Entry point + sidebar navigation (back-office)
├── .streamlit/config.toml  # ค่าตั้งต้นของ Streamlit
├── assets/
│   └── style.css           # สไตล์ทั้งหมดของแอป
├── components/
│   ├── auto_recorder.py    # Custom component อัดเสียงในเบราว์เซอร์ คืนค่า WAV
│   └── frontend/           # HTML/JS ของ component
├── modules/
│   ├── config.py           # path กลาง (ROOT, RECORD_DIR)
│   ├── task_api.py         # client เรียก Core API (/upload-audio, /task, /health)
│   ├── state_manager.py    # อ่าน/เขียนสถานะ consent ใน shared_state.json
│   ├── stt_typhoon.py      # โหลดและเรียก Typhoon ASR ผ่าน NeMo (ใช้ใน Core API)
│   ├── pharmacy_dict.py    # พจนานุกรมแก้ชื่อยา/ศัพท์การแพทย์ที่ถอดเสียงผิด
│   └── emr_groq.py         # prompt + เรียก Groq สกัด EMR เป็น JSON
└── pages/
    ├── recorder.py         # อัดเสียง ส่งเข้า Core API และรายการไฟล์ที่บันทึก
    ├── history.py          # ประวัติเคสจาก Firestore
    ├── emr.py              # แสดง transcript และฟอร์ม EMR (อ่านอย่างเดียว)
    └── settings.py         # สถานะระบบ: Core API, ASR, Groq key
```

ข้อมูลที่ระบบเขียนลงเครื่อง (อยู่นอก `unified_app/`; `record/audio/`, `record/stt/` และ `core_api/temp_audio/` อยู่ใน `.gitignore` แล้ว):

```text
record/
├── audio/              # ไฟล์เสียง .wav ที่อัดจากหน้า Recorder
├── stt/                # transcript (*_stt.txt)
├── shared_state.json   # สถานะ consent: WAITING / READY / RECORDING / FINISHED
└── pharmalog.db        # บันทึก consent (SQLite)

core_api/
├── api_queue.db        # คิวงานและผล EMR (SQLite)
└── temp_audio/         # สำเนาไฟล์เสียงที่ Core API รับมา
```

## ช่อง EMR ที่สกัดได้

กำหนดไว้ใน `EMR_FIELDS` ของ `modules/emr_groq.py` ถ้าจะเพิ่มหรือเปลี่ยนช่อง ต้องแก้ทั้ง `EMR_FIELDS` และ prompt ใน `_build_prompt()`

1. บทสนทนาที่จัดเรียงแล้ว
2. ประวัติการแพ้ยา
3. โรคประจำตัว
4. ประวัติการจ่ายยา
5. บันทึกทางการแพทย์
6. คำแนะนำจากเภสัช

## การตั้งค่า API Key

ระบบอ่านค่าจาก environment variable ก่อน ถ้าไม่มีจึงอ่านจากไฟล์ใน root โปรเจค (ไฟล์เหล่านี้อยู่ใน `.gitignore` ห้าม commit)

| บริการ | Environment variable | ไฟล์สำรอง | จำเป็น |
| --- | --- | --- | --- |
| Groq (สกัด EMR) | `GROQ_API_KEY` | `.groq_api_key` | ใช่ |
| Firebase | `FIREBASE_CREDENTIALS` (path), `FIREBASE_STORAGE_BUCKET` | `core_api/serviceAccountKey.json` | สำหรับหน้า History และ Cloud backup |
| Core API URL | `PHARMALOG_CORE_API_URL` | ค่าเริ่มต้น `http://127.0.0.1:8080` | ไม่ |

รัน `python setup_machine.py` ที่ root เพื่อสร้างไฟล์ key บนเครื่องใหม่ได้ อย่าเขียน key ลงในโค้ดหรือเอกสารใดๆ

## รันเฉพาะส่วนหน้าจอ

ต้องเปิด Core API ก่อน (`core_api/main.py`) จากนั้นที่ root โปรเจค:

```bash
# Back-office
streamlit run unified_app/app.py --server.address 127.0.0.1 --server.port 8515

# หน้าจอเภสัชกร (ต้องเปิด api.py สำหรับหน้า Consent ด้วย)
streamlit run pharmacist_app.py
```

## การแบ่งความรับผิดชอบ

### Frontend / UI — `pages/`, `components/`, `assets/`
- เพิ่มหน้าใหม่: สร้างไฟล์ใน `pages/` แล้วเพิ่ม `st.Page` และ `st.page_link` ใน `app.py` (และ `pharmacist_app.py` ถ้าหน้าเภสัชกรต้องใช้)
- แก้สี ฟอนต์ ระยะห่าง ที่ `assets/style.css`
- ห้ามเรียกโมเดลหรือ LLM ตรงจากหน้าจอ ให้ส่งงานผ่าน `modules/task_api.py`
- ข้อความจาก LLM หรือ transcript ที่แสดงผ่าน `unsafe_allow_html=True` ควร escape ด้วย `html.escape()` ก่อน

### Backend / AI — `modules/` และ `core_api/`
- `stt_typhoon.py`: โหลดโมเดลจาก `models/typhoon-asr-realtime.nemo` ถ้ามี ไม่มีจะดาวน์โหลดจาก Hugging Face
- `emr_groq.py`: prompt engineering และ parse JSON จาก LLM (ตอนนี้ใช้โมเดล `openai/gpt-oss-120b`)
- `pharmacy_dict.py`: เพิ่มคำที่ ASR ถอดผิดบ่อยได้ที่นี่
- เปลี่ยนการทำงานภายในได้อิสระ ตราบใดที่ชื่อฟังก์ชันและรูปแบบค่าที่คืนยังเหมือนเดิม

### Data — `record/`, `core_api/`, Firebase
- ข้อมูลเสียงและ EMR เป็นข้อมูลสุขภาพของคนไข้ ห้าม commit ขึ้น git และห้ามแชร์นอกทีม
- ผล EMR เก็บใน `core_api/api_queue.db` และ Firestore collection `patients_emr` ไฟล์เสียงถูกอัปโหลดไป Firebase Storage ที่ `recordings/`

## ขั้นตอนเพิ่มฟีเจอร์ใหม่

1. เขียน logic ใน `modules/` (หรือ endpoint ใหม่ใน `core_api/main.py` ถ้าเป็นงานหนัก)
2. ถ้าเป็นงานผ่าน Core API ให้เพิ่มฟังก์ชันเรียกใน `modules/task_api.py`
3. สร้างหรือแก้หน้าใน `pages/` ให้ import จาก `modules/`
4. เพิ่มลิงก์เมนูใน `app.py`
