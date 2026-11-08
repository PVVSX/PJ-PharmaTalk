"""Client for the asynchronous Core API audio-processing queue."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

CORE_API_URL = os.environ.get(
    "PHARMALOG_CORE_API_URL", os.environ.get("PHARMATALK_CORE_API_URL", "http://127.0.0.1:8080")
).rstrip("/")


class CoreAPIError(RuntimeError):
    pass


def _raise(resp: requests.Response) -> None:
    if resp.ok:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    raise CoreAPIError(f"{resp.status_code}: {detail}")


def queue_audio(audio_bytes: bytes, filename: str, consent_id: Optional[str] = None, source: str = "unknown") -> str:
    data = {"source": source}
    if consent_id:
        data["consent_id"] = consent_id
    resp = requests.post(f"{CORE_API_URL}/upload-audio", files={"file": (filename, audio_bytes, "audio/wav")},
                         data=data, timeout=60)
    _raise(resp)
    return str(resp.json()["task_id"])


def get_task(task_id: str) -> Dict[str, Any]:
    resp = requests.get(f"{CORE_API_URL}/task/{task_id}", timeout=10)
    _raise(resp)
    return resp.json()


def list_tasks(limit: int = 20) -> List[Dict[str, Any]]:
    resp = requests.get(f"{CORE_API_URL}/tasks", params={"limit": limit}, timeout=10)
    _raise(resp)
    return resp.json()


def retry_task(task_id: str) -> Dict[str, Any]:
    resp = requests.post(f"{CORE_API_URL}/task/{task_id}/retry", timeout=10)
    _raise(resp)
    return resp.json()


def confirm_task(task_id: str, emr: Dict[str, Any]) -> Dict[str, Any]:
    resp = requests.post(f"{CORE_API_URL}/task/{task_id}/confirm", json={"emr": emr}, timeout=15)
    _raise(resp)
    return resp.json()


def get_core_health() -> Dict[str, Any]:
    resp = requests.get(f"{CORE_API_URL}/health", timeout=3)
    _raise(resp)
    return resp.json()
