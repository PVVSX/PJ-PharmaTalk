# result_record — ระบบบันทึกเวชระเบียนอัตโนมัติ (เวอร์ชันล่าสุด)

โฟลเดอร์หลักที่อ้างอิงว่าเวอร์ชันล่าสุดของโปรเจกต์ใช้อะไรบ้าง

**Pipeline:** เสียง → แยกผู้พูด → ถอดเสียง → สกัดฟิลด์ EMR (Gemini) → ประเมินผล

## โครงสร้าง

```
result_record/
├── diarize_final.py           # Speaker diarization (pyannote 3.1)
├── speech_to_text.py          # ถอดเสียง Typhoon Isan ASR
├── nemo_asr_isolated_worker.py # NeMo worker (subprocess บน Windows)
├── classify_gemini_extract.py # สกัดฟิลด์ EMR ด้วย Gemini
├── evaluation/                # สคริปต์ประเมินผล
├── docs/                      # คู่มือและตารางประเมิน
├── model_speech_to_text/      # โมเดล typhoon-isan-asr-realtime.nemo
├── data/                      # ข้อมูลทดสอบ (เสียง, transcript, 500 เคส)
├── report/                    # ผลการประเมินและรายงาน (รวม Ground_truth.xlsx)
└── patient_info/              # ข้อมูลเวชระเบียนผู้ป่วยรายเคส
```

## วิธีเปิดเว็บแอปหลักของโปรเจกต์ (PharmaLog AI)

สำหรับการใช้งานเว็บแอปพลิเคชัน ให้รันจากโฟลเดอร์หลักของโปรเจกต์ `PharmaLog/`:
- **Pharmacist Portal**: `streamlit run pharmacist_app.py --server.port 8501`
- **Unified Back-Office**: `streamlit run unified_app/app.py --server.port 8515`
- **PharmaLog AI Lab**: `streamlit run lab/app.py --server.port 8525` (หรือรัน `run_lab.bat`)

## สคริปต์ Pipeline (รันแยก)

```bash
# ถอดเสียงทั้งโฟลเดอร์ data/voice/
python speech_to_text.py

# สกัดฟิลด์จากบทสนทนา 500 เคส
python classify_gemini_extract.py --from-data บท500_split

# ประเมินผล
python evaluation/evaluate_500_ground_truth.py
python evaluation/evaluate_ground_truth_f1.py
```

## โฟลเดอร์ย่อย

| โฟลเดอร์ | ดูรายละเอียด |
|----------|-------------|
| `data/` | [data/README.md](data/README.md) |
| `report/` | [report/README.md](report/README.md) |
| `evaluation/` | [evaluation/README.md](evaluation/README.md) |
| `docs/` | [PHARMACIST_EVAL_GUIDE.md](docs/PHARMACIST_EVAL_GUIDE.md) |
| `patient_info/` | [patient_info/README.md](patient_info/README.md) |

## การตั้งค่า

- `GEMINI_API_KEY` — สำหรับสกัดฟิลด์ EMR
- `HF_TOKEN` — สำหรับ pyannote speaker-diarization-3.1
- `SPEECH_NEMO_ISOLATED=auto` — NeMo รัน subprocess แยกบน Windows (ค่าเริ่มต้น)
