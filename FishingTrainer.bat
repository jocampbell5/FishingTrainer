@echo off
rem FishingTrainer: double-click to start fishing. In game, Ctrl+Shift pauses and resumes.
rem Close this window to stop. "FishingTrainer.bat check" only checks the setup.
title FishingTrainer
cd /d "%~dp0"
set PYTHONUTF8=1

rem The project's own Python (.venv) if it's there, otherwise the one on your PATH.
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Python wasn't found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH", then start this again.
    pause
    exit /b 1
)

rem Anything missing? The first time, install it (needs the internet once).
"%PY%" -c "import numpy, cv2, mss, keyboard, pyautogui, pydirectinput, win32gui, pycaw" >nul 2>&1
if errorlevel 1 (
    if /i "%~1"=="check" (
        echo Some packages are missing. Start FishingTrainer.bat normally to install them.
        exit /b 1
    )
    echo Installing FishingTrainer's Python packages, one time only...
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Installing failed: see above.
        pause
        exit /b 1
    )
)

if /i "%~1"=="check" (
    echo Ready: "%PY%" has everything FishingTrainer needs.
    exit /b 0
)

"%PY%" main.py
echo.
echo FishingTrainer has stopped.
pause
