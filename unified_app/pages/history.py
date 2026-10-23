# -*- coding: utf-8 -*-
"""Page — History (ประวัติข้อมูล Cloud) — v2 Improved UX"""
from __future__ import annotations

import json
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core_api.firebase_config import get_firestore_client
import firebase_admin
from firebase_admin import storage

# ── Constants ────────────────────────────────────────────────────────────────
TZ_BKK = timezone(timedelta(hours=7))
THAI_MONTHS = [
    "", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
]

_COMPLETED_STATUSES = {"COMPLETED"}
_PROCESSING_STATUSES = {"STT_PROCESSING", "EMR_PROCESSING", "STT_DONE"}
_ERROR_STATUSES = {"ERROR", "EMR_ERROR"}


# ── Helpers ──────────────────────────────────────────────────────────────────
def _to_bkk(dt):
    """Convert a datetime to Bangkok timezone (best-effort)."""
    if dt is None:
        return None
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if hasattr(dt, "astimezone"):
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(TZ_BKK)
    except Exception:
        pass
    return dt


def _thai_date(dt) -> str:
    """Format datetime to Thai short date: '13 ต.ค. 2569'."""
    return f"{dt.day} {THAI_MONTHS[dt.month]} {dt.year + 543}"


def _relative_label(dt) -> str:
    """Return relative Thai date label (วันนี้ / เมื่อวาน / Thai date)."""
    today = datetime.now(TZ_BKK).date()
    d = dt.date() if hasattr(dt, "date") else dt
    if d == today:
        return "วันนี้"
    if d == today - timedelta(days=1):
        return "เมื่อวาน"
    return _thai_date(dt)


def _is_record_completed(rec: dict) -> bool:
    return rec.get("status") in _COMPLETED_STATUSES or bool(rec.get("emr_data"))


def _render_record_card(rec: dict) -> None:
    """Render one compact record card with expandable details."""
    task_id = rec["_id"]
    created_at = rec.get("created_at")
    bkk_dt = _to_bkk(created_at)
    time_str = bkk_dt.strftime("%H:%M") if bkk_dt else "--:--"
    ts_full = bkk_dt.strftime("%d/%m/%Y %H:%M:%S") if bkk_dt else "ไม่ระบุเวลา"

    stt_text = rec.get("stt_text", "")
    emr_data = rec.get("emr_data", {})
    audio_filename = rec.get("audio_filename", "")
    task_status = rec.get("status", "")
    has_stt = bool(stt_text)
    has_emr = bool(emr_data)

    # ── Status badge ──
    if has_emr or task_status == "COMPLETED":
        badge = '<span class="status-pill pill-ok"><span class="status-dot dot-green"></span>วิเคราะห์ EMR สมบูรณ์</span>'
    elif task_status in _ERROR_STATUSES:
        badge = '<span class="status-pill pill-err"><span class="status-dot dot-red"></span>ประมวลผลไม่สำเร็จ</span>'
    else:
        badge = '<span class="status-pill pill-warn"><span class="status-dot dot-amber"></span>กำลังประมวลผล...</span>'

    # ── EMR tags (compact key info) ──
    tags_html = ""
    if has_emr and isinstance(emr_data, dict):
        tags = []
        for key in ("อาการสำคัญ", "การวินิจฉัย", "ยาที่จ่าย"):
            val = emr_data.get(key, "")
            if val and val != "-":
                items = val if isinstance(val, list) else [val]
                for v in items[:2]:
                    s = str(v).strip()
                    if s and s != "-":
                        tags.append(s if len(s) < 30 else s[:27] + "...")
        if tags:
            tags_html = '<div class="history-tags">' + "".join(
                f'<span class="history-tag">{t}</span>' for t in tags[:4]
            ) + "</div>"

    # ── STT preview (first ~150 chars) ──
    stt_preview = ""
    if has_stt:
        clean = stt_text.replace(
            "--- ส่วนที่ 1: ข้อความเนื้อหาภาษาไทย ---", ""
        ).strip()
        stt_preview = clean[:150].strip()
        if len(clean) > 150:
            stt_preview += "..."

    # ── Render card ──
    with st.container(border=True):
        h1, h2 = st.columns([2.5, 1.2])
        with h1:
            st.markdown(f"""
            <div class="history-card-header">
              <span class="material-symbols-rounded history-card-icon">description</span>
              <div>
                <div class="history-file-name">เคส {time_str}</div>
                <div class="history-card-meta">{ts_full} &middot; ID: {task_id[:8]}</div>
              </div>
            </div>""", unsafe_allow_html=True)
        with h2:
            st.markdown(badge, unsafe_allow_html=True)

        # Preview area
        if stt_preview or tags_html:
            html = '<div class="history-preview-area">'
            if stt_preview:
                html += f'<div class="history-stt-preview">{stt_preview}</div>'
            if tags_html:
                html += tags_html
            html += "</div>"
            st.markdown(html, unsafe_allow_html=True)

        # Audio player
        if audio_filename and firebase_admin._apps:
            try:
                bucket = storage.bucket()
                blob = bucket.blob(f"recordings/{audio_filename}")
                if blob.exists():
                    url = blob.generate_signed_url(expiration=timedelta(hours=1))
                    st.audio(url)
                else:
                    st.caption("ไม่มีไฟล์เสียงบน Cloud Storage (หรือระบบกำลังอัปโหลด)")
            except Exception as e:
                st.caption(f"ไม่สามารถโหลดไฟล์เสียงได้: {e}")

        # Expandable: Raw STT
        if has_stt:
            with st.expander("ข้อความถอดเสียงดิบ (ไม่ได้แยกผู้พูด)", expanded=False):
                st.markdown(
                    f"<div style='background:#F8FAFC;padding:15px;border-radius:8px;"
                    f"border:1px solid #E2E8F0;color:#1E293B;font-size:0.95rem;"
                    f"line-height:1.6;'>{stt_text}</div>",
                    unsafe_allow_html=True,
                )

        # Expandable: Dialogue + EMR
        if has_emr:
            dialogue = emr_data.get("บทสนทนาที่จัดเรียงแล้ว")
            if dialogue and dialogue != "-":
                with st.expander("บทสนทนา (AI จัดเรียงใหม่)", expanded=False):
                    lines_html = (
                        "<div style='background:#F8FAFC;padding:15px;border-radius:8px;"
                        "border:1px solid #E2E8F0;color:#1E293B;font-size:0.95rem;"
                        "line-height:1.6;'>"
                    )
                    for line in dialogue.split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        if any(r in line for r in ("เภสัชกร:", "ผู้ป่วย:", "คนไข้:")):
                            lines_html += f"<div style='margin-bottom:4px;'><strong>{line}</strong></div>"
                        else:
                            lines_html += f"<div style='margin-bottom:4px;padding-left:15px;'>{line}</div>"
                    lines_html += "</div>"
                    st.markdown(lines_html, unsafe_allow_html=True)

            with st.expander("ผลวิเคราะห์เวชระเบียน (EMR)", expanded=False):
                if isinstance(emr_data, dict):
                    for key, value in emr_data.items():
                        if key == "บทสนทนาที่จัดเรียงแล้ว":
                            continue
                        st.markdown(f"**{key}**")
                        if isinstance(value, list):
                            for item in value:
                                st.markdown(f"- {item}")
                        else:
                            st.info(str(value))
                else:
                    st.write(emr_data)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE HEADER
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
#  FILTER CONTROLS
# ══════════════════════════════════════════════════════════════════════════════
f1, f2, f3, f4 = st.columns([1.3, 1.5, 1, 0.5])

with f1:
    date_choice = st.selectbox(
        "ช่วงเวลา",
        ["ทั้งหมด", "วันนี้", "7 วันล่าสุด", "30 วันล่าสุด", "กำหนดเอง"],
        index=0,
        label_visibility="collapsed",
        key="hist_date_filter",
    )
with f2:
    search_q = st.text_input(
        "ค้นหา",
        placeholder="ค้นหาชื่อยา, อาการ, เนื้อหา...",
        label_visibility="collapsed",
        key="hist_search",
    )
with f3:
    status_choice = st.selectbox(
        "สถานะ",
        ["ทุกสถานะ", "สำเร็จ", "กำลังประมวลผล", "ผิดพลาด"],
        index=0,
        label_visibility="collapsed",
        key="hist_status_filter",
    )
with f4:
    st.button("โหลดใหม่", icon=":material/refresh:", key="hist_refresh")

# Custom date pickers (only when "กำหนดเอง")
custom_start = custom_end = None
if date_choice == "กำหนดเอง":
    dc1, dc2 = st.columns(2)
    _today = datetime.now(TZ_BKK).date()
    with dc1:
        custom_start = st.date_input("ตั้งแต่วันที่", value=_today - timedelta(days=7), key="hist_d_start")
    with dc2:
        custom_end = st.date_input("ถึงวันที่", value=_today, key="hist_d_end")

st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  FETCH DATA FROM FIRESTORE
# ══════════════════════════════════════════════════════════════════════════════
try:
    query = (
        db.collection("patients_emr")
        .order_by("created_at", direction="DESCENDING")
        .limit(100)
    )
    raw_docs = list(query.stream())
except Exception as e:
    st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")
    raw_docs = []

# Pre-process into dicts
records = []
for doc in raw_docs:
    d = doc.to_dict()
    d["_id"] = doc.id
    records.append(d)

# ══════════════════════════════════════════════════════════════════════════════
#  CLIENT-SIDE FILTERING
# ══════════════════════════════════════════════════════════════════════════════
now_bkk = datetime.now(TZ_BKK)
today_start = now_bkk.replace(hour=0, minute=0, second=0, microsecond=0)

# Date boundaries
date_start = date_end = None
if date_choice == "วันนี้":
    date_start = today_start
elif date_choice == "7 วันล่าสุด":
    date_start = today_start - timedelta(days=7)
elif date_choice == "30 วันล่าสุด":
    date_start = today_start - timedelta(days=30)
elif date_choice == "กำหนดเอง" and custom_start and custom_end:
    date_start = datetime.combine(custom_start, datetime.min.time()).replace(tzinfo=TZ_BKK)
    date_end = datetime.combine(custom_end, datetime.max.time()).replace(tzinfo=TZ_BKK)

filtered: list[dict] = []
for r in records:
    created = r.get("created_at")
    bkk_dt = _to_bkk(created)

    # Date filter
    if date_start and bkk_dt:
        if bkk_dt < date_start:
            continue
    if date_end and bkk_dt:
        if bkk_dt > date_end:
            continue

    # Status filter
    st_val = r.get("status", "")
    if status_choice == "สำเร็จ" and not _is_record_completed(r):
        continue
    elif status_choice == "กำลังประมวลผล" and st_val not in _PROCESSING_STATUSES:
        continue
    elif status_choice == "ผิดพลาด" and st_val not in _ERROR_STATUSES:
        continue

    # Search filter
    if search_q:
        q = search_q.lower()
        stt = (r.get("stt_text") or "").lower()
        emr_str = (
            json.dumps(r.get("emr_data", {}), ensure_ascii=False).lower()
            if r.get("emr_data")
            else ""
        )
        if q not in stt and q not in emr_str and q not in r["_id"].lower():
            continue

    filtered.append(r)

# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY STATS BAR
# ══════════════════════════════════════════════════════════════════════════════
n_total = len(filtered)
n_ok = sum(1 for r in filtered if _is_record_completed(r))
n_proc = sum(1 for r in filtered if r.get("status") in _PROCESSING_STATUSES)
n_err = sum(1 for r in filtered if r.get("status") in _ERROR_STATUSES)

s1, s2, s3, s4 = st.columns(4)
with s1:
    st.markdown(f"""<div class="history-stat-card">
      <div class="history-stat-label"><span class="material-symbols-rounded"
        style="font-size:1rem;vertical-align:middle;margin-right:4px;">folder_open</span>เคสทั้งหมด</div>
      <div class="history-stat-value">{n_total}</div>
    </div>""", unsafe_allow_html=True)
with s2:
    st.markdown(f"""<div class="history-stat-card">
      <div class="history-stat-label"><span class="material-symbols-rounded"
        style="font-size:1rem;vertical-align:middle;margin-right:4px;color:var(--green-500);">check_circle</span>สำเร็จ</div>
      <div class="history-stat-value" style="color:var(--green-600);">{n_ok}</div>
    </div>""", unsafe_allow_html=True)
with s3:
    st.markdown(f"""<div class="history-stat-card">
      <div class="history-stat-label"><span class="material-symbols-rounded"
        style="font-size:1rem;vertical-align:middle;margin-right:4px;color:var(--amber-500);">hourglass_top</span>กำลังประมวลผล</div>
      <div class="history-stat-value" style="color:#B45309;">{n_proc}</div>
    </div>""", unsafe_allow_html=True)
with s4:
    st.markdown(f"""<div class="history-stat-card">
      <div class="history-stat-label"><span class="material-symbols-rounded"
        style="font-size:1rem;vertical-align:middle;margin-right:4px;color:var(--red-500);">error</span>ผิดพลาด</div>
      <div class="history-stat-value" style="color:var(--red-500);">{n_err}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<div style='margin:16px 0;'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
#  GROUPED DISPLAY
# ══════════════════════════════════════════════════════════════════════════════
if not filtered:
    if records:
        st.markdown(f"""
        <div class="record-empty-state" style="min-height:220px;">
          <span class="material-symbols-rounded">filter_alt_off</span>
          <div>ไม่พบข้อมูลที่ตรงกับเงื่อนไขการกรอง (มีข้อมูลทั้งหมด {len(records)} เคสในระบบ)</div>
          <div style="font-size:0.85rem;color:var(--grey-500);margin-top:6px;">ลองเปลี่ยนตัวกรอง "ช่วงเวลา" เป็น "ทั้งหมด" หรือขยายช่วงวันที่</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="record-empty-state" style="min-height:220px;">
          <span class="material-symbols-rounded">cloud_off</span>
          <div>ยังไม่มีข้อมูลประวัติบน Cloud</div>
        </div>""", unsafe_allow_html=True)
else:
    # Build date groups (ordered by most recent first)
    groups: OrderedDict[str, dict] = OrderedDict()
    for r in filtered:
        created = r.get("created_at")
        bkk_dt = _to_bkk(created)
        if bkk_dt:
            key = bkk_dt.strftime("%Y-%m-%d")
            display = _relative_label(bkk_dt)
        else:
            key = "9999-99-99"
            display = "ไม่ระบุวันที่"
        if key not in groups:
            groups[key] = {"display": display, "items": []}
        groups[key]["items"].append(r)

    for _g_key, g_data in groups.items():
        g_display = g_data["display"]
        g_items = g_data["items"]
        g_count = len(g_items)

        # ── Date group header ──
        st.markdown(f"""
        <div class="history-date-header">
          <span class="material-symbols-rounded" style="font-size:1.15rem;">calendar_today</span>
          <span class="history-date-text">{g_display}</span>
          <span class="history-date-badge">{g_count} เคส</span>
        </div>""", unsafe_allow_html=True)

        # ── Cards for this date ──
        for rec in g_items:
            _render_record_card(rec)

        st.markdown("<div style='margin:8px 0;'></div>", unsafe_allow_html=True)
