# -*- coding: utf-8 -*-
"""Page 1 — Audio Recorder (อัดเสียง)"""
from __future__ import annotations

import hashlib
import io
import threading
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

# ── Shared references from app.py context ──
import sys, os
ROOT = Path(__file__).resolve().parent.parent.parent
UNIFIED = Path(__file__).resolve().parent.parent
RECORD_DIR = ROOT / "record"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

from unified_app.modules.stt_typhoon import transcribe_audio_bytes


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _save_audio() -> tuple[str, str] | None:
    if not st.session_state.audio_data:
        return None
    AUDIO_DIR = RECORD_DIR / "audio"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    filename = now.strftime("%d-%m-%y_%H-%M") + "_000.wav"
    filepath = AUDIO_DIR / filename
    try:
        import pyaudio
        wf = wave.open(str(filepath), "wb")
        wf.setnchannels(int(st.session_state.cfg_channels))
        wf.setsampwidth(pyaudio.get_sample_size(pyaudio.paInt16))
        wf.setframerate(int(st.session_state.cfg_rate))
        wf.writeframes(b"".join(st.session_state.audio_data))
        wf.close()
        st.session_state.last_saved_path = str(filepath)
        return str(filepath), now.strftime("%d/%m/%Y %H:%M:%S")
    except Exception as exc:
        st.session_state.rec_error = f"บันทึกไฟล์ไม่สำเร็จ: {exc}"
        return None


def _record_audio() -> None:
    """Thread target — reads from microphone until recording=False."""
    if not PYAUDIO_AVAILABLE:
        st.session_state.rec_error = "ไม่พบ pyaudio — ติดตั้งด้วย: pip install pyaudio"
        st.session_state.recording = False
        return
    import pyaudio
    p = None; stream = None
    try:
        p      = pyaudio.PyAudio()
        rate   = int(st.session_state.cfg_rate)
        ch     = int(st.session_state.cfg_channels)
        chunk  = int(st.session_state.cfg_chunk)
        dev    = st.session_state.cfg_device_index
        kwargs = dict(format=pyaudio.paInt16, channels=ch, rate=rate, input=True, frames_per_buffer=chunk)
        if dev is not None:
            kwargs["input_device_index"] = dev
        stream = p.open(**kwargs)
        st.session_state.audio_data = []
        while st.session_state.recording:
            data = stream.read(chunk, exception_on_overflow=False)
            st.session_state.audio_data.append(data)
            time.sleep(0.005)
    except Exception as exc:
        st.session_state.rec_error = f"ข้อผิดพลาดไมค์: {exc}"
        st.session_state.recording = False
    finally:
        for obj in [stream, p]:
            if obj:
                try: obj.stop_stream() if hasattr(obj, "stop_stream") else None
                except: pass
                try: obj.close() if hasattr(obj, "close") else obj.terminate()
                except: pass


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE CONTENT
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="page-header">
  <span class="material-symbols-rounded page-header-icon">mic</span>
  <div>
    <h2 class="page-title">เครื่องบันทึกเสียง</h2>
    <p class="page-subtitle">Audio Recorder — ระบบบันทึกเสียงแบบ Real-time</p>
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

# ── LEFT: Waveform + Record Controls ───────────────────────────────────
with t1L:
    with st.container(border=True):
        st.markdown("""
        <div class="card-accent-bar accent-blue"></div>
        <div class="section-header">
          <div class="sh-icon sh-blue"><span class="material-symbols-rounded">graphic_eq</span></div>
          <span class="section-title">สถานะเสียง</span>
          <span class="section-sub">Real-time</span>
        </div>""", unsafe_allow_html=True)

        # ── Waveform ──
        st.markdown('<div class="waveform-wrap">', unsafe_allow_html=True)

        @st.fragment(run_every=timedelta(milliseconds=130))
        def _realtime_waveform():
            chunks = st.session_state.audio_data
            if st.session_state.recording and chunks:
                recent = chunks[-140:] if len(chunks) > 140 else chunks
                y = np.frombuffer(b"".join(recent), dtype=np.int16).astype(np.float32)
                if y.size > 3200: y = y[-3200:]
                step = max(1, y.size // 1600)
                # เพิ่ม noise ให้ดูกราฟไม่แบนราบตอนเงียบ
                noise = np.random.normal(0, 50, len(y[::step]))
                st.line_chart({"เสียง": y[::step] + noise}, height=200)
            elif chunks:
                y = np.frombuffer(b"".join(chunks), dtype=np.int16).astype(np.float32)
                if y.size > 8000: y = y[::max(1, y.size // 4000)]
                st.line_chart({"เสียง": y}, height=200)
            else:
                st.line_chart({"เสียง": np.zeros(128)}, height=200)

        _realtime_waveform()
        st.markdown('</div>', unsafe_allow_html=True)

        # ── Duration info ──
        chunks    = st.session_state.audio_data
        cfg_chunk = int(st.session_state.cfg_chunk)
        cfg_rate  = int(st.session_state.cfg_rate)
        duration  = len(chunks) * cfg_chunk / cfg_rate if chunks else 0.0

        if st.session_state.recording:
            st.markdown(f"""
            <div class="rec-banner" style="background-color: var(--red-500); color: white; border: none; padding: 16px; border-radius: 8px; font-size: 1.2rem; text-align: center; margin-bottom: 20px;">
              <span class="material-symbols-rounded" style="vertical-align: middle; animation: blink 1s infinite alternate;">radio_button_checked</span>
              <span style="margin-left: 8px;">กำลังอัดเสียง... {duration:.1f} วินาที</span>
            </div>""", unsafe_allow_html=True)
        elif chunks:
            st.markdown(f"""
            <div class="tip-box" style="margin-bottom: 20px;">
              <span class="material-symbols-rounded" style="font-size:1.1em;vertical-align:middle;color:var(--green-600);">check_circle</span>
              มีเสียงที่อัดไว้ <strong>{duration:.1f} วินาที</strong>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="tip-box" style="margin-bottom: 20px;">
              <span class="material-symbols-rounded" style="font-size:1.1em;vertical-align:middle;color:var(--blue-500);">info</span>
              กดปุ่มด้านล่างเพื่อเริ่มการอัดเสียง
            </div>""", unsafe_allow_html=True)

        # ── Record Button ──
        is_rec = st.session_state.recording
        btn_label = "หยุดบันทึก" if is_rec else "เริ่มต้นการอัดเสียง"

        if st.button(btn_label, key="record_toggle_button", use_container_width=True, type="primary" if not is_rec else "secondary"):
            if not is_rec:
                st.session_state.rec_error  = None
                st.session_state.audio_data = []
                st.session_state.recording  = True
                t = threading.Thread(target=_record_audio, name="record_audio", daemon=True)
                add_script_run_ctx(t)
                st.session_state.recording_thread = t
                t.start()
                st.rerun()
            else:
                st.session_state.recording = False
                if st.session_state.recording_thread:
                    st.session_state.recording_thread.join(timeout=3)
                result = _save_audio()
                if result:
                    fp, ts = result
                    
                    st.success(f"บันทึกแล้ว: `{Path(fp).name}`")
                    if st.session_state.model_loaded:
                        with st.spinner("กำลังถอดเสียงอัตโนมัติ..."):
                            try:
                                audio_bytes = Path(fp).read_bytes()
                                txt = transcribe_audio_bytes(st.session_state.recognizer, audio_bytes)
                                
                                STT_DIR = RECORD_DIR / "stt"
                                STT_DIR.mkdir(parents=True, exist_ok=True)
                                
                                stt_fp = STT_DIR / Path(fp).name.replace(".wav", "_stt.txt")
                                stt_fp.write_text(txt, encoding="utf-8")
                                st.success("ถอดเสียงอัตโนมัติเสร็จสิ้น สามารถดูผลได้ที่หน้า 'ประวัติข้อมูล'")
                            except Exception as e:
                                st.error(f"ถอดเสียงอัตโนมัติไม่สำเร็จ: {e}")
                else:
                    st.error("ไม่มีข้อมูลเสียงที่จะบันทึก")
                st.rerun()

        if st.session_state.rec_error:
            st.error(st.session_state.rec_error)

        # ── Audio Preview ──
        if chunks:
            st.markdown("---")
            st.markdown("**ตัวอย่างเสียงที่อัดล่าสุด**")
            buf = io.BytesIO()
            if PYAUDIO_AVAILABLE:
                import pyaudio
                wf = wave.open(buf, "wb")
                wf.setnchannels(int(st.session_state.cfg_channels))
                wf.setsampwidth(pyaudio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(int(st.session_state.cfg_rate))
                wf.writeframes(b"".join(chunks))
                wf.close()
                st.audio(buf.getvalue(), format="audio/wav")

# ── RIGHT: Saved Recordings ────────────────────────────────
with t1R:
    with st.container(border=True):
        AUDIO_DIR = RECORD_DIR / "audio"
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        wav_files = sorted(AUDIO_DIR.glob("*.wav"),
                           key=lambda p: p.stat().st_mtime, reverse=True)

        st.markdown(f"""
        <div class="card-accent-bar accent-teal"></div>
        <div class="section-header">
          <div class="sh-icon sh-teal"><span class="material-symbols-rounded">folder</span></div>
          <span class="section-title">ไฟล์บันทึก</span>
          <span class="section-sub">{len(wav_files)} ไฟล์</span>
        </div>""", unsafe_allow_html=True)

        if wav_files:
            for wf_path in wav_files:
                mtime     = wf_path.stat().st_mtime
                ts_str    = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                size_kb   = wf_path.stat().st_size / 1024
                rec_id    = hashlib.md5(wf_path.name.encode()).hexdigest()[:16]

                with st.expander(f"{wf_path.name}", expanded=False):
                    st.caption(f"{ts_str}  •  {size_kb:.1f} KB")
                    col_play, col_del = st.columns([2, 1])
                    with col_play:
                        st.audio(wf_path.read_bytes(), format="audio/wav")
                    with col_del:
                        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                        if st.button("ลบ", icon=":material/delete:", key=f"del_{rec_id}", use_container_width=True):
                            wf_path.unlink(missing_ok=True)
                            st.rerun()
        else:
            st.info("ยังไม่มีไฟล์บันทึก")
