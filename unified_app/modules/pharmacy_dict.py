"""
Pharmacy Dictionary -- Comprehensive 5-Layer Hybrid Post-processing Module for STT.

สถาปัตยกรรม 5 เลเยอร์สำหรับแก้ไข Transcript ร้านยา:
  - Layer 0: Unicode & Acoustic Anomaly Cleaner (ล้างสระลอย, สลับวรรณยุกต์หลังสระอะ/อา, และตัด Whisper Degeneration Loop)
  - Layer 1: Empirical Ground-Truth Mapping (คลังคำผิดจริงจากการสกัดเทปเสียง ทำงานแบบ Single-Pass Regex กันการแก้ทับซ้ำ)
  - Layer 2: Structured Pharmacy Ontology & Sig Normalizer (คลังยาจัดหมวดหมู่และคลังหน่วยยา/วิธีใช้ยาจาก dosage_and_sig.json)
  - Layer 3: Context-Guarded Regex Engine (กฎไวยากรณ์และบริบทแวดล้อม: จำนวนยา, มื้อยา, หน่วยยา, รูปแบบยา)
  - Layer 4: Phonetic & Soundex Matching with Levenshtein & Medical Trigger Guard (จับคู่เสียงใกล้เคียง + Edit Distance เมื่อมีคำบริบทแพทย์)
  - Layer Custom: User-defined Custom Dictionary (คำศัพท์กำหนดเองจากหน้า UI)

Usage:
    from unified_app.modules.pharmacy_dict import correct_transcript, get_stats

    raw = "ค่าเชื้อตัวหนึ่งครับ ทานหนึ่งเมตรเช้าเย็น หกร้อยมิติกรรม"
    corrected, changes = correct_transcript(raw)
"""

from collections import Counter
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

_LOCAL_DATA_DIR = Path(__file__).resolve().parent / "pharmacy_data"
_LAB_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "lab" / "modules" / "pharmacy_data"
DATA_DIR = _LOCAL_DATA_DIR if _LOCAL_DATA_DIR.exists() else _LAB_DATA_DIR

_LOCAL_CUSTOM_DICT = Path(__file__).resolve().parent.parent / "custom_dict.json"
_LAB_CUSTOM_DICT = Path(__file__).resolve().parent.parent.parent / "lab" / "custom_dict.json"
CUSTOM_DICT_PATH = _LOCAL_CUSTOM_DICT if _LOCAL_CUSTOM_DICT.exists() else _LAB_CUSTOM_DICT


# ─────────────────────────────────────────────────────────────
#  Helper: Single-Pass Dictionary Replacement (No Substring Collision)
# ─────────────────────────────────────────────────────────────

def _apply_single_pass_dict(
    text: str,
    mapping: Dict[str, str],
    tier: str,
    default_desc: str,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Replaces all keys from `mapping` in `text` using a single-pass compiled regex
    ordered by key length descending. Prevents shorter keys from corrupting
    already-replaced substrings.
    """
    if not text or not mapping:
        return text, []

    valid_items = {k: v for k, v in mapping.items() if k and v and k != v}
    if not valid_items:
        return text, []

    sorted_keys = sorted(valid_items.keys(), key=len, reverse=True)
    pattern = re.compile(
        "(?:" + "|".join(re.escape(k) for k in sorted_keys) + r")(?![\u0e31\u0e34-\u0e3a\u0e47-\u0e4e])"
    )

    match_counts: Counter = Counter()
    order_seen: List[str] = []

    def _replacer(match: re.Match) -> str:
        orig = match.group(0)
        if orig not in match_counts:
            order_seen.append(orig)
        match_counts[orig] += 1
        return valid_items[orig]

    new_text = pattern.sub(_replacer, text)
    if not match_counts:
        return text, []

    changes: List[Dict[str, Any]] = [
        {
            "tier": tier,
            "original": orig,
            "corrected": valid_items[orig],
            "count": match_counts[orig],
            "description": default_desc,
        }
        for orig in order_seen
    ]
    return new_text, changes


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

    # 0. กำจัดอักขระเสีย Unicode Replacement Character (U+FFFD \ufffd) และสระ/วรรณยุกต์ที่เกาะอยู่
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

    # 1. แก้ไขคำเพี้ยนเฉพาะที่โมเดลเสียงมักถอดเป็นสระลอย เช่น ขาู่ไง -> ขายยังไง
    if re.search(r"ขา[\u0e38\u0e39][\u0e48-\u0e4c]*ไง", text):
        text = re.sub(r"ขา[\u0e38\u0e39][\u0e48-\u0e4c]*ไง", "ขายยังไง", text)
        changes.append({
            "tier": "0-unicode",
            "original": "ขาู่ไง",
            "corrected": "ขายยังไง",
            "count": 1,
            "description": "แก้สระลอยและเสียงรวบ (Acoustic slur)",
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

    # 2. ย้ายตำแหน่งวรรณยุกต์ที่วางผิดหลังสระอะ/สระอา/ลากข้างยาว เช่น คะ่ -> ค่ะ, จะ้ -> จ้ะ, ขา่ -> ข่า
    misplaced_tone_pattern = r"([\u0e01-\u0e2e])([\u0e30\u0e32\u0e45])([\u0e48-\u0e4c])"
    if re.search(misplaced_tone_pattern, text):
        cnt = len(re.findall(misplaced_tone_pattern, text))
        text = re.sub(misplaced_tone_pattern, r"\1\3\2", text)
        changes.append({
            "tier": "0-unicode",
            "original": "วรรณยุกต์หลังสระอะ/อา",
            "corrected": "สลับวรรณยุกต์ไว้บนพยัญชนะ",
            "count": cnt,
            "description": "จัดตำแหน่งวรรณยุกต์มาตรฐาน",
        })

    # 3. ตัดสระ/วรรณยุกต์ลอยที่ไปเกาะหลังสระอา สระอะ ไม้ยมก หรือเครื่องหมายวรรคตอน (สาเหตุของวงกลมประ)
    pattern_dangling = r"([ะาๅๆฯ\s.,!?:;\"\'\(\)\[\]])[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]+"
    if re.search(pattern_dangling, text):
        cnt = len(re.findall(pattern_dangling, text))
        text = re.sub(pattern_dangling, r"\1", text)
        changes.append({
            "tier": "0-unicode",
            "original": "สระลอย/วรรณยุกต์ลอย",
            "corrected": "ลบสระลอยที่ไม่เกาะพยัญชนะ",
            "count": cnt,
            "description": "แก้สระลอย OpenType",
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

    # 8. ตรวจจับและตัดอาการหลอนวนลูปคำซ้ำของโมเดลเสียง (Repetition Degeneration Loop)
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
                "description": "ตัดการหลอนวนลูปคำซ้ำของโมเดลเสียง (Loop Degeneration)",
            })
        text = re.sub(r"([A-Za-z0-9\sก-๙]{2,50}?)(?:\s*\1){9,}", "", text)
        text = loop_pattern.sub(r"\1", text)

    # 9. ตัดคำหรือตัวอักษรเดี่ยววนซ้ำ (เช่น L L L L L)
    single_token_loop = re.compile(r"(\b\w+\b)(?:\s+\1){3,}")
    text = single_token_loop.sub(r"\1", text)

    # 10. ตัดตัวอักษรไทยเดี่ยวที่เบิ้ลซ้ำผิดปกติจากการลากเสียง (เช่น มอลลลลล -> มอล, ครับบบบบ -> ครับ)
    if re.search(r"([ก-๙])\1{2,}", text):
        cnt = len(re.findall(r"([ก-๙])\1{2,}", text))
        text = re.sub(r"([ก-๙])\1{2,}", r"\1", text)
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
#  Data Loaders: Ground Truth Map, Ontology & Dosage Sig
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


def _load_dosage_and_sig() -> Dict[str, List[Dict[str, Any]]]:
    sig_file = DATA_DIR / "dosage_and_sig.json"
    if sig_file.exists():
        try:
            return json.loads(sig_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# Words in dosage_and_sig.json that are valid everyday Thai words on their own
# and MUST only be replaced via context-guarded regex in Layer 3 (never globally).
_CONTEXT_ONLY_SIG_WORDS = {
    "เมตร", "สอง", "ส่อง", "แพง", "คดี", "โมชั่น",
    "มก.", "mg", "มล.", "ml", "cc", "c.c.", "g", "gm", "tsp", "tbsp", "IU", "unit",
}


def _build_ontology_sig_map() -> Dict[str, str]:
    """
    Builds a direct replacement map from `dosage_and_sig.json` for unambiguous
    misheard dosage units, forms, and regimen phrases (excluding context-dependent words).
    """
    sig_data = _load_dosage_and_sig()
    mapping: Dict[str, str] = {}

    for entry in sig_data.get("units", []):
        std = entry.get("standard", "").strip()
        for var in entry.get("variants", []):
            var = var.strip()
            if std and var and var not in _CONTEXT_ONLY_SIG_WORDS:
                mapping[var] = std

    for section in ("forms", "regimen"):
        for entry in sig_data.get(section, []):
            std = entry.get("standard", "").strip()
            for mis in entry.get("misheard", []):
                mis = mis.strip()
                if std and mis and mis not in _CONTEXT_ONLY_SIG_WORDS:
                    # "หล่อใหญ่" -> "หลอดใหญ่" preserves the modifier "ใหญ่"
                    if mis == "หล่อใหญ่" and std == "หลอด":
                        mapping[mis] = "หลอดใหญ่"
                    elif mis == "เป็นพผง" and std == "แผง":
                        mapping[mis] = "เป็นแผง"
                    else:
                        mapping[mis] = std

    return mapping


# In-memory datasets (Layer 1 Ground-Truth Map)
SAFE_DRUG_NAMES: Dict[str, str] = {
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

# Layer 2 Ontology & Sig Dictionary (excluding keys already handled in SAFE_DRUG_NAMES)
ONTOLOGY_SIG_MAP: Dict[str, str] = {
    k: v for k, v in _build_ontology_sig_map().items() if k not in SAFE_DRUG_NAMES
}


# ─────────────────────────────────────────────────────────────
#  Layer 3: REGEX & CONTEXT-GUARDED PATTERNS
# ─────────────────────────────────────────────────────────────

_THAI_NUM_WORDS = r"(?:หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ครึ่ง|กี่|หลาย|[๑-๙\d]+)"

REGEX_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # ยาฆ่าเชื้อรา (รูปแบบสะกดเพี้ยนหลากหลาย)
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

    # บริบทรูปแบบยา: โลชั่น / ครีม / แผง / ซอง
    (
        re.compile(r"(?<=เอาเป็น)โมชั่น|(?<=เป็น)โมชั่น|(?<=ทา)โมชั่น"),
        "โลชั่น",
        "โมชั่น -> โลชั่น (บริบทยาทา)"
    ),
    (
        re.compile(r"(ทา|ทายา|เอาเป็น|เป็น)\s*คดี"),
        r"\1ครีม",
        "คดี -> ครีม (บริบทยาทา)"
    ),
    (
        re.compile(rf"(ยา|เอา|ซื้อ|ยก|เป็น)\s*({_THAI_NUM_WORDS})\s*แพง"),
        r"\1 \2แผง",
        "แพง -> แผง (จำนวนแผงยา)"
    ),
    (
        re.compile(rf"(ชง|ละลายน้ำ|เกลือแร่|ผง)\s*({_THAI_NUM_WORDS})\s*(?:สอง|ส่อง)"),
        r"\1 \2ซอง",
        "สอง/ส่อง -> ซอง (บริบทผงชง/เกลือแร่)"
    ),
    (
        re.compile(rf"({_THAI_NUM_WORDS})\s*(?:สอง|ส่อง)\s*(ละลายน้ำ|ผสมน้ำ|ชงน้ำ)"),
        r"\1ซอง\2",
        "สอง/ส่อง -> ซอง (บริบทละลายน้ำ)"
    ),

    # "หนึ่งเมตร/สองเมตร" -> "หนึ่งเม็ด/สองเม็ด" (กัน "มิลลิเมตร" ไว้ให้กฎหน่วยยาด้านล่าง)
    (
        re.compile(rf"(?<!มิลลิ)({_THAI_NUM_WORDS})\s*เมตร"),
        r"\1เม็ด",
        "เมตร -> เม็ด (จำนวนยา)"
    ),

    # "ห้าร้อยมิลลิเมตร" / "สองมิลลิเมตร" -> "ห้าร้อยมิลลิกรัม" / "สองมิลลิกรัม"
    (
        re.compile(r"([๑-๙\d]|หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ร้อย|พัน|กี่)(\s*)มิลลิเมตร"),
        r"\1\2มิลลิกรัม",
        "มิลลิเมตร -> มิลลิกรัม (หน่วยยา)"
    ),

    # "เม็ดละ 500 มิลลิลิตร" -> "เม็ดละ 500 มิลลิกรัม" (เม็ดยาใช้หน่วยเป็นมิลลิกรัม)
    (
        re.compile(r"(เม็ดละ\s*[๑-๙\d]+\s*)มิลลิลิตร"),
        r"\1มิลลิกรัม",
        "มิลลิลิตร -> มิลลิกรัม (บริบทเม็ดละ)"
    ),

    # "รถอาการปวด" / "รถปวด" / "รถอักเสบ" / "รถไข้" / "รถกรด" / "รถน้ำมูก" -> "ลด..."
    (
        re.compile(r"รถ\s*(อาการ)?\s*(ปวด|อักเสบ|บวม|ไข้|กรด|กด|น้ำมูก|น้ํามูก)"),
        lambda m: f"ลด{m.group(1) or ''}{'กรด' if m.group(2) == 'กด' else ('น้ำมูก' if m.group(2) == 'น้ํามูก' else m.group(2))}",
        "รถปวด/รถไข้/รถกรด -> ลดปวด/ลดไข้/ลดกรด"
    ),

    # "ทุกครั้งที่ป่วน" -> "ทุกครั้งที่ปวด"
    (
        re.compile(r"(ทุกครั้ง|เวลา)\s*ที่ป่วน"),
        r"\1ที่ปวด",
        "ที่ป่วน -> ที่ปวด"
    ),

    # "ปวดเก๋า/ปวดเกา/เป็นเก๋า/โรคเก๋า" -> "ปวดเก๊า/เป็นเก๊า/โรคเก๊า"
    (
        re.compile(r"(ปวด|เป็น|โรค)\s*เก๋?า(?!ต์)"),
        r"\1เก๊า",
        "เก๋า/เกา -> เก๊า (โรคเก๊าท์)"
    ),

    # "เด็กโตกดอาการ/เด็กโตกดอากาศ" -> "Dextromethorphan (กดอาการ)"
    (
        re.compile(r"เด็กโตกด\s*(อาการ|อากาศ)"),
        r"Dextromethorphan (กดอาการ)",
        "เด็กโตกด -> Dextromethorphan"
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

    # "ได้ครบไปไหน/ได้ครบทีไหนห้าสิบมิลลิกรัม" -> "ไดโคลฟีแนค 50 มิลลิกรัม"
    (
        re.compile(r"ได้ครบ(?:ไป|ที)ไหน\s*(ห้าสิบ|50)\s*มิลลิกรัม"),
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
#  Layer 4: PHONETIC & SOUNDEX WITH LEVENSHTEIN & TRIGGER GUARD
# ─────────────────────────────────────────────────────────────

MEDICAL_ANCHORS = {
    "ทาน", "กิน", "ยา", "เม็ด", "มิลลิกรัม", "มก", "อาการ", "รักษา", "ขนาน",
    "แผง", "ขวด", "หลอด", "ฉีด", "หยอด", "พ่น", "ทา", "ซอง", "ซีซี", "มล",
    "แก้ปวด", "ฆ่าเชื้อ", "ลดไข้", "ลดน้ำมูก", "ลดกรด", "ขับลม", "เชื้อรา",
    "แก้แพ้", "แก้หวัด", "แก้ไอ", "ละลายเสมหะ", "เจ็บคอ", "พ่นคอ", "หยอดตา", "ตัวยา",
}

DISCOURSE_BOUNDARIES = {
    "หรือ", "และ", "กับ", "แต่", "ที่", "ใน", "ของ", "มี", "ไม่", "ได้",
    "เอา", "ขอ", "ไหม", "มั้ย", "ครับ", "ค่ะ", "ฮะ", "นะ", "เนาะ", "เนอะ",
    "ว่า", "เป็น", "ก็", "จะ", "ให้", "ดี",
}

# Common everyday Thai words that must never be phonetically mutated into drug names
COMMON_THAI_STOPWORDS = {
    "อาการ", "อาหาร", "ทาน", "กิน", "เม็ด", "หลอด", "ขวด", "ซอง", "แผง",
    "เวลา", "ตอนเช้า", "ตอนเย็น", "ก่อนนอน", "หลังอาหาร", "ก่อนอาหาร", "วันนี้",
    "พรุ่งนี้", "เมื่อวาน", "ปกติ", "ธรรมดา", "ทั้งหมด", "เท่าไหร่", "กี่บาท",
    "ขอบคุณ", "สวัสดี", "ผู้ป่วย", "คนไข้", "คุณหมอ", "เภสัช", "ท้องเสีย",
    "ปวดหัว", "ปวดท้อง", "ปวดฟัน", "เจ็บคอ", "น้ำมูก", "ไอแห้ง", "เสมหะ",
    "ถ่ายเหลว", "อาเจียน", "คลื่นไส้", "เวียนหัว", "หน้ามืด", "ความดัน", "เบาหวาน",
    "โรคประจำตัว", "แพ้ยา", "ไม่มี", "ไม่ใช่", "ถูกต้อง", "นิดนึง", "หน่อย",
}

_PHONETIC_INDEX: Optional[Dict[str, List[str]]] = None
_KNOWN_DRUG_WORDS: Optional[set] = None


def _char_similarity(a: str, b: str) -> float:
    """
    Computes normalized Levenshtein similarity in [0.0, 1.0] between two strings.
    """
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0

    prev = list(range(lb + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * lb
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,      # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr

    dist = prev[lb]
    return 1.0 - (dist / max(la, lb))


def _build_phonetic_lookup() -> Tuple[Dict[str, List[str]], set]:
    """
    Builds a multi-candidate soundex lookup index and known drug lexicon from the drugs catalog.
    Maps: soundex_code -> list of standard drug or brand names
    """
    if not thai_soundex:
        return {}, set()

    catalog = _load_drugs_catalog()
    lookup: Dict[str, List[str]] = {}
    known_words: set = set()

    def _add_candidate(word: str) -> None:
        word = word.strip()
        if not word:
            return
        known_words.add(word)
        if len(word) >= 3 and re.search(r"[ก-๙]", word):
            try:
                code = thai_soundex(word, engine="lk82")
                if code:
                    bucket = lookup.setdefault(code, [])
                    if word not in bucket:
                        bucket.append(word)
            except Exception:
                pass

    for _cat, items in catalog.items():
        for item in items:
            _add_candidate(item.get("thai", ""))
            gen_name = item.get("generic", "").strip()
            if gen_name:
                known_words.add(gen_name)
            for b in item.get("brands", []):
                _add_candidate(b)

    return lookup, known_words


def apply_phonetic_matching(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Scans token spans (1-6 grams) in the text. If a phonetic match is found for a drug
    in the ontology, passes the character similarity threshold (>= 0.60), is not a
    common Thai stopword, AND is guarded by a medical anchor word nearby (+/- 3 tokens),
    resolves it to the closest standard drug or brand name.
    """
    global _PHONETIC_INDEX, _KNOWN_DRUG_WORDS
    if not thai_soundex:
        return text, []

    if _PHONETIC_INDEX is None or _KNOWN_DRUG_WORDS is None:
        _PHONETIC_INDEX, _KNOWN_DRUG_WORDS = _build_phonetic_lookup()

    if not _PHONETIC_INDEX:
        return text, []

    if not any(anchor in text for anchor in MEDICAL_ANCHORS):
        return text, []

    changes: List[Dict[str, Any]] = []
    tokens = word_tokenize(text)
    n = len(tokens)
    if n == 0:
        return text, []

    new_tokens = list(tokens)
    matched_indices = set()

    for k in (6, 5, 4, 3, 2, 1):
        for i in range(n - k + 1):
            if any(idx in matched_indices for idx in range(i, i + k)):
                continue

            span_tokens = tokens[i : i + k]
            if k > 1 and any(tok in DISCOURSE_BOUNDARIES for tok in span_tokens):
                continue

            span = "".join(span_tokens).strip()
            if len(span) < 3 or span in COMMON_THAI_STOPWORDS or span in MEDICAL_ANCHORS:
                continue

            if span in _KNOWN_DRUG_WORDS:
                for j in range(i, i + k):
                    matched_indices.add(j)
                continue

            window_start = max(0, i - 3)
            window_end = min(n, i + k + 3)
            window = tokens[window_start:window_end]

            if not any(a in window for a in MEDICAL_ANCHORS):
                continue

            try:
                code = thai_soundex(span, engine="lk82")
                candidates = _PHONETIC_INDEX.get(code, [])
                if not candidates:
                    continue

                best_target = None
                best_sim = 0.0
                for cand in candidates:
                    if abs(len(span) - len(cand)) <= 3 or (0.7 <= len(span) / len(cand) <= 1.3):
                        sim = _char_similarity(span, cand)
                        if sim >= 0.60 and sim > best_sim:
                            best_sim = sim
                            best_target = cand

                if best_target and span != best_target and best_target not in text:
                    new_tokens[i] = best_target
                    for j in range(i + 1, i + k):
                        new_tokens[j] = ""
                    for j in range(i, i + k):
                        matched_indices.add(j)
                    changes.append({
                        "tier": "4-phonetic",
                        "original": span,
                        "corrected": best_target,
                        "count": 1,
                        "description": f"Phonetic Soundex ({best_sim:.0%}): {span} -> {best_target}",
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
      - Layer Custom: User Custom Dictionary (Single-Pass Regex)
      - Layer 1: Empirical Ground-Truth Mapping (Single-Pass Regex)
      - Layer 2: Categorized Pharmacy Ontology & Dosage Sig Normalizer (Single-Pass Regex)
      - Layer 3: Context-Guarded Pattern Engine (Regex Lookaround / Context Rules)
      - Layer 4: Phonetic & Soundex Matching with Levenshtein & Medical Trigger Guard

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

    # ── Layer Custom: User-defined Custom Dictionary (Single-Pass, Longest Match First) ──
    if apply_custom:
        custom_dict = load_custom_dict()
        corrected, cust_changes = _apply_single_pass_dict(
            corrected,
            custom_dict,
            tier="custom",
            default_desc="คำศัพท์กำหนดเองโดยผู้ใช้",
        )
        changes.extend(cust_changes)

    # ── Layer 1: Empirical Ground-Truth Mapping (Single-Pass, Longest Match First) ──
    if apply_safe:
        corrected, safe_changes = _apply_single_pass_dict(
            corrected,
            SAFE_DRUG_NAMES,
            tier="1-safe",
            default_desc="ชื่อยา/คำทางการแพทย์ที่ถอดเสียงผิด",
        )
        changes.extend(safe_changes)

    # ── Layer 2: Categorized Pharmacy Ontology & Dosage Sig Normalizer ──
    if apply_ontology:
        corrected, ont_changes = _apply_single_pass_dict(
            corrected,
            ONTOLOGY_SIG_MAP,
            tier="2-ontology",
            default_desc="หน่วยยา/วิธีบริหารยาจากคลังข้อมูลเภสัชกรรม",
        )
        changes.extend(ont_changes)

    # ── Layer 3: Context-Guarded Regex Patterns ──
    if apply_regex:
        for pattern, replacement, description in REGEX_PATTERNS:
            matches = list(pattern.finditer(corrected))
            if matches:
                count = len(matches)
                corrected = pattern.sub(replacement, corrected)
                display_orig = matches[0].group(0)
                display_corr = replacement if isinstance(replacement, str) else ""
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

    # ── Layer 4: Phonetic & Soundex Matching with Levenshtein & Medical Trigger Guard ──
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
    total = 0
    by_tier: Counter = Counter()
    correction_freq: Counter = Counter()

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
