import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from core_api.firebase_config import get_firestore_client
client = get_firestore_client()
if client:
    print("Firestore client loaded successfully!")
else:
    print("Failed to load Firestore client.")
