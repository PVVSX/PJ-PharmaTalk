import json
import time
from pathlib import Path
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
CONSENT_APP_DIR = ROOT.parent / "consent_app"

class StateModel(BaseModel):
    status: str

def get_state_internal():
    if not STATE_FILE.exists():
        return {"status": "WAITING", "timestamp": 0}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data
    except Exception:
        return {"status": "WAITING", "timestamp": 0}

def set_state_internal(status: str):
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "status": status,
        "timestamp": time.time()
    }
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data

@app.get("/api/state")
def get_state():
    return get_state_internal()

@app.post("/api/state")
def set_state(req: StateModel):
    if req.status not in ["WAITING", "READY", "FINISHED"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    return set_state_internal(req.status)

# Serve the static HTML app at the root "/"
if CONSENT_APP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(CONSENT_APP_DIR), html=True), name="consent_app")

if __name__ == "__main__":
    # Ensure state is reset when API starts
    set_state_internal("WAITING")
    uvicorn.run(app, host="0.0.0.0", port=8502)
