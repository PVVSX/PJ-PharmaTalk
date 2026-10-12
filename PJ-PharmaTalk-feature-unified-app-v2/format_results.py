import json
import os
from pathlib import Path

json_path = "/Users/pvvsx/Desktop/PJ/Pharmatalk_project/batch_stt_results.json"
out_path = "/Users/pvvsx/.gemini/antigravity-ide/brain/e191daa0-4722-4176-a380-c8dd389e5cea/transcriptions.md"

with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

markdown_lines = ["# ผลการถอดความและแยกผู้พูด (STT & Diarization Results)\n\n"]
markdown_lines.append("รายงานนี้แสดงข้อความที่ถอดได้จากไฟล์เสียงทั้งหมดที่ทำการทดสอบ เฉพาะไฟล์ที่มีเสียงพูด (ข้ามไฟล์ที่เป็นความเงียบ)\n\n")

count = 0
for filename, info in data.items():
    if info.get('status') == 'success' and info.get('transcript'):
        count += 1
        size_mb = info.get('size_mb', 0)
        transcript = info.get('transcript', '')
        
        markdown_lines.append(f"### 🎵 ไฟล์: `{filename}` ({size_mb:.1f} MB)")
        markdown_lines.append("```text")
        markdown_lines.append(transcript.strip())
        markdown_lines.append("```")
        markdown_lines.append("---\n")

if count == 0:
    markdown_lines.append("ไม่พบข้อความที่ถอดได้สำเร็จในทุกไฟล์")

with open(out_path, 'w', encoding='utf-8') as f:
    f.write("\n".join(markdown_lines))

print(f"Generated {out_path} with {count} transcriptions.")
