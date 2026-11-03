@echo off
REM Builds TBS Watermark.exe. Needs Python 3.11+ from python.org (tick "Add to PATH").
cd /d "%~dp0"
python -m pip install -r requirements.txt || goto :err
set ADD=
if exist logo.png set ADD=--add-data "logo.png;."
python -m PyInstaller --noconfirm --onefile --windowed --name "TBS Watermark" --collect-all tkinterdnd2 %ADD% --add-data "fonts;fonts" --add-data "brand.png;." tbs_watermark.py || goto :err
echo.
echo Done. Your app is in the "dist" folder: dist\TBS Watermark.exe
pause
exit /b 0
:err
echo Build failed. See the messages above.
pause
exit /b 1
