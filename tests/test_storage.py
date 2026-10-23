import sys
from pathlib import Path
ROOT = Path("/Users/pvvsx/Desktop/PJ/Pharmatalk_project")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core_api.firebase_config import get_firestore_client
import firebase_admin
from firebase_admin import storage

db = get_firestore_client()

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
except Exception as e:
    print(f"Storage error: {e}")
