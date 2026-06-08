import os
import sys
from pythainlp import word_tokenize

# ตั้งค่า encoding สำหรับ Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def segment_text(input_folder, output_folder):
    """
    แบ่งคำจากประโยคในไฟล์ .txt และบันทึกผลลัพธ์
    """
    # สร้างโฟลเดอร์ผลลัพธ์ถ้ายังไม่มี
    os.makedirs(output_folder, exist_ok=True)
    
    # อ่านไฟล์ทั้งหมดในโฟลเดอร์ text
    text_files = [f for f in os.listdir(input_folder) if f.endswith('.txt')]
    
    print(f"พบไฟล์ทั้งหมด: {len(text_files)} ไฟล์")
    
    for filename in text_files:
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)
        
        try:
            # อ่านไฟล์
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.splitlines()
            
            # หาข้อความที่ถอดเสียง
            text = None
            
            # กรณีที่ 1: ไฟล์มีหลายบรรทัด (รูปแบบเดิม - บรรทัดที่ 5)
            if len(lines) >= 5:
                text = lines[4].strip()  # บรรทัดที่ 5 (index 4)
            
            # กรณีที่ 2: ไฟล์มี 1-3 บรรทัด (รูปแบบใหม่)
            elif len(lines) >= 1:
                # หาบรรทัดแรกที่มีข้อความ (ไม่ว่าง)
                for line in lines:
                    line_stripped = line.strip()
                    if line_stripped:  # ถ้าบรรทัดไม่ว่าง
                        text = line_stripped
                        break
            
            # กรณีที่ 3: ไฟล์เป็นข้อความต่อเนื่อง (ไม่มี newline)
            if not text and content.strip():
                text = content.strip()
            
            # ถ้าพบข้อความ ให้แบ่งคำ
            if text:
                # แบ่งคำด้วย pythainlp
                segmented_words = word_tokenize(text, engine='newmm')
                
                # รวมคำที่แบ่งแล้วด้วยช่องว่าง
                segmented_text = ' '.join(segmented_words)
                
                # บันทึกผลลัพธ์
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(f"📄 {filename}\n\n")
                    f.write("การถอดเสียง:\n\n")
                    f.write(f"{text}\n\n")
                    f.write("ผลการแบ่งคำ:\n\n")
                    f.write(f"{segmented_text}\n")
                    
                print(f"✓ ประมวลผล: {filename}")
            else:
                # ถ้าไฟล์ว่าง ให้สร้างไฟล์เปล่า
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(f"📄 {filename}\n\n")   
                    f.write("การถอดเสียง:\n\n")
                    f.write("\n\n")
                    f.write("ผลการแบ่งคำ:\n\n")
                    f.write("\n")
                print(f"⚠ ไฟล์ว่าง: {filename}")
                
        except Exception as e:
            print(f"✗ เกิดข้อผิดพลาดในการประมวลผล {filename}: {str(e)}")
    
    print("\nเสร็จสิ้น!")

if __name__ == "__main__":
    # หา directory ของไฟล์นี้ (nlp/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # กำหนด path ของโฟลเดอร์ (relative to script directory)
    input_folder = os.path.join(script_dir, "text")
    output_folder = os.path.join(script_dir, "nlp_result")
    
    segment_text(input_folder, output_folder)

