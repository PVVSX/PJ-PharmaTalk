"""
Pharmacy Dictionary -- Post-processing module for STT transcript correction.

วิเคราะห์จากผลทดสอบ 47 ไฟล์เสียง พบคำผิดซ้ำจาก Typhoon ASR
แบ่งเป็น 3 ระดับ:
  - Tier 1 (SAFE): แทนได้ทันทีไม่มี false positive
  - Tier 2 (REGEX): ต้องใช้ pattern matching เพื่อป้องกัน false positive
  - Tier 3 (LLM): ต้องใช้ LLM (ไม่ได้ทำใน module นี้ -- ทำใน step ถัดไป)

Usage:
    from unified_app.modules.pharmacy_dict import correct_transcript, get_stats

    raw = "ค่าเชื้อตัวหนึ่งครับ ทานหนึ่งเมตรเช้าเย็น หกร้อยมิติกรรม"
    corrected, changes = correct_transcript(raw)
    # corrected = "ฆ่าเชื้อตัวหนึ่งครับ ทานหนึ่งเม็ดเช้าเย็น หกร้อยมิลลิกรัม"
"""

import re
from typing import Tuple, List, Dict

# ─────────────────────────────────────────────────────────────
#  Tier 1: SAFE REPLACEMENTS
#  ไม่มีคำเหล่านี้ในภาษาไทยปกติ แทนได้เลยไม่มีความเสี่ยง
# ─────────────────────────────────────────────────────────────

SAFE_DRUG_NAMES: Dict[str, str] = {
    # ── ชื่อยาสากล (Generic names) ──
    "Setifisine":           "Cetirizine",
    "อม็อกซี่คือดิน":        "Amoxicillin-Clavulanate",
    "อมซี่คอมโมโดนิก":      "Amoxicillin-Clavulanic",
    "อัมซี่ลิน":            "Amoxicillin",
    "โคชีซีน":              "Colchicine",
    "โคซีม":               "Colchicine",
    "ไซโปเคเตอร์":         "Cyproheptadine",
    "ไซโปรเฮปทาดีน":       "Cyproheptadine",
    "ไฮด็อกซิก":           "Hydroxyzine",
    "เมโทนี่นาโซ":         "Metronidazole",
    "คาโบฟิตเตอร์อีน":     "Carbocisteine",
    "รีโวเซน":             "Levocetirizine",
    "เด็กโตเมอร์":         "Dextromethorphan",
    "อีโดลิค":             "Etodolac",
    "อีโตลิค":             "Etodolac",

    # ── คำทางการแพทย์ที่ไม่มีในภาษาไทย ──
    "ค่าเชื้อ":            "ฆ่าเชื้อ",
    "มิติกรรม":            "มิลลิกรัม",
}

# ─────────────────────────────────────────────────────────────
#  Tier 2: REGEX-BASED CONTEXT-AWARE REPLACEMENTS
#  ต้องใช้ pattern เพื่อป้องกัน false positive
# ─────────────────────────────────────────────────────────────

# Each tuple: (compiled_regex, replacement, description)
REGEX_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # "หนึ่งเมตร/สองเมตร" -> "หนึ่งเม็ด/สองเม็ด"
    # ไม่แทน "มิลลิเมตร" (negative lookbehind)
    (
        re.compile(r"(?<!มิลลิ)(หนึ่ง|สอง|สาม|ครึ่ง)เมตร"),
        r"\1เม็ด",
        "เมตร -> เม็ด (จำนวนยา)"
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
        re.compile(r"รถน้[ํำ]ามูก"),
        "ลดน้ำมูก",
        "รถน้ำมูก -> ลดน้ำมูก"
    ),

    # "เด็กโตกดอาการ/เด็กโตกดอากาศ" -> "Dextromethorphan" (กดอาการไอ)
    (
        re.compile(r"เด็กโตกด(อาการ|อากาศ)"),
        r"Dextromethorphan (กดอาการ)",
        "เด็กโตกด -> Dextromethorphan"
    ),

    # "ห้าร้อยมิลลิเมตร" -> "ห้าร้อยมิลลิกรัม" (ในบริบทยา)
    (
        re.compile(r"มิลลิเมตร"),
        "มิลลิกรัม",
        "มิลลิเมตร -> มิลลิกรัม (หน่วยยา)"
    ),

    # "ห้ามรอมิติกรรม" -> "ห้าร้อยมิลลิกรัม"
    (
        re.compile(r"ห้ามรอมิติกรรม"),
        "ห้าร้อยมิลลิกรัม",
        "ห้ามรอมิติกรรม -> ห้าร้อยมิลลิกรัม"
    ),

    # "ห้ามมิติกรรม" -> "ห้ามิลลิกรัม" (25mg, 50mg patterns)
    (
        re.compile(r"ห้ามมิติกรรม"),
        "ห้ามิลลิกรัม",
        "ห้ามมิติกรรม -> ห้ามิลลิกรัม"
    ),
]


# ─────────────────────────────────────────────────────────────
#  Core API
# ─────────────────────────────────────────────────────────────

def correct_transcript(
    text: str,
    apply_safe: bool = True,
    apply_regex: bool = True,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    แก้คำผิดใน transcript จาก STT โดยใช้คลังคำศัพท์เภสัชกรรม

    Args:
        text:        ข้อความ transcript ดิบจาก STT
        apply_safe:  ใช้ Tier 1 (safe replacements) หรือไม่
        apply_regex: ใช้ Tier 2 (regex patterns) หรือไม่

    Returns:
        (corrected_text, changes) โดย changes เป็น list ของ dict ที่บอกว่าแก้อะไรบ้าง
        แต่ละ dict มี keys: tier, original, corrected, description
    """
    if not text or not text.strip():
        return text, []

    corrected = text
    changes: List[Dict[str, str]] = []

    # ── Tier 1: Safe replacements ──
    if apply_safe:
        for wrong, right in SAFE_DRUG_NAMES.items():
            if wrong in corrected:
                count = corrected.count(wrong)
                corrected = corrected.replace(wrong, right)
                changes.append({
                    "tier": "1-safe",
                    "original": wrong,
                    "corrected": right,
                    "count": count,
                    "description": f"ชื่อยา/คำทางการแพทย์ที่ถอดเสียงผิด",
                })

    # ── Tier 2: Regex patterns ──
    if apply_regex:
        for pattern, replacement, description in REGEX_PATTERNS:
            matches = pattern.findall(corrected)
            if matches:
                count = len(matches)
                corrected = pattern.sub(replacement, corrected)
                changes.append({
                    "tier": "2-regex",
                    "original": pattern.pattern,
                    "corrected": replacement,
                    "count": count,
                    "description": description,
                })

    return corrected, changes


def get_stats(changes_list: List[List[Dict[str, str]]]) -> Dict:
    """
    รวม stats จาก changes หลาย ๆ ไฟล์เข้าด้วยกัน

    Args:
        changes_list: list ของ changes (output จาก correct_transcript หลายครั้ง)

    Returns:
        dict ที่มี:
          total_corrections: จำนวนการแก้ไขทั้งหมด
          by_tier: จำนวนแยกตาม tier
          top_corrections: top 10 คำที่แก้บ่อยสุด
    """
    from collections import Counter

    total = 0
    by_tier = Counter()
    correction_freq = Counter()

    for changes in changes_list:
        for change in changes:
            count = change.get("count", 1)
            total += count
            by_tier[change["tier"]] += count
            key = f'{change["original"]} -> {change["corrected"]}'
            correction_freq[key] += count

    return {
        "total_corrections": total,
        "by_tier": dict(by_tier),
        "top_corrections": correction_freq.most_common(10),
    }


# ─────────────────────────────────────────────────────────────
#  ข้อมูลเพิ่มเติมสำหรับ LLM Post-Processing (Tier 3)
#  ส่ง context นี้ให้ LLM เพื่อช่วยแก้คำที่ Dictionary แก้ไม่ได้
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

กรุณาแก้ไขเฉพาะชื่อยาและคำทางการแพทย์ที่ผิดเท่านั้น ห้ามเปลี่ยนเนื้อหาอื่น
ตอบเฉพาะบทสนทนาที่แก้ไขแล้ว ไม่ต้องอธิบาย

บทสนทนา:
{transcript}"""


# ─────────────────────────────────────────────────────────────
#  Quick self-test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        "ค่าเชื้อตัวหนึ่งครับ ทานหนึ่งเมตรเช้าเย็น หกร้อยมิติกรรม",
        "เป็นยารถไข้รถกดรถน้ํามูก",
        "จะเป็น Setifisine ไปเนาะ แบบไม่ง่วง",
        "อม็อกซี่คือดินมาเป็นยาฆ่าเชื้อ ไอโบเฟนหกร้อยมิติกรรม",
        "ไฮด็อกซิกห้ามมิติกรรม",
        "เป็นโคชีซีนไปนะ ทานสองเมตรทันที",
        "Facebook ทรัพย์สินห้ามรอมิติกรรมเช้าเย็น",
    ]

    print("=" * 60)
    print("Pharmacy Dictionary -- Self-Test")
    print("=" * 60)

    all_changes = []
    for i, test in enumerate(test_cases, 1):
        corrected, changes = correct_transcript(test)
        all_changes.append(changes)
        print(f"\n[Test {i}]")
        print(f"  Input:     {test}")
        print(f"  Corrected: {corrected}")
        if changes:
            for c in changes:
                print(f"  - [{c['tier']}] \"{c['original']}\" -> \"{c['corrected']}\" (x{c['count']})")

    print("\n" + "=" * 60)
    stats = get_stats(all_changes)
    print(f"Total corrections: {stats['total_corrections']}")
    print(f"By tier: {stats['by_tier']}")
    print("Top corrections:")
    for correction, count in stats["top_corrections"]:
        print(f"  {correction}: {count}x")
""" # noqa: E501
"""
