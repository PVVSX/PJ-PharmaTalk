"""
Sidebar component for settings and model status
"""
import streamlit as st
import os
from backend.models.asr_model import TyphoonASRRecognizer
from backend.config import get_model_path
from frontend.components.audio_settings import render_audio_settings


def render_sidebar(recognizer: TyphoonASRRecognizer, model_loaded: bool, model_loading: bool = False):
    """
    Render the sidebar with settings and model status
    
    Args:
        recognizer: ASR Recognizer instance
        model_loaded: Whether model is loaded
        model_loading: Whether model is currently loading
    """
    with st.sidebar:
        st.header("⚙️ การตั้งค่า")
        
        # Model status
        st.subheader("สถานะโมเดล")
        if model_loaded:
            st.markdown('<div class="status-box status-success">✅ ASR พร้อมใช้งาน</div>', 
                       unsafe_allow_html=True)
            st.info(f"📁 โหลดจาก: {os.path.basename(recognizer.model_path)}")
            st.success("✅ โมเดลพร้อมใช้งาน - สามารถถอดเสียงได้เลย")
        elif model_loading:
            st.markdown('<div class="status-box status-warning">⏳ กำลังโหลด ASR...</div>', 
                       unsafe_allow_html=True)
            st.info("🔄 กำลังโหลดโมเดลจากไฟล์ local...")
            st.warning("⏳ กรุณารอสักครู่")
        else:
            st.markdown('<div class="status-box status-warning">⏳ กำลังเริ่มต้นระบบ...</div>', 
                       unsafe_allow_html=True)
            st.info("🔄 กำลังเตรียมระบบ...")
        
        # Manual reload button (optional, for troubleshooting)
        if model_loaded:
            st.markdown("---")
            if st.button("🔄 โหลดโมเดลใหม่", type="secondary", help="โหลดโมเดลใหม่ในกรณีที่เกิดปัญหา"):
                st.session_state.model_loaded = False
                st.session_state.model_loading = False
                st.session_state.recognizer = TyphoonASRRecognizer()
                st.rerun()
        
        st.markdown("---")
        
        # Audio settings (using new component)
        render_audio_settings()
        
        st.markdown("---")
        
        # Clear history
        if st.button("🗑️ ล้างประวัติ", use_container_width=True):
            st.session_state.transcription_history = []
            st.rerun()



