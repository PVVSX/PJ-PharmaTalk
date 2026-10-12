import json
from pathlib import Path
import time

# Create a shared state file in the record directory
RECORD_DIR = Path(__file__).resolve().parent.parent.parent / "record"
STATE_FILE = RECORD_DIR / "shared_state.json"

def get_state() -> str:
    """
    Returns the current state of the recording session.
    Returns one of: 'WAITING', 'READY', 'FINISHED'
    """
    if not STATE_FILE.exists():
        return "WAITING"
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("status", "WAITING")
    except Exception:
        return "WAITING"

def set_state(status: str) -> None:
    """
    Updates the shared state.
    """
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "status": status,
        "timestamp": time.time()
    }
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
