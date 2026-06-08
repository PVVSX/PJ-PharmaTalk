# 🎤 Audio Recorder - Streamlit App

แอปพลิเคชันอัดเสียงที่สร้างด้วย Streamlit พร้อมฟีเจอร์การบันทึก เล่น และจัดการไฟล์เสียง

## ✨ Features

- 🎙️ **อัดเสียง**: บันทึกเสียงจากไมโครโฟน
- ▶️ **เล่นเสียง**: ฟังเสียงที่อัดไว้
- 💾 **บันทึกไฟล์**: บันทึกเป็นไฟล์ WAV ในโฟลเดอร์ `@record/`
- 📊 **แสดงคลื่นเสียง**: ดูกราฟคลื่นเสียง
- 📁 **จัดการไฟล์**: ดูและลบไฟล์ที่บันทึกไว้
- 🕒 **Timestamp**: ระบบเวลาแบบอ่านง่าย (DD/MM/YYYY HH:MM:SS)
- 📥 **ดาวน์โหลด**: ดาวน์โหลดไฟล์เสียงได้
- 🔄 **เรียงลำดับ**: จัดเรียงไฟล์ตามเวลาที่บันทึก (ใหม่สุดก่อน)

## 🚀 การติดตั้ง

### 1. ติดตั้ง Python
ให้แน่ใจว่าคุณมี Python 3.7+ ติดตั้งอยู่

### 2. ติดตั้ง Dependencies

```bash
pip install -r requirements.txt
```

**หมายเหตุ**: สำหรับ Windows อาจต้องติดตั้ง PyAudio แยก:

```bash
# สำหรับ Windows
pip install pipwin
pipwin install pyaudio

# หรือใช้ conda
conda install pyaudio
```

### 3. รันแอป

```bash
streamlit run app.py
```

แอปจะเปิดในเบราว์เซอร์ที่ `http://localhost:8501`

> หมายเหตุ: หากเปิดแอปแล้วไม่พบไมโครโฟน ให้ตรวจสอบสิทธิ์ไมโครโฟนในระบบปฏิบัติการ และติดตั้ง PyAudio ตามขั้นตอนด้านล่าง

## 🎯 วิธีใช้

1. **เริ่มอัดเสียง**: กดปุ่ม "🔴 Start Recording"
2. **หยุดอัดเสียง**: กดปุ่ม "⏹️ Stop Recording" 
3. **เล่นเสียง**: กดปุ่ม "▶️ Play Recording" เพื่อฟัง
4. **บันทึกไฟล์**: กดปุ่ม "💾 Save Recording" เพื่อบันทึก
5. **จัดการไฟล์**: ดูและลบไฟล์ในส่วน "📁 Saved Recordings"

## 📋 Requirements

- Python 3.7+
- Streamlit
- PyAudio
- NumPy
- Wave (built-in)
- Threading (built-in)
- Datetime (built-in)
- OS (built-in)

## 🔧 การแก้ไขปัญหา

### ปัญหา PyAudio บน Windows
```bash
# วิธีที่ 1: ใช้ pipwin
pip install pipwin
pipwin install pyaudio

# วิธีที่ 2: ใช้ conda
conda install pyaudio

# วิธีที่ 3: ดาวน์โหลด wheel file
# ไปที่ https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
# ดาวน์โหลดไฟล์ที่ตรงกับ Python version ของคุณ
pip install PyAudio-0.2.11-cp39-cp39-win_amd64.whl
```

### ปัญหาการอนุญาตไมโครโฟน
- บน Windows: ไปที่ Settings > Privacy > Microphone
- บน macOS: ไปที่ System Preferences > Security & Privacy > Microphone
- บน Linux: ตรวจสอบการตั้งค่า ALSA/PulseAudio

## 📁 โครงสร้างไฟล์

```
record/
├── app.py              # แอปหลัก
├── requirements.txt    # Dependencies
├── README.md          # คู่มือการใช้งาน
└── @record/           # ไฟล์เสียงที่บันทึก (จะสร้างอัตโนมัติ)
    ├── recording_2024-01-15_14-30-25.wav
    ├── recording_2024-01-15_15-45-10.wav
    └── ...
```

## 🎵 รูปแบบไฟล์

- **Input**: ไมโครโฟน (44.1 kHz, 16-bit, Mono)
- **Output**: WAV files (44.1 kHz, 16-bit, Mono)
- **Encoding**: PCM

## 🔒 ความปลอดภัย

- ไฟล์เสียงจะถูกบันทึกในโฟลเดอร์ `@record/` ในเครื่องของคุณ
- ไม่มีการส่งข้อมูลไปยังเซิร์ฟเวอร์ภายนอก
- ข้อมูลทั้งหมดประมวลผลในเครื่อง

## 📞 การสนับสนุน

หากพบปัญหาหรือต้องการความช่วยเหลือ:
1. ตรวจสอบการติดตั้ง PyAudio
2. ตรวจสอบการอนุญาตไมโครโฟน
3. ตรวจสอบ Python version (ต้องเป็น 3.7+)

---

Made with ❤️ using Streamlit
