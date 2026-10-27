import os
import json

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    clear_screen()
    print("="*60)
    print("   PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์")
    print("   Setup Keys & Credentials for New Machine")
    print("="*60)
    print("\nสคริปต์นี้จะช่วยคุณตั้งค่า API Keys และไฟล์ที่จำเป็นสำหรับการรันระบบ\n")

    # 1. Groq API Key
    print("[1] ตั้งค่า Groq API Key (สำหรับ AI สรุปเวชระเบียน)")
    groq_path = ".groq_api_key"
    if os.path.exists(groq_path):
        print(f"[OK] พบไฟล์ {groq_path} อยู่แล้ว")
    else:
        key = input("กรุณาใส่ Groq API Key (ขึ้นต้นด้วย gsk_...): ").strip()
        if key:
            with open(groq_path, "w", encoding="utf-8") as f:
                f.write(key)
            print("[OK] บันทึก .groq_api_key สำเร็จ!")
        else:
            print("[Warning] ข้ามการตั้งค่า Groq API Key")

    print("\n" + "-"*60 + "\n")

    # 2. Firebase Service Account
    print("[2] ตรวจสอบไฟล์ฐานข้อมูล Firebase (serviceAccountKey.json)")
    firebase_path = "serviceAccountKey.json"
    core_firebase_path = os.path.join("core_api", "serviceAccountKey.json")
    if os.path.exists(firebase_path) or os.path.exists(core_firebase_path):
        print("[OK] พบไฟล์ serviceAccountKey.json แล้ว พร้อมเชื่อมต่อ Cloud!")
    else:
        print("[Notice] ยังไม่มีไฟล์ serviceAccountKey.json")
        print("วิธีแก้: นำไฟล์ serviceAccountKey.json วางไว้ที่โฟลเดอร์ core_api/ หรือแตกไฟล์ offline assets")

    print("\n" + "="*60)
    print("[Completed] การตั้งค่าเบื้องต้นเสร็จสิ้น")
    print("อย่าลืมตรวจสอบโมเดล Typhoon ASR (.nemo) ว่ามีอยู่ในโฟลเดอร์ models/ แล้วหรือไม่")
    print("จากนั้นสามารถรันระบบตามคำสั่งใน README.md หรือรัน ./run_lab.sh ได้เลย")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
