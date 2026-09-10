# -*- coding: utf-8 -*-
"""
PharmaTalk — Unified App v3.0  (Multi-page Sidebar Navigation)
Pages:
  Page 1 : อัดเสียง        (Audio Recorder)
  Page 2 : ถอดเสียง       (Speech-to-Text — Typhoon ASR)
  Page 3 : วิเคราะห์ EMR  (Azure OpenAI extraction)
  Page 4 : ตั้งค่า         (Settings)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent          # …/Pharmatalk_project
UNIFIED = Path(__file__).resolve().parent              # …/unified_app
RECORD_DIR = ROOT / "record"

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False



from unified_app.modules.stt_typhoon import ASR_AVAILABLE, TyphoonASRRecognizer, transcribe_audio_bytes
from unified_app.modules.emr_gemini   import EMR_FIELDS, check_credentials, extract_emr

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title  = "PharmaTalk — ระบบบันทึกเวชระเบียนอัตโนมัติ",
    page_icon   = ":material/local_hospital:",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)

# Load CSS
_css = UNIFIED / "assets" / "style.css"
if _css.exists():
    st.markdown(f"<style>{_css.read_text('utf-8')}</style>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════
def _init_state() -> None:
    defaults = {
        # Recorder
        "recording":           False,
        "audio_data":          [],
        "recording_thread":    None,
        "last_saved_path":     None,
        "rec_error":           None,
        "cfg_rate":            44100,
        "cfg_channels":        1,
        "cfg_chunk":           1024,
        "cfg_device_index":    None,
        "device_options_cache": None,
        # STT
        "recognizer":          TyphoonASRRecognizer() if ASR_AVAILABLE else None,
        "model_loaded":        False,
        "model_error":         "",
        "stt_result":          "",
        # EMR
        "emr_conv_input":      "",
        "emr_result":          None,
        "emr_error":           "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ══════════════════════════════════════════════════════════════════════════════
#  ENV FILE HELPERS  (used by Settings page)
# ══════════════════════════════════════════════════════════════════════════════
from unified_app.modules.config import read_env_file, write_env_file


# Try loading ASR model once
if not st.session_state.model_loaded and st.session_state.recognizer:
    try:
        if st.session_state.recognizer.load_model():
            st.session_state.model_loaded = True
    except Exception as e:
        st.session_state.model_error = str(e)


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR BRANDING + NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
api_ok, _ = check_credentials()
model_ok  = st.session_state.model_loaded
wav_count = len(list((RECORD_DIR / "audio").glob("*.wav"))) if (RECORD_DIR / "audio").exists() else 0

# ── Pages (Hidden Native Nav) ──
pages = {
    "เมนูหลัก": [
        st.Page("pages/recorder.py",  title="อัดเสียง",      icon=":material/mic:"),
        st.Page("pages/history.py",   title="ประวัติข้อมูล", icon=":material/history:"),
    ],
    "วิเคราะห์": [
        st.Page("pages/emr.py",       title="วิเคราะห์ EMR", icon=":material/medical_services:"),
    ],
    "ระบบ": [
        st.Page("pages/settings.py",  title="ตั้งค่า",        icon=":material/settings:"),
    ],
}

pg = st.navigation(pages, position="hidden")

# ── Sidebar content ──
with st.sidebar:
    # 1. Logo + Brand
    st.markdown("""
    <div class="sidebar-brand">
      <div class="sidebar-logo-wrap">
        <span class="material-symbols-rounded" style="font-size:2.2rem;color:#fff;">local_hospital</span>
      </div>
      <div class="sidebar-brand-text">
        <div class="sidebar-brand-title">PharmaTalk</div>
        <div class="sidebar-brand-sub">Pharmacy EMR System</div>
      </div>
    </div>
    <div class="sidebar-divider"></div>
    """, unsafe_allow_html=True)

    # 2. Custom Navigation
    st.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: rgba(255,255,255,0.6); margin: 12px 0 12px 16px;'>เมนูหลัก</div>", unsafe_allow_html=True)
    st.page_link("pages/recorder.py", label="อัดเสียง", icon=":material/mic:")
    st.page_link("pages/history.py", label="ประวัติข้อมูล", icon=":material/history:")
    
    st.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: rgba(255,255,255,0.6); margin: 24px 0 12px 16px;'>วิเคราะห์</div>", unsafe_allow_html=True)
    st.page_link("pages/emr.py", label="วิเคราะห์ EMR", icon=":material/medical_services:")
    
    st.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: rgba(255,255,255,0.6); margin: 24px 0 12px 16px;'>ระบบ</div>", unsafe_allow_html=True)
    st.page_link("pages/settings.py", label="ตั้งค่า", icon=":material/settings:")
    
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    # 3. Status indicator
    if model_ok and api_ok:
        status_html = '<span class="sidebar-status status-ok"><span class="sidebar-status-dot dot-green"></span>ระบบพร้อมใช้งาน</span>'
    elif api_ok:
        status_html = '<span class="sidebar-status status-warn"><span class="sidebar-status-dot dot-amber"></span>ASR ยังไม่พร้อม</span>'
    elif model_ok:
        status_html = '<span class="sidebar-status status-warn"><span class="sidebar-status-dot dot-amber"></span>API ยังไม่ตั้งค่า</span>'
    else:
        status_html = '<span class="sidebar-status status-info"><span class="sidebar-status-dot dot-blue"></span>กรุณาตั้งค่าระบบ</span>'
    st.markdown(status_html, unsafe_allow_html=True)

# ── Sidebar footer metrics ──
with st.sidebar:
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    stt_count = len(list((RECORD_DIR / "stt").glob("*_stt.txt"))) if (RECORD_DIR / "stt").exists() else 0
    st.markdown(f"""
    <div class="sidebar-metrics">
      <div class="sidebar-metric">
        <span class="material-symbols-rounded" style="font-size:1.1rem;">audio_file</span>
        <span>{wav_count} ไฟล์เสียง</span>
      </div>
      <div class="sidebar-metric">
        <span class="material-symbols-rounded" style="font-size:1.1rem;">description</span>
        <span>{stt_count} เวชระเบียน</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

pg.run()
