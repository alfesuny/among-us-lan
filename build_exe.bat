@echo off
rem Builds dist\AmongUsLAN.exe (one file, no Python needed to play). Needs: pip install pyinstaller
cd /d "%~dp0"
python -m PyInstaller --noconfirm --onefile --windowed --name AmongUsLAN ^
  --add-data "Assets;Assets" ^
  --exclude-module pytmx --exclude-module tkinter ^
  main.py
