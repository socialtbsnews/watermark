@echo off
REM Builds TBS Reel.exe. Needs Python 3.11+ from python.org (tick "Add to PATH").
cd /d "%~dp0\.."
python -m pip install -r requirements.txt || goto :err
python -m PyInstaller --noconfirm --onefile --windowed --name "TBS Reel" --collect-all tkinterdnd2 --collect-all imageio_ffmpeg --add-data "logo.png;." --add-data "fonts;fonts" --add-data "brand.png;." --add-data "icon.png;." --icon icon.ico --version-file reel\version_info.txt reel\tbs_reel.py || goto :err
echo.
echo Done. Your app is in the "dist" folder: dist\TBS Reel.exe
pause
exit /b 0
:err
echo Build failed. See the messages above.
pause
exit /b 1
