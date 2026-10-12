import sys
from pathlib import Path
ROOT = Path("/Users/pvvsx/Desktop/PJ/Pharmatalk_project")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core_api.firebase_config import get_firestore_client
import firebase_admin
from firebase_admin import storage

db = get_firestore_client()
if not db:
    print("Cannot connect to Firestore")
    sys.exit(1)

print("--- FIRESTORE (patients_emr) ---")
try:
    docs = db.collection("patients_emr").order_by("created_at", direction="DESCENDING").limit(5).stream()
    docs = list(docs)
    if not docs:
        print("0 documents found in 'patients_emr'.")
    else:
        for doc in docs:
            data = doc.to_dict()
            print(f"Task ID: {doc.id}")
            print(f"  created_at: {data.get('created_at')}")
            print(f"  audio_filename: {data.get('audio_filename')}")
            print(f"  has_stt: {bool(data.get('stt_text'))}")
            print(f"  has_emr: {bool(data.get('emr_data'))}")
except Exception as e:
    print(f"Firestore error: {e}")

print("\n--- FIREBASE STORAGE (recordings/) ---")
try:
    bucket = storage.bucket()
    blobs = bucket.list_blobs(prefix="recordings/")
    count = 0
    for blob in blobs:
        print(f"File: {blob.name} (Size: {blob.size / 1024:.1f} KB)")
        count += 1
    if count == 0:
        print("0 files found in 'recordings/'.")
    else:
        print(f"Total files: {count}")
except Exception as e:
    print(f"Storage error: {e}")
