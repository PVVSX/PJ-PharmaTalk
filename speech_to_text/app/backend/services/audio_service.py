"""
Audio recording service
Handles real-time audio recording using PyAudio
Simple recording/clipping audio from microphone
"""
import os
import tempfile
import wave
import pyaudio
import threading
import time
from typing import Optional, List, Dict
from ..config import DEFAULT_SAMPLE_RATE, DEFAULT_CHUNK_SIZE


class AudioRecorder:
    """Class for recording audio in real-time using PyAudio"""
    
    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE, 
                 chunk_size: int = DEFAULT_CHUNK_SIZE,
                 channels: int = 1,
                 device_index: Optional[int] = None):
        """
        Initialize audio recorder
        
        Args:
            sample_rate: Audio sample rate (default: 16000)
            chunk_size: Audio chunk size (default: 1024)
            channels: Number of audio channels (default: 1)
            device_index: Input device index (None for default)
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.device_index = device_index
        self.is_recording = False
        self.pyaudio_instance = None
        self.stream = None
        self.audio_frames = []
        self.recording_thread = None
        self.error = None
        self.format = pyaudio.paInt16
        
    def start_recording(self) -> bool:
        """
        เริ่มอัดเสียงจากไมโครโฟนด้วย PyAudio
        
        Returns:
            bool: True ถ้าเริ่มสำเร็จ, False ถ้าไม่สำเร็จ
        """
        if self.is_recording:
            return False
        
        self.error = None
        self.audio_frames = []
        
        try:
            self.pyaudio_instance = pyaudio.PyAudio()
            
            # เปิด audio stream
            self.stream = self.pyaudio_instance.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                input_device_index=self.device_index
            )
            
            self.is_recording = True
            self.audio_frames = []
            
            # เริ่มบันทึกใน thread แยก
            self.recording_thread = threading.Thread(target=self._record_audio, name="record_audio")
            self.recording_thread.daemon = True
            self.recording_thread.start()
            
            return True
            
        except Exception as e:
            self.error = f"ไม่สามารถเริ่มอัดเสียงได้: {e}"
            if self.pyaudio_instance:
                try:
                    self.pyaudio_instance.terminate()
                except:
                    pass
            return False
    
    def _record_audio(self):
        """บันทึกเสียงใน thread แยก (internal method)"""
        try:
            while self.is_recording:
                try:
                    # อ่านข้อมูลเสียงจาก stream
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    self.audio_frames.append(data)
                    time.sleep(0.01)  # Delay เล็กน้อยเพื่อป้องกันการโอเวอร์โฟลว์
                except Exception as e:
                    self.error = f"ข้อผิดพลาดในการอ่านเสียง: {e}"
                    break
        except Exception as e:
            self.error = f"ข้อผิดพลาดในการอัดเสียง: {e}"
            self.is_recording = False
        finally:
            # ปิด stream
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except:
                    pass
            # ปิด PyAudio
            if self.pyaudio_instance:
                try:
                    self.pyaudio_instance.terminate()
                except:
                    pass
    
    def stop_recording(self) -> Optional[str]:
        """
        หยุดอัดเสียงและบันทึกเป็นไฟล์ WAV
        
        Returns:
            Optional[str]: Path ของไฟล์ WAV ที่บันทึก, หรือ None ถ้าเกิดข้อผิดพลาด
        """
        if not self.is_recording:
            return None
        
        self.is_recording = False
        
        # รอให้ thread บันทึกเสร็จ
        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
        
        # บันทึกเป็นไฟล์ WAV
        if self.audio_frames:
            return self._save_audio_to_file()
        return None
    
    def get_duration(self) -> float:
        """
        คำนวณระยะเวลาการอัดเสียง (วินาที)
        
        Returns:
            float: ระยะเวลาเป็นวินาที
        """
        if not self.audio_frames:
            return 0.0
        
        total_bytes = sum(len(frame) for frame in self.audio_frames)
        total_samples = total_bytes // (pyaudio.get_sample_size(self.format) * self.channels)
        duration = total_samples / self.sample_rate
        return duration
    
    def _save_audio_to_file(self) -> Optional[str]:
        """
        บันทึก audio frames เป็นไฟล์ WAV
        
        Returns:
            Optional[str]: Path ของไฟล์ WAV, หรือ None ถ้าเกิดข้อผิดพลาด
        """
        try:
            import uuid
            temp_filename = f"recording_{uuid.uuid4().hex}.wav"
            temp_file_path = os.path.join(tempfile.gettempdir(), temp_filename)
            
            # เขียนไฟล์ WAV
            with wave.open(temp_file_path, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(pyaudio.get_sample_size(self.format))
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(self.audio_frames))
            
            return temp_file_path
            
        except Exception as e:
            print(f"ERROR: ไม่สามารถบันทึกไฟล์เสียงได้: {e}")
            return None
    
    def get_audio_bytes(self) -> Optional[bytes]:
        """
        ได้ audio data เป็น bytes สำหรับ preview
        
        Returns:
            Optional[bytes]: WAV bytes, หรือ None ถ้าไม่มีข้อมูล
        """
        if not self.audio_frames:
            return None
        
        import io
        buffer = io.BytesIO()
        wf = wave.open(buffer, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(pyaudio.get_sample_size(self.format))
        wf.setframerate(self.sample_rate)
        wf.writeframes(b''.join(self.audio_frames))
        wf.close()
        
        return buffer.getvalue()


class AudioDeviceManager:
    """Manager for audio input devices"""
    
    @staticmethod
    def get_input_devices() -> List[Dict]:
        """
        Get list of available input devices
        
        Returns:
            List[Dict]: List of device information dictionaries
        """
        devices = []
        try:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if int(info.get('maxInputChannels', 0)) > 0:
                    devices.append({
                        'index': i,
                        'name': info.get('name', 'Unknown'),
                        'maxInputChannels': int(info.get('maxInputChannels', 0)),
                        'defaultSampleRate': int(float(info.get('defaultSampleRate', 0))) if 'defaultSampleRate' in info else 0,
                    })
            p.terminate()
        except Exception as e:
            print(f"ERROR: ไม่สามารถสแกน devices ได้: {e}")
        
        return devices
    
    @staticmethod
    def get_microphone_devices() -> List[Dict]:
        """
        Get list of microphone devices only
        
        Returns:
            List[Dict]: List of microphone device information
        """
        all_devices = AudioDeviceManager.get_input_devices()
        mic_devices = [
            d for d in all_devices
            if ('mic' in d.get('name', '').lower()) or 
               ('microphone' in d.get('name', '').lower())
        ]
        return mic_devices if mic_devices else all_devices

