#!/bin/bash
# Simple runner for btc-hunter
# Usage: TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=... ./run.sh
set -e
python3 -m pip install --quiet -r requirements.txt
python3 btc_v37.py
