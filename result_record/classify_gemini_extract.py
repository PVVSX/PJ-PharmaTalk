# -*- coding: utf-8 -*-
"""
เวอร์ชัน 2: ใช้ Gemini 2.5 Flash สรุปจากบทสนทนา
- ประวัติการแพ้ยา / โรคประจำตัว / ประวัติการจ่ายยา (เฉพาะอดีต — ไม่รวมยาที่กำลังจะจ่ายในครั้งนี้)
- บันทึกทางการแพทย์ (healthcare note): เฉพาะประเด็นทางการแพทย์ที่เกี่ยวกับการพิจารณาจ่ายยา ตัดบทสนทนาทั่วไปออก
- ประเภท: จากบทสนทนาในไฟล์ — คนไข้มาซื้อยา / มาปรึกษา / ทั้งคู่ (เขียนเป็นค่าเดียวจากสามค่านี้ หรือ "-" ถ้าไม่ชัด)
- คำแนะนำจากเภสัช: หลังจากนี้ควรทำอะไร โดยเฉพาะ **ยาแต่ละตัวกินตอนไหน** (เช้า/กลางวัน/เย็น/ก่อนนอน ก่อนหรือหลังอาหาร ทุกกี่ชั่วโมง) ตามที่เภสัชกรหรือแพทย์ในบทสนทนาพูด

ต้องตั้ง GEMINI_API_KEY (หรือ GOOGLE_API_KEY)

อินพุต: ทุกไฟล์ *.txt ในโฟลเดอร์ย่อยของ `data/` — เลือกได้ตอนเริ่ม (เมนู) หรือ `--from-data <ชื่อโฟลเดอร์>` / ตั้ง `GEMINI_TEXT_INPUT_SUBDIR` (ค่าเริ่มต้นเมื่อไม่โต้ตอบ: `text`)
ผลรวมตามแหล่งอินพุต: `data/text` → `report/text_to_form/` | `data/text_from_speech` → `report/speech_to_form/`
   | `data/บท500_split` → `report/500/`
   (gemini_extract.csv, reports/, timing_log.tsv, session_summary.txt)

**text → form** เท่านั้น (ไม่รันเสียง) — ถอดเสียงแยก: `speech_to_text.py` จาก `data/voice/*.wav` → `data/text_from_speech/`
ข้ามไฟล์ที่ชื่อตรงกับแถวใน gemini_extract.csv แล้ว (ไม่เรียก API ซ้ำ)
ถ้าโดนกรองอินพุต (PROHIBITED_CONTENT) จะลองตัดท่อนตามบรรทัดผู้พูดทีละท่อน/คู่ท่อนจนกว่าจะประมวลผลได้
ถ้าไฟล์ใด error อื่น (JSON ผิด ฯลฯ) จะ [ข้าม] แล้วทำไฟล์ถัดไป — ไม่หยุดทั้งชุด

ถ้าเจอ 429 / quota: รอแล้วลองใหม่อัตโนมัติ (ตั้ง GEMINI_RATE_LIMIT_RETRIES ค่าเริ่มต้น 6,
GEMINI_RATE_LIMIT_BASE_SEC ค่าเริ่มต้น 20 วินาที) — ลดชนขีดจำกัด: GEMINI_PAUSE_BETWEEN_FILES_SEC=2
ข้อความ gRPC "ALTS creds ignored" = ปกติเมื่อไม่รันบน GCP (ไม่เกี่ยวกับ 429)

ใช้:
  python classify_gemini_extract.py
  python classify_gemini_extract.py --from-data text_from_speech
  python classify_gemini_extract.py --from-data บท500_split   # ผลใน report/500/
  python classify_gemini_extract.py -d text
  python classify_gemini_extract.py path/ไฟล์.txt
  python classify_gemini_extract.py path/โฟลเดอร์
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ลด log gRPC เช่น "ALTS creds ignored" เมื่อไม่รันบน GCP (ไม่กระทบการเรียก API)
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GLOG_minloglevel", "2")

# --- paths ---
BASE = Path(__file__).resolve().parent
DATA_ROOT = (BASE / "data").resolve()
DEFAULT_TEXT_SUBDIR = "text"


def resolve_report_subdir(source_dir: Path) -> str:
    """แมปโฟลเดอร์อินพุตใต้ data/ → ชื่อโฟลเดอร์ภายใต้ report/."""
    try:
        rel = source_dir.resolve().relative_to(DATA_ROOT.resolve())
    except ValueError:
        return "text_to_form"
    head = rel.parts[0] if rel.parts else ""
    if head == "text":
        return "text_to_form"
    if head == "text_from_speech":
        return "speech_to_form"
    if head == "บท500_split":
        return "500"
    return "text_to_form"


def safe_data_subdir(name: str) -> Path:
    """ชื่อโฟลเดอร์เดียวใต้ data/ (กันหลุดออกนอก data)."""
    seg = Path(name.strip()).name
    if not seg or seg in (".", ".."):
        raise SystemExit(f"ชื่อโฟลเดอร์ไม่ถูกต้อง: {name!r}")
    out = (DATA_ROOT / seg).resolve()
    try:
        out.relative_to(DATA_ROOT.resolve())
    except ValueError:
        raise SystemExit(f"โฟลเดอร์ต้องอยู่ภายใต้ {DATA_ROOT}") from None
    return out


def list_txt_files_in_dir(d: Path) -> list[Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.txt") if p.is_file())


def discover_data_subdirs() -> list[tuple[Path, int]]:
    """โฟลเดอร์ย่อยของ data/ กับจำนวนไฟล์ .txt"""
    if not DATA_ROOT.is_dir():
        return []
    rows: list[tuple[Path, int]] = []
    for p in sorted(DATA_ROOT.iterdir()):
        if not p.is_dir():
            continue
        n = sum(1 for _ in p.glob("*.txt"))
        rows.append((p, n))
    return rows


def prompt_pick_data_subdir() -> Path:
    rows = discover_data_subdirs()
    if not rows:
        raise SystemExit(f"ไม่พบโฟลเดอร์ย่อยใน {DATA_ROOT}")
    print("เลือกโฟลเดอร์อินพุตภายใต้ data/ (ไฟล์ *.txt):")
    for i, (p, n) in enumerate(rows, start=1):
        print(f"  [{i}] {p.name}/  ({n} ไฟล์ .txt)")
    default_idx = next(
        (i for i, (p, _) in enumerate(rows, start=1) if p.name == DEFAULT_TEXT_SUBDIR),
        1,
    )
    default_name = rows[default_idx - 1][0].name
    print(f"  (Enter = [{default_idx}] {default_name}/)")
    try:
        line = input("หมายเลข: ").strip()
    except EOFError:
        line = ""
    if not line:
        return rows[default_idx - 1][0]
    try:
        k = int(line)
    except ValueError:
        raise SystemExit(f"ไม่ใช่ตัวเลข: {line!r}") from None
    if k < 1 or k > len(rows):
        raise SystemExit(f"เลขต้องอยู่ระหว่าง 1–{len(rows)}")
    return rows[k - 1][0]


def parse_cli_argv(argv: list[str]) -> tuple[str | None, list[str]]:
    """คืน (ชื่อโฟลเดอร์จาก --from-data, path ที่เหลือ)."""
    rest: list[str] = []
    from_data: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--from-data", "-d"):
            if i + 1 >= len(argv):
                raise SystemExit(f"ใช้: {a} <ชื่อโฟลเดอร์ใต้ data/>")
            from_data = argv[i + 1]
            i += 2
            continue
        if a in ("--help", "-h"):
            _print_cli_help()
            raise SystemExit(0)
        rest.append(a)
        i += 1
    return from_data, rest


def _print_cli_help() -> None:
    print(
        "classify_gemini_extract.py — สรุปบทสนทนาเป็น CSV (text → form)\n\n"
        "  python classify_gemini_extract.py\n"
        "      ถามโฟลเดอร์ภายใต้ data/ (หรืออ่าน GEMINI_TEXT_INPUT_SUBDIR เมื่อไม่มี TTY)\n"
        "  python classify_gemini_extract.py --from-data text_from_speech\n"
        "  python classify_gemini_extract.py --from-data บท500_split   # → report/500/\n"
        "  python classify_gemini_extract.py -d text\n"
        "  python classify_gemini_extract.py <ไฟล์.txt | โฟลเดอร์>\n\n"
        f"โฟลเดอร์ data: {DATA_ROOT}"
    )


def filter_txt_files(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.suffix.lower() == ".txt" and p.is_file()]


# --- Gemini API ---
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_KEY_FILE = BASE / ".gemini_api_key"


def _read_key_from_file() -> str:
    if not GEMINI_KEY_FILE.is_file():
        return ""
    try:
            for line in GEMINI_KEY_FILE.read_text(encoding="utf-8-sig").splitlines():
                s = line.strip().lstrip("\ufeff")
            if s and not s.startswith("#"):
                return s
    except OSError:
        pass
    return ""


def get_gemini_api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        key = _read_key_from_file()
    if not key:
        raise SystemExit(
            "ไม่พบ API key — เลือกอย่างใดอย่างหนึ่ง:\n"
            "  1) PowerShell: $env:GEMINI_API_KEY=\"<key>\"\n"
            "     CMD: set GEMINI_API_KEY=<key>\n"
            f"  2) สร้างไฟล์ {GEMINI_KEY_FILE.name} ในโฟลเดอร์โปรเจกต์นี้\n"
            "     ใส่ key บรรทัดเดียว (บรรทัดที่ขึ้นต้นด้วย # จะถือว่า comment)\n"
            "อย่า commit key ลง git; ถ้า key รั่วให้หมุนใหม่ใน Google AI Studio"
        )
    return key


def get_gemini_model_name() -> str:
    return (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()


def _gemini_rate_limit_retries() -> int:
    return max(1, int(os.environ.get("GEMINI_RATE_LIMIT_RETRIES", "6")))


def _gemini_rate_limit_base_delay_sec() -> float:
    return max(1.0, float(os.environ.get("GEMINI_RATE_LIMIT_BASE_SEC", "20")))


def _gemini_pause_between_files_sec() -> float:
    return max(0.0, float(os.environ.get("GEMINI_PAUSE_BETWEEN_FILES_SEC", "0")))


def _is_gemini_rate_limit_error(exc: BaseException) -> bool:
    """429 / quota / ResourceExhausted — ควรรอแล้วลองใหม่"""
    try:
        from google.api_core import exceptions as gexc

        if isinstance(exc, (gexc.ResourceExhausted, gexc.TooManyRequests)):
            return True
    except ImportError:
        pass
    s = str(exc)
    if "429" in s:
        return True
    up = s.upper()
    if "RESOURCE_EXHAUSTED" in up or "TOO_MANY_REQUESTS" in up:
        return True
    sl = s.lower()
    if "quota" in sl and ("exceed" in sl or "exceeded" in sl):
        return True
    return False


_DIALOGUE_SPEAKER_LINE = re.compile(
    r"^\s*(เภสัชกร|คนไข้|แพทย์|พยาบาล|ผู้ป่วย|ลูกค้า)\s*:\s*(.*)$"
)


def parse_transcript_segments(path: str) -> list[str]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = [ln.strip() for ln in raw_lines if ln.strip()]

    parts: list[str] = []
    for line in lines:
        m = re.match(r"\[\s*[\d.]+s\s*-\s*[\d.]+s\s*\]\s*ผู้พูด\s*\d+\s*:\s*(.+)", line)
        if m:
            t = m.group(1).strip()
            if t and t != "(ไม่มีข้อความ)":
                parts.append(t)

    if parts:
        return parts

    for line in lines:
        m = _DIALOGUE_SPEAKER_LINE.match(line)
        if m:
            role, text = m.group(1), m.group(2).strip()
            if text:
                parts.append(f"{role}: {text}")
        elif parts:
            parts[-1] = f"{parts[-1]} {line}"
        else:
            parts.append(line)
    return parts


def is_gemini_input_blocked_error(exc: BaseException) -> bool:
    s = str(exc)
    if "prompt_block_reason=4" in s:
        return True
    if "PROHIBITED_CONTENT" in s:
        return True
    low = s.lower()
    return "prohibited" in low and "content" in low


def _try_get_response_text(resp) -> str:
    try:
        t = getattr(resp, "text", None)
        if t:
            return t
    except (ValueError, AttributeError):
        pass
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        return ""
    content = getattr(cands[0], "content", None)
    parts = getattr(content, "parts", None) if content else None
    if not parts:
        return ""
    chunks = []
    for p in parts:
        if getattr(p, "text", None):
            chunks.append(p.text)
    return "".join(chunks)


_PROMPT_BLOCK_REASON_TH = {
    0: "ไม่ระบุ",
    1: "SAFETY",
    2: "อื่นๆ",
    3: "BLOCKLIST",
    4: "PROHIBITED_CONTENT (เนื้อหาถูกจำกัดนโยบาย — มักเกิดจากคำในสคริปต์ที่ถอดเสียงผิดหรือถูกตีความผิด)",
}


def _prompt_block_reason_code(pf) -> int | None:
    if not pf:
        return None
    br = getattr(pf, "block_reason", None)
    if br is None:
        return None
    try:
        return int(br)
    except (TypeError, ValueError):
        return getattr(br, "value", None) if hasattr(br, "value") else None


def _gemini_failure_detail(resp) -> str:
    bits = []
    pf = getattr(resp, "prompt_feedback", None)
    if pf:
        br = getattr(pf, "block_reason", None)
        if br is not None:
            code = _prompt_block_reason_code(pf)
            th = _PROMPT_BLOCK_REASON_TH.get(code, "") if code is not None else ""
            bits.append(f"prompt_block_reason={br}" + (f" ({th})" if th else ""))
    cands = getattr(resp, "candidates", None) or []
    if cands:
        c0 = cands[0]
        fr = getattr(c0, "finish_reason", None)
        if fr is not None:
            bits.append(f"finish_reason={fr}")
        sr = getattr(c0, "safety_ratings", None)
        if sr:
            bits.append(f"safety_ratings={sr}")
    return "; ".join(bits) if bits else "ไม่มีรายละเอียดเพิ่ม"


def _sanitize_asr_for_prohibited_filter(text: str) -> str:
    if not text:
        return text
    t = text
    replacements: list[tuple[str, str]] = [
        (
            "อยากเฮ็ดให้อุ้มคือปากก็สิผ ตาย",
            "[ถ้อยคำจากเสียงฟังไม่ชัด-บริบทคลินิก]",
        ),
        ("อยากเฮ็ดให้อุ้มคือปากก็สิผ", "[ถ้อยคำจากเสียงฟังไม่ชัด-บริบทคลินิก]"),
        ("บักอ๊อดหี้", "บักอ๊อด[ถ้อยคำฟังไม่ชัด-คาดว่าชื่อยา/อาการ]"),
        ("บักอ๊อดหี", "บักอ๊อด[ถ้อยคำฟังไม่ชัด]"),
        (
            "ดูดใส่ลิงให้น้องค่อยต้อนให้ซองมันกําไร",
            "[แนะนำการป้อนนมหรือยา-เสียงถอดความไม่ชัด]",
        ),
        ("ดูดใส่ลิง", "[ป้อนขวดนมหรือนม-เสียงฟังไม่ชัด]"),
        ("จิกเอา", "ให้กินทีละน้อย[เสียงฟังไม่ชัด]"),
    ]
    for a, b in replacements:
        if a in t:
            t = t.replace(a, b)
    return t


def _wrap_clinical_transcript(user_text: str) -> str:
    return (
        "บริบท: ข้อความต่อไปนี้เป็นบันทึกการสนทนาในคลินิก/ร้านยาที่ถอดความด้วยเครื่อง (ASR) "
        "ภาษาไทย อาจมีคำฟังผิด ความหมายทั้งหมดเกี่ยวกับการดูแลสุขภาพและยาเท่านั้น "
        "ไม่มีเจตนาเนื้อหาอื่น\n\n"
        "บทสนทนา:\n\n"
        f"{user_text}"
    )


def _safety_settings_all(threshold):
    from google.generativeai.types import HarmCategory

    th = threshold
    return [
        {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": th},
        {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": th},
        {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": th},
        {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": th},
    ]


def _call_gemini_once(system_instruction: str, user_text: str, temperature: float) -> str:
    """เรียก Gemini หนึ่งครั้ง — ถ้า 429 ให้จับที่ call_gemini ด้านนอกแล้ว retry"""
    import google.generativeai as genai
    from google.generativeai.types import HarmBlockThreshold

    genai.configure(api_key=get_gemini_api_key())
    model = genai.GenerativeModel(
        model_name=get_gemini_model_name(),
        system_instruction=system_instruction,
    )
    gen_cfg = {
        "temperature": temperature,
        "max_output_tokens": 8192,
    }

    def _one_call(utext: str, threshold) -> tuple:
        safety = _safety_settings_all(threshold)
        r = model.generate_content(
            utext,
            generation_config=gen_cfg,
            safety_settings=safety,
        )
        return r, _try_get_response_text(r).strip()

    for threshold in (HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmBlockThreshold.BLOCK_NONE):
        resp, text = _one_call(user_text, threshold)
        if text:
            return text

    code = _prompt_block_reason_code(getattr(resp, "prompt_feedback", None))
    if code == 4:
        softened = _sanitize_asr_for_prohibited_filter(user_text)
        wrapped = _wrap_clinical_transcript(softened)
        for threshold in (HarmBlockThreshold.BLOCK_ONLY_HIGH, HarmBlockThreshold.BLOCK_NONE):
            resp, text = _one_call(wrapped, threshold)
            if text:
                return text

    detail = _gemini_failure_detail(resp)
    raise RuntimeError(
        "Gemini ไม่คืนข้อความ (อาจถูกบล็อก safety, เนื้อหาว่าง หรือโมเดลไม่ตอบ). "
        f"รายละเอียด: {detail}"
    )


def call_gemini(system_instruction: str, user_text: str, temperature: float = 0.2) -> str:
    import importlib.util

    if importlib.util.find_spec("google.generativeai") is None:
        raise ImportError(
            "ไม่มีแพ็กเกจ google.generativeai — ติดตั้งด้วย:\n"
            "  python -m pip install google-generativeai"
        )

    n = _gemini_rate_limit_retries()
    base = _gemini_rate_limit_base_delay_sec()
    last: BaseException | None = None
    for attempt in range(n):
        try:
            return _call_gemini_once(system_instruction, user_text, temperature)
        except Exception as e:
            last = e
            if not _is_gemini_rate_limit_error(e) or attempt >= n - 1:
                raise
            # exponential backoff + jitter กัน thundering herd
            wait = min(base * (2**attempt) + random.uniform(0, 3), 300.0)
            print(
                f"[429/โควตา] รอ {wait:.1f} วินาที แล้วลองใหม่ ({attempt + 1}/{n})…",
                flush=True,
            )
            time.sleep(wait)
    assert last is not None
    raise last


# --- CSV output ---
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
VISIT_PURPOSE_CANONICAL = frozenset({"ปรึกษา", "ซื้อยา", "ทั้งคู่"})


def gemini_extract_csv_path(base: Path, report_subdir: str) -> Path:
    return (base / "report" / report_subdir / "gemini_extract.csv").resolve()


def text_to_form_reports_dir(base: Path, report_subdir: str) -> Path:
    d = (base / "report" / report_subdir / "reports").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_text_to_form_file_report(
    base: Path,
    input_path: Path,
    *,
    report_subdir: str,
    gemini_model: str,
    gemini_sec: float,
    n_segments: int,
    skipped_notes: list[str],
) -> Path:
    """รายงานต่อไฟล์: เวลา, โมเดล, path อินพุต, จำนวนท่อน, ท่อนที่ถูกตัด (ถ้ามี)"""
    out = text_to_form_reports_dir(base, report_subdir) / f"{input_path.stem}_result.txt"
    lines = [
        "text → form (classify_gemini_extract)",
        f"เวลาบันทึกรายงาน (local): {datetime.now().isoformat(timespec='seconds')}",
        "",
        "ไฟล์อินพุต:",
        f"  {input_path.resolve()}",
        "",
        "ประสิทธิภาพ / การตั้งค่า:",
        f"  โมเดล Gemini: {gemini_model}",
        f"  เวลาที่ใช้ (วินาที) — เฉพาะขั้น Gemini + ประมวลผลรอบนี้: {gemini_sec:.4f}",
        f"  จำนวนท่อน transcript ที่ส่งเข้าโมเดล: {n_segments}",
    ]
    if skipped_notes:
        lines.append(f"  ท่อนที่ถูกตัดออกชั่วคราวเพราะกรองอินพุต: {len(skipped_notes)}")
        for s in skipped_notes[:12]:
            one = s.replace("\n", " ")[:160]
            lines.append(f"    · {one}")
        if len(skipped_notes) > 12:
            lines.append(f"    · … และอีก {len(skipped_notes) - 12} ท่อน")
    lines.extend(
        [
            "",
            "ผลลัพธ์:",
            f"  CSV: {gemini_extract_csv_path(base, report_subdir)}",
            f"  ชื่อแถว (ชื่อไฟล์): {input_path.name}",
        ]
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def append_text_to_form_timing_tsv(
    base: Path,
    report_subdir: str,
    ts_iso: str,
    filename: str,
    gemini_sec: float,
    n_segments: int,
    n_skipped_segs: int,
) -> None:
    tsv = (base / "report" / report_subdir / "timing_log.tsv").resolve()
    tsv.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "timestamp\tfilename\tgemini_sec\tsegments\tskipped_segments\n"
    )
    new_file = not tsv.is_file()
    with open(tsv, "a", encoding="utf-8") as f:
        if new_file:
            f.write(header)
        f.write(
            f"{ts_iso}\t{filename}\t{gemini_sec:.4f}\t{n_segments}\t{n_skipped_segs}\n"
        )


def append_text_to_form_session_summary(
    base: Path,
    report_subdir: str,
    *,
    source_dir: Path,
    n_to_run: int,
    n_saved: int,
    n_skip_problem: int,
    n_already_in_csv: int,
    session_wall_sec: float,
) -> None:
    path = (base / "report" / report_subdir / "session_summary.txt").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    block = "\n".join(
        [
            f"=== session {datetime.now().isoformat(timespec='seconds')} ===",
            f"อินพุต (โฟลเดอร์หรือไฟล์): {source_dir.resolve()}",
            f"ไฟล์ที่ตั้งใจรันในรอบนี้: {n_to_run}",
            f"สำเร็จและบันทึก CSV + รายงาน: {n_saved}",
            f"ข้ามเพราะอ่าน transcript / error อื่น: {n_skip_problem}",
            f"ข้ามเดิม (มีชื่อใน CSV แล้ว): {n_already_in_csv}",
            f"เวลารวมรอบนี้ (วินาที, wall clock): {session_wall_sec:.2f}",
            "",
        ]
    )
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(block)


def compact_csv_cell_text(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return "-"
    t = " ".join(t.split())
    return t if t else "-"


def normalize_visit_purpose_cell(s: str) -> str:
    t = compact_csv_cell_text(s)
    if t == "-" or not t:
        return "-"
    if t in VISIT_PURPOSE_CANONICAL:
        return t
    return "-"


def existing_result_filenames(csv_path: Path) -> set[str]:
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


# --- extract pipeline ---
SYSTEM_EXTRACT = """คุณเป็นผู้ช่วยสรุปข้อมูลสุขภาพจากบทสนทนาภาษาไทย

กติกา:
1) อ่านบทสนทนาแล้วเติมค่า 6 ช่องตามคีย์ด้านล่าง
2) ถ้าไม่พูดถึงหรือไม่ชัดเจน ให้ใส่ "-" (ขีดเดียว) — ยกเว้นช่อง "ประเภท" ใช้กติกาข้อ 6 เท่านั้น
3) ใช้ภาษาไทยกระชับ คงชื่อยา/โรคตามที่ผู้พูดใช้
4) ห้ามเดาหรือเติมข้อมูลที่ไม่ปรากฏในบทสนทนา
5) ช่อง "ประวัติการจ่ายยา": สรุปเฉพาะการจ่ายยา/การได้รับยา/การใช้ยาใน**อดีต**หรือประวัติจากร้านยาก่อนหน้า — **ห้ามใส่** ยาที่กำลังจะจ่าย กำลังแจก หรือกำลังแนะนำให้ซื้อ/รับในบทสนทนานี้ (ยาครั้งนี้ให้สะท้อนในช่อง "คำแนะนำจากเภสัช" หรือ "บันทึกทางการแพทย์" ตามความเหมาะสม ไม่ใส่ในประวัติการจ่ายยา) ถ้าไม่มีประวัติอดีตนอกจากยาครั้งนี้ให้ใส่ "-"
6) ช่อง "ประเภท": **อ่านจากบทสนทนาในไฟล์นี้** แล้วสรุปว่าคนไข้มาที่ร้านเพื่ออะไร — เลือกได้ **เพียงหนึ่งค่า** จากสามค่านี้เท่านั้น (เขียนตัวอักษรให้ตรงเป๊ะ):
   - ปรึกษา = คนไข้มาปรึกษาเป็นหลัก (ถามอาการ ขอคำแนะทางยา/ข้อมูล) โดยในบทสนทนานี้ไม่ปรากฏการซื้อหรือรับยา
   - ซื้อยา = คนไข้มาซื้อยา/ขอรับยาเป็นหลัก แทบไม่มีการปรึกษาอาการ
   - ทั้งคู่ = มีทั้งการปรึกษา/สอบถามอาการหรือยา และมีการซื้อหรือรับยาในบทสนทนาเดียวกัน
   ถ้าแยกไม่ชัดหรือข้อมูลในไฟล์ไม่พอ ให้ใส่ "-"
7) ช่อง "บันทึกทางการแพทย์" (healthcare note): สรุปเฉพาะประเด็นทางการแพทย์ที่มีผลต่อการพิจารณาจ่ายยา เช่น อาการปัจจุบัน/ความรุนแรง การทานยาอื่น ข้อห้าม/คำเตือนจากแพทย์ การตั้งครรภ์ให้นม โรคไตตับ แพ้ยาเสริม ปฏิกิริยา ระยะห่างมื้อยา ฯลฯ — ตัดการพูดคุยทั่วไปที่ไม่เกี่ยวกับการรักษาหรือยาออกทั้งหมด ถ้าไม่มีประเด็นเพิ่มนอกจากที่สรุปใน 3 ช่องแรกแล้ว ให้ใส่ "-"
8) ช่อง "คำแนะนำจากเภสัช": สรุปว่าหลังออกจากร้านยา/จบบทสนทนานี้ **ควรทำอะไรต่อ** โดยถ้ามีการแนะนำยา ให้เขียนแยกชัดเป็นรูปแบบ **ชื่อยา (หรือชนิดที่พูด) → กินตอนไหน/อย่างไร** เช่น มื้อยา (เช้า กลางวัน เย็น ก่อนนอน) ก่อนหรือหลังอาหารทันที วันละกี่ครั้ง ทุกกี่ชั่วโมงตามอาการ ชงอย่างไร รวมถึงสังเกตอาการ นัดกลับ ข้อห้าม ถ้าบทสนทนามีหลายตัวให้ครบทุกตัวที่มีคำแนะ — เฉพาะที่เภสัชกรหรือแพทย์ในบทสนทนาพูดหรือนัดไว้ ห้ามเดา ถ้าไม่มีคำแนะเชิงปฏิบัติเลยให้ใส่ "-"
9) ในแต่ละค่า string ของ JSON ห้ามมีตัวขึ้นบรรทัดใหม่ — เขียนเป็นบรรทัดเดียวคั่นด้วยช่องว่างหรือคอมมา
10) ตอบเป็น JSON เท่านั้น ไม่มี markdown ไม่มีคำอธิบายก่อน/หลัง รูปแบบคีย์ต้องตรงนี้:
{"ประเภท": "ทั้งคู่", "ประวัติการแพ้ยา": "...", "โรคประจำตัว": "...", "ประวัติการจ่ายยา": "...", "บันทึกทางการแพทย์": "...", "คำแนะนำจากเภสัช": "..."}"""


def extract_json_object(text: str) -> dict:
    t = text.strip()
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        raise ValueError("ไม่พบ JSON ในผลตอบ")
    return json.loads(m.group(0))


def _short_skip_reason(exc: BaseException, max_len: int = 180) -> str:
    s = str(exc).replace("\n", " ")
    s = " ".join(s.split())
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


EXTRACT_FIELD_KEYS = (
    "ประเภท",
    "ประวัติการแพ้ยา",
    "โรคประจำตัว",
    "ประวัติการจ่ายยา",
    "บันทึกทางการแพทย์",
    "คำแนะนำจากเภสัช",
)


def _fields_from_gemini_body(body: str) -> dict:
    user = f"บทสนทนา:\n\n{body}"
    raw = call_gemini(SYSTEM_EXTRACT, user, temperature=0.1)
    data = extract_json_object(raw)
    out = {}
    for k in EXTRACT_FIELD_KEYS:
        v = data.get(k, "-")
        raw_val = (str(v).strip() or "-") if v is not None else "-"
        out[k] = compact_csv_cell_text(raw_val)
    out["ประเภท"] = normalize_visit_purpose_cell(out.get("ประเภท", "-"))
    return out


def extract_fields_with_segment_skip(segments: list[str]) -> tuple[dict, list[str]]:
    active = [s.strip() for s in segments if (s or "").strip()]
    if not active:
        raise ValueError("ไม่มีข้อความใน transcript")
    skipped_notes: list[str] = []
    max_passes = max(32, len(active) + 8)

    for _ in range(max_passes):
        body = " ".join(active)
        try:
            return _fields_from_gemini_body(body), skipped_notes
        except RuntimeError as e:
            if not is_gemini_input_blocked_error(e):
                raise
        if len(active) <= 1:
            raise RuntimeError(
                "Gemini บล็อกอินพุต (PROHIBITED_CONTENT) เหลือท่อนเดียว — แก้ข้อความในไฟล์หรือข้ามไฟล์นี้"
            ) from e

        removed = False
        for i in range(len(active)):
            trial = active[:i] + active[i + 1 :]
            if not trial:
                continue
            try:
                _fields_from_gemini_body(" ".join(trial))
            except RuntimeError as e2:
                if is_gemini_input_blocked_error(e2):
                    continue
                raise
            skipped_notes.append(active[i][:160])
            active = trial
            removed = True
            break
        if removed:
            continue

        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                trial = [active[k] for k in range(len(active)) if k not in (i, j)]
                if not trial:
                    continue
                try:
                    _fields_from_gemini_body(" ".join(trial))
                except RuntimeError as e2:
                    if is_gemini_input_blocked_error(e2):
                        continue
                    raise
                skipped_notes.append(active[i][:120])
                skipped_notes.append(active[j][:120])
                active = trial
                removed = True
                break
            if removed:
                break
        if removed:
            continue

        raise RuntimeError(
            "Gemini บล็อกอินพุตแม้ลองตัดทีละหนึ่งท่อนและทีละสองท่อนแล้ว — ลองแก้ถ้อยคำที่ฟังผิดในไฟล์"
        ) from None

    raise RuntimeError("ถึงจำนวนรอบสูงสุดในการตัดท่อน transcript") from None


def extract_fields(conversation: str) -> dict:
    return _fields_from_gemini_body(conversation.strip())


def main():
    from_data_flag, rest = parse_cli_argv(sys.argv[1:])

    if rest:
        if from_data_flag:
            print(
                "แจ้ง: มี path ในอาร์กิวเมนต์แล้ว — ใช้ path นั้น (ไม่ใช้ --from-data)",
                file=sys.stderr,
            )
        path_arg = Path(rest[0]).resolve()
        if len(rest) > 1:
            print("แจ้ง: ใช้เฉพาะอาร์กิวเมนต์แรกเป็น path", file=sys.stderr)
        if path_arg.is_file():
            files = filter_txt_files([path_arg])
        elif path_arg.is_dir():
            files = filter_txt_files(sorted(path_arg.glob("*.txt")))
        else:
            files = filter_txt_files([path_arg]) if path_arg.exists() else []
        source_dir = path_arg if path_arg.is_dir() else path_arg.parent
    elif from_data_flag:
        input_dir = safe_data_subdir(from_data_flag)
        if not input_dir.is_dir():
            print(f"ไม่พบโฟลเดอร์ {input_dir}")
            sys.exit(1)
        source_dir = input_dir
        files = list_txt_files_in_dir(input_dir)
    else:
        if sys.stdin.isatty():
            input_dir = prompt_pick_data_subdir()
        else:
            sub = (os.environ.get("GEMINI_TEXT_INPUT_SUBDIR") or DEFAULT_TEXT_SUBDIR).strip()
            input_dir = safe_data_subdir(sub)
            print(f"(ไม่มี TTY — ใช้โฟลเดอร์ data/{input_dir.name}/ จาก GEMINI_TEXT_INPUT_SUBDIR หรือค่าเริ่มต้น)")
        if not input_dir.is_dir():
            print(f"ไม่พบโฟลเดอร์ {input_dir}")
            sys.exit(1)
        source_dir = input_dir
        files = list_txt_files_in_dir(input_dir)

    if not files:
        print("ไม่พบไฟล์ .txt ในแหล่งที่เลือก")
        print("ใช้: python classify_gemini_extract.py [--from-data <โฟลเดอร์ใต้ data/>]")
        print("     python classify_gemini_extract.py <ไฟล์.txt | โฟลเดอร์>")
        print(f"     โฟลเดอร์ data: {DATA_ROOT}")
        sys.exit(1)

    report_subdir = resolve_report_subdir(source_dir)
    out_csv = gemini_extract_csv_path(BASE, report_subdir)
    report_root = (BASE / "report" / report_subdir).resolve()
    already_done = existing_result_filenames(out_csv)
    pending = [f for f in files if f.name not in already_done]
    n_already_in_csv = len(files) - len(pending)
    if n_already_in_csv:
        print(
            f"ข้าม {n_already_in_csv} ไฟล์ที่มีผลใน {out_csv.name} แล้ว "
            f"(จะไม่เรียก Gemini ซ้ำ — ถ้าต้องการรันใหม่ให้ลบแถวนั้นออกจาก CSV)"
        )
    files = pending
    if not files:
        print("ไม่มีไฟล์ที่ต้องประมวลผล (ทุกไฟล์มีผลใน CSV แล้ว)")
        sys.exit(0)

    n_to_run = len(files)
    print(
        f"ใช้ไฟล์จาก: {source_dir.resolve()} | จะเรียก Gemini เฉพาะ {n_to_run} ไฟล์ที่ยังไม่มีใน CSV\n"
        f"บันทึกผลที่: {report_root}/ ({report_subdir})\n"
    )

    t_session0 = time.perf_counter()
    n_saved = 0
    n_skip_problem = 0
    pause_between = _gemini_pause_between_files_sec()
    for idx, f in enumerate(files, start=1):
        try:
            try:
                segments = parse_transcript_segments(str(f))
            except Exception as e:
                n_skip_problem += 1
                print(f"[ข้าม] {f.name}: อ่าน transcript ไม่ได้ — {_short_skip_reason(e)}\n")
                continue
            if not segments:
                n_skip_problem += 1
                print(f"[ข้าม] {f.name}: ไม่มีข้อความใน transcript\n")
                continue
            print(f"--- [{idx}/{n_to_run}] {f.name} ---")
            try:
                t0 = time.perf_counter()
                out, skipped_segs = extract_fields_with_segment_skip(segments)
                elapsed_s = time.perf_counter() - t0
                if skipped_segs:
                    print(
                        f"[ข้าม {len(skipped_segs)} ท่อนใน transcript ที่รวมแล้วโดนกรอง — สรุปจากส่วนที่เหลือ]"
                    )
                    for s in skipped_segs[:5]:
                        preview = (s.replace("\n", " ")[:100] + "…") if len(s) > 100 else s
                        print(f"    · {preview}")
                    if len(skipped_segs) > 5:
                        print(f"    · … และอีก {len(skipped_segs) - 5} ท่อน")
            except Exception as e:
                n_skip_problem += 1
                print(f"[ข้าม] {f.name}: {_short_skip_reason(e)} → ไปไฟล์ถัดไป\n")
                continue
            print(f"เวลาที่ใช้: {elapsed_s:.2f} วินาที")
            print("ประเภท:", out["ประเภท"])
            print("ประวัติการแพ้ยา:", out["ประวัติการแพ้ยา"])
            print("โรคประจำตัว:", out["โรคประจำตัว"])
            print("ประวัติการจ่ายยา:", out["ประวัติการจ่ายยา"])
            print("บันทึกทางการแพทย์:", out["บันทึกทางการแพทย์"])
            print("คำแนะนำจากเภสัช:", out["คำแนะนำจากเภสัช"])
            print()
            row = {
                "ชื่อไฟล์": f.name,
                "เวลาที่ใช้ (วินาที)": f"{elapsed_s:.2f}",
                "ประเภท": out["ประเภท"],
                "ประวัติการแพ้ยา": out["ประวัติการแพ้ยา"],
                "โรคประจำตัว": out["โรคประจำตัว"],
                "ประวัติการจ่ายยา": out["ประวัติการจ่ายยา"],
                "บันทึกทางการแพทย์": out["บันทึกทางการแพทย์"],
                "คำแนะนำจากเภสัช": out["คำแนะนำจากเภสัช"],
            }
            upsert_result_csv(out_csv, [row])
            n_saved += 1
            rep_path = write_text_to_form_file_report(
                BASE,
                f,
                report_subdir=report_subdir,
                gemini_model=get_gemini_model_name(),
                gemini_sec=elapsed_s,
                n_segments=len(segments),
                skipped_notes=skipped_segs,
            )
            append_text_to_form_timing_tsv(
                BASE,
                report_subdir,
                datetime.now().isoformat(timespec="seconds"),
                f.name,
                elapsed_s,
                len(segments),
                len(skipped_segs),
            )
            print(f"บันทึกลง {out_csv.name} แล้ว (ทันทีหลังได้ผล)")
            print(f"รายงาน: {rep_path.name}\n")
        finally:
            if pause_between > 0 and idx < n_to_run:
                time.sleep(pause_between)

    session_wall = time.perf_counter() - t_session0
    append_text_to_form_session_summary(
        BASE,
        report_subdir,
        source_dir=source_dir,
        n_to_run=n_to_run,
        n_saved=n_saved,
        n_skip_problem=n_skip_problem,
        n_already_in_csv=n_already_in_csv,
        session_wall_sec=session_wall,
    )

    print("\n--- สรุปรอบนี้ ---")
    print(f"  ไฟล์ที่ลองเรียก Gemini: {n_to_run}")
    print(f"  สำเร็จและบันทึก CSV: {n_saved}")
    if n_skip_problem:
        print(
            f"  ข้ามเพราะ error: {n_skip_problem} (ยังไม่บันทึก — รันครั้งหน้าจะลองใหม่ได้)"
        )
    if n_already_in_csv:
        print(
            f"  ไม่ได้รันเพราะมีใน CSV แล้ว: {n_already_in_csv} "
            f"(นี่คือเหตุที่ดูเหมือน \"ข้ามแล้วไม่ทำต่อ\" — ไฟล์อื่นถูกข้ามตั้งแต่ต้น ไม่ใช่หยุดกลางทาง)"
        )
    print(
        f"  บันทึกสรุปรอบรัน: {(BASE / 'report' / report_subdir / 'session_summary.txt').resolve()}"
    )


if __name__ == "__main__":
    main()
