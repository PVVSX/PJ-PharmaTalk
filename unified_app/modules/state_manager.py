"""Client for the Bridge API recording state. All writes go through the API so its consent rules apply."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

RECORD_DIR = Path(__file__).resolve().parent.parent.parent / "record"
STATE_FILE = RECORD_DIR / "shared_state.json"
BRIDGE_API_URL = os.environ.get("PHARMALOG_BRIDGE_API_URL", "http://127.0.0.1:8500").rstrip("/")
# URL the *browser* uses to reach the bridge (may differ from the server-side URL on a LAN setup)
BRIDGE_PUBLIC_URL = os.environ.get("PHARMALOG_BRIDGE_PUBLIC_URL", "http://localhost:8500").rstrip("/")


def get_state_full() -> Dict[str, Any]:
    """Current state dict {status, consent, timestamp, ...}. Falls back to the state file (read-only)."""
    try:
        with urllib.request.urlopen(f"{BRIDGE_API_URL}/api/state", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            data["_source"] = "api"
            return data
    except Exception:
        pass
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {"status": "WAITING", "consent": None, "timestamp": 0}
    ttl = float(os.environ.get("PHARMALOG_CONSENT_TTL", "120"))
    if data.get("status") == "READY" and time.time() - float(data.get("timestamp") or 0) > ttl:
        data = {"status": "WAITING", "consent": None, "timestamp": time.time()}
    data["_source"] = "file"
    return data


def get_state() -> str:
    return get_state_full().get("status", "WAITING")


def set_state(status: str, consent: Optional[dict] = None, **extra: Any) -> Tuple[bool, str]:
    """POST a new state. Returns (ok, message). Never writes the state file directly."""
    payload: Dict[str, Any] = {"status": status}
    if consent is not None:
        payload["consent"] = consent
    payload.update({k: v for k, v in extra.items() if v is not None})
    req = urllib.request.Request(
        f"{BRIDGE_API_URL}/api/state",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 300, ""
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = str(exc)
        return False, detail
    except Exception as exc:
        return False, f"เชื่อมต่อ Bridge API ไม่ได้: {exc}"
