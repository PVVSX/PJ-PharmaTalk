# -*- coding: utf-8 -*-
"""Page 3 — EMR Analysis (วิเคราะห์ EMR)"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from unified_app.modules.emr_azure import EMR_FIELDS, check_credentials, extract_emr


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _do_emr_extraction(text: str) -> None:
    api_ok, _ = check_credentials()
    if not api_ok:
        st.session_state.emr_error = "กรุณาตั้งค่า Azure OpenAI ในหน้า 'ตั้งค่า' ก่อนใช้งาน"
        return
    st.session_state.emr_error = ""
    try:
        res = extract_emr(text)
        if "error" in res:
            st.session_state.emr_error = res["error"]
        else:
            st.session_state.emr_result = res
            st.session_state.emr_history.insert(0, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "input": text,
                "result": res
            })
    except Exception as e:
        st.session_state.emr_error = str(e)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">medical_services</span>
  <div>
    <h2 class="page-title">วิเคราะห์เวชระเบียน</h2>
    <p class="page-subtitle">EMR Extraction — สกัดข้อมูลจากบทสนทนา</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── API Status Banner ──
api_ok, _ = check_credentials()
col_stat1, col_stat2 = st.columns(2)
with col_stat1:
    if not api_ok:
        st.markdown('<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>Azure OpenAI ยังไม่ได้ตั้งค่า (ไม่สามารถวิเคราะห์ได้)</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>Azure OpenAI พร้อมใช้งาน</span>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
t3L, t3R = st.columns([1, 1], gap="large")

# ── LEFT: Input ──
with t3L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-blue"></div>
        <div class="section-header">
          <div class="sh-icon sh-blue"><span class="material-symbols-rounded">chat</span></div>
          <span class="section-title">บทสนทนา (Transcript)</span>
        </div>""", unsafe_allow_html=True)
        
        STT_DIR = ROOT / "record" / "stt"
        STT_DIR.mkdir(parents=True, exist_ok=True)
        stt_files = sorted(STT_DIR.glob("*_stt.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        stt_options = ["--- เลือกจากประวัติ ---"] + [f.name for f in stt_files]
        
        selected_stt = st.selectbox("เลือกประวัติการถอดเสียง", options=stt_options)
        
        if selected_stt != "--- เลือกจากประวัติ ---":
            file_path = STT_DIR / selected_stt
            if file_path.exists():
                st.session_state.emr_conv_input = file_path.read_text(encoding="utf-8")
        
        st.text_area(
            "ข้อความบทสนทนา (แก้ไขได้ก่อนวิเคราะห์)",
            value=st.session_state.emr_conv_input,
            key="emr_conv_input",
            height=200,
        )

        col_clr, col_ext = st.columns([1, 2])
        with col_clr:
            if st.button("ล้างข้อความ", icon=":material/clear_all:", use_container_width=True):
                st.session_state.emr_conv_input = ""
                st.rerun()
        with col_ext:
            if st.button("วิเคราะห์ EMR", icon=":material/psychiatry:", use_container_width=True, type="primary", key="btn_run_emr"):
                if not st.session_state.emr_conv_input.strip():
                    st.warning("กรุณาใส่ข้อความบทสนทนา")
                else:
                    with st.spinner("กำลังวิเคราะห์ข้อมูล..."):
                        _do_emr_extraction(st.session_state.emr_conv_input)
                        if selected_stt != "--- เลือกจากประวัติ ---" and not st.session_state.emr_error:
                            EMR_DIR = ROOT / "record" / "emr"
                            EMR_DIR.mkdir(parents=True, exist_ok=True)
                            emr_path = EMR_DIR / selected_stt.replace("_stt.txt", "_emr.json")
                            emr_path.write_text(json.dumps(st.session_state.emr_result, ensure_ascii=False, indent=2), encoding="utf-8")
                            st.success("วิเคราะห์และบันทึกประวัติสำเร็จ!")

        if st.session_state.emr_error:
            st.error(f"Error: {st.session_state.emr_error}")

# ── RIGHT: EMR Form Output ──
with t3R:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
          <div class="sh-icon sh-teal"><span class="material-symbols-rounded">assignment</span></div>
          <span class="section-title">ฟอร์มเวชระเบียน</span>
        </div>""", unsafe_allow_html=True)

        emr_data = st.session_state.emr_result or {}

        # Display fields dynamically based on EMR_FIELDS
        for field in EMR_FIELDS:
            label = field
            val = emr_data.get(field, "-")
            if isinstance(val, list):
                val = "\n".join(f"- {x}" for x in val)
            elif isinstance(val, dict):
                val = json.dumps(val, ensure_ascii=False, indent=2)
            else:
                val = str(val)
            
            # Using custom HTML for form field layout
            st.markdown(f"""
            <div style="margin-bottom: 12px;">
              <div style="font-size: 0.85rem; font-weight: 600; color: var(--grey-600); margin-bottom: 4px;">{label}</div>
              <div style="background: var(--grey-50); border: 1px solid var(--grey-200); border-radius: 6px; padding: 10px; font-size: 0.95rem; color: var(--grey-800); min-height: 42px; white-space: pre-wrap;">{val if val != "-" else "<span style='color:var(--grey-400);font-style:italic;'>ไม่มีข้อมูล</span>"}</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<hr style='margin: 1.5rem 0;'>", unsafe_allow_html=True)
        col_json, col_save = st.columns(2)
        with col_json:
            st.download_button(
                "บันทึก JSON", icon=":material/data_object:",
                data=json.dumps(emr_data, ensure_ascii=False, indent=2),
                file_name=f"emr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json", key="btn_dl_emr",
                use_container_width=True,
                disabled=not emr_data
            )
        with col_save:
            if st.button("บันทึกลงระบบ", icon=":material/save:", use_container_width=True, type="primary", disabled=not emr_data):
                st.success("บันทึกเวชระเบียนสำเร็จ!")
                # Mock save functionality
