#!/bin/bash
# PharmaLog AI - เปิดระบบทั้งหมด 3 เว็บ + 2 API (ปิดหน้าต่างนี้เพื่อหยุดทุกตัว)
#   Consent (คนไข้)     http://localhost:8500
#   เภสัชกร             http://localhost:8501   (อัดได้เมื่อคนไข้ยินยอม)
#   หลังบ้าน            http://localhost:8515   (อัดได้ทันที ไม่ต้องรอยินยอม)
#   Core API            http://localhost:8080/docs
cd "$(dirname "$0")"
mkdir -p logs
source venv/bin/activate || { echo "ยังไม่ได้ติดตั้ง ให้รัน setup_pharmalog.command ก่อน"; read -p "Enter"; exit 1; }
[ -f pharmalog.env ] && set -a && source pharmalog.env && set +a
export PHARMALOG_STT_ENGINE="${PHARMALOG_STT_ENGINE:-whisper}"
RAM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1073741824 ))
if [ "$PHARMALOG_STT_ENGINE" = "whisper" ] && [ "$RAM_GB" -gt 0 ] && [ "$RAM_GB" -lt 16 ]; then
  echo "คำเตือน: เครื่องนี้มี RAM ${RAM_GB} GB แต่ Typhoon Whisper Large v3 ต้องการ RAM ว่าง ~7 GB (แนะนำเครื่อง 16 GB ขึ้นไป)"
  echo "ถ้าใช้ต่อ เครื่องอาจช้ามากหรือค้าง"
  read -p "พิมพ์ r แล้ว Enter เพื่อใช้ Typhoon Realtime (เบา) แทนในครั้งนี้ หรือกด Enter เพื่อใช้ Whisper ต่อ: " ANS
  [ "$ANS" = "r" ] && export PHARMALOG_STT_ENGINE=realtime
fi
echo "=== start $(date) engine=$PHARMALOG_STT_ENGINE ===" | tee logs/start_log.txt
# ห้ามมีโปรแกรมอื่นใช้พอร์ตเดียวกัน (เช่นเซิร์ฟเวอร์เก่าที่เปิดค้าง) ไม่งั้นเบราว์เซอร์จะไปเปิดโปรแกรมเก่าแทน
BUSY=""
for P in 8500 8080 8501 8515; do
  if lsof -nP -iTCP:$P -sTCP:LISTEN >/dev/null 2>&1; then BUSY="$BUSY $P"; lsof -nP -iTCP:$P -sTCP:LISTEN | tail -n +2 | tee -a logs/start_log.txt; fi
done
if [ -n "$BUSY" ]; then
  echo "พอร์ตต่อไปนี้มีโปรแกรมอื่นใช้อยู่:$BUSY — ปิดโปรแกรมนั้นก่อน (ดู PID ด้านบน แล้วใช้ kill <PID>) แล้วเปิดใหม่"
  read -p "กด Enter เพื่อปิด"; exit 1
fi
python api.py > logs/api.log 2>&1 & P1=$!
(cd core_api && python main.py) > logs/core_api.log 2>&1 & P2=$!
streamlit run pharmacist_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true > logs/pharmacist_app.log 2>&1 & P3=$!
streamlit run unified_app/app.py --server.address 127.0.0.1 --server.port 8515 --server.headless true > logs/unified_app.log 2>&1 & P4=$!
trap 'echo "กำลังปิดระบบ..."; kill $P1 $P2 $P3 $P4 2>/dev/null' EXIT INT TERM
echo "รอโหลดโมเดลถอดเสียง... (ครั้งแรก Whisper ต้องดาวน์โหลด ~6.2 GB อาจนานหลายนาที)"
for i in $(seq 1 900); do
  H=$(curl -s http://127.0.0.1:8080/health)
  if echo "$H" | grep -q '"asr_loaded":true'; then echo "CORE_READY $H" | tee -a logs/start_log.txt; break; fi
  if ! kill -0 $P2 2>/dev/null; then echo "CORE_DIED ดู logs/core_api.log" | tee -a logs/start_log.txt; break; fi
  sleep 2
done
open "http://localhost:8500"; open "http://127.0.0.1:8501"; open "http://127.0.0.1:8515"
echo ""
echo "เปิดแล้ว 3 เว็บ: Consent :8500 | เภสัชกร :8501 | หลังบ้าน :8515"
echo "ปิดหน้าต่างนี้ หรือกด Ctrl+C เพื่อหยุดระบบทั้งหมด"
caffeinate -i -w $P2 &
wait
