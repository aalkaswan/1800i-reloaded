@echo off
setlocal

echo ===============================================================================
echo        PrimeFilm Studio - Standalone Windows .EXE Builder (PyInstaller)
echo ===============================================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3 is required to BUILD the standalone .exe.
    echo Please install Python 3.9+ from https://www.python.org/
    pause
    exit /b 1
)

echo [*] Installing required packaging tools into virtual environment...
python -m pip install --upgrade pip
python -m pip install pyinstaller pyusb libusb-package pillow PySide6

echo.
echo [*] Compiling standalone PrimeFilmStudio.exe...
pyinstaller --clean PrimeFilmStudio.spec

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===============================================================================
    echo [SUCCESS] Standalone executable created: dist\PrimeFilmStudio.exe
    echo This file is fully portable and requires NO Python or dependencies to run!
    echo ===============================================================================
) else (
    echo.
    echo [ERROR] PyInstaller build failed with exit code %ERRORLEVEL%.
)

pause
endlocal
