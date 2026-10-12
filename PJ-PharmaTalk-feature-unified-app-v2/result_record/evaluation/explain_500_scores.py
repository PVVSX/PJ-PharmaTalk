# -*- coding: utf-8 -*-
"""Generate score explanations and interesting samples for the 500-case evaluation."""
from __future__ import annotations

import csv
import json
import re

from evaluate_500_ground_truth import (
    FIELDS,
    OUT_DIR,
    chunk_substring_recall,
    evaluate_field,
    is_empty_value,
    lenient_chunk_score,
    load_data,
    normalize_text,
    prf,
    tokenize,
    visit_labels,
)


def multiset_token_f1(gt_text: str, pred_text: str) -> float:
    gt = tokenize(gt_text)
    pred = tokenize(pred_text)
    tp = fp = fn = 0
    for t in set(gt) | set(pred):
        gv, pv = gt.get(t, 0), pred.get(t, 0)
        tp += min(gv, pv)
        fp += max(0, pv - gv)
        fn += max(0, gv - pv)
    _, _, f1 = prf(tp, fp, fn)
    return f1


def type_row_f1(gt_text: str, pred_text: str) -> float:
    gt = visit_labels(gt_text)
    pred = visit_labels(pred_text)
    tp = len(gt & pred)
    fp = len(pred - gt)
    fn = len(gt - pred)
    _, _, f1 = prf(tp, fp, fn)
    return f1


def row_reason(field: str, score: float, gt_text: str, pred_text: str) -> str:
    if field == "ประเภท":
        gt = ", ".join(sorted(visit_labels(gt_text))) or "-"
        pred = ", ".join(sorted(visit_labels(pred_text))) or "-"
        if score >= 0.999:
            return f"ได้เต็ม เพราะประเภทตรงกัน ({gt})"
        if score > 0:
            return f"ได้บางส่วน เพราะ label ซ้อนกันบางส่วน: GT={gt}, Pred={pred}"
        return f"ได้ต่ำ เพราะ label ไม่ตรงกัน: GT={gt}, Pred={pred}"

    if normalize_text(gt_text).lower() == normalize_text(pred_text).lower():
        return "ได้เต็ม เพราะข้อความตรงกันหลัง normalize"
    chunk = chunk_substring_recall(gt_text, pred_text)
    if chunk == 1:
        return "ได้สูง เพราะชิ้นข้อมูลจาก GT พบอยู่ใน prediction ครบ"
    if score >= 0.85:
        return "ได้สูง เพราะ prediction ใช้คำใกล้เคียงหรือครอบคลุมความหมายของ GT"
    if score >= 0.5:
        return "ได้กลาง เพราะพบข้อมูลบางส่วน แต่ wording/รายละเอียดยังต่างจาก GT"
    if normalize_text(pred_text) in ("", "-"):
        return "ได้ต่ำ เพราะ prediction ว่างหรือเป็น '-' ทั้งที่ GT มีข้อมูล"
    return "ได้ต่ำ เพราะข้อมูลสำคัญจาก GT ไม่พบตรง ๆ หรือใช้คำคนละชุดมาก"


def row_score(field: str, gt_text: str, pred_text: str) -> float:
    if field == "ประเภท":
        return type_row_f1(gt_text, pred_text)
    value = lenient_chunk_score(gt_text, pred_text)
    return float(value if value is not None else 1.0)


def bucket(score: float) -> str:
    if score >= 0.85:
        return "สูง"
    if score >= 0.5:
        return "กลาง"
    return "ต่ำ"


FEATURE_DESCRIPTIONS = {
    "ประเภท": "บันทึกประเภทการเข้ามาหาเภสัช เช่น มาซื้อยา, มาปรึกษาอาการ, หรือเป็นทั้งสองอย่างในเคสเดียวกัน",
    "ประวัติการแพ้ยา": "บันทึกข้อมูลการแพ้ยาหรือสิ่งที่เกี่ยวข้องกับการแพ้ เช่น ชื่อยา กลุ่มยา อาการแพ้ หรือประวัติแพ้อาหาร/สารบางชนิดที่มีผลต่อการจ่ายยา",
    "โรคประจำตัว": "บันทึกโรคหรือภาวะสุขภาพเดิมของผู้ป่วย เช่น เบาหวาน ความดัน ไมเกรน โรคหัวใจ หรือโรคอื่นที่เภสัชต้องใช้ประกอบการเลือกยา",
    "ประวัติการจ่ายยา": "บันทึกยาที่ผู้ป่วยเคยใช้ กำลังใช้อยู่ หรือรับประทานมาก่อนมาพบเภสัช เช่น ยาประจำ ยาที่กินเองก่อนมา หรือยาที่อาจมีผลต่อการจ่ายยาใหม่",
    "บันทึกทางการแพทย์": "บันทึกอาการสำคัญและบริบททางคลินิกจากบทสนทนา เช่น อาการป่วย ระยะเวลา ความรุนแรง ตำแหน่งที่เป็น และข้อมูลประกอบการประเมินเบื้องต้น",
    "คำแนะนำจากเภสัช": "บันทึกคำแนะนำหรือแผนการดูแลที่เภสัชให้ผู้ป่วย เช่น วิธีใช้ยา ข้อควรระวัง การดูแลตัวเอง และการแนะนำให้พบแพทย์เมื่อมีสัญญาณอันตราย",
}


def pick_examples(rows: list[dict], per_bucket: int = 2) -> list[dict]:
    out: list[dict] = []
    targets = [("สูง", 1.0), ("กลาง", 0.65), ("ต่ำ", 0.0)]
    for label, target in targets:
        candidates = [r for r in rows if r["bucket"] == label]
        candidates.sort(key=lambda r: (abs(float(r["score"]) - target), int(r["case"])))
        out.extend(candidates[:per_bucket])
    return out


def format_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def safe_image_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]+', "_", name.strip())
    return cleaned.strip("_") or "table"


def main() -> None:
    gt_by_key, pred_by_key, matched = load_data()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    metrics = {field: evaluate_field(gt_by_key, pred_by_key, field) for field in FIELDS}
    field_rows: dict[str, list[dict]] = {field: [] for field in FIELDS}

    for key in sorted(gt_by_key, key=lambda k: int(k) if k.isdigit() else k):
        gt_row = gt_by_key[key]
        pred_row = pred_by_key.get(key, {})
        for field in FIELDS:
            gt_text = gt_row.get(field, "")
            pred_text = pred_row.get(field, "")
            if field != "ประเภท" and is_empty_value(gt_text):
                continue
            score = row_score(field, gt_text, pred_text) if key in pred_by_key else 0.0
            item = {
                "case": key,
                "field": field,
                "score": score,
                "score_percent": format_pct(score),
                "bucket": bucket(score),
                "reason": row_reason(field, score, gt_text, pred_text),
                "gt": normalize_text(gt_text),
                "pred": normalize_text(pred_text),
                "token_f1": "" if field == "ประเภท" else format_pct(multiset_token_f1(gt_text, pred_text)),
                "chunk_recall": "" if field == "ประเภท" else format_pct(chunk_substring_recall(gt_text, pred_text) or 0.0),
            }
            field_rows[field].append(item)

    samples = {field: pick_examples(rows) for field, rows in field_rows.items()}
    flat_samples = [item for field in FIELDS for item in samples[field]]

    with open(OUT_DIR / "score_samples_500.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case",
                "field",
                "score_percent",
                "bucket",
                "reason",
                "gt",
                "pred",
                "token_f1",
                "chunk_recall",
            ],
        )
        writer.writeheader()
        for item in flat_samples:
            writer.writerow({k: item.get(k, "") for k in writer.fieldnames})

    payload = {
        "coverage": {
            "gt_cases": len(gt_by_key),
            "pred_cases": len(pred_by_key),
            "matched_cases": len(matched),
            "missing_prediction_cases": sorted(set(gt_by_key) - set(pred_by_key), key=lambda k: int(k)),
        },
        "metrics_by_field": metrics,
        "samples_by_field": samples,
    }
    (OUT_DIR / "score_explanation_500.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines: list[str] = [
        "# ที่มาที่ไปของคะแนนประเมินชุด 500 เคส",
        "",
        "## วิธีคิดคะแนนหลัก",
        "",
        "- `Lenient Score` เป็นคะแนนหลักแบบผ่อนปรน: ถ้า GT อยู่ใน prediction ให้คะแนนเต็ม และถ้าใช้คำใกล้เคียง/paraphrase จะให้คะแนนบางส่วนด้วย similarity",
        "- `Token F1` เข้มกว่า: แตกข้อความเป็น token แล้วนับคำที่ตรงกัน",
        "- `Strict NER F1` เข้มที่สุด: ตัด entity ด้วย comma/semicolon แล้วต้อง match ทั้งก้อน",
        "- `Chunk Recall` ดูว่า chunk จาก GT ปรากฏใน prediction กี่ส่วน",
        "",
        f"Coverage: GT {len(gt_by_key)} เคส, prediction {len(pred_by_key)} เคส, matched {len(matched)} เคส, ขาดเคส {', '.join(payload['coverage']['missing_prediction_cases']) or '-'}",
        "",
        "## สรุปเหตุผลรายหมวด",
        "",
    ]

    for field_index, field in enumerate(FIELDS, start=1):
        m = metrics[field]
        rows = field_rows[field]
        high = sum(1 for r in rows if r["bucket"] == "สูง")
        mid = sum(1 for r in rows if r["bucket"] == "กลาง")
        low = sum(1 for r in rows if r["bucket"] == "ต่ำ")
        if field == "ประเภท":
            main_score = m.get("lenient_score", m.get("f1", 0.0))
            metric_line = f"คะแนนหลัก {format_pct(main_score)} | precision {format_pct(m.get('precision', 0.0))} | recall {format_pct(m.get('recall', 0.0))}"
            reason = "คะแนนสูงเพราะโมเดลมักจับ intent ซื้อยา/ปรึกษาได้ตรง โดย recall สูงมาก แต่ exact row match ต่ำกว่าเพราะบางเคส GT เป็น label เดียวแต่โมเดลตอบเป็นทั้งคู่"
        else:
            main_score = m.get("lenient_score", 0.0)
            metric_line = (
                f"Lenient {format_pct(main_score)} | Token F1 {format_pct(m.get('token_f1', 0.0))} | "
                f"Strict NER F1 {format_pct(m.get('ner_f1', 0.0))} | Chunk Recall {format_pct(m.get('chunk_recall', 0.0))}"
            )
            if main_score >= 0.8:
                reason = "คะแนนดี เพราะคำสำคัญใน GT มักยังปรากฏหรือใกล้เคียงกับ prediction แม้ wording ไม่ตรงเป๊ะ"
            elif main_score >= 0.5:
                reason = "คะแนนระดับกลาง เพราะมี semantic overlap แต่รายละเอียด/รูปประโยคต่างจาก GT มาก ทำให้ strict metrics ต่ำ"
            else:
                reason = "คะแนนต่ำ เพราะข้อมูล GT มักเป็นวลีเฉพาะ แต่ prediction ขาด/ใช้คำคนละชุด/สรุปกว้าง ทำให้ chunk และ entity match น้อย"

        lines.extend(
            [
                f"### {field}",
                "",
                f"- ฟีเจอร์นี้ใช้ทำอะไร: {FEATURE_DESCRIPTIONS[field]}",
                f"- {metric_line}",
                f"- การกระจายเคส: สูง {high} | กลาง {mid} | ต่ำ {low}",
                f"- เหตุผลหลัก: {reason}",
                "",
                "| Case | ระดับ | Score | เหตุผล | GT | Prediction |",
                "|---:|---|---:|---|---|---|",
            ]
        )
        for item in samples[field]:
            gt = str(item["gt"]).replace("|", "\\|")[:160]
            pred = str(item["pred"]).replace("|", "\\|")[:180]
            lines.append(
                f"| {item['case']} | {item['bucket']} | {item['score_percent']} | {item['reason']} | {gt} | {pred} |"
            )
        image_name = f"{field_index:02d}_{safe_image_filename(field)}.png"
        lines.extend(
            [
                "",
                f"รูปตาราง: `report/500/evaluation/table_images/{image_name}`",
                "",
                f"![ตาราง{field}](table_images/{image_name})",
            ]
        )
        lines.append("")

    (OUT_DIR / "score_explanation_500.md").write_text("\n".join(lines), encoding="utf-8")

    print("สร้างรายงานอธิบายคะแนนแล้ว")
    print(OUT_DIR / "score_explanation_500.md")
    print(OUT_DIR / "score_samples_500.csv")
    print(OUT_DIR / "score_explanation_500.json")


if __name__ == "__main__":
    main()
