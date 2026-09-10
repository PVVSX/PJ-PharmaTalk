"""
EMR Extraction Module (Azure OpenAI)
Self-contained extraction logic with its own prompt and OpenAI client.
No dependency on the old streamlit_emr_app.py.
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────
EMR_FIELDS = [
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / "result_record" / ".azure_openai_env"
_DEFAULT_API_VERSION = "2024-02-15-preview"
_DEFAULT_DEPLOYMENT = "gpt-4o-mini"
_MAX_TOKENS = 4096
_RETRY_COUNT = 3
_RETRY_BASE_SEC = 2.0


# ── Credentials ──────────────────────────────────────────────────
def _load_env_file() -> None:
    """Read .azure_openai_env once and set missing env vars."""
    if not _ENV_FILE.is_file():
        return
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip().lstrip("\ufeff")
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def get_credentials() -> dict[str, str]:
    _load_env_file()
    return {
        "api_key": os.environ.get("AZURE_OPENAI_API_KEY", "").strip(),
        "endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip(),
        "api_version": os.environ.get("AZURE_OPENAI_API_VERSION", _DEFAULT_API_VERSION).strip(),
        "deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", _DEFAULT_DEPLOYMENT).strip(),
    }


# ── Prompt ───────────────────────────────────────────────────────
def _build_prompt(conversation: str, retry: bool = False) -> tuple[str, str]:
    system = (
        "คุณเป็นผู้ช่วยเภสัชกรสำหรับสรุปบทสนทนาเป็นเวชระเบียน EMR "
        "ให้สกัดข้อมูลเฉพาะจากบทสนทนา ห้ามเดาข้อมูลที่ไม่มีในบทสนทนา "
        "ถ้าไม่พบข้อมูลให้ใส่ '-' และตอบเป็น JSON เท่านั้น"
    )
    retry_note = (
        "\nรอบนี้เป็นการวิเคราะห์ซ้ำเพราะรอบแรกข้อมูลน้อยเกินไป: "
        "ให้ตรวจบทสนทนาอย่างละเอียดและเติมช่องบันทึกทางการแพทย์/คำแนะนำจากเภสัชถ้ามีหลักฐานในบทสนทนา\n"
        if retry else ""
    )
    user_prompt = f"""จากบทสนทนาต่อไปนี้ ให้สรุปเป็น JSON ภาษาไทยตาม key ต่อไปนี้เท่านั้น:

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
{conversation}"""
    return system, user_prompt


# ── JSON extraction helpers ──────────────────────────────────────
def _extract_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            c = re.sub(r",\s*([}\]])", r"\1", m.group(0))
            v = json.loads(c)
            return v if isinstance(v, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def _parse_fields(raw: str) -> dict[str, str]:
    data = _extract_json(raw)
    if data:
        return {f: str(data.get(f) or "-").strip() or "-" for f in EMR_FIELDS}

    # Fallback: regex parse
    text = (raw or "").strip()
    if not text:
        return {}
    result: dict[str, str] = {}
    field_pattern = "|".join(re.escape(f) for f in EMR_FIELDS)
    for field in EMR_FIELDS:
        pattern = (
            rf'[""]?{re.escape(field)}[""]?\s*[:：]\s*'
            rf'(?P<value>[\s\S]*?)'
            rf'(?=\n\s*(?:[""]?(?:{field_pattern})[""]?\s*[:：])|\Z)'
        )
        m = re.search(pattern, text)
        if m:
            value = m.group("value").strip().strip(',"\' \n\r\t')
            value = re.sub(r"\n+", " ", value).strip()
            result[field] = value or "-"
    return result


def _is_sparse(result: dict[str, str], conversation: str) -> bool:
    if len(conversation.strip()) < 80:
        return False
    vals = {f: str(result.get(f, "")).strip() for f in EMR_FIELDS}
    empty = sum(1 for v in vals.values() if v in ("", "-"))
    missing_core = vals.get("บันทึกทางการแพทย์", "-") in ("", "-") and vals.get("คำแนะนำจากเภสัช", "-") in ("", "-")
    return empty >= 3 or missing_core


# ── OpenAI call ──────────────────────────────────────────────────
def _call_openai(creds: dict, system: str, user: str) -> str:
    try:
        from openai import AzureOpenAI
    except ImportError as exc:
        raise RuntimeError("ไม่พบ openai SDK กรุณาติดตั้ง: pip install openai") from exc

    client = AzureOpenAI(
        api_key=creds["api_key"],
        api_version=creds["api_version"],
        azure_endpoint=creds["endpoint"],
    )

    for attempt in range(max(1, _RETRY_COUNT)):
        try:
            resp = client.chat.completions.create(
                model=creds["deployment"],
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            if "429" in str(exc) and attempt < _RETRY_COUNT - 1:
                time.sleep(min(_RETRY_BASE_SEC * (2 ** attempt), 12.0))
                continue
            raise RuntimeError(f"เรียก Azure OpenAI ไม่สำเร็จ: {exc}") from exc
    return ""


# ── Public API ───────────────────────────────────────────────────
def check_credentials() -> tuple[bool, str]:
    """Check if Azure OpenAI credentials are configured."""
    creds = get_credentials()
    if not creds["api_key"]:
        return False, "ไม่พบ API Key (AZURE_OPENAI_API_KEY)"
    if not creds["endpoint"]:
        return False, "ไม่พบ Endpoint (AZURE_OPENAI_ENDPOINT)"
    return True, "พร้อมใช้งาน"


def extract_emr(conversation: str) -> dict[str, str]:
    """
    Main entry point: extract EMR fields from a conversation string.
    Returns a dict with EMR_FIELDS as keys.
    """
    if not conversation or not conversation.strip():
        return {f: "-" for f in EMR_FIELDS}

    creds = get_credentials()
    if not creds["api_key"] or not creds["endpoint"]:
        raise RuntimeError(
            "ไม่พบ Azure OpenAI API Key หรือ Endpoint\n"
            "กรุณาไปที่แท็บ '⚙️ ตั้งค่า' เพื่อกรอกข้อมูล"
        )

    system, user = _build_prompt(conversation)
    raw = _call_openai(creds, system, user)
    data = _parse_fields(raw)

    if data and _is_sparse(data, conversation):
        system2, user2 = _build_prompt(conversation, retry=True)
        raw2 = _call_openai(creds, system2, user2)
        data = _parse_fields(raw2)

    if not data:
        raise RuntimeError("Azure OpenAI ไม่คืนข้อมูลในรูปแบบที่อ่านได้")

    return {f: str(data.get(f) or "-").strip() or "-" for f in EMR_FIELDS}
