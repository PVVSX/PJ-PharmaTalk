# -*- coding: utf-8 -*-
"""
เทรนโมเดล seq2seq ตัวเดียวให้สรุป 6 ช่องพร้อมกัน (เทียบชุดฟิลด์กับ classify_gemini_extract.py)

แนวคิด: knowledge distillation จากผลครูใน result/gemini_extract.csv + ข้อความ transcript จาก data/
- อินพุต: บทสนทนา (รูปแบบเดียวกับที่ parse ใน gemini_shared)
- เป้า: 6 ค่าคั่นด้วยตัวคั่นคงที่ (FIELD_SEP) ตามลำดับคอลัมน์ใน CSV

ใช้:
  python train_extract_full.py

ตัวแปรสภาพแวดล้อม (ไม่บังคับ):
  EXTRACT_MT5_MODEL   ค่าเริ่มต้น google/mt5-base (ถ้า VRAM ไม่พอลอง google/mt5-small)
  EXTRACT_TRAIN_CSV   ค่าเริ่มต้น text_classified/result/gemini_extract.csv
  EXTRACT_OUTPUT_DIR  ค่าเริ่มต้น text_classified/output_extract_full
  EXTRACT_DATA_DIR    ค่าเริ่มต้น text_classified/data
"""
from __future__ import annotations

import csv
import os
import re
import shutil
from pathlib import Path

import torch
from datasets import Dataset
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    EarlyStoppingCallback,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
)

from gemini_shared import parse_transcript
from result_csv import compact_csv_cell_text, normalize_visit_purpose_cell

BASE = Path(__file__).resolve().parent

DEFAULT_CSV = BASE / "result" / "gemini_extract.csv"
DEFAULT_DATA = BASE / "data"
DEFAULT_OUT = BASE / "output_extract_full"
DEFAULT_MODEL = "google/mt5-base"

# ตัวคั่นฟิลด์ในเป้าเทรน — แทรกในข้อความป้ายกันปนกับเนื้อหาไทยทั่วไป
FIELD_SEP = " ||| "

CSV_FIELD_ORDER = (
    "ประเภท",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
)

MAX_INPUT_LENGTH = int(os.environ.get("EXTRACT_MAX_INPUT", "768"))
MAX_TARGET_LENGTH = int(os.environ.get("EXTRACT_MAX_TARGET", "512"))

TRAIN_RATIO = float(os.environ.get("EXTRACT_TRAIN_RATIO", "0.9"))
NUM_EPOCHS = int(os.environ.get("EXTRACT_EPOCHS", "25"))
BATCH_SIZE = int(os.environ.get("EXTRACT_BATCH", "2"))
GRAD_ACCUM = int(os.environ.get("EXTRACT_GRAD_ACCUM", "8"))
LEARNING_RATE = float(os.environ.get("EXTRACT_LR", "3e-5"))
WARMUP_RATIO = 0.08
WEIGHT_DECAY = 0.01
EARLY_STOPPING_PATIENCE = int(os.environ.get("EXTRACT_EARLY_STOP", "3"))
SAVE_TOTAL_LIMIT = 1
MAX_GRAD_NORM = 1.0
SEED = 42

INPUT_PREFIX = "สรุปข้อมูลจากบทสนทนาร้านยาเป็นหกช่องตามลำดับ: "


def _sanitize_sep_piece(s: str) -> str:
    t = compact_csv_cell_text(s)
    if FIELD_SEP in t:
        t = t.replace(FIELD_SEP.strip(), " ").replace("|||", " ")
    return t


def row_to_target(row: dict) -> str:
    pieces = []
    for key in CSV_FIELD_ORDER:
        raw = row.get(key) or "-"
        if key == "ประเภท":
            v = normalize_visit_purpose_cell(raw)
        else:
            v = _sanitize_sep_piece(str(raw))
        pieces.append(v)
    return FIELD_SEP.join(pieces)


def _stem_variants(filename: str) -> list[str]:
    """ลองชื่อไฟล์ใน CSV กับไฟล์จริงใน data (เช่น dialogue_0005 vs dialogue_005)."""
    name = filename.strip()
    out = [name]
    if not name.lower().endswith(".txt"):
        return out
    stem = name[:-4]
    m = re.match(r"^(dialogue_)(0+)(\d+)$", stem, re.I)
    if m:
        prefix, _zeros, num = m.group(1), m.group(2), m.group(3)
        out.append(f"{prefix}{num}.txt")
        if len(num) > 1:
            out.append(f"{prefix}{num.zfill(4)}.txt")
    return list(dict.fromkeys(out))


def load_pairs(csv_path: Path, data_dir: Path) -> tuple[list[str], list[str]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"ไม่พบไฟล์ครู (CSV): {csv_path}")
    inputs: list[str] = []
    targets: list[str] = []
    skipped = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = (row.get("ชื่อไฟล์") or "").strip()
            if not fn:
                skipped += 1
                continue
            transcript_path = None
            for cand in _stem_variants(fn):
                p = data_dir / cand
                if p.is_file():
                    transcript_path = p
                    break
            if transcript_path is None:
                skipped += 1
                continue
            try:
                body = parse_transcript(str(transcript_path)).strip()
            except OSError:
                skipped += 1
                continue
            if not body:
                skipped += 1
                continue
            tgt = row_to_target(row)
            if not tgt.strip():
                skipped += 1
                continue
            inputs.append(INPUT_PREFIX + body)
            targets.append(tgt)
    if not inputs:
        raise RuntimeError(
            f"ไม่มีคู่ข้อมูลที่ใช้เทรนได้ (ข้าม {skipped} แถว) — ตรวจสอบ path CSV และโฟลเดอร์ data"
        )
    print(f"โหลดคู่ข้อมูลเทรน: {len(inputs)} แถว (ข้ามแถวที่ไม่มีไฟล์/ข้อความว่าง: {skipped})")
    return inputs, targets


def train_main():
    csv_path = Path(os.environ.get("EXTRACT_TRAIN_CSV", str(DEFAULT_CSV))).resolve()
    data_dir = Path(os.environ.get("EXTRACT_DATA_DIR", str(DEFAULT_DATA))).resolve()
    output_dir = Path(os.environ.get("EXTRACT_OUTPUT_DIR", str(DEFAULT_OUT))).resolve()
    model_name = (os.environ.get("EXTRACT_MT5_MODEL") or DEFAULT_MODEL).strip()

    inputs, targets = load_pairs(csv_path, data_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    def tokenize_fn(examples):
        model_inputs = tokenizer(
            examples["input_text"],
            max_length=MAX_INPUT_LENGTH,
            truncation=True,
            padding="max_length",
            return_tensors=None,
        )
        labels = tokenizer(
            examples["target_text"],
            max_length=MAX_TARGET_LENGTH,
            truncation=True,
            padding="max_length",
            return_tensors=None,
        )
        model_inputs["labels"] = [
            [(x if x != tokenizer.pad_token_id else -100) for x in seq]
            for seq in labels["input_ids"]
        ]
        return model_inputs

    full = Dataset.from_dict({"input_text": inputs, "target_text": targets})
    split = full.train_test_split(test_size=1 - TRAIN_RATIO, seed=SEED)
    train_dataset = split["train"].map(
        tokenize_fn, batched=True, remove_columns=split["train"].column_names
    )
    eval_dataset = split["test"].map(
        tokenize_fn, batched=True, remove_columns=split["test"].column_names
    )

    n_train, n_eval = len(train_dataset), len(eval_dataset)
    batch_size = max(1, min(BATCH_SIZE, n_train // 2))
    print(f"  โมเดล: {model_name} | train={n_train} eval={n_eval} batch={batch_size} grad_accum={GRAD_ACCUM}")

    args = Seq2SeqTrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        label_smoothing_factor=0.08,
        warmup_ratio=WARMUP_RATIO,
        weight_decay=WEIGHT_DECAY,
        logging_steps=max(1, n_train // (batch_size * GRAD_ACCUM * 4)),
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=SAVE_TOTAL_LIMIT,
        max_grad_norm=MAX_GRAD_NORM,
        fp16=torch.cuda.is_available(),
        report_to="none",
        seed=SEED,
        predict_with_generate=False,
    )
    collator = DataCollatorForSeq2Seq(tokenizer, model=model, padding=True)
    trainer = Seq2SeqTrainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=collator,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=EARLY_STOPPING_PATIENCE)],
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    print(f"บันทึกโมเดลเต็ม 6 ช่องแล้ว -> {output_dir}")
    print("รัน inference: python classify_model_extract.py")


if __name__ == "__main__":
    train_main()
