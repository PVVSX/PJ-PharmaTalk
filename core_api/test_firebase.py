import sys
import os
from pathlib import Path

# Add core_api to path so imports work
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from firebase_config import get_firestore_client

def test_firebase():
    print("กำลังเชื่อมต่อ Firebase...")
    db = get_firestore_client()
    if not db:
        print("❌ เชื่อมต่อ Firebase ไม่สำเร็จ (ไม่มี Credentials หรือ Init ไม่ผ่าน)")
        sys.exit(1)
        
    print("✅ เชื่อมต่อ Firebase สำเร็จ")
    
    # Test Write
    try:
        print("กำลังทดสอบเขียนข้อมูลลง Firestore...")
        doc_ref = db.collection("system_tests").document("ping")
        doc_ref.set({"status": "ok", "message": "Firebase is working!"})
        print("✅ เขียนข้อมูลลง Firestore สำเร็จ")
    except Exception as e:
        print(f"❌ เขียนข้อมูลล้มเหลว: {e}")
        sys.exit(1)
        
    # Test Read
    try:
        print("กำลังทดสอบอ่านข้อมูลจาก Firestore...")
        doc = doc_ref.get()
        if doc.exists:
            print(f"✅ อ่านข้อมูลสำเร็จ: {doc.to_dict()}")
        else:
            print("❌ ไม่พบข้อมูลที่เพิ่งเขียน")
            sys.exit(1)
    except Exception as e:
        print(f"❌ อ่านข้อมูลล้มเหลว: {e}")
        sys.exit(1)

    # Clean up
    try:
        doc_ref.delete()
        print("✅ ลบข้อมูลทดสอบเรียบร้อย")
    except Exception as e:
        print(f"⚠️ ลบข้อมูลล้มเหลว (ข้ามได้): {e}")

    print("\n🎉 ทดสอบระบบ Firebase (Cloud DB) สำเร็จสมบูรณ์ 100%")

if __name__ == "__main__":
    test_firebase()
