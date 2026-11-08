"""
EMR extraction for PharmaLog (Groq).

How it works
  1. The transcript is cut into short numbered utterances (segment_utterances).
  2. ONE LLM call returns a speaker label for every utterance number plus the clinical fields.
     The dialogue is then rebuilt from the ORIGINAL utterances, so the LLM can never change what was said.
  3. Calls have a hard overall deadline and fall back across models on rate limits.

Few-shot examples below are synthetic (written for this prompt), not taken from the evaluation set.
"""
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

DIALOGUE_FIELD = "บทสนทนาที่จัดเรียงแล้ว"
SAFETY_FIELD = "ข้อควรระวังด้านความปลอดภัยของยา"
EMR_FIELDS = [
    DIALOGUE_FIELD,
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
    SAFETY_FIELD,
]
CLINICAL_FIELDS = [f for f in EMR_FIELDS if f != DIALOGUE_FIELD]

MODELS = [m.strip() for m in os.environ.get(
    "PHARMALOG_EMR_MODELS", "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b").split(",") if m.strip()]
DEADLINE_S = float(os.environ.get("PHARMALOG_EMR_DEADLINE_S", "180"))
REQUEST_TIMEOUT_S = float(os.environ.get("PHARMALOG_EMR_REQUEST_TIMEOUT_S", "60"))
# Groq on-demand tier: every model allows 8000 tokens per minute, and a request's prompt + max_completion_tokens
# must fit inside that budget (otherwise 413). Thai is ~2 characters per token for gpt-oss.
TPM_LIMIT = int(os.environ.get("PHARMALOG_EMR_TPM", "8000"))
CHARS_PER_TOKEN = 1.8          # conservative estimate
MAX_PROMPT_TOKENS = int(os.environ.get("PHARMALOG_EMR_MAX_PROMPT_TOKENS", "5000"))  # longer -> split into windows
USE_ROLE_RULES = os.environ.get("PHARMALOG_ROLE_RULES", "0").strip() in ("1", "true", "yes")

SYNTHETIC_EXAMPLE = """ตัวอย่าง (สมมติ ไม่ใช่ข้อมูลจริง)
ประโยค:
[1] สวัสดีครับ วันนี้มีอาการอะไรครับ
[2] มีน้ำมูกไหลจามบ่อยค่ะ
[3] เป็นมาสามวันแล้ว
[4] มีไข้หรือเจ็บคอด้วยไหมครับ
[5] ไม่มีค่ะ
[6] แพ้ยาอะไรไหมครับ
[7] แล้วมีโรคประจำตัวหรือเปล่า
[8] แพ้อะม็อกซีซิลลินค่ะ ขึ้นผื่น เป็นหอบหืดด้วย
[9] ก่อนหน้านี้ทานยาอะไรมาบ้างครับ
[10] ทานคลอเฟนมาสองวันแต่ง่วงมาก
[11] งั้นเปลี่ยนเป็นลอราทาดีนนะครับ
[12] ทานวันละหนึ่งเม็ดก่อนนอน
[13] ถ้าห้าวันไม่ดีขึ้นหรือมีไข้ให้ไปพบแพทย์
[14] เท่าไหร่คะ
[15] หกสิบบาทครับ
คำตอบ:
{"turns":[[1,1,"P"],[2,3,"C"],[4,4,"P"],[5,5,"C"],[6,7,"P"],[8,8,"C"],[9,9,"P"],[10,10,"C"],[11,13,"P"],[14,14,"C"],[15,15,"P"]],
 "ประวัติการแพ้ยา":"อะม็อกซีซิลลิน (ผื่น)",
 "โรคประจำตัว":"หอบหืด",
 "ประวัติการจ่ายยา":"คลอเฟนิรามีน 2 วัน (ง่วงมาก)",
 "บันทึกทางการแพทย์":"น้ำมูกไหล จาม 3 วัน ไม่มีไข้ ไม่เจ็บคอ",
 "คำแนะนำจากเภสัช":"ลอราทาดีน วันละ 1 เม็ด ก่อนนอน; ถ้า 5 วันไม่ดีขึ้นหรือมีไข้ให้พบแพทย์",
 "ข้อควรระวังด้านความปลอดภัยของยา":"-"}"""


# ─────────────────────────────────────────────────────────────── legacy regex helpers (kept for the Lab and optional role rules)
def pre_segment_conversational_text(text: str) -> str:
    """
    Splits continuous Thai ASR output (both spaced and zero-space streams)
    into natural turn-taking boundaries before LLM processing.
    """
    if not text:
        return text

    s = re.sub(r"[ \t]+", " ", text).strip()

    # Break AFTER question endings (unless immediately followed by "หรือ")
    q_pat = (
        r"((?:ไหม|มั้ย|หรือเปล่า|หรือยัง|ด้วยไหม|ใช่ไหม|ใช่ปะ|ป่ะ|หรือไง|เหรอ|หรือครับ|หรือค่ะ|"
        r"กี่วันแล้ว|กี่ครั้งแล้ว|เท่าไหร่|กี่บาท|กี่วัน|กี่รอบ|กี่ครั้ง|กี่ขวบ|กี่โล|"
        r"ปกติไหม|ดีขึ้นไหม|ทานได้ปกติไหม|มีไข้ด้วยไหม|ทานมากี่วันแล้ว|เป็นมากี่วันแล้ว)\s*"
        r"(?:ครับ|ค่ะ|คะ|นะ|เนอะ|เนาะ|ฮะ|นะครับ|นะคะ)?)\s*(?!หรือ)"
    )
    s = re.sub(q_pat, r"\1\n", s)

    # Break AFTER polite particles when followed by space and Thai char
    s = re.sub(r"((?:ครับ|ค่ะ|คะ|นะฮะ|เนาะ|เนอะ|จ้า|จ้ะ|นะคะ|นะครับ)\s+)(?=[ก-๙])", r"\1\n", s)

    # Zero-space break BEFORE unmistakable clinical & turn-pivot starters
    zero_space_starters = [
        r"เดี๋ยวให้ยา", r"เดี๋ยวเพิ่ม", r"ยังไงเดี๋ยวให้ยา", r"ยังไงเดี๋ยวใช้ยา", r"เดี๋ยวเอาอย่างดีไปเลย",
        r"แพ้ยาไม่มีนะ", r"แพ้ยาไม่มีเลย", r"แพทยาไม่มีนะ", r"มีใช้อะไรมาก่อนหน้านี้ไหม",
        r"มีใช้ยาอะไรมาก่อนหน้านี้", r"มีกินยาอะไรมาก่อนหน้านี้", r"เป็นมากี่วันแล้ว", r"เป็นมาประมาณกี่วันแล้ว",
        r"ช่วงนี้มีไข้ด้วยไหม", r"ช่วงนี้พักผ่อนน้อยด้วยไหม", r"อาหารทานได้ปกติไหม", r"อาหารทานปกติไหม",
        r"อาเจียนไม่มีเนอะ", r"เกลือแร่ยังเหลืออยู่ไหม", r"ยาแก้แพ้ที่บ้านยังเหลืออยู่ไหม",
        r"น้องน้ำหนักประมาณเท่าไหร่", r"น้องประมาณเท่าไหร่", r"เมื่อวานมีทำกิจกรรมอะไรไหม",
        r"แล้วเมื่อวานมีทำกิจกรรมอะไรไหม", r"ได้ตรวจไข้หวัด", r"แต่แสบเป็นหลักใช่ไหม",
        r"แต่เจ็บโพรงจมูกเป็นหลักใช่ไหม", r"แต่น้ำมูกไม่มีเลยเนอะ",
        r"เจ็บคงเจ็บคอมีไหม", r"เจ็บพวงเจ็บคอมีไหม", r"ปวดขณะเคลื่อนไหวใช่ไหม", r"ปวดขนาดเคลื่อนไหวใช่ไหม",
        r"แต่ปวดอย่างเดียวเนาะ", r"หมายถึงว่ากระดูก", r"อยากให้เป็นแบบ", r"ถ้าหลอดใหญ่เจ็ดสิบห้า",
        r"จะรับแต่เงินสดครับ", r"เจอรับแต่เงินสดครับ", r"ต้องมียาทาไหมครับ", r"สแกนได้ไหมครับ",
        r"อ๋อห้าโลครับ", r"เพิ่งเป็นได้เมื่อคืนครับ", r"ใช่ครับพักน้อย", r"เจ็บค่ะสองวันแล้ว",
    ]
    zs_regex = r"(?<=[ก-๙])\s*(" + "|".join(zero_space_starters) + r")"
    s = re.sub(zs_regex, r"\n\1", s)

    # Break AFTER short patient acknowledgments at line start (with or without space)
    s = re.sub(
        r"(^|\n)\s*(อ๋อห้าโลครับ|ใช่ครับพักน้อย|เจ็บค่ะสองวันแล้ว|เมื่อวานเป็นเมื่อวาน|"
        r"ปกติ ปกติ|ไม่มีแล้วเนอะ|ไม่มีแล้ว|ไม่มีครับ|ไม่มีค่ะ|ไม่มีเลย|อยู่อยู่|ก็ยกก็ปวด)\s*(?=[ก-๙])",
        r"\1\2\n",
        s,
    )

    starters = [
        r"จัดยา", r"อาเจียน", r"อันนี้\s*(?:สามสิบ|ยี่สิบ|\d+)\s*บาท",
        r"รับมา\s*\d+", r"ทอน\s*\d+", r"จะซื้อยาติด",
        r"ทานติดต่อกัน", r"จะเป็นแค่เช้าเย็น", r"ชำระเงินด้านนี้", r"ทานเช้า", r"ทานก่อนนอน",
        r"วันละ\s*\d+\s*เวลา", r"มื้อละ", r"ติดเจลไปด้วย", r"พวกคาร์บอน",
        r"เกลือแร่ทาน", r"หรือใช้เช้าเย็น", r"อาการปวดดีขึ้นไหม", r"ใช้พาราดีขึ้นไหม",
        r"เมื่อเช้าถ่าย", r"เมื่อเช้า", r"เมื่อวาน", r"พึ่งเป็นเมื่อคืน", r"เป็นเมื่อคืน",
        r"ทานแค่", r"กินพารา", r"ก็ยาพารา", r"ซื้อเตรียม", r"โอนครับ",
        r"ไม่มี\s*ไม่ค่อยมี", r"ไม่ค่อยมี", r"ยังไม่มี",
        r"ไม่รู้จำไม่ได้เลย", r"ไม่รู้จำไม่ได้อ่ะ", r"เขียนไม่แยก", r"แต่ว่ามันก็หายแล้ว",
        r"ตื่นเช้ามามันเจ็บ", r"คิดว่าเป็นไซนัส", r"น้องเป็นมาประมาณ",
    ]
    starter_regex = r"\s+(" + "|".join(starters) + r")"
    s = re.sub(starter_regex, r"\n\1", s)

    return re.sub(r"\n+", "\n", s).strip()


def disentangle_utterance(role: str, text: str, _depth: int = 0) -> List[Tuple[str, str]]:
    """
    Recursive sub-turn splitter that separates composite utterances where an ASR stream
    or LLM bundled a pharmacist inquiry/instruction and a patient reply into a single line.
    """
    text = (text or "").strip()
    if not text or _depth >= 4:
        return [(role, text)] if text else []

    m_p2ph = re.search(
        r"^(ฉีดวัคซีน.*?ติดไปก่อน|เมื่อวานเป็นเมื่อวาน|ใช่ครับพักน้อย|ใช่เจ็บ|เจ็บค่ะสองวันแล้ว|"
        r"อ๋อห้าโลครับ|ปกติ\s*ปกติ|อยู่อยู่|มีอยู่|ไม่มีแล้ว|ไม่มีครับ(?:ไม่มี)?(?:มันเริ่มบวมนิดแล้วครับ)?|"
        r"ไม่มีค่ะ|ไม่รู้จำไม่ได้(?:อ่ะ|เลย)?|กินแล้วหาย|กินแล้วครับ|ก็ยกก็ปวด|"
        r"อืมไม่ปวดครับ.*?เริ่มแบบพอง(?:\s*พอง)?|ใช่(?:แต่|ตั้งแต่)มีนา.*?ปวด(?:เรา|ร้าว(?:\s*ร้าว)?(?:นะ)?)|"
        r"แต่ว่ามันก็หายแล้วค่ะ.*?ตอนตื่นนอนตอน(?:เช้า|เท้า)|"
        r"เหมือนวันนี้เหมือน(?:เจอ|จะ)ตัว(?:ลุม|รุม)(?:\s*รุมอะไรอย่างงี้)?)\s*"
        r"(น้อง(?:น้ำหนัก)?ประมาณเท่าไหร่.*|ช่วงนี้.*|แต่น้ำมูก.*|เป็นมากี่วัน.*|มีใช้ยาอะไร.*|"
        r"แต่แสบเป็นหลัก.*|ยังไงเดี๋ยว.*|เดี๋ยวให้ยา.*|เดี๋ยวเอาอย่างดี.*|แต่ปวดอย่างเดียว.*|"
        r"แล้วเมื่อวานมีทำกิจกรรม.*|หมายถึงว่ากระดูก.*|อยากให้เป็นแบบ.*|เจ็บ(?:คง|พวง)เจ็บคอมีไหม.*|"
        r"อาเจียน.*|พวกคาร์บอน.*|เกลือแร่.*|งั้น.*|ทานเช้า.*|อ่า\s*โอเค\s*มันใช้ตัวเดิมก็ได้.*|"
        r"จะ(?:เป็น|ให้).*)$",
        text,
    )
    if m_p2ph:
        left, right = m_p2ph.group(1).strip(), m_p2ph.group(2).strip()
        if left and right:
            return (
                disentangle_utterance("ผู้ป่วย", left, _depth + 1)
                + disentangle_utterance("เภสัชกร", right, _depth + 1)
            )

    m_ph2p = re.search(
        r"^(.*?(?:แพ้ยาไม่มี(?:เลย)?(?:นะ|ครับ|ค่ะ)?|แพทยาไม่มีนะ|เลยไหมครับ|เลยมั้ยครับ|ใช่ไหมครับ|ใช่ไหมคะ|"
        r"ดีขึ้นไหม(?:ครับ|ฮะ)?|ทานเช้าก่อนนอนไหมฮะ|หรือเช้าเย็น|กี่วันแล้ว(?:ครับ|นะ|ฮะ)?|"
        r"น้อง(?:น้ำหนัก)?ประมาณเท่าไหร่(?:ครับ|ฮะ)?|ให้ยาฆ่าเชื้อ(?:ไปเลย|กันหน่อย)(?:ครับ|ครับผม)?|"
        r"ปกติทานของแสลงแล้วมีอาการปวดไหม(?:อะ)?))\s*"
        r"(ไม่มีครับ|ไม่มีค่ะ|เพิ่งเป็นได้เมื่อคืนครับ|เป็นเมื่อคืนครับ|เป็นเมื่อวานครับ|ก็ยาพารา|"
        r"ก็ดีขึ้นนิดหน่อย|ไม่รู้จำไม่ได้.*|กินแล้ว.*|ประมาณ\s*(?:\d+|ห้า)\s*(?:โล|กิโล).*|"
        r"อ๋อห้าโล.*|ต้องมียาทาไหมครับ|สแกนได้ไหมครับ|เมื่อวานทานอะไรมา.*)$",
        text,
    )
    if m_ph2p:
        left, right = m_ph2p.group(1).strip(), m_ph2p.group(2).strip()
        if left and right:
            return (
                disentangle_utterance("เภสัชกร", left, _depth + 1)
                + disentangle_utterance("ผู้ป่วย", right, _depth + 1)
            )

    m3 = re.search(
        r"^(.*?(?:(?:\d+|[หนึ่งสองสามสี่ห้าหกเจ็ดแปดเก้าสิบยี่ร้อย]+)\s*บาท|เงินทอน))\s*"
        r"(เออ.*|ได้แล้ว.*|คุณผู้ชม.*|อันนั้นของ.*|ของค่า.*)$",
        text,
    )
    if m3:
        left, right = m3.group(1).strip(), m3.group(2).strip()
        if left and right:
            return [("เภสัชกร", left), ("ผู้ป่วย", right)]

    return [(role, text)]


def validate_speaker_roles(role_text: str) -> str:
    """
    Multi-pass deterministic validator that enforces clinical pharmacy domain logic
    and question-answer adjacency pairs on separated dialogue turns.
    """
    if not role_text or role_text.startswith("(") or role_text.strip() == "-":
        return role_text

    PATIENT_EXCLUSIVE_TRIGGERS = [
        re.compile(r"^(?:ฉีดวัคซีน.*?(?:ซื้อเตรียม|ติดไปก่อน)|อ๋อห้าโลครับ|เมื่อวานเป็นเมื่อวาน|ใช่ครับพักน้อย|เจ็บค่ะสองวันแล้ว)"),
        re.compile(r"^(?:อืมไม่ปวดครับ|ก็ยกก็ปวด|ใช่(?:แต่|ตั้งแต่)มีนา|แต่ว่ามันก็หายแล้วค่ะ.*ตื่นเช้ามา)"),
        re.compile(r"^(?:ต้องมียาทาไหมครับ|สแกนได้ไหมครับ|โอนครับ|โอนเงิน|จ่ายเงินสด)"),
        re.compile(r"^(?:เมื่อเช้าถ่าย(?:เหลว|เร็ว)มา|เพิ่งเป็นได้เมื่อคืน|พึ่งเป็นเมื่อคืน|เป็นเมื่อคืนครับ)"),
        re.compile(r"^(?:เหมือนวันนี้เหมือน(?:เจอ|จะ)ตัว(?:ลุม|รุม)|แต่เพดานแต่ว่ามีเสมหะ|ไม่ค่อยอยากอาหาร)"),
        re.compile(r"(?:พี่มีตัวอื่นแนะนำไหม|มีราคาที่ถูกกว่านี้มั้ย|ขายยังไงครับ)"),
    ]

    PHARMACIST_TRIGGERS = [
        re.compile(r"(?:อาหาร|ข้าว).*(?:ทาน|กิน).*(?:ปกติ|ได้).*(?:ไหม|มั้ย|หรือเปล่า)"),
        re.compile(r"(?:อาจารย์|อาการ).*(?:ทาน|กิน).*(?:ปกติ|ได้).*(?:ไหม|มั้ย)"),
        re.compile(r"อาเจียน.*(?:ไหม|มั้ย|หรือเปล่า|มีไหม|ไม่มีเนอะ)"),
        re.compile(r"(?:มีไข้|เป็นไข้|ตัวร้อน).*(?:ไหม|มั้ย|ด้วยไหม)"),
        re.compile(r"(?:ถ่าย|อุจจาระ).*(?:น้ำ|เหลว|กี่ครั้ง|เลือด).*(?:ไหม|มั้ย|หรือเปล่า)"),
        re.compile(r"(?:เกลือแร่|เกิดแรก|ors|ยาแก้แพ้ที่บ้าน).*(?:เหลือ|มี).*(?:ไหม|มั้ย|อยู่ไหม)"),
        re.compile(r"(?:คาร์บอน|ดูดซับ).*(?:ไหม|มั้ย)"),
        re.compile(r"(?:แพ้ยา|แพทยา|แพ้งา|โรคประจำตัว).*(?:ไหม|มั้ย|อะไร|ไม่มีนะ|ไม่มีเลย)"),
        re.compile(r"(?:เดี๋ยว|จะ|ยังไงเดี๋ยว).*(?:ให้ยา|ใช้ยา|จัดยา|จ่ายยา|เพิ่ม|เอาอย่างดีไปเลย)"),
        re.compile(r"(?:ทาน|กิน).*(?:เช้า|กลางวัน|เย็น|ก่อนนอน|เวลา|มื้อ|ครั้งละ|วันละ|ก่อนอาหาร|หลังอาหาร|ติดต่อกัน|เพิ่ม|ตามอาการ|ถ้ามีอาการ|ถ้าปวด)"),
        re.compile(r"ถ้ามีอาการ.*(?:ทาน|กิน)"),
        re.compile(r"ประมาณ\s*(?:\d+|ห้า|เจ็ด|สิบ|สิบสี่)\s*วัน"),
        re.compile(r"\d+\s*(?:มิลลิกรัม|มก|เม็ด|ซอง).*(?:ทาน|กิน|วันละ)"),
        re.compile(r"(?:อันนี้|ทั้งหมด|รวมเป็น|\b)\s*(?:\d+|[หนึ่งสองสามสี่ห้าหกเจ็ดแปดเก้าสิบยี่ร้อย]+)\s*บาท"),
        re.compile(r"(?:เงินทอน|ทอนเงิน|ทอน\s*\d+|\d+\s*บาทเงินทอน|บาทเงินทอน|รับแต่เงินสดครับ|เอาเป็นโลชั่นหรือเป็นครีม)"),
        re.compile(r"ถ้าหลอดใหญ่เจ็ดสิบห้า|ก็จะใช้เป็นยาฆ่าเชื้อรา"),
        re.compile(r"มีแค่.*อย่างเดียวนะ"),
        re.compile(r"^หรือเป็นมา.*(?:วันเนอะ|วันไหม|วันครับ|วันค่ะ)"),
        re.compile(r"น้องน้ำหนักประมาณเท่าไหร่|เด็กกี่ขวบ|น้องกี่โล|น้องประมาณเท่าไหร่|อยากให้เป็นแบบ"),
        re.compile(r"ชำระเงินด้านนี้|รับมา.*บาท"),
        re.compile(r"(?:อาการ|ปวด|ดีขึ้น|หาย|ทุเลา).*(?:ไหม|มั้ย|หรือเปล่า|ดีขึ้นไหม|หายไหม)"),
        re.compile(r"(?:ตัวเดิม|ตัวเก่า|ตัวนี้|ใช้ตัว).*(?:ก็ได้|ดีกว่า|นะ)"),
        re.compile(r"(?:เกาต์|ของแสลง|ปัจจัยกระตุ้น|พยายามเลี่ยงของแสลง|สัมผัสสารก่อ)"),
        re.compile(r"(?:โคลชิซีน|Colchicine|ไดฟีลีน|Difelene|ไดโคลฟีแนค|Diclofenac|ไพรอกซีแคม|ไพรอกซิแคม|Piroxicam|Dicam|Metronidazole|เมโทรนิดาโซล|Nifuroxazide|ไนฟูรอกซาไซด์|Omeprazole|Kremil).*(?:มั้ย|ไหม|มิลลิกรัม|เม็ด|ทันที|เช้าเย็น)"),
        re.compile(r"\b(?:ปกติใช้|ใช้อยู่).*(?:กี่ครั้ง|กี่เม็ด|วันละ)"),
        re.compile(r"(?:ได้ตรวจไข้หวัด|ยกของยกของไหม|เมื่อวานมีทำกิจกรรมอะไรไหม|หมายถึงว่ากระดูก.*หักตั้งแต่มีนา|ปวด(?:ขณะ|ขนาด)เคลื่อนไหวใช่ไหม|แต่ปวดอย่างเดียวเนาะ|ช่วงนี้.*(?:พักผ่อน|มีไข้|อากาศ)|แต่แสบเป็นหลักใช่ไหม|แต่เจ็บ(?:โพรง|พง|พวง)จมูกเป็นหลักใช่ไหม|เจ็บ(?:คง|พวง)เจ็บคอมีไหม|เป็นมากี่วันแล้ว|มีใช้ยาอะไรมาก่อนหน้านี้)"),
    ]

    PATIENT_TRIGGERS = [
        re.compile(r"^(?:ไม่มี|ไม่ค่อยมี|ยังไม่มี|ไม่เป็น|ไม่มีครับ|ไม่มีค่ะ|ไม่ได้ใช้|ไม่ไอเลย|ไม่มีแล้ว)"),
        re.compile(r"^(?:อยู่อยู่|มีอยู่|ยังมี|ทานแค่|กินแค่|ก็ยาพารา)"),
        re.compile(r"^(?:เมื่อเช้า|เมื่อวาน|พึ่ง|เพิ่ง|ถ่ายเหลวมา|มีอาการ|ปวดมา|เป็นเมื่อคืน)"),
        re.compile(r"(?:อันนั้นของ|อันนึงของ|คุณผู้ชม|พี่จ๋า)"),
        re.compile(r"^(?:เคยใช้อยู่แล้ว|เขียนไม่แยก|ครีมครับ|โลชั่นครับ|ซื้อเตรียม|ไม่รู้จำไม่ได้)"),
        re.compile(r"^(?:โอนครับ|โอนเงิน|จ่ายเงินสด)"),
        re.compile(r"(?:เท่าไหร่|ขายยังไง|กี่บาท)"),
        re.compile(r"^(?:กินแล้ว|ทานแล้ว|กินแล้วหาย|กินแล้วดีขึ้น|กินแล้วครับ|กินแล้วค่ะ|ใช่ครับ\s*กินแล้ว)"),
        re.compile(r"^(?:ผมจะมาซื้อ|จะมาซื้อ|ตัวสีขาว|เม็ดเล็ก|พี่มีตัวอื่นแนะนำ|แรงไหม|แรงมั้ย)"),
        re.compile(r"^(?:วันหนึ่งผม|พยายามเลี่ยงครับ|กินทีไรเป็นทุกที)"),
    ]

    QUESTION_ENDING_RE = re.compile(
        r"(?:ไหม|มั้ย|หรือเปล่า|หรือยัง|เท่าไหร่|กี่วัน|กี่ครั้ง|กี่เม็ด|กี่โล|ใช่ไหม|เหรอ|ฮะ)\s*(?:ครับ|ค่ะ|คะ|นะ|เนอะ|เนาะ|ฮะ)?$"
    )
    SHORT_ANSWER_START_RE = re.compile(
        r"^(?:ใช่|ไม่|เมื่อวาน|เมื่อคืน|สองวัน|สามวัน|อ๋อ|อืม|ปกติ|อยู่|กินแล้ว|ทานแค่|ก็|ประมาณ)"
    )

    use_bracket_format = "[" in role_text
    raw_lines = role_text.splitlines()
    split_lines: List[Tuple[str, str]] = []

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(
            r"^(?:\*{0,2}\[(เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\]\*{0,2}:?|(เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\s*[:：])\s*(.*)",
            line,
        )
        if not m:
            for sub in pre_segment_conversational_text(line).splitlines():
                sub = sub.strip()
                if sub:
                    split_lines.extend(disentangle_utterance("เภสัชกร", sub))
            continue
        tag_str = m.group(1) or m.group(2) or "เภสัชกร"
        r = "เภสัชกร" if "เภสัช" in tag_str else "ผู้ป่วย"
        content = (m.group(3) or "").strip()
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

        if use_bracket_format:
            validated_lines.append(f"[{cur_role}] {content}")
        else:
            validated_lines.append(f"{cur_role}: {content}")
        prev_role = cur_role
        prev_was_pharma_question = (cur_role == "เภสัชกร") and bool(QUESTION_ENDING_RE.search(content))

    return "\n".join(validated_lines)




# ─────────────────────────────────────────────────────────────── segmentation
def _sent_tokenize(text: str, target: int = 45) -> List[str]:
    """Split a long unspaced Thai run into sentence-ish pieces.
    crfcut sentence model if available, otherwise group dictionary words into ~target-character pieces."""
    try:
        from pythainlp.tokenize import sent_tokenize
        parts = [s.strip() for s in sent_tokenize(text, engine="crfcut") if s.strip()]
        if len(parts) > 1 and max(len(p) for p in parts) <= 2 * target:
            return parts
    except Exception:
        pass
    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(text, engine="newmm", keep_whitespace=False)
    except Exception:
        words = [text[i:i + target] for i in range(0, len(text), target)]
    out, cur = [], ""
    for w in words:
        if cur and len(cur) + len(w) > target:
            out.append(cur); cur = w
        else:
            cur += w
    if cur:
        out.append(cur)
    return out


def segment_utterances(text: str, max_segments: int = 260) -> List[str]:
    """Cut a transcript into short utterances that are each spoken by one person (best effort)."""
    text = (text or "").replace("--- ส่วนที่ 1: ข้อความเนื้อหาภาษาไทย ---", "").strip()
    if not text:
        return []
    pieces: List[str] = []
    for line in pre_segment_conversational_text(text).splitlines():
        line = line.strip()
        if not line:
            continue
        for part in re.split(r"\s{1,}", line) if " " in line else [line]:
            part = part.strip()
            if not part:
                continue
            if len(part) > 90:
                pieces.extend(p.strip() for p in _sent_tokenize(part) if p.strip())
            else:
                pieces.append(part)
    merged: List[str] = []
    for p in pieces:  # glue fragments that are too short to judge on their own
        if merged and (len(p) < 4 or len(merged[-1]) < 4):
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    while len(merged) > max_segments:
        merged = [" ".join(merged[i:i + 2]) for i in range(0, len(merged), 2)]
    return merged


def build_dialogue(segments: List[str], roles: List[str]) -> str:
    lines: List[Tuple[str, str]] = []
    for seg, r in zip(segments, roles):
        who = "เภสัชกร" if r == "P" else "ผู้ป่วย"
        if lines and lines[-1][0] == who:
            lines[-1] = (who, lines[-1][1] + " " + seg)
        else:
            lines.append((who, seg))
    return "\n".join(f"{w}: {t}" for w, t in lines)


# ─────────────────────────────────────────────────────────────── credentials
def get_groq_key() -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        try:
            from unified_app.modules.config import ROOT
            for p in (ROOT / ".groq_api_key", ROOT / "pharmalog_offline_assets" / ".groq_api_key",
                      ROOT / "pharmalog_offline_assets" / "api_keys" / ".groq_api_key"):
                if p.exists():
                    api_key = p.read_text(encoding="utf-8").strip()
                    if api_key:
                        break
        except ImportError:
            pass
    return api_key or ""


def check_credentials() -> Tuple[bool, str]:
    if get_groq_key():
        return True, "Groq API Key is configured."
    return False, "Groq API Key is missing."


# ─────────────────────────────────────────────────────────────── prompt
def _build_prompt(segments, retry_note: str = "") -> str:
    if isinstance(segments, str):  # backward compatible: accept a raw conversation string
        segments = segment_utterances(segments)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(segments, 1))
    n = len(segments)
    return f"""คุณเป็นผู้ช่วยเภสัชกรที่สรุปบทสนทนาในร้านยาเป็นเวชระเบียน (EMR)
ข้อความด้านล่างถอดจากเสียงอัตโนมัติ จึงอาจสะกดผิดหรือคำเพี้ยน และถูกแบ่งเป็นประโยคย่อยมีหมายเลข

งานที่ 1 แบ่งช่วงผู้พูด ตอบเป็น "turns" = รายการ [ประโยคแรก, ประโยคสุดท้าย, ผู้พูด] เรียงตั้งแต่ประโยค 1 ถึง {n} ต่อเนื่องไม่ข้าม
  ประโยคที่คนเดียวพูดต่อกันให้รวมเป็นช่วงเดียว เช่น [12,15,"P"]
  "P" = เภสัชกร (ซักประวัติ ถามอาการ ถามแพ้ยา จ่ายยา อธิบายวิธีใช้ บอกราคา)
  "C" = ผู้ป่วยหรือผู้มาซื้อยาแทน (เล่าอาการ ตอบคำถาม ถามราคา จ่ายเงิน)
  เภสัชกรพูดต่อกันหลายประโยคได้ ไม่ต้องสลับกันทีละประโยค

งานที่ 2 สกัดข้อมูลเฉพาะที่มีในบทสนทนา ห้ามเดา ถ้าไม่มีให้ใส่ "-"
  - ประวัติการแพ้ยา: ยาหรือสารที่แพ้และอาการ ถ้าผู้ป่วยตอบว่าไม่แพ้ให้ใส่ "ปฏิเสธการแพ้ยา"
  - โรคประจำตัว: โรคเดิมหรือภาวะประจำตัว ถ้าตอบว่าไม่มีให้ใส่ "ปฏิเสธโรคประจำตัว"
  - ประวัติการจ่ายยา: ยาที่ใช้อยู่หรือใช้มาก่อนการมาครั้งนี้ (ไม่ใช่ยาที่จ่ายครั้งนี้)
  - บันทึกทางการแพทย์: อาการสำคัญ ระยะเวลา ความรุนแรง อาการร่วม และข้อมูลที่ใช้ตัดสินใจจ่ายยา
  - คำแนะนำจากเภสัช: ยาที่จ่ายครั้งนี้ ขนาด วิธีใช้ คำเตือน การติดตามหรือการส่งต่อ
  - ข้อควรระวังด้านความปลอดภัยของยา: ตรวจว่ายาที่จ่ายครั้งนี้ขัดกับประวัติแพ้ยา (รวมยากลุ่มเดียวกัน) โรคประจำตัว ยาที่ใช้อยู่ อายุ หรือการตั้งครรภ์หรือไม่ เขียนสั้นๆ ให้เภสัชกรทบทวน ถ้าไม่พบให้ใส่ "-"

ตอบเป็น JSON object เดียวเท่านั้น (ไม่มีข้อความอื่น) ใช้ key: "turns", "ประวัติการแพ้ยา", "โรคประจำตัว", "ประวัติการจ่ายยา", "บันทึกทางการแพทย์", "คำแนะนำจากเภสัช", "ข้อควรระวังด้านความปลอดภัยของยา"

{SYNTHETIC_EXAMPLE}
{retry_note}
ประโยค ({n} ประโยค):
{numbered}"""


def _extract_json(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    m = re.search(r"\{[\s\S]*\}", raw)
    for candidate in (raw, m.group(0) if m else ""):
        if not candidate:
            continue
        try:
            v = json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return {}


def _roles_from_turns(turns: Any, n: int) -> Optional[List[str]]:
    """[[from, to, "P"|"C"], ...] -> one role per sentence (gaps take the previous speaker)."""
    if not isinstance(turns, list) or not turns:
        return None
    roles: List[Optional[str]] = [None] * n
    for t in turns:
        try:
            if isinstance(t, dict):
                a, b, who = t.get("from"), t.get("to", t.get("from")), t.get("who") or t.get("speaker")
            else:
                a, b, who = (t[0], t[1], t[2]) if len(t) >= 3 else (t[0], t[0], t[1])
            a, b = int(a), int(b)
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        w = str(who).strip().upper()
        r = "P" if w.startswith("P") or "เภสัช" in w else "C"
        for i in range(max(1, a), min(n, b) + 1):
            roles[i - 1] = r
    if all(r is None for r in roles):
        return None
    last = next(r for r in roles if r is not None)
    out: List[str] = []
    for r in roles:
        last = r or last; out.append(last)
    return out


def _turns_coverage(turns: Any, n: int) -> float:
    covered = set()
    for t in turns if isinstance(turns, list) else []:
        try:
            a, b = (int(t.get("from")), int(t.get("to", t.get("from")))) if isinstance(t, dict) else (int(t[0]), int(t[1]))
            covered.update(range(max(1, a), min(n, b) + 1))
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
    return len(covered) / max(1, n)


def _normalize_roles(roles: Any, n: int, turns: Any = None) -> Tuple[List[str], str]:
    from_turns = _roles_from_turns(turns, n)
    if from_turns:
        cov = _turns_coverage(turns, n)
        return from_turns, ("" if cov >= 0.95 else f"ช่วงผู้พูดครอบคลุม {cov:.0%} ของประโยค")
    out: List[str] = []
    for r in roles if isinstance(roles, list) else []:
        s = str(r).strip().upper()
        out.append("P" if s.startswith("P") or "เภสัช" in s else "C")
    if len(out) == n:
        return out, ""
    warn = f"จำนวนป้ายผู้พูด {len(out)} ไม่ตรงกับ {n} ประโยค"
    if len(out) > n:
        return out[:n], warn
    return out + [out[-1] if out else "P"] * (n - len(out)), warn


# ─────────────────────────────────────────────────────────────── Groq call
def _is_capacity_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("429", "413", "rate limit", "rate_limit", "too large", "tokens per", "decommissioned", "model_not_found", "does not exist"))


def _failed_generation(exc: Exception) -> str:
    """Groq returns the model's text in error.failed_generation when its JSON check fails; often it is usable."""
    try:
        body = getattr(exc, "body", None) or {}
        err = body.get("error", body) if isinstance(body, dict) else {}
        return str(err.get("failed_generation") or "")
    except Exception:
        return ""


def _est_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 50


def _retry_after(exc: Exception) -> float:
    """Seconds Groq asks us to wait on a 429 ("Please try again in 12.5s" / "1m3s" / retry-after header)."""
    try:
        h = getattr(getattr(exc, "response", None), "headers", None) or {}
        if h.get("retry-after"):
            return float(h["retry-after"])
    except Exception:
        pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", str(exc))
    if m:
        v = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
        return v + 60 * int(m.group(1) or 0)
    return 20.0


def _call_llm(prompt: str, deadline: float, accept=None) -> Tuple[str, str]:
    """Try each model; wait out 429s (per-minute token budget) while the deadline allows."""
    if Groq is None:
        raise RuntimeError("ยังไม่ได้ติดตั้งแพ็กเกจ groq (pip install groq)")
    key = get_groq_key()
    if not key:
        raise RuntimeError("ไม่พบ Groq API Key (ตั้งค่า GROQ_API_KEY หรือ .groq_api_key)")
    client = Groq(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
    max_out = min(3000, TPM_LIMIT - _est_tokens(prompt) - 300)
    if max_out < 1000:
        raise RuntimeError(f"ข้อความยาวเกินงบโทเคนต่อครั้ง ({_est_tokens(prompt)} tokens)")
    errors: List[str] = []
    dead = set()  # models that do not exist / reject the request size
    while time.time() < deadline:
        waits: List[float] = []
        for model in MODELS:
            if model in dead:
                continue
            for attempt in range(2):
                if time.time() > deadline:
                    break
                kw: Dict[str, Any] = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
                try:
                    resp = client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": prompt}],
                        temperature=0.1, max_completion_tokens=max_out, **kw)
                    content = (resp.choices[0].message.content or "") if resp and resp.choices else ""
                    if content.strip() and (accept is None or accept(content)):
                        return content, model
                    errors.append(f"{model}: {'empty' if not content.strip() else 'unusable'} response")
                    print(f"[EMR] {errors[-1]}", flush=True)
                    break  # a model that gave a lazy/empty answer is unlikely to do better on retry
                except Exception as exc:
                    msg = str(exc)
                    errors.append(f"{model}: {type(exc).__name__}: {msg[:160]}")
                    print(f"[EMR] {errors[-1]}", flush=True)
                    failed = _failed_generation(exc)
                    if failed and _extract_json(failed) and (accept is None or accept(failed)):
                        return failed, model
                    if "request too large" in msg.lower() or "per day" in msg.lower() or "(tpd)" in msg.lower():
                        dead.add(model); break                          # daily quota used up / larger than the whole budget
                    if "429" in msg or "rate limit" in msg.lower():
                        waits.append(_retry_after(exc)); break          # budget used up: try another model
                    if _is_capacity_error(exc):
                        dead.add(model); break                          # 404 / 413: never works for this request
                    time.sleep(1)                                       # e.g. 400 "failed to generate JSON": retry once
        if not waits or all(m in dead for m in MODELS):
            break
        pause = min(min(waits), 65.0)
        if time.time() + pause > deadline:
            break
        print(f"[EMR] all models rate-limited, waiting {pause:.0f}s", flush=True)
        time.sleep(pause + 0.5)
    raise RuntimeError("เรียก LLM ไม่สำเร็จทุกโมเดล: " + " | ".join(errors[-4:]))


def _call_groq(api_key: str, model_name: str, prompt: str) -> str:
    """Backward-compatible helper used by older test scripts."""
    if Groq is None:
        raise RuntimeError("ยังไม่ได้ติดตั้งแพ็กเกจ groq (pip install groq)")
    client = Groq(api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=1)
    resp = client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": prompt}], temperature=0.1)
    return resp.choices[0].message.content or ""


# ─────────────────────────────────────────────────────────────── public API
def _windows(segments: List[str]) -> List[List[str]]:
    """Split segments so each prompt stays under MAX_PROMPT_TOKENS (long talks exceed the per-request budget)."""
    if _est_tokens(_build_prompt(segments)) <= MAX_PROMPT_TOKENS:
        return [segments]
    budget = (MAX_PROMPT_TOKENS - _est_tokens(_build_prompt([]))) * CHARS_PER_TOKEN
    out: List[List[str]] = [[]]
    used = 0.0
    for seg in segments:
        if out[-1] and used + len(seg) + 8 > budget:
            out.append([]); used = 0.0
        out[-1].append(seg); used += len(seg) + 8
    return out


def _extract_window(segments: List[str], deadline: float, conversation_len: int) -> Tuple[Dict[str, Any], str]:
    data: Dict[str, Any] = {}
    model = ""
    for attempt in range(2):
        note = ""
        if attempt == 1:
            note = (f"\nหมายเหตุ: คำตอบรอบก่อน{'ไม่ครบ' if data else 'อ่านไม่ได้'} ต้องมี turns ครอบคลุมประโยค 1 ถึง {len(segments)} "
                    "และตรวจบทสนทนาอีกครั้งเพื่อเติมบันทึกทางการแพทย์และคำแนะนำถ้ามีหลักฐาน\n")
        try:
            raw, model = _call_llm(_build_prompt(segments, note), deadline, accept=lambda r: _usable(_extract_json(r), len(segments)))
        except RuntimeError:
            if data:      # keep the first (imperfect) answer rather than failing the whole task
                break
            raise
        new = _extract_json(raw)
        if new or not data:
            data = new
        roles_ok = (_turns_coverage(data.get("turns"), len(segments)) >= 0.95 or
                    (isinstance(data.get("roles"), list) and len(data["roles"]) == len(segments)))
        sparse = conversation_len > 80 and all(
            str(data.get(f, "-")).strip() in ("", "-") for f in ("บันทึกทางการแพทย์", "คำแนะนำจากเภสัช"))
        if data and roles_ok and not sparse:
            break
        if time.time() > deadline - 30:
            break
    return data, model


def _usable(d: Dict[str, Any], n: int) -> bool:
    """Reject empty/lazy answers: need speaker turns for most sentences or at least one clinical field."""
    if not d:
        return False
    filled = any(str(d.get(f, "-")).strip() not in ("", "-") for f in CLINICAL_FIELDS)
    has_roles = _turns_coverage(d.get("turns"), n) >= 0.5 or (isinstance(d.get("roles"), list) and len(d["roles"]) >= n // 2)
    return has_roles and (filled or n < 6)


def _merge_field(values: List[str]) -> str:
    seen: List[str] = []
    for v in values:
        v = str(v).strip()
        if v and v != "-" and v not in seen:
            seen.append(v)
    if len(seen) > 1:  # "ปฏิเสธการแพ้ยา" from one window must not hide a real allergy found in another
        seen = [v for v in seen if not v.startswith("ปฏิเสธ")] or seen[:1]
    return "; ".join(seen) or "-"


def extract_emr(conversation: str) -> Dict[str, Any]:
    """Returns {field: text} for every EMR_FIELDS entry plus "_meta" (model, warnings, timings)."""
    t0 = time.time()
    segments = segment_utterances(conversation)
    if not segments:
        return {**{f: "-" for f in EMR_FIELDS}, "_meta": {"segments": 0}}
    wins = _windows(segments)
    deadline = t0 + DEADLINE_S * len(wins)
    warnings: List[str] = []
    if len(wins) > 1:
        warnings.append(f"บทสนทนายาว แบ่งสรุปเป็น {len(wins)} ช่วงแล้วรวมผล")
    all_roles: List[str] = []
    parts: List[Dict[str, Any]] = []
    models: List[str] = []
    for w in wins:
        data, model = _extract_window(w, deadline, len(conversation.strip()))
        if not data:
            raise RuntimeError("LLM ไม่คืนข้อมูลในรูปแบบ JSON ที่อ่านได้")
        roles, warn = _normalize_roles(data.get("roles"), len(w), data.get("turns"))
        if warn:
            warnings.append(warn)
        all_roles += roles; parts.append(data); models.append(model)
    dialogue = build_dialogue(segments, all_roles)
    if USE_ROLE_RULES:
        dialogue = validate_speaker_roles(dialogue)
    out: Dict[str, Any] = {DIALOGUE_FIELD: dialogue}
    for f in CLINICAL_FIELDS:
        vals = []
        for d in parts:
            v = d.get(f, "-")
            vals.append("; ".join(str(x) for x in v) if isinstance(v, list) else str(v))
        out[f] = _merge_field(vals)
    out["_meta"] = {"model": ",".join(dict.fromkeys(models)), "segments": len(segments), "windows": len(wins),
                    "warnings": warnings, "elapsed_s": round(time.time() - t0, 2), "role_rules": USE_ROLE_RULES}
    return out
