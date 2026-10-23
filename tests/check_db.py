import sys
from pathlib import Path
ROOT = Path("/Users/pvvsx/Desktop/PJ/Pharmatalk_project")
sys.path.insert(0, str(ROOT))
from core_api.firebase_config import get_firestore_client

db = get_firestore_client()
docs = db.collection("patients_emr").limit(1).stream()
for doc in docs:
    d = doc.to_dict()
    print("STT Length:", len(d.get("stt_text", "")))
    print("EMR Keys:", d.get("emr_data", {}).keys())
