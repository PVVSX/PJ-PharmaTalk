# speech_to_text — Demo STT เวอร์ชันก่อนหน้า

> **หมายเหตุ:** นี่เป็น demo เวอร์ชันก่อนหน้า ระบบล่าสุดอยู่ที่ `result_record/`  
> เอกสารรายงานความคืบหน้า: [docs/thesis/ผลการดำเนินงาน.md](../docs/thesis/ผลการดำเนินงาน.md)

โปรแกรมแปลงเสียงพูดเป็นข้อความด้วย Typhoon ASR Real-time

## 📁 โครงสร้างโปรเจกต์

```
speech_to_text/
├── app/                          # โฟลเดอร์หลักของแอปพลิเคชัน
│   ├── backend/                  # Backend Logic
│   │   ├── __init__.py
│   │   ├── config.py            # การตั้งค่าต่างๆ (model path, device, audio settings)
│   │   ├── models/              # โมเดล ASR
│   │   │   ├── __init__.py
│   │   │   └── asr_model.py    # TyphoonASRRecognizer class
│   │   └── services/           # Services
│   │       ├── __init__.py
│   │       └── audio_service.py # AudioRecorder, AudioDeviceManager
│   │
│   ├── frontend/                # Frontend UI
│   │   ├── __init__.py
│   │   ├── streamlit_app.py    # Main Streamlit application
│   │   ├── styles.py            # CSS styles
│   │   └── components/         # UI Components
│   │       ├── __init__.py
│   │       ├── sidebar.py      # Sidebar component (settings, model status)
│   │       ├── recording.py    # Recording component (audio recording, file upload)
│   │       ├── results.py     # Results component (transcription history)
│   │       └── audio_settings.py # Audio settings component (device, sample rate, etc.)
│   │
│   ├── speech_to_text_streamlit.py  # Entry point
│   │
│   └── backend/
│       └── typhoon-asr-realtime/    # โมเดล Typhoon ASR
│           ├── typhoon-asr-realtime.nemo
│           ├── README.md
│           └── gitattributes
│
├── run_speech_to_text.bat       # Script สำหรับรันโปรแกรม
└── README.md                    # ไฟล์นี้
```

## 🏗️ สถาปัตยกรรม

### Backend (`app/backend/`)
- **`config.py`**: เก็บการตั้งค่าต่างๆ เช่น path ของโมเดล, device, audio settings
- **`models/asr_model.py`**: Class `TyphoonASRRecognizer` สำหรับโหลดและใช้โมเดล ASR
- **`services/audio_service.py`**: 
  - Class `AudioRecorder` สำหรับบันทึกเสียงแบบ real-time ด้วย PyAudio
  - Class `AudioDeviceManager` สำหรับจัดการ audio input devices

### Frontend (`app/frontend/`)
- **`streamlit_app.py`**: Main application ที่รวม components ทั้งหมด
- **`styles.py`**: CSS styles สำหรับ UI
- **`components/`**: UI components ที่แยกตามหน้าที่
  - `sidebar.py`: Sidebar สำหรับการตั้งค่าและสถานะโมเดล
  - `recording.py`: ส่วนบันทึกเสียงและอัปโหลดไฟล์ (ใช้แนวคิดจาก record.py)
  - `results.py`: ส่วนแสดงผลลัพธ์การถอดเสียง
  - `audio_settings.py`: การตั้งค่าเสียง (device, sample rate, channels, chunk size)

## 🚀 การใช้งาน

### 1. ติดตั้ง Dependencies

```bash
# ติดตั้ง NeMo Toolkit (แนะนำ)
pip install nemo_toolkit[asr]

# หรือติดตั้ง typhoon-asr package (fallback)
pip install typhoon-asr

# ติดตั้ง Streamlit และ dependencies อื่นๆ
pip install streamlit pyaudio soundfile
```

### 2. รันโปรแกรม

**Windows:**
```bash
run_speech_to_text.bat
```

**หรือรันด้วย Streamlit โดยตรง:**
```bash
cd app
streamlit run speech_to_text_streamlit.py
```

## 📝 ฟีเจอร์

- ✅ **บันทึกเสียงแบบ Real-time**: บันทึกเสียงผ่านไมโครโฟนด้วย PyAudio
- ✅ **เลือกอุปกรณ์เสียง**: เลือกไมโครโฟนที่ต้องการใช้
- ✅ **การตั้งค่าเสียง**: ปรับ sample rate, channels, chunk size
- ✅ **แสดงระยะเวลาการบันทึก**: แสดงระยะเวลาที่บันทึกแบบ real-time
- ✅ **Preview เสียง**: ฟังเสียงที่บันทึกได้ก่อนถอดเสียง
- ✅ **อัปโหลดไฟล์เสียง**: รองรับไฟล์เสียงหลายรูปแบบ (WAV, MP3, M4A, FLAC)
- ✅ **ถอดเสียงหลายไฟล์พร้อมกัน**: ประมวลผลหลายไฟล์พร้อมกัน
- ✅ **ประวัติการถอดเสียง**: เก็บประวัติการถอดเสียงทั้งหมด
- ✅ **ใช้โมเดล Local**: โหลดโมเดลจากไฟล์ `.nemo` ในเครื่อง
- ✅ **โหลดโมเดลอัตโนมัติ**: โหลดโมเดลทันทีเมื่อเปิดแอป

## ⚙️ การตั้งค่า

### Model Path
โมเดลจะถูกโหลดจาก `app/backend/typhoon-asr-realtime/typhoon-asr-realtime.nemo` โดยอัตโนมัติ

### Device
- **CPU**: ใช้ CPU ในการประมวลผล (default)
- **CUDA**: ใช้ GPU ในการประมวลผล (ถ้ามี CUDA_VISIBLE_DEVICES)

## 🔧 การพัฒนาต่อยอด

### เพิ่ม Component ใหม่
1. สร้างไฟล์ใหม่ใน `app/frontend/components/`
2. Import และใช้ใน `streamlit_app.py`

### เพิ่ม Service ใหม่
1. สร้างไฟล์ใหม่ใน `app/backend/services/`
2. Import และใช้ใน components หรือ main app

### แก้ไขการตั้งค่า
แก้ไขไฟล์ `app/backend/config.py`

## 📚 Dependencies

- `streamlit`: Web UI framework
- `nemo_toolkit[asr]`: NeMo ASR models (แนะนำ)
- `typhoon-asr`: Typhoon ASR package (fallback)
- `pyaudio`: Audio recording
- `soundfile`: Audio file handling

## 🐛 Troubleshooting

### ไม่พบไฟล์โมเดล
- ตรวจสอบว่าไฟล์ `typhoon-asr-realtime.nemo` อยู่ใน `app/backend/typhoon-asr-realtime/`
- ตรวจสอบ path ใน `app/backend/config.py`

### ไม่สามารถโหลดโมเดลได้
- ติดตั้ง `nemo_toolkit[asr]`: `pip install nemo_toolkit[asr]`
- หรือติดตั้ง `typhoon-asr`: `pip install typhoon-asr`

### ไม่สามารถบันทึกเสียงได้
- ตรวจสอบว่าไมโครโฟนทำงานปกติ
- ตรวจสอบ permissions ของไมโครโฟน

## 📄 License

โปรเจกต์นี้ใช้โมเดล Typhoon ASR ซึ่งมี license: CC-BY-4.0

