#!/bin/bash
# PharmaTalk Main Application (Unified App) - One-click Start Script for macOS & Linux

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Starting PharmaTalk Main Application..."
echo "=========================================="

# 0. Auto-merge if user dragged pharmatalk_offline_assets folder into project
if [ -d "pharmatalk_offline_assets" ]; then
    echo "[Info] Detected pharmatalk_offline_assets folder, ensuring files are placed..."
    cp -n pharmatalk_offline_assets/.groq_api_key ./ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/.gemini_api_key ./ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/api_keys/.groq_api_key ./ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/api_keys/.gemini_api_key ./ 2>/dev/null || true
    mkdir -p core_api models record lab/cache lab/cache_emr lab/sample_audio
    cp -n pharmatalk_offline_assets/core_api/serviceAccountKey.json core_api/ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/credentials/serviceAccountKey.json core_api/ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/models/typhoon-asr-realtime.nemo models/ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/core_api/api_queue.db core_api/ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/databases/api_queue.db core_api/ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/record/pharmatalk.db record/ 2>/dev/null || true
    cp -n pharmatalk_offline_assets/databases/pharmatalk.db record/ 2>/dev/null || true
fi

# 1. Check & Create Virtual Environment
if [ ! -d "venv" ]; then
    echo "[Info] Creating virtual environment (venv)..."
    python3 -m venv venv
fi

# 2. Activate Virtual Environment
source venv/bin/activate

# 3. Check Dependencies
if ! python -c "import streamlit, fastapi, firebase_admin" 2>/dev/null; then
    echo "[Info] Installing dependencies for Main Application..."
    pip install --upgrade pip
    pip install streamlit fastapi uvicorn firebase-admin google-cloud-firestore google-cloud-storage reportlab
    pip install -r lab/requirements.txt 2>/dev/null || true
fi

# 4. Check API Key & Credentials
if [ -f ".groq_api_key" ]; then
    echo "[Pass] Groq API Key detected."
else
    echo "[Warning] .groq_api_key not found. Please extract pharmatalk_offline_assets.zip to project root."
fi

# 5. Launch Streamlit Unified App (Back-Office & Testing)
echo "[Info] Launching PharmaTalk Unified App on port 8515..."
echo "[Info] URL: http://localhost:8515"
streamlit run unified_app/app.py --server.port 8515
