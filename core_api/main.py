"""
PharmaLog Core API (port 8080): queue -> speech-to-text -> pharmacy dictionary -> EMR extraction.

Endpoints
  GET  /health                 engine/model status
  POST /upload-audio           multipart file (+ form consent_id, source) -> task_id
  GET  /task/{id}              task status and results
  GET  /tasks?limit=20         latest tasks for the EMR page (automated-test tasks hidden unless include_test=1)
  POST /task/{id}/retry        re-run a failed task (keeps the audio until the task succeeds)
  POST /task/{id}/confirm      store the pharmacist-reviewed EMR
"""
import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

CORE_API_DIR = Path(__file__).resolve().parent
ROOT_DIR = CORE_API_DIR.parent
for _p in (str(CORE_API_DIR), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from unified_app.modules.stt_typhoon import ASR_AVAILABLE, STTError, TyphoonASRRecognizer  # noqa: E402
from unified_app.modules.emr_groq import EMR_FIELDS, extract_emr  # noqa: E402

from database import SessionLocal, TaskTracker, utcnow  # noqa: E402
from firebase_config import cloud_disabled, get_firestore_client  # noqa: E402

MAX_UPLOAD_MB = float(os.environ.get("PHARMALOG_MAX_UPLOAD_MB", "300"))
AUDIO_DIR = CORE_API_DIR / "temp_audio"
AUDIO_DIR.mkdir(exist_ok=True)
TERMINAL = ("COMPLETED", "ERROR")

app = FastAPI(title="PharmaLog AI Core API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

asr_recognizer = TyphoonASRRecognizer()
print(f"Loading STT engine '{asr_recognizer.engine}' ({asr_recognizer.model_name}) ...")
asr_recognizer.load_model()

# Tasks that were running when the server stopped can never finish: mark them so the UI does not wait forever.
with SessionLocal() as _db:
    _n = _db.execute(text("UPDATE tasks SET status='ERROR', error_message='งานถูกขัดจังหวะเพราะเซิร์ฟเวอร์ปิดระหว่างประมวลผล (กดลองใหม่ได้)' "
                          "WHERE status NOT IN ('COMPLETED','ERROR')")).rowcount
    _db.commit()
    if _n:
        print(f"Marked {_n} interrupted task(s) as ERROR")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _fs_write(task_id: str, data: Dict[str, Any], merge: bool = True) -> None:
    """Best-effort Firestore write (skipped when PHARMALOG_DISABLE_CLOUD=1 or no credentials)."""
    client = get_firestore_client()
    if not client:
        return
    try:
        from firebase_admin import firestore
        if "created_at" in data and data["created_at"] is None:
            data["created_at"] = firestore.SERVER_TIMESTAMP
        client.collection("patients_emr").document(task_id).set(data, merge=merge)
    except Exception as exc:
        print(f"[Firestore] write failed for {task_id}: {exc}")


def _set(db: Session, task: TaskTracker, **fields) -> None:
    for k, v in fields.items():
        setattr(task, k, v)
    task.updated_at = utcnow()
    db.commit()


@app.get("/")
async def root():
    return {"service": "PharmaLog AI Core API", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "asr_available": ASR_AVAILABLE or asr_recognizer.engine == "whisper",
        "asr_loaded": bool(asr_recognizer.is_loaded),
        "stt_engine": asr_recognizer.engine,
        "stt_model": asr_recognizer.model_name,
        "stt_device": asr_recognizer.device,
        "stt_error": asr_recognizer.load_error,
        "cloud_enabled": not cloud_disabled(),
    }


async def process_audio_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
        if not task:
            return
        # ---------------- Step 1: speech-to-text (skipped on retry when a transcript already exists)
        if not (task.stt_text or "").strip():
            _set(db, task, status="STT_PROCESSING", error_message=None)
            try:
                detail = await run_in_threadpool(asr_recognizer.transcribe_detailed, task.audio_path)
            except Exception as exc:
                _set(db, task, status="ERROR", error_message=f"STT Failed: {exc}")
                _fs_write(task_id, {"status": "STT_ERROR", "error_message": task.error_message})
                return
            if not detail["raw_text"].strip():
                _set(db, task, status="ERROR", error_message="STT Failed: ไม่พบเสียงพูดในไฟล์เสียง")
                return
            meta = {k: detail[k] for k in ("engine", "model", "device", "duration_s", "elapsed_s", "chunks", "speech_chunks", "segments", "changes")}
            _set(db, task, status="STT_DONE", stt_text=detail["text"], raw_stt_text=detail["raw_text"],
                 stt_meta=json.dumps(meta, ensure_ascii=False))
            _fs_write(task_id, {"task_id": task_id, "stt_text": task.stt_text, "raw_stt_text": task.raw_stt_text,
                                "stt_engine": detail["engine"], "emr_data": {}, "audio_filename": task.audio_filename,
                                "consent_id": task.consent_id, "source": task.source, "created_at": None,
                                "status": "EMR_PROCESSING"})

        # ---------------- Step 2: EMR extraction with a bounded retry
        attempts = 2
        for attempt in range(attempts):
            try:
                _set(db, task, status="EMR_PROCESSING")
                emr = await run_in_threadpool(extract_emr, task.stt_text)
                _set(db, task, status="COMPLETED", emr_json=json.dumps(emr, ensure_ascii=False), error_message=None)
                _fs_write(task_id, {"emr_data": emr, "status": "COMPLETED"})
                break
            except Exception as exc:
                print(f"[EMR] task {task_id} attempt {attempt + 1}/{attempts} failed: {type(exc).__name__}: {exc}", flush=True)
                task.retry_count = (task.retry_count or 0) + 1
                if attempt < attempts - 1:
                    _set(db, task, status="RETRYING_EMR_IN_10S", error_message=str(exc)[:500])
                    await asyncio.sleep(10)
                else:
                    _set(db, task, status="ERROR", error_message=f"EMR Failed: {str(exc)[:500]}")
                    _fs_write(task_id, {"status": "EMR_ERROR", "error_message": task.error_message})

        # Keep the audio until the task has fully succeeded, so a failed task can be retried.
        if task.status == "COMPLETED" and task.audio_path and os.path.exists(task.audio_path):
            try:
                os.remove(task.audio_path)
            except OSError:
                pass
    except Exception as exc:  # never leave a task stuck in a running state
        try:
            task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
            if task and task.status not in TERMINAL:
                _set(db, task, status="ERROR", error_message=f"Unexpected: {exc}")
        except Exception:
            pass
        print(f"[Core] task {task_id} crashed: {exc}")
    finally:
        db.close()


@app.post("/upload-audio")
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...),
                       consent_id: Optional[str] = Form(None), source: Optional[str] = Form(None),
                       db: Session = Depends(get_db)):
    if not asr_recognizer.is_loaded:
        raise HTTPException(503, f"ระบบถอดเสียงยังไม่พร้อม {asr_recognizer.load_error}".strip())
    task_id = str(uuid.uuid4())
    safe_filename = os.path.basename(file.filename or "audio.wav")
    file_path = AUDIO_DIR / f"{task_id}_{safe_filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    size_mb = file_path.stat().st_size / 1e6
    problem = None
    if size_mb == 0:
        problem = "ไฟล์เสียงว่างเปล่า"
    elif size_mb > MAX_UPLOAD_MB:
        problem = f"ไฟล์ใหญ่เกิน {MAX_UPLOAD_MB:.0f} MB"
    else:
        try:
            import soundfile as sf
            info = sf.info(str(file_path))
            if info.frames == 0:
                problem = "ไฟล์เสียงไม่มีข้อมูลเสียง"
        except Exception as exc:
            problem = f"ไม่ใช่ไฟล์เสียงที่อ่านได้ (รองรับ WAV/FLAC/OGG): {exc}"
    if problem:
        file_path.unlink(missing_ok=True)
        raise HTTPException(400, problem)
    now = utcnow()
    db.add(TaskTracker(id=task_id, status="UPLOADED", audio_path=str(file_path), consent_id=consent_id,
                       source=source or "unknown", audio_filename=safe_filename, created_at=now, updated_at=now))
    db.commit()
    background_tasks.add_task(process_audio_task, task_id)
    return {"message": "Audio received and queued", "task_id": task_id}


def _task_dict(t: TaskTracker) -> Dict[str, Any]:
    return {"task_id": t.id, "status": t.status, "retry_count": t.retry_count, "stt_text": t.stt_text,
            "raw_stt_text": t.raw_stt_text, "stt_meta": t.stt_meta, "emr_json": t.emr_json,
            "confirmed_emr_json": t.confirmed_emr_json, "confirmed_at": t.confirmed_at,
            "error_message": t.error_message, "consent_id": t.consent_id, "source": t.source,
            "audio_filename": t.audio_filename, "created_at": t.created_at, "updated_at": t.updated_at,
            "can_retry": t.status == "ERROR" and (bool(t.stt_text) or bool(t.audio_path and os.path.exists(t.audio_path)))}


@app.get("/task/{task_id}")
async def get_task_status(task_id: str, db: Session = Depends(get_db)):
    task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(task)


@app.get("/tasks")
async def list_tasks(limit: int = 20, include_test: bool = False, db: Session = Depends(get_db)):
    q = db.query(TaskTracker)
    if not include_test:
        q = q.filter((TaskTracker.source.is_(None)) | (TaskTracker.source != "test"))
    rows = q.order_by(text("rowid DESC")).limit(max(1, min(limit, 200))).all()
    return [_task_dict(t) for t in rows]


@app.post("/task/{task_id}/retry")
async def retry_task(task_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != "ERROR":
        raise HTTPException(409, f"ลองใหม่ได้เฉพาะงานที่ผิดพลาด (สถานะตอนนี้ {task.status})")
    if not task.stt_text and not (task.audio_path and os.path.exists(task.audio_path)):
        raise HTTPException(409, "ไม่มีไฟล์เสียงหรือข้อความถอดเสียงเหลือให้ประมวลผลใหม่")
    _set(db, task, status="UPLOADED", error_message=None)
    background_tasks.add_task(process_audio_task, task_id)
    return {"task_id": task_id, "status": "UPLOADED"}


class ConfirmModel(BaseModel):
    emr: Dict[str, Any]


@app.post("/task/{task_id}/confirm")
async def confirm_task(task_id: str, body: ConfirmModel, db: Session = Depends(get_db)):
    task = db.query(TaskTracker).filter(TaskTracker.id == task_id).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != "COMPLETED":
        raise HTTPException(409, "ยืนยันได้หลังประมวลผลเสร็จเท่านั้น")
    emr = {f: str(body.emr.get(f, "-") or "-") for f in EMR_FIELDS}
    _set(db, task, confirmed_emr_json=json.dumps(emr, ensure_ascii=False), confirmed_at=utcnow())
    _fs_write(task_id, {"confirmed_emr": emr, "confirmed_at": task.confirmed_at})
    return {"task_id": task_id, "confirmed_at": task.confirmed_at}


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("PHARMALOG_HOST", "127.0.0.1"),
                port=int(os.environ.get("PHARMALOG_CORE_API_PORT", "8080")))
