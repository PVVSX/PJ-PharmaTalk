# -*- coding: utf-8 -*-
"""Render score explanation markdown tables into PNG images."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = ROOT / "report" / "500" / "evaluation" / "score_explanation_500.md"
OUT_DIR = ROOT / "report" / "500" / "evaluation" / "table_images"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\THSarabunNew Bold.ttf") if bold else Path(r"C:\Windows\Fonts\THSarabunNew.ttf"),
        Path(r"C:\Windows\Fonts\tahomabd.ttf") if bold else Path(r"C:\Windows\Fonts\tahoma.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf") if bold else Path(r"C:\Windows\Fonts\segoeui.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = load_font(42, bold=True)
FONT_SUBTITLE = load_font(28, bold=True)
FONT_BODY = load_font(25)
FONT_BODY_BOLD = load_font(25, bold=True)
FONT_TABLE = load_font(23)
FONT_TABLE_BOLD = load_font(23, bold=True)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), "กA", font=font)
    return box[3] - box[1] + 8


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return [""]

    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if current and text_width(draw, trial, font) > max_width:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current = trial
    if current:
        lines.append(current.rstrip())
    return lines or [""]


def parse_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip().replace("\\|", "|") for cell in line.split("|")]


def parse_sections(markdown: str) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    table_lines: list[str] = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("### "):
            if current is not None:
                current["table_lines"] = table_lines
                sections.append(current)
            current = {"title": line[4:].strip(), "bullets": []}
            table_lines = []
            continue

        if current is None:
            continue

        if line.startswith("- "):
            bullets = current["bullets"]
            assert isinstance(bullets, list)
            bullets.append(line[2:].strip())
        elif line.startswith("|"):
            table_lines.append(line)

    if current is not None:
        current["table_lines"] = table_lines
        sections.append(current)

    return sections


def parsed_table(table_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    if len(table_lines) < 3:
        return [], []
    headers = parse_table_row(table_lines[0])
    rows = [parse_table_row(line) for line in table_lines[2:]]
    return headers, rows


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]+', "_", name.strip())
    return cleaned.strip("_") or "table"


def draw_multiline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    lines: list[str],
    font: ImageFont.ImageFont,
    fill: str,
    line_gap: int = 6,
) -> int:
    x, y = xy
    lh = line_height(draw, font)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += lh + line_gap
    return y


def render_section(section: dict[str, object], index: int) -> Path:
    title = str(section["title"])
    bullets = list(section["bullets"])
    headers, rows = parsed_table(list(section["table_lines"]))

    canvas = Image.new("RGB", (1, 1), "white")
    draw = ImageDraw.Draw(canvas)

    width = 1850
    margin = 48
    col_widths = [90, 115, 125, 510, 420, 430]
    table_width = sum(col_widths)
    row_pad_x = 10
    row_pad_y = 12

    title_lines = wrap_text(draw, title, FONT_TITLE, width - (margin * 2))
    bullet_lines: list[tuple[str, list[str]]] = []
    for bullet in bullets:
        bullet_lines.append(("• ", wrap_text(draw, bullet, FONT_BODY, width - (margin * 2) - 24)))

    header_height = max(line_height(draw, FONT_TABLE_BOLD) + (row_pad_y * 2), 52)
    row_heights: list[int] = []
    wrapped_rows: list[list[list[str]]] = []
    for row in rows:
        wrapped_cells: list[list[str]] = []
        for cell, col_width in zip(row, col_widths):
            wrapped_cells.append(wrap_text(draw, cell, FONT_TABLE, col_width - (row_pad_x * 2)))
        wrapped_rows.append(wrapped_cells)
        max_lines = max((len(cell_lines) for cell_lines in wrapped_cells), default=1)
        row_heights.append(max(58, max_lines * line_height(draw, FONT_TABLE) + (row_pad_y * 2)))

    top_height = 40
    top_height += len(title_lines) * (line_height(draw, FONT_TITLE) + 6)
    top_height += 16
    for _, lines in bullet_lines:
        top_height += len(lines) * (line_height(draw, FONT_BODY) + 4) + 4
    top_height += 28

    height = top_height + header_height + sum(row_heights) + 60
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)

    y = 34
    y = draw_multiline(draw, (margin, y), title_lines, FONT_TITLE, "#111827", line_gap=4)
    y += 8
    draw.line((margin, y, width - margin, y), fill="#d1d5db", width=2)
    y += 18

    for prefix, lines in bullet_lines:
        draw.text((margin, y), prefix, font=FONT_BODY_BOLD, fill="#374151")
        y = draw_multiline(draw, (margin + 24, y), lines, FONT_BODY, "#374151", line_gap=3) + 2

    y += 18
    draw.text((margin, y), "ตาราง Sample", font=FONT_SUBTITLE, fill="#111827")
    y += line_height(draw, FONT_SUBTITLE) + 12

    x0 = margin
    y0 = y
    draw.rectangle((x0, y0, x0 + table_width, y0 + header_height), fill="#e5e7eb", outline="#9ca3af")
    x = x0
    for header, col_width in zip(headers, col_widths):
        lines = wrap_text(draw, header, FONT_TABLE_BOLD, col_width - (row_pad_x * 2))
        draw_multiline(draw, (x + row_pad_x, y0 + row_pad_y), lines, FONT_TABLE_BOLD, "#111827", line_gap=1)
        draw.line((x, y0, x, y0 + header_height), fill="#9ca3af", width=1)
        x += col_width
    draw.line((x0 + table_width, y0, x0 + table_width, y0 + header_height), fill="#9ca3af", width=1)

    y = y0 + header_height
    for row, wrapped_cells, row_height in zip(rows, wrapped_rows, row_heights):
        level = row[1] if len(row) > 1 else ""
        if "สูง" in level:
            fill = "#ecfdf5"
        elif "กลาง" in level:
            fill = "#fffbeb"
        elif "ต่ำ" in level:
            fill = "#fef2f2"
        else:
            fill = "#ffffff"
        draw.rectangle((x0, y, x0 + table_width, y + row_height), fill=fill, outline="#d1d5db")

        x = x0
        for cell_lines, col_width in zip(wrapped_cells, col_widths):
            draw_multiline(draw, (x + row_pad_x, y + row_pad_y), cell_lines, FONT_TABLE, "#111827", line_gap=1)
            draw.line((x, y, x, y + row_height), fill="#d1d5db", width=1)
            x += col_width
        draw.line((x0 + table_width, y, x0 + table_width, y + row_height), fill="#d1d5db", width=1)
        y += row_height

    output = OUT_DIR / f"{index:02d}_{safe_filename(title)}.png"
    image.save(output)
    return output


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    markdown = REPORT_MD.read_text(encoding="utf-8")
    sections = parse_sections(markdown)
    outputs = [render_section(section, i) for i, section in enumerate(sections, start=1)]

    print("สร้างรูปตารางแล้ว:")
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
