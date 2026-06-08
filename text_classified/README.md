# text_classified — ทดสอบ Text Classification

โฟลเดอร์สำหรับทดสอบการจำแนกและสกัดข้อมูลจากบทสนทนา มี 2 แนวทาง:

1. **Fine-tuned T5** — จับ keyword 3 หมวด (แพ้ยา / โรคประจำตัว / ประวัติยา)
2. **Gemini extraction** — สกัดฟิลด์ structured จากบทสนทนา

> **เวอร์ชันที่ใช้งานจริง:** `result_record/classify_gemini_extract.py` (ใหม่กว่าและครบถ้วนกว่า)  
> โฟลเดอร์นี้เป็น **R&D sandbox** สำหรับทดลองและเทรนโมเดล

## โครงสร้าง

```
text_classified/
├── classify.py                # รัน inference ด้วยโมเดล T5 ที่เทรนแล้ว
├── classify_gemini_extract.py # สกัดด้วย Gemini (เวอร์ชันเก่า)
├── classify_model_extract.py  # สกัดด้วยโมเดล
├── train.py                   # เทรน T5 keyword model
├── train_extract_full.py      # เทรน extraction model
├── gemini_shared.py           # utility ร่วมสำหรับ Gemini
├── result_csv.py              # แปลงผลเป็น CSV
├── data/                      # บทสนทนา 500 เคส (dialogue_001–500)
├── train_data/                # ข้อมูลเทรน JSON (3 หมวด)
├── output_conditions/         # checkpoint โมเดลโรคประจำตัว
├── output_drug_allergies/     # checkpoint โมเดลแพ้ยา
├── output_medication_history/ # checkpoint โมเดลประวัติยา
└── result/                    # ผลการทดลอง (CSV, JSON ground truth)
```

## แนวทางที่ 1: Fine-tuned T5

```bash
cd text_classified
python -m pip install -r requirements.txt
python train.py          # เทรนโมเดล
python classify.py       # รัน inference
```

รูปแบบข้อมูลเทรน: ดู [train_data/README.txt](train_data/README.txt)

## แนวทางที่ 2: Gemini Extraction

```bash
set GEMINI_API_KEY=your_key
python classify_gemini_extract.py
```

ผลลัพธ์อยู่ใน `result/gemini_extract.csv`

## ความสัมพันธ์กับ result_record

| ไฟล์ | text_classified | result_record |
|------|-----------------|---------------|
| `classify_gemini_extract.py` | เวอร์ชันเก่า (~20 KB) | เวอร์ชันล่าสุด (~48 KB) |
| บทสนทนา 500 เคส | `data/dialogue_*.txt` | `data/บท500_split/case_*.txt` |
| ผล Gemini | `result/gemini_extract.csv` | `report/500/gemini_extract.csv` |
