# -*- coding: utf-8 -*-
"""Page 3 — EMR Analysis (วิเคราะห์ EMR)"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit_autorefresh import st_autorefresh

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.emr_groq import EMR_FIELDS
from unified_app.modules.task_api import get_task
from core_api.database import SessionLocal, TaskTracker

# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">medical_services</span>
  <div>
    <h2 class="page-title">วิเคราะห์เวชระเบียน</h2>
    <p class="page-subtitle">EMR Viewer — ข้อมูลประวัติคนไข้ที่สรุปโดย AI</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Auto Fetch Latest Task ──
task_id = st.session_state.get("last_audio_task_id")
if task_id and not st.session_state.get(f"emr_loaded_{task_id}"):
    st_autorefresh(interval=2000, key="emr_task_refresh")
    try:
        task = get_task(task_id)
        task_status = task.get("status", "UNKNOWN")
        if task_status not in ("COMPLETED", "ERROR"):
            st.info(f"⏳ ระบบหลังบ้านกำลังประมวลผลเวชระเบียน: {task_status}...")
        elif task_status == "ERROR":
            st.error(f"งานประมวลผลไม่สำเร็จ: {task.get('error_message', 'ไม่ทราบสาเหตุ')}")
        elif task.get("emr_json"):
            st.session_state.emr_result = json.loads(task["emr_json"])
            st.session_state.emr_conv_input = task.get("stt_text", "")
            st.session_state[f"emr_loaded_{task_id}"] = True
            st.success("✅ โหลดข้อมูลจากระบบหลังบ้านสำเร็จ!")
    except Exception as exc:
        st.warning(f"เชื่อมต่อระบบหลังบ้านไม่ได้: {exc}")

st.markdown("<br>", unsafe_allow_html=True)
t3L, t3R = st.columns([1, 1], gap="large")

# ── LEFT: Transcript Viewer ──
with t3L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-blue"></div>
        <div class="section-header">
            <div class="sh-icon sh-blue"><span class="material-symbols-rounded">chat</span></div>
            <span class="section-title">บทสนทนา (Transcript)</span>
        </div>""", unsafe_allow_html=True)
        
        # Load tasks from local DB to populate the dropdown
        db = SessionLocal()
        tasks = db.query(TaskTracker).limit(20).all()
        # reverse manually to show newest first if assuming sequential ID or rowid
        tasks = reversed(tasks)
        db.close()
        
        task_options = {"--- งานล่าสุดที่กำลังทำ ---": None}
        for t in tasks:
            if t.emr_json:
                label = f"เคสที่แล้ว - {t.id[:8]}"
                task_options[label] = t

        selected_label = st.selectbox("เลือกดูประวัติ", options=list(task_options.keys()))
        
        if selected_label != "--- งานล่าสุดที่กำลังทำ ---":
            t = task_options[selected_label]
            if t:
                st.session_state.emr_conv_input = t.stt_text
                st.session_state.emr_result = json.loads(t.emr_json) if t.emr_json else {}
                st.session_state.last_audio_task_id = t.id # Update focus
                
        st.markdown('''
        <div class="record-callout info">
            <span class="material-symbols-rounded">info</span>
            <div>
            <strong>โหมดอ่านอย่างเดียว (Read-only)</strong>
            <div>ระบบหลังบ้านได้ทำการวิเคราะห์ข้อมูลเรียบร้อยแล้ว ไม่ต้องกดปุ่มวิเคราะห์ซ้ำ</div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

        st.text_area(
            "บทสนทนาที่ถูกจัดเรียงแล้ว",
            value=st.session_state.get("emr_conv_input", ""),
            height=300,
            disabled=True
        )


# ── RIGHT: EMR Form Output ──
with t3R:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
            <div class="sh-icon sh-teal"><span class="material-symbols-rounded">assignment</span></div>
            <span class="section-title">ฟอร์มเวชระเบียน</span>
        </div>""", unsafe_allow_html=True)

        emr_data = st.session_state.get("emr_result", {})

        if not emr_data:
            st.markdown('''
            <div class="record-empty-state" style="min-height: 220px; margin-bottom: 14px;">
                <span class="material-symbols-rounded">hourglass_empty</span>
                <div>กำลังรอข้อมูลประวัติการรักษา...</div>
            </div>
            ''', unsafe_allow_html=True)
        else:
            for field in EMR_FIELDS:
                label = field
                val = emr_data.get(field, "-")
                if isinstance(val, list):
                    val = "\n".join(f"- {x}" for x in val)
                elif isinstance(val, dict):
                    val = json.dumps(val, ensure_ascii=False, indent=2)
                else:
                    val = str(val)

                st.markdown(f"""
                <div class="emr-field">
                    <div class="emr-field-label">{label}</div>
                    <div class="emr-field-value">{val if val != "-" else "<span style='color:var(--grey-400);font-style:italic;'>ไม่มีข้อมูล</span>"}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        if st.button("ยืนยันและบันทึกลงระบบร้านยา", icon=":material/save:", use_container_width=True, type="primary", disabled=not emr_data):
            st.success("บันทึกเวชระเบียนเสร็จสิ้น!")
