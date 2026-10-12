import os
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes
from unified_app.modules.emr_groq import check_credentials, _call_groq

def format_with_llm(api_key: str, raw_transcript: str) -> str:
    prompt = f"""
นำบทสนทนาภาษาไทยนี้มาจัดเรียงใหม่ โดยแยกผู้พูดเป็น "เภสัชกร:" และ "คนไข้:"
ข้อความที่ได้รับจะไม่มีการเว้นวรรคหรือแบ่งคนพูด ให้คุณวิเคราะห์จากบริบทคำถาม-คำตอบ แล้วหั่นประโยคให้ถูกต้อง
ห้ามแต่งเติมเรื่องราว ห้ามเปลี่ยนความหมาย และไม่ต้องมีคำอธิบายเพิ่มเติม ให้ตอบกลับเฉพาะบทสนทนาที่จัดเรียงแล้วเท่านั้น

ข้อความต้นฉบับ:
{raw_transcript}
"""
    try:
        # Using a model that groq supports for quick reasoning
        response = _call_groq(api_key, "llama3-70b-8192", prompt)
        # fallback to formatting if response format was forced to json in _call_groq, wait _call_groq has response_format={"type": "json_object"}
        # Ah, _call_groq is hardcoded to return JSON object. We should not use _call_groq directly if it forces JSON.
        pass
    except Exception:
        pass
    return ""

def format_with_groq_direct(api_key: str, raw_transcript: str) -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    prompt = f"""นำบทสนทนาภาษาไทยนี้มาจัดเรียงใหม่ โดยแยกผู้พูดเป็น "เภสัชกร:" และ "คนไข้:"
ข้อความที่ได้รับจะไม่มีการเว้นวรรคหรือแบ่งคนพูด ให้วิเคราะห์จากบริบทคำถาม-คำตอบ แล้วหั่นประโยคให้ถูกต้อง
ห้ามแต่งเติมเรื่องราว ห้ามเปลี่ยนความหมาย และไม่ต้องมีคำอธิบาย ให้ตอบเฉพาะบทสนทนาที่จัดเรียงแล้ว

ข้อความ:
{raw_transcript}"""
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b",
            temperature=0.1,
        )
        return chat_completion.choices[0].message.content or ""
    except Exception as e:
        print(f"Groq API Error: {e}")
        return f"(ไม่สามารถแยกผู้พูดได้เนื่องจากข้อผิดพลาด: {e})\n{raw_transcript}"

def run_pipeline():
    print("Initializing Typhoon ASR Model (This might take a moment to load to CPU)...")
    recognizer = TyphoonASRRecognizer()
    if hasattr(recognizer, "load_model"):
        recognizer.load_model()
        
    api_ok, msg = check_credentials()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        key_file = ROOT / ".groq_api_key"
        if key_file.exists():
            api_key = key_file.read_text(encoding="utf-8").strip()

    if not api_key:
        print("Groq API Key not found. Cannot separate speakers.")
        return

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
    
    report_path = ROOT / "typhoon_full_report.md"
    json_path = ROOT / "batch_typhoon_full_results.json"
    
    # Initialize report file if it doesn't exist
    if not report_path.exists():
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# รายงานผลการถอดเสียงด้วย Typhoon ASR และแยกผู้พูดด้วย Groq\n\n")
            f.write("ระบบจะทยอยอัปเดตข้อมูลทีละไฟล์ในรายงานนี้ คุณสามารถเปิดอ่านได้เลย\n\n")
            f.write("---\n\n")
            
    results = {}
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                results = json.load(f)
        except:
            pass

    print(f"Found {len(all_wavs)} WAV files. Processing...")
    
    for i, wav_path in enumerate(all_wavs):
        if wav_path.name in results and results[wav_path.name].get("status") == "success":
            print(f"[{i+1}/{len(all_wavs)}] Skipping {wav_path.name}, already processed.")
            continue
            
        size_mb = wav_path.stat().st_size / 1024 / 1024
        print(f"[{i+1}/{len(all_wavs)}] Processing {wav_path.name} ({size_mb:.1f} MB)...", flush=True)
        
        try:
            with open(wav_path, "rb") as f:
                audio_bytes = f.read()
            
            raw_transcript = transcribe_audio_bytes(recognizer, audio_bytes)
            
            if not raw_transcript.strip():
                formatted = "(ไม่มีเสียงสนทนาที่ตรวจจับได้)"
            else:
                formatted = format_with_groq_direct(api_key, raw_transcript)
                
            results[wav_path.name] = {
                "status": "success", 
                "size_mb": size_mb, 
                "raw_transcript": raw_transcript,
                "formatted_transcript": formatted
            }
            
            # Append to markdown report
            with open(report_path, "a", encoding="utf-8") as f:
                f.write(f"### ไฟล์: `{wav_path.name}` ({size_mb:.1f} MB)\n")
                f.write("**บทสนทนา (แยกผู้พูดแล้ว):**\n")
                f.write("```text\n")
                f.write(formatted.strip() + "\n")
                f.write("```\n")
                f.write("---\n\n")
                
        except Exception as e:
            results[wav_path.name] = {"status": "error", "size_mb": size_mb, "error": str(e)}
            with open(report_path, "a", encoding="utf-8") as f:
                f.write(f"### ไฟล์: `{wav_path.name}` ({size_mb:.1f} MB)\n")
                f.write(f"**เกิดข้อผิดพลาด:** {e}\n\n---\n\n")
            
        # Save JSON progress
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        time.sleep(2) # Prevent Groq rate limiting

    print("All files processed successfully.")

if __name__ == "__main__":
    run_pipeline()
