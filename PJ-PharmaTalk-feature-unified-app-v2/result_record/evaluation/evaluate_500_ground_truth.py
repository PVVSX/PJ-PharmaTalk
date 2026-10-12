# -*- coding: utf-8 -*-
"""
Evaluate report/500/gemini_extract.csv against report/500/บท500_ground_truth.csv.

Outputs:
  report/500/evaluation/metrics_500.json
  report/500/evaluation/metrics_500_by_field.csv
  report/500/evaluation/evaluation_report_500.md
  report/500/evaluation/f1_by_field_500.png
  report/500/evaluation/coverage_by_field_500.png

Optional semantic boundary judging with Gemini:
  python evaluate_500_ground_truth.py --gemini-judge --gemini-judge-max 30
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
from difflib import SequenceMatcher
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
PRED_CSV = BASE / "report" / "500" / "gemini_extract.csv"
GT_CSV = BASE / "report" / "500" / "บท500_ground_truth.csv"
OUT_DIR = BASE / "report" / "500" / "evaluation"

KEY_FIELD_GT = "บทที่"
KEY_FIELD_PRED = "ชื่อไฟล์"
FIELDS = [
    "ประเภท",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def case_key_from_pred(name: str) -> str:
    s = (name or "").strip()
    m = re.search(r"case[_-]?(\d+)", s, flags=re.I)
    if m:
        return str(int(m.group(1)))
    stem = Path(s).stem
    return str(int(stem)) if stem.isdigit() else stem


def case_key_from_gt(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    try:
        return str(int(float(s)))
    except ValueError:
        return s


def normalize_text(s: str) -> str:
    t = unicodedata.normalize("NFKC", str(s or ""))
    # normalize common arrow variants used by GT / prediction
    t = t.replace("->", "→").replace("=>", "→")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def compact_text(s: str) -> str:
    """Normalize for lenient matching: remove spaces and light punctuation."""
    t = normalize_text(s).lower()
    t = re.sub(r"[\s,，;|•·/()（）:：\"'“”‘’\[\]{}]+", "", t)
    return t


def is_empty_value(s: str) -> bool:
    return normalize_text(s) in ("", "-", "–", "—")


def visit_labels(s: str) -> frozenset[str]:
    t = normalize_text(s)
    if is_empty_value(t):
        return frozenset()
    labels: set[str] = set()
    if "ทั้งคู่" in t:
        labels.update(("ซื้อยา", "ปรึกษา"))
    if "ซื้อ" in t or "มาซื้อ" in t:
        labels.add("ซื้อยา")
    if "ปรึกษา" in t:
        labels.add("ปรึกษา")
    return frozenset(labels)


def tokenize(text: str) -> Counter[str]:
    t = normalize_text(text).lower()
    if is_empty_value(t):
        return Counter()
    parts = re.split(r"[,，;|•·/()（）:：]+", t)
    out: Counter[str] = Counter()
    for part in parts:
        for token in re.split(r"\s+", part.strip()):
            token = token.strip()
            if len(token) >= 2 or token.isdigit():
                out[token] += 1
    return out


def ner_entities(text: str) -> set[str]:
    """Mention-level NER proxy: comma/semicolon-separated spans as entities."""
    t = normalize_text(text).lower()
    if is_empty_value(t):
        return set()
    out: set[str] = set()
    for part in re.split(r"[,，;|•·\n]+", t):
        p = part.strip()
        if len(p) >= 2 and not is_empty_value(p):
            out.add(p)
    return out


def chunk_substring_recall(gt_text: str, pred_text: str) -> float | None:
    """How many comma-separated GT chunks appear inside the predicted text."""
    gt = normalize_text(gt_text)
    pred = normalize_text(pred_text).lower()
    if is_empty_value(gt):
        return None
    if not pred:
        return 0.0
    chunks = [c.strip().lower() for c in re.split(r"[,，;|•·\n]+", gt) if c.strip()]
    if not chunks:
        chunks = [gt.lower()]
    hits = [1.0 if c in pred else 0.0 for c in chunks if len(c) >= 2]
    return sum(hits) / len(hits) if hits else None


def lenient_chunk_score(gt_text: str, pred_text: str) -> float | None:
    """
    More forgiving clinical extraction score.

    - Exact/substring containment of a GT chunk inside prediction => 1.0.
    - Otherwise use fuzzy similarity between each GT chunk and the best matching
      prediction chunk/full text. This rewards paraphrases and minor wording changes.
    """
    gt = normalize_text(gt_text)
    pred = normalize_text(pred_text)
    if is_empty_value(gt):
        return None
    if not pred or is_empty_value(pred):
        return 0.0

    gt_chunks = [c.strip() for c in re.split(r"[,，;|•·\n]+", gt) if c.strip()]
    pred_chunks = [c.strip() for c in re.split(r"[,，;|•·\n]+", pred) if c.strip()]
    if not gt_chunks:
        gt_chunks = [gt]
    if not pred_chunks:
        pred_chunks = [pred]

    pred_compact = compact_text(pred)
    pred_compact_chunks = [compact_text(c) for c in pred_chunks]
    scores: list[float] = []
    for chunk in gt_chunks:
        c = compact_text(chunk)
        if not c:
            continue
        if c in pred_compact:
            scores.append(1.0)
            continue
        best = SequenceMatcher(None, c, pred_compact).ratio()
        for pc in pred_compact_chunks:
            if pc:
                best = max(best, SequenceMatcher(None, c, pc).ratio())
        # Slightly boost near matches, but keep weak matches low.
        if best >= 0.82:
            scores.append(0.95)
        elif best >= 0.68:
            scores.append(0.8)
        elif best >= 0.55:
            scores.append(0.6)
        else:
            scores.append(best * 0.8)
    return sum(scores) / len(scores) if scores else None


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0, 1.0, 1.0
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def multilabel_f1(gold: frozenset[str], pred: frozenset[str]) -> tuple[int, int, int]:
    return len(gold & pred), len(pred - gold), len(gold - pred)


def evaluate_field(
    gt_by_key: dict[str, dict[str, str]],
    pred_by_key: dict[str, dict[str, str]],
    field: str,
) -> dict[str, float]:
    token_tp = token_fp = token_fn = 0
    ner_tp = ner_fp = ner_fn = 0
    chunks: list[float] = []
    lenient_scores: list[float] = []
    row_exact = 0
    type_tp = type_fp = type_fn = 0

    for key, gt_row in gt_by_key.items():
        pred_row = pred_by_key.get(key, {})
        gt_text = gt_row.get(field, "")
        pred_text = pred_row.get(field, "")

        if field == "ประเภท":
            tp, fp, fn = multilabel_f1(visit_labels(gt_text), visit_labels(pred_text))
            type_tp += tp
            type_fp += fp
            type_fn += fn
            if tp and not fp and not fn:
                row_exact += 1
            continue

        if normalize_text(gt_text).lower() == normalize_text(pred_text).lower():
            row_exact += 1

        if key not in pred_by_key:
            token_fn += sum(tokenize(gt_text).values())
            ner_fn += len(ner_entities(gt_text))
            if not is_empty_value(gt_text):
                chunks.append(0.0)
                lenient_scores.append(0.0)
            continue

        gt_tok = tokenize(gt_text)
        pred_tok = tokenize(pred_text)
        for t in set(gt_tok) | set(pred_tok):
            gv, pv = gt_tok.get(t, 0), pred_tok.get(t, 0)
            token_tp += min(gv, pv)
            token_fp += max(0, pv - gv)
            token_fn += max(0, gv - pv)

        gt_ent = ner_entities(gt_text)
        pred_ent = ner_entities(pred_text)
        ner_tp += len(gt_ent & pred_ent)
        ner_fp += len(pred_ent - gt_ent)
        ner_fn += len(gt_ent - pred_ent)

        chunk_score = chunk_substring_recall(gt_text, pred_text)
        if chunk_score is not None:
            chunks.append(chunk_score)
        lenient = lenient_chunk_score(gt_text, pred_text)
        if lenient is not None:
            lenient_scores.append(lenient)

    if field == "ประเภท":
        p, r, f1 = prf(type_tp, type_fp, type_fn)
        return {
            "precision": p,
            "recall": r,
            "f1": f1,
            "lenient_score": f1,
            "row_exact_match": row_exact / len(gt_by_key) if gt_by_key else 0.0,
        }

    p_t, r_t, f1_t = prf(token_tp, token_fp, token_fn)
    p_n, r_n, f1_n = prf(ner_tp, ner_fp, ner_fn)
    return {
        "token_precision": p_t,
        "token_recall": r_t,
        "token_f1": f1_t,
        "ner_precision": p_n,
        "ner_recall": r_n,
        "ner_f1": f1_n,
        "chunk_recall": sum(chunks) / len(chunks) if chunks else 0.0,
        "lenient_score": (
            sum(lenient_scores) / len(lenient_scores) if lenient_scores else 0.0
        ),
        "row_exact_match": row_exact / len(gt_by_key) if gt_by_key else 0.0,
    }


def build_low_score_examples(
    gt_by_key: dict[str, dict[str, str]],
    pred_by_key: dict[str, dict[str, str]],
    limit: int = 30,
) -> list[dict[str, str | float]]:
    examples: list[dict[str, str | float]] = []
    for key, gt_row in gt_by_key.items():
        pred_row = pred_by_key.get(key, {})
        for field in FIELDS:
            if field == "ประเภท":
                continue
            gt_text = gt_row.get(field, "")
            pred_text = pred_row.get(field, "")
            score = chunk_substring_recall(gt_text, pred_text)
            if score is None:
                continue
            if score < 1:
                examples.append(
                    {
                        "case": key,
                        "field": field,
                        "chunk_recall": score,
                        "gt": normalize_text(gt_text)[:180],
                        "pred": normalize_text(pred_text)[:220],
                    }
                )
    examples.sort(key=lambda x: (float(x["chunk_recall"]), int(str(x["case"]))))
    return examples[:limit]


def plot_metrics(metrics: dict[str, dict[str, float]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["Tahoma", "Segoe UI", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    fields = list(metrics)
    lenient = [metrics[f].get("lenient_score", metrics[f].get("f1", 0.0)) for f in fields]
    token_f1 = [metrics[f].get("token_f1", metrics[f].get("f1", 0.0)) for f in fields]
    ner_f1 = [metrics[f].get("ner_f1", metrics[f].get("f1", 0.0)) for f in fields]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    x = range(len(fields))
    w = 0.28

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar([i - w for i in x], lenient, width=w, label="Lenient score")
    ax.bar(list(x), token_f1, width=w, label="Token / Type F1")
    ax.bar([i + w for i in x], ner_f1, width=w, label="Strict NER F1")
    ax.set_title("500-case evaluation against ground truth (lenient view)")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(list(x))
    ax.set_xticklabels(fields, rotation=22, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "f1_by_field_500.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(list(x), lenient)
    ax.set_title("Lenient score by field")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(list(x))
    ax.set_xticklabels(fields, rotation=22, ha="right")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "lenient_score_by_field_500.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(["GT cases", "Pred cases", "Matched"], [
        len(read_csv_rows(GT_CSV)),
        len(read_csv_rows(PRED_CSV)),
        len(load_data()[2]),
    ])
    ax.set_title("Case coverage")
    ax.set_ylabel("Rows")
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    fig.savefig(OUT_DIR / "coverage_by_field_500.png", dpi=150)
    plt.close(fig)


def load_data() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], set[str]]:
    gt_rows = read_csv_rows(GT_CSV)
    pred_rows = read_csv_rows(PRED_CSV)
    gt_by_key = {
        case_key_from_gt(row.get(KEY_FIELD_GT, "")): row
        for row in gt_rows
        if case_key_from_gt(row.get(KEY_FIELD_GT, ""))
    }
    pred_by_key = {
        case_key_from_pred(row.get(KEY_FIELD_PRED, "")): row
        for row in pred_rows
        if case_key_from_pred(row.get(KEY_FIELD_PRED, ""))
    }
    return gt_by_key, pred_by_key, set(gt_by_key) & set(pred_by_key)


BOUNDARY_JUDGE_SYSTEM = """คุณเป็นกรรมการประเมินผลการสกัดข้อมูลเชิงคลินิก/เภสัชกรรม
ตอบเป็น JSON เท่านั้น ไม่มี markdown และไม่มีข้อความอื่น"""


def parse_json_loose(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        value = json.loads(m.group(0))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def gemini_boundary_judge(gt_text: str, pred_text: str, field: str) -> dict:
    from classify_gemini_extract import call_gemini

    prompt = (
        f"ช่องข้อมูล: {field}\n\n"
        f"GROUND_TRUTH_BOUNDARY:\n{normalize_text(gt_text) or '(ว่าง)'}\n\n"
        f"PREDICTION:\n{normalize_text(pred_text) or '(ว่าง)'}\n\n"
        "ประเมินว่า PREDICTION อยู่ภายใน boundary ของ ground truth หรือไม่ "
        "โดยอนุญาตให้ใช้คำคนละแบบ/ขยายรายละเอียดได้ ถ้าไม่ขัดแย้งและยังอยู่ประเด็นเดียวกัน\n"
        "ตอบ JSON รูปแบบนี้เท่านั้น:\n"
        '{"within_boundary": true, "coverage_0_1": 0.0, '
        '"contradiction": false, "score_0_100": 0, "reason": "สั้นๆ"}'
    )
    return parse_json_loose(call_gemini(BOUNDARY_JUDGE_SYSTEM, prompt, temperature=0.05))


def run_gemini_judge(
    gt_by_key: dict[str, dict[str, str]],
    pred_by_key: dict[str, dict[str, str]],
    max_calls: int,
) -> dict:
    results: list[dict] = []
    score_values: list[float] = []
    within_values: list[float] = []
    for key in sorted(gt_by_key, key=lambda k: int(k) if k.isdigit() else k):
        if key not in pred_by_key:
            continue
        for field in FIELDS:
            if field == "ประเภท":
                continue
            if len(results) >= max_calls:
                break
            gt_text = gt_by_key[key].get(field, "")
            pred_text = pred_by_key[key].get(field, "")
            if is_empty_value(gt_text) and is_empty_value(pred_text):
                continue
            print(f"[Gemini judge {len(results) + 1}/{max_calls}] case {key} | {field}", flush=True)
            try:
                judge = gemini_boundary_judge(gt_text, pred_text, field)
            except Exception as exc:
                judge = {"error": str(exc)}
            results.append({"case": key, "field": field, "judge": judge})
            score = judge.get("score_0_100")
            if isinstance(score, (int, float)):
                score_values.append(float(score))
            within = judge.get("within_boundary")
            if isinstance(within, bool):
                within_values.append(1.0 if within else 0.0)
            time.sleep(float(os.environ.get("GEMINI_JUDGE_PAUSE_SEC", "1.2")))
        if len(results) >= max_calls:
            break
    return {
        "n_calls": len(results),
        "avg_score_0_100": sum(score_values) / len(score_values) if score_values else 0.0,
        "within_boundary_rate": sum(within_values) / len(within_values) if within_values else 0.0,
        "results": results,
    }


def write_outputs(metrics: dict[str, dict[str, float]], payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "metrics_500.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with open(OUT_DIR / "metrics_500_by_field.csv", "w", encoding="utf-8-sig", newline="") as f:
        cols = [
            "field",
            "lenient_score",
            "token_f1",
            "ner_f1",
            "chunk_recall",
            "type_f1",
            "row_exact_match",
        ]
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for field, m in metrics.items():
            writer.writerow(
                {
                    "field": field,
                    "lenient_score": m.get("lenient_score", ""),
                    "token_f1": m.get("token_f1", ""),
                    "ner_f1": m.get("ner_f1", ""),
                    "chunk_recall": m.get("chunk_recall", ""),
                    "type_f1": m.get("f1", ""),
                    "row_exact_match": m.get("row_exact_match", ""),
                }
            )

    lines = [
        "# Evaluation Report: 500 Cases",
        "",
        f"- Prediction: `{PRED_CSV}`",
        f"- Ground truth: `{GT_CSV}`",
        f"- GT cases: {payload['coverage']['gt_cases']}",
        f"- Prediction cases: {payload['coverage']['pred_cases']}",
        f"- Matched cases: {payload['coverage']['matched_cases']}",
        "",
        "## Metrics",
        "",
        "| Field | Lenient Score | Type/Token F1 | Strict NER F1 | Chunk Recall | Exact Row Match |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for field, m in metrics.items():
        f1 = m.get("token_f1", m.get("f1", 0.0))
        lines.append(
            f"| {field} | {m.get('lenient_score', m.get('f1', 0.0)):.3f} | "
            f"{f1:.3f} | {m.get('ner_f1', m.get('f1', 0.0)):.3f} | "
            f"{m.get('chunk_recall', m.get('row_exact_match', 0.0)):.3f} | "
            f"{m.get('row_exact_match', 0.0):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `Lenient Score` is the headline metric for this view: exact substring matches receive full credit and near paraphrases receive partial credit via text similarity.",
            "- `NER F1` uses comma/semicolon-separated spans as mention entities and exact matching after normalization.",
            "- `Chunk Recall` is more forgiving for GT-short vs prediction-long cases: it checks whether GT chunks appear inside the prediction.",
            "- Optional Gemini boundary judging is available with `--gemini-judge` for semantic assessment.",
            "",
            "## Lowest Chunk-Recall Examples",
            "",
        ]
    )
    for ex in payload["low_score_examples"][:12]:
        lines.extend(
            [
                f"### Case {ex['case']} — {ex['field']} (chunk recall {ex['chunk_recall']:.3f})",
                f"- GT: {ex['gt']}",
                f"- Pred: {ex['pred']}",
                "",
            ]
        )
    (OUT_DIR / "evaluation_report_500.md").write_text("\n".join(lines), encoding="utf-8")


def argv_int(flag: str, default: int) -> int:
    if flag not in sys.argv:
        return default
    try:
        return int(sys.argv[sys.argv.index(flag) + 1])
    except (ValueError, IndexError):
        return default


def main() -> None:
    if not PRED_CSV.is_file():
        raise SystemExit(f"Missing prediction CSV: {PRED_CSV}")
    if not GT_CSV.is_file():
        raise SystemExit(f"Missing ground truth CSV: {GT_CSV}")

    gt_by_key, pred_by_key, matched = load_data()
    metrics = {
        field: evaluate_field(gt_by_key, pred_by_key, field)
        for field in FIELDS
    }
    payload = {
        "prediction_csv": str(PRED_CSV),
        "ground_truth_csv": str(GT_CSV),
        "coverage": {
            "gt_cases": len(gt_by_key),
            "pred_cases": len(pred_by_key),
            "matched_cases": len(matched),
            "missing_prediction_cases": sorted(set(gt_by_key) - set(pred_by_key), key=lambda k: int(k)),
            "extra_prediction_cases": sorted(set(pred_by_key) - set(gt_by_key), key=lambda k: int(k)),
        },
        "metrics_by_field": metrics,
        "low_score_examples": build_low_score_examples(gt_by_key, pred_by_key),
    }

    if "--gemini-judge" in sys.argv:
        max_calls = argv_int("--gemini-judge-max", 30)
        payload["gemini_boundary_judge"] = run_gemini_judge(gt_by_key, pred_by_key, max_calls)

    write_outputs(metrics, payload)
    plot_metrics(metrics)

    print("บันทึกผลประเมิน 500 cases")
    print(str((OUT_DIR / "evaluation_report_500.md").resolve()))
    print(str((OUT_DIR / "metrics_500.json").resolve()))
    print(str((OUT_DIR / "f1_by_field_500.png").resolve()))
    print(str((OUT_DIR / "lenient_score_by_field_500.png").resolve()))
    print()
    print(
        f"Coverage: GT={len(gt_by_key)} pred={len(pred_by_key)} matched={len(matched)}"
    )
    print("Field metrics")
    for field, m in metrics.items():
        if field == "ประเภท":
            print(
                f"  {field}: lenient={m.get('lenient_score', 0):.3f} "
                f"type_f1={m.get('f1', 0):.3f} exact={m.get('row_exact_match', 0):.3f}"
            )
        else:
            print(
                f"  {field}: lenient={m.get('lenient_score', 0):.3f} "
                f"token_f1={m.get('token_f1', 0):.3f} "
                f"ner_f1={m.get('ner_f1', 0):.3f} chunk={m.get('chunk_recall', 0):.3f}"
            )


if __name__ == "__main__":
    main()
