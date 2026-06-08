# -*- coding: utf-8 -*-
"""
เทรนโมเดล seq2seq 3 หมวด (แพ้ยา / โรคประจำตัว / ประวัติการจ่ายยา) ให้สอดคล้องคอลัมน์ใน result/gemini_extract.csv

ข้อมูลเทรนหลัก: แต่ละแถวใน gemini_extract.csv + ไฟล์ transcript ใน data/ (ชื่อไฟล์ตรงกับคอลัมน์ ชื่อไฟล์)
  เป้าหมาย = ค่าในคอลัมน์ที่สอดคล้องกับไฟล์ JSON แต่ละหมวด (ดูคีย์ คอลัมน์เป้าหมายในCSV ใน train_data/*.json)

ข้อมูลเสริม: อาร์เรย์ "text" ใน JSON — ป้ายกำกับจากฮิวริสติกใน train.py (เหมือนเดิม)

แบ่ง train/validation อัตโนมัติ มี early stopping

ใช้: python train.py

ตัวแปรสภาพแวดล้อม (ไม่บังคับ):
  TRAIN_MT5_MODEL              ค่าเริ่มต้น google/mt5-small
  TRAIN_LR                     learning rate (ค่าเริ่มต้น 3e-5)
  TRAIN_BATCH                  batch ต่ออุปกรณ์ (ค่าเริ่มต้นตาม train.py)
  TRAIN_GRAD_ACCUM             gradient accumulation (ค่าเริ่มต้น 1)
  TRAIN_EPOCHS                 จำนวน epoch สูงสุด
  TRAIN_RATIO                  สัดส่วน train เช่น 0.9
  TRAIN_DATALOADER_NUM_WORKERS งานโหลดข้อมูล (Windows แนะนำ 0)
  TRAIN_FORCE_CPU              ตั้งเป็น 1 เพื่อบังคับ CPU
"""
from __future__ import annotations

import csv
import inspect
import json
import os
import re
import shutil
import sys
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
    set_seed,
)

from gemini_shared import parse_transcript
from result_csv import compact_csv_cell_text

BASE = Path(__file__).resolve().parent
TRAIN_DATA_DIR = BASE / "train_data"
EVAL_DATA_DIR = BASE / "data"
GEMINI_EXTRACT_CSV = BASE / "result" / "gemini_extract.csv"
MODEL_NAME = (os.environ.get("TRAIN_MT5_MODEL") or "google/mt5-small").strip()
MAX_INPUT_LENGTH = int(os.environ.get("TRAIN_MAX_INPUT", "512"))
MAX_TARGET_LENGTH = int(os.environ.get("TRAIN_MAX_TARGET", "128"))

# การเทรน (ปรับด้วย env ได้ — ค่าเริ่มต้นใกล้การ fine-tune T5/mT5 ทั่วไป)
TRAIN_RATIO = float(os.environ.get("TRAIN_RATIO", "0.9"))
NUM_EPOCHS = int(os.environ.get("TRAIN_EPOCHS", "30"))
BATCH_SIZE = int(os.environ.get("TRAIN_BATCH", "8"))
GRADIENT_ACCUMULATION_STEPS = int(os.environ.get("TRAIN_GRAD_ACCUM", "1"))
LEARNING_RATE = float(os.environ.get("TRAIN_LR", "3e-5"))
WARMUP_RATIO = float(os.environ.get("TRAIN_WARMUP_RATIO", "0.08"))
WEIGHT_DECAY = float(os.environ.get("TRAIN_WEIGHT_DECAY", "0.01"))
LABEL_SMOOTHING = float(os.environ.get("TRAIN_LABEL_SMOOTHING", "0.05"))
EARLY_STOPPING_PATIENCE = int(os.environ.get("TRAIN_EARLY_STOP", "4"))
SAVE_TOTAL_LIMIT = int(os.environ.get("TRAIN_SAVE_TOTAL_LIMIT", "2"))
MAX_GRAD_NORM = float(os.environ.get("TRAIN_MAX_GRAD_NORM", "1.0"))
SEED = int(os.environ.get("TRAIN_SEED", "42"))
DATALOADER_NUM_WORKERS = int(os.environ.get("TRAIN_DATALOADER_NUM_WORKERS", "0"))

# 3 หมวด: ไฟล์ใน train_data/ -> โฟลเดอร์ output — คอลัมน์ CSV ที่ใช้เป็นป้ายกำกับครู
CATEGORIES = [
    ("Drug_allergies.json", "output_drug_allergies", "ประวัติการแพ้ยา"),
    ("Pre-existing_medical_conditions.json", "output_conditions", "โรคประจำตัว"),
    ("Medication_history.json", "output_medication_history", "ประวัติการจ่ายยา"),
]

JSON_NAME_TO_GEMINI_COLUMN = {j: col for (j, _, col) in CATEGORIES}


def _seq2seq_training_arguments(**kwargs) -> Seq2SeqTrainingArguments:
    """สร้าง Seq2SeqTrainingArguments โดยกรองพารามิเตอร์ให้เข้ากับ transformers 4.x / 5.x"""
    sig = inspect.signature(Seq2SeqTrainingArguments.__init__)
    param_names = set(sig.parameters)
    if (
        "eval_strategy" in kwargs
        and "eval_strategy" not in param_names
        and "evaluation_strategy" in param_names
    ):
        kwargs = {**kwargs, "evaluation_strategy": kwargs.pop("eval_strategy")}
    if (
        "evaluation_strategy" in kwargs
        and "evaluation_strategy" not in param_names
        and "eval_strategy" in param_names
    ):
        kwargs = {**kwargs, "eval_strategy": kwargs.pop("evaluation_strategy")}
    filtered = {k: v for k, v in kwargs.items() if k in param_names}
    return Seq2SeqTrainingArguments(**filtered)


def _mixed_precision_flags() -> tuple[bool, bool]:
    """คืน (bf16, fp16) — ใช้ bf16 บน GPU รุ่นใหม่ ไม่เซ็ตทั้งคู่พร้อมกัน"""
    if os.environ.get("TRAIN_FORCE_CPU", "").strip().lower() in ("1", "true", "yes"):
        return False, False
    if not torch.cuda.is_available():
        return False, False
    try:
        major, _minor = torch.cuda.get_device_capability()
        if major >= 8:
            return True, False
    except Exception:
        pass
    return False, True


def _normalize_target(s: str) -> str:
    """ตัดช่องว่างซ้ำ และจำกัดความยาว"""
    s = " ".join((s or "").strip().split())
    return s[:MAX_TARGET_LENGTH] if s else "-"


def extract_from_text_conditions(text: str) -> str:
    """ดึงคำสำคัญจากข้อความหมวดโรคประจำตัว (เป็น X, โรค X) ไม่ใช้ keyword"""
    t = text.strip()
    if not t:
        return "-"
    # ไม่มีโรค / ไม่เป็นอะไร / สุขภาพดี
    if re.search(r"ไม่มีโรคประจำตัว|ไม่เป็นอะไร|สุขภาพดี(มาก)?|ไม่มีโรค|ไม่เป็น\s+อะไร|ไม่มีครับ|ไม่มีค่ะ", t):
        return "-"
    # เป็น X (อาจมีหลายอัน: เป็น X และ Y, เป็น X กับ Y)
    out = []
    for m in re.finditer(r"เป็น\s+([^\s,]+(?:\s+[^\s,]+){0,3})", t):
        phrase = m.group(1).strip()
        # ตัดคำลงท้ายที่ไม่ใช่ชื่อโรค
        phrase = re.sub(r"\s+(มา|แล้ว|ครับ|ค่ะ|หลายปี|มานาน|อยู่)$", "", phrase)
        if phrase and phrase not in out:
            out.append(phrase)
    if not out:
        return "-"
    return _normalize_target(", ".join(out))


def extract_from_text_allergies(text: str) -> str:
    """ดึงคำสำคัญจากข้อความหมวดแพ้ยา (แพ้ X) ไม่ใช้ keyword"""
    t = text.strip()
    if not t:
        return "-"
    if re.search(r"ไม่มีประวัติแพ้|ไม่เคยแพ้|ไม่แพ้ยา|ทานได้หมด|ทานยาอะไรก็ได้|แพ้แต่กุ้ง|แพ้เฉพาะอาหาร", t):
        return "-"
    m = re.search(r"แพ้\s+([^\s,]+(?:\s+[^\s,]+){0,2})", t)
    if m:
        phrase = m.group(1).strip()
        phrase = re.sub(r"\s+(ครับ|ค่ะ|ผื่น|บวม|เคย)$", "", phrase)
        return _normalize_target(phrase) if phrase else "-"
    return "-"


def extract_from_text_medication(text: str) -> str:
    """ดึงคำสำคัญจากข้อความหมวดประวัติจ่ายยา (กินยา X, ได้ X, ใช้ X) ไม่ใช้ keyword"""
    t = text.strip()
    if not t:
        return "-"
    if re.search(r"ยังไม่เคย|ไม่เคยได้ยา|ไม่เคยได้ยาจาก|ไม่มีประวัติการจ่ายยา|ไม่เคยจ่ายยาที่นี่", t):
        return "-"
    out = []
    # ได้ X จาก / กิน X / ใช้ X
    for m in re.finditer(r"(?:ได้|กิน|ใช้)\s+([^\s,]+(?:\s+[^\s,]+){0,2})", t):
        phrase = m.group(1).strip()
        phrase = re.sub(r"^(ยาที่|ยาจาก)\s*", "", phrase)
        if phrase and len(phrase) > 1 and phrase not in out:
            out.append(phrase)
    # ระยะเวลา/จำนวน
    for m in re.finditer(r"(\d+\s*(?:วัน|เดือน|ปี|สัปดาห์|ครั้ง|อาทิตย์)|เมื่อวาน|เมื่อ\s*[^\s]+ก่อน|หลายวัน)", t):
        if m.group(1) not in out:
            out.append(m.group(1))
    if not out:
        return "-"
    return _normalize_target(", ".join(out[:5]))


EXTRACTORS = {
    "Drug_allergies.json": extract_from_text_allergies,
    "Pre-existing_medical_conditions.json": extract_from_text_conditions,
    "Medication_history.json": extract_from_text_medication,
}


def _stem_variants(filename: str) -> list[str]:
    """ลองชื่อไฟล์ใน CSV กับไฟล์จริงใน data/"""
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


def load_supervised_from_gemini_csv(
    csv_path: Path, data_dir: Path, target_column: str
) -> tuple[list[str], list[str]]:
    """คู่ (transcript, ค่าคอลัมน์) จาก gemini_extract.csv — distill จากผลครู"""
    if not csv_path.is_file() or not data_dir.is_dir():
        return [], []
    inputs: list[str] = []
    targets: list[str] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            fn = (row.get("ชื่อไฟล์") or "").strip()
            if not fn:
                continue
            path = None
            for cand in _stem_variants(fn):
                p = data_dir / cand
                if p.is_file():
                    path = p
                    break
            if path is None:
                continue
            try:
                body = parse_transcript(str(path)).strip()
            except OSError:
                continue
            if not body:
                continue
            cell = row.get(target_column)
            tgt = _normalize_target(compact_csv_cell_text(cell if cell is not None else "-"))
            inputs.append(body)
            targets.append(tgt)
    return inputs, targets


def _texts_from_train_json(data) -> list[str]:
    if isinstance(data, list):
        return [
            (item.get("text") or "").strip()
            for item in data
            if isinstance(item, dict) and (item.get("text") or "").strip()
        ]
    if isinstance(data, dict) and "text" in data:
        raw = data["text"]
        texts = []
        for s in raw:
            if isinstance(s, str):
                t = s.strip()
            elif isinstance(s, dict):
                t = (s.get("text") or "").strip()
            else:
                t = ""
            if t:
                texts.append(t)
        return texts
    return []


def load_category_data(json_path: Path, json_name: str) -> tuple[list[str], list[str]]:
    """
    รวม (1) คู่จาก gemini_extract.csv + transcript ใน data/
    (2) คู่จาก JSON อาร์เรย์ text + เป้าหมายจากฮิวริสติก
    """
    column = JSON_NAME_TO_GEMINI_COLUMN.get(json_name)
    csv_in: list[str] = []
    csv_tar: list[str] = []
    if column:
        csv_in, csv_tar = load_supervised_from_gemini_csv(
            GEMINI_EXTRACT_CSV, EVAL_DATA_DIR, column
        )
        if csv_in:
            print(f"  [{json_name}] จาก {GEMINI_EXTRACT_CSV.name} ({column}): {len(csv_in)} คู่")

    json_in: list[str] = []
    json_tar: list[str] = []
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        texts = _texts_from_train_json(data)
        extractor = EXTRACTORS.get(json_name)
        if not extractor:
            raise ValueError(f"ไม่มี extractor สำหรับ {json_name}")
        for text in texts:
            json_in.append(text)
            json_tar.append(extractor(text))
        if texts:
            print(f"  [{json_name}] จาก JSON (ฮิวริสติก): {len(texts)} คู่")

    return csv_in + json_in, csv_tar + json_tar


def train_one_category(name_th: str, inputs: list, targets: list, output_dir: Path):
    if not inputs:
        print(f"[ข้าม] {name_th}: ไม่มีข้อมูลในไฟล์")
        return
    # transformers v5+ ไม่มี overwrite_output_dir — ล้างโฟลเดอร์ก่อนเทรนแทน
    if output_dir.exists():
        shutil.rmtree(output_dir)

    set_seed(SEED)
    use_bf16, use_fp16 = _mixed_precision_flags()
    device_s = "cuda" if torch.cuda.is_available() else "cpu"
    if torch.cuda.is_available():
        device_s = f"cuda ({torch.cuda.get_device_name(0)})"
    print(
        f"\n=== เทรน: {name_th} ===\n"
        f"  โมเดล: {MODEL_NAME} | อุปกรณ์: {device_s}\n"
        f"  mixed precision: bf16={use_bf16} fp16={use_fp16}\n"
        f"  lr={LEARNING_RATE} warmup_ratio={WARMUP_RATIO} label_smoothing={LABEL_SMOOTHING}\n"
        f"  grad_accum={GRADIENT_ACCUMULATION_STEPS} max_grad_norm={MAX_GRAD_NORM}"
    )

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)

    def tokenize_fn(examples):
        # ไม่ pad ใน map — ให้ DataCollatorForSeq2Seq pad แบบ dynamic ต่อ batch (ประหยัดหน่วยความจำ)
        model_inputs = tokenizer(
            examples["input_text"],
            max_length=MAX_INPUT_LENGTH,
            truncation=True,
        )
        try:
            labels = tokenizer(
                text_target=examples["target_text"],
                max_length=MAX_TARGET_LENGTH,
                truncation=True,
            )
        except TypeError:
            labels = tokenizer(
                examples["target_text"],
                max_length=MAX_TARGET_LENGTH,
                truncation=True,
            )
        model_inputs["labels"] = labels["input_ids"]
        return model_inputs

    full = Dataset.from_dict({"input_text": inputs, "target_text": targets})
    split = full.train_test_split(test_size=1 - TRAIN_RATIO, seed=SEED)
    train_dataset = split["train"].map(
        tokenize_fn,
        batched=True,
        remove_columns=split["train"].column_names,
        desc="tokenize train",
    )
    eval_dataset = split["test"].map(
        tokenize_fn,
        batched=True,
        remove_columns=split["test"].column_names,
        desc="tokenize eval",
    )

    n_train, n_eval = len(train_dataset), len(eval_dataset)
    batch_size = min(BATCH_SIZE, max(1, n_train // 2))
    eff_batch = batch_size * max(1, GRADIENT_ACCUMULATION_STEPS)
    print(
        f"  train={n_train} eval={n_eval} | per_device_batch={batch_size} "
        f"| effective_batch≈{eff_batch} (× grad_accum)"
    )

    logging_steps = max(1, min(500, n_train // max(eff_batch * 2, 1)))

    arg_kw: dict = {
        "output_dir": str(output_dir),
        "num_train_epochs": NUM_EPOCHS,
        "per_device_train_batch_size": batch_size,
        "per_device_eval_batch_size": max(1, min(batch_size, n_eval)) if n_eval else batch_size,
        "gradient_accumulation_steps": max(1, GRADIENT_ACCUMULATION_STEPS),
        "learning_rate": LEARNING_RATE,
        "lr_scheduler_type": "cosine",
        "warmup_ratio": WARMUP_RATIO,
        "weight_decay": WEIGHT_DECAY,
        "label_smoothing_factor": LABEL_SMOOTHING,
        "logging_steps": logging_steps,
        "logging_first_step": True,
        "log_level": "info",
        "eval_strategy": "epoch",
        "save_strategy": "epoch",
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "save_total_limit": SAVE_TOTAL_LIMIT,
        "max_grad_norm": MAX_GRAD_NORM,
        "bf16": use_bf16,
        "fp16": use_fp16,
        "dataloader_num_workers": DATALOADER_NUM_WORKERS,
        "dataloader_pin_memory": bool(torch.cuda.is_available()),
        "report_to": "none",
        "seed": SEED,
        "disable_tqdm": False,
        "save_safetensors": True,
        "predict_with_generate": False,
    }
    args = _seq2seq_training_arguments(**arg_kw)

    collator = DataCollatorForSeq2Seq(
        tokenizer,
        model=model,
        padding=True,
        pad_to_multiple_of=8 if torch.cuda.is_available() else None,
    )
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
    print(f"เทรนเสร็จ {name_th} -> {output_dir}\n")


def main():
    if not TRAIN_DATA_DIR.exists():
        raise FileNotFoundError(f"ไม่มีโฟลเดอร์ {TRAIN_DATA_DIR}")

    print(
        f"text_classified/train.py | Python {sys.version.split()[0]} | "
        f"torch {torch.__version__} | CUDA ใช้ได้: {torch.cuda.is_available()}",
        flush=True,
    )

    for json_name, output_name, name_th in CATEGORIES:
        json_path = TRAIN_DATA_DIR / json_name
        output_dir = BASE / output_name
        inputs, targets = load_category_data(json_path, json_name)
        train_one_category(name_th, inputs, targets, output_dir)

    print("โฟลเดอร์สำหรับ evaluate:", EVAL_DATA_DIR)


if __name__ == "__main__":
    main()
