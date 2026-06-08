import os
import torch
import torchaudio
from pyannote.audio import Pipeline

# 1. ตั้งค่า Token และดึง Pipeline มาจาก Hugging Face
HUGGING_FACE_TOKEN = (
    os.environ.get("HF_TOKEN")
    or os.environ.get("HUGGING_FACE_TOKEN")
    or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    or ""
).strip()
if not HUGGING_FACE_TOKEN:
    raise SystemExit("ตั้ง HF_TOKEN หรือ HUGGING_FACE_TOKEN ก่อนรัน")
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=HUGGING_FACE_TOKEN
)

# 2. ย้ายการคำนวณไปที่ GPU (ถ้ามี)
# สำหรับคุณกัปตันที่ใช้ Jetson หรือเครื่องที่มี NVIDIA GPU จะเร็วขึ้นมาก
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
pipeline.to(device)

# 3. รันการประมวลผล
# โหลดเสียงด้วย torchaudio (ข้าม torchcodec/FFmpeg ที่มีปัญหา)
audio_file = "sound/multi_speaker.wav"
waveform, sample_rate = torchaudio.load(audio_file)
audio_in = {"waveform": waveform, "sample_rate": sample_rate}
# สามารถระบุ num_speakers ถ้าทราบจำนวนคนพูดที่แน่นอนเพื่อความแม่นยำ
diarization = pipeline(audio_in, num_speakers=2) 

# 4. แสดงผลลัพธ์
# รุ่นใหม่คืน DiarizeOutput → ใช้ .speaker_diarization | โหมด legacy คืน Annotation ตรงๆ
ann = getattr(diarization, "speaker_diarization", diarization)
print("--- สรุปผลการแยกแยะผู้พูด ---")
for turn, _, speaker in ann.itertracks(yield_label=True):
    print(f"เริ่ม: {turn.start:.1f}s | จบ: {turn.end:.1f}s | ผู้พูด: {speaker}")

# 5. บันทึกผลลัพธ์ลงไฟล์ RTTM (ถ้าต้องการนำไป Evaluate ต่อ)
with open("output.rttm", "w") as rttm:
    ann.write_rttm(rttm)    