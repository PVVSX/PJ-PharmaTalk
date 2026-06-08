import torch
import torchaudio
import tempfile
import os
import time
import numpy as np
import uuid
import logging
import sys
import contextlib
import warnings

# ให้ Windows แสดงผลไทยและ emoji ได้
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ปิด tqdm (Progress Bar) ผ่าน Environment Variable
os.environ["TQDM_DISABLE"] = "1"

import nemo.collections.asr as nemo_asr
from pyannote.audio import Pipeline
from pyannote.core import Segment

# 0. ปิดการแจ้งเตือนและ Log ทุกประเภทเพื่อให้ Output สะอาดที่สุด
warnings.filterwarnings("ignore") # ปิด Python warnings ทั้งหมด
logging.disable(logging.CRITICAL) # ปิด logging ทั้งหมดของ Python
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3" # ปิด TensorFlow logging
os.environ["HYDRA_FULL_ERROR"] = "0"
os.environ["PYTHONWARNINGS"] = "ignore"

import nemo.utils
nemo.utils.logging.setLevel(nemo.utils.logging.ERROR) # ปิด NeMo logging

@contextlib.contextmanager
def suppress_stdout_stderr():
    """บริบทสำหรับซ่อน output ของระบบที่ปลอดภัยสำหรับ Windows"""
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

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

# 2. ย้ายการคำนวณไปที่ GPU (ถ้ามี) — ลดภาระโดยประมวลผลทีละช่วง
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
pipeline.to(device)
print(f"   ใช้ device: {device}")

# 3. โหลดโมเดล Typhoon Isan ASR (NeMo)
MODEL_PATH = "model/typhoon-isan-asr-realtime.nemo"
print(f"🔄 กำลังโหลดโมเดล Typhoon Isan ASR จาก {MODEL_PATH}...")
if os.path.exists(MODEL_PATH):
    asr_model = nemo_asr.models.ASRModel.restore_from(restore_path=MODEL_PATH)
    asr_model.to(device)
    asr_model.eval()
    print("✅ โหลดโมเดล Typhoon สำเร็จ\n")
else:
    print(f"❌ ไม่พบไฟล์โมเดลที่ {MODEL_PATH}")
    exit()

# 4. โหลดไฟล์เสียงและตั้งค่าช่วงประมวลผล
audio_dir = "sound"
CHUNK_DURATION_SEC = 180  # ประมวลผลทีละ 3 นาที เพื่อลด memory/GPU
# เรียงชื่อไฟล์ให้ลำดับแน่นอน และประมวลผลครบทุกไฟล์
audio_files = sorted([f for f in os.listdir(audio_dir) if f.endswith(".wav")])

if not audio_files:
    print(f"❌ ไม่พบไฟล์ .wav ในโฟลเดอร์ {audio_dir}")
    exit()

# ถ้า True จะข้ามไฟล์ที่มี report (.txt) อยู่แล้ว — ใช้รันเติมเฉพาะไฟล์ที่ยังไม่มี report
SKIP_IF_REPORT_EXISTS = True

report_dir = "report"
if not os.path.exists(report_dir):
    os.makedirs(report_dir)

report_file = os.path.join(report_dir, "summary_report.txt")
header = "ไฟล์เสียง\tจำนวนผู้พูด\tความยาว(s)\tเวลาที่ใช้ดำเนินการ\tความเร็วในการดำเนินการ\n"
# ถ้าข้ามไฟล์ที่มี report แล้ว ไม่เขียนทับ summary — เปิด append ตอนเขียนทีหลัง
if not SKIP_IF_REPORT_EXISTS or not os.path.exists(report_file):
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(header)

# นับสถิติ
num_processed = 0
num_skipped = 0
num_failed = 0

print(f"🔍 พบไฟล์เสียงทั้งหมด {len(audio_files)} ไฟล์ ในโฟลเดอร์ {audio_dir}")
if SKIP_IF_REPORT_EXISTS:
    print(f"   (ข้ามไฟล์ที่มี report แล้ว)\n")
else:
    print(f"   (ประมวลผลทุกไฟล์ใหม่)\n")

# วนลูปประมวลผลทุกไฟล์
for audio_filename in audio_files:
    audio_file = os.path.join(audio_dir, audio_filename)
    report_txt_path = os.path.join(report_dir, f"{os.path.splitext(audio_filename)[0]}.txt")
    if SKIP_IF_REPORT_EXISTS and os.path.exists(report_txt_path):
        print(f"⏭️ ข้าม (มี report แล้ว): {audio_filename}")
        num_skipped += 1
        continue

    print(f"\n{'='*80}")
    print(f"📂 กำลังประมวลผล: {audio_filename}")
    print(f"{'='*80}")

    try:
        waveform, sample_rate = torchaudio.load(audio_file)

        # แปลงเป็น 16kHz สำหรับ Typhoon (ถ้าจำเป็น)
        TARGET_SAMPLE_RATE = 16000
        if sample_rate != TARGET_SAMPLE_RATE:
            waveform = torchaudio.functional.resample(waveform, sample_rate, TARGET_SAMPLE_RATE)
            sample_rate = TARGET_SAMPLE_RATE

        audio_duration = waveform.shape[1] / sample_rate
        start_time_total = time.time()
        temp_dir = tempfile.gettempdir()

        # ประมวลผลทีละช่วง (ช่วงละ CHUNK_DURATION_SEC) เพื่อลด memory/GPU
        log_lines = []
        all_speaker_count = 0
        chunk_start = 0.0
        num_chunks = 0

        while chunk_start < audio_duration:
            chunk_end = min(chunk_start + CHUNK_DURATION_SEC, audio_duration)
            chunk_len_sec = chunk_end - chunk_start
            start_s = int(chunk_start * sample_rate)
            end_s = int(chunk_end * sample_rate)
            chunk_waveform = waveform[:, start_s:end_s].clone()
            num_chunks += 1
            print(f"   📌 ช่วงที่ {num_chunks}: {chunk_start/60:.1f}-{chunk_end/60:.1f} นาที ({chunk_len_sec:.1f}s)")

            audio_in_chunk = {"waveform": chunk_waveform, "sample_rate": sample_rate}

            # 5. แยกผู้พูดเฉพาะช่วงนี้ (ใช้ GPU น้อยลง)
            print("🎤 กำลังแยกผู้พูด...")
            diarization = pipeline(audio_in_chunk, min_speakers=1, max_speakers=5)
            ann = getattr(diarization, "speaker_diarization", diarization)
            n_speakers_chunk = len(ann.labels())
            speaker_offset = all_speaker_count
            all_speaker_count += n_speakers_chunk
            print(f"✅ แยกผู้พูดเสร็จ (พบ {n_speakers_chunk} ผู้พูดในช่วงนี้)")

            # 6. ถอดความแต่ละ turn ด้วย Typhoon (ใช้ GPU)
            print("📝 กำลังถอดความเสียงด้วย Typhoon Isan ASR...")
            print("-" * 40)
            turns = sorted(ann.itertracks(yield_label=True), key=lambda x: x[0].start)

            for turn, _, speaker in turns:
                local_start = turn.start
                local_end = turn.end
                duration = local_end - local_start
                if duration < 0.1:
                    continue

                global_start = chunk_start + local_start
                global_end = chunk_start + local_end

                try:
                    parts = speaker.split("_")
                    if len(parts) > 1:
                        speaker_id = int(parts[-1]) + 1 + speaker_offset
                    else:
                        import re
                        match = re.search(r"\d+", speaker)
                        speaker_id = (int(match.group()) + 1 + speaker_offset) if match else speaker
                    speaker_label = f"ผู้พูด {speaker_id}"
                except Exception:
                    speaker_label = speaker

                seg_start_s = int(local_start * sample_rate)
                seg_end_s = int(local_end * sample_rate)
                segment_waveform = chunk_waveform[:, seg_start_s:seg_end_s]
                seg_path = os.path.join(temp_dir, f"seg_{uuid.uuid4().hex}.wav")
                torchaudio.save(seg_path, segment_waveform, sample_rate)

                seg_text = ""
                try:
                    with suppress_stdout_stderr():
                        seg_hyp = asr_model.transcribe([seg_path])[0]
                    seg_text = seg_hyp.text if hasattr(seg_hyp, "text") else str(seg_hyp)
                    seg_text = (seg_text or "").strip()
                finally:
                    if os.path.exists(seg_path):
                        os.remove(seg_path)

                display_text = seg_text if seg_text else "(ไม่มีข้อความ)"
                log_line = f"[ {global_start:4.1f}s-{global_end:4.1f}s ] {speaker_label} : {display_text}"
                print(log_line)
                log_lines.append(log_line)

            chunk_start = chunk_end
            del chunk_waveform
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        num_speakers = all_speaker_count

        # คำนวณสรุปผล
        elapsed_time = time.time() - start_time_total
        rtf = audio_duration / elapsed_time if elapsed_time > 0 else 0
        summary_line = f"{audio_filename}\t{num_speakers}\t{audio_duration:.2f}\t{elapsed_time:.2f}\t{rtf:.2f}x"

        # 8. แสดงสรุปใน Terminal
        print("-" * 40)
        print(f"📊 สรุป: {audio_filename}")
        print(f"ผู้พูด: {num_speakers} | ยาว: {audio_duration:.2f}s | ใช้เวลา: {elapsed_time:.2f}s | RTF: {rtf:.2f}x")
        
        # 9. บันทึก Report (5 คอลัมน์: ไฟล์เสียง | จำนวนผู้พูด | ความยาว(s) | เวลาที่ใช้ดำเนินการ | ความเร็วในการดำเนินการ)
        summary_line_table = f"{audio_filename}\t{num_speakers}\t{audio_duration:.2f}\t{elapsed_time:.2f}\t{rtf:.2f}x"
        
        with open(report_file, "a", encoding="utf-8") as f:
            f.write(summary_line_table + "\n")

        # 10. บันทึก log แบบเดียวกับที่แสดงในเทอร์มินัล (หนึ่งบรรทัดต่อหนึ่งช่วง) — ไม่บันทึก .rttm แบบเก่าแล้ว
        log_path = os.path.join(report_dir, f"{os.path.splitext(audio_filename)[0]}.txt")
        with open(log_path, "w", encoding="utf-8") as logf:
            logf.write("\n".join(log_lines))
            if log_lines:
                logf.write("\n")

        num_processed += 1

    except Exception as e:
        num_failed += 1
        print(f"❌ เกิดข้อผิดพลาดกับไฟล์ {audio_filename}: {str(e)}")

print(f"\n{'='*80}")
print(f"✅ เสร็จสิ้น — ไฟล์ในโฟลเดอร์ sound: {len(audio_files)} ไฟล์")
print(f"   ประมวลผลใหม่: {num_processed} | ข้าม (มี report แล้ว): {num_skipped} | ผิดพลาด: {num_failed}")
print(f"   ตรวจสอบ Report ได้ที่: {report_file}")
print(f"{'='*80}")
