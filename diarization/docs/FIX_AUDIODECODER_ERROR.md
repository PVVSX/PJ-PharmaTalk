# 🔧 แก้ไข AudioDecoder Error

## ⚠️ ปัญหา

Error: `NameError: name 'AudioDecoder' is not defined`

ปัญหานี้เกิดจาก **dependency conflicts** ภายใน pyannote.audio library เอง ไม่ใช่จากโค้ดของคุณ

## 🔍 สาเหตุ

1. **protobuf version conflicts**: 
   - pyannote.audio ต้องการ protobuf เวอร์ชันหนึ่ง
   - แต่มี packages อื่นๆ (เช่น nemo-toolkit) ที่ต้องการเวอร์ชันอื่น

2. **numpy version conflicts**:
   - pyannote.audio ต้องการ numpy < 2.0
   - แต่มี packages อื่นๆ ที่ต้องการ numpy >= 2.0

3. **Missing dependencies**:
   - บาง dependencies ที่ pyannote.audio ต้องการไม่ถูกติดตั้งครบ

## ✅ วิธีแก้ไข

### วิธีที่ 1: ใช้ Virtual Environment (แนะนำที่สุด) ⭐

สร้าง virtual environment แยกสำหรับ pyannote.audio:

```bash
# สร้าง virtual environment
python -m venv venv_pyanote

# เปิดใช้งาน (Windows)
venv_pyanote\Scripts\activate

# เปิดใช้งาน (Linux/Mac)
source venv_pyanote/bin/activate

# ติดตั้ง dependencies
pip install -r requirements_pyanote.txt

# ทดสอบ
python pyanote.py
```

### วิธีที่ 2: ใช้สคริปต์แก้ไขอัตโนมัติ

```bash
python fix_dependencies.py
```

สคริปต์นี้จะ:
- Downgrade protobuf เป็น < 6.0.0
- Downgrade numpy เป็น < 2.0.0
- Reinstall pyannote.audio

### วิธีที่ 3: แก้ไขด้วยตนเอง

```bash
# 1. Downgrade protobuf
pip install "protobuf>=5.26.1,<6.0.0" --force-reinstall

# 2. Downgrade numpy
pip install "numpy>=1.21.0,<2.0.0" --force-reinstall

# 3. Reinstall pyannote.audio
pip install --upgrade --force-reinstall pyannote.audio

# 4. ทดสอบ
python -c "from pyannote.audio import Pipeline; print('✅ สำเร็จ')"
```

### วิธีที่ 4: ใช้ Conda Environment

```bash
# สร้าง conda environment
conda create -n pyanote python=3.10
conda activate pyanote

# ติดตั้ง dependencies
pip install -r requirements_pyanote.txt
```

## 🧪 ทดสอบการแก้ไข

```bash
# ทดสอบ import
python -c "from pyannote.audio import Pipeline; print('✅ pyannote.audio พร้อมใช้งาน')"

# ทดสอบ AudioDecoder
python -c "from pyannote.audio.utils.audio import AudioDecoder; print('✅ AudioDecoder พร้อมใช้งาน')"
```

## ⚠️ หมายเหตุสำคัญ

1. **Virtual Environment เป็นวิธีที่ปลอดภัยที่สุด** เพราะ:
   - แยก dependencies ออกจากกัน
   - ไม่กระทบ packages อื่นๆ
   - ง่ายต่อการจัดการ

2. **การ Downgrade Packages อาจทำให้**:
   - packages อื่นๆ ที่ต้องการ protobuf 6.x หรือ numpy 2.x ทำงานผิดพลาด
   - nemo-toolkit อาจไม่ทำงาน

3. **nemo-toolkit และ pyannote.audio** อาจไม่สามารถใช้งานพร้อมกันได้ใน environment เดียว

## 🔗 ลิงก์ที่เกี่ยวข้อง

- [FIX_DEPENDENCIES.md](FIX_DEPENDENCIES.md) - คำแนะนำทั่วไปเกี่ยวกับ dependency conflicts
- [requirements_pyanote.txt](requirements_pyanote.txt) - รายการ dependencies ที่ถูกต้อง

## 📞 ถ้ายังแก้ไม่ได้

1. ตรวจสอบเวอร์ชัน Python (ควรเป็น 3.8-3.11)
2. อัปเดต pip: `pip install --upgrade pip`
3. ลบ cache: `pip cache purge`
4. ติดตั้งใหม่ทั้งหมด:
   ```bash
   pip uninstall pyannote.audio -y
   pip install pyannote.audio --no-cache-dir
   ```
