#!/usr/bin/env bash
# PharmaTalk Lab - Standalone Launcher (macOS / Linux)
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "================================================="
echo "   PharmaTalk Lab - Benchmark & Ablation Lab"
echo "================================================="

PORT=8525
python3 -m streamlit run app.py \
    --server.port "$PORT" \
    --server.address 127.0.0.1 \
    --server.headless false \
    --theme.base light \
    --theme.primaryColor "#0284c7" \
    --theme.backgroundColor "#f6f8fb" \
    --theme.secondaryBackgroundColor "#eef2f7" \
    --theme.textColor "#0f172a"
