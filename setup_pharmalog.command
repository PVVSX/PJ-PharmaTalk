#!/bin/bash
# PharmaLog AI - ติดตั้งและทดสอบระบบ (ดับเบิลคลิกเพื่อรัน)
cd "$(dirname "$0")"
mkdir -p logs
LOG="logs/setup_log.txt"
exec > >(tee "$LOG") 2>&1
echo "=== PharmaLog setup $(date) ==="
sw_vers 2>/dev/null; uname -m

# 1) หา Python ที่เหมาะสม (3.11 > 3.10 > 3.12)
PY=""
for v in 3.11 3.10 3.12; do
  for c in "python$v" "/opt/homebrew/bin/python$v" "/usr/local/bin/python$v" "/Library/Frameworks/Python.framework/Versions/$v/bin/python$v"; do
    if [ -z "$PY" ] && command -v "$c" >/dev/null 2>&1; then PY="$c"; fi
  done
done
if [ -z "$PY" ] && command -v python3 >/dev/null 2>&1; then
  V=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  echo "python3 = $V"
  case "$V" in 3.10|3.11|3.12) PY=python3;; esac
fi
if [ -z "$PY" ]; then
  BREW=""
  for b in brew /opt/homebrew/bin/brew /usr/local/bin/brew; do command -v "$b" >/dev/null 2>&1 && BREW="$b" && break; done
  if [ -n "$BREW" ]; then
    echo "--- ไม่มี Python 3.10-3.12 กำลังติดตั้ง python@3.11 ด้วย Homebrew"
    "$BREW" install python@3.11
    for c in "$("$BREW" --prefix)/bin/python3.11" "$("$BREW" --prefix python@3.11 2>/dev/null)/bin/python3.11"; do
      [ -z "$PY" ] && [ -x "$c" ] && PY="$c"
    done
  fi
fi
echo "PYTHON_SELECTED: ${PY:-NONE}"
if [ -z "$PY" ]; then
  echo "ERROR_NO_PYTHON: ไม่พบ Python 3.10-3.12  ติดตั้งด้วย: brew install python@3.11"
  echo "SETUP_DONE status=no_python"
  read -p "กด Enter เพื่อปิดหน้าต่าง"; exit 1
fi
"$PY" --version

# 2) สร้าง venv
if [ ! -x venv/bin/python ]; then
  echo "--- creating venv"
  "$PY" -m venv venv || { echo "SETUP_DONE status=venv_failed"; read -p "Enter"; exit 1; }
fi
source venv/bin/activate
python -m pip install --upgrade pip wheel setuptools

# 3) ติดตั้งแพ็กเกจหลัก
echo "--- installing base packages"
pip install fastapi uvicorn sqlalchemy python-multipart firebase-admin groq requests \
  streamlit streamlit-autorefresh pythainlp python-crfsuite fpdf2 uharfbuzz soundfile librosa numpy pandas openpyxl matplotlib \
  transformers accelerate
BASE_RC=$?
echo "BASE_INSTALL_RC=$BASE_RC"

# 4) ติดตั้ง PyTorch + NeMo (ใหญ่ ใช้เวลานาน)
echo "--- installing torch + nemo (อาจใช้เวลา 10-20 นาที)"
pip install torch torchaudio
pip install "nemo_toolkit[asr]"
NEMO_RC=$?
echo "NEMO_INSTALL_RC=$NEMO_RC"

# 5) ตรวจ import
echo "--- import check"
python - <<'PYEOF'
import importlib
for m in ["fastapi","uvicorn","sqlalchemy","firebase_admin","groq","streamlit","streamlit_autorefresh","pythainlp","fpdf","torch","nemo.collections.asr"]:
    try:
        mod=importlib.import_module(m); print("IMPORT_OK", m, getattr(mod,"__version__",""))
    except Exception as e:
        print("IMPORT_FAIL", m, type(e).__name__, str(e)[:200])
import torch
print("MPS available:", torch.backends.mps.is_available())
PYEOF

# 6) รันชุดทดสอบ (Typhoon + Groq)
echo "--- running tests/run_tests.py"
python tests/run_tests.py
echo "TESTS_RC=$?"
echo "SETUP_DONE status=finished"
read -p "เสร็จแล้ว กด Enter เพื่อปิดหน้าต่าง"
