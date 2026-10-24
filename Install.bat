@echo off
rem Installs the Python packages the game needs. Run once on every PC.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installing failed. Check your internet connection and try again.
    pause
    exit /b 1
)
echo.
echo All set! Double-click Play.bat to start the game.
pause
