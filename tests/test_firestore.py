import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent))
from core_api.firebase_config import get_firestore_client
db = get_firestore_client()
if db:
    try:
        db.collection("test").document("test").set({"test": "test"})
        print("✅ Firestore is working!")
    except Exception as e:
        print(f"❌ Firestore Error: {e}")
else:
    print("❌ Could not init Firebase")
