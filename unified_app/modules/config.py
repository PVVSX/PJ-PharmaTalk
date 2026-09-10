import os
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = ROOT / "result_record" / ".azure_openai_env"

def read_env_file() -> dict:
    """Read current values from .azure_openai_env file."""
    vals = {
        "AZURE_OPENAI_API_KEY": "", 
        "AZURE_OPENAI_ENDPOINT": "",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4o-mini",
        "AZURE_OPENAI_API_VERSION": "2024-02-15-preview"
    }
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals

def write_env_file(data: dict) -> None:
    """Write settings to .azure_openai_env and update current-process env."""
    _ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Azure OpenAI Settings\n"]
    for k, v in data.items():
        lines.append(f"{k}={v}\n")
    _ENV_FILE.write_text("".join(lines), encoding="utf-8")
    for k, v in data.items():
        os.environ[k] = v
