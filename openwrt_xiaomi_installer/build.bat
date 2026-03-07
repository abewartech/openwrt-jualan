@echo off
:: ============================================================
:: build.bat
:: Build standalone EXE(s) using PyInstaller
::
:: Usage:
::   build.bat           - Build both CLI and GUI executables
::   build.bat cli       - Build CLI only (openwrt_installer.exe)
::   build.bat gui       - Build GUI only (openwrt_gui.exe)
::   build.bat clean     - Delete dist/ and build/ folders
:: ============================================================

TITLE OpenWRT Installer - EXE Build

echo.
echo  =====================================================
echo   OpenWRT Xiaomi Installer - EXE Builder
echo  =====================================================
echo.

cd /d "%~dp0"

:: ----------------------------------------------------------
:: Handle 'clean' argument
:: ----------------------------------------------------------
IF /I "%1"=="clean" (
    echo  [*] Cleaning build artifacts...
    IF EXIST dist   rmdir /s /q dist
    IF EXIST build  rmdir /s /q build
    echo  [OK] Cleaned.
    goto :EOF
)

:: ----------------------------------------------------------
:: Check Python
:: ----------------------------------------------------------
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [ERROR] Python not found in PATH.
    pause & exit /b 1
)

:: ----------------------------------------------------------
:: Install PyInstaller
:: ----------------------------------------------------------
echo  [*] Installing/updating PyInstaller...
python -m pip install pyinstaller --quiet
IF ERRORLEVEL 1 (
    echo  [ERROR] Failed to install PyInstaller.
    pause & exit /b 1
)

:: Also install UPX for compression if not already present
:: (optional - PyInstaller will skip UPX if not found)
where upx >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [!!] UPX not found - executables will not be compressed.
    echo       Download UPX from https://upx.github.io/ and add to PATH
    echo       for smaller exe size. Continuing without UPX...
)

:: Install project deps so PyInstaller can find them
echo  [*] Installing project dependencies...
python -m pip install -r requirements.txt --quiet

echo.

:: ----------------------------------------------------------
:: Choose what to build
:: ----------------------------------------------------------
SET BUILD_CLI=1
SET BUILD_GUI=1

IF /I "%1"=="cli" SET BUILD_GUI=0
IF /I "%1"=="gui" SET BUILD_CLI=0

:: ----------------------------------------------------------
:: Build CLI exe
:: ----------------------------------------------------------
IF "%BUILD_CLI%"=="1" (
    echo  [*] Building CLI executable (openwrt_installer.exe^)...
    python -m PyInstaller openwrt_installer.spec --noconfirm
    IF ERRORLEVEL 1 (
        echo  [ERROR] CLI build failed!
        pause & exit /b 1
    )
    echo  [OK] CLI build complete.
    echo.
)

:: ----------------------------------------------------------
:: Build GUI exe
:: ----------------------------------------------------------
IF "%BUILD_GUI%"=="1" (
    echo  [*] Building GUI executable (openwrt_gui.exe^)...
    python -m PyInstaller openwrt_gui.spec --noconfirm
    IF ERRORLEVEL 1 (
        echo  [ERROR] GUI build failed!
        pause & exit /b 1
    )
    echo  [OK] GUI build complete.
    echo.
)

:: ----------------------------------------------------------
:: Summary
:: ----------------------------------------------------------
echo  =====================================================
echo   Build Output (dist\)
echo  =====================================================
IF "%BUILD_CLI%"=="1" (
    IF EXIST dist\openwrt_installer.exe (
        FOR %%F IN (dist\openwrt_installer.exe) DO (
            echo   openwrt_installer.exe  %%~zF bytes
        )
    )
)
IF "%BUILD_GUI%"=="1" (
    IF EXIST dist\openwrt_gui.exe (
        FOR %%F IN (dist\openwrt_gui.exe) DO (
            echo   openwrt_gui.exe        %%~zF bytes
        )
    )
)
echo.
echo  [*] Executables are in the dist\ folder.
echo  [*] Copy dist\*.exe + config.yaml to any Windows machine.
echo      No Python installation needed on target machine!
echo.

pause
