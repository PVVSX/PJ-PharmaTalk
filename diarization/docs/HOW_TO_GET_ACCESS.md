# 🔓 วิธีขอสิทธิ์เข้าถึงโมเดล pyannote.audio

## ⚠️ ปัญหา: Error 403 - Access Denied

ถ้าคุณได้รับ error:
```
403 Client Error
Cannot access gated repo
Access to model pyannote/speaker-diarization-3.1 is restricted
```

หมายความว่าคุณยังไม่ได้ยอมรับข้อตกลงการใช้งานโมเดล

## ✅ วิธีแก้ไข (ทำตามขั้นตอน)

### ขั้นตอนที่ 1: สร้าง Hugging Face Account

1. ไปที่: https://huggingface.co/join
2. สร้างบัญชี (Sign Up)
3. ยืนยันอีเมล

### ขั้นตอนที่ 2: สร้าง Access Token

1. ไปที่: https://huggingface.co/settings/tokens
2. คลิก "New token"
3. ตั้งชื่อ token (เช่น: "pyannote-diarization")
4. เลือกสิทธิ์ "Read"
5. คลิก "Generate token"
6. **คัดลอก token** (จะแสดงแค่ครั้งเดียว!)

### ขั้นตอนที่ 3: ยอมรับข้อตกลงการใช้งานโมเดล

1. ไปที่: https://huggingface.co/pyannote/speaker-diarization-3.1
2. **สำคัญ**: ต้องล็อกอินด้วยบัญชี Hugging Face ก่อน
3. คลิกปุ่ม **"Agree and access repository"**
4. อ่านและยอมรับข้อตกลง
5. รอให้ได้รับอนุมัติ (มักจะทันที แต่บางครั้งอาจใช้เวลาสักครู่)

### ขั้นตอนที่ 4: ใช้ Token ในโค้ด

1. เปิดไฟล์ `pyanote.py`
2. แก้ไขบรรทัดนี้:
   ```python
   HF_TOKEN = "hf_YOUR_TOKEN_HERE"  # วาง token ที่คัดลอกมา
   ```
3. บันทึกไฟล์

### ขั้นตอนที่ 5: ทดสอบ

รันโปรแกรม:
```bash
python pyanote.py
```

## 🔍 ตรวจสอบว่า Token ถูกต้อง

Token ควรมีลักษณะดังนี้:
- เริ่มต้นด้วย `hf_`
- ยาวประมาณ 40-50 ตัวอักษร
- ตัวอย่าง: `hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

## ❓ ปัญหาที่พบบ่อย

### Q: Token ไม่ทำงาน
**A**: ตรวจสอบว่า:
- Token ถูกคัดลอกมาครบถ้วน (ไม่มีช่องว่าง)
- Token ยังไม่หมดอายุ
- Token มีสิทธิ์ "Read"

### Q: ยังได้ Error 403 หลังจากยอมรับข้อตกลงแล้ว
**A**: 
- รอสักครู่ (อาจใช้เวลาสักนาทีในการอัปเดต)
- ลองล็อกอินและล็อกเอาต์ Hugging Face อีกครั้ง
- ตรวจสอบว่าใช้ token ที่ถูกต้อง

### Q: ไม่เห็นปุ่ม "Agree and access repository"
**A**:
- ตรวจสอบว่าล็อกอินแล้ว
- ลองรีเฟรชหน้าเว็บ
- ตรวจสอบว่าไปที่ URL ที่ถูกต้อง

## 🔗 ลิงก์ที่สำคัญ

- **หน้าโมเดล**: https://huggingface.co/pyannote/speaker-diarization-3.1
- **สร้าง Token**: https://huggingface.co/settings/tokens
- **หน้าหลัก Hugging Face**: https://huggingface.co

## 📝 หมายเหตุ

- Token เป็นข้อมูลลับ **อย่าแชร์ให้ใคร**
- Token สามารถลบและสร้างใหม่ได้ที่หน้า settings
- ถ้า Token ถูกแชร์หรือรั่วไหล ให้ลบและสร้างใหม่ทันที
