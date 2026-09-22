import os
import sys
import json
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from unified_app.modules.emr_groq import extract_emr

conversation = """
เภสัชกร: สวัสดีครับ วันนี้เป็นอะไรมาครับ
คนไข้: ปวดหัว ตัวร้อน มีน้ำมูกครับ
เภสัชกร: เป็นมาตั้งแต่วันไหนครับ
คนไข้: เป็นมา 2 วันแล้วครับ
เภสัชกร: มีประวัติแพ้ยาอะไรไหมครับ
คนไข้: เคยแพ้ยาพาราเซตามอลครับ กินแล้วผื่นขึ้นเต็มตัวเลย
เภสัชกร: อ๋อ แพ้พารานะครับ แล้วมีโรคประจำตัวอะไรไหมครับ
คนไข้: เป็นความดันโลหิตสูงครับ กินยา Amlodipine อยู่
เภสัชกร: ถ้างั้นผมจ่ายยา Ibuprofen ให้แทนพารานะครับ ทานหลังอาหารทันที 1 เม็ดเช้าเย็น อาการน้ำมูกให้ทาน CPM นะครับ 
"""

print("กำลังทดสอบเรียก Groq API...")
try:
    result = extract_emr(conversation)
    print("\n✅ ทดสอบสำเร็จ! ได้ผลลัพธ์ EMR (JSON) ดังนี้:\n")
    print(json.dumps(result, ensure_ascii=False, indent=4))
except Exception as e:
    print(f"\n❌ เกิดข้อผิดพลาด: {e}")
