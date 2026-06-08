import os
import torch
import torchaudio
import numpy as np
import tempfile
import uuid
from speechbrain.pretrained import EncoderClassifier
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize
import nemo.collections.asr as nemo_asr

# ===== CONFIGURATION =====
# 1. ดึงไฟล์จาก path ที่ระบุ
AUDIO_PATH = "diarization/sound/multi_speaker.wav"
MODEL_PATH = "diarization/model/typhoon-isan-asr-realtime.nemo" 
NUM_SPEAKERS = 2 # จำนวนผู้พูดที่ระบุ
SAMPLE_RATE = 16000

# พารามิเตอร์การแบ่งช่วง
WINDOW_SIZE = 1.5 # ขนาดหน้าต่างเวลา
VAD_THRESHOLD = 0.5 # ความไวในการตรวจจับเสียงพูด

print("🔄 กำลังโหลดโมเดลและเตรียมระบบ...")

# โหลดโมเดล Diarization (SpeechBrain)
encoder = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")
vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad')
(get_speech_timestamps, _, read_audio, _, _) = utils

# โหลดโมเดล Typhoon Isan ASR
if os.path.exists(MODEL_PATH):
    asr_model = nemo_asr.models.ASRModel.restore_from(restore_path=MODEL_PATH)
    asr_model.eval()
else:
    print(f"❌ ไม่พบไฟล์โมเดลที่ {MODEL_PATH}")
    exit()

def process_complete_system(audio_path):
    # --- ขั้นตอนที่ 1 & 2: ดึงไฟล์และแบ่งช่วง (Segmentation) ---
    wav = read_audio(audio_path, sampling_rate=SAMPLE_RATE)
    signal, fs = torchaudio.load(audio_path)
    if fs != SAMPLE_RATE:
        signal = torchaudio.functional.resample(signal, fs, SAMPLE_RATE)

    # ตรวจหาช่วงเวลาที่มีการพูดจริง (VAD)
    speech_timestamps = get_speech_timestamps(wav, vad_model, sampling_rate=SAMPLE_RATE, threshold=VAD_THRESHOLD)
    
    embeddings = []
    metadata = []

    for ts in speech_timestamps:
        start_samp = ts['start']
        end_samp = ts['end']
        
        # ซอยย่อยช่วงเวลาเพื่อความละเอียดในการระบุตัวตน
        window_samples = int(WINDOW_SIZE * SAMPLE_RATE)
        for start in range(start_samp, end_samp, window_samples):
            end = min(start + window_samples, end_samp)
            if (end - start) > (0.5 * SAMPLE_RATE):
                seg = signal[:, start:end]
                # สร้างเอกลักษณ์เสียง (Embedding)
                emb = encoder.encode_batch(seg).squeeze().detach().cpu().numpy()
                embeddings.append(emb)
                metadata.append({'start': start/SAMPLE_RATE, 'end': end/SAMPLE_RATE, 'tensor': seg})

    # --- ขั้นตอนที่ 3: Label ผู้พูด (Clustering) ---
    X = normalize(np.array(embeddings))
    # ใช้ค่า Cosine ในการแยกแยะผู้พูด 2 ท่าน
    cluster = AgglomerativeClustering(n_clusters=NUM_SPEAKERS, metric='cosine', linkage='complete')
    labels = cluster.fit_predict(X)

    # --- ขั้นตอนที่ 4: เรียบเรียงและถอดความ (Transcription) ---
    print("📝 กำลังถอดความเสียงด้วย Typhoon Isan ASR...")
    
    # รวมช่วงที่เป็นคนเดียวกันพูดต่อเนื่อง
    merged_segments = []
    if len(labels) > 0:
        curr_spk = labels[0]
        curr_start = metadata[0]['start']
        curr_tensors = [metadata[0]['tensor']]
        
        for i in range(1, len(labels)):
            # รวมถ้าระยะห่างไม่เกิน 0.8 วินาที และเป็นคนเดิม
            if labels[i] == curr_spk and (metadata[i]['start'] - metadata[i-1]['end'] < 0.8):
                curr_tensors.append(metadata[i]['tensor'])
            else:
                merged_audio = torch.cat(curr_tensors, dim=1)
                merged_segments.append({'speaker': curr_spk, 'start': curr_start, 'end': metadata[i-1]['end'], 'audio': merged_audio})
                curr_spk = labels[i]
                curr_start = metadata[i]['start']
                curr_tensors = [metadata[i]['tensor']]
        
        merged_audio = torch.cat(curr_tensors, dim=1)
        merged_segments.append({'speaker': curr_spk, 'start': curr_start, 'end': metadata[-1]['end'], 'audio': merged_audio})

    # ถอดความรายก้อน (ดึงเฉพาะส่วน text)
    final_output = []
    temp_dir = tempfile.gettempdir()
    
    for seg in merged_segments:
        unique_id = str(uuid.uuid4())[:8]
        temp_filename = os.path.join(temp_dir, f"segment_{unique_id}.wav")
        
        try:
            torchaudio.save(temp_filename, seg['audio'], SAMPLE_RATE)
            # เรียกใช้ ASR และดึงเฉพาะข้อความ
            hypothesis = asr_model.transcribe([temp_filename])[0]
            
            # ตรวจสอบว่าเป็น Object หรือ String และดึงเฉพาะ text
            if hasattr(hypothesis, 'text'):
                clean_text = hypothesis.text
            else:
                clean_text = str(hypothesis)
            
            final_output.append({
                'time': f"[{seg['start']:6.2f}s - {seg['end']:6.2f}s]",
                'speaker': f"ผู้พูด {seg['speaker'] + 1}",
                'text': clean_text
            })
        finally:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
    
    return final_output

# --- แสดงผลลัพธ์ ---
if os.path.exists(AUDIO_PATH):
    results = process_complete_system(AUDIO_PATH)
    print("\n" + "="*75)
    print(f"📋 สรุปผลการแยกผู้พูดและถอดความ: {os.path.basename(AUDIO_PATH)}")
    print("="*75)
    for r in results:
        # แสดงผลในรูปแบบที่สะอาดตา
        print(f"{r['time']} {r['speaker']} : \"{r['text']}\"")
else:
    print(f"❌ ไม่พบไฟล์เสียงที่ {AUDIO_PATH}")