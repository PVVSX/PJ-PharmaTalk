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
from unified_app.modules.emr_gemini import EMR_FIELDS, check_credentials, extract_emr
from unified_app.modules.task_api import get_task


task_id = st.session_state.get("last_audio_task_id")
if task_id and not st.session_state.get("emr_result"):
    st_autorefresh(interval=2000, key="emr_task_refresh")
    try:
        task = get_task(task_id)
        task_status = task.get("status", "UNKNOWN")
        if task_status not in ("COMPLETED", "ERROR"):
            st.info(f"งานจากหน้าอัดเสียงกำลังประมวลผล: {task_status}")
        elif task_status == "ERROR":
            st.error(f"งานประมวลผลไม่สำเร็จ: {task.get('error_message', 'ไม่ทราบสาเหตุ')}")
        elif task.get("emr_json"):
            st.session_state.emr_result = json.loads(task["emr_json"])
            st.success("ได้รับผลวิเคราะห์ EMR จาก Core API แล้ว")
    except Exception as exc:
        st.warning(f"ยังเชื่อมต่อ Core API ไม่ได้: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _do_emr_extraction(text: str) -> None:
    api_ok, _ = check_credentials()
    if not api_ok:
        st.session_state.emr_error = "กรุณาตั้งค่า Gemini API ในหน้า 'ตั้งค่า' ก่อนใช้งาน"
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
status_col1, status_col2 = st.columns([2, 1])
with status_col1:
    if not api_ok:
        st.markdown('<div class="record-status-banner warn"><span class="material-symbols-rounded">warning</span><span>Gemini API ยังไม่ได้ตั้งค่า</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="record-status-banner ok"><span class="material-symbols-rounded">check_circle</span><span>Gemini API พร้อมใช้งาน</span></div>', unsafe_allow_html=True)
with status_col2:
    st.markdown(f'<div class="record-mini-stat"><span class="label">สถานะ</span><strong>{"พร้อม" if api_ok else "รอตั้งค่า"}</strong></div>', unsafe_allow_html=True)

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
        
        sample_prompts = {
            "ตัวอย่าง 1: คนไข้รายใหม่": "คนไข้รายนี้แพ้ยาพาราเซตามอลและยาลดไข้ชนิด NSAIDs มีประวัติโรคความดันโลหิตสูงและเบาหวาน เคยได้รับยา amlodipine 5 มก. วันละ 1 เม็ด และ metformin 500 มก. วันละ 2 เม็ด หลังจากรับประทานยาแล้วมีอาการเวียนหัวและผื่นแดงที่ผิวหนัง ผู้ป่วยบอกว่ามีอาการไอเรื้อรัง 2 สัปดาห์ และแพทย์แนะนำให้ใช้ยา salbutamol 2 puff เมื่อมีอาการหอบ",
            "ตัวอย่าง 2: การปรับยา": "ผู้ป่วยมียา celecoxib 200 มก. หลังอาหาร วันละ 1 เม็ด และ aspirin 81 มก. วันละ 1 เม็ด มีประวัติแพ้ penicillin อาการคันและผื่นแดง ควรหลีกเลี่ยงยา NSAIDs เพราะมีประวัติปวดศีรษะและความดันโลหิตสูง แพทย์แนะนำให้ทานยา atorvastatin 20 มก. ก่อนนอน"
        }

        st.markdown('''
        <div class="workflow-guide">
          <div class="workflow-step"><span class="material-symbols-rounded">upload_file</span><div><strong>ขั้นที่ 1</strong><small>เลือกหรือคัดลอกข้อความ</small></div></div>
          <div class="workflow-step"><span class="material-symbols-rounded">bolt</span><div><strong>ขั้นที่ 2</strong><small>กดวิเคราะห์ EMR</small></div></div>
          <div class="workflow-step"><span class="material-symbols-rounded">task_alt</span><div><strong>ขั้นที่ 3</strong><small>ตรวจสอบฟอร์มผลลัพธ์</small></div></div>
        </div>
        ''', unsafe_allow_html=True)

        st.markdown('''
        <div class="record-callout info">
          <span class="material-symbols-rounded">auto_awesome</span>
          <div>
            <strong>เริ่มต้นได้เร็ว</strong>
            <div>เลือกตัวอย่างข้อความด้านล่างหรือวางบทสนทนาจากประวัติที่มีอยู่</div>
          </div>
        </div>
        ''', unsafe_allow_html=True)

        prompt_col1, prompt_col2 = st.columns(2)
        with prompt_col1:
            if st.button("ตัวอย่างข้อความ 1", use_container_width=True):
                st.session_state.emr_conv_input = sample_prompts["ตัวอย่าง 1: คนไข้รายใหม่"]
                st.rerun()
        with prompt_col2:
            if st.button("ตัวอย่างข้อความ 2", use_container_width=True):
                st.session_state.emr_conv_input = sample_prompts["ตัวอย่าง 2: การปรับยา"]
                st.rerun()

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

        if not emr_data:
            st.markdown('''
            <div class="record-empty-state" style="min-height: 220px; margin-bottom: 14px;">
              <span class="material-symbols-rounded">assignment</span>
              <div>ยังไม่มีผลวิเคราะห์ EMR</div>
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
