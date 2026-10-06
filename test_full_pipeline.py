import os
import time
import asyncio
from pathlib import Path
from colorama import init, Fore
import json

init(autoreset=True)

# Import all modules from the pipeline
from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes
from unified_app.modules.stt_deepgram import transcribe_audio_deepgram
from unified_app.modules.emr_groq import extract_emr

async def run_full_pipeline_test(wav_path: Path):
    print(Fore.CYAN + f"\n========== 🚀 TESTING PIPELINE FOR: {wav_path.name} ==========")
    
    with open(wav_path, "rb") as f:
        audio_bytes = f.read()

    # 1. Initialize Typhoon
    print(Fore.YELLOW + "1. Loading Typhoon ASR...")
    recognizer = TyphoonASRRecognizer()
    recognizer.load_model()
    
    # 2. Run STT (Typhoon + Dictionary) and Diarization (Deepgram) in PARALLEL
    print(Fore.YELLOW + "2. Running STT (Typhoon) + Diarization (Deepgram) in parallel...")
    start_stt = time.time()
    
    # Simulate asyncio wrapper for synchronous functions
    loop = asyncio.get_running_loop()
    task_typhoon = loop.run_in_executor(None, transcribe_audio_bytes, recognizer, audio_bytes)
    task_deepgram = loop.run_in_executor(None, transcribe_audio_deepgram, audio_bytes)
    
    results = await asyncio.gather(task_typhoon, task_deepgram, return_exceptions=True)
    stt_time = time.time() - start_stt
    
    typhoon_res = results[0]
    deepgram_res = results[1]
    
    print(Fore.GREEN + f"   -> STT Phase completed in {stt_time:.2f} seconds.")
    
    # Error checking STT Phase
    has_error = False
    if isinstance(typhoon_res, Exception) or "(เกิดข้อผิดพลาด" in str(typhoon_res):
        print(Fore.RED + f"   [ERROR] Typhoon STT failed: {typhoon_res}")
        has_error = True
        typhoon_text = str(typhoon_res)
    else:
        typhoon_text = typhoon_res
        
    if isinstance(deepgram_res, Exception):
        print(Fore.RED + f"   [ERROR] Deepgram Diarization failed: {deepgram_res}")
        has_error = True
        deepgram_text = str(deepgram_res)
    else:
        deepgram_text = deepgram_res
        
    print(Fore.WHITE + "--- Typhoon Result (with Dictionary) ---")
    print(f"{typhoon_text[:200]}..." if len(typhoon_text) > 200 else typhoon_text)
    
    if has_error:
        print(Fore.RED + "Pipeline stopped early due to STT errors.")
        return

    # 3. Combine results for LLM
    print(Fore.YELLOW + "\n3. Combining results for Groq EMR LLM...")
    combined_text = f"--- ส่วนที่ 1: ข้อความเนื้อหาภาษาไทย ---\n{typhoon_text}\n\n--- ส่วนที่ 2: โครงสร้างคนพูด (Deepgram) ---\n{deepgram_text}"
    
    # 4. Run EMR Extraction
    print(Fore.YELLOW + "4. Extracting EMR via Groq...")
    start_emr = time.time()
    try:
        emr_result = await loop.run_in_executor(None, extract_emr, combined_text)
        emr_time = time.time() - start_emr
        print(Fore.GREEN + f"   -> EMR Extraction completed in {emr_time:.2f} seconds.")
        
        # Parse JSON
        if isinstance(emr_result, dict):
            emr_json = emr_result
        else:
            emr_json = json.loads(emr_result)
            
        print(Fore.CYAN + "\n✅ [SUCCESS] FULL PIPELINE COMPLETED!")
        print(Fore.MAGENTA + f"Total Pipeline Time: {stt_time + emr_time:.2f} seconds")
        print(Fore.WHITE + "--- Raw EMR JSON Output ---")
        print(json.dumps(emr_json, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(Fore.RED + f"   [ERROR] EMR Extraction failed: {e}")

async def main():
    ROOT = Path(__file__).resolve().parent
    audio_dirs = [
        ROOT.parent / "Project_record" / "Demo" / "record",
        ROOT.parent / "Project_record" / "october" / "Week 1"
    ]
    
    all_wavs = []
    for d in audio_dirs:
        if d.exists():
            all_wavs.extend(list(d.glob("*.wav")))
            
    if not all_wavs:
        print("No audio files found!")
        return
        
    all_wavs.sort(key=lambda p: p.stat().st_size)
    
    test_file = Path("/Users/pvvsx/Desktop/PJ/Project_record/Demo/record/recording_2025-10-09_13-47-26.wav")
    await run_full_pipeline_test(test_file)

if __name__ == "__main__":
    asyncio.run(main())
