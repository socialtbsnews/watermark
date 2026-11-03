#!/bin/bash
# Builds "TBS Watermark.app". Needs Python 3.11+ from python.org.
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
ADD=()
[ -f logo.png ] && ADD=(--add-data "logo.png:.")
python3 -m PyInstaller --noconfirm --windowed --name "TBS Watermark" --collect-all tkinterdnd2 "${ADD[@]}" tbs_watermark.py
echo "Done. Your app is in dist/TBS Watermark.app"
