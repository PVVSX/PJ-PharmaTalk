# 🔧 แก้ไข Dependency Conflicts

## ⚠️ ปัญหา

หลังจากติดตั้ง `pyannote.audio` อาจเกิด dependency conflicts กับ packages อื่นๆ:

- **protobuf**: nemo-toolkit ต้องการ ~5.29.5 แต่ pyannote.audio ติดตั้ง 6.33.4
- **numpy**: mediapipe ต้องการ <2 แต่ pyannote.audio ติดตั้ง 2.2.6

## ✅ วิธีแก้ไข

### วิธีที่ 1: ใช้ Virtual Environment (แนะนำ)

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
```

### วิธีที่ 2: Downgrade Packages

ถ้าต้องการใช้ใน environment เดียวกัน:

```bash
# Downgrade protobuf เพื่อให้เข้ากันได้กับ nemo-toolkit
pip install "protobuf>=5.26.1,<6.0.0"

# Downgrade numpy เพื่อให้เข้ากันได้กับ mediapipe
pip install "numpy>=1.21.0,<2.0.0"

# ติดตั้ง pyannote.audio อีกครั้ง
pip install pyannote.audio
```

### วิธีที่ 3: ใช้ Conda Environment

```bash
# สร้าง conda environment
conda create -n pyanote python=3.10
conda activate pyanote

# ติดตั้ง dependencies
pip install -r requirements_pyanote.txt
```

## 📝 หมายเหตุ

- **Virtual environment** เป็นวิธีที่ปลอดภัยที่สุด เพราะแยก dependencies ออกจากกัน
- ถ้าใช้ **วิธีที่ 2** อาจทำให้ packages อื่นๆ ที่ต้องการ protobuf 6.x หรือ numpy 2.x ทำงานผิดพลาด
- **nemo-toolkit** และ **pyannote.audio** อาจไม่สามารถใช้งานพร้อมกันได้ใน environment เดียว

## 🧪 ทดสอบการติดตั้ง

```bash
python -c "from pyannote.audio import Pipeline; print('✅ pyannote.audio พร้อมใช้งาน')"
```
