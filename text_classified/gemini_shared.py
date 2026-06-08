# -*- coding: utf-8 -*-
from __future__ import annotations

# ใช้ร่วมกับ classify_gemini_refine.py / classify_gemini_extract.py
import os
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
# transcript จากโปรเจกต์: text_classified/data/*.txt
DATA_DIR = (BASE / "data").resolve()


def list_data_txt_files() -> list[Path]:
    """รายการไฟล์ .txt ใน text_classified/data (เรียงชื่อ)"""
    if not DATA_DIR.is_dir():
        return []
    return sorted(p for p in DATA_DIR.glob("*.txt") if p.is_file())


def filter_txt_files(paths: list[Path]) -> list[Path]:
    """คงเฉพาะไฟล์ .txt"""
    return [p for p in paths if p.suffix.lower() == ".txt" and p.is_file()]

# โมเดล Gemini (เปลี่ยนได้ด้วย GEMINI_MODEL)
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
# ไฟล์เก็บ key (บรรทัดแรก = key) ถ้าไม่ตั้ง GEMINI_API_KEY / GOOGLE_API_KEY
GEMINI_KEY_FILE = BASE / ".gemini_api_key"


def _read_key_from_file() -> str:
    if not GEMINI_KEY_FILE.is_file():
        return ""
    try:
        for line in GEMINI_KEY_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                return s
    except OSError:
        pass
    return ""


def get_gemini_api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        key = _read_key_from_file()
    if not key:
        raise SystemExit(
            "ไม่พบ API key — เลือกอย่างใดอย่างหนึ่ง:\n"
            "  1) PowerShell: $env:GEMINI_API_KEY=\"<key>\"\n"
            "     CMD: set GEMINI_API_KEY=<key>\n"
            f"  2) สร้างไฟล์ {GEMINI_KEY_FILE.name} ในโฟลเดอร์ text_classified\n"
            "     ใส่ key บรรทัดเดียว (บรรทัดที่ขึ้นต้นด้วย # จะถือว่า comment)\n"
            "อย่า commit key ลง git; ถ้า key รั่วให้หมุนใหม่ใน Google AI Studio"
        )
    return key


def get_gemini_model_name() -> str:
    return (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


# บทสนทนาแบบสคริปต์ (ไม่มี timestamp) เช่น dialogue_005.txt
_DIALOGUE_SPEAKER_LINE = re.compile(
    r"^\s*(เภสัชกร|คนไข้|แพทย์|พยาบาล|ผู้ป่วย|ลูกค้า)\s*:\s*(.*)$"
)


def parse_transcript_segments(path: str) -> list[str]:
    """แยกเป็นท่อนตามผู้พูด — ใช้ตัดท่อนที่ทำให้ API บล็อกได้

    รองรับสองรูปแบบ:
    1) ASR + timestamp: ``[ 0.5s- 1.6s ] ผู้พูด 2 : ข้อความ``
    2) สคริปต์บทสนทนา: ``เภสัชกร: ...`` / ``คนไข้: ...`` (บรรทัดต่อเนื่องที่ไม่มีป้ายผู้พูดจะต่อท้ายท่อนก่อนหน้า)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = [ln.strip() for ln in raw_lines if ln.strip()]

    parts: list[str] = []
    for line in lines:
        m = re.match(r"\[\s*[\d.]+s\s*-\s*[\d.]+s\s*\]\s*ผู้พูด\s*\d+\s*:\s*(.+)", line)
        if m:
            t = m.group(1).strip()
            if t and t != "(ไม่มีข้อความ)":
                parts.append(t)

    if parts:
        return parts

    # รูปแบบสคริปต์: เก็บทั้งบทบาท + ข้อความ เพื่อให้โมเดลรู้ว่าใครพูด
    for line in lines:
        m = _DIALOGUE_SPEAKER_LINE.match(line)
        if m:
            role, text = m.group(1), m.group(2).strip()
            if text:
                parts.append(f"{role}: {text}")
        elif parts:
            parts[-1] = f"{parts[-1]} {line}"
        else:
            parts.append(line)
    return parts


def parse_transcript(path: str) -> str:
    return " ".join(parse_transcript_segments(path))


def is_gemini_input_blocked_error(exc: BaseException) -> bool:
    """True ถ้า Gemini ปฏิเสธอินพุต (PROHIBITED_CONTENT / prompt_block_reason=4)"""
    s = str(exc)
    if "prompt_block_reason=4" in s:
        return True
    if "PROHIBITED_CONTENT" in s:
        return True
    low = s.lower()
    return "prohibited" in low and "content" in low


def _try_get_response_text(resp) -> str:
    """ดึงข้อความจาก response (บางกรณี resp.text ว่างแต่มี parts)"""
    try:
        t = getattr(resp, "text", None)
        if t:
            return t
    except (ValueError, AttributeError):
        pass
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        return ""
    content = getattr(cands[0], "content", None)
    parts = getattr(content, "parts", None) if content else None
    if not parts:
        return ""
    chunks = []
    for p in parts:
        if getattr(p, "text", None):
            chunks.append(p.text)
    return "".join(chunks)


# BlockReason (google.ai.generativelanguage): 4 = PROHIBITED_CONTENT — กรองระดับอินพุต ไม่ใช่แค่ safety ตอนตอบ
_PROMPT_BLOCK_REASON_TH = {
    0: "ไม่ระบุ",
    1: "SAFETY",
    2: "อื่นๆ",
    3: "BLOCKLIST",
    4: "PROHIBITED_CONTENT (เนื้อหาถูกจำกัดนโยบาย — มักเกิดจากคำในสคริปต์ที่ถอดเสียงผิดหรือถูกตีความผิด)",
}


def _prompt_block_reason_code(pf) -> int | None:
    if not pf:
        return None
    br = getattr(pf, "block_reason", None)
    if br is None:
        return None
    try:
        return int(br)
    except (TypeError, ValueError):
        return getattr(br, "value", None) if hasattr(br, "value") else None


def _gemini_failure_detail(resp) -> str:
    bits = []
    pf = getattr(resp, "prompt_feedback", None)
    if pf:
        br = getattr(pf, "block_reason", None)
        if br is not None:
            code = _prompt_block_reason_code(pf)
            th = _PROMPT_BLOCK_REASON_TH.get(code, "") if code is not None else ""
            bits.append(f"prompt_block_reason={br}" + (f" ({th})" if th else ""))
    cands = getattr(resp, "candidates", None) or []
    if cands:
        c0 = cands[0]
        fr = getattr(c0, "finish_reason", None)
        if fr is not None:
            bits.append(f"finish_reason={fr}")
        sr = getattr(c0, "safety_ratings", None)
        if sr:
            bits.append(f"safety_ratings={sr}")
    return "; ".join(bits) if bits else "ไม่มีรายละเอียดเพิ่ม"


def _sanitize_asr_for_prohibited_filter(text: str) -> str:
    """แทนที่ลายคำจาก ASR ที่มักทำให้ Gemini บล็อกอินพุตเป็น PROHIBITED_CONTENT (คำฟังผิดในบริบทเด็ก/การถ่าย/นม)."""
    if not text:
        return text
    t = text
    # ลำดับสำคัญ: แพทเทิร์นเฉพาะก่อน แล้วค่อยกว้างขึ้น
    replacements: list[tuple[str, str]] = [
        # ลำดับยาว→สั้น: วลีที่ ASR ฟังผิดมักไปชน PROHIBITED_CONTENT
        (
            "อยากเฮ็ดให้อุ้มคือปากก็สิผ ตาย",
            "[ถ้อยคำจากเสียงฟังไม่ชัด-บริบทคลินิก]",
        ),
        ("อยากเฮ็ดให้อุ้มคือปากก็สิผ", "[ถ้อยคำจากเสียงฟังไม่ชัด-บริบทคลินิก]"),
        ("บักอ๊อดหี้", "บักอ๊อด[ถ้อยคำฟังไม่ชัด-คาดว่าชื่อยา/อาการ]"),
        ("บักอ๊อดหี", "บักอ๊อด[ถ้อยคำฟังไม่ชัด]"),
        # ห้ามคงคำว่า ดูด ไว้ — ยังถูกกรองได้แม้ตามด้วยคำอธิบาย
        (
            "ดูดใส่ลิงให้น้องค่อยต้อนให้ซองมันกําไร",
            "[แนะนำการป้อนนมหรือยา-เสียงถอดความไม่ชัด]",
        ),
        ("ดูดใส่ลิง", "[ป้อนขวดนมหรือนม-เสียงฟังไม่ชัด]"),
        ("จิกเอา", "ให้กินทีละน้อย[เสียงฟังไม่ชัด]"),
    ]
    for a, b in replacements:
        if a in t:
            t = t.replace(a, b)
    return t


def _wrap_clinical_transcript(user_text: str) -> str:
    return (
        "บริบท: ข้อความต่อไปนี้เป็นบันทึกการสนทนาในคลินิก/ร้านยาที่ถอดความด้วยเครื่อง (ASR) "
        "ภาษาไทย อาจมีคำฟังผิด ความหมายทั้งหมดเกี่ยวกับการดูแลสุขภาพและยาเท่านั้น "
        "ไม่มีเจตนาเนื้อหาอื่น\n\n"
        "บทสนทนา:\n\n"
        f"{user_text}"
    )


def _safety_settings_all(threshold):
    """threshold เช่น HarmBlockThreshold.BLOCK_ONLY_HIGH / BLOCK_NONE"""
    from google.generativeai.types import HarmCategory, HarmBlockThreshold

    th = threshold
    return [
        {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": th},
        {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": th},
        {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": th},
        {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": th},
    ]


def call_gemini(system_instruction: str, user_text: str, temperature: float = 0.2) -> str:
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise ImportError(
            "ไม่มีแพ็กเกจ google.generativeai — ติดตั้งด้วย Python ตัวเดียวกับที่รันสคริปต์:\n"
            "  python -m pip install -r text_classified/requirements.txt\n"
            "หรือ: python -m pip install google-generativeai"
        ) from e

    from google.generativeai.types import HarmBlockThreshold

    genai.configure(api_key=get_gemini_api_key())
    model = genai.GenerativeModel(
        model_name=get_gemini_model_name(),
        system_instruction=system_instruction,
    )
    gen_cfg = {
        "temperature": temperature,
        "max_output_tokens": 8192,
    }

    def _one_call(utext: str, threshold) -> tuple:
        safety = _safety_settings_all(threshold)
        r = model.generate_content(
            utext,
            generation_config=gen_cfg,
            safety_settings=safety,
        )
        return r, _try_get_response_text(r).strip()

    # บันทึกทางการแพทย์มักถูก safety ตัด — ลอง BLOCK_ONLY_HIGH ก่อน แล้วค่อย BLOCK_NONE
    for threshold in (HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmBlockThreshold.BLOCK_NONE):
        resp, text = _one_call(user_text, threshold)
        if text:
            return text

    # อินพุตโดน PROHIBITED_CONTENT (เช่น คำจาก ASR ฟังผิด) — ลองห่อบริบท + แทนที่ลายคำที่พบบ่อย แล้วเรียกอีกรอบ
    code = _prompt_block_reason_code(getattr(resp, "prompt_feedback", None))
    if code == 4:
        softened = _sanitize_asr_for_prohibited_filter(user_text)
        wrapped = _wrap_clinical_transcript(softened)
        for threshold in (HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmBlockThreshold.BLOCK_NONE):
            resp, text = _one_call(wrapped, threshold)
            if text:
                return text

    detail = _gemini_failure_detail(resp)
    raise RuntimeError(
        "Gemini ไม่คืนข้อความ (อาจถูกบล็อก safety, เนื้อหาว่าง หรือโมเดลไม่ตอบ). "
        f"รายละเอียด: {detail}"
    )
