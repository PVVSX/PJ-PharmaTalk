# -*- coding: utf-8 -*-
"""
Demo App: Automatic Electronic Medical Record (EMR)

Run:
  streamlit run streamlit_emr_app.py

Gemini API key:
  - set GEMINI_API_KEY / GOOGLE_API_KEY, or
  - create .gemini_api_key in this project folder

Saved records:
  patient_info/*.json
  patient_info/emr_records.csv
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import streamlit as st


BASE = Path(__file__).resolve().parent
PATIENT_INFO_DIR = BASE / "patient_info"
AUDIO_INPUT_DIR = PATIENT_INFO_DIR / "audio_inputs"
GEMINI_KEY_FILE = BASE / ".gemini_api_key"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
# ถ้าโมเดลหลักโหลดหนัก (503) หรือโควตาเต็ม (429) จะลองรายการนี้ตามลำดับ
GEMINI_FALLBACK_MODELS = (
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
)
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "4096"))
GEMINI_THINKING_BUDGET = os.environ.get("GEMINI_THINKING_BUDGET", "0").strip()
GEMINI_RETRY_COUNT = int(os.environ.get("GEMINI_RETRY_COUNT", "4"))
GEMINI_RETRY_BASE_SEC = float(os.environ.get("GEMINI_RETRY_BASE_SEC", "2"))

EMR_FIELDS = [
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]


def conversation_widget_state_key() -> str:
    """คีย์ของ st.text_area บทสนทนา — เปลี่ยนเลขรุ่นเมื่อล้างเพื่อไม่ให้ชน StreamlitAPIException."""
    wid = int(st.session_state.get("conversation_widget_id", 0))
    return f"conversation_text_{wid}"


def read_key_from_file() -> str:
    if not GEMINI_KEY_FILE.is_file():
        return ""
    try:
        for line in GEMINI_KEY_FILE.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip().lstrip("\ufeff")
            if s and not s.startswith("#"):
                return s
    except OSError:
        return ""
    return ""


def get_gemini_api_key() -> str:
    try:
        override = st.session_state.get("gemini_api_key_override", "")
    except Exception:
        override = ""
    if override:
        return str(override).strip()
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or read_key_from_file()
    ).strip()


def get_gemini_model_name() -> str:
    return (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


def get_gemini_model_candidates() -> list[str]:
    """โมเดลหลัก + fallback เมื่อเซิร์ฟเวอร์ตอบ 503/429."""
    primary = get_gemini_model_name()
    extra_raw = (os.environ.get("GEMINI_FALLBACK_MODELS") or "").strip()
    if extra_raw:
        extras = [m.strip() for m in extra_raw.split(",") if m.strip()]
    else:
        extras = list(GEMINI_FALLBACK_MODELS)
    ordered: list[str] = []
    for name in [primary, *extras]:
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _gemini_skip_to_next_model(http_code: int, detail: str) -> bool:
    """True = โมเดลนี้ใช้ไม่ได้ชั่วคราว/ถาวร — ข้ามไปลองโมเดลถัดไป."""
    if http_code == 404:
        return True
    if http_code == 429:
        lowered = detail.lower()
        if "limit: 0" in lowered:
            return True
        if "perday" in lowered.replace("_", ""):
            return True
    return False


def _gemini_retry_delay_sec(detail: str, attempt: int) -> float:
    match = re.search(r'"retryDelay"\s*:\s*"(\d+)s"', detail)
    if match:
        return min(float(match.group(1)) + 1.0, 60.0)
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", detail, flags=re.IGNORECASE)
    if match:
        return min(float(match.group(1)) + 1.0, 60.0)
    return min(GEMINI_RETRY_BASE_SEC * (2**attempt), 12.0)


def _legacy_gemini_sdk_available() -> bool:
    try:
        import google.generativeai as genai

        return hasattr(genai, "GenerativeModel")
    except ImportError:
        return False


def _new_gemini_sdk_available() -> bool:
    try:
        from google import genai  # noqa: F401

        return True
    except ImportError:
        return False


def extract_json_object(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        candidate = match.group(0)
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        value = json.loads(candidate)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def extract_emr_fields_from_text(raw: str) -> dict[str, str]:
    """อ่านผล Gemini แบบยืดหยุ่น ถ้าโมเดลไม่คืน JSON ที่สมบูรณ์"""
    data = extract_json_object(raw)
    if data:
        return {field: str(data.get(field) or "-").strip() or "-" for field in EMR_FIELDS}

    text = (raw or "").strip()
    if not text:
        return {}

    result: dict[str, str] = {}
    field_pattern = "|".join(re.escape(f) for f in EMR_FIELDS)
    for field in EMR_FIELDS:
        # รองรับทั้ง "field": "value" ที่ quote พังบางส่วน และ field: value แบบบรรทัด
        pattern = (
            rf'["“]?{re.escape(field)}["”]?\s*[:：]\s*'
            rf'(?P<value>[\s\S]*?)'
            rf'(?=\n\s*(?:["“]?(?:{field_pattern})["”]?\s*[:：])|\Z)'
        )
        m = re.search(pattern, text)
        if not m:
            continue
        value = m.group("value").strip()
        value = value.strip('",“” \n\r\t')
        value = re.sub(r"\n+", " ", value).strip()
        result[field] = value or "-"

    return result


def result_is_too_sparse(result: dict[str, str], conversation: str) -> bool:
    """กันเคส Gemini ตอบห้วน/หลุดช่องมากเกินไป แล้วให้ลอง prompt รอบสอง"""
    if len((conversation or "").strip()) < 80:
        return False
    values = {field: str(result.get(field) or "").strip() for field in EMR_FIELDS}
    empty_count = sum(1 for v in values.values() if v in ("", "-"))
    short_count = sum(1 for v in values.values() if 0 < len(v) <= 5 and v != "-")
    # ถ้าบันทึกและคำแนะนำว่างทั้งคู่ มักผิด เพราะบทสนทนาร้านยามักมีอย่างน้อยหนึ่งช่อง
    missing_core = (
        values.get("บันทึกทางการแพทย์", "-") in ("", "-")
        and values.get("คำแนะนำจากเภสัช", "-") in ("", "-")
    )
    return empty_count >= 3 or short_count >= 2 or missing_core


def analysis_cache_key(conversation: str) -> str:
    raw = f"{get_gemini_model_name()}\n{conversation}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def save_last_gemini_raw(raw_text: str) -> Path:
    ensure_patient_dir()
    p = PATIENT_INFO_DIR / "last_gemini_raw.txt"
    p.write_text(raw_text or "", encoding="utf-8")
    return p


def build_emr_prompt(conversation: str, *, retry: bool = False) -> tuple[str, str]:
    system_instruction = (
        "คุณเป็นผู้ช่วยเภสัชกรสำหรับสรุปบทสนทนาเป็นเวชระเบียน EMR "
        "ให้สกัดข้อมูลเฉพาะจากบทสนทนา ห้ามเดาข้อมูลที่ไม่มีในบทสนทนา "
        "ถ้าไม่พบข้อมูลให้ใส่ '-' และตอบเป็น JSON เท่านั้น"
    )
    retry_note = (
        "\nรอบนี้เป็นการวิเคราะห์ซ้ำเพราะรอบแรกข้อมูลน้อยเกินไป: "
        "ให้ตรวจบทสนทนาอย่างละเอียดและเติมช่องบันทึกทางการแพทย์/คำแนะนำจากเภสัชถ้ามีหลักฐานในบทสนทนา\n"
        if retry
        else ""
    )
    prompt = f"""
จากบทสนทนาต่อไปนี้ ให้สรุปเป็น JSON ภาษาไทยตาม key ต่อไปนี้เท่านั้น:

{{
  "ประวัติการแพ้ยา": "...",
  "โรคประจำตัว": "...",
  "ประวัติการจ่ายยา": "...",
  "บันทึกทางการแพทย์": "...",
  "คำแนะนำจากเภสัช": "..."
}}

หลักการ:
- ประวัติการแพ้ยา: ยาหรือสารที่ผู้ป่วยแพ้ พร้อมอาการแพ้ถ้ามี
- โรคประจำตัว: โรคเดิม/ภาวะประจำตัว/ยาที่สัมพันธ์กับโรคประจำตัว
- ประวัติการจ่ายยา: ยาที่เคยได้รับหรือกำลังใช้อยู่ก่อนการจ่ายครั้งนี้
- บันทึกทางการแพทย์: อาการสำคัญ ระยะเวลา ความรุนแรง ข้อมูลที่เกี่ยวกับการพิจารณาจ่ายยา
- คำแนะนำจากเภสัช: ยาที่แนะนำ วิธีใช้ คำเตือน การติดตามอาการ หรือการส่งต่อ
- ถ้าไม่มีข้อมูลในช่องใดให้ใส่ "-"
{retry_note}

บทสนทนา:
{conversation}
""".strip()
    return system_instruction, prompt


def call_gemini_with_legacy_sdk(
    api_key: str, system_instruction: str, prompt: str, *, model_name: str
) -> str:
    import google.generativeai as genai

    if not hasattr(genai, "GenerativeModel"):
        raise AttributeError("google.generativeai ไม่มี GenerativeModel")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction,
    )
    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.1,
            "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
            "response_mime_type": "application/json",
        },
    )
    return getattr(response, "text", "") or ""


def call_gemini_with_new_sdk(
    api_key: str, system_instruction: str, prompt: str, *, model_name: str
) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "ไม่พบ Gemini SDK ที่ใช้ได้ ให้ติดตั้งอย่างใดอย่างหนึ่ง:\n"
            "python -m pip install google-genai\n"
            "หรือ\n"
            "python -m pip install google-generativeai"
        ) from exc

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        ),
    )
    return getattr(response, "text", "") or ""


def call_gemini_with_rest_api(
    api_key: str,
    system_instruction: str,
    prompt: str,
    *,
    model_name: str | None = None,
) -> str:
    """เรียก Gemini ผ่าน REST (ใช้ได้บน Python 3.8 โดยไม่ต้อง SDK ใหม่)."""
    model_name = (model_name or get_gemini_model_name()).strip()
    model = urllib.parse.quote(model_name, safe="")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={urllib.parse.quote(api_key)}"
    )
    generation_config: dict[str, Any] = {
        "temperature": 0.1,
        "candidateCount": 1,
        "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
        "responseMimeType": "application/json",
        "responseSchema": {
            "type": "OBJECT",
            "properties": {
                field: {"type": "STRING"} for field in EMR_FIELDS
            },
            "required": EMR_FIELDS,
        },
    }
    if GEMINI_THINKING_BUDGET:
        try:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": int(GEMINI_THINKING_BUDGET)
            }
        except ValueError:
            pass

    payload = {
        "systemInstruction": {
            "parts": [{"text": system_instruction}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": generation_config,
    }

    def post_once(body_payload: dict) -> dict:
        body = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    retryable_codes = {429, 500, 502, 503, 504}
    data: dict | None = None
    last_detail = ""

    for attempt in range(max(1, GEMINI_RETRY_COUNT)):
        try:
            data = post_once(payload)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_detail = detail

            if exc.code == 400 and (
                "thinkingConfig" in detail
                or "responseSchema" in detail
                or "unknown field" in detail.lower()
            ):
                payload["generationConfig"] = {
                    "temperature": 0.1,
                    "candidateCount": 1,
                    "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
                    "responseMimeType": "application/json",
                }
                try:
                    data = post_once(payload)
                    break
                except urllib.error.HTTPError as exc2:
                    detail = exc2.read().decode("utf-8", errors="replace")
                    last_detail = detail
                    exc = exc2

            if exc.code == 403 and "project has been denied access" in detail.lower():
                raise RuntimeError(
                    "Gemini API ตอบ 403: โปรเจกต์ของ API key นี้ถูกปฏิเสธสิทธิ์ "
                    "(Your project has been denied access). "
                    "ให้สร้าง API key ใหม่จาก Google AI Studio หรือใช้ Google Cloud project อื่น"
                ) from exc
            if exc.code == 400 and "API_KEY_INVALID" in detail:
                raise RuntimeError(
                    "Gemini API key ไม่ถูกต้อง หรือมีตัวอักษรเกิน/คีย์ถูกปิดใช้งาน "
                    "ให้ตรวจสอบหรือสร้าง key ใหม่"
                ) from exc

            if exc.code in retryable_codes and attempt < GEMINI_RETRY_COUNT - 1:
                if _gemini_skip_to_next_model(exc.code, detail):
                    raise RuntimeError(
                        f"Gemini REST API ({model_name}) error {exc.code}: {detail[:800]}"
                    ) from exc
                time.sleep(_gemini_retry_delay_sec(detail, attempt))
                continue

            raise RuntimeError(
                f"Gemini REST API ({model_name}) error {exc.code}: {detail[:800]}"
            ) from exc

    if data is None:
        raise RuntimeError(
            f"Gemini REST API ({model_name}) ไม่สำเร็จ: {last_detail[:800]}"
        )

    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Gemini REST API ไม่คืนข้อความที่อ่านได้: "
            + json.dumps(data, ensure_ascii=False)[:800]
        ) from exc
    return "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()


def call_gemini_generate_text(
    api_key: str, system_instruction: str, prompt: str
) -> str:
    """ลอง REST ทุกโมเดลในรายการ + retry 503; จากนั้นค่อยลอง SDK ถ้ามี."""
    errors: list[str] = []
    for model_name in get_gemini_model_candidates():
        try:
            return call_gemini_with_rest_api(
                api_key,
                system_instruction,
                prompt,
                model_name=model_name,
            )
        except Exception as exc:
            errors.append(f"REST ({model_name}): {exc}")

    if _legacy_gemini_sdk_available():
        for model_name in get_gemini_model_candidates():
            try:
                return call_gemini_with_legacy_sdk(
                    api_key, system_instruction, prompt, model_name=model_name
                )
            except Exception as exc:
                errors.append(f"legacy SDK ({model_name}): {exc}")
    else:
        errors.append(
            "legacy SDK: ไม่พร้อมใช้ (Python 3.8 มักติดตั้งได้แค่ google-generativeai รุ่นเก่า "
            "— ใช้ REST เป็นหลัก)"
        )

    if _new_gemini_sdk_available():
        for model_name in get_gemini_model_candidates():
            try:
                return call_gemini_with_new_sdk(
                    api_key, system_instruction, prompt, model_name=model_name
                )
            except Exception as exc:
                errors.append(f"new SDK ({model_name}): {exc}")
    else:
        errors.append(
            "new SDK: ไม่พบ google-genai (ติดตั้งได้บน Python 3.10+ หรือใช้ REST)"
        )

    hint = ""
    joined = "\n".join(errors)
    if "429" in joined or "RESOURCE_EXHAUSTED" in joined or "quota" in joined.lower():
        hint = (
            "\n\nโควตา Gemini API เต็มหรือ key นี้ไม่มี free tier สำหรับโมเดลที่ลองแล้ว:\n"
            "  • สร้าง API key ใหม่ที่ https://aistudio.google.com/apikey\n"
            "  • ลองโมเดลเบา: set GEMINI_MODEL=gemini-2.5-flash-lite\n"
            "  • ตรวจสอบ usage: https://aistudio.google.com/\n"
            "  • ถ้าใช้ key เก่า/โปรเจกต์ที่ถูกจำกัด ให้เปลี่ยน key ใน sidebar"
        )
    elif "503" in joined or "UNAVAILABLE" in joined or "high demand" in joined.lower():
        hint = (
            "\n\nเซิร์ฟเวอร์ Gemini โหลดหนักชั่วคราว (503) — รอ 1–2 นาทีแล้วกดวิเคราะห์อีกครั้ง "
            "หรือตั้ง GEMINI_MODEL=gemini-2.5-flash-lite"
        )
    elif "404" in joined and "not found" in joined.lower():
        hint = (
            "\n\nโมเดล Gemini บางตัวถูกยกเลิกแล้ว (เช่น gemini-1.5-flash) "
            "— ใช้ gemini-2.5-flash หรือ gemini-2.5-flash-lite"
        )

    raise RuntimeError("เรียก Gemini ไม่สำเร็จ:\n" + joined + hint)


def call_gemini_extract(conversation: str) -> dict[str, str]:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "ไม่พบ Gemini API key: ตั้ง GEMINI_API_KEY / GOOGLE_API_KEY "
            "หรือสร้างไฟล์ .gemini_api_key ในโฟลเดอร์โปรเจกต์"
        )

    system_instruction, prompt = build_emr_prompt(conversation)
    raw_text = call_gemini_generate_text(api_key, system_instruction, prompt)

    data = extract_emr_fields_from_text(raw_text)
    if data and result_is_too_sparse(data, conversation):
        # ลองอีกครั้งด้วย prompt ที่ย้ำให้ละเอียดขึ้น แต่ยังจำกัด output ให้ไม่ยาวเกินไป
        system_instruction, prompt = build_emr_prompt(conversation, retry=True)
        raw_text = call_gemini_generate_text(api_key, system_instruction, prompt)
        data = extract_emr_fields_from_text(raw_text)

    if not data:
        raw_path = save_last_gemini_raw(raw_text)
        raise RuntimeError(
            "Gemini ไม่คืน JSON/รูปแบบข้อความที่อ่านได้ "
            f"(บันทึก raw response ไว้ที่ {raw_path})"
        )

    return {field: str(data.get(field) or "-").strip() or "-" for field in EMR_FIELDS}


def safe_filename_part(text: str) -> str:
    s = re.sub(r"[^\w\-ก-๙]+", "_", str(text or "").strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown"


def ensure_patient_dir() -> None:
    PATIENT_INFO_DIR.mkdir(parents=True, exist_ok=True)


def ensure_audio_input_dir() -> None:
    ensure_patient_dir()
    AUDIO_INPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_audio_input(audio_file: Any, *, source_name: str = "recorded_audio.wav") -> Path:
    """บันทึกเสียงจาก Streamlit ลงเครื่องก่อนส่งเข้า diarization/STT."""
    ensure_audio_input_dir()
    raw = audio_file.getvalue()
    suffix = Path(source_name or "").suffix.lower() or ".wav"
    if suffix not in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
        suffix = ".wav"
    file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_filename_part(Path(source_name).stem)}{suffix}"
    path = AUDIO_INPUT_DIR / file_name
    path.write_bytes(raw)
    return path


def _speaker_name_from_diarize_label(speaker: Any) -> str:
    text = str(speaker)
    match = re.search(r"(\d+)$", text)
    if match:
        return f"ผู้พูด {int(match.group(1)) + 1}"
    return text or "ผู้พูด"


def transcribe_audio_with_diarize_final(audio_path: Path) -> tuple[str, dict[str, Any]]:
    """
    ใช้ diarize_final.py สำหรับแยกผู้พูด แล้วใช้ NeMo ASR local สำหรับถอดเสียง
    แต่ละ segment เป็นข้อความบทสนทนาพร้อมเวลาและผู้พูด
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("ต้องติดตั้ง numpy สำหรับประมวลผลเสียง: python -m pip install numpy") from exc

    try:
        from diarize_final import (
            postprocess_diarization,
            preprocess_audio,
            run_diarization,
            save_diarization_to_csv,
        )
        from speech_to_text import (
            _mono_to_wav_bytes,
            _transcribe_one_wav_bytes_nemo,
        )
    except ImportError as exc:
        raise RuntimeError(
            "ยังขาด dependency สำหรับ diarization/STT ให้ติดตั้ง librosa scipy torch pyannote.audio "
            "และ nemo_toolkit[asr]\n"
            f"{exc}"
        ) from exc

    waveform, sr, audio_duration = preprocess_audio(str(audio_path), sr=16000)
    ann, diarization_time = run_diarization(
        waveform,
        sr,
        num_speakers=2,
        clustering_threshold=0.50,
        segmentation_params=None,
    )
    turns, confidences = postprocess_diarization(
        ann,
        min_merge_duration=0.08,
        merge_silence_threshold=0.25,
        overlap_detection=True,
        aggressive_split=True,
    )

    csv_path = audio_path.with_suffix(".diarization.csv")
    try:
        save_diarization_to_csv(
            turns,
            confidences,
            audio_duration,
            diarization_time,
            2,
            {
                "clustering_threshold": 0.50,
                "min_merge_duration": 0.08,
                "merge_silence_threshold": 0.25,
                "overlap_detection": True,
                "aggressive_split": True,
                "asr_backend": "nemo",
            },
            str(csv_path),
        )
    except Exception:
        csv_path = Path("")

    lines: list[str] = []
    for turn, _, speaker in turns:
        start = max(0.0, float(turn.start))
        end = min(float(turn.end), audio_duration)
        if end <= start:
            continue
        start_i = int(start * sr)
        end_i = min(int(end * sr), len(waveform))
        segment = np.asarray(waveform[start_i:end_i], dtype=np.float32)
        if len(segment) < int(0.15 * sr):
            continue
        wav_bytes = _mono_to_wav_bytes(segment, sr=sr)
        text = _transcribe_one_wav_bytes_nemo(wav_bytes).strip()
        if not text:
            continue
        lines.append(f"[ {start:5.1f}s-{end:5.1f}s ] {_speaker_name_from_diarize_label(speaker)}: {text}")

    transcript = "\n".join(lines).strip()
    transcript_path = audio_path.with_suffix(".transcript.txt")
    transcript_path.write_text(transcript, encoding="utf-8")

    return transcript, {
        "audio_path": str(audio_path),
        "transcript_path": str(transcript_path),
        "diarization_csv": str(csv_path) if str(csv_path) else "",
        "audio_duration": audio_duration,
        "segments": len(turns),
        "transcribed_segments": len(lines),
        "diarization_time": diarization_time,
    }


EMR_CSV_FIELDNAMES = [
    "record_id",
    "created_at",
    "ชื่อผู้ป่วย",
    "อายุ",
    "HN",
    "pdf_file",
    "pdf_path",
    "pdf_link",
    "audio_path",
    "transcript_path",
    "diarization_csv",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
    "บทสนทนา",
]


def _emr_record_files() -> list[Path]:
    if not PATIENT_INFO_DIR.is_dir():
        return []
    return sorted(p for p in PATIENT_INFO_DIR.glob("*.json") if p.is_file())


def rebuild_emr_csv_from_json(fieldnames: list[str] | None = None) -> Path:
    """สร้าง emr_records.csv ใหม่จากไฟล์ JSON ทุกเคสในโฟลเดอร์ patient_info/
    ใช้กรณี CSV เสีย/หาย เพราะ JSON เก็บ record เต็มเสมอ.
    """
    fields = fieldnames or EMR_CSV_FIELDNAMES
    ensure_patient_dir()
    csv_path = PATIENT_INFO_DIR / "emr_records.csv"

    rows: list[dict[str, Any]] = []
    for jpath in _emr_record_files():
        try:
            with open(jpath, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rec, dict) and rec.get("record_id"):
            rows.append(rec)

    rows.sort(key=lambda r: str(r.get("created_at") or r.get("record_id") or ""))

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in rows:
            writer.writerow({k: rec.get(k, "") for k in fields})
    return csv_path


def _emr_csv_needs_rebuild(csv_path: Path, fieldnames: list[str]) -> bool:
    """True ถ้าไฟล์ CSV ไม่อ่านได้ปกติ (header เพี้ยน, row ชนกัน, จำนวน row ไม่ตรงกับ JSON บนดิสก์)"""
    if not csv_path.is_file():
        return False
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = list(reader.fieldnames or [])
            data_rows = [row for row in reader if any((row.get(k) or "").strip() for k in row)]
    except Exception:
        return True

    if len(header) != len(fieldnames):
        return True
    for got, want in zip(header, fieldnames):
        if got != want:
            return True

    json_count = len(_emr_record_files())

    # ตรวจ record_id ของแต่ละ row ว่าอยู่ในรูป YYYYMMDD_HHMMSS (ที่แอปสร้าง)
    valid_id_count = 0
    for row in data_rows:
        rid = (row.get("record_id") or "").strip()
        if re.fullmatch(r"\d{8}_\d{6}", rid):
            valid_id_count += 1

    # ถ้า row ที่ valid น้อยกว่าจำนวน JSON บนดิสก์ → CSV ไม่ตรงความจริง ให้ rebuild
    if json_count > 0 and valid_id_count < json_count:
        return True

    return False


def _ensure_trailing_newline(csv_path: Path) -> None:
    """รับประกันว่าไฟล์ลงท้ายด้วย newline ก่อน append ไม่อย่างนั้น row ใหม่จะชน row เก่า."""
    if not csv_path.is_file():
        return
    try:
        size = csv_path.stat().st_size
    except OSError:
        return
    if size == 0:
        return
    try:
        with open(csv_path, "rb") as f:
            f.seek(-1, 2)
            last = f.read(1)
    except OSError:
        return
    if last not in (b"\n", b"\r"):
        try:
            with open(csv_path, "ab") as f:
                f.write(b"\r\n")
        except OSError:
            pass


def append_csv_record(record: dict[str, Any]) -> Path:
    ensure_patient_dir()
    csv_path = PATIENT_INFO_DIR / "emr_records.csv"
    fieldnames = EMR_CSV_FIELDNAMES

    # 1) ถ้าไฟล์เสีย ให้ rebuild จาก JSON ก่อน (ปลอดภัยกว่าพยายาม parse ของเสีย)
    if _emr_csv_needs_rebuild(csv_path, fieldnames):
        rebuild_emr_csv_from_json(fieldnames)

    # 2) migrate fieldnames ถ้ามีคอลัมน์ใหม่ที่ schema เก่ายังไม่มี
    if csv_path.is_file():
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            old_fieldnames = reader.fieldnames or []
            old_rows = [dict(row) for row in reader]
        if any(name not in old_fieldnames for name in fieldnames):
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in old_rows:
                    writer.writerow({k: row.get(k, "") for k in fieldnames})

    # 3) ป้องกัน row ชนกัน — รับประกัน newline ปลายไฟล์ก่อน append
    _ensure_trailing_newline(csv_path)

    new_file = not csv_path.is_file()
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in fieldnames})
    return csv_path


def find_pdf_font() -> Path | None:
    candidates = [
        Path(r"C:\Windows\Fonts\tahoma.ttf"),
        Path(r"C:\Windows\Fonts\THSarabunNew.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def patch_hashlib_usedforsecurity_compat() -> None:
    """
    Python/OpenSSL บางชุด (เช่น Python 3.8 บน Windows บางเครื่อง) ไม่รองรับ
    hashlib.md5(..., usedforsecurity=False) แต่ reportlab รุ่นใหม่อาจส่ง argument นี้เข้ามา
    จึง patch ให้ ignore argument นี้ก่อน import reportlab
    """
    for name in ("md5", "sha1", "sha256"):
        fn = getattr(hashlib, name, None)
        if fn is None or getattr(fn, "_emr_compat_patched", False):
            continue

        def wrapper(*args, _fn=fn, **kwargs):
            kwargs.pop("usedforsecurity", None)
            return _fn(*args, **kwargs)

        wrapper._emr_compat_patched = True  # type: ignore[attr-defined]
        setattr(hashlib, name, wrapper)


def save_record_pdf(record: dict[str, Any], pdf_path: Path) -> None:
    patch_hashlib_usedforsecurity_compat()

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as exc:
        raise RuntimeError(
            "ยังไม่มีแพ็กเกจ reportlab สำหรับสร้าง PDF ให้ติดตั้งด้วย: "
            "python -m pip install reportlab"
        ) from exc

    font_path = find_pdf_font()
    font_name = "Helvetica"
    if font_path is not None:
        font_name = "ThaiFont"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    def para(text: Any, style: ParagraphStyle) -> Paragraph:
        return Paragraph(escape(str(text or "-")).replace("\n", "<br/>"), style)

    def conversation_flowables(text: Any, body_style: ParagraphStyle, head_style: ParagraphStyle) -> list:
        """บทสนทนายาวต้องอยู่นอก Table — Paragraph ใน story แบ่งหน้าได้ ไม่ชน error cell too large."""
        raw = str(text or "").strip()
        if not raw:
            return []
        out: list = [
            Spacer(1, 6),
            Paragraph("บทสนทนาต้นฉบับ", head_style),
            Spacer(1, 4),
        ]
        lines = raw.splitlines()
        chunk_lines = 20
        for i in range(0, max(len(lines), 1), chunk_lines):
            block = "\n".join(lines[i : i + chunk_lines]) if lines else raw
            if not block.strip():
                continue
            out.append(para(block, body_style))
            out.append(Spacer(1, 3))
        return out

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.1 * cm,
        bottomMargin=1.1 * cm,
        title=f"EMR {record.get('HN', '')}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ThaiTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=15,
        leading=20,
        alignment=1,
        spaceAfter=6,
    )
    header_style = ParagraphStyle(
        "ThaiHeader",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#222222"),
    )
    normal_style = ParagraphStyle(
        "ThaiNormal",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
    )
    small_style = ParagraphStyle(
        "ThaiSmall",
        parent=normal_style,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#444444"),
    )

    story = [
        Paragraph("เวชระเบียนอัตโนมัติ (Electronic Medical Record)", title_style),
        Paragraph(f"วันที่บันทึก: {escape(str(record.get('created_at', '-')))}", small_style),
        Spacer(1, 8),
    ]

    report_rows = [
        [para("ชื่อผู้ป่วย", header_style), para(record.get("ชื่อผู้ป่วย", "-"), normal_style)],
        [para("อายุ", header_style), para(record.get("อายุ", "-"), normal_style)],
        [para("HN", header_style), para(record.get("HN", "-"), normal_style)],
        [para("Record ID", header_style), para(record.get("record_id", "-"), normal_style)],
    ]
    report_rows.extend(
        [para(field, header_style), para(record.get(field, "-"), normal_style)]
        for field in EMR_FIELDS
    )

    report_table = Table(report_rows, colWidths=[4.2 * cm, 13.0 * cm], hAlign="LEFT", repeatRows=0)
    report_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D6D6D6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(report_table)
    story.extend(conversation_flowables(record.get("บทสนทนา"), normal_style, header_style))
    story.extend(
        [
            Spacer(1, 8),
            Paragraph(
                "หมายเหตุ: รายงานนี้สร้างจากระบบช่วยสรุปอัตโนมัติ ควรตรวจทานโดยเภสัชกรก่อนใช้งานจริง",
                small_style,
            ),
        ]
    )

    doc.build(story)


def save_record(record: dict[str, Any]) -> tuple[Path, Path, Path]:
    ensure_patient_dir()
    record_id = record["record_id"]
    hn = safe_filename_part(record.get("HN", ""))
    name = safe_filename_part(record.get("ชื่อผู้ป่วย", ""))
    json_path = PATIENT_INFO_DIR / f"{record_id}_{hn}_{name}.json"
    pdf_path = PATIENT_INFO_DIR / f"{record_id}_{hn}_{name}.pdf"
    record["pdf_file"] = pdf_path.name
    record["pdf_path"] = str(pdf_path.resolve())
    record["pdf_link"] = pdf_path.resolve().as_uri()
    json_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_record_pdf(record, pdf_path)
    csv_path = append_csv_record(record)
    return json_path, csv_path, pdf_path


def load_saved_records() -> list[dict[str, str]]:
    csv_path = PATIENT_INFO_DIR / "emr_records.csv"

    # ถ้า CSV หาย/เสีย แต่มี JSON เก็บไว้ ให้ rebuild ก่อน
    try:
        if _emr_csv_needs_rebuild(csv_path, EMR_CSV_FIELDNAMES):
            rebuild_emr_csv_from_json(EMR_CSV_FIELDNAMES)
    except Exception:
        pass

    if not csv_path.is_file():
        return []
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except OSError:
        return []


def record_table_rows(records: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for r in records:
        rows.append(
            {
                "ID": r.get("record_id", ""),
                "name": r.get("ชื่อผู้ป่วย", ""),
                "อายุ": r.get("อายุ", ""),
                "HN": r.get("HN", ""),
                "วันที่บันทึก": r.get("created_at", ""),
                "PDF": r.get("pdf_file", ""),
                "pdf_path": r.get("pdf_path", ""),
            }
        )
    return rows


def filter_records(records: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    q = (query or "").strip().lower()
    if not q:
        return records
    out: list[dict[str, str]] = []
    for r in records:
        haystack = " ".join(str(v) for v in r.values()).lower()
        if q in haystack:
            out.append(r)
    return out


def init_state() -> None:
    for field in EMR_FIELDS:
        st.session_state.setdefault(field, "")
    st.session_state.setdefault("conversation_widget_id", 0)
    st.session_state.setdefault("last_audio_meta", {})
    st.session_state.setdefault("last_analysis_ok", False)
    st.session_state.setdefault("data_search_query", "")
    st.session_state.setdefault("analysis_cache", {})


def main() -> None:
    st.set_page_config(
        page_title="Automatic EMR Demo",
        page_icon="🩺",
        layout="wide",
    )
    init_state()

    st.title("Demo App ระบบบันทึกเวชระเบียนอัตโนมัติ (EMR)")
    st.caption(
        "กรอกข้อมูลผู้ป่วยเอง จากนั้นวางบทสนทนาและกด วิเคราะห์ด้วย AI "
        "เพื่อให้ Gemini ช่วยเติมฟอร์มเวชระเบียน"
    )

    with st.sidebar:
        st.header("การตั้งค่า")
        st.write(f"Model: `{get_gemini_model_name()}`")
        st.caption(
            "Fallback: "
            + ", ".join(f"`{m}`" for m in get_gemini_model_candidates()[1:])
        )
        api_key_override = st.text_input(
            "Gemini API key (ถ้าต้องการใช้ key ใหม่เฉพาะรอบนี้)",
            type="password",
            value=st.session_state.get("gemini_api_key_override", ""),
            help="ถ้าใส่ช่องนี้ แอปจะใช้ key นี้แทน .gemini_api_key / env",
        )
        st.session_state.gemini_api_key_override = api_key_override.strip()
        if get_gemini_api_key():
            st.success("พบ Gemini API key แล้ว")
        else:
            st.warning("ยังไม่พบ Gemini API key")
            st.caption("ตั้ง GEMINI_API_KEY หรือสร้างไฟล์ .gemini_api_key")
        st.divider()
        st.caption(f"บันทึกข้อมูลลง: `{PATIENT_INFO_DIR}`")

    tab_record, tab_log = st.tabs(["บันทึกเวชระเบียน", "LOG"])

    with tab_record:
        # ล้างค่าต้องทำก่อนสร้าง widget ที่ผูก key (เช่น conversation_text)
        # ไม่เช่นนั้นกด "ล้างผลวิเคราะห์" แล้วจะได้ StreamlitAPIException
        if st.session_state.pop("_pending_clear_emr", False):
            for field in EMR_FIELDS:
                st.session_state[field] = ""
            st.session_state["conversation_widget_id"] = int(
                st.session_state.get("conversation_widget_id", 0)
            ) + 1
            st.session_state["last_audio_meta"] = {}
            st.session_state["last_analysis_ok"] = False
            st.session_state["analysis_cache"] = {}

        st.header("1) Patient Info")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            patient_name = st.text_input("ชื่อผู้ป่วย", placeholder="เช่น นายสมชาย ใจดี")
        with c2:
            age = st.number_input("อายุ", min_value=0, max_value=130, value=30, step=1)
        with c3:
            hn = st.text_input("HN", placeholder="เช่น HN00123")

        st.header("2) Automation")
        st.write("วางบทสนทนา อัปโหลดไฟล์ข้อความ หรือบันทึกเสียงเพื่อถอดเป็นข้อความก่อนกดปุ่มวิเคราะห์")

        uploaded = st.file_uploader("อัปโหลดไฟล์บทสนทนา (.txt) ถ้ามี", type=["txt"])
        if uploaded is not None:
            uploaded_text = uploaded.getvalue().decode("utf-8", errors="replace")
            if st.button("นำข้อความจากไฟล์ .txt มาใส่ช่องบทสนทนา", use_container_width=True):
                st.session_state[conversation_widget_state_key()] = uploaded_text

        with st.expander("บันทึกเสียง / ถอดเสียงเป็นบทสนทนา", expanded=False):
            st.caption(
                "ระบบจะใช้ diarization จาก `diarize_final.py` เพื่อแบ่งผู้พูด "
                "และใช้ NeMo ASR `model_speech_to_text/typhoon-isan-asr-realtime.nemo` เพื่อถอดเสียง"
            )
            recorded_audio = None
            audio_input_fn = getattr(st, "audio_input", None)
            if audio_input_fn is not None:
                recorded_audio = audio_input_fn("บันทึกเสียงบทสนทนา")
            else:
                st.info("Streamlit เวอร์ชันนี้ยังไม่มี `st.audio_input` ให้ใช้อัปโหลดไฟล์เสียงแทน")

            uploaded_audio = st.file_uploader(
                "หรืออัปโหลดไฟล์เสียง",
                type=["wav", "mp3", "m4a", "flac", "ogg"],
                key="audio_conversation_file",
            )
            audio_source = recorded_audio or uploaded_audio
            if audio_source is not None:
                source_name = getattr(audio_source, "name", "recorded_audio.wav")
                st.audio(audio_source.getvalue())
                if st.button("ถอดเสียง + แยกผู้พูด แล้วใส่ช่องบทสนทนา", type="primary", use_container_width=True):
                    try:
                        audio_path = save_audio_input(audio_source, source_name=source_name)
                        with st.spinner("กำลัง diarize และถอดเสียงด้วย NeMo ASR อาจใช้เวลาสักครู่..."):
                            transcript, audio_meta = transcribe_audio_with_diarize_final(audio_path)
                    except Exception as exc:
                        st.error(str(exc))
                    else:
                        if transcript:
                            st.session_state[conversation_widget_state_key()] = transcript
                            st.session_state.last_audio_meta = audio_meta
                            st.success("ถอดเสียงสำเร็จและเติมลงช่องบทสนทนาแล้ว")
                            st.json(audio_meta, expanded=False)
                        else:
                            st.warning("ถอดเสียงเสร็จแล้ว แต่ยังไม่พบข้อความจากช่วงเสียงที่ตรวจได้")

        conversation = st.text_area(
            "บทสนทนา",
            key=conversation_widget_state_key(),
            height=260,
            placeholder=(
                "ตัวอย่าง:\n"
                "เภสัชกร: มีอาการอะไรคะ\n"
                "ผู้ป่วย: ปวดหัวข้างเดียว คลื่นไส้ เป็นไมเกรนอยู่แล้ว ไม่แพ้ยา..."
            ),
        )

        analyze_col, clear_col = st.columns([1, 1])
        with analyze_col:
            analyze_clicked = st.button("วิเคราะห์ด้วย AI", type="primary", use_container_width=True)
        with clear_col:
            if st.button("ล้างผลวิเคราะห์", use_container_width=True):
                st.session_state["_pending_clear_emr"] = True
                st.rerun()

        if analyze_clicked:
            if not conversation.strip():
                st.error("กรุณาใส่บทสนทนาก่อนวิเคราะห์")
            else:
                cache_key = analysis_cache_key(conversation)
                cached = st.session_state.analysis_cache.get(cache_key)
                if cached:
                    result = cached
                    st.info("ใช้ผลวิเคราะห์จาก cache")
                else:
                    with st.spinner("กำลังวิเคราะห์บทสนทนาด้วย Gemini..."):
                        try:
                            result = call_gemini_extract(conversation)
                        except Exception as exc:
                            st.session_state.last_analysis_ok = False
                            st.error(str(exc))
                            result = None
                        else:
                            st.session_state.analysis_cache[cache_key] = result
                if result:
                    for field in EMR_FIELDS:
                        if field in result:
                            st.session_state[field] = result[field]
                    st.session_state.last_analysis_ok = True
                    st.success("วิเคราะห์สำเร็จ สามารถตรวจแก้ก่อนบันทึกได้")

        st.header("3) EMR Form")
        left, right = st.columns(2)
        with left:
            st.text_area("ประวัติการแพ้ยา", key="ประวัติการแพ้ยา", height=120)
            st.text_area("โรคประจำตัว", key="โรคประจำตัว", height=120)
            st.text_area("ประวัติการจ่ายยา", key="ประวัติการจ่ายยา", height=120)
        with right:
            st.text_area("บันทึกทางการแพทย์", key="บันทึกทางการแพทย์", height=180)
            st.text_area("คำแนะนำจากเภสัช", key="คำแนะนำจากเภสัช", height=180)

        st.header("4) Save Record")
        st.caption("เมื่อบันทึก ระบบจะสร้าง PDF 1 ไฟล์ในเครื่อง และเพิ่ม log ลง CSV พร้อม path/link ไปยัง PDF")

        if st.button("บันทึกเวชระเบียน", type="primary", use_container_width=True):
            if not patient_name.strip() or not hn.strip():
                st.error("กรุณากรอกชื่อผู้ป่วยและ HN ก่อนบันทึก")
            else:
                created_at = datetime.now().isoformat(timespec="seconds")
                record_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                record = {
                    "record_id": record_id,
                    "created_at": created_at,
                    "ชื่อผู้ป่วย": patient_name.strip(),
                    "อายุ": int(age),
                    "HN": hn.strip(),
                    "บทสนทนา": conversation.strip(),
                }
                last_audio_meta = st.session_state.get("last_audio_meta") or {}
                if last_audio_meta:
                    record["audio_path"] = last_audio_meta.get("audio_path", "")
                    record["transcript_path"] = last_audio_meta.get("transcript_path", "")
                    record["diarization_csv"] = last_audio_meta.get("diarization_csv", "")
                for field in EMR_FIELDS:
                    record[field] = st.session_state.get(field, "").strip() or "-"

                try:
                    json_path, csv_path, pdf_path = save_record(record)
                except Exception as exc:
                    st.error(str(exc))
                    return
                st.success("บันทึกเวชระเบียนสำเร็จ")
                st.write("JSON:", str(json_path))
                st.write("CSV:", str(csv_path))
                st.write("PDF:", str(pdf_path))

                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "ดาวน์โหลด PDF",
                        data=f,
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        use_container_width=True,
                    )

                with st.expander("ดูข้อมูลที่บันทึก"):
                    st.json(record, expanded=False)

    with tab_log:
        st.header("LOG")
        st.caption("แสดง log จาก patient_info/emr_records.csv พร้อมค้นหาและดาวน์โหลด PDF รายเคส")
        records = load_saved_records()
        search_text = st.text_input(
            "ค้นหา",
            value=st.session_state.get("data_search_query", ""),
            placeholder="ค้นหา ID, name, HN, อายุ, เนื้อหาเวชระเบียน...",
            key="log_search_input",
        )
        search_col, clear_search_col = st.columns(2)
        with search_col:
            if st.button("Search", use_container_width=True):
                st.session_state.data_search_query = search_text.strip()
        with clear_search_col:
            if st.button("Clear", use_container_width=True):
                st.session_state.data_search_query = ""
                st.rerun()

        active_query = st.session_state.get("data_search_query", "").strip()
        shown_records = filter_records(records, active_query)
        st.caption(f"ทั้งหมด {len(records)} รายการ | แสดง {len(shown_records)} รายการ")
        csv_path = PATIENT_INFO_DIR / "emr_records.csv"
        if csv_path.is_file():
            with open(csv_path, "rb") as f:
                st.download_button(
                    "ดาวน์โหลด CSV log",
                    data=f,
                    file_name="emr_records.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        if shown_records:
            st.dataframe(
                record_table_rows(shown_records),
                use_container_width=True,
                hide_index=True,
                height=420,
            )
            st.subheader("ดาวน์โหลด PDF จาก LOG")
            for i, row in enumerate(shown_records):
                pdf_raw = row.get("pdf_path", "")
                pdf_path = Path(pdf_raw) if pdf_raw else Path()
                label = (
                    f"{row.get('record_id', '-')} | "
                    f"{row.get('ชื่อผู้ป่วย', '-')} | "
                    f"HN {row.get('HN', '-')}"
                )
                cols = st.columns([3, 1])
                cols[0].write(label)
                if pdf_path.is_file():
                    with open(pdf_path, "rb") as f:
                        cols[1].download_button(
                            "โหลด PDF",
                            data=f,
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            key=f"log_pdf_download_{i}_{row.get('record_id', '')}",
                            use_container_width=True,
                        )
                else:
                    cols[1].caption("ไม่พบ PDF")
        else:
            st.info("ยังไม่มีข้อมูล หรือไม่พบผลลัพธ์จากคำค้นหา")


if __name__ == "__main__":
    main()
