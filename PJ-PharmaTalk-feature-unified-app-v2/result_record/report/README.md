# report — ผลการประเมินและรายงาน

| โฟลเดอร์ | เนื้อหา |
|----------|---------|
| `500/` | ผลสกัด Gemini จากบทสนทนา 500 เคส + metrics ใน `500/evaluation/` |
| `text_to_form/` | ผลสกัดจาก input ข้อความ (`data/text/`) |
| `speech_to_form/` | ผลสกัดจาก input เสียง (`data/text_from_speech/`) |
| `Grount_truth.xlsx` | Ground truth สำหรับประเมิน F1 |

## สร้าง/อัปเดตรายงาน

```bash
# สกัดฟิลด์ด้วย Gemini
python classify_gemini_extract.py --from-data บท500_split

# ประเมิน 500 เคส
python evaluation/evaluate_500_ground_truth.py

# ประเมิน F1 เทียบ Grount_truth.xlsx
python evaluation/evaluate_ground_truth_f1.py
```
