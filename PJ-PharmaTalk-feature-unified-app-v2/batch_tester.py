import os
import sys
import json
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.stt_deepgram import transcribe_audio_deepgram
from unified_app.modules.emr_groq import extract_emr

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
    print("Warning: pypdf not installed.")

def process_audio_files():
    audio_dirs = [
        ROOT.parent / "Project_record" / "Demo" / "record",
        ROOT.parent / "Project_record" / "october" / "Week 1"
    ]
    all_wavs = []
    for d in audio_dirs:
        if d.exists():
            all_wavs.extend(list(d.glob("*.wav")))
    
    print(f"Found {len(all_wavs)} WAV files. Starting STT Batch Processing...")
    results = {}
    
    # Initialize Typhoon
    from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes
    from unified_app.modules.stt_groq import transcribe_audio_groq
    
    print("Loading Typhoon ASR Model...")
    recognizer = TyphoonASRRecognizer()
    recognizer.load_model()
    
    # Process files (Start with smaller files first for quicker feedback)
    all_wavs.sort(key=lambda p: p.stat().st_size)
    
    for i, wav_path in enumerate(all_wavs):
        size_mb = wav_path.stat().st_size / 1024 / 1024
        print(f"[{i+1}/{len(all_wavs)}] STT on {wav_path.name} ({size_mb:.1f} MB)...", flush=True)
        
        with open(wav_path, "rb") as f:
            audio_bytes = f.read()
            
        try:
            # Test Groq
            start_g = time.time()
            groq_text = transcribe_audio_groq(audio_bytes)
            time_g = time.time() - start_g
            
            # Test Typhoon
            start_t = time.time()
            typhoon_text = transcribe_audio_bytes(recognizer, audio_bytes)
            time_t = time.time() - start_t
            
            results[wav_path.name] = {
                "status": "success",
                "size_mb": size_mb,
                "groq_transcript": groq_text,
                "groq_time_sec": time_g,
                "typhoon_transcript": typhoon_text,
                "typhoon_time_sec": time_t
            }
        except Exception as e:
            results[wav_path.name] = {"status": "error", "size_mb": size_mb, "error": str(e)}
        
        # Save progress continually
        with open("batch_stt_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        time.sleep(2) # Pauses between requests to respect API rate limits

def process_pdf():
    pdf_path = ROOT.parent / "Project_record" / "Speech (AI)" / "บทสนทนา50บท.pdf"
    if not pdf_path.exists() or not HAS_PYPDF:
        print("PDF not found or pypdf not installed.")
        return

    print("Extracting text from PDF for EMR batch testing...", flush=True)
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
        
    import re
    # Splitting scripts by "บทที่" or similar headers
    chunks = re.split(r'บทที่\s*\d+', text)
    chunks = [c.strip() for c in chunks if len(c.strip()) > 50]
    
    print(f"Found {len(chunks)} conversation chunks in PDF.", flush=True)
    results = {}
    
    for i, chunk in enumerate(chunks):
        print(f"[{i+1}/{len(chunks)}] EMR Extraction on chunk length {len(chunk)}...", flush=True)
        try:
            emr_data = extract_emr(chunk)
            results[f"Conversation_{i+1}"] = {"status": "success", "input_snippet": chunk[:150], "emr": emr_data}
        except Exception as e:
            results[f"Conversation_{i+1}"] = {"status": "error", "input_snippet": chunk[:150], "error": str(e)}
            
        with open("batch_emr_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        time.sleep(3) # Groq API rate limits

if __name__ == "__main__":
    print("=== STARTING BATCH PROCESS ===")
    try:
        process_audio_files()
    except Exception as e:
        print(f"Error in audio processing: {e}")
        
    if HAS_PYPDF:
        try:
            process_pdf()
        except Exception as e:
            print(f"Error in PDF processing: {e}")
    print("=== BATCH PROCESS COMPLETE ===")
