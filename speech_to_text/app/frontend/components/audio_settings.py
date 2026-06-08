"""
Audio settings component for device and audio configuration
"""
import streamlit as st
import re
import difflib
from backend.services.audio_service import AudioDeviceManager


def render_audio_settings():
    """
    Render audio settings section
    
    Returns:
        dict: Settings dictionary with rate, channels, chunk, device_index
    """
    st.subheader("🎚️ การตั้งค่าเสียง")
    
    # Get devices
    if 'device_options_cache' not in st.session_state:
        st.session_state.device_options_cache = None
    
    do_refresh = st.button("🔄 รีเฟรชอุปกรณ์", key="refresh_devices")
    
    if (st.session_state.device_options_cache is None) or do_refresh:
        if not st.session_state.get('recording', False):
            try:
                devices = AudioDeviceManager.get_microphone_devices()
                st.session_state.device_options_cache = devices
            except Exception as e:
                st.warning(f"ไม่สามารถสแกนอุปกรณ์ได้: {e}")
                st.session_state.device_options_cache = []
        else:
            st.session_state.device_options_cache = st.session_state.device_options_cache or []
    else:
        devices = st.session_state.device_options_cache or []
    
    # Deduplicate similar device names
    def normalize_name(name: str) -> str:
        n = name.lower()
        n = re.sub(r"\b(array|audio|mic input|communications|default|input|device)\b", "", n)
        n = re.sub(r"[^a-z0-9 ]", "", n)
        n = re.sub(r"\s+", " ", n).strip()
        return n
    
    unique_map = {}
    for d in devices:
        raw = d.get('name', '')
        norm = normalize_name(raw)
        
        # Find similar existing key
        best_key = None
        best_ratio = 0.0
        for k in unique_map.keys():
            r = difflib.SequenceMatcher(None, norm, k).ratio()
            if r > best_ratio:
                best_ratio = r
                best_key = k
        
        is_near_dup = False
        if best_key is not None:
            if best_ratio >= 0.9 or (
                (norm.startswith(best_key) or best_key.startswith(norm)) and 
                abs(len(norm) - len(best_key)) <= 3
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
        'name': d['display_name'],
    } for d in unique_map.values()]
    
    deduped_devices.sort(key=lambda x: x['name'].lower())
    
    device_options = [{'index': None, 'name': 'Default (system)'}] + deduped_devices
    
    # Device selection
    current_device_index = st.session_state.get('cfg_device_index', None)
    try:
        sel_idx = next(
            (i for i, d in enumerate(device_options) if d['index'] == current_device_index),
            0
        )
    except Exception:
        sel_idx = 0
    
    selected_device = st.selectbox(
        "ไมโครโฟน",
        options=device_options,
        index=sel_idx,
        format_func=lambda d: d['name'],
        help="เลือกไมโครโฟนที่ต้องการใช้"
    )
    device_index = selected_device['index']
    
    # Audio settings in columns
    from backend.config import SUPPORTED_SAMPLE_RATES, SUPPORTED_CHUNK_SIZES
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        current_rate = st.session_state.get('cfg_rate', 16000)
        try:
            rate_idx = SUPPORTED_SAMPLE_RATES.index(current_rate)
        except ValueError:
            rate_idx = 1  # Default to 16000
        sample_rate = st.selectbox(
            "Sample Rate",
            options=SUPPORTED_SAMPLE_RATES,
            index=rate_idx,
            help="อัตราการสุ่มตัวอย่างเสียง"
        )
    
    with c2:
        current_channels = st.session_state.get('cfg_channels', 1)
        channels = st.selectbox(
            "Channels",
            options=[1, 2],
            index=[1, 2].index(current_channels) if current_channels in [1, 2] else 0,
            help="จำนวนช่องสัญญาณ (1=Mono, 2=Stereo)"
        )
    
    with c3:
        current_chunk = st.session_state.get('cfg_chunk', 1024)
        try:
            chunk_idx = SUPPORTED_CHUNK_SIZES.index(current_chunk)
        except ValueError:
            chunk_idx = 1  # Default to 1024
        chunk_size = st.selectbox(
            "Chunk Size",
            options=SUPPORTED_CHUNK_SIZES,
            index=chunk_idx,
            help="ขนาด chunk สำหรับการบันทึก"
        )
    
    # Save settings to session state
    st.session_state.cfg_rate = sample_rate
    st.session_state.cfg_channels = channels
    st.session_state.cfg_chunk = chunk_size
    st.session_state.cfg_device_index = device_index
    
    st.caption("💡 การเปลี่ยนค่าใช้กับการบันทึกครั้งถัดไป • หลีกเลี่ยงการสแกนอุปกรณ์ระหว่างกำลังบันทึก")
    
    return {
        'sample_rate': sample_rate,
        'channels': channels,
        'chunk_size': chunk_size,
        'device_index': device_index
    }

