# -*- coding: utf-8 -*-
"""Page 2 — Speech-to-Text (ถอดเสียง)"""
from __future__ import annotations

import io
import sys
import wave
from datetime import datetime
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


from unified_app.modules.stt_typhoon import ASR_AVAILABLE, transcribe_audio_bytes



# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">description</span>
  <div>
    <h2 class="page-title">ถอดเสียง</h2>
    <p class="page-subtitle">Speech-to-Text — Typhoon ASR</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Model status banner ──
if st.session_state.model_loaded:
    st.markdown('<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>โมเดล Typhoon ASR พร้อมใช้งาน</span>', unsafe_allow_html=True)
elif st.session_state.model_error:
    st.markdown(f'<span class="status-pill pill-err"><span class="status-dot dot-red"></span>โหลดโมเดลล้มเหลว: {st.session_state.model_error}</span>', unsafe_allow_html=True)
    st.warning("ติดตั้ง dependency: `pip install nemo_toolkit[asr]`")
elif not ASR_AVAILABLE:
    st.markdown('<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>ไม่พบ NeMo / typhoon-asr — UI แสดงได้ แต่ถอดเสียงไม่ได้</span>', unsafe_allow_html=True)
else:
    st.markdown('<span class="status-pill pill-info"><span class="status-dot dot-blue"></span>กำลังโหลดโมเดล Typhoon ASR…</span>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
t2L, t2R = st.columns([1, 1], gap="large")

# ── LEFT: Input ──
with t2L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-blue"></div>
        <div class="section-header">
          <div class="sh-icon sh-blue"><span class="material-symbols-rounded">upload_file</span></div>
          <span class="section-title">อัปโหลดหรือใช้เสียงที่อัดไว้</span>
        </div>""", unsafe_allow_html=True)

        stt_uploaded = st.file_uploader(
            "ลากไฟล์มาวาง หรือคลิกเพื่อเลือก (WAV · MP3 · M4A · FLAC)",
            type=["wav", "mp3", "m4a", "flac"],
            key="stt_upload",
        )

        if stt_uploaded:
            st.audio(stt_uploaded)
            if st.button("ถอดเสียงไฟล์นี้", icon=":material/transcribe:", use_container_width=True,
                         type="primary", disabled=not st.session_state.model_loaded,
                         key="btn_transcribe_upload"):
                with st.spinner("กำลังถอดเสียง… อาจใช้เวลาสักครู่"):
                    result = transcribe_audio_bytes(
                        st.session_state.recognizer, stt_uploaded.getvalue()
                    )
                    st.session_state.stt_result = result



# ── RIGHT: Result ──
with t2R:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
          <div class="sh-icon sh-teal"><span class="material-symbols-rounded">article</span></div>
          <span class="section-title">ผลการถอดเสียง</span>
        </div>""", unsafe_allow_html=True)

        if st.session_state.stt_result:
            st.text_area(
                "ข้อความที่ถอดได้",
                value=st.session_state.stt_result,
                height=260,
                key="stt_output",
            )
            col_send, col_copy = st.columns(2)
            with col_send:
                if st.button("ส่งไป EMR", icon=":material/arrow_forward:", use_container_width=True,
                             type="primary", key="btn_send_emr"):
                    st.session_state.emr_conv_input = st.session_state.stt_result
                    st.success("ส่งข้อความไปยังหน้า วิเคราะห์ EMR แล้ว")
            with col_copy:
                st.download_button(
                    "บันทึก .txt", icon=":material/download:", data=st.session_state.stt_result,
                    file_name=f"stt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain", key="btn_dl_stt",
                    use_container_width=True,
                )


        else:
            st.markdown("""
            <div style="text-align:center; padding:3rem 1rem; color:var(--grey-400);">
              <div style="font-size:3rem;margin-bottom:.5rem;"><span class="material-symbols-rounded" style="font-size:inherit;">headphones</span></div>
              <div style="font-size:1rem; font-weight:500; color:var(--grey-400);">
                อัปโหลดไฟล์เสียงหรือใช้เสียงที่อัดไว้<br>
                แล้วกดปุ่ม <strong>ถอดเสียง</strong>
              </div>
            </div>""", unsafe_allow_html=True)


