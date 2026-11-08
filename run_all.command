#!/bin/bash
# PharmaLog AI — ทำทุกขั้นในครั้งเดียว: ติดตั้งส่วนที่ขาด -> เทียบโมเดลถอดเสียง -> เลือกโมเดล -> ทดสอบทั้งระบบ
# ปล่อยหน้าต่างนี้ไว้จนขึ้น ALL_DONE (อาจใช้ 1.5-3 ชั่วโมง) — ไม่มีการเขียนข้อมูลขึ้น Cloud ระหว่างทดสอบ
cd "$(dirname "$0")"
mkdir -p logs
exec > >(tee -a logs/run_all.txt) 2>&1
echo "=== run_all $(date) ==="
source venv/bin/activate || { echo "ยังไม่ได้ติดตั้ง ให้รัน setup_pharmalog.command ก่อน"; read -p "Enter"; exit 1; }
echo "STEP 1/4 install missing packages"
python -c "import uharfbuzz, pycrfsuite, transformers, accelerate" 2>/dev/null || pip install uharfbuzz python-crfsuite transformers accelerate
echo "STEP 2/4 compare STT engines"
caffeinate -i python tests/stt_compare.py
echo "STEP 3/4 choose engine"
python tests/choose_engine.py
set -a; source pharmalog.env; set +a
echo "STEP 4/4 end-to-end test (engine=$PHARMALOG_STT_ENGINE)"
caffeinate -i python tests/e2e_check.py
echo "ALL_DONE $(date)"
read -p "เสร็จทั้งหมดแล้ว กด Enter เพื่อปิด"
