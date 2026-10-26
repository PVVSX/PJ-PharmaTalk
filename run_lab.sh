#!/bin/bash
# PharmaLog AI Lab: ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์ - One-click Start Script for macOS & Linux

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Starting PharmaLog AI Lab..."
echo " ระบบสรุปบทสนทนาเภสัชกรรมด้วยปัญญาประดิษฐ์"
echo "=========================================="

# 0. Auto-merge if user dragged pharmalog_offline_assets or pharmatalk_offline_assets folder into project
for ASSET_DIR in "pharmalog_offline_assets" "pharmatalk_offline_assets"; do
    if [ -d "$ASSET_DIR" ]; then
        echo "[Info] Detected $ASSET_DIR folder, ensuring files are placed..."
        cp -n "$ASSET_DIR/.groq_api_key" ./ 2>/dev/null || true
        cp -n "$ASSET_DIR/.gemini_api_key" ./ 2>/dev/null || true
        cp -n "$ASSET_DIR/api_keys/.groq_api_key" ./ 2>/dev/null || true
        cp -n "$ASSET_DIR/api_keys/.gemini_api_key" ./ 2>/dev/null || true
        mkdir -p core_api models record lab/cache lab/cache_emr lab/sample_audio
        cp -n "$ASSET_DIR/core_api/serviceAccountKey.json" core_api/ 2>/dev/null || true
        cp -n "$ASSET_DIR/credentials/serviceAccountKey.json" core_api/ 2>/dev/null || true
        cp -n "$ASSET_DIR/models/typhoon-asr-realtime.nemo" models/ 2>/dev/null || true
        cp -n "$ASSET_DIR/core_api/api_queue.db" core_api/ 2>/dev/null || true
        cp -n "$ASSET_DIR/databases/api_queue.db" core_api/ 2>/dev/null || true
        cp -n "$ASSET_DIR/record/pharmatalk.db" record/ 2>/dev/null || true
        cp -n "$ASSET_DIR/databases/pharmatalk.db" record/ 2>/dev/null || true
        cp -n "$ASSET_DIR/record/pharmalog.db" record/ 2>/dev/null || true
        cp -n "$ASSET_DIR/databases/pharmalog.db" record/ 2>/dev/null || true
        cp -rn "$ASSET_DIR/lab/sample_audio"/* lab/sample_audio/ 2>/dev/null || true
    fi
done

# 1. Check & Create Virtual Environment
if [ ! -d "venv" ]; then
    echo "[Info] Creating virtual environment (venv)..."
    python3 -m venv venv
fi

# 2. Activate Virtual Environment
source venv/bin/activate

# 3. Check Dependencies
if ! python -c "import streamlit" 2>/dev/null; then
    echo "[Info] Installing dependencies from lab/requirements.txt..."
    pip install --upgrade pip
    pip install -r lab/requirements.txt
fi

# 4. Check API Key
if [ -f ".groq_api_key" ]; then
    echo "[Pass] Groq API Key detected."
else
    echo "[Warning] .groq_api_key not found. Please extract offline assets zip to project root."
fi

# 5. Launch Streamlit Lab
echo "[Info] Launching Streamlit on port 8525..."
echo "[Info] URL: http://localhost:8525"
streamlit run lab/app.py --server.port 8525
