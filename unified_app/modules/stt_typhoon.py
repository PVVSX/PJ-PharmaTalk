"""
Speech-to-Text module for PharmaLog.

Two engines, selected with env PHARMALOG_STT_ENGINE (default "whisper"):
  - "whisper"  : typhoon-ai/typhoon-whisper-large-v3 (Hugging Face transformers; override with PHARMALOG_WHISPER_MODEL).
                 Needs ~6.2 GB download and ~7 GB free RAM in fp32 (CPU) or a CUDA GPU (fp16, ~3.5 GB VRAM).
  - "realtime" : typhoon-ai/typhoon-asr-realtime (NeMo FastConformer-Transducer, local .nemo file) - light fallback

Both engines receive the same silence-aware chunks (<= 25 s, the length the models were trained on),
silent chunks are skipped, and the raw transcript is kept next to the dictionary-corrected one.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import torch
    import nemo.collections.asr as nemo_asr
    ASR_AVAILABLE = True
except ImportError:  # NeMo is optional when the whisper engine is used
    torch = None  # type: ignore
    nemo_asr = None  # type: ignore
    ASR_AVAILABLE = False

try:
    import transformers  # noqa: F401
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REALTIME_MODEL_ID = "typhoon-ai/typhoon-asr-realtime"
WHISPER_MODEL_ID = os.environ.get("PHARMALOG_WHISPER_MODEL", "typhoon-ai/typhoon-whisper-large-v3").strip()
DEFAULT_ENGINE = os.environ.get("PHARMALOG_STT_ENGINE", "whisper").strip().lower()
CHUNK_MAX_S = float(os.environ.get("PHARMALOG_STT_CHUNK_S", "25"))


class STTError(RuntimeError):
    """Raised when audio cannot be transcribed."""


def _hyp_text(h: Any) -> str:
    if isinstance(h, (list, tuple)):
        h = h[0] if h else ""
    if hasattr(h, "text"):
        return str(h.text or "")
    if isinstance(h, dict):
        return str(h.get("text", ""))
    return str(h or "")


def _clean(text: str) -> str:
    text = text or ""
    if "�" in text:
        text = re.sub(r"�[ัิ-ฺ็-๎]*", "", text).replace("�", "")
    # The ASR tokenizer spells SARA AM as NIKHAHIT + SARA AA ("น้ํา"); it renders the same but breaks
    # dictionary/LLM matching. Normalise to the single code point (tone mark stays before it: "น้ำ").
    if "\u0e4d" in text:
        text = re.sub("\u0e4d([\u0e48-\u0e4b]?)\u0e32", "\\1\u0e33", text)
    return re.sub(r"[ \t]+", " ", text).strip()


class TyphoonASRRecognizer:
    """Thread-safe recognizer. Name kept for backward compatibility; supports both engines."""

    def __init__(self, model_name: str = REALTIME_MODEL_ID, engine: Optional[str] = None):
        self.engine = (engine or DEFAULT_ENGINE)
        if self.engine not in ("realtime", "whisper"):
            self.engine = "whisper"
        self.model_name = WHISPER_MODEL_ID if self.engine == "whisper" else model_name
        self.model = None
        self.device = "cpu"
        self.is_loaded = False
        self.load_error = ""
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def load_model(self) -> bool:
        if self.is_loaded:
            return True
        try:
            if self.engine == "whisper":
                self._load_whisper()
            else:
                self._load_realtime()
            self.is_loaded = True
            print(f"[STT] {self.engine} engine ready on {self.device}")
            return True
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            print(f"[STT] failed to load {self.engine}: {self.load_error}")
            self.is_loaded = False
            return False

    def _load_realtime(self) -> None:
        if not ASR_AVAILABLE:
            raise STTError("NeMo ยังไม่ได้ติดตั้ง (pip install 'nemo_toolkit[asr]')")
        candidates = [
            os.path.join(ROOT_DIR, "models", "typhoon-asr-realtime.nemo"),
            os.path.join(ROOT_DIR, "pharmalog_offline_assets", "models", "typhoon-asr-realtime.nemo"),
            os.path.join(ROOT_DIR, "lab", "models", "typhoon-asr-realtime.nemo"),
        ]
        local = next((p for p in candidates if os.path.exists(p)), None)
        self.model = (nemo_asr.models.ASRModel.restore_from(local) if local
                      else nemo_asr.models.ASRModel.from_pretrained(REALTIME_MODEL_ID))
        if torch.cuda.is_available():
            self.model = self.model.cuda(); self.device = "cuda"
        elif torch.backends.mps.is_available():
            self.model = self.model.to("mps"); self.device = "mps"
        self.model.eval()

    def _load_whisper(self) -> None:
        if not WHISPER_AVAILABLE:
            raise STTError("transformers ยังไม่ได้ติดตั้ง (pip install transformers accelerate)")
        import torch as _torch
        from transformers import pipeline as hf_pipeline
        forced = os.environ.get("PHARMALOG_WHISPER_DEVICE", "").strip().lower()
        if forced == "cuda" or (not forced and _torch.cuda.is_available()):
            device, dtype = "cuda", _torch.float16
        elif forced == "mps":
            device, dtype = "mps", _torch.float32
        else:  # MPS produced garbage (fp16) / hung (fp32) in earlier lab tests -> CPU is the safe default
            device, dtype = "cpu", _torch.float32
        try:  # newer transformers renamed torch_dtype -> dtype
            self.model = hf_pipeline("automatic-speech-recognition", model=WHISPER_MODEL_ID, dtype=dtype, device=device)
        except TypeError:
            self.model = hf_pipeline("automatic-speech-recognition", model=WHISPER_MODEL_ID, torch_dtype=dtype, device=device)
        self.device = device

    # ------------------------------------------------------------------ inference
    def _run_realtime(self, chunks: List["np.ndarray"]) -> List[str]:  # noqa: F821
        import soundfile as sf
        paths = []
        try:
            for c in chunks:
                fd, p = tempfile.mkstemp(suffix=".wav"); os.close(fd)
                sf.write(p, c, 16000, subtype="PCM_16"); paths.append(p)
            try:
                out = self.model.transcribe(paths, batch_size=4, verbose=False)
            except TypeError:
                out = self.model.transcribe(paths, batch_size=4)
            if isinstance(out, tuple):  # older RNNT API: (best, all)
                out = out[0]
            return [_hyp_text(h) for h in out]
        finally:
            for p in paths:
                try: os.remove(p)
                except OSError: pass

    def _run_whisper(self, chunks) -> List[str]:
        res = self.model(
            [{"raw": c, "sampling_rate": 16000} for c in chunks],
            batch_size=2,
            generate_kwargs={"language": "th", "task": "transcribe",
                             "no_repeat_ngram_size": 4, "repetition_penalty": 1.15},
        )
        return [r.get("text", "") if isinstance(r, dict) else str(r) for r in res]

    def transcribe_detailed(self, source, apply_dictionary: bool = True) -> Dict[str, Any]:
        """source = path or bytes. Returns raw/corrected text, segments, changes and timings. Raises STTError."""
        from unified_app.modules.audio_utils import load_audio, split_on_silence, is_silent
        if not self.is_loaded or self.model is None:
            raise STTError(f"ระบบถอดเสียงยังไม่พร้อม {self.load_error}".strip())
        t0 = time.time()
        try:
            y = load_audio(source)
        except ValueError as exc:
            raise STTError(str(exc)) from exc
        duration = len(y) / 16000.0
        if duration < 0.3:
            raise STTError("ไฟล์เสียงสั้นเกินไปหรือว่างเปล่า")
        spans = split_on_silence(y, 16000, max_s=CHUNK_MAX_S)
        keep = [(a, b) for a, b in spans if not is_silent(y[a:b])]
        texts: List[str] = []
        if keep:
            with self._lock:  # one inference at a time on the shared model
                runner = self._run_whisper if self.engine == "whisper" else self._run_realtime
                texts = runner([y[a:b] for a, b in keep])
        segments = [{"start": round(a / 16000, 2), "end": round(b / 16000, 2), "text": _clean(t)}
                    for (a, b), t in zip(keep, texts)]
        raw = _clean(" ".join(s["text"] for s in segments if s["text"]))
        corrected, changes = raw, []
        if apply_dictionary and raw:
            try:
                from unified_app.modules.pharmacy_dict import correct_transcript
                corrected, changes = correct_transcript(raw)
            except Exception as exc:
                print(f"[STT] dictionary skipped: {exc}")
        return {"engine": self.engine, "model": self.model_name, "device": self.device,
                "duration_s": round(duration, 2), "elapsed_s": round(time.time() - t0, 2),
                "chunks": len(spans), "speech_chunks": len(keep), "segments": segments,
                "raw_text": raw, "text": corrected, "changes": changes}

    def transcribe_audio(self, path: str) -> str:
        """Backward compatible: returns corrected text, or an error string (old behaviour)."""
        try:
            return self.transcribe_detailed(path)["text"]
        except Exception as exc:
            return f"(เกิดข้อผิดพลาดในการถอดเสียง: {exc})"


# ---------------------------------------------------------------- backward-compatible helpers
STT_ERROR_PREFIXES = ("(ระบบถอดเสียงยังไม่พร้อม", "(เกิดข้อผิดพลาดในการถอดเสียง", "(ถอดเสียงล้มเหลว")


def is_stt_error(text: str) -> bool:
    return isinstance(text, str) and text.strip().startswith(STT_ERROR_PREFIXES)


def transcribe_audio_bytes(recognizer: TyphoonASRRecognizer, audio_bytes: bytes) -> str:
    if not audio_bytes:
        return ""
    try:
        return recognizer.transcribe_detailed(audio_bytes)["text"]
    except Exception as exc:
        return f"(ถอดเสียงล้มเหลว: {exc})"
