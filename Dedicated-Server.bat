@echo off
rem Optional: run the game server on its own (players then all use JOIN GAME).
cd /d "%~dp0"
python server.py %*
pause
