# -*- coding: utf-8 -*-
"""Generate PharmaLog_User_Manual.pdf (2 pages, Thai) with fpdf2 + Kanit/Sarabun.
Run:  venv/bin/python docs/make_user_manual.py
Edit the CONTENT below when the system changes, then re-run."""
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
OUT = ROOT / "PharmaLog_User_Manual.pdf"

NAVY, BLUE, CYAN = (17, 24, 39), (37, 99, 235), (14, 165, 233)
INK, MUTED, LINE, SOFT = (30, 49, 70), (90, 107, 128), (226, 232, 240), (242, 246, 251)
GREEN, AMBER = (22, 163, 74), (217, 119, 6)
VERSION = "VERSION 3.0 | CLINICAL"


class Manual(FPDF):
    subtitle = ""

    def header(self):
        self.set_fill_color(*CYAN); self.rect(10, 8, 190, 1.6, "F")
        self.set_fill_color(*NAVY); self.rect(10, 9.6, 190, 22, "F")
        self.set_xy(15, 12); self.set_text_color(255, 255, 255); self.set_font("Kanit", "B", 14)
        self.cell(120, 7, "PHARMALOG AI — CLINICAL ASR & EMR SYSTEM")
        self.set_xy(15, 20); self.set_font("Kanit", "", 9); self.set_text_color(203, 213, 225)
        self.cell(120, 5, self.subtitle)
        self.set_draw_color(*CYAN); self.set_line_width(0.3); self.rect(150, 12.5, 46, 15, "D")
        self.set_xy(150, 14); self.set_font("Kanit", "B", 8); self.set_text_color(*CYAN)
        self.cell(46, 5, "OFFICIAL SETUP GUIDE", align="C")
        self.set_xy(150, 20); self.set_font("Kanit", "", 7.5); self.set_text_color(255, 255, 255)
        self.cell(46, 5, VERSION, align="C")
        self.set_y(36)

    def footer(self):
        self.set_draw_color(*LINE); self.line(10, 284, 200, 284)
        self.set_xy(10, 286); self.set_font("Kanit", "", 7.5); self.set_text_color(*MUTED)
        self.cell(150, 4, f"PharmaLog AI Clinical Documentation | ปรับปรุงล่าสุด: {datetime.now():%d/%m/%Y %H:%M}")
        self.cell(40, 4, f"หน้า {self.page_no()} / {{nb}}", align="R")

    # ---------------------------------------------------------------- blocks
    def section(self, num, title, en, tag=""):
        y = self.get_y() + 2
        self.set_fill_color(*SOFT); self.set_draw_color(*LINE); self.rect(10, y, 190, 9, "DF")
        self.set_fill_color(*BLUE); self.rect(10, y, 3, 9, "F"); self.rect(16, y + 1.8, 5.5, 5.5, "F")
        self.set_xy(16, y + 1.8); self.set_text_color(255, 255, 255); self.set_font("Kanit", "B", 8.5)
        self.cell(5.5, 5.5, str(num), align="C")
        self.set_xy(24, y + 1.5); self.set_text_color(*NAVY); self.set_font("Kanit", "B", 10.5)
        w = self.get_string_width(title) + 2; self.cell(w, 6, title)
        self.set_font("Kanit", "", 8); self.set_text_color(*MUTED); self.cell(70, 6, f"  ({en})")
        if tag:
            self.set_xy(150, y + 1.5); self.set_font("Kanit", "B", 8); self.set_text_color(*BLUE)
            self.cell(48, 6, f"[{tag}]", align="R")
        self.set_y(y + 11)

    def para(self, text, size=8.5, color=INK, bold=False, x=14, w=182, h=4.6):
        self.set_x(x); self.set_font("Kanit", "B" if bold else "", size); self.set_text_color(*color)
        self.multi_cell(w, h, text)

    def label(self, text, color=BLUE, x=14, size=9):
        self.set_x(x); self.set_font("Kanit", "B", size); self.set_text_color(*color); self.cell(0, 5.5, text, new_x="LMARGIN", new_y="NEXT")

    def code(self, lines, x=14, w=182):
        y = self.get_y() + 0.5; h = 4.6 * len(lines) + 7
        self.set_fill_color(*NAVY); self.rect(x, y, w, h, "F")
        for i, c in enumerate(((239, 68, 68), (245, 158, 11), (34, 197, 94))):
            self.set_fill_color(*c); self.ellipse(x + 3 + i * 3.5, y + 1.6, 2, 2, "F")
        self.set_xy(x + 14, y + 0.8); self.set_font("Kanit", "", 6.5); self.set_text_color(148, 163, 184); self.cell(60, 3, "Terminal")
        self.set_text_color(125, 211, 252); self.set_font("Kanit", "B", 8)
        for i, ln in enumerate(lines):
            self.set_xy(x + 4, y + 5 + i * 4.6); self.cell(w - 8, 4.6, ln)
        self.set_y(y + h + 1.5)

    def table(self, headers, rows, widths, size=7.8):
        keep = [i for i, w in enumerate(widths) if w > 0]   # 0-width = unused column (cell(0) would fill the line)
        headers = [headers[i] for i in keep]; widths = [widths[i] for i in keep]
        rows = [[r[i] for i in keep] for r in rows]
        self.set_x(10); self.set_fill_color(*NAVY); self.set_text_color(255, 255, 255); self.set_font("Kanit", "B", size)
        for h, w in zip(headers, widths):
            self.cell(w, 7, " " + h, fill=True)
        self.ln(7)
        for r_i, row in enumerate(rows):
            self.set_x(10); fill = r_i % 2 == 1; self.set_fill_color(*SOFT)
            for c_i, (v, w) in enumerate(zip(row, widths)):
                self.set_font("Kanit", "B" if c_i == 0 else "", size)
                self.set_text_color(*(BLUE if c_i == 1 else INK))
                self.cell(w, 6.6, " " + v, fill=fill)
            self.ln(6.6)
        self.ln(1.5)


def build():
    pdf = Manual(format="A4"); pdf.set_auto_page_break(False)
    for style, f in (("", "Kanit-Regular.ttf"), ("B", "Kanit-SemiBold.ttf")):
        pdf.add_font("Kanit", style, str(FONTS / f))
    pdf.set_text_shaping(True)  # correct Thai vowel/tone placement (needs uharfbuzz)
    pdf.alias_nb_pages()

    # ================================================================ page 1
    pdf.subtitle = "คู่มือการติดตั้งและการเปิดใช้งานระบบ (Setup & User Manual)"
    pdf.add_page()
    pdf.set_fill_color(240, 249, 255); pdf.set_draw_color(186, 230, 253); pdf.rect(10, 36, 190, 13, "DF")
    pdf.set_xy(14, 37.5); pdf.set_font("Kanit", "B", 8.8); pdf.set_text_color(3, 105, 161)
    pdf.cell(0, 5, "ระบบบันทึกบทสนทนาเภสัชกร-ผู้ป่วย → ถอดเสียง (Typhoon) → พจนานุกรมยา → สรุปเวชระเบียน (Groq LLM) → เภสัชกรตรวจทานและยืนยัน")
    pdf.set_xy(14, 43); pdf.set_font("Kanit", "", 8); pdf.set_text_color(*MUTED)
    pdf.cell(0, 4.5, "บันทึกเสียงได้เฉพาะเมื่อคนไข้กดยินยอม (ยกเว้นโหมดหลังบ้าน) และทุกขั้นตอนเก็บหลักฐานการยินยอมไว้ในเครื่อง")
    pdf.set_y(51)

    pdf.section(1, "ติดตั้งบนเครื่องใหม่", "Setup", "macOS / Windows")
    pdf.label("ขั้นตอนที่ 1  โคลนโค้ดและวางไฟล์ที่อยู่นอก Git")
    pdf.code(["$ git clone https://github.com/PVVSX/PharmaLog.git && cd PharmaLog"])
    pdf.para("วางไฟล์: models/typhoon-asr-realtime.nemo  •  .groq_api_key  •  core_api/serviceAccountKey.json (เฉพาะถ้าใช้ Cloud)  "
             "— หรือแตก pharmalog_offline_assets.zip ลงโฟลเดอร์โปรเจกต์", size=8, color=MUTED)
    pdf.ln(1)
    pdf.label("ขั้นตอนที่ 2  ติดตั้ง Python 3.11 และแพ็กเกจ (Python 3.13 ใช้ไม่ได้ เพราะ NeMo)")
    pdf.code(["macOS : ดับเบิลคลิก setup_pharmalog.command",
              "อื่นๆ : python3.11 -m venv venv  แล้ว  venv/bin/pip install -r requirements.txt"])
    pdf.label("ขั้นตอนที่ 3  เปิดระบบ")
    pdf.code(["macOS : ดับเบิลคลิก start_pharmalog.command   (อ่านค่าจาก pharmalog.env, log อยู่ใน logs/)"])
    pdf.para("สคริปต์จะหยุดถ้ามีโปรแกรมอื่นใช้พอร์ตอยู่ และเตือนถ้า RAM ไม่พอสำหรับ Whisper Large v3 (พิมพ์ r เพื่อใช้ Typhoon Realtime แทนชั่วคราว)",
             size=8, color=MUTED)
    pdf.ln(1)

    pdf.section(2, "พอร์ตและการเข้าใช้งาน", "Ports & URLs", "ภาพรวม")
    pdf.table(["ส่วนงาน", "URL", "ไฟล์", "หน้าที่"],
              [["Consent (คนไข้)", "http://localhost:8500", "api.py", "กดยินยอม/ไม่ยินยอม + Bridge API ควบคุมสถานะ"],
               ["เภสัชกร", "http://127.0.0.1:8501", "pharmacist_app.py", "อัดได้เมื่อคนไข้ยินยอม → ส่ง → ตรวจทาน EMR"],
               ["หลังบ้าน", "http://127.0.0.1:8515", "unified_app/app.py", "อัดได้ทันที + ประวัติ + ตั้งค่า"],
               ["Core API", "http://127.0.0.1:8080/docs", "core_api/main.py", "ถอดเสียง → พจนานุกรมยา → สรุป EMR"],
               ["Lab (ไม่บังคับ)", "http://localhost:8525", "run_lab.sh / .bat", "ทดลองโมเดลและพิมพ์ PDF"]],
              [30, 46, 36, 78])

    pdf.section(3, "ตั้งค่าที่สำคัญ (pharmalog.env)", "Settings", "")
    pdf.table(["ตัวแปร", "ค่าเริ่มต้น", "", "ความหมาย"],
              [["PHARMALOG_STT_ENGINE", "whisper", "", "whisper = Typhoon Whisper Large v3 (RAM 16 GB+) / realtime = เบา"],
               ["PHARMALOG_DISABLE_CLOUD", "(ว่าง)", "", "1 = ไม่เขียน Firestore — ต้องตั้งทุกครั้งที่ทดสอบ"],
               ["PHARMALOG_CONSENT_TTL", "120", "", "วินาทีที่ consent ใช้ได้ก่อนเริ่มอัด"],
               ["PHARMALOG_RECORDING_MAX_S", "1800", "", "ปลดสถานะกำลังอัดที่ค้าง (ปิดเบราว์เซอร์กลางคัน)"],
               ["PHARMALOG_ROLE_RULES", "1", "", "ใช้กฎตรวจผู้พูดเสริม LLM"]],
              [56, 24, 0, 110])

    # ================================================================ page 2
    pdf.subtitle = "ขั้นตอนการใช้งานในร้านยาและการแก้ปัญหา (Clinical Workflow & Troubleshooting)"
    pdf.add_page()
    pdf.section(4, "ขั้นตอนการใช้งานจริง", "Clinical Workflow", "เภสัชกร 8501")
    steps = [
        ("1. คนไข้กด \"ยินยอมให้บันทึกเสียง\"", "หน้าเภสัชกรปลดล็อกและนับถอยหลัง; ถ้ากด \"ไม่ยินยอม\" ระบบล็อกทันที; ถ้าไม่เริ่มอัดภายในเวลาที่กำหนด consent หมดอายุ"),
        ("2. เภสัชกรกด \"เริ่มอัดเสียง\"", "ระบบตรวจ consent อีกครั้งก่อนเปิดไมโครโฟน (อัดได้สูงสุด 20 นาที) แล้วกด \"หยุดอัดเสียง\""),
        ("3. ฟังทวน → \"ส่งประมวลผล\"", "หรือ \"อัดใหม่\" ถ้าไม่ชัด; ระหว่างประมวลผลจะแสดงขั้น: ถอดเสียง → สรุปเวชระเบียน"),
        ("4. หน้า \"วิเคราะห์ EMR\"", "ดูบทสนทนาแยกผู้พูด ข้อความดิบ และคำที่พจนานุกรมยาแก้; แก้ไขฟอร์มแล้วกด \"ยืนยันและบันทึกเวชระเบียน\""),
        ("5. \"บันทึกผู้ป่วยรายใหม่\"", "ระบบกลับไปรอคนไข้รายถัดไป; consent ของเคสนี้ถูกผูกกับเลขงานและไฟล์เสียงแล้ว"),
    ]
    for t, d in steps:
        pdf.label(t, color=NAVY, size=8.8)
        pdf.para(d, size=8, color=MUTED, x=18, w=178)
    pdf.para("โหมดหลังบ้าน (8515) ใช้ขั้นตอน 2–4 เหมือนกันแต่ไม่ต้องรอ consent", size=8, color=BLUE, bold=True)
    pdf.ln(1)

    pdf.section(5, "เวชระเบียนที่ AI สรุป", "EMR Fields", "ต้องตรวจทานเสมอ")
    pdf.para("ประวัติการแพ้ยา • โรคประจำตัว • ประวัติการจ่ายยา (ยาที่ใช้ก่อนมาครั้งนี้) • บันทึกทางการแพทย์ • คำแนะนำจากเภสัช • "
             "ข้อควรระวังด้านความปลอดภัยของยา (AI แจ้งเตือน ต้องให้เภสัชกรทบทวน) + บทสนทนาที่แยกผู้พูดแล้ว", size=8.3)
    pdf.para("LLM เลือกได้เฉพาะว่าประโยคไหนใครพูด ข้อความบทสนทนามาจากการถอดเสียงจริงเสมอ  •  ระบบเก็บทั้งฉบับ AI และฉบับที่เภสัชกรยืนยัน",
             size=8, color=MUTED)
    pdf.ln(1)

    pdf.section(6, "เมื่อเกิดปัญหา", "Troubleshooting", "")
    pdf.table(["อาการ", "วิธีแก้", "", ""],
              [["ประมวลผลไม่สำเร็จ", "กด \"ลองประมวลผลใหม่\" (ไฟล์เสียงเก็บไว้จนกว่าจะสำเร็จ)", "", ""],
               ["Core API ปิดกลางงาน", "เปิดระบบใหม่ งานค้างจะขึ้นผิดพลาด แล้วกดลองใหม่", "", ""],
               ["\"เรียก LLM ไม่สำเร็จทุกโมเดล\"", "โควตา Groq ต่อนาที/ต่อวันเต็ม รอสักครู่แล้วลองใหม่", "", ""],
               ["หน้าเภสัชกรไม่ปลดล็อก", "ให้คนไข้กดยินยอมใหม่; ถ้าค้างที่กำลังอัด กด \"บันทึกผู้ป่วยรายใหม่\"", "", ""],
               ["เปิด 8501 แล้วเป็นโปรแกรมอื่น", "มีโปรแกรมเก่าใช้พอร์ตอยู่ ปิดโปรแกรมนั้นก่อน", "", ""],
               ["\"ระบบถอดเสียงยังไม่พร้อม\"", "รอโหลดโมเดล (Whisper ครั้งแรกดาวน์โหลด ~6.2 GB) ดู logs/core_api.log", "", ""]],
              [58, 132, 0, 0])

    pdf.section(7, "การทดสอบและความปลอดภัย", "Verification & Security", "")
    pdf.code(["$ python tests/stt_compare.py        # เทียบโมเดลถอดเสียง",
              "$ PHARMALOG_DISABLE_CLOUD=1 python tests/e2e_check.py   # ทดสอบทั้งระบบ → logs/e2e_report.md"])
    pdf.para("ห้ามขึ้น Cloud ระหว่างทดสอบ  •  ห้าม commit ไฟล์เสียง (*.wav), ฐานข้อมูล (*.db), .groq_api_key, .gemini_api_key, serviceAccountKey.json  "
             "•  ไฟล์เสียงและเฉลยใน ground_truth/ เป็นข้อมูลจริงของผู้รับบริการ", size=8, color=AMBER, bold=True)
    pdf.output(str(OUT))
    print("written", OUT)


if __name__ == "__main__":
    build()
