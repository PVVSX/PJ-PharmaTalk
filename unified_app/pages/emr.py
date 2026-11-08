# -*- coding: utf-8 -*-
"""Page — EMR review (วิเคราะห์ EMR): read the AI summary, correct it, and confirm it."""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import streamlit as st
from streamlit_autorefresh import st_autorefresh

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.emr_groq import DIALOGUE_FIELD, EMR_FIELDS, SAFETY_FIELD
from unified_app.modules.task_api import confirm_task, get_task, list_tasks, retry_task

st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">medical_services</span>
  <div>
    <h2 class="page-title">วิเคราะห์เวชระเบียน</h2>
    <p class="page-subtitle">EMR Review — ตรวจทาน แก้ไข และยืนยันข้อมูลที่ AI สรุป</p>
  </div>
</div>
""", unsafe_allow_html=True)

try:
    tasks = list_tasks(30)
except Exception as exc:
    st.error(f"เชื่อมต่อ Core API ไม่ได้: {exc}")
    st.stop()

if not tasks:
    st.markdown('<div class="record-empty-state" style="min-height:220px;"><span class="material-symbols-rounded">inbox</span><div>ยังไม่มีเคส</div></div>', unsafe_allow_html=True)
    st.stop()


def _label(t: dict) -> str:
    when = (t.get("created_at") or "")[:16].replace("T", " ")
    flag = {"COMPLETED": "✓ ยืนยันแล้ว" if t.get("confirmed_at") else "รอตรวจทาน", "ERROR": "ผิดพลาด"}.get(t["status"], "กำลังประมวลผล")
    who = {"pharmacist": "เภสัชกร", "backoffice": "หลังบ้าน"}.get(t.get("source") or "", t.get("source") or "-")
    return f"{when} UTC · {t['task_id'][:8]} · {who} · {flag}"


ids = [t["task_id"] for t in tasks]
default = st.session_state.get("last_audio_task_id")
idx = ids.index(default) if default in ids else 0
sel = st.selectbox("เลือกเคส", options=ids, index=idx, format_func=lambda i: _label(next(t for t in tasks if t["task_id"] == i)))
st.session_state.last_audio_task_id = sel
task = get_task(sel)

if task["status"] not in ("COMPLETED", "ERROR"):
    st_autorefresh(interval=2000, key="emr_task_refresh")
    st.info(f"กำลังประมวลผล: {task['status']} …", icon=":material/hourglass_top:")
    st.stop()
if task["status"] == "ERROR":
    st.error(f"งานนี้ประมวลผลไม่สำเร็จ: {task.get('error_message')}")
    if task.get("can_retry") and st.button("ลองประมวลผลใหม่", icon=":material/replay:", type="primary"):
        retry_task(sel); st.rerun()
    st.stop()

emr = json.loads(task.get("emr_json") or "{}")
confirmed = json.loads(task.get("confirmed_emr_json") or "null")
meta = json.loads(task.get("stt_meta") or "{}")
current = confirmed or emr

L, R = st.columns([1, 1], gap="large")
with L:
    with st.container(border=True):
        st.markdown("""<div class="card-accent-bar accent-blue"></div><div class="section-header">
            <div class="sh-icon sh-blue"><span class="material-symbols-rounded">chat</span></div>
            <span class="section-title">บทสนทนา (แยกผู้พูดโดย AI จากข้อความถอดเสียงจริง)</span></div>""", unsafe_allow_html=True)
        dialogue = emr.get(DIALOGUE_FIELD, "-")
        rows = []
        for line in str(dialogue).splitlines():
            who, _, txt = line.partition(":")
            cls = "#E8F0FE" if "เภสัช" in who else "#F1F5F9"
            rows.append(f"<div style='background:{cls};padding:6px 10px;border-radius:8px;margin-bottom:4px;'><b>{html.escape(who)}</b>: {html.escape(txt.strip())}</div>")
        st.markdown("<div style='max-height:420px;overflow:auto'>" + "".join(rows) + "</div>", unsafe_allow_html=True)
        e_meta = emr.get("_meta") or {}
        st.caption(f"ถอดเสียง: {meta.get('engine', '-')} · {meta.get('duration_s', '-')} วินาที · ใช้เวลา {meta.get('elapsed_s', '-')} วินาที · "
                   f"สรุปโดย {e_meta.get('model', '-')}" + (f" · ⚠ {'; '.join(e_meta.get('warnings', []))}" if e_meta.get("warnings") else ""))
        with st.expander("ข้อความถอดเสียงดิบ (ก่อนแก้ด้วยพจนานุกรมยา)"):
            st.text(task.get("raw_stt_text") or "-")
        changes = meta.get("changes") or []
        with st.expander(f"คำที่พจนานุกรมยาแก้ไข ({len(changes)})"):
            for c in changes:
                st.markdown(f"- `{html.escape(str(c.get('original')))}` → `{html.escape(str(c.get('corrected')))}` ({c.get('tier')})")
        if task.get("consent_id"):
            st.caption(f"Consent ID: {task['consent_id']}")

with R:
    with st.container(border=True):
        st.markdown("""<div class="card-accent-bar accent-teal"></div><div class="section-header">
            <div class="sh-icon sh-teal"><span class="material-symbols-rounded">assignment</span></div>
            <span class="section-title">ฟอร์มเวชระเบียน (แก้ไขได้ก่อนยืนยัน)</span></div>""", unsafe_allow_html=True)
        if confirmed:
            st.success(f"ยืนยันแล้วเมื่อ {str(task.get('confirmed_at'))[:19].replace('T', ' ')} UTC — แก้ไขแล้วกดยืนยันซ้ำได้")
        safety = str(current.get(SAFETY_FIELD, "-")).strip()
        if safety not in ("", "-"):
            st.warning(f"**ข้อควรระวังด้านความปลอดภัยของยา (AI แจ้งเตือน ต้องให้เภสัชกรทบทวน):** {safety}")
        edited = {}
        with st.form(f"emr_form_{sel}"):
            for f in EMR_FIELDS:
                if f == DIALOGUE_FIELD:
                    continue
                edited[f] = st.text_area(f, value=str(current.get(f, "-")), height=90 if f != "บันทึกทางการแพทย์" else 120, key=f"{sel}_{f}")
            ok = st.form_submit_button("ยืนยันและบันทึกเวชระเบียน", icon=":material/save:", type="primary", use_container_width=True)
        if ok:
            edited[DIALOGUE_FIELD] = emr.get(DIALOGUE_FIELD, "-")
            try:
                confirm_task(sel, edited)
                st.success("บันทึกเวชระเบียนที่ตรวจทานแล้วเรียบร้อย (เก็บทั้งฉบับ AI และฉบับที่ยืนยัน)")
                st.rerun()
            except Exception as exc:
                st.error(f"บันทึกไม่สำเร็จ: {exc}")
