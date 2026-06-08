# -*- coding: utf-8 -*-
"""
เวอร์ชัน 2: ใช้ Gemini 2.5 Flash สรุปจากบทสนทนา
- ประวัติการแพ้ยา / โรคประจำตัว / ประวัติการจ่ายยา (เฉพาะอดีต — ไม่รวมยาที่กำลังจะจ่ายในครั้งนี้)
- บันทึกทางการแพทย์ (healthcare note): เฉพาะประเด็นทางการแพทย์ที่เกี่ยวกับการพิจารณาจ่ายยา ตัดบทสนทนาทั่วไปออก
- ประเภท: จากบทสนทนาในไฟล์ — คนไข้มาซื้อยา / มาปรึกษา / ทั้งคู่ (เขียนเป็นค่าเดียวจากสามค่านี้ หรือ "-" ถ้าไม่ชัด)
- คำแนะนำจากเภสัช: หลังจากนี้ควรทำอะไร โดยเฉพาะ **ยาแต่ละตัวกินตอนไหน** (เช้า/กลางวัน/เย็น/ก่อนนอน ก่อนหรือหลังอาหาร ทุกกี่ชั่วโมง) ตามที่เภสัชกรหรือแพทย์ในบทสนทนาพูด

ต้องตั้ง GEMINI_API_KEY (หรือ GOOGLE_API_KEY)

ค่าเริ่มต้น: ทุกไฟล์ *.txt ในโฟลเดอร์ text_classified/data
ผลรวม: text_classified/result/gemini_extract.csv (มีคอลัมน์ เวลาที่ใช้ (วินาที) = เวลาประมวลผลไฟล์นั้นรวมการเรียก API; merge ตามชื่อไฟล์ — บันทึกทันทีหลังได้ผลแต่ละไฟล์)
ข้ามไฟล์ที่ชื่อตรงกับแถวใน gemini_extract.csv แล้ว (ไม่เรียก API ซ้ำ)
ถ้าโดนกรองอินพุต (PROHIBITED_CONTENT) จะลองตัดท่อนตามบรรทัดผู้พูดทีละท่อน/คู่ท่อนจนกว่าจะประมวลผลได้
ถ้าไฟล์ใด error อื่น (JSON ผิด ฯลฯ) จะ [ข้าม] แล้วทำไฟล์ถัดไป — ไม่หยุดทั้งชุด

ใช้:
  python classify_gemini_extract.py
  python classify_gemini_extract.py text_classified/data/ไฟล์.txt
"""
import json
import re
import sys
import time
from pathlib import Path

from gemini_shared import (
    DATA_DIR,
    call_gemini,
    filter_txt_files,
    is_gemini_input_blocked_error,
    list_data_txt_files,
    parse_transcript_segments,
)
from result_csv import (
    compact_csv_cell_text,
    existing_result_filenames,
    gemini_extract_csv_path,
    normalize_visit_purpose_cell,
    upsert_result_csv,
)

BASE = Path(__file__).resolve().parent

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
        raw = (str(v).strip() or "-") if v is not None else "-"
        out[k] = compact_csv_cell_text(raw)
    out["ประเภท"] = normalize_visit_purpose_cell(out.get("ประเภท", "-"))
    return out


def extract_fields_with_segment_skip(segments: list[str]) -> tuple[dict, list[str]]:
    """
    เรียก Gemini จากท่อนตามลำดับในไฟล์
    ถ้าโดนกรองอินพุต จะลองตัดท่อนทีละหนึ่ง แล้วทีละสอง จนกว่าจะสำเร็จ
    คืน (ผลหลายช่องรวมคำแนะนำจากเภสัช, รายการข้อความท่อนที่ข้ามสั้นๆ เพื่อ log)
    """
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
    """เรียกจากข้อความรวมท่อนเดียว (ไม่ตัดท่อน) — ใช้ภายใน/ทดสอบ"""
    return _fields_from_gemini_body(conversation.strip())


def main():
    if len(sys.argv) > 1:
        path_arg = Path(sys.argv[1]).resolve()
        if path_arg.is_file():
            files = filter_txt_files([path_arg])
        elif path_arg.is_dir():
            files = filter_txt_files(sorted(path_arg.glob("*.txt")))
        else:
            files = filter_txt_files([path_arg]) if path_arg.exists() else []
        source_dir = path_arg if path_arg.is_dir() else path_arg.parent
    else:
        source_dir = DATA_DIR
        files = list_data_txt_files()

    if not files:
        print("ใช้: python classify_gemini_extract.py [ไฟล์ .txt หรือโฟลเดอร์]")
        print(f"ค่าเริ่มต้น: *.txt ใน {DATA_DIR}")
        sys.exit(1)

    out_csv = gemini_extract_csv_path(BASE)
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
    )

    n_saved = 0
    n_skip_problem = 0
    for idx, f in enumerate(files, start=1):
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
        print(f"บันทึกลง {out_csv.name} แล้ว (ทันทีหลังได้ผล)\n")

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


if __name__ == "__main__":
    main()
