# คู่มือทดสอบ Typhoon Whisper Large v3 (สำหรับเครื่องที่แรงพอ)

ระบบตั้งค่าให้ใช้ **Typhoon Whisper Large v3** (`typhoon-ai/typhoon-whisper-large-v3`) เป็นโมเดลถอดเสียงหลักแล้ว
(`pharmalog.env` → `PHARMALOG_STT_ENGINE=whisper`) แต่ยังไม่เคยวัดความแม่นยำจริง เพราะเครื่องเดิมมี RAM 8 GB ไม่พอ
คู่มือนี้ใช้รันทดสอบบนเครื่องอื่น แล้วส่งผลกลับมา

## 1. สเปกเครื่องที่ต้องมี
| | ขั้นต่ำ | แนะนำ |
|---|---|---|
| RAM | 16 GB (Mac Apple Silicon หรือ PC) | 32 GB |
| GPU | ไม่บังคับ | NVIDIA ที่มี VRAM ≥ 6 GB (เร็วขึ้นมาก ใช้ fp16 อัตโนมัติ) |
| ดิสก์ว่าง | 20 GB (โมเดล Whisper 6.2 GB + PyTorch/NeMo) | |
| Python | 3.10–3.12 (**3.13 ใช้ไม่ได้** เพราะ NeMo) | 3.11 |
| อินเทอร์เน็ต | ครั้งแรกต้องดาวน์โหลดโมเดล ~6.2 GB จาก Hugging Face | |

## 2. สิ่งที่ต้องคัดลอกไปเครื่องเพื่อน
- โฟลเดอร์โปรเจกต์ทั้งหมด **ยกเว้น** `venv/` (ต้องสร้างใหม่บนเครื่องนั้น) และ `_backup_before_fixes_20261107/`
- `models/typhoon-asr-realtime.nemo` (ใช้เทียบกับ Realtime)
- `ground_truth/` และ `ไฟล์เสียงทั้งหมด/` (ใช้วัด CER)
- `.groq_api_key` — ต้องมีถ้าจะรันขั้น e2e (สรุป EMR)

> ⚠️ **ข้อมูลอ่อนไหว:** `ไฟล์เสียงทั้งหมด/` และ `ground_truth/` เป็นเสียง/บทสนทนาจริงของผู้รับบริการ และ `.groq_api_key` เป็นกุญแจบัญชีของคุณ
> ส่งให้เฉพาะคนที่ไว้ใจได้ ผ่านช่องทางส่วนตัว (เช่น USB/ไดรฟ์ที่แชร์เฉพาะบุคคล) ไม่ใช่ Git/กลุ่มแชต และให้ลบออกจากเครื่องเพื่อนหลังทดสอบเสร็จ
> ไม่จำเป็นต้องส่ง `core_api/serviceAccountKey.json` (การทดสอบปิด Cloud อยู่แล้ว)

## 3. ติดตั้ง
**macOS:** ดับเบิลคลิก `setup_pharmalog.command`

**Windows / Linux:**
```bash
python3.11 -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
# ถ้ามี NVIDIA GPU ให้ติดตั้ง torch รุ่น CUDA ตามคำสั่งจาก https://pytorch.org ก่อน pip install -r requirements.txt
```

## 4. รันทดสอบ
**macOS:** ดับเบิลคลิก `run_all.command` (ทำครบทุกขั้น ใช้เวลา 1–3 ชั่วโมง)

**หรือรันทีละขั้น (ทุกระบบปฏิบัติการ):**
```bash
# (ทางเลือก) ลองเร็วๆ ก่อนด้วย 3 ไฟล์สั้นที่สุด
STT_COMPARE_MAX_FILES=3 python tests/stt_compare.py

# เทียบเต็ม 25 ไฟล์ (รันต่อจากเดิมได้ถ้าหยุดกลางคัน)
python tests/stt_compare.py
python tests/choose_engine.py          # สรุปและแนะนำ (ไม่เปลี่ยน pharmalog.env เอง)

# ทดสอบทั้งระบบด้วย Whisper (ต้องปิดโปรแกรมที่ใช้พอร์ต 8500/8080 ก่อน)
PHARMALOG_DISABLE_CLOUD=1 PHARMALOG_STT_ENGINE=whisper PHARMALOG_ROLE_RULES=1 python tests/e2e_check.py
```
Windows (PowerShell) ตั้งตัวแปรแบบนี้: `$env:PHARMALOG_DISABLE_CLOUD="1"; $env:PHARMALOG_STT_ENGINE="whisper"; python tests/e2e_check.py`

หมายเหตุ
- ถ้าเครื่องมี RAM < 14 GB และไม่มี GPU NVIDIA สคริปต์จะข้าม Whisper ให้เอง (บังคับรันได้ด้วย `STT_COMPARE_FORCE_WHISPER=1` แต่เครื่องอาจค้าง)
- ถ้า Whisper ช้ามาก (ใช้เวลา > 3 เท่าของความยาวเสียงตั้งแต่ 2 ไฟล์แรก) สคริปต์จะหยุดรัน Whisper เองและบันทึกเหตุผลไว้
- บน Mac สคริปต์จะลอง MPS ก่อน ถ้าผลเพี้ยนหรือค้างจะกลับไปใช้ CPU อัตโนมัติ
- `e2e_check.py` ใช้โควตา Groq ประมาณครึ่งวัน (บัญชีฟรี 200,000 โทเคน/วัน/โมเดล) — รันวันละรอบพอ

## 5. ไฟล์ที่ต้องส่งกลับ (ในโฟลเดอร์ `logs/` ไม่มีเสียงคนไข้)
- `stt_compare.jsonl`, `stt_compare.md`, `stt_compare_progress.txt`
- `stt_decision.txt`
- `e2e_report.md`, `e2e_results.json` (ถ้ารัน e2e)

> `stt_compare.jsonl` และ `e2e_results.json` มีข้อความถอดเสียงของบทสนทนาอยู่ ให้ส่งกลับทางช่องทางส่วนตัวเหมือนตอนส่งไป

## 6. อ่านผล
`logs/stt_decision.txt` จะบอก CER เฉลี่ย/มัธยฐานของทั้งสองโมเดลบนไฟล์ชุดเดียวกัน และความเร็ว (RTF: 0.5 = ถอดเสียง 10 นาทีใช้ 5 นาที)
ผลของ Typhoon Realtime บนเครื่องเดิม (ใช้เทียบ): CER เฉลี่ย 0.538 หลังพจนานุกรม (มัธยฐาน 0.463), RTF 0.025

ถ้าผลออกมาว่า Realtime แม่นกว่าชัดเจนหรือ Whisper ช้าเกินไป เปลี่ยนกลับได้โดยแก้ `pharmalog.env` เป็น `PHARMALOG_STT_ENGINE=realtime`
หรือรัน `python tests/choose_engine.py --apply`
