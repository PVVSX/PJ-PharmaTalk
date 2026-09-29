import os
import uuid
import time
import shutil
import asyncio
import json
import sys
from pathlib import Path
import uvicorn
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi.concurrency import run_in_threadpool
from firebase_admin import firestore

# Add root directory to sys.path to import unified_app modules
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from unified_app.modules.stt_typhoon import TyphoonASRRecognizer, transcribe_audio_bytes, ASR_AVAILABLE
from unified_app.modules.emr_groq import extract_emr
from unified_app.modules.stt_groq import transcribe_audio_groq
from unified_app.modules.stt_deepgram import transcribe_audio_deepgram

# TOGGLE FOR STT MODEL
# Set USE_DEEPGRAM_STT = True to use Diarization (Speaker separation)
USE_DEEPGRAM_STT = False
USE_GROQ_STT = False



from database import SessionLocal, TaskTracker, engine
from firebase_config import get_firestore_client, upload_file_to_storage

app = FastAPI(title="PharmaTalk Fault-Tolerant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "asr_available": ASR_AVAILABLE,
        "asr_loaded": bool(getattr(asr_recognizer, "is_loaded", False)),
    }


@app.get("/")
async def root():
    return {
        "service": "PharmaTalk Core API",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "temp_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Global ASR Recognizer
asr_recognizer = TyphoonASRRecognizer()
if ASR_AVAILABLE:
    print("Loading Typhoon ASR Model...")
    # This might take time depending on hardware
    asr_recognizer.load_model()


# --- BACKGROUND WORKER WITH RETRY ---
async def process_audio_task(task_id: str, audio_path: str):
    db = SessionLocal()
    task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
    if not task:
        db.close()
        return

    max_retries = 3
    base_wait = 5 # seconds

    # Step 1: STT Processing
    try:
        task.status = "STT_PROCESSING"
        db.commit()
        
        # Call STT based on configuration
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
            
        if USE_DEEPGRAM_STT:
            stt_result = await run_in_threadpool(transcribe_audio_deepgram, audio_bytes)
        elif USE_GROQ_STT:
            stt_result = await run_in_threadpool(transcribe_audio_groq, audio_bytes, "audio.wav")
        else:
            stt_result = await run_in_threadpool(transcribe_audio_bytes, asr_recognizer, audio_bytes)
        
        task.stt_text = stt_result
        task.status = "STT_DONE"
        db.commit()
        
        # Save to Firestore EARLY so it shows up in History page immediately
        firestore_db = get_firestore_client()
        if firestore_db:
            try:
                doc_ref = firestore_db.collection("patients_emr").document(task_id)
                doc_ref.set({
                    "task_id": task_id,
                    "stt_text": task.stt_text,
                    "emr_data": {},
                    "audio_filename": os.path.basename(audio_path),
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "status": "EMR_PROCESSING"
                })
                print(f"Task {task_id} saved to Firestore (STT only) successfully.")
            except Exception as fs_error:
                print(f"Warning: Failed to save STT to Firestore: {fs_error}")

    except Exception as e:
        task.status = "ERROR"
        task.error_message = f"STT Failed: {str(e)}"
        db.commit()
        db.close()
        return # Optionally implement retry for STT here too

    # Step 2: EMR Processing (LLM) with Retry Mechanism for API failure
    for attempt in range(max_retries):
        try:
            task.status = "EMR_PROCESSING"
            db.commit()
            
            # Call actual Groq extraction
            emr_dict = await run_in_threadpool(extract_emr, task.stt_text)
            emr_result = json.dumps(emr_dict, ensure_ascii=False)
            
            task.emr_json = emr_result
            task.status = "COMPLETED"
            db.commit()
            
            # Update to Firestore
            firestore_db = get_firestore_client()
            if firestore_db:
                try:
                    doc_ref = firestore_db.collection("patients_emr").document(task_id)
                    doc_ref.update({
                        "emr_data": emr_dict,
                        "status": "COMPLETED"
                    })
                    print(f"Task {task_id} EMR updated to Firestore successfully.")
                    
                    # 🚀 AUTOMATICALLY UPLOAD AUDIO TO CLOUD STORAGE
                    try:
                        destination = f"recordings/{os.path.basename(audio_path)}"
                        upload_file_to_storage(audio_path, destination)
                        print(f"Audio {audio_path} automatically uploaded to Cloud Storage as {destination}")
                    except Exception as upload_err:
                        print(f"Warning: Failed to automatically upload audio to Cloud Storage: {upload_err}")
                        
                except Exception as fs_error:
                    print(f"Warning: Failed to update EMR to Firestore: {fs_error}")
            
            break # Success!
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = base_wait * (2 ** attempt) # Exponential backoff: 5s, 10s...
                task.retry_count += 1
                task.status = f"RETRYING_EMR_IN_{wait_time}S"
                task.error_message = str(e)
                db.commit()
                await asyncio.sleep(wait_time)
            else:
                task.status = "ERROR"
                task.error_message = f"EMR API Failed after retries: {str(e)}"
                db.commit()
                
                # Update status in Firestore
                firestore_db = get_firestore_client()
                if firestore_db:
                    try:
                        doc_ref = firestore_db.collection("patients_emr").document(task_id)
                        doc_ref.update({
                            "status": "EMR_ERROR",
                            "error_message": task.error_message
                        })
                    except Exception as fs_error:
                        pass

    db.close()


@app.post("/upload-audio")
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    task_id = str(uuid.uuid4())
    file_path = os.path.join(AUDIO_DIR, f"{task_id}_{file.filename}")
    
    # 1. Save file safely first
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 2. Record task in DB
    new_task = TaskTracker(
        id=task_id,
        status="UPLOADED",
        audio_path=file_path
    )
    db.add(new_task)
    db.commit()
    
    # 3. Trigger Background Processing
    background_tasks.add_task(process_audio_task, task_id, file_path)
    
    return {"message": "Audio received and queued", "task_id": task_id}

@app.get("/task/{task_id}")
async def get_task_status(task_id: str, db: Session = Depends(get_db)):
    task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    return {
        "task_id": task.id,
        "status": task.status,
        "retry_count": task.retry_count,
        "stt_text": task.stt_text,
        "emr_json": task.emr_json,
        "error_message": task.error_message
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PHARMATALK_CORE_API_PORT", "8080")))
