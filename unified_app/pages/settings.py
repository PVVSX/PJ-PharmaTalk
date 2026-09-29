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
from unified_app.modules.emr_groq import check_credentials

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
          <span class="section-title">ตั้งค่า Groq API</span>
          <span class="section-sub">สำหรับวิเคราะห์ EMR</span>
        </div>""", unsafe_allow_html=True)
        
        api_ok, _ = check_credentials()
        if api_ok:
            st.success("Groq API พร้อมใช้งานแล้ว", icon=":material/check_circle:")
        else:
            st.warning("ยังไม่ได้ตั้งค่า Groq API Key กรุณาตั้งค่าให้เรียบร้อยก่อนใช้งานฟังก์ชันสกัด EMR", icon=":material/info:")

        st.caption("หมายเหตุ: API Key ถูกอ่านจาก environment/config ของระบบ ไม่ควรเก็บไว้ในโค้ดหรือไฟล์โปรเจกต์")


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
        
        # Check ASR (from Core API)
        from unified_app.modules.task_api import get_core_health
        try:
            core_health = get_core_health()
            model_ok = bool(core_health.get("asr_loaded"))
            asr_avail = bool(core_health.get("asr_available"))
        except Exception:
            model_ok = False
            asr_avail = False
            
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--grey-200);">
          <span style="font-weight:500;">โมเดลถอดเสียง (Typhoon ASR)</span>
          {
            '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>พร้อมใช้งาน (Core API)</span>' if model_ok
            else ('<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>กำลังโหลด / ไม่พร้อม</span>' if asr_avail else '<span class="status-pill pill-err"><span class="status-dot dot-red"></span>ไม่สามารถเชื่อมต่อ API ได้</span>')
          }
        </div>
        """, unsafe_allow_html=True)
        
        # Check API
        api_ok, api_msg = check_credentials()
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; padding:10px 0;">
          <span style="font-weight:500;">Groq API</span>
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
            st.rerun()
