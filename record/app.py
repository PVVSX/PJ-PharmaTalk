import streamlit as st
import pyaudio
import wave
import numpy as np
import io
import os
from datetime import datetime, timedelta
import threading
import time
from streamlit.runtime.scriptrunner import add_script_run_ctx
import re
import difflib
import hashlib

from drive_upload import drive_enabled, local_wav_to_drive_target, upload_wav_to_drive

# Page configuration
st.set_page_config(
    page_title="Audio Recorder",
    page_icon="🎤",
    layout="wide"
)

# Styles: make the main toggle button larger while keeping buttons in expanders compact
st.markdown(
    """
    <style>
    /* Enlarge general buttons */
    div.stButton > button {
        font-size: 1.6rem;
        padding: 1.1rem 0.75rem;
        border-radius: 14px;
    }
    /* Keep buttons inside expanders compact */
    div[data-testid="stExpander"] div.stButton > button {
        font-size: 0.9rem;
        padding: 0.45rem 0.6rem;
        border-radius: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Initialize session state
if 'recording' not in st.session_state:
    st.session_state.recording = False
if 'audio_data' not in st.session_state:
    st.session_state.audio_data = []
if 'recording_thread' not in st.session_state:
    st.session_state.recording_thread = None
if 'last_saved_path' not in st.session_state:
    st.session_state.last_saved_path = None
if 'error' not in st.session_state:
    st.session_state.error = None
if 'show_settings' not in st.session_state:
    st.session_state.show_settings = False
if 'cfg_rate' not in st.session_state:
    st.session_state.cfg_rate = 44100
if 'cfg_channels' not in st.session_state:
    st.session_state.cfg_channels = 1
if 'cfg_chunk' not in st.session_state:
    st.session_state.cfg_chunk = 1024
if 'cfg_device_index' not in st.session_state:
    st.session_state.cfg_device_index = None
if 'device_options_cache' not in st.session_state:
    st.session_state.device_options_cache = None
if 'device_scan_error' not in st.session_state:
    st.session_state.device_scan_error = None

# Audio configuration
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
RECORD_SECONDS = 10


def next_daily_recording_index(record_dir: str, now: datetime) -> int:
    """Next 000-based index for today, from existing files named dd-mm-yy_hh-mm_NNN.wav."""
    y2 = now.year % 100
    prefix = f"{now.day:02d}-{now.month:02d}-{y2:02d}_"
    pattern = re.compile(
        rf"^{re.escape(prefix)}\d{{2}}-\d{{2}}_(\d{{3}})\.wav$"
    )
    max_n = -1
    if os.path.isdir(record_dir):
        for name in os.listdir(record_dir):
            m = pattern.match(name)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def build_recording_filenames(now: datetime, seq: int) -> tuple:
    """
    Local name uses hyphens (Windows cannot use ':' in paths).
    Drive name uses dd:mm:yy_hh:mm as requested.
    """
    y2 = now.year % 100
    d, m, h, mi = now.day, now.month, now.hour, now.minute
    local = f"{d:02d}-{m:02d}-{y2:02d}_{h:02d}-{mi:02d}_{seq:03d}.wav"
    drive = f"{d:02d}:{m:02d}:{y2:02d}_{h:02d}:{mi:02d}_{seq:03d}.wav"
    return local, drive


def record_audio():
    """Record audio in a separate thread"""
    p = None
    stream = None
    try:
        p = pyaudio.PyAudio()
        # Pull current settings from session
        rate = int(st.session_state.get('cfg_rate', RATE))
        channels = int(st.session_state.get('cfg_channels', CHANNELS))
        chunk = int(st.session_state.get('cfg_chunk', CHUNK))
        device_index = st.session_state.get('cfg_device_index', None)
        # Validate format; fallback to a safe combo if needed
        def try_open(target_rate: int, target_channels: int):
            kwargs = dict(
                format=FORMAT,
                channels=target_channels,
                rate=target_rate,
                input=True,
                frames_per_buffer=chunk,
            )
            if device_index is not None:
                kwargs['input_device_index'] = device_index
            return p.open(**kwargs)

        try:
            # Prefer the selected settings
            # Some drivers crash on is_format_supported; so attempt open directly first
            stream = try_open(rate, channels)
        except Exception:
            # Fallback strategies
            fallback_rates = [44100, 48000, 32000, 16000, 8000]
            fallback_channels = [channels, 1]
            opened = False
            for fr in fallback_rates:
                for ch in fallback_channels:
                    try:
                        stream = try_open(fr, ch)
                        rate, channels = fr, ch
                        opened = True
                        break
                    except Exception:
                        continue
                if opened:
                    break
            if not opened:
                raise

        st.session_state.audio_data = []

        while st.session_state.recording:
            # Avoid overflow errors on slower machines
            data = stream.read(chunk, exception_on_overflow=False)
            st.session_state.audio_data.append(data)
            time.sleep(0.01)  # Small delay to prevent overwhelming
    except Exception as e:
        st.session_state.error = f"Microphone error: {e}"
        st.session_state.recording = False
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass

def save_audio():
    """Save recorded audio to file (อัปโหลด Drive ทำจากรายการไฟล์ด้านล่าง)."""
    if not st.session_state.audio_data:
        return None

    now = datetime.now()
    readable_time = now.strftime("%d/%m/%Y %H:%M:%S")
    os.makedirs("record", exist_ok=True)
    record_dir = "record"
    seq = next_daily_recording_index(record_dir, now)
    filename, _ = build_recording_filenames(now, seq)
    filepath = os.path.join(record_dir, filename)

    wf = wave.open(filepath, 'wb')
    wf.setnchannels(int(st.session_state.get('cfg_channels', CHANNELS)))
    wf.setsampwidth(pyaudio.get_sample_size(FORMAT))
    wf.setframerate(int(st.session_state.get('cfg_rate', RATE)))
    wf.writeframes(b''.join(st.session_state.audio_data))
    wf.close()

    st.session_state.last_saved_path = filepath
    return filepath, readable_time

def play_audio():
    """Play the recorded audio"""
    if not st.session_state.audio_data:
        return

    # Encode PCM frames to WAV bytes for reliable browser playback
    pcm_frames = b''.join(st.session_state.audio_data)
    buffer = io.BytesIO()
    wf = wave.open(buffer, 'wb')
    wf.setnchannels(int(st.session_state.get('cfg_channels', CHANNELS)))
    wf.setsampwidth(pyaudio.get_sample_size(FORMAT))
    wf.setframerate(int(st.session_state.get('cfg_rate', RATE)))
    wf.writeframes(pcm_frames)
    wf.close()

    st.audio(buffer.getvalue(), format="audio/wav")


def _pcm_to_mono_line(pcm: bytes, channels: int) -> np.ndarray:
    """Int16 PCM → 1D array for chart (mono or mean of stereo pairs)."""
    if len(pcm) < 2:
        return np.zeros(1, dtype=np.float32)
    arr = np.frombuffer(pcm, dtype=np.int16)
    if channels == 2 and arr.size >= 2:
        arr = arr[: (arr.size // 2) * 2].reshape(-1, 2).mean(axis=1)
    return arr.astype(np.float32)


@st.fragment(run_every=timedelta(milliseconds=110))
def realtime_waveform_panel():
    """Redraws ~9×/s while the session is open; shows live audio while recording."""
    ch = int(st.session_state.get("cfg_channels", CHANNELS))
    recording = st.session_state.recording
    chunks = st.session_state.audio_data

    if recording and chunks:
        # ใช้เฉพาะช่วงท้ายล่าสุดเพื่อให้กราฟเลื่อนแบบ oscilloscope
        max_chunks = 140
        recent = chunks[-max_chunks:] if len(chunks) > max_chunks else chunks
        pcm = b"".join(recent)
        y = _pcm_to_mono_line(pcm, ch)
        max_pts = 3200
        if y.size > max_pts:
            y = y[-max_pts:]
        step = max(1, y.size // 1600)
        y_ds = y[::step] if step > 1 else y
        st.line_chart({"sample": y_ds}, height=220)
    elif not recording and chunks:
        pcm = b"".join(chunks)
        y = _pcm_to_mono_line(pcm, ch)
        if y.size > 8000:
            y = y[:: max(1, y.size // 4000)]
        st.line_chart({"sample": y}, height=220)
        st.caption("บันทึกล่าสุด (หยุดอัดแล้ว) — กด Start เพื่อดูแบบเรียลไทม์อีกครั้ง")
    else:
        st.line_chart({"sample": np.zeros(128)}, height=220)
        st.caption("กด **Start** แล้วพูดใส่ไมค์ — กราฟจะขยับตามเสียงแบบเรียลไทม์")


# Main UI
st.title("🎤 Audio Recorder")
st.markdown("---")

st.caption("📈 Waveform เรียลไทม์")
with st.container(border=True):
    realtime_waveform_panel()

st.markdown("---")

with st.expander("📤 Google Drive — อัปโหลดเมื่อกดปุ่มในรายการไฟล์"):
    st.markdown(
        """
        ใน **Saved Recordings** แต่ละไฟล์มีปุ่ม **☁️** กดเพื่ออัปโหลดเข้าโฟลเดอร์ [Project_record](https://drive.google.com/drive/folders/19z1neaTpHjJ57101faZTwaAwcVkj2A-Q)  
        ย่อยตามชื่อเดือนภาษาอังกฤษ (เช่น `march`, `april`)

        1. สร้าง **Service account** ใน Google Cloud Console แล้วดาวน์โหลดไฟล์ JSON  
        2. เปิดใช้ **Google Drive API** สำหรับโปรเจกต์นั้น  
        3. แชร์โฟลเดอร์รากด้านบนให้ **อีเมลของ service account** (สิทธิ์ *Editor*)  
        4. ตั้งค่า environment variable ชี้ไปที่ JSON อย่างใดอย่างหนึ่ง:
           - `GOOGLE_APPLICATION_CREDENTIALS`  
           - หรือ `GDRIVE_SERVICE_ACCOUNT_JSON`  

        ชื่อบน Drive ใช้รูปแบบ `วัน:เดือน:ปี_ชม:นาที_ลำดับ.wav`  
        ในเครื่อง Windows ไฟล์จะบันทึกเป็น `วัน-เดือน-ปี_ชม-นาที_ลำดับ.wav` (ใช้ขีดแทน `:` เพราะ Windows ไม่อนุญาต `:` ในชื่อไฟล์)
        """
    )

# Single big centered toggle button + settings
left, center, right = st.columns([1, 4, 1])
with center:
    label = "⏹️ Stop" if st.session_state.recording else "🔴 Start"
    # Use a stable key so the widget identity doesn't change when label changes
    if st.button(label, key="record_toggle_button", use_container_width=True):
        if not st.session_state.recording:
            # Start
            st.session_state.error = None
            st.session_state.audio_data = []
            st.session_state.recording = True
            t = threading.Thread(target=record_audio, name="record_audio")
            add_script_run_ctx(t)
            st.session_state.recording_thread = t
            t.start()
            # Immediately rerender so the label switches to Stop
            st.rerun()
        else:
            # Stop and auto-save
            st.session_state.recording = False
            if st.session_state.recording_thread:
                st.session_state.recording_thread.join()
            result = save_audio()
            if result:
                filepath, readable_time = result
                st.success(f"Saved: {filepath}")
                st.info(f"📅 {readable_time}")
            else:
                st.error("No audio data to save")
            # Rerender to switch the label back to Start
            st.rerun()

    # Status under the button
    if st.session_state.recording:
        st.markdown("**🔴 กำลังอัดเสียง...** กดปุ่ม ⏹️ Stop เพื่อหยุด")
        if st.session_state.audio_data:
            duration = (
                len(st.session_state.audio_data)
                * int(st.session_state.get('cfg_chunk', CHUNK))
                / int(st.session_state.get('cfg_rate', RATE))
            )
            st.caption(f"ระยะเวลา: {duration:.1f} วินาที")
    else:
        st.caption("พร้อมอัดเสียง • ปุ่มจะเปลี่ยนเป็น ⏹️ Stop ระหว่างอัด")
    if st.session_state.error:
        st.error(st.session_state.error)

if True:
    st.markdown("---")
    st.subheader("🎚️ Input Settings")

    # Enumerate input devices (avoid scanning while recording to prevent driver issues)
    devices = []
    can_scan = not st.session_state.recording
    do_refresh = st.button("🔄 Refresh devices", key="refresh_devices")
    if (st.session_state.device_options_cache is None) or do_refresh:
        if can_scan:
            try:
                p = pyaudio.PyAudio()
                for i in range(p.get_device_count()):
                    info = p.get_device_info_by_index(i)
                    if int(info.get('maxInputChannels', 0)) > 0:
                        devices.append({
                            'index': i,
                            'raw_name': info.get('name', 'Unknown'),
                            'name': f"[{i}] {info.get('name', 'Unknown')}",
                            'maxInputChannels': int(info.get('maxInputChannels', 0)),
                            'defaultSampleRate': int(float(info.get('defaultSampleRate', 0))) if 'defaultSampleRate' in info else 0,
                        })
                p.terminate()
                st.session_state.device_scan_error = None
            except Exception as e:
                st.session_state.device_scan_error = str(e)
                devices = []
            st.session_state.device_options_cache = devices
        else:
            devices = st.session_state.device_options_cache or []
    else:
        devices = st.session_state.device_options_cache or []

    # Keep only devices that look like microphones by name ("mic" or "microphone")
    mic_devices = [
        d for d in devices
        if ('mic' in d.get('raw_name', '').lower()) or ('microphone' in d.get('raw_name', '').lower())
    ]
    usable_devices = mic_devices if mic_devices else devices

    # Fuzzy-deduplicate names that are nearly identical (e.g., "Mini" vs "Min")
    def normalize_name(name: str) -> str:
        n = name.lower()
        # Remove common noise words
        n = re.sub(r"\b(array|audio|mic input|communications|default|input|device)\b", "", n)
        # Remove punctuation and collapse spaces
        n = re.sub(r"[^a-z0-9 ]", "", n)
        n = re.sub(r"\s+", " ", n).strip()
        return n

    unique_map = {}  # key: canonical normalized name -> best device dict with 'display_name'
    for d in usable_devices:
        raw = d.get('raw_name', '')
        norm = normalize_name(raw)

        # Find an existing key that is very similar
        best_key = None
        best_ratio = 0.0
        for k in unique_map.keys():
            r = difflib.SequenceMatcher(None, norm, k).ratio()
            if r > best_ratio:
                best_ratio = r
                best_key = k

        is_near_dup = False
        if best_key is not None:
            # Consider near-duplicate if high similarity or short prefix difference
            if best_ratio >= 0.9 or (
                (norm.startswith(best_key) or best_key.startswith(norm)) and abs(len(norm) - len(best_key)) <= 3
            ):
                is_near_dup = True

        key = best_key if is_near_dup else norm

        if key not in unique_map:
            unique_map[key] = {
                **d,
                'display_name': raw,
            }
        else:
            keep = unique_map[key]
            cand_score = (d['maxInputChannels'], d['defaultSampleRate'], -d['index'])
            keep_score = (keep['maxInputChannels'], keep['defaultSampleRate'], -keep['index'])
            if cand_score > keep_score:
                unique_map[key] = {
                    **d,
                    'display_name': raw,
                }

    deduped_devices = [{
        'index': d['index'],
        'name': d['display_name'],  # cleaner label without bracketed index
    } for d in unique_map.values()]

    # Sort by name for stable UX
    deduped_devices.sort(key=lambda x: x['name'].lower())

    device_options = [{'index': None, 'name': 'Default (system)'}] + deduped_devices
    # Determine current selection index
    current_device_index = st.session_state.get('cfg_device_index', None)
    try:
        sel_idx = next(
            (i for i, d in enumerate(device_options) if d['index'] == current_device_index),
            0
        )
    except Exception:
        sel_idx = 0

    selected_device = st.selectbox(
        "ไมโครโฟน (Microphone เท่านั้น)",
        options=device_options,
        index=sel_idx,
        format_func=lambda d: d['name']
    )
    st.session_state.cfg_device_index = selected_device['index']

    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state.cfg_rate = st.selectbox(
            "Sample Rate",
            options=[8000, 16000, 22050, 32000, 44100, 48000],
            index=[8000,16000,22050,32000,44100,48000].index(
                int(st.session_state.get('cfg_rate', RATE))
            )
        )
    with c2:
        st.session_state.cfg_channels = st.selectbox(
            "Channels",
            options=[1, 2],
            index=[1,2].index(int(st.session_state.get('cfg_channels', CHANNELS)))
        )
    with c3:
        st.session_state.cfg_chunk = st.selectbox(
            "Chunk Size",
            options=[512, 1024, 2048, 4096],
            index=[512,1024,2048,4096].index(int(st.session_state.get('cfg_chunk', CHUNK)))
        )
    if st.session_state.device_scan_error:
        st.warning(f"Device scan error: {st.session_state.device_scan_error}")
    st.caption("โชว์เฉพาะไมค์และลบรายการซ้ำตามชื่อ (เลือกตัวที่เหมาะสมที่สุดให้) • หากไม่พบไมค์ จะแสดงทุกอุปกรณ์รับเสียง • การเปลี่ยนค่าใช้กับการอัดครั้งถัดไป • เลี่ยงสแกนระหว่างกำลังอัดเพื่อความเสถียร")


# Optional preview/playback right under the button
if st.session_state.audio_data:
    st.caption("Preview of last take")
    play_audio()

# Status display (moved under the main button)

# File management
st.markdown("---")
st.subheader("📁 Saved Recordings")

# List saved recordings
recordings_dir = "record"
if os.path.exists(recordings_dir):
    recordings = [f for f in os.listdir(recordings_dir) if f.endswith('.wav')]
    
    if recordings:
        # Sort recordings by modification time (newest first)
        recordings_with_time = []
        for recording in recordings:
            filepath = os.path.join(recordings_dir, recording)
            mod_time = os.path.getmtime(filepath)
            recordings_with_time.append((recording, mod_time, filepath))
        
        # Sort by modification time (newest first)
        recordings_with_time.sort(key=lambda x: x[1], reverse=True)
        
        for recording, mod_time, filepath in recordings_with_time:
            file_size = os.path.getsize(filepath)
            readable_time = datetime.fromtimestamp(mod_time).strftime("%d/%m/%Y %H:%M:%S")
            
            # Create expandable section for each recording
            with st.expander(f"📄 {recording} - {readable_time}", expanded=False):
                rec_id = hashlib.md5(recording.encode("utf-8")).hexdigest()[:20]

                st.write(f"**File:** {recording}")
                st.caption(f"📊 Size: {file_size / 1024:.1f} KB")
                st.caption(f"📅 Created: {readable_time}")

                if st.button(
                    "☁️ อัปโหลด Google Drive",
                    key=f"gdrive_upload_{rec_id}",
                    use_container_width=True,
                    type="primary",
                    help="อัปโหลดไฟล์นี้ไปโฟลเดอร์ตามเดือนใน Google Drive",
                ):
                    if not drive_enabled():
                        st.session_state[f"gdrive_msg_{rec_id}"] = (
                            False,
                            "ยังไม่ได้ตั้ง credentials — ตั้งค่า environment variable "
                            "`GOOGLE_APPLICATION_CREDENTIALS` หรือ `GDRIVE_SERVICE_ACCOUNT_JSON` "
                            "ให้ชี้ไปที่ไฟล์ JSON ของ service account (ดูคำแนะนำในแถบ Google Drive ด้านบน)",
                        )
                    else:
                        dname, month = local_wav_to_drive_target(
                            recording, mod_time
                        )
                        ok, msg = upload_wav_to_drive(filepath, dname, month)
                        st.session_state[f"gdrive_msg_{rec_id}"] = (ok, msg)
                    st.rerun()

                col_play, col_dl, col_del = st.columns(3)
                with col_play:
                    if st.button("▶️ Play", key=f"play_{rec_id}"):
                        with open(filepath, "rb") as audio_file:
                            st.audio(audio_file.read(), format="audio/wav")

                with col_dl:
                    if st.button("📥 Download", key=f"dlbtn_{rec_id}"):
                        with open(filepath, "rb") as audio_file:
                            st.download_button(
                                label="Download Audio",
                                data=audio_file.read(),
                                file_name=recording,
                                mime="audio/wav",
                                key=f"dl_{rec_id}",
                            )

                with col_del:
                    if st.button("🗑️ Delete", key=f"delete_{rec_id}"):
                        os.remove(filepath)
                        st.rerun()

                gmsg_key = f"gdrive_msg_{rec_id}"
                gmsg = st.session_state.pop(gmsg_key, None)
                if gmsg is not None:
                    ok, text = gmsg
                    if ok:
                        st.success(text)
                    else:
                        st.warning(text)
    else:
        st.info("📭 No recordings found in record/ directory")
else:
    st.info("📁 record/ directory not found - will be created when you save your first recording")

# Instructions
st.markdown("---")
st.subheader("📖 How to Use")
st.markdown("""
1. ดูกราฟ **Waveform เรียลไทม์** ด้านบน — จะขยับตามเสียงขณะกด Start อัด
2. กดปุ่มใหญ่เพื่อเริ่มอัดเสียง
3. กดปุ่มเดิมอีกครั้งเพื่อหยุด ระบบจะบันทึกไฟล์อัตโนมัติ
4. ดูไฟล์ที่บันทึกในส่วน "Saved Recordings" แล้วกด **อัปโหลด Google Drive** ต่อไฟล์

หมายเหตุ: ตรวจสอบสิทธิ์ไมโครโฟนหากไม่พบเสียง
""")

# Footer
st.markdown("---")
st.markdown("Made with ❤️ using Streamlit")
