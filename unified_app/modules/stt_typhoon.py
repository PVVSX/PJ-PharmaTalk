"""
Speech-to-Text Module (Typhoon ASR)
Wraps the existing TyphoonASRRecognizer with a simpler interface.
Falls back gracefully when NeMo / typhoon-asr is not installed.
"""
import os
import sys
import tempfile
from pathlib import Path

# ── Import the recognizer from the existing speech_to_text app ──
_stt_app_path = str(Path(__file__).resolve().parent.parent.parent / "speech_to_text" / "app")
if _stt_app_path not in sys.path:
    sys.path.insert(0, _stt_app_path)

try:
    from backend.models.asr_model import TyphoonASRRecognizer  # noqa: F401
    ASR_AVAILABLE = True
except ImportError:
    ASR_AVAILABLE = False

    # Provide a stub so the app can still render its UI
    class TyphoonASRRecognizer:  # type: ignore[no-redef]
        is_loaded = False

        def load_model(self) -> bool:
            return False

        def transcribe_audio(self, path: str) -> str:
            return ""


def transcribe_audio_bytes(recognizer: TyphoonASRRecognizer, audio_bytes: bytes) -> str:
    """
    Write audio bytes to a temp WAV file and transcribe using the recognizer.
    Returns the transcribed text or an error message string.
    """
    if not audio_bytes:
        return ""

    if not getattr(recognizer, "is_loaded", False):
        return "(ระบบถอดเสียงยังไม่พร้อม)"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        result = recognizer.transcribe_audio(tmp_path)
        return result if isinstance(result, str) else str(result)
    except Exception as exc:
        return f"(ถอดเสียงล้มเหลว: {exc})"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
