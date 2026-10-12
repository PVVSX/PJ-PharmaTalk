# patient_info — ผลลัพธ์จาก Demo App

โฟลเดอร์นี้เก็บข้อมูลที่สร้างขึ้นเมื่อใช้งาน `demo_app` (บันทึกเวชระเบียน)

```
patient_info/
├── emr_records.csv          # log รวมทุกเคส
├── <record_id>_<HN>_<ชื่อ>.json   # ข้อมูลรายเคส
├── <record_id>_<HN>_<ชื่อ>.pdf    # PDF รายเคส
└── audio_inputs/            # เสียง + transcript + diarization (สร้างอัตโนมัติ)
```

มี **ตัวอย่าง 1 เคส** (`test01`) สำหรับอ้างอิง — เมื่อรันแอปจริงจะเพิ่มไฟล์ใหม่ในโฟลเดอร์นี้อัตโนมัติ
