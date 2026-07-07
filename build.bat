@echo off
chcp 65001 >nul
echo ============================================
echo   CMW500 BLE TX Test Tool - Build EXE
echo ============================================
echo.

REM Project directory
set "PROJECT_DIR=%~dp0"

REM Try to find Python
set PYTHON_CMD=

python --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python
    goto :found_python
)

py --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=py
    goto :found_python
)

python3 --version >nul 2>&1
if not errorlevel 1 (
    set PYTHON_CMD=python3
    goto :found_python
)

for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
) do (
    if exist %%P (
        set PYTHON_CMD=%%P
        goto :found_python
    )
)

echo [ERROR] Python not found!
echo Please install Python from https://www.python.org/downloads/
echo Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:found_python
echo [INFO] Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

REM Install dependencies
echo [Step 1/3] Installing dependencies...
%PYTHON_CMD% -m pip install -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo.

REM Clean old build
cd /d "%PROJECT_DIR%"
if exist dist rmdir /S /Q dist
if exist build rmdir /S /Q build

REM Build exe with PyInstaller (no spec file, direct command)
echo [Step 2/3] Building exe...
echo.
%PYTHON_CMD% -m PyInstaller main.py --noconfirm --clean --windowed --name CMW500_BLE_Test --add-data "config.yaml;." --hidden-import pyvisa_py --hidden-import pyvisa_py.protocols --hidden-import pyvisa_py.protocols.rpc --hidden-import pyvisa_py.protocols.usb --hidden-import pyvisa_py.protocols.tcpip --hidden-import pyvisa_py.protocols.gpib --hidden-import pyvisa_py.protocols.serial --hidden-import usb --hidden-import usb.core --hidden-import usb.util --hidden-import serial --hidden-import serial.tools
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed
    pause
    exit /b 1
)
echo.

REM Copy config.yaml to output
echo [Step 3/3] Copying config files...
copy /Y "%PROJECT_DIR%config.yaml" "%PROJECT_DIR%dist\CMW500_BLE_Test\config.yaml" >nul

echo.
echo ============================================
echo   Build complete!
echo.
echo   EXE: dist\CMW500_BLE_Test\CMW500_BLE_Test.exe
echo.
echo   Usage:
echo   1. config.yaml is already in the same folder
echo   2. Double-click CMW500_BLE_Test.exe to run
echo ============================================
echo.

start "" explorer "%PROJECT_DIR%dist\CMW500_BLE_Test"

pause
