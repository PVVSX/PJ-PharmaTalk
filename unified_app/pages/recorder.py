# -*- coding: utf-8 -*-
"""Page 1 — Audio Recorder (อัดเสียง)"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# ── Shared references from app.py context ──
ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_DIR = ROOT / "record"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.stt_typhoon import transcribe_audio_bytes
from unified_app.modules.emr_gemini import extract_emr, EMR_FIELDS
from unified_app.modules.state_manager import get_state, set_state

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">mic</span>
  <div>
    <h2 class="page-title">เครื่องบันทึกเสียง</h2>
    <p class="page-subtitle">Audio Recorder — ระบบบันทึกเสียงอัตโนมัติ</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Status Banner ──
col_stat1, col_stat2 = st.columns(2)
with col_stat1:
    if st.session_state.model_loaded:
        st.markdown('<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>โมเดล ASR พร้อมใช้งาน (รองรับถอดเสียงอัตโนมัติ)</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>โมเดล ASR ยังไม่พร้อม (ไม่สามารถถอดเสียงอัตโนมัติได้)</span>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

t1L, t1R = st.columns([3, 2], gap="large")

# ── LEFT: Native Audio Recorder ───────────────────────────────────
with t1L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-blue"></div>
        <div class="section-header">
          <div class="sh-icon sh-blue"><span class="material-symbols-rounded">graphic_eq</span></div>
          <span class="section-title">อัดเสียงสนทนา</span>
        </div>""", unsafe_allow_html=True)

        @st.fragment(run_every="1s")
        def render_recorder():
            current_state = get_state()
            
            if current_state == "WAITING":
                st.info("รอคนไข้กดยืนยันข้อตกลงความเป็นส่วนตัว...")
                st.markdown("<div style='min-height: 100px;'></div>", unsafe_allow_html=True)
            elif current_state == "FINISHED":
                st.success("บันทึกและถอดเสียงเสร็จสิ้น รอสักครู่ระบบจะกลับสู่สถานะพร้อมใช้งาน")
                st.markdown("<div style='min-height: 100px;'></div>", unsafe_allow_html=True)
            else:
                # READY state
                st.success("คนไข้ยินยอมแล้ว พร้อมบันทึกเสียง")
                audio_key = f"native_audio_recorder_{st.session_state.get('audio_key_counter', 0)}"
                audio_value = st.audio_input("กดปุ่มไมโครโฟนด้านล่างเพื่อเริ่มและหยุดอัดเสียง", key=audio_key)
                
                if audio_value:
                    audio_bytes = audio_value.getvalue()
                    # To avoid re-transcribing the same audio on every re-render, we check if it's new
                    # We can hash the audio bytes to check if it's a new recording
                    audio_hash = hashlib.md5(audio_bytes).hexdigest()
                    
                    if st.session_state.get("last_audio_hash") != audio_hash:
                        st.session_state.last_audio_hash = audio_hash
                        
                        AUDIO_DIR = RECORD_DIR / "audio"
                        STT_DIR = RECORD_DIR / "stt"
                        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                        STT_DIR.mkdir(parents=True, exist_ok=True)
                        
                        now = datetime.now()
                        base_name = now.strftime("%d-%m-%y_%H-%M") + "_000"
                        audio_filename = f"{base_name}.wav"
                        stt_filename = f"{base_name}_stt.txt"
                        
                        audio_path = AUDIO_DIR / audio_filename
                        stt_path = STT_DIR / stt_filename
                        
                        # Save audio
                        audio_path.write_bytes(audio_bytes)
                        st.session_state.last_saved_path = str(audio_path)
                        
                        # Transcribe
                        if st.session_state.model_loaded:
                            with st.spinner("กำลังถอดเสียงอัตโนมัติ..."):
                                try:
                                    txt = transcribe_audio_bytes(st.session_state.recognizer, audio_bytes)
                                    stt_path.write_text(txt, encoding="utf-8")
                                    st.toast(f"บันทึกและถอดเสียงสำเร็จ! (`{audio_filename}`)", icon=":material/check_circle:")
                                except Exception as e:
                                    st.toast(f"เกิดข้อผิดพลาดในการถอดเสียง: {e}", icon=":material/error:")
                        else:
                            st.toast(f"บันทึกไฟล์ `{audio_filename}` แล้ว (ไม่สามารถถอดเสียงได้)", icon=":material/warning:")
                            
                        # Tell the JS app that we finished
                        set_state("FINISHED")
                            
                        # Auto reset the audio recorder so it's ready for the next patient
                        st.session_state.audio_key_counter = st.session_state.get('audio_key_counter', 0) + 1
                        st.rerun()

        render_recorder()

# ── RIGHT: Saved Recordings ────────────────────────────────
with t1R:
    with st.container(border=True):
        AUDIO_DIR = RECORD_DIR / "audio"
        STT_DIR = RECORD_DIR / "stt"
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        STT_DIR.mkdir(parents=True, exist_ok=True)
        wav_files = sorted(AUDIO_DIR.glob("*.wav"),
                           key=lambda p: p.stat().st_mtime, reverse=True)

        st.markdown(f"""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
          <div class="sh-icon sh-teal"><span class="material-symbols-rounded">folder</span></div>
          <span class="section-title">ประวัติการบันทึก</span>
          <span class="section-sub">{len(wav_files)} ไฟล์</span>
        </div>""", unsafe_allow_html=True)

        if wav_files:
            for wf_path in wav_files:
                mtime     = wf_path.stat().st_mtime
                ts_str    = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                size_kb   = wf_path.stat().st_size / 1024
                rec_id    = hashlib.md5(wf_path.name.encode()).hexdigest()[:16]
                
                # Check STT status
                stt_file = STT_DIR / wf_path.name.replace(".wav", "_stt.txt")
                if stt_file.exists():
                    stt_status = "(ถอดเสียงแล้ว)"
                else:
                    stt_status = "(รอถอดเสียง)"

                with st.expander(f"{wf_path.name}", expanded=False):
                    st.caption(f"{ts_str}  •  {size_kb:.1f} KB  •  {stt_status}")
                    col_play, col_del = st.columns([2, 1])
                    with col_play:
                        st.audio(str(wf_path))
                    with col_del:
                        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                        if st.button("ลบ", icon=":material/delete:", key=f"del_{rec_id}", use_container_width=True):
                            wf_path.unlink(missing_ok=True)
                            if stt_file.exists():
                                stt_file.unlink(missing_ok=True)
                            st.rerun()
        else:
            st.info("ยังไม่มีไฟล์บันทึก")
