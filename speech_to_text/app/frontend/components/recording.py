"""
Recording component for audio recording and file upload
Simple audio recording/clipping using PyAudio
"""
import streamlit as st
import tempfile
import os
import uuid
import time
from datetime import datetime
from backend.services.audio_service import AudioRecorder
from backend.models.asr_model import TyphoonASRRecognizer
from backend.config import SUPPORTED_AUDIO_FORMATS


def get_audio_duration(audio_file_path: str) -> float:
    """
    หาความยาวของไฟล์เสียง (วินาที)
    
    Args:
        audio_file_path: Path ของไฟล์เสียง
        
    Returns:
        float: ความยาวของไฟล์เสียงเป็นวินาที, หรือ 0.0 ถ้าเกิดข้อผิดพลาด
    """
    try:
        import soundfile as sf
        with sf.SoundFile(audio_file_path) as f:
            duration = len(f) / f.samplerate
            return duration
    except Exception as e:
        # Fallback: ลองใช้ wave สำหรับไฟล์ WAV
        try:
            import wave
            with wave.open(audio_file_path, 'rb') as wf:
                frames = wf.getnframes()
                sample_rate = wf.getframerate()
                duration = frames / float(sample_rate)
                return duration
        except:
            print(f"ERROR: ไม่สามารถหาความยาวของไฟล์เสียงได้: {e}")
            return 0.0


def calculate_average_time_per_second(processing_times: list, audio_durations: list) -> dict:
    """
    คำนวณเวลาเฉลี่ยต่อวินาทีต่อไฟล์
    
    Args:
        processing_times: List ของเวลาที่ใช้ในการประมวลผลแต่ละไฟล์ (วินาที)
        audio_durations: List ของความยาวไฟล์เสียงแต่ละไฟล์ (วินาที)
        
    Returns:
        dict: Dictionary ที่มีข้อมูลสถิติ:
            - 'average_time_per_second': เวลาเฉลี่ยต่อวินาที (วินาที)
            - 'total_processing_time': เวลารวมที่ใช้ในการประมวลผล (วินาที)
            - 'total_audio_duration': ความยาวรวมของไฟล์เสียงทั้งหมด (วินาที)
            - 'per_file_stats': List ของข้อมูลแต่ละไฟล์
    """
    if not processing_times or not audio_durations or len(processing_times) != len(audio_durations):
        return {
            'average_time_per_second': 0.0,
            'total_processing_time': 0.0,
            'total_audio_duration': 0.0,
            'per_file_stats': []
        }
    
    total_processing_time = sum(processing_times)
    total_audio_duration = sum(audio_durations)
    
    # คำนวณเวลาเฉลี่ยต่อวินาที
    if total_audio_duration > 0:
        average_time_per_second = total_processing_time / total_audio_duration
    else:
        average_time_per_second = 0.0
    
    # สร้างข้อมูลแต่ละไฟล์
    per_file_stats = []
    for i, (proc_time, audio_dur) in enumerate(zip(processing_times, audio_durations)):
        if audio_dur > 0:
            time_per_sec = proc_time / audio_dur
        else:
            time_per_sec = 0.0
        
        per_file_stats.append({
            'file_index': i + 1,
            'processing_time': proc_time,
            'audio_duration': audio_dur,
            'time_per_second': time_per_sec
        })
    
    return {
        'average_time_per_second': average_time_per_second,
        'total_processing_time': total_processing_time,
        'total_audio_duration': total_audio_duration,
        'per_file_stats': per_file_stats
    }


def render_recording_section(recognizer: TyphoonASRRecognizer, recorder: AudioRecorder, 
                            model_loaded: bool, recording: bool):
    """
    Render the recording section with improved UI
    
    Args:
        recognizer: ASR Recognizer instance
        recorder: AudioRecorder instance
        model_loaded: Whether model is loaded
        recording: Whether currently recording
    """
    st.header("🎙️ บันทึกเสียง")
    
    if not model_loaded:
        st.warning("⚠️ กรุณาโหลดโมเดลก่อน")
        return
    
    # Single big centered toggle button (inspired by record.py)
    left, center, right = st.columns([1, 4, 1])
    
    with center:
        # Toggle button label
        label = "⏹️ หยุดบันทึก" if recording else "🔴 เริ่มบันทึก"
        
        if st.button(label, key="record_toggle_button", use_container_width=True):
            if not recording:
                # Start recording
                # Get settings from session state
                sample_rate = st.session_state.get('cfg_rate', 16000)
                channels = st.session_state.get('cfg_channels', 1)
                chunk_size = st.session_state.get('cfg_chunk', 1024)
                device_index = st.session_state.get('cfg_device_index', None)
                
                # Update recorder settings
                recorder.sample_rate = sample_rate
                recorder.channels = channels
                recorder.chunk_size = chunk_size
                recorder.device_index = device_index
                
                if recorder.start_recording():
                    st.session_state.recording = True
                    st.session_state.error = None
                    st.rerun()
            else:
                # Stop recording and auto-transcribe
                st.session_state.recording = False
                audio_file = recorder.stop_recording()
                
                if audio_file:
                    process_audio(recognizer, audio_file, source='recording')
                else:
                    st.error("❌ ไม่สามารถบันทึกเสียงได้")
                    if recorder.error:
                        st.error(f"Error: {recorder.error}")
        
        # Status under the button
        if recording:
            st.markdown("**🔴 กำลังอัดเสียง...** กดปุ่ม ⏹️ หยุดบันทึก เพื่อหยุด")
            if recorder.audio_frames:
                duration = recorder.get_duration()
                st.caption(f"⏱️ ระยะเวลา: {duration:.1f} วินาที")
        else:
            st.caption("พร้อมอัดเสียง • ปุ่มจะเปลี่ยนเป็น ⏹️ หยุดบันทึก ระหว่างอัด")
        
        # Show error if any
        if recorder.error:
            st.error(f"❌ {recorder.error}")
    
    # Preview audio if available
    if recorder.audio_frames and not recording:
        st.markdown("---")
        st.subheader("🎵 Preview")
        audio_bytes = recorder.get_audio_bytes()
        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
    
    # File upload
    st.markdown("---")
    st.subheader("📁 อัปโหลดไฟล์เสียง")
    
    uploaded_files = st.file_uploader(
        "เลือกไฟล์เสียง (สามารถเลือกหลายไฟล์)", 
        type=SUPPORTED_AUDIO_FORMATS, 
        accept_multiple_files=True
    )
    
    if uploaded_files:
        st.info(f"📂 เลือกไฟล์แล้ว {len(uploaded_files)} ไฟล์")
        
        if st.button("🎵 ถอดเสียงจากไฟล์ทั้งหมด", type="secondary"):
            if model_loaded:
                process_multiple_files(recognizer, uploaded_files)
            else:
                st.warning("⚠️ กรุณาโหลดโมเดลก่อน")


def process_audio(recognizer: TyphoonASRRecognizer, audio_file: str, source: str = 'file', 
                 filename: str = None):
    """
    Process audio file and add to transcription history
    
    Args:
        recognizer: ASR Recognizer instance
        audio_file: Path to audio file
        source: Source of audio ('recording' or 'file')
        filename: Original filename if from file upload
    """
    with st.spinner("กำลังถอดเสียง..."):
        # Get audio duration
        audio_duration = get_audio_duration(audio_file)
        
        # Measure processing time
        start_time = time.time()
        transcription = recognizer.transcribe_audio(audio_file)
        end_time = time.time()
        
        processing_time = end_time - start_time
        
        if transcription and transcription != "โมเดลยังไม่ได้โหลด":
            # Add to history
            timestamp = datetime.now().strftime("%H:%M:%S")
            st.session_state.transcription_history.append({
                'time': timestamp,
                'text': transcription,
                'source': source,
                'filename': filename
            })
            
            st.success("✅ ถอดเสียงเสร็จสิ้น!")
            
            # Display statistics for single file
            if audio_duration > 0:
                time_per_second = processing_time / audio_duration
                st.info(f"⏱️ เวลาที่ใช้: {processing_time:.2f} วินาที | "
                       f"ความยาวไฟล์: {audio_duration:.2f} วินาที | "
                       f"เวลาต่อวินาที: {time_per_second:.3f} วินาที")
            
            # Clean up temporary file
            try:
                if source == 'recording':
                    os.unlink(audio_file)
            except:
                pass
            
            st.rerun()
        else:
            st.error("❌ ไม่สามารถถอดเสียงได้")


def process_multiple_files(recognizer: TyphoonASRRecognizer, uploaded_files):
    """
    Process multiple uploaded files and calculate average time per second per file
    
    Args:
        recognizer: ASR Recognizer instance
        uploaded_files: List of uploaded files
    """
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    success_count = 0
    error_count = 0
    
    # Lists to store processing times and audio durations
    processing_times = []
    audio_durations = []
    file_names = []
    
    for idx, uploaded_file in enumerate(uploaded_files):
        try:
            status_text.text(f"กำลังประมวลผล {idx+1}/{len(uploaded_files)}: {uploaded_file.name}")
            
            # Save uploaded file temporarily
            file_extension = uploaded_file.name.split('.')[-1]
            temp_filename = f"upload_audio_{uuid.uuid4().hex}.{file_extension}"
            temp_file_path = os.path.join(tempfile.gettempdir(), temp_filename)
            
            with open(temp_file_path, 'wb') as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
            
            # Get audio duration before processing
            audio_duration = get_audio_duration(temp_file_path)
            audio_durations.append(audio_duration)
            file_names.append(uploaded_file.name)
            
            # Measure processing time
            start_time = time.time()
            transcription = recognizer.transcribe_audio(temp_file_path)
            end_time = time.time()
            
            processing_time = end_time - start_time
            processing_times.append(processing_time)
            
            if transcription and transcription != "โมเดลยังไม่ได้โหลด":
                # Add to history
                timestamp = datetime.now().strftime("%H:%M:%S")
                st.session_state.transcription_history.append({
                    'time': timestamp,
                    'text': transcription,
                    'source': 'file',
                    'filename': uploaded_file.name
                })
                success_count += 1
            else:
                error_count += 1
            
            # Clean up
            try:
                os.unlink(temp_file_path)
            except:
                pass
            
            # Update progress
            progress_bar.progress((idx + 1) / len(uploaded_files))
            
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาดกับไฟล์ {uploaded_file.name}: {e}")
            error_count += 1
            # Add zero values for failed files
            processing_times.append(0.0)
            audio_durations.append(0.0)
            file_names.append(uploaded_file.name)
    
    # Calculate average time per second
    stats = calculate_average_time_per_second(processing_times, audio_durations)
    
    # Final status
    progress_bar.empty()
    status_text.empty()
    
    if success_count > 0:
        st.success(f"✅ ถอดเสียงสำเร็จ {success_count} ไฟล์")
    if error_count > 0:
        st.warning(f"⚠️ ถอดเสียงไม่สำเร็จ {error_count} ไฟล์")
    
    # Display statistics
    if stats['total_audio_duration'] > 0:
        st.markdown("---")
        st.subheader("📊 สถิติการประมวลผล")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "เวลาเฉลี่ยต่อวินาที",
                f"{stats['average_time_per_second']:.3f} วินาที"
            )
        with col2:
            st.metric(
                "เวลารวมที่ใช้",
                f"{stats['total_processing_time']:.2f} วินาที"
            )
        with col3:
            st.metric(
                "ความยาวไฟล์รวม",
                f"{stats['total_audio_duration']:.2f} วินาที"
            )
        
        # Display per-file statistics in expander
        with st.expander("📋 รายละเอียดแต่ละไฟล์"):
            for stat in stats['per_file_stats']:
                file_idx = stat['file_index'] - 1
                if file_idx < len(file_names):
                    file_name = file_names[file_idx]
                    st.write(f"**ไฟล์ {stat['file_index']}: {file_name}**")
                    st.write(f"  - เวลาที่ใช้: {stat['processing_time']:.2f} วินาที")
                    st.write(f"  - ความยาวไฟล์: {stat['audio_duration']:.2f} วินาที")
                    st.write(f"  - เวลาต่อวินาที: {stat['time_per_second']:.3f} วินาที")
                    st.write("---")
    
    st.rerun()

