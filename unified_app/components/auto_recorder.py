"""Browser audio recorder (16 kHz mono WAV). In pharmacist mode it claims the consent (RECORDING) before capturing."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_COMPONENT = components.declare_component("auto_recorder", path=str(Path(__file__).parent / "frontend"))


def auto_recorder(*, key: str | None = None, api_url: str = "", max_seconds: int = 1200,
                  cooldown_seconds: int = 0) -> dict[str, Any] | None:
    """Return {"audio_bytes", "duration_seconds"} when a recording is stopped. api_url="" disables the consent claim."""
    value = _COMPONENT(api_url=api_url, max_seconds=max_seconds, default=None, key=key)
    if not isinstance(value, dict) or not value.get("audio_base64"):
        return None
    try:
        audio_bytes = base64.b64decode(value["audio_base64"], validate=True)
    except (ValueError, TypeError):
        return None
    return {"audio_bytes": audio_bytes, "duration_seconds": value.get("duration_seconds", 0),
            "automatic": bool(value.get("automatic", False))}
