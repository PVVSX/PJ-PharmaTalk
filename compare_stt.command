#!/bin/bash
# เปรียบเทียบ Typhoon ASR Realtime กับ Typhoon Whisper Large v3 (ใช้เวลานาน ปล่อยทิ้งไว้ได้ รันซ้ำจะทำต่อจากเดิม)
cd "$(dirname "$0")"
source venv/bin/activate || { echo "รัน setup_pharmalog.command ก่อน"; read -p "Enter"; exit 1; }
python -c "import transformers, accelerate" 2>/dev/null || pip install transformers accelerate
caffeinate -i python tests/stt_compare.py 2>&1 | tee -a logs/stt_compare_console.txt
read -p "เสร็จแล้ว กด Enter เพื่อปิด"
