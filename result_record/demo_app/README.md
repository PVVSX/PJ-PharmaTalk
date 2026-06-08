# Demo App ระบบบันทึกเวชระเบียนอัตโนมัติ (EMR)

แอปนี้เป็น Streamlit demo สำหรับให้เภสัชกรกรอกข้อมูลผู้ป่วย วางบทสนทนา และให้ Gemini ช่วยสกัดข้อมูลลงแบบฟอร์ม EMR
รองรับการบันทึก/อัปโหลดเสียงบทสนทนา แล้วแยกผู้พูดด้วย `diarize_final.py` และถอดเสียงด้วยโมเดล NeMo `model_speech_to_text/typhoon-isan-asr-realtime.nemo`

## วิธีรัน

### Windows (ดับเบิลคลิก)

จากโฟลเดอร์โปรเจกต์หลัก รัน `launch_streamlit_emr_app.bat` — เปิด `streamlit_emr_app.py` ที่ `http://localhost:8501` และติดตั้งแพ็กเกจจาก `demo_app/requirements.txt` อัตโนมัติถ้ายังไม่มี Streamlit

### Command line

จากโฟลเดอร์โปรเจกต์:

```bash
streamlit run streamlit_emr_app.py
```

ทางเลือกเทียบเท่า:

```bash
streamlit run demo_app/app.py
```

ถ้ายังไม่มีแพ็กเกจ:

```bash
python -m pip install -r demo_app/requirements.txt
```

ถ้าติดตั้ง NeMo แล้วเจอ error เกี่ยวกับ `youtokentome` / `Cython` บน Python 3.8 ให้ติดตั้งตัว build helper ก่อน:

```bash
python -m pip install Cython wheel
python -m pip install youtokentome --no-build-isolation
python -m pip install -r demo_app/requirements.txt
```

หมายเหตุ: ถ้าจะอัปโหลดไฟล์ `.mp3` หรือ `.m4a` ควรติดตั้ง `ffmpeg` ในเครื่องด้วย ส่วนไฟล์ `.wav` ใช้งานได้ตรงกว่า

## ความเร็ว speaker diarization (pyannote)

`diarize_final.py` โหลดโมเดล `pyannote/speaker-diarization-3.1` **ครั้งเดียวต่อ process** แล้วใช้แคช — ครั้งแรกอาจช้า (ดาวน์โหลด/โหลดหน่วยความจำ) แต่ครั้งถัดไปใน Streamlit จะเร็วกว่าเดิมมาก

- ดีบัก / บังคับโหลดโมเดลใหม่: `set DIARIZATION_RELOAD_PIPELINE=1` ก่อนรัน Streamlit
- มี **GPU (CUDA)**: pyannote รันบน GPU อัตโนมัติ — เร็วกว่า CPU ชัดเจน
- ขั้น **inference ต่อไฟล์** ยังใช้เวลาตามความยาวเสียง (ไม่มี magic ลดเวลาโดยไม่เสียคุณภาพ)

## NeMo + ONNX บน Windows (Streamlit)

บางเครื่องแสดง `DLL load failed` ตอน `import onnx` ร่วมกับ Streamlit/pyannote ใน process เดียวกัน แอปจะส่งงานถอดเสียง NeMo ไป **subprocess แยก** อัตโนมัติบน Windows เมื่อรันภายใต้ Streamlit (ตัวแปร `SPEECH_NEMO_ISOLATED=auto`)

- บังคับใช้โหมดแยก process: `set SPEECH_NEMO_ISOLATED=1`
- บังคับใช้ใน process เดียว (debug): `set SPEECH_NEMO_ISOLATED=0`
- ถ้า subprocess ก็ยังล้ม ให้ติดตั้ง [Visual C++ Redistributable x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) แล้ว `python -m pip install --force-reinstall onnx==1.17.0`

## Gemini API Key

ค่าเริ่มต้นโมเดล: `gemini-2.0-flash` (เปลี่ยนด้วย `set GEMINI_MODEL=...`)

ถ้าเจอ **503 / high demand** แอปจะ **ลองใหม่อัตโนมัติ** และสลับไปโมเดลสำรอง (`gemini-1.5-flash` ฯลฯ)  
บน **Python 3.8** ใช้ **REST API** เป็นหลัก (ไม่ต้องติดตั้ง `google-genai` ใหม่)

ตั้งค่าอย่างใดอย่างหนึ่ง:

```bash
set GEMINI_API_KEY=your_key
```

หรือสร้างไฟล์ `.gemini_api_key` ที่โฟลเดอร์โปรเจกต์หลัก แล้วใส่ key หนึ่งบรรทัด

## การใช้เสียง

ใน Tab `บันทึกเวชระเบียน` ส่วน `Automation` สามารถเปิดหัวข้อ `บันทึกเสียง / ถอดเสียงเป็นบทสนทนา` แล้วเลือกอย่างใดอย่างหนึ่ง:

- บันทึกเสียงจากไมค์ผ่าน `st.audio_input` ถ้า Streamlit เวอร์ชันที่ติดตั้งรองรับ
- อัปโหลดไฟล์เสียง `.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`

เมื่อกด `ถอดเสียง + แยกผู้พูด แล้วใส่ช่องบทสนทนา` ระบบจะบันทึกเสียงไว้ที่ `patient_info/audio_inputs/`, สร้าง transcript และไฟล์ CSV ผล diarization จากนั้นเติมข้อความลงช่อง `บทสนทนา` ให้อัตโนมัติ

## ข้อมูลที่บันทึก

เมื่อกด `บันทึกเวชระเบียน` ระบบจะบันทึกไฟล์ไว้ที่:

```text
patient_info/
```

โดยมีทั้ง JSON รายเคส และ CSV รวม:
พร้อม PDF รายเคสสำหรับดาวน์โหลด/พิมพ์

```text
patient_info/emr_records.csv
patient_info/audio_inputs/<audio>.transcript.txt
patient_info/audio_inputs/<audio>.diarization.csv
patient_info/<record_id>_<HN>_<ชื่อผู้ป่วย>.pdf
```

## หน้าจอในแอป

- Tab `บันทึกเวชระเบียน`: กรอกข้อมูล วิเคราะห์ด้วย AI และบันทึกเวชระเบียน
- Tab `LOG`: แสดง CSV log เป็นตาราง มีระบบค้นหา และปุ่มโหลด PDF รายเคส

ใน CSV จะมีคอลัมน์ `pdf_file`, `pdf_path`, `pdf_link`, `audio_path`, `transcript_path`, และ `diarization_csv` เพื่ออ้างอิงไฟล์ PDF/เสียง/transcript ที่เก็บไว้ในเครื่อง
