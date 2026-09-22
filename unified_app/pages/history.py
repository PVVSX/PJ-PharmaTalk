# -*- coding: utf-8 -*-
"""Page — History (ประวัติข้อมูล)"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_DIR = ROOT / "record"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    st.markdown('''
    <div class="record-empty-state" style="min-height: 220px;">
      <span class="material-symbols-rounded">history</span>
      <div>ยังไม่มีข้อมูลประวัติ ให้กลับไปที่หน้าอัดเสียงเพื่อเริ่มบันทึกครั้งแรก</div>
    </div>
    ''', unsafe_allow_html=True)
else:
    summary_cols = st.columns(3)
    with summary_cols[0]:
        st.markdown(f'<div class="history-stat-card"><div class="history-stat-label">ไฟล์เสียง</div><div class="history-stat-value">{len(wav_files)}</div></div>', unsafe_allow_html=True)
    with summary_cols[1]:
        st.markdown(f'<div class="history-stat-card"><div class="history-stat-label">ถอดเสียงแล้ว</div><div class="history-stat-value">{sum((STT_DIR / (p.stem + "_stt.txt")).exists() for p in wav_files)}</div></div>', unsafe_allow_html=True)
    with summary_cols[2]:
        st.markdown(f'<div class="history-stat-card"><div class="history-stat-label">EMR แล้ว</div><div class="history-stat-value">{sum((EMR_DIR / (p.stem + "_emr.json")).exists() for p in wav_files)}</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='margin: 18px 0;'></div>", unsafe_allow_html=True)

    for wf_path in wav_files:
        mtime = wf_path.stat().st_mtime
        ts_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M:%S")

        stt_path = STT_DIR / (wf_path.stem + "_stt.txt")
        emr_path = EMR_DIR / (wf_path.stem + "_emr.json")
        has_stt = stt_path.exists()
        has_emr = emr_path.exists()

        status_html = ""
        status_html += (
            '<span class="status-pill pill-ok" style="margin-right: 8px;">'
            '<span class="status-dot dot-green"></span>ถอดเสียงแล้ว</span>'
            if has_stt else
            '<span class="status-pill pill-warn" style="margin-right: 8px;">'
            '<span class="status-dot dot-amber"></span>รอถอดเสียง</span>'
        )
        status_html += (
            '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>วิเคราะห์ EMR แล้ว</span>'
            if has_emr else
            '<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>ยังไม่ได้วิเคราะห์ EMR</span>'
        )

        with st.container(border=True):
            meta_cols = st.columns([2.5, 1.2])
            with meta_cols[0]:
                st.markdown(f"<div class='history-file-name'>{wf_path.name}</div>", unsafe_allow_html=True)
                st.caption(f"เวลา: {ts_str}  •  ขนาด: {wf_path.stat().st_size / 1024:.1f} KB")
            with meta_cols[1]:
                st.markdown(status_html, unsafe_allow_html=True)

            st.markdown("<div style='margin: 10px 0 16px;'></div>", unsafe_allow_html=True)
            st.audio(str(wf_path))

            if has_stt:
                with st.expander("ข้อความถอดเสียง", expanded=False):
                    st.text_area(
                        "STT Result",
                        value=stt_path.read_text(encoding="utf-8"),
                        height=120,
                        disabled=True,
                        label_visibility="collapsed",
                        key=f"stt_{wf_path.stem}",
                    )

            if has_emr:
                with st.expander("ผลวิเคราะห์ EMR", expanded=True):
                    try:
                        emr_data = json.loads(emr_path.read_text(encoding="utf-8"))
                        st.json(emr_data, expanded=False)
                    except Exception:
                        st.code(emr_path.read_text(encoding="utf-8"), language="json")

            c1, c2 = st.columns([1, 3])
            with c1:
                if st.button("ลบข้อมูลนี้", icon=":material/delete:", key=f"del_{wf_path.stem}", use_container_width=True):
                    wf_path.unlink(missing_ok=True)
                    if has_stt:
                        stt_path.unlink(missing_ok=True)
                    if has_emr:
                        emr_path.unlink(missing_ok=True)
                    st.rerun()

            st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
