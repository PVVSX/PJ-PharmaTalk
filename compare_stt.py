import os
import time
import asyncio
from pathlib import Path
from colorama import init, Fore

# Import STT Modules
from unified_app.modules.stt_groq import transcribe_audio_groq
from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes

init(autoreset=True)

def main():
    print(Fore.CYAN + "=== STT Comparison Tool (Typhoon vs Groq) ===")
    
    # 1. Find a sample audio file
    record_dir = Path("record")
    if not record_dir.exists():
        print(Fore.RED + "Error: Folder 'record' not found.")
        return
        
    wav_files = list(record_dir.glob("*.wav"))
    if not wav_files:
        print(Fore.RED + "Error: No .wav files found in 'record' folder.")
        return
        
    test_file = wav_files[0]
    print(Fore.YELLOW + f"Selected test file: {test_file.name} ({os.path.getsize(test_file)/1024/1024:.2f} MB)")
    
    with open(test_file, "rb") as f:
        audio_bytes = f.read()

    # 2. Test Groq
    print(Fore.MAGENTA + "\n[1/2] Testing Groq (Whisper Large v3 Turbo)...")
    start_time = time.time()
    try:
        groq_result = transcribe_audio_groq(audio_bytes)
        groq_time = time.time() - start_time
        print(Fore.GREEN + f"Groq finished in {groq_time:.2f} seconds.")
        print(f"Result: {groq_result[:200]}...")
    except Exception as e:
        print(Fore.RED + f"Groq Error: {e}")
        groq_result = str(e)
        groq_time = -1

    # 3. Test Typhoon
    print(Fore.MAGENTA + "\n[2/2] Testing Typhoon ASR (Local NeMo Model)...")
    print("Initializing Typhoon (this may download the model ~1-2GB if first time)...")
    
    start_time = time.time()
    recognizer = TyphoonASRRecognizer()
    success = recognizer.load_model()
    
    if not success:
        print(Fore.RED + "Failed to load Typhoon ASR model.")
        typhoon_time = -1
        typhoon_result = "Failed to load"
    else:
        print(Fore.YELLOW + "Transcribing with Typhoon...")
        transcribe_start = time.time()
        typhoon_result = transcribe_audio_bytes(recognizer, audio_bytes)
        typhoon_time = time.time() - transcribe_start
        print(Fore.GREEN + f"Typhoon finished in {typhoon_time:.2f} seconds.")
        print(f"Result: {typhoon_result[:200]}...")

    # 4. Final Comparison
    print(Fore.CYAN + "\n=== FINAL COMPARISON ===")
    print(f"File: {test_file.name}")
    print(f"Groq Time    : {groq_time:.2f}s")
    print(f"Typhoon Time : {typhoon_time:.2f}s")
    
    print("\n--- Groq Transcript ---")
    print(groq_result)
    print("\n--- Typhoon Transcript ---")
    print(typhoon_result)
    
if __name__ == "__main__":
    main()
