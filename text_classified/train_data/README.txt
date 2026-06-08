โฟลเดอร์ train_data ใช้สำหรับเทรนจับ keyword แยก 3 หมวด

ไฟล์ทั้ง 3 (รูปแบบ JSON):
- Drug_allergies.json       -> ประวัติการแพ้ยา
- Pre-existing_medical_conditions.json -> โรคประจำตัว
- Medication_history.json   -> ประวัติการจ่ายยา

รูปแบบแต่ละไฟล์: รายการของ object
  {"text": "ประโยคหรือ transcript จากบทสนทนา", "keywords": "คำตอบหรือคำสำคัญที่ต้องการจับ"}

ตัวอย่าง:
  {"text": "ผู้ป่วยบอกว่าไม่มีประวัติแพ้ยา", "keywords": "-"}
  {"text": "แพ้พาราเซตามอล ผื่นคัน", "keywords": "พาราเซตามอล"}

ถ้าไม่มีข้อมูลในหมวดนั้นใช้ "keywords": "-"
