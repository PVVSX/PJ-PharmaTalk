import os
import json

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    clear_screen()
    print("="*50)
    print("   🚀 PharmaTalk - Setup Keys for New Machine")
    print("="*50)
    print("\nสคริปต์นี้จะช่วยคุณตั้งค่า API Keys และไฟล์ที่จำเป็นสำหรับการรันระบบ\n")

    # 1. Groq API Key
    print("📌 1. ตั้งค่า Groq API Key (สำหรับ AI สรุปเวชระเบียน)")
    groq_path = ".groq_api_key"
    if os.path.exists(groq_path):
        print(f"✅ พบไฟล์ {groq_path} อยู่แล้ว")
    else:
        key = input("กรุณาใส่ Groq API Key (ขึ้นต้นด้วย gsk_...): ").strip()
        if key:
            with open(groq_path, "w", encoding="utf-8") as f:
                f.write(key)
            print("✅ บันทึก .groq_api_key สำเร็จ!")
        else:
            print("⚠️ ข้ามการตั้งค่า Groq API Key")

    print("\n" + "-"*50 + "\n")

    # 2. Deepgram API Key (ทางเลือก)
    print("📌 2. ตั้งค่า Deepgram API Key (สำหรับโมเดลแยกเสียงผู้พูด - ถ้ามี)")
    dg_path = ".deepgram_api_key"
    if os.path.exists(dg_path):
        print(f"✅ พบไฟล์ {dg_path} อยู่แล้ว")
    else:
        key = input("กรุณาใส่ Deepgram API Key (ถ้าไม่ใช้ให้กด Enter ผ่านได้เลย): ").strip()
        if key:
            with open(dg_path, "w", encoding="utf-8") as f:
                f.write(key)
            print("✅ บันทึก .deepgram_api_key สำเร็จ!")
        else:
            print("⏭️ ข้ามการตั้งค่า Deepgram")

    print("\n" + "-"*50 + "\n")

    # 3. Firebase Service Account
    print("📌 3. ตรวจสอบไฟล์ฐานข้อมูล Firebase (serviceAccountKey.json)")
    firebase_path = "serviceAccountKey.json"
    if os.path.exists(firebase_path):
        print("✅ พบไฟล์ serviceAccountKey.json แล้ว พร้อมเชื่อมต่อ Cloud!")
    else:
        print("❌ ยังไม่มีไฟล์ serviceAccountKey.json ในโฟลเดอร์นี้")
        print("💡 วิธีแก้: กรุณานำไฟล์ serviceAccountKey.json (ที่ได้จากเพื่อน หรือจาก Firebase Console)")
        print("มาวางไว้ในโฟลเดอร์เดียวกับสคริปต์นี้ เพื่อให้ระบบสามารถบันทึกข้อมูลคนไข้ขึ้น Cloud ได้")

    print("\n" + "="*50)
    print("🎉 การตั้งค่าเบื้องต้นเสร็จสิ้น!")
    print("อย่าลืมตรวจสอบโมเดล Typhoon ASR (.nemo) ว่ามีอยู่ในเครื่องแล้วหรือไม่")
    print("จากนั้นสามารถรันเซิร์ฟเวอร์ด้วยคำสั่งปกติได้เลยครับ")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
