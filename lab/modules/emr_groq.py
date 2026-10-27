import json
import re
import os
import time
from typing import Any
from pathlib import Path
try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent

# ── Constants ────────────────────────────────────────────────────
EMR_FIELDS = [
    "บทสนทนาที่จัดเรียงแล้ว",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]

def get_groq_api_key() -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        candidates = [
            ROOT / ".groq_api_key",
            ROOT.parent / ".groq_api_key",
            ROOT / "pharmalog_offline_assets" / ".groq_api_key",
            ROOT / "pharmalog_offline_assets" / "api_keys" / ".groq_api_key",
            ROOT.parent / "pharmalog_offline_assets" / ".groq_api_key",
            ROOT.parent / "pharmalog_offline_assets" / "api_keys" / ".groq_api_key",
        ]
        for p in candidates:
            if p.exists():
                api_key = p.read_text(encoding="utf-8").strip()
                if api_key:
                    break
    return api_key


def check_credentials() -> tuple[bool, str]:
    api_key = get_groq_api_key()
    if api_key:
        return True, "Groq API Key is configured."
    return False, "Groq API Key is missing."

_RETRY_COUNT = 3
_RETRY_BASE_SEC = 2.0


# ── Prompt ───────────────────────────────────────────────────────
def _build_prompt(conversation: str, retry: bool = False) -> str:
    system = (
        "คุณเป็นผู้ช่วยเภสัชกรสำหรับสรุปบทสนทนาการซักประวัติและจ่ายยาเป็นเวชระเบียนคลินิก EMR\n"
        "ให้สกัดข้อมูลเฉพาะจากบทสนทนา ห้ามเดาข้อมูลที่ไม่มีในบทสนทนา\n"
        "ถ้าไม่พบข้อมูลให้ใส่ '-' และตอบเป็น JSON ภาษาไทยเท่านั้น\n"
    )
    retry_note = (
        "\nรอบนี้เป็นการวิเคราะห์ซ้ำเพราะรอบแรกข้อมูลน้อยเกินไป: "
        "ให้ตรวจบทสนทนาอย่างละเอียดและเติมช่องบันทึกทางการแพทย์/คำแนะนำจากเภสัชถ้ามีหลักฐานในบทสนทนา\n"
        if retry else ""
    )
    is_dual = "โครงสร้างคนพูด" in conversation or "Deepgram" in conversation
    if is_dual:
        task_desc = """คุณจะได้รับข้อมูล 2 ส่วน:
1. "ข้อความเนื้อหาภาษาไทย" (จาก Typhoon) ซึ่งคำศัพท์ถูกต้องแม่นยำ แต่เป็นข้อความติดกัน ไม่มีการแยกผู้พูด
2. "โครงสร้างคนพูด" (จาก Deepgram) ซึ่งแบ่งผู้พูด [Speaker 0], [Speaker 1] ได้แม่นยำตามเนื้อเสียงจริง แต่อาจสะกดคำผิดบ้าง

หน้าที่ของคุณ:
ให้นำ "เนื้อหาภาษาไทยที่ถูกต้องจากส่วนที่ 1" มาจัดเรียงบทสนทนาใหม่ โดยยึด "จังหวะและผู้พูดตามโครงสร้างของส่วนที่ 2" เป็นแม่แบบ (ใครเป็นเภสัชกร ใครเป็นผู้ป่วย วิเคราะห์จากบริบท)"""
        turns_principle = '- บทสนทนาที่จัดเรียงแล้ว: ต้องเป็นเนื้อหาจากส่วนที่ 1 ที่นำมาหั่นและใส่ "เภสัชกร:" / "ผู้ป่วย:" นำหน้าประโยคอย่างถูกต้องตามจังหวะของส่วนที่ 2'
    else:
        task_desc = "ให้วิเคราะห์บทสนทนาระหว่างเภสัชกรและผู้ป่วยต่อไปนี้ แล้วสกัดข้อมูลสรุปเป็นเวชระเบียนคลินิก (EMR)"
        turns_principle = '- บทสนทนาที่จัดเรียงแล้ว: บทสนทนาระหว่างเภสัชกรและผู้ป่วยที่จัดลำดับเรียบร้อยและอ่านเข้าใจง่าย'

    user_prompt = f"""{system}
{task_desc}
จากนั้นให้สกัดข้อมูลและสรุปเป็น JSON ภาษาไทยตาม key ต่อไปนี้เท่านั้น:

{{
  "บทสนทนาที่จัดเรียงแล้ว": "เภสัชกร: ...\\nผู้ป่วย: ...\\nเภสัชกร: ...",
  "ประวัติการแพ้ยา": "...",
  "โรคประจำตัว": "...",
  "ประวัติการจ่ายยา": "...",
  "บันทึกทางการแพทย์": "...",
  "คำแนะนำจากเภสัช": "..."
}}

หลักการ:
{turns_principle}
- ประวัติการแพ้ยา: ยาหรือสารที่ผู้ป่วยแพ้ พร้อมอาการแพ้ถ้ามี (หากปฏิเสธหรือไม่พบให้ใส่ "-")
- โรคประจำตัว: โรคเดิม/ภาวะประจำตัว/ยาที่สัมพันธ์กับโรคประจำตัว (หากไม่มีให้ใส่ "-")
- ประวัติการจ่ายยา: ยาที่เคยได้รับหรือกำลังใช้อยู่ก่อนการจ่ายครั้งนี้ (หากไม่มีให้ใส่ "-")
- บันทึกทางการแพทย์: อาการสำคัญ ระยะเวลา ความรุนแรง ข้อมูลที่เกี่ยวกับการพิจารณาจ่ายยา
- คำแนะนำจากเภสัช: ยาที่แนะนำหรือจ่าย วิธีใช้ คำเตือน การติดตามอาการ หรือการส่งต่อ
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


def _validate_dialogue_field(dialogue: str) -> str:
    if not dialogue or dialogue.strip() in ("", "-"):
        return "-"
    try:
        from pipeline import validate_speaker_roles
    except ImportError:
        try:
            from lab.pipeline import validate_speaker_roles
        except ImportError:
            return dialogue
    # Preserve colon format if input uses colon format
    use_colon = bool(re.search(r"(?:เภสัชกร|ผู้ป่วย|คนไข้)\s*:", dialogue)) and not bool(
        re.search(r"\[(?:เภสัชกร|ผู้ป่วย|คนไข้)\]", dialogue)
    )
    validated = validate_speaker_roles(dialogue)
    if use_colon:
        out_lines = []
        for line in validated.split("\n"):
            m = re.match(r"^\[(เภสัชกร|ผู้ป่วย)\]\s*(.*)$", line.strip())
            if m:
                out_lines.append(f"{m.group(1)}: {m.group(2)}")
            elif line.strip():
                out_lines.append(line.strip())
        return "\n".join(out_lines)
    return validated


def _parse_fields(raw: str) -> dict[str, str]:
    data = _extract_json(raw)
    if data:
        parsed = {f: str(data.get(f) or "-").strip() or "-" for f in EMR_FIELDS}
        if parsed.get("บทสนทนาที่จัดเรียงแล้ว", "-") != "-":
            parsed["บทสนทนาที่จัดเรียงแล้ว"] = _validate_dialogue_field(parsed["บทสนทนาที่จัดเรียงแล้ว"])
        return parsed

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
            if field != "บทสนทนาที่จัดเรียงแล้ว":
                value = re.sub(r"\n+", " ", value).strip()
            result[field] = value or "-"
    if result.get("บทสนทนาที่จัดเรียงแล้ว", "-") != "-":
        result["บทสนทนาที่จัดเรียงแล้ว"] = _validate_dialogue_field(result["บทสนทนาที่จัดเรียงแล้ว"])
    return result


def _is_sparse(result: dict[str, str], conversation: str) -> bool:
    if len(conversation.strip()) < 80:
        return False
    vals = {f: str(result.get(f, "")).strip() for f in EMR_FIELDS}
    empty = sum(1 for v in vals.values() if v in ("", "-"))
    missing_core = vals.get("บันทึกทางการแพทย์", "-") in ("", "-") and vals.get("คำแนะนำจากเภสัช", "-") in ("", "-")
    return empty >= 5 or missing_core



# ── API call ──────────────────────────────────────────────────
def _call_groq(api_key: str, model_name: str, prompt: str) -> str:
    if Groq is None:
        raise RuntimeError("ยังไม่ได้ติดตั้งแพ็กเกจ groq (pip install groq)")
    client = Groq(api_key=api_key)
    models_to_try = [
        model_name,
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-20b",
    ]
    # Remove duplicates while preserving order
    seen = set()
    ordered_models = []
    for m in models_to_try:
        if m not in seen:
            seen.add(m)
            ordered_models.append(m)

    last_exc = None
    for m_name in ordered_models:
        for attempt in range(max(1, _RETRY_COUNT)):
            try:
                chat_completion = client.chat.completions.create(
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                    model=m_name,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                if chat_completion and chat_completion.choices:
                    return chat_completion.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                if "429" in str(exc):
                    # Rate limit reached for this model, break attempt loop and fall back to next model
                    break
                if attempt < _RETRY_COUNT - 1:
                    time.sleep(min(_RETRY_BASE_SEC * (2 ** attempt), 12.0))
                    continue

    raise RuntimeError(f"เรียก Groq API ไม่สำเร็จ: {last_exc}") from last_exc


# ── Public API ───────────────────────────────────────────────────
def extract_emr(conversation: str) -> dict[str, str]:
    """
    Main entry point: extract EMR fields from a conversation string using Groq.
    Returns a dict with EMR_FIELDS as keys.
    """
    if not conversation or not conversation.strip():
        return {f: "-" for f in EMR_FIELDS}

    api_key = get_groq_api_key()
    model_name = "openai/gpt-oss-120b"

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
