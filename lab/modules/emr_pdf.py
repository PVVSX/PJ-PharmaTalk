"""
โมดูลสร้างไฟล์ PDF เวชระเบียนเภสัชกรรมคลินิก (PharmaLog AI Clinical EMR PDF Generator)
ใช้ fpdf2 ร่วมกับแบบอักษร Kanit (และสำรองด้วย Sarabun)
ปรับแต่งรูปแบบให้เป็นทางการ กะทัดรัด ตัวอักษรคมชัด อ่านง่าย และเป็นมาตรฐานเวชระเบียนโรงพยาบาล/คลินิก
"""

import os
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional
from fpdf import FPDF
from fpdf.enums import XPos, YPos

warnings.filterwarnings("ignore", category=UserWarning, module="fpdf")

# ตำแหน่งชุดฟอนต์
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
_FONT_DIR = os.path.join(_PROJECT_ROOT, "fonts")

# ฟอนต์ Kanit
KANIT_REGULAR = os.path.join(_FONT_DIR, "Kanit-Regular.ttf")
KANIT_BOLD = os.path.join(_FONT_DIR, "Kanit-Bold.ttf")
KANIT_ITALIC = os.path.join(_FONT_DIR, "Kanit-Italic.ttf")
KANIT_MEDIUM = os.path.join(_FONT_DIR, "Kanit-Medium.ttf")

# ฟอนต์ Sarabun สำรอง
SARABUN_REGULAR = os.path.join(_FONT_DIR, "Sarabun-Regular.ttf")
SARABUN_BOLD = os.path.join(_FONT_DIR, "Sarabun-Bold.ttf")
SARABUN_ITALIC = os.path.join(_FONT_DIR, "Sarabun-Italic.ttf")

_CHAR_MAP = str.maketrans({
    "\u2011": "-",  # non-breaking hyphen
    "\u202f": " ",  # narrow no-break space
    "\u00a0": " ",  # no-break space
    "\ufeff": "",   # zero-width no-break space (BOM)
    "\u200b": "",   # zero-width space
    "\u200e": "",   # LTR mark
    "\u200f": "",   # RTL mark
})


def _clean_text(s: Any) -> str:
    """ทำความสะอาดข้อความและแปลงอักขระพิเศษ Unicode ให้อยู่ในชุดที่ฟอนต์ Kanit รองรับ"""
    if s is None:
        return "-"
    text = str(s).translate(_CHAR_MAP).strip()
    return text if text else "-"


class PharmaLogEMRPDF(FPDF):
    """FPDF คลาสสำหรับสร้างเอกสารเวชระเบียนคลินิก PharmaLog AI ในแบบฟอร์มทางการ"""

    def __init__(self, record_id: str = "", model_name: str = "") -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.record_id = record_id
        self.model_name = model_name

        # ลงทะเบียนฟอนต์ Kanit หากมี หรือสลับไป Sarabun
        if os.path.exists(KANIT_REGULAR) and os.path.exists(KANIT_BOLD):
            self.font_family_name = "Kanit"
            self.add_font("Kanit", "", KANIT_REGULAR)
            self.add_font("Kanit", "B", KANIT_BOLD)
            self.add_font("Kanit", "I", KANIT_ITALIC if os.path.exists(KANIT_ITALIC) else KANIT_REGULAR)
            if os.path.exists(KANIT_MEDIUM):
                self.add_font("KanitMedium", "", KANIT_MEDIUM)
            else:
                self.add_font("KanitMedium", "", KANIT_REGULAR)
        else:
            self.font_family_name = "Sarabun"
            self.add_font("Sarabun", "", SARABUN_REGULAR)
            self.add_font("Sarabun", "B", SARABUN_BOLD)
            self.add_font("Sarabun", "I", SARABUN_ITALIC if os.path.exists(SARABUN_ITALIC) else SARABUN_REGULAR)
            self.add_font("KanitMedium", "", SARABUN_REGULAR)

        self.set_margins(left=14, top=14, right=14)
        self.set_auto_page_break(auto=True, margin=15)

    def header(self) -> None:
        """ส่วนหัวกระดาษสำหรับหน้าที่ 2 เป็นต้นไป"""
        if self.page_no() > 1:
            self.set_font(self.font_family_name, "I", 7.5)
            self.set_text_color(100, 116, 139)
            rec_str = self.record_id[:16] if self.record_id else "-"
            self.cell(
                0,
                5,
                f"PharmaLog AI Clinical EMR  |  รหัสเวชระเบียน: {rec_str}  |  โมเดล: {self.model_name}",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.set_draw_color(226, 232, 240)
            self.set_line_width(0.2)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(3)

    def footer(self) -> None:
        """ส่วนท้ายกระดาษพร้อมเลขหน้า"""
        self.set_y(-12)
        self.set_font(self.font_family_name, "", 7.5)
        self.set_text_color(148, 163, 184)
        w_avail = self.w - self.l_margin - self.r_margin
        self.cell(w_avail / 2, 6, "เอกสารเวชระเบียนอิเล็กทรอนิกส์สร้างโดยระบบ PharmaLog AI", align="L")
        self.cell(w_avail / 2, 6, f"หน้า {self.page_no()} / {{nb}}", align="R")


# เพื่อรักษาความเข้ากันได้ย้อนหลัง
PharmaTalkEMRPDF = PharmaLogEMRPDF


def generate_emr_pdf(
    emr_data: Dict[str, Any],
    model_name: str = "Typhoon Whisper Large v3",
    record_id: str = "",
    dialogue_turns: Optional[List[Dict[str, str]]] = None,
) -> bytes:
    """
    สร้างไบต์ข้อมูลไฟล์ PDF เวชระเบียนคลินิกและบันทึกการบริบาลทางเภสัชกรรมด้วยฟอนต์ Kanit

    Args:
        emr_data: พจนานุกรมข้อมูลเวชระเบียน
        model_name: ชื่อโมเดลที่ใช้ถอดเสียง/สกัดข้อมูล
        record_id: รหัสบันทึกหรือ hash
        dialogue_turns: ลิสต์บทสนทนา [{"role": ..., "text": ...}] (ถ้ามี)

    Returns:
        bytes: ข้อมูลไบนารีของไฟล์ PDF
    """
    pdf = PharmaLogEMRPDF(record_id=record_id, model_name=model_name)
    fname = pdf.font_family_name
    pdf.alias_nb_pages()
    pdf.add_page()
    w_avail = pdf.w - pdf.l_margin - pdf.r_margin

    # 1. แถบสีด้านบนและหัวกระดาษทางการ
    pdf.set_fill_color(15, 23, 42)  # Slate 900
    pdf.rect(pdf.l_margin, pdf.t_margin, w_avail, 1.2, style="F")
    pdf.set_y(pdf.t_margin + 3.5)

    # หมวดหมู่ระบบ
    pdf.set_font(fname, "", 7.5)
    pdf.set_text_color(100, 116, 139)  # Slate 500
    pdf.cell(w_avail - 50, 4, "PHARMALOG AI INTELLIGENT CLINICAL SYSTEM  |  OPD PHARMACY CARE", new_x=XPos.RIGHT, new_y=YPos.TOP)

    # ป้ายชั้นความลับทางการแพทย์
    pdf.set_font(fname, "B", 7.5)
    pdf.set_text_color(15, 23, 42)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_draw_color(203, 213, 225)
    pdf.cell(50, 4.5, "เวชระเบียนทางการแพทย์ (CONFIDENTIAL)", border=1, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # หัวเรื่องหลักของเวชระเบียน
    pdf.set_font(fname, "B", 13.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(w_avail, 6.5, "บันทึกการบริบาลทางเภสัชกรรมและเวชระเบียนคลินิก (Clinical EMR)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # เส้นคั่น
    pdf.set_draw_color(203, 213, 225)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
    pdf.ln(3)

    # 2. แถบข้อมูลเมทาดาตา (Metadata Grid)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M น.")
    meta_h = 9
    col_w = w_avail / 4
    y_meta = pdf.get_y()

    meta_cols = [
        ("วันที่ตรวจบันทึก", now_str),
        ("รหัสเวชระเบียน", (record_id[:16] if record_id else "-")),
        ("โมเดลประมวลผล", model_name[:24]),
        ("แผนกการบริบาล", "เภสัชกรรมผู้ป่วยนอก"),
    ]

    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(pdf.l_margin, y_meta, w_avail, meta_h, style="DF", round_corners=True, corner_radius=1.5)

    for i, (k, v) in enumerate(meta_cols):
        cx = pdf.l_margin + i * col_w
        pdf.set_xy(cx + 2.5, y_meta + 1.2)
        pdf.set_font(fname, "", 7)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(col_w - 5, 3, k, align="L")

        pdf.set_xy(cx + 2.5, y_meta + 4.5)
        pdf.set_font(fname, "B", 7.8)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(col_w - 5, 3.5, v, align="L")

        if i < 3:
            pdf.set_draw_color(226, 232, 240)
            pdf.line(cx + col_w, y_meta + 1, cx + col_w, y_meta + meta_h - 1)

    pdf.set_y(y_meta + meta_h + 3.5)

    # 3. ข้อมูลความปลอดภัยและประวัติผู้ป่วย (Allergy, Chronic, Past Meds)
    allergy = _clean_text(emr_data.get("ประวัติการแพ้ยา", "-"))
    chronic = _clean_text(emr_data.get("โรคประจำตัว", "-"))
    prev_med = _clean_text(
        emr_data.get("ประวัติการใช้ยา") or emr_data.get("ประวัติการจ่ายยา") or "-"
    )

    is_allergic = (
        allergy != "-"
        and "ปฏิเสธ" not in allergy
        and "ไม่" not in allergy
        and "ไม่มี" not in allergy
    )

    pdf.set_font(fname, "B", 9.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(
        w_avail,
        5,
        "1. ข้อมูลความปลอดภัยและประวัติผู้ป่วย (Patient Safety Screening)",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(1)

    col3_w = (w_avail - 4) / 3
    y_safety = pdf.get_y()
    safety_h = 16

    safety_cards = [
        ("ประวัติการแพ้ยา", f"[ระวังแพ้ยา] {allergy}" if is_allergic else allergy, is_allergic),
        ("โรคประจำตัว", chronic, False),
        ("ประวัติการใช้ยา / ยาเดิม", prev_med, False),
    ]

    for idx, (label, val, alert) in enumerate(safety_cards):
        bx = pdf.l_margin + idx * (col3_w + 2)
        if alert:
            pdf.set_fill_color(254, 242, 242)
            pdf.set_draw_color(239, 68, 68)
        else:
            pdf.set_fill_color(248, 250, 252)
            pdf.set_draw_color(226, 232, 240)
        pdf.rect(bx, y_safety, col3_w, safety_h, style="DF", round_corners=True, corner_radius=1.5)

        pdf.set_xy(bx + 2.5, y_safety + 1.5)
        pdf.set_font(fname, "B", 7.5)
        pdf.set_text_color(185, 28, 28) if alert else pdf.set_text_color(100, 116, 139)
        pdf.cell(col3_w - 5, 4, label, align="L")

        pdf.set_xy(bx + 2.5, y_safety + 6)
        pdf.set_font(fname, "B" if alert else "", 8.2)
        pdf.set_text_color(185, 28, 28) if alert else pdf.set_text_color(15, 23, 42)
        pdf.multi_cell(col3_w - 5, 4.2, val[:80], align="L")

    pdf.set_y(y_safety + safety_h + 3.5)

    # 4. บันทึกทางการแพทย์ (Clinical SOAP)
    med_notes = _clean_text(
        emr_data.get("บันทึกทางการแพทย์") or emr_data.get("บันทึกการแพทย์") or "-"
    )

    pdf.set_font(fname, "B", 9.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(
        w_avail,
        5,
        "2. บันทึกทางการแพทย์ (Clinical Assessment & SOAP)",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(1)

    y_soap = pdf.get_y()
    pdf.set_font(fname, "", 8.5)
    pdf.set_text_color(30, 41, 59)
    lines_notes = pdf.multi_cell(w_avail - 8, 4.5, med_notes, align="L", dry_run=True)
    box_h = max(14, lines_notes * 4.5 + 4.5)

    if y_soap + box_h > pdf.h - 22:
        pdf.add_page()
        y_soap = pdf.get_y()

    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(pdf.l_margin, y_soap, w_avail, box_h, style="DF", round_corners=True, corner_radius=1.5)

    # แถบเน้นสีฟ้าด้านซ้าย
    pdf.set_fill_color(2, 132, 199)  # Sky 600
    pdf.rect(pdf.l_margin, y_soap, 2, box_h, style="F")

    pdf.set_xy(pdf.l_margin + 4, y_soap + 2.2)
    pdf.multi_cell(w_avail - 8, 4.5, med_notes, align="L")
    pdf.set_y(y_soap + box_h + 3)

    # 5. คำแนะนำจากเภสัชกร & รายการยาที่จ่าย (Plan & Dispensing Advice)
    rx_advice = _clean_text(
        emr_data.get("คำแนะนำจากเภสัชกร") or emr_data.get("คำแนะนำจากเภสัช") or "-"
    )

    pdf.set_font(fname, "B", 9.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(
        w_avail,
        5,
        "3. คำแนะนำจากเภสัชกร & รายการยาที่จ่าย (Plan & Dispensing Advice)",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(1)

    y_rx = pdf.get_y()
    pdf.set_font(fname, "", 8.5)
    pdf.set_text_color(30, 41, 59)
    lines_rx = pdf.multi_cell(w_avail - 8, 4.5, rx_advice, align="L", dry_run=True)
    box_rx_h = max(14, lines_rx * 4.5 + 4.5)

    if y_rx + box_rx_h > pdf.h - 22:
        pdf.add_page()
        y_rx = pdf.get_y()

    pdf.set_fill_color(240, 253, 244)  # Light mint
    pdf.set_draw_color(187, 247, 208)
    pdf.rect(pdf.l_margin, y_rx, w_avail, box_rx_h, style="DF", round_corners=True, corner_radius=1.5)

    # แถบเน้นสีเขียวมรกตด้านซ้าย
    pdf.set_fill_color(16, 185, 129)  # Emerald 500
    pdf.rect(pdf.l_margin, y_rx, 2, box_rx_h, style="F")

    pdf.set_xy(pdf.l_margin + 4, y_rx + 2.2)
    pdf.multi_cell(w_avail - 8, 4.5, rx_advice, align="L")
    pdf.set_y(y_rx + box_rx_h + 3)

    # 6. บทสนทนาการซักประวัติ (Consultation Transcript)
    raw_conv = emr_data.get("บทสนทนาที่จัดเรียงแล้ว", "")
    if dialogue_turns or raw_conv:
        pdf.set_font(fname, "B", 9.5)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(
            w_avail,
            5,
            "4. บันทึกบทสนทนา (Consultation Transcript)",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(1)

        turns = []
        if dialogue_turns and isinstance(dialogue_turns, list):
            turns = dialogue_turns
        elif raw_conv:
            for line in str(raw_conv).split("\n"):
                line = line.strip()
                if not line:
                    continue
                if ":" in line:
                    r, txt = line.split(":", 1)
                    turns.append({"role": r.strip(), "text": txt.strip()})
                else:
                    turns.append({"role": "-", "text": line})

        tag_w = 18
        for t in turns:
            role = str(t.get("role", "")).strip()
            text = _clean_text(t.get("text", ""))
            if not text or text == "-":
                continue

            is_pharma = "เภสัช" in role
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()

            pdf.set_font(fname, "B", 8)
            if is_pharma:
                pdf.set_text_color(2, 132, 199)
                role_tag = "[เภสัชกร]"
            else:
                pdf.set_text_color(71, 85, 105)
                role_tag = "[ผู้ป่วย]"

            pdf.cell(tag_w, 4.3, role_tag, align="L")
            pdf.set_font(fname, "", 8)
            pdf.set_text_color(30, 41, 59)
            pdf.multi_cell(w_avail - tag_w, 4.3, text, align="L")
            pdf.ln(0.8)

    # 7. ส่วนลงนามเภสัชกร
    if pdf.get_y() > pdf.h - 25:
        pdf.add_page()
    pdf.ln(4)
    pdf.set_font(fname, "", 8)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(w_avail / 2, 5, "ลงชื่อ เภสัชกรผู้ประเมินและบริบาล: .....................................................", align="L")
    pdf.cell(w_avail / 2, 5, "วันที่: .....................................................", align="R")

    return bytes(pdf.output())
