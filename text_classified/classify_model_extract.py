# -*- coding: utf-8 -*-
"""
สรุปหกช่องจาก transcript แบบเดียวกับ classify_gemini_extract.py โดยใช้โมเดล local

โหมดหลัก (แนะนำ — หลังรัน train_extract_full.py):
  โมเดลเดียวใน output_extract_full/ สรุปครบ ประเภท / แพ้ยา / โรค / จ่ายยา / บันทึกทางการแพทย์ / คำแนะนำจากเภสัช
  เทรนจากผลครูใน result/gemini_extract.csv (distillation)

โหมดเดิม (ถ้ายังไม่มี output_extract_full):
  โมเดล 3 ตัวใน output_drug_allergies, output_conditions, output_medication_history
  — ช่อง ประเภท / บันทึกทางการแพทย์ / คำแนะนำจากเภสัช จะเป็น "-"

อินพุต: ไฟล์ .txt (รูปแบบ timestamp ASR หรือสคริปต์ เภสัชกร:/คนไข้:) ผ่าน gemini_shared.parse_transcript
ผลรวมค่าเริ่มต้น: text_classified/result/model_extract.csv
อินพุตค่าเริ่มต้น (ไม่ระบุ path): text_classified/data/*.txt — เหมาะทดลองก่อนรันทั้งชุด

ใช้: python classify_model_extract.py
     python classify_model_extract.py --limit 20
     python classify_model_extract.py --output result/model_extract.csv
     python classify_model_extract.py path/to/file.txt
     python classify_model_extract.py path/to/folder
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from gemini_shared import parse_transcript
from result_csv import (
    compact_csv_cell_text,
    model_extract_csv_path,
    normalize_visit_purpose_cell,
    upsert_result_csv,
)

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"

# --- โมเดลเต็ม 6 ช่อง (train_extract_full.py) ---
FULL_MODEL_DIR = BASE / "output_extract_full"
FIELD_SEP = " ||| "
INPUT_PREFIX = "สรุปข้อมูลจากบทสนทนาร้านยาเป็นหกช่องตามลำดับ: "

EXTRACT_FIELD_KEYS = (
    "ประเภท",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
)

MAX_INPUT_FULL = 768
MAX_TARGET_FULL = 512
MAX_INPUT_LEGACY = 512
MAX_TARGET_LEGACY = 128

# --- โมเดลแยก 3 หมวด (train.py เดิม) ---
MODELS = [
    (BASE / "output_drug_allergies", "ประวัติการแพ้ยา"),
    (BASE / "output_conditions", "โรคประจำตัว"),
    (BASE / "output_medication_history", "ประวัติการจ่ายยา"),
]

EXTRA_ID_RE = re.compile(r"<extra_id_\d+>\s*")

_WEIGHT_FILENAMES = ("model.safetensors", "pytorch_model.bin")


def _resolve_seq2seq_model_dir(model_dir: Path) -> Path:
    """คืนโฟลเดอร์ที่มี config + weights + tokenizer — ถ้า root ไม่ครบให้ใช้ checkpoint-* ล่าสุด"""
    model_dir = Path(model_dir)
    if not model_dir.is_dir():
        return model_dir

    def has_weights(p: Path) -> bool:
        return any((p / w).is_file() for w in _WEIGHT_FILENAMES)

    def has_tokenizer(p: Path) -> bool:
        if not (p / "tokenizer_config.json").is_file():
            return False
        return (p / "tokenizer.json").is_file() or (p / "spiece.model").is_file()

    def is_ready(p: Path) -> bool:
        return (p / "config.json").is_file() and has_weights(p) and has_tokenizer(p)

    if is_ready(model_dir):
        return model_dir

    checkpoints: list[tuple[int, Path]] = []
    for child in model_dir.glob("checkpoint-*"):
        if not child.is_dir():
            continue
        suffix = child.name.split("-", 1)[-1]
        try:
            step = int(suffix)
        except ValueError:
            step = -1
        checkpoints.append((step, child))
    for _step, child in sorted(checkpoints, key=lambda x: -x[0]):
        if is_ready(child):
            return child
    return model_dir


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def clean_keyword_output(raw: str) -> str:
    s = EXTRA_ID_RE.sub("", raw).strip()
    s = " ".join(s.split())
    if not s or s in (".", "。"):
        return "-"
    words = s.split()
    if len(words) >= 2:
        c = Counter(words)
        most_count = c.most_common(1)[0][1]
        if most_count >= 2 and most_count >= len(words) / 2:
            return "-"
    return s if len(s) <= 500 else s[:500].rsplit(" ", 1)[0] or "-"


def predict_keywords(transcript_text: str, tokenizer, model, device: torch.device) -> str:
    inputs = tokenizer(
        transcript_text,
        max_length=MAX_INPUT_LEGACY,
        truncation=True,
        padding="max_length",
        return_tensors="pt",
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}
    out = model.generate(
        **inputs,
        max_length=MAX_TARGET_LEGACY,
        num_beams=4,
        early_stopping=True,
    )
    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
    return clean_keyword_output(decoded)


def classify_legacy(transcript_text: str, tokenizers_models: list, device: torch.device) -> dict:
    """โมเดลทั้งสามเป็น seq2seq แบบเดียวกัน (เทรนจากคอลัมน์ CSV + ข้อความใน train_data)"""
    result = {"ประวัติการแพ้ยา": "", "โรคประจำตัว": "", "ประวัติการจ่ายยา": ""}
    for (_, name), (tok, model) in zip(MODELS, tokenizers_models):
        result[name] = predict_keywords(transcript_text, tok, model, device)
    return result


def decode_six_fields(raw: str) -> dict[str, str]:
    s = (raw or "").strip()
    parts = [p.strip() for p in s.split(FIELD_SEP)]
    while len(parts) < 6:
        parts.append("-")
    if len(parts) > 6:
        parts = parts[:5] + [FIELD_SEP.join(parts[5:])]
    out = {}
    for k, v in zip(EXTRACT_FIELD_KEYS, parts):
        out[k] = compact_csv_cell_text(v)
    out["ประเภท"] = normalize_visit_purpose_cell(out.get("ประเภท", "-"))
    return out


def predict_full_six(
    transcript_text: str, tokenizer, model, device: torch.device
) -> dict[str, str]:
    input_str = INPUT_PREFIX + (transcript_text or "").strip()
    inputs = tokenizer(
        input_str,
        max_length=MAX_INPUT_FULL,
        truncation=True,
        padding="max_length",
        return_tensors="pt",
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}
    out = model.generate(
        **inputs,
        max_length=MAX_TARGET_FULL,
        num_beams=5,
        length_penalty=1.0,
        early_stopping=True,
        no_repeat_ngram_size=4,
    )
    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
    return decode_six_fields(decoded)


def _full_model_ready() -> bool:
    cfg = FULL_MODEL_DIR / "config.json"
    return cfg.is_file()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="สรุป transcript ด้วยโมเดล local แล้วบันทึกลง CSV (ค่าเริ่มต้น: data/ -> result/model_extract.csv)"
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="ไฟล์ .txt หรือโฟลเดอร์ที่มี .txt (ถ้าไม่ใส่ ใช้โฟลเดอร์ data/ ข้างสคริปต์)",
    )
    p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="จำกัดจำนวนไฟล์ .txt หลังเรียงชื่อ (ใช้ทดลอง; ใช้ได้เมื่อระบุโฟลเดอร์หรือโหมดค่าเริ่มต้น data/)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="พาธ CSV ผลลัพธ์ (ค่าเริ่มต้น: result/model_extract.csv ภายใต้โฟลเดอร์ text_classified)",
    )
    return p.parse_args()


def main():
    args = _parse_args()
    device = _device()
    use_full = _full_model_ready()

    if use_full:
        tokenizer = AutoTokenizer.from_pretrained(str(FULL_MODEL_DIR))
        model = AutoModelForSeq2SeqLM.from_pretrained(str(FULL_MODEL_DIR))
        model.to(device)
        model.eval()
        tokenizers_models = None
        print(f"ใช้โมเดลเต็ม 6 ช่อง: {FULL_MODEL_DIR.name} (device={device})\n")
    else:
        missing = [d for d, _ in MODELS if not Path(d).exists()]
        if missing:
            print("ยังไม่มีโมเดลสำหรับสรุปแบบเดียวกับ Gemini")
            print("  แบบเต็ม 6 ช่อง: รัน python train_extract_full.py (สร้าง output_extract_full/)")
            print("  หรือแบบ 3 ช่องเดิม: รัน python train.py — โฟลเดอร์ที่ขาด:", missing)
            sys.exit(1)
        tokenizers_models = []
        for model_dir, label in MODELS:
            resolved = _resolve_seq2seq_model_dir(Path(model_dir))
            if resolved != Path(model_dir):
                try:
                    rel = resolved.relative_to(BASE)
                except ValueError:
                    rel = resolved
                print(f"  [{label}] โหลดจาก {rel} (ไม่มีไฟล์ครบที่โฟลเดอร์หลัก)")
            tokenizer = AutoTokenizer.from_pretrained(str(resolved))
            model = AutoModelForSeq2SeqLM.from_pretrained(str(resolved))
            model.to(device)
            model.eval()
            tokenizers_models.append((tokenizer, model))
        print(f"ใช้โมเดลแยก 3 หมวด (legacy) | device={device}\n")

    if args.path:
        path_arg = Path(args.path).expanduser().resolve()
        if path_arg.is_file():
            files = [path_arg]
        elif path_arg.is_dir():
            files = sorted(path_arg.glob("*.txt"))
        else:
            files = [path_arg] if path_arg.exists() else []
        source_dir = path_arg if path_arg.is_dir() else path_arg.parent
    else:
        source_dir = DATA_DIR.resolve()
        files = sorted(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []

    if args.limit is not None and args.limit < 1:
        print("--limit ต้องเป็นจำนวนเต็มบวก")
        sys.exit(2)
    if args.limit is not None and len(files) > 1:
        files = files[: args.limit]
    elif args.limit is not None and len(files) == 1:
        pass

    if not files:
        print("ไม่พบไฟล์ .txt — ใช้: python classify_model_extract.py [โฟลเดอร์หรือไฟล์]")
        print("ค่าเริ่มต้นอ่านจาก:", DATA_DIR.resolve())
        sys.exit(1)

    if args.output:
        raw_out = Path(args.output).expanduser()
        out_csv = raw_out.resolve() if raw_out.is_absolute() else (BASE / raw_out).resolve()
    else:
        out_csv = model_extract_csv_path(BASE)

    print(f"ใช้ไฟล์จาก: {source_dir}")
    print(f"จำนวน {len(files)} ไฟล์")
    print(f"บันทึกผลที่: {out_csv}\n")

    csv_rows = []
    for f in files:
        try:
            text = parse_transcript(str(f)).strip()
        except Exception as e:
            print(f"[ข้าม] {f.name}: {e}")
            continue
        if not text:
            print(f"[ข้าม] {f.name}: ไม่มีข้อความใน transcript")
            continue

        if use_full:
            out = predict_full_six(text, tokenizer, model, device)
        else:
            leg = classify_legacy(text, tokenizers_models, device)
            out = {
                "ประเภท": "-",
                "ประวัติการแพ้ยา": leg["ประวัติการแพ้ยา"],
                "โรคประจำตัว": leg["โรคประจำตัว"],
                "ประวัติการจ่ายยา": leg["ประวัติการจ่ายยา"],
                "บันทึกทางการแพทย์": "-",
                "คำแนะนำจากเภสัช": "-",
            }

        print("---", f.name, "---")
        for k in EXTRACT_FIELD_KEYS:
            print(f"{k}: {out[k]}")
        print()
        csv_rows.append(
            {
                "ชื่อไฟล์": f.name,
                **{k: out[k] for k in EXTRACT_FIELD_KEYS},
            }
        )

    if csv_rows:
        upsert_result_csv(out_csv, csv_rows)
        print(f"บันทึกผลรวมแล้ว: {out_csv}")


if __name__ == "__main__":
    main()
