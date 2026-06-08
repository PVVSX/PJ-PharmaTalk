import os
import torch
import torchaudio
import numpy as np
from speechbrain.pretrained import EncoderClassifier
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

# 1. ดึงไฟล์จาก path ที่ระบุ 
AUDIO_PATH = "diarization/sound/multi_speaker.wav"
NUM_SPEAKERS = 2
SAMPLE_RATE = 16000

print("🔄 กำลังเตรียมโมเดลและประมวลผล...")
encoder = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")
vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad')
(get_speech_timestamps, _, read_audio, _, _) = utils

def run_diarization_system(path):
    # ดึงไฟล์เสียง
    wav = read_audio(path, sampling_rate=SAMPLE_RATE)
    signal, fs = torchaudio.load(path)
    if fs != SAMPLE_RATE:
        signal = torchaudio.functional.resample(signal, fs, SAMPLE_RATE)

    # 2. แบ่งช่วง (Segmentation) - ใช้ VAD ตัดตามจังหวะหยุดหายใจ
    speech_timestamps = get_speech_timestamps(wav, vad_model, sampling_rate=SAMPLE_RATE, threshold=0.5)
    
    embeddings = []
    metadata = []

    # ซอยย่อย Segment ที่ยาวเกินไปเพื่อหาจุดสลับคนพูด
    for ts in speech_timestamps:
        start_samp = ts['start']
        end_samp = ts['end']
        duration = (end_samp - start_samp) / SAMPLE_RATE
        
        # หากช่วงยาวกว่า 1.5 วินาที ให้แบ่งเป็นหน้าต่างเล็กๆ เพื่อความละเอียด
        window_size = int(1.5 * SAMPLE_RATE)
        for start in range(start_samp, end_samp, window_size):
            end = min(start + window_size, end_samp)
            if (end - start) > (0.5 * SAMPLE_RATE):
                seg = signal[:, start:end]
                emb = encoder.encode_batch(seg).squeeze().detach().cpu().numpy()
                embeddings.append(emb)
                metadata.append({'start': start/SAMPLE_RATE, 'end': end/SAMPLE_RATE})

    # 3. Label ผู้พูด (Clustering)
    X = np.array(embeddings)
    X = normalize(X) # L2 Normalization เพื่อให้แยกแยะ Vector เสียงได้ชัดเจนขึ้น
    
    # บังคับให้แยกเป็น 2 กลุ่มด้วย linkage='complete' เพื่อหาความต่างที่ชัดที่สุด
    cluster = AgglomerativeClustering(n_clusters=NUM_SPEAKERS, metric='cosine', linkage='complete')
    labels = cluster.fit_predict(X)

    # 4. เรียบเรียง (Merging Adjacent Segments)
    final_results = []
    if len(labels) > 0:
        current_spk = labels[0]
        start_time = metadata[0]['start']
        
        for i in range(1, len(labels)):
            # รวมช่วงเวลาถ้าเป็นคนเดิมพูดต่อกัน
            if labels[i] != current_spk:
                final_results.append({
                    'speaker': f"ผู้พูด {current_spk + 1}",
                    'start': start_time,
                    'end': metadata[i-1]['end']
                })
                current_spk = labels[i]
                start_time = metadata[i]['start']
        
        final_results.append({'speaker': f"ผู้พูด {current_spk + 1}", 'start': start_time, 'end': metadata[-1]['end']})
    
    return final_results

# แสดงผลลัพธ์
if os.path.exists(AUDIO_PATH):
    results = run_diarization_system(AUDIO_PATH)
    print("\n" + "="*50)
    print(f"📋 รายงานการแยกผู้พูด (Final Version): {os.path.basename(AUDIO_PATH)}")
    print("="*50)
    for r in results:
        print(f"[{r['start']:6.2f}s - {r['end']:6.2f}s] {r['speaker']}")
else:
    print("❌ ไม่พบไฟล์ใน Path ที่ระบุ")