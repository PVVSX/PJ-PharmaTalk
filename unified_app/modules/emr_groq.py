import json
import re
import os
import time
from typing import Any, List, Tuple, Optional
try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

# ── Constants ────────────────────────────────────────────────────
EMR_FIELDS = [
    "บทสนทนาที่จัดเรียงแล้ว",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]

# ── Dynamic Clinical Domain Exemplars ──
CLINICAL_EXEMPLARS = {
    "gi": """ตัวอย่างการแยกผู้พูด (กรณีท้องเสีย / ถ่ายเหลว / ทางเดินอาหาร):
[เภสัชกร] หรือเป็นมาสองวันเนอะ
[ผู้ป่วย] เมื่อเช้าถ่ายเหลวมาสองครั้งแล้วเนอะ
[เภสัชกร] ช่วงนี้มีไข้ด้วยไหม
[ผู้ป่วย] ไม่มี ไม่ค่อยมี
[เภสัชกร] ถ่ายเหลวเป็นน้ำ อาหารทานได้ปกติไหม
[ผู้ป่วย] ปกติ ปกติ
[เภสัชกร] อาเจียนไม่มีเนอะ เดี๋ยวให้ยาแก้ท้องเสีย จะเป็นไนฟูรอกซาไซด์ ทานเช้า กลางวัน เย็น ก่อนนอน 4 เวลานะ อันนี้สามสิบห้าบาทครับ""",

    "pain": """ตัวอย่างการแยกผู้พูด (กรณีปวดฟัน / แผล / ปวดเมื่อย / ฆ่าเชื้อ / เกาต์):
[เภสัชกร] เป็นยาแก้ปวดฟันนะ แพ้ยาไม่มีนะ
[ผู้ป่วย] ไม่มีครับ
[เภสัชกร] เป็นมากี่วันแล้วครับ
[ผู้ป่วย] เพิ่งเป็นได้เมื่อคืนครับ
[เภสัชกร] มีใช้อะไรมาก่อนหน้านี้ไหมครับ
[ผู้ป่วย] ก็ยาพารา
[เภสัชกร] เดี๋ยวจะเป็นฆ่าเชื้อนะครับ เพิ่ม Metronidazole ทานติดต่อกันจนหมดหน่อย เช้าเย็นนะครับ สามสิบบาทครับ
[ผู้ป่วย] โอนครับ""",

    "cold": """ตัวอย่างการแยกผู้พูด (กรณีไข้หวัด / ไอ / เสมหะ / ไซนัส / เจ็บคอ):
[เภสัชกร] เป็นไข้หวัดเนอะ
[ผู้ป่วย] เป็นไข้วันจันทร์ ได้พาราอย่างเดียว สองวันยังมีไข้อยู่
[เภสัชกร] ไปโรงพยาบาลได้สวอปอะไรให้ไหม
[ผู้ป่วย] อาการที่เหลือคือมีไข้แต่ไม่สูง แล้วก็ไอ คันคอ เจ็บคอ
[เภสัชกร] เดี๋ยวให้ยาแก้ไอขับเสมหะ ทานครั้งละ 1 เม็ด 3 เวลานะครับ""",

    "gerd": """ตัวอย่างการแยกผู้พูด (กรณีลดกรด / กระเพาะ / กรดไหลย้อน):
[เภสัชกร] ยาลดกรดทานปกติเช้าก่อนนอนไหมครับ หรือเช้าเย็น
[ผู้ป่วย] ไม่รู้จำไม่ได้เลย
[เภสัชกร] ทานเช้าก่อนนอนสองตัวนี้นะ เคมิลทานตามอาการ 1-2 เม็ด ให้เขียนแยกไปไหมฮะ
[ผู้ป่วย] เขียนไม่แยกค่ะ""",

    "pediatric": """ตัวอย่างการแยกผู้พูด (กรณีเด็ก / วัคซีน / จัดยาตามน้ำหนัก):
[ผู้ป่วย] ฉีดวัคซีนอนามัยก็เลยจะซื้อยาแก้ปวดติดไปก่อน
[เภสัชกร] น้องน้ำหนักประมาณเท่าไหร่ครับ
[ผู้ป่วย] อ๋อห้าโลครับ
[เภสัชกร] ห้าโล ทานครั้งละ 0.5 ซีซี ตามอาการทุก 4-6 ชั่วโมง ถ้าไข้ไม่มีก็หยุดใช้ได้ สี่สิบห้าบาทครับ""",
}


def pick_few_shot_exemplar(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"ถ่าย|ท้องเสีย|เหลว|เกลือแร่|คาร์บอน|ไนฟูรอก|อาเจียน", t):
        return CLINICAL_EXEMPLARS["gi"]
    elif re.search(r"ฟัน|ปวดฟัน|แผล|อักเสบ|ฆ่าเชื้อ|เมโทรนิดา|metronidazole|difelene|กล้ามเนื้อ|เกาต์|เก๊า|colchicine", t):
        return CLINICAL_EXEMPLARS["pain"]
    elif re.search(r"ลดกรด|หลั่งกรด|กรดไหลย้อน|กระเพาะ|เคมิล|โอเมพราโซล", t):
        return CLINICAL_EXEMPLARS["gerd"]
    elif re.search(r"เด็ก|น้อง|ขวบ|วัคซีน|กิโล|ห้าโล|ไซริ้ง|ติดเจล", t):
        return CLINICAL_EXEMPLARS["pediatric"]
    return CLINICAL_EXEMPLARS["cold"]


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
        re.compile(r"(?:โคลชิซีน|Colchicine|ไดฟีลีน|Difelene|ไดโคลฟีแนค|Diclofenac|ไพรอกซีแคม|Piroxicam|Metronidazole).*(?:มั้ย|ไหม|มิลลิกรัม|เม็ด|ทันที|เช้าเย็น)"),
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


def get_groq_key() -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        try:
            from unified_app.modules.config import ROOT
            candidates = [
                ROOT / ".groq_api_key",
                ROOT / "pharmalog_offline_assets" / ".groq_api_key",
                ROOT / "pharmalog_offline_assets" / "api_keys" / ".groq_api_key",
            ]
            for p in candidates:
                if p.exists():
                    api_key = p.read_text(encoding="utf-8").strip()
                    if api_key:
                        break
        except ImportError:
            pass
    return api_key or ""


def get_groq_client():
    if Groq is None:
        raise RuntimeError("ยังไม่ได้ติดตั้งแพ็กเกจ groq (pip install groq)")
    api_key = get_groq_key()
    if not api_key:
        raise RuntimeError("ไม่พบ Groq API Key (ตั้งค่า GROQ_API_KEY หรือ .groq_api_key)")
    return Groq(api_key=api_key)


def check_credentials() -> tuple[bool, str]:
    if get_groq_key():
        return True, "Groq API Key is configured."
    return False, "Groq API Key is missing."


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
    segmented_conv = pre_segment_conversational_text(conversation)
    few_shot = pick_few_shot_exemplar(segmented_conv)

    user_prompt = f"""{system}
คุณจะได้รับ "ข้อความเนื้อหาภาษาไทย" ที่ผ่านการตัดแบ่งประโยคเบื้องต้นแล้ว

หน้าที่ของคุณ:
1. จำแนกแต่ละประโยคว่าเป็นของ `เภสัชกร:` หรือ `ผู้ป่วย:` ตามบริบททางคลินิก (หากบรรทัดใดมีคำตอบของผู้ป่วยติดอยู่กับคำถามหรือคำแนะนำของเภสัชกร ให้ตัดแยกเป็นคนละบรรทัด):
   - **เภสัชกร**: ผู้ซักประวัติคัดกรอง ('เป็นมากี่วันแล้ว', 'มีไข้ด้วยไหม', 'แพ้ยาไม่มีนะ'), ผู้สั่งจ่ายยาและบอกวิธีทาน ('เดี๋ยวให้ยา...', 'ทานเช้าเย็น', 'ติดต่อกันจนหมด'), ผู้แจ้งราคาและเงินทอน ('สามสิบบาทครับ')
   - **ผู้ป่วย**: ผู้บอกอาการตนเอง ('เมื่อวาน', 'ปวดฟัน', 'ถ่ายเหลว'), ผู้ตอบรับ/ปฏิเสธ ('ไม่มีครับ', 'ปกติ', 'อ๋อห้าโลครับ'), ผู้ถามราคาหรือวิธีจ่ายเงิน ('เท่าไหร่ครับ', 'สแกนได้ไหมครับ', 'โอนครับ')
   - ห้ามสลับบทบาทแบบปิงปองอัตโนมัติ เภสัชกรสามารถซักถามหรืออธิบายติดต่อกันหลายประโยคได้

{few_shot}

2. สกัดข้อมูลและสรุปเป็น JSON ภาษาไทยตาม key ต่อไปนี้เท่านั้น:

{{
  "บทสนทนาที่จัดเรียงแล้ว": "เภสัชกร: ...\\nผู้ป่วย: ...\\nเภสัชกร: ...",
  "ประวัติการแพ้ยา": "...",
  "โรคประจำตัว": "...",
  "ประวัติการจ่ายยา": "...",
  "บันทึกทางการแพทย์": "...",
  "คำแนะนำจากเภสัช": "..."
}}

หลักการ:
- บทสนทนาที่จัดเรียงแล้ว: ต้องเป็นเนื้อหาจากข้อความที่ได้รับ ที่นำมาหั่นและใส่ "เภสัชกร:" / "ผู้ป่วย:" นำหน้าประโยคตามบริบท ห้ามเพิ่มหรือลดเนื้อหา
- ประวัติการแพ้ยา: ยาหรือสารที่ผู้ป่วยแพ้ พร้อมอาการแพ้ถ้ามี
- โรคประจำตัว: โรคเดิม/ภาวะประจำตัว/ยาที่สัมพันธ์กับโรคประจำตัว
- ประวัติการจ่ายยา: ยาที่เคยได้รับหรือกำลังใช้อยู่ก่อนการจ่ายครั้งนี้
- บันทึกทางการแพทย์: อาการสำคัญ ระยะเวลา ความรุนแรง ข้อมูลที่เกี่ยวกับการพิจารณาจ่ายยา
- คำแนะนำจากเภสัช: ยาที่แนะนำ วิธีใช้ คำเตือน การติดตามอาการ หรือการส่งต่อ
- ถ้าไม่มีข้อมูลในช่องใดให้ใส่ "-"
{retry_note}
บทสนทนา:
{segmented_conv}"""
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
    if Groq is None:
        raise RuntimeError("ยังไม่ได้ติดตั้งแพ็กเกจ groq (pip install groq)")
    client = Groq(api_key=api_key)
    models_to_try = [
        model_name,
        "llama-3.3-70b-versatile",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-20b",
    ]
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
                    break
                if attempt < _RETRY_COUNT - 1:
                    time.sleep(min(_RETRY_BASE_SEC * (2 ** attempt), 12.0))
                    continue

    raise RuntimeError(f"เรียก Groq API ไม่สำเร็จ: {last_exc}") from last_exc


# ── Public API ───────────────────────────────────────────────────
def extract_emr(conversation: str) -> dict[str, str]:
    """
    Main entry point: extract EMR fields from a conversation string using Groq,
    with pre-segmentation, dynamic clinical few-shot exemplars, and deterministic
    post-processing speaker role validation.
    """
    if not conversation or not conversation.strip():
        return {f: "-" for f in EMR_FIELDS}

    api_key = get_groq_key()
    model_name = "openai/gpt-oss-120b"  # Primary model on Groq with automatic fallback

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

    formatted = {f: str(data.get(f) or "-").strip() or "-" for f in EMR_FIELDS}
    conv_sorted = formatted.get("บทสนทนาที่จัดเรียงแล้ว", "-")
    if conv_sorted and conv_sorted != "-":
        formatted["บทสนทนาที่จัดเรียงแล้ว"] = validate_speaker_roles(conv_sorted)
    return formatted
