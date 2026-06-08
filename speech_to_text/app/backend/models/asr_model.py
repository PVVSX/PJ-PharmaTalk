"""
ASR Model class for Typhoon ASR
Handles model loading and transcription
"""
import os
import time
from typing import Optional

class TyphoonASRRecognizer:
    """Class for Thai speech recognition using Typhoon ASR Real-time"""
    
    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize ASR Recognizer
        
        Args:
            model_path: Path to the .nemo model file. If None, uses default from config
        """
        self.is_loaded = False
        self.device = "cuda" if os.environ.get('CUDA_VISIBLE_DEVICES') else "cpu"
        self.model = None
        
        # Import config here to avoid circular imports
        from ..config import get_model_path
        self.model_path = model_path or get_model_path()
        
    def load_model(self) -> bool:
        """
        Load Typhoon ASR model from local file
        
        Returns:
            bool: True if model loaded successfully, False otherwise
        """
        try:
            # Check if model file exists
            if not os.path.exists(self.model_path):
                error_msg = f"ไม่พบไฟล์โมเดล: {self.model_path}"
                print(f"ERROR: {error_msg}")
                print("กรุณาตรวจสอบว่าไฟล์โมเดลอยู่ในโฟลเดอร์ backend/typhoon-asr-realtime")
                return False
            
            # Try to load using NeMo
            try:
                import nemo.collections.asr as nemo_asr
                
                # Load model from .nemo file
                self.model = nemo_asr.models.ASRModel.restore_from(
                    restore_path=self.model_path,
                    map_location=self.device
                )
                self.model.eval()
                self.is_loaded = True
                print(f"✅ โหลดโมเดลสำเร็จจาก: {os.path.basename(self.model_path)}")
                return True
                
            except ImportError:
                # Fallback to typhoon-asr package
                try:
                    from typhoon_asr import transcribe
                    if callable(transcribe):
                        self.is_loaded = True
                        print("✅ ใช้ typhoon-asr package (fallback mode)")
                        return True
                    else:
                        print("ERROR: Typhoon ASR transcribe function ไม่สามารถเรียกใช้ได้")
                        return False
                except ImportError as e:
                    print(f"ERROR: ไม่พบ NeMo หรือ Typhoon ASR Package: {e}")
                    print("กรุณาติดตั้งด้วยคำสั่ง: pip install nemo_toolkit[asr] หรือ pip install typhoon-asr")
                    return False
            
        except Exception as e:
            print(f"ERROR: เกิดข้อผิดพลาดในการโหลดโมเดล: {e}")
            return False
    
    def transcribe_audio(self, audio_file_path: str) -> str:
        """
        Transcribe audio file to text using Typhoon ASR from local model
        
        Args:
            audio_file_path: Path to the audio file
            
        Returns:
            str: Transcribed text or error message
        """
        if not self.is_loaded:
            return "โมเดลยังไม่ได้โหลด"
        
        try:
            # Wait a bit to ensure file is not locked
            time.sleep(0.1)
            
            # If using NeMo model directly
            if self.model is not None:
                # Use NeMo model to transcribe
                result = self.model.transcribe([audio_file_path])
                
                # NeMo transcribe returns a list of transcripts
                # Handle different return types: Hypothesis objects, strings, or lists
                if isinstance(result, list) and len(result) > 0:
                    first_result = result[0]
                    # Check if it's a Hypothesis object (has 'text' attribute)
                    if hasattr(first_result, 'text'):
                        return str(first_result.text).strip()
                    # Check if it's a Hypothesis object (has 'transcript' attribute)
                    elif hasattr(first_result, 'transcript'):
                        return str(first_result.transcript).strip()
                    # If it's already a string
                    elif isinstance(first_result, str):
                        return first_result.strip()
                    # Otherwise convert to string
                    else:
                        return str(first_result).strip()
                elif isinstance(result, str):
                    return result.strip()
                else:
                    # Handle Hypothesis object directly
                    if hasattr(result, 'text'):
                        return str(result.text).strip()
                    elif hasattr(result, 'transcript'):
                        return str(result.transcript).strip()
                    else:
                        return str(result).strip()
            
            # If using typhoon-asr package (fallback)
            else:
                from typhoon_asr import transcribe
                
                try:
                    result = transcribe(audio_file_path, with_timestamps=False)
                except TypeError:
                    result = transcribe(audio_file_path, with_timestamps=False)
                
                # Handle Typhoon ASR result format
                if isinstance(result, dict) and 'text' in result:
                    hypothesis = result['text']
                    if hasattr(hypothesis, 'text'):
                        return hypothesis.text.strip()
                    else:
                        return str(hypothesis).strip()
                elif isinstance(result, dict):
                    for key in ['transcript', 'transcription', 'result']:
                        if key in result:
                            return str(result[key]).strip()
                    return str(result).strip()
                elif isinstance(result, str):
                    return result.strip()
                elif hasattr(result, 'text'):
                    return result.text.strip()
                elif hasattr(result, 'transcript'):
                    return result.transcript.strip()
                else:
                    return str(result).strip()
                
        except Exception as e:
            return f"เกิดข้อผิดพลาดในการถอดเสียง: {e}"

