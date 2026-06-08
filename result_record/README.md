# result_record — ระบบบันทึกเวชระเบียนอัตโนมัติ (เวอร์ชันล่าสุด)

โฟลเดอร์หลักที่อ้างอิงว่าเวอร์ชันล่าสุดของโปรเจกต์ใช้อะไรบ้าง

**Pipeline:** เสียง → แยกผู้พูด → ถอดเสียง → สกัดฟิลด์ EMR (Gemini) → ประเมินผล

## โครงสร้าง

```
result_record/
├── launch_streamlit_emr_app.bat # เปิดแอป EMR บน Windows (ดับเบิลคลิก)
├── demo_app/                  # wrapper + requirements สำหรับ Streamlit
├── streamlit_emr_app.py       # แอป EMR หลัก
├── diarize_final.py           # Speaker diarization (pyannote 3.1)
├── speech_to_text.py          # ถอดเสียง Typhoon Isan ASR
├── nemo_asr_isolated_worker.py # NeMo worker (subprocess บน Windows)
├── classify_gemini_extract.py # สกัดฟิลด์ EMR ด้วย Gemini
├── evaluation/                # สคริปต์ประเมินผล
├── docs/                      # คู่มือและตารางประเมิน
├── model_speech_to_text/      # โมเดล typhoon-isan-asr-realtime.nemo
├── data/                      # ข้อมูลทดสอบ (เสียง, transcript, 500 เคส)
├── report/                    # ผลการประเมินและรายงาน
└── patient_info/              # ผลลัพธ์ runtime จาก demo app
```

## วิธีรัน Demo App

### Windows (แนะนำ)

ดับเบิลคลิก `launch_streamlit_emr_app.bat` ที่โฟลเดอร์โปรเจกต์ — สคริปต์จะเปลี่ยนไปโฟลเดอร์ที่ถูกต้อง ใช้ Python จาก `.venv`/`venv` ถ้ามี ติดตั้งแพ็กเกจอัตโนมัติเมื่อยังไม่มี Streamlit แล้วเปิดแอปที่ `http://localhost:8501`

### Command line

```bash
cd result_record
python -m pip install -r demo_app/requirements.txt
set GEMINI_API_KEY=your_key
set HF_TOKEN=your_huggingface_token
streamlit run streamlit_emr_app.py
```

ทางเลือกเทียบเท่า: `streamlit run demo_app/app.py` (เรียกโค้ดจาก `streamlit_emr_app.py`)

รายละเอียด: [demo_app/README.md](demo_app/README.md)

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
