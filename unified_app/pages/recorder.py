# -*- coding: utf-8 -*-
"""Page — Audio Recorder (อัดเสียง). Shared by the pharmacist portal (consent required) and the back-office (no consent gate)."""
from __future__ import annotations

import hashlib
import html
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit_autorefresh import st_autorefresh

ROOT = Path(__file__).resolve().parent.parent.parent
RECORD_DIR = ROOT / "record"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_app.modules.state_manager import BRIDGE_PUBLIC_URL, get_state_full, set_state
from unified_app.modules.task_api import get_core_health, get_task, queue_audio, retry_task
from unified_app.components.auto_recorder import auto_recorder

try:
    from core_api.firebase_config import upload_file_to_storage
except Exception:
    upload_file_to_storage = None

AUDIO_DIR = RECORD_DIR / "audio"
STT_DIR = RECORD_DIR / "stt"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
STT_DIR.mkdir(parents=True, exist_ok=True)
IS_BACKOFFICE = bool(st.session_state.get("is_backoffice", False))
SOURCE = "backoffice" if IS_BACKOFFICE else "pharmacist"

# Refresh while a task runs, or while the pharmacist waits for the patient's consent.
if st.session_state.get("audio_task_id") or (not IS_BACKOFFICE and not st.session_state.get("pending_audio")):
    st_autorefresh(interval=2000, key="recorder_state_refresh")

st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">mic</span>
  <div>
    <h2 class="page-title">เครื่องบันทึกเสียง</h2>
    <p class="page-subtitle">Audio Recorder — บันทึกบทสนทนาและส่งถอดเสียง/สรุปเวชระเบียน</p>
  </div>
</div>
""", unsafe_allow_html=True)

try:
    core_health = get_core_health()
except Exception:
    core_health = {}
core_ready = bool(core_health.get("asr_loaded"))
cloud_on = bool(core_health.get("cloud_enabled"))

c1, c2, c3 = st.columns([2, 1, 1], gap="small")
with c1:
    if core_ready:
        st.markdown(f'<div class="record-status-banner ok"><span class="material-symbols-rounded">check_circle</span>'
                    f'<span>ระบบถอดเสียงพร้อม ({html.escape(str(core_health.get("stt_engine", "")))} บน {html.escape(str(core_health.get("stt_device", "")))})</span></div>',
                    unsafe_allow_html=True)
    else:
        why = core_health.get("stt_error") or "ตรวจว่า Core API รันอยู่ที่พอร์ต 8080 และโหลดโมเดลเสร็จแล้ว"
        st.markdown(f'<div class="record-status-banner warn"><span class="material-symbols-rounded">warning</span><span>ระบบถอดเสียงยังไม่พร้อม: {html.escape(why)}</span></div>', unsafe_allow_html=True)
with c2:
    mode = "หลังบ้าน (ไม่ต้องรอยินยอม)" if IS_BACKOFFICE else "เภสัชกร (ต้องมีความยินยอม)"
    st.markdown(f'<div class="record-mini-stat"><span class="label">โหมด</span><strong>{mode}</strong></div>', unsafe_allow_html=True)
with c3:
    n_audio = len(list(AUDIO_DIR.glob("*.wav")))
    st.markdown(f'<div class="record-mini-stat"><span class="label">ไฟล์เสียงในเครื่อง</span><strong>{n_audio}</strong></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
left, right = st.columns([3, 2], gap="large")


def _callout(kind: str, icon: str, title: str, body: str) -> None:
    st.markdown(f'<div class="record-callout {kind}"><span class="material-symbols-rounded">{icon}</span>'
                f'<div><strong>{title}</strong><div>{body}</div></div></div>', unsafe_allow_html=True)


def _reset_for_next_patient() -> None:
    for k in ("pending_audio", "audio_task_id", "last_saved_path", "last_audio_hash", "finished_task"):
        st.session_state[k] = None
    st.session_state.audio_key_counter = st.session_state.get("audio_key_counter", 0) + 1
    if not IS_BACKOFFICE:
        set_state("WAITING", reason="new_patient")


def render_task_progress(task_id: str) -> bool:
    """Show the running/finished task. Returns True when the page should stop here."""
    try:
        task = get_task(task_id)
    except Exception as exc:
        st.warning(f"ยังเชื่อมต่อ Core API ไม่ได้: {exc}")
        return True
    status = task.get("status", "UNKNOWN")
    steps = {"UPLOADED": "รอคิว", "STT_PROCESSING": "กำลังถอดเสียง", "STT_DONE": "ถอดเสียงเสร็จ",
             "EMR_PROCESSING": "กำลังสรุปเวชระเบียน (AI)"}
    if status not in ("COMPLETED", "ERROR"):
        st.info(f"กำลังประมวลผล: {steps.get(status, status)} …", icon=":material/hourglass_top:")
        return True
    if status == "ERROR":
        st.error(f"ประมวลผลไม่สำเร็จ: {task.get('error_message') or 'ไม่ทราบสาเหตุ'}")
        b1, b2 = st.columns(2)
        with b1:
            if task.get("can_retry") and st.button("ลองประมวลผลใหม่", icon=":material/replay:", type="primary", use_container_width=True):
                try:
                    retry_task(task_id)
                    st.rerun()
                except Exception as exc:
                    st.error(f"ลองใหม่ไม่ได้: {exc}")
        with b2:
            if st.button("ยกเลิกและเริ่มใหม่", icon=":material/refresh:", use_container_width=True):
                _reset_for_next_patient(); st.rerun()
        return True
    # COMPLETED (handle once)
    if st.session_state.get("finished_task") != task_id:
        saved = st.session_state.get("last_saved_path")
        if saved:
            (STT_DIR / (Path(saved).stem + "_stt.txt")).write_text(task.get("stt_text") or "", encoding="utf-8")
        st.session_state.emr_conv_input = task.get("stt_text") or ""
        st.session_state.last_audio_task_id = task_id
        st.session_state.finished_task = task_id
        if not IS_BACKOFFICE:
            ok, msg = set_state("FINISHED", consent={"consent_id": task.get("consent_id")} if task.get("consent_id") else None,
                                task_id=task_id, audio_filename=task.get("audio_filename"))
            if not ok:
                st.warning(f"บันทึกการปิดงานในระบบยินยอมไม่สำเร็จ: {msg}")
    where = "และบันทึกผลขึ้นฐานข้อมูล Cloud (Firestore) แล้ว" if cloud_on else "(เก็บในเครื่องเท่านั้น ระบบ Cloud ปิดอยู่)"
    _callout("success", "check_circle", "ถอดเสียงและสรุปเวชระเบียนเสร็จแล้ว",
             f"{where} — ไฟล์เสียงเก็บไว้ในเครื่อง กด 'อัปโหลด Cloud' ทางขวาถ้าต้องการสำรองเสียง "
             "จากนั้นไปที่หน้า <b>วิเคราะห์ EMR</b> เพื่อตรวจทานและยืนยัน")
    if st.button("บันทึกผู้ป่วยรายใหม่", icon=":material/person_add:", type="primary", use_container_width=True):
        _reset_for_next_patient(); st.rerun()
    return True


def render_recorder() -> None:
    task_id = st.session_state.get("audio_task_id")
    if task_id and render_task_progress(task_id):
        return

    consent_id = None
    if not IS_BACKOFFICE:
        state = get_state_full()
        status = state.get("status", "WAITING")
        consent_id = (state.get("consent") or {}).get("consent_id")
        if state.get("_source") == "file":
            st.warning("เชื่อมต่อระบบยืนยันความยินยอม (พอร์ต 8500) ไม่ได้ — ต้องเปิด api.py ก่อน")
        if status == "WAITING" and not st.session_state.get("pending_audio"):
            _callout("warning", "privacy_tip", "รอการยืนยันความยินยอม",
                     "ให้คนไข้กดยินยอมที่หน้าจอ Consent ก่อน ระบบจึงจะเปิดให้บันทึกเสียง (ถ้าคนไข้ไม่ยินยอม ระบบจะไม่บันทึก)")
            return
        if status == "FINISHED" and not st.session_state.get("pending_audio"):
            _callout("info", "task_alt", "เคสก่อนหน้าปิดงานแล้ว", "กดปุ่มด้านล่างเพื่อรอคนไข้รายถัดไป")
            if st.button("รอคนไข้รายใหม่", icon=":material/person_add:", type="primary", use_container_width=True):
                _reset_for_next_patient(); st.rerun()
            return

    pending = st.session_state.get("pending_audio")
    if pending:
        _callout("info", "check_circle", "บันทึกเสียงเสร็จแล้ว",
                 "ฟังทวนแล้วกด <b>ส่งประมวลผล</b> เพื่อถอดเสียงและสรุปเวชระเบียน หรือกด <b>อัดใหม่</b>")
        st.audio(pending["bytes"], format="audio/wav")
        u, c = st.columns([3, 2], gap="small")
        with u:
            if st.button("ส่งประมวลผล (ถอดเสียง + สรุป EMR)", icon=":material/send:", type="primary", use_container_width=True, disabled=not core_ready):
                try:
                    st.session_state.audio_task_id = queue_audio(pending["bytes"], pending["filename"],
                                                                 consent_id=pending.get("consent_id"), source=SOURCE)
                    st.session_state.pending_audio = None
                    st.rerun()
                except Exception as exc:
                    st.error(f"ส่งงานไป Core API ไม่สำเร็จ: {exc}")
        with c:
            if st.button("อัดใหม่ (ทิ้งไฟล์นี้)", icon=":material/refresh:", use_container_width=True):
                Path(pending.get("path", "")).unlink(missing_ok=True)
                st.session_state.pending_audio = None
                st.session_state.last_saved_path = None
                st.session_state.audio_key_counter = st.session_state.get("audio_key_counter", 0) + 1
                st.rerun()
        return

    st.markdown('''
    <div class="workflow-guide">
      <div class="workflow-step"><span class="material-symbols-rounded">mic</span><div><strong>ขั้นที่ 1</strong><small>กดอัดเสียงสนทนา</small></div></div>
      <div class="workflow-step"><span class="material-symbols-rounded">send</span><div><strong>ขั้นที่ 2</strong><small>ฟังทวนแล้วกดส่งประมวลผล</small></div></div>
      <div class="workflow-step"><span class="material-symbols-rounded">assignment</span><div><strong>ขั้นที่ 3</strong><small>ตรวจทานและยืนยันในหน้า EMR</small></div></div>
    </div>''', unsafe_allow_html=True)
    if IS_BACKOFFICE:
        _callout("info", "mic_external_on", "พร้อมบันทึกเสียง (โหมดหลังบ้าน)", "บันทึกได้ทันทีโดยไม่ต้องรอหน้าจอขอความยินยอม")
    else:
        state = get_state_full()
        left_s = state.get("expires_in")
        extra = f" (เหลือเวลาเริ่มอัดอีก {left_s} วินาที)" if state.get("status") == "READY" and left_s is not None else ""
        _callout("info", "mic_external_on", "คนไข้ยินยอมแล้ว พร้อมบันทึกเสียง",
                 f"กด <b>เริ่มอัดเสียง</b>{extra} ถ้าเกินเวลาต้องให้คนไข้กดยินยอมใหม่")

    value = auto_recorder(key=f"rec_{st.session_state.get('audio_key_counter', 0)}",
                          api_url="" if IS_BACKOFFICE else f"{BRIDGE_PUBLIC_URL}/api/state")
    if not value:
        return
    audio_bytes = value["audio_bytes"]
    h = hashlib.md5(audio_bytes).hexdigest()
    if st.session_state.get("last_audio_hash") == h:
        return
    st.session_state.last_audio_hash = h
    if not IS_BACKOFFICE:
        state = get_state_full()
        consent_id = (state.get("consent") or {}).get("consent_id")
        if state.get("status") != "RECORDING" or not consent_id:
            st.error("ไม่มีความยินยอมที่ใช้ได้ระหว่างอัดเสียง ไฟล์นี้ถูกทิ้งและจะไม่ถูกส่งประมวลผล")
            return
    name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ("_bo" if IS_BACKOFFICE else "_ph") + ".wav"
    path = AUDIO_DIR / name
    path.write_bytes(audio_bytes)
    st.session_state.last_saved_path = str(path)
    st.session_state.pending_audio = {"bytes": audio_bytes, "filename": name, "path": str(path), "consent_id": consent_id}
    st.session_state.audio_key_counter = st.session_state.get("audio_key_counter", 0) + 1
    st.rerun()


with left:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-blue"></div>
        <div class="section-header">
          <div class="sh-icon sh-blue"><span class="material-symbols-rounded">graphic_eq</span></div>
          <span class="section-title">อัดเสียงสนทนา</span>
        </div>""", unsafe_allow_html=True)
        render_recorder()

with right:
    with st.container(border=True):
        wav_files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        st.markdown(f"""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
          <div class="sh-icon sh-teal"><span class="material-symbols-rounded">folder</span></div>
          <span class="section-title">ไฟล์เสียงในเครื่อง</span>
          <span class="section-sub">{len(wav_files)} ไฟล์</span>
        </div>""", unsafe_allow_html=True)
        if not wav_files:
            st.markdown('<div class="record-empty-state"><span class="material-symbols-rounded">folder_open</span><div>ยังไม่มีไฟล์บันทึก</div></div>', unsafe_allow_html=True)
        for wf in wav_files[:30]:
            rec_id = hashlib.md5(wf.name.encode()).hexdigest()[:16]
            ready = (STT_DIR / (wf.stem + "_stt.txt")).exists()
            with st.container(border=True):
                st.markdown(f'''
                <div class="record-file-card"><div class="record-file-header"><div>
                  <div class="record-file-name">{html.escape(wf.name)}</div>
                  <div class="record-file-meta">{datetime.fromtimestamp(wf.stat().st_mtime).strftime("%d/%m/%Y %H:%M")} • {wf.stat().st_size / 1024:.0f} KB</div>
                </div>
                <span class="status-pill {'pill-ok' if ready else 'pill-warn'}"><span class="status-dot {'dot-green' if ready else 'dot-amber'}"></span>
                {'ถอดเสียงแล้ว' if ready else 'ยังไม่ถอดเสียง'}</span></div></div>''', unsafe_allow_html=True)
                st.audio(str(wf))
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("อัปโหลด Cloud", icon=":material/cloud_upload:", key=f"up_{rec_id}", use_container_width=True):
                        if upload_file_to_storage is None:
                            st.error("ระบบ Firebase ยังไม่พร้อมใช้งาน")
                        else:
                            try:
                                upload_file_to_storage(str(wf), f"recordings/{wf.name}")
                                st.success("อัปโหลดขึ้น Cloud สำเร็จแล้ว")
                            except Exception as up_err:
                                st.error(f"อัปโหลดไม่สำเร็จ: {up_err}")
                with b2:
                    confirm_key = f"confirm_del_{rec_id}"
                    if st.session_state.get(confirm_key):
                        if st.button("ยืนยันลบถาวร", icon=":material/delete_forever:", key=f"del2_{rec_id}", use_container_width=True, type="primary"):
                            wf.unlink(missing_ok=True)
                            (STT_DIR / (wf.stem + "_stt.txt")).unlink(missing_ok=True)
                            st.session_state[confirm_key] = False
                            st.rerun()
                    elif st.button("ลบไฟล์", icon=":material/delete:", key=f"del_{rec_id}", use_container_width=True):
                        st.session_state[confirm_key] = True
                        st.rerun()
