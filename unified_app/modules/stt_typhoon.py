"""
Speech-to-Text Module (Typhoon ASR via NeMo)
Directly loads Typhoon ASR Real-time model using NeMo toolkit.
"""
import os
import io
import sys
import tempfile
import torch

try:
    import nemo.collections.asr as nemo_asr
    ASR_AVAILABLE = True
except ImportError:
    ASR_AVAILABLE = False
    print("Warning: NeMo is not installed. Please install 'nemo_toolkit[asr]' to use Typhoon ASR.")

class TyphoonASRRecognizer:
    def __init__(self, model_name: str = "typhoon-ai/typhoon-asr-realtime"):
        self.is_loaded = False
        self.model_name = model_name
        self.model = None
        
        # We will not load the model immediately on init unless explicitly told
        # to save startup time. The load_model() method must be called.

    def load_model(self) -> bool:
        """Downloads (if necessary) and loads the Typhoon model to memory/GPU."""
        if not ASR_AVAILABLE:
            print("Cannot load model: NeMo is not installed.")
            return False
            
        if self.is_loaded:
            return True
            
        print(f"Loading Typhoon ASR Model: {self.model_name} (This may take a while...)")
        try:
            # Check if there is a local model file bundled
            local_model_path = os.path.join(os.path.dirname(__file__), "..", "..", "models", "typhoon-asr-realtime.nemo")
            local_model_path = os.path.abspath(local_model_path)
            
            if os.path.exists(local_model_path):
                print(f"Found local model at {local_model_path}. Restoring from local file...")
                self.model = nemo_asr.models.ASRModel.restore_from(local_model_path)
            else:
                print("No local model found. Downloading from Hugging Face...")
                self.model = nemo_asr.models.ASRModel.from_pretrained(self.model_name)
            
            # Move to GPU if available
            if torch.cuda.is_available():
                self.model = self.model.cuda()
            elif torch.backends.mps.is_available():
                self.model = self.model.to('mps')
                
            self.model.eval()
            self.is_loaded = True
            print("Typhoon ASR Model loaded successfully!")
            return True
        except Exception as e:
            print(f"Error loading Typhoon ASR: {e}")
            self.is_loaded = False
            return False

    def transcribe_audio(self, path: str) -> str:
        """Transcribe an audio file using the local Typhoon model."""
        if not self.is_loaded or self.model is None:
            return "(ระบบถอดเสียงยังไม่พร้อม)"
            
        try:
            # NeMo transcribe function usually takes a list of audio file paths
            transcriptions = self.model.transcribe([path])
            if transcriptions and len(transcriptions) > 0:
                result = transcriptions[0]
                
                # Handle return tuple/list from NeMo
                if isinstance(result, list) or isinstance(result, tuple):
                    result = result[0]
                    
                # Extract text if it's a Hypothesis object
                if hasattr(result, "text"):
                    return str(result.text)
                elif isinstance(result, dict) and "text" in result:
                    return str(result["text"])
                else:
                    return str(result)
            return ""
        except Exception as e:
            return f"(เกิดข้อผิดพลาดในการถอดเสียง: {e})"

def transcribe_audio_bytes(recognizer: TyphoonASRRecognizer, audio_bytes: bytes) -> str:
    """
    Write audio bytes to a temp WAV file and transcribe using the recognizer.
    Returns the transcribed text or an error message string.
    """
    if not audio_bytes:
        return ""

    if not getattr(recognizer, "is_loaded", False):
        return "(ระบบถอดเสียงยังไม่พร้อม)"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        result = recognizer.transcribe_audio(tmp_path)
        text = result if isinstance(result, str) else str(result)

        # ── Post-process: แก้ชื่อยาและคำทางการแพทย์ที่ถอดเสียงผิด ──
        try:
            from unified_app.modules.pharmacy_dict import correct_transcript
            text, _changes = correct_transcript(text)
        except Exception:
            pass  # Fail silently -- dictionary is optional

        return text
    except Exception as exc:
        return f"(ถอดเสียงล้มเหลว: {exc})"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
