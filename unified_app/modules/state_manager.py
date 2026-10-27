import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import urllib.request

# Create a shared state file in the record directory
RECORD_DIR = Path(__file__).resolve().parent.parent.parent / "record"
STATE_FILE = RECORD_DIR / "shared_state.json"
BRIDGE_API_URL = os.environ.get("PHARMALOG_BRIDGE_API_URL", "http://127.0.0.1:8500").rstrip("/")


def _get_database_file() -> Path:
    return RECORD_DIR / "pharmalog.db"


def _init_database(db_file: Path) -> None:
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_file)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS consent_records (
                consent_id TEXT PRIMARY KEY,
                consent_version TEXT NOT NULL,
                consented_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
        """)
        connection.commit()


def get_state() -> str:
    """
    Returns the current state of the recording session.
    Returns one of: 'WAITING', 'READY', 'RECORDING', 'FINISHED'
    """
    if not STATE_FILE.exists():
        return "WAITING"
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data.get("status", "WAITING")
    except Exception:
        return "WAITING"


def set_state(status: str, consent: Optional[dict] = None) -> None:
    """
    Updates the shared state via Bridge API if available, with a local file + SQLite
    fallback that preserves consent metadata and updates consent_records timestamps.
    """
    payload: dict = {"status": status}
    if consent is not None:
        payload["consent"] = consent

    try:
        req = urllib.request.Request(
            f"{BRIDGE_API_URL}/api/state",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if 200 <= resp.status < 300:
                return
    except Exception:
        pass

    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    existing = {}
    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    current_consent = consent if consent is not None else existing.get("consent")
    data = {
        "status": status,
        "timestamp": time.time(),
        "consent": current_consent,
    }
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    if isinstance(current_consent, dict) and current_consent.get("consent_id"):
        db_file = _get_database_file()
        try:
            _init_database(db_file)
            with closing(sqlite3.connect(db_file)) as connection:
                if status == "READY":
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO consent_records
                        (consent_id, consent_version, consented_at, recorded_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            str(current_consent["consent_id"]),
                            str(current_consent.get("consent_version", "1.0")),
                            str(current_consent.get("consented_at") or datetime.now(timezone.utc).isoformat()),
                            "",
                        ),
                    )
                elif status == "FINISHED":
                    connection.execute(
                        """
                        UPDATE consent_records
                        SET recorded_at = ?
                        WHERE consent_id = ?
                        """,
                        (
                            datetime.now(timezone.utc).isoformat(),
                            str(current_consent["consent_id"]),
                        ),
                    )
                connection.commit()
        except Exception:
            pass
