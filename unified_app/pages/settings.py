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
from unified_app.modules.emr_azure import check_credentials

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

# ── LEFT: Azure OpenAI Settings ──
with t4L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-amber"></div>
        <div class="section-header">
          <div class="sh-icon sh-grey"><span class="material-symbols-rounded">key</span></div>
          <span class="section-title">ตั้งค่า Azure OpenAI</span>
          <span class="section-sub">สำหรับวิเคราะห์ EMR</span>
        </div>""", unsafe_allow_html=True)
        
        env_vals = read_env_file()
        new_ep   = st.text_input("Endpoint URL", value=env_vals["AZURE_OPENAI_ENDPOINT"], placeholder="https://<resource-name>.openai.azure.com/")
        new_key  = st.text_input("API Key", value=env_vals["AZURE_OPENAI_API_KEY"], type="password")
        new_dep  = st.text_input("Deployment Name", value=env_vals["AZURE_OPENAI_DEPLOYMENT_NAME"], placeholder="gpt-4o-mini")
        new_ver  = st.text_input("API Version", value=env_vals["AZURE_OPENAI_API_VERSION"])
        
        if st.button("บันทึกการตั้งค่า API", icon=":material/save:", type="primary", use_container_width=True):
            write_env_file({
                "AZURE_OPENAI_ENDPOINT": new_ep,
                "AZURE_OPENAI_API_KEY": new_key,
                "AZURE_OPENAI_DEPLOYMENT_NAME": new_dep,
                "AZURE_OPENAI_API_VERSION": new_ver
            })
            st.success("บันทึกข้อมูลเรียบร้อย")
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-amber"></div>
        <div class="section-header">
          <div class="sh-icon sh-grey"><span class="material-symbols-rounded">settings</span></div>
          <span class="section-title">ตั้งค่าไมโครโฟน</span>
        </div>""", unsafe_allow_html=True)

        st.selectbox(
            "Sample Rate",
            options=[8000, 16000, 22050, 44100, 48000],
            index=[8000,16000,22050,44100,48000].index(int(st.session_state.cfg_rate)),
            key="cfg_rate",
        )
        st.selectbox(
            "ช่องสัญญาณ",
            options=[1, 2],
            index=int(st.session_state.cfg_channels) - 1,
            format_func=lambda x: f"{'Mono' if x == 1 else 'Stereo'} ({x}ch)",
            key="cfg_channels",
        )

        if PYAUDIO_AVAILABLE:
            if st.session_state.device_options_cache is None:
                try:
                    import pyaudio
                    pa = pyaudio.PyAudio()
                    devs = {None: "Default"}
                    for i in range(pa.get_device_count()):
                        info = pa.get_device_info_by_index(i)
                        if info.get("maxInputChannels", 0) > 0:
                            devs[i] = f"{i}: {info['name']}"
                    pa.terminate()
                    st.session_state.device_options_cache = devs
                except Exception:
                    st.session_state.device_options_cache = {None: "Default"}

            opts = st.session_state.device_options_cache
            dev_keys = list(opts.keys())
            cur_idx  = dev_keys.index(st.session_state.cfg_device_index) if st.session_state.cfg_device_index in dev_keys else 0
            chosen   = st.selectbox(
                "อุปกรณ์ไมโครโฟน",
                options=dev_keys,
                index=cur_idx,
                format_func=lambda x: opts[x],
                key="_device_select",
            )
            st.session_state.cfg_device_index = chosen
        else:
            st.warning("ไม่พบ PyAudio — ติดตั้ง: `pip install pyaudio`")


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
          <span style="font-weight:500;">ระบบบันทึกเสียง (PyAudio)</span>
          {{
            '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>พร้อมใช้งาน</span>' if has_audio
            else '<span class="status-pill pill-err"><span class="status-dot dot-red"></span>ไม่พบ PyAudio</span>'
          }}
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
          <span style="font-weight:500;">Azure OpenAI API</span>
          {
            '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>ตั้งค่าแล้ว</span>' if api_ok
            else '<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>ยังไม่ได้ตั้งค่า</span>'
          }
        </div>
        """, unsafe_allow_html=True)
        
        if not api_ok and api_msg:
            st.caption(f"ℹ️ {api_msg}")

        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("ตรวจสอบระบบใหม่ (Refresh)", icon=":material/refresh:", use_container_width=True):
            if st.session_state.recognizer and not st.session_state.model_loaded:
                try:
                    if st.session_state.recognizer.load_model():
                        st.session_state.model_loaded = True
                except Exception as e:
                    st.session_state.model_error = str(e)
            st.rerun()
