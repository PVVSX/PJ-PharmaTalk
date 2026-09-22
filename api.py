import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="PharmaTalk Bridge API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parent
RECORD_DIR = ROOT / "record"
STATE_FILE = RECORD_DIR / "shared_state.json"
DATABASE_FILE = RECORD_DIR / "pharmatalk.db"
CONSENT_APP_DIR = ROOT / "consent_app"

class StateModel(BaseModel):
    status: str
    consent: Optional[dict] = None


def init_database() -> None:
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_FILE) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS consent_records (
                consent_id TEXT PRIMARY KEY,
                consent_version TEXT NOT NULL,
                consented_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
        """)
        connection.commit()

def get_state_internal():
    if not STATE_FILE.exists():
        return {"status": "WAITING", "timestamp": 0}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data
    except Exception:
        return {"status": "WAITING", "timestamp": 0}

def set_state_internal(status: str, consent: Optional[dict] = None):
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "status": status,
        "timestamp": time.time()
    }
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if status == "READY" and consent and consent.get("consent_id"):
        consent_record = {
            "consent_id": str(consent["consent_id"]),
            "consent_version": str(consent.get("consent_version", "1.0")),
            "consented_at": str(consent.get("consented_at") or datetime.now(timezone.utc).isoformat()),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        init_database()
        with sqlite3.connect(DATABASE_FILE) as connection:
            connection.execute("""
                INSERT OR IGNORE INTO consent_records
                (consent_id, consent_version, consented_at, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (
                consent_record["consent_id"],
                consent_record["consent_version"],
                consent_record["consented_at"],
                consent_record["recorded_at"],
            ))
            connection.commit()
    return data

@app.get("/api/state")
def get_state():
    return get_state_internal()

@app.post("/api/state")
def set_state(req: StateModel):
    if req.status not in ["WAITING", "READY", "FINISHED"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    return set_state_internal(req.status, req.consent)

# Serve the static HTML app at the root "/"
if CONSENT_APP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(CONSENT_APP_DIR), html=True), name="consent_app")

if __name__ == "__main__":
    # Ensure state is reset when API starts
    init_database()
    set_state_internal("WAITING")
    uvicorn.run(app, host="0.0.0.0", port=8502)
