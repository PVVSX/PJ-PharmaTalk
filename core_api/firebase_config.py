import os
import firebase_admin
from firebase_admin import credentials, firestore, storage

def init_firebase():
    # Only initialize if not already initialized
    if not firebase_admin._apps:
        # Use absolute path relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        cred_path = os.environ.get("FIREBASE_CREDENTIALS", os.path.join(current_dir, "serviceAccountKey.json"))
        
        if os.path.exists(cred_path):
            try:
                cred = credentials.Certificate(cred_path)
                options = {}
                bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET", "").strip()
                if bucket_name:
                    options["storageBucket"] = bucket_name
                firebase_admin.initialize_app(cred, options or None)
                print("Firebase Initialized successfully.")
            except Exception as e:
                print(f"Failed to initialize Firebase with credentials: {e}")
        else:
            print(f"Warning: Firebase credentials not found at {cred_path}. Firestore features will not work until this is provided.")
            
def get_firestore_client():
    if not firebase_admin._apps:
        init_firebase()
    
    if firebase_admin._apps:
        return firestore.client()
    return None


def upload_file_to_storage(file_path: str, destination: str) -> str:
    """Upload one local file to Firebase Storage on explicit user request."""
    if not firebase_admin._apps:
        init_firebase()
    if not firebase_admin._apps:
        raise RuntimeError("ยังไม่ได้ตั้งค่า Firebase credentials")
    try:
        blob = storage.bucket().blob(destination)
        blob.upload_from_filename(file_path)
        return destination
    except Exception as exc:
        raise RuntimeError(f"อัปโหลด Cloud ไม่สำเร็จ: {exc}") from exc
