"""
สคริปต์แปลง typhoon_report.md เป็น PDF (ภาษาไทย)
ใช้ fpdf2 + ฟอนต์ Sarabun (Google Fonts)
"""
import os
import re
from fpdf import FPDF

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
FONT_DIR = os.path.join(ROOT_DIR, "fonts")

FONT_REGULAR = os.path.join(FONT_DIR, "Sarabun-Regular.ttf")
FONT_BOLD = os.path.join(FONT_DIR, "Sarabun-Bold.ttf")
FONT_ITALIC = os.path.join(FONT_DIR, "Sarabun-Italic.ttf")

# ──────────────────────────────────────────────
# 1. อ่าน Markdown
# ──────────────────────────────────────────────
md_path = os.path.join(ROOT_DIR, "docs", "reports", "typhoon_full_report.md")
if not os.path.exists(md_path):
    md_path = os.path.join(SCRIPT_DIR, "typhoon_report.md")
with open(md_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# ──────────────────────────────────────────────
# 2. สร้าง PDF Class
# ──────────────────────────────────────────────
class ThaiPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("Sarabun", "", FONT_REGULAR)
        self.add_font("Sarabun", "B", FONT_BOLD)
        self.add_font("Sarabun", "I", FONT_ITALIC)
        self.set_auto_page_break(auto=True, margin=22)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Sarabun", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, "PharmaTalk - AI Model & Token API Report", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Sarabun", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"หน้า {self.page_no()} / {{nb}}", align="C")


def render_inline(pdf, text, base_style="", base_size=12):
    """จัดการ inline markdown: **bold**, `code`, ข้อความปกติ"""
    parts = re.split(r'(\*\*.*?\*\*|`[^`]+`)', text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            pdf.set_font("Sarabun", "B", base_size)
            pdf.set_text_color(26, 35, 126)
            pdf.write(7, part[2:-2])
            pdf.set_font("Sarabun", base_style, base_size)
            pdf.set_text_color(34, 34, 34)
        elif part.startswith("`") and part.endswith("`"):
            pdf.set_font("Sarabun", "", base_size - 1)
            pdf.set_text_color(180, 30, 30)
            pdf.write(7, part[1:-1])
            pdf.set_font("Sarabun", base_style, base_size)
            pdf.set_text_color(34, 34, 34)
        else:
            pdf.write(7, part)


# ──────────────────────────────────────────────
# 3. สร้าง PDF instance
# ──────────────────────────────────────────────
pdf = ThaiPDF()
pdf.alias_nb_pages()
pdf.add_page()
pdf.set_margins(20, 20, 20)
pdf.set_font("Sarabun", "", 12)
pdf.set_text_color(34, 34, 34)

# ──────────────────────────────────────────────
# 4. Parse & Render
# ──────────────────────────────────────────────
in_code_block = False
code_buffer = []
table_rows = []

i = 0
while i < len(lines):
    line = lines[i].rstrip("\n")

    # ── Code block ──
    if line.startswith("```"):
        if not in_code_block:
            in_code_block = True
            code_buffer = []
            i += 1
            continue
        else:
            in_code_block = False
            code_text = "\n".join(code_buffer)
            pdf.set_font("Sarabun", "", 9)
            pdf.set_fill_color(38, 50, 56)
            pdf.set_text_color(238, 255, 255)
            x = pdf.get_x()
            y = pdf.get_y()
            w = pdf.w - pdf.l_margin - pdf.r_margin
            num_lines = code_text.count("\n") + 1
            h = num_lines * 5 + 10
            if y + h > pdf.h - 30:
                pdf.add_page()
                y = pdf.get_y()
            pdf.rect(x, y, w, h, style="F")
            pdf.set_xy(x + 5, y + 5)
            pdf.multi_cell(w - 10, 5, code_text)
            pdf.set_xy(x, y + h + 4)
            pdf.set_text_color(34, 34, 34)
            pdf.set_fill_color(255, 255, 255)
            pdf.set_font("Sarabun", "", 12)
            i += 1
            continue

    if in_code_block:
        code_buffer.append(line)
        i += 1
        continue

    # ── Table ──
    if "|" in line and line.strip().startswith("|"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.match(r'^[-:]+$', c) for c in cells):
            i += 1
            continue
        table_rows.append(cells)
        if i + 1 < len(lines) and "|" in lines[i + 1] and lines[i + 1].strip().startswith("|"):
            i += 1
            continue
        else:
            if table_rows:
                num_cols = max(len(r) for r in table_rows)
                avail_w = pdf.w - pdf.l_margin - pdf.r_margin
                col_w = avail_w / num_cols

                # วัดความกว้างตามเนื้อหา
                col_max = [0] * num_cols
                pdf.set_font("Sarabun", "", 9)
                for row in table_rows:
                    for ci, cell in enumerate(row):
                        if ci < num_cols:
                            clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', cell)
                            clean = re.sub(r'`([^`]+)`', r'\1', clean)
                            tw = pdf.get_string_width(clean) + 8
                            col_max[ci] = max(col_max[ci], tw)
                total_max = sum(col_max)
                if total_max > 0:
                    col_widths = [(cm / total_max) * avail_w for cm in col_max]
                else:
                    col_widths = [col_w] * num_cols

                # Header row
                pdf.set_font("Sarabun", "B", 10)
                pdf.set_fill_color(26, 35, 126)
                pdf.set_text_color(255, 255, 255)
                header = table_rows[0]
                for ci in range(num_cols):
                    cell_text = header[ci] if ci < len(header) else ""
                    cell_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', cell_text)
                    pdf.cell(col_widths[ci], 8, cell_text, border=1, fill=True)
                pdf.ln()

                # Data rows
                pdf.set_font("Sarabun", "", 9)
                pdf.set_text_color(34, 34, 34)
                for ri, row in enumerate(table_rows[1:]):
                    if ri % 2 == 0:
                        pdf.set_fill_color(245, 245, 245)
                    else:
                        pdf.set_fill_color(255, 255, 255)
                    for ci in range(num_cols):
                        cell_text = row[ci] if ci < len(row) else ""
                        cell_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', cell_text)
                        cell_text = re.sub(r'`([^`]+)`', r'\1', cell_text)
                        pdf.cell(col_widths[ci], 7, cell_text[:80], border=1, fill=True)
                    pdf.ln()
                pdf.ln(4)
                pdf.set_fill_color(255, 255, 255)
            table_rows = []
            i += 1
            continue

    # ── Heading H1 ──
    if line.startswith("# ") and not line.startswith("##"):
        pdf.set_font("Sarabun", "B", 24)
        pdf.set_text_color(26, 35, 126)
        pdf.ln(4)
        pdf.cell(0, 14, line[2:], new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y()
        pdf.set_draw_color(26, 35, 126)
        pdf.set_line_width(0.8)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(8)
        pdf.set_text_color(34, 34, 34)
        pdf.set_font("Sarabun", "", 12)
        i += 1
        continue

    # ── Heading H2 ──
    if line.startswith("## "):
        pdf.ln(6)
        pdf.set_font("Sarabun", "B", 17)
        pdf.set_text_color(40, 53, 147)
        pdf.cell(0, 11, line[3:], new_x="LMARGIN", new_y="NEXT")
        y = pdf.get_y()
        pdf.set_draw_color(197, 202, 233)
        pdf.set_line_width(0.4)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(5)
        pdf.set_text_color(34, 34, 34)
        pdf.set_font("Sarabun", "", 12)
        i += 1
        continue

    # ── Heading H3 ──
    if line.startswith("### "):
        pdf.ln(4)
        pdf.set_font("Sarabun", "B", 14)
        pdf.set_text_color(57, 73, 171)
        pdf.cell(0, 9, line[4:], new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf.set_text_color(34, 34, 34)
        pdf.set_font("Sarabun", "", 12)
        i += 1
        continue

    # ── Horizontal rule ──
    if line.strip() == "---":
        pdf.ln(4)
        pdf.set_draw_color(200, 200, 200)
        pdf.set_line_width(0.3)
        y = pdf.get_y()
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(4)
        i += 1
        continue

    # ── Blockquote ──
    if line.startswith("> "):
        text = line[2:]
        pdf.set_fill_color(232, 234, 246)
        x = pdf.get_x()
        y = pdf.get_y()
        w = pdf.w - pdf.l_margin - pdf.r_margin
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        pdf.set_font("Sarabun", "I", 11)
        # วัดความสูง
        str_w = pdf.get_string_width(clean)
        est_lines = max(1, int(str_w / (w - 14)) + 1)
        h = est_lines * 6 + 8
        pdf.rect(x, y, w, h, style="F")
        pdf.set_draw_color(26, 35, 126)
        pdf.set_line_width(1.2)
        pdf.line(x, y, x, y + h)
        pdf.set_xy(x + 8, y + 4)
        pdf.set_text_color(51, 51, 51)
        pdf.multi_cell(w - 14, 6, clean)
        pdf.set_xy(x, y + h + 4)
        pdf.set_text_color(34, 34, 34)
        pdf.set_font("Sarabun", "", 12)
        pdf.set_line_width(0.2)
        i += 1
        continue

    # ── Ordered list ──
    m = re.match(r'^(\d+)\.\s+(.*)', line)
    if m:
        num = m.group(1)
        text = m.group(2)
        pdf.set_font("Sarabun", "B", 12)
        pdf.set_text_color(26, 35, 126)
        pdf.cell(10, 7, f"{num}.")
        pdf.set_font("Sarabun", "", 12)
        pdf.set_text_color(34, 34, 34)
        render_inline(pdf, text)
        pdf.ln(8)
        i += 1
        continue

    # ── Unordered list ──
    if line.startswith("- "):
        text = line[2:]
        pdf.set_font("Sarabun", "", 12)
        pdf.set_text_color(26, 35, 126)
        pdf.cell(8, 7, chr(8226))
        pdf.set_text_color(34, 34, 34)
        render_inline(pdf, text)
        pdf.ln(8)
        i += 1
        continue

    # ── Empty line ──
    if line.strip() == "":
        pdf.ln(3)
        i += 1
        continue

    # ── Normal paragraph ──
    pdf.set_font("Sarabun", "", 12)
    pdf.set_text_color(34, 34, 34)
    render_inline(pdf, line)
    pdf.ln(8)
    i += 1

# ──────────────────────────────────────────────
# 5. บันทึก PDF
# ──────────────────────────────────────────────
output_path = os.path.join(ROOT_DIR, "docs", "reports", "typhoon_full_report.pdf")
pdf.output(output_path)
print(f"สร้างไฟล์ PDF สำเร็จ: {output_path}")
print(f"จำนวนหน้า: {pdf.page_no()}")
