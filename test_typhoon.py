import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes, ASR_AVAILABLE

def run_typhoon_batch():
    print(f"ASR_AVAILABLE from stt_typhoon: {ASR_AVAILABLE}")
    print("Initializing Typhoon ASR Model...")
    
    recognizer = TyphoonASRRecognizer()
    if hasattr(recognizer, "load_model"):
        recognizer.load_model()
        
    audio_dirs = [
        ROOT.parent / "Project_record" / "Demo" / "record",
        ROOT.parent / "Project_record" / "october" / "Week 1"
    ]
    all_wavs = []
    for d in audio_dirs:
        if d.exists():
            all_wavs.extend(list(d.glob("*.wav")))
            
    # Sort to run smallest files first
    all_wavs.sort(key=lambda p: p.stat().st_size)
    
    # We will only process the first 3 valid files to save time, because CPU inference is slow.
    test_wavs = [w for w in all_wavs if w.stat().st_size > 100000][:3]
    
    print(f"Testing {len(test_wavs)} WAV files with Typhoon...")
    
    results = {}
    for i, wav_path in enumerate(test_wavs):
        size_mb = wav_path.stat().st_size / 1024 / 1024
        print(f"[{i+1}/{len(test_wavs)}] Typhoon STT on {wav_path.name} ({size_mb:.1f} MB)...", flush=True)
        try:
            with open(wav_path, "rb") as f:
                audio_bytes = f.read()
            transcript = transcribe_audio_bytes(recognizer, audio_bytes)
            results[wav_path.name] = {"status": "success", "size_mb": size_mb, "transcript": transcript}
        except Exception as e:
            results[wav_path.name] = {"status": "error", "size_mb": size_mb, "error": str(e)}
            
        with open("batch_typhoon_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    run_typhoon_batch()
