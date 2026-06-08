# -*- coding: utf-8 -*-
from __future__ import annotations

# บันทึกผล classify ลง text_classified/result/*.csv
import csv
from pathlib import Path

RESULT_FIELDNAMES = [
    "ชื่อไฟล์",
    "เวลาที่ใช้ (วินาที)",
    "ประเภท",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]

# ค่าที่อนุญาตในคอลัมน์ ประเภท (วัตถุประสงค์การมา)
VISIT_PURPOSE_CANONICAL = frozenset({"ปรึกษา", "ซื้อยา", "ทั้งคู่"})


def result_csv_path(base: Path) -> Path:
    return (base / "result" / "result.csv").resolve()


def gemini_extract_csv_path(base: Path) -> Path:
    return (base / "result" / "gemini_extract.csv").resolve()


def model_extract_csv_path(base: Path) -> Path:
    return (base / "result" / "model_extract.csv").resolve()


def compact_csv_cell_text(s: str) -> str:
    """บีบ newline และช่องว่างซ้ำในเซลล์ให้เหลือบรรทัดเดียว — กัน CSV ทะลุหลายบรรทัดเวลาเปิดใน Excel/สคริปต์"""
    t = (s or "").strip()
    if not t:
        return "-"
    t = " ".join(t.split())
    return t if t else "-"


def normalize_visit_purpose_cell(s: str) -> str:
    """คืนค่า ปรึกษา / ซื้อยา / ทั้งคู่ หรือ '-' ถ้าไม่ชัดหรือไม่ตรงชุดที่อนุญาต"""
    t = compact_csv_cell_text(s)
    if t == "-" or not t:
        return "-"
    if t in VISIT_PURPOSE_CANONICAL:
        return t
    return "-"


def existing_result_filenames(csv_path: Path) -> set[str]:
    """ชื่อไฟล์ที่มีแถวใน CSV แล้ว (คอลัมน์ ชื่อไฟล์)"""
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        return set()
    names: set[str] = set()
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not row:
                continue
            fn = (row.get("ชื่อไฟล์") or "").strip()
            if fn:
                names.add(fn)
    return names


def _normalize_row(d: dict) -> dict:
    fn = (d.get("ชื่อไฟล์") or "").strip()
    elapsed_s = compact_csv_cell_text(d.get("เวลาที่ใช้ (วินาที)") or "-")
    return {
        "ชื่อไฟล์": fn,
        "เวลาที่ใช้ (วินาที)": elapsed_s,
        "ประเภท": normalize_visit_purpose_cell(d.get("ประเภท") or "-"),
        "ประวัติการแพ้ยา": compact_csv_cell_text(d.get("ประวัติการแพ้ยา") or "-"),
        "โรคประจำตัว": compact_csv_cell_text(d.get("โรคประจำตัว") or "-"),
        "ประวัติการจ่ายยา": compact_csv_cell_text(d.get("ประวัติการจ่ายยา") or "-"),
        "บันทึกทางการแพทย์": compact_csv_cell_text(d.get("บันทึกทางการแพทย์") or "-"),
        "คำแนะนำจากเภสัช": compact_csv_cell_text(d.get("คำแนะนำจากเภสัช") or "-"),
    }


def upsert_result_csv(csv_path: Path, new_rows: list[dict]) -> None:
    """อ่าน CSV เดิม (ถ้ามี) แล้วอัปเดต/เพิ่มแถวตามชื่อไฟล์ เรียงชื่อไฟล์"""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict] = {}
    if csv_path.exists():
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if not row:
                    continue
                fn = (row.get("ชื่อไฟล์") or "").strip()
                if fn:
                    merged[fn] = _normalize_row(row)
    for r in new_rows:
        r2 = _normalize_row(r)
        if r2["ชื่อไฟล์"]:
            merged[r2["ชื่อไฟล์"]] = r2
    rows_out = [merged[k] for k in sorted(merged.keys())]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)
