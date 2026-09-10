import os
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
KEY_FILE = ROOT / ".gemini_api_key"

def read_env_file() -> dict:
    """Read API config from file."""
    api_key = ""
    if KEY_FILE.exists():
        api_key = KEY_FILE.read_text(encoding="utf-8").strip()
    return {
        "GEMINI_API_KEY": api_key,
        "GEMINI_MODEL_NAME": "gemini-2.5-pro"
    }

def write_env_file(data: dict) -> None:
    """No-op since config is hardcoded."""
    pass

