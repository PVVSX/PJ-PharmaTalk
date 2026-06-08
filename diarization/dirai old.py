import torch
import torchaudio
from speechbrain.pretrained import EncoderClassifier
from scipy.spatial.distance import cosine
import numpy as np
import os
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import tempfile
import argparse
import json
from datetime import datetime

# ===== CONFIG =====
SAMPLE_RATE = 16000
SEGMENT_DURATION = 1.5  # วินาทีต่อช่วง (ปรับได้ตามต้องการ)
MIN_SEGMENT_DURATION = 0.5  # ช่วงสั้นสุดที่ยอมรับได้ (วินาที)
NUM_SPEAKERS = 2  # จำนวนผู้พูดที่คาดหวัง (ปรับได้)
ENABLE_TRANSCRIPTION = True  # เปิด/ปิดการแปลงเสียงเป็นข้อความ

# ===== โหลดโมเดล ASR (ถ้ามี) =====
asr_model = None
asr_available = False

if ENABLE_TRANSCRIPTION:
    print("🔄 กำลังตรวจสอบ ASR Model...", flush=True)
    try:
        # ลองหาโมเดลจาก speech_to_text
        import sys
        speech_to_text_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "speech_to_text", "app", "backend")
        if os.path.exists(speech_to_text_path):
            sys.path.insert(0, speech_to_text_path)
            try:
                from models.asr_model import TyphoonASRRecognizer  # type: ignore
                from config import get_model_path  # type: ignore
                
                asr_model = TyphoonASRRecognizer()
                if asr_model.load_model():
                    asr_available = True
                    print("✅ โหลด ASR Model สำเร็จ\n", flush=True)
                else:
                    print("⚠️ ไม่สามารถโหลด ASR Model ได้ (จะข้ามการแปลงเสียงเป็นข้อความ)\n", flush=True)
            except (ImportError, ModuleNotFoundError):
                # ลองใช้ NeMo โดยตรง
                try:
                    import nemo.collections.asr as nemo_asr  # type: ignore
                    # ลองหาโมเดลในหลายที่
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    possible_paths = [
                        os.path.join(current_dir, "typhoon-asr-realtime", "typhoon-asr-realtime.nemo"),  # ในโฟลเดอร์ diarization
                        os.path.join(speech_to_text_path, "typhoon-asr-realtime", "typhoon-asr-realtime.nemo"),
                        "speech_to_text/app/backend/typhoon-asr-realtime/typhoon-asr-realtime.nemo",
                        "../speech_to_text/app/backend/typhoon-asr-realtime/typhoon-asr-realtime.nemo"
                    ]
                    model_path = None
                    for path in possible_paths:
                        if os.path.exists(path):
                            model_path = path
                            break
                    
                    if model_path:
                        asr_model = nemo_asr.models.ASRModel.restore_from(restore_path=model_path)
                        asr_model.eval()
                        asr_available = True
                        print(f"✅ โหลด ASR Model สำเร็จ (NeMo) จาก: {model_path}\n", flush=True)
                    else:
                        print("⚠️ ไม่พบไฟล์โมเดล ASR (จะข้ามการแปลงเสียงเป็นข้อความ)\n", flush=True)
                except ImportError:
                    print("⚠️ ไม่พบ NeMo Toolkit (จะข้ามการแปลงเสียงเป็นข้อความ)\n", flush=True)
        else:
            # ลองใช้ NeMo โดยตรง
            try:
                import nemo.collections.asr as nemo_asr  # type: ignore
                # ลองหาโมเดลในหลายที่
                current_dir = os.path.dirname(os.path.abspath(__file__))
                possible_paths = [
                    os.path.join(current_dir, "typhoon-asr-realtime", "typhoon-asr-realtime.nemo"),  # ในโฟลเดอร์ diarization
                    "speech_to_text/app/backend/typhoon-asr-realtime/typhoon-asr-realtime.nemo",
                    "../speech_to_text/app/backend/typhoon-asr-realtime/typhoon-asr-realtime.nemo"
                ]
                model_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        model_path = path
                        break
                
                if model_path:
                    asr_model = nemo_asr.models.ASRModel.restore_from(restore_path=model_path)
                    asr_model.eval()
                    asr_available = True
                    print(f"✅ โหลด ASR Model สำเร็จ (NeMo) จาก: {model_path}\n", flush=True)
                else:
                    print("⚠️ ไม่พบไฟล์โมเดล ASR (จะข้ามการแปลงเสียงเป็นข้อความ)\n", flush=True)
            except ImportError:
                print("⚠️ ไม่พบ NeMo Toolkit (จะข้ามการแปลงเสียงเป็นข้อความ)\n", flush=True)
    except Exception as e:
        print(f"⚠️ ไม่สามารถโหลด ASR Model: {e} (จะข้ามการแปลงเสียงเป็นข้อความ)\n", flush=True)
else:
    print("ℹ️ การแปลงเสียงเป็นข้อความถูกปิดใช้งาน\n", flush=True)

# โหลดโมเดล Speaker Diarization
print("🔄 กำลังโหลดโมเดล SpeechBrain...", flush=True)
model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")
print("✅ โหลดโมเดลสำเร็จ\n", flush=True)

def save_segment_to_temp_file(segment, sample_rate=SAMPLE_RATE):
    """บันทึก segment เป็นไฟล์ชั่วคราว"""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
    temp_path = temp_file.name
    temp_file.close()
    
    # แปลงเป็น mono ถ้ายังไม่ใช่
    if segment.dim() == 1:
        segment = segment.unsqueeze(0)
    elif segment.shape[0] > 1:
        segment = segment.mean(dim=0, keepdim=True)
    
    torchaudio.save(temp_path, segment, sample_rate)
    return temp_path

def transcribe_segment(segment):
    """แปลงเสียง segment เป็นข้อความ"""
    if not asr_available or asr_model is None:
        return None
    
    try:
        # บันทึก segment เป็นไฟล์ชั่วคราว
        temp_path = save_segment_to_temp_file(segment)
        
        # แปลงเสียงเป็นข้อความ
        if hasattr(asr_model, 'transcribe'):
            # NeMo model
            result = asr_model.transcribe([temp_path])
            if isinstance(result, list) and len(result) > 0:
                text = result[0]
                if hasattr(text, 'text'):
                    text = text.text
                elif hasattr(text, 'transcript'):
                    text = text.transcript
                text = str(text).strip()
            else:
                text = str(result).strip()
        elif hasattr(asr_model, 'transcribe_audio'):
            # TyphoonASRRecognizer
            text = asr_model.transcribe_audio(temp_path)
        else:
            text = None
        
        # ลบไฟล์ชั่วคราว
        try:
            os.unlink(temp_path)
        except:
            pass
        
        return text if text and text != "โมเดลยังไม่ได้โหลด" else None
        
    except Exception as e:
        # ลบไฟล์ชั่วคราวถ้ามี
        try:
            if 'temp_path' in locals():
                os.unlink(temp_path)
        except:
            pass
        return None

def get_embedding(signal):
    """สร้าง embedding จาก signal tensor"""
    if signal.dim() == 1:
        signal = signal.unsqueeze(0)
    embeddings = model.encode_batch(signal)
    return embeddings.squeeze().detach().cpu().numpy()

def get_embedding_from_file(file_path):
    """โหลดไฟล์และสร้าง embedding"""
    signal, fs = torchaudio.load(file_path)
    if fs != SAMPLE_RATE:
        signal = torchaudio.functional.resample(signal, fs, SAMPLE_RATE)
    return get_embedding(signal)

def split_audio_into_segments(file_path, segment_duration=SEGMENT_DURATION):
    """แบ่งไฟล์เสียงเป็นช่วงๆ (ไม่กรองด้วย VAD)"""
    signal, fs = torchaudio.load(file_path)
    if fs != SAMPLE_RATE:
        signal = torchaudio.functional.resample(signal, fs, SAMPLE_RATE)
    
    # แปลงเป็น mono ถ้ายังไม่ใช่
    if signal.shape[0] > 1:
        signal = signal.mean(dim=0, keepdim=True)
    
    segment_samples = int(SAMPLE_RATE * segment_duration)
    segments = []
    timestamps = []
    
    for start_idx in range(0, signal.shape[-1], segment_samples):
        end_idx = min(start_idx + segment_samples, signal.shape[-1])
        segment = signal[:, start_idx:end_idx]
        
        # ข้ามช่วงที่สั้นเกินไป
        if segment.shape[-1] < SAMPLE_RATE * MIN_SEGMENT_DURATION:
            continue
            
        segments.append(segment)
        timestamps.append((start_idx / SAMPLE_RATE, end_idx / SAMPLE_RATE))
    
    return segments, timestamps

def analyze_single_file_unsupervised(audio_file, num_speakers=NUM_SPEAKERS):
    """วิเคราะห์ไฟล์เสียงโดยแยกผู้พูดอัตโนมัติ (ไม่ต้องใช้โปรไฟล์อ้างอิง)"""
    
    # แบ่งไฟล์เป็นช่วงๆ
    print(f"\n📂 กำลังวิเคราะห์ไฟล์: {audio_file}", flush=True)
    segments, timestamps = split_audio_into_segments(audio_file)
    print(f"✅ แบ่งเป็น {len(segments)} ช่วง\n", flush=True)
    
    if len(segments) == 0:
        print("⚠️ ไม่พบช่วงที่มีเสียงพูดในไฟล์นี้", flush=True)
        return []
    
    # สร้าง embeddings สำหรับทุกช่วง
    print("🔄 กำลังสร้าง embeddings...", flush=True)
    embeddings = []
    for i, segment in enumerate(segments):
        emb = get_embedding(segment)
        embeddings.append(emb)
        if (i + 1) % 10 == 0:
            print(f"   ประมวลผลแล้ว {i+1}/{len(segments)} ช่วง", flush=True)
    
    embeddings = np.array(embeddings)
    print(f"✅ สร้าง embeddings สำเร็จ\n", flush=True)
    
    # ใช้ KMeans clustering เพื่อแยกผู้พูด
    print(f"🎯 กำลังแยกผู้พูดด้วย KMeans (k={num_speakers})...", flush=True)
    
    # ปรับขนาดข้อมูลก่อน clustering
    scaler = StandardScaler()
    embeddings_scaled = scaler.fit_transform(embeddings)
    
    # Clustering
    kmeans = KMeans(n_clusters=num_speakers, random_state=42, n_init=10)
    speaker_labels = kmeans.fit_predict(embeddings_scaled)
    
    print(f"✅ แยกผู้พูดสำเร็จ\n", flush=True)
    
    # สร้างผลลัพธ์และแปลงเสียงเป็นข้อความ
    results = []
    speaker_names = [f"ผู้พูด {i+1}" for i in range(num_speakers)]
    
    if asr_available:
        print("📝 กำลังแปลงเสียงเป็นข้อความ...", flush=True)
    
    for i, ((start_time, end_time), label, segment) in enumerate(zip(timestamps, speaker_labels, segments)):
        speaker = speaker_names[label]
        
        # แปลงเสียงเป็นข้อความ (ถ้าเปิดใช้งาน)
        text = None
        if asr_available:
            text = transcribe_segment(segment)
            if (i + 1) % 5 == 0:
                print(f"   แปลงเสียงแล้ว {i+1}/{len(segments)} ช่วง", flush=True)
        
        results.append({
            'segment': i + 1,
            'start': start_time,
            'end': end_time,
            'speaker': speaker,
            'speaker_id': label,
            'text': text
        })
        
        # แสดงผลลัพธ์
        if text:
            print(f"[{start_time:05.1f}s - {end_time:05.1f}s] {speaker}: \"{text}\"", flush=True)
        else:
            print(f"[{start_time:05.1f}s - {end_time:05.1f}s] {speaker}", flush=True)
    
    if asr_available:
        print(f"✅ แปลงเสียงเป็นข้อความสำเร็จ\n", flush=True)
    
    # สรุปผล
    print(f"\n📊 สรุปผล:", flush=True)
    for i in range(num_speakers):
        count = sum(1 for r in results if r['speaker_id'] == i)
        text_count = sum(1 for r in results if r['speaker_id'] == i and r['text'])
        print(f"   {speaker_names[i]}: {count} ช่วง (มีข้อความ: {text_count} ช่วง)", flush=True)
    
    return results

def analyze_single_file_with_profile(audio_file, pharmacist_profile):
    """วิเคราะห์ไฟล์เสียงโดยใช้โปรไฟล์อ้างอิง (แบบเดิม)"""
    
    # โหลดโปรไฟล์เภสัชกร
    if os.path.exists(pharmacist_profile):
        pharmacist_emb = np.load(pharmacist_profile)
        print(f"✅ โหลดโปรไฟล์เภสัชกรจาก {pharmacist_profile}", flush=True)
    else:
        print("⚠️ ไม่พบโปรไฟล์เภสัชกร", flush=True)
        return []
    
    # แบ่งไฟล์เป็นช่วงๆ
    print(f"\n📂 กำลังวิเคราะห์ไฟล์: {audio_file}", flush=True)
    segments, timestamps = split_audio_into_segments(audio_file)
    print(f"✅ แบ่งเป็น {len(segments)} ช่วง\n", flush=True)
    
    if asr_available:
        print("📝 กำลังแปลงเสียงเป็นข้อความ...", flush=True)
    
    results = []
    for i, (segment, (start_time, end_time)) in enumerate(zip(segments, timestamps)):
        emb = get_embedding(segment)
        similarity = 1 - cosine(emb, pharmacist_emb)
        
        if similarity > 0.30:  # threshold
            speaker = "เภสัชกร 💊"
        else:
            speaker = "ผู้ป่วย/ลูกค้า 🧍"
        
        # แปลงเสียงเป็นข้อความ (ถ้าเปิดใช้งาน)
        text = None
        if asr_available:
            text = transcribe_segment(segment)
            if (i + 1) % 5 == 0:
                print(f"   แปลงเสียงแล้ว {i+1}/{len(segments)} ช่วง", flush=True)
        
        results.append({
            'segment': i + 1,
            'start': start_time,
            'end': end_time,
            'speaker': speaker,
            'similarity': similarity,
            'text': text
        })
        
        # แสดงผลลัพธ์
        if text:
            print(f"[{start_time:05.1f}s - {end_time:05.1f}s] {speaker} (similarity={similarity:.3f}): \"{text}\"", flush=True)
        else:
            print(f"[{start_time:05.1f}s - {end_time:05.1f}s] {speaker} (similarity={similarity:.3f})", flush=True)
    
    if asr_available:
        print(f"✅ แปลงเสียงเป็นข้อความสำเร็จ\n", flush=True)
    
    # สรุปผล
    pharmacist_count = sum(1 for r in results if "เภสัชกร" in r['speaker'])
    patient_count = sum(1 for r in results if "ผู้ป่วย" in r['speaker'] or "ลูกค้า" in r['speaker'])
    pharmacist_text_count = sum(1 for r in results if "เภสัชกร" in r['speaker'] and r['text'])
    patient_text_count = sum(1 for r in results if ("ผู้ป่วย" in r['speaker'] or "ลูกค้า" in r['speaker']) and r['text'])
    
    print(f"\n📊 สรุปผล:", flush=True)
    print(f"   เภสัชกร: {pharmacist_count} ช่วง (มีข้อความ: {pharmacist_text_count} ช่วง)", flush=True)
    print(f"   ผู้ป่วย/ลูกค้า: {patient_count} ช่วง (มีข้อความ: {patient_text_count} ช่วง)", flush=True)
    
    return results

def print_speaker_transcripts(results):
    """แสดงผลลัพธ์แบบสรุปตามผู้พูด"""
    if not results:
        return
    
    print("\n" + "="*60, flush=True)
    print("📋 สรุปข้อความตามผู้พูด:", flush=True)
    print("="*60, flush=True)
    
    # รวบรวมผลลัพธ์ที่มีข้อความและเรียงตามเวลา
    transcripts = []
    for r in results:
        if r.get('text'):
            transcripts.append({
                'start': r['start'],
                'end': r['end'],
                'speaker': r['speaker'],
                'text': r['text']
            })
    
    # เรียงตามเวลาเริ่มต้น
    transcripts.sort(key=lambda x: x['start'])
    
    # แสดงผลในรูปแบบ: [ เวลา ] ผู้พูด : เนื้อหา
    if transcripts:
        for item in transcripts:
            time_str = f"{item['start']:.1f}s-{item['end']:.1f}s"
            print(f"[ {time_str} ] {item['speaker']} : {item['text']}", flush=True)
    else:
        print("(ไม่มีข้อความ)", flush=True)
    
    print("\n" + "="*60 + "\n", flush=True)

def convert_to_json_serializable(obj):
    """แปลง numpy types และ types อื่นๆ ให้เป็น JSON serializable"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_to_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_json_serializable(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_to_json_serializable(item) for item in obj)
    else:
        return obj

def save_results_to_file(results, audio_file, output_file=None):
    """บันทึกผลลัพธ์เป็นไฟล์ JSON และ TXT"""
    if not results:
        print("⚠️ ไม่มีผลลัพธ์ให้บันทึก", flush=True)
        return None
    
    # สร้างชื่อไฟล์อัตโนมัติถ้าไม่ได้ระบุ
    if output_file is None:
        base_name = os.path.splitext(os.path.basename(audio_file))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"{base_name}_diarization_{timestamp}"
    
    # แปลง results ให้เป็น JSON serializable
    json_results = convert_to_json_serializable(results)
    
    # บันทึกเป็น JSON
    json_file = f"{output_file}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_results, f, ensure_ascii=False, indent=2)
    print(f"💾 บันทึกผลลัพธ์เป็น JSON: {json_file}", flush=True)
    
    # บันทึกเป็น TXT (อ่านง่าย)
    txt_file = f"{output_file}.txt"
    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write("="*60 + "\n")
        f.write(f"ผลการแยกผู้พูด: {os.path.basename(audio_file)}\n")
        f.write(f"วันที่: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*60 + "\n\n")
        
        # รวบรวมผลลัพธ์ที่มีข้อความและเรียงตามเวลา
        transcripts = []
        for r in results:
            if r.get('text'):
                transcripts.append({
                    'start': r['start'],
                    'end': r['end'],
                    'speaker': r['speaker'],
                    'text': r['text']
                })
        
        # เรียงตามเวลาเริ่มต้น
        transcripts.sort(key=lambda x: x['start'])
        
        # เขียนผลลัพธ์ในรูปแบบ: [ เวลา ] ผู้พูด : เนื้อหา
        if transcripts:
            for item in transcripts:
                time_str = f"{item['start']:.1f}s-{item['end']:.1f}s"
                f.write(f"[ {time_str} ] {item['speaker']} : {item['text']}\n")
        else:
            f.write("(ไม่มีข้อความ)\n")
    
    print(f"💾 บันทึกผลลัพธ์เป็น TXT: {txt_file}", flush=True)
    
    return output_file

def analyze_audio_file(audio_file, num_speakers=None, use_profile=False, pharmacist_profile=None, save_output=True):
    """
    ฟังก์ชันง่ายๆ สำหรับวิเคราะห์ไฟล์เสียง
    
    Args:
        audio_file: path ไปยังไฟล์เสียง
        num_speakers: จำนวนผู้พูด (ถ้า None จะใช้ค่าเริ่มต้น)
        use_profile: ใช้โปรไฟล์อ้างอิงหรือไม่
        pharmacist_profile: path ไปยังไฟล์โปรไฟล์เภสัชกร (.npy)
        save_output: บันทึกผลลัพธ์เป็นไฟล์หรือไม่
    
    Returns:
        list: ผลลัพธ์การวิเคราะห์
    """
    # ตรวจสอบไฟล์
    if not os.path.exists(audio_file):
        print(f"❌ ไม่พบไฟล์: {audio_file}", flush=True)
        return []
    
    # วิเคราะห์
    if use_profile:
        if pharmacist_profile is None:
            pharmacist_profile = "pharmacist.npy"
        if os.path.exists(pharmacist_profile):
            results = analyze_single_file_with_profile(audio_file, pharmacist_profile)
        else:
            print("⚠️ ไม่พบโปรไฟล์ เปลี่ยนเป็นโหมด unsupervised", flush=True)
            num_speakers = num_speakers or NUM_SPEAKERS
            results = analyze_single_file_unsupervised(audio_file, num_speakers=num_speakers)
    else:
        num_speakers = num_speakers or NUM_SPEAKERS
        results = analyze_single_file_unsupervised(audio_file, num_speakers=num_speakers)
    
    # แสดงสรุป
    if results:
        print_speaker_transcripts(results)
        
        # บันทึกผลลัพธ์
        if save_output:
            save_results_to_file(results, audio_file)
    
    return results

# ===== ใช้งาน =====
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ระบบแยกผู้พูดและแปลงเสียงเป็นข้อความ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ตัวอย่างการใช้งาน:
  # โหมด unsupervised (แยกผู้พูดอัตโนมัติ)
  python SpeakerDiarization.py sound/multi_speaker.wav
  
  # ระบุจำนวนผู้พูด
  python SpeakerDiarization.py sound/multi_speaker.wav --num-speakers 3
  
  # ใช้โปรไฟล์อ้างอิง
  python SpeakerDiarization.py sound/multi_speaker.wav --use-profile --profile pharmacist.npy
  
  # ไม่บันทึกผลลัพธ์
  python SpeakerDiarization.py sound/multi_speaker.wav --no-save
        """
    )
    
    parser.add_argument(
        "audio_file",
        nargs="?",
        default=None,
        help="Path ไปยังไฟล์เสียงที่ต้องการวิเคราะห์ (ถ้าไม่ระบุจะใช้ค่าเริ่มต้น)"
    )
    
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help=f"จำนวนผู้พูดที่คาดหวัง (ค่าเริ่มต้น: {NUM_SPEAKERS})"
    )
    
    parser.add_argument(
        "--use-profile",
        action="store_true",
        help="ใช้โปรไฟล์อ้างอิงสำหรับระบุตัวตนผู้พูด"
    )
    
    parser.add_argument(
        "--profile",
        type=str,
        default="pharmacist.npy",
        help="Path ไปยังไฟล์โปรไฟล์ (.npy) - ใช้กับ --use-profile"
    )
    
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="ไม่บันทึกผลลัพธ์เป็นไฟล์"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="ชื่อไฟล์ผลลัพธ์ (ไม่ต้องใส่ extension)"
    )
    
    args = parser.parse_args()
    
    # ตรวจสอบ audio_file
    if args.audio_file is None:
        # ใช้ค่าเริ่มต้น: diarization/sound/multi_speaker.wav
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_audio = os.path.join(current_dir, "sound", "multi_speaker.wav")
        
        if os.path.exists(default_audio):
            print(f"ℹ️  ไม่ได้ระบุไฟล์เสียง ใช้ค่าเริ่มต้น: {default_audio}\n", flush=True)
            args.audio_file = default_audio
        else:
            # ลองหาไฟล์เสียงในโฟลเดอร์ sound
            sound_dir = os.path.join(current_dir, "sound")
            if os.path.exists(sound_dir):
                wav_files = [f for f in os.listdir(sound_dir) if f.endswith(('.wav', '.mp3', '.m4a'))]
                if wav_files:
                    # ลองหา multi_speaker.wav ก่อน
                    if "multi_speaker.wav" in wav_files:
                        default_audio = os.path.join(sound_dir, "multi_speaker.wav")
                    else:
                        default_audio = os.path.join(sound_dir, wav_files[0])
                    print(f"ℹ️  ไม่ได้ระบุไฟล์เสียง ใช้ไฟล์: {default_audio}\n", flush=True)
                    args.audio_file = default_audio
                else:
                    parser.print_help()
                    print(f"\n❌ ไม่พบไฟล์เสียงในโฟลเดอร์: {sound_dir}", flush=True)
                    print("กรุณาระบุไฟล์เสียงที่ต้องการวิเคราะห์", flush=True)
                    exit(1)
            else:
                parser.print_help()
                print(f"\n❌ ไม่พบโฟลเดอร์ sound ใน: {current_dir}", flush=True)
                print("กรุณาระบุไฟล์เสียงที่ต้องการวิเคราะห์", flush=True)
                exit(1)
    
    # ตรวจสอบว่าไฟล์มีอยู่จริง
    if not os.path.exists(args.audio_file):
        print(f"❌ ไม่พบไฟล์: {args.audio_file}", flush=True)
        exit(1)
    
    # วิเคราะห์ไฟล์
    results = analyze_audio_file(
        audio_file=args.audio_file,
        num_speakers=args.num_speakers,
        use_profile=args.use_profile,
        pharmacist_profile=args.profile if args.use_profile else None,
        save_output=not args.no_save
    )
    
    if args.output and results:
        save_results_to_file(results, args.audio_file, args.output)

