@echo off
:: ============================================================
:: windows_runner.bat
:: Wrapper to run the OpenWRT Xiaomi Installer on Windows
::
:: Usage:
::   windows_runner.bat              - CLI installer (auto-detect)
::   windows_runner.bat --gui        - Graphical (tkinter) installer
::   windows_runner.bat --setup      - Run PowerShell setup (admin)
::   windows_runner.bat [any args]   - Passed directly to CLI installer
:: ============================================================

TITLE OpenWRT Xiaomi Auto-Installer

echo.
echo  =====================================================
echo   OpenWRT Auto-Installer for Xiaomi Routers
echo   Windows Launcher  v1.1
echo  =====================================================
echo.

:: Change to the script directory
cd /d "%~dp0"

:: ----------------------------------------------------------
:: Handle --setup flag: delegate to PowerShell setup script
:: ----------------------------------------------------------
IF /I "%1"=="--setup" (
    echo  [*] Launching PowerShell setup (admin elevation required^)...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_setup.ps1"
    exit /b %ERRORLEVEL%
)

:: ----------------------------------------------------------
:: Check Python is installed
:: ----------------------------------------------------------
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [ERROR] Python is not installed or not in PATH.
    echo          Download from: https://www.python.org/downloads/
    echo          Ensure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

:: ----------------------------------------------------------
:: Install/upgrade dependencies
:: ----------------------------------------------------------
echo  [*] Checking Python dependencies...
python -m pip install -r requirements.txt --quiet 2>nul
IF ERRORLEVEL 1 (
    echo  [WARNING] Some dependencies may not have installed correctly.
    echo            Run manually: pip install -r requirements.txt
)

echo.

:: ----------------------------------------------------------
:: Handle --gui flag: launch tkinter GUI
:: ----------------------------------------------------------
IF /I "%1"=="--gui" (
    echo  [*] Launching graphical installer...
    python openwrt_gui.py
    goto :END
)

:: ----------------------------------------------------------
:: Default: run CLI installer, forward all args
:: ----------------------------------------------------------
echo  [*] Starting CLI installer...
echo.
python openwrt_installer.py %*

:END
echo.
IF ERRORLEVEL 1 (
    echo  [!] Installer exited with errors.
    echo      Check the log file for details.
    echo.
    echo  Tip: run "windows_runner.bat --setup" to configure firewall
    echo       rules and verify network adapter settings.
) ELSE (
    echo  [OK] Installer finished successfully.
)

pause
