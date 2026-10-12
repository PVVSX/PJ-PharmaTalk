import os
import sys
import json
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Patch Groq client model temporarily for testing if it's using invalid models
from unified_app.modules.stt_deepgram import transcribe_audio_deepgram
from unified_app.modules.emr_groq import extract_emr

def test_stt():
    wav_path = ROOT.parent / "Project_record" / "Demo" / "record" / "recording_2025-10-09_13-40-00.wav"
    if not wav_path.exists():
        return "Audio file not found."
    
    print(f"Testing STT on {wav_path.name}...")
    try:
        transcript = transcribe_audio_deepgram(str(wav_path))
        return transcript
    except Exception as e:
        return f"Error: {e}"

def test_emr():
    sample_text = (
        "[Speaker 0]: สวัสดีครับ วันนี้เป็นอะไรมาครับ\n"
        "[Speaker 1]: ปวดหัว ตัวร้อน มีไข้สูงครับ\n"
        "[Speaker 0]: มีโรคประจำตัวไหมครับ\n"
        "[Speaker 1]: เป็นความดันครับ\n"
        "[Speaker 0]: มีประวัติแพ้ยาไหม\n"
        "[Speaker 1]: แพ้ยาพาราเซตามอลครับ\n"
        "[Speaker 0]: โอเคครับ เดี๋ยวหมอจัดยาไอบูโพรเฟนให้นะครับ ทานหลังอาหารทันทีนะ"
    )
    print("Testing EMR Extraction...")
    try:
        emr_data = extract_emr(sample_text)
        return sample_text, emr_data
    except Exception as e:
        return sample_text, f"Error: {e}"

if __name__ == "__main__":
    stt_res = test_stt()
    emr_in, emr_out = test_emr()
    
    print("\n=== STT RESULT ===")
    print(stt_res)
    print("\n=== EMR RESULT ===")
    print("INPUT:")
    print(emr_in)
    print("OUTPUT:")
    if isinstance(emr_out, dict):
        print(json.dumps(emr_out, ensure_ascii=False, indent=2))
    else:
        print(emr_out)
