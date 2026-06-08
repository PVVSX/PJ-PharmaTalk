# Evaluation Report: 500 Cases

- Prediction: `C:\Users\Captan\Desktop\project_updated\result_record\report\500\gemini_extract.csv`
- Ground truth: `C:\Users\Captan\Desktop\project_updated\result_record\report\500\บท500_ground_truth.csv`
- GT cases: 500
- Prediction cases: 499
- Matched cases: 499

## Metrics

| Field | Lenient Score | Type/Token F1 | Strict NER F1 | Chunk Recall | Exact Row Match |
|---|---:|---:|---:|---:|---:|
| ประเภท | 0.922 | 0.922 | 0.922 | 0.730 | 0.730 |
| ประวัติการแพ้ยา | 0.910 | 0.267 | 0.200 | 0.773 | 0.240 |
| โรคประจำตัว | 0.882 | 0.550 | 0.494 | 0.643 | 0.604 |
| ประวัติการจ่ายยา | 0.299 | 0.197 | 0.072 | 0.136 | 0.792 |
| บันทึกทางการแพทย์ | 0.392 | 0.239 | 0.002 | 0.006 | 0.002 |
| คำแนะนำจากเภสัช | 0.621 | 0.422 | 0.038 | 0.098 | 0.040 |

## Notes

- `Lenient Score` is the headline metric for this view: exact substring matches receive full credit and near paraphrases receive partial credit via text similarity.
- `NER F1` uses comma/semicolon-separated spans as mention entities and exact matching after normalization.
- `Chunk Recall` is more forgiving for GT-short vs prediction-long cases: it checks whether GT chunks appear inside the prediction.
- Optional Gemini boundary judging is available with `--gemini-judge` for semantic assessment.

## Lowest Chunk-Recall Examples

### Case 1 — ประวัติการจ่ายยา (chunk recall 0.000)
- GT: พาราเซตามอล (ทานเมื่อเช้า)
- Pred: ทานพาราไป 1 เม็ดเมื่อเช้า

### Case 1 — บันทึกทางการแพทย์ (chunk recall 0.000)
- GT: ปวดหัวข้างเดียวตุบๆ ที่ขมับ มีอาการคลื่นไส้ร่วมด้วย
- Pred: ปวดหัวข้างเดียว ปวดตุบๆ ตรงขมับ มีคลื่นไส้นิดหน่อย เป็นไมเกรนอยู่แล้ว ทานพาราแล้วไม่ดีขึ้น

### Case 1 — คำแนะนำจากเภสัช (chunk recall 0.000)
- GT: ยาแก้ปวดไมเกรน → ทาน 1 เม็ดตอนที่มีอาการ
- Pred: ยาแก้ปวดไมเกรนเฉพาะกิจ → ทาน 1 เม็ดตอนมีอาการ

### Case 2 — บันทึกทางการแพทย์ (chunk recall 0.000)
- GT: ซื้อยาให้แฟน มีอาการปวดฟันรุนแรง
- Pred: อาการปวดฟันรุนแรงจนนอนไม่ได้, แพ้ยา ibuprofen ทําให้ตาบวม, ยาที่จ่ายอาจระคายเคืองกระเพาะ

### Case 2 — คำแนะนำจากเภสัช (chunk recall 0.000)
- GT: ยาแก้ปวดฟัน → ทานครั้งละ 1 เม็ด หลังอาหารทันที
- Pred: ยาแก้ปวดฟัน (ตัวที่จ่าย) → ทานครั้งละ 1 เม็ด หลังอาหารทันที

### Case 3 — บันทึกทางการแพทย์ (chunk recall 0.000)
- GT: ผื่นคันลักษณะปื้นขึ้นทั่วตัวหลังทานอาหารทะเล ไม่มีอาการหายใจลําบาก
- Pred: ผู้ป่วยมีผื่นคันขึ้นเป็นปื้นทั่วตัวหลังทานอาหารทะเลเมื่อเย็น ไม่มีอาการแน่นหน้าอก หายใจไม่ออก หรือปากบวม

### Case 4 — บันทึกทางการแพทย์ (chunk recall 0.000)
- GT: ซื้อให้ลูกชายอายุ 5 ขวบ มีอาการคันและรอยแดงจากยุงกัด
- Pred: ลูกชายอายุ 5 ขวบ โดนยุงกัด เกาจนเป็นรอยแดง ไม่มีประวัติแพ้ยา

### Case 5 — บันทึกทางการแพทย์ (chunk recall 0.000)
- GT: เจ็บคอมาก คอแดง มีไข้และน้ํามูกใส
- Pred: เจ็บคอมาก กลืนน้ําลายเจ็บ เหมือนจะมีไข้ มีน้ํามูกใสนิดหน่อย คอแดงค่อนข้างมาก ทานยาละลายลิ่มเลือดอยู่ ต้องเลี่ยงยาแก้ปวดอักเสบกลุ่มอื่น

### Case 5 — คำแนะนำจากเภสัช (chunk recall 0.000)
- GT: ยาอมแก้เจ็บคอ, ยาลดไข้พาราเซตามอล → (ไม่ได้ระบุวิธีกินละเอียด)
- Pred: เลี่ยงยาแก้ปวดอักเสบกลุ่มอื่น

### Case 6 — บันทึกทางการแพทย์ (chunk recall 0.000)
- GT: แสบท้อง จุกเสียดลิ้นปี่ เรอเปรี้ยว ทานข้าวไม่ตรงเวลา
- Pred: อาการแสบท้องมาก โดยเฉพาะตอนหิวหรือหลังทานอาหารเผ็ด มีเรอเปรี้ยวบ่อยๆ จุกตรงลิ้นปี่ มีประวัติเป็นกรดไหลย้อนมานานแล้ว ช่วงนี้ทานข้าวไม่เป็นเวลา

### Case 6 — คำแนะนำจากเภสัช (chunk recall 0.000)
- GT: ยาลดกรด → ทานก่อนอาหารครึ่งชั่วโมง 3 มื้อ และอย่าทานแล้วนอนทันที
- Pred: ยาลดกรด → ทานก่อนอาหารครึ่งชั่วโมง 3 มื้อ, ปรับพฤติกรรมอย่าทานแล้วนอนทันที

### Case 7 — โรคประจำตัว (chunk recall 0.000)
- GT: ความดันโลหิตสูง
- Pred: ความดันสูง
