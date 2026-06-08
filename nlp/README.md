# nlp — Tokenization / แบ่งคำภาษาไทย

โฟลเดอร์สำหรับทดสอบการแบ่งคำ (word segmentation) จาก transcript ที่ถอดเสียงแล้ว ใช้ PyThaiNLP

> โมดูลนี้เป็น **การทดลองประเมินคุณภาพแบ่งคำ** — ไม่ได้รวมใน pipeline หลักของ `result_record`

## โครงสร้าง

```
nlp/
├── text/                    # ไฟล์ข้อความที่ถอดเสียงแล้ว
├── nlp_result/              # ผลการแบ่งคำจาก word_segmentation.py
├── groundtruth/             # ไฟล์ Ground Truth (คำตอบที่ถูกต้อง)
├── evaluation/              # กราฟผลประเมิน (PNG)
├── word_segmentation.py     # แบ่งคำ
├── evaluation.py              # ประเมินผลเทียบ ground truth
├── evaluation_results.txt   # ผลการประเมิน
└── requirements.txt
```

## Workflow

```
text/ → word_segmentation.py → nlp_result/ → evaluation.py (เทียบ groundtruth/) → evaluation_results.txt
```

## วิธีใช้งาน

```bash
cd nlp
python -m pip install -r requirements.txt
python word_segmentation.py
python evaluation.py
```

## Metrics ที่คำนวณ

- **Precision** — ความแม่นยำ
- **Recall** — ความครบถ้วน
- **F1-Score** — ค่าเฉลี่ย Precision และ Recall
- **WER** — Word Error Rate
- **CER** — Character Error Rate

## หมายเหตุ

1. ชื่อไฟล์ใน `nlp_result/` และ `groundtruth/` ต้องตรงกัน
2. ไฟล์ Ground Truth เป็นข้อความที่แบ่งคำแล้ว (แยกด้วยช่องว่าง)
3. ใช้ UTF-8 encoding ทุกไฟล์
