#!/bin/bash
# PharmaLog AI - ทดสอบระบบทั้งหมดแบบอัตโนมัติ (ราว 30-60 นาที) — ปิดหน้าต่าง start_pharmalog ก่อนรัน
cd "$(dirname "$0")"
source venv/bin/activate || { echo "รัน setup_pharmalog.command ก่อน"; read -p "Enter"; exit 1; }
[ -f pharmalog.env ] && set -a && source pharmalog.env && set +a
python -c "import uharfbuzz, pycrfsuite, transformers, accelerate" 2>/dev/null || pip install uharfbuzz python-crfsuite transformers accelerate
caffeinate -i python tests/e2e_check.py 2>&1 | tee logs/e2e_console.txt
read -p "ทดสอบเสร็จ กด Enter เพื่อปิด"
