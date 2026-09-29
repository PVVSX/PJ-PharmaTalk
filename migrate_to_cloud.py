import sys
import json
import uuid
from pathlib import Path
from datetime import datetime

ROOT = Path("/Users/pvvsx/Desktop/PJ/Pharmatalk_project")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core_api.firebase_config import get_firestore_client, upload_file_to_storage
import firebase_admin
from firebase_admin import firestore

db = get_firestore_client()
if not db:
    print("Cannot connect to Firestore")
    sys.exit(1)

# Paths for the latest file
base_name = "23-09-26_01-10_000"
audio_path = ROOT / "record" / "audio" / f"{base_name}.wav"
stt_path = ROOT / "record" / "stt" / f"{base_name}_stt.txt"
emr_path = ROOT / "record" / "emr" / f"{base_name}_emr.json"

if not audio_path.exists():
    print("Audio file not found!")
    sys.exit(1)

stt_text = stt_path.read_text(encoding="utf-8") if stt_path.exists() else ""
emr_data = json.loads(emr_path.read_text(encoding="utf-8")) if emr_path.exists() else {}

task_id = str(uuid.uuid4())
audio_filename = f"{task_id}_{base_name}.wav"
destination = f"recordings/{audio_filename}"

# 1. Upload to Storage
print(f"Uploading audio to {destination}...")
try:
    # upload_file_to_storage(str(audio_path), destination)
    print("Upload bypassed for now (bucket not ready)!")
except Exception as e:
    print(f"Failed to upload audio: {e}")
    sys.exit(1)

# 2. Save to Firestore
print(f"Saving metadata to Firestore (Task ID: {task_id})...")
try:
    doc_ref = db.collection("patients_emr").document(task_id)
    doc_ref.set({
        "task_id": task_id,
        "stt_text": stt_text,
        "emr_data": emr_data,
        "audio_filename": audio_filename,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    print("Firestore save successful!")
except Exception as e:
    print(f"Failed to save to Firestore: {e}")
