import os
import time
import json
import asyncio
from pathlib import Path

# Import STT Modules
from unified_app.modules.stt_groq import transcribe_audio_groq
from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes

def main():
    print("=== STT Batch Comparison Tool ===")
    
    ROOT = Path(__file__).resolve().parent
    audio_dirs = [
        ROOT.parent / "Project_record" / "Demo" / "record",
        ROOT.parent / "Project_record" / "october" / "Week 1"
    ]
    
    all_wavs = []
    for d in audio_dirs:
        if d.exists():
            all_wavs.extend(list(d.glob("*.wav")))
            
    # Sort by size to run smallest first
    all_wavs.sort(key=lambda p: p.stat().st_size)
    
    if not all_wavs:
        print("No .wav files found.")
        return
        
    print(f"Found {len(all_wavs)} files. Testing the first 3 files for a quick comparison...\n")
    
    # Initialize Typhoon
    print("Initializing Typhoon ASR (May take a while if downloading model)...")
    recognizer = TyphoonASRRecognizer()
    success = recognizer.load_model()
    if not success:
        print("Failed to load Typhoon. Exiting.")
        return
        
    report_path = ROOT / "STT_Side_by_Side_Report.md"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 📊 รายงานเปรียบเทียบ: Typhoon (Local) vs Groq (Cloud)\n\n")
        f.write("ทดสอบกับไฟล์เสียงขนาดเล็ก 3 ไฟล์แรก เพื่อดูความแตกต่างของคำศัพท์และความเร็ว\n\n")
        
    for i, test_file in enumerate(all_wavs[:3]):
        file_mb = os.path.getsize(test_file) / (1024 * 1024)
        print(f"[{i+1}/3] Processing: {test_file.name} ({file_mb:.2f} MB)")
        
        with open(test_file, "rb") as f_in:
            audio_bytes = f_in.read()

        # Groq
        start = time.time()
        try:
            groq_res = transcribe_audio_groq(audio_bytes)
        except Exception as e:
            groq_res = f"Error: {e}"
        groq_time = time.time() - start
        
        # Typhoon
        start = time.time()
        try:
            typhoon_res = transcribe_audio_bytes(recognizer, audio_bytes)
        except Exception as e:
            typhoon_res = f"Error: {e}"
        typhoon_time = time.time() - start
        
        # Write to report
        with open(report_path, "a", encoding="utf-8") as f:
            f.write(f"## 🎵 ไฟล์: `{test_file.name}` (ขนาด {file_mb:.2f} MB)\n")
            f.write(f"- **เวลาที่ Groq ใช้:** {groq_time:.2f} วินาที\n")
            f.write(f"- **เวลาที่ Typhoon ใช้:** {typhoon_time:.2f} วินาที\n\n")
            
            f.write("### 📝 ผลลัพธ์จาก Groq (เร็วแต่วิ่งผ่าน Cloud)\n")
            f.write(f"> {groq_res}\n\n")
            
            f.write("### 📝 ผลลัพธ์จาก Typhoon (ช้ากว่าแต่ปลอดภัย 100%)\n")
            f.write(f"> {typhoon_res}\n\n")
            f.write("---\n\n")
            
    print(f"\nDone! Report saved to {report_path}")

if __name__ == "__main__":
    main()
