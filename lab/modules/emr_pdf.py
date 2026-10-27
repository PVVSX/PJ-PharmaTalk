"""
โมดูลสร้างไฟล์ PDF เวชระเบียนเภสัชกรรมคลินิก (PharmaLog AI Clinical EMR PDF Generator)
ใช้ fpdf2 ร่วมกับแบบอักษร Kanit (และสำรองด้วย Sarabun)
ออกแบบจัดวางสัดส่วนระดับมาตรฐานโรงพยาบาลและคลินิก อ่านง่าย คมชัด และไม่มีบรรทัดซ้อนทับ
"""

import json
import os
import re
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    FPDF_AVAILABLE = True
except ImportError:
    FPDF = object  # type: ignore
    XPos = None  # type: ignore
    YPos = None  # type: ignore
    FPDF_AVAILABLE = False

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
    "\u2013": "-",  # en-dash
    "\u2014": "-",  # em-dash
    "\u2022": "-",  # bullet
    "\u202f": " ",  # narrow no-break space
    "\u00a0": " ",  # no-break space
    "\ufeff": "",   # zero-width no-break space (BOM)
    "\u200b": "",   # zero-width space
    "\u200e": "",   # LTR mark
    "\u200f": "",   # RTL mark
})


def _clean_text(s: Any) -> str:
    """ทำความสะอาดข้อความ แปลง list/dict เป็นบรรทัดที่อ่านง่าย และกรองอักขระพิเศษ Unicode"""
    if s is None:
        return "-"
    if isinstance(s, list):
        items = [str(x).translate(_CHAR_MAP).strip() for x in s if str(x).strip() and str(x).strip() != "-"]
        text = "\n".join(f"- {x}" if not x.startswith("-") else x for x in items)
    elif isinstance(s, dict):
        items = [f"- {k}: {v}" for k, v in s.items() if str(v).strip()]
        text = "\n".join(items).translate(_CHAR_MAP)
    else:
        text = str(s).translate(_CHAR_MAP).strip()
    return text if text else "-"


def _wrap_lines(pdf: "FPDF", width: float, line_h: float, text: str) -> List[str]:
    """คำนวณจำนวนบรรทัดจริงที่จะถูกตัดคำใน fpdf2 อย่างแม่นยำ"""
    cleaned = _clean_text(text)
    try:
        lines = pdf.multi_cell(width, line_h, cleaned, align="L", dry_run=True, output="LINES")
        if isinstance(lines, list) and lines:
            return [str(x) for x in lines]
    except Exception:
        pass
    # สำรองกรณีรุ่นเก่า
    est = max(1, int(len(cleaned) / max(1, (width * 0.42))) + cleaned.count("\n") + 1)
    return [cleaned] * est


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

        self.set_margins(left=14, top=13, right=14)
        self.set_auto_page_break(auto=True, margin=16)

    def header(self) -> None:
        """ส่วนหัวกระดาษสำหรับหน้าที่ 2 เป็นต้นไป"""
        if self.page_no() > 1:
            w_avail = self.w - self.l_margin - self.r_margin
            self.set_fill_color(30, 49, 70)
            self.rect(self.l_margin, 10, w_avail, 0.8, style="F")
            self.set_y(12)
            self.set_font(self.font_family_name, "", 8)
            self.set_text_color(90, 107, 128)
            rec_str = self.record_id[:12].upper() if self.record_id else "-"
            self.cell(
                w_avail * 0.55,
                5,
                f"PharmaLog AI Clinical EMR  |  รหัสอ้างอิง: #{rec_str}",
                align="L",
            )
            self.cell(
                w_avail * 0.45,
                5,
                f"โมเดล: {self.model_name[:42]}",
                align="R",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            self.set_draw_color(226, 232, 240)
            self.set_line_width(0.25)
            self.line(self.l_margin, self.get_y() + 0.5, self.w - self.r_margin, self.get_y() + 0.5)
            self.ln(4)

    def footer(self) -> None:
        """ส่วนท้ายกระดาษพร้อมเส้นคั่นและเลขหน้า"""
        self.set_y(-13)
        w_avail = self.w - self.l_margin - self.r_margin
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.25)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)
        self.set_font(self.font_family_name, "", 7.8)
        self.set_text_color(122, 140, 163)
        self.cell(
            w_avail * 0.7,
            5,
            "เอกสารเวชระเบียนอิเล็กทรอนิกส์สร้างโดยระบบ PharmaLog AI (Clinical Pharmacy Documentation)",
            align="L",
        )
        self.cell(w_avail * 0.3, 5, f"หน้า {self.page_no()} / {{nb}}", align="R")


# เพื่อรักษาความเข้ากันได้ย้อนหลัง
PharmaTalkEMRPDF = PharmaLogEMRPDF


def _draw_section_header(pdf: PharmaLogEMRPDF, num_str: str, title_th: str, title_en: str) -> None:
    """วาดหัวข้อหมวดหมู่พร้อมป้ายหมายเลขและเส้นคั่นอย่างเป็นสัดส่วน"""
    fname = pdf.font_family_name
    w_avail = pdf.w - pdf.l_margin - pdf.r_margin

    if pdf.get_y() > pdf.h - 36:
        pdf.add_page()

    y0 = pdf.get_y()
    # ป้ายตัวเลขสีน้ำเงินเข้ม
    badge_w = 6.5
    badge_h = 6.0
    pdf.set_fill_color(37, 99, 235)
    pdf.rect(pdf.l_margin, y0 + 0.4, badge_w, badge_h, style="F", round_corners=True, corner_radius=1.4)
    pdf.set_xy(pdf.l_margin, y0 + 0.6)
    pdf.set_font(fname, "B", 8.5)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(badge_w, badge_h - 0.4, num_str, align="C")

    # ชื่อหมวดหมู่ภาษาไทย
    pdf.set_xy(pdf.l_margin + badge_w + 2.5, y0)
    pdf.set_font(fname, "B", 10.2)
    pdf.set_text_color(30, 49, 70)
    pdf.cell(115, 6.5, title_th, align="L")

    # ชื่อหมวดหมู่ภาษาอังกฤษชิดขวา
    pdf.set_xy(pdf.l_margin + w_avail - 65, y0 + 0.5)
    pdf.set_font(fname, "", 7.8)
    pdf.set_text_color(122, 140, 163)
    pdf.cell(65, 5.5, title_en, align="R")

    pdf.set_y(y0 + 7.2)
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.25)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2.2)


def generate_emr_pdf(
    emr_data: Dict[str, Any],
    model_name: str = "Typhoon Whisper Large v3",
    record_id: str = "",
    dialogue_turns: Optional[List[Dict[str, str]]] = None,
) -> bytes:
    """
    สร้างไบต์ข้อมูลไฟล์ PDF เวชระเบียนคลินิกและบันทึกการบริบาลทางเภสัชกรรมด้วยฟอนต์ Kanit
    """
    if not FPDF_AVAILABLE:
        return b""

    pdf = PharmaLogEMRPDF(record_id=record_id, model_name=model_name)
    fname = pdf.font_family_name
    pdf.alias_nb_pages()
    pdf.add_page()
    w_avail = pdf.w - pdf.l_margin - pdf.r_margin  # 182 mm

    # ══════════════════════════════════════════════════════════════════════════
    #  ส่วนหัวเอกสาร (Banner Header Card)
    # ══════════════════════════════════════════════════════════════════════════
    y_top = pdf.t_margin
    header_h = 20.5

    # พื้นหลังส่วนหัวสีฟ้าอ่อนสุขุม + แถบสีด้านบน 3 โทน (Navy / Sky / Mint)
    pdf.set_fill_color(247, 250, 255)
    pdf.set_draw_color(214, 228, 245)
    pdf.set_line_width(0.3)
    pdf.rect(pdf.l_margin, y_top, w_avail, header_h, style="DF", round_corners=True, corner_radius=2.5)

    # แถบสีคาดด้านบนสุดของการ์ดหัวกระดาษ
    seg1 = w_avail * 0.50
    seg2 = w_avail * 0.30
    seg3 = w_avail * 0.20
    pdf.set_fill_color(37, 99, 235)   # Primary Blue
    pdf.rect(pdf.l_margin, y_top, seg1, 1.8, style="F")
    pdf.set_fill_color(90, 168, 245)  # Sky Blue
    pdf.rect(pdf.l_margin + seg1, y_top, seg2, 1.8, style="F")
    pdf.set_fill_color(58, 173, 110)  # Clinical Mint
    pdf.rect(pdf.l_margin + seg1 + seg2, y_top, seg3, 1.8, style="F")

    # ข้อความหัวกระดาษฝั่งซ้าย
    pdf.set_xy(pdf.l_margin + 4.5, y_top + 3.2)
    pdf.set_font(fname, "B", 7.8)
    pdf.set_text_color(74, 143, 214)
    pdf.cell(115, 4, "PHARMALOG AI CLINICAL SYSTEM  |  OUTPATIENT PHARMACY CARE", align="L")

    pdf.set_xy(pdf.l_margin + 4.5, y_top + 7.5)
    pdf.set_font(fname, "B", 14.0)
    pdf.set_text_color(30, 49, 70)
    pdf.cell(125, 6.5, "บันทึกการบริบาลทางเภสัชกรรมและเวชระเบียนคลินิก", align="L")

    pdf.set_xy(pdf.l_margin + 4.5, y_top + 14.2)
    pdf.set_font(fname, "", 8.2)
    pdf.set_text_color(90, 107, 128)
    pdf.cell(125, 4.5, "Clinical Electronic Medical Record & Pharmaceutical Care Summary", align="L")

    # ป้ายขวาบน: ชั้นความลับ + รหัสอ้างอิง
    badge_x = pdf.l_margin + w_avail - 52
    pdf.set_fill_color(232, 243, 255)
    pdf.set_draw_color(169, 212, 255)
    pdf.rect(badge_x, y_top + 3.8, 48, 6.0, style="DF", round_corners=True, corner_radius=1.5)
    pdf.set_xy(badge_x, y_top + 4.3)
    pdf.set_font(fname, "B", 7.6)
    pdf.set_text_color(29, 78, 216)
    pdf.cell(48, 5, "เอกสารทางการแพทย์ (CONFIDENTIAL)", align="C")

    rec_short = (record_id[:12].upper() if record_id else "LOCAL-RECORD")
    pdf.set_xy(badge_x, y_top + 11.8)
    pdf.set_font(fname, "B", 8.2)
    pdf.set_text_color(30, 49, 70)
    pdf.cell(48, 4.5, f"REF ID: #{rec_short}", align="R")

    pdf.set_y(y_top + header_h + 2.8)

    # ══════════════════════════════════════════════════════════════════════════
    #  ตารางข้อมูลเมทาดาตา 4 ช่อง (Metadata Grid)
    # ══════════════════════════════════════════════════════════════════════════
    now_str = f"{datetime.now().strftime('%d/%m/%Y %H:%M')} น."
    meta_h = 11.5
    y_meta = pdf.get_y()

    # สัดส่วนความกว้าง 4 คอลัมน์ (รวม 182 mm)
    col_widths = [38.0, 34.0, 66.0, 44.0]
    meta_cols = [
        ("วันที่และเวลาบันทึก", now_str),
        ("รหัสเวชระเบียน", (record_id[:14] if record_id else "-")),
        ("โมเดลประมวลผล AI", _clean_text(model_name)[:38]),
        ("แผนกการบริบาล", "เภสัชกรรมผู้ป่วยนอก (OPD)"),
    ]

    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(220, 230, 242)
    pdf.set_line_width(0.28)
    pdf.rect(pdf.l_margin, y_meta, w_avail, meta_h, style="DF", round_corners=True, corner_radius=2.0)

    curr_x = pdf.l_margin
    for i, ((k, v), cw) in enumerate(zip(meta_cols, col_widths)):
        pdf.set_xy(curr_x + 3.0, y_meta + 1.4)
        pdf.set_font(fname, "", 7.2)
        pdf.set_text_color(122, 140, 163)
        pdf.cell(cw - 6.0, 3.6, k, align="L")

        pdf.set_xy(curr_x + 3.0, y_meta + 5.4)
        pdf.set_font(fname, "B", 8.4)
        pdf.set_text_color(30, 49, 70)
        pdf.cell(cw - 6.0, 4.4, v, align="L")

        if i < len(col_widths) - 1:
            pdf.set_draw_color(226, 232, 240)
            pdf.line(curr_x + cw, y_meta + 1.8, curr_x + cw, y_meta + meta_h - 1.8)
        curr_x += cw

    pdf.set_y(y_meta + meta_h + 3.2)

    # ══════════════════════════════════════════════════════════════════════════
    #  หมวดที่ 1: ข้อมูลความปลอดภัยและประวัติผู้ป่วย (Patient Safety & History)
    # ══════════════════════════════════════════════════════════════════════════
    _draw_section_header(
        pdf,
        "1",
        "ข้อมูลความปลอดภัยและประวัติผู้ป่วย",
        "PATIENT SAFETY & MEDICATION HISTORY",
    )

    allergy = _clean_text(emr_data.get("ประวัติการแพ้ยา", "-"))
    chronic = _clean_text(emr_data.get("โรคประจำตัว", "-"))
    prev_med = _clean_text(
        emr_data.get("ประวัติการใช้ยา") or emr_data.get("ประวัติการจ่ายยา") or "-"
    )

    is_allergy_free = (
        allergy == "-"
        or any(w in allergy for w in ("ปฏิเสธ", "ไม่มี", "ไม่แพ้", "ไม่เคยแพ้"))
    )
    is_allergic = not is_allergy_free

    # แถวที่ 1: ประวัติการแพ้ยา (ซ้าย 50%) + โรคประจำตัว (ขวา 50%)
    gap = 4.0
    half_w = (w_avail - gap) / 2.0
    line_h_card = 4.5

    allergy_display = f"ระวังแพ้ยา: {allergy}" if is_allergic else (
        "ปฏิเสธประวัติแพ้ยา / ไม่พบประวัติแพ้ยา" if allergy in ("-", "ไม่มี", "ปฏิเสธ", "ไม่แพ้") else allergy
    )
    chronic_display = (
        "ปฏิเสธโรคประจำตัว / ไม่ระบุโรคประจำตัว" if chronic in ("-", "ไม่มี", "ปฏิเสธ") else chronic
    )
    prev_med_display = "ไม่ระบุประวัติการใช้ยาก่อนหน้า" if prev_med == "-" else prev_med

    pdf.set_font(fname, "B" if is_allergic else "", 8.8)
    lines_allergy = _wrap_lines(pdf, half_w - 9.0, line_h_card, allergy_display)
    pdf.set_font(fname, "", 8.8)
    lines_chronic = _wrap_lines(pdf, half_w - 9.0, line_h_card, chronic_display)

    row1_lines = max(len(lines_allergy), len(lines_chronic), 1)
    row1_h = max(14.5, 7.8 + row1_lines * line_h_card)

    y_r1 = pdf.get_y()

    # การ์ดซ้าย: ประวัติการแพ้ยา
    bx1 = pdf.l_margin
    if is_allergic:
        pdf.set_fill_color(255, 241, 242)
        pdf.set_draw_color(251, 113, 133)
        accent_c1 = (225, 29, 72)
        label_c1 = (190, 18, 60)
        text_c1 = (159, 18, 57)
        status_tag1 = "แจ้งเตือนแพ้ยา"
    else:
        pdf.set_fill_color(240, 253, 244)
        pdf.set_draw_color(168, 239, 195)
        accent_c1 = (46, 138, 87)
        label_c1 = (46, 138, 87)
        text_c1 = (30, 49, 70)
        status_tag1 = "ปลอดภัย"

    pdf.rect(bx1, y_r1, half_w, row1_h, style="DF", round_corners=True, corner_radius=2.0)
    pdf.set_fill_color(*accent_c1)
    pdf.rect(bx1, y_r1, 2.5, row1_h, style="F")

    pdf.set_xy(bx1 + 5.0, y_r1 + 1.5)
    pdf.set_font(fname, "B", 7.8)
    pdf.set_text_color(*label_c1)
    pdf.cell(half_w - 28.0, 4.0, "ประวัติการแพ้ยา (DRUG ALLERGY)", align="L")

    pdf.set_xy(bx1 + half_w - 23.0, y_r1 + 1.5)
    pdf.set_font(fname, "B", 7.2)
    pdf.cell(20.0, 4.0, f"[{status_tag1}]", align="R")

    pdf.set_xy(bx1 + 5.0, y_r1 + 6.2)
    pdf.set_font(fname, "B" if is_allergic else "", 8.8)
    pdf.set_text_color(*text_c1)
    pdf.multi_cell(half_w - 8.5, line_h_card, allergy_display, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # การ์ดขวา: โรคประจำตัว
    bx2 = pdf.l_margin + half_w + gap
    pdf.set_fill_color(247, 250, 255)
    pdf.set_draw_color(205, 224, 245)
    pdf.rect(bx2, y_r1, half_w, row1_h, style="DF", round_corners=True, corner_radius=2.0)
    pdf.set_fill_color(74, 143, 214)
    pdf.rect(bx2, y_r1, 2.5, row1_h, style="F")

    pdf.set_xy(bx2 + 5.0, y_r1 + 1.5)
    pdf.set_font(fname, "B", 7.8)
    pdf.set_text_color(74, 143, 214)
    pdf.cell(half_w - 8.5, 4.0, "โรคประจำตัว (UNDERLYING CONDITIONS)", align="L")

    pdf.set_xy(bx2 + 5.0, y_r1 + 6.2)
    pdf.set_font(fname, "", 8.8)
    pdf.set_text_color(30, 49, 70)
    pdf.multi_cell(half_w - 8.5, line_h_card, chronic_display, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(y_r1 + row1_h + 2.2)

    # แถวที่ 2 (เต็มความกว้าง): ประวัติการใช้ยา / ยาเดิม
    y_r2 = pdf.get_y()
    pdf.set_font(fname, "", 8.8)
    lines_prev = _wrap_lines(pdf, w_avail - 10.0, line_h_card, prev_med_display)
    row2_h = max(13.5, 7.6 + len(lines_prev) * line_h_card)

    pdf.set_fill_color(250, 251, 253)
    pdf.set_draw_color(216, 226, 238)
    pdf.rect(pdf.l_margin, y_r2, w_avail, row2_h, style="DF", round_corners=True, corner_radius=2.0)
    pdf.set_fill_color(100, 116, 139)
    pdf.rect(pdf.l_margin, y_r2, 2.5, row2_h, style="F")

    pdf.set_xy(pdf.l_margin + 5.0, y_r2 + 1.5)
    pdf.set_font(fname, "B", 7.8)
    pdf.set_text_color(90, 107, 128)
    pdf.cell(w_avail - 10.0, 4.0, "ประวัติการใช้ยาและยาก่อนมาพบเภสัชกร (PAST MEDICATION HISTORY)", align="L")

    pdf.set_xy(pdf.l_margin + 5.0, y_r2 + 6.0)
    pdf.set_font(fname, "", 8.8)
    pdf.set_text_color(30, 49, 70)
    pdf.multi_cell(w_avail - 9.0, line_h_card, prev_med_display, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(y_r2 + row2_h + 3.2)

    # ══════════════════════════════════════════════════════════════════════════
    #  หมวดที่ 2: บันทึกทางการแพทย์และการประเมินอาการ (Clinical Assessment)
    # ══════════════════════════════════════════════════════════════════════════
    _draw_section_header(
        pdf,
        "2",
        "บันทึกทางการแพทย์และการประเมินอาการ",
        "CLINICAL ASSESSMENT & SOAP NOTE",
    )

    med_notes = _clean_text(
        emr_data.get("บันทึกทางการแพทย์") or emr_data.get("บันทึกการแพทย์") or "-"
    )
    line_h_body = 5.0
    pdf.set_font(fname, "", 9.2)
    lines_notes = _wrap_lines(pdf, w_avail - 11.0, line_h_body, med_notes)
    box_soap_h = max(18.0, 9.5 + len(lines_notes) * line_h_body)

    if pdf.get_y() + box_soap_h > pdf.h - 20:
        pdf.add_page()

    y_soap = pdf.get_y()
    pdf.set_fill_color(247, 250, 255)
    pdf.set_draw_color(191, 219, 254)
    pdf.rect(pdf.l_margin, y_soap, w_avail, box_soap_h, style="DF", round_corners=True, corner_radius=2.0)

    # แถบเน้นสีฟ้าด้านซ้าย
    pdf.set_fill_color(37, 99, 235)
    pdf.rect(pdf.l_margin, y_soap, 3.0, box_soap_h, style="F")

    pdf.set_xy(pdf.l_margin + 5.5, y_soap + 2.0)
    pdf.set_font(fname, "B", 8.0)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(w_avail - 10.0, 4.2, "อาการสำคัญ ประวัติการเจ็บป่วยปัจจุบัน และการประเมินทางคลินิก", align="L")

    pdf.set_xy(pdf.l_margin + 5.5, y_soap + 7.0)
    pdf.set_font(fname, "", 9.2)
    pdf.set_text_color(30, 49, 70)
    pdf.multi_cell(w_avail - 10.0, line_h_body, med_notes, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(y_soap + box_soap_h + 4.2)

    # ══════════════════════════════════════════════════════════════════════════
    #  หมวดที่ 3: คำแนะนำจากเภสัชกรและรายการยาที่จ่าย (Plan & Dispensing)
    # ══════════════════════════════════════════════════════════════════════════
    _draw_section_header(
        pdf,
        "3",
        "คำแนะนำจากเภสัชกรและรายการยาที่จ่าย",
        "DISPENSING & PHARMACIST COUNSELING PLAN",
    )

    rx_advice = _clean_text(
        emr_data.get("คำแนะนำจากเภสัชกร") or emr_data.get("คำแนะนำจากเภสัช") or "-"
    )
    pdf.set_font(fname, "", 9.2)
    lines_rx = _wrap_lines(pdf, w_avail - 11.0, line_h_body, rx_advice)
    box_rx_h = max(18.0, 9.5 + len(lines_rx) * line_h_body)

    if pdf.get_y() + box_rx_h > pdf.h - 20:
        pdf.add_page()

    y_rx = pdf.get_y()
    pdf.set_fill_color(242, 253, 246)
    pdf.set_draw_color(167, 243, 208)
    pdf.rect(pdf.l_margin, y_rx, w_avail, box_rx_h, style="DF", round_corners=True, corner_radius=2.0)

    # แถบเน้นสีเขียวมรกตด้านซ้าย
    pdf.set_fill_color(46, 138, 87)
    pdf.rect(pdf.l_margin, y_rx, 3.0, box_rx_h, style="F")

    pdf.set_xy(pdf.l_margin + 5.5, y_rx + 2.0)
    pdf.set_font(fname, "B", 8.0)
    pdf.set_text_color(46, 138, 87)
    pdf.cell(w_avail - 10.0, 4.2, "แผนการรักษา ขนาดและวิธีใช้ยา รวมถึงคำแนะนำการปฏิบัติตัวของผู้ป่วย", align="L")

    pdf.set_xy(pdf.l_margin + 5.5, y_rx + 7.0)
    pdf.set_font(fname, "", 9.2)
    pdf.set_text_color(30, 49, 70)
    pdf.multi_cell(w_avail - 10.0, line_h_body, rx_advice, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(y_rx + box_rx_h + 4.2)

    # ══════════════════════════════════════════════════════════════════════════
    #  หมวดที่ 4: บันทึกบทสนทนาการซักประวัติ (Consultation Transcript)
    # ══════════════════════════════════════════════════════════════════════════
    raw_conv = emr_data.get("บทสนทนาที่จัดเรียงแล้ว", "")
    turns: List[Dict[str, str]] = []
    if dialogue_turns and isinstance(dialogue_turns, list):
        turns = dialogue_turns
    elif raw_conv and str(raw_conv).strip() != "-":
        for line in str(raw_conv).split("\n"):
            line = line.strip()
            if not line:
                continue
            m_br = re.match(r"^\*{0,2}\[(เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\]\*{0,2}:?\s*(.*)$", line)
            if m_br:
                turns.append({"role": m_br.group(1).strip(), "text": m_br.group(2).strip()})
            elif ":" in line:
                r, txt = line.split(":", 1)
                turns.append({"role": r.strip().strip("[]* "), "text": txt.strip()})
            else:
                turns.append({"role": "-", "text": line})

    if turns:
        _draw_section_header(
            pdf,
            "4",
            "บันทึกบทสนทนาการซักประวัติ",
            "CONSULTATION DIALOGUE TRANSCRIPT",
        )

        tag_col_w = 24.0
        txt_col_w = w_avail - tag_col_w - 4.0
        line_h_chat = 4.6

        for idx, t in enumerate(turns):
            role = str(t.get("role") or t.get("speaker") or "").strip()
            raw_txt = str(t.get("text", "")).strip()
            raw_txt = re.sub(
                r"^(?:\*{0,2}\[(?:เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\]\*{0,2}:?|(?:เภสัชกร|เภสัช|ผู้ป่วย|คนไข้)\s*[:：])\s*",
                "",
                raw_txt,
            ).strip()
            text = _clean_text(raw_txt)
            if not text or text == "-":
                continue

            is_pharma = "เภสัช" in role
            pdf.set_font(fname, "", 8.6)
            wrapped = _wrap_lines(pdf, txt_col_w, line_h_chat, text)
            row_h = max(7.2, len(wrapped) * line_h_chat + 2.6)

            if pdf.get_y() + row_h > pdf.h - 20:
                pdf.add_page()

            y_row = pdf.get_y()

            # พื้นหลังแถวสลับสีอ่อนแยกตามผู้พูด
            if is_pharma:
                pdf.set_fill_color(244, 251, 247)
                pdf.set_draw_color(214, 238, 223)
                badge_bg = (220, 252, 231)
                badge_fg = (22, 101, 52)
                role_label = "เภสัชกร"
            else:
                pdf.set_fill_color(248, 250, 252) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
                pdf.set_draw_color(226, 232, 240)
                badge_bg = (224, 242, 254)
                badge_fg = (3, 105, 161)
                role_label = "ผู้ป่วย"

            pdf.rect(pdf.l_margin, y_row, w_avail, row_h, style="DF", round_corners=True, corner_radius=1.4)

            # ป้ายชื่อผู้พูด
            pdf.set_fill_color(*badge_bg)
            pdf.rect(pdf.l_margin + 2.0, y_row + 1.4, tag_col_w - 4.0, 4.5, style="F", round_corners=True, corner_radius=1.0)
            pdf.set_xy(pdf.l_margin + 2.0, y_row + 1.5)
            pdf.set_font(fname, "B", 7.8)
            pdf.set_text_color(*badge_fg)
            pdf.cell(tag_col_w - 4.0, 4.3, role_label, align="C")

            # ข้อความสนทนา
            pdf.set_xy(pdf.l_margin + tag_col_w + 1.5, y_row + 1.3)
            pdf.set_font(fname, "", 8.6)
            pdf.set_text_color(30, 49, 70)
            pdf.multi_cell(
                txt_col_w,
                line_h_chat,
                text,
                align="L",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

            pdf.set_y(y_row + row_h + 1.2)

        pdf.ln(2.0)

    # ══════════════════════════════════════════════════════════════════════════
    #  ส่วนลงนามรับรองเวชระเบียน (Pharmacist Signature & Verification Block)
    # ══════════════════════════════════════════════════════════════════════════
    sig_h = 22.0
    if pdf.get_y() + sig_h > pdf.h - 18:
        pdf.add_page()

    pdf.ln(2.0)
    y_sig = pdf.get_y()
    sig_w = (w_avail - 4.0) / 2.0

    # กล่องซ้าย: เภสัชกรผู้ตรวจและรับรอง
    pdf.set_fill_color(250, 251, 253)
    pdf.set_draw_color(216, 226, 238)
    pdf.rect(pdf.l_margin, y_sig, sig_w, sig_h, style="DF", round_corners=True, corner_radius=2.0)

    pdf.set_xy(pdf.l_margin + 4.0, y_sig + 2.0)
    pdf.set_font(fname, "B", 8.0)
    pdf.set_text_color(74, 143, 214)
    pdf.cell(sig_w - 8.0, 4.0, "สำหรับเภสัชกรผู้ปฏิบัติการ (PHARMACIST VERIFICATION)", align="L")

    pdf.set_xy(pdf.l_margin + 4.0, y_sig + 8.0)
    pdf.set_font(fname, "", 8.2)
    pdf.set_text_color(58, 76, 98)
    pdf.cell(sig_w - 8.0, 4.5, "ลงชื่อ: ............................................................................. เภสัชกร", align="L")

    pdf.set_xy(pdf.l_margin + 4.0, y_sig + 14.2)
    pdf.cell(sig_w - 8.0, 4.5, "วันที่ตรวจรับรอง: ............/............/....................", align="L")

    # กล่องขวา: ข้อมูลรับรองระบบอิเล็กทรอนิกส์
    bx_sig2 = pdf.l_margin + sig_w + 4.0
    pdf.set_fill_color(250, 251, 253)
    pdf.set_draw_color(216, 226, 238)
    pdf.rect(bx_sig2, y_sig, sig_w, sig_h, style="DF", round_corners=True, corner_radius=2.0)

    pdf.set_xy(bx_sig2 + 4.0, y_sig + 2.0)
    pdf.set_font(fname, "B", 8.0)
    pdf.set_text_color(46, 138, 87)
    pdf.cell(sig_w - 8.0, 4.0, "การรับรองเวชระเบียนอิเล็กทรอนิกส์ (SYSTEM ATTESTATION)", align="L")

    pdf.set_xy(bx_sig2 + 4.0, y_sig + 8.0)
    pdf.set_font(fname, "", 8.2)
    pdf.set_text_color(58, 76, 98)
    pdf.cell(sig_w - 8.0, 4.5, f"ประมวลผลด้วยโมเดล: {_clean_text(model_name)[:34]}", align="L")

    pdf.set_xy(bx_sig2 + 4.0, y_sig + 14.2)
    pdf.cell(sig_w - 8.0, 4.5, f"เวลาที่ออกเอกสาร: {now_str}  |  สถานะ: สมบูรณ์", align="L")

    return bytes(pdf.output())
