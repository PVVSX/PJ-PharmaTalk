# -*- coding: utf-8 -*-
"""
EvalLab Pipeline Engine
Handles multi-model STT, Pharmacy Dictionary correction,
Speaker Role Identification, and Dialogue Turn Formatting with local caching.
"""

from __future__ import annotations

import os
import sys
import json
import re
import time
import hashlib
import tempfile
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

CACHE_DIR = APP_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Import Domain Modules (Standalone) ──
try:
    from modules.pharmacy_dict import correct_transcript
except ImportError:
    try:
        from pharmacy_dict import correct_transcript
    except ImportError:
        def correct_transcript(text: str):
            return text, []

try:
    from modules.emr_groq import extract_emr, EMR_FIELDS
except ImportError:
    try:
        from emr_groq import extract_emr, EMR_FIELDS
    except ImportError:
        def extract_emr(conversation: str):
            return {
                "บทสนทนาที่จัดเรียงแล้ว": conversation,
                "ประวัติการแพ้ยา": "-",
                "โรคประจำตัว": "-",
                "ประวัติการจ่ายยา": "-",
                "บันทึกทางการแพทย์": "-",
                "คำแนะนำจากเภสัช": "-",
            }
        EMR_FIELDS = [
            "บทสนทนาที่จัดเรียงแล้ว",
            "ประวัติการแพ้ยา",
            "โรคประจำตัว",
            "ประวัติการจ่ายยา",
            "บันทึกทางการแพทย์",
            "คำแนะนำจากเภสัช",
        ]

# ── Groq API Client ──
def get_groq_api_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        candidates = [
            APP_DIR / ".groq_api_key",
            APP_DIR.parent / ".groq_api_key",
            APP_DIR / "pharmalog_offline_assets" / ".groq_api_key",
            APP_DIR / "pharmalog_offline_assets" / "api_keys" / ".groq_api_key",
            APP_DIR.parent / "pharmalog_offline_assets" / ".groq_api_key",
            APP_DIR.parent / "pharmalog_offline_assets" / "api_keys" / ".groq_api_key",
        ]
        for p in candidates:
            if p.exists():
                key = p.read_text(encoding="utf-8").strip()
                if key:
                    break
    return key

# ── Typhoon ASR Singleton ──
_typhoon_model = None

def get_typhoon_recognizer():
    global _typhoon_model
    if _typhoon_model is not None and getattr(_typhoon_model, "is_loaded", False):
        return _typhoon_model

    try:
        import nemo.collections.asr as nemo_asr
        import torch

        class LocalTyphoon:
            def __init__(self):
                self.model = None
                self.is_loaded = False

            def load(self):
                candidate_paths = [
                    APP_DIR / "models" / "typhoon-asr-realtime.nemo",
                    APP_DIR.parent / "STT_Bundle_With_Model" / "models" / "typhoon-asr-realtime.nemo",
                    APP_DIR.parent / "models" / "typhoon-asr-realtime.nemo",
                ]
                local_path = None
                for p in candidate_paths:
                    if p.exists():
                        local_path = str(p)
                        break

                if local_path:
                    self.model = nemo_asr.models.ASRModel.restore_from(local_path)
                else:
                    self.model = nemo_asr.models.ASRModel.from_pretrained("typhoon-ai/typhoon-asr-realtime")

                if torch.cuda.is_available():
                    self.model = self.model.cuda()
                elif torch.backends.mps.is_available():
                    self.model = self.model.to("mps")
                self.model.eval()
                self.is_loaded = True
                return True

            def transcribe(self, wav_path: str) -> str:
                if not self.is_loaded or self.model is None:
                    return ""
                res = self.model.transcribe([wav_path], verbose=False)
                if res and len(res) > 0:
                    item = res[0]
                    if isinstance(item, (list, tuple)):
                        item = item[0]
                    if hasattr(item, "text"):
                        return str(item.text).strip()
                    elif isinstance(item, dict) and "text" in item:
                        return str(item["text"]).strip()
                    return str(item).strip()
                return ""

        inst = LocalTyphoon()
        inst.load()
        _typhoon_model = inst
        return _typhoon_model
    except Exception as e:
        print(f"Failed to load Typhoon ASR: {e}")
        return None


def fix_broken_stdio() -> None:
    for fd, stream_name in [(1, "stdout"), (2, "stderr")]:
        try:
            os.write(fd, b"")
        except OSError as e:
            if getattr(e, "errno", None) == 5:
                try:
                    devnull = os.open(os.devnull, os.O_RDWR)
                    os.dup2(devnull, fd)
                    os.close(devnull)
                    setattr(sys, stream_name, open(os.devnull, "w"))
                except Exception:
                    pass


# ── Audio Preprocessing: Silence Compression ──
def compress_long_silences(
    audio_bytes: bytes,
    min_silence_dur: float = 1.2,
    keep_silence_dur: float = 0.4,
    top_db: float = 24.0,
) -> Tuple[bytes, float]:
    """
    Detects prolonged silence gaps (> min_silence_dur) and compresses them down to keep_silence_dur.
    Preserves natural short speech pauses (< min_silence_dur) so speech cadence is unchanged.
    Returns: (cleaned_audio_bytes_wav_16khz, seconds_of_dead_silence_removed)
    """
    try:
        import io
        import soundfile as sf
        import librosa
        import numpy as np

        with io.BytesIO(audio_bytes) as bio:
            y, sr = sf.read(bio)

        if y.ndim > 1:
            y = np.mean(y, axis=1)

        if sr != 16000:
            y = librosa.resample(y, orig_sr=sr, target_sr=16000)
            sr = 16000

        total_dur = len(y) / sr
        if total_dur < 10.0:
            return audio_bytes, 0.0

        intervals = librosa.effects.split(y, top_db=top_db, frame_length=2048, hop_length=512)
        if len(intervals) <= 1:
            return audio_bytes, 0.0

        kept_parts = []
        min_silence_samples = int(min_silence_dur * sr)
        keep_silence_samples = int(keep_silence_dur * sr)
        silence_dropped = 0

        kept_parts.append(y[intervals[0][0]:intervals[0][1]])

        for i in range(1, len(intervals)):
            prev_end = intervals[i - 1][1]
            curr_start = intervals[i][0]
            gap_samples = curr_start - prev_end

            if gap_samples > min_silence_samples:
                compressed_pause = np.zeros(keep_silence_samples, dtype=y.dtype)
                kept_parts.append(compressed_pause)
                silence_dropped += (gap_samples - keep_silence_samples)
            elif gap_samples > 0:
                kept_parts.append(y[prev_end:curr_start])

            kept_parts.append(y[intervals[i][0]:intervals[i][1]])

        if silence_dropped <= 0:
            return audio_bytes, 0.0

        y_out = np.concatenate(kept_parts)
        out_buf = io.BytesIO()
        sf.write(out_buf, y_out, sr, format="WAV", subtype="PCM_16")
        return out_buf.getvalue(), round(silence_dropped / sr, 2)
    except Exception as exc:
        print(f"Warning: silence compression bypassed: {exc}")
        return audio_bytes, 0.0


# ── Transcribe Functions ──
def run_raw_typhoon(audio_bytes: bytes) -> Tuple[str, float]:
    fix_broken_stdio()
    recognizer = get_typhoon_recognizer()
    if not recognizer:
        return "(ไม่สามารถโหลดโมเดล Typhoon ASR ได้ในเครื่องนี้)", 0.0

    # Compress prolonged dead silences to prevent sluggish execution
    clean_bytes, _ = compress_long_silences(audio_bytes)

    tmp_path = None
    start = time.time()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(clean_bytes)
            tmp_path = tmp.name
        fix_broken_stdio()
        text = recognizer.transcribe(tmp_path)
        if text and "\ufffd" in text:
            text = re.sub(r"\ufffd[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]*", "", text).replace("\ufffd", "")
        latency = round(time.time() - start, 2)
        return text or "(ไม่มีเสียงพูดที่ถอดความได้)", latency
    except Exception as exc:
        return f"(ข้อผิดพลาด Typhoon: {exc})", round(time.time() - start, 2)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ── Typhoon Whisper Large v3 (high-accuracy, offline) ──
TYPHOON_LARGE_MODEL_ID = "typhoon-ai/typhoon-whisper-large-v3"
_typhoon_large_pipe = None


def get_typhoon_large_pipeline():
    global _typhoon_large_pipe
    if _typhoon_large_pipe is not None:
        return _typhoon_large_pipe
    import torch
    from transformers import pipeline as hf_pipeline

    # MPS gave garbage (fp16) / hung (fp32) in testing; CPU fp32 verified correct.
    # Override with env TYPHOON_LARGE_DEVICE=cuda|mps|cpu.
    forced = os.environ.get("TYPHOON_LARGE_DEVICE", "").strip().lower()
    if forced == "cuda" or (not forced and torch.cuda.is_available()):
        device, dtype = "cuda", torch.float16
    elif forced == "mps":
        device, dtype = "mps", torch.float16
    else:
        device, dtype = "cpu", torch.float32
    _typhoon_large_pipe = hf_pipeline(
        "automatic-speech-recognition",
        model=TYPHOON_LARGE_MODEL_ID,
        torch_dtype=dtype,
        device=device,
    )
    return _typhoon_large_pipe


def run_raw_typhoon_large(audio_bytes: bytes) -> Tuple[str, float]:
    start = time.time()
    tmp_path = None
    try:
        asr = get_typhoon_large_pipeline()

        # Compress prolonged silences before Whisper to avoid looping/hallucination
        clean_bytes, _ = compress_long_silences(audio_bytes)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(clean_bytes)
            tmp_path = tmp.name

        out = asr(
            tmp_path,
            chunk_length_s=30,
            stride_length_s=4,
            return_timestamps=True,
            generate_kwargs={
                "language": "th",
                "task": "transcribe",
                "no_repeat_ngram_size": 4,
                "repetition_penalty": 1.15,
            },
        )
        latency = round(time.time() - start, 2)
        raw_text = (out.get("text") or "").strip()
        if raw_text and "\ufffd" in raw_text:
            raw_text = re.sub(r"\ufffd[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]*", "", raw_text).replace("\ufffd", "")
        return raw_text or "(ไม่มีเสียงพูดที่ถอดความได้)", latency
    except Exception as exc:
        return f"(ข้อผิดพลาด Typhoon Whisper Large: {exc})", round(time.time() - start, 2)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ── Post-processing Stages ──
def apply_pharmacy_dictionary(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    if not text or text.startswith("("):
        return text, []
    return correct_transcript(text)


def split_text_into_chunks(text: str, max_chars: int = 1500) -> List[str]:
    """
    Safely splits long transcripts into logical chunks along spaces or Thai sentence-ending particles.
    """
    import re
    text = (text or "").strip()
    if len(text) <= int(max_chars * 1.25):
        return [text] if text else []

    chunks: List[str] = []
    remaining = text
    while len(remaining) > int(max_chars * 1.25):
        window = remaining[:max_chars]
        space_idx = window.rfind(" ", int(max_chars * 0.7))
        particle_pattern = r'(?:ครับ|ค่ะ|คะ|นะ|เนาะ|เนอะ|ไหม|มั้ย|จ้า|จ้ะ|เท่าไหร่|กี่วัน)'
        matches = [m.end() for m in re.finditer(particle_pattern, window)]
        particle_idx = max([idx for idx in matches if idx >= int(max_chars * 0.65)], default=-1)

        if space_idx != -1 and space_idx >= int(max_chars * 0.7):
            split_at = space_idx
        elif particle_idx != -1:
            split_at = particle_idx
        else:
            split_at = max_chars

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


# ── Dynamic Clinical Domain Exemplars ──
CLINICAL_EXEMPLARS = {
    "gi": """ตัวอย่างบทสนทนา (กรณีท้องเสีย / ถ่ายเหลว / ทางเดินอาหาร):
ข้อความ: หรือเป็นมาสองวันเนอะ เมื่อเช้าถ่ายเหลวมาสองครั้งแล้วเนอะ ช่วงนี้มีไข้ด้วยไหม ไม่มี ไม่ค่อยมี ถ่ายเหลวเป็นน้ำ อาหารทานได้ปกติไหม ปกติ ปกติ อาเจียนไม่มีเนอะ อืม เดี๋ยวให้ยาแก้ท้องเสีย เดี๋ยวเพิ่มลดอาการท้องเสียไป จะเป็นนิฟูรอกซาไซด์ ทานเช้ากลางวันเย็นก่อนนอนสี่เวลานะ อันนี้สามสิบห้าบาท รับมาสี่สิบนะ ทอนห้าบาทครับ
ผลลัพธ์:
[เภสัชกร] หรือเป็นมาสองวันเนอะ
[ผู้ป่วย] เมื่อเช้าถ่ายเหลวมาสองครั้งแล้วเนอะ
[เภสัชกร] ช่วงนี้มีไข้ด้วยไหม
[ผู้ป่วย] ไม่มี ไม่ค่อยมี
[เภสัชกร] ถ่ายเหลวเป็นน้ำ อาหารทานได้ปกติไหม
[ผู้ป่วย] ปกติ ปกติ
[เภสัชกร] อาเจียนไม่มีเนอะ
[ผู้ป่วย] อืม
[เภสัชกร] เดี๋ยวให้ยาแก้ท้องเสีย เดี๋ยวเพิ่มลดอาการท้องเสียไป จะเป็นนิฟูรอกซาไซด์ ทานเช้า กลางวัน เย็น ก่อนนอน 4 เวลานะ
[เภสัชกร] อันนี้สามสิบห้าบาท รับมาสี่สิบนะ ทอนห้าบาทครับ""",

    "pain": """ตัวอย่างบทสนทนา (กรณีปวดฟัน / แผล / ปวดเมื่อย / ฆ่าเชื้อ / เกาต์):
ข้อความ: เป็นยาแก้ปวดฟันนะ แพ้ยาไม่มีนะ ไม่มีครับ เป็นมากี่วันแล้วครับ พึ่งเป็นได้เมื่อคืนครับ มีใช้อะไรมาก่อนหน้านี้ไหมครับ ก็ยาพารา ใช้พาราดีขึ้นไหม ก็ดีขึ้นนิดหน่อย เดี๋ยวจะเป็นฆ่าเชื้อนะครับ เดี๋ยวเพิ่มไป เมโทรนิดาโซล ทานติดต่อกันจนหมดหน่อย เช้าเย็นนะครับ โอนครับ สามสิบบาทครับ
ผลลัพธ์:
[เภสัชกร] เป็นยาแก้ปวดฟันนะ แพ้ยาไม่มีนะ
[ผู้ป่วย] ไม่มีครับ
[เภสัชกร] เป็นมากี่วันแล้วครับ
[ผู้ป่วย] พึ่งเป็นได้เมื่อคืนครับ
[เภสัชกร] มีใช้อะไรมาก่อนหน้านี้ไหมครับ
[ผู้ป่วย] ก็ยาพารา
[เภสัชกร] ใช้พาราดีขึ้นไหม
[ผู้ป่วย] ก็ดีขึ้นนิดหน่อย
[เภสัชกร] เดี๋ยวจะเป็นฆ่าเชื้อนะครับ เดี๋ยวเพิ่มไป เมโทรนิดาโซล ทานติดต่อกันจนหมดหน่อย เช้าเย็นนะครับ
[ผู้ป่วย] โอนครับ
[เภสัชกร] สามสิบบาทครับ""",

    "cold": """ตัวอย่างบทสนทนา (กรณีไข้หวัด / ไอ / เสมหะ / ไซนัส / เจ็บคอ):
ข้อความ: เป็นไข้หวัดเนอะ เป็นไข้วันจันทร์ ได้พาราอย่างเดียว สองวันยังมีไข้อยู่ ไปโรงพยาบาลได้สวอปอะไรให้ไหม อาการที่เหลือคือมีไข้แต่ไม่สูง แล้วก็ไอ คันคอ เจ็บคอ เดี๋ยวให้ยาแก้ไอขับเสมหะ ทานครั้งละหนึ่งเม็ดสามเวลานะครับ
ผลลัพธ์:
[เภสัชกร] เป็นไข้หวัดเนอะ
[ผู้ป่วย] เป็นไข้วันจันทร์ ได้พาราอย่างเดียว สองวันยังมีไข้อยู่
[เภสัชกร] ไปโรงพยาบาลได้สวอปอะไรให้ไหม
[ผู้ป่วย] อาการที่เหลือคือมีไข้แต่ไม่สูง แล้วก็ไอ คันคอ เจ็บคอ
[เภสัชกร] เดี๋ยวให้ยาแก้ไอขับเสมหะ ทานครั้งละ 1 เม็ด 3 เวลานะครับ""",

    "gerd": """ตัวอย่างบทสนทนา (กรณีลดกรด / กระเพาะ / กรดไหลย้อน):
ข้อความ: ยาลดกรดทานปกติเช้าก่อนนอนไหมครับ หรือเช้าเย็น ไม่รู้จำไม่ได้เลย ทานเช้าก่อนนอนสองตัวนี้นะ เคมิลทานตามอาการ 1-2 เม็ด เขียนไม่แยกค่ะ
ผลลัพธ์:
[เภสัชกร] ยาลดกรดทานปกติเช้าก่อนนอนไหมครับ หรือเช้าเย็น
[ผู้ป่วย] ไม่รู้จำไม่ได้เลย
[เภสัชกร] ทานเช้าก่อนนอนสองตัวนี้นะ เคมิลทานตามอาการ 1-2 เม็ด
[ผู้ป่วย] เขียนไม่แยกค่ะ""",

    "pediatric": """ตัวอย่างบทสนทนา (กรณีเด็ก / วัคซีน / จัดยาตามน้ำหนัก):
ข้อความ: ฉีดวัคซีนอนามัยก็เลยจะซื้อเตรียม จะซื้อยาติดไปก่อน น้องน้ำหนักประมาณเท่าไร ประมาณห้าโลค่ะ ห้าโลทานครั้งละศูนย์จุดห้าซีซีตามอาการ ถ้าไข้ไม่มีก็หยุดใช้ได้ สี่สิบห้าบาทครับ
ผลลัพธ์:
[ผู้ป่วย] ฉีดวัคซีนอนามัยก็เลยจะซื้อเตรียม
[เภสัชกร] จะซื้อยาติดไปก่อน น้องน้ำหนักประมาณเท่าไร
[ผู้ป่วย] ประมาณห้าโลค่ะ
[เภสัชกร] ห้าโล ทานครั้งละ 0.5 ซีซี ตามอาการ ถ้าไข้ไม่มีก็หยุดใช้ได้ สี่สิบห้าบาทครับ"""
}


def pick_few_shot_exemplar(text: str) -> str:
    t = (text or "").lower()
    if re.search(r'ถ่าย|ท้องเสีย|เหลว|เกลือแร่|คาร์บอน|นิฟูรอก|อาเจียน', t):
        return CLINICAL_EXEMPLARS["gi"]
    elif re.search(r'ฟัน|ปวดฟัน|แผล|อักเสบ|ฆ่าเชื้อ|เมโทรนิดา|ดิฟฟีลีน|กล้ามเนื้อ|เกาต์|โคลชิซีน', t):
        return CLINICAL_EXEMPLARS["pain"]
    elif re.search(r'ลดกรด|กรดไหลย้อน|กระเพาะ|เคมิล|แสบท้อง|หิวแล้วปวด', t):
        return CLINICAL_EXEMPLARS["gerd"]
    elif re.search(r'เด็ก|น้อง|ขวบ|วัคซีน|กิโล|ห้าโล|ไซริ้ง|เจลลดไข้', t):
        return CLINICAL_EXEMPLARS["pediatric"]
    else:
        return CLINICAL_EXEMPLARS["cold"]


def pre_segment_conversational_text(text: str) -> str:
    """
    Splits continuous Thai ASR output (both spaced and zero-space streams)
    into natural turn-taking boundaries:
    1. Complete question endings (ไหม, มั้ย, หรือเปล่า, กี่วันแล้ว, กี่ครั้ง, เท่าไหร่)
    2. Polite particles followed by space or distinct turn-pivot starters
    3. Patient affirmations/acknowledgments (even without trailing space)
    4. Zero-space clinical pharmacist & patient turn starters
    """
    if not text:
        return text

    # Step 1: Normalize horizontal whitespace while preserving existing newlines
    s = re.sub(r'[ \t]+', ' ', text).strip()

    # Step 2: Break AFTER question endings (unless immediately followed by "หรือ")
    q_pat = (
        r'((?:ไหม|มั้ย|หรือเปล่า|หรือยัง|ด้วยไหม|ใช่ไหม|ใช่ปะ|ป่ะ|หรือไง|เหรอ|หรือครับ|หรือค่ะ|'
        r'กี่วันแล้ว|กี่ครั้งแล้ว|เท่าไหร่|กี่บาท|กี่วัน|กี่รอบ|กี่ครั้ง|กี่ขวบ|กี่โล|'
        r'ปกติไหม|ดีขึ้นไหม|ทานได้ปกติไหม|มีไข้ด้วยไหม|ทานมากี่วันแล้ว|เป็นมากี่วันแล้ว)\s*'
        r'(?:ครับ|ค่ะ|คะ|นะ|เนอะ|เนาะ|ฮะ|นะครับ|นะคะ)?)\s*(?!หรือ)'
    )
    s = re.sub(q_pat, r'\1\n', s)

    # Step 3: Break AFTER polite particles when followed by space and Thai char
    s = re.sub(r'((?:ครับ|ค่ะ|คะ|นะฮะ|เนาะ|เนอะ|จ้า|จ้ะ|นะคะ|นะครับ)\s+)(?=[ก-๙])', r'\1\n', s)

    # Step 4: Zero-space break BEFORE unmistakable clinical & turn-pivot starters
    zero_space_starters = [
        r'เดี๋ยวให้ยา', r'เดี๋ยวเพิ่ม', r'ยังไงเดี๋ยวให้ยา', r'ยังไงเดี๋ยวใช้ยา', r'เดี๋ยวเอาอย่างดีไปเลย',
        r'แพ้ยาไม่มีนะ', r'แพ้ยาไม่มีเลย', r'แพทยาไม่มีนะ', r'มีใช้อะไรมาก่อนหน้านี้ไหม',
        r'มีใช้ยาอะไรมาก่อนหน้านี้', r'มีกินยาอะไรมาก่อนหน้านี้', r'เป็นมากี่วันแล้ว', r'เป็นมาประมาณกี่วันแล้ว',
        r'ช่วงนี้มีไข้ด้วยไหม', r'ช่วงนี้พักผ่อนน้อยด้วยไหม', r'อาหารทานได้ปกติไหม', r'อาหารทานปกติไหม',
        r'อาเจียนไม่มีเนอะ', r'เกลือแร่ยังเหลืออยู่ไหม', r'เกิดแรกยังเหลืออยู่ไหม', r'ยาแก้แพ้ที่บ้านยังเหลืออยู่ไหม',
        r'น้องน้ำหนักประมาณเท่าไหร่', r'น้องประมาณเท่าไหร่', r'เมื่อวานมีทำกิจกรรมอะไรไหม',
        r'แล้วเมื่อวานมีทำกิจกรรมอะไรไหม', r'ได้ตรวจไข้หวัด', r'แต่แสบเป็นหลักใช่ไหม',
        r'แต่เจ็บโพรงจมูกเป็นหลักใช่ไหม', r'แต่เจ็บพงจมูกเป็นหลักใช่ไหม', r'แต่น้ำมูกไม่มีเลยเนอะ',
        r'เจ็บคงเจ็บคอมีไหม', r'เจ็บพวงเจ็บคอมีไหม', r'ปวดขณะเคลื่อนไหวใช่ไหม', r'ปวดขนาดเคลื่อนไหวใช่ไหม',
        r'แต่ปวดอย่างเดียวเนาะ', r'หมายถึงว่ากระดูก', r'อยากให้เป็นแบบ', r'ถ้าหลอดใหญ่เจ็ดสิบห้า',
        r'จะรับแต่เงินสดครับ', r'เจอรับแต่เงินสดครับ', r'ต้องมียาทาไหมครับ', r'สแกนได้ไหมครับ',
        r'อ๋อห้าโลครับ', r'เพิ่งเป็นได้เมื่อคืนครับ', r'ใช่ครับพักน้อย', r'เจ็บค่ะสองวันแล้ว',
        r'อ๋อที่ให้ไปตอนนั้น', r'อ๋อ\s*ที่ให้ไปตอนนั้น', r'อ๋อคือตอนนั้นที่ให้', r'เบรกขออนุญาตนะ',
        r'อ่าขออนุญาตนะ', r'มันก็ตีแต่มันไม่เป็นเหมือน', r'นี่ก็ดีแต่มันไม่เหมือนกับอันนี้',
    ]
    zs_regex = r'(?<=[ก-๙])\s*(' + '|'.join(zero_space_starters) + r')'
    s = re.sub(zs_regex, r'\n\1', s)

    # Step 5: Break AFTER short patient acknowledgments at line start (with or without space)
    s = re.sub(
        r'(^|\n)\s*(อ๋อห้าโลครับ|ใช่ครับพักน้อย|เจ็บค่ะสองวันแล้ว|เมื่อวานเป็นเมื่อวาน|'
        r'ปกติ ปกติ|ไม่มีแล้วเนอะ|ไม่มีแล้ว|ไม่มีครับ|ไม่มีค่ะ|ไม่มีเลย|อยู่อยู่|ก็ยกก็ปวด)\s*(?=[ก-๙])',
        r'\1\2\n',
        s,
    )

    # Step 6: Break BEFORE general clinical starters when preceded by whitespace
    starters = [
        r'จัดยา', r'อาเจียน', r'อันนี้\s*(?:สามสิบ|ยี่สิบ|\d+)\s*บาท',
        r'รับมา\s*\d+', r'ทอน\s*\d+', r'จะซื้อยาติด',
        r'ทานติดต่อกัน', r'จะเป็นแค่เช้าเย็น', r'ชำระเงินด้านนี้', r'ทานเช้า', r'ทานก่อนนอน',
        r'วันละ\s*\d+\s*เวลา', r'มื้อละ', r'ติดเจลไปด้วย', r'พวกคาร์บอน',
        r'เกลือแร่ทาน', r'หรือใช้เช้าเย็น', r'อาการปวดดีขึ้นไหม', r'ใช้พาราดีขึ้นไหม',
        r'เมื่อเช้าถ่าย', r'เมื่อเช้า', r'เมื่อวาน', r'พึ่งเป็นเมื่อคืน', r'เป็นเมื่อคืน',
        r'ทานแค่', r'กินพารา', r'ก็ยาพารา', r'ซื้อเตรียม', r'โอนครับ',
        r'ไม่มี\s*ไม่ค่อยมี', r'ไม่ค่อยมี', r'ยังไม่มี',
        r'ไม่รู้จำไม่ได้เลย', r'ไม่รู้จำไม่ได้อ่ะ', r'เขียนไม่แยก', r'แต่ว่ามันก็หายแล้ว',
        r'ตื่นเช้ามามันเจ็บ', r'คิดว่าเป็นไซนัส', r'ว่าพรืน', r'น้องเป็นมาประมาณ',
        r'ปวดเนี้ยะ', r'ปัสสาวะขัด',
    ]
    starter_regex = r'\s+(' + '|'.join(starters) + r')'
    s = re.sub(starter_regex, r'\n\1', s)

    return re.sub(r'\n+', '\n', s).strip()


def disentangle_utterance(role: str, text: str, _depth: int = 0) -> List[Tuple[str, str]]:
    """
    Recursive sub-turn splitter that separates composite utterances where an ASR stream
    or LLM bundled a pharmacist inquiry/instruction and a patient reply into a single line
    (works on both spaced and zero-space Thai transcripts).
    """
    text = (text or "").strip()
    if not text or _depth >= 4:
        return [(role, text)] if text else []

    # Pattern A1: Patient statement/complaint followed by Pharmacist question/dispensing
    m_p2ph = re.search(
        r'^(ฉีดวัคซีน.*?ติดไปก่อน|เมื่อวานเป็นเมื่อวาน|ใช่ครับพักน้อย|ใช่เจ็บ|เจ็บค่ะสองวันแล้ว|'
        r'อ๋อห้าโลครับ|ปกติ\s*ปกติ|อยู่อยู่|มีอยู่|ไม่มีแล้ว|ไม่มีครับ(?:ไม่มี)?(?:มันเริ่มบวมนิดแล้วครับ)?|'
        r'ไม่มีค่ะ|ไม่รู้จำไม่ได้(?:อ่ะ|เลย)?|กินแล้วหาย|กินแล้วครับ|ก็ยกก็ปวด|'
        r'อืมไม่ปวดครับ.*?เริ่มแบบพอง(?:\s*พอง)?|ใช่(?:แต่|ตั้งแต่)มีนา.*?ปวด(?:เรา|ร้าว(?:\s*ร้าว)?(?:นะ)?)|'
        r'แต่ว่ามันก็หายแล้วค่ะ.*?ตอนตื่นนอนตอน(?:เช้า|เท้า)|'
        r'เหมือนวันนี้เหมือน(?:เจอ|จะ)ตัว(?:ลุม|รุม)(?:\s*รุมอะไรอย่างงี้)?|'
        r'อันนั้นไม่ได้ใช้.*?ไม่ได้ใช้|มันก็(?:ดี|ตี)แต่มันไม่เป็นเหมือนแก้สิ|นี่ก็ดีแต่มันไม่เหมือนกับอันนี้.*?แก้อักเสบ)\s*'
        r'(น้อง(?:น้ำหนัก)?ประมาณเท่าไหร่.*|ช่วงนี้.*|แต่น้ำมูก.*|เป็นมากี่วัน.*|มีใช้ยาอะไร.*|'
        r'แต่แสบเป็นหลัก.*|ยังไงเดี๋ยว.*|เดี๋ยวให้ยา.*|เดี๋ยวเอาอย่างดี.*|แต่ปวดอย่างเดียว.*|'
        r'แล้วเมื่อวานมีทำกิจกรรม.*|หมายถึงว่ากระดูก.*|อยากให้เป็นแบบ.*|เจ็บ(?:คง|พวง)เจ็บคอมีไหม.*|'
        r'อาเจียน.*|พวกคาร์บอน.*|เกลือแร่.*|งั้น.*|ทานเช้า.*|อ่า\s*โอเค\s*มันใช้ตัวเดิมก็ได้.*|'
        r'อ๋อ\s*ที่ให้ไปตอนนั้น.*|อ๋อคือตอนนั้นที่ให้.*|จะ(?:เป็น|ให้).*)$',
        text,
    )
    if m_p2ph:
        left, right = m_p2ph.group(1).strip(), m_p2ph.group(2).strip()
        if left and right:
            return (
                disentangle_utterance("ผู้ป่วย", left, _depth + 1)
                + disentangle_utterance("เภสัชกร", right, _depth + 1)
            )

    # Pattern A2: Pharmacist question/dispensing followed by Patient answer/question
    m_ph2p = re.search(
        r'^(.*?(?:แพ้ยาไม่มี(?:เลย)?(?:นะ|ครับ|ค่ะ)?|แพทยาไม่มีนะ|เลยไหมครับ|เลยมั้ยครับ|ใช่ไหมครับ|ใช่ไหมคะ|'
        r'ดีขึ้นไหม(?:ครับ|ฮะ)?|ทานเช้าก่อนนอนไหมฮะ|หรือเช้าเย็น|กี่วันแล้ว(?:ครับ|นะ|ฮะ)?|'
        r'น้อง(?:น้ำหนัก)?ประมาณเท่าไหร่(?:ครับ|ฮะ)?|ให้ยาฆ่าเชื้อ(?:ไปเลย|กันหน่อย)(?:ครับ|ครับผม)?|'
        r'ปกติทานของแสลงแล้วมีอาการปวดไหม(?:อะ)?))\s*'
        r'(ไม่มีครับ|ไม่มีค่ะ|เพิ่งเป็นได้เมื่อคืนครับ|เป็นเมื่อคืนครับ|เป็นเมื่อวานครับ|ก็ยาพารา|'
        r'ก็ดีขึ้นนิดหน่อย|ไม่รู้จำไม่ได้.*|กินแล้ว.*|ประมาณ\s*(?:\d+|ห้า)\s*(?:โล|กิโล).*|'
        r'อ๋อห้าโล.*|ต้องมียาทาไหมครับ|สแกนได้ไหมครับ|เมื่อวานทานอะไรมา.*)$',
        text,
    )
    if m_ph2p:
        left, right = m_ph2p.group(1).strip(), m_ph2p.group(2).strip()
        if left and right:
            return (
                disentangle_utterance("เภสัชกร", left, _depth + 1)
                + disentangle_utterance("ผู้ป่วย", right, _depth + 1)
            )

    # Pattern C: Pharmacist price quote or change followed by customer/bystander remark
    m3 = re.search(
        r'^(.*?(?:(?:\d+|[หนึ่งสองสามสี่ห้าหกเจ็ดแปดเก้าสิบยี่ร้อย]+)\s*บาท|เงินทอน))\s*'
        r'(เออ.*|ได้แล้ว.*|คุณผู้ชม.*|อันนั้นของ.*|ของค่า.*)$',
        text,
    )
    if m3:
        left, right = m3.group(1).strip(), m3.group(2).strip()
        if left and right:
            return [
                ("เภสัชกร", left),
                ("ผู้ป่วย", right),
            ]

    return [(role, text)]


def validate_speaker_roles(role_text: str) -> str:
    """
    Multi-pass deterministic validator that enforces clinical pharmacy domain logic:
    - Pharmacist: triage questions, dispensing directions, regimen instructions (Sig), pricing
    - Patient: symptom complaints, confirmations, negations, home medicine status, payment
    Applies recursive intra-line disentanglement, question-answer adjacency pair locking,
    and flips any illogical LLM assignments.
    """
    if not role_text or role_text.startswith("("):
        return role_text

    PATIENT_EXCLUSIVE_TRIGGERS = [
        re.compile(r'^(?:ฉีดวัคซีน.*?(?:ซื้อเตรียม|ติดไปก่อน)|อ๋อห้าโลครับ|เมื่อวานเป็นเมื่อวาน|ใช่ครับพักน้อย|เจ็บค่ะสองวันแล้ว)'),
        re.compile(r'^(?:อืมไม่ปวดครับ|ก็ยกก็ปวด|ใช่(?:แต่|ตั้งแต่)มีนา|แต่ว่ามันก็หายแล้วค่ะ.*ตื่นเช้ามา)'),
        re.compile(r'^(?:ต้องมียาทาไหมครับ|สแกนได้ไหมครับ|โอนครับ|โอนเงิน|จ่ายเงินสด)'),
        re.compile(r'^(?:เมื่อเช้าถ่าย(?:เหลว|เร็ว)มา|เพิ่งเป็นได้เมื่อคืน|พึ่งเป็นเมื่อคืน|เป็นเมื่อคืนครับ)'),
        re.compile(r'^(?:เหมือนวันนี้เหมือน(?:เจอ|จะ)ตัว(?:ลุม|รุม)|แต่เพดานแต่ว่ามีเสมหะ|ไม่ค่อยอยากอาหาร)'),
        re.compile(r'^(?:อันนี้\s*อันนี้คนละแบบ|นี่ก็ดีแต่มันไม่เหมือนกับอันนี้|มันก็(?:ดี|ตี)แต่มันไม่เป็นเหมือน|อันนั้นไม่ได้ใช้.*หายปวดก่อน)'),
        re.compile(r'(?:พี่มีตัวอื่นแนะนำไหม|มีราคาที่ถูกกว่านี้มั้ย|ขายยังไงครับ)'),
    ]

    PHARMACIST_TRIGGERS = [
        re.compile(r'(?:อาหาร|ข้าว).*(?:ทาน|กิน).*(?:ปกติ|ได้).*(?:ไหม|มั้ย|หรือเปล่า)'),
        re.compile(r'(?:อาจารย์|อาการ).*(?:ทาน|กิน).*(?:ปกติ|ได้).*(?:ไหม|มั้ย)'),
        re.compile(r'อาเจียน.*(?:ไหม|มั้ย|หรือเปล่า|มีไหม|ไม่มีเนอะ)'),
        re.compile(r'(?:มีไข้|เป็นไข้|ตัวร้อน).*(?:ไหม|มั้ย|ด้วยไหม)'),
        re.compile(r'(?:ถ่าย|อุจจาระ).*(?:น้ำ|เหลว|กี่ครั้ง|เลือด).*(?:ไหม|มั้ย|หรือเปล่า)'),
        re.compile(r'(?:เกลือแร่|เกิดแรก|ors|ยาแก้แพ้ที่บ้าน).*(?:เหลือ|มี).*(?:ไหม|มั้ย|อยู่ไหม)'),
        re.compile(r'(?:คาร์บอน|ดูดซับ).*(?:ไหม|มั้ย)'),
        re.compile(r'(?:แพ้ยา|แพทยา|แพ้งา|โรคประจำตัว).*(?:ไหม|มั้ย|อะไร|ไม่มีนะ|ไม่มีเลย)'),
        re.compile(r'(?:เดี๋ยว|จะ|ยังไงเดี๋ยว).*(?:ให้ยา|ใช้ยา|จัดยา|จ่ายยา|เพิ่ม|เอาอย่างดีไปเลย)'),
        re.compile(r'(?:ทาน|กิน).*(?:เช้า|กลางวัน|เย็น|ก่อนนอน|เวลา|มื้อ|ครั้งละ|วันละ|ก่อนอาหาร|หลังอาหาร|ติดต่อกัน|เพิ่ม|ตามอาการ|ถ้ามีอาการ|ถ้าปวด)'),
        re.compile(r'ถ้ามีอาการ.*(?:ทาน|กิน)'),
        re.compile(r'ประมาณ\s*(?:\d+|ห้า|เจ็ด|สิบ|สิบสี่)\s*วัน'),
        re.compile(r'\d+\s*(?:มิลลิกรัม|มก|เม็ด|ซอง).*(?:ทาน|กิน|วันละ)'),
        re.compile(r'(?:อันนี้|ทั้งหมด|รวมเป็น|\b)\s*(?:\d+|[หนึ่งสองสามสี่ห้าหกเจ็ดแปดเก้าสิบยี่ร้อย]+)\s*บาท'),
        re.compile(r'(?:เงินทอน|ทอนเงิน|ทอน\s*\d+|\d+\s*บาทเงินทอน|บาทเงินทอน|รับแต่เงินสดครับ|เอาเป็นโลชั่นหรือเป็นครีม)'),
        re.compile(r'ถ้าหลอดใหญ่เจ็ดสิบห้า|ก็จะใช้เป็นยาฆ่าเชื้อรา'),
        re.compile(r'มีแค่.*อย่างเดียวนะ'),
        re.compile(r'^หรือเป็นมา.*(?:วันเนอะ|วันไหม|วันครับ|วันค่ะ)'),
        re.compile(r'น้องน้ำหนักประมาณเท่าไหร่|เด็กกี่ขวบ|น้องกี่โล|น้องประมาณเท่าไหร่|อยากให้เป็นแบบ'),
        re.compile(r'ชำระเงินด้านนี้|รับมา.*บาท'),
        re.compile(r'(?:อาการ|ปวด|ดีขึ้น|หาย|ทุเลา).*(?:ไหม|มั้ย|หรือเปล่า|ดีขึ้นไหม|หายไหม)'),
        re.compile(r'(?:ตัวเดิม|ตัวเก่า|ตัวนี้|ใช้ตัว).*(?:ก็ได้|ดีกว่า|นะ)'),
        re.compile(r'(?:เกาต์|ของแสลง|ปัจจัยกระตุ้น|พยายามเลี่ยงของแสลง|สัมผัสสารก่อ)'),
        re.compile(r'(?:โคลชิซีน|Colchicine|ไดฟีลีน|Difelene|ไดโคลฟีแนค|Diclofenac|ไพรอกซีแคม|Piroxicam|Metronidazole).*(?:มั้ย|ไหม|มิลลิกรัม|เม็ด|ทันที|เช้าเย็น)'),
        re.compile(r'\b(?:ปกติใช้|ใช้อยู่).*(?:กี่ครั้ง|กี่เม็ด|วันละ)'),
        re.compile(r'(?:ได้ตรวจไข้หวัด|ยกของยกของไหม|เมื่อวานมีทำกิจกรรมอะไรไหม|หมายถึงว่ากระดูก.*หักตั้งแต่มีนา|ปวด(?:ขณะ|ขนาด)เคลื่อนไหวใช่ไหม|แต่ปวดอย่างเดียวเนาะ|ช่วงนี้.*(?:พักผ่อน|มีไข้|อากาศ)|แต่แสบเป็นหลักใช่ไหม|แต่เจ็บ(?:โพรง|พง|พวง)จมูกเป็นหลักใช่ไหม|เจ็บ(?:คง|พวง)เจ็บคอมีไหม|เป็นมากี่วันแล้ว|มีใช้ยาอะไรมาก่อนหน้านี้|ลองไปถอนออก|มองใบถอนออก|ขออนุญาตนะ(?:ฮะ|ครับ|คะ)|อ๋อ\s*ที่ให้ไปตอนนั้น|อ๋อคือตอนนั้นที่ให้|สามารถใช้ได้นะ.*ฆ่าเชื้อเพิ่ม|แต่ตอนนั้นมันห่างกี่วันแล้ว)'),
    ]

    PATIENT_TRIGGERS = [
        re.compile(r'^(?:ไม่มี|ไม่ค่อยมี|ยังไม่มี|ไม่เป็น|ไม่มีครับ|ไม่มีค่ะ|ไม่ได้ใช้|ไม่ไอเลย|ไม่มีแล้ว)'),
        re.compile(r'^(?:อยู่อยู่|มีอยู่|ยังมี|ทานแค่|กินแค่|ก็ยาพารา)'),
        re.compile(r'^(?:เมื่อเช้า|เมื่อวาน|พึ่ง|เพิ่ง|ถ่ายเหลวมา|มีอาการ|ปวดมา|เป็นเมื่อคืน)'),
        re.compile(r'(?:อันนั้นของ|อันนึงของ|คุณผู้ชม|พี่จ๋า)'),
        re.compile(r'^(?:เคยใช้อยู่แล้ว|เขียนไม่แยก|ครีมครับ|โลชั่นครับ|ซื้อเตรียม|ไม่รู้จำไม่ได้)'),
        re.compile(r'^(?:โอนครับ|โอนเงิน|จ่ายเงินสด)'),
        re.compile(r'(?:เท่าไหร่|ขายยังไง|กี่บาท)'),
        re.compile(r'^(?:กินแล้ว|ทานแล้ว|กินแล้วหาย|กินแล้วดีขึ้น|กินแล้วครับ|กินแล้วค่ะ|ใช่ครับ\s*กินแล้ว)'),
        re.compile(r'^(?:ผมจะมาซื้อ|จะมาซื้อ|ตัวสีขาว|เม็ดเล็ก|พี่มีตัวอื่นแนะนำ|แรงไหม|แรงมั้ย)'),
        re.compile(r'^(?:วันหนึ่งผม|พยายามเลี่ยงครับ|กินทีไรเป็นทุกที)'),
    ]

    QUESTION_ENDING_RE = re.compile(
        r'(?:ไหม|มั้ย|หรือเปล่า|หรือยัง|เท่าไหร่|กี่วัน|กี่ครั้ง|กี่เม็ด|กี่โล|ใช่ไหม|เหรอ|ฮะ)\s*(?:ครับ|ค่ะ|คะ|นะ|เนอะ|เนาะ|ฮะ)?$'
    )
    SHORT_ANSWER_START_RE = re.compile(
        r'^(?:ใช่|ไม่|เมื่อวาน|เมื่อคืน|สองวัน|สามวัน|อ๋อ|อืม|ปกติ|อยู่|กินแล้ว|ทานแค่|ก็|ประมาณ)'
    )

    raw_lines = role_text.splitlines()
    split_lines: List[Tuple[str, str]] = []

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^(?:\*{0,2}\[(เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\]\*{0,2}:?|(เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\s*[:：])\s*(.*)', line)
        if not m:
            for sub in pre_segment_conversational_text(line).splitlines():
                sub = sub.strip()
                if sub:
                    split_lines.extend(disentangle_utterance("เภสัชกร", sub))
            continue
        tag_str = m.group(1) or m.group(2) or "เภสัชกร"
        r = "เภสัชกร" if "เภสัช" in tag_str else "ผู้ป่วย"
        content = (m.group(3) or "").strip()
        # Run pre-segmentation on long composite lines to split zero-space turn pivots
        for sub in pre_segment_conversational_text(content).splitlines():
            sub = sub.strip()
            if sub:
                split_lines.extend(disentangle_utterance(r, sub))

    validated_lines: List[str] = []
    prev_role: Optional[str] = None
    prev_was_pharma_question = False

    for cur_role, content in split_lines:
        content = content.strip()
        if not content:
            continue

        if any(pat.search(content) for pat in PATIENT_EXCLUSIVE_TRIGGERS):
            cur_role = "ผู้ป่วย"
        elif any(pat.search(content) for pat in PHARMACIST_TRIGGERS):
            cur_role = "เภสัชกร"
        elif any(pat.search(content) for pat in PATIENT_TRIGGERS):
            cur_role = "ผู้ป่วย"
        elif (
            prev_role == "เภสัชกร"
            and prev_was_pharma_question
            and len(content) <= 45
            and SHORT_ANSWER_START_RE.search(content)
        ):
            cur_role = "ผู้ป่วย"

        validated_lines.append(f"[{cur_role}] {content}")
        prev_role = cur_role
        prev_was_pharma_question = (cur_role == "เภสัชกร") and bool(QUESTION_ENDING_RE.search(content))

    return "\n".join(validated_lines)


def apply_speaker_role_separation(text: str) -> str:
    """
    Separates speech into [เภสัชกร] and [ผู้ป่วย] using clinical domain-guided prompt,
    dynamic topic-matched Few-Shot exemplars, robust pre-segmentation, and
    deterministic post-processing clinical guard.
    """
    if not text or text.startswith("("):
        return text

    # Pre-segment continuous conversational speech before sending to LLM
    pre_segmented = pre_segment_conversational_text(text)

    key = get_groq_api_key()
    if not key:
        return pre_segmented

    chunks = split_text_into_chunks(pre_segmented, max_chars=1500)
    if not chunks:
        return pre_segmented

    try:
        from groq import Groq
        client = Groq(api_key=key)
        separated_parts = []
        prev_speaker = None

        # Dynamically select clinical few-shot exemplar for this consultation
        few_shot_exemplar = pick_few_shot_exemplar(text)

        for idx, chunk in enumerate(chunks):
            context_note = ""
            if prev_speaker:
                context_note = f"\nบริบทต่อเนื่อง: ประโยคก่อนหน้านี้สิ้นสุดที่ [{prev_speaker}] ให้วิเคราะห์และจำแนกบทบาทต่อเนื่องจากจุดนี้\n"

            prompt = f"""คุณเป็นผู้เชี่ยวชาญด้านเวชสารสนเทศและการจำแนกบทสนทนาในร้านยา
หน้าที่: จำแนกผู้พูดโดยเติม [เภสัชกร] หรือ [ผู้ป่วย] นำหน้าแต่ละประโยค พร้อมตัดบรรทัดให้อ่านง่าย
{context_note}
กฎเหล็กทางคลินิก (Clinical Ground Rules):
1. **บทบาทของ [เภสัชกร] (Pharmacist):**
   - ผู้ซักประวัติอาการและคัดกรอง: ถามประวัติแพ้ยา ('แพ้ยาไม่มีนะ'), ถามระยะเวลา ('เป็นมากี่วันแล้ว'), ถามอาการร่วม ('ช่วงนี้มีไข้ด้วยไหม', 'ถ่ายเหลวเป็นน้ำไหม', 'อาหารทานได้ปกติไหม', 'อาเจียนไหม', 'อาการปวดดีขึ้นไหม')
   - ผู้ตรวจสอบสต็อกยาคนไข้ที่บ้าน: 'เกลือแร่ยังเหลืออยู่ไหม', 'คาร์บอนดูดซับมีไหม'
   - ผู้สั่งจ่ายยาและอธิบายวิธีรับประทาน (Sig): 'เดี๋ยวให้ยา...', 'ทานเช้า กลางวัน เย็น ก่อนนอน 4 เวลานะ', 'ทานติดต่อกันจนหมด', 'เคมิลทานตามอาการ'
   - ผู้แจ้งราคาและคิดเงิน 100%: 'สามสิบบาทครับ', 'อันนี้ 35 บาท', 'ทอน ... บาท', 'ชำระเงินด้านนี้'

2. **บทบาทของ [ผู้ป่วย] (Patient):**
   - ผู้บอกเล่าอาการของตนเอง: 'เมื่อเช้าถ่ายเหลวมาสองครั้งแล้วเนอะ', 'ปวดฟัน', 'เป็นเมื่อคืนครับ'
   - ผู้ตอบปฏิเสธหรือยืนยันอาการ: 'ไม่มีครับ', 'ไม่มีค่ะ', 'ไม่มี ไม่ค่อยมี', 'อยู่อยู่', 'ทานแค่...', 'กินแล้วหาย'
   - ผู้ถามชื่อยาหรือข้อสงสัย: 'พี่มีตัวอื่นแนะนำไหม', 'กินก่อนอาหาร'
   - ผู้ชำระเงิน: 'โอนครับ', 'จ่ายเงินสด'

3. **ห้ามสลับผู้พูดแบบปิงปองอัตโนมัติ (Strict No Ping-Pong Bias):**
   - เภสัชกรสามารถซักถามอาการหรือให้คำแนะนำติดต่อกันได้หลายประโยค
   - ห้ามเด็ดขาดไม่ให้ผู้ป่วยเป็นคนถามซักประวัติ หรือเป็นคนสั่งจ่ายยาและบอกวิธีรับประทาน 4 เวลา

4. **การแยกประโยคที่ผู้พูดติดกันในบรรทัดเดียว (Intra-Line Turn Splitting):**
   - หากในบรรทัดเดียวกันมีคำตอบของผู้ป่วยติดอยู่กับคำถามหรือคำแนะนำถัดไปของเภสัชกร (แม้ไม่มีเว้นวรรคคั่น) ให้ตัดแยกขึ้นบรรทัดใหม่และติดป้าย `[ผู้ป่วย]` และ `[เภสัชกร]` แยกออกจากกันให้ชัดเจน

{few_shot_exemplar}

5. ห้ามตัดทอนคำ ห้ามแก้ไขคำเดิม รักษาข้อความเดิมครบถ้วน 100%
6. ตอบกลับเฉพาะบทสนทนาที่ติดป้าย [เภสัชกร] และ [ผู้ป่วย] เท่านั้น

ข้อความบทสนทนา:
{chunk}"""

            models_to_try = [
                ("qwen/qwen3.8-27b", None),
                ("openai/gpt-oss-120b", "low"),
                ("openai/gpt-oss-20b", "low"),
            ]
            resp = None
            last_err = None
            for m_id, reasoning in models_to_try:
                try:
                    kwargs = {
                        "messages": [{"role": "user", "content": prompt}],
                        "model": m_id,
                        "temperature": 0.1,
                        "max_completion_tokens": 4000,
                    }
                    if reasoning:
                        kwargs["reasoning_effort"] = reasoning
                    resp = client.chat.completions.create(**kwargs)
                    if resp and resp.choices and resp.choices[0].message.content:
                        break
                except Exception as err:
                    last_err = err
                    continue

            if resp is None or not resp.choices or not resp.choices[0].message.content:
                out = f"(คำเตือน: ช่วงที่ {idx+1} โมเดลไม่ส่งผลลัพธ์: {last_err})\n{chunk}"
            else:
                out = (resp.choices[0].message.content or "").strip()
            separated_parts.append(out)

            all_tags = re.findall(r'\[(เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\]', out)
            if all_tags:
                last_tag = all_tags[-1]
                prev_speaker = "เภสัชกร" if "เภสัช" in last_tag else "ผู้ป่วย"

        raw_separated = "\n".join(separated_parts)
        # Pass 2: Two-pass Deterministic Role Validator
        return validate_speaker_roles(raw_separated)
    except Exception as exc:
        return f"(ข้อผิดพลาดการแยกผู้พูด: {exc})\n\n{text}"


def apply_dialogue_formatting(role_text: str) -> List[Dict[str, str]]:
    """
    Parses role-separated text into structured dialogue turns:
    [{"speaker": "เภสัชกร", "text": "..."}, {"speaker": "ผู้ป่วย", "text": "..."}]
    Supports single-line, multi-line, markdown bullets, and Thai speaker variants.
    """
    import re
    turns: List[Dict[str, str]] = []
    if not role_text or role_text.startswith("("):
        return turns

    tag_pattern = re.compile(
        r'(?:\*{0,2}\[(?:เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\]\*{0,2}:?|\b(?:เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\s*[:：])'
    )
    matches = list(tag_pattern.finditer(role_text))

    if not matches:
        clean = role_text.strip()
        if clean:
            turns.append({"speaker": "เภสัชกร", "text": clean})
        return turns

    for j, m in enumerate(matches):
        raw_tag = m.group(0)
        speaker = "เภสัชกร" if ("เภสัช" in raw_tag) else "ผู้ป่วย"
        start_pos = m.end()
        end_pos = matches[j + 1].start() if (j + 1 < len(matches)) else len(role_text)
        content = role_text[start_pos:end_pos].strip()
        content = re.sub(r'^[:：*\s]+', '', content).strip()
        if content:
            if turns and turns[-1]["speaker"] == speaker:
                turns[-1]["text"] += " " + content
            else:
                turns.append({"speaker": speaker, "text": content})

    return turns


# ── Full Pipeline Caching ──
def get_audio_hash(audio_input: Any) -> str:
    """คำนวณ hash สำหรับแคชข้อมูล รองรับทั้ง bytes, str, และ Path"""
    if isinstance(audio_input, (str, Path)):
        p = Path(audio_input)
        if p.exists() and p.is_file():
            b = p.read_bytes()
        else:
            b = str(audio_input).encode("utf-8")
    elif isinstance(audio_input, bytes):
        b = audio_input
    else:
        b = bytes(audio_input)
    return hashlib.sha256(b).hexdigest()[:16]


def get_cached_result(audio_hash: str) -> Optional[Dict[str, Any]]:
    cache_file = CACHE_DIR / f"{audio_hash}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            ty_text = data.get("typhoon", {}).get("stage_0_raw", "")
            if "ข้อผิดพลาด" in ty_text or "Errno" in ty_text:
                return None
            healed = False
            if "typhoon_large" not in data and "typhoon" in data:
                raw_t = data["typhoon"].get("stage_0_raw", "")
                if raw_t and not raw_t.startswith("("):
                    data["typhoon_large"] = _build_pack(raw_t, data["typhoon"].get("latency", 0.0))
                    healed = True
            for key in ("typhoon", "typhoon_large"):
                if key not in data:
                    continue
                pack = data[key]
                raw = pack.get("stage_0_raw", "")
                role = (pack.get("stage_2_role") or "").strip()
                broken = (not role) or role.startswith("(ข้อผิดพลาด") or (
                    len(raw) > 300 and len(role) < len(raw) * 0.5
                )
                if broken and raw and not raw.startswith("("):
                    data[key] = _build_pack(raw, pack.get("latency", 0.0))
                    healed = True
            if healed:
                cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
        except Exception:
            return None
    return None


def save_cached_result(audio_hash: str, data: Dict[str, Any]) -> None:
    ty_text = data.get("typhoon", {}).get("stage_0_raw", "")
    if "ข้อผิดพลาด" in ty_text or "Errno" in ty_text:
        return
    cache_file = CACHE_DIR / f"{audio_hash}.json"
    try:
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"Failed to write cache: {exc}")


def _build_pack(raw: str, latency: float) -> Dict[str, Any]:
    dict_text, changes = apply_pharmacy_dictionary(raw)
    role_text = apply_speaker_role_separation(dict_text)
    turns = apply_dialogue_formatting(role_text)

    # ── Stage 4: Automatic Clinical EMR Extraction ──
    stage_4_emr: Dict[str, str] = {}
    conv_for_emr = ""
    if turns:
        conv_for_emr = "\n".join(f"{t.get('speaker', '')}: {t.get('text', '')}" for t in turns)
    elif role_text and not role_text.startswith("("):
        conv_for_emr = role_text

    if conv_for_emr and extract_emr:
        try:
            stage_4_emr = extract_emr(conv_for_emr)
        except Exception as exc:
            print(f"Warning: EMR auto-extraction failed: {exc}")
            stage_4_emr = {
                "บทสนทนาที่จัดเรียงแล้ว": conv_for_emr,
                "ประวัติการแพ้ยา": "-",
                "โรคประจำตัว": "-",
                "ประวัติการจ่ายยา": "-",
                "บันทึกทางการแพทย์": "-",
                "คำแนะนำจากเภสัช": "-",
            }
    else:
        stage_4_emr = {
            "บทสนทนาที่จัดเรียงแล้ว": conv_for_emr or raw,
            "ประวัติการแพ้ยา": "-",
            "โรคประจำตัว": "-",
            "ประวัติการจ่ายยา": "-",
            "บันทึกทางการแพทย์": "-",
            "คำแนะนำจากเภสัช": "-",
        }

    return {
        "latency": latency,
        "stage_0_raw": raw,
        "stage_1_dict": dict_text,
        "dict_changes": changes,
        "stage_2_role": role_text,
        "stage_3_dialogue": turns,
        "stage_4_emr": stage_4_emr,
    }


def rebuild_cached_pipeline(audio_hash: str) -> Optional[Dict[str, Any]]:
    """
    Re-runs stage 1 (dict & unicode clean), stage 2 (role separation), and stage 3 (dialogue formatting)
    using the existing stage_0_raw transcripts without re-running STT.
    Preserves existing cached role tags and EMR fields if LLM API is offline.
    """
    cache_file = CACHE_DIR / f"{audio_hash}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        for key in ("typhoon", "typhoon_large"):
            if key in data:
                old_pack = data[key]
                raw = old_pack.get("stage_0_raw", "")
                lat = old_pack.get("latency", 0.0)
                if raw and not raw.startswith("("):
                    if "\ufffd" in raw:
                        raw = re.sub(r"\ufffd[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]*", "", raw).replace("\ufffd", "")
                    dict_text, changes = apply_pharmacy_dictionary(raw)
                    old_role = old_pack.get("stage_2_role", "")
                    if old_role and not old_role.startswith("("):
                        role_clean, _ = apply_pharmacy_dictionary(old_role)
                        role_text = validate_speaker_roles(role_clean)
                    else:
                        role_text = apply_speaker_role_separation(dict_text)
                    turns = apply_dialogue_formatting(role_text)
                    conv_for_emr = (
                        "\n".join(f"{t.get('speaker', '')}: {t.get('text', '')}" for t in turns)
                        if turns else role_text
                    )
                    old_emr = old_pack.get("stage_4_emr", {})
                    if isinstance(old_emr, dict) and any(
                        str(old_emr.get(f, "-")).strip() not in ("", "-")
                        for f in ("ประวัติการแพ้ยา", "โรคประจำตัว", "ประวัติการจ่ายยา", "บันทึกทางการแพทย์", "คำแนะนำจากเภสัช")
                    ):
                        stage_4_emr = {}
                        for k_f, v_f in old_emr.items():
                            if k_f == "บทสนทนาที่จัดเรียงแล้ว":
                                stage_4_emr[k_f] = conv_for_emr
                            elif isinstance(v_f, str) and v_f.strip() not in ("", "-"):
                                corr_v, _ = apply_pharmacy_dictionary(v_f)
                                stage_4_emr[k_f] = corr_v
                            else:
                                stage_4_emr[k_f] = v_f
                    else:
                        new_pack = _build_pack(raw, lat)
                        stage_4_emr = new_pack.get("stage_4_emr", {})
                    data[key] = {
                        "latency": lat,
                        "stage_0_raw": raw,
                        "stage_1_dict": dict_text,
                        "dict_changes": changes,
                        "stage_2_role": role_text,
                        "stage_3_dialogue": turns,
                        "stage_4_emr": stage_4_emr,
                    }
        save_cached_result(audio_hash, data)
        return data
    except Exception as exc:
        print(f"Error rebuilding cache: {exc}")
        return None


def process_audio_full_pipeline(audio_bytes: bytes, filename: str = "audio.wav") -> Dict[str, Any]:
    """
    Runs Typhoon Realtime and Typhoon Whisper Large v3 through the multi-stage
    pipeline, caching all intermediate states so toggles can be viewed instantly.
    """
    audio_hash = get_audio_hash(audio_bytes)
    cached = get_cached_result(audio_hash)
    if cached:
        return cached

    raw_rt, lat_rt = run_raw_typhoon(audio_bytes)
    raw_lg, lat_lg = run_raw_typhoon_large(audio_bytes)

    result = {
        "audio_hash": audio_hash,
        "filename": filename,
        "created_at": time.time(),
        "typhoon": _build_pack(raw_rt, lat_rt),
        "typhoon_large": _build_pack(raw_lg, lat_lg),
    }

    save_cached_result(audio_hash, result)
    return result


def resolve_output_by_toggles(
    model_data: Dict[str, Any],
    use_dict: bool,
    use_roles: bool,
    use_format: bool
) -> Dict[str, Any]:
    """
    Calculates the exact display state based on which checkboxes are selected.
    """
    raw_text = model_data.get("stage_0_raw", "")
    dict_text = model_data.get("stage_1_dict", "")
    role_text = model_data.get("stage_2_role", "")
    turns = model_data.get("stage_3_dialogue", [])
    changes = model_data.get("dict_changes", []) if use_dict else []

    # Decide base text
    base_text = dict_text if use_dict else raw_text

    # Decide roles / format
    if use_format and use_roles:
        display_mode = "turns"
        display_content = turns
    elif use_roles:
        display_mode = "role_text"
        display_content = role_text
    else:
        display_mode = "plain_text"
        display_content = base_text

    return {
        "display_mode": display_mode,
        "display_content": display_content,
        "active_changes": changes,
        "base_text": base_text,
        "stage_4_emr": model_data.get("stage_4_emr", {}),
    }
