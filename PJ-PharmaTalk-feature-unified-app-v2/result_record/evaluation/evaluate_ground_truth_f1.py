# -*- coding: utf-8 -*-
"""
เปรียบเทียบผลสกัด Gemini กับ Ground Truth (Grount_truth.xlsx)
โดยคำนวณ F1 แบบ token overlap (แนวคิดคลาย NER: แบ่งหน่วยความหมายด้วย token / span)

แมปคอลัมน์ GT → CSV:
  ประเภท → ประเภท (ป้ายกำหนดการมา — multi-label F1)
  อาการ → บันทึกทางการแพทย์
  ประวัติการแพ้ยา → ประวัติการแพ้ยา
  โรคประจำตัว → โรคประจำตัว
  ประวัติการรับยา → ประวัติการจ่ายยา
  ข้อมูลการจ่ายยา (จากเภสัชกร) → คำแนะนำจากเภสัช

ผลลัพธ์: report/evaluation/*.png และ f1_metrics.json

รายงานสองแบบ: (1) นับทุกแถวใน GT — แถวที่ไม่มีไฟล์ใน CSV จะกลายเป็น FN
(2) เฉพาะแถวที่มีทั้งใน speech และ text CSV — เปรียบเทียบคุณภาพบนเคสเดียวกัน

ทำไม tok / span F1 ถึงเป็น 0 ได้บ่อย:
- GT (เช่น อาการ) เป็นคีย์เวิร์ดสั้น ส่วนผล Gemini เป็นยาว — token ต้องตรงกันทุกตัวจึงได้คะแนน
- span-F1 เทียบเฉพาะ “ก้อนที่ตัดด้วย comma” ว่าตรงทั้งสตริง — ข้อความยาวจึงไม่ชนกับ GT สั้น
- เสริมเมตริก chk = สัดส่วนชิ้นคำจาก GT (คั่นด้วย comma) ที่พบเป็นคำย่อยในข้อความ pred

NER (ระดับเอนทิตี): แบ่งชิ้นด้วย comma/วรรคตอน → เปรียบเป็น **ชุด** (exact match หลัง normalize) แล้วคิด micro P/R/F1

Gemini boundary judge (ทางเลือก): `python evaluate_ground_truth_f1.py --gemini-judge [--gemini-judge-max N] [--gemini-judge-both-only]`
ถามโมเดลว่าผลสกัดอยู่ใน boundary ของ GT หรือไม่ → ได้คะแนน/coverage (ใช้โควตา API)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
GT_XLSX = BASE / "report" / "Grount_truth.xlsx"
SPEECH_CSV = BASE / "report" / "speech_to_form" / "speech_gemini_extract.csv"
TEXT_CSV = BASE / "report" / "text_to_form" / "text_gemini_extract.csv"
OUT_DIR = BASE / "report" / "evaluation"

# คอลัมน์ใน xlsx (0-based): row ข้อมูลเริ่มแถวที่ 4 ในไฟล์
GT_COL_AUDIO = 1
GT_COL_TYPE = 12
GT_COL_SYMPTOM = 5  # อาการ
GT_COL_ALLERGY = 6
GT_COL_DISEASE = 7
GT_COL_RX_HIST = 8
GT_COL_PHARM = 9

CSV_FIELDS = {
    "ประเภท": "ประเภท",
    "อาการ": "บันทึกทางการแพทย์",
    "ประวัติการแพ้ยา": "ประวัติการแพ้ยา",
    "โรคประจำตัว": "โรคประจำตัว",
    "ประวัติการรับยา": "ประวัติการจ่ายยา",
    "ข้อมูลการจ่ายยา": "คำแนะนำจากเภสัช",
}


def normalize_filename_key(name: str | None) -> str:
    if not name:
        return ""
    s = str(name).strip().lower().rstrip(".")
    if s.endswith(".txt") or s.endswith(".wav"):
        s = Path(s).stem
    if s.startswith("recording_"):
        s = s[len("recording_") :]
    return s


def strip_bom(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        return {}
    return {((n or "").lstrip("\ufeff")): n for n in fieldnames}


def load_csv_by_key(path: Path) -> dict[str, dict[str, str]]:
    by_key: dict[str, dict[str, str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        remap = strip_bom(reader.fieldnames)
        for row in reader:
            raw_name = row.get(remap.get("ชื่อไฟล์", "ชื่อไฟล์"), "")
            k = normalize_filename_key(raw_name)
            if not k:
                continue
            fixed = {(remap.get(a, a)): (row.get(a) or "") for a in row}
            by_key[k] = fixed
    return by_key


def load_ground_truth() -> list[dict[str, str]]:
    try:
        import openpyxl
    except ImportError as e:
        raise SystemExit("ติดตั้ง openpyxl: python -m pip install openpyxl") from e

    wb = openpyxl.load_workbook(GT_XLSX, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    wb.close()

    out: list[dict[str, str]] = []
    for row in rows:
        audio = row[GT_COL_AUDIO]
        if audio is None or str(audio).strip() == "":
            continue
        key = normalize_filename_key(str(audio))
        out.append(
            {
                "key": key,
                "ประเภท": _cell(row, GT_COL_TYPE),
                "อาการ": _cell(row, GT_COL_SYMPTOM),
                "ประวัติการแพ้ยา": _cell(row, GT_COL_ALLERGY),
                "โรคประจำตัว": _cell(row, GT_COL_DISEASE),
                "ประวัติการรับยา": _cell(row, GT_COL_RX_HIST),
                "ข้อมูลการจ่ายยา": _cell(row, GT_COL_PHARM),
            }
        )
    return out


def _cell(row: tuple, idx: int) -> str:
    if idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    return str(v).strip()


def normalize_text(s: str) -> str:
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def is_empty_value(s: str) -> bool:
    """เฉพาะตัวบ่งชี้ว่าไม่มีข้อมูลในเซลล์ — ไม่ถือว่า 'ไม่มี' (เชิงความหมาย) เป็นค่าว่าง"""
    t = normalize_text(s)
    return t in ("", "-", "–", "—")


def tokenize_ner_like(s: str) -> Counter[str]:
    """แบ่ง token สำหรับ F1 แบบ multiset (ช่องว่าง + เครื่องหมายวรรคตอน)"""
    t = normalize_text(s).lower()
    if not t or is_empty_value(t):
        return Counter()
    # คงอักษรไทย/อังกฤษ/ตัวเลข เป็นชิ้น; แยกตาม comma/semicolon
    parts = re.split(r"[,，;|•·]+", t)
    tokens: Counter[str] = Counter()
    for part in parts:
        for w in re.split(r"\s+", part.strip()):
            if len(w) < 2 and not w.isdigit():
                continue
            if w:
                tokens[w] += 1
    return tokens


def spans_from_commas(s: str) -> frozenset[str]:
    """แนวคิด span เหมือนเอนทิตีจากตัวคั่น (คลาย chunk NER)"""
    t = normalize_text(s)
    if not t or is_empty_value(t):
        return frozenset()
    chunks = re.split(r"[,，;\\n]+", t)
    out = []
    for c in chunks:
        c = c.strip()
        if len(c) >= 2 and not is_empty_value(c):
            out.append(c.lower())
    return frozenset(out)


def extract_ner_entity_set(text: str) -> set[str]:
    """
    แบ่งชิ้นเหมือน mention ใน NER (comma / semicolon) → ชุดสตริงเปรียบเทียบแบบ exact หลัง normalize
    """
    t = normalize_text(text)
    if not t or is_empty_value(t):
        return set()
    out: set[str] = set()
    for part in re.split(r"[,，;|•·]+", t):
        p = part.strip()
        if len(p) >= 2 and not is_empty_value(p):
            out.add(p.lower())
    return out


def comma_chunk_substring_recall(gt_text: str, pred_text: str) -> float | None:
    """
    คะแนน 0–1 ต่อแถว: ชิ้นที่ตัดจาก GT (comma) มีกี่ส่วนที่ปรากฏในข้อความ pred ทั้งสตริง
    (ช่วยเมื่อ GT สั้นและ pred ยาว — tok/span เข้มงวดมักได้ 0)
    """
    if is_empty_value(gt_text):
        return None
    pred_n = normalize_text(pred_text)
    pred_lower = pred_n.lower()
    if not pred_lower.strip():
        return 0.0

    gt_norm = normalize_text(gt_text)
    pieces = [p.strip() for p in re.split(r"[,，;\n]+", gt_norm) if p.strip()]
    if not pieces:
        pieces = [gt_norm.strip()]
    hits: list[float] = []
    for p in pieces:
        if len(p) < 2 and not any(ch.isdigit() for ch in p):
            continue
        if normalize_text(p).lower() in pred_lower:
            hits.append(1.0)
        else:
            hits.append(0.0)
    if not hits:
        return None
    return sum(hits) / len(hits)


def visit_labels_from_gt(s: str) -> frozenset[str]:
    if not s or is_empty_value(s):
        return frozenset()
    labels: set[str] = set()
    for part in re.split(r"[,，]", str(s)):
        p = part.strip()
        if not p:
            continue
        if "ทั้งคู่" in p:
            labels.update(("ซื้อยา", "ปรึกษา"))
            continue
        if "มาซื้อ" in p or p == "ซื้อยา":
            labels.add("ซื้อยา")
        elif "ปรึกษา" in p:
            labels.add("ปรึกษา")
    return frozenset(labels)


def visit_labels_from_csv(s: str) -> frozenset[str]:
    if not s or is_empty_value(s):
        return frozenset()
    t = normalize_text(str(s))
    if "ทั้งคู่" in t:
        return frozenset({"ซื้อยา", "ปรึกษา"})
    labels: set[str] = set()
    if "ซื้อยา" in t and "ปรึกษา" in t:
        return frozenset({"ซื้อยา", "ปรึกษา"})
    if "ซื้อ" in t:
        labels.add("ซื้อยา")
    if "ปรึกษา" in t:
        labels.add("ปรึกษา")
    return frozenset(labels)


def multilabel_micro_f1(pred: frozenset[str], gold: frozenset[str]) -> float:
    if not gold and not pred:
        return 1.0
    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def evaluate_pairs(
    gt_rows: list[dict[str, str]],
    pred_by_key: dict[str, dict[str, str]],
    label: str,
) -> dict[str, float]:
    token_tp = token_fp = token_fn = 0
    span_tp = span_fp = span_fn = 0
    ent_tp = ent_fp = ent_fn = 0
    visit_scores: list[float] = []
    chunk_recalls: list[float] = []
    n_missing = 0

    for row in gt_rows:
        k = row["key"]
        if label == "ประเภท":
            if k not in pred_by_key:
                visit_scores.append(0.0)
                n_missing += 1
                continue
            pr = pred_by_key[k]
            g = visit_labels_from_gt(row["ประเภท"])
            p = visit_labels_from_csv(pr.get("ประเภท", ""))
            visit_scores.append(multilabel_micro_f1(p, g))
            continue

        gt_col = label
        csv_col = CSV_FIELDS[label]
        gt_text = row.get(gt_col, "")

        if k not in pred_by_key:
            n_missing += 1
            tg = tokenize_ner_like(gt_text)
            token_fn += sum(tg.values())
            sg = spans_from_commas(gt_text)
            span_fn += len(sg)
            ent_fn += len(extract_ner_entity_set(gt_text))
            if not is_empty_value(gt_text):
                chunk_recalls.append(0.0)
            continue

        pr = pred_by_key[k]
        pd_text = pr.get(csv_col, "")

        if is_empty_value(gt_text) and is_empty_value(pd_text):
            continue

        ges = extract_ner_entity_set(gt_text)
        pes = extract_ner_entity_set(pd_text)
        ent_tp += len(ges & pes)
        ent_fp += len(pes - ges)
        ent_fn += len(ges - pes)

        sub = comma_chunk_substring_recall(gt_text, pd_text)
        if sub is not None:
            chunk_recalls.append(sub)

        tg = tokenize_ner_like(gt_text)
        tp = tokenize_ner_like(pd_text)
        for t in set(tg) | set(tp):
            gv, pv = tg.get(t, 0), tp.get(t, 0)
            token_tp += min(gv, pv)
            token_fp += max(0, pv - gv)
            token_fn += max(0, gv - pv)

        sg = spans_from_commas(gt_text)
        sp = spans_from_commas(pd_text)
        span_tp += len(sg & sp)
        span_fp += len(sp - sg)
        span_fn += len(sg - sp)

    if label == "ประเภท":
        return {
            "f1_macro": sum(visit_scores) / len(visit_scores) if visit_scores else 0.0,
            "n_pairs": len(visit_scores),
            "n_missing_pred": n_missing,
        }

    # micro F1 tokens
    if token_tp == 0 and token_fp == 0 and token_fn == 0:
        f1_t = p_t = r_t = 1.0
    else:
        p_t = token_tp / (token_tp + token_fp) if (token_tp + token_fp) else 0.0
        r_t = token_tp / (token_tp + token_fn) if (token_tp + token_fn) else 0.0
        f1_t = 2 * p_t * r_t / (p_t + r_t) if (p_t + r_t) else 0.0

    if span_tp == 0 and span_fp == 0 and span_fn == 0:
        f1_s = p_s = r_s = 1.0
    else:
        p_s = span_tp / (span_tp + span_fp) if (span_tp + span_fp) else 0.0
        r_s = span_tp / (span_tp + span_fn) if (span_tp + span_fn) else 0.0
        f1_s = 2 * p_s * r_s / (p_s + r_s) if (p_s + r_s) else 0.0

    chk = (
        sum(chunk_recalls) / len(chunk_recalls) if chunk_recalls else 0.0
    )

    if ent_tp == 0 and ent_fp == 0 and ent_fn == 0:
        f1_e = p_e = r_e = 1.0
    else:
        p_e = ent_tp / (ent_tp + ent_fp) if (ent_tp + ent_fp) else 0.0
        r_e = ent_tp / (ent_tp + ent_fn) if (ent_tp + ent_fn) else 0.0
        f1_e = 2 * p_e * r_e / (p_e + r_e) if (p_e + r_e) else 0.0

    return {
        "f1_token_micro": f1_t,
        "f1_span_micro": f1_s,
        "precision_token": p_t,
        "recall_token": r_t,
        "precision_span": p_s,
        "recall_span": r_s,
        "ner_entity_f1_micro": f1_e,
        "ner_entity_precision": p_e,
        "ner_entity_recall": r_e,
        "substring_chunk_recall_macro": chk,
        "n_rows_substring_recall": len(chunk_recalls),
        "n_pairs": len(gt_rows),
        "n_missing_pred": n_missing,
    }


def _matplotlib_thai_font() -> None:
    import matplotlib

    matplotlib.use("Agg")
    # Windows มักมี Tahoma รองรับไทย
    matplotlib.rcParams["font.sans-serif"] = ["Tahoma", "Segoe UI", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False


def plot_comparison(
    fields: list[str],
    speech_metrics: dict[str, dict[str, float]],
    text_metrics: dict[str, dict[str, float]],
    out_path: Path,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:
        raise SystemExit("ติดตั้ง matplotlib: python -m pip install matplotlib") from e

    _matplotlib_thai_font()

    x = range(len(fields))
    w = 0.35
    tok_sp = [
        speech_metrics[f].get("f1_token_micro", speech_metrics[f].get("f1_macro", 0))
        for f in fields
    ]
    tok_tx = [
        text_metrics[f].get("f1_token_micro", text_metrics[f].get("f1_macro", 0))
        for f in fields
    ]

    fields_span = [f for f in fields if f != "ประเภท"]
    xs = range(len(fields_span))
    span_sp = [speech_metrics[f].get("f1_span_micro", 0) for f in fields_span]
    span_tx = [text_metrics[f].get("f1_span_micro", 0) for f in fields_span]

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=False)

    ax1 = axes[0]
    ax1.bar([i - w / 2 for i in x], tok_sp, width=w, label="speech → form (token / type-F1)")
    ax1.bar([i + w / 2 for i in x], tok_tx, width=w, label="text → form (token / type-F1)")
    ax1.set_ylabel("F1")
    ax1.set_title("เปรียบเทียบ F1 กับ Grount_truth.xlsx (token overlap / ประเภท = multi-label F1)")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(fields, rotation=22, ha="right")
    ax1.legend()
    ax1.set_ylim(0, 1.05)
    ax1.grid(axis="y", alpha=0.3)

    ax2 = axes[1]
    ax2.bar([i - w / 2 for i in xs], span_sp, width=w, label="speech (span / comma-NER)")
    ax2.bar([i + w / 2 for i in xs], span_tx, width=w, label="text (span / comma-NER)")
    ax2.set_ylabel("F1")
    ax2.set_xlabel("ช่องข้อมูล")
    ax2.set_title("F1 แบบ span (ตัดด้วย comma — ไม่รวมประเภท)")
    ax2.set_xticks(list(xs))
    ax2.set_xticklabels(fields_span, rotation=22, ha="right")
    ax2.legend()
    ax2.set_ylim(0, 1.05)
    ax2.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_delta(fields: list[str], speech_m: dict, text_m: dict, out_path: Path) -> None:
    import matplotlib.pyplot as plt

    _matplotlib_thai_font()

    deltas_tok = [
        text_m[f].get("f1_token_micro", text_m[f].get("f1_macro", 0))
        - speech_m[f].get("f1_token_micro", speech_m[f].get("f1_macro", 0))
        for f in fields
    ]
    deltas_sp = [
        text_m[f].get("f1_span_micro", 0) - speech_m[f].get("f1_span_micro", 0)
        for f in fields
    ]

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(fields))
    w = 0.35
    ax.bar([i - w / 2 for i in x], deltas_tok, width=w, label="Δ token F1 (text − speech)")
    ax.bar([i + w / 2 for i in x], deltas_sp, width=w, label="Δ span F1 (text − speech)")
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(fields, rotation=22, ha="right")
    ax.set_ylabel("ความต่าง F1")
    ax.set_title("ความต่างระหว่าง text→form กับ speech→form (บวก = text ดีกว่า)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _filter_gt(gt: list[dict[str, str]], keys: set[str]) -> list[dict[str, str]]:
    return [r for r in gt if r["key"] in keys]


BOUNDARY_JUDGE_SYSTEM = """คุณเป็นกรรมการประเมินผลการสกัดข้อความในบริบทเภสัชกรรม
ให้ตอบเป็น JSON เท่านั้น ไม่มี markdown ไม่มีข้อความอื่นนอกวงเล็บปีกกา"""


def _parse_json_loose(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        o = json.loads(raw)
        return o if isinstance(o, dict) else {}
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            o = json.loads(m.group(0))
            return o if isinstance(o, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def gemini_boundary_judge_call(gt_text: str, pred_text: str, field_label: str) -> dict:
    """ถาม Gemini ว่า prediction อยู่ใน semantic boundary ของ GT หรือไม่"""
    try:
        from classify_gemini_extract import call_gemini
    except ImportError as e:
        raise SystemExit(
            "ต้องมี classify_gemini_extract.py และแพ็กเกจ google-generativeai"
        ) from e

    user = (
        f"ชื่อช่อง: {field_label}\n\n"
        f"Ground truth (ขอบเขตอ้างอิง — อาจสั้นมาก):\n{(gt_text or '').strip() or '(ว่าง)'}\n\n"
        f"ผลสกัดจากระบบ (Prediction — อาจยาว):\n{(pred_text or '').strip() or '(ว่าง)'}\n\n"
        "ตอบ JSON เท่านั้น รูปแบบนี้:\n"
        '{"within_gt_boundary": true หรือ false, '
        '"coverage_gt_0_1": ตัวเลขระหว่าง 0 กับ 1, '
        '"contradiction_or_off_topic": true หรือ false, '
        '"score_0_100": จำนวนเต็ม 0 ถึง 100}\n\n'
        "ความหมาย within_gt_boundary: เนื้อหาใน Prediction ไม่ขัดแย้ง GT และอยู่ในประเด็นเดียวกัน "
        "(การขยายจาก GT สั้นไปข้อความยาวที่สอดคล้องถือว่าอยู่ใน boundary)\n"
        "coverage_gt_0_1: ประเด็นสำคัญจาก GT ถูกสะท้อนใน Prediction แค่ไหน\n"
        "contradiction_or_off_topic: true ถ้ามีข้อมูลขัดแย้งชัดหรือหลุดประเด็นหลักของ GT"
    )
    raw = call_gemini(BOUNDARY_JUDGE_SYSTEM, user, temperature=0.05)
    return _parse_json_loose(raw)


def run_gemini_boundary_judge(
    gt_rows: list[dict[str, str]],
    speech: dict[str, dict[str, str]],
    text: dict[str, dict[str, str]],
    *,
    max_calls: int,
    pause_sec: float,
) -> tuple[list[dict], dict[str, float]]:
    """คืน (รายการผลแต่ละครั้ง, สรุปค่าเฉลี่ยตามแหล่ง speech/text)"""
    entity_fields = [f for f in CSV_FIELDS if f != "ประเภท"]
    tasks: list[tuple[str, str, str, str, str]] = []
    for row in gt_rows:
        k = row["key"]
        for label in entity_fields:
            csv_col = CSV_FIELDS[label]
            gt_t = row.get(label, "")
            for src_name, pmap in (("speech", speech), ("text", text)):
                if k not in pmap:
                    continue
                pd_t = pmap[k].get(csv_col, "")
                if is_empty_value(gt_t) and is_empty_value(pd_t):
                    continue
                tasks.append((k, label, src_name, gt_t, pd_t))

    results: list[dict] = []
    summary: dict[str, list[float]] = {"speech_scores": [], "text_scores": [], "speech_within": [], "text_within": []}

    for idx, (k, label, src_name, gt_t, pd_t) in enumerate(tasks):
        if len(results) >= max_calls:
            break
        print(
            f"[Gemini boundary judge {len(results) + 1}/{max_calls}] {k} | {label} | {src_name}",
            flush=True,
        )
        try:
            j = gemini_boundary_judge_call(gt_t, pd_t, label)
        except Exception as e:
            j = {"error": str(e)}
        row_out = {
            "key": k,
            "field": label,
            "source": src_name,
            "gemini": j,
        }
        results.append(row_out)
        sc = j.get("score_0_100")
        if isinstance(sc, (int, float)):
            key_s = f"{src_name}_scores"
            if key_s in summary:
                summary[key_s].append(float(sc))
        wb = j.get("within_gt_boundary")
        if isinstance(wb, bool):
            key_w = f"{src_name}_within"
            if key_w in summary:
                summary[key_w].append(1.0 if wb else 0.0)
        time.sleep(pause_sec)

    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    agg = {
        "speech_avg_score": _mean(summary["speech_scores"]),
        "text_avg_score": _mean(summary["text_scores"]),
        "speech_within_rate": _mean(summary["speech_within"]),
        "text_within_rate": _mean(summary["text_within"]),
        "n_api_calls": len(results),
    }
    return results, agg


def _argv_int(flag: str, default: int) -> int:
    if flag not in sys.argv:
        return default
    try:
        i = sys.argv.index(flag)
        return int(sys.argv[i + 1])
    except (ValueError, IndexError):
        return default


def main() -> None:
    if not GT_XLSX.is_file():
        raise SystemExit(f"ไม่พบไฟล์ ground truth: {GT_XLSX}")

    gt = load_ground_truth()
    speech = load_csv_by_key(SPEECH_CSV)
    text = load_csv_by_key(TEXT_CSV)

    fields = list(CSV_FIELDS.keys())
    gt_keys = {r["key"] for r in gt}
    keys_speech = gt_keys & set(speech)
    keys_text = gt_keys & set(text)
    keys_both = keys_speech & keys_text

    speech_metrics: dict[str, dict[str, float]] = {}
    text_metrics: dict[str, dict[str, float]] = {}
    speech_metrics_both: dict[str, dict[str, float]] = {}
    text_metrics_both: dict[str, dict[str, float]] = {}

    gt_both = _filter_gt(gt, keys_both)

    for f in fields:
        speech_metrics[f] = evaluate_pairs(gt, speech, f)
        text_metrics[f] = evaluate_pairs(gt, text, f)
        if gt_both:
            speech_metrics_both[f] = evaluate_pairs(gt_both, speech, f)
            text_metrics_both[f] = evaluate_pairs(gt_both, text, f)

    out_json = OUT_DIR / "f1_metrics.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "ground_truth": str(GT_XLSX),
        "n_gt_rows": len(gt),
        "keys_in_gt": len(gt_keys),
        "keys_gt_and_speech_csv": len(keys_speech),
        "keys_gt_and_text_csv": len(keys_text),
        "keys_gt_and_both_csv": len(keys_both),
        "speech_csv": str(SPEECH_CSV),
        "text_csv": str(TEXT_CSV),
        "by_field_all_gt_rows": {
            fn: {"speech": speech_metrics[fn], "text": text_metrics[fn]} for fn in fields
        },
        "by_field_same_cases_in_both_csv": (
            {
                fn: {
                    "speech": speech_metrics_both[fn],
                    "text": text_metrics_both[fn],
                }
                for fn in fields
            }
            if gt_both
            else {}
        ),
    }
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    plot_comparison(
        fields,
        speech_metrics,
        text_metrics,
        OUT_DIR / "f1_comparison.png",
    )
    plot_delta(fields, speech_metrics, text_metrics, OUT_DIR / "f1_delta_text_minus_speech.png")
    if gt_both:
        plot_comparison(
            fields,
            speech_metrics_both,
            text_metrics_both,
            OUT_DIR / "f1_comparison_same_cases_both_csv.png",
        )
        plot_delta(
            fields,
            speech_metrics_both,
            text_metrics_both,
            OUT_DIR / "f1_delta_same_cases_text_minus_speech.png",
        )

    # แยกบรรทัด — อย่ารวมข้อความไทยกับพาธยาวในบรรทัดเดียว (บางเทอร์มินัล wrap ผิดทำให้ชื่อไฟล์ดูแตก)
    def _print_out(label: str, path: Path) -> None:
        print(label)
        print(str(path.resolve()))

    _print_out("บันทึกกราฟ (ทุกแถว GT)", OUT_DIR / "f1_comparison.png")
    _print_out("บันทึกความต่าง (ทุกแถว GT)", OUT_DIR / "f1_delta_text_minus_speech.png")
    if gt_both:
        _print_out(
            "บันทึกกราฟ (เฉพาะเคสที่มีทั้ง speech และ text CSV)",
            OUT_DIR / "f1_comparison_same_cases_both_csv.png",
        )
        _print_out(
            "บันทึกความต่าง (เคสเดียวกัน)",
            OUT_DIR / "f1_delta_same_cases_text_minus_speech.png",
        )
    _print_out("บันทึก JSON", out_json)
    print()
    print(
        f"จำแนกจาก GT {len(gt)} แถว — คีย์ตรงกับ speech CSV: {len(keys_speech)} | "
        f"กับ text CSV: {len(keys_text)} | มีในทั้งสองไฟล์: {len(keys_both)}"
    )
    print("(ตัวเลขต่ำเมื่อใช้ “ทุกแถว GT” มักมาจากแถวที่ไม่มีใน CSV → ถูกนับเป็น FN)")
    print(
        "(chk = ชิ้นจาก GT ที่คั่นด้วย comma พบในข้อความ pred — เหมาะเมื่อ GT สั้นกว่าผลสกัดยาว)"
    )
    print(
        "(ner = micro-F1 ระหว่างชุดชิ้นที่ตัดด้วย comma — เหมือน mention-level NER exact match)"
    )
    print()
    print("— ทุกแถวใน GT (รวมเคสที่ไม่มีไฟล์ใน CSV) —")

    def _print_metrics_for_field(fname: str, sm: dict, tm: dict) -> None:
        """แยกชื่อช่อง (ไทย) กับตัวเลข — บรรทัดยาวที่มีไทย+ASCII ทำให้เทอร์มินัล wrap ผิดกลางคำ (เช่น ner→nerr)"""
        print(f"  [{fname}]")
        if fname == "ประเภท":
            print(
                f"    speech F1(type)={sm.get('f1_macro', 0):.3f}  |  "
                f"text F1(type)={tm.get('f1_macro', 0):.3f}"
            )
            return
        print(
            "    speech "
            f"tok={sm.get('f1_token_micro', 0):.3f} "
            f"span={sm.get('f1_span_micro', 0):.3f} "
            f"ner={sm.get('ner_entity_f1_micro', 0):.3f} "
            f"chk={sm.get('substring_chunk_recall_macro', 0):.3f}"
        )
        print(
            "    text   "
            f"tok={tm.get('f1_token_micro', 0):.3f} "
            f"span={tm.get('f1_span_micro', 0):.3f} "
            f"ner={tm.get('ner_entity_f1_micro', 0):.3f} "
            f"chk={tm.get('substring_chunk_recall_macro', 0):.3f}"
        )

    for f in fields:
        _print_metrics_for_field(f, speech_metrics[f], text_metrics[f])
    if gt_both:
        print()
        print(
            f"— เฉพาะเคสที่มีในทั้ง speech และ text CSV ({len(gt_both)} แถว) —"
        )
        for f in fields:
            _print_metrics_for_field(f, speech_metrics_both[f], text_metrics_both[f])

    if "--gemini-judge" in sys.argv:
        max_calls = _argv_int("--gemini-judge-max", 30)
        pause_sec = float(os.environ.get("GEMINI_JUDGE_PAUSE_SEC", "1.2"))
        if "--gemini-judge-both-only" in sys.argv and gt_both:
            rows_judge = gt_both
            print("\n[Gemini boundary judge] ใช้เฉพาะเคสที่มีทั้ง speech และ text CSV")
        else:
            rows_judge = gt
            if "--gemini-judge-both-only" in sys.argv:
                print(
                    "\n[Gemini boundary judge] ไม่มีเคสทั้งสอง CSV — ใช้ทุกแถว GT แทน",
                    flush=True,
                )
        print(
            f"\nเรียก Gemini ประเมิน boundary (สูงสุด {max_calls} ครั้ง, pause {pause_sec}s)…",
            flush=True,
        )
        judge_results, judge_agg = run_gemini_boundary_judge(
            rows_judge,
            speech,
            text,
            max_calls=max_calls,
            pause_sec=pause_sec,
        )
        judge_path = OUT_DIR / "gemini_boundary_judge.json"
        judge_path.parent.mkdir(parents=True, exist_ok=True)
        judge_path.write_text(
            json.dumps(
                {"aggregate": judge_agg, "results": judge_results},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("\nสรุป Gemini boundary judge")
        print(f"  เรียก API จำนวน: {judge_agg.get('n_api_calls', 0)}")
        print(
            f"  speech — avg score: {judge_agg.get('speech_avg_score', 0):.1f} | "
            f"within_boundary rate: {judge_agg.get('speech_within_rate', 0):.3f}"
        )
        print(
            f"  text   — avg score: {judge_agg.get('text_avg_score', 0):.1f} | "
            f"within_boundary rate: {judge_agg.get('text_within_rate', 0):.3f}"
        )
        print("\nบันทึกรายละเอียด")
        print(str(judge_path.resolve()))


if __name__ == "__main__":
    main()
