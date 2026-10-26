#!/bin/bash
# PharmaTalk Lab - One-click Start Script for macOS & Linux

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Starting PharmaTalk Lab..."
echo "=========================================="

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
    echo "[Warning] .groq_api_key not found. Please extract pharmatalk_offline_assets.zip to project root."
fi

# 5. Launch Streamlit Lab
echo "[Info] Launching Streamlit on port 8525..."
echo "[Info] URL: http://localhost:8525"
streamlit run lab/app.py --server.port 8525
