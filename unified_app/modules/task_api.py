"""Client for the asynchronous Core API audio-processing queue."""
from __future__ import annotations

import os
from typing import Any

import requests


CORE_API_URL = os.environ.get("PHARMATALK_CORE_API_URL", "http://127.0.0.1:8080").rstrip("/")


def queue_audio(audio_bytes: bytes, filename: str) -> str:
    response = requests.post(
        f"{CORE_API_URL}/upload-audio",
        files={"file": (filename, audio_bytes, "audio/wav")},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["task_id"])


def get_task(task_id: str) -> dict[str, Any]:
    response = requests.get(f"{CORE_API_URL}/task/{task_id}", timeout=10)
    response.raise_for_status()
    return response.json()


def get_core_health() -> dict[str, Any]:
    response = requests.get(f"{CORE_API_URL}/health", timeout=3)
    response.raise_for_status()
    return response.json()