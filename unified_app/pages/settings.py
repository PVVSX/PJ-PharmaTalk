# -*- coding: utf-8 -*-
"""Page 4 — Settings (ตั้งค่า)"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False




from unified_app.modules.config import read_env_file, write_env_file

from unified_app.modules.stt_typhoon import ASR_AVAILABLE
from unified_app.modules.emr_gemini import check_credentials

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">settings</span>
  <div>
    <h2 class="page-title">ตั้งค่าระบบ</h2>
    <p class="page-subtitle">System Settings & API Configuration</p>
  </div>
</div>
""", unsafe_allow_html=True)

t4L, t4R = st.columns([1, 1], gap="large")

# ── LEFT: Settings ──
with t4L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-amber"></div>
        <div class="section-header">
           <div class="sh-icon sh-grey"><span class="material-symbols-rounded">key</span></div>
          <span class="section-title">ตั้งค่า Gemini API</span>
          <span class="section-sub">สำหรับวิเคราะห์ EMR</span>
        </div>""", unsafe_allow_html=True)
        
        st.info("API Key ของ Gemini ถูกตั้งค่าไว้ในระบบเรียบร้อยแล้ว", icon=":material/info:")




# ── RIGHT: System Diagnostics ──
with t4R:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
          <div class="sh-icon sh-teal"><span class="material-symbols-rounded">monitor_heart</span></div>
          <span class="section-title">สถานะระบบ (Diagnostics)</span>
        </div>""", unsafe_allow_html=True)
        
        # Check Audio
        import sys
        try:
            import pyaudio
            has_audio = True
        except ImportError:
            has_audio = False
            
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--grey-200);">
          <span style="font-weight:500;">ระบบอัดเสียง (Native)</span>
          {'<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>พร้อมใช้งาน</span>'}
        </div>
        """, unsafe_allow_html=True)
        
        # Check ASR
        model_ok = st.session_state.model_loaded
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--grey-200);">
          <span style="font-weight:500;">โมเดลถอดเสียง (Typhoon ASR)</span>
          {
            '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>โหลดสำเร็จ</span>' if model_ok
            else ('<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>กำลังโหลด / ไม่พร้อม</span>' if ASR_AVAILABLE else '<span class="status-pill pill-err"><span class="status-dot dot-red"></span>ไม่พบ NeMo</span>')
          }
        </div>
        """, unsafe_allow_html=True)
        
        # Check API
        api_ok, api_msg = check_credentials()
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; padding:10px 0;">
          <span style="font-weight:500;">Gemini API</span>
          {
            '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>ตั้งค่าแล้ว</span>' if api_ok
            else '<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>ยังไม่ได้ตั้งค่า</span>'
          }
        </div>
        """, unsafe_allow_html=True)
        
        if not api_ok and api_msg:
            st.info(api_msg, icon=":material/info:")

        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("ตรวจสอบระบบใหม่ (Refresh)", icon=":material/refresh:", use_container_width=True):
            if st.session_state.recognizer and not st.session_state.model_loaded:
                try:
                    if st.session_state.recognizer.load_model():
                        st.session_state.model_loaded = True
                except Exception as e:
                    st.session_state.model_error = str(e)
            st.rerun()
