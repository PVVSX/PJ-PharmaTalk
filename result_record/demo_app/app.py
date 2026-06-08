# -*- coding: utf-8 -*-
"""Streamlit entrypoint สำหรับ Demo EMR App.

รันจากโฟลเดอร์โปรเจกต์:
  streamlit run demo_app/app.py

ไฟล์นี้เป็น entrypoint ในโฟลเดอร์ demo_app และเรียกใช้ logic หลักจาก
../streamlit_emr_app.py เพื่อไม่ให้โค้ดซ้ำหลายชุด
"""
from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from streamlit_emr_app import main  # noqa: E402


if __name__ == "__main__":
    main()
