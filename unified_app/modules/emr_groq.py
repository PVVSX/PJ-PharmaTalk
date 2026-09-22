import json
import re
import os
import time
from typing import Any
from groq import Groq

# ── Constants ────────────────────────────────────────────────────
EMR_FIELDS = [
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]

_RETRY_COUNT = 3
_RETRY_BASE_SEC = 2.0


# ── Prompt ───────────────────────────────────────────────────────
def _build_prompt(conversation: str, retry: bool = False) -> str:
    system = (
        "คุณเป็นผู้ช่วยเภสัชกรสำหรับสรุปบทสนทนาเป็นเวชระเบียน EMR\n"
        "ให้สกัดข้อมูลเฉพาะจากบทสนทนา ห้ามเดาข้อมูลที่ไม่มีในบทสนทนา\n"
        "ถ้าไม่พบข้อมูลให้ใส่ '-' และตอบเป็น JSON เท่านั้น\n"
    )
    retry_note = (
        "\nรอบนี้เป็นการวิเคราะห์ซ้ำเพราะรอบแรกข้อมูลน้อยเกินไป: "
        "ให้ตรวจบทสนทนาอย่างละเอียดและเติมช่องบันทึกทางการแพทย์/คำแนะนำจากเภสัชถ้ามีหลักฐานในบทสนทนา\n"
        if retry else ""
    )
    user_prompt = f"""{system}
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
{conversation}"""
    return user_prompt


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


# ── API call ──────────────────────────────────────────────────
def _call_groq(api_key: str, model_name: str, prompt: str) -> str:
    client = Groq(api_key=api_key)
    
    for attempt in range(max(1, _RETRY_COUNT)):
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=model_name,
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return chat_completion.choices[0].message.content or ""
        except Exception as exc:
            if "429" in str(exc) and attempt < _RETRY_COUNT - 1:
                time.sleep(min(_RETRY_BASE_SEC * (2 ** attempt), 12.0))
                continue
            raise RuntimeError(f"เรียก Groq API ไม่สำเร็จ: {exc}") from exc
    return ""


# ── Public API ───────────────────────────────────────────────────
def extract_emr(conversation: str) -> dict[str, str]:
    """
    Main entry point: extract EMR fields from a conversation string using Groq.
    Returns a dict with EMR_FIELDS as keys.
    """
    if not conversation or not conversation.strip():
        return {f: "-" for f in EMR_FIELDS}

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        # Fallback to look for .groq_api_key in project root
        try:
            from unified_app.modules.config import ROOT
            key_file = ROOT / ".groq_api_key"
            if key_file.exists():
                api_key = key_file.read_text(encoding="utf-8").strip()
        except ImportError:
            pass

    model_name = "openai/gpt-oss-120b" # Using available model on Groq

    if not api_key:
        raise RuntimeError("ไม่พบ Groq API Key (ตั้งค่า GROQ_API_KEY หรือ .groq_api_key)")

    prompt = _build_prompt(conversation)
    raw = _call_groq(api_key, model_name, prompt)
    data = _parse_fields(raw)

    if data and _is_sparse(data, conversation):
        prompt2 = _build_prompt(conversation, retry=True)
        raw2 = _call_groq(api_key, model_name, prompt2)
        data = _parse_fields(raw2)

    if not data:
        raise RuntimeError("Groq ไม่คืนข้อมูลในรูปแบบที่อ่านได้")

    return {f: str(data.get(f) or "-").strip() or "-" for f in EMR_FIELDS}
