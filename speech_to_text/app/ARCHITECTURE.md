# สถาปัตยกรรมโปรเจกต์

## 📐 โครงสร้าง Backend และ Frontend

### Backend (`app/backend/`)

Backend รับผิดชอบการจัดการ business logic, models, และ services

#### 1. Configuration (`config.py`)
- เก็บการตั้งค่าต่างๆ ของแอปพลิเคชัน
- Model path, device configuration
- Audio settings (sample rate, chunk size)
- Supported file formats

#### 2. Models (`models/asr_model.py`)
- **TyphoonASRRecognizer**: Class สำหรับจัดการโมเดล ASR
  - `load_model()`: โหลดโมเดลจากไฟล์ `.nemo`
  - `transcribe_audio()`: ถอดเสียงจากไฟล์เสียง

#### 3. Services

##### Audio Service (`services/audio_service.py`)
- **AudioRecorder**: Class สำหรับบันทึกเสียงแบบ real-time ด้วย PyAudio
  - `start_recording()`: เริ่มบันทึกเสียงจากไมโครโฟนด้วย PyAudio
  - `stop_recording()`: หยุดบันทึกและบันทึกเป็นไฟล์ WAV
  - `get_duration()`: คำนวณระยะเวลาการบันทึก
  - `get_audio_bytes()`: ได้ audio bytes สำหรับ preview
  - `_record_audio()`: Internal method สำหรับบันทึกใน thread แยก
- **AudioDeviceManager**: Class สำหรับจัดการ audio input devices
  - `get_input_devices()`: ดึงรายการ input devices ทั้งหมด
  - `get_microphone_devices()`: ดึงรายการไมโครโฟนเท่านั้น

### Frontend (`app/frontend/`)

Frontend รับผิดชอบการแสดงผล UI และการโต้ตอบกับผู้ใช้

#### 1. Main App (`streamlit_app.py`)
- Entry point ของ Streamlit application
- จัดการ session state
- รวม components ทั้งหมดเข้าด้วยกัน

#### 2. Styles (`styles.py`)
- เก็บ CSS styles สำหรับ UI
- Custom styling สำหรับ status boxes, headers

#### 3. Components (`components/`)

##### Sidebar (`sidebar.py`)
- แสดงสถานะโมเดล
- ปุ่มโหลดโมเดล
- การตั้งค่าเสียง
- ปุ่มล้างประวัติ

##### Recording (`recording.py`)
- ส่วนบันทึกเสียงแบบ real-time (ใช้แนวคิดจาก record.py)
- ปุ่ม toggle ขนาดใหญ่สำหรับเริ่ม/หยุดบันทึก
- แสดงระยะเวลาการบันทึกแบบ real-time
- Preview เสียงที่บันทึกได้
- อัปโหลดไฟล์เสียง
- ประมวลผลหลายไฟล์พร้อมกัน
- `process_audio()`: ประมวลผลไฟล์เสียงเดียว
- `process_multiple_files()`: ประมวลผลหลายไฟล์

##### Audio Settings (`audio_settings.py`)
- การเลือกไมโครโฟน (device selection)
- การตั้งค่า sample rate, channels, chunk size
- Device deduplication (ลบรายการซ้ำ)
- Device caching เพื่อประสิทธิภาพ

##### Results (`results.py`)
- แสดงประวัติการถอดเสียง
- แสดงผลลัพธ์ในรูปแบบ expandable sections
- ปุ่มคัดลอกผลลัพธ์

## 🔄 Data Flow

```
User Input (Frontend)
    ↓
Streamlit UI Components
    ↓
Backend Services/Models
    ↓
ASR Model (NeMo/Typhoon)
    ↓
Transcription Result
    ↓
Display in UI (Frontend)
```

## 📦 Dependencies

### Backend Dependencies
- `nemo_toolkit[asr]` หรือ `typhoon-asr`: สำหรับ ASR model
- `pyaudio`: สำหรับบันทึกเสียง
- `soundfile`: สำหรับจัดการไฟล์เสียง

### Frontend Dependencies
- `streamlit`: Web UI framework
- `numpy`: สำหรับการประมวลผลข้อมูล

## 🔌 Integration Points

### Backend → Frontend
- `TyphoonASRRecognizer` ถูกใช้ใน `streamlit_app.py` และ components
- `AudioRecorder` ถูกใช้ใน `recording.py` component

### Frontend → Backend
- Components เรียกใช้ methods จาก backend models และ services
- Session state ถูกจัดการใน `streamlit_app.py`

## 🎯 Design Principles

1. **Separation of Concerns**: Backend และ Frontend แยกกันชัดเจน
2. **Modularity**: แต่ละ component มีหน้าที่ชัดเจน
3. **Reusability**: Components และ services สามารถนำไปใช้ซ้ำได้
4. **Maintainability**: โครงสร้างชัดเจน ง่ายต่อการดูแลรักษา

## 🚀 การขยายโปรเจกต์

### เพิ่ม Feature ใหม่
1. **Backend**: สร้าง service หรือ model ใหม่ใน `backend/`
2. **Frontend**: สร้าง component ใหม่ใน `frontend/components/`
3. **Integration**: เชื่อมต่อใน `streamlit_app.py`

### เพิ่ม Model ใหม่
1. สร้าง class ใหม่ใน `backend/models/`
2. อัปเดต `config.py` ถ้าต้องการตั้งค่าใหม่
3. ใช้ใน components ผ่าน dependency injection

