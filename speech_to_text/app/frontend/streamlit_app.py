"""
Main Streamlit application
Entry point for the Speech-to-Text UI
"""
import streamlit as st
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.asr_model import TyphoonASRRecognizer
from backend.services.audio_service import AudioRecorder
from frontend.styles import CUSTOM_CSS
from frontend.components.sidebar import render_sidebar
from frontend.components.recording import render_recording_section
from frontend.components.results import render_results_section

# Page configuration
st.set_page_config(
    page_title="Speech-to-Text with Typhoon ASR",
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Apply custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def initialize_session_state():
    """Initialize session state variables"""
    if 'recognizer' not in st.session_state:
        st.session_state.recognizer = TyphoonASRRecognizer()
    
    if 'recorder' not in st.session_state:
        from backend.config import DEFAULT_SAMPLE_RATE, DEFAULT_CHUNK_SIZE, DEFAULT_CHANNELS
        st.session_state.recorder = AudioRecorder(
            sample_rate=DEFAULT_SAMPLE_RATE,
            chunk_size=DEFAULT_CHUNK_SIZE,
            channels=DEFAULT_CHANNELS
        )
    
    if 'transcription_history' not in st.session_state:
        st.session_state.transcription_history = []
    
    if 'model_loaded' not in st.session_state:
        st.session_state.model_loaded = False
    
    if 'model_loading' not in st.session_state:
        st.session_state.model_loading = False
    
    if 'recording' not in st.session_state:
        st.session_state.recording = False
    
    # Initialize audio settings
    from backend.config import DEFAULT_SAMPLE_RATE, DEFAULT_CHUNK_SIZE, DEFAULT_CHANNELS
    if 'cfg_rate' not in st.session_state:
        st.session_state.cfg_rate = DEFAULT_SAMPLE_RATE
    if 'cfg_channels' not in st.session_state:
        st.session_state.cfg_channels = DEFAULT_CHANNELS
    if 'cfg_chunk' not in st.session_state:
        st.session_state.cfg_chunk = DEFAULT_CHUNK_SIZE
    if 'cfg_device_index' not in st.session_state:
        st.session_state.cfg_device_index = None
    if 'device_options_cache' not in st.session_state:
        st.session_state.device_options_cache = None
    if 'error' not in st.session_state:
        st.session_state.error = None


def load_model_automatically():
    """Load model automatically if not loaded yet"""
    if not st.session_state.model_loaded and not st.session_state.model_loading:
        st.session_state.model_loading = True
        
        # Show loading message in main area
        with st.container():
            st.info("🔄 กำลังโหลดโมเดล Typhoon ASR จากไฟล์ local...")
            st.warning("⏳ กรุณารอสักครู่ (อาจใช้เวลา 1-2 นาที)")
            
            # Use spinner for loading indication
            with st.spinner("📂 กำลังอ่านและโหลดโมเดล..."):
                try:
                    if st.session_state.recognizer.load_model():
                        st.session_state.model_loaded = True
                        st.session_state.model_loading = False
                        st.success("✅ โมเดล Typhoon ASR โหลดเสร็จสิ้น!")
                        st.balloons()
                        st.rerun()
                    else:
                        st.session_state.model_loading = False
                        st.error("❌ ไม่สามารถโหลดโมเดลได้")
                        st.error("ลองตรวจสอบการติดตั้ง dependencies หรือ path ของไฟล์โมเดล")
                        
                except Exception as e:
                    st.session_state.model_loading = False
                    st.error(f"❌ เกิดข้อผิดพลาด: {e}")
                    st.error("ลองตรวจสอบการติดตั้ง dependencies")


def main():
    """Main Streamlit application"""
    
    # Initialize session state
    initialize_session_state()
    
    # Header (always show)
    st.markdown('<h1 class="main-header">🎤 Speech-to-Text with Typhoon ASR Real-time</h1>', 
                unsafe_allow_html=True)
    
    # Load model automatically (this will show loading UI)
    if not st.session_state.model_loaded:
        load_model_automatically()
        # Don't render other components while loading
        if not st.session_state.model_loaded:
            return
    
    # Sidebar (only show when model is loaded or loading)
    render_sidebar(
        st.session_state.recognizer,
        st.session_state.model_loaded,
        st.session_state.model_loading
    )
    
    # Main content (only show when model is loaded)
    if st.session_state.model_loaded:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            render_recording_section(
                st.session_state.recognizer,
                st.session_state.recorder,
                st.session_state.model_loaded,
                st.session_state.recording
            )
        
        with col2:
            render_results_section()
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666;'>
        <p>🎤 Speech-to-Text with Typhoon ASR | Powered by Streamlit</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()

