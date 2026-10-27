# -*- coding: utf-8 -*-
"""
PharmaLog AI: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ — Benchmark Lab (compact UI)
Two main tabs: speech-to-text ablation, and EMR model comparison.
"""

from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

import streamlit as st

# ── Path setup (Standalone) ──
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

try:
    import emr_models as emr
    from pipeline import (
        CACHE_DIR,
        get_audio_hash,
        get_cached_result,
        process_audio_full_pipeline,
        rebuild_cached_pipeline,
        resolve_output_by_toggles,
    )
    from modules.pharmacy_dict import (
        load_custom_dict,
        add_custom_word,
        remove_custom_word,
    )
    from modules.emr_pdf import generate_emr_pdf
except (ImportError, KeyError):
    from lab import emr_models as emr
    from lab.pipeline import (
        CACHE_DIR,
        get_audio_hash,
        get_cached_result,
        process_audio_full_pipeline,
        rebuild_cached_pipeline,
        resolve_output_by_toggles,
    )
    from lab.modules.pharmacy_dict import (
        load_custom_dict,
        add_custom_word,
        remove_custom_word,
    )
    from lab.modules.emr_pdf import generate_emr_pdf

st.set_page_config(
    page_title="PharmaLog AI Lab: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์",
    page_icon=":material/biotech:",
    layout="wide",
    initial_sidebar_state="expanded",
)

css_file = APP_DIR / "style.css"
if css_file.exists():
    st.markdown(f"<style>{css_file.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# Auto-expand sidebar if collapsed
st.html(
    """
    <script>
    function ensureSidebarOpen() {
        try {
            const doc = window.parent.document;
            const btn = doc.querySelector('[data-testid="stExpandSidebarButton"]') || doc.querySelector('[data-testid="collapsedControl"]');
            if (btn) {
                btn.click();
            }
        } catch(e) {}
    }
    setTimeout(ensureSidebarOpen, 150);
    setTimeout(ensureSidebarOpen, 500);
    </script>
    """
)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def icon(name: str) -> str:
    return f'<span class="material-symbols-rounded">{name}</span>'


def scan_audio_files() -> list[Path]:
    dirs = [
        APP_DIR / "sample_audio",
        APP_DIR / "audio",
        APP_DIR.parent / "result_record" / "data" / "voice",
        APP_DIR.parent / "ไฟล์รุ่นพี่" / "october" / "Week 1",
    ]
    files: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        if d.exists():
            for p in d.glob("*.wav"):
                if p.name not in seen:
                    seen.add(p.name)
                    files.append(p)
    return sorted(files, key=lambda p: p.name)


def bubbles_html(turns: list[dict]) -> str:
    rows = []
    for t in turns:
        is_pharm = "เภสัช" in t.get("speaker", "")
        cls = "pharmacist" if is_pharm else "patient"
        ico = "stethoscope" if is_pharm else "person"
        who = "เภสัชกร" if is_pharm else "ผู้ป่วย"
        txt = html.escape(str(t.get("text", "")))
        rows.append(
            f'<div class="bubble-row {cls}">'
            f'<div class="bubble-avatar {cls}">{icon(ico)}</div>'
            f'<div class="bubble-content {cls}"><div class="bubble-speaker-tag">{who}</div>'
            f"<div>{txt}</div></div></div>"
        )
    return '<div class="chat-stream">' + "".join(rows) + "</div>"


def pills_html(changes: list[dict]) -> str:
    if not changes:
        return ""
    valid_pills = []
    seen = set()
    for c in changes:
        tier = c.get("tier", "")
        orig = str(c.get("original", "")).strip()
        corr = str(c.get("corrected", "")).strip()
        # Don't show technical unicode or loop cleanup as drug pills
        if tier in ("0-loop", "0-unicode") and any(k in orig for k in ("U+FFFD", "สระลอย", "วรรณยุกต์", "วนลูป")):
            continue
        if not orig or not corr or orig == corr:
            continue
        # Guard against raw regex artifacts
        if "(?" in orig or "\\" in corr:
            continue
        key = (orig, corr)
        if key in seen:
            continue
        seen.add(key)
        valid_pills.append(
            f'<span class="drug-pill"><span class="original-wrong">{html.escape(orig)}</span>'
            f'<span class="arrow-sep">&rarr;</span>'
            f'<span class="corrected-right">{html.escape(corr)}</span></span>'
        )
    if not valid_pills:
        return ""
    pills = "".join(valid_pills)
    return f'<div class="pill-section"><div class="pill-title">คำที่แก้</div>{pills}</div>'


def _fmt_emr_val(val: object) -> str:
    if isinstance(val, list):
        s = "\n".join(f"- {x}" for x in val if str(x).strip())
    elif isinstance(val, dict):
        s = json.dumps(val, ensure_ascii=False)
    else:
        s = str(val or "").strip()
    return s if s else "-"


def emr_summary_html(emr_data: dict, model_title: str = "") -> str:
    if not emr_data:
        return '<div class="emr-empty-box">ยังไม่มีข้อมูลเวชระเบียน</div>'

    allergy = _fmt_emr_val(emr_data.get("ประวัติการแพ้ยา", "-"))
    underlying = _fmt_emr_val(emr_data.get("โรคประจำตัว", "-"))
    prev_meds = _fmt_emr_val(emr_data.get("ประวัติการใช้ยา") or emr_data.get("ประวัติการจ่ายยา") or "-")
    assessment = _fmt_emr_val(emr_data.get("บันทึกทางการแพทย์") or emr_data.get("บันทึกการแพทย์") or "-")
    advice = _fmt_emr_val(emr_data.get("คำแนะนำจากเภสัชกร") or emr_data.get("คำแนะนำจากเภสัช") or "-")

    # Allergies styling
    is_allergy_free = allergy in ("-", "ไม่มี", "ปฏิเสธ", "ปฏิเสธประวัติแพ้ยา", "ไม่มีประวัติการแพ้ยา", "ไม่แพ้")
    allergy_cls = "emr-badge-safe" if is_allergy_free else "emr-badge-alert"
    if is_allergy_free:
        allergy_val_html = (
            f'<span class="emr-tag {allergy_cls}">{icon("verified")} ปฏิเสธประวัติแพ้ยา</span>'
            if allergy != "-" else '<span class="emr-tag-empty">-</span>'
        )
    else:
        allergy_val_html = f'<span class="emr-tag {allergy_cls}">{icon("warning")} {html.escape(allergy)}</span>'

    # Underlying condition styling
    is_underlying_none = underlying in ("-", "ไม่มี", "ปฏิเสธ", "ไม่มีโรคประจำตัว")
    underlying_cls = "emr-badge-safe" if is_underlying_none else "emr-badge-info"
    if is_underlying_none:
        underlying_val_html = (
            f'<span class="emr-tag {underlying_cls}">{icon("check_circle")} ไม่มีโรคประจำตัว</span>'
            if underlying != "-" else '<span class="emr-tag-empty">-</span>'
        )
    else:
        underlying_val_html = f'<span class="emr-tag {underlying_cls}">{icon("vital_signs")} {html.escape(underlying)}</span>'

    header_sub = f'<span class="emr-model-tag">{html.escape(model_title)}</span>' if model_title else ''

    return (
        f'<div class="emr-summary-card">'
        f'<div class="emr-summary-head">'
        f'<div class="emr-head-title">{icon("clinical_notes")}<span>เวชระเบียนคลินิก (EMR Summary)</span></div>'
        f'{header_sub}'
        f'</div>'
        f'<div class="emr-quick-row">'
        f'<div class="emr-quick-item">'
        f'<div class="emr-quick-label">{icon("warning")} ประวัติการแพ้ยา</div>'
        f'<div class="emr-quick-val">{allergy_val_html}</div>'
        f'</div>'
        f'<div class="emr-quick-item">'
        f'<div class="emr-quick-label">{icon("cardiology")} โรคประจำตัว</div>'
        f'<div class="emr-quick-val">{underlying_val_html}</div>'
        f'</div>'
        f'</div>'
        f'<div class="emr-box-row">'
        f'<div class="emr-box-label">{icon("medication")} ประวัติการใช้ยา / ยาเดิม</div>'
        f'<div class="emr-box-val {"empty" if prev_meds == "-" else ""}">{html.escape(prev_meds)}</div>'
        f'</div>'
        f'<div class="emr-box-row assessment">'
        f'<div class="emr-box-label">{icon("stethoscope")} บันทึกทางการแพทย์ (อาการสำคัญ & การซักประวัติ)</div>'
        f'<div class="emr-box-val {"empty" if assessment == "-" else ""}">{html.escape(assessment).replace(chr(10), "<br>")}</div>'
        f'</div>'
        f'<div class="emr-box-row plan">'
        f'<div class="emr-box-label">{icon("prescriptions")} คำแนะนำจากเภสัชกร & รายการยาที่จ่าย (Plan & Sig)</div>'
        f'<div class="emr-box-val {"empty" if advice == "-" else ""}">{html.escape(advice).replace(chr(10), "<br>")}</div>'
        f'</div>'
        f'</div>'
    )


def model_header(model_type: str, title: str, latency: float) -> str:
    return (
        f'<div class="arena-header {model_type}"><span>{title}</span>'
        f'<span class="lat-chip">{latency} วินาที</span></div>'
    )


def text_block(text: str, key: str, height: int = 260) -> None:
    st.text_area("ข้อความ", value=text, height=height, label_visibility="collapsed", key=key)


preset_files = scan_audio_files()
cached_cases = len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR (Pharmacist Portal Light Glass Style)
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
          <div class="sidebar-logo-wrap">
            <span class="material-symbols-rounded" style="font-size:2rem;color:#fff;">local_hospital</span>
          </div>
          <div class="sidebar-brand-text">
            <div class="sidebar-brand-title">PharmaLog AI</div>
            <div class="sidebar-brand-sub">ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ (AI Lab)</div>
          </div>
        </div>
        <div class="sidebar-divider"></div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='sidebar-section-label'>แสดงผลโมเดล</div>", unsafe_allow_html=True)
    stt_choice = st.radio(
        "แสดงผลโมเดล",
        ["เทียบ 2 โมเดล", "Typhoon Large v3", "Typhoon Realtime"],
        label_visibility="collapsed",
    )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown("<div class='sidebar-section-label'>ฟังก์ชันหลังถอดเสียง</div>", unsafe_allow_html=True)
    toggle_dict = st.toggle(
        "แก้คำศัพท์ยา", value=True,
        help="แก้ชื่อยาและหน่วยที่ถอดเพี้ยน เช่น Setifisine เป็น Cetirizine, เมตร เป็น เม็ด",
    )
    toggle_roles = st.toggle(
        "แยกผู้พูด", value=True,
        help="ระบุว่าประโยคไหนเป็นของเภสัชกรหรือผู้ป่วย",
    )
    toggle_format = st.toggle(
        "จัดเป็นแชต", value=True,
        help="แสดงเป็นกล่องข้อความสลับซ้าย-ขวา (ต้องเปิด แยกผู้พูด ด้วย)",
    )

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown(
        '<span class="sidebar-status"><span class="sidebar-status-dot dot-green"></span>ระบบพร้อมใช้งาน (Local Engine)</span>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="sidebar-metrics">
          <div class="sidebar-metric">
            <span class="material-symbols-rounded" style="font-size:1.1rem;">audio_file</span>
            <span>{len(preset_files)} ไฟล์เสียงในคลัง</span>
          </div>
          <div class="sidebar-metric">
            <span class="material-symbols-rounded" style="font-size:1.1rem;">description</span>
            <span>{cached_cases} เคสในแคช</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  HEADER & TOP STATUS BANNER (Pharmacist Portal Style)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    """
    <div class="page-header">
      <span class="material-symbols-rounded page-header-icon">local_hospital</span>
      <div>
        <h2 class="page-title">PharmaLog AI Lab — ทดสอบถอดเสียงและวิเคราะห์เวชระเบียน</h2>
        <p class="page-subtitle">ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ (Speech-to-Text & Clinical EMR Benchmark)</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st_col1, st_col2, st_col3 = st.columns([2.2, 1, 1], gap="small")
with st_col1:
    st.markdown(
        '<div class="record-status-banner ok"><span class="material-symbols-rounded">check_circle</span>'
        '<span>ระบบประมวลผลพร้อมใช้งาน (5-Layer Pharmacy Dict + Hybrid 4-Stage Role Diarization)</span></div>',
        unsafe_allow_html=True,
    )
with st_col2:
    st.markdown(
        f'<div class="record-mini-stat"><span class="label">คลังเสียงตัวอย่าง</span><strong>{len(preset_files)} ไฟล์</strong></div>',
        unsafe_allow_html=True,
    )
with st_col3:
    st.markdown(
        f'<div class="record-mini-stat"><span class="label">แคชประมวลผลแล้ว</span><strong>{cached_cases} เคส</strong></div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
tab_stt, tab_emr = st.tabs(["1  ถอดเสียงสนทนา (Speech-to-Text)", "2  วิเคราะห์เวชระเบียน (EMR)"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1: SPEECH-TO-TEXT
# ══════════════════════════════════════════════════════════════════════════════
selected_audio_bytes: bytes | None = None
selected_filename = ""

with tab_stt:
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="card-accent-bar accent-blue"></div>
            <div class="section-header">
              <div class="sh-icon sh-blue"><span class="material-symbols-rounded">graphic_eq</span></div>
              <span class="section-title">เลือกหรือบันทึกไฟล์เสียงสนทนา</span>
              <span class="section-sub">{len(preset_files)} ไฟล์ในคลัง</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        source_mode = st.segmented_control(
            "แหล่งไฟล์เสียง",
            ["คลังเสียง", "อัดเสียง", "อัปโหลด"],
            default="คลังเสียง",
            label_visibility="collapsed",
            key="audio_source_mode",
        ) or "คลังเสียง"

        if source_mode == "คลังเสียง":
            if preset_files:
                labels = [f"{p.name}  ·  {round(p.stat().st_size / 1024)} KB" for p in preset_files]
                idx = st.selectbox(
                    "ไฟล์เสียง",
                    range(len(preset_files)),
                    format_func=lambda i: labels[i],
                    label_visibility="collapsed",
                    key="preset_audio_select",
                )
                chosen = preset_files[idx]
                selected_audio_bytes = chosen.read_bytes()
                selected_filename = chosen.name
            else:
                st.info("ไม่พบไฟล์เสียงในเครื่อง")
        elif source_mode == "อัดเสียง":
            live = st.audio_input("อัดเสียง", label_visibility="collapsed", key="live_audio_input")
            if live:
                selected_audio_bytes = live.read()
                selected_filename = f"live_record_{int(time.time())}.wav"
            else:
                st.caption("กดปุ่มไมโครโฟนด้านบนเพื่อเริ่มบันทึกเสียงสนทนาสด")
        else:
            up = st.file_uploader("ไฟล์เสียง", type=["wav", "mp3", "m4a"], label_visibility="collapsed")
            if up:
                selected_audio_bytes = up.read()
                selected_filename = up.name
            else:
                st.caption("ลากไฟล์เสียงมาวาง หรือกด Browse files เพื่ออัปโหลด")

        if selected_audio_bytes:
            cur_hash = get_audio_hash(selected_audio_bytes)
            is_cached = get_cached_result(cur_hash) is not None
            c_audio, c_state, c_btn = st.columns([2.2, 1, 1.3], gap="medium", vertical_alignment="center")
            with c_audio:
                st.audio(selected_audio_bytes, format="audio/wav")
            with c_state:
                if is_cached:
                    st.markdown(f'<span class="status-chip ok">{icon("bolt")}แคชแล้ว</span>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<span class="status-chip new">{icon("fiber_new")}ไฟล์ใหม่</span>', unsafe_allow_html=True)
            with c_btn:
                run_btn = st.button(
                    "วิเคราะห์", icon=":material/play_arrow:", type="primary",
                    use_container_width=True, key="run_stt",
                )

            if run_btn or is_cached:
                if is_cached:
                    st.session_state["active_pipeline_data"] = get_cached_result(cur_hash)
                else:
                    with st.spinner("กำลังประมวลผล…"):
                        st.session_state["active_pipeline_data"] = process_audio_full_pipeline(
                            selected_audio_bytes, filename=selected_filename
                        )
                st.session_state["active_filename"] = selected_filename
                st.session_state["active_hash"] = cur_hash

    cur_h = get_audio_hash(selected_audio_bytes) if selected_audio_bytes else None
    data = (
        st.session_state.get("active_pipeline_data")
        if (selected_audio_bytes and st.session_state.get("active_hash") == cur_h)
        else None
    )

    if not data:
        msg = "บันทึกเสียงด้านบนเพื่อเริ่ม" if source_mode == "อัดเสียง" else (
            "อัปโหลดไฟล์เสียงด้านบนเพื่อเริ่ม" if source_mode == "อัปโหลด" else "เลือกไฟล์เสียงด้านบนเพื่อเริ่ม"
        )
        st.markdown(
            f'<div class="empty-state">{icon("graphic_eq")}<div>{msg}</div></div>',
            unsafe_allow_html=True,
        )
    else:
        ty_pack = resolve_output_by_toggles(data["typhoon"], toggle_dict, toggle_roles, toggle_format)
        lg_pack = resolve_output_by_toggles(data["typhoon_large"], toggle_dict, toggle_roles, toggle_format)

        def chip(label: str, on: bool) -> str:
            return f'<span class="chip {"on" if on else "off"}">{label}</span>'

        view_active, view_steps = st.tabs(["ผลลัพธ์", "ทีละขั้น"])

        # ── Active view ──
        with view_active:
            st.markdown(
                '<div class="chip-row">'
                + chip("แก้คำยา", toggle_dict)
                + chip("แยกผู้พูด", toggle_roles)
                + chip("จัดเป็นแชต", toggle_format)
                + ("<span class='chip-hint'>ปิดทุกอย่าง = ข้อความดิบจากโมเดล</span>"
                   if not (toggle_dict or toggle_roles or toggle_format) else "")
                + "</div>",
                unsafe_allow_html=True,
            )

            def render_active(pack: dict, latency: float, mtype: str, title: str) -> None:
                st.markdown(model_header(mtype, title, latency), unsafe_allow_html=True)
                with st.container(border=True, key=f"arena_body_{mtype}"):
                    content = pack["display_content"]
                    if pack["display_mode"] == "turns" and isinstance(content, list) and content:
                        st.markdown(bubbles_html(content), unsafe_allow_html=True)
                    else:
                        text_block(
                            content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                            key=f"active_text_{mtype}", height=320,
                        )
                    st.markdown(pills_html(pack.get("active_changes", [])), unsafe_allow_html=True)

            if stt_choice == "เทียบ 2 โมเดล":
                cl, cr = st.columns(2, gap="large")
                with cl:
                    render_active(lg_pack, data["typhoon_large"]["latency"], "typhoon_large", "Typhoon Whisper Large v3")
                with cr:
                    render_active(ty_pack, data["typhoon"]["latency"], "typhoon", "Typhoon Realtime")
            elif stt_choice == "Typhoon Large v3":
                render_active(lg_pack, data["typhoon_large"]["latency"], "typhoon_large", "Typhoon Whisper Large v3")
            else:
                render_active(ty_pack, data["typhoon"]["latency"], "typhoon", "Typhoon Realtime")

        # ── Step by step ──
        with view_steps:
            stage = st.segmented_control(
                "ขั้นตอน",
                ["0 ดิบ", "1 แก้คำยา", "2 แยกผู้พูด", "3 จัดเป็นแชต", "4 เวชระเบียน EMR"],
                default="0 ดิบ",
                label_visibility="collapsed",
                key="stage_pick",
            ) or "0 ดิบ"
            captions = {
                "0 ดิบ": "ข้อความตรงจากโมเดลเสียง",
                "1 แก้คำยา": "แก้ชื่อยาและหน่วยด้วยพจนานุกรม 5-Layer",
                "2 แยกผู้พูด": "ระบุเภสัชกร / ผู้ป่วย (Hybrid 4-Stage)",
                "3 จัดเป็นแชต": "จัดเป็นบทสนทนาสลับฝั่ง",
                "4 เวชระเบียน EMR": "สรุปเวชระเบียนคลินิกอัตโนมัติ (Clinical EMR)",
            }
            st.caption(captions[stage])

            def stage_body(model_key: str, mtype: str, title: str) -> None:
                d = data[model_key]
                if stage == "0 ดิบ":
                    text_block(d["stage_0_raw"], key=f"st0_{mtype}")
                elif stage == "1 แก้คำยา":
                    text_block(d["stage_1_dict"], key=f"st1_{mtype}")
                    st.markdown(pills_html(d.get("dict_changes", [])) or "<span class='chip-hint'>ไม่พบคำที่ต้องแก้</span>",
                                unsafe_allow_html=True)
                elif stage == "2 แยกผู้พูด":
                    text_block(d["stage_2_role"], key=f"st2_{mtype}", height=300)
                elif stage == "3 จัดเป็นแชต":
                    turns = d["stage_3_dialogue"]
                    if turns:
                        st.markdown(bubbles_html(turns), unsafe_allow_html=True)
                    else:
                        st.markdown("<span class='chip-hint'>ไม่มีบทสนทนา</span>", unsafe_allow_html=True)
                else:
                    emr_obj = d.get("stage_4_emr", {})
                    st.markdown(emr_summary_html(emr_obj, title), unsafe_allow_html=True)
                    if emr_obj:
                        pdf_s4 = generate_emr_pdf(
                            emr_data=emr_obj,
                            model_name=title,
                            record_id=cur_h or "",
                            dialogue_turns=d.get("stage_3_dialogue", []),
                        )
                        if pdf_s4:
                            st.download_button(
                                f"ดาวน์โหลดเวชระเบียน PDF ({title})",
                                data=pdf_s4,
                                file_name=f"EMR_{(cur_h or 'case')[:8]}_{mtype}.pdf",
                                mime="application/pdf",
                                icon=":material/picture_as_pdf:",
                                use_container_width=True,
                                key=f"dl_pdf_s4_{mtype}",
                            )

            def render_step_col(model_key: str, mtype: str, title: str) -> None:
                st.markdown(model_header(mtype, title, data[model_key]["latency"]), unsafe_allow_html=True)
                with st.container(border=True, key=f"step_body_{mtype}"):
                    stage_body(model_key, mtype, title)

            if stt_choice == "เทียบ 2 โมเดล":
                sl, sr = st.columns(2, gap="large")
                with sl:
                    render_step_col("typhoon_large", "typhoon_large", "Typhoon Whisper Large v3")
                with sr:
                    render_step_col("typhoon", "typhoon", "Typhoon Realtime")
            elif stt_choice == "Typhoon Large v3":
                render_step_col("typhoon_large", "typhoon_large", "Typhoon Whisper Large v3")
            else:
                render_step_col("typhoon", "typhoon", "Typhoon Realtime")

        # ── Word & Floating Vowel Fixer ──
        with st.expander("จัดการคำศัพท์ & แก้สระลอย (Word & Vowel Fixer)", expanded=False, icon=":material/spellcheck:"):
            st.markdown(
                '<div style="font-size: 0.92rem; color: #475569; margin-bottom: 0.75rem;">'
                'ระบบตรวจจับสระลอยและข้อผิดพลาด Unicode อัตโนมัติใน Stage 1 '
                'ท่านสามารถเพิ่มคำศัพท์เฉพาะทาง หรือคำที่โมเดลฟังเพี้ยน เพื่อให้ระบบแทนที่และปรับปรุงบทสนทนาทันที'
                '</div>',
                unsafe_allow_html=True,
            )
            c_w1, c_w2, c_btn = st.columns([2, 2, 1.5], gap="medium", vertical_alignment="bottom")
            with c_w1:
                new_wrong = st.text_input("คำที่ถอดเสียงผิด (เช่น ขมุดขมุด)", key="add_wrong_word")
            with c_w2:
                new_right = st.text_input("คำที่ถูกต้อง (เช่น ขวดละ)", key="add_right_word")
            with c_btn:
                if st.button("เพิ่มคำ & อัปเดต", icon=":material/add_circle:", type="primary", use_container_width=True, key="btn_add_custom_word"):
                    if new_wrong and new_right:
                        add_custom_word(new_wrong, new_right)
                        with st.spinner("กำลังอัปเดตบทสนทนา…"):
                            st.session_state["active_pipeline_data"] = rebuild_cached_pipeline(cur_h)
                        st.toast("เพิ่มคำศัพท์และอัปเดตบทสนทนาเรียบร้อย")
                        st.rerun()

            c_act1, c_act2 = st.columns([1, 1], gap="medium")
            with c_act1:
                if st.button("ล้างสระลอย & ซิงก์พจนานุกรมทันที", icon=":material/sync:", use_container_width=True, key="btn_sync_dict"):
                    with st.spinner("กำลังล้างสระลอยและปรับปรุงคำศัพท์…"):
                        st.session_state["active_pipeline_data"] = rebuild_cached_pipeline(cur_h)
                    st.toast("ล้างสระลอยและปรับปรุงคำศัพท์เรียบร้อย")
                    st.rerun()

            custom_words = load_custom_dict()
            if custom_words:
                st.caption(f"คำศัพท์กำหนดเอง ({len(custom_words)} คำ):")
                for w_wrong, w_right in list(custom_words.items()):
                    cw_col1, cw_col2, cw_del = st.columns([3, 3, 1], gap="small", vertical_alignment="center")
                    with cw_col1:
                        st.markdown(f"<code>{html.escape(w_wrong)}</code>", unsafe_allow_html=True)
                    with cw_col2:
                        st.markdown(f"&rarr; <b>{html.escape(w_right)}</b>", unsafe_allow_html=True)
                    with cw_del:
                        if st.button("ลบ", key=f"del_cw_{w_wrong}", icon=":material/delete:"):
                            remove_custom_word(w_wrong)
                            st.session_state["active_pipeline_data"] = rebuild_cached_pipeline(cur_h)
                            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2: EMR MODEL COMPARISON
# ══════════════════════════════════════════════════════════════════════════════
with tab_emr:
    emr_text = ""

    with st.container(border=True):
        st.markdown(
            """
            <div class="card-accent-bar accent-blue"></div>
            <div class="section-header">
              <div class="sh-icon sh-blue"><span class="material-symbols-rounded">chat</span></div>
              <span class="section-title">บทสนทนาต้นทาง (Transcript Source)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        src_mode = st.radio(
            "แหล่งบทสนทนา",
            ["ผลถอดเสียง", "ไฟล์เฉลย", "พิมพ์เอง"],
            horizontal=True,
            label_visibility="collapsed",
            key="emr_src_mode",
        )

        if src_mode == "ผลถอดเสียง":
            if not data:
                st.info("ยังไม่มีผลถอดเสียง ไปแท็บ ถอดเสียง ก่อน หรือเลือกแหล่งอื่น")
            else:
                which = st.radio("โมเดลถอดเสียง", ["Typhoon Large v3", "Typhoon Realtime"], horizontal=True,
                                 label_visibility="collapsed", key="emr_stt_which")
                mk = "typhoon_large" if which == "Typhoon Large v3" else "typhoon"
                pack_e = resolve_output_by_toggles(data[mk], toggle_dict, toggle_roles, toggle_format)
                ce = pack_e["display_content"]
                emr_text = emr.turns_to_text(ce) if isinstance(ce, list) else str(ce or "")
                if emr_text.strip().startswith("("):
                    st.warning("ผลถอดเสียงนี้เป็นข้อความข้อผิดพลาด")
                    emr_text = ""
                else:
                    st.caption("ใช้ตามสวิตช์ด้านซ้าย")

                cached_emr = data[mk].get("stage_4_emr")
                curr_thash = emr.text_hash(emr_text) if emr_text else ""
                stored_thash = st.session_state.get("emr_results", {}).get("thash", "")
                if cached_emr and isinstance(cached_emr, dict) and curr_thash and (not st.session_state.get("emr_results") or stored_thash != curr_thash):
                    st.session_state["emr_results"] = {
                        "thash": curr_thash,
                        "results": [
                            {
                                "provider": "groq",
                                "label": f"Groq ({which})",
                                "model": "openai/gpt-oss-120b",
                                "from_cache": True,
                                "ok": True,
                                "error": "",
                                "latency": round(data[mk].get("latency", 0.0), 2),
                                "fields": cached_emr,
                                "score": emr.score_result(cached_emr),
                            }
                        ],
                    }

        elif src_mode == "ไฟล์เฉลย":
            gt_files = emr.list_ground_truth()
            if not gt_files:
                st.info("ไม่พบไฟล์เฉลยใน ground_truth/")
            else:
                matched = emr.match_ground_truth(selected_filename)
                default_idx = gt_files.index(matched) if matched in gt_files else 0
                gi = st.selectbox(
                    "ไฟล์เฉลย",
                    range(len(gt_files)),
                    index=default_idx,
                    format_func=lambda i: gt_files[i].stem + ("  [ตรงกับไฟล์เสียง]" if gt_files[i] == matched else ""),
                    label_visibility="collapsed",
                    key="emr_gt_idx",
                )
                emr_text = emr.read_ground_truth(gt_files[gi])
        else:
            emr_text = st.text_area(
                "บทสนทนา", height=150, placeholder="เภสัชกร: …\nผู้ป่วย: …",
                label_visibility="collapsed", key="emr_manual_text",
            )

        if emr_text.strip():
            with st.expander(f"ดูข้อความที่จะส่ง · {len(emr_text)} ตัวอักษร"):
                st.text(emr_text)

    with st.container(border=True):
        st.markdown(
            """
            <div class="card-accent-bar accent-teal"></div>
            <div class="section-header">
              <div class="sh-icon sh-teal"><span class="material-symbols-rounded">assignment</span></div>
              <span class="section-title">เลือกโมเดลประมวลผลเวชระเบียน (EMR Extraction)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        c_mode_left, c_mode_right = st.columns([1.1, 1.5], gap="large", vertical_alignment="top")
        with c_mode_left:
            st.markdown('<div class="ctrl-label">รูปแบบการประมวลผล:</div>', unsafe_allow_html=True)
            mode_choice = st.segmented_control(
                "รูปแบบการประมวลผล",
                ["ประมวลผล 1 โมเดล (เดี่ยว)", "เปรียบเทียบหลายโมเดล"],
                default="ประมวลผล 1 โมเดล (เดี่ยว)",
                label_visibility="collapsed",
                key="emr_mode_choice",
            ) or "ประมวลผล 1 โมเดล (เดี่ยว)"

        emr_jobs: list[dict] = []

        if mode_choice == "ประมวลผล 1 โมเดล (เดี่ยว)":
            with c_mode_right:
                st.markdown('<div class="ctrl-label">เลือกผู้ให้บริการโมเดล:</div>', unsafe_allow_html=True)
                single_pid = st.segmented_control(
                    "ผู้ให้บริการ",
                    list(emr.PROVIDERS.keys()),
                    format_func=lambda pid: emr.PROVIDERS[pid]["label"],
                    default=list(emr.PROVIDERS.keys())[0],
                    label_visibility="collapsed",
                    key="emr_single_pid",
                ) or list(emr.PROVIDERS.keys())[0]

            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)
            spec = emr.PROVIDERS[single_pid]
            with st.container(border=True):
                c_p1, c_p2, c_p3 = st.columns([1.4, 2.1, 1.3], gap="medium", vertical_alignment="center")
                with c_p1:
                    st.markdown(f'<div style="font-weight:800; color:#1E3146; font-size:1rem;">{spec["label"]}</div>', unsafe_allow_html=True)
                    st.caption("โมเดลที่เลือกใช้งาน")
                with c_p2:
                    model_name = st.selectbox(
                        "สถาปัตยกรรมโมเดล",
                        spec["suggestions"],
                        index=0,
                        accept_new_options=True,
                        key=f"emr_single_model_{single_pid}",
                        help="เลือกสถาปัตยกรรมโมเดล หรือพิมพ์ชื่อโมเดลอื่นแล้วกด Enter",
                    )
                with c_p3:
                    saved = emr.load_saved_key(single_pid)
                    typed = st.text_input(
                        "API Key",
                        type="password",
                        key=f"emr_single_key_{single_pid}",
                        placeholder="ใช้ key ในเครื่อง" if saved else "วาง API Key",
                    )
                    if typed:
                        st.markdown("<span class='key-ok'>ใช้ key ที่กรอก</span>", unsafe_allow_html=True)
                    elif saved:
                        st.markdown("<span class='key-ok'>พร้อมใช้งาน</span>", unsafe_allow_html=True)
                    else:
                        st.markdown("<span class='key-miss'>ต้องใส่ key</span>", unsafe_allow_html=True)

                emr_jobs.append({
                    "provider": single_pid,
                    "model": model_name,
                    "api_key": typed.strip() or saved,
                })

        else:
            with c_mode_right:
                st.markdown('<div class="ctrl-label">จำนวนโมเดลที่ต้องการเทียบ:</div>', unsafe_allow_html=True)
                multi_count_choice = st.segmented_control(
                    "จำนวนโมเดลเปรียบเทียบ",
                    ["2 โมเดล (Groq + Gemini)", "3 โมเดล (ทั้งหมด)", "กำหนดเอง"],
                    default="2 โมเดล (Groq + Gemini)",
                    label_visibility="collapsed",
                    key="emr_multi_count_choice",
                ) or "2 โมเดล (Groq + Gemini)"

            st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

            cols = st.columns(len(emr.PROVIDERS), gap="medium")
            for col, (pid, spec) in zip(cols, emr.PROVIDERS.items()):
                with col:
                    with st.container(border=True):
                        if multi_count_choice == "2 โมเดล (Groq + Gemini)":
                            def_val = pid in ("groq", "gemini")
                        elif multi_count_choice == "3 โมเดล (ทั้งหมด)":
                            def_val = True
                        else:
                            def_val = (pid == "groq")

                        on = st.checkbox(spec["label"], value=def_val, key=f"emr_multi_on_{pid}")
                        model_name = st.selectbox(
                            "โมเดล",
                            spec["suggestions"],
                            index=0,
                            accept_new_options=True,
                            key=f"emr_multi_model_{pid}",
                            disabled=not on,
                            label_visibility="collapsed",
                            help="เลือกจากรายการ หรือพิมพ์ชื่อโมเดลอื่นแล้วกด Enter",
                        )
                        saved = emr.load_saved_key(pid)
                        typed = st.text_input(
                            "API Key",
                            type="password",
                            key=f"emr_multi_key_{pid}",
                            disabled=not on,
                            placeholder="ใช้ key ในเครื่อง (หรือวางใหม่)" if saved else "วาง API Key",
                            label_visibility="collapsed",
                        )
                        if typed:
                            st.markdown("<span class='key-ok'>ใช้ key ที่กรอก</span>", unsafe_allow_html=True)
                        elif saved:
                            st.markdown("<span class='key-ok'>พร้อมใช้งาน</span>", unsafe_allow_html=True)
                        else:
                            st.markdown("<span class='key-miss'>ต้องใส่ key</span>", unsafe_allow_html=True)
                        if on:
                            emr_jobs.append({
                                "provider": pid,
                                "model": model_name,
                                "api_key": typed.strip() or saved,
                            })

        b1, b2 = st.columns([1, 1.4], vertical_alignment="center")
        with b1:
            emr_fresh = st.checkbox("รันใหม่ (ไม่ใช้แคช)", value=False, key="emr_fresh")
        with b2:
            num_jobs = len(emr_jobs)
            btn_label = f"ประมวลผล ({num_jobs} โมเดล)" if num_jobs > 1 else "ประมวลผล"
            emr_run = st.button(
                btn_label,
                icon=":material/play_arrow:",
                type="primary",
                use_container_width=True,
                disabled=not (emr_text.strip() and emr_jobs),
                key="emr_run_btn",
            )

    if emr_run:
        with st.spinner(f"กำลังประมวลผล EMR ด้วย {len(emr_jobs)} โมเดล…"):
            st.session_state["emr_results"] = {
                "thash": emr.text_hash(emr_text),
                "results": emr.run_comparison(emr_text, emr_jobs, use_cache=not emr_fresh),
            }

    state = st.session_state.get("emr_results")
    if state:
        results = state["results"]
        ok_results = [r for r in results if r["ok"]]
        fastest = min(ok_results, key=lambda r: r["latency"])["label"] if len(ok_results) > 1 else None
        fullest = max(ok_results, key=lambda r: r["score"]["percent"])["label"] if len(ok_results) > 1 else None

        if len(ok_results) == 1:
            st.markdown('<div class="emr-block-title" style="margin-top: 1.25rem;">ผลการประมวลผลเวชระเบียน (EMR Result)</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="emr-block-title" style="margin-top: 1.25rem;">ผลการประมวลผลและเปรียบเทียบ ({len(ok_results)} โมเดล)</div>', unsafe_allow_html=True)

        card_cols = st.columns(len(results), gap="medium")
        for col, r in zip(card_cols, results):
            with col:
                if not r["ok"]:
                    st.markdown(
                        f"<div class='emr-card err'><div class='emr-card-title'>{html.escape(r['label'])}</div>"
                        f"<div class='emr-card-model'>{html.escape(r['model'])}</div>"
                        f"<div class='emr-err'>{html.escape(r['error'])}</div></div>",
                        unsafe_allow_html=True,
                    )
                    continue
                badges = ""
                if r["label"] == fastest:
                    badges += "<span class='emr-badge fast'>เร็วสุด</span>"
                if r["label"] == fullest:
                    badges += "<span class='emr-badge full'>ครบสุด</span>"
                if r.get("from_cache"):
                    badges += "<span class='emr-badge cache'>แคช</span>"
                s = r["score"]
                st.markdown(
                    f"<div class='emr-card'><div class='emr-card-title'>{html.escape(r['label'])}</div>"
                    f"<div class='emr-card-model'>{html.escape(r['model'])}</div>"
                    f"<div class='emr-badges'>{badges}</div>"
                    f"<div class='emr-stats'><div><b>{r['latency']}</b><small>วินาที</small></div>"
                    f"<div><b>{s['filled']}/{s['total']}</b><small>หัวข้อมีข้อมูล</small></div></div>"
                    f"<div class='emr-bar'><span style='width:{s['percent']}%'></span></div></div>",
                    unsafe_allow_html=True,
                )

        if ok_results:
            st.caption("คะแนนดูแค่ว่ามีข้อมูลหรือไม่ ไม่ได้วัดความถูกต้อง")
            if len(ok_results) == 1:
                r0 = ok_results[0]
                st.markdown(emr_summary_html(r0["fields"], r0["label"]), unsafe_allow_html=True)
            else:
                for field in [f for f in emr.EMR_FIELDS if f != "บทสนทนาที่จัดเรียงแล้ว"]:
                    st.markdown(f"<div class='emr-field-title'>{html.escape(field)}</div>", unsafe_allow_html=True)
                    fc = st.columns(len(ok_results), gap="medium")
                    for col, r in zip(fc, ok_results):
                        val = _fmt_emr_val(r["fields"].get(field, "-"))
                        with col:
                            st.markdown(
                                f"<div class='emr-cell{' empty' if val == '-' else ''}'>"
                                f"<div class='emr-cell-model'>{html.escape(r['label'])}</div>"
                                f"{html.escape(val).replace(chr(10), '<br>')}</div>",
                                unsafe_allow_html=True,
                            )

            with st.expander("บทสนทนาที่จัดเรียง และ JSON ดิบ"):
                tabs_raw = st.tabs([r["label"] for r in ok_results])
                for t, r in zip(tabs_raw, ok_results):
                    with t:
                        st.text(r["fields"].get("บทสนทนาที่จัดเรียงแล้ว", "-"))
                        st.json(r["fields"], expanded=False)

            c_dl_pdf, c_dl_json = st.columns([1, 1], gap="medium")
            with c_dl_pdf:
                if len(ok_results) == 1:
                    primary_r = ok_results[0]
                    emr_payload = dict(primary_r["fields"])
                    if not emr_payload.get("บทสนทนาที่จัดเรียงแล้ว") or emr_payload.get("บทสนทนาที่จัดเรียงแล้ว") == "-":
                        emr_payload["บทสนทนาที่จัดเรียงแล้ว"] = emr_text
                    pdf_data = generate_emr_pdf(
                        emr_data=emr_payload,
                        model_name=primary_r["label"],
                        record_id=state["thash"],
                    )
                    if pdf_data:
                        st.download_button(
                            f"ดาวน์โหลดเวชระเบียน PDF ({primary_r['label']})",
                            data=pdf_data,
                            file_name=f"EMR_{state['thash'][:8]}.pdf",
                            mime="application/pdf",
                            icon=":material/picture_as_pdf:",
                            use_container_width=True,
                            key="emr_dl_pdf",
                        )
                    else:
                        st.caption("ติดตั้ง fpdf2 เพื่อส่งออกไฟล์ PDF (pip install fpdf2)")
                elif len(ok_results) > 1:
                    sel_pdf_model = st.selectbox(
                        "เลือกโมเดลเพื่อดาวน์โหลด PDF",
                        options=[r["label"] for r in ok_results],
                        label_visibility="collapsed",
                        key="sel_pdf_model_key",
                    )
                    target_r = next((r for r in ok_results if r["label"] == sel_pdf_model), ok_results[0])
                    emr_payload = dict(target_r["fields"])
                    if not emr_payload.get("บทสนทนาที่จัดเรียงแล้ว") or emr_payload.get("บทสนทนาที่จัดเรียงแล้ว") == "-":
                        emr_payload["บทสนทนาที่จัดเรียงแล้ว"] = emr_text
                    pdf_data = generate_emr_pdf(
                        emr_data=emr_payload,
                        model_name=target_r["label"],
                        record_id=state["thash"],
                    )
                    if pdf_data:
                        st.download_button(
                            f"ดาวน์โหลดเวชระเบียน PDF ({target_r['label']})",
                            data=pdf_data,
                            file_name=f"EMR_{state['thash'][:8]}_{target_r.get('provider', 'model')}.pdf",
                            mime="application/pdf",
                            icon=":material/picture_as_pdf:",
                            use_container_width=True,
                            key="emr_dl_pdf",
                        )
                    else:
                        st.caption("ติดตั้ง fpdf2 เพื่อส่งออกไฟล์ PDF (pip install fpdf2)")

            with c_dl_json:
                st.download_button(
                    "ดาวน์โหลดผล (JSON)",
                    data=json.dumps(
                        {
                            "conversation_hash": state["thash"],
                            "results": [
                                {k: r.get(k) for k in ("label", "model", "latency", "score", "fields", "ok", "error")}
                                for r in results
                            ],
                        },
                        ensure_ascii=False, indent=2,
                    ),
                    file_name=f"emr_compare_{state['thash']}.json",
                    mime="application/json",
                    icon=":material/download:",
                    use_container_width=True,
                    key="emr_dl",
                )

        for r in results:
            if not r["ok"] and r.get("raw"):
                with st.expander(f"ข้อความดิบจาก {r['label']}"):
                    st.text(r["raw"])
