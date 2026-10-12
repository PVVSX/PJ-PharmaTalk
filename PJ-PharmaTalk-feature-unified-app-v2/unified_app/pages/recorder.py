# -*- coding: utf-8 -*-
"""Page 1 — Audio Recorder (อัดเสียง)"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ── Shared references from app.py context ──
ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_DIR = ROOT / "record"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.stt_typhoon import transcribe_audio_bytes
from unified_app.modules.emr_groq import extract_emr, EMR_FIELDS
from unified_app.modules.state_manager import get_state, set_state
from unified_app.modules.task_api import get_core_health, get_task, queue_audio
from unified_app.components.auto_recorder import auto_recorder

try:
  from core_api.firebase_config import upload_file_to_storage
except Exception:
  upload_file_to_storage = None

st_autorefresh(interval=2000, key="recorder_state_refresh")

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
status_col1, status_col2, status_col3 = st.columns([2, 1, 1], gap="small")
try:
  core_health = get_core_health()
  core_asr_ready = bool(core_health.get("asr_loaded"))
except Exception:
  core_asr_ready = False
with status_col1:
  if core_asr_ready:
        st.markdown('<div class="record-status-banner ok"><span class="material-symbols-rounded">check_circle</span><span>โมเดล ASR พร้อมใช้งาน</span></div>', unsafe_allow_html=True)
with status_col2:
  if core_asr_ready:
        st.markdown('<div class="record-mini-stat"><span class="label">สถานะ</span><strong>พร้อมใช้งาน</strong></div>', unsafe_allow_html=True)
with status_col3:
    audio_total = len(sorted((RECORD_DIR / "audio").glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)) if (RECORD_DIR / "audio").exists() else 0
    st.markdown(f'<div class="record-mini-stat"><span class="label">ไฟล์เสียง</span><strong>{audio_total}</strong></div>', unsafe_allow_html=True)

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

        def render_recorder():
            is_backoffice = st.session_state.get("is_backoffice", False)
            
            if is_backoffice:
                # Back-office uses isolated local session state so it won't conflict with pharmacist app
                if "bo_state" not in st.session_state:
                    st.session_state.bo_state = "READY"
                current_state = st.session_state.bo_state
                
                def active_set_state(s):
                    st.session_state.bo_state = s
            else:
                # Pharmacist app uses shared state from consent app
                current_state = get_state()
                active_set_state = set_state
                
                if current_state == "WAITING":
                    st.markdown('''
                    <div class="record-callout warning">
                      <span class="material-symbols-rounded">privacy_tip</span>
                      <div>
                        <strong>รอการยืนยันความยินยอม</strong>
                        <div>กรุณาให้คนไข้กดยืนยันในหน้า Consent (หน้าจอด้านนอก) ก่อน ระบบจึงจะเปิดให้บันทึกเสียง</div>
                      </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    return

            task_id = st.session_state.get("audio_task_id")
            if task_id:
                try:
                    task = get_task(task_id)
                    task_status = task.get("status", "UNKNOWN")
                    if task_status not in ("COMPLETED", "ERROR"):
                        st.info(f"กำลังประมวลผลเสียง: {task_status}")
                        return
                    if task_status == "ERROR":
                        st.error(f"ประมวลผลเสียงไม่สำเร็จ: {task.get('error_message', 'ไม่ทราบสาเหตุ')}")
                        stt_text = task.get("stt_text")
                        if stt_text:
                            saved_path = Path(st.session_state.last_saved_path)
                            stt_path = RECORD_DIR / "stt" / (saved_path.stem + "_stt.txt")
                            stt_path.write_text(stt_text, encoding="utf-8")
                            st.session_state.emr_conv_input = stt_text
                            st.warning("ระบบสามารถถอดเสียงได้สำเร็จ แต่มีข้อผิดพลาดบางอย่างในขั้นตอนถัดไป คุณสามารถตรวจสอบข้อความได้")
                        st.session_state.audio_task_id = None
                        return

                    stt_text = task.get("stt_text") or ""
                    if st.session_state.get("audio_task_completed") != task_id:
                        saved_path = Path(st.session_state.last_saved_path)
                        stt_path = RECORD_DIR / "stt" / (saved_path.stem + "_stt.txt")
                        stt_path.write_text(stt_text, encoding="utf-8")
                        st.session_state.emr_conv_input = stt_text
                        st.session_state.audio_task_completed = task_id
                        st.session_state.last_audio_task_id = task_id
                        st.session_state.audio_task_id = None
                        active_set_state("FINISHED")
                        st.success("🎉 ประมวลผลเวชระเบียนและแบ็คอัปเสร็จสมบูรณ์ สามารถดูสรุปได้ที่หน้า 'วิเคราะห์เวชระเบียน'")
                        return
                except Exception as exc:
                    st.warning(f"ยังเชื่อมต่อ Core API ไม่ได้: {exc}")
                    return


            if current_state == "FINISHED":
                st.markdown('''
                <div class="record-callout success">
                  <span class="material-symbols-rounded">check_circle</span>
                  <div>
                    <strong>ประมวลผลเสร็จสมบูรณ์</strong>
                    <div>ระบบดึงข้อมูลลง EMR และแบ็คอัปขึ้น Cloud เรียบร้อยแล้ว ไปที่หน้าเวชระเบียนได้เลย</div>
                  </div>
                </div>
                ''', unsafe_allow_html=True)
                if st.button("บันทึกผู้ป่วยรายใหม่", icon=":material/refresh:", type="primary", use_container_width=True):
                    active_set_state("READY" if is_backoffice else "WAITING")
                    st.rerun()
                st.markdown("<div style='min-height: 100px;'></div>", unsafe_allow_html=True)
                return

            st.markdown('''
            <div class="workflow-guide">
              <div class="workflow-step"><span class="material-symbols-rounded">mic</span><div><strong>ขั้นที่ 1</strong><small>กดอัดเสียงและรอระบบถอดเสียง</small></div></div>
              <div class="workflow-step"><span class="material-symbols-rounded">arrow_forward</span><div><strong>ขั้นที่ 2</strong><small>ไปที่หน้าเวชระเบียนเพื่อดูสรุปผล</small></div></div>
            </div>
            ''', unsafe_allow_html=True)

            st.markdown('''
            <div class="record-callout info">
              <span class="material-symbols-rounded">mic_external_on</span>
              <div>
                <strong>พร้อมบันทึกเสียง</strong>
                <div>กรุณากดปุ่ม <b>เริ่มอัดเสียง</b> ภายใน 30 วินาที หากเกินเวลาต้องให้คนไข้กดยืนยันใหม่</div>
              </div>
            </div>
            ''', unsafe_allow_html=True)
            audio_key = f"native_audio_recorder_{st.session_state.get('audio_key_counter', 0)}"
            audio_value = auto_recorder(
                cooldown_seconds=0,
                key=audio_key,
            )

            if audio_value:
                audio_bytes = audio_value.get("audio_bytes", b"")
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

                    audio_path.write_bytes(audio_bytes)
                    st.session_state.last_saved_path = str(audio_path)

                    try:
                      st.session_state.audio_task_id = queue_audio(audio_bytes, audio_filename)
                      st.session_state.last_audio_task_id = st.session_state.audio_task_id
                      st.info("บันทึกไฟล์ในเครื่องแล้ว และส่งงานไปประมวลผลเบื้องหลัง")
                    except Exception as exc:
                      st.error(f"ส่งงานไป Core API ไม่สำเร็จ: {exc}")
                      st.warning(f"ไฟล์ถูกเก็บไว้ในเครื่องแล้ว: {audio_filename}")
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
                
                stt_file = STT_DIR / wf_path.name.replace(".wav", "_stt.txt")
                is_ready = stt_file.exists()

                with st.container(border=True):
                    st.markdown(f'''
                    <div class="record-file-card">
                      <div class="record-file-header">
                        <div>
                          <div class="record-file-name">{wf_path.name}</div>
                          <div class="record-file-meta">{ts_str} • {size_kb:.1f} KB</div>
                        </div>
                        <span class="status-pill {'pill-ok' if is_ready else 'pill-warn'}">
                          <span class="status-dot {'dot-green' if is_ready else 'dot-amber'}"></span>
                          {'ถอดเสียงแล้ว' if is_ready else 'รอถอดเสียง'}
                        </span>
                      </div>
                    </div>
                    ''', unsafe_allow_html=True)
                    st.audio(str(wf_path))
                    st.markdown('''
                    <div style="text-align: center; margin-bottom: 8px; color: #10b981; font-size: 0.9rem;">
                      <span class="material-symbols-rounded" style="font-size: 1.1rem; vertical-align: middle;">cloud_done</span> แบ็คอัปขึ้น Cloud แล้ว
                    </div>
                    ''', unsafe_allow_html=True)
                    if st.button("ลบไฟล์", icon=":material/delete:", key=f"del_{rec_id}", use_container_width=True):
                        wf_path.unlink(missing_ok=True)
                        if stt_file.exists():
                            stt_file.unlink(missing_ok=True)
                        st.rerun()
        else:
            st.markdown('''
            <div class="record-empty-state">
              <span class="material-symbols-rounded">folder_open</span>
              <div>ยังไม่มีไฟล์บันทึก</div>
            </div>
            ''', unsafe_allow_html=True)
