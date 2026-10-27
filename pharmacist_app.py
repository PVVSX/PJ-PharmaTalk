# -*- coding: utf-8 -*-
"""
PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ — Pharmacist Portal
Pages:
  Page 1 : อัดเสียง        (Audio Recorder)
  Page 2 : ประวัติข้อมูล     (History)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent          # …/PharmaLog
UNIFIED = ROOT / "unified_app"              # …/unified_app
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RECORD_DIR = ROOT / "record"

from unified_app.modules.emr_groq import check_credentials
from unified_app.modules.task_api import get_core_health

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title  = "PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์",
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
        "last_saved_path":      None,
        "model_loaded":         False,
        "emr_conv_input":       "",
        "emr_result":           None,
        "audio_task_id":        None,
        "last_audio_task_id":   None,
        "audio_task_completed": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    st.session_state["is_backoffice"] = False

_init_state()

# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR BRANDING + NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
api_ok, _ = check_credentials()
try:
    _core_health = get_core_health()
    model_ok = bool(_core_health.get("asr_loaded"))
except Exception:
    model_ok = False
st.session_state.model_loaded = model_ok
wav_count = len(list((RECORD_DIR / "audio").glob("*.wav"))) if (RECORD_DIR / "audio").exists() else 0

# ── Pages (Hidden Native Nav) ──
p_rec = st.Page(str(UNIFIED / "pages/recorder.py"),  title="อัดเสียง",      icon=":material/mic:")
p_hist = st.Page(str(UNIFIED / "pages/history.py"),   title="ประวัติข้อมูล", icon=":material/history:")

pages = {
    "เมนูหลัก": [p_rec, p_hist]
}

pg = st.navigation(pages, position="hidden")

def _nav_link(page, label: str, icon: str) -> None:
    """Sidebar link; the current page is wrapped so CSS can highlight it."""
    is_active = (page == pg) or (getattr(page, "title", None) == getattr(pg, "title", None))
    if is_active:
        with st.container(key="nav_active"):
            st.page_link(page, label=label, icon=icon)
    else:
        st.page_link(page, label=label, icon=icon)

# ── Sidebar content ──
with st.sidebar:
    # 1. Logo + Brand
    st.markdown("""
    <div class="sidebar-brand">
      <div class="sidebar-logo-wrap">
        <span class="material-symbols-rounded" style="font-size:2.2rem;color:#fff;">local_hospital</span>
      </div>
      <div class="sidebar-brand-text">
        <div class="sidebar-brand-title">PharmaLog AI</div>
        <div class="sidebar-brand-sub">ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์</div>
      </div>
    </div>
    <div class="sidebar-divider"></div>
    """, unsafe_allow_html=True)

    # 2. Custom Navigation
    st.markdown("<div class='sidebar-section-label'>เมนูหลัก</div>", unsafe_allow_html=True)
    _nav_link(p_rec, label="อัดเสียง", icon=":material/mic:")
    _nav_link(p_hist, label="ประวัติข้อมูล", icon=":material/history:")
    
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    # 3. Status indicator
    if model_ok and api_ok:
        status_html = '<span class="sidebar-status status-ok"><span class="sidebar-status-dot dot-green"></span>ระบบพร้อมใช้งาน</span>'
    elif model_ok or api_ok:
        status_html = '<span class="sidebar-status"><span class="sidebar-status-dot dot-amber"></span>พร้อมบางส่วน (ตรวจสอบ API)</span>'
    else:
        status_html = '<span class="sidebar-status"><span class="sidebar-status-dot dot-red"></span>รอการเชื่อมต่อระบบหลังบ้าน</span>'
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

