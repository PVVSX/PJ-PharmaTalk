#!/bin/bash
# PharmaTalk Main Application (Unified App) - One-click Start Script for macOS & Linux

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Starting PharmaTalk Main Application..."
echo "=========================================="

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
