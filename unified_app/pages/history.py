# -*- coding: utf-8 -*-
"""Page — History (ประวัติข้อมูล)"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_DIR = ROOT / "record"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">history</span>
  <div>
    <h2 class="page-title">ประวัติข้อมูล</h2>
    <p class="page-subtitle">ดูประวัติไฟล์เสียง ผลถอดเสียง และข้อมูล EMR</p>
  </div>
</div>
""", unsafe_allow_html=True)


AUDIO_DIR = RECORD_DIR / "audio"
STT_DIR = RECORD_DIR / "stt"
EMR_DIR = RECORD_DIR / "emr"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
STT_DIR.mkdir(parents=True, exist_ok=True)
EMR_DIR.mkdir(parents=True, exist_ok=True)

wav_files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)

if not wav_files:
    st.info("ยังไม่มีข้อมูลประวัติ")
else:
    for wf_path in wav_files:
        mtime = wf_path.stat().st_mtime
        ts_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M:%S")
        
        stt_path = STT_DIR / (wf_path.stem + "_stt.txt")
        emr_path = EMR_DIR / (wf_path.stem + "_emr.json")
        
        has_stt = stt_path.exists()
        has_emr = emr_path.exists()
        
        # Build status pills
        status_html = ""
        if has_stt:
            status_html += '<span class="status-pill pill-ok" style="margin-right: 8px;"><span class="status-dot dot-green"></span>ถอดเสียงแล้ว</span>'
        else:
            status_html += '<span class="status-pill pill-warn" style="margin-right: 8px;"><span class="status-dot dot-amber"></span>รอถอดเสียง</span>'
            
        if has_emr:
            status_html += '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>วิเคราะห์ EMR แล้ว</span>'
        else:
            status_html += '<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>ยังไม่ได้วิเคราะห์ EMR</span>'
            
        with st.container(border=True):
            st.markdown(f"**ไฟล์:** `{wf_path.name}` &nbsp;&nbsp;|&nbsp;&nbsp; **เวลา:** {ts_str}")
            st.markdown(status_html, unsafe_allow_html=True)
            st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)
            
            st.audio(str(wf_path))
            
            if has_stt:
                st.markdown("**ข้อความจากการถอดเสียง:**")
                st.text_area("STT Result", value=stt_path.read_text(encoding="utf-8"), height=100, disabled=True, label_visibility="collapsed", key=f"stt_{wf_path.stem}")
            
            if has_emr:
                st.markdown("**ผลวิเคราะห์ EMR:**")
                emr_content = emr_path.read_text(encoding="utf-8")
                st.json(emr_content, expanded=False)
                
            col1, col2 = st.columns([1, 5])
            with col1:
                if st.button("ลบข้อมูลนี้", icon=":material/delete:", key=f"del_{wf_path.stem}"):
                    wf_path.unlink(missing_ok=True)
                    if has_stt: stt_path.unlink(missing_ok=True)
                    if has_emr: emr_path.unlink(missing_ok=True)
                    st.rerun()
