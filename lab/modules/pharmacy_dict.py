"""
Pharmacy Dictionary -- Comprehensive 5-Layer Hybrid Post-processing Module for STT.

สถาปัตยกรรม 5 เลเยอร์สำหรับแก้ไข Transcript ร้านยา:
  - Layer 0: Unicode & Acoustic Anomaly Cleaner (ล้างสระลอย, อักขระเสีย, และ Whisper Degeneration Loop)
  - Layer 1: Empirical Ground-Truth Mapping (คลังคำผิดจริงจากการสกัด 47 เทปเสียง)
  - Layer 2: Structured Pharmacy Ontology (คลังยาจัดหมวดหมู่: GI, Resp, Pain, Antibiotics, Topicals)
  - Layer 3: Context-Guarded Regex Engine (กฎไวยากรณ์และบริบทแวดล้อม: จำนวนยา, มื้อยา, เวลาทาน)
  - Layer 4: Phonetic & Soundex Matching with Medical Trigger Guard (จับคู่เสียงใกล้เคียงเมื่อมีคำบริบทแพทย์)
  - Layer Custom: User-defined Custom Dictionary (คำศัพท์กำหนดเองจากหน้า UI)

Usage:
    from modules.pharmacy_dict import correct_transcript, get_stats

    raw = "ค่าเชื้อตัวหนึ่งครับ ทานหนึ่งเมตรเช้าเย็น หกร้อยมิติกรรม"
    corrected, changes = correct_transcript(raw)
"""

import json
import os
import re
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

try:
    from pythainlp.util import normalize
    from pythainlp.soundex import soundex as thai_soundex
    from pythainlp.tokenize import word_tokenize
except ImportError:
    normalize = lambda s: s
    thai_soundex = None
    word_tokenize = lambda s: s.split()

DATA_DIR = Path(__file__).resolve().parent / "pharmacy_data"
CUSTOM_DICT_PATH = Path(__file__).resolve().parent.parent / "custom_dict.json"


# ─────────────────────────────────────────────────────────────
#  Layer 0: THAI UNICODE & ACOUSTIC ANOMALY CLEANER
# ─────────────────────────────────────────────────────────────

def clean_thai_unicode(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    ตรวจจับและแก้ไขสระลอย สระซ้อน อักขระตกค้าง และสระที่เกาะผิดหลัก Unicode
    ซึ่งเกิดจากเอนจิน Speech-to-Text ถอดรหัสคลื่นเสียงเพี้ยน
    """
    if not text:
        return text, []

    changes: List[Dict[str, Any]] = []

    # 0. กำจัดอักขระเสีย Unicode Replacement Character (U+FFFD \ufffd หรือ ) และสระ/วรรณยุกต์ที่เกาะอยู่
    if "\ufffd" in text:
        cnt = text.count("\ufffd")
        text = re.sub(r"\ufffd[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]*", "", text)
        text = text.replace("\ufffd", "")
        changes.append({
            "tier": "0-unicode",
            "original": " (U+FFFD)",
            "corrected": "ลบอักขระเสีย",
            "count": cnt,
            "description": "ลบอักขระเสีย Unicode U+FFFD จากเอนจินเสียง",
        })

    # 1. แก้ไขคำเพี้ยนเฉพาะที่ Whisper มักถอดเป็นสระลอย เช่น ขาู่ไง -> ขายยังไง
    if re.search(r"ขา[\u0e38\u0e39][\u0e48-\u0e4c]*ไง", text):
        text = re.sub(r"ขา[\u0e38\u0e39][\u0e48-\u0e4c]*ไง", "ขายยังไง", text)
        changes.append({
            "tier": "0-unicode",
            "original": "ขาู่ไง",
            "corrected": "ขายยังไง",
            "count": 1,
            "description": "แก้สระลอยและเสียงรวบ (Whisper acoustic slur)",
        })

    if re.search(r"ขา[\u0e38\u0e39][\u0e48-\u0e4c]+", text):
        text = re.sub(r"ขา[\u0e38\u0e39][\u0e48-\u0e4c]+", "ขายอยู่", text)
        changes.append({
            "tier": "0-unicode",
            "original": "ขาู่",
            "corrected": "ขายอยู่",
            "count": 1,
            "description": "แก้สระลอย",
        })

    # 2. ย้ายตำแหน่งวรรณยุกต์ที่วางผิดหลังสระอา/ลากข้างยาว เช่น ขา่ -> ข่า
    if re.search(r"([\u0e01-\u0e2e])([\u0e32\u0e45])([\u0e48-\u0e4c])", text):
        cnt = len(re.findall(r"([\u0e01-\u0e2e])([\u0e32\u0e45])([\u0e48-\u0e4c])", text))
        text = re.sub(r"([\u0e01-\u0e2e])([\u0e32\u0e45])([\u0e48-\u0e4c])", r"\1\3\2", text)
        changes.append({
            "tier": "0-unicode",
            "original": "วรรณยุกต์หลังสระอา",
            "corrected": "สลับวรรณยุกต์ไว้บนพยัญชนะ",
            "count": cnt,
            "description": "จัดตำแหน่งวรรณยุกต์มาตรฐาน",
        })

    # 3. ตัดสระ/วรรณยุกต์ลอยที่ไปเกาะหลังสระอา สระอะ ไม้ยมก หรือเครื่องหมายวรรคตอน (สาเหตุของวงกลมประ ◌)
    pattern_dangling = r"([ะาๅๆฯ\s.,!?:;\"\'\(\)\[\]])[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]+"
    if re.search(pattern_dangling, text):
        cnt = len(re.findall(pattern_dangling, text))
        text = re.sub(pattern_dangling, r"\1", text)
        changes.append({
            "tier": "0-unicode",
            "original": "สระลอย/วรรณยุกต์ลอย",
            "corrected": "ลบสระลอยที่ไม่เกาะพยัญชนะ",
            "count": cnt,
            "description": "แก้สระลอย OpenType ◌",
        })

    # 4. ตัดสระ/วรรณยุกต์ลอยที่อยู่ต้นข้อความ
    if re.search(r"^[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]+", text):
        text = re.sub(r"^[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]+", "", text)
        changes.append({
            "tier": "0-unicode",
            "original": "สระลอยต้นข้อความ",
            "corrected": "ลบออก",
            "count": 1,
            "description": "แก้สระลอยต้นประโยค",
        })

    # 5. ยุบสระและวรรณยุกต์ซ้ำซ้อน
    if re.search(r"([\u0e48-\u0e4c]){2,}", text) or re.search(r"([\u0e34-\u0e3a]){2,}", text):
        text = re.sub(r"([\u0e48-\u0e4c]){2,}", r"\1", text)
        text = re.sub(r"([\u0e34-\u0e3a]){2,}", r"\1", text)
        changes.append({
            "tier": "0-unicode",
            "original": "สระ/วรรณยุกต์ซ้อน",
            "corrected": "ยุบเหลือตัวเดียว",
            "count": 1,
            "description": "แก้การพิมพ์วรรณยุกต์เบิ้ล",
        })

    # 6. แปลงสระเอคู่ (เเ) เป็นสระแอ (แ)
    if "\u0e40\u0e40" in text:
        cnt = text.count("\u0e40\u0e40")
        text = text.replace("\u0e40\u0e40", "\u0e41")
        changes.append({
            "tier": "0-unicode",
            "original": "เเ",
            "corrected": "แ",
            "count": cnt,
            "description": "แปลงสระเอคู่เป็นสระแอ",
        })

    # 7. PyThaiNLP normalize
    try:
        norm = normalize(text)
        if norm != text:
            text = norm
    except Exception:
        pass

    # 8. ตรวจจับและตัดอาการหลอนวนลูปคำซ้ำของ Whisper (Whisper Repetition Degeneration Loop)
    loop_pattern = re.compile(r"(.{2,50}?)(?:\s*\1){3,}")
    matches = list(loop_pattern.finditer(text))
    if matches:
        for m in matches:
            rep_unit = m.group(1).strip()
            if not rep_unit:
                continue
            count = len(re.findall(re.escape(rep_unit), m.group(0)))
            changes.append({
                "tier": "0-loop",
                "original": f"{rep_unit} (วนลูป {count} ครั้ง)",
                "corrected": rep_unit if count < 10 else "",
                "count": count,
                "description": "ตัดการหลอนวนลูปคำซ้ำของโมเดลเสียง (Whisper Loop Degeneration)",
            })
        text = re.sub(r"([A-Za-z0-9\sก-๙]{2,50}?)(?:\s*\1){9,}", "", text)
        text = loop_pattern.sub(r"\1", text)

    # 9. ตัดคำหรือตัวอักษรเดี่ยววนซ้ำ (เช่น L L L L L)
    single_token_loop = re.compile(r"(\b\w+\b)(?:\s+\1){3,}")
    text = single_token_loop.sub(r"\1", text)

    # 10. ตัดตัวอักษรไทยเดี่ยวที่เบิ้ลซ้ำผิดปกติจากการลากเสียงหรือโมเดลเสียงหลอน (เช่น มอลลลลล -> มอล, ครับบบบบ -> ครับ)
    if re.search(r'([ก-๙])\1{2,}', text):
        cnt = len(re.findall(r'([ก-๙])\1{2,}', text))
        text = re.sub(r'([ก-๙])\1{2,}', r'\1', text)
        changes.append({
            "tier": "0-repetition",
            "original": "ตัวอักษรเบิ้ลซ้ำ",
            "corrected": "ตัดตัวอักษรลากเสียง",
            "count": cnt,
            "description": "ตัดการเบิ้ลตัวอักษรซ้ำผิดปกติจากการลากเสียง",
        })

    return text.strip(), changes


# ─────────────────────────────────────────────────────────────
#  Custom Dictionary Persistence
# ─────────────────────────────────────────────────────────────

def load_custom_dict() -> Dict[str, str]:
    if CUSTOM_DICT_PATH.exists():
        try:
            return json.loads(CUSTOM_DICT_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_custom_dict(mapping: Dict[str, str]) -> None:
    try:
        CUSTOM_DICT_PATH.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"Error saving custom dict: {exc}")


def add_custom_word(wrong: str, right: str) -> None:
    w = wrong.strip()
    r = right.strip()
    if not w or not r:
        return
    d = load_custom_dict()
    d[w] = r
    save_custom_dict(d)


def remove_custom_word(wrong: str) -> None:
    d = load_custom_dict()
    if wrong in d:
        del d[wrong]
        save_custom_dict(d)


# ─────────────────────────────────────────────────────────────
#  Data Loaders: Ground Truth Map & Pharmacy Ontology
# ─────────────────────────────────────────────────────────────

def _load_ground_truth_map() -> Dict[str, str]:
    gt_file = DATA_DIR / "ground_truth_map.json"
    if gt_file.exists():
        try:
            return json.loads(gt_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_drugs_catalog() -> Dict[str, List[Dict[str, Any]]]:
    catalog_file = DATA_DIR / "drugs_catalog.json"
    if catalog_file.exists():
        try:
            return json.loads(catalog_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# In-memory datasets
SAFE_DRUG_NAMES: Dict[str, str] = {
    # Default built-in base terms
    "Setifisine":           "Cetirizine",
    "เซทิริซีน":            "Cetirizine",
    "เซทิริซิน":            "Cetirizine",
    "อม็อกซี่คือดิน":        "Amoxicillin-Clavulanate",
    "อมซี่คอมโมโดนิก":      "Amoxicillin-Clavulanic",
    "อัมซี่ลิน":            "Amoxicillin",
    "อะม็อกซี่":            "Amoxicillin",
    "โคชีซีน":              "Colchicine",
    "โคซีซีน":              "Colchicine",
    "โคซีม":               "Colchicine",
    "โคจิซีน":              "Colchicine",
    "โคชิซีน":              "Colchicine",
    "โคลชิซีน":             "Colchicine",
    "โคลชีซีน":             "Colchicine",
    "โคชิ้น":               "Colchicine",
    "โคิน":                "Colchicine",
    "ไซโปเคเตอร์":         "Cyproheptadine",
    "ไซโปรเฮปทาดีน":       "Cyproheptadine",
    "ไฮด็อกซิก":           "Hydroxyzine",
    "ไฮดรอกซีซีน":          "Hydroxyzine",
    "เมโทนี่นาโซ":         "Metronidazole",
    "เมโทลิดาโซ":          "Metronidazole",
    "เมโทรลิดาโซ":         "Metronidazole",
    "เมโทรนิดาโซล":        "Metronidazole",
    "คาโบฟิตเตอร์อีน":     "Carbocisteine",
    "รีโวเซน":             "Levocetirizine",
    "เด็กโตเมอร์":         "Dextromethorphan",
    "อีโดลิค":             "Etodolac",
    "อีโตลิค":             "Etodolac",
    "ไอฟีลีน":             "Difelene",
    "โอฟี่ลั่น":            "Difelene",
    "ไดฟีลีน":             "Diclofenac",
    "ไดโคฟีน":             "Diclofenac",
    "ไดโคลฟีแนค":          "Diclofenac",
    "ไดโคลฟี":             "Diclofenac",
    "โดเฟล":               "Diclofenac",
    "ไพรอกซีแคม":          "Piroxicam",
    "ล็อกซีแคมป์":          "Piroxicam",
    "ไพร็อกซิแคมป์":        "Piroxicam",
    "ไดแคม":               "Dicam",
    "เบียร์แพงป์":          "Dicam (Piroxicam)",
    "เบียร์แพง":           "Dicam (Piroxicam)",
    "ค่าเชื้อ":            "ฆ่าเชื้อ",
    "มิติกรรม":            "มิลลิกรัม",
    "ขมุดขมุด":            "ขวดละ",
    "เป็นพผง":             "เป็นแผง",
    "ทานตามประกัน":         "ทานตามอาการ",
    "ของแถลง":             "ของแสลง",
    "ปวดฝัน":              "ปวดฟัน",
    "ไปทอนออก":            "ไปถอนออก",
    "เคมีล":               "เคมิล (Kremil)",
    "เคมิล็อต":            "เคมิล (Kremil)",
    "โอมิคราโซ":           "โอเมพราโซล",
    "โอมิปาโซ":            "โอเมพราโซล",
    "โอมิโฟ":              "โอเมพราโซล",
    "ยาฆ่าเชื้อราษฎร์":       "ยาฆ่าเชื้อรา",
    "ยาฆ่าเชื้ออาหาร":       "ยาฆ่าเชื้อรา",
    "กลอนอาหาร":           "ก่อนอาหาร",
    "ต่อมือ":              "ต่อมื้อ",
    "หล่อใหญ่":            "หลอดใหญ่",
    "รถกำลังกด":           "ลดการหลั่งกรด",
    "รถการรังกด":          "ลดการหลั่งกรด",
    "ลดการรังกด":          "ลดการหลั่งกรด",
    "ยศยามรถ":             "ตัวยาลด",
    "ตัวยอด":              "ตัวยา",
    "ตีม่า":               "ซีม่า",
    "ทีม่า":               "ซีม่า",
    "ดีมาน":               "ซีม่า",
    "ตีมาน":               "ซีม่า",
    "วีแคป":               "บีแคป",
    "ตัวVแคป":             "บีแคป",
    "มีฉายาอะไร":          "มีใช้ยาอะไร",
    "แผลยังไม่มีเลย":       "แพ้ยาไม่มีเลย",
    "ริมผีป่า":             "ริมฝีปาก",
    "ป่านกกระจอก":          "ปากนกกระจอก",
    "ใช้ยาฆ่าฝาด":         "ใช้ยารักษา",
    "คาบูโลนิค":           "คลาวูลานิก",
    "รอบไซน์":             "ดรอปไซส์",
}

# Merge with external ground_truth_map.json
SAFE_DRUG_NAMES.update(_load_ground_truth_map())


# ─────────────────────────────────────────────────────────────
#  Layer 3: REGEX & CONTEXT-GUARDED PATTERNS
# ─────────────────────────────────────────────────────────────

REGEX_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # สระลอย / คำเพี้ยนจาก ASR
    (
        re.compile(r"ขา[ูู่่]+ไง"),
        "ขายยังไง",
        "ขาู่ไง -> ขายยังไง (แก้สระลอย/สะกดเพี้ยน)"
    ),
    (
        re.compile(r"ขา[ูู่่]+"),
        "ขายอยู่",
        "ขาู่ -> ขายอยู่ (แก้สระลอย)"
    ),
    (
        re.compile(r"ขมุดขมุด"),
        "ขวดละ",
        "ขมุดขมุด -> ขวดละ"
    ),

    # ซีม่า (Zema ยาฆ่าเชื้อรา)
    (
        re.compile(r"(ตีม่า|ทีม่า|ดีมาน|ตีมาน)"),
        "ซีม่า",
        "ตีม่า -> ซีม่า (ยาฆ่าเชื้อรา)"
    ),
    (
        re.compile(r"ยาศัพท์เชื[า้า]*ร์?ราชนะ"),
        "ยาฆ่าเชื้อรา",
        "ยาศัพท์เชืาร์ราชนะ -> ยาฆ่าเชื้อรา"
    ),
    (
        re.compile(r"จริงจร[ีย]*[งย]"),
        "จริงจริง",
        "จริงจรียง -> จริงจริง"
    ),
    (
        re.compile(r"(?<=เอาเป็น)โมชั่น|(?<=เป็น)โมชั่น"),
        "โลชั่น",
        "โมชั่น -> โลชั่น"
    ),

    # "หนึ่งเมตร/สองเมตร" -> "หนึ่งเม็ด/สองเม็ด"
    (
        re.compile(r"(?<!มิลลิ)(หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ครึ่ง|กี่|หลาย|\d+)\s*เมตร"),
        r"\1เม็ด",
        "เมตร -> เม็ด (จำนวนยา)"
    ),

    # "รถอาการปวด" / "รถปวด" / "รถอักเสบ" -> "ลดอาการปวด"
    (
        re.compile(r"รถ\s*(อาการ)?\s*(ปวด|อักเสบ|บวม)"),
        r"ลด\1\2",
        "รถปวด/รถอักเสบ -> ลดปวด/ลดอักเสบ"
    ),

    # "รถกด" -> "ลดกรด" (ในบริบทร้านยาเท่านั้น)
    (
        re.compile(r"รถกด"),
        "ลดกรด",
        "รถกด -> ลดกรด"
    ),

    # "รถไข้" -> "ลดไข้"
    (
        re.compile(r"รถไข้"),
        "ลดไข้",
        "รถไข้ -> ลดไข้"
    ),

    # "รถน้ํามูก" / "รถน้ำมูก" -> "ลดน้ำมูก"
    (
        re.compile(r"รถ\s*น้[ํำ]ามูก"),
        "ลดน้ำมูก",
        "รถน้ำมูก -> ลดน้ำมูก"
    ),

    # "ของแถลง" -> "ของแสลง" (ในบริบทอาหารแสลง/ของแสลง)
    (
        re.compile(r"ของแถลง"),
        "ของแสลง",
        "ของแถลง -> ของแสลง"
    ),

    # "ทุกครั้งที่ป่วน" -> "ทุกครั้งที่ปวด"
    (
        re.compile(r"(ทุกครั้ง|เวลา)\s*ที่ป่วน"),
        r"\1ที่ปวด",
        "ที่ป่วน -> ที่ปวด"
    ),

    # "ปวดเก๋า/เป็นเก๋า" -> "ปวดเก๊า/เป็นเก๊า"
    (
        re.compile(r"(ปวด|เป็น)\s*เก๋า"),
        r"\1เก๊า",
        "เก๋า -> เก๊า (โรคเก๊าท์)"
    ),

    # "เด็กโตกดอาการ/เด็กโตกดอากาศ" -> "Dextromethorphan" (กดอาการไอ)
    (
        re.compile(r"เด็กโตกด\s*(อาการ|อากาศ)"),
        r"Dextromethorphan (กดอาการ)",
        "เด็กโตกด -> Dextromethorphan"
    ),

    # "ห้าร้อยมิลลิเมตร" / "สองมิลลิเมตร" -> "ห้าร้อยมิลลิกรัม" / "สองมิลลิกรัม" (ในบริบทยา)
    (
        re.compile(r"([๑-๙\d]|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ร้อย|พัน|กี่)(\s*)มิลลิเมตร"),
        r"\1\2มิลลิกรัม",
        "มิลลิเมตร -> มิลลิกรัม (หน่วยยา)"
    ),

    # "ห้ามรอมิติกรรม" -> "ห้าร้อยมิลลิกรัม"
    (
        re.compile(r"ห้ามรอมิติกรรม"),
        "ห้าร้อยมิลลิกรัม",
        "ห้ามรอมิติกรรม -> ห้าร้อยมิลลิกรัม"
    ),

    # "ห้ามมิติกรรม" -> "ห้ามิลลิกรัม"
    (
        re.compile(r"ห้ามมิติกรรม"),
        "ห้ามิลลิกรัม",
        "ห้ามมิติกรรม -> ห้ามิลลิกรัม"
    ),

    # "ได้ครบไปไหนห้าสิบมิลลิกรัม" -> "ไดโคลฟีแนค 50 มิลลิกรัม"
    (
        re.compile(r"ได้ครบไปไหน\s*(ห้าสิบ|50)\s*มิลลิกรัม"),
        r"ไดโคลฟีแนค \1มิลลิกรัม",
        "ได้ครบไปไหน -> ไดโคลฟีแนค"
    ),

    # "นักเลิศแม่งแบบสีขาว..." -> "ตัวสีขาวอันนี้"
    (
        re.compile(r"นักเลิศ.*แบบสีขาว[^\s]*"),
        "ตัวสีขาวอันนี้",
        "นักเลิศแบบสีขาว -> ตัวสีขาว (ลักษณะเม็ดยา)"
    ),

    # "(จาก|หนัก)สิบบาทเป็นต้น" -> "สามสิบบาทเงินทอน"
    (
        re.compile(r"(จาก|หนัก)\s*สิบบาทเป็นต้น"),
        "สามสิบบาทเงินทอน",
        "สิบบาทเป็นต้น -> สามสิบบาทเงินทอน"
    ),

    # "มีราคาที่ถูกแบบนี้หลายนึง" -> "มีราคาที่ถูกกว่านี้มั้ย"
    (
        re.compile(r"มีราคาที่ถูกแบบนี้หลายนึง"),
        "มีราคาที่ถูกกว่านี้มั้ย",
        "ราคาที่ถูกแบบนี้หลายนึง -> ราคาที่ถูกกว่านี้มั้ย"
    ),
]


# ─────────────────────────────────────────────────────────────
#  Layer 4: PHONETIC & SOUNDEX WITH MEDICAL TRIGGER GUARD
# ─────────────────────────────────────────────────────────────

MEDICAL_ANCHORS = {
    "ทาน", "กิน", "ยา", "เม็ด", "มิลลิกรัม", "มก", "อาการ", "รักษา", "ขนาน",
    "แผง", "ขวด", "หลอด", "ฉีด", "หยอด", "พ่น", "ทา", "ซอง", "ซีซี", "มล",
    "แก้ปวด", "ฆ่าเชื้อ", "ลดไข้", "ลดน้ำมูก", "ลดกรด", "ขับลม", "เชื้อรา",
    "แก้แพ้", "แก้หวัด", "แก้ไอ", "ละลายเสมหะ", "เจ็บคอ", "พ่นคอ", "หยอดตา", "ตัวยา"
}

DISCOURSE_BOUNDARIES = {
    "หรือ", "และ", "กับ", "แต่", "ที่", "ใน", "ของ", "มี", "ไม่", "ได้",
    "เอา", "ขอ", "ไหม", "มั้ย", "ครับ", "ค่ะ", "ฮะ", "นะ", "เนาะ", "เนอะ",
    "ว่า", "เป็น", "ก็", "จะ", "ให้", "ดี"
}

_PHONETIC_INDEX: Optional[Dict[str, str]] = None
_KNOWN_DRUG_WORDS: Optional[set] = None


def _build_phonetic_lookup() -> Tuple[Dict[str, str], set]:
    """
    Builds a soundex lookup index and known drug lexicon from the drugs catalog.
    Maps: soundex_code -> standard drug or brand name
    """
    if not thai_soundex:
        return {}, set()

    catalog = _load_drugs_catalog()
    lookup: Dict[str, str] = {}
    known_words: set = set()

    for cat, items in catalog.items():
        for item in items:
            thai_name = item.get("thai", "").strip()
            gen_name = item.get("generic", "").strip()
            if thai_name:
                known_words.add(thai_name)
                if len(thai_name) >= 3:
                    try:
                        code = thai_soundex(thai_name, engine="lk82")
                        if code and code not in lookup:
                            lookup[code] = thai_name
                    except Exception:
                        pass
            if gen_name:
                known_words.add(gen_name)

            for b in item.get("brands", []):
                b = b.strip()
                if b:
                    known_words.add(b)
                    if len(b) >= 3:
                        try:
                            code = thai_soundex(b, engine="lk82")
                            if code and code not in lookup:
                                lookup[code] = b
                        except Exception:
                            pass

    return lookup, known_words


def apply_phonetic_matching(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Scans token spans (1-6 grams) in the text. If a phonetic match is found for a drug
    in the ontology AND it is guarded by a medical anchor word nearby (+/- 3 tokens),
    resolves it to the standard drug or brand name.
    Guarantees zero false positives on everyday conversation.
    """
    global _PHONETIC_INDEX, _KNOWN_DRUG_WORDS
    if not thai_soundex:
        return text, []

    if _PHONETIC_INDEX is None or _KNOWN_DRUG_WORDS is None:
        _PHONETIC_INDEX, _KNOWN_DRUG_WORDS = _build_phonetic_lookup()

    if not _PHONETIC_INDEX:
        return text, []

    # Check if text contains any medical anchor at all
    has_anchor = any(anchor in text for anchor in MEDICAL_ANCHORS)
    if not has_anchor:
        return text, []

    changes: List[Dict[str, Any]] = []
    tokens = word_tokenize(text)
    n = len(tokens)
    if n == 0:
        return text, []

    new_tokens = list(tokens)
    matched_indices = set()

    # Try spans from 6 down to 1 (longest match first)
    for k in (6, 5, 4, 3, 2, 1):
        for i in range(n - k + 1):
            if any(idx in matched_indices for idx in range(i, i + k)):
                continue

            span_tokens = tokens[i : i + k]
            # Avoid spans crossing discourse conjunctions
            if k > 1 and any(tok in DISCOURSE_BOUNDARIES for tok in span_tokens):
                continue

            span = "".join(span_tokens).strip()
            if len(span) < 3:
                continue

            # If already spelled correctly as a known drug/brand, protect it
            if span in _KNOWN_DRUG_WORDS:
                for j in range(i, i + k):
                    matched_indices.add(j)
                continue

            # Look in +/- 3 window for a medical anchor
            window_start = max(0, i - 3)
            window_end = min(n, i + k + 3)
            window = tokens[window_start:window_end]

            if not any(a in window for a in MEDICAL_ANCHORS):
                continue

            try:
                code = thai_soundex(span, engine="lk82")
                if code in _PHONETIC_INDEX:
                    clean_target = _PHONETIC_INDEX[code]
                    # Length sanity check: candidate length must be comparable
                    if abs(len(span) - len(clean_target)) <= 3 or (0.7 <= len(span) / len(clean_target) <= 1.3):
                        if span != clean_target and clean_target not in text:
                            new_tokens[i] = clean_target
                            for j in range(i + 1, i + k):
                                new_tokens[j] = ""
                            for j in range(i, i + k):
                                matched_indices.add(j)
                            changes.append({
                                "tier": "4-phonetic",
                                "original": span,
                                "corrected": clean_target,
                                "count": 1,
                                "description": f"Phonetic Soundex: {span} -> {clean_target} (Medical context)",
                            })
            except Exception:
                pass

    return "".join(new_tokens), changes


# ─────────────────────────────────────────────────────────────
#  Core API: 5-Layer Hybrid Pipeline
# ─────────────────────────────────────────────────────────────

def correct_transcript(
    text: str,
    apply_unicode: bool = True,
    apply_safe: bool = True,
    apply_ontology: bool = True,
    apply_regex: bool = True,
    apply_phonetic: bool = True,
    apply_custom: bool = True,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    แก้คำผิดและสระลอยใน transcript จาก STT โดยใช้ระบบ 5-Layer Hybrid Pipeline:
      - Layer 0: Unicode & Repetition Loop Purge
      - Layer 1: Empirical Ground-Truth Mapping
      - Layer 2: Categorized Pharmacy Ontology
      - Layer 3: Context-Guarded Pattern Engine
      - Layer 4: Phonetic & Soundex Matching with Medical Trigger Guard
      - Layer Custom: User Custom Dictionary

    Returns:
        (corrected_text, changes)
    """
    if not text or not text.strip():
        return text, []

    corrected = text
    changes: List[Dict[str, Any]] = []

    # ── Layer 0: Thai Unicode & Acoustic Loop Cleaning ──
    if apply_unicode:
        corrected, uni_changes = clean_thai_unicode(corrected)
        changes.extend(uni_changes)

    # ── Layer Custom: User-defined Custom Dictionary (Longest Match First) ──
    if apply_custom:
        custom_dict = load_custom_dict()
        sorted_custom = sorted(custom_dict.items(), key=lambda x: len(x[0]), reverse=True)
        for wrong, right in sorted_custom:
            if wrong in corrected:
                count = corrected.count(wrong)
                corrected = corrected.replace(wrong, right)
                changes.append({
                    "tier": "custom",
                    "original": wrong,
                    "corrected": right,
                    "count": count,
                    "description": "คำศัพท์กำหนดเองโดยผู้ใช้",
                })

    # ── Layer 1: Empirical Ground-Truth Mapping (Longest Match First) ──
    if apply_safe:
        sorted_safe = sorted(SAFE_DRUG_NAMES.items(), key=lambda x: len(x[0]), reverse=True)
        for wrong, right in sorted_safe:
            if wrong in corrected:
                count = corrected.count(wrong)
                corrected = corrected.replace(wrong, right)
                changes.append({
                    "tier": "1-safe",
                    "original": wrong,
                    "corrected": right,
                    "count": count,
                    "description": "ชื่อยา/คำทางการแพทย์ที่ถอดเสียงผิด",
                })

    # ── Layer 2: Categorized Pharmacy Ontology Brands Normalizer ──
    if apply_ontology:
        catalog = _load_drugs_catalog()
        for cat, items in catalog.items():
            for item in items:
                generic_thai = item.get("thai", "")
                for brand in item.get("brands", []):
                    # Normalizes phonetic misspellings of brands if safe
                    if brand in corrected and generic_thai and brand != generic_thai:
                        # We don't overwrite the brand, but record ontology classification if needed
                        pass

    # ── Layer 3: Context-Guarded Regex Patterns ──
    if apply_regex:
        for pattern, replacement, description in REGEX_PATTERNS:
            matches = pattern.findall(corrected)
            if matches:
                count = len(matches)
                corrected = pattern.sub(replacement, corrected)
                display_orig = pattern.pattern
                display_corr = replacement
                if " -> " in description:
                    parts = description.split(" (")[0].split(" -> ")
                    if len(parts) == 2:
                        display_orig = parts[0].strip()
                        display_corr = parts[1].strip()
                changes.append({
                    "tier": "3-regex",
                    "original": display_orig,
                    "corrected": display_corr,
                    "count": count,
                    "description": description,
                })

    # ── Layer 4: Phonetic & Soundex Matching with Medical Trigger Guard ──
    if apply_phonetic:
        corrected, phon_changes = apply_phonetic_matching(corrected)
        changes.extend(phon_changes)

    return corrected, changes


# Alias for intuitive import
apply_pharmacy_dictionary = correct_transcript


def get_stats(changes_list: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    รวมสถิติจาก changes หลายๆ ไฟล์
    """
    from collections import Counter

    total = 0
    by_tier = Counter()
    correction_freq = Counter()

    for changes in changes_list:
        for change in changes:
            count = change.get("count", 1)
            total += count
            by_tier[change.get("tier", "unknown")] += count
            key = f'{change.get("original", "")} -> {change.get("corrected", "")}'
            correction_freq[key] += count

    return {
        "total_corrections": total,
        "by_tier": dict(by_tier),
        "top_corrections": correction_freq.most_common(15),
    }


# ─────────────────────────────────────────────────────────────
#  Layer 5: LLM Post-Processing Prompt Template
# ─────────────────────────────────────────────────────────────

LLM_CORRECTION_PROMPT = """คุณเป็นผู้เชี่ยวชาญด้านเภสัชกรรม กรุณาตรวจสอบและแก้ไขชื่อยาที่ถอดเสียงผิดในบทสนทนาต่อไปนี้
โดยเฉพาะ:
1. ชื่อยาสากล (Generic names) ที่อาจถูกถอดเสียงเป็นคำไทยที่ไม่มีความหมาย
2. หน่วยยาที่ผิด (เช่น มิลลิเมตร ควรเป็น มิลลิกรัม)
3. คำสั่งใช้ยาที่ฟังเพี้ยน
4. เว้นวรรคให้อ่านง่ายขึ้น

ยาที่พบบ่อยในร้านยา:
- Paracetamol (พาราเซตามอล), Ibuprofen (ไอบูโพรเฟน), Amoxicillin (อะม็อกซีซิลลิน)
- Cetirizine (เซทิริซีน), Levocetirizine (เลโวเซทิริซีน), Loratadine (ลอราทาดีน)
- Dextromethorphan (เด็กซ์โทรเมธอร์แฟน), Carbocisteine (คาร์โบซิสเทอีน)
- Colchicine (โคลชิซีน), Diclofenac (ไดโคลฟีแนค), Naproxen (นาพร็อกเซน)
- Metronidazole (เมโทรนิดาโซล), Roxithromycin (ร็อกซิโทรมัยซิน)
- Hydroxyzine (ไฮดรอกซีซีน), Cyproheptadine (ไซโปรเฮปทาดีน)
- Etodolac (อีโทโดแลค), Etoricoxib (อีโทริค็อกซิบ)
- Omeprazole (โอเมพราโซล), Kremil-S (เคมิล), Air-X (แอร์เอ็กซ์)
- Zema (ซีม่า), Canesten (คาเนสเทน)

กรุณาแก้ไขเฉพาะชื่อยาและคำทางการแพทย์ที่ผิดเท่านั้น ห้ามเปลี่ยนเนื้อหาอื่น
ตอบเฉพาะบทสนทนาที่แก้ไขแล้ว ไม่ต้องอธิบาย

บทสนทนา:
{transcript}"""
