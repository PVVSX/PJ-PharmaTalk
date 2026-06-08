# diarization — Speaker Diarization

โฟลเดอร์เก็บการทำงานและการทดลอง Speaker Diarization ร่วมกับ Typhoon ASR

> **เวอร์ชันที่ใช้งานจริง:** `result_record/diarize_final.py` (pyannote 3.1)  
> โฟลเดอร์นี้เป็น **บันทึกการทดลอง** และ pipeline รุ่นก่อนหน้า

## โครงสร้าง

```
diarization/
├── pyanote+typhoon.py         # Pipeline หลัก: pyannote + Typhoon ASR
├── pyanote.py                 # pyannote อย่างเดียว
├── diarization.py             # SpeechBrain + Silero VAD (แนวทางทดลอง)
├── diarize_tuning.py          # ปรับจูน hyperparameter
├── model/                     # โมเดล Typhoon ASR (.nemo)
├── sound/                     # ไฟล์เสียงทดสอบ (45 WAV)
├── report/                    # ผล transcript หลัง diarization
├── docs/                      # คู่มือแก้ปัญหาและการขอสิทธิ์
├── archives/                  # ไฟล์ ZIP สำรอง (ไม่จำเป็นต่อการรัน)
└── requirements_pyanote.txt   # Dependencies
```

## สคริปต์หลัก

| สคริปต์ | สถานะ | คำอธิบาย |
|---------|--------|----------|
| `pyanote+typhoon.py` | ใช้งานได้ | แยกผู้พูด + ถอดเสียง Typhoon แบบ batch |
| `pyanote.py` | ทดลอง | diarization อย่างเดียว |
| `diarization.py` | ทดลอง | SpeechBrain clustering |
| `backup.py`, `test.py`, `dirai old.py` | legacy | สคริปต์เก่า — ไม่ใช้ใน pipeline หลัก |

## วิธีรัน (batch)

```bash
cd diarization
python -m pip install -r requirements_pyanote.txt
set HF_TOKEN=your_huggingface_token
python pyanote+typhoon.py
```

ผลลัพธ์ transcript จะอยู่ใน `report/` และ RTTM ใน `output.rttm`

## การขอสิทธิ์โมเดล pyannote

ดู [docs/HOW_TO_GET_ACCESS.md](docs/HOW_TO_GET_ACCESS.md)

## แก้ปัญหาที่พบบ่อย

- [docs/FIX_AUDIODECODER_ERROR.md](docs/FIX_AUDIODECODER_ERROR.md)
- [docs/FIX_DEPENDENCIES.md](docs/FIX_DEPENDENCIES.md)

## ข้อมูลที่ซ้ำกับ result_record

- `sound/*.wav` — ชุดเดียวกับ `result_record/data/voice/`
- `model/typhoon-isan-asr-realtime.nemo` — ชุดเดียวกับ `result_record/model_speech_to_text/`

สำหรับการใช้งานจริง ให้อ้างอิง `result_record/` เป็นหลัก
