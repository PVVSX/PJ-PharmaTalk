"""
สคริปต์สำหรับแก้ไข AudioDecoder error ใน pyannote.audio
"""

import subprocess
import sys
import os

def run_command(cmd, check=True):
    """รัน command และแสดงผลลัพธ์"""
    print(f"🔄 รัน: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        if result.stdout.strip():
            print(f"✅ {result.stdout.strip()}\n")
        else:
            print(f"✅ สำเร็จ\n")
        return True
    else:
        if check:
            print(f"⚠️ เกิดข้อผิดพลาด:\n{result.stderr}\n")
        return False

def check_audiodecoder():
    """ตรวจสอบว่า AudioDecoder ใช้งานได้หรือไม่"""
    print("🔍 กำลังตรวจสอบ AudioDecoder...")
    try:
        # ลอง import AudioDecoder
        test_cmd = f'{sys.executable} -c "from pyannote.audio.utils.audio import AudioDecoder; print(\'OK\')"'
        result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0 and "OK" in result.stdout:
            print("✅ AudioDecoder ใช้งานได้\n")
            return True
        else:
            print("❌ AudioDecoder ไม่สามารถใช้งานได้\n")
            return False
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการตรวจสอบ: {e}\n")
        return False

def check_versions():
    """ตรวจสอบเวอร์ชันของ packages"""
    print("📦 กำลังตรวจสอบเวอร์ชัน packages...\n")
    
    packages = ["pyannote.audio", "protobuf", "numpy"]
    for pkg in packages:
        cmd = f'{sys.executable} -m pip show {pkg}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            # หาเวอร์ชัน
            for line in result.stdout.split('\n'):
                if line.startswith('Version:'):
                    version = line.split(':')[1].strip()
                    print(f"   {pkg}: {version}")
                    break
        else:
            print(f"   {pkg}: ไม่พบ")
    print()

def fix_audiodecoder():
    """แก้ไข AudioDecoder error"""
    print("="*60)
    print("🔧 แก้ไข AudioDecoder Error")
    print("="*60)
    print()
    
    # ตรวจสอบเวอร์ชันก่อน
    check_versions()
    
    # ตรวจสอบ AudioDecoder
    if check_audiodecoder():
        print("✅ ไม่จำเป็นต้องแก้ไข - AudioDecoder ใช้งานได้แล้ว")
        return True
    
    print("⚠️  ต้องแก้ไข dependency conflicts\n")
    
    # ถามผู้ใช้
    print("วิธีแก้ไข:")
    print("  1. Downgrade protobuf และ numpy (อาจกระทบ packages อื่น)")
    print("  2. ใช้ Virtual Environment (แนะนำ - ปลอดภัยที่สุด)")
    print()
    
    choice = input("เลือกวิธีแก้ไข (1/2) [Enter = 2]: ").strip() or "2"
    
    if choice == "1":
        # วิธีที่ 1: Downgrade packages
        print("\n📋 กำลังแก้ไขด้วยวิธี Downgrade Packages...\n")
        
        # 1. Downgrade protobuf
        print("1️⃣  กำลัง downgrade protobuf...")
        if not run_command(f"{sys.executable} -m pip install 'protobuf>=5.26.1,<6.0.0' --force-reinstall"):
            print("⚠️ ไม่สามารถ downgrade protobuf ได้")
            return False
        
        # 2. Downgrade numpy
        print("2️⃣  กำลัง downgrade numpy...")
        if not run_command(f"{sys.executable} -m pip install 'numpy>=1.21.0,<2.0.0' --force-reinstall"):
            print("⚠️ ไม่สามารถ downgrade numpy ได้")
            return False
        
        # 3. Reinstall pyannote.audio
        print("3️⃣  กำลังติดตั้ง pyannote.audio อีกครั้ง...")
        if not run_command(f"{sys.executable} -m pip install --upgrade --force-reinstall pyannote.audio"):
            print("⚠️ ไม่สามารถติดตั้ง pyannote.audio ได้")
            return False
        
        # ตรวจสอบอีกครั้ง
        print("🔍 กำลังตรวจสอบอีกครั้ง...")
        if check_audiodecoder():
            print("="*60)
            print("✅ แก้ไขสำเร็จ!")
            print("="*60)
            print("\n⚠️  หมายเหตุ: การแก้ไขนี้อาจทำให้ packages อื่นๆ ที่ต้องการ")
            print("   protobuf 6.x หรือ numpy 2.x ทำงานผิดพลาด")
            print("   แนะนำให้ใช้ virtual environment แยก\n")
            return True
        else:
            print("❌ ยังไม่สามารถแก้ไขได้")
            print("   ลองใช้วิธีที่ 2 (Virtual Environment) แทน")
            return False
    
    else:
        # วิธีที่ 2: Virtual Environment
        print("\n📋 วิธีสร้าง Virtual Environment:\n")
        print("="*60)
        print("คำสั่งที่ต้องรัน:")
        print("="*60)
        print()
        print("# สร้าง virtual environment")
        print("python -m venv venv_pyanote")
        print()
        print("# เปิดใช้งาน (Windows)")
        print("venv_pyanote\\Scripts\\activate")
        print()
        print("# เปิดใช้งาน (Linux/Mac)")
        print("source venv_pyanote/bin/activate")
        print()
        print("# ติดตั้ง dependencies")
        print("pip install -r requirements_pyanote.txt")
        print()
        print("# ทดสอบ")
        print("python pyanote.py")
        print()
        print("="*60)
        print()
        
        # ถามว่าต้องการให้สร้างให้อัตโนมัติหรือไม่
        auto = input("ต้องการให้สร้าง virtual environment อัตโนมัติหรือไม่? (y/n) [n]: ").strip().lower()
        
        if auto == 'y':
            venv_name = "venv_pyanote"
            print(f"\n🔄 กำลังสร้าง virtual environment: {venv_name}...")
            
            # สร้าง venv
            if not run_command(f"{sys.executable} -m venv {venv_name}"):
                print("❌ ไม่สามารถสร้าง virtual environment ได้")
                return False
            
            # กำหนด path สำหรับ activate script
            if sys.platform == "win32":
                activate_script = os.path.join(venv_name, "Scripts", "activate")
                pip_path = os.path.join(venv_name, "Scripts", "pip")
            else:
                activate_script = os.path.join(venv_name, "bin", "activate")
                pip_path = os.path.join(venv_name, "bin", "pip")
            
            # ติดตั้ง dependencies
            print(f"🔄 กำลังติดตั้ง dependencies ใน {venv_name}...")
            if os.path.exists("requirements_pyanote.txt"):
                if not run_command(f"{pip_path} install -r requirements_pyanote.txt"):
                    print("⚠️ ไม่สามารถติดตั้ง dependencies ได้")
                    return False
            else:
                if not run_command(f"{pip_path} install pyannote.audio"):
                    print("⚠️ ไม่สามารถติดตั้ง pyannote.audio ได้")
                    return False
            
            print("="*60)
            print("✅ สร้าง virtual environment สำเร็จ!")
            print("="*60)
            print()
            print("📋 วิธีใช้งาน:")
            print()
            if sys.platform == "win32":
                print(f"  {venv_name}\\Scripts\\activate")
            else:
                print(f"  source {venv_name}/bin/activate")
            print("  python pyanote.py")
            print()
            print("="*60)
            return True
        else:
            print("✅ ดูคำแนะนำด้านบนเพื่อสร้าง virtual environment ด้วยตนเอง")
            return True

if __name__ == "__main__":
    try:
        success = fix_audiodecoder()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n❌ ยกเลิกการทำงาน")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ เกิดข้อผิดพลาด: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
