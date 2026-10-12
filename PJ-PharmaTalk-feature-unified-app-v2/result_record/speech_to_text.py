# -*- coding: utf-8 -*-
"""
ถอดเสียงเป็นข้อความ (speech → text)

ค่าเริ่มต้นใช้โมเดล NeMo local:
  `model_speech_to_text/typhoon-isan-asr-realtime.nemo`

  - อินพุต: `data/voice/*.wav` หรือส่ง path ไฟล์ `.wav` เป็น argv
  - ผลลัพธ์: `data/text_from_speech/<ชื่อไฟล์>.txt` (และ `session_summary.txt`)

เลือก backend:
  SPEECH_ASR_BACKEND=nemo       # ค่าเริ่มต้น
  SPEECH_ASR_BACKEND=dashscope  # ใช้ Alibaba Cloud DashScope

NeMo model path:
  NEMO_ASR_MODEL_PATH=model_speech_to_text/typhoon-isan-asr-realtime.nemo

DashScope API key: `DASHSCOPE_API_KEY` หรือไฟล์ `.dashscope_api_key` (บรรทัดเดียว)

โหมดโฟลเดอร์เดิม (sound → report):

  python speech_to_text.py --sound

ตัวแปรสภาพแวดล้อมที่เกี่ยวข้อง:
  DASHSCOPE_BASE_URL — ค่าเริ่มต้น https://dashscope-intl.aliyuncs.com/api/v1
  DASHSCOPE_CHUNK_SEC — ความยาวสูงสุดต่อชิ้น (วินาที) ค่าเริ่มต้น 240

ก่อนส่ง API จะแปลงเป็น mono 16 kHz PCM — ต้องมี numpy + soundfile

แยกผู้พูด: **pyannote/speaker-diarization-3.1** (ต้องมี torch + pyannote + HF_TOKEN)
ปิดการแยกผู้พูด: `--no-diarization` หรือ `SPEECH_DIARIZATION=0`

Windows + Streamlit: NeMo ถอดเสียงใน **subprocess แยก** อัตโนมัติ (ลดปัญหา onnx DLL ชน Streamlit)
  `SPEECH_NEMO_ISOLATED=auto` (ค่าเริ่มต้น) | `1` บังคับ | `0` ปิด
"""
from __future__ import annotations

import atexit
import base64
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GLOG_minloglevel", "2")
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

BASE = Path(__file__).resolve().parent
VOICE_DIR = (BASE / "data" / "voice").resolve()
TRANSCRIPT_DIR = (BASE / "data" / "text_from_speech").resolve()
SKIP_STT_IF_TRANSCRIPT_EXISTS = True

DASHSCOPE_KEY_FILE = BASE / ".dashscope_api_key"

DEFAULT_DASHSCOPE_BASE = "https://dashscope-intl.aliyuncs.com/api/v1"
DEFAULT_ASR_MODEL = "qwen3-asr-flash"
DASHSCOPE_MAX_CHUNK_SEC = float(os.environ.get("DASHSCOPE_CHUNK_SEC", "240"))

DEFAULT_ASR_BACKEND = "nemo"
DEFAULT_NEMO_ASR_MODEL = BASE / "model_speech_to_text" / "typhoon-isan-asr-realtime.nemo"
_NEMO_ASR: dict | None = None

_NEMO_ISOLATED_WORKER: subprocess.Popen | None = None
_NEMO_ISOLATED_LOCK = threading.Lock()


def _nemo_worker_script_path() -> Path:
    return BASE / "nemo_asr_isolated_worker.py"


def should_use_nemo_isolated_process() -> bool:
    """
    บน Windows ถ้ารันใต้ Streamlit ให้ถอดเสียง NeMo ใน subprocess แยก
    เพื่อเลี่ยง onnx_cpp2py_export DLL initialization failed (ชน DLL กับ stack อื่นใน process เดียวกัน)

    ตั้งค่า:
      SPEECH_NEMO_ISOLATED=auto|1|0   (ค่าเริ่มต้น auto)
    """
    v = (os.environ.get("SPEECH_NEMO_ISOLATED") or "auto").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    if sys.platform != "win32":
        return False
    return "streamlit" in sys.modules


def _shutdown_nemo_isolated_worker() -> None:
    global _NEMO_ISOLATED_WORKER
    proc = _NEMO_ISOLATED_WORKER
    if proc is None:
        return
    try:
        if proc.stdin:
            proc.stdin.write(json.dumps({"op": "quit"}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _NEMO_ISOLATED_WORKER = None


def _ensure_nemo_isolated_worker() -> subprocess.Popen:
    global _NEMO_ISOLATED_WORKER
    script = _nemo_worker_script_path()
    if not script.is_file():
        raise RuntimeError(
            f"ไม่พบไฟล์ worker สำหรับ NeMo แยก process: {script}\n"
            "ให้คงไฟล์ nemo_asr_isolated_worker.py ไว้ข้าง speech_to_text.py"
        )
    if _NEMO_ISOLATED_WORKER is not None and _NEMO_ISOLATED_WORKER.poll() is None:
        return _NEMO_ISOLATED_WORKER
    if _NEMO_ISOLATED_WORKER is not None:
        _shutdown_nemo_isolated_worker()

    creationkwargs: dict = {}
    if sys.platform == "win32":
        # Python 3.8+: ซ่อนหน้าต่าง console ของ worker บน Windows
        try:
            creationkwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        except AttributeError:
            pass

    _NEMO_ISOLATED_WORKER = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(BASE),
        env=os.environ.copy(),
        **creationkwargs,
    )
    return _NEMO_ISOLATED_WORKER


def _read_nemo_worker_response(proc: subprocess.Popen) -> dict:
    """อ่านบรรทัดจาก worker จนได้ JSON ที่มีฟิลด์ ok (กันข้อความ tqdm/ล็อกปน stdout)."""
    assert proc.stdout is not None
    for _ in range(8000):
        line = proc.stdout.readline()
        if not line:
            break
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "ok" in obj:
            return obj
    raise RuntimeError(
        "ไม่ได้รับ JSON ตอบจาก NeMo worker (stdout ถูกปนโดยล็อก — ลองอัปเดต worker)"
    )


def _transcribe_one_wav_bytes_nemo_isolated(wav_bytes: bytes) -> str:
    """ถอดเสียงใน subprocess — แก้ ONNX DLL บน Windows เมื่อรันคู่กับ Streamlit."""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name

        req = (
            json.dumps({"op": "transcribe", "path": tmp_path}, ensure_ascii=False)
            + "\n"
        )

        with _NEMO_ISOLATED_LOCK:
            proc = _ensure_nemo_isolated_worker()
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(req)
            proc.stdin.flush()

            if proc.poll() is not None:
                raise RuntimeError(
                    "NeMo worker process จบก่อนถอดเสียง (exit "
                    f"{proc.returncode}) — มักเกิดจากโหลด ONNX/VC++ ใน subprocess"
                )

            try:
                proc.stdout.flush()
            except Exception:
                pass

            resp = _read_nemo_worker_response(proc)
        if not resp.get("ok"):
            tb = resp.get("traceback") or ""
            err = resp.get("error") or "unknown"
            raise RuntimeError(err + (("\n" + tb) if tb else ""))
        return str(resp.get("text") or "").strip()
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


atexit.register(_shutdown_nemo_isolated_worker)

# ส่ง DashScope เป็น WAV mono 16 kHz — ขนาดชิ้นดิบไม่ควรใกล้เพดาน JSON/base64 (~10MB)
TARGET_SAMPLE_RATE_API = 16000
MAX_WAV_PAYLOAD_BYTES = 6_500_000

_DIARIZATION: dict | None = None


def get_hf_token() -> str:
    return (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    ).strip()


def patch_torchaudio_for_speechbrain(ta) -> None:
    if ta is None:
        return

    def list_audio_backends() -> list[str]:
        return ["soundfile"]

    ta.list_audio_backends = list_audio_backends  # type: ignore[method-assign]


def load_diarization_models() -> dict:
    global _DIARIZATION
    if _DIARIZATION is not None:
        return _DIARIZATION

    try:
        import torch
        import torchaudio
    except ImportError as e:
        raise RuntimeError(f"ติดตั้ง torch/torchaudio สำหรับแยกผู้พูด: pip install torch torchaudio\n{e}") from e

    patch_torchaudio_for_speechbrain(torchaudio)

    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise RuntimeError(f"ติดตั้ง pyannote.audio สำหรับแยกผู้พูด\n{e}") from e

    tok = get_hf_token()
    if not tok:
        raise RuntimeError("ไม่มี HF_TOKEN / HUGGING_FACE_TOKEN สำหรับดาวน์โหลดโมเดล pyannote")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=tok,
        )
    except TypeError as e:
        if "token" not in str(e):
            raise
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=tok,
        )
    pipeline.to(device)

    _DIARIZATION = {"pipeline": pipeline, "device": device, "torch": torch}
    print(f"   🎚️ โหลด pyannote speaker-diarization บน {device}")
    return _DIARIZATION


def diarization_enabled() -> bool:
    v = os.environ.get("SPEECH_DIARIZATION", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def argv_no_diarization() -> bool:
    return "--no-diarization" in sys.argv


def get_asr_backend() -> str:
    if "--nemo" in sys.argv:
        return "nemo"
    if "--dashscope" in sys.argv:
        return "dashscope"
    backend = (os.environ.get("SPEECH_ASR_BACKEND") or DEFAULT_ASR_BACKEND).strip().lower()
    if backend not in ("nemo", "dashscope"):
        raise SystemExit("SPEECH_ASR_BACKEND ต้องเป็น 'nemo' หรือ 'dashscope'")
    return backend


def get_nemo_model_path() -> Path:
    raw = (os.environ.get("NEMO_ASR_MODEL_PATH") or "").strip()
    p = Path(raw) if raw else DEFAULT_NEMO_ASR_MODEL
    if not p.is_absolute():
        p = (BASE / p).resolve()
    return p


def get_runtime_patched_nemo_path(model_path: Path) -> Path:
    """
    NeMo บางรุ่นไม่ยอมโหลด config ที่มีทั้ง durations: [] และ
    big_blank_durations: [] จึงสร้างสำเนา .nemo สำหรับ runtime โดยตั้งเป็น null
    โดยไม่แก้ไฟล์โมเดลต้นฉบับ
    """
    patched_path = model_path.with_name(f"{model_path.stem}.runtime_patched{model_path.suffix}")
    if patched_path.is_file() and patched_path.stat().st_mtime >= model_path.stat().st_mtime:
        return patched_path

    with tarfile.open(model_path, "r:*") as src, tarfile.open(patched_path, "w:gz") as dst:
        for member in src.getmembers():
            file_obj = src.extractfile(member) if member.isfile() else None
            data = file_obj.read() if file_obj is not None else None
            if member.name.endswith("model_config.yaml") and data is not None:
                text = data.decode("utf-8", errors="replace")
                text = text.replace(
                    "  durations: []\n  big_blank_durations: []",
                    "  durations: null\n  big_blank_durations: null",
                )
                text = re.sub(r"^\s*tdt_[A-Za-z0-9_]+:.*\n", "", text, flags=re.MULTILINE)
                data = text.encode("utf-8")
                member.size = len(data)
            if data is None:
                dst.addfile(member)
            else:
                dst.addfile(member, io.BytesIO(data))
    return patched_path


def load_nemo_asr_model() -> dict:
    global _NEMO_ASR
    if _NEMO_ASR is not None:
        return _NEMO_ASR

    model_path = get_nemo_model_path()
    if not model_path.is_file():
        raise RuntimeError(
            f"ไม่พบโมเดล NeMo: {model_path}\n"
            "ให้วางไฟล์ .nemo ตาม path นี้ หรือกำหนด NEMO_ASR_MODEL_PATH"
        )

    try:
        try:
            import onnx  # noqa: F401
            import onnx.onnx_cpp2py_export  # noqa: F401
        except Exception:
            pass
        import torch
        from nemo.collections.asr import models as nemo_asr_models
    except ImportError as e:
        detail = str(e)
        if "onnx_cpp2py_export" in detail or "DLL load failed" in detail:
            raise RuntimeError(
                "NeMo ASR import แล้วติด ONNX (.pyd) / DLL บน Windows\n"
                "สาเหตุที่พบบ่อย:\n"
                "  • ไม่ครบ Visual C++ Redistributable x64 — ติดตั้งจาก Microsoft\n"
                "  • ไฟล์ onnx จาก pip เสียหาย — reinstall: python -m pip install --force-reinstall onnx==1.17.0\n"
                "  • ลำดับโหลด DLL ชนเมื่อรัน Streamlit+pyannote ใน process เดียวกัน — "
                "แอปจะใช้ subprocess แยกอัตโนมัติเมื่อรันใต้ Streamlit (SPEECH_NEMO_ISOLATED=auto)\n"
                "ถ้ารัน CLI แล้วยัง error ลอง: set SPEECH_NEMO_ISOLATED=1\n"
                f"{e}"
            ) from e
        raise RuntimeError(
            "ต้องติดตั้ง NeMo ASR ก่อนใช้งานโมเดล .nemo:\n"
            "  python -m pip install nemo_toolkit[asr]\n"
            f"{e}"
        ) from e

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = None
    errors: list[str] = []
    candidate_class_names = [
        "ASRModel",
        "EncDecCTCModelBPE",
        "EncDecCTCModel",
        "EncDecRNNTBPEModel",
        "EncDecRNNTModel",
        "EncDecHybridRNNTCTCBPEModel",
        "EncDecHybridRNNTCTCModel",
    ]
    restore_paths = [model_path]
    patched_path = get_runtime_patched_nemo_path(model_path)
    if patched_path != model_path:
        restore_paths.append(patched_path)

    for restore_path in restore_paths:
        for class_name in candidate_class_names:
            cls = getattr(nemo_asr_models, class_name, None)
            if cls is None:
                continue
            try:
                model = cls.restore_from(str(restore_path), map_location=device)
                model_path = restore_path
                break
            except Exception as e:
                errors.append(f"{restore_path.name} / {class_name}: {e}")
        if model is not None:
            break
    if model is None:
        detail = "\n".join(errors[-4:])
        raise RuntimeError(f"โหลดโมเดล NeMo ไม่สำเร็จ: {model_path}\n{detail}")
    model.eval()
    try:
        model = model.to(device)
    except Exception:
        pass

    _NEMO_ASR = {"model": model, "device": device, "path": model_path}
    print(f"   🎙️ โหลด NeMo ASR: {model_path.name} บน {device}")
    return _NEMO_ASR


def _speaker_display_name(speaker: str, speaker_offset: int) -> str:
    try:
        parts = speaker.split("_")
        if len(parts) > 1:
            speaker_id = int(parts[-1]) + 1 + speaker_offset
        else:
            match = re.search(r"\d+", speaker)
            speaker_id = (
                int(match.group()) + 1 + speaker_offset if match else speaker
            )
        return f"ผู้พูด {speaker_id}"
    except Exception:
        return str(speaker)


def _ensure_numpy():
    try:
        import numpy as np

        return np
    except ImportError:
        raise SystemExit(
            "ต้องการ numpy สำหรับรีแซมเปิลเสียง: python -m pip install numpy"
        ) from None


def _load_mono_resampled(path: Path):
    """โหลด WAV → mono float32 @ TARGET_SAMPLE_RATE_API"""
    import soundfile as sf

    np = _ensure_numpy()
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if data.shape[1] >= 2:
        mono = np.mean(data, axis=1).astype(np.float32)
    else:
        mono = data[:, 0].astype(np.float32)
    if sr == TARGET_SAMPLE_RATE_API:
        return mono
    ratio = TARGET_SAMPLE_RATE_API / sr
    n_out = max(1, int(round(len(mono) * ratio)))
    old_x = np.arange(len(mono), dtype=np.float64)
    new_x = np.linspace(0.0, len(mono) - 1.0, num=n_out)
    mono = np.interp(new_x, old_x, mono.astype(np.float64)).astype(np.float32)
    return mono


def _mono_to_wav_bytes(mono_seg, sr: int = TARGET_SAMPLE_RATE_API) -> bytes:
    import soundfile as sf

    np = _ensure_numpy()
    mono_seg = np.clip(mono_seg, -1.0, 1.0)
    buf = io.BytesIO()
    sf.write(buf, mono_seg, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _mono_to_api_chunks(
    mono, max_sec: float
) -> tuple[list[tuple[bytes, float, float]], float]:
    """แบ่งชิ้นเป็น WAV mono 16 kHz; t เป็นเวลาจริงในไฟล์"""
    sr = TARGET_SAMPLE_RATE_API
    n = len(mono)
    duration = n / sr
    max_samples = max(int(max_sec * sr), int(5 * sr))
    min_samples = int(5 * sr)
    out: list[tuple[bytes, float, float]] = []
    i = 0
    while i < n:
        j = min(i + max_samples, n)
        seg = mono[i:j]
        wav_b = _mono_to_wav_bytes(seg)
        while len(wav_b) > MAX_WAV_PAYLOAD_BYTES and j - i > min_samples:
            j = i + max((j - i) // 2, min_samples)
            seg = mono[i:j]
            wav_b = _mono_to_wav_bytes(seg)
        if len(wav_b) > MAX_WAV_PAYLOAD_BYTES:
            raise RuntimeError(
                "ชิ้นเสียงยังใหญ่เกินหลังแบ่งย่อย — ลดบิตเรตต้นทางหรือตั้ง DASHSCOPE_CHUNK_SEC เล็กลง"
            )
        out.append((wav_b, i / sr, j / sr))
        i = j
    return out, duration


def _mono_span_to_api_chunks(mono_seg, sr: int, t_abs_start: float) -> list[tuple[bytes, float, float]]:
    """แบ่งช่วงย่อยของ mono (numpy) ให้พอใส่ payload; เวลาเป็นจริงในไฟล์เต็ม"""
    min_samples = int(5 * sr)
    max_samples = max(int(DASHSCOPE_MAX_CHUNK_SEC * sr), min_samples)
    n = len(mono_seg)
    out: list[tuple[bytes, float, float]] = []
    i = 0
    while i < n:
        j = min(i + max_samples, n)
        seg = mono_seg[i:j]
        wav_b = _mono_to_wav_bytes(seg)
        ta = t_abs_start + i / sr
        tb = t_abs_start + j / sr
        while len(wav_b) > MAX_WAV_PAYLOAD_BYTES and j - i > min_samples:
            j = i + max((j - i) // 2, min_samples)
            seg = mono_seg[i:j]
            wav_b = _mono_to_wav_bytes(seg)
            tb = t_abs_start + j / sr
        if len(wav_b) > MAX_WAV_PAYLOAD_BYTES:
            raise RuntimeError("ช่วงผู้พูดยาวเกินหลังแบ่งย่อย — ลด DASHSCOPE_CHUNK_SEC")
        out.append((wav_b, ta, tb))
        i = j
    return out


def _wav_file_to_api_chunks(
    path: Path, max_sec: float
) -> tuple[list[tuple[bytes, float, float]], float]:
    mono = _load_mono_resampled(path)
    return _mono_to_api_chunks(mono, max_sec)


def _transcribe_mono_with_diarization(
    mono,
    *,
    sr: int,
    duration: float,
    chunk_duration_sec: float,
    backend: str,
    model: str,
    api_key: str | None,
    base: str | None,
    verbose: bool,
) -> tuple[list[str], float, dict]:
    dip = load_diarization_models()
    pipeline = dip["pipeline"]
    device = dip["device"]
    torch = dip["torch"]

    wav = torch.from_numpy(mono.copy()).unsqueeze(0).float()
    dip_win_sec = float(os.environ.get("DIARIZATION_CHUNK_SEC", "180"))

    log_lines: list[str] = []
    t_all0 = time.perf_counter()
    all_speaker_count = 0
    api_calls = 0
    win_idx = 0

    win_start_sec = 0.0
    while win_start_sec < duration - 1e-6:
        win_end_sec = min(win_start_sec + dip_win_sec, duration)
        i0 = int(win_start_sec * sr)
        i1 = int(win_end_sec * sr)
        chunk_wav = wav[:, i0:i1].to(device)
        win_idx += 1
        if verbose:
            print(
                f"   🎤 ช่วง diarization {win_idx}: {win_start_sec / 60:.1f}-{win_end_sec / 60:.1f} นาที"
            )

        audio_in_chunk = {"waveform": chunk_wav, "sample_rate": sr}
        diarization = pipeline(audio_in_chunk, min_speakers=1, max_speakers=5)
        ann = getattr(diarization, "speaker_diarization", diarization)
        n_spk_chunk = len(ann.labels())
        speaker_offset = all_speaker_count
        all_speaker_count += n_spk_chunk
        if verbose:
            print(f"      พบ {n_spk_chunk} ป้ายผู้พูดในช่วงนี้")

        turns = sorted(ann.itertracks(yield_label=True), key=lambda x: x[0].start)

        for turn, _, speaker in turns:
            local_start = turn.start
            local_end = turn.end
            if local_end - local_start < 0.1:
                continue
            global_start = win_start_sec + local_start
            global_end = win_start_sec + local_end
            sp_label = _speaker_display_name(speaker, speaker_offset)

            s0 = int(global_start * sr)
            s1 = int(global_end * sr)
            seg_np = mono[s0:s1]
            parts = _mono_span_to_api_chunks(seg_np, sr, global_start)
            for wav_b, ta, tb in parts:
                api_calls += 1
                if verbose:
                    print(
                        f"      📌 {ta:.1f}s-{tb:.1f}s → {backend_label(backend, model)} [{sp_label}]..."
                    )
                text = _transcribe_one_wav_bytes_dispatch(
                    wav_b,
                    backend=backend,
                    model=model,
                    api_key=api_key,
                    base=base,
                )
                display = text if text else "(ไม่มีข้อความ)"
                line = f"[ {ta:4.1f}s-{tb:4.1f}s ] {sp_label} : {display}"
                if verbose:
                    print(line)
                    print("-" * 40)
                log_lines.append(line)

        win_start_sec = win_end_sec
        del chunk_wav
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    elapsed = time.perf_counter() - t_all0
    meta = {
        "audio_duration": duration,
        "num_speakers": all_speaker_count,
        "num_chunks": api_calls,
        "asr_backend": backend,
        "asr_model": model,
    }
    return log_lines, elapsed, meta


def get_dashscope_api_key() -> str:
    k = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if k:
        return k
    if DASHSCOPE_KEY_FILE.is_file():
        try:
            for line in DASHSCOPE_KEY_FILE.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    return s
        except OSError:
            pass
    return ""


def get_dashscope_base_url() -> str:
    return (os.environ.get("DASHSCOPE_BASE_URL") or DEFAULT_DASHSCOPE_BASE).rstrip("/")


def get_asr_model_name() -> str:
    return (os.environ.get("DASHSCOPE_ASR_MODEL") or DEFAULT_ASR_MODEL).strip()


def backend_label(backend: str, model: str) -> str:
    if backend == "nemo":
        return f"NeMo ({model})"
    return f"DashScope ({model})"


def _wav_bytes_to_data_uri(wav_bytes: bytes) -> str:
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    return f"data:audio/wav;base64,{b64}"


def _dashscope_post_json(url: str, api_key: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DashScope HTTP {e.code}: {err[:1200]}") from e


def _parse_multimodal_asr_response(obj: dict) -> str:
    if obj.get("code"):
        raise RuntimeError(
            f"DashScope error: {obj.get('code')} — {obj.get('message', obj)}"[:800]
        )
    output = obj.get("output") or {}
    choices = output.get("choices") or []
    if not choices:
        raise RuntimeError(f"คำตอบไม่มี choices: {json.dumps(obj, ensure_ascii=False)[:600]}")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                texts.append(str(part["text"]).strip())
        return "\n".join(t for t in texts if t).strip()
    if isinstance(content, str):
        return content.strip()
    return (str(content) if content is not None else "").strip()


def _transcribe_one_wav_bytes(wav_bytes: bytes, *, model: str, api_key: str, base: str) -> str:
    if len(wav_bytes) > MAX_WAV_PAYLOAD_BYTES + 500_000:
        raise RuntimeError(
            "ชิ้น WAV ยังใหญ่เกินเพดาน DashScope — ควรไม่เกิดหลังแปลง mono 16 kHz"
        )
    url = f"{base}/services/aigc/multimodal-generation/generation"
    uri = _wav_bytes_to_data_uri(wav_bytes)
    payload = {
        "model": model,
        "input": {
            "messages": [
                {"role": "system", "content": [{"text": ""}]},
                {"role": "user", "content": [{"audio": uri}]},
            ]
        },
        "parameters": {
            "asr_options": {
                "enable_itn": True,
            }
        },
    }
    data = _dashscope_post_json(url, api_key, payload)
    return _parse_multimodal_asr_response(data)


def _asr_text_from_nemo_output(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if hasattr(value, "text"):
        return str(value.text).strip()
    if isinstance(value, (list, tuple)) and value:
        return _asr_text_from_nemo_output(value[0])
    return (str(value) if value is not None else "").strip()


def _transcribe_one_wav_bytes_nemo(wav_bytes: bytes) -> str:
    if should_use_nemo_isolated_process():
        return _transcribe_one_wav_bytes_nemo_isolated(wav_bytes)

    asr = load_nemo_asr_model()
    model = asr["model"]

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name

        # NeMo หลายเวอร์ชันใช้ signature ต่างกัน จึงลองแบบใหม่ก่อนแล้วค่อย fallback
        try:
            out = model.transcribe([tmp_path], batch_size=1, return_hypotheses=False)
        except TypeError:
            out = model.transcribe(paths2audio_files=[tmp_path], batch_size=1)
        return _asr_text_from_nemo_output(out)
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _transcribe_one_wav_bytes_dispatch(
    wav_bytes: bytes,
    *,
    backend: str,
    model: str,
    api_key: str | None,
    base: str | None,
) -> str:
    if backend == "nemo":
        return _transcribe_one_wav_bytes_nemo(wav_bytes)
    if not api_key or not base:
        raise RuntimeError("DashScope ต้องมี api_key และ base")
    return _transcribe_one_wav_bytes(wav_bytes, model=model, api_key=api_key, base=base)


def transcribe_wav_to_log_lines(
    wav_path: str | Path,
    *,
    chunk_duration_sec: float = DASHSCOPE_MAX_CHUNK_SEC,
    verbose: bool = True,
) -> tuple[list[str], float, dict]:
    """ถอดเสียงทั้งไฟล์ → บรรทัด [เวลา] ผู้พูด N : ข้อความ (มีแยกผู้พูดด้วย pyannote ได้)"""
    wav_path = Path(wav_path)
    if not wav_path.is_file():
        raise FileNotFoundError(wav_path)

    backend = get_asr_backend()
    if backend == "nemo":
        model = get_nemo_model_path().name
        api_key = None
        base = None
    else:
        api_key = get_dashscope_api_key()
        if not api_key:
            raise SystemExit("ไม่มี DASHSCOPE_API_KEY — ตั้ง env หรือสร้างไฟล์ .dashscope_api_key")
        model = get_asr_model_name()
        base = get_dashscope_base_url()

    try:
        mono = _load_mono_resampled(wav_path)
    except ImportError as e:
        raise SystemExit(
            "ต้องติดตั้ง soundfile / numpy เพื่อประมวลผลเสียง:\n"
            "  python -m pip install soundfile numpy\n" + str(e)
        ) from e

    sr = TARGET_SAMPLE_RATE_API
    duration = len(mono) / sr

    if diarization_enabled() and not argv_no_diarization():
        try:
            return _transcribe_mono_with_diarization(
                mono,
                sr=sr,
                duration=duration,
                chunk_duration_sec=chunk_duration_sec,
                backend=backend,
                model=model,
                api_key=api_key,
                base=base,
                verbose=verbose,
            )
        except Exception as e:
            if verbose:
                print(
                    f"   ⚠️ แยกผู้พูดไม่ได้ ({e}) — ใช้โหมดไม่แยกผู้พูด\n"
                )

    t0 = time.perf_counter()
    chunks, audio_duration_tracked = _mono_to_api_chunks(mono, chunk_duration_sec)

    log_lines: list[str] = []
    for idx, (wav_bytes, ts, te) in enumerate(chunks, start=1):
        if verbose:
            print(
                f"   📌 ช่วงที่ {idx}: {ts / 60:.1f}-{te / 60:.1f} นาที ({te - ts:.1f}s) → {backend_label(backend, model)}..."
            )
        text = _transcribe_one_wav_bytes_dispatch(
            wav_bytes,
            backend=backend,
            model=model,
            api_key=api_key,
            base=base,
        )
        display = text if text else "(ไม่มีข้อความ)"
        line = f"[ {ts:4.1f}s-{te:4.1f}s ] ผู้พูด 1 : {display}"
        if verbose:
            print(line)
            print("-" * 40)
        log_lines.append(line)

    elapsed = time.perf_counter() - t0
    meta = {
        "audio_duration": audio_duration_tracked,
        "num_speakers": 1,
        "num_chunks": len(chunks),
        "asr_backend": backend,
        "asr_model": model,
    }
    return log_lines, elapsed, meta


def run_sound_folder_legacy() -> None:
    """ถอดความ: BASE/sound/*.wav → BASE/report/<stem>.txt + summary_report.txt"""
    audio_dir = BASE / "sound"
    report_dir = BASE / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    if not audio_dir.is_dir():
        print(f"❌ ไม่พบโฟลเดอร์ {audio_dir}")
        sys.exit(1)

    audio_files = sorted(f for f in audio_dir.iterdir() if f.suffix.lower() == ".wav")
    if not audio_files:
        print(f"❌ ไม่พบไฟล์ .wav ในโฟลเดอร์ {audio_dir}")
        sys.exit(1)

    skip_if_exists = True
    report_file = report_dir / "summary_report.txt"
    header = (
        "ไฟล์เสียง\tจำนวนผู้พูด\tความยาว(s)\tเวลาที่ใช้ดำเนินการ\tความเร็วในการดำเนินการ\n"
    )
    if not skip_if_exists or not report_file.is_file():
        report_file.write_text(header, encoding="utf-8")

    num_processed = num_skipped = num_failed = 0
    print(f"🔍 พบไฟล์เสียงทั้งหมด {len(audio_files)} ไฟล์ ในโฟลเดอร์ {audio_dir}")
    print(f"   ({'ข้ามไฟล์ที่มี report แล้ว' if skip_if_exists else 'ประมวลผลทุกไฟล์ใหม่'})\n")

    for audio_path in audio_files:
        report_txt_path = report_dir / f"{audio_path.stem}.txt"
        if skip_if_exists and report_txt_path.is_file():
            print(f"⏭️ ข้าม (มี report แล้ว): {audio_path.name}")
            num_skipped += 1
            continue

        print(f"\n{'=' * 80}")
        print(f"📂 กำลังประมวลผล: {audio_path.name}")
        print(f"{'=' * 80}")

        try:
            log_lines, elapsed_time, meta = transcribe_wav_to_log_lines(
                audio_path, verbose=True
            )
            audio_duration = meta["audio_duration"]
            num_speakers = meta["num_speakers"]
            rtf = audio_duration / elapsed_time if elapsed_time > 0 else 0.0

            print("-" * 40)
            print(f"📊 สรุป: {audio_path.name}")
            print(
                f"ผู้พูด: {num_speakers} | ยาว: {audio_duration:.2f}s | "
                f"ใช้เวลา: {elapsed_time:.2f}s | RTF: {rtf:.2f}x"
            )

            summary_line = (
                f"{audio_path.name}\t{num_speakers}\t{audio_duration:.2f}\t"
                f"{elapsed_time:.2f}\t{rtf:.2f}x"
            )
            with open(report_file, "a", encoding="utf-8") as f:
                f.write(summary_line + "\n")

            text_out = "\n".join(log_lines)
            if log_lines:
                text_out += "\n"
            report_txt_path.write_text(text_out, encoding="utf-8")
            num_processed += 1
        except Exception as e:
            num_failed += 1
            print(f"❌ เกิดข้อผิดพลาดกับไฟล์ {audio_path.name}: {e}")

    print(f"\n{'=' * 80}")
    print(f"✅ เสร็จสิ้น — ไฟล์ในโฟลเดอร์ {audio_dir.name}: {len(audio_files)} ไฟล์")
    print(
        f"   ประมวลผลใหม่: {num_processed} | ข้าม (มี report แล้ว): {num_skipped} | ผิดพลาด: {num_failed}"
    )
    print(f"   ตรวจสอบ Report ได้ที่: {report_file}")
    print(f"{'=' * 80}")


def _write_transcript(transcript_path: Path, log_lines: list[str]) -> None:
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    text_out = "\n".join(log_lines)
    if log_lines:
        text_out += "\n"
    transcript_path.write_text(text_out, encoding="utf-8")


def append_session_summary(
    *,
    source_desc: str,
    n_ok: int,
    n_skip: int,
    n_fail: int,
    wall_sec: float,
) -> None:
    path = (TRANSCRIPT_DIR / "session_summary.txt").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    block = "\n".join(
        [
            f"=== session {datetime.now().isoformat(timespec='seconds')} ===",
            f"อินพุต: {source_desc}",
            f"สำเร็จ: {n_ok} | ข้าม (มี transcript): {n_skip} | ผิดพลาด: {n_fail}",
            f"เวลารวม (วินาที): {wall_sec:.2f}",
            "",
        ]
    )
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(block)


def main() -> None:
    if "--sound" in sys.argv[1:]:
        run_sound_folder_legacy()
        return

    wav_paths: list[Path] = []
    for a in sys.argv[1:]:
        if a.startswith("-"):
            if a in ("--no-diarization", "--nemo", "--dashscope"):
                continue
            if a in ("--help", "-h"):
                print(
                    "python speech_to_text.py              # data/voice/*.wav\n"
                    "python speech_to_text.py file.wav\n"
                    "python speech_to_text.py file.wav --nemo       # ใช้ local NeMo .nemo\n"
                    "python speech_to_text.py file.wav --dashscope  # ใช้ DashScope API\n"
                    "python speech_to_text.py file.wav --no-diarization\n"
                    "python speech_to_text.py --sound      # sound/*.wav → report/\n"
                    f"SPEECH_ASR_BACKEND=nemo|dashscope (default {DEFAULT_ASR_BACKEND}); "
                    f"NEMO_ASR_MODEL_PATH (default {DEFAULT_NEMO_ASR_MODEL})\n"
                    f"DASHSCOPE_ASR_MODEL (default {DEFAULT_ASR_MODEL}), DASHSCOPE_API_KEY, "
                    f"DASHSCOPE_BASE_URL ({DEFAULT_DASHSCOPE_BASE}); "
                    "SPEECH_DIARIZATION=0 หรือ --no-diarization = ไม่แยกผู้พูด"
                )
                sys.exit(0)
            print(f"ไม่รู้จักอาร์กิวเมนต์: {a}")
            sys.exit(1)
        p = Path(a).resolve()
        if p.is_file() and p.suffix.lower() == ".wav":
            wav_paths.append(p)
        else:
            print(f"ไม่พบไฟล์ .wav: {a}")
            sys.exit(1)

    if len(wav_paths) > 1:
        print("ระบุได้ทีละหนึ่งไฟล์ .wav")
        sys.exit(1)

    if wav_paths:
        wav_files = wav_paths
        source_desc = str(wav_paths[0])
    else:
        if not VOICE_DIR.is_dir():
            print(f"ไม่พบโฟลเดอร์ {VOICE_DIR}")
            print("ใส่ไฟล์ .wav ใน data/voice หรือส่ง path ไฟล์ argv")
            sys.exit(1)
        wav_files = sorted(VOICE_DIR.glob("*.wav"))
        source_desc = str(VOICE_DIR)

    if not wav_files:
        print(f"ไม่พบไฟล์ .wav ใน {source_desc}")
        sys.exit(1)

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    backend = get_asr_backend()
    if backend == "nemo":
        model_desc = str(get_nemo_model_path())
        base_desc = "local"
    else:
        model_desc = get_asr_model_name()
        base_desc = get_dashscope_base_url()
    print(
        f"--- speech → text ({backend}) ---\n"
        f"โมเดล: {model_desc} | base: {base_desc}\n"
        f"อินพุต: {source_desc}\n"
        f"transcript: {TRANSCRIPT_DIR}\n"
    )

    t0 = time.perf_counter()
    n_ok = n_skip = n_fail = 0

    for idx, wav_path in enumerate(wav_files, start=1):
        transcript_path = TRANSCRIPT_DIR / f"{wav_path.stem}.txt"
        print(f"=== [{idx}/{len(wav_files)}] {wav_path.name} ===")

        if SKIP_STT_IF_TRANSCRIPT_EXISTS and transcript_path.is_file():
            print(f"   ข้าม (มี transcript แล้ว): {transcript_path.name}\n")
            n_skip += 1
            continue

        try:
            log_lines, elapsed, meta = transcribe_wav_to_log_lines(
                wav_path, verbose=True
            )
            _write_transcript(transcript_path, log_lines)
            ad = meta["audio_duration"]
            rtf = ad / elapsed if elapsed > 0 else 0.0
            print(
                f"   บันทึก: {transcript_path} ({ad:.1f}s เสียง, {elapsed:.1f}s ประมวลผล, RTF ~{rtf:.2f}x)\n"
            )
            n_ok += 1
        except SystemExit:
            raise
        except Exception as e:
            n_fail += 1
            err = str(e).replace("\n", " ")[:400]
            print(f"[ข้าม] {wav_path.name}: {err}\n")

    append_session_summary(
        source_desc=source_desc,
        n_ok=n_ok,
        n_skip=n_skip,
        n_fail=n_fail,
        wall_sec=time.perf_counter() - t0,
    )
    print("--- สรุป ---")
    print(f"  สำเร็จ: {n_ok} | ข้าม: {n_skip} | ผิดพลาด: {n_fail}")
    print(f"  สรุปรอบรัน: {TRANSCRIPT_DIR / 'session_summary.txt'}")


if __name__ == "__main__":
    main()
