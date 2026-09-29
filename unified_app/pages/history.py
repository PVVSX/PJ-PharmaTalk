# -*- coding: utf-8 -*-
"""Page — History (ประวัติข้อมูล Cloud)"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core_api.firebase_config import get_firestore_client
import firebase_admin
from firebase_admin import storage

st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">cloud_done</span>
  <div>
    <h2 class="page-title">ประวัติข้อมูล (Cloud)</h2>
    <p class="page-subtitle">ดูประวัติและผลการวิเคราะห์เวชระเบียนจากระบบส่วนกลาง</p>
  </div>
</div>
""", unsafe_allow_html=True)

db = get_firestore_client()
if not db:
    st.error("ไม่สามารถเชื่อมต่อฐานข้อมูล Cloud (Firestore) ได้")
    st.stop()

# Fetch latest tasks
try:
    docs = db.collection("patients_emr").order_by("created_at", direction="DESCENDING").limit(20).stream()
    docs = list(docs)
except Exception as e:
    st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")
    docs = []

if not docs:
    st.markdown('''
    <div class="record-empty-state" style="min-height: 220px;">
      <span class="material-symbols-rounded">cloud_off</span>
      <div>ยังไม่มีประวัติใน Cloud</div>
    </div>
    ''', unsafe_allow_html=True)
else:
    st.markdown(f"พบข้อมูลล่าสุด **{len(docs)}** เคส", unsafe_allow_html=True)
    st.markdown("<div style='margin: 18px 0;'></div>", unsafe_allow_html=True)

    for doc in docs:
        data = doc.to_dict()
        task_id = doc.id
        created_at = data.get("created_at")
        ts_str = created_at.strftime("%d/%m/%Y %H:%M:%S") if created_at else "ไม่ระบุเวลา"
        
        stt_text = data.get("stt_text", "")
        emr_data = data.get("emr_data", {})
        audio_filename = data.get("audio_filename", "")
        task_status = data.get("status", "")
        
        has_stt = bool(stt_text)
        has_emr = bool(emr_data)
        
        with st.container(border=True):
            meta_cols = st.columns([2.5, 1.2])
            with meta_cols[0]:
                st.markdown(f"<div class='history-file-name'>รหัสอ้างอิง: {task_id[:8]}...</div>", unsafe_allow_html=True)
                st.caption(f"เวลา: {ts_str}  •  บันทึกบน Cloud Firestore")
            with meta_cols[1]:
                if has_emr or task_status == "COMPLETED":
                    st.markdown('<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>วิเคราะห์ EMR สมบูรณ์</span>', unsafe_allow_html=True)
                elif task_status == "EMR_ERROR":
                    st.markdown('<span class="status-pill pill-error" style="background:#fee2e2;color:#991b1b;"><span class="status-dot dot-red" style="background:#ef4444;"></span>ประมวลผล EMR ไม่สำเร็จ</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>กำลังประมวลผล EMR...</span>', unsafe_allow_html=True)
            
            st.markdown("<div style='margin: 10px 0 16px;'></div>", unsafe_allow_html=True)
            
            # Show Audio Player if we have the filename
            if audio_filename and firebase_admin._apps:
                try:
                    bucket = storage.bucket()
                    blob = bucket.blob(f"recordings/{audio_filename}")
                    if blob.exists():
                        url = blob.generate_signed_url(expiration=timedelta(hours=1))
                        st.audio(url)
                    else:
                        st.caption("⚠️ ไม่มีไฟล์เสียงบน Cloud Storage (หรือระบบกำลังอัปโหลด)")
                except Exception as e:
                    st.caption(f"⚠️ ไม่สามารถโหลดไฟล์เสียงได้: {e}")
                    
            if has_stt:
                stt_display_text = stt_text
                with st.expander("ข้อความถอดเสียงดิบ (ไม่ได้แยกผู้พูด)", expanded=False):
                    st.markdown(f"<div style='background-color: #F8FAFC; padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0; color: #1E293B; font-size: 0.95rem; line-height: 1.6;'>{stt_display_text}</div>", unsafe_allow_html=True)

            if has_emr:
                dialogue = emr_data.get("บทสนทนาที่จัดเรียงแล้ว")
                if dialogue and dialogue != "-":
                    st.markdown("##### บทสนทนา (AI จัดเรียงใหม่)")
                    formatted_html = "<div style='background-color: #F8FAFC; padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0; color: #1E293B; font-size: 0.95rem; line-height: 1.6; margin-bottom: 20px;'>"
                    for line in dialogue.split('\n'):
                        line = line.strip()
                        if not line: continue
                        if "เภสัชกร:" in line or "ผู้ป่วย:" in line or "คนไข้:" in line:
                            formatted_html += f"<div style='margin-bottom: 4px;'><strong>{line}</strong></div>"
                        else:
                            formatted_html += f"<div style='margin-bottom: 4px; padding-left: 15px;'>{line}</div>"
                    formatted_html += "</div>"
                    st.markdown(formatted_html, unsafe_allow_html=True)

                with st.expander("📋 ผลวิเคราะห์เวชระเบียน (EMR)", expanded=True):
                    # BEAUTIFUL EMR RENDERING instead of raw JSON
                    if isinstance(emr_data, dict):
                        for key, value in emr_data.items():
                            if key == "บทสนทนาที่จัดเรียงแล้ว":
                                continue # Skip showing this twice
                            st.markdown(f"**{key}**")
                            if isinstance(value, list):
                                for item in value:
                                    st.markdown(f"- {item}")
                            else:
                                st.info(str(value))
                    else:
                        st.write(emr_data)

            st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
