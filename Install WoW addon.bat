@echo off
rem Copies the FishingInteract addon into WoW Forever's AddOns folder. Double-click it once
rem (and again after an update), then restart WoW.
title Install the FishingInteract addon
cd /d "%~dp0"
set PYTHONUTF8=1

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo Python wasn't found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH", then start this again.
    pause
    exit /b 1
)

"%PY%" install_addon.py
if not errorlevel 1 goto done

echo.
echo WoW wasn't found in the usual places. Find your WoW folder, open
echo   _forever_\Interface\AddOns
echo inside it, click the address bar at the top, copy it, and paste it here.
set /p "WOW_ADDONS=AddOns folder: "
"%PY%" install_addon.py
if errorlevel 1 (
    echo.
    echo That didn't work: see above.
    pause
    exit /b 1
)

:done
echo.
echo Done. Restart WoW so it loads the addon.
pause
