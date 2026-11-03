#!/bin/bash
# Builds "TBS Reel.app". Needs Python 3.11+ from python.org.
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt
python3 -m PyInstaller --noconfirm --windowed --name "TBS Reel" --osx-bundle-identifier com.tbsnews.reel --collect-all tkinterdnd2 --collect-all imageio_ffmpeg --add-data "logo.png:." --add-data "fonts:fonts" --add-data "brand.png:." --add-data "icon.png:." --icon icon.png reel/tbs_reel.py
echo "Done. Your app is in dist/TBS Reel.app"
