# -*- coding: utf-8 -*-
"""
ใช้โมเดล 3 ตัวที่เทรนแล้ว (จับ keyword ต่อหมวด) fill 3 ช่อง จาก transcript
- อินพุต: ไฟล์ .txt จากโฟลเดอร์ data/ (text_classified/data)
- ผลรวม: บันทึก merge ลง text_classified/result/result.csv (คอลัมน์ ชื่อไฟล์ + 3 ช่อง)

ใช้: python classify.py                    -> รันทุกไฟล์ .txt ใน data/
     python classify.py path/to/file.txt    -> รันไฟล์เดียว
     python classify.py path/to/folder      -> รันทุก .txt ในโฟลเดอร์นั้น
"""
import re
import sys
from collections import Counter
from pathlib import Path

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from result_csv import result_csv_path, upsert_result_csv

BASE = Path(__file__).resolve().parent
# โฟลเดอร์ที่ใช้ classify: ไฟล์ transcript ทั้งหมดใน data/
DATA_DIR = BASE / "data"
MAX_INPUT_LENGTH = 512
MAX_TARGET_LENGTH = 128

# โมเดล 3 หมวด (ตรงกับ train.py)
# Drug_allergies: อินพุต = บริบท + คำที่พบ, เอาต์พุต = "แพ้จริง" หรือ "แค่พูดเฉยๆ"
MODELS = [
    (BASE / "output_drug_allergies", "ประวัติการแพ้ยา"),
    (BASE / "output_conditions", "โรคประจำตัว"),
    (BASE / "output_medication_history", "ประวัติการจ่ายยา"),
]


# โทเค็นพิเศษของ T5/mT5 ที่อาจโผล่ในผล generate
EXTRA_ID_RE = re.compile(r"<extra_id_\d+>\s*")


def extract_allergy_keyword_from_text(text: str) -> str:
    """ดึงคำ/วลีหลัง 'แพ้' ใน transcript (ใช้เป็น 'คำที่พบ' สำหรับโมเดลแพ้ยา)"""
    t = (text or "").strip()
    if not t:
        return "-"
    m = re.search(r"แพ้\s+([^\s,]+(?:\s+[^\s,]+){0,3})", t)
    if m:
        phrase = m.group(1).strip()
        phrase = re.sub(r"\s+(ครับ|ค่ะ|ผื่น|บวม|เคย|มาก|แล้ว)$", "", phrase)
        phrase = " ".join(phrase.split())
        return phrase[:128] if phrase else "-"
    return "-"


def clean_keyword_output(raw: str) -> str:
    """ลบ extra_id token และผลที่ไม่มีความหมาย ใช้ - แทน"""
    s = EXTRA_ID_RE.sub("", raw).strip()
    s = " ".join(s.split())
    if not s or s in (".", "。"):
        return "-"
    words = s.split()
    # ผลซ้ำคำ/วลีเดิม (เช่น "ครับ ครับ ครับ" หรือ "หกสิบแปดโล หกสิบแปดโล") ถือว่าไม่มีความหมาย
    if len(words) >= 2:
        c = Counter(words)
        most_count = c.most_common(1)[0][1]
        if most_count >= 2 and most_count >= len(words) / 2:
            return "-"
    return s if len(s) <= 500 else s[:500].rsplit(" ", 1)[0] or "-"


def parse_transcript(path: str) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    parts = []
    for line in lines:
        line = line.strip()
        m = re.match(r"\[\s*[\d.]+s\s*-\s*[\d.]+s\s*\]\s*ผู้พูด\s*\d+\s*:\s*(.+)", line)
        if m:
            t = m.group(1).strip()
            if t and t != "(ไม่มีข้อความ)":
                parts.append(t)
    return " ".join(parts)


def predict_keywords(transcript_text: str, tokenizer, model) -> str:
    """รันโมเดลหนึ่งตัว ได้ข้อความ keywords (หนึ่งช่อง)"""
    inputs = tokenizer(
        transcript_text,
        max_length=MAX_INPUT_LENGTH,
        truncation=True,
        padding="max_length",
        return_tensors="pt",
    )
    out = model.generate(
        **inputs,
        max_length=MAX_TARGET_LENGTH,
        num_beams=4,
        early_stopping=True,
    )
    decoded = tokenizer.decode(out[0], skip_special_tokens=True)
    return clean_keyword_output(decoded)


def predict_allergy_real_or_mention(transcript_text: str, tokenizer, model) -> str:
    """โมเดลแพ้ยา: อินพุต = บริบท + คำที่พบ → เอาต์พุต แพ้จริง/แค่พูดเฉยๆ ถ้าแพ้จริงค่อยส่งคำที่พบออก"""
    keyword = extract_allergy_keyword_from_text(transcript_text)
    if keyword == "-":
        return "-"
    input_str = f"บริบท: {transcript_text} คำที่พบ: {keyword}"
    inputs = tokenizer(
        input_str,
        max_length=MAX_INPUT_LENGTH,
        truncation=True,
        padding="max_length",
        return_tensors="pt",
    )
    out = model.generate(
        **inputs,
        max_length=MAX_TARGET_LENGTH,
        num_beams=2,
        early_stopping=True,
    )
    decoded = tokenizer.decode(out[0], skip_special_tokens=True).strip()
    if "แพ้จริง" in decoded:
        return keyword
    return "-"


def classify(transcript_text: str, tokenizers_models: list) -> dict:
    """รัน 3 โมเดล แยกช่อง ได้ dict 3 ช่อง"""
    result = {"ประวัติการแพ้ยา": "", "โรคประจำตัว": "", "ประวัติการจ่ายยา": ""}
    for i, ((_, name), (tok, model)) in enumerate(zip(MODELS, tokenizers_models)):
        if i == 0:
            result[name] = predict_allergy_real_or_mention(transcript_text, tok, model)
        else:
            result[name] = predict_keywords(transcript_text, tok, model)
    return result


def main():
    missing = [d for d, _ in MODELS if not Path(d).exists()]
    if missing:
        print("ยังไม่มีโมเดล กรุณารัน train.py ก่อน โฟลเดอร์ที่ขาด:", missing)
        sys.exit(1)

    tokenizers_models = []
    for model_dir, _ in MODELS:
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        model = AutoModelForSeq2SeqLM.from_pretrained(str(model_dir))
        tokenizers_models.append((tokenizer, model))

    # กำหนดไฟล์ที่ใช้ classify: ไม่ใส่ path = ใช้ทุกไฟล์จาก data/
    if len(sys.argv) > 1:
        path_arg = Path(sys.argv[1])
        if path_arg.is_file():
            files = [path_arg]
        elif path_arg.is_dir():
            files = sorted(path_arg.glob("*.txt"))
        else:
            files = [path_arg] if path_arg.exists() else []
        source_dir = path_arg if path_arg.is_dir() else path_arg.parent
    else:
        # ค่าเริ่มต้น: ใช้ไฟล์จากโฟลเดอร์ data/
        source_dir = DATA_DIR
        files = sorted(DATA_DIR.glob("*.txt")) if DATA_DIR.exists() else []

    if not files:
        print("ใช้: python classify.py  หรือ  python classify.py <ไฟล์หรือโฟลเดอร์>")
        print("ค่าเริ่มต้น: ใช้ไฟล์จากโฟลเดอร์ data/")
        sys.exit(1)

    print(f"ใช้ไฟล์จาก: {source_dir}")
    print(f"จำนวน {len(files)} ไฟล์\n")

    csv_rows = []
    out_csv = result_csv_path(BASE)
    for f in files:
        try:
            text = parse_transcript(str(f))
        except Exception as e:
            print(f"[ข้าม] {f.name}: {e}")
            continue
        out = classify(text, tokenizers_models)
        print("---", f.name, "---")
        print("ประวัติการแพ้ยา:", out["ประวัติการแพ้ยา"])
        print("โรคประจำตัว:", out["โรคประจำตัว"])
        print("ประวัติการจ่ายยา:", out["ประวัติการจ่ายยา"])
        print()
        csv_rows.append(
            {
                "ชื่อไฟล์": f.name,
                "ประเภท": "-",
                "ประวัติการแพ้ยา": out["ประวัติการแพ้ยา"],
                "โรคประจำตัว": out["โรคประจำตัว"],
                "ประวัติการจ่ายยา": out["ประวัติการจ่ายยา"],
                "บันทึกทางการแพทย์": "-",
                "คำแนะนำจากเภสัช": "-",
            }
        )

    if csv_rows:
        upsert_result_csv(out_csv, csv_rows)
        print(f"บันทึกผลรวมแล้ว: {out_csv}")


if __name__ == "__main__":
    main()
