"""
สคริปต์สำหรับแก้ไข dependency conflicts ระหว่าง pyannote.audio กับ packages อื่นๆ
"""

import subprocess
import sys

def run_command(cmd):
    """รัน command และแสดงผลลัพธ์"""
    print(f"🔄 รัน: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✅ สำเร็จ\n")
        return True
    else:
        print(f"⚠️ เกิดข้อผิดพลาด:\n{result.stderr}\n")
        return False

def fix_dependencies():
    """แก้ไข dependency conflicts"""
    print("="*60)
    print("🔧 แก้ไข Dependency Conflicts")
    print("="*60)
    print()
    
    # 1. Downgrade protobuf
    print("1. กำลัง downgrade protobuf...")
    if not run_command(f"{sys.executable} -m pip install 'protobuf>=5.26.1,<6.0.0' --force-reinstall"):
        print("⚠️ ไม่สามารถ downgrade protobuf ได้")
        return False
    
    # 2. Downgrade numpy
    print("2. กำลัง downgrade numpy...")
    if not run_command(f"{sys.executable} -m pip install 'numpy>=1.21.0,<2.0.0' --force-reinstall"):
        print("⚠️ ไม่สามารถ downgrade numpy ได้")
        return False
    
    # 3. Reinstall pyannote.audio
    print("3. กำลังติดตั้ง pyannote.audio อีกครั้ง...")
    if not run_command(f"{sys.executable} -m pip install pyannote.audio --force-reinstall"):
        print("⚠️ ไม่สามารถติดตั้ง pyannote.audio ได้")
        return False
    
    print("="*60)
    print("✅ แก้ไข dependency conflicts เสร็จสิ้น")
    print("="*60)
    print()
    print("🧪 ทดสอบการติดตั้ง:")
    print("  python -c \"from pyannote.audio import Pipeline; print('✅ pyannote.audio พร้อมใช้งาน')\"")
    print()
    print("⚠️ หมายเหตุ: การแก้ไขนี้อาจทำให้ packages อื่นๆ ที่ต้องการ protobuf 6.x หรือ numpy 2.x ทำงานผิดพลาด")
    print("   แนะนำให้ใช้ virtual environment แยก (ดูที่ FIX_DEPENDENCIES.md)")

if __name__ == "__main__":
    try:
        fix_dependencies()
    except KeyboardInterrupt:
        print("\n❌ ยกเลิกการทำงาน")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ เกิดข้อผิดพลาด: {e}")
        sys.exit(1)
