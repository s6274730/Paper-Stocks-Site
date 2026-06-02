#!/usr/bin/env bash
set -e

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install flask cryptography groq yfinance

echo ""
echo "Setup complete. Run the app:"
echo "  source .venv/bin/activate"
echo "  python website.py"
