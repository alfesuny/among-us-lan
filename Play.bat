@echo off
cd /d "%~dp0"
python -c "import pygame" >nul 2>nul
if errorlevel 1 (
    echo First run: installing the game's Python packages...
    python -m pip install -r requirements.txt
)
python main.py
if errorlevel 1 pause
