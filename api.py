"""
PharmaLog Bridge API (port 8500): serves the patient consent page and owns the shared
recording state WAITING -> READY -> RECORDING -> FINISHED.

Rules enforced here (not in the browser):
  * READY needs a fresh consent object with a consent_id that was never used before.
  * READY expires after PHARMALOG_CONSENT_TTL seconds (default 120) if recording has not started.
  * RECORDING is only allowed from a valid READY.
  * RECORDING is released after PHARMALOG_RECORDING_MAX_S seconds (default 1800 = 30 min; the recorder stops
    itself at 20 min) so a closed/crashed pharmacist browser cannot block the next patient forever.
  * WAITING (also used for "decline") clears the consent so it can never carry over.
  * Every transition is written to consent_events (audit trail); FINISHED links the consent
    to the task_id and audio file that were produced under it.
"""
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="PharmaLog AI Bridge API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ROOT = Path(__file__).resolve().parent
RECORD_DIR = ROOT / "record"
STATE_FILE = RECORD_DIR / "shared_state.json"
DATABASE_FILE = RECORD_DIR / "pharmalog.db"
CONSENT_APP_DIR = ROOT / "consent_app"
CONSENT_TTL = float(os.environ.get("PHARMALOG_CONSENT_TTL", "120"))
RECORDING_MAX_S = float(os.environ.get("PHARMALOG_RECORDING_MAX_S", "1800"))
VALID = ("WAITING", "READY", "RECORDING", "FINISHED")


class StateModel(BaseModel):
    status: str
    consent: Optional[dict] = None
    reason: Optional[str] = None          # e.g. "declined", "expired", "new_patient"
    task_id: Optional[str] = None         # sent with FINISHED
    audio_filename: Optional[str] = None  # sent with FINISHED


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_database() -> None:
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_FILE)) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS consent_records (
            consent_id TEXT PRIMARY KEY, consent_version TEXT NOT NULL,
            consented_at TEXT NOT NULL, recorded_at TEXT NOT NULL)""")
        cols = {r[1] for r in c.execute("PRAGMA table_info(consent_records)")}
        for col in ("task_id", "audio_filename", "status"):
            if col not in cols:
                c.execute(f"ALTER TABLE consent_records ADD COLUMN {col} TEXT DEFAULT ''")
        c.execute("""CREATE TABLE IF NOT EXISTS consent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL,
            consent_id TEXT, detail TEXT)""")
        c.commit()


def _event(event: str, consent_id: Optional[str], detail: str = "") -> None:
    with closing(sqlite3.connect(DATABASE_FILE)) as c:
        c.execute("INSERT INTO consent_events (at, event, consent_id, detail) VALUES (?,?,?,?)",
                  (_now(), event, consent_id, detail))
        c.commit()


def _read() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "WAITING", "timestamp": 0, "consent": None}


def _write(status: str, consent: Optional[dict]) -> dict:
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    data = {"status": status, "timestamp": time.time(), "consent": consent}
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)
    return data


def get_state_internal() -> dict:
    data = _read()
    if data.get("status") == "READY" and time.time() - float(data.get("timestamp") or 0) > CONSENT_TTL:
        cid = (data.get("consent") or {}).get("consent_id")
        if cid:
            with closing(sqlite3.connect(DATABASE_FILE)) as c:
                c.execute("UPDATE consent_records SET status='expired' WHERE consent_id=? AND status IN ('', 'ready')", (cid,))
                c.commit()
            _event("EXPIRED", cid, f"no recording within {CONSENT_TTL:.0f}s")
        data = _write("WAITING", None)
    elif data.get("status") == "RECORDING" and time.time() - float(data.get("timestamp") or 0) > RECORDING_MAX_S:
        cid = (data.get("consent") or {}).get("consent_id")
        if cid:
            with closing(sqlite3.connect(DATABASE_FILE)) as c:
                c.execute("UPDATE consent_records SET status='abandoned' WHERE consent_id=? AND status='recording'", (cid,))
                c.commit()
            _event("RECORDING_TIMEOUT", cid, f"still RECORDING after {RECORDING_MAX_S:.0f}s (browser closed?)")
        data = _write("WAITING", None)
    data["ttl_seconds"] = CONSENT_TTL
    if data.get("status") == "READY":
        data["expires_in"] = max(0, round(CONSENT_TTL - (time.time() - float(data["timestamp"]))))
    return data


def set_state_internal(req: StateModel) -> dict:
    init_database()
    current = get_state_internal()
    cur_consent = current.get("consent") or None
    cur_id = (cur_consent or {}).get("consent_id")

    if req.status == "WAITING":
        if cur_id and current["status"] in ("READY", "RECORDING"):
            with closing(sqlite3.connect(DATABASE_FILE)) as c:
                c.execute("UPDATE consent_records SET status=? WHERE consent_id=? AND status IN ('', 'ready', 'recording')",
                          (req.reason or "cancelled", cur_id)); c.commit()
        _event("DECLINED" if req.reason == "declined" else "WAITING", cur_id, req.reason or "")
        return _write("WAITING", None)

    if req.status == "READY":
        consent = req.consent or {}
        cid = str(consent.get("consent_id") or "").strip()
        if not cid:
            raise HTTPException(400, "READY ต้องมี consent พร้อม consent_id")
        if current["status"] == "RECORDING":
            raise HTTPException(409, "กำลังบันทึกเสียงของคนไข้อีกรายอยู่")
        with closing(sqlite3.connect(DATABASE_FILE)) as c:
            if c.execute("SELECT 1 FROM consent_records WHERE consent_id=?", (cid,)).fetchone():
                raise HTTPException(409, "consent_id นี้ถูกใช้แล้ว ต้องขอความยินยอมใหม่")
            c.execute("""INSERT INTO consent_records (consent_id, consent_version, consented_at, recorded_at, status)
                         VALUES (?,?,?,?, 'ready')""",
                      (cid, str(consent.get("consent_version", "1.0")), str(consent.get("consented_at") or _now()), ""))
            c.commit()
        _event("READY", cid)
        return _write("READY", {"consent_id": cid, "consent_version": str(consent.get("consent_version", "1.0")),
                                "consented_at": str(consent.get("consented_at") or _now())})

    if req.status == "RECORDING":
        if current["status"] == "RECORDING" and cur_id:
            return current
        if current["status"] != "READY" or not cur_id:
            raise HTTPException(409, "ยังไม่มีความยินยอมที่ใช้ได้ (หมดอายุหรือยังไม่ได้กดยินยอม)")
        with closing(sqlite3.connect(DATABASE_FILE)) as c:
            c.execute("UPDATE consent_records SET status='recording' WHERE consent_id=?", (cur_id,)); c.commit()
        _event("RECORDING", cur_id)
        return _write("RECORDING", cur_consent)

    if req.status == "FINISHED":
        cid = (req.consent or {}).get("consent_id") or cur_id
        if not cid:
            raise HTTPException(409, "ไม่มี consent ที่จะปิดงาน")
        with closing(sqlite3.connect(DATABASE_FILE)) as c:
            c.execute("""UPDATE consent_records SET recorded_at=?, status='finished',
                         task_id=COALESCE(?, task_id), audio_filename=COALESCE(?, audio_filename) WHERE consent_id=?""",
                      (_now(), req.task_id, req.audio_filename, cid)); c.commit()
        _event("FINISHED", cid, json.dumps({"task_id": req.task_id, "audio": req.audio_filename}, ensure_ascii=False))
        return _write("FINISHED", cur_consent or {"consent_id": cid})

    raise HTTPException(400, "Invalid status")


@app.get("/api/state")
def get_state():
    return get_state_internal()


@app.post("/api/state")
def set_state(req: StateModel):
    if req.status not in VALID:
        raise HTTPException(status_code=400, detail="Invalid status")
    return set_state_internal(req)


@app.get("/api/consents")
def list_consents(limit: int = 50):
    init_database()
    with closing(sqlite3.connect(DATABASE_FILE)) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM consent_records ORDER BY consented_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


if CONSENT_APP_DIR.exists():
    @app.get("/", include_in_schema=False)
    def consent_page():
        return FileResponse(CONSENT_APP_DIR / "index-popup-scenes.html",
                            headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    app.mount("/", StaticFiles(directory=str(CONSENT_APP_DIR), html=True), name="consent_app")

if __name__ == "__main__":
    init_database()
    _write("WAITING", None)
    host = os.environ.get("PHARMALOG_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=int(os.environ.get("PHARMALOG_BRIDGE_PORT", "8500")))
