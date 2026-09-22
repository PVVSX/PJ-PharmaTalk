"""Browser audio recorder with a manual start and automatic fallback."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_COMPONENT = components.declare_component(
    "auto_recorder",
    path=str(Path(__file__).parent / "frontend"),
)


def auto_recorder(*, cooldown_seconds: int = 30, key: str | None = None) -> dict[str, Any] | None:
    """Return a WAV payload when the browser recorder is stopped."""
    value = _COMPONENT(cooldown_seconds=cooldown_seconds, default=None, key=key)
    if not isinstance(value, dict) or not value.get("audio_base64"):
        return None

    try:
        audio_bytes = base64.b64decode(value["audio_base64"], validate=True)
    except (ValueError, TypeError):
        return None

    return {
        "audio_bytes": audio_bytes,
        "duration_seconds": value.get("duration_seconds", 0),
        "automatic": bool(value.get("automatic", False)),
    }