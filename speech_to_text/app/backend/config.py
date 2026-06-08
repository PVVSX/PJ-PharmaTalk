"""
Configuration settings for the Speech-to-Text application
"""
import os

# Model configuration
# โมเดลอยู่ในโฟลเดอร์ backend/typhoon-asr-realtime
MODEL_DIR = "typhoon-asr-realtime"
MODEL_FILE = "typhoon-asr-realtime.nemo"

# Device configuration
DEVICE = "cuda" if os.environ.get('CUDA_VISIBLE_DEVICES') else "cpu"

# Audio configuration
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHUNK_SIZE = 1024
DEFAULT_CHANNELS = 1
SUPPORTED_SAMPLE_RATES = [8000, 16000, 22050, 32000, 44100, 48000]
SUPPORTED_CHUNK_SIZES = [512, 1024, 2048, 4096]
SUPPORTED_AUDIO_FORMATS = ['wav', 'mp3', 'm4a', 'flac']

def get_model_path():
    """
    Get the full path to the model file
    โมเดลอยู่ในโฟลเดอร์ backend/typhoon-asr-realtime
    """
    # ใช้ directory ของไฟล์ config.py (ซึ่งอยู่ใน backend/)
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = os.path.join(backend_dir, MODEL_DIR)
    model_file = os.path.join(model_dir, MODEL_FILE)
    
    if os.path.exists(model_file):
        return model_file
    else:
        # Fallback: ลองหาใน backend directory
        fallback_path = os.path.join(backend_dir, MODEL_DIR, MODEL_FILE)
        if os.path.exists(fallback_path):
            return fallback_path
        # ถ้ายังไม่พบ ให้ใช้ relative path
        return os.path.join(MODEL_DIR, MODEL_FILE)

