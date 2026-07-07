@echo off
chcp 65001 >nul
cls
echo ============================================
echo   CMW500 BLE Test Tool - Build EXE
echo ============================================
echo.

REM Project directory
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

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

REM Check PyInstaller
echo [Step 0/4] Checking PyInstaller...
%PYTHON_CMD% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller not found, installing...
    %PYTHON_CMD% -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller is ready.
echo.

REM Install dependencies
echo [Step 1/4] Installing dependencies...
%PYTHON_CMD% -m pip install -r "%PROJECT_DIR%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo.

REM Syntax check
echo [Step 2/4] Syntax check...
%PYTHON_CMD% -m py_compile "%PROJECT_DIR%\main.py" "%PROJECT_DIR%\gui_main.py" "%PROJECT_DIR%\test_executor.py" "%PROJECT_DIR%\data_exporter.py" "%PROJECT_DIR%\instrument_connection.py"
if errorlevel 1 (
    echo [ERROR] Syntax check failed, please fix the errors above.
    pause
    exit /b 1
)
echo [OK] Syntax check passed.
echo.

REM Clean old build
cd /d "%PROJECT_DIR%"
echo [Step 3/4] Cleaning old build directories...
if exist dist rmdir /S /Q dist
if exist build rmdir /S /Q build
echo [OK] Cleaned.
echo.

REM Build exe with PyInstaller spec
echo [Step 4/4] Building exe...
%PYTHON_CMD% -m PyInstaller "%PROJECT_DIR%\build_exe.spec" --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed
    pause
    exit /b 1
)
echo.

REM Verify output
if not exist "%PROJECT_DIR%\dist\CMW500_BLE_Test\CMW500_BLE_Test.exe" (
    echo [ERROR] Output exe not found!
    pause
    exit /b 1
)

REM Copy config.yaml to output (ensure latest config)
echo [INFO] Copying latest config.yaml to output...
copy /Y "%PROJECT_DIR%\config.yaml" "%PROJECT_DIR%\dist\CMW500_BLE_Test\config.yaml" >nul

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

start "" explorer "%PROJECT_DIR%\dist\CMW500_BLE_Test"

pause
