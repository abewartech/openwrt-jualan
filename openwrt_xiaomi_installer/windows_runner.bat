@echo off
:: ============================================================
:: windows_runner.bat
:: Wrapper to run the OpenWRT Xiaomi Installer on Windows
:: ============================================================

TITLE OpenWRT Xiaomi Auto-Installer

echo.
echo  =====================================================
echo   OpenWRT Auto-Installer for Xiaomi Routers
echo   Windows Launcher
echo  =====================================================
echo.

:: Change to the script directory
cd /d "%~dp0"

:: Check Python is installed
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [ERROR] Python is not installed or not in PATH.
    echo          Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Install/upgrade dependencies
echo  [*] Checking Python dependencies...
python -m pip install -r requirements.txt --quiet
IF ERRORLEVEL 1 (
    echo  [WARNING] Some dependencies may not have installed correctly.
    echo            Run manually: pip install -r requirements.txt
)

echo.
echo  [*] Starting installer...
echo.

:: Run the installer, passing all command-line arguments
python openwrt_installer.py %*

echo.
IF ERRORLEVEL 1 (
    echo  [!] Installer exited with errors (code %ERRORLEVEL%).
    echo      Check the log file for details.
) ELSE (
    echo  [OK] Installer finished.
)

pause
