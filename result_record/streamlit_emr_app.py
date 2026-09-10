# -*- coding: utf-8 -*-
"""
Demo App: Automatic Electronic Medical Record (EMR)

Run:
  streamlit run streamlit_emr_app.py

Azure OpenAI configuration:
  - set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT_NAME, or
  - create .azure_openai_env in this project folder (KEY=VALUE format)

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
AZURE_ENV_FILE = BASE / ".azure_openai_env"

# Default values if not in env
DEFAULT_AZURE_API_VERSION = "2024-02-15-preview"
DEFAULT_AZURE_DEPLOYMENT = "gpt-4o-mini"
AZURE_MAX_OUTPUT_TOKENS = int(os.environ.get("AZURE_MAX_OUTPUT_TOKENS", "4096"))
AZURE_RETRY_COUNT = int(os.environ.get("AZURE_RETRY_COUNT", "3"))
AZURE_RETRY_BASE_SEC = float(os.environ.get("AZURE_RETRY_BASE_SEC", "2"))

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


def load_azure_env_from_file() -> None:
    if not AZURE_ENV_FILE.is_file():
        return
    try:
        for line in AZURE_ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip().lstrip("\ufeff")
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def get_azure_credentials() -> dict[str, str]:
    load_azure_env_from_file()
    api_key = (
        st.session_state.get("azure_api_key_override", "")
        or os.environ.get("AZURE_OPENAI_API_KEY", "")
    ).strip()
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_AZURE_API_VERSION).strip()
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", DEFAULT_AZURE_DEPLOYMENT).strip()
    return {
        "api_key": api_key,
        "endpoint": endpoint,
        "api_version": api_version,
        "deployment": deployment,
    }


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
    deployment = get_azure_credentials()["deployment"]
    raw = f"{deployment}\n{conversation}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def save_last_raw_response(raw_text: str) -> Path:
    ensure_patient_dir()
    p = PATIENT_INFO_DIR / "last_azure_raw.txt"
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


def call_azure_openai_generate_text(
    creds: dict[str, str], system_instruction: str, prompt: str
) -> str:
    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise RuntimeError("ไม่พบ openai SDK กรุณาติดตั้งผ่าน: pip install openai") from exc

    client = AzureOpenAI(
        api_key=creds["api_key"],
        api_version=creds["api_version"],
        azure_endpoint=creds["endpoint"],
    )

    for attempt in range(max(1, AZURE_RETRY_COUNT)):
        try:
            response = client.chat.completions.create(
                model=creds["deployment"],
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=AZURE_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            return content or ""
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg and attempt < AZURE_RETRY_COUNT - 1:
                time.sleep(min(AZURE_RETRY_BASE_SEC * (2**attempt), 12.0))
                continue
            raise RuntimeError(f"เรียก Azure OpenAI ไม่สำเร็จ:\n{err_msg}") from exc
    return ""


def call_azure_openai_extract(conversation: str) -> dict[str, str]:
    creds = get_azure_credentials()
    if not creds["api_key"] or not creds["endpoint"]:
        raise RuntimeError(
            "ไม่พบ Azure OpenAI API key หรือ Endpoint: "
            "ตั้งค่า AZURE_OPENAI_API_KEY และ AZURE_OPENAI_ENDPOINT ในไฟล์ .azure_openai_env"
        )

    system_instruction, prompt = build_emr_prompt(conversation)
    raw_text = call_azure_openai_generate_text(creds, system_instruction, prompt)

    data = extract_emr_fields_from_text(raw_text)
    if data and result_is_too_sparse(data, conversation):
        system_instruction, prompt = build_emr_prompt(conversation, retry=True)
        raw_text = call_azure_openai_generate_text(creds, system_instruction, prompt)
        data = extract_emr_fields_from_text(raw_text)

    if not data:
        raw_path = save_last_raw_response(raw_text)
        raise RuntimeError(
            "Azure OpenAI ไม่คืน JSON/รูปแบบข้อความที่อ่านได้ "
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
        st.write(f"Deployment: `{get_azure_credentials()['deployment']}`")
        api_key_override = st.text_input(
            "Azure API Key (เฉพาะรอบนี้)",
            type="password",
            value=st.session_state.get("azure_api_key_override", ""),
            help="ถ้าใส่ช่องนี้ แอปจะใช้ key นี้แทน .azure_openai_env",
        )
        st.session_state.azure_api_key_override = api_key_override.strip()
        
        creds = get_azure_credentials()
        if creds["api_key"] and creds["endpoint"]:
            st.success("พบ Azure OpenAI API Key แล้ว")
        else:
            st.warning("ยังไม่พบ Azure API Key หรือ Endpoint")
            st.caption("ตั้งค่าในไฟล์ .azure_openai_env")
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
                    with st.spinner("กำลังวิเคราะห์บทสนทนาด้วย Azure OpenAI..."):
                        try:
                            result = call_azure_openai_extract(conversation)
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
